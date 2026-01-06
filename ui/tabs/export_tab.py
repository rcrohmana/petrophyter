"""
Export Tab for Petrophyter PyQt
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QGroupBox, QPushButton, QTableView,
    QFileDialog, QMessageBox, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal

from .qc_tab import PandasTableModel


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
        content = QWidget()
        content_layout = QVBoxLayout(content)
        
        # =====================================================================
        # DOWNLOAD BUTTONS
        # =====================================================================
        download_group = QGroupBox("Download Results")
        download_layout = QHBoxLayout(download_group)
        
        self.csv_btn = QPushButton("📥 Download CSV")
        self.csv_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 10px 20px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #a5d6a7;
            }
        """)
        self.csv_btn.clicked.connect(self._on_export_csv)
        download_layout.addWidget(self.csv_btn)
        
        self.excel_btn = QPushButton("📥 Download Excel")
        self.excel_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                font-weight: bold;
                padding: 10px 20px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:disabled {
                background-color: #90CAF9;
            }
        """)
        self.excel_btn.clicked.connect(self._on_export_excel)
        download_layout.addWidget(self.excel_btn)
        
        download_layout.addStretch()
        
        content_layout.addWidget(download_group)
        
        # =====================================================================
        # RESULTS PREVIEW
        # =====================================================================
        preview_group = QGroupBox("Results Preview")
        preview_layout = QVBoxLayout(preview_group)
        
        self.preview_table = QTableView()
        self.preview_model = PandasTableModel()
        self.preview_table.setModel(self.preview_model)
        self.preview_table.setMinimumHeight(400)
        preview_layout.addWidget(self.preview_table)
        
        content_layout.addWidget(preview_group)
        
        # Placeholder
        self.placeholder = QLabel("👈 Run analysis first to export results")
        self.placeholder.setStyleSheet("color: #4A4540; background-color: transparent; font-size: 14px;")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(self.placeholder)
        
        content_layout.addStretch()
        
        scroll.setWidget(content)
        layout.addWidget(scroll)
        
        # Initially disable buttons
        self.csv_btn.setEnabled(False)
        self.excel_btn.setEnabled(False)
    
    def _on_export_csv(self):
        """Handle CSV export."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save CSV",
            "petrophyter_results.csv",
            "CSV Files (*.csv);;All Files (*)"
        )
        if file_path:
            self.export_csv.emit(file_path)
    
    def _on_export_excel(self):
        """Handle Excel export."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Excel",
            "petrophyter_results.xlsx",
            "Excel Files (*.xlsx);;All Files (*)"
        )
        if file_path:
            self.export_excel.emit(file_path)
    
    def update_display(self):
        """Update display with analysis results."""
        if not self.model.calculated or self.model.results is None:
            self.placeholder.setVisible(True)
            self.csv_btn.setEnabled(False)
            self.excel_btn.setEnabled(False)
            return
        
        self.placeholder.setVisible(False)
        self.csv_btn.setEnabled(True)
        self.excel_btn.setEnabled(True)
        
        # Update preview table (first 50 rows)
        preview_df = self.model.results.head(50).copy()
        self.preview_model.set_dataframe(preview_df)
    
    def show_export_success(self, message: str):
        """Show export success message."""
        QMessageBox.information(self, "Export Complete", message)
    
    def show_export_error(self, message: str):
        """Show export error message."""
        QMessageBox.critical(self, "Export Error", message)
