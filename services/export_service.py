"""
Export Service for Petrophyter PyQt
Handles export functionality for results.
"""

from PyQt6.QtCore import QObject, pyqtSignal
import pandas as pd
import io
from typing import Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.las_handler import export_merged_las


class ExportService(QObject):
    """
    Service for exporting analysis results.
    """
    
    export_complete = pyqtSignal(str)  # success message
    export_error = pyqtSignal(str)  # error message
    
    def __init__(self, parent=None):
        super().__init__(parent)
    
    def export_csv(self, results: pd.DataFrame, file_path: str) -> bool:
        """Export results to CSV file."""
        try:
            results.to_csv(file_path, index=False)
            self.export_complete.emit(f"Exported to {file_path}")
            return True
        except Exception as e:
            self.export_error.emit(f"CSV export failed: {str(e)}")
            return False
    
    def export_excel(self, results: pd.DataFrame, summary: dict, file_path: str) -> bool:
        """Export results and summary to Excel file."""
        try:
            with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                results.to_excel(writer, sheet_name='Results', index=False)
                
                # Summary sheet
                summary_df = pd.DataFrame([summary])
                summary_df.to_excel(writer, sheet_name='Summary', index=False)
            
            self.export_complete.emit(f"Exported to {file_path}")
            return True
        except Exception as e:
            self.export_error.emit(f"Excel export failed: {str(e)}")
            return False
    
    def export_las(self, merged_df: pd.DataFrame, well_info: dict, file_path: str) -> bool:
        """Export merged data to LAS file."""
        try:
            las_content = export_merged_las(merged_df, well_info)
            with open(file_path, 'w') as f:
                f.write(las_content)
            self.export_complete.emit(f"Exported to {file_path}")
            return True
        except Exception as e:
            self.export_error.emit(f"LAS export failed: {str(e)}")
            return False
    
    def get_csv_string(self, results: pd.DataFrame) -> str:
        """Get CSV data as string."""
        buffer = io.StringIO()
        results.to_csv(buffer, index=False)
        return buffer.getvalue()
    
    def get_excel_bytes(self, results: pd.DataFrame, summary: dict) -> bytes:
        """Get Excel data as bytes."""
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            results.to_excel(writer, sheet_name='Results', index=False)
            summary_df = pd.DataFrame([summary])
            summary_df.to_excel(writer, sheet_name='Summary', index=False)
        return buffer.getvalue()
