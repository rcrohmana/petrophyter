"""Remediation panel of the LRLC Workbench: a list of corrections and the selected one's settings.

The list on the left holds the Rt corrections (Overview, radial invasion, laminated sand,
pyrite) and the saturation corrections (clay Qv, Sw basis, variable m/n), each with its state for
the selected zone. The page on the right edits a scratch copy of the values that apply to the
zone chosen in the LRLC header. Changing a control writes nothing: the one Apply button writes
the changes of every page to the chosen scope, through ``LrlcService.apply_remediation`` (the
ladder values and the Rt steps) and the service calls of the project and well switches, then
asks the owner to mark the wells stale (``stale_requested``). The form never runs the analysis.
"""

import logging
from typing import Any, Dict, List, Optional

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from modules.lrlc import chain
from modules.lrlc.config import LRLC_RANGES, resolve_lrlc
from modules.lrlc.invasion import GENERIC_TOOLS
from modules.lrlc.l2 import resolve_basis
from modules.lrlc.methods import METHOD_TEXT
from modules.lrlc.thomas_stieber import check_endpoints
from services.lrlc_service import LrlcService
from themes.helpers import set_status

from .lrlc_common import fmt, item, make_table, note, scroll_area, zone_title
from .lrlc_diagnosis import lrlc_summary
from .lrlc_mn_invasion import NEW_LABELS, MnInvasionMixin, MultiSpin
from .lrlc_pickett import zone_labels
from .lrlc_ts_plot import PefRhobPlot
from .method_box import MethodReferenceBox

logger = logging.getLogger(__name__)

SECTIONS = ("laminated", "pyrite", "clay", "sw_basis", "variable_mn", "invasion")
# The list of corrections: (heading, ((section key, title), ...)). "rt_source" is the Overview.
SECTION_GROUPS = (
    ("Rt corrections", (("rt_source", "Overview"), ("invasion", "Radial invasion"),
                        ("laminated", "Laminated sand"), ("pyrite", "Pyrite"))),
    ("Saturation", (("clay", "Clay Qv"), ("sw_basis", "Sw basis"),
                    ("variable_mn", "Variable m/n"))),
)
SECTION_TABS = tuple(entry for _heading, entries in SECTION_GROUPS for entry in entries)
SECTION_TITLES = dict(SECTION_TABS)
# Rt steps that have a page of their own (section key = step name) and the text of their switch.
STEP_PAGES = ("invasion", "laminated", "pyrite")
STEP_CHECK_TEXT = {
    "invasion": "Apply the radial invasion correction",
    "laminated": "Apply the laminated-sand correction (Hagiwara)",
    "pyrite": "Apply the pyrite correction",
}
# A step that needs a project switch to produce its input: ticking the step ticks the switch.
STEP_SETTING = {"laminated": "ts_enabled", "pyrite": "vpyr_enabled"}
LIST_WIDTH = 260
SPIN_MAX_WIDTH = 240
COMBO_MAX_WIDTH = 420
PLOT_MIN_WIDTH = 320

OTHER_ZONES = "Other zones (default)"
NO_STEPS_NOTE = ("No Rt correction steps are available in this version. "
                 "Sw reads the measured Rt.")
CHAIN_SENTENCE = "Rsh and Rw estimators stay on the measured RT."
GUARD_RUN_FIRST = ("Run the analysis with Thomas-Stieber switched on to classify laminated zones; "
                   "the guard cannot block anything before that.")
FALLBACK_LABELS = (("nan", "Invalid step output becomes NaN"),
                   ("previous", "Use the previous Rt (measured Rt for the first step)"))

# (key, label, lo, hi, decimals, step, text shown when the value is None or "")
LAMINATED_ROWS = (
    ("phi_max", "Clean-sand porosity (phi_max)", 3, 0.01, "not applied"),
    ("phi_sh", "Shale porosity (phi_sh)", 3, 0.01, "not applied"),
    ("vlam_const", "Constant Vlam (v/v)", 3, 0.05, ""),
    ("hag_vsh_max", "Shale volume limit of the correction", 2, 0.05, ""),
    ("s_warn", "Sensitivity warning limit (s)", 2, 0.05, ""),
    ("s_invalid", "Sensitivity invalid limit (s)", 2, 0.05, ""),
)
PYRITE_ROWS = (
    ("pyr_vpyr", "Constant VPYR (v/v)", 3, 0.01, ""),
    ("pyr_rho", "Pyrite density (g/cc)", 2, 0.05, ""),
    ("pyr_pef", "Pyrite PEF (b/e)", 2, 0.5, ""),
    ("ma_rho", "Matrix density (g/cc)", 3, 0.01, "zone matrix"),
    ("ma_pef", "Matrix PEF (b/e)", 2, 0.1, ""),
    ("sh_rho", "Shale density (g/cc)", 3, 0.01, "zone shale"),
    ("sh_pef", "Shale PEF (b/e)", 2, 0.1, ""),
    ("pyr_f", "Connected pyrite fraction (f)", 2, 0.05, ""),
    ("pyr_rpy", "Pyrite resistivity Rpy (ohm.m)", 4, 0.01, ""),
)
CLAY_ROWS = (
    ("cec_shale", "Shale CEC (meq/100 g)", 1, 1.0, ""),
    ("qv_rho_g", "Grain density for Qv (g/cc)", 3, 0.01, "zone matrix"),
)
NULLABLE = ("phi_max", "phi_sh", "ma_rho", "sh_rho", "qv_rho_g", "rmf")

COMBOS = {
    "vlam_source": (("ts", "Thomas-Stieber split"), ("constant", "Constant value")),
    "pyr_method": (("manual", "Constant VPYR"), ("rhob_pef", "From RHOB and PEF")),
    "qv_source": (("manual", "Constant Qv of the Waxman-Smits parameters"),
                  ("estimate", "Estimate from Vsh and the shale CEC")),
    "sw_basis": (("auto", "Automatic (sand where the laminated step is on)"),
                 ("sand", "Sand laminae"), ("bulk", "Bulk")),
}
KEY_LABELS = {r[0]: r[1] for r in LAMINATED_ROWS + PYRITE_ROWS + CLAY_ROWS}
KEY_LABELS.update({
    "vlam_source": "Vlam source", "pyr_method": "Pyrite method", "qv_source": "Qv source",
    "sw_basis": "Sw basis", "rt_steps": "Rt steps"})
KEY_LABELS.update(NEW_LABELS)

