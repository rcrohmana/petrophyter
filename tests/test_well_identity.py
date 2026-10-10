"""
Tests for LAS header identity capture, depth-unit handling and the
same-well guard on the merge path.
"""

import io

import numpy as np
import pandas as pd
import pytest

from modules.las_handler import (
    LASHandler,
    MergeReport,
    count_unidentified,
    validate_same_well,
)
from modules.las_parser import LASParser
from modules.las_utils import canonical_unit
from services.merge_service import MergeWorker


def make_las(well_lines=" WELL.   TESTWELL : WELL\n", params="", strt_unit="M",
             curve_unit=None, depth_mnemonic="DEPT", curves=(("GR", "API", [50.0, 60.0, 70.0]),)):
    """Build a LAS 2.0 document with 3 rows. curve_unit defaults to strt_unit."""
    cu = strt_unit if curve_unit is None else curve_unit
    curve_lines = "".join(f" {m}.{u}   : {m}\n" for m, u, _ in curves)
    rows = ""
    for i, depth in enumerate([1000.0, 1001.0, 1002.0]):
        rows += f"{depth}  " + "  ".join(str(v[i]) for _, _, v in curves) + "\n"
    return (
        "~VERSION INFORMATION\n"
        " VERS.                 2.0 : CWLS LAS 2.0\n"
        " WRAP.                  NO : ONE LINE PER DEPTH STEP\n"
        "~WELL INFORMATION\n"
        f" STRT.{strt_unit}    1000.0 : START DEPTH\n"
        f" STOP.{strt_unit}    1002.0 : STOP DEPTH\n"
        f" STEP.{strt_unit}       1.0 : STEP\n"
        " NULL.    -999.25 : NULL VALUE\n"
        f"{well_lines}"
        + (f"~PARAMETER INFORMATION\n{params}" if params else "")
        + "~CURVE INFORMATION\n"
        f" {depth_mnemonic}.{cu}      : DEPTH\n"
        + curve_lines
        + "~ASCII\n"
        + rows
    )


def parse(text):
    parser = LASParser()
    assert parser.read_las_from_buffer(io.StringIO(text)), parser.last_error
    return parser


class Fake:
    """Duck-typed parser for merge tests."""

    def __init__(self, data, well_info=None, curve_info=None):
        self.data = data
        self.well_info = {"well_name": "W", "depth_unit": "FT", "null_value": -999.25}
        self.well_info.update(well_info or {})
        self.curve_info = curve_info or {}


# --------------------------------------------------------------------------- #
# Header identity
# --------------------------------------------------------------------------- #
def test_identity_fields_captured():
    well = (
        " WELL.   A-1  : WELL\n"
        " UWI .   UWI-001 : UWI\n"
        " API .   42-123 : API\n"
        " LOC .   Block 7 : LOCATION\n"
        " SRVC.   ACME : SERVICE COMPANY\n"
        " DATE.   2020-01-02 : DATE\n"
    )
    info = parse(make_las(well_lines=well)).well_info
    assert info["well_name"] == "A-1"
    assert info["uwi"] == "UWI-001"
    assert info["api"] == "42-123"
    assert info["location"] == "Block 7"
    assert info["service_company"] == "ACME"
    assert info["date"] == "2020-01-02"
    assert info["well_key"] == "UWI:UWI-001"
    assert info["well_identified"] is True


def test_missing_identity_is_none_and_unidentified():
    info = parse(make_las(well_lines=" WELL.   Unknown : WELL\n")).well_info
    assert info["uwi"] is None and info["api"] is None
    assert info["well_key"] == ""
    assert info["well_identified"] is False
    assert "kb_elevation" not in info


def test_parameters_captured():
    params = (
        " EKB .M   25.5 : KB\n"
        " EGL .M   10 : GL\n"
        " EDF .M   24 : DF\n"
        " PDAT.   MSL : DATUM\n"
        " DMF .   KB : MEASURED FROM\n"
        " BHT .DEGC   85 : BHT\n"
        " TDD .M   3200 : TD\n"
    )
    info = parse(make_las(params=params)).well_info
    assert info["kb_elevation"] == 25.5 and info["kb_elevation_unit"] == "M"
    assert info["gl_elevation"] == 10.0
    assert info["df_elevation"] == 24.0
    assert info["permanent_datum"] == "MSL"
    assert info["depth_measured_from"] == "KB"
    assert info["bht"] == 85.0 and info["bht_unit"] == "DEGC"
    assert info["td"] == 3200.0 and info["td_unit"] == "M"


