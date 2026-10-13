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


# ---------------------------------------------------------------------------
# Render cost: counters, never wall-clock
# ---------------------------------------------------------------------------
@pytest.fixture()
def counters(monkeypatch):
    from ui.widgets.plot_widget import PlotWidget

    calls = {"figure": 0, "pay": 0, "table": 0, "update": 0}

    def count(owner, name, key):
        orig = getattr(owner, name)

        def wrapper(*a, **k):
            calls[key] += 1
            return orig(*a, **k)
        monkeypatch.setattr(owner, name, wrapper)

    count(PlotWidget, "refresh", "figure")
    count(RockTypingTab, "_render_pay", "pay")
    count(RockTypingTab, "update_display", "update")
    count(rt, "build_core_table", "table")
    return calls


def _reset(calls):
    for k in calls:
        calls[k] = 0


def _window_on_rock_tab(qtbot):
    from models.project import WellDataset
    from ui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    for i in range(3):
        key = f"WELL:W{i}"
        ds = WellDataset(key, f"W{i}")
        ds.core_data = _handler(20, i)
        ds.core_data.get_summary = lambda: {}
        w.model.project._wells[key] = ds
    w.model.project.set_active("WELL:W0", force=True)
    w.tab_widget.setCurrentWidget(w.rock_tab)
    w.rock_tab.update_display()
    qtbot.wait(30)
    w._dirty_tabs.clear()
    return w


def test_active_well_change_renders_only_the_pay_table(qtbot, counters):
    w = _window_on_rock_tab(qtbot)
    assert w.rock_tab.plot_tabs.currentIndex() == 0
    _reset(counters)
    w.model.project.set_active("WELL:W1", force=True)
    qtbot.wait(30)
    assert counters["figure"] == 0
    assert counters["pay"] == 1
    assert counters["update"] == 0
    assert counters["table"] == 0


def test_active_well_change_redraws_phik_only_when_visible(qtbot, counters):
    w = _window_on_rock_tab(qtbot)
    w.rock_tab.plot_tabs.setCurrentIndex(1)
    qtbot.wait(30)
    # The overlay follows the active well's results: a new results object means a redraw.
    w.model.results = pd.DataFrame({"PHIE": [0.1, 0.2], "PERM_RT": [1.0, 10.0]})
    _reset(counters)
    w.model.project.set_active("WELL:W1", force=True)
    assert counters["figure"] == 1
    assert counters["pay"] == 1


def test_burst_of_wells_changed_renders_once(qtbot, counters):
    w = _window_on_rock_tab(qtbot)
    _reset(counters)
    for _ in range(3):
        w.model.project.wells_changed.emit()
    assert counters["update"] == 0          # coalesced, not run inside the emit
    qtbot.waitUntil(lambda: counters["update"] >= 1, timeout=2000)
    qtbot.wait(30)
    assert counters["update"] == 1


def test_hidden_rock_tab_stays_untouched_until_shown(qtbot, counters):
    w = _window_on_rock_tab(qtbot)
    w.tab_widget.setCurrentIndex(0)
    _reset(counters)
    w.model.project.wells_changed.emit()
    w.model.project.set_active("WELL:W2", force=True)
    qtbot.wait(30)
    assert counters["update"] == 0 and counters["figure"] == 0
    w.tab_widget.setCurrentWidget(w.rock_tab)
    assert counters["update"] == 1


def test_plot_subtab_switch_renders_only_that_figure(qtbot, tab, counters):
    tab.plot_tabs.setCurrentIndex(0)
    tab.update_display()
    _reset(counters)
    tab.update_display()
    assert counters["figure"] == 0          # unchanged data: FZI already shows it
    tab.plot_tabs.setCurrentIndex(2)
    assert counters["figure"] == 1
    tab.plot_tabs.setCurrentIndex(3)
    assert counters["figure"] == 2


def test_only_the_visible_subtab_is_drawn_on_update(qtbot, tab, counters):
    tab.plot_tabs.setCurrentIndex(0)
    tab.update_display()
    assert set(tab._plot_done) == {0}
    _reset(counters)
    tab.min_phie_spin.setValue(0.01)        # a settings change redraws the visible figure only
    assert counters["figure"] == 1


def test_unchanged_data_does_not_rebuild_core_table(qtbot, tab, counters):
    tab.update_display()
    _reset(counters)
    tab.update_display()
    tab.update_display()
    assert counters["table"] == 0


def test_core_edit_in_place_rebuilds_table(qtbot, tab, counters):
    tab.update_display()
    _reset(counters)
    core = tab.model.project._wells["WELL:W0"].core_data
    core.data.loc[core.data.index[0], "perm"] *= 3.0
    tab.update_display()
    assert counters["table"] == 1


