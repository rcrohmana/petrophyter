"""LRLC pipeline glue (no pipeline import: everything the pipeline owns is passed in).

``LrlcRun`` is created once per ``run_pipeline`` call and handed to every saturation
segment. ``apply_lrlc_stage`` is the tail of ``_saturation_to_pay`` (BVW, WATER_FREE_FLAG,
LRLC_SCORE, LRLC_FLAG and RT_CUT); ``lrlc_summary`` builds ``summary["lrlc"]`` from the
merged results. Every column listed here is written by EVERY segment, so the segment merge
(``pd.concat(parts).reindex``) never produces a spurious NaN or turns an int flag into a float.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from modules.lrlc import l2
from modules.lrlc.config import AUX_ROLES, L2_PARAM_KEYS, LRLC_PARAM_DEFAULTS
from modules.lrlc.movable import bvw, movable_zone_rows, water_free_flag
from modules.lrlc.rt_cutoff import rt_cutoff, zone_scalar
from modules.lrlc.screening import CRITERIA, criteria_counts, screen, unavailable_criteria, zone_table
from modules.param_scopes import UNZONED, normalize_zone
from modules.shf_stage import zone_series

# The laminated and pyrite steps and the segment derives are available as soon as the
# pipeline side of LRLC is imported.
l2.register_all()

# Roles whose non-positive readings are NaN in the LRLC context (counted once per role).
POSITIVE_ROLES = ("RM", "RS", "RXO", "HIRES")
NO_ROOT_WARNING_SHARE = 0.05
WELL_ZONE = "WELL"
WELL_SOURCES_KEY = "(well)"     # modules.pipeline.WELL_SOURCES_KEY


@dataclass
class LrlcRun:
    lrlc: dict                                  # p["lrlc"]
    aux: Dict[str, Optional[pd.Series]]         # sanitised well-level role curves (None = not available)
    aux_names: Dict[str, str]                   # role -> column actually found in the data
    force_rt_sw: bool
    well_labels: pd.Series                      # normalised zone key per sample of the whole well
    well_derived: Dict[str, Any]
    has_labels: bool = False                    # the well has formation tops
    planned: bool = False                       # zone overrides split the well into segments
    records: List[dict] = field(default_factory=list)
    record_depths: List[float] = field(default_factory=list)
    criteria: Dict[str, List[int]] = field(
        default_factory=lambda: {name: [0, 0] for name in CRITERIA})
    swirr_missing: int = 0
    cut_model: Optional[str] = None
    cut_eligible: int = 0
    cut_no_root: int = 0
    cut_rows: List[dict] = field(default_factory=list)
    plan: l2.L2Plan = field(default_factory=l2.L2Plan)
    ts_notes: Dict[Any, dict] = field(default_factory=dict)         # zone key -> end-points, clamps
    guard_states: Dict[Any, dict] = field(default_factory=dict)
    guard_decisions: Dict[Any, Any] = field(default_factory=dict)
    rw_eff_parts: List[pd.Series] = field(default_factory=list)
    shf_held: int = 0                                               # pay Sw held on SHF values

    def aux_array(self, role: str, index) -> Optional[np.ndarray]:
        series = self.aux.get(role)
        if series is None:
            return None
        return series.reindex(index).to_numpy(dtype=float)


def zone_keys_for(index, zone) -> np.ndarray:
    """Per-sample zone key matching the keys of ``lrlc["resolved"]["zones"]``.

    Same normalisation as ``shf_stage.zone_series`` (the ladder keys are ``normalize_zone``
    names), except that the unzoned label stays :data:`UNZONED`.
    """
    keys = zone_series(index, zone)
    keys = keys.where(keys != normalize_zone(UNZONED), UNZONED)
    return keys.to_numpy(dtype=object)


def resolved_for(lrlc: dict, key) -> dict:
    res = lrlc["resolved"]
    return res.get("zones", {}).get(key, res["default"])


def build_aux(lrlc: dict, data: pd.DataFrame, warnings):
    """``(aux, aux_names)``: sanitised curves per role; issues for missing / non-positive."""
    aux: Dict[str, Optional[pd.Series]] = {}
    names: Dict[str, str] = {}
    curves = lrlc.get("curves") or {}
    for role in AUX_ROLES:
        name = curves.get(role)
        if not name:
            aux[role] = None
            continue
        if name not in data.columns:
            warnings.add("LRLC_AUX_MISSING",
                         f"{role} curve {name} is not in the data; the role is ignored.")
            aux[role] = None
            continue
        series = pd.to_numeric(data[name], errors="coerce").astype(float)
        if role in POSITIVE_ROLES:
            bad = (series <= 0).to_numpy()
            count = int(bad.sum())
            if count:
                series = series.mask(bad)
                warnings.add("LRLC_AUX_NONPOSITIVE",
                             f"{role} ({name}): {count} samples <= 0 set to NaN in the LRLC context.")
        aux[role] = series
        names[role] = name
    return aux, names


def _per_sample(lrlc: dict, keys: np.ndarray, name: str, fallback=None) -> np.ndarray:
    out = np.empty(len(keys), dtype=float)
    for key in dict.fromkeys(keys):
        value = resolved_for(lrlc, key).get(name)
        out[keys == key] = fallback if value is None else value
    return out


def _array(value, n) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if arr.ndim == 0:
        return np.full(n, float(arr))
    return arr.reshape(-1)


def apply_lrlc_stage(calc, data, p, run: LrlcRun, *, rt_curve, zone_keys, sw_inputs, sw_model,
                     dz, warnings) -> None:
    """Write BVW, WATER_FREE_FLAG, LRLC_SCORE, LRLC_FLAG and RT_CUT on ``calc.results``.

    Reads ``SW``, ``SWIRR``, ``NET_*`` flags, ``GAS_FLAG``, ``PHIE`` and ``VSH`` (the latter
    two via ``sw_inputs``); writes only new columns. ``sw_inputs`` is the segment's one
    ``SwInputs`` record (the inputs ``_primary_sw`` used), ``sw_model`` the model that ended
    up as ``SW`` (None when none did).
    """
    lrlc = run.lrlc
    res = calc.results
    index = data.index
    n = len(index)
    sw = _array(res["SW"].to_numpy(dtype=float) if "SW" in res.columns else np.nan, n)
    phie = _array(sw_inputs.phie, n)
    vsh = _array(sw_inputs.vsh, n)
    rt = pd.to_numeric(data[rt_curve], errors="coerce").to_numpy(dtype=float)

    # ---- screening ----------------------------------------------------------
    scr = lrlc.get("screening") or {}
    gas = res["GAS_FLAG"].to_numpy(dtype=float) if "GAS_FLAG" in res.columns else None
    result = screen(
        rt, run.aux_array("RS", index), gas, phie, vsh, _array(sw_inputs.rsh_eff, n), sw,
        screen_rt_max=_per_sample(lrlc, zone_keys, "screen_rt_max"),
        screen_contrast_max=_per_sample(lrlc, zone_keys, "screen_contrast_max"),
        screen_min_score=_per_sample(lrlc, zone_keys, "screen_min_score"),
        phi_cutoff=p["phi_cutoff"], vsh_cutoff=p["vsh_cutoff"], sw_cutoff=p["sw_cutoff"],
        use_gas_flag=bool(scr.get("use_gas_flag", True)), use_rs=bool(scr.get("use_rs", True)))
    for name, c in criteria_counts(result).items():
        run.criteria[name][0] += c["met"]
        run.criteria[name][1] += c["evaluable"]
    res["LRLC_SCORE"] = np.asarray(result.score, dtype=int)
    res["LRLC_FLAG"] = np.asarray(result.flag, dtype=int)

    # ---- BVW and the water-free flag ----------------------------------------
    res["BVW"] = bvw(phie, sw)
    column = (lrlc.get("movable") or {}).get("swirr_column", "SWIRR")
    if column not in res.columns:
        if column != "SWIRR":
            warnings.add("LRLC_SWIRR_COLUMN",
                         f"Swirr column {column} is not available; SWIRR is used for the "
                         "water-free flag.")
        column = "SWIRR"
    swirr = (res[column].to_numpy(dtype=float) if column in res.columns
             else np.full(n, np.nan))
    flag, missing = water_free_flag(
        res["NET_RES_FLAG"].to_numpy(), sw, swirr, _per_sample(lrlc, zone_keys, "movable_tol"))
    run.swirr_missing += missing
    res["WATER_FREE_FLAG"] = flag

    # ---- Rt cutoff ----------------------------------------------------------
    if (lrlc.get("rt_cutoff") or {}).get("enabled"):
        if sw_model is None:
            res["RT_CUT"] = np.full(n, np.nan)
            return
        run.cut_model = run.cut_model or sw_model
        target = _per_sample(lrlc, zone_keys, "cut_sw_target", fallback=float(p["sw_cutoff"]))
        cut, eligible, no_root = rt_cutoff(sw_model, sw_inputs, target, index)
        res["RT_CUT"] = cut
        run.cut_eligible += eligible
        run.cut_no_root += no_root
        dz_arr = _array(dz, n)
        for key in dict.fromkeys(zone_keys):
            mask = zone_keys == key
            label = WELL_ZONE if (key == UNZONED and not run.has_labels) else str(key)
            row = zone_scalar(
                sw_model, sw_inputs, float(target[mask][0]), zone_mask=mask, dz=dz_arr,
                net_pay_flag=res["NET_PAY_FLAG"].to_numpy(),
                net_res_flag=res["NET_RES_FLAG"].to_numpy(),
                gross_sand_flag=res["GROSS_SAND_FLAG"].to_numpy(), zone=label)
            if row is None:
                warnings.add("LRLC_CUT_NO_BASIS",
                             f"Rt cutoff: {label} has no pay, net reservoir or gross sand "
                             "sample; no zone value.", zone=None if label == WELL_ZONE else label)
            else:
                run.cut_rows.append(row)


def _summary_params(resolved: dict) -> dict:
    """The resolved ladder for the summary: 2.6 keys only where they differ from built-in.

    Keeps the summary of a run that uses none of them as it was before they existed.
    """
    def level(values):
        return {k: v for k, v in values.items()
                if k not in L2_PARAM_KEYS or v != LRLC_PARAM_DEFAULTS[k]}
    return {"default": level(resolved.get("default") or {}),
            "zones": {z: level(v) for z, v in (resolved.get("zones") or {}).items()}}


def _clean(value):
    """JSON-friendly python value."""
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def lrlc_summary(run: LrlcRun, results: pd.DataFrame, rt, vsh, phie, labels, dz, p, summary,
                 param_sources, warnings) -> dict:
    """``summary["lrlc"]`` from the merged results (screening table built after the concat).

    ``rt`` (measured), ``vsh`` and ``phie`` are the well's arrays in ``results`` order;
    ``labels`` the zone Series (or None), ``dz`` the per-sample thickness.
    """
    lrlc = run.lrlc
    n = len(results)
    cols = results.columns
    labels_arr = None if labels is None else labels.to_numpy(dtype=object)

    order = sorted(range(len(run.records)), key=lambda i: (run.record_depths[i], i))
    chain = [_clean(run.records[i]) for i in order]

    counts_by = {name: {"met": m, "evaluable": e} for name, (m, e) in run.criteria.items()}
    unavailable = [name for name in CRITERIA if run.criteria[name][1] == 0]
    if unavailable:
        warnings.add("LRLC_CRITERION_UNAVAILABLE",
                     "Screening criteria not evaluable for the whole well: "
                     + ", ".join(unavailable) + ".")

    cut_zone_map = {row["zone"]: row["rt_cut"] for row in run.cut_rows}
    cut_on = bool((lrlc.get("rt_cutoff") or {}).get("enabled"))
    zeros = np.zeros(n, dtype=int)

    def col(name, default=np.nan):
        return results[name].to_numpy() if name in cols else (
            zeros if default == 0 else np.full(n, default))

    rows = zone_table(
        col("LRLC_FLAG", 0), col("NET_PAY_FLAG", 0), col("NET_RES_FLAG", 0), dz,
        np.asarray(phie, dtype=float), np.asarray(vsh, dtype=float), col("SW"),
        np.asarray(rt, dtype=float), labels_arr, cut_zone_map if cut_on else None)

    def thresholds_for(zone):
        key = UNZONED if zone == WELL_ZONE else zone
        prm = resolved_for(lrlc, key)
        out = {k: prm[k] for k in ("screen_rt_max", "screen_contrast_max", "screen_min_score")}
        source = (param_sources or {}).get(zone) or (param_sources or {}).get(WELL_SOURCES_KEY) or {}
        for name in ("vsh_cutoff", "phi_cutoff", "sw_cutoff"):
            try:
                out[name] = float(source[name]["value"])
            except (KeyError, TypeError, ValueError):
                out[name] = float(p[name])
        return out

    thresholds = {row["zone"]: thresholds_for(row["zone"]) for row in rows}
    screening = {"thresholds": thresholds, "criteria": counts_by, "unavailable": unavailable,
                 "zones": rows}

    movable_rows = movable_zone_rows(
        labels_arr, col("NET_RES_FLAG", 0), col("WATER_FREE_FLAG", 0), col("BVW"), dz,
        col("SW"), col("SWIRR"))
    tol_by_zone = {r["zone"]: resolved_for(lrlc, UNZONED if r["zone"] == WELL_ZONE
                                           else r["zone"])["movable_tol"] for r in movable_rows}
    movable = {
        "swirr_column": (lrlc.get("movable") or {}).get("swirr_column", "SWIRR"),
        "swirr_method": summary.get("swirr_method"),
        "tol_by_zone": tol_by_zone,
        "zones": movable_rows,
    }
    if run.swirr_missing:
        warnings.add("LRLC_SWIRR_MISSING",
                     f"{run.swirr_missing} net reservoir samples have no Swirr; the water-free "
                     "flag was not evaluated there.")

    out = {
        "version": 1,
        "curves": dict(run.aux_names),
        "params": _clean(_summary_params(lrlc["resolved"])),
        "chain": chain,
        "screening": screening,
        "movable": movable,
        "counts": {
            "n": n,
            "flag": int(np.nansum(col("LRLC_FLAG", 0))),
            "water_free": int(np.nansum(col("WATER_FREE_FLAG", 0))),
            "rt_sw_written": bool("RT_SW" in cols),
        },
    }
    if cut_on:
        out["rt_cutoff"] = {"model": run.cut_model, "zones": run.cut_rows,
                            "no_root": int(run.cut_no_root), "eligible": int(run.cut_eligible)}
        if run.cut_no_root:
            share = run.cut_no_root / max(run.cut_eligible, 1)
            warnings.add(
                "LRLC_CUT_NO_ROOT",
                f"Rt cutoff: no root for {run.cut_no_root} of {run.cut_eligible} eligible "
                f"samples ({100.0 * share:.0f} percent).",
                severity="warning" if share > NO_ROOT_WARNING_SHARE else "info")
    return _clean(out)

