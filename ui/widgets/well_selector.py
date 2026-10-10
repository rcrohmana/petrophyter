"""Toolbar combo that switches the active well of a Project."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QComboBox


class WellSelector(QComboBox):
    """One entry per well (data = well key). ``well_selected`` fires only on user choice."""

    well_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WellSelector")
        self.setMinimumWidth(160)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.setToolTip("Active well")
        self._project = None
        self.activated.connect(self._on_activated)
        self._refresh()

    def set_project(self, project):
        if self._project is not None:
            self._project.wells_changed.disconnect(self._refresh)
            self._project.active_well_changed.disconnect(self._refresh)
        self._project = project
        if project is not None:
            project.wells_changed.connect(self._refresh)
            project.active_well_changed.connect(self._refresh)
        self._refresh()

    def _refresh(self, *_args):
        wells = self._project.wells if self._project is not None else []
        self.blockSignals(True)
        try:
            self.clear()
            if not wells:
                self.addItem("No wells")
                self.setEnabled(False)
                return
            for ds in wells:
                self.addItem(ds.display_name or ds.key, ds.key)
                self.setItemData(self.count() - 1, ds.key, Qt.ItemDataRole.ToolTipRole)
            self.setEnabled(True)
            index = self.findData(self._project.active_key)
            self.setCurrentIndex(max(index, 0))
        finally:
            self.blockSignals(False)

    def _on_activated(self, index):
        key = self.itemData(index)
        if key:
            self.well_selected.emit(key)
