"""
Import plan for multi-well tops and core files (pure, no Qt, no model access).

A tops or core file with a well column holds the data of several wells. This
module turns the parsed file plus a snapshot of the loaded wells into an
:class:`ImportPlan`: one :class:`ImportRow` per well in the file, with the well
it matches, the existing data it would replace, the depth coverage, the unit
fit and the blockers that keep the dialog's OK button disabled. The dialog
shows the plan; ``build_parts`` produces the objects the apply step attaches.

Typical use::

    parsed = parse_import_file(path, options)
    plan = build_import_plan(parsed, path, well_refs(project, options.kind), options)
    # ... the user edits plan.set_target / plan.set_action ...
    if not plan.blockers():
        parts = build_parts(plan, plan.wells)      # {well key: tops / core part}

A change of ``options.depth_unit`` only needs a new plan from the same parsed
file; a change of columns, fill-down, sheet or porosity scale needs a new
``parse_import_file``.
"""

import copy
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

from modules.formation_tops import FormationTops, extend_last_bottom
from modules.las_utils import same_well
from modules.param_scopes import normalize_zone
from modules.well_matching import depth_coverage_warning, group_key

M_TO_FT = FormationTops.M_TO_FT
_ACTIONS = ("assign", "keep", "replace", "skip")
_APPLY = ("assign", "replace")
_O2O_NOTE = "Also assigned to the same well by "


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class ImportOptions:
    """What the user chose in the dialog (and what a replayed import record says)."""
    kind: str                           # "tops" | "core"
    depth_unit: Optional[str] = None    # None = use detection; "M" / "FT" = user choice
    fill_down: Optional[bool] = None    # None = default (parsed.fill_down_applicable)
    last_bottom: str = "log_bottom"     # or "next_top"
    sheet: Union[int, str] = 0
    columns: Optional[dict] = None      # explicit column override, by original header name
    porosity_scales: dict = field(default_factory=dict)  # {file well: "percent" | "fraction"}
    tvd_confirmed: bool = False         # core TVD depth column acknowledged


@dataclass
class WellRef:
    """What the plan needs from a loaded well (a plain snapshot, no Qt)."""
    key: str
    display_name: str
    well_info: dict
    log_top: Optional[float] = None         # ft, from DEPTH
    log_bottom: Optional[float] = None
    existing_count: int = 0                 # formations / samples already attached
    existing_path: Optional[str] = None
    zones_with_params: list = field(default_factory=list)   # normalised zone names
    selected_formations: list = field(default_factory=list)


