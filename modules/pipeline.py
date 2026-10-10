"""
Petrophysics analysis pipeline.

Pure, Qt-free entry point that turns a log DataFrame plus a plain parameter
dict into a results DataFrame and a summary dict. The GUI worker in
``services/analysis_service.py`` is a thin adapter around :func:`run_pipeline`;
Monte Carlo, ML, scripts, and tests call it directly.

Contract:
- ``data`` has a numeric ``DEPTH`` column in feet (see ADR 0010).
- ``params`` keys follow :data:`PARAM_DEFAULTS`; missing keys take defaults.
- Never imports PyQt6, directly or indirectly.
"""

from typing import Callable, Dict, Optional, Tuple

import pandas as pd

from modules.petrophysics import PetrophysicsCalculator
from modules.statistics_utils import StatisticsUtils, get_default_matrix_parameters

ProgressFn = Callable[[str, int], None]

# Analysis parameters read by the pipeline, with the defaults the GUI ships.
# Keys match the AppModel attribute names and the session-file fields.
PARAM_DEFAULTS: Dict[str, object] = {
    "analysis_mode": "Whole Well",
    "selected_formations": [],
    "vsh_baseline_method": "Statistically (Auto)",
    "gr_min_manual": 20.0,
    "gr_max_manual": 120.0,
    "vsh_methods": ["Linear"],
    "rho_matrix": 2.65,
    "dt_matrix": 55.5,
    "nphi_matrix": None,
    "rho_fluid": 1.0,
    "dt_fluid": 189.0,
    "rho_shale": 2.45,
    "dt_shale": 100.0,
    "nphi_shale": 0.35,
    "primary_phie_method": "PHIE_DN",
    "lithology_preset": "Sandstone (Humble)",
    "a": 0.62,
    "m": 2.15,
    "n": 2.0,
    "rw": 0.05,
    "rsh": 5.0,
    "rw_mode": "manual",
    "rsh_mode": "auto",
    "perm_C": 8581.0,
    "perm_P": 4.4,
    "perm_Q": 2.0,
    "swirr_method": "Hierarchical (Recommended)",
    "k_buckles": 0.02,
    "vsh_cutoff": 0.4,
    "phi_cutoff": 0.08,
    "sw_cutoff": 0.6,
    "sw_methods": ["Simandoux"],
    "sw_primary_method": "Simandoux",
    "ws_qv": 0.2,
    "ws_b": 1.0,
    "dw_swb": 0.1,
    "dw_rwb": 0.2,
    "gas_correction_enabled": False,
    "gas_nphi_factor": 0.30,
    "gas_rhob_factor": 0.15,
}

VSH_METHOD_MAP = {
    "Linear": "linear",
    "Larionov Tertiary": "larionov_tertiary",
    "Larionov Older": "larionov_older",
}

VSH_COLUMN_MAP = {
    "linear": "VSH_LINEAR",
    "larionov_tertiary": "VSH_LARIO_TERT",
    "larionov_older": "VSH_LARIO_OLD",
}

SW_COLUMN_MAP = {
    "Archie": "SW_ARCHIE",
    "Indonesian": "SW_INDO",
    "Simandoux": "SW_SIMAN",
    "Waxman-Smits": "SW_WS",
    "Dual-Water": "SW_DW",
}

SWIRR_METHOD_MAP = {
    "Buckles Number": ["buckles"],
    "Clean Zone": ["clean_zone"],
    "Statistical": ["statistical"],
    "All Methods": ["buckles", "clean_zone", "statistical"],
}


class PipelineError(ValueError):
    """Raised for input conditions that make an analysis impossible."""


def resolve_nphi_matrix(params: Dict) -> float:
    """Explicit ``nphi_matrix`` wins; otherwise derive it from the lithology preset."""
    configured = params.get("nphi_matrix")
    if configured is not None:
        return configured
    preset = str(params.get("lithology_preset", "sandstone")).lower()
    if "dolomite" in preset:
        lithology = "dolomite"
    elif "carbonate" in preset or "limestone" in preset:
        lithology = "limestone"
    else:
        lithology = "sandstone"
    return get_default_matrix_parameters(lithology)["nphi_matrix"]


