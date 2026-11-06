"""LRLC export provenance (pure, no Qt): LAS curve descriptions and the Rt corrections text.

Both read ``ds.summary["lrlc"]`` written by the pipeline; a dataset without that block
yields nothing, so exports of runs without LRLC are unchanged.
"""

from typing import Any, Dict, List, Optional

from modules.lrlc.config import LRLC_PARAM_DEFAULTS

# Fixed descriptions (ASCII, no colon; derived curves are marked MODELLED)
_FIXED = {
    "RT_CUT": "MODELLED RT AT TARGET SW (primary model)",
    "BVW": "MODELLED BULK VOLUME WATER PHIE*SW",
    "WATER_FREE_FLAG": "FLAG SW AT OR BELOW SWIRR PLUS TOL IN NET RES",
    "LRLC_FLAG": "FLAG LRLC SCREENING CANDIDATE",
    "LRLC_SCORE": "COUNT OF SCREENING CRITERIA MET",
    "VLAM": "MODELLED LAMINAR SHALE VOLUME (THOMAS-STIEBER)",
    "VDISP": "MODELLED DISPERSED SHALE VOLUME (THOMAS-STIEBER)",
    "PHI_SAND": "MODELLED SAND POROSITY (THOMAS-STIEBER)",
    "TS_CLASS": "THOMAS-STIEBER CLASS CODE 0 TO 5",
    "QV_EST": "ESTIMATED QV FROM VSH AND CEC",
    "SW_BASE": "SW FROM MEASURED RT, NO LRLC CORRECTION",
    "NET_PAY_BASE_FLAG": "NET PAY FLAG FROM SW_BASE",
    "M_VAR": "MODELLED CEMENTATION EXPONENT (variable m, zone formula)",
    "N_VAR": "MODELLED SATURATION EXPONENT (variable n)",
    "RXO_INV": "MODELLED FLUSHED-ZONE RESISTIVITY (step profile)",
    "DI_INV": "MODELLED INVASION DIAMETER (step profile)",
}

# Step columns whose description names the curve they were computed from.
_STEP_TEXT = {
    "RT_SAND": "MODELLED LAMINATED-SAND RT (HAGIWARA)",
    "RT_PYR": "MODELLED PYRITE-CORRECTED RT",
    "RT_INV": "MODELLED INVASION-CORRECTED RT (step profile)",
}

OTHER_ZONE = "other"


def _lrlc_block(summary: Any) -> Optional[dict]:
    if not isinstance(summary, dict):
        return None
    block = summary.get("lrlc")
    return block if isinstance(block, dict) else None


def _zone_paths(chain: List[dict]) -> Dict[Any, List[str]]:
    """Per zone: the step columns in the order they ran (each step once)."""
    paths: Dict[Any, List[str]] = {}
    for rec in chain or []:
        if not isinstance(rec, dict):
            continue
        col = rec.get("curve")
        if not col:
            continue
        cols = paths.setdefault(rec.get("zone"), [])
        if col not in cols:
            cols.append(col)
    return paths


def _path_text(columns: List[str]) -> str:
    """``RT_PYR <- RT_SAND <- RT`` for steps that ran RT_SAND then RT_PYR."""
    return " <- ".join(list(reversed(columns)) + ["RT"])


def rt_corrections_text(summary_lrlc: Optional[dict]) -> str:
    """The "Rt corrections" provenance value (zones grouped by identical chain path)."""
    chain = summary_lrlc.get("chain") if isinstance(summary_lrlc, dict) else None
    paths = _zone_paths(chain or [])
    if not paths:
        return "none (RT_SW not written)"
    groups: Dict[str, List[str]] = {}
    for zone, cols in paths.items():
        label = OTHER_ZONE if zone is None else str(zone)
        groups.setdefault(_path_text(cols), []).append(label)
    return "; ".join(
        f"RT_SW = {path} (zones: {', '.join(zones)})" for path, zones in groups.items()
    )


def lrlc_curve_descriptions(ds: Any) -> Dict[str, str]:
    """LAS curve descriptions for the LRLC columns; ``{}`` when the run has no LRLC block."""
    block = _lrlc_block(getattr(ds, "summary", None))
    if block is None:
        return {}
    distinct: List[str] = []
    for cols in _zone_paths(block.get("chain") or []).values():
        text = _path_text(cols)
        if text not in distinct:
            distinct.append(text)
    path = " | ".join(distinct) if distinct else "RT"
    out = {"RT_SW": f"MODELLED RT READ BY SW MODELS ({path})"}
    out.update(_FIXED)
    out["VPYR"] = ("MODELLED PYRITE VOLUME FROM RHOB/PEF"
                   if any(v.get("pyr_method") == "rhob_pef" for _, v in _levels(block))
                   else "USER-SET PYRITE VOLUME")
    from modules.lrlc.chain import STEPS  # lazy: empty registry in this release

    for spec in STEPS.values():
        if spec.column and spec.description:
            out[spec.column] = str(spec.description)
    sources: Dict[str, List[str]] = {}
    for rec in block.get("chain") or []:
        if isinstance(rec, dict) and rec.get("curve") in _STEP_TEXT:
            origin = str(rec.get("from") or "RT")
            if origin not in sources.setdefault(rec["curve"], []):
                sources[rec["curve"]].append(origin)
    for column, text in _STEP_TEXT.items():
        out[column] = f"{text}, FROM {' OR '.join(sources.get(column) or ['RT'])}"
    return out


