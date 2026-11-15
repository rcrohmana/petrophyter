"""LRLC report frames: zones, Rt correction chain, references (pure: pandas only, no Qt, no services import).

Each builder takes ``wells``, a list of ``(label, summary, results)`` triples (the well summary with its
``lrlc`` block, and the results frame). Output is deterministic: wells sorted by label (stable), zones in the
order of ``summary["lrlc"]["screening"]["zones"]``, the ``(well)`` row first in the zones table. A cell of a
feature that is off is blank (None / NaN), never 0. Text cells are not made spreadsheet-safe here.
"""

import json
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from modules import references
from modules.lrlc import SHIPPED_METHODS
from modules.lrlc.chain import CHAIN_ORDER
from modules.petrophysics import depth_increments

WELL_ROW = "(well)"
_WELL_NAMES = ("WELL", None)
UNVERIFIED_MARK = "(to verify)"
ELASTIC_REF = "ashfaq_us11709287"
STEP_CURVES = {"decon": "RT_DECON", "invasion": "RT_INV", "laminated": "RT_SAND", "pyrite": "RT_PYR"}

ZONE_COLUMNS = (
    "Well", "Zone", "Top_ft", "Bottom_ft", "Samples", "Net_res_samples", "Flag_samples",
    "Flag_thickness_ft", "Flag_fraction_net", "Score_mean_net", "Water_free_samples", "Diagnosis",
    "Diagnosis_level", "Diagnosis_evidence", "Rt_steps", "Rt_source", "Rt_fallback", "Guard",
    "Net_pay_base_ft", "Net_pay_ft", "Net_pay_change_ft", "Avg_sw_pay_base", "Avg_sw_pay",
    "Hcpv_base", "Hcpv", "Sw_minus_shf_bias", "Sw_minus_shf_rmse", "Sw_shf_n", "Decon_status",
    "Decon_beds", "Decon_misfit_rms", "Decon_amplified", "Decon_width_sensitivity",
    "Elastic_flag_samples",
    "Elastic_flag_thickness_ft", "Elastic_wet_samples", "Issues",
)
STEP_COLUMNS = ("Well", "Zone", "Order", "Step", "Curve", "From", "Status", "Valid_samples",
                "Invalid_samples", "Fallback_samples", "Params", "References")
REF_COLUMNS = ("Key", "Citation", "Status", "Used_by")

# summary block -> SHIPPED_METHODS key, for the references the screening-side content cites
_BLOCK_METHODS = (("rt_cutoff", "rt_cutoff"), ("variable_mn", "variable_mn"),
                  ("ts", "thomas_stieber"))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _lrlc(summary) -> Optional[dict]:
    block = (summary or {}).get("lrlc")
    return block if isinstance(block, dict) and "skipped" not in block else None


def wells_with_lrlc(wells) -> list:
    """The triples whose summary has an LRLC block that ran (no ``skipped`` marker)."""
    return [w for w in (wells or []) if _lrlc(w[1]) is not None]


def _sorted(wells) -> list:
    return sorted(wells_with_lrlc(wells), key=lambda w: str(w[0]))


def _name(zone) -> str:
    return WELL_ROW if zone in _WELL_NAMES else str(zone)


def _zones(lrlc: dict) -> list:
    """Zone names of the well in screening order (``WELL`` for an unzoned well)."""
    rows = (lrlc.get("screening") or {}).get("zones") or []
    out = list(dict.fromkeys(r.get("zone") for r in rows))
    return out or ["WELL"]


def _num(value):
    """A python float / int, or None for missing and NaN."""
    if value is None or isinstance(value, bool):
        return value
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(f):
        return None
    return int(value) if isinstance(value, (int, np.integer)) else f


def _by_zone(rows, key="zone") -> dict:
    return {r.get(key): r for r in rows or [] if isinstance(r, dict)}


def _col(results, name):
    if results is None or name not in results.columns:
        return None
    return pd.to_numeric(results[name], errors="coerce").to_numpy(dtype=float)


def _zone_mask(results, zone, unzoned: bool):
    n = len(results)
    if zone is None or unzoned:
        return np.ones(n, dtype=bool)
    if "ZONE" not in results.columns:
        return np.zeros(n, dtype=bool)
    return (results["ZONE"].astype(object).astype(str) == str(zone)).to_numpy()


def _fmt(value) -> str:
    try:
        return f"{float(value):.4g}"
    except (TypeError, ValueError):
        return str(value)


