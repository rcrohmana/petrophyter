"""LRLC pipeline glue for laminated sands, conductive minerals, Qv and diagnosis (no pipeline import).

Everything the pipeline owns is passed in. The segment derives (Thomas-Stieber, pyrite volume,
Qv estimate) are registered in ``chain.DERIVES`` and run by :func:`run_derives` on one saturation
segment before the Rt chain. Issues are tuples ``(code, text, zone_label, severity_or_None)``.

Nothing here runs unless a feature is switched on (:class:`L2Plan`), so a run with LRLC on and
nothing selected is unchanged.
"""

from dataclasses import dataclass, field
from functools import partial
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from modules.lrlc import chain
from modules.lrlc.chain import DeriveSpec, register_derive, resolve_steps
from modules.lrlc.config import (
    DIAGNOSIS_DEFAULTS, GUARD_DEFAULTS, PYRITE_DEFAULTS, QV_DEFAULTS, THOMAS_STIEBER_DEFAULTS)
from modules.lrlc.diagnosis import diagnose_zone, lrlc_note, zone_evidence
from modules.lrlc.guard import evaluate_guard, guard_summary, zone_state
from modules.lrlc.pyrite import solve_volumes
from modules.lrlc.qv import estimate_qv, qv_for_model
from modules.lrlc.thomas_stieber import check_endpoints, decompose, zone_stats
from modules.param_scopes import UNZONED

COUNT_SHARE = 0.20          # info becomes warning above this share of the samples counted
TS_COLUMNS = ("VLAM", "VDISP", "PHI_SAND", "TS_CLASS")
WELL_ZONE = "WELL"
_BLOCK_DEFAULTS = {
    "thomas_stieber": THOMAS_STIEBER_DEFAULTS, "pyrite": PYRITE_DEFAULTS, "qv": QV_DEFAULTS,
    "guard": GUARD_DEFAULTS, "diagnosis": DIAGNOSIS_DEFAULTS,
}
DERIVE_NAMES = ("thomas_stieber", "pyrite_volume", "qv_estimate")


def block(lrlc: dict, name: str) -> dict:
    """One setting block with the defaults filled in (a ``p["lrlc"]`` built by hand may lack it)."""
    return {**_BLOCK_DEFAULTS[name], **((lrlc or {}).get(name) or {})}


def _resolved(lrlc: dict, key) -> dict:
    res = lrlc["resolved"]
    return res.get("zones", {}).get(key, res["default"])


def _label(key) -> Optional[str]:
    return None if key == UNZONED else key


def _where(key) -> str:
    return "the unzoned interval" if key == UNZONED else f"zone {key}"


def _unique(keys) -> List:
    return list(dict.fromkeys(np.asarray(keys, dtype=object).tolist()))


# ---------------------------------------------------------------------------
# Which features are on
# ---------------------------------------------------------------------------
def step_names(prm: dict) -> List[str]:
    return [s.name for s in resolve_steps(prm.get("rt_steps", []))[0]]


def resolve_basis(prm: dict) -> str:
    """``"sand"`` or ``"bulk"`` for one zone (auto: sand where the laminated step is listed)."""
    basis = prm.get("sw_basis", "auto")
    if basis in ("sand", "bulk"):
        return basis
    return "sand" if "laminated" in step_names(prm) else "bulk"


def zone_active(prm: dict) -> bool:
    """A remediation is active in the zone: a chain step, a Qv estimate or the sand basis."""
    return bool(step_names(prm)) or prm.get("qv_source") == "estimate" \
        or resolve_basis(prm) == "sand"


@dataclass
class L2Plan:
    ts_on: bool = False
    vpyr_on: bool = False
    qv_on: bool = False
    any_active: bool = False        # a remediation is active in at least one zone of the well
    rt_sbc: bool = False            # the mapped RT is marked shoulder-bed corrected

    @property
    def l2_on(self) -> bool:
        return self.ts_on or self.vpyr_on or self.qv_on or self.any_active


