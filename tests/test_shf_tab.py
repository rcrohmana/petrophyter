"""Saturation-Height tab: enable switch, explicit Fit / Apply / Accept writes, pay gate, contacts."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import copy
import io

import numpy as np
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

from models.project import WellDataset
from modules.pc_handler import PcDataHandler
from modules.pipeline import run_pipeline
from modules.shf import BASIS_CORE, BASIS_LOG, ShfFit
from tests.golden.cases import FULL_MAPPING, ROCK_TYPE_DEFS, fixture_frame
from ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A modal box would block the offscreen test run; fail loudly instead."""
    def refuse(*args, **kwargs):
        raise AssertionError(f"unexpected dialog: {args[1:3]}")

    for name in ("warning", "critical", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(refuse))


@pytest.fixture()
def window(qtbot):
    w = MainWindow()
    qtbot.addWidget(w, before_close_func=lambda w: w._set_busy(None))
    return w


def _fit_dict(basis=BASIS_CORE, key="All"):
    return ShfFit(rock_type=key, model="power", params={"c": 0.45, "d": -0.55}, basis=basis,
                  n_samples=10, n_points=100).to_dict()


def _pc_text():
    """Four samples of the power curve Sw = 0.45 * J^-0.55 in an air-brine lab."""
    rows = ["Well,Sample,Depth (ft),Porosity,Perm (mD),Pc (psi),Sw,System"]
    for i, (phi, k) in enumerate(((0.12, 5.0), (0.16, 20.0), (0.20, 80.0), (0.24, 200.0))):
        for j in (0.6, 0.9, 1.3, 2.0, 3.0):
            sw = 0.45 * j ** -0.55
            pc = j * 72.0 / (0.2166 * np.sqrt(k / phi))
            rows.append(f"A,P{i},{5000 + i},{phi},{k},{pc:.6f},{sw:.6f},air-brine")
    return "\n".join(rows) + "\n"


def _well(window, contacts=None, run=True, enabled=True, fits=True, pc=True):
    """Load a well with logs (and a finished run when asked) into the window's model."""
    model = window.model
    model.project.shf["enabled"] = enabled
    if fits:
        model.project.shf["fits"] = {"All": _fit_dict()}
    data = fixture_frame("sample_log_data")
    ds = WellDataset(key="WELL:A", display_name="A")
    ds.las_data = data
    ds.curve_mapping = dict(FULL_MAPPING)
    if contacts is not None:
        ds.shf_contacts = copy.deepcopy(contacts)
    if pc:
        handler = PcDataHandler()
        assert handler.read_pc_from_buffer(io.StringIO(_pc_text()))
        ds.pc_data = handler
    model.project.add_well(ds, activate=True)
    if run:
        results, summary = run_pipeline(data.copy(), ds.curve_mapping, model.params_for_well(ds))
        ds.results, ds.summary, ds.calculated = results, summary, True
        ds.run_params_hash = model.well_params_hash(ds)
    window.shf_tab.update_display()
    return ds


CONTACTS = {"datum": "TVD", "kb_ft": None,
            "default": {"fwl": 1090.0, "fluid": "oil", "water_density": None}, "zones": {}}


def _fit(qtbot, tab, button=None):
    with qtbot.waitSignal(tab.fit_finished, timeout=60000):
        (button or tab.fit_button).click()


def _set_row(tab, row, fwl=None, water=None):
    if fwl is not None:
        tab.contact_table.item(row, 1).setText(fwl)
    if water is not None:
        tab.contact_table.item(row, 3).setText(water)


# ---- tab wiring ---------------------------------------------------------------------------
def test_tab_follows_rock_typing(window):
    texts = [window.tab_widget.tabText(i) for i in range(window.tab_widget.count())]
    assert texts.index("Saturation-Height") == texts.index("Rock Typing") + 1
    assert window.tab_widget.widget(texts.index("Saturation-Height")) is window.shf_tab
    assert window.shf_tab in window._lazy_tabs


def test_enable_toggles_project_setting_and_asks_for_stale_check(window, qtbot):
    tab = window.shf_tab
    assert window.model.project.shf["enabled"] is False
    with qtbot.waitSignal(tab.stale_requested, timeout=500):
        tab.enable_check.setChecked(True)
    assert window.model.project.shf["enabled"] is True
    assert window.model.dirty
    tab.enable_check.setChecked(False)
    assert window.model.project.shf["enabled"] is False


