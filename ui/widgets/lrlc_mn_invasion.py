"""Variable m/n and Radial invasion sections of the Remediation form.

``MnInvasionMixin`` is mixed into ``RemediationForm`` and uses its scratch-copy machinery: the
controls registered here change nothing until Apply. The m fit and its Apply button write
through ``services.lrlc_service`` (a separate explicit step), and the invasion plots read the
last run; nothing here runs the analysis.
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
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from modules.lrlc.config import INV_R50_KEYS, INV_R50_RANGE, LRLC_LISTS, LRLC_RANGES
from modules.lrlc.invasion import GENERIC_LABEL, GENERIC_TOOLS, resolve_tool
from modules.lrlc.methods import METHOD_TEXT
from modules.las_parser import mud_header_proposal
from modules.lrlc.variable_mn import SHELL_PRESET
from services import lrlc_service as svc
from services.lrlc_service import LrlcService
from themes.helpers import set_status

from .lrlc_common import fmt, make_table, note
from .lrlc_common import item as table_item
from .lrlc_invasion_plot import InvasionProfilePlot, TornadoPlot
from .lrlc_mn_plot import MnFitPlot
from .method_box import MethodReferenceBox

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
            spin.valueChanged.connect(lambda v: self.valueChanged.emit(float(v)))
            col.addWidget(spin)
            row.addLayout(col)
            self.spins.append(spin)

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


class MnInvasionMixin:
    """Builds and refreshes the Variable m/n and Radial invasion sections."""

    # ------------------------------------------------------------------ helpers
    def _add_combo(self, form: QFormLayout, key: str, label: str):
        combo = QComboBox()
        for value, text in MN_COMBOS[key]:
            combo.addItem(text, value)
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
            self._register(key, spin)
            form.addRow(label, spin)

    def _display_value(self, key: str, resolved: dict):
        """Value a control shows for a resolved ladder (the tool radii when none are stored)."""
        if key == "inv_r50":
            return dict(zip(INV_R50_KEYS, resolve_tool(resolved)[0]))
        return resolved.get(key)

    # ------------------------------------------------------------ variable m/n
    def _build_variable_mn(self) -> QGroupBox:
        group = self._group("variable_mn", "Variable m/n")
        v = QVBoxLayout(group)
        form = QFormLayout()
        self._add_combo(form, "mn_mode", "Mode")
        self._add_combo(form, "m_model", "m model")
        coef = MultiSpin(MN_COEF_LABELS, LRLC_LISTS["m_coef"], 3, 0.05)
        self._register("m_coef", coef)
        form.addRow("m coefficients", coef)
        self.shell_check = QCheckBox("Use Shell in this zone although the preset is not Carbonate")
        self._register("shell_confirm", self.shell_check)
        form.addRow("", self.shell_check)
        self._add_combo(form, "n_model", "n model")
        ncoef = MultiSpin(N_COEF_LABELS, LRLC_LISTS["n_coef"], 3, 0.05)
        self._register("n_coef", ncoef)
        form.addRow("n coefficients", ncoef)
        self._add_combo(form, "phi_source", "Porosity")
        v.addLayout(form)
        row = QHBoxLayout()
        self.scoped_m_label = note("")
        row.addWidget(self.scoped_m_label, 1)
        self.set_c0_button = QPushButton("Set c0 to the zone m")
        self.set_c0_button.clicked.connect(self._on_set_c0)
        row.addWidget(self.set_c0_button)
        v.addLayout(row)
        self.shell_badge = note("")
        v.addWidget(self.shell_badge)
        self.clip_label = note("")
        v.addWidget(self.clip_label)
        self.mn_last_label = note("")
        v.addWidget(self.mn_last_label)

        fit_row = QHBoxLayout()
        self.mn_fit_button = QPushButton("Fit m to the wet points")
        self.mn_fit_button.clicked.connect(self._on_mn_fit)
        fit_row.addWidget(self.mn_fit_button)
        self.mn_apply_fit_button = QPushButton("Apply fit")
        self.mn_apply_fit_button.setProperty("variant", "primary")
        self.mn_apply_fit_button.clicked.connect(self._on_mn_apply_fit)
        fit_row.addWidget(self.mn_apply_fit_button)
        fit_row.addStretch(1)
        v.addLayout(fit_row)
        self.mn_fit_inputs = note("")
        v.addWidget(self.mn_fit_inputs)
        self.mn_fit_status = note("")
        v.addWidget(self.mn_fit_status)
        self.mn_fit_table = make_table(("Coefficient", "Value", "Standard error (approximate)"))
        self.mn_fit_table.setMaximumHeight(150)
        self.mn_fit_table.horizontalHeader().setStretchLastSection(False)
        v.addWidget(self.mn_fit_table)
        self.mn_fit_stats = note("")
        v.addWidget(self.mn_fit_stats)
        self.mn_plot = MnFitPlot()
        v.addWidget(self.mn_plot)
        self.mn_box = MethodReferenceBox()
        self.mn_box.set_method(METHOD_TEXT["variable_mn"])
        v.addWidget(self.mn_box)
        self._reset_mn_fit()
        return group

    def _reset_mn_fit(self):
        self._mn_proposal = None
        self.mn_fit_table.setRowCount(0)
        self.mn_fit_status.setText("")
        self.mn_fit_stats.setText("")
        self.mn_fit_inputs.setText(
            "The fit reads the wet points of the Pickett selection, the Rt that the Sw models "
            "read (RT_SW of the last run) and the zone Rw. It moves when the Rt chain changes.")
        self.mn_plot.clear_data("Fit m to see the wet points")
        self._state_mn_fit()

    def _state_mn_fit(self):
        has_run = self.ds is not None and getattr(self.ds, "results", None) is not None
        self.mn_fit_button.setEnabled(bool(has_run) and self.model is not None)
        prop = getattr(self, "_mn_proposal", None)
        self.mn_apply_fit_button.setEnabled(prop is not None and prop.ok)

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
        text = fit.message or ("Usable: apply it to write the coefficients."
                               if fit.apply_allowed else fit.status)
        self.mn_fit_status.setText(f"Status: {fit.status}. {text}")
        set_status(self.mn_fit_status, "success" if fit.apply_allowed else "warning")
        flat = self._flat_params()
        self.mn_plot.set_data(prop.phi, prop.vsh, fit.index, fit.m_obs, fit.coef,
                              flat.get("m"), self._clip("clip_m"), prop.phi_source.upper())
        self._state_mn_fit()

    def _on_mn_apply_fit(self):
        prop = getattr(self, "_mn_proposal", None)
        if self.model is None or prop is None or not prop.ok:
            return
        level, zone = self._target()
        written = svc.apply_variable_m_fit(self.model, level, zone, prop.fit, prop.phi_source,
                                           self.ds)
        if not written:
            self.result_label.setText(
                "Nothing was written: the fit is already stored at this scope.")
            set_status(self.result_label, "warning")
            return
        # The four keys are stored now: show the stored values and drop them from the pending set.
        resolved = self._resolved_now()
        for key in written:
            self._dirty.discard(key)
            if key in self.controls:
                was = self._loading
                self._loading = True
                try:
                    self._write_widget(key, self.controls[key], self._display_value(key, resolved))
                finally:
                    self._loading = was
        self._refresh_info()
        self._update_state()
        self.result_label.setText(
            "Written: " + ", ".join(NEW_LABELS.get(k, k) for k in written)
            + ". Run the analysis to see the effect.")
        set_status(self.result_label, "success")
        self.stale_requested.emit(self._stale_keys("project" if level == "project" else level))
        self.applied.emit(written)

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
            text, status = f"Zone preset: {preset}.", "muted"
        self.shell_badge.setText(text)
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
    def _build_invasion(self) -> QGroupBox:
        group = self._group("invasion", "Radial invasion")
        v = QVBoxLayout(group)
        self.inv_banner = note(
            "RM, RS and RXO must already be corrected by you for borehole, mud and shoulder-bed "
            "effects; this step does not correct them.", "warning")
        v.addWidget(self.inv_banner)
        self.inv_step_label = note("")
        v.addWidget(self.inv_step_label)
        self.inv_curves_label = note("")
        v.addWidget(self.inv_curves_label)
        form = QFormLayout()
        tool = self._add_combo(form, "inv_tool", "Tool")
        tool.currentIndexChanged.connect(self._on_tool_changed)
        self.generic_badge = QLabel(GENERIC_LABEL)
        set_status(self.generic_badge, "warning")
        form.addRow("", self.generic_badge)
        r50 = MultiSpin(("Deep (in)", "Medium (in)", "Shallow (in)"), INV_R50_RANGE, 1, 1.0,
                        as_dict=True)
        self._register("inv_r50", r50)
        form.addRow("Investigation diameters", r50)
        self._add_combo(form, "inv_rxo_mode", "RXO")
        self._add_spins(form, INVASION_ROWS)
        v.addLayout(form)
        row = QHBoxLayout()
        self.header_label = note("")
        row.addWidget(self.header_label, 1)
        self.header_button = QPushButton("Use header Rmf")
        self.header_button.clicked.connect(self._on_use_header_rmf)
        row.addWidget(self.header_button)
        v.addLayout(row)
        self.inv_tool_label = note("")
        v.addWidget(self.inv_tool_label)

        self.inv_counts = make_table(COUNT_COLUMNS)
        self.inv_counts.setMaximumHeight(150)
        v.addWidget(self.inv_counts)

        depth_row = QHBoxLayout()
        depth_row.addWidget(QLabel("Profile at depth"))
        self.depth_spin = QDoubleSpinBox()
        self.depth_spin.setRange(-10000.0, 100000.0)
        self.depth_spin.setDecimals(2)
        self.depth_spin.setSingleStep(1.0)
        self.depth_spin.setKeyboardTracking(False)
        self.depth_spin.valueChanged.connect(lambda _v: self._draw_invasion_profile())
        depth_row.addWidget(self.depth_spin)
        depth_row.addStretch(1)
        v.addLayout(depth_row)
        self.profile_plot = InvasionProfilePlot()
        v.addWidget(self.profile_plot)
        self.tornado_plot = TornadoPlot()
        self.tornado_plot.depth_picked.connect(self._on_depth_picked)
        v.addWidget(self.tornado_plot)
        self.inv_box = MethodReferenceBox()
        self.inv_box.set_method(METHOD_TEXT["invasion"])
        v.addWidget(self.inv_box)
        return group

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
        prm = self._current_params()
        from .lrlc_remediation import resolve_lrlc_steps

        on = "invasion" in resolve_lrlc_steps(prm)
        self.inv_step_label.setText(
            "The Invasion step is on for this zone: Sw reads the invasion-corrected Rt."
            if on else
            "The Invasion step is off for this zone. Switch it on in Rt source above; the "
            "settings below take effect after Apply and a run.")
        set_status(self.inv_step_label, "accent" if on else "muted")
        if self.ds is not None:
            names = []
            for role in ("RM", "RS", "RXO"):
                name = svc.aux_curve_name(self.ds, role)
                names.append(f"{role} {name}" if name else f"{role} not mapped")
            self.inv_curves_label.setText(
                "Curves: " + ", ".join(names) + ". Map them in Screening > Curves.")
        else:
            self.inv_curves_label.setText("")
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
