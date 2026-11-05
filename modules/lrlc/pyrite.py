"""Pyrite volume (RHOB/PEF) and parallel-conductance correction, chain step ``pyrite`` (pure: numpy/pandas only, no Qt, no pipeline import)."""

from dataclasses import dataclass, field
from typing import Dict, Tuple

import numpy as np

from modules.lrlc import chain
from modules.lrlc.chain import StepResult, StepSpec


@dataclass
class PyriteVolumes:
    vpyr: np.ndarray
    phi: np.ndarray
    vma: np.ndarray
    counts: Dict[str, int] = field(default_factory=dict)
    cond: float = float("nan")
    ill_conditioned: bool = False


def _endpoint_matrix(rho_f, u_fluid, rho_ma, pef_ma, rho_py, pef_py):
    return np.array([
        [1.0, 1.0, 1.0],
        [rho_f, rho_ma, rho_py],
        [u_fluid, pef_ma * rho_ma, pef_py * rho_py],
    ], dtype=float)


def solve_volumes(rhob, pef, vsh, *, rho_f, u_fluid, rho_ma, pef_ma, rho_py, pef_py,
                  rho_sh, pef_sh, pef_max, neg_tol, vpyr_max, cond_max=1e4) -> PyriteVolumes:
    """Pore, matrix and pyrite volumes from RHOB and the volumetric PEF (U = PEF * RHOB).

    One zone's scalar endpoints. Unknowns (phi, Vma, Vpy) with Vsh known. An endpoint matrix
    with condition number above ``cond_max`` returns NaN everywhere.
    """
    rhob = np.atleast_1d(np.asarray(rhob, dtype=float))
    n = len(rhob)
    pef = np.broadcast_to(np.atleast_1d(np.asarray(pef, dtype=float)), (n,))
    vsh = np.broadcast_to(np.atleast_1d(np.asarray(vsh, dtype=float)), (n,))
    nan = np.full(n, np.nan)
    counts = {"no_input": 0, "negative": 0, "rounded_zero": 0, "implausible": 0}
    mat = _endpoint_matrix(rho_f, u_fluid, rho_ma, pef_ma, rho_py, pef_py)
    with np.errstate(all="ignore"):
        cond = float(np.linalg.cond(mat))
    if not np.isfinite(cond) or cond > cond_max:
        return PyriteVolumes(nan.copy(), nan.copy(), nan.copy(), counts, cond, True)
    inv = np.linalg.inv(mat)
    with np.errstate(invalid="ignore"):
        ok = (np.isfinite(rhob) & np.isfinite(pef) & np.isfinite(vsh)
              & (pef > 0) & (pef <= pef_max))
    counts["no_input"] = int((~ok).sum())
    u_sh = pef_sh * rho_sh
    b = np.vstack([1.0 - vsh, rhob - vsh * rho_sh, pef * rhob - vsh * u_sh])
    b = np.where(ok, b, 0.0)
    x = inv @ b
    phi, vma, vpy = x[0].copy(), x[1].copy(), x[2].copy()
    phi[~ok] = np.nan
    vma[~ok] = np.nan
    vpy[~ok] = np.nan
    with np.errstate(invalid="ignore"):
        neg = ok & (vpy < -neg_tol)
        rz = ok & (vpy < 0) & ~neg
        imp = ok & (vpy > vpyr_max)
    vpy[neg | imp] = np.nan
    vpy[rz] = 0.0
    counts["negative"] = int(neg.sum())
    counts["rounded_zero"] = int(rz.sum())
    counts["implausible"] = int(imp.sum())
    return PyriteVolumes(vpy, phi, vma, counts, cond, False)


def pyrite_rt(rt_in, vpyr, f, rpy, s_warn, s_invalid) -> Tuple[np.ndarray, np.ndarray, Dict[str, int]]:
    """``RT_PYR = 1 / (1/Rt - f*Vpyr/Rpy)``; ``t == 0`` returns ``rt_in`` unchanged."""
    rt_in = np.asarray(rt_in, dtype=float)
    n = len(rt_in)
    vpyr = np.broadcast_to(np.asarray(vpyr, dtype=float), (n,))
    counts = {"identity": 0, "invalid": 0, "sensitive": 0, "no_input": 0}
    out = np.full(n, np.nan)
    valid = np.zeros(n, dtype=bool)
    with np.errstate(invalid="ignore"):
        rt_ok = np.isfinite(rt_in) & (rt_in > 0)
    f = 0.0 if f is None else float(f)
    rpy = float("nan") if rpy is None else float(rpy)
    if f <= 0:
        out[rt_ok] = rt_in[rt_ok]
        valid[rt_ok] = True
        counts["identity"] = int(rt_ok.sum())
        counts["invalid"] = int((np.isfinite(rt_in) & ~rt_ok).sum())
        return out, valid, counts
    if not (np.isfinite(rpy) and rpy > 0):
        counts["invalid"] = int(np.isfinite(rt_in).sum())
        return out, valid, counts
    no_in = rt_ok & ~np.isfinite(vpyr)
    work = rt_ok & np.isfinite(vpyr)
    with np.errstate(invalid="ignore", divide="ignore"):
        t = f * vpyr / rpy
        s = t * rt_in
        ident = work & (t == 0)
        calc = work & (t != 0)
        bad = calc & (s >= s_invalid)
        good = calc & ~bad
        out[ident] = rt_in[ident]
        out[good] = rt_in[good] / (1.0 - s[good])
    valid[ident | good] = True
    counts["identity"] = int(ident.sum())
    counts["invalid"] = int(bad.sum() + (np.isfinite(rt_in) & ~rt_ok).sum())
    counts["sensitive"] = int((good & (s >= s_warn)).sum())
    counts["no_input"] = int(no_in.sum())
    return out, valid, counts


def pyrite_step(rt, ctx, prm) -> StepResult:
    n = len(rt)
    if prm.get("pyr_method") == "manual":
        v = prm.get("pyr_vpyr")
        vpyr = np.full(n, np.nan if v is None else float(v))
    else:
        got = ctx.derived.get("VPYR")
        vpyr = np.full(n, np.nan) if got is None else np.asarray(got, dtype=float)
    s_warn = 0.8 if prm.get("s_warn") is None else prm["s_warn"]
    s_invalid = 0.95 if prm.get("s_invalid") is None else prm["s_invalid"]
    out, valid, counts = pyrite_rt(rt, vpyr, prm.get("pyr_f"), prm.get("pyr_rpy"), s_warn, s_invalid)
    return StepResult(rt_out=out, valid_mask=valid, counts=counts, refs=("clavier1976",))


STEP = StepSpec(
    name="pyrite", order=chain.CHAIN_ORDER.index("pyrite"), column="RT_PYR", fn=pyrite_step,
    label="Pyrite",
    description="Removes the parallel conductance of connected pyrite from the measured resistivity.",
    refs=("clavier1976",),
    params=("pyr_method", "pyr_vpyr", "pyr_f", "pyr_rpy", "s_warn", "s_invalid"),
    varied=(), kind="mineral",
)


def register_step() -> None:
    if STEP.name not in chain.STEPS:
        chain.register(STEP)
