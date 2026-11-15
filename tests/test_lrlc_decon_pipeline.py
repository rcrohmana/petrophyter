"""Rt deconvolution (chain step ``decon``) through the pipeline: columns, guard rules G1 / G3 / G4,
well-only keys, per-zone ratio, segment agreement, summary block, off-and-idle guards."""
import copy
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from models.app_model import AppModel
from modules import param_scopes as ps
from modules.lrlc.config import LRLC_PARAM_DEFAULTS, resolve_lrlc
from modules.pipeline import PARAM_DEFAULTS, run_pipeline
from modules.uncertainty import LRLC_DECON, lrlc_not_varied
from tests.golden.cases import DECON_BEDS, build_case, decon_truth
from tests.test_lrlc_pipeline import lrlc_p
from tests.test_lrlc_pipeline_l2 import MAPPING, PARAMS, laminated_well, ts_p

L4_COLUMNS = {"RT_DECON", "AI", "VPVS", "ELASTIC_FLAG"}
BASELINE = {"SW_BASE", "NET_PAY_BASE_FLAG"}


def codes(summary):
    return [i["code"] for i in summary["issues"]]


def issue_texts(summary, code):
    return [i["text"] for i in summary["issues"] if i["code"] == code]


def case_params(steps=("decon",), fallback="nan", zone_extra=None, **ladder):
    data, mapping, params, tops = build_case("lrlc_decon")
    params = copy.deepcopy(params)
    resolved = params["lrlc"]["resolved"]
    resolved["default"] = {**resolved["default"], "rt_steps": list(steps), "rt_fallback": fallback,
                           **ladder}
    for zone, row in resolved["zones"].items():
        resolved["zones"][zone] = {**row, "rt_steps": list(steps), "rt_fallback": fallback,
                                   **ladder, **((zone_extra or {}).get(zone) or {})}
    return data, mapping, params, tops


def run_case(**kw):
    data, mapping, params, tops = case_params(**kw)
    return data, run_pipeline(data.copy(), mapping, params, formation_tops=tops)


# ---- columns, Sw from RT_SW, RT untouched -------------------------------------------------
def test_step_adds_the_columns_and_sw_reads_rt_sw():
    data, (r, s) = run_case()
    _, (idle, _) = run_case(steps=())
    assert set(r.columns) - set(idle.columns) == {"RT_DECON", "RT_SW"} | BASELINE
    np.testing.assert_array_equal(r["RT"].to_numpy(), data["RT"].to_numpy())
    np.testing.assert_array_equal(r["RT_SW"].to_numpy(), r["RT_DECON"].to_numpy())
    ok = r["RT_SW"].notna()
    assert ok.sum() > 150 and r.loc[~ok, "SW"].isna().all()
    # Archie with a = 1, m = n = 2, Rw 0.05 reads RT_SW (not RT)
    expected = np.minimum(np.sqrt(0.05 / (r["RT_SW"] * r["PHIE"] ** 2)), 1.0)
    np.testing.assert_allclose(r.loc[ok, "SW"], expected[ok], rtol=1e-9)
    assert [c["step"] for c in s["lrlc"]["chain"]] == ["decon", "decon"]


def test_thin_sands_rise_toward_the_true_beds():
    data, (r, _) = run_case()
    depth = r["DEPTH"].to_numpy()
    truth = decon_truth(depth)
    decon, rt = r["RT_DECON"].to_numpy(), r["RT"].to_numpy()
    for top, bottom, value in DECON_BEDS:
        if value < 40.0 or bottom - top > 4.0:
            continue
        inside = (depth >= top + 0.75) & (depth <= bottom - 0.75) & np.isfinite(decon)
        assert inside.sum() >= 2
        assert (decon[inside] > 3.0 * rt[inside]).all()
        np.testing.assert_allclose(decon[inside], value, rtol=0.25)
    thick = (depth >= 1026) & (depth <= 1036)
    np.testing.assert_allclose(decon[thick], truth[thick], rtol=0.05)


def test_auto_rw_and_rsh_read_the_measured_rt():
    def estimates(steps):
        data, mapping, params, tops = case_params(steps=steps)
        params["rw_mode"] = "auto"
        _, s = run_pipeline(data.copy(), mapping, params, formation_tops=tops)
        return s["rw"], s["rsh"], s["rw_source"], s["rsh_source"]

    assert estimates(("decon",)) == estimates(())


