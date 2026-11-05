"""LRLC export provenance (pure, no Qt): LAS curve descriptions and the Rt corrections text.

Both read ``ds.summary["lrlc"]`` written by the pipeline; a dataset without that block
yields nothing, so exports of runs without LRLC are unchanged.
"""

from typing import Any, Dict, List, Optional

# Fixed descriptions (ASCII, no colon; derived curves are marked MODELLED)
_FIXED = {
    "RT_CUT": "MODELLED RT AT TARGET SW (primary model)",
    "BVW": "MODELLED BULK VOLUME WATER PHIE*SW",
    "WATER_FREE_FLAG": "FLAG SW AT OR BELOW SWIRR PLUS TOL IN NET RES",
    "LRLC_FLAG": "FLAG LRLC SCREENING CANDIDATE",
    "LRLC_SCORE": "COUNT OF SCREENING CRITERIA MET",
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
    from modules.lrlc.chain import STEPS  # lazy: empty registry in this release

    for spec in STEPS.values():
        if spec.column and spec.description:
            out[spec.column] = str(spec.description)
    return out
