"""
Parameter Group Widgets for Petrophyter PyQt
Collapsible group boxes for sidebar parameters.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QGroupBox, QLabel, QPushButton, QComboBox, QDoubleSpinBox,
    QSpinBox, QRadioButton, QButtonGroup, QCheckBox, QListWidget,
    QListWidgetItem, QSlider, QFrame, QScrollArea, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal
from typing import List, Dict, Optional


class CollapsibleGroupBox(QGroupBox):
    """
    A simple group box (always expanded).
    No checkbox - content is always visible.
    """
    
    toggled = pyqtSignal(bool)
    
    def __init__(self, title: str, parent=None, expanded: bool = True):
        super().__init__(title, parent)
        # Not checkable - always expanded
        self.setCheckable(False)
        self._content_widget = None
    
    def set_content_widget(self, widget: QWidget):
        """Set the content widget."""
        self._content_widget = widget
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.addWidget(widget)
        # Always visible
        widget.setVisible(True)
    
    def expand_all(self):
        """Expand the group (for compatibility)."""
        if self._content_widget:
            self._content_widget.setVisible(True)


class AnalysisModeGroup(QWidget):
    """
    Analysis mode selection widget.
    Replaces the Analysis Mode expander in Streamlit.
    """
    
    mode_changed = pyqtSignal(str)
    formations_changed = pyqtSignal(list)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Radio buttons for mode selection
        self.whole_well_radio = QRadioButton("Whole Well")
        self.per_formation_radio = QRadioButton("Per-Formation")
        self.whole_well_radio.setChecked(True)
        
        self.button_group = QButtonGroup(self)
        self.button_group.addButton(self.whole_well_radio)
        self.button_group.addButton(self.per_formation_radio)
        
        layout.addWidget(QLabel("Select analysis scope:"))
        layout.addWidget(self.whole_well_radio)
        layout.addWidget(self.per_formation_radio)
        
        # Formation list (shown when Per-Formation is selected)
        self.formation_label = QLabel("Select Formation(s):")
        self.formation_list = QListWidget()
        self.formation_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.formation_list.setMaximumHeight(100)
        
        layout.addWidget(self.formation_label)
        layout.addWidget(self.formation_list)
        
        # Initially hide formation selection
        self.formation_label.setVisible(False)
        self.formation_list.setVisible(False)
        
        # Connect signals
        self.whole_well_radio.toggled.connect(self._on_mode_changed)
        self.formation_list.itemSelectionChanged.connect(self._on_formations_changed)
    
    def _on_mode_changed(self, checked: bool):
        if checked:
            self.mode_changed.emit("Whole Well")
            self.formation_label.setVisible(False)
            self.formation_list.setVisible(False)
        else:
            self.mode_changed.emit("Per-Formation")
            self.formation_label.setVisible(True)
            self.formation_list.setVisible(True)
    
    def _on_formations_changed(self):
        selected = [item.text() for item in self.formation_list.selectedItems()]
        self.formations_changed.emit(selected)
    
    def set_formations(self, formations: List[str]):
        """Update the formation list."""
        self.formation_list.clear()
        for fm in formations:
            self.formation_list.addItem(fm)
    
    def get_mode(self) -> str:
        return "Whole Well" if self.whole_well_radio.isChecked() else "Per-Formation"
    
    def get_selected_formations(self) -> List[str]:
        return [item.text() for item in self.formation_list.selectedItems()]


class CurveMappingGroup(QWidget):
    """
    Curve mapping widget.
    Replaces the Curve Mapping expander in Streamlit.
    """
    
    mapping_changed = pyqtSignal(str, str)  # (curve_type, curve_name)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.curve_combos = {}
        curve_types = ['GR', 'RHOB', 'NPHI', 'DT', 'RT']
        
        for ctype in curve_types:
            combo = QComboBox()
            combo.addItem('None')
            combo.currentTextChanged.connect(
                lambda text, ct=ctype: self.mapping_changed.emit(ct, text)
            )
            self.curve_combos[ctype] = combo
            layout.addRow(f"{ctype}:", combo)
    
    def set_available_curves(self, curves: List[str], detected: Dict[str, str] = None):
        """Update available curves in all combos."""
        for ctype, combo in self.curve_combos.items():
            combo.blockSignals(True)
            current = combo.currentText()
            combo.clear()
            combo.addItem('None')
            combo.addItems(curves)
            
            # Set detected curve if available
            if detected and ctype in detected and detected[ctype] in curves:
                combo.setCurrentText(detected[ctype])
            elif current in curves:
                combo.setCurrentText(current)
            
            combo.blockSignals(False)
    
    def get_mapping(self) -> Dict[str, str]:
        return {ctype: combo.currentText() for ctype, combo in self.curve_combos.items()}


class VShaleParamsGroup(QWidget):
    """VShale parameters widget."""
    
    params_changed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # GR Baseline method
        form = QFormLayout()
        self.baseline_combo = QComboBox()
        self.baseline_combo.addItems(["Statistically (Auto)", "Custom (Manual)"])
        form.addRow("GR Baseline:", self.baseline_combo)
        layout.addLayout(form)
        
        # Manual GR inputs (initially hidden)
        self.manual_frame = QFrame()
        manual_layout = QFormLayout(self.manual_frame)
        
        self.gr_min_spin = QDoubleSpinBox()
        self.gr_min_spin.setRange(0, 200)
        self.gr_min_spin.setValue(20.0)
        self.gr_min_spin.setSuffix(" API")
        
        self.gr_max_spin = QDoubleSpinBox()
        self.gr_max_spin.setRange(0, 300)
        self.gr_max_spin.setValue(120.0)
        self.gr_max_spin.setSuffix(" API")
        
        manual_layout.addRow("GR min:", self.gr_min_spin)
        manual_layout.addRow("GR max:", self.gr_max_spin)
        
        self.manual_frame.setVisible(False)
        layout.addWidget(self.manual_frame)
        
        # Info label for auto mode
        self.auto_info = QLabel("📈 GRmin/GRmax from P5/P95")
        self.auto_info.setStyleSheet("color: #4A4540; background-color: transparent;")
        layout.addWidget(self.auto_info)
        
        # VShale methods
        layout.addWidget(QLabel("VShale Methods:"))
        self.method_list = QListWidget()
        self.method_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.method_list.setMaximumHeight(80)
        
        for method in ["Linear", "Larionov Tertiary", "Larionov Older"]:
            item = QListWidgetItem(method)
            self.method_list.addItem(item)
        
        # Select Linear by default
        self.method_list.item(0).setSelected(True)
        layout.addWidget(self.method_list)
        
        # Connect signals
        self.baseline_combo.currentTextChanged.connect(self._on_baseline_changed)
        self.gr_min_spin.valueChanged.connect(self._emit_changed)
        self.gr_max_spin.valueChanged.connect(self._emit_changed)
        self.method_list.itemSelectionChanged.connect(self._emit_changed)
    
    def _on_baseline_changed(self, text: str):
        is_manual = text == "Custom (Manual)"
        self.manual_frame.setVisible(is_manual)
        self.auto_info.setVisible(not is_manual)
        self._emit_changed()
    
    def _emit_changed(self):
        self.params_changed.emit()
    
    def get_params(self) -> Dict:
        return {
            'baseline_method': self.baseline_combo.currentText(),
            'gr_min': self.gr_min_spin.value(),
            'gr_max': self.gr_max_spin.value(),
            'methods': [item.text() for item in self.method_list.selectedItems()]
        }


class MatrixParamsGroup(QWidget):
    """Matrix parameters widget."""
    
    params_changed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.rho_matrix_spin = QDoubleSpinBox()
        self.rho_matrix_spin.setRange(2.5, 2.9)
        self.rho_matrix_spin.setValue(2.65)
        self.rho_matrix_spin.setSingleStep(0.01)
        self.rho_matrix_spin.setDecimals(2)
        self.rho_matrix_spin.setSuffix(" g/cc")
        
        self.dt_matrix_spin = QDoubleSpinBox()
        self.dt_matrix_spin.setRange(40, 70)
        self.dt_matrix_spin.setValue(55.5)
        self.dt_matrix_spin.setSingleStep(0.5)
        self.dt_matrix_spin.setSuffix(" µs/ft")
        
        layout.addRow("ρ matrix:", self.rho_matrix_spin)
        layout.addRow("DT matrix:", self.dt_matrix_spin)
        
        self.rho_matrix_spin.valueChanged.connect(lambda: self.params_changed.emit())
        self.dt_matrix_spin.valueChanged.connect(lambda: self.params_changed.emit())
    
    def get_params(self) -> Dict:
        return {
            'rho_matrix': self.rho_matrix_spin.value(),
            'dt_matrix': self.dt_matrix_spin.value()
        }


class FluidParamsGroup(QWidget):
    """Fluid parameters widget."""
    
    params_changed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.rho_fluid_spin = QDoubleSpinBox()
        self.rho_fluid_spin.setRange(0.8, 1.2)
        self.rho_fluid_spin.setValue(1.0)
        self.rho_fluid_spin.setSingleStep(0.01)
        self.rho_fluid_spin.setDecimals(2)
        self.rho_fluid_spin.setSuffix(" g/cc")
        
        self.dt_fluid_spin = QDoubleSpinBox()
        self.dt_fluid_spin.setRange(150, 210)
        self.dt_fluid_spin.setValue(189.0)
        self.dt_fluid_spin.setSingleStep(1.0)
        self.dt_fluid_spin.setSuffix(" µs/ft")
        
        layout.addRow("ρ fluid:", self.rho_fluid_spin)
        layout.addRow("DT fluid:", self.dt_fluid_spin)
        
        self.rho_fluid_spin.valueChanged.connect(lambda: self.params_changed.emit())
        self.dt_fluid_spin.valueChanged.connect(lambda: self.params_changed.emit())
    
    def get_params(self) -> Dict:
        return {
            'rho_fluid': self.rho_fluid_spin.value(),
            'dt_fluid': self.dt_fluid_spin.value()
        }


class ShaleParamsGroup(QWidget):
    """Shale parameters widget with adaptive threshold support."""
    
    params_changed = pyqtSignal()
    calculate_clicked = pyqtSignal()
    apply_clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Approach selection
        form = QFormLayout()
        self.approach_combo = QComboBox()
        self.approach_combo.addItems(["Custom (Manual)", "Statistical (Auto)"])
        form.addRow("Approach:", self.approach_combo)
        layout.addLayout(form)
        
        # Manual input frame
        self.manual_frame = QFrame()
        manual_layout = QFormLayout(self.manual_frame)
        
        self.rho_shale_spin = QDoubleSpinBox()
        self.rho_shale_spin.setRange(2.2, 2.7)
        self.rho_shale_spin.setValue(2.45)
        self.rho_shale_spin.setSingleStep(0.01)
        self.rho_shale_spin.setDecimals(2)
        self.rho_shale_spin.setSuffix(" g/cc")
        
        self.dt_shale_spin = QDoubleSpinBox()
        self.dt_shale_spin.setRange(70, 150)
        self.dt_shale_spin.setValue(100.0)
        self.dt_shale_spin.setSingleStep(1.0)
        self.dt_shale_spin.setSuffix(" µs/ft")
        
        self.nphi_shale_spin = QDoubleSpinBox()
        self.nphi_shale_spin.setRange(0.15, 0.5)
        self.nphi_shale_spin.setValue(0.35)
        self.nphi_shale_spin.setSingleStep(0.01)
        self.nphi_shale_spin.setDecimals(2)
        
        manual_layout.addRow("ρ shale:", self.rho_shale_spin)
        manual_layout.addRow("DT shale:", self.dt_shale_spin)
        manual_layout.addRow("NPHI shale:", self.nphi_shale_spin)
        
        layout.addWidget(self.manual_frame)
        
        # Statistical frame (buttons and settings)
        self.stat_frame = QFrame()
        stat_layout = QVBoxLayout(self.stat_frame)
        
        # === SELECTION MODE (v2.1) ===
        mode_form = QFormLayout()
        self.selection_mode_combo = QComboBox()
        self.selection_mode_combo.addItems(["Fixed Threshold", "Quantile", "Stability Sweep"])
        self.selection_mode_combo.setToolTip("Method for determining shale VSH threshold")
        mode_form.addRow("Selection mode:", self.selection_mode_combo)
        stat_layout.addLayout(mode_form)
        
        # === FIXED THRESHOLD FRAME ===
        self.fixed_frame = QFrame()
        fixed_layout = QFormLayout(self.fixed_frame)
        self.vsh_threshold_spin = QDoubleSpinBox()
        self.vsh_threshold_spin.setRange(0.0, 1.0)
        self.vsh_threshold_spin.setValue(0.80)
        self.vsh_threshold_spin.setSingleStep(0.05)
        self.vsh_threshold_spin.setDecimals(2)
        self.vsh_threshold_spin.setToolTip("Minimum Vsh to be considered 'pure shale'")
        fixed_layout.addRow("Vsh threshold:", self.vsh_threshold_spin)
        stat_layout.addWidget(self.fixed_frame)
        
        # === QUANTILE FRAME ===
        self.quantile_frame = QFrame()
        quantile_layout = QFormLayout(self.quantile_frame)
        self.vsh_quantile_spin = QDoubleSpinBox()
        self.vsh_quantile_spin.setRange(0.80, 0.99)
        self.vsh_quantile_spin.setValue(0.90)
        self.vsh_quantile_spin.setSingleStep(0.01)
        self.vsh_quantile_spin.setDecimals(2)
        self.vsh_quantile_spin.setToolTip("Quantile of VSH distribution to use as threshold")
        quantile_layout.addRow("Vsh quantile:", self.vsh_quantile_spin)
        self.quantile_frame.setVisible(False)
        stat_layout.addWidget(self.quantile_frame)
        
        # === SWEEP FRAME ===
        self.sweep_frame = QFrame()
        sweep_layout = QFormLayout(self.sweep_frame)
        
        self.sweep_tmin_spin = QDoubleSpinBox()
        self.sweep_tmin_spin.setRange(0.4, 0.9)
        self.sweep_tmin_spin.setValue(0.65)
        self.sweep_tmin_spin.setSingleStep(0.05)
        self.sweep_tmin_spin.setDecimals(2)
        self.sweep_tmin_spin.setToolTip("Minimum threshold to sweep")
        
        self.sweep_tmax_spin = QDoubleSpinBox()
        self.sweep_tmax_spin.setRange(0.7, 1.0)
        self.sweep_tmax_spin.setValue(0.95)
        self.sweep_tmax_spin.setSingleStep(0.05)
        self.sweep_tmax_spin.setDecimals(2)
        self.sweep_tmax_spin.setToolTip("Maximum threshold to sweep")
        
        self.sweep_step_spin = QDoubleSpinBox()
        self.sweep_step_spin.setRange(0.01, 0.1)
        self.sweep_step_spin.setValue(0.02)
        self.sweep_step_spin.setSingleStep(0.01)
        self.sweep_step_spin.setDecimals(2)
        self.sweep_step_spin.setToolTip("Step size for threshold sweep")
        
        sweep_layout.addRow("T min:", self.sweep_tmin_spin)
        sweep_layout.addRow("T max:", self.sweep_tmax_spin)
        sweep_layout.addRow("Step:", self.sweep_step_spin)
        self.sweep_frame.setVisible(False)
        stat_layout.addWidget(self.sweep_frame)
        
        # === COMMON OPTIONS ===
        common_form = QFormLayout()
        self.min_points_spin = QSpinBox()
        self.min_points_spin.setRange(5, 500)
        self.min_points_spin.setValue(50)
        self.min_points_spin.setToolTip("Minimum shale samples required (fallback if below)")
        common_form.addRow("Min points:", self.min_points_spin)
        stat_layout.addLayout(common_form)
        
        # Robust filtering options
        self.gate_logs_check = QCheckBox("Gate logs (RHOB/NPHI/DT ranges)")
        self.gate_logs_check.setChecked(True)
        self.gate_logs_check.setToolTip("Filter out samples with RHOB/NPHI/DT outside typical shale ranges")
        stat_layout.addWidget(self.gate_logs_check)
        
        self.iqr_filter_check = QCheckBox("IQR outlier filter")
        self.iqr_filter_check.setChecked(True)
        self.iqr_filter_check.setToolTip("Remove outliers using IQR method before calculating median")
        stat_layout.addWidget(self.iqr_filter_check)
        
        self.calc_btn = QPushButton("🔄 Calculate Shale Parameters")
        self.calc_btn.clicked.connect(self.calculate_clicked.emit)
        stat_layout.addWidget(self.calc_btn)
        
        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        stat_layout.addWidget(self.result_label)
        
        self.apply_btn = QPushButton("✅ Apply Calculated")
        self.apply_btn.clicked.connect(self.apply_clicked.emit)
        self.apply_btn.setVisible(False)
        stat_layout.addWidget(self.apply_btn)
        
        self.stat_frame.setVisible(False)
        layout.addWidget(self.stat_frame)
        
        # Connect signals
        self.approach_combo.currentTextChanged.connect(self._on_approach_changed)
        self.selection_mode_combo.currentTextChanged.connect(self._on_selection_mode_changed)
        self.rho_shale_spin.valueChanged.connect(lambda: self.params_changed.emit())
        self.dt_shale_spin.valueChanged.connect(lambda: self.params_changed.emit())
        self.nphi_shale_spin.valueChanged.connect(lambda: self.params_changed.emit())
        self.vsh_threshold_spin.valueChanged.connect(lambda: self.params_changed.emit())
        self.vsh_quantile_spin.valueChanged.connect(lambda: self.params_changed.emit())
        self.sweep_tmin_spin.valueChanged.connect(lambda: self.params_changed.emit())
        self.sweep_tmax_spin.valueChanged.connect(lambda: self.params_changed.emit())
        self.sweep_step_spin.valueChanged.connect(lambda: self.params_changed.emit())
        self.min_points_spin.valueChanged.connect(lambda: self.params_changed.emit())
        self.gate_logs_check.stateChanged.connect(lambda: self.params_changed.emit())
        self.iqr_filter_check.stateChanged.connect(lambda: self.params_changed.emit())
    
    def _on_approach_changed(self, text: str):
        is_stat = text == "Statistical (Auto)"
        self.manual_frame.setVisible(not is_stat)
        self.stat_frame.setVisible(is_stat)
    
    def _on_selection_mode_changed(self, text: str):
        """Show/hide mode-specific frames."""
        self.fixed_frame.setVisible(text == "Fixed Threshold")
        self.quantile_frame.setVisible(text == "Quantile")
        self.sweep_frame.setVisible(text == "Stability Sweep")
    
    def show_calculated_result(self, result: Dict):
        """Show calculated shale parameters with diagnostics."""
        text_lines = [
            f"📊 Calculated:",
            f"  ρ shale: {result.get('rho_shale', 2.45):.2f} g/cc",
            f"  NPHI shale: {result.get('nphi_shale', 0.35):.2f}",
            f"  DT shale: {result.get('dt_shale', 100.0):.1f} µs/ft"
        ]
        
        # Add diagnostics
        if 'shale_selection_mode' in result:
            text_lines.append(f"  🔧 Mode: {result['shale_selection_mode']}")
        if 'shale_threshold_used' in result:
            text_lines.append(f"  🎯 Threshold: {result['shale_threshold_used']:.3f}")
        elif 'threshold' in result:
            text_lines.append(f"  🎯 Threshold: {result['threshold']:.3f}")
        if 'shale_points_after' in result:
            before = result.get('shale_points_before', '?')
            after = result['shale_points_after']
            text_lines.append(f"  📍 Shale points: {before} → {after}")
        elif 'shale_points' in result:
            text_lines.append(f"  📍 Shale points: {result['shale_points']}")
        if 'vsh_method_used' in result:
            text_lines.append(f"  📐 VSH: {result['vsh_method_used']}")
        if result.get('method') == 'fallback':
            text_lines.append("  ⚠️ Using fallback defaults")
        
        self.result_label.setText("\n".join(text_lines))
        self.apply_btn.setVisible(True)
    
    def get_params(self) -> Dict:
        mode_map = {
            "Fixed Threshold": "fixed_threshold",
            "Quantile": "quantile",
            "Stability Sweep": "stability_sweep"
        }
        return {
            'approach': self.approach_combo.currentText(),
            'rho_shale': self.rho_shale_spin.value(),
            'dt_shale': self.dt_shale_spin.value(),
            'nphi_shale': self.nphi_shale_spin.value(),
            'shale_vsh_threshold': self.vsh_threshold_spin.value(),
            'shale_gate_logs': self.gate_logs_check.isChecked(),
            'shale_iqr_filter': self.iqr_filter_check.isChecked(),
            # Adaptive threshold params (v2.1)
            'shale_selection_mode': mode_map.get(self.selection_mode_combo.currentText(), "fixed_threshold"),
            'shale_vsh_quantile': self.vsh_quantile_spin.value(),
            'shale_min_points': self.min_points_spin.value(),
            'shale_sweep_tmin': self.sweep_tmin_spin.value(),
            'shale_sweep_tmax': self.sweep_tmax_spin.value(),
            'shale_sweep_step': self.sweep_step_spin.value()
        }
    
    def set_params(self, rho: float, dt: float, nphi: float):
        """Set parameter values."""
        self.rho_shale_spin.setValue(rho)
        self.dt_shale_spin.setValue(dt)
        self.nphi_shale_spin.setValue(nphi)


class ArchieParamsGroup(QWidget):
    """Archie parameters widget."""
    
    params_changed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Lithology preset
        form = QFormLayout()
        self.lithology_combo = QComboBox()
        self.lithology_combo.addItems(["Sandstone (Humble)", "Carbonate", "Custom"])
        form.addRow("Lithology:", self.lithology_combo)
        layout.addLayout(form)
        
        # Preset info
        self.preset_info = QLabel("a=0.62, m=2.15, n=2.0")
        self.preset_info.setStyleSheet("color: #4A4540; background-color: transparent;")
        layout.addWidget(self.preset_info)
        
        # Custom input frame
        self.custom_frame = QFrame()
        custom_layout = QFormLayout(self.custom_frame)
        
        self.a_spin = QDoubleSpinBox()
        self.a_spin.setRange(0.5, 2.0)
        self.a_spin.setValue(0.62)
        self.a_spin.setSingleStep(0.01)
        self.a_spin.setDecimals(2)
        
        self.m_spin = QDoubleSpinBox()
        self.m_spin.setRange(1.5, 3.0)
        self.m_spin.setValue(2.15)
        self.m_spin.setSingleStep(0.01)
        self.m_spin.setDecimals(2)
        
        self.n_spin = QDoubleSpinBox()
        self.n_spin.setRange(1.5, 3.0)
        self.n_spin.setValue(2.0)
        self.n_spin.setSingleStep(0.1)
        self.n_spin.setDecimals(1)
        
        custom_layout.addRow("a (tortuosity):", self.a_spin)
        custom_layout.addRow("m (cementation):", self.m_spin)
        custom_layout.addRow("n (saturation):", self.n_spin)
        
        self.custom_frame.setVisible(False)
        layout.addWidget(self.custom_frame)
        
        # Connect signals
        self.lithology_combo.currentTextChanged.connect(self._on_lithology_changed)
        self.a_spin.valueChanged.connect(lambda: self.params_changed.emit())
        self.m_spin.valueChanged.connect(lambda: self.params_changed.emit())
        self.n_spin.valueChanged.connect(lambda: self.params_changed.emit())
    
    def _on_lithology_changed(self, text: str):
        presets = {
            "Sandstone (Humble)": {"a": 0.62, "m": 2.15, "n": 2.0},
            "Carbonate": {"a": 1.0, "m": 2.0, "n": 2.0}
        }
        
        if text == "Custom":
            self.custom_frame.setVisible(True)
            self.preset_info.setVisible(False)
        else:
            self.custom_frame.setVisible(False)
            self.preset_info.setVisible(True)
            preset = presets[text]
            self.preset_info.setText(f"a={preset['a']}, m={preset['m']}, n={preset['n']}")
            self.a_spin.setValue(preset['a'])
            self.m_spin.setValue(preset['m'])
            self.n_spin.setValue(preset['n'])
        
        self.params_changed.emit()
    
    def get_params(self) -> Dict:
        return {
            'lithology': self.lithology_combo.currentText(),
            'a': self.a_spin.value(),
            'm': self.m_spin.value(),
            'n': self.n_spin.value()
        }


class ResistivityParamsGroup(QWidget):
    """Resistivity parameters widget."""
    
    params_changed = pyqtSignal()
    calculate_clicked = pyqtSignal()
    apply_clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        form = QFormLayout()
        
        self.rw_spin = QDoubleSpinBox()
        self.rw_spin.setRange(0.001, 5.0)
        self.rw_spin.setValue(0.05)
        self.rw_spin.setSingleStep(0.001)
        self.rw_spin.setDecimals(3)
        self.rw_spin.setSuffix(" Ω.m")
        
        self.rsh_spin = QDoubleSpinBox()
        self.rsh_spin.setRange(0.1, 50.0)
        self.rsh_spin.setValue(5.0)
        self.rsh_spin.setSingleStep(0.1)
        self.rsh_spin.setDecimals(1)
        self.rsh_spin.setSuffix(" Ω.m")
        
        form.addRow("Rw:", self.rw_spin)
        form.addRow("Rsh:", self.rsh_spin)
        layout.addLayout(form)
        
        # Calculate button
        self.calc_btn = QPushButton("🔄 Calculate Rw & Rsh from Data")
        self.calc_btn.clicked.connect(self.calculate_clicked.emit)
        layout.addWidget(self.calc_btn)
        
        # Result label
        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)
        
        # Apply button
        self.apply_btn = QPushButton("✅ Apply Calculated Values")
        self.apply_btn.clicked.connect(self.apply_clicked.emit)
        self.apply_btn.setVisible(False)
        layout.addWidget(self.apply_btn)
        
        # Connect signals
        self.rw_spin.valueChanged.connect(lambda: self.params_changed.emit())
        self.rsh_spin.valueChanged.connect(lambda: self.params_changed.emit())
    
    def show_calculated_result(self, rw: float, rsh: float):
        """Show calculated values."""
        self.result_label.setText(f"📊 Calculated: Rw={rw:.4f}, Rsh={rsh:.2f}")
        self.apply_btn.setVisible(True)
        self._calculated_rw = rw
        self._calculated_rsh = rsh
    
    def apply_calculated(self):
        """Apply calculated values to spinboxes."""
        if hasattr(self, '_calculated_rw'):
            self.rw_spin.setValue(self._calculated_rw)
            self.rsh_spin.setValue(self._calculated_rsh)
            self.result_label.setText("")
            self.apply_btn.setVisible(False)
    
    def get_params(self) -> Dict:
        return {
            'rw': self.rw_spin.value(),
            'rsh': self.rsh_spin.value()
        }


class PermParamsGroup(QWidget):
    """Permeability coefficient parameters widget."""
    
    params_changed = pyqtSignal()
    calculate_clicked = pyqtSignal()
    apply_clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Formula label
        formula = QLabel("Wyllie-Rose: K = C × φ^P / Swi^Q")
        formula.setStyleSheet("color: #4A4540; background-color: transparent; font-style: italic;")
        layout.addWidget(formula)
        
        form = QFormLayout()
        
        self.c_spin = QDoubleSpinBox()
        self.c_spin.setRange(10, 50000)
        self.c_spin.setValue(8581.0)
        self.c_spin.setSingleStep(100)
        self.c_spin.setDecimals(0)
        
        self.p_spin = QDoubleSpinBox()
        self.p_spin.setRange(2.0, 7.0)
        self.p_spin.setValue(4.4)
        self.p_spin.setSingleStep(0.1)
        self.p_spin.setDecimals(1)
        
        self.q_spin = QDoubleSpinBox()
        self.q_spin.setRange(0.5, 4.0)
        self.q_spin.setValue(2.0)
        self.q_spin.setSingleStep(0.1)
        self.q_spin.setDecimals(1)
        
        form.addRow("C:", self.c_spin)
        form.addRow("P:", self.p_spin)
        form.addRow("Q:", self.q_spin)
        layout.addLayout(form)
        
        # Info label
        info = QLabel("💡 Timur defaults: C=8581, P=4.4, Q=2.0")
        info.setStyleSheet("color: #4A4540; background-color: transparent;")
        layout.addWidget(info)
        
        # Calculate button
        self.calc_btn = QPushButton("🔄 Calculate C, P, Q")
        self.calc_btn.clicked.connect(self.calculate_clicked.emit)
        layout.addWidget(self.calc_btn)
        
        # Result and apply
        self.result_label = QLabel("")
        layout.addWidget(self.result_label)
        
        self.apply_btn = QPushButton("✅ Apply Calculated Values")
        self.apply_btn.clicked.connect(self._do_apply)
        self.apply_btn.setVisible(False)
        layout.addWidget(self.apply_btn)
        
        # Connect signals
        self.c_spin.valueChanged.connect(lambda: self.params_changed.emit())
        self.p_spin.valueChanged.connect(lambda: self.params_changed.emit())
        self.q_spin.valueChanged.connect(lambda: self.params_changed.emit())
    
    def get_params(self) -> Dict:
        return {
            'C': self.c_spin.value(),
            'P': self.p_spin.value(),
            'Q': self.q_spin.value()
        }
    
    def show_calculated_result(self, C: float, P: float, Q: float):
        """Show calculated values."""
        self.result_label.setText(f"📊 Calculated: C={C:.0f}, P={P:.2f}, Q={Q:.2f}")
        self.apply_btn.setVisible(True)
        self._calculated_C = C
        self._calculated_P = P
        self._calculated_Q = Q
    
    def apply_calculated(self):
        """Apply calculated values to spinboxes."""
        if hasattr(self, '_calculated_C'):
            self.c_spin.setValue(self._calculated_C)
            self.p_spin.setValue(self._calculated_P)
            self.q_spin.setValue(self._calculated_Q)
            self.result_label.setText("✅ Values applied")
            self.apply_btn.setVisible(False)
    
    def _do_apply(self):
        """Internal apply handler."""
        self.apply_calculated()
        self.apply_clicked.emit()


class SwirEstimationGroup(QWidget):
    """Swirr estimation parameters widget."""
    
    params_changed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        form = QFormLayout()
        
        # Swirr method
        self.method_combo = QComboBox()
        self.method_combo.addItems([
            "Hierarchical (Recommended)",
            "Buckles Number",
            "Clean Zone",
            "Statistical",
            "All Methods"
        ])
        form.addRow("Method:", self.method_combo)
        layout.addLayout(form)
        
        # Buckles preset
        self.buckles_frame = QFrame()
        buckles_layout = QFormLayout(self.buckles_frame)
        
        self.buckles_combo = QComboBox()
        self.buckles_combo.addItems([
            "Sandstone (Clean)",
            "Sandstone (Shaly)",
            "Carbonate",
            "Custom"
        ])
        buckles_layout.addRow("Buckles Preset:", self.buckles_combo)
        
        self.k_buckles_spin = QDoubleSpinBox()
        self.k_buckles_spin.setRange(0.005, 0.1)
        self.k_buckles_spin.setValue(0.02)
        self.k_buckles_spin.setSingleStep(0.005)
        self.k_buckles_spin.setDecimals(3)
        self.k_buckles_spin.setVisible(False)
        buckles_layout.addRow("K_buckles:", self.k_buckles_spin)
        
        self.buckles_info = QLabel("K_buckles = 0.02")
        self.buckles_info.setStyleSheet("color: #4A4540; background-color: transparent;")
        buckles_layout.addRow("", self.buckles_info)
        
        layout.addWidget(self.buckles_frame)
        
        # Method info
        self.method_info = QLabel("✓ Best for no-core calibration")
        self.method_info.setStyleSheet("color: green;")
        layout.addWidget(self.method_info)
        
        # Connect signals
        self.method_combo.currentTextChanged.connect(self._on_method_changed)
        self.buckles_combo.currentTextChanged.connect(self._on_buckles_changed)
        self.k_buckles_spin.valueChanged.connect(lambda: self.params_changed.emit())
    
    def _on_method_changed(self, text: str):
        show_buckles = text in ["Hierarchical (Recommended)", "Buckles Number", "All Methods"]
        self.buckles_frame.setVisible(show_buckles)
        
        if text == "Hierarchical (Recommended)":
            self.method_info.setText("✓ Best for no-core calibration")
            self.method_info.setVisible(True)
        else:
            self.method_info.setVisible(False)
        
        self.params_changed.emit()
    
    def _on_buckles_changed(self, text: str):
        presets = {
            "Sandstone (Clean)": 0.02,
            "Sandstone (Shaly)": 0.03,
            "Carbonate": 0.04
        }
        
        if text == "Custom":
            self.k_buckles_spin.setVisible(True)
            self.buckles_info.setVisible(False)
        else:
            self.k_buckles_spin.setVisible(False)
            self.buckles_info.setVisible(True)
            k = presets[text]
            self.k_buckles_spin.setValue(k)
            self.buckles_info.setText(f"K_buckles = {k}")
        
        self.params_changed.emit()
    
    def get_params(self) -> Dict:
        return {
            'method': self.method_combo.currentText(),
            'buckles_preset': self.buckles_combo.currentText(),
            'k_buckles': self.k_buckles_spin.value()
        }


class CutoffParamsGroup(QWidget):
    """Cutoff parameters widget."""
    
    params_changed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Vsh cutoff
        vsh_layout = QHBoxLayout()
        vsh_layout.addWidget(QLabel("Vsh:"))
        self.vsh_slider = QSlider(Qt.Orientation.Horizontal)
        self.vsh_slider.setRange(0, 100)
        self.vsh_slider.setValue(40)
        self.vsh_label = QLabel("0.40")
        vsh_layout.addWidget(self.vsh_slider)
        vsh_layout.addWidget(self.vsh_label)
        layout.addLayout(vsh_layout)
        
        # PHIE cutoff
        phi_layout = QHBoxLayout()
        phi_layout.addWidget(QLabel("PHIE:"))
        self.phi_slider = QSlider(Qt.Orientation.Horizontal)
        self.phi_slider.setRange(0, 30)
        self.phi_slider.setValue(8)
        self.phi_label = QLabel("0.08")
        phi_layout.addWidget(self.phi_slider)
        phi_layout.addWidget(self.phi_label)
        layout.addLayout(phi_layout)
        
        # Sw cutoff
        sw_layout = QHBoxLayout()
        sw_layout.addWidget(QLabel("Sw:"))
        self.sw_slider = QSlider(Qt.Orientation.Horizontal)
        self.sw_slider.setRange(0, 100)
        self.sw_slider.setValue(60)
        self.sw_label = QLabel("0.60")
        sw_layout.addWidget(self.sw_slider)
        sw_layout.addWidget(self.sw_label)
        layout.addLayout(sw_layout)
        
        # Connect signals
        self.vsh_slider.valueChanged.connect(self._on_vsh_changed)
        self.phi_slider.valueChanged.connect(self._on_phi_changed)
        self.sw_slider.valueChanged.connect(self._on_sw_changed)
    
    def _on_vsh_changed(self, value: int):
        self.vsh_label.setText(f"{value/100:.2f}")
        self.params_changed.emit()
    
    def _on_phi_changed(self, value: int):
        self.phi_label.setText(f"{value/100:.2f}")
        self.params_changed.emit()
    
    def _on_sw_changed(self, value: int):
        self.sw_label.setText(f"{value/100:.2f}")
        self.params_changed.emit()
    
    def get_params(self) -> Dict:
        return {
            'vsh_cutoff': self.vsh_slider.value() / 100,
            'phi_cutoff': self.phi_slider.value() / 100,
            'sw_cutoff': self.sw_slider.value() / 100
        }


class GasCorrectionGroup(QWidget):
    """Gas correction parameters widget for PHIE calculation (v1.2)."""
    
    params_changed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Enable checkbox
        self.enable_check = QCheckBox("Enable Gas Correction")
        self.enable_check.setToolTip(
            "Apply gas correction to PHIE calculation.\n"
            "Corrects for gas effect on neutron-density readings."
        )
        layout.addWidget(self.enable_check)
        
        # Parameters frame (shown when enabled)
        self.params_frame = QFrame()
        params_layout = QFormLayout(self.params_frame)
        
        # Info label
        info_label = QLabel("⛽ Corrects N-D crossover in gas zones")
        info_label.setStyleSheet("color: #4A4540; font-style: italic; background-color: transparent;")
        params_layout.addRow(info_label)
        
        # Neutron factor
        self.nphi_spin = QDoubleSpinBox()
        self.nphi_spin.setRange(0.10, 0.50)
        self.nphi_spin.setValue(0.30)
        self.nphi_spin.setSingleStep(0.05)
        self.nphi_spin.setDecimals(2)
        self.nphi_spin.setToolTip("Neutron correction factor (0.2-0.4 typical)")
        params_layout.addRow("NPHI Factor:", self.nphi_spin)
        
        # Density factor
        self.rhob_spin = QDoubleSpinBox()
        self.rhob_spin.setRange(0.05, 0.30)
        self.rhob_spin.setValue(0.15)
        self.rhob_spin.setSingleStep(0.05)
        self.rhob_spin.setDecimals(2)
        self.rhob_spin.setToolTip("Density correction factor (0.1-0.2 typical)")
        params_layout.addRow("RHOB Factor:", self.rhob_spin)
        
        self.params_frame.setVisible(False)
        layout.addWidget(self.params_frame)
        
        # Connect signals
        self.enable_check.toggled.connect(self._on_enabled_changed)
        self.nphi_spin.valueChanged.connect(lambda: self.params_changed.emit())
        self.rhob_spin.valueChanged.connect(lambda: self.params_changed.emit())
    
    def _on_enabled_changed(self, checked: bool):
        self.params_frame.setVisible(checked)
        self.params_changed.emit()
    
    def get_params(self) -> Dict:
        return {
            'enabled': self.enable_check.isChecked(),
            'nphi_factor': self.nphi_spin.value(),
            'rhob_factor': self.rhob_spin.value()
        }
    
    def set_params(self, enabled: bool, nphi_factor: float = 0.30, rhob_factor: float = 0.15):
        """Set parameter values."""
        self.enable_check.setChecked(enabled)
        self.nphi_spin.setValue(nphi_factor)
        self.rhob_spin.setValue(rhob_factor)


class SwModelsGroup(QWidget):
    """
    Water Saturation Models selection and parameters.
    Multi-select for calculation, Single-select for Primary output.
    """
    
    params_changed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 1. Method Selection (Multi-select)
        layout.addWidget(QLabel("Calculate Methods:"))
        self.methods_list = QListWidget()
        self.methods_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.methods_list.setMaximumHeight(100)
        
        methods = ["Archie", "Indonesian", "Simandoux", "Waxman-Smits", "Dual-Water"]
        for m in methods:
            item = QListWidgetItem(m)
            self.methods_list.addItem(item)
            if m == "Simandoux":
                item.setSelected(True)
        
        layout.addWidget(self.methods_list)
        
        # 2. Primary Method (ComboBox)
        form = QFormLayout()
        self.primary_combo = QComboBox()
        self.primary_combo.setToolTip("Result maps to 'SW' and used for Net Pay/Cutoffs")
        form.addRow("Primary Sw:", self.primary_combo)
        layout.addLayout(form)
        
        # 3. Parameters Panels (Conditional)
        # Waxman-Smits Params
        self.ws_frame = QGroupBox("Waxman-Smits Params")
        ws_layout = QFormLayout(self.ws_frame)
        
        self.ws_qv_spin = QDoubleSpinBox()
        self.ws_qv_spin.setRange(0.0, 5.0)
        self.ws_qv_spin.setValue(0.2)
        self.ws_qv_spin.setSingleStep(0.05)
        self.ws_qv_spin.setDecimals(3)
        self.ws_qv_spin.setToolTip("Cation exchange capacity (Qv)")
        
        self.ws_b_spin = QDoubleSpinBox()
        self.ws_b_spin.setRange(0.0, 10.0)
        self.ws_b_spin.setValue(1.0)
        self.ws_b_spin.setSingleStep(0.1)
        self.ws_b_spin.setDecimals(3)
        self.ws_b_spin.setToolTip("Equivalent conductance (B)")
        
        ws_layout.addRow("Qv (meq/ml):", self.ws_qv_spin)
        ws_layout.addRow("B (mho/m):", self.ws_b_spin)
        
        layout.addWidget(self.ws_frame)
        
        # Dual-Water Params
        self.dw_frame = QGroupBox("Dual-Water Params")
        dw_layout = QFormLayout(self.dw_frame)
        
        self.dw_swb_spin = QDoubleSpinBox()
        self.dw_swb_spin.setRange(0.0, 1.0)
        self.dw_swb_spin.setValue(0.1)
        self.dw_swb_spin.setSingleStep(0.01)
        self.dw_swb_spin.setDecimals(2)
        self.dw_swb_spin.setToolTip("Bound water saturation fraction (Swb)")
        
        self.dw_rwb_spin = QDoubleSpinBox()
        self.dw_rwb_spin.setRange(0.01, 50.0)
        self.dw_rwb_spin.setValue(0.2)
        self.dw_rwb_spin.setSingleStep(0.01)
        self.dw_rwb_spin.setDecimals(2)
        self.dw_rwb_spin.setSuffix(" Ω.m")
        self.dw_rwb_spin.setToolTip("Bound water resistivity (Rwb)")
        
        dw_layout.addRow("Swb:", self.dw_swb_spin)
        dw_layout.addRow("Rwb:", self.dw_rwb_spin)
        
        layout.addWidget(self.dw_frame)
        
        # Connect signals
        self.methods_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.primary_combo.currentTextChanged.connect(self._emit_changed)
        
        self.ws_qv_spin.valueChanged.connect(self._emit_changed)
        self.ws_b_spin.valueChanged.connect(self._emit_changed)
        self.dw_swb_spin.valueChanged.connect(self._emit_changed)
        self.dw_rwb_spin.valueChanged.connect(self._emit_changed)
        
        # Initial sync
        self._on_selection_changed()
    
    def _on_selection_changed(self):
        """Handle method selection changes."""
        selected_items = self.methods_list.selectedItems()
        selected_methods = [item.text() for item in selected_items]
        
        # Update visibility
        self.ws_frame.setVisible("Waxman-Smits" in selected_methods)
        self.dw_frame.setVisible("Dual-Water" in selected_methods)
        
        # Update primary combo
        current_primary = self.primary_combo.currentText()
        self.primary_combo.blockSignals(True)
        self.primary_combo.clear()
        
        if not selected_methods:
            self.primary_combo.addItem("None")
        else:
            self.primary_combo.addItems(selected_methods)
            
            # Restore selection if valid, else pick Simandoux or first
            if current_primary in selected_methods:
                self.primary_combo.setCurrentText(current_primary)
            elif "Simandoux" in selected_methods:
                self.primary_combo.setCurrentText("Simandoux")
            else:
                self.primary_combo.setCurrentIndex(0)
        
        self.primary_combo.blockSignals(False)
        self._emit_changed()
    
    def _emit_changed(self):
        self.params_changed.emit()
    
    def get_params(self) -> Dict:
        return {
            'sw_methods': [item.text() for item in self.methods_list.selectedItems()],
            'sw_primary_method': self.primary_combo.currentText(),
            'ws_qv': self.ws_qv_spin.value(),
            'ws_b': self.ws_b_spin.value(),
            'dw_swb': self.dw_swb_spin.value(),
            'dw_rwb': self.dw_rwb_spin.value()
        }
    
    def set_params(self, params: Dict):
        """Restore parameters from dictionary."""
        # Restore parameters
        if 'ws_qv' in params: self.ws_qv_spin.setValue(params['ws_qv'])
        if 'ws_b' in params: self.ws_b_spin.setValue(params['ws_b'])
        if 'dw_swb' in params: self.dw_swb_spin.setValue(params['dw_swb'])
        if 'dw_rwb' in params: self.dw_rwb_spin.setValue(params['dw_rwb'])
        
        # Restore selection
        if 'sw_methods' in params:
            self.methods_list.blockSignals(True)
            methods = params['sw_methods']
            for i in range(self.methods_list.count()):
                item = self.methods_list.item(i)
                item.setSelected(item.text() in methods)
            self.methods_list.blockSignals(False)
            
            # Trigger updates to frames/combo
            self._on_selection_changed()
            
            # Set primary (must do after updating combo options)
            if 'sw_primary_method' in params:
                self.primary_combo.setCurrentText(params['sw_primary_method'])
