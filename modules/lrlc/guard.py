"""Shoulder-bed guard: laminated-zone classification and the chain guard rules (pure: numpy/pandas only, no Qt, no pipeline import).

Bind the settings with ``functools.partial(evaluate_guard, zone_states=..., guard_settings=...,
rt_sbc_marked=...)`` and hand the result to ``apply_rt_chain(..., guard=...)``.

Rules:
  G1  a step of kind "vertical" in a laminated zone is dropped (guard on) or only warned about
      (guard off).
  G2  the mapped RT is marked shoulder-bed corrected, the zone is laminated and the laminated
      step is active: keep everything, warn; never invalidates a sample.
  G3  vertical and laminated steps selected together in a zone that is not laminated: both run,
      info note (double correction).
  G4  a step of kind "vertical" and the mapped RT marked shoulder-bed corrected (any zone,
      classified or not): dropped (guard on) or only warned about (guard off). When G1 applies
      too, only G1 is reported (one message per zone and step).

The texts name a step by its label (``StepSpec.label``), not by its internal name.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from modules.lrlc.chain import ChainContext, GuardDecision, StepSpec, _zone_label

RESERVED_RULES = ()


@dataclass
class GuardResult(GuardDecision):
    """A ``GuardDecision`` that also remembers what the guard did (for the summary)."""
    blocked_steps: List[str] = field(default_factory=list)
    sbc_rt: bool = False
    # step name -> "laminated" (G1) or "shoulder" (G4), for dropped and (guard off) warned steps
    reasons: Dict[str, str] = field(default_factory=dict)
    warned_steps: List[str] = field(default_factory=list)


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
    state["excluded_ft"] = float(stats.get("excluded_ft", 0.0) or 0.0)

    def laminated_by(share, mean):
        return bool(np.isfinite(share) and np.isfinite(mean)
                    and share >= float(guard_settings.get("vlam_share", 0.50))
                    and mean >= float(guard_settings.get("min_vlam", 0.05)))

    if state["excluded_ft"] > 0 or stats.get("emptied"):
        # what the zone would have been without the resolved-bed rule (for the guard line)
        state["laminated_all"] = laminated_by(float(stats.get("lam_share_all", float("nan"))),
                                              float(stats.get("mean_vlam_all", float("nan"))))
    if stats.get("emptied"):
        # Thomas-Stieber classified the zone; only resolved beds (or too little thickness
        # to call laminated) remain, so it is classified and not laminated.
        state["classified"] = True
        return state
    if n <= 0 or not np.isfinite(lam_share) or not np.isfinite(mean_vlam):
        return state
    state["classified"] = True
    state["laminated"] = laminated_by(lam_share, mean_vlam)
    return state


def resolved_note(row: dict) -> str:
    """Plain words for a guard-summary row when resolved shale beds were left out of the
    laminated check ("" when the rule did nothing in the zone)."""
    ft = float(row.get("resolved_ft") or 0.0)
    if ft > 0:
        shown = f"{ft:.1f}".rstrip("0").rstrip(".")
        return f"{shown} ft of resolved shale beds left out of the laminated check"
    if row.get("class_changed"):
        return "too little of the zone is left after the resolved shale beds for a laminated check"
    return ""


def _why(reason):
    """``(why, tail)`` of a guard sentence for a reason: ``"laminated"`` or ``"shoulder"``."""
    if reason == "laminated":
        return "laminated", "; use the laminated-sand correction."
    return "RT is marked shoulder-bed corrected", "."


def blocked_text(name, shown, reason):
    """The guard-on sentence for a dropped step (shared by the issue and the Workbench)."""
    why, tail = _why(reason)
    return f"{name} not applied in {shown}: {why} (guard){tail}"


def _vertical_rule(spec, enabled, shown, label, reason, kept, blocked, warned, reasons, issues):
    """Drop (guard on) or warn about (guard off) one vertical step; reason is laminated or shoulder."""
    name = spec.label or spec.name
    reasons[spec.name] = reason
    why, tail = _why(reason)
    if enabled:
        kept.remove(spec)
        blocked.append(spec.name)
        issues.append(("LRLC_GUARD_BLOCKED", blocked_text(name, shown, reason), label, None))
    else:
        warned.append(spec.name)
        issues.append(("LRLC_GUARD_WARNED", f"{name} applied in {shown}: {why} (guard off){tail}",
                       label, None))


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
    warned: List[str] = []
    reasons: Dict[str, str] = {}
    off = "" if enabled else " (guard off)"
    vertical = [s for s in kept if s.kind == "vertical"]

    # G1 (laminated zone) and G4 (RT marked shoulder-bed corrected) act on the vertical steps;
    # G4 is evaluated before the unclassified return, so it works without Thomas-Stieber.
    for spec in vertical:
        if laminated:
            _vertical_rule(spec, enabled, shown, label, "laminated", kept, blocked, warned,
                           reasons, issues)
        elif rt_sbc_marked:
            _vertical_rule(spec, enabled, shown, label, "shoulder", kept, blocked, warned,
                           reasons, issues)

    has_lam = any(s.name == "laminated" for s in kept)
    # G3: vertical and laminated steps together in a zone that is not laminated.
    if not laminated:
        for spec in [s for s in kept if s.kind == "vertical"]:
            if has_lam:
                issues.append(("LRLC_GUARD_COMBINED",
                               f"{spec.label or spec.name} and the laminated-sand correction are both "
                               f"selected in {shown}; both act on thin beds, check for double "
                               "correction.", label, None))

    if not classified:
        if enabled and (zone_states or vertical):
            tail = ("cannot classify it and blocks nothing." if not blocked
                    else "cannot classify it for the laminated check.")
            issues.append(("LRLC_GUARD_NO_TS",
                           f"{shown} has no Thomas-Stieber result, so the shoulder-bed guard "
                           + tail, label, None))
        return GuardResult(kept, None, issues, blocked, False, reasons, warned)

    if laminated:
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
        return GuardResult(kept, None, issues, blocked, sbc, reasons, warned)

    return GuardResult(kept, None, issues, blocked, False, reasons, warned)


def guard_summary(zone_states: Dict[str, dict], decisions: Dict[str, GuardDecision],
                  enabled: bool = True) -> dict:
    """The ``summary["lrlc"]["guard"]`` block."""
    keys = list(dict.fromkeys(list((zone_states or {}).keys()) + list((decisions or {}).keys())))
    zones = []
    for key in keys:
        st = (zone_states or {}).get(key) or {}
        dec = (decisions or {}).get(key)
        row = {
            "zone": _zone_label(key),
            "laminated": bool(st.get("laminated", False)),
            "lam_share": st.get("lam_share", float("nan")),
            "blocked_steps": list(getattr(dec, "blocked_steps", []) or []),
            "sbc_rt": bool(getattr(dec, "sbc_rt", False)),
        }
        reasons = dict(getattr(dec, "reasons", {}) or {})
        if reasons:             # only when a guard rule acted: the block of every other case is unchanged
            row["reasons"] = reasons
        if st.get("excluded_ft", 0.0) > 0:      # only when the resolved-bed rule left beds out
            row["resolved_ft"] = round(float(st["excluded_ft"]), 3)
        if st.get("laminated_all") and not st.get("laminated"):
            row["class_changed"] = True
        zones.append(row)
    out = {"enabled": bool(enabled), "zones": zones}
    if any("resolved_ft" in z or "class_changed" in z for z in zones):
        out["resolved_beds_left_out"] = True
    return out