def make_plan(lrlc: dict, well_keys, rt_curve: str) -> L2Plan:
    keys = _unique(well_keys) or [UNZONED]
    prms = [_resolved(lrlc, k) for k in keys]
    py = block(lrlc, "pyrite")
    marker = (lrlc.get("curves") or {}).get("RT_SBC")
    return L2Plan(
        ts_on=bool(block(lrlc, "thomas_stieber")["enabled"]),
        vpyr_on=bool(py["enabled"]) or any(
            prm.get("pyr_method") == "rhob_pef" and "pyrite" in step_names(prm) for prm in prms),
        qv_on=any(prm.get("qv_source") == "estimate" for prm in prms),
        any_active=any(zone_active(prm) for prm in prms),
        rt_sbc=bool(marker) and marker == rt_curve)


def segment_active(lrlc: dict, keys) -> bool:
    return any(zone_active(_resolved(lrlc, k)) for k in _unique(keys))


# ---------------------------------------------------------------------------
# Segment environment and derives
# ---------------------------------------------------------------------------
@dataclass
class SegEnv:
    lrlc: dict
    keys: np.ndarray                    # per-sample zone key (UNZONED for none)
    p: dict                             # the segment's flat parameters
    vsh: np.ndarray                     # primary VSH (what the Sw models read)
    vsh_ts: np.ndarray                  # VSH used by Thomas-Stieber (settings vsh_column)
    phit: np.ndarray
    phie: np.ndarray
    rt: np.ndarray                      # measured RT
    dz: np.ndarray
    has_gr: bool
    rhob: Optional[np.ndarray]
    pef: Optional[np.ndarray]
    gas: Optional[np.ndarray]
    plan: L2Plan
    issues: List[tuple] = field(default_factory=list)
    notes: Dict[str, Any] = field(default_factory=dict)

    def add(self, code, text, key=UNZONED, severity=None):
        self.issues.append((code, text, _label(key), severity))


def _share_severity(count: int, total: int) -> Optional[str]:
    return "warning" if total > 0 and count / total > COUNT_SHARE else None


def derive_thomas_stieber(env: SegEnv) -> Dict[str, np.ndarray]:
    s = block(env.lrlc, "thomas_stieber")
    if not s["enabled"]:
        return {}
    if not env.has_gr:
        env.add("LRLC_TS_VSH_DEFAULTED",
                "Thomas-Stieber was skipped: the shale volume is the default constant because "
                "no GR curve is available.")
        return {}
    n = len(env.keys)
    out = {"VLAM": np.full(n, np.nan), "VDISP": np.full(n, np.nan),
           "PHI_SAND": np.full(n, np.nan), "TS_CLASS": np.zeros(n, dtype=int)}
    zones: Dict[Any, dict] = {}
    for key in _unique(env.keys):
        mask = env.keys == key
        prm = _resolved(env.lrlc, key)
        pm, ps = prm.get("phi_max"), prm.get("phi_sh")
        info = {"phi_max": pm, "phi_sh": ps, "applied": False,
                "clamped": {"structural": 0, "clay_supported": 0, "below_dispersed": 0}}
        zones[key] = info
        if pm is None or ps is None:
            env.add("LRLC_TS_NO_ENDPOINTS",
                    f"Thomas-Stieber has no applied clean-sand and shale porosity in "
                    f"{_where(key)}; no laminar shale volume there.", key)
            continue
        ok, why = check_endpoints(pm, ps)
        if not ok:
            env.add("LRLC_TS_ENDPOINTS_INVALID",
                    f"Thomas-Stieber end-points in {_where(key)} are not usable: {why}", key)
            continue
        res = decompose(env.vsh_ts[mask], env.phit[mask], float(pm), float(ps), s)
        for name, arr in (("VLAM", res.vlam), ("VDISP", res.vdisp), ("PHI_SAND", res.phi_sand),
                          ("TS_CLASS", res.ts_class)):
            out[name][mask] = arr
        info["applied"] = True
        info["clamped"] = dict(res.counts["clamped"])
        classes = res.counts["classes"]
        classified = sum(classes[c] for c in range(1, 6))
        outside = sum(res.counts["clamped"].values())
        if outside:
            env.add("LRLC_TS_OUTSIDE",
                    f"Thomas-Stieber: {outside} of {classified} classified sample(s) in "
                    f"{_where(key)} lie outside the dispersed-laminar triangle "
                    f"(structural {res.counts['clamped']['structural']}, clay-supported "
                    f"{res.counts['clamped']['clay_supported']}, below the dispersed line "
                    f"{res.counts['clamped']['below_dispersed']}); their laminar volume is clamped.",
                    key, _share_severity(outside, classified))
        if env.gas is not None:
            gas = int(((env.gas[mask] == 1) & (res.ts_class != 0)).sum())
            if gas:
                env.add("LRLC_TS_GAS_BIAS",
                        f"Thomas-Stieber: {gas} gas sample(s) in {_where(key)} are classified; "
                        "gas lowers the density-neutron porosity contrast.", key)
    env.notes["ts"] = zones
    return out


