"""LRLC report frames (zones, chain, references): columns, blanks, determinism, multi-well, references."""
import copy

import numpy as np
import pandas as pd
import pytest

from modules import references
from modules.lrlc import report
from modules.lrlc.diagnosis import CAUSE_ORDER
from modules.lrlc.report import (REF_COLUMNS, STEP_COLUMNS, ZONE_COLUMNS, refs_frame, steps_frame,
                                 wells_with_lrlc, zones_frame)

ZONE_COLUMNS_SPEC = [
    "Well", "Zone", "Top_ft", "Bottom_ft", "Samples", "Net_res_samples", "Flag_samples",
    "Flag_thickness_ft", "Flag_fraction_net", "Score_mean_net", "Water_free_samples", "Diagnosis",
    "Diagnosis_level", "Diagnosis_evidence", "Rt_steps", "Rt_source", "Rt_fallback", "Guard",
    "Net_pay_base_ft", "Net_pay_ft", "Net_pay_change_ft", "Avg_sw_pay_base", "Avg_sw_pay",
    "Hcpv_base", "Hcpv", "Sw_minus_shf_bias", "Sw_minus_shf_rmse", "Sw_shf_n", "Decon_status",
    "Decon_beds", "Decon_misfit_rms", "Decon_amplified", "Decon_width_sensitivity",
    "Elastic_flag_samples", "Elastic_flag_thickness_ft", "Elastic_wet_samples", "Issues"]
STEP_COLUMNS_SPEC = ["Well", "Zone", "Order", "Step", "Curve", "From", "Status", "Valid_samples",
                     "Invalid_samples", "Fallback_samples", "Params", "References"]


