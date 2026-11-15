"""Rt deconvolution: conductivity-domain thin-bed enhancement (pure: numpy and scipy only, no Qt, no pipeline import).

Forward model, horizontal beds ``k`` with tops ``t_k`` < bottoms ``b_k`` (depth in ft, increasing downward)::

    sigma_a(z) = sum_k sigma_k * w_k(z),     sigma = 1 / Rt
    w_k(z)     = integral_{t_k}^{b_k} g(z - z') dz'          (g >= 0, integral g = 1)

Gaussian response: ``w_k(z) = Phi((z - t_k) / s) - Phi((z - b_k) / s)``, ``s = FWHM / 2.3548``.
Doll response: the vertical geometric factor of a two-coil sonde, tabulated numerically (formula to verify).

Bed boundaries come from a high-resolution reference curve (peaks of the smoothed derivative), the bed
conductivities from a regularised bounded least-squares solve (or a multiplicative iteration) window by
window. Skin effect, dip, anisotropy, borehole and invasion are ignored: the output is a bed-model estimate.

Benchmark of the ``lsq_linear`` method for the bounded branch (development PC, 0.5 ft step, bounds 1/R..R, lam 1e-3, per call):
40 beds / 330 rows / 2 beds at a bound: bvls 2.7 ms, trf 7.2 ms; 40 beds, R = 3 (23 at a bound): bvls 3.1 ms,
trf 9.8 ms; 120 beds / 1100 rows (56 at a bound): bvls 96 ms, trf 59 ms. Both give the same answer (max difference
5e-9). Windows hold at most 150 beds and typically about 40, so ``bvls`` is kept.
"""

from dataclasses import dataclass, field, fields, replace
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter1d, median_filter
from scipy.optimize import lsq_linear
from scipy.signal import find_peaks
from scipy.special import ndtr

from modules.petrophysics import DEPTH_STEP_WINDOW, GAP_STEP_FACTOR

REFS = ("doll1949", "thadani1981", "coll1993")
CONTEXT_REFS = ("us6963803", "unocal_attaka")
GENERIC_LABEL = "generic, confirm with tool charts"

GENERIC_RESPONSES: Dict[str, dict] = {
    "array_induction_1ft": {"fwhm_ft": 1.0, "label": GENERIC_LABEL},
    "array_induction_2ft": {"fwhm_ft": 2.0, "label": GENERIC_LABEL},
    "array_induction_4ft": {"fwhm_ft": 4.0, "label": GENERIC_LABEL},
    "laterolog_deep_2ft": {"fwhm_ft": 2.0, "label": GENERIC_LABEL},
    "dual_induction_deep_8ft": {"fwhm_ft": 8.0, "label": GENERIC_LABEL},
    "custom": {"fwhm_ft": 4.0, "label": GENERIC_LABEL},
}

FWHM_TO_SIGMA = 2.0 * np.sqrt(2.0 * np.log(2.0))   # 2.3548
MAX_BEDS_PER_WINDOW = 150
DOLL_HALF_RANGE = 20.0       # table covers |z| <= 20 L
DOLL_CELLS_PER_L = 200       # table step L / 200
LAM_RANGE = (-4.0, 0.0)      # log10 of the automatic Tikhonov weight
LAM_EVALS = 6
LAM_FALLBACK = 1e-4
MISFIT_AUTO_FACTOR = 2.0     # automatic misfit warning: twice the relative noise of the deep curve
BOUND_RTOL = 1e-6
_LSQ_METHOD = "bvls"         # bvls and trf agree to 1e-9 on the benchmark; bvls was faster (module docstring)
DEFAULT_MIN_BED = {"resistivity": 1.0, "RHOB": 1.5, "GR": 2.0}

COUNT_KEYS = ("no_hires", "no_rt", "undersampled", "amplified", "edge", "no_data", "windows_bad_misfit",
              "boundaries_merged", "edits_unmatched", "not_converged", "gap", "step_irregular", "window_split")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DeconParams:
    """Settings of one deconvolution run (the ``dec_*`` ladder keys without the prefix)."""

    hires_source: str = "auto"
    tool: str = "custom"
    fwhm_ft: float = 4.0
    response: str = "gaussian"
    doll_spacing_ft: float = 3.333
    smooth_ft: float = 0.5
    edge_k: float = 4.0
    min_contrast: float = 0.05
    min_bed_ft: Optional[float] = None
    window_ft: float = 200.0
    overlap_ft: float = 25.0
    solver: str = "lsq"
    lam: Optional[float] = None
    noise_rel: float = 0.03
    mult_max_iter: int = 100
    output: str = "blocky"
    max_ratio: float = 10.0
    misfit_warn: Optional[float] = None       # None: automatic, MISFIT_AUTO_FACTOR x noise_rel
    edits: Dict[str, list] = field(default_factory=lambda: {"add": [], "remove": []})
    edit_tol_ft: float = 1.0

    @classmethod
    def from_settings(cls, settings: Optional[dict]) -> "DeconParams":
        """Build from a dict of ``dec_*`` keys; unknown keys are ignored, a preset tool fills the response."""
        settings = settings or {}
        known = {f.name for f in fields(cls)}
        values: Dict[str, Any] = {}
        for key, value in settings.items():
            name = key[4:] if key.startswith("dec_") else None
            if name == "lambda":
                name = "lam"
            if name in known:
                values[name] = value
        tool = values.get("tool", "custom")
        if tool != "custom" and tool in GENERIC_RESPONSES:
            values["fwhm_ft"] = GENERIC_RESPONSES[tool]["fwhm_ft"]
            values["response"] = "gaussian"
        edits = values.get("edits")
        if isinstance(edits, dict):
            values["edits"] = {"add": list(edits.get("add", [])), "remove": list(edits.get("remove", []))}
        elif "edits" in values:
            del values["edits"]
        return cls(**values)

    @property
    def misfit_warn_value(self) -> float:
        """The misfit warning level in use: the set value, or ``MISFIT_AUTO_FACTOR`` times the noise."""
        return float(self.misfit_warn) if self.misfit_warn is not None else MISFIT_AUTO_FACTOR * float(self.noise_rel)

    @property
    def width_ft(self) -> float:
        """Vertical scale of the response: FWHM (Gaussian) or coil spacing (Doll)."""
        return float(self.doll_spacing_ft if self.response == "doll" else self.fwhm_ft)

    def with_width(self, width_ft: float) -> "DeconParams":
        """The same settings with the response width (FWHM, or coil spacing for Doll) replaced."""
        if self.response == "doll":
            return replace(self, doll_spacing_ft=float(width_ft))
        return replace(self, fwhm_ft=float(width_ft))

    def with_reference(self, curve_name: Optional[str]) -> "DeconParams":
        """Fill the automatic minimum bed thickness for the reference curve kind."""
        if self.min_bed_ft is not None:
            return self
        return replace(self, min_bed_ft=default_min_bed(curve_name))


