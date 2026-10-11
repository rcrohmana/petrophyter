"""U10: Parameters-window controls for the P0 'C' items, and their messages."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from models.app_model import AppModel
from models.project import WellDataset
from modules.well_import import ImportOptions, WellRef, build_parts, import_record
from services.session_service import SessionService
from tests.golden.cases import FULL_MAPPING, fixture_frame, make_tops
from ui.parameters_window import ParametersWindow
from ui.widgets.parameter_groups import PermParamsGroup, ResistivityParamsGroup
from ui.widgets.well_import_dialog import MultiWellImportDialog


def _model():
    model = AppModel()
    ds = WellDataset(key="WELL:A", display_name="A")
    ds.las_data = fixture_frame("sample_log_data")
    ds.curve_mapping = dict(FULL_MAPPING)
    ds.formation_tops = make_tops()
    model.add_well(ds)
    model.set_active_well("WELL:A")
    return model


@pytest.fixture
def model():
    return _model()


@pytest.fixture
def win(qtbot, model):
    window = ParametersWindow(model)
    qtbot.addWidget(window)
    return window


# ---- C1 / C4 / C11 controls ----------------------------------------------------
def test_controls_write_the_project_values_to_the_model(win, model):
    por, gas, vsh = win.porosity_method_widget, win.gas_correction_widget, win.vsh_params_widget
    por.dn_combo.setCurrentIndex(por.dn_combo.findData("RMS"))
    gas.crossover_spin.setValue(0.035)
    gas.gas_vsh_spin.setValue(0.25)
    vsh.primary_combo.setCurrentIndex(vsh.primary_combo.findData("Larionov Tertiary"))
    assert model.dn_combination == "RMS"
    assert model.gas_crossover_min == pytest.approx(0.035)
    assert model.gas_vsh_max == pytest.approx(0.25)
    assert model.vsh_primary_method == "Larionov Tertiary"
    vsh.primary_combo.setCurrentIndex(0)
    assert model.vsh_primary_method is None


def test_controls_follow_the_model(win, model):
    model.dn_combination, model.gas_crossover_min, model.gas_vsh_max = "RMS", 0.05, 0.3
    model.vsh_primary_method = "Larionov Older"
    win.refresh_scope_view()
    assert win.porosity_method_widget.dn_combo.currentData() == "RMS"
    assert win.gas_correction_widget.crossover_spin.value() == pytest.approx(0.05)
    assert win.gas_correction_widget.gas_vsh_spin.value() == pytest.approx(0.3)
    assert win.vsh_params_widget.primary_combo.currentData() == "Larionov Older"


def test_session_round_trip_through_the_window(qtbot, win, model, tmp_path):
    win.porosity_method_widget.dn_combo.setCurrentIndex(1)
    win.gas_correction_widget.crossover_spin.setValue(0.04)
    win.vsh_params_widget.primary_combo.setCurrentIndex(
        win.vsh_params_widget.primary_combo.findData("Larionov Tertiary"))
    # Zone scope: only the zone-capable keys can be set.
    model.set_edit_scope("project", "LOWER")
    win.porosity_method_widget.dn_combo.setCurrentIndex(0)
    win.gas_correction_widget.gas_vsh_spin.setValue(0.2)
    assert not win.vsh_params_widget.primary_combo.isEnabled()     # project-wide only
    path = str(tmp_path / "s.json")
    svc = SessionService()
    assert svc.save_session(model, path)

    fresh = AppModel()
    assert svc.apply_session_to_model(fresh, svc.load_session(path))
    other = ParametersWindow(fresh)
    qtbot.addWidget(other)
    assert other.porosity_method_widget.dn_combo.currentData() == "RMS"
    assert other.gas_correction_widget.crossover_spin.value() == pytest.approx(0.04)
    assert other.vsh_params_widget.primary_combo.currentData() == "Larionov Tertiary"
    lower = fresh.project.zone_params["LOWER"]
    assert lower["dn_combination"]["value"] == "Average"
    assert lower["gas_vsh_max"]["value"] == pytest.approx(0.2)
    fresh.set_edit_scope("project", "LOWER")
    assert other.porosity_method_widget.dn_combo.currentData() == "Average"
    assert other.gas_correction_widget.gas_vsh_spin.value() == pytest.approx(0.2)
    assert other.gas_correction_widget.crossover_spin.value() == pytest.approx(0.04)  # inherited


def test_zone_edit_leaves_the_project_value_alone(win, model):
    model.set_edit_scope("well", "UPPER")
    win.gas_correction_widget.crossover_spin.setValue(0.08)
    assert model.gas_crossover_min == pytest.approx(0.02)
    assert model.get_entry("gas_crossover_min")["value"] == pytest.approx(0.08)


# ---- focus_field ------------------------------------------------------------------
@pytest.mark.parametrize("field, page, attr", [
    ("dn_combination", "porosity", ("porosity_method_widget", "dn_combo")),
    ("gas_crossover_min", "gas", ("gas_correction_widget", "crossover_spin")),
    ("gas_vsh_max", "gas", ("gas_correction_widget", "gas_vsh_spin")),
    ("vsh_primary_method", "vshale", ("vsh_params_widget", "primary_combo")),
])
def test_focus_field_opens_the_page_and_focuses(win, qtbot, field, page, attr):
    win.show()
    win.gas_correction_widget.enable_check.setChecked(True)
    win.focus_field(field)
    assert win.current_page() == page
    widget = getattr(getattr(win, attr[0]), attr[1])
    assert win.focusWidget() is widget


def test_focus_field_rw_value_and_unknown(win, qtbot):
    win.show()
    win.res_params_widget.rw_auto_cb.setChecked(False)
    win.focus_field("rw_value")
    assert win.current_page() == "sat"
    assert win.focusWidget() is win.res_params_widget.rw_spin
    page = win.current_page()
    win.focus_field("no_such_field")
    assert win.current_page() == page


# ---- C8: Rw/Rsh counts and warnings ----------------------------------------------
def test_rw_rsh_page_shows_counts_and_warnings(win):
    win.show_calculated_rw_rsh(0.04, 3.0, ["Rw clamped to 0.02"], water_samples=42,
                               shale_samples=17, quality="fair")
    res = win.res_params_widget
    assert "42 water-leg samples" in res.counts_label.text()
    assert "17 shale samples" in res.counts_label.text()
    assert not res.counts_label.isHidden()
    assert res.message_label.text() == "Rw clamped to 0.02"
    assert res.message_label.property("status") == "warning"
    res.discard_calculated()
    assert res.counts_label.isHidden()


# ---- C13 / I6: perm messages keep the pending result ----------------------------------
def test_perm_message_can_keep_the_pending_result(qtbot):
    group = PermParamsGroup()
    qtbot.addWidget(group)
    group.show_calculated_result(5000.0, 4.0, 1.5, source="core calibration, 8 pairs")
    assert "core calibration, 8 pairs" in group.result_label.text()
    group.show_message("Swirr mismatch", "warning", keep_result=True)
    assert group.message_label.text() == "Swirr mismatch" and not group.message_label.isHidden()
    assert group.message_label.property("status") == "warning"
    assert not group.apply_btn.isHidden() and group._calculated_C == 5000.0
    # A new result clears the earlier note; a plain message drops the result.
    group.show_calculated_result(6000.0, 4.0, 1.5)
    assert group.message_label.isHidden()
    group.show_message("no pairs")
    assert group.apply_btn.isHidden() and group.result_label.text() == "no pairs"
    assert not hasattr(group, "_calculated_C")


# ---- I7: temperature readout ------------------------------------------------------------
def test_refused_bht_is_shown_in_warning_style(win, model):
    ds = model.active_well
    ds.identity = {"bht": 40.0, "td": 8000.0}          # BHT below the 80 degF surface
    win._update_temperature_readout()
    readout = win.temperature_widget.readout
    assert "not used" in readout.text()
    assert readout.property("status") == "warning"
    ds.identity = {"bht": 200.0, "td": 8000.0}
    win._update_temperature_readout()
    assert "not used" not in readout.text()
    assert readout.property("status") == "muted"


# ---- I9: tops TVD confirmation, end to end ---------------------------------------------------
def test_tops_tvd_confirmation_is_honoured_end_to_end(qtbot, tmp_path):
    path = tmp_path / "tops.csv"
    path.write_text("Well,Formation,Top TVD (ft),Bottom TVD (ft)\n"
                    "BKS-01,A,1000,1100\nBKS-01,B,1100,1200\n", encoding="utf-8")
    wells = [WellRef(key="WELL:BKS-01", display_name="BKS-01", well_info={"well_name": "BKS-01"},
                     log_top=0.0, log_bottom=10000.0)]
    dialog = MultiWellImportDialog("tops", str(path), wells, options=ImportOptions(kind="tops"))
    qtbot.addWidget(dialog)
    assert dialog.tvd_check.isVisibleTo(dialog) and not dialog.ok_button.isEnabled()
    with pytest.raises(ValueError, match="Confirm that TVD"):
        build_parts(dialog.plan, wells)
    dialog.tvd_check.setChecked(True)
    dialog.tvd_check.clicked.emit(True)
    assert dialog.ok_button.isEnabled()
    parts = build_parts(dialog.plan, wells)
    assert set(parts) == {"WELL:BKS-01"}
    assert import_record(dialog.plan, dialog.plan.rows[0])["tvd_confirmed"] is True