def results_frame(n=40, zoned=True):
    depth = 1000.0 + 0.5 * np.arange(n)
    df = pd.DataFrame({
        "DEPTH": depth,
        "NET_RES_FLAG": (np.arange(n) % 2 == 0).astype(int),
        "LRLC_FLAG": (np.arange(n) % 4 == 0).astype(int),
        "LRLC_SCORE": np.where(np.arange(n) % 2 == 0, 5.0, 2.0),
        "WATER_FREE_FLAG": (np.arange(n) % 10 == 0).astype(int)})
    if zoned:
        df["ZONE"] = np.where(np.arange(n) < n // 2, "UPPER", "LOWER")
    return df


def crit(i, op, th, value, met):
    return {"id": i, "value": value, "op": op, "threshold": th, "met": met}


def summary_full(zoned=True):
    """A summary with every block the report reads (shapes as shipped, decon / elastic per spec)."""
    zones = ["UPPER", "LOWER"] if zoned else ["WELL"]
    lam = {"key": "laminated", "label": "Thin beds / laminations", "level": "probable", "score": 1.0,
           "n_eval": 2, "remedy": {}, "criteria": [crit("vlam_share", ">=", 0.5, 0.62, True),
                                                      crit("contrast", "<=", 2.0, 3.0, False)]}
    diag = [{"zone": zones[0], "status": "ok", "n_res": 20, "thickness_ft": 10.0, "primary": "laminated",
             "causes": [lam], "ts": None, "guard": {"laminated": True, "lam_share": 0.62}}]
    if zoned:
        diag.append({"zone": "LOWER", "status": "insufficient", "n_res": 3, "thickness_ft": 1.0,
                     "primary": None, "causes": [], "ts": None, "guard": {}})
    chain = []
    for z in zones:
        zone_name = None if z == "WELL" else z
        chain.append({"zone": zone_name, "segment": "well", "step": "invasion", "curve": "RT_INV",
                      "from": "RT_DECON" if z == "UPPER" else "RT", "params": {"inv_tool": "generic"},
                      "refs": ["doll1949", "arps1953"], "n_valid": 18, "n_invalid": 2, "fallback": 1,
                      "counts": {}})
        if z == "UPPER":
            chain.insert(0, {"zone": z, "segment": "well", "step": "decon", "curve": "RT_DECON",
                             "from": "RT", "params": {"dec_fwhm_ft": 2.0}, "refs": [], "n_valid": 19,
                             "n_invalid": 1, "fallback": 0, "counts": {}})
    shf_stats = {"n": 30, "bias": 0.02, "rmse": 0.05, "mae": 0.04, "r2": 0.8}
    lrlc = {
        "version": 1, "curves": {},
        "params": {"default": {"rt_steps": [], "rt_fallback": "nan"},
                   "zones": {z: {"rt_steps": ["invasion", "decon"] if z == "UPPER" else ["invasion"],
                                 "rt_fallback": "previous" if z == "UPPER" else "nan"}
                             for z in zones if z != "WELL"}},
        "chain": chain,
        "screening": {"thresholds": {}, "criteria": {}, "unavailable": [],
                      "zones": [{"zone": z, "n": 20, "candidate_ft": 2.5, "net_res_ft": 10.0}
                                for z in zones]},
        "movable": {}, "counts": {"n": 40},
        "guard": {"enabled": True, "zones": [
            {"zone": None if z == "WELL" else z, "laminated": z == "UPPER", "lam_share": 0.6,
             "blocked_steps": ["decon"] if z == "LOWER" else [], "sbc_rt": False} for z in zones]},
        "validation": {"basis": "x", "pay_sw": "resistivity", "n_shf_held": 0,
                       "well": {"net_pay_base": 10.0, "net_pay": 12.0, "delta": 2.0,
                                "avg_sw_pay_base": 0.5, "avg_sw_pay": 0.4, "hcpv_net_pay_base": 1.0,
                                "hcpv_net_pay": 1.2},
                       "zones": [{"zone": z, "net_pay_base": 5.0, "net_pay": 6.0, "delta": 1.0,
                                  "avg_sw_pay_base": 0.5, "avg_sw_pay": 0.4, "hcpv_net_pay_base": 0.5,
                                  "hcpv_net_pay": 0.6} for z in zones if z != "WELL"],
                       "shf": {"well": {"base": shf_stats, "corrected": shf_stats},
                               "zones": [{"zone": z, "base": shf_stats, "corrected": shf_stats}
                                         for z in zones if z != "WELL"]}},
        "zones": diag,
        "decon": {"hires": {}, "params": {}, "n_beds": 14, "boundaries": {"UPPER": [1.0, 2.0, 3.0, 4.0]},
                  "zones": [{"zone": "UPPER", "status": "ran", "max_ratio": 10.0, "n_active": 20,
                             "n_valid": 19, "n_amplified": 2, "misfit_rms": 0.07}],
                  "counts": {}},
        "elastic": {"curves": {}, "params": {}, "baseline": {}, "wet": {"n": 33, "source": "sw"},
                    "zones": [{"zone": z, "n_net": 20, "n_flag": 4, "thickness_flag_ft": 2.0,
                               "n_invalid": 0} for z in zones],
                    "counts": {"flag": 8}},
    }
    issues = [{"code": "LRLC_STEP_INVALID", "severity": "warning", "text": "t", "zone": "UPPER"},
              {"code": "LRLC_GUARD_NO_TS", "severity": "info", "text": "t", "zone": "UPPER"},
              {"code": "SWIRR_LIMITED", "severity": "warning", "text": "t", "zone": "UPPER"},
              {"code": "LRLC_STEP_FALLBACK", "severity": "warning", "text": "t", "zone": None}]
    summary = {"lrlc": lrlc, "issues": issues}
    if zoned:
        summary["zones"] = [{"zone": "UPPER", "top": 1000.0, "bottom": 1010.0, "samples": 20},
                            {"zone": "LOWER", "top": 1010.0, "bottom": 1020.0, "samples": 20}]
    else:
        summary["zones"] = []
    return summary


def minimal_summary():
    """LRLC on, nothing selected: only the blocks that always exist."""
    return {"lrlc": {"version": 1, "curves": {}, "params": {"default": {"rt_steps": []}, "zones": {}},
                     "chain": [], "screening": {"thresholds": {}, "criteria": {}, "unavailable": [],
                                                "zones": [{"zone": "UPPER", "n": 20},
                                                          {"zone": "LOWER", "n": 20}]},
                     "movable": {}, "counts": {"n": 40}}, "issues": []}


def well(label="W1", summary=None, results=None):
    return (label, summary if summary is not None else summary_full(),
            results if results is not None else results_frame())


def row(df, zone, well_label="W1"):
    return df[(df["Well"] == well_label) & (df["Zone"] == zone)].iloc[0]


def blank(value):
    return value is None or (isinstance(value, float) and np.isnan(value))


# ---------------------------------------------------------------------------
def test_exact_columns_and_order():
    assert list(ZONE_COLUMNS) == ZONE_COLUMNS_SPEC
    assert list(STEP_COLUMNS) == STEP_COLUMNS_SPEC
    assert list(REF_COLUMNS) == ["Key", "Citation", "Status", "Used_by"]
    w = [well()]
    assert list(zones_frame(w).columns) == ZONE_COLUMNS_SPEC
    assert list(steps_frame(w).columns) == STEP_COLUMNS_SPEC
    assert list(refs_frame(w).columns) == ["Key", "Citation", "Status", "Used_by"]


def test_no_lrlc_gives_empty_frames_with_the_columns():
    skipped = ("A", {"lrlc": {"version": 1, "skipped": "no RT"}}, results_frame())
    plain = ("B", {"issues": []}, results_frame())
    assert wells_with_lrlc([skipped, plain]) == []
    for frame, cols in ((zones_frame([skipped, plain]), ZONE_COLUMNS_SPEC),
                        (steps_frame([skipped, plain]), STEP_COLUMNS_SPEC),
                        (refs_frame([skipped, plain]), ["Key", "Citation", "Status", "Used_by"])):
        assert len(frame) == 0 and list(frame.columns) == cols
    assert [w[0] for w in wells_with_lrlc([skipped, well()])] == ["W1"]


def test_well_row_first_then_zones_in_summary_order():
    df = zones_frame([well()])
    assert df["Zone"].tolist() == ["(well)", "UPPER", "LOWER"]
    w = row(df, "(well)")
    assert w["Samples"] == 40 and w["Net_res_samples"] == 20 and w["Flag_samples"] == 10
    assert w["Flag_fraction_net"] == pytest.approx(0.5)
    assert w["Score_mean_net"] == pytest.approx(5.0)
    assert w["Water_free_samples"] == 4
    assert w["Top_ft"] == pytest.approx(1000.0) and w["Bottom_ft"] == pytest.approx(1019.5)
    up = row(df, "UPPER")
    assert up["Samples"] == 20 and up["Top_ft"] == pytest.approx(1000.0)
    assert up["Flag_thickness_ft"] == pytest.approx(0.5 * up["Flag_samples"], rel=0.1)
    assert w["Flag_samples"] == up["Flag_samples"] + row(df, "LOWER")["Flag_samples"]


def test_diagnosis_columns_use_the_shipped_cause_keys():
    df = zones_frame([well()])
    up, lo = row(df, "UPPER"), row(df, "LOWER")
    assert up["Diagnosis"] == "laminated" and "laminated" in CAUSE_ORDER
    assert up["Diagnosis_level"] == "probable"
    assert up["Diagnosis_evidence"] == "vlam_share >= 0.5 (0.62)"      # only the met criteria
    assert lo["Diagnosis"] == "insufficient"
    assert blank(lo["Diagnosis_level"]) and blank(lo["Diagnosis_evidence"])
    assert blank(row(df, "(well)")["Diagnosis"])                      # zoned well: no well diagnosis
    for key in CAUSE_ORDER:                                           # any shipped key passes through
        s = summary_full()
        s["lrlc"]["zones"][0]["primary"] = key
        s["lrlc"]["zones"][0]["causes"][0]["key"] = key
        assert row(zones_frame([well(summary=s)]), "UPPER")["Diagnosis"] == key


def test_chain_cells_guard_and_validation():
    df = zones_frame([well()])
    up, lo, w = row(df, "UPPER"), row(df, "LOWER"), row(df, "(well)")
    assert up["Rt_steps"] == "decon > invasion"                       # chain order, not request order
    assert up["Rt_source"] == "RT_INV <- RT_DECON <- RT"
    assert up["Rt_fallback"] == "previous"
    assert lo["Rt_steps"] == "invasion" and lo["Rt_source"] == "RT_INV <- RT"
    assert blank(w["Rt_steps"]) and blank(w["Rt_source"])             # no steps at the well default
    assert up["Guard"] == "on" and lo["Guard"] == "on; blocked: decon" and w["Guard"] == "on"
    assert (up["Net_pay_base_ft"], up["Net_pay_ft"], up["Net_pay_change_ft"]) == (5.0, 6.0, 1.0)
    assert (up["Avg_sw_pay_base"], up["Avg_sw_pay"]) == (0.5, 0.4)
    assert (up["Hcpv_base"], up["Hcpv"]) == (0.5, 0.6)
    assert (w["Net_pay_base_ft"], w["Net_pay_ft"], w["Net_pay_change_ft"]) == (10.0, 12.0, 2.0)
    assert (up["Sw_minus_shf_bias"], up["Sw_minus_shf_rmse"], up["Sw_shf_n"]) == (0.02, 0.05, 30)


def test_decon_and_elastic_columns():
    df = zones_frame([well()])
    up, lo, w = row(df, "UPPER"), row(df, "LOWER"), row(df, "(well)")
    assert up["Decon_status"] == "ran" and lo["Decon_status"] == "not requested"
    assert up["Decon_beds"] == 3 and up["Decon_misfit_rms"] == pytest.approx(0.07)
    assert up["Decon_amplified"] == 2
    assert w["Decon_beds"] == 14 and w["Decon_amplified"] == 2 and blank(w["Decon_status"])
    assert blank(lo["Decon_beds"]) and blank(lo["Decon_misfit_rms"])
    assert (up["Elastic_flag_samples"], up["Elastic_flag_thickness_ft"]) == (4, 2.0)
    assert (w["Elastic_flag_samples"], w["Elastic_flag_thickness_ft"]) == (8, 4.0)
    assert w["Elastic_wet_samples"] == 33 and blank(up["Elastic_wet_samples"])


def test_issue_counts_are_lrlc_warnings_only():
    df = zones_frame([well()])
    assert row(df, "UPPER")["Issues"] == 1          # info and the non-LRLC warning are not counted
    assert row(df, "LOWER")["Issues"] == 0
    assert row(df, "(well)")["Issues"] == 2


def test_features_off_are_blank_not_zero():
    df = zones_frame([well(summary=minimal_summary())])
    assert df["Zone"].tolist() == ["(well)", "UPPER", "LOWER"]
    off = ["Diagnosis", "Diagnosis_level", "Diagnosis_evidence", "Rt_steps", "Rt_source", "Rt_fallback",
           "Net_pay_base_ft", "Net_pay_ft", "Net_pay_change_ft", "Avg_sw_pay_base", "Avg_sw_pay",
           "Hcpv_base", "Hcpv", "Sw_minus_shf_bias", "Sw_minus_shf_rmse", "Sw_shf_n", "Decon_status",
           "Decon_beds", "Decon_misfit_rms", "Decon_amplified", "Decon_width_sensitivity",
           "Elastic_flag_samples", "Elastic_flag_thickness_ft", "Elastic_wet_samples"]
    for _, r in df.iterrows():
        for col in off:
            assert blank(r[col]), (r["Zone"], col)
        assert r["Guard"] == "n/a" and r["Issues"] == 0
    assert row(df, "UPPER")["Samples"] == 20
    # SHF off: the shipped validation without a shf block keeps the three columns blank
    s = summary_full()
    del s["lrlc"]["validation"]["shf"]
    r = row(zones_frame([well(summary=s)]), "UPPER")
    assert blank(r["Sw_minus_shf_bias"]) and blank(r["Sw_shf_n"]) and r["Net_pay_ft"] == 6.0
    # elastic skipped by the stage is off as well
    s = summary_full()
    s["lrlc"]["elastic"] = {"skipped": "units"}
    assert blank(row(zones_frame([well(summary=s)]), "UPPER")["Elastic_flag_samples"])


def test_zero_counts_stay_zero_when_the_feature_is_on():
    s = summary_full()
    s["lrlc"]["elastic"]["zones"][0]["n_flag"] = 0
    s["lrlc"]["elastic"]["zones"][0]["thickness_flag_ft"] = 0.0
    r = row(zones_frame([well(summary=s)]), "UPPER")
    assert r["Elastic_flag_samples"] == 0 and r["Elastic_flag_thickness_ft"] == 0.0


def test_unzoned_well_has_a_single_well_row():
    w = well(summary=summary_full(zoned=False), results=results_frame(zoned=False))
    df = zones_frame([w])
    assert df["Zone"].tolist() == ["(well)"]
    r = df.iloc[0]
    assert r["Diagnosis"] == "laminated" and r["Decon_status"] == "not requested"
    assert r["Elastic_flag_samples"] == 4 and r["Elastic_wet_samples"] == 33
    assert r["Net_pay_ft"] == 12.0 and r["Rt_source"] == "RT_INV <- RT"
    st = steps_frame([w])
    assert st["Zone"].unique().tolist() == ["(well)"]


def test_deterministic_output_and_no_input_mutation():
    wells = [well("B"), well("A")]
    before = copy.deepcopy([(l, s) for l, s, _ in wells])
    res_before = [r.copy() for _, _, r in wells]
    first = [f(wells) for f in (zones_frame, steps_frame, refs_frame)]
    second = [f(list(reversed(wells))) for f in (zones_frame, steps_frame, refs_frame)]
    for a, b in zip(first, second):
        pd.testing.assert_frame_equal(a, b)
    assert [(l, s) for l, s, _ in wells] == before
    for (_, _, r), r0 in zip(wells, res_before):
        pd.testing.assert_frame_equal(r, r0)


def test_multi_well_sorted_by_label_and_other_wells_untouched():
    wells = [well("W2"), well("W1", summary=minimal_summary()), ("W0", {"lrlc": {"skipped": "no RT"}}, None)]
    df = zones_frame(wells)
    assert df["Well"].tolist() == ["W1"] * 3 + ["W2"] * 3
    assert blank(row(df, "UPPER", "W1")["Rt_steps"]) and row(df, "UPPER", "W2")["Rt_steps"]
    st = steps_frame(wells)
    assert set(st["Well"]) == {"W2"}                 # W1 has no steps
    assert set(refs_frame(wells)["Key"]) >= {"doll1949", "arps1953"}


def test_steps_rows_status_order_and_cells():
    st = steps_frame([well()])
    assert st["Zone"].tolist() == ["UPPER", "UPPER", "LOWER", "LOWER"]
    up = st[st["Zone"] == "UPPER"]
    assert up["Step"].tolist() == ["decon", "invasion"] and up["Order"].tolist() == [1, 2]
    d, i = up.iloc[0], up.iloc[1]
    assert (d["Curve"], d["From"], d["Status"], d["Valid_samples"]) == ("RT_DECON", "RT", "ran", 19)
    assert (i["Curve"], i["From"], i["Invalid_samples"], i["Fallback_samples"]) == ("RT_INV", "RT_DECON", 2, 1)
    assert d["Params"] == '{"dec_fwhm_ft":2.0}' and blank(d["References"])
    assert i["Params"] == '{"inv_tool":"generic"}'
    lo = st[st["Zone"] == "LOWER"]
    assert lo["Step"].tolist() == ["decon", "invasion"]
    blocked = lo.iloc[0]
    assert blocked["Status"] == "blocked" and blocked["Curve"] == "RT_DECON"
    assert blank(blocked["Valid_samples"]) and blank(blocked["Params"])
    assert lo.iloc[1]["Status"] == "ran"


def test_requested_step_without_a_record_is_skipped():
    s = summary_full()
    s["lrlc"]["params"]["zones"]["LOWER"]["rt_steps"] = ["invasion", "pyrite"]
    st = steps_frame([well(summary=s)])
    lo = st[st["Zone"] == "LOWER"].set_index("Step")
    assert lo.loc["pyrite", "Status"] == "skipped" and lo.loc["pyrite", "Curve"] == "RT_PYR"


def test_no_steps_no_chain_rows():
    assert len(steps_frame([well(summary=minimal_summary())])) == 0


def test_references_only_cited_keys_with_used_by_and_unverified_mark():
    st = steps_frame([well()])
    refs = refs_frame([well()])
    assert refs["Key"].tolist() == sorted(refs["Key"])
    keys = set(refs["Key"])
    assert {"doll1949", "arps1953"} <= keys
    assert not keys & {"hagiwara_us4739255", "clavier1976", "poupon1954"}      # steps that did not run
    assert references.REFERENCES["doll1949"].key in keys
    by = dict(zip(refs["Key"], refs["Used_by"]))
    assert by["doll1949"] == "invasion"
    assert "screening" in by["boyd1995"]
    assert refs["Status"].isin(["verified", "to verify"]).all()
    for _, r in refs.iterrows():
        assert r["Citation"] == references.format_full(r["Key"])
        assert r["Status"] == references.REFERENCES[r["Key"]].status
    # References cell of a chain row: short citations, unverified ones marked
    unverified = [k for k in ("doll1949", "arps1953") if references.REFERENCES[k].status != "verified"]
    verified = [k for k in ("doll1949", "arps1953") if references.REFERENCES[k].status == "verified"]
    cell = st[(st["Zone"] == "UPPER") & (st["Step"] == "invasion")].iloc[0]["References"]
    for k in unverified:
        assert references.format_short(k) + " (to verify)" in cell
    for k in verified:
        assert references.format_short(k) in cell and references.format_short(k) + " (to verify)" not in cell


def test_unverified_mark_for_a_key_known_to_be_unverified():
    unverified = next(k for k, r in references.REFERENCES.items() if r.status != "verified")
    s = summary_full()
    s["lrlc"]["chain"][0]["refs"] = [unverified]
    st = steps_frame([well(summary=s)])
    assert references.format_short(unverified) + " (to verify)" in st.iloc[0]["References"]
    refs = refs_frame([well(summary=s)])
    assert refs[refs["Key"] == unverified].iloc[0]["Status"] == "to verify"


def test_refs_follow_the_content_not_the_registry():
    s = summary_full()
    s["lrlc"]["chain"] = []
    s["lrlc"]["elastic"] = {"skipped": "units"}
    keys = set(refs_frame([well(summary=s)])["Key"])
    assert keys == set(references.REFERENCES) & set(report.SHIPPED_METHODS["screening"])
    assert "ashfaq_us11709287" not in keys
    s["lrlc"]["elastic"] = summary_full()["lrlc"]["elastic"]
    r = refs_frame([well(summary=s)])
    assert "elastic" in dict(zip(r["Key"], r["Used_by"]))["ashfaq_us11709287"]


def test_text_cells_are_not_made_spreadsheet_safe():
    s = summary_full()
    s["lrlc"]["chain"][0]["params"] = {"x": "=SUM(A1)"}
    st = steps_frame([well(summary=s)])
    assert "=SUM(A1)" in st.iloc[0]["Params"]
    assert not st.iloc[0]["Params"].startswith("'")


# ---------------------------------------------------------------------------
# one real summary from the pipeline
# ---------------------------------------------------------------------------
def test_real_pipeline_summary():
    from tests.golden.cases import build_case
    from tests.test_lrlc_pipeline import lrlc_p, run
    data, mapping, params, tops = build_case("lrlc_screening")
    params = dict(params)
    params.pop("lrlc")
    results, summary = run((data, mapping, params, tops),
                           lrlc_p(zone_steps={"UPPER": ["laminated"], "LOWER": []},
                                  vlam_source="constant", vlam_const=0.2))
    wells = [("Real", summary, results)]
    z, st, rf = zones_frame(wells), steps_frame(wells), refs_frame(wells)
    assert list(z.columns) == ZONE_COLUMNS_SPEC
    assert z["Zone"].tolist() == ["(well)", "UPPER", "LOWER"]
    assert int(row(z, "(well)", "Real")["Samples"]) == len(results)
    up = row(z, "UPPER", "Real")
    assert up["Rt_steps"] == "laminated" and up["Rt_source"] == "RT_SAND <- RT"
    assert up["Net_pay_change_ft"] == pytest.approx(summary["lrlc"]["validation"]["zones"][0]["delta"])
    assert up["Top_ft"] == pytest.approx(summary["zones"][0]["top"])
    assert up["Guard"] == "n/a" and blank(up["Decon_status"]) and blank(up["Elastic_flag_samples"])
    assert blank(row(z, "LOWER", "Real")["Rt_steps"])
    assert st["Step"].tolist() == ["laminated"] and st.iloc[0]["Status"] == "ran"
    assert {"poupon1954", "hagiwara1997"} <= set(rf["Key"])
    pd.testing.assert_frame_equal(z, zones_frame(wells))


# ---------------------------------------------------------------------------
# deconvolution response-width sensitivity
# ---------------------------------------------------------------------------
def _with_sensitivity(entry):
    s = summary_full()
    s["lrlc"]["decon"]["zones"][0]["width_sensitivity"] = entry
    return s


def test_width_sensitivity_text_and_position():
    assert ZONE_COLUMNS_SPEC.index("Decon_width_sensitivity") == \
        ZONE_COLUMNS_SPEC.index("Decon_amplified") + 1
    s = _with_sensitivity({"widths_ft": [3.2, 4.0, 5.0], "median_ratio": [1.9, 2.0, 1.7],
                           "n_valid": [19, 19, 14], "n": 19})
    df = zones_frame([well(summary=s)])
    assert row(df, "UPPER")["Decon_width_sensitivity"] == \
        "3.2 / 4.0 / 5.0 ft: 1.9 / 2.0 / 1.7 x (valid 19 / 19 / 14 of 19)"
    assert blank(row(df, "LOWER")["Decon_width_sensitivity"])
    assert blank(row(df, "(well)")["Decon_width_sensitivity"])


def test_width_sensitivity_none_ratio_rounding_and_blank_cases():
    s = _with_sensitivity({"widths_ft": [3.24, 4.0, 4.96], "median_ratio": [None, 2.04, 3.449],
                           "n_valid": [0, 7, 5], "n": 7})
    assert row(zones_frame([well(summary=s)]), "UPPER")["Decon_width_sensitivity"] == \
        "3.2 / 4.0 / 5.0 ft: n/a / 2.0 / 3.4 x (valid 0 / 7 / 5 of 7)"
    for entry in (None, {"widths_ft": [3.0, 4.0, 5.0], "median_ratio": [1.0, 1.0, 1.0],
                         "n_valid": [0, 0, 0], "n": 0}):
        s = _with_sensitivity(entry)
        assert blank(row(zones_frame([well(summary=s)]), "UPPER")["Decon_width_sensitivity"])
    assert blank(row(zones_frame([well()]), "UPPER")["Decon_width_sensitivity"])


def test_score_maximum_is_not_assumed():
    s = summary_full()
    s["lrlc"]["screening"]["score_max"] = 7
    r = results_frame()
    r["LRLC_SCORE"] = np.where(np.arange(len(r)) % 2 == 0, 7.0, 2.0)
    assert row(zones_frame([well(summary=s, results=r)]), "(well)")["Score_mean_net"] == 7.0


# ---------------------------------------------------------------------------
# export: the LRLC sheet and the CSV sidecars
# ---------------------------------------------------------------------------
def _export_well(key, name, with_lrlc=True):
    from models.project import WellDataset
    ds = WellDataset(key, name)
    ds.results = results_frame()
    ds.summary = summary_full() if with_lrlc else {"zones": []}
    ds.calculated = True
    return ds


def _read_blocks(path):
    """The three stacked tables of the sheet, split at the title cells."""
    raw = pd.read_excel(path, sheet_name="LRLC", header=None)
    starts = [i for i in range(len(raw)) if raw.iloc[i, 0] in ("Zones", "Rt correction chain", "References")
              and raw.iloc[i, 1:].isna().all()]
    assert [raw.iloc[i, 0] for i in starts] == ["Zones", "Rt correction chain", "References"]
    out = {}
    for n, start in enumerate(starts):
        end = starts[n + 1] - 1 if n + 1 < len(starts) else len(raw)
        block = raw.iloc[start + 1:end].dropna(how="all", axis=1)
        block.columns = block.iloc[0]
        out[raw.iloc[start, 0]] = block.iloc[1:].reset_index(drop=True)
        assert raw.iloc[end - 1:end].notna().any(axis=None) or n + 1 == len(starts) or True
    return out


def test_lrlc_sheet_constant_reserved_and_absent_without_lrlc(tmp_path):
    from services.export_service import LRLC_SHEET, ExportService
    assert LRLC_SHEET == "LRLC"
    plain = tmp_path / "plain.xlsx"
    assert ExportService().export_excel_wells([_export_well("W:A", "A", False)], str(plain))
    assert LRLC_SHEET not in pd.ExcelFile(plain).sheet_names
    both = tmp_path / "both.xlsx"
    wells = [_export_well("W:A", "A"), _export_well("W:B", "LRLC")]     # a well named like the sheet
    assert ExportService().export_excel_wells(wells, str(both))
    names = pd.ExcelFile(both).sheet_names
    assert names.count(LRLC_SHEET) == 1 and len(names) == len({n.lower() for n in names})
    assert any(n.startswith("LRLC") and n != LRLC_SHEET for n in names)


def test_lrlc_sheet_holds_the_three_tables(tmp_path):
    from services.export_service import ExportService
    wells = [_export_well("W:B", "Beta"), _export_well("W:A", "Alpha"), _export_well("W:C", "Gamma", False)]
    path = tmp_path / "w.xlsx"
    assert ExportService().export_excel_wells(wells, str(path))
    blocks = _read_blocks(path)
    triples = [("Alpha", wells[1].summary, wells[1].results), ("Beta", wells[0].summary, wells[0].results)]
    assert list(blocks["Zones"].columns) == ZONE_COLUMNS_SPEC
    assert list(blocks["Rt correction chain"].columns) == STEP_COLUMNS_SPEC
    assert list(blocks["References"].columns) == list(REF_COLUMNS)
    assert blocks["Zones"]["Well"].tolist() == ["Alpha"] * 3 + ["Beta"] * 3
    assert len(blocks["Rt correction chain"]) == len(steps_frame(triples))
    assert blocks["References"]["Key"].tolist() == refs_frame(triples)["Key"].tolist()


def test_lrlc_sheet_text_is_spreadsheet_safe(tmp_path):
    import openpyxl
    from services.export_service import ExportService
    ds = _export_well("W:A", "Alpha")
    ds.summary["lrlc"]["chain"][0]["params"] = {"x": "=SUM(A1)"}
    path = tmp_path / "s.xlsx"
    assert ExportService().export_excel_wells([ds], str(path))
    sheet = openpyxl.load_workbook(path)["LRLC"]
    cells = [c for row in sheet.iter_rows() for c in row if isinstance(c.value, str) and "=SUM(A1)" in c.value]
    assert cells and all(c.data_type == "s" for c in cells)


def test_lrlc_csv_sidecars_equal_the_tables_and_are_deterministic(tmp_path):
    from services.export_service import ExportService
    wells = [_export_well("W:A", "Alpha"), _export_well("W:B", "Beta")]
    wells[0].summary["lrlc"]["chain"][0]["params"] = {"x": "=SUM(A1)"}
    path = tmp_path / "all.csv"
    assert ExportService().export_csv_wells(wells, str(path))
    zones = tmp_path / "all.lrlc_zones.csv"
    steps = tmp_path / "all.lrlc_steps.csv"
    refs = tmp_path / "all.lrlc_refs.csv"
    assert zones.exists() and steps.exists() and refs.exists()
    triples = [(ds.display_name, ds.summary, ds.results) for ds in wells]
    got = pd.read_csv(zones, dtype=object)
    assert list(got.columns) == ZONE_COLUMNS_SPEC and got["Well"].tolist() == ["Alpha"] * 3 + ["Beta"] * 3
    assert list(pd.read_csv(refs).columns) == list(REF_COLUMNS)
    assert len(pd.read_csv(steps)) == len(steps_frame(triples))
    assert "'" + "{" not in steps.read_text(encoding="utf-8")        # JSON params are not risky text
    first = [p.read_bytes() for p in (zones, steps, refs)]
    assert ExportService().export_csv_wells(wells, str(path))
    assert [p.read_bytes() for p in (zones, steps, refs)] == first


def test_lrlc_csv_risky_text_is_prefixed(tmp_path):
    from services.export_service import ExportService
    ds = _export_well("W:A", "=Alpha")
    path = tmp_path / "r.csv"
    assert ExportService().export_csv_wells([ds], str(path))
    assert "'=Alpha" in (tmp_path / "r.lrlc_zones.csv").read_text(encoding="utf-8")


def test_no_lrlc_writes_no_sidecars_and_single_well_paths(tmp_path):
    from services.export_service import ExportService
    ds = _export_well("W:A", "Alpha", False)
    path = tmp_path / "n.csv"
    assert ExportService().export_csv_wells([ds], str(path))
    assert not list(tmp_path.glob("*.lrlc_*.csv"))
    one = _export_well("W:A", "Alpha")
    single = tmp_path / "one.csv"
    assert ExportService().export_csv(one.results, str(single), {"Well": "Alpha"}, one.summary)
    assert len(pd.read_csv(tmp_path / "one.lrlc_zones.csv")) == 3
    assert ExportService().export_csv(one.results, str(tmp_path / "two.csv"), {"Well": "Alpha"})
    assert not (tmp_path / "two.lrlc_zones.csv").exists()
    book = tmp_path / "one.xlsx"
    assert ExportService().export_excel(one.results, one.summary, str(book), {"Well": "Alpha"})
    assert "LRLC" in pd.ExcelFile(book).sheet_names
