"""Rt cutoff ``RT_CUT``: the Rt at which the primary Sw model returns a target Sw.

Pure numerical code. The Sw is evaluated with the app's own ``calculate_sw_*`` through
their Rt array path, on a SCRATCH calculator (the production functions overwrite
``results``, ``sw_flags`` and ``solver_diagnostics`` of whatever calculator they run on,
so a live calculator is never used here).
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from modules.lrlc import SHIPPED_METHODS
from modules.petrophysics import SW_MIN_POROSITY, PetrophysicsCalculator

BRACKET = (-2.0, 5.0)  # log10 Rt, 0.01 to 100000 ohm.m
N_ITER = 30

MODELS = ("Archie", "Indonesian", "Simandoux", "Waxman-Smits", "Dual-Water")


def _refs(method):
    def deco(fn):
        fn.refs = tuple(SHIPPED_METHODS[method])
        return fn
    return deco


@dataclass
class SwInputs:
    """The one set of Sw inputs of a segment (everything but Rt).

    Mirrors the arguments ``modules.pipeline._primary_sw`` hands to the five models:
    ``rw_eff``, ``rsh_eff``, ``rwb_eff`` and ``ws_b`` are the effective values of
    ``_sw_effective_inputs`` (scalar or one value per sample); ``phie``, ``phit``, ``vsh``
    are per-sample arrays; ``a`` and ``dw_swb`` are scalars. ``m``, ``n`` and ``ws_qv`` are scalars
    or, where a zone uses variable exponents or an estimated Qv, one value per sample (the same
    arrays the primary Sw model read), so the cutoff is computed with exactly the inputs of ``SW``.
    """

    phie: Any
    phit: Any
    vsh: Any
    rw_eff: Any
    rsh_eff: Any
    rwb_eff: Any
    ws_b: Any
    a: float
    m: Any
    n: Any
    ws_qv: Any
    dw_swb: float


_PER_SAMPLE = ("phie", "phit", "vsh", "rw_eff", "rsh_eff", "rwb_eff", "ws_b")
# Inputs that are a scalar or one value per sample, with the neutral value that stands in for an
# ineligible sample.
_OPTIONAL_ARRAYS = (("m", 2.0), ("n", 2.0), ("ws_qv", 0.0))


def _broadcast(value, size):
    arr = np.asarray(value, dtype=float)
    if arr.ndim == 0:
        return np.full(size, float(arr))
    arr = arr.reshape(-1)
    if arr.shape != (size,):
        raise ValueError("Sw input must be a scalar or have one value per sample")
    return arr


def _model_fields(model):
    """``(porosity field, other per-sample fields that must be finite)`` of a model."""
    if model == "Archie":
        return "phie", ("rw_eff",)
    if model in ("Indonesian", "Simandoux"):
        return "phie", ("vsh", "rw_eff", "rsh_eff")
    if model == "Waxman-Smits":
        return "phit", ("phie", "rw_eff", "ws_b")
    if model == "Dual-Water":
        return "phit", ("phie", "rw_eff", "rwb_eff")
    raise ValueError(f"unknown Sw model {model!r}")


def _sw_function(model, inputs, index):
    """``(sw_at(log_rt), eligible)`` for ``inputs`` on ``index``."""
    size = len(index)
    arr = {k: _broadcast(getattr(inputs, k), size) for k in _PER_SAMPLE}
    por_field, others = _model_fields(model)
    por = arr[por_field]
    eligible = np.isfinite(por) & (por > SW_MIN_POROSITY)
    for key in others:
        eligible &= np.isfinite(arr[key])
    # The production validators reject non-finite / non-positive parameters, so neutral
    # values stand in for the ineligible samples (their result is discarded).
    optional = {}
    for key, fill in _OPTIONAL_ARRAYS:
        value = getattr(inputs, key)
        if np.ndim(value) == 0:
            optional[key] = value
            continue
        values = _broadcast(value, size)
        if key == "ws_qv":
            if model == "Waxman-Smits":
                eligible &= np.isfinite(values)
        else:
            eligible &= np.isfinite(values) & (values > 0)
        optional[key] = np.where(np.isfinite(values), values, fill)
    # The ineligible rows of the safe arrays carry the neutral value.
    for key, fill in _OPTIONAL_ARRAYS:
        if np.ndim(optional[key]) != 0:
            optional[key] = np.where(eligible, optional[key], fill)
    safe = {}
    for key in _PER_SAMPLE:
        fill = 0.2 if key in ("phie", "phit", "vsh") else 1.0
        safe[key] = pd.Series(np.where(eligible & np.isfinite(arr[key]), arr[key], fill),
                              index=index)
    scratch = PetrophysicsCalculator(pd.DataFrame({"RT_TRIAL": np.ones(size)}, index=index))
    a, m, n, ws_qv = inputs.a, optional["m"], optional["n"], optional["ws_qv"]

    def sw_at(log_rt):
        rt = np.power(10.0, np.asarray(log_rt, dtype=float))
        if model == "Archie":
            sw = scratch.calculate_sw_archie("RT_TRIAL", safe["phie"], safe["rw_eff"].values,
                                             a, m, n, rt=rt)
        elif model == "Indonesian":
            sw = scratch.calculate_sw_indonesian(
                "RT_TRIAL", safe["phie"], safe["vsh"], safe["rw_eff"].values,
                safe["rsh_eff"].values, a, m, n, rt=rt)
        elif model == "Simandoux":
            sw = scratch.calculate_sw_simandoux(
                "RT_TRIAL", safe["phie"], safe["vsh"], safe["rw_eff"].values,
                safe["rsh_eff"].values, a, m, n, rt=rt)
        elif model == "Waxman-Smits":
            sw = scratch.calculate_sw_waxman_smits(
                "RT_TRIAL", safe["phit"], safe["rw_eff"].values, a, m, n, ws_qv,
                safe["ws_b"].values, phie=safe["phie"], rt=rt)
        else:
            sw = scratch.calculate_sw_dual_water(
                "RT_TRIAL", safe["phit"], safe["rw_eff"].values, a, m, n, inputs.dw_swb,
                safe["rwb_eff"].values, phie=safe["phie"], rt=rt)
        return np.asarray(sw, dtype=float)

    return sw_at, eligible


@_refs("rt_cutoff")
def rt_cutoff(model: str, inputs: SwInputs, target: float, index):
    """``(rt_cut, n_eligible, n_no_root)`` for ``model`` at Sw = ``target``.

    ``rt_cut`` is an ndarray (ohm.m) with NaN where the sample is ineligible (porosity NaN
    or <= ``SW_MIN_POROSITY``, or a non-finite input) or no root lies in ``BRACKET``.
    Ineligible samples are not counted as failures.
    """
    index = pd.Index(index)
    size = len(index)
    if size == 0:
        return np.zeros(0), 0, 0
    sw_at, eligible = _sw_function(model, inputs, index)
    lo = np.full(size, BRACKET[0])
    hi = np.full(size, BRACKET[1])
    with np.errstate(invalid="ignore"):
        root_ok = eligible & (sw_at(hi) <= target) & (sw_at(lo) >= target)
        for _ in range(N_ITER):
            mid = 0.5 * (lo + hi)
            gt = sw_at(mid) > target
            lo = np.where(gt, mid, lo)
            hi = np.where(gt, hi, mid)
    cut = np.where(root_ok, np.power(10.0, 0.5 * (lo + hi)), np.nan)
    n_eligible = int(eligible.sum())
    n_no_root = int((eligible & ~root_ok).sum())
    return cut, n_eligible, n_no_root


def _weighted_mean(values, weights):
    values = np.asarray(values, dtype=float)
    ok = np.isfinite(values)
    if not ok.any():
        return float("nan")
    w = np.where(np.isfinite(weights), weights, 0.0)[ok]
    if w.sum() <= 0:
        return float(values[ok].mean())
    return float((values[ok] * w).sum() / w.sum())


@_refs("rt_cutoff")
def zone_scalar(model: str, inputs: SwInputs, target: float, *, zone_mask, dz,
                net_pay_flag, net_res_flag, gross_sand_flag, zone: str = "WELL"
                ) -> Optional[Dict[str, Any]]:
    """The per-zone Rt cutoff row, or None when the zone has no basis sample.

    Basis samples (inside ``zone_mask``): ``NET_PAY_FLAG == 1``; else ``NET_RES_FLAG == 1``;
    else ``GROSS_SAND_FLAG == 1``. The dz-weighted means (finite values only) of the
    per-sample inputs form a one-row input record and the same bisection gives the scalar.
    Row: ``zone, sw_target, rt_cut, basis, n, phie, vsh, model`` (``rt_cut`` is NaN when
    the one-row bisection finds no root).
    """
    zone_mask = np.asarray(zone_mask, dtype=bool)
    size = len(zone_mask)
    basis = None
    for label, flag in (("pay", net_pay_flag), ("net reservoir", net_res_flag),
                        ("gross sand", gross_sand_flag)):
        mask = zone_mask & (np.asarray(flag) == 1)
        if mask.any():
            basis = (label, mask)
            break
    if basis is None:
        return None
    label, mask = basis
    weights = _broadcast(dz, size)[mask]
    means = {}
    for key in _PER_SAMPLE:
        value = np.asarray(getattr(inputs, key), dtype=float)
        means[key] = (float(value) if value.ndim == 0
                      else _weighted_mean(value.reshape(-1)[mask], weights))
    scalars = {}
    for key, _ in _OPTIONAL_ARRAYS:
        value = np.asarray(getattr(inputs, key), dtype=float)
        scalars[key] = (getattr(inputs, key) if value.ndim == 0
                        else _weighted_mean(value.reshape(-1)[mask], weights))
    one = SwInputs(a=inputs.a, dw_swb=inputs.dw_swb, **scalars, **means)
    cut, _, _ = rt_cutoff(model, one, target, pd.RangeIndex(1))
    return {
        "zone": zone, "sw_target": float(target), "rt_cut": float(cut[0]), "basis": label,
        "n": int(mask.sum()), "phie": means["phie"], "vsh": means["vsh"], "model": model,
    }
