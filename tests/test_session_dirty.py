"""Save protection (P0-UI/UX U4): dirty state, window title, Save / Save As, the unsaved-changes prompt."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from models.app_model import AppModel
from tests.test_session_v2 import _write
from ui.main_window import MainWindow

TIMEOUT = 15000


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A modal box would block the offscreen test run; fail loudly instead."""

    def refuse(*args, **kwargs):
        raise AssertionError(f"unexpected dialog: {args[1:3]}")

    for name in ("warning", "critical", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(refuse))


@pytest.fixture
def window(qtbot):
    widget = MainWindow()
    qtbot.addWidget(widget)
    yield widget
    widget._cancel_restore()
    if widget._restore_pool is not None:
        assert widget._restore_pool.waitForDone(5000)
    widget.close()


@pytest.fixture
def loaded(window, tmp_path):
    """A window with one well loaded; the model is dirty."""
    window._load_single_las(_write(tmp_path, "a.las", well="BKS-01"))
    return window


def patch_save_dialog(monkeypatch, path, calls=None):
    def dialog(*args, **kwargs):
        if calls is not None:
            calls.append(1)
        return (path, "")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(dialog))


def patch_prompt(monkeypatch, window, answer):
    asked = []

    def ask(self, action):
        asked.append(action)
        return answer

    monkeypatch.setattr(MainWindow, "_confirm_discard", ask)
    return asked


# ---- the model ----
def test_a_fresh_model_is_clean_and_unsaved():
    model = AppModel()
    assert model.dirty is False
    assert model.session_path is None


def test_mark_dirty_and_clean_emit_once(qtbot):
    model = AppModel()
    seen = []
    model.dirty_changed.connect(seen.append)
    model.mark_dirty()
    model.mark_dirty()
    model.mark_clean()
    model.mark_clean()
    assert seen == [True, False]


# ---- what makes it dirty ----
@pytest.mark.parametrize("signal", [
    "data_loaded", "merge_complete", "core_data_loaded", "formation_tops_loaded",
    "parameters_changed",
])
def test_model_signals_set_dirty(window, signal):
    assert not window.model.dirty
    getattr(window.model, signal).emit()
    assert window.model.dirty


def test_scoped_params_changed_sets_dirty(window):
    window.model.scoped_params_changed.emit("")
    assert window.model.dirty


@pytest.mark.parametrize("signal,args", [("wells_changed", ()), ("tops_changed", ([],))])
def test_project_signals_set_dirty(window, signal, args):
    getattr(window.model.project, signal).emit(*args)
    assert window.model.dirty


@pytest.mark.parametrize("signal,args", [
    ("analysis_complete", ()), ("scope_changed", ()),
])
def test_model_signals_that_are_not_content_do_not(window, signal, args):
    getattr(window.model, signal).emit(*args)
    assert not window.model.dirty


def test_results_stale_flags_and_errors_do_not(loaded):
    model = loaded.model
    model.mark_clean()
    key = model.project.active_key
    ds = model.project.get(key)
    project = model.project
    project.well_updated.emit(key)                     # a run finished, went stale or failed
    project.active_well_changed.emit(key)
    ds.error = "boom"
    project.well_updated.emit(key)
    assert not model.dirty
    loaded._recompute_stale()
    assert not model.dirty


def test_curve_mapping_edit_sets_dirty(loaded):
    loaded.model.mark_clean()
    loaded.model.set_curve_mapping("GR", "None")
    assert loaded.model.dirty


def test_loading_a_file_sets_dirty(loaded):
    assert loaded.model.dirty
    assert loaded.windowTitle().startswith("*")


def test_programmatic_widget_refresh_does_not(loaded):
    loaded.model.mark_clean()
    loaded._refresh_active_well_ui()
    loaded._update_ui_from_model()
    assert not loaded.model.dirty


def test_parameter_signal_is_ignored_while_restoring(window):
    window._restoring = True
    window.model.parameters_changed.emit()
    window._restoring = False
    assert not window.model.dirty


