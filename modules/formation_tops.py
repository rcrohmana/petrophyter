"""
Formation Tops Module for Petrophyter
Handles reading and integrating formation top data
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


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
        self.converted_to_feet = False
    
    def convert_to_feet(self):
        """
        Convert all formation depths from meters to feet.
        """
        if self.converted_to_feet:
            return  # Already converted
            
        for fm in self.formations:
            fm.top_depth *= self.M_TO_FT
            fm.bottom_depth *= self.M_TO_FT
            fm.thickness *= self.M_TO_FT
        
        self.depth_unit = 'FT'
        self.converted_to_feet = True
        print(f"Converted {len(self.formations)} formation tops from M to FT")
        
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
        try:
            # Read the file
            df = pd.read_csv(file_path, sep=separator)
            
            # Normalize column names
            df.columns = df.columns.str.strip().str.lower()
            
            # Find relevant columns
            name_col = self._find_column(df, ['stratigrafical unit', 'stratigraphical unit', 
                                              'formation', 'unit', 'name', 'fm'])
            top_col = self._find_column(df, ['top (m)', 'top', 'top_md', 'top_depth'])
            bottom_col = self._find_column(df, ['bottom (m)', 'bottom', 'bottom_md', 'bottom_depth'])
            anomaly_col = self._find_column(df, ['anomaly code', 'anomaly', 'code', 'remarks'])
            
            if name_col is None or top_col is None:
                print("Could not find required columns (name, top)")
                return False
            
            self.formations = []
            
            for _, row in df.iterrows():
                name = str(row[name_col]).strip()
                top = float(row[top_col])
                
                if bottom_col:
                    bottom = float(row[bottom_col])
                else:
                    bottom = top  # Will be updated later
                    
                anomaly = str(row[anomaly_col]).strip() if anomaly_col and pd.notna(row[anomaly_col]) else ''
                
                thickness = abs(bottom - top)
                
                self.formations.append(Formation(
                    name=name,
                    top_depth=top,
                    bottom_depth=bottom,
                    thickness=thickness,
                    anomaly_code=anomaly
                ))
            
            # Sort by top depth
            self.formations.sort(key=lambda f: f.top_depth)
            
            return True
            
        except Exception as e:
            print(f"Error reading tops file: {e}")
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
        try:
            df = pd.read_csv(file_buffer, sep=separator)
            
            # Same logic as read_tops_file
            df.columns = df.columns.str.strip().str.lower()
            
            name_col = self._find_column(df, ['stratigrafical unit', 'stratigraphical unit', 
                                              'formation', 'unit', 'name', 'fm'])
            top_col = self._find_column(df, ['top (m)', 'top', 'top_md', 'top_depth'])
            bottom_col = self._find_column(df, ['bottom (m)', 'bottom', 'bottom_md', 'bottom_depth'])
            anomaly_col = self._find_column(df, ['anomaly code', 'anomaly', 'code', 'remarks'])
            
            if name_col is None or top_col is None:
                return False
            
            self.formations = []
            
            for _, row in df.iterrows():
                name = str(row[name_col]).strip()
                top = float(row[top_col])
                bottom = float(row[bottom_col]) if bottom_col else top
                anomaly = str(row[anomaly_col]).strip() if anomaly_col and pd.notna(row[anomaly_col]) else ''
                thickness = abs(bottom - top)
                
                self.formations.append(Formation(
                    name=name,
                    top_depth=top,
                    bottom_depth=bottom,
                    thickness=thickness,
                    anomaly_code=anomaly
                ))
            
            self.formations.sort(key=lambda f: f.top_depth)
            return True
            
        except Exception as e:
            print(f"Error reading tops: {e}")
            return False
    
    def _find_column(self, df: pd.DataFrame, aliases: List[str]) -> Optional[str]:
        """Find column by alias list."""
        for alias in aliases:
            for col in df.columns:
                if alias in col.lower():
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
        for fm in self.formations:
            if fm.top_depth <= depth <= fm.bottom_depth:
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
        for fm in self.formations:
            # Check if formation overlaps with range
            if fm.bottom_depth >= top_depth and fm.top_depth <= bottom_depth:
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
            depth_range = self.get_depth_range_for_formation(fm_name)
            if depth_range:
                mask = (data[depth_col] >= depth_range[0]) & (data[depth_col] <= depth_range[1])
                masks.append(mask)
        
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
