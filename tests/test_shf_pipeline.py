"""Saturation-height pipeline stage: columns, counts, contacts, TVD, pay and Monte Carlo hold."""
import copy

import numpy as np
import pandas as pd
import pytest

from models.app_model import AppModel
from modules.pipeline import PARAM_DEFAULTS, run_pipeline
from modules.shf import BASIS_CORE, BASIS_LOG, ShfFit
from modules.shf_stage import apply_shf
from tests.golden.cases import (
    FULL_MAPPING, ROCK_TYPE_DEFS, build_case, fixture_frame, make_tops)

NEW_COLUMNS = {"SW_SHF", "HAFWL", "SW_SHF_RESID"}


def fit_dict(c=0.45, d=-0.55, basis=BASIS_CORE, key="All"):
    return ShfFit(rock_type=key, model="power", params={"c": c, "d": d}, basis=basis,
                  n_samples=10, n_points=100).to_dict()


def shf_p(fits=None, contacts=None, **over):
    """A ``p["shf"]`` payload as ``AppModel.params_for_well`` builds it."""
    shf = {"enabled": True, "use_for_pay": False, "phie_source": "PHIE", "perm_source": "auto",
           "fallback": "none", "fits": fits if fits is not None else {"All": fit_dict()},
           "fluids": {"water": 1.03, "oil": 0.75, "gas": 0.25},
           "sigma_cos_res": {"oil": 26.0, "gas": 50.0},
           "contacts": contacts if contacts is not None else
           {"datum": "TVD", "kb_ft": None, "default": {"fwl": 1090.0, "fluid": "oil"},
            "zones": {}}}
    shf.update(over)
    return shf


@pytest.fixture(scope="module")
def log():
    return fixture_frame("sample_log_data")


def run(log, shf=None, mapping=None, tops=None, **params):
    p = dict(params)
    if shf is not None:
        p["shf"] = shf
    return run_pipeline(log.copy(), dict(mapping or FULL_MAPPING), p, formation_tops=tops)


@pytest.fixture(scope="module")
def base(log):
    return run(log)


def issue_codes(summary):
    return [i["code"] for i in summary["issues"]]


# ---- off means untouched --------------------------------------------------------------------
def test_params_have_no_shf_key_unless_enabled():
    model = AppModel()
    off = model.params_for_well()
    assert "shf" not in off and "shf" not in PARAM_DEFAULTS
    hash_off = model.well_params_hash()
    model.project.shf["enabled"] = True
    model.project.shf["fits"] = {"All": fit_dict()}
    on = model.params_for_well()
    assert set(on["shf"]) == {"enabled", "use_for_pay", "phie_source", "perm_source", "fallback",
                              "fits", "fluids", "sigma_cos_res", "contacts"}
    assert on["shf"]["sigma_cos_res"] == {"oil": model.project.shf["sigma_cos"]["oil-water"],
                                          "gas": model.project.shf["sigma_cos"]["gas-water"]}
    assert model.well_params_hash() != hash_off
    model.project.shf["enabled"] = False
    assert model.well_params_hash() == hash_off


def test_disabled_run_has_no_shf_output(base):
    results, summary = base
    assert not NEW_COLUMNS & set(results.columns) and "SW_PAY" not in results.columns
    assert "shf" not in summary


def test_enabled_adds_only_the_documented_columns_and_sw_is_unchanged(log, base):
    results, summary = run(log, shf_p())
    assert set(results.columns) - set(base[0].columns) == NEW_COLUMNS
    pd.testing.assert_frame_equal(results[base[0].columns], base[0])
    extra = set(summary) - set(base[1])
    assert extra == {"shf"}
    for key in ("net_pay", "hcpv_net_pay", "avg_sw_pay"):
        assert summary[key] == base[1][key]
    assert summary["shf"]["use_for_pay"] is False and summary["shf"]["pay_active"] is False
    s = summary["shf"]
    for key in ("basis", "tvd_source", "perm_source", "phie_source", "fluids", "contacts",
                "counts", "stats"):
        assert key in s
    assert s["basis"] == BASIS_CORE and s["perm_source"] == "PERM_TIMUR"
    assert set(s["stats"]) == {"well", "zones", "rock_types"}
    assert set(s["stats"]["well"]) >= {"n", "bias", "rmse", "mae", "r2", "basis"}


