"""Parameters page "Uncertainty" and the Analysis menu gating of Run Uncertainty / Stop Monte Carlo."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QMessageBox

from modules.uncertainty import (
    N_MAX, N_MIN, PARAM_ORDER, SUGGESTED_RANGES, UncertaintyConfig,
)
from ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError(f"unexpected dialog: {args[1:3]}")

    for name in ("warning", "critical", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(refuse))


@pytest.fixture()
def window(qtbot):
    w = MainWindow()
    qtbot.addWidget(w, before_close_func=lambda w: w._set_busy(None))
    return w


@pytest.fixture()
def page(window):
    return window.params_window.uncertainty_page


def cfg(window):
    return window.model.project.uncertainty


def test_page_registered(window):
    from ui.parameters_window import PAGES

    assert ("uncertainty", "Uncertainty", "Analysis", "sigma") in PAGES
    assert "page_uncertainty" in window.actions_
    window.actions_["page_uncertainty"].trigger()
    assert window.params_window.current_page() == "uncertainty"


def test_widgets_to_config_round_trip(window, page):
    row = page._rows["rw"]
    row.enable.setChecked(True)
    assert cfg(window).distributions["rw"].enabled
    row.spins["low"].setValue(-20.0)
    row.spins["mid"].setValue(5.0)
    row.spins["high"].setValue(25.0)
    d = cfg(window).distributions["rw"]
    assert (d.low, d.mid, d.high) == pytest.approx((-0.20, 0.05, 0.25))   # percent -> fraction
    assert d.mode == "relative"
    row_m = page._rows["m"]                  # additive by default: absolute units
    row_m.enable.setChecked(True)
    row_m.spins["high"].setValue(0.3)
    assert cfg(window).distributions["m"].high == pytest.approx(0.3)
    row_m.kind.setCurrentIndex(row_m.kind.findData("normal"))
    row_m.spins["sd"].setValue(0.1)
    d = cfg(window).distributions["m"]
    assert d.kind == "normal" and d.sd == pytest.approx(0.1)
    page.n_spin.setValue(N_MIN)
    page.seed_spin.setValue(42)
    page.sampling_combo.setCurrentIndex(page.sampling_combo.findData("random"))
    c = cfg(window)
    assert (c.n, c.seed, c.sampling) == (N_MIN, 42, "random")
    page.n_spin.setValue(N_MAX + 1000)
    assert cfg(window).n == N_MAX


def test_mode_change_keeps_stored_values(window, page):
    row = page._rows["rw"]
    row.enable.setChecked(True)
    row.spins["high"].setValue(25.0)
    row.mode.setCurrentIndex(row.mode.findData("additive"))
    d = cfg(window).distributions["rw"]
    assert d.mode == "additive" and d.high == pytest.approx(0.25)
    assert row.spins["high"].value() == pytest.approx(0.25)
    assert "ohm" in row.spins["high"].suffix()


def test_config_to_widgets_after_session_load(window, page):
    new = UncertaintyConfig(n=500, seed=7, sampling="random")
    d = new.distributions["rsh"]
    d.enabled, d.kind, d.mode, d.low, d.mid, d.high = True, "uniform", "relative", -0.1, 0.0, 0.3
    new.correlations[("m", "n")] = 0.4
    window.model.project.uncertainty = new
    window._refresh_uncertainty_page()
    row = page._rows["rsh"]
    assert row.enable.isChecked() and row.current_kind() == "uniform"
    assert row.spins["low"].value() == pytest.approx(-10.0)
    assert row.spins["high"].value() == pytest.approx(30.0)
    assert (page.n_spin.value(), page.seed_spin.value()) == (500, 7)
    assert page.sampling_combo.currentData() == "random"
    assert page.rho_spin.value() == pytest.approx(0.4)
    assert window.actions_["run_uncertainty"].isEnabled()
    assert not window.model.dirty        # a programmatic refresh is not an edit


def test_suggested_ranges_fill_without_enabling(window, page):
    page.suggest_btn.click()
    c = cfg(window)
    for name in PARAM_ORDER:
        d = c.distributions[name]
        assert not d.enabled and d.kind == "triangular"
        assert (d.low, d.mid, d.high) == SUGGESTED_RANGES[name]
    assert page._rows["a"].spins["high"].value() == pytest.approx(10.0)    # shown in percent
    assert page._rows["m"].spins["high"].value() == pytest.approx(0.15)    # additive: absolute
    assert not any(r.enable.isChecked() for r in page._rows.values())


def test_kind_switches_enabled_spins(page):
    row = page._rows["n"]
    row.enable.setChecked(True)

    def enabled():
        return {f for f, s in row.spins.items() if s.isEnabled()}

    assert enabled() == {"low", "mid", "high"}                 # triangular
    row.kind.setCurrentIndex(row.kind.findData("normal"))
    assert enabled() == {"mid", "sd"}
    row.kind.setCurrentIndex(row.kind.findData("uniform"))
    assert enabled() == {"low", "high"}
    row.enable.setChecked(False)
    assert enabled() == set()


def test_rho_stored_and_removed(window, page):
    page.rho_spin.setValue(0.5)
    assert cfg(window).correlations[("m", "n")] == pytest.approx(0.5)
    page.rho_spin.setValue(0.0)
    assert ("m", "n") not in cfg(window).correlations


def test_status_line_shows_validation_errors(window, page):
    assert page.status_label.text() == ""              # nothing enabled yet is not an error
    row = page._rows["a"]
    row.enable.setChecked(True)
    row.spins["low"].setValue(5.0)
    row.spins["high"].setValue(-5.0)
    assert "triangular" in page.status_label.text()
    assert page.status_label.property("status") == "warning"
    row.spins["high"].setValue(5.0)
    row.spins["low"].setValue(-5.0)
    assert page.status_label.text() == ""


def test_new_seed_changes_seed(window, page):
    page.seed_spin.setValue(1)
    page.new_seed_btn.click()
    assert cfg(window).seed == page.seed_spin.value()


def test_edits_mark_dirty_but_not_stale(window, page, monkeypatch):
    from models.project import WellDataset

    model = window.model
    ds = WellDataset(key="WELL:W1", display_name="W1")
    model.project.add_well(ds)
    before = model.well_params_hash(ds)
    stale_before = [w.stale for w in model.project.wells]
    model.mark_clean()
    page._rows["rw"].enable.setChecked(True)
    page.suggest_btn.click()
    page.rho_spin.setValue(0.2)
    assert model.dirty
    assert model.well_params_hash(ds) == before
    assert [w.stale for w in model.project.wells] == stale_before


def test_menu_gating_and_tooltips(window, page, monkeypatch):
    run, stop = window.actions_["run_uncertainty"], window.actions_["stop_uncertainty"]
    assert run.text() == "Run Uncertainty…" and run.shortcut().isEmpty()
    window.model.project.uncertainty = UncertaintyConfig()
    window._refresh_uncertainty_page()
    assert not run.isEnabled()
    assert run.toolTip() == "Enable a distribution on Parameters → Uncertainty"
    page._rows["a"].enable.setChecked(True)             # signal refreshes the menu
    assert run.isEnabled()
    mc = {"on": False}
    batch = {"on": False}
    monkeypatch.setattr(window.uncertainty_runner, "is_running", lambda: mc["on"])
    monkeypatch.setattr(window.batch_runner, "is_running", lambda: batch["on"])
    assert not stop.isEnabled()
    mc["on"] = True
    window._refresh_run_action()
    assert not run.isEnabled() and run.toolTip() == "Monte Carlo is running"
    assert stop.isEnabled()
    mc["on"], batch["on"] = False, True
    window._refresh_run_action()
    assert not run.isEnabled() and run.toolTip() == "Wait for the analysis to finish"
    assert not stop.isEnabled()
    batch["on"] = False
    window._refresh_run_action()
    assert run.isEnabled() and not stop.isEnabled()


def test_menu_order_after_run_all(window):
    texts = [a.text() for a in window._menus["analysis"].actions()]
    assert texts.index("Run Uncertainty…") == texts.index("Run All Wells") + 1
    assert "Stop Monte Carlo" in texts
