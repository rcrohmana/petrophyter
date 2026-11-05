"""Small helpers shared by the LRLC Workbench panels (tables, notes, number formatting)."""

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHeaderView, QLabel, QScrollArea, QTableWidget, QTableWidgetItem, QWidget

from themes.helpers import set_status

WHOLE_WELL = "Whole well"


def fmt(value, digits=2) -> str:
    """A number to ``digits`` decimals; empty for None or a non-finite value."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    return "" if not np.isfinite(v) else f"{v:.{digits}f}"


def item(text, align_right=False) -> QTableWidgetItem:
    cell = QTableWidgetItem("" if text is None else str(text))
    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if align_right:
        cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return cell


def note(text="", status="muted") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    set_status(label, status)
    return label


def make_table(columns) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(list(columns))
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setStretchLastSection(True)
    return table


def scroll_area(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setWidget(widget)
    return area


def zone_title(zone) -> str:
    """Display name of a summary zone ("WELL" and None are the whole well)."""
    return WHOLE_WELL if zone in (None, "", "WELL") else str(zone)
