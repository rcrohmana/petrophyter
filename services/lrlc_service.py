"""LRLC writes (no Qt widgets, no pipeline).

The LRLC Workbench changes the model only through these functions: each one marks the session
dirty, and the caller asks for the stale recompute (``stale_requested``). Nothing here runs the
analysis.

Levels: ``"project"`` writes ``Project.lrlc["params"]``; ``"well"`` writes the well's own
``ds.lrlc`` (the active well unless ``ds`` is given). ``zone=None`` is the level's default.
"""

import copy
import datetime
from typing import Any, Optional

from modules.lrlc.config import (
    AUX_ROLES, LRLC_PARAM_DEFAULTS, clean_param, lrlc_defaults)
from modules.param_scopes import normalize_zone

LEVELS = ("project", "well")
SETTING_BLOCKS = ("screening", "rt_cutoff", "movable", "pickett", "buckles")


class LrlcService:
    """Static writers for the LRLC settings."""

    @staticmethod
    def set_enabled(model, on: bool) -> None:
        model.project.lrlc["enabled"] = bool(on)
        model.mark_dirty()

    @staticmethod
    def _store(model, level: str, ds=None) -> dict:
        """The ``{"default", "zones"}`` store of a level, created when missing."""
        if level == "project":
            params = model.project.lrlc.setdefault("params", {"default": {}, "zones": {}})
        elif level == "well":
            ds = ds if ds is not None else model.active_well
            if ds is None:
                raise ValueError("no active well")
            if not ds.lrlc:
                ds.lrlc = {"default": {}, "zones": {}}
            params = ds.lrlc
        else:
            raise ValueError(f"unknown level {level!r}")
        params.setdefault("default", {})
        params.setdefault("zones", {})
        return params

    @staticmethod
    def _level_dict(params: dict, zone: Optional[str], create: bool) -> Optional[dict]:
        if zone is None:
            return params["default"]
        z = normalize_zone(zone)
        if not z:
            return params["default"]
        if create:
            return params["zones"].setdefault(z, {})
        return params["zones"].get(z)

    @staticmethod
    def set_param(model, level: str, zone: Optional[str], key: str, value: Any,
                  ds=None) -> bool:
        """Set one ladder value. False (nothing written) when the value is invalid."""
        cleaned, ok = clean_param(key, value)
        if not ok:
            return False
        params = LrlcService._store(model, level, ds)
        LrlcService._level_dict(params, zone, True)[key] = cleaned
        model.mark_dirty()
        return True

    @staticmethod
    def clear_param(model, level: str, zone: Optional[str], key: str, ds=None) -> bool:
        """Remove one ladder value from a level (the next level down shows through)."""
        if key not in LRLC_PARAM_DEFAULTS:
            return False
        if level == "well":
            target = ds if ds is not None else model.active_well
            if target is None or not target.lrlc:
                return False
        params = LrlcService._store(model, level, ds)
        d = LrlcService._level_dict(params, zone, False)
        if d is None or key not in d:
            return False
        del d[key]
        if zone is not None:
            z = normalize_zone(zone)
            if z and not params["zones"].get(z):
                params["zones"].pop(z, None)
        if level == "well" and not params["default"] and not params["zones"]:
            (ds if ds is not None else model.active_well).lrlc = {}
        model.mark_dirty()
        return True

    @staticmethod
    def set_curve(model, ds, role: str, mnemonic: Optional[str]) -> bool:
        """Assign an auxiliary curve role (``None`` = not used)."""
        if role not in AUX_ROLES or ds is None:
            return False
        ds.lrlc_curves[role] = mnemonic if mnemonic else None
        model.mark_dirty()
        return True

    @staticmethod
    def clear_curve(model, ds, role: str) -> bool:
        """Drop a user assignment, so the role is auto-detected again."""
        if ds is None or role not in (ds.lrlc_curves or {}):
            return False
        del ds.lrlc_curves[role]
        model.mark_dirty()
        return True

    @staticmethod
    def set_setting(model, block: str, key: str, value: Any) -> bool:
        """Set one key of a project settings block (screening, rt_cutoff, movable, pickett,
        buckles). Unknown blocks or keys write nothing."""
        if block not in SETTING_BLOCKS:
            return False
        current = model.project.lrlc.get(block)
        if not isinstance(current, dict) or key not in lrlc_defaults()[block]:
            return False
        current[key] = copy.deepcopy(value)
        model.mark_dirty()
        return True

    @staticmethod
    def apply_pickett(model, well, zone: Optional[str], fit, apply_rw: bool) -> bool:
        """Write a Pickett fit into the existing scoped ``m`` (and ``rw``) of the well.

        Only a fit with status ``"ok"`` is applied. ``zone=None`` writes the well scope, a zone
        name the well-zone scope; the project scope is never written. ``a`` and ``n`` are not
        touched; the Rw written is the fit's ``rw`` (``a_rw / a``).
        """
        if fit is None or getattr(fit, "status", None) != "ok" or well is None:
            return False
        meta = dict(source="pickett", method="Pickett wet-point fit",
                    date=datetime.date.today().isoformat())
        z = normalize_zone(zone) if zone else None
        model.set_entry("m", "manual", round(float(fit.m), 3), scope="well", zone=z,
                        well=well, **meta)
        if apply_rw:
            model.set_entry("rw", "manual", round(float(fit.rw), 4), scope="well", zone=z,
                            well=well, **meta)
        model.mark_dirty()
        return True
