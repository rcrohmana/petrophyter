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

from .qc_tab import MetricCard
from ..widgets.plot_widget import PlotWidget


class SummaryTab(QWidget):
    """Summary Tab - analysis summary and net pay."""

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Title
        title = QLabel("📋 Analysis Summary")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)

        # =====================================================================
        # ANALYSIS SCOPE
        # =====================================================================
        scope_group = QGroupBox("🎯 Analysis Scope")
        scope_layout = QVBoxLayout(scope_group)

        self.scope_label = QLabel("📍 Mode: - | Data Points: -")
        self.scope_label.setStyleSheet("font-size: 14px;")
        scope_layout.addWidget(self.scope_label)

        content_layout.addWidget(scope_group)

        # =====================================================================
        # NET PAY ANALYSIS
        # =====================================================================
        pay_group = QGroupBox("Net Pay Analysis")
        pay_layout = QGridLayout(pay_group)

        # Row 1
        self.gross_sand_card = MetricCard("Gross Sand", "- ft")
        self.net_reservoir_card = MetricCard("Net Reservoir", "- ft")
        self.net_pay_card = MetricCard("Net Pay", "- ft")

        pay_layout.addWidget(self.gross_sand_card, 0, 0)
        pay_layout.addWidget(self.net_reservoir_card, 0, 1)
        pay_layout.addWidget(self.net_pay_card, 0, 2)

        # Row 2
        self.ng_reservoir_card = MetricCard("N/G Reservoir", "- %")
        self.ng_pay_card = MetricCard("N/G Pay", "- %")
        self.avg_phie_card = MetricCard("Avg PHIE (Pay)", "- %")

        pay_layout.addWidget(self.ng_reservoir_card, 1, 0)
        pay_layout.addWidget(self.ng_pay_card, 1, 1)
        pay_layout.addWidget(self.avg_phie_card, 1, 2)

        # Row 3
        self.avg_sw_card = MetricCard("Avg Sw (Pay)", "- %")
        self.avg_vsh_card = MetricCard("Avg Vsh (Pay)", "- %")

        pay_layout.addWidget(self.avg_sw_card, 2, 0)
        pay_layout.addWidget(self.avg_vsh_card, 2, 1)

        content_layout.addWidget(pay_group)

        # =====================================================================
        # HCPV SUMMARY
        # =====================================================================
        hcpv_group = QGroupBox("HCPV Summary")
        hcpv_layout = QGridLayout(hcpv_group)

        self.hcpv_gross_card = MetricCard("HCPV Gross", "- ft")
        self.hcpv_net_res_card = MetricCard("HCPV Net Reservoir", "- ft")
        self.hcpv_net_pay_card = MetricCard("HCPV Net Pay", "- ft")

        hcpv_layout.addWidget(self.hcpv_gross_card, 0, 0)
        hcpv_layout.addWidget(self.hcpv_net_res_card, 0, 1)
        hcpv_layout.addWidget(self.hcpv_net_pay_card, 0, 2)

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
        self.placeholder = QLabel("👈 Run analysis first to view summary")
        self.placeholder.setStyleSheet(
            "color: #4A4540; background-color: transparent; font-size: 14px;"
        )
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(self.placeholder)

        content_layout.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll)

    def update_display(self):
        """Update display with analysis results."""
        if not self.model.calculated or self.model.summary is None:
            self.placeholder.setVisible(True)
            return

        self.placeholder.setVisible(False)

        summary = self.model.summary

        # Update scope
        analysis_mode = summary.get("analysis_mode", "Whole Well")
        selected_fms = summary.get("selected_formations", [])
        data_points = summary.get("data_points", 0)

        if analysis_mode == "Per-Formation" and selected_fms:
            self.scope_label.setText(
                f"📍 <b>Mode:</b> Per-Formation | "
                f"<b>Formation(s):</b> {', '.join(selected_fms)} | "
                f"<b>Data Points:</b> {data_points:,}"
            )
        else:
            self.scope_label.setText(
                f"📍 <b>Mode:</b> Whole Well | <b>Data Points:</b> {data_points:,}"
            )

        # Update net pay metrics
        self.gross_sand_card.set_value(f"{summary['gross_sand']:.1f} ft")
        self.net_reservoir_card.set_value(f"{summary['net_reservoir']:.1f} ft")
        self.net_pay_card.set_value(f"{summary['net_pay']:.1f} ft")

        self.ng_reservoir_card.set_value(f"{summary['ng_reservoir'] * 100:.1f}%")
        self.ng_pay_card.set_value(f"{summary['ng_pay'] * 100:.1f}%")

        avg_phie = summary.get("avg_phie_pay", np.nan)
        self.avg_phie_card.set_value(
            f"{avg_phie * 100:.1f}%" if not np.isnan(avg_phie) else "N/A"
        )

        avg_sw = summary.get("avg_sw_pay", np.nan)
        self.avg_sw_card.set_value(
            f"{avg_sw * 100:.1f}%" if not np.isnan(avg_sw) else "N/A"
        )

        avg_vsh = summary.get("avg_vsh_pay", np.nan)
        self.avg_vsh_card.set_value(
            f"{avg_vsh * 100:.1f}%" if not np.isnan(avg_vsh) else "N/A"
        )

        # Update HCPV metrics
        hcpv_gross = summary.get("hcpv_gross", 0)
        hcpv_net_res = summary.get("hcpv_net_res", 0)
        hcpv_net_pay = summary.get("hcpv_net_pay", 0)

        self.hcpv_gross_card.set_value(f"{hcpv_gross:.4f} ft")
        self.hcpv_net_res_card.set_value(f"{hcpv_net_res:.4f} ft")
        self.hcpv_net_pay_card.set_value(f"{hcpv_net_pay:.4f} ft")

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
        values = [
            summary.get("gross_sand", 0),
            summary.get("net_reservoir", 0),
            summary.get("net_pay", 0),
            summary.get("hcpv_net_pay", 0),
        ]
        colors = ["#2196F3", "#4CAF50", "#FF9800", "#228B22"]

        bars = ax.bar(labels, values, color=colors, edgecolor="white", linewidth=1.2)

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
                fontweight="bold",
            )

        ax.set_ylabel("Thickness / Volume (ft)", fontsize=11)
        ax.set_title("Thickness & HCPV Summary", fontsize=12, fontweight="bold")
        ax.grid(axis="y", alpha=0.3)
        ax.tick_params(axis="x", rotation=15)

        self.bar_chart.refresh()

    def reset_ui(self):
        """Reset UI to fresh state for New Project."""
        # Reset scope label
        self.scope_label.setText("📍 Mode: - | Data Points: -")

        # Reset net pay cards
        self.gross_sand_card.set_value("- ft")
        self.net_reservoir_card.set_value("- ft")
        self.net_pay_card.set_value("- ft")
        self.ng_reservoir_card.set_value("- %")
        self.ng_pay_card.set_value("- %")
        self.avg_phie_card.set_value("- %")
        self.avg_sw_card.set_value("- %")
        self.avg_vsh_card.set_value("- %")

        # Reset HCPV cards
        self.hcpv_gross_card.set_value("- ft")
        self.hcpv_net_res_card.set_value("- ft")
        self.hcpv_net_pay_card.set_value("- ft")

        # Clear bar chart
        self.bar_chart.clear()

        # Reset cutoff labels
        self.vsh_cutoff_label.setText("Vsh cutoff: -")
        self.phi_cutoff_label.setText("PHIE cutoff: -")
        self.sw_cutoff_label.setText("Sw cutoff: -")

        # Show placeholder
        self.placeholder.setVisible(True)
