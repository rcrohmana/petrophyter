"""Monte Carlo uncertainty on HCPV and pay: distributions, sampling, kernel, statistics, tornado.

Pure module: numpy, scipy and pandas only, never Qt. Parameters (a, m, n, Rw, Rsh and the three
cutoffs) become distributions defined once for the project. A realisation draws one perturbation per
parameter and applies it to the resolved value of every well and zone segment, so the scopes,
presets and auto estimates the resolver produced are kept. The deterministic results and summary
are never touched.

Convention: P90 is the low case (exceeded with 90 % probability), P10 the high case.
"""

from __future__ import annotations

import math
import time
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

from modules.issue_codes import IssueLog
from modules.las_utils import mask_nonpositive
from modules.petrophysics import PetrophysicsCalculator, depth_increments, pay_summary
from modules.pipeline import (
    PARAM_DEFAULTS, PipelineError, _filter_formations, _primary_sw, run_pipeline,
)

# Canonical parameter order: sampling columns follow this order, never the UI order.
PARAM_ORDER: Tuple[str, ...] = ("a", "m", "n", "rw", "rsh", "vsh_cutoff", "phi_cutoff", "sw_cutoff")

# Parameters that act on the saturation stage (class S) and on the pay flags only (class C).
SATURATION_PARAMS = ("a", "m", "n", "rw", "rsh")
CUTOFF_PARAMS = ("vsh_cutoff", "phi_cutoff", "sw_cutoff")

# Default perturbation mode: relative for positive, skewed quantities, additive otherwise.
DEFAULT_MODES: Dict[str, str] = {
    "a": "relative", "m": "additive", "n": "additive", "rw": "relative", "rsh": "relative",
    "vsh_cutoff": "additive", "phi_cutoff": "additive", "sw_cutoff": "additive",
}

# Hard physical bounds applied after perturbation, per segment. (low, high, low_open, high_open):
# an open end excludes the bound itself (a cutoff of 0 means nothing passes).
BOUNDS: Dict[str, Tuple[float, float, bool, bool]] = {
    "a": (0.1, 5.0, False, False),
    "m": (1.0, 4.0, False, False),
    "n": (1.0, 4.0, False, False),
    "rw": (1e-3, 100.0, False, False),
    "rsh": (0.05, 5000.0, False, False),
    "vsh_cutoff": (0.0, 1.0, True, False),
    "phi_cutoff": (0.0, 0.5, False, False),
    "sw_cutoff": (0.0, 1.0, True, False),
}

# Triangular [low, mid, high] offsets the "Suggested ranges" button fills (fractions for relative).
SUGGESTED_RANGES: Dict[str, Tuple[float, float, float]] = {
    "a": (-0.10, 0.0, 0.10),
    "m": (-0.15, 0.0, 0.15),
    "n": (-0.20, 0.0, 0.20),
    "rw": (-0.20, 0.0, 0.25),
    "rsh": (-0.20, 0.0, 0.25),
    "vsh_cutoff": (-0.05, 0.0, 0.05),
    "phi_cutoff": (-0.02, 0.0, 0.02),
    "sw_cutoff": (-0.05, 0.0, 0.05),
}

KINDS = ("triangular", "normal", "uniform")
MODES = ("relative", "additive")
SAMPLINGS = ("lhs", "random")

N_MIN, N_MAX = 50, 5000
DEFAULT_N = 300        # owner rule: 500 unless the 10-well Simandoux varying-n run exceeds 30 s
DEFAULT_SEED = 12345
NORMAL_TRUNCATION_SD = 3.0
CONVERGENCE_TOLERANCE = 0.02   # half-sample percentiles within 2 % of P50

# Inputs held at their base value in every realisation (stated in the result header and exports).
NOT_VARIED = "porosity, shale point, GR baseline"


@dataclass
class Distribution:
    """One parameter's perturbation; offsets are fractions (relative) or absolute units (additive)."""

    name: str
    enabled: bool = False
    kind: str = "triangular"     # "triangular" | "normal" | "uniform"
    mode: str = "relative"       # "relative" | "additive"
    low: float = 0.0             # triangular/uniform lower offset; normal: unused
    mid: float = 0.0             # triangular mode offset; normal: mean offset
    high: float = 0.0            # triangular/uniform upper offset
    sd: float = 0.0              # normal only (truncated at +/- NORMAL_TRUNCATION_SD)


def default_distributions() -> Dict[str, Distribution]:
    """Every parameter, disabled, with its default mode."""
    return {name: Distribution(name=name, mode=DEFAULT_MODES[name]) for name in PARAM_ORDER}


