"""
Sidebar Panel for Petrophyter PyQt
Left panel with file upload and parameter controls.
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
    QFrame,
    QLabel,
    QPushButton,
    QGroupBox,
    QFileDialog,
    QMessageBox,
    QComboBox,
    QDoubleSpinBox,
    QProgressBar,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal
import os
from themes.colors import get_color

from .widgets.parameter_groups import (
    CollapsibleGroupBox,
    AnalysisModeGroup,
    CurveMappingGroup,
    VShaleParamsGroup,
    PorosityMethodGroup,
    MatrixParamsGroup,
    FluidParamsGroup,
    ShaleParamsGroup,
    ArchieParamsGroup,
    ResistivityParamsGroup,
    PermParamsGroup,
    SwirEstimationGroup,
    CutoffParamsGroup,
    GasCorrectionGroup,
    SwModelsGroup,
)


class SidebarPanel(QWidget):
    """
    Left sidebar panel with file upload and parameter controls.
    Replaces Streamlit's st.sidebar.
    """

    # Signals
    las_files_selected = pyqtSignal(list)  # List of file paths
    merge_requested = pyqtSignal()
    tops_file_selected = pyqtSignal(str)
    core_file_selected = pyqtSignal(str)
    run_analysis_clicked = pyqtSignal()
    download_merged_clicked = pyqtSignal()

    # Parameter signals
    parameters_updated = pyqtSignal()
    calculate_rw_rsh_clicked = pyqtSignal()
    calculate_shale_clicked = pyqtSignal()
    apply_shale_clicked = pyqtSignal()
    calculate_perm_clicked = pyqtSignal()
    apply_perm_clicked = pyqtSignal()

    # Session signals (v1.2)
    new_project_clicked = pyqtSignal()
    save_session_clicked = pyqtSignal()
    load_session_clicked = pyqtSignal()

    # Help signal
    help_clicked = pyqtSignal()

    # Theme signal
    theme_toggle_clicked = pyqtSignal()

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.setMinimumWidth(340)  # Slightly wider for better readability
        self.setMaximumWidth(420)  # Increased max width
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """Setup the sidebar UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # === TOP TOOLBAR (New/Save/Load + Theme) ===
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setSpacing(6)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)

        # Session buttons (icon-only)
        self.new_btn = self._create_toolbar_button("📄", "New Project - Clear all data")
        self.new_btn.clicked.connect(self.new_project_clicked.emit)
        toolbar_layout.addWidget(self.new_btn)
        toolbar_layout.setStretchFactor(self.new_btn, 1)

        self.save_session_btn = self._create_toolbar_button("💾", "Save Session")
        self.save_session_btn.clicked.connect(self.save_session_clicked.emit)
        toolbar_layout.addWidget(self.save_session_btn)
        toolbar_layout.setStretchFactor(self.save_session_btn, 1)

        self.load_session_btn = self._create_toolbar_button("📂", "Load Session")
        self.load_session_btn.clicked.connect(self.load_session_clicked.emit)
        toolbar_layout.addWidget(self.load_session_btn)
        toolbar_layout.setStretchFactor(self.load_session_btn, 1)

        # Theme toggle button (auto icon based on current theme)
        self.theme_btn = self._create_toolbar_button("🌙", "Switch to Dark Theme")
        self.theme_btn.clicked.connect(self._on_theme_toggle)
        toolbar_layout.addWidget(self.theme_btn)
        toolbar_layout.setStretchFactor(self.theme_btn, 1)

        main_layout.addLayout(toolbar_layout)

        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Content widget
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setSpacing(10)

        # =====================================================================
        # DATA INPUT SECTION
        # =====================================================================
        self._create_data_input_section()

        # =====================================================================
        # RUN ANALYSIS BUTTON (after data input)
        # =====================================================================
        self.run_btn = QPushButton("🚀 Run Analysis")
        self.run_btn.setStyleSheet(self._get_run_button_style())
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(self.run_analysis_clicked.emit)
        self.content_layout.addWidget(self.run_btn)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.content_layout.addWidget(self.progress_bar)

        # =====================================================================
        # FORMATION TOPS SECTION
        # =====================================================================
        self._create_formation_tops_section()

        # =====================================================================
        # CORE DATA SECTION
        # =====================================================================
        self._create_core_data_section()

        # =====================================================================
        # PARAMETERS SECTION
        # =====================================================================
        self.params_frame = QFrame()
        self.params_layout = QVBoxLayout(self.params_frame)
        self.params_layout.setSpacing(5)
        self._create_parameters_section()
        self.params_frame.setVisible(False)  # Hidden until data loaded
        self.content_layout.addWidget(self.params_frame)

        # Push remaining space to top
        self.content_layout.addStretch()

        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        # Help Button (Bottom Left)
        self.help_btn = QPushButton("❓ About Petrophyter")
        self.help_btn.setFlat(True)
        self.help_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_help_style()
        self.help_btn.clicked.connect(self.help_clicked.emit)
        main_layout.addWidget(self.help_btn)

    def _create_toolbar_button(self, icon: str, tooltip: str) -> QPushButton:
        """Create a styled toolbar button with icon and tooltip."""
        from themes.colors import get_color

        btn = QPushButton(icon)
        btn.setMinimumHeight(32)
        btn.setToolTip(tooltip)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._apply_toolbar_style(btn)
        return btn

    def _apply_toolbar_style(self, btn: QPushButton):
        from themes.colors import get_color

        btn.setStyleSheet(
            f"""
            QPushButton {{
                border: 1px solid {get_color("border")};
                border-radius: 6px;
                background-color: {get_color("bg_surface_alt")};
                font-size: 14px;
                min-width: 0px;
            }}
            QPushButton:hover {{
                background-color: {get_color("bg_surface_hover")};
            }}
            QPushButton:pressed {{
                background-color: {get_color("bg_surface_pressed")};
            }}
            """
        )

    def _get_run_button_style(self) -> str:
        """Get stylesheet for Run Analysis button."""
        from themes.colors import get_color

        return f"""
            QPushButton {{
                background-color: {get_color("primary")};
                color: white;
                font-weight: bold;
                padding: 10px;
                border-radius: 5px;
            }}
            QPushButton:hover {{
                background-color: {get_color("primary_dark")};
            }}
            QPushButton:disabled {{
                background-color: {get_color("primary_light")};
            }}
        """

    def _create_data_input_section(self):
        """Create the data input section."""
        group = QGroupBox("📁 Data Input")
        layout = QVBoxLayout(group)

        # LAS file upload button
        self.las_btn = QPushButton("📂 Open LAS File(s)...")
        self.las_btn.clicked.connect(self._on_open_las)
        layout.addWidget(self.las_btn)

        # File info label
        self.las_info_label = QLabel("")
        self.las_info_label.setWordWrap(True)
        self.las_info_label.setStyleSheet(
            f"color: {get_color('text_secondary')}; background-color: transparent;"
        )
        layout.addWidget(self.las_info_label)

        # Merge controls (hidden by default)
        self.merge_frame = QFrame()
        merge_layout = QVBoxLayout(self.merge_frame)

        merge_layout.addWidget(QLabel("🔗 Multi-LAS Merge"))

        # Merge settings
        settings_layout = QHBoxLayout()
        settings_layout.addWidget(QLabel("Step (ft):"))
        self.merge_step_spin = QDoubleSpinBox()
        self.merge_step_spin.setRange(0.1, 1.0)
        self.merge_step_spin.setValue(0.5)
        self.merge_step_spin.setSingleStep(0.1)
        settings_layout.addWidget(self.merge_step_spin)

        settings_layout.addWidget(QLabel("Gap Limit:"))
        self.merge_gap_spin = QDoubleSpinBox()
        self.merge_gap_spin.setRange(1.0, 50.0)
        self.merge_gap_spin.setValue(5.0)
        self.merge_gap_spin.setSingleStep(1.0)
        settings_layout.addWidget(self.merge_gap_spin)
        merge_layout.addLayout(settings_layout)

        self.merge_btn = QPushButton("🔄 Merge LAS Files")
        self.merge_btn.setStyleSheet(
            f"background-color: {get_color('success')}; color: white;"
        )
        self.merge_btn.clicked.connect(self.merge_requested.emit)
        merge_layout.addWidget(self.merge_btn)

        self.download_merged_btn = QPushButton("📥 Download Merged LAS")
        self.download_merged_btn.clicked.connect(self.download_merged_clicked.emit)
        self.download_merged_btn.setVisible(False)
        merge_layout.addWidget(self.download_merged_btn)

        self.merge_frame.setVisible(False)
        layout.addWidget(self.merge_frame)

        self.content_layout.addWidget(group)

    def _create_formation_tops_section(self):
        """Create formation tops section."""
        group = QGroupBox("📋 Formation Tops")
        layout = QVBoxLayout(group)

        self.tops_btn = QPushButton("📂 Open Formation Tops...")
        self.tops_btn.clicked.connect(self._on_open_tops)
        layout.addWidget(self.tops_btn)

        self.tops_info_label = QLabel("")
        self.tops_info_label.setStyleSheet("color: green;")
        layout.addWidget(self.tops_info_label)

        self.content_layout.addWidget(group)

    def _create_core_data_section(self):
        """Create core data section."""
        group = QGroupBox("🔬 Core Data (Optional)")
        layout = QVBoxLayout(group)

        self.core_btn = QPushButton("📂 Open Core Data...")
        self.core_btn.clicked.connect(self._on_open_core)
        layout.addWidget(self.core_btn)

        # Core settings
        settings = QHBoxLayout()
        settings.addWidget(QLabel("Depth Unit:"))
        self.core_unit_combo = QComboBox()
        self.core_unit_combo.addItems(["Auto", "M", "FT"])
        settings.addWidget(self.core_unit_combo)

        settings.addWidget(QLabel("Max Dist:"))
        self.core_dist_spin = QDoubleSpinBox()
        self.core_dist_spin.setRange(0.1, 10.0)
        self.core_dist_spin.setValue(2.0)
        self.core_dist_spin.setSuffix(" ft")
        settings.addWidget(self.core_dist_spin)
        layout.addLayout(settings)

        self.core_info_label = QLabel("")
        self.core_info_label.setStyleSheet("color: green;")
        layout.addWidget(self.core_info_label)

        self.content_layout.addWidget(group)

    def _create_parameters_section(self):
        """Create reorganized parameter groups for better UX."""

        # =========================================================
        # 📊 ANALYSIS SETTINGS (Always expanded)
        # =========================================================
        analysis_section = CollapsibleGroupBox("📊 Analysis Settings", expanded=True)
        analysis_container = QWidget()
        analysis_layout = QVBoxLayout(analysis_container)
        analysis_layout.setContentsMargins(0, 0, 0, 0)
        analysis_layout.setSpacing(8)

        # Analysis Mode
        self.analysis_mode_widget = AnalysisModeGroup()
        analysis_layout.addWidget(self._create_subsection_label("🎯 Analysis Mode"))
        analysis_layout.addWidget(self.analysis_mode_widget)

        # Curve Mapping
        self.curve_mapping_widget = CurveMappingGroup()
        analysis_layout.addWidget(self._create_subsection_label("🔗 Curve Mapping"))
        analysis_layout.addWidget(self.curve_mapping_widget)

        analysis_section.set_content_widget(analysis_container)
        self.params_layout.addWidget(analysis_section)

        # =========================================================
        # 🔧 BASIC PARAMETERS (Expanded - for beginners)
        # =========================================================
        basic_section = CollapsibleGroupBox("🔧 Basic Parameters", expanded=True)
        basic_container = QWidget()
        basic_layout = QVBoxLayout(basic_container)
        basic_layout.setContentsMargins(0, 0, 0, 0)
        basic_layout.setSpacing(8)

        # Porosity Method
        self.porosity_method_widget = PorosityMethodGroup()
        basic_layout.addWidget(self._create_subsection_label("📊 Porosity Method"))
        basic_layout.addWidget(self.porosity_method_widget)

        # VShale Parameters
        self.vsh_params_widget = VShaleParamsGroup()
        basic_layout.addWidget(self._create_subsection_label("📊 VShale Parameters"))
        basic_layout.addWidget(self.vsh_params_widget)

        # Cutoff Parameters
        self.cutoff_params_widget = CutoffParamsGroup()
        basic_layout.addWidget(self._create_subsection_label("✂️ Cutoff Parameters"))
        basic_layout.addWidget(self.cutoff_params_widget)

        basic_section.set_content_widget(basic_container)
        self.params_layout.addWidget(basic_section)

        # =========================================================
        # 📐 ADVANCED PARAMETERS (Collapsed - for experienced users)
        # =========================================================
        advanced_section = CollapsibleGroupBox("📐 Advanced Parameters", expanded=False)
        advanced_container = QWidget()
        advanced_layout = QVBoxLayout(advanced_container)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(4)

        # --- Rock Properties (Nested Collapsible) ---
        rock_group = CollapsibleGroupBox("🪨 Rock Properties", expanded=False)
        rock_container = QWidget()
        rock_layout = QVBoxLayout(rock_container)
        rock_layout.setContentsMargins(0, 0, 0, 0)
        rock_layout.setSpacing(6)

        self.matrix_params_widget = MatrixParamsGroup()
        self.fluid_params_widget = FluidParamsGroup()
        self.shale_params_widget = ShaleParamsGroup()
        self.shale_params_widget.calculate_clicked.connect(
            self.calculate_shale_clicked.emit
        )
        self.shale_params_widget.apply_clicked.connect(self.apply_shale_clicked.emit)

        rock_layout.addWidget(self._create_mini_label("Matrix:"))
        rock_layout.addWidget(self.matrix_params_widget)
        rock_layout.addWidget(self._create_mini_label("Fluid:"))
        rock_layout.addWidget(self.fluid_params_widget)
        rock_layout.addWidget(self._create_mini_label("Shale:"))
        rock_layout.addWidget(self.shale_params_widget)

        rock_group.set_content_widget(rock_container)
        advanced_layout.addWidget(rock_group)

        # --- Saturation Models (Nested Collapsible) ---
        sat_group = CollapsibleGroupBox("💧 Saturation Models", expanded=False)
        sat_container = QWidget()
        sat_layout = QVBoxLayout(sat_container)
        sat_layout.setContentsMargins(0, 0, 0, 0)
        sat_layout.setSpacing(6)

        self.archie_params_widget = ArchieParamsGroup()
        self.sw_models_widget = SwModelsGroup()
        self.res_params_widget = ResistivityParamsGroup()
        self.res_params_widget.calculate_clicked.connect(
            self.calculate_rw_rsh_clicked.emit
        )
        self.res_params_widget.apply_clicked.connect(
            self.res_params_widget.apply_calculated
        )

        sat_layout.addWidget(self._create_mini_label("Archie:"))
        sat_layout.addWidget(self.archie_params_widget)
        sat_layout.addWidget(self._create_mini_label("Sw Models:"))
        sat_layout.addWidget(self.sw_models_widget)
        sat_layout.addWidget(self._create_mini_label("Resistivity:"))
        sat_layout.addWidget(self.res_params_widget)

        sat_group.set_content_widget(sat_container)
        advanced_layout.addWidget(sat_group)

        # Keep reference for backward compatibility
        self.sw_models_group = sat_group

        # --- Permeability (Nested Collapsible) ---
        perm_group = CollapsibleGroupBox("📈 Permeability", expanded=False)
        perm_container = QWidget()
        perm_layout = QVBoxLayout(perm_container)
        perm_layout.setContentsMargins(0, 0, 0, 0)
        perm_layout.setSpacing(6)

        self.perm_params_widget = PermParamsGroup()
        self.perm_params_widget.calculate_clicked.connect(
            self.calculate_perm_clicked.emit
        )
        self.perm_params_widget.apply_clicked.connect(self._apply_perm_values)
        self.swir_params_widget = SwirEstimationGroup()

        perm_layout.addWidget(self._create_mini_label("Coefficients:"))
        perm_layout.addWidget(self.perm_params_widget)
        perm_layout.addWidget(self._create_mini_label("Swirr Estimation:"))
        perm_layout.addWidget(self.swir_params_widget)

        perm_group.set_content_widget(perm_container)
        advanced_layout.addWidget(perm_group)

        advanced_section.set_content_widget(advanced_container)
        self.params_layout.addWidget(advanced_section)

        # =========================================================
        # ⚡ CORRECTIONS (Collapsed)
        # =========================================================
        corrections_section = CollapsibleGroupBox("⚡ Corrections", expanded=False)
        corrections_container = QWidget()
        corrections_layout = QVBoxLayout(corrections_container)
        corrections_layout.setContentsMargins(0, 0, 0, 0)

        self.gas_correction_widget = GasCorrectionGroup()
        corrections_layout.addWidget(self.gas_correction_widget)

        corrections_section.set_content_widget(corrections_container)
        self.params_layout.addWidget(corrections_section)

    def _create_subsection_label(self, text: str) -> QLabel:
        """Create a styled subsection label."""
        label = QLabel(text)
        label.setStyleSheet(f"""
            font-weight: 600;
            color: {get_color("text_secondary")};
            padding: 4px 0px 2px 0px;
            border-bottom: 1px solid {get_color("border_light")};
            margin-top: 8px;
            background: transparent;
        """)

        return label

    def _create_mini_label(self, text: str) -> QLabel:
        """Create a mini label for nested parameters."""
        label = QLabel(text)
        label.setStyleSheet(
            f"""
            font-weight: 500;
            font-size: 11px;
            color: {get_color("text_secondary")};
            background: transparent;
        """
        )
        return label

    def _connect_signals(self):
        """Connect internal signals."""
        # Parameter changes
        self.curve_mapping_widget.mapping_changed.connect(self._on_params_changed)
        self.analysis_mode_widget.mode_changed.connect(self._on_params_changed)
        self.vsh_params_widget.params_changed.connect(self._on_params_changed)
        self.porosity_method_widget.params_changed.connect(self._on_params_changed)
        self.matrix_params_widget.params_changed.connect(self._on_params_changed)
        self.fluid_params_widget.params_changed.connect(self._on_params_changed)
        self.shale_params_widget.params_changed.connect(self._on_params_changed)
        self.archie_params_widget.params_changed.connect(self._on_params_changed)
        self.sw_models_widget.params_changed.connect(self._on_params_changed)
        self.res_params_widget.params_changed.connect(self._on_params_changed)
        self.perm_params_widget.params_changed.connect(self._on_params_changed)
        self.swir_params_widget.params_changed.connect(self._on_params_changed)
        self.cutoff_params_widget.params_changed.connect(self._on_params_changed)
        self.gas_correction_widget.params_changed.connect(self._on_params_changed)

    def _on_params_changed(self, *args):
        """Handle parameter changes."""
        self.update_model_from_ui()
        self.parameters_updated.emit()

    def _on_open_las(self):
        """Open LAS file dialog."""
        files, _ = QFileDialog.getOpenFileNames(
            self, "Open LAS File(s)", "", "LAS Files (*.las *.LAS);;All Files (*)"
        )
        if files:
            self.las_files_selected.emit(files)

    def _on_open_tops(self):
        """Open formation tops file dialog."""
        file, _ = QFileDialog.getOpenFileName(
            self, "Open Formation Tops", "", "Text Files (*.txt *.csv);;All Files (*)"
        )
        if file:
            self.tops_file_selected.emit(file)

    def _on_open_core(self):
        """Open core data file dialog."""
        file, _ = QFileDialog.getOpenFileName(
            self, "Open Core Data", "", "Text Files (*.txt *.csv);;All Files (*)"
        )
        if file:
            self.core_file_selected.emit(file)

    # =========================================================================
    # PUBLIC METHODS
    # =========================================================================

    def update_las_info(
        self, filename: str, rows: int, curves: int, is_merged: bool = False
    ):
        """Update LAS file info display."""
        if is_merged:
            self.las_info_label.setText(f"✅ Merged: {rows:,} rows, {curves} curves")
            self.las_info_label.setStyleSheet(f"color: {get_color('success')};")
            self.download_merged_btn.setVisible(True)
        else:
            self.las_info_label.setText(
                f"✅ Loaded: {os.path.basename(filename)}\n📊 {rows:,} rows, {curves} curves"
            )
            self.las_info_label.setStyleSheet(f"color: {get_color('success')};")

        # Show parameters section
        self.params_frame.setVisible(True)
        self.run_btn.setEnabled(True)

    def update_multiple_files_info(self, count: int):
        """Show multiple files selected info."""
        self.las_info_label.setText(f"📁 {count} files selected")
        self.las_info_label.setStyleSheet(f"color: {get_color('primary')};")
        self.merge_frame.setVisible(True)

    def update_tops_info(self, count: int):
        """Update formation tops info."""
        self.tops_info_label.setText(f"✅ Loaded {count} formations")

    def update_core_info(self, count: int, unit: str, por_converted: bool = False):
        """Update core data info."""
        msg = f"✅ Loaded {count} samples ({unit})"
        if por_converted:
            msg += "\nℹ️ Porosity auto-converted % → fraction"
        self.core_info_label.setText(msg)

    def update_available_curves(self, curves: list, detected: dict = None):
        """Update curve mapping combos."""
        self.curve_mapping_widget.set_available_curves(curves, detected)

    def update_formations_list(self, formations: list):
        """Update formation list in analysis mode widget."""
        self.analysis_mode_widget.set_formations(formations)

    def show_calculated_rw_rsh(self, rw: float, rsh: float):
        """Show calculated Rw/Rsh values."""
        self.res_params_widget.show_calculated_result(rw, rsh)

    def show_calculated_shale(self, result: dict):
        """Show calculated shale parameters."""
        self.shale_params_widget.show_calculated_result(result)

    def _apply_perm_values(self):
        """Apply calculated permeability coefficients."""
        self.perm_params_widget.apply_calculated()

    def set_progress(self, value: int, message: str = None):
        """Set progress bar value."""
        self.progress_bar.setVisible(value < 100)
        self.progress_bar.setValue(value)
        if message:
            self.progress_bar.setFormat(f"{message} - %p%")

    def update_model_from_ui(self):
        """Update model from UI values."""
        # Analysis mode
        self.model.analysis_mode = self.analysis_mode_widget.get_mode()
        self.model.selected_formations = (
            self.analysis_mode_widget.get_selected_formations()
        )

        # Curve mapping
        for ctype, curve in self.curve_mapping_widget.get_mapping().items():
            self.model.set_curve_mapping(ctype, curve)

        # VShale params
        vsh = self.vsh_params_widget.get_params()
        self.model.vsh_baseline_method = vsh["baseline_method"]
        self.model.gr_min_manual = vsh["gr_min"]
        self.model.gr_max_manual = vsh["gr_max"]
        self.model.vsh_methods = vsh["methods"]

        # Porosity method
        porosity = self.porosity_method_widget.get_params()
        self.model.primary_phie_method = porosity["primary_phie_method"]

        # Matrix params
        matrix = self.matrix_params_widget.get_params()
        self.model.rho_matrix = matrix["rho_matrix"]
        self.model.dt_matrix = matrix["dt_matrix"]

        # Fluid params
        fluid = self.fluid_params_widget.get_params()
        self.model.rho_fluid = fluid["rho_fluid"]
        self.model.dt_fluid = fluid["dt_fluid"]

        # Shale params
        shale = self.shale_params_widget.get_params()
        self.model.shale_approach = shale["approach"]
        self.model.rho_shale = shale["rho_shale"]
        self.model.dt_shale = shale["dt_shale"]
        self.model.nphi_shale = shale["nphi_shale"]
        # Shale estimation settings (v2.0)
        self.model.shale_vsh_threshold = shale.get("shale_vsh_threshold", 0.80)
        self.model.shale_gate_logs = shale.get("shale_gate_logs", True)
        self.model.shale_iqr_filter = shale.get("shale_iqr_filter", True)
        # Adaptive shale threshold params (v2.1)
        self.model.shale_selection_mode = shale.get(
            "shale_selection_mode", "fixed_threshold"
        )
        self.model.shale_vsh_quantile = shale.get("shale_vsh_quantile", 0.90)
        self.model.shale_min_points = shale.get("shale_min_points", 50)
        self.model.shale_sweep_tmin = shale.get("shale_sweep_tmin", 0.65)
        self.model.shale_sweep_tmax = shale.get("shale_sweep_tmax", 0.95)
        self.model.shale_sweep_step = shale.get("shale_sweep_step", 0.02)

        # Archie params
        archie_cfg = self.archie_params_widget.get_params()
        self.model.lithology_preset = archie_cfg["lithology"]
        self.model.a = archie_cfg["a"]
        self.model.m = archie_cfg["m"]
        self.model.n = archie_cfg["n"]

        # Sw Models
        sw_cfg = self.sw_models_widget.get_params()
        self.model.sw_methods = sw_cfg["sw_methods"]
        self.model.sw_primary_method = sw_cfg["sw_primary_method"]
        self.model.ws_qv = sw_cfg["ws_qv"]
        self.model.ws_b = sw_cfg["ws_b"]
        self.model.dw_swb = sw_cfg["dw_swb"]
        self.model.dw_rwb = sw_cfg["dw_rwb"]

        # Resistivity params
        res_cfg = self.res_params_widget.get_params()
        self.model.rw = res_cfg["rw"]
        self.model.rsh = res_cfg["rsh"]

        # Perm params
        perm = self.perm_params_widget.get_params()
        self.model.perm_C = perm["C"]
        self.model.perm_P = perm["P"]
        self.model.perm_Q = perm["Q"]

        # Swirr params
        swir = self.swir_params_widget.get_params()
        self.model.swirr_method = swir["method"]
        self.model.buckles_preset = swir["buckles_preset"]
        self.model.k_buckles = swir["k_buckles"]

        # Cutoff params
        cutoff = self.cutoff_params_widget.get_params()
        self.model.vsh_cutoff = cutoff["vsh_cutoff"]
        self.model.phi_cutoff = cutoff["phi_cutoff"]
        self.model.sw_cutoff = cutoff["sw_cutoff"]

        # Merge settings
        self.model.merge_step = self.merge_step_spin.value()
        self.model.merge_gap_limit = self.merge_gap_spin.value()

        # Core settings
        self.model.core_depth_unit = self.core_unit_combo.currentText()
        self.model.core_max_dist = self.core_dist_spin.value()

        # Gas correction (v1.2)
        gas = self.gas_correction_widget.get_params()
        self.model.gas_correction_enabled = gas["enabled"]
        self.model.gas_nphi_factor = gas["nphi_factor"]
        self.model.gas_rhob_factor = gas["rhob_factor"]

    def reset_ui(self):
        """Reset sidebar UI to fresh/initial state."""
        # Reset LAS info
        self.las_info_label.setText("")
        self.las_info_label.setStyleSheet(
            f"color: {get_color('text_secondary')}; background-color: transparent;"
        )

        # Hide merge controls
        self.merge_frame.setVisible(False)
        self.download_merged_btn.setVisible(False)

        # Reset formation tops info
        self.tops_info_label.setText("")

        # Reset core data info
        self.core_info_label.setText("")

        # Hide parameters section and disable run button
        self.params_frame.setVisible(False)
        self.run_btn.setEnabled(False)

        # Hide progress bar
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)

        # Clear curve mapping
        self.curve_mapping_widget.set_available_curves([], None)

        # Clear formations list
        self.analysis_mode_widget.set_formations([])

    def _on_theme_toggle(self):
        """Handle theme toggle button click."""
        self.theme_toggle_clicked.emit()

    def update_theme_button(self, is_dark: bool):
        """Update theme button icon based on current theme."""
        if is_dark:
            self.theme_btn.setText("☀️")  # Show sun = click to go light
            self.theme_btn.setToolTip("Switch to Light Theme")
        else:
            self.theme_btn.setText("🌙")  # Show moon = click to go dark
            self.theme_btn.setToolTip("Switch to Dark Theme")

    def _apply_help_style(self):
        self.help_btn.setStyleSheet(
            f"text-align: left; padding: 5px; color: {get_color('text_secondary')};"
        )

    def refresh_theme(self):
        """Refresh widget styling when theme changes."""
        # Refresh toolbar buttons
        for btn in [
            self.new_btn,
            self.save_session_btn,
            self.load_session_btn,
            self.theme_btn,
        ]:
            self._apply_toolbar_style(btn)

        # Refresh collapsible groups
        for group in self.findChildren(CollapsibleGroupBox):
            if hasattr(group, "refresh_theme"):
                group.refresh_theme()

        # Refresh Run Analysis button
        self.run_btn.setStyleSheet(self._get_run_button_style())

        # Refresh info labels/help color
        self.las_info_label.setStyleSheet(
            f"color: {get_color('text_secondary')}; background-color: transparent;"
        )
        if hasattr(self, "help_btn"):
            self._apply_help_style()
