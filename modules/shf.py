"""
Saturation-height modelling: Leverett J, Sw(J) fits and free-water-level estimation (pure, no Qt).

Capillary pressure becomes the dimensionless Leverett J-function (Leverett 1941), which
collapses samples of one rock type onto one curve; :func:`fit_core_pc` fits Sw = f(J) to
laboratory Pc curves (a power law or Brooks and Corey 1964) and :func:`sw_shf` evaluates the
fit on the logs from the height above the free water level. :func:`fit_log_sw` fits the
same forms to the log water saturation of a well with a known contact: such a fit is
**not** independent of the resistivity Sw (``basis == "log"``) and is a cross-check only.
:func:`estimate_fwl` scans candidate contacts for the one that best reproduces the log Sw.

Units: Pc in psi, k in mD, porosity as a fraction, sigma*cos(theta) in dyne/cm, density in
g/cc, height in ft. Densities are always passed in explicitly (water density can differ per
zone), never read from a global. Every value in a serialised fit is a plain ``float``,
``int``, ``str``, ``list``, ``dict`` or ``None`` (no NaN), so ``json.dumps`` is stable
across a session save and load.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np
from scipy.optimize import least_squares, minimize_scalar

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# 1 g/cc = 62.428 lb/ft3, divided by 144 in2/ft2 (textbooks round to 0.433).
PSI_PER_FT_PER_GCC = 0.433527

# Leverett J in field units: 1 psi = 68 947.57 dyne/cm2 and 1 mD = 9.869233e-12 cm2, so
# J = Pc[dyne/cm2] * sqrt(k[cm2]/phi) / sigma_cos = J_CONST * Pc[psi] * sqrt(k[mD]/phi) / sigma_cos.
DYNE_CM2_PER_PSI = 68947.57
CM2_PER_MD = 9.869233e-12
J_CONST = DYNE_CM2_PER_PSI * float(np.sqrt(CM2_PER_MD))        # 0.21660
assert abs(J_CONST - 0.2166) < 1e-4

# Default sigma*cos(theta), dyne/cm (magnitude): air-brine 72 at 0 deg, Hg-air |480 cos 140|,
# oil-brine 48 at 30 deg, oil-water 30 at 30 deg, gas-water 50 at 0 deg (Amyx, Bass and
# Whiting 1960; Purcell 1949 for mercury).
SIGMA_COS_DEFAULTS: Dict[str, float] = {
    "air-brine": 72.0, "hg-air": 367.7, "oil-brine": 41.6, "oil-water": 26.0, "gas-water": 50.0,
}
LAB_SYSTEMS = ("air-brine", "hg-air", "oil-brine")
RESERVOIR_SYSTEMS = ("oil-water", "gas-water")

DEFAULT_FLUIDS = {"water": 1.03, "oil": 0.75, "gas": 0.25}      # g/cc, placeholders to confirm

MODELS = ("power", "brooks_corey")
PARAM_NAMES = {"power": ("c", "d"), "brooks_corey": ("J_d", "lam", "Swi")}
BOUNDS = {
    "power": {"c": (1e-3, 10.0), "d": (-6.0, -0.05)},
    "brooks_corey": {"J_d": (1e-3, 20.0), "lam": (0.1, 6.0), "Swi": (0.0, 0.6)},
}
# (minimum samples, minimum points) per model.
MIN_DATA = {"power": (3, 8), "brooks_corey": (5, 15)}

BASIS_CORE = "core_pc"
BASIS_LOG = "log"
STATUS_OK = "ok"
STATUS_INSUFFICIENT = "insufficient data"
STATUS_FAILED = "fit failed"
FWL_OK = "ok"
FWL_NOT_IDENTIFIABLE = "not identifiable"
FWL_INSUFFICIENT = "insufficient data"

LOSS = "soft_l1"
F_SCALE = 0.05
ALL = "All"


# ---------------------------------------------------------------------------
# Plain-data helpers
# ---------------------------------------------------------------------------
def _arr(x) -> np.ndarray:
    return np.asarray(x, dtype=float)


def _plain_float(v) -> Optional[float]:
    """A finite Python float, or None for NaN, inf and None."""
    if v is None:
        return None
    v = float(v)
    return v if np.isfinite(v) else None


def _plain_dict(d) -> Optional[dict]:
    if d is None:
        return None
    return {str(k): _plain_float(v) for k, v in d.items()}


@dataclass
class ShfFit:
    """One saturation-height fit.

    ``model`` is ``"power"`` (``params`` ``c``, ``d``) or ``"brooks_corey"`` (``J_d``, ``lam``,
    ``Swi``); ``basis`` is ``"core_pc"`` (laboratory Pc, independent of the resistivity Sw) or
    ``"log"`` (fitted to the log Sw: a cross-check, never used for pay). ``params`` is None
    when ``status`` is not ``"ok"``. ``se`` holds approximate standard errors,
    ``cov = (J'J)^-1 s^2``. ``rock_type`` is a string, ``"All"`` for a single pooled fit.
    """
    rock_type: str
    model: str
    params: Optional[Dict[str, float]]
    basis: str
    n_samples: int = 0
    n_points: int = 0
    rmse: Optional[float] = None
    bias: Optional[float] = None
    r2: Optional[float] = None
    se: Optional[Dict[str, Optional[float]]] = None
    wells: List[str] = field(default_factory=list)
    weight_by: str = "sample"
    status: str = STATUS_OK
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK and self.params is not None

    def to_dict(self) -> dict:
        return {
            "rock_type": str(self.rock_type), "model": str(self.model),
            "params": _plain_dict(self.params), "basis": str(self.basis),
            "n_samples": int(self.n_samples), "n_points": int(self.n_points),
            "rmse": _plain_float(self.rmse), "bias": _plain_float(self.bias),
            "r2": _plain_float(self.r2), "se": _plain_dict(self.se),
            "wells": [str(w) for w in self.wells], "weight_by": str(self.weight_by),
            "status": str(self.status), "message": str(self.message),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ShfFit":
        params = d.get("params")
        se = d.get("se")
        return cls(
            rock_type=str(d.get("rock_type", ALL)), model=str(d.get("model", "power")),
            params=None if params is None else {str(k): float(v) for k, v in params.items()},
            basis=str(d.get("basis", BASIS_CORE)),
            n_samples=int(d.get("n_samples", 0) or 0), n_points=int(d.get("n_points", 0) or 0),
            rmse=d.get("rmse"), bias=d.get("bias"), r2=d.get("r2"),
            se=None if se is None else {str(k): v for k, v in se.items()},
            wells=[str(w) for w in (d.get("wells") or [])],
            weight_by=str(d.get("weight_by", "sample")), status=str(d.get("status", STATUS_OK)),
            message=str(d.get("message", "")))


@dataclass
class PcCurve:
    """One laboratory Pc sample: arrays of Pc (psi) and Sw (fraction), plus its k, phi and lab sigma*cos(theta).

    For mercury injection give ``sw = 1 - S_Hg`` (:func:`sw_from_hg`).
    """
    pc_psi: Sequence[float]
    sw: Sequence[float]
    k_md: float
    phi: float
    sigma_cos_lab: float
    well: str = ""
    sample: str = ""

    @classmethod
    def coerce(cls, c) -> "PcCurve":
        if isinstance(c, cls):
            return c
        return cls(pc_psi=c["pc_psi"], sw=c["sw"], k_md=c["k_md"], phi=c["phi"],
                   sigma_cos_lab=c["sigma_cos_lab"], well=str(c.get("well", "")),
                   sample=str(c.get("sample", "")))


@dataclass
class ZoneFluids:
    """Densities (g/cc) of one zone: its brine and the hydrocarbon above the contact."""
    water_density: float
    fluid_density: float

    @property
    def delta_rho(self) -> float:
        return float(self.water_density) - float(self.fluid_density)


def delta_rho(fluids) -> float:
    """Density contrast water - hydrocarbon (g/cc) from a :class:`ZoneFluids`, a dict or a number.

    A dict needs ``water_density`` and ``fluid_density``. Raises ``ValueError`` when the
    contrast is not a positive finite number.
    """
    if isinstance(fluids, ZoneFluids):
        d = fluids.delta_rho
    elif isinstance(fluids, dict):
        d = float(fluids["water_density"]) - float(fluids["fluid_density"])
    else:
        d = float(fluids)
    if not np.isfinite(d) or d <= 0:
        raise ValueError(f"density contrast must be positive (got {d:g} g/cc)")
    return d


# ---------------------------------------------------------------------------
# Equations
# ---------------------------------------------------------------------------
def sw_from_hg(s_hg) -> np.ndarray:
    """Water saturation of a mercury-injection point: ``Sw = 1 - S_Hg``."""
    return np.clip(1.0 - _arr(s_hg), 0.0, 1.0)


def lab_to_reservoir(pc_lab, sigma_cos_lab, sigma_cos_res) -> np.ndarray:
    """``Pc_res = Pc_lab * (sigma cos theta)_res / (sigma cos theta)_lab`` (Amyx, Bass and Whiting 1960)."""
    return _arr(pc_lab) * (_arr(sigma_cos_res) / _arr(sigma_cos_lab))


def leverett_j(pc_psi, k_md, phi, sigma_cos) -> np.ndarray:
    """Leverett J-function ``J = 0.2166 * Pc * sqrt(k/phi) / (sigma cos theta)`` (Leverett 1941).

    Pc in psi, k in mD, sigma cos theta in dyne/cm. J is the same from laboratory or
    reservoir Pc as long as ``sigma_cos`` matches. NaN where k or phi is not positive.
    """
    pc, k, p, s = np.broadcast_arrays(_arr(pc_psi), _arr(k_md), _arr(phi), _arr(sigma_cos))
    ok = (k > 0) & (p > 0) & (s > 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        root = np.sqrt(np.where(ok, k, np.nan) / np.where(ok, p, np.nan))
        return J_CONST * pc * root / np.where(ok, s, np.nan)


def height_from_pc(pc_res_psi, delta_rho_gcc) -> np.ndarray:
    """Height above the free water level ``h = Pc_res / (0.433527 * delta_rho)`` (ft)."""
    return _arr(pc_res_psi) / (PSI_PER_FT_PER_GCC * delta_rho(delta_rho_gcc))


def pc_from_height(h_ft, delta_rho_gcc) -> np.ndarray:
    """Reservoir capillary pressure at height ``h``: ``Pc_res = 0.433527 * delta_rho * h`` (psi)."""
    return PSI_PER_FT_PER_GCC * delta_rho(delta_rho_gcc) * _arr(h_ft)


def j_at_height(h_ft, k_md, phi, delta_rho_gcc, sigma_cos_res) -> np.ndarray:
    """J on the logs at height ``h``: ``0.2166 * 0.433527 * delta_rho * h * sqrt(k/phi) / (sigma cos theta)_res``."""
    return leverett_j(pc_from_height(h_ft, delta_rho_gcc), k_md, phi, sigma_cos_res)


def sw_from_j(j, model: str, params: dict) -> np.ndarray:
    """Water saturation from J for a fit form, clipped to [0, 1].

    ``power``: ``Sw = min(1, c * J^d)`` (the industry power-law J curve, entry J
    ``c^(-1/d)``). ``brooks_corey``: ``Se = (J_d/J)^lam`` for ``J > J_d`` else 1 and
    ``Sw = Swi + (1 - Swi) * Se`` (Brooks and Corey 1964). Sw is 1 where J <= 0 (no
    capillary pressure) and NaN where J is NaN.
    """
    j = _arr(j)
    nan = np.isnan(j)
    pos = np.where(nan | (j <= 0), 1.0, j)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        if model == "power":
            sw = np.minimum(1.0, params["c"] * pos ** params["d"])
        elif model == "brooks_corey":
            se = np.minimum(1.0, (params["J_d"] / pos) ** params["lam"])
            sw = params["Swi"] + (1.0 - params["Swi"]) * se
        else:
            raise ValueError(f"unknown saturation-height model {model!r}")
    sw = np.where(j <= 0, 1.0, sw)
    return np.where(nan, np.nan, np.clip(sw, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------
def _start_values(model, j, sw):
    lo = {n: b[0] for n, b in BOUNDS[model].items()}
    hi = {n: b[1] for n, b in BOUNDS[model].items()}

    def clip(p):
        return {n: float(min(max(v, lo[n] * 1.0001 if lo[n] > 0 else lo[n] + 1e-4), hi[n] * 0.9999
                             if hi[n] > 0 else hi[n] - 1e-4)) for n, v in p.items()}

    order = np.argsort(j)
    js, ss = j[order], sw[order]
    if model == "power":
        sel = (ss > 0) & (ss < 0.99)
        if sel.sum() >= 2 and np.ptp(np.log(js[sel])) > 0:
            d, ln_c = np.polyfit(np.log(js[sel]), np.log(ss[sel]), 1)
        else:
            d, ln_c = -0.5, np.log(0.3)
        if d >= 0:
            d = -0.5
        return [clip({"c": float(np.exp(ln_c)), "d": float(d)})]
    swi = 0.5 * float(np.min(sw))
    below = np.where(ss < 0.99)[0]
    jd = float(js[below[0]]) if len(below) else float(np.median(js))
    se = (ss - swi) / (1.0 - swi)
    n = len(js)
    mid = slice(n // 3, max(n // 3 + 2, n - n // 3))
    jm, sm = js[mid], se[mid]
    keep = (sm > 0) & (sm < 1)
    lam = 1.0
    if keep.sum() >= 2 and np.ptp(np.log(jm[keep])) > 0:
        lam = -float(np.polyfit(np.log(jm[keep]), np.log(sm[keep]), 1)[0])
    if not np.isfinite(lam) or lam <= 0:
        lam = 1.0
    starts = [clip({"J_d": jd, "lam": lam, "Swi": swi}),
              clip({"J_d": jd * 0.5, "lam": lam, "Swi": swi}),
              clip({"J_d": jd * 2.0, "lam": lam, "Swi": swi}),
              clip({"J_d": jd, "lam": lam * 0.5, "Swi": swi}),
              clip({"J_d": jd, "lam": lam * 2.0, "Swi": swi})]
    return starts


def _fit_j(model, j, sw, sample_id, weight_by):
    """Robust bounded least squares of Sw(J); returns ``(params, se, rmse, bias, r2)`` or raises ``RuntimeError``."""
    names = PARAM_NAMES[model]
    lo = np.array([BOUNDS[model][n][0] for n in names])
    hi = np.array([BOUNDS[model][n][1] for n in names])
    if weight_by == "point":
        w = np.ones(len(j))
    else:
        _, inv, counts = np.unique(sample_id, return_inverse=True, return_counts=True)
        w = 1.0 / counts[inv]
        w = w * len(w) / w.sum()            # mean weight 1, so f_scale keeps its meaning
    sqw = np.sqrt(w)

    def resid(x):
        return (sw_from_j(j, model, dict(zip(names, x))) - sw) * sqw

    best = None
    for start in _start_values(model, j, sw):
        x0 = np.array([start[n] for n in names])
        try:
            res = least_squares(resid, x0, bounds=(lo, hi), method="trf", loss=LOSS,
                                f_scale=F_SCALE, x_scale="jac")
        except (ValueError, FloatingPointError) as exc:
            raise RuntimeError(str(exc)) from exc
        if best is None or res.cost < best.cost:
            best = res
    if best is None or not np.all(np.isfinite(best.x)):
        raise RuntimeError("no finite solution")
    params = {n: float(v) for n, v in zip(names, best.x)}
    fitted = sw_from_j(j, model, params)
    r = fitted - sw
    rmse = float(np.sqrt(np.mean(r ** 2)))
    bias = float(np.mean(r))
    sstot = float(np.sum((sw - np.mean(sw)) ** 2))
    r2 = 1.0 - float(np.sum(r ** 2)) / sstot if sstot > 0 else None
    se = {n: None for n in names}
    dof = len(j) - len(names)
    if dof > 0:
        try:
            jac = best.jac
            cov = np.linalg.pinv(jac.T @ jac) * (float(np.sum(resid(best.x) ** 2)) / dof)
            se = {n: _plain_float(np.sqrt(abs(cov[i, i]))) for i, n in enumerate(names)}
        except np.linalg.LinAlgError:
            pass
    return params, se, rmse, bias, r2


def _check_model(model):
    if model not in MODELS:
        raise ValueError(f"unknown saturation-height model {model!r}; use one of {MODELS}")


def _insufficient(rock_type, model, basis, n_samples, n_points, weight_by, wells, need):
    return ShfFit(rock_type=str(rock_type), model=model, params=None, basis=basis,
                  n_samples=n_samples, n_points=n_points, wells=wells, weight_by=weight_by,
                  status=STATUS_INSUFFICIENT,
                  message=(f"{model} needs at least {need[0]} samples and {need[1]} points; "
                           f"got {n_samples} samples and {n_points} points"))


def fit_core_pc(curves, rock_type, model="power", weight_by="sample", min_pc_psi=0.0) -> ShfFit:
    """Fit Sw = f(J) to laboratory Pc curves of one rock type (``basis`` ``"core_pc"``).

    ``curves`` is a list of :class:`PcCurve` (or dicts with the same keys). J comes from each
    sample's lab Pc, k, phi and lab sigma cos theta, so no reservoir conversion enters.
    Points with Pc <= ``min_pc_psi`` (closure), non-finite values, Sw outside (0, 1] or
    non-positive k or phi are dropped. The fit is a bounded robust least squares
    (``soft_l1``, f_scale 0.05) of Sw residuals. ``weight_by="sample"`` gives each sample the
    weight 1/n_points so a long MICP curve does not drown a short porous-plate one;
    ``"point"`` weights points equally. Below the minimum data (power: 3 samples and 8
    points; Brooks-Corey: 5 and 15) the status is ``"insufficient data"`` and ``params`` is None.
    """
    _check_model(model)
    if weight_by not in ("sample", "point"):
        raise ValueError("weight_by must be 'sample' or 'point'")
    js, sws, ids, wells = [], [], [], []
    for i, c in enumerate(PcCurve.coerce(c) for c in curves):
        pc, sw = _arr(c.pc_psi), _arr(c.sw)
        if pc.shape != sw.shape:
            raise ValueError("pc_psi and sw must have the same length")
        j = leverett_j(pc, c.k_md, c.phi, c.sigma_cos_lab)
        ok = (np.isfinite(j) & (j > 0) & np.isfinite(sw) & (sw > 0) & (sw <= 1.0)
              & (pc > float(min_pc_psi)))
        if not ok.any():
            continue
        js.append(j[ok])
        sws.append(sw[ok])
        ids.append(np.full(int(ok.sum()), i))
        if c.well and c.well not in wells:
            wells.append(c.well)
    j = np.concatenate(js) if js else np.array([])
    sw = np.concatenate(sws) if sws else np.array([])
    sid = np.concatenate(ids) if ids else np.array([], dtype=int)
    n_samples, n_points = len(js), int(len(j))
    need = MIN_DATA[model]
    if n_samples < need[0] or n_points < need[1]:
        return _insufficient(rock_type, model, BASIS_CORE, n_samples, n_points, weight_by, wells, need)
    return _finish(rock_type, model, BASIS_CORE, j, sw, sid, n_samples, n_points, weight_by, wells)


def _finish(rock_type, model, basis, j, sw, sid, n_samples, n_points, weight_by, wells):
    try:
        params, se, rmse, bias, r2 = _fit_j(model, j, sw, sid, weight_by)
    except RuntimeError as exc:
        return ShfFit(rock_type=str(rock_type), model=model, params=None, basis=basis,
                      n_samples=n_samples, n_points=n_points, wells=wells, weight_by=weight_by,
                      status=STATUS_FAILED, message=str(exc))
    return ShfFit(rock_type=str(rock_type), model=model, params=params, basis=basis,
                  n_samples=n_samples, n_points=n_points, rmse=rmse, bias=bias, r2=r2, se=se,
                  wells=wells, weight_by=weight_by, status=STATUS_OK)


def fit_log_sw(h, k, phi, sw, rock_type, model, fluids, sigma_cos_res, wells=None) -> ShfFit:
    """Fit Sw = f(J) to log water saturation against height above a known FWL (``basis`` ``"log"``).

    Not independent of the resistivity Sw (it is fitted to it): the result smooths Sw along
    a hydrostatic profile and is a cross-check, never a source of pay saturation. ``h`` is
    height above the FWL in ft (samples at or below the contact are dropped), ``k`` and
    ``phi`` the log permeability (mD) and porosity, ``sw`` the log Sw (samples with Sw >= 1
    are dropped), ``fluids`` a :class:`ZoneFluids`, dict or density contrast (g/cc) and
    ``sigma_cos_res`` the reservoir sigma cos theta (dyne/cm). Every sample is one point and
    one sample, with equal weight; the minimum data are those of :func:`fit_core_pc`.
    """
    _check_model(model)
    drho = delta_rho(fluids)
    h, k, phi, sw = (_arr(a) for a in (h, k, phi, sw))
    j = j_at_height(h, k, phi, drho, sigma_cos_res)
    ok = np.isfinite(j) & (j > 0) & np.isfinite(sw) & (sw > 0) & (sw < 1.0) & (h > 0)
    j, sw = j[ok], sw[ok]
    n = int(len(j))
    wells = [str(w) for w in (wells or [])]
    need = MIN_DATA[model]
    if n < need[0] or n < need[1]:
        return _insufficient(rock_type, model, BASIS_LOG, n, n, "point", wells, need)
    return _finish(rock_type, model, BASIS_LOG, j, sw, np.arange(n), n, n, "point", wells)


def sw_shf(hafwl_ft, k_md, phi, fit: ShfFit, fluids_for_zone, sigma_cos_res) -> np.ndarray:
    """Water saturation from a fit at height above the FWL, vectorised on arrays.

    ``fluids_for_zone`` supplies the zone's density contrast (:class:`ZoneFluids`, dict or
    number); ``sigma_cos_res`` is the reservoir sigma cos theta (dyne/cm). Sw is 1 at or below
    the contact (h <= 0) and NaN where height, k or phi is not finite or k or phi is not
    positive, or where the fit has no parameters.
    """
    h, k, p = np.broadcast_arrays(_arr(hafwl_ft), _arr(k_md), _arr(phi))
    if fit is None or not fit.ok:
        return np.full(h.shape, np.nan)
    j = j_at_height(h, k, p, delta_rho(fluids_for_zone), sigma_cos_res)
    sw = sw_from_j(np.where(h <= 0, 0.0, j), fit.model, fit.params)
    bad = ~np.isfinite(h) | ~np.isfinite(k) | ~np.isfinite(p) | (k <= 0) | (p <= 0)
    return np.where(bad, np.nan, sw)


# ---------------------------------------------------------------------------
# Free water level
# ---------------------------------------------------------------------------
@dataclass
class FwlEstimate:
    """Result of :func:`estimate_fwl`.

    ``status`` is ``"ok"``, ``"not identifiable"`` (no transition zone in the logs: the
    result cannot be accepted, ``fwl_ft`` is None) or ``"insufficient data"``. ``interval_ft``
    is the FWL range whose RMSE is within 5 % of the minimum; ``grid_ft`` and
    ``rmse_profile`` are the scan for the profile plot.
    """
    status: str
    fwl_ft: Optional[float] = None
    rmse: Optional[float] = None
    interval_ft: Optional[List[float]] = None
    grid_ft: List[float] = field(default_factory=list)
    rmse_profile: List[Optional[float]] = field(default_factory=list)
    n_samples: int = 0
    reason: str = ""

    @property
    def identifiable(self) -> bool:
        return self.status == FWL_OK and self.fwl_ft is not None

    def to_dict(self) -> dict:
        return {
            "status": str(self.status), "fwl_ft": _plain_float(self.fwl_ft),
            "rmse": _plain_float(self.rmse),
            "interval_ft": None if self.interval_ft is None else [float(v) for v in self.interval_ft],
            "grid_ft": [float(v) for v in self.grid_ft],
            "rmse_profile": [_plain_float(v) for v in self.rmse_profile],
            "n_samples": int(self.n_samples), "reason": str(self.reason),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FwlEstimate":
        return cls(status=str(d.get("status", FWL_INSUFFICIENT)), fwl_ft=d.get("fwl_ft"),
                   rmse=d.get("rmse"), interval_ft=d.get("interval_ft"),
                   grid_ft=list(d.get("grid_ft") or []), rmse_profile=list(d.get("rmse_profile") or []),
                   n_samples=int(d.get("n_samples", 0) or 0), reason=str(d.get("reason", "")))


FWL_SEARCH_DEFAULTS = {"half_range_ft": 600.0, "step_ft": 1.0, "sw_cutoff": 0.5,
                       "robust_resid": 0.35, "min_samples": 10, "flat_fraction": 0.10,
                       "interval_fraction": 0.05}


def estimate_fwl(tvd, k, phi, sw_log, rock_types, fits, fluids, sigma_cos_res,
                 search=None, weights=None) -> FwlEstimate:
    """Estimate the free water level that best reproduces the log Sw with the fitted curves.

    Inputs are per net-reservoir sample: ``tvd`` (ft), ``k`` (mD), ``phi``, the log ``sw_log``
    and ``rock_types`` (labels; ``fits`` is a dict keyed by ``str(label)``, with ``"All"`` as the
    fallback; samples with no fit are ignored). ``fluids`` is the zone's :class:`ZoneFluids`,
    dict or density contrast, so a zone with its own brine density is honoured. The
    candidates are a ``step_ft`` grid of +/- ``half_range_ft`` around the deepest sample with
    ``sw_log < sw_cutoff``, refined with a bounded scalar minimisation. The objective is
    ``sqrt(mean(w * (Sw_log - Sw_shf)^2))`` where samples with ``|resid| > robust_resid``
    get half weight. The result is ``"not identifiable"`` when there is no hydrocarbon
    sample, when the best FWL or the within-5 % interval touches the search edge, or when the
    RMSE profile is flat (range < 10 % of its mean). ``search`` overrides
    ``FWL_SEARCH_DEFAULTS``.
    """
    s = dict(FWL_SEARCH_DEFAULTS)
    s.update(search or {})
    drho = delta_rho(fluids)
    tvd, k, phi, sw = (_arr(a) for a in (tvd, k, phi, sw_log))
    labels = np.array([str(x) for x in np.asarray(rock_types, dtype=object)], dtype=object)
    w0 = np.ones(len(tvd)) if weights is None else _arr(weights)
    groups = []
    keep = np.isfinite(tvd) & np.isfinite(k) & np.isfinite(phi) & np.isfinite(sw) & (k > 0) & (phi > 0)
    for lab in pd_unique(labels):
        fit = fits.get(lab) or fits.get(ALL)
        if fit is None or not fit.ok:
            continue
        m = keep & (labels == lab)
        if m.any():
            groups.append((m, fit))
    used = np.zeros(len(tvd), dtype=bool)
    for m, _ in groups:
        used |= m
    n = int(used.sum())
    if n < int(s["min_samples"]):
        return FwlEstimate(FWL_INSUFFICIENT, n_samples=n,
                           reason=f"{n} usable samples, at least {int(s['min_samples'])} needed")
    hc = used & (sw < float(s["sw_cutoff"]))
    if not hc.any():
        return FwlEstimate(FWL_NOT_IDENTIFIABLE, n_samples=n,
                           reason="no hydrocarbon-bearing sample (not identifiable: no transition zone in the logs)")
    centre = float(np.max(tvd[hc]))
    grid = np.arange(centre - s["half_range_ft"], centre + s["half_range_ft"] + 0.5 * s["step_ft"],
                     s["step_ft"])

    def objective(fwl):
        sq = np.zeros(len(tvd))
        for m, fit in groups:
            model = sw_shf(fwl - tvd[m], k[m], phi[m], fit, drho, sigma_cos_res)
            sq[m] = (sw[m] - model) ** 2
        r = np.sqrt(sq[used])
        w = np.where(r > s["robust_resid"], 0.5, 1.0) * w0[used]
        val = float(np.sqrt(np.nanmean(w * sq[used])))
        return val if np.isfinite(val) else np.inf

    prof = np.array([objective(f) for f in grid])
    if not np.isfinite(prof).any():
        return FwlEstimate(FWL_NOT_IDENTIFIABLE, n_samples=n, reason="objective is undefined on the grid")
    ib = int(np.argmin(prof))
    lo_b, hi_b = grid[max(ib - 1, 0)], grid[min(ib + 1, len(grid) - 1)]
    best, best_val = float(grid[ib]), float(prof[ib])
    if hi_b > lo_b:
        res = minimize_scalar(objective, bounds=(lo_b, hi_b), method="bounded",
                              options={"xatol": 1e-3})
        if np.isfinite(res.fun) and res.fun < best_val:
            best, best_val = float(res.x), float(res.fun)
    thr = best_val * (1.0 + float(s["interval_fraction"]))
    inside = prof <= thr
    lo_i = ib
    while lo_i > 0 and inside[lo_i - 1]:
        lo_i -= 1
    hi_i = ib
    while hi_i < len(grid) - 1 and inside[hi_i + 1]:
        hi_i += 1
    interval = [float(grid[lo_i]), float(grid[hi_i])]
    finite = prof[np.isfinite(prof)]
    mean = float(np.mean(finite))
    reason = ""
    if ib in (0, len(grid) - 1):
        reason = "the minimum is at the search edge"
    elif lo_i == 0 or hi_i == len(grid) - 1:
        reason = "the best-fit interval reaches the search edge"
    elif mean <= 0 or (float(np.max(finite)) - float(np.min(finite))) < float(s["flat_fraction"]) * mean:
        reason = "the RMSE profile is flat"
    profile = [_plain_float(v) for v in prof]
    if reason:
        return FwlEstimate(FWL_NOT_IDENTIFIABLE, rmse=_plain_float(best_val), interval_ft=interval,
                           grid_ft=[float(g) for g in grid], rmse_profile=profile, n_samples=n,
                           reason=f"not identifiable (no transition zone in the logs): {reason}")
    return FwlEstimate(FWL_OK, fwl_ft=best, rmse=best_val, interval_ft=interval,
                       grid_ft=[float(g) for g in grid], rmse_profile=profile, n_samples=n)


def pd_unique(labels) -> list:
    """Unique labels in first-seen order."""
    seen, out = set(), []
    for x in labels:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out
