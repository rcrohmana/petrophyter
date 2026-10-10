"""
Core Data Handler Module for Petrophyter
Handles loading and validation of core data against log-derived petrophysical properties.
"""

import copy
import re
import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from scipy import stats
from scipy.interpolate import interp1d

from dataclasses import replace

from modules.table_reader import read_table
from modules.well_matching import (
    find_well_column, fill_down_wells, group_key, group_well_names,
    merged_cell_pattern_applies,
)

logger = logging.getLogger(__name__)


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

# Depth-unit tokens.
_FEET_TOKENS = {'ft', 'feet', 'foot'}
_METER_TOKENS = {'m', 'meter', 'meters', 'metre', 'metres'}


def _tokenize(text: str) -> List[str]:
    """Split a string into lower-case alphanumeric tokens (drops punctuation)."""
    return [t for t in re.split(r'[^a-z0-9]+', text.lower()) if t]


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


@dataclass
class CoreValidationResult:
    """Container for validation metrics between core and log data."""
    n_points: int
    bias: float  # Mean error (log - core)
    mae: float   # Mean absolute error
    rmse: float  # Root mean square error
    r_squared: Optional[float]  # Coefficient of determination
    spearman_rho: float  # Spearman correlation (robust to non-linear)
    spearman_pvalue: float


@dataclass  
class PermValidationResult:
    """Container for permeability validation metrics (linear and log domain)."""
    # Linear domain
    n_points: int
    bias_linear: float
    mae_linear: float
    rmse_linear: float
    r_squared_linear: Optional[float]
    spearman_rho: float
    spearman_pvalue: float
    # Log10 domain (for valid perm > 0)
    n_valid_log: int
    mae_log10: float
    rmse_log10: float