# ---------------------------------------------------------------- next-step guidance
def _fake_active(monkeypatch, *, rock=False, stale=False, calculated=True):
    ds = SimpleNamespace(
        calculated=calculated, stale=stale,
        summary={"rock_types": {"by_rt": []}} if rock else {})
    monkeypatch.setattr(AppModel, "active_well", property(lambda self: ds))
    return ds


def test_guidance_enabled_without_definitions(tab):
    tab.enable_check.setChecked(True)
    assert tab.enable_hint.text() == "No definitions applied yet: fit and apply rock types first."
    assert tab.enable_hint.property("status") == "warning"
    assert not tab.run_all_button.isVisibleTo(tab)


def test_guidance_enabled_with_definitions_asks_for_a_run(qtbot, tab, monkeypatch):
    _fit_and_apply(qtbot, tab)
    _fake_active(monkeypatch, rock=False)
    tab.enable_check.setChecked(True)
    assert tab.enable_hint.text() == (
        "Rock typing is on. Run the analysis (or Run All Wells) to compute rock types.")
    assert tab.enable_hint.property("status") == "warning"
    assert tab.run_all_button.isVisibleTo(tab) and tab.run_all_button.isEnabled()


def test_guidance_stale_results_ask_for_a_run(qtbot, tab, monkeypatch):
    _fit_and_apply(qtbot, tab)
    _fake_active(monkeypatch, rock=True, stale=True)
    tab.enable_check.setChecked(True)
    assert tab.enable_hint.text().startswith("Rock typing is on. Run the analysis")
    assert tab.run_all_button.isVisibleTo(tab)


def test_guidance_results_with_rock_types_say_where(qtbot, tab, monkeypatch):
    _fit_and_apply(qtbot, tab)
    _fake_active(monkeypatch, rock=True)
    tab.enable_check.setChecked(True)
    assert tab.enable_hint.text() == (
        "Rock types are in the results: Summary → Rock types, Log Display → "
        "Rock Type track, and the exports.")
    assert tab.enable_hint.property("status") == "success"
    assert not tab.run_all_button.isVisibleTo(tab)


def test_guidance_disabled_after_a_run_says_next_run_drops_them(qtbot, tab, monkeypatch):
    _fit_and_apply(qtbot, tab)
    _fake_active(monkeypatch, rock=True)
    tab.enable_check.setChecked(True)
    tab.enable_check.setChecked(False)
    assert tab.enable_hint.text() == (
        "Rock types are in the current results. The next run drops them.")
    assert not tab.run_all_button.isVisibleTo(tab)


def test_guidance_disabled_without_results_is_silent(tab):
    assert not tab.enable_hint.isVisibleTo(tab)


def test_guidance_follows_a_finished_run(qtbot, tab, monkeypatch):
    _fit_and_apply(qtbot, tab)
    ds = _fake_active(monkeypatch, rock=False)
    tab.enable_check.setChecked(True)
    assert tab.run_all_button.isVisibleTo(tab)
    ds.summary = {"rock_types": {"by_rt": []}}
    tab.model.analysis_complete.emit()
    assert tab.enable_hint.text().startswith("Rock types are in the results")
    assert not tab.run_all_button.isVisibleTo(tab)


def test_apply_while_enabled_says_to_run(qtbot, tab, monkeypatch):
    _fake_active(monkeypatch, rock=False)
    tab.enable_check.setChecked(True)
    _fit(qtbot, tab)
    tab.apply_button.click()
    assert tab.status_label.text() == (
        "Applied to the project. Rock typing is on. Run the analysis (or Run All Wells) "
        "to compute rock types.")
    assert tab.status_label.property("status") == "warning"
    assert tab.enable_hint.text().startswith("Rock typing is on. Run the analysis")


def test_run_all_button_emits_and_is_off_during_a_batch(qtbot, tab, monkeypatch):
    _fit_and_apply(qtbot, tab)
    _fake_active(monkeypatch, rock=False)
    tab.enable_check.setChecked(True)
    with qtbot.waitSignal(tab.run_all_requested, timeout=1000):
        tab.run_all_button.click()
    tab.set_batch_running(True)
    assert not tab.run_all_button.isEnabled()
    tab.set_batch_running(False)
    assert tab.run_all_button.isEnabled()


def test_guidance_update_is_cheap(qtbot, tab, counters, monkeypatch):
    _fit_and_apply(qtbot, tab)
    _fake_active(monkeypatch, rock=False)
    _reset(counters)
    tab.enable_check.setChecked(True)
    tab.model.parameters_changed.emit()
    assert counters["update"] == 0 and counters["table"] == 0 and counters["figure"] == 0


def test_main_window_run_all_button_calls_the_run_all_handler(qtbot, monkeypatch):
    from ui.main_window import MainWindow

    calls = []
    monkeypatch.setattr(MainWindow, "_on_run_all", lambda self: calls.append(1))
    w = MainWindow()
    qtbot.addWidget(w)
    w.rock_tab.run_all_requested.emit()
    assert calls == [1]

