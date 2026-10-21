"""Saturation-height settings kept on the project (pure, no Qt).

``SHF_DEFAULTS`` is the shape of ``Project.shf``: plain JSON types and string keys, so
the session writer can store it as is. ``merge_shf`` reads a stored dict back tolerantly.
"""

import copy
import math
from typing import Any, Dict

from modules.shf import DEFAULT_FLUIDS, SIGMA_COS_DEFAULTS

# Fluid densities (g/cc) and sigma*cos(theta) (dyne/cm) by system come from modules.shf.
SHF_DEFAULTS: Dict[str, Any] = {
    "enabled": False,
    "use_for_pay": False,
    "phie_source": "PHIE",
    "perm_source": "auto",
    "fallback": "none",
    "rock_type_source": "auto",
    "weight_by": "sample",
    "min_pc_psi": 0.0,
    "fluids": dict(DEFAULT_FLUIDS),
    "sigma_cos": dict(SIGMA_COS_DEFAULTS),
    "fits": {},
}


def shf_defaults() -> Dict[str, Any]:
    """A fresh deep copy of the defaults."""
    return copy.deepcopy(SHF_DEFAULTS)


def _is_number(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def merge_shf(stored) -> Dict[str, Any]:
    """Defaults overlaid with the stored settings.

    Unknown keys are dropped and a value of the wrong type falls back to its default, so
    a session written by another version never breaks the load.
    """
    out = shf_defaults()
    if not isinstance(stored, dict):
        return out
    for key, default in SHF_DEFAULTS.items():
        if key not in stored:
            continue
        value = stored[key]
        if key == "fits":
            if isinstance(value, dict):
                out[key] = {str(k): copy.deepcopy(v) for k, v in value.items()}
        elif isinstance(default, dict):
            if isinstance(value, dict):
                for sub in default:
                    if _is_number(value.get(sub)):
                        out[key][sub] = float(value[sub])
        elif isinstance(default, bool):
            if isinstance(value, bool):
                out[key] = value
        elif isinstance(default, float):
            if _is_number(value):
                out[key] = float(value)
        elif isinstance(default, str):
            if isinstance(value, str) and value:
                out[key] = value
    return out


def _non_empty(value) -> bool:
    if value is None:
        return False
    empty = getattr(value, "empty", None)
    if empty is not None:
        return not empty
    try:
        return len(value) > 0
    except TypeError:
        return bool(value)


def shf_in_use(project) -> bool:
    """True when the project holds saturation-height content worth saving.

    That is SHF switched on, any stored fit, any Pc data or any fluid contact.
    """
    shf = getattr(project, "shf", None) or {}
    if shf.get("enabled") or shf.get("fits"):
        return True
    try:
        wells = list(project)
    except TypeError:          # not a Project (a bare model in older callers)
        return False
    for ds in wells:
        if _non_empty(getattr(ds, "pc_data", None)) or _non_empty(getattr(ds, "shf_contacts", None)):
            return True
    return False