SCOPES = (("zone", "Zone of this well"), ("well", "Well default"), ("project", "Project default"))
# Switches outside the scoped ladder: where each one is written, whatever "Apply to" says.
SETTING_KEYS = {"ts_enabled": ("thomas_stieber", "enabled"), "vpyr_enabled": ("pyrite", "enabled")}
SETTING_LABELS = {
    "ts_enabled": "Thomas-Stieber on (project)",
    "vpyr_enabled": "VPYR column on (project)",
    "rt_fallback": "step fallback",
    "rt_sbc": "RT shoulder-bed mark (this well)",
    "guard_enabled": "shoulder-bed guard (project)",
}
SETTING_SECTION = {"ts_enabled": "laminated", "vpyr_enabled": "pyrite", "rt_fallback": "rt_source",
                   "rt_sbc": "rt_source", "guard_enabled": "rt_source"}
PROJECT_SETTINGS = ("ts_enabled", "vpyr_enabled", "guard_enabled")
SCOPE_NOTE = {
    "zone": "Written to this well for the chosen zone.",
    "well": "Written as the default of this well.",
    "project": "Written as the project default; every well is marked for a re-check.",
}
SCOPE_WHERE = {"zone": "in zone {zone}", "well": "as the default of this well",
               "project": "as the project default"}


def _spin(lo, hi, decimals, step, none_text) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setDecimals(decimals)
    spin.setSingleStep(step)
    if none_text:
        spin.setRange(lo - step, hi)
        spin.setSpecialValueText(none_text)
    else:
        spin.setRange(lo, hi)
    spin.setKeyboardTracking(False)
    spin.setMaximumWidth(SPIN_MAX_WIDTH)
    return spin


LABEL_MIN_WIDTH = 170


class AlignedForm(QFormLayout):
    """A form whose text labels share one minimum width, so the fields of the separate groups of
    a page line up."""

    def addRow(self, label, field=None):  # noqa: N802 - Qt name
        if field is not None and isinstance(label, str):
            label = QLabel(label)
            label.setMinimumWidth(LABEL_MIN_WIDTH)
        if field is None:
            return super().addRow(label)
        return super().addRow(label, field)


def make_form() -> QFormLayout:
    """A form whose fields keep their natural width (the inputs carry their own maximum)."""
    form = AlignedForm()
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    form.setHorizontalSpacing(14)
    return form


def heading(text: str) -> QLabel:
    """A section heading of a page (``QLabel#SectionLabel``)."""
    label = QLabel(text)
    label.setObjectName("SectionLabel")
    return label


def subheading(text: str) -> QLabel:
    """A sub-section heading of a page (``QLabel#SubsectionLabel``)."""
    label = QLabel(text)
    label.setObjectName("SubsectionLabel")
    return label


def side_by_side(left: QVBoxLayout, right: QWidget) -> QHBoxLayout:
    """Controls on the left, a plot (or a column of plots) on the right."""
    row = QHBoxLayout()
    row.addLayout(left, 1)
    right.setMinimumWidth(PLOT_MIN_WIDTH)
    right.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    row.addWidget(right, 1)
    return row


def method_strip(key: str) -> MethodReferenceBox:
    """The one-line Method & Reference strip of a Remediation page."""
    box = MethodReferenceBox(compact=True)
    box.set_method(METHOD_TEXT[key])
    return box


