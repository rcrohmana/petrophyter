"""Bulk volume water, the water-free flag and the per-zone movable-water rows."""

from typing import Any, Dict, List, Optional

import numpy as np

from modules.lrlc import SHIPPED_METHODS
from modules.lrlc.screening import zone_groups


def _refs(method):
    def deco(fn):
        fn.refs = tuple(SHIPPED_METHODS[method])
        return fn
    return deco


@_refs("bvw")
def bvw(phie, sw) -> np.ndarray:
    """Bulk volume water ``PHIE * SW`` (v/v); NaN when either input is NaN."""
    return np.asarray(phie, dtype=float) * np.asarray(sw, dtype=float)


@_refs("buckles")
def water_free_flag(net_res_flag, sw, swirr, tol):
    """``(flag, n_missing_swirr)``.

    ``flag`` is int 0/1: 1 iff ``NET_RES_FLAG == 1``, ``sw`` and ``swirr`` finite and
    ``sw <= swirr + tol``. ``n_missing_swirr`` counts net-reservoir samples without a
    finite Swirr (those are not evaluated).
    """
    res = np.asarray(net_res_flag).reshape(-1) == 1
    sw = np.asarray(sw, dtype=float).reshape(-1)
    swirr = np.asarray(swirr, dtype=float).reshape(-1)
    tol = np.asarray(tol, dtype=float)
    with np.errstate(invalid="ignore"):
        flag = res & np.isfinite(sw) & np.isfinite(swirr) & (sw <= swirr + tol)
    return flag.astype(int), int((res & ~np.isfinite(swirr)).sum())


@_refs("buckles")
def movable_zone_rows(labels, net_res_flag, water_free, bvw_values, dz, sw=None,
                      swirr=None) -> List[Dict[str, Any]]:
    """Per-zone rows: ``zone, n, water_free_ft, net_res_ft, pct, avg_bvw,
    avg_movable_sw``.

    ``n`` counts net-reservoir samples; ``avg_bvw`` and ``avg_movable_sw`` (``SW - SWIRR``,
    NaN without both) are over them, thickness weighted; ``pct`` is the water-free share of
    the net reservoir thickness in percent (NaN without net reservoir).
    """
    res = np.asarray(net_res_flag).reshape(-1) == 1
    size = len(res)
    wf = np.asarray(water_free).reshape(-1) == 1
    w = np.nan_to_num(np.asarray(dz, dtype=float).reshape(-1)
                      if np.ndim(dz) else np.full(size, float(dz)), nan=0.0)
    bv = np.asarray(bvw_values, dtype=float).reshape(-1)
    if sw is not None and swirr is not None:
        mov = np.asarray(sw, dtype=float).reshape(-1) - np.asarray(swirr, dtype=float).reshape(-1)
    else:
        mov = np.full(size, np.nan)

    def wmean(values, mask):
        ok = mask & np.isfinite(values)
        if not ok.any():
            return float("nan")
        if w[ok].sum() <= 0:
            return float(values[ok].mean())
        return float((values[ok] * w[ok]).sum() / w[ok].sum())

    rows = []
    for zone, mask in zone_groups(labels, size):
        sel = mask & res
        res_ft = float(w[sel].sum())
        wf_ft = float(w[sel & wf].sum())
        rows.append({
            "zone": zone,
            "n": int(sel.sum()),
            "water_free_ft": wf_ft,
            "net_res_ft": res_ft,
            "pct": (100.0 * wf_ft / res_ft) if res_ft > 0 else float("nan"),
            "avg_bvw": wmean(bv, sel),
            "avg_movable_sw": wmean(mov, sel),
        })
    return rows
