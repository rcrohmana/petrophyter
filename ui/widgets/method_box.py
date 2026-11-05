"""Method & Reference box shown under the LRLC tools."""

import html

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontMetrics
from PyQt6.QtWidgets import QGroupBox, QLabel, QPlainTextEdit, QVBoxLayout

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
        self.equation = QPlainTextEdit()
        self.equation.setReadOnly(True)
        self.equation.setFont(QFont(TYPOGRAPHY["font_mono"], TYPOGRAPHY["font_body"]))
        self.equation.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.equation.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.assumptions = QLabel()
        self.limits = QLabel()
        self.citations = QLabel()
        for label in (self.title_label, self.assumptions, self.limits, self.citations):
            label.setWordWrap(True)
        set_status(self.citations, "muted")

        for widget in (self.title_label, self.equation, self.assumptions, self.limits,
                       self.citations):
            layout.addWidget(widget)

    def set_method(self, info: MethodInfo) -> None:
        self.title_label.setText(info.title)
        self.equation.setPlainText(info.equation)
        self._fit_equation_height()
        self.assumptions.setText(f"<b>Assumptions.</b> {html.escape(info.assumptions)}")
        self.limits.setText(f"<b>Limits.</b> {html.escape(info.limits)}")
        self.citations.setText(
            f"References: {html.escape(citation_text(info.refs))}" if info.refs else ""
        )
        self.citations.setVisible(bool(info.refs))

    def _fit_equation_height(self) -> None:
        """Show every line of the equation: no inner vertical scroll, no empty space."""
        lines = max(self.equation.document().blockCount(), 1)
        metrics = QFontMetrics(self.equation.font())
        margins = self.equation.contentsMargins()
        height = (lines * metrics.lineSpacing() + 2 * self.equation.document().documentMargin()
                  + margins.top() + margins.bottom() + 2 * self.equation.frameWidth())
        height += self.equation.horizontalScrollBar().sizeHint().height()
        self.equation.setFixedHeight(int(height) + 2)
