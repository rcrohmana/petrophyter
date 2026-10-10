"""Load Summary dialog: group several opened LAS files into wells."""
from typing import List, Optional, Tuple

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from models.project import display_name_for, make_well_key
from modules.las_utils import same_well
from services.load_service import group_files
from themes.icon_loader import get_icon

_COLUMNS = ["File", "Well", "Key", "Depth range (ft)", "Step", "Curves", "Notes", "Group"]
_SEPARATE = -1
_NOTE = "Files in the same group are merged into one well. Files from different wells are never merged."


def _depth_and_step(parser) -> Tuple[Optional[Tuple[float, float]], Optional[float]]:
    data = getattr(parser, "data", None)
    if data is None or len(data) == 0:
        return None, None
    col = "DEPTH" if "DEPTH" in data.columns else data.columns[0]
    depth = data[col].dropna().to_numpy(dtype=float)
    if depth.size == 0:
        return None, None
    step = float(np.median(np.abs(np.diff(depth)))) if depth.size > 1 else None
    return (float(depth.min()), float(depth.max())), step


class LoadSummaryDialog(QDialog):
    """One row per file with an editable well group; OK loads the wells."""

    def __init__(self, parsed: list, merge_step: float = 0.5, merge_gap: float = 5.0,
                 parent=None):
        super().__init__(parent)
        self.setObjectName("LoadSummaryDialog")
        self.setWindowTitle("Load LAS Files")
        self.setModal(True)
        self.resize(980, 420)
        self._parsed = list(parsed)
        self._proposed = group_files(self._parsed)
        self._combos = {}  # row -> QComboBox

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("PlaceholderLabel")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.table = QTableWidget(len(self._parsed), len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COLUMNS.index("Notes"), QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        form = QFormLayout()
        self.step_spin = QDoubleSpinBox()
        self.step_spin.setRange(0.1, 1.0)
        self.step_spin.setSingleStep(0.1)
        self.step_spin.setValue(min(max(float(merge_step), 0.1), 1.0))
        self.gap_spin = QDoubleSpinBox()
        self.gap_spin.setRange(1.0, 50.0)
        self.gap_spin.setSingleStep(1.0)
        self.gap_spin.setValue(min(max(float(merge_gap), 1.0), 50.0))
        form.addRow("Merge step (ft)", self.step_spin)
        form.addRow("Merge gap limit", self.gap_spin)
        layout.addLayout(form)

        self.note_label = QLabel(_NOTE)
        self.note_label.setObjectName("PlaceholderLabel")
        self.note_label.setWordWrap(True)
        layout.addWidget(self.note_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_button.setIcon(get_icon("folder-open"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._fill_table()
        self._refresh_state()

    def refresh_theme(self):
        self._ok_button.setIcon(get_icon("folder-open"))

    # ---- table ----
    def _group_label(self, index: int) -> str:
        first = self._proposed[index][0]
        name = display_name_for(first.well_info, first.path)
        return f"Well {index + 1}: {name}"

    def _fill_table(self):
        proposed_index = {}
        for gi, group in enumerate(self._proposed):
            for item in group:
                proposed_index[id(item)] = gi
        for row, item in enumerate(self._parsed):
            cells = self._cells(item)
            for col, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                cell.setFlags(Qt.ItemFlag.ItemIsEnabled if item.ok else Qt.ItemFlag.NoItemFlags)
                self.table.setItem(row, col, cell)
            notes_col = _COLUMNS.index("Notes")
            self.table.item(row, notes_col).setToolTip(self._note_tooltip(item))
            if not item.ok:
                continue
            combo = QComboBox()
            for gi in range(len(self._proposed)):
                combo.addItem(self._group_label(gi), gi)
            combo.addItem("Separate well", _SEPARATE)
            combo.setCurrentIndex(combo.findData(proposed_index[id(item)]))
            combo.currentIndexChanged.connect(self._refresh_state)
            self.table.setCellWidget(row, _COLUMNS.index("Group"), combo)
            self._combos[row] = combo

    def _cells(self, item) -> List[str]:
        if not item.ok:
            return [item.name, "", "", "", "", "", item.error or "Could not parse file", ""]
        info = item.well_info
        rng, step = _depth_and_step(item.parser)
        data = item.parser.data
        n_curves = max(len(data.columns) - 1, 0)
        warnings = self._warnings(item)
        notes = f"{len(warnings)} warning{'s' if len(warnings) != 1 else ''}" if warnings else ""
        return [
            item.name,
            display_name_for(info, item.path),
            make_well_key(info, item.path),
            f"{rng[0]:,.1f} - {rng[1]:,.1f}" if rng else "",
            f"{step:g}" if step else "",
            str(n_curves),
            notes,
            "",
        ]

    @staticmethod
    def _warnings(item) -> List[str]:
        lines = []
        if getattr(item.parser, "depth_unit_warning", None):
            lines.append(item.parser.depth_unit_warning)
        lines.extend(getattr(item.parser, "unit_warnings", None) or [])
        return lines

    def _note_tooltip(self, item) -> str:
        return item.error or "\n".join(self._warnings(item))

    # ---- grouping ----
    def groups(self) -> list:
        """Final grouping: a list of lists of ParsedFile (failed files excluded)."""
        by_group = {}
        order = []
        for row, item in enumerate(self._parsed):
            combo = self._combos.get(row)
            if combo is None:
                continue
            data = combo.currentData()
            token = ("sep", row) if data == _SEPARATE else ("grp", data)
            if token not in by_group:
                by_group[token] = []
                order.append(token)
            by_group[token].append(item)
        return [by_group[t] for t in order]

    def merge_settings(self) -> Tuple[float, float]:
        return self.step_spin.value(), self.gap_spin.value()

    def _conflict(self) -> Optional[str]:
        for group in self.groups():
            for i, a in enumerate(group):
                for b in group[i + 1:]:
                    if same_well(a.well_info, b.well_info) is False:
                        return (f"{a.name} and {b.name} are different wells and cannot "
                                "share a group. Move one to a different group.")
        return None

    def _refresh_state(self, *_):
        groups = self.groups()
        n = len(groups)
        failed = sum(1 for p in self._parsed if not p.ok)
        merging = any(len(g) > 1 for g in groups)
        self.step_spin.setEnabled(merging)
        self.gap_spin.setEnabled(merging)
        self._ok_button.setText(f"Load {n} well{'s' if n != 1 else ''}")
        text = f"{len(self._parsed)} LAS files selected."
        if failed:
            text += f" {failed} could not be read."
        self.summary_label.setText(text)
        conflict = self._conflict()
        if n == 0:
            self._ok_button.setEnabled(False)
            self._ok_button.setToolTip("No readable LAS files.")
        elif conflict:
            self._ok_button.setEnabled(False)
            self._ok_button.setToolTip(conflict)
        else:
            self._ok_button.setEnabled(True)
            self._ok_button.setToolTip("")
