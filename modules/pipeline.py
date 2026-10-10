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

import numpy as np
import pandas as pd

from modules.param_scopes import (
    GR_MANUAL, PROJECT, PROJECT_ZONE, SPECS, UNZONED, ZONE_AUTO_MIN_FT,
    ZONE_AUTO_MIN_SAMPLES, arps_factor, flat_value, formation_temperature, normalize_zone,
)
from modules.petrophysics import PetrophysicsCalculator
from modules.shale_estimation import SHALE_PARAMS, estimate_shale_point, is_estimate
from modules.statistics_utils import (
    MIN_GR_SEPARATION, StatisticsUtils, get_default_matrix_parameters,
)

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
    # Formation temperature (degF, degF/100 ft) and the Arps correction of Rw.
    "temp_correction": False,
    "surface_temp": 80.0,
    "temp_gradient": 1.5,
    "rw_ref_temp": 75.0,
}

# ``summary["param_sources"]`` key for the well-level parameters.
WELL_SOURCES_KEY = "(well)"

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


def _shale_auto_names(p):
    """Shale-point parameters in AUTO mode for the scope resolved into ``p``."""
    auto = p.get("shale_auto") or ()
    return [n for n in SHALE_PARAMS if n in auto]


def _resolve_shale_auto(data, curve_mapping, p, gr_min, gr_max, warnings):
    """Fill the AUTO shale-point parameters of ``p`` from ``data`` (in place).

    The estimator runs once on the scope's samples with that scope's GR
    baseline. Returns the names whose estimate is unavailable; those keep the
    entered (project) value.
    """
    names = _shale_auto_names(p)
    if not names:
        return []
    estimate = estimate_shale_point(data, curve_mapping, p, gr_min, gr_max)
    if not is_estimate(estimate):
        warnings.append(
            "Shale point could not be estimated automatically "
            f"({estimate.get('vsh_method_used', 'no estimate')}); using the entered values."
        )
        return names
    for name in names:
        p[name] = estimate[name]
    return []


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


def temperature_factor(data: pd.DataFrame, p: Dict) -> Optional[pd.Series]:
    """Arps multiplier ``Rw(T(depth)) / Rw(T_ref)`` per sample, or None when off.

    T(depth) uses the well's surface temperature and gradient (degF,
    degF/100 ft) on the measured ``DEPTH`` in feet.
    """
    if not p.get("temp_correction"):
        return None
    temp = formation_temperature(data["DEPTH"], float(p["surface_temp"]), float(p["temp_gradient"]))
    return arps_factor(temp, float(p["rw_ref_temp"]))


def _auto_rw(stats_util, calc, vsh, rt_curve, p, temp_factor=None):
    """Rwa-method Rw on PHIE (PHIT if PHIE is absent) and the reference VSH, or None.

    With temperature correction the RT values are first brought to the Rw
    reference temperature, so the estimate is Rw at that temperature.
    """
    phi = calc.results.get("PHIE")
    if phi is None or not phi.notna().any():
        phi = calc.results.get("PHIT")
    if phi is None:
        return None
    if temp_factor is not None:
        frame = stats_util.data.copy()
        frame[rt_curve] = frame[rt_curve] / temp_factor.loc[frame.index]
        stats_util = StatisticsUtils(frame)
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


def _resolve_rw_rsh(stats_util, calc, vsh, rt_curve, p, warnings, temp_factor=None):
    """Effective Rw/Rsh per ``rw_mode`` / ``rsh_mode``.

    Returns ``(rw, rsh, rw_source, rsh_source)``; a source is ``"manual"``,
    ``"auto"`` or :data:`AUTO_UNAVAILABLE`. With temperature correction Rw is
    at the reference temperature.
    """
    rw, rsh = p["rw"], p["rsh"]
    rw_source = rsh_source = "manual"
    if p["rw_mode"] == "auto":
        estimate = _auto_rw(stats_util, calc, vsh, rt_curve, p, temp_factor)
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


