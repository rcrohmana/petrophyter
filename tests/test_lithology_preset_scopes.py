"""Lithology preset keeps a/m/n linked across scopes (multi-well follow-ups, section 6 / D10)."""
import copy

import pytest

from models.app_model import AppModel
from models.project import WellDataset
from modules import param_scopes as ps
from modules.pipeline import PARAM_DEFAULTS
from tests.golden.cases import FULL_MAPPING, fixture_frame, make_tops
from ui.parameters_window import ParametersWindow

G = dict(PARAM_DEFAULTS)
CARB = {"a": 1.0, "m": 2.0, "n": 2.0}
SAND = {"a": 0.62, "m": 2.15, "n": 2.0}


def _preset(name):
    return ps.make_entry(ps.MANUAL, name)


def _amn(flat):
    return {k: flat[k] for k in "amn"}


def test_table_matches_previous_widget_numbers():
    assert ps.LITHOLOGY_PRESETS["Sandstone (Humble)"] == SAND
    assert ps.LITHOLOGY_PRESETS["Carbonate"] == CARB


def test_well_preset_supplies_amn_with_source_label():
    flat, info = ps.resolve(G, {"lithology_preset": _preset("Carbonate")})
    assert _amn(flat) == CARB
    assert info["m"]["source"] == "well (lithology preset)" and info["m"]["scope"] == ps.WELL


def test_changing_well_preset_updates_amn():
    well = {"lithology_preset": _preset("Carbonate")}
    assert _amn(ps.resolve(G, well)[0]) == CARB
    well["lithology_preset"] = _preset("Sandstone (Humble)")
    assert _amn(ps.resolve(G, well)[0]) == SAND


def test_custom_supplies_nothing_and_keeps_explicit_values():
    well = {"lithology_preset": _preset("Custom"),
            "a": ps.make_entry(ps.MANUAL, 0.9), "m": ps.make_entry(ps.MANUAL, 1.8),
            "n": ps.make_entry(ps.MANUAL, 2.2)}
    flat, _ = ps.resolve(G, well)
    assert _amn(flat) == {"a": 0.9, "m": 1.8, "n": 2.2}
    flat, _ = ps.resolve(G, {"lithology_preset": _preset("Custom")})
    assert _amn(flat) == _amn(G)


def test_project_scope_preset_is_unchanged():
    # A project-level preset is just the flat a/m/n: resolve does not rewrite them.
    g = {**G, "lithology_preset": "Carbonate", "a": 0.7}
    flat, info = ps.resolve(g)
    assert flat["a"] == 0.7 and info["a"]["scope"] == ps.PROJECT


def test_explicit_entry_at_same_or_more_specific_scope_beats_preset():
    well = {"lithology_preset": _preset("Carbonate"), "a": ps.make_entry(ps.MANUAL, 0.5)}
    flat, info = ps.resolve(G, well)
    assert flat["a"] == 0.5 and flat["m"] == 2.0 and info["a"]["source"] == "well"
    # explicit a at a zone beats the well preset in that zone only
    wz = {"UPPER": {"a": ps.make_entry(ps.MANUAL, 0.4)}}
    well = {"lithology_preset": _preset("Carbonate")}
    flat, info = ps.resolve(G, well, None, wz, "Upper")
    assert flat["a"] == 0.4 and info["a"]["scope"] == ps.WELL_ZONE and flat["m"] == 2.0
    assert ps.resolve(G, well, None, wz, "Lower")[0]["a"] == 1.0


def test_explicit_at_less_specific_scope_loses_to_preset():
    well = {"a": ps.make_entry(ps.MANUAL, 0.5)}
    pz = {"UPPER": {"lithology_preset": _preset("Carbonate")}}
    flat, info = ps.resolve(G, well, pz, None, "UPPER")
    assert flat["a"] == 1.0 and info["a"]["source"] == "project·zone (lithology preset)"
    assert ps.resolve(G, well, pz, None, "LOWER")[0]["a"] == 0.5


def test_project_zone_preset_flows_to_every_wells_zone_plan():
    pz = {"UPPER": {"lithology_preset": _preset("Carbonate")}}
    for well in ({}, {"a": ps.make_entry(ps.MANUAL, 0.5)}, {"m": ps.make_entry(ps.MANUAL, 1.7)}):
        plan = ps.zone_plan(G, well, pz, None, ["UPPER", "LOWER"])
        assert set(plan) == {"UPPER"}
        assert _amn(plan["UPPER"]["params"]) == CARB
        assert {"a", "m", "n"} <= set(plan["UPPER"]["zone_keys"])
    # well-level params are untouched by a zone preset
    assert _amn(ps.resolve(G, {}, pz)[0]) == _amn(G)


def test_zone_plan_per_zone_values_with_mixed_presets():
    pz = {"UPPER": {"lithology_preset": _preset("Carbonate")}}
    wz = {"LOWER": {"lithology_preset": _preset("Sandstone (Humble)")}}
    plan = ps.zone_plan(G, {"lithology_preset": _preset("Carbonate")}, pz, wz, ["UPPER", "LOWER"])
    assert _amn(plan["UPPER"]["params"]) == CARB
    assert _amn(plan["LOWER"]["params"]) == SAND


def test_well_preset_alone_gives_no_zone_plan():
    assert ps.zone_plan(G, {"lithology_preset": _preset("Carbonate")}, None, None, ["UPPER"]) == {}


# ---- migration ----------------------------------------------------------
def _triple(values):
    return {k: ps.make_entry(ps.MANUAL, v) for k, v in zip("amn", values)}


