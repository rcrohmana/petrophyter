"""Modeless Parameters window (spec §2.5): every analysis parameter, one page per menu item.

Scopes (multi-well spec §4): a scope bar on top selects what the pages edit.
At Project scope (no zone) the pages read and write the flat project values exactly
as before. At any other scope the pages show ``model.scope_view()``: values set in
that scope look normal, inherited values are muted with a "From …" tooltip, and the
model is only ever written through explicit user intent (an edit, or a choice in a
field's mode menu) — never by comparing a widget value with the inherited one.
"""
import datetime
from contextlib import contextmanager
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget,
)

from modules.param_scopes import (
    ARCHIE_KEYS, AUTO, AUTO_PARAMS, GR_MANUAL, INHERIT, LITHOLOGY_CUSTOM, LITHOLOGY_PRESETS,
    MANUAL, SPECS, flat_value, temperature_readout, validate_entry,
)
from .widgets.parameter_groups import (
    AnalysisModeGroup, ArchieParamsGroup, CurveMappingGroup, CutoffParamsGroup,
    FieldModeControl, FluidParamsGroup, GasCorrectionGroup, MatrixParamsGroup,
    PermParamsGroup, PorosityMethodGroup, ResistivityParamsGroup, ShaleParamsGroup,
    SwirEstimationGroup, SwModelsGroup, TemperatureGroup, VShaleParamsGroup,
)
from .widgets.scope_bar import ScopeBar
from .widgets.zone_grid import ZoneParamGrid
from themes.helpers import set_status
from themes.icon_loader import get_icon
from themes.tokens import METRICS

