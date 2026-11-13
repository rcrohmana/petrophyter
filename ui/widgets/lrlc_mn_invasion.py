"""Variable m/n and Radial invasion sections of the Remediation form.

``MnInvasionMixin`` is mixed into ``RemediationForm`` and uses its scratch-copy machinery: the
controls registered here change nothing until Apply. The m fit is a proposal; **Use fit** copies
it into the pending values (curve mode, the formula model, the coefficients and the porosity),
which the form's one Apply writes. The invasion plots read the last run; nothing here runs the
analysis.
"""

import logging
from typing import Any, Dict, List, Optional

import numpy as np
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
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

from modules.lrlc.config import INV_R50_KEYS, INV_R50_RANGE, LRLC_LISTS, LRLC_RANGES
from modules.lrlc.invasion import GENERIC_LABEL, GENERIC_TOOLS, resolve_tool
from modules.las_parser import mud_header_proposal
from modules.lrlc.variable_mn import SHELL_PRESET
from services import lrlc_service as svc
from themes.helpers import set_status, set_variant

from .lrlc_common import fmt, make_table, note
from .lrlc_common import item as table_item
from .lrlc_invasion_plot import InvasionProfilePlot, TornadoPlot
from .lrlc_mn_plot import MnFitPlot

SPIN_MAX_WIDTH = 240
COMBO_MAX_WIDTH = 420
PLOT_MIN_WIDTH = 320
MULTI_SPIN_WIDTH = 84

logger = logging.getLogger(__name__)

NEW_SECTIONS = ("variable_mn", "invasion")

MN_COMBOS = {
    "mn_mode": (("scalar", "Scalar (one m and one n per zone)"),
                ("curve", "Curve (m and n per sample)")),
    "m_model": (("formula", "Formula c0 + c1 PHI + c2 Vsh + c3 / PHI"),
                ("shell", "Shell 1.87 + 0.019 / PHI (carbonates)")),
    "n_model": (("constant", "Constant n of the zone"), ("vsh", "n = d0 + d1 Vsh")),
    "phi_source": (("phie", "Effective porosity (PHIE)"), ("phit", "Total porosity (PHIT)")),
    "inv_tool": (("generic_induction", "Generic induction"),
                 ("generic_laterolog", "Generic laterolog"), ("custom", "Custom radii")),
    "inv_rxo_mode": (("fixed", "Use RXO as the flushed-zone resistivity"),
                     ("ignore", "Ignore RXO")),
}
NEW_LABELS = {
    "mn_mode": "Mode", "m_model": "m model", "m_coef": "m coefficients", "n_model": "n model",
    "n_coef": "n coefficients", "phi_source": "Porosity", "shell_confirm": "Shell confirmed",
    "inv_tool": "Tool", "inv_r50": "Investigation diameters", "inv_p": "Shape exponent",
    "inv_rxo_mode": "RXO use", "inv_di_min": "Smallest diameter",
    "inv_di_max": "Largest diameter", "inv_min_contrast": "Minimum contrast",
    "inv_max_rms": "Maximum rms", "rmf": "Rmf", "rmf_temp": "Rmf temperature",
}
# (key, label, decimals, step, text shown when the value is None)
INVASION_ROWS = (
    ("inv_p", "Shape exponent p", 2, 0.1, ""),
    ("inv_di_min", "Smallest diameter (in)", 1, 1.0, ""),
    ("inv_di_max", "Largest diameter (in)", 1, 5.0, ""),
    ("inv_min_contrast", "Minimum curve contrast", 2, 0.05, ""),
    ("inv_max_rms", "Maximum rms of the fit (ln)", 2, 0.05, ""),
    ("rmf", "Rmf (ohm.m)", 4, 0.05, "not set"),
    ("rmf_temp", "Rmf temperature (degF)", 1, 5.0, ""),
)
MN_COEF_LABELS = ("c0", "c1 (PHI)", "c2 (Vsh)", "c3 (1/PHI)")
N_COEF_LABELS = ("d0", "d1 (Vsh)")
COUNT_COLUMNS = ("Zone", "Tool", "Valid", "Fitted", "Non-unique", "Diameter at lower bound",
                 "Diameter at upper bound", "Poor fit", "Failed", "Missing curves",
                 "RT_INV / RT median", "DI_INV median (in)")