def vsh_reference(calc: PetrophysicsCalculator, methods, data: pd.DataFrame, gr_curve: str):
    """Return the VSH series used for shale masking and its label.

    One method: that method's column. Several: their row-wise maximum.
    """
    if len(methods) == 1:
        key = VSH_COLUMN_MAP.get(methods[0], "VSH_LINEAR")
        vsh_ref = calc.results.get(
            key,
            calc.results.get("VSH", pd.Series([0.5] * len(data), index=data.index)),
        )
        return vsh_ref, methods[0]

    vsh_arrays = [
        calc.results[VSH_COLUMN_MAP.get(m, "VSH")]
        for m in methods
        if VSH_COLUMN_MAP.get(m, "VSH") in calc.results.columns
    ]
    if vsh_arrays:
        vsh_ref = pd.concat(vsh_arrays, axis=1).max(axis=1)
    else:
        vsh_ref = calc.results.get("VSH", pd.Series([0.5] * len(data), index=data.index))
    return vsh_ref, "max(" + ",".join(methods) + ")"


def _has(curve: Optional[str], data: pd.DataFrame) -> bool:
    return bool(curve and curve != "None" and curve in data.columns)


AUTO_UNAVAILABLE = "manual (auto estimate unavailable)"


def _compute_vsh(calc, stats_util, data, curve_mapping, p, warnings):
    """GR baseline and reference VSH, shared by the pipeline and Rw/Rsh estimation.

    Also sets the ``VSH`` result column to the series used downstream (with
    several methods that is the row-wise maximum, not the first method).
    """
    gr_curve = curve_mapping.get("GR", "GR")
    has_gr = _has(gr_curve, data)
    if p["vsh_baseline_method"] == "Custom (Manual)":
        gr_min, gr_max = p["gr_min_manual"], p["gr_max_manual"]
    elif has_gr:
        gr_min, gr_max = stats_util.estimate_gr_baseline(gr_curve)
    else:
        gr_min, gr_max = 20, 120

    vsh_selected = p["vsh_methods"] or ["Linear"]
    methods_to_calc = [VSH_METHOD_MAP[m] for m in vsh_selected if m in VSH_METHOD_MAP] or ["linear"]

    if has_gr:
        calc.calculate_all_vshale(gr_curve, gr_min, gr_max, methods_to_calc)
        vsh, _ = vsh_reference(calc, methods_to_calc, data, gr_curve)
        calc.results["VSH"] = vsh
    else:
        vsh = pd.Series([0.3] * len(data), index=data.index)
        calc.results["VSH"] = vsh
        warnings.append("VSH defaulted to 0.3 because no GR curve was available.")
    return vsh, gr_min, gr_max


def _compute_porosity(calc, vsh, data, curve_mapping, p, warnings):
    """Density, neutron and sonic porosity, PHIT and PHIE (results land in ``calc``)."""
    rhob_curve = curve_mapping.get("RHOB", "RHOB")
    nphi_curve = curve_mapping.get("NPHI", "NPHI")
    dt_curve = curve_mapping.get("DT", "DT")
    has_density = _has(rhob_curve, data)
    has_neutron = _has(nphi_curve, data)
    has_sonic = _has(dt_curve, data)
    rho_matrix, rho_fluid = p["rho_matrix"], p["rho_fluid"]
    dt_matrix, dt_fluid = p["dt_matrix"], p["dt_fluid"]

    if has_neutron and data[nphi_curve].median() > 1.0:
        warnings.append(
            f"NPHI curve {nphi_curve} has a median above 1.0; it looks like percent, "
            "not fractional porosity (v/v). Porosity and Sw results will be wrong."
        )

    if has_density:
        calc.calculate_porosity_density(rhob_curve, rho_matrix, rho_fluid)
    if has_neutron:
        calc.calculate_porosity_neutron(nphi_curve, resolve_nphi_matrix(p))
    if has_sonic:
        calc.calculate_porosity_sonic(dt_curve, dt_matrix, dt_fluid)
    if has_density or has_neutron:
        calc.calculate_phit_neutron_density()
    else:
        warnings.append("PHIT was not calculated because no RHOB or NPHI curve was available.")

    calc.calculate_all_phie(
        vsh=vsh,
        nphi_shale=p["nphi_shale"],
        rhob_shale=p["rho_shale"],
        dt_shale=p["dt_shale"],
        rho_matrix=rho_matrix,
        rho_fluid=rho_fluid,
        dt_matrix=dt_matrix,
        dt_fluid=dt_fluid,
        gas_correction=p["gas_correction_enabled"],
        gas_nphi_factor=p["gas_nphi_factor"],
        gas_rhob_factor=p["gas_rhob_factor"],
        primary_method=p["primary_phie_method"],
    )


