"""What changed between a well's last-run parameters and its current ones (P0-UI/UX U12).

Both sides are ``AppModel.params_for_well`` dicts. A zone is reported only where it
does not simply follow the well: a project Rw change shows once, not once per zone.
"""
import math
from typing import Dict, List, Optional

# Keys of params_for_well that are not parameters (or are compared on their own).
_SKIP = {"param_info", "zone_plan", "curve_mapping"}
MISSING = object()


def _same(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b or a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
            return True
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    return a == b


def format_value(value) -> str:
    if value is MISSING or value is None:
        return "not set"
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, (list, tuple)):
        return ", ".join(format_value(v) for v in value) or "none"
    if isinstance(value, dict):
        return ", ".join(f"{k}={format_value(v)}" for k, v in value.items()) or "none"
    return str(value)


def _flat(params: Dict) -> Dict:
    return {k: v for k, v in params.items() if k not in _SKIP and not k.startswith("_")}


def _zone_params(params: Dict, zone: str) -> Dict:
    """A zone's effective parameters: its plan entry, or the well's when it has none."""
    entry = (params.get("zone_plan") or {}).get(zone)
    return _flat(entry["params"]) if entry else _flat(params)


def _diff(old: Dict, new: Dict, where: str) -> List[Dict]:
    out = []
    for key in list(old) + [k for k in new if k not in old]:
        a, b = old.get(key, MISSING), new.get(key, MISSING)
        if a is MISSING or b is MISSING:
            if a is b:
                continue
        elif _same(a, b):
            continue
        out.append({"where": where, "name": key, "old": a, "new": b, "revertible": True})
    return out


def param_changes(old: Dict, new: Dict, old_tops=None, new_tops=None) -> List[Dict]:
    """Changes from ``old`` to ``new``: ``{"where", "name", "old", "new", "revertible"}``.

    ``where`` is "" for the well, a zone name, or "curves" for the curve mapping.
    Formation tops (``old_tops``/``new_tops``) are data, not parameters: a change is
    reported with ``revertible`` False.
    """
    old_well, new_well = _flat(old), _flat(new)
    changes = _diff(old_well, new_well, "")
    old_map, new_map = old.get("curve_mapping") or {}, new.get("curve_mapping") or {}
    for ctype in list(old_map) + [c for c in new_map if c not in old_map]:
        a, b = old_map.get(ctype, "None"), new_map.get(ctype, "None")
        if a != b:
            changes.append({"where": "curves", "name": f"{ctype} curve", "old": a, "new": b,
                            "revertible": True})
    zones = list(old.get("zone_plan") or {})
    zones += [z for z in (new.get("zone_plan") or {}) if z not in zones]
    for zone in zones:
        old_zone, new_zone = _zone_params(old, zone), _zone_params(new, zone)
        for change in _diff(old_zone, new_zone, zone):
            key = change["name"]
            follows_well = (_same(old_zone.get(key), old_well.get(key))
                            and _same(new_zone.get(key), new_well.get(key)))
            if not follows_well:
                changes.append(change)
    if old_tops is not None and new_tops is not None and list(old_tops) != list(new_tops):
        changes.append({"where": "", "name": "Formation tops", "old": len(old_tops),
                        "new": len(new_tops), "revertible": False})
    return changes


def describe(change: Dict) -> str:
    """One line for a change, e.g. ``UPPER SAND · m: 2 → 2.15``."""
    if change["name"] == "Formation tops":
        return "Formation tops changed (Revert does not restore tops)"
    where = change["where"]
    prefix = "" if where in ("", "curves") else f"{where} · "
    return f"{prefix}{change['name']}: {format_value(change['old'])} → {format_value(change['new'])}"


def summary_text(changes: List[Dict], limit: int = 2) -> Optional[str]:
    """Short footer text: the first ``limit`` changes and how many more."""
    if not changes:
        return None
    lines = [describe(c) for c in changes]
    head = "; ".join(lines[:limit])
    more = len(lines) - limit
    count = f"{len(lines)} change{'s' if len(lines) != 1 else ''} since the last run"
    return f"{count}: {head}" + (f" (+{more} more)" if more > 0 else "")
