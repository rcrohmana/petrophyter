"""
Merge Service for Petrophyter PyQt
Wraps LAS merge operations for background execution.
"""

from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, QThreadPool
import logging
import math
import pandas as pd
from typing import List

from modules.las_handler import LASHandler, validate_same_well


logger = logging.getLogger(__name__)


class MergeSignals(QObject):
    """Signals for merge worker."""
    started = pyqtSignal()
    progress = pyqtSignal(str, int)
    completed = pyqtSignal(pd.DataFrame, object)  # (merged_df, merge_report)
    error = pyqtSignal(str)


class MergeWorker(QRunnable):
    """Worker for merging LAS files in background thread."""
    
    def __init__(self, parsers: List, file_names: List[str], step_ft: float, gap_limit_ft: float):
        super().__init__()
        # Snapshot caller-owned containers before the worker crosses threads.
        self.parsers = list(parsers)
        self.file_names = list(file_names)
        self.step_ft = step_ft
        self.gap_limit_ft = gap_limit_ft
        self.signals = MergeSignals()
    
    def run(self):
        """Execute the merge."""
        try:
            self.signals.started.emit()
            self.signals.progress.emit("Validating files...", 10)

            try:
                step_ft = float(self.step_ft)
            except (TypeError, ValueError):
                self.signals.error.emit("Merge step must be a finite number greater than zero")
                return
            try:
                gap_limit_ft = float(self.gap_limit_ft)
            except (TypeError, ValueError):
                self.signals.error.emit("Merge gap limit must be a finite number of zero or greater")
                return
            if not math.isfinite(step_ft) or step_ft <= 0:
                self.signals.error.emit("Merge step must be a finite number greater than zero")
                return
            if not math.isfinite(gap_limit_ft) or gap_limit_ft < 0:
                self.signals.error.emit("Merge gap limit must be a finite number of zero or greater")
                return

            if len(self.parsers) < 2:
                self.signals.error.emit("Need at least 2 valid LAS files to merge")
                return

            # Validate same well and make a visible, non-fatal warning.
            is_same_well, well_names = validate_same_well(self.parsers)
            if not is_same_well:
                well_list = ", ".join(str(name) for name in well_names) or "unknown"
                self.signals.progress.emit(
                    f"Warning: Files may be from different wells ({well_list}). Proceeding with merge...",
                    20,
                )

            self.signals.progress.emit("Merging files...", 30)

            handler = LASHandler()
            result = handler.merge_las_files(
                self.parsers,
                file_identifiers=self.file_names,
                step_ft=step_ft,
                gap_limit_ft=gap_limit_ft,
            )

            if not isinstance(result, dict):
                raise ValueError("Merge returned an invalid result")
            if "merged_df" not in result or "merge_report" not in result:
                raise ValueError("Merge result is missing merged_df or merge_report")
            merged_df = result["merged_df"]
            merge_report = result["merge_report"]
            if not isinstance(merged_df, pd.DataFrame):
                raise ValueError("Merge result merged_df must be a DataFrame")
            if merged_df.empty:
                raise ValueError("Merge produced an empty DataFrame")

            self.signals.progress.emit("Finalizing...", 90)
            self.signals.progress.emit("Merge complete!", 100)
            self.signals.completed.emit(merged_df, merge_report)

        except Exception as e:
            logger.exception("Merge failed")
            self.signals.error.emit(f"Merge failed: {str(e)}")


class MergeService(QObject):
    """
    Service for merging multiple LAS files.
    Manages background thread execution.
    """
    
    started = pyqtSignal()
    progress = pyqtSignal(str, int)
    completed = pyqtSignal(pd.DataFrame, object)
    error = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread_pool = QThreadPool()
    
    def merge_files(self, parsers: List, file_names: List[str], step_ft: float, gap_limit_ft: float):
        """Start merge in background thread."""
        worker = MergeWorker(parsers, file_names, step_ft, gap_limit_ft)
        worker.signals.started.connect(self.started.emit)
        worker.signals.progress.connect(self.progress.emit)
        worker.signals.completed.connect(self.completed.emit)
        worker.signals.error.connect(self.error.emit)
        
        self.thread_pool.start(worker)