@dataclass
class ImportRow:
    """One well of the file and what would happen to it."""
    file_well: str                          # first spelling
    spellings: List[str]
    group_key: str
    part: object                            # FormationTops / CoreDataHandler, not unit-converted
    rows: int = 0
    excluded: list = field(default_factory=list)      # [(line, reason)]
    depth_range: Optional[Tuple[float, float]] = None  # ft under the effective unit
    status: str = "no_match"                # "matched" | "no_match" | "ambiguous"
    match_how: Optional[str] = None         # "uwi" | "api" | "name" | "manual"
    candidates: List[str] = field(default_factory=list)  # loaded keys when ambiguous
    target_key: Optional[str] = None
    existing: str = "none"                  # "none" | "12 formations (tops.csv)" | ...
    action: str = "skip"                    # "assign" | "keep" | "replace" | "skip"
    coverage: Optional[float] = None        # fraction of the part inside the target's logs
    coverage_note: Optional[str] = None
    unit_fit: Optional[str] = None          # "M" / "FT" when only one reading fits the logs
    porosity_scale: Optional[str] = None    # core: "percent" | "fraction"
    zone_impact: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class ImportPlan:
    kind: str
    path: str
    options: ImportOptions
    parsed: object
    rows: List[ImportRow] = field(default_factory=list)
    no_well_rows: list = field(default_factory=list)   # [(line, reason)] excluded, no well
    effective_unit: Optional[str] = None    # "M" | "FT" | None (undetected, not chosen)
    notes: List[str] = field(default_factory=list)
    wells: List[WellRef] = field(default_factory=list)

    # ---- queries ----
    @property
    def wells_not_in_file(self) -> List[str]:
        """Display names of the loaded wells no row targets."""
        targeted = {r.target_key for r in self.rows if r.target_key}
        return [w.display_name for w in self.wells if w.key not in targeted]

    def changes(self) -> int:
        """Rows that would attach data to a well."""
        return sum(1 for r in self.rows if r.action in _APPLY and r.target_key)

    def _conflicts(self) -> Dict[str, List[ImportRow]]:
        by_target: Dict[str, List[ImportRow]] = {}
        for row in self.rows:
            if row.action in _APPLY and row.target_key:
                by_target.setdefault(row.target_key, []).append(row)
        return {k: v for k, v in by_target.items() if len(v) > 1}

    def blockers(self) -> List[str]:
        """Reasons the OK button must stay disabled (empty = the plan can be applied)."""
        out: List[str] = []
        if self.effective_unit is None:
            out.append("Choose the depth unit (M or FT)")
        for row in self.rows:
            if row.status == "ambiguous" and row.target_key is None:
                out.append(f"Choose the well for {row.file_well} "
                           f"({len(row.candidates)} loaded wells match)")
        for key, rows in self._conflicts().items():
            names = " and ".join(r.file_well for r in rows)
            out.append(f"{names} are assigned to the same well ({self._display(key)})")
        if self.kind == "core" and getattr(self.parsed, "depth_is_tvd", False) \
                and not self.options.tvd_confirmed:
            out.append("Confirm that TVD core depths may be used")
        if not out and self.changes() == 0:
            out.append("No well would receive data")
        return out

    # ---- manual edits ----
    def set_target(self, row_index: int, key_or_none: Optional[str]) -> None:
        """Map a file well to a loaded well by hand (``None`` skips it)."""
        row = self.rows[row_index]
        if key_or_none is not None and self._ref(key_or_none) is None:
            raise KeyError(key_or_none)
        row.target_key = key_or_none
        if key_or_none is None:
            row.status, row.match_how = "no_match", None
        else:
            row.status, row.match_how = "matched", "manual"
        self._settle(row, reset_action=True)
        self._flag_conflicts()

    def set_action(self, row_index: int, action: str) -> None:
        """Choose ``assign`` / ``keep`` / ``replace`` / ``skip`` for a row.

        ``assign`` and ``replace`` are interchangeable names for "attach the file's
        data": the stored action follows whether the well has data already.
        A row without a target can only be skipped.
        """
        if action not in _ACTIONS:
            raise ValueError(f"Unknown action {action!r}")
        row = self.rows[row_index]
        if row.target_key is None:
            action = "skip"
        elif action in _APPLY:
            action = "replace" if self._ref(row.target_key).existing_count else "assign"
        elif action == "keep" and not self._ref(row.target_key).existing_count:
            action = "assign"
        row.action = action
        row.zone_impact = self._zone_impact(row)
        self._flag_conflicts()

    # ---- internals ----
    def _ref(self, key: Optional[str]) -> Optional[WellRef]:
        return next((w for w in self.wells if w.key == key), None)

    def _display(self, key: str) -> str:
        ref = self._ref(key)
        return ref.display_name if ref else key

    def _settle(self, row: ImportRow, reset_action: bool) -> None:
        """Recompute everything that depends on the row's target."""
        ref = self._ref(row.target_key)
        fac = _factor(self.effective_unit)
        items = _raw_items(row.part)
        row.depth_range = _range(items, fac)
        row.coverage = row.coverage_note = row.unit_fit = None
        row.existing = "none"
        if ref is not None:
            row.existing = _existing_text(ref, self.kind)
            if ref.log_top is not None and ref.log_bottom is not None:
                lo, hi = ref.log_top, ref.log_bottom
                if fac is not None:
                    row.coverage = _coverage(items, fac, lo, hi)
                    span = _range(items, fac)
                    if span:
                        row.coverage_note = depth_coverage_warning(
                            row.file_well, span[0], span[1], lo, hi)
                row.unit_fit = _unit_fit(items, lo, hi)
        if reset_action:
            row.action = _default_action(ref, self.path)
        row.zone_impact = self._zone_impact(row)

    def _zone_impact(self, row: ImportRow) -> List[str]:
        """Notes on parameters and scope entries that lose their zone (tops only)."""
        ref = self._ref(row.target_key)
        if self.kind != "tops" or ref is None or row.action not in _APPLY:
            return []
        new = {normalize_zone(f.name) for f in row.part.formations}
        out: List[str] = []
        lost = [z for z in ref.zones_with_params if normalize_zone(z) not in new]
        if lost:
            out.append(f"zone parameters for {', '.join(lost)} will no longer apply")
        gone = [z for z in ref.selected_formations if normalize_zone(z) not in new]
        out.extend(f"{z} will be removed from the analysis scope" for z in gone)
        return out

    def _flag_conflicts(self) -> None:
        for row in self.rows:
            row.notes = [n for n in row.notes if not n.startswith(_O2O_NOTE)]
        for rows in self._conflicts().values():
            for row in rows:
                others = ", ".join(r.file_well for r in rows if r is not row)
                row.notes.append(f"{_O2O_NOTE}{others}")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _factor(unit: Optional[str]) -> Optional[float]:
    """Multiplier from the file unit to feet (None when the unit is unknown)."""
    return {"M": M_TO_FT, "FT": 1.0}.get(unit)