# ---- title ----
def test_title_shows_the_star_only_when_dirty(window):
    assert window.windowTitle() == "Petrophyter"
    window.model.mark_dirty()
    assert window.windowTitle() == "*Petrophyter"
    window.model.mark_clean()
    assert window.windowTitle() == "Petrophyter"


def test_title_keeps_the_well_name(loaded):
    assert loaded.windowTitle() == "*BKS-01 — Petrophyter"
    loaded.model.mark_clean()
    assert loaded.windowTitle() == "BKS-01 — Petrophyter"


# ---- Save and Save As ----
def test_save_as_action_exists_with_its_shortcut(window):
    assert window.actions_["save_session_as"].shortcut().toString() == "Ctrl+Shift+S"
    assert window.actions_["save_session"].shortcut().toString() == "Ctrl+S"


def test_first_save_asks_for_a_file_then_clears_dirty(loaded, tmp_path, monkeypatch):
    path = str(tmp_path / "one.json")
    calls = []
    patch_save_dialog(monkeypatch, path, calls)
    loaded._on_save_session()
    assert calls == [1]
    assert os.path.exists(path)
    assert loaded.model.session_path == path
    assert not loaded.model.dirty
    assert not loaded.windowTitle().startswith("*")


def test_second_save_writes_without_a_dialog(loaded, tmp_path, monkeypatch):
    path = str(tmp_path / "one.json")
    patch_save_dialog(monkeypatch, path)
    loaded._on_save_session()
    os.remove(path)
    calls = []
    patch_save_dialog(monkeypatch, str(tmp_path / "other.json"), calls)
    loaded.model.mark_dirty()
    loaded._on_save_session()
    assert calls == []
    assert os.path.exists(path)
    assert not loaded.model.dirty


def test_save_as_always_asks_and_switches_the_file(loaded, tmp_path, monkeypatch):
    patch_save_dialog(monkeypatch, str(tmp_path / "one.json"))
    loaded._on_save_session()
    other = str(tmp_path / "other.json")
    calls = []
    patch_save_dialog(monkeypatch, other, calls)
    loaded._on_save_session_as()
    assert calls == [1]
    assert loaded.model.session_path == other
    assert os.path.exists(other)


def test_cancelled_save_dialog_keeps_the_model_dirty(loaded, monkeypatch):
    patch_save_dialog(monkeypatch, "")
    loaded._on_save_session()
    assert loaded.model.dirty
    assert loaded.model.session_path is None


# ---- load clears it ----
def test_load_session_clears_dirty_and_sets_the_path(window, tmp_path, monkeypatch, qtbot):
    window._load_single_las(_write(tmp_path, "a.las", well="BKS-01"))
    path = str(tmp_path / "s.json")
    assert window.session_service.save_session(window.model, path)
    window.model.reset()
    window.model.mark_clean()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (path, "")))
    window._on_load_session()
    qtbot.waitUntil(lambda: window._restore_worker is None, timeout=TIMEOUT)
    assert [ds.display_name for ds in window.model.project.wells] == ["BKS-01"]
    assert not window.model.dirty
    assert window.model.session_path == path
    assert not window.windowTitle().startswith("*")


def test_parameter_only_v1_session_leaves_the_project_unsaved(loaded, tmp_path, monkeypatch):
    # A 1.x file holds parameters only; the open well stays, so the project is not the
    # file, and Ctrl+S must ask for a file instead of overwriting it in 2.x format.
    import json

    path = tmp_path / "old.json"
    path.write_text(json.dumps({"_session_version": "1.4", "rw": 0.1}), encoding="utf-8")
    loaded.model.mark_clean()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(path), "")))
    loaded._on_load_session()
    assert [ds.display_name for ds in loaded.model.project.wells] == ["BKS-01"]
    assert loaded.model.dirty
    assert loaded.model.session_path is None


def test_new_project_clears_dirty_and_the_path(loaded, tmp_path, monkeypatch):
    patch_save_dialog(monkeypatch, str(tmp_path / "one.json"))
    loaded._on_save_session()
    loaded.model.mark_dirty()
    patch_prompt(monkeypatch, loaded, True)
    loaded._on_new_project()
    assert len(loaded.model.project) == 0
    assert not loaded.model.dirty
    assert loaded.model.session_path is None


