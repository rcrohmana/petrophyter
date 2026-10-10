# tests/test_busy_state.py
"""Busy state while files load or a session restores; quit prompt while busy.

An analysis run is not a busy state: the batch runner gates Run per well and
New Project / Load Session cancel it (see test_batch_run.py).
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
import pytest
from PyQt6.QtWidgets import QMessageBox

from models.project import WellDataset
from ui.main_window import MainWindow

# Captured at import time, before the autouse fixture patches it out.
REAL_CONFIRM_QUIT = MainWindow._confirm_quit

LOAD_KEYS = (
    "new_project", "open_las", "open_tops", "open_core", "open_tops_multi",
    "open_core_multi", "load_session", "merge_las", "run_analysis", "run_all",
)
ALWAYS_ENABLED = ("save_session", "toggle_browser", "theme_light", "theme_dark",
                  "about", "user_guide", "params_window")


@pytest.fixture()
def window(qtbot, monkeypatch):
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
    qtbot.addWidget(w, before_close_func=lambda w: w._set_busy(None))
    w.message_calls = calls
    return w


def _load_well(window):
    ds = WellDataset(key="WELL:A", display_name="A")
    ds.las_data = pd.DataFrame({"DEPTH": [100.0, 101.0], "GR": [50.0, 60.0]})
    ds.curve_mapping = {"GR": "GR"}
    window.model.add_well(ds)
    window._refresh_action_states()


def _assert_busy(window, keys, tip):
    for key in keys:
        action = window.actions_[key]
        assert not action.isEnabled(), key
        assert action.statusTip() == tip, key
    for key in ALWAYS_ENABLED:
        assert window.actions_[key].isEnabled(), key


def _assert_idle(window, tips):
    for key in ("new_project", "open_las", "open_tops", "open_core", "load_session",
                "merge_las", "run_analysis", "run_all", "open_tops_multi", "open_core_multi"):
        assert window.actions_[key].isEnabled(), key
    for key, tip in tips.items():
        assert window.actions_[key].statusTip() == tip, key
    assert window._busy is None


def test_load_disables_actions_and_idle_restores_gating(window):
    _load_well(window)
    tips = {key: window.actions_[key].statusTip() for key in LOAD_KEYS}
    _assert_idle(window, tips)

    window._set_busy("load")
    _assert_busy(window, LOAD_KEYS, "Unavailable while files are loading")
    assert not window.run_button.isEnabled()

    # Normal gating refreshes must not re-enable anything while busy.
    window._refresh_action_states()
    window._refresh_run_action()
    window._refresh_import_actions()
    window.model.project.well_updated.emit("WELL:A")
    _assert_busy(window, LOAD_KEYS, "Unavailable while files are loading")

    window._set_busy(None)
    _assert_idle(window, tips)


def test_restore_keeps_new_project_and_load_session(window):
    _load_well(window)
    window._set_busy("restore")
    keys = tuple(k for k in LOAD_KEYS if k not in ("new_project", "load_session"))
    for key in keys + ("save_session",):
        assert not window.actions_[key].isEnabled(), key
        assert window.actions_[key].statusTip() == "Unavailable while a session is loading", key
    assert window.actions_["new_project"].isEnabled()
    assert window.actions_["load_session"].isEnabled()
    window._set_busy(None)
    assert window.actions_["run_analysis"].isEnabled()
    assert window.actions_["save_session"].isEnabled()


def test_switching_busy_kind_restores_the_original_tips(window):
    _load_well(window)
    tips = {key: window.actions_[key].statusTip() for key in LOAD_KEYS}
    window._set_busy("load")
    window._set_busy("restore")
    assert window.actions_["new_project"].statusTip() == tips["new_project"]
    window._set_busy(None)
    _assert_idle(window, tips)


def test_multi_file_load_is_busy_until_it_finishes(window, monkeypatch):
    started = []
    monkeypatch.setattr(window, "_load_pool", type("P", (), {"start": started.append})(),
                        raising=False)
    window._start_multi_load(["a.las", "b.las"])
    assert window._busy == "load"
    assert not window.actions_["open_las"].isEnabled()
    window._abort_load()
    assert window._busy is None
    assert window.actions_["open_las"].isEnabled()


def test_run_is_ignored_while_busy(window, monkeypatch):
    _load_well(window)
    runs = []
    monkeypatch.setattr(window.batch_runner, "run", lambda *a, **k: runs.append(a))
    window._set_busy("load")
    window._on_run_analysis()
    window._on_run_all()
    assert runs == []


def test_data_browser_cannot_trigger_disabled_action(window):
    _load_well(window)
    window._set_busy("load")
    opened = []
    window.actions_["open_las"].triggered.disconnect()
    window.actions_["open_las"].triggered.connect(lambda: opened.append(True))
    window.data_browser.action_requested.emit("open_las")
    assert opened == []
    window._set_busy(None)
    window.data_browser.action_requested.emit("open_las")
    assert opened == [True]


@pytest.mark.parametrize("kind, text", [
    ("analysis", "Analysis is still running. Quit anyway?"),
    ("load", "Files are still loading. Quit anyway?"),
    ("restore", "A session is still loading. Quit anyway?"),
])
@pytest.mark.parametrize("answer", [QMessageBox.StandardButton.Yes,
                                    QMessageBox.StandardButton.No])
def test_close_while_busy_asks_for_confirmation(window, monkeypatch, kind, text, answer):
    monkeypatch.setattr(MainWindow, "_confirm_quit", REAL_CONFIRM_QUIT)
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a[2]) or answer)
    cancelled = []
    monkeypatch.setattr(window.batch_runner, "cancel", lambda: cancelled.append(True))
    if kind == "analysis":
        monkeypatch.setattr(window.batch_runner, "is_running", lambda: True)
    else:
        window._set_busy(kind)

    # The real close path: QWidget.close() returns whether the event was accepted.
    accepted = window.close()

    assert asked == [text]
    if answer == QMessageBox.StandardButton.Yes:
        assert accepted
        assert cancelled == [True]
    else:
        assert not accepted
        assert cancelled == []
        if kind != "analysis":
            assert window._busy == kind
    monkeypatch.setattr(window.batch_runner, "is_running", lambda: False)


def test_close_when_idle_does_not_ask(window, monkeypatch):
    monkeypatch.setattr(MainWindow, "_confirm_quit", REAL_CONFIRM_QUIT)
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a))
    assert window.close()
    assert asked == []
