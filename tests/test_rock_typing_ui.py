"""Rock Typing tab: states, Fit/Apply rules, editing, enable switch, stale banner (P1 spec 7.1)."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from PyQt6.QtCore import Qt

from models.app_model import AppModel
from modules import rock_typing as rt
from ui.tabs.rock_typing_tab import RockTypingTab


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A modal box would block the offscreen test run; fail loudly instead."""
    from PyQt6.QtWidgets import QMessageBox

    def refuse(*args, **kwargs):
        raise AssertionError(f"unexpected dialog: {args[1:3]}")

    for name in ("warning", "critical", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(refuse))


def _handler(n_per_pop, seed, centres=(-0.5, 0.0, 0.6)):
    rng = np.random.default_rng(seed)
    lf = np.concatenate([rng.normal(c, 0.05, n_per_pop) for c in centres])
    phi = rng.uniform(0.10, 0.30, len(lf))
    k = rt.perm_from_fzi(10.0 ** lf, phi)
    depth = 1000.0 + np.arange(len(lf)) * 0.5
    return SimpleNamespace(
        data=pd.DataFrame({"depth": depth, "por": phi, "perm": k}),
        depth_col="depth", porosity_col="por", perm_col="perm", depth_is_tvd=False,
        excluded_rows=[], excluded_row_wells={}, spellings=[])


def _model(n=20):
    model = AppModel()
    for i in range(3):
        key = f"WELL:W{i}"
        model.project._wells[key] = SimpleNamespace(
            key=key, display_name=f"W{i}", core_data=_handler(n, i), formation_tops=None)
    return model


@pytest.fixture()
def tab(qtbot):
    t = RockTypingTab(_model())
    qtbot.addWidget(t)
    return t


def _fit(qtbot, tab):
    with qtbot.waitSignal(tab.fit_finished, timeout=60000):
        tab.fit_button.click()


def test_empty_state_names_what_is_missing(qtbot):
    t = RockTypingTab(AppModel())
    qtbot.addWidget(t)
    assert t.stack.currentIndex() == 0
    assert "core" in t.placeholder.text().lower()
    assert not t.fit_button.isEnabled()
    assert not t.apply_button.isEnabled()


def test_empty_state_core_without_permeability(qtbot):
    model = AppModel()
    h = _handler(5, 0)
    h.perm_col = None
    model.project._wells["WELL:A"] = SimpleNamespace(
        key="WELL:A", display_name="A", core_data=h, formation_tops=None)
    t = RockTypingTab(model)
    qtbot.addWidget(t)
    assert t.stack.currentIndex() == 0
    assert "permeability" in t.placeholder.text()


def test_fit_enabled_apply_disabled_until_proposal(tab):
    assert tab.stack.currentIndex() == 1
    assert tab.fit_button.isEnabled()
    assert not tab.apply_button.isEnabled()
    assert not tab.cancel_button.isEnabled()


def test_fit_produces_proposal_and_apply_writes_project(qtbot, tab):
    model = tab.model
    _fit(qtbot, tab)
    assert tab._proposal is not None
    assert tab.apply_button.isEnabled()
    assert model.project.rock_types is None          # a fit never writes the model
    assert tab.defs_table.rowCount() == 3
    assert tab.fit_button.isEnabled()
    tab.apply_button.click()
    defs = model.project.rock_types
    assert defs is not None and defs["sets"]["*"]["n_rt"] == 3
    assert "_display" not in defs
    assert not tab.apply_button.isEnabled()
    assert model.dirty


def test_editing_boundary_sets_edited(qtbot, tab):
    _fit(qtbot, tab)
    tab.apply_button.click()
    before = tab.model.project.rock_types["sets"]["*"]["boundaries"]
    assert tab.model.project.rock_types["sets"]["*"]["edited"] is False
    item = tab.defs_table.item(1, 4)                 # lower boundary of rock type 2
    item.setText(f"{before[0] + 0.01:.4f}")
    stored = tab.model.project.rock_types["sets"]["*"]
    assert stored["edited"] is True
    assert stored["boundaries"][0] == pytest.approx(before[0] + 0.01, abs=1e-4)
    assert "edited manually" in tab.defs_basis.text()


def test_non_monotonic_boundary_is_refused(qtbot, tab):
    _fit(qtbot, tab)
    tab.apply_button.click()
    before = list(tab.model.project.rock_types["sets"]["*"]["boundaries"])
    tab.defs_table.item(1, 4).setText(f"{before[1] + 1.0:.4f}")
    stored = tab.model.project.rock_types["sets"]["*"]
    assert stored["boundaries"] == before and stored["edited"] is False


