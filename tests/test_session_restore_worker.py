"""Session restore on a worker thread (spec §10)."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QFileDialog

from services.restore_service import RestoreWorker
from services.session_service import RestoreCancelled, SessionService
from tests.test_multiwell_loading import _write
from ui.main_window import MainWindow

TIMEOUT = 15000


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A modal box would block the offscreen test run; fail loudly instead."""
    from PyQt6.QtWidgets import QMessageBox

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
        assert widget._restore_pool.waitForDone(5000)    # no worker outlives the test
    widget.close()


@pytest.fixture
def sessions(window, tmp_path):
    """Two session files: ``one`` (BKS-01) and ``two`` (BKS-01, BKS-02; BKS-02 active)."""
    window._load_single_las(_write(tmp_path, "a.las", well="BKS-01"))
    window._load_single_las(_write(tmp_path, "b.las", well="BKS-02"))
    two = tmp_path / "two.json"
    assert window.session_service.save_session(window.model, str(two))
    second = next(ds.key for ds in window.model.project.wells if ds.display_name == "BKS-02")
    window.model.project.remove_well(second)
    one = tmp_path / "one.json"
    assert window.session_service.save_session(window.model, str(one))
    window.model.reset()
    return {"one": str(one), "two": str(two)}


def load(window, monkeypatch, path):
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (path, "")))
    window._on_load_session()


def names(window):
    return [ds.display_name for ds in window.model.project.wells]


def idle(window):
    return window._restore_worker is None


def slow_builder(monkeypatch, gate, steps=None):
    """Replace the builder by one that waits on ``gate`` (polling ``cancelled``), then delegates."""
    original = SessionService.build_wells_from_session

    def slow(self, data, progress=None, cancelled=None, **kwargs):
        if progress:
            progress("Restoring 1 of 2: SLOW", 10)
        while not gate.wait(0.01):
            if cancelled is not None and cancelled():
                raise RestoreCancelled()
            if steps is not None:
                steps.append(1)
        return original(self, data, progress, cancelled, **kwargs)

    monkeypatch.setattr(SessionService, "build_wells_from_session", slow)


def test_the_builder_is_pure(sessions):
    # A fresh interpreter: no QApplication is ever created and no QObject is alive afterwards.
    code = (
        "import gc, json, sys\n"
        "from PyQt6.QtCore import QObject, QCoreApplication\n"
        "from services.session_service import SessionService\n"
        "data = json.load(open(sys.argv[1], encoding='utf-8'))\n"
        "before = sum(isinstance(o, QObject) for o in gc.get_objects())\n"
        "datasets, notes = SessionService().build_wells_from_session(data)\n"
        "gc.collect()\n"
        "after = sum(isinstance(o, QObject) for o in gc.get_objects())\n"
        "assert QCoreApplication.instance() is None\n"
        "assert after == before, (before, after)\n"
        "assert [d.display_name for d in datasets] == ['BKS-01', 'BKS-02'], datasets\n"
        "assert not any(isinstance(d, QObject) for d in datasets)\n"
        "print('pure')\n"
    )
    root = Path(__file__).resolve().parent.parent
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(root))
    result = subprocess.run([sys.executable, "-c", code, sessions["two"]], cwd=root, env=env,
                            capture_output=True, text=True, timeout=100)
    assert result.returncode == 0 and "pure" in result.stdout, result.stderr


def test_the_builder_stops_when_cancelled(sessions):
    import json

    data = json.loads(Path(sessions["two"]).read_text(encoding="utf-8"))
    with pytest.raises(RestoreCancelled):
        SessionService().build_wells_from_session(data, cancelled=lambda: True)


def test_worker_completion_installs_the_wells_once(window, sessions, monkeypatch, qtbot):
    window.model.reset()
    refreshes = []
    original = window._refresh_active_well_ui
    monkeypatch.setattr(window, "_refresh_active_well_ui",
                        lambda *a, **k: (refreshes.append(1), original(*a, **k))[1])
    start = window._start_restore          # the reset before it refreshes once, as it always did
    monkeypatch.setattr(window, "_start_restore",
                        lambda *a, **k: (refreshes.clear(), start(*a, **k))[1])
    load(window, monkeypatch, sessions["two"])
    qtbot.waitUntil(lambda: idle(window), timeout=TIMEOUT)
    assert names(window) == ["BKS-01", "BKS-02"]
    assert window.model.project.active.display_name == "BKS-02"
    assert not window._bulk_loading
    assert refreshes == [1]
    assert not any(ds.calculated for ds in window.model.project.wells)


def test_cancelled_restore_leaves_an_empty_project_and_no_banner(window, sessions, monkeypatch, qtbot):
    gate = threading.Event()
    slow_builder(monkeypatch, gate)
    load(window, monkeypatch, sessions["two"])
    assert not idle(window)
    worker = window._restore_worker
    window._on_new_project()
    assert idle(window) and worker.cancelled
    gate.set()                                    # a worker that missed the cancel must not land
    qtbot.waitUntil(lambda: not window._restore_retired, timeout=TIMEOUT)
    assert len(window.model.project) == 0
    assert not window.banner.isVisibleTo(window)
    assert window.actions_["open_las"].isEnabled()


