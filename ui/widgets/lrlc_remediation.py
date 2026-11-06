"""Remediation form of the LRLC Workbench: laminated sand, pyrite, clay (Qv) and the Sw basis.

The form edits a scratch copy of the values that apply to the chosen zone. Changing a control
writes nothing; the Apply button writes only the values you changed, to the chosen scope, through
``LrlcService.apply_remediation`` (and the Thomas-Stieber / pyrite switches through
``LrlcService.set_setting``), then asks the owner to mark the wells stale
(``stale_requested``). The form never runs the analysis.
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

from modules.lrlc import chain
from modules.lrlc.config import LRLC_RANGES, resolve_lrlc
from modules.lrlc.invasion import GENERIC_TOOLS
from modules.lrlc.l2 import resolve_basis
from modules.lrlc.methods import METHOD_TEXT
from modules.lrlc.thomas_stieber import check_endpoints
from services.lrlc_service import LrlcService
from themes.helpers import set_status

from .lrlc_common import WHOLE_WELL, fmt, note
from .lrlc_diagnosis import lrlc_summary
from .lrlc_mn_invasion import NEW_LABELS, MnInvasionMixin, MultiSpin
from .lrlc_pickett import zone_labels
from .lrlc_ts_plot import PefRhobPlot
from .method_box import MethodReferenceBox

logger = logging.getLogger(__name__)

SECTIONS = ("laminated", "pyrite", "clay", "sw_basis", "variable_mn", "invasion")

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
SETTING_KEYS = {"ts_enabled": ("thomas_stieber", "enabled"), "vpyr_enabled": ("pyrite", "enabled")}
SETTING_LABELS = {"ts_enabled": "Thomas-Stieber on", "vpyr_enabled": "VPYR column on"}
SCOPE_NOTE = {
    "zone": "Written to this well for the chosen zone.",
    "well": "Written as the default of this well.",
    "project": "Written as the project default; every well is marked for a re-check.",
}


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
    return spin


class RemediationForm(MnInvasionMixin, QWidget):
    """The Remediation sections below the Rt source box. Public: ``set_context``, ``prepare``,
    ``scroll_target``."""

    stale_requested = pyqtSignal(list)
    navigate_requested = pyqtSignal(str)
    zone_changed = pyqtSignal(object)       # the user picked another zone in this form
    applied = pyqtSignal(list)              # keys written

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = None
        self.ds = None
        self.zone: Optional[str] = None
        self._loading = False
        self._loaded_for = None
        self._dirty: set = set()
        self._steps: Optional[List[str]] = None
        self._settings: Dict[str, bool] = {}
        self._models_hint: List[str] = []
        self._proposal = None
        self._cec = None
        self._mn_proposal = None
        self.manual_provider = None     # callable(zone) -> manual wet-point boxes
        self.controls: Dict[str, QWidget] = {}
        self.groups: Dict[str, QGroupBox] = {}
        self._build()

    # ------------------------------------------------------------------ build
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addLayout(self._build_header())
        self.hint_label = note("", "accent")
        root.addWidget(self.hint_label)
        root.addWidget(self._build_laminated())
        root.addWidget(self._build_pyrite())
        root.addWidget(self._build_clay())
        root.addWidget(self._build_basis())
        root.addWidget(self._build_variable_mn())
        root.addWidget(self._build_invasion())
        root.addStretch(1)

    def _build_header(self) -> QVBoxLayout:
        v = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(QLabel("Zone"))
        self.zone_combo = QComboBox()
        self.zone_combo.setMinimumWidth(140)
        self.zone_combo.currentIndexChanged.connect(self._on_zone_combo)
        row.addWidget(self.zone_combo)
        row.addWidget(QLabel("Apply to"))
        self.scope_combo = QComboBox()
        for key, text in SCOPES:
            self.scope_combo.addItem(text, key)
        self.scope_combo.setCurrentIndex(1)
        self.scope_combo.currentIndexChanged.connect(lambda _i: self._update_state())
        row.addWidget(self.scope_combo)
        self.apply_button = QPushButton("Apply")
        self.apply_button.setProperty("variant", "primary")
        self.apply_button.clicked.connect(self._on_apply)
        row.addWidget(self.apply_button)
        self.discard_button = QPushButton("Discard changes")
        self.discard_button.clicked.connect(self._on_discard)
        row.addWidget(self.discard_button)
        row.addStretch(1)
        v.addLayout(row)
        self.pending_label = note("")
        v.addWidget(self.pending_label)
        self.result_label = note("")
        v.addWidget(self.result_label)
        return v

    def _register(self, key, widget):
        self.controls[key] = widget
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

    def _combo(self, form: QFormLayout, key, label):
        combo = QComboBox()
        for value, text in COMBOS[key]:
            combo.addItem(text, value)
        self._register(key, combo)
        form.addRow(label, combo)

    def _group(self, name, title) -> QGroupBox:
        group = QGroupBox(title)
        self.groups[name] = group
        return group

    def _build_laminated(self) -> QGroupBox:
        group = self._group("laminated", "Laminated sand")
        v = QVBoxLayout(group)
        self.ts_check = QCheckBox("Compute Thomas-Stieber (laminar shale volume) on the next run")
        self.ts_check.toggled.connect(lambda on: self._setting_touched("ts_enabled", on))
        v.addWidget(self.ts_check)
        form = QFormLayout()
        self._combo(form, "vlam_source", "Vlam source")
        self._rows(form, LAMINATED_ROWS)
        v.addLayout(form)
        proposal = QHBoxLayout()
        self.proposal_label = note("")
        proposal.addWidget(self.proposal_label, 1)
        self.use_proposal_button = QPushButton("Use proposal")
        self.use_proposal_button.clicked.connect(self._on_use_proposal)
        proposal.addWidget(self.use_proposal_button)
        v.addLayout(proposal)
        self.applied_label = note("")
        v.addWidget(self.applied_label)
        self.laminated_box = MethodReferenceBox()
        self.laminated_box.set_method(METHOD_TEXT["laminated"])
        v.addWidget(self.laminated_box)
        return group

    def _build_pyrite(self) -> QGroupBox:
        group = self._group("pyrite", "Pyrite")
        v = QVBoxLayout(group)
        self.vpyr_check = QCheckBox("Compute the VPYR column on the next run")
        self.vpyr_check.toggled.connect(lambda on: self._setting_touched("vpyr_enabled", on))
        v.addWidget(self.vpyr_check)
        form = QFormLayout()
        self._combo(form, "pyr_method", "Pyrite volume")
        self._rows(form, PYRITE_ROWS)
        v.addLayout(form)
        self.vpyr_label = note("")
        v.addWidget(self.vpyr_label)
        self.pef_plot = PefRhobPlot()
        v.addWidget(self.pef_plot)
        self.pyrite_box = MethodReferenceBox()
        self.pyrite_box.set_method(METHOD_TEXT["pyrite"])
        v.addWidget(self.pyrite_box)
        return group

    def _build_clay(self) -> QGroupBox:
        group = self._group("clay", "Clay (Qv)")
        v = QVBoxLayout(group)
        form = QFormLayout()
        self._combo(form, "qv_source", "Qv source")
        self._rows(form, CLAY_ROWS)
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
        self.qv_box = MethodReferenceBox()
        self.qv_box.set_method(METHOD_TEXT["qv"])
        v.addWidget(self.qv_box)
        return group

    def _build_basis(self) -> QGroupBox:
        group = self._group("sw_basis", "Sw basis")
        v = QVBoxLayout(group)
        form = QFormLayout()
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
        return group

    # ---------------------------------------------------------------- context
    def set_context(self, model, ds, zone: Optional[str] = None, zones=()):
        self.model = model
        self.ds = ds
        new_zone = zone or None
        self._fill_zone_combo(list(zones), new_zone)
        target = (getattr(ds, "key", None), new_zone)
        reload = not (self._loaded_for == target and (self._dirty or self._settings))
        self.zone = new_zone
        self._loaded_for = target
        if reload:
            self._steps = None
            self._settings = {}
            self._dirty = set()
            self._models_hint = []
            self.result_label.setText("")
            self._load_values()
        fit_key = (target, id(getattr(ds, "results", None)))
        if getattr(self, "_mn_fit_for", None) != fit_key:
            self._mn_fit_for = fit_key
            self._reset_mn_fit()
        self._refresh_info()
        self._update_state()

    def _fill_zone_combo(self, zones, current):
        was = self._loading
        self._loading = True
        try:
            self.zone_combo.clear()
            self.zone_combo.addItem(WHOLE_WELL, None)
            for z in zones:
                self.zone_combo.addItem(z, z)
            if current and self.zone_combo.findData(current) < 0:
                self.zone_combo.addItem(current, current)
            i = self.zone_combo.findData(current)
            self.zone_combo.setCurrentIndex(max(i, 0))
        finally:
            self._loading = was

    def _on_zone_combo(self, *_):
        if self._loading:
            return
        self.zone_changed.emit(self.zone_combo.currentData())

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
        if remedy.get("rt_steps"):
            resolved = resolve_lrlc(*self._ladder(), self.zone)
            have = list(resolve_lrlc_steps(resolved))
            names = have + [s for s in remedy["rt_steps"] if s not in have]
            self._steps = chain_sorted(names)
            self._dirty.add("rt_steps")
            if "laminated" in remedy["rt_steps"]:
                self._set_setting("ts_enabled", True)
            if "pyrite" in remedy["rt_steps"]:
                self._set_setting("vpyr_enabled", True)
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

    def _load_values(self):
        if self.model is None:
            return
        resolved = resolve_lrlc(*self._ladder(), self.zone)
        was = self._loading
        self._loading = True
        try:
            for key, widget in self.controls.items():
                self._write_widget(key, widget, self._display_value(key, resolved))
            lrlc = self.model.project.lrlc
            self.ts_check.setChecked(bool((lrlc.get("thomas_stieber") or {}).get("enabled")))
            self.vpyr_check.setChecked(bool((lrlc.get("pyrite") or {}).get("enabled")))
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

    def _set_setting(self, name, on):
        check = self.ts_check if name == "ts_enabled" else self.vpyr_check
        was = self._loading
        self._loading = True
        try:
            check.setChecked(bool(on))
        finally:
            self._loading = was
        block, key = SETTING_KEYS[name]
        stored = bool((self.model.project.lrlc.get(block) or {}).get(key))
        if stored != bool(on):
            self._settings[name] = bool(on)
        else:
            self._settings.pop(name, None)

    def _touched(self, key):
        if self._loading:
            return
        self._dirty.add(key)
        self.result_label.setText("")
        self._refresh_info()
        self._update_state()

    def _setting_touched(self, name, on):
        if self._loading:
            return
        self._set_setting(name, on)
        self.result_label.setText("")
        self._update_state()

    def _current_params(self) -> dict:
        """The resolved ladder of the zone with the form's values on top."""
        prm = resolve_lrlc(*self._ladder(), self.zone)
        for key in self.controls:
            prm[key] = self._read_widget(key)
        if self._steps is not None:
            prm["rt_steps"] = list(self._steps)
        return prm

    # ------------------------------------------------------------------- state
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
        vconst = self._read_widget("vlam_source") == "constant"
        self.controls["vlam_const"].setEnabled(vconst)
        manual = self._read_widget("pyr_method") == "manual"
        self.controls["pyr_vpyr"].setEnabled(manual)
        self._state_variable_mn()
        self._state_invasion()
        pending = [KEY_LABELS.get(k, k) for k in sorted(self._dirty)] + [
            SETTING_LABELS[k] for k in sorted(self._settings)]
        self.apply_button.setEnabled(bool(pending) and self.model is not None)
        self.discard_button.setEnabled(bool(pending))
        scope = self.scope_combo.currentData()
        self.pending_label.setText(
            ("Not yet written: " + ", ".join(pending) + ". " + SCOPE_NOTE[scope]) if pending
            else "Changing a value writes nothing; Apply writes the values you changed. "
                 + SCOPE_NOTE[scope])
        steps = self._steps
        if steps is not None:
            self.pending_label.setText(
                self.pending_label.text() + " Rt steps after Apply: " + (", ".join(steps) or "none")
                + ".")

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
        self._steps = None
        self._settings = {}
        self._dirty = set()
        self._models_hint = []
        self.result_label.setText("")
        self._load_values()
        self._refresh_info()
        self._update_state()

    def _on_apply(self):
        if self.model is None or not (self._dirty or self._settings):
            return
        level, zone = self._target()
        values: Dict[str, Any] = {}
        for key in self._dirty:
            if key == "rt_steps":
                values[key] = list(self._steps or [])
            else:
                values[key] = self._read_widget(key)
        written: List[str] = []
        if values:
            written = LrlcService.apply_remediation(self.model, level, zone, values, self.ds)
        changed_settings = []
        for name, on in list(self._settings.items()):
            block, key = SETTING_KEYS[name]
            if LrlcService.set_setting(self.model, block, key, on):
                changed_settings.append(name)
        if not written and not changed_settings:
            self.result_label.setText(
                "Nothing was written: the values are already stored at this scope, or they break "
                "a rule (the shale porosity must be at least 0.02 below the clean-sand porosity, "
                "and the sensitivity warning limit below the invalid limit).")
            set_status(self.result_label, "warning")
            return
        wrote = [KEY_LABELS.get(k, k) for k in written] + [SETTING_LABELS[n]
                                                          for n in changed_settings]
        self._steps = None
        self._settings = {}
        self._dirty = set()
        self._load_values()
        self._refresh_info()
        self._update_state()
        self.result_label.setText(
            "Written: " + ", ".join(wrote) + ". Run the analysis to see the effect.")
        set_status(self.result_label, "success")
        project_wide = level == "project" or bool(changed_settings)
        self.stale_requested.emit(self._stale_keys("project" if project_wide else level))
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
        self._info_laminated()
        self._info_pyrite()
        self._info_clay()
        self._info_basis()
        self._info_variable_mn()
        self._info_invasion()

    def _zone_key(self):
        return self.zone

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
        resolved = resolve_lrlc(*self._ladder(), self.zone)
        pm, ps = resolved.get("phi_max"), resolved.get("phi_sh")
        if pm is None or ps is None:
            self.applied_label.setText(
                "Stored for this zone: no end-points. Without them Thomas-Stieber gives no "
                "laminar shale volume.")
        else:
            ok, why = check_endpoints(pm, ps)
            self.applied_label.setText(
                f"Stored for this zone: phi_max {fmt(pm, 3)}, phi_sh {fmt(ps, 3)}"
                + ("" if ok else f" (not usable: {why})") + ".")

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
            samples = None
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
            self.vpyr_label.setText(
                "No VPYR in the last run. Choose the RHOB and PEF method, switch the VPYR column "
                "on, apply and run.")

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
        self.basis_label.setText(
            f"This zone reads the {'sand-lamina' if basis == 'sand' else 'bulk'} porosity and "
            "shale volume in the Sw models. The sand basis needs the Thomas-Stieber result; "
            "samples without it fall back to the bulk values and are counted. With the bulk "
            "basis after the laminated correction, laminar shale is counted twice by the "
            "Indonesian and Simandoux models.")
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
            ("Suggested Sw model after these corrections: " + " or ".join(models) + ". ")
            if models else "")
        self.suggestion_label.setText(
            self.suggestion_label.text()
            + "The primary Sw model is a project parameter; Apply does not change it.")
        self._info_hint(prm)

    def _info_hint(self, prm):
        text = ""
        guard = lrlc_summary(self.ds).get("guard") or {}
        if guard.get("enabled", True) and "laminated" not in resolve_lrlc_steps(prm):
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


def resolve_lrlc_steps(prm: dict) -> List[str]:
    """Names of the registered steps listed in a resolved ladder, in chain order."""
    specs, _unknown = chain.resolve_steps(prm.get("rt_steps") or [])
    return [s.name for s in specs]


def chain_sorted(names: List[str]) -> List[str]:
    order = {s.name: i for i, s in enumerate(chain.available_steps())}
    return sorted(dict.fromkeys(names), key=lambda n: order.get(n, len(order)))

