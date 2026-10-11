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

from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from modules.issue_codes import ISSUE_CODES, IssueLog  # noqa: F401  (re-exported)
from modules.las_utils import mask_nonpositive
from modules.param_scopes import (
    GR_MANUAL, OPTIONAL_SOURCE_PARAMS, PROJECT, PROJECT_ZONE, SPECS, UNZONED,
    ZONE_AUTO_MIN_FT, ZONE_AUTO_MIN_SAMPLES, arps_factor, flat_value, formation_temperature,
    juhasz_b, normalize_zone, resolve_tvd,
)
from modules.petrophysics import PetrophysicsCalculator, depth_increments, pay_summary
from modules.shale_estimation import SHALE_PARAMS, estimate_shale_point, is_estimate
from modules.statistics_utils import (
    MIN_GR_SEPARATION, StatisticsUtils, get_default_matrix_parameters,
)

ProgressFn = Callable[[str, int], None]

# A zone's own GR P95 is its shale line only if it reaches this fraction of the
# way from the well's GRmin to its GRmax; below it the zone has no shale.
ZONE_SHALE_REACH = 0.75

# Hierarchical Swirr limit counts (floor, 0.60) are a warning only above this share
# of the samples that have a Swirr; below it they are info. Samples limited to the
# measured Sw are always info.
SWIRR_COUNT_SHARE = 0.10