def _filter_formations(data, p, formation_tops):
    if p["analysis_mode"] == "Per-Formation" and p["selected_formations"] and formation_tops:
        return formation_tops.filter_by_formations(data, p["selected_formations"], "DEPTH")
    return data


def estimate_rw_rsh(
    data: pd.DataFrame,
    curve_mapping: Dict[str, str],
    params: Dict,
    formation_tops=None,
    zone: Optional[str] = None,
) -> Optional[Dict]:
    """Rw and Rsh exactly as a pipeline run in auto mode would estimate them.

    Uses the same formation filter, GR baseline, VSH and porosity steps as
    :func:`run_pipeline`, then the same estimators, regardless of ``rw_mode`` /
    ``rsh_mode``. With ``zone`` only that zone's samples are used (the
    well · zone "Calculate" of spec §4.7). Returns ``None`` when there is no
    data or no RT curve, otherwise a dict with ``rw`` and ``rsh`` (the estimate,
    or the entered value when it is unavailable), ``rw_source``,
    ``rsh_source``, ``gr_min``, ``gr_max`` and ``warnings``.
    """
    if data is None:
        return None
    p = {**PARAM_DEFAULTS, **params, "rw_mode": "auto", "rsh_mode": "auto"}
    data = _filter_formations(data.copy(), p, formation_tops)
    if zone and formation_tops is not None:
        labels, _ = assign_zones(data["DEPTH"], formation_tops)
        data = data[labels == normalize_zone(zone)]
    rt_curve = curve_mapping.get("RT", "RT")
    if len(data) == 0 or not _has(rt_curve, data):
        return None

    warnings = []
    calc = PetrophysicsCalculator(data)
    stats_util = StatisticsUtils(data)
    vsh, gr_min, gr_max = _compute_vsh(calc, stats_util, data, curve_mapping, p, warnings)
    _resolve_shale_auto(data, curve_mapping, p, gr_min, gr_max, warnings)
    _compute_porosity(calc, vsh, data, curve_mapping, p, warnings)
    rw, rsh, rw_source, rsh_source = _resolve_rw_rsh(
        stats_util, calc, vsh, rt_curve, p, warnings, temperature_factor(data, p)
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


# ---------------------------------------------------------------------------
# Zones (spec §4.6)
# ---------------------------------------------------------------------------
def assign_zones(depth: pd.Series, formation_tops) -> Tuple[pd.Series, list]:
    """Zone label per sample, plus warnings.

    A sample belongs to the formation with ``top <= d < bottom`` (the deepest
    formation keeps its bottom, as in :class:`FormationTops`). Where intervals
    overlap the shallower formation wins and a warning is returned. Samples
    outside every interval are :data:`UNZONED`. Labels are normalised names.
    """
    labels = pd.Series(UNZONED, index=depth.index, dtype=object)
    formations = list(getattr(formation_tops, "formations", None) or [])
    if not formations:
        return labels, []
    deepest = max(formations, key=lambda fm: fm.bottom_depth)
    ordered = sorted(formations, key=lambda fm: fm.top_depth)
    warnings = []
    for upper, lower in zip(ordered, ordered[1:]):
        if lower.top_depth < upper.bottom_depth:
            warnings.append(
                f"Formation tops overlap: {upper.name} ({upper.top_depth:g}-"
                f"{upper.bottom_depth:g}) and {lower.name} ({lower.top_depth:g}-"
                f"{lower.bottom_depth:g}); the shallower formation is used."
            )
    # Deepest first, so a shallower formation overwrites any overlap.
    for fm in reversed(ordered):
        inside = depth >= fm.top_depth
        inside &= (depth <= fm.bottom_depth) if fm is deepest else (depth < fm.bottom_depth)
        labels[inside] = normalize_zone(fm.name)
    return labels, warnings


def _segment_order(labels: pd.Series, depth: pd.Series):
    """Zone names in order of their shallowest sample."""
    return list(depth.groupby(labels).min().sort_values().index)


def _enough_data(seg: pd.DataFrame, curve: Optional[str]) -> bool:
    """Whether a zone has enough samples of ``curve`` for an AUTO estimate (§4.4)."""
    if not _has(curve, seg):
        return False
    valid = seg.loc[seg[curve].notna(), "DEPTH"]
    return len(valid) >= ZONE_AUTO_MIN_SAMPLES and (
        float(valid.max() - valid.min()) >= ZONE_AUTO_MIN_FT
    )


def _zone_gr_baseline(seg, gr_curve):
    """P5/P95 of the zone's GR, or None when the zone cannot support it (§4.4)."""
    if not _enough_data(seg, gr_curve):
        return None
    gr = seg[gr_curve].dropna()
    lo, hi = float(np.percentile(gr, 5)), float(np.percentile(gr, 95))
    if hi - lo < MIN_GR_SEPARATION:
        return None
    return lo, hi


def _fallback_value(name, plan_entry, well_value):
    fb = plan_entry.get("fallback", {}).get(name, {})
    if fb.get("scope") == PROJECT_ZONE:
        return fb.get("value"), f"auto (fallback: {PROJECT_ZONE})"
    return well_value, "auto (fallback: well)"


def _merge_diagnostics(total, diagnostics):
    for method, diag in diagnostics.items():
        counts = total.setdefault(method, {"no_root": 0, "failed": 0})
        counts["no_root"] += int(diag.get("no_root", 0))
        counts["failed"] += int(diag.get("failed", 0))


def _zone_curves(seg, curve_mapping, p, plan_entry, well, temp_factor, warnings):
    """Compute one planned zone segment; returns ``(calc, pay, sources_table)``.

    ``well`` holds the well-level resolved numbers (GR baseline, Rw, Rsh) and
    their sources, used wherever the zone does not set its own value.
    """
    zone_keys, zone_auto = plan_entry["zone_keys"], plan_entry["zone_auto"]
    sp = dict(p)
    for name in zone_keys:
        for key in SPECS[name].keys:
            sp[key] = plan_entry["params"].get(key, sp.get(key))
    sources = dict(well["sources"])
    for name in zone_keys:
        sources[name] = plan_entry["info"][name]["source"]

    gr_curve = curve_mapping.get("GR", "GR")
    rt_curve = curve_mapping.get("RT", "RT")
    if "gr_baseline" in zone_auto:
        baseline = _zone_gr_baseline(seg, gr_curve)
        if baseline is None:
            baseline, sources["gr_baseline"] = _fallback_value("gr_baseline", plan_entry, well["gr"])
    elif "gr_baseline" in zone_keys:
        baseline = (sp["gr_min_manual"], sp["gr_max_manual"])
    else:
        baseline = well["gr"]
    sp["vsh_baseline_method"] = GR_MANUAL
    sp["gr_min_manual"], sp["gr_max_manual"] = float(baseline[0]), float(baseline[1])

    calc = PetrophysicsCalculator(seg)
    stats_util = StatisticsUtils(seg)
    vsh, _, _ = _compute_vsh(calc, stats_util, seg, curve_mapping, sp, warnings)
    shale_auto = [n for n in SHALE_PARAMS if n in zone_auto]
    if shale_auto:
        # The scope's own shale point; the well's value is the fallback.
        estimate = None
        if _enough_data(seg, gr_curve):
            estimate = estimate_shale_point(
                seg, curve_mapping, sp, sp["gr_min_manual"], sp["gr_max_manual"]
            )
        for name in shale_auto:
            if is_estimate(estimate):
                sp[name] = estimate[name]
            else:
                sp[name], sources[name] = _fallback_value(name, plan_entry, p[name])
    _compute_porosity(calc, vsh, seg, curve_mapping, sp, warnings)

    values = {}
    estimators = {
        "rw": lambda: _auto_rw(stats_util, calc, vsh, rt_curve, sp, temp_factor),
        "rsh": lambda: _auto_rsh(stats_util, vsh, rt_curve),
    }
    for name, estimator in estimators.items():
        if name in zone_auto:
            estimate = estimator() if _enough_data(seg, rt_curve) else None
            if estimate is None:
                estimate, sources[name] = _fallback_value(name, plan_entry, well[name])
            values[name] = estimate
        elif name in zone_keys:
            values[name] = sp[name]
        else:
            values[name] = well[name]
    sp["rw"], sp["rsh"] = values["rw"], values["rsh"]
    sp["rw_mode"] = sp["rsh_mode"] = "manual"
    pay = _saturation_to_pay(calc, seg, curve_mapping, sp, vsh, values["rw"], values["rsh"],
                             temp_factor, warnings)
    resolved = {"gr_baseline": [sp["gr_min_manual"], sp["gr_max_manual"]],
                "rw": values["rw"], "rsh": values["rsh"]}
    return calc, pay, _sources_table(sp, sources, resolved)


def _sources_table(p, sources, resolved):
    """``{param: {"value", "source"}}`` for every scoped parameter."""
    table = {}
    for name in SPECS:
        value = resolved[name] if name in resolved else flat_value(name, p)
        table[name] = {"value": value, "source": sources.get(name, PROJECT)}
    return table


def _well_sources(p, rw_source, rsh_source, shale_failed=()):
    """Sources of the well-level parameters, from the resolver info when given."""
    info = p.get("param_info") or {}
    sources = {name: (info.get(name) or {}).get("source", PROJECT) for name in SPECS}
    if not info:
        if p["vsh_baseline_method"] != GR_MANUAL:
            sources["gr_baseline"] = "auto"
        for name in ("rw", "rsh"):
            if p[f"{name}_mode"] == "auto":
                sources[name] = "auto"
        for name in _shale_auto_names(p):
            sources[name] = "auto"
    for name in shale_failed:
        sources[name] = "auto unavailable (fallback: project)"
    for name, src in (("rw", rw_source), ("rsh", rsh_source)):
        if src == AUTO_UNAVAILABLE:
            sources[name] = "auto unavailable (fallback: project)"
    return sources


# ---------------------------------------------------------------------------
# Saturation, Swirr, permeability, pay flags
# ---------------------------------------------------------------------------
def _saturation_to_pay(calc, data, curve_mapping, p, vsh, rw, rsh, temp_factor, warnings):
    """Sw, Swirr, permeability and pay flags on ``calc``.

    ``rw`` is a number (at the reference temperature when ``temp_factor`` is
    given). Returns the ``vsh``/``phie``/``sw``/``swirr`` series used and the
    net-pay summary of this calculator's samples.
    """
    rt_curve = curve_mapping.get("RT", "RT")
    has_rt = _has(rt_curve, data)
    a, m, n = p["a"], p["m"], p["n"]
    rw_eff = rw if temp_factor is None else rw * temp_factor.loc[data.index]

    phie = calc.results.get("PHIE")
    if phie is None:
        phie = pd.Series([0.15] * len(data), index=data.index)
        warnings.append("PHIE defaulted to 0.15 because no usable porosity method was available.")

    if has_rt:
        selected = p["sw_methods"]
        if "Archie" in selected:
            calc.calculate_sw_archie(rt_curve, phie, rw_eff, a, m, n)
        if "Indonesian" in selected:
            calc.calculate_sw_indonesian(rt_curve, phie, vsh, rw_eff, rsh, a, m, n)
        if "Simandoux" in selected:
            calc.calculate_sw_simandoux(rt_curve, phie, vsh, rw_eff, rsh, a, m, n)
        if "Waxman-Smits" in selected:
            calc.calculate_sw_waxman_smits(rt_curve, phie, rw_eff, a, m, n, p["ws_qv"], p["ws_b"])
        if "Dual-Water" in selected:
            calc.calculate_sw_dual_water(rt_curve, phie, rw_eff, a, m, n, p["dw_swb"], p["dw_rwb"])

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

    perm_timur = calc.calculate_permeability_timur(phie, swirr)
    calc.calculate_permeability_wyllie_rose(phie, swirr, p["perm_C"], p["perm_P"], p["perm_Q"])
    calc.classify_flow_units(perm_timur)
    calc.get_permeability_quality_flags(perm_timur, swirr, phie)

    sw_for_pay = calc.results.get("SW", pd.Series([1.0] * len(data), index=data.index))
    pay = calc.calculate_net_pay(
        vsh, phie, sw_for_pay, p["vsh_cutoff"], p["phi_cutoff"], p["sw_cutoff"]
    )
    return {"vsh": vsh, "phie": phie, "sw": sw_for_pay, "swirr": swirr, "summary": pay}


def _depth_step(data: pd.DataFrame) -> float:
    """The net-pay depth step, derived as ``calculate_net_pay`` derives it."""
    if "DEPTH" in data.columns:
        depths = data["DEPTH"].dropna()
        if len(depths) > 1:
            return abs(np.median(np.diff(depths)))
    return 0.1


def _pay_stats(results, vsh, phie, sw, step, mask=None):
    """Net-pay numbers from the stored flags (same arithmetic as ``calculate_net_pay``)."""
    if mask is not None:
        results, vsh, phie, sw = results[mask], vsh[mask], phie[mask], sw[mask]
    gross_flag = results["GROSS_SAND_FLAG"].astype(bool)
    res_flag = results["NET_RES_FLAG"].astype(bool)
    pay_flag = results["NET_PAY_FLAG"].astype(bool)
    gross = gross_flag.sum() * step
    net_res = res_flag.sum() * step
    net_pay = pay_flag.sum() * step
    if pay_flag.sum() > 0:
        avg_phi = float(phie[pay_flag].mean())
        avg_sw = float(sw[pay_flag].mean())
        avg_vsh = float(vsh[pay_flag].mean())
    else:
        avg_phi = avg_sw = avg_vsh = np.nan
    return {
        "gross_sand": float(gross),
        "net_reservoir": float(net_res),
        "net_pay": float(net_pay),
        "ng_reservoir": float(net_res / gross if gross > 0 else 0),
        "ng_pay": float(net_pay / gross if gross > 0 else 0),
        "avg_phie_pay": float(avg_phi),
        "avg_sw_pay": float(avg_sw),
        "avg_vsh_pay": float(avg_vsh),
    }


ZONE_SUMMARY_PARAMS = ("a", "m", "n", "rw", "rsh", "vsh_cutoff", "phi_cutoff", "sw_cutoff")


def _zone_rows(results, labels, data, pay_series, step, sources_by_zone):
    """Per-zone pay summary rows in depth order (spec §4.8)."""
    rows = []
    for zone in _segment_order(labels, data["DEPTH"]):
        mask = labels == zone
        depth = data.loc[mask, "DEPTH"]
        row = {"zone": zone, "top": float(depth.min()), "bottom": float(depth.max()),
               "samples": int(mask.sum())}
        row.update(_pay_stats(results, *pay_series, step, mask))
        if "dHCPV_NET_PAY" in results.columns:
            row["hcpv_net_pay"] = float(results.loc[mask, "dHCPV_NET_PAY"].sum())
        table = sources_by_zone.get(zone, {})
        names = ZONE_SUMMARY_PARAMS
        if any(str(table.get(k, {}).get("source", "")).startswith("auto")
               for k in SHALE_PARAMS):
            names = names + SHALE_PARAMS
        row["params"] = {k: table[k] for k in names if k in table}
        rows.append(row)
    return rows


ZONE_CUTOFFS = (("vsh_cutoff", "pass_vsh"), ("phi_cutoff", "pass_phi"), ("sw_cutoff", "pass_sw"))


def _zone_diagnostics(vsh, phie, sw, cutoffs, step):
    """Why a zone has no gross / net reservoir / net pay (spec §9.1).

    ``vsh``, ``phie`` and ``sw`` are one zone's series; ``cutoffs`` holds the
    ``vsh_cutoff``, ``phi_cutoff`` and ``sw_cutoff`` applied in that zone; ``step``
    is the depth step (thicknesses are in the unit of the summary). Samples with a
    NaN in any of the three are not ``valid`` and count nowhere. Passing follows
    the pay flags: ``vsh < cutoff``, ``phie > cutoff``, ``sw < cutoff``.

    ``status``: ``no_data`` (no valid sample; fractions and ``limiting`` are
    ``None``), ``no_gross``, ``no_reservoir``, ``no_pay`` or ``ok``. ``limiting``
    is the cutoff with the lowest pass fraction among the samples that pass the
    other two (``None`` when every cutoff passes everything); a zone without
    gross, reservoir or pay names the Vsh, PHIE or Sw cutoff respectively.
    """
    vsh, phie, sw = (np.asarray(x, dtype=float) for x in (vsh, phie, sw))
    ok = np.isfinite(vsh) & np.isfinite(phie) & np.isfinite(sw)
    vsh, phie, sw = vsh[ok], phie[ok], sw[ok]
    n = int(ok.sum())
    out = {"valid": n, "gross": 0.0, "pass_vsh": None, "pass_phi": None, "pass_sw": None,
           "net_reservoir": 0.0, "net_pay": 0.0, "status": "no_data", "limiting": None,
           "cutoffs": {k: float(cutoffs[k]) for k, _ in ZONE_CUTOFFS}}
    if n == 0:
        return out
    passes = {"vsh_cutoff": vsh < cutoffs["vsh_cutoff"],
              "phi_cutoff": phie > cutoffs["phi_cutoff"],
              "sw_cutoff": sw < cutoffs["sw_cutoff"]}
    gross = passes["vsh_cutoff"]
    reservoir = gross & passes["phi_cutoff"]
    pay = reservoir & passes["sw_cutoff"]
    for name, key in ZONE_CUTOFFS:
        out[key] = float(passes[name].sum() / n)
    out["gross"], out["net_reservoir"], out["net_pay"] = (
        float(m.sum() * step) for m in (gross, reservoir, pay))
    if not gross.any():
        out["status"], out["limiting"] = "no_gross", "vsh_cutoff"
    elif not reservoir.any():
        out["status"], out["limiting"] = "no_reservoir", "phi_cutoff"
    elif not pay.any():
        out["status"], out["limiting"] = "no_pay", "sw_cutoff"
    else:
        out["status"] = "ok"
        worst = 1.0
        for name, _ in ZONE_CUTOFFS:
            others = np.logical_and.reduce([v for k, v in passes.items() if k != name])
            if others.any():
                fraction = float(passes[name][others].mean())
                if fraction < worst:
                    worst, out["limiting"] = fraction, name
    return out


def zone_diagnostic_note(diag):
    """``(level, text)`` for a zone's diagnostics, or ``None`` when nothing needs a look.

    ``level`` is ``"warning"`` (no net reservoir) or ``"info"``. The wording is
    diagnostic: a tight or water-bearing zone is legitimate.
    """
    status, c = diag.get("status"), diag.get("cutoffs") or {}
    if status == "no_data":
        return "info", "No valid samples: VSH, PHIE or Sw is missing over the whole zone."
    if status == "no_gross":
        return "info", (f"No gross: the Vsh cutoff {c['vsh_cutoff']:.2f} passes 0% of "
                        f"{diag['valid']} samples. Shale by this cutoff, as expected for a seal; "
                        "check the cutoff if the zone should be reservoir.")
    if status == "no_reservoir":
        return "warning", (f"No net reservoir: PHIE cutoff {c['phi_cutoff']:.2f} passes 0% of "
                           f"{diag['gross']:.0f} ft gross. Tight rock, or check the cutoff and "
                           "the porosity inputs (matrix, shale point).")
    if status == "no_pay":
        return "info", (f"No net pay: the Sw cutoff {c['sw_cutoff']:.2f} passes 0% of "
                        f"{diag['net_reservoir']:.0f} ft net reservoir. May be water-bearing; "
                        "check the cutoff and the Rw inputs if pay is expected.")
    return None


def _zone_diagnostics_by_zone(labels, pay_series, step, sources_by_zone):
    """``{zone: diagnostics}`` using the cutoffs applied in each zone."""
    vsh, phie, sw = pay_series
    out = {}
    for zone in dict.fromkeys(labels.dropna()):
        mask = (labels == zone).to_numpy()
        table = sources_by_zone.get(zone, {})
        try:
            cutoffs = {k: table[k]["value"] for k, _ in ZONE_CUTOFFS}
        except KeyError:
            continue
        out[zone] = _zone_diagnostics(vsh[mask], phie[mask], sw[mask], cutoffs, step)
    return out


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
        params: Plain dict; see :data:`PARAM_DEFAULTS`. Optional extras from
            :mod:`modules.param_scopes`: ``zone_plan`` (per-zone parameters)
            and ``param_info`` (provenance of the well-level values).
        progress: Optional ``callback(message, percent)``.
        formation_tops: ``FormationTops`` instance; needed for Per-Formation
            mode and for zones.

    Returns:
        ``(results, summary)`` where ``results`` is the original curves plus the
        computed columns (and ``ZONE`` when tops are given) and ``summary``
        holds net pay, HCPV, parameters and their sources (``param_sources``),
        the per-zone pay summary (``zones``), solver diagnostics, and warnings.

    Zones with an entry in ``zone_plan`` are computed as separate segments
    with their own parameters. All other samples are computed together with
    the well's parameters, exactly as an unzoned run (spec §4.6).

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
    data = _filter_formations(data, p, formation_tops)
    if len(data) == 0:
        raise PipelineError("No data in selected formation(s)")

    labels = None
    if formation_tops is not None and getattr(formation_tops, "formations", None):
        labels, zone_warnings = assign_zones(data["DEPTH"], formation_tops)
        warnings.extend(zone_warnings)
    plan = {}
    if labels is not None:
        present = set(labels.unique())
        plan = {z: e for z, e in (p.get("zone_plan") or {}).items() if z in present}

    emit("Initializing calculator...", 10)
    calc = PetrophysicsCalculator(data)
    stats_util = StatisticsUtils(data)
    rt_curve = curve_mapping.get("RT", "RT")
    has_rt = _has(rt_curve, data)
    temp_factor = temperature_factor(data, p)

    # ---- Shale volume -------------------------------------------------------
    emit("Calculating VShale...", 20)
    vsh, gr_min, gr_max = _compute_vsh(calc, stats_util, data, curve_mapping, p, warnings)

    # ---- Porosity -----------------------------------------------------------
    emit("Calculating porosity...", 35)
    shale_failed = _resolve_shale_auto(data, curve_mapping, p, gr_min, gr_max, warnings)
    _compute_porosity(calc, vsh, data, curve_mapping, p, warnings)
    emit("Calculating effective porosity...", 45)

    # ---- Water saturation (well-level Rw / Rsh) -----------------------------
    emit("Calculating water saturation...", 55)
    rw, rsh, rw_source, rsh_source = p["rw"], p["rsh"], "manual", "manual"
    if has_rt:
        rw, rsh, rw_source, rsh_source = _resolve_rw_rsh(
            stats_util, calc, vsh, rt_curve, p, warnings, temp_factor
        )
    well_sources = _well_sources(p, rw_source, rsh_source, shale_failed)
    well_table = _sources_table(
        p, well_sources, {"gr_baseline": [gr_min, gr_max], "rw": rw, "rsh": rsh}
    )
    sources_by_zone = {}
    solver_raw = {}

    if not plan:
        emit("Calculating Swirr...", 65)
        pay = _saturation_to_pay(calc, data, curve_mapping, p, vsh, rw, rsh, temp_factor, warnings)
        emit("Calculating permeability...", 75)
        emit("Calculating net pay...", 85)
        summary = dict(pay["summary"])
        _merge_diagnostics(solver_raw, calc.solver_diagnostics)
    else:
        # Planned zones run as their own segments; every other sample runs
        # together with the well's parameters.
        well = {"gr": (gr_min, gr_max), "rw": rw, "rsh": rsh, "sources": well_sources}
        zones = [z for z in _segment_order(labels, data["DEPTH"]) if z in plan]
        parts, pays = [], []
        for i, zone in enumerate(zones):
            emit(f"Calculating zone {zone}...", 55 + int(25 * i / len(zones)))
            seg_calc, seg_pay, table = _zone_curves(
                data[labels == zone], curve_mapping, p, plan[zone], well, temp_factor, warnings
            )
            parts.append(seg_calc.results)
            pays.append(seg_pay)
            sources_by_zone[zone] = table
            _merge_diagnostics(solver_raw, seg_calc.solver_diagnostics)
        rest = ~labels.isin(zones)
        if rest.any():
            rest_data = data[rest]
            rest_calc = PetrophysicsCalculator(rest_data)
            sp = {**p, "vsh_baseline_method": GR_MANUAL,
                  "gr_min_manual": gr_min, "gr_max_manual": gr_max}
            rest_vsh, _, _ = _compute_vsh(
                rest_calc, StatisticsUtils(rest_data), rest_data, curve_mapping, sp, warnings
            )
            _compute_porosity(rest_calc, rest_vsh, rest_data, curve_mapping, sp, warnings)
            pays.append(_saturation_to_pay(rest_calc, rest_data, curve_mapping, sp, rest_vsh,
                                           rw, rsh, temp_factor, warnings))
            parts.append(rest_calc.results)
            _merge_diagnostics(solver_raw, rest_calc.solver_diagnostics)
        emit("Calculating net pay...", 85)
        calc.results = pd.concat(parts).reindex(data.index)
        pay = {k: pd.concat([pp[k] for pp in pays]).reindex(data.index)
               for k in ("vsh", "phie", "sw", "swirr")}
        summary = _pay_stats(calc.results, pay["vsh"], pay["phie"], pay["sw"], _depth_step(data))
        warnings[:] = list(dict.fromkeys(warnings))

    emit("Calculating HCPV...", 88)
    hcpv = calc.calculate_hcpv(
        phie=pay["phie"],
        sw=pay["sw"],
        depth=data["DEPTH"],
        net_res_flag=calc.results.get("NET_RES_FLAG"),
        net_pay_flag=calc.results.get("NET_PAY_FLAG"),
    )

    # ---- Summary ------------------------------------------------------------
    emit("Finalizing results...", 95)
    if labels is not None:
        calc.results["ZONE"] = labels
    results = calc.export_results()
    summary["gr_min"] = gr_min
    summary["gr_max"] = gr_max
    summary["rw"] = rw
    summary["rsh"] = rsh
    summary["rw_source"] = rw_source
    summary["rsh_source"] = rsh_source
    summary["swirr_method"] = p["swirr_method"]
    summary["swirr_mean"] = pay["swirr"].mean()
    summary["analysis_mode"] = analysis_mode
    summary["selected_formations"] = selected_formations
    summary["data_points"] = len(data)
    if temp_factor is not None:
        rw_at_depth = rw * temp_factor
        summary["rw_ref_temp"] = float(p["rw_ref_temp"])
        summary["rw_at_depth_range"] = [float(rw_at_depth.min()), float(rw_at_depth.max())]

    param_sources = {WELL_SOURCES_KEY: well_table}
    if labels is not None:
        for zone in _segment_order(labels, data["DEPTH"]):
            param_sources[zone] = sources_by_zone.get(zone, well_table)
    summary["param_sources"] = param_sources
    summary["zones"] = (
        _zone_rows(calc.results, labels, data, (pay["vsh"], pay["phie"], pay["sw"]),
                   _depth_step(data), param_sources)
        if labels is not None else []
    )
    if summary["zones"]:
        summary["zone_diagnostics"] = _zone_diagnostics_by_zone(
            labels, (pay["vsh"], pay["phie"], pay["sw"]),
            _depth_step(data), param_sources)

    solver_diagnostics = {}
    for method, diagnostics in solver_raw.items():
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
