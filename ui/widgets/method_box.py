"""Method & Reference box shown under the LRLC tools."""

import html

from PyQt6.QtGui import QFont
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


class MethodReferenceBox(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Method & Reference", parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        self.title_label = QLabel()
        set_status(self.title_label, "muted")
        self.equation = QPlainTextEdit()
        self.equation.setReadOnly(True)
        self.equation.setFont(QFont(TYPOGRAPHY["font_mono"], TYPOGRAPHY["font_body"]))
        self.equation.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.equation.setMaximumHeight(130)
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
        self.assumptions.setText(f"<b>Assumptions.</b> {html.escape(info.assumptions)}")
        self.limits.setText(f"<b>Limits.</b> {html.escape(info.limits)}")
        self.citations.setText(
            f"References: {html.escape(citation_text(info.refs))}" if info.refs else ""
        )
        self.citations.setVisible(bool(info.refs))
