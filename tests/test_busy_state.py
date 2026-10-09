# tests/test_busy_state.py
"""F1: busy state while an analysis or a LAS merge is running."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox

from ui.main_window import MainWindow

BUSY_KEYS = (
    "new_project", "open_las", "open_tops", "open_core",
    "load_session", "merge_las", "run_analysis",
)
ALWAYS_ENABLED = ("save_session", "toggle_browser", "theme_light", "theme_dark",
                  "about", "user_guide", "params_window")


@pytest.fixture()
def window(qtbot, monkeypatch):
    # No modal may block: every QMessageBox entry point answers immediately.
    calls = []

    def record(kind, answer):
        def fake(*args, **kwargs):
            calls.append((kind, args[2] if len(args) > 2 else None))
            return answer
        return fake

    monkeypatch.setattr(QMessageBox, "critical", record("critical", QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "warning", record("warning", QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "question", record("question", QMessageBox.StandardButton.Yes))
    w = MainWindow()
    # Never reach the real quit prompt when pytest-qt closes the window.
    qtbot.addWidget(w, before_close_func=lambda w: w._set_busy(None))
    w.message_calls = calls
    monkeypatch.setattr(w, "_sync_model_from_ui", lambda: None)
    return w


def _load_data(window):
    window.model._las_data = pd.DataFrame({"DEPTH": [100.0, 101.0], "GR": [50.0, 60.0]})
    window._refresh_action_states()


def _start_run(window, monkeypatch):
    runs = []
    monkeypatch.setattr(window.analysis_service, "run_analysis",
                        lambda model, generation=0: runs.append(generation))
    window._on_run_analysis()
    window.analysis_service.started.emit(runs[-1])
    return runs[-1]


def _complete(window, gen):
    # MainWindow connects `completed` with a QueuedConnection.
    window.analysis_service.completed.emit(*_results(), gen)
    QApplication.processEvents()


def _results():
    return (pd.DataFrame({"DEPTH": [100.0, 101.0], "PHIE": [0.2, 0.21]}),
            {"net_pay": 1.0, "gross_sand": 2.0, "ng_pay": 0.5})


def _assert_busy(window, kind):
    for key in BUSY_KEYS:
        action = window.actions_[key]
        assert not action.isEnabled(), key
        assert action.statusTip() == f"Unavailable while {kind} is running", key
    for key in ALWAYS_ENABLED:
        assert window.actions_[key].isEnabled(), key


def _assert_idle(window, run_enabled, merge_enabled):
    for key in ("new_project", "open_las", "open_tops", "open_core", "load_session"):
        assert window.actions_[key].isEnabled(), key
    assert window.actions_["run_analysis"].isEnabled() is run_enabled
    assert window.actions_["merge_las"].isEnabled() is merge_enabled
    for key in BUSY_KEYS:
        assert window.actions_[key].statusTip() == "", key
    assert window._busy is None


def test_analysis_disables_actions_and_completion_restores_gating(window, monkeypatch):
    _load_data(window)
    _assert_idle(window, run_enabled=True, merge_enabled=False)
    gen = _start_run(window, monkeypatch)
    _assert_busy(window, "analysis")
    assert window.run_button.isEnabled() is False
    assert window.statusBar.currentMessage() == "Analysis running…"

    _complete(window, gen)

    _assert_idle(window, run_enabled=True, merge_enabled=False)
    assert window.model.calculated


def test_analysis_error_restores_gating(window, monkeypatch):
    _load_data(window)
    gen = _start_run(window, monkeypatch)
    window.analysis_service.error.emit("boom", gen)
    _assert_idle(window, run_enabled=True, merge_enabled=False)
    assert ("critical", "boom") in window.message_calls


def test_run_is_ignored_while_busy(window, monkeypatch):
    _load_data(window)
    _start_run(window, monkeypatch)
    calls = []
    monkeypatch.setattr(window.analysis_service, "run_analysis",
                        lambda *a, **k: calls.append(a))
    window._on_run_analysis()
    assert calls == []


def _start_merge(window, monkeypatch):
    window._loaded_parsers = [object(), object()]
    window._loaded_file_names = ["a.las", "b.las"]
    window._merge_pending = True
    window._refresh_action_states()
    monkeypatch.setattr(window.merge_service, "merge_files", lambda *args: None)
    window._on_merge_requested()
    window.merge_service.started.emit()


def test_merge_disables_actions_and_completion_restores_gating(window, monkeypatch):
    _start_merge(window, monkeypatch)
    _assert_busy(window, "merge")
    assert window.statusBar.currentMessage() == "Merging…"

    # Completion runs the real handler; keep its data work out of the test.
    monkeypatch.setattr(window, "_on_data_loaded", lambda: None)

    class _Parser:
        well_info = {}
        data = None

        def get_available_curves(self):
            return ["GR"]

        def find_curve_by_type(self, ctype):
            return "GR" if ctype == "GR" else None

    class _Report:
        well_name = "W-1"

    window._loaded_parsers = [_Parser(), _Parser()]
    window._loaded_row_counts = [2, 2]
    merged = pd.DataFrame({"DEPTH": [100.0, 101.0], "GR": [50.0, 60.0]})
    window.merge_service.completed.emit(merged, _Report())

    _assert_idle(window, run_enabled=True, merge_enabled=False)


def test_merge_error_restores_gating(window, monkeypatch):
    _start_merge(window, monkeypatch)
    window.merge_service.error.emit("merge broke")
    # Files are still pending, so Merge LAS comes back; no data, so no Run.
    _assert_idle(window, run_enabled=False, merge_enabled=True)
    assert ("critical", "merge broke") in window.message_calls


def test_data_browser_cannot_trigger_disabled_action(window, monkeypatch):
    _load_data(window)
    _start_run(window, monkeypatch)
    opened = []
    monkeypatch.setattr(window, "_open_las_dialog", lambda: opened.append(True))
    window.actions_["open_las"].triggered.disconnect()
    window.actions_["open_las"].triggered.connect(lambda: opened.append(True))
    window.data_browser.action_requested.emit("open_las")
    assert opened == []


def test_stale_generation_result_is_dropped(window, monkeypatch):
    _load_data(window)
    gen = _start_run(window, monkeypatch)
    assert gen == 1
    window._on_new_project()  # programmatic call mid-run bumps the generation
    assert window._analysis_gen == 2
    _assert_idle(window, run_enabled=False, merge_enabled=False)

    refreshed = []
    monkeypatch.setattr(window, "_update_all_tabs", lambda: refreshed.append(True))
    window.analysis_service.progress.emit("late", 50, gen)
    _complete(window, gen)

    assert refreshed == []
    assert window.model.results is None
    assert not window.model.calculated
    assert not window.qc_chip.isVisibleTo(window)
    assert not window.banner.isVisibleTo(window)
    assert not window.status_progress.isVisibleTo(window)
    assert window.statusBar.currentMessage() == "Ready. Load a LAS file to begin."

    window.analysis_service.error.emit("late error", gen)
    assert ("critical", "late error") not in window.message_calls


def test_params_changed_while_running_marks_results_stale(window, monkeypatch):
    _load_data(window)
    gen = _start_run(window, monkeypatch)
    window.params_window.parameters_updated.emit()
    assert not window.stale_label.isVisibleTo(window)  # nothing to mark yet

    _complete(window, gen)

    assert window.model.calculated
    assert window.stale_label.isVisibleTo(window)
    assert window.data_browser._results_stale


def test_no_stale_after_clean_run(window, monkeypatch):
    _load_data(window)
    gen = _start_run(window, monkeypatch)
    _complete(window, gen)
    assert not window.stale_label.isVisibleTo(window)


@pytest.mark.parametrize("kind, text", [
    ("analysis", "Analysis is still running. Quit anyway?"),
    ("merge", "A merge is still running. Quit anyway?"),
])
@pytest.mark.parametrize("answer", [QMessageBox.StandardButton.Yes,
                                    QMessageBox.StandardButton.No])
def test_close_while_busy_asks_for_confirmation(window, monkeypatch, kind, text, answer):
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a[2]) or answer)
    cancelled = []
    monkeypatch.setattr(window.analysis_service, "cancel", lambda: cancelled.append(True))
    window._set_busy(kind)
    gen = window._analysis_gen

    # The real close path: QWidget.close() returns whether the event was accepted.
    accepted = window.close()

    assert asked == [text]
    if answer == QMessageBox.StandardButton.Yes:
        assert accepted
        assert cancelled == [True]
        assert window._analysis_gen == gen + 1  # a late result is dropped
    else:
        assert not accepted
        assert cancelled == []
        assert window._busy == kind


def test_close_when_idle_does_not_ask(window, monkeypatch):
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a))
    assert window.close()
    assert asked == []
