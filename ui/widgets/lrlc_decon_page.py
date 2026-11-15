"""Rt deconvolution page of the Remediation form.

``DeconMixin`` is mixed into ``RemediationForm`` and uses its scratch-copy machinery: the controls
registered here change nothing until Apply. **Propose** runs ``DeconWorker`` (a snapshot of the
well taken on the GUI thread, the solve on a pool thread) with the page's current values and fills
the plot and the tables; it writes nothing. Boundary edits re-run the preview in the worker.
**Use proposal** copies the inputs it ran with and its boundary edits into the pending values, and
the form's one Apply writes them. The page never runs the analysis.
"""

import logging
from typing import List, Optional

from PyQt6.QtCore import QThreadPool, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from modules.lrlc.config import LRLC_PARAM_DEFAULTS, LRLC_RANGES
from modules.lrlc.decon import (
    GENERIC_LABEL,
    GENERIC_RESPONSES,
    MISFIT_AUTO_FACTOR,
    width_sensitivity_text,
)
from services import lrlc_service as svc
from themes.helpers import set_status, set_variant

from .lrlc_common import fmt, make_table, note
from .lrlc_common import item as table_item
from .lrlc_decon_plot import DeconPlot, classify_boundaries
from .fold_section import FoldSection
from .lrlc_diagnosis import lrlc_summary

logger = logging.getLogger(__name__)

SPIN_MAX_WIDTH = 240
COMBO_MAX_WIDTH = 420

DEC_COMBOS = {
    "dec_hires_source": (("auto", "Automatic (HIRES, RXO, RHOB, GR)"), ("HIRES", "HIRES"),
                         ("RXO", "RXO"), ("RHOB", "RHOB"), ("GR", "GR")),
    "dec_tool": (("array_induction_1ft", "Array induction, 1 ft"),
                 ("array_induction_2ft", "Array induction, 2 ft"),
                 ("array_induction_4ft", "Array induction, 4 ft"),
                 ("laterolog_deep_2ft", "Deep laterolog, 2 ft"),
                 ("dual_induction_deep_8ft", "Deep dual induction, 8 ft"),
                 ("custom", "Custom")),
    "dec_response": (("gaussian", "Gaussian"), ("doll", "Doll geometric factor")),
    "dec_solver": (("lsq", "Regularised least squares"), ("mult", "Multiplicative iteration")),
    "dec_output": (("blocky", "Bed values (blocky)"),
                   ("residual", "Bed values with the fit residual")),
}
DEC_LABELS = {
    "dec_hires_source": "Reference curve", "dec_tool": "Tool", "dec_fwhm_ft": "FWHM",
    "dec_response": "Response", "dec_doll_spacing_ft": "Coil spacing",
    "dec_smooth_ft": "Smoothing", "dec_edge_k": "Edge threshold",
    "dec_min_contrast": "Minimum contrast", "dec_min_bed_ft": "Minimum bed",
    "dec_window_ft": "Window", "dec_overlap_ft": "Overlap", "dec_solver": "Solver",
    "dec_lambda": "Lambda", "dec_noise_rel": "Noise", "dec_mult_max_iter": "Iteration cap",
    "dec_output": "Output", "dec_max_ratio": "Largest change", "dec_misfit_warn": "Misfit warning",
    "dec_edits": "Boundary edits", "dec_edit_tol_ft": "Edit tolerance",
}
# (key, label, decimals, step)
DEC_ROWS = (
    ("dec_fwhm_ft", "FWHM (ft)", 2, 0.5),
    ("dec_doll_spacing_ft", "Coil spacing (ft)", 3, 0.5),
    ("dec_smooth_ft", "Smoothing of the reference (ft)", 2, 0.1),
    ("dec_edge_k", "Edge threshold (robust sigmas)", 1, 0.5),
    ("dec_min_contrast", "Minimum contrast across a boundary", 2, 0.01),
    ("dec_window_ft", "Solve window (ft)", 0, 10.0),
    ("dec_overlap_ft", "Window overlap (ft)", 1, 5.0),
    ("dec_noise_rel", "Relative noise of the deep curve", 3, 0.005),
    ("dec_mult_max_iter", "Multiplicative iteration cap", 0, 10.0),
    ("dec_max_ratio", "Largest change from the measured Rt (x)", 1, 1.0),
    ("dec_misfit_warn", "Misfit warning (relative rms)", 2, 0.01),
    ("dec_edit_tol_ft", "Boundary edit tolerance (ft)", 2, 0.25),
)
LATEROLOG_NOTE = "approximate: laterolog response is not linear in conductivity"
SENSITIVITY_TIP = ("The deconvolved Rt depends on the response width. The lines show the median "
                   "increase of the samples the correction raises, solved again at a narrower and "
                   "a wider response. The width presets are generic: confirm the width against "
                   "the tool's charts. Information only.")
SENSITIVITY_INTRO = ("Median Rt increase in the raised beds at three response widths. A large "
                     "spread means the result depends on the width; confirm it against the tool's "
                     "charts.")
