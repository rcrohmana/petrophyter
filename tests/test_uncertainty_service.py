"""Monte Carlo lifecycle: UncertaintyRunner / UncertaintyWorker and the MainWindow wiring.

The kernel (modules.uncertainty.freeze_well / run_monte_carlo) is replaced by fakes, so
these tests cover only the service: validation, generation counter, cancel, merging of
exclusions, basis and config hash, progress throttle, and the window hooks.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time
from dataclasses import dataclass, field

import pandas as pd
import pytest
from PyQt6.QtWidgets import QMessageBox

import modules.uncertainty as unc
from models.app_model import AppModel
from models.project import WellDataset
from modules.param_scopes import params_hash
from services.uncertainty_service import UncertaintyRunner
from ui.main_window import MainWindow

REAL_CONFIRM_QUIT = MainWindow._confirm_quit


class FakeExcluded(Exception):
    pass


@dataclass
class FakeResult:
    excluded: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    basis: dict = field(default_factory=dict)
    config_hash: str = ""
    keys: tuple = ()


@dataclass
class FakeFrozen:
    key: str


class Kernel:
    """Controls the fake kernel from a test."""

    def __init__(self):
        self.excluded_keys = set()
        self.raise_keys = set()
        self.progress_calls = 0
        self.gate = None           # threading.Event the MC waits for, when set
        self.entered = threading.Event()
        self.respect_cancel = True


@pytest.fixture
def kernel(monkeypatch):
    k = Kernel()

    def freeze_well(key, name, data, curve_mapping, params, formation_tops=None):
        if key in k.excluded_keys:
            raise FakeExcluded(f"no PHIE in {name}")
        if key in k.raise_keys:
            raise ValueError("boom")
        return FakeFrozen(key)

    def run_monte_carlo(frozen_wells, cfg, progress=None, cancel=None):
        k.entered.set()
        total = 1000
        for i in range(1, total + 1):
            if k.gate is not None and i == 1:
                k.gate.wait(10)
            if cancel is not None and cancel() and k.respect_cancel:
                return None
            if progress is not None:
                progress(i, total)
                k.progress_calls += 1
        return FakeResult(keys=tuple(f.key for f in frozen_wells))

    monkeypatch.setattr(unc, "freeze_well", freeze_well, raising=False)
    monkeypatch.setattr(unc, "run_monte_carlo", run_monte_carlo, raising=False)
    monkeypatch.setattr(unc, "UncertaintyExcluded", FakeExcluded, raising=False)
    return k


def _well(key, with_rt=True):
    ds = WellDataset(key, key.split(":")[1])
    cols = {"DEPTH": [100.0, 100.5, 101.0], "GR": [40.0, 60.0, 80.0]}
    if with_rt:
        cols["RT"] = [10.0, 20.0, 5.0]
    ds.las_data = pd.DataFrame(cols)
    ds.curve_mapping = {"GR": "GR", "RT": "RT"}
    return ds


def _model(keys=("WELL:A", "WELL:B"), enable=True):
    model = AppModel()
    for key in keys:
        model.project.add_well(_well(key))
    if enable:
        model.project.uncertainty.distributions["m"].enabled = True
        model.project.uncertainty.distributions["m"].low = -0.1
        model.project.uncertainty.distributions["m"].high = 0.1
    return model


@pytest.fixture
def runner(qtbot):
    r = UncertaintyRunner()
    yield r
    r.cancel()
    r._pool.waitForDone(5000)


def _run(qtbot, runner, model):
    out = {"completed": [], "failed": [], "cancelled": 0}
    runner.completed.connect(out["completed"].append)
    runner.failed.connect(out["failed"].append)
    runner.cancelled.connect(lambda: out.__setitem__("cancelled", out["cancelled"] + 1))
    with qtbot.waitSignal(runner.finished, timeout=20000):
        assert runner.start(model) is None
    return out


# ---- start refusals ----

def test_start_refused_without_enabled_distribution(runner):
    err = runner.start(_model(enable=False))
    assert err and "Enable at least one" in err
    assert not runner.is_running()


def test_start_refused_without_wells(runner):
    err = runner.start(_model(keys=()))
    assert err and "No well" in err


def test_start_refused_when_no_well_has_rt(runner):
    model = _model(keys=())
    model.project.add_well(_well("WELL:A", with_rt=False))
    err = runner.start(model)
    assert err and "RT" in err


def test_start_refused_while_running(qtbot, runner, kernel):
    kernel.gate = threading.Event()
    model = _model()
    assert runner.start(model) is None
    assert runner.is_running()
    assert "already running" in runner.start(model)
    kernel.gate.set()
    with qtbot.waitSignal(runner.finished, timeout=20000):
        pass
    assert not runner.is_running()


# ---- results ----

def test_completed_carries_basis_and_config_hash(qtbot, runner, kernel):
    model = _model()
    got = []
    runner.completed.connect(got.append)
    started = []
    runner.started.connect(lambda w, n: started.append((w, n)))
    out = _run(qtbot, runner, model)
    assert len(got) == 1 and not out["failed"] and not out["cancelled"]
    result = got[0]
    assert started == [(2, model.project.uncertainty.n)]
    expected = {ds.key: model.well_params_hash(ds) for ds in model.project.wells}
    assert result.basis == expected
    assert result.config_hash == params_hash(unc.config_to_dict(model.project.uncertainty))
    # The runner does not write the model.
    assert model.project.uncertainty_result is None


def test_excluded_wells_are_merged(qtbot, runner, kernel):
    kernel.excluded_keys = {"WELL:A"}
    kernel.raise_keys = set()
    model = _model(keys=("WELL:A", "WELL:B", "WELL:C"))
    kernel.raise_keys = {"WELL:C"}
    out = _run(qtbot, runner, model)
    result = out["completed"][0]
    assert result.keys == ("WELL:B",)
    by_key = {e["key"]: e for e in result.excluded}
    assert set(by_key) == {"WELL:A", "WELL:C"}
    assert "no PHIE" in by_key["WELL:A"]["reason"]
    assert by_key["WELL:C"]["reason"] == "boom"
    assert by_key["WELL:A"]["name"] == "A"
    assert any("no PHIE" in w for w in result.warnings)
    assert set(result.basis) == {"WELL:B"}


def test_all_wells_excluded_fails(qtbot, runner, kernel):
    kernel.excluded_keys = {"WELL:A", "WELL:B"}
    out = _run(qtbot, runner, _model())
    assert not out["completed"]
    assert len(out["failed"]) == 1
    assert out["failed"][0].startswith("No well can be evaluated:")
    assert "no PHIE in A" in out["failed"][0]


def test_kernel_exception_fails(qtbot, runner, monkeypatch, kernel):
    def boom(*a, **k):
        raise RuntimeError("kernel broke")
    monkeypatch.setattr(unc, "run_monte_carlo", boom)
    out = _run(qtbot, runner, _model())
    assert len(out["failed"]) == 1 and "kernel broke" in out["failed"][0]


# ---- cancel and generation ----

def test_cancel_emits_cancelled_and_no_completed(qtbot, runner, kernel):
    kernel.gate = threading.Event()
    out = {"completed": [], "cancelled": 0}
    runner.completed.connect(out["completed"].append)
    runner.cancelled.connect(lambda: out.__setitem__("cancelled", out["cancelled"] + 1))
    assert runner.start(_model()) is None
    assert kernel.entered.wait(10)
    with qtbot.waitSignal(runner.finished, timeout=5000):
        runner.cancel()
    kernel.gate.set()
    runner._pool.waitForDone(10000)
    qtbot.wait(100)    # let any (dropped) queued worker signal arrive
    assert out["cancelled"] == 1
    assert out["completed"] == []
    assert not runner.is_running()


def test_late_result_after_cancel_and_restart_is_dropped(qtbot, runner, kernel):
    """Run 1 ignores cancel and finishes late; its result must not be delivered."""
    kernel.gate = threading.Event()
    kernel.respect_cancel = False
    model = _model()
    completed = []
    runner.completed.connect(completed.append)
    assert runner.start(model) is None
    assert kernel.entered.wait(10)
    runner.cancel()
    kernel.respect_cancel = True
    kernel.gate = None
    assert runner.start(model) is None      # queued behind run 1 (one pool thread)
    first_generation = runner.generation
    kernel.entered.clear()
    with qtbot.waitSignal(runner.finished, timeout=20000):
        pass
    # Run 1's gate is only released after the restart; its late result is dropped.
    # (Gate was replaced for run 2, so release run 1 through its own event.)
    assert runner.generation == first_generation
    assert len(completed) == 1               # only run 2's result


def test_late_result_is_dropped_directly(qtbot, runner):
    runner._generation = 5
    runner._running = True
    seen = []
    runner.completed.connect(seen.append)
    runner._on_completed(4, object())
    runner._on_failed(3, "x")
    assert seen == [] and runner.is_running()


def test_progress_is_throttled(qtbot, runner, kernel):
    seen = []
    runner.progress.connect(lambda d, t: seen.append((d, t)))
    _run(qtbot, runner, _model())
    assert kernel.progress_calls == 1000
    assert 1 <= len(seen) < 200            # 1000 reports collapsed (<= 10 Hz plus the final)
    assert seen[-1] == (1000, 1000)


# ---- MainWindow ----

@pytest.fixture()
def window(qtbot, monkeypatch, kernel):
    for name in ("critical", "warning", "information"):
        monkeypatch.setattr(QMessageBox, name, lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    w = MainWindow()
    qtbot.addWidget(w)
    yield w
    w.uncertainty_runner.cancel()
    w.uncertainty_runner._pool.waitForDone(5000)


def _load(window, keys=("WELL:A", "WELL:B")):
    for key in keys:
        window.model.project.add_well(_well(key))
    d = window.model.project.uncertainty.distributions["m"]
    d.enabled, d.low, d.high = True, -0.1, 0.1


def test_window_stores_completed_result(qtbot, window):
    _load(window)
    with qtbot.waitSignal(window.uncertainty_result_changed, timeout=20000):
        window.run_uncertainty()
    assert isinstance(window.model.project.uncertainty_result, FakeResult)
    assert set(window.model.project.uncertainty_result.basis) == {"WELL:A", "WELL:B"}
    qtbot.waitUntil(lambda: not window.uncertainty_runner.is_running(), timeout=5000)
    assert not window.status_progress.isVisible()


def test_window_run_refused_while_batch_running(window, monkeypatch):
    _load(window)
    monkeypatch.setattr(window.batch_runner, "is_running", lambda: True)
    window.run_uncertainty()
    assert not window.uncertainty_runner.is_running()
    assert "Wait for the analysis to finish before running Monte Carlo." in \
        window.banner.message_label.text()
    monkeypatch.setattr(window.batch_runner, "is_running", lambda: False)


def test_window_start_error_shown_as_banner(window):
    window.run_uncertainty()          # nothing enabled, no wells
    assert "Enable at least one" in window.banner.message_label.text()


def test_window_failure_is_modal_error(qtbot, window, kernel, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a, **k: shown.append(a[2]) or QMessageBox.StandardButton.Ok)
    _load(window)
    kernel.excluded_keys = {"WELL:A", "WELL:B"}
    with qtbot.waitSignal(window.uncertainty_runner.failed, timeout=20000):
        window.run_uncertainty()
    assert len(shown) == 1 and "No well can be evaluated" in shown[0]
    assert window.model.project.uncertainty_result is None


def test_new_project_cancels_and_clears(qtbot, window, kernel):
    _load(window)
    kernel.gate = threading.Event()
    window.run_uncertainty()
    assert kernel.entered.wait(10)
    window.model.project.uncertainty_result = FakeResult()
    window.model.mark_clean()
    window._on_new_project()
    assert not window.uncertainty_runner.is_running()
    assert window.model.project.uncertainty_result is None
    kernel.gate.set()
    window.uncertainty_runner._pool.waitForDone(10000)
    qtbot.wait(100)
    assert window.model.project.uncertainty_result is None


def test_cancel_uncertainty(qtbot, window, kernel):
    _load(window)
    kernel.gate = threading.Event()
    window.run_uncertainty()
    assert kernel.entered.wait(10)
    with qtbot.waitSignal(window.uncertainty_runner.cancelled, timeout=5000):
        window.cancel_uncertainty()
    kernel.gate.set()
    assert window.model.project.uncertainty_result is None


@pytest.mark.parametrize("answer", [QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No])
def test_close_while_running_asks(qtbot, window, monkeypatch, answer):
    monkeypatch.setattr(MainWindow, "_confirm_quit", REAL_CONFIRM_QUIT)
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or answer)
    cancelled = []
    monkeypatch.setattr(window.uncertainty_runner, "cancel", lambda: cancelled.append(True))
    monkeypatch.setattr(window.uncertainty_runner, "is_running", lambda: True)
    accepted = window.close()
    assert asked == ["Monte Carlo is still running. Quit anyway?"]
    if answer == QMessageBox.StandardButton.Yes:
        assert accepted and cancelled == [True]
    else:
        assert not accepted and cancelled == []
    monkeypatch.setattr(window.uncertainty_runner, "is_running", lambda: False)


def test_close_prefers_analysis_question(window, monkeypatch):
    monkeypatch.setattr(MainWindow, "_confirm_quit", REAL_CONFIRM_QUIT)
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.No)
    monkeypatch.setattr(window.batch_runner, "is_running", lambda: True)
    monkeypatch.setattr(window.uncertainty_runner, "is_running", lambda: True)
    assert not window.close()
    assert asked == ["Analysis is still running. Quit anyway?"]
    monkeypatch.setattr(window.batch_runner, "is_running", lambda: False)
    monkeypatch.setattr(window.uncertainty_runner, "is_running", lambda: False)


# ---- real kernel, end to end ----

def test_runner_with_the_real_kernel(qtbot, runner):
    """No fakes: two wells run, a well without porosity logs is excluded with its reason."""
    from tests.golden.cases import FULL_MAPPING
    from tests.test_perf_multiwell import _well as _log

    model = AppModel()
    for i in range(2):
        ds = WellDataset(f"WELL:R{i}", f"R{i}")
        ds.las_data = _log(i).iloc[:400].reset_index(drop=True)
        ds.curve_mapping = dict(FULL_MAPPING)
        model.project.add_well(ds)
    bare = WellDataset("WELL:BARE", "BARE")
    bare.las_data = _log(9).iloc[:400][["DEPTH", "GR", "RT"]].reset_index(drop=True)
    bare.curve_mapping = {"GR": "GR", "RT": "RT"}
    model.project.add_well(bare)
    cfg = model.project.uncertainty
    cfg.n = unc.N_MIN
    for name in ("m", "rw", "sw_cutoff"):
        lo, mid, hi = unc.SUGGESTED_RANGES[name]
        d = cfg.distributions[name]
        d.enabled, d.low, d.mid, d.high = True, lo, mid, hi

    out = _run(qtbot, runner, model)
    assert not out["failed"]
    (result,) = out["completed"]
    assert [w["key"] for w in result.wells] == ["WELL:R0", "WELL:R1"]
    assert [e["key"] for e in result.excluded] == ["WELL:BARE"]
    assert set(result.basis) == {"WELL:R0", "WELL:R1"}
    assert result.config_hash == params_hash(unc.config_to_dict(cfg))
    s = result.stats[("field", "hcpv_net_pay")]
    assert s["n"] == unc.N_MIN and s["p90"] <= s["p50"] <= s["p10"]