def default_min_bed(curve_name: Optional[str]) -> float:
    """1.0 ft for resistivity-type references (HIRES, RXO), 1.5 ft for RHOB, 2.0 ft for GR."""
    name = (curve_name or "").upper()
    if name == "RHOB":
        return DEFAULT_MIN_BED["RHOB"]
    if name == "GR":
        return DEFAULT_MIN_BED["GR"]
    return DEFAULT_MIN_BED["resistivity"]


@dataclass
class Bed:
    top: float
    bottom: float
    n_rows: int
    rt_prior: float
    rt_decon: float
    at_bound: bool


@dataclass
class WindowStat:
    top: float
    bottom: float
    n_rows: int
    n_beds: int
    lam: float
    misfit_rms: float
    misfit_max: float
    status: str


@dataclass
class BedPick:
    """Interior bed boundaries of one segment (ascending depths) and what was dropped on the way."""

    boundaries: np.ndarray
    strengths: np.ndarray
    n_candidates: int = 0
    n_dropped_contrast: int = 0
    n_dropped_thickness: int = 0

    @property
    def n_dropped(self) -> int:
        return self.n_dropped_contrast + self.n_dropped_thickness


@dataclass
class DeconResult:
    rt_decon: np.ndarray
    valid: np.ndarray
    beds: List[Bed] = field(default_factory=list)
    windows: List[WindowStat] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)
    issues: List[tuple] = field(default_factory=list)
    zone_stats: Dict[str, dict] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Vertical response
# ---------------------------------------------------------------------------
_DOLL_CACHE: Dict[float, dict] = {}


def doll_gz(z, doll_l_ft: float) -> np.ndarray:
    """Doll vertical response ``g_z(z)``, integral over rho of the unit-volume geometric factor.

    Has an integrable logarithmic singularity at ``z = +/-L/2``: never call it exactly there.
    """
    L = float(doll_l_ft)
    z = np.atleast_1d(np.asarray(z, dtype=float))
    u = np.linspace(np.log(1e-8 * L), np.log(1e4 * L), 1500)
    rho = np.exp(u)
    rho2 = rho * rho
    out = np.empty(z.size)
    for start in range(0, z.size, 400):
        zc = z[start:start + 400, None]
        a2 = rho2[None, :] + (zc + L / 2.0) ** 2
        b2 = rho2[None, :] + (zc - L / 2.0) ** 2
        f = rho2[None, :] * rho[None, :] / (a2 * np.sqrt(a2) * b2 * np.sqrt(b2))
        out[start:start + 400] = np.trapezoid(f, u, axis=1) if hasattr(np, "trapezoid") else np.trapz(f, u, axis=1)
    return out * (L * L / np.pi)


def _singular_cell_mass(L: float, edge_pos: float, direction: float, dz: float) -> float:
    """Mass of the cell next to a singular point (``edge_pos = +/-L/2``) by dyadic grading toward the singularity."""
    nodes, weights = np.polynomial.legendre.leggauss(4)
    depth = 14
    total = 0.0
    for j in range(depth + 1):
        far, near = dz * 0.5 ** j, dz * 0.5 ** (j + 1)
        x = 0.5 * (far + near) + 0.5 * (far - near) * nodes          # distance from the singular point
        total += 0.5 * (far - near) * float(np.sum(weights * doll_gz(edge_pos + direction * x, L)))
    tail = dz * 0.5 ** (depth + 1)
    return total + tail * float(doll_gz([edge_pos + direction * tail / 2.0], L)[0])


def doll_table(doll_l_ft: float, half_range: float = DOLL_HALF_RANGE) -> dict:
    """Cumulative Doll response ``G_z`` on ``|z| <= half_range * L`` (cell step L/200, midpoint cells, cached by L).

    Cells next to the log singularities at ``z = +/-L/2`` are graded toward the singular point; no value is ever
    computed at the singular point itself. Returns ``edges``, ``G`` (renormalised to 1 at +inf), ``centres``, ``gz``
    (values at the cell centres), ``mass`` (cell integrals) and ``raw_area`` (the integral before renormalisation).
    """
    key = (round(float(doll_l_ft), 9), float(half_range))
    cached = _DOLL_CACHE.get(key)
    if cached is not None:
        return cached
    L = float(doll_l_ft)
    dz = L / DOLL_CELLS_PER_L
    n_half = int(round(half_range * DOLL_CELLS_PER_L))
    positive = (np.arange(n_half) + 0.5) * dz
    gz_pos = doll_gz(positive, L)
    mass_pos = gz_pos * dz
    k_edge = DOLL_CELLS_PER_L // 2                  # cell index whose upper edge is L/2 is k_edge - 1
    mass_pos[k_edge - 1] = _singular_cell_mass(L, L / 2.0, -1.0, dz)
    mass_pos[k_edge] = _singular_cell_mass(L, L / 2.0, 1.0, dz)
    mass = np.concatenate([mass_pos[::-1], mass_pos])
    gz = np.concatenate([gz_pos[::-1], gz_pos])
    centres = np.concatenate([-positive[::-1], positive])
    edges = np.concatenate([[-n_half * dz], centres + dz / 2.0])
    cum = np.concatenate([[0.0], np.cumsum(mass)])
    raw = float(cum[-1])
    table = {"edges": edges, "G": cum / raw, "centres": centres, "gz": gz, "mass": mass, "raw_area": raw}
    _DOLL_CACHE[key] = table
    return table


