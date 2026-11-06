"""LRLC writes (no Qt widgets, no pipeline).

The LRLC Workbench changes the model only through these functions: each one marks the session
dirty, and the caller asks for the stale recompute (``stale_requested``). Nothing here runs the
analysis.

Levels: ``"project"`` writes ``Project.lrlc["params"]``; ``"well"`` writes the well's own
``ds.lrlc`` (the active well unless ``ds`` is given). ``zone=None`` is the level's default.
"""

import copy
import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence

import math

import numpy as np

from modules.lrlc.config import (
    AUX_ROLES, BLOCK_PAIRS, BLOCK_RANGES, CURVE_MARKERS, L2_BLOCKS, L3_BLOCKS,
    LRLC_PARAM_DEFAULTS, clean_param,
    lrlc_defaults, resolve_lrlc)
from modules.param_scopes import UNZONED, normalize_zone

logger = logging.getLogger(__name__)

LEVELS = ("project", "well")
SETTING_BLOCKS = (("screening", "rt_cutoff", "movable", "pickett", "buckles") + L2_BLOCKS
                  + L3_BLOCKS)


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


def _clean_l3_value(block: str, key: str, default, value):
    """``(value, True)`` for a valid key of the variable m/n and invasion blocks (numbers and
    ``[low, high]`` pairs with their ranges, and the ``fit`` options of variable m/n), else
    ``(None, False)``."""
    if isinstance(default, dict):
        if not isinstance(value, dict):
            return None, False
        out = {}
        for sub, sub_default in default.items():
            if sub not in value:
                out[sub] = copy.deepcopy(sub_default)
                continue
            cleaned, ok = _clean_l3_value(f"{block}.{key}", sub, sub_default, value[sub])
            if not ok:
                return None, False
            out[sub] = cleaned
        return out, True
    if isinstance(default, list):
        if not (isinstance(value, (list, tuple)) and len(value) == len(default)
                and all(_is_num(x) for x in value)):
            return None, False
        pair = [float(x) for x in value]
        bounds = BLOCK_PAIRS.get(block, {}).get(key)
        if bounds is not None and not (bounds[0] <= pair[0] < pair[1] <= bounds[1]):
            return None, False
        return pair, True
    return _clean_block_value(block, key, default, value)


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
        if block in L3_BLOCKS:
            value, ok = _clean_l3_value(block, key, defaults[key], value)
            if not ok:
                return False
            if current.get(key) == value:
                return True
        elif block in L2_BLOCKS:
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


@dataclass
class MnFitProposal:
    """A variable-m fit proposal for one zone (nothing is stored)."""

    status: str                                  # fit / no_results / no_rt / no_phi / no_rw
    reason: str = ""
    fit: Any = None                              # MnFitResult when a fit was attempted
    zone: Optional[str] = None
    rt_curve: str = ""                           # RT_SW or the mapped RT
    basis: str = "bulk"                          # bulk / sand / mixed
    phi_source: str = "phie"
    rw: float = float("nan")
    rw_mode: str = ""                            # auto / manual / ""
    a: float = 1.0
    temperature: bool = False
    n_rows: int = 0
    n_wet: int = 0
    phi: Any = None                              # zone arrays, for plotting
    vsh: Any = None
    wet: Any = None
    notes: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.fit is not None and bool(self.fit.apply_allowed)


def _zone_labels(res) -> Any:
    """Zone label of every result row ('' without zones)."""
    if "ZONE" in res.columns:
        return res["ZONE"].fillna("").astype(str).to_numpy()
    return np.full(len(res), "", dtype=object)