def _raw_items(part) -> List[Tuple[float, float]]:
    """``(top, bottom)`` of every formation / sample, in the unit as written in the file."""
    if hasattr(part, "formations"):
        return [(f.top_depth, max(f.top_depth, f.bottom_depth)) for f in part.formations]
    if part.data is None or part.depth_col is None:
        return []
    depths = part.data[part.depth_col].to_numpy(dtype=float)
    if getattr(part, "converted_to_feet", False):
        depths = depths / M_TO_FT      # the core reader already converted a detected M
    return [(float(d), float(d)) for d in depths]


def _range(items, factor: Optional[float]) -> Optional[Tuple[float, float]]:
    if not items or factor is None:
        return None
    return (min(t for t, _ in items) * factor, max(b for _, b in items) * factor)


def _coverage(items, factor: float, log_top: float, log_bottom: float) -> Optional[float]:
    """Fraction of the items that overlap the log range under a unit reading."""
    if not items:
        return None
    inside = sum(1 for t, b in items if b * factor >= log_top and t * factor <= log_bottom)
    return inside / len(items)


def _unit_fit(items, log_top: float, log_bottom: float) -> Optional[str]:
    """``"M"`` / ``"FT"`` when exactly one reading of the depths overlaps the log range."""
    cov_m = _coverage(items, M_TO_FT, log_top, log_bottom)
    cov_ft = _coverage(items, 1.0, log_top, log_bottom)
    if cov_m is None or cov_ft is None or bool(cov_m) == bool(cov_ft):
        return None
    return "M" if cov_m else "FT"


