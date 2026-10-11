"""Curve Mapping detail (U11): unit, coverage, range and auto or manual mapping per curve type."""
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from modules.las_parser import find_curve

DETAIL_COLUMNS = ["Type", "Curve", "Unit", "Coverage", "Range", "Mapping"]
# Coverage below this share of the well's samples is shown in warning style.
LOW_COVERAGE = 0.5


def _curve_units(ds) -> Dict[str, Dict]:
    """``curve_info`` of the data the well holds: the merge's for a merged well, else the file's."""
    report = getattr(ds, "merge_report", None)
    info = getattr(report, "curve_info", None) if getattr(ds, "merged", False) else None
    if not info:
        info = getattr(getattr(ds, "las_parser", None), "curve_info", None)
    return info or {}


def _fmt(value: float) -> str:
    return f"{value:.4g}"


def curve_detail_rows(ds) -> List[Dict]:
    """One row per curve type of ``ds.curve_mapping``.

    Keys: ``type``, ``curve`` ("None" when unmapped), ``unit``, ``coverage``
    (share of the well's samples with a value, or None), ``range`` (min, max or
    None), ``mapping`` ("Auto" when the curve is the one detected from the
    curve names, "Manual" when the user chose another one or cleared a detected
    curve, "" when nothing is mapped or detected) and ``detected`` (the curve
    detection would pick, or None).
    """
    if ds is None:
        return []
    data: Optional[pd.DataFrame] = getattr(ds, "las_data", None)
    columns = list(data.columns) if data is not None else []
    units = _curve_units(ds)
    rows = []
    for ctype, mapped in (ds.curve_mapping or {}).items():
        curve = mapped if mapped and mapped != "None" else None
        detected = find_curve(columns, ctype)
        row = {"type": ctype, "curve": curve or "None", "unit": "", "coverage": None,
               "range": None, "detected": detected}
        if curve is None:
            row["mapping"] = "Manual" if detected else ""
        else:
            row["mapping"] = "Auto" if curve == detected else "Manual"
        if curve is not None and data is not None and curve in data.columns:
            values = pd.to_numeric(data[curve], errors="coerce").to_numpy(dtype=float)
            finite = values[np.isfinite(values)]
            row["coverage"] = len(finite) / len(values) if len(values) else 0.0
            if len(finite):
                row["range"] = (float(finite.min()), float(finite.max()))
            row["unit"] = str((units.get(curve) or {}).get("unit") or "").strip()
        rows.append(row)
    return rows


def detail_cells(row: Dict) -> List[str]:
    """The table cells of one row, in ``DETAIL_COLUMNS`` order."""
    coverage = "" if row["coverage"] is None else f"{row['coverage'] * 100:.1f} %"
    span = "" if row["range"] is None else f"{_fmt(row['range'][0])} – {_fmt(row['range'][1])}"
    unit = row["unit"] or ("—" if row["curve"] != "None" else "")
    return [row["type"], row["curve"], unit, coverage, span, row["mapping"]]


def detail_tooltip(row: Dict) -> str:
    """Why a row reads as it does (mapping source, low coverage)."""
    parts = []
    if row["mapping"] == "Auto":
        parts.append(f"Detected from the curve names: {row['curve']}")
    elif row["mapping"] == "Manual":
        parts.append("Chosen by you" + (f"; detection would pick {row['detected']}"
                                        if row["detected"] else "; detection finds no curve"))
    if row["coverage"] is not None and row["coverage"] < LOW_COVERAGE:
        parts.append(f"Values on fewer than {LOW_COVERAGE:.0%} of the well's samples")
    if row["curve"] != "None" and not row["unit"]:
        parts.append("The file gives no unit for this curve")
    return ". ".join(parts)