def _width_sensitivity_text(entry) -> Optional[str]:
    """``3.2 / 4.0 / 5.0 ft: 1.9 / 2.0 / 1.7 x (valid 19 / 19 / 14 of 19)`` from a zone's
    ``width_sensitivity`` (None when absent or when no sample is raised by more than 10 percent)."""
    if not isinstance(entry, dict):
        return None
    if entry.get("n") is not None and _num(entry.get("n")) == 0:
        return None
    widths, ratios = entry.get("widths_ft"), entry.get("median_ratio")
    if not isinstance(widths, (list, tuple)) or not isinstance(ratios, (list, tuple)) or not widths:
        return None
    w_text = " / ".join("n/a" if _num(w) is None else f"{_num(w):.1f}" for w in widths)
    r_text = " / ".join("n/a" if _num(r) is None else f"{_num(r):.1f}" for r in ratios)
    text = f"{w_text} ft: {r_text} x"
    valid, total = entry.get("n_valid"), _num(entry.get("n"))
    if isinstance(valid, (list, tuple)) and valid and total is not None:
        v_text = " / ".join("n/a" if _num(v) is None else str(int(_num(v))) for v in valid)
        text += f" (valid {v_text} of {int(total)})"
    return text


def _resolved(lrlc: dict, zone) -> dict:
    params = lrlc.get("params") or {}
    out = dict(params.get("default") or {})
    if zone not in _WELL_NAMES:
        out.update((params.get("zones") or {}).get(zone) or {})
    return out


def _ordered_steps(steps) -> list:
    steps = list(dict.fromkeys(steps or []))
    return sorted(steps, key=lambda s: (CHAIN_ORDER.index(s) if s in CHAIN_ORDER else len(CHAIN_ORDER), s))


def _zone_records(lrlc: dict, zone) -> list:
    """Chain records of one zone, first record per step, in chain order."""
    seen: Dict[str, dict] = {}
    for rec in lrlc.get("chain") or []:
        if _name(rec.get("zone")) == _name(zone):
            seen.setdefault(rec.get("step"), rec)
    return [seen[s] for s in _ordered_steps(list(seen))]


def _guard_entry(lrlc: dict, zone) -> Optional[dict]:
    for z in (lrlc.get("guard") or {}).get("zones") or []:
        if _name(z.get("zone")) == _name(zone):
            return z
    return None


def _short(key: str) -> str:
    try:
        text = references.format_short(key)
        verified = references.REFERENCES[key].status == "verified"
    except KeyError:
        text, verified = key, False
    return text if verified else f"{text} {UNVERIFIED_MARK}"


# ---------------------------------------------------------------------------
# zones table
# ---------------------------------------------------------------------------
def _issue_count(summary: dict, zone) -> int:
    n = 0
    for i in summary.get("issues") or []:
        if not str(i.get("code", "")).startswith("LRLC_") or i.get("severity") not in ("warning", "error"):
            continue
        if zone is None or _name(i.get("zone")) == _name(zone):
            n += 1
    return n


def _diagnosis_cells(lrlc: dict, zone) -> tuple:
    res = _by_zone(lrlc.get("zones")).get(zone)
    if res is None:
        return None, None, None
    if res.get("status") == "insufficient":
        return "insufficient", None, None
    key = res.get("primary")
    if not key:
        return "none", None, None
    cause = next((c for c in res.get("causes") or [] if c.get("key") == key), {})
    met = [f"{c['id']} {c['op']} {_fmt(c['threshold'])} ({_fmt(c['value'])})"
           for c in cause.get("criteria") or [] if c.get("met")]
    return key, cause.get("level"), "; ".join(met) or None


