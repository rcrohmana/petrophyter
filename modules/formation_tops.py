"""
Formation Tops Module for Petrophyter
Handles reading and integrating formation top data
"""

import re
import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Depth-unit tokens for detecting units from column names.
_FEET_TOKENS = {'ft', 'feet', 'foot'}
_METER_TOKENS = {'m', 'meter', 'meters', 'metre', 'metres'}


def _tokenize(text: str) -> List[str]:
    """Split a string into lower-case alphanumeric tokens (drops punctuation)."""
    return [t for t in re.split(r'[^a-z0-9]+', str(text).lower()) if t]


@dataclass
class Formation:
    """Formation data class."""
    name: str
    top_depth: float
    bottom_depth: float
    thickness: float
    anomaly_code: str = ''


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
        
    def read_tops_file(self, file_path: str, separator: str = '\t') -> bool:
        """
        Read formation tops from a text file.
        
        Expected format (tab-separated):
        Stratigraphical unit    Top (m)    Bottom (m)    Anomaly code
        
        Args:
            file_path: Path to the tops file
            separator: Column separator (default tab)
            
        Returns:
            True if successful
        """
        self.last_error = None
        try:
            df = pd.read_csv(file_path, sep=separator)
            return self._build_from_dataframe(df)
        except Exception as e:
            self.last_error = str(e)
            logger.error("Error reading tops file: %s", e, exc_info=True)
            return False

    def read_tops_from_buffer(self, file_buffer, separator: str = '\t') -> bool:
        """
        Read formation tops from a file buffer (for Streamlit uploads).

        Args:
            file_buffer: File buffer object
            separator: Column separator

        Returns:
            True if successful
        """
        self.last_error = None
        try:
            df = pd.read_csv(file_buffer, sep=separator)
            return self._build_from_dataframe(df)
        except Exception as e:
            self.last_error = str(e)
            logger.error("Error reading tops: %s", e, exc_info=True)
            return False

    def _build_from_dataframe(self, df: pd.DataFrame) -> bool:
        """
        Build the formation list from a parsed DataFrame.

        Shared by read_tops_file and read_tops_from_buffer. Handles column
        detection, depth-unit detection, top>bottom swaps, missing bottom
        (defaulted to the next formation's top), and sorting.
        """
        # A FormationTops instance can be reused. Clear prior parsed data and
        # unit provenance before rebuilding so a previous conversion/warning
        # cannot suppress conversion or leak into the next file.
        self.formations = []
        self.depth_unit = 'M'
        self.depth_unit_detected = False
        self.depth_unit_warning = None
        self.converted_to_feet = False
        self.last_error = None

        # Normalize column names
        df.columns = df.columns.str.strip().str.lower()

        name_col = self._find_column(df, ['stratigrafical unit', 'stratigraphical unit',
                                          'formation', 'unit', 'name', 'fm'])
        top_col = self._find_column(df, ['top (m)', 'top (ft)', 'top', 'top_md', 'top_depth'])
        bottom_col = self._find_column(df, ['bottom (m)', 'bottom (ft)', 'bottom',
                                            'bottom_md', 'bottom_depth'])
        anomaly_col = self._find_column(df, ['anomaly code', 'anomaly', 'code', 'remarks'])

        if name_col is None or top_col is None:
            self.last_error = "Could not find required columns (name, top)"
            logger.warning(self.last_error)
            return False

        # Detect the depth unit from the top/bottom column names.
        self._detect_depth_unit(top_col, bottom_col)

        # Drop rows with no/invalid top depth before sorting so ordering is
        # deterministic (a NaN top would otherwise sort unpredictably).
        df = df.copy()
        df[top_col] = pd.to_numeric(df[top_col], errors='coerce')
        if bottom_col:
            df[bottom_col] = pd.to_numeric(df[bottom_col], errors='coerce')
        df = df.dropna(subset=[top_col])

        # Build raw records first (name, top, bottom-or-None, anomaly).
        records = []
        for _, row in df.iterrows():
            name = str(row[name_col]).strip()
            top = float(row[top_col])

            has_bottom = bool(bottom_col) and pd.notna(row[bottom_col])
            bottom = float(row[bottom_col]) if has_bottom else None

            # Repair reversed top/bottom (a common manual data-entry error)
            # instead of hiding it behind abs().
            if bottom is not None and bottom < top:
                logger.warning("Formation '%s' has bottom < top; swapping.", name)
                top, bottom = bottom, top

            anomaly = str(row[anomaly_col]).strip() if anomaly_col and pd.notna(row[anomaly_col]) else ''
            records.append({'name': name, 'top': top, 'bottom': bottom, 'anomaly': anomaly})

        # Sort by top depth so missing bottoms can be filled from the next top.
        records.sort(key=lambda r: r['top'])

        # Fill missing bottom depths with the next formation's top depth so a
        # formation without an explicit bottom column is not collapsed to zero
        # thickness (which broke every depth-range query).
        for i, rec in enumerate(records):
            if rec['bottom'] is None:
                if i + 1 < len(records):
                    rec['bottom'] = records[i + 1]['top']
                else:
                    rec['bottom'] = rec['top']  # last formation: no next top known

        self.formations = []
        seen_names = set()
        for rec in records:
            if rec['name'].lower() in seen_names:
                logger.warning("Duplicate formation name '%s'; queries return the first.", rec['name'])
            seen_names.add(rec['name'].lower())
            thickness = max(0.0, rec['bottom'] - rec['top'])
            self.formations.append(Formation(
                name=rec['name'],
                top_depth=rec['top'],
                bottom_depth=rec['bottom'],
                thickness=thickness,
                anomaly_code=rec['anomaly']
            ))

        return True

    def _detect_depth_unit(self, top_col: str, bottom_col: Optional[str]):
        """Detect the depth unit from top/bottom column names."""
        tokens = set(_tokenize(top_col))
        if bottom_col:
            tokens |= set(_tokenize(bottom_col))

        if tokens & _FEET_TOKENS:
            self.depth_unit = 'FT'
            self.depth_unit_detected = True
        elif tokens & _METER_TOKENS:
            self.depth_unit = 'M'
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
