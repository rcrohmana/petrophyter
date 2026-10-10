"""
Per-well file helpers shared by formation tops and core data.

A tops or core file may carry an optional well column. After the file has been
split by well (``FormationTops.split_by_well`` / ``CoreDataHandler.split_by_well``)
:func:`assign_to_wells` pairs each part with a loaded well, matching on UWI/API
when the column holds those identifiers and on the normalised well name
otherwise. :func:`depth_coverage_warning` tells the user when tops or core
depths do not overlap the well's logs.
"""

import math
import re
from typing import Dict, List, Optional, Tuple, TypeVar

from modules.las_utils import normalize_well_name, same_well

T = TypeVar("T")

# Token-matched column aliases, in priority order; the value is the kind of
# identifier the column holds ("name", "uwi" or "api").
WELL_COLUMN_ALIASES: List[Tuple[str, str]] = [
    ("well", "name"),
    ("well_name", "name"),
    ("wellname", "name"),
    ("well name", "name"),
    ("well id", "name"),
    ("uwi", "uwi"),
    ("api", "api"),
    ("wellbore", "name"),
    ("borehole", "name"),
    ("well identifier", "name"),
]


def find_well_column(df, find_column) -> Tuple[Optional[str], str]:
    """Return ``(column, kind)`` for the well column of ``df`` (``(None, "name")`` if absent).

    ``find_column(df, aliases)`` is the caller's token-matching column finder.
    """
    for alias, kind in WELL_COLUMN_ALIASES:
        col = find_column(df, [alias])
        if col is not None:
            return col, kind
    return None, "name"


def _info_for(name: str, kind: str) -> Dict:
    field = {"uwi": "uwi", "api": "api"}.get(kind, "well_name")
    return {field: name}


def assign_to_wells(split: Dict[str, T], wells: List[Tuple[str, Dict]],
                    kind: str = "name") -> Tuple[Dict[str, T], List[str]]:
    """Match the parts of a split file to loaded wells.

    Args:
        split: ``{name in file: part}`` from ``split_by_well()``.
        wells: ``[(well_key, well_info), ...]`` of the loaded wells.
        kind: what the file's well column holds: ``"name"``, ``"uwi"`` or ``"api"``
            (``FormationTops.well_kind`` / ``CoreDataHandler.well_kind``).

    Returns:
        ``(matches, unmatched)``: ``matches`` maps well key to its part; a well is
        matched at most once (the first name in file order wins) and ``unmatched``
        lists the file names that matched no free well.
    """
    matches: Dict[str, T] = {}
    unmatched: List[str] = []
    for name, part in split.items():
        probe = _info_for(name, kind)
        target = None
        for key, info in wells:
            if key in matches:
                continue
            verdict = same_well(probe, info)
            if verdict is None and kind != "name":
                # Some files put the well name in the UWI/API column.
                verdict = same_well({"well_name": name}, info)
            if verdict is True:
                target = key
                break
        if target is None:
            unmatched.append(name)
        else:
            matches[target] = part
    return matches, unmatched


def _clean_name(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def group_key(name, kind: str = "name") -> str:
    """Identity key of a well spelling: ``BKS-01``, ``bks 01`` and ``BKS_01`` share one."""
    text = _clean_name(name)
    if kind in ("uwi", "api"):
        return re.sub(r"[^A-Z0-9]", "", text.upper())
    return normalize_well_name(text) or text.upper()


def group_well_names(names, kind: str = "name") -> Dict[str, List[str]]:
    """Group spellings of the same well: ``{group_key: [spellings in first-seen order]}``."""
    groups: Dict[str, List[str]] = {}
    for name in names:
        text = _clean_name(name)
        if not text:
            continue
        spellings = groups.setdefault(group_key(text, kind), [])
        if text not in spellings:
            spellings.append(text)
    return groups


def fill_down_wells(wells) -> List[Optional[str]]:
    """Fill blank well cells with the last well above (``None`` before the first well)."""
    out: List[Optional[str]] = []
    current: Optional[str] = None
    for value in wells:
        text = _clean_name(value)
        if text:
            current = text
        out.append(current)
    return out


def merged_cell_pattern_applies(wells, depths=None) -> bool:
    """True when blank well cells look like merged cells (an Excel export).

    The first data row must carry a well, at least one cell must be blank, and
    after filling down every well's rows must form one contiguous block with
    non-decreasing depths (NaN depths are ignored).
    """
    cleaned = [_clean_name(w) for w in wells]
    if not cleaned or not cleaned[0] or all(cleaned):
        return False
    filled = fill_down_wells(wells)
    depth_list = list(depths) if depths is not None else [None] * len(filled)
    seen = set()
    prev = None
    last_depth = None
    for well, depth in zip(filled, depth_list):
        if well != prev:
            if well in seen:
                return False
            seen.add(well)
            prev = well
            last_depth = None
        try:
            value = float(depth)
        except (TypeError, ValueError):
            continue
        if math.isnan(value):
            continue
        if last_depth is not None and value < last_depth:
            return False
        last_depth = value
    return True


def depth_coverage_warning(name: str, top, bottom, log_min, log_max) -> Optional[str]:
    """Warn when ``name`` (a top or core interval, depths in ft) misses the log range.

    Returns ``None`` when the interval lies inside ``[log_min, log_max]`` or any
    depth is unknown.
    """
    try:
        t, b, lo, hi = float(top), float(bottom), float(log_min), float(log_max)
    except (TypeError, ValueError):
        return None
    if any(math.isnan(v) for v in (t, b, lo, hi)):
        return None
    if t > b:
        t, b = b, t
    span = f"{lo:.1f}-{hi:.1f} ft"
    if b < lo or t > hi:
        return f"{name} ({t:.1f}-{b:.1f} ft) lies entirely outside the log depth range ({span})."
    if t < lo or b > hi:
        return f"{name} ({t:.1f}-{b:.1f} ft) extends beyond the log depth range ({span})."
    return None