def test_fluid_and_tension_edits_clear_the_defaults_badge(window):
    tab = window.shf_tab
    assert not tab.defaults_badge.isHidden()
    tab.fluid_spins["oil"].setValue(0.8)
    tab.fluid_spins["oil"].editingFinished.emit()
    assert window.model.project.shf["fluids"]["oil"] == pytest.approx(0.8)
    assert tab.defaults_badge.isHidden()
    window.model.project.clear()                  # New Project: defaults again
    tab.reset_ui()
    assert not tab.defaults_badge.isHidden()


# ---- fit, apply ---------------------------------------------------------------------------
def test_fit_proposes_and_only_apply_fit_writes(window, qtbot):
    ds = _well(window, run=False, fits=False)
    tab = window.shf_tab
    assert tab.fit_button.isEnabled()
    assert not tab.apply_button.isEnabled()
    _fit(qtbot, tab)
    assert window.model.project.shf["fits"] == {}            # Fit alone changes nothing
    assert tab.apply_button.isEnabled()
    assert tab.fit_table.rowCount() == 1 and tab.fit_table.item(0, 0).text() == "All"
    assert tab.fit_table.item(0, 6).text() == "core Pc"
    assert tab.fit_table.item(0, 7).text() == "ok"
    with qtbot.waitSignal(tab.stale_requested, timeout=500):
        tab.apply_button.click()
    fits = window.model.project.shf["fits"]
    assert set(fits) == {"All"} and fits["All"]["basis"] == BASIS_CORE
    assert fits["All"]["params"]["c"] == pytest.approx(0.45, rel=0.02)
    assert fits["All"]["params"]["d"] == pytest.approx(-0.55, rel=0.02)
    assert not tab.apply_button.isEnabled()


def test_fit_needs_pc_data(window):
    _well(window, run=False, fits=False, pc=False)
    assert not window.shf_tab.fit_button.isEnabled()
    assert "capillary" in window.shf_tab.fit_button.toolTip().lower()


def test_fit_from_logs_gives_a_log_basis_and_closes_the_pay_switch(window, qtbot):
    _well(window, contacts=CONTACTS, fits=True)
    tab = window.shf_tab
    assert tab.fit_logs_button.isEnabled()
    _fit(qtbot, tab, tab.fit_logs_button)
    assert tab.fit_table.item(0, 6).text() == "log-derived"
    tab.apply_button.click()
    assert window.model.project.shf["fits"]["All"]["basis"] == BASIS_LOG
    assert not tab.pay_check.isEnabled()


def test_pay_switch_disabled_for_log_derived_fits(window):
    _well(window, run=False)
    tab = window.shf_tab
    assert tab.pay_check.isEnabled()
    window.model.project.shf["fits"] = {"All": _fit_dict(BASIS_LOG)}
    tab.update_display()
    assert not tab.pay_check.isEnabled()
    assert tab.pay_check.toolTip() == "Log-derived fits are a cross-check only"
    window.model.project.shf["fits"] = {"All": _fit_dict(BASIS_CORE)}
    tab.update_display()
    assert tab.pay_check.isEnabled()
    tab.pay_check.setChecked(True)
    assert window.model.project.shf["use_for_pay"] is True


def test_zone_scoped_rock_types_show_the_all_note(window):
    _well(window, run=False)
    model = window.model
    defs = copy.deepcopy(ROCK_TYPE_DEFS)
    defs["fit_scope"] = "zone"
    model.project.rock_types = defs
    model.rock_typing_enabled = True
    window.shf_tab.update_display()
    tab = window.shf_tab
    assert not tab.rt_note.isHidden()
    assert tab.rt_note.text() == ("Rock types are fitted per zone; one saturation-height fit is "
                                  "used for all types.")


# ---- contacts -----------------------------------------------------------------------------
def test_contact_table_lists_default_and_stored_values(window):
    ds = _well(window, contacts=CONTACTS, run=False)
    t = window.shf_tab.contact_table
    assert t.item(0, 0).text() == "Default"
    assert t.item(0, 1).text() == "1090"
    assert t.cellWidget(0, 2).currentData() == "oil"
    assert t.item(0, 3).text() == ""
    assert ds.shf_contacts == CONTACTS