def response_weights(z, tops, bottoms, fwhm_ft, kind="gaussian", doll_l_ft=None) -> np.ndarray:
    """Weights ``(n_rows, n_beds)`` of each bed at each depth. Infinite tops / bottoms are allowed."""
    z = np.asarray(z, dtype=float)[:, None]
    tops = np.asarray(tops, dtype=float)[None, :]
    bottoms = np.asarray(bottoms, dtype=float)[None, :]
    if kind == "doll":
        if doll_l_ft is None or doll_l_ft <= 0:
            raise ValueError("doll response needs doll_l_ft > 0")
        table = doll_table(doll_l_ft)
        edges, cum = table["edges"], table["G"]
        return np.interp(z - tops, edges, cum) - np.interp(z - bottoms, edges, cum)
    if kind != "gaussian":
        raise ValueError(f"unknown response {kind!r}")
    s = float(fwhm_ft) / FWHM_TO_SIGMA
    return ndtr((z - tops) / s) - ndtr((z - bottoms) / s)


# ---------------------------------------------------------------------------
# Bed picking and manual edits
# ---------------------------------------------------------------------------
def _robust_sigma(values: np.ndarray) -> float:
    values = values[np.isfinite(values)]
    if values.size == 0:
        return 0.0
    return float(1.4826 * np.median(np.abs(values - np.median(values))))


MED3_RESIDUAL_MAD = 1.0213     # robust sigma of the non-zero x - median3(x) for unit Gaussian noise (simulated)
EDGE_DOMINATED = 0.5           # derivative MAD this many times the noise estimate or more: the edges inflated it


def _derivative_noise(yg: np.ndarray, ds: float, smooth_samples: float) -> float:
    """Noise sigma of the smoothed derivative, estimated from the curve's own sample noise.

    The sample noise comes from the residual against a 3-point running median, which follows steps, so the estimate
    does not grow with the number of bed boundaries (a MAD of the derivative does: on closely alternating beds the
    transitions are most of the samples and no boundary passes the threshold). It replaces the derivative MAD only
    when that is clearly inflated (``EDGE_DOMINATED``), so sparse beds and pure noise keep the plain MAD rule. The
    noise is carried through the same smoothing and gradient as the curve (L2 norm of the impulse response). Beds of
    about three samples or fewer stay below the resolution of the rule.
    """
    if yg.size < 5:
        return 0.0
    resid = yg - median_filter(yg, size=3, mode="nearest")
    resid = resid[resid != 0]                    # the sample that is its own median carries no noise information
    if resid.size < 5:
        return 0.0
    sigma_y = _robust_sigma(resid) / MED3_RESIDUAL_MAD
    half = int(np.ceil(4.0 * smooth_samples)) + 2
    impulse = np.zeros(2 * half + 1)
    impulse[half] = 1.0
    kernel = np.gradient(gaussian_filter1d(impulse, smooth_samples, mode="constant"), ds)
    return float(sigma_y * np.sqrt(np.sum(kernel ** 2)))


def _effective_min_bed(params: DeconParams, ds: float, log_domain: bool) -> float:
    base = params.min_bed_ft if params.min_bed_ft is not None else (DEFAULT_MIN_BED["resistivity"] if log_domain
                                                                     else DEFAULT_MIN_BED["GR"])
    return float(max(base, 2.0 * ds))


def pick_beds(depth, curve, params: DeconParams, log_domain: bool) -> BedPick:
    """Interior bed boundaries of one segment from the reference curve (peaks of the smoothed derivative)."""
    empty = BedPick(np.empty(0), np.empty(0))
    z = np.asarray(depth, dtype=float)
    y = np.asarray(curve, dtype=float)
    if log_domain:
        y = np.where(y > 0, np.log10(np.where(y > 0, y, 1.0)), np.nan)
    finite = np.isfinite(y) & np.isfinite(z)
    if finite.sum() < 5:
        return empty
    step = np.diff(z[finite])
    step = step[step > 0]
    if step.size == 0:
        return empty
    ds = float(np.median(step))
    n = int(np.floor((z[finite][-1] - z[finite][0]) / ds)) + 1
    if n < 5:
        return empty
    grid = z[finite][0] + ds * np.arange(n)
    yg = np.interp(grid, z[finite], y[finite])
    smooth_samples = max(params.smooth_ft / ds, 1e-3)
    ys = gaussian_filter1d(yg, smooth_samples, mode="nearest")
    d = np.gradient(ys, ds)
    mag = np.abs(d)
    sigma_d = _robust_sigma(d)
    noise_d = _derivative_noise(yg, ds, smooth_samples)
    if noise_d < EDGE_DOMINATED * sigma_d:      # many boundaries: the derivative MAD measures edges, not noise
        sigma_d = noise_d
    height = params.edge_k * max(sigma_d, 1e-6 * float(mag.max()), 1e-12)
    min_bed = _effective_min_bed(params, ds, log_domain)
    peaks, _ = find_peaks(mag, height=height, distance=max(1, int(round(min_bed / ds))))
    n_candidates = int(peaks.size)
    if n_candidates == 0:
        return BedPick(empty.boundaries, empty.strengths, 0)
    contrast_min = params.min_contrast if log_domain else params.min_contrast * max(_robust_sigma(yg), 1e-12)
    margin = max(1, int(round(min(params.smooth_ft, min_bed / 2.0) / ds)))
    span = max(margin + 1, int(round(min_bed / ds)))
    keep: List[int] = []
    for p in peaks:
        above = ys[max(0, p - span):max(0, p - margin) + 1]
        below = ys[min(n - 1, p + margin):min(n, p + span + 1)]
        if above.size == 0 or below.size == 0:
            continue
        if abs(np.median(below) - np.median(above)) >= contrast_min:
            keep.append(int(p))
    n_dropped_contrast = n_candidates - len(keep)
    refined = []
    for q in keep:                                   # parabolic refinement of the peak position
        if 0 < q < n - 1:
            denom = mag[q - 1] - 2.0 * mag[q] + mag[q + 1]
            shift = 0.0 if denom == 0 else float(np.clip(0.5 * (mag[q - 1] - mag[q + 1]) / denom, -0.5, 0.5))
        else:
            shift = 0.0
        refined.append(grid[q] + shift * ds)
    depths = refined
    strengths = list(mag[keep])
    top, bottom = float(z[finite][0]), float(z[finite][-1])
    n_dropped_thickness = 0
    while len(depths) > 0:
        edges = np.array([top] + depths + [bottom])
        thin = np.flatnonzero(np.diff(edges) < min_bed)
        if thin.size == 0:
            break
        # drop the weaker interior boundary of the first too-thin bed
        i = int(thin[0])                          # bed i lies between edges i and i+1; interior ids are i-1 and i
        candidates = [j for j in (i - 1, i) if 0 <= j < len(depths)]
        drop = min(candidates, key=lambda j: strengths[j])
        del depths[drop], strengths[drop]
        n_dropped_thickness += 1
    return BedPick(np.array(depths, dtype=float), np.array(strengths, dtype=float), n_candidates,
                   n_dropped_contrast, n_dropped_thickness)


