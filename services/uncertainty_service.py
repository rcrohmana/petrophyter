"""
Uncertainty service: runs the Monte Carlo kernel (modules.uncertainty) on a pool thread.

Wells are snapshotted on the GUI thread; the worker freezes each well, runs the kernel and
reports through signals. Results of a cancelled or superseded run (older generation) are
dropped, as in ``BatchRunner``. The runner never writes the model: the owner stores the
result it receives from ``completed``.
"""

import copy
import logging
import threading
from typing import List, Optional

from PyQt6.QtCore import QElapsedTimer, QObject, QRunnable, QThreadPool, pyqtSignal

from modules.param_scopes import params_hash
from services.analysis_service import WellSnapshot, snapshot_well

logger = logging.getLogger(__name__)


def result_is_stale(model, result) -> bool:
    """True when ``result`` no longer matches the project (shared by the tab and the export)."""
    from modules.uncertainty import config_to_dict

    project = model.project
    basis = getattr(result, "basis", None) or {}
    excluded = {e.get("key") for e in (getattr(result, "excluded", None) or [])}
    for key, h in basis.items():
        ds = project.get(key)
        if ds is None or model.well_params_hash(ds) != h:
            return True
    for ds in project.wells:
        if ds.key in basis or ds.key in excluded:
            continue
        if UncertaintyRunner._has_rt_data(model, ds):
            return True
    cfg_hash = params_hash(config_to_dict(project.uncertainty))
    return cfg_hash != getattr(result, "config_hash", None)


class UncertaintySignals(QObject):
    """Signals of one worker."""

    progress = pyqtSignal(int, int)    # done, total
    completed = pyqtSignal(object)     # MCResult
    cancelled = pyqtSignal()
    failed = pyqtSignal(str)


class UncertaintyWorker(QRunnable):
    """Freeze every snapshot, run the Monte Carlo kernel, report through signals."""

    def __init__(self, snapshots: List[WellSnapshot], config):
        super().__init__()
        self.signals = UncertaintySignals()
        self._snapshots = list(snapshots)
        self._config = copy.deepcopy(config)
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def _cancelled(self) -> bool:
        return self._cancel.is_set()

    def run(self):
        try:
            from modules import uncertainty as unc

            frozen, excluded = [], []
            for snap in self._snapshots:
                if self._cancelled():
                    self.signals.cancelled.emit()
                    return
                try:
                    frozen.append(unc.freeze_well(
                        snap.key, snap.display_name, snap.data, snap.curve_mapping,
                        snap.params, snap.formation_tops))
                except unc.UncertaintyExcluded as e:
                    excluded.append({"key": snap.key, "name": snap.display_name, "reason": str(e)})
                except Exception as e:  # noqa: BLE001 - any failure on one well excludes it
                    logger.debug("freeze_well failed for %s", snap.key, exc_info=True)
                    excluded.append({"key": snap.key, "name": snap.display_name, "reason": str(e)})
            if not frozen:
                reasons = "; ".join(f"{e['name']}: {e['reason']}" for e in excluded)
                self.signals.failed.emit(f"No well can be evaluated: {reasons}")
                return

            result = unc.run_monte_carlo(
                frozen, self._config, progress=self.signals.progress.emit,
                cancel=self._cancelled)
            if result is None or self._cancelled():
                self.signals.cancelled.emit()
                return
            result.excluded = list(excluded) + list(getattr(result, "excluded", None) or [])
            result.warnings = list(getattr(result, "warnings", None) or [])
            for e in excluded:
                result.warnings.append(f"{e['name']} excluded: {e['reason']}")
            dropped = {e["key"] for e in excluded}
            result.basis = {s_.key: s_.params_hash for s_ in self._snapshots
                            if s_.key not in dropped}
            result.config_hash = params_hash(unc.config_to_dict(self._config))
            self.signals.completed.emit(result)
        except Exception as e:  # noqa: BLE001
            logger.exception("Monte Carlo run failed")
            self.signals.failed.emit(f"Monte Carlo failed: {e}")