def derive_pyrite_volume(env: SegEnv) -> Dict[str, np.ndarray]:
    if not env.plan.vpyr_on:
        return {}
    py = block(env.lrlc, "pyrite")
    n = len(env.keys)
    vpyr = np.full(n, np.nan)
    caution = False
    for key in _unique(env.keys):
        mask = env.keys == key
        prm = _resolved(env.lrlc, key)
        if prm.get("pyr_method") != "rhob_pef":
            if py["enabled"]:
                v = prm.get("pyr_vpyr")
                vpyr[mask] = np.nan if v is None else float(v)
            continue
        if env.rhob is None or env.pef is None:
            env.add("LRLC_PYR_NO_INPUT",
                    f"Pyrite volume in {_where(key)} needs the density and the photoelectric "
                    "curves (map PEF as an auxiliary curve); VPYR is empty there.", key)
            continue
        caution = True
        vol = solve_volumes(
            env.rhob[mask], env.pef[mask], env.vsh[mask],
            rho_f=float(env.p["rho_fluid"]), u_fluid=float(py["u_fluid"]),
            rho_ma=float(prm["ma_rho"] if prm.get("ma_rho") is not None else env.p["rho_matrix"]),
            pef_ma=float(prm["ma_pef"]), rho_py=float(prm["pyr_rho"]), pef_py=float(prm["pyr_pef"]),
            rho_sh=float(prm["sh_rho"] if prm.get("sh_rho") is not None else env.p["rho_shale"]),
            pef_sh=float(prm["sh_pef"]), pef_max=float(py["pef_max"]),
            neg_tol=float(py["neg_tol"]), vpyr_max=float(py["vpyr_max"]))
        if vol.ill_conditioned:
            env.add("LRLC_PYR_ILL_CONDITIONED",
                    f"The pyrite end-point matrix in {_where(key)} is close to singular "
                    "(check the matrix, pyrite and fluid values); VPYR is empty there.", key)
            continue
        vpyr[mask] = vol.vpyr
        usable = int(mask.sum()) - vol.counts["no_input"]
        neg = vol.counts["negative"] + vol.counts["rounded_zero"]
        if neg:
            env.add("LRLC_PYR_NEGATIVE",
                    f"Pyrite volume: {vol.counts['negative']} sample(s) in {_where(key)} came out "
                    f"below zero (left empty), {vol.counts['rounded_zero']} within the tolerance "
                    "set to zero.", key, _share_severity(neg, usable))
        if vol.counts["implausible"]:
            env.add("LRLC_PYR_IMPLAUSIBLE",
                    f"Pyrite volume: {vol.counts['implausible']} sample(s) in {_where(key)} "
                    f"exceed {py['vpyr_max']:g} (left empty).", key)
    if caution:
        env.add("LRLC_PYR_PEF_CAUTION",
                "Pyrite from RHOB and PEF: barite mud, siderite and heavy minerals raise PEF, "
                "and a padded PEF is a pad-contact measurement.")
    return {"VPYR": vpyr}


