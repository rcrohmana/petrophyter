"""Rt correction chain framework (pure: numpy/pandas only, no Qt, no pipeline import).

RT (measured, never modified) -> step_1 -> step_2 -> ... (fixed order, per LRLC zone)
=> ``RT_SW``, the Rt every Sw model reads in the segment.

``ctx_arrays`` contract (built by the pipeline glue, one entry per sample of the SEGMENT,
all in ``data.index`` order)::

    required float arrays, length n:  depth, rt_raw, vsh, phit, phie, rsh, rw
        rsh / rw are the EFFECTIVE per-sample values (Arps applied); a scalar is broadcast.
    optional float arrays or None:    temperature, rhob, pef, rm, rs, rxo, hires
        a missing key or None means "curve not available" (ChainContext field is None).
    optional bool array or None:      data_mask   (False = not measured data; None = all data)
    optional dict:                    flags    (copied, not sliced; e.g. {"shoulder_corrected": False})
    optional dict of arrays:          derived  (DERIVES outputs aligned to the segment rows)

``rt_raw`` defaults to the ``rt`` argument when absent. ``ctx_for(zone, rows)`` slices every
array to ``rows`` (integer positions inside the segment); ``segment_depth`` is the whole
segment's depth. Nothing passed in is ever mutated.

Issues are tuples ``(code, text, zone, severity_or_None)``; ``zone`` is None for the
unzoned key. A replay (``rerun_chain``) emits none.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import numpy as np

from modules.param_scopes import UNZONED

CHAIN_ORDER = ("decon", "invasion", "laminated", "pyrite")

_RESERVED_COLUMNS = ("RT", "RT_SW")
_OPTIONAL_ARRAYS = ("temperature", "rhob", "pef", "rm", "rs", "rxo", "hires")
_REQUIRED_ARRAYS = ("depth", "rt_raw", "vsh", "phit", "phie", "rsh", "rw")


@dataclass(frozen=True)
class StepSpec:
    name: str
    order: int
    column: str
    fn: Callable[..., "StepResult"]
    label: str
    description: str
    refs: Tuple[str, ...]
    params: Tuple[str, ...] = ()
    varied: Tuple[str, ...] = ()
    extra_columns: Tuple[str, ...] = ()
    kind: str = "test"


@dataclass(frozen=True)
class DeriveSpec:
    name: str
    scope: str                      # "segment" | "well"
    fn: Callable[..., Dict[str, np.ndarray]]
    outputs: Tuple[str, ...]


@dataclass
class ChainContext:
    depth: np.ndarray
    zone: str
    rows: np.ndarray
    rt_raw: np.ndarray
    vsh: np.ndarray
    phit: np.ndarray
    phie: np.ndarray
    rsh: np.ndarray
    rw: np.ndarray
    temperature: Optional[np.ndarray]
    rhob: Optional[np.ndarray]
    pef: Optional[np.ndarray]
    rm: Optional[np.ndarray]
    rs: Optional[np.ndarray]
    rxo: Optional[np.ndarray]
    hires: Optional[np.ndarray]
    segment_depth: np.ndarray
    flags: Dict[str, Any]
    derived: Dict[str, np.ndarray]
    data_mask: Optional[np.ndarray] = None


@dataclass
class StepResult:
    rt_out: np.ndarray
    valid_mask: np.ndarray
    counts: Dict[str, int] = field(default_factory=dict)
    extra_columns: Dict[str, np.ndarray] = field(default_factory=dict)
    refs: Tuple[str, ...] = ()


@dataclass
class GuardDecision:
    specs_kept: List[StepSpec]
    invalid_mask: Optional[np.ndarray] = None
    issues: List[tuple] = field(default_factory=list)


@dataclass
class _ReplayZone:
    zone: str
    rows: np.ndarray
    entering: np.ndarray            # frozen Rt entering the first varied step
    specs: List[StepSpec]           # that step and every later one that ran
    params: List[dict]
    fallback: str


@dataclass
class ChainReplay:
    base_rt_sw: np.ndarray
    ctx_arrays: Dict[str, Any]
    zones: List[_ReplayZone]


@dataclass
class ChainOutput:
    rt_values: Optional[np.ndarray]
    write_rt_sw: bool
    rt_sw: np.ndarray
    columns: Dict[str, np.ndarray]
    records: List[dict]
    issues: List[tuple]
    replay: Optional[ChainReplay]
    guard_masked: Dict[str, int] = field(default_factory=dict)


STEPS: Dict[str, StepSpec] = {}
DERIVES: Dict[str, DeriveSpec] = {}


def register(spec: StepSpec) -> None:
    if spec.name in STEPS:
        raise ValueError(f"Rt step {spec.name!r} is already registered")
    taken = set(_RESERVED_COLUMNS)
    for other in STEPS.values():
        taken.add(other.column)
        taken.update(other.extra_columns)
    mine = (spec.column,) + tuple(spec.extra_columns)
    for col in mine:
        if col in taken:
            raise ValueError(f"result column {col!r} is already used by another Rt step")
    if len(set(mine)) != len(mine):
        raise ValueError("a step's columns must be distinct")
    STEPS[spec.name] = spec


def register_derive(spec: DeriveSpec) -> None:
    if spec.name in DERIVES:
        raise ValueError(f"derive {spec.name!r} is already registered")
    if spec.scope not in ("segment", "well"):
        raise ValueError("derive scope must be 'segment' or 'well'")
    DERIVES[spec.name] = spec


def available_steps() -> List[StepSpec]:
    return sorted(STEPS.values(), key=lambda s: (s.order, s.name))


def resolve_steps(names) -> Tuple[List[StepSpec], List[str]]:
    """(known specs sorted by order, unknown names); duplicates collapse."""
    known: Dict[str, StepSpec] = {}
    unknown: List[str] = []
    for name in names or []:
        if isinstance(name, str) and name in STEPS:
            known[name] = STEPS[name]
        else:
            text = str(name)
            if text not in unknown:
                unknown.append(text)
    return sorted(known.values(), key=lambda s: (s.order, s.name)), unknown


def chain_path(specs) -> str:
    """"RT_SAND <- RT_INV <- RT"; "RT" when no spec."""
    ordered = sorted(specs or [], key=lambda s: (s.order, s.name))
    return " <- ".join([s.column for s in reversed(ordered)] + ["RT"])


def step_params(prm: dict, spec: StepSpec) -> dict:
    """The resolved LRLC values a step reads (``spec.params``)."""
    return {key: prm.get(key) for key in spec.params}


def _unique_keys(zone_keys) -> List[str]:
    arr = np.asarray(zone_keys, dtype=object)
    seen: Dict[str, None] = {}
    for key in arr:
        seen.setdefault(key, None)
    return list(seen)


def _resolved(lrlc: dict, zone: str) -> dict:
    res = lrlc["resolved"]
    return res.get("zones", {}).get(zone, res["default"])


def chain_active_anywhere(lrlc, zone_keys) -> bool:
    """True when any zone present lists at least one known step."""
    if not lrlc or "resolved" not in lrlc:
        return False
    for zone in _unique_keys(zone_keys):
        specs, _ = resolve_steps(_resolved(lrlc, zone).get("rt_steps", []))
        if specs:
            return True
    return False


def _zone_label(zone: str) -> Optional[str]:
    return None if zone == UNZONED else zone


def _normalise(ctx_arrays: dict, rt: np.ndarray) -> Dict[str, Any]:
    n = len(rt)
    out: Dict[str, Any] = {}
    src = dict(ctx_arrays)
    src.setdefault("rt_raw", rt)
    for key in _REQUIRED_ARRAYS:
        if key not in src or src[key] is None:
            raise ValueError(f"ctx_arrays is missing {key!r}")
        out[key] = np.broadcast_to(np.asarray(src[key], dtype=float), (n,))
    for key in _OPTIONAL_ARRAYS:
        v = src.get(key)
        out[key] = None if v is None else np.broadcast_to(np.asarray(v, dtype=float), (n,))
    mask = src.get("data_mask")
    out["data_mask"] = None if mask is None else np.broadcast_to(np.asarray(mask, dtype=bool), (n,))
    out["flags"] = dict(src.get("flags") or {})
    out["derived"] = {k: np.asarray(v) for k, v in (src.get("derived") or {}).items()}
    return out


def _ctx_for(arrays: Dict[str, Any], zone: str, rows: np.ndarray) -> ChainContext:
    def cut(key):
        v = arrays[key]
        return None if v is None else np.array(v[rows], dtype=float)

    mask = arrays["data_mask"]
    return ChainContext(
        depth=cut("depth"), zone=zone, rows=rows, rt_raw=cut("rt_raw"),
        vsh=cut("vsh"), phit=cut("phit"), phie=cut("phie"),
        rsh=cut("rsh"), rw=cut("rw"), temperature=cut("temperature"),
        rhob=cut("rhob"), pef=cut("pef"), rm=cut("rm"), rs=cut("rs"),
        rxo=cut("rxo"), hires=cut("hires"),
        segment_depth=np.array(arrays["depth"], dtype=float),
        flags=dict(arrays["flags"]),
        derived={k: np.array(v[rows]) for k, v in arrays["derived"].items()},
        data_mask=None if mask is None else np.array(mask[rows]),
    )


def _exec_step(spec: StepSpec, cur: np.ndarray, ctx: ChainContext, prm: dict, fallback: str):
    """Run one step and sanitise its output. Returns (out, res, n_valid, n_bad, n_fallback)."""
    n = len(ctx.rows)
    res = spec.fn(cur.copy(), ctx, step_params(prm, spec))
    out = np.array(res.rt_out, dtype=float)
    vm = np.asarray(res.valid_mask, dtype=bool)
    if out.shape != (n,) or vm.shape != (n,):
        raise ValueError(f"step {spec.name!r} must return {n} values (got {out.shape}, {vm.shape})")
    elig = np.isfinite(cur)
    with np.errstate(invalid="ignore"):
        valid = vm & np.isfinite(out) & (out > 0)
    bad = elig & ~valid
    out[~valid] = np.nan
    n_fallback = 0
    if fallback == "previous":
        sub = bad & np.isfinite(cur)
        out[sub] = cur[sub]
        n_fallback = int(sub.sum())
    return out, res, int((elig & valid).sum()), int(bad.sum()), n_fallback


def apply_rt_chain(rt, ctx_arrays, zone_keys, lrlc, force_rt_sw, guard=None,
                   segment: Optional[str] = None) -> ChainOutput:
    rt = np.asarray(rt, dtype=float)
    n = len(rt)
    zone_arr = np.asarray(zone_keys, dtype=object)
    if zone_arr.shape != (n,):
        raise ValueError("zone_keys must have one entry per sample")
    arrays = _normalise(ctx_arrays, rt)

    rt_sw = rt.copy()
    any_ran = False
    columns: Dict[str, np.ndarray] = {}
    records: List[dict] = []
    issues: List[tuple] = []
    guard_masked: Dict[str, int] = {}
    replay_zones: List[_ReplayZone] = []

    def col(name):
        if name not in columns:
            columns[name] = np.full(n, np.nan)
        return columns[name]

    for zone in _unique_keys(zone_arr):
        rows = np.flatnonzero(zone_arr == zone)
        label = _zone_label(zone)
        shown = label or "the unzoned interval"
        prm = _resolved(lrlc, zone)
        fallback = prm.get("rt_fallback", "nan")
        specs, unknown = resolve_steps(prm.get("rt_steps", []))
        for name in unknown:
            issues.append(("LRLC_STEP_UNKNOWN",
                           f"Rt correction step {name!r} is not available and was skipped in {shown}.",
                           label, None))
        cur = rt[rows]
        if guard is not None:
            dec = guard(zone, specs, _ctx_for(arrays, zone, rows))
            specs = sorted(dec.specs_kept, key=lambda s: (s.order, s.name))
            issues.extend(dec.issues or [])
            if dec.invalid_mask is not None:
                m = np.asarray(dec.invalid_mask, dtype=bool) & np.isfinite(cur)
                if fallback != "previous":
                    cur = np.where(m, np.nan, cur)
                guard_masked[zone] = int(m.sum())
                any_ran |= bool(m.any())
        prev_col = "RT"
        replay_from: Optional[int] = None
        entering = None
        for i, spec in enumerate(specs):
            if replay_from is None and spec.varied:
                replay_from, entering = i, cur.copy()
            ctx = _ctx_for(arrays, zone, rows)
            out, res, n_valid, n_bad, n_fb = _exec_step(spec, cur, ctx, prm, fallback)
            extras = dict(res.extra_columns or {})
            for key, vals in extras.items():
                if key not in spec.extra_columns:
                    raise ValueError(f"step {spec.name!r} returned undeclared column {key!r}")
                vals = np.asarray(vals, dtype=float)
                if vals.shape != (len(rows),):
                    raise ValueError(f"extra column {key!r} must have one value per row")
                col(key)[rows] = vals
            col(spec.column)[rows] = out
            if fallback == "previous":
                if n_fb:
                    issues.append(("LRLC_STEP_FALLBACK",
                                   f"{spec.label}: {n_fb} invalid sample(s) in {shown} took the previous Rt.",
                                   label, None))
            elif n_bad:
                issues.append(("LRLC_STEP_INVALID",
                               f"{spec.label}: {n_bad} sample(s) in {shown} gave no valid Rt (left empty).",
                               label, None))
            refs = list(dict.fromkeys(list(spec.refs) + list(res.refs or ())))
            records.append({
                "zone": label, "segment": segment, "step": spec.name, "curve": spec.column,
                "from": prev_col, "params": step_params(prm, spec), "refs": refs,
                "n_valid": n_valid, "n_invalid": n_bad, "fallback": n_fb,
            })
            prev_col = spec.column
            cur = out
            any_ran = True
        rt_sw[rows] = cur
        if replay_from is not None:
            kept = specs[replay_from:]
            replay_zones.append(_ReplayZone(
                zone=zone, rows=rows, entering=entering, specs=list(kept),
                params=[dict(prm) for _ in kept], fallback=fallback))

    replay = ChainReplay(rt_sw.copy(), arrays, replay_zones) if replay_zones else None
    return ChainOutput(
        rt_values=rt_sw if any_ran else None,
        write_rt_sw=bool(any_ran or force_rt_sw),
        rt_sw=rt_sw, columns=columns, records=records, issues=issues,
        replay=replay, guard_masked=guard_masked)


def rerun_chain(replay: ChainReplay, overrides: Dict[str, Any]) -> np.ndarray:
    """New ``rt_sw`` with ctx.rsh / ctx.rw replaced; only the steps from the first varied one run."""
    arrays = dict(replay.ctx_arrays)
    n = len(replay.base_rt_sw)
    for key in ("rsh", "rw"):
        if overrides and overrides.get(key) is not None:
            arrays[key] = np.broadcast_to(np.asarray(overrides[key], dtype=float), (n,))
    rt_sw = replay.base_rt_sw.copy()
    for rz in replay.zones:
        cur = rz.entering.copy()
        for spec, prm in zip(rz.specs, rz.params):
            ctx = _ctx_for(arrays, rz.zone, rz.rows)
            cur = _exec_step(spec, cur, ctx, prm, rz.fallback)[0]
        rt_sw[rz.rows] = cur
    return rt_sw