@dataclass
class UncertaintyConfig:
    n: int = DEFAULT_N
    seed: int = DEFAULT_SEED
    sampling: str = "lhs"
    distributions: Dict[str, Distribution] = field(default_factory=default_distributions)
    # Pairwise rank correlation applied by a Gaussian copula, keyed by a pair in PARAM_ORDER order.
    correlations: Dict[Tuple[str, str], float] = field(default_factory=dict)

    def enabled_names(self) -> Tuple[str, ...]:
        """Enabled parameters in canonical order."""
        return tuple(n for n in PARAM_ORDER
                     if n in self.distributions and self.distributions[n].enabled)


# ---------------------------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------------------------

def _copula_matrix(cfg: UncertaintyConfig, names: Tuple[str, ...]) -> np.ndarray:
    """Gaussian-copula correlation matrix for the requested Spearman rhos.

    A Gaussian copula with Pearson rho_g has Spearman 6/pi * asin(rho_g / 2), so the requested
    rank correlation is converted with rho_g = 2 sin(pi * rho / 6).
    """
    idx = {n: i for i, n in enumerate(names)}
    k = len(names)
    r = np.eye(k)
    for (a, b), rho in cfg.correlations.items():
        if a in idx and b in idx and a != b:
            g = 2.0 * math.sin(math.pi * float(rho) / 6.0)
            r[idx[a], idx[b]] = r[idx[b], idx[a]] = g
    return r


def _is_pd(r: np.ndarray) -> bool:
    try:
        np.linalg.cholesky(r)
        return True
    except np.linalg.LinAlgError:
        return False


def validate_config(cfg: UncertaintyConfig) -> List[str]:
    """Return a list of human-readable errors; empty when the configuration can run."""
    errors: List[str] = []
    names = cfg.enabled_names()
    if not names:
        errors.append("Enable at least one parameter distribution.")
    try:
        n_ok = N_MIN <= int(cfg.n) <= N_MAX
    except (TypeError, ValueError):
        n_ok = False
    if not n_ok:
        errors.append(f"Number of realisations must be between {N_MIN} and {N_MAX}.")
    if cfg.sampling not in SAMPLINGS:
        errors.append(f"Unknown sampling '{cfg.sampling}'.")
    for name in names:
        d = cfg.distributions[name]
        ok_kind = d.kind in KINDS
        if not ok_kind:
            errors.append(f"{name}: unknown distribution kind '{d.kind}'.")
        if d.mode not in MODES:
            errors.append(f"{name}: unknown mode '{d.mode}'.")
        if not ok_kind:
            continue
        vals = (d.low, d.mid, d.high, d.sd)
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in vals):
            errors.append(f"{name}: distribution values must be finite numbers.")
        elif d.kind == "triangular" and not (d.low <= d.mid <= d.high):
            errors.append(f"{name}: triangular needs low <= mode <= high.")
        elif d.kind == "uniform" and not (d.low <= d.high):
            errors.append(f"{name}: uniform needs low <= high.")
        elif d.kind == "normal" and d.sd < 0:
            errors.append(f"{name}: normal needs sd >= 0.")
    corr_ok = True
    for key, rho in cfg.correlations.items():
        try:
            a, b = key
        except (TypeError, ValueError):
            errors.append(f"Invalid correlation key {key!r}.")
            corr_ok = False
            continue
        if a not in names or b not in names or a == b:
            errors.append(f"Correlation {a}-{b}: both parameters must be enabled and different.")
            corr_ok = False
        elif not (isinstance(rho, (int, float)) and abs(rho) < 1):
            errors.append(f"Correlation {a}-{b}: |rho| must be below 1.")
            corr_ok = False
    if corr_ok and cfg.correlations and names:
        if not _is_pd(_copula_matrix(cfg, names)):
            errors.append("Correlation matrix is not positive definite.")
    return errors


# ---------------------------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------------------------

@dataclass
class ParamDraws:
    """Perturbation draws for the enabled parameters.

    offsets: (n, k) perturbation offsets (fractions or absolute units per mode), not applied values.
    uniforms: (n, k) uniforms fed to the marginals (after the copula when correlations are set;
        for lhs without correlations each column hits every one of the n strata exactly once).
    """

    names: Tuple[str, ...]
    offsets: np.ndarray
    uniforms: np.ndarray