def _auto_rw(stats_util, calc, vsh, rt_curve, p):
    """Rwa-method Rw on PHIE (PHIT if PHIE is absent) and the reference VSH, or None."""
    phi = calc.results.get("PHIE")
    if phi is None or not phi.notna().any():
        phi = calc.results.get("PHIT")
    if phi is None:
        return None
    rw = stats_util.estimate_rw_from_rt_water_zone(
        rt_curve, phi, 0.15, p["a"], p["m"], vsh_series=vsh
    )
    return rw or None


def _auto_rsh(stats_util, vsh, rt_curve):
    """Median RT of the shale zone (VSH > 0.8), or None when there is none."""
    return stats_util.estimate_rsh(rt_curve, vsh, unavailable_default=None) or None


def _unavailable_warning(name, entered):
    return (
        f"{name} could not be estimated automatically; using the entered "
        f"{name} of {entered}."
    )


def _resolve_rw_rsh(stats_util, calc, vsh, rt_curve, p, warnings):
    """Effective Rw/Rsh per ``rw_mode`` / ``rsh_mode``.

    Returns ``(rw, rsh, rw_source, rsh_source)``; a source is ``"manual"``,
    ``"auto"`` or :data:`AUTO_UNAVAILABLE`.
    """
    rw, rsh = p["rw"], p["rsh"]
    rw_source = rsh_source = "manual"
    if p["rw_mode"] == "auto":
        estimate = _auto_rw(stats_util, calc, vsh, rt_curve, p)
        if estimate is not None:
            rw, rw_source = estimate, "auto"
        else:
            rw_source = AUTO_UNAVAILABLE
            warnings.append(_unavailable_warning("Rw", rw))
    if p["rsh_mode"] == "auto":
        estimate = _auto_rsh(stats_util, vsh, rt_curve)
        if estimate is not None:
            rsh, rsh_source = estimate, "auto"
        else:
            rsh_source = AUTO_UNAVAILABLE
            warnings.append(_unavailable_warning("Rsh", rsh))
    return rw, rsh, rw_source, rsh_source


def estimate_rw_rsh(
    data: pd.DataFrame,
    curve_mapping: Dict[str, str],
    params: Dict,
    formation_tops=None,
) -> Optional[Dict]:
    """Rw and Rsh exactly as a pipeline run in auto mode would estimate them.

    Uses the same formation filter, GR baseline, VSH and porosity steps as
    :func:`run_pipeline`, then the same estimators, regardless of ``rw_mode`` /
    ``rsh_mode``. Returns ``None`` when there is no data or no RT curve,
    otherwise a dict with ``rw`` and ``rsh`` (the estimate, or the entered value
    when it is unavailable), ``rw_source``, ``rsh_source``, ``gr_min``,
    ``gr_max`` and ``warnings``.
    """
    if data is None:
        return None
    p = {**PARAM_DEFAULTS, **params, "rw_mode": "auto", "rsh_mode": "auto"}
    data = data.copy()
    if p["analysis_mode"] == "Per-Formation" and p["selected_formations"] and formation_tops:
        data = formation_tops.filter_by_formations(data, p["selected_formations"], "DEPTH")
    rt_curve = curve_mapping.get("RT", "RT")
    if len(data) == 0 or not _has(rt_curve, data):
        return None

    warnings = []
    calc = PetrophysicsCalculator(data)
    stats_util = StatisticsUtils(data)
    vsh, gr_min, gr_max = _compute_vsh(calc, stats_util, data, curve_mapping, p, warnings)
    _compute_porosity(calc, vsh, data, curve_mapping, p, warnings)
    rw, rsh, rw_source, rsh_source = _resolve_rw_rsh(
        stats_util, calc, vsh, rt_curve, p, warnings
    )
    return {
        "rw": rw,
        "rsh": rsh,
        "rw_source": rw_source,
        "rsh_source": rsh_source,
        "gr_min": gr_min,
        "gr_max": gr_max,
        "warnings": warnings,
    }


