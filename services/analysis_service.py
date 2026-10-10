"""
Analysis Service for Petrophyter PyQt
Wraps the petrophysics calculation logic for background execution.
"""

from dataclasses import dataclass, field

from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, QThread, QThreadPool
import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional
import logging
import traceback


logger = logging.getLogger(__name__)

from modules.param_scopes import normalize_zone
from modules.pipeline import (
    PipelineError,
    assign_zones,
    estimate_rw_rsh,
    resolve_nphi_matrix,
    run_pipeline,
)
from modules.shale_estimation import SHALE_SETTING_DEFAULTS, estimate_shale_point


@dataclass
class WellSnapshot:
    """Everything the pipeline needs for one well, detached from the model."""

    key: str
    display_name: str
    data: Optional[pd.DataFrame]
    curve_mapping: Dict[str, str]
    params: dict
    formation_tops: object = None
    params_hash: str = ""
    # The dataset the snapshot was taken from (identity check on delivery).
    dataset: object = field(default=None, repr=False, compare=False)


def snapshot_well(model, ds, params_hash: Optional[str] = None) -> WellSnapshot:
    """Snapshot ``ds`` for a worker thread. GUI thread only."""
    params = model.params_for_well(ds)
    data = ds.las_data
    return WellSnapshot(
        key=ds.key,
        display_name=ds.display_name or ds.key,
        data=data.copy() if data is not None else None,
        curve_mapping=params["curve_mapping"],
        params=params,
        formation_tops=ds.formation_tops,
        params_hash=params_hash if params_hash is not None else model.well_params_hash(ds),
        dataset=ds,
    )


class AnalysisSignals(QObject):
    """Signals for analysis worker."""

    started = pyqtSignal()
    progress = pyqtSignal(str, int)  # (message, percentage)
    completed = pyqtSignal(pd.DataFrame, dict)  # (results, summary)
    error = pyqtSignal(str)
    completed_key = pyqtSignal(str, object, object)  # (well key, results, summary)
    error_key = pyqtSignal(str, str)  # (well key, message)


class AnalysisWorker(QRunnable):
    """Run :func:`modules.pipeline.run_pipeline` on a pool thread.

    Everything the pipeline needs is snapshotted in ``__init__``, which runs on
    the GUI thread, so the model is never read from the worker thread.
    ``AnalysisWorker(model)`` runs the active well; :meth:`from_snapshot` runs
    any well.
    """

    def __init__(self, model=None, snapshot: Optional[WellSnapshot] = None):
        super().__init__()
        self.model = model
        self.signals = AnalysisSignals()
        if snapshot is None:
            las_data = model.las_data
            project = getattr(model, "project", None)
            self._key = (project.active_key or "") if project is not None else ""
            self._data = las_data.copy() if las_data is not None else None
            self._params = model.to_params()
            self._formation_tops = model.formation_tops
        else:
            self._key = snapshot.key
            self._data = snapshot.data
            self._params = snapshot.params
            self._formation_tops = snapshot.formation_tops

    @classmethod
    def from_snapshot(cls, snapshot: WellSnapshot) -> "AnalysisWorker":
        return cls(None, snapshot=snapshot)

    def _fail(self, message: str):
        self.signals.error.emit(message)
        self.signals.error_key.emit(self._key, message)

    def run(self):
        """Execute the analysis and report through signals."""
        try:
            self.signals.started.emit()
            if self._data is None:
                self.signals.progress.emit("Preparing data...", 5)
                self._fail("No data loaded. Please load a LAS file first.")
                return

            results, summary = run_pipeline(
                self._data,
                self._params["curve_mapping"],
                self._params,
                progress=self.signals.progress.emit,
                formation_tops=self._formation_tops,
            )
            self.signals.completed.emit(results, summary)
            self.signals.completed_key.emit(self._key, results, summary)

        except PipelineError as e:
            self._fail(str(e))
        except Exception as e:
            self._fail(f"Analysis failed: {str(e)}\n{traceback.format_exc()}")


