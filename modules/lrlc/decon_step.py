"""Rt deconvolution glue: the well-scope derive ``decon_well`` and the chain step ``decon`` (no Qt, no pipeline import).

``decon.py`` stays the pure maths. This module reads the resolved ladder (``lrlc["resolved"]``), picks the
reference curve, builds the ``active`` rows from the zones that list ``decon`` in ``rt_steps`` and calls
:func:`modules.lrlc.decon.deconvolve` once on the whole filtered well (one continuous solve; a per-segment
kernel would be truncated at every zone boundary). The step itself only slices that result to the zone rows.

``decon_well`` never consults the shoulder-bed guard: zones the guard drops later are solved and discarded.
The tool and solver keys are well-only (``WELL_ONLY_KEYS``): they are read at the well default, the zone-capable
``dec_max_ratio`` and ``dec_misfit_warn`` per zone.

Issue tuples are ``(code, text, zone_or_None, severity_or_None)``.
"""

from dataclasses import asdict
from typing import Any, Dict, List, Optional

import numpy as np

from modules.lrlc import chain
from modules.lrlc.chain import CHAIN_ORDER, StepResult, StepSpec, resolve_steps
from modules.lrlc.config import LRLC_PARAM_DEFAULTS, WELL_ONLY_KEYS
from modules.lrlc.decon import GENERIC_RESPONSES, REFS, DeconParams, default_min_bed, deconvolve, width_sensitivity
from modules.param_scopes import UNZONED

STEP_NAME = "decon"
WELL_ZONE = "WELL"
REFERENCE_ORDER = ("HIRES", "RXO", "RHOB", "GR")        # automatic choice
LOG_KINDS = ("HIRES", "RXO")                            # resistivity-type references are used in log10
BOUNDARY_CAP = 2000
DEC_KEYS = tuple(k for k in LRLC_PARAM_DEFAULTS if k.startswith("dec_"))
WELL_DEC_KEYS = tuple(k for k in DEC_KEYS if k in WELL_ONLY_KEYS)


def _resolved(lrlc: dict, key) -> dict:
    res = lrlc["resolved"]
    return res.get("zones", {}).get(key, res["default"])


def _unique(keys) -> list:
    return list(dict.fromkeys(np.asarray(keys, dtype=object).tolist()))


def decon_zone_keys(lrlc: Optional[dict], zone_keys) -> list:
    """Zone keys present in ``zone_keys`` whose resolved ``rt_steps`` list ``decon``."""
    if not lrlc or "resolved" not in lrlc:
        return []
    return [key for key in _unique(zone_keys)
            if any(s.name == STEP_NAME for s in resolve_steps(_resolved(lrlc, key).get("rt_steps", []))[0])]


def decon_needed(lrlc: Optional[dict], zone_keys) -> bool:
    return bool(decon_zone_keys(lrlc, zone_keys))


def well_settings(lrlc: dict) -> dict:
    """The ``dec_*`` keys of the well: well-only ones at the well default (zone values are ignored)."""
    return {key: lrlc["resolved"]["default"].get(key, LRLC_PARAM_DEFAULTS[key]) for key in WELL_DEC_KEYS}


def pick_reference(source: str, candidates: Dict[str, Any]):
    """``(kind, column, array)`` of the reference curve, or ``(None, None, None)`` when there is none.

    ``candidates`` maps ``HIRES`` / ``RXO`` / ``RHOB`` / ``GR`` to ``(array_or_None, column_name)``.
    ``auto`` takes the first usable one in the order HIRES, RXO, RHOB, GR; an explicit source takes
    only that curve.
    """
    kinds = REFERENCE_ORDER if source == "auto" else (source,)
    for kind in kinds:
        arr, column = candidates.get(kind, (None, None))
        if arr is None:
            continue
        arr = np.asarray(arr, dtype=float)
        usable = np.isfinite(arr) & (arr > 0) if kind in LOG_KINDS else np.isfinite(arr)
        if usable.any():
            return kind, column, arr
    return None, None, None