def test_residual_is_resistivity_minus_capillary_sw(log):
    results, _ = run(log, shf_p())
    np.testing.assert_allclose(results["SW_SHF_RESID"], results["SW"] - results["SW_SHF"],
                               equal_nan=True)


def test_stats_use_the_comparison_mask(log):
    results, summary = run(log, shf_p())
    m = ((results["NET_RES_FLAG"] == 1) & (results["HAFWL"] > 0)
         & results["SW"].notna() & results["SW_SHF"].notna())
    st = summary["shf"]["stats"]["well"]
    assert st["n"] == int(m.sum()) > 0
    d = (results["SW"] - results["SW_SHF"])[m]
    assert st["bias"] == pytest.approx(d.mean())
    assert st["rmse"] == pytest.approx(np.sqrt((d ** 2).mean()))
    assert st["mae"] == pytest.approx(d.abs().mean())


# ---- height, water leg, counts ----------------------------------------------------------------
def test_height_is_fwl_minus_md_and_water_leg_is_one(log):
    results, summary = run(log, shf_p())
    np.testing.assert_allclose(results["HAFWL"], 1090.0 - results["DEPTH"])
    leg = results["HAFWL"] <= 0
    assert leg.any()
    assert (results.loc[leg, "SW_SHF"] == 1.0).all()
    assert (results.loc[leg, "HAFWL"] < 1e-9).all() and (results.loc[leg, "HAFWL"] <= 0).all()
    assert summary["shf"]["counts"]["water_leg_samples"] == int(leg.sum())
    assert summary["shf"]["tvd_source"] == "MD (assumed vertical)"
    assert summary["shf"]["fluids"]["(unzoned)"]["delta_rho"] == pytest.approx(0.28)


def test_every_sample_lands_in_one_count(log):
    results, summary = run(log, shf_p())
    c = summary["shf"]["counts"]
    assert c["samples"] == len(results)
    assert (c["samples_no_contact"] + c["samples_no_tvd"] + c["samples_no_kphi"]
            + c["samples_unclassified"] + sum(c["samples_no_model"].values())
            + c["samples_modelled"]) == len(results)      # the water leg is modelled (Sw = 1)
    assert c["samples_modelled"] == int(results["SW_SHF"].notna().sum())


def test_no_contact_is_counted_and_blank(log):
    results, summary = run(log, shf_p(contacts={"datum": "TVD", "kb_ft": None, "default": None,
                                                "zones": {}}))
    assert results["SW_SHF"].isna().all() and results["HAFWL"].isna().all()
    assert summary["shf"]["counts"]["samples_no_contact"] == len(results)
    assert "SHF_NO_CONTACT" in issue_codes(summary)


def test_missing_perm_column_is_counted_no_kphi(log):
    results, summary = run(log, shf_p(perm_source="PERM_RT"))
    assert summary["shf"]["perm_source"] is None
    live = results["HAFWL"] > 0
    assert summary["shf"]["counts"]["samples_no_kphi"] == int(live.sum())
    assert results.loc[live, "SW_SHF"].isna().all()
    assert "SHF_NO_PERM_PHI" in issue_codes(summary)


def test_perm_source_named_column_is_used(log):
    results, summary = run(log, shf_p(perm_source="PERM_WR"))
    assert summary["shf"]["perm_source"] == "PERM_WR"
    assert results["SW_SHF"].notna().any()