def marginal_quantile(dist: Distribution, q):
    """Offset at quantile q (scalar or array) of one distribution; zero width gives a constant."""
    q = np.asarray(q, dtype=float)
    if dist.kind == "triangular":
        scale = dist.high - dist.low
        if scale <= 0:
            return np.full(q.shape, float(dist.low)) if q.ndim else float(dist.low)
        c = min(max((dist.mid - dist.low) / scale, 0.0), 1.0)
        out = stats.triang.ppf(q, c, loc=dist.low, scale=scale)
    elif dist.kind == "normal":
        if dist.sd <= 0:
            return np.full(q.shape, float(dist.mid)) if q.ndim else float(dist.mid)
        t = NORMAL_TRUNCATION_SD
        out = stats.truncnorm.ppf(q, -t, t, loc=dist.mid, scale=dist.sd)
    elif dist.kind == "uniform":
        out = dist.low + q * (dist.high - dist.low)
    else:
        raise ValueError(f"Unknown distribution kind '{dist.kind}'.")
    return out if q.ndim else float(out)


def sample_parameters(cfg: UncertaintyConfig, n: Optional[int] = None,
                      seed: Optional[int] = None) -> ParamDraws:
    """Draw perturbation offsets for the enabled parameters; identical (cfg, seed) is bit-identical."""
    names = cfg.enabled_names()
    k = len(names)
    n = int(cfg.n if n is None else n)
    seed = cfg.seed if seed is None else seed
    if k == 0:
        raise ValueError("No enabled distribution to sample.")
    if cfg.sampling not in SAMPLINGS:
        raise ValueError(f"Unknown sampling '{cfg.sampling}'.")
    rng = np.random.default_rng(seed)
    if cfg.sampling == "lhs":
        u = stats.qmc.LatinHypercube(d=k, seed=rng).random(n)
    else:
        u = rng.random((n, k))
    eps = 1e-12
    u = np.clip(u, eps, 1.0 - eps)
    if cfg.correlations:
        r = _copula_matrix(cfg, names)
        try:
            chol = np.linalg.cholesky(r)
        except np.linalg.LinAlgError:
            raise ValueError("Correlation matrix is not positive definite.") from None
        z = stats.norm.ppf(u) @ chol.T
        u = np.clip(stats.norm.cdf(z), eps, 1.0 - eps)
    offsets = np.empty((n, k), dtype=float)
    for j, name in enumerate(names):
        offsets[:, j] = marginal_quantile(cfg.distributions[name], u[:, j])
    return ParamDraws(names=names, offsets=offsets, uniforms=u)


def apply_offset(name: str, base, offset, mode: str):
    """Apply a perturbation to base and clip to the hard bounds.

    Returns (value, clipped) vectorised over arrays; clipped is a boolean array (or bool for scalars)
    that is True where the unclipped value left the bounds. Open ends map to the nearest
    representable value inside the bound.
    """
    if mode == "relative":
        raw = np.asarray(base, dtype=float) * (1.0 + np.asarray(offset, dtype=float))
    elif mode == "additive":
        raw = np.asarray(base, dtype=float) + np.asarray(offset, dtype=float)
    else:
        raise ValueError(f"Unknown mode '{mode}'.")
    low, high, low_open, high_open = BOUNDS[name]
    lo = float(np.nextafter(low, np.inf)) if low_open else float(low)
    hi = float(np.nextafter(high, -np.inf)) if high_open else float(high)
    clipped = (raw < lo) | (raw > hi)
    value = np.clip(raw, lo, hi)
    if value.ndim == 0:
        return float(value), bool(clipped)
    return value, clipped


# ---------------------------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------------------------

def exceedance_stats(values, zero_mask=None) -> Dict[str, float]:
    """P90/P50/P10 (exceedance convention), moments and zero probability of a realisation vector.

    P90 = 10th percentile (low case), P10 = 90th percentile (high case). NaN excluded.
    prob_zero: share of finite values equal to 0, or the mean of zero_mask when given.
    """
    x = np.asarray(values, dtype=float).ravel()
    fin = x[np.isfinite(x)]
    nv = int(fin.size)
    out: Dict[str, float] = {"n": int(x.size), "n_valid": nv}
    if nv == 0:
        for key in ("p90", "p50", "p10", "mean", "std", "min", "max"):
            out[key] = float("nan")
        out["prob_zero"] = float("nan")
    else:
        out["p90"] = float(np.percentile(fin, 10))
        out["p50"] = float(np.percentile(fin, 50))
        out["p10"] = float(np.percentile(fin, 90))
        out["mean"] = float(fin.mean())
        out["std"] = float(fin.std(ddof=1)) if nv > 1 else 0.0
        out["min"] = float(fin.min())
        out["max"] = float(fin.max())
        out["prob_zero"] = float(np.mean(fin == 0.0))
    if zero_mask is not None:
        zm = np.asarray(zero_mask, dtype=bool).ravel()
        out["prob_zero"] = float(zm.mean()) if zm.size else float("nan")
    return out


