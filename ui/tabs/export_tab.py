"""
Export Tab for Petrophyter PyQt
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QGroupBox,
    QPushButton,
    QTableView,
    QFileDialog,
    QMessageBox,
    QScrollArea,
    QDoubleSpinBox,
    QHeaderView,
)
from PyQt6.QtCore import Qt, pyqtSignal
import pandas as pd
from .qc_tab import PandasTableModel
from themes.colors import get_color


class ExportTab(QWidget):
    """Export Tab - export results to CSV/Excel."""

    export_csv = pyqtSignal(str)  # file path
    export_excel = pyqtSignal(str)  # file path

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Title
        title = QLabel("💾 Export Results")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content_layout = QVBoxLayout(content)

        # =====================================================================
        # DOWNLOAD BUTTONS
        # =====================================================================
        download_group = QGroupBox("Download Results")
        download_layout = QHBoxLayout(download_group)

        self.csv_btn = QPushButton("📥 Download CSV")
        self.csv_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {get_color("success")};
                color: white;
                font-weight: bold;
                padding: 10px 20px;
                border-radius: 5px;
            }}
            QPushButton:hover {{
                background-color: #3d8b40;
            }}
            QPushButton:disabled {{
                background-color: {get_color("text_disabled")};
            }}
        """)
        self.csv_btn.clicked.connect(self._on_export_csv)
        download_layout.addWidget(self.csv_btn)

        self.excel_btn = QPushButton("📥 Download Excel")
        self.excel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {get_color("primary")};
                color: white;
                font-weight: bold;
                padding: 10px 20px;
                border-radius: 5px;
            }}
            QPushButton:hover {{
                background-color: {get_color("primary_dark")};
            }}
            QPushButton:disabled {{
                background-color: {get_color("primary_light")};
            }}
        """)
        self.excel_btn.clicked.connect(self._on_export_excel)
        download_layout.addWidget(self.excel_btn)

        self.buttons = [self.csv_btn, self.excel_btn]

        download_layout.addStretch()

        content_layout.addWidget(download_group)

        # =====================================================================
        # RESULTS PREVIEW
        # =====================================================================
        preview_group = QGroupBox("Results Preview")
        preview_layout = QVBoxLayout(preview_group)

        # Filter controls
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Top MD:"))
        self.top_md_spin = QDoubleSpinBox()
        self.top_md_spin.setRange(0, 100000)
        self.top_md_spin.setDecimals(1)
        self.top_md_spin.setSuffix(" ft")
        filter_layout.addWidget(self.top_md_spin)

        filter_layout.addWidget(QLabel("Bottom MD:"))
        self.bottom_md_spin = QDoubleSpinBox()
        self.bottom_md_spin.setRange(0, 100000)
        self.bottom_md_spin.setDecimals(1)
        self.bottom_md_spin.setSuffix(" ft")
        filter_layout.addWidget(self.bottom_md_spin)

        self.update_table_btn = QPushButton("Update View")
        self.update_table_btn.clicked.connect(self._update_table_view)
        filter_layout.addWidget(self.update_table_btn)

        filter_layout.addStretch()
        preview_layout.addLayout(filter_layout)

        self.preview_table = QTableView()
        self.preview_model = PandasTableModel()
        self.preview_table.setModel(self.preview_model)
        self.preview_table.setMinimumHeight(400)
        self.preview_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.preview_table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        # Configure header
        header = self.preview_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)  # FIXED
        header.setDefaultSectionSize(120)  # FIXED
        header.setHighlightSections(False)

        preview_layout.addWidget(self.preview_table)

        content_layout.addWidget(preview_group)

        # Placeholder
        self.placeholder = QLabel("👈 Run analysis first to export results")
        self.placeholder.setStyleSheet(
            f"color: {get_color('text_secondary')}; background-color: transparent; font-size: 14px;"
        )
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(self.placeholder)

        content_layout.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll)

        # Initially disable buttons
        self.csv_btn.setEnabled(False)
        self.excel_btn.setEnabled(False)

    def refresh_theme(self):
        # Reapply button styles and placeholder color
        self.csv_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {get_color("success")};
                color: white;
                font-weight: bold;
                padding: 10px 20px;
                border-radius: 5px;
            }}
            QPushButton:hover {{
                background-color: #3d8b40;
            }}
            QPushButton:disabled {{
                background-color: {get_color("text_disabled")};
            }}
            """
        )
        self.excel_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {get_color("primary")};
                color: white;
                font-weight: bold;
                padding: 10px 20px;
                border-radius: 5px;
            }}
            QPushButton:hover {{
                background-color: {get_color("primary_dark")};
            }}
            QPushButton:disabled {{
                background-color: {get_color("primary_light")};
            }}
            """
        )
        self.placeholder.setStyleSheet(
            f"color: {get_color('text_secondary')}; background-color: transparent; font-size: 14px;"
        )

    def _on_export_csv(self):
        """Handle CSV export."""

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save CSV",
            "petrophyter_results.csv",
            "CSV Files (*.csv);;All Files (*)",
        )
        if file_path:
            self.export_csv.emit(file_path)

    def _on_export_excel(self):
        """Handle Excel export."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Excel",
            "petrophyter_results.xlsx",
            "Excel Files (*.xlsx);;All Files (*)",
        )
        if file_path:
            self.export_excel.emit(file_path)

    def update_display(self):
        """Update display with analysis results."""
        # print(f"[DEBUG ExportTab] update_display called")
        # print(f"[DEBUG ExportTab] model.calculated = {self.model.calculated}")
        # print(f"[DEBUG ExportTab] model.results is None = {self.model.results is None}")

        if not self.model.calculated or self.model.results is None:
            # print("[DEBUG ExportTab] Early return - no results")
            self.placeholder.setVisible(True)
            self.csv_btn.setEnabled(False)
            self.excel_btn.setEnabled(False)
            return

        self.placeholder.setVisible(False)
        self.preview_table.setVisible(True)
        self.csv_btn.setEnabled(True)
        self.excel_btn.setEnabled(True)

        # Init filter range if needed (only if 0)
        results = self.model.results
        if self.top_md_spin.value() == 0 and self.bottom_md_spin.value() == 0:
            min_depth = results["DEPTH"].min() if "DEPTH" in results.columns else 0
            max_depth = results["DEPTH"].max() if "DEPTH" in results.columns else 0
            if pd.notna(min_depth):
                self.top_md_spin.setValue(min_depth)
            if pd.notna(max_depth):
                self.bottom_md_spin.setValue(max_depth)

        # Update preview table
        self._update_table_view()

    def _update_table_view(self):
        """Update table view based on filters."""
        if not self.model.calculated or self.model.results is None:
            return

        results = self.model.results

        # Filter by depth
        top = self.top_md_spin.value()
        bottom = self.bottom_md_spin.value()

        if "DEPTH" in results.columns and bottom > top:
            filtered_df = results[
                (results["DEPTH"] >= top) & (results["DEPTH"] <= bottom)
            ]
        else:
            filtered_df = results

        # Update preview table (limit to 500 rows)
        preview_df = filtered_df.head(500).copy()
        # print(f"[DEBUG ExportTab] preview_df.shape = {preview_df.shape}")
        # print(
        #     f"[DEBUG ExportTab] preview_df.columns[:5] = {list(preview_df.columns)[:5]}"
        # )
        self.preview_model.set_dataframe(preview_df)

        # FORCE RESET COLUMN SIZES
        header = self.preview_table.horizontalHeader()
        header.setStretchLastSection(False)
        for i in range(self.preview_model.columnCount()):
            self.preview_table.setColumnWidth(i, 120)

    def show_export_success(self, message: str):
        """Show export success message."""
        QMessageBox.information(self, "Export Complete", message)

    def show_export_error(self, message: str):
        """Show export error message."""
        QMessageBox.critical(self, "Export Error", message)

    def reset_ui(self):
        """Reset UI to fresh state for New Project."""
        # Reset spinboxes to 0 so they get updated on next data load
        self.top_md_spin.setValue(0)
        self.bottom_md_spin.setValue(0)

        # Clear table
        self.preview_model.set_dataframe(pd.DataFrame())
        self.preview_table.setVisible(False)

        # Disable export buttons
        self.csv_btn.setEnabled(False)
        self.excel_btn.setEnabled(False)

        # Show placeholder
        self.placeholder.setVisible(True)