def apply_edits(boundaries, edits: Optional[dict], tol_ft: float) -> Tuple[np.ndarray, dict]:
    """Apply manual edits to automatic boundaries: ``remove`` deletes the nearest one within ``tol_ft``, ``add`` inserts.

    Returns the sorted boundaries and ``{"removed", "added", "unmatched", "skipped"}`` (unmatched removes, adds that
    sat within ``tol_ft`` of an existing boundary).
    """
    auto = [float(b) for b in np.asarray(boundaries, dtype=float)]
    edits = edits or {}
    info = {"removed": 0, "added": 0, "unmatched": 0, "skipped": 0}
    for depth in edits.get("remove", []) or []:
        depth = float(depth)
        if auto:
            j = int(np.argmin(np.abs(np.array(auto) - depth)))
            if abs(auto[j] - depth) <= tol_ft:
                del auto[j]
                info["removed"] += 1
                continue
        info["unmatched"] += 1
    for depth in edits.get("add", []) or []:
        depth = float(depth)
        if auto and np.min(np.abs(np.array(auto) - depth)) <= tol_ft:
            info["skipped"] += 1
            continue
        auto.append(depth)
        info["added"] += 1
    return np.array(sorted(auto), dtype=float), info


# ---------------------------------------------------------------------------
# Solvers
# ---------------------------------------------------------------------------
def _rms(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(values * values))) if values.size else float("nan")


def _ridge(AtA: np.ndarray, Atr: np.ndarray, lam: float) -> np.ndarray:
    return 1.0 + np.linalg.solve(AtA + lam * np.eye(AtA.shape[0]), Atr)


def _auto_lambda(A: np.ndarray, AtA: np.ndarray, Atr: np.ndarray, noise_rel: float) -> float:
    """Largest lambda whose relative misfit stays within ``1.1 * noise_rel`` (bisection on log10, <= 6 solves)."""
    target = 1.1 * noise_rel

    def misfit(log_lam: float) -> float:
        return _rms(A @ _ridge(AtA, Atr, 10.0 ** log_lam) - 1.0)

    lo, hi = LAM_RANGE
    if misfit(lo) > target:
        return LAM_FALLBACK
    if misfit(hi) <= target:
        return 10.0 ** hi
    best = lo
    for _ in range(LAM_EVALS - 2):
        mid = 0.5 * (lo + hi)
        if misfit(mid) <= target:
            best, lo = mid, mid
        else:
            hi = mid
    return 10.0 ** best


def _solve_lsq(A: np.ndarray, lam: Optional[float], R: float, noise_rel: float) -> Tuple[np.ndarray, float, bool]:
    """Regularised bounded least squares; returns ``(x, lam, converged)``."""
    AtA = A.T @ A
    Atr = A.T @ (1.0 - A.sum(axis=1))
    if lam is None:
        lam = _auto_lambda(A, AtA, Atr, noise_rel)
    x = _ridge(AtA, Atr, lam)
    lo, hi = 1.0 / R, R
    if np.all((x >= lo) & (x <= hi)):
        return x, lam, True
    k = A.shape[1]
    aug_a = np.vstack([A, np.sqrt(lam) * np.eye(k)])
    aug_b = np.concatenate([np.ones(A.shape[0]), np.sqrt(lam) * np.ones(k)])
    res = lsq_linear(aug_a, aug_b, bounds=(lo, hi), method=_LSQ_METHOD)
    return res.x, lam, bool(res.status > 0)


def _solve_mult(A: np.ndarray, noise_rel: float, max_iter: int) -> Tuple[np.ndarray, bool]:
    """Multiplicative (Richardson-Lucy form) iteration; early stopping is the regulariser."""
    colsum = np.maximum(A.sum(axis=0), 1e-12)
    x = np.ones(A.shape[1])
    prev = np.inf
    stall = 0
    for _ in range(max_iter):
        f = np.maximum(A @ x, 1e-12)
        misfit = _rms(f - 1.0)
        if misfit <= noise_rel:
            return x, True
        if prev - misfit < 1e-4 * prev:
            stall += 1
            if stall >= 3:
                return x, True
        else:
            stall = 0
        prev = misfit
        x = x * (A.T @ (1.0 / f)) / colsum
    return x, _rms(A @ x - 1.0) <= noise_rel


# ---------------------------------------------------------------------------
# Deconvolution
# ---------------------------------------------------------------------------
def _gap_after(depth: np.ndarray) -> np.ndarray:
    """True where the interval to the next sample is a gap (same rule and constants as ``depth_increments``)."""
    if depth.size < 2:
        return np.zeros(0, dtype=bool)
    delta = np.abs(np.diff(depth))
    positive = pd.Series(np.where(delta > 0, delta, np.nan))
    local = positive.rolling(DEPTH_STEP_WINDOW, center=True, min_periods=1).median()
    overall = positive.median()
    local = local.fillna(overall if np.isfinite(overall) else 0.0).to_numpy()
    with np.errstate(invalid="ignore"):
        return delta > GAP_STEP_FACTOR * local


class _Events:
    """Collects counted events per zone and turns them into one issue tuple per (code, zone)."""

    def __init__(self):
        self.items: Dict[Tuple[str, Optional[str]], dict] = {}

    def add(self, code: str, zone, n: int = 1, note: str = "", hint: bool = False):
        entry = self.items.setdefault((code, zone), {"n": 0, "notes": [], "hint": False})
        entry["n"] += n
        entry["hint"] = entry["hint"] or hint
        if note and len(entry["notes"]) < 3:
            entry["notes"].append(note)


def _zone_key(zone) -> str:
    return "" if zone is None else str(zone)


