"""Parameters window: scope bar, per-field modes, zone grid (multi-well spec §4.8)."""
import copy

import pytest
from PyQt6.QtCore import Qt

from models.app_model import AppModel
from models.project import WellDataset
from modules import param_scopes as ps
from tests.golden.cases import FULL_MAPPING, fixture_frame, make_tops
from ui.parameters_window import ParametersWindow
from ui.widgets.scope_bar import ALL_ZONES
from ui.widgets.zone_grid import STATE_ROLE


def _model_with_wells():
    model = AppModel()
    for name in ("A", "B"):
        ds = WellDataset(key=f"WELL:{name}", display_name=name)
        ds.las_data = fixture_frame("sample_log_data")
        ds.curve_mapping = dict(FULL_MAPPING)
        ds.formation_tops = make_tops()
        model.add_well(ds)
    model.set_active_well("WELL:A")
    return model


@pytest.fixture
def model():
    return _model_with_wells()


@pytest.fixture
def win(qtbot, model):
    window = ParametersWindow(model)
    qtbot.addWidget(window)
    return window


def _stores(model):
    return copy.deepcopy((
        {w.key: w.overrides for w in model.project},
        {w.key: w.zone_overrides for w in model.project},
        model.project.zone_params,
    ))


def _grid_cell(grid, zone, name):
    row = grid.zones().index(zone)
    return grid.table.item(row, grid.columns.index(name))


# ---- scope bar ----------------------------------------------------------
def test_scope_bar_drives_edit_scope(win, model):
    bar = win.scope_bar
    assert bar.well_btn.text() == "Well: A" and bar.well_btn.isEnabled()
    assert bar.caption.text() == "Values for every well"
    bar.well_btn.click()
    assert model.edit_scope == "well" and bar.caption.text() == "Values for A"
    index = bar.zone_combo.findData("LOWER")
    assert index > 0 and bar.zone_combo.itemText(0) == ALL_ZONES
    bar.zone_combo.setCurrentIndex(index)
    bar.zone_combo.activated.emit(index)
    assert model.edit_zone == "LOWER" and bar.caption.text() == "LOWER in A"
    bar.project_btn.click()
    assert (model.edit_scope, model.edit_zone) == ("project", "LOWER")
    assert bar.caption.text() == "LOWER in every well"
    model.set_edit_scope("well", None)         # the bar follows the model
    assert bar.well_btn.isChecked() and bar.zone_combo.currentData() is None


def test_scope_bar_well_disabled_without_wells(qtbot):
    empty = AppModel()
    bar = ParametersWindow(empty).scope_bar
    qtbot.addWidget(bar)
    assert not bar.well_btn.isEnabled() and bar.well_btn.text() == "Well"


def test_switching_scopes_never_creates_entries(win, model):
    before = _stores(model)
    values = (model.a, model.m, model.rw, model.rw_mode, model.vsh_cutoff)
    for scope, zone in (("well", None), ("well", "LOWER"), ("project", "UPPER"),
                        ("project", None), ("well", "UPPER"), ("project", None)):
        model.set_edit_scope(scope, zone)
    model.set_active_well("WELL:B")
    model.set_edit_scope("well")
    model.set_active_well("WELL:A")
    model.set_edit_scope("project")
    assert _stores(model) == before
    assert (model.a, model.m, model.rw, model.rw_mode, model.vsh_cutoff) == values


# ---- explicit edits -----------------------------------------------------
def test_project_scope_still_writes_flat_values(win, model):
    win.archie_params_widget.m_spin.setValue(1.9)
    assert model.m == 1.9
    assert model.project.get("WELL:A").overrides == {}


def test_edit_at_well_scope_creates_entry_only_for_active_well(win, model, qtbot):
    project_m = model.m
    model.set_edit_scope("well")
    with qtbot.waitSignal(win.parameters_updated):
        win.archie_params_widget.m_spin.setValue(1.9)
    entry = model.get_entry("m")
    assert entry["mode"] == "manual" and entry["value"] == 1.9
    assert "m" not in model.project.get("WELL:B").overrides
    assert model.m == project_m
    assert [k for k in model.project.get("WELL:A").overrides] == ["m"]


def test_inherit_clears_entry_and_shows_project_value(win, model):
    model.set_edit_scope("well")
    win.archie_params_widget.m_spin.setValue(1.9)
    win._controls["m"].actions_["inherit"].trigger()
    assert model.get_entry("m") is None
    assert win.archie_params_widget.m_spin.value() == pytest.approx(model.m)


def test_auto_for_rw_sets_auto_entry(win, model):
    model.set_edit_scope("well")
    win._controls["rw"].actions_["auto"].trigger()
    assert model.get_entry("rw")["mode"] == "auto"
    assert win.res_params_widget.rw_auto_cb.isChecked()
    assert "auto" not in win._controls["m"].actions_      # m has no Auto mode
    win.res_params_widget.rw_auto_cb.setChecked(False)    # explicit toggle -> Manual
    assert model.get_entry("rw")["mode"] == "manual"