# ---- guard: G1, G3, G4, no Thomas-Stieber --------------------------------------------------
def lam_run(steps=("decon",), guard=True, sbc=False, ts=True, clean_zone=False):
    frame, _ = laminated_well()
    lrlc = ts_p(steps=steps) if ts else lrlc_p(steps=list(steps), zones=())
    if not guard:
        lrlc["guard"] = {"enabled": False}
    if clean_zone:      # a classified zone that the guard does not call laminated
        lrlc["guard"] = {**lrlc.get("guard", {}), "enabled": True, "min_vlam": 0.6}
    if sbc:
        lrlc["curves"]["RT_SBC"] = "RT"
    return run_pipeline(frame.copy(), dict(MAPPING), {**PARAMS, "lrlc": lrlc})


def test_g1_drops_decon_in_a_laminated_zone_and_counts_it():
    r, s = lam_run()
    assert r["RT_DECON"].isna().all()
    np.testing.assert_array_equal(r["RT_SW"].to_numpy(), r["RT"].to_numpy())
    blocked = issue_texts(s, "LRLC_GUARD_BLOCKED")
    assert blocked == ["Deconvolution not applied in the unzoned interval: laminated (guard); "
                       "use the laminated-sand correction."]
    block = s["lrlc"]["decon"]
    assert block["zones"][0]["status"] == "guard_dropped_laminated"
    assert block["counts"]["guard_dropped_laminated"] == len(r)
    assert s["lrlc"]["guard"]["zones"][0]["blocked_steps"] == ["decon"]


def test_guard_off_warns_and_keeps_the_values():
    r, s = lam_run(guard=False)
    assert r["RT_DECON"].notna().any()
    assert not issue_texts(s, "LRLC_GUARD_BLOCKED")
    warned = issue_texts(s, "LRLC_GUARD_WARNED")
    assert len(warned) == 1 and warned[0].startswith("Deconvolution applied in the unzoned interval")
    assert s["lrlc"]["decon"]["counts"]["guard_warned"] == len(r)


def test_g4_blocks_a_marked_rt_with_and_without_thomas_stieber():
    for ts in (False, True):
        r, s = lam_run(sbc=True, ts=ts, clean_zone=ts)
        assert r["RT_DECON"].isna().all(), ts
        blocked = issue_texts(s, "LRLC_GUARD_BLOCKED")
        assert blocked == ["Deconvolution not applied in the unzoned interval: RT is marked "
                           "shoulder-bed corrected (guard)."], ts
        zone = s["lrlc"]["decon"]["zones"][0]
        assert zone["status"] == "guard_dropped_shoulder"
        assert s["lrlc"]["decon"]["counts"]["guard_dropped_shoulder"] == len(r)
    # without Thomas-Stieber the zone is also reported as unclassified (info)
    assert "LRLC_GUARD_NO_TS" in codes(lam_run(sbc=True, ts=False)[1])


def test_g1_and_g4_together_give_one_message_per_zone_and_step():
    _, s = lam_run(sbc=True)
    blocked = issue_texts(s, "LRLC_GUARD_BLOCKED")
    assert len(blocked) == 1 and "laminated (guard)" in blocked[0]
    assert s["lrlc"]["decon"]["zones"][0]["status"] == "guard_dropped_laminated"


def test_unclassified_zone_runs_decon_with_an_info_note():
    r, s = lam_run(ts=False)
    assert r["RT_DECON"].notna().any()
    assert "LRLC_GUARD_NO_TS" in codes(s) and not issue_texts(s, "LRLC_GUARD_BLOCKED")
    assert s["lrlc"]["decon"]["counts"]["lamination_unknown"] == len(r)


def test_g3_info_when_decon_and_laminated_are_both_selected_in_a_clean_zone():
    r, s = lam_run(steps=("decon", "laminated"), clean_zone=True)
    assert "LRLC_GUARD_COMBINED" in codes(s)
    assert [c["step"] for c in s["lrlc"]["chain"]] == ["decon", "laminated"]
    assert r["RT_DECON"].notna().any()
    # in a laminated zone G1 drops decon first, so there is nothing to combine
    _, s2 = lam_run(steps=("decon", "laminated"))
    assert "LRLC_GUARD_COMBINED" not in codes(s2)


