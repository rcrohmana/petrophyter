"""Elastic-attribute screening flag (pure: numpy/pandas only, no Qt, no pipeline import).

    Vp = 304800 / DT      Vs = 304800 / DTS      AI = RHOB * Vp      VPVS = DTS / DT

AI and Vp/Vs are normalised to the adjacent shale and to a robust wet trend against porosity; a net
reservoir sample whose attributes fall below that trend by more than the thresholds is flagged.
Generic screening statistic with design defaults; not a reproduction of any patented procedure.

This module never computes or changes ``LRLC_FLAG``. The caller adds ``flag`` to ``LRLC_SCORE``.

Interface of :func:`elastic_screen`:

* ``results``: DataFrame with ``PHIE``, ``SW``, ``NET_RES_FLAG``, ``LRLC_FLAG`` (and ``VSH``), one row per sample.
* ``curves``: dict of arrays in the same row order: ``DEPTH`` (ft), ``DT``, ``DTS`` (us/ft), ``RHOB`` (g/cc);
  optional ``DZ`` (thickness per sample, ft), ``VSH`` / ``PHIE`` / ``SW`` (override the columns of
  ``results``) and ``DT_NAME`` / ``DTS_NAME`` / ``RHOB_NAME`` (curve names for the summary).
* ``params_by_zone``: ``{zone key: resolved settings}`` with the prefixed ``el_*`` keys; missing keys take the
  defaults. Well-only keys are read from the first zone's settings.
* ``zone_keys``: per-sample zone key (same keys as ``params_by_zone``).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from modules.param_scopes import UNZONED

WELL_ZONE = "WELL"

DEFAULTS = {
    "el_baseline_mode": "rolling", "el_shale_window_ft": 100.0, "el_shale_min_n": 10,
    "el_vsh_shale": 0.7, "el_shale_interval": None, "el_sw_wet": 0.9, "el_wet_interval": None,
    "el_trend_scope": "well", "el_min_wet_n": 30, "el_min_phi_span": 0.04,
    "el_ai_drop": 0.05, "el_vpvs_drop": 0.03, "el_mode": "both",
}

DT_RANGE = (40.0, 200.0)
DTS_RANGE = (60.0, 500.0)
RHOB_RANGE = (1.5, 3.2)
RATIO_RANGE = (1.15, 4.0)
INVALID_WARN_SHARE = 0.05
SIGMA_REJECT = 3.0
ROBUST_PASSES = 2
FT_PER_M = 0.3048
VP_FACTOR = 1.0e6 * FT_PER_M            # 304800: Vp [m/s] = 304800 / DT [us/ft]


@dataclass
class ElasticOutput:
    """``ai``, ``vpvs`` (NaN where invalid) and ``flag`` (int 0/1) per sample; ``ran`` False when skipped."""
    ai: np.ndarray
    vpvs: np.ndarray
    flag: np.ndarray
    summary: dict
    issues: List[Tuple[str, str, Optional[str], Optional[str]]] = field(default_factory=list)
    ran: bool = True


def acoustic_impedance(dt, rhob):
    """AI = RHOB * 304800 / DT [(g/cc)(m/s)]."""
    return np.asarray(rhob, dtype=float) * VP_FACTOR / np.asarray(dt, dtype=float)


def vp_vs_ratio(dt, dts):
    """Vp/Vs = DTS / DT."""
    return np.asarray(dts, dtype=float) / np.asarray(dt, dtype=float)


def validity_mask(dt, dts, rhob) -> np.ndarray:
    """True where DT, DTS, RHOB and DTS/DT are finite and inside the validity ranges (4.4)."""
    dt, dts, rhob = (np.asarray(a, dtype=float) for a in (dt, dts, rhob))
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = dts / dt
        return ((dt >= DT_RANGE[0]) & (dt <= DT_RANGE[1]) & (dts >= DTS_RANGE[0])
                & (dts <= DTS_RANGE[1]) & (rhob >= RHOB_RANGE[0]) & (rhob <= RHOB_RANGE[1])
                & (ratio >= RATIO_RANGE[0]) & (ratio <= RATIO_RANGE[1]))


def looks_like_us_per_m(dt, dts) -> bool:
    """Median DT above 200 or median DTS above 500 (the curves are probably us/m)."""
    for arr, limit in ((dt, DT_RANGE[1]), (dts, DTS_RANGE[1])):
        a = np.asarray(arr, dtype=float)
        a = a[np.isfinite(a) & (a > 0)]
        if a.size and float(np.median(a)) > limit:
            return True
    return False


def _label(key) -> str:
    return WELL_ZONE if key == UNZONED else str(key)


def _settings(params_by_zone: dict, key) -> dict:
    out = dict(DEFAULTS)
    out.update({k: v for k, v in ((params_by_zone or {}).get(key) or {}).items() if k in DEFAULTS})
    return out


def _interval(value) -> Optional[Tuple[float, float]]:
    try:
        lo, hi = float(value[0]), float(value[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    return (min(lo, hi), max(lo, hi))


def _median(values) -> float:
    return float(np.median(values)) if len(values) else float("nan")


def _rolling_baseline(depth, values, shale, window_ft, min_n) -> np.ndarray:
    """Median of ``values`` over shale samples within +/- window/2, interpolated in depth (NaN: too few shales)."""
    out = np.full(len(depth), np.nan)
    idx = np.flatnonzero(shale)
    if idx.size < min_n:
        return out
    order = idx[np.argsort(depth[idx], kind="stable")]
    sd, sv = depth[order], values[order]
    half = window_ft / 2.0
    lo = np.searchsorted(sd, sd - half, side="left")
    hi = np.searchsorted(sd, sd + half, side="right")
    meds = np.array([np.median(sv[a:b]) if (b - a) >= min_n else np.nan for a, b in zip(lo, hi)])
    ok = np.isfinite(meds)
    if not ok.any():
        return out
    interp = np.interp(depth, sd[ok], meds[ok])
    # only where the window around the sample holds enough shale samples
    a = np.searchsorted(sd, depth - half, side="left")
    b = np.searchsorted(sd, depth + half, side="right")
    good = (b - a) >= min_n
    out[good] = interp[good]
    return out


def _robust_line(x, y) -> Optional[dict]:
    """Linear fit y = c0 + c1 x with two passes of 3 robust sigma (MAD) rejection."""
    keep = np.ones(len(x), dtype=bool)
    coef = None
    for _ in range(ROBUST_PASSES + 1):
        if keep.sum() < 2 or np.ptp(x[keep]) <= 0:
            return None
        coef = np.polyfit(x[keep], y[keep], 1)
        res = y - (coef[1] + coef[0] * x)
        mad = float(np.median(np.abs(res[keep] - np.median(res[keep]))))
        sigma = 1.4826 * mad
        if sigma <= 0:
            break
        new = np.abs(res - np.median(res[keep])) <= SIGMA_REJECT * sigma
        if new.sum() < 2 or (new == keep).all():
            keep = new if new.sum() >= 2 else keep
            break
        keep = new
    coef = np.polyfit(x[keep], y[keep], 1)
    res = y[keep] - (coef[1] + coef[0] * x[keep])
    sst = float(((y[keep] - y[keep].mean()) ** 2).sum())
    return {"c0": float(coef[1]), "c1": float(coef[0]), "n_fit": int(keep.sum()),
            "rmse": float(np.sqrt((res ** 2).mean())),
            "r2": float(1.0 - (res ** 2).sum() / sst) if sst > 0 else None}


def _trend(mask, phie, ai_rel, vp_rel, min_n, min_span) -> Optional[dict]:
    """Wet trends for a boolean wet mask, or None when the count or the PHIE span is short."""
    m = mask & np.isfinite(phie) & np.isfinite(ai_rel) & np.isfinite(vp_rel)
    n = int(m.sum())
    if n < min_n or n < 2:
        return None
    span = float(np.ptp(phie[m]))
    if span < min_span:
        return None
    fa = _robust_line(phie[m], ai_rel[m])
    fv = _robust_line(phie[m], vp_rel[m])
    if fa is None or fv is None:
        return None
    return {"n": n, "phi_span": span, "ai": fa, "vpvs": fv}


def _eval(trend: dict, key: str, phie, rel):
    fit = trend[key]
    base = fit["c0"] + fit["c1"] * phie
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(base > 0, rel / base - 1.0, np.nan)


def _empty(n, summary, issues, ran=False) -> ElasticOutput:
    return ElasticOutput(np.full(n, np.nan), np.full(n, np.nan), np.zeros(n, dtype=int), summary,
                         issues, ran)


def elastic_screen(results: pd.DataFrame, curves: dict, params_by_zone: dict,
                   zone_keys: np.ndarray) -> ElasticOutput:
    """AI, Vp/Vs and the elastic flag for the whole well; inputs are not modified."""
    n = len(results)
    issues: List[Tuple[str, str, Optional[str], Optional[str]]] = []
    names = {k: (curves or {}).get(k) for k in ("DT", "DTS", "RHOB")}
    missing = [k for k, v in names.items() if v is None]
    if missing:
        issues.append(("LRLC_ELASTIC_NO_DTS",
                       "Elastic screening skipped: " + ", ".join(missing) + " not mapped.", None, None))
        return _empty(n, {"skipped": "missing " + ", ".join(missing)}, issues)
    dt, dts, rhob = (np.array(names[k], dtype=float) for k in ("DT", "DTS", "RHOB"))
    depth = np.array(curves.get("DEPTH", results["DEPTH"] if "DEPTH" in results.columns
                                else np.arange(n)), dtype=float)
    if looks_like_us_per_m(dt, dts):
        issues.append(("LRLC_ELASTIC_UNITS",
                       "Elastic screening skipped: DT or DTS look like us/m; convert to us/ft.",
                       None, None))
        return _empty(n, {"skipped": "units"}, issues)

    def column(name, default=np.nan):
        if curves.get(name) is not None:
            return np.array(curves[name], dtype=float)
        if name in results.columns:
            return pd.to_numeric(results[name], errors="coerce").to_numpy(dtype=float)
        return np.full(n, default)

    vsh, phie, sw = column("VSH"), column("PHIE"), column("SW")
    net = column("NET_RES_FLAG", 0.0) == 1
    base_flag = column("LRLC_FLAG", 0.0) == 1
    keys = np.asarray(zone_keys, dtype=object)
    zone_list = list(dict.fromkeys(keys.tolist()))
    sets = {z: _settings(params_by_zone, z) for z in zone_list}
    well = sets[zone_list[0]] if zone_list else dict(DEFAULTS)
    mode = well["el_mode"] if well["el_mode"] in ("both", "ai", "vpvs") else "both"

    dz = curves.get("DZ")
    if dz is None:
        step = np.abs(np.diff(depth))
        step = step[np.isfinite(step) & (step > 0)]
        dz = np.full(n, float(np.median(step)) if step.size else 0.0)
    dz = np.nan_to_num(np.array(dz, dtype=float), nan=0.0)

    valid = validity_mask(dt, dts, rhob)
    with np.errstate(invalid="ignore", divide="ignore"):
        ai = np.where(valid, acoustic_impedance(dt, rhob), np.nan)
        vpvs = np.where(valid, vp_vs_ratio(dt, dts), np.nan)
    present = np.isfinite(dt) | np.isfinite(dts) | np.isfinite(rhob)
    n_invalid = int((present & ~valid).sum())
    if n_invalid:
        share = n_invalid / max(n, 1)
        issues.append(("LRLC_ELASTIC_INVALID",
                       f"Elastic screening: {n_invalid} sample(s) ({100.0 * share:.1f} percent) are "
                       "outside the DT, DTS, RHOB or Vp/Vs validity ranges; AI and VPVS are empty and "
                       "the flag is 0 there.", None, "warning" if share > INVALID_WARN_SHARE else "info"))

    # ---- shale baselines
    shale = valid & np.isfinite(vsh) & (vsh >= well["el_vsh_shale"])
    min_n = int(well["el_shale_min_n"])
    well_ai = _median(ai[shale])
    well_vp = _median(vpvs[shale])
    ai_sh = np.full(n, np.nan)
    vp_sh = np.full(n, np.nan)
    base_mode = well["el_baseline_mode"] if well["el_baseline_mode"] in ("rolling", "zone", "window") \
        else "rolling"
    if base_mode == "rolling":
        ai_roll = _rolling_baseline(depth, ai, shale, float(well["el_shale_window_ft"]), min_n)
        vp_roll = _rolling_baseline(depth, vpvs, shale, float(well["el_shale_window_ft"]), min_n)
    base_rows = []
    for z in zone_list:
        zm = keys == z
        zshale = zm & shale
        fallback = None
        a_val = v_val = np.nan
        if base_mode == "window":
            iv = _interval(sets[z]["el_shale_interval"])
            inwin = zm & valid & (depth >= iv[0]) & (depth <= iv[1]) if iv else np.zeros(n, dtype=bool)
            if inwin.sum() >= min_n:
                a_val, v_val = _median(ai[inwin]), _median(vpvs[inwin])
                ai_sh[zm], vp_sh[zm] = a_val, v_val
                n_sh = int(inwin.sum())
            else:
                n_sh = int(zshale.sum())
        else:
            n_sh = int(zshale.sum())
            if base_mode == "rolling":
                ai_sh[zm], vp_sh[zm] = ai_roll[zm], vp_roll[zm]
        z_ai = _median(ai[zshale]) if zshale.sum() >= min_n else np.nan
        z_vp = _median(vpvs[zshale]) if zshale.sum() >= min_n else np.nan
        if base_mode == "zone":
            ai_sh[zm], vp_sh[zm] = z_ai, z_vp
        need = zm & ~np.isfinite(ai_sh)
        if need.any():
            if np.isfinite(z_ai) and np.isfinite(z_vp):
                ai_sh[need], vp_sh[need] = z_ai, z_vp
                fallback = "zone"
            else:
                ai_sh[need], vp_sh[need] = well_ai, well_vp
                fallback = "well"
        if fallback is not None:
            have = np.isfinite(well_ai) if fallback == "well" else True
            issues.append(("LRLC_ELASTIC_NO_SHALE",
                           f"Elastic screening: too few shale samples for the {base_mode} baseline in "
                           f"{_label(z)}; "
                           + (f"the {fallback} median is used." if have else "no shale in the well; "
                              "the samples are not evaluated."),
                           None if z == UNZONED else str(z), None))
        a_show = _median(ai_sh[zm & np.isfinite(ai_sh)])
        v_show = _median(vp_sh[zm & np.isfinite(vp_sh)])
        base_rows.append({"zone": _label(z), "n_shale": n_sh, "ai_shale_median": a_show,
                          "vpvs_shale_median": v_show, "fallback": fallback})
    with np.errstate(invalid="ignore", divide="ignore"):
        ai_rel = ai / ai_sh
        vp_rel = vpvs / vp_sh

    # ---- wet trend
    min_wet, min_span = int(well["el_min_wet_n"]), float(well["el_min_phi_span"])
    wet_iv = _interval(well["el_wet_interval"])
    sw_wet = np.array([sets[z]["el_sw_wet"] for z in keys.tolist()], dtype=float) if n else np.zeros(0)
    if wet_iv is not None:
        wet_source = "interval"
        wet = net & (depth >= wet_iv[0]) & (depth <= wet_iv[1])
    else:
        wet_source = "sw"
        wet = net & ~base_flag & np.isfinite(sw) & (sw >= sw_wet)
    wet = wet & np.isfinite(phie) & np.isfinite(ai_rel) & np.isfinite(vp_rel)
    scope = well["el_trend_scope"] if well["el_trend_scope"] in ("well", "zone") else "well"
    well_trend = _trend(wet, phie, ai_rel, vp_rel, min_wet, min_span)
    if well_trend is None:
        issues.append(("LRLC_ELASTIC_NO_WET",
                       f"Elastic screening: no wet trend ({int(wet.sum())} wet sample(s), need "
                       f"{min_wet} and a porosity span of {min_span:g}); the flag is 0 and the samples "
                       "are counted as not evaluable.", None, None))
    trends = {}
    for z in zone_list:
        t = well_trend
        if scope == "zone":
            zt = _trend(wet & (keys == z), phie, ai_rel, vp_rel, min_wet, min_span)
            if zt is not None:
                t = zt
            elif well_trend is not None:
                issues.append(("LRLC_ELASTIC_NO_WET",
                               f"Elastic screening: too few wet samples in {_label(z)}; the well trend "
                               "is used.", None if z == UNZONED else str(z), "info"))
        trends[z] = t

    # ---- flag
    flag = np.zeros(n, dtype=int)
    evaluable = np.zeros(n, dtype=bool)
    for z in zone_list:
        t = trends[z]
        if t is None:
            continue
        zm = keys == z
        d_a = _eval(t, "ai", phie, ai_rel)
        d_v = _eval(t, "vpvs", phie, vp_rel)
        s = sets[z]
        hit_a = d_a <= -float(s["el_ai_drop"])
        hit_v = d_v <= -float(s["el_vpvs_drop"])
        if mode == "ai":
            ok, hit = np.isfinite(d_a), hit_a
        elif mode == "vpvs":
            ok, hit = np.isfinite(d_v), hit_v
        else:
            ok, hit = np.isfinite(d_a) & np.isfinite(d_v), hit_a & hit_v
        ok = ok & np.isfinite(phie)
        evaluable[zm] = ok[zm]
        flag[zm] = (net & ok & hit)[zm].astype(int)
    unevaluable = net & ~evaluable
    n_unev = int(unevaluable.sum())

    zone_rows = []
    for z in zone_list:
        zm = keys == z
        fm = zm & (flag == 1)
        zone_rows.append({"zone": _label(z), "n_net": int((zm & net).sum()), "n_flag": int(fm.sum()),
                          "thickness_flag_ft": float(dz[fm].sum()),
                          "n_invalid": int((zm & present & ~valid).sum())})
    wet_block = {"source": wet_source, "scope": scope, "n": int(wet.sum()),
                 "ai": None, "vpvs": None, "phi_span": None}
    if well_trend is not None:
        wet_block.update({
            "ai": {"a0": well_trend["ai"]["c0"], "a1": well_trend["ai"]["c1"],
                   "r2": well_trend["ai"]["r2"], "rmse": well_trend["ai"]["rmse"]},
            "vpvs": {"c0": well_trend["vpvs"]["c0"], "c1": well_trend["vpvs"]["c1"],
                     "r2": well_trend["vpvs"]["r2"], "rmse": well_trend["vpvs"]["rmse"]},
            "phi_span": well_trend["phi_span"]})
    summary = {
        "curves": {k: (curves.get(f"{k}_NAME") or k) for k in ("DT", "DTS", "RHOB")},
        "params": {k: well[k] for k in DEFAULTS if k not in ("el_sw_wet", "el_ai_drop", "el_vpvs_drop",
                                                              "el_shale_interval")},
        "baseline": {"mode": base_mode, "zones": base_rows},
        "wet": wet_block,
        "zones": zone_rows,
        "counts": {"n": n, "valid": int(valid.sum()), "invalid": n_invalid, "net": int(net.sum()),
                   "flag": int(flag.sum()), "unevaluable": n_unev, "wet": int(wet.sum())},
    }
    return ElasticOutput(ai, vpvs, flag, summary, issues, True)
