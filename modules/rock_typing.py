"""
Rock typing from core: RQI/FZI, hydraulic-flow-unit clustering, Winland R35, Lorenz (pure, no Qt).

Core permeability and porosity become RQI and FZI (Amaefule et al. 1993, SPE 26436);
:func:`fit_rock_types` clusters ``log10(FZI)`` with a seeded k-means into rock types
(``1`` = lowest FZI) and returns one plain-data "set" (centres, midpoint boundaries,
representative FZI) that the project stores and the pipeline only consumes
(P1 rock-typing spec, sections 3 to 5). :func:`build_core_table` turns the core of every
well into one row per sample with exactly one status, so every exclusion is counted.
The Winland R35 method, the Lorenz coefficient and the stratigraphic modified Lorenz
plot (SMLP) with flow-unit segments live here too.

Every value in a returned definition dict is a plain Python ``float``/``int``/``list``/``None``
(no numpy scalars, no tuples), so ``json.dumps(..., default=str)`` is stable across a
session save and load.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.cluster.vq import ClusterError, kmeans2

from modules.petrophysics import pay_summary

K_RQI = 0.0314                       # um, k in mD, phi as a fraction
PERM_CLIP = (0.001, 50000.0)         # same clip as PERM_TIMUR
R35_BOUNDARIES = [-1.0, -0.301, 0.301, 1.0]   # log10 um: 0.1, 0.5, 2, 10 (Martin et al. 1997)
R35_CLASSES = ["nano", "micro", "meso", "macro", "mega"]
KMEANS_RESTARTS = 10
KMEANS_ITER = 50
SILHOUETTE_MAX_POINTS = 3000
OUTLIER_Z = 3.0

DEFAULT_SETTINGS = {
    "seed": 0, "restarts": KMEANS_RESTARTS, "min_samples": 20, "min_per_rt": 5,
    "reservoir_only": True, "min_phie": 0.02, "use_core_labels": True, "margin_min": 0.05,
    "lorenz": True, "r35_column": False, "ob_phi_factor": 1.0, "ob_k_factor": 1.0,
    # Core-plug QC limits (not the log clips of the pipeline).
    "core_phi_min": 0.01, "core_phi_max": 0.50,
}

STATUS_OK = "ok"
STATUS_REASONS = ("no_porosity", "no_perm", "perm_not_positive", "phi_out_of_range", "no_depth")
OVERBURDEN_NOTE = ("core measured as loaded; overburden/Klinkenberg correction not applied")


class RockTypingError(ValueError):
    """A fit that cannot be done; the message names the counts and is shown as is."""


# ---------------------------------------------------------------------------
# Equations
# ---------------------------------------------------------------------------
def _arr(x) -> np.ndarray:
    return np.asarray(x, dtype=float)


def rqi(k, phie) -> np.ndarray:
    """Reservoir quality index ``0.0314 * sqrt(k / phie)`` (um); NaN unless k > 0 and 0 < phie."""
    k, phie = np.broadcast_arrays(_arr(k), _arr(phie))
    ok = (k > 0) & (phie > 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(ok, K_RQI * np.sqrt(np.where(ok, k / np.where(ok, phie, 1.0), np.nan)), np.nan)


def phi_z(phie) -> np.ndarray:
    """Pore-to-grain volume ratio ``phie / (1 - phie)``; NaN outside 0 < phie < 1."""
    phie = _arr(phie)
    ok = (phie > 0) & (phie < 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(ok, phie / np.where(ok, 1.0 - phie, 1.0), np.nan)


def free_slope_fits(phiz, rqi_values, labels, n_rt, min_samples=3) -> list[dict]:
    """Per rock type least-squares ``log10(RQI) = a + b * log10(phi_z)`` (diagnostic only).

    One dict per type 1..n_rt: ``rt``, ``n``, ``slope`` (b), ``intercept_fzi`` (10**a, the RQI at
    phi_z = 1), ``r2`` (in log space), ``phiz_min``, ``phiz_max``. Only finite, positive samples
    count. ``slope``, ``intercept_fzi`` and ``r2`` are None with fewer than ``min_samples`` samples
    or identical phi_z; ``r2`` is also None when log RQI has no spread. Label 0 is ignored.
    """
    x, y, lab = np.broadcast_arrays(_arr(phiz), _arr(rqi_values), np.asarray(labels))
    ok = np.isfinite(x) & np.isfinite(y) & (x > 0) & (y > 0)
    out = []
    for i in range(1, int(n_rt) + 1):
        sel = ok & (lab == i)
        n = int(sel.sum())
        rec = {"rt": i, "n": n, "slope": None, "intercept_fzi": None, "r2": None,
               "phiz_min": float(x[sel].min()) if n else None,
               "phiz_max": float(x[sel].max()) if n else None}
        if n >= max(int(min_samples), 2):
            lx, ly = np.log10(x[sel]), np.log10(y[sel])
            if np.ptp(lx) > 0:
                b, a = np.polyfit(lx, ly, 1)
                sstot = float(np.sum((ly - ly.mean()) ** 2))
                rec["slope"], rec["intercept_fzi"] = float(b), float(10.0 ** a)
                if sstot > 0:
                    ssres = float(np.sum((ly - (a + b * lx)) ** 2))
                    rec["r2"] = 1.0 - ssres / sstot
        out.append(rec)
    return out


def fzi(k, phie) -> np.ndarray:
    """Flow zone indicator ``RQI / phi_z`` (um)."""
    with np.errstate(invalid="ignore", divide="ignore"):
        return rqi(k, phie) / phi_z(phie)


def perm_from_fzi(fzi_value, phie) -> np.ndarray:
    """``k = FZI^2 * phi_z^2 * phie / 0.0314^2`` (mD), clipped to [0.001, 50000].

    The source analysis wrote ``phi_z^3``; that form is off by a factor phi_z. The exact
    ``K_RQI**2`` (not the rounded 1014) is used so ``perm_from_fzi(fzi(k, phi), phi) == k``.
    """
    k = _arr(fzi_value) ** 2 * phi_z(phie) ** 2 * _arr(phie) / K_RQI ** 2
    return np.clip(k, *PERM_CLIP)


def winland_r35(k, phie) -> np.ndarray:
    """Winland R35 (um): ``log R35 = 0.732 + 0.588 log k - 0.864 log(phi %)``; phie is a fraction."""
    k, phie = np.broadcast_arrays(_arr(k), _arr(phie))
    ok = (k > 0) & (phie > 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        k_safe = np.where(ok, k, np.nan)
        phi_pct = np.where(ok, phie * 100.0, np.nan)
        return 10.0 ** (0.732 + 0.588 * np.log10(k_safe) - 0.864 * np.log10(phi_pct))


# ---------------------------------------------------------------------------
# Core snapshot and core table
# ---------------------------------------------------------------------------
@dataclass
class CoreInput:
    """One well's core as plain arrays (a GUI-thread snapshot; safe to hand to a worker).

    ``load_excluded`` counts the values the core loader blanked (reason -> n), see
    :func:`core_inputs`.
    """
    well_key: str
    well: str
    depth_ft: np.ndarray
    phi: np.ndarray
    k: np.ndarray
    zone: np.ndarray
    depth_is_tvd: bool
    load_excluded: Dict[str, int] = field(default_factory=dict)


def _load_reason(text: str) -> str:
    low = text.lower()
    if "null sentinel" in low:
        return "null_sentinel"
    if "negative porosity" in low:
        return "negative_porosity"
    if "permeability not positive" in low:
        return "nonpositive_perm"
    if "porosity" in low and "out of range" in low:
        return "porosity_out_of_range"
    return "other"


def _load_excluded_counts(handler) -> Dict[str, int]:
    """Load-time exclusions of one well's core, by reason (from ``excluded_rows``).

    ``CoreDataHandler.split_by_well`` shallow-copies the handler, so ``excluded_rows``
    covers the whole file; the lines are filtered by the well text of each exclusion.
    """
    rows = list(getattr(handler, "excluded_rows", None) or [])
    if not rows:
        return {}
    wells = getattr(handler, "excluded_row_wells", None) or {}
    spellings = {str(s).strip() for s in (getattr(handler, "spellings", None) or [])}
    counts: Dict[str, int] = {}
    for line, reason in rows:
        if spellings and str(wells.get(line, "")).strip() not in spellings:
            continue
        key = _load_reason(str(reason))
        counts[key] = counts.get(key, 0) + 1
    return counts


def well_core_input(well) -> Optional[CoreInput]:
    """One well's core as plain arrays, or None without a porosity and permeability column.

    Zone per core row: ``assign_zones`` (the pipeline's) on the well's formation tops, with
    the core depth taken as measured depth. A well whose core depth is TVD
    (``depth_is_tvd``) cannot be matched to MD tops, so its rows are all ``UNZONED``. Wells
    without tops give ``UNZONED`` too. Arrays are copies, so later edits cannot reach a worker.
    """
    from modules.param_scopes import UNZONED
    from modules.pipeline import assign_zones      # lazy: pipeline imports this module

    core = getattr(well, "core_data", None)
    data = getattr(core, "data", None)
    if core is None or data is None:
        return None
    if not (core.depth_col and core.porosity_col and core.perm_col):
        return None
    cols = (core.depth_col, core.porosity_col, core.perm_col)
    if any(c not in data.columns for c in cols):
        return None
    depth, phi, k = (pd.to_numeric(data[c], errors="coerce").to_numpy(dtype=float).copy()
                     for c in cols)
    tvd = bool(getattr(core, "depth_is_tvd", False))
    if tvd or getattr(well, "formation_tops", None) is None:
        zone = np.full(len(depth), UNZONED, dtype=object)
    else:
        labels, _ = assign_zones(pd.Series(depth), well.formation_tops)
        zone = labels.to_numpy(dtype=object)
    return CoreInput(
        well_key=str(well.key), well=str(well.display_name or well.key),
        depth_ft=depth, phi=phi, k=k, zone=zone, depth_is_tvd=tvd,
        load_excluded=_load_excluded_counts(core))


def core_inputs(model) -> List[CoreInput]:
    """Snapshot of every well's core (GUI thread): wells with porosity and permeability columns."""
    inputs = (well_core_input(well) for well in model.project.wells)
    return [ci for ci in inputs if ci is not None]


def core_labels(ci: CoreInput, rt: dict) -> Optional[dict]:
    """``{"depth": [...], "rt": [...]}`` of one well's valid, non-TVD core rows, as plain lists.

    ``rt`` is the resolved ``rock_types`` dict (``method``, ``set``, ``zone_sets``,
    ``settings``). Each row takes the class of its own feature (log10 FZI, or log10 R35 for
    the r35 method) in the set for its zone; sorted by depth. None when nothing is labelled
    (no valid row, or TVD core depth, which cannot be matched to the MD of the logs).
    """
    if ci is None or ci.depth_is_tvd:
        return None
    table, _ = build_core_table([ci], rt.get("settings"))
    table = table[table["status"] == STATUS_OK]
    if table.empty:
        return None
    phi, k = table["phi"].to_numpy(dtype=float), table["k"].to_numpy(dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        feature = (np.log10(winland_r35(k, phi)) if rt.get("method") == "r35"
                   else table["log_fzi"].to_numpy(dtype=float))
    label = np.zeros(len(table), dtype=int)
    zone = table["zone"].to_numpy(dtype=object)
    zsets = rt.get("zone_sets") or {}
    for z in pd.unique(zone):
        mask = zone == z
        label[mask] = classify(feature[mask], zsets.get(z) or rt["set"])[0]
    keep = (label > 0) & np.isfinite(table["depth"].to_numpy(dtype=float))
    if not keep.any():
        return None
    depth = table["depth"].to_numpy(dtype=float)[keep]
    order = np.argsort(depth, kind="stable")
    return {"depth": [float(v) for v in depth[order]],
            "rt": [int(v) for v in label[keep][order]]}


def _settings(settings) -> dict:
    merged = dict(DEFAULT_SETTINGS)
    merged.update(settings or {})
    return merged


def build_core_table(inputs, settings=None) -> Tuple[pd.DataFrame, dict]:
    """One row per core sample with exactly one ``status``, and the report that counts them.

    Columns: well_key, well, depth, zone, phi, k (the values used, i.e. after the
    ``ob_phi_factor`` / ``ob_k_factor`` overburden factors), rqi, fzi, log_fzi, outlier_z3,
    status (``ok`` or the first failing reason of ``no_porosity``, ``no_perm``,
    ``perm_not_positive``, ``phi_out_of_range``, ``no_depth``). The phi range check is on the
    measured porosity.

    Report keys: rows, valid, excluded {reason: n} (non-zero only), per_well {well_key:
    {well, rows, valid, excluded}}, load_excluded {reason: n} (blanked by the loader; the cause
    of part of the no_porosity/no_perm counts, not extra rows), outliers_z3 (n),
    outlier_rows (list of {well_key, depth, log_fzi}), tvd_wells (well keys), overburden
    ({phi, k, applied}), notes (list of text).
    """
    s = _settings(settings)
    f_phi, f_k = float(s["ob_phi_factor"]), float(s["ob_k_factor"])
    frames = []
    per_well: Dict[str, dict] = {}
    load_excluded: Dict[str, int] = {}
    tvd_wells: List[str] = []
    for ci in inputs:
        depth, phi, k = _arr(ci.depth_ft), _arr(ci.phi), _arr(ci.k)
        n = len(depth)
        status = np.full(n, STATUS_OK, dtype=object)
        with np.errstate(invalid="ignore"):
            bad = {
                "no_depth": ~np.isfinite(depth),
                "phi_out_of_range": np.isfinite(phi) & ((phi <= s["core_phi_min"]) | (phi > s["core_phi_max"])),
                "perm_not_positive": np.isfinite(k) & (k <= 0),
                "no_perm": ~np.isfinite(k),
                "no_porosity": ~np.isfinite(phi),
            }
        for reason in ("no_depth", "phi_out_of_range", "perm_not_positive", "no_perm", "no_porosity"):
            status[bad[reason]] = reason         # later (higher priority) reasons overwrite
        phi_used, k_used = phi * f_phi, k * f_k
        valid = status == STATUS_OK
        r = np.full(n, np.nan)
        z = np.full(n, np.nan)
        r[valid] = rqi(k_used[valid], phi_used[valid])
        z[valid] = fzi(k_used[valid], phi_used[valid])
        with np.errstate(invalid="ignore", divide="ignore"):
            lf = np.log10(z)
        # A factor can push phi_used to >= 1 (FZI undefined): count it as out of range.
        undefined = valid & ~np.isfinite(lf)
        status[undefined] = "phi_out_of_range"
        valid = status == STATUS_OK
        outlier = np.zeros(n, dtype=bool)
        if valid.sum() >= 3:
            sd = np.std(lf[valid])
            if sd > 0:
                outlier[valid] = np.abs(lf[valid] - np.mean(lf[valid])) / sd > OUTLIER_Z
        frames.append(pd.DataFrame({
            "well_key": ci.well_key, "well": ci.well, "depth": depth,
            "zone": np.asarray(ci.zone, dtype=object), "phi": phi_used, "k": k_used,
            "rqi": r, "fzi": z, "log_fzi": lf, "outlier_z3": outlier, "status": status}))
        exc = {x: int((status == x).sum()) for x in STATUS_REASONS if (status == x).any()}
        per_well[ci.well_key] = {"well": ci.well, "rows": int(n), "valid": int(valid.sum()),
                                 "excluded": exc}
        for reason, c in (ci.load_excluded or {}).items():
            load_excluded[reason] = load_excluded.get(reason, 0) + int(c)
        if ci.depth_is_tvd:
            tvd_wells.append(ci.well_key)
    cols = ["well_key", "well", "depth", "zone", "phi", "k", "rqi", "fzi", "log_fzi",
            "outlier_z3", "status"]
    table = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=cols)
    ok = table["status"] == STATUS_OK
    excluded = {x: int((table["status"] == x).sum()) for x in STATUS_REASONS
                if (table["status"] == x).any()}
    out_rows = table[table["outlier_z3"] & ok]
    notes = []
    if f_phi == 1.0 and f_k == 1.0:
        notes.append(OVERBURDEN_NOTE)
    else:
        notes.append(f"overburden factors applied: porosity x{f_phi:g}, permeability x{f_k:g} "
                     "(user input, not a built-in correction)")
    if load_excluded:
        notes.append("Values blanked by the core loader are part of the no_porosity/no_perm "
                     "counts, not additional rows.")
    if tvd_wells:
        notes.append("Core depth is TVD in " + ", ".join(tvd_wells) + ": rows enter the fit but "
                     "not the core labels in the log.")
    report = {
        "rows": int(len(table)), "valid": int(ok.sum()), "excluded": excluded,
        "per_well": per_well, "load_excluded": load_excluded,
        "outliers_z3": int(len(out_rows)),
        "outlier_rows": [{"well_key": str(r.well_key), "depth": float(r.depth),
                          "log_fzi": float(r.log_fzi)} for r in out_rows.itertuples()],
        "tvd_wells": tvd_wells,
        "overburden": {"phi": f_phi, "k": f_k, "applied": not (f_phi == 1.0 and f_k == 1.0)},
        "notes": notes,
    }
    return table, report


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------
def _finite_sorted(feature) -> np.ndarray:
    x = _arr(feature).ravel()
    return np.sort(x[np.isfinite(x)])


def _kmeans_1d(xs: np.ndarray, n_rt: int, seeds) -> Tuple[Optional[np.ndarray], int]:
    """Best (lowest within-cluster sum of squares) sorted centres over ``seeds``; None if all fail."""
    best, best_wcss, failed = None, np.inf, 0
    for seed in seeds:
        try:
            centres, labels = kmeans2(xs, n_rt, iter=KMEANS_ITER, minit="++",
                                      missing="raise", seed=int(seed))
        except (ClusterError, ValueError):
            failed += 1
            continue
        wcss = float(np.sum((xs - centres[labels]) ** 2))
        if wcss < best_wcss:
            best, best_wcss = np.sort(centres), wcss
    return best, failed


def _class_counts(xs: np.ndarray, boundaries: np.ndarray, n_rt: int) -> np.ndarray:
    return np.bincount(np.searchsorted(boundaries, xs), minlength=n_rt)


def _silhouette_sorted(xs: np.ndarray, labels: np.ndarray, n_rt: int) -> float:
    """Mean silhouette of 1-D data sorted ascending whose classes are contiguous runs."""
    n = len(xs)
    prefix = np.concatenate([[0.0], np.cumsum(xs)])
    edges = np.concatenate([[0], np.cumsum(np.bincount(labels, minlength=n_rt))])

    def dist_sum(lo: int, hi: int) -> np.ndarray:
        # sum_{j in [lo, hi)} |x_i - x_j| for every i, from prefix sums.
        m = np.clip(np.searchsorted(xs, xs), lo, hi)
        return (m - lo) * xs - (prefix[m] - prefix[lo]) + (prefix[hi] - prefix[m]) - (hi - m) * xs

    a = np.empty(n)
    b = np.full(n, np.inf)
    for c in range(n_rt):
        lo, hi = edges[c], edges[c + 1]
        own = labels == c
        a[own] = dist_sum(lo, hi)[own] / max(hi - lo - 1, 1)
        for d in range(n_rt):
            if d != c:
                lo2, hi2 = edges[d], edges[d + 1]
                b[own] = np.minimum(b[own], dist_sum(lo2, hi2)[own] / (hi2 - lo2))
    denom = np.maximum(a, b)
    s = np.where(denom > 0, (b - a) / np.where(denom > 0, denom, 1.0), 0.0)
    return float(np.mean(s))


def suggest_n_rt(feature, k_max=8, min_per_rt=5) -> Tuple[Optional[int], dict]:
    """Rock-type count with the best mean 1-D silhouette (Rousseeuw 1987), k = 2 ... k_max.

    Only k whose every class holds at least ``min_per_rt`` samples count. Data over 3000
    points use a deterministic evenly spaced subsample of the sorted values for the
    silhouette (class counts are checked on all the data). Returns ``(n or None, info)``;
    ``info`` = {"silhouette": {k: score}, "n_samples": n, "subsampled": bool, "k_max": k_max}.
    """
    xs = _finite_sorted(feature)
    n = len(xs)
    info = {"silhouette": {}, "n_samples": int(n), "subsampled": False, "k_max": int(k_max)}
    if n < 2 * max(int(min_per_rt), 1):
        return None, info
    sub = xs
    if n > SILHOUETTE_MAX_POINTS:
        sub = xs[np.linspace(0, n - 1, SILHOUETTE_MAX_POINTS).round().astype(int)]
        info["subsampled"] = True
    best_k, best_s = None, -np.inf
    for k in range(2, int(k_max) + 1):
        if n < k * min_per_rt or len(np.unique(sub)) < k:
            break
        centres, _ = _kmeans_1d(sub, k, range(3))
        if centres is None:
            continue
        bounds = (centres[:-1] + centres[1:]) / 2.0
        if _class_counts(xs, bounds, k).min() < min_per_rt:
            continue
        labels = np.searchsorted(bounds, sub)
        if np.bincount(labels, minlength=k).min() == 0:
            continue
        score = _silhouette_sorted(sub, labels, k)
        info["silhouette"][k] = float(score)
        if score > best_s + 1e-12:
            best_k, best_s = k, score
    return best_k, info


def _plain(values) -> list:
    return [None if v is None or not np.isfinite(v) else float(v) for v in values]


def _k_rmse(x, phi, k, labels, fzi_rt, n_rt) -> list:
    out = []
    for i in range(n_rt):
        sel = labels == i
        if phi is None or fzi_rt[i] is None or not sel.any():
            out.append(None)
            continue
        pred = perm_from_fzi(fzi_rt[i], phi[sel])
        d = np.log10(k[sel]) - np.log10(pred)
        d = d[np.isfinite(d)]
        out.append(float(np.sqrt(np.mean(d ** 2))) if len(d) else None)
    return out


def _core_arrays(feature, phi, k):
    x = _arr(feature).ravel()
    p = None if phi is None else _arr(phi).ravel()
    kk = None if k is None else _arr(k).ravel()
    ok = np.isfinite(x)
    if p is not None and kk is not None:
        ok &= np.isfinite(p) & np.isfinite(kk) & (kk > 0)
        return x[ok], p[ok], kk[ok]
    return x[ok], None, None


def fit_rock_types(feature, n_rt, *, method="fzi", settings=None, phi=None, k=None,
                   log_fzi=None, basis=None) -> dict:
    """One rock-type "set" from the core feature (``log10(FZI)``, or ``log10(R35)`` for r35).

    FZI method: ``kmeans2(minit='++', missing='raise')`` on the sorted feature (so the input
    order cannot matter), seeds 0..9, lowest within-cluster sum of squares wins; centres sorted
    ascending (rock type 1 = lowest FZI), boundaries are the midpoints, ``fzi = 10**centre``.
    ``phi`` and ``k`` (aligned with ``feature``) give ``k_rmse_log10`` per type.

    R35 method: fixed boundaries ``R35_BOUNDARIES`` (five port-size classes); ``log_fzi``
    (aligned with ``feature``) gives each class its geometric-mean FZI, ``None`` for an
    empty class.

    Set keys: n_rt, centers, boundaries, fzi, n_samples, sd, feature_range, k_rmse_log10,
    edited, basis. Raises :class:`RockTypingError` naming the counts when the data cannot
    support the fit.
    """
    s = _settings(settings)
    if method == "r35":
        return _fit_r35(feature, s, phi, k, log_fzi, basis)
    xs_all, p_all, k_all = _core_arrays(feature, phi, k)
    n = len(xs_all)
    if n_rt < 2:
        raise RockTypingError(f"At least 2 rock types are needed (asked for {n_rt}).")
    if n < s["min_samples"]:
        raise RockTypingError(
            f"Only {n} valid core samples; at least {s['min_samples']} are needed to fit rock types.")
    order = np.argsort(xs_all, kind="stable")
    xs = xs_all[order]
    p_sorted = None if p_all is None else p_all[order]
    k_sorted = None if k_all is None else k_all[order]
    seeds = range(int(s["restarts"]))
    centres, failed = _kmeans_1d(xs, int(n_rt), seeds)
    if centres is None:
        raise RockTypingError(
            f"Clustering {n} samples into {n_rt} rock types failed in all {failed} restarts "
            "(an empty class each time); use fewer rock types.")
    bounds = (centres[:-1] + centres[1:]) / 2.0
    counts = _class_counts(xs, bounds, int(n_rt))
    if counts.min() < s["min_per_rt"]:
        raise RockTypingError(
            f"{n_rt} rock types leave a class with {int(counts.min())} samples (class counts "
            f"{[int(c) for c in counts]}); at least {s['min_per_rt']} per rock type are needed. "
            "Use fewer rock types.")
    labels = np.searchsorted(bounds, xs)
    sd = [float(np.std(xs[labels == i], ddof=1)) if counts[i] > 1 else 0.0 for i in range(int(n_rt))]
    fzi_rt = [float(10.0 ** c) for c in centres]
    return {
        "n_rt": int(n_rt), "centers": _plain(centres), "boundaries": _plain(bounds),
        "fzi": fzi_rt, "n_samples": [int(c) for c in counts], "sd": sd,
        "feature_range": [float(xs[0]), float(xs[-1])],
        "k_rmse_log10": _k_rmse(xs, p_sorted, k_sorted, labels, fzi_rt, int(n_rt)),
        "edited": False, "basis": basis or f"{n} samples",
    }


def _fit_r35(feature, s, phi, k, log_fzi, basis) -> dict:
    x = _arr(feature).ravel()
    lf = None if log_fzi is None else _arr(log_fzi).ravel()
    ok = np.isfinite(x)
    n = int(ok.sum())
    if n < s["min_samples"]:
        raise RockTypingError(
            f"Only {n} valid core samples; at least {s['min_samples']} are needed to fit rock types.")
    n_rt = len(R35_CLASSES)
    labels = np.searchsorted(R35_BOUNDARIES, x)
    out = default_r35_set()
    counts, sds, fzis, rmse = [], [], [], []
    for i in range(n_rt):
        sel = ok & (labels == i)
        counts.append(int(sel.sum()))
        sds.append(float(np.std(x[sel], ddof=1)) if sel.sum() > 1 else (0.0 if sel.any() else None))
        g = None
        if lf is not None:
            v = lf[sel]
            v = v[np.isfinite(v)]
            if len(v):
                g = float(10.0 ** np.mean(v))
        fzis.append(g)
        if g is not None and phi is not None and k is not None:
            p, kk = _arr(phi).ravel()[sel], _arr(k).ravel()[sel]
            d = np.log10(kk) - np.log10(perm_from_fzi(g, p))
            d = d[np.isfinite(d)]
            rmse.append(float(np.sqrt(np.mean(d ** 2))) if len(d) else None)
        else:
            rmse.append(None)
    out.update({"n_samples": counts, "sd": sds, "fzi": fzis, "k_rmse_log10": rmse,
                "feature_range": [float(x[ok].min()), float(x[ok].max())],
                "basis": basis or f"{n} samples, Winland R35 port-size classes"})
    return out


def default_r35_set() -> dict:
    """Winland R35 port-size set: fixed boundaries, five types (1 = nano), no core statistics.

    ``centers`` are nominal plotting positions (class midpoints in log10 um; the outer
    classes use 0.5 log unit beyond their boundary); ``fzi`` is ``None`` until a fit gives
    each class the geometric-mean FZI of its core samples.
    """
    b = R35_BOUNDARIES
    centres = [b[0] - 0.5] + [(b[i] + b[i + 1]) / 2.0 for i in range(len(b) - 1)] + [b[-1] + 0.5]
    n = len(R35_CLASSES)
    return {
        "n_rt": n, "centers": [float(c) for c in centres], "boundaries": [float(v) for v in b],
        "fzi": [None] * n, "n_samples": [0] * n, "sd": [None] * n, "feature_range": None,
        "k_rmse_log10": [None] * n, "edited": False,
        "basis": "Winland R35 port-size classes (fixed boundaries)",
    }


def classify(feature, rt_set) -> Tuple[np.ndarray, np.ndarray]:
    """Rock type ``1..n`` (``searchsorted(boundaries, x) + 1``) and the margin per sample.

    The margin is the distance, in log10 units, to the nearest boundary. A NaN feature gives
    rock type 0 and a NaN margin.
    """
    x = _arr(feature)
    bounds = np.asarray(rt_set["boundaries"], dtype=float)
    finite = np.isfinite(x)
    rt = np.where(finite, np.searchsorted(bounds, np.where(finite, x, 0.0)) + 1, 0).astype(int)
    if len(bounds) == 0:
        return rt, np.full(x.shape, np.nan)
    margin = np.min(np.abs(np.where(finite, x, np.nan)[..., None] - bounds), axis=-1)
    return rt, margin


# ---------------------------------------------------------------------------
# Lorenz and SMLP
# ---------------------------------------------------------------------------
def core_thickness(depth_ft) -> np.ndarray:
    """Thickness represented by each core sample (ft), in the order of ``depth_ft``.

    Half the distance to each neighbour, each side capped at half the median spacing, i.e.
    ``min(gap, median) / 2``: a core gap is a gap, not thickness. The first and last samples
    use the median spacing for their open side. Fewer than two samples give zeros.
    """
    d = _arr(depth_ft).ravel()
    h = np.zeros(len(d))
    if len(d) < 2:
        return h
    order = np.argsort(d, kind="stable")
    ds = d[order]
    gaps = np.diff(ds)
    pos = gaps[gaps > 0]
    if not len(pos):
        return h
    cap = float(np.median(pos))
    side = np.minimum(gaps, cap) / 2.0
    hs = np.zeros(len(ds))
    hs[:-1] += side
    hs[1:] += side
    hs[0] += cap / 2.0
    hs[-1] += cap / 2.0
    h[order] = hs
    return h


def _valid_lorenz(phi, k, h):
    phi, k, h = _arr(phi).ravel(), _arr(k).ravel(), _arr(h).ravel()
    ok = np.isfinite(phi) & np.isfinite(k) & np.isfinite(h) & (phi > 0) & (k >= 0) & (h > 0)
    return ok, phi, k, h


def lorenz_coefficient(phi, k, h) -> float:
    """Lorenz coefficient (Schmalz and Rahme 1950): 0 homogeneous, towards 1 heterogeneous.

    Samples sorted by ``k / phi`` descending; ``C = cum(phi h)``, ``F = cum(k h)``
    (both normalised); ``LC = 2 * integral(F - C) dC`` (trapezoid). NaN when nothing is valid
    or the total flow capacity is zero.
    """
    ok, phi, k, h = _valid_lorenz(phi, k, h)
    phi, k, h = phi[ok], k[ok], h[ok]
    if not len(phi) or (k * h).sum() <= 0:
        return float("nan")
    order = np.argsort(-(k / phi), kind="stable")
    c = np.concatenate([[0.0], np.cumsum((phi * h)[order])])
    f = np.concatenate([[0.0], np.cumsum((k * h)[order])])
    c, f = c / c[-1], f / f[-1]
    gap = f - c
    return float(2.0 * np.sum(np.diff(c) * (gap[1:] + gap[:-1]) / 2.0))


def smlp(depth, phi, k, h) -> pd.DataFrame:
    """Stratigraphic modified Lorenz plot (Gunter et al. 1997): samples in depth order.

    Columns: depth, top, base (depth -/+ h/2), h, C, F (cumulative storage and flow capacity
    fractions down to the base of each sample). Invalid samples (NaN, phi <= 0, k < 0,
    h <= 0) are dropped. The curve starts at the origin (0, 0), which is not a row.
    """
    d = _arr(depth).ravel()
    ok, phi, k, h = _valid_lorenz(phi, k, h)
    ok &= np.isfinite(d)
    order = np.argsort(d[ok], kind="stable")
    d, phi, k, h = d[ok][order], phi[ok][order], k[ok][order], h[ok][order]
    if not len(d) or (k * h).sum() <= 0:
        return pd.DataFrame(columns=["depth", "top", "base", "h", "C", "F"])
    c = np.cumsum(phi * h)
    f = np.cumsum(k * h)
    return pd.DataFrame({"depth": d, "top": d - h / 2.0, "base": d + h / 2.0, "h": h,
                         "C": c / c[-1], "F": f / f[-1]})


def _rdp(px: np.ndarray, py: np.ndarray, eps: float) -> List[int]:
    """Indices kept by Ramer-Douglas-Peucker on the polyline (px, py)."""
    keep = {0, len(px) - 1}
    stack = [(0, len(px) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        dx, dy = px[b] - px[a], py[b] - py[a]
        norm = np.hypot(dx, dy)
        sl = slice(a + 1, b)
        if norm == 0:
            dist = np.hypot(px[sl] - px[a], py[sl] - py[a])
        else:
            dist = np.abs(dx * (py[sl] - py[a]) - dy * (px[sl] - px[a])) / norm
        i = int(np.argmax(dist))
        if dist[i] > eps:
            m = a + 1 + i
            keep.add(m)
            stack += [(a, m), (m, b)]
    return sorted(keep)


def _slope_class(slope: float) -> str:
    if slope > 1.5:
        return "speed"
    if slope <= 0.1:
        return "barrier"
    if slope < 0.5:
        return "baffle"
    return "intermediate"


def smlp_units(curve, eps=0.02, min_thickness_ft=5.0) -> List[dict]:
    """Flow-unit segments of an SMLP curve (:func:`smlp`).

    Ramer-Douglas-Peucker on the polyline in the unit square (tolerance ``eps``), then
    segments thinner than ``min_thickness_ft`` merge into the neighbour with the closer
    slope. Each unit: top, bottom, thickness (sum of sample h), storage_fraction,
    flow_fraction, slope (flow / storage) and class: ``speed`` slope > 1.5, ``barrier``
    <= 0.1, ``baffle`` < 0.5, else ``intermediate``. All plain float/str.
    """
    if curve is None or len(curve) == 0:
        return []
    cx = np.concatenate([[0.0], curve["C"].to_numpy(dtype=float)])
    cy = np.concatenate([[0.0], curve["F"].to_numpy(dtype=float)])
    tops = np.concatenate([[float(curve["top"].iloc[0])], curve["base"].to_numpy(dtype=float)])
    cum_h = np.concatenate([[0.0], np.cumsum(curve["h"].to_numpy(dtype=float))])
    knots = _rdp(cx, cy, float(eps))
    # Segment = (first knot, last knot); merging joins neighbours.
    segs = [[knots[i], knots[i + 1]] for i in range(len(knots) - 1)]

    def thickness(sg):
        return cum_h[sg[1]] - cum_h[sg[0]]

    def slope(sg):
        ds = cx[sg[1]] - cx[sg[0]]
        return (cy[sg[1]] - cy[sg[0]]) / ds if ds > 0 else float("inf")

    while len(segs) > 1:
        j = min(range(len(segs)), key=lambda i: thickness(segs[i]))
        if thickness(segs[j]) >= min_thickness_ft:
            break
        cands = [i for i in (j - 1, j + 1) if 0 <= i < len(segs)]
        t = min(cands, key=lambda i: abs(slope(segs[i]) - slope(segs[j])))
        lo, hi = sorted((j, t))
        segs[lo:hi + 1] = [[segs[lo][0], segs[hi][1]]]
    units = []
    for a, b in segs:
        st, fl = float(cx[b] - cx[a]), float(cy[b] - cy[a])
        sl = fl / st if st > 0 else float("inf")
        units.append({"top": float(tops[a]), "bottom": float(tops[b]),
                      "thickness": float(cum_h[b] - cum_h[a]),
                      "storage_fraction": st, "flow_fraction": fl, "slope": float(sl),
                      "class": _slope_class(sl)})
    return units


# ---------------------------------------------------------------------------
# Pipeline hook: rock type per log sample (spec section 6)
# ---------------------------------------------------------------------------
SOURCE_CODES = ("core", "log", "x_vsh", "x_phie", "x_perm", "x_nan")
RANGE_MARGIN = 0.5          # log10 units beyond the fitted feature range
DEFAULT_CORE_MAX_DIST = 2.0


def _definition_sets(rt) -> list:
    """Every set of a resolved ``rock_types`` dict: the well's set, then the zone sets."""
    if not rt:
        return []
    sets = [rt.get("set")] + list((rt.get("zone_sets") or {}).values())
    return [s for s in sets if s]


def rock_typing_unavailable(p) -> Optional[str]:
    """Why ``PERM_RT`` cannot be the primary permeability, or None when it can."""
    rt = p.get("rock_types")
    if not p.get("rock_typing_enabled"):
        return "rock typing is off"
    if not _definition_sets(rt):
        return "no rock-type definitions are applied"
    if any(v is None for s in _definition_sets(rt) for v in (s.get("fzi") or [None])):
        return "a rock type has no representative FZI"
    return None


def _zone_groups(zone, index, rt) -> List[Tuple[np.ndarray, dict]]:
    """``[(sample mask, set)]``: the zone's set where there is one, else the well's set."""
    base = rt.get("set") or {}
    zsets = rt.get("zone_sets") or {}
    n = len(index)
    if zone is None or not zsets:
        return [(np.ones(n, dtype=bool), base)]
    if isinstance(zone, str):
        return [(np.ones(n, dtype=bool), zsets.get(zone) or base)]
    codes, names = pd.factorize(np.asarray(zone, dtype=object))
    groups = [(codes == i, zsets.get(z) or base) for i, z in enumerate(names)]
    if (codes < 0).any():
        groups.append((codes < 0, base))        # unlabelled samples take the well's set
    return groups


def _nearest_core(depth, core_depth, core_rt, max_dist):
    """``(label, hit)`` per sample: the rock type of the nearest core sample within ``max_dist``."""
    n = len(depth)
    if not len(core_depth):
        return np.zeros(n, dtype=int), np.zeros(n, dtype=bool)
    order = np.argsort(core_depth, kind="stable")
    cd, cr = core_depth[order], core_rt[order]
    with np.errstate(invalid="ignore"):
        pos = np.searchsorted(cd, depth)
        left = np.clip(pos - 1, 0, len(cd) - 1)
        right = np.clip(pos, 0, len(cd) - 1)
        dl, dr = np.abs(depth - cd[left]), np.abs(depth - cd[right])
        use_right = dr < dl
        near = np.where(use_right, right, left)
        dist = np.where(use_right, dr, dl)
        hit = np.isfinite(dist) & (dist <= max_dist)
    return np.where(hit, cr[near], 0).astype(int), hit


def apply_rock_types(calc, data, p, vsh, zone=None, warnings=None) -> None:
    """Rock type per log sample onto ``calc.results`` (pipeline hook, spec 6.1 to 6.4).

    Does nothing unless ``p["rock_typing_enabled"]`` and ``p["rock_types"]`` (the definitions
    resolved for the well by ``AppModel.params_for_well``) are set. ``zone`` is a zone name
    (a zone segment), a Series of zone labels aligned with ``data`` (several zones), or None;
    the zone's set is used where ``zone_sets`` has one, else the well's ``set``.

    Columns: RQI, FZI (um, where defined), ROCK_TYPE (int, 0 = unassigned), ROCK_TYPE_SOURCE
    (core / log / x_vsh / x_phie / x_perm / x_nan), RT_MARGIN (log10 units to the nearest
    boundary); PERM_RT when ``perm_primary`` is "Rock type" or ``settings.perm_rt_column``;
    R35 (um) when ``settings.r35_column``. Eligibility priority: x_vsh, x_phie, x_perm, x_nan.
    A core label replaces the log class of an eligible sample within ``core_max_dist`` of a
    labelled core sample. ``calc.rock_type_info`` (DataFrame: log_rt, outside) feeds the summary.
    """
    rt = p.get("rock_types")
    if not p.get("rock_typing_enabled") or not rt or not _definition_sets(rt):
        return
    s = _settings(rt.get("settings"))
    index = data.index
    n = len(index)
    res = calc.results
    phie = np.asarray(res["PHIE"], dtype=float) if "PHIE" in res else np.full(n, np.nan)
    log_col = "PERM_WR" if p.get("rt_log_perm") == "Wyllie-Rose" else "PERM_TIMUR"
    k = np.asarray(res[log_col], dtype=float) if log_col in res else np.full(n, np.nan)
    vsh_a = np.asarray(vsh, dtype=float)

    rq, fz = rqi(k, phie), fzi(k, phie)
    with np.errstate(invalid="ignore", divide="ignore"):
        feature = np.log10(winland_r35(k, phie) if rt.get("method") == "r35" else fz)

    source = np.full(n, "", dtype=object)
    reservoir_only = bool(s["reservoir_only"])
    with np.errstate(invalid="ignore"):
        source[reservoir_only & ~np.isfinite(vsh_a)] = "x_nan"
        source[~np.isfinite(k) | (k <= PERM_CLIP[0]) | (k >= PERM_CLIP[1])] = "x_perm"
        source[~np.isfinite(phie) | (phie < s["min_phie"])] = "x_phie"
        source[reservoir_only & (vsh_a >= float(p.get("vsh_cutoff", 0.4)))] = "x_vsh"
    source[(source == "") & ~np.isfinite(feature)] = "x_nan"
    eligible = source == ""

    groups = _zone_groups(zone, index, rt)
    rock = np.zeros(n, dtype=int)
    margin = np.full(n, np.nan)
    outside = np.zeros(n, dtype=bool)
    for mask, rset in groups:
        sel = mask & eligible
        if not sel.any():
            continue
        r, m = classify(feature[sel], rset)
        rock[sel], margin[sel] = r, m
        rng = rset.get("feature_range")
        if rng:
            outside[sel] = (feature[sel] < rng[0] - RANGE_MARGIN) | (feature[sel] > rng[1] + RANGE_MARGIN)
    log_rt = rock.copy()
    source[eligible] = "log"

    core = p.get("rock_core") or {}
    core_depth = np.asarray(core.get("depth") or [], dtype=float)
    core_rt = np.asarray(core.get("rt") or [], dtype=int)
    if s["use_core_labels"] and len(core_depth) and "DEPTH" in data.columns:
        label, hit = _nearest_core(np.asarray(data["DEPTH"], dtype=float), core_depth, core_rt,
                                   float(rt.get("core_max_dist") or DEFAULT_CORE_MAX_DIST))
        hit &= eligible & (label > 0)
        rock[hit] = label[hit]
        source[hit] = "core"
    if warnings is not None and not len(core_depth):
        warnings.add("ROCK_TYPES_UNCORED",
                     "No core labels for this well: rock types are log-derived with the "
                     "project definitions.")

    out = {"RQI": rq, "FZI": fz, "ROCK_TYPE": rock, "ROCK_TYPE_SOURCE": source,
           "RT_MARGIN": margin}
    if p.get("perm_primary") == "Rock type" or s.get("perm_rt_column"):
        fz_rt = np.full(n, np.nan)
        for mask, rset in groups:
            table = np.array([np.nan if v is None else float(v) for v in (rset.get("fzi") or [])])
            sel = mask & (rock > 0) & (rock <= len(table))
            fz_rt[sel] = table[rock[sel] - 1]
        with np.errstate(invalid="ignore"):
            out["PERM_RT"] = np.where(rock > 0, perm_from_fzi(fz_rt, phie), np.nan)
    if s["r35_column"]:
        out["R35"] = winland_r35(k, phie)
    for name, values in out.items():
        res[name] = pd.Series(values, index=index)
    calc.rock_type_info = pd.DataFrame({"log_rt": log_rt, "outside": outside}, index=index)


def _positive_geomean(values) -> Optional[float]:
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v) & (v > 0)]
    return float(np.exp(np.mean(np.log(v)))) if len(v) else None


def rock_type_rows(results, vsh, phie, sw, dz, labels, rt, info=None, perm_col="PERM_TIMUR",
                   hcpv_col="dHCPV_NET_PAY") -> dict:
    """``summary["rock_types"]``: pay, HCPV and counts per rock type (spec 6.5).

    ``results`` is the run's result frame (flags, ROCK_TYPE, ROCK_TYPE_SOURCE, RT_MARGIN,
    ``hcpv_col``); ``vsh``/``phie``/``sw`` the series the pay flags were made from; ``dz`` the
    per-sample thickness (array or scalar, as for the well totals); ``labels`` the zone labels
    or None; ``rt`` the resolved definitions; ``info`` the concatenated
    ``calc.rock_type_info``; ``perm_col`` the primary permeability column.
    Every sample is in exactly one of ``by_rt`` and ``unassigned``, so the sums of net pay and
    HCPV over both equal the well totals. ``pct_core`` is a percentage of the group's samples.
    """
    s = _settings(rt.get("settings"))
    n = len(results)
    rock = np.asarray(results["ROCK_TYPE"].fillna(0), dtype=int)
    source = np.asarray(results["ROCK_TYPE_SOURCE"].fillna("x_nan"), dtype=object)
    margin = np.asarray(results["RT_MARGIN"], dtype=float)
    gross, res_f, pay_f = (np.asarray(results[c]).astype(bool)
                           for c in ("GROSS_SAND_FLAG", "NET_RES_FLAG", "NET_PAY_FLAG"))
    vsh_a, phie_a, sw_a = (np.asarray(x, dtype=float) for x in (vsh, phie, sw))
    dz_a = np.broadcast_to(np.asarray(dz, dtype=float), (n,))
    dh = (np.asarray(results[hcpv_col], dtype=float) if hcpv_col in results.columns
          else np.zeros(n))
    perm = (np.asarray(results[perm_col], dtype=float) if perm_col in results.columns
            else np.full(n, np.nan))
    base = rt.get("set") or {}
    zsets = rt.get("zone_sets") or {}
    n_types = max([int(x.get("n_rt") or len(x.get("fzi") or [])) for x in _definition_sets(rt)]
                  + [0])

    def measures(mask, code, rset):
        row = {"rt": int(code), "samples": int(mask.sum())}
        row.update(pay_summary(gross[mask], res_f[mask], pay_f[mask], vsh_a[mask], phie_a[mask],
                               sw_a[mask], dz_a[mask]))
        row["hcpv_net_pay"] = float(dh[mask].sum())
        row["perm_geomean"] = _positive_geomean(perm[mask & pay_f])
        fzi_list = (rset or {}).get("fzi") or []
        row["fzi"] = (float(fzi_list[code - 1])
                      if 1 <= code <= len(fzi_list) and fzi_list[code - 1] is not None else None)
        count = int(mask.sum())
        row["pct_core"] = float(100.0 * (mask & (source == "core")).sum() / count) if count else 0.0
        return row

    by_rt = [measures(rock == c, c, base) for c in range(1, n_types + 1)]
    unassigned = measures(rock == 0, 0, None)
    by_zone = []
    if labels is not None:
        zl = np.asarray(labels, dtype=object)
        depth = np.asarray(results["DEPTH"], dtype=float) if "DEPTH" in results.columns else None
        zones = list(pd.unique(zl[pd.notna(zl)]))
        if depth is not None:
            zones.sort(key=lambda z: np.nanmin(depth[zl == z]))
        for z in zones:
            zmask = zl == z
            for c in sorted(set(rock[zmask].tolist())):
                row = {"zone": z}
                row.update(measures(zmask & (rock == c), c, zsets.get(z) or base))
                by_zone.append(row)
    assigned = rock > 0
    counts = {c: int((source == c).sum()) for c in SOURCE_CODES}
    with np.errstate(invalid="ignore"):
        counts["near_boundary"] = int((assigned & (margin < s["margin_min"])).sum())
    counts["outside_range"] = int(info["outside"].sum()) if info is not None else 0
    counts["perm_rt_missing"] = 0
    if "PERM_RT" in results.columns:
        counts["perm_rt_missing"] = int(
            (assigned & ~np.isfinite(np.asarray(results["PERM_RT"], dtype=float))).sum())

    agree = {"n": 0, "fraction": None, "confusion": [[0] * n_types for _ in range(n_types)]}
    if info is not None and n_types:
        log_rt = np.asarray(info["log_rt"], dtype=int)
        sel = ((source == "core") & (log_rt >= 1) & (rock >= 1)
               & (rock <= n_types) & (log_rt <= n_types))
        if sel.any():
            flat = np.bincount((rock[sel] - 1) * n_types + (log_rt[sel] - 1),
                               minlength=n_types * n_types)
            agree["confusion"] = flat.reshape(n_types, n_types).astype(int).tolist()
            agree["n"] = int(sel.sum())
            agree["fraction"] = float((rock[sel] == log_rt[sel]).mean())

    notes = [str(rt["basis"])] if rt.get("basis") else []
    if counts["core"] == 0:
        notes.append("Rock types are log-derived with the project definitions (no core label used).")
    out = {"method": rt.get("method", "fzi"), "fit_scope": rt.get("fit_scope"),
           "basis": rt.get("basis"), "by_rt": by_rt, "unassigned": unassigned,
           "by_zone_rt": by_zone, "counts": counts, "agreement": agree, "notes": notes}
    if s["lorenz"]:
        pick = res_f & np.isfinite(perm) & np.isfinite(phie_a)
        depth = (np.asarray(results["DEPTH"], dtype=float) if "DEPTH" in results.columns
                 else np.arange(n, dtype=float))
        coefficient = lorenz_coefficient(phie_a[pick], perm[pick], dz_a[pick])
        out["lorenz"] = {
            "basis": perm_col,
            "coefficient": float(coefficient) if np.isfinite(coefficient) else None,
            "units": smlp_units(smlp(depth[pick], phie_a[pick], perm[pick], dz_a[pick]))}
    return out


# ---------------------------------------------------------------------------
# Rock type of loose (phi, k) pairs, e.g. Pc samples
# ---------------------------------------------------------------------------
def rock_types_zone_scoped(rt) -> bool:
    """True when the definitions were fitted per zone, so rock-type ids are not global."""
    return bool(rt) and rt.get("fit_scope") == "zone"


def classify_pairs(phi, k, rt, zone=None) -> Tuple[np.ndarray, np.ndarray]:
    """Rock type of (porosity, permeability) pairs with the project definitions.

    ``phi`` is a fraction and ``k`` is mD (core-plug values as measured); ``rt`` is the
    resolved ``rock_types`` dict (``method``, ``set``, ``zone_sets``, ``settings``). The
    ``ob_phi_factor`` / ``ob_k_factor`` overburden factors are applied exactly as in
    :func:`build_core_table`, and the feature is log10 FZI (log10 R35 for the r35 method)
    classified by :func:`classify`. ``zone`` is one zone name or one label per pair; the zone's
    set is used where ``zone_sets`` has one, else the well's ``set``.

    Returns ``(labels, reasons)``: the rock type (``0`` = unassigned) and, per pair, ``"ok"`` or
    the first failing reason of ``phi_out_of_range``, ``perm_not_positive``, ``no_perm``,
    ``no_porosity`` (the same priority as :func:`build_core_table`). With zone-scoped
    definitions (:func:`rock_types_zone_scoped`) the ids are not comparable across zones.
    """
    phi, k = np.atleast_1d(_arr(phi)), np.atleast_1d(_arr(k))
    if phi.shape != k.shape:
        raise ValueError("phi and k must have the same length")
    n = len(phi)
    s = _settings((rt or {}).get("settings"))
    status = np.full(n, STATUS_OK, dtype=object)
    with np.errstate(invalid="ignore"):
        bad = {
            "phi_out_of_range": np.isfinite(phi) & ((phi <= s["core_phi_min"]) | (phi > s["core_phi_max"])),
            "perm_not_positive": np.isfinite(k) & (k <= 0),
            "no_perm": ~np.isfinite(k),
            "no_porosity": ~np.isfinite(phi),
        }
    for reason in ("phi_out_of_range", "perm_not_positive", "no_perm", "no_porosity"):
        status[bad[reason]] = reason
    phi_used, k_used = phi * float(s["ob_phi_factor"]), k * float(s["ob_k_factor"])
    ok = status == STATUS_OK
    feature = np.full(n, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        if (rt or {}).get("method") == "r35":
            feature[ok] = np.log10(winland_r35(k_used[ok], phi_used[ok]))
        else:
            feature[ok] = np.log10(fzi(k_used[ok], phi_used[ok]))
    status[ok & ~np.isfinite(feature)] = "phi_out_of_range"      # a factor pushed phi to >= 1
    labels = np.zeros(n, dtype=int)
    if not _definition_sets(rt):
        return labels, status
    for mask, rset in _zone_groups(zone, pd.RangeIndex(n), rt):
        sel = mask & (status == STATUS_OK)
        if sel.any():
            labels[sel] = classify(feature[sel], rset)[0]
    return labels, status
