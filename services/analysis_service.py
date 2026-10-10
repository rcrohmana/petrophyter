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

from modules.petrophysics import PetrophysicsCalculator
from modules.pipeline import (
    PipelineError,
    estimate_rw_rsh,
    resolve_nphi_matrix,
    run_pipeline,
    vsh_reference,
)
from modules.statistics_utils import StatisticsUtils


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

    def calculate_shale_parameters(self, model) -> Optional[Dict]:
        """
        Calculate shale parameters from data (synchronous).

        v2.1 Improvements:
        - Supports 3 selection modes: fixed_threshold, quantile, stability_sweep
        - Enriched result with shale_stats and sweep_summary
        """
        if model.las_data is None:
            return None

        data = model.las_data.copy()

        # Apply Per-Formation filter
        if (
            model.analysis_mode == "Per-Formation"
            and model.selected_formations
            and model.formation_tops
        ):
            data = model.formation_tops.filter_by_formations(
                data, model.selected_formations, "DEPTH"
            )

        if len(data) == 0:
            return self._fallback_result("no_data")

        # Get curve mappings
        gr_curve = model.curve_mapping.get("GR", "GR")
        rhob_curve = model.curve_mapping.get("RHOB", "RHOB")
        nphi_curve = model.curve_mapping.get("NPHI", "NPHI")
        dt_curve = model.curve_mapping.get("DT", "DT")

        if gr_curve == "None" or gr_curve not in data.columns:
            return self._fallback_result("no_gr")

        try:
            # Compute GR baseline
            if model.vsh_baseline_method == "Custom (Manual)":
                gr_min = model.gr_min_manual
                gr_max = model.gr_max_manual
            else:
                stats_util = StatisticsUtils(data)
                gr_min, gr_max = stats_util.estimate_gr_baseline(gr_curve)

            # Compute VSH
            calc = PetrophysicsCalculator(data)
            vsh_methods_selected = model.vsh_methods or ["Linear"]
            method_map = {
                "Linear": "linear",
                "Larionov Tertiary": "larionov_tertiary",
                "Larionov Older": "larionov_older",
            }
            methods_to_calc = [
                method_map[m] for m in vsh_methods_selected if m in method_map
            ] or ["linear"]

            calc.calculate_all_vshale(gr_curve, gr_min, gr_max, methods_to_calc)
            vsh_ref, vsh_method_used = self._get_vsh_reference(
                calc, methods_to_calc, data, gr_curve
            )

            # Get model params with defaults for backward compatibility
            selection_mode = getattr(model, "shale_selection_mode", "fixed_threshold")
            min_points = getattr(model, "shale_min_points", 50)
            use_gating = getattr(model, "shale_gate_logs", True)
            use_iqr = getattr(model, "shale_iqr_filter", True)

            # Build params dict for helper functions
            params = {
                "use_gating": use_gating,
                "use_iqr": use_iqr,
                "min_points": min_points,
                "rhob_curve": rhob_curve,
                "nphi_curve": nphi_curve,
                "dt_curve": dt_curve,
            }

            # === SELECTION MODE DISPATCH ===
            if selection_mode == "quantile":
                quantile = getattr(model, "shale_vsh_quantile", 0.90)
                threshold = np.nanquantile(vsh_ref, quantile)
                if np.isnan(threshold):
                    threshold = 0.80
                mode_info = f"quantile({quantile:.2f})"
                sweep_summary = None

            elif selection_mode == "stability_sweep":
                tmin = getattr(model, "shale_sweep_tmin", 0.65)
                tmax = getattr(model, "shale_sweep_tmax", 0.95)
                step = getattr(model, "shale_sweep_step", 0.02)
                threshold, sweep_summary = self._stability_sweep(
                    data, vsh_ref, params, tmin, tmax, step, min_points
                )
                mode_info = f"sweep({tmin:.2f}-{tmax:.2f})"
            else:  # fixed_threshold (default)
                threshold = getattr(model, "shale_vsh_threshold", 0.80)
                mode_info = "fixed"
                sweep_summary = None

            # Build and apply shale mask
            shale_mask, points_before = self._build_shale_mask(vsh_ref, threshold)
            filtered_mask, points_after = self._apply_gates_and_filters(
                data, shale_mask, params
            )

            # Check minimum points
            if points_after < min_points:
                result = self._fallback_result("insufficient_points")
                result.update(
                    {
                        "shale_selection_mode": selection_mode,
                        "shale_threshold_used": float(threshold),
                        "shale_points_before": points_before,
                        "shale_points_after": points_after,
                        "vsh_method_used": vsh_method_used,
                        "gr_min": float(gr_min),
                        "gr_max": float(gr_max),
                    }
                )
                return result

            # Calculate shale parameters with robust median
            rho_shale, nphi_shale, dt_shale = self._calculate_medians(
                data, filtered_mask, params
            )

            # Calculate shale zone statistics
            shale_stats = self._calculate_shale_stats(
                data, filtered_mask, params, gr_curve, vsh_ref
            )

            # Build result
            result = {
                "rho_shale": float(rho_shale),
                "nphi_shale": float(nphi_shale),
                "dt_shale": float(dt_shale),
                "gr_min": float(gr_min),
                "gr_max": float(gr_max),
                "shale_selection_mode": selection_mode,
                "shale_threshold_used": float(threshold),
                "shale_points_before": points_before,
                "shale_points_after": points_after,
                "vsh_method_used": vsh_method_used,
                "method": "statistical_vsh",
                "shale_stats": shale_stats,
            }

            if sweep_summary:
                result["sweep_summary"] = sweep_summary

            return result

        except Exception as e:
            result = self._fallback_result("error")
            result["error"] = str(e)
            return result

    def _fallback_result(self, reason: str) -> Dict:
        """Return default fallback result."""
        return {
            "method": "fallback",
            "rho_shale": 2.45,
            "nphi_shale": 0.35,
            "dt_shale": 100.0,
            "shale_points_before": 0,
            "shale_points_after": 0,
            "shale_threshold_used": 0.0,
            "vsh_method_used": reason,
            "shale_selection_mode": "fallback",
        }

    @staticmethod
    def _get_vsh_reference(calc, methods_to_calc, data, gr_curve):
        """Get VSH reference series for shale masking (see pipeline.vsh_reference)."""
        return vsh_reference(calc, methods_to_calc, data, gr_curve)

    def _build_shale_mask(self, vsh_ref, threshold: float) -> Tuple[pd.Series, int]:
        """Build initial shale mask from VSH and threshold."""
        mask = (vsh_ref >= threshold) & vsh_ref.notna()
        return mask, int(mask.sum())

    def _apply_gates_and_filters(self, data, mask, params) -> Tuple[pd.Series, int]:
        """Apply log gating to shale mask."""
        filtered = mask.copy()
        if params["use_gating"]:
            if params["rhob_curve"] != "None" and params["rhob_curve"] in data.columns:
                filtered &= data[params["rhob_curve"]].between(2.2, 2.7)
            if params["nphi_curve"] != "None" and params["nphi_curve"] in data.columns:
                filtered &= data[params["nphi_curve"]].between(0.15, 0.5)
            if params["dt_curve"] != "None" and params["dt_curve"] in data.columns:
                filtered &= data[params["dt_curve"]].between(70, 150)
        return filtered, int(filtered.sum())

    def _robust_median(self, series, use_iqr: bool = True) -> float:
        """Calculate median with optional IQR outlier filtering."""
        s = series.dropna()
        if len(s) == 0:
            return np.nan
        if use_iqr and len(s) >= 5:
            q1, q3 = s.quantile(0.25), s.quantile(0.75)
            iqr = q3 - q1
            s = s[(s >= q1 - 1.5 * iqr) & (s <= q3 + 1.5 * iqr)]
        return float(s.median()) if len(s) > 0 else np.nan

    def _calculate_medians(self, data, mask, params) -> Tuple[float, float, float]:
        """Calculate shale parameters from masked data."""
        use_iqr = params["use_iqr"]

        rho = 2.45
        if params["rhob_curve"] != "None" and params["rhob_curve"] in data.columns:
            val = self._robust_median(data.loc[mask, params["rhob_curve"]], use_iqr)
            if not np.isnan(val):
                rho = np.clip(val, 2.2, 2.7)

        nphi = 0.35
        if params["nphi_curve"] != "None" and params["nphi_curve"] in data.columns:
            val = self._robust_median(data.loc[mask, params["nphi_curve"]], use_iqr)
            if not np.isnan(val):
                nphi = np.clip(val, 0.15, 0.5)

        dt = 100.0
        if params["dt_curve"] != "None" and params["dt_curve"] in data.columns:
            val = self._robust_median(data.loc[mask, params["dt_curve"]], use_iqr)
            if not np.isnan(val):
                dt = np.clip(val, 70, 150)

        return rho, nphi, dt

    def _calculate_shale_stats(self, data, mask, params, gr_curve, vsh_ref) -> Dict:
        """Calculate statistics for shale zone."""
        stats = {}
        curves = [
            ("GR", gr_curve),
            ("RHOB", params["rhob_curve"]),
            ("NPHI", params["nphi_curve"]),
            ("DT", params["dt_curve"]),
            ("VSH", None),  # Special case
        ]

        for name, curve in curves:
            if name == "VSH":
                s = vsh_ref[mask].dropna()
            elif curve and curve != "None" and curve in data.columns:
                s = data.loc[mask, curve].dropna()
            else:
                continue

            if len(s) > 0:
                stats[name] = {
                    "mean": float(np.nanmean(s)),
                    "median": float(np.nanmedian(s)),
                    "std": float(np.nanstd(s)),
                    "min": float(np.nanmin(s)),
                    "max": float(np.nanmax(s)),
                    "count": len(s),
                }

        return stats

    def _stability_sweep(
        self, data, vsh_ref, params, tmin, tmax, step, min_points
    ) -> Tuple[float, list]:
        """
        Sweep threshold candidates and select most stable.
        Returns (best_threshold, sweep_summary).
        """
        thresholds = np.arange(tmin, tmax + step / 2, step)
        sweep_results = []

        for t in thresholds:
            mask, _ = self._build_shale_mask(vsh_ref, t)
            filtered, n_points = self._apply_gates_and_filters(data, mask, params)

            if n_points >= min_points:
                rho, nphi, dt = self._calculate_medians(data, filtered, params)
                sweep_results.append(
                    {
                        "threshold": float(t),
                        "n_points": n_points,
                        "rho": rho,
                        "nphi": nphi,
                        "dt": dt,
                    }
                )

        if not sweep_results:
            # Fallback to fixed
            return 0.80, [{"threshold": 0.80, "n_points": 0, "note": "fallback"}]

        # Calculate stability scores
        for i, r in enumerate(sweep_results):
            score = 0.0
            count = 0

            for key in ["rho", "nphi", "dt"]:
                vals = [sr[key] for sr in sweep_results if not np.isnan(sr[key])]
                if len(vals) < 2:
                    continue

                # Normalize by range
                vrange = max(vals) - min(vals)
                if vrange < 1e-6:
                    continue

                # Local variation
                if i > 0 and i < len(sweep_results) - 1:
                    diff = abs(r[key] - sweep_results[i - 1][key]) + abs(
                        sweep_results[i + 1][key] - r[key]
                    )
                elif i == 0 and len(sweep_results) > 1:
                    diff = abs(sweep_results[1][key] - r[key])
                elif i == len(sweep_results) - 1 and len(sweep_results) > 1:
                    diff = abs(r[key] - sweep_results[-2][key])
                else:
                    diff = 0

                score += diff / vrange
                count += 1

            r["score"] = score / max(count, 1)

        # Select minimum score (most stable)
        best = min(sweep_results, key=lambda x: x["score"])

        # Return top 5 for summary
        sorted_results = sorted(sweep_results, key=lambda x: x["score"])[:5]

        return best["threshold"], sorted_results