def test_collapse_removes_only_equal_triples():
    equal = {"lithology_preset": _preset("Carbonate"), **_triple((1.0, 2.0, 2.0 + 1e-12))}
    differs = {"lithology_preset": _preset("Carbonate"), **_triple((1.0, 2.1, 2.0))}
    custom = {"lithology_preset": _preset("Custom"), **_triple((1.0, 2.0, 2.0))}
    partial = {"lithology_preset": _preset("Carbonate"), "a": ps.make_entry(ps.MANUAL, 1.0)}
    assert ps.collapse_preset_entries(equal) is True
    assert set(equal) == {"lithology_preset"}
    for store in (differs, custom, partial):
        before = copy.deepcopy(store)
        assert ps.collapse_preset_entries(store) is False and store == before


def test_collapse_stores_handles_zone_maps():
    zones = {"UPPER": {"lithology_preset": _preset("Carbonate"), **_triple((1.0, 2.0, 2.0))},
             "LOWER": {"lithology_preset": _preset("Carbonate"), **_triple((0.9, 2.0, 2.0))}}
    assert ps.collapse_preset_stores({}, zones) is True
    assert set(zones["UPPER"]) == {"lithology_preset"} and "a" in zones["LOWER"]


def test_session_load_collapses_with_one_note(tmp_path):
    from services.session_service import SessionService
    import tests.test_session_v2 as t2

    model = AppModel()
    t2._load(model, tmp_path, [[("a.las", dict(well="ALPHA-1"))],
                               [("b.las", dict(well="BETA-2"))]])
    keys = model.project.keys()
    for key in keys:
        ds = model.project.get(key)
        ds.overrides.update({"lithology_preset": _preset("Carbonate"), **_triple((1.0, 2.0, 2.0))})
    model.project.get(keys[0]).zone_overrides["UPPER"] = {
        "lithology_preset": _preset("Carbonate"), **_triple((1.0, 2.0, 2.0))}
    model.project.zone_params["LOWER"] = {
        "lithology_preset": _preset("Sandstone (Humble)"), **_triple((0.62, 2.15, 2.0))}
    path = str(tmp_path / "s.json")
    svc = SessionService()
    assert svc.save_session(model, path)
    fresh = AppModel()
    data = svc.load_session(path)
    assert svc.apply_session_to_model(fresh, data)
    notes = svc.restore_wells(fresh, data)
    assert len([n for n in notes if "Lithology presets" in n]) == 1
    for key in keys:
        assert not {"a", "m", "n"} & set(fresh.project.get(key).overrides)
        assert fresh.project.get(key).overrides["lithology_preset"]["value"] == "Carbonate"
    assert set(fresh.project.get(keys[0]).zone_overrides["UPPER"]) == {"lithology_preset"}
    assert set(fresh.project.zone_params["LOWER"]) == {"lithology_preset"}


def test_hash_stable_without_preset_entries():
    model = AppModel()
    ds = WellDataset(key="WELL:A", display_name="A")
    ds.las_data = fixture_frame("sample_log_data")
    ds.curve_mapping = dict(FULL_MAPPING)
    model.add_well(ds)
    plain = model.well_params_hash(ds)
    assert model.well_params_hash(ds) == plain       # no preset entry: stable
    model.set_entry("lithology_preset", "manual", "Carbonate", scope="well", well="WELL:A")
    linked = model.well_params_hash(ds)
    assert linked != plain
    model.clear_entry("lithology_preset", scope="well", well="WELL:A")
    assert model.well_params_hash(ds) == plain       # removing it restores the old hash


# ---- Parameters window --------------------------------------------------
@pytest.fixture
def model():
    model = AppModel()
    ds = WellDataset(key="WELL:A", display_name="A")
    ds.las_data = fixture_frame("sample_log_data")
    ds.curve_mapping = dict(FULL_MAPPING)
    ds.formation_tops = make_tops()
    model.add_well(ds)
    model.set_active_well("WELL:A")
    return model


@pytest.fixture
def win(qtbot, model):
    window = ParametersWindow(model)
    qtbot.addWidget(window)
    return window


def test_ui_choose_preset_at_well_scope_writes_only_preset_and_shows_muted(win, model):
    model.set_edit_scope("well")
    arch = win.archie_params_widget
    arch.lithology_combo.setCurrentText("Carbonate")
    entries = model.project.get("WELL:A").overrides
    assert entries["lithology_preset"]["value"] == "Carbonate"
    assert not {"a", "m", "n"} & set(entries)
    assert (arch.a_spin.value(), arch.m_spin.value(), arch.n_spin.value()) == (1.0, 2.0, 2.0)
    assert "lithology preset" in arch.a_spin.toolTip()
    assert arch.a_spin.property("status") == "muted"


def test_ui_typing_a_sets_preset_custom_and_writes_explicit_amn(win, model):
    model.set_edit_scope("well")
    arch = win.archie_params_widget
    arch.lithology_combo.setCurrentText("Carbonate")
    arch.a_spin.setValue(0.8)
    entries = model.project.get("WELL:A").overrides
    assert entries["lithology_preset"]["value"] == "Custom"
    assert (entries["a"]["value"], entries["m"]["value"], entries["n"]["value"]) == (0.8, 2.0, 2.0)


def test_ui_inherit_on_preset_removes_it(win, model):
    model.set_edit_scope("well")
    win.archie_params_widget.lithology_combo.setCurrentText("Carbonate")
    win._on_mode_chosen("lithology_preset", ps.INHERIT)
    assert "lithology_preset" not in model.project.get("WELL:A").overrides
    assert model.effective_params("WELL:A")[0]["m"] == model.m


def test_ui_flat_project_scope_unchanged(win, model):
    arch = win.archie_params_widget
    arch.lithology_combo.setCurrentText("Carbonate")
    assert (model.a, model.m, model.n) == (1.0, 2.0, 2.0)
    assert model.project.get("WELL:A").overrides.get("lithology_preset") is None