COUNT_KEYS = ("n_valid", "n_ok", "n_nonunique", "n_di_lower", "n_di_upper", "n_poor_fit",
              "n_failed", "n_missing")


class MultiSpin(QWidget):
    """A row of small spin boxes that edits one list (or one named-value dict) setting."""

    valueChanged = pyqtSignal(float)

    def __init__(self, labels, lo_hi, decimals=3, step=0.05, as_dict: bool = False, parent=None):
        super().__init__(parent)
        self.labels = tuple(labels)
        self.as_dict = as_dict
        self.spins: List[QDoubleSpinBox] = []
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        bounds = lo_hi if isinstance(lo_hi[0], (tuple, list)) else [lo_hi] * len(self.labels)
        for label, (lo, hi) in zip(self.labels, bounds):
            col = QVBoxLayout()
            col.addWidget(QLabel(label))
            spin = QDoubleSpinBox()
            spin.setRange(lo, hi)
            spin.setDecimals(decimals)
            spin.setSingleStep(step)
            spin.setKeyboardTracking(False)
            spin.setMaximumWidth(MULTI_SPIN_WIDTH)
            spin.valueChanged.connect(lambda v: self.valueChanged.emit(float(v)))
            col.addWidget(spin)
            row.addLayout(col)
            self.spins.append(spin)
        row.addStretch(1)
        self.setMaximumWidth((MULTI_SPIN_WIDTH + 12) * len(self.labels))

    def set(self, value):
        """Write a list (or dict) of values without emitting."""
        if isinstance(value, dict):
            value = [value.get(k) for k in INV_R50_KEYS]
        for spin, v in zip(self.spins, value or []):
            if v is None:
                continue
            was = spin.blockSignals(True)
            spin.setValue(float(v))
            spin.blockSignals(was)

    def get(self):
        values = [float(s.value()) for s in self.spins]
        if self.as_dict:
            return dict(zip(INV_R50_KEYS, values))
        return values


def parse_header_mud(info) -> Optional[Dict[str, Any]]:
    """``{"rmf", "rmf_temp" (degF or None), "note"}`` from the LAS header values, or None.

    A thin wrapper over ``mud_header_proposal``: the proposal is empty (None here) when the
    header gives no usable Rmf; the note says which values were assumed or left out.
    """
    if not isinstance(info, dict):
        return None
    prop = mud_header_proposal(info)
    if "rmf" not in prop:
        return None
    notes = []
    if "rmf" in prop["assumed"]:
        notes.append("Rmf unit not stated, taken as ohm.m")
    if "rmf_temp" in prop["assumed"]:
        notes.append("temperature unit not stated, taken as degF")
    if "rmf_temp" in prop["skipped"]:
        notes.append(f"temperature not offered: {prop['skipped']['rmf_temp']}")
    return {"rmf": prop["rmf"], "rmf_temp": prop.get("rmf_temp"), "note": "; ".join(notes)}


def _make_form() -> QFormLayout:
    from .lrlc_remediation import make_form

    return make_form()


def _heading(text) -> QLabel:
    from .lrlc_remediation import heading

    return heading(text)


def _subheading(text) -> QLabel:
    from .lrlc_remediation import subheading

    return subheading(text)


def _strip(key):
    from .lrlc_remediation import method_strip

    return method_strip(key)


def _side_by_side(left, right) -> QHBoxLayout:
    from .lrlc_remediation import side_by_side

    return side_by_side(left, right)


