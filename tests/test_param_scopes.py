"""Parameter scopes and zoned execution (spec §4.10)."""

import io

import numpy as np
import pandas as pd
import pytest

from models.app_model import AppModel
from models.project import WellDataset
from modules import param_scopes as ps
from modules.formation_tops import FormationTops
from modules.pipeline import PARAM_DEFAULTS, assign_zones, run_pipeline
from tests.golden.cases import FULL_MAPPING, fixture_frame, make_tops

MANUAL_RW_RSH_GR = {
    "rw_mode": "manual", "rw": 0.06, "rsh_mode": "manual", "rsh": 4.0,
    "vsh_baseline_method": ps.GR_MANUAL, "gr_min_manual": 30.0, "gr_max_manual": 120.0,
}


def _data():
    return fixture_frame("sample_log_data")


def _tops(text="Formation\tTop (ft)\tBottom (ft)\nUpper\t1000\t1040\nLower\t1040\t1100\n"):
    tops = FormationTops()
    assert tops.read_tops_from_buffer(io.StringIO(text))
    return tops


def _plan(zone_params=None, overrides=None, zone_overrides=None, global_params=None, zones=("UPPER", "LOWER")):
    g = {**PARAM_DEFAULTS, **(global_params or {})}
    return ps.zone_plan(g, overrides, zone_params, zone_overrides, zones)


# ---- resolution -----------------------------------------------------------
def test_resolution_order_well_zone_beats_project_zone_beats_well_beats_project():
    g = {**PARAM_DEFAULTS, "m": 2.0}
    well = {"m": ps.make_entry(ps.MANUAL, 2.1)}
    pz = {"TALANG AKAR": {"m": ps.make_entry(ps.MANUAL, 1.85)}}
    wz = {"TALANG AKAR": {"m": ps.make_entry(ps.MANUAL, 1.9)}}

    assert ps.resolve(g)[0]["m"] == 2.0
    assert ps.resolve(g, well)[0]["m"] == 2.1
    flat, info = ps.resolve(g, well, pz, None, "Talang  akar")
    assert flat["m"] == 1.85 and info["m"]["scope"] == ps.PROJECT_ZONE
    flat, info = ps.resolve(g, well, pz, wz, "TALANG AKAR")
    assert flat["m"] == 1.9 and info["m"]["source"] == ps.WELL_ZONE
    # Another zone falls back to the well value.
    assert ps.resolve(g, well, pz, wz, "BATURAJA")[0]["m"] == 2.1


def test_inherit_entries_fall_through_and_well_only_params_ignore_zones():
    g = dict(PARAM_DEFAULTS)
    well = {"m": ps.make_entry(ps.INHERIT, 9.9), "rho_fluid": ps.make_entry(ps.MANUAL, 1.1)}
    wz = {"A": {"rho_fluid": ps.make_entry(ps.MANUAL, 0.8)}}
    flat, info = ps.resolve(g, well, None, wz, "A")
    assert flat["m"] == g["m"] and info["m"]["scope"] == ps.PROJECT
    assert flat["rho_fluid"] == 1.1 and info["rho_fluid"]["scope"] == ps.WELL


def test_project_only_parameters_ignore_every_entry():
    g = dict(PARAM_DEFAULTS)
    assert ps.is_project_only("sw_primary_method")
    flat, _ = ps.resolve(g, {"sw_primary_method": ps.make_entry(ps.MANUAL, "Archie")})
    assert flat["sw_primary_method"] == g["sw_primary_method"]


def test_auto_entries_map_to_flat_modes():
    g = {**PARAM_DEFAULTS, **MANUAL_RW_RSH_GR}
    flat, info = ps.resolve(g, ps.default_well_overrides())
    assert flat["rw_mode"] == "auto" and flat["rsh_mode"] == "auto"
    assert flat["vsh_baseline_method"] == ps.GR_AUTO
    assert flat["rw"] == 0.06  # the project value stays as the fallback
    assert info["rw"]["source"] == "auto"
    flat, _ = ps.resolve(g, {"gr_baseline": ps.make_entry(ps.MANUAL, [25, 140])})
    assert (flat["gr_min_manual"], flat["gr_max_manual"]) == (25.0, 140.0)


def test_formation_names_are_normalised():
    assert ps.normalize_zone(" Talang  Akar ") == ps.normalize_zone("TALANG AKAR") == "TALANG AKAR"


def test_zone_plan_is_empty_without_zone_entries():
    assert _plan() == {}
    assert _plan(overrides={"m": ps.make_entry(ps.MANUAL, 2.0)}) == {}