def convergence_warning(values, tol: float = CONVERGENCE_TOLERANCE) -> Optional[str]:
    """Warn when P90/P50/P10 of the first and second half differ by more than tol * |P50|."""
    x = np.asarray(values, dtype=float).ravel()
    n = int(x.size)
    h = n // 2
    a, b = x[:h], x[h:]
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    if a.size < 2 or b.size < 2:
        return None
    p50 = np.percentile(x[np.isfinite(x)], 50)
    limit = max(tol * abs(p50), 1e-9)
    for q in (10, 50, 90):
        if abs(np.percentile(a, q) - np.percentile(b, q)) > limit:
            return f"Percentiles not converged at N = {n}; increase N"
    return None


def tornado_rows(base_value: float, outputs: Dict[str, Tuple[float, float, float, float]]
                 ) -> List[Dict[str, Any]]:
    """One row per parameter, sorted by swing descending (NaN swings last)."""
    rows = []
    for name, (at_low, at_high, low_in, high_in) in outputs.items():
        swing = abs(at_high - at_low)
        vals = [v for v in (at_low, at_high) if np.isfinite(v)]
        rows.append({
            "name": name, "low_input": low_in, "high_input": high_in,
            "at_low_input": at_low, "at_high_input": at_high,
            "bar_min": min(vals) if vals else float("nan"),
            "bar_max": max(vals) if vals else float("nan"),
            "swing": float(swing), "base": base_value,
        })
    rows.sort(key=lambda r: (not np.isfinite(r["swing"]), -r["swing"] if np.isfinite(r["swing"]) else 0.0))
    return rows


def rank_correlations(offsets, names, output) -> Dict[str, float]:
    """Spearman rank correlation of each offset column with the output; NaN-safe."""
    off = np.asarray(offsets, dtype=float)
    y = np.asarray(output, dtype=float).ravel()
    res: Dict[str, float] = {}
    for j, name in enumerate(names):
        x = off[:, j]
        m = np.isfinite(x) & np.isfinite(y)
        if m.sum() < 3 or np.ptp(x[m]) == 0 or np.ptp(y[m]) == 0:
            res[name] = float("nan")
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            rho = stats.spearmanr(x[m], y[m])[0]
        res[name] = float(rho)
    return res


# ---------------------------------------------------------------------------------------------
# Session (de)serialisation
# ---------------------------------------------------------------------------------------------

def config_to_dict(cfg: UncertaintyConfig) -> Dict[str, Any]:
    """JSON-safe dict; correlations become a list of [a, b, rho]."""
    return {
        "n": int(cfg.n), "seed": int(cfg.seed), "sampling": cfg.sampling,
        "distributions": {
            name: {"enabled": bool(d.enabled), "kind": d.kind, "mode": d.mode,
                   "low": float(d.low), "mid": float(d.mid), "high": float(d.high), "sd": float(d.sd)}
            for name, d in cfg.distributions.items()
        },
        "correlations": [[a, b, float(r)] for (a, b), r in cfg.correlations.items()],
    }


def _num(v, default):
    try:
        f = float(v)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def config_from_dict(d: Optional[Dict[str, Any]]) -> UncertaintyConfig:
    """Tolerant inverse of config_to_dict: unknown or missing fields fall back to defaults."""
    cfg = UncertaintyConfig()
    if not isinstance(d, dict):
        return cfg
    n = int(_num(d.get("n"), cfg.n))
    cfg.n = n if N_MIN <= n <= N_MAX else cfg.n
    cfg.seed = int(_num(d.get("seed"), cfg.seed))
    if d.get("sampling") in SAMPLINGS:
        cfg.sampling = d["sampling"]
    dists = d.get("distributions")
    if isinstance(dists, dict):
        for name in PARAM_ORDER:
            src = dists.get(name)
            if not isinstance(src, dict):
                continue
            dist = cfg.distributions[name]
            dist.enabled = src.get("enabled") is True
            if src.get("kind") in KINDS:
                dist.kind = src["kind"]
            if src.get("mode") in MODES:
                dist.mode = src["mode"]
            for f in ("low", "mid", "high", "sd"):
                setattr(dist, f, _num(src.get(f), getattr(dist, f)))
    corr = d.get("correlations")
    if isinstance(corr, (list, tuple)):
        for item in corr:
            try:
                a, b, r = item
                r = float(r)
                if a in PARAM_ORDER and b in PARAM_ORDER and a != b and abs(r) < 1.0:
                    key = (a, b) if PARAM_ORDER.index(a) < PARAM_ORDER.index(b) else (b, a)
                    cfg.correlations[key] = r
            except (TypeError, ValueError):
                continue
    return cfg


