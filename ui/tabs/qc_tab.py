"""
Data QC Tab for Petrophyter PyQt
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QFrame,
    QTableView,
    QGroupBox,
    QScrollArea,
)
from PyQt6.QtCore import Qt, QAbstractTableModel
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QPalette, QColor
import pandas as pd

from ..widgets.plot_widget import TripleComboPlot

# Theme colors - DARKER THEME
_THEME_SURFACE = QColor("#F0EBE1")
_THEME_BG = QColor("#E8E3D9")


class MetricCard(QFrame):
    """A metric display card."""

    def __init__(self, label: str, value: str = "", parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)

        # Set palette to theme color (fixes debug mode detection)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, _THEME_SURFACE)
        palette.setColor(QPalette.ColorRole.Base, _THEME_SURFACE)
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        self.setStyleSheet("""
            QFrame {
                background-color: #F0EBE1;
                border: 1px solid #C9C0B0;
                border-radius: 8px;
                padding: 5px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(2)

        self.label = QLabel(label)
        self.label.setStyleSheet(
            "color: #4A4540; font-size: 11px; background-color: transparent;"
        )

        self.value_label = QLabel(value)
        self.value_label.setStyleSheet(
            "color: #000000; font-size: 16px; font-weight: bold; background-color: transparent;"
        )

        layout.addWidget(self.label)
        layout.addWidget(self.value_label)

    def set_value(self, value: str):
        self.value_label.setText(value)


class PandasTableModel(QAbstractTableModel):
    """Table model for displaying pandas DataFrames."""

    def __init__(self, df: pd.DataFrame = None, parent=None):
        super().__init__(parent)
        self._df = df if df is not None else pd.DataFrame()

    def rowCount(self, parent=None):
        count = len(self._df)
        # print(f"[DEBUG Model] rowCount called, returning {count}")
        return count

    def columnCount(self, parent=None):
        return len(self._df.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        if role == Qt.ItemDataRole.DisplayRole:
            value = self._df.iloc[index.row(), index.column()]
            if isinstance(value, float):
                return f"{value:.4f}"
            return str(value)

        # Center align all cells
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None

        if orientation == Qt.Orientation.Horizontal:
            return str(self._df.columns[section])
        else:
            return str(section + 1)

    def set_dataframe(self, df: pd.DataFrame):
        self.beginResetModel()
        self._df = df
        self.endResetModel()


class QCTab(QWidget):
    """Data QC Tab - displays QC report and data quality metrics."""

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Title
        title = QLabel("📊 Data Quality Control")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        # Scroll area for content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)

        # =====================================================================
        # WELL INFO METRICS
        # =====================================================================
        metrics_layout = QHBoxLayout()

        self.well_name_card = MetricCard("Well Name", "-")
        self.depth_range_card = MetricCard("Depth Range", "-")
        self.total_points_card = MetricCard("Total Points", "-")
        self.quality_score_card = MetricCard("Quality Score", "-")

        metrics_layout.addWidget(self.well_name_card)
        metrics_layout.addWidget(self.depth_range_card)
        metrics_layout.addWidget(self.total_points_card)
        metrics_layout.addWidget(self.quality_score_card)

        content_layout.addLayout(metrics_layout)

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
        table_layout.addWidget(self.qc_table)

        tables_layout.addWidget(table_group, stretch=2)

        # Formation Tops (right)
        self.tops_group = QGroupBox("Formation Tops")
        tops_layout = QVBoxLayout(self.tops_group)

        self.tops_table = QTableView()
        self.tops_table_model = PandasTableModel()
        self.tops_table.setModel(self.tops_table_model)
        self.tops_table.setMinimumHeight(250)
        tops_layout.addWidget(self.tops_table)

        self.tops_group.setVisible(False)
        tables_layout.addWidget(self.tops_group, stretch=1)

        content_layout.addLayout(tables_layout)

        # =====================================================================
        # NULL VALUE INFO
        # =====================================================================
        null_layout = QHBoxLayout()

        self.null_value_label = QLabel("📌 Declared NULL value: -")
        null_layout.addWidget(self.null_value_label)

        null_info = QLabel(
            "✅ Common null values (-999.25, -9999, etc.) auto-replaced with NaN"
        )
        null_info.setStyleSheet("color: green;")
        null_layout.addWidget(null_info)
        null_layout.addStretch()

        content_layout.addLayout(null_layout)

        # =====================================================================
        # MERGE REPORT (conditional)
        # =====================================================================
        self.merge_group = QGroupBox("🔗 LAS Merge Report")
        merge_layout = QVBoxLayout(self.merge_group)

        merge_metrics = QHBoxLayout()
        self.files_merged_card = MetricCard("Files Merged", "-")
        self.depth_min_card = MetricCard("Depth Min", "-")
        self.depth_max_card = MetricCard("Depth Max", "-")
        self.depth_points_card = MetricCard("Depth Points", "-")

        merge_metrics.addWidget(self.files_merged_card)
        merge_metrics.addWidget(self.depth_min_card)
        merge_metrics.addWidget(self.depth_max_card)
        merge_metrics.addWidget(self.depth_points_card)
        merge_layout.addLayout(merge_metrics)

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
        log_group = QGroupBox("📊 Triple Combo Log (QC Preview)")
        log_layout = QVBoxLayout(log_group)

        self.triple_combo_plot = TripleComboPlot()
        self.triple_combo_plot.setMinimumHeight(400)
        log_layout.addWidget(self.triple_combo_plot)

        content_layout.addWidget(log_group)

        # Placeholder message
        self.placeholder = QLabel(
            "👈 Please load a LAS file using the sidebar to begin."
        )
        self.placeholder.setStyleSheet(
            "color: #4A4540; background-color: transparent; font-size: 14px;"
        )
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(self.placeholder)

        content_layout.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll)

    def update_display(self):
        """Update display with current model data."""
        qc = self.model.qc_report

        if qc is None:
            self.placeholder.setVisible(True)
            return

        self.placeholder.setVisible(False)

        # Update metrics
        self.well_name_card.set_value(qc.well_name)
        self.depth_range_card.set_value(
            f"{qc.depth_range[0]:.1f} - {qc.depth_range[1]:.1f}"
        )
        self.total_points_card.set_value(str(qc.total_points))
        self.quality_score_card.set_value(f"{qc.overall_quality_score:.0f}/100")

        # Update curve availability
        self.available_label.setText(", ".join(qc.curves_available))

        if qc.curves_missing:
            self.missing_label.setText(", ".join(qc.curves_missing))
            self.missing_label.setStyleSheet("color: orange;")
        else:
            self.missing_label.setText("All required curves available ✓")
            self.missing_label.setStyleSheet("color: green;")

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
            self.null_value_label.setText(f"📌 Declared NULL value: {null_val}")

        # Update merge report
        merge_report = self.model.merge_report
        if merge_report:
            self.merge_group.setVisible(True)
            self.files_merged_card.set_value(str(len(merge_report.files_processed)))
            self.depth_min_card.set_value(f"{merge_report.master_depth['min']:.1f} ft")
            self.depth_max_card.set_value(f"{merge_report.master_depth['max']:.1f} ft")
            self.depth_points_card.set_value(str(merge_report.master_depth["points"]))

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
