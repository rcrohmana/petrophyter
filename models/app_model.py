"""
Application Model for Petrophyter PyQt
Replaces Streamlit's st.session_state with a Qt-based reactive model.
"""

import copy
from PyQt6.QtCore import QObject, pyqtSignal
import pandas as pd
from typing import Dict, List, Optional, Any

from models.project import Project, WellDataset, default_curve_mapping, make_well_key, display_name_for

SCOPE_PROJECT, SCOPE_WELL = "project", "well"


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
    # Parameter scopes (spec §4): the edited scope changed, or an entry
    # changed (argument: the affected well key, "" for project scopes).
    scope_changed = pyqtSignal()
    scoped_params_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        # Wells live in the project; the well-scoped properties below are a
        # facade over the active well. Without wells they read and write a
        # scratch dataset, which becomes a real well once data is assigned.
        self.project = Project(self)
        self._scratch = WellDataset()

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
        # None means derive the neutron matrix response from the selected
        # lithology preset; explicit values support calibrated/custom sessions.
        self._nphi_matrix: Optional[float] = None

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
        # Shale estimation settings (v2.0)
        self._shale_vsh_threshold: float = 0.80  # Min VSH to be considered "pure shale"
        self._shale_gate_logs: bool = True  # Apply RHOB/NPHI/DT range gating
        self._shale_iqr_filter: bool = True  # Apply IQR outlier filtering
        # Adaptive shale threshold settings (v2.1)
        self._shale_selection_mode: str = (
            "fixed_threshold"  # fixed_threshold/quantile/stability_sweep
        )
        self._shale_vsh_quantile: float = 0.90  # Quantile for quantile mode
        self._shale_min_points: int = 50  # Minimum shale points required
        self._shale_sweep_tmin: float = 0.65  # Sweep mode: min threshold
        self._shale_sweep_tmax: float = 0.95  # Sweep mode: max threshold
        self._shale_sweep_step: float = 0.02  # Sweep mode: step size

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
        # "manual" uses the value above; "auto" estimates it from the loaded data.
        self._rw_mode: str = "manual"
        self._rsh_mode: str = "auto"

        # =====================================================================
        # PERMEABILITY COEFFICIENTS
        # =====================================================================
        self._perm_C: float = 8581.0
        self._perm_P: float = 4.4
        self._perm_Q: float = 2.0

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
        # POROSITY METHOD
        # =====================================================================
        self._primary_phie_method: str = "PHIE_DN"  # Default to Density-Neutron

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

        # =====================================================================
        # FORMATION TEMPERATURE (P3): degF, degF/100 ft; Rw entered at rw_ref_temp
        # =====================================================================
        self.temp_correction: bool = False
        self.surface_temp: float = 80.0
        self.temp_gradient: float = 1.5
        self.rw_ref_temp: float = 75.0

        # Scope edited in the Parameters window (spec §4.8).
        self._edit_scope: str = SCOPE_PROJECT
        self._edit_zone: Optional[str] = None

    # =========================================================================
    # PROPERTIES - DATA
    # =========================================================================
    @property
    def las_data(self) -> Optional[pd.DataFrame]:
        return self._well.las_data

    @las_data.setter
    def las_data(self, value: Optional[pd.DataFrame]):
        # New data for the active well invalidates its calculated state while
        # preserving user-selected parameters. With no well yet, the scratch
        # dataset becomes the project's first well.
        self._clear_derived_state()
        self._well.las_data = value
        if value is not None and self.project.active is None:
            self._promote_scratch()
        if value is not None:
            self.data_loaded.emit()

    # =========================================================================
    # WELLS
    # =========================================================================
    @property
    def _well(self) -> WellDataset:
        """The active well, or the scratch dataset when the project is empty."""
        return self.project.active or self._scratch

    @property
    def active_well(self) -> Optional[WellDataset]:
        return self.project.active

    def _promote_scratch(self):
        well = self._scratch
        self._scratch = WellDataset()
        info = getattr(well.las_parser, "well_info", None) or {}
        well.key = make_well_key(info, well.las_filename)
        well.display_name = display_name_for(info, well.las_filename)
        well.identity = dict(info)
        self.project.add_well(well, activate=True)

    def add_well(self, dataset: WellDataset, activate: bool = True) -> str:
        """Add (or replace, by key) a well; emits ``data_loaded`` when it becomes active."""
        key = self.project.add_well(dataset, activate=activate)
        if activate:
            self.data_loaded.emit()
        return key

    def set_active_well(self, key: Optional[str]):
        self.project.set_active(key)

    @property
    def las_parser(self):
        return self._well.las_parser

    @las_parser.setter
    def las_parser(self, value):
        self._well.las_parser = value

    @property
    def las_filename(self) -> str:
        return self._well.las_filename

    @las_filename.setter
    def las_filename(self, value: str):
        self._well.las_filename = value

    @property
    def qc_report(self):
        return self._well.qc_report

    @qc_report.setter
    def qc_report(self, value):
        self._well.qc_report = value

    @property
    def results(self) -> Optional[pd.DataFrame]:
        return self._well.results

    @results.setter
    def results(self, value: Optional[pd.DataFrame]):
        self._well.results = value
        self._well.calculated = value is not None
        if value is not None:
            self.analysis_complete.emit()

    @property
    def summary(self) -> Optional[Dict]:
        return self._well.summary

    @summary.setter
    def summary(self, value: Optional[Dict]):
        self._well.summary = value

    @property
    def formation_tops(self):
        return self._well.formation_tops

    @formation_tops.setter
    def formation_tops(self, value):
        self._well.formation_tops = value
        if value is not None:
            self.formation_tops_loaded.emit()

    @property
    def core_data(self):
        return self._well.core_data

    @core_data.setter
    def core_data(self, value):
        self._well.core_data = value
        if value is not None:
            self.core_data_loaded.emit()

    @property
    def merge_report(self):
        return self._well.merge_report

    @merge_report.setter
    def merge_report(self, value):
        self._well.merge_report = value
        if value is not None:
            self.merge_complete.emit()

    @property
    def calculated(self) -> bool:
        return self._well.calculated

    @calculated.setter
    def calculated(self, value: bool):
        self._well.calculated = value

    # =========================================================================
    # PROPERTIES - CURVE MAPPING
    # =========================================================================
    @property
    def curve_mapping(self) -> Dict[str, str]:
        return self._well.curve_mapping

    @curve_mapping.setter
    def curve_mapping(self, value: Dict[str, str]):
        self._well.curve_mapping = value
        self.parameters_changed.emit()

    def set_curve_mapping(self, curve_type: str, curve_name: str):
        """Set a single curve mapping."""
        self._well.curve_mapping[curve_type] = curve_name
        self.parameters_changed.emit()

    # =========================================================================
    # PROPERTIES - ANALYSIS MODE
    # =========================================================================
    @property
    def analysis_mode(self) -> str:
        return self._well.analysis_mode

    @analysis_mode.setter
    def analysis_mode(self, value: str):
        self._well.analysis_mode = value
        self.parameters_changed.emit()

    @property
    def selected_formations(self) -> List[str]:
        return self._well.selected_formations

    @selected_formations.setter
    def selected_formations(self, value: List[str]):
        self._well.selected_formations = value
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

    @property
    def nphi_matrix(self) -> Optional[float]:
        """Configured matrix neutron response, or None for lithology default."""
        return self._nphi_matrix

    @nphi_matrix.setter
    def nphi_matrix(self, value: Optional[float]):
        self._nphi_matrix = value

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
        return self._well.shale_method_used

    @shale_method_used.setter
    def shale_method_used(self, value: str):
        self._well.shale_method_used = value

    @property
    def calculated_shale(self) -> Optional[Dict]:
        return self._well.calculated_shale

    @calculated_shale.setter
    def calculated_shale(self, value: Optional[Dict]):
        self._well.calculated_shale = value

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
    # PROPERTIES - POROSITY METHOD
    # =========================================================================
    @property
    def primary_phie_method(self) -> str:
        return self._primary_phie_method

    @primary_phie_method.setter
    def primary_phie_method(self, value: str):
        self._primary_phie_method = value

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
    def rw_mode(self) -> str:
        return self._rw_mode

    @rw_mode.setter
    def rw_mode(self, value: str):
        self._rw_mode = value

    @property
    def rsh_mode(self) -> str:
        return self._rsh_mode

    @rsh_mode.setter
    def rsh_mode(self, value: str):
        self._rsh_mode = value

    @property
    def calculated_rw(self) -> Optional[float]:
        return self._well.calculated_rw

    @calculated_rw.setter
    def calculated_rw(self, value: Optional[float]):
        self._well.calculated_rw = value

    @property
    def calculated_rsh(self) -> Optional[float]:
        return self._well.calculated_rsh

    @calculated_rsh.setter
    def calculated_rsh(self, value: Optional[float]):
        self._well.calculated_rsh = value

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
        return self._well.calculated_C

    @calculated_C.setter
    def calculated_C(self, value: Optional[float]):
        self._well.calculated_C = value

    @property
    def calculated_P(self) -> Optional[float]:
        return self._well.calculated_P

    @calculated_P.setter
    def calculated_P(self, value: Optional[float]):
        self._well.calculated_P = value

    @property
    def calculated_Q(self) -> Optional[float]:
        return self._well.calculated_Q

    @calculated_Q.setter
    def calculated_Q(self, value: Optional[float]):
        self._well.calculated_Q = value

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
    def _clear_derived_state(self):
        """Clear the active well's data-dependent results (parameters stay)."""
        self._well.clear_derived()

    def set_analysis_results(self, results: Optional[pd.DataFrame], summary: Optional[Dict]):
        """Store results and summary together, then emit one completion signal."""
        self._well.results = results
        self._well.summary = summary
        self._well.calculated = results is not None
        if results is not None:
            self.analysis_complete.emit()

    def reset(self):
        """Remove every well and its results (keep user parameters)."""
        self._scratch = WellDataset()
        self.project.clear()

    def project_params(self) -> dict:
        """The project-scope analysis parameters as a detached flat dict."""
        from modules.pipeline import PARAM_DEFAULTS

        return {
            key: copy.deepcopy(getattr(self, key, default))
            for key, default in PARAM_DEFAULTS.items()
        }

    def params_for_well(self, well: Optional[WellDataset] = None) -> dict:
        """Effective pipeline parameters for one well (spec §4.4).

        Project values, overridden by the well's entries; plus ``zone_plan``
        (per-zone parameters for zones with entries), ``param_info`` (the
        source of every scoped value) and ``curve_mapping``. Detached: safe to
        hand to a worker thread.
        """
        from modules.param_scopes import resolve, zone_plan

        ds = well if well is not None else self._well
        global_params = self.project_params()
        header = ds.well_info
        flat, info = resolve(global_params, ds.overrides, None, None, None, header)
        flat["analysis_mode"] = ds.analysis_mode
        flat["selected_formations"] = list(ds.selected_formations)
        flat["param_info"] = info
        flat["zone_plan"] = zone_plan(
            global_params, ds.overrides, self.project.zone_params, ds.zone_overrides,
            self.zones_for(ds), header,
        )
        flat["curve_mapping"] = dict(ds.curve_mapping)
        return copy.deepcopy(flat)

    def to_params(self) -> dict:
        """Snapshot the active well's effective parameters as a plain, detached dict.

        Keys follow ``modules.pipeline.PARAM_DEFAULTS``. Workers must call this
        on the GUI thread and read only the returned dict afterwards, so the
        model is never touched from a pool thread. Curve mapping is included
        under ``"curve_mapping"``; see :meth:`params_for_well` for the rest.
        """
        return self.params_for_well(self._well)

    def well_params_hash(self, well: Optional[WellDataset] = None) -> str:
        """Hash of a well's effective parameters and tops, for stale tracking (§5.5)."""
        from modules.param_scopes import params_hash

        ds = well if well is not None else self._well
        params = self.params_for_well(ds)
        tops = getattr(ds.formation_tops, "formations", None) or []
        params["_tops"] = [(fm.name, fm.top_depth, fm.bottom_depth) for fm in tops]
        return params_hash(params)

    # =========================================================================
    # PARAMETER SCOPES (spec §4)
    # =========================================================================
    @property
    def edit_scope(self) -> str:
        """Scope edited in the Parameters window: "project" or "well"."""
        return self._edit_scope

    @property
    def edit_zone(self) -> Optional[str]:
        """Zone (normalised formation name) being edited, or None."""
        return self._edit_zone

    def set_edit_scope(self, scope: str, zone: Optional[str] = None):
        from modules.param_scopes import normalize_zone

        if scope not in (SCOPE_PROJECT, SCOPE_WELL):
            raise ValueError(scope)
        zone = normalize_zone(zone) or None
        if (scope, zone) != (self._edit_scope, self._edit_zone):
            self._edit_scope, self._edit_zone = scope, zone
            self.scope_changed.emit()

    def zones_for(self, well: Optional[WellDataset] = None) -> List[str]:
        """Normalised formation names of a well's tops, in depth order."""
        from modules.param_scopes import normalize_zone

        ds = well if well is not None else self._well
        formations = getattr(ds.formation_tops, "formations", None) or []
        names = []
        for fm in sorted(formations, key=lambda f: f.top_depth):
            name = normalize_zone(fm.name)
            if name and name not in names:
                names.append(name)
        return names

    def _scope_target(self, scope, zone, well):
        from modules.param_scopes import normalize_zone

        scope = scope or self._edit_scope
        zone = normalize_zone(zone if zone is not None else self._edit_zone) or None
        ds = None
        if scope == SCOPE_WELL:
            ds = self.project.get(well) if isinstance(well, str) else (well or self.project.active)
            if ds is None:
                raise ValueError("No well to edit")
        return scope, zone, ds

    def _store(self, scope, zone, ds, create=False) -> Optional[dict]:
        """The entry dict of a non-project scope (None for the flat project scope)."""
        if scope == SCOPE_PROJECT and zone is None:
            return None
        if scope == SCOPE_PROJECT:
            store = self.project.zone_params
        elif zone is None:
            return ds.overrides
        else:
            store = ds.zone_overrides
        if create:
            return store.setdefault(zone, {})
        return store.get(zone, {})

    def get_entry(self, name: str, scope: Optional[str] = None,
                  zone: Optional[str] = None, well=None) -> Optional[dict]:
        """The entry stored in a scope (project: read from the flat values)."""
        from modules.param_scopes import project_entry

        scope, zone, ds = self._scope_target(scope, zone, well)
        store = self._store(scope, zone, ds)
        if store is None:
            return project_entry(name, self.project_params())
        return store.get(name)

    def set_entry(self, name: str, mode: str, value=None, scope: Optional[str] = None,
                  zone: Optional[str] = None, well=None, **meta):
        """Set a parameter in a scope (default: the edited scope).

        ``mode`` is "auto" or "manual"; "inherit" removes the entry. Extra
        keyword arguments (``source="calibrated"``, ``method``, ``date``) are
        stored on the entry. The project scope without a zone writes the flat
        project values.
        """
        from modules.param_scopes import (
            AUTO, INHERIT, SPECS, apply_entry, make_entry, project_entry,
        )

        spec = SPECS.get(name)
        if spec is None:
            raise ValueError(f"{name} is a project-only parameter")
        scope, zone, ds = self._scope_target(scope, zone, well)
        if zone is not None and not spec.zone:
            raise ValueError(f"{name} cannot be set per zone")
        if scope == SCOPE_WELL and not spec.well:
            raise ValueError(f"{name} cannot be set per well")
        if mode == AUTO and not spec.auto:
            raise ValueError(f"{name} has no automatic estimate")
        store = self._store(scope, zone, ds, create=True)
        if store is None:
            if mode == INHERIT:
                raise ValueError("The project scope cannot inherit")
            if value is None and mode != AUTO:
                value = project_entry(name, self.project_params())["value"]
            flat = {}
            apply_entry(flat, name, make_entry(mode, value))
            for key, val in flat.items():
                setattr(self, key, val)
        elif mode == INHERIT:
            store.pop(name, None)
        else:
            entry = make_entry(mode, value)
            entry.update({k: v for k, v in meta.items() if v is not None})
            store[name] = entry
        self._prune_zone_stores()
        self.scoped_params_changed.emit(ds.key if ds is not None else "")

    def clear_entry(self, name: str, scope: Optional[str] = None,
                    zone: Optional[str] = None, well=None):
        """Reset an entry to inherit (spec §4.7 rule 4)."""
        from modules.param_scopes import INHERIT

        self.set_entry(name, INHERIT, scope=scope, zone=zone, well=well)

    def _prune_zone_stores(self):
        for store in [self.project.zone_params] + [w.zone_overrides for w in self.project]:
            for zone in [z for z, entries in store.items() if not entries]:
                del store[zone]

    def effective_params(self, well=None, zone: Optional[str] = None):
        """``(flat, info)`` as resolved for a well and optional zone (§4.4)."""
        from modules.param_scopes import resolve

        ds = self.project.get(well) if isinstance(well, str) else (well or self._well)
        return resolve(self.project_params(), ds.overrides, self.project.zone_params,
                       ds.zone_overrides, zone, ds.well_info)

    def scope_view(self, scope: Optional[str] = None, zone: Optional[str] = None,
                   well=None):
        """What the Parameters window shows for a scope.

        Returns ``(flat, info)``: the values in effect at that scope (for the
        project · zone scope: the project values with that zone's entries) and,
        per scoped parameter, ``{"scope", "mode", "source", "here"}`` where
        ``here`` says whether the value is set in this very scope.
        """
        from modules.param_scopes import PROJECT, PROJECT_ZONE, WELL, WELL_ZONE, resolve

        scope, zone, ds = self._scope_target(scope, zone, well)
        global_params = self.project_params()
        if scope == SCOPE_PROJECT:
            zone_params = self.project.zone_params if zone else None
            flat, info = resolve(global_params, None, zone_params, None, zone)
            here_scope = PROJECT_ZONE if zone else PROJECT
        else:
            flat, info = resolve(global_params, ds.overrides, self.project.zone_params,
                                 ds.zone_overrides, zone, ds.well_info)
            here_scope = WELL_ZONE if zone else WELL
        for item in info.values():
            item["here"] = item["scope"] == here_scope
        return flat, info

    def copy_entry(self, name: str, entry: dict, targets: List[tuple]):
        """Copy an entry to ``[(scope, zone, well_key), ...]`` (spec §4.7 rule 2)."""
        meta = {k: v for k, v in entry.items() if k not in ("mode", "value")}
        for scope, zone, well in targets:
            self.set_entry(name, entry["mode"], entry.get("value"), scope, zone, well, **meta)

    def promote_to_project(self, name: str, value):
        """Set as project default: write a value to the project scope."""
        from modules.param_scopes import MANUAL

        self.set_entry(name, MANUAL, value, scope=SCOPE_PROJECT, zone=None)

    def get_available_curves(self) -> List[str]:
        """Get list of available curves from loaded LAS data."""
        if self._well.las_parser is not None:
            return self._well.las_parser.get_available_curves()
        return []

    def get_formation_list(self) -> List[str]:
        """Get list of formation names."""
        if self._well.formation_tops is not None:
            return self._well.formation_tops.get_formation_list()
        return []