def _row_cells(label, summary, results, zone, well_row: bool, dz) -> dict:
    lrlc = summary["lrlc"]
    zone_names = _zones(lrlc)
    unzoned = zone_names == ["WELL"]
    row = {c: None for c in ZONE_COLUMNS}
    row["Well"], row["Zone"] = label, WELL_ROW if well_row else _name(zone)
    key = None if well_row else zone              # lookup key of the zone-keyed blocks
    use_zone = well_row and unzoned               # the single zone of an unzoned well is the well
    if use_zone:
        key = "WELL"

    # results-based counts
    if results is not None and len(results):
        mask = _zone_mask(results, zone, well_row or unzoned)
        net, flag = _col(results, "NET_RES_FLAG"), _col(results, "LRLC_FLAG")
        score, wf = _col(results, "LRLC_SCORE"), _col(results, "WATER_FREE_FLAG")
        row["Samples"] = int(mask.sum())
        if "DEPTH" in results.columns:
            depth = pd.to_numeric(results["DEPTH"], errors="coerce").to_numpy(dtype=float)[mask]
            if np.isfinite(depth).any():
                row["Top_ft"], row["Bottom_ft"] = _num(np.nanmin(depth)), _num(np.nanmax(depth))
        if net is not None:
            is_net = mask & (net == 1)
            row["Net_res_samples"] = int(is_net.sum())
            if score is not None:
                vals = score[is_net]
                vals = vals[np.isfinite(vals)]
                row["Score_mean_net"] = _num(vals.mean()) if vals.size else None
        if flag is not None:
            is_flag = mask & (flag == 1)
            row["Flag_samples"] = int(is_flag.sum())
            if dz is not None:
                row["Flag_thickness_ft"] = _num(np.nansum(dz[is_flag]))
            if net is not None and row["Net_res_samples"]:
                row["Flag_fraction_net"] = row["Flag_samples"] / row["Net_res_samples"]
        if wf is not None:
            row["Water_free_samples"] = int((mask & (wf == 1)).sum())
    zrow = _by_zone((lrlc.get("screening") or {}).get("zones")).get(key)
    if zrow and row["Flag_thickness_ft"] is None:
        row["Flag_thickness_ft"] = _num(zrow.get("candidate_ft"))
    srow = _by_zone(summary.get("zones")).get(key)
    if srow:
        row["Top_ft"] = _num(srow.get("top")) if row["Top_ft"] is None else row["Top_ft"]
        row["Bottom_ft"] = _num(srow.get("bottom")) if row["Bottom_ft"] is None else row["Bottom_ft"]
        if row["Samples"] is None:
            row["Samples"] = _num(srow.get("samples"))

    # diagnosis (one per zone; the well row only for an unzoned well)
    if not well_row or use_zone:
        row["Diagnosis"], row["Diagnosis_level"], row["Diagnosis_evidence"] = _diagnosis_cells(lrlc, key)

    # chain
    prm = _resolved(lrlc, None if (well_row and not use_zone) else key)
    steps = _ordered_steps(prm.get("rt_steps"))
    if steps:
        row["Rt_steps"] = " > ".join(steps)
        row["Rt_fallback"] = prm.get("rt_fallback")
    recs = [] if (well_row and not use_zone) else _zone_records(lrlc, key)
    if recs:
        row["Rt_source"] = " <- ".join([r["curve"] for r in reversed(recs)] + [recs[0].get("from") or "RT"])
    guard = lrlc.get("guard")
    if guard is not None:
        text = "on" if guard.get("enabled") else "off"
        entry = _guard_entry(lrlc, key) if (not well_row or use_zone) else None
        if entry and entry.get("blocked_steps"):
            text += "; blocked: " + ", ".join(entry["blocked_steps"])
        row["Guard"] = text
    else:
        row["Guard"] = "n/a"

    # validation (before / after)
    val = lrlc.get("validation")
    if val:
        v = val.get("well") if (well_row and not use_zone) else _by_zone(val.get("zones")).get(key)
        if v is None and use_zone:
            v = val.get("well")
        if v:
            row["Net_pay_base_ft"], row["Net_pay_ft"] = _num(v.get("net_pay_base")), _num(v.get("net_pay"))
            row["Net_pay_change_ft"] = _num(v.get("delta"))
            row["Avg_sw_pay_base"], row["Avg_sw_pay"] = _num(v.get("avg_sw_pay_base")), _num(v.get("avg_sw_pay"))
            row["Hcpv_base"], row["Hcpv"] = _num(v.get("hcpv_net_pay_base")), _num(v.get("hcpv_net_pay"))
        shf = val.get("shf")
        if shf:
            s = shf.get("well") if (well_row and not use_zone) else _by_zone(shf.get("zones")).get(key)
            if s is None and use_zone:
                s = shf.get("well")
            corrected = (s or {}).get("corrected")
            if corrected:
                row["Sw_minus_shf_bias"] = _num(corrected.get("bias"))
                row["Sw_minus_shf_rmse"] = _num(corrected.get("rmse"))
                row["Sw_shf_n"] = _num(corrected.get("n"))

    # deconvolution
    decon = lrlc.get("decon")
    if decon:
        zones = _by_zone(decon.get("zones"))
        if well_row and not use_zone:
            row["Decon_beds"] = _num(decon.get("n_beds"))
            row["Decon_amplified"] = _num(sum(int(z.get("n_amplified") or 0) for z in zones.values()))
        else:
            z = zones.get(key)
            row["Decon_status"] = z.get("status") if z else "not requested"
            if z:
                bounds = (decon.get("boundaries") or {}).get(key)
                row["Decon_beds"] = _num(z["n_beds"]) if "n_beds" in z else (
                    max(len(bounds) - 1, 0) if bounds is not None else None)
                row["Decon_misfit_rms"] = _num(z.get("misfit_rms"))
                row["Decon_amplified"] = _num(z.get("n_amplified"))
                row["Decon_width_sensitivity"] = _width_sensitivity_text(z.get("width_sensitivity"))
            if use_zone:
                row["Decon_beds"] = _num(decon.get("n_beds")) if row["Decon_beds"] is None else row["Decon_beds"]

    # elastic screening
    el = lrlc.get("elastic")
    if el and "skipped" not in el:
        zones = el.get("zones") or []
        if well_row and not use_zone:
            row["Elastic_flag_samples"] = _num((el.get("counts") or {}).get("flag", sum(
                int(z.get("n_flag") or 0) for z in zones)))
            row["Elastic_flag_thickness_ft"] = _num(sum(float(z.get("thickness_flag_ft") or 0.0) for z in zones))
            row["Elastic_wet_samples"] = _num((el.get("wet") or {}).get("n"))
        else:
            z = _by_zone(zones).get(key)
            if z:
                row["Elastic_flag_samples"] = _num(z.get("n_flag"))
                row["Elastic_flag_thickness_ft"] = _num(z.get("thickness_flag_ft"))
            if use_zone:
                row["Elastic_wet_samples"] = _num((el.get("wet") or {}).get("n"))

    row["Issues"] = _issue_count(summary, None if well_row else key)
    if use_zone:
        row["Issues"] = _issue_count(summary, None)
    return row


