"""
Rock Typing Tab for Petrophyter PyQt
Fit rock-type definitions from core (FZI clustering or Winland R35), review them, apply them to
the project. The fit runs on a worker thread and only proposes; Apply is the single write
(P1 rock-typing spec, section 7.1).
"""

import copy
import logging

import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt, QThreadPool, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from modules import rock_typing as rt
from services import rock_typing_service as svc
from themes.colors import get_plot_color, get_rock_type_color
from themes.helpers import set_status
from ..widgets.plot_widget import PlotWidget
from ..widgets.table_model import PandasTableModel


logger = logging.getLogger(__name__)

METHODS = (("fzi", "FZI clustering"), ("r35", "Winland R35"))
SCOPES = (("project", "Project pooled"), ("well", "Per well"), ("zone", "Per zone"))
# Settings that the Fit uses; changing them in the controls never edits applied definitions.
FIT_ONLY = set(svc.FIT_SETTING_KEYS)
ISO_R35_UM = (0.1, 0.5, 2.0, 10.0)
MAX_LOG_POINTS = 2000
WELL_SCOPE_NOTE = "Rock type IDs are not comparable between wells."
DEF_COLUMNS = ("RT", "Samples", "Centre (log10)", "FZI (um)", "Lower", "Upper", "k RMSE (log10)",
               "Colour")
PAY_COLUMNS = (("rt", "RT"), ("samples", "Samples"), ("gross_sand", "Gross sand"),
               ("net_reservoir", "Net res."), ("net_pay", "Net pay"), ("ng_pay", "N/G pay"),
               ("avg_phie_pay", "Avg PHIE"), ("avg_sw_pay", "Avg Sw"),
               ("hcpv_net_pay", "HCPV net pay"), ("perm_geomean", "k geomean"),
               ("fzi", "FZI"), ("pct_core", "% core"))


def rt_colors(n: int) -> list:
    """Rock types 1..n as ``(r, g, b)`` fractions, from the same ramp as the Rock Type log track."""
    n = max(int(n), 1)
    hexes = [get_rock_type_color(i, n) for i in range(1, n + 1)]
    return [tuple(int(h[j:j + 2], 16) / 255.0 for j in (1, 3, 5)) for h in hexes]


def _fmt(value, digits=3) -> str:
    if value is None:
        return ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    return "" if not np.isfinite(v) else f"{v:.{digits}f}"


