"""
Merge Service for Petrophyter PyQt
Wraps LAS merge operations for background execution.
"""

from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, QThreadPool
import pandas as pd
from typing import List, Optional
import traceback

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.las_handler import LASHandler, validate_same_well, MergeReport


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
        self.parsers = parsers
        self.file_names = file_names
        self.step_ft = step_ft
        self.gap_limit_ft = gap_limit_ft
        self.signals = MergeSignals()
    
    def run(self):
        """Execute the merge."""
        try:
            self.signals.started.emit()
            self.signals.progress.emit("Validating files...", 10)
            
            if len(self.parsers) < 2:
                self.signals.error.emit("Need at least 2 valid LAS files to merge")
                return
            
            # Validate same well
            is_same_well, well_names = validate_same_well(self.parsers)
            
            self.signals.progress.emit("Merging files...", 30)
            
            handler = LASHandler()
            result = handler.merge_las_files(
                self.parsers,
                file_identifiers=self.file_names,
                step_ft=self.step_ft,
                gap_limit_ft=self.gap_limit_ft
            )
            
            self.signals.progress.emit("Finalizing...", 90)
            
            merged_df = result['merged_df']
            merge_report = result['merge_report']
            
            self.signals.progress.emit("Merge complete!", 100)
            self.signals.completed.emit(merged_df, merge_report)
            
        except Exception as e:
            self.signals.error.emit(f"Merge failed: {str(e)}\n{traceback.format_exc()}")


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
