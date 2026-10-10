"""
Formation Tops Module for Petrophyter
Handles reading and integrating formation top data
"""

import re
import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, replace

from modules.table_reader import read_table
from modules.well_matching import (
    find_well_column, fill_down_wells, group_key, group_well_names,
    merged_cell_pattern_applies,
)

logger = logging.getLogger(__name__)

# Depth-unit tokens for detecting units from column names.
_FEET_TOKENS = {'ft', 'feet', 'foot'}
_METER_TOKENS = {'m', 'meter', 'meters', 'metre', 'metres'}


def _tokenize(text: str) -> List[str]:
    """Split a string into lower-case alphanumeric tokens (drops punctuation)."""
    return [t for t in re.split(r'[^a-z0-9]+', str(text).lower()) if t]


def _is_blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and np.isnan(value):
        return True
    return isinstance(value, str) and not value.strip()


def _cell_text(value) -> str:
    """Text of a well cell ('' when blank; 101.0 from a spreadsheet becomes '101')."""
    if _is_blank(value):
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _resolve_override(columns, df_columns) -> dict:
    """Map an explicit column override onto the columns of a frame.

    ``columns`` is ``{role: header name or None}``; header names match
    case-insensitively after a strip. Returns ``{role: actual column or None}``.

    Raises:
        ValueError: a named header is not in ``df_columns``.
    """
    lookup = {}
    for col in df_columns:
        lookup.setdefault(str(col).strip().lower(), col)
    resolved = {}
    for role, name in (columns or {}).items():
        if name is None or str(name).strip() == '':
            resolved[role] = None
            continue
        col = lookup.get(str(name).strip().lower())
        if col is None:
            raise ValueError(f"Column '{name}' (for {role}) was not found in the file. "
                             f"Columns found: {list(df_columns)}")
        resolved[role] = col
    return resolved


@dataclass
class Formation:
    """Formation data class."""
    name: str
    top_depth: float
    bottom_depth: float
    thickness: float
    anomaly_code: str = ''
    well: str = ''  # well name from the optional well column
    # True when the bottom was not in the file (taken from the next top, or equal
    # to the top for the last formation of a well). See extend_last_bottom().
    bottom_inferred: bool = False