def test_no_model_and_fallback(log):
    data, mapping, params, tops = build_case("rock_typing_enabled")
    only_one = {"1": fit_dict(key="1")}
    results, summary = run_pipeline(data, mapping, {**params, "shf": shf_p(only_one)},
                                    formation_tops=tops)
    c = summary["shf"]["counts"]
    assert c["samples_no_model"] and set(c["samples_no_model"]) <= {"2", "3"}
    assert "SHF_NO_MODEL" in issue_codes(summary)
    typed = results["ROCK_TYPE"].astype(int)
    live = results["HAFWL"] > 0
    assert results.loc[live & (typed == 2), "SW_SHF"].isna().all()
    # a pooled fit fills the types that have none
    pooled = {"1": fit_dict(key="1"), "All": fit_dict(c=0.6, key="All")}
    _, s2 = run_pipeline(data, mapping, {**params, "shf": shf_p(pooled, fallback="pooled")},
                         formation_tops=tops)
    c2 = s2["shf"]["counts"]
    assert not c2["samples_no_model"] and c2["samples_pooled"]
    assert c2["samples_modelled"] > c["samples_modelled"]


def test_rock_typing_off_uses_the_all_fit(log):
    results, summary = run(log, shf_p({"All": fit_dict(), "1": fit_dict(c=0.9, key="1")}))
    assert summary["shf"]["rock_type_basis"] == "All"
    assert summary["shf"]["counts"]["samples_unclassified"] == 0
    assert summary["shf"]["stats"]["rock_types"] == []
    only_typed = run(log, shf_p({"1": fit_dict(key="1")}))[1]
    assert only_typed["shf"]["counts"]["samples_no_model"] == {
        "All": only_typed["shf"]["counts"]["samples"] - only_typed["shf"]["counts"][
            "water_leg_samples"] - only_typed["shf"]["counts"]["samples_no_kphi"]}


def test_zone_scoped_rock_types_use_the_all_fit():
    data, mapping, params, tops = build_case("rock_typing_enabled")
    per_type = {"All": fit_dict(), "1": fit_dict(c=0.9, key="1"), "2": fit_dict(c=0.2, key="2")}
    scoped = copy.deepcopy(params)
    scoped["rock_types"]["fit_scope"] = "zone"
    a, sa = run_pipeline(data, mapping, {**scoped, "shf": shf_p(per_type)}, formation_tops=tops)
    b, _ = run_pipeline(data, mapping, {**scoped, "shf": shf_p({"All": fit_dict()})},
                        formation_tops=tops)
    pd.testing.assert_series_equal(a["SW_SHF"], b["SW_SHF"])
    issue = [i for i in sa["issues"] if i["code"] == "SHF_ZONE_SCOPE_RT"]
    assert issue and issue[0]["severity"] == "info"
    assert sa["shf"]["counts"]["samples_unclassified"] == 0
    # global ids: the per-type fits are used
    c, sc = run_pipeline(data, mapping, {**params, "shf": shf_p(per_type)}, formation_tops=tops)
    assert not c["SW_SHF"].equals(b["SW_SHF"])
    assert "SHF_ZONE_SCOPE_RT" not in issue_codes(sc)
    assert {r["rock_type"] for r in sc["shf"]["stats"]["rock_types"]} <= {1, 2, 3}


# ---- zones and contacts -----------------------------------------------------------------------
def zone_contacts():
    return {"datum": "TVD", "kb_ft": None, "default": {"fwl": 1090.0, "fluid": "oil"},
            "zones": {"UPPER": {"fwl": 1060.0, "fluid": "gas"}}}


def test_zone_contact_overrides_default_and_fluid_follows(log):
    results, summary = run(log, shf_p(contacts=zone_contacts()), tops=make_tops())
    up = results["ZONE"] == "UPPER"
    assert up.any() and (~up).any()
    np.testing.assert_allclose(results.loc[up, "HAFWL"], 1060.0 - results.loc[up, "DEPTH"])
    np.testing.assert_allclose(results.loc[~up, "HAFWL"], 1090.0 - results.loc[~up, "DEPTH"])
    f = summary["shf"]["fluids"]
    assert f["UPPER"]["fluid"] == "gas" and f["UPPER"]["delta_rho"] == pytest.approx(0.78)
    assert f["LOWER"]["fluid"] == "oil" and f["LOWER"]["contact"] == "default"
    assert [z["zone"] for z in summary["shf"]["stats"]["zones"]] == ["UPPER", "LOWER"]


