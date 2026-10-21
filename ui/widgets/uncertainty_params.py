"""Parameters page "Uncertainty": the Monte Carlo setup (one distribution per parameter).

Edits write ``model.project.uncertainty`` at once and mark the session dirty. They never touch
the scoped parameters, so no well goes stale. Relative offsets are stored as fractions and shown
in percent; additive offsets are absolute.
"""
import random

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from modules.uncertainty import (
    DEFAULT_MODES, KINDS, MODES, N_MAX, N_MIN, NOT_VARIED, PARAM_ORDER, SAMPLINGS,
    SUGGESTED_RANGES, rw_quality_text, validate_config,
)
from themes.helpers import set_status

PARAM_LABELS = {
    "a": "a", "m": "m", "n": "n", "rw": "Rw (ohm·m)", "rsh": "Rsh (ohm·m)",
    "vsh_cutoff": "Vsh cutoff", "phi_cutoff": "PHIE cutoff", "sw_cutoff": "Sw cutoff",
}
_ADDITIVE_UNIT = {"rw": " ohm·m", "rsh": " ohm·m"}
_KIND_TEXT = {"triangular": "Triangular", "normal": "Normal", "uniform": "Uniform"}
_MODE_TEXT = {"relative": "Relative", "additive": "Additive"}
_SAMPLING_TEXT = {"lhs": "Latin hypercube", "random": "Random"}
# Which spin boxes each kind uses.
_USES = {"triangular": ("low", "mid", "high"), "normal": ("mid", "sd"),
         "uniform": ("low", "high")}
_FIELDS = ("low", "mid", "high", "sd")
RHO_PAIR = ("m", "n")
_RHO_TIP = "Rank correlation between the m and n draws (0 = independent)"
_RHO_OFF_TIP = _RHO_TIP + ". Ignored while m or n is not enabled."
INFO_TEXT = ("Applied to every well and zone as a change of the resolved value. "
             f"Not varied: {NOT_VARIED}.")


class _Row:
    def __init__(self, name):
        self.name = name
        self.enable = QCheckBox()
        self.kind = QComboBox()
        for k in KINDS:
            self.kind.addItem(_KIND_TEXT[k], k)
        self.mode = QComboBox()
        for m in MODES:
            self.mode.addItem(_MODE_TEXT[m], m)
        self.spins = {}
        for f in _FIELDS:
            spin = QDoubleSpinBox()
            spin.setRange(-1000.0, 1000.0)
            spin.setSingleStep(1.0)
            spin.setKeyboardTracking(False)
            self.spins[f] = spin
        self.enable.setToolTip(f"Vary {PARAM_LABELS[name]} in the Monte Carlo run")

    def current_mode(self):
        return self.mode.currentData()

    def current_kind(self):
        return self.kind.currentData()

    def format_spins(self):
        """Decimals, suffix and step follow the mode (percent or absolute units)."""
        if self.current_mode() == "relative":
            decimals, suffix, step = 2, " %", 1.0
        else:
            decimals, suffix, step = 4, _ADDITIVE_UNIT.get(self.name, ""), 0.01
        for spin in self.spins.values():
            spin.setDecimals(decimals)
            spin.setSuffix(suffix)
            spin.setSingleStep(step)

    def update_enabled(self):
        used = _USES.get(self.current_kind(), ())
        on = self.enable.isChecked()
        self.kind.setEnabled(on)
        self.mode.setEnabled(on)
        for f, spin in self.spins.items():
            spin.setEnabled(on and f in used)


