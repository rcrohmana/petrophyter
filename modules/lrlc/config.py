"""LRLC settings kept on the project and per well (pure, no Qt).

``LRLC_DEFAULTS`` is the shape of ``Project.lrlc``: plain JSON types and string keys, so the
session writer can store it as is. ``merge_lrlc`` reads a stored dict back tolerantly (the
twin of ``modules.shf_config.merge_shf``).

The ladder parameters (``LRLC_PARAM_DEFAULTS``) are resolved per zone from four levels, later
wins per key: built-in, project default, project zone, well default, well zone.

A well's own levels (``WellDataset.lrlc``) are ``{}`` while nothing is set (that is "not in
use"), else ``{"default": {...}, "zones": {ZONE: {...}}}`` with empty parts allowed.

This module must not import ``modules.lrlc.chain``: ``rt_steps`` takes any strings.
"""

import copy
import math
from typing import Any, Dict, List, Optional, Tuple

from modules.param_scopes import normalize_zone

# Auxiliary curve roles a well can map (``WellDataset.lrlc_curves``).
AUX_ROLES = ("RM", "RS", "RXO", "PEF", "DTS", "HIRES")
# Marker keys stored beside the roles in ``WellDataset.lrlc_curves`` (not curve roles):
# ``RT_SBC`` names the log curve the user declares shoulder-bed corrected.
CURVE_MARKERS = ("RT_SBC",)

LEVEL_BUILTIN = "built-in"
LEVEL_PROJECT_DEFAULT = "project default"
LEVEL_PROJECT_ZONE = "project zone"
LEVEL_WELL_DEFAULT = "well default"
LEVEL_WELL_ZONE = "well zone"

# Pickett plot / fit options (Workbench-only: saved, never hashed).
PICKETT_DEFAULTS: Dict[str, Any] = {
    "phi_source": "PHIE",
    "color_by": "VSH",
    "vsh_max": 0.25,
    "phi_min": 0.05,
    "wet_quantile": 0.10,
    "n_bins": 8,
    "min_points": 10,
    "fit_mode": "m_and_rw",
    "iso_sw": [1.0, 0.8, 0.6, 0.4, 0.2],
}
PHI_SOURCES = ("PHIE", "PHIT")
COLOR_BY = ("VSH", "zone")
FIT_MODES = ("m_and_rw", "rw_only")

# Thomas-Stieber decomposition settings (spec L2 3.5).
THOMAS_STIEBER_DEFAULTS: Dict[str, Any] = {
    "enabled": False,
    "vsh_column": "VSH",
    "clean_vsh": 0.05,
    "clean_pct": 90.0,
    "clean_min_n": 30,
    "shale_vsh": 0.80,
    "shale_min_n": 10,
    "class_share": 0.20,
    "class_tol": 0.03,
    "class_vsh_min": 0.05,
    "class_vsh_max": 0.95,
}

PYRITE_DEFAULTS: Dict[str, Any] = {
    "enabled": False,
    "u_fluid": 0.4,
    "pef_max": 25.0,
    "neg_tol": 0.01,
    "vpyr_max": 0.25,
}

QV_DEFAULTS: Dict[str, Any] = {
    "phi_min": 0.03,
    "qv_max": 3.0,
    "pair_tol_ft": 0.5,
    "min_pairs": 5,
}

GUARD_DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "vlam_share": 0.50,
    "min_vlam": 0.05,
    "vsh_min": 0.10,
}

DIAGNOSIS_DEFAULTS: Dict[str, Any] = {
    "min_n": 10,
    "bvw_cv_max": 0.20,
    "rw_low": 0.06,
    "contrast_low": 3.0,
    "vpyr_flag": 0.01,
    "pef_flag": 4.0,
    "qv_high": 0.30,
    "vsh_clay": 0.15,
    "dsw_clay": 0.10,
}

