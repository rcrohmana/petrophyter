"""
LRLC Workbench tab for Petrophyter PyQt
Opt-in low-resistivity low-contrast (LRLC) analysis: screening, diagnosis (zone causes,
Thomas-Stieber, Pickett, Buckles), remediation (Rt source, laminated sand, pyrite, Qv, Sw basis)
and validation (pay before and after). The tab writes only LRLC settings through LrlcService
and asks for a stale re-check (stale_requested); it never runs the analysis.
"""

import logging

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from modules.lrlc import chain
from modules.lrlc.config import AUX_ROLES, SWIRR_COLUMNS, resolve_lrlc, resolve_lrlc_sources
from modules.lrlc.methods import METHOD_TEXT
from modules.param_scopes import normalize_zone
from services.lrlc_service import LrlcService as svc
from themes.helpers import set_status
from ..widgets.lrlc_buckles import BucklesPanel
from ..widgets.lrlc_common import fmt as _fmt
from ..widgets.lrlc_common import item as _item
from ..widgets.lrlc_common import make_table as _table
from ..widgets.lrlc_common import note as _note
from ..widgets.lrlc_common import scroll_area as _scroll
from ..widgets.lrlc_common import zone_title
from ..widgets.lrlc_diagnosis import ThomasStieberPanel, ZonesPanel
from ..widgets.lrlc_pickett import PickettPanel
from ..widgets.lrlc_remediation import RemediationForm
from ..widgets.lrlc_validation import ValidationPanel
from ..widgets.method_box import MethodReferenceBox
from .rock_typing_tab import fit_table_height

logger = logging.getLogger(__name__)

PANELS = ("screening", "diagnosis", "remediation", "validation")
DIAGNOSIS_SECTIONS = ("zones", "thomas_stieber", "pickett", "buckles")
REMEDIATION_SECTIONS = ("rt_source", "laminated", "pyrite", "clay", "sw_basis")
PANEL_TITLES = {"screening": "Screening", "diagnosis": "Diagnosis",
                "remediation": "Remediation", "validation": "Validation"}

SCOPES = (("project_default", "Project default", "project", False),
          ("project_zone", "Project zone", "project", True),
          ("well_default", "Well default", "well", False),
          ("well_zone", "Well zone", "well", True))

CONTROLS_MIN_WIDTH = 320
CONTROLS_MAX_WIDTH = 380
ALL_ZONES = "All zones"
OTHER_ZONES = "Other zones (default)"
AUTO_KEY = "__auto__"
NONE_KEY = "__none__"
CUT_NONE = 0.04          # cut_sw_target spin minimum: shows "zone Sw cutoff" (None)

# (key, label, kind, lo, hi, decimals, step)
PARAM_ROWS = (
    ("screen_rt_max", "Rt maximum (ohm.m)", "float", 0.2, 100.0, 2, 0.5),
    ("screen_contrast_max", "Rt / Rsh contrast maximum", "float", 0.5, 50.0, 2, 0.5),
    ("screen_min_score", "Minimum criteria met (of 6)", "int", 3, 6, 0, 1),
    ("cut_sw_target", "Rt cutoff Sw target", "cut", CUT_NONE, 0.95, 2, 0.05),
    ("movable_tol", "Movable water tolerance", "float", 0.0, 0.30, 2, 0.01),
)

FALLBACK_LABELS = (("nan", "Invalid step output becomes NaN"),
                   ("previous", "Use the previous Rt (measured Rt for the first step)"))

SCREEN_COLUMNS = ("Zone", "Samples", "Candidate (ft)", "Candidate, not pay (ft)",
                  "% of net reservoir", "Avg PHIE", "Avg VSH", "Avg Sw", "Avg Rt", "Rt cutoff")
CUT_COLUMNS = ("Zone", "Sw target", "Rt cutoff (ohm.m)", "Basis", "Samples")

PLACEHOLDER_TEXT = (
    "LRLC analysis screens for pay that conventional Sw calls wet, and adds the Rt cutoff, "
    "bulk volume water, Pickett and Buckles diagnostics. It is off by default: enabling it adds "
    "diagnostic columns to the next run and leaves Sw, pay and HCPV unchanged until an Rt "
    "correction step is chosen.")
NO_STEPS_NOTE = ("No Rt correction steps are available in this version. "
                 "Sw reads the measured Rt.")
CHAIN_SENTENCE = "Rsh and Rw estimators stay on the measured RT."
RUN_FIRST = "Run the analysis first"
GUARD_RUN_FIRST = ("Run the analysis with Thomas-Stieber switched on to classify laminated zones; "
                   "the guard cannot block anything before that.")


