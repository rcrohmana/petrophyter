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
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy import stats

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