LRLC_DEFAULTS: Dict[str, Any] = {
    "enabled": False,
    "screening": {"use_gas_flag": True, "use_rs": True},
    "rt_cutoff": {"enabled": False},
    "movable": {"swirr_column": "SWIRR"},
    "pickett": PICKETT_DEFAULTS,
    "buckles": {"bvw_lines": [0.02, 0.04, 0.06, 0.08, 0.10]},
    "thomas_stieber": THOMAS_STIEBER_DEFAULTS,
    "pyrite": PYRITE_DEFAULTS,
    "qv": QV_DEFAULTS,
    "guard": GUARD_DEFAULTS,
    "diagnosis": DIAGNOSIS_DEFAULTS,
    "params": {"default": {}, "zones": {}},
}

# Blocks that only drive Workbench plots: they never raise the session version.
WORKBENCH_ONLY = ("pickett", "buckles")

# Blocks added with session format 2.6 (laminated sands, minerals, Qv, guard, diagnosis).
L2_BLOCKS = ("thomas_stieber", "pyrite", "qv", "guard", "diagnosis")

# Inclusive (low, high) for the numeric keys of the setting blocks; a stored value outside
# falls back to the default.
BLOCK_RANGES: Dict[str, Dict[str, Tuple[float, float]]] = {
    "thomas_stieber": {
        "clean_vsh": (0.01, 0.15), "clean_pct": (50.0, 99.0), "clean_min_n": (5, 1000),
        "shale_vsh": (0.5, 0.99), "shale_min_n": (3, 1000), "class_share": (0.05, 0.45),
        "class_tol": (0.0, 0.15), "class_vsh_min": (0.0, 0.5), "class_vsh_max": (0.5, 1.0),
    },
    "pyrite": {
        "u_fluid": (0.0, 2.0), "pef_max": (5.0, 100.0), "neg_tol": (0.0, 0.1),
        "vpyr_max": (0.01, 0.5),
    },
    "qv": {
        "phi_min": (0.0, 0.2), "qv_max": (0.1, 20.0), "pair_tol_ft": (0.0, 5.0),
        "min_pairs": (2, 1000),
    },
    "guard": {"vlam_share": (0.1, 0.95), "min_vlam": (0.0, 0.5), "vsh_min": (0.0, 0.5)},
    "diagnosis": {
        "min_n": (1, 10000), "bvw_cv_max": (0.0, 2.0), "rw_low": (0.001, 10.0),
        "contrast_low": (1.0, 100.0), "vpyr_flag": (0.0, 0.5), "pef_flag": (0.0, 20.0),
        "qv_high": (0.0, 20.0), "vsh_clay": (0.0, 1.0), "dsw_clay": (0.0, 1.0),
    },
}

LRLC_PARAM_DEFAULTS: Dict[str, Any] = {
    "rt_steps": [],
    "rt_fallback": "nan",
    "screen_rt_max": 5.0,
    "screen_contrast_max": 2.0,
    "screen_min_score": 5,
    "cut_sw_target": None,
    "movable_tol": 0.05,
    # Thomas-Stieber end-points and the Vlam the laminated step reads (None = not applied).
    "phi_max": None,
    "phi_sh": None,
    "vlam_source": "ts",
    "vlam_const": 0.0,
    # Laminated-sand Rt (Hagiwara) and the sensitivity limits shared with the pyrite step.
    "hag_vsh_max": 0.80,
    "s_warn": 0.80,
    "s_invalid": 0.95,
    "sw_basis": "auto",
    # Pyrite volume and correction (None = the zone's rho_matrix / rho_shale).
    "pyr_method": "manual",
    "pyr_vpyr": 0.0,
    "pyr_rho": 4.99,
    "pyr_pef": 16.97,
    "ma_rho": None,
    "ma_pef": 1.81,
    "sh_rho": None,
    "sh_pef": 3.4,
    "pyr_f": 0.0,
    "pyr_rpy": 0.01,
    # Qv estimate for Waxman-Smits (None = the zone's rho_matrix).
    "qv_source": "manual",
    "cec_shale": 25.0,
    "qv_rho_g": None,
}

RT_FALLBACKS = ("nan", "previous")