def test_enable_checkbox_toggles_model(tab):
    seen = []
    tab.model.parameters_changed.connect(lambda: seen.append(1))
    assert tab.model.rock_typing_enabled is False
    tab.enable_check.setChecked(True)
    assert tab.model.rock_typing_enabled is True
    assert seen and tab.model.dirty
    assert tab.enable_hint.isVisibleTo(tab)          # no definitions applied yet
    tab.enable_check.setChecked(False)
    assert tab.model.rock_typing_enabled is False


def test_stale_banner_after_core_change(qtbot, tab):
    _fit(qtbot, tab)
    tab.apply_button.click()
    assert not tab.stale_banner.isVisibleTo(tab)
    core = tab.model.project._wells["WELL:W0"].core_data
    core.data.loc[core.data.index[0], "perm"] *= 3.0
    tab.update_display()
    assert tab.stale_banner.isVisibleTo(tab)
    assert "refit" in tab.stale_banner.text().lower()


def test_well_scope_shows_persistent_note(qtbot, tab):
    idx = tab.scope_combo.findData("well")
    tab.scope_combo.setCurrentIndex(idx)
    assert tab.scope_note.isVisibleTo(tab)
    assert "not comparable" in tab.scope_note.text()


def test_too_few_rows_is_a_status_message(qtbot):
    model = _model(n=2)
    t = RockTypingTab(model)
    qtbot.addWidget(t)
    _fit(qtbot, t)
    assert t._proposal is None
    assert not t.apply_button.isEnabled()
    assert "at least" in t.status_label.text()


def test_exclusion_table_counts_valid_rows(tab):
    texts = [tab.excl_table.item(r, 0).text() for r in range(tab.excl_table.rowCount())]
    assert "valid (used)" in texts


# ---------------------------------------------------------------- page layout
def _fit_and_apply(qtbot, tab):
    _fit(qtbot, tab)
    tab.apply_button.click()


def test_whole_page_is_one_scroll_area(qtbot, tab):
    from PyQt6.QtWidgets import QScrollArea, QSplitter

    tab.resize(1400, 900)
    tab.show()
    _fit_and_apply(qtbot, tab)
    areas = [a for a in tab.findChildren(QScrollArea) if a.__class__ is QScrollArea]
    assert areas == [tab.page_scroll]
    assert tab.page_scroll.widgetResizable()
    assert not tab.findChildren(QSplitter)
    assert tab.page_scroll.widget() is tab.page
    for w in (tab.fit_button, tab.stack, tab.plot_tabs, tab.defs_table):
        assert tab.page.isAncestorOf(w)


def test_tables_show_all_rows_without_own_scrollbar(qtbot, tab):
    tab.resize(1400, 900)
    tab.show()
    _fit_and_apply(qtbot, tab)
    tab.plot_tabs.setCurrentWidget(tab.plot_lorenz.parentWidget())
    qtbot.wait(50)
    assert tab.defs_table.rowCount() == 3
    for t in (tab.defs_table, tab.excl_table, tab.pay_table, tab.units_view):
        assert t.verticalScrollBar().maximum() == 0
        rows = t.model().rowCount()
        need = t.horizontalHeader().height() + sum(t.rowHeight(r) for r in range(rows))
        assert t.height() >= need
    assert tab.plot_fzi.minimumHeight() >= 420


def test_controls_need_no_horizontal_scrollbar(qtbot, tab):
    tab.resize(1400, 900)
    tab.show()
    _fit_and_apply(qtbot, tab)
    qtbot.wait(50)
    assert tab.page_scroll.horizontalScrollBar().maximum() == 0
    controls = tab.fit_button.parentWidget()
    assert controls.width() >= 300
    for w in (tab.method_combo, tab.min_phie_spin, tab.ob_k_spin, tab.status_label):
        right = w.mapTo(controls, w.rect().topRight()).x()
        assert right <= controls.width()


def test_wheel_over_plot_scrolls_the_page(qtbot, tab):
    from PyQt6.QtCore import QPoint, QPointF
    from PyQt6.QtGui import QWheelEvent
    from PyQt6.QtWidgets import QApplication

    tab.resize(1400, 500)
    tab.show()
    _fit_and_apply(qtbot, tab)
    qtbot.wait(50)
    bar = tab.page_scroll.verticalScrollBar()
    assert bar.maximum() > 0
    canvas = tab.plot_fzi.canvas
    pos = QPointF(canvas.width() / 2, canvas.height() / 2)
    ev = QWheelEvent(pos, canvas.mapToGlobal(pos), QPoint(0, 0), QPoint(0, -120),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(canvas, ev)
    assert bar.value() > 0