def derive_qv_estimate(env: SegEnv) -> Dict[str, np.ndarray]:
    if not env.plan.qv_on:
        return {}
    qs = block(env.lrlc, "qv")
    qv = np.full(len(env.keys), np.nan)
    for key in _unique(env.keys):
        prm = _resolved(env.lrlc, key)
        if prm.get("qv_source") != "estimate":
            continue
        mask = env.keys == key
        rho_g = prm["qv_rho_g"] if prm.get("qv_rho_g") is not None else env.p["rho_matrix"]
        est, counts = estimate_qv(env.vsh[mask], env.phit[mask], float(prm["cec_shale"]),
                                  float(rho_g), float(qs["phi_min"]), float(qs["qv_max"]))
        qv[mask] = est
        if counts["out_of_range"]:
            total = int(np.isfinite(env.vsh[mask] + env.phit[mask]).sum())
            env.add("LRLC_QV_OUT_OF_RANGE",
                    f"Qv estimate: {counts['out_of_range']} sample(s) in {_where(key)} have a "
                    f"porosity below {qs['phi_min']:g} or Qv above {qs['qv_max']:g} meq/mL.",
                    key, _share_severity(counts["out_of_range"], total))
        if "Waxman-Smits" not in (env.p.get("sw_methods") or []):
            env.add("LRLC_QV_NOT_USED",
                    f"Qv is estimated in {_where(key)} but Waxman-Smits is not a selected Sw "
                    "method, so the estimate is not used.", key)
    return {"QV_EST": qv}


def register_derives() -> None:
    for name, fn, outputs in (
            ("thomas_stieber", derive_thomas_stieber, TS_COLUMNS),
            ("pyrite_volume", derive_pyrite_volume, ("VPYR",)),
            ("qv_estimate", derive_qv_estimate, ("QV_EST",))):
        if name not in chain.DERIVES:
            register_derive(DeriveSpec(name, "segment", fn, outputs))


def register_all() -> None:
    """Register the laminated and pyrite steps and the three segment derives (idempotent)."""
    from modules.lrlc import laminated, pyrite
    laminated.register_step()
    pyrite.register_step()
    register_derives()


def run_derives(env: SegEnv) -> Dict[str, np.ndarray]:
    """Run the registered segment derives of this phase; ``{column: array}``."""
    out: Dict[str, np.ndarray] = {}
    for name in DERIVE_NAMES:
        spec = chain.DERIVES.get(name)
        if spec is not None and spec.scope == "segment":
            out.update(spec.fn(env))
    return out


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------
def build_guard(env: SegEnv, derived: Dict[str, np.ndarray], decisions: dict, states: dict
                ) -> Optional[Callable]:
    """The chain guard bound to this segment's zone states, or None without Thomas-Stieber output.

    ``decisions`` / ``states`` collect what the guard did per zone key (for the summary).
    """
    if "TS_CLASS" not in derived:
        return None
    gs = block(env.lrlc, "guard")
    stats = zone_stats(env.vsh_ts, derived["VLAM"], derived["TS_CLASS"], env.dz, env.keys,
                       gs["vsh_min"])
    zone_states = {k: zone_state(v, gs) for k, v in stats.items()}
    states.update(zone_states)
    bound = partial(evaluate_guard, zone_states=zone_states, guard_settings=gs,
                    rt_sbc_marked=env.plan.rt_sbc)

    def guard(zone, specs, ctx):
        dec = bound(zone, specs, ctx)
        decisions[zone] = dec
        return dec
    return guard


def guard_block(states: dict, decisions: dict, lrlc: dict) -> dict:
    return guard_summary(states, decisions, bool(block(lrlc, "guard")["enabled"]))


# ---------------------------------------------------------------------------
# Qv array and sand basis
# ---------------------------------------------------------------------------
def qv_array(env: SegEnv, qv_est: Optional[np.ndarray]) -> Optional[np.ndarray]:
    """Per-sample Qv for Waxman-Smits, or None when no zone estimates it."""
    if qv_est is None:
        return None
    scalar = float(env.p["ws_qv"])
    out = np.full(len(env.keys), scalar)
    for key in _unique(env.keys):
        if _resolved(env.lrlc, key).get("qv_source") != "estimate":
            continue
        mask = env.keys == key
        used, _ = qv_for_model(qv_est[mask], scalar)
        out[mask] = used
        need = mask & ~np.isfinite(qv_est) & np.isfinite(env.rt) & np.isfinite(env.vsh) \
            & np.isfinite(env.phit)
        count = int(need.sum())
        if count:
            env.add("LRLC_QV_FALLBACK",
                    f"{count} sample(s) in {_where(key)} have no Qv estimate and use the constant "
                    f"Qv {scalar:g}.", key)
    return out