def test_tvdss_without_kb_disables_accept(window):
    _well(window, run=False)
    tab = window.shf_tab
    assert tab.accept_button.isEnabled()
    tab.datum_combo.setCurrentIndex(tab.datum_combo.findData("TVDSS"))
    assert not tab.accept_button.isEnabled()
    assert not tab.estimate_button.isEnabled()
    assert tab.contact_status.text() == "KB required for TVDSS"
    tab.kb_edit.setText("25")
    assert tab.accept_button.isEnabled()


def test_kb_hint_shows_the_header_values(window):
    ds = _well(window, run=False)
    ds.identity = {"kb_elevation": 25.0, "kb_elevation_unit": "m",
                   "depth_measured_from": "KB", "permanent_datum": "MSL"}
    window.shf_tab.update_active_well()
    hint = window.shf_tab.kb_hint.text()
    assert "KB 25.0 m" in hint and "depth measured from KB" in hint and "MSL" in hint
    assert window.shf_tab.kb_edit.text() == ""                  # a hint, never filled in


def test_water_density_out_of_range_is_refused(window):
    ds = _well(window, run=False)
    tab = window.shf_tab
    _set_row(tab, 0, fwl="1090", water="1.5")
    tab.accept_button.click()
    assert ds.shf_contacts == {}
    assert "outside" in tab.contact_status.text()
    _set_row(tab, 0, water="1.08")
    tab.accept_button.click()
    assert ds.shf_contacts["default"] == {"fwl": 1090.0, "fluid": "oil", "water_density": 1.08}
    assert ds.shf_contacts["datum"] == "TVD" and ds.shf_contacts["kb_ft"] is None


def test_accept_writes_tvdss_with_kb(window):
    ds = _well(window, run=False)
    tab = window.shf_tab
    tab.datum_combo.setCurrentIndex(tab.datum_combo.findData("TVDSS"))
    tab.kb_edit.setText("25")
    _set_row(tab, 0, fwl="1065")
    tab.accept_button.click()
    assert ds.shf_contacts["datum"] == "TVDSS" and ds.shf_contacts["kb_ft"] == 25.0
    assert ds.shf_contacts["default"]["fwl"] == 1065.0


def test_accept_marks_the_run_well_stale(window, qtbot):
    ds = _well(window, contacts=CONTACTS)
    assert ds.calculated and not ds.stale
    tab = window.shf_tab
    _set_row(tab, 0, fwl="1080")
    tab.accept_button.click()
    assert ds.shf_contacts["default"]["fwl"] == 1080.0
    assert ds.stale
    assert window.model.dirty


def test_accepting_unchanged_contacts_leaves_the_well_current(window):
    ds = _well(window, contacts=CONTACTS)
    window.shf_tab.accept_button.click()
    assert not ds.stale


def test_apply_fit_marks_the_run_well_stale(window, qtbot):
    ds = _well(window, contacts=CONTACTS, fits=False)
    window.model.project.shf["fits"] = {"All": _fit_dict()}      # what the run used
    ds.run_params_hash = window.model.well_params_hash(ds)
    ds.stale = False
    tab = window.shf_tab
    _fit(qtbot, tab)
    tab.apply_button.click()
    assert ds.stale


def test_estimate_never_writes_and_reports(window):
    ds = _well(window, contacts=CONTACTS)
    tab = window.shf_tab
    tab.contact_table.selectRow(0)
    tab.estimate_button.click()
    assert tab.contact_status.text()
    assert ds.shf_contacts == CONTACTS                           # only Accept writes
    assert not ds.stale


def test_estimate_without_a_run_explains(window):
    _well(window, run=False)
    window.shf_tab.estimate_button.click()
    assert "Run this well" in window.shf_tab.contact_status.text()


def test_misfit_table_reads_the_last_run(window):
    ds = _well(window, contacts=CONTACTS)
    t = window.shf_tab.stats_table
    assert t.rowCount() >= 1 and t.item(0, 0).text() == "Well"
    assert t.item(0, 1).text() == str(ds.summary["shf"]["stats"]["well"]["n"])
    assert t.item(0, 6).text() == "core Pc"


def test_run_all_button_follows_stale_wells_and_batch(window):
    ds = _well(window, contacts=CONTACTS)
    tab = window.shf_tab
    assert tab.run_all_button.isHidden()
    ds.stale = True
    tab.update_display()
    assert not tab.run_all_button.isHidden()
    tab.set_batch_running(True)
    assert not tab.run_all_button.isEnabled()
    tab.set_batch_running(False)
    assert tab.run_all_button.isEnabled()