def test_zone_without_default_has_no_contact(log):
    contacts = {"datum": "TVD", "kb_ft": None, "default": None,
                "zones": {"UPPER": {"fwl": 1060.0, "fluid": "oil"}}}
    results, summary = run(log, shf_p(contacts=contacts), tops=make_tops())
    lower = results["ZONE"] == "LOWER"
    assert results.loc[lower, "SW_SHF"].isna().all()
    assert summary["shf"]["counts"]["samples_no_contact"] == int(lower.sum())


def test_zone_segment_path_matches_whole_well_path(log):
    tops = make_tops()
    whole = run(log, shf_p(contacts=zone_contacts()), tops=tops)
    from modules import param_scopes as ps
    zone_plan = ps.zone_plan({**PARAM_DEFAULTS}, None,
                             {"LOWER": {"m": ps.make_entry(ps.MANUAL, PARAM_DEFAULTS["m"])}},
                             None, ("UPPER", "LOWER"))
    assert zone_plan
    split = run(log, shf_p(contacts=zone_contacts()), tops=tops, zone_plan=zone_plan)
    for col in ("SW", "SW_SHF", "HAFWL", "SW_SHF_RESID"):
        np.testing.assert_allclose(split[0][col], whole[0][col], rtol=1e-9, equal_nan=True,
                                   err_msg=col)
    assert split[1]["shf"]["counts"] == whole[1]["shf"]["counts"]


# ---- TVD --------------------------------------------------------------------------------------
def test_deviated_well_uses_the_tvd_curve(log):
    dev = log.copy()
    dev["TVD"] = 0.8 * dev["DEPTH"]
    contacts = {"datum": "TVD", "kb_ft": None, "default": {"fwl": 870.0, "fluid": "oil"},
                "zones": {}}
    with_tvd, summary = run(dev, shf_p(contacts=contacts), mapping={**FULL_MAPPING, "TVD": "TVD"})
    np.testing.assert_allclose(with_tvd["HAFWL"], 870.0 - 0.8 * with_tvd["DEPTH"], atol=1e-9)
    assert summary["shf"]["tvd_source"].startswith("TVD curve")
    vertical, vsum = run(dev, shf_p(contacts=contacts))
    np.testing.assert_allclose(vertical["HAFWL"], 870.0 - vertical["DEPTH"], atol=1e-9)
    assert vsum["shf"]["tvd_source"] == "MD (assumed vertical)"
    assert not np.allclose(with_tvd["HAFWL"], vertical["HAFWL"])


def test_unmapped_tvd_curve_note_says_heights(log):
    dev = log.copy()
    dev["TVD"] = 0.8 * dev["DEPTH"]
    _, summary = run(dev, shf_p())
    notes = [i["text"] for i in summary["issues"] if i["code"] == "SHF_TVD_NOTE"]
    assert any("heights assume a vertical well" in t for t in notes)


def test_tvdss_contact_needs_kb(log):
    ss = {"datum": "TVDSS", "kb_ft": 100.0, "default": {"fwl": 990.0, "fluid": "oil"},
          "zones": {}}
    with_kb, summary = run(log, shf_p(contacts=ss))
    plain, _ = run(log, shf_p())
    np.testing.assert_allclose(with_kb["HAFWL"], plain["HAFWL"])
    assert summary["shf"]["fluids"]["(unzoned)"]["fwl_tvd"] == pytest.approx(1090.0)
    no_kb, s2 = run(log, shf_p(contacts={**ss, "kb_ft": None}))
    assert no_kb["SW_SHF"].isna().all()
    assert s2["shf"]["counts"]["samples_no_contact"] == len(no_kb)
    assert any("KB" in i["text"] for i in s2["issues"] if i["code"] == "SHF_NO_CONTACT")


