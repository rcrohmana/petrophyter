"""Methods panel of the LRLC Workbench: the full write-up of every LRLC method.

A list of the methods on the left, grouped by where the tool lives, and a readable page on
the right: the rendered equations, what the symbols mean, the criteria table, the assumptions
and limits as paragraphs, and the full references with links. The inline Method & Reference
strips under the tools link here; opened from one, a Back link returns to that place. Read-only; it reads ``modules.lrlc.methods.METHOD_TEXT``.
"""

import html
from typing import Dict, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtGui import QFont

from modules.lrlc.methods import METHOD_TEXT
from themes.helpers import set_status, set_variant
from themes.tokens import TYPOGRAPHY

from .equation_view import EquationView, LEGEND_PT, PANEL_PT
from .method_box import citation_text
from .references_dialog import _entry_html

TEXT_WIDTH = 800   # widest the paragraphs get, in pixels

# (group heading, method keys) in list order; any other METHOD_TEXT key follows under "Other".
METHOD_GROUPS = (
    ("Screening", ("screening", "rt_cutoff", "bvw", "buckles", "pickett")),
    ("Diagnosis", ("thomas_stieber",)),
    ("Remediation", ("rt_chain", "laminated", "pyrite", "qv", "variable_mn", "invasion")),
)


def grouped_keys():
    """METHOD_GROUPS completed with any METHOD_TEXT key that is not listed in it."""
    listed = {k for _, keys in METHOD_GROUPS for k in keys}
    groups = [(name, [k for k in keys if k in METHOD_TEXT]) for name, keys in METHOD_GROUPS]
    extra = [k for k in METHOD_TEXT if k not in listed]
    if extra:
        groups.append(("Other", extra))
    return [(name, keys) for name, keys in groups if keys]


def _heading(text: str) -> QLabel:
    label = QLabel(f"<b>{html.escape(text)}</b>")
    set_status(label, "muted")
    return label


