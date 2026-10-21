"""U1.2: structured issue codes in the pipeline summary."""

import re
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import modules.pipeline as pipeline
from modules.issue_codes import ISSUE_CODES, IssueLog
from modules.pipeline import SWIRR_COUNT_SHARE, run_pipeline
from tests.golden.cases import CASES, build_case


def _run(name):
    data, mapping, params, tops = build_case(name)
    return run_pipeline(data, mapping, params, formation_tops=tops)[1]


@pytest.fixture(scope="module")
def summaries():
    return {name: _run(name) for name in CASES}


def test_every_emitted_code_is_in_the_closed_list(summaries):
    for name, summary in summaries.items():
        for issue in summary["issues"]:
            assert issue["code"] in ISSUE_CODES, (name, issue)
            assert set(issue) == {"code", "severity", "text", "zone", "target"}


def test_every_add_call_in_the_source_uses_a_listed_code():
    source = Path(pipeline.__file__).read_text(encoding="utf-8")
    literal = set(re.findall(r'\.add\(\s*"([A-Z_]+)"', source))
    assert literal and literal <= set(ISSUE_CODES)
    # Codes built from a name: f"{logical}_NONPOSITIVE", f"{which}_AUTO_NOTE", ...
    assert {"RT_NONPOSITIVE", "RHOB_NONPOSITIVE", "DT_NONPOSITIVE",
            "RW_AUTO_NOTE", "RSH_AUTO_NOTE"} <= set(ISSUE_CODES)


def test_warnings_are_exactly_the_non_info_issue_texts(summaries):
    for name, summary in summaries.items():
        expected = list(dict.fromkeys(
            i["text"] for i in summary["issues"] if i["severity"] != "info"))
        assert summary["warnings"] == expected, name


def test_issue_log_rejects_unknown_codes_and_keeps_info_out_of_warnings():
    log = IssueLog()
    with pytest.raises(KeyError):
        log.add("NOT_A_CODE", "x")
    log.add("SWIRR_FLOOR", "info text")
    log.add("SWIRR_FLOOR", "warn text", severity="warning")
    assert list(log) == ["warn text"]
    assert [i["severity"] for i in log.issues] == ["info", "warning"]
    assert log.issues[0]["target"] == "params.swirr"


def test_swirr_diagnostics_shape(summaries):
    for name, summary in summaries.items():
        diag = summary["swirr_diagnostics"]
        assert set(diag) == {"method_used", "samples", "fallback_samples", "floor_samples",
                             "limited_by_sw", "limited_to_max"}, name
        assert diag["method_used"] == summary["swirr_method"]
        assert all(isinstance(diag[k], int) for k in diag if k != "method_used")
        assert diag["samples"] >= 0


class _Calc:
    def __init__(self, **cols):
        self.swirr_flags = pd.DataFrame(cols)


def test_swirr_counts_are_info_below_the_share_and_warning_above():
    index = pd.RangeIndex(100)
    n = int(SWIRR_COUNT_SHARE * 100)
    flags = {"raised_to_floor": [i < n for i in index],           # exactly at the share
             "limited_by_sw": [i < 90 for i in index],            # min(Swirr, Sw): always info
             "limited_to_max": [i < n + 1 for i in index]}        # above the share
    log = IssueLog()
    counts = pipeline._swirr_warnings([_Calc(**flags)], index, log, 100)
    by_code = {i["code"]: i["severity"] for i in log.issues}
    assert by_code == {"SWIRR_FLOOR": "info", "SWIRR_LIMITED": "info", "SWIRR_MAXED": "warning"}
    assert len(log) == 1 and "0.60 maximum" in log[0]
    assert counts == {"fallback_samples": 0, "floor_samples": n, "limited_by_sw": 90,
                      "limited_to_max": n + 1}


def test_zone_without_shale_is_an_info_issue_with_the_zone():
    data, mapping, params, tops = build_case("per_formation_lower")
    # A clean zone: GR low everywhere in the lower formation.
    data = data.copy()
    data.loc[data["DEPTH"] >= 1040, "GR"] = 25.0 + (data["DEPTH"] % 7)
    _, summary = run_pipeline(
        data, mapping, {**params, "analysis_mode": "Whole Well", "selected_formations": []},
        formation_tops=tops)
    notes = [d for d in (summary.get("zone_diagnostics") or {}).values() if d.get("note")]
    found = [i for i in summary["issues"] if i["code"] == "ZONE_NO_SHALE"]
    assert len(found) == len(notes)
    for issue in found:
        assert issue["severity"] == "info" and issue["target"] == "diagnostics"
        assert issue["zone"] and issue["text"] == pipeline.ZONE_NO_SHALE_NOTE
        assert issue["text"] not in summary["warnings"]


def test_no_rt_case_has_field_level_codes(summaries):
    codes = {i["code"] for i in summaries["no_rt_no_dt"]["issues"]}
    assert "SW_DEFAULTED_NO_RT" in codes


def test_saturation_height_codes_are_listed():
    expected = {"SHF_NO_CONTACT", "SHF_NO_MODEL", "SHF_NO_PERM_PHI", "SHF_UNCLASSIFIED",
                "SHF_TVD_NOTE", "SHF_TVDSS_SUSPECT", "SHF_PAY_FALLBACK", "SHF_PAY_REFUSED",
                "SHF_ZONE_SCOPE_RT"}
    assert expected <= set(ISSUE_CODES)
    log = IssueLog()
    for code in expected:
        log.add(code, code)
    assert all(i["target"] == "diagnostics" for i in log.issues)
    assert ISSUE_CODES["SHF_ZONE_SCOPE_RT"][0] == "info"