def test_subsea_tvd_mnemonic_is_flagged(log):
    dev = log.copy()
    dev["TVDSS"] = 0.8 * dev["DEPTH"] - 100.0
    _, summary = run(dev, shf_p(), mapping={**FULL_MAPPING, "TVD": "TVDSS"})
    assert "SHF_TVDSS_SUSPECT" in issue_codes(summary)
    assert "SHF_TVDSS_SUSPECT" not in issue_codes(run(log, shf_p())[1])


# ---- brine density per zone -------------------------------------------------------------------
def test_zone_brine_density_shifts_sw_by_the_delta_rho_ratio(log):
    steep = {"All": fit_dict(c=0.05, d=-1.0)}          # Sw = c / J: inversely proportional to drho
    plain = run(log, shf_p(steep, contacts=zone_contacts_oil()), tops=make_tops())[0]
    rows = zone_contacts_oil()
    rows["zones"]["UPPER"]["water_density"] = 1.10
    salty, summary = run(log, shf_p(steep, contacts=rows), tops=make_tops())
    up = (salty["ZONE"] == "UPPER") & (plain["SW_SHF"] < 0.999) & (salty["SW_SHF"] < 0.999)
    assert up.sum() > 3
    ratio = (salty.loc[up, "SW_SHF"] / plain.loc[up, "SW_SHF"])
    np.testing.assert_allclose(ratio, (1.03 - 0.75) / (1.10 - 0.75), rtol=1e-9)
    lower = salty["ZONE"] == "LOWER"
    pd.testing.assert_series_equal(salty.loc[lower, "SW_SHF"], plain.loc[lower, "SW_SHF"])
    f = summary["shf"]["fluids"]
    assert f["UPPER"]["water_density"] == 1.10 and f["LOWER"]["water_density"] == 1.03


def zone_contacts_oil():
    return {"datum": "TVD", "kb_ft": None, "default": {"fwl": 1090.0, "fluid": "oil"},
            "zones": {"UPPER": {"fwl": 1090.0, "fluid": "oil"}}}


@pytest.mark.parametrize("density", [0.9, 1.3])
def test_brine_density_outside_range_refuses_the_row(log, density):
    rows = zone_contacts_oil()
    rows["zones"]["UPPER"]["water_density"] = density
    results, summary = run(log, shf_p(contacts=rows), tops=make_tops())
    up = results["ZONE"] == "UPPER"
    assert results.loc[up, "SW_SHF"].isna().all() and results.loc[~up, "SW_SHF"].notna().any()
    assert any("water density" in i["text"] for i in summary["issues"])


# ---- use for pay ------------------------------------------------------------------------------
def test_use_for_pay_changes_flags_and_pay_totals(log, base):
    results, summary = run(log, shf_p(use_for_pay=True))
    sw_pay = np.where(results["SW_SHF"].notna(), results["SW_SHF"], results["SW"])
    np.testing.assert_allclose(results["SW_PAY"], sw_pay)
    assert (results["SW"] == base[0]["SW"]).all()
    assert not results["NET_PAY_FLAG"].equals(base[0]["NET_PAY_FLAG"])
    s, b = summary, base[1]
    for key in ("net_pay", "avg_sw_pay", "hcpv_net_pay"):
        assert s[key] != b[key], key
    assert s["ng_pay"] != b["ng_pay"]
    fallback = int(results["SW_SHF"].isna().sum())
    assert fallback > 0
    assert s["shf"]["counts"]["pay_fallback_samples"] == fallback
    assert s["shf"]["pay_active"] is True
    assert "SHF_PAY_FALLBACK" in issue_codes(s)
    # pay stats follow SW_PAY, not SW
    pay = results["NET_PAY_FLAG"] == 1
    assert (sw_pay[pay.to_numpy()] < PARAM_DEFAULTS["sw_cutoff"]).all()


def test_use_for_pay_off_leaves_pay_totals_alone(log, base):
    results, summary = run(log, shf_p(use_for_pay=False))
    assert "SW_PAY" not in results.columns
    for key in ("net_pay", "avg_sw_pay", "hcpv_net_pay", "ng_pay"):
        assert summary[key] == base[1][key]


