"""Shoulder-bed guard: laminated-zone classification and the chain guard rules (pure: numpy/pandas only, no Qt, no pipeline import).

Bind the settings with ``functools.partial(evaluate_guard, zone_states=..., guard_settings=...,
rt_sbc_marked=...)`` and hand the result to ``apply_rt_chain(..., guard=...)``.

Rules (in order, per laminated zone):
  G1  a step of kind "vertical" is dropped (guard on) or only warned about (guard off).
  G2  the mapped RT is marked shoulder-bed corrected and the laminated step is active:
      keep everything, warn; never invalidates a sample.
  G3  vertical and laminated steps selected together: reserved, no behaviour yet.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from modules.lrlc.chain import ChainContext, GuardDecision, StepSpec, _zone_label

RESERVED_RULES = ("G3",)


@dataclass
class GuardResult(GuardDecision):
    """A ``GuardDecision`` that also remembers what the guard did (for the summary)."""
    blocked_steps: List[str] = field(default_factory=list)
    sbc_rt: bool = False


def zone_state(stats: Optional[dict], guard_settings: dict) -> dict:
    """Laminated classification of one zone from ``thomas_stieber.zone_stats`` output."""
    state = {"laminated": False, "lam_share": float("nan"), "mean_vlam": float("nan"),
             "n": 0, "classified": False}
    if not stats:
        return state
    lam_share = float(stats.get("lam_share", float("nan")))
    mean_vlam = float(stats.get("mean_vlam", float("nan")))
    n = int(stats.get("n", 0))
    state.update(lam_share=lam_share, mean_vlam=mean_vlam, n=n)
    if n <= 0 or not np.isfinite(lam_share) or not np.isfinite(mean_vlam):
        return state
    state["classified"] = True
    state["laminated"] = bool(
        lam_share >= float(guard_settings.get("vlam_share", 0.50))
        and mean_vlam >= float(guard_settings.get("min_vlam", 0.05)))
    return state


def evaluate_guard(zone_key, specs, ctx: ChainContext, *, zone_states: Dict[str, dict],
                   guard_settings: dict, rt_sbc_marked: bool = False) -> GuardResult:
    state = (zone_states or {}).get(zone_key) or {}
    enabled = bool(guard_settings.get("enabled", True))
    label = _zone_label(zone_key)
    shown = f"Zone {label}" if label else "the unzoned interval"
    laminated = bool(state.get("laminated")) and bool(state.get("classified", True))
    classified = bool(state.get("classified"))
    issues: List[tuple] = []
    kept = list(specs)
    blocked: List[str] = []
    off = "" if enabled else " (guard off)"

    if not classified:
        if enabled:
            issues.append(("LRLC_GUARD_NO_TS",
                           f"{shown} has no Thomas-Stieber result, so the shoulder-bed guard "
                           f"cannot classify it and blocks nothing.", label, None))
        return GuardResult(kept, None, issues, [], False)

    if laminated:
        # G1: vertical steps (deconvolution) do not belong in laminated zones.
        for spec in list(kept):
            if spec.kind != "vertical":
                continue
            if enabled:
                kept.remove(spec)
                blocked.append(spec.name)
                issues.append(("LRLC_GUARD_BLOCKED",
                               f"{spec.name} not applied in {shown}: laminated (guard); "
                               f"use the laminated-sand correction.", label, None))
            else:
                issues.append(("LRLC_GUARD_WARNED",
                               f"{spec.name} applied in {shown}: laminated (guard off); "
                               f"use the laminated-sand correction.", label, None))
        # G3 (reserved): vertical + laminated together. No behaviour yet.

        has_lam = any(s.name == "laminated" for s in kept)
        # G2: marked curve plus the laminated step. Compute, warn, mark; never invalidate.
        sbc = bool(rt_sbc_marked) and has_lam
        if sbc:
            issues.append(("LRLC_GUARD_SBC_RT",
                           f"RT is marked shoulder-bed corrected in {shown}, which is laminated"
                           f"{off}: map the raw deep RT and use the laminated-sand correction.",
                           label, None))
        if not has_lam and enabled:
            issues.append(("LRLC_GUARD_HINT",
                           f"{shown} is laminated by Thomas-Stieber; consider the "
                           f"laminated-sand Rt (Hagiwara).", label, None))
        return GuardResult(kept, None, issues, blocked, sbc)

    return GuardResult(kept, None, issues, blocked, False)


def guard_summary(zone_states: Dict[str, dict], decisions: Dict[str, GuardDecision],
                  enabled: bool = True) -> dict:
    """The ``summary["lrlc"]["guard"]`` block."""
    keys = list(dict.fromkeys(list((zone_states or {}).keys()) + list((decisions or {}).keys())))
    zones = []
    for key in keys:
        st = (zone_states or {}).get(key) or {}
        dec = (decisions or {}).get(key)
        zones.append({
            "zone": _zone_label(key),
            "laminated": bool(st.get("laminated", False)),
            "lam_share": st.get("lam_share", float("nan")),
            "blocked_steps": list(getattr(dec, "blocked_steps", []) or []),
            "sbc_rt": bool(getattr(dec, "sbc_rt", False)),
        })
    return {"enabled": bool(enabled), "zones": zones}
