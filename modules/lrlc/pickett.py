"""Pickett plot helpers: wet-point selection and the robust (Huber) wet-line fit.

``log10 Rt = -m log10 PHI + log10(a Rw) - n log10 Sw``; wet points (Sw = 1) fall on a line
of slope ``-m`` with intercept ``log10(a Rw)``.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from modules.lrlc import SHIPPED_METHODS
from modules.param_scopes import VALID_RANGES

M_RANGE = VALID_RANGES["m"]
RW_RANGE = VALID_RANGES["rw"]
MIN_DECADES = 0.2          # narrowest log10 PHI span a fit is allowed on
MIN_BIN_SAMPLES = 5
HUBER_K = 1.345
MAX_ITER = 50
TOL = 1e-8

DEFAULT_SETTINGS = {
    "phi_source": "PHIE", "color_by": "VSH", "vsh_max": 0.25, "phi_min": 0.05,
    "wet_quantile": 0.10, "n_bins": 8, "min_points": 10, "fit_mode": "m_and_rw",
    "iso_sw": [1.0, 0.8, 0.6, 0.4, 0.2],
}


def _refs(method):
    def deco(fn):
        fn.refs = tuple(SHIPPED_METHODS[method])
        return fn
    return deco


@dataclass
class PickettFit:
    status: str
    m: float = float("nan")
    a_rw: float = float("nan")
    rw: float = float("nan")
    se_m: float = float("nan")
    se_c: float = float("nan")
    n_points: int = 0
    r2: float = float("nan")
    iterations: int = 0
    phi_range: Tuple[float, float] = (float("nan"), float("nan"))


def _valid(phi, rt):
    phi = np.asarray(phi, dtype=float).reshape(-1)
    rt = np.asarray(rt, dtype=float).reshape(-1)
    with np.errstate(invalid="ignore"):
        return phi, rt, np.isfinite(phi) & np.isfinite(rt) & (phi > 0) & (rt > 0)


@_refs("pickett")
def wet_points(phi, rt, vsh, settings: Dict[str, Any], manual: Optional[Sequence] = None
               ) -> np.ndarray:
    """Boolean mask of the wet points: automatic proposal, then the manual boxes.

    Automatic: candidates have ``VSH <= vsh_max`` and ``PHI >= phi_min``; ``log10 PHI`` is
    cut into ``n_bins`` equal-width bins (bins with fewer than 5 candidates are skipped) and
    each bin keeps the candidates at or below its ``wet_quantile`` quantile of ``log10 Rt``.
    ``rt`` is the ordinate of the plot (already normalised for temperature when that is on).
    ``manual`` is a list of ``(kind, phi_lo, phi_hi, rt_lo, rt_hi)``, kind ``"add"`` or
    ``"remove"``, applied in order after the proposal.
    """
    s = dict(DEFAULT_SETTINGS)
    s.update(settings or {})
    phi, rt, ok = _valid(phi, rt)
    size = len(phi)
    mask = np.zeros(size, dtype=bool)
    cand = ok & (phi >= s["phi_min"])
    if vsh is not None:
        v = np.asarray(vsh, dtype=float).reshape(-1)
        with np.errstate(invalid="ignore"):
            cand &= np.isfinite(v) & (v <= s["vsh_max"])
    if cand.sum() >= MIN_BIN_SAMPLES:
        x = np.log10(phi[cand])
        y = np.log10(rt[cand])
        idx = np.flatnonzero(cand)
        n_bins = max(int(s["n_bins"]), 1)
        edges = np.linspace(x.min(), x.max(), n_bins + 1)
        which = np.clip(np.digitize(x, edges[1:-1]), 0, n_bins - 1)
        for b in range(n_bins):
            sel = which == b
            if sel.sum() < MIN_BIN_SAMPLES:
                continue
            cut = np.quantile(y[sel], s["wet_quantile"])
            mask[idx[sel & (y <= cut)]] = True
    for kind, phi_lo, phi_hi, rt_lo, rt_hi in (manual or []):
        with np.errstate(invalid="ignore"):
            box = (ok & (phi >= min(phi_lo, phi_hi)) & (phi <= max(phi_lo, phi_hi))
                   & (rt >= min(rt_lo, rt_hi)) & (rt <= max(rt_lo, rt_hi)))
        if kind == "add":
            mask |= box
        elif kind == "remove":
            mask &= ~box
        else:
            raise ValueError(f"unknown manual box kind {kind!r}")
    return mask


def _mad_scale(r):
    return max(1.4826 * float(np.median(np.abs(r - np.median(r)))), 1e-6)


def _huber_weights(r):
    s = _mad_scale(r)
    ar = np.abs(r)
    with np.errstate(divide="ignore", invalid="ignore"):
        w = np.where(ar > 0, np.minimum(1.0, HUBER_K * s / ar), 1.0)
    return w


def _irls_line(x, y):
    """Huber IRLS of ``y = c + b x``. Returns (c, b, w, r, iterations)."""
    X = np.column_stack([np.ones_like(x), x])
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    w = np.ones_like(x)
    it = 0
    for it in range(1, MAX_ITER + 1):
        r = y - X @ beta
        w = _huber_weights(r)
        sw = np.sqrt(w)
        new = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)[0]
        done = float(np.max(np.abs(new - beta))) < TOL
        beta = new
        if done:
            break
    r = y - X @ beta
    return beta[0], beta[1], w, r, it


def _irls_location(z):
    """Huber location of ``z``. Returns (c, w, r, iterations)."""
    c = float(np.mean(z))
    w = np.ones_like(z)
    it = 0
    for it in range(1, MAX_ITER + 1):
        r = z - c
        w = _huber_weights(r)
        new = float((w * z).sum() / w.sum())
        done = abs(new - c) < TOL
        c = new
        if done:
            break
    return c, w, z - c, it


@_refs("pickett")
def fit_pickett(phi, rt, wet_mask, *, a: float, m_current: float, fit_mode: str = "m_and_rw",
                min_points: int = 10, min_decades: float = MIN_DECADES) -> PickettFit:
    """Huber IRLS fit of the wet line over the wet points.

    ``m_and_rw`` fits slope (``m = -slope``) and intercept (``a_rw = 10**c``); ``rw_only``
    fixes ``m`` at ``m_current`` and fits the intercept as the Huber location of
    ``y + m x`` (and skips the porosity-range test). ``rw = a_rw / a`` (``a`` is the scoped
    value, never fitted). Status: ``no_data``, ``too_few_points``, ``narrow_porosity_range``,
    ``m_outside_range``, ``rw_outside_range``, ``ok``; the fit values are filled when a fit
    was computed (so the out-of-range ones can be shown).
    """
    phi, rt, ok = _valid(phi, rt)
    sel = ok & np.asarray(wet_mask, dtype=bool).reshape(-1)
    n = int(sel.sum())
    if n == 0:
        return PickettFit("no_data")
    x = np.log10(phi[sel])
    y = np.log10(rt[sel])
    rng = (float(phi[sel].min()), float(phi[sel].max()))
    if n < min_points:
        return PickettFit("too_few_points", n_points=n, phi_range=rng)
    rw_only = fit_mode == "rw_only"
    if not rw_only and float(x.max() - x.min()) < min_decades:
        return PickettFit("narrow_porosity_range", n_points=n, phi_range=rng)

    if rw_only:
        m = float(m_current)
        c, w, r, it = _irls_location(y + m * x)
        dof = max(n - 1, 1)
        s2 = float((w * r ** 2).sum() / dof)
        se_m = float("nan")
        se_c = float(np.sqrt(s2 / w.sum()))
        yw = float((w * y).sum() / w.sum())
    else:
        c, b, w, r, it = _irls_line(x, y)
        m = -float(b)
        X = np.column_stack([np.ones_like(x), x])
        s2 = float((w * r ** 2).sum() / max(n - 2, 1))
        cov = s2 * np.linalg.inv(X.T @ (w[:, None] * X))
        se_c = float(np.sqrt(cov[0, 0]))
        se_m = float(np.sqrt(cov[1, 1]))
        yw = float((w * y).sum() / w.sum())
    tot = float((w * (y - yw) ** 2).sum())
    r2 = 1.0 - float((w * r ** 2).sum()) / tot if tot > 0 else float("nan")
    a_rw = float(10.0 ** c)
    rw = a_rw / float(a)
    status = "ok"
    if not rw_only and not (M_RANGE[0] <= m <= M_RANGE[1]):
        status = "m_outside_range"
    elif not (RW_RANGE[0] <= rw <= RW_RANGE[1]):
        status = "rw_outside_range"
    return PickettFit(status, m=m, a_rw=a_rw, rw=rw, se_m=se_m, se_c=se_c, n_points=n,
                      r2=r2, iterations=it, phi_range=rng)


@_refs("pickett")
def iso_sw_line(phi, a, rw, m, n, sw) -> np.ndarray:
    """Rt (ohm.m) of the iso-Sw line: ``a Rw / (PHI^m Sw^n)``."""
    phi = np.asarray(phi, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return a * rw / (np.power(phi, m) * np.power(float(sw), n))


@_refs("pickett")
def normalise_rt_for_temperature(rt, factor) -> np.ndarray:
    """Plot ordinate at the Rw reference temperature: ``RT / factor`` (NaN for factor <= 0)."""
    rt = np.asarray(rt, dtype=float)
    f = np.asarray(factor, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(f > 0, rt / f, np.nan)
