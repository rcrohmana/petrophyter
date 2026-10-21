"""
Saturation-Height Tab for Petrophyter PyQt
Fit Leverett J-Sw curves per rock type from core capillary pressure (or from the logs), apply
them to the project, set the fluid contacts of the active well and estimate its free water
level. Fit shows results here only; Apply fit and Accept are the explicit writes (they mark the
affected wells stale).
"""

import logging

import numpy as np
import pandas as pd
from PyQt6.QtCore import QEvent, Qt, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from modules.shf import (
    ALL, BASIS_CORE, BASIS_LOG, MODELS, PARAM_NAMES, STATUS_OK, ShfFit, leverett_j, sw_from_j)
from modules.shf_config import SHF_DEFAULTS
from modules.shf_stage import fits_in_use, pay_refused_for
from services import shf_service as svc
from themes.colors import get_plot_color, get_rock_type_color
from themes.helpers import set_status
from ..widgets.plot_widget import PlotWidget
from .rock_typing_tab import fit_table_height

logger = logging.getLogger(__name__)

MODEL_LABELS = {"power": "Power law", "brooks_corey": "Brooks-Corey"}
WEIGHT_LABELS = (("sample", "Each sample equally"), ("point", "Each point equally"))
PERM_SOURCES = (("auto", "Auto"), ("PERM_RT", "PERM_RT"), ("PERM_WR", "PERM_WR"),
                ("PERM_TIMUR", "PERM_TIMUR"))
PHIE_SOURCES = (("PHIE", "PHIE"), ("PHIT", "PHIT"))
ROCK_TYPE_LABELS = (("auto", "Auto"), ("file", "Pc file column"),
                    ("definitions", "Rock type definitions"), ("all", "All (one type)"))
FALLBACK_LABELS = (("none", "None"), ("pooled", "Pooled curve (All)"))
BASIS_LABELS = {BASIS_CORE: "core Pc", BASIS_LOG: "log-derived"}
LAB_SYSTEMS = (("air-brine", "Air-brine"), ("hg-air", "Mercury-air"), ("oil-brine", "Oil-brine"))
RES_SYSTEMS = (("oil-water", "Oil-water"), ("gas-water", "Gas-water"))
FLUID_ROWS = (("water", "Water"), ("oil", "Oil"), ("gas", "Gas"))

PAY_TIP = "Uses the saturation-height Sw for pay flags, net pay and HCPV where it is available."
PAY_LOG_TIP = "Log-derived fits are a cross-check only"
FWL_TIP = ("The free water level (Pc = 0), not the oil-water or gas-water contact. The "
           "contact sits higher by the entry height, so using it as the FWL biases Sw high in "
           "the transition zone.")
CONTROLS_MIN_WIDTH = 320
CONTROLS_MAX_WIDTH = 380
PLOT_MIN_HEIGHT = 380
STATS_COLUMNS = ("Scope", "Samples", "Bias", "RMSE", "MAE", "R²", "Basis")
FIT_COLUMNS = ("Rock type", "Model", "Parameters", "Samples", "Points", "RMSE", "Basis", "Status")
CONTACT_COLUMNS = ("Zone", "FWL (ft)", "Fluid", "Water density (g/cc)")
DEFAULT_ROW = "Default"


def _fmt(value, digits=3) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    return "" if not np.isfinite(v) else f"{v:.{digits}f}"


def _num_text(value) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    return "" if not np.isfinite(v) else f"{v:g}"


def _combo_items(combo: QComboBox, items):
    for key, text in items:
        combo.addItem(text, key)


def _set_combo(combo: QComboBox, key):
    i = combo.findData(key)
    if i >= 0:
        combo.setCurrentIndex(i)


def _spin(lo, hi, decimals, step) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    return s


def _param_text(fit: ShfFit) -> str:
    if not fit.params:
        return ""
    parts = []
    for name in PARAM_NAMES.get(fit.model, tuple(fit.params)):
        if name not in fit.params:
            continue
        text = f"{name} = {_fmt(fit.params[name], 4)}"
        se = (fit.se or {}).get(name)
        if se is not None and np.isfinite(float(se)):
            text += f" ± {_fmt(se, 4)}"
        parts.append(text)
    return ", ".join(parts)


