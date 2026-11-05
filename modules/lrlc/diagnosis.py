"""Low-resistivity-pay diagnosis per zone: evidence, decision tree and remedy (pure: numpy/pandas only, no Qt, no pipeline import)."""

from typing import Any, Dict, List, Optional

import numpy as np

PROBABLE_SCORE = 0.67
POSSIBLE_SCORE = 0.34
CLASS_SHARE = 0.5
WATER_FREE_SHARE = 0.5

# Tie order of the primary cause.
CAUSE_ORDER = ("laminated", "microporosity", "saline", "conductive_mineral", "clay_conductivity")

CAUSE_LABELS = {
    "laminated": "Thin beds / laminations",
    "microporosity": "Microporosity / fine grain",
    "saline": "Saline water / low contrast",
    "conductive_mineral": "Conductive minerals (pyrite)",
    "clay_conductivity": "Clay conductivity / high CEC",
}

_NOTE_NAMES = {
    "laminated": "laminated sand",
    "microporosity": "microporosity",
    "saline": "saline formation water",
    "conductive_mineral": "conductive minerals",
    "clay_conductivity": "clay conductivity",
}

_REMEDIES = {
    "laminated": {
        "rt_steps": ["laminated"], "qv_source": None, "sw_basis": "sand",
        "sw_models": ["Waxman-Smits", "Archie"],
        "text": ("Add the laminated-sand Rt step and set the Vlam endpoints; consider the sand basis. "
                 "Use Waxman-Smits or Archie after the step; with the bulk basis avoid Indonesian "
                 "and Simandoux."),
    },
    "microporosity": {
        "rt_steps": [], "qv_source": None, "sw_basis": None, "sw_models": [],
        "text": ("Not an Rt problem: use the Buckles / movable-water check and the saturation-height "
                 "validation, and read the water-free flag. Keep the Sw model."),
    },
    "saline": {
        "rt_steps": [], "qv_source": None, "sw_basis": None, "sw_models": ["Archie", "Simandoux"],
        "text": ("No Rt step: check Rw (auto Rwa, Pickett plot) and the Arps temperature correction, "
                 "then use Archie or Simandoux with the corrected Rw."),
    },
    "conductive_mineral": {
        "rt_steps": ["pyrite"], "qv_source": None, "sw_basis": None, "sw_models": [],
        "text": "Add the pyrite step and calibrate the connected fraction and the pyrite resistivity.",
    },
    "clay_conductivity": {
        "rt_steps": [], "qv_source": "estimate", "sw_basis": None,
        "sw_models": ["Waxman-Smits", "Dual-Water"],
        "text": "Estimate Qv from Vsh and the shale CEC, and use Waxman-Smits or Dual-Water.",
    },
}


def _remedy(key: str) -> Dict[str, Any]:
    r = _REMEDIES[key]
    return {"rt_steps": list(r["rt_steps"]), "qv_source": r["qv_source"], "sw_basis": r["sw_basis"],
            "sw_models": list(r["sw_models"]), "text": r["text"]}


def _col(frame, name):
    if frame is None or name not in frame.columns:
        return None
    return np.asarray(frame[name], dtype=float)


def _wmedian(values, weights) -> Optional[float]:
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    ok = np.isfinite(v)
    v, w = v[ok], w[ok]
    if v.size == 0:
        return None
    w = np.where(np.isfinite(w) & (w > 0), w, 0.0)
    if w.sum() <= 0:
        w = np.ones_like(v)
    order = np.argsort(v, kind="mergesort")
    v, w = v[order], w[order]
    cum = np.cumsum(w)
    return float(v[int(np.searchsorted(cum, 0.5 * cum[-1]))])


def _wmean(values, weights) -> Optional[float]:
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    ok = np.isfinite(v)
    v, w = v[ok], w[ok]
    if v.size == 0:
        return None
    w = np.where(np.isfinite(w) & (w > 0), w, 0.0)
    if w.sum() <= 0:
        return float(v.mean())
    return float(np.sum(v * w) / w.sum())


