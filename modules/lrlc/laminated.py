"""Laminated-sand Rt (Hagiwara parallel conductance), chain step ``laminated`` (pure: numpy/pandas only, no Qt, no pipeline import).

    1/Rt = (1 - Vlam) / Rsand + Vlam / Rsh_eff
    RT_SAND = (1 - Vlam) * Rt / (1 - s),      s = Vlam * Rt / Rsh_eff

``s`` is the share of the measured conductance carried by the shale laminae; the relative
error of Rt is amplified by ``1 / (1 - s)``.
"""

from typing import Dict, Tuple

import numpy as np

from modules.lrlc import chain
from modules.lrlc.chain import CHAIN_ORDER, ChainContext, StepResult, StepSpec

_DEFAULT_HAG_VSH_MAX = 0.80
_DEFAULT_S_WARN = 0.80
_DEFAULT_S_INVALID = 0.95

COUNT_KEYS = ("not_applicable", "no_input", "identity", "invalid", "sensitive", "below_rsh")


def hagiwara_rt(rt_in, vlam, rsh_eff, vsh, hag_vsh_max, s_warn, s_invalid
                ) -> Tuple[np.ndarray, np.ndarray, Dict[str, int]]:
    """``(rt_sand, valid_mask, counts)``; all inputs scalar or per-sample arrays."""
    rt_in = np.atleast_1d(np.asarray(rt_in, dtype=float))
    n = len(rt_in)

    def arr(v):
        return np.broadcast_to(np.asarray(v, dtype=float), (n,))

    vlam, rsh, vsh = arr(vlam), arr(rsh_eff), arr(vsh)
    counts = {k: 0 for k in COUNT_KEYS}
    out = rt_in.copy()
    valid = np.ones(n, dtype=bool)

    with np.errstate(invalid="ignore", divide="ignore"):
        not_app = np.isfinite(vsh) & (vsh >= hag_vsh_max)
        no_input = ~not_app & (~np.isfinite(rt_in) | (rt_in <= 0) | ~np.isfinite(rsh)
                               | (rsh <= 0) | ~np.isfinite(vlam) | ~np.isfinite(vsh)
                               | (vlam < 0))
        todo = ~not_app & ~no_input
        identity = todo & (vlam == 0)
        calc = todo & ~identity
        s = np.where(calc, vlam * rt_in / np.where(rsh > 0, rsh, 1.0), 0.0)
        invalid = calc & ((s >= s_invalid) | (vlam >= 1.0))
        keep = calc & ~invalid
        val = (1.0 - vlam) * rt_in / (1.0 - s)

    out[no_input] = np.nan
    valid[no_input] = False
    out[invalid] = np.nan
    valid[invalid] = False
    out[keep] = val[keep]
    counts["not_applicable"] = int(not_app.sum())
    counts["no_input"] = int(no_input.sum())
    counts["identity"] = int(identity.sum())
    counts["invalid"] = int(invalid.sum())
    counts["sensitive"] = int((keep & (s >= s_warn)).sum())
    counts["below_rsh"] = int((keep & (rt_in < rsh)).sum())
    return out, valid, counts


def _num(value, default):
    return default if value is None else float(value)


def laminated_step(rt: np.ndarray, ctx: ChainContext, prm: dict) -> StepResult:
    n = len(rt)
    extra: Dict[str, int] = {}
    if prm.get("vlam_source") == "constant":
        vlam = np.full(n, _num(prm.get("vlam_const"), 0.0))
    else:
        derived = ctx.derived.get("VLAM") if ctx.derived else None
        if derived is None:
            vlam = np.full(n, np.nan)
            extra["no_vlam"] = n
        else:
            vlam = np.asarray(derived, dtype=float)
    out, valid, counts = hagiwara_rt(
        rt, vlam, ctx.rsh, ctx.vsh,
        _num(prm.get("hag_vsh_max"), _DEFAULT_HAG_VSH_MAX),
        _num(prm.get("s_warn"), _DEFAULT_S_WARN),
        _num(prm.get("s_invalid"), _DEFAULT_S_INVALID))
    counts.update(extra)
    return StepResult(out, valid, counts, {}, ("poupon1954", "hagiwara_us4739255", "hagiwara1995", "hagiwara1997"))


STEP = StepSpec(
    name="laminated",
    order=CHAIN_ORDER.index("laminated"),
    column="RT_SAND",
    fn=laminated_step,
    label="Laminated sand (Hagiwara)",
    description="Removes the conductance of the shale laminae from the measured Rt "
                "(parallel conductance) to give the resistivity of the sand laminae.",
    refs=("poupon1954", "hagiwara_us4739255", "hagiwara1995", "hagiwara1997"),
    params=("vlam_source", "vlam_const", "hag_vsh_max", "s_warn", "s_invalid"),
    varied=("rsh",),
    kind="lamination",
)


def register_step() -> None:
    """Register the step unless it is already registered."""
    if STEP.name not in chain.STEPS:
        chain.register(STEP)