class ShfTab(QWidget):
    """Saturation-Height tab: controls on the left, plots, fit table and contacts on the right."""

    fit_finished = pyqtSignal()        # a Fit ended (completed, refused or cancelled)
    stale_requested = pyqtSignal(list)  # well keys to re-check for staleness (empty = every well)
    run_all_requested = pyqtSignal()   # "Run All Wells" in the next-step guidance

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self._proposal = None            # fitted, not yet applied: {"mode", "fits", "report"}
        self._worker = None
        self._estimate = None            # last FwlEstimate of the active well
        self._estimate_text = ""
        self._confirmed = False          # fluids and tensions confirmed or edited by the user
        self._updating = False
        self._batch_running = False
        self._setup_ui()
        self.update_display()
        for signal in (model.analysis_complete, model.project.well_updated,
                       model.project.active_well_changed):
            signal.connect(self._render_guidance)

    # ------------------------------------------------------------------ UI
    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.page_scroll = QScrollArea()
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.page = QWidget()
        root = QHBoxLayout(self.page)
        root.addWidget(self._build_controls(), 0, Qt.AlignmentFlag.AlignTop)
        root.addWidget(self._build_content(), 1, Qt.AlignmentFlag.AlignTop)
        self.page_scroll.setWidget(self.page)
        outer.addWidget(self.page_scroll)

    def _build_controls(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(CONTROLS_MIN_WIDTH)
        panel.setMaximumWidth(CONTROLS_MAX_WIDTH)
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)

        def section(text):
            label = QLabel(text.upper())
            label.setObjectName("SectionLabel")
            v.addWidget(label)

        section("Analysis")
        self.enable_check = QCheckBox("Compute saturation-height Sw on Run")
        self.enable_check.setToolTip(
            "Adds SW_SHF, HAFWL and SW_SHF_RESID to the results. Needs a fit and a contact.")
        v.addWidget(self.enable_check)
        self.enable_hint = QLabel("")
        self.enable_hint.setWordWrap(True)
        set_status(self.enable_hint, "warning")
        self.enable_hint.setVisible(False)
        v.addWidget(self.enable_hint)
        self.run_all_button = QPushButton("Run All Wells")
        self.run_all_button.setToolTip("Run the analysis for every well with saturation height on.")
        self.run_all_button.setVisible(False)
        self.run_all_button.clicked.connect(self.run_all_requested.emit)
        v.addWidget(self.run_all_button)

        section("Fluids (g/cc)")
        self.fluid_spins = {}
        grid = QGridLayout()
        for i, (key, text) in enumerate(FLUID_ROWS):
            grid.addWidget(QLabel(text), i, 0)
            spin = _spin(0.01, 2.0, 3, 0.01)
            self.fluid_spins[key] = spin
            grid.addWidget(spin, i, 1)
        v.addLayout(grid)
        section("Interfacial tension x cos(theta) (dyne/cm)")
        self.sigma_spins = {}
        grid = QGridLayout()
        for i, (key, text) in enumerate(LAB_SYSTEMS + RES_SYSTEMS):
            grid.addWidget(QLabel(text + (" (lab)" if (key, text) in LAB_SYSTEMS else " (reservoir)")),
                           i, 0)
            spin = _spin(0.1, 1000.0, 1, 1.0)
            self.sigma_spins[key] = spin
            grid.addWidget(spin, i, 1)
        v.addLayout(grid)
        badge_row = QHBoxLayout()
        self.defaults_badge = QLabel("Defaults, confirm")
        self.defaults_badge.setToolTip(
            "These are typical values. Edit them or confirm them for your reservoir fluids.")
        set_status(self.defaults_badge, "warning")
        badge_row.addWidget(self.defaults_badge, 1)
        self.confirm_button = QPushButton("Confirm")
        badge_row.addWidget(self.confirm_button)
        v.addLayout(badge_row)

        section("Fit settings")
        form = QGridLayout()
        self.model_combo = QComboBox()
        for key in MODELS:
            self.model_combo.addItem(MODEL_LABELS[key], key)
        self.weight_combo = QComboBox()
        _combo_items(self.weight_combo, WEIGHT_LABELS)
        self.min_pc_spin = _spin(0.0, 1000.0, 2, 0.5)
        self.min_pc_spin.setToolTip("Points at or below this Pc (psi) are left out (closure).")
        self.rt_source_combo = QComboBox()
        _combo_items(self.rt_source_combo, ROCK_TYPE_LABELS)
        self.perm_combo = QComboBox()
        _combo_items(self.perm_combo, PERM_SOURCES)
        self.phie_combo = QComboBox()
        _combo_items(self.phie_combo, PHIE_SOURCES)
        self.fallback_combo = QComboBox()
        _combo_items(self.fallback_combo, FALLBACK_LABELS)
        self.fallback_combo.setToolTip(
            "What a rock type without its own fitted curve uses in the run.")
        for i, (text, widget) in enumerate((
                ("Model", self.model_combo), ("Weighting", self.weight_combo),
                ("Minimum Pc (psi)", self.min_pc_spin), ("Rock type source", self.rt_source_combo),
                ("Permeability", self.perm_combo), ("Porosity", self.phie_combo),
                ("Fallback", self.fallback_combo))):
            form.addWidget(QLabel(text), i, 0)
            form.addWidget(widget, i, 1)
        v.addLayout(form)

        section("Fit")
        row = QHBoxLayout()
        self.fit_button = QPushButton("Fit")
        self.fit_button.setToolTip("Fit one curve per rock type to the core Pc data of all wells.")
        self.fit_logs_button = QPushButton("Fit from logs")
        self.fit_logs_button.setToolTip(
            "Fit to the log Sw above the contact of the run wells. Not independent of the "
            "resistivity Sw: a cross-check only.")
        row.addWidget(self.fit_button)
        row.addWidget(self.fit_logs_button)
        v.addLayout(row)
        row = QHBoxLayout()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.apply_button = QPushButton("Apply fit")
        self.apply_button.setEnabled(False)
        row.addWidget(self.cancel_button)
        row.addWidget(self.apply_button)
        v.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        v.addWidget(self.progress)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        set_status(self.status_label, "muted")
        v.addWidget(self.status_label)
        self.pay_check = QCheckBox("Use SHF Sw for pay and HCPV")
        self.pay_check.setToolTip(PAY_TIP)
        v.addWidget(self.pay_check)
        v.addStretch(1)

        self.enable_check.toggled.connect(self._on_enable_toggled)
        self.pay_check.toggled.connect(self._on_pay_toggled)
        for key, spin in self.fluid_spins.items():
            spin.editingFinished.connect(self._on_fluids_edited)
        for key, spin in self.sigma_spins.items():
            spin.editingFinished.connect(self._on_sigma_edited)
        self.confirm_button.clicked.connect(self._on_confirm)
        self.model_combo.currentIndexChanged.connect(self._on_fit_setting_changed)
        self.weight_combo.currentIndexChanged.connect(self._on_fit_setting_changed)
        self.min_pc_spin.editingFinished.connect(self._on_fit_setting_changed)
        self.rt_source_combo.currentIndexChanged.connect(self._on_fit_setting_changed)
        self.perm_combo.currentIndexChanged.connect(self._on_run_setting_changed)
        self.phie_combo.currentIndexChanged.connect(self._on_run_setting_changed)
        self.fallback_combo.currentIndexChanged.connect(self._on_run_setting_changed)
        self.fit_button.clicked.connect(lambda: self._on_fit(svc.MODE_CORE))
        self.fit_logs_button.clicked.connect(lambda: self._on_fit(svc.MODE_LOG))
        self.cancel_button.clicked.connect(self._on_cancel)
        self.apply_button.clicked.connect(self._on_apply)
        return panel

    def _build_content(self) -> QWidget:
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        self.rt_note = QLabel("")
        self.rt_note.setWordWrap(True)
        set_status(self.rt_note, "muted")
        self.rt_note.setVisible(False)
        cl.addWidget(self.rt_note)

        self.plot_tabs = QTabWidget()
        self.plot_j = PlotWidget(figsize=(8, 4))
        self.plot_height = PlotWidget(figsize=(8, 4))
        self.plot_profile = PlotWidget(figsize=(8, 4))
        for widget, title in ((self.plot_j, "J-Sw"), (self.plot_height, "Sw versus height"),
                              (self.plot_profile, "FWL profile")):
            widget.setMinimumHeight(PLOT_MIN_HEIGHT)
            widget.canvas.installEventFilter(self)   # wheel over a plot scrolls the page
            self.plot_tabs.addTab(widget, title)
        cl.addWidget(self.plot_tabs)

        self.fit_group = QGroupBox("Fits per rock type")
        fl = QVBoxLayout(self.fit_group)
        self.fit_title = QLabel("")
        set_status(self.fit_title, "muted")
        fl.addWidget(self.fit_title)
        self.fit_table = QTableWidget(0, len(FIT_COLUMNS))
        self.fit_table.setHorizontalHeaderLabels(list(FIT_COLUMNS))
        self.fit_table.verticalHeader().setVisible(False)
        self.fit_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.fit_table.horizontalHeader().setStretchLastSection(True)
        fl.addWidget(self.fit_table)
        self.fit_notes = QLabel("")
        self.fit_notes.setWordWrap(True)
        set_status(self.fit_notes, "muted")
        fl.addWidget(self.fit_notes)
        cl.addWidget(self.fit_group)

        self.contact_group = QGroupBox("Contacts (active well)")
        kl = QVBoxLayout(self.contact_group)
        top = QHBoxLayout()
        top.addWidget(QLabel("Datum"))
        self.datum_combo = QComboBox()
        for key in svc.DATUMS:
            self.datum_combo.addItem(key, key)
        top.addWidget(self.datum_combo)
        top.addWidget(QLabel("KB (ft)"))
        self.kb_edit = QLineEdit()
        self.kb_edit.setPlaceholderText("required for TVDSS")
        self.kb_edit.setMaximumWidth(140)
        top.addWidget(self.kb_edit)
        top.addStretch(1)
        kl.addLayout(top)
        self.kb_hint = QLabel("")
        self.kb_hint.setWordWrap(True)
        set_status(self.kb_hint, "muted")
        kl.addWidget(self.kb_hint)
        self.contact_table = QTableWidget(0, len(CONTACT_COLUMNS))
        self.contact_table.setHorizontalHeaderLabels(list(CONTACT_COLUMNS))
        self.contact_table.verticalHeader().setVisible(False)
        self.contact_table.horizontalHeader().setStretchLastSection(True)
        self.contact_table.setToolTip(FWL_TIP + " A blank water density uses the project value "
                                      "(0.95 to 1.25 g/cc).")
        kl.addWidget(self.contact_table)
        row = QHBoxLayout()
        self.estimate_button = QPushButton("Estimate FWL")
        self.estimate_button.setToolTip(
            "Find the free water level that best reproduces the log Sw with the applied fits, "
            "for the selected row. Nothing is written until Accept.")
        self.accept_button = QPushButton("Accept")
        self.accept_button.setToolTip("Store these contacts for the well and mark it stale.")
        row.addWidget(self.estimate_button)
        row.addWidget(self.accept_button)
        row.addStretch(1)
        kl.addLayout(row)
        self.contact_status = QLabel("")
        self.contact_status.setWordWrap(True)
        set_status(self.contact_status, "muted")
        kl.addWidget(self.contact_status)
        cl.addWidget(self.contact_group)

        self.stats_group = QGroupBox("Misfit (active well, last run)")
        sl = QVBoxLayout(self.stats_group)
        self.stats_table = QTableWidget(0, len(STATS_COLUMNS))
        self.stats_table.setHorizontalHeaderLabels(list(STATS_COLUMNS))
        self.stats_table.verticalHeader().setVisible(False)
        self.stats_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        sl.addWidget(self.stats_table)
        self.stats_notes = QLabel("")
        self.stats_notes.setWordWrap(True)
        set_status(self.stats_notes, "muted")
        sl.addWidget(self.stats_notes)
        cl.addWidget(self.stats_group)
        cl.addStretch(1)

        self.datum_combo.currentIndexChanged.connect(self._on_datum_changed)
        self.kb_edit.textChanged.connect(self._on_datum_changed)
        self.estimate_button.clicked.connect(self._on_estimate)
        self.accept_button.clicked.connect(self._on_accept)
        return content

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_tables()

    def eventFilter(self, obj, event):
        """The matplotlib canvas swallows wheel events; hand them to the page scroll area."""
        if event.type() == QEvent.Type.Wheel:
            QApplication.sendEvent(self.page_scroll.verticalScrollBar(), event)
            return True
        return super().eventFilter(obj, event)

    def _fit_tables(self):
        for t in (self.fit_table, self.contact_table, self.stats_table):
            fit_table_height(t)

    # ------------------------------------------------------------ model access
    @property
    def _shf(self) -> dict:
        return self.model.project.shf

    def _ds(self):
        return self.model.active_well

    def _all_only(self):
        ds = self._ds()
        if ds is None:
            return False, ""
        return svc.all_only_for(self.model, ds)

    def _request_stale(self, keys=None):
        self.stale_requested.emit(list(keys or []))

    def _write(self, key, value, stale=True):
        """Store one project setting; the session is dirty and the wells are re-checked."""
        self._shf[key] = value
        self.model.mark_dirty()
        if stale:
            self._request_stale()

    # ------------------------------------------------------------ settings handlers
    def _on_enable_toggled(self, checked):
        if self._updating:
            return
        self._write("enabled", bool(checked))
        self._render_guidance()

    def _on_pay_toggled(self, checked):
        if self._updating:
            return
        self._write("use_for_pay", bool(checked))

    def _on_fluids_edited(self):
        if self._updating:
            return
        fluids = {k: float(s.value()) for k, s in self.fluid_spins.items()}
        if fluids == self._shf.get("fluids"):
            return
        self._confirmed = True
        self._write("fluids", fluids)
        self._render_badge()

    def _on_sigma_edited(self):
        if self._updating:
            return
        sigma = {k: float(s.value()) for k, s in self.sigma_spins.items()}
        if sigma == self._shf.get("sigma_cos"):
            return
        self._confirmed = True
        self._write("sigma_cos", sigma)
        self._render_badge()

    def _on_confirm(self):
        self._confirmed = True
        self._render_badge()

    def _on_fit_setting_changed(self, *_):
        """Settings that only change the next Fit (no effect on a run)."""
        if self._updating:
            return
        for key, value in (("weight_by", self.weight_combo.currentData()),
                           ("min_pc_psi", float(self.min_pc_spin.value())),
                           ("rock_type_source", self.rt_source_combo.currentData())):
            if self._shf.get(key) != value:
                self._write(key, value, stale=False)

    def _on_run_setting_changed(self, *_):
        if self._updating:
            return
        self._shf["perm_source"] = self.perm_combo.currentData()
        self._shf["phie_source"] = self.phie_combo.currentData()
        self._shf["fallback"] = self.fallback_combo.currentData()
        self.model.mark_dirty()
        self._request_stale()

    # ------------------------------------------------------------ display
    def _render_badge(self):
        shf = self._shf
        defaults = (shf.get("fluids") == SHF_DEFAULTS["fluids"]
                    and shf.get("sigma_cos") == SHF_DEFAULTS["sigma_cos"])
        self.defaults_badge.setVisible(defaults and not self._confirmed)
        self.confirm_button.setVisible(defaults and not self._confirmed)

    def _fill_controls(self):
        shf = self._shf
        was = self._updating
        self._updating = True
        try:
            self.enable_check.setChecked(bool(shf.get("enabled")))
            self.pay_check.setChecked(bool(shf.get("use_for_pay")))
            for key, spin in self.fluid_spins.items():
                spin.setValue(float((shf.get("fluids") or {}).get(key, spin.value())))
            for key, spin in self.sigma_spins.items():
                spin.setValue(float((shf.get("sigma_cos") or {}).get(key, spin.value())))
            _set_combo(self.weight_combo, shf.get("weight_by", "sample"))
            self.min_pc_spin.setValue(float(shf.get("min_pc_psi") or 0.0))
            _set_combo(self.rt_source_combo, shf.get("rock_type_source", "auto"))
            _set_combo(self.perm_combo, shf.get("perm_source", "auto"))
            _set_combo(self.phie_combo, shf.get("phie_source", "PHIE"))
            _set_combo(self.fallback_combo, shf.get("fallback", "none"))
        finally:
            self._updating = was

    def update_display(self):
        """Rebuild everything from the model (project settings, Pc data, active-well results)."""
        self._fill_controls()
        self._render_badge()
        self._render_all()

    def update_active_well(self):
        """The active well changed: its contacts, misfit and plots."""
        self._estimate = None
        self._estimate_text = ""
        self._render_well()
        self._render_plots()
        self._render_guidance()

    def _render_all(self):
        self._render_fits()
        self._render_well()
        self._render_plots()
        self._render_buttons()
        self._render_guidance()

    def _render_well(self):
        self._render_contacts()
        self._render_stats()
        self._render_datum_state()

    def _applied_fits(self) -> dict:
        all_only, _ = self._all_only()
        return fits_in_use(self._shf, all_only)

    def _render_buttons(self):
        has_pc = any(getattr(ds, "pc_data", None) is not None for ds in self.model.project.wells)
        running = self._worker is not None
        self.fit_button.setEnabled(has_pc and not running)
        self.fit_button.setToolTip(
            "Fit one curve per rock type to the core Pc data of all wells." if has_pc
            else "Import capillary pressure data first (File menu).")
        has_run = any(getattr(ds, "summary", None) and (ds.summary or {}).get("shf")
                      for ds in self.model.project.wells)
        self.fit_logs_button.setEnabled(has_run and not running)
        self.apply_button.setEnabled(self._proposal is not None and not running
                                     and any(f.ok for f in self._proposal["fits"].values()))
        self.cancel_button.setEnabled(running)
        all_only, _ = self._all_only()
        refused = pay_refused_for(self._shf, all_only)
        self.pay_check.setEnabled(not refused)
        self.pay_check.setToolTip(PAY_LOG_TIP if refused else PAY_TIP)

    def _render_guidance(self, *_):
        shf = self._shf
        msg, status, run_all = "", "warning", False
        if shf.get("enabled"):
            if not shf.get("fits"):
                msg = "Fit and apply a curve to compute saturation-height Sw."
            elif not any((getattr(ds, "shf_contacts", None) or {}).get("default")
                         or (getattr(ds, "shf_contacts", None) or {}).get("zones")
                         for ds in self.model.project.wells):
                msg = "Set a free water level for the well below, then accept it."
            elif any(ds.calculated and ds.stale for ds in self.model.project.wells):
                msg = "Run Analysis (or Run All Wells) to update the saturation-height Sw."
                run_all = True
        self.enable_hint.setText(msg)
        set_status(self.enable_hint, status)
        self.enable_hint.setVisible(bool(msg))
        self.run_all_button.setVisible(run_all)
        self.run_all_button.setEnabled(not self._batch_running)

    def set_batch_running(self, running: bool):
        """Run All Wells is unavailable while a batch is running."""
        self._batch_running = bool(running)
        self.run_all_button.setEnabled(not self._batch_running)

    # ---- fits table
    def _shown_fits(self):
        """``(title, fits dict of ShfFit)``: the proposal when there is one, else the applied fits."""
        if self._proposal is not None:
            mode = self._proposal["mode"]
            return (f"Proposed fits ({BASIS_LABELS[BASIS_LOG if mode == svc.MODE_LOG else BASIS_CORE]}),"
                    " not applied", self._proposal["fits"])
        stored = self._shf.get("fits") or {}
        return "Applied fits", {k: ShfFit.from_dict(v) for k, v in stored.items()}

    def _render_fits(self):
        title, fits = self._shown_fits()
        self.fit_title.setText(title if fits else "No fits yet.")
        t = self.fit_table
        t.setRowCount(0)
        for key in sorted(fits, key=lambda s: (len(s), s)):
            f = fits[key]
            r = t.rowCount()
            t.insertRow(r)
            cells = (str(key), MODEL_LABELS.get(f.model, f.model), _param_text(f),
                     str(f.n_samples), str(f.n_points), _fmt(f.rmse),
                     BASIS_LABELS.get(f.basis, f.basis), f.status)
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == len(cells) - 1 and f.message:
                    item.setToolTip(f.message)
                t.setItem(r, c, item)
        notes = []
        _, note = self._all_only()
        self.rt_note.setText(note)
        self.rt_note.setVisible(bool(note))
        if self._proposal is not None:
            rep = self._proposal.get("report") or {}
            if rep.get("excluded"):
                notes.append("Left out: " + ", ".join(f"{n} samples with {why}"
                                                      for why, n in rep["excluded"].items()) + ".")
            if rep.get("per_type"):
                notes.append("Samples per rock type: " + ", ".join(
                    f"{k} {v}" for k, v in sorted(rep["per_type"].items())) + ".")
            if rep.get("skipped"):
                notes.append("No permeability or porosity column in the last run of: "
                             + ", ".join(rep["skipped"]) + ".")
        self.fit_notes.setText(" ".join(notes))
        fit_table_height(t)

    # ---- contacts
    def _datum_kb(self):
        return self.datum_combo.currentData() or "TVD", self.kb_edit.text()

    def _render_contacts(self):
        ds = self._ds()
        self.contact_group.setEnabled(ds is not None)
        t = self.contact_table
        was = self._updating
        self._updating = True
        try:
            t.setRowCount(0)
            if ds is None:
                self.kb_hint.setText("")
                return
            contacts = ds.shf_contacts or {}
            _set_combo(self.datum_combo, contacts.get("datum") or "TVD")
            kb = contacts.get("kb_ft")
            self.kb_edit.setText(_num_text(kb))
            rows = [(None, DEFAULT_ROW, contacts.get("default") or {})]
            zones = contacts.get("zones") or {}
            names = list(self.model.zones_for(ds))
            names += [z for z in zones if z not in names]
            rows += [(z, z, zones.get(z) or {}) for z in names]
            for zone, label, row in rows:
                r = t.rowCount()
                t.insertRow(r)
                head = QTableWidgetItem(label)
                head.setData(Qt.ItemDataRole.UserRole, zone)
                head.setFlags(head.flags() & ~Qt.ItemFlag.ItemIsEditable)
                t.setItem(r, 0, head)
                t.setItem(r, 1, QTableWidgetItem(_num_text(row.get("fwl"))))
                combo = QComboBox()
                for fluid in svc.FLUIDS:
                    combo.addItem(fluid, fluid)
                _set_combo(combo, row.get("fluid") or "oil")
                t.setCellWidget(r, 2, combo)
                t.setItem(r, 3, QTableWidgetItem(_num_text(row.get("water_density"))))
            info = ds.well_info
            parts = []
            if info.get("kb_elevation") is not None:
                parts.append(f"KB {info['kb_elevation']} {info.get('kb_elevation_unit', '')}".strip())
            if info.get("depth_measured_from"):
                parts.append(f"depth measured from {info['depth_measured_from']}")
            if info.get("permanent_datum"):
                parts.append(f"permanent datum {info['permanent_datum']}")
            self.kb_hint.setText(("Header: " + "; ".join(parts) + ". Type the KB in ft to use it.")
                                 if parts else "")
        finally:
            self._updating = was
        fit_table_height(t)
        self.contact_status.setText(self._estimate_text)

    def _contact_rows(self):
        rows = []
        for r in range(self.contact_table.rowCount()):
            head = self.contact_table.item(r, 0)
            fwl = self.contact_table.item(r, 1)
            water = self.contact_table.item(r, 3)
            combo = self.contact_table.cellWidget(r, 2)
            rows.append({"zone": head.data(Qt.ItemDataRole.UserRole),
                         "fwl": fwl.text() if fwl else "",
                         "fluid": combo.currentData() if combo else "oil",
                         "water": water.text() if water else ""})
        return rows

    def _kb_ok(self) -> bool:
        datum, kb = self._datum_kb()
        if datum != "TVDSS":
            return True
        try:
            return bool(np.isfinite(float(kb.replace(",", "."))))
        except ValueError:
            return False

    def _render_datum_state(self):
        ok = self._kb_ok() and self._ds() is not None
        self.accept_button.setEnabled(ok)
        self.estimate_button.setEnabled(ok and self._ds() is not None)
        datum, _ = self._datum_kb()
        if datum == "TVDSS" and not self._kb_ok():
            self.contact_status.setText("KB required for TVDSS")
            set_status(self.contact_status, "warning")
        elif self.contact_status.text() == "KB required for TVDSS":
            self.contact_status.setText(self._estimate_text)
            set_status(self.contact_status, "muted")

    def _on_datum_changed(self, *_):
        if self._updating:
            return
        self._render_datum_state()

    def _on_accept(self):
        ds = self._ds()
        if ds is None or not self._kb_ok():
            return
        datum, kb = self._datum_kb()
        contacts, message = svc.parse_contacts(self._contact_rows(), datum, kb)
        if contacts is None:
            self.contact_status.setText(message)
            set_status(self.contact_status, "error")
            return
        if svc.store_contacts(ds, contacts):
            self.model.mark_dirty()
            self._request_stale([ds.key])
            text = "Contacts stored for this well. Run Analysis to use them."
        else:
            text = "Contacts are unchanged."
        self._estimate = None
        self._estimate_text = ""
        self.contact_status.setText(text)
        set_status(self.contact_status, "success")
        self._render_guidance()
        self._render_plots()

    def _on_estimate(self):
        ds = self._ds()
        if ds is None or not self._kb_ok():
            return
        r = self.contact_table.currentRow()
        r = 0 if r < 0 else r
        rows = self._contact_rows()
        row = rows[r]
        water = None
        if row["water"].strip():
            try:
                water = float(row["water"].replace(",", "."))
            except ValueError:
                water = None
        lo, hi = svc.WATER_DENSITY_RANGE
        if water is not None and not (lo <= water <= hi):
            self.contact_status.setText(
                f"Water density {row['water']} g/cc is outside {lo:g}-{hi:g} g/cc.")
            set_status(self.contact_status, "error")
            return
        est = svc.estimate_for_well(self.model, ds, row["zone"], row["fluid"], water)
        self._estimate = est
        datum, kb = self._datum_kb()
        if est.identifiable:
            shift = float(kb.replace(",", ".")) if datum == "TVDSS" else 0.0
            value = est.fwl_ft - shift
            interval = est.interval_ft or [est.fwl_ft, est.fwl_ft]
            self._estimate_text = (
                f"Estimated FWL {value:.1f} ft ({datum}), interval {interval[0] - shift:.0f} to "
                f"{interval[1] - shift:.0f} ft, RMSE {est.rmse:.3f}. Press Accept to store it.")
            item = self.contact_table.item(r, 1)
            if item is not None:
                item.setText(f"{value:.1f}")
            set_status(self.contact_status, "success")
        else:
            self._estimate_text = est.reason or est.status
            set_status(self.contact_status, "warning")
        self.contact_status.setText(self._estimate_text)
        self._render_plots()

    # ---- misfit
    def _render_stats(self):
        ds = self._ds()
        info = ((getattr(ds, "summary", None) or {}).get("shf") if ds is not None else None)
        t = self.stats_table
        t.setRowCount(0)
        if not info:
            self.stats_notes.setText("Run the active well with saturation height on to see "
                                     "the misfit.")
            fit_table_height(t)
            return
        stats = info.get("stats") or {}
        rows = [("Well", stats.get("well") or {})]
        rows += [(f"Zone {z['zone']}", z) for z in stats.get("zones", [])]
        rows += [(f"Rock type {z['rock_type']}", z) for z in stats.get("rock_types", [])]
        for label, s in rows:
            r = t.rowCount()
            t.insertRow(r)
            basis = BASIS_LABELS.get(s.get("basis"), s.get("basis") or "")
            for c, text in enumerate((label, str(s.get("n", "")), _fmt(s.get("bias")),
                                      _fmt(s.get("rmse")), _fmt(s.get("mae")), _fmt(s.get("r2")),
                                      str(basis))):
                t.setItem(r, c, QTableWidgetItem(text))
        counts = info.get("counts") or {}
        self.stats_notes.setText(
            f"{counts.get('samples_modelled', 0)} of {counts.get('samples', 0)} samples modelled. "
            f"Height on {info.get('tvd_source') or 'TVD'}. Bias is SW minus SW_SHF.")
        fit_table_height(t)

    # ------------------------------------------------------------ plots
    def _plot_fits(self) -> dict:
        _, fits = self._shown_fits()
        return {k: f for k, f in fits.items() if f.ok}

    def _render_plots(self):
        self._plot_j_sw()
        self._plot_sw_height()
        self._plot_fwl_profile()

    def _type_color(self, key, keys):
        if key == ALL:
            return get_plot_color("SW")
        try:
            return get_rock_type_color(int(key), max(len(keys), 2))
        except ValueError:
            return get_plot_color("SW")

    def _basis_title(self, fits) -> str:
        bases = {f.basis for f in fits.values()}
        if not bases:
            return ""
        return " (" + ("log-derived" if bases == {BASIS_LOG} else
                       "core Pc" if bases == {BASIS_CORE} else "core Pc and log-derived") + ")"

    def _plot_j_sw(self):
        pw = self.plot_j
        fits = self._plot_fits()
        groups = {}
        try:
            if self._proposal is None or self._proposal["mode"] == svc.MODE_CORE:
                groups, _ = svc.collect_core_curves(self.model)
        except Exception:
            logger.exception("Could not collect the Pc curves for the plot")
        if not groups and not fits:
            pw.clear()
            return
        ax = pw.get_axes()
        keys = sorted(set(groups) | set(fits), key=lambda s: (len(s), s))
        for key in keys:
            color = self._type_color(key, keys)
            xs, ys = [], []
            for c in groups.get(key, []):
                j = leverett_j(np.asarray(c.pc_psi, float), c.k_md, c.phi, c.sigma_cos_lab)
                sw = np.asarray(c.sw, float)
                ok = np.isfinite(j) & (j > 0) & np.isfinite(sw)
                xs.append(sw[ok])
                ys.append(j[ok])
            if xs:
                ax.scatter(np.concatenate(xs), np.concatenate(ys), s=10, color=color, alpha=0.6,
                           label=f"Rock type {key}" if key != ALL else "All")
            fit = fits.get(key)
            if fit is not None:
                j_grid = np.logspace(-2, 1.5, 200)
                ax.plot(sw_from_j(j_grid, fit.model, fit.params), j_grid, color=color,
                        linewidth=1.5)
        ax.set_yscale("log")
        ax.set_xlim(0, 1)
        ax.set_xlabel("Sw (fraction)")
        ax.set_ylabel("Leverett J")
        ax.set_title("J versus Sw" + self._basis_title(fits))
        if ax.get_legend_handles_labels()[0]:
            ax.legend(fontsize=8, loc="best")
        pw.refresh()

    def _plot_sw_height(self):
        pw = self.plot_height
        ds = self._ds()
        res = getattr(ds, "results", None) if ds is not None else None
        info = ((getattr(ds, "summary", None) or {}).get("shf") if ds is not None else None)
        if res is None or not info or "HAFWL" not in res.columns:
            pw.clear()
            return
        h = pd.to_numeric(res["HAFWL"], errors="coerce").to_numpy(dtype=float)
        ax = pw.get_axes()
        if "SW" in res.columns:
            ax.scatter(pd.to_numeric(res["SW"], errors="coerce"), h, s=6,
                       color=get_plot_color("SW"), alpha=0.5, label="SW")
        if "SW_SHF" in res.columns:
            ax.scatter(pd.to_numeric(res["SW_SHF"], errors="coerce"), h, s=6,
                       color=get_plot_color("PAY"), alpha=0.5, label="SW_SHF")
        ax.axhline(0.0, color=get_plot_color("FORMATION_TOP"), linestyle="--", linewidth=1,
                   label="FWL")
        ax.set_xlim(0, 1)
        ax.set_xlabel("Sw (fraction)")
        ax.set_ylabel("Height above FWL (ft)")
        ax.set_title("Sw versus height" + self._basis_title(self._plot_fits()))
        ax.legend(fontsize=8, loc="best")
        pw.refresh()

    def _plot_fwl_profile(self):
        pw = self.plot_profile
        est = self._estimate
        if est is None or not est.grid_ft:
            pw.clear()
            return
        ax = pw.get_axes()
        prof = np.asarray([np.nan if v is None else v for v in est.rmse_profile], dtype=float)
        ax.plot(est.grid_ft, prof, color=get_plot_color("SW"), linewidth=1.5)
        if est.identifiable:
            ax.axvline(est.fwl_ft, color=get_plot_color("FORMATION_TOP"), linestyle="--",
                       linewidth=1, label="Estimate")
            ax.legend(fontsize=8, loc="best")
        ax.set_xlabel("FWL (ft, TVD)")
        ax.set_ylabel("RMSE of Sw")
        ax.set_title("FWL profile" + self._basis_title(self._plot_fits()))
        pw.refresh()

    # ------------------------------------------------------------ fit worker
    def _running(self) -> bool:
        return self._worker is not None

    def _on_fit(self, mode):
        if self._running():
            return
        worker = svc.ShfWorker.from_model(self.model, mode, self.model_combo.currentData())
        worker.setAutoDelete(False)          # the tab owns it until a result signal arrives
        worker.signals.progress.connect(self._on_progress)
        worker.signals.completed.connect(self._on_completed)
        worker.signals.error.connect(self._on_error)
        worker.signals.cancelled.connect(self._on_cancelled)
        self._worker = worker
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self._render_buttons()
        self._set_status("Fitting...", "muted")
        QThreadPool.globalInstance().start(worker)

    def _on_cancel(self):
        if self._worker is not None:
            self._worker.cancel()
            self.cancel_button.setEnabled(False)
            self._set_status("Cancelling...", "muted")

    def _on_progress(self, message, percent):
        self.progress.setValue(int(percent))
        self._set_status(message, "muted")

    def _finish_run(self):
        self._worker = None
        self.progress.setVisible(False)

    def _on_completed(self, proposal):
        self._finish_run()
        self._proposal = proposal
        fits = proposal["fits"]
        ok = sum(1 for f in fits.values() if f.ok)
        if not fits:
            text = "Nothing to fit: no usable samples."
            status = "warning"
        elif ok:
            text = f"Proposal: {ok} of {len(fits)} rock types fitted. Review it, then Apply fit."
            status = "success"
        else:
            text = "No rock type had enough data to fit."
            status = "warning"
        self._render_fits()
        self._render_plots()
        self._render_buttons()
        self._set_status(text, status)
        self.fit_finished.emit()

    def _on_error(self, message):
        self._finish_run()
        self._render_buttons()
        first = message.strip().splitlines()[0] if message.strip() else "Fit failed."
        self._set_status(first, "error")
        self.status_label.setToolTip(message)
        self.fit_finished.emit()

    def _on_cancelled(self):
        self._finish_run()
        self._render_buttons()
        self._set_status("Fit cancelled. Nothing was changed.", "muted")
        self.fit_finished.emit()

    def _on_apply(self):
        if self._proposal is None or self._running():
            return
        stored = svc.store_fits(self.model, self._proposal["fits"])
        self._proposal = None
        self._request_stale()
        self._render_fits()
        self._render_plots()
        self._render_buttons()
        self._render_guidance()
        self._set_status(f"Applied {len(stored)} fit(s) to the project. Run Analysis to use them.",
                         "success")

    def _set_status(self, text, status):
        self.status_label.setText(text)
        self.status_label.setToolTip("")
        set_status(self.status_label, status)

    # ------------------------------------------------------------ lifecycle
    def refresh_theme(self):
        for plot in (self.plot_j, self.plot_height, self.plot_profile):
            plot.refresh_theme()
        self._render_plots()

    def reset_ui(self):
        """Reset for New Project: drop the proposal and show the empty state."""
        self._proposal = None
        self._estimate = None
        self._estimate_text = ""
        self._confirmed = False
        self.status_label.setText("")
        self.status_label.setToolTip("")
        self.contact_status.setText("")
        self.update_display()
