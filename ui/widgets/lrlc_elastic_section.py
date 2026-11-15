"""Elastic flag section of the LRLC Workbench (Screening content column).

The project switch of the elastic screening, the curves it uses, the per-zone result of the
last run, two small crossplots of the relative attributes against PHIE coloured by the flag,
and the ``el_*`` thresholds as Set here / Inherit rows. The section writes nothing itself: the
switch is a plain check box the owner wires to the service, and Set here / Inherit are signals
the owner turns into ladder writes (it knows the scope). It never runs the analysis.
"""

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd
from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from modules.lrlc.config import (
    LEVEL_BUILTIN,
    LRLC_CHOICES,
    LRLC_PARAM_DEFAULTS,
    LRLC_RANGES,
    WELL_ONLY_KEYS,
)
from modules.lrlc.methods import METHOD_TEXT
from themes.colors import get_plot_chrome, get_plot_color
from themes.helpers import set_status, set_variant
from ..tabs.rock_typing_tab import fit_table_height
from .fold_section import FoldSection
from .lrlc_common import fmt, item, make_table, note, zone_title
from .lrlc_pickett import forward_wheel_to_scroll, zone_labels
from .method_box import MethodReferenceBox
from .plot_widget import PlotWidget

logger = logging.getLogger(__name__)

PLOT_MIN_HEIGHT = 230
NO_INTERVAL = -1.0       # interval spin minimum: shows "none"

DEFAULTS_NOTE = ("The thresholds are design defaults. Calibrate them on wells with known "
                 "fluids before relying on the flag.")
ROLLING_NOTE = ("The plots divide by the median shale of each zone; with the rolling baseline "
                "the run divides by the shale median around each depth, so single points can "
                "differ slightly.")
NOT_RUN = ("Switch the flag on, then run the analysis. The flag adds one point to the "
           "screening score and changes no Sw, pay or LRLC flag.")
SKIPPED_TEXT = {"units": "DT or DTS look like us/m; convert them to us/ft."}

ZONE_COLUMNS = ("Zone", "Net samples", "Flagged samples", "Flagged (ft)", "Invalid samples",
                "Shale AI", "Shale Vp/Vs", "Baseline")

CHOICE_TEXT = {
    "rolling": "Rolling median", "zone": "Zone median", "window": "Shale interval",
    "well": "Well", "both": "AI and Vp/Vs", "ai": "AI only", "vpvs": "Vp/Vs only",
}

# (key, label, kind, decimals, step); ranges come from the configuration.
ELASTIC_ROWS = (
    ("el_baseline_mode", "Shale baseline", "choice", 0, 0),
    ("el_shale_window_ft", "Rolling window (ft)", "float", 0, 10.0),
    ("el_shale_min_n", "Minimum shale samples", "int", 0, 1),
    ("el_vsh_shale", "Shale Vsh limit (at least)", "float", 2, 0.05),
    ("el_shale_interval", "Shale interval, top and bottom (ft)", "interval", 1, 10.0),
    ("el_sw_wet", "Wet-sample Sw (at least)", "float", 2, 0.05),
    ("el_wet_interval", "Water interval, top and bottom (ft)", "interval", 1, 10.0),
    ("el_trend_scope", "Wet trend scope", "choice", 0, 0),
    ("el_min_wet_n", "Minimum wet samples", "int", 0, 10),
    ("el_min_phi_span", "Minimum PHIE span of the wet samples", "float", 3, 0.01),
    ("el_ai_drop", "AI drop below the wet trend", "float", 3, 0.005),
    ("el_vpvs_drop", "Vp/Vs drop below the wet trend", "float", 3, 0.005),
    ("el_mode", "Attributes that must deviate", "choice", 0, 0),
)
ROW_BY_KEY = {row[0]: row for row in ELASTIC_ROWS}


def _choice_label(value) -> str:
    return CHOICE_TEXT.get(value, str(value))


def _shown(key, value) -> str:
    """A resolved value as text."""
    kind = ROW_BY_KEY[key][2]
    if kind == "choice":
        return _choice_label(value)
    if kind == "interval":
        try:
            return f"{float(value[0]):g} to {float(value[1]):g} ft"
        except (TypeError, ValueError, IndexError, KeyError):
            return "none"
    return f"{value:g}" if value is not None else "none"


def _section_label(text) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("SectionLabel")
    return label