class _Relay(QObject):
    """GUI-thread receiver for one worker, tagged with its run generation."""

    def __init__(self, runner: "UncertaintyRunner", generation: int):
        super().__init__(runner)
        self._runner, self._generation = runner, generation

    def on_progress(self, done, total):
        self._runner._on_progress(self._generation, done, total)

    def on_completed(self, result):
        self._runner._on_completed(self._generation, result)

    def on_cancelled(self):
        self._runner._on_cancelled(self._generation)

    def on_failed(self, message):
        self._runner._on_failed(self._generation, message)


class UncertaintyRunner(QObject):
    """One Monte Carlo run at a time on a single pool thread."""

    started = pyqtSignal(int, int)     # n wells, n realisations
    progress = pyqtSignal(int, int)    # done, total
    completed = pyqtSignal(object)     # MCResult
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()
    finished = pyqtSignal()

    PROGRESS_MAX_HZ = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._generation = 0
        self._running = False
        self._worker: Optional[UncertaintyWorker] = None
        self._relay: Optional[_Relay] = None
        self._retired: list = []    # workers/relays of cancelled runs, kept alive until they exit
        self._timer = QElapsedTimer()

    @property
    def generation(self) -> int:
        return self._generation

    def is_running(self) -> bool:
        return self._running

    # ---- control ----
    @staticmethod
    def _has_rt_data(model, ds) -> bool:
        data = ds.las_data
        if data is None:
            return False
        mapping = model.params_for_well(ds).get("curve_mapping") or {}
        return mapping.get("RT", "RT") in data.columns

    def start(self, model) -> Optional[str]:
        """Start a run on the project's wells; returns an error text instead of starting."""
        from modules.uncertainty import validate_config

        cfg = model.project.uncertainty
        errors = validate_config(cfg)
        if errors:
            return " ".join(errors)
        if self._running:
            return "Monte Carlo is already running."
        wells = [ds for ds in model.project.wells if self._has_rt_data(model, ds)]
        if not wells:
            return "No well has data with a resistivity (RT) curve."
        snapshots = [snapshot_well(model, ds, model.well_params_hash(ds)) for ds in wells]

        self._generation += 1
        worker = UncertaintyWorker(snapshots, cfg)
        relay = _Relay(self, self._generation)
        worker.signals.progress.connect(relay.on_progress)
        worker.signals.completed.connect(relay.on_completed)
        worker.signals.cancelled.connect(relay.on_cancelled)
        worker.signals.failed.connect(relay.on_failed)
        self._worker, self._relay = worker, relay
        self._running = True
        self._timer.invalidate()
        self.started.emit(len(snapshots), int(cfg.n))
        self._pool.start(worker)
        return None

    def cancel(self):
        """Drop the current run; late signals from it are ignored."""
        self._generation += 1
        if not self._running:
            return
        self._running = False
        if self._worker is not None:
            self._worker.cancel()
            self._retired.append((self._worker, self._relay))
            self._worker = self._relay = None
        self._retired = self._retired[-8:]
        self.cancelled.emit()
        self.finished.emit()

    # ---- worker callbacks (GUI thread) ----
    def _live(self, generation: int) -> bool:
        return generation == self._generation and self._running

    def _on_progress(self, generation: int, done: int, total: int):
        if not self._live(generation):
            return
        timer = self._timer
        final = total > 0 and done >= total
        if not final and timer.isValid() and timer.elapsed() < 1000 // self.PROGRESS_MAX_HZ:
            return
        timer.restart()
        self.progress.emit(int(done), int(total))

    def _on_completed(self, generation: int, result):
        if not self._live(generation):
            return
        self._end_after(lambda: self.completed.emit(result))

    def _on_failed(self, generation: int, message: str):
        if not self._live(generation):
            return
        self._end_after(lambda: self.failed.emit(message))

    def _on_cancelled(self, generation: int):
        if not self._live(generation):
            return
        self._end_after(self.cancelled.emit)

    def _end_after(self, emit):
        self._running = False
        self._worker = self._relay = None
        emit()
        self.finished.emit()
