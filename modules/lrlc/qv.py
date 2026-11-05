"""Qv (cation exchange per pore volume) estimated from Vsh and a shale CEC (pure: numpy only, no Qt, no pipeline import)."""

from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np


@dataclass
class CecFit:
    cec_shale: float
    n: int
    r2: float
    ok: bool
    reason: str = ""


def qv_from_cec(cec_rock, rho_g, phit):
    """Qv [meq/mL] = CEC/100 * rho_g * (1 - phit) / phit; CEC in meq/100 g of dry rock."""
    cec_rock = np.asarray(cec_rock, dtype=float)
    rho_g = np.asarray(rho_g, dtype=float)
    phit = np.asarray(phit, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        return (cec_rock / 100.0) * rho_g * (1.0 - phit) / phit


def estimate_qv(vsh, phit, cec_shale, rho_g, phi_min, qv_max) -> Tuple[np.ndarray, Dict[str, int]]:
    """Per-sample Qv from ``Vsh * cec_shale``; out-of-range samples are NaN and counted."""
    vsh = np.asarray(vsh, dtype=float)
    phit = np.broadcast_to(np.asarray(phit, dtype=float), vsh.shape)
    rho_g = np.broadcast_to(np.asarray(rho_g, dtype=float), vsh.shape)
    cec = vsh * float(cec_shale)
    with np.errstate(invalid="ignore"):
        ok_in = np.isfinite(vsh) & np.isfinite(phit) & np.isfinite(rho_g) & (vsh >= 0)
        low = ok_in & (phit < phi_min)
        calc = ok_in & ~low & (phit > 0)
    qv = np.full(vsh.shape, np.nan)
    qv[calc] = qv_from_cec(cec[calc], rho_g[calc], phit[calc])
    with np.errstate(invalid="ignore"):
        high = calc & (qv > qv_max)
    qv[high] = np.nan
    counts = {
        "no_input": int((~ok_in).sum()),
        "out_of_range": int(low.sum() + high.sum()),
    }
    return qv, counts


def qv_for_model(qv_est, ws_qv) -> Tuple[np.ndarray, int]:
    """Array for Waxman-Smits: the estimate where finite, else the scalar; count of fallbacks."""
    qv_est = np.asarray(qv_est, dtype=float)
    fin = np.isfinite(qv_est)
    return np.where(fin, qv_est, float(ws_qv)), int((~fin).sum())


def calibrate_cec_shale(cec, vsh, min_vsh=0.05, min_pairs=5) -> CecFit:
    """``cec_shale = sum(CEC*Vsh) / sum(Vsh^2)`` over pairs with ``Vsh >= min_vsh``."""
    cec = np.asarray(cec, dtype=float)
    vsh = np.asarray(vsh, dtype=float)
    with np.errstate(invalid="ignore"):
        use = np.isfinite(cec) & np.isfinite(vsh) & (vsh >= min_vsh) & (cec >= 0)
    c, v = cec[use], vsh[use]
    n = int(use.sum())
    if n < min_pairs:
        return CecFit(float("nan"), n, float("nan"), False,
                      f"{n} usable core pairs; need {min_pairs}")
    slope = float(np.sum(c * v) / np.sum(v * v))
    ss_res = float(np.sum((c - slope * v) ** 2))
    ss_tot = float(np.sum((c - c.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return CecFit(slope, n, r2, True, "")


def pair_core_cec(core_depth, core_cec, log_depth, log_vsh, tol_ft):
    """Each core CEC sample paired with the nearest log sample within ``tol_ft`` (inclusive).

    Returns ``(cec, vsh)`` arrays of the matched pairs.
    """
    core_depth = np.asarray(core_depth, dtype=float)
    core_cec = np.asarray(core_cec, dtype=float)
    log_depth = np.asarray(log_depth, dtype=float)
    log_vsh = np.asarray(log_vsh, dtype=float)
    good = np.isfinite(log_depth)
    log_depth, log_vsh = log_depth[good], log_vsh[good]
    if log_depth.size == 0:
        return np.array([]), np.array([])
    cec_out, vsh_out = [], []
    for d, c in zip(core_depth, core_cec):
        if not (np.isfinite(d) and np.isfinite(c)):
            continue
        idx = int(np.argmin(np.abs(log_depth - d)))
        if abs(log_depth[idx] - d) <= tol_ft:
            cec_out.append(c)
            vsh_out.append(log_vsh[idx])
    return np.array(cec_out), np.array(vsh_out)