class CoreDataHandler:
    """
    Core data handler for loading and validating core measurements.
    
    Supports loading core data from TXT/CSV files with flexible column detection.
    Provides depth interpolation and validation metrics calculation.
    """
    
    # Column aliases for robust detection
    DEPTH_ALIASES = ['depth', 'depth (m)', 'depth(m)', 'depth_m', 'md', 'tvd', 'depth_md', 'tvdss']
    POROSITY_ALIASES = ['porosity', 'porosity (%)', 'porosity(%)', 'por', 'phi', 'core_por', 'core porosity']
    PERM_ALIASES = ['hor.perm', 'hor.perm. (md)', 'perm', 'permeability', 'k', 'kh', 'khor', 
                   'horizontal perm', 'hor perm', 'perm (md)', 'permeability (md)']
    GRAIN_DENSITY_ALIASES = ['grain density', 'grain density (g/cm³)', 'grain_density', 
                             'rhog', 'rho_grain', 'matrix density']
    NUMBER_ALIASES = ['number', 'no', 'sample', 'sample_no', 'id', 'sample id']
    
    # Conversion constants
    M_TO_FT = 3.28084
    
    def __init__(self):
        self.data: Optional[pd.DataFrame] = None
        self.depth_col: Optional[str] = None
        self.porosity_col: Optional[str] = None
        self.perm_col: Optional[str] = None
        self.grain_density_col: Optional[str] = None
        self.depth_unit: str = 'M'  # Will be converted to FT to match log data
        self.depth_unit_detected: bool = False
        self.depth_unit_warning: Optional[str] = None
        self.porosity_unit: str = 'fraction'  # After conversion
        self.converted_to_feet: bool = False
        self.porosity_converted: bool = False
        # Optional well column of a multi-well core file.
        self.well_col: Optional[str] = None
        self.well_kind: str = 'name'  # what the column holds: name / uwi / api
        # Parse diagnostics (reset by every read).
        self.last_error: Optional[str] = None
        self.excluded_rows: List[Tuple[Optional[int], str]] = []  # (file line, reason)
        self.blank_well_rows: List[int] = []   # lines whose well cell was blank (not filled)
        self.filled_rows: List[int] = []       # lines given a well by fill-down
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
        self.depth_is_tvd: bool = False
        self.tvd_warning: Optional[str] = None
        # Porosity scale: 'percent' / 'fraction' (None when wells disagree).
        self.porosity_scale: Optional[str] = None
        self.porosity_scales: Dict[str, str] = {}  # first spelling of each well -> scale
        self.porosity_scale_mixed: bool = False
        self.porosity_warning: Optional[str] = None
        self._scales_by_group: Dict[str, str] = {}
        self._por_raw: Optional[np.ndarray] = None  # porosity as read, aligned with data

    def _reset(self):
        """Clear everything a previous file left behind."""
        self.data = None
        self.depth_col = None
        self.porosity_col = None
        self.perm_col = None
        self.grain_density_col = None
        self.depth_unit = 'M'
        self.depth_unit_detected = False
        self.depth_unit_warning = None
        self.converted_to_feet = False
        self.porosity_converted = False
        self.well_col = None
        self.well_kind = 'name'
        self.last_error = None
        self.excluded_rows = []
        self.blank_well_rows = []
        self.filled_rows = []
        self.fill_down = False
        self.fill_down_applicable = False
        self.notes = []
        self.spellings = []
        self.table_read = None
        self.columns_detected = {}
        self.excluded_row_wells = {}
        self._override_error = None
        self.depth_is_tvd = False
        self.tvd_warning = None
        self.porosity_scale = None
        self.porosity_scales = {}
        self.porosity_scale_mixed = False
        self.porosity_warning = None
        self._scales_by_group = {}
        self._por_raw = None

    def _detect_columns(self, df: pd.DataFrame) -> dict:
        """Resolve the columns of ``df``: detected by alias, overridden by ``columns``."""
        ov = _resolve_override(self._columns_override, df.columns)

        def pick(role, aliases):
            return ov[role] if role in ov else self._find_column(df, aliases)

        cols = {'depth': pick('depth', self.DEPTH_ALIASES),
                'porosity': pick('porosity', self.POROSITY_ALIASES),
                'permeability': pick('permeability', self.PERM_ALIASES),
                'grain_density': pick('grain_density', self.GRAIN_DENSITY_ALIASES)}
        if 'well' in ov:
            well_col, well_kind = ov['well'], 'name'
            if well_col is not None:
                found, kind = find_well_column(df[[well_col]], self._find_column)
                well_kind = kind if found is not None else 'name'
        else:
            well_col, well_kind = find_well_column(df, self._find_column)
        if well_col in (cols['depth'], cols['porosity'], cols['permeability'],
                        cols['grain_density']):
            well_col, well_kind = None, 'name'
        cols['well'], cols['well_kind'] = well_col, well_kind
        return cols

    def _columns_found(self, df: pd.DataFrame) -> bool:
        """Predicate for ``read_table``: a depth column and a porosity or perm column."""
        try:
            cols = self._detect_columns(df)
        except ValueError as e:
            self._override_error = str(e)
            return False
        return (cols['depth'] is not None
                and (cols['porosity'] is not None or cols['permeability'] is not None))

    def read_core_from_buffer(self, file_buffer, separator: Optional[str] = None,
                              depth_unit: str = 'Auto', *, fill_down: bool = False,
                              porosity_scale=None, sheet=0,
                              columns: Optional[dict] = None) -> bool:
        """
        Read core data from a file buffer (for Streamlit uploads).

        Args:
            file_buffer: File buffer object
            separator: preferred delimiter (None = detect: tab, comma, ; or |)
            depth_unit: Depth unit: 'Auto', 'M', or 'FT'
            fill_down: blank well cells continue the well above
            porosity_scale: None (decide per well: max > 1 means percent),
                'percent' / 'fraction' for every well, or ``{well: scale}``
            sheet: sheet index or name (Excel bytes only)
            columns: explicit column override ``{well|depth|porosity|permeability|
                grain_density: header name or None}``; names match case-insensitively,
                None = no such column

        Returns:
            True if successful, False otherwise
        """
        return self._read(file_buffer, separator, depth_unit, fill_down, porosity_scale,
                          sheet, columns)

    def read_core_file(self, file_path: str, separator: Optional[str] = None,
                       depth_unit: str = 'Auto', *, fill_down: bool = False,
                       porosity_scale=None, sheet=0,
                       columns: Optional[dict] = None) -> bool:
        """
        Read core data from a file path (delimited text, UTF-8 or CP1252, or .xlsx).

        Args:
            file_path: Path to the core data file
            separator: preferred delimiter (None = detect)
            columns: explicit column override (see ``read_core_from_buffer``)

        Returns:
            True if successful
        """
        return self._read(file_path, separator, depth_unit, fill_down, porosity_scale,
                          sheet, columns)

    def _read(self, source, separator, depth_unit, fill_down, porosity_scale, sheet,
              columns=None) -> bool:
        # A handler instance may be reused for another file. Reset all
        # per-load metadata so a prior M conversion or warning cannot suppress
        # or contaminate the next load.
        self._reset()
        self._columns_override = columns
        try:
            table = read_table(source, self._columns_found, sheet=sheet, delimiter=separator)
            return self._build_from_table(table, depth_unit, fill_down, porosity_scale)
        except Exception as e:
            self.last_error = self._override_error or str(e)
            logger.error("Error reading core data: %s", e)
            return False

    def _build_from_table(self, table, depth_unit: str, fill_down: bool,
                          porosity_scale) -> bool:
        self.table_read = replace(table, frame=None)
        self.notes = list(table.notes)
        df = table.frame.copy()
        lines = list(table.line_numbers) or list(range(2, len(df) + 2))

        if df.empty:
            self.last_error = "Empty core file"
            logger.warning("Empty core file")
            return False

        original = {}
        for col in df.columns:
            original.setdefault(str(col).strip().lower(), col)
        # Normalize column names for matching
        df.columns = df.columns.str.strip().str.lower()

        try:
            cols = self._detect_columns(df)
        except ValueError as e:
            self.last_error = str(e)
            return False

        # Find required depth column
        self.depth_col = cols['depth']
        if self.depth_col is None:
            self.last_error = f"Could not find depth column. Columns found: {list(df.columns)}"
            logger.warning("Could not find depth column")
            return False

        # Find optional columns
        self.porosity_col = cols['porosity']
        self.perm_col = cols['permeability']
        self.grain_density_col = cols['grain_density']
        self.well_col, self.well_kind = cols['well'], cols['well_kind']

        # Validate that we have at least one property to validate
        if self.porosity_col is None and self.perm_col is None:
            self.last_error = ("No porosity or permeability column found. "
                               f"Columns found: {list(df.columns)}")
            logger.warning("No porosity or permeability column found")
            return False

        # A depth column that is TVD does not match MD logs.
        if set(_tokenize(self.depth_col)) & {'tvd', 'tvdss'}:
            self.depth_is_tvd = True
            self.tvd_warning = (
                f"Core depths look like TVD (column '{self.depth_col}'); logs are on MD. "
                "Import only if the well is vertical or the logs are on TVD."
            )
            logger.warning(self.tvd_warning)

        depth_num = pd.to_numeric(df[self.depth_col], errors='coerce')

        # Well column: strip, optionally fill blanks down, count what is left.
        wells_txt: List[str] = []
        if self.well_col:
            wells_txt = [_cell_text(v) for v in df[self.well_col]]
            if not any(wells_txt):
                self.notes.append(f"Well column '{self.well_col}' is empty; it was ignored.")
                self.well_col, self.well_kind = None, 'name'
                wells_txt = []
        self.columns_detected = {
            role: (original.get(col) if col else None)
            for role, col in (('well', self.well_col), ('depth', self.depth_col),
                              ('porosity', self.porosity_col),
                              ('permeability', self.perm_col),
                              ('grain_density', self.grain_density_col))}
        if self.well_col:
            self.fill_down_applicable = merged_cell_pattern_applies(
                wells_txt, depth_num.tolist())
            self.fill_down = bool(fill_down)
            if fill_down:
                filled = fill_down_wells(wells_txt)
                self.filled_rows = [lines[i] for i, w in enumerate(wells_txt)
                                    if not w and filled[i]]
                wells_txt = [f or '' for f in filled]

        keep = []
        for i in range(len(df)):
            if pd.isna(depth_num.iloc[i]):
                raw = df[self.depth_col].iloc[i]
                reason = ("missing depth" if _is_blank(raw)
                          else f"non-numeric depth {str(raw)!r}")
                self.excluded_rows.append((lines[i], reason))
                self.excluded_row_wells[lines[i]] = wells_txt[i] if self.well_col else ''
            elif self.well_col and not wells_txt[i]:
                self.blank_well_rows.append(lines[i])
                self.excluded_rows.append((lines[i], "no well (blank well cell)"))
            else:
                keep.append(i)

        if not keep:
            self.last_error = "No valid core data after cleaning"
            logger.warning("No valid core data after cleaning")
            return False

        df[self.depth_col] = depth_num
        if self.well_col:
            df[self.well_col] = wells_txt
        # Convert numeric columns
        for col in (self.porosity_col, self.perm_col, self.grain_density_col):
            if col:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        df['__line__'] = lines
        df = df.iloc[keep]

        if self.porosity_col:
            df = self._convert_porosity(df, porosity_scale)

        # Sort by depth
        df = df.sort_values(self.depth_col).reset_index(drop=True)
        self._row_lines = df.pop('__line__').tolist()
        if self.porosity_col:
            self._por_raw = df.pop('__por_raw__').to_numpy(dtype=float)

        self.data = df

        # Record original unit
        if depth_unit != 'Auto':
            self.depth_unit = depth_unit.upper()
            self.depth_unit_detected = True
        else:
            # Detect from the depth column name via whole-token matching.
            col_tokens = set(_tokenize(self.depth_col))
            if col_tokens & _FEET_TOKENS:
                self.depth_unit = 'FT'
                self.depth_unit_detected = True
            elif col_tokens & _METER_TOKENS:
                self.depth_unit = 'M'
                self.depth_unit_detected = True
            elif table.unit_row_unit in ('FT', 'M'):
                self.depth_unit = table.unit_row_unit
                self.depth_unit_detected = True
            else:
                # Unit unknown: do NOT silently assume meters and triple the
                # depth of a feet-native file. Treat as feet (no conversion)
                # and warn so the UI can prompt the user to confirm.
                self.depth_unit = 'FT'
                self.depth_unit_detected = False
                self.depth_unit_warning = (
                    "Core depth unit could not be determined from the column "
                    f"name '{self.depth_col}'; depths were left unchanged "
                    "(assumed feet). Set the depth unit manually if this is wrong."
                )
                logger.warning(self.depth_unit_warning)

        # Auto convert to feet only when the unit is positively meters.
        if self.depth_unit == 'M':
            self.convert_depth_to_feet()

        return True
    
    def _find_column(self, df: pd.DataFrame, aliases: List[str]) -> Optional[str]:
        """
        Find a column by alias list using whole-token matching.

        Substring matching (the previous approach) let short aliases like 'k'
        (permeability) match unrelated columns such as 'Remarks', and 'por'
        match 'Report_ID'. Token matching requires each alias token to appear as
        a complete token in the column name, eliminating those false positives.
        """
        col_tokens = {col: set(_tokenize(str(col))) for col in df.columns}
        for alias in aliases:
            alias_tokens = _tokenize(alias)
            if not alias_tokens:
                continue
            for col in df.columns:
                if all(tok in col_tokens[col] for tok in alias_tokens):
                    return col
        return None
    
    def _group_keys(self, df: pd.DataFrame) -> np.ndarray:
        """Per-row well identity key ('' for a file without a well column)."""
        if not self.well_col or self.well_col not in df.columns:
            return np.full(len(df), '', dtype=object)
        return np.array([group_key(w, self.well_kind) for w in df[self.well_col]], dtype=object)

    def _convert_porosity(self, df: pd.DataFrame, requested) -> pd.DataFrame:
        """Decide percent vs fraction per well and convert (whole file without a well column).

        Values above 1 after conversion (e.g. above 100 %) are invalid: they are set to NaN
        and listed in ``excluded_rows``. ``requested`` may force the scale
        (``'percent'`` / ``'fraction'`` for all wells, or ``{well: scale}``).
        """
        col = self.porosity_col
        raw = df[col].to_numpy(dtype=float)
        keys = self._group_keys(df)
        line_of = df['__line__'].to_numpy()
        well_of = (df[self.well_col].to_numpy() if self.well_col and self.well_col in df.columns
                   else np.full(len(df), '', dtype=object))
        forced: Dict[str, str] = {}
        if isinstance(requested, dict):
            forced = {group_key(k, self.well_kind): v for k, v in requested.items()}
        elif requested in ('percent', 'fraction'):
            forced = {k: requested for k in set(keys)}

        scales: Dict[str, str] = {}
        converted = raw.copy()
        for key in dict.fromkeys(keys):
            mask = keys == key
            finite = raw[mask][np.isfinite(raw[mask])]
            pmax = float(finite.max()) if len(finite) else 0.0
            # The median decides, so one typo ("25" among fractions) is flagged
            # as out of range instead of dividing the whole well by 100.
            median = float(np.median(finite)) if len(finite) else 0.0
            scale = forced.get(key) or ('percent' if median > 1.0 else 'fraction')
            scales[key] = scale
            if pmax > 100.0:
                logger.warning(
                    "Core porosity max is %.1f (> 100); data may be corrupt; "
                    "values above 100 %% are excluded.", pmax)
            if scale == 'percent':
                converted[mask] = raw[mask] / 100.0
                logger.info("Converted porosity from %% to fraction (max was %.1f%%)", pmax)
        bad = np.isfinite(converted) & (converted > 1.0)
        for i in np.flatnonzero(bad):
            shown = raw[i]
            self.excluded_rows.append(
                (int(line_of[i]), f"porosity {shown:g} out of range (value excluded)"))
            self.excluded_row_wells[int(line_of[i])] = str(well_of[i])
        converted[bad] = np.nan

        df = df.copy()
        df['__por_raw__'] = raw
        df[col] = converted
        self._scales_by_group = scales
        self._publish_scales(df)
        return df

    def _publish_scales(self, df: Optional[pd.DataFrame] = None):
        """Derive the public scale attributes from ``_scales_by_group``."""
        data = df if df is not None else self.data
        labels: Dict[str, str] = {}
        if self.well_col and data is not None and self.well_col in data.columns:
            for w in data[self.well_col]:
                labels.setdefault(group_key(w, self.well_kind), str(w))
        self.porosity_scales = {labels.get(k, k or ''): v
                                for k, v in self._scales_by_group.items()}
        distinct = set(self._scales_by_group.values())
        self.porosity_converted = 'percent' in distinct
        self.porosity_scale_mixed = len(distinct) > 1
        self.porosity_scale = next(iter(distinct)) if len(distinct) == 1 else None
        if self.porosity_scale_mixed:
            parts = ", ".join(f"{name}: {scale}" for name, scale in self.porosity_scales.items())
            self.porosity_warning = (
                f"Porosity scale differs between wells ({parts}). Check each well.")
        else:
            self.porosity_warning = None

    def set_porosity_scale(self, scale: str, well: Optional[str] = None) -> int:
        """Override the porosity scale ('percent' or 'fraction') of this part.

        Re-derives the porosity from the values as read. ``well`` limits the change to
        one well of a multi-well handler (any spelling); a split part is changed as a
        whole. Values above 1 after conversion become NaN.

        Returns:
            The number of values that became invalid.
        """
        if scale not in ('percent', 'fraction'):
            raise ValueError("scale must be 'percent' or 'fraction'")
        if self.data is None or self.porosity_col is None or self._por_raw is None:
            return 0
        keys = self._group_keys(self.data)
        mask = np.ones(len(keys), dtype=bool)
        if well is not None:
            mask = keys == group_key(well, self.well_kind)
        raw = self._por_raw
        new = raw[mask] / 100.0 if scale == 'percent' else raw[mask]
        invalid = np.isfinite(new) & (new > 1.0)
        new = np.where(invalid, np.nan, new)
        values = self.data[self.porosity_col].to_numpy(dtype=float).copy()
        values[mask] = new
        self.data[self.porosity_col] = values
        for key in set(keys[mask]):
            self._scales_by_group[key] = scale
        self._publish_scales()
        return int(invalid.sum())
    
    def convert_depth_to_feet(self):
        """Convert depth from meters to feet to match log data."""
        if self.data is None or self.converted_to_feet:
            return
        
        if self.depth_col:
            self.data[self.depth_col] = self.data[self.depth_col] * self.M_TO_FT
            self.depth_unit = 'FT'
            self.converted_to_feet = True
            logger.info("Converted core depths from M to FT")
    
    def get_available_properties(self) -> List[str]:
        """Get list of available core properties."""
        props = []
        if self.porosity_col:
            props.append('porosity')
        if self.perm_col:
            props.append('permeability')
        if self.grain_density_col:
            props.append('grain_density')
        return props
    
    def get_core_depths(self) -> np.ndarray:
        """Get array of core sample depths."""
        if self.data is None or self.depth_col is None:
            return np.array([])
        return self.data[self.depth_col].values
    
    def get_core_porosity(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Get core porosity values with corresponding depths.
        
        Returns:
            Tuple of (depths, porosity values)
        """
        if self.data is None or self.porosity_col is None:
            return np.array([]), np.array([])
        
        mask = self.data[self.porosity_col].notna()
        depths = self.data.loc[mask, self.depth_col].values
        porosity = self.data.loc[mask, self.porosity_col].values
        return depths, porosity
    
    def get_core_permeability(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Get core permeability values with corresponding depths.
        
        Returns:
            Tuple of (depths, permeability values in mD)
        """
        if self.data is None or self.perm_col is None:
            return np.array([]), np.array([])
        
        mask = self.data[self.perm_col].notna()
        depths = self.data.loc[mask, self.depth_col].values
        perm = self.data.loc[mask, self.perm_col].values
        return depths, perm
    
    def interpolate_log_to_core(self, log_depth: np.ndarray, 
                                 log_values: np.ndarray,
                                 core_depths: np.ndarray,
                                 max_dist_ft: float = 2.0) -> np.ndarray:
        """
        Interpolate log values to core sample depths.
        
        Args:
            log_depth: Log depth array
            log_values: Log property values
            core_depths: Core sample depths to interpolate to
            max_dist_ft: Maximum distance from core depth to nearest log point (feet).
                        If distance is greater, returns NaN for that point.
            
        Returns:
            Interpolated log values at core depths
        """
        # Create mask for valid log data
        valid_mask = ~np.isnan(log_values) & ~np.isnan(log_depth)
        if valid_mask.sum() < 2:
            return np.full(len(core_depths), np.nan)
        
        log_depth_valid = log_depth[valid_mask]
        log_values_valid = log_values[valid_mask]
        
        # Linear interpolation
        try:
            interp_func = interp1d(log_depth_valid, log_values_valid, 
                                   kind='linear', 
                                   bounds_error=False, 
                                   fill_value=np.nan)
            interpolated = interp_func(core_depths)
            
            # Apply max distance constraint
            # Find nearest log depth for each core depth
            # (Note: log_depth_valid is usually sorted or mostly sorted)
            for i, cd in enumerate(core_depths):
                if np.isnan(interpolated[i]):
                    continue
                # Simple check for nearest point
                nearest_dist = np.min(np.abs(log_depth_valid - cd))
                if nearest_dist > max_dist_ft:
                    interpolated[i] = np.nan
            
            return interpolated
        except Exception as e:
            logger.warning("Interpolation error: %s", e)
            return np.full(len(core_depths), np.nan)
    
    def validate_porosity(self, log_depth: np.ndarray,
                          log_phie: np.ndarray,
                          max_dist_ft: float = 2.0) -> Optional[CoreValidationResult]:
        """
        Validate log porosity against core porosity.
        
        Args:
            log_depth: Log depth array
            log_phie: Log effective porosity (0-1 scale)
            max_dist_ft: Maximum distance for interpolation
            
        Returns:
            CoreValidationResult with validation metrics, or None if validation not possible
        """
        if self.porosity_col is None:
            return None
        
        core_depths, core_por = self.get_core_porosity()
        if len(core_depths) < 3:
            logger.warning("Insufficient core porosity data (< 3 points)")
            return None
        
        # Interpolate log to core depths
        log_at_core = self.interpolate_log_to_core(log_depth, log_phie, core_depths, max_dist_ft)
        
        # Create valid mask (both log and core have values)
        valid_mask = ~np.isnan(log_at_core) & ~np.isnan(core_por)
        n_points = valid_mask.sum()
        
        if n_points < 3:
            logger.warning("Insufficient matched points: %s", n_points)
            return None
        
        log_valid = log_at_core[valid_mask]
        core_valid = core_por[valid_mask]
        
        # Calculate metrics
        errors = log_valid - core_valid
        bias = np.mean(errors)
        mae = np.mean(np.abs(errors))
        rmse = np.sqrt(np.mean(errors ** 2))
        
        # R-squared
        try:
            ss_res = np.sum(errors ** 2)
            ss_tot = np.sum((core_valid - np.mean(core_valid)) ** 2)
            r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else None
        except:
            r_squared = None
        
        # Spearman correlation (robust to non-linear relationships)
        spearman_rho, spearman_p = stats.spearmanr(log_valid, core_valid)
        
        return CoreValidationResult(
            n_points=n_points,
            bias=bias,
            mae=mae,
            rmse=rmse,
            r_squared=r_squared,
            spearman_rho=spearman_rho,
            spearman_pvalue=spearman_p
        )
    
    def validate_permeability(self, log_depth: np.ndarray,
                               log_perm: np.ndarray,
                               max_dist_ft: float = 2.0) -> Optional[PermValidationResult]:
        """
        Validate log permeability against core permeability.
        
        Computes metrics in both linear and log10 domains.
        
        Args:
            log_depth: Log depth array
            log_perm: Log permeability in mD
            max_dist_ft: Maximum distance for interpolation
            
        Returns:
            PermValidationResult with validation metrics, or None if validation not possible
        """
        if self.perm_col is None:
            return None
        
        core_depths, core_perm = self.get_core_permeability()
        if len(core_depths) < 3:
            logger.warning("Insufficient core permeability data (< 3 points)")
            return None
        
        # Interpolate log to core depths
        log_at_core = self.interpolate_log_to_core(log_depth, log_perm, core_depths, max_dist_ft)
        
        # Create valid mask for linear domain
        valid_mask = ~np.isnan(log_at_core) & ~np.isnan(core_perm)
        n_points = valid_mask.sum()
        
        if n_points < 3:
            logger.warning("Insufficient matched points: %s", n_points)
            return None
        
        log_valid = log_at_core[valid_mask]
        core_valid = core_perm[valid_mask]
        
        # ===== LINEAR DOMAIN METRICS =====
        errors_lin = log_valid - core_valid
        bias_linear = np.mean(errors_lin)
        mae_linear = np.mean(np.abs(errors_lin))
        rmse_linear = np.sqrt(np.mean(errors_lin ** 2))
        
        # R-squared (linear)
        try:
            ss_res = np.sum(errors_lin ** 2)
            ss_tot = np.sum((core_valid - np.mean(core_valid)) ** 2)
            r_squared_linear = 1 - (ss_res / ss_tot) if ss_tot > 0 else None
        except:
            r_squared_linear = None
        
        # Spearman correlation
        spearman_rho, spearman_p = stats.spearmanr(log_valid, core_valid)
        
        # ===== LOG10 DOMAIN METRICS =====
        # Mask for valid log scale (perm > 0)
        log_valid_mask = valid_mask & (log_at_core > 0) & (core_perm > 0)
        n_valid_log = log_valid_mask.sum()
        
        if n_valid_log >= 3:
            log_log = np.log10(log_at_core[log_valid_mask])
            core_log = np.log10(core_perm[log_valid_mask])
            errors_log = log_log - core_log
            mae_log10 = np.mean(np.abs(errors_log))
            rmse_log10 = np.sqrt(np.mean(errors_log ** 2))
        else:
            mae_log10 = np.nan
            rmse_log10 = np.nan
        
        return PermValidationResult(
            n_points=n_points,
            bias_linear=bias_linear,
            mae_linear=mae_linear,
            rmse_linear=rmse_linear,
            r_squared_linear=r_squared_linear,
            spearman_rho=spearman_rho,
            spearman_pvalue=spearman_p,
            n_valid_log=n_valid_log,
            mae_log10=mae_log10,
            rmse_log10=rmse_log10
        )
    
    def get_matched_data(self, log_depth: np.ndarray,
                          log_phie: np.ndarray = None,
                          log_perm: np.ndarray = None,
                          max_dist_ft: float = 2.0) -> pd.DataFrame:
        """
        Get DataFrame with matched core and log data for plotting.
        
        Args:
            log_depth: Log depth array
            log_phie: Log porosity (optional)
            log_perm: Log permeability (optional)
            max_dist_ft: Maximum distance for interpolation
            
        Returns:
            DataFrame with matched data at core depths
        """
        if self.data is None:
            return pd.DataFrame()
        
        result = pd.DataFrame()
        
        # Add core depths
        if self.depth_col:
            result['DEPTH'] = self.data[self.depth_col].values
        
        # Add core porosity
        if self.porosity_col:
            result['CORE_POROSITY'] = self.data[self.porosity_col].values
        
        # Add core permeability
        if self.perm_col:
            result['CORE_PERM'] = self.data[self.perm_col].values
        
        # Add interpolated log values
        if log_phie is not None and 'DEPTH' in result.columns:
            result['LOG_PHIE'] = self.interpolate_log_to_core(
                log_depth, log_phie, result['DEPTH'].values, max_dist_ft
            )
        
        if log_perm is not None and 'DEPTH' in result.columns:
            result['LOG_PERM'] = self.interpolate_log_to_core(
                log_depth, log_perm, result['DEPTH'].values, max_dist_ft
            )
        
        return result
    
    def get_summary(self) -> Dict:
        """Get summary of loaded core data."""
        if self.data is None:
            return {}
        
        summary = {
            'n_samples': len(self.data),
            'depth_range': (self.data[self.depth_col].min(), self.data[self.depth_col].max()),
            'depth_unit': self.depth_unit,
            'properties': self.get_available_properties()
        }
        
        if self.porosity_col:
            por = self.data[self.porosity_col].dropna()
            summary['porosity_stats'] = {
                'n': len(por),
                'mean': por.mean(),
                'min': por.min(),
                'max': por.max()
            }
        
        if self.perm_col:
            perm = self.data[self.perm_col].dropna()
            summary['perm_stats'] = {
                'n': len(perm),
                'mean': perm.mean(),
                'min': perm.min(),
                'max': perm.max()
            }
        
        return summary
    
    # ------------------------------------------------------------------
    # Multi-well files
    # ------------------------------------------------------------------
    def well_names(self) -> List[str]:
        """Well names in the file's well column, in order of first appearance.

        Empty when the file has no well column.
        """
        if self.data is None or not self.well_col or self.well_col not in self.data.columns:
            return []
        values = self.data[self.well_col].dropna().astype(str).str.strip()
        return [v for v in dict.fromkeys(values) if v]

    def _make_part(self, idx: np.ndarray, spellings: List[str]) -> 'CoreDataHandler':
        part = copy.copy(self)
        part.data = self.data.iloc[idx].reset_index(drop=True)
        part.spellings = list(spellings)
        if self._por_raw is not None:
            part._por_raw = self._por_raw[idx]
        keys = {group_key(s, self.well_kind) for s in spellings}
        part._scales_by_group = {k: v for k, v in self._scales_by_group.items() if k in keys}
        part._publish_scales()
        return part

    def split_by_well(self, group: bool = False) -> Dict[str, 'CoreDataHandler']:
        """One CoreDataHandler per well (same unit state, that well's samples).

        With ``group=False`` the parts are keyed by the raw well string. With
        ``group=True`` spellings of one well ("BKS-01", "BKS 01") form one part, re-sorted
        by depth, keyed by the first spelling seen; ``part.spellings`` lists all of them.
        Each part carries its own ``porosity_scale``.
        """
        parts: Dict[str, CoreDataHandler] = {}
        names = self.well_names()
        if not names:
            return parts
        labels = self.data[self.well_col].astype(str).str.strip().to_numpy()
        if not group:
            for name in names:
                parts[name] = self._make_part(np.flatnonzero(labels == name), [name])
            return parts
        depths = self.data[self.depth_col].to_numpy(dtype=float)
        for _key, spellings in group_well_names(names, self.well_kind).items():
            idx = np.flatnonzero(np.isin(labels, spellings))
            idx = idx[np.argsort(depths[idx], kind='stable')]
            parts[spellings[0]] = self._make_part(idx, spellings)
        return parts

    def to_dataframe(self) -> pd.DataFrame:
        """
        Return the core data as a DataFrame.

        Note: column names are normalized to lower-case (see read_core_from_buffer).
        Use the resolved ``depth_col``/``porosity_col``/``perm_col`` attributes to
        access specific columns rather than assuming original header casing.
        """
        if self.data is None:
            return pd.DataFrame()
        return self.data.copy()