def sand_basis(env: SegEnv, derived: Dict[str, np.ndarray]
               ) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """``(phie, phit, vsh)`` of the sand laminae where a zone reads the sand basis, else None."""
    phie, phit, vsh = env.phie.copy(), env.phit.copy(), env.vsh.copy()
    vlam, vdisp, phi_sand = derived.get("VLAM"), derived.get("VDISP"), derived.get("PHI_SAND")
    used = False
    primary = env.p.get("sw_primary_method")
    for key in _unique(env.keys):
        prm = _resolved(env.lrlc, key)
        laminated = "laminated" in step_names(prm)
        if prm.get("sw_basis") == "bulk" and laminated:
            if primary in ("Indonesian", "Simandoux"):
                env.add("LRLC_LAM_VSH_DOUBLE",
                        f"In {_where(key)} the {primary} model reads the bulk shale volume after "
                        "the laminated-sand correction, so laminar shale is counted twice; use "
                        "the sand basis or another model.", key)
            env.add("LRLC_LAM_BULK_PHI",
                    f"In {_where(key)} the Sw models read bulk porosity after the laminated-sand "
                    "correction; the sand-lamina porosity is higher.", key)
        if resolve_basis(prm) != "sand":
            continue
        used = True
        mask = env.keys == key
        pm = prm.get("phi_max")
        ok = np.zeros(len(env.keys), dtype=bool)
        if vlam is not None and pm is not None:
            with np.errstate(invalid="ignore", divide="ignore"):
                vd_s = vdisp / (1.0 - vlam)
                ok = (mask & np.isfinite(phi_sand) & np.isfinite(vlam) & np.isfinite(vdisp)
                      & (vlam < 1.0))
                phit[ok] = phi_sand[ok]
                vsh[ok] = vd_s[ok]
                phie[ok] = float(pm) - vd_s[ok]
        missing = int((mask & ~ok & np.isfinite(env.phie) & np.isfinite(env.rt)).sum())
        if missing:
            env.add("LRLC_LAM_NO_SAND_BASIS",
                    f"{missing} sample(s) in {_where(key)} have no sand-lamina values (no "
                    "Thomas-Stieber result) and use the bulk porosity and shale volume.", key)
    return (phie, phit, vsh) if used else None


# ---------------------------------------------------------------------------
# Issues from the step counts
# ---------------------------------------------------------------------------
def chain_count_issues(records: List[dict]) -> List[tuple]:
    out: List[tuple] = []
    for rec in records:
        counts = rec.get("counts") or {}
        zone = rec.get("zone")
        where = "the unzoned interval" if zone is None else f"zone {zone}"
        applicable = int(rec.get("n_valid", 0)) + int(rec.get("n_invalid", 0))
        step = rec.get("step")
        if step == "laminated":
            if counts.get("no_vlam"):
                out.append(("LRLC_HAG_NO_VLAM",
                            f"The laminated-sand correction has no laminar shale volume in {where} "
                            "(Thomas-Stieber is off or has no end-points there); no corrected Rt.",
                            zone, None))
            if counts.get("sensitive"):
                out.append(("LRLC_HAG_SENSITIVE",
                            f"Laminated-sand Rt: {counts['sensitive']} sample(s) in {where} amplify "
                            "the Rt error five times or more.",
                            zone, _share_severity(counts["sensitive"], applicable)))
            if counts.get("below_rsh"):
                out.append(("LRLC_HAG_RT_BELOW_RSH",
                            f"Laminated-sand Rt: {counts['below_rsh']} sample(s) in {where} read "
                            "below the shale resistivity.", zone, None))
        elif step == "pyrite":
            params = rec.get("params") or {}
            if params.get("pyr_f") is not None and float(params["pyr_f"]) <= 0:
                out.append(("LRLC_PYR_F_ZERO",
                            f"The pyrite step is selected in {where} with a connected fraction of "
                            "zero, so it changes nothing.", zone, None))
            if counts.get("sensitive"):
                out.append(("LRLC_PYR_SENSITIVE",
                            f"Pyrite correction: {counts['sensitive']} sample(s) in {where} remove "
                            "most of the measured conductance.",
                            zone, _share_severity(counts["sensitive"], applicable)))
    return out


