"""Radial invasion correction (step profile), chain step ``invasion`` (pure: numpy only, no Qt, no pipeline import).

Model, in the conductivity domain, for a tool ``i`` with 50 percent radial diameter ``r_i`` and shape ``p``::

    J_i(di) = 1 / (1 + (r_i / di) ** p)          pseudo-geometric factor (share of signal inside the invaded cylinder)
    Ca_i    = J_i * Cxo + (1 - J_i) * Ct         apparent conductivity,   Ra_i = 1 / Ca_i

Unknowns per sample: ``Rt``, ``Rxo`` (or fixed from a micro-resistivity curve) and the invasion diameter ``di``.
The inversion is vectorised over samples: a closed-form variable-projection start on a diameter grid, then a
batched Levenberg-Marquardt iteration in log space with analytic derivatives.

The tool presets are generic placeholders, not specifications of any tool: confirm them against the chart book of
the tool that was run. Borehole, mud and shoulder-bed corrections of the input curves are the user's responsibility.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from modules.lrlc import chain
from modules.lrlc.chain import CHAIN_ORDER, ChainContext, StepResult, StepSpec
from modules.param_scopes import arps_factor

REFS = ("doll1949", "anderson2001", "arps1953")
GENERIC_LABEL = "generic, confirm with tool charts"

GENERIC_TOOLS: Dict[str, dict] = {
    "generic_induction": {"deep": 80.0, "medium": 45.0, "shallow": 20.0, "p": 2.5, "label": GENERIC_LABEL},
    "generic_laterolog": {"deep": 70.0, "medium": 35.0, "shallow": 25.0, "p": 2.5, "label": GENERIC_LABEL},
}

DEFAULT_RT_BOUNDS = (0.05, 20000.0)
DEFAULT_CHUNK = 20000
DEFAULT_MAX_ITER = 40
GRID_SIZE = 48
_WORK_CHUNK = 5000          # cap that keeps the working arrays small whatever ``chunk`` says
_RXO_BOUNDS = (1e-3, 1e6)
_TOL = 1e-6

OK, NONUNIQUE, FAILED, DI_UPPER, DI_LOWER, POOR_FIT, MISSING = range(7)
STATUS_NAMES = ("ok", "nonunique", "failed", "di_upper", "di_lower", "poor_fit", "missing")
COUNT_KEYS = ("ok", "nonunique", "failed", "di_upper", "di_lower", "poor_fit", "missing",
              "curves_missing", "rxo_below_rmf", "generic", "rmf_missing", "no_temperature", "setting_invalid")


# ---------------------------------------------------------------------------
# Forward model
# ---------------------------------------------------------------------------
def pseudo_geometric_factor(di, r50, p):
    """``J = 1 / (1 + (r50 / di) ** p)``; broadcasts."""
    return 1.0 / (1.0 + (np.asarray(r50, dtype=float) / np.asarray(di, dtype=float)) ** p)


def forward_ra(rt, rxo, di, r50, p):
    """Apparent resistivity of each tool; ``r50`` has one entry per tool and the result gains that last axis."""
    rt, rxo, di = (np.asarray(v, dtype=float)[..., None] for v in (rt, rxo, di))
    j = pseudo_geometric_factor(di, np.asarray(r50, dtype=float), p)
    return 1.0 / (j / rxo + (1.0 - j) / rt)


def rmf_at_temperature(rmf, rmf_temp_f, temp_f):
    """Mud-filtrate resistivity brought from ``rmf_temp_f`` to ``temp_f`` (Arps, degF); scalars or arrays."""
    return rmf * arps_factor(temp_f, rmf_temp_f)


# ---------------------------------------------------------------------------
# Inversion
# ---------------------------------------------------------------------------
@dataclass
class InvasionFit:
    rt: np.ndarray                  # undisturbed Rt (NaN where invalid)
    rxo: np.ndarray                 # fitted or observed Rxo
    di: np.ndarray                  # invasion diameter (NaN where non-unique or invalid)
    valid: np.ndarray               # bool
    status: np.ndarray              # int codes, see STATUS_NAMES
    counts: Dict[str, int] = field(default_factory=dict)


def _grid_start(cm, use, fixed, cxo_fix, jg, dgrid):
    """Variable projection: for each sample the best (Ct, Cxo, di) on the diameter grid (closed form per di)."""
    w2 = use / cm ** 2
    w1 = use / cm
    a = 1.0 - jg
    saa = w2 @ (a * a).T
    sab = w2 @ (a * jg).T
    sbb = w2 @ (jg * jg).T
    sa = w1 @ a.T
    sb = w1 @ jg.T
    s0 = use.sum(axis=1)[:, None]
    with np.errstate(all="ignore"):
        det = saa * sbb - sab * sab
        ct_f = (sa * sbb - sab * sb) / det
        cx_f = (saa * sb - sab * sa) / det
        cx_x = cxo_fix[:, None] * np.ones_like(saa)
        ct_x = (sa - sab * cx_x) / saa
        fx = fixed[:, None]
        ct = np.where(fx, ct_x, ct_f)
        cx = np.where(fx, cx_x, cx_f)
        cost = saa * ct * ct + 2.0 * sab * ct * cx + sbb * cx * cx - 2.0 * sa * ct - 2.0 * sb * cx + s0
        bad = ~(np.isfinite(cost) & (ct > 0) & (cx > 0))
        cost = np.where(bad, np.inf, cost)
    g = np.argmin(cost, axis=1)
    rows = np.arange(len(g))
    ok = np.isfinite(cost[rows, g])
    ct0, cx0, d0 = ct[rows, g], cx[rows, g], dgrid[g]
    # fallback start when no grid diameter gives positive conductivities
    cmax = np.where(use > 0, cm, -np.inf).max(axis=1)
    cmin = np.where(use > 0, cm, np.inf).min(axis=1)
    ct0 = np.where(ok, ct0, cmin)
    cx0 = np.where(ok, cx0, np.where(fixed, cxo_fix, cmax))
    d0 = np.where(ok, d0, np.sqrt(dgrid[0] * dgrid[-1]))
    return ct0, cx0, d0


def _model(x, lnram, use, r50, p, want_jac):
    """Residuals ``f = ln Ra_model - ln Ra_meas`` (zero where unused), cost and optionally the (m, K, 3) Jacobian."""
    ct = np.exp(-x[:, 0])[:, None]
    cx = np.exp(-x[:, 1])[:, None]
    q = (r50[None, :] / np.exp(x[:, 2])[:, None]) ** p
    j = 1.0 / (1.0 + q)
    c = j * cx + (1.0 - j) * ct
    f = (-np.log(c) - lnram) * use
    cost = (f * f).sum(axis=1)
    if not want_jac:
        return f, cost, None
    jac = np.empty(f.shape + (3,))
    jac[..., 0] = (1.0 - j) * ct / c
    jac[..., 1] = j * cx / c
    jac[..., 2] = -(cx - ct) * p * q * j * j / c
    jac *= use[..., None]
    return f, cost, jac


def _lm(x0, lnram, use, free_v, r50, p, lo, hi, max_iter):
    """Batched Levenberg-Marquardt; returns (x, converged, cost)."""
    n = len(x0)
    x = x0.copy()
    lam = np.full(n, 1e-3)
    active = np.ones(n, dtype=bool)
    conv = np.zeros(n, dtype=bool)
    eye = np.eye(3)
    for _ in range(max_iter):
        idx = np.flatnonzero(active)
        if idx.size == 0:
            break
        xa, ua, fv = x[idx], use[idx], free_v[idx]
        f, cost, jac = _model(xa, lnram[idx], ua, r50, p, True)
        jac[:, :, 1] *= fv[:, None]
        a = np.einsum("mki,mkj->mij", jac, jac)
        g = np.einsum("mki,mk->mi", jac, f)
        a_d = a + lam[idx, None, None] * a * eye + 1e-12 * eye
        a_d[:, 1, 1] += (~fv)
        try:
            delta = -np.linalg.solve(a_d, g[..., None])[..., 0]
        except np.linalg.LinAlgError:       # pragma: no cover - ridge makes this very unlikely
            delta = np.zeros_like(g)
        delta[:, 1] *= fv
        xn = np.clip(xa + delta, lo[idx], hi[idx])
        xn[:, 1] = np.where(fv, xn[:, 1], xa[:, 1])
        _, cost_n, _ = _model(xn, lnram[idx], ua, r50, p, False)
        accept = np.isfinite(cost_n) & (cost_n <= cost)
        step = np.abs(xn - xa).max(axis=1)
        acc_i = idx[accept]
        x[acc_i] = xn[accept]
        lam[acc_i] = np.maximum(lam[acc_i] * 0.3, 1e-12)
        done = accept & (step < _TOL)
        rej_i = idx[~accept]
        lam[rej_i] *= 5.0
        stuck = ~accept & (lam[idx] > 1e12)
        conv[idx[done | stuck]] = True
        active[idx[done | stuck]] = False
    cost = _model(x, lnram, use, r50, p, False)[1]
    return x, conv, cost


def fit_invasion(rt, rm=None, rs=None, rxo=None, *, r50, p=2.5, rxo_mode="fixed",
                 di_min=8.0, di_max=120.0, min_contrast=1.15, max_rms=0.15,
                 rt_bounds=DEFAULT_RT_BOUNDS, rmf_t=None, chunk=DEFAULT_CHUNK,
                 max_iter=DEFAULT_MAX_ITER) -> InvasionFit:
    """Per-sample step-profile inversion.

    ``rt`` is the deep input, ``rm`` / ``rs`` the medium and shallow curves, ``rxo`` the optional micro-resistivity
    (used as a fixed Rxo when ``rxo_mode == "fixed"``). ``r50`` is ``(deep, medium, shallow)`` in inches (a dict with
    those keys is accepted). ``rmf_t`` (scalar or per-sample, ohm.m at formation temperature) is a lower bound of Rxo.
    """
    rt = np.atleast_1d(np.asarray(rt, dtype=float))
    n = len(rt)
    if isinstance(r50, dict):
        r50 = (r50["deep"], r50["medium"], r50["shallow"])
    r50 = np.asarray(r50, dtype=float)

    def col(v):
        if v is None:
            return np.full(n, np.nan)
        return np.array(np.broadcast_to(np.asarray(v, dtype=float), (n,)))

    ram = np.stack([rt, col(rm), col(rs)], axis=1)
    rxo_a = col(rxo) if rxo_mode == "fixed" else np.full(n, np.nan)
    with np.errstate(invalid="ignore"):
        use_all = np.isfinite(ram) & (ram > 0)
        fixed = np.isfinite(rxo_a) & (rxo_a > 0)
    counts = {k: 0 for k in COUNT_KEYS}

    rm_av, rs_av = use_all[:, 1].any(), use_all[:, 2].any()
    rxo_av = fixed.any()
    if not ((rm_av and rs_av) or ((rm_av or rs_av) and rxo_av)):
        counts["curves_missing"] = n
        counts["missing"] = n
        nan = np.full(n, np.nan)
        return InvasionFit(nan.copy(), nan.copy(), nan.copy(), np.zeros(n, bool),
                           np.full(n, MISSING, dtype=int), counts)

    need_ok = np.where(fixed, use_all[:, 0] & (use_all[:, 1] | use_all[:, 2]), use_all.all(axis=1))
    use = np.where(need_ok[:, None], use_all, False).astype(float)
    cm = np.where(use > 0, 1.0 / np.where(use > 0, ram, 1.0), 1.0)
    cxo_fix = np.where(fixed, 1.0 / np.where(fixed, rxo_a, 1.0), 1.0)
    fixed = fixed & need_ok

    # non-unique: the conductivities (including a fixed Rxo) barely differ
    cmax = np.maximum(np.where(use > 0, cm, -np.inf).max(axis=1), np.where(fixed, cxo_fix, -np.inf))
    cmin = np.minimum(np.where(use > 0, cm, np.inf).min(axis=1), np.where(fixed, cxo_fix, np.inf))
    with np.errstate(invalid="ignore", divide="ignore"):
        nonuni = need_ok & (cmax / cmin < min_contrast)
    todo = need_ok & ~nonuni

    status = np.full(n, MISSING, dtype=int)
    status[nonuni] = NONUNIQUE
    out_rt = np.full(n, np.nan)
    out_rxo = np.full(n, np.nan)
    out_di = np.full(n, np.nan)
    out_rt[nonuni] = rt[nonuni]
    out_rxo[fixed] = rxo_a[fixed]

    rmf_arr = None if rmf_t is None else col(rmf_t)
    di_min, di_max = float(di_min), float(di_max)
    dgrid = np.geomspace(di_min, di_max, GRID_SIZE)
    jg = pseudo_geometric_factor(dgrid[:, None], r50[None, :], p)
    n_obs = use.sum(axis=1)
    n_unk = np.where(fixed, 2, 3)
    rmf_hit = np.zeros(n, dtype=bool)
    work = max(1, min(int(chunk), _WORK_CHUNK))

    ids = np.flatnonzero(todo)
    for s in range(0, len(ids), work):
        sel = ids[s:s + work]
        u_, f_, cx_ = use[sel], fixed[sel], cxo_fix[sel]
        ct0, cx0, d0 = _grid_start(cm[sel], u_, f_, cx_, jg, dgrid)
        cx0 = np.where(f_, cx_, cx0)
        x0 = np.stack([-np.log(ct0), -np.log(cx0), np.log(d0)], axis=1)
        lo = np.empty_like(x0)
        hi = np.empty_like(x0)
        lo[:, 0], hi[:, 0] = np.log(rt_bounds[0]), np.log(rt_bounds[1])
        lo[:, 1], hi[:, 1] = np.log(_RXO_BOUNDS[0]), np.log(_RXO_BOUNDS[1])
        if rmf_arr is not None:
            with np.errstate(invalid="ignore"):
                lo[:, 1] = np.where(np.isfinite(rmf_arr[sel]) & (rmf_arr[sel] > 0),
                                    np.maximum(lo[:, 1], np.log(np.where(rmf_arr[sel] > 0, rmf_arr[sel], 1.0))), lo[:, 1])
        lo[:, 2], hi[:, 2] = np.log(di_min), np.log(di_max)
        x0 = np.clip(x0, lo, hi)
        x0[:, 1] = np.where(f_, np.log(1.0 / cx_), x0[:, 1])
        lnram = np.log(1.0 / cm[sel])
        x, conv, cost = _lm(x0, lnram, u_, ~f_, r50, p, lo, hi, int(max_iter))
        rt_f, rxo_f, di_f = np.exp(x[:, 0]), np.exp(x[:, 1]), np.exp(x[:, 2])
        rms = np.sqrt(cost / np.maximum(n_obs[sel], 1.0))
        st = np.full(len(sel), OK, dtype=int)
        redundant = n_obs[sel] > n_unk[sel]
        st[redundant & (rms > max_rms)] = POOR_FIT
        st[di_f <= 1.01 * di_min] = DI_LOWER
        st[di_f >= 0.99 * di_max] = DI_UPPER
        st[~conv] = FAILED
        status[sel] = st
        good = (st == OK) | (st == DI_LOWER)
        out_rt[sel] = np.where(good, rt_f, np.nan)
        out_rxo[sel] = np.where(f_, rxo_a[sel], np.where(good, rxo_f, np.nan))
        out_di[sel] = np.where(good, di_f, np.nan)
        if rmf_arr is not None:
            with np.errstate(invalid="ignore"):
                at_bound = ~f_ & (x[:, 1] <= lo[:, 1] + 1e-9) & (lo[:, 1] > np.log(_RXO_BOUNDS[0]) + 1e-9)
            rmf_hit[sel] = at_bound

    if rmf_arr is not None:
        with np.errstate(invalid="ignore"):
            rmf_hit |= fixed & np.isfinite(rmf_arr) & (rxo_a < rmf_arr)
    valid = (status == OK) | (status == DI_LOWER) | (status == NONUNIQUE)
    for code, name in enumerate(STATUS_NAMES):
        counts[name] = int((status == code).sum())
    counts["rxo_below_rmf"] = int((rmf_hit & valid).sum())
    return InvasionFit(out_rt, out_rxo, out_di, valid, status, counts)


# ---------------------------------------------------------------------------
# Chain step
# ---------------------------------------------------------------------------
def _num(value, default):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if np.isfinite(v) else default


def resolve_tool(prm: dict) -> Tuple[Tuple[float, float, float], float, bool, bool]:
    """``(r50 (deep, medium, shallow), p, generic, setting_invalid)`` from the zone settings."""
    tool = prm.get("inv_tool")
    preset = GENERIC_TOOLS.get(tool) or GENERIC_TOOLS["generic_induction"]
    base = (preset["deep"], preset["medium"], preset["shallow"])
    r50 = prm.get("inv_r50")
    invalid = False
    vals = base
    if isinstance(r50, dict):
        got = tuple(_num(r50.get(k), np.nan) for k in ("deep", "medium", "shallow"))
        if all(np.isfinite(g) and g > 0 for g in got):
            vals = got
        else:
            invalid = True
    elif r50 is not None:
        invalid = True
    p = _num(prm.get("inv_p"), preset["p"])
    if p <= 0:
        p, invalid = preset["p"], True
    generic = tool in GENERIC_TOOLS and vals == base and p == preset["p"]
    return vals, p, generic, invalid


def step_invasion(rt: np.ndarray, ctx: ChainContext, prm: dict) -> StepResult:
    n = len(rt)
    r50, p, generic, bad_setting = resolve_tool(prm)
    rmf = prm.get("rmf")
    rmf_val = None if rmf is None else _num(rmf, None)
    rmf_t = None
    extra_counts = {}
    if rmf_val is None:
        extra_counts["rmf_missing"] = 1
    else:
        t_fm = ctx.derived.get("T_FM_F") if ctx.derived else None
        if t_fm is None:
            extra_counts["no_temperature"] = n
        else:
            rmf_t = rmf_at_temperature(rmf_val, _num(prm.get("rmf_temp"), 75.0),
                                       np.asarray(t_fm, dtype=float))
    di_min = _num(prm.get("inv_di_min"), 8.0)
    di_max = _num(prm.get("inv_di_max"), 120.0)
    res = fit_invasion(
        rt, ctx.rm, ctx.rs, ctx.rxo, r50=r50, p=p,
        rxo_mode=prm.get("inv_rxo_mode") or "fixed",
        di_min=di_min, di_max=di_max,
        min_contrast=_num(prm.get("inv_min_contrast"), 1.15),
        max_rms=_num(prm.get("inv_max_rms"), 0.15),
        rmf_t=rmf_t)
    out = np.where(res.valid, res.rt, np.nan)
    counts = dict(res.counts)
    counts.update(extra_counts)
    counts["generic"] = int(generic)
    counts["setting_invalid"] = int(bad_setting)
    return StepResult(out, res.valid, counts,
                      {"RXO_INV": res.rxo, "DI_INV": res.di}, REFS)


STEP = StepSpec(
    name="invasion",
    order=CHAIN_ORDER.index("invasion"),
    column="RT_INV",
    fn=step_invasion,
    label="Radial invasion",
    description="MODELLED INVASION-CORRECTED RT (STEP PROFILE)",
    refs=REFS,
    params=("inv_tool", "inv_r50", "inv_p", "inv_rxo_mode", "inv_di_min", "inv_di_max",
            "inv_min_contrast", "inv_max_rms", "rmf", "rmf_temp"),
    varied=(),
    extra_columns=("RXO_INV", "DI_INV"),
    kind="radial",
)


def register_step() -> None:
    """Register the step unless it is already registered."""
    if STEP.name not in chain.STEPS:
        chain.register(STEP)
    register_derive()


# ---------------------------------------------------------------------------
# Issues from the step counts
# ---------------------------------------------------------------------------
def invasion_count_issues(records: List[dict]) -> List[tuple]:
    """Issue tuples ``(code, text, zone, severity_or_None)`` for the ``invasion`` records of a chain run."""
    out: List[tuple] = []
    vertical_zones = {
        rec.get("zone") for rec in records
        if rec.get("step") in chain.STEPS and chain.STEPS[rec["step"]].kind == "vertical"}
    for rec in records:
        if rec.get("step") != "invasion":
            continue
        if rec.get("zone") in vertical_zones:
            zone = rec.get("zone")
            where = "the unzoned interval" if zone is None else f"zone {zone}"
            out.append(("LRLC_INV_DECON_MISMATCH",
                        f"Invasion correction in {where} follows a vertical-resolution step that changes only "
                        "the deep curve; the medium and shallow curves are used as measured, so the "
                        "three curves have different vertical resolution.", zone, None))
        c = rec.get("counts") or {}
        zone = rec.get("zone")
        where = "the unzoned interval" if zone is None else f"zone {zone}"
        valid = int(rec.get("n_valid", 0)) + int(rec.get("n_invalid", 0))
        if c.get("curves_missing"):
            out.append(("LRLC_INV_CURVES_MISSING",
                        f"The invasion correction needs the medium and shallow resistivity curves, or one of "
                        f"them with a micro-resistivity curve; they are not mapped for {where}, so the step "
                        "was skipped there.", zone, None))
            continue
        if c.get("generic"):
            out.append(("LRLC_INV_TOOL_GENERIC",
                        f"Invasion correction in {where} uses a generic tool preset; confirm the radial "
                        "diameters against the chart book of the tool that was run.", zone, None))
        if c.get("nonunique"):
            share = c["nonunique"] / valid if valid else 0.0
            out.append(("LRLC_INV_NONUNIQUE",
                        f"Invasion correction: {c['nonunique']} sample(s) in {where} have curves too close "
                        "together to separate Rt from Rxo; the input Rt is kept.",
                        zone, "warning" if share > 0.25 else "info"))
        if c.get("di_upper"):
            out.append(("LRLC_INV_DI_BOUND",
                        f"Invasion correction: {c['di_upper']} sample(s) in {where} reached the upper "
                        "invasion diameter bound and give no Rt.", zone, "warning"))
        if c.get("di_lower"):
            out.append(("LRLC_INV_DI_BOUND",
                        f"Invasion correction: {c['di_lower']} sample(s) in {where} reached the lower "
                        "invasion diameter bound.", zone, "info"))
        if c.get("poor_fit"):
            out.append(("LRLC_INV_POOR_FIT",
                        f"Invasion correction: {c['poor_fit']} sample(s) in {where} fit the curves poorly "
                        "and give no Rt.", zone, None))
        if c.get("failed"):
            out.append(("LRLC_INV_FAIL",
                        f"Invasion correction: the fit did not converge for {c['failed']} sample(s) in "
                        f"{where}; they give no Rt.", zone, None))
        if c.get("rxo_below_rmf"):
            out.append(("LRLC_INV_RXO_BELOW_RMF",
                        f"Invasion correction: Rxo is below the mud-filtrate resistivity at formation "
                        f"temperature for {c['rxo_below_rmf']} sample(s) in {where}.", zone, None))
        if c.get("rmf_missing"):
            out.append(("LRLC_INV_RMF_MISSING",
                        f"No mud-filtrate resistivity is set for {where}; Rxo has no lower bound.", zone, None))
    return out


# ---------------------------------------------------------------------------
# Formation temperature (well-scope derive read by the step as ``ctx.derived["T_FM_F"]``)
# ---------------------------------------------------------------------------
# Defaults of the temperature setup (surface temperature degF, gradient degF/100 ft, datum ft).
_TEMP_SETUP_DEFAULTS = (80.0, 1.5, 0.0)


def temperature_needed(lrlc, zone_keys) -> bool:
    """True when some zone present runs the ``invasion`` step with a mud-filtrate resistivity set."""
    if not lrlc or "resolved" not in lrlc:
        return False
    for zone in chain._unique_keys(zone_keys):
        prm = chain._resolved(lrlc, zone)
        specs, _ = chain.resolve_steps(prm.get("rt_steps", []))
        if any(sp.name == "invasion" for sp in specs) and prm.get("rmf") is not None:
            return True
    return False


def temperature_setup_is_default(params) -> bool:
    """True when surface temperature, gradient and datum are all still at their defaults (or absent)."""
    params = params or {}
    for key, default in zip(("surface_temp", "temp_gradient", "temp_datum_depth"), _TEMP_SETUP_DEFAULTS):
        val = params.get(key)
        if val is None:
            continue
        try:
            if abs(float(val) - default) > 1e-9:
                return False
        except (TypeError, ValueError):
            return False
    return True


def derive_formation_temperature(*, tvd, params, zone_keys, lrlc, issues=None) -> Dict[str, np.ndarray]:
    """``{"T_FM_F": degF per sample}`` from the TVD of each sample and the temperature settings.

    ``tvd`` is the true vertical depth (ft) per sample, ``params`` the flat parameters (``surface_temp``,
    ``temp_gradient``, ``temp_datum_depth``). The array is produced only when a zone runs ``invasion``
    with ``rmf`` set (otherwise ``{}``); it does not depend on the Arps or Juhasz options. When the
    temperature settings are all still defaults an ``LRLC_INV_TEMP_DEFAULT`` tuple is appended to
    ``issues`` (if given).
    """
    if not temperature_needed(lrlc, zone_keys):
        return {}
    from modules.param_scopes import formation_temperature
    params = params or {}
    surface = float(params.get("surface_temp") if params.get("surface_temp") is not None
                    else _TEMP_SETUP_DEFAULTS[0])
    gradient = float(params.get("temp_gradient") if params.get("temp_gradient") is not None
                     else _TEMP_SETUP_DEFAULTS[1])
    datum = float(params.get("temp_datum_depth") or 0.0)
    temp = np.asarray(formation_temperature(np.asarray(tvd, dtype=float), surface, gradient, datum),
                      dtype=float)
    if issues is not None and temperature_setup_is_default(params):
        finite = temp[np.isfinite(temp)]
        span = f" ({finite.min():.0f} to {finite.max():.0f} degF)" if finite.size else ""
        issues.append(("LRLC_INV_TEMP_DEFAULT",
                       "The mud-filtrate bound of the invasion correction uses the default formation "
                       f"temperature settings (surface 80 degF, gradient 1.5 degF/100 ft){span}; enter "
                       "the temperature settings of the well to refine it.", None, None))
    return {"T_FM_F": temp}


DERIVE = chain.DeriveSpec(
    name="formation_temperature", scope="well", fn=derive_formation_temperature, outputs=("T_FM_F",))


def register_derive() -> None:
    """Register the formation-temperature derive unless it is already registered."""
    if DERIVE.name not in chain.DERIVES:
        chain.register_derive(DERIVE)
