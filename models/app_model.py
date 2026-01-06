"""
Application Model for Petrophyter PyQt
Replaces Streamlit's st.session_state with a Qt-based reactive model.
"""

from PyQt6.QtCore import QObject, pyqtSignal
import pandas as pd
from typing import Dict, List, Optional, Any


class AppModel(QObject):
    """
    Central application state model.
    
    This class replaces st.session_state from Streamlit.
    Uses Qt signals for reactive UI updates.
    """
    
    # Signals for state changes
    data_loaded = pyqtSignal()
    analysis_complete = pyqtSignal()
    parameters_changed = pyqtSignal()
    merge_complete = pyqtSignal()
    core_data_loaded = pyqtSignal()
    formation_tops_loaded = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # =====================================================================
        # DATA STORAGE
        # =====================================================================
        self._las_data: Optional[pd.DataFrame] = None
        self._las_parser = None
        self._las_filename: str = ""
        self._qc_report = None
        self._results: Optional[pd.DataFrame] = None
        self._summary: Optional[Dict] = None
        self._formation_tops = None
        self._core_data = None
        self._merge_report = None
        self._calculated: bool = False
        
        # =====================================================================
        # CURVE MAPPING
        # =====================================================================
        self._curve_mapping: Dict[str, str] = {
            'GR': 'None',
            'RHOB': 'None',
            'NPHI': 'None',
            'DT': 'None',
            'RT': 'None'
        }
        
        # =====================================================================
        # ANALYSIS MODE
        # =====================================================================
        self._analysis_mode: str = "Whole Well"
        self._selected_formations: List[str] = []
        
        # =====================================================================
        # VSHALE PARAMETERS
        # =====================================================================
        self._vsh_baseline_method: str = "Statistically (Auto)"
        self._gr_min_manual: float = 20.0
        self._gr_max_manual: float = 120.0
        self._vsh_methods: List[str] = ["Linear"]
        
        # =====================================================================
        # MATRIX PARAMETERS
        # =====================================================================
        self._rho_matrix: float = 2.65
        self._dt_matrix: float = 55.5
        
        # =====================================================================
        # FLUID PARAMETERS
        # =====================================================================
        self._rho_fluid: float = 1.0
        self._dt_fluid: float = 189.0
        
        # =====================================================================
        # SHALE PARAMETERS
        # =====================================================================
        self._shale_approach: str = "Custom (Manual)"
        self._rho_shale: float = 2.45
        self._dt_shale: float = 100.0
        self._nphi_shale: float = 0.35
        self._shale_method_used: str = "custom"
        self._calculated_shale: Optional[Dict] = None
        # Shale estimation settings (v2.0)
        self._shale_vsh_threshold: float = 0.80  # Min VSH to be considered "pure shale"
        self._shale_gate_logs: bool = True       # Apply RHOB/NPHI/DT range gating
        self._shale_iqr_filter: bool = True      # Apply IQR outlier filtering
        # Adaptive shale threshold settings (v2.1)
        self._shale_selection_mode: str = "fixed_threshold"  # fixed_threshold/quantile/stability_sweep
        self._shale_vsh_quantile: float = 0.90   # Quantile for quantile mode
        self._shale_min_points: int = 50         # Minimum shale points required
        self._shale_sweep_tmin: float = 0.65     # Sweep mode: min threshold
        self._shale_sweep_tmax: float = 0.95     # Sweep mode: max threshold
        self._shale_sweep_step: float = 0.02     # Sweep mode: step size
        
        # =====================================================================
        # ARCHIE PARAMETERS
        # =====================================================================
        self._lithology_preset: str = "Sandstone (Humble)"
        self._a: float = 0.62
        self._m: float = 2.15
        self._n: float = 2.0
        
        # =====================================================================
        # RESISTIVITY PARAMETERS
        # =====================================================================
        self._rw: float = 0.05
        self._rsh: float = 5.0
        self._calculated_rw: Optional[float] = None
        self._calculated_rsh: Optional[float] = None
        
        # =====================================================================
        # PERMEABILITY COEFFICIENTS
        # =====================================================================
        self._perm_C: float = 8581.0
        self._perm_P: float = 4.4
        self._perm_Q: float = 2.0
        self._calculated_C: Optional[float] = None
        self._calculated_P: Optional[float] = None
        self._calculated_Q: Optional[float] = None
        
        # =====================================================================
        # SWIRR ESTIMATION
        # =====================================================================
        self._swirr_method: str = "Hierarchical (Recommended)"
        self._buckles_preset: str = "Sandstone (Clean)"
        self._k_buckles: float = 0.02
        
        # =====================================================================
        # CUTOFF PARAMETERS
        # =====================================================================
        self._vsh_cutoff: float = 0.4
        self._phi_cutoff: float = 0.08
        self._sw_cutoff: float = 0.6
        
        # =====================================================================
        # WATER SATURATION MODELS
        # =====================================================================
        self._sw_methods: List[str] = ["Simandoux"]
        self._sw_primary_method: str = "Simandoux"
        self._ws_qv: float = 0.2
        self._ws_b: float = 1.0
        self._dw_swb: float = 0.1
        self._dw_rwb: float = 0.2
        
        # =====================================================================
        # MERGE SETTINGS
        # =====================================================================
        self._merge_step: float = 0.5
        self._merge_gap_limit: float = 5.0
        
        # =====================================================================
        # CORE DATA SETTINGS
        # =====================================================================
        self._core_depth_unit: str = "Auto"
        self._core_max_dist: float = 2.0
        
        # =====================================================================
        # GAS CORRECTION PARAMETERS (v1.2)
        # =====================================================================
        self._gas_correction_enabled: bool = False
        self._gas_nphi_factor: float = 0.30  # Neutron correction (0.2-0.4 typical)
        self._gas_rhob_factor: float = 0.15  # Density correction (0.1-0.2 typical)
    
    # =========================================================================
    # PROPERTIES - DATA
    # =========================================================================
    @property
    def las_data(self) -> Optional[pd.DataFrame]:
        return self._las_data
    
    @las_data.setter
    def las_data(self, value: Optional[pd.DataFrame]):
        self._las_data = value
        if value is not None:
            self.data_loaded.emit()
    
    @property
    def las_parser(self):
        return self._las_parser
    
    @las_parser.setter
    def las_parser(self, value):
        self._las_parser = value
    
    @property
    def las_filename(self) -> str:
        return self._las_filename
    
    @las_filename.setter
    def las_filename(self, value: str):
        self._las_filename = value
    
    @property
    def qc_report(self):
        return self._qc_report
    
    @qc_report.setter
    def qc_report(self, value):
        self._qc_report = value
    
    @property
    def results(self) -> Optional[pd.DataFrame]:
        return self._results
    
    @results.setter
    def results(self, value: Optional[pd.DataFrame]):
        self._results = value
        if value is not None:
            self._calculated = True
            self.analysis_complete.emit()
    
    @property
    def summary(self) -> Optional[Dict]:
        return self._summary
    
    @summary.setter
    def summary(self, value: Optional[Dict]):
        self._summary = value
    
    @property
    def formation_tops(self):
        return self._formation_tops
    
    @formation_tops.setter
    def formation_tops(self, value):
        self._formation_tops = value
        if value is not None:
            self.formation_tops_loaded.emit()
    
    @property
    def core_data(self):
        return self._core_data
    
    @core_data.setter
    def core_data(self, value):
        self._core_data = value
        if value is not None:
            self.core_data_loaded.emit()
    
    @property
    def merge_report(self):
        return self._merge_report
    
    @merge_report.setter
    def merge_report(self, value):
        self._merge_report = value
        if value is not None:
            self.merge_complete.emit()
    
    @property
    def calculated(self) -> bool:
        return self._calculated
    
    @calculated.setter
    def calculated(self, value: bool):
        self._calculated = value
    
    # =========================================================================
    # PROPERTIES - CURVE MAPPING
    # =========================================================================
    @property
    def curve_mapping(self) -> Dict[str, str]:
        return self._curve_mapping
    
    @curve_mapping.setter
    def curve_mapping(self, value: Dict[str, str]):
        self._curve_mapping = value
        self.parameters_changed.emit()
    
    def set_curve_mapping(self, curve_type: str, curve_name: str):
        """Set a single curve mapping."""
        self._curve_mapping[curve_type] = curve_name
        self.parameters_changed.emit()
    
    # =========================================================================
    # PROPERTIES - ANALYSIS MODE
    # =========================================================================
    @property
    def analysis_mode(self) -> str:
        return self._analysis_mode
    
    @analysis_mode.setter
    def analysis_mode(self, value: str):
        self._analysis_mode = value
        self.parameters_changed.emit()
    
    @property
    def selected_formations(self) -> List[str]:
        return self._selected_formations
    
    @selected_formations.setter
    def selected_formations(self, value: List[str]):
        self._selected_formations = value
        self.parameters_changed.emit()
    
    # =========================================================================
    # PROPERTIES - VSHALE
    # =========================================================================
    @property
    def vsh_baseline_method(self) -> str:
        return self._vsh_baseline_method
    
    @vsh_baseline_method.setter
    def vsh_baseline_method(self, value: str):
        self._vsh_baseline_method = value
    
    @property
    def gr_min_manual(self) -> float:
        return self._gr_min_manual
    
    @gr_min_manual.setter
    def gr_min_manual(self, value: float):
        self._gr_min_manual = value
    
    @property
    def gr_max_manual(self) -> float:
        return self._gr_max_manual
    
    @gr_max_manual.setter
    def gr_max_manual(self, value: float):
        self._gr_max_manual = value
    
    @property
    def vsh_methods(self) -> List[str]:
        return self._vsh_methods
    
    @vsh_methods.setter
    def vsh_methods(self, value: List[str]):
        self._vsh_methods = value
    
    # =========================================================================
    # PROPERTIES - MATRIX
    # =========================================================================
    @property
    def rho_matrix(self) -> float:
        return self._rho_matrix
    
    @rho_matrix.setter
    def rho_matrix(self, value: float):
        self._rho_matrix = value
    
    @property
    def dt_matrix(self) -> float:
        return self._dt_matrix
    
    @dt_matrix.setter
    def dt_matrix(self, value: float):
        self._dt_matrix = value
    
    # =========================================================================
    # PROPERTIES - FLUID
    # =========================================================================
    @property
    def rho_fluid(self) -> float:
        return self._rho_fluid
    
    @rho_fluid.setter
    def rho_fluid(self, value: float):
        self._rho_fluid = value
    
    @property
    def dt_fluid(self) -> float:
        return self._dt_fluid
    
    @dt_fluid.setter
    def dt_fluid(self, value: float):
        self._dt_fluid = value
    
    # =========================================================================
    # PROPERTIES - SHALE
    # =========================================================================
    @property
    def shale_approach(self) -> str:
        return self._shale_approach
    
    @shale_approach.setter
    def shale_approach(self, value: str):
        self._shale_approach = value
    
    @property
    def rho_shale(self) -> float:
        return self._rho_shale
    
    @rho_shale.setter
    def rho_shale(self, value: float):
        self._rho_shale = value
    
    @property
    def dt_shale(self) -> float:
        return self._dt_shale
    
    @dt_shale.setter
    def dt_shale(self, value: float):
        self._dt_shale = value
    
    @property
    def nphi_shale(self) -> float:
        return self._nphi_shale
    
    @nphi_shale.setter
    def nphi_shale(self, value: float):
        self._nphi_shale = value
    
    @property
    def shale_method_used(self) -> str:
        return self._shale_method_used
    
    @shale_method_used.setter
    def shale_method_used(self, value: str):
        self._shale_method_used = value
    
    @property
    def calculated_shale(self) -> Optional[Dict]:
        return self._calculated_shale
    
    @calculated_shale.setter
    def calculated_shale(self, value: Optional[Dict]):
        self._calculated_shale = value
    
    @property
    def shale_vsh_threshold(self) -> float:
        return self._shale_vsh_threshold
    
    @shale_vsh_threshold.setter
    def shale_vsh_threshold(self, value: float):
        self._shale_vsh_threshold = value
    
    @property
    def shale_gate_logs(self) -> bool:
        return self._shale_gate_logs
    
    @shale_gate_logs.setter
    def shale_gate_logs(self, value: bool):
        self._shale_gate_logs = value
    
    @property
    def shale_iqr_filter(self) -> bool:
        return self._shale_iqr_filter
    
    @shale_iqr_filter.setter
    def shale_iqr_filter(self, value: bool):
        self._shale_iqr_filter = value
    
    @property
    def shale_selection_mode(self) -> str:
        return self._shale_selection_mode
    
    @shale_selection_mode.setter
    def shale_selection_mode(self, value: str):
        self._shale_selection_mode = value
    
    @property
    def shale_vsh_quantile(self) -> float:
        return self._shale_vsh_quantile
    
    @shale_vsh_quantile.setter
    def shale_vsh_quantile(self, value: float):
        self._shale_vsh_quantile = value
    
    @property
    def shale_min_points(self) -> int:
        return self._shale_min_points
    
    @shale_min_points.setter
    def shale_min_points(self, value: int):
        self._shale_min_points = value
    
    @property
    def shale_sweep_tmin(self) -> float:
        return self._shale_sweep_tmin
    
    @shale_sweep_tmin.setter
    def shale_sweep_tmin(self, value: float):
        self._shale_sweep_tmin = value
    
    @property
    def shale_sweep_tmax(self) -> float:
        return self._shale_sweep_tmax
    
    @shale_sweep_tmax.setter
    def shale_sweep_tmax(self, value: float):
        self._shale_sweep_tmax = value
    
    @property
    def shale_sweep_step(self) -> float:
        return self._shale_sweep_step
    
    @shale_sweep_step.setter
    def shale_sweep_step(self, value: float):
        self._shale_sweep_step = value
    
    # =========================================================================
    # PROPERTIES - ARCHIE
    # =========================================================================
    @property
    def lithology_preset(self) -> str:
        return self._lithology_preset
    
    @lithology_preset.setter
    def lithology_preset(self, value: str):
        self._lithology_preset = value
    
    @property
    def a(self) -> float:
        return self._a
    
    @a.setter
    def a(self, value: float):
        self._a = value
    
    @property
    def m(self) -> float:
        return self._m
    
    @m.setter
    def m(self, value: float):
        self._m = value
    
    @property
    def n(self) -> float:
        return self._n
    
    @n.setter
    def n(self, value: float):
        self._n = value
    
    # =========================================================================
    # PROPERTIES - RESISTIVITY
    # =========================================================================
    @property
    def rw(self) -> float:
        return self._rw
    
    @rw.setter
    def rw(self, value: float):
        self._rw = value
    
    @property
    def rsh(self) -> float:
        return self._rsh
    
    @rsh.setter
    def rsh(self, value: float):
        self._rsh = value
    
    @property
    def calculated_rw(self) -> Optional[float]:
        return self._calculated_rw
    
    @calculated_rw.setter
    def calculated_rw(self, value: Optional[float]):
        self._calculated_rw = value
    
    @property
    def calculated_rsh(self) -> Optional[float]:
        return self._calculated_rsh
    
    @calculated_rsh.setter
    def calculated_rsh(self, value: Optional[float]):
        self._calculated_rsh = value
    
    # =========================================================================
    # PROPERTIES - PERMEABILITY
    # =========================================================================
    @property
    def perm_C(self) -> float:
        return self._perm_C
    
    @perm_C.setter
    def perm_C(self, value: float):
        self._perm_C = value
    
    @property
    def perm_P(self) -> float:
        return self._perm_P
    
    @perm_P.setter
    def perm_P(self, value: float):
        self._perm_P = value
    
    @property
    def perm_Q(self) -> float:
        return self._perm_Q
    
    @perm_Q.setter
    def perm_Q(self, value: float):
        self._perm_Q = value
    
    @property
    def calculated_C(self) -> Optional[float]:
        return self._calculated_C
    
    @calculated_C.setter
    def calculated_C(self, value: Optional[float]):
        self._calculated_C = value
    
    @property
    def calculated_P(self) -> Optional[float]:
        return self._calculated_P
    
    @calculated_P.setter
    def calculated_P(self, value: Optional[float]):
        self._calculated_P = value
    
    @property
    def calculated_Q(self) -> Optional[float]:
        return self._calculated_Q
    
    @calculated_Q.setter
    def calculated_Q(self, value: Optional[float]):
        self._calculated_Q = value
    
    # =========================================================================
    # PROPERTIES - SWIRR
    # =========================================================================
    @property
    def swirr_method(self) -> str:
        return self._swirr_method
    
    @swirr_method.setter
    def swirr_method(self, value: str):
        self._swirr_method = value
    
    @property
    def buckles_preset(self) -> str:
        return self._buckles_preset
    
    @buckles_preset.setter
    def buckles_preset(self, value: str):
        self._buckles_preset = value
    
    @property
    def k_buckles(self) -> float:
        return self._k_buckles
    
    @k_buckles.setter
    def k_buckles(self, value: float):
        self._k_buckles = value
    
    # =========================================================================
    # PROPERTIES - CUTOFFS
    # =========================================================================
    @property
    def vsh_cutoff(self) -> float:
        return self._vsh_cutoff
    
    @vsh_cutoff.setter
    def vsh_cutoff(self, value: float):
        self._vsh_cutoff = value
    
    @property
    def phi_cutoff(self) -> float:
        return self._phi_cutoff
    
    @phi_cutoff.setter
    def phi_cutoff(self, value: float):
        self._phi_cutoff = value
    
    @property
    def sw_cutoff(self) -> float:
        return self._sw_cutoff
    
    @sw_cutoff.setter
    def sw_cutoff(self, value: float):
        self._sw_cutoff = value
    
    # =========================================================================
    # PROPERTIES - WATER SATURATION MODELS
    # =========================================================================
    @property
    def sw_methods(self) -> List[str]:
        return self._sw_methods
    
    @sw_methods.setter
    def sw_methods(self, value: List[str]):
        self._sw_methods = value
    
    @property
    def sw_primary_method(self) -> str:
        return self._sw_primary_method
    
    @sw_primary_method.setter
    def sw_primary_method(self, value: str):
        self._sw_primary_method = value
    
    @property
    def ws_qv(self) -> float:
        return self._ws_qv
    
    @ws_qv.setter
    def ws_qv(self, value: float):
        self._ws_qv = value
    
    @property
    def ws_b(self) -> float:
        return self._ws_b
    
    @ws_b.setter
    def ws_b(self, value: float):
        self._ws_b = value
    
    @property
    def dw_swb(self) -> float:
        return self._dw_swb
    
    @dw_swb.setter
    def dw_swb(self, value: float):
        self._dw_swb = value
    
    @property
    def dw_rwb(self) -> float:
        return self._dw_rwb
    
    @dw_rwb.setter
    def dw_rwb(self, value: float):
        self._dw_rwb = value
    
    # =========================================================================
    # PROPERTIES - MERGE SETTINGS
    # =========================================================================
    @property
    def merge_step(self) -> float:
        return self._merge_step
    
    @merge_step.setter
    def merge_step(self, value: float):
        self._merge_step = value
    
    @property
    def merge_gap_limit(self) -> float:
        return self._merge_gap_limit
    
    @merge_gap_limit.setter
    def merge_gap_limit(self, value: float):
        self._merge_gap_limit = value
    
    # =========================================================================
    # PROPERTIES - CORE DATA SETTINGS
    # =========================================================================
    @property
    def core_depth_unit(self) -> str:
        return self._core_depth_unit
    
    @core_depth_unit.setter
    def core_depth_unit(self, value: str):
        self._core_depth_unit = value
    
    @property
    def core_max_dist(self) -> float:
        return self._core_max_dist
    
    @core_max_dist.setter
    def core_max_dist(self, value: float):
        self._core_max_dist = value
    
    # =========================================================================
    # PROPERTIES - GAS CORRECTION (v1.2)
    # =========================================================================
    @property
    def gas_correction_enabled(self) -> bool:
        return self._gas_correction_enabled
    
    @gas_correction_enabled.setter
    def gas_correction_enabled(self, value: bool):
        self._gas_correction_enabled = value
    
    @property
    def gas_nphi_factor(self) -> float:
        return self._gas_nphi_factor
    
    @gas_nphi_factor.setter
    def gas_nphi_factor(self, value: float):
        self._gas_nphi_factor = value
    
    @property
    def gas_rhob_factor(self) -> float:
        return self._gas_rhob_factor
    
    @gas_rhob_factor.setter
    def gas_rhob_factor(self, value: float):
        self._gas_rhob_factor = value
    
    # =========================================================================
    # METHODS
    # =========================================================================
    def reset(self):
        """Reset all data (keep parameters)."""
        self._las_data = None
        self._las_parser = None
        self._las_filename = ""
        self._qc_report = None
        self._results = None
        self._summary = None
        self._formation_tops = None
        self._core_data = None
        self._merge_report = None
        self._calculated = False
        self._curve_mapping = {
            'GR': 'None',
            'RHOB': 'None',
            'NPHI': 'None',
            'DT': 'None',
            'RT': 'None'
        }
    
    def get_available_curves(self) -> List[str]:
        """Get list of available curves from loaded LAS data."""
        if self._las_parser is not None:
            return self._las_parser.get_available_curves()
        return []
    
    def get_formation_list(self) -> List[str]:
        """Get list of formation names."""
        if self._formation_tops is not None:
            return self._formation_tops.get_formation_list()
        return []
