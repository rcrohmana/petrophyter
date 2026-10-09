"""
Data QC Tab for Petrophyter PyQt
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTableView,
    QGroupBox,
    QScrollArea,
    QHeaderView,
)
from PyQt6.QtCore import Qt
import pandas as pd

from ..widgets.info_strip import InfoStrip
from ..widgets.plot_widget import TripleComboPlot
from ..widgets.table_model import PandasTableModel
from themes.helpers import set_status


class QCTab(QWidget):
    """Data QC Tab - displays QC report and data quality metrics."""

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Scroll area for content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)

        # =====================================================================
        # WELL INFO METRICS
        # =====================================================================
        self.info_strip = InfoStrip()
        self.info_strip.add_block("well", "Well Name")
        self.info_strip.add_block("depth", "Depth Range")
        self.info_strip.add_block("points", "Total Points")
        self.info_strip.add_block("qc", "Quality Score")
        content_layout.addWidget(self.info_strip)

        # =====================================================================
        # CURVE AVAILABILITY
        # =====================================================================
        curves_layout = QHBoxLayout()

        available_group = QGroupBox("Available Curves")
        available_layout = QVBoxLayout(available_group)
        self.available_label = QLabel("-")
        self.available_label.setWordWrap(True)
        available_layout.addWidget(self.available_label)
        curves_layout.addWidget(available_group)

        missing_group = QGroupBox("Missing Required Curves")
        missing_layout = QVBoxLayout(missing_group)
        self.missing_label = QLabel("-")
        self.missing_label.setWordWrap(True)
        missing_layout.addWidget(self.missing_label)
        curves_layout.addWidget(missing_group)

        content_layout.addLayout(curves_layout)

        # =====================================================================
        # QC SUMMARY TABLE & FORMATION TOPS (SIDE BY SIDE)
        # =====================================================================
        tables_layout = QHBoxLayout()

        # Curve Statistics (left)
        table_group = QGroupBox("Curve Statistics")
        table_layout = QVBoxLayout(table_group)

        self.qc_table = QTableView()
        self.qc_table_model = PandasTableModel()
        self.qc_table.setModel(self.qc_table_model)
        self.qc_table.setMinimumHeight(250)
        self.qc_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        table_layout.addWidget(self.qc_table)

        tables_layout.addWidget(table_group, stretch=2)

        # Formation Tops (right)
        self.tops_group = QGroupBox("Formation Tops")
        tops_layout = QVBoxLayout(self.tops_group)

        self.tops_table = QTableView()
        self.tops_table_model = PandasTableModel(float_decimals=1)
        self.tops_table.setModel(self.tops_table_model)
        self.tops_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.tops_table.setMinimumHeight(250)
        tops_layout.addWidget(self.tops_table)

        self.tops_group.setVisible(False)
        tables_layout.addWidget(self.tops_group, stretch=1)

        content_layout.addLayout(tables_layout)

        # =====================================================================
        # NULL VALUE INFO
        # =====================================================================
        null_layout = QHBoxLayout()

        self.null_value_label = QLabel("Declared NULL value: -")
        null_layout.addWidget(self.null_value_label)

        null_info = QLabel(
            "Common null values (-999.25, -9999, etc.) auto-replaced with NaN"
        )
        set_status(null_info, "success")
        null_layout.addWidget(null_info)
        null_layout.addStretch()

        content_layout.addLayout(null_layout)

        # =====================================================================
        # MERGE REPORT (conditional)
        # =====================================================================
        self.merge_group = QGroupBox("LAS Merge Report")
        merge_layout = QVBoxLayout(self.merge_group)

        self.merge_strip = InfoStrip()
        self.merge_strip.add_block("files", "Files Merged")
        self.merge_strip.add_block("min", "Depth Min")
        self.merge_strip.add_block("max", "Depth Max")
        self.merge_strip.add_block("points", "Depth Points")
        merge_layout.addWidget(self.merge_strip)

        self.merge_table = QTableView()
        self.merge_table_model = PandasTableModel()
        self.merge_table.setModel(self.merge_table_model)
        self.merge_table.setMaximumHeight(150)
        merge_layout.addWidget(self.merge_table)

        self.merge_group.setVisible(False)
        content_layout.addWidget(self.merge_group)

        # =====================================================================
        # TRIPLE COMBO LOG
        # =====================================================================
        log_group = QGroupBox("Triple Combo Log (QC Preview)")
        log_layout = QVBoxLayout(log_group)

        self.triple_combo_plot = TripleComboPlot()
        self.triple_combo_plot.setMinimumHeight(400)
        log_layout.addWidget(self.triple_combo_plot)

        content_layout.addWidget(log_group)

        # Placeholder message
        self.placeholder = QLabel("Load a LAS file to begin.")
        self.placeholder.setObjectName("PlaceholderLabel")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(self.placeholder)

        content_layout.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll)

    def refresh_theme(self):
        if hasattr(self, "triple_combo_plot"):
            self.triple_combo_plot.refresh_theme()

    def update_display(self):
        """Update display with current model data."""

        qc = self.model.qc_report

        if qc is None:
            self.reset_ui()
            return

        self.placeholder.setVisible(False)

        # Update metrics
        self.info_strip.set_value("well", qc.well_name)
        self.info_strip.set_value(
            "depth", f"{qc.depth_range[0]:.1f} - {qc.depth_range[1]:.1f}"
        )
        self.info_strip.set_value("points", str(qc.total_points))
        score = qc.overall_quality_score
        self.info_strip.set_value("qc", f"{score:.0f}/100")
        self.info_strip.set_status(
            "qc", "success" if score >= 90 else "warning" if score >= 70 else "error"
        )

        # Update curve availability
        self.available_label.setText(", ".join(qc.curves_available))

        if qc.curves_missing:
            self.missing_label.setText(", ".join(qc.curves_missing))
            set_status(self.missing_label, "warning")
        else:
            self.missing_label.setText("All required curves available")
            set_status(self.missing_label, "success")

        # Update QC table
        if qc.curve_results:
            qc_data = []
            for curve, result in qc.curve_results.items():
                qc_data.append(
                    {
                        "Curve": curve,
                        "Valid %": f"{(1 - result.null_percentage / 100) * 100:.1f}%",
                        "Min": f"{result.min_value:.2f}",
                        "Max": f"{result.max_value:.2f}",
                        "Mean": f"{result.mean_value:.2f}",
                        "Std": f"{result.std_value:.2f}",
                        "Score": f"{result.quality_score:.0f}",
                    }
                )
            self.qc_table_model.set_dataframe(pd.DataFrame(qc_data))

        # Update null value info
        if self.model.las_parser:
            null_val = self.model.las_parser.null_value
            self.null_value_label.setText(f"Declared NULL value: {null_val}")

        # Update merge report
        merge_report = self.model.merge_report
        if merge_report:
            self.merge_group.setVisible(True)
            self.merge_strip.set_value("files", str(len(merge_report.files_processed)))
            self.merge_strip.set_value("min", f"{merge_report.master_depth['min']:.1f} ft")
            self.merge_strip.set_value("max", f"{merge_report.master_depth['max']:.1f} ft")
            self.merge_strip.set_value("points", str(merge_report.master_depth["points"]))

            # Curve sources table
            curve_data = []
            for curve, info in merge_report.curves.items():
                curve_data.append(
                    {
                        "Curve": curve,
                        "Source": info["source_file"],
                        "Coverage": f"{info['coverage'] * 100:.1f}%",
                        "QC Score": f"{info['qc_score']:.0f}",
                        "Gaps Filled": info.get("gaps_filled_from", "-"),
                    }
                )
            if curve_data:
                self.merge_table_model.set_dataframe(pd.DataFrame(curve_data))
        else:
            self.merge_group.setVisible(False)

        # Update triple combo plot
        if self.model.las_data is not None:
            self.triple_combo_plot.plot_triple_combo(
                self.model.las_data, self.model.curve_mapping
            )

        # Update formation tops
        if self.model.formation_tops:
            self.tops_group.setVisible(True)
            tops_df = self.model.formation_tops.to_dataframe()
            self.tops_table_model.set_dataframe(tops_df)
        else:
            self.tops_group.setVisible(False)

    def reset_ui(self):
        """Reset UI to fresh state for New Project."""
        # Reset metric cards
        for key in ("well", "depth", "points", "qc"):
            self.info_strip.set_value(key, "-")
        self.info_strip.set_status("qc", None)

        # Reset curve availability labels
        self.available_label.setText("-")
        self.missing_label.setText("-")
        set_status(self.missing_label, None)

        # Clear QC table
        self.qc_table_model.set_dataframe(pd.DataFrame())

        # Reset null value info
        self.null_value_label.setText("Declared NULL value: -")

        # Reset merge report section
        for key in ("files", "min", "max", "points"):
            self.merge_strip.set_value(key, "-")
        self.merge_table_model.set_dataframe(pd.DataFrame())
        self.merge_group.setVisible(False)

        # Clear triple combo plot
        self.triple_combo_plot.clear()

        # Reset formation tops section
        self.tops_table_model.set_dataframe(pd.DataFrame())
        self.tops_group.setVisible(False)

        # Show placeholder
        self.placeholder.setVisible(True)
