"""v1.7.1 intake and merge guards (P0 I1-I5, I7, I8; P0-Hardening H1, H5)."""

import io
import os

import numpy as np
import pandas as pd
import pytest

from modules import las_handler, table_reader
from modules import param_scopes as ps
from modules.las_handler import LASHandler, MERGE_POLICY
from modules.las_parser import LASParser
from modules.las_utils import normalize_curve_units


def las_text(curves, rows, depth_unit="FT", header_extra="", strt=1000.0, stop=1004.0):
    """Minimal LAS 2.0 text; ``curves`` is a list of (mnemonic, unit)."""
    curve_lines = "".join(f" {m}.{u}   : {m}\n" for m, u in curves)
    body = "".join("  ".join(str(v) for v in row) + "\n" for row in rows)
    return (
        "~VERSION INFORMATION\n VERS. 2.0 : X\n WRAP. NO : X\n"
        "~WELL INFORMATION\n"
        f" STRT.{depth_unit} {strt} : START\n STOP.{depth_unit} {stop} : STOP\n"
        f" STEP.{depth_unit} 1.0 : STEP\n NULL. -999.25 : NULL\n WELL. W1 : WELL\n"
        f"{header_extra}"
        f"~CURVE INFORMATION\n{curve_lines}~ASCII\n{body}"
    )


def parse(text):
    parser = LASParser()
    assert parser.read_las_from_buffer(io.StringIO(text)), parser.last_error
    return parser


class Fake:
    """Duck-typed parser for merge tests."""

    def __init__(self, data, curve_info=None):
        self.data = data
        self.curve_info = curve_info or {}
        self.well_info = {"well_name": "W", "depth_unit": "FT", "null_value": -999.25}


# ---------------------------------------------------------------- I1, I2
def test_resistivity_at_or_below_zero_is_masked_and_counted():
    rows = [(1000 + i, 50.0, 10.0 if i not in (1, 3) else (0.0 if i == 1 else -5.0)) for i in range(5)]
    parser = parse(las_text([("DEPT", "FT"), ("GR", "API"), ("RT", "OHMM")], rows))
    assert parser.data["RT"].isna().sum() == 2
    assert "RT: 2 samples ≤ 0 set to NaN" in parser.unit_warnings
    assert parser.data["GR"].notna().all()


def test_any_ohm_curve_is_masked_but_not_nphi():
    rows = [(1000 + i, -0.02 if i == 0 else 0.2, 0.0 if i == 2 else 5.0) for i in range(5)]
    parser = parse(las_text([("DEPT", "FT"), ("NPHI", "V/V"), ("MYRES", "OHM.M")], rows))
    assert parser.data["MYRES"].isna().sum() == 1
    assert parser.data["NPHI"].notna().all()


def test_rhob_and_dt_nonpositive_masked_but_low_positive_density_kept():
    rows = [(1000 + i, d, t) for i, (d, t) in enumerate(
        [(0.0, 90.0), (-1.0, 0.0), (1.0, 80.0), (2.4, -3.0), (2.5, 70.0)])]
    parser = parse(las_text([("DEPT", "FT"), ("RHOB", "G/CC"), ("DT", "US/F")], rows))
    assert parser.data["RHOB"].isna().tolist() == [True, True, False, False, False]
    assert parser.data["RHOB"].iloc[2] == 1.0
    assert parser.data["DT"].isna().sum() == 2
    assert "RHOB: 2 samples ≤ 0 set to NaN" in parser.unit_warnings
    assert "DT: 2 samples ≤ 0 set to NaN" in parser.unit_warnings