class FormationTops:
    """
    Formation tops manager for integrating stratigraphic data with logs.
    """
    
    # Conversion factor: 1 meter = 3.28084 feet
    M_TO_FT = 3.28084
    
    def __init__(self):
        self.formations: List[Formation] = []
        self.depth_unit = 'M'
        self.depth_unit_detected = False
        self.depth_unit_warning: Optional[str] = None
        self.converted_to_feet = False
        self.last_error: Optional[str] = None
        # Optional well column of a multi-well tops file.
        self.well_column: Optional[str] = None
        self.well_kind: str = 'name'  # what the column holds: name / uwi / api
        # Parse diagnostics (reset by every read).
        self.excluded_rows: List[Tuple[Optional[int], str]] = []  # (file line, reason)
        self.blank_well_rows: List[int] = []   # lines whose well cell was blank (not filled)
        self.filled_rows: List[int] = []       # lines given a well by fill-down
        self.swapped_rows: List[int] = []      # lines whose reversed top/bottom was swapped
        self.duplicates: List[Tuple[str, str, int]] = []  # (well, formation, line)
        self.fill_down: bool = False
        self.fill_down_applicable: bool = False  # blanks look like merged cells
        self.notes: List[str] = []
        self.spellings: List[str] = []  # well spellings of a split part
        self.table_read = None  # TableRead without its frame
        # Columns used, by original header name (None when absent); and the
        # well text of every excluded line ({line: well}, '' without a well).
        self.columns_detected: Dict[str, Optional[str]] = {}
        self.excluded_row_wells: Dict[int, str] = {}
        self._columns_override: Optional[dict] = None
        self._override_error: Optional[str] = None

    def convert_to_feet(self):
        """
        Convert formation depths from meters to feet.

        Only converts when the detected unit is meters. If the unit is feet or
        could not be determined, this is a no-op so a feet-native tops file is
        not wrongly multiplied by 3.28084 (the previous unconditional behavior).
        """
        if self.converted_to_feet:
            return  # Already converted

        if self.depth_unit != 'M':
            # Feet or undetected: nothing to convert. Mark done so a later
            # call cannot convert either.
            self.converted_to_feet = True
            return

        for fm in self.formations:
            fm.top_depth *= self.M_TO_FT
            fm.bottom_depth *= self.M_TO_FT
            fm.thickness *= self.M_TO_FT

        self.depth_unit = 'FT'
        self.converted_to_feet = True
        logger.info("Converted %d formation tops from M to FT", len(self.formations))
        
    def _reset(self):
        """Clear everything a previous file left behind."""
        self.formations = []
        self.depth_unit = 'M'
        self.depth_unit_detected = False
        self.depth_unit_warning = None
        self.converted_to_feet = False
        self.last_error = None
        self.well_column = None
        self.well_kind = 'name'
        self.excluded_rows = []
        self.blank_well_rows = []
        self.filled_rows = []
        self.swapped_rows = []
        self.duplicates = []
        self.fill_down = False
        self.fill_down_applicable = False
        self.notes = []
        self.spellings = []
        self.table_read = None
        self.columns_detected = {}
        self.excluded_row_wells = {}
        self._override_error = None

    def read_tops_file(self, file_path: str, separator: Optional[str] = None, *,
                       fill_down: bool = False, sheet=0,
                       columns: Optional[dict] = None) -> bool:
        """
        Read formation tops from a file (delimited text or .xlsx).

        Expected columns: a formation name, a top and optionally a bottom,
        anomaly code and well. The delimiter (tab, comma, semicolon, pipe),
        encoding, header row and decimal comma are detected; see
        ``modules.table_reader.read_table``.

        Args:
            file_path: Path to the tops file
            separator: preferred delimiter (None = detect)
            fill_down: blank well cells continue the well above
            sheet: sheet index or name for Excel workbooks
            columns: explicit column override ``{well|name|top|bottom: header
                name or None}``; names match case-insensitively, None = no such column

        Returns:
            True if successful
        """
        self._reset()
        self._columns_override = columns
        try:
            table = read_table(file_path, self._columns_found, sheet=sheet, delimiter=separator)
            return self._build_from_table(table, fill_down)
        except Exception as e:
            self.last_error = self._override_error or str(e)
            logger.error("Error reading tops file: %s", e, exc_info=True)
            return False

    def read_tops_from_buffer(self, file_buffer, separator: Optional[str] = None, *,
                              fill_down: bool = False, sheet=0,
                              columns: Optional[dict] = None) -> bool:
        """
        Read formation tops from a file buffer (for Streamlit uploads).

        Args:
            file_buffer: File buffer object
            separator: preferred delimiter (None = detect)
            fill_down: blank well cells continue the well above
            sheet: sheet index or name (Excel bytes only)
            columns: explicit column override (see ``read_tops_file``)

        Returns:
            True if successful
        """
        self._reset()
        self._columns_override = columns
        try:
            table = read_table(file_buffer, self._columns_found, sheet=sheet, delimiter=separator)
            return self._build_from_table(table, fill_down)
        except Exception as e:
            self.last_error = self._override_error or str(e)
            logger.error("Error reading tops: %s", e, exc_info=True)
            return False

    # Column aliases (token matched, in priority order).
    NAME_ALIASES = ['stratigrafical unit', 'stratigraphical unit', 'formation', 'unit',
                    'name', 'fm', 'surface', 'horizon', 'marker', 'pick', 'zone']
    TOP_ALIASES = ['top (m)', 'top (ft)', 'top', 'top_md', 'top_depth']
    TOP_FALLBACK_ALIASES = ['top md', 'md', 'depth']  # only when no explicit top column
    BOTTOM_ALIASES = ['bottom (m)', 'bottom (ft)', 'bottom', 'bottom_md', 'bottom_depth']
    ANOMALY_ALIASES = ['anomaly code', 'anomaly', 'code', 'remarks']

    def _detect_columns(self, df: pd.DataFrame) -> dict:
        ov = _resolve_override(self._columns_override, df.columns)
        if 'well' in ov:
            well_col = ov['well']
            well_kind = 'name'
            if well_col is not None:
                found, kind = find_well_column(df[[well_col]], self._find_column)
                well_kind = kind if found is not None else 'name'
        else:
            well_col, well_kind = find_well_column(df, self._find_column)
        # A 'well_name' column must not be mistaken for the formation name.
        name_df = df.drop(columns=[well_col]) if well_col else df
        name_col = (ov['name'] if 'name' in ov
                    else self._find_column(name_df, self.NAME_ALIASES))
        top_col = (ov['top'] if 'top' in ov
                   else self._find_column(df, self.TOP_ALIASES))
        bottom_col = (ov['bottom'] if 'bottom' in ov
                      else self._find_column(df, self.BOTTOM_ALIASES))
        if top_col is None and 'top' not in ov:
            skip = [c for c in (bottom_col, name_col, well_col) if c is not None]
            top_col = self._find_column(df.drop(columns=skip), self.TOP_FALLBACK_ALIASES)
        anomaly_col = self._find_column(df, self.ANOMALY_ALIASES)
        return {'well': well_col, 'well_kind': well_kind, 'name': name_col, 'top': top_col,
                'bottom': bottom_col, 'anomaly': anomaly_col}

    def _columns_found(self, df: pd.DataFrame) -> bool:
        try:
            cols = self._detect_columns(df)
        except ValueError as e:
            self._override_error = str(e)
            return False
        return cols['name'] is not None and cols['top'] is not None

    def _build_from_dataframe(self, df: pd.DataFrame) -> bool:
        """Build from an already parsed DataFrame (rows numbered 2.. as in a file)."""
        from modules.table_reader import TableRead
        table = TableRead(frame=df, line_numbers=list(range(2, len(df) + 2)))
        self._reset()
        return self._build_from_table(table, False)

    def _build_from_table(self, table, fill_down: bool = False) -> bool:
        """
        Build the formation list from a ``TableRead``.

        Handles column detection, depth-unit detection, top>bottom swaps,
        missing bottom (defaulted to the next formation's top, marked
        ``bottom_inferred``), sorting, and counts every excluded row.
        """
        # A FormationTops instance can be reused. Clear prior parsed data and
        # unit provenance before rebuilding so a previous conversion/warning
        # cannot suppress conversion or leak into the next file.
        self._reset()
        self.table_read = replace(table, frame=None)
        self.notes = list(table.notes)

        df = table.frame.copy()
        lines = list(table.line_numbers) or list(range(2, len(df) + 2))
        original = {}
        for col in df.columns:
            original.setdefault(str(col).strip().lower(), col)
        # Normalize column names
        df.columns = df.columns.str.strip().str.lower()

        try:
            cols = self._detect_columns(df)
        except ValueError as e:
            self.last_error = str(e)
            return False
        well_col, well_kind = cols['well'], cols['well_kind']
        name_col, top_col = cols['name'], cols['top']
        bottom_col, anomaly_col = cols['bottom'], cols['anomaly']

        if name_col is None or top_col is None:
            self.last_error = ("Could not find required columns (name, top). "
                               f"Columns found: {list(df.columns)}")
            logger.warning(self.last_error)
            return False

        # Detect the depth unit from the top/bottom column names (or a unit row).
        self._detect_depth_unit(top_col, bottom_col, table.unit_row_unit)

        top_num = pd.to_numeric(df[top_col], errors='coerce')
        bottom_num = pd.to_numeric(df[bottom_col], errors='coerce') if bottom_col else None

        # Well column: strip, optionally fill blanks down, count what is left.
        wells_txt: List[str] = []
        if well_col:
            wells_txt = [_cell_text(v) for v in df[well_col]]
            if not any(wells_txt):
                self.notes.append(f"Well column '{well_col}' is empty; it was ignored.")
                well_col, well_kind = None, 'name'
                wells_txt = []
        if well_col:
            self.fill_down_applicable = merged_cell_pattern_applies(
                wells_txt, top_num.tolist())
            self.fill_down = bool(fill_down)
            if fill_down:
                filled = fill_down_wells(wells_txt)
                self.filled_rows = [lines[i] for i, w in enumerate(wells_txt)
                                    if not w and filled[i]]
                wells_txt = [f or '' for f in filled]
        self.well_column, self.well_kind = well_col, well_kind
        self.columns_detected = {
            role: (original.get(col) if col else None)
            for role, col in (('well', well_col), ('name', name_col),
                              ('top', top_col), ('bottom', bottom_col))}

        # Build raw records first (name, top, bottom-or-None, anomaly).
        records = []
        bad_bottoms = 0
        for i in range(len(df)):
            line = lines[i]
            top = top_num.iloc[i]
            if pd.isna(top):
                raw = df[top_col].iloc[i]
                if _is_blank(raw):
                    reason = "missing top depth"
                else:
                    reason = f"non-numeric top depth {str(raw)!r}"
                self.excluded_rows.append((line, reason))
                self.excluded_row_wells[line] = wells_txt[i] if well_col else ''
                continue
            well = wells_txt[i] if well_col else ''
            if well_col and not well:
                self.blank_well_rows.append(line)
                self.excluded_rows.append((line, "no well (blank well cell)"))
                continue
            name = '' if _is_blank(df[name_col].iloc[i]) else str(df[name_col].iloc[i]).strip()
            if not name:
                self.excluded_rows.append((line, "missing formation name"))
                self.excluded_row_wells[line] = well
                continue
            top = float(top)

            bottom = None
            if bottom_col:
                b = bottom_num.iloc[i]
                if pd.notna(b):
                    bottom = float(b)
                elif not _is_blank(df[bottom_col].iloc[i]):
                    bad_bottoms += 1

            # Repair reversed top/bottom (a common manual data-entry error)
            # instead of hiding it behind abs().
            if bottom is not None and bottom < top:
                logger.warning("Formation '%s' has bottom < top; swapping.", name)
                top, bottom = bottom, top
                self.swapped_rows.append(line)

            anomaly_raw = df[anomaly_col].iloc[i] if anomaly_col else None
            anomaly = '' if _is_blank(anomaly_raw) else str(anomaly_raw).strip()
            records.append({'name': name, 'top': top, 'bottom': bottom,
                            'anomaly': anomaly, 'well': well, 'line': line,
                            'wkey': group_key(well, well_kind) if well else ''})
        if bad_bottoms:
            self.notes.append(
                f"{bad_bottoms} non-numeric bottom depth(s); taken from the next top instead.")

        # Sort by top depth so missing bottoms can be filled from the next top.
        records.sort(key=lambda r: r['top'])

        # Fill missing bottom depths with the next formation's top depth so a
        # formation without an explicit bottom column is not collapsed to zero
        # thickness (which broke every depth-range query).
        for i, rec in enumerate(records):
            rec['inferred'] = rec['bottom'] is None
            if rec['bottom'] is None:
                # The next top of the same well (all rows share one without a well column).
                nxt = next((r for r in records[i + 1:] if r['wkey'] == rec['wkey']), None)
                if nxt is not None:
                    rec['bottom'] = nxt['top']
                else:
                    rec['bottom'] = rec['top']  # last formation: no next top known

        self.formations = []
        seen_names = set()
        for rec in records:
            seen_key = (rec['wkey'], rec['name'].lower())
            if seen_key in seen_names:
                logger.warning("Duplicate formation name '%s'; queries return the first.", rec['name'])
                self.duplicates.append((rec['well'], rec['name'], rec['line']))
            seen_names.add(seen_key)
            thickness = max(0.0, rec['bottom'] - rec['top'])
            self.formations.append(Formation(
                name=rec['name'],
                top_depth=rec['top'],
                bottom_depth=rec['bottom'],
                thickness=thickness,
                anomaly_code=rec['anomaly'],
                well=rec['well'],
                bottom_inferred=rec['inferred'],
            ))

        return True

    # ------------------------------------------------------------------
    # Multi-well files
    # ------------------------------------------------------------------
    def well_names(self) -> List[str]:
        """Well names in the file's well column, ordered by each well's shallowest top.

        Empty when the file has no well column.
        """
        if not self.well_column:
            return []
        names: List[str] = []
        for fm in self.formations:
            if fm.well and fm.well not in names:
                names.append(fm.well)
        return names

    def _new_part(self) -> 'FormationTops':
        part = FormationTops()
        part.depth_unit = self.depth_unit
        part.depth_unit_detected = self.depth_unit_detected
        part.depth_unit_warning = self.depth_unit_warning
        part.converted_to_feet = self.converted_to_feet
        part.well_column = self.well_column
        part.well_kind = self.well_kind
        part.table_read = self.table_read
        part.columns_detected = dict(self.columns_detected)
        return part

    def split_by_well(self, group: bool = False) -> Dict[str, 'FormationTops']:
        """One FormationTops per well (same depth-unit state, that well's formations).

        With ``group=False`` the parts are keyed by the raw well string. With
        ``group=True`` spellings of one well ("BKS-01", "BKS 01", "bks_01") are
        merged into one part (re-sorted by top); it is keyed by the first
        spelling seen and ``part.spellings`` lists all of them.
        """
        parts: Dict[str, FormationTops] = {}
        if not group:
            for name in self.well_names():
                part = self._new_part()
                part.formations = [replace(fm) for fm in self.formations if fm.well == name]
                part.spellings = [name]
                parts[name] = part
            return parts
        for _key, spellings in group_well_names(self.well_names(), self.well_kind).items():
            part = self._new_part()
            wanted = set(spellings)
            part.formations = sorted((replace(fm) for fm in self.formations if fm.well in wanted),
                                     key=lambda f: f.top_depth)
            part.spellings = list(spellings)
            parts[spellings[0]] = part
        return parts

    def _detect_depth_unit(self, top_col: str, bottom_col: Optional[str],
                           unit_row_unit: Optional[str] = None):
        """Detect the depth unit from top/bottom column names, then a unit row."""
        tokens = set(_tokenize(top_col))
        if bottom_col:
            tokens |= set(_tokenize(bottom_col))

        if tokens & _FEET_TOKENS:
            self.depth_unit = 'FT'
            self.depth_unit_detected = True
        elif tokens & _METER_TOKENS:
            self.depth_unit = 'M'
            self.depth_unit_detected = True
        elif unit_row_unit in ('FT', 'M'):
            self.depth_unit = unit_row_unit
            self.depth_unit_detected = True
        else:
            # Unknown: assume feet (the app's working unit) and do not convert.
            # Warn rather than silently multiplying a possibly-feet file.
            self.depth_unit = 'FT'
            self.depth_unit_detected = False
            self.depth_unit_warning = (
                "Formation tops depth unit could not be determined from the "
                "column names; depths were left unchanged (assumed feet). "
                "Verify units if tops do not align with the logs."
            )
            logger.warning(self.depth_unit_warning)

    def _find_column(self, df: pd.DataFrame, aliases: List[str]) -> Optional[str]:
        """
        Find a column by alias list using whole-token matching.

        Token matching (vs. plain substring) avoids false positives and lets the
        unit-bearing aliases 'top (m)' and 'top (ft)' be distinguished.
        """
        col_tokens = {col: set(_tokenize(col)) for col in df.columns}
        for alias in aliases:
            alias_tokens = _tokenize(alias)
            if not alias_tokens:
                continue
            for col in df.columns:
                if all(tok in col_tokens[col] for tok in alias_tokens):
                    return col
        return None
    
    def get_formation_at_depth(self, depth: float) -> Optional[Formation]:
        """
        Get the formation at a specific depth.
        
        Args:
            depth: Depth value
            
        Returns:
            Formation object or None
        """
        # Half-open interval [top, bottom) so a depth exactly on a shared
        # boundary (bottom of A == top of B) resolves to a single formation (B),
        # not both. The deepest formation keeps its bottom inclusive so the very
        # last depth still matches.
        for i, fm in enumerate(self.formations):
            is_last = i == len(self.formations) - 1
            if is_last:
                if fm.top_depth <= depth <= fm.bottom_depth:
                    return fm
            elif fm.top_depth <= depth < fm.bottom_depth:
                return fm
        return None
    
    def get_formation_name_at_depth(self, depth: float) -> str:
        """
        Get the formation name at a specific depth.
        
        Args:
            depth: Depth value
            
        Returns:
            Formation name or empty string
        """
        fm = self.get_formation_at_depth(depth)
        return fm.name if fm else ''
    
    def add_formation_column(self, data: pd.DataFrame, 
                             depth_col: str = 'DEPTH') -> pd.DataFrame:
        """
        Add a formation name column to log data.
        
        Args:
            data: Log data DataFrame
            depth_col: Depth column name
            
        Returns:
            DataFrame with added FORMATION column
        """
        if depth_col not in data.columns:
            return data
        
        fm_names = []
        for depth in data[depth_col]:
            fm_names.append(self.get_formation_name_at_depth(depth))
        
        data = data.copy()
        data['FORMATION'] = fm_names
        return data
    
    def get_depth_range_for_formation(self, formation_name: str) -> Optional[Tuple[float, float]]:
        """
        Get depth range for a specific formation.
        
        Args:
            formation_name: Formation name
            
        Returns:
            Tuple of (top, bottom) or None
        """
        for fm in self.formations:
            if fm.name.lower() == formation_name.lower():
                return (fm.top_depth, fm.bottom_depth)
        return None
    
    def get_formations_in_range(self, top_depth: float, 
                                 bottom_depth: float) -> List[Formation]:
        """
        Get all formations within a depth range.
        
        Args:
            top_depth: Top of range
            bottom_depth: Bottom of range
            
        Returns:
            List of Formation objects
        """
        formations = []
        for i, fm in enumerate(self.formations):
            # Match the lookup/filter interval convention: a non-deepest
            # formation is [top, bottom), while the deepest formation includes
            # its final bottom. This avoids returning both formations for a
            # zero-width query exactly on a shared boundary.
            is_last = i == len(self.formations) - 1
            if is_last:
                overlaps = fm.bottom_depth >= top_depth and fm.top_depth <= bottom_depth
            else:
                overlaps = fm.bottom_depth > top_depth and fm.top_depth < bottom_depth
            if overlaps:
                formations.append(fm)
        return formations
    
    def get_formation_list(self) -> List[str]:
        """Get list of all formation names."""
        return [fm.name for fm in self.formations]
    
    def to_dataframe(self) -> pd.DataFrame:
        """Convert formations to DataFrame."""
        unit = self.depth_unit.lower()
        data = []
        for fm in self.formations:
            data.append({
                'Formation': fm.name,
                f'Top ({unit})': fm.top_depth,
                f'Bottom ({unit})': fm.bottom_depth,
                f'Thickness ({unit})': fm.thickness,
                'Anomaly': fm.anomaly_code
            })
        return pd.DataFrame(data)
    
    def filter_by_formations(self, data: pd.DataFrame,
                             formation_names: List[str],
                             depth_col: str = 'DEPTH') -> pd.DataFrame:
        """
        Filter log data to only include specified formations.
        
        Args:
            data: Log data DataFrame
            formation_names: List of formation names to include
            depth_col: Depth column name
            
        Returns:
            Filtered DataFrame
        """
        if depth_col not in data.columns:
            return data
        
        masks = []
        for fm_name in formation_names:
            formation = next(
                (fm for fm in self.formations
                 if fm.name.lower() == fm_name.lower()),
                None,
            )
            if formation is None:
                continue

            # Keep filtering consistent with get_formation_at_depth: intervals
            # are half-open except for the deepest formation, whose bottom is
            # inclusive so the final well sample remains selectable.
            is_last = bool(self.formations) and formation is self.formations[-1]
            lower = data[depth_col] >= formation.top_depth
            upper = (
                data[depth_col] <= formation.bottom_depth
                if is_last
                else data[depth_col] < formation.bottom_depth
            )
            masks.append(lower & upper)
        
        if not masks:
            return data
        
        combined_mask = masks[0]
        for mask in masks[1:]:
            combined_mask = combined_mask | mask
        
        return data[combined_mask].copy()