# ---- the prompt ----
def ask_with(monkeypatch, reply):
    """Patch QMessageBox.question to answer ``reply``; returns the list of (title, text)."""
    asked = []

    def question(parent, title, text, buttons=None, default=None):
        asked.append((title, text))
        return reply

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    return asked


@pytest.fixture
def real_confirm(monkeypatch):
    """The real ``_confirm_discard`` (the autouse fixture returns True)."""
    monkeypatch.setattr(MainWindow, "_confirm_discard", _REAL_CONFIRM_DISCARD)


_REAL_CONFIRM_DISCARD = MainWindow._confirm_discard


def test_clean_model_is_not_asked(window, real_confirm):
    assert window._confirm_discard("close") is True


def test_prompt_discard_lets_the_action_go(loaded, real_confirm, monkeypatch):
    asked = ask_with(monkeypatch, QMessageBox.StandardButton.Discard)
    assert loaded._confirm_discard("close") is True
    assert len(asked) == 1
    assert loaded.model.dirty


def test_prompt_cancel_stops_the_action(loaded, real_confirm, monkeypatch):
    ask_with(monkeypatch, QMessageBox.StandardButton.Cancel)
    assert loaded._confirm_discard("close") is False


def test_prompt_save_saves_then_goes_on(loaded, real_confirm, tmp_path, monkeypatch):
    path = str(tmp_path / "one.json")
    ask_with(monkeypatch, QMessageBox.StandardButton.Save)
    patch_save_dialog(monkeypatch, path)
    assert loaded._confirm_discard("load") is True
    assert os.path.exists(path)
    assert not loaded.model.dirty


def test_prompt_save_cancelled_in_the_file_dialog_counts_as_cancel(loaded, real_confirm, monkeypatch):
    ask_with(monkeypatch, QMessageBox.StandardButton.Save)
    patch_save_dialog(monkeypatch, "")
    assert loaded._confirm_discard("close") is False
    assert loaded.model.dirty


def test_new_project_prompt_carries_the_clear_sentence_once(loaded, real_confirm, monkeypatch):
    asked = ask_with(monkeypatch, QMessageBox.StandardButton.Cancel)
    loaded._on_new_project()
    assert len(asked) == 1
    assert "All current data will be cleared" in asked[0][1]
    assert len(loaded.model.project) == 1


def test_close_on_a_dirty_model_prompts_and_cancel_keeps_the_window(loaded, monkeypatch):
    asked = patch_prompt(monkeypatch, loaded, False)
    assert loaded.close() is False
    assert asked == ["close"]
    assert loaded.isVisible() or len(loaded.model.project) == 1
    assert len(loaded.model.project) == 1


def test_load_session_on_a_dirty_model_prompts_and_cancel_keeps_the_data(loaded, tmp_path, monkeypatch):
    path = str(tmp_path / "s.json")
    assert loaded.session_service.save_session(loaded.model, path)
    asked = patch_prompt(monkeypatch, loaded, False)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (path, "")))
    loaded._on_load_session()
    assert asked == ["load"]
    assert loaded._restore_worker is None
    assert len(loaded.model.project) == 1
    assert loaded.model.dirty


def test_failed_load_does_not_prompt_or_touch_the_project(loaded, tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    asked = patch_prompt(monkeypatch, loaded, True)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(bad), "")))
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: shown.append(a[2])))
    loaded._on_load_session()
    assert asked == []
    assert shown
    assert len(loaded.model.project) == 1


def test_new_project_on_a_dirty_model_prompts_and_cancel_keeps_the_data(loaded, monkeypatch):
    asked = patch_prompt(monkeypatch, loaded, False)
    loaded._on_new_project()
    assert asked == ["new"]
    assert len(loaded.model.project) == 1
    assert loaded.model.dirty


def test_new_project_on_a_clean_model_with_data_keeps_the_old_question(loaded, monkeypatch):
    loaded.model.mark_clean()
    asked = ask_with(monkeypatch, QMessageBox.StandardButton.No)
    loaded._on_new_project()
    assert len(asked) == 1
    assert len(loaded.model.project) == 1