# ---- invalid reference, fallback ------------------------------------------------------------
def test_missing_reference_gives_nan_or_the_previous_rt():
    data, (nan_r, nan_s) = run_case(dec_hires_source="HIRES")
    assert nan_r["RT_DECON"].isna().all() and nan_r["RT_SW"].isna().all()
    assert "LRLC_DECON_NO_HIRES" in codes(nan_s)
    block = nan_s["lrlc"]["decon"]
    assert block["zones"][0]["status"] == "no_hires" and block["counts"]["no_hires"] > 0
    assert block["hires"]["curve"] is None
    _, (prev_r, _) = run_case(dec_hires_source="HIRES", fallback="previous")
    np.testing.assert_array_equal(prev_r["RT_SW"].to_numpy(), data["RT"].to_numpy())


def test_auto_reference_prefers_the_rxo_role_then_the_mapped_rhob():
    _, (_, s) = run_case()
    assert s["lrlc"]["decon"]["hires"] == {"curve": "RXO", "column": "RXO", "source": "auto",
                                           "log_domain": True}
    data, mapping, params, tops = case_params()
    params["lrlc"]["curves"]["RXO"] = None
    _, s2 = run_pipeline(data.copy(), mapping, params, formation_tops=tops)
    assert s2["lrlc"]["decon"]["hires"] == {"curve": "RHOB", "column": "RHOB", "source": "auto",
                                            "log_domain": False}


# ---- settings: well-only keys, per-zone ratio -----------------------------------------------
def test_well_only_keys_are_read_from_the_well_default():
    _, (base, s_base) = run_case()
    _, (zoned, s_zone) = run_case(zone_extra={"UPPER": {"dec_fwhm_ft": 1.0, "dec_solver": "mult"}})
    pd.testing.assert_series_equal(zoned["RT_DECON"], base["RT_DECON"], check_exact=True)
    assert s_zone["lrlc"]["decon"]["params"]["fwhm_ft"] == 4.0
    assert s_zone["lrlc"]["decon"]["params"]["solver"] == "lsq"


def test_resolve_reads_well_only_keys_at_the_well_default_for_every_zone():
    project = {"default": {"dec_fwhm_ft": 6.0}, "zones": {"UPPER": {"dec_fwhm_ft": 2.0,
                                                                    "dec_max_ratio": 5.0}}}
    well = {"default": {"dec_solver": "mult"}, "zones": {"UPPER": {"dec_solver": "lsq",
                                                                   "dec_misfit_warn": 0.3}}}
    upper = resolve_lrlc(project, well, "UPPER")
    assert upper["dec_fwhm_ft"] == 6.0 and upper["dec_solver"] == "mult"      # well-only: well default
    assert upper["dec_max_ratio"] == 5.0 and upper["dec_misfit_warn"] == 0.3  # zone-capable: the zone
    assert resolve_lrlc(project, well, "LOWER")["dec_max_ratio"] == 10.0
    assert resolve_lrlc(project, well, None)["dec_fwhm_ft"] == 6.0


def test_max_ratio_is_resolved_per_zone():
    _, (r, s) = run_case(zone_extra={"UPPER": {"dec_max_ratio": 2.0}})
    zones = {z["zone"]: z for z in s["lrlc"]["decon"]["zones"]}
    assert zones["UPPER"]["max_ratio"] == 2.0 and zones["LOWER"]["max_ratio"] == 10.0
    assert zones["UPPER"]["n_amplified"] > 0 and zones["LOWER"]["n_amplified"] == 0
    assert np.isnan(r.loc[r["DEPTH"] == 1012.0, "RT_DECON"]).all()
    assert "LRLC_DECON_AMPLIFIED" in codes(s)


