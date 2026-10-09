"""Modeless Parameters window (spec §2.5): every analysis parameter, one page per menu item."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QScrollArea, QStackedWidget,
    QVBoxLayout, QWidget,
)

from .widgets.parameter_groups import (
    AnalysisModeGroup, ArchieParamsGroup, CurveMappingGroup, CutoffParamsGroup,
    FluidParamsGroup, GasCorrectionGroup, MatrixParamsGroup, PermParamsGroup,
    PorosityMethodGroup, ResistivityParamsGroup, ShaleParamsGroup,
    SwirEstimationGroup, SwModelsGroup, VShaleParamsGroup,
)
from themes.tokens import METRICS

# (key, title, menu) in page-list order. MainWindow builds its menus from this.
PAGES = (
    ("scope", "Analysis Scope", "Analysis"),
    ("curves", "Curve Mapping", "Analysis"),
    ("core", "Core Matching", "Analysis"),
    ("porosity", "Porosity Method", "Parameters"),
    ("vshale", "VShale", "Parameters"),
    ("cutoffs", "Cutoffs", "Parameters"),
    ("rock", "Rock Properties", "Parameters"),
    ("sat", "Saturation Models", "Parameters"),
    ("perm", "Permeability", "Parameters"),
    ("gas", "Gas Correction", "Corrections"),
)
_KEY_ROLE = Qt.ItemDataRole.UserRole + 1


class ParametersWindow(QDialog):
    parameters_updated = pyqtSignal()
    calculate_rw_rsh_clicked = pyqtSignal()
    calculate_shale_clicked = pyqtSignal()
    apply_shale_clicked = pyqtSignal()
    calculate_perm_clicked = pyqtSignal()
    apply_perm_clicked = pyqtSignal()

    def __init__(self, model, parent=None):
        super().__init__(parent, Qt.WindowType.Tool)
        self.model = model
        self.setObjectName("ParametersWindow")
        self.setWindowTitle("Parameters — Petrophyter")
        self.setModal(False)
        self.resize(METRICS["params_window_width"], METRICS["params_window_height"])
        self.setMinimumSize(METRICS["params_window_min_width"], METRICS["params_window_min_height"])
        self._rows = {}
        self._create_widgets()
        self._build_layout()
        self._connect_signals()
        self.set_core_available(False)

    # ---- widgets: same constructors/connections as SidebarPanel had ----
    def _create_widgets(self):
        self.analysis_mode_widget = AnalysisModeGroup()
        self.curve_mapping_widget = CurveMappingGroup()
        self.porosity_method_widget = PorosityMethodGroup()
        self.vsh_params_widget = VShaleParamsGroup()
        self.cutoff_params_widget = CutoffParamsGroup()
        self.matrix_params_widget = MatrixParamsGroup()
        self.fluid_params_widget = FluidParamsGroup()
        self.shale_params_widget = ShaleParamsGroup()
        self.archie_params_widget = ArchieParamsGroup()
        self.sw_models_widget = SwModelsGroup()
        self.res_params_widget = ResistivityParamsGroup()
        self.perm_params_widget = PermParamsGroup()
        self.swir_params_widget = SwirEstimationGroup()
        self.gas_correction_widget = GasCorrectionGroup()
        # Core matching (was under the sidebar's Core Data group)
        self.core_unit_combo = QComboBox()
        self.core_unit_combo.addItems(["Auto", "M", "FT"])
        self.core_dist_spin = QDoubleSpinBox()
        self.core_dist_spin.setRange(0.1, 10.0)
        self.core_dist_spin.setValue(2.0)
        self.core_dist_spin.setSuffix(" ft")
        self.core_note = QLabel("Load core data to set matching options.")
        self.core_note.setObjectName("PlaceholderLabel")

    def _sub(self, text):
        label = QLabel(text.upper())
        label.setObjectName("SectionLabel")
        return label

    def _page(self, *parts):
        """parts: QWidget or (sub_header, QWidget). Returns a scrollable page."""
        body = QWidget()
        body.setObjectName("ParamsPage")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(8)
        for part in parts:
            if isinstance(part, tuple):
                layout.addWidget(self._sub(part[0]))
                part = part[1]
            layout.addWidget(part)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        return scroll

    def _build_layout(self):
        core = QWidget()
        form = QFormLayout(core)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow("Depth unit", self.core_unit_combo)
        form.addRow("Max dist", self.core_dist_spin)
        bodies = {
            "scope": self._page(self.analysis_mode_widget),
            "curves": self._page(self.curve_mapping_widget),
            "core": self._page(self.core_note, core),
            "porosity": self._page(self.porosity_method_widget),
            "vshale": self._page(self.vsh_params_widget),
            "cutoffs": self._page(self.cutoff_params_widget),
            "rock": self._page(("Matrix", self.matrix_params_widget),
                               ("Fluid", self.fluid_params_widget),
                               ("Shale", self.shale_params_widget)),
            "sat": self._page(("Archie", self.archie_params_widget),
                              ("Sw models", self.sw_models_widget),
                              ("Resistivity", self.res_params_widget)),
            "perm": self._page(("Coefficients", self.perm_params_widget),
                               ("Swirr estimation", self.swir_params_widget)),
            "gas": self._page(self.gas_correction_widget),
        }
        self.page_list = QListWidget()
        self.page_list.setObjectName("ParamsPageList")
        self.page_list.setFixedWidth(METRICS["params_page_list_width"])
        self.stack = QStackedWidget()
        self.stack.setObjectName("ParamsStack")
        header_font = QFont()
        header_font.setPointSize(8)
        header_font.setWeight(QFont.Weight.DemiBold)
        last_menu = None
        for key, title, menu in PAGES:
            if menu != last_menu:
                header = QListWidgetItem(menu.upper())
                header.setFlags(Qt.ItemFlag.NoItemFlags)   # QSS ::item:disabled → text_muted
                header.setFont(header_font)
                self.page_list.addItem(header)
                last_menu = menu
            item = QListWidgetItem(title)
            item.setData(_KEY_ROLE, key)
            self.page_list.addItem(item)
            self._rows[key] = (self.page_list.row(item), self.stack.addWidget(bodies[key]))
        self.page_list.currentItemChanged.connect(self._on_page_changed)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.hide)
        footer = QHBoxLayout()
        footer.setContentsMargins(12, 8, 12, 8)
        footer.addStretch()
        footer.addWidget(close_btn)
        main = QHBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        main.addWidget(self.page_list)
        main.addWidget(self.stack, 1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addLayout(main, 1)
        footer_frame = QWidget()
        footer_frame.setObjectName("ParamsFooter")
        footer_frame.setLayout(footer)
        outer.addWidget(footer_frame)
        self.open_page("scope", show=False)

    def _on_page_changed(self, item, _previous):
        if item is not None and item.data(_KEY_ROLE):
            self.stack.setCurrentIndex(self._rows[item.data(_KEY_ROLE)][1])

    def open_page(self, key: str, show: bool = True):
        row, _index = self._rows[key]
        self.page_list.setCurrentRow(row)
        if show:
            self.show()
            self.raise_()
            self.activateWindow()

    def current_page(self) -> str:
        item = self.page_list.currentItem()
        return item.data(_KEY_ROLE) if item else "scope"

    def refresh_theme(self):
        """Re-fetch cached icons (groups with calculate/apply buttons)."""
        for group in (self.shale_params_widget, self.res_params_widget,
                      self.perm_params_widget):
            group.refresh_theme()

    def set_core_available(self, available: bool):
        self.core_unit_combo.setEnabled(available)
        self.core_dist_spin.setEnabled(available)
        self.core_note.setVisible(not available)

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

        self.shale_params_widget.calculate_clicked.connect(self.calculate_shale_clicked.emit)
        self.shale_params_widget.apply_clicked.connect(self.apply_shale_clicked.emit)
        self.res_params_widget.calculate_clicked.connect(self.calculate_rw_rsh_clicked.emit)
        self.res_params_widget.apply_clicked.connect(self.res_params_widget.apply_calculated)
        self.perm_params_widget.calculate_clicked.connect(self.calculate_perm_clicked.emit)
        self.perm_params_widget.apply_clicked.connect(self._apply_perm_values)

    def _on_params_changed(self, *args):
        """Handle parameter changes."""
        self.update_model_from_ui()
        self.parameters_updated.emit()


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

        # Core settings
        self.model.core_depth_unit = self.core_unit_combo.currentText()
        self.model.core_max_dist = self.core_dist_spin.value()

        # Gas correction (v1.2)
        gas = self.gas_correction_widget.get_params()
        self.model.gas_correction_enabled = gas["enabled"]
        self.model.gas_nphi_factor = gas["nphi_factor"]
        self.model.gas_rhob_factor = gas["rhob_factor"]

    def reset_ui(self):
        """Reset the parameter pages to their fresh/initial state."""
        self.curve_mapping_widget.set_available_curves([], None)
        self.analysis_mode_widget.set_formations([])
        self.analysis_mode_widget.whole_well_radio.setChecked(True)
        self.set_core_available(False)