def zones_frame(wells) -> pd.DataFrame:
    """One row per well and zone, the ``(well)`` row first; columns ``ZONE_COLUMNS``."""
    rows = []
    for label, summary, results in _sorted(wells):
        lrlc = summary["lrlc"]
        dz = None
        if results is not None and len(results) and "DEPTH" in results.columns:
            dz = depth_increments(results["DEPTH"]).to_numpy(dtype=float)
        rows.append(_row_cells(label, summary, results, None, True, dz))
        names = _zones(lrlc)
        if names == ["WELL"]:
            continue
        for zone in names:
            rows.append(_row_cells(label, summary, results, zone, False, dz))
    return pd.DataFrame(rows, columns=list(ZONE_COLUMNS))


# ---------------------------------------------------------------------------
# chain table
# ---------------------------------------------------------------------------
def _params_text(params) -> Optional[str]:
    if not params:
        return None
    return json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)


def steps_frame(wells) -> pd.DataFrame:
    """One row per well, zone and step (ran, blocked or skipped); columns ``STEP_COLUMNS``."""
    rows = []
    for label, summary, _results in _sorted(wells):
        lrlc = summary["lrlc"]
        for zone in _zones(lrlc):
            recs = {r["step"]: r for r in _zone_records(lrlc, zone)}
            guard = _guard_entry(lrlc, zone) or {}
            blocked = list(guard.get("blocked_steps") or [])
            requested = _resolved(lrlc, zone).get("rt_steps") or []
            for order, step in enumerate(_ordered_steps(list(requested) + list(recs) + blocked), 1):
                rec = recs.get(step)
                row = {c: None for c in STEP_COLUMNS}
                row.update(Well=label, Zone=_name(zone), Order=order, Step=step,
                           Curve=STEP_CURVES.get(step))
                if rec is not None:
                    row.update(Curve=rec.get("curve"), From=rec.get("from"), Status="ran",
                               Valid_samples=_num(rec.get("n_valid")),
                               Invalid_samples=_num(rec.get("n_invalid")),
                               Fallback_samples=_num(rec.get("fallback")),
                               Params=_params_text(rec.get("params")),
                               References="; ".join(_short(k) for k in rec.get("refs") or []) or None)
                else:
                    row["Status"] = "blocked" if step in blocked else "skipped"
                rows.append(row)
    return pd.DataFrame(rows, columns=list(STEP_COLUMNS))


# ---------------------------------------------------------------------------
# references table
# ---------------------------------------------------------------------------
def _cited(lrlc: dict) -> List[Tuple[str, str]]:
    """``(reference key, used by)`` pairs of one well's content."""
    pairs = []
    for rec in lrlc.get("chain") or []:
        pairs += [(k, str(rec.get("step"))) for k in rec.get("refs") or []]
    if lrlc.get("screening"):
        pairs += [(k, "screening") for k in SHIPPED_METHODS.get("screening", ())]
    for block, method in _BLOCK_METHODS:
        if lrlc.get(block):
            pairs += [(k, method) for k in SHIPPED_METHODS.get(method, ())]
    el = lrlc.get("elastic")
    if el and "skipped" not in el:
        pairs += [(k, "elastic") for k in SHIPPED_METHODS.get("elastic", (ELASTIC_REF,))]
    return pairs


def refs_frame(wells) -> pd.DataFrame:
    """Only the keys the exported wells cite; columns ``REF_COLUMNS``, sorted by key."""
    used: Dict[str, List[str]] = {}
    for _label, summary, _results in _sorted(wells):
        for key, by in _cited(summary["lrlc"]):
            if key in references.REFERENCES and by not in used.setdefault(key, []):
                used[key].append(by)
    rows = [{"Key": key, "Citation": references.format_full(key),
             "Status": references.REFERENCES[key].status, "Used_by": "; ".join(sorted(by))}
            for key, by in sorted(used.items())]
    return pd.DataFrame(rows, columns=list(REF_COLUMNS))
