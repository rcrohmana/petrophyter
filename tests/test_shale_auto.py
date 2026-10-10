"""Shale point AUTO for parameter scopes: pure estimator, well and zone level."""

import io
from types import SimpleNamespace

import pandas as pd
import pytest

from models.app_model import AppModel
from models.project import WellDataset
from modules import param_scopes as ps
from modules.formation_tops import FormationTops
from modules.pipeline import PARAM_DEFAULTS, estimate_rw_rsh, run_pipeline
from modules.shale_estimation import SHALE_PARAMS, estimate_shale_point
from services.analysis_service import AnalysisService
from tests.golden.cases import FULL_MAPPING, fixture_frame, make_tops

MANUAL = {
    "rw_mode": "manual", "rw": 0.06, "rsh_mode": "manual", "rsh": 4.0,
    "vsh_baseline_method": ps.GR_MANUAL, "gr_min_manual": 30.0, "gr_max_manual": 120.0,
}
SETTINGS = {"shale_min_points": 5, "shale_vsh_threshold": 0.4}


def _data():
    return fixture_frame("sample_log_data")


def _tops(text):
    tops = FormationTops()
    assert tops.read_tops_from_buffer(io.StringIO(text))
    return tops


def _plan(zone_overrides, global_params):
    return ps.zone_plan({**PARAM_DEFAULTS, **global_params}, None, None, zone_overrides,
                        ("UPPER", "LOWER"))


AUTO_ALL = {name: ps.make_entry(ps.AUTO) for name in SHALE_PARAMS}

# Frozen output of the pre-refactor AnalysisService.calculate_shale_parameters
# on the golden fixture (rho, nphi, dt).
OLD_SERVICE = [
    ({"shale_min_points": 10}, (2.408485138995547, 0.2506429346774069, 86.96776218904279)),
    ({"shale_min_points": 10, "shale_vsh_threshold": 0.7, "shale_gate_logs": False},
     (2.40786844838313, 0.2511342398860938, 87.11945357302523)),
    ({"shale_selection_mode": "quantile", "shale_min_points": 5, "shale_vsh_quantile": 0.8},
     (2.408485138995547, 0.2526993516784257, 86.01010202865068)),
    ({"shale_selection_mode": "stability_sweep", "shale_min_points": 5},
     (2.40786844838313, 0.2511342398860938, 87.11945357302523)),
    ({}, (2.45, 0.35, 100.0)),  # too few shale points: fallback
    ({"vsh_baseline_method": "Custom (Manual)", "shale_min_points": 10,
      "shale_vsh_threshold": 0.5}, (2.418178588637648, 0.25222432600548045, 90.62709263136296)),
]


# ---- estimator -------------------------------------------------------------
@pytest.mark.parametrize("settings, expected", OLD_SERVICE)
def test_estimator_matches_the_old_service_output(settings, expected):
    result = estimate_shale_point(_data(), FULL_MAPPING,
                                  {"vsh_methods": ["Linear", "Larionov Tertiary"], **settings})
    got = (result["rho_shale"], result["nphi_shale"], result["dt_shale"])
    assert got == pytest.approx(expected, rel=1e-12)
    assert (result["method"] == "fallback") == (settings == {})

    attrs = dict(
        las_data=_data(), curve_mapping=FULL_MAPPING, analysis_mode="Whole Well",
        selected_formations=[], formation_tops=None,
        vsh_baseline_method="Statistically (Auto)", gr_min_manual=20.0, gr_max_manual=120.0,
        vsh_methods=["Linear", "Larionov Tertiary"])
    model = SimpleNamespace(**{**attrs, **settings})
    wrapped = AnalysisService().calculate_shale_parameters(model)
    assert wrapped == result


def test_service_wrapper_with_zone_uses_only_that_zones_samples():
    model = SimpleNamespace(
        las_data=_data(), curve_mapping=FULL_MAPPING, analysis_mode="Whole Well",
        selected_formations=[], formation_tops=make_tops(),
        vsh_baseline_method="Statistically (Auto)", gr_min_manual=20.0, gr_max_manual=120.0,
        vsh_methods=["Linear"], **SETTINGS)
    data = _data()
    lower = data[(data["DEPTH"] >= 1040) & (data["DEPTH"] <= 1100)]
    expected = estimate_shale_point(lower, FULL_MAPPING, {"vsh_methods": ["Linear"], **SETTINGS})
    assert AnalysisService().calculate_shale_parameters(model, zone="Lower") == expected