# Analysis parameters read by the pipeline, with the defaults the GUI ships.
# Keys match the AppModel attribute names and the session-file fields.
PARAM_DEFAULTS: Dict[str, object] = {
    "analysis_mode": "Whole Well",
    "selected_formations": [],
    "vsh_baseline_method": "Statistically (Auto)",
    "gr_min_manual": 20.0,
    "gr_max_manual": 120.0,
    "vsh_methods": ["Linear"],
    "vsh_primary_method": None,     # None: the first of vsh_methods
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
    "gas_crossover_min": 0.02,
    "gas_vsh_max": 0.40,
    # PHIT and PHIE_DN from PHID and PHIN: "Average" or "RMS" (RMS on gas-flagged samples).
    "dn_combination": "Average",
    # Formation temperature (degF, degF/100 ft) and the Arps correction of Rw.
    "temp_correction": False,
    "surface_temp": 80.0,
    "temp_gradient": 1.5,
    "rw_ref_temp": 75.0,
    # Datum depth d0 (ft) at which surface_temp applies, on the TVD axis.
    "temp_datum_depth": 0.0,
    # Temperature (degF) at which a manual Rsh was read; None = not corrected.
    "rsh_ref_temp": None,
    # Waxman-Smits B from temperature (Juhasz 1981) instead of the entered B.
    "ws_b_auto": False,
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


def resolve_vsh_primary(vsh_methods, stored=None) -> Optional[str]:
    """The primary Vsh method (UI name): the stored one if still selected, else the first.

    ``stored`` is ``vsh_primary_method`` (``None`` by default). Returns ``None``
    only when no method is selected.
    """
    names = list(vsh_methods or [])
    if stored is not None and stored in names:
        return stored
    return names[0] if names else None


def vsh_reference(calc: PetrophysicsCalculator, methods, data: pd.DataFrame, gr_curve: str,
                  primary: Optional[str] = None):
    """Return the VSH series used for shale masking and its label.

    ``methods`` are the calculated method keys; the reference is the column of
    ``primary`` (a key, default the first of ``methods``). The other selected
    methods stay in the results as comparison curves.
    """
    method = primary if primary in methods else (methods[0] if methods else "linear")
    key = VSH_COLUMN_MAP.get(method, "VSH_LINEAR")
    vsh_ref = calc.results.get(
        key,
        calc.results.get("VSH", pd.Series([0.5] * len(data), index=data.index)),
    )
    return vsh_ref, method


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
    primary = VSH_METHOD_MAP.get(resolve_vsh_primary(vsh_selected, p.get("vsh_primary_method")))

    if has_gr:
        calc.calculate_all_vshale(gr_curve, gr_min, gr_max, methods_to_calc)
        vsh, _ = vsh_reference(calc, methods_to_calc, data, gr_curve, primary)
        calc.results["VSH"] = vsh
    else:
        vsh = pd.Series([0.3] * len(data), index=data.index)
        calc.results["VSH"] = vsh
        warnings.add("VSH_DEFAULTED", "VSH defaulted to 0.3 because no GR curve was available.")
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
        warnings.add(
            "SHALE_POINT_UNAVAILABLE",
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
        warnings.add(
            "NPHI_PERCENT",
            f"NPHI curve {nphi_curve} has a median above 1.0; it looks like percent, "
            "not fractional porosity (v/v). Porosity and Sw results will be wrong."
        )

    if has_density:
        calc.calculate_porosity_density(rhob_curve, rho_matrix, rho_fluid)
    if has_neutron:
        calc.calculate_porosity_neutron(nphi_curve, resolve_nphi_matrix(p))
    if has_sonic:
        calc.calculate_porosity_sonic(dt_curve, dt_matrix, dt_fluid)
    # Gas samples are flagged whenever the correction is on, whatever the primary
    # PHIE method; PHIT then uses RMS there (Gaymard-Poupon).
    gas_flag = None
    if p["gas_correction_enabled"] and has_density and has_neutron:
        gas_flag = calc.calculate_gas_flag(vsh, p["gas_crossover_min"], p["gas_vsh_max"])
    if has_density or has_neutron or has_sonic:
        calc.calculate_phit_neutron_density(
            dn_combination=p["dn_combination"], gas_flag=gas_flag
        )
    else:
        warnings.add(
            "PHIT_UNAVAILABLE",
            "PHIT was not calculated because no RHOB, NPHI or DT curve was available.")

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
        nphi_matrix=resolve_nphi_matrix(p),
        dn_combination=p["dn_combination"],
        gas_crossover_min=p["gas_crossover_min"],
        gas_vsh_max=p["gas_vsh_max"],
    )
    partial = getattr(calc, "phie_partial", None)
    if partial is not None:
        method, fraction = partial
        if method is None:
            warnings.add("PHIE_NO_VALID",
                         "PHIE has no valid samples: no porosity method produced a value, "
                         "so Sw, pay and HCPV are NaN.")
        else:
            warnings.add(
                "PHIE_SUBSTITUTED",
                f"PHIE from {method} covers {fraction * 100:.0f} % of the samples; the rest "
                "have no porosity and are excluded from pay and HCPV")


@dataclass
class TemperatureContext:
    """Formation temperature per sample and what it was computed from."""

    temp: pd.Series                      # degF per sample
    factor: Optional[pd.Series]          # Arps Rw(T)/Rw(T_ref); None unless temp_correction
    source: Dict                         # recorded in summary["temperature"]


def temperature_context(data: pd.DataFrame, p: Dict,
                        curve_mapping: Optional[Dict] = None) -> Optional[TemperatureContext]:
    """Formation temperature of every sample, or None when nothing needs it.

    ``T(z) = Ts + g (TVD(z) - d0) / 100`` (degF, degF/100 ft, ft). TVD comes
    from a mapped TVD curve, else the depth index when the log is on TVD, else
    the measured ``DEPTH`` (assumed vertical); see :func:`resolve_tvd`. Needed
    for the Arps correction (``temp_correction``) and for WS B from
    temperature (``ws_b_auto``).
    """
    if not (p.get("temp_correction") or p.get("ws_b_auto")):
        return None
    tvd_curve = (curve_mapping or p.get("curve_mapping") or {}).get("TVD")
    tvd_source = resolve_tvd(data, tvd_curve, p.get("depth_reference"),
                             bool(p.get("header_deviation")))
    tvd = pd.Series(tvd_source.at(data["DEPTH"].to_numpy(dtype=float)), index=data.index)
    datum = float(p.get("temp_datum_depth") or 0.0)
    temp = formation_temperature(tvd, float(p["surface_temp"]), float(p["temp_gradient"]), datum)
    factor = arps_factor(temp, float(p["rw_ref_temp"])) if p.get("temp_correction") else None
    source = {
        "tvd_source": tvd_source.label,
        "kind": tvd_source.kind,
        "extrapolated_fraction": tvd_source.extrapolated,
        "datum_depth": datum,
        "surface_temp": float(p["surface_temp"]),
        "gradient": float(p["temp_gradient"]),
        "range": [float(temp.min()), float(temp.max())],
        "notes": list(tvd_source.notes),
    }
    return TemperatureContext(temp, factor, source)


def temperature_factor(data: pd.DataFrame, p: Dict,
                       curve_mapping: Optional[Dict] = None) -> Optional[pd.Series]:
    """Arps multiplier ``Rw(T(z)) / Rw(T_ref)`` per sample, or None when off."""
    ctx = temperature_context(data, {**p, "ws_b_auto": False}, curve_mapping)
    return None if ctx is None else ctx.factor


def _factor(tctx: Optional[TemperatureContext]) -> Optional[pd.Series]:
    return None if tctx is None else tctx.factor


def _auto_rw(stats_util, calc, vsh, rt_curve, p, temp_factor=None, info=None):
    """Rwa-method Rw on PHIE (PHIT if PHIE is absent) and the reference VSH, or None.

    With temperature correction the RT values are first brought to the Rw
    reference temperature, so the estimate is Rw at that temperature. When
    ``info`` is given it receives ``quality``, ``n_water``, ``n_hc`` and the
    estimator's ``warnings``.
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
    rw, quality = stats_util.estimate_rw_from_rt_water_zone(
        rt_curve, phi, 0.15, p["a"], p["m"], vsh_series=vsh, n=p["n"]
    )
    if info is not None:
        detail = getattr(stats_util, "rw_info", None) or {}
        info.update(quality=quality, n_water=detail.get("n_water", 0),
                    n_hc=detail.get("n_hc", 0), warnings=list(detail.get("warnings", [])))
        if rw is None:
            info["warnings"].append(
                "auto Rw: no water-bearing samples found; entered Rw used.")
    return rw or None


def _auto_rsh(stats_util, vsh, rt_curve, temp_factor=None, info=None):
    """Median RT of the shale zone (VSH > 0.8), or None when there is none.

    With temperature correction each sample's RT is first brought to the Rw
    reference temperature (``RT / factor``), so the median is Rsh at that
    temperature (as for :func:`_auto_rw`).
    """
    if temp_factor is not None:
        frame = stats_util.data.copy()
        frame[rt_curve] = frame[rt_curve] / temp_factor.loc[frame.index]
        stats_util = StatisticsUtils(frame)
    rsh = stats_util.estimate_rsh(rt_curve, vsh, unavailable_default=None) or None
    if info is not None:
        detail = getattr(stats_util, "rsh_info", None) or {}
        info.update(n_shale=detail.get("n_shale", 0),
                    warnings=list(detail.get("warnings", [])))
        if rsh is None and detail.get("n_shale", 0):
            info["warnings"].append(
                f"auto Rsh: only {detail['n_shale']} samples with Vsh above 0.8 "
                "(at least 10 are needed); entered Rsh used.")
    return rsh


def _rsh_effective(rsh, rsh_auto, p, tctx, index):
    """Rsh as used in Sw: a number, or per-sample values at formation temperature.

    Arps form ``R(T2) = R(T1) (T1 + 6.77) / (T2 + 6.77)``. An auto Rsh is at the
    Rw reference temperature; a manual Rsh is corrected from ``rsh_ref_temp``
    and left as entered when that is not set. Without correction it is the number.
    """
    if tctx is None or tctx.factor is None:
        return rsh
    if rsh_auto:
        return rsh * tctx.factor.loc[index]
    ref = p.get("rsh_ref_temp")
    if ref is None:
        return rsh
    return rsh * arps_factor(tctx.temp.loc[index], float(ref))


def _unavailable_warning(name, entered):
    return (
        f"{name} could not be estimated automatically; using the entered "
        f"{name} of {entered}."
    )


_ESTIMATOR_CODES = (
    ("auto Rw: no water", "RW_AUTO_NO_WATER"),
    ("auto Rw: Rwa shows no", "RW_AUTO_UNIFORM"),
    ("auto Rw of", "RW_AUTO_CLAMPED"),
    ("auto Rsh: only", "RSH_AUTO_FEW_SHALE"),
    ("auto Rsh of", "RSH_AUTO_CLAMPED"),
)


def _add_estimator_warnings(log, which, texts):
    """Record the Rw / Rsh estimators' warning texts under their codes."""
    for text in texts:
        code = next((c for prefix, c in _ESTIMATOR_CODES if text.startswith(prefix)),
                    f"{which}_AUTO_NOTE")
        log.add(code, text)


def _resolve_rw_rsh(stats_util, calc, vsh, rt_curve, p, warnings, tctx=None, info=None):
    """Effective Rw/Rsh per ``rw_mode`` / ``rsh_mode``.

    Returns ``(rw, rsh, rw_source, rsh_source)``; a source is ``"manual"``,
    ``"auto"`` or :data:`AUTO_UNAVAILABLE`. With temperature correction an
    auto Rw and Rsh are at the reference temperature. When ``info`` is given it
    receives ``rw_quality``, ``rw_water_samples``, ``rw_hc_samples`` and
    ``rsh_shale_samples`` for an auto estimate; the estimators' warnings go to
    ``warnings``.
    """
    temp_factor = _factor(tctx)
    rw, rsh = p["rw"], p["rsh"]
    rw_source = rsh_source = "manual"
    if p["rw_mode"] == "auto":
        rw_info = {}
        estimate = _auto_rw(stats_util, calc, vsh, rt_curve, p, temp_factor, rw_info)
        _add_estimator_warnings(warnings, "RW", rw_info.get("warnings", []))
        if info is not None and rw_info:
            info.update(rw_quality=rw_info.get("quality"),
                        rw_water_samples=rw_info.get("n_water", 0),
                        rw_hc_samples=rw_info.get("n_hc", 0))
        if estimate is not None:
            rw, rw_source = estimate, "auto"
        else:
            rw_source = AUTO_UNAVAILABLE
            warnings.add("RW_AUTO_UNAVAILABLE", _unavailable_warning("Rw", rw))
    if p["rsh_mode"] == "auto":
        rsh_info = {}
        estimate = _auto_rsh(stats_util, vsh, rt_curve, temp_factor, rsh_info)
        _add_estimator_warnings(warnings, "RSH", rsh_info.get("warnings", []))
        if info is not None and rsh_info:
            info.update(rsh_shale_samples=rsh_info.get("n_shale", 0))
        if estimate is not None:
            rsh, rsh_source = estimate, "auto"
        else:
            rsh_source = AUTO_UNAVAILABLE
            warnings.add("RSH_AUTO_UNAVAILABLE", _unavailable_warning("Rsh", rsh))
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

    warnings = IssueLog()
    calc = PetrophysicsCalculator(data)
    stats_util = StatisticsUtils(data)
    vsh, gr_min, gr_max = _compute_vsh(calc, stats_util, data, curve_mapping, p, warnings)
    _resolve_shale_auto(data, curve_mapping, p, gr_min, gr_max, warnings)
    _compute_porosity(calc, vsh, data, curve_mapping, p, warnings)
    tctx = temperature_context(data, p, curve_mapping)
    if tctx is not None:
        for note in tctx.source["notes"]:
            warnings.add("TEMPERATURE_NOTE", note)
    estimator_info = {}
    rw, rsh, rw_source, rsh_source = _resolve_rw_rsh(
        stats_util, calc, vsh, rt_curve, p, warnings, tctx, estimator_info
    )
    return {
        "rw": rw,
        "rsh": rsh,
        "rw_source": rw_source,
        "rsh_source": rsh_source,
        "rw_quality": estimator_info.get("rw_quality"),
        "rw_water_samples": estimator_info.get("rw_water_samples"),
        "rw_hc_samples": estimator_info.get("rw_hc_samples"),
        "rsh_shale_samples": estimator_info.get("rsh_shale_samples"),
        "gr_min": gr_min,
        "gr_max": gr_max,
        "warnings": list(warnings),
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


ZONE_NO_SHALE_NOTE = "zone has no shale; GRmax from the well"


def _zone_gr_baseline(seg, gr_curve, well_baseline=None):
    """P5/P95 of the zone's GR, or None when the zone cannot support it (§4.4).

    GRmax is the zone's P95 only if it reaches ``ZONE_SHALE_REACH`` of the way
    from the well's GRmin to its GRmax (the zone contains shale). Otherwise the
    zone is clean and its own P95 would label clean sand as shale, so GRmax is
    the well's. Returns ``(lo, hi)`` or, when GRmax came from the well,
    ``(lo, hi, ZONE_NO_SHALE_NOTE)``.
    """
    if not _enough_data(seg, gr_curve):
        return None
    gr = seg[gr_curve].dropna()
    lo, hi = float(np.percentile(gr, 5)), float(np.percentile(gr, 95))
    if well_baseline is not None:
        well_lo, well_hi = float(well_baseline[0]), float(well_baseline[1])
        if hi < well_lo + ZONE_SHALE_REACH * (well_hi - well_lo):
            if well_hi - lo < MIN_GR_SEPARATION:
                return None
            return lo, well_hi, ZONE_NO_SHALE_NOTE
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


SW_MODEL_NAMES = {column: name for name, column in SW_COLUMN_MAP.items()}

# Per-model counts in ``summary["solver_diagnostics"]`` (and per zone under ``"zones"``).
SW_DIAGNOSTIC_KEYS = (
    "no_root", "failed", "at_upper_bound", "at_lower_bound", "no_porosity",
    "no_phit", "bvh_exceeds_phie", "phie_above_phit",
)
# Warn when more than this share of a zone's samples has inconsistent porosities.
INCONSISTENT_POROSITY_SHARE = 0.05
# Warn when more than this share of a zone's clean samples sits at the upper Sw bound.
UPPER_BOUND_SHARE = 0.10


def _concat_flags(frames, index):
    """Per-sample flag frames of several calculators as one boolean frame on ``index``."""
    return pd.concat(frames).reindex(index).fillna(False).astype(bool)


def _sw_solver_diagnostics(calcs, labels, index, vsh, vsh_cutoffs, default_cutoff, warnings):
    """``solver_diagnostics`` per Sw model and zone from the calculators' sample flags.

    ``{column: {count: n, ..., "zones": {zone: {count: n, ..., "samples": N}}}}``;
    ``"zones"`` is present when the well has formation zones. The counts are the
    ``SW_DIAGNOSTIC_KEYS``; ``no_root`` and ``failed`` are the solver counts of
    Waxman-Smits and Dual-Water. Appends a warning to ``warnings`` per model and
    zone where more than 5 % of the samples have inconsistent porosities or more
    than 10 % of the clean samples sit at the upper Sw bound (Sw > 1 before clipping).
    """
    frames = {}
    for calc in calcs:
        for column, flags in calc.sw_flags.items():
            frames.setdefault(column, []).append(flags)
    vsh_a = np.asarray(vsh, dtype=float)
    zones = list(dict.fromkeys(labels.dropna())) if labels is not None else [None]
    out = {}
    for column in SW_COLUMN_MAP.values():
        if column not in frames:
            continue
        flags = _concat_flags(frames[column], index)
        name = SW_MODEL_NAMES[column]
        entry = {key: int(flags[key].sum()) if key in flags else 0 for key in SW_DIAGNOSTIC_KEYS}
        by_zone = {}
        for zone in zones:
            mask = (np.ones(len(index), dtype=bool) if zone is None
                    else (labels == zone).to_numpy())
            samples = int(mask.sum())
            if not samples:
                continue
            counts = {key: int(flags.loc[mask, key].sum()) if key in flags else 0
                      for key in SW_DIAGNOSTIC_KEYS}
            counts["samples"] = samples
            if zone is not None:
                by_zone[zone] = counts
            where = f" (zone {zone})" if zone is not None else ""
            for key, text in (
                ("bvh_exceeds_phie",
                 "the hydrocarbon volume from total porosity is larger than the effective "
                 "porosity can hold, so it was limited to PHIE"),
                ("phie_above_phit", "effective porosity is above total porosity"),
            ):
                if counts[key] > INCONSISTENT_POROSITY_SHARE * samples:
                    warnings.add(
                        "BVH_CAPPED" if key == "bvh_exceeds_phie" else "PHIE_ABOVE_PHIT",
                        f"{name}{where}: {text} in {counts[key]} of {samples} samples. "
                        "Check that PHIE and PHIT come from the same inputs.",
                        zone=zone,
                    )
            cutoff = vsh_cutoffs.get(zone, default_cutoff)
            with np.errstate(invalid="ignore"):
                clean = mask & (vsh_a < cutoff)
            n_clean = int(clean.sum())
            n_upper = int((flags["at_upper_bound"].to_numpy() & clean).sum())
            if n_clean and n_upper > UPPER_BOUND_SHARE * n_clean:
                warnings.add(
                    "SW_AT_BOUND",
                    f"{name}{where}: Sw > 1 before clipping in {n_upper} clean samples: "
                    "check Rw, m, n or Rt.",
                    zone=zone,
                )
        if labels is not None:
            entry["zones"] = by_zone
        if entry["no_phit"]:
            warnings.add(
                "SW_NO_PHIT",
                f"{name}: {entry['no_phit']} samples have an effective porosity but no total "
                f"porosity, so {name} has no Sw there."
            )
        out[column] = entry
    return out


def _swirr_warnings(calcs, index, warnings, n_swirr=0):
    """Record Swirr samples that were limited or taken from Buckles; returns the counts.

    The floor and 0.60 counts are info, and a warning only when one of them
    exceeds ``SWIRR_COUNT_SHARE`` of the ``n_swirr`` samples that have a Swirr.
    Samples limited to the measured Sw are always info: ``min(Swirr, Sw)`` is the
    method's definition (kept on purpose, P0 spec section 12), not a correction.
    The returned dict has ``fallback_samples``, ``floor_samples``, ``limited_by_sw``
    and ``limited_to_max``.
    """
    counts = {"fallback_samples": 0, "floor_samples": 0, "limited_by_sw": 0, "limited_to_max": 0}
    parts = [c.swirr_flags for c in calcs if c.swirr_flags is not None]
    if not parts:
        return counts
    flags = _concat_flags(parts, index)

    def count(column):
        return int(flags[column].sum()) if column in flags else 0

    counts["floor_samples"] = n_raised = count("raised_to_floor")
    counts["limited_by_sw"] = n_by_sw = count("limited_by_sw")
    counts["limited_to_max"] = n_max = count("limited_to_max")
    counts["fallback_samples"] = count("buckles_fallback")

    def level(n):
        return "warning" if n > SWIRR_COUNT_SHARE * n_swirr else "info"

    if n_raised:
        warnings.add(
            "SWIRR_FLOOR",
            f"Hierarchical Swirr: {n_raised} samples were raised to the 0.05 floor "
            "(Swirr is never below 0.05, even where the measured Sw is).",
            severity=level(n_raised))
    if n_by_sw:
        warnings.add(
            "SWIRR_LIMITED",
            f"Hierarchical Swirr: {n_by_sw} samples were limited to the measured Sw "
            "(Swirr cannot exceed Sw).",
            severity="info")
    if n_max:
        warnings.add(
            "SWIRR_MAXED",
            f"Hierarchical Swirr: {n_max} samples were limited to the 0.60 maximum.",
            severity=level(n_max))
    return counts


def _swirr_method_label(method, n_fallback, warnings):
    """The Swirr method shown in the summary: the series actually used."""
    if method == "All Methods":
        return "All methods (Buckles used)"
    if n_fallback:
        warnings.add(
            "SWIRR_FALLBACK",
            f"Swirr method {method}: no value for {n_fallback} samples; "
            "Buckles Swirr was used for them."
        )
        return f"{method} (Buckles used for {n_fallback} samples)"
    return method


def _zone_curves(seg, curve_mapping, p, plan_entry, well, tctx, warnings):
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
        baseline = _zone_gr_baseline(seg, gr_curve, well["gr"])
        if baseline is None:
            baseline, sources["gr_baseline"] = _fallback_value("gr_baseline", plan_entry, well["gr"])
        elif len(baseline) == 3:
            sources["gr_baseline"] = f"auto ({baseline[2]})"
            baseline = baseline[:2]
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
    temp_factor = _factor(tctx)
    estimator_info = {"rw": {}, "rsh": {}}
    estimators = {
        "rw": lambda: _auto_rw(stats_util, calc, vsh, rt_curve, sp, temp_factor,
                               estimator_info["rw"]),
        "rsh": lambda: _auto_rsh(stats_util, vsh, rt_curve, temp_factor,
                                 estimator_info["rsh"]),
    }
    rsh_auto = well.get("rsh_auto", False)     # is the Rsh used an estimate at T_ref?
    for name, estimator in estimators.items():
        if name in zone_auto:
            estimate = estimator() if _enough_data(seg, rt_curve) else None
            _add_estimator_warnings(warnings, name.upper(),
                                    estimator_info[name].get("warnings", []))
            auto = estimate is not None
            if estimate is None:
                estimate, sources[name] = _fallback_value(name, plan_entry, well[name])
                auto = (plan_entry.get("fallback", {}).get(name, {}).get("scope") != PROJECT_ZONE
                        and well.get(f"{name}_auto", False))
            values[name] = estimate
        elif name in zone_keys:
            values[name], auto = sp[name], False
        else:
            values[name], auto = well[name], well.get(f"{name}_auto", False)
        if name == "rsh":
            rsh_auto = auto
    sp["rw"], sp["rsh"] = values["rw"], values["rsh"]
    sp["rw_mode"] = sp["rsh_mode"] = "manual"
    pay = _saturation_to_pay(calc, seg, curve_mapping, sp, vsh, values["rw"], values["rsh"],
                             tctx, warnings, rsh_auto)
    resolved = {"gr_baseline": [sp["gr_min_manual"], sp["gr_max_manual"]],
                "rw": values["rw"], "rsh": values["rsh"]}
    return calc, pay, _sources_table(sp, sources, resolved)


def _sources_table(p, sources, resolved):
    """``{param: {"value", "source"}}`` for every scoped parameter."""
    table = {}
    for name in SPECS:
        value = resolved[name] if name in resolved else flat_value(name, p)
        if name in OPTIONAL_SOURCE_PARAMS and value in OPTIONAL_SOURCE_PARAMS[name]:
            continue        # inactive optional parameter: nothing to report
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
def _saturation_to_pay(calc, data, curve_mapping, p, vsh, rw, rsh, tctx, warnings,
                       rsh_auto=False):
    """Sw, Swirr, permeability and pay flags on ``calc``.

    ``rw`` is a number (at the reference temperature when the Arps correction is
    on, ``tctx.factor``); ``rsh`` is an auto estimate at that temperature when
    ``rsh_auto`` or a manual value (see :func:`_rsh_effective`). Returns the
    ``vsh``/``phie``/``sw``/``swirr`` series used and the net-pay summary of
    this calculator's samples.
    """
    rt_curve = curve_mapping.get("RT", "RT")
    has_rt = _has(rt_curve, data)
    a, m, n = p["a"], p["m"], p["n"]
    temp_factor = _factor(tctx)
    rw_eff = rw if temp_factor is None else rw * temp_factor.loc[data.index]
    rsh_eff = _rsh_effective(rsh, rsh_auto, p, tctx, data.index)
    rwb_eff = p["dw_rwb"] if temp_factor is None else p["dw_rwb"] * temp_factor.loc[data.index]
    ws_b = p["ws_b"]
    if p.get("ws_b_auto") and tctx is not None:
        # Juhasz B at each sample's formation temperature with Rw AT that temperature.
        ws_b = juhasz_b(tctx.temp.loc[data.index], rw_eff)

    phie = calc.results.get("PHIE")
    if phie is None:
        # Never fabricate porosity: a sample without one has NaN Sw and no pay.
        phie = pd.Series(np.nan, index=data.index)

    phit = calc.results.get("PHIT")
    if phit is None:
        phit = pd.Series(np.nan, index=data.index)

    if has_rt:
        selected = p["sw_methods"]
        if "Archie" in selected:
            calc.calculate_sw_archie(rt_curve, phie, rw_eff, a, m, n)
        if "Indonesian" in selected:
            calc.calculate_sw_indonesian(rt_curve, phie, vsh, rw_eff, rsh_eff, a, m, n)
        if "Simandoux" in selected:
            calc.calculate_sw_simandoux(rt_curve, phie, vsh, rw_eff, rsh_eff, a, m, n)
        if "Waxman-Smits" in selected:
            # Total-porosity models: solved on PHIT, returned as effective Sw on PHIE.
            calc.calculate_sw_waxman_smits(rt_curve, phit, rw_eff, a, m, n, p["ws_qv"], ws_b,
                                           phie=phie)
        if "Dual-Water" in selected:
            calc.calculate_sw_dual_water(rt_curve, phit, rw_eff, a, m, n, p["dw_swb"], rwb_eff,
                                         phie=phie)

        primary_col = SW_COLUMN_MAP.get(p["sw_primary_method"], "SW_SIMAN")
        if primary_col in calc.results.columns:
            calc.results["SW"] = calc.results[primary_col]
        else:
            available = [c for c in SW_COLUMN_MAP.values() if c in calc.results.columns]
            if available:
                calc.results["SW"] = calc.results[available[0]]
            else:
                calc.results["SW"] = pd.Series([1.0] * len(data), index=data.index)
                warnings.add(
                    "SW_DEFAULTED_NO_METHOD",
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
    # Every Swirr method sets SWIRR; no constant stands in for a missing one.
    swirr = calc.results.get("SWIRR", pd.Series(np.nan, index=data.index))

    perm_timur = calc.calculate_permeability_timur(phie, swirr)
    calc.calculate_permeability_wyllie_rose(phie, swirr, p["perm_C"], p["perm_P"], p["perm_Q"])
    calc.classify_flow_units(perm_timur)
    calc.get_permeability_quality_flags(perm_timur, swirr, phie)

    sw_for_pay = calc.results.get("SW", pd.Series([1.0] * len(data), index=data.index))
    pay = calc.calculate_net_pay(
        vsh, phie, sw_for_pay, p["vsh_cutoff"], p["phi_cutoff"], p["sw_cutoff"]
    )
    return {"vsh": vsh, "phie": phie, "sw": sw_for_pay, "swirr": swirr, "summary": pay}


def _sample_dz(data: pd.DataFrame):
    """Per-sample thickness of the run's samples (:func:`depth_increments`), or 0.1 ft."""
    if "DEPTH" in data.columns:
        return depth_increments(data["DEPTH"])
    return 0.1


def _pay_stats(results, vsh, phie, sw, dz, mask=None):
    """Net-pay numbers from the stored flags (same arithmetic as ``calculate_net_pay``).

    ``dz`` is the per-sample thickness aligned with ``results`` (or a scalar);
    ``mask`` selects one zone's samples.
    """
    if mask is not None:
        results, vsh, phie, sw = results[mask], vsh[mask], phie[mask], sw[mask]
        if not np.isscalar(dz):
            dz = np.asarray(dz, dtype=float)[np.asarray(mask, dtype=bool)]
    return pay_summary(
        results["GROSS_SAND_FLAG"].astype(bool),
        results["NET_RES_FLAG"].astype(bool),
        results["NET_PAY_FLAG"].astype(bool),
        vsh, phie, sw, dz,
    )


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
    if not np.isscalar(step):
        step = np.asarray(step, dtype=float)[ok]
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
        float(np.sum(m * step)) for m in (gross, reservoir, pay))
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
    note = diag.get("note")
    base = _zone_status_note(diag)
    if not note:
        return base
    text = f"GR baseline: {note}."
    if base is None:
        return "info", text
    return base[0], f"{base[1]} {text}"


def _zone_status_note(diag):
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


def _zone_diagnostics_by_zone(labels, pay_series, step, sources_by_zone, log=None):
    """``{zone: diagnostics}`` using the cutoffs applied in each zone.

    A zone whose GRmax came from the well also adds an info ``ZONE_NO_SHALE`` to ``log``.
    """
    vsh, phie, sw = pay_series
    out = {}
    for zone in dict.fromkeys(labels.dropna()):
        mask = (labels == zone).to_numpy()
        table = sources_by_zone.get(zone, {})
        try:
            cutoffs = {k: table[k]["value"] for k, _ in ZONE_CUTOFFS}
        except KeyError:
            continue
        zone_step = step if np.isscalar(step) else np.asarray(step, dtype=float)[mask]
        out[zone] = _zone_diagnostics(vsh[mask], phie[mask], sw[mask], cutoffs, zone_step)
        note = str((table.get("gr_baseline") or {}).get("source", ""))
        if ZONE_NO_SHALE_NOTE in note:
            out[zone]["note"] = ZONE_NO_SHALE_NOTE
            if log is not None:
                log.add("ZONE_NO_SHALE", ZONE_NO_SHALE_NOTE, zone=zone)
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
    warnings = IssueLog()

    # Resistivity, density and slowness cannot be <= 0 (tool-off or casing
    # readings): NaN, counted. Session-restored frames bypass the parser.
    for logical in ("RT", "RHOB", "DT"):
        mnemonic = curve_mapping.get(logical, logical)
        for name, count in mask_nonpositive(data, [mnemonic]).items():
            warnings.add(f"{logical}_NONPOSITIVE",
                         f"{logical}: {count} samples ≤ 0 set to NaN" if name == logical
                         else f"{logical} ({name}): {count} samples ≤ 0 set to NaN")

    analysis_mode = p["analysis_mode"]
    selected_formations = p["selected_formations"]
    data = _filter_formations(data, p, formation_tops)
    missing = []
    if p["analysis_mode"] == "Per-Formation" and selected_formations and formation_tops:
        missing = formation_tops.missing_formations(selected_formations)
    if len(data) == 0:
        if missing and len(missing) == len(selected_formations):
            raise PipelineError(
                f"none of the selected formations ({', '.join(missing)}) "
                "exists in this well's tops")
        raise PipelineError("No data in selected formation(s)")
    if missing:
        warnings.add("FORMATION_MISSING",
                     f"Selected formations not in this well's tops: {', '.join(missing)}")

    labels = None
    if formation_tops is not None and getattr(formation_tops, "formations", None):
        labels, zone_warnings = assign_zones(data["DEPTH"], formation_tops)
        for text in zone_warnings:
            warnings.add("FORMATION_OVERLAP", text)
    plan = {}
    if labels is not None:
        present = set(labels.unique())
        plan = {z: e for z, e in (p.get("zone_plan") or {}).items() if z in present}

    emit("Initializing calculator...", 10)
    calc = PetrophysicsCalculator(data)
    stats_util = StatisticsUtils(data)
    rt_curve = curve_mapping.get("RT", "RT")
    has_rt = _has(rt_curve, data)
    tctx = temperature_context(data, p, curve_mapping)
    if tctx is not None:
        for note in tctx.source["notes"]:
            warnings.add("TEMPERATURE_NOTE", note)
        if p.get("ws_b_auto") and tctx.factor is None:
            warnings.add(
                "WS_B_RW_UNCORRECTED",
                "WS B from temperature uses Rw as entered (the Rw temperature correction is off)."
            )

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
    rw_rsh_info = {}
    if has_rt:
        rw, rsh, rw_source, rsh_source = _resolve_rw_rsh(
            stats_util, calc, vsh, rt_curve, p, warnings, tctx, rw_rsh_info
        )
    rsh_auto = rsh_source == "auto"
    well_sources = _well_sources(p, rw_source, rsh_source, shale_failed)
    well_table = _sources_table(
        p, well_sources, {"gr_baseline": [gr_min, gr_max], "rw": rw, "rsh": rsh}
    )
    sources_by_zone = {}
    solver_raw = {}
    flag_calcs = []     # calculators whose per-sample Sw / Swirr flags feed the diagnostics

    if not plan:
        emit("Calculating Swirr...", 65)
        pay = _saturation_to_pay(calc, data, curve_mapping, p, vsh, rw, rsh, tctx, warnings,
                                 rsh_auto)
        emit("Calculating permeability...", 75)
        emit("Calculating net pay...", 85)
        summary = dict(pay["summary"])
        _merge_diagnostics(solver_raw, calc.solver_diagnostics)
        flag_calcs.append(calc)
    else:
        # Planned zones run as their own segments; every other sample runs
        # together with the well's parameters.
        well = {"gr": (gr_min, gr_max), "rw": rw, "rsh": rsh, "rsh_auto": rsh_auto,
                "sources": well_sources}
        zones = [z for z in _segment_order(labels, data["DEPTH"]) if z in plan]
        parts, pays = [], []
        for i, zone in enumerate(zones):
            emit(f"Calculating zone {zone}...", 55 + int(25 * i / len(zones)))
            seg_calc, seg_pay, table = _zone_curves(
                data[labels == zone], curve_mapping, p, plan[zone], well, tctx, warnings
            )
            parts.append(seg_calc.results)
            pays.append(seg_pay)
            sources_by_zone[zone] = table
            _merge_diagnostics(solver_raw, seg_calc.solver_diagnostics)
            flag_calcs.append(seg_calc)
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
                                           rw, rsh, tctx, warnings, rsh_auto))
            parts.append(rest_calc.results)
            _merge_diagnostics(solver_raw, rest_calc.solver_diagnostics)
            flag_calcs.append(rest_calc)
        emit("Calculating net pay...", 85)
        calc.results = pd.concat(parts).reindex(data.index)
        pay = {k: pd.concat([pp[k] for pp in pays]).reindex(data.index)
               for k in ("vsh", "phie", "sw", "swirr")}
        summary = _pay_stats(calc.results, pay["vsh"], pay["phie"], pay["sw"], _sample_dz(data))
        warnings.dedupe()

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
    renamed = getattr(calc, "renamed_inputs", [])
    if renamed:
        warnings.add(
            "INPUT_RENAMED",
            f"input curves {', '.join(renamed)} kept as "
            f"{', '.join(c + '_IN' for c in renamed)}")
    summary["gr_min"] = gr_min
    summary["gr_max"] = gr_max
    summary["rw"] = rw
    summary["rsh"] = rsh
    summary["rw_source"] = rw_source
    summary["rsh_source"] = rsh_source
    summary.update(rw_rsh_info)     # rw_quality and sample counts, only for auto Rw / Rsh
    n_swirr = int(pay["swirr"].notna().sum())
    swirr_counts = _swirr_warnings(flag_calcs, data.index, warnings, n_swirr)
    summary["swirr_method"] = _swirr_method_label(
        p["swirr_method"], swirr_counts["fallback_samples"], warnings)
    summary["swirr_diagnostics"] = {
        "method_used": summary["swirr_method"], "samples": n_swirr, **swirr_counts}
    summary["swirr_mean"] = pay["swirr"].mean()
    summary["analysis_mode"] = analysis_mode
    summary["selected_formations"] = selected_formations
    summary["data_points"] = len(data)
    if tctx is not None and tctx.factor is not None:
        rw_at_depth = rw * tctx.factor
        summary["rw_ref_temp"] = float(p["rw_ref_temp"])
        summary["rw_at_depth_range"] = [float(rw_at_depth.min()), float(rw_at_depth.max())]
        # Rsh: auto estimates are at the Rw reference temperature; a manual one
        # is corrected only from rsh_ref_temp.
        rsh_ref = float(p["rw_ref_temp"]) if rsh_auto else p.get("rsh_ref_temp")
        rsh_at_depth = _rsh_effective(rsh, rsh_auto, p, tctx, data.index)
        summary["rsh_temperature"] = {
            "corrected": rsh_ref is not None,
            "ref_temp": None if rsh_ref is None else float(rsh_ref),
            "range": [float(np.min(rsh_at_depth)), float(np.max(rsh_at_depth))],
        }
    if tctx is not None:
        summary["temperature"] = tctx.source

    param_sources = {WELL_SOURCES_KEY: well_table}
    if tctx is not None:
        param_sources["temperature"] = tctx.source
    if labels is not None:
        for zone in _segment_order(labels, data["DEPTH"]):
            param_sources[zone] = sources_by_zone.get(zone, well_table)
    summary["param_sources"] = param_sources
    summary["zones"] = (
        _zone_rows(calc.results, labels, data, (pay["vsh"], pay["phie"], pay["sw"]),
                   _sample_dz(data), param_sources)
        if labels is not None else []
    )
    if summary["zones"]:
        summary["zone_diagnostics"] = _zone_diagnostics_by_zone(
            labels, (pay["vsh"], pay["phie"], pay["sw"]),
            _sample_dz(data), param_sources, warnings)

    vsh_cutoffs = {}
    for zone in (dict.fromkeys(labels.dropna()) if labels is not None else ()):
        try:
            vsh_cutoffs[zone] = float(param_sources[zone]["vsh_cutoff"]["value"])
        except (KeyError, TypeError, ValueError):
            pass
    solver_diagnostics = _sw_solver_diagnostics(
        flag_calcs, labels, data.index, pay["vsh"], vsh_cutoffs, p["vsh_cutoff"], warnings
    )
    for method, diagnostics in solver_raw.items():
        counts = solver_diagnostics.setdefault(method, {
            "no_root": int(diagnostics.get("no_root", 0)),
            "failed": int(diagnostics.get("failed", 0)),
        })
        if counts["no_root"] or counts["failed"]:
            warnings.add(
                "SOLVER_FAILED",
                f"{method}: {counts['no_root']} no-root, {counts['failed']} failed solver points."
            )
    summary["solver_diagnostics"] = solver_diagnostics

    if not has_rt:
        warnings.add("SW_DEFAULTED_NO_RT",
                     "Water saturation defaulted to 1.0 because no RT curve was available.")
    summary["warnings"] = list(warnings)
    summary["issues"] = list(warnings.issues)

    if "HCPV_CUM" in hcpv:
        def _last(series):
            return float(series.iloc[-1]) if len(series) > 0 else 0.0
        summary["hcpv_gross"] = _last(hcpv["HCPV_CUM"])
        summary["hcpv_net_res"] = _last(hcpv["HCPV_CUM_NET_RES"])
        summary["hcpv_net_pay"] = _last(hcpv["HCPV_CUM_NET_PAY"])

    emit("Analysis complete!", 100)
    return results, summary