class _ListRow(QWidget):
    """A row of the corrections list: the title and, in muted text, its state for the zone."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 4, 8, 4)
        self.title_label = QLabel(title)
        self.state_label = QLabel("")
        set_status(self.state_label, "muted")
        lay.addWidget(self.title_label)
        lay.addStretch(1)
        lay.addWidget(self.state_label)


class RemediationForm(MnInvasionMixin, QWidget):
    """The Remediation panel: header (Apply to, Apply, Discard), the corrections list and the
    selected correction's page; every page edits the same scratch copy. Public:
    ``set_context``, ``prepare``, ``scroll_target``, ``show_section``, ``current_section``."""

    stale_requested = pyqtSignal(list)
    navigate_requested = pyqtSignal(str)
    panel_requested = pyqtSignal(str, str)  # another LRLC panel and section, e.g. Screening > Curves
    guard_changed = pyqtSignal(bool)        # the shoulder-bed guard was written by Apply
    applied = pyqtSignal(list)              # keys written

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = None
        self.ds = None
        self.zone: Optional[str] = None
        self._zones: List[str] = []
        self._loading = False
        self._loaded_for = None
        self._dirty: set = set()
        self._step_toggles: Dict[str, bool] = {}
        self._settings: Dict[str, Any] = {}
        self._models_hint: List[str] = []
        self._proposal = None
        self._cec = None
        self._mn_proposal = None
        self._fit_coef: Optional[List[float]] = None
        self._building: Optional[str] = None
        self._section_keys: Dict[str, set] = {}
        self.manual_provider = None     # callable(zone) -> manual wet-point boxes
        self.controls: Dict[str, QWidget] = {}
        self.groups: Dict[str, QWidget] = {}
        self.page_headings: Dict[str, QLabel] = {}
        self.step_checks: Dict[str, QCheckBox] = {}
        self._other_step_checks: Dict[str, QCheckBox] = {}
        self._build()

    # ------------------------------------------------------------------ build
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addLayout(self._build_header())
        self.hint_label = note("", "accent")
        self.hint_label.setVisible(False)
        root.addWidget(self.hint_label)
        body = QHBoxLayout()
        body.setSpacing(12)
        self.section_list = QListWidget()
        self.section_list.setObjectName("MethodList")
        self.section_list.setFixedWidth(LIST_WIDTH)
        self.section_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.section_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.section_stack = QStackedWidget()
        self._items: Dict[str, QListWidgetItem] = {}
        self._list_rows: Dict[str, _ListRow] = {}
        self._page_index: Dict[str, int] = {}
        builders = {"rt_source": self._build_overview, "laminated": self._build_laminated,
                    "pyrite": self._build_pyrite, "clay": self._build_clay,
                    "sw_basis": self._build_basis, "variable_mn": self._build_variable_mn,
                    "invasion": self._build_invasion}
        for group, entries in SECTION_GROUPS:
            head = QListWidgetItem(group.upper())
            head.setFlags(Qt.ItemFlag.NoItemFlags)
            font = head.font()
            font.setBold(True)
            head.setFont(font)
            self.section_list.addItem(head)
            for key, title in entries:
                entry = QListWidgetItem()
                entry.setData(Qt.ItemDataRole.UserRole, key)
                row = _ListRow(title)
                entry.setSizeHint(row.sizeHint())
                self.section_list.addItem(entry)
                self.section_list.setItemWidget(entry, row)
                self._items[key] = entry
                self._list_rows[key] = row
                self._building = key
                self._section_keys[key] = set()
                page = QWidget()
                lay = QVBoxLayout(page)
                lay.setContentsMargins(4, 0, 8, 8)
                title_label = heading(title)
                self.page_headings[key] = title_label
                lay.addWidget(title_label)
                builders[key](lay)
                lay.addStretch(1)
                self.groups[key] = page
                area = scroll_area(page)
                area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                self._page_index[key] = self.section_stack.addWidget(area)
        self._building = None
        self.section_list.currentItemChanged.connect(self._on_list_changed)
        body.addWidget(self.section_list)
        body.addWidget(self.section_stack, 1)
        root.addLayout(body, 1)
        self.show_section("rt_source")

    def _on_list_changed(self, current, _previous):
        key = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        if key in self._page_index:
            self.section_stack.setCurrentIndex(self._page_index[key])

    def show_section(self, section: str) -> bool:
        """Select the page of a section key; False for an unknown key."""
        entry = self._items.get(section)
        if entry is None:
            return False
        self.section_list.setCurrentItem(entry)
        self.section_stack.setCurrentIndex(self._page_index[section])
        return True

    def current_section(self) -> Optional[str]:
        entry = self.section_list.currentItem()
        return entry.data(Qt.ItemDataRole.UserRole) if entry is not None else None

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Apply to"))
        self.scope_combo = QComboBox()
        for key, text in SCOPES:
            self.scope_combo.addItem(text, key)
        self.scope_combo.setCurrentIndex(1)
        self.scope_combo.setMaximumWidth(260)
        self.scope_combo.currentIndexChanged.connect(lambda _i: self._on_scope_changed())
        row.addWidget(self.scope_combo)
        self.apply_button = QPushButton("Apply")
        self.apply_button.clicked.connect(self._on_apply)
        row.addWidget(self.apply_button)
        self.discard_button = QPushButton("Discard changes")
        self.discard_button.clicked.connect(self._on_discard)
        row.addWidget(self.discard_button)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        self.pending_label = note("")
        texts.addWidget(self.pending_label)
        self.result_label = note("")
        texts.addWidget(self.result_label)
        row.addSpacing(8)
        row.addLayout(texts, 1)
        return row

    def _register(self, key, widget):
        self.controls[key] = widget
        if self._building is not None:
            self._section_keys[self._building].add(key)
        if isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(lambda _i, k=key: self._touched(k))
        elif isinstance(widget, QCheckBox):
            widget.toggled.connect(lambda _on, k=key: self._touched(k))
        else:
            widget.valueChanged.connect(lambda _v, k=key: self._touched(k))

    def _rows(self, form: QFormLayout, rows):
        for key, label, decimals, step, none_text in rows:
            lo, hi = LRLC_RANGES[key]
            spin = _spin(lo, hi, decimals, step, none_text)
            self._register(key, spin)
            form.addRow(label, spin)

    def _row_slice(self, rows, *keys):
        return tuple(r for r in rows if r[0] in keys)

    def _combo(self, form: QFormLayout, key, label):
        combo = QComboBox()
        for value, text in COMBOS[key]:
            combo.addItem(text, value)
        combo.setMaximumWidth(COMBO_MAX_WIDTH)
        self._register(key, combo)
        form.addRow(label, combo)

    def _step_check(self, layout: QVBoxLayout, name: str):
        check = QCheckBox(STEP_CHECK_TEXT[name])
        check.toggled.connect(lambda on, n=name: self._step_touched(n, on))
        self.step_checks[name] = check
        layout.addWidget(check)

    def _setting_check(self, layout: QVBoxLayout, name: str, text: str) -> QCheckBox:
        check = QCheckBox(text)
        check.toggled.connect(lambda on, n=name: self._setting_touched(n, on))
        layout.addWidget(check)
        return check

    def _build_overview(self, v: QVBoxLayout):
        self.sw_reads_label = QLabel("")
        v.addWidget(self.sw_reads_label)
        self.remediation_note = note("")
        v.addWidget(self.remediation_note)
        self.chain_table = make_table(("Zone", "Sw reads"))
        self.chain_table.horizontalHeader().setStretchLastSection(False)
        self.chain_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        self.chain_table.verticalHeader().setDefaultSectionSize(26)
        self.chain_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chain_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        v.addWidget(self.chain_table, 0, Qt.AlignmentFlag.AlignLeft)
        self.chain_table_note = note("Stored settings; switch a step on its own page.")
        v.addWidget(self.chain_table_note)
        # Steps without a page of their own (none in the shipped chain) are switched here.
        self.other_steps_heading = subheading("Other Rt steps")
        v.addWidget(self.other_steps_heading)
        self.other_steps_box = QVBoxLayout()
        v.addLayout(self.other_steps_box)
        v.addWidget(subheading("Chain options"))
        form = make_form()
        self.fallback_combo = QComboBox()
        for key, text in FALLBACK_LABELS:
            self.fallback_combo.addItem(text, key)
        self.fallback_combo.setMaximumWidth(COMBO_MAX_WIDTH)
        self.fallback_combo.currentIndexChanged.connect(
            lambda _i: self._setting_touched("rt_fallback", self.fallback_combo.currentData()))
        form.addRow("When a step cannot produce a value", self.fallback_combo)
        v.addLayout(form)
        self.sbc_check = self._setting_check(v, "rt_sbc",
                                             "The mapped RT is shoulder-bed corrected")
        self.sbc_check.setToolTip(
            "Declare the mapped RT curve already shoulder-bed corrected. The laminated-sand "
            "correction is meant for the raw deep RT.")
        self.sbc_note = note("")
        v.addWidget(self.sbc_note)
        self.guard_check = self._setting_check(v, "guard_enabled",
                                               "Shoulder-bed guard (laminated zones)")
        self.guard_status = note("")
        v.addWidget(self.guard_status)
        self.chain_note = note(CHAIN_SENTENCE)
        v.addWidget(self.chain_note)
        self.chain_box = method_strip("rt_chain")
        v.addWidget(self.chain_box)

    def _build_laminated(self, v: QVBoxLayout):
        self._step_check(v, "laminated")
        self.ts_check = self._setting_check(
            v, "ts_enabled", "Compute Thomas-Stieber (laminar shale volume) on the next run")
        v.addWidget(subheading("End-points"))
        ends = make_form()
        self._rows(ends, self._row_slice(LAMINATED_ROWS, "phi_max", "phi_sh"))
        v.addLayout(ends)
        proposal = QHBoxLayout()
        self.proposal_label = note("")
        proposal.addWidget(self.proposal_label, 1)
        self.use_proposal_button = QPushButton("Use proposal")
        self.use_proposal_button.clicked.connect(self._on_use_proposal)
        proposal.addWidget(self.use_proposal_button)
        proposal.addStretch(0)
        v.addLayout(proposal)
        self.applied_label = note("", "warning")
        v.addWidget(self.applied_label)
        v.addWidget(subheading("Laminar shale volume"))
        vlam = make_form()
        self._combo(vlam, "vlam_source", "Vlam source")
        self._rows(vlam, self._row_slice(LAMINATED_ROWS, "vlam_const"))
        v.addLayout(vlam)
        v.addWidget(heading("Advanced"))
        limits = make_form()
        self._rows(limits, self._row_slice(LAMINATED_ROWS, "hag_vsh_max", "s_warn", "s_invalid"))
        v.addLayout(limits)
        self.laminated_box = method_strip("laminated")
        v.addWidget(self.laminated_box)

    def _build_pyrite(self, v: QVBoxLayout):
        self._step_check(v, "pyrite")
        self.vpyr_check = self._setting_check(v, "vpyr_enabled",
                                              "Compute the VPYR column on the next run")
        left = QVBoxLayout()
        left.addWidget(subheading("Pyrite volume"))
        vol = make_form()
        self._combo(vol, "pyr_method", "Pyrite volume")
        self._rows(vol, self._row_slice(PYRITE_ROWS, "pyr_vpyr", "pyr_f", "pyr_rpy"))
        left.addLayout(vol)
        self.vpyr_label = note("")
        left.addWidget(self.vpyr_label)
        left.addWidget(heading("Advanced"))
        left.addWidget(subheading("Pyrite mineral"))
        pyr = make_form()
        self._rows(pyr, self._row_slice(PYRITE_ROWS, "pyr_rho", "pyr_pef"))
        left.addLayout(pyr)
        left.addWidget(subheading("Matrix and shale end-points"))
        mat = make_form()
        self._rows(mat, self._row_slice(PYRITE_ROWS, "ma_rho", "ma_pef", "sh_rho", "sh_pef"))
        left.addLayout(mat)
        left.addStretch(1)
        self.pef_plot = PefRhobPlot()
        self.pef_plot.setMinimumHeight(320)
        v.addLayout(side_by_side(left, self.pef_plot))
        self.pyrite_box = method_strip("pyrite")
        v.addWidget(self.pyrite_box)

    def _build_clay(self, v: QVBoxLayout):
        form = make_form()
        self._combo(form, "qv_source", "Qv source")
        self._rows(form, self._row_slice(CLAY_ROWS, "cec_shale"))
        v.addLayout(form)
        row = QHBoxLayout()
        self.cec_label = note("")
        row.addWidget(self.cec_label, 1)
        self.use_cec_button = QPushButton("Use core CEC")
        self.use_cec_button.clicked.connect(self._on_use_cec)
        row.addWidget(self.use_cec_button)
        v.addLayout(row)
        self.qv_label = note("")
        v.addWidget(self.qv_label)
        v.addWidget(heading("Advanced"))
        adv = make_form()
        self._rows(adv, self._row_slice(CLAY_ROWS, "qv_rho_g"))
        v.addLayout(adv)
        self.qv_box = method_strip("qv")
        v.addWidget(self.qv_box)

    def _build_basis(self, v: QVBoxLayout):
        form = make_form()
        self._combo(form, "sw_basis", "Sw basis")
        v.addLayout(form)
        self.basis_label = note("")
        v.addWidget(self.basis_label)
        self.suggestion_label = note("")
        v.addWidget(self.suggestion_label)
        row = QHBoxLayout()
        self.sw_models_button = QPushButton("Open Parameters > Sw models")
        self.sw_models_button.clicked.connect(lambda: self.navigate_requested.emit("params.sat"))
        row.addWidget(self.sw_models_button)
        row.addStretch(1)
        v.addLayout(row)

    # ---------------------------------------------------------------- context
    def set_context(self, model, ds, zone: Optional[str] = None, zones=()):
        self.model = model
        self.ds = ds
        self._zones = list(zones)
        new_zone = zone or None
        target = (getattr(ds, "key", None), new_zone)
        moved = self._loaded_for != target
        reload = moved or not self._has_pending()
        dropped = moved and self._loaded_for is not None and self._has_pending()
        old_zone = self.zone
        self.zone = new_zone
        self._loaded_for = target
        if reload:
            self._clear_pending()
            self.result_label.setText("")
            if moved:
                self._default_scope()
            self._load_values()
        if dropped:
            self.result_label.setText(
                f"Changes not applied for {zone_title(old_zone)} were discarded.")
            set_status(self.result_label, "warning")
        fit_key = (target, id(getattr(ds, "results", None)))
        if getattr(self, "_mn_fit_for", None) != fit_key:
            self._mn_fit_for = fit_key
            self._reset_mn_fit()
        self._refresh_info()
        self._update_state()

    def _default_scope(self):
        """A zone selected in the header writes to that zone; all zones write the well default."""
        key = "zone" if self.zone is not None else ("well" if self.ds is not None else "project")
        was = self.scope_combo.blockSignals(True)
        self.scope_combo.setCurrentIndex(self.scope_combo.findData(key))
        self.scope_combo.blockSignals(was)

    def scroll_target(self, section: str) -> Optional[QWidget]:
        return self.groups.get(section)

    def prepare(self, zone: Optional[str], remedy: Optional[dict] = None,
                values: Optional[dict] = None):
        """Fill the form from a remedy or from values; nothing is written."""
        remedy = remedy or {}
        self._loading = True
        try:
            if zone != self.zone:
                self.zone = zone or None
                self._load_values()
        finally:
            self._loading = False
        for name in remedy.get("rt_steps") or []:
            self._set_step(name, True)
        if remedy.get("qv_source"):
            self._set_value("qv_source", remedy["qv_source"])
        if remedy.get("sw_basis"):
            self._set_value("sw_basis", remedy["sw_basis"])
        self._models_hint = list(remedy.get("sw_models") or [])
        for key, value in (values or {}).items():
            if key in self.controls:
                self._set_value(key, value)
        self.result_label.setText("")
        self._refresh_info()
        self._update_state()

    # ------------------------------------------------------------------ values
    def _ladder(self):
        project = self.model.project.lrlc.get("params") or {}
        well = (getattr(self.ds, "lrlc", None) or {}) if self.ds is not None else {}
        return project, well

    def _has_pending(self) -> bool:
        return bool(self._dirty or self._settings or self._step_toggles)

    def _clear_pending(self):
        self._step_toggles = {}
        self._settings = {}
        self._dirty = set()
        self._models_hint = []
        self._fit_coef = None

    def _load_values(self, keep: Optional[set] = None):
        """Show the stored values; keys in ``keep`` keep their pending value."""
        if self.model is None:
            return
        keep = keep or set()
        resolved = resolve_lrlc(*self._ladder(), self.zone)
        was = self._loading
        self._loading = True
        try:
            for key, widget in self.controls.items():
                if key not in keep:
                    self._write_widget(key, widget, self._display_value(key, resolved))
            for name in SETTING_LABELS:
                if name not in self._settings:
                    self._show_setting(name, self._stored_setting(name))
            self._show_steps()
        finally:
            self._loading = was

    @staticmethod
    def _write_widget(key, widget, value):
        if isinstance(widget, QComboBox):
            i = widget.findData(value)
            widget.setCurrentIndex(max(i, 0))
        elif isinstance(widget, MultiSpin):
            widget.set(value)
        elif isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
        elif value is None:
            widget.setValue(widget.minimum())
        else:
            widget.setValue(float(value))

    def _read_widget(self, key) -> Any:
        widget = self.controls[key]
        if isinstance(widget, QComboBox):
            return widget.currentData()
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, MultiSpin):
            values = widget.get()
            if key == "inv_r50":
                preset = GENERIC_TOOLS.get(self.controls["inv_tool"].currentData())
                if preset is not None and all(
                        abs(values[k] - preset[k]) < 1e-9 for k in values):
                    return None
            return values
        if key in NULLABLE and widget.value() <= widget.minimum() + 1e-12:
            return None
        return float(widget.value())

    def _set_value(self, key, value):
        was = self._loading
        self._loading = True
        try:
            self._write_widget(key, self.controls[key], value)
        finally:
            self._loading = was
        self._dirty.add(key)

    # ---- the switches outside the ladder
    def _stored_setting(self, name):
        lrlc = self.model.project.lrlc
        if name in SETTING_KEYS:
            block, key = SETTING_KEYS[name]
            return bool((lrlc.get(block) or {}).get(key))
        if name == "rt_fallback":
            return resolve_lrlc(*self._ladder(), None)["rt_fallback"]
        if name == "rt_sbc":
            ds = self.ds
            mapped = (getattr(ds, "curve_mapping", None) or {}).get("RT") if ds is not None else None
            marked = (getattr(ds, "lrlc_curves", None) or {}).get("RT_SBC") if ds is not None else None
            return bool(marked) and marked == mapped
        return bool((lrlc.get("guard") or {}).get("enabled", True))

    def _setting_widget(self, name):
        return {"ts_enabled": self.ts_check, "vpyr_enabled": self.vpyr_check,
                "rt_fallback": self.fallback_combo, "rt_sbc": self.sbc_check,
                "guard_enabled": self.guard_check}[name]

    def _show_setting(self, name, value):
        widget = self._setting_widget(name)
        was = self._loading
        self._loading = True
        try:
            if isinstance(widget, QComboBox):
                i = widget.findData(value)
                if i >= 0:
                    widget.setCurrentIndex(i)
            else:
                widget.setChecked(bool(value))
        finally:
            self._loading = was

    def _set_setting(self, name, value):
        """Show a switch value and keep it pending when it differs from the stored one."""
        self._show_setting(name, value)
        if value != self._stored_setting(name):
            self._settings[name] = value
        else:
            self._settings.pop(name, None)

    def _setting_touched(self, name, value):
        if self._loading:
            return
        self._set_setting(name, value)
        self.result_label.setText("")
        self._refresh_info()
        self._update_state()

    # ---- the Rt steps
    def _stored_steps(self, zone=None) -> List[str]:
        return resolve_lrlc_steps(resolve_lrlc(*self._ladder(), zone if zone else self.zone))

    def _with_toggles(self, names) -> List[str]:
        names = [n for n in names if self._step_toggles.get(n, True)]
        names += [n for n, on in self._step_toggles.items() if on and n not in names]
        return chain_sorted(names)

    def _displayed_steps(self) -> List[str]:
        """The steps of the shown zone with the pending switches on top."""
        return self._with_toggles(self._stored_steps())

    def _target_steps(self, level: str, zone: Optional[str]) -> List[str]:
        """The list to write at ``(level, zone)``: what that level resolves to today with the
        pending switches on top, so a zone's own steps are never copied to a default."""
        project, well = self._ladder()
        base = resolve_lrlc(project, {} if level == "project" else well, zone)
        return self._with_toggles(resolve_lrlc_steps(base))

    def _set_step(self, name: str, on: bool):
        if (name in self._stored_steps()) == bool(on):
            self._step_toggles.pop(name, None)
        else:
            self._step_toggles[name] = bool(on)
        if on and name in STEP_SETTING and not self._stored_setting(STEP_SETTING[name]):
            self._set_setting(STEP_SETTING[name], True)
        self._show_steps()

    def _step_touched(self, name: str, on: bool):
        if self._loading:
            return
        self._set_step(name, on)
        self.result_label.setText("")
        self._refresh_info()
        self._update_state()

    def _show_steps(self):
        on = set(self._displayed_steps())
        was = self._loading
        self._loading = True
        try:
            for name, check in list(self.step_checks.items()) + list(
                    self._other_step_checks.items()):
                check.setChecked(name in on)
        finally:
            self._loading = was

    def _render_other_steps(self):
        """A switch for each registered step that has no page of its own."""
        names = [s.name for s in chain.available_steps() if s.name not in STEP_PAGES]
        if list(self._other_step_checks) != names:
            for check in self._other_step_checks.values():
                self.other_steps_box.removeWidget(check)
                check.deleteLater()
            self._other_step_checks = {}
            labels = {s.name: s.label for s in chain.available_steps()}
            for name in names:
                check = QCheckBox(f"Apply {labels[name]}")
                check.toggled.connect(lambda on, n=name: self._step_touched(n, on))
                self.other_steps_box.addWidget(check)
                self._other_step_checks[name] = check
        self.other_steps_heading.setVisible(bool(names))
        self._show_steps()

    def _touched(self, key):
        if self._loading:
            return
        self._dirty.add(key)
        if key == "m_coef":
            self._fit_coef = None
        self.result_label.setText("")
        self._refresh_info()
        self._update_state()

    def _current_params(self) -> dict:
        """The resolved ladder of the zone with the form's values on top."""
        prm = resolve_lrlc(*self._ladder(), self.zone)
        for key in self.controls:
            prm[key] = self._read_widget(key)
        if self._fit_coef is not None:
            prm["m_coef"] = list(self._fit_coef)
        prm["rt_steps"] = self._displayed_steps()
        return prm

    # ------------------------------------------------------------------- state
    def _on_scope_changed(self):
        self._update_state()

    def _scope_where(self) -> str:
        scope = self.scope_combo.currentData()
        return SCOPE_WHERE[scope].format(zone=self.zone or "")

    def _update_state(self):
        has_zone = self.zone is not None
        has_well = self.ds is not None
        model = self.scope_combo.model()
        model.item(0).setEnabled(has_zone and has_well)
        model.item(1).setEnabled(has_well)
        if not model.item(self.scope_combo.currentIndex()).isEnabled():
            was = self.scope_combo.blockSignals(True)
            self.scope_combo.setCurrentIndex(2 if not has_well else 1)
            self.scope_combo.blockSignals(was)
        where = self._scope_where()
        for name, check in self.step_checks.items():
            check.setText(f"{STEP_CHECK_TEXT[name]} {where}")
        vconst = self._read_widget("vlam_source") == "constant"
        self.controls["vlam_const"].setEnabled(vconst)
        manual = self._read_widget("pyr_method") == "manual"
        self.controls["pyr_vpyr"].setEnabled(manual)
        self._state_variable_mn()
        self._state_invasion()
        labels = {s.name: s.label for s in chain.available_steps()}
        pending = [KEY_LABELS.get(k, k) for k in sorted(self._dirty)]
        pending += [f"{labels.get(n, n)} {'on' if on else 'off'}"
                    for n, on in sorted(self._step_toggles.items())]
        pending += [SETTING_LABELS[k] for k in sorted(self._settings)]
        self.apply_button.setEnabled(bool(pending) and self.model is not None)
        self.discard_button.setEnabled(bool(pending))
        scope = self.scope_combo.currentData()
        self.pending_label.setText(
            ("Not yet written: " + ", ".join(pending) + ". " + SCOPE_NOTE[scope]) if pending
            else "Changes on every page are written together by Apply. " + SCOPE_NOTE[scope])
        self._update_list_states()

    def _section_pending(self, key) -> bool:
        if self._dirty & self._section_keys.get(key, set()):
            return True
        if any(SETTING_SECTION[n] == key for n in self._settings):
            return True
        return any((n if n in STEP_PAGES else "rt_source") == key for n in self._step_toggles)

    def _update_list_states(self):
        if self.model is None:
            return
        prm = self._current_params()
        steps = prm["rt_steps"]
        states = {
            "rt_source": (f"{len(steps)} step{'s' if len(steps) != 1 else ''} on" if steps
                          else "measured Rt"),
            "clay": "estimated Qv" if prm.get("qv_source") == "estimate" else "constant Qv",
            "sw_basis": f"{resolve_basis(prm)} basis",
            "variable_mn": prm.get("mn_mode") or "scalar",
        }
        for name in STEP_PAGES:
            states[name] = "on" if name in steps else "off"
        for key, row in self._list_rows.items():
            text = states.get(key, "")
            if self._section_pending(key):
                text += ", changed"
            row.state_label.setText(text)

    def _target(self):
        scope = self.scope_combo.currentData()
        if scope == "zone":
            return "well", self.zone
        if scope == "well":
            return "well", None
        return "project", None

    def _stale_keys(self, level):
        if level == "well":
            return [self.ds.key] if self.ds is not None else []
        return list(self.model.project.keys())

    def _on_discard(self):
        self._clear_pending()
        self.result_label.setText("")
        self._load_values()
        self._refresh_info()
        self._update_state()

    def _write_setting(self, name, value, level) -> bool:
        if name in SETTING_KEYS:
            block, key = SETTING_KEYS[name]
            return LrlcService.set_setting(self.model, block, key, value)
        if name == "rt_fallback":
            return LrlcService.set_param(self.model, level, None, "rt_fallback", value, self.ds)
        if name == "rt_sbc":
            return LrlcService.set_rt_sbc(self.model, self.ds, bool(value))
        if LrlcService.set_guard_enabled(self.model, bool(value)):
            self.guard_changed.emit(bool(value))
            return True
        return False

    def _on_apply(self):
        if self.model is None or not self._has_pending():
            return
        level, zone = self._target()
        values: Dict[str, Any] = {}
        for key in self._dirty:
            if key == "m_coef" and self._fit_coef is not None:
                values[key] = list(self._fit_coef)
            else:
                values[key] = self._read_widget(key)
        if self._step_toggles:
            values["rt_steps"] = self._target_steps(level, zone)
        # The ladder values first: a refused set stays pending; the switches are written anyway.
        written: List[str] = []
        refused = False
        if values:
            written = LrlcService.apply_remediation(self.model, level, zone, values, self.ds)
            refused = not written
        changed_settings = []
        for name, value in list(self._settings.items()):
            if self._write_setting(name, value, level):
                changed_settings.append(name)
        self._settings = {}
        if not refused:
            self._dirty = set()
            self._step_toggles = {}
            self._fit_coef = None
        self._load_values(keep=self._dirty if refused else None)
        self._refresh_info()
        self._update_state()
        wrote = [KEY_LABELS.get(k, k) for k in written] + [SETTING_LABELS[n]
                                                          for n in changed_settings]
        rule = ("the values are already stored at this scope, or they break a rule (the shale "
                "porosity must be at least 0.02 below the clean-sand porosity, and the "
                "sensitivity warning limit below the invalid limit)")
        if not wrote:
            self.result_label.setText(f"Nothing was written: {rule}.")
            set_status(self.result_label, "warning")
            return
        if refused:
            self.result_label.setText(
                "Written: " + ", ".join(wrote) + f". The other changes are still pending: {rule}.")
            set_status(self.result_label, "warning")
        else:
            self.result_label.setText(
                "Written: " + ", ".join(wrote) + ". Run the analysis to see the effect.")
            set_status(self.result_label, "success")
        project_wide = (level == "project" and (written or "rt_fallback" in changed_settings)) \
            or any(n in PROJECT_SETTINGS for n in changed_settings)
        self.stale_requested.emit(self._stale_keys("project" if project_wide else "well"))
        if written:
            self.applied.emit(written)

    def _on_use_proposal(self):
        prop = self._proposal
        if prop is None or not prop.ok:
            return
        self._set_value("phi_max", float(prop.phi_max))
        self._set_value("phi_sh", float(prop.phi_sh))
        self._refresh_info()
        self._update_state()

    def _on_use_cec(self):
        fit = self._cec
        if fit is None or not fit.ok:
            return
        self._set_value("cec_shale", round(float(fit.cec_shale), 1))
        self._refresh_info()
        self._update_state()

    # --------------------------------------------------------------- info texts
    def _refresh_info(self):
        if self.model is None:
            return
        self._info_overview()
        self._info_laminated()
        self._info_pyrite()
        self._info_clay()
        self._info_basis()
        self._info_variable_mn()
        self._info_invasion()

    def _zone_key(self):
        return self.zone

    def _info_overview(self):
        steps = chain.available_steps()
        self._render_other_steps()
        columns = ["Zone", "Sw reads"] + [s.label for s in steps]
        table = self.chain_table
        table.clear()
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)
        zones = [None] + list(self._zones)
        if self.zone is not None and self.zone not in zones:
            zones.append(self.zone)
        table.setRowCount(len(zones))
        for r, zone in enumerate(zones):
            resolved = resolve_lrlc(*self._ladder(), zone)
            specs, _unknown = chain.resolve_steps(resolved["rt_steps"])
            on = {s.name for s in specs}
            table.setItem(r, 0, item(zone or OTHER_ZONES))
            table.setItem(r, 1, item(chain.chain_path(specs)))
            for c, spec in enumerate(steps):
                cell = item("on" if spec.name in on else "")
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(r, 2 + c, cell)
        self._size_chain_table()
        self.remediation_note.setText("" if steps else NO_STEPS_NOTE)
        self.remediation_note.setVisible(not steps)
        self.chain_table_note.setVisible(bool(steps))
        specs, _unknown = chain.resolve_steps(self._displayed_steps())
        where = zone_title(self.zone) if self.zone else OTHER_ZONES
        after = " after Apply" if self._step_toggles else ""
        self.sw_reads_label.setText(f"Sw reads{after}: {chain.chain_path(specs)} ({where})")
        self._info_sbc()
        self._info_guard()

    def _size_chain_table(self):
        """Columns to their content; the table is exactly as large as its cells."""
        table = self.chain_table
        header = table.horizontalHeader()
        width = 0
        for c in range(table.columnCount()):
            table.setColumnWidth(c, max(table.sizeHintForColumn(c), header.sectionSizeHint(c)) + 16)
            width += table.columnWidth(c)
        table.setFixedWidth(width + 2 * table.frameWidth() + 4)
        header_h = max(header.height(), header.sizeHint().height())
        rows_h = sum(table.rowHeight(r) for r in range(table.rowCount()))
        table.setFixedHeight(header_h + rows_h + 2 * table.frameWidth() + 2)

    def _info_sbc(self):
        ds = self.ds
        mapped = (getattr(ds, "curve_mapping", None) or {}).get("RT") if ds is not None else None
        marked = (getattr(ds, "lrlc_curves", None) or {}).get("RT_SBC") if ds is not None else None
        self.sbc_check.setEnabled(bool(mapped))
        if marked and marked != mapped:
            text = (f"The marked curve {marked} is no longer the mapped RT, so the mark is "
                    "ignored.")
        elif marked:
            text = (f"{marked} is marked shoulder-bed corrected. In laminated zones with the "
                    "laminated-sand correction, map the raw deep RT instead.")
        else:
            text = ""
        self.sbc_note.setText(text)
        self.sbc_note.setVisible(bool(text))

    @staticmethod
    def guard_lines(summary_guard, zone):
        lines = []
        for z in summary_guard.get("zones", []):
            name = z.get("zone")
            if zone is not None and name != zone:
                continue
            where = f"Zone {name}" if name else "the unzoned interval"
            if not z.get("laminated"):
                lines.append(f"{where}: not laminated.")
                continue
            share = fmt(z.get("lam_share"), 2)
            lines.append(f"{where}: laminated (laminar share {share}).")
            for step in z.get("blocked_steps") or []:
                lines.append(f"{step} not applied in {where}: laminated (guard); use the "
                             "laminated-sand correction.")
            if z.get("sbc_rt"):
                lines.append(f"RT is marked shoulder-bed corrected in {where}, which is "
                             "laminated: map the raw deep RT and use the laminated-sand "
                             "correction.")
        return lines

    def _info_guard(self):
        enabled = self.guard_check.isChecked()
        guard = lrlc_summary(self.ds).get("guard")
        head = "The guard is on." if enabled else "The guard is off: it only warns."
        if not guard:
            text = f"{head} {GUARD_RUN_FIRST}"
        else:
            text = "\n".join([head] + self.guard_lines(guard, self.zone))
        self.guard_status.setText(text)

    def _info_laminated(self):
        from modules.param_scopes import UNZONED

        proposals = LrlcService.ts_proposals(self.model, self.ds) if self.ds is not None else None
        self._proposal = None
        if proposals is None:
            self.proposal_label.setText("Run the analysis to get proposed end-points.")
        else:
            prop = proposals.get(self.zone if self.zone is not None else UNZONED)
            if prop is None and self.zone is None and len(proposals) == 1:
                prop = next(iter(proposals.values()))
            if prop is None:
                self.proposal_label.setText("No proposal for this zone.")
            elif prop.ok:
                self._proposal = prop
                self.proposal_label.setText(
                    f"Proposed: phi_max {fmt(prop.phi_max, 3)}, phi_sh {fmt(prop.phi_sh, 3)} "
                    f"(from the {prop.source}, {prop.n_clean} clean and {prop.n_shale} shale "
                    "samples).")
            else:
                self.proposal_label.setText(f"No usable proposal. {prop.reason or ''}")
        self.use_proposal_button.setEnabled(self._proposal is not None)
        prm = self._current_params()
        pm, ps = prm.get("phi_max"), prm.get("phi_sh")
        if pm is None or ps is None:
            text = "No end-points: without them Thomas-Stieber gives no laminar shale volume."
        else:
            ok, why = check_endpoints(pm, ps)
            text = "" if ok else f"These end-points are not usable: {why}."
        self.applied_label.setText(text)
        self.applied_label.setVisible(bool(text))

    def _sample_arrays(self):
        res = getattr(self.ds, "results", None)
        if res is None or len(res) == 0:
            return None
        rhob_name = (getattr(self.ds, "curve_mapping", None) or {}).get("RHOB") or "RHOB"
        curves = getattr(self.ds, "lrlc_curves", None) or {}
        pef_name = curves.get("PEF") if "PEF" in curves else None
        if pef_name is None and "PEF" not in curves:
            try:
                from modules.las_parser import find_curve
                pef_name = find_curve(list(self.ds.las_data.columns), "PEF")
            except Exception:
                pef_name = None
        if rhob_name not in res.columns or pef_name not in res.columns:
            return None
        mask = np.ones(len(res), dtype=bool)
        if self.zone is not None and "ZONE" in res.columns:
            mask = zone_labels(res) == self.zone
        vpyr = res["VPYR"].to_numpy(dtype=float)[mask] if "VPYR" in res.columns else None
        return (res[rhob_name].to_numpy(dtype=float)[mask],
                res[pef_name].to_numpy(dtype=float)[mask], vpyr)

    def _flat_params(self) -> dict:
        try:
            flat = self.model.params_for_well(self.ds)
            plan = (flat.get("zone_plan") or {}).get(self.zone) if self.zone else None
            return plan["params"] if plan and plan.get("params") else flat
        except Exception:
            logger.debug("well parameters unavailable", exc_info=True)
            return {}

    def _info_pyrite(self):
        prm = self._current_params()
        flat = self._flat_params()
        rho_ma = prm["ma_rho"] if prm.get("ma_rho") is not None else flat.get("rho_matrix", 2.65)
        rho_sh = prm["sh_rho"] if prm.get("sh_rho") is not None else flat.get("rho_shale", 2.65)
        arrays = self._sample_arrays() if self.ds is not None else None
        if arrays is None:
            self.pef_plot.clear_data("Run the analysis with a PEF curve mapped to see the samples")
        else:
            samples, vpyr = (arrays[0], arrays[1]), arrays[2]
            self.pef_plot.set_data(samples, (float(rho_ma), float(prm["ma_pef"])),
                                   (float(rho_sh), float(prm["sh_pef"])),
                                   (float(prm["pyr_rho"]), float(prm["pyr_pef"])), vpyr)
        if arrays is not None and arrays[2] is not None and np.isfinite(arrays[2]).any():
            v = arrays[2][np.isfinite(arrays[2])]
            self.vpyr_label.setText(
                f"VPYR in the last run, {self.zone or 'whole well'}: median {fmt(np.median(v), 3)}, "
                f"maximum {fmt(v.max(), 3)} ({len(v)} samples).")
        else:
            self.vpyr_label.setText("No VPYR in the last run.")

    def _info_clay(self):
        fit = None
        if self.ds is not None:
            try:
                fit = LrlcService.cec_proposal(self.model, self.ds, self.zone)
            except Exception:
                logger.debug("core CEC proposal failed", exc_info=True)
        self._cec = fit
        if fit is None:
            self.cec_label.setText("No core CEC loaded, or no results yet: enter the shale CEC "
                                   "by hand.")
        elif fit.ok:
            self.cec_label.setText(
                f"From core CEC: {fmt(fit.cec_shale, 1)} meq/100 g ({fit.n} pairs, R2 "
                f"{fmt(fit.r2, 2)}).")
        else:
            self.cec_label.setText(f"No core CEC proposal: {fit.reason}")
        self.use_cec_button.setEnabled(fit is not None and fit.ok)
        res = getattr(self.ds, "results", None)
        text = "No Qv estimate in the last run."
        if res is not None and "QV_EST" in res.columns:
            mask = np.ones(len(res), dtype=bool)
            if self.zone is not None and "ZONE" in res.columns:
                mask = zone_labels(res) == self.zone
            v = res["QV_EST"].to_numpy(dtype=float)[mask]
            v = v[np.isfinite(v)]
            if len(v):
                text = f"Qv estimate in the last run: median {fmt(np.median(v), 3)} meq/mL."
        self.qv_label.setText(text)

    def _info_basis(self):
        prm = self._current_params()
        basis = resolve_basis(prm)
        text = (f"This zone reads the {'sand-lamina' if basis == 'sand' else 'bulk'} porosity "
                "and shale volume in the Sw models.")
        status = "muted"
        if basis == "bulk" and "laminated" in prm["rt_steps"]:
            text += (" With the laminated correction on, laminar shale is counted twice by the "
                     "Indonesian and Simandoux models.")
            status = "warning"
        self.basis_label.setText(text)
        set_status(self.basis_label, status)
        models = list(self._models_hint)
        if not models:
            for res in lrlc_summary(self.ds).get("zones") or []:
                if res.get("zone") == (self.zone or "WELL") or (
                        self.zone is None and len(lrlc_summary(self.ds)["zones"]) == 1):
                    cause = next((c for c in res.get("causes") or []
                                  if c["key"] == res.get("primary")), None)
                    if cause:
                        models = list(cause["remedy"].get("sw_models") or [])
                    break
        self.suggestion_label.setText(
            ("Suggested Sw model after these corrections: " + " or ".join(models)
             + ". The primary Sw model is a project parameter.") if models else "")
        self.suggestion_label.setVisible(bool(models))
        self._info_hint(prm)

    def _info_hint(self, prm):
        text = ""
        guard = lrlc_summary(self.ds).get("guard") or {}
        if guard.get("enabled", True) and "laminated" not in prm["rt_steps"]:
            for z in guard.get("zones", []):
                name = z.get("zone")
                if z.get("laminated") and (self.zone is None or name == self.zone):
                    where = f"Zone {name}" if name else "The interval"
                    text = (f"{where} is laminated by Thomas-Stieber; consider the "
                            "laminated-sand Rt (Hagiwara).")
                    break
        self.hint_label.setText(text)
        self.hint_label.setVisible(bool(text))

    def refresh_theme(self):
        self.pef_plot.refresh_theme()
        self.refresh_new_themes()
        for box in (self.chain_box, self.laminated_box, self.pyrite_box, self.qv_box,
                    self.mn_box, self.inv_box):
            box.refresh_theme()


def resolve_lrlc_steps(prm: dict) -> List[str]:
    """Names of the registered steps listed in a resolved ladder, in chain order."""
    specs, _unknown = chain.resolve_steps(prm.get("rt_steps") or [])
    return [s.name for s in specs]


def chain_sorted(names: List[str]) -> List[str]:
    order = {s.name: i for i, s in enumerate(chain.available_steps())}
    return sorted(dict.fromkeys(names), key=lambda n: order.get(n, len(order)))
