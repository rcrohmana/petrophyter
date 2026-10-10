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
from typing import Dict, List, Optional, Tuple, TypeVar

from modules.las_utils import same_well

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
