"""
Core Data Handler Module for Petrophyter
Handles loading and validation of core data against log-derived petrophysical properties.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from scipy import stats
from scipy.interpolate import interp1d


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
    DEPTH_ALIASES = ['depth', 'depth (m)', 'depth(m)', 'depth_m', 'md', 'tvd', 'depth_md']
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
        self.porosity_unit: str = 'fraction'  # After conversion
        self.converted_to_feet: bool = False
        self.porosity_converted: bool = False
    
    # Updated read_core_from_buffer with depth_unit support
    def read_core_from_buffer(self, file_buffer, separator: str = '\t', depth_unit: str = 'Auto') -> bool:
        """
        Read core data from a file buffer (for Streamlit uploads).
        
        Args:
            file_buffer: File buffer object
            separator: Column separator (default tab)
            depth_unit: Depth unit: 'Auto', 'M', or 'FT'
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Try to read with specified separator
            try:
                df = pd.read_csv(file_buffer, sep=separator)
            except:
                # Fallback: try comma separator
                file_buffer.seek(0)
                df = pd.read_csv(file_buffer, sep=',')
            
            if df.empty:
                print("Empty file")
                return False
            
            # Normalize column names for matching
            df.columns = df.columns.str.strip().str.lower()
            
            # Find required depth column
            self.depth_col = self._find_column(df, self.DEPTH_ALIASES)
            if self.depth_col is None:
                print("Could not find depth column")
                return False
            
            # Find optional columns
            self.porosity_col = self._find_column(df, self.POROSITY_ALIASES)
            self.perm_col = self._find_column(df, self.PERM_ALIASES)
            self.grain_density_col = self._find_column(df, self.GRAIN_DENSITY_ALIASES)
            
            # Validate that we have at least one property to validate
            if self.porosity_col is None and self.perm_col is None:
                print("No porosity or permeability column found")
                return False
            
            # Clean data: drop rows where depth is NaN
            df = df.dropna(subset=[self.depth_col])
            
            # Convert numeric columns
            df[self.depth_col] = pd.to_numeric(df[self.depth_col], errors='coerce')
            if self.porosity_col:
                df[self.porosity_col] = pd.to_numeric(df[self.porosity_col], errors='coerce')
            if self.perm_col:
                df[self.perm_col] = pd.to_numeric(df[self.perm_col], errors='coerce')
            if self.grain_density_col:
                df[self.grain_density_col] = pd.to_numeric(df[self.grain_density_col], errors='coerce')
            
            # Drop rows where depth is still NaN after conversion
            df = df.dropna(subset=[self.depth_col])
            
            if df.empty:
                print("No valid data after cleaning")
                return False
            
            # Sort by depth
            df = df.sort_values(self.depth_col).reset_index(drop=True)
            
            self.data = df
            
            # Record original unit
            if depth_unit != 'Auto':
                self.depth_unit = depth_unit.upper()
            else:
                # Try to detect from column name
                if '(m)' in self.depth_col.lower() or '_m' in self.depth_col.lower():
                    self.depth_unit = 'M'
                elif '(ft)' in self.depth_col.lower() or '_ft' in self.depth_col.lower():
                    self.depth_unit = 'FT'
                else:
                    self.depth_unit = 'M'  # Default to M if unknown
            
            self._auto_convert_units()
            
            # Auto convert to feet if unit is M
            if self.depth_unit == 'M':
                self.convert_depth_to_feet()
            
            return True
            
        except Exception as e:
            print(f"Error reading core data: {e}")
            return False
    
    def read_core_file(self, file_path: str, separator: str = '\t') -> bool:
        """
        Read core data from a file path.
        
        Args:
            file_path: Path to the core data file
            separator: Column separator
            
        Returns:
            True if successful
        """
        try:
            with open(file_path, 'r') as f:
                return self.read_core_from_buffer(f, separator)
        except Exception as e:
            print(f"Error reading file: {e}")
            return False
    
    def _find_column(self, df: pd.DataFrame, aliases: List[str]) -> Optional[str]:
        """Find column by alias list (case-insensitive partial match)."""
        for alias in aliases:
            for col in df.columns:
                if alias in col.lower():
                    return col
        return None
    
    def _auto_convert_units(self):
        """Auto-detect and convert units for porosity."""
        if self.data is None or self.porosity_col is None:
            return
        
        porosity = self.data[self.porosity_col].dropna()
        if len(porosity) == 0:
            return
        
        # If max porosity > 1, assume it's in percentage (0-100)
        if porosity.max() > 1.0:
            self.data[self.porosity_col] = self.data[self.porosity_col] / 100.0
            self.porosity_converted = True
            print(f"Converted porosity from % to fraction (max was {porosity.max():.1f}%)")
    
    def convert_depth_to_feet(self):
        """Convert depth from meters to feet to match log data."""
        if self.data is None or self.converted_to_feet:
            return
        
        if self.depth_col:
            self.data[self.depth_col] = self.data[self.depth_col] * self.M_TO_FT
            self.depth_unit = 'FT'
            self.converted_to_feet = True
            print(f"Converted core depths from M to FT")
    
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
            print(f"Interpolation error: {e}")
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
            print("Insufficient core porosity data (< 3 points)")
            return None
        
        # Interpolate log to core depths
        log_at_core = self.interpolate_log_to_core(log_depth, log_phie, core_depths, max_dist_ft)
        
        # Create valid mask (both log and core have values)
        valid_mask = ~np.isnan(log_at_core) & ~np.isnan(core_por)
        n_points = valid_mask.sum()
        
        if n_points < 3:
            print(f"Insufficient matched points: {n_points}")
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
            print("Insufficient core permeability data (< 3 points)")
            return None
        
        # Interpolate log to core depths
        log_at_core = self.interpolate_log_to_core(log_depth, log_perm, core_depths, max_dist_ft)
        
        # Create valid mask for linear domain
        valid_mask = ~np.isnan(log_at_core) & ~np.isnan(core_perm)
        n_points = valid_mask.sum()
        
        if n_points < 3:
            print(f"Insufficient matched points: {n_points}")
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
    
    def to_dataframe(self) -> pd.DataFrame:
        """Return the core data as DataFrame."""
        if self.data is None:
            return pd.DataFrame()
        return self.data.copy()