def test_a_superseded_generation_is_dropped(window, sessions, monkeypatch, qtbot):
    gate_a, gate_b = threading.Event(), threading.Event()
    original = SessionService.build_wells_from_session

    def pick(self, data, progress=None, cancelled=None, **kwargs):
        gate = gate_a if len(data["wells"]) == 2 else gate_b
        while not gate.wait(0.01):
            if cancelled():
                raise RestoreCancelled()
        return original(self, data, progress, cancelled, **kwargs)

    monkeypatch.setattr(SessionService, "build_wells_from_session", pick)
    load(window, monkeypatch, sessions["two"])        # A: two wells
    first = window._restore_worker
    load(window, monkeypatch, sessions["one"])        # B: one well, supersedes A
    second = window._restore_worker
    assert first is not second and first.cancelled and second.generation > first.generation
    gate_a.set()
    gate_b.set()
    qtbot.waitUntil(lambda: idle(window) and not window._restore_retired, timeout=TIMEOUT)
    assert names(window) == ["BKS-01"]
    # Even a result that does arrive late from the old worker is ignored.
    window._on_restore_completed(first, [object()], ["stale"])
    assert names(window) == ["BKS-01"]


def test_the_ui_stays_responsive_during_a_restore(window, sessions, monkeypatch, qtbot):
    gate, ticks = threading.Event(), []
    slow_builder(monkeypatch, gate)
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start(10)
    try:
        load(window, monkeypatch, sessions["two"])
        qtbot.waitUntil(lambda: len(ticks) >= 5, timeout=TIMEOUT)    # the event loop kept running
        assert not idle(window)
        gate.set()
        qtbot.waitUntil(lambda: idle(window), timeout=TIMEOUT)
    finally:
        timer.stop()
    assert names(window) == ["BKS-01", "BKS-02"]


def test_actions_are_disabled_while_restoring(window, sessions, monkeypatch, qtbot):
    locked = ("open_las", "open_tops", "open_core", "open_tops_multi", "open_core_multi",
              "merge_las", "save_session", "run_analysis", "run_all")
    gate = threading.Event()
    slow_builder(monkeypatch, gate)
    load(window, monkeypatch, sessions["two"])
    qtbot.waitUntil(lambda: "Restoring 1 of 2" in window.statusBar.currentMessage(), timeout=TIMEOUT)
    assert not any(window.actions_[key].isEnabled() for key in locked)
    assert window.actions_["new_project"].isEnabled()
    assert window.actions_["load_session"].isEnabled()    # cancels and restarts
    window._refresh_run_action()                   # other refreshes must not re-enable Run
    window._refresh_import_actions()
    assert not window.actions_["run_all"].isEnabled()
    assert not window.actions_["open_tops_multi"].isEnabled()
    gate.set()
    qtbot.waitUntil(lambda: idle(window), timeout=TIMEOUT)
    for key in ("open_las", "open_tops", "open_core", "merge_las", "load_session", "save_session",
                "open_tops_multi", "open_core_multi", "run_analysis", "run_all"):
        assert window.actions_[key].isEnabled(), key


def test_a_failing_restore_shows_one_warning_and_an_empty_project(window, sessions, monkeypatch, qtbot):
    def boom(self, *args, **kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(SessionService, "build_wells_from_session", boom)
    load(window, monkeypatch, sessions["two"])
    qtbot.waitUntil(lambda: idle(window), timeout=TIMEOUT)
    assert len(window.model.project) == 0
    assert "disk on fire" in window.banner.message_label.text()
    assert window.actions_["load_session"].isEnabled()


def test_the_synchronous_wrapper_still_restores(sessions):
    import json
    from models.app_model import AppModel

    data = json.loads(Path(sessions["two"]).read_text(encoding="utf-8"))
    model = AppModel()
    svc = SessionService()
    svc.apply_session_to_model(model, data)
    assert svc.restore_wells(model, data) == []
    assert [ds.display_name for ds in model.project.wells] == ["BKS-01", "BKS-02"]
    assert model.project.active.display_name == "BKS-02"


def test_worker_signals_progress_and_completion(sessions, qtbot):
    import json

    data = json.loads(Path(sessions["two"]).read_text(encoding="utf-8"))
    worker = RestoreWorker(data, generation=3)
    messages = []
    worker.signals.progress.connect(lambda message, percent: messages.append(message))
    from PyQt6.QtCore import QThreadPool

    pool = QThreadPool()
    with qtbot.waitSignal(worker.signals.completed, timeout=TIMEOUT) as blocker:
        pool.start(worker)
    datasets, notes = blocker.args
    assert [d.display_name for d in datasets] == ["BKS-01", "BKS-02"] and notes == []
    assert messages[0] == "Restoring 1 of 2: BKS-01"
    assert pool.waitForDone(5000)
