"""Multi-well import dialog: assign a tops or core file with a well column to loaded wells.

The dialog only edits an :class:`~modules.well_import.ImportPlan`; it never touches the
model. The caller reads ``dialog.plan`` after ``exec()`` and applies it.
"""
import os
from dataclasses import replace
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from modules.table_reader import list_sheets, read_table
from modules.well_import import ImportOptions, ImportPlan, build_import_plan, parse_import_file
from themes.helpers import set_status
from themes.icon_loader import get_icon

_ROLES = {
    "tops": [("well", "Well"), ("name", "Formation"), ("top", "Top"), ("bottom", "Bottom")],
    "core": [("well", "Well"), ("depth", "Depth"), ("porosity", "Porosity"),
             ("permeability", "Permeability"), ("grain_density", "Grain density")],
}
_DELIMITERS = {"\t": "tab", ",": "comma", ";": "semicolon", "|": "pipe"}
_ENCODINGS = {"utf-8-sig": "UTF-8", "utf-8": "UTF-8", "cp1252": "Windows-1252"}
_ACTION_TEXT = {"assign": "Assign", "keep": "Keep existing", "replace": "Replace"}
_HOW_TEXT = {"uwi": "UWI", "api": "API", "name": "name", "manual": "manual"}
_SKIP = "— Skip —"
_CHOOSE = "— Choose —"
_NOTE = ("Each well in the file is assigned to a loaded well. Nothing changes until you "
         "confirm; existing data is kept unless you choose Replace.")
_PREVIEW_ROWS = 5
_MAX_NOTE = 60


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