def test_zone_scope_edit_lands_in_zone_overrides(win, model):
    model.set_edit_scope("well", "LOWER")
    win.archie_params_widget.n_spin.setValue(2.4)
    ds = model.project.get("WELL:A")
    assert ds.zone_overrides["LOWER"]["n"]["value"] == 2.4
    assert ds.overrides == {} and model.project.zone_params == {}


def test_project_zone_edit_lands_in_project_zone_params(win, model):
    project_a = model.a
    model.set_edit_scope("project", "UPPER")
    win.archie_params_widget.a_spin.setValue(0.9)
    assert model.project.zone_params["UPPER"]["a"]["value"] == 0.9
    assert model.a == project_a
    assert all(w.zone_overrides == {} for w in model.project)


def test_lithology_preset_writes_only_the_preset_entry(win, model):
    # Changed intentionally (spec D10): a/m/n now follow the preset at resolve time.
    model.set_edit_scope("well")
    win.archie_params_widget.lithology_combo.setCurrentText("Carbonate")
    entries = model.project.get("WELL:A").overrides
    assert entries["lithology_preset"]["value"] == "Carbonate"
    assert not {"a", "m", "n"} & set(entries)
    flat, info = model.effective_params("WELL:A")
    assert (flat["a"], flat["m"], flat["n"]) == (1.0, 2.0, 2.0)
    assert info["a"]["source"] == "well (lithology preset)"


# ---- enabled / muted state ---------------------------------------------
def test_project_only_fields_disabled_off_project_scope(win, model):
    gas = win.gas_correction_widget
    assert gas.nphi_spin.isEnabled()
    model.set_edit_scope("well")
    assert not gas.nphi_spin.isEnabled() and gas.nphi_spin.toolTip() == "Project-wide setting"
    assert not win.sw_models_widget.methods_list.isEnabled()
    assert win.fluid_params_widget.rho_fluid_spin.isEnabled()      # well-only, fine at well
    model.set_edit_scope("well", "UPPER")
    assert not win.fluid_params_widget.rho_fluid_spin.isEnabled()  # no zone for well-only
    assert win.archie_params_widget.m_spin.isEnabled()
    model.set_edit_scope("project")
    assert gas.nphi_spin.isEnabled() and win.fluid_params_widget.rho_fluid_spin.isEnabled()
    assert gas.nphi_spin.toolTip() != "Project-wide setting"


def test_inherited_fields_muted_with_source_tooltip(win, model):
    model.set_entry("m", "manual", 1.9, scope="well")
    model.set_edit_scope("well")
    m_spin, n_spin = win.archie_params_widget.m_spin, win.archie_params_widget.n_spin
    assert m_spin.property("status") is None
    assert n_spin.property("status") == "muted" and n_spin.toolTip() == "From project"
    model.set_entry("n", "manual", 2.2, scope="project", zone="UPPER")
    model.set_edit_scope("well", "UPPER")
    assert n_spin.toolTip() == "From project · zone"
    assert m_spin.toolTip() == "From well"
    model.set_edit_scope("project")
    assert n_spin.property("status") is None            # flat scope: no decoration


def test_temperature_group_edits_project_defaults_and_well_entries(win, model):
    tmp = win.temperature_widget
    tmp.surface_spin.setValue(70.0)
    assert model.surface_temp == 70.0
    model.set_edit_scope("well")
    tmp.ref_spin.setValue(60.0)
    assert model.get_entry("rw_ref_temp")["value"] == 60.0 and model.rw_ref_temp == 75.0
    assert tmp.grad_auto_cb.isEnabled()
    model.set_edit_scope("well", "UPPER")
    assert not tmp.ref_spin.isEnabled()


# ---- apply buttons, copy, promote ---------------------------------------
def test_apply_rw_at_well_scope_stores_calibrated_source(win, model):
    model.set_edit_scope("well")
    win.show_calculated_rw_rsh(0.031, 4.2)
    win.res_params_widget.apply_btn.click()
    entry = model.get_entry("rw")
    assert entry["value"] == 0.031 and entry["source"] == "calibrated"
    assert entry["method"] == "Rwa" and entry["date"]
    assert model.get_entry("rsh")["value"] == 4.2
    assert model.rw != 0.031
    info = model.scope_view()[1]["rw"]
    assert info["source"] == "calibrated" and info["here"]


def test_apply_rw_at_project_scope_keeps_flat_behaviour(win, model):
    win.show_calculated_rw_rsh(0.031, 4.2)
    win.res_params_widget.apply_btn.click()
    assert model.rw == 0.031 and model.rw_mode == "manual"
    assert model.project.get("WELL:A").overrides == {}


