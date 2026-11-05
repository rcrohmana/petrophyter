"""Method & Reference box shown under the LRLC tools."""

import html

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontMetrics
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from modules import references
from modules.lrlc.methods import MethodInfo
from themes.helpers import set_status
from themes.tokens import TYPOGRAPHY


def citation_text(keys) -> str:
    """Short citations, '(to verify)' after the unverified ones."""
    out = []
    for key in keys:
        short = references.format_short(key)
        if references.REFERENCES[key].status != "verified":
            short += " (to verify)"
        out.append(short)
    return "; ".join(out)


TITLE = "Method & Reference"


class MethodReferenceBox(QGroupBox):
    def __init__(self, parent=None):
        # "&&": a single "&" in a group-box title is a mnemonic marker and is not drawn.
        super().__init__(TITLE.replace("&", "&&"), parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        self.title_label = QLabel()
        set_status(self.title_label, "muted")
        self.equation = _equation_box()
        self.criteria = QTableWidget(0, 3)
        self.criteria.setHorizontalHeaderLabels(["#", "Criterion", "Condition"])
        self.criteria.verticalHeader().setVisible(False)
        self.criteria.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.criteria.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.criteria.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.criteria.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        header = self.criteria.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.criteria.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.criteria.hide()
        self.equation_after = _equation_box()
        self.equation_after.hide()
        self.assumptions = QLabel()
        self.limits = QLabel()
        self.citations = QLabel()
        for label in (self.title_label, self.assumptions, self.limits, self.citations):
            label.setWordWrap(True)
        set_status(self.citations, "muted")

        for widget in (self.title_label, self.equation, self.criteria, self.equation_after,
                       self.assumptions, self.limits, self.citations):
            layout.addWidget(widget)

    def set_method(self, info: MethodInfo) -> None:
        self.title_label.setText(info.title)
        self.equation.setPlainText(info.equation)
        _fit_equation_height(self.equation)
        self._set_criteria(info.criteria)
        self.equation_after.setPlainText(info.equation_after)
        _fit_equation_height(self.equation_after)
        self.equation_after.setVisible(bool(info.equation_after))
        self.assumptions.setText(f"<b>Assumptions.</b> {html.escape(info.assumptions)}")
        self.limits.setText(f"<b>Limits.</b> {html.escape(info.limits)}")
        self.citations.setText(
            f"References: {html.escape(citation_text(info.refs))}" if info.refs else ""
        )
        self.citations.setVisible(bool(info.refs))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # The horizontal scrollbar of an equation box comes and goes with the width.
        _fit_equation_height(self.equation)
        _fit_equation_height(self.equation_after)
        self._fit_criteria()

    def showEvent(self, event):
        super().showEvent(event)
        # Fonts from the theme are only known once the box is polished and shown.
        self._fit_criteria()

    def _set_criteria(self, rows) -> None:
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
        self._fit_criteria()

    def _fit_criteria(self) -> None:
        """As wide and tall as the content: a compact table, not a full-width grid."""
        table = self.criteria
        rows = table.rowCount()
        if not rows:
            return
        table.resizeColumnsToContents()
        table.resizeRowsToContents()
        header = table.horizontalHeader()
        frame = 2 * table.frameWidth() + 2
        width = sum(table.columnWidth(c) for c in range(table.columnCount()))
        table.setFixedWidth(width + frame)
        height = max(header.height(), header.sizeHint().height())
        height += sum(table.rowHeight(r) for r in range(rows))
        table.setFixedHeight(height + frame)


def _equation_box() -> QPlainTextEdit:
    box = QPlainTextEdit()
    # The object name gets a monospace rule in the theme; the app-wide "*" font rule
    # would otherwise replace the font set here.
    box.setObjectName("MethodEquation")
    box.setReadOnly(True)
    box.setFont(QFont(TYPOGRAPHY["font_mono"], TYPOGRAPHY["font_body"]))
    box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    box.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return box


def _fit_equation_height(box: QPlainTextEdit) -> None:
    """Show every line of the equation: no inner vertical scroll, no empty space."""
    lines = max(box.document().blockCount(), 1)
    metrics = QFontMetrics(box.font())
    margins = box.contentsMargins()
    height = (lines * metrics.lineSpacing() + 2 * box.document().documentMargin()
              + margins.top() + margins.bottom() + 2 * box.frameWidth())
    widest = max((metrics.horizontalAdvance(line) for line in box.toPlainText().splitlines()),
                 default=0)
    room = box.width() - 2 * box.frameWidth() - 2 * box.document().documentMargin()
    if widest > room:
        height += box.horizontalScrollBar().sizeHint().height()
    box.setFixedHeight(int(height) + 2)