class _Relay(QObject):
    """GUI-thread receiver for one worker, tagged with its run generation."""

    def __init__(self, runner: "BatchRunner", generation: int, key: str):
        super().__init__(runner)
        self._runner, self._generation, self._key = runner, generation, key

    def on_started(self):
        self._runner._on_started(self._generation, self._key)

    def on_completed(self, key, results, summary):
        self._runner._on_done(self._generation, key, results, summary)

    def on_error(self, key, message):
        self._runner._on_failed(self._generation, key, message)


class BatchRunner(QObject):
    """Run the analysis for several wells on a thread pool.

    Wells are snapshotted on the GUI thread; results of a cancelled or
    superseded run (older generation) are dropped and never emitted.
    """

    started = pyqtSignal(int)  # total wells to run
    well_started = pyqtSignal(str)
    well_completed = pyqtSignal(str, object, object, str)  # key, results, summary, params hash
    well_failed = pyqtSignal(str, str)
    progress = pyqtSignal(int, int)  # done, total
    finished = pyqtSignal(dict)  # {"ok", "failed", "skipped", "cancelled"}

    def __init__(self, parent=None, max_threads: Optional[int] = None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        ideal = QThread.idealThreadCount()
        self._pool.setMaxThreadCount(max_threads or max(1, min(4, ideal if ideal > 0 else 2)))
        self._generation = 0
        self._running = False
        self._project = None
        self._pending: Dict[str, WellSnapshot] = {}
        self._relays = []
        self._total = 0
        self._done = 0
        self._report = self._new_report()

    @staticmethod
    def _new_report() -> dict:
        return {"ok": [], "failed": {}, "skipped": [], "cancelled": False}

    # ---- state ----
    @property
    def generation(self) -> int:
        return self._generation

    def is_running(self) -> bool:
        return self._running

    def is_pending(self, key: Optional[str]) -> bool:
        """True while ``key`` is queued or running in the current batch."""
        return self._running and key in self._pending

    # ---- control ----
    def run(self, model, keys=None, force: bool = False, extend: bool = False):
        """Analyse ``keys`` (default: every well with data).

        Unchanged wells (same parameter hash as their last run) are skipped
        unless ``force``. A new run cancels a running one, except with
        ``extend`` which adds the wells to the running batch. GUI thread only.
        """
        project = model.project
        wanted = list(project.keys()) if keys is None else list(dict.fromkeys(keys))
        extending = extend and self._running
        snapshots, skipped = [], []
        for key in wanted:
            ds = project.get(key)
            if ds is None or ds.las_data is None:
                continue
            if extending and key in self._pending:
                continue
            params_hash = model.well_params_hash(ds)
            if not force and ds.calculated and params_hash == ds.run_params_hash:
                skipped.append(key)
                continue
            snapshots.append(snapshot_well(model, ds, params_hash))

        if extending:
            self._report["skipped"].extend(skipped)
            self._total += len(snapshots)
        else:
            if self._running:
                self.cancel()
            self._generation += 1
            self._report = self._new_report()
            self._report["skipped"] = skipped
            self._total = len(snapshots)
            self._done = 0
            self._pending = {}
            if not snapshots:
                self.finished.emit(self._report)
                return
            self._running = True
            self._project = project
            self.started.emit(self._total)
        for snap in snapshots:
            self._pending[snap.key] = snap
        for snap in snapshots:
            worker = AnalysisWorker.from_snapshot(snap)
            relay = _Relay(self, self._generation, snap.key)
            self._relays.append(relay)
            worker.signals.started.connect(relay.on_started)
            worker.signals.completed_key.connect(relay.on_completed)
            worker.signals.error_key.connect(relay.on_error)
            self._pool.start(worker)
        if extending and snapshots:
            self.progress.emit(self._done, self._total)

    def cancel(self):
        """Drop everything still running or queued; late results are ignored."""
        self._generation += 1
        self._pool.clear()
        self._drop_relays()
        self._pending = {}
        if self._running:
            self._running = False
            self._report["cancelled"] = True
            self.finished.emit(self._report)

    # ---- worker callbacks (GUI thread) ----
    def _on_started(self, generation: int, key: str):
        if generation == self._generation and key in self._pending:
            self.well_started.emit(key)

    def _complete_one(self):
        self._done += 1
        self.progress.emit(self._done, self._total)
        if not self._pending:
            self._running = False
            self._drop_relays()
            self.finished.emit(self._report)

    def _drop_relays(self):
        for relay in self._relays:
            relay.deleteLater()
        self._relays = []

    def _take(self, generation: int, key: str):
        """The snapshot for a live result, or None when it must be dropped."""
        if generation != self._generation or key not in self._pending:
            return None, False
        snap = self._pending.pop(key)
        current = self._project.get(key) if self._project is not None else None
        return snap, current is not None and current is snap.dataset

    def _on_done(self, generation: int, key: str, results, summary):
        snap, deliver = self._take(generation, key)
        if snap is None:
            return
        if deliver:
            self._report["ok"].append(key)
            self.well_completed.emit(key, results, summary, snap.params_hash)
        self._complete_one()

    def _on_failed(self, generation: int, key: str, message: str):
        snap, deliver = self._take(generation, key)
        if snap is None:
            return
        if deliver:
            self._report["failed"][key] = message
            self.well_failed.emit(key, message)
        self._complete_one()


class AnalysisService(QObject):
    """
    Service for running petrophysics analysis.
    Manages background thread execution.
    """

    started = pyqtSignal()
    progress = pyqtSignal(str, int)
    completed = pyqtSignal(pd.DataFrame, dict)
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread_pool = QThreadPool()
        self._current_worker = None

    @staticmethod
    def _get_nphi_matrix(model) -> float:
        """Resolve the neutron matrix response for a model (see pipeline.resolve_nphi_matrix)."""
        return resolve_nphi_matrix(
            {
                "nphi_matrix": getattr(model, "nphi_matrix", None),
                "lithology_preset": getattr(model, "lithology_preset", "sandstone"),
            }
        )

    def run_analysis(self, model):
        """Start analysis in background thread."""
        worker = AnalysisWorker(model)
        worker.signals.started.connect(self.started.emit)
        worker.signals.progress.connect(self.progress.emit)
        worker.signals.completed.connect(self._on_completed)
        worker.signals.error.connect(self.error.emit)

        self._current_worker = worker
        self.thread_pool.start(worker)

    def _on_completed(self, results: pd.DataFrame, summary: dict):
        """Handle analysis completion."""
        self.completed.emit(results, summary)

    def calculate_rw_rsh(self, model, zone: Optional[str] = None) -> Optional[Dict]:
        """Calculate Rw and Rsh from log data (synchronous).

        With ``zone`` only that zone's samples of the active well are used.
        """
        if model.las_data is None:
            return None

        try:
            estimate = estimate_rw_rsh(
                model.las_data,
                model.curve_mapping,
                model.to_params(),
                formation_tops=model.formation_tops,
                zone=zone,
            )
        except Exception:
            return None
        if estimate is None:
            return None

        return {
            "rw": round(estimate["rw"], 4),
            "rsh": round(estimate["rsh"], 2),
            "rw_source": estimate["rw_source"],
            "rsh_source": estimate["rsh_source"],
            "warnings": estimate["warnings"],
        }

    def calculate_shale_parameters(self, model, zone: Optional[str] = None) -> Optional[Dict]:
        """Calculate the shale point from the active well's data (synchronous).

        Thin wrapper around :func:`modules.shale_estimation.estimate_shale_point`;
        keeps the Per-Formation filter. With ``zone`` (and formation tops) only
        that zone's samples are used.
        """
        if model.las_data is None:
            return None

        data = model.las_data.copy()

        if (
            model.analysis_mode == "Per-Formation"
            and model.selected_formations
            and model.formation_tops
        ):
            data = model.formation_tops.filter_by_formations(
                data, model.selected_formations, "DEPTH"
            )
        if zone and model.formation_tops is not None and len(data) > 0:
            labels, _ = assign_zones(data["DEPTH"], model.formation_tops)
            data = data[labels == normalize_zone(zone)]

        params = {
            "vsh_baseline_method": model.vsh_baseline_method,
            "gr_min_manual": model.gr_min_manual,
            "gr_max_manual": model.gr_max_manual,
            "vsh_methods": model.vsh_methods,
        }
        params.update(
            {k: getattr(model, k) for k in SHALE_SETTING_DEFAULTS if hasattr(model, k)}
        )
        return estimate_shale_point(data, model.curve_mapping, params)