# ---------------------------------------------------------------------------------------------
# Kernel: freeze a well once, evaluate any number of realisations
# ---------------------------------------------------------------------------------------------

METRICS: Tuple[str, ...] = ("hcpv_net_pay", "hcpv_net_res", "net_pay", "net_res",
                            "avg_phie_pay", "avg_sw_pay", "phih_pay")
TORNADO_METRICS: Tuple[str, ...] = ("hcpv_net_pay", "net_pay")
TORNADO_QUANTILES = (0.10, 0.90)


class UncertaintyExcluded(Exception):
    """A well that cannot be evaluated (no RT, no PHIE, pipeline failure); str() is the reason."""


@dataclass
class _Segment:
    """One saturation segment: its samples, resolved parameters and a private calculator."""

    positions: np.ndarray
    params: Dict[str, Any]
    rw: float
    rsh: float
    rsh_auto: bool
    tctx: Any
    has_rt: bool
    data: pd.DataFrame
    vsh_s: pd.Series
    vsh: np.ndarray
    phie: np.ndarray
    calc: PetrophysicsCalculator
    sw_base: Optional[np.ndarray] = None


@dataclass
class FrozenWell:
    """Everything one well needs for any number of realisations.

    ``base_summary`` is the summary of the base ``run_pipeline`` call (the deterministic column).
    ``zones`` are the zone labels in depth order. The remaining fields are internals; each
    segment holds its own calculator, so one FrozenWell must not be evaluated from two threads.
    """

    key: str
    name: str
    base_summary: dict
    zones: list
    segments: list = field(default_factory=list, repr=False)
    dz: Any = field(default=None, repr=False)
    vsh: Any = field(default=None, repr=False)
    phie: Any = field(default=None, repr=False)
    zone_idx: Dict[str, np.ndarray] = field(default_factory=dict, repr=False)
    curve_mapping: Dict[str, str] = field(default_factory=dict, repr=False)


def _primary_sw_values(seg: _Segment, frozen_mapping, sp, rw, rsh, warn) -> np.ndarray:
    sw, _, _, _ = _primary_sw(seg.calc, seg.data, frozen_mapping, sp, seg.vsh_s, rw, rsh,
                              seg.tctx, warn, seg.rsh_auto, only_primary=True)
    return np.asarray(sw, dtype=float)


def freeze_well(key, name, data, curve_mapping, params, formation_tops=None) -> FrozenWell:
    """Run the pipeline once with capture and keep what any realisation needs.

    Raises UncertaintyExcluded when the well cannot be evaluated: no RT, no PHIE, or a
    pipeline failure. Inputs are not modified.
    """
    capture: list = []
    try:
        results, summary = run_pipeline(data, curve_mapping, params, None, formation_tops,
                                        capture=capture)
    except PipelineError as exc:
        raise UncertaintyExcluded(f"analysis failed: {exc}") from exc
    if not capture or not any(b.has_rt for b in capture):
        raise UncertaintyExcluded("no RT curve")
    if not any(np.isfinite(b.phie).any() for b in capture):
        raise UncertaintyExcluded("no effective porosity (PHIE)")

    # The data the pipeline's segments saw: non-positive resistivity, density and slowness are
    # NaN, then the formation filter (positions in the capture refer to these rows).
    p = {**PARAM_DEFAULTS, **params}
    filt = data.copy()
    for logical in ("RT", "RHOB", "DT"):
        mask_nonpositive(filt, [curve_mapping.get(logical, logical)])
    filt = _filter_formations(filt, p, formation_tops)
    n = len(filt)
    if n != len(results):
        raise UncertaintyExcluded("internal: sample count differs from the pipeline result")

    if "DEPTH" in filt.columns:
        dz = depth_increments(filt["DEPTH"]).to_numpy(dtype=float)
    else:
        dz = np.full(n, 0.1)

    vsh_all = np.full(n, np.nan)
    phie_all = np.full(n, np.nan)
    segments: List[_Segment] = []
    for b in capture:
        seg_data = filt.iloc[b.positions]
        calc = PetrophysicsCalculator(seg_data)
        calc.results["PHIE"] = pd.Series(b.phie, index=seg_data.index)
        calc.results["PHIT"] = pd.Series(b.phit, index=seg_data.index)
        seg = _Segment(
            positions=np.asarray(b.positions, dtype=np.intp), params=dict(b.params),
            rw=b.rw, rsh=b.rsh, rsh_auto=bool(b.rsh_auto), tctx=b.tctx, has_rt=bool(b.has_rt),
            data=seg_data, vsh_s=pd.Series(b.vsh, index=seg_data.index),
            vsh=np.asarray(b.vsh, dtype=float), phie=np.asarray(b.phie, dtype=float), calc=calc)
        vsh_all[seg.positions] = seg.vsh
        phie_all[seg.positions] = seg.phie
        if seg.has_rt:
            sp = seg.params
            seg.sw_base = _primary_sw_values(seg, curve_mapping, sp, seg.rw, seg.rsh, IssueLog())
        segments.append(seg)

    zones = [row["zone"] for row in summary.get("zones") or []]
    zone_idx: Dict[str, np.ndarray] = {}
    if zones:
        if "ZONE" not in results.columns:
            raise UncertaintyExcluded("internal: zoned summary without a ZONE column")
        labels = results["ZONE"].to_numpy()
        for z in zones:
            zone_idx[z] = np.flatnonzero(labels == z)
    return FrozenWell(key=key, name=name, base_summary=summary, zones=zones, segments=segments,
                      dz=dz, vsh=vsh_all, phie=phie_all, zone_idx=zone_idx,
                      curve_mapping=dict(curve_mapping))