def _paragraph(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class LrlcMethodsPanel(QWidget):
    """Method list and page. ``set_back(text)`` shows a Back link (``back_requested``)."""

    back_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.method_list = QListWidget()
        self.method_list.setFixedWidth(320)
        self.method_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.method_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.method_list.setObjectName("MethodList")
        self._items: Dict[str, QListWidgetItem] = {}
        for group, keys in grouped_keys():
            head = QListWidgetItem(group.upper())
            head.setFlags(Qt.ItemFlag.NoItemFlags)
            font = head.font()
            font.setBold(True)
            head.setFont(font)
            self.method_list.addItem(head)
            for key in keys:
                item = QListWidgetItem("   " + METHOD_TEXT[key].title)
                item.setData(Qt.ItemDataRole.UserRole, key)
                self.method_list.addItem(item)
                self._items[key] = item
        self.method_list.currentItemChanged.connect(self._on_item_changed)
        root.addWidget(self.method_list)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(16, 8, 16, 16)
        self.sheet = QWidget()
        self.sheet.setMaximumWidth(TEXT_WIDTH)
        outer.addWidget(self.sheet, 1, Qt.AlignmentFlag.AlignTop)
        outer.addStretch(0)
        sheet = QVBoxLayout(self.sheet)
        sheet.setContentsMargins(0, 0, 0, 0)
        sheet.setSpacing(8)

        self.back_button = QPushButton("Back")
        set_variant(self.back_button, "link")
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.clicked.connect(self.back_requested.emit)
        self.back_button.setVisible(False)
        sheet.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.title_label = QLabel()
        self.title_label.setWordWrap(True)
        self.equation_view = EquationView(size_pt=PANEL_PT)
        self.where_heading = _heading("Where")
        self.legend_widget = QWidget()
        self.legend_grid = QGridLayout(self.legend_widget)
        self.legend_grid.setContentsMargins(0, 0, 0, 0)
        self.legend_grid.setHorizontalSpacing(16)
        self.legend_grid.setVerticalSpacing(4)
        self.legend_grid.setColumnStretch(1, 1)
        self.criteria_heading = _heading("Criteria")
        self.criteria = _criteria_table()
        self.assumptions_heading = _heading("Assumptions")
        self.assumptions = _paragraph()
        self.limits_heading = _heading("Limits")
        self.limits = _paragraph()
        self.references_heading = _heading("References")
        self.references = QLabel()
        self.references.setWordWrap(True)
        self.references.setTextFormat(Qt.TextFormat.RichText)
        self.references.setOpenExternalLinks(True)
        self.references.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)

        for widget in (self.title_label, self.equation_view, self.where_heading,
                       self.legend_widget, self.criteria_heading, self.criteria,
                       self.assumptions_heading, self.assumptions, self.limits_heading,
                       self.limits, self.references_heading, self.references):
            sheet.addWidget(widget)
            if widget is self.equation_view:
                sheet.addSpacing(10)
        sheet.setAlignment(self.criteria, Qt.AlignmentFlag.AlignLeft)
        sheet.addStretch(1)
        self.scroll.setWidget(page)
        root.addWidget(self.scroll, 1)

        self._key: Optional[str] = None
        first = next(iter(self._items), None)
        if first:
            self.show_method(first)

    # ----------------------------------------------------------------- content
    @property
    def current_key(self) -> Optional[str]:
        return self._key

    def set_back(self, text: Optional[str]) -> None:
        """Show the Back link with ``text``; None hides it."""
        self.back_button.setText(text or "Back")
        self.back_button.setVisible(bool(text))

    def method_keys(self):
        return list(self._items)

    def show_method(self, key: str) -> bool:
        """Select a method; an unknown key leaves the page as it is."""
        item = self._items.get(key)
        if item is None:
            return False
        if self.method_list.currentItem() is not item:
            self.method_list.setCurrentItem(item)  # fills the page through _on_item_changed
        else:
            self._fill(key)
        return True

    def _on_item_changed(self, current, _previous):
        key = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        if key:
            self._fill(key)

    def _fill(self, key: str) -> None:
        info = METHOD_TEXT[key]
        self._key = key
        self.title_label.setText(
            f'<h3 style="margin: 0;">{html.escape(info.title)}</h3>')
        self.equation_view.set_lines(info.equation_tex)
        self._fill_legend(info.legend)
        self._fill_criteria(info.criteria)
        self.assumptions.setText(info.assumptions)
        self.limits.setText(info.limits)
        self.references.setText(self._references_html(info.refs))
        for widget in (self.references_heading, self.references):
            widget.setVisible(bool(info.refs))
        self.scroll.verticalScrollBar().setValue(0)

    def _fill_legend(self, rows) -> None:
        grid = self.legend_grid
        while grid.count():
            item = grid.takeAt(0)
            old = item.widget()
            if old is not None:
                old.hide()
                old.setParent(None)
                old.deleteLater()
        for r, (symbol, meaning) in enumerate(rows):
            view = EquationView(size_pt=LEGEND_PT)
            view.set_lines((symbol,))
            text = QLabel(meaning)
            text.setWordWrap(True)
            grid.addWidget(view, r, 0, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(text, r, 1, Qt.AlignmentFlag.AlignVCenter)
        self.where_heading.setVisible(bool(rows))
        self.legend_widget.setVisible(bool(rows))

    def _fill_criteria(self, rows) -> None:
        table = self.criteria
        table.setRowCount(len(rows))
        mono = QFont(TYPOGRAPHY["font_mono"], TYPOGRAPHY["font_body"])
        for r, (code, condition) in enumerate(rows):
            number = QTableWidgetItem(str(r + 1))
            number.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(r, 0, number)
            for c, text in ((1, code), (2, condition)):
                item = QTableWidgetItem(text)
                item.setFont(mono)
                table.setItem(r, c, item)
        table.setVisible(bool(rows))
        self.criteria_heading.setVisible(bool(rows))
        self._fit_criteria()

    def _fit_criteria(self) -> None:
        table = self.criteria
        rows = table.rowCount()
        if not rows:
            return
        table.resizeColumnsToContents()
        table.resizeRowsToContents()
        frame = 2 * table.frameWidth() + 2
        width = sum(table.columnWidth(c) for c in range(table.columnCount()))
        height = max(table.horizontalHeader().height(),
                     table.horizontalHeader().sizeHint().height())
        height += sum(table.rowHeight(r) for r in range(rows))
        table.setFixedSize(width + frame, height + frame)

    def showEvent(self, event):
        super().showEvent(event)
        # Fonts from the theme are only known once the table is polished and shown.
        self._fit_criteria()

    @staticmethod
    def _references_html(keys) -> str:
        if not keys:
            return ""
        return "<ul style='margin-left: 0px; -qt-list-indent: 0;'>" + "".join(
            _entry_html(k) for k in keys) + "</ul>"

    def short_citations(self, key: str) -> str:
        return citation_text(METHOD_TEXT[key].refs)

    def refresh_theme(self) -> None:
        self.equation_view.refresh_theme()
        self._fill(self._key) if self._key else None


def _criteria_table() -> QTableWidget:
    table = QTableWidget(0, 3)
    table.setHorizontalHeaderLabels(["#", "Criterion", "Condition"])
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.hide()
    return table
