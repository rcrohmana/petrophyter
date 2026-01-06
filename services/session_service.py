"""
Session Service for Petrophyter PyQt
Manages saving and loading of analysis sessions.
"""

import json
import os
from typing import Dict, Any, Optional
from PyQt6.QtCore import QObject, pyqtSignal


class SessionService(QObject):
    """
    Service for saving and loading analysis sessions.
    
    Saves all parameter values to JSON file so users don't need
    to re-enter parameters when reopening the application.
    """
    
    session_saved = pyqtSignal(str)  # file path
    session_loaded = pyqtSignal(dict)  # parameters
    error = pyqtSignal(str)
    
    # Session file version for compatibility
    SESSION_VERSION = "1.2"
    
    def __init__(self, parent=None):
        super().__init__(parent)
    
    def save_session(self, model, file_path: str) -> bool:
        """
        Save current session parameters to JSON file.
        
        Args:
            model: AppModel instance with all parameters
            file_path: Path to save the session file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            session_data = self._model_to_dict(model)
            session_data['_session_version'] = self.SESSION_VERSION
            session_data['_las_filename'] = model.las_filename
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, indent=2, ensure_ascii=False)
            
            self.session_saved.emit(file_path)
            return True
            
        except Exception as e:
            self.error.emit(f"Failed to save session: {str(e)}")
            return False
    
    def load_session(self, file_path: str) -> Optional[Dict]:
        """
        Load session parameters from JSON file.
        
        Args:
            file_path: Path to the session file
            
        Returns:
            Dictionary with session parameters, or None if failed
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                session_data = json.load(f)
            
            # Check version compatibility
            version = session_data.get('_session_version', '1.0')
            if version != self.SESSION_VERSION:
                # Future: migration logic here
                pass
            
            self.session_loaded.emit(session_data)
            return session_data
            
        except Exception as e:
            self.error.emit(f"Failed to load session: {str(e)}")
            return None
    
    def apply_session_to_model(self, model, session_data: Dict) -> bool:
        """
        Apply loaded session data to AppModel.
        
        Args:
            model: AppModel instance
            session_data: Dictionary from load_session
            
        Returns:
            True if successful
        """
        try:
            # Analysis mode
            if 'analysis_mode' in session_data:
                model.analysis_mode = session_data['analysis_mode']
            if 'selected_formations' in session_data:
                model.selected_formations = session_data['selected_formations']
            
            # VShale parameters
            if 'vsh_baseline_method' in session_data:
                model.vsh_baseline_method = session_data['vsh_baseline_method']
            if 'gr_min_manual' in session_data:
                model.gr_min_manual = session_data['gr_min_manual']
            if 'gr_max_manual' in session_data:
                model.gr_max_manual = session_data['gr_max_manual']
            if 'vsh_methods' in session_data:
                model.vsh_methods = session_data['vsh_methods']
            
            # Matrix parameters
            if 'rho_matrix' in session_data:
                model.rho_matrix = session_data['rho_matrix']
            if 'dt_matrix' in session_data:
                model.dt_matrix = session_data['dt_matrix']
            
            # Fluid parameters
            if 'rho_fluid' in session_data:
                model.rho_fluid = session_data['rho_fluid']
            if 'dt_fluid' in session_data:
                model.dt_fluid = session_data['dt_fluid']
            
            # Shale parameters
            if 'shale_approach' in session_data:
                model.shale_approach = session_data['shale_approach']
            if 'rho_shale' in session_data:
                model.rho_shale = session_data['rho_shale']
            if 'dt_shale' in session_data:
                model.dt_shale = session_data['dt_shale']
            if 'nphi_shale' in session_data:
                model.nphi_shale = session_data['nphi_shale']
            
            # Archie parameters
            if 'lithology_preset' in session_data:
                model.lithology_preset = session_data['lithology_preset']
            if 'a' in session_data:
                model.a = session_data['a']
            if 'm' in session_data:
                model.m = session_data['m']
            if 'n' in session_data:
                model.n = session_data['n']
            
            # Resistivity parameters
            if 'rw' in session_data:
                model.rw = session_data['rw']
            if 'rsh' in session_data:
                model.rsh = session_data['rsh']
            
            # Permeability parameters
            if 'perm_C' in session_data:
                model.perm_C = session_data['perm_C']
            if 'perm_P' in session_data:
                model.perm_P = session_data['perm_P']
            if 'perm_Q' in session_data:
                model.perm_Q = session_data['perm_Q']
            
            # Swirr parameters
            if 'swirr_method' in session_data:
                model.swirr_method = session_data['swirr_method']
            if 'buckles_preset' in session_data:
                model.buckles_preset = session_data['buckles_preset']
            if 'k_buckles' in session_data:
                model.k_buckles = session_data['k_buckles']
            
            # Cutoff parameters
            if 'vsh_cutoff' in session_data:
                model.vsh_cutoff = session_data['vsh_cutoff']
            if 'phi_cutoff' in session_data:
                model.phi_cutoff = session_data['phi_cutoff']
            if 'sw_cutoff' in session_data:
                model.sw_cutoff = session_data['sw_cutoff']
            
            # Sw Parameters
            if 'sw_methods' in session_data: model.sw_methods = session_data['sw_methods']
            if 'sw_primary_method' in session_data: model.sw_primary_method = session_data['sw_primary_method']
            if 'ws_qv' in session_data: model.ws_qv = session_data['ws_qv']
            if 'ws_b' in session_data: model.ws_b = session_data['ws_b']
            if 'dw_swb' in session_data: model.dw_swb = session_data['dw_swb']
            if 'dw_rwb' in session_data: model.dw_rwb = session_data['dw_rwb']
            
            # Merge settings
            if 'merge_step' in session_data:
                model.merge_step = session_data['merge_step']
            if 'merge_gap_limit' in session_data:
                model.merge_gap_limit = session_data['merge_gap_limit']
            
            # Core settings
            if 'core_depth_unit' in session_data:
                model.core_depth_unit = session_data['core_depth_unit']
            if 'core_max_dist' in session_data:
                model.core_max_dist = session_data['core_max_dist']
            
            # Gas correction (v1.2)
            if 'gas_correction_enabled' in session_data:
                model.gas_correction_enabled = session_data['gas_correction_enabled']
            if 'gas_nphi_factor' in session_data:
                model.gas_nphi_factor = session_data['gas_nphi_factor']
            if 'gas_rhob_factor' in session_data:
                model.gas_rhob_factor = session_data['gas_rhob_factor']
            
            return True
            
        except Exception as e:
            self.error.emit(f"Failed to apply session: {str(e)}")
            return False
    
    def _model_to_dict(self, model) -> Dict[str, Any]:
        """Convert model parameters to dictionary for saving."""
        return {
            # Analysis mode
            'analysis_mode': model.analysis_mode,
            'selected_formations': model.selected_formations,
            
            # VShale parameters
            'vsh_baseline_method': model.vsh_baseline_method,
            'gr_min_manual': model.gr_min_manual,
            'gr_max_manual': model.gr_max_manual,
            'vsh_methods': model.vsh_methods,
            
            # Matrix parameters
            'rho_matrix': model.rho_matrix,
            'dt_matrix': model.dt_matrix,
            
            # Fluid parameters
            'rho_fluid': model.rho_fluid,
            'dt_fluid': model.dt_fluid,
            
            # Shale parameters
            'shale_approach': model.shale_approach,
            'rho_shale': model.rho_shale,
            'dt_shale': model.dt_shale,
            'nphi_shale': model.nphi_shale,
            
            # Archie parameters
            'lithology_preset': model.lithology_preset,
            'a': model.a,
            'm': model.m,
            'n': model.n,
            
            # Resistivity parameters
            'rw': model.rw,
            'rsh': model.rsh,
            
            # Permeability parameters
            'perm_C': model.perm_C,
            'perm_P': model.perm_P,
            'perm_Q': model.perm_Q,
            
            # Swirr parameters
            'swirr_method': model.swirr_method,
            'buckles_preset': model.buckles_preset,
            'k_buckles': model.k_buckles,
            
            # Cutoff parameters
            'vsh_cutoff': model.vsh_cutoff,
            'phi_cutoff': model.phi_cutoff,
            'sw_cutoff': model.sw_cutoff,
            
            # Sw Parameters
            'sw_methods': model.sw_methods,
            'sw_primary_method': model.sw_primary_method,
            'ws_qv': model.ws_qv,
            'ws_b': model.ws_b,
            'dw_swb': model.dw_swb,
            'dw_rwb': model.dw_rwb,
            
            # Merge settings
            'merge_step': model.merge_step,
            'merge_gap_limit': model.merge_gap_limit,
            
            # Core settings
            'core_depth_unit': model.core_depth_unit,
            'core_max_dist': model.core_max_dist,
            
            # Gas correction (v1.2)
            'gas_correction_enabled': model.gas_correction_enabled,
            'gas_nphi_factor': model.gas_nphi_factor,
            'gas_rhob_factor': model.gas_rhob_factor,
        }
