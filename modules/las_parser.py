"""
LAS File Parser Module for Petrophyter
Handles reading and parsing LAS 2.0 format files
"""

import lasio
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Any


class LASParser:
    """
    LAS file parser class that handles reading and extracting data from LAS files.
    """
    
    def __init__(self):
        self.las = None
        self.well_info = {}
        self.curve_info = {}
        self.data = None
        self.null_value = -999.25
        
    def read_las(self, file_path: str) -> bool:
        """
        Read a LAS file and parse its contents.
        
        Args:
            file_path: Path to the LAS file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.las = lasio.read(file_path)
            self._extract_well_info()
            self._extract_curve_info()
            self._extract_data()
            return True
        except Exception as e:
            print(f"Error reading LAS file: {e}")
            return False
    
    def read_las_from_buffer(self, file_buffer) -> bool:
        """
        Read a LAS file from a file buffer (for Streamlit uploads).
        
        Args:
            file_buffer: File buffer object
            
        Returns:
            True if successful, False otherwise
        """
        try:
            import io
            
            # Read the file content
            file_buffer.seek(0)
            content = file_buffer.read()
            
            # Handle both bytes and string content
            if isinstance(content, bytes):
                content = content.decode('utf-8', errors='replace')
            
            # Create StringIO object for lasio
            string_io = io.StringIO(content)
            
            # Read with lasio (handles wrapped files automatically)
            self.las = lasio.read(string_io)
            self._extract_well_info()
            self._extract_curve_info()
            self._extract_data()
            return True
        except Exception as e:
            print(f"Error reading LAS file: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _extract_well_info(self):
        """Extract well header information."""
        if self.las is None:
            return
            
        self.well_info = {
            'well_name': self._get_header_value('WELL', 'Unknown'),
            'field': self._get_header_value('FLD', 'Unknown'),
            'company': self._get_header_value('COMP', 'Unknown'),
            'start_depth': self._get_header_value('STRT', 0),
            'stop_depth': self._get_header_value('STOP', 0),
            'step': self._get_header_value('STEP', 0),
            'null_value': self._get_header_value('NULL', -999.25),
            'depth_unit': self._get_depth_unit(),
        }
        self.null_value = self.well_info['null_value']
        
    def _get_header_value(self, mnemonic: str, default: Any) -> Any:
        """Get a value from LAS header."""
        try:
            return self.las.well[mnemonic].value
        except (KeyError, AttributeError):
            return default
    
    def _get_depth_unit(self) -> str:
        """Determine the depth unit from the LAS file."""
        try:
            strt_unit = self.las.well['STRT'].unit
            if strt_unit:
                return strt_unit.upper()
        except (KeyError, AttributeError):
            pass
        return 'M'  # Default to meters
    
    def _extract_curve_info(self):
        """Extract curve information."""
        if self.las is None:
            return
            
        self.curve_info = {}
        for curve in self.las.curves:
            self.curve_info[curve.mnemonic] = {
                'unit': curve.unit if curve.unit else '',
                'description': curve.descr if curve.descr else '',
                'data_type': str(curve.data.dtype),
            }
    
    def _extract_data(self):
        """Extract log data as a DataFrame."""
        if self.las is None:
            return
            
        self.data = self.las.df().reset_index()
        
        # Find the depth column
        depth_cols = ['DEPT', 'DEPTH', 'MD', 'TVD', 'TDEP']
        for col in depth_cols:
            if col in self.data.columns:
                self.data = self.data.rename(columns={col: 'DEPTH'})
                break
        
        # If depth is still in index
        if 'DEPTH' not in self.data.columns:
            if self.data.index.name in depth_cols or self.data.index.name is None:
                self.data = self.data.reset_index()
                self.data = self.data.rename(columns={self.data.columns[0]: 'DEPTH'})
        
        # Convert depth to FEET if in meters
        depth_unit = self.well_info.get('depth_unit', 'M').upper()
        self.original_depth_unit = depth_unit
        
        if depth_unit == 'M' or depth_unit == 'METER' or depth_unit == 'METERS':
            # Convert meters to feet (1 m = 3.28084 ft)
            self.data['DEPTH'] = self.data['DEPTH'] * 3.28084
            self.well_info['depth_unit'] = 'FT'
            self.well_info['converted_from_meters'] = True
            print(f"Converted depth from {depth_unit} to FT")
        else:
            self.well_info['converted_from_meters'] = False
        
        # Replace null values with NaN
        # 1. Replace the declared null value from LAS header
        null_val = self.null_value
        if null_val is not None:
            # Use tolerance for float comparison
            for col in self.data.columns:
                if col != 'DEPTH' and self.data[col].dtype in ['float64', 'float32']:
                    # Replace values close to null value (within tolerance)
                    mask = np.abs(self.data[col] - null_val) < 0.01
                    self.data.loc[mask, col] = np.nan
        
        # 2. Replace common null values that might not be declared
        common_null_values = [-999.25, -999, -9999, -999.0, -9999.0, -999999, 999.25]
        for null in common_null_values:
            for col in self.data.columns:
                if col != 'DEPTH' and self.data[col].dtype in ['float64', 'float32']:
                    mask = np.abs(self.data[col] - null) < 0.01
                    self.data.loc[mask, col] = np.nan
        
        # Store null value info
        self.null_values_replaced = True
        
    def get_available_curves(self) -> List[str]:
        """Get list of available curve mnemonics."""
        if self.data is None:
            return []
        return list(self.data.columns)
    
    def get_curve_data(self, mnemonic: str) -> Optional[pd.Series]:
        """Get data for a specific curve."""
        if self.data is None:
            return None
        if mnemonic in self.data.columns:
            return self.data[mnemonic]
        return None
    
    def get_depth_range(self) -> Tuple[float, float]:
        """Get the depth range of the data."""
        if self.data is None or 'DEPTH' not in self.data.columns:
            return (0, 0)
        return (self.data['DEPTH'].min(), self.data['DEPTH'].max())
    
    def get_data_in_range(self, top: float, bottom: float) -> pd.DataFrame:
        """Get data within a specified depth range."""
        if self.data is None:
            return pd.DataFrame()
        mask = (self.data['DEPTH'] >= top) & (self.data['DEPTH'] <= bottom)
        return self.data[mask].copy()
    
    def find_curve_by_type(self, curve_type: str) -> Optional[str]:
        """
        Find a curve mnemonic by its type.
        
        Args:
            curve_type: Type of curve ('GR', 'RHOB', 'NPHI', 'DT', 'RT', 'DEPTH')
            
        Returns:
            The mnemonic of the found curve or None
        """
        curve_aliases = {
            'GR':    ['GR', 'CGR', 'SGR', 'GAMMA', 'GAMMARAY'],
            
            'RHOB':  ['RHOB', 'RHOZ', 'DEN', 'DENSITY', 'ZDEN'],
            
            # Neutron porosity: CN dan CNC umum dipakai sebagai mnemonic neutron porosity
            'NPHI':  ['NPHI', 'TNPH', 'NEU', 'NEUTRON', 'NPOR', 'PHIN', 'CN', 'CNC', 'SNP'],
            
            'DT':    ['DT', 'DTC', 'AC', 'SONIC', 'DTCO'],
            
            # Deep resistivity: RILD termasuk alias RT/ILD (deep)
            'RT':    ['RT', 'LLD', 'ILD', 'RD', 'RESD', 'LLG', 'RILD', 'RDEEP'],
            
            # Medium resistivity: RILM = medium induction resistivity
            'RM':    ['RM', 'RILM', 'RMED', 'RIM'],
            
            # Shallow resistivity
            'RS':    ['RS', 'LLS', 'ILS', 'RESS', 'RXOZ', 'RSHALLOW'],
            
            'DEPTH': ['DEPTH', 'DEPT', 'MD', 'TVD', 'TDEP'],
            
            'SP':    ['SP', 'SSP', 'SPONT'],
            
            'CALI':  ['CALI', 'CAL', 'CALIPER', 'HCAL'],
            
            # Density correction: ZCOR umum dipakai sebagai bulk density correction
            'DRHO':  ['DRHO', 'DPHI_CORR', 'DCOR', 'ZCOR', 'ZCORR'],
            
            'PEF':   ['PEF', 'PE', 'PEFZ'],
            
            # Spectral gamma components
            'K':     ['K', 'POTA', 'POTASSIUM'],
            'TH':    ['TH', 'THOR', 'THORIUM'],
            'U':     ['U', 'URAN', 'URANIUM'],
            'KTH':   ['KTH'],  # GR minus Uranium
            
            # Other curves
            'SPD':   ['SPD'],
            'TTEN':  ['TTEN'],
        }
        
        if curve_type not in curve_aliases:
            return None
            
        available = self.get_available_curves()
        for alias in curve_aliases[curve_type]:
            if alias in available:
                return alias
            # Case insensitive search
            for curve in available:
                if curve.upper() == alias.upper():
                    return curve
        return None


def load_las_file(file_path: str) -> Optional[LASParser]:
    """
    Convenience function to load a LAS file.
    
    Args:
        file_path: Path to the LAS file
        
    Returns:
        LASParser object if successful, None otherwise
    """
    parser = LASParser()
    if parser.read_las(file_path):
        return parser
    return None


def load_las_from_buffer(file_buffer) -> Optional[LASParser]:
    """
    Convenience function to load a LAS file from buffer.
    
    Args:
        file_buffer: File buffer object
        
    Returns:
        LASParser object if successful, None otherwise
    """
    parser = LASParser()
    if parser.read_las_from_buffer(file_buffer):
        return parser
    return None