def derive_decon_well(*, depth, rt, candidates, zone_keys, lrlc, issues: Optional[list] = None,
                      info: Optional[dict] = None, data_mask=None) -> Dict[str, np.ndarray]:
    """``{"rt_decon", "decon_valid"}`` for the whole well (arrays aligned to ``depth``).

    ``candidates`` are the possible reference curves (see :func:`pick_reference`). ``issues`` receives
    the issue tuples; ``info`` the data the summary block needs (reference, parameters, solver result).
    """
    keys = np.asarray(zone_keys, dtype=object)
    n = len(keys)
    zones = decon_zone_keys(lrlc, keys)
    active = np.isin(keys, zones) if zones else np.zeros(n, dtype=bool)
    well = well_settings(lrlc)
    params = DeconParams.from_settings(well)
    ratio_by_zone = {str(z): float(_resolved(lrlc, z).get("dec_max_ratio", params.max_ratio)) for z in zones}
    misfit_by_zone = {str(z): float(_resolved(lrlc, z).get("dec_misfit_warn", params.misfit_warn)) for z in zones}
    source = str(well.get("dec_hires_source", "auto"))
    kind, column, hires = pick_reference(source, candidates or {})
    params = params.with_reference(kind or ("HIRES" if source == "auto" else source))
    log_domain = kind in LOG_KINDS if kind else True
    res = deconvolve(np.asarray(depth, dtype=float), None if rt is None else np.asarray(rt, dtype=float), hires,
                     params, active, data_mask=data_mask, zone_labels=keys,
                     max_ratio_by_zone=ratio_by_zone, misfit_warn_by_zone=misfit_by_zone, log_domain=log_domain)
    if issues is not None:
        for code, text, zone, severity in res.issues:
            issues.append((code, text, None if zone in (None, "", UNZONED) else zone, severity))
    if info is not None:
        info["sensitivity"] = width_sensitivity(
            np.asarray(depth, dtype=float), None if rt is None else np.asarray(rt, dtype=float), hires, params,
            active, res, data_mask=data_mask, zone_labels=keys, max_ratio_by_zone=ratio_by_zone,
            misfit_warn_by_zone=misfit_by_zone, log_domain=log_domain) if hires is not None and rt is not None \
            else {}
        info.update({
            "result": res, "depth": np.asarray(depth, dtype=float), "keys": keys, "active": active,
            "zones": zones, "params": params, "tool": well.get("dec_tool", "custom"),
            "hires": {"curve": kind, "column": column, "source": source, "log_domain": bool(log_domain)},
            "ratio_by_zone": ratio_by_zone})
    return {"rt_decon": np.asarray(res.rt_decon, dtype=float), "decon_valid": np.asarray(res.valid, dtype=bool)}


def step_decon(rt: np.ndarray, ctx, prm: dict) -> StepResult:
    """Slice the well-level derive to the zone's rows; invalid samples take the chain's ``rt_fallback``."""
    n = len(rt)
    derived = ctx.derived or {}
    out = derived.get("rt_decon")
    valid = derived.get("decon_valid")
    if out is None or valid is None:
        out = np.full(n, np.nan)
        valid = np.zeros(n, dtype=bool)
    out = np.asarray(out, dtype=float)
    valid = np.asarray(valid).astype(float) > 0.5
    return StepResult(out, valid & np.isfinite(out), {"valid": int((valid & np.isfinite(out)).sum())}, {}, REFS)


STEP = StepSpec(
    name=STEP_NAME,
    order=CHAIN_ORDER.index(STEP_NAME),
    column="RT_DECON",
    fn=step_decon,
    label="Deconvolution",
    description="MODELLED DECONVOLVED RT (thin-bed)",
    refs=REFS,
    params=("dec_max_ratio", "dec_misfit_warn") + WELL_DEC_KEYS,
    varied=(),
    extra_columns=(),
    kind="vertical",
)

DERIVE = chain.DeriveSpec(name="decon_well", scope="well", fn=derive_decon_well,
                          outputs=("rt_decon", "decon_valid"))


def register_step() -> None:
    """Register the step and its well derive unless they are already registered."""
    if STEP.name not in chain.STEPS:
        chain.register(STEP)
    if DERIVE.name not in chain.DERIVES:
        chain.register_derive(DERIVE)


# ---------------------------------------------------------------------------
# Summary block
# ---------------------------------------------------------------------------
def _zone_name(key) -> str:
    return WELL_ZONE if key == UNZONED else str(key)