# String-valued ladder keys and their allowed values.
LRLC_CHOICES: Dict[str, Tuple[str, ...]] = {
    "rt_fallback": RT_FALLBACKS,
    "vlam_source": ("ts", "constant"),
    "sw_basis": ("auto", "sand", "bulk"),
    "pyr_method": ("manual", "rhob_pef"),
    "qv_source": ("manual", "estimate"),
}

# Numeric ladder keys that also accept None.
LRLC_NULLABLE = ("cut_sw_target", "phi_max", "phi_sh", "ma_rho", "sh_rho", "qv_rho_g")

# Ladder keys added with session format 2.6.
L2_PARAM_KEYS = (
    "phi_max", "phi_sh", "vlam_source", "vlam_const", "hag_vsh_max", "s_warn", "s_invalid",
    "sw_basis", "pyr_method", "pyr_vpyr", "pyr_rho", "pyr_pef", "ma_rho", "ma_pef", "sh_rho",
    "sh_pef", "pyr_f", "pyr_rpy", "qv_source", "cec_shale", "qv_rho_g",
)
# Chain steps added with session format 2.6.
L2_STEPS = ("laminated", "pyrite")

# Inclusive (low, high) for the numeric keys. Cross-key rules (phi_sh < phi_max - 0.02,
# s_warn < s_invalid) are checked where the values are used, not here.
LRLC_RANGES: Dict[str, Tuple[float, float]] = {
    "screen_rt_max": (0.2, 100.0),
    "screen_contrast_max": (0.5, 50.0),
    "screen_min_score": (3, 6),
    "cut_sw_target": (0.05, 0.95),
    "movable_tol": (0.0, 0.30),
    "phi_max": (0.10, 0.45),
    "phi_sh": (0.0, 0.40),
    "vlam_const": (0.0, 0.9),
    "hag_vsh_max": (0.5, 0.99),
    "s_warn": (0.5, 0.99),
    "s_invalid": (0.5, 0.99),
    "pyr_vpyr": (0.0, 0.25),
    "pyr_rho": (3.0, 6.0),
    "pyr_pef": (5.0, 25.0),
    "ma_rho": (2.0, 3.2),
    "ma_pef": (0.0, 10.0),
    "sh_rho": (1.8, 3.2),
    "sh_pef": (0.0, 10.0),
    "pyr_f": (0.0, 1.0),
    "pyr_rpy": (1e-5, 10.0),
    "cec_shale": (1.0, 150.0),
    "qv_rho_g": (2.0, 3.2),
}

SWIRR_COLUMNS = ("SWIRR", "SWIRR_BUCKLES", "SWIRR_CLEANZONE", "SWIRR_STAT")


def lrlc_defaults() -> Dict[str, Any]:
    """A fresh deep copy of the defaults."""
    return copy.deepcopy(LRLC_DEFAULTS)