def test_validation_warnings():
    assert ps.validate_entry("m", 3.5)
    assert ps.validate_entry("m", 2.0) is None
    assert ps.validate_entry("rw", 0.001)
    assert ps.validate_entry("gr_baseline", [50, 60])
    assert ps.validate_entry("gr_baseline", [20, 120]) is None


# ---- zoned execution ------------------------------------------------------
def test_zoned_run_without_zone_entries_equals_unzoned_run():
    data = _data()
    plain, plain_summary = run_pipeline(data, FULL_MAPPING, {})
    zoned, summary = run_pipeline(data, FULL_MAPPING, {"zone_plan": {}}, formation_tops=make_tops())
    pd.testing.assert_frame_equal(zoned.drop(columns=["ZONE"]), plain)
    assert summary["net_pay"] == plain_summary["net_pay"]
    assert [z["zone"] for z in summary["zones"]] == ["UPPER", "LOWER"]
    assert sum(z["net_pay"] for z in summary["zones"]) == pytest.approx(summary["net_pay"])


def test_assign_zones_half_open_unzoned_and_overlap():
    depth = pd.Series([990.0, 1000.0, 1039.5, 1040.0, 1100.0, 1101.0])
    labels, warnings = assign_zones(depth, make_tops())
    assert list(labels) == [ps.UNZONED, "UPPER", "UPPER", "LOWER", "LOWER", ps.UNZONED]
    assert warnings == []
    overlap = _tops("Formation\tTop (ft)\tBottom (ft)\nA\t1000\t1050\nB\t1040\t1100\n")
    labels, warnings = assign_zones(pd.Series([1045.0]), overlap)
    assert list(labels) == ["A"] and warnings


def test_two_zones_with_different_m_match_single_zone_runs():
    data = _data()
    tops = make_tops()
    base = {**MANUAL_RW_RSH_GR, "sw_methods": ["Archie", "Simandoux"]}
    plan = _plan(zone_params={"LOWER": {"m": ps.make_entry(ps.MANUAL, 1.8)}}, global_params=base)
    zoned, summary = run_pipeline(data, FULL_MAPPING, {**base, "zone_plan": plan}, formation_tops=tops)

    lower = data[(data["DEPTH"] >= 1040) & (data["DEPTH"] <= 1100)]
    upper = data[(data["DEPTH"] >= 1000) & (data["DEPTH"] < 1040)]
    ref_lower, _ = run_pipeline(lower, FULL_MAPPING, {**base, "m": 1.8})
    ref_upper, _ = run_pipeline(upper, FULL_MAPPING, base)
    for col in ("SW_ARCHIE", "SW_SIMAN", "VSH", "PHIE"):
        np.testing.assert_allclose(zoned.loc[lower.index, col], ref_lower[col], rtol=1e-12)
        np.testing.assert_allclose(zoned.loc[upper.index, col], ref_upper[col], rtol=1e-12)
    sources = summary["param_sources"]
    assert sources["LOWER"]["m"] == {"value": 1.8, "source": ps.PROJECT_ZONE}
    assert sources["UPPER"]["m"]["source"] == ps.PROJECT
    assert [r["params"]["m"]["value"] for r in summary["zones"]] == [PARAM_DEFAULTS["m"], 1.8]


def test_per_zone_cutoffs_sum_to_well_net_pay():
    data = _data()
    plan = _plan(zone_overrides={"UPPER": {"sw_cutoff": ps.make_entry(ps.MANUAL, 0.3)},
                                 "LOWER": {"phi_cutoff": ps.make_entry(ps.MANUAL, 0.15)}})
    _, summary = run_pipeline(data, FULL_MAPPING, {"zone_plan": plan}, formation_tops=make_tops())
    zones = summary["zones"]
    for key in ("net_pay", "net_reservoir", "gross_sand"):
        assert summary[key] == pytest.approx(sum(z[key] for z in zones))
    assert zones[0]["params"]["sw_cutoff"]["value"] == 0.3
    assert zones[1]["params"]["phi_cutoff"]["value"] == 0.15
    _, plain = run_pipeline(data, FULL_MAPPING, {}, formation_tops=make_tops())
    assert summary["net_pay"] <= plain["net_pay"]


