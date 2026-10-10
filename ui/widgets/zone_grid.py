"""Zones page of the Parameters window (spec §4.8): one row per zone, one column per parameter."""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from modules.pipeline import zone_diagnostic_note
from modules.param_scopes import SPECS, normalize_zone, validate_entry
from themes.colors import get_color

GRID_PARAMS = ("a", "m", "n", "rw", "rsh", "rho_matrix",
               "vsh_cutoff", "phi_cutoff", "sw_cutoff")
GR_COLUMN = "gr_baseline"
STATE_ROLE = Qt.ItemDataRole.UserRole + 1     # "set" | "inherited" | "warning" | "info"
ZONE_ROLE = Qt.ItemDataRole.UserRole + 2


def _fmt(value) -> str:
    if isinstance(value, bool) or value is None:
        return "" if value is None else str(value)
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


class ZoneParamGrid(QWidget):
    """Edit per-zone parameters for the well (Well scope) or every well (Project scope)."""

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self._busy = False
        self._zones = []
        self.columns = ("zone",) + GRID_PARAMS + (GR_COLUMN,)

        self.caption = QLabel("")
        self.caption.setObjectName("PlaceholderLabel")
        self.caption.setWordWrap(True)
        self.table = QTableWidget(0, len(self.columns))
        self.table.setHorizontalHeaderLabels(
            ["Zone"] + [SPECS[n].label for n in GRID_PARAMS] + ["GR clean–shale"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(180)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.caption)
        layout.addWidget(self.table)

        self.table.itemChanged.connect(self._on_item_changed)
        model.scope_changed.connect(self.refresh)
        model.project.active_well_changed.connect(self.refresh)
        model.project.wells_changed.connect(self.refresh)
        model.formation_tops_loaded.connect(self.refresh)
        model.scoped_params_changed.connect(self.refresh)
        self.refresh()

    # ---- scope ----
    def grid_scope(self) -> str:
        """"well" while editing the active well, else "project" (the zone is ignored)."""
        active = self.model.project.active is not None
        return "well" if self.model.edit_scope == "well" and active else "project"

    def zones(self):
        scope = self.grid_scope()
        zones = []
        if scope == "well":
            zones.extend(self.model.zones_for())
            zones.extend(self.model.project.active.zone_overrides)
        else:
            for well in self.model.project.wells:
                zones.extend(self.model.zones_for(well))
            zones.extend(self.model.project.zone_params)
        seen = []
        for zone in zones:
            zone = normalize_zone(zone)
            if zone and zone not in seen:
                seen.append(zone)
        return seen

    # ---- model -> table ----
    def refresh(self, *_args):
        if self._busy:
            return
        zones = self.zones()
        self._busy = True
        try:
            self.table.blockSignals(True)
            if zones != self._zones:
                self._zones = zones
                self.table.setRowCount(len(zones))
                for row, zone in enumerate(zones):
                    item = QTableWidgetItem(zone)
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    self.table.setItem(row, 0, item)
                    for col in range(1, len(self.columns)):
                        cell = QTableWidgetItem("")
                        if self.columns[col] == GR_COLUMN:
                            cell.setFlags(Qt.ItemFlag.ItemIsEnabled)
                        self.table.setItem(row, col, cell)
            scope = self.grid_scope()
            where = (self.model.project.active.display_name or self.model.project.active.key
                     if scope == "well" else "every well")
            self.caption.setText(
                f"Zone values for {where}. Muted cells inherit; type a value to "
                "override, clear the cell to inherit again, type auto for Rw / Rsh.")
            for row, zone in enumerate(zones):
                self._fill_row(row, zone, scope)
        finally:
            self.table.blockSignals(False)
            self._busy = False

    def _fill_row(self, row: int, zone: str, scope: str):
        flat, info = self.model.scope_view(scope, zone)
        muted = QBrush(QColor(get_color("text_muted")))
        warn = QBrush(QColor(get_color("warning")))
        limiting, note = self._limiting_cell(scope, zone)
        for col, name in enumerate(self.columns[1:], start=1):
            item = self.table.item(row, col)
            item.setData(ZONE_ROLE, zone)
            entry = info[name]
            if name == GR_COLUMN:
                lo, hi = flat.get("gr_min_manual"), flat.get("gr_max_manual")
                text = "auto" if entry["mode"] == "auto" else f"{_fmt(lo)}–{_fmt(hi)}"
            elif entry["mode"] == "auto":
                text = "auto"
            else:
                text = _fmt(flat.get(name))
            item.setText(text)
            if entry["here"]:
                value = flat.get(name) if entry["mode"] != "auto" else None
                message = validate_entry(name, value)
                state = "warning" if message else "set"
                item.setForeground(warn if message else QBrush())
                item.setToolTip(message or "Set for this zone")
            else:
                state = "inherited"
                item.setForeground(muted)
                source = str(entry["source"]).replace("·", " · ")
                item.setToolTip(source if source.startswith("auto") else f"Inherited from {source}")
            if name == limiting:
                state = note[0]
                item.setForeground(warn if state == "warning" else muted)
                item.setToolTip(note[1])
            item.setData(STATE_ROLE, state)

    def _limiting_cell(self, scope: str, zone: str):
        """``(param, (level, text))`` of the zone's limiting cutoff, from a fresh run of the well."""
        ds = self.model.project.active
        if scope != "well" or ds is None or not ds.calculated or ds.stale:
            return None, None
        diag = ((ds.summary or {}).get("zone_diagnostics") or {}).get(zone)
        note = zone_diagnostic_note(diag) if diag else None
        limiting = (diag or {}).get("limiting")
        return (limiting, note) if note and limiting in self.columns else (None, None)

    def refresh_theme(self):
        self._zones = []
        self.refresh()

    # ---- table -> model (explicit edits only) ----
    def _on_item_changed(self, item: QTableWidgetItem):
        if self._busy:
            return
        name = self.columns[item.column()]
        zone = item.data(ZONE_ROLE)
        if name in ("zone", GR_COLUMN) or not zone:
            return
        scope = self.grid_scope()
        text = item.text().strip().replace(",", ".")
        self._busy = True
        try:
            if not text:
                self.model.clear_entry(name, scope=scope, zone=zone)
            elif text.lower() == "auto":
                if SPECS[name].auto:
                    self.model.set_entry(name, "auto", scope=scope, zone=zone)
            else:
                try:
                    value = float(text)
                except ValueError:
                    return
                self.model.set_entry(name, "manual", value, scope=scope, zone=zone)
        except ValueError:
            pass
        finally:
            self._busy = False
            if self.zones() == self._zones:
                self.refresh()          # in place: no item is deleted inside the signal
            else:                       # rows change: rebuild once the edit is committed
                QTimer.singleShot(0, self.refresh)