def decon_block(info: Optional[dict], guard_decisions: Optional[dict], has_labels: bool = True) -> Optional[dict]:
    """``summary["lrlc"]["decon"]`` from the derive's ``info`` and the guard decisions (None: no zone requested it)."""
    if not info or not info.get("zones"):
        return None
    res = info["result"]
    params: DeconParams = info["params"]
    decisions = guard_decisions or {}
    counts = {k: int(v) for k, v in res.counts.items()}
    keys, active, depth = info["keys"], info["active"], info["depth"]
    zone_rows: List[dict] = []
    guard_counts = {"guard_dropped_laminated": 0, "guard_dropped_shoulder": 0, "guard_warned": 0,
                    "lamination_unknown": 0}
    for key in info["zones"]:
        stats = res.zone_stats.get(str(key), {})
        n_rows = int((active & (keys == key)).sum())
        dec = decisions.get(key)
        reasons = dict(getattr(dec, "reasons", {}) or {})
        reason = reasons.get(STEP_NAME)
        blocked = STEP_NAME in (getattr(dec, "blocked_steps", []) or [])
        warned = STEP_NAME in (getattr(dec, "warned_steps", []) or [])
        if blocked and reason == "shoulder":
            status = "guard_dropped_shoulder"
        elif blocked:
            status = "guard_dropped_laminated"
        elif counts.get("no_hires") and not stats.get("n_valid"):
            status = "no_hires"
        elif counts.get("no_rt") and not stats.get("n_valid"):
            status = "no_rt"
        elif counts.get("undersampled") and not stats.get("n_valid"):
            status = "undersampled"
        else:
            status = "ran"
        if status == "guard_dropped_laminated":
            guard_counts["guard_dropped_laminated"] += n_rows
        elif status == "guard_dropped_shoulder":
            guard_counts["guard_dropped_shoulder"] += n_rows
        if warned:
            guard_counts["guard_warned"] += n_rows
        if dec is not None and any(code == "LRLC_GUARD_NO_TS" for code, *_ in (dec.issues or [])):
            guard_counts["lamination_unknown"] += n_rows
        zone_rows.append({
            "zone": _zone_name(key) if (has_labels or key != UNZONED) else WELL_ZONE, "status": status,
            "max_ratio": float(info["ratio_by_zone"].get(str(key), params.max_ratio)),
            "n_active": int(stats.get("n_active", n_rows)), "n_valid": int(stats.get("n_valid", 0)),
            "n_amplified": int(stats.get("n_amplified", 0)),
            "misfit_rms": float(stats.get("misfit_rms", float("nan"))),
            "width_sensitivity": (info.get("sensitivity") or {}).get(str(key))})
    counts.update(guard_counts)

    # Interior boundaries: the shared edge of two touching beds (window and segment ends are not boundaries).
    unique = {(round(float(b.top), 6), round(float(b.bottom), 6)): b for b in res.beds}
    beds = sorted(unique.values(), key=lambda b: (b.top, b.bottom))
    tops = np.array([b.top for b in beds])
    boundaries: Dict[str, list] = {}
    seen = set()
    truncated = False
    n_beds = 0
    for i, bed in enumerate(beds):
        idx = int(np.clip(np.searchsorted(depth, 0.5 * (bed.top + bed.bottom)), 0, len(depth) - 1))
        if not active[idx]:
            continue
        n_beds += 1
        if not (np.abs(tops - bed.bottom) < 1e-6).any():
            continue
        mark = round(float(bed.bottom), 6)
        if mark in seen:
            continue
        seen.add(mark)
        lst = boundaries.setdefault(_zone_name(keys[idx]), [])
        if len(lst) >= BOUNDARY_CAP:
            truncated = True
        else:
            lst.append(float(bed.bottom))
    for lst in boundaries.values():
        lst.sort()

    p = asdict(params)
    edits = p.pop("edits")
    label = GENERIC_RESPONSES.get(info.get("tool", "custom"), GENERIC_RESPONSES["custom"])["label"]
    if p.get("min_bed_ft") is None:
        p["min_bed_ft"] = default_min_bed(info["hires"].get("curve"))
    p["lambda"] = p.pop("lam")
    p.update({"tool": info.get("tool", "custom"), "label": label, "width_ft": float(params.width_ft)})
    block = {
        "hires": dict(info["hires"]),
        "params": p,
        "zones": zone_rows,
        "windows": [asdict(w) for w in res.windows],
        "n_beds": n_beds,
        "boundaries": boundaries,
        "edits": {"add": list(edits.get("add", [])), "remove": list(edits.get("remove", []))},
        "counts": counts,
    }
    if truncated:
        block["truncated"] = True
    return block