class MnInvasionMixin:
    """Builds and refreshes the Variable m/n and Radial invasion sections."""

    # ------------------------------------------------------------------ helpers
    def _add_combo(self, form: QFormLayout, key: str, label: str):
        combo = QComboBox()
        for value, text in MN_COMBOS[key]:
            combo.addItem(text, value)
        combo.setMaximumWidth(COMBO_MAX_WIDTH)
        self._register(key, combo)
        form.addRow(label, combo)
        return combo

    def _add_spins(self, form: QFormLayout, rows):
        for key, label, decimals, step, none_text in rows:
            lo, hi = LRLC_RANGES[key]
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
            self._register(key, spin)
            form.addRow(label, spin)

    def _display_value(self, key: str, resolved: dict):
        """Value a control shows for a resolved ladder (the tool radii when none are stored)."""
        if key == "inv_r50":
            return dict(zip(INV_R50_KEYS, resolve_tool(resolved)[0]))
        return resolved.get(key)

    # ------------------------------------------------------------ variable m/n
    def _build_variable_mn(self, v: QVBoxLayout):
        # The fit first: it is the path most zones need. The manual settings follow.
        v.addWidget(_subheading("Fit m to the wet points"))
        fit = QVBoxLayout()
        fit_row = QHBoxLayout()
        self.mn_fit_button = QPushButton("Fit m to the wet points")
        self.mn_fit_button.clicked.connect(self._on_mn_fit)
        fit_row.addWidget(self.mn_fit_button)
        self.mn_use_fit_button = QPushButton("Use fit")
        self.mn_use_fit_button.setToolTip(
            "Copy the fit into the settings below (curve mode, formula, coefficients, "
            "porosity). Apply writes them.")
        self.mn_use_fit_button.clicked.connect(self._on_mn_use_fit)
        fit_row.addWidget(self.mn_use_fit_button)
        fit_row.addStretch(1)
        fit.addLayout(fit_row)
        self.mn_fit_status = note("")
        fit.addWidget(self.mn_fit_status)
        self.mn_fit_inputs = note("")
        fit.addWidget(self.mn_fit_inputs)
        self.mn_fit_table = make_table(("Coefficient", "Value", "Standard error (approximate)"))
        self.mn_fit_table.setMaximumHeight(150)
        self.mn_fit_table.horizontalHeader().setStretchLastSection(False)
        fit.addWidget(self.mn_fit_table)
        self.mn_fit_stats = note("")
        fit.addWidget(self.mn_fit_stats)
        fit.addStretch(1)
        self.mn_plot = MnFitPlot()
        self.mn_plot.setMinimumHeight(300)
        v.addLayout(_side_by_side(fit, self.mn_plot))

        v.addWidget(_heading("Manual"))
        mform = _make_form()
        self._add_combo(mform, "mn_mode", "Mode")
        self._add_combo(mform, "m_model", "m model")
        coef = MultiSpin(MN_COEF_LABELS, LRLC_LISTS["m_coef"], 3, 0.05)
        self._register("m_coef", coef)
        mform.addRow("m coefficients", coef)
        self.shell_check = QCheckBox("Use Shell in this zone although the preset is not Carbonate")
        self._register("shell_confirm", self.shell_check)
        mform.addRow("", self.shell_check)
        self._add_combo(mform, "n_model", "n model")
        ncoef = MultiSpin(N_COEF_LABELS, LRLC_LISTS["n_coef"], 3, 0.05)
        self._register("n_coef", ncoef)
        mform.addRow("n coefficients", ncoef)
        self._add_combo(mform, "phi_source", "Porosity")
        v.addLayout(mform)
        self.shell_badge = note("")
        v.addWidget(self.shell_badge)
        row = QHBoxLayout()
        self.scoped_m_label = note("")
        row.addWidget(self.scoped_m_label, 1)
        self.set_c0_button = QPushButton("Set c0 to the zone m")
        self.set_c0_button.clicked.connect(self._on_set_c0)
        row.addWidget(self.set_c0_button)
        v.addLayout(row)
        self.clip_label = note("")
        v.addWidget(self.clip_label)
        self.mn_last_label = note("")
        v.addWidget(self.mn_last_label)
        self.mn_box = _strip("variable_mn")
        v.addWidget(self.mn_box)
        self._reset_mn_fit()

    def _reset_mn_fit(self):
        self._mn_proposal = None
        self.mn_fit_table.setRowCount(0)
        self.mn_fit_table.setVisible(False)
        self.mn_fit_status.setText("")
        self.mn_fit_stats.setText("")
        self.mn_fit_inputs.setText("")
        # Before a fit the plot and the table are hidden: one hint line, and Manual follows.
        self.mn_plot.clear_data("Fit m to see the wet points")
        self.mn_plot.setVisible(False)
        self.mn_fit_inputs.setVisible(False)
        self.mn_fit_stats.setVisible(False)
        self.mn_fit_status.setText("Fit m to see the wet points.")
        set_status(self.mn_fit_status, "muted")
        self._state_mn_fit()

    def _state_mn_fit(self):
        has_run = self.ds is not None and getattr(self.ds, "results", None) is not None
        self.mn_fit_button.setEnabled(bool(has_run) and self.model is not None)
        prop = getattr(self, "_mn_proposal", None)
        self.mn_use_fit_button.setEnabled(self._fit_usable(prop))

    @staticmethod
    def _fit_usable(prop) -> bool:
        fit = getattr(prop, "fit", None)
        return (prop is not None and prop.ok and fit is not None
                and bool(getattr(fit, "apply_allowed", False)) and bool(fit.coef))

    def _on_set_c0(self):
        flat = self._flat_params()
        m = flat.get("m")
        if m is None:
            return
        coef = self.controls["m_coef"].get()
        coef[0] = float(min(max(m, LRLC_LISTS["m_coef"][0][0]), LRLC_LISTS["m_coef"][0][1]))
        self.controls["m_coef"].set(coef)
        self._touched("m_coef")

    def _manual_boxes(self) -> list:
        provider = getattr(self, "manual_provider", None)
        if provider is None:
            return []
        try:
            return list(provider(self.zone) or [])
        except Exception:      # noqa: BLE001 - the fit then uses the automatic proposal
            logger.debug("manual wet-point boxes unavailable", exc_info=True)
            return []

    def _on_mn_fit(self):
        if self.model is None or self.ds is None:
            return
        phi_source = self._read_widget("phi_source")
        prop = svc.variable_m_proposal(self.model, self.ds, self.zone, self._manual_boxes(),
                                       phi_source)
        self._mn_proposal = prop
        self._show_mn_proposal(prop)

    def _show_mn_proposal(self, prop):
        self.mn_fit_table.setRowCount(0)
        self.mn_fit_stats.setText("")
        if prop.status != "fit":
            self.mn_fit_status.setText(prop.reason)
            set_status(self.mn_fit_status, "warning")
            self.mn_plot.clear_data(prop.reason)
            self._state_mn_fit()
            return
        fit = prop.fit
        self.mn_fit_inputs.setVisible(True)
        self.mn_fit_stats.setVisible(True)
        rw_text = fmt(prop.rw, 4) + (f" ({prop.rw_mode})" if prop.rw_mode else "")
        self.mn_fit_inputs.setText(
            f"Fit read: Rt curve {prop.rt_curve}, {prop.basis} basis, {prop.phi_source.upper()}, "
            f"Rw {rw_text}, a {fmt(prop.a, 2)}"
            + (", Rw brought to formation temperature" if prop.temperature else "")
            + f". Wet points {prop.n_wet} of {prop.n_rows}. "
            "The fit moves when the Rt chain changes. "
            + " ".join(prop.notes))
        if fit.coef is None:
            self.mn_fit_status.setText(fit.message or fit.status)
            set_status(self.mn_fit_status, "warning")
            self.mn_plot.clear_data(fit.message or "No fit")
            self._state_mn_fit()
            return
        names = ("c0", "c1", "c2", "c3")
        self.mn_fit_table.setVisible(True)
        self.mn_fit_table.setRowCount(4)
        for i, name in enumerate(names):
            free = name in fit.free
            self.mn_fit_table.setItem(i, 0, table_item(name + ("" if free else " (fixed)")))
            self.mn_fit_table.setItem(i, 1, table_item(fmt(fit.coef[i], 4), True))
            se = fit.se[i] if fit.se else None
            self.mn_fit_table.setItem(i, 2, table_item(fmt(se, 4) if free else "", True))
        ex = fit.excluded or {}
        parts = [f"Points used {fit.n_used}",
                 f"excluded: {ex.get('not_wet', 0)} not wet, {ex.get('nan', 0)} missing, "
                 f"{ex.get('window', 0)} outside the porosity window",
                 f"free: {', '.join(fit.free) or 'none'}",
                 f"rmse in ln Rt {fmt(fit.rmse_ln_rt, 3)}",
                 f"rmse in m {fmt(fit.rmse_m, 3)}", f"bias {fmt(fit.bias_m, 3)}",
                 f"R2 {fmt(fit.r2_m, 2)}"]
        if fit.phi_range:
            parts.append(f"porosity {fmt(fit.phi_range[0], 3)} to {fmt(fit.phi_range[1], 3)}")
        if fit.vsh_range:
            parts.append(f"Vsh {fmt(fit.vsh_range[0], 2)} to {fmt(fit.vsh_range[1], 2)}")
        if fit.m_range:
            parts.append(f"fitted m {fmt(fit.m_range[0], 2)} to {fmt(fit.m_range[1], 2)}")
        self.mn_fit_stats.setText("; ".join(parts) + ".")
        text = fit.message or ("Usable: Use fit copies it into the settings below."
                               if fit.apply_allowed else fit.status)
        self.mn_fit_status.setText(f"Status: {fit.status}. {text}")
        set_status(self.mn_fit_status, "success" if fit.apply_allowed else "warning")
        flat = self._flat_params()
        self.mn_plot.setVisible(True)
        self.mn_plot.set_data(prop.phi, prop.vsh, fit.index, fit.m_obs, fit.coef,
                              flat.get("m"), self._clip("clip_m"), prop.phi_source.upper())
        self._state_mn_fit()

    def _on_mn_use_fit(self):
        """Copy a usable fit into the pending values: the same four keys the fit service writes
        (curve mode, the formula model, the coefficients, the porosity), never the n model. The
        coefficients are kept at full precision for Apply; the spin boxes show them rounded."""
        prop = getattr(self, "_mn_proposal", None)
        if self.model is None or not self._fit_usable(prop):
            return
        self._set_value("mn_mode", "curve")
        self._set_value("m_model", "formula")
        self._set_value("phi_source", str(prop.phi_source).lower())
        coef = [round(float(c), 6) for c in prop.fit.coef]
        self._set_value("m_coef", coef)
        self._fit_coef = coef
        self._refresh_info()
        self._update_state()
        self.result_label.setText("The fit is in the settings below. Apply writes it.")
        set_status(self.result_label, "accent")

    def _clip(self, key: str):
        block = self.model.project.lrlc.get("variable_mn") or {} if self.model else {}
        value = block.get(key)
        try:
            lo, hi = float(value[0]), float(value[1])
            return lo, hi
        except (TypeError, ValueError, IndexError):
            return 1.0, 4.0

    def _state_variable_mn(self):
        shell = self._read_widget("m_model") == "shell"
        self.controls["m_coef"].setEnabled(not shell)
        self.shell_check.setEnabled(shell)
        self.controls["n_coef"].setEnabled(self._read_widget("n_model") == "vsh")
        self._state_mn_fit()

    def _info_variable_mn(self):
        flat = self._flat_params()
        m = flat.get("m")
        n = flat.get("n")
        self.scoped_m_label.setText(
            f"Zone values: m {fmt(m, 3)}, n {fmt(n, 3)}. They are used where the curve cannot "
            "be evaluated and as the constant n." if m is not None else "")
        self.set_c0_button.setEnabled(m is not None)
        preset = flat.get("lithology_preset") or "unknown"
        if self._read_widget("m_model") == "shell":
            if preset == SHELL_PRESET:
                text, status = f"Zone preset: {preset}. Shell is evaluated.", "success"
            elif self._read_widget("shell_confirm"):
                text, status = (f"Zone preset: {preset}, not {SHELL_PRESET}. Shell is evaluated "
                                "because you confirmed it for this zone.", "warning")
            else:
                text, status = (f"Zone preset: {preset}, not {SHELL_PRESET}. Shell is refused "
                                "and the zone keeps its constant m unless you confirm it.",
                                "warning")
        else:
            text, status = "", "muted"
        self.shell_badge.setText(text)
        self.shell_badge.setVisible(bool(text))
        set_status(self.shell_badge, status)
        lo_m, hi_m = self._clip("clip_m")
        lo_n, hi_n = self._clip("clip_n")
        self.clip_label.setText(
            f"Values are clipped to m {lo_m:g} to {hi_m:g} and n {lo_n:g} to {hi_n:g} "
            "(project setting) and the number clipped is reported after the run.")
        self.mn_last_label.setText(self._mn_last_run_text())
        self._state_variable_mn()

    def _zone_mask(self, res):
        if self.zone is not None and "ZONE" in res.columns:
            return res["ZONE"].fillna("").astype(str).to_numpy() == self.zone
        return np.ones(len(res), dtype=bool)

    def _mn_last_run_text(self) -> str:
        res = getattr(self.ds, "results", None) if self.ds is not None else None
        if res is None or "M_VAR" not in res.columns:
            return "M_VAR and N_VAR are not in the last run."
        mask = self._zone_mask(res)
        out = []
        for col, name in (("M_VAR", "m"), ("N_VAR", "n")):
            vals = res[col].to_numpy(dtype=float)[mask] if col in res.columns else np.array([])
            vals = vals[np.isfinite(vals)]
            if vals.size:
                p5, p50, p95 = np.percentile(vals, [5, 50, 95])
                out.append(f"{name} {fmt(p5, 2)} / {fmt(p50, 2)} / {fmt(p95, 2)}")
        text = "Last run (5th / 50th / 95th percentile): " + "; ".join(out) + "."
        lrlc = (getattr(self.ds, "summary", None) or {}).get("lrlc") or {}
        rec = svc.summary_record(lrlc.get("variable_mn"), self.zone)
        if rec:
            bits = [f"{rec[k]} {label}" for k, label in
                    (("n_eval", "evaluated"), ("n_fallback", "used the zone value"),
                     ("n_clipped_m", "m clipped"), ("n_clipped_n", "n clipped")) if k in rec]
            if bits:
                text += " Samples: " + ", ".join(bits) + "."
        return text

    # ---------------------------------------------------------- radial invasion
    def _build_invasion(self, v: QVBoxLayout):
        self._step_check(v, "invasion")
        self.inv_banner = note(
            "RM, RS and RXO must already be corrected for borehole, mud and shoulder-bed "
            "effects; this step does not correct them.", "warning")
        v.addWidget(self.inv_banner)
        curves = QHBoxLayout()
        self.inv_curves_label = note("")
        curves.addWidget(self.inv_curves_label, 1)
        self.inv_curves_button = QPushButton("Open Screening > Curves")
        set_variant(self.inv_curves_button, "link")
        self.inv_curves_button.clicked.connect(
            lambda: self.panel_requested.emit("screening", "curves"))
        curves.addWidget(self.inv_curves_button)
        v.addLayout(curves)

        left = QVBoxLayout()
        tform = _make_form()
        tool = self._add_combo(tform, "inv_tool", "Tool")
        tool.currentIndexChanged.connect(self._on_tool_changed)
        self.generic_badge = QLabel(GENERIC_LABEL)
        set_status(self.generic_badge, "warning")
        tform.addRow("", self.generic_badge)
        self._add_combo(tform, "inv_rxo_mode", "RXO")
        self._add_spins(tform, tuple(r for r in INVASION_ROWS if r[0] in ("rmf", "rmf_temp")))
        left.addLayout(tform)
        row = QHBoxLayout()
        self.header_label = note("")
        row.addWidget(self.header_label, 1)
        self.header_button = QPushButton("Use header Rmf")
        self.header_button.clicked.connect(self._on_use_header_rmf)
        row.addWidget(self.header_button)
        left.addLayout(row)
        left.addWidget(_heading("Advanced"))
        aform = _make_form()
        r50 = MultiSpin(("Deep (in)", "Medium (in)", "Shallow (in)"), INV_R50_RANGE, 1, 1.0,
                        as_dict=True)
        self._register("inv_r50", r50)
        aform.addRow("Investigation diameters", r50)
        left.addLayout(aform)
        self.inv_tool_label = note("")
        left.addWidget(self.inv_tool_label)
        fform = _make_form()
        self._add_spins(fform, tuple(r for r in INVASION_ROWS if r[0] in (
            "inv_p", "inv_di_min", "inv_di_max", "inv_min_contrast", "inv_max_rms")))
        left.addLayout(fform)
        left.addStretch(1)

        right = QVBoxLayout()
        depth_row = QHBoxLayout()
        depth_row.addWidget(QLabel("Profile at depth"))
        self.depth_spin = QDoubleSpinBox()
        self.depth_spin.setRange(-10000.0, 100000.0)
        self.depth_spin.setDecimals(2)
        self.depth_spin.setSingleStep(1.0)
        self.depth_spin.setKeyboardTracking(False)
        self.depth_spin.setMaximumWidth(SPIN_MAX_WIDTH)
        self.depth_spin.valueChanged.connect(lambda _v: self._draw_invasion_profile())
        depth_row.addWidget(self.depth_spin)
        depth_row.addStretch(1)
        right.addLayout(depth_row)
        self.profile_plot = InvasionProfilePlot()
        right.addWidget(self.profile_plot, 1)
        self.tornado_plot = TornadoPlot()
        self.tornado_plot.depth_picked.connect(self._on_depth_picked)
        right.addWidget(self.tornado_plot, 1)
        plots = QWidget()
        plots.setLayout(right)
        right.setContentsMargins(0, 0, 0, 0)
        v.addLayout(_side_by_side(left, plots))

        self.inv_counts = make_table(COUNT_COLUMNS)
        self.inv_counts.setMaximumHeight(150)
        v.addWidget(self.inv_counts)
        self.inv_box = _strip("invasion")
        v.addWidget(self.inv_box)

    def _on_tool_changed(self, *_):
        if self._loading:
            return
        key = self.controls["inv_tool"].currentData()
        preset = GENERIC_TOOLS.get(key)
        if preset is not None:
            self.controls["inv_r50"].set(
                {"deep": preset["deep"], "medium": preset["medium"],
                 "shallow": preset["shallow"]})
        resolved = self._resolved_now()
        if self._read_widget("inv_r50") != resolved.get("inv_r50"):
            self._dirty.add("inv_r50")
        else:
            self._dirty.discard("inv_r50")
        self._refresh_info()
        self._update_state()

    def _resolved_now(self) -> dict:
        from modules.lrlc.config import resolve_lrlc

        return resolve_lrlc(*self._ladder(), self.zone)

    def _header_mud(self):
        return parse_header_mud(getattr(self.ds, "well_info", None)) if self.ds is not None else None

    def _on_use_header_rmf(self):
        mud = self._header_mud()
        if mud is None:
            return
        self._set_value("rmf", round(mud["rmf"], 4))
        if mud["rmf_temp"] is not None:
            self._set_value("rmf_temp", round(mud["rmf_temp"], 1))
        self._refresh_info()
        self._update_state()

    def _tool_now(self):
        return resolve_tool(self._current_params())

    def _state_invasion(self):
        custom = self._read_widget("inv_tool") == "custom"
        self.controls["inv_r50"].setEnabled(custom)
        _r50, _p, generic, _bad = self._tool_now()
        self.generic_badge.setVisible(generic)

    def _info_invasion(self):
        # One line, only when a curve role is not mapped: a warning when RM or RS (required) is
        # missing, a muted note when only RXO (optional) is; both link to Screening > Curves.
        required = optional = False
        text = ""
        if self.ds is not None:
            names = []
            for role in ("RM", "RS", "RXO"):
                name = svc.aux_curve_name(self.ds, role)
                names.append(f"{role} {name}" if name else f"{role} not mapped")
                if not name:
                    required = required or role != "RXO"
                    optional = optional or role == "RXO"
            if required or optional:
                text = (("The step needs RM and RS. " if required else "") + "Curves: "
                        + ", ".join(names) + ".")
        self.inv_curves_label.setText(text)
        set_status(self.inv_curves_label, "warning" if required else "muted")
        self.inv_curves_label.setVisible(bool(text))
        self.inv_curves_button.setVisible(bool(text))
        mud = self._header_mud()
        if mud is None:
            self.header_label.setText("")
        else:
            t = (f" at {fmt(mud['rmf_temp'], 1)} degF" if mud["rmf_temp"] is not None else "")
            self.header_label.setText(
                f"Header: Rmf {fmt(mud['rmf'], 4)} ohm.m{t}."
                + (f" ({mud['note']})" if mud["note"] else ""))
        self.header_label.setVisible(mud is not None)
        self.header_button.setVisible(mud is not None)
        r50, p, generic, bad = self._tool_now()
        self.inv_tool_label.setText(
            ("Preset values in use: " if generic else "Values in use: ")
            + f"deep {r50[0]:g} in, medium {r50[1]:g} in, shallow {r50[2]:g} in, p {p:g}."
            + (" The stored values are not valid; the preset is used." if bad else ""))
        self._fill_invasion_counts()
        self._configure_depth_spin()
        self._draw_invasion_plots()
        self._state_invasion()

    def _fill_invasion_counts(self):
        table = self.inv_counts
        table.setRowCount(0)
        lrlc = (getattr(self.ds, "summary", None) or {}).get("lrlc") or {}
        block = lrlc.get("invasion")
        records = []
        if isinstance(block, dict) and isinstance(block.get("zones"), list):
            records = [r for r in block["zones"] if isinstance(r, dict)]
        elif isinstance(block, dict):
            records = [dict(r, zone=z) if isinstance(r, dict) else {"zone": z}
                       for z, r in block.items()]
        elif block:
            records = [r for r in block if isinstance(r, dict)]
        if self.zone is not None:
            records = [r for r in records if r.get("zone") == self.zone]
        for rec in records:
            row = table.rowCount()
            table.insertRow(row)
            cells = [rec.get("zone") or "Whole well",
                     (rec.get("tool") or "") + (" (generic)" if rec.get("generic") else "")]
            cells += [rec.get(k, "") for k in COUNT_KEYS]
            cells += [fmt(rec.get("rt_ratio_p50"), 3), fmt(rec.get("di_p50"), 1)]
            for c, text in enumerate(cells):
                table.setItem(row, c, table_item(text, c >= 2))

    def _view(self):
        return svc.invasion_view_data(self.ds, self.zone) if self.ds is not None else None

    def _configure_depth_spin(self):
        view = self._view()
        spin = self.depth_spin
        was = spin.blockSignals(True)
        try:
            if view is None or not np.isfinite(view["depth"]).any():
                spin.setEnabled(False)
                return
            spin.setEnabled(True)
            d = view["depth"][np.isfinite(view["depth"])]
            spin.setRange(float(d.min()), float(d.max()))
            if not (float(d.min()) <= spin.value() <= float(d.max())):
                spin.setValue(float(d[len(d) // 2]))
        finally:
            spin.blockSignals(was)

    def _draw_invasion_plots(self):
        self._draw_tornado()
        self._draw_invasion_profile()

    def _draw_tornado(self):
        view = self._view()
        if view is None or view["rt"] is None or view["rm"] is None or view["rs"] is None:
            self.tornado_plot.clear_data(
                "Map RM and RS (Screening > Curves) to see the RS/RT against RM/RT crossplot")
            return
        r50, p, generic, _bad = self._tool_now()
        prm = self._current_params()
        self.tornado_plot.set_data(view["rt"], view["rm"], view["rs"], view["di"], r50, p,
                                   float(prm["inv_di_min"]), float(prm["inv_di_max"]), generic,
                                   depth=view["depth"])

    def _on_depth_picked(self, depth: float):
        was = self.depth_spin.blockSignals(True)
        self.depth_spin.setValue(float(depth))
        self.depth_spin.blockSignals(was)
        self._draw_invasion_profile()

    def _draw_invasion_profile(self):
        view = self._view()
        if view is None or view["rt"] is None or not self.depth_spin.isEnabled():
            self.profile_plot.clear_data("Run the analysis to see the profile at a depth")
            return
        depth = view["depth"]
        ok = np.isfinite(depth)
        if not ok.any():
            self.profile_plot.clear_data("No depth values")
            return
        row = int(np.flatnonzero(ok)[np.argmin(np.abs(depth[ok] - self.depth_spin.value()))])

        def at(key):
            arr = view.get(key)
            return None if arr is None else float(arr[row])

        r50, p, _generic, _bad = self._tool_now()
        readings = [at("rt"), at("rm"), at("rs")]
        di = at("di")
        note_text = ""
        if view["rt_inv"] is None:
            note_text = "the Invasion step has not run"
        elif di is None or not np.isfinite(di):
            note_text = "no profile (non-unique or invalid)"
        self.profile_plot.set_data(float(depth[row]), readings, at("rt_inv"), at("rxo_inv"), di,
                                   r50, p, note_text)

    def refresh_new_themes(self):
        self.mn_plot.refresh_theme()
        self.profile_plot.refresh_theme()
        self.tornado_plot.refresh_theme()
