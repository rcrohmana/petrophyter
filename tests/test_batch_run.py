"""Batch analysis: BatchRunner, per-well delivery, hash-based stale flags (spec §5.4-5.5)."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading

import pytest
from PyQt6.QtWidgets import QMessageBox

import services.analysis_service as svc
from models.app_model import AppModel
from models.project import WellDataset
from services.analysis_service import BatchRunner, WellSnapshot, snapshot_well
from tests.golden.cases import FULL_MAPPING, fixture_frame, make_tops
from ui.main_window import MainWindow

KEYS = ["WELL:A", "WELL:B", "WELL:C"]


def _well(key, data=None, name=None):
    ds = WellDataset(key, name or key.split(":")[1])
    ds.las_data = fixture_frame("sample_log_data") if data is None else data
    ds.curve_mapping = dict(FULL_MAPPING)
    return ds


def _model(keys=KEYS):
    model = AppModel()
    for key in keys:
        model.project.add_well(_well(key))
    return model


def _run(qtbot, runner, model, **kwargs):
    """Run a batch and return (report, completed keys, failed dict)."""
    done, failed = [], {}
    runner.well_completed.connect(lambda k, r, s, h: done.append(k))
    runner.well_failed.connect(lambda k, m: failed.__setitem__(k, m))
    with qtbot.waitSignal(runner.finished, timeout=60000) as blocker:
        runner.run(model, **kwargs)
    return blocker.args[0], done, failed


@pytest.fixture
def runner(qtbot):
    r = BatchRunner()
    yield r
    r.cancel()


def _apply(model, runner):
    """Mimic the window: store each delivery on its well."""
    def store(key, results, summary, params_hash):
        ds = model.project.get(key)
        ds.results, ds.summary, ds.calculated = results, summary, True
        ds.run_params_hash = params_hash

    runner.well_completed.connect(store)


# ---- BatchRunner -------------------------------------------------------------------

def test_snapshot_is_detached_and_keyed():
    model = _model(["WELL:A"])
    ds = model.project.get("WELL:A")
    snap = snapshot_well(model, ds)
    assert isinstance(snap, WellSnapshot)
    assert snap.key == "WELL:A" and snap.display_name == "A"
    assert snap.data is not ds.las_data and snap.data.equals(ds.las_data)
    assert snap.params_hash == model.well_params_hash(ds)
    assert snap.curve_mapping == FULL_MAPPING


def test_three_wells_run_with_keyed_completions(qtbot, runner):
    model = _model()
    started, progress = [], []
    runner.started.connect(started.append)
    runner.progress.connect(lambda d, t: progress.append((d, t)))
    report, done, failed = _run(qtbot, runner, model)
    assert started == [3]
    assert sorted(done) == sorted(KEYS) and not failed
    assert sorted(report["ok"]) == sorted(KEYS)
    assert report["failed"] == {} and report["skipped"] == [] and not report["cancelled"]
    assert progress[-1] == (3, 3)
    assert not runner.is_running()


def test_unchanged_wells_are_skipped_and_force_reruns(qtbot, runner):
    model = _model()
    _apply(model, runner)
    _run(qtbot, runner, model)
    report, done, _ = _run(qtbot, runner, model)
    assert done == [] and sorted(report["skipped"]) == sorted(KEYS) and report["ok"] == []
    report, done, _ = _run(qtbot, runner, model, force=True)
    assert sorted(done) == sorted(KEYS) and report["skipped"] == []
    # Changing a parameter makes the wells run again.
    model.rw = 0.2
    report, done, _ = _run(qtbot, runner, model)
    assert sorted(done) == sorted(KEYS)


def test_only_selected_keys_run(qtbot, runner):
    model = _model()
    report, done, _ = _run(qtbot, runner, model, keys=["WELL:B", "WELL:NOPE"])
    assert done == ["WELL:B"] and report["ok"] == ["WELL:B"]


def test_failing_well_is_reported_while_others_succeed(qtbot, runner):
    model = _model(["WELL:A", "WELL:C"])
    bad = _well("WELL:BAD", data=fixture_frame("sample_log_data").drop(columns=["DEPTH"]))
    model.project.add_well(bad, activate=False)
    report, done, failed = _run(qtbot, runner, model)
    assert sorted(report["ok"]) == ["WELL:A", "WELL:C"]
    assert list(report["failed"]) == ["WELL:BAD"] and report["failed"]["WELL:BAD"]
    assert list(failed) == ["WELL:BAD"]


def test_cancel_drops_late_results(qtbot, runner, monkeypatch):
    model = _model(["WELL:A"])
    gate = threading.Event()
    real = svc.run_pipeline
    monkeypatch.setattr(svc, "run_pipeline", lambda *a, **k: (gate.wait(10), real(*a, **k))[1])
    delivered, finished = [], []
    runner.well_completed.connect(lambda *a: delivered.append(a))
    runner.finished.connect(finished.append)
    runner.run(model)
    assert runner.is_running() and runner.is_pending("WELL:A")
    generation = runner.generation
    runner.cancel()
    assert runner.generation > generation and not runner.is_running()
    assert finished[-1]["cancelled"] is True
    gate.set()
    qtbot.wait(800)
    assert delivered == [] and len(finished) == 1
    # A stale-generation callback is ignored even if it arrives directly.
    runner._on_done(generation, "WELL:A", None, {})
    assert delivered == []


def test_new_run_supersedes_the_running_one(qtbot, runner, monkeypatch):
    model = _model(["WELL:A"])
    gate = threading.Event()
    real = svc.run_pipeline
    calls = []

    def slow(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            gate.wait(10)
        return real(*a, **k)

    monkeypatch.setattr(svc, "run_pipeline", slow)
    delivered = []
    runner.well_completed.connect(lambda *a: delivered.append(a))
    reports = []
    runner.finished.connect(reports.append)
    runner.run(model)
    runner.run(model, force=True)
    qtbot.waitUntil(lambda: len(reports) == 2 and bool(delivered), timeout=60000)
    gate.set()
    qtbot.wait(500)
    assert [r["cancelled"] for r in reports] == [True, False]
    assert len(delivered) == 1


def test_result_for_a_replaced_or_removed_well_is_dropped(qtbot, runner, monkeypatch):
    model = _model(["WELL:A", "WELL:B"])
    gate = threading.Event()
    real = svc.run_pipeline
    monkeypatch.setattr(svc, "run_pipeline", lambda *a, **k: (gate.wait(10), real(*a, **k))[1])
    delivered = []
    runner.well_completed.connect(lambda k, *a: delivered.append(k))
    with qtbot.waitSignal(runner.finished, timeout=60000, raising=False) as blocker:
        runner.run(model)
        model.project.remove_well("WELL:A")
        model.project.add_well(_well("WELL:B"))  # same key, new dataset
        gate.set()
    assert blocker.signal_triggered
    assert delivered == []


# ---- main window ------------------------------------------------------------------------

@pytest.fixture
def window(qtbot):
    widget = MainWindow()
    qtbot.addWidget(widget)
    yield widget
    widget.close()


@pytest.fixture
def two_wells(window):
    for key in ("WELL:A", "WELL:B"):
        window.model.project.add_well(_well(key))
    window.model.set_active_well("WELL:A")
    return window


def _finish(window, qtbot):
    qtbot.waitUntil(lambda: not window.batch_runner.is_running(), timeout=60000)
    qtbot.wait(50)


def test_run_all_runs_every_well_and_skips_unchanged(two_wells, qtbot):
    window = two_wells
    a, b = (window.model.project.get(k) for k in ("WELL:A", "WELL:B"))
    window.actions_["run_all"].trigger()
    _finish(window, qtbot)
    assert a.status == "run_ok" and b.status == "run_ok"
    assert window.model.results is a.results
    assert "2 wells" in window.statusBar.currentMessage()
    window.actions_["run_all"].trigger()
    assert window.statusBar.currentMessage() == "All wells are up to date"
    assert window.actions_["run_all"].shortcut().toString() == "Ctrl+Shift+R"


def test_run_analysis_runs_only_the_active_well(two_wells, qtbot):
    window = two_wells
    window.model.set_active_well("WELL:B")
    window.actions_["run_analysis"].trigger()
    _finish(window, qtbot)
    a, b = (window.model.project.get(k) for k in ("WELL:A", "WELL:B"))
    assert b.status == "run_ok" and a.status == "loaded"


def test_results_go_to_their_well_after_switching_active_well(two_wells, qtbot, monkeypatch):
    window = two_wells
    gate = threading.Event()
    real = svc.run_pipeline
    monkeypatch.setattr(svc, "run_pipeline", lambda *a, **k: (gate.wait(10), real(*a, **k))[1])
    window._on_run_analysis()  # A
    assert not window.actions_["run_analysis"].isEnabled()
    window.model.set_active_well("WELL:B")
    assert window.actions_["run_analysis"].isEnabled()  # B is not running
    gate.set()
    _finish(window, qtbot)
    a, b = (window.model.project.get(k) for k in ("WELL:A", "WELL:B"))
    assert a.status == "run_ok" and b.results is None
    assert window.model.results is None
    window.model.set_active_well("WELL:A")
    assert window.model.results is a.results


def test_new_project_during_a_run_drops_results(two_wells, qtbot, monkeypatch):
    window = two_wells
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    gate = threading.Event()
    real = svc.run_pipeline
    monkeypatch.setattr(svc, "run_pipeline", lambda *a, **k: (gate.wait(10), real(*a, **k))[1])
    window._on_run_all()
    assert window.batch_runner.is_running()
    window._on_new_project()
    gate.set()
    qtbot.wait(800)
    assert len(window.model.project) == 0
    assert not window.batch_runner.is_running()
    assert window.model.results is None


def test_project_parameter_change_marks_every_analysed_well_stale(two_wells, qtbot):
    window = two_wells
    window._on_run_all()
    _finish(window, qtbot)
    a, b = (window.model.project.get(k) for k in ("WELL:A", "WELL:B"))
    assert not a.stale and not b.stale
    updated = []
    window.model.project.well_updated.connect(updated.append)
    window.model.rw = 0.5
    window.params_window.parameters_updated.emit()
    assert a.stale and b.stale and a.status == "stale"
    assert sorted(updated) == ["WELL:A", "WELL:B"]
    assert not window.stale_label.isHidden()


def test_well_scope_entry_marks_only_that_well(two_wells, qtbot):
    window = two_wells
    window._on_run_all()
    _finish(window, qtbot)
    a, b = (window.model.project.get(k) for k in ("WELL:A", "WELL:B"))
    window.model.set_entry("m", "manual", 1.9, scope="well", well=window.model.project.get("WELL:B"))
    assert b.stale and not a.stale
    assert window.stale_label.isHidden()  # A is active
    window.model.set_active_well("WELL:B")
    assert not window.stale_label.isHidden()
    # Re-running clears it.
    window._on_run_analysis()
    _finish(window, qtbot)
    assert not b.stale and b.status == "run_ok"


def test_failures_are_reported_once_in_a_banner(two_wells, qtbot, monkeypatch):
    window = two_wells
    window.model.project.add_well(_well("WELL:C"))
    for key in ("WELL:A", "WELL:B"):
        window.model.project.get(key).las_data = (
            fixture_frame("sample_log_data").drop(columns=["DEPTH"])
        )
    modal = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: modal.append(a))
    banners = []
    original = window.show_banner
    monkeypatch.setattr(window, "show_banner", lambda kind, text: (banners.append((kind, text)), original(kind, text)))
    window._on_run_all()
    _finish(window, qtbot)
    assert modal == []
    assert len(banners) == 1
    kind, text = banners[0]
    assert kind == "warning" and text.startswith("2 wells failed: ")
    assert "A (" in text and "B (" in text
    assert window.model.project.get("WELL:A").status == "error"
    assert window.model.project.get("WELL:C").status == "run_ok"


def test_single_well_failure_keeps_the_error_dialog(two_wells, qtbot, monkeypatch):
    window = two_wells
    window.model.active_well.las_data = fixture_frame("sample_log_data").drop(columns=["DEPTH"])
    modal = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: modal.append(a))
    window._on_run_analysis()
    _finish(window, qtbot)
    assert len(modal) == 1 and window.model.active_well.status == "error"


def test_tops_change_marks_the_active_well_stale(two_wells, qtbot):
    window = two_wells
    window._on_run_all()
    _finish(window, qtbot)
    window.model.formation_tops = make_tops()
    a, b = (window.model.project.get(k) for k in ("WELL:A", "WELL:B"))
    assert a.stale and not b.stale