# ---------------------------------------------------------------- I3
def test_merge_keeps_tvd_and_md_curves_next_to_depth():
    a = parse(las_text([("DEPT", "FT"), ("TVD", "FT"), ("GR", "API")],
                       [(1000 + i, 990.0 + i, 50.0 + i) for i in range(5)]))
    b = parse(las_text([("DEPT", "FT"), ("MD", "FT"), ("GR", "API")],
                       [(1000 + i, 1000.0 + i, 60.0 + i) for i in range(5)]))
    out = LASHandler().merge_las_files([a, b], ["a", "b"], step_ft=1.0)
    merged = out["merged_df"]
    assert "TVD" in merged.columns and "MD" in merged.columns
    assert list(merged.columns).count("DEPTH") == 1


def test_normalize_renames_a_candidate_only_when_depth_is_absent():
    df = pd.DataFrame({"MD": [1.0, 2.0], "TVD": [1.0, 2.0], "GR": [1.0, 2.0]})
    out = LASHandler().normalize_las_dataframe(df)
    assert list(out.columns) == ["DEPTH", "TVD", "GR"]


# ---------------------------------------------------------------- I4
def project(x, y, grid, gap):
    return LASHandler()._linear_interp_with_gap_limit(np.asarray(grid, float), np.asarray(x, float),
                                                      np.asarray(y, float), gap)


def test_no_extrapolation_before_first_or_after_last_sample():
    out = project([1000.0, 1001.0], [5.0, 6.0], [998.0, 999.5, 1000.0, 1000.5, 1001.0, 1002.0], 5.0)
    assert np.isnan(out[[0, 1, 5]]).all()
    assert out[2] == 5.0 and out[3] == pytest.approx(5.5) and out[4] == 6.0


def test_measured_samples_at_gap_edges_are_kept():
    grid = np.arange(1000.0, 1012.0)
    out = project([1000.0, 1001.0, 1010.0, 1011.0], [10, 20, 30, 40], grid, 5.0)
    assert out[[0, 1, 10, 11]].tolist() == [10, 20, 30, 40]
    assert np.isnan(out[2:10]).all()


def curve_df(lo, hi, value, curve="GR"):
    depth = np.arange(lo, hi + 0.5, 1.0)
    return pd.DataFrame({"DEPTH": depth, curve: value(depth)})


def test_overlapping_files_keep_measured_values_and_never_extrapolate():
    a = Fake(curve_df(1000, 1100, lambda d: 10.0 + 0 * d))
    b = Fake(curve_df(1098, 1200, lambda d: 90.0 + 0 * d))
    merged = LASHandler().merge_las_files([a, b], ["a", "b"], step_ft=1.0, gap_limit_ft=5.0)["merged_df"]
    gr = merged.set_index("DEPTH")["GR"]
    assert gr.loc[1000.0:1100.0].eq(10.0).all() or gr.loc[1000.0:1097.0].eq(10.0).all()
    assert gr.loc[1101.0:1200.0].eq(90.0).all()
    assert gr.loc[1098.0] in (10.0, 90.0)
    assert gr.notna().all()


def test_a_gap_between_files_is_not_bridged_by_end_values():
    a = Fake(curve_df(1000, 1010, lambda d: 10.0 + 0 * d))
    b = Fake(curve_df(1090, 1100, lambda d: 90.0 + 0 * d))
    merged = LASHandler().merge_las_files([a, b], ["a", "b"], step_ft=1.0, gap_limit_ft=5.0)["merged_df"]
    gr = merged.set_index("DEPTH")["GR"]
    assert gr.loc[1016.0:1084.0].isna().all()
    assert gr.loc[1011.0:1015.0].isna().all()  # no end value held past the last sample


def test_coverage_counts_measured_spans_only():
    short = curve_df(1000, 1010, lambda d: 1.0 + 0 * d)
    long_ = curve_df(1000, 1100, lambda d: 2.0 + 0 * d)
    merged = LASHandler().merge_las_files([Fake(short), Fake(long_)], ["s", "l"], step_ft=1.0,
                                          gap_limit_ft=5.0)
    assert merged["merge_report"].curves["GR"]["source_file"] == "l"


