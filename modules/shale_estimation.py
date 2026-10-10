"""
Shale-point estimation (density, neutron, sonic of the shale), pure and Qt-free.

Lifted out of ``AnalysisService.calculate_shale_parameters`` so the pipeline can
estimate the shale point per well and per zone (parameter scopes, AUTO mode).
Three selection modes pick the VSH threshold: ``fixed_threshold``,
``quantile`` and ``stability_sweep``.
"""

from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

SHALE_PARAMS = ("rho_shale", "dt_shale", "nphi_shale")

# Settings read from the params dict, with the defaults the GUI model ships.
SHALE_SETTING_DEFAULTS = {
    "shale_selection_mode": "fixed_threshold",
    "shale_min_points": 50,
    "shale_gate_logs": True,
    "shale_iqr_filter": True,
    "shale_vsh_quantile": 0.90,
    "shale_sweep_tmin": 0.65,
    "shale_sweep_tmax": 0.95,
    "shale_sweep_step": 0.02,
    "shale_vsh_threshold": 0.80,
}


def fallback_result(reason: str) -> Dict:
    """Default shale point, used when no estimate can be made."""
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


def is_estimate(result: Optional[Dict]) -> bool:
    """Whether ``result`` is a real estimate (not a fallback)."""
    return bool(result) and result.get("method") != "fallback"


def build_shale_mask(vsh_ref, threshold: float) -> Tuple[pd.Series, int]:
    """Initial shale mask from VSH and threshold."""
    mask = (vsh_ref >= threshold) & vsh_ref.notna()
    return mask, int(mask.sum())


def apply_gates_and_filters(data, mask, params) -> Tuple[pd.Series, int]:
    """Apply log gating to the shale mask."""
    filtered = mask.copy()
    if params["use_gating"]:
        if params["rhob_curve"] != "None" and params["rhob_curve"] in data.columns:
            filtered &= data[params["rhob_curve"]].between(2.2, 2.7)
        if params["nphi_curve"] != "None" and params["nphi_curve"] in data.columns:
            filtered &= data[params["nphi_curve"]].between(0.15, 0.5)
        if params["dt_curve"] != "None" and params["dt_curve"] in data.columns:
            filtered &= data[params["dt_curve"]].between(70, 150)
    return filtered, int(filtered.sum())


def robust_median(series, use_iqr: bool = True) -> float:
    """Median with optional IQR outlier filtering."""
    s = series.dropna()
    if len(s) == 0:
        return np.nan
    if use_iqr and len(s) >= 5:
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        s = s[(s >= q1 - 1.5 * iqr) & (s <= q3 + 1.5 * iqr)]
    return float(s.median()) if len(s) > 0 else np.nan


def calculate_medians(data, mask, params) -> Tuple[float, float, float]:
    """Shale ``(rho, nphi, dt)`` from the masked data."""
    use_iqr = params["use_iqr"]

    rho = 2.45
    if params["rhob_curve"] != "None" and params["rhob_curve"] in data.columns:
        val = robust_median(data.loc[mask, params["rhob_curve"]], use_iqr)
        if not np.isnan(val):
            rho = np.clip(val, 2.2, 2.7)

    nphi = 0.35
    if params["nphi_curve"] != "None" and params["nphi_curve"] in data.columns:
        val = robust_median(data.loc[mask, params["nphi_curve"]], use_iqr)
        if not np.isnan(val):
            nphi = np.clip(val, 0.15, 0.5)

    dt = 100.0
    if params["dt_curve"] != "None" and params["dt_curve"] in data.columns:
        val = robust_median(data.loc[mask, params["dt_curve"]], use_iqr)
        if not np.isnan(val):
            dt = np.clip(val, 70, 150)

    return rho, nphi, dt


def calculate_shale_stats(data, mask, params, gr_curve, vsh_ref) -> Dict:
    """Statistics of the shale zone."""
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