class LrlcTab(QWidget):
    """LRLC Workbench: enable placeholder, then Screening, Diagnosis, Remediation, Validation."""

    stale_requested = pyqtSignal(list)   # well keys to re-check for staleness
    run_all_requested = pyqtSignal()     # "Run All Wells" in the guidance
    zone_changed = pyqtSignal(object)    # header zone selector: a zone name or None (all zones)
    guard_toggled = pyqtSignal(bool)     # the shoulder-bed guard was switched here
    navigate_requested = pyqtSignal(str)  # a page of the Parameters window, e.g. "params.sat"

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self._updating = False
        self._pending_zone = None        # zone asked for while LRLC was off
        self._scope = "project_default"
        self._batch_running = False
        self._setup_ui()
        self.pickett_panel = PickettPanel()
        self.buckles_panel = BucklesPanel()
        self.set_diagnosis_pages(self.pickett_panel, self.buckles_panel)
        self.pickett_panel.stale_requested.connect(self.stale_requested.emit)
        self.zones_panel.zone_selected.connect(self.select_zone)
        self.zones_panel.prepare_requested.connect(self._on_prepare_remedy)
        self.ts_panel.prepare_requested.connect(self._on_prepare_endpoints)
        self.remediation_form.stale_requested.connect(self.stale_requested.emit)
        self.remediation_form.navigate_requested.connect(self.navigate_requested.emit)
        self.remediation_form.zone_changed.connect(self._on_form_zone)
        self.zone_changed.connect(lambda _z: self._render_zone_views())
        self.update_display()
        for signal in (model.analysis_complete, model.project.well_updated,
                       model.project.active_well_changed):
            signal.connect(self._render_guidance)

    # ------------------------------------------------------------------ UI
    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_placeholder())
        self.stack.addWidget(self._build_content())
        outer.addWidget(self.stack)

    def _build_placeholder(self) -> QWidget:
        # A fixed-width column centred by stretches: a word-wrapped QLabel added with an
        # alignment flag loses its height-for-width and gets clipped to one line's height.
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        column = QWidget()
        column.setFixedWidth(560)
        v = QVBoxLayout(column)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        heading = QLabel("LRLC analysis is off")
        font = heading.font()
        font.setPointSizeF(font.pointSizeF() * 1.4)
        font.setBold(True)
        heading.setFont(font)
        heading.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(heading)
        text = QLabel(PLACEHOLDER_TEXT)
        text.setWordWrap(True)
        text.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        set_status(text, "muted")
        v.addWidget(text)
        self.enable_button = QPushButton("Enable LRLC analysis")
        self.enable_button.setProperty("variant", "primary")
        self.enable_button.clicked.connect(self._on_enable_clicked)
        v.addWidget(self.enable_button, 0, Qt.AlignmentFlag.AlignHCenter)
        row.addWidget(column)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)
        return page

    def _build_content(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.addLayout(self._build_header())
        self.panels = QTabWidget()
        self.panels.addTab(self._build_screening(), PANEL_TITLES["screening"])
        self.panels.addTab(self._build_diagnosis(), PANEL_TITLES["diagnosis"])
        self.panels.addTab(self._build_remediation(), PANEL_TITLES["remediation"])
        self.panels.addTab(self._build_validation(), PANEL_TITLES["validation"])
        v.addWidget(self.panels, 1)
        return page

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.well_label = QLabel("")
        self.well_label.setObjectName("SectionLabel")
        row.addWidget(self.well_label)
        row.addWidget(QLabel("Zone"))
        self.zone_combo = QComboBox()
        self.zone_combo.setMinimumWidth(140)
        self.zone_combo.addItem(ALL_ZONES, None)
        self.zone_combo.currentIndexChanged.connect(self._on_zone_changed)
        row.addWidget(self.zone_combo)
        self.status_label = QLabel("")
        set_status(self.status_label, "muted")
        row.addWidget(self.status_label, 1)
        self.guidance_label = QLabel("")
        set_status(self.guidance_label, "warning")
        self.guidance_label.setVisible(False)
        row.addWidget(self.guidance_label)
        self.run_all_button = QPushButton("Run All Wells")
        self.run_all_button.setToolTip("Run the analysis for every well to refresh LRLC results.")
        self.run_all_button.setVisible(False)
        self.run_all_button.clicked.connect(self.run_all_requested.emit)
        row.addWidget(self.run_all_button)
        self.disable_check = QCheckBox("Disable LRLC analysis")
        self.disable_check.setToolTip("Switch LRLC off. All LRLC settings are kept.")
        self.disable_check.toggled.connect(self._on_disable_toggled)
        row.addWidget(self.disable_check)
        return row

    # ---- screening panel
    def _build_screening(self) -> QWidget:
        self.page_scroll_widget = QWidget()
        root = QHBoxLayout(self.page_scroll_widget)
        root.addWidget(self._build_screening_controls(), 0, Qt.AlignmentFlag.AlignTop)
        root.addWidget(self._build_screening_content(), 1, Qt.AlignmentFlag.AlignTop)
        self.page_scroll = _scroll(self.page_scroll_widget)
        return self.page_scroll

    def _build_screening_controls(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(CONTROLS_MIN_WIDTH)
        panel.setMaximumWidth(CONTROLS_MAX_WIDTH)
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)

        def section(text):
            label = QLabel(text.upper())
            label.setObjectName("SectionLabel")
            v.addWidget(label)

        section("Scope")
        self.scope_buttons = {}
        group = QButtonGroup(self)
        for key, text, _level, _zone in SCOPES:
            radio = QRadioButton(text)
            group.addButton(radio)
            self.scope_buttons[key] = radio
            v.addWidget(radio)
        self.scope_buttons[self._scope].setChecked(True)
        for key, radio in self.scope_buttons.items():
            radio.toggled.connect(lambda on, k=key: on and self._on_scope_changed(k))
        self.scope_zone_combo = QComboBox()
        self.scope_zone_combo.currentIndexChanged.connect(self._on_scope_zone_changed)
        v.addWidget(self.scope_zone_combo)

        section("Screening parameters")
        self.param_widgets = {}
        for key, text, kind, lo, hi, decimals, step in PARAM_ROWS:
            v.addWidget(QLabel(text))
            line = QHBoxLayout()
            if kind == "int":
                spin = QSpinBox()
                spin.setRange(int(lo), int(hi))
            else:
                spin = QDoubleSpinBox()
                spin.setRange(lo, hi)
                spin.setDecimals(decimals)
                spin.setSingleStep(step)
                if kind == "cut":
                    spin.setSpecialValueText("zone Sw cutoff")
            set_btn = QPushButton("Set here")
            inherit_btn = QPushButton("Inherit")
            line.addWidget(spin, 1)
            line.addWidget(set_btn)
            line.addWidget(inherit_btn)
            v.addLayout(line)
            source = _note("")
            v.addWidget(source)
            set_btn.clicked.connect(lambda _=False, k=key: self._on_set_here(k))
            inherit_btn.clicked.connect(lambda _=False, k=key: self._on_inherit(k))
            self.param_widgets[key] = {"spin": spin, "source": source, "set": set_btn,
                                       "inherit": inherit_btn, "kind": kind}
        self.cutoffs_label = _note("")
        v.addWidget(self.cutoffs_label)

        section("Indicators")
        self.use_gas_check = QCheckBox("Use the gas flag as a hydrocarbon indicator")
        self.use_rs_check = QCheckBox("Use deep / shallow resistivity separation")
        v.addWidget(self.use_gas_check)
        v.addWidget(self.use_rs_check)
        self.use_gas_check.toggled.connect(
            lambda on: self._on_setting("screening", "use_gas_flag", bool(on)))
        self.use_rs_check.toggled.connect(
            lambda on: self._on_setting("screening", "use_rs", bool(on)))
        v.addWidget(QLabel("Swirr column for the movable-water flag"))
        self.swirr_combo = QComboBox()
        for name in SWIRR_COLUMNS:
            self.swirr_combo.addItem(name, name)
        self.swirr_combo.currentIndexChanged.connect(
            lambda _i: self._on_setting("movable", "swirr_column", self.swirr_combo.currentData()))
        v.addWidget(self.swirr_combo)

        self.curves_group = QGroupBox("Curves")
        grid = QGridLayout(self.curves_group)
        self.curve_combos = {}
        for i, role in enumerate(AUX_ROLES):
            grid.addWidget(QLabel(role), i, 0)
            combo = QComboBox()
            combo.currentIndexChanged.connect(lambda _i, r=role: self._on_curve_changed(r))
            self.curve_combos[role] = combo
            grid.addWidget(combo, i, 1)
        v.addWidget(self.curves_group)
        v.addStretch(1)
        return panel

    def _build_screening_content(self) -> QWidget:
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox("Screening candidates (last run)")
        gl = QVBoxLayout(group)
        self.candidate_note = _note("")
        gl.addWidget(self.candidate_note)
        self.candidate_table = _table(SCREEN_COLUMNS)
        gl.addWidget(self.candidate_table)
        cl.addWidget(group)
        self.screening_box = MethodReferenceBox()
        self.screening_box.set_method(METHOD_TEXT["screening"])
        cl.addWidget(self.screening_box)

        self.rt_cutoff_group = QGroupBox("Rt cutoff overlay")
        rl = QVBoxLayout(self.rt_cutoff_group)
        self.rt_cut_check = QCheckBox("Compute the Rt cutoff (RT_CUT) on Run")
        self.rt_cut_check.setToolTip(
            "Adds RT_CUT, the Rt at which the primary Sw model returns the Sw target. "
            "An overlay only: it changes no Sw, flag or pay.")
        self.rt_cut_check.toggled.connect(
            lambda on: self._on_setting("rt_cutoff", "enabled", bool(on)))
        rl.addWidget(self.rt_cut_check)
        self.cut_note = _note("")
        rl.addWidget(self.cut_note)
        self.cut_table = _table(CUT_COLUMNS)
        rl.addWidget(self.cut_table)
        cl.addWidget(self.rt_cutoff_group)
        self.rt_cutoff_box = MethodReferenceBox()
        self.rt_cutoff_box.set_method(METHOD_TEXT["rt_cutoff"])
        cl.addWidget(self.rt_cutoff_box)
        cl.addStretch(1)
        return content

    # ---- diagnosis panel
    def _build_diagnosis(self) -> QWidget:
        self.zones_panel = ZonesPanel()
        self.ts_panel = ThomasStieberPanel()
        self.diagnosis_tabs = QTabWidget()
        self.diagnosis_tabs.addTab(_scroll(self.zones_panel), "Zones")
        self.diagnosis_tabs.addTab(_scroll(self.ts_panel), "Thomas-Stieber")
        self.diagnosis_tabs.addTab(self._diagnosis_placeholder("pickettPage"), "Pickett")
        self.diagnosis_tabs.addTab(self._diagnosis_placeholder("bucklesPage"), "Buckles")
        return self.diagnosis_tabs

    @staticmethod
    def _diagnosis_placeholder(name) -> QWidget:
        page = QWidget()
        page.setObjectName(name)
        v = QVBoxLayout(page)
        v.addWidget(_note(RUN_FIRST))
        v.addStretch(1)
        return page

    def set_diagnosis_pages(self, pickett_widget, buckles_widget):
        """Swap the Pickett and Buckles sub-tab pages for the real widgets.

        Each widget gets the object name ``pickettPage`` / ``bucklesPage``; the page it
        replaces is deleted. The current sub-tab is kept.
        """
        current = self.diagnosis_tabs.currentIndex()
        for widget, name, title in ((pickett_widget, "pickettPage", "Pickett"),
                                    (buckles_widget, "bucklesPage", "Buckles")):
            if widget is None:
                continue
            index = next((i for i in range(self.diagnosis_tabs.count())
                          if self.diagnosis_tabs.widget(i).objectName() == name),
                         self.diagnosis_tabs.count())
            old = self.diagnosis_tabs.widget(index) if index < self.diagnosis_tabs.count() else None
            widget.setObjectName(name)
            if old is not None:
                self.diagnosis_tabs.removeTab(index)
            self.diagnosis_tabs.insertTab(index, widget, title)
            if old is not None and old is not widget:
                old.deleteLater()
        self.diagnosis_tabs.setCurrentIndex(max(current, 0))

    # ---- remediation panel
    def _build_remediation(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        group = QGroupBox("Rt source")
        self.rt_source_group = group
        gl = QVBoxLayout(group)
        top = QHBoxLayout()
        top.addWidget(QLabel("Write to"))
        self.level_combo = QComboBox()
        self.level_combo.addItem("Active well", "well")
        self.level_combo.addItem("Project", "project")
        self.level_combo.currentIndexChanged.connect(lambda _i: self._render_remediation())
        top.addWidget(self.level_combo)
        top.addStretch(1)
        gl.addLayout(top)
        self.remediation_note = _note("")
        gl.addWidget(self.remediation_note)
        self.rt_source_table = _table(("Zone", "Sw reads"))
        gl.addWidget(self.rt_source_table)
        self.sw_reads_label = QLabel("")
        gl.addWidget(self.sw_reads_label)
        self.chain_note = _note(CHAIN_SENTENCE)
        gl.addWidget(self.chain_note)
        row = QHBoxLayout()
        row.addWidget(QLabel("When a step cannot produce a value"))
        self.fallback_combo = QComboBox()
        for key, text in FALLBACK_LABELS:
            self.fallback_combo.addItem(text, key)
        self.fallback_combo.currentIndexChanged.connect(self._on_fallback_changed)
        row.addWidget(self.fallback_combo)
        row.addStretch(1)
        gl.addLayout(row)
        self.sbc_check = QCheckBox("The mapped RT is shoulder-bed corrected")
        self.sbc_check.setToolTip(
            "Declare the mapped RT curve already shoulder-bed corrected. The laminated-sand "
            "correction is meant for the raw deep RT.")
        self.sbc_check.toggled.connect(self._on_sbc_toggled)
        gl.addWidget(self.sbc_check)
        self.sbc_note = _note("")
        gl.addWidget(self.sbc_note)
        self.guard_check = QCheckBox("Shoulder-bed guard (laminated zones)")
        self.guard_check.toggled.connect(self._on_guard_toggled)
        gl.addWidget(self.guard_check)
        self.guard_status = _note("")
        gl.addWidget(self.guard_status)
        v.addWidget(group)
        self.chain_box = MethodReferenceBox()
        self.chain_box.set_method(METHOD_TEXT["rt_chain"])
        v.addWidget(self.chain_box)
        self.remediation_form = RemediationForm()
        v.addWidget(self.remediation_form)
        v.addStretch(1)
        self.remediation_scroll = _scroll(page)
        return self.remediation_scroll

    # ---- validation panel
    def _build_validation(self) -> QWidget:
        self.validation_panel = ValidationPanel()
        return _scroll(self.validation_panel)

    # ------------------------------------------------------------ model access
    @property
    def _lrlc(self) -> dict:
        return self.model.project.lrlc

    def _ds(self):
        return self.model.active_well

    def _enabled(self) -> bool:
        return bool(self._lrlc.get("enabled"))

    def _all_keys(self):
        return list(self.model.project.keys())

    def _request_stale(self, level="project"):
        if level == "well":
            ds = self._ds()
            self.stale_requested.emit([ds.key] if ds is not None else [])
        else:
            self.stale_requested.emit(self._all_keys())

    def _zones(self):
        """Zone names of the active well plus those either ladder names."""
        ds = self._ds()
        zones = list(self.model.zones_for(ds)) if ds is not None else []
        for params in (self._lrlc.get("params") or {}, (ds.lrlc if ds is not None else None) or {}):
            for z in (params.get("zones") or {}):
                if z not in zones:
                    zones.append(z)
        return zones

    def _ladder_args(self):
        ds = self._ds()
        return (self._lrlc.get("params") or {}), ((ds.lrlc if ds is not None else None) or {})

    # ------------------------------------------------------------ handlers
    def _on_enable_clicked(self):
        svc.set_enabled(self.model, True)
        self._request_stale("project")
        self.update_display()
        if self._pending_zone:
            zone, self._pending_zone = self._pending_zone, None
            self.select_zone(zone)

    def _on_disable_toggled(self, checked):
        if self._updating or not checked:
            return
        svc.set_enabled(self.model, False)
        self._request_stale("project")
        self.update_display()

    def _on_zone_changed(self, *_):
        if self._updating:
            return
        self.zone_changed.emit(self.selected_zone())

    def selected_zone(self):
        """The header zone selector: a zone name, or None for all zones."""
        return self.zone_combo.currentData()

    def _on_scope_changed(self, key):
        self._scope = key
        if not self._updating:
            self._render_params()

    def _on_scope_zone_changed(self, *_):
        if not self._updating:
            self._render_params()

    def _scope_target(self):
        """``(level, zone)`` of the selected scope; ``(None, None)`` when it cannot be written."""
        _key, _text, level, needs_zone = next(s for s in SCOPES if s[0] == self._scope)
        if level == "well" and self._ds() is None:
            return None, None
        zone = None
        if needs_zone:
            zone = self.scope_zone_combo.currentData()
            if not zone:
                return None, None
        return level, zone

    def _on_set_here(self, key):
        level, zone = self._scope_target()
        if level is None:
            return
        w = self.param_widgets[key]
        value = w["spin"].value()
        if w["kind"] == "cut":
            value = None if value <= CUT_NONE + 1e-9 else float(value)
        elif w["kind"] == "int":
            value = int(value)
        if svc.set_param(self.model, level, zone, key, value):
            self._request_stale(level)
            self._render_params()

    def _on_inherit(self, key):
        level, zone = self._scope_target()
        if level is None:
            return
        if svc.clear_param(self.model, level, zone, key):
            self._request_stale(level)
            self._render_params()

    def _on_setting(self, block, key, value):
        if self._updating:
            return
        if svc.set_setting(self.model, block, key, value):
            self._request_stale("project")

    def _on_curve_changed(self, role):
        if self._updating:
            return
        ds = self._ds()
        data = self.curve_combos[role].currentData()
        if ds is None:
            return
        if data == AUTO_KEY:
            changed = svc.clear_curve(self.model, ds, role)
        elif data == NONE_KEY:
            changed = svc.set_curve(self.model, ds, role, None)
        else:
            changed = svc.set_curve(self.model, ds, role, data)
        if changed:
            self._request_stale("well")

    def _remediation_level(self):
        level = self.level_combo.currentData()
        return level if level == "project" or self._ds() is not None else "project"

    def _on_step_toggled(self, zone, name, on):
        if self._updating:
            return
        level = self._remediation_level()
        resolved = resolve_lrlc(*self._ladder_args(), zone)
        names = [n for n in resolved["rt_steps"] if n != name]
        if on:
            names.append(name)
        order = {s.name: i for i, s in enumerate(chain.available_steps())}
        names.sort(key=lambda n: order.get(n, len(order)))
        if svc.set_param(self.model, level, zone, "rt_steps", names):
            self._request_stale(level)
            self._render_remediation()

    def _on_fallback_changed(self, *_):
        if self._updating:
            return
        level = self._remediation_level()
        if svc.set_param(self.model, level, None, "rt_fallback", self.fallback_combo.currentData()):
            self._request_stale(level)

    def _on_sbc_toggled(self, on):
        if self._updating:
            return
        if svc.set_rt_sbc(self.model, self._ds(), bool(on)):
            self._request_stale("well")
            self._render_remediation()

    def _on_guard_toggled(self, on):
        if self._updating:
            return
        if svc.set_guard_enabled(self.model, bool(on)):
            self._request_stale("project")
            self.guard_toggled.emit(bool(on))
            self._render_guard()

    def _on_form_zone(self, zone):
        """The zone selector of the remediation form follows into the header selector."""
        if zone:
            self.select_zone(zone)
        elif self.selected_zone() is not None:
            self.zone_combo.setCurrentIndex(0)      # all zones; emits through _on_zone_changed

    def _on_prepare_remedy(self, zone, remedy):
        """A remedy from the zone diagnosis: fill the Remediation panel, write nothing."""
        if zone:
            self.select_zone(zone)
        self.remediation_form.prepare(zone, remedy=remedy)
        steps = remedy.get("rt_steps") or []
        section = ("laminated" if "laminated" in steps else "pyrite" if "pyrite" in steps
                   else "clay" if remedy.get("qv_source") else "sw_basis")
        self.show_panel("remediation", section)

    def _on_prepare_endpoints(self, zone, values):
        """Thomas-Stieber end-points proposed for a zone: fill the Remediation panel."""
        if zone:
            self.select_zone(zone)
        self.remediation_form.prepare(zone, values=values)
        self.show_panel("remediation", "laminated")

    # ------------------------------------------------------------ display
    def update_display(self):
        """Rebuild everything from the model."""
        was = self._updating
        self._updating = True
        try:
            enabled = self._enabled()
            self.stack.setCurrentIndex(1 if enabled else 0)
            self.disable_check.setChecked(False)
            if enabled:
                self._render_header()
                self._render_zone_combos()
                self._render_params()
                self._render_settings()
                self._render_curves()
                self._render_results()
                self._render_remediation()
                self._render_zone_views()
        finally:
            self._updating = was
        self._render_guidance()

    def _render_zone_views(self):
        """Point the diagnosis, remediation and validation panels at the active well and the
        selected zone."""
        if not self._enabled():
            return
        self._render_diagnosis()
        self._render_remediation_form()
        self._render_guard()
        self._render_sw_reads()
        self.validation_panel.set_context(self.model, self._ds(), self.selected_zone())

    def _render_diagnosis(self):
        ds, zone = self._ds(), self.selected_zone()
        self.zones_panel.set_context(self.model, ds, zone)
        self.ts_panel.set_context(self.model, ds, zone)
        self.pickett_panel.set_context(self.model, ds, zone)
        self.buckles_panel.set_context(self.model, ds, zone)

    def _render_remediation_form(self):
        self.remediation_form.set_context(self.model, self._ds(), self.selected_zone(),
                                          self._zones())

    def _fill_zone_combo(self, combo, first, zones, keep):
        combo.clear()
        if first is not None:
            combo.addItem(first, None)
        for z in zones:
            combo.addItem(z, z)
        i = combo.findData(keep)
        if i >= 0:
            combo.setCurrentIndex(i)

    def _ensure_zone_item(self, combo, zone):
        if combo.findData(zone) < 0:
            combo.addItem(zone, zone)

    def _render_zone_combos(self):
        zones = self._zones()
        was = self._updating
        self._updating = True
        try:
            self._fill_zone_combo(self.zone_combo, ALL_ZONES, zones, self.selected_zone())
            self._fill_zone_combo(self.scope_zone_combo, None, zones,
                                  self.scope_zone_combo.currentData())
        finally:
            self._updating = was

    def _render_header(self):
        ds = self._ds()
        self.well_label.setText(f"Well: {getattr(ds, 'name', None) or ds.key}" if ds is not None
                                else "No well loaded")
        if ds is None:
            text, status = "Load a well, then run the analysis", "muted"
        elif (getattr(ds, "summary", None) or {}).get("lrlc"):
            text, status = "LRLC results from the last run", "success"
        elif ds.calculated:
            text, status = "Run the analysis to compute LRLC results", "warning"
        else:
            text, status = "Run the analysis to compute LRLC results", "muted"
        self.set_status(text, status)

    def set_status(self, text, status="muted"):
        self.status_label.setText(text)
        set_status(self.status_label, status)

    def _render_guidance(self, *_):
        stale = any(ds.calculated and ds.stale for ds in self.model.project.wells)
        show = self._enabled() and stale
        self.guidance_label.setText("Run the analysis to refresh LRLC results" if show else "")
        self.guidance_label.setVisible(show)
        self.run_all_button.setVisible(show)
        self.run_all_button.setEnabled(not self._batch_running)
        if self._enabled():
            self._render_header()

    def set_batch_running(self, running: bool):
        """Run All Wells is unavailable while a batch is running."""
        self._batch_running = bool(running)
        self.run_all_button.setEnabled(not self._batch_running)

    def _render_params(self):
        ds = self._ds()
        was = self._updating
        self._updating = True
        try:
            for key, radio in self.scope_buttons.items():
                level = next(s[2] for s in SCOPES if s[0] == key)
                radio.setEnabled(level == "project" or ds is not None)
                radio.setChecked(key == self._scope)
            needs_zone = next(s[3] for s in SCOPES if s[0] == self._scope)
            self.scope_zone_combo.setEnabled(needs_zone)
            level, zone = self._scope_target()
            sources = resolve_lrlc_sources(*self._ladder_args(),
                                           zone if needs_zone else None)
            for key, w in self.param_widgets.items():
                value, src = sources[key]
                spin = w["spin"]
                if w["kind"] == "cut":
                    spin.setValue(CUT_NONE if value is None else float(value))
                elif w["kind"] == "int":
                    spin.setValue(int(value))
                else:
                    spin.setValue(float(value))
                shown = "zone Sw cutoff" if value is None else f"{value:g}"
                w["source"].setText(f"Resolved: {shown} ({src})")
                w["set"].setEnabled(level is not None)
                w["inherit"].setEnabled(level is not None)
            self._render_cutoffs(zone if needs_zone else None)
        finally:
            self._updating = was

    def _render_cutoffs(self, zone):
        ds = self._ds()
        text = ""
        if ds is not None:
            try:
                flat = self.model.params_for_well(ds)
                plan = (flat.get("zone_plan") or {}).get(zone) if zone else None
                p = plan["params"] if plan and plan.get("params") else flat
                text = (f"Vsh < {_fmt(p.get('vsh_cutoff'))}, PHIE > {_fmt(p.get('phi_cutoff'))}, "
                        f"Sw >= {_fmt(p.get('sw_cutoff'))} (pay cutoffs of this zone, set on the "
                        "Parameters window)")
            except Exception:                       # a well still loading has no parameters yet
                logger.debug("cutoffs unavailable", exc_info=True)
        if not text:
            text = "Vsh, PHIE and Sw cutoffs are the pay cutoffs of the zone (Parameters window)"
        self.cutoffs_label.setText(text)

    def _render_settings(self):
        was = self._updating
        self._updating = True
        try:
            lrlc = self._lrlc
            self.use_gas_check.setChecked(bool((lrlc.get("screening") or {}).get("use_gas_flag")))
            self.use_rs_check.setChecked(bool((lrlc.get("screening") or {}).get("use_rs")))
            self.rt_cut_check.setChecked(bool((lrlc.get("rt_cutoff") or {}).get("enabled")))
            i = self.swirr_combo.findData((lrlc.get("movable") or {}).get("swirr_column"))
            if i >= 0:
                self.swirr_combo.setCurrentIndex(i)
        finally:
            self._updating = was

    def _auto_curve(self, ds, role):
        try:
            from modules.las_parser import find_curve
            return find_curve(list(ds.las_data.columns), role)
        except Exception:
            return None

    def _render_curves(self):
        ds = self._ds()
        was = self._updating
        self._updating = True
        try:
            columns = [str(c) for c in ds.las_data.columns] if (
                ds is not None and getattr(ds, "las_data", None) is not None) else []
            assigned = (ds.lrlc_curves if ds is not None else None) or {}
            for role, combo in self.curve_combos.items():
                combo.setEnabled(ds is not None)
                combo.clear()
                auto = self._auto_curve(ds, role) if ds is not None else None
                combo.addItem(f"Auto ({auto})" if auto else "Auto (none found)", AUTO_KEY)
                combo.addItem("Not used", NONE_KEY)
                for name in columns:
                    combo.addItem(name, name)
                if role not in assigned:
                    combo.setCurrentIndex(0)
                elif assigned[role] is None:
                    combo.setCurrentIndex(1)
                else:
                    i = combo.findData(assigned[role])
                    if i < 0:
                        combo.addItem(assigned[role], assigned[role])
                        i = combo.count() - 1
                    combo.setCurrentIndex(i)
        finally:
            self._updating = was

    def _lrlc_summary(self) -> dict:
        ds = self._ds()
        return ((getattr(ds, "summary", None) or {}).get("lrlc") or {}) if ds is not None else {}

    def _render_results(self):
        summary = self._lrlc_summary()
        screening = summary.get("screening") or {}
        rows = screening.get("zones") or []
        self.candidate_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values = (row.get("zone"), row.get("n"), _fmt(row.get("candidate_ft"), 1),
                      _fmt(row.get("candidate_not_pay_ft"), 1), _fmt(row.get("pct_of_net_res"), 1),
                      _fmt(row.get("avg_phie"), 3), _fmt(row.get("avg_vsh"), 3),
                      _fmt(row.get("avg_sw"), 3), _fmt(row.get("avg_rt"), 2),
                      _fmt(row.get("rt_cut"), 2))
            for c, v in enumerate(values):
                self.candidate_table.setItem(r, c, _item(v))
        if rows:
            unavailable = screening.get("unavailable") or []
            self.candidate_note.setText(
                "Criteria not evaluable in this well: " + ", ".join(unavailable)
                if unavailable else "")
        else:
            self.candidate_note.setText(
                "No screening results yet. Run the analysis to list candidate zones.")
        self.candidate_note.setVisible(bool(self.candidate_note.text()))

        cut = summary.get("rt_cutoff") or {}
        cut_rows = cut.get("zones") or []
        self.cut_table.setRowCount(len(cut_rows))
        for r, row in enumerate(cut_rows):
            values = (row.get("zone"), _fmt(row.get("sw_target"), 2), _fmt(row.get("rt_cut"), 2),
                      row.get("basis"), row.get("n"))
            for c, v in enumerate(values):
                self.cut_table.setItem(r, c, _item(v))
        if cut_rows:
            self.cut_note.setText(f"Model: {cut.get('model', '')}")
        elif (self._lrlc.get("rt_cutoff") or {}).get("enabled"):
            self.cut_note.setText("Run the analysis to compute the Rt cutoff.")
        else:
            self.cut_note.setText("Switch the Rt cutoff on, then run the analysis.")
        for table in (self.candidate_table, self.cut_table):
            fit_table_height(table)

    def _render_remediation(self):
        steps = chain.available_steps()
        was = self._updating
        self._updating = True
        try:
            columns = ["Zone", "Sw reads"] + [s.label for s in steps]
            table = self.rt_source_table
            table.clear()
            table.setColumnCount(len(columns))
            table.setHorizontalHeaderLabels(columns)
            zones = [None] + self._zones()
            table.setRowCount(len(zones))
            for r, zone in enumerate(zones):
                resolved = resolve_lrlc(*self._ladder_args(), zone)
                specs, _unknown = chain.resolve_steps(resolved["rt_steps"])
                table.setItem(r, 0, _item(zone or OTHER_ZONES))
                table.setItem(r, 1, _item(chain.chain_path(specs)))
                on = {s.name for s in specs}
                for c, spec in enumerate(steps):
                    box = QCheckBox()
                    box.setChecked(spec.name in on)
                    box.toggled.connect(
                        lambda checked, z=zone, n=spec.name: self._on_step_toggled(z, n, checked))
                    table.setCellWidget(r, 2 + c, box)
            self.remediation_note.setText("" if steps else NO_STEPS_NOTE)
            self.remediation_note.setVisible(not steps)
            fallback = resolve_lrlc(*self._ladder_args(), None)["rt_fallback"]
            i = self.fallback_combo.findData(fallback)
            if i >= 0:
                self.fallback_combo.setCurrentIndex(i)
            if self._ds() is None:
                self.level_combo.setCurrentIndex(self.level_combo.findData("project"))
        finally:
            self._updating = was
        fit_table_height(self.rt_source_table)
        self._render_sw_reads()
        self._render_sbc()
        self._render_guard()
        if self._enabled():
            self._render_remediation_form()

    def _render_sw_reads(self):
        zone = self.selected_zone()
        resolved = resolve_lrlc(*self._ladder_args(), zone)
        specs, _unknown = chain.resolve_steps(resolved["rt_steps"])
        where = zone_title(zone) if zone else OTHER_ZONES
        self.sw_reads_label.setText(f"Sw reads: {chain.chain_path(specs)} ({where})")

    def _render_sbc(self):
        was = self._updating
        self._updating = True
        try:
            ds = self._ds()
            mapped = (getattr(ds, "curve_mapping", None) or {}).get("RT") if ds is not None else None
            marked = (getattr(ds, "lrlc_curves", None) or {}).get("RT_SBC") if ds is not None else None
            self.sbc_check.setEnabled(bool(mapped))
            self.sbc_check.setChecked(bool(marked) and marked == mapped)
            if marked and marked != mapped:
                self.sbc_note.setText(
                    f"The marked curve {marked} is no longer the mapped RT, so the mark is "
                    "ignored.")
            elif marked:
                self.sbc_note.setText(
                    f"{marked} is marked shoulder-bed corrected. In laminated zones with the "
                    "laminated-sand correction, map the raw deep RT instead.")
            else:
                self.sbc_note.setText("")
            self.sbc_note.setVisible(bool(self.sbc_note.text()))
        finally:
            self._updating = was

    @staticmethod
    def _guard_lines(summary_guard, zone):
        lines = []
        for z in summary_guard.get("zones", []):
            name = z.get("zone")
            if zone is not None and name != zone:
                continue
            where = f"Zone {name}" if name else "the unzoned interval"
            if not z.get("laminated"):
                lines.append(f"{where}: not laminated.")
                continue
            share = _fmt(z.get("lam_share"), 2)
            lines.append(f"{where}: laminated (laminar share {share}).")
            for step in z.get("blocked_steps") or []:
                lines.append(f"{step} not applied in {where}: laminated (guard); use the "
                             "laminated-sand correction.")
            if z.get("sbc_rt"):
                lines.append(f"RT is marked shoulder-bed corrected in {where}, which is "
                             "laminated: map the raw deep RT and use the laminated-sand "
                             "correction.")
        return lines

    def _render_guard(self):
        was = self._updating
        self._updating = True
        try:
            enabled = bool((self._lrlc.get("guard") or {}).get("enabled", True))
            self.guard_check.setChecked(enabled)
            guard = self._lrlc_summary().get("guard")
            head = "The guard is on." if enabled else "The guard is off: it only warns."
            if not guard:
                text = f"{head} {GUARD_RUN_FIRST}"
            else:
                lines = self._guard_lines(guard, self.selected_zone())
                text = "\n".join([head] + lines)
            self.guard_status.setText(text)
        finally:
            self._updating = was

    # ------------------------------------------------------------ navigation
    def show_panel(self, name, section=None):
        """Select a panel ("screening", "diagnosis", "remediation", "validation") and scroll to
        a section of it: ``"rt_cutoff"`` or ``"curves"`` on Screening; ``"zones"``,
        ``"thomas_stieber"``, ``"pickett"`` or ``"buckles"`` on Diagnosis; ``"rt_source"``,
        ``"laminated"``, ``"pyrite"``, ``"clay"`` or ``"sw_basis"`` on Remediation."""
        if name in PANELS:
            self.panels.setCurrentIndex(PANELS.index(name))
        if name == "screening" and section:
            target = {"rt_cutoff": self.rt_cutoff_group, "curves": self.curves_group}.get(section)
            if target is not None:
                self.page_scroll.ensureWidgetVisible(target)
        elif name == "diagnosis" and section in DIAGNOSIS_SECTIONS:
            self.diagnosis_tabs.setCurrentIndex(DIAGNOSIS_SECTIONS.index(section))
        elif name == "remediation" and section in REMEDIATION_SECTIONS:
            self._scroll_remediation(section)
            # The page may not be laid out yet (the tab was hidden): scroll again once it is.
            QTimer.singleShot(0, lambda s=section: self._scroll_remediation(s))

    def _scroll_remediation(self, section):
        target = (self.rt_source_group if section == "rt_source"
                  else self.remediation_form.scroll_target(section))
        if target is not None:
            self.remediation_scroll.ensureWidgetVisible(target, 0, 0)

    def select_zone(self, zone):
        """Select a zone in the zone selectors and the Diagnosis zone table. With LRLC off the
        zone is remembered and applied after Enable."""
        z = normalize_zone(zone) if zone else None
        if not self._enabled():
            self._pending_zone = z
            return
        if not z:
            return
        was = self._updating
        self._updating = True
        try:
            for combo in (self.zone_combo, self.scope_zone_combo):
                self._ensure_zone_item(combo, z)
                combo.setCurrentIndex(combo.findData(z))
        finally:
            self._updating = was
        self._render_params()
        self.zone_changed.emit(z)

    # ------------------------------------------------------------ lifecycle
    def refresh_theme(self):
        self._render_guidance()
        self.pickett_panel.refresh_theme()
        self.buckles_panel.refresh_theme()
        self.ts_panel.refresh_theme()
        self.remediation_form.refresh_theme()
        self.validation_panel.refresh_theme()

    def reset_ui(self):
        """Reset for New Project: back to the placeholder with empty selections."""
        self._pending_zone = None
        self._scope = "project_default"
        self.panels.setCurrentIndex(0)
        self.update_display()
