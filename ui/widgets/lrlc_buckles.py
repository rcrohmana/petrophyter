"""Buckles plot panel of the LRLC Workbench (Diagnosis > Buckles).

Sw versus porosity of the net-reservoir samples with constant-BVW hyperbolas, the water-free
samples marked, and a per-zone table. Read-only: nothing here changes the model.
"""

from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from modules.lrlc.methods import METHOD_TEXT
from themes.colors import get_plot_chrome, get_plot_color, get_rock_type_color
from themes.helpers import set_status

from .lrlc_pickett import forward_wheel_to_scroll, source_value, zone_labels, zone_sources
from .method_box import MethodReferenceBox
from .plot_widget import PlotWidget

PLOT_MIN_HEIGHT = 380
TABLE_COLUMNS = ("Zone", "Net samples", "Mean BVW (v/v)", "Mean Sw - Swirr",
                 "Water-free (ft)")
ALL_LABEL = "All zones"
NO_ZONE_LABEL = "All samples"


def _step(depth: np.ndarray) -> float:
    d = np.diff(depth[np.isfinite(depth)])
    d = d[d > 0]
    return float(np.median(d)) if d.size else 0.0


class BucklesPanel(QWidget):
    """Buckles plot and zone table. Public: ``set_context``, ``refresh_theme``."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = None
        self.ds = None
        self.zone: Optional[str] = None
        self.rows: List[Dict] = []
        self.line_values: List[float] = []
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        set_status(self.status_label, "muted")
        root.addWidget(self.status_label)

        body = QHBoxLayout()
        self.plot = PlotWidget(figsize=(8, 5))
        self.plot.setMinimumHeight(PLOT_MIN_HEIGHT)
        self.plot.canvas.installEventFilter(self)
        body.addWidget(self.plot, 3)

        self.table = QTableWidget(0, len(TABLE_COLUMNS))
        self.table.setHorizontalHeaderLabels(list(TABLE_COLUMNS))
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumWidth(360)
        body.addWidget(self.table, 2)
        root.addLayout(body, 1)

        self.method_box = MethodReferenceBox()
        self.method_box.set_method(METHOD_TEXT["buckles"])
        root.addWidget(self.method_box)

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

    # -------------------------------------------------------------------- data
    def _net_frame(self) -> Optional[pd.DataFrame]:
        ds = self.ds
        results = getattr(ds, "results", None)
        if results is None or len(results) == 0:
            return None
        df = results
        if "PHIE" not in df.columns or "SW" not in df.columns:
            return df.iloc[0:0]
        phie = pd.to_numeric(df["PHIE"], errors="coerce")
        sw = pd.to_numeric(df["SW"], errors="coerce")
        net = (pd.to_numeric(df["NET_RES_FLAG"], errors="coerce").fillna(0) == 1
               if "NET_RES_FLAG" in df.columns else pd.Series(True, index=df.index))
        out = pd.DataFrame({
            "DEPTH": (pd.to_numeric(df["DEPTH"], errors="coerce")
                      if "DEPTH" in df.columns else np.nan),
            "PHIE": phie, "SW": sw,
            "BVW": (pd.to_numeric(df["BVW"], errors="coerce") if "BVW" in df.columns
                    else phie * sw),
            "SWIRR": (pd.to_numeric(df["SWIRR"], errors="coerce") if "SWIRR" in df.columns
                      else np.nan),
            "WF": (pd.to_numeric(df["WATER_FREE_FLAG"], errors="coerce").fillna(0) == 1
                   if "WATER_FREE_FLAG" in df.columns else False),
            "ZONE": zone_labels(df),
        }, index=df.index)
        out = out[net & phie.notna() & sw.notna() & (phie > 0)]
        if self.zone:
            out = out[out["ZONE"] == self.zone]
        return out

    def _table_rows(self, df: pd.DataFrame, dz: float) -> List[Dict]:
        rows = []

        def summarise(name, part):
            wf = part["WF"].astype(bool)
            movable = (part["SW"] - part["SWIRR"]).dropna()
            rows.append({
                "zone": name,
                "n": int(len(part)),
                "mean_bvw": float(part["BVW"].mean()) if len(part) else float("nan"),
                "mean_movable": float(movable.mean()) if len(movable) else float("nan"),
                "water_free_ft": float(wf.sum()) * dz,
            })

        names = sorted(set(df["ZONE"]), key=str)
        for name in names:
            summarise(name or NO_ZONE_LABEL, df[df["ZONE"] == name])
        if len(names) > 1:
            summarise(ALL_LABEL, df)
        return rows

    # ------------------------------------------------------------------ render
    def _render(self):
        fig = self.plot.figure
        fig.clear()
        ax = fig.add_subplot(111)
        self.plot._style_axes(ax)
        chrome = get_plot_chrome()
        self.rows = []
        self.line_values = []
        df = self._net_frame()
        if df is None:
            self._message(ax, "Run the analysis first", chrome)
            return
        if df.empty:
            self._message(ax, "No net-reservoir samples with porosity and Sw for this selection.",
                          chrome)
            return

        settings = (self.model.project.lrlc.get("buckles") if self.model is not None else None) \
            or {}
        lines = [float(v) for v in settings.get("bvw_lines", []) if float(v) > 0]
        self.line_values = lines
        phi_max = max(float(df["PHIE"].max()) * 1.1, 0.05)
        phi = np.linspace(0.01, phi_max, 200)
        for v in lines:
            ax.plot(phi, np.minimum(v / phi, 1.0), color=chrome["spine"], lw=0.8, ls="--",
                    zorder=1)
            ax.annotate(f"BVW {v:g}", (phi_max, min(v / phi_max, 1.0)), fontsize=7,
                        color=chrome["text"], ha="right", va="bottom")
        k = source_value(zone_sources(self.ds, self.zone), "k_buckles", float("nan"))
        if np.isfinite(k) and k > 0:
            ax.plot(phi, np.minimum(k / phi, 1.0), color=get_plot_color("BVW"), lw=1.6,
                    label=f"Buckles number {k:g}", zorder=3)

        names = sorted(set(df["ZONE"]), key=str)
        for i, name in enumerate(names):
            part = df[df["ZONE"] == name]
            ax.scatter(part["PHIE"], part["SW"], s=7, alpha=0.6, linewidths=0,
                       color=get_rock_type_color(i + 1, max(len(names), 2)),
                       label=str(name) if name else NO_ZONE_LABEL, zorder=2)
        wf = df[df["WF"].astype(bool)]
        if len(wf):
            ax.scatter(wf["PHIE"], wf["SW"], s=26, marker="D", facecolors="none",
                       edgecolors=get_plot_color("WATER_FREE_FLAG"), linewidths=1.0,
                       label=f"Water-free ({len(wf)})", zorder=4)
        ax.set_xlim(0.0, phi_max)
        ax.set_ylim(0.0, 1.0)
        ax.set_xlabel("PHIE (v/v)")
        ax.set_ylabel("Sw (v/v)")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper right", fontsize=8)
        self.plot.canvas.draw_idle()

        dz = _step(df["DEPTH"].to_numpy(dtype=float)) if df["DEPTH"].notna().any() else 0.0
        results = self.ds.results
        if "DEPTH" in results.columns:
            dz = _step(pd.to_numeric(results["DEPTH"], errors="coerce").to_numpy(dtype=float))
        self.rows = self._table_rows(df, dz)
        self._fill_table()
        self.status_label.setText(
            f"{len(df)} net-reservoir samples, {len(wf)} water-free. Samples along one "
            "hyperbola are at constant BVW (irreducible water).")
        set_status(self.status_label, "muted")

    def _message(self, ax, text, chrome):
        ax.set_xticks([])
        ax.set_yticks([])
        ax.text(0.5, 0.5, text, ha="center", va="center", transform=ax.transAxes,
                color=chrome["text"])
        self.status_label.setText(text)
        set_status(self.status_label, "muted")
        self.table.setRowCount(0)
        self.plot.canvas.draw_idle()

    def _fill_table(self):
        self.table.setRowCount(len(self.rows))
        for r, row in enumerate(self.rows):
            values = (row["zone"], str(row["n"]), self._num(row["mean_bvw"], 3),
                      self._num(row["mean_movable"], 3), self._num(row["water_free_ft"], 1))
            for c, text in enumerate(values):
                item = QTableWidgetItem(text)
                if c:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                          | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, c, item)

    @staticmethod
    def _num(v, d):
        return "n/a" if v is None or not np.isfinite(v) else f"{v:.{d}f}"