def test_zone_segments_agree_with_the_whole_well():
    data, mapping, params, tops = case_params()
    whole, s_whole = run_pipeline(data.copy(), mapping, params, formation_tops=tops)
    plan = ps.zone_plan({**PARAM_DEFAULTS, **params}, None,
                        {"LOWER": {"m": ps.make_entry(ps.MANUAL, 2.0)}}, None, ("UPPER", "LOWER"))
    seg, s_seg = run_pipeline(data.copy(), mapping, {**params, "zone_plan": plan}, formation_tops=tops)
    for column in ("RT_DECON", "RT_SW", "SW"):
        pd.testing.assert_series_equal(seg[column], whole[column], check_exact=True)
    assert {c["segment"] for c in s_seg["lrlc"]["chain"]} == {"zone", "rest"}
    assert s_seg["lrlc"]["decon"]["boundaries"] == s_whole["lrlc"]["decon"]["boundaries"]


def test_the_derive_runs_once_per_well(monkeypatch):
    from modules.lrlc import chain, decon_step

    calls = []
    real = chain.DERIVES["decon_well"]

    def counting(**kw):
        calls.append(1)
        return real.fn(**kw)

    monkeypatch.setitem(chain.DERIVES, "decon_well",
                        chain.DeriveSpec(real.name, real.scope, counting, real.outputs))
    data, mapping, params, tops = case_params()
    plan = ps.zone_plan({**PARAM_DEFAULTS, **params}, None,
                        {"LOWER": {"m": ps.make_entry(ps.MANUAL, 2.0)}}, None, ("UPPER", "LOWER"))
    run_pipeline(data.copy(), mapping, {**params, "zone_plan": plan}, formation_tops=tops)
    assert len(calls) == 1
    calls.clear()
    run_pipeline(data.copy(), mapping, case_params(steps=())[2], formation_tops=tops)
    assert calls == []
    assert decon_step.STEP.kind == "vertical" and decon_step.STEP.varied == ()


# ---- summary block ------------------------------------------------------------------------
def test_decon_summary_block_keys():
    _, (_, s) = run_case()
    block = s["lrlc"]["decon"]
    assert set(block) == {"hires", "params", "zones", "windows", "n_beds", "boundaries", "edits",
                          "counts"}
    assert {z["zone"] for z in block["zones"]} == {"UPPER", "LOWER"}
    assert set(block["zones"][0]) == {"zone", "status", "max_ratio", "n_active", "n_valid", "width_sensitivity",
                                      "n_amplified", "misfit_rms"}
    assert {"top", "bottom", "n_rows", "n_beds", "lam", "misfit_rms", "misfit_max",
            "status"} <= set(block["windows"][0])
    assert block["n_beds"] == len(DECON_BEDS) and block["edits"] == {"add": [], "remove": []}
    found = [d for ds in block["boundaries"].values() for d in ds]
    truth = [b[1] for b in DECON_BEDS[:-1]]
    assert len(found) == len(truth)
    np.testing.assert_allclose(sorted(found), truth, atol=0.5)
    assert block["params"]["label"] == "generic, confirm with tool charts"
    # the summary params carry the changed ladder keys only
    assert "dec_fwhm_ft" not in s["lrlc"]["params"]["default"]
    _, (_, s2) = run_case(dec_fwhm_ft=3.0)
    assert s2["lrlc"]["params"]["default"]["dec_fwhm_ft"] == 3.0
    assert s2["lrlc"]["decon"]["params"]["fwhm_ft"] == 3.0


# ---- off and idle --------------------------------------------------------------------------
def test_lrlc_off_has_no_key_no_column_and_the_same_hash():
    data, mapping, params, tops = case_params()
    params.pop("lrlc")
    r, s = run_pipeline(data.copy(), mapping, params, formation_tops=tops)
    assert "lrlc" not in s and not (L4_COLUMNS | {"RT_SW"}) & set(r.columns)
    model = AppModel()
    model.las_data = data
    before = model.well_params_hash()
    model.project.lrlc["elastic"]["enabled"] = True
    model.project.lrlc["params"]["default"] = {"rt_steps": ["decon"], "dec_fwhm_ft": 3.0}
    assert "lrlc" not in model.params_for_well(model._well)
    assert model.well_params_hash() == before


def test_lrlc_on_changes_the_hash_with_a_decon_setting():
    data, _, _, _ = case_params()
    model = AppModel()
    model.las_data = data
    model.project.lrlc["enabled"] = True
    on = model.well_params_hash()
    model.project.lrlc["params"]["default"] = {"dec_fwhm_ft": 3.0}
    assert model.well_params_hash() != on
    model.project.lrlc["params"]["default"] = {}
    model.project.lrlc["elastic"]["enabled"] = True
    assert model.well_params_hash() != on


