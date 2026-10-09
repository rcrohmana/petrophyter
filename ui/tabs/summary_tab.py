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
)
from PyQt6.QtCore import Qt
import numpy as np

from ..widgets.info_strip import InfoStrip
from ..widgets.plot_widget import PlotWidget
from themes.colors import get_plot_chrome, get_plot_color, TITLE_SIZE, LABEL_SIZE


class SummaryTab(QWidget):
    """Summary Tab - analysis summary and net pay."""

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self._setup_ui()

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

        # Show placeholder
        self.placeholder.setVisible(True)