ADVANCED_TITLE = "Advanced settings"
ADVANCED_KEYS = ("dec_smooth_ft", "dec_edge_k", "dec_min_contrast", "dec_min_bed_ft",
                 "dec_window_ft", "dec_overlap_ft", "dec_solver", "dec_lambda", "dec_noise_rel",
                 "dec_mult_max_iter", "dec_output", "dec_max_ratio", "dec_misfit_warn",
                 "dec_edit_tol_ft")
NO_REFERENCE = "No high-resolution reference curve: map HIRES or RXO, or RHOB / GR."
LAMINATED_LINK = "Open Laminated sand"
PROPOSE_HINT = "Propose previews the result for this zone; nothing is written."


class AutoSpin(QWidget):
    """A number with an *Automatic* check box: ``get()`` is None while Automatic is ticked."""

    valueChanged = pyqtSignal(float)

    def __init__(self, lo, hi, decimals, step, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.auto = QCheckBox("Automatic")
        self.spin = QDoubleSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setDecimals(decimals)
        self.spin.setSingleStep(step)
        self.spin.setKeyboardTracking(False)
        self.spin.setMaximumWidth(SPIN_MAX_WIDTH)
        row.addWidget(self.auto)
        row.addWidget(self.spin)
        row.addStretch(1)
        self.auto.toggled.connect(self._changed)
        self.spin.valueChanged.connect(self._changed)
        self._changed()

    def _changed(self, *_):
        self.spin.setEnabled(not self.auto.isChecked() and self.isEnabled())
        self.valueChanged.emit(float(self.spin.value()))

    def set(self, value):
        """Show a value (None: Automatic) without emitting."""
        for w in (self.auto, self.spin):
            w.blockSignals(True)
        self.auto.setChecked(value is None)
        if value is not None:
            self.spin.setValue(float(value))
        for w in (self.auto, self.spin):
            w.blockSignals(False)
        self.spin.setEnabled(value is not None and self.isEnabled())

    def get(self):
        return None if self.auto.isChecked() else float(self.spin.value())

    def show_automatic(self, value):
        """While Automatic is ticked, show the value it resolves to (the spin is disabled; the
        stored value stays None). Unticking starts from it."""
        if value is None or not self.auto.isChecked():
            return
        self.spin.blockSignals(True)
        self.spin.setValue(float(value))
        self.spin.blockSignals(False)

    def setEnabled(self, on):  # noqa: N802 - Qt name
        super().setEnabled(on)
        self.spin.setEnabled(bool(on) and not self.auto.isChecked())


def _make_form() -> QFormLayout:
    from .lrlc_remediation import make_form

    return make_form()


def _subheading(text) -> QLabel:
    from .lrlc_remediation import subheading

    return subheading(text)


def _strip(key):
    from .lrlc_remediation import method_strip

    return method_strip(key)


def _side_by_side(left, right) -> QHBoxLayout:
    from .lrlc_remediation import side_by_side

    return side_by_side(left, right)


def sensitivity_text(rec: Optional[dict]) -> str:
    """The response-width line of a zone record (empty when there is nothing to say)."""
    sens = (rec or {}).get("width_sensitivity")
    if not sens or not sens.get("n"):
        return ""
    if len(sens.get("widths_ft") or []) != 3:
        return ""
    return width_sensitivity_text(sens) + "."


class DeconMixin:
    """Builds and refreshes the Rt deconvolution page."""

    # ------------------------------------------------------------------ state
    def _init_decon(self):
        self._dec_token = 0
        self._dec_running = False
        self._dec_proposal: Optional[dict] = None
        self._dec_edits: Optional[dict] = None       # pending boundary edits (None: none)
        self._dec_rows: List[tuple] = []
        self._dec_worker = None
        self._dec_run_inputs = ({}, {"add": [], "remove": []})
        self._dec_ref_cache: dict = {}

    # ------------------------------------------------------------------ build
    def _dec_combo(self, form: QFormLayout, key: str, label: str):
        combo = QComboBox()
        for value, text in DEC_COMBOS[key]:
            combo.addItem(text, value)
        combo.setMaximumWidth(COMBO_MAX_WIDTH)
        self._register(key, combo)
        if form is not None:
            form.addRow(label, combo)
        return combo

    def _dec_auto(self, form: QFormLayout, key, label, decimals, step):
        lo, hi = LRLC_RANGES[key]
        box = AutoSpin(lo, hi, decimals, step)
        self._register(key, box)
        form.addRow(label, box)

    def _build_decon(self, v: QVBoxLayout):
        self._step_check(v, "decon")
        # Actionable notes, one line each, only when they apply.
        ref_row = QHBoxLayout()
        self.dec_ref_warning = note(NO_REFERENCE, "warning")
        ref_row.addWidget(self.dec_ref_warning, 1)
        self.dec_curves_button = QPushButton("Open Screening > Curves")
        set_variant(self.dec_curves_button, "link")
        self.dec_curves_button.clicked.connect(
            lambda: self.panel_requested.emit("screening", "curves"))
        ref_row.addWidget(self.dec_curves_button)
        v.addLayout(ref_row)
        guard_row = QHBoxLayout()
        self.dec_guard_label = note("", "warning")
        guard_row.addWidget(self.dec_guard_label, 1)
        self.dec_lam_button = QPushButton(LAMINATED_LINK)
        set_variant(self.dec_lam_button, "link")
        self.dec_lam_button.clicked.connect(lambda: self.show_section("laminated"))
        guard_row.addWidget(self.dec_lam_button)
        v.addLayout(guard_row)
        self.dec_invasion_note = note("Radial invasion also runs on this zone: medium and "
                                      "shallow stay measured.")
        v.addWidget(self.dec_invasion_note)

        # Main inputs.
        form = _make_form()
        ref = QHBoxLayout()
        self.dec_source_combo = self._dec_combo(None, "dec_hires_source", "")
        ref.addWidget(self.dec_source_combo)
        self.dec_resolved_label = note("")
        ref.addWidget(self.dec_resolved_label, 1)
        form.addRow("Reference curve", ref)
        tool_row = QHBoxLayout()
        self.dec_tool_combo = self._dec_combo(None, "dec_tool", "")
        self.dec_tool_combo.currentIndexChanged.connect(self._on_dec_tool_changed)
        tool_row.addWidget(self.dec_tool_combo)
        self.dec_generic_badge = QLabel("")
        set_status(self.dec_generic_badge, "warning")
        tool_row.addWidget(self.dec_generic_badge)
        tool_row.addStretch(1)
        form.addRow("Tool", tool_row)
        self.dec_laterolog_note = note(LATEROLOG_NOTE)
        form.addRow("", self.dec_laterolog_note)
        self._add_spins(form, tuple((k, lab, d, s, "") for k, lab, d, s in DEC_ROWS
                                    if k == "dec_fwhm_ft"))
        self._dec_combo(form, "dec_response", "Response")
        self._add_spins(form, tuple((k, lab, d, s, "") for k, lab, d, s in DEC_ROWS
                                    if k == "dec_doll_spacing_ft"))
        self._dec_form = form
        v.addLayout(form)

        # Propose and its status.
        row = QHBoxLayout()
        self.dec_propose_button = QPushButton("Propose")
        self.dec_propose_button.setToolTip(PROPOSE_HINT)
        self.dec_propose_button.clicked.connect(self._on_dec_propose)
        row.addWidget(self.dec_propose_button)
        self.dec_status_label = note(PROPOSE_HINT)
        row.addWidget(self.dec_status_label, 1)
        v.addLayout(row)
        self.dec_sensitivity_intro = note(SENSITIVITY_INTRO)
        self.dec_sensitivity_intro.setToolTip(SENSITIVITY_TIP)
        v.addWidget(self.dec_sensitivity_intro)
        self.dec_sensitivity_label = note("")
        self.dec_sensitivity_label.setToolTip(SENSITIVITY_TIP)
        v.addWidget(self.dec_sensitivity_label)
        self.dec_sensitivity_intro.setVisible(False)

        # Boundary editing, tables and the plot.
        left = QVBoxLayout()
        self.dec_edit_box = QWidget()
        edit = QVBoxLayout(self.dec_edit_box)
        edit.setContentsMargins(0, 0, 0, 0)
        modes = QHBoxLayout()
        self.dec_add_button = QPushButton("Add boundary")
        self.dec_add_button.setCheckable(True)
        self.dec_add_button.setToolTip("Click on the reference or the RT track to add a boundary.")
        self.dec_remove_button = QPushButton("Remove boundary")
        self.dec_remove_button.setCheckable(True)
        self.dec_remove_button.setToolTip("Click near a boundary line to remove it.")
        self.dec_add_button.toggled.connect(lambda on: self._on_dec_mode("add", on))
        self.dec_remove_button.toggled.connect(lambda on: self._on_dec_mode("remove", on))
        modes.addWidget(self.dec_add_button)
        modes.addWidget(self.dec_remove_button)
        modes.addStretch(1)
        edit.addLayout(modes)
        self.dec_boundary_table = make_table(("Depth (ft)", "Origin", "Bed below (ft)",
                                              "Rt before", "Rt after", "At bound"))
        self.dec_boundary_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.dec_boundary_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.dec_boundary_table.setMaximumHeight(220)
        self.dec_boundary_table.itemSelectionChanged.connect(self._state_decon)
        edit.addWidget(self.dec_boundary_table)
        acts = QHBoxLayout()
        self.dec_delete_button = QPushButton("Delete boundary")
        self.dec_delete_button.clicked.connect(self._on_dec_delete)
        self.dec_reset_button = QPushButton("Reset edits")
        self.dec_reset_button.clicked.connect(self._on_dec_reset)
        acts.addWidget(self.dec_delete_button)
        acts.addWidget(self.dec_reset_button)
        acts.addStretch(1)
        edit.addLayout(acts)
        self.dec_edits_label = note("")
        edit.addWidget(self.dec_edits_label)
        use = QHBoxLayout()
        self.dec_use_button = QPushButton("Use proposal")
        self.dec_use_button.setToolTip("Copy the inputs and boundary edits of the proposal into "
                                       "the settings of this page. Apply writes them.")
        self.dec_use_button.clicked.connect(self._on_dec_use)
        use.addWidget(self.dec_use_button)
        use.addStretch(1)
        edit.addLayout(use)
        left.addWidget(self.dec_edit_box)
        self.dec_window_table = make_table(("Window (ft)", "Beds", "Lambda", "Misfit rms",
                                            "Status"))
        left.addWidget(self.dec_window_table)
        self.dec_counts_label = note("")
        left.addWidget(self.dec_counts_label)
        left.addStretch(1)
        self.dec_plot = DeconPlot()
        self.dec_plot.boundary_clicked.connect(self._on_dec_click)
        self.dec_plot.setVisible(False)
        v.addLayout(_side_by_side(left, self.dec_plot))

        # Advanced.
        self.dec_advanced = FoldSection(ADVANCED_TITLE)
        v.addWidget(self.dec_advanced)
        adv = _make_form()
        keys = ("dec_smooth_ft", "dec_edge_k", "dec_min_contrast")
        self._add_spins(adv, tuple((k, lab, d, s, "") for k, lab, d, s in DEC_ROWS if k in keys))
        self._dec_auto(adv, "dec_min_bed_ft", "Minimum bed (ft)", 2, 0.25)
        self._add_spins(adv, tuple((k, lab, d, s, "") for k, lab, d, s in DEC_ROWS
                                   if k in ("dec_window_ft", "dec_overlap_ft")))
        self._dec_combo(adv, "dec_solver", "Solver")
        self._dec_auto(adv, "dec_lambda", "Lambda", 6, 0.001)
        self._add_spins(adv, tuple((k, lab, d, s, "") for k, lab, d, s in DEC_ROWS
                                   if k in ("dec_noise_rel", "dec_mult_max_iter")))
        self._dec_combo(adv, "dec_output", "Output")
        self._add_spins(adv, tuple((k, lab, d, s, "") for k, lab, d, s in DEC_ROWS
                                   if k in ("dec_max_ratio", "dec_edit_tol_ft")))
        self._dec_auto(adv, "dec_misfit_warn", "Misfit warning (relative rms)", 2, 0.01)
        self.dec_advanced.body_layout.addLayout(adv)
        self.dec_box = _strip("decon")
        v.addWidget(self.dec_box)
        self._reset_decon()

    def _reset_decon(self):
        """Forget the proposal (a new well or zone, a discarded page)."""
        self._dec_token += 1
        self._dec_running = False
        self._dec_proposal = None
        self._dec_rows = []
        self.dec_plot.clear_data("Propose to see the result")
        self.dec_plot.setVisible(False)
        for button in (self.dec_add_button, self.dec_remove_button):
            was = button.blockSignals(True)
            button.setChecked(False)
            button.blockSignals(was)
        self.dec_plot.set_mode("none")
        self.dec_boundary_table.setRowCount(0)
        self.dec_status_label.setText(PROPOSE_HINT)
        set_status(self.dec_status_label, "muted")

    # ---------------------------------------------------------------- helpers
    def _dec_resolved_stored(self) -> dict:
        return self._resolved_now()

    def _dec_stored_edits(self) -> dict:
        edits = self._dec_resolved_stored().get("dec_edits") or {}
        return {"add": [float(x) for x in edits.get("add", [])],
                "remove": [float(x) for x in edits.get("remove", [])]}

    def _dec_page_edits(self) -> dict:
        """The boundary edits the page holds: the pending ones, else the stored ones."""
        if self._dec_edits is not None:
            return {"add": list(self._dec_edits["add"]), "remove": list(self._dec_edits["remove"])}
        return self._dec_stored_edits()

    @staticmethod
    def _norm_edits(edits: dict) -> dict:
        return {"add": sorted(round(float(x), 3) for x in edits.get("add", [])),
                "remove": sorted(round(float(x), 3) for x in edits.get("remove", []))}

    def _dec_values(self) -> dict:
        return {key: self._read_widget(key) for key in self.controls if key.startswith("dec_")}

    def _dec_edit_state_text(self) -> str:
        edits = self._dec_proposal["edits"] if self._dec_proposal else self._dec_page_edits()
        return (f"Boundary edits: {len(edits['add'])} added, {len(edits['remove'])} removed.")

    # ------------------------------------------------------------- the proposal
    def _on_dec_propose(self):
        self._start_decon(self._dec_page_edits())

    def _start_decon(self, edits: dict, values: Optional[dict] = None):
        """Run the worker with the page's values (or the given ones: a preview after a boundary
        edit keeps the inputs of the proposal it belongs to)."""
        if self.model is None or self.ds is None or self._dec_running:
            return
        values = dict(values) if values is not None else self._dec_values()
        self._dec_token += 1
        token = self._dec_token
        try:
            worker = svc.DeconWorker.from_model(self.model, self.ds, self.zone, values, edits,
                                                token)
        except Exception as e:      # noqa: BLE001 - the page reports it, nothing was started
            logger.exception("Rt deconvolution snapshot failed")
            self._dec_failed(f"The proposal could not start: {e}")
            return
        if worker is None:
            self._dec_failed("The well has no log data to deconvolve.")
            return
        self._dec_run_inputs = (values, {"add": list(edits["add"]), "remove": list(edits["remove"])})
        worker.signals.completed.connect(self._on_dec_done)
        worker.signals.error.connect(self._on_dec_error)
        self._dec_worker = worker
        self._dec_running = True
        self.dec_status_label.setText("Running the proposal...")
        set_status(self.dec_status_label, "muted")
        self._state_decon()
        QThreadPool.globalInstance().start(worker)

    def _dec_failed(self, text: str):
        self._dec_running = False
        self.dec_status_label.setText(text)
        set_status(self.dec_status_label, "warning")
        self._state_decon()

    def _on_dec_error(self, token: int, text: str):
        if token != self._dec_token:
            return
        self._dec_failed(text)

    def _on_dec_done(self, token: int, payload: dict):
        if token != self._dec_token:
            return          # a newer request or another well: this result is stale
        values, edits = self._dec_run_inputs
        payload["values"] = dict(values)
        payload["edits"] = {"add": list(edits["add"]), "remove": list(edits["remove"])}
        self._dec_running = False
        self._dec_proposal = payload
        self._dec_worker = None
        self._show_dec_proposal()
        self._refresh_info()
        self._update_state()
        self.decon_proposed.emit()

    def _show_dec_proposal(self):
        prop = self._dec_proposal
        block = prop.get("block") if prop else None
        plot = prop.get("plot") if prop else None
        if not block or not plot:
            kind = (prop or {}).get("reference", {}).get("curve")
            issues = [i["text"] for i in (prop or {}).get("issues", [])
                      if i["code"] in ("LRLC_DECON_NO_HIRES", "LRLC_DECON_NO_RT",
                                       "LRLC_DECON_UNDERSAMPLED")]
            self.dec_status_label.setText(
                issues[0] if issues else ("Nothing to deconvolve in this zone."
                                          if kind else NO_REFERENCE))
            set_status(self.dec_status_label, "warning")
            self.dec_plot.clear_data("No proposal")
            self.dec_plot.setVisible(False)
            return
        rec = self._dec_zone_records(block)
        n_valid = sum(r.get("n_valid", 0) for r in rec)
        n_active = sum(r.get("n_active", 0) for r in rec)
        warnings = [i["text"] for i in prop["issues"] if i.get("severity") == "warning"]
        text = (f"Proposal: {block['n_beds']} beds, {len(plot['final'])} boundaries, reference "
                f"{(block['hires'].get('column') or block['hires'].get('curve') or '')}; "
                f"{n_valid} of {n_active} samples valid.")
        if warnings:
            text += " " + warnings[0]
        self.dec_status_label.setText(text)
        set_status(self.dec_status_label, "warning" if warnings else "success")
        self._draw_dec_plot()

    def _draw_dec_plot(self):
        prop = self._dec_proposal
        plot = prop.get("plot") if prop else None
        if not plot:
            return
        self.dec_plot.setVisible(True)
        self.dec_plot.set_data(plot, prop["edits"], plot.get("tol", 1.0))

    # ----------------------------------------------------------- boundary edits
    def _dec_tol(self) -> float:
        plot = (self._dec_proposal or {}).get("plot") or {}
        return float(plot.get("tol", 1.0))

    def _dec_classified(self):
        prop = self._dec_proposal
        plot = prop.get("plot") if prop else None
        if not plot:
            return []
        return classify_boundaries(plot["auto"], plot["final"], prop["edits"], self._dec_tol())

    def add_boundary(self, depth: float) -> bool:
        """Add a bed boundary at ``depth`` to the proposal's edits and re-run the preview;
        a removed boundary near ``depth`` is restored instead. False when nothing changed."""
        prop = self._dec_proposal
        if prop is None or self._dec_running or not prop.get("plot"):
            return False
        tol = self._dec_tol()
        edits = {"add": list(prop["edits"]["add"]), "remove": list(prop["edits"]["remove"])}
        near = [x for x in edits["remove"] if abs(x - depth) <= tol]
        if near:
            edits["remove"] = [x for x in edits["remove"] if x not in near]
        elif any(abs(x - depth) <= tol for x, o in self._dec_classified() if o != "removed"):
            return False
        else:
            edits["add"].append(round(float(depth), 2))
        self._start_decon(edits, prop["values"])
        return True

    def remove_boundary(self, depth: float) -> bool:
        """Remove the boundary nearest to ``depth`` (an added one leaves the add list, an
        automatic one joins the remove list) and re-run the preview."""
        prop = self._dec_proposal
        if prop is None or self._dec_running or not prop.get("plot"):
            return False
        rows = [r for r in self._dec_classified() if r[1] != "removed"]
        if not rows:
            return False
        x, origin = min(rows, key=lambda r: abs(r[0] - depth))
        tol = self._dec_tol()
        edits = {"add": list(prop["edits"]["add"]), "remove": list(prop["edits"]["remove"])}
        if origin == "added":
            added = [a for a in edits["add"] if abs(a - x) <= tol]
            if not added:
                return False
            edits["add"].remove(min(added, key=lambda a: abs(a - x)))
        else:
            edits["remove"].append(round(float(x), 2))
        self._start_decon(edits, prop["values"])
        return True

    def restore_boundary(self, depth: float) -> bool:
        """Undo the removal of the boundary near ``depth`` and re-run the preview."""
        prop = self._dec_proposal
        if prop is None or self._dec_running:
            return False
        tol = self._dec_tol()
        near = [x for x in prop["edits"]["remove"] if abs(x - depth) <= tol]
        if not near:
            return False
        edits = {"add": list(prop["edits"]["add"]),
                 "remove": [x for x in prop["edits"]["remove"] if x not in near]}
        self._start_decon(edits, prop["values"])
        return True

    def reset_boundary_edits(self) -> bool:
        """Clear the proposal's boundary edits and re-run the preview."""
        prop = self._dec_proposal
        if prop is None or self._dec_running:
            return False
        self._start_decon({"add": [], "remove": []}, prop["values"])
        return True

    def _on_dec_mode(self, mode: str, on: bool):
        other = self.dec_remove_button if mode == "add" else self.dec_add_button
        if on:
            was = other.blockSignals(True)
            other.setChecked(False)
            other.blockSignals(was)
            self.dec_plot.set_mode(mode)
        elif not other.isChecked():
            self.dec_plot.set_mode("none")

    def _on_dec_click(self, mode: str, depth: float):
        if mode == "add":
            self.add_boundary(depth)
        elif mode == "remove":
            self.remove_boundary(depth)

    def _selected_dec_row(self):
        rows = self.dec_boundary_table.selectionModel().selectedRows() if \
            self.dec_boundary_table.selectionModel() else []
        if not rows:
            return None
        i = rows[0].row()
        return self._dec_rows[i] if 0 <= i < len(self._dec_rows) else None

    def _on_dec_delete(self):
        row = self._selected_dec_row()
        if row is None:
            return
        depth, origin = row
        if origin == "removed":
            self.restore_boundary(depth)
        else:
            self.remove_boundary(depth)

    def _on_dec_reset(self):
        self.reset_boundary_edits()

    def _on_dec_use(self):
        """Copy the proposal's inputs and boundary edits into the pending values."""
        prop = self._dec_proposal
        if prop is None:
            return
        for key, value in (prop.get("values") or {}).items():
            if key in self.controls and self._read_widget(key) != value:
                self._set_value(key, value)
        edits = prop["edits"]
        if self._norm_edits(edits) != self._norm_edits(self._dec_stored_edits()):
            self._dec_edits = {"add": list(edits["add"]), "remove": list(edits["remove"])}
        else:
            self._dec_edits = None
        self._refresh_info()
        self._update_state()

    # ----------------------------------------------------------- controls state
    def _on_dec_tool_changed(self, *_):
        if self._loading:
            return
        key = self.controls["dec_tool"].currentData()
        preset = GENERIC_RESPONSES.get(key)
        was = self._loading
        self._loading = True
        try:
            if key != "custom" and preset is not None:
                self._write_widget("dec_fwhm_ft", self.controls["dec_fwhm_ft"], preset["fwhm_ft"])
                self._write_widget("dec_response", self.controls["dec_response"], "gaussian")
        finally:
            self._loading = was
        resolved = self._resolved_now()
        for k in ("dec_fwhm_ft", "dec_response"):
            if self._read_widget(k) != resolved.get(k):
                self._dirty.add(k)
            else:
                self._dirty.discard(k)
        self._refresh_info()
        self._update_state()

    def _dec_guard(self):
        """``(text, link, blocked, check_locked)`` of the guard for this zone, from the guard and
        mark switches as the page shows them (pending values count)."""
        if self.ds is None:
            return "", False, False, False
        enabled = self.guard_check.isChecked()
        marked = self.sbc_check.isChecked() and self.sbc_check.isEnabled()
        guard = lrlc_summary(self.ds).get("guard") or {}
        names = [z.get("zone") for z in guard.get("zones", [])
                 if z.get("laminated") and (self.zone is None or z.get("zone") == self.zone)]
        lines = []
        if names:
            where = ", ".join(f"Zone {n}" if n else "the unzoned interval" for n in names)
            if enabled:
                lines.append(f"{where} was laminated in the last run: with the shoulder-bed guard "
                             "on, Deconvolution is not applied there. If the laminations are thinner "
                             "than the reference curve resolves, use the laminated-sand "
                             "correction; if the reference curve resolves the beds, switch the "
                             "guard off on the Overview page.")
            else:
                lines.append(f"{where} was laminated in the last run: with the guard off, "
                             "Deconvolution is applied there and can correct the thin beds twice.")
        if marked and (self.zone is None or not names):
            if enabled:
                lines.append("The mapped RT is marked shoulder-bed corrected: with the guard on, "
                             "Deconvolution is not applied. Remove the mark on the Overview page "
                             "or switch the guard off.")
            else:
                lines.append("The mapped RT is marked shoulder-bed corrected: Deconvolution on a "
                             "corrected curve corrects the thin beds twice (guard off).")
        blocked = enabled and (bool(names) or marked)
        return " ".join(lines), bool(names), blocked, enabled and marked

    def _dec_row_state(self, steps) -> str:
        if "decon" not in steps:
            return "off"
        return "blocked" if self._dec_guard()[2] else "on"

    def _state_decon(self, *_):
        tool = self._read_widget("dec_tool")
        custom = tool == "custom"
        self.controls["dec_fwhm_ft"].setEnabled(custom and self._read_widget("dec_response")
                                                == "gaussian")
        self.controls["dec_response"].setEnabled(custom)
        doll = self._read_widget("dec_response") == "doll"
        spacing = self.controls["dec_doll_spacing_ft"]
        spacing.setVisible(doll)
        label = self._dec_form.labelForField(spacing)
        if label is not None:
            label.setVisible(doll)
        if not custom:
            badge = GENERIC_LABEL
        elif doll:
            badge = ""
        else:
            badge = f"FWHM {self._read_widget('dec_fwhm_ft'):.1f} ft"
        self.dec_generic_badge.setText(badge)
        self.dec_generic_badge.setVisible(bool(badge))
        set_status(self.dec_generic_badge, "warning" if not custom else "muted")
        self.dec_laterolog_note.setVisible(tool.startswith("laterolog"))
        solver = self._read_widget("dec_solver")
        self.controls["dec_lambda"].setEnabled(solver == "lsq")
        self.controls["dec_mult_max_iter"].setEnabled(solver == "mult")
        noise = self._read_widget("dec_noise_rel")
        self.controls["dec_misfit_warn"].show_automatic(MISFIT_AUTO_FACTOR * float(noise))
        have = self._dec_proposal is not None and bool(self._dec_proposal.get("plot"))
        self.dec_edit_box.setVisible(have)
        row = self._selected_dec_row()
        self.dec_delete_button.setEnabled(have and row is not None and not self._dec_running)
        self.dec_delete_button.setText("Restore boundary" if row and row[1] == "removed"
                                       else "Delete boundary")
        self.dec_reset_button.setEnabled(have and not self._dec_running)
        self.dec_use_button.setEnabled(have and not self._dec_running)
        self.dec_add_button.setEnabled(have and not self._dec_running)
        self.dec_remove_button.setEnabled(have and not self._dec_running)
        reference = bool(self._dec_reference()[0])
        mapped = self.ds is not None and self._dec_has_rt()
        self.dec_propose_button.setEnabled(bool(self.model is not None and self.ds is not None
                                                and reference and mapped
                                                and not self._dec_running))

    def _dec_has_rt(self) -> bool:
        log = getattr(self.ds, "las_data", None)
        name = (getattr(self.ds, "curve_mapping", None) or {}).get("RT")
        return log is not None and bool(name) and name in log.columns

    def _dec_reference(self):
        if self.ds is None:
            return None, None
        source = self._read_widget("dec_hires_source")
        key = (id(self.ds), id(getattr(self.ds, "las_data", None)), source,
               tuple(sorted((getattr(self.ds, "lrlc_curves", None) or {}).items())))
        if key not in self._dec_ref_cache:
            self._dec_ref_cache = {key: svc.decon_reference(self.ds, source)}
        return self._dec_ref_cache[key]

    # -------------------------------------------------------------- info texts
    def _dec_zone_range(self):
        res = getattr(self.ds, "results", None) if self.ds is not None else None
        if self.zone is None or res is None or "ZONE" not in res.columns or "DEPTH" not in res.columns:
            return None
        sel = res["ZONE"].fillna("").astype(str).to_numpy() == self.zone
        depth = res["DEPTH"].to_numpy(dtype=float)[sel]
        return (float(depth.min()), float(depth.max())) if depth.size else None

    def _dec_zone_records(self, block) -> List[dict]:
        records = [r for r in (block or {}).get("zones", []) if isinstance(r, dict)]
        if self.zone is not None:
            records = [r for r in records if r.get("zone") == self.zone]
        return records

    def _dec_last_block(self):
        lrlc = (getattr(self.ds, "summary", None) or {}).get("lrlc") or {} if self.ds else {}
        block = lrlc.get("decon")
        return block if isinstance(block, dict) else None

    def _info_decon(self):
        kind, column = self._dec_reference()
        source = self._read_widget("dec_hires_source")
        have_data = self.ds is not None and getattr(self.ds, "las_data", None) is not None
        self.dec_resolved_label.setText(f"Using {column}" if column else
                                        ("Not available" if have_data else ""))
        warn = have_data and kind is None
        self.dec_ref_warning.setVisible(warn)
        self.dec_curves_button.setVisible(warn)
        self.dec_ref_warning.setText(
            NO_REFERENCE if source == "auto" else
            f"No high-resolution reference curve: {source} is not available (map HIRES or RXO, "
            "or RHOB / GR).")
        text, link, blocked, locked = self._dec_guard()
        self.dec_guard_label.setText(text)
        self.dec_guard_label.setVisible(bool(text))
        self.dec_lam_button.setVisible(link)
        check = self.step_checks["decon"]
        check.setEnabled(not locked or check.isChecked())
        check.setToolTip("Blocked by the shoulder-bed guard: the mapped RT is marked shoulder-bed "
                         "corrected." if locked and not check.isChecked() else "")
        steps = self._displayed_steps()
        self.dec_invasion_note.setVisible("invasion" in steps)

        prop = self._dec_proposal
        block = prop["block"] if prop and prop.get("block") else self._dec_last_block()
        from_run = not (prop and prop.get("block"))
        records = self._dec_zone_records(block)
        dropped = [r for r in records if str(r.get("status", "")).startswith("guard_dropped")]
        lines = []
        if from_run:
            records = [r for r in records if r not in dropped]
        for rec in records:
            line = sensitivity_text(rec)
            if line:
                named = self.zone is None and rec.get("zone") not in (None, "", "WELL")
                lines.append(f"{rec.get('zone')}: {line}" if named else line)
        self.dec_sensitivity_label.setText("\n".join(lines))
        self.dec_sensitivity_label.setVisible(bool(lines))
        self.dec_sensitivity_intro.setVisible(bool(lines))
        if from_run and block and self._dec_proposal is None:
            if dropped and not records:
                why = "RT is marked shoulder-bed corrected" if any(
                    r["status"] == "guard_dropped_shoulder" for r in dropped) else "laminated"
                self.dec_status_label.setText(f"Last run: Deconvolution was not applied ({why}).")
                set_status(self.dec_status_label, "warning")
            elif records and not self._dec_running:
                valid = sum(r.get("n_valid", 0) for r in records)
                active = sum(r.get("n_active", 0) for r in records)
                self.dec_status_label.setText(
                    f"Last run: {valid} of {active} samples valid. {PROPOSE_HINT}")
                set_status(self.dec_status_label, "muted")
        if from_run and dropped and not records:
            block = None            # a zone the guard dropped has no result to show
        self._fill_dec_tables(block, from_run)
        self.dec_edits_label.setText(self._dec_edit_state_text())
        changed = self._dec_advanced_changed()
        self.dec_advanced.set_changed_count(changed)
        if changed:
            self.dec_advanced.set_expanded(True)

    def _dec_advanced_changed(self) -> int:
        """How many Advanced values (pending, else resolved for the zone) differ from the
        defaults."""
        n = 0
        for key in ADVANCED_KEYS:
            if key not in self.controls:
                continue
            value, default = self._read_widget(key), LRLC_PARAM_DEFAULTS[key]
            if value is None or default is None:
                n += value is not default
            elif isinstance(default, str):
                n += value != default
            else:
                n += abs(float(value) - float(default)) > 1e-9
        return int(n)

    def _fill_dec_tables(self, block, from_run: bool):
        # window table and counts
        table = self.dec_window_table
        table.setRowCount(0)
        rng = self._dec_zone_range()
        windows = [w for w in (block or {}).get("windows", [])
                   if rng is None or (w["bottom"] >= rng[0] and w["top"] <= rng[1])]
        for w in windows:
            r = table.rowCount()
            table.insertRow(r)
            cells = [f"{w['top']:.1f} - {w['bottom']:.1f}", w["n_beds"], f"{w['lam']:.2g}",
                     fmt(w["misfit_rms"], 3), w["status"]]
            for c, text in enumerate(cells):
                table.setItem(r, c, table_item(text, c in (1, 2, 3)))
        table.setVisible(bool(windows))
        rows_h = sum(table.rowHeight(r) for r in range(table.rowCount()))
        table.setFixedHeight(min(170, table.horizontalHeader().height() + rows_h
                                 + 2 * table.frameWidth() + 4))
        counts = (block or {}).get("counts") or {}
        if block:
            self.dec_counts_label.setText(
                "Counts: " + ", ".join(
                    f"{label} {int(counts.get(key, 0))}" for key, label in (
                        ("amplified", "amplified"), ("edge", "edge"),
                        ("boundaries_merged", "merged"), ("not_converged", "not converged"))) + ".")
        else:
            self.dec_counts_label.setText("")
        self.dec_counts_label.setVisible(bool(block))
        # boundary table (proposal only)
        bt = self.dec_boundary_table
        keep = self._selected_dec_row()
        bt.setRowCount(0)
        self._dec_rows = []
        prop = self._dec_proposal
        plot = prop.get("plot") if prop else None
        if not plot:
            return
        tol = self._dec_tol()
        beds = plot["beds"]
        self._dec_rows = classify_boundaries(plot["auto"], plot["final"], prop["edits"], tol)
        for depth, origin in self._dec_rows:
            r = bt.rowCount()
            bt.insertRow(r)
            bed = next((b for b in beds if abs(b["top"] - depth) <= 0.25), None) \
                if origin != "removed" else None
            cells = [f"{depth:.2f}", origin,
                     fmt(bed["bottom"] - bed["top"], 2) if bed else "",
                     fmt(bed["rt_prior"], 2) if bed else "", fmt(bed["rt_decon"], 2) if bed else "",
                     ("yes" if bed["at_bound"] else "") if bed else ""]
            for c, text in enumerate(cells):
                bt.setItem(r, c, table_item(text, c >= 2))
            if origin == "removed":
                for c in range(bt.columnCount()):
                    bt.item(r, c).setForeground(self.palette().placeholderText())
        if keep is not None and keep in self._dec_rows:
            bt.selectRow(self._dec_rows.index(keep))

    def refresh_decon_theme(self):
        self.dec_plot.refresh_theme()
        self.dec_advanced.refresh_theme()
        self.dec_box.refresh_theme()