# ---------------------------------------------------------------------------
# Thomas-Stieber summary
# ---------------------------------------------------------------------------
def ts_stats_by_key(results: pd.DataFrame, vsh, keys, dz, lrlc: dict) -> Dict[Any, dict]:
    vsh_min = block(lrlc, "guard")["vsh_min"]
    return zone_stats(vsh, results["VLAM"].to_numpy(dtype=float),
                      results["TS_CLASS"].to_numpy(), dz, keys, vsh_min)


def ts_block(stats: Dict[Any, dict], ts_notes: dict, has_labels: bool) -> dict:
    """``summary["lrlc"]["ts"]`` from :func:`ts_stats_by_key` and the per-zone end-point notes."""
    rows = []
    for key, st in stats.items():
        note = ts_notes.get(key) or {}
        rows.append({
            "zone": key if has_labels or key != UNZONED else WELL_ZONE,
            "phi_max": note.get("phi_max"), "phi_sh": note.get("phi_sh"),
            "n": st["n"], "class_counts": st["class_counts"],
            "lam_share": st["lam_share"], "mean_vlam": st["mean_vlam"],
            "clamped": dict(note.get("clamped") or {}),
        })
    return {"zones": rows}


# ---------------------------------------------------------------------------
# Diagnosis
# ---------------------------------------------------------------------------
def diagnose_all(results: pd.DataFrame, keys, zones: List[Tuple[str, Any]], dz, rt, vsh, pef,
                 rw_eff, lrlc: dict, ts_stats: Dict[Any, dict], zone_settings: Callable,
                 qv_default: float, warnings) -> List[dict]:
    """One diagnosis per ``(display name, zone key)`` of ``zones``.

    ``keys`` is the per-sample zone key; ``zone_settings(display name)`` returns
    ``{"sw_cutoff", "a", "m"}`` for the zone; ``ts_stats`` is
    :func:`modules.lrlc.thomas_stieber.zone_stats` output by zone key.
    """
    th = block(lrlc, "diagnosis")
    gs = block(lrlc, "guard")
    n = len(results)
    dz = np.broadcast_to(np.asarray(dz, dtype=float), (n,))
    frame_all = pd.DataFrame(index=results.index)
    for name in ("NET_RES_FLAG", "SW", "SW_ARCHIE", "BVW", "WATER_FREE_FLAG", "PHIT", "VPYR",
                 "QV_EST"):
        if name in results.columns:
            frame_all[name] = results[name].to_numpy()
    frame_all["RT"] = np.asarray(rt, dtype=float)
    frame_all["VSH"] = np.asarray(vsh, dtype=float)
    if pef is not None:
        frame_all["PEF"] = np.asarray(pef, dtype=float)
    rw_arr = np.broadcast_to(np.asarray(rw_eff, dtype=float), (n,))
    keys = np.asarray(keys, dtype=object)
    out = []
    for zone, key in zones:
        mask = keys == key
        prm = _resolved(lrlc, key)
        zs = zone_settings(zone)
        st = ts_stats.get(key)
        ts = None
        if st and st.get("n"):
            counts = st["class_counts"]
            classified = sum(counts[c] for c in range(1, 6))
            ts = {"lam_share": st["lam_share"], "mean_vlam": st["mean_vlam"],
                  "class13_share": (counts[1] + counts[3]) / classified if classified else None}
        ev = zone_evidence(
            frame_all[mask], dz[mask], sw_cutoff=zs["sw_cutoff"],
            screen_rt_max=prm["screen_rt_max"], a=zs["a"], m=zs["m"], rw_eff=rw_arr[mask],
            ts_stats=ts, qv_value=qv_default, min_n=th["min_n"])
        ev["zone"] = zone
        res = diagnose_zone(ev, th, gs)
        if res["status"] == "insufficient":
            warnings.add("LRLC_DIAG_INSUFFICIENT",
                         f"Diagnosis: {_where(key) if zone != WELL_ZONE else 'the well'} has "
                         f"{res['n_res']} net reservoir sample(s), fewer than {th['min_n']}.",
                         zone=None if zone == WELL_ZONE else zone)
        out.append(res)
    return out