def deconvolve(depth, rt, hires, params: DeconParams, active, data_mask=None, zone_labels=None,
               max_ratio_by_zone=None, misfit_warn_by_zone=None, log_domain=True) -> DeconResult:
    """Deconvolve the deep resistivity ``rt`` in the rows flagged ``active``; see the module docstring.

    ``hires`` is the reference curve (log10 when ``log_domain``). Rows outside ``active`` feed the data term as context
    but never produce output. Inputs are not modified.
    """
    z = np.asarray(depth, dtype=float)
    n = z.size
    rt_arr = None if rt is None else np.asarray(rt, dtype=float)
    hi_arr = None if hires is None else np.asarray(hires, dtype=float)
    act = np.asarray(active, dtype=bool)
    mask = np.ones(n, dtype=bool) if data_mask is None else np.asarray(data_mask, dtype=bool)
    zones = None if zone_labels is None else np.asarray(zone_labels, dtype=object)
    ratios = max_ratio_by_zone or {}
    warns = misfit_warn_by_zone or {}
    counts = {key: 0 for key in COUNT_KEYS}
    ev = _Events()
    out = np.full(n, np.nan)
    valid = np.zeros(n, dtype=bool)
    result = DeconResult(out, valid, counts=counts)

    def zone_at(i):
        return None if zones is None else zones[int(i)]

    def finish() -> DeconResult:
        result.issues = _issues(ev, result, params, act, zones)
        return result

    n_active = int(act.sum())
    if n_active == 0:
        return finish()
    if n < 3 or not np.all(np.isfinite(z)) or np.any(np.diff(z) <= 0):
        counts["no_rt"] = n_active
        ev.add("LRLC_DECON_NO_RT", None, n_active, "depth not ascending")
        return finish()
    data_ok = (np.zeros(n, dtype=bool) if rt_arr is None else (np.isfinite(rt_arr) & (rt_arr > 0))) & mask
    if not np.any(data_ok & act) and not np.any(data_ok):
        counts["no_rt"] = n_active
        ev.add("LRLC_DECON_NO_RT", None, n_active, "no finite resistivity")
        return finish()
    if hi_arr is None or not np.any(np.isfinite(hi_arr) & (hi_arr > 0 if log_domain else True)):
        counts["no_hires"] = n_active
        ev.add("LRLC_DECON_NO_HIRES", None, n_active, "no usable reference curve")
        return finish()

    w = params.width_ft
    pad = 3.0 * w
    h = (3.0 if params.response == "doll" else 2.0) * w
    overlap = max(params.overlap_ft, 3.0 * w)
    core_len = max(params.window_ft - 2.0 * overlap, overlap)
    sigma_a = np.full(n, np.nan)
    sigma_a[data_ok] = 1.0 / rt_arr[data_ok]
    gap_after = _gap_after(z)
    default_ratio = float(params.max_ratio)

    # step 1: solve intervals from the active rows, padded and merged
    idx = np.flatnonzero(act)
    run_starts = np.concatenate([[0], np.flatnonzero(np.diff(idx) > 1) + 1])
    run_ends = np.concatenate([run_starts[1:] - 1, [idx.size - 1]])
    intervals: List[List[float]] = []
    for s, e in zip(run_starts, run_ends):
        lo_d, hi_d = z[idx[s]] - pad, z[idx[e]] + pad
        if intervals and lo_d <= intervals[-1][1]:
            intervals[-1][1] = max(intervals[-1][1], hi_d)
        else:
            intervals.append([lo_d, hi_d])

    rt_row = np.full(n, np.nan)        # blocky or residual value before validity
    f_row = np.full(n, np.nan)
    resid_row = np.full(n, np.nan)
    bed_bad = np.zeros(n, dtype=bool)  # row belongs to a bed at a bound
    no_data_row = np.zeros(n, dtype=bool)
    edge_row = np.zeros(n, dtype=bool)
    skipped_row = np.zeros(n, dtype=bool)   # rows of undersampled or too short segments

    for lo_d, hi_d in intervals:
        i0 = int(np.searchsorted(z, lo_d, side="left"))
        i1 = int(np.searchsorted(z, hi_d, side="right"))
        if i1 - i0 < 3:
            continue
        step_med = float(np.median(np.diff(z[i0:i1])))
        keep = np.ones(i1 - i0, dtype=bool)
        bad = ~data_ok[i0:i1]
        if bad.any():
            edges = np.diff(np.concatenate([[0], bad.astype(int), [0]]))
            for s, e in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
                extent = z[i0 + e - 1] - z[i0 + s] + step_med
                if extent > 2.0 * w:
                    keep[s:e] = False
                    counts["gap"] += 1
                    ev.add("LRLC_DECON_GAP", zone_at(i0 + s), 1, f"no data {z[i0 + s]:.1f}-{z[i0 + e - 1]:.1f} ft")
        brk = gap_after[i0:i1 - 1]
        starts = [j for j in range(i1 - i0) if keep[j] and (j == 0 or not keep[j - 1] or brk[j - 1])]
        ends = [j for j in range(i1 - i0) if keep[j] and (j == i1 - i0 - 1 or not keep[j + 1] or brk[j])]
        for j in starts[1:]:
            if j > 0 and keep[j - 1] and brk[j - 1]:
                counts["gap"] += 1
                ev.add("LRLC_DECON_GAP", zone_at(i0 + j), 1, f"depth gap at {z[i0 + j]:.1f} ft")
        for js, je in zip(starts, ends):
            _segment(i0 + js, i0 + je + 1, z, hires=hi_arr, params=params, act=act, data_ok=data_ok, sigma_a=sigma_a,
                     log_domain=log_domain, w=w, h=h, overlap=overlap, core_len=core_len, ratios=ratios,
                     warns=warns, default_ratio=default_ratio, zone_at=zone_at, counts=counts, ev=ev, result=result,
                     rt_row=rt_row, f_row=f_row, resid_row=resid_row, bed_bad=bed_bad, no_data_row=no_data_row,
                     edge_row=edge_row, skipped_row=skipped_row)

    # step 6: validity per sample
    rows = np.flatnonzero(act)
    row_ratio = np.full(n, default_ratio)
    if zones is not None:
        for zn, val in ratios.items():
            row_ratio[zones == zn] = float(val)
    finite = np.isfinite(rt_row)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(finite & data_ok, np.maximum(rt_row / rt_arr, rt_arr / rt_row), np.nan)
    too_big = np.isfinite(ratio) & (ratio > row_ratio)
    amplified = act & ~skipped_row & ~edge_row & ~no_data_row & (bed_bad | too_big)
    ok = act & finite & data_ok & ~skipped_row & ~edge_row & ~no_data_row & ~amplified
    out[ok] = rt_row[ok]
    valid[ok] = True
    counts["edge"] += int((act & edge_row & ~skipped_row).sum())
    counts["amplified"] = int(amplified.sum())
    counts["no_data"] = int((act & no_data_row & ~edge_row & ~skipped_row).sum())
    for i in np.flatnonzero(act & edge_row & ~skipped_row):
        ev.add("LRLC_DECON_EDGE", zone_at(i), 1)
    for i in np.flatnonzero(amplified):
        ev.add("LRLC_DECON_AMPLIFIED", zone_at(i), 1)
    # zone statistics
    labels = [_zone_key(zone_at(i)) for i in rows] if zones is not None else [""] * rows.size
    for zone in sorted(set(labels)):
        sel = rows[np.asarray([label == zone for label in labels])]
        res = resid_row[sel]
        res = res[np.isfinite(res)]
        result.zone_stats[zone] = {
            "n_active": int(sel.size), "n_valid": int(valid[sel].sum()), "n_amplified": int(amplified[sel].sum()),
            "n_edge": int((edge_row[sel] & ~skipped_row[sel]).sum()),
            "misfit_rms": _rms(res) if res.size else float("nan"),
            "max_ratio": float(ratios.get(zone, default_ratio)),
        }
    return finish()


