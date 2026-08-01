"""
Export Service for Petrophyter PyQt
Handles export functionality for results.
"""

from PyQt6.QtCore import QObject, pyqtSignal
import io
import json
import os
import tempfile
from contextlib import contextmanager

import pandas as pd

from modules.las_handler import export_merged_las


@contextmanager
def _atomic_target(file_path: str, temporary_suffix: str = None):
    """Yield a same-directory temporary path and atomically publish it."""
    final_path = os.fspath(file_path)
    directory = os.path.dirname(os.path.abspath(final_path)) or "."
    prefix = f".{os.path.basename(final_path)}."
    suffix = temporary_suffix or os.path.splitext(final_path)[1] or ".tmp"
    fd, temporary_path = tempfile.mkstemp(
        prefix=prefix, suffix=suffix, dir=directory
    )
    os.close(fd)
    try:
        yield temporary_path
        os.replace(temporary_path, final_path)
    except Exception:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


def _summary_frame(summary: dict) -> pd.DataFrame:
    """Serialize summary values into Excel-safe key/value rows."""
    if not isinstance(summary, dict):
        raise ValueError("summary must be a dictionary")

    rows = []
    for key, value in summary.items():
        if isinstance(value, (dict, list, tuple, set)):
            value = json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
        elif value is None:
            value = ""
        rows.append((str(key), value))
    return pd.DataFrame(rows, columns=["Parameter", "Value"])


def _validate_results(results: pd.DataFrame) -> None:
    if not isinstance(results, pd.DataFrame):
        raise ValueError("results must be a pandas DataFrame")


class ExportService(QObject):
    """
    Service for exporting analysis results.
    """
    
    export_complete = pyqtSignal(str)  # success message
    export_error = pyqtSignal(str)  # error message
    
    def __init__(self, parent=None):
        super().__init__(parent)
    
    def export_csv(self, results: pd.DataFrame, file_path: str) -> bool:
        """Export results to CSV file without corrupting an existing target."""
        try:
            _validate_results(results)
            with _atomic_target(file_path) as temporary_path:
                results.to_csv(temporary_path, index=False)
            self.export_complete.emit(f"Exported to {file_path}")
            return True
        except PermissionError:
            self.export_error.emit(
                "CSV export failed: close the destination file and check folder permissions"
            )
            return False
        except Exception as e:
            self.export_error.emit(f"CSV export failed: {str(e)}")
            return False

    def export_excel(self, results: pd.DataFrame, summary: dict, file_path: str) -> bool:
        """Export results and a nested-value-safe summary to Excel."""
        try:
            _validate_results(results)
            summary_df = _summary_frame(summary)
            with _atomic_target(file_path, ".xlsx") as temporary_path:
                with pd.ExcelWriter(temporary_path, engine="openpyxl") as writer:
                    results.to_excel(writer, sheet_name="Results", index=False)
                    summary_df.to_excel(writer, sheet_name="Summary", index=False)
            self.export_complete.emit(f"Exported to {file_path}")
            return True
        except PermissionError:
            self.export_error.emit(
                "Excel export failed: close the destination file and check folder permissions"
            )
            return False
        except Exception as e:
            self.export_error.emit(f"Excel export failed: {str(e)}")
            return False

    def export_las(self, merged_df: pd.DataFrame, well_info: dict, file_path: str) -> bool:
        """Export merged data to LAS using UTF-8 and an atomic target."""
        try:
            if not isinstance(merged_df, pd.DataFrame):
                raise ValueError("merged_df must be a pandas DataFrame")
            las_content = export_merged_las(merged_df, well_info)
            with _atomic_target(file_path) as temporary_path:
                with open(temporary_path, "w", encoding="utf-8") as handle:
                    handle.write(las_content)
            self.export_complete.emit(f"Exported to {file_path}")
            return True
        except PermissionError:
            self.export_error.emit(
                "LAS export failed: close the destination file and check folder permissions"
            )
            return False
        except Exception as e:
            self.export_error.emit(f"LAS export failed: {str(e)}")
            return False

    def get_csv_string(self, results: pd.DataFrame) -> str:
        """Get CSV data as string."""
        _validate_results(results)
        buffer = io.StringIO()
        results.to_csv(buffer, index=False)
        return buffer.getvalue()

    def get_excel_bytes(self, results: pd.DataFrame, summary: dict) -> bytes:
        """Get Excel data as bytes using the same summary schema as file export."""
        _validate_results(results)
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            results.to_excel(writer, sheet_name="Results", index=False)
            _summary_frame(summary).to_excel(writer, sheet_name="Summary", index=False)
        return buffer.getvalue()