class RockTypingTab(QWidget):
    """Rock Typing tab: controls on the left, plots and tables on the right."""

    fit_finished = pyqtSignal()      # a Fit ended (completed, refused or cancelled)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self._proposal = None            # fitted, not yet applied (includes "_display")
        self._worker = None
        self._suggested = None
        self._table = None               # core table (DataFrame) of the current settings
        self._report = None
        self._set_key = svc.POOLED_KEY
        self._last_stored = None         # stored definitions the controls were last filled from
        self._updating = False
        self._setup_ui()
        self.update_display()

    # ------------------------------------------------------------------ UI
    def _setup_ui(self):
        root = QHBoxLayout(self)
        root.addWidget(self._build_controls(), 0)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.stale_banner = QLabel("")
        self.stale_banner.setWordWrap(True)
        set_status(self.stale_banner, "warning")
        self.stale_banner.setVisible(False)
        self.scope_note = QLabel(WELL_SCOPE_NOTE)
        set_status(self.scope_note, "muted")
        self.scope_note.setVisible(False)
        rl.addWidget(self.stale_banner)
        rl.addWidget(self.scope_note)

        self.stack = QStackedWidget()
        self.placeholder = QLabel("")
        self.placeholder.setObjectName("PlaceholderLabel")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.stack.addWidget(self.placeholder)
        self.stack.addWidget(self._build_content())
        rl.addWidget(self.stack, 1)
        root.addWidget(right, 1)

    def _build_controls(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(260)
        panel.setMaximumWidth(320)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        v = QVBoxLayout(inner)

        def section(text):
            label = QLabel(text.upper())
            label.setObjectName("SectionLabel")
            v.addWidget(label)

        section("Fit")
        form = QGridLayout()
        form.addWidget(QLabel("Method"), 0, 0)
        self.method_combo = QComboBox()
        for key, text in METHODS:
            self.method_combo.addItem(text, key)
        form.addWidget(self.method_combo, 0, 1)
        form.addWidget(QLabel("Fit scope"), 1, 0)
        self.scope_combo = QComboBox()
        for key, text in SCOPES:
            self.scope_combo.addItem(text, key)
        form.addWidget(self.scope_combo, 1, 1)
        form.addWidget(QLabel("Rock types"), 2, 0)
        self.n_rt_spin = QSpinBox()
        self.n_rt_spin.setRange(2, 10)
        self.n_rt_spin.setValue(svc.DEFAULT_N_RT)
        form.addWidget(self.n_rt_spin, 2, 1)
        self.suggested_label = QLabel("Suggested: -")
        set_status(self.suggested_label, "muted")
        form.addWidget(self.suggested_label, 3, 1)
        v.addLayout(form)

        row = QHBoxLayout()
        self.fit_button = QPushButton("Fit")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        row.addWidget(self.fit_button)
        row.addWidget(self.cancel_button)
        v.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        v.addWidget(self.progress)
        self.apply_button = QPushButton("Apply to project")
        self.apply_button.setEnabled(False)
        v.addWidget(self.apply_button)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        set_status(self.status_label, "muted")
        v.addWidget(self.status_label)

        section("Analysis")
        self.enable_check = QCheckBox("Enable rock typing in the analysis")
        self.enable_check.setToolTip(
            "Adds ROCK_TYPE, RQI, FZI and related columns to the results. Needs applied "
            "definitions.")
        v.addWidget(self.enable_check)
        self.enable_hint = QLabel("")
        self.enable_hint.setWordWrap(True)
        set_status(self.enable_hint, "warning")
        self.enable_hint.setVisible(False)
        v.addWidget(self.enable_hint)

        section("Settings")
        self.reservoir_check = QCheckBox("Reservoir only (gross sand)")
        self.core_labels_check = QCheckBox("Use core labels in the log")
        self.lorenz_check = QCheckBox("Lorenz coefficient and SMLP")
        self.r35_check = QCheckBox("Add R35 column")
        for w in (self.reservoir_check, self.core_labels_check, self.lorenz_check,
                  self.r35_check):
            v.addWidget(w)
        sg = QGridLayout()
        sg.addWidget(QLabel("Min PHIE"), 0, 0)
        self.min_phie_spin = QDoubleSpinBox()
        self.min_phie_spin.setRange(0.0, 0.3)
        self.min_phie_spin.setDecimals(3)
        self.min_phie_spin.setSingleStep(0.005)
        sg.addWidget(self.min_phie_spin, 0, 1)
        sg.addWidget(QLabel("Overburden phi factor"), 1, 0)
        self.ob_phi_spin = QDoubleSpinBox()
        sg.addWidget(self.ob_phi_spin, 1, 1)
        sg.addWidget(QLabel("Overburden k factor"), 2, 0)
        self.ob_k_spin = QDoubleSpinBox()
        sg.addWidget(self.ob_k_spin, 2, 1)
        for spin in (self.ob_phi_spin, self.ob_k_spin):
            spin.setRange(0.1, 2.0)
            spin.setDecimals(3)
            spin.setSingleStep(0.05)
        self.ob_phi_spin.setToolTip("Applied to core porosity before RQI. Used by the next Fit.")
        self.ob_k_spin.setToolTip("Applied to core permeability before RQI. Used by the next Fit.")
        v.addLayout(sg)
        v.addStretch(1)
        scroll.setWidget(inner)
        lay.addWidget(scroll)

        self._fill_controls(rt.DEFAULT_SETTINGS)
        self.method_combo.currentIndexChanged.connect(self._on_method_changed)
        self.scope_combo.currentIndexChanged.connect(self._on_scope_changed)
        self.fit_button.clicked.connect(self._on_fit)
        self.cancel_button.clicked.connect(self._on_cancel)
        self.apply_button.clicked.connect(self._on_apply)
        self.enable_check.toggled.connect(self._on_enable_toggled)
        for w in (self.reservoir_check, self.core_labels_check, self.lorenz_check,
                  self.r35_check):
            w.toggled.connect(self._on_setting_changed)
        for w in (self.min_phie_spin, self.ob_phi_spin, self.ob_k_spin):
            w.valueChanged.connect(self._on_setting_changed)
        return panel

    def _build_content(self) -> QWidget:
        split = QSplitter(Qt.Orientation.Vertical)
        self.plot_tabs = QTabWidget()
        self.plot_fzi = PlotWidget(figsize=(8, 4))
        self.plot_phik = PlotWidget(figsize=(8, 4))
        self.plot_rqi = PlotWidget(figsize=(8, 4))
        self.plot_r35 = PlotWidget(figsize=(8, 4))
        lorenz = QWidget()
        ll = QVBoxLayout(lorenz)
        ll.setContentsMargins(0, 0, 0, 0)
        self.plot_lorenz = PlotWidget(figsize=(8, 4))
        ll.addWidget(self.plot_lorenz, 3)
        self.lorenz_label = QLabel("")
        set_status(self.lorenz_label, "muted")
        ll.addWidget(self.lorenz_label)
        self.units_view = QTableView()
        self.units_view.setModel(PandasTableModel(pd.DataFrame(), float_decimals=3))
        self.units_view.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        ll.addWidget(self.units_view, 1)
        for widget, title in ((self.plot_fzi, "FZI"), (self.plot_phik, "Phi-K"),
                              (self.plot_rqi, "RQI-phiz"), (self.plot_r35, "R35"),
                              (lorenz, "Lorenz")):
            self.plot_tabs.addTab(widget, title)
        split.addWidget(self.plot_tabs)

        lower = QScrollArea()
        lower.setWidgetResizable(True)
        lower.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        bl = QVBoxLayout(body)

        self.defs_group = QGroupBox("Rock type definitions")
        dl = QVBoxLayout(self.defs_group)
        top = QHBoxLayout()
        self.defs_basis = QLabel("")
        set_status(self.defs_basis, "muted")
        top.addWidget(self.defs_basis, 1)
        self.set_label = QLabel("Set")
        self.set_combo = QComboBox()
        self.set_label.setVisible(False)
        self.set_combo.setVisible(False)
        top.addWidget(self.set_label)
        top.addWidget(self.set_combo)
        dl.addLayout(top)
        self.defs_table = QTableWidget(0, len(DEF_COLUMNS))
        self.defs_table.setHorizontalHeaderLabels(list(DEF_COLUMNS))
        self.defs_table.verticalHeader().setVisible(False)
        self.defs_table.setMinimumHeight(140)
        dl.addWidget(self.defs_table)
        bl.addWidget(self.defs_group)

        self.excl_group = QGroupBox("Core exclusions")
        el = QVBoxLayout(self.excl_group)
        self.excl_table = QTableWidget(0, 4)
        self.excl_table.setHorizontalHeaderLabels(
            ["Reason", "Rows", "Wells", "Of which excluded at load"])
        self.excl_table.verticalHeader().setVisible(False)
        self.excl_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.excl_table.setMinimumHeight(120)
        el.addWidget(self.excl_table)
        self.excl_notes = QLabel("")
        self.excl_notes.setWordWrap(True)
        set_status(self.excl_notes, "muted")
        el.addWidget(self.excl_notes)
        bl.addWidget(self.excl_group)

        self.pay_group = QGroupBox("Pay per rock type (active well)")
        pl = QVBoxLayout(self.pay_group)
        self.pay_table = QTableWidget(0, len(PAY_COLUMNS))
        self.pay_table.setHorizontalHeaderLabels([c[1] for c in PAY_COLUMNS])
        self.pay_table.verticalHeader().setVisible(False)
        self.pay_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.pay_table.setMinimumHeight(120)
        pl.addWidget(self.pay_table)
        self.pay_notes = QLabel("")
        self.pay_notes.setWordWrap(True)
        set_status(self.pay_notes, "muted")
        pl.addWidget(self.pay_notes)
        self.pay_group.setVisible(False)
        bl.addWidget(self.pay_group)
        bl.addStretch(1)
        lower.setWidget(body)
        split.addWidget(lower)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        self.set_combo.currentIndexChanged.connect(self._on_set_changed)
        self.defs_table.itemChanged.connect(self._on_def_edited)
        return split

    # ----------------------------------------------------------- settings
    def _fill_controls(self, settings: dict):
        """Fill the controls from a settings dict without emitting changes."""
        s = dict(rt.DEFAULT_SETTINGS)
        s.update(settings or {})
        was = self._updating
        self._updating = True
        try:
            self.reservoir_check.setChecked(bool(s["reservoir_only"]))
            self.core_labels_check.setChecked(bool(s["use_core_labels"]))
            self.lorenz_check.setChecked(bool(s["lorenz"]))
            self.r35_check.setChecked(bool(s["r35_column"]))
            self.min_phie_spin.setValue(float(s["min_phie"]))
            self.ob_phi_spin.setValue(float(s["ob_phi_factor"]))
            self.ob_k_spin.setValue(float(s["ob_k_factor"]))
        finally:
            self._updating = was

    def settings(self) -> dict:
        """Full settings dict: stored/default values overlaid with the controls."""
        s = dict(rt.DEFAULT_SETTINGS)
        stored = self.model.project.rock_types
        if stored and stored.get("settings"):
            s.update(stored["settings"])
        s.update({
            "reservoir_only": self.reservoir_check.isChecked(),
            "use_core_labels": self.core_labels_check.isChecked(),
            "lorenz": self.lorenz_check.isChecked(),
            "r35_column": self.r35_check.isChecked(),
            "min_phie": float(self.min_phie_spin.value()),
            "ob_phi_factor": float(self.ob_phi_spin.value()),
            "ob_k_factor": float(self.ob_k_spin.value()),
        })
        return s

    def _stored(self):
        return getattr(self.model.project, "rock_types", None) or None

    def _current(self):
        """The definitions on show: the pending proposal, else the applied ones."""
        return self._proposal or self._stored()

    # ------------------------------------------------------------- refresh
    def update_display(self):
        """Rebuild everything from the model (core, applied definitions, active-well results)."""
        stored = self._stored()
        if stored is not self._last_stored:
            self._last_stored = stored
            if stored and stored.get("settings") and self._proposal is None:
                self._fill_controls(stored["settings"])
            if stored:
                self._set_combo_value(self.method_combo, stored.get("method", "fzi"))
                self._set_combo_value(self.scope_combo, stored.get("fit_scope", "project"))
        self._updating = True
        try:
            self.enable_check.setChecked(bool(getattr(self.model, "rock_typing_enabled", False)))
        finally:
            self._updating = False
        self._render()

    def _set_combo_value(self, combo, key):
        was = self._updating
        self._updating = True
        try:
            i = combo.findData(key)
            if i >= 0:
                combo.setCurrentIndex(i)
        finally:
            self._updating = was
        self._sync_method_widgets()

    def _sync_method_widgets(self):
        r35 = self.method_combo.currentData() == "r35"
        self.n_rt_spin.setEnabled(not r35 and not self._running())
        if r35:
            self.n_rt_spin.setValue(len(rt.R35_CLASSES))

    def _running(self) -> bool:
        return self._worker is not None

    def _render(self):
        inputs = rt.core_inputs(self.model)
        self._table, self._report = rt.build_core_table(inputs, self.settings())
        valid = int(self._report["valid"])
        reason = None if valid else self._missing_reason(inputs)
        self.fit_button.setEnabled(valid > 0 and not self._running())
        self.apply_button.setEnabled(self._proposal is not None and not self._running())
        self.stack.setCurrentIndex(0 if reason else 1)
        self.placeholder.setText(reason or "")
        defs = self._current()
        self._render_banner(defs)
        self._render_enable_hint()
        if not reason:
            if not self._running() and self._proposal is None:
                self._set_status_text(self._counts_text(), "muted")
            self._render_set_combo(defs)
            self._render_all(defs)

    def _missing_reason(self, inputs) -> str:
        wells = list(self.model.project.wells)
        cores = [w for w in wells if getattr(w, "core_data", None) is not None]
        if not cores:
            return ("No core data loaded. Rock typing needs core with porosity and permeability "
                    "in the same row. Load core data to begin.")
        if not inputs:
            miss = []
            for w in cores:
                c = w.core_data
                if not getattr(c, "porosity_col", None):
                    miss.append("porosity")
                if not getattr(c, "perm_col", None):
                    miss.append("permeability")
                if not getattr(c, "depth_col", None):
                    miss.append("depth")
            what = " and ".join(sorted(set(miss))) or "porosity and permeability"
            return f"The loaded core has no {what} column. Rock typing needs both porosity and permeability."
        ex = self._report["excluded"]
        why = ", ".join(f"{n} {r}" for r, n in ex.items()) or "no rows"
        return (f"No core row has both a usable porosity and a permeability above zero "
                f"({self._report['rows']} rows: {why}).")

    def _counts_text(self) -> str:
        r = self._report
        wells = len(r["per_well"])
        text = f"{r['valid']} of {r['rows']} core rows are usable in {wells} well(s)."
        if r["excluded"]:
            text += " Excluded: " + ", ".join(f"{n} {k}" for k, n in r["excluded"].items()) + "."
        return text

    def _set_status_text(self, text: str, status):
        self.status_label.setText(text)
        set_status(self.status_label, status)

    def _render_banner(self, defs):
        msg = ""
        if defs:
            try:
                stale = svc.fingerprint_is_stale(defs, self.model)
            except Exception:                      # a fingerprint problem must not break the tab
                logger.exception("fingerprint check failed")
                stale = False
            if stale:
                msg = "Core data changed since this fit; refit."
            elif self._proposal is None and self._fit_settings_differ(defs):
                msg = "Fit settings changed since this fit; refit."
        self.stale_banner.setText(msg)
        self.stale_banner.setVisible(bool(msg))
        scope = (defs or {}).get("fit_scope") if defs else None
        self.scope_note.setVisible(scope == "well" or self.scope_combo.currentData() == "well")

    def _fit_settings_differ(self, defs) -> bool:
        stored = defs.get("settings") or {}
        ui = self.settings()
        return any(abs(float(ui[k]) - float(stored.get(k, rt.DEFAULT_SETTINGS[k]))) > 1e-9
                   for k in ("ob_phi_factor", "ob_k_factor"))

    def _render_enable_hint(self):
        on = self.enable_check.isChecked()
        msg = "No definitions applied yet: fit and apply rock types first." \
            if on and not self._stored() else ""
        self.enable_hint.setText(msg)
        self.enable_hint.setVisible(bool(msg))

    # -------------------------------------------------------- data for plots
    def _render_set_combo(self, defs):
        keys = list((defs or {}).get("sets", {}).keys())
        was = self._updating
        self._updating = True
        try:
            self.set_combo.clear()
            for k in keys:
                self.set_combo.addItem("Pooled" if k == svc.POOLED_KEY else str(k), k)
            show = len(keys) > 1
            self.set_label.setVisible(show)
            self.set_combo.setVisible(show)
            if self._set_key not in keys:
                self._set_key = svc.POOLED_KEY if svc.POOLED_KEY in keys else (keys[0] if keys else svc.POOLED_KEY)
            i = self.set_combo.findData(self._set_key)
            if i >= 0:
                self.set_combo.setCurrentIndex(i)
        finally:
            self._updating = was

    def _feature_for(self, df: pd.DataFrame, method: str) -> np.ndarray:
        if method == "r35":
            return np.log10(rt.winland_r35(df["k"].to_numpy(float), df["phi"].to_numpy(float)))
        return df["log_fzi"].to_numpy(float)

    def _valid_rows(self, defs):
        """Valid core rows with a finite feature for the method of ``defs`` (or the control)."""
        if self._table is None or not len(self._table):
            return pd.DataFrame(), "fzi"
        method = (defs or {}).get("method") or self.method_combo.currentData()
        ok = self._table[self._table["status"] == rt.STATUS_OK].copy()
        ok["feature"] = self._feature_for(ok, method) if len(ok) else np.array([])
        ok = ok[np.isfinite(ok["feature"].to_numpy(float))]
        return ok, method

    def _rows_for_key(self, rows: pd.DataFrame, defs, key) -> pd.DataFrame:
        scope = (defs or {}).get("fit_scope", "project")
        if key == svc.POOLED_KEY or scope == "project":
            return rows
        if scope == "well":
            return rows[rows["well_key"] == key]
        return rows[rows["zone"] == key]

    def _active_set(self, defs):
        if not defs:
            return None
        sets = defs.get("sets") or {}
        return sets.get(self._set_key) or sets.get(svc.POOLED_KEY)

    def _labels(self, rows: pd.DataFrame, rset):
        if rset is None or not len(rows):
            return np.zeros(len(rows), dtype=int)
        lab, _ = rt.classify(rows["feature"].to_numpy(float), rset)
        return lab

    # --------------------------------------------------------------- render
    def _render_all(self, defs):
        rows, method = self._valid_rows(defs)
        rset = self._active_set(defs)
        sub = self._rows_for_key(rows, defs, self._set_key)
        labels = self._labels(sub, rset)
        n_rt = int(rset["n_rt"]) if rset else 0
        self._render_defs_table(defs, rset, sub, labels, method)
        self._render_exclusions()
        self._render_pay()
        self._plot_fzi(sub, labels, rset, method)
        self._plot_phik(sub, labels, rset, n_rt)
        self._plot_rqi(sub, labels, rset, n_rt)
        self._plot_r35(sub)
        self._plot_lorenz()

    # ---- definitions table
    def _render_defs_table(self, defs, rset, sub, labels, method):
        t = self.defs_table
        was = self._updating
        self._updating = True
        try:
            t.setRowCount(0)
            if not rset:
                self.defs_basis.setText("No definitions yet. Fit, then Apply to project.")
                return
            n = int(rset["n_rt"])
            colors = rt_colors(n)
            bounds = rset.get("boundaries") or []
            centres = rset.get("centers") or []
            fzis = rset.get("fzi") or [None] * n
            counts = np.bincount(labels[labels > 0], minlength=n + 1)[1:n + 1] \
                if len(labels) else np.zeros(n, dtype=int)
            rmse = self._live_rmse(sub, labels, fzis, n)
            basis = rset.get("basis") or ""
            pending = " (proposal, not applied)" if self._proposal is not None else ""
            edited = "  edited manually" if rset.get("edited") else ""
            self.defs_basis.setText(f"{basis}{pending}{edited}")
            t.setRowCount(n)
            mono = QFont("Consolas", 9)
            for i in range(n):
                lower = bounds[i - 1] if i > 0 and i - 1 < len(bounds) else None
                upper = bounds[i] if i < len(bounds) else None
                cells = [
                    (str(i + 1) + (f" {rt.R35_CLASSES[i]}" if method == "r35"
                                   and i < len(rt.R35_CLASSES) else ""), False),
                    (str(int(counts[i])), False),
                    (_fmt(centres[i] if i < len(centres) else None), False),
                    (_fmt(fzis[i] if i < len(fzis) else None, 4), True),
                    (_fmt(lower, 4), i > 0),
                    (_fmt(upper, 4), i < n - 1),
                    (_fmt(rmse[i]), False),
                    ("", False),
                ]
                for c, (text, editable) in enumerate(cells):
                    item = QTableWidgetItem(text)
                    flags = item.flags()
                    item.setFlags(flags | Qt.ItemFlag.ItemIsEditable if editable
                                  else flags & ~Qt.ItemFlag.ItemIsEditable)
                    if c > 0:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                              | Qt.AlignmentFlag.AlignVCenter)
                        item.setFont(mono)
                    if c == len(cells) - 1:
                        r, g, b = colors[i]
                        item.setBackground(QBrush(QColor.fromRgbF(r, g, b)))
                    t.setItem(i, c, item)
            t.resizeColumnsToContents()
        finally:
            self._updating = was

    @staticmethod
    def _live_rmse(sub, labels, fzis, n):
        out = [None] * n
        if not len(sub):
            return out
        phi, k = sub["phi"].to_numpy(float), sub["k"].to_numpy(float)
        for i in range(n):
            f = fzis[i] if i < len(fzis) else None
            sel = labels == i + 1
            if f is None or not sel.any():
                continue
            kp = rt.perm_from_fzi(float(f), phi[sel])
            d = np.log10(k[sel]) - np.log10(kp)
            out[i] = float(np.sqrt(np.mean(d ** 2)))
        return out

    def _on_def_edited(self, item):
        if self._updating:
            return
        defs = self._current()
        rset = self._active_set(defs)
        if not rset:
            return
        row, col = item.row(), item.column()
        try:
            value = float(item.text())
        except ValueError:
            self._set_status_text("Enter a number.", "error")
            self._render()
            return
        new = copy.deepcopy(defs)
        nset = new["sets"].get(self._set_key) or new["sets"][svc.POOLED_KEY]
        bounds = list(nset["boundaries"])
        if col == 3:
            if value <= 0:
                self._set_status_text("FZI must be positive.", "error")
                self._render()
                return
            nset["fzi"][row] = value
        elif col in (4, 5):
            idx = row - 1 if col == 4 else row
            if not 0 <= idx < len(bounds):
                return
            trial = list(bounds)
            trial[idx] = value
            if any(b >= a for b, a in zip(trial[:-1], trial[1:])):
                self._set_status_text("Boundaries must increase from rock type 1 upward.", "error")
                self._render()
                return
            nset["boundaries"] = trial
        else:
            return
        nset["edited"] = True
        if self._proposal is not None:
            self._proposal = new
            self._render()
        else:
            svc.apply_definitions(self.model, new)
            self._last_stored = self._stored()
            self._set_status_text(
                f"Edited rock type {row + 1}; applied to the project. Run again to use it.",
                "success")
            self._render()

    # ---- exclusions
    def _render_exclusions(self):
        r, table = self._report, self._table
        t = self.excl_table
        reasons = []
        load = r.get("load_excluded") or {}
        at_load = {
            "no_porosity": int(load.get("negative_porosity", 0) + load.get("porosity_out_of_range", 0)),
            "no_perm": int(load.get("nonpositive_perm", 0)),
        }
        for reason, n in r["excluded"].items():
            wells = int(table.loc[table["status"] == reason, "well_key"].nunique())
            reasons.append((reason, n, wells, at_load.get(reason, 0)))
        if r["outliers_z3"]:
            reasons.append(("outlier |z| > 3 (kept)", r["outliers_z3"],
                            len({o["well_key"] for o in r["outlier_rows"]}), 0))
        reasons.append(("valid (used)", r["valid"],
                        int(table.loc[table["status"] == rt.STATUS_OK, "well_key"].nunique()), 0))
        t.setRowCount(len(reasons))
        for i, row in enumerate(reasons):
            for c, val in enumerate(row):
                it = QTableWidgetItem(str(val))
                if c:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                t.setItem(i, c, it)
        t.resizeColumnsToContents()
        self.excl_notes.setText(" ".join(r.get("notes") or []))

    # ---- pay table (active well summary)
    def _render_pay(self):
        summary = getattr(self.model, "summary", None) or {}
        block = summary.get("rock_types") if isinstance(summary, dict) else None
        if not block or not block.get("by_rt"):
            self.pay_group.setVisible(False)
            return
        rows = list(block["by_rt"])
        if block.get("unassigned"):
            rows.append(block["unassigned"])
        t = self.pay_table
        t.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for c, (key, _title) in enumerate(PAY_COLUMNS):
                v = row.get(key)
                text = ("unassigned" if key == "rt" and v == 0 else
                        str(v) if key in ("rt", "samples") else _fmt(v))
                it = QTableWidgetItem(text)
                it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                t.setItem(i, c, it)
        t.resizeColumnsToContents()
        notes = []
        counts = block.get("counts") or {}
        if counts:
            notes.append("Samples: " + ", ".join(f"{k} {v}" for k, v in counts.items()) + ".")
        ag = block.get("agreement") or {}
        if ag.get("n"):
            notes.append(f"Core vs log agreement {100.0 * float(ag['fraction']):.0f} % "
                         f"(n = {ag['n']}).")
        notes.extend(str(n) for n in block.get("notes") or [])
        self.pay_notes.setText(" ".join(notes))
        self.pay_group.setVisible(True)

    # ---- plots
    @staticmethod
    def _log_axes_k(ax):
        ax.set_yscale("log")

    def _scatter_by_rt(self, ax, x, y, labels, n_rt, size=14):
        if n_rt <= 0:
            ax.scatter(x, y, s=size, color=get_plot_color("CORE_PERM"), alpha=0.8)
            return
        colors = rt_colors(n_rt)
        for i in range(1, n_rt + 1):
            sel = labels == i
            if sel.any():
                ax.scatter(np.asarray(x)[sel], np.asarray(y)[sel], s=size, color=colors[i - 1],
                           alpha=0.85, label=f"RT {i}")
        unassigned = labels == 0
        if unassigned.any():
            ax.scatter(np.asarray(x)[unassigned], np.asarray(y)[unassigned], s=size,
                       color=get_plot_color("SW_DEFAULT"), alpha=0.6, label="unassigned")
        ax.legend(fontsize=8, loc="best")

    def _plot_fzi(self, sub, labels, rset, method):
        pw = self.plot_fzi
        if not len(sub):
            pw.clear()
            return
        ax_h, ax_p = pw.get_axes(1, 2)
        x = sub["feature"].to_numpy(float)
        name = "log10 R35 (um)" if method == "r35" else "log10 FZI (um)"
        n = int(rset["n_rt"]) if rset else 0
        bins = np.linspace(x.min(), x.max(), 31) if x.max() > x.min() else 10
        if n:
            colors = rt_colors(n)
            groups = [x[labels == i] for i in range(1, n + 1)]
            ax_h.hist(groups, bins=bins, stacked=True, color=colors, edgecolor="none")
            for b in rset["boundaries"]:
                ax_h.axvline(b, color=get_plot_color("FORMATION_TOP"), linestyle="--", linewidth=1)
        else:
            ax_h.hist(x, bins=bins, color=get_plot_color("DEFAULT_HISTOGRAM"), edgecolor="none")
        ax_h.set_xlabel(name)
        ax_h.set_ylabel("Samples")
        ax_h.set_title("Histogram")
        # Normal-probability plot: breaks in slope hint at populations (Amaefule et al. 1993).
        from scipy.stats import norm
        order = np.argsort(x)
        xs = x[order]
        q = norm.ppf((np.arange(1, len(xs) + 1) - 0.5) / len(xs))
        self._scatter_by_rt(ax_p, xs, q, labels[order] if n else np.zeros(len(xs), dtype=int), n,
                            size=8)
        ax_p.set_xlabel(name)
        ax_p.set_ylabel("Normal quantile")
        ax_p.set_title("Normal probability")
        pw.refresh()

    def _plot_phik(self, sub, labels, rset, n_rt):
        pw = self.plot_phik
        if not len(sub):
            pw.clear()
            return
        ax = pw.get_axes()
        self._scatter_by_rt(ax, sub["phi"].to_numpy(float), sub["k"].to_numpy(float), labels, n_rt)
        phi = np.linspace(max(float(sub["phi"].min()) * 0.8, 0.01),
                          min(float(sub["phi"].max()) * 1.2, 0.5), 60)
        fzis = (rset or {}).get("fzi") or []
        colors = rt_colors(n_rt) if n_rt else []
        for i, f in enumerate(fzis):
            if f is None:
                continue
            ax.plot(phi, rt.perm_from_fzi(float(f), phi), color=colors[i], linewidth=1.2,
                    linestyle="--")
        self._overlay_log(ax)
        ax.set_yscale("log")
        ax.set_xlabel("Core porosity (fraction)")
        ax.set_ylabel("Core permeability (mD)")
        ax.set_title("Porosity vs permeability, iso-FZI curves dashed")
        pw.refresh()

    def _overlay_log(self, ax):
        """Faint log PHIE vs primary permeability of the active well."""
        res = getattr(self.model, "results", None)
        if res is None or "PHIE" not in res.columns:
            return
        col = next((c for c in ("PERM_RT", "PERM_TIMUR", "PERM_WR") if c in res.columns), None)
        if col is None:
            return
        d = res[["PHIE", col]].dropna()
        d = d[(d["PHIE"] > 0) & (d[col] > 0)]
        if not len(d):
            return
        if len(d) > MAX_LOG_POINTS:
            d = d.iloc[np.linspace(0, len(d) - 1, MAX_LOG_POINTS).astype(int)]
        ax.scatter(d["PHIE"], d[col], s=3, color=get_plot_color("SW_DEFAULT"), alpha=0.25,
                   label=f"log {col}", zorder=0)

    def _plot_rqi(self, sub, labels, rset, n_rt):
        pw = self.plot_rqi
        if not len(sub):
            pw.clear()
            return
        ax = pw.get_axes()
        phiz = rt.phi_z(sub["phi"].to_numpy(float))
        rqi = sub["rqi"].to_numpy(float)
        self._scatter_by_rt(ax, phiz, rqi, labels, n_rt)
        pz = np.logspace(np.log10(max(phiz.min() * 0.7, 1e-3)), np.log10(phiz.max() * 1.4), 20)
        colors = rt_colors(n_rt) if n_rt else []
        for i, f in enumerate((rset or {}).get("fzi") or []):
            if f is not None:
                ax.plot(pz, float(f) * pz, color=colors[i], linewidth=1.2, linestyle="--")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("phi_z = phi / (1 - phi)")
        ax.set_ylabel("RQI (um)")
        ax.set_title("RQI vs phi_z, unit-slope lines at each FZI")
        pw.refresh()

    def _plot_r35(self, sub):
        pw = self.plot_r35
        if self._table is None:
            pw.clear()
            return
        ok = self._table[self._table["status"] == rt.STATUS_OK]
        if not len(ok):
            pw.clear()
            return
        ax = pw.get_axes()
        phi, k = ok["phi"].to_numpy(float), ok["k"].to_numpy(float)
        x = np.log10(rt.winland_r35(k, phi))
        lab = np.searchsorted(np.asarray(rt.R35_BOUNDARIES), x) + 1
        colors = rt_colors(len(rt.R35_CLASSES))
        for i, name in enumerate(rt.R35_CLASSES, start=1):
            sel = lab == i
            if sel.any():
                ax.scatter(phi[sel], k[sel], s=14, color=colors[i - 1], alpha=0.85, label=name)
        pg = np.linspace(max(float(phi.min()) * 0.8, 0.01), min(float(phi.max()) * 1.2, 0.5), 60)
        for r35 in ISO_R35_UM:
            kk = 10.0 ** ((np.log10(r35) - 0.732 + 0.864 * np.log10(pg * 100.0)) / 0.588)
            ax.plot(pg, kk, color=get_plot_color("SW_DEFAULT"), linewidth=1, linestyle="--")
            ax.annotate(f"{r35:g} um", (pg[-1], kk[-1]), fontsize=8, ha="right",
                        color=get_plot_color("SW_DEFAULT"))
        ax.set_yscale("log")
        ax.set_xlabel("Core porosity (fraction)")
        ax.set_ylabel("Core permeability (mD)")
        ax.set_title("Winland R35 port classes (sandstone relation)")
        ax.legend(fontsize=8, loc="best")
        pw.refresh()

    def _lorenz_rows(self):
        if self._table is None:
            return None
        ok = self._table[self._table["status"] == rt.STATUS_OK]
        if not len(ok):
            return None
        active = getattr(self.model.active_well, "key", None)
        keys = ok["well_key"].unique().tolist()
        key = str(active) if str(active) in {str(k) for k in keys} else str(keys[0])
        sub = ok[ok["well_key"].astype(str) == key].sort_values("depth")
        return key, sub

    def _plot_lorenz(self):
        pw = self.plot_lorenz
        self.units_view.model().set_dataframe(pd.DataFrame())
        data = self._lorenz_rows()
        if data is None or len(data[1]) < 3:
            pw.clear()
            self.lorenz_label.setText("")
            return
        key, sub = data
        depth = sub["depth"].to_numpy(float)
        phi, k = sub["phi"].to_numpy(float), sub["k"].to_numpy(float)
        h = rt.core_thickness(depth)
        lc = rt.lorenz_coefficient(phi, k, h)
        curve = rt.smlp(depth, phi, k, h)
        ax_l, ax_s = pw.get_axes(1, 2)
        order = np.argsort(-(k / phi), kind="stable")
        c = np.concatenate([[0.0], np.cumsum((phi * h)[order])])
        f = np.concatenate([[0.0], np.cumsum((k * h)[order])])
        if c[-1] > 0 and f[-1] > 0:
            c, f = c / c[-1], f / f[-1]
            ax_l.plot(c, f, color=get_plot_color("CORE_PERM"), linewidth=1.5)
        ax_l.plot([0, 1], [0, 1], color=get_plot_color("SW_DEFAULT"), linewidth=1, linestyle="--")
        ax_l.set_xlabel("Cumulative storage capacity")
        ax_l.set_ylabel("Cumulative flow capacity")
        ax_l.set_title(f"Lorenz, LC = {_fmt(lc, 2)}")
        units = rt.smlp_units(curve) if len(curve) else []
        if len(curve):
            cx = np.concatenate([[0.0], curve["C"].to_numpy(float)])
            cy = np.concatenate([[0.0], curve["F"].to_numpy(float)])
            ax_s.plot(cx, cy, color=get_plot_color("CORE_PERM"), linewidth=1.2)
            ax_s.plot([0, 1], [0, 1], color=get_plot_color("SW_DEFAULT"), linewidth=1,
                      linestyle="--")
            cls_color = {"speed": "NET_RESERVOIR", "barrier": "NET_PAY", "baffle": "NET_PAY"}
            c0 = 0.0
            f0 = 0.0
            for u in units:
                c1, f1 = c0 + u["storage_fraction"], f0 + u["flow_fraction"]
                ax_s.plot([c0, c1], [f0, f1], linewidth=3, alpha=0.8,
                          color=get_plot_color(cls_color.get(u["class"], "GROSS_SAND")))
                c0, f0 = c1, f1
        ax_s.set_xlabel("Cumulative storage capacity (depth order)")
        ax_s.set_ylabel("Cumulative flow capacity")
        ax_s.set_title("SMLP flow units")
        pw.refresh()
        df = pd.DataFrame([{
            "Top": u["top"], "Bottom": u["bottom"], "Thickness": u["thickness"],
            "Storage": u["storage_fraction"], "Flow": u["flow_fraction"], "Slope": u["slope"],
            "Class": u["class"]} for u in units])
        self.units_view.model().set_dataframe(df)
        label = f"Core Lorenz basis: {key}, {len(sub)} samples."
        block = ((getattr(self.model, "summary", None) or {}).get("rock_types") or {})
        lz = block.get("lorenz") if isinstance(block, dict) else None
        if lz and lz.get("coefficient") is not None:
            label += f" Log {lz.get('basis', 'permeability')} Lorenz coefficient {_fmt(lz['coefficient'], 2)}."
        self.lorenz_label.setText(label)

    # -------------------------------------------------------------- actions
    def _on_method_changed(self, *_):
        if self._updating:
            return
        self._sync_method_widgets()
        self._render_banner(self._current())

    def _on_scope_changed(self, *_):
        if self._updating:
            return
        self._render_banner(self._current())

    def _on_set_changed(self, *_):
        if self._updating:
            return
        key = self.set_combo.currentData()
        if key is not None:
            self._set_key = key
            self._render_all(self._current())

    def _on_setting_changed(self, *_):
        """A settings control changed. Display settings update the applied definitions."""
        if self._updating:
            return
        stored = self._stored()
        if stored is not None and self._proposal is None:
            ui = self.settings()
            new = copy.deepcopy(stored)
            for k, v in ui.items():
                if k not in FIT_ONLY:
                    new.setdefault("settings", {})[k] = v
            if new.get("settings") != stored.get("settings"):
                svc.apply_definitions(self.model, new)
                self._last_stored = self._stored()
        self._render()

    def _on_enable_toggled(self, checked: bool):
        if self._updating:
            return
        self.model.rock_typing_enabled = bool(checked)
        self.model.mark_dirty()
        self.model.parameters_changed.emit()
        self._render_enable_hint()

    def _on_fit(self):
        if self._running():
            return
        method = self.method_combo.currentData()
        n_rt = None if method == "r35" else int(self.n_rt_spin.value())
        worker = svc.RockTypingWorker.from_model(
            self.model, self.settings(), method, n_rt, self.scope_combo.currentData())
        worker.setAutoDelete(False)          # the tab owns it until a result signal arrives
        worker.signals.progress.connect(self._on_progress)
        worker.signals.completed.connect(self._on_completed)
        worker.signals.error.connect(self._on_error)
        worker.signals.cancelled.connect(self._on_cancelled)
        self._worker = worker
        self.fit_button.setEnabled(False)
        self.apply_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.n_rt_spin.setEnabled(False)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self._set_status_text("Fitting...", "muted")
        QThreadPool.globalInstance().start(worker)

    def _on_cancel(self):
        if self._worker is not None:
            self._worker.cancel()
            self.cancel_button.setEnabled(False)
            self._set_status_text("Cancelling...", "muted")

    def _on_progress(self, message: str, percent: int):
        self.progress.setValue(int(percent))
        self._set_status_text(message, "muted")

    def _finish_run(self):
        self._worker = None
        self.progress.setVisible(False)
        self.cancel_button.setEnabled(False)
        self._sync_method_widgets()

    def _on_completed(self, proposal: dict):
        self._finish_run()
        self._proposal = proposal
        disp = proposal.get(svc.DISPLAY_KEY) or {}
        sug = (disp.get("suggestion") or {}).get("n_rt")
        self._suggested = sug
        self.suggested_label.setText(f"Suggested: {sug}" if sug else "Suggested: -")
        pooled = proposal["sets"].get(svc.POOLED_KEY) or next(iter(proposal["sets"].values()))
        if proposal["method"] == "fzi":
            self.n_rt_spin.setValue(int(pooled["n_rt"]))
        self._set_key = svc.POOLED_KEY
        text = (f"Proposal: {pooled['n_rt']} rock types from {proposal['fit_report']['valid']} "
                f"core samples. Review it, then Apply to project.")
        fb = proposal["fit_report"].get("fallback") or {}
        if fb:
            text += " Using the pooled set for: " + "; ".join(f"{k} ({v})" for k, v in fb.items()) + "."
        self._render()
        self._set_status_text(text, "success")
        self.fit_finished.emit()

    def _on_error(self, message: str):
        self._finish_run()
        self._render()
        first = message.strip().splitlines()[0] if message.strip() else "Fit failed."
        self._set_status_text(first, "error")
        self.status_label.setToolTip(message)
        self.fit_finished.emit()

    def _on_cancelled(self):
        self._finish_run()
        self._render()
        self._set_status_text("Fit cancelled. Nothing was changed.", "muted")
        self.fit_finished.emit()

    def _on_apply(self):
        if self._proposal is None:
            return
        defs = copy.deepcopy(self._proposal)
        ui = self.settings()
        stored_settings = dict(defs.get("settings") or {})
        for k, v in ui.items():
            if k not in FIT_ONLY:
                stored_settings[k] = v
        defs["settings"] = stored_settings
        svc.apply_definitions(self.model, defs)
        self._last_stored = self._stored()
        self._proposal = None
        self._render()
        self._set_status_text(
            "Applied to the project. Run Analysis (or Run All Wells) to use the rock types.",
            "success")

    # ------------------------------------------------------------ lifecycle
    def refresh_theme(self):
        for plot in (self.plot_fzi, self.plot_phik, self.plot_rqi, self.plot_r35,
                     self.plot_lorenz):
            plot.refresh_theme()
        self._render()

    def reset_ui(self):
        """Reset for New Project: drop the proposal and show the empty state."""
        self._proposal = None
        self._suggested = None
        self._last_stored = None
        self.suggested_label.setText("Suggested: -")
        self._fill_controls(rt.DEFAULT_SETTINGS)
        self.status_label.setToolTip("")
        self.update_display()