def _scope_metrics(vsh, phie, sw, dz, gross, res, pay, hcpv_pay_d, hcpv_res_d, idx) -> Dict[str, float]:
    """Metrics of one scope (idx None = whole well). pay_summary does the thickness/averages."""
    if idx is None:
        ps = pay_summary(gross, res, pay, vsh, phie, sw, dz)
        # Well level: last value of the cumulative, as the pipeline reads it.
        hp = float(np.cumsum(hcpv_pay_d)[-1]) if hcpv_pay_d.size else 0.0
        hr = float(np.cumsum(hcpv_res_d)[-1]) if hcpv_res_d.size else 0.0
    else:
        ps = pay_summary(gross[idx], res[idx], pay[idx], vsh[idx], phie[idx], sw[idx], dz[idx])
        hp = float(hcpv_pay_d[idx].sum())
        hr = float(hcpv_res_d[idx].sum())
    return {"hcpv_net_pay": hp, "hcpv_net_res": hr, "net_pay": ps["net_pay"],
            "net_res": ps["net_reservoir"], "avg_phie_pay": ps["avg_phie_pay"],
            "avg_sw_pay": ps["avg_sw_pay"], "phih_pay": ps["phih_pay"]}


def evaluate(frozen: FrozenWell, theta: Dict[str, float],
             modes: Optional[Dict[str, str]] = None) -> dict:
    """One realisation. ``theta`` = {name: offset} for the varied parameters (missing = 0).

    ``modes`` ({name: "relative" | "additive"}) defaults to DEFAULT_MODES; run_monte_carlo passes
    the configured modes. Returns {"well": metrics, "zones": {zone: metrics},
    "clipped": {name: bool_any_segment_clipped}}.
    """
    mode_of = {**DEFAULT_MODES, **(modes or {})}
    theta = {k: float(v) for k, v in theta.items() if k in BOUNDS}
    clipped = {k: False for k in theta}
    saturation_varied = any(k in SATURATION_PARAMS for k in theta)
    warn = IssueLog()

    def apply(name, base):
        value, was = apply_offset(name, base, theta[name], mode_of[name])
        if was:
            clipped[name] = True
        return value

    n = len(frozen.dz)
    sw_all = np.full(n, np.nan)
    gross = np.zeros(n, dtype=bool)
    res = np.zeros(n, dtype=bool)
    pay = np.zeros(n, dtype=bool)
    for seg in frozen.segments:
        sp = seg.params
        c_v = apply("vsh_cutoff", sp["vsh_cutoff"]) if "vsh_cutoff" in theta else sp["vsh_cutoff"]
        c_phi = apply("phi_cutoff", sp["phi_cutoff"]) if "phi_cutoff" in theta else sp["phi_cutoff"]
        c_sw = apply("sw_cutoff", sp["sw_cutoff"]) if "sw_cutoff" in theta else sp["sw_cutoff"]
        if not seg.has_rt:
            sw = np.ones(len(seg.positions))
        elif not saturation_varied:
            sw = seg.sw_base
        else:
            p2 = dict(sp)
            for nm in ("a", "m", "n"):
                if nm in theta:
                    p2[nm] = apply(nm, sp[nm])
            rw = apply("rw", seg.rw) if "rw" in theta else seg.rw
            rsh = apply("rsh", seg.rsh) if "rsh" in theta else seg.rsh
            sw = _primary_sw_values(seg, frozen.curve_mapping, p2, rw, rsh, warn)
        pos = seg.positions
        g = seg.vsh < c_v
        r = g & (seg.phie > c_phi)
        pay_seg = r & (sw < c_sw)
        sw_all[pos] = sw
        gross[pos], res[pos], pay[pos] = g, r, pay_seg

    with np.errstate(invalid="ignore"):
        frac = np.clip(frozen.phie * (1.0 - sw_all), 0.0, 1.0)
        d_pay = np.nan_to_num(np.where(pay, frac, 0.0) * frozen.dz, nan=0.0)
        d_res = np.nan_to_num(np.where(res, frac, 0.0) * frozen.dz, nan=0.0)
    args = (frozen.vsh, frozen.phie, sw_all, frozen.dz, gross, res, pay, d_pay, d_res)
    return {
        "well": _scope_metrics(*args, None),
        "zones": {z: _scope_metrics(*args, frozen.zone_idx[z]) for z in frozen.zones},
        "clipped": clipped,
    }