def zone_evidence(frame, dz, *, sw_cutoff, screen_rt_max, a, m, rw_eff, ts_stats, qv_value,
                  min_n) -> Dict[str, Any]:
    """Every value of the decision tree for one zone (None = not evaluable).

    ``frame`` holds the zone's rows; optional columns are NET_RES_FLAG, SW, SW_ARCHIE, BVW,
    WATER_FREE_FLAG, RT, PHIT, VSH, VPYR, PEF, QV_EST. ``ts_stats`` is None or a dict with
    ``lam_share``, ``mean_vlam`` and ``class13_share``. Statistics use the net reservoir samples
    (``NET_RES_FLAG == 1``) weighted by the depth increments ``dz``.
    """
    n_all = 0 if frame is None else len(frame)
    flag = _col(frame, "NET_RES_FLAG")
    dz = np.broadcast_to(np.asarray(dz, dtype=float), (n_all,)) if n_all else np.array([])
    sel = np.zeros(n_all, dtype=bool) if flag is None else (flag == 1)
    w = dz[sel]
    n_res = int(sel.sum())
    ev: Dict[str, Any] = {
        "zone": None, "n_res": n_res,
        "thickness_ft": float(np.nansum(w)) if n_res else 0.0,
        "min_n": min_n, "sw_cutoff": sw_cutoff, "screen_rt_max": screen_rt_max,
        "ts_stats": dict(ts_stats) if ts_stats else None,
        "lam_share": None, "mean_vlam": None, "class13_share": None,
        "sw_median": None, "water_free_share": None, "bvw_cv": None,
        "rw_median": None, "rt_ro_median": None, "rt_median": None,
        "vpyr_median": None, "pef_median": None,
        "qv": None, "vsh_mean": None, "dsw_median": None,
    }
    if ts_stats:
        for key in ("lam_share", "mean_vlam", "class13_share"):
            v = ts_stats.get(key)
            ev[key] = None if v is None or not np.isfinite(v) else float(v)
    if n_res == 0:
        ev["qv"] = _finite_or_none(qv_value)
        return ev

    def pick(name):
        c = _col(frame, name)
        return None if c is None else c[sel]

    sw = pick("SW")
    ev["sw_median"] = None if sw is None else _wmedian(sw, w)
    wf = pick("WATER_FREE_FLAG")
    if wf is not None:
        ok = np.isfinite(wf)
        if ok.any():
            ev["water_free_share"] = float(_wmean((wf[ok] == 1).astype(float), w[ok]))
    bvw = pick("BVW")
    if bvw is not None:
        b = bvw[np.isfinite(bvw)]
        if b.size >= 2 and b.mean() > 0:
            ev["bvw_cv"] = float(b.std() / b.mean())
    rt = pick("RT")
    phit = pick("PHIT")
    if rt is not None:
        ev["rt_median"] = _wmedian(rt, w)
    if rw_eff is not None:
        rw_all = np.broadcast_to(np.asarray(rw_eff, dtype=float), (n_all,))
        rw = rw_all[sel]
        ev["rw_median"] = _wmedian(rw, w)
        if rt is not None and phit is not None:
            with np.errstate(invalid="ignore", divide="ignore"):
                ro = a * rw / np.power(phit, m)
                ratio = np.where((phit > 0) & np.isfinite(ro) & (ro > 0), rt / ro, np.nan)
            ev["rt_ro_median"] = _wmedian(ratio, w)
    vp = pick("VPYR")
    ev["vpyr_median"] = None if vp is None else _wmedian(vp, w)
    pf = pick("PEF")
    ev["pef_median"] = None if pf is None else _wmedian(pf, w)
    qe = pick("QV_EST")
    q = None if qe is None else _wmedian(qe, w)
    ev["qv"] = q if q is not None else _finite_or_none(qv_value)
    vs = pick("VSH")
    ev["vsh_mean"] = None if vs is None else _wmean(vs, w)
    swa = pick("SW_ARCHIE")
    if swa is not None and sw is not None:
        ev["dsw_median"] = _wmedian(swa - sw, w)
    return ev


def _finite_or_none(v):
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def _crit(cid, value, op, threshold) -> Dict[str, Any]:
    value = _finite_or_none(value)
    threshold = _finite_or_none(threshold)
    if value is None or threshold is None:
        return {"id": cid, "value": value, "op": op, "threshold": threshold, "met": None}
    met = value >= threshold if op == ">=" else value <= threshold
    return {"id": cid, "value": value, "op": op, "threshold": threshold, "met": bool(met)}