class UncertaintyParamsPage(QWidget):
    """The Uncertainty page; ``config_changed`` fires after every user edit."""

    config_changed = pyqtSignal()

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self._loading = False
        self._rows = {}
        self._build()
        self.load_from_config()

    # ---- layout ----
    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        for col, text in enumerate(("", "Parameter", "Kind", "Mode", "Low", "Mid", "High", "Sd")):
            if text:
                label = QLabel(text.upper())
                label.setObjectName("SectionLabel")
                grid.addWidget(label, 0, col)
        for r, name in enumerate(PARAM_ORDER, start=1):
            row = _Row(name)
            self._rows[name] = row
            grid.addWidget(row.enable, r, 0)
            grid.addWidget(QLabel(PARAM_LABELS[name]), r, 1)
            grid.addWidget(row.kind, r, 2)
            grid.addWidget(row.mode, r, 3)
            for c, f in enumerate(_FIELDS, start=4):
                grid.addWidget(row.spins[f], r, c)
            row.enable.toggled.connect(lambda _c, n=name: self._on_row_edit(n))
            row.kind.currentIndexChanged.connect(lambda _i, n=name: self._on_row_edit(n))
            row.mode.currentIndexChanged.connect(lambda _i, n=name: self._on_mode_edit(n))
            for spin in row.spins.values():
                spin.valueChanged.connect(lambda _v, n=name: self._on_row_edit(n))
        layout.addLayout(grid)

        self.suggest_btn = QPushButton("Suggested ranges")
        self.suggest_btn.setToolTip("Fill triangular ranges with the default modes. "
                                    "Nothing is enabled.")
        self.suggest_btn.clicked.connect(self.apply_suggested_ranges)
        suggest = QHBoxLayout()
        suggest.addWidget(self.suggest_btn)
        suggest.addStretch()
        layout.addLayout(suggest)

        self.n_spin = QSpinBox()
        self.n_spin.setRange(N_MIN, N_MAX)
        self.n_spin.setKeyboardTracking(False)
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 2_147_483_647)
        self.seed_spin.setKeyboardTracking(False)
        self.new_seed_btn = QPushButton("New seed")
        self.new_seed_btn.clicked.connect(self._on_new_seed)
        self.sampling_combo = QComboBox()
        for s in SAMPLINGS:
            self.sampling_combo.addItem(_SAMPLING_TEXT[s], s)
        self.rho_spin = QDoubleSpinBox()
        self.rho_spin.setRange(-0.95, 0.95)
        self.rho_spin.setSingleStep(0.05)
        self.rho_spin.setDecimals(2)
        self.rho_spin.setKeyboardTracking(False)
        self.rho_spin.setToolTip(_RHO_TIP)
        opts = QGridLayout()
        opts.setHorizontalSpacing(8)
        opts.addWidget(QLabel("N"), 0, 0)
        opts.addWidget(self.n_spin, 0, 1)
        opts.addWidget(QLabel("Seed"), 0, 2)
        opts.addWidget(self.seed_spin, 0, 3)
        opts.addWidget(self.new_seed_btn, 0, 4)
        opts.addWidget(QLabel("Sampling"), 1, 0)
        opts.addWidget(self.sampling_combo, 1, 1)
        opts.addWidget(QLabel("rho(m, n)"), 1, 2)
        opts.addWidget(self.rho_spin, 1, 3)
        opts.setColumnStretch(5, 1)
        layout.addLayout(opts)
        for signal in (self.n_spin.valueChanged, self.seed_spin.valueChanged,
                       self.sampling_combo.currentIndexChanged, self.rho_spin.valueChanged):
            signal.connect(self._on_global_edit)

        self.info_label = QLabel(INFO_TEXT)
        self.info_label.setWordWrap(True)
        set_status(self.info_label, "muted")
        layout.addWidget(self.info_label)
        self.rw_quality_label = QLabel("")
        self.rw_quality_label.setWordWrap(True)
        layout.addWidget(self.rw_quality_label)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    # ---- config helpers ----
    @property
    def config(self):
        return self.model.project.uncertainty

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_rw_quality()

    def _refresh_rw_quality(self):
        """Note beside the Rw distribution on how the last run's auto Rw was estimated."""
        result = getattr(self.model.project, "uncertainty_result", None)
        text = rw_quality_text(result)
        if text:
            text = f"{text} (last run)"
        elif result is None:
            text = "Auto Rw quality is shown here after a run."
        self.rw_quality_label.setText(text)    # a run with a fixed Rw has nothing to show
        set_status(self.rw_quality_label, "muted")

    def _refresh_rho_enabled(self):
        both = all(self._rows[n].enable.isChecked() for n in RHO_PAIR)
        self.rho_spin.setEnabled(both)
        self.rho_spin.setToolTip(_RHO_TIP if both else _RHO_OFF_TIP)

    # ---- model -> widgets ----
    def load_from_config(self):
        """Show ``model.project.uncertainty``; never writes the model."""
        cfg = self.config
        self._loading = True
        try:
            for name, row in self._rows.items():
                d = cfg.distributions.get(name)
                if d is None:
                    continue
                row.enable.setChecked(bool(d.enabled))
                row.kind.setCurrentIndex(max(row.kind.findData(d.kind), 0))
                row.mode.setCurrentIndex(max(row.mode.findData(d.mode), 0))
                row.format_spins()
                scale = 100.0 if d.mode == "relative" else 1.0
                row.spins["low"].setValue(d.low * scale)
                row.spins["mid"].setValue(d.mid * scale)
                row.spins["high"].setValue(d.high * scale)
                row.spins["sd"].setValue(d.sd * scale)
                row.update_enabled()
            self.n_spin.setValue(int(cfg.n))
            self.seed_spin.setValue(int(cfg.seed))
            self.sampling_combo.setCurrentIndex(max(self.sampling_combo.findData(cfg.sampling), 0))
            self.rho_spin.setValue(float(cfg.correlations.get(RHO_PAIR, 0.0)))
        finally:
            self._loading = False
        self._refresh_status()
        self._refresh_rw_quality()

    # ---- widgets -> model ----
    def _write_row(self, name):
        row, d = self._rows[name], self.config.distributions[name]
        d.enabled = row.enable.isChecked()
        d.kind = row.current_kind()
        d.mode = row.current_mode()
        scale = 0.01 if d.mode == "relative" else 1.0
        d.low = row.spins["low"].value() * scale
        d.mid = row.spins["mid"].value() * scale
        d.high = row.spins["high"].value() * scale
        d.sd = row.spins["sd"].value() * scale

    def _changed(self):
        self._refresh_status()
        self.model.mark_dirty()
        self.config_changed.emit()

    def _on_row_edit(self, name):
        if self._loading:
            return
        self._rows[name].update_enabled()
        self._write_row(name)
        self._changed()

    def _on_mode_edit(self, name):
        """Stored fractions stay as they are; only the display unit changes."""
        if self._loading:
            return
        row = self._rows[name]
        self.config.distributions[name].mode = row.current_mode()
        self._loading = True
        try:
            row.format_spins()
            self._show_row(name)
        finally:
            self._loading = False
        self._changed()

    def _show_row(self, name):
        row, d = self._rows[name], self.config.distributions[name]
        scale = 100.0 if d.mode == "relative" else 1.0
        for f in _FIELDS:
            row.spins[f].setValue(getattr(d, f) * scale)

    def _on_global_edit(self, *_args):
        if self._loading:
            return
        cfg = self.config
        cfg.n = self.n_spin.value()
        cfg.seed = self.seed_spin.value()
        cfg.sampling = self.sampling_combo.currentData()
        rho = round(self.rho_spin.value(), 2)
        if rho == 0.0:
            cfg.correlations.pop(RHO_PAIR, None)
        else:
            cfg.correlations[RHO_PAIR] = rho
        self._changed()

    def _on_new_seed(self):
        self.seed_spin.setValue(random.randint(0, 2_147_483_647))

    def apply_suggested_ranges(self):
        """Triangular suggested ranges with the default modes; enabled flags are kept."""
        for name, (low, mid, high) in SUGGESTED_RANGES.items():
            d = self.config.distributions[name]
            d.kind, d.mode = "triangular", DEFAULT_MODES[name]
            d.low, d.mid, d.high = low, mid, high
        self.load_from_config()
        self._changed()

    def _refresh_status(self):
        self._refresh_rho_enabled()
        # Nothing enabled is the normal starting state, not an error (the menu tooltip says it).
        errors = validate_config(self.config) if self.config.enabled_names() else []
        self.status_label.setText("\n".join(errors))
        self.status_label.setVisible(bool(errors))
        set_status(self.status_label, "warning" if errors else None)