def test_thin_zone_auto_rw_falls_back_to_the_well_value():
    data = _data()
    tops = _tops("Formation\tTop (ft)\tBottom (ft)\nThin\t1000\t1005\nMain\t1005\t1100\n")
    base = {**MANUAL_RW_RSH_GR, "rw_mode": "auto"}
    plan = _plan(zone_overrides={"THIN": {"rw": ps.make_entry(ps.AUTO)}},
                 global_params=base, zones=("THIN", "MAIN"))
    _, summary = run_pipeline(data, FULL_MAPPING, {**base, "zone_plan": plan}, formation_tops=tops)
    thin = summary["param_sources"]["THIN"]["rw"]
    assert thin["source"] == "auto (fallback: well)"
    assert thin["value"] == pytest.approx(summary["rw"])


def test_thin_zone_falls_back_to_a_manual_project_zone_value():
    data = _data()
    tops = _tops("Formation\tTop (ft)\tBottom (ft)\nThin\t1000\t1005\nMain\t1005\t1100\n")
    plan = _plan(zone_params={"THIN": {"rw": ps.make_entry(ps.MANUAL, 0.09)}},
                 zone_overrides={"THIN": {"rw": ps.make_entry(ps.AUTO)}}, zones=("THIN", "MAIN"))
    _, summary = run_pipeline(data, FULL_MAPPING, {"zone_plan": plan}, formation_tops=tops)
    assert summary["param_sources"]["THIN"]["rw"] == {
        "value": 0.09, "source": "auto (fallback: project·zone)"}


def test_zone_auto_rw_uses_only_that_zones_samples():
    data = _data()
    base = {**MANUAL_RW_RSH_GR}
    plan = _plan(zone_overrides={"LOWER": {"rw": ps.make_entry(ps.AUTO)}}, global_params=base)
    _, summary = run_pipeline(data, FULL_MAPPING, {**base, "zone_plan": plan}, formation_tops=make_tops())
    src = summary["param_sources"]["LOWER"]["rw"]
    assert src["source"] == "auto (well·zone)"
    lower = data[data["DEPTH"] >= 1040]
    _, ref = run_pipeline(lower, FULL_MAPPING, {**base, "rw_mode": "auto"})
    assert src["value"] == pytest.approx(ref["rw"])
    assert src["value"] != pytest.approx(base["rw"])


def test_manual_rsh_is_used():
    data = _data()
    flat, _ = ps.resolve({**PARAM_DEFAULTS}, {"rsh": ps.make_entry(ps.MANUAL, 7.5)})
    _, summary = run_pipeline(data, FULL_MAPPING, flat)
    assert summary["rsh"] == 7.5 and summary["rsh_source"] == "manual"


# ---- temperature (P3) -----------------------------------------------------
def test_gradient_from_header_and_units():
    assert ps.gradient_from_header({"bht": 230.0, "td": 10000.0}, 80.0) == pytest.approx(1.5)
    g = ps.gradient_from_header({"bht": 110.0, "bht_unit": "DEGC", "td": 3048.0, "td_unit": "M"}, 80.0)
    assert g == pytest.approx((230.0 - 80.0) / 10000.0 * 100, rel=1e-3)
    assert ps.gradient_from_header({"bht": 70.0, "td": 1000.0}, 80.0) is None
    assert ps.gradient_from_header({}, 80.0) is None


def test_arps_factor():
    assert ps.arps_factor(75.0, 75.0) == pytest.approx(1.0)
    # Hotter water is more conductive.
    assert ps.arps_factor(200.0, 75.0) < 1.0


def test_temperature_correction_lowers_sw_at_depth():
    data = _data()
    base = {**MANUAL_RW_RSH_GR, "sw_methods": ["Archie"], "sw_primary_method": "Archie"}
    plain, _ = run_pipeline(data, FULL_MAPPING, base)
    neutral, _ = run_pipeline(data, FULL_MAPPING, {
        **base, "temp_correction": True, "surface_temp": 75.0, "temp_gradient": 0.0, "rw_ref_temp": 75.0})
    np.testing.assert_allclose(neutral["SW_ARCHIE"], plain["SW_ARCHIE"], rtol=1e-12)
    hot, summary = run_pipeline(data, FULL_MAPPING, {
        **base, "temp_correction": True, "surface_temp": 80.0, "temp_gradient": 1.5, "rw_ref_temp": 75.0})
    valid = plain["SW_ARCHIE"].between(0.01, 0.99) & hot["SW_ARCHIE"].between(0.01, 0.99)
    assert (hot.loc[valid, "SW_ARCHIE"] < plain.loc[valid, "SW_ARCHIE"]).all()
    lo, hi = summary["rw_at_depth_range"]
    assert hi < 0.06 and lo < hi


