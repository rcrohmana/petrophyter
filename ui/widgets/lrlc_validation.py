"""Validation panel of the LRLC Workbench: pay before and after the corrections.

Reads ``summary["lrlc"]["validation"]`` of the last run (net pay, average Sw and HCPV with the
measured Rt, the single Qv and the bulk basis against the corrected run), the saturation-height
comparison when there is one, and a depth plot of the Sw curves. Read-only.
"""

from typing import Optional

import numpy as np
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QGroupBox, QVBoxLayout, QWidget

from themes.colors import get_plot_chrome, get_plot_color

from ..tabs.rock_typing_tab import fit_table_height
from .lrlc_common import fmt, item, make_table, note, zone_title
from .lrlc_diagnosis import lrlc_summary
from .lrlc_pickett import forward_wheel_to_scroll, zone_labels
from .plot_widget import PlotWidget

PAY_COLUMNS = ("Zone", "Net pay before (ft)", "Net pay after (ft)", "Change (ft)",
               "Avg Sw before", "Avg Sw after", "HCPV before (ft)", "HCPV after (ft)")
SHF_COLUMNS = ("Zone", "Samples", "Bias before", "Bias after", "RMSE before", "RMSE after")
PLOT_MIN_HEIGHT = 420
EMPTY_TEXT = ("Run the analysis with a correction step, a Qv estimate or the sand basis switched "
              "on to compare pay before and after.")


