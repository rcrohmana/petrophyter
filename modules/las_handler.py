"""
LAS Handler Module for Petrophyter
Handles merging of multiple LAS files with automatic curve selection
based on coverage and QC scores.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass


# Discrete curves tokens that should NOT be interpolated
DISCRETE_CURVE_TOKENS = ['LITH', 'FACIES', 'FLAG', 'ZONE', 'CODE', 'TYPE', 'CLASS']

# Expected curve ranges for QC scoring
CURVE_RANGES = {
    'GR': (0, 300),
    'RHOB': (1.0, 3.0),
    'NPHI': (-0.15, 0.60),
    'DT': (40, 250),
    'RT': (0.1, 10000),
    'CALI': (4, 20),
    'SP': (-200, 200),
    'PEF': (0, 10),
}

# Common null values to replace
COMMON_NULL_VALUES = [-999.25, -999, -9999, -999.0, -9999.0, -999999, 999.25]


@dataclass
class MergeReport:
    """Data class for merge report."""
    curves: Dict[str, Dict]
    master_depth: Dict
    files_processed: List[str]
    warnings: List[str]
    well_name: str


def _get_las_metadata(las_obj, key: str, default: Any = None) -> Any:
    """
    Safely get metadata from LAS parser object.
    Handles both well_info dict and wellinfo attribute styles.
    
    Args:
        las_obj: LAS parser object
        key: Metadata key to retrieve
        default: Default value if not found
        
    Returns:
        Metadata value or default
    """
    # Try well_info dict first (our LASParser style)
    if hasattr(las_obj, 'well_info') and isinstance(las_obj.well_info, dict):
        return las_obj.well_info.get(key, default)
    
    # Try wellinfo dict
    if hasattr(las_obj, 'wellinfo') and isinstance(las_obj.wellinfo, dict):
        return las_obj.wellinfo.get(key, default)
    
    # Try direct attribute
    if hasattr(las_obj, key):
        return getattr(las_obj, key, default)
    
    return default


def _is_discrete_curve(curve_name: str) -> bool:
    """
    Check if a curve is discrete (should not be interpolated).
    Uses token matching for flexibility.
    
    Args:
        curve_name: Curve name to check
        
    Returns:
        True if discrete curve
    """
    curve_upper = curve_name.upper()
    for token in DISCRETE_CURVE_TOKENS:
        if token in curve_upper:
            return True
    return False


class LASHandler:
    """
    Handler for merging multiple LAS files.
    
    Provides functionality for:
    - Normalizing LAS DataFrames
    - Building master depth grids
    - QC scoring per curve
    - Merging files with coverage-based selection
    """
    
    def __init__(self):
        self.files = []
        self.merged_df = None
        self.merge_report = None
    
    def normalize_las_dataframe(self, df: pd.DataFrame, 
                                 null_values: List[float] = None,
                                 depth_unit: str = 'FT') -> pd.DataFrame:
        """
        Normalize a LAS DataFrame for merging.
        
        Args:
            df: Input DataFrame from LAS file
            null_values: List of null values to replace with NaN
            depth_unit: Depth unit ('FT' or 'M')
            
        Returns:
            Normalized DataFrame
        """
        df = df.copy()
        
        # 1. Ensure DEPTH column exists
        depth_cols = ['DEPT', 'DEPTH', 'MD', 'TVD', 'TDEP']
        for col in depth_cols:
            if col in df.columns and col != 'DEPTH':
                df = df.rename(columns={col: 'DEPTH'})
                break
        
        if 'DEPTH' not in df.columns:
            raise ValueError("No depth column found in DataFrame")
        
        # 2. Convert null values to NaN
        if null_values is None:
            null_values = COMMON_NULL_VALUES
        
        for col in df.columns:
            if col != 'DEPTH' and df[col].dtype in ['float64', 'float32', 'int64']:
                for null in null_values:
                    mask = np.abs(df[col] - null) < 0.01
                    df.loc[mask, col] = np.nan
        
        # 3. Convert depth to FT if in meters
        if depth_unit.upper() in ['M', 'METER', 'METERS']:
            df['DEPTH'] = df['DEPTH'] * 3.28084
        
        # 4. Sort by depth
        df = df.sort_values('DEPTH').reset_index(drop=True)
        
        # 5. Handle duplicate depths (take median)
        if df['DEPTH'].duplicated().any():
            df = df.groupby('DEPTH').median().reset_index()
        
        return df
    
    def build_master_depth(self, files_dfs: List[pd.DataFrame], 
                           step_ft: float = 0.5) -> np.ndarray:
        """
        Build master depth grid from multiple files.
        
        Args:
            files_dfs: List of normalized DataFrames
            step_ft: Depth step in feet
            
        Returns:
            Master depth array
        """
        # Find global min/max depth
        all_mins = []
        all_maxs = []
        
        for df in files_dfs:
            if 'DEPTH' in df.columns and len(df) > 0:
                all_mins.append(df['DEPTH'].min())
                all_maxs.append(df['DEPTH'].max())
        
        if not all_mins or not all_maxs:
            raise ValueError("No valid depth data found in files")
        
        global_min = min(all_mins)
        global_max = max(all_maxs)
        
        # Round to step
        min_depth = np.floor(global_min / step_ft) * step_ft
        max_depth = np.ceil(global_max / step_ft) * step_ft
        
        master_depth = np.arange(min_depth, max_depth + step_ft, step_ft)
        
        return master_depth
    
    def curve_qc_score(self, series: pd.Series, 
                       curve_type: str = None) -> float:
        """
        Calculate QC score (0-100) for a curve.
        
        Components:
        - Coverage (40%): 1 - missing fraction
        - Flatline (20%): 1 - consecutive zeros ratio (with tolerance)
        - Spike (20%): 1 - outlier ratio
        - Range (20%): within expected bounds
        
        Args:
            series: Curve data series
            curve_type: Curve type for range checking
            
        Returns:
            QC score 0-100
        """
        if len(series) == 0:
            return 0.0
        
        series_clean = series.dropna()
        
        if len(series_clean) == 0:
            return 0.0
        
        # 1. Coverage score (40%)
        coverage = len(series_clean) / len(series)
        coverage_score = coverage * 40
        
        # 2. Flatline score (20%) - use np.isclose for tolerance
        if len(series_clean) > 1:
            diffs = series_clean.diff().dropna()
            if len(diffs) > 0:
                # Use tolerance for float comparison
                data_range = series_clean.max() - series_clean.min()
                atol = max(1e-6, data_range * 0.0001)  # 0.01% of data range
                flatline_mask = np.isclose(diffs, 0, atol=atol)
                flatline_ratio = flatline_mask.sum() / len(diffs)
                flatline_score = (1 - flatline_ratio) * 20
            else:
                flatline_score = 20
        else:
            flatline_score = 20
        
        # 3. Spike score (20%)
        if len(series_clean) > 10:
            diffs = series_clean.diff().dropna().abs()
            if len(diffs) > 0:
                p99 = np.percentile(diffs, 99)
                spike_ratio = (diffs > p99 * 3).sum() / len(diffs)
                spike_score = (1 - spike_ratio) * 20
            else:
                spike_score = 20
        else:
            spike_score = 20
        
        # 4. Range score (20%)
        if curve_type and curve_type.upper() in CURVE_RANGES:
            expected_min, expected_max = CURVE_RANGES[curve_type.upper()]
            in_range = ((series_clean >= expected_min) & (series_clean <= expected_max)).sum()
            range_score = (in_range / len(series_clean)) * 20
        else:
            range_score = 20  # No range check, full score
        
        total_score = coverage_score + flatline_score + spike_score + range_score
        
        return min(100, max(0, total_score))
    
    def project_to_master_grid(self, df: pd.DataFrame, 
                                master_depth: np.ndarray,
                                gap_limit_ft: float = 5.0,
                                step_ft: float = 0.5) -> pd.DataFrame:
        """
        Project DataFrame to master depth grid with interpolation.
        
        Args:
            df: Input DataFrame
            master_depth: Master depth array
            gap_limit_ft: Maximum gap for interpolation
            step_ft: Depth step (for discrete curve max_dist)
            
        Returns:
            Projected DataFrame on master grid
        """
        # Create output DataFrame
        result = pd.DataFrame({'DEPTH': master_depth})
        
        if 'DEPTH' not in df.columns:
            return result
        
        # Get curves (excluding DEPTH)
        curves = [c for c in df.columns if c != 'DEPTH']
        
        # Discrete curve max distance = 2 * step
        discrete_max_dist = max(1.0, 2 * step_ft)
        
        for curve in curves:
            curve_data = df[['DEPTH', curve]].dropna()
            
            if len(curve_data) == 0:
                result[curve] = np.nan
                continue
            
            # Check if discrete curve using token matching
            is_discrete = _is_discrete_curve(curve)
            
            if is_discrete:
                # Nearest neighbor with limit based on step
                result[curve] = self._nearest_neighbor_interp(
                    master_depth, 
                    curve_data['DEPTH'].values,
                    curve_data[curve].values,
                    max_dist=discrete_max_dist
                )
            else:
                # Linear interpolation with gap limit
                result[curve] = self._linear_interp_with_gap_limit(
                    master_depth,
                    curve_data['DEPTH'].values,
                    curve_data[curve].values,
                    gap_limit_ft
                )
        
        return result
    
    def _linear_interp_with_gap_limit(self, x_new: np.ndarray,
                                       x: np.ndarray, y: np.ndarray,
                                       gap_limit: float) -> np.ndarray:
        """Linear interpolation with gap limit."""
        result = np.full(len(x_new), np.nan)
        
        # Sort input
        sort_idx = np.argsort(x)
        x_sorted = x[sort_idx]
        y_sorted = y[sort_idx]
        
        for i, xi in enumerate(x_new):
            # Find surrounding points
            idx_right = np.searchsorted(x_sorted, xi)
            
            if idx_right == 0:
                # Before first point
                if abs(xi - x_sorted[0]) <= gap_limit:
                    result[i] = y_sorted[0]
            elif idx_right >= len(x_sorted):
                # After last point
                if abs(xi - x_sorted[-1]) <= gap_limit:
                    result[i] = y_sorted[-1]
            else:
                # Between points
                x_left = x_sorted[idx_right - 1]
                x_right = x_sorted[idx_right]
                
                if (x_right - x_left) <= gap_limit:
                    # Interpolate
                    t = (xi - x_left) / (x_right - x_left)
                    result[i] = y_sorted[idx_right - 1] * (1 - t) + y_sorted[idx_right] * t
        
        return result
    
    def _nearest_neighbor_interp(self, x_new: np.ndarray,
                                  x: np.ndarray, y: np.ndarray,
                                  max_dist: float) -> np.ndarray:
        """Nearest neighbor interpolation with distance limit."""
        result = np.full(len(x_new), np.nan)
        
        for i, xi in enumerate(x_new):
            distances = np.abs(x - xi)
            min_idx = np.argmin(distances)
            
            if distances[min_idx] <= max_dist:
                result[i] = y[min_idx]
        
        return result
    
    def select_best_source(self, curve_name: str,
                           projected_dfs: List[Tuple[str, pd.DataFrame]],
                           qc_scores: Dict[str, Dict[str, float]]) -> List[Tuple[str, float, float]]:
        """
        Rank files by coverage and QC score for a curve.
        
        Args:
            curve_name: Curve to evaluate
            projected_dfs: List of (filename, projected_df) tuples
            qc_scores: Dict of {filename: {curve: score}}
            
        Returns:
            Sorted list of (filename, coverage, qc_score)
        """
        rankings = []
        
        for filename, df in projected_dfs:
            if curve_name in df.columns:
                coverage = df[curve_name].notna().sum() / len(df)
                qc_score = qc_scores.get(filename, {}).get(curve_name, 50)
                rankings.append((filename, coverage, qc_score))
        
        # Sort by coverage first, then QC score
        rankings.sort(key=lambda x: (x[1], x[2]), reverse=True)
        
        return rankings
    
    def fill_gaps_from_secondary(self, primary: pd.Series,
                                  secondary: pd.Series) -> Tuple[pd.Series, int]:
        """
        Fill gaps in primary series using secondary source.
        
        Args:
            primary: Primary data series
            secondary: Secondary data series
            
        Returns:
            Tuple of (filled series, number of gaps filled)
        """
        result = primary.copy()
        gaps = result.isna()
        gaps_before = gaps.sum()
        result.loc[gaps] = secondary.loc[gaps]
        gaps_after = result.isna().sum()
        gaps_filled = gaps_before - gaps_after
        return result, int(gaps_filled)
    
    def merge_las_files(self, las_objects: List[Any],
                        file_identifiers: List[str] = None,
                        step_ft: float = 0.5,
                        gap_limit_ft: float = None) -> Dict:
        """
        Merge multiple LAS files.
        
        Args:
            las_objects: List of LASParser objects
            file_identifiers: List of file names/identifiers (for report)
            step_ft: Master depth step in feet
            gap_limit_ft: Maximum interpolation gap (None = auto)
            
        Returns:
            Dict with 'merged_df' and 'merge_report'
        """
        if not las_objects:
            raise ValueError("No LAS files provided")
        
        # Single file case
        if len(las_objects) == 1:
            well_name = _get_las_metadata(las_objects[0], 'well_name', 'Unknown')
            file_id = file_identifiers[0] if file_identifiers else well_name
            return {
                'merged_df': las_objects[0].data,
                'merge_report': MergeReport(
                    curves={},
                    master_depth={'min': 0, 'max': 0, 'step': step_ft, 'points': 0},
                    files_processed=[file_id],
                    warnings=['Single file provided, no merge needed'],
                    well_name=well_name
                )
            }
        
        warnings = []
        
        # Validate same well
        well_names = set()
        for las in las_objects:
            well_name = _get_las_metadata(las, 'well_name', 'Unknown')
            well_names.add(well_name)
        
        if len(well_names) > 1:
            warnings.append(f"Multiple wells detected: {well_names}")
        
        # Normalize all DataFrames
        normalized_dfs = []
        file_names = []  # Actual file identifiers
        
        for i, las in enumerate(las_objects):
            df = las.data.copy()
            depth_unit = _get_las_metadata(las, 'depth_unit', 'FT')
            null_val = _get_las_metadata(las, 'null_value', -999.25)
            
            # Use file identifier if provided, else use index-based name
            if file_identifiers and i < len(file_identifiers):
                file_id = file_identifiers[i]
            else:
                file_id = f"File_{i+1}"
            
            try:
                normalized = self.normalize_las_dataframe(
                    df, 
                    null_values=[null_val] + COMMON_NULL_VALUES if null_val else COMMON_NULL_VALUES,
                    depth_unit=depth_unit
                )
                normalized_dfs.append(normalized)
                file_names.append(file_id)
            except Exception as e:
                warnings.append(f"Error normalizing {file_id}: {str(e)}")
        
        if not normalized_dfs:
            raise ValueError("No files could be normalized")
        
        # Build master depth grid
        master_depth = self.build_master_depth(normalized_dfs, step_ft)
        
        # Calculate adaptive gap limit if not provided
        if gap_limit_ft is None:
            median_steps = []
            for df in normalized_dfs:
                if 'DEPTH' in df.columns and len(df) > 1:
                    steps = df['DEPTH'].diff().dropna()
                    if len(steps) > 0:
                        median_steps.append(steps.median())
            
            if median_steps:
                gap_limit_ft = max(5.0, 10 * np.median(median_steps))
            else:
                gap_limit_ft = 5.0
        
        # Project all files to master grid
        projected_dfs = []
        for i, df in enumerate(normalized_dfs):
            projected = self.project_to_master_grid(df, master_depth, gap_limit_ft, step_ft)
            projected_dfs.append((file_names[i], projected))
        
        # Calculate QC scores per curve per file
        qc_scores = {}
        for filename, df in projected_dfs:
            qc_scores[filename] = {}
            for col in df.columns:
                if col != 'DEPTH':
                    curve_type = col.upper()
                    qc_scores[filename][col] = self.curve_qc_score(df[col], curve_type)
        
        # Get all curves
        all_curves = set()
        for _, df in projected_dfs:
            all_curves.update([c for c in df.columns if c != 'DEPTH'])
        
        # Merge curves
        merged_df = pd.DataFrame({'DEPTH': master_depth})
        curve_sources = {}
        
        for curve in all_curves:
            rankings = self.select_best_source(curve, projected_dfs, qc_scores)
            
            if not rankings:
                continue
            
            # Get primary source
            primary_file, primary_coverage, primary_qc = rankings[0]
            primary_df = next(df for fn, df in projected_dfs if fn == primary_file)
            merged_df[curve] = primary_df[curve].copy()
            
            # Initialize curve source info IMMEDIATELY (fix for missing curves in report)
            curve_sources[curve] = {
                'source_file': primary_file,
                'coverage': float(merged_df[curve].notna().sum() / len(merged_df)),
                'qc_score': float(primary_qc),
                'gaps_filled_from': None,
                'gaps_count': 0
            }
            
            # Fill gaps from secondary sources
            total_gaps_filled = 0
            secondary_sources = []
            
            for sec_file, _, _ in rankings[1:]:
                if merged_df[curve].isna().any():
                    sec_df = next((df for fn, df in projected_dfs if fn == sec_file), None)
                    if sec_df is not None and curve in sec_df.columns:
                        merged_df[curve], filled = self.fill_gaps_from_secondary(
                            merged_df[curve], sec_df[curve]
                        )
                        if filled > 0:
                            total_gaps_filled += filled
                            secondary_sources.append(sec_file)
            
            # Update with gap fill info
            curve_sources[curve]['coverage'] = float(merged_df[curve].notna().sum() / len(merged_df))
            curve_sources[curve]['gaps_filled_from'] = secondary_sources[0] if secondary_sources else None
            curve_sources[curve]['gaps_count'] = total_gaps_filled
        
        # Create merge report
        merge_report = MergeReport(
            curves=curve_sources,
            master_depth={
                'min': float(master_depth.min()),
                'max': float(master_depth.max()),
                'step': step_ft,
                'points': len(master_depth)
            },
            files_processed=file_names,
            warnings=warnings,
            well_name=list(well_names)[0] if well_names else 'Unknown'
        )
        
        self.merged_df = merged_df
        self.merge_report = merge_report
        
        return {
            'merged_df': merged_df,
            'merge_report': merge_report
        }


def validate_same_well(las_objects: List[Any]) -> Tuple[bool, List[str]]:
    """
    Validate that all LAS files are from the same well.
    
    Args:
        las_objects: List of LASParser objects
        
    Returns:
        Tuple of (is_valid, list_of_well_names)
    """
    well_names = []
    for las in las_objects:
        name = _get_las_metadata(las, 'well_name', 'Unknown')
        well_names.append(name)
    
    unique_names = set(well_names)
    return len(unique_names) == 1, well_names


def export_merged_las(merged_df: pd.DataFrame, 
                      well_info: Dict,
                      output_path: str = None) -> str:
    """
    Export merged DataFrame to LAS format.
    
    Args:
        merged_df: Merged DataFrame
        well_info: Well information dictionary
        output_path: Output file path
        
    Returns:
        LAS file content as string
    """
    from datetime import datetime
    
    lines = []
    
    # Version section
    lines.append("~VERSION INFORMATION")
    lines.append(" VERS.                          2.0 : CWLS LAS - VERSION 2.0")
    lines.append(" WRAP.                           NO : One line per depth step")
    lines.append("")
    
    # Well section
    well_name = well_info.get('well_name', 'MERGED') if isinstance(well_info, dict) else 'MERGED'
    lines.append("~WELL INFORMATION")
    lines.append(f" WELL.                 {well_name} : WELL NAME")
    lines.append(f" STRT.FT            {merged_df['DEPTH'].min():.2f} : START DEPTH")
    lines.append(f" STOP.FT            {merged_df['DEPTH'].max():.2f} : STOP DEPTH")
    lines.append(f" STEP.FT            {merged_df['DEPTH'].diff().median():.4f} : STEP")
    lines.append(f" NULL.              -999.2500 : NULL VALUE")
    lines.append(f" COMP.              PETROPHYTER : COMPANY")
    lines.append(f" DATE.              {datetime.now().strftime('%Y-%m-%d')} : LOG DATE")
    lines.append("")
    
    # Curve section
    lines.append("~CURVE INFORMATION")
    lines.append(" DEPTH.FT                        : DEPTH")
    for col in merged_df.columns:
        if col != 'DEPTH':
            lines.append(f" {col}.                           : {col}")
    lines.append("")
    
    # Data section
    lines.append("~A DEPTH " + " ".join(merged_df.columns[merged_df.columns != 'DEPTH']))
    
    for idx, row in merged_df.iterrows():
        values = [f"{row['DEPTH']:.2f}"]
        for col in merged_df.columns:
            if col != 'DEPTH':
                val = row[col]
                if pd.isna(val):
                    values.append("-999.2500")
                else:
                    values.append(f"{val:.4f}")
        lines.append(" ".join(values))
    
    content = "\n".join(lines)
    
    if output_path:
        with open(output_path, 'w') as f:
            f.write(content)
    
    return content
