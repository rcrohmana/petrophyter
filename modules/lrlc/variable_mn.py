"""Variable cementation and saturation exponents (pure, numpy / pandas / scipy only, no Qt).

``m`` and ``n`` of a zone become per-sample curves of porosity and shale volume:

    m = c0 + c1 * phi + c2 * Vsh + c3 / phi          (user formula, ``m_coef = [c0, c1, c2, c3]``)
    m = 1.87 + 0.019 / phi                           (Shell, carbonate zones only)
    n = d0 + d1 * Vsh                                (``n_coef = [d0, d1]``)

``build_mn_curves`` evaluates them for all samples of a segment at once, zone by zone, and
returns arrays that are always finite (samples that cannot be evaluated keep the scalar value).
``fit_variable_m`` proposes the formula coefficients from wet points; it writes nothing.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

REFS = ("archie1942", "guo2023", "rasmus1986", "borai1987")

# Samples below this porosity are not evaluated (a 1/phi term explodes).
PHI_MIN = 0.02
SHELL_COEF = (1.87, 0.0, 0.0, 0.019)
SHELL_PRESET = "Carbonate"

# Coefficient bounds of the user formula and of the n formula (the same as the settings ranges).
M_COEF_BOUNDS = ((0.5, 5.0), (-10.0, 10.0), (-3.0, 3.0), (-0.5, 0.5))
N_COEF_BOUNDS = ((1.0, 4.0), (-3.0, 3.0))

DEFAULT_CLIP = (1.0, 4.0)

FIT_DEFAULTS: Dict[str, Any] = {
    "min_points_per_param": 15,
    "min_phi_range": 0.05,
    "min_vsh_range": 0.10,
    "phi_window": [0.03, 0.60],
    "f_scale": 0.1,
    "max_implausible_fraction": 0.05,
}

CODE_CLIPPED = "LRLC_MN_CLIPPED"
CODE_FALLBACK = "LRLC_MN_FALLBACK"
CODE_SHELL = "LRLC_MN_SHELL_LITHOLOGY"
CODE_INVALID = "LRLC_MN_SETTING_INVALID"


# ---------------------------------------------------------------------------
# Formulas
# ---------------------------------------------------------------------------
def m_formula(phi, vsh, coef) -> np.ndarray:
    """``c0 + c1*phi + c2*Vsh + c3/phi``; ``coef`` has shape (4,) or (N, 4).

    Not guarded: the caller keeps ``phi`` at or above ``PHI_MIN`` and finite.
    """
    phi = np.asarray(phi, dtype=float)
    vsh = np.asarray(vsh, dtype=float)
    c = np.asarray(coef, dtype=float)
    if c.ndim == 1:
        c0, c1, c2, c3 = c[0], c[1], c[2], c[3]
    else:
        c0, c1, c2, c3 = c[:, 0], c[:, 1], c[:, 2], c[:, 3]
    with np.errstate(divide="ignore", invalid="ignore"):
        return c0 + c1 * phi + c2 * vsh + c3 / phi


def shell_m(phi) -> np.ndarray:
    """Shell formula ``m = 1.87 + 0.019 / phi`` (phi as a fraction)."""
    return m_formula(phi, np.zeros_like(np.asarray(phi, dtype=float)), SHELL_COEF)


def n_formula(vsh, coef) -> np.ndarray:
    """``d0 + d1*Vsh``; ``coef`` has shape (2,) or (N, 2)."""
    vsh = np.asarray(vsh, dtype=float)
    c = np.asarray(coef, dtype=float)
    if c.ndim == 1:
        return c[0] + c[1] * vsh
    return c[:, 0] + c[:, 1] * vsh


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------
@dataclass
class MnResult:
    m: np.ndarray               # M_VAR: finite everywhere
    n: np.ndarray               # N_VAR: finite everywhere
    m_valid: np.ndarray         # bool, the m curve was evaluated
    n_valid: np.ndarray         # bool, the n curve was evaluated
    counts: Dict[Any, Dict[str, Any]] = field(default_factory=dict)
    refs: Tuple[str, ...] = REFS

    @property
    def any_curve(self) -> bool:
        return any(c["mode"] == "curve" for c in self.counts.values())


def _valid_coef(coef, length: int) -> Optional[np.ndarray]:
    try:
        arr = np.asarray(coef, dtype=float)
    except (TypeError, ValueError):
        return None
    if arr.shape != (length,) or not np.all(np.isfinite(arr)):
        return None
    return arr


def _zone_setting(settings: Optional[dict], key: str, default):
    if not isinstance(settings, dict):
        return default
    return settings.get(key, default)


def _lithology_of(lithology, zone) -> Optional[str]:
    if isinstance(lithology, dict):
        return lithology.get(zone)
    return lithology


def _as_samples(value, size: int) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if arr.ndim == 0:
        return np.full(size, float(arr))
    return np.array(arr, dtype=float, copy=True)


def _clip_pair(clip, default=DEFAULT_CLIP) -> Tuple[float, float]:
    try:
        lo, hi = float(clip[0]), float(clip[1])
    except (TypeError, ValueError, IndexError):
        return default
    if not (np.isfinite(lo) and np.isfinite(hi) and lo < hi):
        return default
    return lo, hi


def _empty_counts(n_samples: int) -> Dict[str, Any]:
    return {
        "mode": "scalar", "m_model": None, "n_model": None, "n_samples": n_samples,
        "n_eval": 0, "n_fallback": 0, "n_clipped_m": 0, "n_clipped_n": 0, "shell_refused": 0,
        "shell_confirmed": False, "invalid_setting": False,
        "m_raw_min": None, "m_raw_max": None, "n_raw_min": None, "n_raw_max": None,
    }


def build_mn_curves(phi, vsh, zone_labels, zone_settings, scalar_m, scalar_n, clip_m, clip_n,
                    lithology) -> MnResult:
    """Per-sample ``m`` and ``n`` for one segment.

    ``phi`` and ``vsh`` are the porosity and shale volume the saturation model reads (fractions);
    ``zone_labels`` has one label per row; ``zone_settings`` maps a label to its resolved
    ladder dict (keys ``mn_mode``, ``m_model``, ``m_coef``, ``shell_confirm``, ``n_model``,
    ``n_coef``); a zone without settings stays scalar. ``scalar_m`` / ``scalar_n`` are the
    scoped values (a float or one value per row); ``lithology`` is a preset name or a dict
    zone -> preset name (Shell is evaluated in ``"Carbonate"`` zones only, or where the zone
    sets ``shell_confirm``).
    """
    phi = np.asarray(phi, dtype=float)
    vsh = np.asarray(vsh, dtype=float)
    size = phi.shape[0]
    labels = pd.Series(np.asarray(zone_labels, dtype=object)
                       if np.ndim(zone_labels) else np.full(size, zone_labels, dtype=object))
    if len(labels) != size or vsh.shape[0] != size:
        raise ValueError("phi, vsh and zone labels must have one value per row")
    m_out = _as_samples(scalar_m, size)
    n_out = _as_samples(scalar_n, size)
    m_valid = np.zeros(size, dtype=bool)
    n_valid = np.zeros(size, dtype=bool)
    lo_m, hi_m = _clip_pair(clip_m)
    lo_n, hi_n = _clip_pair(clip_n)
    counts: Dict[Any, Dict[str, Any]] = {}
    evaluable_all = np.isfinite(phi) & np.isfinite(vsh) & (phi >= PHI_MIN)

    codes, uniques = pd.factorize(labels, use_na_sentinel=False)
    for idx, zone in enumerate(uniques):
        rows = np.flatnonzero(codes == idx)
        cnt = _empty_counts(int(rows.size))
        counts[zone] = cnt
        st = zone_settings.get(zone) if isinstance(zone_settings, dict) else None
        mode = _zone_setting(st, "mn_mode", "scalar")
        if mode == "scalar" or st is None:
            continue
        m_model = _zone_setting(st, "m_model", "formula")
        n_model = _zone_setting(st, "n_model", "constant")
        m_coef = _valid_coef(_zone_setting(st, "m_coef", None), 4)
        n_coef = _valid_coef(_zone_setting(st, "n_coef", None), 2)
        bad = (mode != "curve" or m_model not in ("formula", "shell")
               or n_model not in ("constant", "vsh")
               or (m_model == "formula" and m_coef is None)
               or (n_model == "vsh" and n_coef is None))
        if bad:
            cnt["invalid_setting"] = True
            continue
        cnt["mode"] = "curve"
        cnt["m_model"], cnt["n_model"] = m_model, n_model

        ok = evaluable_all[rows]
        cnt["n_eval"] = int(ok.sum())
        cnt["n_fallback"] = int(rows.size - ok.sum())
        eval_rows = rows[ok]
        if eval_rows.size == 0:
            if m_model == "shell" and _lithology_of(lithology, zone) != SHELL_PRESET \
                    and not bool(_zone_setting(st, "shell_confirm", False)):
                cnt["shell_refused"] = int(rows.size)
            continue

        # m
        use_m = True
        if m_model == "shell":
            carbonate = _lithology_of(lithology, zone) == SHELL_PRESET
            confirmed = bool(_zone_setting(st, "shell_confirm", False))
            if not carbonate and not confirmed:
                use_m = False
                cnt["shell_refused"] = int(rows.size)
            elif not carbonate:
                cnt["shell_confirmed"] = True
        if use_m:
            raw = (shell_m(phi[eval_rows]) if m_model == "shell"
                   else m_formula(phi[eval_rows], vsh[eval_rows], m_coef))
            cnt["m_raw_min"], cnt["m_raw_max"] = float(raw.min()), float(raw.max())
            cnt["n_clipped_m"] = int(((raw < lo_m) | (raw > hi_m)).sum())
            m_out[eval_rows] = np.clip(raw, lo_m, hi_m)
            m_valid[eval_rows] = True
        # n
        if n_model == "vsh":
            raw = n_formula(vsh[eval_rows], n_coef)
            cnt["n_raw_min"], cnt["n_raw_max"] = float(raw.min()), float(raw.max())
            cnt["n_clipped_n"] = int(((raw < lo_n) | (raw > hi_n)).sum())
            n_out[eval_rows] = np.clip(raw, lo_n, hi_n)
            n_valid[eval_rows] = True
    return MnResult(m=m_out, n=n_out, m_valid=m_valid, n_valid=n_valid, counts=counts)


def curve_percentiles(result: MnResult, zone_labels) -> Dict[Any, Dict[str, Optional[float]]]:
    """Per zone P05 / P50 / P95 of ``m`` and ``n`` over the samples of curve zones."""
    labels = pd.Series(np.asarray(zone_labels, dtype=object))
    codes, uniques = pd.factorize(labels, use_na_sentinel=False)
    out: Dict[Any, Dict[str, Optional[float]]] = {}
    for idx, zone in enumerate(uniques):
        cnt = result.counts.get(zone)
        if cnt is None or cnt["mode"] != "curve":
            continue
        rows = codes == idx
        entry: Dict[str, Optional[float]] = {}
        for name, arr in (("m", result.m), ("n", result.n)):
            vals = arr[rows]
            vals = vals[np.isfinite(vals)]
            for q in (5, 50, 95):
                entry[f"{name}_p{q:02d}"] = float(np.percentile(vals, q)) if vals.size else None
        out[zone] = entry
    return out


def mn_issues(result: MnResult, warn_fraction: float = 0.05) -> List[dict]:
    """Issue records ``{code, severity, zone, text}`` for the counts of a result.

    Clipping is info below ``warn_fraction`` of a zone's samples and a warning above;
    fallback is info below 5 percent and a warning above.
    """
    issues: List[dict] = []
    for zone, c in result.counts.items():
        label = "the well" if zone is None or (isinstance(zone, float) and np.isnan(zone)) \
            else f"zone {zone}"
        if c["invalid_setting"]:
            issues.append({"code": CODE_INVALID, "severity": "warning", "zone": zone, "text": (
                f"Variable m/n: the settings of {label} are not valid; constant m and n are "
                "used there.")})
        if c["shell_refused"]:
            issues.append({"code": CODE_SHELL, "severity": "warning", "zone": zone, "text": (
                f"Variable m/n: the Shell model is for carbonate zones and {label} is not "
                "one; the constant m is used there unless you confirm the Shell model.")})
        elif c["shell_confirmed"]:
            issues.append({"code": CODE_SHELL, "severity": "info", "zone": zone, "text": (
                f"Variable m/n: the Shell model is used in {label}, which is not a carbonate "
                "zone, because you confirmed it.")})
        if c["mode"] != "curve":
            continue
        total = max(c["n_samples"], 1)
        clipped = c["n_clipped_m"] + c["n_clipped_n"]
        if clipped:
            frac = max(c["n_clipped_m"], c["n_clipped_n"]) / total
            issues.append({
                "code": CODE_CLIPPED, "severity": "warning" if frac > warn_fraction else "info",
                "zone": zone, "text": (
                    f"Variable m/n: {c['n_clipped_m']} m and {c['n_clipped_n']} n values in "
                    f"{label} were outside the allowed range and were clipped to it.")})
        if c["n_fallback"]:
            frac = c["n_fallback"] / total
            issues.append({
                "code": CODE_FALLBACK, "severity": "warning" if frac > 0.05 else "info",
                "zone": zone, "text": (
                    f"Variable m/n: {c['n_fallback']} samples in {label} have no usable "
                    "porosity or shale volume (or porosity below 0.02); constant m and n are "
                    "used there.")})
    return issues


# ---------------------------------------------------------------------------
# Fit (proposal only)
# ---------------------------------------------------------------------------
@dataclass
class MnFitResult:
    status: str                              # ok / insufficient points / implausible m / notes
    coef: Optional[List[float]] = None       # [c0, c1, c2, 0.0]; None when nothing is proposed
    se: Optional[List[Optional[float]]] = None
    free: Tuple[str, ...] = ()
    n_used: int = 0
    excluded: Dict[str, int] = field(default_factory=dict)
    rmse_ln_rt: Optional[float] = None
    rmse_m: Optional[float] = None
    bias_m: Optional[float] = None
    r2_m: Optional[float] = None
    phi_range: Optional[Tuple[float, float]] = None
    vsh_range: Optional[Tuple[float, float]] = None
    m_range: Optional[Tuple[float, float]] = None
    notes: List[str] = field(default_factory=list)
    apply_allowed: bool = False
    pickett_equivalent: bool = False
    message: str = ""
    n_implausible: int = 0
    index: Optional[np.ndarray] = None       # positions (input rows) of the points used
    m_obs: Optional[np.ndarray] = None       # observed m = ln(a Rw / Rt) / ln(phi), points used
    m_fit: Optional[np.ndarray] = None
    refs: Tuple[str, ...] = ("archie1942", "pickett1966", "guo2023", "rasmus1986")


def _range_of(x) -> Tuple[float, float]:
    return float(np.percentile(x, 5)), float(np.percentile(x, 95))


def fit_variable_m(phi, rt, vsh, rw, a, wet_mask=None, options: Optional[dict] = None,
                   clip_m: Sequence[float] = DEFAULT_CLIP) -> MnFitResult:
    """Fit ``c0, c1, c2`` of the m formula to wet points (Archie at Sw = 1).

    ``t_i = ln(a Rw_i / Rt_i) = (c0 + c1 phi_i + c2 Vsh_i) ln(phi_i)`` is linear in the
    coefficients; the residual is taken in ln Rt and solved with a robust (soft L1) least
    squares (soft L1 loss, solved by iterative reweighting). ``rw`` is a float or one value
    per row; ``wet_mask`` selects the wet points
    (all rows when None). ``c1`` / ``c2`` are freed only when the porosity / shale-volume
    spread (P95 - P05) of the points allows it. Nothing is stored anywhere.
    """
    from scipy.optimize import lsq_linear

    opt = dict(FIT_DEFAULTS)
    if options:
        opt.update({k: v for k, v in options.items() if k in FIT_DEFAULTS})
    phi = np.asarray(phi, dtype=float)
    rt = np.asarray(rt, dtype=float)
    vsh = np.asarray(vsh, dtype=float)
    size = phi.shape[0]
    rw = np.broadcast_to(np.asarray(rw, dtype=float), (size,))
    wet = np.ones(size, dtype=bool) if wet_mask is None else np.asarray(wet_mask, dtype=bool)
    lo_m, hi_m = _clip_pair(clip_m)
    w_lo, w_hi = float(opt["phi_window"][0]), float(opt["phi_window"][1])

    finite = (np.isfinite(phi) & np.isfinite(rt) & np.isfinite(vsh) & np.isfinite(rw)
              & (rt > 0) & (rw > 0) & (phi > 0) & (phi < 1))
    excluded = {"not_wet": int((~wet).sum()), "nan": int((wet & ~finite).sum())}
    in_window = (phi >= w_lo) & (phi <= w_hi)
    excluded["window"] = int((wet & finite & ~in_window).sum())
    keep = wet & finite & in_window
    idx = np.flatnonzero(keep)
    res = MnFitResult(status="insufficient points", excluded=excluded, n_used=int(idx.size))
    if idx.size == 0:
        res.message = "No wet points are usable."
        return res

    p, v = phi[idx], vsh[idx]
    t = np.log(a * rw[idx] / rt[idx])
    lnp = np.log(p)
    res.phi_range, res.vsh_range = _range_of(p), _range_of(v)
    notes: List[str] = []
    free = [0]
    if res.phi_range[1] - res.phi_range[0] >= opt["min_phi_range"]:
        free.append(1)
    else:
        notes.append("phi range too small, c1 fixed")
    if res.vsh_range[1] - res.vsh_range[0] >= opt["min_vsh_range"]:
        free.append(2)
    else:
        notes.append("vsh range too small, c2 fixed")
    need = int(opt["min_points_per_param"]) * len(free)
    if idx.size < need:
        res.message = (f"{idx.size} wet points; {need} are needed for {len(free)} free "
                       "coefficient(s).")
        res.notes = notes
        return res

    cols_all = np.column_stack([lnp, p * lnp, v * lnp])
    # Drop coefficients (last first) while the normal equations are singular.
    while True:
        x_mat = cols_all[:, free]
        if len(free) == 1 or np.linalg.matrix_rank(x_mat) == len(free):
            break
        dropped = free.pop()
        notes.append(f"singular, c{dropped} fixed")
    x_mat = cols_all[:, free]
    bounds = ([M_COEF_BOUNDS[i][0] for i in free], [M_COEF_BOUNDS[i][1] for i in free])
    x0 = np.clip(np.linalg.lstsq(x_mat, t, rcond=None)[0], bounds[0], bounds[1])
    fs = float(opt["f_scale"])
    c_free = x0
    for _ in range(200):          # iteratively reweighted least squares of the soft L1 loss
        weights = 1.0 / np.sqrt(1.0 + ((x_mat @ c_free - t) / fs) ** 2)
        root = np.sqrt(weights)
        step = lsq_linear(x_mat * root[:, None], t * root, bounds=bounds).x
        done = float(np.max(np.abs(step - c_free))) < 1e-12
        c_free = step
        if done:
            break
    coef = np.zeros(4)
    for j, i in enumerate(free):
        coef[i] = c_free[j]
    e = x_mat @ c_free - t
    weights = 1.0 / np.sqrt(1.0 + (e / fs) ** 2)
    dof = max(idx.size - len(free), 1)
    s2 = float(np.sum(weights * e * e) / dof)
    se: List[Optional[float]] = [None] * 4
    try:
        cov = np.linalg.inv(x_mat.T @ (x_mat * weights[:, None])) * s2
        for j, i in enumerate(free):
            se[i] = float(np.sqrt(max(cov[j, j], 0.0)))
    except np.linalg.LinAlgError:
        pass

    m_fit = m_formula(p, v, coef)
    m_obs = t / lnp
    small = p <= 0.5
    res.coef = [float(c) for c in coef]
    res.se = se
    res.free = tuple(f"c{i}" for i in free)
    res.rmse_ln_rt = float(np.sqrt(np.mean(e * e)))
    if small.any():
        d = m_fit[small] - m_obs[small]
        res.rmse_m = float(np.sqrt(np.mean(d * d)))
        res.bias_m = float(np.mean(d))
        var = float(np.sum((m_obs[small] - m_obs[small].mean()) ** 2))
        res.r2_m = float(1.0 - np.sum(d * d) / var) if var > 0 else None
    res.m_range = (float(m_fit.min()), float(m_fit.max()))
    res.index, res.m_obs, res.m_fit = idx, m_obs, m_fit
    res.n_used = int(idx.size)
    res.pickett_equivalent = len(free) == 1
    res.notes = notes
    res.n_implausible = int(((m_fit < lo_m) | (m_fit > hi_m)).sum())
    if res.n_implausible > opt["max_implausible_fraction"] * idx.size:
        res.status = "implausible m"
        res.apply_allowed = False
        res.message = f"fitted m is outside {lo_m:g}-{hi_m:g} for {res.n_implausible} points"
    else:
        res.status = "; ".join(notes) if notes else "ok"
        res.apply_allowed = True
        res.message = ("Only c0 is free: the result equals the constant m of a Pickett fit."
                       if res.pickett_equivalent else "")
    return res
