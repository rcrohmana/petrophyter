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

import math

import numpy as np

from modules.lrlc.config import (
    AUX_ROLES, BLOCK_RANGES, CURVE_MARKERS, L2_BLOCKS, LRLC_PARAM_DEFAULTS, clean_param,
    lrlc_defaults, resolve_lrlc)
from modules.param_scopes import UNZONED, normalize_zone

LEVELS = ("project", "well")
SETTING_BLOCKS = ("screening", "rt_cutoff", "movable", "pickett", "buckles") + L2_BLOCKS


def _is_num(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _clean_block_value(block: str, key: str, default, value):
    """``(value, True)`` for a valid value of a settings block key of the laminated, mineral,
    Qv, guard and diagnosis blocks, else ``(None, False)``."""
    if isinstance(default, bool):
        return (value, True) if isinstance(value, bool) else (None, False)
    if isinstance(default, str):
        return (value, True) if isinstance(value, str) and value else (None, False)
    if not _is_num(value):
        return None, False
    if isinstance(default, int):
        if float(value) != int(value):
            return None, False
        value = int(value)
    else:
        value = float(value)
    rng = BLOCK_RANGES.get(block, {}).get(key)
    if rng is not None and not rng[0] <= value <= rng[1]:
        return None, False
    return value, True


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
        """Set one key of a project settings block. Unknown blocks or keys, and invalid values
        (type or range) of the laminated, mineral, Qv, guard and diagnosis blocks, write
        nothing and return False. A valid value equal to the stored one writes nothing."""
        if block not in SETTING_BLOCKS:
            return False
        current = model.project.lrlc.get(block)
        defaults = lrlc_defaults()[block]
        if not isinstance(current, dict) or key not in defaults:
            return False
        if block in L2_BLOCKS:
            value, ok = _clean_block_value(block, key, defaults[key], value)
            if not ok:
                return False
            if current.get(key) == value:
                return True
        current[key] = copy.deepcopy(value)
        model.mark_dirty()
        return True

    @staticmethod
    def set_guard_enabled(model, on: bool) -> bool:
        """Switch the shoulder-bed guard on or off. True when the stored value changed."""
        guard = model.project.lrlc.get("guard")
        if not isinstance(guard, dict):
            guard = model.project.lrlc["guard"] = copy.deepcopy(lrlc_defaults()["guard"])
        on = bool(on)
        if guard.get("enabled", True) == on:
            return False
        guard["enabled"] = on
        model.mark_dirty()
        return True

    @staticmethod
    def set_rt_sbc(model, ds, marked: bool) -> bool:
        """Declare the well's mapped RT curve shoulder-bed corrected (or remove the mark).

        True when the stored marker changed; False when there is no well, no mapped RT curve to
        mark, or nothing to change.
        """
        if ds is None or "RT_SBC" not in CURVE_MARKERS:
            return False
        curves = ds.lrlc_curves
        if marked:
            name = (ds.curve_mapping or {}).get("RT")
            if not name or curves.get("RT_SBC") == name:
                return False
            curves["RT_SBC"] = name
        else:
            if "RT_SBC" not in curves:
                return False
            del curves["RT_SBC"]
        model.mark_dirty()
        return True

    @staticmethod
    def _log_arrays(ds, vsh_column: Optional[str] = None):
        """``(depth, vsh, phit, zone labels or None)`` from the well's last results, or None."""
        res = getattr(ds, "results", None)
        if res is None or len(res) == 0:
            return None
        col = vsh_column if vsh_column in res.columns else "VSH"
        if col not in res.columns or "PHIT" not in res.columns:
            return None
        if "DEPTH" in res.columns:
            depth = res["DEPTH"].to_numpy(dtype=float)
        else:
            depth = np.asarray(res.index, dtype=float)
        labels = None
        if "ZONE" in res.columns:
            z = res["ZONE"].astype(object)
            labels = z.where(z.notna(), UNZONED).to_numpy()
        return (depth, res[col].to_numpy(dtype=float), res["PHIT"].to_numpy(dtype=float),
                labels)

    @staticmethod
    def ts_proposals(model, ds=None) -> Optional[dict]:
        """``{zone: Proposal}`` of Thomas-Stieber end-points from the well's last results;
        None when the well has no usable results."""
        from modules.lrlc.thomas_stieber import propose_endpoints

        ds = ds if ds is not None else model.active_well
        if ds is None:
            return None
        settings = model.project.lrlc.get("thomas_stieber") or {}
        arrays = LrlcService._log_arrays(ds, settings.get("vsh_column"))
        if arrays is None:
            return None
        depth, vsh, phit, labels = arrays
        return propose_endpoints(vsh, phit, depth, labels, settings)

    @staticmethod
    def _stored_value(model, level: str, zone: Optional[str], key: str, ds=None):
        """``(present, value)`` of a key stored at exactly this level; nothing is created."""
        if level == "project":
            params = model.project.lrlc.get("params") or {}
        else:
            target = ds if ds is not None else model.active_well
            params = (target.lrlc if target is not None else None) or {}
        if not params:
            return False, None
        d = LrlcService._level_dict(
            {"default": params.get("default") or {}, "zones": params.get("zones") or {}},
            zone, False)
        if d is None or key not in d:
            return False, None
        return True, d[key]

    @staticmethod
    def _write_values(model, level: str, zone: Optional[str], values: dict, ds=None) -> list:
        """Write already-valid ladder values; keys whose stored value is equal are skipped.
        Returns the keys written (and marks the session dirty when any)."""
        changed = [k for k, v in values.items()
                   if LrlcService._stored_value(model, level, zone, k, ds) != (True, v)]
        if not changed:
            return []
        params = LrlcService._store(model, level, ds)
        target = LrlcService._level_dict(params, zone, True)
        for k in changed:
            target[k] = values[k]
        model.mark_dirty()
        return changed

    @staticmethod
    def apply_endpoints(model, level: str, zone: Optional[str], phi_max, phi_sh,
                        ds=None) -> bool:
        """Write ``phi_max`` and ``phi_sh`` together at a level (project / well, default / zone).

        Both must pass ``check_endpoints``, else nothing is written. False when invalid or when
        both stored values already equal the new ones.
        """
        from modules.lrlc.thomas_stieber import check_endpoints

        if level not in LEVELS:
            return False
        if level == "well" and (ds if ds is not None else model.active_well) is None:
            return False
        if not check_endpoints(phi_max, phi_sh)[0]:
            return False
        pm, ok1 = clean_param("phi_max", phi_max)
        ps, ok2 = clean_param("phi_sh", phi_sh)
        if not (ok1 and ok2):
            return False
        return bool(LrlcService._write_values(
            model, level, zone, {"phi_max": pm, "phi_sh": ps}, ds))

    @staticmethod
    def cec_proposal(model, ds=None, zone: Optional[str] = None):
        """``CecFit`` of ``cec_shale`` from the well's core CEC paired to the log Vsh, or None
        when the well has no results or no core CEC. ``zone`` limits the log samples used."""
        from modules.lrlc.qv import calibrate_cec_shale, pair_core_cec

        ds = ds if ds is not None else model.active_well
        core = getattr(ds, "core_data", None) if ds is not None else None
        data = getattr(core, "data", None)
        if data is None or "CEC" not in data.columns:
            return None
        depth_col = getattr(core, "depth_col", None)
        if depth_col not in data.columns:
            return None
        settings = model.project.lrlc.get("thomas_stieber") or {}
        arrays = LrlcService._log_arrays(ds, settings.get("vsh_column"))
        if arrays is None:
            return None
        depth, vsh, _, labels = arrays
        if zone is not None and labels is not None:
            z = normalize_zone(zone)
            keep = np.array([normalize_zone(str(x)) == z for x in labels], dtype=bool)
            depth, vsh = depth[keep], vsh[keep]
        qv = model.project.lrlc.get("qv") or {}
        cec, v = pair_core_cec(data[depth_col].to_numpy(dtype=float),
                               data["CEC"].to_numpy(dtype=float), depth, vsh,
                               float(qv.get("pair_tol_ft", 0.5)))
        return calibrate_cec_shale(cec, v, min_pairs=int(qv.get("min_pairs", 5)))

    @staticmethod
    def apply_remediation(model, level: str, zone: Optional[str], values: dict,
                          ds=None) -> list:
        """Write ladder values from a diagnosis remedy; returns the keys written.

        All or nothing: an unknown key, an invalid value, a bad level or a broken cross-key
        rule (``s_warn < s_invalid``; ``phi_sh < phi_max - 0.02`` when both are set), checked
        against the values resolved for that level and zone with the new ones applied, writes
        nothing and returns ``[]``. Keys already holding the value are not rewritten.
        """
        if level not in LEVELS or not isinstance(values, dict) or not values:
            return []
        target = ds if ds is not None else model.active_well
        if level == "well" and target is None:
            return []
        cleaned = {}
        for key, value in values.items():
            v, ok = clean_param(key, value)
            if not ok:
                return []
            cleaned[key] = v
        project_params = copy.deepcopy(model.project.lrlc.get("params") or {})
        well_params = copy.deepcopy((target.lrlc if target is not None else None) or {})
        trial = project_params if level == "project" else well_params
        trial.setdefault("default", {})
        trial.setdefault("zones", {})
        LrlcService._level_dict(trial, zone, True).update(cleaned)
        r = resolve_lrlc(project_params, well_params, zone)
        if not r["s_warn"] < r["s_invalid"]:
            return []
        if (r["phi_max"] is not None and r["phi_sh"] is not None
                and not r["phi_sh"] < r["phi_max"] - 0.02):
            return []
        return LrlcService._write_values(model, level, zone, cleaned, ds)

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