def _subsection_label(text) -> QLabel:
    label = QLabel(text)
    label.setObjectName("SubsectionLabel")
    return label


class ElasticSection(QWidget):
    """The Elastic flag section. Signals: ``set_here_requested(key, value)``,
    ``inherit_requested(key)`` and ``curves_requested()`` (the link to Curves)."""

    set_here_requested = pyqtSignal(str, object)
    inherit_requested = pyqtSignal(str)
    curves_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = None
        self.ds = None
        self.zone: Optional[str] = None
        self._drops = {"el_ai_drop": 0.05, "el_vpvs_drop": 0.03}
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 12, 0, 0)
        v.setSpacing(6)

        v.addWidget(_section_label("Elastic flag"))
        self.enable_check = QCheckBox("Compute the elastic flag on Run")
        self.enable_check.setToolTip(
            "Adds AI, VPVS and ELASTIC_FLAG, and one point to LRLC_SCORE where the flag is set. "
            "Changes no Sw, pay or LRLC flag. Off by default.")
        v.addWidget(self.enable_check)
        self.intro_note = note(NOT_RUN)
        v.addWidget(self.intro_note)

        self.curves_label = note("")
        v.addWidget(self.curves_label)
        warn = QHBoxLayout()
        self.warning_label = note("", "warning")
        warn.addWidget(self.warning_label, 1)
        self.curves_link = QPushButton("Go to Curves")
        set_variant(self.curves_link, "link")
        self.curves_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.curves_link.clicked.connect(self.curves_requested.emit)
        warn.addWidget(self.curves_link)
        self.warning_box = QWidget()
        self.warning_box.setLayout(warn)
        warn.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.warning_box)

        self.result_label = note("")
        v.addWidget(self.result_label)
        self.zone_table = make_table(ZONE_COLUMNS)
        v.addWidget(self.zone_table)

        self.plot_box = QWidget()
        pv = QVBoxLayout(self.plot_box)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.addWidget(_subsection_label("Relative AI and Vp/Vs against PHIE (net reservoir)"))
        self.plot = PlotWidget(show_toolbar=False, figsize=(8, 3))
        self.plot.setMinimumHeight(PLOT_MIN_HEIGHT)
        self.plot.canvas.installEventFilter(self)
        pv.addWidget(self.plot)
        self.plot_note = note("")
        pv.addWidget(self.plot_note)
        v.addWidget(self.plot_box)
        self.plot_box.setVisible(False)

        self.defaults_note = note(DEFAULTS_NOTE)
        v.addWidget(self.defaults_note)

        self.advanced = FoldSection("Advanced settings")
        v.addWidget(self.advanced)
        adv = self.advanced.body_layout
        adv.setSpacing(6)
        self.rows: Dict[str, dict] = {}
        for key, text, kind, decimals, step in ELASTIC_ROWS:
            adv.addWidget(QLabel(text))
            line = QHBoxLayout()
            widgets = self._make_input(key, kind, decimals, step)
            for w in widgets:
                line.addWidget(w, 1)
            set_btn = QPushButton("Set here")
            inherit_btn = QPushButton("Inherit")
            line.addWidget(set_btn)
            line.addWidget(inherit_btn)
            adv.addLayout(line)
            source = note("")
            adv.addWidget(source)
            set_btn.clicked.connect(lambda _=False, k=key: self._on_set_here(k))
            inherit_btn.clicked.connect(lambda _=False, k=key: self.inherit_requested.emit(k))
            self.rows[key] = {"inputs": widgets, "source": source, "set": set_btn,
                              "inherit": inherit_btn, "kind": kind}
        self.write_label = note("")
        v.addWidget(self.write_label)

        self.method_box = MethodReferenceBox(compact=True)
        self.method_box.set_method(METHOD_TEXT["elastic"])
        v.addWidget(self.method_box)
        self._render_empty()

    # ------------------------------------------------------------------ inputs
    @staticmethod
    def _make_input(key, kind, decimals, step):
        if kind == "choice":
            combo = QComboBox()
            for value in LRLC_CHOICES[key]:
                combo.addItem(_choice_label(value), value)
            return [combo]
        lo, hi = LRLC_RANGES.get(key, (0.0, 100000.0))
        if kind == "int":
            spin = QSpinBox()
            spin.setRange(int(lo), int(hi))
            spin.setSingleStep(int(step))
            return [spin]
        if kind == "interval":
            spins = []
            for _ in range(2):
                spin = QDoubleSpinBox()
                spin.setRange(NO_INTERVAL, 100000.0)
                spin.setDecimals(decimals)
                spin.setSingleStep(step)
                spin.setSpecialValueText("none")
                spin.setValue(NO_INTERVAL)
                spins.append(spin)
            return spins
        spin = QDoubleSpinBox()
        spin.setRange(float(lo), float(hi))
        spin.setDecimals(decimals)
        spin.setSingleStep(step)
        return [spin]

    def row_value(self, key):
        """The value the input of ``key`` shows, as ``set_param`` takes it."""
        row = self.rows[key]
        kind, inputs = row["kind"], row["inputs"]
        if kind == "choice":
            return inputs[0].currentData()
        if kind == "interval":
            top, bottom = inputs[0].value(), inputs[1].value()
            if top <= NO_INTERVAL + 1e-9 and bottom <= NO_INTERVAL + 1e-9:
                return None
            return [top, bottom]
        return inputs[0].value()

    def _set_input(self, key, value):
        row = self.rows[key]
        kind, inputs = row["kind"], row["inputs"]
        if kind == "choice":
            i = inputs[0].findData(value)
            if i >= 0:
                inputs[0].setCurrentIndex(i)
        elif kind == "interval":
            try:
                inputs[0].setValue(float(value[0]))
                inputs[1].setValue(float(value[1]))
            except (TypeError, ValueError, IndexError, KeyError):
                inputs[0].setValue(NO_INTERVAL)
                inputs[1].setValue(NO_INTERVAL)
        elif kind == "int":
            inputs[0].setValue(int(value))
        else:
            inputs[0].setValue(float(value))

    def _on_set_here(self, key):
        self.set_here_requested.emit(key, self.row_value(key))

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel and forward_wheel_to_scroll(self, event):
            return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------ display
    def set_resolved(self, sources, writable: bool, zone_scope: bool):
        """Show the resolved value and its source of every ``el_*`` key; ``zone_scope`` marks
        that the selected scope is a zone (well-wide keys are then written to the default)."""
        changed, set_somewhere = 0, False
        for key, row in self.rows.items():
            value, src = sources[key]
            changed += value != LRLC_PARAM_DEFAULTS.get(key)
            set_somewhere = set_somewhere or src != LEVEL_BUILTIN
            self._set_input(key, value)
            text = f"Resolved: {_shown(key, value)} ({src})"
            if zone_scope and key in WELL_ONLY_KEYS:
                text += "; well-wide setting, Set here writes the default"
            row["source"].setText(text)
            row["set"].setEnabled(writable)
            row["inherit"].setEnabled(writable)
        self.advanced.set_changed_count(changed)
        if changed or set_somewhere:
            self.advanced.set_expanded(True)

    def show_write_result(self, text: str, status: str = "muted"):
        self.write_label.setText(text)
        set_status(self.write_label, status)
        self.write_label.setVisible(bool(text))

    def set_enabled_state(self, on: bool):
        was = self.enable_check.blockSignals(True)
        self.enable_check.setChecked(bool(on))
        self.enable_check.blockSignals(was)

    def set_context(self, model, ds, zone: Optional[str], summary: dict, drops: dict):
        """Point the section at the active well, the selected zone, the LRLC summary of the
        last run and the resolved drop thresholds."""
        self.model, self.ds, self.zone = model, ds, zone
        self._drops.update({k: float(v) for k, v in (drops or {}).items()
                            if k in self._drops and v is not None})
        self._render_curves()
        elastic = (summary or {}).get("elastic") or {}
        self.intro_note.setVisible(not elastic.get("counts"))
        self._render_result(elastic)
        self._replot(elastic)

    def _render_empty(self):
        self.curves_label.setText("")
        self.warning_box.setVisible(False)
        self.result_label.setVisible(False)
        self.zone_table.setVisible(False)
        self.plot_box.setVisible(False)
        self.show_write_result("")

    @staticmethod
    def _usable(name) -> Optional[str]:
        return None if name in (None, "", "None") else str(name)

    def curve_names(self) -> Dict[str, Optional[str]]:
        """Resolved names of DT, DTS and RHOB for the active well (None when missing)."""
        ds = self.ds
        out = {"DT": None, "DTS": None, "RHOB": None}
        if ds is None:
            return out
        mapping = getattr(ds, "curve_mapping", None) or {}
        out["DT"] = self._usable(mapping.get("DT"))
        out["RHOB"] = self._usable(mapping.get("RHOB"))
        assigned = getattr(ds, "lrlc_curves", None) or {}
        if "DTS" in assigned:
            out["DTS"] = self._usable(assigned["DTS"])
        else:
            try:
                from modules.las_parser import find_curve
                out["DTS"] = find_curve(list(ds.las_data.columns), "DTS")
            except Exception:       # a well still loading has no log yet
                out["DTS"] = None
        return out

    def _render_curves(self):
        if self.ds is None:
            self.curves_label.setText("")
            self.warning_box.setVisible(False)
            return
        names = self.curve_names()
        shown = ", ".join(f"{role}: {names[role] or 'not mapped'}"
                          for role in ("DT", "DTS", "RHOB"))
        self.curves_label.setText(f"Curves used: {shown}")
        missing = [role for role in ("DT", "DTS", "RHOB") if not names[role]]
        if "DTS" in missing:
            self.warning_label.setText(
                "No DTS curve is assigned, so the elastic flag is skipped. Assign the shear "
                "slowness under Curves.")
            self.curves_link.setVisible(True)
        elif missing:
            self.warning_label.setText(
                f"{' and '.join(missing)} is not mapped, so the elastic flag is skipped. Map it "
                "on the Parameters window.")
            self.curves_link.setVisible(False)
        self.warning_box.setVisible(bool(missing))

    def _render_result(self, elastic: dict):
        counts = elastic.get("counts") or {}
        skipped = elastic.get("skipped")
        if skipped:
            text = "The last run skipped the elastic flag"
            reason = SKIPPED_TEXT.get(skipped, str(skipped))
            self.result_label.setText(f"{text}: {reason}")
            set_status(self.result_label, "warning")
            self.result_label.setVisible(True)
            self.zone_table.setVisible(False)
            return
        if not counts:
            self.result_label.setVisible(False)
            self.zone_table.setVisible(False)
            return
        wet = elastic.get("wet") or {}
        parts = [f"{counts.get('flag', 0)} flagged of {counts.get('net', 0)} net reservoir "
                 f"samples; {counts.get('unevaluable', 0)} not evaluable"]
        if wet.get("ai") and wet.get("vpvs"):
            parts.append(
                f"wet trend from {wet.get('n', 0)} samples ({'water interval' if wet.get('source') == 'interval' else 'Sw rule'}): "
                f"AI R2 {fmt(wet['ai'].get('r2'), 2)}, Vp/Vs R2 {fmt(wet['vpvs'].get('r2'), 2)}")
            set_status(self.result_label, "muted")
        else:
            parts.append("no wet trend, nothing is flagged (too few wet samples or too narrow a "
                         "porosity span)")
            set_status(self.result_label, "warning")
        self.result_label.setText("Last run: " + "; ".join(parts) + ".")
        self.result_label.setVisible(True)
        base = {r.get("zone"): r for r in (elastic.get("baseline") or {}).get("zones") or []}
        rows = elastic.get("zones") or []
        self.zone_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            b = base.get(row.get("zone")) or {}
            values = (zone_title(row.get("zone")), row.get("n_net"), row.get("n_flag"),
                      fmt(row.get("thickness_flag_ft"), 1), row.get("n_invalid"),
                      fmt(b.get("ai_shale_median"), 0), fmt(b.get("vpvs_shale_median"), 2),
                      (f"{b.get('fallback')} median fallback" if b.get("fallback")
                       else (elastic.get("baseline") or {}).get("mode", "")))
            for c, value in enumerate(values):
                self.zone_table.setItem(r, c, item(value, align_right=c in (1, 2, 3, 4, 5, 6)))
        self.zone_table.setVisible(bool(rows))
        fit_table_height(self.zone_table)

    # ------------------------------------------------------------------ plots
    def plot_frame(self, elastic: dict) -> Optional[pd.DataFrame]:
        """Net reservoir samples of the selected zone with ``AI_REL`` and ``VPVS_REL`` from the
        results and the stored shale medians; None when the last run has no elastic flag."""
        ds = self.ds
        results = getattr(ds, "results", None) if ds is not None else None
        if results is None or len(results) == 0 or not (elastic or {}).get("counts"):
            return None
        for col in ("AI", "VPVS", "PHIE", "ELASTIC_FLAG"):
            if col not in results.columns:
                return None
        baseline = {r.get("zone"): r for r in (elastic.get("baseline") or {}).get("zones") or []}
        if not baseline:
            return None
        labels = zone_labels(results)
        labels = np.array(["WELL" if z in ("", None) else z for z in labels], dtype=object)
        ai_sh = np.full(len(results), np.nan)
        vp_sh = np.full(len(results), np.nan)
        only = next(iter(baseline.values())) if len(baseline) == 1 else None
        for z in set(labels.tolist()):
            row = baseline.get(z) or only
            if row is None:
                continue
            sel = labels == z
            ai_sh[sel] = row.get("ai_shale_median", np.nan)
            vp_sh[sel] = row.get("vpvs_shale_median", np.nan)
        num = lambda c: pd.to_numeric(results[c], errors="coerce").to_numpy(dtype=float)  # noqa: E731
        net = (num("NET_RES_FLAG") == 1) if "NET_RES_FLAG" in results.columns \
            else np.ones(len(results), dtype=bool)
        frame = pd.DataFrame({
            "PHIE": num("PHIE"), "AI_REL": num("AI") / ai_sh, "VPVS_REL": num("VPVS") / vp_sh,
            "FLAG": np.nan_to_num(num("ELASTIC_FLAG")) == 1, "ZONE": labels})
        frame = frame[net]
        if self.zone:
            frame = frame[frame["ZONE"] == self.zone]
        return frame

    def _replot(self, elastic: dict):
        frame = self.plot_frame(elastic)
        fig = self.plot.figure
        fig.clear()
        if frame is None:
            self.plot_box.setVisible(False)
            self.plot.canvas.draw_idle()
            return
        self.plot_box.setVisible(True)
        chrome = get_plot_chrome()
        flag_color = get_plot_color("ELASTIC_FLAG")
        wet = elastic.get("wet") or {}
        trends = (("AI_REL", "AI / AI shale", wet.get("ai"), ("a0", "a1"), "el_ai_drop"),
                  ("VPVS_REL", "Vp/Vs / Vp/Vs shale", wet.get("vpvs"), ("c0", "c1"),
                   "el_vpvs_drop"))
        for i, (col, label, fit, names, drop_key) in enumerate(trends, start=1):
            ax = fig.add_subplot(1, 2, i)
            self.plot._style_axes(ax)
            ok = np.isfinite(frame["PHIE"]) & np.isfinite(frame[col])
            rest, hit = frame[ok & ~frame["FLAG"]], frame[ok & frame["FLAG"]]
            ax.scatter(rest["PHIE"], rest[col], s=5, alpha=0.5, linewidths=0,
                       color=chrome["spine"], label="Not flagged", zorder=2)
            ax.scatter(hit["PHIE"], hit[col], s=7, alpha=0.8, linewidths=0, color=flag_color,
                       label="Flagged", zorder=3)
            if fit and ok.any():
                phi = np.linspace(float(frame.loc[ok, "PHIE"].min()),
                                  float(frame.loc[ok, "PHIE"].max()), 30)
                trend = fit[names[0]] + fit[names[1]] * phi
                ax.plot(phi, trend, color=chrome["text"], lw=1.2, label="Wet trend", zorder=4)
                ax.plot(phi, trend * (1.0 - self._drops[drop_key]), color=flag_color, lw=1.0,
                        ls="--", label="Threshold", zorder=4)
            ax.set_xlabel("PHIE (v/v)", fontsize=8)
            ax.set_ylabel(label, fontsize=8)
            ax.tick_params(labelsize=7)
            ax.grid(True, alpha=0.3)
            if i == 1:
                ax.legend(loc="best", fontsize=6)
        try:
            fig.tight_layout()
        except Exception:       # a very small canvas cannot be laid out
            logger.debug("elastic crossplot layout failed", exc_info=True)
        mode = (elastic.get("baseline") or {}).get("mode")
        self.plot_note.setText(ROLLING_NOTE if mode == "rolling" else "")
        self.plot_note.setVisible(mode == "rolling")
        self.plot.canvas.draw_idle()

    def refresh_theme(self):
        self.advanced.refresh_theme()
        self.plot.update_theme_colors()
        summary = {}
        if self.ds is not None:
            summary = (getattr(self.ds, "summary", None) or {}).get("lrlc") or {}
        self._replot(summary.get("elastic") or {})