def _segment(j0, j1, z, *, hires, params, act, data_ok, sigma_a, log_domain, w, h, overlap, core_len, ratios, warns,
             default_ratio, zone_at, counts, ev, result, rt_row, f_row, resid_row, bed_bad, no_data_row, edge_row,
             skipped_row):
    """Solve one contiguous, gap-free segment (rows ``j0:j1``) and write the per-row outputs in place."""
    zs = z[j0:j1]
    seg_act = act[j0:j1]
    n_act = int(seg_act.sum())
    steps = np.diff(zs)
    ds = float(np.median(steps)) if steps.size else np.inf
    mid_zone = zone_at(j0 + (j1 - j0) // 2)
    if (j1 - j0) < 5 or not np.isfinite(ds):
        skipped_row[j0:j1] = True
        counts["edge"] += n_act
        for i in np.flatnonzero(act[j0:j1]) + j0:
            ev.add("LRLC_DECON_EDGE", zone_at(i), 1)
        return
    if ds > w / 2.0:
        skipped_row[j0:j1] = True
        counts["undersampled"] += n_act
        if n_act:
            ev.add("LRLC_DECON_UNDERSAMPLED", mid_zone, n_act, f"step {ds:.2f} ft > FWHM/2 = {w / 2.0:.2f} ft")
        return
    if steps.size > 1 and np.std(steps) / np.mean(steps) > 0.05:
        counts["step_irregular"] += 1
        ev.add("LRLC_DECON_STEP_IRREGULAR", mid_zone, 1)
    hs = hires[j0:j1]
    if not np.any(np.isfinite(hs) & (hs > 0 if log_domain else True)):
        skipped_row[j0:j1] = True
        counts["no_hires"] += n_act
        if n_act:
            ev.add("LRLC_DECON_NO_HIRES", mid_zone, n_act, "reference curve empty here")
        return
    edge_row[j0:j1] |= (zs < zs[0] + w) | (zs > zs[-1] - w)

    # step 2: bed boundaries
    p_seg = params if params.min_bed_ft is not None else replace(params, min_bed_ft=_effective_min_bed(params, ds, log_domain))
    pick = pick_beds(zs, hs, p_seg, log_domain)
    top, bottom = float(zs[0] - ds / 2.0), float(zs[-1] + ds / 2.0)
    lo_edit, hi_edit = top, bottom
    seg_edits = {key: [d for d in params.edits.get(key, []) if lo_edit <= float(d) <= hi_edit]
                 for key in ("add", "remove")}
    bounds, info = apply_edits(pick.boundaries, seg_edits, params.edit_tol_ft)
    bounds = bounds[(bounds > top + 1e-9) & (bounds < bottom - 1e-9)]
    if bounds.size:
        keep = np.concatenate([[True], np.diff(bounds) > 1e-9])
        bounds = bounds[keep]
    if pick.n_dropped:
        counts["boundaries_merged"] += pick.n_dropped
        ev.add("LRLC_DECON_BED_MERGED", mid_zone, pick.n_dropped)
    if info["unmatched"]:
        counts["edits_unmatched"] += info["unmatched"]
        ev.add("LRLC_DECON_BED_EDIT_UNMATCHED", mid_zone, info["unmatched"])
    edges = np.concatenate([[top], bounds, [bottom]])
    nb = edges.size - 1
    bed_of = np.searchsorted(bounds, zs, side="right")
    row_ptr = np.searchsorted(bed_of, np.arange(nb + 1))
    d_ok = data_ok[j0:j1]
    sa = sigma_a[j0:j1]

    # step 3: bed priors (median conductivity over the central half of the finite rows)
    sigma0 = np.full(nb, np.nan)
    for k in range(nb):
        rows = np.flatnonzero(d_ok[row_ptr[k]:row_ptr[k + 1]]) + row_ptr[k]
        if rows.size == 0:
            continue
        if rows.size >= 3:
            q1, q2 = int(np.floor(0.25 * rows.size)), int(np.ceil(0.75 * rows.size))
            sigma0[k] = np.median(sa[rows[q1:max(q2, q1 + 1)]])
        else:
            sigma0[k] = np.mean(sa[rows])
    usable = np.isfinite(sigma0)
    centres = 0.5 * (edges[:-1] + edges[1:])

    # step 4: windows (cores tile the segment, snapped to bed boundaries)
    cuts = [top]
    x = top + core_len
    while bottom - x > 0.5 * core_len:
        snapped = float(bounds[np.argmin(np.abs(bounds - x))]) if bounds.size else x
        if snapped > cuts[-1] + 1e-9:
            cuts.append(snapped)
        x = cuts[-1] + core_len
    cuts.append(bottom)
    cores = [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)]

    def n_system(c_lo, c_hi):
        lo_, hi_ = max(top, c_lo - overlap), min(bottom, c_hi + overlap)
        return int(np.sum((edges[1:] > lo_) & (edges[:-1] < hi_) & usable))

    work = list(cores)
    final: List[Tuple[float, float]] = []
    while work:
        c_lo, c_hi = work.pop(0)
        inner = bounds[(bounds > c_lo + 1e-9) & (bounds < c_hi - 1e-9)]
        if n_system(c_lo, c_hi) > MAX_BEDS_PER_WINDOW and inner.size:
            mid = float(inner[np.argmin(np.abs(inner - 0.5 * (c_lo + c_hi)))])
            counts["window_split"] += 1
            ev.add("LRLC_DECON_WINDOW_SPLIT", mid_zone, 1)
            work = [(c_lo, mid), (mid, c_hi)] + work
        else:
            final.append((c_lo, c_hi))

    x_bed = np.full(nb, np.nan)
    bound_bed = np.zeros(nb, dtype=bool)
    solved_bed = np.zeros(nb, dtype=bool)
    kind = params.response
    for wi, (c_lo, c_hi) in enumerate(final):
        last = wi == len(final) - 1
        owned = usable & (centres >= c_lo) & ((centres < c_hi) | (last & (centres <= c_hi)))
        own_rows = np.zeros(j1 - j0, dtype=bool)
        for k in np.flatnonzero(owned):
            own_rows[row_ptr[k]:row_ptr[k + 1]] = True
        if not np.any(own_rows & seg_act):
            continue
        lo_, hi_ = max(top, c_lo - overlap), min(bottom, c_hi + overlap)
        sys_k = np.flatnonzero((edges[1:] > lo_) & (edges[:-1] < hi_) & usable)
        win_rows = np.flatnonzero((zs >= lo_) & (zs <= hi_))
        if sys_k.size == 0 or win_rows.size == 0:
            continue
        tops_s, bots_s = edges[sys_k].copy(), edges[sys_k + 1].copy()
        tops_s[0], bots_s[-1] = -np.inf, np.inf
        W = response_weights(zs[win_rows], tops_s, bots_s, params.fwhm_ft, kind, params.doll_spacing_ft)
        W = W / np.maximum(W.sum(axis=1, keepdims=True), 1e-12)
        zw = zs[win_rows]
        use = d_ok[win_rows].copy()
        if lo_ > top + 1e-9:
            use &= zw >= lo_ + h
        if hi_ < bottom - 1e-9:
            use &= zw <= hi_ - h
        s0 = sigma0[sys_k]
        sa_w = sa[win_rows]
        mu = ~np.isfinite(sa_w) | ~use
        A_full = W * s0[None, :] / np.where(np.isfinite(sa_w), sa_w, 1.0)[:, None]
        A = A_full[~mu]
        zone_c = zone_at(min(j1 - 1, j0 + int(np.searchsorted(zs, 0.5 * (c_lo + c_hi)))))
        R = float(ratios.get(zone_c, default_ratio))
        if ratios:
            win_zones = {zone_at(j0 + int(i)) for i in win_rows}
            R = max(float(ratios.get(zn, default_ratio)) for zn in win_zones)
        status = "ok"
        lam_used = 0.0
        if A.shape[0] < 1:
            status = "no_data"
            continue
        if params.solver == "mult":
            xs, converged = _solve_mult(A, params.noise_rel, params.mult_max_iter)
            xs = np.clip(xs, 1.0 / R, R)
            if not converged:
                status = "not_converged"
                counts["not_converged"] += 1
                ev.add("LRLC_DECON_NOT_CONVERGED", zone_c, 1, f"{c_lo:.1f}-{c_hi:.1f} ft")
        else:
            xs, lam_used, converged = _solve_lsq(A, params.lam, R, params.noise_rel)
            if not converged:
                status = "not_converged"
                counts["not_converged"] += 1
                ev.add("LRLC_DECON_NOT_CONVERGED", zone_c, 1, f"{c_lo:.1f}-{c_hi:.1f} ft")
        resid = A @ xs - 1.0
        m_rms, m_max = _rms(resid), float(np.max(np.abs(resid)))
        zone_warn = warns.get(zone_c)
        warn = float(zone_warn) if zone_warn is not None else params.misfit_warn_value
        if m_rms > warn:
            counts["windows_bad_misfit"] += 1
            if status == "ok":
                status = "high_misfit"
            # automatic lambda at its lower limit: the solver already fits as closely as it allows, so the
            # bed model itself is off; in the width tests this was the case for every wrong-width window
            at_floor = params.solver == "lsq" and params.lam is None and lam_used <= LAM_FALLBACK * (1.0 + 1e-9)
            ev.add("LRLC_DECON_MISFIT", zone_c, 1, f"{c_lo:.1f}-{c_hi:.1f} ft rms {m_rms:.2f}", hint=at_floor)
        sigma_k = xs * s0
        f_win = W @ sigma_k
        own_pos = np.isin(sys_k, np.flatnonzero(owned))
        for pos in np.flatnonzero(own_pos):
            k = sys_k[pos]
            x_bed[k] = xs[pos]
            solved_bed[k] = True
            bound_bed[k] = bool(abs(xs[pos] - 1.0 / R) <= BOUND_RTOL / R or abs(xs[pos] - R) <= BOUND_RTOL * R)
        rel = f_win / np.where(np.isfinite(sa_w), sa_w, np.nan) - 1.0
        for pos in np.flatnonzero(own_pos):
            k = sys_k[pos]
            r0, r1 = row_ptr[k], row_ptr[k + 1]
            wr = np.arange(r0, r1) - win_rows[0]
            sel = (wr >= 0) & (wr < win_rows.size)
            gi = j0 + np.arange(r0, r1)[sel]
            f_row[gi] = f_win[wr[sel]]
            resid_row[gi] = rel[wr[sel]]
        result.windows.append(WindowStat(float(c_lo), float(c_hi), int(A.shape[0]), int(owned.sum()), float(lam_used),
                                         m_rms, m_max, status))

    # step 7: output per row, beds
    for k in range(nb):
        r0, r1 = row_ptr[k], row_ptr[k + 1]
        if r1 <= r0:
            continue
        gi = j0 + np.arange(r0, r1)
        sig = x_bed[k] * sigma0[k] if solved_bed[k] else np.nan
        if not np.isfinite(sig):
            no_data_row[gi] = True
            result.beds.append(Bed(float(edges[k]), float(edges[k + 1]), int(r1 - r0),
                                   float(1.0 / sigma0[k]) if usable[k] else float("nan"), float("nan"), False))
            continue
        bed_bad[gi] = bound_bed[k]
        if params.output == "residual":
            with np.errstate(divide="ignore", invalid="ignore"):
                val = np.where(f_row[gi] > 0, f_row[gi] / (sig * sigma_a[gi]), np.nan)
            rt_row[gi] = val
        else:
            rt_row[gi] = 1.0 / sig
        result.beds.append(Bed(float(edges[k]), float(edges[k + 1]), int(r1 - r0), float(1.0 / sigma0[k]),
                               float(1.0 / sig), bool(bound_bed[k])))