# ---------------------------------------------------------------------------------------------
# Aggregation and Monte Carlo
# ---------------------------------------------------------------------------------------------

def aggregate_field(well_arrays: List[Dict[str, np.ndarray]]) -> Dict[str, np.ndarray]:
    """Field vectors from per-well metric vectors (same rule as export_service.wells_summary_frame).

    Sums for HCPV and thickness; average PHIE weighted by net pay; average Sw weighted by phih_pay,
    falling back to the net pay weights in a realisation where no well has phih_pay > 0; wells
    with an undefined average (or zero weight) are skipped.
    """
    stack = {m: np.vstack([np.atleast_1d(w[m]).astype(float) for w in well_arrays]) for m in METRICS}
    out = {m: stack[m].sum(axis=0) for m in ("hcpv_net_pay", "hcpv_net_res", "net_pay",
                                              "net_res", "phih_pay")}
    net = np.nan_to_num(stack["net_pay"], nan=0.0)
    phih = np.nan_to_num(stack["phih_pay"], nan=0.0)
    use_phih = (phih > 0).any(axis=0)

    def weighted(avg, weights):
        valid = np.isfinite(avg) & (weights > 0)
        den = np.where(valid, weights, 0.0).sum(axis=0)
        num = np.where(valid, np.nan_to_num(avg) * weights, 0.0).sum(axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan)

    out["avg_phie_pay"] = weighted(stack["avg_phie_pay"], net)
    out["avg_sw_pay"] = weighted(stack["avg_sw_pay"], np.where(use_phih[None, :], phih, net))
    return out


@dataclass
class MCResult:
    config: dict
    n: int
    seed: int
    sampling: str
    names: tuple
    offsets: np.ndarray
    wells: list
    excluded: list
    zones: dict
    values: dict
    deterministic: dict
    stats: dict
    tornado: dict
    rank_corr: dict
    clipped: dict
    warnings: list
    elapsed_s: float
    basis: dict = field(default_factory=dict)
    config_hash: str = ""


def _scope_series(frozen_wells, per_well_zone: Dict[Tuple[int, Optional[str]], Dict[str, np.ndarray]]):
    """{(scope, metric): array} for field, wells and zones from per-(well, zone) metric arrays."""
    out: Dict[Tuple[Any, str], np.ndarray] = {}
    field_in = []
    for wi, fw in enumerate(frozen_wells):
        well = per_well_zone[(wi, None)]
        field_in.append(well)
        for m in METRICS:
            out[(fw.key, m)] = well[m]
        for z in fw.zones:
            for m in METRICS:
                out[((fw.key, z), m)] = per_well_zone[(wi, z)][m]
    for m, v in aggregate_field(field_in).items():
        out[("field", m)] = v
    return out