def test_log_derived_fit_refuses_pay_and_keeps_resistivity_sw(log, base):
    fits = {"All": fit_dict(basis=BASIS_LOG)}
    results, summary = run(log, shf_p(fits, use_for_pay=True))
    assert "SW_PAY" not in results.columns and "SW_SHF" in results.columns
    for key in ("net_pay", "avg_sw_pay", "hcpv_net_pay"):
        assert summary[key] == base[1][key]
    assert summary["shf"]["pay_refused"] is True and summary["shf"]["pay_active"] is False
    assert summary["shf"]["basis"] == BASIS_LOG
    assert "SHF_PAY_REFUSED" in issue_codes(summary)
    # a log-derived fit that is not in use (rock typing off: only "All" applies) does not block pay
    mixed = {"All": fit_dict(), "1": fit_dict(basis=BASIS_LOG, key="1")}
    assert "SW_PAY" in run(log, shf_p(mixed, use_for_pay=True))[0].columns
    data, mapping, params, tops = build_case("rock_typing_enabled")
    typed = run_pipeline(data, mapping, {**params, "shf": shf_p(mixed, use_for_pay=True)},
                         formation_tops=tops)
    assert "SW_PAY" not in typed[0].columns and typed[1]["shf"]["basis"] == "mixed"


# ---- the stage on its own ---------------------------------------------------------------------
def test_apply_shf_is_pure_and_matches_the_pipeline_columns(log):
    results, _ = run(log, shf_p())
    frame = results[["PHIE", "PERM_TIMUR", "SW"]].copy()
    before = frame.copy()
    out = apply_shf(shf_p(), frame, results["DEPTH"], pd.Series("(unzoned)", index=frame.index),
                    frame["SW"], "PERM_TIMUR", False)
    pd.testing.assert_frame_equal(frame, before)
    pd.testing.assert_series_equal(out.sw_shf, results["SW_SHF"], check_names=False)
    pd.testing.assert_series_equal(out.hafwl, results["HAFWL"], check_names=False)
    assert out.sw_pay is None and out.perm_column == "PERM_TIMUR"


def test_session_fit_dicts_round_trip_into_the_stage(log):
    dicts = {"All": ShfFit.from_dict(fit_dict()).to_dict()}
    a = run(log, shf_p(dicts))[0]["SW_SHF"]
    b = run(log, shf_p({"All": fit_dict()}))[0]["SW_SHF"]
    pd.testing.assert_series_equal(a, b)


def test_golden_cases_exist_with_documented_behaviour():
    for name, active in (("shf_core_pc", True), ("shf_log_derived", False)):
        data, mapping, params, tops = build_case(name)
        results, summary = run_pipeline(data, mapping, params, formation_tops=tops)
        assert ("SW_PAY" in results.columns) is active
        assert summary["shf"]["pay_active"] is active
    assert ROCK_TYPE_DEFS


def test_unclassified_samples_are_counted_by_reason():
    n = 6
    frame = pd.DataFrame({
        "PHIE": [0.2] * n, "PERM_TIMUR": [50.0] * n, "SW": [0.5] * n,
        "ROCK_TYPE": [1, 1, 0, 0, 0, 2],
        "ROCK_TYPE_SOURCE": ["log", "core", "x_vsh", "x_vsh", "x_perm", "log"]})
    out = apply_shf(shf_p({"1": fit_dict(key="1")}), frame, pd.Series(np.full(n, 1000.0)),
                    pd.Series("(unzoned)", index=frame.index), frame["SW"], "PERM_TIMUR", False)
    c = out.counts
    assert c["samples_unclassified"] == 3
    assert c["unclassified_reasons"] == {"x_vsh": 2, "x_perm": 1}
    assert c["samples_no_model"] == {"2": 1} and c["samples_modelled"] == 2
    assert out.sw_shf.iloc[[2, 3, 4, 5]].isna().all() and out.sw_shf.iloc[[0, 1]].notna().all()