# ---- model API ------------------------------------------------------------
def _model_with_wells():
    model = AppModel()
    for name in ("A", "B"):
        ds = WellDataset(key=f"WELL:{name}", display_name=name)
        ds.las_data = _data()
        ds.curve_mapping = dict(FULL_MAPPING)
        ds.formation_tops = make_tops()
        model.add_well(ds)
    return model


def test_calibrating_rw_on_one_well_leaves_the_other_unchanged():
    model = _model_with_wells()
    model.set_active_well("WELL:A")
    model.set_entry("rw", ps.MANUAL, 0.031, scope="well", source="calibrated", method="Rwa")
    assert model.effective_params("WELL:A")[0]["rw"] == 0.031
    assert model.effective_params("WELL:A")[1]["rw"]["source"] == "calibrated"
    assert model.effective_params("WELL:B")[0]["rw"] == model.rw
    assert model.params_for_well(model.project.get("WELL:B"))["rw"] == model.rw


def test_scope_view_marks_values_set_here_and_hash_changes_per_well():
    model = _model_with_wells()
    hash_a = model.well_params_hash(model.project.get("WELL:A"))
    hash_b = model.well_params_hash(model.project.get("WELL:B"))
    model.set_entry("m", ps.MANUAL, 1.9, scope="well", zone="Lower", well="WELL:A")
    _, info = model.scope_view("well", "LOWER", "WELL:A")
    assert info["m"]["here"] and not info["n"]["here"]
    assert model.well_params_hash(model.project.get("WELL:A")) != hash_a
    assert model.well_params_hash(model.project.get("WELL:B")) == hash_b
    plan = model.params_for_well(model.project.get("WELL:A"))["zone_plan"]
    assert list(plan) == ["LOWER"]
    model.clear_entry("m", scope="well", zone="LOWER", well="WELL:A")
    assert model.project.get("WELL:A").zone_overrides == {}


def test_project_zone_entries_apply_to_every_well_and_scope_rules():
    model = _model_with_wells()
    model.set_entry("a", ps.MANUAL, 1.0, scope="project", zone="upper")
    for key in ("WELL:A", "WELL:B"):
        assert model.effective_params(key, "UPPER")[0]["a"] == 1.0
    with pytest.raises(ValueError):
        model.set_entry("rho_fluid", ps.MANUAL, 1.1, scope="project", zone="UPPER")
    with pytest.raises(ValueError):
        model.set_entry("m", ps.AUTO, scope="well")
    with pytest.raises(ValueError):
        model.set_entry("sw_methods", ps.MANUAL, ["Archie"], scope="well")
    model.promote_to_project("rw", 0.07)
    assert model.rw == 0.07 and model.rw_mode == "manual"


def test_copy_entry_to_other_wells():
    model = _model_with_wells()
    entry = ps.make_entry(ps.MANUAL, 0.04, "calibrated")
    model.copy_entry("rw", entry, [("well", None, "WELL:B")])
    assert model.project.get("WELL:B").overrides["rw"]["source"] == "calibrated"


def test_legacy_session_keeps_manual_values_for_the_single_well():
    g = {**PARAM_DEFAULTS, "rw_mode": "manual", "rw": 0.08,
         "vsh_baseline_method": ps.GR_MANUAL, "gr_min_manual": 15.0, "gr_max_manual": 110.0}
    overrides = {**ps.default_well_overrides(), **ps.legacy_well_overrides(g)}
    flat, _ = ps.resolve(g, overrides)
    for key in ("rw", "rw_mode", "rsh_mode", "vsh_baseline_method", "gr_min_manual", "gr_max_manual"):
        assert flat[key] == g[key], key


def test_session_load_applies_legacy_overrides_to_the_active_well(tmp_path):
    from services.session_service import SessionService

    model = _model_with_wells()
    model.project.get("WELL:B").overrides = ps.default_well_overrides()
    svc = SessionService()
    model.rw, model.rw_mode = 0.08, "manual"
    path = tmp_path / "s.json"
    assert svc.save_session(model, str(path))
    model.rw = 0.05
    assert svc.apply_session_to_model(model, svc.load_session(str(path)))
    assert model.to_params()["rw"] == 0.08
    assert model.to_params()["rw_mode"] == "manual"


def test_edit_scope_returns_to_project_when_no_well_is_left():
    model = _model_with_wells()
    model.set_edit_scope("well", "upper")
    assert (model.edit_scope, model.edit_zone) == ("well", "UPPER")
    model.reset()
    assert model.edit_scope == "project"