def _run_batch(frozen_wells, thetas: List[Dict[str, float]], modes, cancel=None, progress=None,
               clipped_out: Optional[Dict[str, np.ndarray]] = None):
    """Evaluate every theta for every well; returns per-(well, zone) metric arrays or None."""
    n = len(thetas)
    per = {}
    for wi, fw in enumerate(frozen_wells):
        for z in [None] + list(fw.zones):
            per[(wi, z)] = {m: np.full(n, np.nan) for m in METRICS}
    step = max(1, n // 100)
    for i, theta in enumerate(thetas):
        if cancel is not None and cancel():
            return None
        for wi, fw in enumerate(frozen_wells):
            r = evaluate(fw, theta, modes)
            for m, v in r["well"].items():
                per[(wi, None)][m][i] = v
            for z, zm in r["zones"].items():
                for m, v in zm.items():
                    per[(wi, z)][m][i] = v
            if clipped_out is not None:
                for name, was in r["clipped"].items():
                    if was:
                        clipped_out[name][i] = True
        if progress is not None and ((i + 1) % step == 0 or i + 1 == n):
            progress(i + 1, n)
    return per


def run_monte_carlo(frozen_wells, cfg: UncertaintyConfig, progress=None, cancel=None,
                    excluded: Optional[list] = None) -> Optional[MCResult]:
    """Monte Carlo over the enabled distributions, single thread.

    progress(done, total) is called at most about every 1 %; cancel() is polled before each
    realisation and a cancelled run returns None. Draws are made before the loop, so results are
    bit-identical for equal (cfg, wells). ``excluded`` ([{"key","name","reason"}]) is recorded in
    the result and its warnings (wells the caller could not freeze). Raises ValueError for an
    invalid configuration or an empty well list.
    """
    t0 = time.perf_counter()
    errors = validate_config(cfg)
    if errors:
        raise ValueError("; ".join(errors))
    frozen_wells = list(frozen_wells)
    if not frozen_wells:
        raise ValueError("No wells to evaluate.")
    draws = sample_parameters(cfg)
    names = draws.names
    n = draws.offsets.shape[0]
    modes = {nm: cfg.distributions[nm].mode for nm in names}
    thetas = [dict(zip(names, row)) for row in draws.offsets.tolist()]
    clipped_flags = {nm: np.zeros(n, dtype=bool) for nm in names}

    per = _run_batch(frozen_wells, thetas, modes, cancel, progress, clipped_flags)
    if per is None:
        return None
    values = _scope_series(frozen_wells, per)

    # Deterministic column: theta = 0, the same kernel (equals each well's base summary).
    det_per = _run_batch(frozen_wells, [{}], modes)
    det_arrays = _scope_series(frozen_wells, det_per)
    deterministic = {k: float(v[0]) for k, v in det_arrays.items()}

    # Statistics; prob_zero is the share of realisations with zero net pay in the scope.
    stats_out = {}
    for (scope, metric), vec in values.items():
        stats_out[(scope, metric)] = exceedance_stats(vec, zero_mask=values[(scope, "net_pay")] == 0)

    # Tornado: one parameter at its own 10th / 90th marginal percentile, the rest at the base.
    tornado: dict = {}
    if names:
        q_low, q_high = TORNADO_QUANTILES
        t_thetas, inputs = [], {}
        for nm in names:
            lo = float(marginal_quantile(cfg.distributions[nm], q_low))
            hi = float(marginal_quantile(cfg.distributions[nm], q_high))
            inputs[nm] = (lo, hi)
            t_thetas += [{nm: lo}, {nm: hi}]
        t_per = _run_batch(frozen_wells, t_thetas, modes, cancel)
        if t_per is None:
            return None
        t_values = _scope_series(frozen_wells, t_per)
        for (scope, metric), vec in t_values.items():
            if metric not in TORNADO_METRICS:
                continue
            outputs = {nm: (float(vec[2 * j]), float(vec[2 * j + 1]), inputs[nm][0], inputs[nm][1])
                       for j, nm in enumerate(names)}
            tornado[(scope, metric)] = tornado_rows(deterministic[(scope, metric)], outputs)

    rank_corr = {m: rank_correlations(draws.offsets, names, values[("field", m)]) for m in METRICS}
    clipped = {nm: float(clipped_flags[nm].mean()) for nm in names}

    warns: List[str] = []
    for metric, label in (("hcpv_net_pay", "HCPV net pay"), ("net_pay", "Net pay")):
        msg = convergence_warning(values[("field", metric)])
        if msg:
            warns.append(f"{label}: {msg}")
    excluded = [dict(e) for e in (excluded or [])]
    for e in excluded:
        warns.append(f"Well {e.get('name', e.get('key'))} excluded: {e.get('reason', '')}")
    warns.append(f"Not varied: {NOT_VARIED}")

    return MCResult(
        config=config_to_dict(cfg), n=int(n), seed=int(cfg.seed), sampling=cfg.sampling,
        names=tuple(names), offsets=draws.offsets,
        wells=[{"key": fw.key, "name": fw.name} for fw in frozen_wells], excluded=excluded,
        zones={fw.key: list(fw.zones) for fw in frozen_wells}, values=values,
        deterministic=deterministic, stats=stats_out, tornado=tornado, rank_corr=rank_corr,
        clipped=clipped, warnings=warns, elapsed_s=time.perf_counter() - t0)
