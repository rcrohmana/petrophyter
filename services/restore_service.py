"""
Restore Service for Petrophyter PyQt
Rebuilds the wells of a v2 session on a pool thread. The worker only runs the
pure builder (``SessionService.build_wells_from_session``); the GUI thread
installs the result into the model.
"""

import copy
import logging
import threading
from typing import Dict

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from services.load_service import sanitize_error_detail
from services.session_service import RestoreCancelled, SessionService

logger = logging.getLogger(__name__)


class RestoreSignals(QObject):
    progress = pyqtSignal(str, int)         # "Restoring 3 of 10: BKS-03", percent
    completed = pyqtSignal(object, object)  # list[WellDataset], list[str] notes
    error = pyqtSignal(str)
    finished = pyqtSignal()                 # always last; lets the owner release the worker


class RestoreWorker(QRunnable):
    """Build the wells of a session off the GUI thread.

    ``generation`` is a token the owner compares with its current one when a
    signal arrives, so results of a superseded restore are dropped. ``cancel()``
    sets an event that the builder polls between wells; a cancelled worker emits
    only ``finished``. The session data is deep-copied on construction (GUI
    thread) so later edits cannot race with the build.
    """

    def __init__(self, session_data: Dict, generation: int = 0):
        super().__init__()
        self.generation = generation
        self.signals = RestoreSignals()
        self._session_data = copy.deepcopy(session_data)
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def _build(self):
        return SessionService().build_wells_from_session(
            self._session_data,
            progress=lambda message, percent: self.signals.progress.emit(message, percent),
            cancelled=self._cancel.is_set,
        )

    def run(self):
        try:
            try:
                datasets, notes = self._build()
            except RestoreCancelled:
                return
            except Exception as exc:
                logger.exception("Restoring the session failed")
                if not self._cancel.is_set():
                    self.signals.error.emit(
                        f"Failed to restore the session: {sanitize_error_detail(exc)}")
                return
            if not self._cancel.is_set():
                self.signals.completed.emit(datasets, notes)
        finally:
            self.signals.finished.emit()
