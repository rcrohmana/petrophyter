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
from themes.helpers import set_status
from services.export_service import (
    ALL_DEPTHS, ExportService, FIELD_TOTAL_RULE, apply_depth_range, blockers_text,
    default_file_stem, depth_interval_label, export_blockers, las_frame,
    provenance_block, well_label, wells_with_results,
)

# Answers of the freshness confirmation.
CONFIRM_RUN, CONFIRM_EXPORT, CONFIRM_CANCEL = "run", "export", "cancel"

SCOPE_ACTIVE = "Active well"
SCOPE_ALL = "All wells"
PREVIEW_ROWS = 500
PREVIEW_TITLE = "Results Preview"


class ExportTab(QWidget):
    """Export Tab - export results to CSV/Excel."""

    export_csv = pyqtSignal(str)  # file path
    export_excel = pyqtSignal(str)  # file path
    export_succeeded = pyqtSignal(str)  # message for the banner
    run_wells_requested = pyqtSignal(list)  # keys of the out-of-date wells to run first

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
        self.scope_combo.currentIndexChanged.connect(self._on_scope_changed)
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

        # Rock-type definitions (project data, not a well result): shown once defined
        self.definitions_btn = QPushButton("Export definitions")
        self.definitions_btn.setIcon(get_icon("download"))
        self.definitions_btn.setToolTip("Rock-type definitions of the project as CSV")
        self.definitions_btn.clicked.connect(self._on_export_definitions)
        self.definitions_btn.setVisible(False)
        download_layout.addWidget(self.definitions_btn)

        download_layout.addStretch()

        content_layout.addWidget(download_group)

        # =====================================================================
        # RESULTS PREVIEW
        # =====================================================================
        self.preview_group = QGroupBox(PREVIEW_TITLE)
        preview_group = self.preview_group
        preview_layout = QVBoxLayout(preview_group)

        # Freshness of the wells in the export scope
        self.status_line = QLabel("")
        self.status_line.setWordWrap(True)
        preview_layout.addWidget(self.status_line)

        # All-wells scope: the preview shows the active well; this says what the export holds
        self.scope_note = QLabel("")
        self.scope_note.setWordWrap(True)
        preview_layout.addWidget(self.scope_note)

        # Filter controls: the interval choice applies to the preview and the export
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Depth interval:"))
        self.interval_combo = QComboBox()
        self.interval_combo.addItems([ALL_DEPTHS, depth_interval_label((0, 0))])
        self.interval_combo.setToolTip(
            "Applies to the preview and to the exported files (CSV, Excel and LAS)")
        filter_layout.addWidget(self.interval_combo)
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

        self.interval_combo.currentIndexChanged.connect(lambda _i: self._update_table_view())
        self.top_md_spin.valueChanged.connect(self._on_interval_edited)
        self.bottom_md_spin.valueChanged.connect(self._on_interval_edited)
        self._refresh_interval_item()

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

    # ---- depth interval (U9) ----
    def _interval_valid(self) -> bool:
        return self.bottom_md_spin.value() > self.top_md_spin.value()

    def _refresh_interval_item(self):
        """Keep the "Selected interval" entry in step with the Top/Bottom MD boxes."""
        valid = self._interval_valid()
        self.interval_combo.setItemText(1, depth_interval_label(
            (self.top_md_spin.value(), self.bottom_md_spin.value())))
        item = self.interval_combo.model().item(1)
        if item is not None:
            item.setEnabled(valid)
        self.interval_combo.setItemData(
            1, "" if valid else "Set a Bottom MD below the Top MD to use an interval",
            Qt.ItemDataRole.ToolTipRole)

    def _on_interval_edited(self, _value=None):
        self._refresh_interval_item()
        if self.interval_combo.currentIndex() == 1 and not self._interval_valid():
            self.interval_combo.setCurrentIndex(0)   # re-enters through the signal
            return
        if self.interval_combo.currentIndex() == 1:
            self._update_table_view()

    def depth_range(self):
        """``(top, bottom)`` when "Selected interval" is chosen, else ``None`` (all depths)."""
        if self.interval_combo.currentIndex() == 1 and self._interval_valid():
            return (self.top_md_spin.value(), self.bottom_md_spin.value())
        return None

    def _on_scope_changed(self, _index=None):
        self._sync_buttons()
        self._update_table_view()

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
        self.definitions_btn.setVisible(bool((self.model.project.rock_types or {}).get("sets")))
        self._update_status_line(enabled)

    def _scope_wells(self) -> list:
        project = self.model.project
        if self.export_scope() == "all":
            return list(project.wells)
        return [project.active] if project.active is not None else []

    def _update_status_line(self, enabled: bool):
        """Say whether the wells in scope are current (set_status colours it)."""
        if not enabled:
            self.status_line.setText("")
            set_status(self.status_line, None)
            return
        text = blockers_text(export_blockers(self._scope_wells()))
        if text:
            self.status_line.setText(text)
            set_status(self.status_line, "warning")
        else:
            self.status_line.setText("Ready — results current")
            set_status(self.status_line, "success")

    # ---- freshness confirmation ----
    def _confirm_export(self, blockers: dict) -> str:
        """Ask what to do about out-of-date or failed wells (a confirmation, so a modal).

        Returns ``CONFIRM_RUN``, ``CONFIRM_EXPORT`` or ``CONFIRM_CANCEL``.
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Results are not current")
        box.setText(blockers_text(blockers, with_ready=True))
        notes = [FIELD_TOTAL_RULE]
        left_out = [well_label(ds) for ds in blockers["failed_no_results"]]
        if left_out:
            notes.append("Not exported (latest run failed, no earlier results): "
                         + ", ".join(left_out) + ".")
        box.setInformativeText(" ".join(notes))
        run_btn = None
        if blockers["out_of_date"]:
            run_btn = box.addButton("Run out-of-date wells",
                                    QMessageBox.ButtonRole.AcceptRole)
        export_btn = box.addButton("Export last successful results",
                                   QMessageBox.ButtonRole.ActionRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if run_btn is not None and clicked is run_btn:
            return CONFIRM_RUN
        if clicked is export_btn:
            return CONFIRM_EXPORT
        return CONFIRM_CANCEL

    def _proceed(self) -> bool:
        """True when the export may go ahead; asks first if a well is stale or failed."""
        blockers = export_blockers(self._scope_wells())
        if not (blockers["out_of_date"] or blockers["failed"] or blockers["failed_no_results"]):
            return True
        answer = self._confirm_export(blockers)
        if answer == CONFIRM_RUN:
            self.run_wells_requested.emit([ds.key for ds in blockers["out_of_date"]])
        return answer == CONFIRM_EXPORT

    def _stem(self, prefix: str = "petrophyter_results") -> str:
        project = self.model.project
        return default_file_stem(project.active, prefix) if self.export_scope() == "active" \
            else f"{prefix}_all_wells"

    def _on_export_csv(self):
        """Handle CSV export."""
        if not self._proceed():
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save CSV",
            f"{self._stem()}.csv",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not file_path:
            return
        depth_range = self.depth_range()
        if self.export_scope() == "all":
            self._service.export_csv_wells(self.model.project.wells, file_path, depth_range)
        elif self.model.calculated and self.model.results is not None:
            self._service.export_csv(
                apply_depth_range(self.model.results, depth_range), file_path,
                provenance_block(self.model.project.active, depth_range))

    def _on_export_excel(self):
        """Handle Excel export."""
        if not self._proceed():
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Excel",
            f"{self._stem()}.xlsx",
            "Excel Files (*.xlsx);;All Files (*)",
        )
        if not file_path:
            return
        depth_range = self.depth_range()
        if self.export_scope() == "all":
            self._service.export_excel_wells(self.model.project.wells, file_path, depth_range)
        elif (self.model.calculated and self.model.results is not None
              and self.model.summary is not None):
            self._service.export_excel(
                apply_depth_range(self.model.results, depth_range), self.model.summary,
                file_path, provenance_block(self.model.project.active, depth_range))

    def _on_export_las(self):
        """Handle LAS export: one file (active well) or a folder of files (all wells)."""
        if not self._proceed():
            return
        project = self.model.project
        depth_range = self.depth_range()
        if self.export_scope() == "all":
            directory = QFileDialog.getExistingDirectory(self, "Choose Folder for LAS Files")
            if directory:
                self._service.export_las_wells(project.wells, directory, depth_range)
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
            self._service.export_las(apply_depth_range(las_frame(ds), depth_range),
                                     ds.well_info, file_path,
                                     provenance_block(ds, depth_range))

    def _on_export_definitions(self):
        """Save the rock-type definitions table (project level, no freshness check)."""
        defs = self.model.project.rock_types
        if not (defs or {}).get("sets"):
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Rock-Type Definitions", "petrophyter_rock_type_definitions.csv",
            "CSV Files (*.csv);;All Files (*)")
        if file_path:
            self._service.export_rock_type_definitions(defs, file_path)

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

        # The preview shows the active well, filtered by the same interval as the export
        filtered_df = apply_depth_range(self.model.results, self.depth_range())

        # Update preview table (limit to PREVIEW_ROWS rows)
        preview_df = filtered_df.head(PREVIEW_ROWS).copy()
        self._update_preview_title(len(preview_df), len(filtered_df))
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

    def _update_preview_title(self, shown: int, total: int):
        """Say what the preview shows, and for all wells what the export holds."""
        active = self.model.project.active
        well = f" (well {well_label(active)})" if active is not None else ""
        self.preview_group.setTitle(
            f"Preview \u2014 showing {shown:,} of {total:,} rows{well}")
        if self.export_scope() == "all":
            depth_range = self.depth_range()
            ready = wells_with_results(self.model.project.wells)
            rows = sum(len(apply_depth_range(ds.results, depth_range)) for ds in ready)
            wells = f"{len(ready)} well" if len(ready) == 1 else f"{len(ready)} wells"
            self.scope_note.setText(f"Export contains {wells}, {rows:,} rows")
            self.scope_note.setVisible(True)
        else:
            self.scope_note.setText("")
            self.scope_note.setVisible(False)

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
        self.preview_group.setTitle(PREVIEW_TITLE)
        self.scope_note.setText("")
        self.interval_combo.setCurrentIndex(0)
        self.preview_model.set_dataframe(pd.DataFrame())
        self.preview_table.setVisible(False)

        # Disable export buttons
        for button in self.buttons:
            button.setEnabled(False)

        # Show placeholder
        self.placeholder.setVisible(True)
