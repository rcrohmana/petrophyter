"""Parameters page "Uncertainty": rho with disabled parameters and the auto-Rw quality note."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QMessageBox

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


def test_rho_with_disabled_parameters_is_not_an_error(window, page):
    page._rows["a"].enable.setChecked(True)
    page.rho_spin.setValue(0.5)
    assert not page.rho_spin.isEnabled()
    assert "m or n" in page.rho_spin.toolTip()
    assert not page.status_label.isVisible()
    assert page.status_label.text() == ""


def test_rho_enabled_when_m_and_n_enabled(window, page):
    page._rows["m"].enable.setChecked(True)
    assert not page.rho_spin.isEnabled()
    page._rows["n"].enable.setChecked(True)
    assert page.rho_spin.isEnabled()


def test_rw_quality_note_follows_last_result(window, page):
    assert "after a run" in page.rw_quality_label.text()
    window.model.project.uncertainty_result = SimpleNamespace(rw_quality={"w": ["water_leg"]})
    page.load_from_config()
    assert page.rw_quality_label.text() == "Auto Rw: from water leg (last run)"


def test_info_names_shf_sw_only_when_used_for_pay(window, page):
    page._refresh_info()
    assert "SHF" not in page.info_label.text()
    window.model.project.shf.update(enabled=True, use_for_pay=True)
    page._refresh_info()
    assert "SHF Sw where used for pay" in page.info_label.text()
    window.model.project.shf["enabled"] = False
    page._refresh_info()
    assert "SHF" not in page.info_label.text()
