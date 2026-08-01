"""
Regression tests for data-integrity fixes in modules/las_parser.py and
modules/las_handler.py. Imports the production classes directly (previously
neither module had any tests).

Covered fixes:
  - groupby('DEPTH').median() TypeError crash on pandas 2.x (discrete curves)
  - positive 999.25 removed from COMMON_NULL_VALUES (both modules, identical)
  - int64 null-replacement consistency between parser and handler
  - build_master_depth uses np.linspace (deterministic endpoints, no drift)
  - honest depth-unit detection (no silent M->FT on undetected/feet files)
  - merge report gaps_filled_from records ALL contributing secondary sources
"""

import io
import numpy as np
import pandas as pd
import pytest

from modules.las_parser import LASParser, COMMON_NULL_VALUES as PARSER_NULLS
from modules.las_handler import (
    LASHandler,
    COMMON_NULL_VALUES as HANDLER_NULLS,
    export_merged_las,
    _is_discrete_curve,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def make_las(strt_unit="M", gr_last=60.0):
    """Build a minimal LAS 2.0 document. strt_unit='' => no declared unit."""
    return (
        "~VERSION INFORMATION\n"
        " VERS.                 2.0 : CWLS LAS 2.0\n"
        " WRAP.                  NO : ONE LINE PER DEPTH STEP\n"
        "~WELL INFORMATION\n"
        f" STRT.{strt_unit}    1000.0 : START DEPTH\n"
        f" STOP.{strt_unit}    1002.0 : STOP DEPTH\n"
        f" STEP.{strt_unit}       1.0 : STEP\n"
        " NULL.    -999.25 : NULL VALUE\n"
        " WELL.   TESTWELL : WELL\n"
        "~CURVE INFORMATION\n"
        f" DEPT.{strt_unit}      : DEPTH\n"
        " GR.API      : GAMMA\n"
        "~ASCII\n"
        "1000.0  50.0\n"
        "1001.0  -999.25\n"
        f"1002.0  {gr_last}\n"
    )


class FakeLAS:
    """Duck-typed stand-in for a parsed LAS object for merge tests."""
    def __init__(self, data, well_name="TESTWELL"):
        self.data = data
        self.well_info = {
            "well_name": well_name,
            "depth_unit": "FT",
            "null_value": -999.25,
        }


# --------------------------------------------------------------------------- #
# Null-value list consistency + 999.25 removal
# --------------------------------------------------------------------------- #
def test_null_lists_identical_and_no_positive_999():
    assert PARSER_NULLS == HANDLER_NULLS
    assert 999.25 not in PARSER_NULLS
    assert -999.25 in PARSER_NULLS


def test_parser_keeps_valid_999_and_nulls_declared_sentinel():
    parser = LASParser()
    assert parser.read_las_from_buffer(io.StringIO(make_las("M", gr_last=999.25)))
    gr = parser.data["GR"]
    # -999.25 sentinel row -> NaN; valid 999.25 reading -> preserved.
    assert gr.isna().sum() == 1
    assert np.isclose(gr.dropna().to_numpy(), 999.25, atol=1e-3).any()


# --------------------------------------------------------------------------- #
# Depth-unit honesty
# --------------------------------------------------------------------------- #
def test_meters_are_converted_to_feet():
    parser = LASParser()
    assert parser.read_las_from_buffer(io.StringIO(make_las("M")))
    assert parser.well_info["depth_unit"] == "FT"
    assert parser.well_info["converted_from_meters"] is True
    assert parser.data["DEPTH"].iloc[0] == pytest.approx(1000.0 * 3.28084)


def test_feet_are_not_converted():
    parser = LASParser()
    assert parser.read_las_from_buffer(io.StringIO(make_las("F")))
    assert parser.well_info["converted_from_meters"] is False
    assert parser.data["DEPTH"].iloc[0] == pytest.approx(1000.0)


def test_undetected_unit_is_not_converted_and_warns():
    parser = LASParser()
    assert parser.read_las_from_buffer(io.StringIO(make_las("")))
    assert parser.depth_unit_detected is False
    assert parser.depth_unit_warning is not None
    # No silent conversion: depth left unchanged.
    assert parser.data["DEPTH"].iloc[0] == pytest.approx(1000.0)
    assert parser.well_info["converted_from_meters"] is False


def test_latin1_buffer_decodes_and_flags_encoding_fallback():
    parser = LASParser()
    content = make_las("F").replace("TESTWELL", "WÉLL")

    assert parser.read_las_from_buffer(io.BytesIO(content.encode("latin-1")))
    assert parser.well_info["well_name"] == "WÉLL"
    assert parser.encoding_warning is True


def test_nonnumeric_null_header_does_not_crash():
    parser = LASParser()
    # Header NULL blank -> guarded to default -999.25 instead of raising.
    las = make_las("M").replace(" NULL.    -999.25 : NULL VALUE\n",
                                " NULL.          : NULL VALUE\n")
    assert parser.read_las_from_buffer(io.StringIO(las))
    assert parser.null_value == pytest.approx(-999.25)


def test_find_curve_by_type_uses_class_aliases():
    parser = LASParser()
    assert parser.read_las_from_buffer(io.StringIO(make_las("M")))
    assert "CURVE_ALIASES" in vars(LASParser)  # class-level constant
    assert parser.find_curve_by_type("GR") == "GR"
    assert parser.find_curve_by_type("RHOB") is None


# --------------------------------------------------------------------------- #
# normalize_las_dataframe: groupby crash + null handling
# --------------------------------------------------------------------------- #
def test_duplicate_depth_with_discrete_curve_does_not_crash():
    handler = LASHandler()
    df = pd.DataFrame({
        "DEPTH": [100.0, 100.0, 101.0],
        "GR": [50.0, 60.0, 70.0],
        "LITH": ["SAND", "SAND", "SHALE"],  # object dtype -> old code crashed
    })
    out = handler.normalize_las_dataframe(df, depth_unit="FT")
    assert list(out["DEPTH"]) == [100.0, 101.0]
    # numeric aggregated by median, discrete preserved via 'first'
    assert out.loc[out["DEPTH"] == 100.0, "GR"].iloc[0] == pytest.approx(55.0)
    assert out.loc[out["DEPTH"] == 100.0, "LITH"].iloc[0] == "SAND"
    assert "LITH" in out.columns


def test_normalize_nulls_999_removed_and_int64_included():
    handler = LASHandler()
    df = pd.DataFrame({
        "DEPTH": [100.0, 101.0, 102.0],
        "GR": [999.25, -999.25, 70.0],           # float sentinel handling
        "FACIES": pd.Series([1, -999, 3], dtype="int64"),  # int64 sentinel
    })
    out = handler.normalize_las_dataframe(df, depth_unit="FT")
    # Valid 999.25 preserved; -999.25 nulled.
    assert np.isclose(out["GR"].dropna().to_numpy(), 999.25, atol=1e-3).any()
    assert out["GR"].isna().sum() == 1
    # int64 discrete sentinel -999 nulled (dtype list includes int64).
    assert out["FACIES"].isna().sum() == 1


# --------------------------------------------------------------------------- #
# build_master_depth: linspace determinism
# --------------------------------------------------------------------------- #
def test_master_depth_has_exact_endpoints_no_drift():
    handler = LASHandler()
    dfs = [
        pd.DataFrame({"DEPTH": np.array([0.0, 5000.0])}),
    ]
    master = handler.build_master_depth(dfs, step_ft=0.5)
    assert master[0] == pytest.approx(0.0)
    assert master[-1] == pytest.approx(5000.0)  # last point never dropped
    assert len(master) == 10001
    steps = np.diff(master)
    assert np.allclose(steps, 0.5)


def test_master_depth_rejects_nonpositive_step():
    handler = LASHandler()
    dfs = [pd.DataFrame({"DEPTH": [1000.0, 1001.0]})]

    with pytest.raises(ValueError, match="step_ft"):
        handler.build_master_depth(dfs, step_ft=0.0)


# --------------------------------------------------------------------------- #
# merge report: gaps_filled_from records all contributing sources
# --------------------------------------------------------------------------- #
def test_gaps_filled_from_lists_all_sources():
    depths = np.arange(1000.0, 1020.0, 1.0)  # 20 points
    a = np.full(20, np.nan); a[0:10] = np.arange(10) + 1.0     # A covers 0-9
    b = np.full(20, np.nan); b[15:20] = np.arange(5) + 100.0   # B covers 15-19
    c = np.full(20, np.nan); c[10:15] = np.arange(5) + 200.0   # C covers 10-14

    las_a = FakeLAS(pd.DataFrame({"DEPTH": depths, "GR": a}))
    las_b = FakeLAS(pd.DataFrame({"DEPTH": depths, "GR": b}))
    las_c = FakeLAS(pd.DataFrame({"DEPTH": depths, "GR": c}))

    handler = LASHandler()
    # Small gap_limit so the 10-point gaps in A are not bridged by
    # extrapolation and must genuinely be filled from B and C.
    result = handler.merge_las_files(
        [las_a, las_b, las_c], ["A", "B", "C"], step_ft=1.0, gap_limit_ft=1.5
    )
    curves = result["merge_report"].curves
    assert "GR" in curves
    filled_from = curves["GR"]["gaps_filled_from"]
    assert filled_from is not None
    # Both secondary files contributed -> comma-joined, both present.
    assert "B" in filled_from and "C" in filled_from
    assert "," in filled_from


def test_export_merged_las_writes_utf8(tmp_path):
    df = pd.DataFrame({"DEPTH": [1000.0, 1001.0], "GR": [50.0, 60.0]})
    out = tmp_path / "merged.las"
    content = export_merged_las(df, {"well_name": "WELL-Ñ"}, str(out))
    assert out.exists()
    # Reads back cleanly as UTF-8 (would raise if written as CP1252).
    text = out.read_text(encoding="utf-8")
    assert "WELL-Ñ" in text and "WELL-Ñ" in content


def test_discrete_detection_uses_curve_name_tokens():
    # CLASS is a discrete token only when it is a standalone mnemonic token;
    # VCLASSIFIER must remain a continuous curve name.
    assert _is_discrete_curve("LITHOLOGY") is False
    assert _is_discrete_curve("VCLASSIFIER") is False
    assert _is_discrete_curve("CLASS_CODE") is True


def test_discrete_string_curve_projects_without_numeric_cast():
    handler = LASHandler()
    df = pd.DataFrame({
        "DEPTH": [100.0, 101.0],
        "LITH": ["SAND", "SHALE"],
    })

    projected = handler.project_to_master_grid(
        df, np.array([100.0, 100.5, 101.0]), gap_limit_ft=2.0, step_ft=0.5
    )

    assert projected["LITH"].tolist() == ["SAND", "SAND", "SHALE"]


def test_merge_handles_duplicate_depth_with_string_curve():
    depths = [100.0, 100.0, 101.0]
    frame = pd.DataFrame({
        "DEPTH": depths,
        "GR": [50.0, 60.0, 70.0],
        "LITH": ["SAND", "SAND", "SHALE"],
    })
    result = LASHandler().merge_las_files(
        [FakeLAS(frame.copy()), FakeLAS(frame.copy())],
        ["A", "B"],
        step_ft=1.0,
        gap_limit_ft=1.5,
    )

    assert result["merged_df"]["LITH"].tolist() == ["SAND", "SHALE"]


def test_fill_gaps_rejects_misaligned_indexes():
    handler = LASHandler()
    primary = pd.Series([1.0, np.nan], index=[10, 11])
    secondary = pd.Series([2.0, 3.0], index=[0, 1])

    with pytest.raises(ValueError, match="identical indexes"):
        handler.fill_gaps_from_secondary(primary, secondary)


def test_export_merged_las_preserves_discrete_labels(tmp_path):
    df = pd.DataFrame({
        "DEPTH": [1000.0, 1001.0],
        "LITH": ["SAND", "SHALE"],
        "GR": [50.0, np.nan],
    })

    content = export_merged_las(df, {"well_name": "W1"}, str(tmp_path / "labels.las"))

    assert "SAND" in content and "SHALE" in content
    assert "-999.2500" in content


def test_export_merged_las_sorts_depth_before_serializing():
    df = pd.DataFrame({
        "DEPTH": [1001.0, 1000.0, 1002.0],
        "GR": [60.0, 50.0, 70.0],
    })

    content = export_merged_las(df, {"well_name": "W1"})
    data_lines = content.split("~A DEPTH GR\n", 1)[1].splitlines()

    assert data_lines[0].startswith("1000.00")
    assert data_lines[1].startswith("1001.00")
    assert data_lines[2].startswith("1002.00")
    assert "STEP.FT            1.0000" in content
