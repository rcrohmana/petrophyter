"""
Summary Tab for Petrophyter PyQt
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QGroupBox,
    QScrollArea,
    QTableView,
    QCheckBox,
    QHeaderView,
    QAbstractItemView,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
import numpy as np
import pandas as pd

from ..widgets.info_strip import InfoStrip
from ..widgets.plot_widget import PlotWidget
from ..widgets.table_model import PandasTableModel
from services.export_service import (
    FIELD_TOTAL_LABEL, WELL_COLUMNS, wells_summary_frame, well_label,
)
from themes.colors import get_plot_chrome, get_plot_color, TITLE_SIZE, LABEL_SIZE

ZONE_TABLE_COLUMNS = [
    "Zone", "Top", "Bottom", "Gross", "Net", "N/G", "Avg PHIE", "Avg Sw",
    "HCPV", "a", "m", "n", "Rw", "Cutoffs (Vsh/Phi/Sw)",
]
_MAX_TABLE_ROWS = 10


def _fmt(value, digits=1, percent=False) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if not np.isfinite(number):
        return ""
    if percent:
        return f"{number * 100:.{digits}f}%"
    return f"{number:.{digits}f}"


def _entry_value(params: dict, name: str):
    return (params.get(name) or {}).get("value")


class _AnnotatedTableModel(PandasTableModel):
    """PandasTableModel plus per-cell tooltips and bold rows/cells."""

    def __init__(self, df=None, parent=None):
        super().__init__(df, parent)
        self.tooltips = {}
        self.bold_rows = set()
        self.bold_cells = set()

    def set_table(self, df, tooltips=None, bold_rows=(), bold_cells=()):
        self.tooltips = dict(tooltips or {})
        self.bold_rows = set(bold_rows)
        self.bold_cells = set(bold_cells)
        self.set_dataframe(df)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid():
            cell = (index.row(), index.column())
            if role == Qt.ItemDataRole.ToolTipRole:
                return self.tooltips.get(cell)
            if role == Qt.ItemDataRole.FontRole and (
                index.row() in self.bold_rows or cell in self.bold_cells
            ):
                font = super().data(index, role) or QFont()
                font.setBold(True)
                return font
        return super().data(index, role)


def _fit_table(table: QTableView, rows: int):
    """Size a table to its rows (up to a cap) so the page scrolls, not the table."""
    shown = min(max(rows, 1), _MAX_TABLE_ROWS)
    header = table.horizontalHeader().height() or 28
    table.setFixedHeight(header + shown * table.verticalHeader().defaultSectionSize() + 6)


def _make_table() -> tuple:
    table = QTableView()
    model = _AnnotatedTableModel()
    table.setModel(model)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setHighlightSections(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    return table, model


class SummaryTab(QWidget):
    """Summary Tab - analysis summary and net pay."""

    well_activated = pyqtSignal(str)  # key of the well whose row was clicked

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self._row_keys = []
        self._setup_ui()
        project = self.model.project
        project.wells_changed.connect(self._refresh_multi)
        project.active_well_changed.connect(lambda _key: self._refresh_multi())
        project.well_updated.connect(lambda _key: self._refresh_multi())
        self._refresh_multi()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)

        # =====================================================================
        # ANALYSIS SCOPE
        # =====================================================================
        scope_group = QGroupBox("Analysis Scope")
        scope_layout = QVBoxLayout(scope_group)

        self.scope_label = QLabel("Mode: - | Data Points: -")
        scope_layout.addWidget(self.scope_label)

        content_layout.addWidget(scope_group)

        # =====================================================================
        # NET PAY ANALYSIS
        # =====================================================================
        pay_group = QGroupBox("Net Pay Analysis")
        pay_layout = QGridLayout(pay_group)

        self._strips = {}
        for row, blocks in enumerate(
            (
                (("gross_sand", "Gross Sand"), ("net_reservoir", "Net Reservoir"), ("net_pay", "Net Pay")),
                (("ng_reservoir", "N/G Reservoir"), ("ng_pay", "N/G Pay"), ("avg_phie", "Avg PHIE (Pay)")),
                (("avg_sw", "Avg Sw (Pay)"), ("avg_vsh", "Avg Vsh (Pay)")),
            )
        ):
            strip = InfoStrip()
            for key, label in blocks:
                strip.add_block(key, label)
                self._strips[key] = strip
            pay_layout.addWidget(strip, row, 0)

        content_layout.addWidget(pay_group)

        # =====================================================================
        # HCPV SUMMARY
        # =====================================================================
        hcpv_group = QGroupBox("HCPV Summary")
        hcpv_layout = QGridLayout(hcpv_group)

        hcpv_strip = InfoStrip()
        for key, label in (
            ("hcpv_gross", "HCPV Gross"),
            ("hcpv_net_res", "HCPV Net Reservoir"),
            ("hcpv_net_pay", "HCPV Net Pay"),
        ):
            hcpv_strip.add_block(key, label)
            self._strips[key] = hcpv_strip
        hcpv_layout.addWidget(hcpv_strip, 0, 0)

        content_layout.addWidget(hcpv_group)

        # =====================================================================
        # BAR CHART
        # =====================================================================
        chart_group = QGroupBox("Thickness Summary")
        chart_layout = QVBoxLayout(chart_group)

        self.bar_chart = PlotWidget(show_toolbar=False, figsize=(8, 4))
        self.bar_chart.setMinimumHeight(300)
        chart_layout.addWidget(self.bar_chart)

        content_layout.addWidget(chart_group)

        # =====================================================================
        # CUTOFF PARAMETERS
        # =====================================================================
        cutoff_group = QGroupBox("Cutoff Parameters Used")
        cutoff_layout = QHBoxLayout(cutoff_group)

        self.vsh_cutoff_label = QLabel("Vsh cutoff: -")
        self.phi_cutoff_label = QLabel("PHIE cutoff: -")
        self.sw_cutoff_label = QLabel("Sw cutoff: -")

        cutoff_layout.addWidget(self.vsh_cutoff_label)
        cutoff_layout.addWidget(self.phi_cutoff_label)
        cutoff_layout.addWidget(self.sw_cutoff_label)
        cutoff_layout.addStretch()

        content_layout.addWidget(cutoff_group)

        # =====================================================================
        # ZONES (active well)
        # =====================================================================
        self.zones_group = QGroupBox("Zones")
        zones_layout = QVBoxLayout(self.zones_group)
        self.zones_table, self.zones_model = _make_table()
        zones_layout.addWidget(self.zones_table)
        self.zones_group.setVisible(False)
        content_layout.addWidget(self.zones_group)

        # =====================================================================
        # WELLS (project, 2+ wells)
        # =====================================================================
        self.wells_group = QGroupBox("Wells")
        wells_layout = QVBoxLayout(self.wells_group)
        self.wells_zone_check = QCheckBox("Show zones per well")
        self.wells_zone_check.toggled.connect(lambda _on: self._refresh_multi())
        wells_layout.addWidget(self.wells_zone_check)
        self.wells_table, self.wells_model = _make_table()
        self.wells_table.clicked.connect(self._on_well_row_clicked)
        wells_layout.addWidget(self.wells_table)
        self.wells_group.setVisible(False)
        content_layout.addWidget(self.wells_group)

        # Placeholder
        self.placeholder = QLabel("Run analysis to view summary")
        self.placeholder.setObjectName("PlaceholderLabel")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(self.placeholder)

        content_layout.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll)

    def refresh_theme(self):
        self.bar_chart.refresh_theme()

    # ---- zones and multi-well tables ----
    def _refresh_multi(self):
        self._update_zones()
        self._update_wells()

    def _update_zones(self):
        summary = self.model.summary if self.model.calculated else None
        zones = (summary or {}).get("zones") or []
        self.zones_group.setVisible(bool(zones))
        if not zones:
            self.zones_model.set_table(pd.DataFrame(columns=ZONE_TABLE_COLUMNS))
            return
        rows, tooltips, bold_cells = [], {}, set()
        for r, zone in enumerate(zones):
            params = zone.get("params") or {}
            cutoffs = " / ".join(
                _fmt(_entry_value(params, key), 2)
                for key in ("vsh_cutoff", "phi_cutoff", "sw_cutoff")
            )
            rows.append([
                str(zone.get("zone", "")), _fmt(zone.get("top")), _fmt(zone.get("bottom")),
                _fmt(zone.get("gross_sand")), _fmt(zone.get("net_pay")),
                _fmt(zone.get("ng_pay"), 1, True), _fmt(zone.get("avg_phie_pay"), 1, True),
                _fmt(zone.get("avg_sw_pay"), 1, True), _fmt(zone.get("hcpv_net_pay"), 4),
                _fmt(_entry_value(params, "a"), 2), _fmt(_entry_value(params, "m"), 2),
                _fmt(_entry_value(params, "n"), 2), _fmt(_entry_value(params, "rw"), 4),
                cutoffs,
            ])
            columns = {"a": 9, "m": 10, "n": 11, "rw": 12}
            for name, c in columns.items():
                self._annotate(params, name, r, c, tooltips, bold_cells)
            parts = []
            for name in ("vsh_cutoff", "phi_cutoff", "sw_cutoff"):
                entry = params.get(name) or {}
                parts.append(f"{name}: {entry.get('source', '-')}")
                if entry.get("source") not in (None, "", "project"):
                    bold_cells.add((r, 13))
            tooltips[(r, 13)] = "Source - " + "; ".join(parts)
        self.zones_model.set_table(
            pd.DataFrame(rows, columns=ZONE_TABLE_COLUMNS), tooltips, bold_cells=bold_cells)
        _fit_table(self.zones_table, len(rows))

    @staticmethod
    def _annotate(params, name, row, col, tooltips, bold_cells):
        """Tooltip with the value's source; bold when it differs from the project value."""
        source = (params.get(name) or {}).get("source")
        if source:
            tooltips[(row, col)] = f"Source: {source}"
            if source != "project":
                bold_cells.add((row, col))

    def _update_wells(self):
        wells = self.model.project.wells
        self.wells_group.setVisible(len(wells) >= 2)
        self._row_keys = []
        if len(wells) < 2:
            self.wells_model.set_table(pd.DataFrame(columns=WELL_COLUMNS))
            return
        frame = wells_summary_frame(wells)
        show_zones = self.wells_zone_check.isChecked()
        rows, keys, bold_rows, tooltips = [], [], set(), {}
        for i, line in frame.iterrows():
            is_total = line["Well"] == FIELD_TOTAL_LABEL and i >= len(wells)
            ds = None if is_total else wells[i]
            rows.append([
                line["Well"], line["Status"], _fmt(line["Gross"]), _fmt(line["Net"]),
                _fmt(line["N/G"], 1, True), _fmt(line["Avg PHIE"], 1, True),
                _fmt(line["Avg Sw"], 1, True), _fmt(line["HCPV"], 4),
                _fmt(line["Rw"], 4), line["Rw source"], _fmt(line["Rsh"], 2),
                line["Rsh source"], _fmt(line["QC score"], 0),
            ])
            keys.append(ds.key if ds is not None else None)
            if is_total:
                bold_rows.add(len(rows) - 1)
                tooltips[(len(rows) - 1, 0)] = (
                    "Gross, Net and HCPV are summed over wells with results; "
                    "N/G = total Net / total Gross; Avg PHIE and Avg Sw are "
                    "weighted by each well's net pay thickness.")
            elif ds is not None and ds.stale:
                tooltips[(len(rows) - 1, 1)] = "Results are out of date; re-run the analysis."
            elif ds is not None and ds.error:
                tooltips[(len(rows) - 1, 1)] = str(ds.error)
            if show_zones and ds is not None and ds.summary and ds.calculated:
                for zone in ds.summary.get("zones") or []:
                    params = zone.get("params") or {}
                    rows.append([
                        f"    {zone.get('zone', '')}", "", _fmt(zone.get("gross_sand")),
                        _fmt(zone.get("net_pay")), _fmt(zone.get("ng_pay"), 1, True),
                        _fmt(zone.get("avg_phie_pay"), 1, True),
                        _fmt(zone.get("avg_sw_pay"), 1, True),
                        _fmt(zone.get("hcpv_net_pay"), 4),
                        _fmt(_entry_value(params, "rw"), 4),
                        str((params.get("rw") or {}).get("source", "")),
                        _fmt(_entry_value(params, "rsh"), 2),
                        str((params.get("rsh") or {}).get("source", "")), "",
                    ])
                    keys.append(ds.key)
        self._row_keys = keys
        self.wells_model.set_table(
            pd.DataFrame(rows, columns=WELL_COLUMNS), tooltips, bold_rows)
        _fit_table(self.wells_table, len(rows))

    def _on_well_row_clicked(self, index):
        row = index.row()
        if 0 <= row < len(self._row_keys) and self._row_keys[row]:
            self.well_activated.emit(self._row_keys[row])

    def _set(self, key: str, value: str):
        self._strips[key].set_value(key, value)

    def update_display(self):
        """Update display with analysis results."""

        if not self.model.calculated or self.model.summary is None:
            self.reset_ui()
            return

        self.placeholder.setVisible(False)

        summary = self.model.summary

        def numeric(key: str, default: float = 0.0) -> float:
            value = summary.get(key, default)
            try:
                number = float(value)
            except (TypeError, ValueError):
                return default
            return number if np.isfinite(number) else default

        # Update scope
        analysis_mode = summary.get("analysis_mode", "Whole Well")
        selected_fms = summary.get("selected_formations", [])
        data_points = summary.get("data_points", 0)

        if analysis_mode == "Per-Formation" and selected_fms:
            self.scope_label.setText(
                f"<b>Mode:</b> Per-Formation | "
                f"<b>Formation(s):</b> {', '.join(selected_fms)} | "
                f"<b>Data Points:</b> {data_points:,}"
            )
        else:
            self.scope_label.setText(
                f"<b>Mode:</b> Whole Well | <b>Data Points:</b> {data_points:,}"
            )

        # Update net pay metrics
        self._set("gross_sand", f"{numeric('gross_sand'):.1f} ft")
        self._set("net_reservoir", f"{numeric('net_reservoir'):.1f} ft")
        self._set("net_pay", f"{numeric('net_pay'):.1f} ft")

        self._set("ng_reservoir", f"{numeric('ng_reservoir') * 100:.1f}%")
        self._set("ng_pay", f"{numeric('ng_pay') * 100:.1f}%")

        for key, card_key in (
            ("avg_phie_pay", "avg_phie"),
            ("avg_sw_pay", "avg_sw"),
            ("avg_vsh_pay", "avg_vsh"),
        ):
            value = summary.get(key)
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = np.nan
            self._set(card_key, f"{value * 100:.1f}%" if np.isfinite(value) else "N/A")

        # Update HCPV metrics
        hcpv_gross = numeric("hcpv_gross")
        hcpv_net_res = numeric("hcpv_net_res")
        hcpv_net_pay = numeric("hcpv_net_pay")

        self._set("hcpv_gross", f"{hcpv_gross:.4f} ft")
        self._set("hcpv_net_res", f"{hcpv_net_res:.4f} ft")
        self._set("hcpv_net_pay", f"{hcpv_net_pay:.4f} ft")

        # Update bar chart
        self._update_bar_chart(summary)

        # Update cutoff labels
        self.vsh_cutoff_label.setText(f"Vsh cutoff: {self.model.vsh_cutoff:.2f}")
        self.phi_cutoff_label.setText(f"PHIE cutoff: {self.model.phi_cutoff:.2f}")
        self.sw_cutoff_label.setText(f"Sw cutoff: {self.model.sw_cutoff:.2f}")

        self._refresh_multi()

    def _update_bar_chart(self, summary: dict):
        """Create thickness summary bar chart including HCPV."""
        ax = self.bar_chart.get_axes()

        labels = ["Gross Sand", "Net Reservoir", "Net Pay", "HCPV Net Pay"]
        values = []
        for key in ("gross_sand", "net_reservoir", "net_pay", "hcpv_net_pay"):
            try:
                value = float(summary.get(key, 0) or 0)
            except (TypeError, ValueError):
                value = 0.0
            values.append(value if np.isfinite(value) else 0.0)
        colors = [
            get_plot_color("GROSS_SAND"),
            get_plot_color("NET_RESERVOIR"),
            get_plot_color("NET_PAY"),
            get_plot_color("HCPV"),
        ]

        chrome = get_plot_chrome()
        bars = ax.bar(
            labels, values, color=colors, edgecolor=chrome["figure"], linewidth=1.2
        )

        # Add value labels on bars
        for bar, value in zip(bars, values):
            height = bar.get_height()
            # Format based on magnitude
            if value < 0.01:
                label_text = f"{value:.4f} ft"
            elif value < 1:
                label_text = f"{value:.3f} ft"
            else:
                label_text = f"{value:.1f} ft"

            ax.text(
                bar.get_x() + bar.get_width() / 2.0,
                height,
                label_text,
                ha="center",
                va="bottom",
                fontsize=9,
                color=chrome["text"],
            )

        ax.set_ylabel("Thickness / Volume (ft)", fontsize=LABEL_SIZE)
        ax.set_title("Thickness & HCPV Summary", fontsize=TITLE_SIZE)
        ax.grid(axis="y", alpha=0.3)
        ax.tick_params(axis="x", rotation=15)

        self.bar_chart.refresh()

    def reset_ui(self):
        """Reset UI to fresh state for New Project."""
        # Reset scope label
        self.scope_label.setText("Mode: - | Data Points: -")

        # Reset net pay cards
        self._set("gross_sand", "- ft")
        self._set("net_reservoir", "- ft")
        self._set("net_pay", "- ft")
        self._set("ng_reservoir", "- %")
        self._set("ng_pay", "- %")
        self._set("avg_phie", "- %")
        self._set("avg_sw", "- %")
        self._set("avg_vsh", "- %")

        # Reset HCPV cards
        self._set("hcpv_gross", "- ft")
        self._set("hcpv_net_res", "- ft")
        self._set("hcpv_net_pay", "- ft")

        # Clear bar chart
        self.bar_chart.clear()

        # Reset cutoff labels
        self.vsh_cutoff_label.setText("Vsh cutoff: -")
        self.phi_cutoff_label.setText("PHIE cutoff: -")
        self.sw_cutoff_label.setText("Sw cutoff: -")

        self._refresh_multi()

        # Show placeholder
        self.placeholder.setVisible(True)