def _is_number(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


# ---------------------------------------------------------------------------
# Ladder parameters
# ---------------------------------------------------------------------------
def clean_param(key: str, value) -> Tuple[Any, bool]:
    """``(value, True)`` for a valid ladder value, else ``(None, False)``.

    Type and range checked; ``cut_sw_target`` also accepts ``None`` (the zone's own
    ``sw_cutoff``). Unknown keys are invalid.
    """
    if key not in LRLC_PARAM_DEFAULTS:
        return None, False
    if key == "rt_steps":
        if isinstance(value, (list, tuple)) and all(isinstance(s, str) for s in value):
            return list(value), True
        return None, False
    if key in LRLC_CHOICES:
        if isinstance(value, str) and value in LRLC_CHOICES[key]:
            return value, True
        return None, False
    if key in LRLC_NULLABLE and value is None:
        return None, True
    if not _is_number(value):
        return None, False
    lo, hi = LRLC_RANGES[key]
    if key == "screen_min_score":
        if float(value) != int(value):
            return None, False
        value = int(value)
    else:
        value = float(value)
    if value < lo or value > hi:
        return None, False
    return value, True


def _clean_level(level) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if isinstance(level, dict):
        for key, value in level.items():
            cleaned, ok = clean_param(str(key), value)
            if ok:
                out[str(key)] = cleaned
    return out


def clean_params(stored) -> Dict[str, Any]:
    """``{"default": {...}, "zones": {ZONE: {...}}}`` from stored data (invalid parts dropped).

    Always the full shape; empty zone levels are kept out.
    """
    out: Dict[str, Any] = {"default": {}, "zones": {}}
    if not isinstance(stored, dict):
        return out
    out["default"] = _clean_level(stored.get("default"))
    zones = stored.get("zones")
    if isinstance(zones, dict):
        for name, level in zones.items():
            zone = normalize_zone(name)
            cleaned = _clean_level(level)
            if zone and cleaned:
                out["zones"][zone] = cleaned
    return out


def clean_well_lrlc(stored) -> Dict[str, Any]:
    """A well's own ladder levels from stored data: ``{}`` when nothing valid is set."""
    params = clean_params(stored)
    if not params["default"] and not params["zones"]:
        return {}
    return params


def clean_curves(stored) -> Dict[str, Optional[str]]:
    """Auxiliary curve assignments: known roles only, value a non-empty string or ``None``."""
    out: Dict[str, Optional[str]] = {}
    if not isinstance(stored, dict):
        return out
    for role in AUX_ROLES + CURVE_MARKERS:
        if role not in stored:
            continue
        value = stored[role]
        if value is None:
            out[role] = None
        elif isinstance(value, str) and value:
            out[role] = value
    return out


# ---------------------------------------------------------------------------
# Project block
# ---------------------------------------------------------------------------
def _merge_block(key: str, default, value, out) -> None:
    """Overlay one dict block of the project settings (tolerant)."""
    if not isinstance(value, dict):
        return
    block = out[key]
    for sub, sub_default in default.items():
        if sub not in value:
            continue
        v = value[sub]
        if isinstance(sub_default, bool):
            if isinstance(v, bool):
                block[sub] = v
        elif isinstance(sub_default, list):
            if (isinstance(v, (list, tuple)) and v and all(_is_number(x) for x in v)):
                block[sub] = [float(x) for x in v]
        elif isinstance(sub_default, int):
            if _is_number(v) and float(v) == int(v) and int(v) >= 1:
                block[sub] = int(v)
        elif isinstance(sub_default, float):
            if _is_number(v):
                block[sub] = float(v)
        elif isinstance(sub_default, str):
            if isinstance(v, str) and v:
                block[sub] = v
    for sub, (lo, hi) in BLOCK_RANGES.get(key, {}).items():
        if not lo <= block[sub] <= hi:
            block[sub] = copy.deepcopy(default[sub])
    if key == "pickett":
        if block["phi_source"] not in PHI_SOURCES:
            block["phi_source"] = PICKETT_DEFAULTS["phi_source"]
        if block["color_by"] not in COLOR_BY:
            block["color_by"] = PICKETT_DEFAULTS["color_by"]
        if block["fit_mode"] not in FIT_MODES:
            block["fit_mode"] = PICKETT_DEFAULTS["fit_mode"]


def merge_lrlc(stored) -> Dict[str, Any]:
    """Defaults overlaid with the stored settings.

    Unknown keys are dropped and a value of the wrong type falls back to its default, so a
    session written by another version never breaks the load.
    """
    out = lrlc_defaults()
    if not isinstance(stored, dict):
        return out
    if isinstance(stored.get("enabled"), bool):
        out["enabled"] = stored["enabled"]
    for key in ("screening", "rt_cutoff", "movable", "pickett", "buckles") + L2_BLOCKS:
        _merge_block(key, LRLC_DEFAULTS[key], stored.get(key), out)
    out["params"] = clean_params(stored.get("params"))
    return out


def _non_empty(value) -> bool:
    if value is None:
        return False
    try:
        return len(value) > 0
    except TypeError:
        return bool(value)


def lrlc_in_use(project) -> bool:
    """True when the project holds LRLC content worth saving.

    That is LRLC switched on, any setting or ladder value differing from the defaults
    (excluding the Workbench-only ``pickett`` and ``buckles`` blocks), or any well with its own
    ladder levels or curve assignments.
    """
    lrlc = getattr(project, "lrlc", None) or {}
    if lrlc.get("enabled"):
        return True
    defaults = lrlc_defaults()
    for key in defaults:
        if key in WORKBENCH_ONLY or key == "enabled":
            continue
        if key in lrlc and lrlc[key] != defaults[key]:
            return True
    try:
        wells = list(project)
    except TypeError:          # not a Project (a bare model in older callers)
        return False
    for ds in wells:
        if _non_empty(getattr(ds, "lrlc", None)) or _non_empty(getattr(ds, "lrlc_curves", None)):
            return True
    return False


def _levels_of(params):
    if not isinstance(params, dict):
        return []
    zones = params.get("zones") or {}
    return [params.get("default") or {}] + [z for z in zones.values() if isinstance(z, dict)]


def _level_uses_l2(level) -> bool:
    if any(key in level for key in L2_PARAM_KEYS):
        return True
    steps = level.get("rt_steps") or []
    return any(step in L2_STEPS for step in steps)


def lrlc_l2_configured(project) -> bool:
    """True when the project uses a setting of session format 2.6.

    That is a 2.6 setting block differing from its default (the guard on, its default, is
    not "configured"), a 2.6 ladder key or a ``laminated`` / ``pyrite`` step at any level,
    or a curve marked shoulder-bed corrected.
    """
    lrlc = getattr(project, "lrlc", None) or {}
    defaults = lrlc_defaults()
    for key in L2_BLOCKS:
        if key in lrlc and lrlc[key] != defaults[key]:
            return True
    if any(_level_uses_l2(level) for level in _levels_of(lrlc.get("params"))):
        return True
    try:
        wells = list(project)
    except TypeError:
        return False
    for ds in wells:
        if any(_level_uses_l2(level) for level in _levels_of(getattr(ds, "lrlc", None))):
            return True
        curves = getattr(ds, "lrlc_curves", None) or {}
        if any(curves.get(marker) for marker in CURVE_MARKERS):
            return True
    return False


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------
def _levels(params, zone):
    """``(default level, zone level)`` of one ``{"default", "zones"}`` store."""
    if not isinstance(params, dict):
        return {}, {}
    default = params.get("default") or {}
    zones = params.get("zones") or {}
    z = normalize_zone(zone) if zone is not None else None
    return default, (zones.get(z) or {} if z else {})


def resolve_lrlc_sources(project_params, well_params, zone) -> Dict[str, Tuple[Any, str]]:
    """``{key: (value, level)}`` for one zone, later levels winning per key."""
    out = {k: (copy.deepcopy(v), LEVEL_BUILTIN) for k, v in LRLC_PARAM_DEFAULTS.items()}
    p_default, p_zone = _levels(project_params, zone)
    w_default, w_zone = _levels(well_params, zone)
    for level_name, level in ((LEVEL_PROJECT_DEFAULT, p_default), (LEVEL_PROJECT_ZONE, p_zone),
                              (LEVEL_WELL_DEFAULT, w_default), (LEVEL_WELL_ZONE, w_zone)):
        for key, value in level.items():
            if key in out:
                out[key] = (copy.deepcopy(value), level_name)
    return out


def resolve_lrlc(project_params, well_params, zone) -> Dict[str, Any]:
    """The full ladder dict for one zone (a ``None`` or unknown zone gets the default levels)."""
    return {k: v for k, (v, _) in resolve_lrlc_sources(project_params, well_params, zone).items()}


def ladder_zones(project_params, well_params) -> List[str]:
    """Zone names that either ladder mentions, in first-seen order."""
    names: List[str] = []
    for params in (project_params, well_params):
        if isinstance(params, dict):
            for z in (params.get("zones") or {}):
                if z not in names:
                    names.append(z)
    return names