# ---- flat parameters --------------------------------------------------------
def test_apply_entry_records_auto_names_only_when_auto():
    g = dict(PARAM_DEFAULTS)
    flat, info = ps.resolve(g)
    assert "shale_auto" not in flat and flat == {**g, **{k: flat[k] for k in flat}}
    assert set(flat) == set(g)  # nothing leaks into project-flat params
    flat, info = ps.resolve(g, {"nphi_shale": ps.make_entry(ps.AUTO),
                                "rho_shale": ps.make_entry(ps.AUTO)})
    assert flat["shale_auto"] == ["nphi_shale", "rho_shale"]
    assert flat["nphi_shale"] == g["nphi_shale"] and info["nphi_shale"]["source"] == "auto"
    flat, _ = ps.resolve(g, {"rho_shale": ps.make_entry(ps.AUTO)},
                         None, {"A": {"rho_shale": ps.make_entry(ps.MANUAL, 2.5)}}, "A")
    assert "shale_auto" not in flat and flat["rho_shale"] == 2.5


# ---- well level -------------------------------------------------------------
def test_well_auto_uses_the_estimate_and_reports_auto():
    data = _data()
    params = {**MANUAL, **SETTINGS}
    expected = estimate_shale_point(data, FULL_MAPPING, params, 30.0, 120.0)
    assert expected["method"] == "statistical_vsh"
    flat, info = ps.resolve({**PARAM_DEFAULTS, **params}, AUTO_ALL)

    auto, summary = run_pipeline(data, FULL_MAPPING, {**flat, "param_info": info})
    manual, _ = run_pipeline(data, FULL_MAPPING, {
        **params, **{name: expected[name] for name in SHALE_PARAMS}})
    pd.testing.assert_frame_equal(auto, manual)
    default, _ = run_pipeline(data, FULL_MAPPING, params)
    assert not auto["PHIE"].equals(default["PHIE"])

    table = summary["param_sources"]["(well)"]
    for name in SHALE_PARAMS:
        assert table[name] == {"value": expected[name], "source": "auto"}


def test_well_auto_unavailable_keeps_entered_values_with_source():
    data = _data()  # default min points (50) is not reached by the fixture
    flat, info = ps.resolve({**PARAM_DEFAULTS, **MANUAL}, AUTO_ALL)
    results, summary = run_pipeline(data, FULL_MAPPING, {**flat, "param_info": info})
    table = summary["param_sources"]["(well)"]
    assert table["rho_shale"] == {"value": PARAM_DEFAULTS["rho_shale"],
                                  "source": "auto unavailable (fallback: project)"}
    assert any("Shale point" in w for w in summary["warnings"])
    plain, _ = run_pipeline(data, FULL_MAPPING, MANUAL)
    pd.testing.assert_frame_equal(results, plain)


def test_only_the_auto_shale_parameter_is_replaced():
    data = _data()
    params = {**MANUAL, **SETTINGS}
    expected = estimate_shale_point(data, FULL_MAPPING, params, 30.0, 120.0)
    flat, info = ps.resolve({**PARAM_DEFAULTS, **params},
                            {"dt_shale": ps.make_entry(ps.AUTO),
                             "rho_shale": ps.make_entry(ps.MANUAL, 2.5)})
    _, summary = run_pipeline(data, FULL_MAPPING, {**flat, "param_info": info})
    table = summary["param_sources"]["(well)"]
    assert table["dt_shale"] == {"value": expected["dt_shale"], "source": "auto"}
    assert table["rho_shale"] == {"value": 2.5, "source": "well"}
    assert table["nphi_shale"]["value"] == PARAM_DEFAULTS["nphi_shale"]


def test_rw_rsh_estimate_sees_the_auto_shale_point():
    data = _data()
    params = {**MANUAL, **SETTINGS}
    flat, _ = ps.resolve({**PARAM_DEFAULTS, **params}, AUTO_ALL)
    expected = estimate_shale_point(data, FULL_MAPPING, params, 30.0, 120.0)
    with_auto = estimate_rw_rsh(data, FULL_MAPPING, flat)
    with_values = estimate_rw_rsh(data, FULL_MAPPING, {
        **params, **{name: expected[name] for name in SHALE_PARAMS}})
    assert with_auto["rw"] == with_values["rw"] and with_auto["rsh"] == with_values["rsh"]