def zone_note(result: dict, guard_zone: Optional[dict]) -> Optional[str]:
    """The ``lrlc_note`` text of one zone: the diagnosis sentence and the marked-RT sentence."""
    parts = []
    text = lrlc_note(result)
    if text:
        parts.append(text)
    if guard_zone and guard_zone.get("sbc_rt"):
        parts.append("RT is marked shoulder-bed corrected in this laminated zone; map the raw "
                     "deep RT.")
    return " ".join(parts) or None


# ---------------------------------------------------------------------------
# Validation (before / after)
# ---------------------------------------------------------------------------
def validation_block(results: pd.DataFrame, pay_stats: Callable, vsh, phie, sw_pay, sw_base_pay,
                     base_dhcpv, dz, zone_rows: List[dict], shf: Optional[dict],
                     n_shf_held: int, compare_stats: Callable) -> dict:
    """``summary["lrlc"]["validation"]``: pay before and after the corrections.

    ``pay_stats(results, vsh, phie, sw, dz, mask=None)`` is the pipeline's pay arithmetic;
    "before" is the stored ``NET_PAY_BASE_FLAG`` with ``sw_base_pay``.
    """
    base_res = results.copy()
    base_res["NET_PAY_FLAG"] = results["NET_PAY_BASE_FLAG"]
    now = pay_stats(results, vsh, phie, sw_pay, dz)
    base = pay_stats(base_res, vsh, phie, sw_base_pay, dz)
    hcpv_now = (float(results["dHCPV_NET_PAY"].sum())
                if "dHCPV_NET_PAY" in results.columns else None)
    hcpv_base = None if base_dhcpv is None else float(np.asarray(base_dhcpv, dtype=float).sum())
    well = {
        "net_pay_base": base["net_pay"], "net_pay": now["net_pay"],
        "delta": now["net_pay"] - base["net_pay"],
        "avg_sw_pay_base": base["avg_sw_pay"], "avg_sw_pay": now["avg_sw_pay"],
        "hcpv_net_pay_base": hcpv_base, "hcpv_net_pay": hcpv_now,
    }
    zones = []
    for row in zone_rows or []:
        if "net_pay_base" not in row:
            continue
        zones.append({
            "zone": row["zone"],
            "net_pay_base": row["net_pay_base"], "net_pay": row["net_pay"],
            "delta": row["net_pay"] - row["net_pay_base"],
            "avg_sw_pay_base": row["avg_sw_pay_base"], "avg_sw_pay": row["avg_sw_pay"],
            "hcpv_net_pay_base": row["hcpv_net_pay_base"],
            "hcpv_net_pay": row.get("hcpv_net_pay"),
        })
    shf_active = bool(shf and shf.get("pay_active"))
    out = {
        "basis": "measured RT, scalar Qv, bulk basis",
        "pay_sw": "SHF where available" if shf_active else "resistivity",
        "n_shf_held": int(n_shf_held),
        "well": well,
        "zones": zones,
    }
    if shf and "HAFWL" in results.columns and "SW_SHF" in results.columns:
        sw = np.asarray(results["SW"], dtype=float)
        swb = np.asarray(results["SW_BASE"], dtype=float)
        sws = np.asarray(results["SW_SHF"], dtype=float)
        mask = np.asarray(results["HAFWL"], dtype=float) > 0
        if "NET_RES_FLAG" in results.columns:
            mask &= np.asarray(results["NET_RES_FLAG"], dtype=float) == 1
        stats = shf.get("stats") or {}
        block_out = {"well": {"base": compare_stats(swb, sws, mask),
                              "corrected": stats.get("well")}, "zones": []}
        if "ZONE" in results.columns:
            zl = results["ZONE"].astype(object).where(results["ZONE"].notna(), UNZONED).to_numpy()
            corrected = {z["zone"]: z for z in stats.get("zones", [])}
            for z in dict.fromkeys(zl.tolist()):
                block_out["zones"].append({
                    "zone": str(z), "base": compare_stats(swb, sws, mask & (zl == z)),
                    "corrected": corrected.get(str(z))})
        out["shf"] = block_out
    return out
