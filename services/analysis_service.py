"""
Analysis Service for Petrophyter PyQt
Wraps the petrophysics calculation logic for background execution.
"""

from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, QThreadPool
import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional
import traceback

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.petrophysics import PetrophysicsCalculator
from modules.statistics_utils import StatisticsUtils


class AnalysisSignals(QObject):
    """Signals for analysis worker."""

    started = pyqtSignal()
    progress = pyqtSignal(str, int)  # (message, percentage)
    completed = pyqtSignal(pd.DataFrame, dict)  # (results, summary)
    error = pyqtSignal(str)


class AnalysisWorker(QRunnable):
    """
    Worker for running petrophysics analysis in background thread.
    """

    def __init__(self, model):
        super().__init__()
        self.model = model
        self.signals = AnalysisSignals()

    def run(self):
        """Execute the analysis."""
        try:
            self.signals.started.emit()
            self.signals.progress.emit("Preparing data...", 5)

            data = self.model.las_data.copy()

            # Apply formation filter if Per-Formation mode
            analysis_mode = self.model.analysis_mode
            selected_formations = self.model.selected_formations

            if (
                analysis_mode == "Per-Formation"
                and selected_formations
                and self.model.formation_tops
            ):
                data = self.model.formation_tops.filter_by_formations(
                    data, selected_formations, "DEPTH"
                )

            if len(data) == 0:
                self.signals.error.emit("No data in selected formation(s)")
                return

            self.signals.progress.emit("Initializing calculator...", 10)

            # Initialize calculator
            calc = PetrophysicsCalculator(data)

            # Get curve mappings
            gr_curve = self.model.curve_mapping.get("GR", "GR")
            rhob_curve = self.model.curve_mapping.get("RHOB", "RHOB")
            nphi_curve = self.model.curve_mapping.get("NPHI", "NPHI")
            dt_curve = self.model.curve_mapping.get("DT", "DT")
            rt_curve = self.model.curve_mapping.get("RT", "RT")

            # Initialize statistics utility
            stats_util = StatisticsUtils(data)

            self.signals.progress.emit("Calculating VShale...", 20)

            # Calculate GR baselines
            if self.model.vsh_baseline_method == "Custom (Manual)":
                gr_min = self.model.gr_min_manual
                gr_max = self.model.gr_max_manual
            elif gr_curve and gr_curve != "None" and gr_curve in data.columns:
                gr_min, gr_max = stats_util.estimate_gr_baseline(gr_curve)
            else:
                gr_min, gr_max = 20, 120

            # Calculate Vshale
            vsh_methods_selected = self.model.vsh_methods
            if not vsh_methods_selected:
                vsh_methods_selected = ["Linear"]

            method_map = {
                "Linear": "linear",
                "Larionov Tertiary": "larionov_tertiary",
                "Larionov Older": "larionov_older",
            }
            methods_to_calc = [
                method_map[m] for m in vsh_methods_selected if m in method_map
            ]

            if gr_curve and gr_curve != "None" and gr_curve in data.columns:
                vsh_results = calc.calculate_all_vshale(
                    gr_curve, gr_min, gr_max, methods_to_calc
                )
                vsh = calc.results["VSH"]
            else:
                vsh = pd.Series([0.3] * len(data), index=data.index)
                calc.results["VSH"] = vsh

            self.signals.progress.emit("Calculating porosity...", 35)

            # Calculate porosities
            rho_matrix = self.model.rho_matrix
            rho_fluid = self.model.rho_fluid
            dt_matrix = self.model.dt_matrix
            dt_fluid = self.model.dt_fluid

            if rhob_curve and rhob_curve != "None" and rhob_curve in data.columns:
                phid = calc.calculate_porosity_density(
                    rhob_curve, rho_matrix, rho_fluid
                )

            if nphi_curve and nphi_curve != "None" and nphi_curve in data.columns:
                phin = calc.calculate_porosity_neutron(nphi_curve)

            if dt_curve and dt_curve != "None" and dt_curve in data.columns:
                phis = calc.calculate_porosity_sonic(dt_curve, dt_matrix, dt_fluid)

            # Total porosity (N-D crossplot)
            phit = calc.calculate_phit_neutron_density()

            self.signals.progress.emit("Calculating effective porosity...", 45)

            # Calculate all PHIE methods
            nphi_shale = self.model.nphi_shale
            rho_shale = self.model.rho_shale
            dt_shale = self.model.dt_shale

            # Gas correction parameters (v1.2)
            gas_correction = getattr(self.model, "gas_correction_enabled", False)
            gas_nphi_factor = getattr(self.model, "gas_nphi_factor", 0.30)
            gas_rhob_factor = getattr(self.model, "gas_rhob_factor", 0.15)

            # Primary PHIE method
            primary_phie_method = getattr(self.model, "primary_phie_method", "PHIE_DN")

            calc.calculate_all_phie(
                vsh=vsh,
                nphi_shale=nphi_shale,
                rhob_shale=rho_shale,
                dt_shale=dt_shale,
                rho_matrix=rho_matrix,
                rho_fluid=rho_fluid,
                dt_matrix=dt_matrix,
                dt_fluid=dt_fluid,
                gas_correction=gas_correction,
                gas_nphi_factor=gas_nphi_factor,
                gas_rhob_factor=gas_rhob_factor,
                primary_method=primary_phie_method,
            )

            self.signals.progress.emit("Calculating water saturation...", 55)

            # Water saturation
            rw = self.model.rw
            rsh = self.model.rsh
            a = self.model.a
            m = self.model.m
            n = self.model.n

            # Data-driven Rw/Rsh estimation if needed
            if (
                rw <= 0.01
                and rt_curve
                and rt_curve != "None"
                and rt_curve in data.columns
            ):
                rw_est = stats_util.estimate_rw_from_rt_water_zone(
                    rt_curve, "PHIE", 0.15, a, m
                )
                if rw_est:
                    rw = rw_est

            if rt_curve and rt_curve != "None" and rt_curve in data.columns:
                rsh_est = stats_util.estimate_rsh(rt_curve, vsh)
                if rsh_est:
                    rsh = rsh_est

            phie = calc.results.get(
                "PHIE", pd.Series([0.15] * len(data), index=data.index)
            )

            if rt_curve and rt_curve != "None" and rt_curve in data.columns:
                # Retrieve selected models (defaults if missing)
                selected_methods = getattr(self.model, "sw_methods", ["Simandoux"])
                primary_method = getattr(self.model, "sw_primary_method", "Simandoux")

                # Retrieve extra params
                qv = getattr(self.model, "ws_qv", 0.2)
                B = getattr(self.model, "ws_b", 1.0)
                swb = getattr(self.model, "dw_swb", 0.1)
                rwb = getattr(self.model, "dw_rwb", 0.2)

                # Calculate selected
                if "Archie" in selected_methods:
                    calc.calculate_sw_archie(rt_curve, phie, rw, a, m, n)
                if "Indonesian" in selected_methods:
                    calc.calculate_sw_indonesian(rt_curve, phie, vsh, rw, rsh, a, m, n)
                if "Simandoux" in selected_methods:
                    calc.calculate_sw_simandoux(rt_curve, phie, vsh, rw, rsh, a, m, n)
                if "Waxman-Smits" in selected_methods:
                    calc.calculate_sw_waxman_smits(rt_curve, phie, rw, a, m, n, qv, B)
                if "Dual-Water" in selected_methods:
                    calc.calculate_sw_dual_water(rt_curve, phie, rw, a, m, n, swb, rwb)

                # Set Primary SW
                # Method Name -> Column Name map
                method_to_col = {
                    "Archie": "SW_ARCHIE",
                    "Indonesian": "SW_INDO",
                    "Simandoux": "SW_SIMAN",
                    "Waxman-Smits": "SW_WS",
                    "Dual-Water": "SW_DW",
                }

                primary_col = method_to_col.get(primary_method, "SW_SIMAN")

                # Check if primary result exists
                if primary_col in calc.results.columns:
                    calc.results["SW"] = calc.results[primary_col]
                    # Also set for internal use in this function scope if needed
                    sw_primary_series = calc.results[primary_col]
                else:
                    # Fallback
                    available = [
                        c for c in method_to_col.values() if c in calc.results.columns
                    ]
                    if available:
                        calc.results["SW"] = calc.results[available[0]]
                        sw_primary_series = calc.results[available[0]]
                    else:
                        calc.results["SW"] = pd.Series(
                            [1.0] * len(data), index=data.index
                        )
                        sw_primary_series = calc.results["SW"]

            self.signals.progress.emit("Calculating Swirr...", 65)

            # Calculate Swirr
            swirr_method = self.model.swirr_method
            k_buckles = self.model.k_buckles

            # Use Primary SW for Swirr logic (if it uses Sw input)
            sw_for_swirr = calc.results.get(
                "SW", pd.Series([0.5] * len(data), index=data.index)
            )

            if swirr_method == "Hierarchical (Recommended)":
                swirr, swirr_info = calc.calculate_swirr_hierarchical(
                    phie=phie, sw=sw_for_swirr, vsh=vsh, k_buckles=k_buckles
                )
                swirr_actual_method = swirr_info["method"]
            else:
                method_map = {
                    "Buckles Number": ["buckles"],
                    "Clean Zone": ["clean_zone"],
                    "Statistical": ["statistical"],
                    "All Methods": ["buckles", "clean_zone", "statistical"],
                }
                swirr_methods_to_use = method_map.get(swirr_method, ["buckles"])

                swirr_results = calc.calculate_all_swirr(
                    phie=phie,
                    sw=sw_for_swirr,
                    vsh=vsh,
                    k_buckles=k_buckles,
                    vsh_threshold=0.2,
                    methods=swirr_methods_to_use,
                )
                swirr_actual_method = swirr_method

            swirr = calc.results.get(
                "SWIRR", pd.Series([0.2] * len(data), index=data.index)
            )
            swirr_mean = swirr.mean()

            self.signals.progress.emit("Calculating permeability...", 75)

            # Permeability
            C = self.model.perm_C
            P = self.model.perm_P
            Q = self.model.perm_Q

            perm_timur = calc.calculate_permeability_timur(phie, swirr)
            perm_wr = calc.calculate_permeability_wyllie_rose(phie, swirr, C, P, Q)

            # Flow Unit Classification
            flow_units = calc.classify_flow_units(perm_timur)
            perm_flags = calc.get_permeability_quality_flags(perm_timur, swirr, phie)

            self.signals.progress.emit("Calculating net pay...", 85)

            # Net pay calculations
            vsh_cutoff = self.model.vsh_cutoff
            phi_cutoff = self.model.phi_cutoff
            sw_cutoff = self.model.sw_cutoff

            sw_for_pay = calc.results.get(
                "SW", pd.Series([1.0] * len(data), index=data.index)
            )
            summary = calc.calculate_net_pay(
                vsh, phie, sw_for_pay, vsh_cutoff, phi_cutoff, sw_cutoff
            )

            self.signals.progress.emit("Calculating HCPV...", 88)

            # Calculate HCPV
            # Use primary SW (already set in calc.results['SW'])
            hcpv_results = calc.calculate_hcpv(
                phie=phie,
                sw=sw_for_pay,
                depth=data["DEPTH"],
                net_res_flag=calc.results.get("NET_RES_FLAG"),
                net_pay_flag=calc.results.get("NET_PAY_FLAG"),
            )

            self.signals.progress.emit("Finalizing results...", 95)

            # Store results
            results = calc.export_results()
            summary["gr_min"] = gr_min
            summary["gr_max"] = gr_max
            summary["rw"] = rw
            summary["rsh"] = rsh
            summary["swirr_method"] = swirr_method
            summary["swirr_mean"] = swirr_mean
            summary["analysis_mode"] = analysis_mode
            summary["selected_formations"] = selected_formations
            summary["data_points"] = len(data)

            # Add HCPV summary statistics
            if "HCPV_CUM" in hcpv_results:
                summary["hcpv_gross"] = (
                    float(hcpv_results["HCPV_CUM"].iloc[-1])
                    if len(hcpv_results["HCPV_CUM"]) > 0
                    else 0.0
                )
                summary["hcpv_net_res"] = (
                    float(hcpv_results["HCPV_CUM_NET_RES"].iloc[-1])
                    if len(hcpv_results["HCPV_CUM_NET_RES"]) > 0
                    else 0.0
                )
                summary["hcpv_net_pay"] = (
                    float(hcpv_results["HCPV_CUM_NET_PAY"].iloc[-1])
                    if len(hcpv_results["HCPV_CUM_NET_PAY"]) > 0
                    else 0.0
                )

            self.signals.progress.emit("Analysis complete!", 100)
            self.signals.completed.emit(results, summary)

        except Exception as e:
            self.signals.error.emit(
                f"Analysis failed: {str(e)}\n{traceback.format_exc()}"
            )


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
        # print(f"[DEBUG AnalysisService] _on_completed called")
        # print(f"[DEBUG AnalysisService] results.shape = {results.shape}")
        # print(f"[DEBUG AnalysisService] Emitting completed signal...")
        self.completed.emit(results, summary)
        # print(f"[DEBUG AnalysisService] Signal emitted")

    def calculate_rw_rsh(self, model) -> Optional[Dict]:
        """Calculate Rw and Rsh from log data (synchronous)."""
        if model.las_data is None:
            return None

        data = model.las_data.copy()

        # Apply formation filter if applicable
        if (
            model.analysis_mode == "Per-Formation"
            and model.selected_formations
            and model.formation_tops
        ):
            data = model.formation_tops.filter_by_formations(
                data, model.selected_formations, "DEPTH"
            )

        if len(data) == 0:
            return None

        gr_curve = model.curve_mapping.get("GR", "GR")
        rt_curve = model.curve_mapping.get("RT", "RT")

        if rt_curve == "None" or rt_curve not in data.columns:
            return None

        stats_util = StatisticsUtils(data)

        try:
            a = model.a
            m = model.m

            rw_est = stats_util.estimate_rw_from_rt_water_zone(
                rt_curve, "PHIT", 0.15, a, m
            )
            if not rw_est:
                rw_est = 0.05

            vsh = None
            if gr_curve and gr_curve != "None" and gr_curve in data.columns:
                gr = data[gr_curve]
                gr_min = np.percentile(gr.dropna(), 5)
                gr_max = np.percentile(gr.dropna(), 95)
                vsh = (gr - gr_min) / (gr_max - gr_min)
                vsh = np.clip(vsh, 0, 1)

            rsh_est = stats_util.estimate_rsh(
                rt_curve, vsh, gr_curve if gr_curve != "None" else None
            )
            if not rsh_est:
                rsh_est = 5.0

            return {"rw": round(rw_est, 4), "rsh": round(rsh_est, 2)}

        except Exception:
            return None

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

    def _get_vsh_reference(self, calc, methods_to_calc, data, gr_curve):
        """Get VSH reference series for shale masking."""
        key_map = {
            "linear": "VSH_LINEAR",
            "larionov_tertiary": "VSH_LARIO_TERT",
            "larionov_older": "VSH_LARIO_OLD",
        }

        if len(methods_to_calc) == 1:
            key = key_map.get(methods_to_calc[0], "VSH_LINEAR")
            vsh_ref = calc.results.get(
                key,
                calc.results.get("VSH", pd.Series([0.5] * len(data), index=data.index)),
            )
            return vsh_ref, methods_to_calc[0]
        else:
            vsh_arrays = [
                calc.results[key_map.get(m, "VSH")]
                for m in methods_to_calc
                if key_map.get(m, "VSH") in calc.results.columns
            ]
            if vsh_arrays:
                vsh_ref = pd.concat(vsh_arrays, axis=1).max(axis=1)
            else:
                vsh_ref = calc.results.get(
                    "VSH", pd.Series([0.5] * len(data), index=data.index)
                )
            return vsh_ref, "max(" + ",".join(methods_to_calc) + ")"

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