def test_on_without_the_new_step_adds_nothing_of_l4():
    data, (idle, s) = run_case(steps=())
    assert not L4_COLUMNS & set(idle.columns)
    block = s["lrlc"]
    assert "decon" not in block and "elastic" not in block
    assert "score_max" not in block["screening"] and "ELASTIC" not in block["screening"]["criteria"]
    assert not [k for k in block["params"]["default"] if k.startswith(("dec_", "el_"))]
    # with the elastic switch on but no DTS: still no L4 column, only the info issue
    data, mapping, params, tops = case_params(steps=())
    params["lrlc"]["elastic"] = {"enabled": True}
    r, s2 = run_pipeline(data.copy(), mapping, params, formation_tops=tops)
    assert not L4_COLUMNS & set(r.columns) and "elastic" not in s2["lrlc"]
    assert "LRLC_ELASTIC_NO_DTS" in codes(s2)
    for column in ("SW", "LRLC_SCORE", "LRLC_FLAG", "NET_PAY_FLAG"):
        pd.testing.assert_series_equal(r[column], idle[column], check_exact=True)


# ---- invasion with decon, Monte Carlo text -------------------------------------------------
def test_invasion_after_decon_warns_about_the_unequal_resolution():
    data, mapping, params, tops = build_case("lrlc_invasion")
    params = copy.deepcopy(params)
    resolved = params["lrlc"]["resolved"]
    resolved["default"] = {**resolved["default"], "rt_steps": ["decon", "invasion"]}
    _, s = run_pipeline(data.copy(), mapping, params)
    assert "LRLC_INV_DECON_MISMATCH" in codes(s)
    assert [c["step"] for c in s["lrlc"]["chain"]] == ["decon", "invasion"]


def test_monte_carlo_not_varied_text_names_the_frozen_deconvolved_rt():
    well = SimpleNamespace(base_summary={"lrlc": {"chain": [{"step": "decon"}]}}, segments=[])
    items, laminated = lrlc_not_varied([well])
    assert LRLC_DECON in items and LRLC_DECON == "deconvolved Rt (frozen)" and not laminated
    assert lrlc_not_varied([SimpleNamespace(base_summary={"lrlc": {"chain": []}},
                                            segments=[])])[0] == ()


# ---- a zone's result does not depend on the neighbouring zone's switch -----------------------------
def test_upper_result_is_the_same_whether_the_step_is_on_in_lower_or_not():
    _, (both, s_both) = run_case()
    _, (alone, s_alone) = run_case(zone_extra={"LOWER": {"rt_steps": []}})
    upper = both["ZONE"].astype(str).str.upper().eq("UPPER").to_numpy() if "ZONE" in both.columns else (
        both["DEPTH"].to_numpy() < 1040.0)
    assert upper.sum() > 50
    np.testing.assert_array_equal(np.isfinite(both["RT_DECON"].to_numpy()[upper]),
                                  np.isfinite(alone["RT_DECON"].to_numpy()[upper]))
    np.testing.assert_allclose(both["RT_DECON"].to_numpy()[upper], alone["RT_DECON"].to_numpy()[upper],
                               rtol=1e-12, equal_nan=True)
    assert alone["RT_DECON"].to_numpy()[~upper].tolist() == [] or np.isnan(
        alone["RT_DECON"].to_numpy()[~upper]).all()

    def windows(s, lo, hi):
        return [(w["top"], w["bottom"], w["lam"], w["status"]) for w in s["lrlc"]["decon"]["windows"]
                if w["bottom"] >= lo and w["top"] <= hi]

    lo, hi = float(both["DEPTH"][upper].min()), float(both["DEPTH"][upper].max())
    assert windows(s_alone, lo, hi) == windows(s_both, lo, hi) != []
    # nothing is reported for the zone without the step
    assert not [i for i in s_alone["issues"] if i["code"].startswith("LRLC_DECON") and i.get("zone") == "LOWER"]
    assert [z["zone"] for z in s_alone["lrlc"]["decon"]["zones"]] == ["UPPER"]