def _issues(ev: _Events, result: DeconResult, params: DeconParams, act: np.ndarray, zones) -> List[tuple]:
    """Turn the counted events into ``(code, text, zone, severity)`` tuples."""
    out: List[tuple] = []
    texts = {
        "LRLC_DECON_NO_HIRES": "Deconvolution: no usable reference curve ({n} samples)",
        "LRLC_DECON_NO_RT": "Deconvolution: no usable resistivity ({n} samples)",
        "LRLC_DECON_UNDERSAMPLED": "Deconvolution: log step too coarse for the response, {n} samples not deconvolved",
        "LRLC_DECON_STEP_IRREGULAR": "Deconvolution: irregular depth step in {n} segment(s); actual depths are used",
        "LRLC_DECON_GAP": "Deconvolution: segment split at a gap or a long run without data ({n} place(s))",
        "LRLC_DECON_BED_MERGED": "Deconvolution: {n} candidate boundaries dropped (thickness or contrast)",
        "LRLC_DECON_BED_EDIT_UNMATCHED": "Deconvolution: {n} boundary removal(s) matched no automatic boundary",
        "LRLC_DECON_AMPLIFIED": "Deconvolution: {n} samples set to NaN (bed on its bound or change above the maximum ratio)",
        "LRLC_DECON_EDGE": "Deconvolution: {n} samples within one FWHM of a segment end set to NaN",
        "LRLC_DECON_MISFIT": "Deconvolution: {n} window(s) fit the measured curve badly; boundaries may be missing",
        "LRLC_DECON_NOT_CONVERGED": "Deconvolution: {n} window(s) did not reach the solver target",
        "LRLC_DECON_WINDOW_SPLIT": "Deconvolution: {n} window(s) split (more than 150 beds)",
    }
    for (code, zone), entry in ev.items.items():
        n = entry["n"]
        text = texts[code].format(n=n)
        if entry["notes"]:
            text += " (" + "; ".join(entry["notes"]) + ")"
        if code == "LRLC_DECON_MISFIT" and entry.get("hint"):
            text += "; the solver already fits as closely as it allows: check the response width and the boundaries"
        severity = None
        if code == "LRLC_DECON_AMPLIFIED":
            n_zone = int(sum(1 for i in np.flatnonzero(act) if zones is None or zones[i] == zone)) if zones is not None \
                else int(act.sum())
            severity = "warning" if n_zone and n > 0.01 * n_zone else "info"
        out.append((code, text, zone, severity))
    return out