# ---- zone level -------------------------------------------------------------
def test_zone_auto_uses_the_zones_samples():
    data = _data()
    tops = make_tops()
    params = {**MANUAL, **SETTINGS}
    plan = _plan({"LOWER": AUTO_ALL}, params)
    assert plan["LOWER"]["zone_auto"] == list(SHALE_PARAMS)
    _, summary = run_pipeline(
        data, FULL_MAPPING, {**params, **{"shale_auto": []}, "zone_plan": plan},
        formation_tops=tops)

    lower = data[(data["DEPTH"] >= 1040) & (data["DEPTH"] <= 1100)]
    expected = estimate_shale_point(lower, FULL_MAPPING, params, 30.0, 120.0)
    assert expected["method"] == "statistical_vsh"
    lower_table = summary["param_sources"]["LOWER"]
    for name in SHALE_PARAMS:
        assert lower_table[name] == {"value": expected[name], "source": "auto (well·zone)"}
    # The upper zone keeps the project values.
    assert summary["param_sources"]["UPPER"]["rho_shale"] == {
        "value": PARAM_DEFAULTS["rho_shale"], "source": "project"}
    rows = {z["zone"]: z for z in summary["zones"]}
    assert rows["LOWER"]["params"]["rho_shale"]["value"] == expected["rho_shale"]
    assert "rho_shale" not in rows["UPPER"]["params"] or \
        rows["UPPER"]["params"]["rho_shale"]["source"] == "project"


def test_thin_zone_falls_back_to_the_well_value():
    data = _data()
    tops = _tops("Formation\tTop (ft)\tBottom (ft)\nTHIN\t1000\t1010\nBODY\t1010\t1100\n")
    params = {**MANUAL, **SETTINGS}
    plan = ps.zone_plan({**PARAM_DEFAULTS, **params}, None, None, {"THIN": AUTO_ALL}, ("THIN",))
    _, summary = run_pipeline(data, FULL_MAPPING, {**params, "zone_plan": plan},
                              formation_tops=tops)
    table = summary["param_sources"]["THIN"]
    for name in SHALE_PARAMS:
        assert table[name] == {"value": PARAM_DEFAULTS[name], "source": "auto (fallback: well)"}


def test_zone_auto_falls_back_to_the_well_auto_estimate():
    data = _data()
    tops = _tops("Formation\tTop (ft)\tBottom (ft)\nTHIN\t1000\t1010\nBODY\t1010\t1100\n")
    params = {**MANUAL, **SETTINGS}
    well = {name: ps.make_entry(ps.AUTO) for name in SHALE_PARAMS}
    plan = ps.zone_plan({**PARAM_DEFAULTS, **params}, well, None, {"THIN": AUTO_ALL}, ("THIN",))
    flat, info = ps.resolve({**PARAM_DEFAULTS, **params}, well)
    _, summary = run_pipeline(data, FULL_MAPPING,
                              {**flat, "param_info": info, "zone_plan": plan},
                              formation_tops=tops)
    well_table = summary["param_sources"]["(well)"]
    thin = summary["param_sources"]["THIN"]
    assert well_table["rho_shale"]["source"] == "auto"
    assert thin["rho_shale"] == {"value": well_table["rho_shale"]["value"],
                                 "source": "auto (fallback: well)"}


# ---- no AUTO: nothing changes ------------------------------------------------
def test_without_auto_entries_results_and_hashes_are_unchanged():
    data = _data()
    tops = make_tops()
    base, base_summary = run_pipeline(data, FULL_MAPPING, MANUAL, formation_tops=tops)
    flat, info = ps.resolve({**PARAM_DEFAULTS, **MANUAL},
                            {"rho_shale": ps.make_entry(ps.MANUAL, PARAM_DEFAULTS["rho_shale"])})
    assert "shale_auto" not in flat
    again, summary = run_pipeline(data, FULL_MAPPING, {**flat, "param_info": info},
                                  formation_tops=tops)
    pd.testing.assert_frame_equal(base, again)
    assert summary["net_pay"] == base_summary["net_pay"]
    assert [z["params"].keys() for z in summary["zones"]] == \
        [z["params"].keys() for z in base_summary["zones"]]
    assert not any(k.startswith("shale") for k in flat)


def test_model_carries_shale_settings_only_when_a_shale_parameter_is_auto():
    model = AppModel()
    ds = WellDataset(key="WELL:A", display_name="A")
    ds.las_data = _data()
    ds.curve_mapping = dict(FULL_MAPPING)
    ds.formation_tops = make_tops()
    model.add_well(ds)
    model.set_active_well("WELL:A")
    plain = model.params_for_well(ds)
    assert "shale_auto" not in plain and "shale_selection_mode" not in plain
    hash_before = model.well_params_hash(ds)
    model.shale_min_points = 5
    assert model.well_params_hash(ds) == hash_before
    model.set_entry("rho_shale", ps.AUTO, scope="well")
    flat = model.params_for_well(ds)
    assert flat["shale_auto"] == ["rho_shale"] and flat["shale_min_points"] == 5
    assert model.well_params_hash(ds) != hash_before