def test_apply_perm_and_shale_at_well_scope(win, model):
    model.set_edit_scope("well")
    perm = win.perm_params_widget
    perm.show_calculated_result(5000.0, 4.0, 1.5)
    perm.apply_btn.click()
    entry = model.get_entry("perm_C")
    assert entry["value"] == 5000.0 and entry["method"] == "core calibration"
    model.calculated_shale = {"rho_shale": 2.5, "dt_shale": 90.0, "nphi_shale": 0.3}
    win.shale_params_widget.apply_btn.click()
    assert model.get_entry("dt_shale")["method"] == "shale estimate"
    assert model.dt_shale != 90.0


def test_copy_to_other_well_and_set_project_default(win, model):
    model.set_edit_scope("well")
    win.archie_params_widget.m_spin.setValue(1.9)
    targets = dict(win.copy_targets("m"))
    assert list(targets) == ["B"]
    win.copy_field_to("m", [targets["B"]])
    assert model.project.get("WELL:B").overrides["m"]["value"] == 1.9
    win.promote_field("m")
    assert model.m == 1.9
    model.set_edit_scope("well", "LOWER")
    labels = [label for label, _t in win.copy_targets("m")]
    assert labels == ["B · LOWER", "Project · LOWER (every well)"]
    win.archie_params_widget.m_spin.setValue(1.7)
    win.copy_field_to("m", [("project", "LOWER", None)])
    assert model.project.zone_params["LOWER"]["m"]["value"] == 1.7
    win.promote_field("m")                       # zone scope: still the flat project value
    assert model.m == 1.7


def test_validation_warning_inline_not_modal(win, model):
    model.set_edit_scope("well")
    win._controls["rw"].actions_["manual"].trigger()
    win.res_params_widget.rw_spin.setValue(0.002)      # below the plausible range
    control = win._controls["rw"]
    assert control.caption.text() == "Check value"
    assert control.caption.property("status") == "warning"
    assert "Rw" in win.res_params_widget.rw_spin.toolTip()
    assert win.res_params_widget.rw_spin.property("status") == "warning"
    win.res_params_widget.rw_spin.setValue(0.05)
    assert control.caption.property("status") == "muted" or control.caption.text() != "Check value"


# ---- zone grid ----------------------------------------------------------
def test_zone_grid_rows_and_inherited_cells(win, model):
    grid = win.zone_grid
    model.set_edit_scope("well")
    assert grid.zones() == ["UPPER", "LOWER"]
    cell = _grid_cell(grid, "UPPER", "m")
    assert cell.data(STATE_ROLE) == "inherited"
    assert cell.text() == f"{model.m:g}"
    model.set_entry("m", "manual", 1.9, scope="well", zone="UPPER")
    cell = _grid_cell(grid, "UPPER", "m")
    assert cell.data(STATE_ROLE) == "set" and cell.text() == "1.9"
    assert _grid_cell(grid, "LOWER", "m").data(STATE_ROLE) == "inherited"


def test_zone_grid_edit_clear_and_auto(win, model):
    grid = win.zone_grid
    model.set_edit_scope("well")
    _grid_cell(grid, "LOWER", "n").setText("2.3")
    ds = model.project.get("WELL:A")
    assert ds.zone_overrides["LOWER"]["n"]["value"] == 2.3
    assert model.project.get("WELL:B").zone_overrides == {}
    _grid_cell(grid, "LOWER", "n").setText("")
    assert ds.zone_overrides == {}
    _grid_cell(grid, "UPPER", "rw").setText("auto")
    assert ds.zone_overrides["UPPER"]["rw"]["mode"] == "auto"
    assert _grid_cell(grid, "UPPER", "rw").text() == "auto"
    _grid_cell(grid, "UPPER", "m").setText("auto")        # no Auto estimate for m
    assert "m" not in ds.zone_overrides["UPPER"]


def test_zone_grid_project_scope_uses_project_zones(win, model):
    grid = win.zone_grid
    assert grid.grid_scope() == "project"
    _grid_cell(grid, "UPPER", "a").setText("0.9")
    assert model.project.zone_params["UPPER"]["a"]["value"] == 0.9
    assert model.a != 0.9
    model.set_entry("a", "manual", 1.1, scope="project", zone="EXTRA")
    assert "EXTRA" in grid.zones()
    _grid_cell(grid, "EXTRA", "a").setText("")
    assert "EXTRA" not in model.project.zone_params


def test_zone_grid_flags_implausible_value(win, model):
    model.set_edit_scope("well")
    _grid_cell(win.zone_grid, "UPPER", "m").setText("5")
    cell = _grid_cell(win.zone_grid, "UPPER", "m")
    assert cell.data(STATE_ROLE) == "warning" and "outside" in cell.toolTip()


def test_zone_grid_refresh_creates_no_entries(win, model):
    before = _stores(model)
    for scope in ("well", "project"):
        model.set_edit_scope(scope)
    model.set_active_well("WELL:B")
    assert _stores(model) == before
