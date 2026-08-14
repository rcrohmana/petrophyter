"""
Session Service for Petrophyter PyQt
Manages saving and loading of analysis sessions.
"""

import copy
import json
import logging
import os
import tempfile
from typing import Dict, Any, Optional
from PyQt6.QtCore import QObject, pyqtSignal


logger = logging.getLogger(__name__)

_SESSION_DEFAULTS = {
    "analysis_mode": "Whole Well",
    "selected_formations": [],
    "curve_mapping": {"GR": "None", "RHOB": "None", "NPHI": "None", "DT": "None", "RT": "None"},
    "vsh_baseline_method": "Statistically (Auto)",
    "gr_min_manual": 20.0,
    "gr_max_manual": 120.0,
    "vsh_methods": ["Linear"],
    "rho_matrix": 2.65,
    "dt_matrix": 55.5,
    # Optional explicit matrix neutron response; absent/None preserves the
    # lithology-derived default used by older sessions.
    "nphi_matrix": None,
    "rho_fluid": 1.0,
    "dt_fluid": 189.0,
    "shale_approach": "Custom (Manual)",
    "rho_shale": 2.45,
    "dt_shale": 100.0,
    "nphi_shale": 0.35,
    "shale_vsh_threshold": 0.80,
    "shale_gate_logs": True,
    "shale_iqr_filter": True,
    "shale_selection_mode": "fixed_threshold",
    "shale_vsh_quantile": 0.90,
    "shale_min_points": 50,
    "shale_sweep_tmin": 0.65,
    "shale_sweep_tmax": 0.95,
    "shale_sweep_step": 0.02,
    "primary_phie_method": "PHIE_DN",
    "lithology_preset": "Sandstone (Humble)",
    "a": 0.62,
    "m": 2.15,
    "n": 2.0,
    "rw": 0.05,
    "rsh": 5.0,
    "perm_C": 8581.0,
    "perm_P": 4.4,
    "perm_Q": 2.0,
    "swirr_method": "Hierarchical (Recommended)",
    "buckles_preset": "Sandstone (Clean)",
    "k_buckles": 0.02,
    "vsh_cutoff": 0.4,
    "phi_cutoff": 0.08,
    "sw_cutoff": 0.6,
    "sw_methods": ["Simandoux"],
    "sw_primary_method": "Simandoux",
    "ws_qv": 0.2,
    "ws_b": 1.0,
    "dw_swb": 0.1,
    "dw_rwb": 0.2,
    "merge_step": 0.5,
    "merge_gap_limit": 5.0,
    "core_depth_unit": "Auto",
    "core_max_dist": 2.0,
    "gas_correction_enabled": False,
    "gas_nphi_factor": 0.30,
    "gas_rhob_factor": 0.15,
}


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
    SESSION_VERSION = "1.3"
    SESSION_FIELDS = tuple(_SESSION_DEFAULTS)
    
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
        temporary_path = None
        try:
            session_data = self._model_to_dict(model)
            session_data["_session_version"] = self.SESSION_VERSION
            session_data["_las_filename"] = getattr(model, "las_filename", "")

            directory = os.path.dirname(os.path.abspath(file_path)) or "."
            fd, temporary_path = tempfile.mkstemp(
                prefix=f".{os.path.basename(file_path)}.",
                suffix=".tmp",
                dir=directory,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(session_data, handle, indent=2, ensure_ascii=False)
            os.replace(temporary_path, file_path)
            temporary_path = None

            self.session_saved.emit(file_path)
            return True

        except Exception as e:
            logger.exception("Failed to save session")
            self.error.emit(f"Failed to save session: {str(e)}")
            return False
        finally:
            if temporary_path:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass
    
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
            
            # Check version compatibility while keeping older parameter-only
            # sessions loadable; unknown fields are simply ignored below.
            version = session_data.get("_session_version", "1.0")
            if version != self.SESSION_VERSION:
                logger.warning(
                    "Session version %s differs from current version %s; "
                    "loading compatible fields",
                    version,
                    self.SESSION_VERSION,
                )
            
            self.session_loaded.emit(session_data)
            return session_data
            
        except Exception as e:
            logger.exception("Failed to load session")
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
            if 'nphi_matrix' in session_data:
                model.nphi_matrix = session_data['nphi_matrix']
            
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

            # Fields introduced after the original 1.2 schema.
            for field in (
                "curve_mapping",
                "primary_phie_method",
                "shale_vsh_threshold",
                "shale_gate_logs",
                "shale_iqr_filter",
                "shale_selection_mode",
                "shale_vsh_quantile",
                "shale_min_points",
                "shale_sweep_tmin",
                "shale_sweep_tmax",
                "shale_sweep_step",
            ):
                if field in session_data:
                    setattr(model, field, session_data[field])
            if "_las_filename" in session_data and hasattr(model, "las_filename"):
                model.las_filename = session_data["_las_filename"]

            return True

        except Exception as e:
            logger.exception("Failed to apply session")
            self.error.emit(f"Failed to apply session: {str(e)}")
            return False
    
    def _model_to_dict(self, model) -> Dict[str, Any]:
        """Convert known model parameters, tolerating older/minimal models."""
        return {
            field: copy.deepcopy(getattr(model, field, default))
            for field, default in _SESSION_DEFAULTS.items()
        }