class MultiWellImportDialog(QDialog):
    """Preview and mapping of one multi-well tops or core file.

    Args:
        kind: ``"tops"`` or ``"core"``.
        path: the file.
        wells: ``WellRef`` snapshots of the loaded wells (``well_refs(project, kind)``).
        parsed: the file already parsed with ``options`` (parsed here when omitted).
        options: starting options.

    Raises:
        ValueError: the file cannot be read or has no well column.
    """

    def __init__(self, kind: str, path: str, wells: list, parsed=None,
                 options: Optional[ImportOptions] = None, parent=None):
        super().__init__(parent)
        self.setObjectName("MultiWellImportDialog")
        self.kind = kind
        self.path = path
        self.wells = list(wells)
        self.options = options or ImportOptions(kind=kind)
        self.parsed = parsed if parsed is not None else parse_import_file(path, self.options)
        self.plan: ImportPlan = build_import_plan(self.parsed, path, self.wells, self.options)
        self._frames: Dict[object, object] = {}
        self._selected = 0
        self._col: Dict[str, int] = {}
        self._column_combos: Dict[str, QComboBox] = {}
        self._match_combos: List[QComboBox] = []
        self._action_combos: List[QComboBox] = []
        self._scale_combos: List[QComboBox] = []
        self._has_error = False

        label = "formation tops" if kind == "tops" else "core data"
        self.setWindowTitle(f"Assign {label}")
        self.setModal(True)
        self.resize(1180, 680)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.file_label = QLabel()
        layout.addWidget(self.file_label)
        note = QLabel(_NOTE)
        note.setObjectName("PlaceholderLabel")
        note.setWordWrap(True)
        layout.addWidget(note)

        layout.addLayout(self._build_mapping())
        layout.addLayout(self._build_options())

        self.message_label = QLabel()
        self.message_label.setObjectName("PlaceholderLabel")
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)

        self.preview_label = QLabel()
        self.preview_label.setObjectName("PlaceholderLabel")
        layout.addWidget(self.preview_label)
        self.preview = QTableWidget(0, 0)
        self._plain_table(self.preview)
        self.preview.setMaximumHeight(170)
        layout.addWidget(self.preview)

        self.table = QTableWidget(0, 0)
        self._plain_table(self.table)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.cellClicked.connect(lambda r, _c: self._select_row(r))
        layout.addWidget(self.table, 1)

        self.not_in_file_label = QLabel()
        self.not_in_file_label.setObjectName("PlaceholderLabel")
        self.not_in_file_label.setWordWrap(True)
        layout.addWidget(self.not_in_file_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setIcon(get_icon("check"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate()

    def refresh_theme(self):
        self.ok_button.setIcon(get_icon("check"))

    # ---- construction ----
    @staticmethod
    def _plain_table(table: QTableWidget):
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.verticalHeader().setVisible(False)

    def _build_mapping(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        for col, (role, title) in enumerate(_ROLES[self.kind]):
            caption = QLabel(title)
            caption.setObjectName("PlaceholderLabel")
            combo = QComboBox()
            combo.setObjectName(f"column_{role}")
            combo.setToolTip(f"File column used as {title.lower()}")
            combo.activated.connect(self._on_column_changed)
            self._column_combos[role] = combo
            grid.addWidget(caption, 0, col)
            grid.addWidget(combo, 1, col)
            grid.setColumnStretch(col, 1)
        return grid

    def _build_options(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        self.unit_combo = QComboBox()
        self.unit_combo.setObjectName("unit_combo")
        for text, value in (("Auto", None), ("M", "M"), ("FT", "FT")):
            self.unit_combo.addItem(text, value)
        self.unit_combo.setToolTip("Depth unit of the file")
        self.unit_combo.activated.connect(self._on_unit_changed)
        self.unit_label = QLabel()
        self.unit_label.setObjectName("PlaceholderLabel")
        row.addWidget(QLabel("Depth unit"))
        row.addWidget(self.unit_combo)
        row.addWidget(self.unit_label)

        self.fill_check = QCheckBox("Blank well cells continue the well above")
        self.fill_check.setObjectName("fill_down_check")
        self.fill_check.setToolTip(
            "For tables exported from merged cells, where only the first row of each well "
            "names it.")
        self.fill_check.clicked.connect(self._on_fill_down_changed)
        row.addWidget(self.fill_check)

        self.last_combo = QComboBox()
        self.last_combo.setObjectName("last_bottom_combo")
        self.last_combo.addItem("Last formation: extend to log bottom", "log_bottom")
        self.last_combo.addItem("Last formation: stop at its top", "next_top")
        self.last_combo.setToolTip(
            "Applies to a last formation that has no bottom in the file.")
        self.last_combo.activated.connect(self._on_last_bottom_changed)
        self.last_combo.setVisible(self.kind == "tops")
        row.addWidget(self.last_combo)

        sheets = self._sheets()
        self.sheet_label = QLabel("Sheet")
        self.sheet_combo = QComboBox()
        self.sheet_combo.setObjectName("sheet_combo")
        for name in sheets:
            self.sheet_combo.addItem(name, name)
        self.sheet_combo.activated.connect(self._on_sheet_changed)
        self.sheet_label.setVisible(len(sheets) > 1)
        self.sheet_combo.setVisible(len(sheets) > 1)
        row.addWidget(self.sheet_label)
        row.addWidget(self.sheet_combo)

        self.tvd_check = QCheckBox("Core depths are TVD; use them as measured depth")
        self.tvd_check.setObjectName("tvd_check")
        self.tvd_check.clicked.connect(self._on_tvd_changed)
        row.addWidget(self.tvd_check)
        row.addStretch(1)
        return row

    def _sheets(self) -> List[str]:
        try:
            return list_sheets(self.path)
        except Exception:
            return []

    # ---- file headers and detection text ----
    def _frame(self):
        """The file's raw table for the current sheet (headers and preview rows)."""
        sheet = self.options.sheet
        if sheet not in self._frames:
            try:
                self._frames[sheet] = read_table(self.path, None, sheet=sheet).frame
            except Exception:
                self._frames[sheet] = None
        return self._frames[sheet]

    def _headers(self) -> List[str]:
        frame = self._frame()
        headers = [str(c) for c in frame.columns] if frame is not None else []
        for value in self.parsed.columns_detected.values():
            if value and value not in headers:
                headers.append(value)
        return headers

    def _detect_text(self) -> str:
        table = self.parsed.table_read
        parts = []
        if table is not None:
            if table.delimiter:
                parts.append(_DELIMITERS.get(table.delimiter, table.delimiter))
            elif table.sheet:
                parts.append(f"sheet {table.sheet}")
            encoding = _ENCODINGS.get(table.encoding)
            if encoding:
                parts.append(encoding)
            if table.decimal == ",":
                parts.append("decimal comma")
        name = os.path.basename(self.path)
        return f"{name}  ·  {', '.join(parts)}" if parts else name

    # ---- state -> controls ----
    def _sync_controls(self):
        headers = self._headers()
        detected = self.parsed.columns_detected
        for role, combo in self._column_combos.items():
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("— none —", None)
            for name in headers:
                combo.addItem(name, name)
            value = detected.get(role)
            combo.setCurrentIndex(max(combo.findData(value), 0) if value else 0)
            combo.blockSignals(False)
        self.file_label.setText(self._detect_text())
        self.unit_combo.blockSignals(True)
        self.unit_combo.setCurrentIndex(max(self.unit_combo.findData(self.options.depth_unit), 0))
        self.unit_combo.blockSignals(False)
        if self.options.depth_unit:
            self.unit_label.setText("")
        elif self.parsed.depth_unit_detected:
            unit = "metres" if self.plan.effective_unit == "M" else "feet"
            self.unit_label.setText(f"detected: {unit}")
        else:
            self.unit_label.setText("not detected; choose M or FT")
        self.fill_check.blockSignals(True)
        self.fill_check.setChecked(bool(self.parsed.fill_down))
        self.fill_check.blockSignals(False)
        self.last_combo.blockSignals(True)
        self.last_combo.setCurrentIndex(max(self.last_combo.findData(self.options.last_bottom), 0))
        self.last_combo.blockSignals(False)
        if self.sheet_combo.count() > 1:
            self.sheet_combo.blockSignals(True)
            wanted = self.options.sheet
            index = self.sheet_combo.findData(wanted) if isinstance(wanted, str) else int(wanted)
            self.sheet_combo.setCurrentIndex(max(index, 0))
            self.sheet_combo.blockSignals(False)
        tvd = self.kind == "core" and bool(getattr(self.parsed, "depth_is_tvd", False))
        self.tvd_check.setVisible(tvd)
        self.tvd_check.blockSignals(True)
        self.tvd_check.setChecked(bool(self.options.tvd_confirmed))
        self.tvd_check.blockSignals(False)
        if tvd:
            self.tvd_check.setToolTip(getattr(self.parsed, "tvd_warning", "") or "")

    def _populate(self):
        """Rebuild the whole table (after a new plan)."""
        self._sync_controls()
        plan = self.plan
        titles = ["File well", "Rows", "Depth range (ft)", "Match", "How", "Existing", "Action"]
        if self.kind == "core":
            titles.append("Porosity")
        titles.append("Notes")
        self._col = {t: i for i, t in enumerate(titles)}
        self.table.clear()
        self.table.setColumnCount(len(titles))
        self.table.setHorizontalHeaderLabels(titles)
        self.table.setRowCount(len(plan.rows))
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self._col["Notes"], QHeaderView.ResizeMode.Stretch)
        self._match_combos, self._action_combos, self._scale_combos = [], [], []
        for i, row in enumerate(plan.rows):
            for title in ("File well", "Rows", "Depth range (ft)", "How", "Existing", "Notes"):
                self.table.setItem(i, self._col[title], QTableWidgetItem())
            self.table.item(i, self._col["File well"]).setText(row.file_well)
            self.table.item(i, self._col["File well"]).setToolTip(", ".join(row.spellings))
            self.table.item(i, self._col["Rows"]).setText(str(row.rows))

            match = QComboBox()
            match.addItem(_SKIP, None)
            for ref in plan.wells:
                match.addItem(ref.display_name, ref.key)
            match.activated.connect(lambda _=0, r=i: self._on_target_changed(r))
            self.table.setCellWidget(i, self._col["Match"], match)
            self._match_combos.append(match)

            action = QComboBox()
            action.activated.connect(lambda _=0, r=i: self._on_action_changed(r))
            self.table.setCellWidget(i, self._col["Action"], action)
            self._action_combos.append(action)

            if self.kind == "core":
                scale = QComboBox()
                scale.addItem("Percent", "percent")
                scale.addItem("Fraction", "fraction")
                scale.setToolTip("How the porosity values of this well are read")
                scale.activated.connect(lambda _=0, r=i: self._on_scale_changed(r))
                self.table.setCellWidget(i, self._col["Porosity"], scale)
                self._scale_combos.append(scale)
        self._refresh_rows()
        if plan.rows:
            self._selected = min(self._selected, len(plan.rows) - 1)
            self.table.selectRow(self._selected)
        self._refresh_preview()
        self._refresh_state()

    def _row_notes(self, row) -> List[str]:
        notes = list(row.notes)
        if row.coverage_note:
            notes.append(row.coverage_note)
        if row.unit_fit:
            notes.append("depths fit the logs as " + ("metres" if row.unit_fit == "M" else "feet"))
        notes.extend(row.zone_impact)
        return notes

    def _refresh_rows(self):
        """Update every cell that depends on the plan (the Match item lists stay)."""
        plan = self.plan
        for i, row in enumerate(plan.rows):
            rng = row.depth_range
            self.table.item(i, self._col["Depth range (ft)"]).setText(
                f"{rng[0]:,.1f} - {rng[1]:,.1f}" if rng else "unit needed")
            self.table.item(i, self._col["How"]).setText(_HOW_TEXT.get(row.match_how, "—"))
            self.table.item(i, self._col["Existing"]).setText(
                row.existing if row.target_key else "")

            match = self._match_combos[i]
            match.blockSignals(True)
            unresolved = row.status == "ambiguous" and row.target_key is None
            match.setItemText(0, _CHOOSE if unresolved else _SKIP)
            match.setCurrentIndex(max(match.findData(row.target_key), 0))
            match.blockSignals(False)

            action = self._action_combos[i]
            action.blockSignals(True)
            action.clear()
            ref = plan._ref(row.target_key)
            if ref is None:
                action.addItem("Skip", "skip")
                action.setEnabled(False)
            elif ref.existing_count:
                action.addItem(_ACTION_TEXT["keep"], "keep")
                action.addItem(_ACTION_TEXT["replace"], "replace")
                action.setEnabled(True)
            else:
                action.addItem(_ACTION_TEXT["assign"], "assign")
                action.setEnabled(False)
            action.setCurrentIndex(max(action.findData(row.action), 0))
            action.blockSignals(False)

            if self.kind == "core":
                scale = self._scale_combos[i]
                scale.blockSignals(True)
                index = scale.findData(row.porosity_scale)
                scale.setCurrentIndex(max(index, 0))
                scale.setEnabled(index >= 0)
                scale.blockSignals(False)

            notes = self._row_notes(row)
            cell = self.table.item(i, self._col["Notes"])
            text = notes[0] if notes else ""
            if len(text) > _MAX_NOTE:
                text = text[:_MAX_NOTE - 1] + "…"
            if len(notes) > 1:
                text += f" (+{len(notes) - 1})"
            cell.setText(text)
            cell.setToolTip("\n".join(notes))

    def _refresh_preview(self):
        """First rows of the selected file well, with the mapped role over each column."""
        rows = self.plan.rows
        self.preview.clear()
        frame = self._frame()
        if not rows or frame is None or not len(frame.columns):
            self.preview_label.setText("")
            self.preview.setRowCount(0)
            self.preview.setColumnCount(0)
            return
        row = rows[min(self._selected, len(rows) - 1)]
        self.preview_label.setText(f"First rows of {row.file_well}")
        roles = {v: r for r, v in self.parsed.columns_detected.items() if v}
        titles = dict(_ROLES[self.kind])
        well_col = self.parsed.columns_detected.get("well")
        subset = frame
        if well_col in frame.columns:
            wanted = frame[well_col].astype(str).str.strip().isin(set(row.spellings))
            if wanted.any():
                subset = frame[wanted]
        subset = subset.head(_PREVIEW_ROWS)
        headers = []
        for col in frame.columns:
            role = roles.get(str(col))
            headers.append(f"{titles.get(role, role)}\n{col}" if role else f"\n{col}")
        self.preview.setColumnCount(len(headers))
        self.preview.setHorizontalHeaderLabels(headers)
        self.preview.setRowCount(len(subset))
        for r, values in enumerate(subset.itertuples(index=False, name=None)):
            for c, value in enumerate(values):
                self.preview.setItem(r, c, QTableWidgetItem("" if value is None else str(value)))
        self.preview.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)

    def _refresh_state(self):
        plan = self.plan
        self.ok_button.setText(f"Assign to {_plural(plan.changes(), 'well')}")
        blockers = plan.blockers()
        self.ok_button.setEnabled(not blockers)
        self.ok_button.setToolTip("\n".join(blockers))
        missing = plan.wells_not_in_file
        self.not_in_file_label.setText(
            f"Loaded wells not in this file: {', '.join(missing)}" if missing else "")
        if not self._has_error:
            lines = list(plan.notes)
            self.message_label.setText("\n".join(lines))
            set_status(self.message_label, "warning" if lines else "muted")

    # ---- errors ----
    def _show_error(self, text: str):
        if text == "no well column":
            text = "The file needs a well column."
        self._has_error = True
        self.message_label.setText(text)
        set_status(self.message_label, "error")

    # ---- changing options ----
    def _carry(self) -> dict:
        return {r.group_key: (r.target_key, r.match_how, r.action) for r in self.plan.rows}

    def _apply(self, options: ImportOptions, reparse: bool) -> bool:
        """Switch to ``options`` (re-parsing when needed), keeping the user's manual choices."""
        carry = self._carry()
        try:
            parsed = parse_import_file(self.path, options) if reparse else self.parsed
            plan = build_import_plan(parsed, self.path, self.wells, options)
        except ValueError as exc:
            self._show_error(str(exc))
            self._sync_controls()
            return False
        self._has_error = False
        for i, row in enumerate(plan.rows):
            saved = carry.get(row.group_key)
            if saved is None:
                continue
            target, how, action = saved
            if target != row.target_key and (how == "manual" or target is None):
                plan.set_target(i, target)
            if action != plan.rows[i].action and plan.rows[i].target_key is not None:
                plan.set_action(i, action)
        self.options, self.parsed, self.plan = options, parsed, plan
        self._populate()
        return True

    def _on_column_changed(self, *_):
        columns = {role: combo.currentData() for role, combo in self._column_combos.items()}
        self._apply(replace(self.options, columns=columns), reparse=True)

    def _on_unit_changed(self, *_):
        self._apply(replace(self.options, depth_unit=self.unit_combo.currentData()),
                    reparse=False)

    def _on_fill_down_changed(self, checked: bool):
        self._apply(replace(self.options, fill_down=bool(checked)), reparse=True)

    def _on_last_bottom_changed(self, *_):
        self.options.last_bottom = self.last_combo.currentData()

    def _on_sheet_changed(self, *_):
        self._apply(replace(self.options, sheet=self.sheet_combo.currentData(), columns=None),
                    reparse=True)

    def _on_tvd_changed(self, checked: bool):
        self.options.tvd_confirmed = bool(checked)
        self._refresh_state()

    def _on_scale_changed(self, row_index: int):
        row = self.plan.rows[row_index]
        scales = dict(self.options.porosity_scales)
        scales[row.file_well] = self._scale_combos[row_index].currentData()
        self._apply(replace(self.options, porosity_scales=scales), reparse=True)

    def _on_target_changed(self, row_index: int):
        self._select_row(row_index)
        self.plan.set_target(row_index, self._match_combos[row_index].currentData())
        self._refresh_rows()
        self._refresh_state()

    def _on_action_changed(self, row_index: int):
        self.plan.set_action(row_index, self._action_combos[row_index].currentData())
        self._refresh_rows()
        self._refresh_state()

    def _select_row(self, row_index: int):
        self._selected = row_index
        self.table.selectRow(row_index)
        self._refresh_preview()