# ---------------------------------------------------------------- I5
def test_resistivity_is_interpolated_in_log10():
    df = pd.DataFrame({"DEPTH": [1000.0, 1001.0], "RT": [1.0, 1000.0], "GR": [1.0, 1000.0]})
    projected = LASHandler().project_to_master_grid(df, np.arange(1000.0, 1001.01, 0.25), 5.0, 0.25)
    assert projected["RT"].iloc[1:4].tolist() == pytest.approx([5.62, 31.6, 177.8], abs=0.05)
    assert projected["RT"].iloc[0] == 1.0 and projected["RT"].iloc[4] == 1000.0
    assert projected["GR"].iloc[1] == pytest.approx(250.75)  # other curves stay linear


def test_ohm_unit_curve_is_log_interpolated_via_curve_info():
    df = pd.DataFrame({"DEPTH": [1000.0, 1001.0], "MYRES": [1.0, 1000.0]})
    projected = LASHandler().project_to_master_grid(
        df, np.arange(1000.0, 1001.01, 0.25), 5.0, 0.25, curve_info={"MYRES": {"unit": "OHM.M"}})
    assert projected["MYRES"].iloc[2] == pytest.approx(31.6, abs=0.05)


def test_merge_policy_is_two():
    assert MERGE_POLICY == 2


# ---------------------------------------------------------------- I7
BHT_HEADER = " BHT. 194 : BOTTOM HOLE TEMP\n TD. 3000 : TOTAL DEPTH\n"


def test_metric_las_with_unitless_bht_and_td_is_flagged_and_gives_a_sane_gradient():
    rows = [(1000 + i, 50.0) for i in range(5)]
    parser = parse(las_text([("DEPT", "M"), ("GR", "API")], rows, depth_unit="M", header_extra=BHT_HEADER))
    info = parser.well_info
    assert info["td_unit_assumed"] and info["bht_unit_assumed"]
    gradient = ps.gradient_from_header(info, 80.0)
    assert gradient == pytest.approx(1.16, abs=0.01)
    notes = ps.gradient_header_notes(info, gradient)
    assert "TD unit assumed: m" in notes and "BHT unit assumed: °F" in notes
    assert "unusual" not in notes


def test_td_with_a_declared_metre_unit_gives_the_same_gradient_without_the_td_flag():
    header = " BHT. 194 : BOTTOM HOLE TEMP\n TD.M 3000 : TOTAL DEPTH\n"
    rows = [(1000 + i, 50.0) for i in range(5)]
    parser = parse(las_text([("DEPT", "M"), ("GR", "API")], rows, depth_unit="M", header_extra=header))
    assert not parser.well_info.get("td_unit_assumed")
    assert ps.gradient_from_header(parser.well_info, 80.0) == pytest.approx(1.16, abs=0.01)


def test_unusual_gradient_is_warned():
    notes = ps.gradient_header_notes({}, 5.0)
    assert "check the BHT and TD units" in notes
    assert "check the BHT and TD units" in ps.gradient_header_notes({}, 0.2)
    assert ps.gradient_header_notes({}, 1.5) == ""


# ---------------------------------------------------------------- I8
def test_nphi_in_percent_values_labelled_vv_warns():
    df = pd.DataFrame({"DEPTH": [1.0, 2.0, 3.0], "NPHI": [20.0, 25.0, 30.0]})
    _, info, warnings = normalize_curve_units(df, {"NPHI": {"unit": "V/V", "description": ""}})
    assert any(w.startswith("NPHI median") for w in warnings)


def test_rhob_in_kg_m3_labelled_gcc_warns_and_converts():
    df = pd.DataFrame({"DEPTH": [1.0, 2.0, 3.0], "RHOB": [2350.0, 2400.0, 2450.0]})
    df, info, warnings = normalize_curve_units(df, {"RHOB": {"unit": "G/CC", "description": ""}})
    assert df["RHOB"].median() == pytest.approx(2.40)
    assert any("contradicts" in w for w in warnings)
    assert info["RHOB"]["unit"] == "G/C3"