def temperature_factor_array(model, ds, df) -> Optional[np.ndarray]:
    """Arps multiplier per result row from the well's current parameters, or None when the
    temperature correction is off. A mapped TVD curve that is not in the results is
    interpolated from the log onto the result depths."""
    from modules.pipeline import temperature_factor

    if model is None or ds is None or "DEPTH" not in df.columns:
        return None
    try:
        params = model.params_for_well(ds)
        if not params.get("temp_correction"):
            return None
        mapping = dict(ds.curve_mapping or {})
        frame = df[["DEPTH"]].copy()
        tvd = mapping.get("TVD")
        if tvd and tvd in df.columns:
            frame[tvd] = df[tvd]
        elif tvd and tvd not in ("None", "DEPTH"):
            log = getattr(ds, "las_data", None)
            if log is not None and tvd in log.columns and "DEPTH" in log.columns:
                ok = log["DEPTH"].notna() & log[tvd].notna()
                frame[tvd] = np.interp(frame["DEPTH"].to_numpy(dtype=float),
                                       log.loc[ok, "DEPTH"].to_numpy(dtype=float),
                                       log.loc[ok, tvd].to_numpy(dtype=float))
        factor = temperature_factor(frame, params, mapping)
        return None if factor is None else np.asarray(factor, dtype=float)
    except Exception:      # noqa: BLE001 - callers fall back to the raw Rt
        logger.exception("temperature factor failed")
        return None


def _resolved_ladder(model, ds, zones: Sequence[str]) -> dict:
    """``{"resolved": {"default", "zones"}}`` as the pipeline builds it, from the stored ladders."""
    project = model.project.lrlc.get("params") or {}
    well = (getattr(ds, "lrlc", None) or {}) if ds is not None else {}
    return {"resolved": {
        "default": resolve_lrlc(project, well, None),
        "zones": {z: resolve_lrlc(project, well, z) for z in zones if z},
    }}


def zone_exponent_basis(model, ds, res, zone: Optional[str]):
    """``(phie, phit, vsh, basis)`` per result row: the arrays the zone's Sw models read.

    The bulk columns ``PHIE``, ``PHIT`` and ``VSH`` of the last run, replaced by the
    sand-lamina values (rebuilt from ``VLAM``, ``VDISP``, ``PHI_SAND`` and the zone's
    ``phi_max`` with ``l2.sand_basis``) in the zones that read the sand basis. ``basis`` is
    ``"bulk"``, ``"sand"`` or ``"mixed"`` for the rows of ``zone`` (all rows when None).
    """
    from modules.lrlc import l2

    def col(name):
        if name in res.columns:
            return res[name].to_numpy(dtype=float)
        return np.full(len(res), np.nan)

    phie, phit, vsh = col("PHIE"), col("PHIT"), col("VSH")
    labels = _zone_labels(res)
    keys = np.array([k if k else UNZONED for k in labels], dtype=object)
    names = [k for k in dict.fromkeys(keys.tolist()) if k != UNZONED]
    lrlc = _resolved_ladder(model, ds, names)
    in_zone = np.ones(len(res), dtype=bool) if zone is None else labels == zone
    used_keys = list(dict.fromkeys(keys[in_zone].tolist()))
    sand_keys = [k for k in used_keys if l2.resolve_basis(l2._resolved(lrlc, k)) == "sand"]
    if not sand_keys:
        return phie, phit, vsh, "bulk"
    env = l2.SegEnv(lrlc=lrlc, keys=keys, p={}, vsh=vsh, vsh_ts=vsh, phit=phit, phie=phie,
                    rt=col("RT"), dz=np.zeros(len(res)), has_gr=False, rhob=None, pef=None,
                    gas=None, plan=None)
    derived = {k: res[k].to_numpy(dtype=float) for k in ("VLAM", "VDISP", "PHI_SAND")
               if k in res.columns}
    out = l2.sand_basis(env, derived)
    if out is None:
        return phie, phit, vsh, "bulk"
    basis = "sand" if len(sand_keys) == len(used_keys) else "mixed"
    return out[0], out[1], out[2], basis


def _zone_source_table(ds, zone: Optional[str]) -> dict:
    from modules.pipeline import WELL_SOURCES_KEY

    sources = (getattr(ds, "summary", None) or {}).get("param_sources") or {}
    if zone and isinstance(sources.get(zone), dict):
        return sources[zone]
    return sources.get(WELL_SOURCES_KEY) or {}