def extend_last_bottom(tops, log_bottom: float) -> int:
    """Extend the last formation of each well to ``log_bottom`` when its bottom was inferred.

    Only the deepest formation of a well whose ``bottom_inferred`` flag is set is
    touched, and only when ``log_bottom`` is deeper than its current bottom.
    ``tops`` is a ``FormationTops`` (or a list of ``Formation``); depths and
    ``log_bottom`` must be in the same unit. Formations are modified in place.

    Returns:
        The number of formations extended.
    """
    try:
        log_bottom = float(log_bottom)
    except (TypeError, ValueError):
        return 0
    if np.isnan(log_bottom):
        return 0
    formations = tops.formations if hasattr(tops, 'formations') else list(tops)
    last: Dict[str, Formation] = {}
    for fm in formations:
        key = group_key(fm.well) if fm.well else ''
        cur = last.get(key)
        if cur is None or fm.top_depth >= cur.top_depth:
            last[key] = fm
    extended = 0
    for fm in last.values():
        if fm.bottom_inferred and log_bottom > fm.bottom_depth:
            fm.bottom_depth = log_bottom
            fm.thickness = max(0.0, log_bottom - fm.top_depth)
            extended += 1
    return extended


def load_tops_file(file_path: str) -> Optional[FormationTops]:
    """
    Convenience function to load a formation tops file.
    
    Args:
        file_path: Path to the tops file
        
    Returns:
        FormationTops object or None
    """
    tops = FormationTops()
    if tops.read_tops_file(file_path):
        return tops
    return None