def stability_sweep(data, vsh_ref, params, tmin, tmax, step, min_points) -> Tuple[float, list]:
    """Sweep threshold candidates and select the most stable.

    Returns ``(best_threshold, sweep_summary)``.
    """
    thresholds = np.arange(tmin, tmax + step / 2, step)
    sweep_results = []

    for t in thresholds:
        mask, _ = build_shale_mask(vsh_ref, t)
        filtered, n_points = apply_gates_and_filters(data, mask, params)

        if n_points >= min_points:
            rho, nphi, dt = calculate_medians(data, filtered, params)
            sweep_results.append(
                {"threshold": float(t), "n_points": n_points, "rho": rho, "nphi": nphi, "dt": dt}
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


def estimate_shale_point(
    data: pd.DataFrame,
    curve_mapping: Dict[str, str],
    params: Dict,
    gr_min: Optional[float] = None,
    gr_max: Optional[float] = None,
) -> Dict:
    """Estimate the shale point (rho, nphi, dt) from the samples in ``data``.

    ``gr_min`` / ``gr_max`` give the GR baseline; when omitted it follows
    ``params`` (manual values, or the statistical estimate on ``data``).
    Returns the result dict (also for fallbacks: ``method == "fallback"``).
    """
    # Imported here: modules.pipeline imports this module.
    from modules.pipeline import VSH_METHOD_MAP, vsh_reference
    from modules.petrophysics import PetrophysicsCalculator
    from modules.statistics_utils import StatisticsUtils

    def setting(key):
        return params.get(key, SHALE_SETTING_DEFAULTS[key])

    if data is None or len(data) == 0:
        return fallback_result("no_data")

    gr_curve = curve_mapping.get("GR", "GR")
    rhob_curve = curve_mapping.get("RHOB", "RHOB")
    nphi_curve = curve_mapping.get("NPHI", "NPHI")
    dt_curve = curve_mapping.get("DT", "DT")

    if gr_curve == "None" or gr_curve not in data.columns:
        return fallback_result("no_gr")

    try:
        if gr_min is None or gr_max is None:
            if params.get("vsh_baseline_method", "Statistically (Auto)") == "Custom (Manual)":
                gr_min = params.get("gr_min_manual", 20.0)
                gr_max = params.get("gr_max_manual", 120.0)
            else:
                gr_min, gr_max = StatisticsUtils(data).estimate_gr_baseline(gr_curve)

        calc = PetrophysicsCalculator(data)
        vsh_methods_selected = params.get("vsh_methods") or ["Linear"]
        methods_to_calc = [
            VSH_METHOD_MAP[m] for m in vsh_methods_selected if m in VSH_METHOD_MAP
        ] or ["linear"]

        calc.calculate_all_vshale(gr_curve, gr_min, gr_max, methods_to_calc)
        vsh_ref, vsh_method_used = vsh_reference(calc, methods_to_calc, data, gr_curve)

        selection_mode = setting("shale_selection_mode")
        min_points = setting("shale_min_points")

        mask_params = {
            "use_gating": setting("shale_gate_logs"),
            "use_iqr": setting("shale_iqr_filter"),
            "min_points": min_points,
            "rhob_curve": rhob_curve,
            "nphi_curve": nphi_curve,
            "dt_curve": dt_curve,
        }

        if selection_mode == "quantile":
            quantile = setting("shale_vsh_quantile")
            threshold = np.nanquantile(vsh_ref, quantile)
            if np.isnan(threshold):
                threshold = 0.80
            sweep_summary = None
        elif selection_mode == "stability_sweep":
            tmin = setting("shale_sweep_tmin")
            tmax = setting("shale_sweep_tmax")
            step = setting("shale_sweep_step")
            threshold, sweep_summary = stability_sweep(
                data, vsh_ref, mask_params, tmin, tmax, step, min_points
            )
        else:  # fixed_threshold (default)
            threshold = setting("shale_vsh_threshold")
            sweep_summary = None

        shale_mask, points_before = build_shale_mask(vsh_ref, threshold)
        filtered_mask, points_after = apply_gates_and_filters(data, shale_mask, mask_params)

        if points_after < min_points:
            result = fallback_result("insufficient_points")
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

        rho_shale, nphi_shale, dt_shale = calculate_medians(data, filtered_mask, mask_params)
        shale_stats = calculate_shale_stats(data, filtered_mask, mask_params, gr_curve, vsh_ref)

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
        result = fallback_result("error")
        result["error"] = str(e)
        return result
