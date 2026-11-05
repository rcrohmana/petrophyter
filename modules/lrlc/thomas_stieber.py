"""Thomas-Stieber decomposition of shale volume into laminar and dispersed parts (pure: numpy/pandas only, no Qt, no pipeline import).

Two end-member model (sand laminae with dispersed clay, plus shale laminae) in the
Vsh - PHIT plane::

    phi_sand = phi_max - Vd_s * (1 - phi_sh)
    phi_t    = (1 - Vlam) * phi_sand + Vlam * phi_sh
    Vsh      = Vlam + (1 - Vlam) * Vd_s

    =>  Vlam = [phi_t - phi_max + Vsh * (1 - phi_sh)] / (1 - phi_max)

The closed form is clamped to the triangle of physically possible points and each sample
gets a class (``TS_CLASS``): 0 n/a, 1 laminar, 2 dispersed, 3 mixed, 4 structural,
5 clay-supported.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from modules.lrlc.config import LRLC_RANGES
from modules.param_scopes import UNZONED, ZONE_AUTO_MIN_FT

CLASS_NA, CLASS_LAMINAR, CLASS_DISPERSED, CLASS_MIXED = 0, 1, 2, 3
CLASS_STRUCTURAL, CLASS_CLAY_SUPPORTED = 4, 5

MIN_ENDPOINT_GAP = 0.02


@dataclass
class TsResult:
    vlam: np.ndarray
    vdisp: np.ndarray
    phi_sand: np.ndarray
    ts_class: np.ndarray
    # {"classes": {0..5: n}, "clamped": {"structural", "clay_supported", "below_dispersed"},
    #  "no_endpoints": n, "nan_input": n}
    counts: Dict[str, object] = field(default_factory=dict)


@dataclass
class Proposal:
    phi_max: float = float("nan")
    phi_sh: float = float("nan")
    n_clean: int = 0
    n_shale: int = 0
    source: Optional[str] = None        # "zone" | "well" | None
    ok: bool = False
    reason: Optional[str] = None


def _as_array(value, n) -> np.ndarray:
    if value is None:
        return np.full(n, np.nan)
    return np.broadcast_to(np.asarray(value, dtype=float), (n,))


def decompose(vsh, phit, phi_max, phi_sh, settings) -> TsResult:
    """Laminar / dispersed split. ``phi_max`` / ``phi_sh`` are scalars or per-sample arrays
    (NaN or None = no applied endpoint for that sample)."""
    vsh = np.atleast_1d(np.asarray(vsh, dtype=float))
    phit = np.atleast_1d(np.asarray(phit, dtype=float))
    n = len(vsh)
    if phit.shape != (n,):
        raise ValueError("vsh and phit must have the same length")
    pm = _as_array(phi_max, n)
    ps = _as_array(phi_sh, n)
    tol = float(settings.get("class_tol", 0.03))
    share = float(settings.get("class_share", 0.20))
    cmin = float(settings.get("class_vsh_min", 0.05))
    cmax = float(settings.get("class_vsh_max", 0.95))

    with np.errstate(invalid="ignore", divide="ignore"):
        input_bad = ~np.isfinite(vsh) | ~np.isfinite(phit) | (vsh < 0) | (vsh > 1)
        applied = np.isfinite(pm) & np.isfinite(ps) & (pm < 1.0)
        no_end = ~input_bad & ~applied
        dead = input_bad | ~applied
        pm_s = np.where(applied, pm, 0.5)
        ps_s = np.where(applied, ps, 0.1)
        vsh_s = np.where(dead, 0.0, vsh)
        phit_s = np.where(dead, 0.0, phit)

        v_raw = (phit_s - pm_s + vsh_s * (1.0 - ps_s)) / (1.0 - pm_s)
        vmin = np.maximum(0.0, (vsh_s - pm_s) / (1.0 - pm_s))
        clipped = np.minimum(np.maximum(v_raw, vmin), vsh_s)

        outside_window = (vsh_s < cmin) | (vsh_s > cmax)
        structural = ~outside_window & (v_raw > vsh_s + tol)
        clay_sup = ~outside_window & ~structural & (vsh_s > pm_s) & (v_raw < vmin - tol)
        inside = ~outside_window & ~structural & ~clay_sup
        below_disp = inside & (vsh_s <= pm_s) & (v_raw < -tol)

        vlam = clipped.copy()
        vlam = np.where(structural, vsh_s, vlam)
        vlam = np.where(clay_sup, vmin, vlam)

        f = np.where(vsh_s > 0, vlam / np.where(vsh_s > 0, vsh_s, 1.0), 0.0)
        cls = np.zeros(n, dtype=int)
        cls[inside & (f >= 1.0 - share)] = CLASS_LAMINAR
        cls[inside & (f <= share)] = CLASS_DISPERSED
        cls[inside & (f < 1.0 - share) & (f > share)] = CLASS_MIXED
        cls[below_disp] = CLASS_DISPERSED
        cls[structural] = CLASS_STRUCTURAL
        cls[clay_sup] = CLASS_CLAY_SUPPORTED
        cls[dead] = CLASS_NA

        vdisp = vsh_s - vlam
        vd_s = np.where(vlam < 1.0, vdisp / np.where(vlam < 1.0, 1.0 - vlam, 1.0), 0.0)
        phi_sand = pm_s - vd_s * (1.0 - ps_s)

    vlam = np.where(dead, np.nan, vlam)
    vdisp = np.where(dead, np.nan, vdisp)
    phi_sand = np.where(dead, np.nan, phi_sand)

    counts = {
        "classes": {c: int((cls == c).sum()) for c in range(6)},
        "clamped": {
            "structural": int(structural.sum()),
            "clay_supported": int(clay_sup.sum()),
            "below_dispersed": int(below_disp.sum()),
        },
        "no_endpoints": int(no_end.sum()),
        "nan_input": int(input_bad.sum()),
    }
    return TsResult(vlam=vlam, vdisp=vdisp, phi_sand=phi_sand, ts_class=cls, counts=counts)


def check_endpoints(phi_max, phi_sh) -> Tuple[bool, Optional[str]]:
    """(ok, reason). Ranges from LRLC_RANGES and ``phi_sh < phi_max - 0.02``."""
    def num(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return v if np.isfinite(v) else None

    pm, ps = num(phi_max), num(phi_sh)
    if pm is None:
        return False, "Clean-sand porosity (phi_max) is not set."
    if ps is None:
        return False, "Shale porosity (phi_sh) is not set."
    lo, hi = LRLC_RANGES["phi_max"]
    if pm < lo or pm > hi:
        return False, f"Clean-sand porosity must be between {lo:g} and {hi:g}."
    lo, hi = LRLC_RANGES["phi_sh"]
    if ps < lo or ps > hi:
        return False, f"Shale porosity must be between {lo:g} and {hi:g}."
    if not ps < pm - MIN_ENDPOINT_GAP:
        return False, "Shale porosity must be at least 0.02 below the clean-sand porosity."
    return True, None


def _group_keys(zone_labels, n) -> np.ndarray:
    if zone_labels is None:
        return np.full(n, UNZONED, dtype=object)
    arr = np.asarray(zone_labels, dtype=object)
    if arr.shape != (n,):
        raise ValueError("zone_labels must have one entry per sample")
    return np.array([UNZONED if (z is None or z == "") else z for z in arr], dtype=object)


def _unique(keys) -> List:
    seen: Dict = {}
    for k in keys:
        seen.setdefault(k, None)
    return list(seen)


def _step(depth: np.ndarray) -> float:
    d = np.diff(depth[np.isfinite(depth)])
    d = np.abs(d[np.isfinite(d) & (d != 0)])
    return float(np.median(d)) if len(d) else 0.0


def _endpoints_from(vsh, phit, step, s) -> Tuple[float, float, int, int, Optional[str]]:
    """(phi_max, phi_sh, n_clean, n_shale, reason). reason is None when both are available."""
    ok = np.isfinite(vsh) & np.isfinite(phit)
    clean = ok & (vsh < float(s.get("clean_vsh", 0.05)))
    shale = ok & (vsh > float(s.get("shale_vsh", 0.80)))
    n_clean, n_shale = int(clean.sum()), int(shale.sum())
    reason = None
    if n_clean < int(s.get("clean_min_n", 30)):
        reason = f"Only {n_clean} clean-sand samples (need {int(s.get('clean_min_n', 30))})."
    elif n_clean * step < ZONE_AUTO_MIN_FT:
        reason = f"Clean sand is thinner than {ZONE_AUTO_MIN_FT:g} ft."
    elif n_shale < int(s.get("shale_min_n", 10)):
        reason = f"Only {n_shale} shale samples (need {int(s.get('shale_min_n', 10))})."
    if reason:
        return float("nan"), float("nan"), n_clean, n_shale, reason
    pm = float(np.percentile(phit[clean], float(s.get("clean_pct", 90.0))))
    ps = float(np.median(phit[shale]))
    return pm, ps, n_clean, n_shale, None


def propose_endpoints(vsh, phit, depth, zone_labels, settings) -> Dict[str, Proposal]:
    """Per-zone ``phi_max`` / ``phi_sh`` proposals; a zone short of samples or thickness
    takes the whole-well values (source "well")."""
    vsh = np.asarray(vsh, dtype=float)
    phit = np.asarray(phit, dtype=float)
    depth = np.asarray(depth, dtype=float)
    n = len(vsh)
    keys = _group_keys(zone_labels, n)
    w_pm, w_ps, w_nc, w_ns, w_reason = _endpoints_from(vsh, phit, _step(depth), settings)

    def build(pm, ps, nc, ns, source, reason):
        if reason:
            return Proposal(float("nan"), float("nan"), nc, ns, None, False, reason)
        ok, why = check_endpoints(pm, ps)
        return Proposal(pm, ps, nc, ns, source, ok, why)

    out: Dict[str, Proposal] = {}
    for zone in _unique(keys):
        if zone_labels is None:
            out[zone] = build(w_pm, w_ps, w_nc, w_ns, "well", w_reason)
            continue
        m = keys == zone
        pm, ps, nc, ns, reason = _endpoints_from(vsh[m], phit[m], _step(depth[m]), settings)
        if reason is None:
            out[zone] = build(pm, ps, nc, ns, "zone", None)
        elif w_reason is None:
            out[zone] = build(w_pm, w_ps, w_nc, w_ns, "well", None)
        else:
            out[zone] = build(pm, ps, nc, ns, None, f"{reason} The whole well also lacks data: {w_reason}")
    return out


def zone_stats(vsh, vlam, ts_class, dz, zone_labels, vsh_min) -> Dict[str, dict]:
    """Per zone ``{"lam_share", "mean_vlam", "n", "class_counts"}`` over samples with
    ``Vsh >= vsh_min`` and finite VLAM (thickness weighted by ``dz``)."""
    vsh = np.asarray(vsh, dtype=float)
    vlam = np.asarray(vlam, dtype=float)
    cls = np.asarray(ts_class)
    n = len(vsh)
    dz = np.broadcast_to(np.asarray(dz, dtype=float), (n,))
    keys = _group_keys(zone_labels, n)
    out: Dict[str, dict] = {}
    for zone in _unique(keys):
        m = keys == zone
        use = m & np.isfinite(vsh) & np.isfinite(vlam) & np.isfinite(dz) & (vsh >= float(vsh_min))
        w = dz[use]
        den = float((vsh[use] * w).sum())
        wsum = float(w.sum())
        lam_share = float((vlam[use] * w).sum() / den) if den > 0 else float("nan")
        mean_vlam = float((vlam[use] * w).sum() / wsum) if wsum > 0 else float("nan")
        out[zone] = {
            "lam_share": lam_share,
            "mean_vlam": mean_vlam,
            "n": int(use.sum()),
            "class_counts": {c: int((m & (cls == c)).sum()) for c in range(6)},
        }
    return out