def _source_float(table: dict, name: str, default: float) -> float:
    try:
        value = float(table[name]["value"])
    except (KeyError, TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def variable_m_proposal(model, ds=None, zone: Optional[str] = None,
                        manual: Optional[Sequence] = None,
                        phi_source: Optional[str] = None) -> MnFitProposal:
    """Fit ``c0..c2`` of the m formula on the zone's wet points of the last run.

    Reads the last results: the Rt the Sw models read (``RT_SW``, else the mapped RT), the
    zone's porosity per ``phi_source`` and Vsh on the basis the zone's Sw models read (the sand
    basis is rebuilt with ``l2.sand_basis``), Rw and ``a`` from the zone's parameter table, the
    temperature multiplier when that correction is on, and the wet points of the Pickett
    selection (``manual`` boxes included). Writes nothing.
    """
    from modules.lrlc import pickett
    from modules.lrlc.variable_mn import fit_variable_m

    ds = ds if ds is not None else model.active_well
    prop = MnFitProposal(status="no_results", zone=zone or None,
                         reason="Run the analysis first.")
    res = getattr(ds, "results", None) if ds is not None else None
    if res is None or len(res) == 0:
        return prop
    project = model.project.lrlc.get("params") or {}
    prm = resolve_lrlc(project, getattr(ds, "lrlc", None) or {}, zone or None)
    src = str(phi_source or prm.get("phi_source") or "phie").lower()
    prop.phi_source = src if src in ("phie", "phit") else "phie"
    mapped = (ds.curve_mapping or {}).get("RT")
    rt_col = next((c for c in ("RT_SW", mapped, "RT") if c and c in res.columns), None)
    if rt_col is None:
        prop.status, prop.reason = "no_rt", "The last run has no resistivity curve."
        return prop
    prop.rt_curve = rt_col
    phie, phit, vsh, prop.basis = zone_exponent_basis(model, ds, res, zone or None)
    phi_all = phie if prop.phi_source == "phie" else phit
    labels = _zone_labels(res)
    sel = np.ones(len(res), dtype=bool) if not zone else labels == zone
    if not sel.any():
        prop.status, prop.reason = "no_results", "The zone has no samples in the last run."
        return prop
    phi, vs = phi_all[sel], vsh[sel]
    rt = res[rt_col].to_numpy(dtype=float)[sel]
    if not np.isfinite(phi).any():
        prop.status, prop.reason = "no_phi", f"{prop.phi_source.upper()} is not in the results."
        return prop
    table = _zone_source_table(ds, zone or None)
    prop.a = _source_float(table, "a", 1.0)
    prop.rw = _source_float(table, "rw", float("nan"))
    prop.rw_mode = str((table.get("rw") or {}).get("mode") or "")
    if not math.isfinite(prop.rw) or prop.rw <= 0:
        prop.status = "no_rw"
        prop.reason = "Rw is unknown for this zone: set it in the Sw parameters, then run."
        return prop
    factor = temperature_factor_array(model, ds, res)
    prop.temperature = factor is not None
    rw_i = prop.rw if factor is None else prop.rw * factor[sel]
    rt_norm = rt if factor is None else pickett.normalise_rt_for_temperature(rt, factor[sel])
    settings = dict(pickett.DEFAULT_SETTINGS)
    stored = model.project.lrlc.get("pickett")
    if isinstance(stored, dict):
        settings.update({k: x for k, x in stored.items() if k in settings})
    wet = pickett.wet_points(phi, rt_norm, vs, settings, manual)
    block = model.project.lrlc.get("variable_mn") or {}
    fit = fit_variable_m(phi, rt, vs, rw_i, prop.a, wet, options=block.get("fit"),
                         clip_m=block.get("clip_m") or (1.0, 4.0))
    prop.status, prop.fit = "fit", fit
    prop.n_rows, prop.n_wet = int(sel.sum()), int(wet.sum())
    prop.phi, prop.vsh, prop.wet = phi, vs, wet
    if prop.basis != "bulk":
        prop.notes.append("Sand basis active in this zone: the wet points are the sand-lamina "
                          "values, which are the values the Sw models read.")
    if prop.rw_mode == "auto":
        prop.notes.append("Rw is estimated automatically with the constant m, so the fitted m "
                          "depends on that estimate.")
    return prop


def apply_variable_m_fit(model, level: str, zone: Optional[str], fit, phi_source: str,
                         ds=None) -> list:
    """Write a variable-m fit: ``mn_mode = "curve"``, ``m_model = "formula"``, ``m_coef`` and
    ``phi_source`` at a scope (``n_model`` is never touched). Only a fit that may be applied is
    written. Returns the keys written."""
    if fit is None or not getattr(fit, "apply_allowed", False) or not fit.coef:
        return []
    values = {"mn_mode": "curve", "m_model": "formula",
              "m_coef": [round(float(c), 6) for c in fit.coef],
              "phi_source": str(phi_source).lower()}
    return LrlcService.apply_remediation(model, level, zone, values, ds)


def aux_curve_name(ds, role: str) -> Optional[str]:
    """Mnemonic of an auxiliary curve role: the user's assignment, else the auto-detected one;
    None when the role is switched off or nothing matches."""
    curves = getattr(ds, "lrlc_curves", None) or {}
    if role in curves:
        return curves[role] or None
    log = getattr(ds, "las_data", None)
    if log is None:
        return None
    try:
        from modules.las_parser import find_curve
        return find_curve([str(c) for c in log.columns], role)
    except Exception:      # noqa: BLE001 - an unreadable log has no auxiliary curve
        return None


def invasion_view_data(ds, zone: Optional[str] = None) -> Optional[dict]:
    """Arrays for the invasion plots, restricted to ``zone`` (all rows when None).

    ``depth``, the measured ``rt`` (the deep curve), ``rm``, ``rs``, ``rxo`` (None when the role
    has no curve) and the step outputs ``rt_inv``, ``rxo_inv``, ``di`` (None before a run that
    included the step). Rows come from the last results, or from the log when there are no
    results. None when the well has neither.
    """
    res = getattr(ds, "results", None) if ds is not None else None
    log = getattr(ds, "las_data", None) if ds is not None else None
    base = res if res is not None and len(res) else log
    if base is None or len(base) == 0:
        return None
    if "DEPTH" in base.columns:
        depth = base["DEPTH"].to_numpy(dtype=float)
    else:
        depth = np.asarray(base.index, dtype=float)
    sel = np.ones(len(base), dtype=bool)
    if zone and res is not None and base is res:
        sel = _zone_labels(res) == zone

    def from_base(name):
        if name and name in base.columns:
            return base[name].to_numpy(dtype=float)[sel]
        return None

    def from_log(name):
        if not name or log is None or name not in log.columns:
            return None
        if base is log:
            return log[name].to_numpy(dtype=float)[sel]
        return log[name].reindex(base.index).to_numpy(dtype=float)[sel]

    mapped = (getattr(ds, "curve_mapping", None) or {}).get("RT")
    rt = from_base(mapped) if from_base(mapped) is not None else from_base("RT")
    if rt is None:
        rt = from_log(mapped)
    out = {"depth": depth[sel], "rt": rt}
    for role in ("RM", "RS", "RXO"):
        out[role.lower()] = from_log(aux_curve_name(ds, role))
    for key, column in (("rt_inv", "RT_INV"), ("rxo_inv", "RXO_INV"), ("di", "DI_INV")):
        out[key] = from_base(column) if base is res else None
    return out


def summary_record(block, zone: Optional[str]) -> Optional[dict]:
    """The record of a zone in a per-zone summary block (a list of records with a ``zone``
    key, or a dict keyed by zone); the only record when there is just one and no zone is asked
    for. None when absent."""
    if isinstance(block, dict) and isinstance(block.get("zones"), list):
        block = block["zones"]
    if not block:
        return None
    names = (zone,) if zone else (None, "WELL", "")
    if isinstance(block, dict):
        for name in names:
            if name in block and isinstance(block[name], dict):
                return block[name]
        if not zone and len(block) == 1:
            only = next(iter(block.values()))
            return only if isinstance(only, dict) else None
        return None
    records = [r for r in block if isinstance(r, dict)]
    for rec in records:
        if rec.get("zone") in names:
            return rec
    if not zone and len(records) == 1:
        return records[0]
    return None