WIDTH_FACTORS = (0.8, 1.25)      # response-width sensitivity: solved again at these multiples of the set width
SENSITIVITY_MIN_CHANGE = 1.1     # samples the set-width solve raises by more than 10 % (the thin resistive beds)


def _median_ratio(rt_decon, rt, rows) -> Tuple[Optional[float], int]:
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.asarray(rt_decon, dtype=float)[rows] / np.asarray(rt, dtype=float)[rows]
    ratio = ratio[np.isfinite(ratio)]
    return (float(np.median(ratio)) if ratio.size else None), int(ratio.size)


def width_sensitivity(depth, rt, hires, params: DeconParams, active, base: DeconResult, data_mask=None,
                      zone_labels=None, max_ratio_by_zone=None, misfit_warn_by_zone=None, log_domain=True,
                      factors=WIDTH_FACTORS) -> Dict[str, dict]:
    """Median RT_DECON / RT per zone at the set response width and at ``factors`` times it.

    The samples are those valid at the set width (``base.valid``) that the set-width solve raises by more
    than 10 % (``SENSITIVITY_MIN_CHANGE``): the thin resistive beds the correction acts on, not the shales
    and shoulders it leaves alone or lowers. The same samples are read at every width; a sample that is
    invalid at another width (amplified, for example) is left out of that width's median, and ``n_valid``
    says how many remained. Same beds, edits and solver settings. Information only: the deconvolved Rt
    always depends on the width, so no threshold is applied.

    Returns ``{zone label: {"widths_ft": [low, set, high], "median_ratio": [...], "n_valid": [...], "n": int}}``
    (label ``""`` without zone labels; a median is None when no sample remained).
    """
    w = params.width_ft
    low, high = sorted(factors)
    runs = {1.0: base}
    for f in (low, high):
        runs[f] = deconvolve(depth, rt, hires, params.with_width(w * f), active, data_mask=data_mask,
                             zone_labels=zone_labels, max_ratio_by_zone=max_ratio_by_zone,
                             misfit_warn_by_zone=misfit_warn_by_zone, log_domain=log_domain)
    act = np.asarray(active, dtype=bool)
    with np.errstate(divide="ignore", invalid="ignore"):
        change = np.asarray(base.rt_decon, dtype=float) / np.asarray(rt, dtype=float)
    acted = act & np.asarray(base.valid, dtype=bool) & np.isfinite(change) & (change > SENSITIVITY_MIN_CHANGE)
    zones = None if zone_labels is None else np.asarray(zone_labels, dtype=object)
    labels = [""] if zones is None else sorted({_zone_key(z) for z in zones[act]})
    out: Dict[str, dict] = {}
    for label in labels:
        sel = acted.copy()
        if zones is not None:
            sel &= np.asarray([_zone_key(z) == label for z in zones], dtype=bool)
        medians, counts = zip(*(_median_ratio(runs[f].rt_decon, rt, sel) for f in (low, 1.0, high)))
        out[label] = {"widths_ft": [float(w * low), float(w), float(w * high)],
                      "median_ratio": list(medians), "n_valid": list(counts), "n": int(sel.sum())}
    return out