# (key, title, menu, icon) in page-list order. MainWindow builds its menus from this.
PAGES = (
    ("scope", "Analysis Scope", "Analysis", "crosshair"),
    ("curves", "Curve Mapping", "Analysis", "spline"),
    ("core", "Core Matching", "Analysis", "cylinder"),
    ("porosity", "Porosity Method", "Parameters", "percent"),
    ("vshale", "VShale", "Parameters", "mountain"),
    ("cutoffs", "Cutoffs", "Parameters", "scissors"),
    ("rock", "Rock Properties", "Parameters", "hexagon"),
    ("sat", "Saturation Models", "Parameters", "droplets"),
    ("perm", "Permeability", "Parameters", "waves-horizontal"),
    ("gas", "Gas Correction", "Corrections", "flame"),
)
# Pages reached from the Parameters window only (not in the main menus).
EXTRA_PAGES = (
    ("zones", "Zones", "Scopes", "layers"),
)
_KEY_ROLE = Qt.ItemDataRole.UserRole + 1
PROJECT_ONLY_TIP = "Project-wide setting"
WELL_ONLY_TIP = "Set per well, not per zone"


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
        self._refreshing = False      # programmatic widget refresh: never creates entries
        self._batch = 0               # >0: several entries are being written together
        self._batch_dirty = False
        self._controls = {}           # parameter name -> FieldModeControl
        self._fields = {}             # parameter name -> binding dict
        self._tips = {}               # widget -> its original tooltip
        self._create_widgets()
        self._build_layout()
        self._bind_scoped_fields()
        self._connect_signals()
        self._connect_model()
        self.set_core_available(False)
        self.refresh_scope_view()

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
        self.temperature_widget = TemperatureGroup()
        self.perm_params_widget = PermParamsGroup()
        self.swir_params_widget = SwirEstimationGroup()
        self.gas_correction_widget = GasCorrectionGroup()
        self.scope_bar = ScopeBar(self.model)
        self.zone_grid = ZoneParamGrid(self.model)
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
                              ("Resistivity", self.res_params_widget),
                              ("Temperature", self.temperature_widget)),
            "perm": self._page(("Coefficients", self.perm_params_widget),
                               ("Swirr estimation", self.swir_params_widget)),
            "gas": self._page(self.gas_correction_widget),
            "zones": self._page(self.zone_grid),
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
        for key, title, menu, icon in PAGES + EXTRA_PAGES:
            if menu != last_menu:
                header = QListWidgetItem(menu.upper())
                header.setFlags(Qt.ItemFlag.NoItemFlags)   # QSS ::item:disabled → text_muted
                header.setFont(header_font)
                self.page_list.addItem(header)
                last_menu = menu
            item = QListWidgetItem(get_icon(icon), title)
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
        outer.addWidget(self.scope_bar)
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
        icons = {key: icon for key, _t, _m, icon in PAGES + EXTRA_PAGES}
        for key, (row, _index) in self._rows.items():
            self.page_list.item(row).setIcon(get_icon(icons[key]))
        self.zone_grid.refresh_theme()

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
        self.temperature_widget.params_changed.connect(self._on_params_changed)
        self.perm_params_widget.params_changed.connect(self._on_params_changed)
        self.swir_params_widget.params_changed.connect(self._on_params_changed)
        self.cutoff_params_widget.params_changed.connect(self._on_params_changed)
        self.gas_correction_widget.params_changed.connect(self._on_params_changed)

        self.shale_params_widget.calculate_clicked.connect(self.calculate_shale_clicked.emit)
        self.shale_params_widget.apply_clicked.connect(self._on_shale_apply)
        self.res_params_widget.calculate_clicked.connect(self.calculate_rw_rsh_clicked.emit)
        self.res_params_widget.apply_clicked.connect(self._on_rw_rsh_apply)
        self.perm_params_widget.calculate_clicked.connect(self.calculate_perm_clicked.emit)
        self.perm_params_widget.scoped_apply = self._apply_perm_scoped
        self.perm_params_widget.apply_clicked.connect(self._apply_perm_values)

    def _connect_model(self):
        self.model.scope_changed.connect(self.refresh_scope_view)
        self.model.project.active_well_changed.connect(self.refresh_scope_view)
        self.model.scoped_params_changed.connect(self._on_scoped_params_changed)

    def _on_params_changed(self, *args):
        """Handle parameter changes."""
        if self._refreshing:
            return
        self.update_model_from_ui()
        self.parameters_updated.emit()
        self._update_temperature_readout()

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

    # =====================================================================
    # Scopes
    # =====================================================================
    def is_flat_scope(self) -> bool:
        """True at Project scope without a zone: the flat project values."""
        return self.model.edit_scope == "project" and self.model.edit_zone is None

    def _define_fields(self):
        """name -> (anchor widget, widgets that carry the state, value getter)."""
        a, m, n = (self.archie_params_widget.a_spin, self.archie_params_widget.m_spin,
                   self.archie_params_widget.n_spin)
        res, vsh, sw = self.res_params_widget, self.vsh_params_widget, self.sw_models_widget
        perm, cut, tmp = self.perm_params_widget, self.cutoff_params_widget, self.temperature_widget
        mat, flu, sha = self.matrix_params_widget, self.fluid_params_widget, self.shale_params_widget
        field = {}

        def spin(name, widget):
            field[name] = ((widget, [widget], widget.value))

        spin("a", a), spin("m", m), spin("n", n)
        field["lithology_preset"] = (self.archie_params_widget.lithology_combo,
                                     [self.archie_params_widget.lithology_combo],
                                     self.archie_params_widget.lithology_combo.currentText)
        spin("rho_matrix", mat.rho_matrix_spin), spin("dt_matrix", mat.dt_matrix_spin)
        spin("rho_fluid", flu.rho_fluid_spin), spin("dt_fluid", flu.dt_fluid_spin)
        spin("rho_shale", sha.rho_shale_spin), spin("dt_shale", sha.dt_shale_spin)
        spin("nphi_shale", sha.nphi_shale_spin)
        field["gas_correction_enabled"] = (self.gas_correction_widget.enable_check,
                                           [self.gas_correction_widget.enable_check],
                                           self.gas_correction_widget.enable_check.isChecked)
        field["gr_baseline"] = (vsh.baseline_combo,
                                [vsh.baseline_combo, vsh.gr_min_spin, vsh.gr_max_spin],
                                lambda: [vsh.gr_min_spin.value(), vsh.gr_max_spin.value()])
        field["rw"] = (res.rw_auto_cb, [res.rw_spin, res.rw_auto_cb], res.rw_spin.value)
        field["rsh"] = (res.rsh_auto_cb, [res.rsh_spin, res.rsh_auto_cb], res.rsh_spin.value)
        spin("ws_qv", sw.ws_qv_spin), spin("ws_b", sw.ws_b_spin)
        spin("dw_swb", sw.dw_swb_spin), spin("dw_rwb", sw.dw_rwb_spin)
        spin("perm_C", perm.c_spin), spin("perm_P", perm.p_spin), spin("perm_Q", perm.q_spin)
        spin("k_buckles", self.swir_params_widget.k_buckles_spin)
        for name, slider, label, key in (
                ("vsh_cutoff", cut.vsh_slider, cut.vsh_label, "vsh_cutoff"),
                ("phi_cutoff", cut.phi_slider, cut.phi_label, "phi_cutoff"),
                ("sw_cutoff", cut.sw_slider, cut.sw_label, "sw_cutoff")):
            field[name] = (slider, [slider, label],
                           lambda k=key: self.cutoff_params_widget.get_params()[k])
        field["temp_correction"] = (tmp.enable_check, [tmp.enable_check], tmp.enable_check.isChecked)
        spin("surface_temp", tmp.surface_spin), spin("rw_ref_temp", tmp.ref_spin)
        spin("temp_datum_depth", tmp.datum_spin)
        field["rsh_ref_temp"] = (tmp.rsh_ref_spin, [tmp.rsh_ref_spin], tmp.rsh_ref_value)
        field["ws_b_auto"] = (tmp.ws_b_check, [tmp.ws_b_check], tmp.ws_b_check.isChecked)
        field["temp_gradient"] = (tmp.grad_auto_cb, [tmp.gradient_spin, tmp.grad_auto_cb],
                                  tmp.gradient_spin.value)
        return field

    def _project_only_widgets(self):
        sha, gas = self.shale_params_widget, self.gas_correction_widget
        return [
            self.porosity_method_widget.combo, self.vsh_params_widget.method_list,
            sha.approach_combo, sha.selection_mode_combo, sha.vsh_threshold_spin,
            sha.vsh_quantile_spin, sha.sweep_tmin_spin, sha.sweep_tmax_spin,
            sha.sweep_step_spin, sha.min_points_spin, sha.gate_logs_check,
            sha.iqr_filter_check, self.sw_models_widget.methods_list,
            self.sw_models_widget.primary_combo, self.swir_params_widget.method_combo,
            self.swir_params_widget.buckles_combo, gas.nphi_spin, gas.rhob_spin,
        ]

    def _bind_scoped_fields(self):
        """Add a mode control to every scoped field and hook its edit signals."""
        for name, (anchor, widgets, getter) in self._define_fields().items():
            control = FieldModeControl(name, anchor, auto=SPECS[name].auto)
            control.mode_chosen.connect(self._on_mode_chosen)
            control.copy_requested.connect(self.copy_field)
            control.promote_requested.connect(self.promote_field)
            self._controls[name] = control
            self._fields[name] = {"anchor": anchor, "widgets": widgets, "get": getter}
        res, vsh, tmp = self.res_params_widget, self.vsh_params_widget, self.temperature_widget
        arch, swir = self.archie_params_widget, self.swir_params_widget
        # Plain value edits -> Manual in the edited scope.
        for name in ("a", "m", "n"):
            self._on_edit(self._fields[name]["anchor"].valueChanged, name, arch)
        for name in ("rho_matrix", "dt_matrix", "rho_fluid", "dt_fluid", "rho_shale",
                     "dt_shale", "nphi_shale", "ws_qv", "ws_b", "dw_swb", "dw_rwb",
                     "perm_C", "perm_P", "perm_Q", "surface_temp", "rw_ref_temp",
                     "temp_datum_depth", "rsh_ref_temp"):
            self._on_edit(self._fields[name]["anchor"].valueChanged, name)
        self._on_edit(swir.k_buckles_spin.valueChanged, "k_buckles", swir)
        for name in ("vsh_cutoff", "phi_cutoff", "sw_cutoff"):
            self._on_edit(self._fields[name]["anchor"].valueChanged, name)
        for name in ("gas_correction_enabled", "temp_correction", "ws_b_auto"):
            self._on_edit(self._fields[name]["anchor"].toggled, name)
        # Fields with an Auto mode.
        self._on_edit(res.rw_spin.valueChanged, "rw")
        self._on_edit(res.rsh_spin.valueChanged, "rsh")
        self._on_edit(tmp.gradient_spin.valueChanged, "temp_gradient")
        res.rw_auto_cb.toggled.connect(lambda checked: self._on_auto_toggled("rw", checked))
        res.rsh_auto_cb.toggled.connect(lambda checked: self._on_auto_toggled("rsh", checked))
        res.rsh_auto_cb.toggled.connect(lambda checked: tmp.set_rsh_manual(not checked))
        tmp.grad_auto_cb.toggled.connect(lambda checked: self._on_auto_toggled("temp_gradient", checked))
        vsh.baseline_combo.currentTextChanged.connect(self._on_gr_mode_edit)
        self._on_edit(vsh.gr_min_spin.valueChanged, "gr_baseline")
        self._on_edit(vsh.gr_max_spin.valueChanged, "gr_baseline")
        arch.lithology_combo.currentTextChanged.connect(self._on_lithology_edit)

    def _on_edit(self, signal, name, guard_group=None):
        signal.connect(lambda *_a: self._on_scoped_edit(name, guard_group))

    # ---- explicit-intent writers ----
    @contextmanager
    def _writing(self):
        """Group several entry writes into one refresh and one ``parameters_updated``."""
        self._batch += 1
        try:
            yield
        finally:
            self._batch -= 1
            if self._batch == 0 and self._batch_dirty:
                self._batch_dirty = False
                self._after_entry_change()

    def _set_entry(self, name, mode, value=None, **meta) -> bool:
        try:
            self.model.set_entry(name, mode, value, **meta)
        except ValueError:
            return False
        return True

    def _can_write(self) -> bool:
        return not self._refreshing and not self.is_flat_scope()

    def _on_scoped_edit(self, name, guard_group=None):
        if not self._can_write() or getattr(guard_group, "updating", False):
            return
        if name in ARCHIE_KEYS and self._preset_here():
            # Typing a/m/n over a preset: explicit intent, the preset becomes Custom.
            with self._writing():
                self._set_entry("lithology_preset", MANUAL, LITHOLOGY_CUSTOM)
                for key in ARCHIE_KEYS:
                    self._set_entry(key, MANUAL, self._fields[key]["get"]())
            return
        self._set_entry(name, MANUAL, self._fields[name]["get"]())

    def _on_auto_toggled(self, name, checked):
        if not self._can_write():
            return
        if checked:
            self._set_entry(name, AUTO)
        else:
            self._set_entry(name, MANUAL, self._fields[name]["get"]())

    def _on_gr_mode_edit(self, text):
        if not self._can_write():
            return
        if text == GR_MANUAL:
            self._set_entry("gr_baseline", MANUAL, self._fields["gr_baseline"]["get"]())
        else:
            self._set_entry("gr_baseline", AUTO)

    def _on_lithology_edit(self, text):
        """Write the preset entry only: a, m, n follow it (spec D, section 6).

        A named preset removes explicit a/m/n at this scope (they would win over
        it). "Custom" keeps the values on screen as explicit a/m/n.
        """
        if not self._can_write():
            return
        with self._writing():
            self._set_entry("lithology_preset", MANUAL, text)
            for key in ARCHIE_KEYS:
                if text == LITHOLOGY_CUSTOM:
                    self._set_entry(key, MANUAL, self._fields[key]["get"]())
                else:
                    try:
                        self.model.clear_entry(key)
                    except ValueError:
                        pass

    def _preset_here(self) -> bool:
        """True when a named lithology preset is set in the edited scope itself."""
        try:
            flat, info = self.model.scope_view()
        except ValueError:
            return False
        return (info["lithology_preset"]["here"]
                and flat.get("lithology_preset") in LITHOLOGY_PRESETS)

    def _on_mode_chosen(self, name, mode):
        if self.is_flat_scope():
            return
        if mode == INHERIT:
            try:
                self.model.clear_entry(name)
            except ValueError:
                pass
        elif mode == AUTO:
            self._set_entry(name, AUTO)
        else:
            self._set_entry(name, MANUAL, self._fields[name]["get"]())

    def _on_scoped_params_changed(self, _well_key=""):
        if self._batch:
            self._batch_dirty = True
            return
        self._after_entry_change()

    def _after_entry_change(self):
        self.refresh_scope_view()
        self.parameters_updated.emit()

    # ---- apply buttons ----
    def _today(self) -> str:
        return datetime.date.today().isoformat()

    def _calculated_rsh_ref(self) -> Optional[float]:
        """Temperature the calculated Rsh is at: the Rw reference with correction on.

        The estimate normalises shale RT to the Rw reference temperature, so an
        applied Rsh keeps that temperature and stays corrected per sample.
        """
        try:
            p = self.model.params_for_well()
        except Exception:
            return None
        return float(p["rw_ref_temp"]) if p.get("temp_correction") else None

    def _on_rw_rsh_apply(self):
        calculated = self.res_params_widget.calculated()
        if calculated is None:
            return
        ref = self._calculated_rsh_ref()
        if self.is_flat_scope():
            self.res_params_widget.apply_calculated()
            spin = self.temperature_widget.rsh_ref_spin
            spin.setValue(spin.minimum() if ref is None else ref)
            return
        date = self._today()
        with self._writing():
            for name, value in zip(("rw", "rsh"), calculated):
                self._set_entry(name, MANUAL, value, source="calibrated",
                                method="Rwa", date=date)
            if ref is not None:
                self._set_entry("rsh_ref_temp", MANUAL, ref, source="calibrated",
                                method="Rwa", date=date)
            else:
                try:
                    self.model.clear_entry("rsh_ref_temp")
                except ValueError:
                    pass
        self.res_params_widget.discard_calculated()

    def _on_shale_apply(self):
        if self.is_flat_scope():
            self.apply_shale_clicked.emit()
            return
        calculated = getattr(self.model, "calculated_shale", None)
        if not calculated:
            return
        date = self._today()
        with self._writing():
            for name in ("rho_shale", "dt_shale", "nphi_shale"):
                if name in calculated:
                    self._set_entry(name, MANUAL, calculated[name], source="calibrated",
                                    method="shale estimate", date=date)
        self.model.shale_method_used = "statistical"

    def _apply_perm_scoped(self, C, P, Q) -> bool:
        if self.is_flat_scope():
            return False
        date = self._today()
        with self._writing():
            for name, value in (("perm_C", C), ("perm_P", P), ("perm_Q", Q)):
                self._set_entry(name, MANUAL, value, source="calibrated",
                                method="core calibration", date=date)
        return True

    # ---- per-field menu: copy / promote ----
    def copy_targets(self, name):
        """``[(label, (scope, zone, well_key)), ...]`` where ``name`` can be copied."""
        spec, zone = SPECS[name], self.model.edit_zone
        if self.is_flat_scope() or (zone and not spec.zone):
            return []
        project, targets = self.model.project, []
        if self.model.edit_scope == "well":
            for well in project.wells:
                if well.key != project.active_key:
                    suffix = f" · {zone}" if zone else ""
                    targets.append((f"{well.display_name or well.key}{suffix}",
                                    ("well", zone, well.key)))
            if zone:
                targets.append((f"Project · {zone} (every well)", ("project", zone, None)))
        else:
            for well in project.wells:
                targets.append((f"{well.display_name or well.key} · {zone}",
                                ("well", zone, well.key)))
        return targets

    def copy_field(self, name):
        """Ask for target scopes, then copy the field's entry there."""
        targets = self.copy_targets(name)
        label = SPECS[name].label
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Copy {label} to…")
        layout = QVBoxLayout(dialog)
        boxes = []
        if not targets:
            layout.addWidget(QLabel("No other scope to copy to."))
        for text, target in targets:
            box = QCheckBox(text)
            layout.addWidget(box)
            boxes.append((box, target))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.copy_field_to(name, [t for box, t in boxes if box.isChecked()])

    def copy_field_to(self, name, targets):
        """Copy this scope's entry (or its effective value, as Manual) to ``targets``."""
        if not targets or self.is_flat_scope():
            return
        entry = self.model.get_entry(name)
        if not (isinstance(entry, dict) and entry.get("mode") in (AUTO, MANUAL)):
            entry = {"mode": MANUAL, "value": self._fields[name]["get"]()}
        with self._writing():
            self.model.copy_entry(name, entry, list(targets))

    def promote_field(self, name):
        """Set the value shown for ``name`` as the project default."""
        self.model.promote_to_project(name, self._fields[name]["get"]())

    # ---- model -> widgets ----
    def refresh_scope_view(self, *_args):
        """Show the values in effect at the edited scope (never writes the model)."""
        if self._refreshing:
            return
        flat_scope = self.is_flat_scope()
        try:
            flat, info = self.model.scope_view()
        except ValueError:      # well scope without a well
            return
        self._refreshing = True
        try:
            self._load_widgets(flat, info)
            self._decorate(flat, info, flat_scope)
        finally:
            self._refreshing = False

    def _load_widgets(self, flat, info):
        def num(key, default=None):
            value = flat.get(key)
            return default if value is None else value

        arch, res, vsh = self.archie_params_widget, self.res_params_widget, self.vsh_params_widget
        arch.set_params(num("a", arch.a_spin.value()), num("m", arch.m_spin.value()),
                        num("n", arch.n_spin.value()),
                        lithology=num("lithology_preset", arch.lithology_combo.currentText()))
        mat, flu, sha = self.matrix_params_widget, self.fluid_params_widget, self.shale_params_widget
        mat.set_params(num("rho_matrix", mat.rho_matrix_spin.value()),
                       num("dt_matrix", mat.dt_matrix_spin.value()))
        flu.set_params(num("rho_fluid", flu.rho_fluid_spin.value()),
                       num("dt_fluid", flu.dt_fluid_spin.value()))
        sha.set_params(num("rho_shale", sha.rho_shale_spin.value()),
                       num("dt_shale", sha.dt_shale_spin.value()),
                       num("nphi_shale", sha.nphi_shale_spin.value()))
        vsh.baseline_combo.setCurrentText(num("vsh_baseline_method", vsh.baseline_combo.currentText()))
        vsh.gr_min_spin.setValue(num("gr_min_manual", vsh.gr_min_spin.value()))
        vsh.gr_max_spin.setValue(num("gr_max_manual", vsh.gr_max_spin.value()))
        res.set_params(num("rw", res.rw_spin.value()), num("rsh", res.rsh_spin.value()),
                       flat.get("rw_mode", "manual"), flat.get("rsh_mode", "manual"))
        sw = self.sw_models_widget
        sw.set_params({k: flat[k] for k in ("ws_qv", "ws_b", "dw_swb", "dw_rwb") if flat.get(k) is not None})
        perm = self.perm_params_widget
        perm.set_params(num("perm_C", perm.c_spin.value()), num("perm_P", perm.p_spin.value()),
                        num("perm_Q", perm.q_spin.value()))
        self.swir_params_widget.k_buckles_spin.setValue(
            num("k_buckles", self.swir_params_widget.k_buckles_spin.value()))
        cut = self.cutoff_params_widget
        cut.set_params(num("vsh_cutoff", cut.vsh_slider.value() / 100),
                       num("phi_cutoff", cut.phi_slider.value() / 100),
                       num("sw_cutoff", cut.sw_slider.value() / 100))
        self.gas_correction_widget.enable_check.setChecked(bool(flat.get("gas_correction_enabled", False)))
        tmp = self.temperature_widget
        tmp.set_params(bool(flat.get("temp_correction", False)),
                       num("surface_temp", tmp.surface_spin.value()),
                       num("temp_gradient", tmp.gradient_spin.value()),
                       num("rw_ref_temp", tmp.ref_spin.value()),
                       gradient_auto=info["temp_gradient"]["mode"] == AUTO
                       and not self.is_flat_scope(),
                       datum=num("temp_datum_depth", 0.0),
                       rsh_ref_temp=flat.get("rsh_ref_temp"),
                       ws_b_auto=bool(flat.get("ws_b_auto", False)))
        tmp.set_rsh_manual(flat.get("rsh_mode", "manual") != "auto")
        self._update_temperature_readout()

    def _update_temperature_readout(self):
        """Temperature at the log ends and the header gradient, for the active well."""
        tmp, ds = self.temperature_widget, self.model.active_well
        if ds is None or ds.las_data is None:
            tmp.set_readout([])
            return
        header = ds.well_info
        flat, _info = self.model.effective_params()
        tmp.set_readout(temperature_readout(
            ds.las_data, ds.curve_mapping.get("TVD"), header.get("depth_reference"), header, flat
        ))

    @staticmethod
    def _source_tip(source: str, here: bool, mode: str) -> str:
        if here:
            if source == "calibrated":
                return "Calibrated at this scope"
            return "Auto: estimated from the data" if mode == AUTO else "Set at this scope"
        if source.startswith("auto"):
            return source
        if source == "calibrated":
            return "From calibration"
        return "From " + source.replace("·", " · ")

    def _tip_for(self, widget, text):
        self._tips.setdefault(widget, widget.toolTip())
        widget.setToolTip(self._tips[widget] if text is None else text)

    def _decorate(self, flat, info, flat_scope):
        zone = self.model.edit_zone
        # Project-only controls: editable at Project scope only.
        for widget in self._project_only_widgets():
            widget.setEnabled(flat_scope)
            self._tip_for(widget, None if flat_scope else PROJECT_ONLY_TIP)
        for name, binding in self._fields.items():
            spec, control = SPECS[name], self._controls[name]
            allowed = flat_scope or not (zone and not spec.zone)
            widgets = binding["widgets"]
            for widget in widgets:
                widget.setEnabled(allowed)
            control.set_active(allowed and not flat_scope)
            if flat_scope:
                for widget in widgets:
                    set_status(widget, None)
                    self._tip_for(widget, None)
                continue
            if not allowed:
                for widget in widgets:
                    set_status(widget, "muted")
                    self._tip_for(widget, WELL_ONLY_TIP)
                continue
            entry = info[name]
            here, mode = entry["here"] and not entry.get("preset"), entry["mode"]
            tip = self._source_tip(entry["source"], here, mode)
            warning = None
            if here and mode != AUTO:
                warning = validate_entry(name, flat_value(name, flat))
            control.show_state(here, mode, "set here" if here else "inherited", tip, warning)
            for widget in widgets:
                set_status(widget, "warning" if warning else (None if here else "muted"))
                self._tip_for(widget, warning or tip)
        # Restore the natural enabled state of fields gated by their Auto box.
        res, tmp = self.res_params_widget, self.temperature_widget
        if self._fields["rw"]["widgets"][0].isEnabled():
            res.rw_spin.setEnabled(not res.rw_auto_cb.isChecked())
        if self._fields["rsh"]["widgets"][0].isEnabled():
            res.rsh_spin.setEnabled(not res.rsh_auto_cb.isChecked())
        if flat_scope or zone:
            tmp.grad_auto_cb.setEnabled(False)
            tmp.gradient_spin.setEnabled(not zone)
        else:
            tmp.gradient_spin.setEnabled(not tmp.grad_auto_cb.isChecked())
        if flat_scope:
            tmp.grad_auto_cb.setToolTip("Auto applies per well")

    # =====================================================================
    # Window -> model (Project scope writes the flat values, as before)
    # =====================================================================
    def update_model_from_ui(self):
        """Update model from UI values.

        At non-project scopes the scoped parameters are skipped: they are written
        only by explicit edits (see ``_on_scoped_edit`` and friends).
        """
        flat = self.is_flat_scope()
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
        if flat:
            self.model.vsh_baseline_method = vsh["baseline_method"]
            self.model.gr_min_manual = vsh["gr_min"]
            self.model.gr_max_manual = vsh["gr_max"]
        self.model.vsh_methods = vsh["methods"]

        # Porosity method
        porosity = self.porosity_method_widget.get_params()
        self.model.primary_phie_method = porosity["primary_phie_method"]

        # Matrix params
        matrix = self.matrix_params_widget.get_params()
        if flat:
            self.model.rho_matrix = matrix["rho_matrix"]
            self.model.dt_matrix = matrix["dt_matrix"]

        # Fluid params
        fluid = self.fluid_params_widget.get_params()
        if flat:
            self.model.rho_fluid = fluid["rho_fluid"]
            self.model.dt_fluid = fluid["dt_fluid"]

        # Shale params
        shale = self.shale_params_widget.get_params()
        self.model.shale_approach = shale["approach"]
        if flat:
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
        if flat:
            self.model.lithology_preset = archie_cfg["lithology"]
            self.model.a = archie_cfg["a"]
            self.model.m = archie_cfg["m"]
            self.model.n = archie_cfg["n"]

        # Sw Models
        sw_cfg = self.sw_models_widget.get_params()
        self.model.sw_methods = sw_cfg["sw_methods"]
        self.model.sw_primary_method = sw_cfg["sw_primary_method"]
        if flat:
            self.model.ws_qv = sw_cfg["ws_qv"]
            self.model.ws_b = sw_cfg["ws_b"]
            self.model.dw_swb = sw_cfg["dw_swb"]
            self.model.dw_rwb = sw_cfg["dw_rwb"]

        # Resistivity params
        if flat:
            res_cfg = self.res_params_widget.get_params()
            self.model.rw = res_cfg["rw"]
            self.model.rsh = res_cfg["rsh"]
            self.model.rw_mode = res_cfg["rw_mode"]
            self.model.rsh_mode = res_cfg["rsh_mode"]

            # Temperature (project defaults)
            temp = self.temperature_widget.get_params()
            self.model.temp_correction = temp["temp_correction"]
            self.model.surface_temp = temp["surface_temp"]
            self.model.temp_gradient = temp["temp_gradient"]
            self.model.rw_ref_temp = temp["rw_ref_temp"]
            self.model.temp_datum_depth = temp["temp_datum_depth"]
            self.model.rsh_ref_temp = temp["rsh_ref_temp"]
            self.model.ws_b_auto = temp["ws_b_auto"]

            # Perm params
            perm = self.perm_params_widget.get_params()
            self.model.perm_C = perm["C"]
            self.model.perm_P = perm["P"]
            self.model.perm_Q = perm["Q"]

        # Swirr params
        swir = self.swir_params_widget.get_params()
        self.model.swirr_method = swir["method"]
        self.model.buckles_preset = swir["buckles_preset"]
        if flat:
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
        if flat:
            self.model.gas_correction_enabled = gas["enabled"]
        self.model.gas_nphi_factor = gas["nphi_factor"]
        self.model.gas_rhob_factor = gas["rhob_factor"]

    def reset_ui(self):
        """Reset the parameter pages to their fresh/initial state."""
        self.curve_mapping_widget.set_available_curves([], None)
        self.analysis_mode_widget.set_formations([])
        self.analysis_mode_widget.whole_well_radio.setChecked(True)
        self.set_core_available(False)