def _same_path(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _default_action(ref: Optional[WellRef], path: str) -> str:
    """Decision D5: assign to an empty well; replace data from the same file, else keep."""
    if ref is None:
        return "skip"
    if not ref.existing_count:
        return "assign"
    return "replace" if _same_path(ref.existing_path, path) else "keep"


def _existing_text(ref: WellRef, kind: str) -> str:
    if not ref.existing_count:
        return "none"
    noun = "formations" if kind == "tops" else "samples"
    text = f"{ref.existing_count} {noun}"
    if ref.existing_path:
        text += f" ({os.path.basename(ref.existing_path)})"
    return text


def _well_column(parsed) -> Optional[str]:
    return getattr(parsed, "well_column", None) or getattr(parsed, "well_col", None)


def _probe(name: str, kind: str) -> dict:
    return {"uwi": {"uwi": name}, "api": {"api": name}}.get(kind, {"well_name": name})


def _find_wells(spellings: List[str], kind: str, wells: List[WellRef]):
    """``([matching refs], how)`` for one file well (UWI, then API, then name)."""
    found: List[WellRef] = []
    hows = set()
    for ref in wells:
        for name in spellings:
            verdict, how = same_well(_probe(name, kind), ref.well_info), kind
            if verdict is None and kind != "name":
                verdict, how = same_well(_probe(name, "name"), ref.well_info), "name"
            if verdict is True:
                found.append(ref)
                hows.add(how)
                break
    return found, (hows.pop() if len(hows) == 1 else None)


def _override_for(scales: dict, spellings: List[str], kind: str) -> Optional[str]:
    wanted = {group_key(s, kind) for s in spellings}
    for name, scale in (scales or {}).items():
        if group_key(name, kind) in wanted:
            return scale
    return None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def _parse_once(path: str, options: ImportOptions, fill_down: bool):
    if options.kind == "tops":
        parsed = FormationTops()
        ok = parsed.read_tops_file(path, fill_down=fill_down, sheet=options.sheet,
                                   columns=options.columns)
    elif options.kind == "core":
        from modules.core_handler import CoreDataHandler
        parsed = CoreDataHandler()
        # The depth unit is applied by the plan, so the file is always read as detected.
        ok = parsed.read_core_file(path, fill_down=fill_down, sheet=options.sheet,
                                   porosity_scale=options.porosity_scales or None,
                                   columns=options.columns)
    else:
        raise ValueError(f"Unknown import kind {options.kind!r}")
    if not ok:
        raise ValueError(parsed.last_error or f"Could not read {os.path.basename(path)}")
    return parsed


def parse_import_file(path: str, options: ImportOptions):
    """Read a tops or core file with the options' columns, sheet and porosity scales.

    ``options.fill_down=None`` applies decision D6: blank well cells continue the
    well above only when they look like merged cells (``fill_down_applicable``);
    the value used is left on ``parsed.fill_down``.

    Raises:
        ValueError: the parser's ``last_error`` when the file cannot be read.
    """
    fill_down = options.fill_down
    if fill_down is None:
        first = _parse_once(path, options, False)
        if not first.fill_down_applicable:
            return first
        fill_down = True
    return _parse_once(path, options, bool(fill_down))


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------
def _effective_unit(parsed, options: ImportOptions) -> Optional[str]:
    if options.depth_unit:
        return str(options.depth_unit).upper()
    if getattr(parsed, "depth_unit_detected", False):
        if getattr(parsed, "converted_to_feet", False):
            return "M"      # the core reader already converted a detected M
        return parsed.depth_unit if parsed.depth_unit in ("M", "FT") else None
    return None


def _excluded_by_well(parsed, kind: str) -> Tuple[Dict[str, list], list]:
    """Split ``excluded_rows`` into ``{group key: rows}`` and the rows without a well."""
    by_key: Dict[str, list] = {}
    no_well: list = []
    owners = getattr(parsed, "excluded_row_wells", {})
    for line, reason in parsed.excluded_rows:
        well = owners.get(line, "")
        if well:
            by_key.setdefault(group_key(well, kind), []).append((line, reason))
        else:
            no_well.append((line, reason))
    return by_key, no_well


def _row_notes(row: ImportRow, parsed, kind: str) -> List[str]:
    notes: List[str] = []
    if row.excluded:
        lines = ", ".join(str(l) for l, _ in row.excluded[:3] if l is not None)
        more = "..." if len(row.excluded) > 3 else ""
        notes.append(f"{len(row.excluded)} row(s) excluded (line {lines}{more}): "
                     f"{row.excluded[0][1]}")
    for well, name, line in getattr(parsed, "duplicates", []):
        if group_key(well, kind) == row.group_key:
            notes.append(f"duplicate formation {name} (line {line}); the shallower pick is used")
    return notes


def build_import_plan(parsed, path: str, wells: List[WellRef],
                      options: ImportOptions) -> ImportPlan:
    """Group the file's wells, match them to the loaded wells and decide the defaults.

    Raises:
        ValueError: ``"no well column"`` when the file has no (non-empty) well column.
    """
    if not _well_column(parsed):
        raise ValueError("no well column")
    kind = parsed.well_kind
    plan = ImportPlan(kind=options.kind, path=path, options=options, parsed=parsed,
                      effective_unit=_effective_unit(parsed, options), wells=list(wells))
    by_key, plan.no_well_rows = _excluded_by_well(parsed, kind)
    plan.notes = _plan_notes(parsed, plan)

    for file_well, part in parsed.split_by_well(group=True).items():
        spellings = list(part.spellings) or [file_well]
        row = ImportRow(file_well=file_well, spellings=spellings,
                        group_key=group_key(file_well, kind), part=part)
        row.rows = len(part.formations) if options.kind == "tops" else len(part.data)
        row.excluded = by_key.get(row.group_key, [])
        row.notes = _row_notes(row, parsed, kind)
        if options.kind == "core":
            _apply_porosity_override(row, options, kind)
            row.porosity_scale = part.porosity_scale

        found, how = _find_wells(spellings, kind, plan.wells)
        if len(found) == 1:
            row.status, row.match_how, row.target_key = "matched", how, found[0].key
        elif found:
            row.status, row.candidates = "ambiguous", [w.key for w in found]
        plan._settle(row, reset_action=True)
        plan.rows.append(row)
    plan._flag_conflicts()
    return plan


def _apply_porosity_override(row: ImportRow, options: ImportOptions, kind: str) -> None:
    want = _override_for(options.porosity_scales, row.spellings, kind)
    if want in ("percent", "fraction") and row.part.porosity_scale != want:
        bad = row.part.set_porosity_scale(want)
        if bad:
            row.notes.append(f"{bad} porosity value(s) above 1 excluded after reading "
                             f"the values as {want}")


def _plan_notes(parsed, plan: ImportPlan) -> List[str]:
    notes = list(parsed.notes)
    if getattr(parsed, "swapped_rows", None):
        notes.append(f"{len(parsed.swapped_rows)} row(s) had top and bottom reversed; swapped")
    if parsed.filled_rows:
        notes.append(f"{len(parsed.filled_rows)} blank well cell(s) continue the well above")
    if plan.no_well_rows:
        notes.append(f"{len(plan.no_well_rows)} row(s) without a well (excluded)")
    if plan.kind == "core":
        if parsed.tvd_warning:
            notes.append(parsed.tvd_warning)
        if parsed.porosity_warning:
            notes.append(parsed.porosity_warning)
    return notes


# ---------------------------------------------------------------------------
# Apply helpers
# ---------------------------------------------------------------------------
def _core_depths_to_feet(part, unit: str) -> None:
    """Express a core part's depths in feet under the effective unit."""
    if part.data is not None and part.depth_col:
        was_feet = bool(part.converted_to_feet)  # the reader converted a detected M
        col = part.depth_col
        if unit == "M" and not was_feet:
            part.data[col] = part.data[col] * M_TO_FT
        elif unit == "FT" and was_feet:
            part.data[col] = part.data[col] / M_TO_FT
    part.depth_unit = "FT"
    part.converted_to_feet = True


def _build_part(plan: ImportPlan, row: ImportRow, target: WellRef):
    part = copy.deepcopy(row.part)
    if plan.kind == "tops":
        part.depth_unit, part.converted_to_feet = plan.effective_unit, False
        part.convert_to_feet()
        if plan.options.last_bottom == "log_bottom" and target.log_bottom is not None:
            extend_last_bottom(part, target.log_bottom)
    else:
        _core_depths_to_feet(part, plan.effective_unit)
    return part


def build_parts(plan: ImportPlan, wells: List[WellRef]) -> Dict[str, object]:
    """``{well key: part}`` for every row that assigns or replaces data (pure).

    Each part is a deep copy converted to feet under the effective unit; tops get
    their inferred last bottom extended to the target's log bottom when
    ``options.last_bottom == "log_bottom"``. Nothing is returned if any part fails.

    Raises:
        ValueError: the depth unit is undecided, TVD core depths are unconfirmed, two
            rows target one well, or building a part failed.
    """
    if plan.effective_unit is None:
        raise ValueError("Choose the depth unit (M or FT)")
    if plan.kind == "core" and plan.parsed.depth_is_tvd and not plan.options.tvd_confirmed:
        raise ValueError("Confirm that TVD core depths may be used")
    if plan._conflicts():
        raise ValueError("Two file wells are assigned to the same well")
    refs = {w.key: w for w in wells}
    built: Dict[str, object] = {}
    for row in plan.rows:
        if row.action not in _APPLY or not row.target_key:
            continue
        try:
            built[row.target_key] = _build_part(plan, row, refs[row.target_key])
        except Exception as exc:
            raise ValueError(f"Could not build the data for {row.file_well}: {exc}") from exc
    return built


def import_record(plan: ImportPlan, row: ImportRow) -> dict:
    """Session 2.1 import record of one row (spec §3.10); replays the import exactly."""
    table = plan.parsed.table_read
    record = {
        "path": plan.path,
        "file_well": row.file_well,
        "spellings": list(row.spellings),
        "columns": dict(plan.parsed.columns_detected),
        "delimiter": getattr(table, "delimiter", None),
        "decimal": getattr(table, "decimal", "."),
        "encoding": getattr(table, "encoding", ""),
        "sheet": getattr(table, "sheet", None),
        "depth_unit": plan.effective_unit,
        "fill_down": bool(plan.parsed.fill_down),
        "last_bottom": plan.options.last_bottom,
    }
    if plan.kind == "core":
        record["porosity_scale"] = row.porosity_scale
    return record


# ---------------------------------------------------------------------------
# Snapshot of a Project
# ---------------------------------------------------------------------------
def _log_range(las_data) -> Tuple[Optional[float], Optional[float]]:
    try:
        depth = las_data["DEPTH"].dropna()
        return (float(depth.min()), float(depth.max())) if len(depth) else (None, None)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None, None


def _existing_of(ds, kind: str) -> Tuple[int, Optional[str]]:
    if kind == "tops":
        tops = ds.formation_tops
        return (len(tops.formations) if tops is not None else 0), ds.tops_path
    core = ds.core_data
    data = getattr(core, "data", None)
    return (len(data) if data is not None else 0), ds.core_path


def _zones_with_params(project, ds) -> List[str]:
    zones = []
    for source in (project.zone_params, ds.zone_overrides):
        for zone, entries in (source or {}).items():
            name = normalize_zone(zone)
            if entries and name not in zones:
                zones.append(name)
    return zones


def well_refs(project, kind: str = "tops") -> List[WellRef]:
    """Snapshots of the loaded wells for :func:`build_import_plan`.

    ``kind`` (``"tops"`` or ``"core"``) selects which attached data fills
    ``existing_count`` / ``existing_path``.
    """
    refs = []
    for ds in project.wells:
        top, bottom = _log_range(ds.las_data) if ds.las_data is not None else (None, None)
        count, path = _existing_of(ds, kind)
        refs.append(WellRef(
            key=ds.key, display_name=ds.display_name, well_info=ds.well_info,
            log_top=top, log_bottom=bottom, existing_count=count, existing_path=path,
            zones_with_params=_zones_with_params(project, ds),
            selected_formations=list(ds.selected_formations)))
    return refs