def run_pipeline(
    data: pd.DataFrame,
    curve_mapping: Dict[str, str],
    params: Dict,
    progress: Optional[ProgressFn] = None,
    formation_tops=None,
) -> Tuple[pd.DataFrame, Dict]:
    """Run the full deterministic evaluation.

    Args:
        data: Log DataFrame with a ``DEPTH`` column. Not mutated.
        curve_mapping: ``{"GR": mnemonic or "None", "RHOB": ..., "NPHI": ..., "DT": ..., "RT": ...}``.
        params: Plain dict; see :data:`PARAM_DEFAULTS`.
        progress: Optional ``callback(message, percent)``.
        formation_tops: ``FormationTops`` instance, needed only for Per-Formation mode.

    Returns:
        ``(results, summary)`` where ``results`` is the original curves plus the
        computed columns and ``summary`` holds net pay, HCPV, parameters, solver
        diagnostics, and warnings.

    Raises:
        PipelineError: no data, or nothing left after formation filtering.
    """
    emit = progress or (lambda message, percent: None)
    p = {**PARAM_DEFAULTS, **params}

    emit("Preparing data...", 5)
    if data is None:
        raise PipelineError("No data loaded. Please load a LAS file first.")

    data = data.copy()
    warnings = []

    analysis_mode = p["analysis_mode"]
    selected_formations = p["selected_formations"]
    if analysis_mode == "Per-Formation" and selected_formations and formation_tops:
        data = formation_tops.filter_by_formations(data, selected_formations, "DEPTH")
    if len(data) == 0:
        raise PipelineError("No data in selected formation(s)")

    emit("Initializing calculator...", 10)
    calc = PetrophysicsCalculator(data)
    stats_util = StatisticsUtils(data)

    gr_curve = curve_mapping.get("GR", "GR")
    rhob_curve = curve_mapping.get("RHOB", "RHOB")
    nphi_curve = curve_mapping.get("NPHI", "NPHI")
    dt_curve = curve_mapping.get("DT", "DT")
    rt_curve = curve_mapping.get("RT", "RT")

    has_gr = _has(gr_curve, data)
    has_density = _has(rhob_curve, data)
    has_neutron = _has(nphi_curve, data)
    has_sonic = _has(dt_curve, data)
    has_rt = _has(rt_curve, data)

    # ---- Shale volume -------------------------------------------------------
    emit("Calculating VShale...", 20)
    vsh, gr_min, gr_max = _compute_vsh(calc, stats_util, data, curve_mapping, p, warnings)

    # ---- Porosity -----------------------------------------------------------
    emit("Calculating porosity...", 35)
    _compute_porosity(calc, vsh, data, curve_mapping, p, warnings)
    emit("Calculating effective porosity...", 45)

    # ---- Water saturation ---------------------------------------------------
    emit("Calculating water saturation...", 55)
    a, m, n = p["a"], p["m"], p["n"]

    rw, rsh, rw_source, rsh_source = p["rw"], p["rsh"], "manual", "manual"
    if has_rt:
        rw, rsh, rw_source, rsh_source = _resolve_rw_rsh(
            stats_util, calc, vsh, rt_curve, p, warnings
        )

    phie = calc.results.get("PHIE")
    if phie is None:
        phie = pd.Series([0.15] * len(data), index=data.index)
        warnings.append("PHIE defaulted to 0.15 because no usable porosity method was available.")

    if has_rt:
        selected = p["sw_methods"]
        if "Archie" in selected:
            calc.calculate_sw_archie(rt_curve, phie, rw, a, m, n)
        if "Indonesian" in selected:
            calc.calculate_sw_indonesian(rt_curve, phie, vsh, rw, rsh, a, m, n)
        if "Simandoux" in selected:
            calc.calculate_sw_simandoux(rt_curve, phie, vsh, rw, rsh, a, m, n)
        if "Waxman-Smits" in selected:
            calc.calculate_sw_waxman_smits(rt_curve, phie, rw, a, m, n, p["ws_qv"], p["ws_b"])
        if "Dual-Water" in selected:
            calc.calculate_sw_dual_water(rt_curve, phie, rw, a, m, n, p["dw_swb"], p["dw_rwb"])

        primary_col = SW_COLUMN_MAP.get(p["sw_primary_method"], "SW_SIMAN")
        if primary_col in calc.results.columns:
            calc.results["SW"] = calc.results[primary_col]
        else:
            available = [c for c in SW_COLUMN_MAP.values() if c in calc.results.columns]
            if available:
                calc.results["SW"] = calc.results[available[0]]
            else:
                calc.results["SW"] = pd.Series([1.0] * len(data), index=data.index)
                warnings.append(
                    "Water saturation defaulted to 1.0 because no selected method produced a result."
                )

    # ---- Irreducible saturation ---------------------------------------------
    emit("Calculating Swirr...", 65)
    swirr_method = p["swirr_method"]
    k_buckles = p["k_buckles"]
    sw_for_swirr = calc.results.get("SW", pd.Series([0.5] * len(data), index=data.index))

    if swirr_method == "Hierarchical (Recommended)":
        calc.calculate_swirr_hierarchical(phie=phie, sw=sw_for_swirr, vsh=vsh, k_buckles=k_buckles)
    else:
        calc.calculate_all_swirr(
            phie=phie,
            sw=sw_for_swirr,
            vsh=vsh,
            k_buckles=k_buckles,
            vsh_threshold=0.2,
            methods=SWIRR_METHOD_MAP.get(swirr_method, ["buckles"]),
        )
    swirr = calc.results.get("SWIRR", pd.Series([0.2] * len(data), index=data.index))
    swirr_mean = swirr.mean()

    # ---- Permeability -------------------------------------------------------
    emit("Calculating permeability...", 75)
    perm_timur = calc.calculate_permeability_timur(phie, swirr)
    calc.calculate_permeability_wyllie_rose(phie, swirr, p["perm_C"], p["perm_P"], p["perm_Q"])
    calc.classify_flow_units(perm_timur)
    calc.get_permeability_quality_flags(perm_timur, swirr, phie)

    # ---- Net pay and HCPV ---------------------------------------------------
    emit("Calculating net pay...", 85)
    sw_for_pay = calc.results.get("SW", pd.Series([1.0] * len(data), index=data.index))
    summary = calc.calculate_net_pay(
        vsh, phie, sw_for_pay, p["vsh_cutoff"], p["phi_cutoff"], p["sw_cutoff"]
    )

    emit("Calculating HCPV...", 88)
    hcpv = calc.calculate_hcpv(
        phie=phie,
        sw=sw_for_pay,
        depth=data["DEPTH"],
        net_res_flag=calc.results.get("NET_RES_FLAG"),
        net_pay_flag=calc.results.get("NET_PAY_FLAG"),
    )

    # ---- Summary ------------------------------------------------------------
    emit("Finalizing results...", 95)
    results = calc.export_results()
    summary["gr_min"] = gr_min
    summary["gr_max"] = gr_max
    summary["rw"] = rw
    summary["rsh"] = rsh
    summary["rw_source"] = rw_source
    summary["rsh_source"] = rsh_source
    summary["swirr_method"] = swirr_method
    summary["swirr_mean"] = swirr_mean
    summary["analysis_mode"] = analysis_mode
    summary["selected_formations"] = selected_formations
    summary["data_points"] = len(data)

    solver_diagnostics = {}
    for method, diagnostics in calc.solver_diagnostics.items():
        counts = {
            "no_root": int(diagnostics.get("no_root", 0)),
            "failed": int(diagnostics.get("failed", 0)),
        }
        solver_diagnostics[method] = counts
        if counts["no_root"] or counts["failed"]:
            warnings.append(
                f"{method}: {counts['no_root']} no-root, {counts['failed']} failed solver points."
            )
    summary["solver_diagnostics"] = solver_diagnostics

    if not has_rt:
        warnings.append("Water saturation defaulted to 1.0 because no RT curve was available.")
    summary["warnings"] = warnings

    if "HCPV_CUM" in hcpv:
        def _last(series):
            return float(series.iloc[-1]) if len(series) > 0 else 0.0
        summary["hcpv_gross"] = _last(hcpv["HCPV_CUM"])
        summary["hcpv_net_res"] = _last(hcpv["HCPV_CUM_NET_RES"])
        summary["hcpv_net_pay"] = _last(hcpv["HCPV_CUM_NET_PAY"])

    emit("Analysis complete!", 100)
    return results, summary