class ValidationPanel(QWidget):
    """Before / after tables and the Sw depth plot. Public: ``set_context``, ``refresh_theme``."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = None
        self.ds = None
        self.zone: Optional[str] = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.status_label = note("")
        root.addWidget(self.status_label)
        self.basis_label = note("")
        root.addWidget(self.basis_label)
        self.pay_label = note("")
        root.addWidget(self.pay_label)

        self.pay_group = QGroupBox("Pay before and after the corrections")
        pl = QVBoxLayout(self.pay_group)
        self.pay_table = make_table(PAY_COLUMNS)
        pl.addWidget(self.pay_table)
        root.addWidget(self.pay_group)

        self.shf_group = QGroupBox("Resistivity Sw against saturation-height Sw")
        sl = QVBoxLayout(self.shf_group)
        self.shf_note = note("An improvement is a smaller bias and a smaller RMSE after the "
                             "correction.")
        sl.addWidget(self.shf_note)
        self.shf_table = make_table(SHF_COLUMNS)
        sl.addWidget(self.shf_table)
        root.addWidget(self.shf_group)

        self.plot_group = QGroupBox("Sw before and after")
        gl = QVBoxLayout(self.plot_group)
        self.plot = PlotWidget(figsize=(6, 6))
        self.plot.setMinimumHeight(PLOT_MIN_HEIGHT)
        self.plot.canvas.installEventFilter(self)
        gl.addWidget(self.plot)
        root.addWidget(self.plot_group)
        root.addStretch(1)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel and forward_wheel_to_scroll(self, event):
            return True
        return super().eventFilter(obj, event)

    # ----------------------------------------------------------------- context
    def set_context(self, model, ds, zone: Optional[str] = None):
        self.model = model
        self.ds = ds
        self.zone = zone or None
        self._render()

    def refresh_theme(self):
        self.plot.update_theme_colors()
        self._render()

    # ------------------------------------------------------------------ render
    def _render(self):
        val = lrlc_summary(self.ds).get("validation")
        shown = bool(val)
        for w in (self.basis_label, self.pay_label, self.pay_group, self.plot_group):
            w.setVisible(shown)
        self.shf_group.setVisible(bool(shown and val.get("shf")))
        if not shown:
            self.status_label.setText(
                "No well loaded" if self.ds is None else
                (EMPTY_TEXT if getattr(self.ds, "results", None) is not None
                 else "Run the analysis first. " + EMPTY_TEXT))
            self.pay_table.setRowCount(0)
            self.shf_table.setRowCount(0)
            ax = self.plot.get_axes()
            ax.set_xticks([])
            ax.set_yticks([])
            self.plot.canvas.draw_idle()
            return
        self.status_label.setText("Compared with the Sw this well gives without the corrections.")
        self.basis_label.setText(f"Before: {val.get('basis', '')}. After: the current settings.")
        held = int(val.get("n_shf_held") or 0)
        if val.get("pay_sw") == "SHF where available":
            self.pay_label.setText(
                f"Pay Sw: saturation height where available. The correction changes pay only at "
                f"the other samples; {held} sample(s) are held by saturation height.")
        else:
            self.pay_label.setText("Pay Sw: resistivity Sw.")
        self._fill_pay(val)
        self._fill_shf(val.get("shf") or {})
        self._draw_plot()

    def _fill_pay(self, val):
        rows = [(None, val.get("well") or {})] + [(z.get("zone"), z) for z in val.get("zones", [])]
        self.pay_table.setRowCount(len(rows))
        for r, (zone, row) in enumerate(rows):
            delta = row.get("delta")
            values = (zone_title(zone), fmt(row.get("net_pay_base"), 1), fmt(row.get("net_pay"), 1),
                      ("" if delta is None or not np.isfinite(delta) else f"{delta:+.1f}"),
                      fmt(row.get("avg_sw_pay_base"), 3), fmt(row.get("avg_sw_pay"), 3),
                      fmt(row.get("hcpv_net_pay_base"), 3), fmt(row.get("hcpv_net_pay"), 3))
            for c, text in enumerate(values):
                self.pay_table.setItem(r, c, item(text, align_right=c > 0))
        fit_table_height(self.pay_table)

    def _fill_shf(self, shf):
        rows = []
        if shf.get("well"):
            rows.append((None, shf["well"].get("base"), shf["well"].get("corrected")))
        for z in shf.get("zones", []):
            rows.append((z.get("zone"), z.get("base"), z.get("corrected")))
        self.shf_table.setRowCount(len(rows))
        for r, (zone, base, corrected) in enumerate(rows):
            base, corrected = base or {}, corrected or {}
            values = (zone_title(zone), str(base.get("n", "")), fmt(base.get("bias"), 3),
                      fmt(corrected.get("bias"), 3), fmt(base.get("rmse"), 3),
                      fmt(corrected.get("rmse"), 3))
            for c, text in enumerate(values):
                self.shf_table.setItem(r, c, item(text, align_right=c > 0))
        fit_table_height(self.shf_table)

    def _draw_plot(self):
        res = self.ds.results
        ax = self.plot.get_axes()
        chrome = get_plot_chrome()
        if res is None or "SW_BASE" not in res.columns:
            ax.text(0.5, 0.5, "No baseline Sw in the last run", ha="center", va="center",
                    transform=ax.transAxes, color=chrome["text"])
            self.plot.canvas.draw_idle()
            return
        mask = np.ones(len(res), dtype=bool)
        if self.zone is not None and "ZONE" in res.columns:
            mask = zone_labels(res) == self.zone
        depth = (res["DEPTH"].to_numpy(dtype=float) if "DEPTH" in res.columns
                 else np.arange(len(res), dtype=float))[mask]
        for column, key, label, style in (
                ("SW_BASE", "SW_BASE", "Sw before", "--"), ("SW", "SW", "Sw after", "-"),
                ("SW_SHF", "SW_SHF", "Sw saturation height", "-")):
            if column in res.columns:
                ax.plot(res[column].to_numpy(dtype=float)[mask], depth,
                        color=get_plot_color(key), ls=style, lw=1.2, label=label)
        ax.set_xlim(0.0, 1.0)
        if len(depth):
            ax.set_ylim(np.nanmax(depth), np.nanmin(depth))
        ax.set_xlabel("Sw (v/v)")
        ax.set_ylabel("Depth")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="lower right", fontsize=8)
        self.plot.canvas.draw_idle()