def _criteria(ev, th, gs) -> Dict[str, List[Dict[str, Any]]]:
    return {
        "laminated": [
            _crit("lam_share", ev.get("lam_share"), ">=", gs.get("vlam_share")),
            _crit("mean_vlam", ev.get("mean_vlam"), ">=", gs.get("min_vlam")),
            _crit("class13_share", ev.get("class13_share"), ">=", CLASS_SHARE),
        ],
        "microporosity": [
            _crit("sw_median", ev.get("sw_median"), ">=", ev.get("sw_cutoff")),
            _crit("water_free_share", ev.get("water_free_share"), ">=", WATER_FREE_SHARE),
            _crit("bvw_cv", ev.get("bvw_cv"), "<=", th.get("bvw_cv_max")),
        ],
        "saline": [
            _crit("rw_median", ev.get("rw_median"), "<=", th.get("rw_low")),
            _crit("rt_ro_median", ev.get("rt_ro_median"), "<=", th.get("contrast_low")),
            _crit("rt_median", ev.get("rt_median"), "<=", ev.get("screen_rt_max")),
        ],
        "conductive_mineral": [
            _crit("vpyr_median", ev.get("vpyr_median"), ">=", th.get("vpyr_flag")),
            _crit("pef_median", ev.get("pef_median"), ">=", th.get("pef_flag")),
        ],
        "clay_conductivity": [
            _crit("qv", ev.get("qv"), ">=", th.get("qv_high")),
            _crit("vsh_mean", ev.get("vsh_mean"), ">=", th.get("vsh_clay")),
            _crit("dsw_median", ev.get("dsw_median"), ">=", th.get("dsw_clay")),
        ],
    }


def diagnose_zone(evidence, thresholds, guard_settings) -> Dict[str, Any]:
    """Decision tree per zone; see the module constants for the fixed shares."""
    th = thresholds or {}
    gs = guard_settings or {}
    n_res = int(evidence.get("n_res") or 0)
    min_n = int(evidence.get("min_n") if evidence.get("min_n") is not None else th.get("min_n", 10))
    lam = evidence.get("lam_share")
    out: Dict[str, Any] = {
        "zone": evidence.get("zone"), "status": "ok", "n_res": n_res,
        "thickness_ft": evidence.get("thickness_ft", 0.0),
        "primary": None, "causes": [],
        "ts": evidence.get("ts_stats"),
        "guard": {"laminated": (None if lam is None or gs.get("vlam_share") is None
                                else bool(lam >= gs["vlam_share"])),
                  "lam_share": lam},
    }
    if n_res < min_n:
        out["status"] = "insufficient"
        return out
    crit = _criteria(evidence, th, gs)
    causes = []
    for key in CAUSE_ORDER:
        items = crit[key]
        evaluable = [c for c in items if c["met"] is not None]
        n_eval = len(evaluable)
        if n_eval == 0:
            continue
        met = sum(1 for c in evaluable if c["met"])
        score = met / n_eval
        shown = round(score, 2)     # 2 of 3 counts as 0.67
        probable = shown >= PROBABLE_SCORE and (n_eval >= 2 or key == "conductive_mineral")
        if probable:
            level = "probable"
        elif shown >= POSSIBLE_SCORE:
            level = "possible"
        else:
            continue
        causes.append({"key": key, "label": CAUSE_LABELS[key], "level": level, "score": score,
                       "n_eval": n_eval, "criteria": items, "remedy": _remedy(key)})
    probables = [c for c in causes if c["level"] == "probable"]
    if probables:
        best = max(c["score"] for c in probables)
        out["primary"] = next(c["key"] for c in probables if c["score"] == best)
    out["causes"] = causes
    return out


def lrlc_note(zone_result) -> Optional[str]:
    """One-line zone note, only when a primary cause exists."""
    key = (zone_result or {}).get("primary")
    if not key:
        return None
    detail = ""
    if key == "laminated":
        lam = (zone_result.get("guard") or {}).get("lam_share")
        if lam is not None:
            detail = f" (Vlam share {lam:.2f})"
    return f"LRLC: probable {_NOTE_NAMES[key]}{detail}; see Remediation."