def _levels(block: dict) -> List[tuple]:
    """``(zone label or None, settings)``: the zone levels, or the default level alone."""
    params = block.get("params") if isinstance(block.get("params"), dict) else {}
    default = params.get("default") or {}
    zones = params.get("zones") or {}
    base = dict(LRLC_PARAM_DEFAULTS)
    if not zones:
        return [(None, {**base, **default})]
    return [(zone, {**base, **default, **(values or {})}) for zone, values in zones.items()]


def _num(value: Any) -> str:
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return "none"


def _scoped(label: Optional[str], text: str) -> str:
    return f"{label} {text}" if label else text


def lrlc_inputs_text(summary_lrlc: Optional[dict]) -> str:
    """The "LRLC inputs" provenance value; ``""`` when no laminated-mineral feature was used.

    Names the Thomas-Stieber end-points, the Qv estimate, the pyrite correction, the Sw
    basis and the shoulder-bed guard, read from the run's summary block.
    """
    if not isinstance(summary_lrlc, dict):
        return ""
    parts: List[str] = []
    ts = summary_lrlc.get("ts")
    if isinstance(ts, dict) and ts.get("zones"):
        items = []
        for row in ts["zones"]:
            zone = str(row.get("zone"))
            items.append(_scoped(
                None if zone == "WELL" else zone,
                f"phi_max {_num(row.get('phi_max'))} phi_sh {_num(row.get('phi_sh'))}"))
        parts.append("Thomas-Stieber " + ", ".join(items))
    levels = _levels(summary_lrlc)
    steps = {rec.get("step") for rec in summary_lrlc.get("chain") or [] if isinstance(rec, dict)}
    qv = [(z, v) for z, v in levels if v.get("qv_source") == "estimate"]
    if qv:
        parts.append("Qv estimate " + ", ".join(
            _scoped(z, f"cec_shale {_num(v.get('cec_shale'))}") for z, v in qv))
    if "pyrite" in steps:
        parts.append("Pyrite " + ", ".join(
            _scoped(z, f"{v.get('pyr_method', 'manual')} f {_num(v.get('pyr_f'))} "
                       f"Rpy {_num(v.get('pyr_rpy'))}") for z, v in levels))
    if "laminated" in steps:
        bases = {"bulk" if v.get("sw_basis") == "bulk" else "sand" for _, v in levels}
        parts.append("Sw basis " + "/".join(sorted(bases)))
    guard = summary_lrlc.get("guard")
    if parts and isinstance(guard, dict):
        parts.append("guard " + ("on" if guard.get("enabled") else "off"))
    return "; ".join(parts)


def variable_mn_text(summary_lrlc: Optional[dict]) -> str:
    """The "Variable m/n" provenance value; ``""`` unless a zone ran in curve mode."""
    block = summary_lrlc.get("variable_mn") if isinstance(summary_lrlc, dict) else None
    rows = block.get("zones") if isinstance(block, dict) else None
    if not rows:
        return ""
    groups: Dict[str, List[str]] = {}
    clipped = evaluated = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        m_text = ("M_VAR = Shell formula" if row.get("m_model") == "shell"
                  else "M_VAR = f(PHIE, VSH) formula")
        n_text = ("N_VAR = f(VSH) formula" if row.get("n_model") == "vsh"
                  else "N_VAR = constant")
        groups.setdefault(f"{m_text}, {n_text}", []).append(str(row.get("zone")))
        try:
            clipped += int(row.get("n_clipped_m") or 0) + int(row.get("n_clipped_n") or 0)
            evaluated += 2 * int(row.get("n_eval") or 0)
        except (TypeError, ValueError):
            pass
    if not groups:
        return ""
    text = "; ".join(f"{label} (zones: {', '.join(zones)})" for label, zones in groups.items())
    if evaluated:
        text += f"; clipped {100.0 * clipped / evaluated:.1f} %"
    return text


def invasion_tool_text(summary_lrlc: Optional[dict]) -> str:
    """The "Invasion tool" provenance value; ``""`` unless the invasion step ran."""
    block = summary_lrlc.get("invasion") if isinstance(summary_lrlc, dict) else None
    rows = block.get("zones") if isinstance(block, dict) else None
    if not rows:
        return ""
    parts = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        tool = str(row.get("tool") or "custom")
        note = f" ({row['badge'].split(',')[0]}, unconfirmed)" if row.get("generic") and row.get("badge") else ""
        parts.append(f"{tool}{note}")
    labels = list(dict.fromkeys(parts))
    zones = [str(r.get("zone")) for r in rows if isinstance(r, dict)]
    text = "; ".join(labels)
    if len(zones) > 1 or (zones and zones[0] != "WELL"):
        text += f" (zones: {', '.join(zones)})"
    return text
