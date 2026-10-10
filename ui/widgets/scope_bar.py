"""Scope selector of the Parameters window (spec §4.8): Project | Well, plus a zone."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup, QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from themes.helpers import set_status

ALL_ZONES = "All zones"


def _repolish(widget: QWidget):
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


class ScopeBar(QWidget):
    """Drives ``model.set_edit_scope`` and follows the model back (no feedback loops)."""

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self._syncing = False
        self.setObjectName("ScopeBar")

        self.project_btn = QPushButton("Project")
        self.well_btn = QPushButton("Well")
        for button in (self.project_btn, self.well_btn):
            button.setCheckable(True)
        group = QButtonGroup(self)
        group.setExclusive(True)
        group.addButton(self.project_btn)
        group.addButton(self.well_btn)
        self.zone_combo = QComboBox()
        self.zone_combo.setMinimumContentsLength(14)
        self.zone_combo.setToolTip("Zone to edit (formation name)")
        self.caption = QLabel("")
        set_status(self.caption, "muted")

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(self.project_btn)
        row.addWidget(self.well_btn)
        row.addSpacing(12)
        row.addWidget(QLabel("Zone:"))
        row.addWidget(self.zone_combo)
        row.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)
        layout.addLayout(row)
        layout.addWidget(self.caption)

        self.project_btn.toggled.connect(self._on_user_scope)
        self.well_btn.toggled.connect(self._on_user_scope)
        self.zone_combo.activated.connect(self._on_user_scope)

        model.scope_changed.connect(self.refresh)
        model.project.active_well_changed.connect(self.refresh)
        model.project.wells_changed.connect(self.refresh)
        model.formation_tops_loaded.connect(self.refresh)
        model.scoped_params_changed.connect(self.refresh)
        self.refresh()

    # ---- user -> model ----
    def _on_user_scope(self, *_args):
        if self._syncing:
            return
        scope = "well" if self.well_btn.isChecked() else "project"
        zone = self.zone_combo.currentData()
        self.model.set_edit_scope(scope, zone)

    # ---- model -> widgets ----
    def zone_choices(self):
        """Zones offered by the combo: the active well's, project zones, the current one."""
        from modules.param_scopes import normalize_zone

        zones = []
        wells = [self.model.project.active] if self.model.edit_scope == "well" else self.model.project.wells
        for well in wells:
            if well is not None:
                zones.extend(self.model.zones_for(well))
        zones.extend(self.model.project.zone_params)
        if self.model.edit_zone:
            zones.append(self.model.edit_zone)
        seen = []
        for zone in zones:
            zone = normalize_zone(zone)
            if zone and zone not in seen:
                seen.append(zone)
        return seen

    def well_name(self) -> str:
        active = self.model.project.active
        return (active.display_name or active.key) if active is not None else ""

    def refresh(self, *_args):
        self._syncing = True
        try:
            name = self.well_name()
            self.well_btn.setText(f"Well: {name}" if name else "Well")
            self.well_btn.setEnabled(bool(name))
            is_well = self.model.edit_scope == "well" and bool(name)
            self.well_btn.setChecked(is_well)
            self.project_btn.setChecked(not is_well)
            for button in (self.project_btn, self.well_btn):
                button.setProperty("variant", "primary" if button.isChecked() else None)
                _repolish(button)

            self.zone_combo.clear()
            self.zone_combo.addItem(ALL_ZONES, None)
            for zone in self.zone_choices():
                self.zone_combo.addItem(zone, zone)
            index = self.zone_combo.findData(self.model.edit_zone)
            self.zone_combo.setCurrentIndex(max(index, 0))
            self.caption.setText(self.caption_text())
        finally:
            self._syncing = False

    def caption_text(self) -> str:
        zone = self.model.edit_zone
        if self.model.edit_scope == "well" and self.well_name():
            where = self.well_name()
            return f"{zone} in {where}" if zone else f"Values for {where}"
        return f"{zone} in every well" if zone else "Values for every well"