def test_sane_curves_give_no_sanity_warning():
    df = pd.DataFrame({"DEPTH": [1.0, 2.0], "NPHI": [0.2, 0.3], "RHOB": [2.4, 2.5], "DT": [80.0, 90.0]})
    _, _, warnings = normalize_curve_units(df, {})
    assert warnings == []


# ---------------------------------------------------------------- H1
def test_merge_records_the_resolved_gap_limit_and_build_well_sets_the_recipe():
    from services.load_service import ParsedFile, build_well

    a = parse(las_text([("DEPT", "FT"), ("GR", "API")], [(1000 + i, 10.0) for i in range(5)]))
    b = parse(las_text([("DEPT", "FT"), ("GR", "API")], [(1003 + i, 20.0) for i in range(5)],
                       strt=1003.0, stop=1007.0))
    result = LASHandler().merge_las_files([a, b], ["a", "b"], step_ft=0.5, gap_limit_ft=None)
    master = result["merge_report"].master_depth
    assert isinstance(master["gap_limit"], float) and master["gap_limit"] >= 5.0
    files = [ParsedFile("a.las", "a.las", a), ParsedFile("b.las", "b.las", b)]  # parsed LAS files
    ds = build_well(files, result)
    assert ds.merge_recipe == {"step": 0.5, "gap_limit": master["gap_limit"], "policy": MERGE_POLICY}


def test_single_file_well_has_no_merge_recipe():
    from services.load_service import ParsedFile, build_well

    parser = parse(las_text([("DEPT", "FT"), ("GR", "API")], [(1000 + i, 50.0) for i in range(5)]))
    assert build_well([ParsedFile("a.las", "a.las", parser)]).merge_recipe is None


# ---------------------------------------------------------------- H5
def test_merge_grid_over_the_point_ceiling_is_refused_without_allocating():
    df = pd.DataFrame({"DEPTH": [0.0, 200000.2], "GR": [1.0, 2.0]})
    with pytest.raises(ValueError, match=r"needs 2000003 points.*check the depth unit and the step"):
        LASHandler().build_master_depth([df], 0.1)


def test_merge_grid_over_the_memory_estimate_is_refused():
    wide = pd.DataFrame({c: [0.0, 1.0] for c in ["DEPTH"] + [f"C{i}" for i in range(60)]})
    wide["DEPTH"] = [0.0, 1_000_000.0]
    with pytest.raises(ValueError, match="GB"):
        LASHandler().build_master_depth([wide, wide, wide], 1.0)


def test_a_normal_grid_passes():
    df = pd.DataFrame({"DEPTH": [0.0, 30000.0], "GR": [1.0, 2.0]})
    assert len(LASHandler().build_master_depth([df], 0.5)) == 60001


def test_depth_outside_the_sane_range_is_a_load_error_naming_the_curve():
    rows = [(1000000 + i, 50.0) for i in range(5)]
    parser = LASParser()
    ok = parser.read_las_from_buffer(io.StringIO(
        las_text([("DEPT", "FT"), ("GR", "API")], rows, strt=1000000.0, stop=1000004.0)))
    assert not ok and "DEPT" in parser.last_error


def test_normalize_rejects_an_absurd_depth():
    with pytest.raises(ValueError, match="TVD"):
        LASHandler().normalize_las_dataframe(pd.DataFrame({"TVD": [1.0, 5e6], "GR": [1.0, 2.0]}))


def test_oversize_files_are_refused(monkeypatch, tmp_path):
    from services import load_service

    path = tmp_path / "w.las"
    path.write_text("x")
    monkeypatch.setattr(os.path, "getsize", lambda p: 600 * 1024 * 1024)
    parsed = load_service.parse_file(str(path))
    assert not parsed.ok and "limit" in parsed.error
    with pytest.raises(table_reader.TableReadError, match="limit"):
        table_reader.read_table(str(path))
