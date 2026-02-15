"""
Diagnostics Tab for Petrophyter PyQt
Cross-validation, statistics, and warnings.
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QGroupBox,
    QTableView,
    QScrollArea,
    QFrame,
    QComboBox,
    QPushButton,
)
from PyQt6.QtCore import Qt
import pandas as pd
import numpy as np

from .qc_tab import MetricCard, PandasTableModel
from ..widgets.plot_widget import HistogramPlot, CrossPlot, PlotWidget
from themes.colors import get_color


class DiagnosticsTab(QWidget):
    """Diagnostics Tab - cross-validation, statistics, and warnings."""

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Title
        title = QLabel("🔍 Diagnostics & Validation")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)

        # =====================================================================
        # SHALE PARAMETERS CROSS-VALIDATION
        # =====================================================================
        shale_group = QGroupBox("📐 Shale Parameters Cross-Validation")
        shale_layout = QHBoxLayout(shale_group)

        # Current values
        current_frame = QFrame()
        current_layout = QVBoxLayout(current_frame)
        current_layout.addWidget(QLabel("<b>Current Values (Used):</b>"))
        self.shale_current_label = QLabel("-")
        current_layout.addWidget(self.shale_current_label)
        shale_layout.addWidget(current_frame)

        # Statistical values
        stat_frame = QFrame()
        stat_layout = QVBoxLayout(stat_frame)
        stat_layout.addWidget(QLabel("<b>Statistical Values:</b>"))
        self.shale_stat_label = QLabel("-")
        stat_layout.addWidget(self.shale_stat_label)
        shale_layout.addWidget(stat_frame)

        # Deviation
        dev_frame = QFrame()
        dev_layout = QVBoxLayout(dev_frame)
        dev_layout.addWidget(QLabel("<b>Deviation:</b>"))
        self.shale_dev_label = QLabel("-")
        dev_layout.addWidget(self.shale_dev_label)
        shale_layout.addWidget(dev_frame)

        content_layout.addWidget(shale_group)

        self.shale_warnings = QLabel("")
        self.shale_warnings.setWordWrap(True)
        content_layout.addWidget(self.shale_warnings)

        # =====================================================================
        # POROSITY CROSS-VALIDATION
        # =====================================================================
        por_group = QGroupBox("📊 Porosity (PHIE) Cross-Validation")
        por_layout = QVBoxLayout(por_group)

        # Control row: dropdown + update button
        control_layout = QHBoxLayout()
        control_layout.addWidget(QLabel("Method:"))

        self.phie_method_combo = QComboBox()
        self.phie_method_combo.addItems(
            ["PHIE_DN", "PHIE_D", "PHIE_N", "PHIE_S", "PHIE_GAS"]
        )
        self.phie_method_combo.setMinimumWidth(120)
        control_layout.addWidget(self.phie_method_combo)

        self.phie_update_btn = QPushButton("Update Plot")
        self.phie_update_btn.clicked.connect(self._update_phie_plot)
        control_layout.addWidget(self.phie_update_btn)

        control_layout.addStretch()
        por_layout.addLayout(control_layout)

        # Plot and stats row
        plot_stats_layout = QHBoxLayout()

        self.phie_hist = HistogramPlot()
        self.phie_hist.setMinimumHeight(250)
        plot_stats_layout.addWidget(self.phie_hist, stretch=2)

        self.phie_stats_table = QTableView()
        self.phie_stats_model = PandasTableModel()
        self.phie_stats_table.setModel(self.phie_stats_model)
        self.phie_stats_table.setMaximumWidth(300)
        plot_stats_layout.addWidget(self.phie_stats_table, stretch=1)

        por_layout.addLayout(plot_stats_layout)

        content_layout.addWidget(por_group)

        self.phie_warnings = QLabel("")
        self.phie_warnings.setWordWrap(True)
        content_layout.addWidget(self.phie_warnings)

        # =====================================================================
        # WATER SATURATION CROSS-VALIDATION
        # =====================================================================
        sw_group = QGroupBox("💧 Water Saturation (Sw) Cross-Validation")
        sw_layout = QHBoxLayout(sw_group)

        self.sw_hist = HistogramPlot()
        self.sw_hist.setMinimumHeight(250)
        sw_layout.addWidget(self.sw_hist, stretch=2)

        self.sw_stats_table = QTableView()
        self.sw_stats_model = PandasTableModel()
        self.sw_stats_table.setModel(self.sw_stats_model)
        self.sw_stats_table.setMaximumWidth(300)
        sw_layout.addWidget(self.sw_stats_table, stretch=1)

        content_layout.addWidget(sw_group)

        # =====================================================================
        # PERMEABILITY VALIDATION
        # =====================================================================
        perm_group = QGroupBox("🔑 Permeability (k) Validation")
        perm_layout = QHBoxLayout(perm_group)

        self.perm_crossplot = CrossPlot()
        self.perm_crossplot.setMinimumHeight(250)
        perm_layout.addWidget(self.perm_crossplot, stretch=2)

        self.perm_stats_table = QTableView()
        self.perm_stats_model = PandasTableModel()
        self.perm_stats_table.setModel(self.perm_stats_model)
        self.perm_stats_table.setMaximumWidth(300)
        perm_layout.addWidget(self.perm_stats_table, stretch=1)

        content_layout.addWidget(perm_group)

        self.perm_warnings = QLabel("")
        self.perm_warnings.setWordWrap(True)
        content_layout.addWidget(self.perm_warnings)

        # =====================================================================
        # NET PAY VALIDATION
        # =====================================================================
        pay_group = QGroupBox("📏 Net Pay Validation")
        pay_layout = QHBoxLayout(pay_group)

        self.net_pay_card = MetricCard("Net Pay", "- ft")
        self.gross_sand_card = MetricCard("Gross Sand", "- ft")
        self.ng_pay_card = MetricCard("N/G Pay", "- %")

        self.metric_cards = [
            self.net_pay_card,
            self.gross_sand_card,
            self.ng_pay_card,
        ]

        pay_layout.addWidget(self.net_pay_card)
        pay_layout.addWidget(self.gross_sand_card)
        pay_layout.addWidget(self.ng_pay_card)
        pay_layout.addStretch()

        content_layout.addWidget(pay_group)

        self.pay_warnings = QLabel("")
        self.pay_warnings.setWordWrap(True)
        content_layout.addWidget(self.pay_warnings)

        # =====================================================================
        # CORE DATA VALIDATION (conditional)
        # =====================================================================
        self.core_group = QGroupBox("🔬 Core Data Validation")
        core_layout = QVBoxLayout(self.core_group)

        # Core summary metrics
        core_metrics = QHBoxLayout()
        self.core_samples_card = MetricCard("Core Samples", "-")
        self.core_depth_card = MetricCard("Core Depth Range", "-")
        self.core_props_card = MetricCard("Properties", "-")

        self.metric_cards.extend(
            [self.core_samples_card, self.core_depth_card, self.core_props_card]
        )

        core_metrics.addWidget(self.core_samples_card)
        core_metrics.addWidget(self.core_depth_card)
        core_metrics.addWidget(self.core_props_card)

        core_layout.addLayout(core_metrics)

        # Porosity validation
        por_valid_layout = QHBoxLayout()

        self.core_por_crossplot = CrossPlot()
        self.core_por_crossplot.setMinimumHeight(280)
        por_valid_layout.addWidget(self.core_por_crossplot, stretch=2)

        self.core_por_stats = QTableView()
        self.core_por_stats_model = PandasTableModel()
        self.core_por_stats.setModel(self.core_por_stats_model)
        self.core_por_stats.setMaximumWidth(280)
        por_valid_layout.addWidget(self.core_por_stats, stretch=1)

        core_layout.addLayout(por_valid_layout)

        # Permeability validation
        perm_valid_layout = QHBoxLayout()

        self.core_perm_crossplot = CrossPlot()
        self.core_perm_crossplot.setMinimumHeight(280)
        perm_valid_layout.addWidget(self.core_perm_crossplot, stretch=2)

        self.core_perm_stats = QTableView()
        self.core_perm_stats_model = PandasTableModel()
        self.core_perm_stats.setModel(self.core_perm_stats_model)
        self.core_perm_stats.setMaximumWidth(280)
        perm_valid_layout.addWidget(self.core_perm_stats, stretch=1)

        core_layout.addLayout(perm_valid_layout)

        # Depth tracks with core overlay
        depth_track_label = QLabel("<b>📏 Depth Track with Core Points</b>")
        core_layout.addWidget(depth_track_label)

        depth_track_layout = QHBoxLayout()

        self.core_phie_depth_plot = PlotWidget(show_toolbar=True, figsize=(5, 4))
        self.core_phie_depth_plot.setMinimumHeight(350)
        depth_track_layout.addWidget(self.core_phie_depth_plot)

        self.core_perm_depth_plot = PlotWidget(show_toolbar=True, figsize=(5, 4))
        self.core_perm_depth_plot.setMinimumHeight(350)
        depth_track_layout.addWidget(self.core_perm_depth_plot)

        core_layout.addLayout(depth_track_layout)

        self.core_warnings = QLabel("")
        self.core_warnings.setWordWrap(True)
        core_layout.addWidget(self.core_warnings)

        self.core_group.setVisible(False)
        content_layout.addWidget(self.core_group)

        # Placeholder
        self.placeholder = QLabel("👈 Run analysis first to view diagnostics")
        self.placeholder.setStyleSheet(
            f"color: {get_color('text_secondary')}; background-color: transparent; font-size: 14px;"
        )
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(self.placeholder)

        content_layout.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll)

    def refresh_theme(self):
        for card in getattr(self, "metric_cards", []):
            card.refresh_theme()
        self.placeholder.setStyleSheet(
            f"color: {get_color('text_secondary')}; background-color: transparent; font-size: 14px;"
        )

    def update_display(self):
        """Update display with analysis results."""

        if not self.model.calculated or self.model.results is None:
            self.placeholder.setVisible(True)
            return

        self.placeholder.setVisible(False)

        results = self.model.results
        summary = self.model.summary

        # =====================================================================
        # SHALE PARAMETERS
        # =====================================================================
        rho_shale = self.model.rho_shale
        nphi_shale = self.model.nphi_shale
        dt_shale = self.model.dt_shale
        method = self.model.shale_method_used

        self.shale_current_label.setText(
            f"ρ shale: {rho_shale:.2f} g/cc\n"
            f"NPHI shale: {nphi_shale:.2f}\n"
            f"DT shale: {dt_shale:.1f} µs/ft\n"
            f"Method: {method}"
        )

        # Get statistical values from calculated_shale
        calculated_shale = getattr(self.model, "calculated_shale", None)
        if calculated_shale and "shale_stats" in calculated_shale:
            shale_stats = calculated_shale["shale_stats"]

            # Extract statistical values (using mean as the standard comparison)
            stat_rhob = shale_stats.get("RHOB", {}).get("mean")
            stat_nphi = shale_stats.get("NPHI", {}).get("mean")
            stat_dt = shale_stats.get("DT", {}).get("mean")

            stat_lines = []
            dev_lines = []

            if stat_rhob is not None:
                stat_lines.append(f"ρ shale: {stat_rhob:.2f} g/cc")
                dev_lines.append(f"Δρ: {rho_shale - stat_rhob:+.3f}")
            if stat_nphi is not None:
                stat_lines.append(f"NPHI shale: {stat_nphi:.2f}")
                dev_lines.append(f"ΔNPHI: {nphi_shale - stat_nphi:+.3f}")
            if stat_dt is not None:
                stat_lines.append(f"DT shale: {stat_dt:.1f} µs/ft")
                dev_lines.append(f"ΔDT: {dt_shale - stat_dt:+.1f}")

            self.shale_stat_label.setText("\n".join(stat_lines) if stat_lines else "-")
            self.shale_dev_label.setText("\n".join(dev_lines) if dev_lines else "-")

            # Add dynamic warning if deviation is high
            has_high_dev = False
            if stat_rhob is not None and abs(rho_shale - stat_rhob) > 0.1:
                has_high_dev = True
            if stat_nphi is not None and abs(nphi_shale - stat_nphi) > 0.05:
                has_high_dev = True

            if has_high_dev:
                self.shale_warnings.setText("⚠️ High deviation in shale parameters")
                self.shale_warnings.setStyleSheet("color: orange; font-weight: bold;")
            else:
                self.shale_warnings.setText("✅ Shale parameters within expected range")
                self.shale_warnings.setStyleSheet("color: green;")
        else:
            self.shale_stat_label.setText("(No shale stats available)")
            self.shale_dev_label.setText("-")
            self.shale_warnings.setText("✅ Shale parameters set")
            self.shale_warnings.setStyleSheet("color: green;")

        # =====================================================================
        # POROSITY VALIDATION
        # =====================================================================
        phie_cols = ["PHIE_D", "PHIE_N", "PHIE_S", "PHIE_DN", "PHIE_GAS"]
        available_phie = [
            c
            for c in phie_cols
            if c in results.columns and results[c].notna().sum() > 0
        ]

        if available_phie:
            # Update combo box with available methods
            self.phie_method_combo.blockSignals(True)
            self.phie_method_combo.clear()
            self.phie_method_combo.addItems(available_phie)
            # Default to PHIE_DN if available
            if "PHIE_DN" in available_phie:
                self.phie_method_combo.setCurrentText("PHIE_DN")
            self.phie_method_combo.blockSignals(False)

            # Call update plot to show initial histogram
            self._update_phie_plot()

        # =====================================================================
        # WATER SATURATION VALIDATION
        # =====================================================================
        sw_cols = ["SW_ARCHIE", "SW_INDO", "SW_SIMAN"]
        available_sw = [
            c for c in sw_cols if c in results.columns and results[c].notna().sum() > 0
        ]

        if available_sw:
            # Statistics table
            stats_data = []
            for col in available_sw:
                data = results[col].dropna()
                stats_data.append(
                    {
                        "Method": col.replace("SW_", ""),
                        "Mean": f"{data.mean():.3f}",
                        "Std": f"{data.std():.3f}",
                        "Min": f"{data.min():.3f}",
                        "Max": f"{data.max():.3f}",
                    }
                )
            self.sw_stats_model.set_dataframe(pd.DataFrame(stats_data))

            # Histogram - overlay all available Sw methods (density mode)
            self.sw_hist.figure.clear()
            ax = self.sw_hist.figure.add_subplot(111)
            ax.set_facecolor(self.sw_hist._axes_color)

            # Define colors and labels for each method
            method_config = {
                "SW_ARCHIE": {"color": "#FF6B6B", "label": "Archie"},
                "SW_INDO": {"color": "#4ECDC4", "label": "Indonesian"},
                "SW_SIMAN": {"color": "#45B7D1", "label": "Simandoux"},
            }

            # Use consistent bins for all methods
            bins = np.linspace(0, 1, 31)  # 30 bins from 0 to 1

            # Plot density histogram for each available method
            all_patches = []
            all_counts = []
            for col in available_sw:
                data = results[col].dropna()
                config = method_config.get(col, {"color": "#808080", "label": col})

                # Calculate counts first (for labels)
                counts, bin_edges = np.histogram(data, bins=bins)

                # Plot density histogram
                n, _, patches = ax.hist(
                    data,
                    bins=bins,
                    density=True,
                    color=config["color"],
                    alpha=0.6,
                    label=config["label"],
                    edgecolor="white",
                    linewidth=0.5,
                )

                all_patches.append(patches)
                all_counts.append(counts)

            # Add count labels on top of bars (only for single method to avoid clutter)
            if len(available_sw) == 1 and all_patches:
                patches = all_patches[0]
                counts = all_counts[0]
                for patch, count in zip(patches, counts):
                    if count > 0:  # Only label non-zero bars
                        height = patch.get_height()
                        x = patch.get_x() + patch.get_width() / 2
                        ax.annotate(
                            f"{count}",
                            xy=(x, height),
                            xytext=(0, 2),
                            textcoords="offset points",
                            ha="center",
                            va="bottom",
                            fontsize=6,
                            color="#4A4540",
                        )

            # Styling
            ax.set_xlabel("Water Saturation (Sw)", fontsize=9)
            ax.set_ylabel("Density", fontsize=9)
            ax.set_title(
                "Water Saturation Distribution", fontsize=10, fontweight="bold"
            )
            ax.set_xlim(0, 1)

            # Adjust Y-axis limit with 10% margin for compact display
            if ax.patches:
                y_max = max([patch.get_height() for patch in ax.patches])
                ax.set_ylim(0, y_max * 1.15)  # Extra margin for count labels

            ax.grid(True, alpha=0.3, linestyle="--")
            ax.legend(loc="upper right", fontsize=8, framealpha=0.9)

            self.sw_hist.figure.tight_layout()
            self.sw_hist.canvas.draw()

        # =====================================================================
        # PERMEABILITY VALIDATION
        # =====================================================================
        perm_cols = ["PERM_TIMUR", "PERM_WR"]
        available_perm = [
            c
            for c in perm_cols
            if c in results.columns and results[c].notna().sum() > 0
        ]

        if available_perm:
            # Statistics table
            stats_data = []
            for col in available_perm:
                data = results[col].dropna()
                stats_data.append(
                    {
                        "Method": col.replace("PERM_", ""),
                        "Mean": f"{data.mean():.2f}",
                        "Std": f"{data.std():.2f}",
                        "Min": f"{data.min():.4f}",
                        "Max": f"{data.max():.2f}",
                    }
                )
            self.perm_stats_model.set_dataframe(pd.DataFrame(stats_data))

            # Crossplot
            if "PHIE" in results.columns and "PERM_TIMUR" in results.columns:
                perm_log = np.log10(results["PERM_TIMUR"].clip(0.001, 50000))
                self.perm_crossplot.plot_crossplot(
                    results["PHIE"],
                    perm_log,
                    color_data=results.get("VSH"),
                    x_label="PHIE (v/v)",
                    y_label="log10(k) [mD]",
                    title="Permeability vs Porosity",
                )

            # Warnings
            warnings = []
            for col in available_perm:
                k = results[col].dropna()
                high_k = (k > 50000).sum()
                low_k = (k < 0.001).sum()
                if high_k > 0:
                    warnings.append(f"⚠️ {col}: {high_k} points with k > 50,000 mD")
                if low_k > 0:
                    warnings.append(f"⚠️ {col}: {low_k} points with k < 0.001 mD")

            if warnings:
                self.perm_warnings.setText("\n".join(warnings))
                self.perm_warnings.setStyleSheet("color: orange;")
            else:
                self.perm_warnings.setText("✅ No permeability outliers detected")
                self.perm_warnings.setStyleSheet("color: green;")

        # =====================================================================
        # NET PAY VALIDATION
        # =====================================================================
        if summary:
            net_pay = summary.get("net_pay", 0)
            gross_sand = summary.get("gross_sand", 0)
            ng_pay = summary.get("ng_pay", 0) * 100

            self.net_pay_card.set_value(f"{net_pay:.1f} ft")
            self.gross_sand_card.set_value(f"{gross_sand:.1f} ft")
            self.ng_pay_card.set_value(f"{ng_pay:.1f}%")

            # Warnings
            warnings = []
            if net_pay < 1:
                warnings.append(
                    f"⚠️ Net Pay ({net_pay:.1f} ft) < 1 ft - may be too thin"
                )
            if gross_sand > 0 and ng_pay > 50:
                warnings.append(f"⚠️ N/G Pay ({ng_pay:.1f}%) > 50% - verify cutoffs")

            if warnings:
                self.pay_warnings.setText("\n".join(warnings))
                self.pay_warnings.setStyleSheet("color: orange;")
            else:
                self.pay_warnings.setText("✅ Net Pay values within expected range")
                self.pay_warnings.setStyleSheet("color: green;")

        # =====================================================================
        # CORE DATA VALIDATION
        # =====================================================================
        if self.model.core_data is not None:
            self.core_group.setVisible(True)
            core = self.model.core_data

            # Summary metrics
            summary_core = core.get_summary()
            self.core_samples_card.set_value(str(summary_core.get("n_samples", 0)))

            depth_range = summary_core.get("depth_range", (0, 0))
            self.core_depth_card.set_value(
                f"{depth_range[0]:.0f} - {depth_range[1]:.0f} ft"
            )

            props = summary_core.get("properties", [])
            self.core_props_card.set_value(", ".join(props))

            # Validation
            if "DEPTH" in results.columns and "PHIE" in results.columns:
                log_depth = results["DEPTH"].values
                log_phie = results["PHIE"].values

                # Porosity validation
                por_result = core.validate_porosity(log_depth, log_phie)
                if por_result:
                    # Stats table
                    stats_data = [
                        {"Metric": "N Points", "Value": str(por_result.n_points)},
                        {"Metric": "Bias", "Value": f"{por_result.bias:.4f}"},
                        {"Metric": "MAE", "Value": f"{por_result.mae:.4f}"},
                        {"Metric": "RMSE", "Value": f"{por_result.rmse:.4f}"},
                        {
                            "Metric": "R²",
                            "Value": f"{por_result.r_squared:.3f}"
                            if por_result.r_squared
                            else "N/A",
                        },
                        {
                            "Metric": "Spearman ρ",
                            "Value": f"{por_result.spearman_rho:.3f}",
                        },
                    ]
                    self.core_por_stats_model.set_dataframe(pd.DataFrame(stats_data))

                    # Crossplot
                    matched = core.get_matched_data(log_depth, log_phie=log_phie)
                    if (
                        "CORE_POROSITY" in matched.columns
                        and "LOG_PHIE" in matched.columns
                    ):
                        valid = matched.dropna(subset=["CORE_POROSITY", "LOG_PHIE"])
                        if len(valid) > 0:
                            self.core_por_crossplot.plot_crossplot(
                                valid["CORE_POROSITY"],
                                valid["LOG_PHIE"],
                                x_label="Core Porosity",
                                y_label="Log PHIE",
                                title="Core vs Log Porosity",
                            )
                            # Add 1:1 line (access existing axes, don't call get_axes which clears)
                            if self.core_por_crossplot.figure.axes:
                                ax = self.core_por_crossplot.figure.axes[0]
                                lims = [
                                    0,
                                    max(
                                        valid["CORE_POROSITY"].max(),
                                        valid["LOG_PHIE"].max(),
                                    )
                                    * 1.1,
                                ]
                                ax.plot(lims, lims, "k--", alpha=0.5, label="1:1")
                                self.core_por_crossplot.refresh()

                # Permeability validation
                if "PERM_TIMUR" in results.columns:
                    log_perm = results["PERM_TIMUR"].values
                    perm_result = core.validate_permeability(log_depth, log_perm)
                    if perm_result:
                        # Stats table
                        stats_data = [
                            {"Metric": "N Points", "Value": str(perm_result.n_points)},
                            {
                                "Metric": "Bias (linear)",
                                "Value": f"{perm_result.bias_linear:.2f}",
                            },
                            {
                                "Metric": "MAE (linear)",
                                "Value": f"{perm_result.mae_linear:.2f}",
                            },
                            {
                                "Metric": "RMSE (linear)",
                                "Value": f"{perm_result.rmse_linear:.2f}",
                            },
                            {
                                "Metric": "MAE (log10)",
                                "Value": f"{perm_result.mae_log10:.3f}",
                            },
                            {
                                "Metric": "Spearman ρ",
                                "Value": f"{perm_result.spearman_rho:.3f}",
                            },
                        ]
                        self.core_perm_stats_model.set_dataframe(
                            pd.DataFrame(stats_data)
                        )

                        # Crossplot
                        matched = core.get_matched_data(log_depth, log_perm=log_perm)
                        if (
                            "CORE_PERM" in matched.columns
                            and "LOG_PERM" in matched.columns
                        ):
                            valid = matched.dropna(subset=["CORE_PERM", "LOG_PERM"])
                            if len(valid) > 0:
                                # Log scale
                                core_log = np.log10(valid["CORE_PERM"].clip(0.001))
                                log_log = np.log10(valid["LOG_PERM"].clip(0.001))
                                self.core_perm_crossplot.plot_crossplot(
                                    core_log,
                                    log_log,
                                    x_label="Core Perm (log10 mD)",
                                    y_label="Log Perm (log10 mD)",
                                    title="Core vs Log Permeability",
                                )
                                # Add 1:1 line (access existing axes, don't call get_axes which clears)
                                if self.core_perm_crossplot.figure.axes:
                                    ax = self.core_perm_crossplot.figure.axes[0]
                                    lims = [
                                        min(core_log.min(), log_log.min()),
                                        max(core_log.max(), log_log.max()),
                                    ]
                                    ax.plot(lims, lims, "k--", alpha=0.5, label="1:1")
                                    self.core_perm_crossplot.refresh()

                # ===============================================================
                # DEPTH TRACK WITH CORE POINTS
                # ===============================================================
                self._plot_depth_track_with_core(core, results)

                # Warnings
                warnings = []
                if por_result and por_result.r_squared and por_result.r_squared < 0.5:
                    warnings.append(
                        f"⚠️ Porosity R² = {por_result.r_squared:.2f} (low correlation)"
                    )
                if por_result and abs(por_result.bias) > 0.05:
                    warnings.append(f"⚠️ Porosity bias = {por_result.bias:.3f} (>0.05)")

                if warnings:
                    self.core_warnings.setText("\n".join(warnings))
                    self.core_warnings.setStyleSheet("color: orange;")
                else:
                    self.core_warnings.setText(
                        "✅ Core validation within acceptable range"
                    )
                    self.core_warnings.setStyleSheet("color: green;")
        else:
            self.core_group.setVisible(False)

    def _plot_depth_track_with_core(self, core, results):
        """Plot depth tracks with log curves and core overlay points."""
        # Get log data
        log_depth = results["DEPTH"].values

        # ===================================================================
        # PHIE vs Depth with Core Porosity
        # ===================================================================
        self.core_phie_depth_plot.figure.clear()
        ax1 = self.core_phie_depth_plot.figure.add_subplot(111)
        ax1.set_facecolor(self.core_phie_depth_plot._axes_color)

        # Plot log PHIE
        if "PHIE" in results.columns:
            log_phie = results["PHIE"].values
            ax1.plot(
                log_phie, log_depth, color="#00CED1", linewidth=1, label="Log PHIE"
            )

        # Overlay core porosity
        try:
            core_depths, core_por = core.get_core_porosity()
            if len(core_depths) > 0:
                ax1.scatter(
                    core_por,
                    core_depths,
                    c="#006666",
                    marker="D",
                    s=40,
                    zorder=5,
                    label="Core Porosity",
                    edgecolors="white",
                    linewidths=0.5,
                )
        except:
            pass

        ax1.set_xlim(0, 0.4)
        ax1.set_xlabel("Porosity (v/v)", fontsize=10)
        ax1.set_ylabel("Depth (ft)", fontsize=10)
        ax1.set_title("PHIE vs Depth", fontsize=11, fontweight="bold")
        ax1.invert_yaxis()
        ax1.grid(True, alpha=0.3)
        ax1.legend(loc="upper right", fontsize=8)

        self.core_phie_depth_plot.figure.tight_layout()
        self.core_phie_depth_plot.canvas.draw()

        # ===================================================================
        # Permeability vs Depth with Core Permeability
        # ===================================================================
        self.core_perm_depth_plot.figure.clear()
        ax2 = self.core_perm_depth_plot.figure.add_subplot(111)
        ax2.set_facecolor(self.core_perm_depth_plot._axes_color)

        # Plot log permeability
        if "PERM_TIMUR" in results.columns:
            log_perm = np.clip(results["PERM_TIMUR"].values, 0.01, 50000)
            ax2.plot(
                log_perm, log_depth, color="#FF6347", linewidth=1, label="Log Perm"
            )

        # Overlay core permeability
        try:
            core_depths, core_perm = core.get_core_permeability()
            if len(core_depths) > 0:
                ax2.scatter(
                    core_perm,
                    core_depths,
                    c="#CC0000",
                    marker="D",
                    s=40,
                    zorder=5,
                    label="Core Perm",
                    edgecolors="white",
                    linewidths=0.5,
                )
        except:
            pass

        ax2.set_xscale("log")
        ax2.set_xlim(0.1, 50000)
        ax2.set_xlabel("Permeability (mD)", fontsize=10)
        ax2.set_ylabel("Depth (ft)", fontsize=10)
        ax2.set_title("Permeability vs Depth", fontsize=11, fontweight="bold")
        ax2.invert_yaxis()
        ax2.grid(True, alpha=0.3, which="both")
        ax2.legend(loc="upper right", fontsize=8)

        self.core_perm_depth_plot.figure.tight_layout()
        self.core_perm_depth_plot.canvas.draw()

    def _update_phie_plot(self):
        """Update PHIE histogram and stats based on selected method."""
        if not self.model.calculated or self.model.results is None:
            return

        results = self.model.results
        selected_method = self.phie_method_combo.currentText()

        # Check if selected method exists in results
        if selected_method not in results.columns:
            self.phie_warnings.setText(f"⚠️ {selected_method} not available in results")
            self.phie_warnings.setStyleSheet("color: orange;")
            return

        data = results[selected_method].dropna()
        if len(data) == 0:
            self.phie_warnings.setText(f"⚠️ {selected_method} has no valid data")
            self.phie_warnings.setStyleSheet("color: orange;")
            return

        # Update histogram
        self.phie_hist.plot_histogram(data, f"{selected_method} Distribution")

        # Update statistics table
        phie_cols = ["PHIE_D", "PHIE_N", "PHIE_S", "PHIE_DN", "PHIE_GAS"]
        available_phie = [
            c
            for c in phie_cols
            if c in results.columns and results[c].notna().sum() > 0
        ]

        stats_data = []
        for col in available_phie:
            col_data = results[col].dropna()
            # Highlight selected method
            method_name = col if col != selected_method else f"► {col}"
            stats_data.append(
                {
                    "Method": method_name,
                    "Mean": f"{col_data.mean():.3f}",
                    "Std": f"{col_data.std():.3f}",
                    "Min": f"{col_data.min():.3f}",
                    "Max": f"{col_data.max():.3f}",
                }
            )
        self.phie_stats_model.set_dataframe(pd.DataFrame(stats_data))

        # Update warnings
        warnings = []
        high_phie = (data > 0.45).sum()
        low_phie = (data < 0).sum()
        if high_phie > 0:
            warnings.append(f"⚠️ {high_phie} points with {selected_method} > 0.45")
        if low_phie > 0:
            warnings.append(
                f"⚠️ {low_phie} points with {selected_method} < 0 (negative)"
            )

        if warnings:
            self.phie_warnings.setText("\n".join(warnings))
            self.phie_warnings.setStyleSheet("color: orange;")
        else:
            self.phie_warnings.setText(f"✅ No {selected_method} outliers detected")
            self.phie_warnings.setStyleSheet("color: green;")

    def reset_ui(self):
        """Reset UI to fresh state for New Project."""
        # Reset shale parameters section
        self.shale_current_label.setText("-")
        self.shale_stat_label.setText("-")
        self.shale_dev_label.setText("-")
        self.shale_warnings.setText("")

        # Reset porosity section
        self.phie_method_combo.clear()
        self.phie_hist.clear()
        self.phie_stats_model.set_dataframe(pd.DataFrame())
        self.phie_warnings.setText("")

        # Reset Sw section
        self.sw_hist.clear()
        self.sw_stats_model.set_dataframe(pd.DataFrame())

        # Reset permeability section
        self.perm_crossplot.clear()
        self.perm_stats_model.set_dataframe(pd.DataFrame())
        self.perm_warnings.setText("")

        # Reset net pay section
        self.net_pay_card.set_value("- ft")
        self.gross_sand_card.set_value("- ft")
        self.ng_pay_card.set_value("- %")
        self.pay_warnings.setText("")

        # Reset core validation section
        self.core_samples_card.set_value("-")
        self.core_depth_card.set_value("-")
        self.core_props_card.set_value("-")
        self.core_por_crossplot.clear()
        self.core_por_stats_model.set_dataframe(pd.DataFrame())
        self.core_perm_crossplot.clear()
        self.core_perm_stats_model.set_dataframe(pd.DataFrame())
        self.core_phie_depth_plot.clear()
        self.core_perm_depth_plot.clear()
        self.core_warnings.setText("")
        self.core_group.setVisible(False)

        # Show placeholder
        self.placeholder.setVisible(True)
