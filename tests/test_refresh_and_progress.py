"""One UI refresh per load (spec follow-ups §11) and per-stage batch progress (§7)."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from models.project import WellDataset
from services.analysis_service import BatchRunner, _Relay
from tests.test_multiwell_loading import _parsed, _write
from ui.main_window import MainWindow


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
    widget.close()


class Counter:
    """Counts refresh work: tab redraws and Data Browser rebuilds caused by a refresh.

    Browser rebuilds are counted only while a refresh runs (``_finish_load`` or
    the window's ``_update_all_tabs``): the Data Browser rebuilds itself on
    ``active_well_changed``, so the window must not rebuild it a second time.
    """

    def __init__(self, window, monkeypatch):
        self.calls = {"summary": 0, "export": 0, "browser": 0, "all_tabs": 0}
        self._depth = 0
        self._patch(monkeypatch, window.summary_tab, "update_display", "summary")
        self._patch(monkeypatch, window.export_tab, "update_display", "export")
        self._patch(monkeypatch, window.data_browser, "rebuild", "browser", only_inside=True)
        self._patch(monkeypatch, window, "_update_all_tabs", "all_tabs", marks_inside=True)
        self._patch(monkeypatch, window, "_finish_load", None, marks_inside=True)

    def _patch(self, monkeypatch, obj, name, label, only_inside=False, marks_inside=False):
        real = getattr(obj, name)

        def counted(*args, **kwargs):
            if label and (not only_inside or self._depth):
                self.calls[label] += 1
            self._depth += marks_inside
            try:
                return real(*args, **kwargs)
            finally:
                self._depth -= marks_inside

        monkeypatch.setattr(obj, name, counted)


# ---- I: one refresh per load ---------------------------------------------------


def test_data_version_changes_whenever_data_is_replaced():
    import pandas as pd

    ds = WellDataset("K")
    seen = [ds.data_version]
    ds.las_data = pd.DataFrame({"DEPTH": [1.0]})
    seen.append(ds.data_version)
    ds.las_data = pd.DataFrame({"DEPTH": [1.0]})
    seen.append(ds.data_version)
    assert len(set(seen)) == 3 and seen == sorted(seen)
    # A different dataset never shares a version (a reload is a new object).
    other = WellDataset("K")
    other.las_data = pd.DataFrame({"DEPTH": [1.0]})
    assert other.data_version not in seen


def test_build_well_and_model_setter_bump_data_version(window, tmp_path):
    from services.load_service import build_well

    item = _parsed(tmp_path, "a.las", well="BKS-01")
    first, second = build_well([item]), build_well([item])
    assert first.data_version > 0 and first.data_version != second.data_version

    window._load_single_las(_write(tmp_path, "b.las", well="BKS-02"))
    ds = window.model.active_well
    before = ds.data_version
    window.model.las_data = ds.las_data.copy()
    assert ds.data_version != before


def test_single_load_refreshes_once(window, tmp_path, monkeypatch):
    counter = Counter(window, monkeypatch)
    window._load_single_las(_write(tmp_path, "a.las", well="BKS-01"))
    assert counter.calls == {"summary": 1, "export": 1, "browser": 1, "all_tabs": 1}
    ds = window.model.active_well
    assert window._refreshed_for == (ds.key, ds.data_version)


def test_bulk_load_of_three_wells_refreshes_once(window, tmp_path, monkeypatch):
    counter = Counter(window, monkeypatch)
    groups = [[_parsed(tmp_path, f"w{i}.las", well=f"BKS-0{i}")] for i in (1, 2, 3)]
    window._begin_load(groups)
    assert len(window.model.project) == 3
    assert counter.calls["all_tabs"] == 1
    assert counter.calls["summary"] == 1 and counter.calls["export"] == 1
    assert counter.calls["browser"] == 1


def test_data_loaded_is_ignored_during_a_bulk_load(window, tmp_path, monkeypatch):
    window._load_single_las(_write(tmp_path, "a.las", well="BKS-01"))
    counter = Counter(window, monkeypatch)
    window._bulk_loading = True
    window.model.las_data = window.model.las_data.copy()
    window._bulk_loading = False
    assert counter.calls["all_tabs"] == 0


def test_reload_of_the_active_well_still_refreshes(window, tmp_path, monkeypatch):
    path = _write(tmp_path, "a.las", well="BKS-01")
    window._load_single_las(path)
    old_version = window.model.active_well.data_version
    counter = Counter(window, monkeypatch)
    window._load_single_las(path)  # same key: the dataset is replaced
    assert len(window.model.project) == 1
    assert window.model.active_well.data_version != old_version
    assert counter.calls["all_tabs"] == 1 and counter.calls["summary"] == 1


def test_replacing_the_active_wells_data_refreshes_once(window, tmp_path, monkeypatch):
    window._load_single_las(_write(tmp_path, "a.las", well="BKS-01"))
    counter = Counter(window, monkeypatch)
    window.model.las_data = window.model.las_data.copy()
    assert counter.calls["all_tabs"] == 1 and counter.calls["summary"] == 1
    # The same data announced again does nothing.
    window._on_data_loaded()
    assert counter.calls["all_tabs"] == 1


def test_adding_an_active_well_through_the_model_refreshes_once(window, tmp_path, monkeypatch):
    from services.load_service import build_well

    counter = Counter(window, monkeypatch)
    window.model.add_well(build_well([_parsed(tmp_path, "a.las", well="BKS-01")]))
    assert counter.calls["all_tabs"] == 1


def test_new_project_still_resets(window, tmp_path, monkeypatch):
    window._load_single_las(_write(tmp_path, "a.las", well="BKS-01"))
    resets = []
    real = window._reset_ui
    monkeypatch.setattr(window, "_reset_ui", lambda: (resets.append(1), real())[1])
    window.model.reset()
    assert resets and window.model.active_well is None
    assert window._refreshed_for is None


# ---- E: BatchRunner relays stage progress --------------------------------------


def test_relay_forwards_progress_with_the_well_key(qtbot):
    runner = BatchRunner()
    runner._generation = 3
    runner._pending = {"WELL:A": object()}
    got = []
    runner.well_progress.connect(lambda *args: got.append(args))
    _Relay(runner, 3, "WELL:A").on_progress("Calculating porosity...", 40)
    assert got == [("WELL:A", "Calculating porosity...", 40)]


def test_relay_drops_stale_generations_and_finished_wells(qtbot):
    runner = BatchRunner()
    runner._generation = 3
    runner._pending = {"WELL:A": object()}
    got = []
    runner.well_progress.connect(lambda *args: got.append(args))
    _Relay(runner, 2, "WELL:A").on_progress("old run", 10)      # superseded run
    _Relay(runner, 3, "WELL:B").on_progress("not pending", 10)  # finished / unknown
    assert got == []


def test_real_run_reports_stage_progress(window, tmp_path, qtbot):
    window._load_single_las(_write(tmp_path, "a.las", well="BKS-01"))
    key = window.model.active_well.key
    got = []
    window.batch_runner.well_progress.connect(lambda *args: got.append(args))
    window._on_run_analysis()
    qtbot.waitUntil(lambda: not window.batch_runner.is_running(), timeout=60000)
    qtbot.wait(50)
    assert got and {k for k, _, _ in got} == {key}
    assert all(isinstance(msg, str) and msg for _, msg, _ in got)
    assert all(0 <= pct <= 100 for _, _, pct in got)
    assert window.model.active_well.status == "run_ok"


# ---- E: status bar -------------------------------------------------------------


class FakeTimer:
    def __init__(self, valid=False, elapsed=1000):
        self.valid, self._elapsed, self.restarts = valid, elapsed, 0

    def isValid(self):
        return self.valid

    def elapsed(self):
        return self._elapsed

    def restart(self):
        self.restarts += 1
        self.valid = True

    def invalidate(self):
        self.valid = False


@pytest.fixture
def three_wells(window, tmp_path):
    window._begin_load([[_parsed(tmp_path, f"w{i}.las", well=f"BKS-0{i}")] for i in (1, 2, 3)])
    keys = [ds.key for ds in window.model.project.wells]
    window._progress_timer = FakeTimer()
    return window, keys


def test_single_well_shows_the_stage_message_and_percent(three_wells):
    window, keys = three_wells
    window._on_batch_started(1)
    window._on_well_progress(keys[0], "Calculating porosity...", 40)
    assert window.statusBar.currentMessage() == "Calculating porosity..."
    assert window.status_progress.value() == 40
    window._on_well_progress(keys[0], "Computing saturation...", 75)
    assert window.statusBar.currentMessage() == "Computing saturation..."
    assert window.status_progress.value() == 75


def test_multi_well_progress_is_the_aggregate(three_wells):
    window, keys = three_wells
    a, b, c = keys
    window._on_batch_started(4)
    window._on_batch_progress(1, 4)  # one well finished
    window._on_well_progress(a, "Calculating porosity...", 50)
    window._on_well_progress(b, "Computing saturation...", 30)
    # (100*1 + 50 + 30) / 4 = 45
    assert window.status_progress.value() == 45
    name_b = window.model.project.get(b).display_name
    assert window.statusBar.currentMessage() == (
        f"Analysing 2 of 4 wells · {name_b}: Computing saturation..."
    )
    window._on_well_progress(a, "Computing saturation...", 90)
    name_a = window.model.project.get(a).display_name
    assert window.status_progress.value() == int((100 + 90 + 30) / 4)
    assert window.statusBar.currentMessage().startswith("Analysing 2 of 4 wells")
    assert name_a in window.statusBar.currentMessage()  # most recent reporter


def test_finished_wells_stop_contributing_their_stage(three_wells):
    window, keys = three_wells
    window._on_batch_started(2)
    window._on_well_progress(keys[0], "Computing saturation...", 90)
    # The runner reports 1 of 2 done; the finished well is no longer pending.
    window._on_batch_progress(1, 2)
    assert window.status_progress.value() == 50


def test_batch_progress_without_stage_reports_keeps_the_old_text(three_wells):
    window, keys = three_wells
    window._on_batch_started(3)
    window._on_batch_progress(1, 3)
    assert window.statusBar.currentMessage() == "Running 1/3 wells…"
    assert window.status_progress.value() == 33


def test_progress_updates_are_throttled_to_ten_per_second(three_wells):
    window, keys = three_wells
    timer = FakeTimer()
    window._progress_timer = timer
    window._on_batch_started(1)
    window._on_well_progress(keys[0], "first", 10)      # timer not started: shown
    assert window.statusBar.currentMessage() == "first"
    timer._elapsed = 50
    window._on_well_progress(keys[0], "too soon", 20)   # < 100 ms: dropped
    assert window.statusBar.currentMessage() == "first"
    timer._elapsed = 100
    window._on_well_progress(keys[0], "later", 30)      # >= 100 ms: shown
    assert window.statusBar.currentMessage() == "later"
    timer._elapsed = 10
    window._on_well_progress(keys[0], "Complete", 100)  # the final 100 always passes
    assert window.statusBar.currentMessage() == "Complete"
    restarts = timer.restarts
    window._on_batch_progress(1, 1)                     # completion is never throttled
    assert timer.restarts == restarts + 1


def test_batch_finished_clears_the_progress_bar(three_wells):
    window, keys = three_wells
    window._on_batch_started(1)
    window._on_well_progress(keys[0], "Computing saturation...", 90)
    window._on_batch_finished({"ok": [], "failed": {}, "skipped": [], "cancelled": True})
    assert not window.status_progress.isVisible()
    assert window.status_progress.value() == 0