def test_mrt_is_bht_fallback():
    info = parse(make_las(params=" MRT .DEGC   90 : MAX TEMP\n")).well_info
    assert info["bht"] == 90.0


# --------------------------------------------------------------------------- #
# Depth unit
# --------------------------------------------------------------------------- #
def test_strt_unit_falls_back_to_depth_curve_unit():
    text = make_las(strt_unit="", curve_unit="M")
    parser = parse(text)
    assert parser.depth_unit_detected is True
    assert parser.original_depth_unit == "M"
    assert abs(parser.data["DEPTH"].iloc[0] - 1000.0 * 3.28084) < 1e-6


def test_meter_conversion_updates_start_stop_step():
    parser = parse(make_las(strt_unit="M"))
    info = parser.well_info
    assert abs(info["start_depth"] - 1000.0 * 3.28084) < 1e-6
    assert abs(info["stop_depth"] - 1002.0 * 3.28084) < 1e-6
    assert abs(info["step"] - 3.28084) < 1e-6
    assert info["original_depth_unit"] == "M"
    assert info["depth_unit"] == "FT"


def test_feet_file_keeps_start_stop_step():
    info = parse(make_las(strt_unit="F")).well_info
    assert info["start_depth"] == 1000.0 and info["step"] == 1.0


def test_depth_reference_md_by_default():
    parser = parse(make_las())
    assert parser.well_info["depth_reference"] == "MD"
    assert not parser.depth_unit_warning


def test_tvd_depth_flagged():
    parser = parse(make_las(depth_mnemonic="TVD"))
    assert parser.well_info["depth_reference"] == "TVD"
    assert "TVD" in parser.depth_unit_warning


# --------------------------------------------------------------------------- #
# validate_same_well / merge service
# --------------------------------------------------------------------------- #
def test_validate_same_well_different_wells():
    a = Fake(pd.DataFrame(), {"well_name": "A-1"})
    b = Fake(pd.DataFrame(), {"well_name": "B-2"})
    ok, names = validate_same_well([a, b])
    assert ok is False and names == ["A-1", "B-2"]


def test_validate_same_well_name_variants_match():
    a = Fake(pd.DataFrame(), {"well_name": "a_1 "})
    b = Fake(pd.DataFrame(), {"well_name": "A-1"})
    assert validate_same_well([a, b])[0] is True


def test_uwi_beats_name():
    a = Fake(pd.DataFrame(), {"well_name": "A-1", "uwi": "X1"})
    b = Fake(pd.DataFrame(), {"well_name": "OTHER", "uwi": "X1"})
    assert validate_same_well([a, b])[0] is True


def test_undecidable_identity_allowed_but_counted():
    a = Fake(pd.DataFrame(), {"well_name": "A-1"})
    b = Fake(pd.DataFrame(), {"well_name": "Unknown"})
    assert validate_same_well([a, b])[0] is True
    assert count_unidentified([a, b]) == 1


def _run_worker(parsers):
    messages, errors, completed = [], [], []
    worker = MergeWorker(parsers, [f"f{i}" for i in range(len(parsers))], 1.0, 5.0)
    worker.signals.progress.connect(lambda m, p: messages.append(m))
    worker.signals.error.connect(errors.append)
    worker.signals.completed.connect(lambda df, rep: completed.append((df, rep)))
    worker.run()
    return messages, errors, completed


def _df(**curves):
    return pd.DataFrame({"DEPTH": [0.0, 1.0, 2.0, 3.0], **curves})


def test_service_refuses_different_wells():
    a = Fake(_df(GR=[1.0, 2, 3, 4]), {"well_name": "A-1"})
    b = Fake(_df(GR=[1.0, 2, 3, 4]), {"well_name": "B-2"})
    _, errors, completed = _run_worker([a, b])
    assert len(errors) == 1 and "different wells" in errors[0]
    assert "A-1" in errors[0] and "B-2" in errors[0]
    assert completed == []


def test_service_merges_unidentified_with_warning():
    a = Fake(_df(GR=[1.0, 2, 3, 4]), {"well_name": "A-1"})
    b = Fake(_df(GR=[1.0, 2, 3, 4]), {"well_name": "Unknown"})
    messages, errors, completed = _run_worker([a, b])
    assert errors == [] and len(completed) == 1
    assert any("no well identifier" in m for m in messages)


