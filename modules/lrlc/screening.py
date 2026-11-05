"""LRLC screening: samples that look like sand that conventional logs call wet.

Pure numerical code. Reads measured values; changes no model input.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np

from modules.lrlc import SHIPPED_METHODS

RS_SEPARATION_MIN = 1.0  # RT / RS at or above this reads as hydrocarbon (weak with saline mud)

CRITERIA = ("LOW_RT", "HC", "PHI", "VSH", "CONTRAST", "SW_HIGH")
CORE = ("LOW_RT", "PHI", "SW_HIGH")


def _refs(method):
    def deco(fn):
        fn.refs = tuple(SHIPPED_METHODS[method])
        return fn
    return deco


@dataclass
class ScreenResult:
    score: np.ndarray                 # int 0..6
    flag: np.ndarray                  # int 0/1
    met: Dict[str, np.ndarray]        # name -> bool array
    evaluable: Dict[str, np.ndarray]  # name -> bool array


def _arr(value, size):
    arr = np.asarray(value, dtype=float)
    if arr.ndim == 0:
        return np.full(size, float(arr))
    return arr.reshape(-1)


@_refs("screening")
def screen(rt, rs, gas_flag, phie, vsh, rsh_eff, sw, *, screen_rt_max, screen_contrast_max,
           screen_min_score, phi_cutoff, vsh_cutoff, sw_cutoff, use_gas_flag=True,
           use_rs=True) -> ScreenResult:
    """The six screening criteria, score and flag per sample.

    ``rt`` is the measured RT (never RT_SW); ``rs`` and ``gas_flag`` may be None (role not
    mapped / column absent). ``rsh_eff`` and the cutoffs are scalars or per-sample arrays.
    Score counts met criteria (an unevaluable one counts as not met); the flag needs the
    core criteria LOW_RT, PHI, SW_HIGH met and ``score >= min(screen_min_score, n_eval)``.
    Samples with RT NaN get score 0 and flag 0.
    """
    rt = np.asarray(rt, dtype=float).reshape(-1)
    size = len(rt)
    phie = _arr(phie, size)
    vsh = _arr(vsh, size)
    sw = _arr(sw, size)
    rsh = _arr(rsh_eff, size)
    rt_ok = np.isfinite(rt)

    met: Dict[str, np.ndarray] = {}
    ev: Dict[str, np.ndarray] = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        ev["LOW_RT"] = rt_ok.copy()
        met["LOW_RT"] = rt_ok & (rt < screen_rt_max)

        hc_gas = use_gas_flag and gas_flag is not None
        hc_rs = use_rs and rs is not None
        hc_ev = np.zeros(size, dtype=bool)
        hc_met = np.zeros(size, dtype=bool)
        if hc_gas:
            gas = _arr(gas_flag, size)
            hc_ev |= True
            hc_met |= np.where(np.isfinite(gas), gas, 0.0) == 1
        if hc_rs:
            rs_a = _arr(rs, size)
            rs_ok = rt_ok & np.isfinite(rs_a) & (rs_a > 0) & (rt > 0)
            hc_ev |= rs_ok
            hc_met |= rs_ok & (rt / rs_a >= RS_SEPARATION_MIN)
        ev["HC"], met["HC"] = hc_ev, hc_met

        ev["PHI"] = np.isfinite(phie)
        met["PHI"] = ev["PHI"] & (phie > phi_cutoff)
        ev["VSH"] = np.isfinite(vsh)
        met["VSH"] = ev["VSH"] & (vsh < vsh_cutoff)
        ev["CONTRAST"] = rt_ok & (rt > 0) & np.isfinite(rsh) & (rsh > 0)
        met["CONTRAST"] = ev["CONTRAST"] & (rt / rsh <= screen_contrast_max)
        ev["SW_HIGH"] = np.isfinite(sw)
        met["SW_HIGH"] = ev["SW_HIGH"] & (sw >= sw_cutoff)

    for name in CRITERIA:
        met[name] = np.asarray(met[name], dtype=bool) & rt_ok
        ev[name] = np.asarray(ev[name], dtype=bool)

    score = sum(met[name].astype(int) for name in CRITERIA)
    n_eval = sum(ev[name].astype(int) for name in CRITERIA)
    core = np.logical_and.reduce([met[name] for name in CORE])
    need = np.minimum(screen_min_score, n_eval)
    flag = (core & (score >= need) & rt_ok).astype(int)
    return ScreenResult(score=np.asarray(score, dtype=int), flag=flag, met=met, evaluable=ev)


@_refs("screening")
def criteria_counts(result: ScreenResult) -> Dict[str, Dict[str, int]]:
    """``{name: {"met": n, "evaluable": n}}`` over the whole well."""
    return {name: {"met": int(result.met[name].sum()),
                   "evaluable": int(result.evaluable[name].sum())} for name in CRITERIA}


@_refs("screening")
def unavailable_criteria(result: ScreenResult) -> List[str]:
    """Criteria that are unevaluable for every sample of the well, in criteria order."""
    return [name for name in CRITERIA if not result.evaluable[name].any()]


@_refs("screening")
def zone_groups(labels, size: int):
    """``[(zone, boolean mask)]`` in order of first appearance; ``[("WELL", all)]`` for none."""
    if labels is None:
        return [("WELL", np.ones(size, dtype=bool))]
    lab = np.asarray(labels, dtype=object).reshape(-1)
    seen: List[Any] = []
    for value in lab:
        if value not in seen:
            seen.append(value)
    return [(str(z), lab == z) for z in seen]


def _wmean(values, weights, mask):
    values = np.asarray(values, dtype=float)
    ok = mask & np.isfinite(values)
    if not ok.any():
        return float("nan")
    w = weights[ok]
    if w.sum() <= 0:
        return float(values[ok].mean())
    return float((values[ok] * w).sum() / w.sum())


@_refs("screening")
def zone_table(flag, net_pay_flag, net_res_flag, dz, phie, vsh, sw, rt, labels=None,
               rt_cut: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
    """One row per zone: ``zone, n, candidate_ft, candidate_not_pay_ft, pct_of_net_res,
    avg_phie, avg_vsh, avg_sw, avg_rt, rt_cut`` (+ ``net_res_ft``).

    Thickness (``dz``) weighted; the averages are over the candidate samples (NaN when
    none). ``pct_of_net_res`` is percent (0 to 100) of the zone's net reservoir thickness,
    NaN without net reservoir. ``rt_cut`` maps zone -> scalar cutoff (NaN when absent).
    """
    flag = np.asarray(flag).reshape(-1)
    size = len(flag)
    w = np.nan_to_num(_arr(dz, size), nan=0.0)
    pay = np.asarray(net_pay_flag).reshape(-1) == 1
    res = np.asarray(net_res_flag).reshape(-1) == 1
    cand = flag == 1
    rows = []
    for zone, mask in zone_groups(labels, size):
        cand_ft = float(w[mask & cand].sum())
        res_ft = float(w[mask & res].sum())
        sel = mask & cand
        rows.append({
            "zone": zone,
            "n": int(mask.sum()),
            "candidate_ft": cand_ft,
            "candidate_not_pay_ft": float(w[sel & ~pay].sum()),
            "net_res_ft": res_ft,
            "pct_of_net_res": (100.0 * cand_ft / res_ft) if res_ft > 0 else float("nan"),
            "avg_phie": _wmean(phie, w, sel),
            "avg_vsh": _wmean(vsh, w, sel),
            "avg_sw": _wmean(sw, w, sel),
            "avg_rt": _wmean(rt, w, sel),
            "rt_cut": float((rt_cut or {}).get(zone, float("nan"))),
        })
    return rows
