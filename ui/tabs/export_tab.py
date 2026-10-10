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
    QComboBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
import pandas as pd
from ..widgets.table_model import PandasTableModel
from themes.icon_loader import get_icon
from services.export_service import ExportService, default_file_stem, las_frame, wells_with_results

SCOPE_ACTIVE = "Active well"
SCOPE_ALL = "All wells"


class ExportTab(QWidget):
    """Export Tab - export results to CSV/Excel."""

    export_csv = pyqtSignal(str)  # file path
    export_excel = pyqtSignal(str)  # file path
    export_succeeded = pyqtSignal(str)  # message for the banner

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

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

        download_layout.addWidget(QLabel("Scope:"))
        self.scope_combo = QComboBox()
        self.scope_combo.addItems([SCOPE_ACTIVE, SCOPE_ALL])
        self.scope_combo.currentIndexChanged.connect(lambda _i: self._sync_buttons())
        download_layout.addWidget(self.scope_combo)

        self.csv_btn = QPushButton("Download CSV")
        self.csv_btn.setIcon(get_icon("download"))
        self.csv_btn.clicked.connect(self._on_export_csv)
        download_layout.addWidget(self.csv_btn)

        self.excel_btn = QPushButton("Download Excel")
        self.excel_btn.setIcon(get_icon("download"))
        self.excel_btn.clicked.connect(self._on_export_excel)
        download_layout.addWidget(self.excel_btn)

        self.las_btn = QPushButton("Download LAS")
        self.las_btn.setIcon(get_icon("download"))
        self.las_btn.clicked.connect(self._on_export_las)
        download_layout.addWidget(self.las_btn)

        self.buttons = [self.csv_btn, self.excel_btn, self.las_btn]

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
        self.placeholder = QLabel("Run analysis to export results")
        self.placeholder.setObjectName("PlaceholderLabel")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(self.placeholder)

        content_layout.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll)

        # Initially disable buttons
        for button in self.buttons:
            button.setEnabled(False)

        # "All wells" exports run here (the active-well exports are still
        # emitted as signals for the main window).
        self._service = ExportService(self)
        self._service.export_complete.connect(self.show_export_success)
        self._service.export_error.connect(self.show_export_error)

        project = self.model.project
        project.wells_changed.connect(self._sync_buttons)
        project.active_well_changed.connect(lambda _key: self._sync_buttons())
        project.well_updated.connect(lambda _key: self._sync_buttons())
        self._sync_buttons()

    def refresh_theme(self):
        # Icons are cached per theme; re-fetch so they recolor.
        for button in self.buttons:
            button.setIcon(get_icon("download"))

    # ---- scope ----
    def export_scope(self) -> str:
        """``"active"`` or ``"all"``."""
        return "all" if self.scope_combo.currentText() == SCOPE_ALL else "active"

    def _all_wells_available(self) -> bool:
        wells = self.model.project.wells
        return len(wells) >= 2 and bool(wells_with_results(wells))

    def _sync_buttons(self):
        """Enable the scope choice and download buttons from the project state."""
        item = self.scope_combo.model().item(1)
        available = self._all_wells_available()
        if item is not None:
            item.setEnabled(available)
        if not available and self.scope_combo.currentIndex() == 1:
            self.scope_combo.setCurrentIndex(0)   # re-enters through the signal
            return
        if self.export_scope() == "all":
            enabled = available
        else:
            enabled = bool(self.model.calculated and self.model.results is not None)
        for button in self.buttons:
            button.setEnabled(enabled)

    def _stem(self, prefix: str = "petrophyter_results") -> str:
        project = self.model.project
        return default_file_stem(project.active, prefix) if self.export_scope() == "active" \
            else f"{prefix}_all_wells"

    def _on_export_csv(self):
        """Handle CSV export."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save CSV",
            f"{self._stem()}.csv",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not file_path:
            return
        if self.export_scope() == "all":
            self._service.export_csv_wells(self.model.project.wells, file_path)
        else:
            self.export_csv.emit(file_path)

    def _on_export_excel(self):
        """Handle Excel export."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Excel",
            f"{self._stem()}.xlsx",
            "Excel Files (*.xlsx);;All Files (*)",
        )
        if not file_path:
            return
        if self.export_scope() == "all":
            self._service.export_excel_wells(self.model.project.wells, file_path)
        else:
            self.export_excel.emit(file_path)

    def _on_export_las(self):
        """Handle LAS export: one file (active well) or a folder of files (all wells)."""
        project = self.model.project
        if self.export_scope() == "all":
            directory = QFileDialog.getExistingDirectory(self, "Choose Folder for LAS Files")
            if directory:
                self._service.export_las_wells(project.wells, directory)
            return
        ds = project.active
        if ds is None or ds.las_data is None:
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save LAS",
            f"{default_file_stem(ds, 'petrophyter_las')}.las",
            "LAS Files (*.las);;All Files (*)",
        )
        if file_path:
            self._service.export_las(las_frame(ds), ds.well_info, file_path)

    def update_display(self):
        """Update display with analysis results."""
        # print(f"[DEBUG ExportTab] update_display called")
        # print(f"[DEBUG ExportTab] model.calculated = {self.model.calculated}")
        # print(f"[DEBUG ExportTab] model.results is None = {self.model.results is None}")

        if not self.model.calculated or self.model.results is None:
            self.reset_ui()
            return

        self.placeholder.setVisible(False)
        self.preview_table.setVisible(True)
        self._sync_buttons()

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
        """Report export success through the main window banner."""
        self.export_succeeded.emit(message)

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
        for button in self.buttons:
            button.setEnabled(False)

        # Show placeholder
        self.placeholder.setVisible(True)