# --------------------------------------------------------------------------- #
# Merge determinism and report content
# --------------------------------------------------------------------------- #
def test_merge_column_order_and_well_name_deterministic():
    a = Fake(_df(ZZZ=[1.0, 2, 3, 4], AAA=[1.0, 2, 3, 4]), {"well_name": " Unknown "})
    b = Fake(_df(MMM=[1.0, 2, 3, 4], AAA=[1.0, 2, 3, 4]), {"well_name": " Well-7 "})
    for _ in range(3):
        result = LASHandler().merge_las_files([a, b], ["a", "b"], step_ft=1.0, gap_limit_ft=5.0)
        assert list(result["merged_df"].columns) == ["DEPTH", "ZZZ", "AAA", "MMM"]
        assert result["merge_report"].well_name == "Well-7"


def test_merge_report_warns_with_all_distinct_names():
    a = Fake(_df(GR=[1.0, 2, 3, 4]), {"well_name": "A-1"})
    b = Fake(_df(GR=[1.0, 2, 3, 4]), {"well_name": "b-2"})
    report = LASHandler().merge_las_files([a, b], ["a", "b"], 1.0, 5.0)["merge_report"]
    assert any("A-1" in w and "B-2" in w for w in report.warnings)


def test_merge_report_curve_info_and_well_info():
    ci = {"GR": {"unit": "API", "description": "gamma"}}
    a = Fake(_df(GR=[1.0, 2, 3, 4]), {"well_name": "A-1", "uwi": "U1"}, ci)
    b = Fake(_df(GR=[1.0, 2, 3, 4]), {"well_name": "A-1"}, ci)
    report = LASHandler().merge_las_files([a, b], ["a", "b"], 1.0, 5.0)["merge_report"]
    assert isinstance(report, MergeReport)
    assert report.curve_info["GR"]["unit"] == "API"
    assert report.curve_info["GR"]["description"] == "gamma"
    assert report.curve_info["GR"]["source_file"] in ("a", "b")
    assert report.well_info["uwi"] == "U1"
    assert report.well_info["depth_unit"] == "FT"
    assert report.well_info["start_depth"] == 0.0
    assert report.well_info["stop_depth"] == 3.0
    assert report.well_info["step"] == 1.0


def _gap_pair(unit_b):
    n = 20
    depth = np.arange(float(n))
    ga = np.full(n, 50.0)
    ga[8:14] = np.nan
    gb = np.full(n, np.nan)
    gb[8:14] = 99.0
    a = Fake(pd.DataFrame({"DEPTH": depth, "GR": ga}), {"well_name": "A"}, {"GR": {"unit": "API"}})
    b = Fake(pd.DataFrame({"DEPTH": depth, "GR": gb}), {"well_name": "A"}, {"GR": {"unit": unit_b}})
    return LASHandler().merge_las_files([a, b], ["a", "b"], 1.0, 2.0)


def test_unit_mismatch_disables_secondary_gap_fill():
    result = _gap_pair("CPS")
    merged, report = result["merged_df"], result["merge_report"]
    assert report.curves["GR"]["source_file"] == "a"
    assert merged["GR"].iloc[8:14].isna().all()
    assert report.curves["GR"]["gaps_filled_from"] is None
    assert any("different units" in w for w in report.warnings)


def test_same_units_case_insensitive_still_fills():
    result = _gap_pair("api")
    assert (result["merged_df"]["GR"].iloc[8:14] == 99.0).all()
    assert not any("different units" in w for w in result["merge_report"].warnings)


@pytest.mark.parametrize("unit_b", ["GAPI", "gapi"])
def test_unit_spelling_variants_still_fill(unit_b):
    result = _gap_pair(unit_b)
    assert (result["merged_df"]["GR"].iloc[8:14] == 99.0).all()
    assert not any("different units" in w for w in result["merge_report"].warnings)


@pytest.mark.parametrize(("a", "b"), [("G/CC", "G/C3"), ("US/FT", "US/F"), ("OHM.M", "OHMM")])
def test_canonical_unit_folds_spellings(a, b):
    assert canonical_unit(a) == canonical_unit(b)


def test_canonical_unit_keeps_real_differences():
    assert canonical_unit("G/CC") != canonical_unit("KG/M3")
