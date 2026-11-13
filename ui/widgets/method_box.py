"""Compact Method & Reference strip shown under the LRLC tools.

Title, rendered equations, one line of short citations and a link that opens the full
write-up (assumptions, limits, references) in the Methods panel of the LRLC Workbench. The
compact form (``compact=True``, used on the Remediation pages) is one line: the method title,
the short citations and the link, with no equations.
"""

import html
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QGuiApplication
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from modules import references
from modules.lrlc.methods import METHOD_TEXT, MethodInfo
from themes.helpers import set_status, set_variant

from .equation_view import EquationView


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
LINK_TEXT = "Assumptions, limits and references"


def method_key(info: MethodInfo) -> Optional[str]:
    """Key of ``info`` in METHOD_TEXT, None for a text that is not one of the shipped methods."""
    for key, known in METHOD_TEXT.items():
        if known is info:
            return key
    return None


class MethodReferenceBox(QGroupBox):
    """Compact strip. Its link emits ``method_requested(key)`` and asks the enclosing LRLC tab
    (the first ancestor with ``open_method``, else ``show_panel``) to open the Methods panel at
    that key. ``compact=True`` gives the one-line form without a title or equations."""

    method_requested = pyqtSignal(str)

    def __init__(self, parent=None, compact: bool = False):
        # "&&": a single "&" in a group-box title is a mnemonic marker and is not drawn.
        super().__init__("" if compact else TITLE.replace("&", "&&"), parent)
        self._key: Optional[str] = None
        self.compact = compact
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        if compact:
            layout.setContentsMargins(0, 8, 0, 0)

        self.title_label = QLabel()
        set_status(self.title_label, "muted")
        self.title_label.setWordWrap(True)
        # The copyable plain-text form of the equation: not shown, kept for copying and tests.
        self.equation = QPlainTextEdit()
        self.equation.setReadOnly(True)
        self.equation.hide()
        self.equation_view = EquationView()
        copy = QAction("Copy equation as text", self.equation_view)
        copy.triggered.connect(
            lambda: QGuiApplication.clipboard().setText(self.equation.toPlainText()))
        self.equation_view.addAction(copy)
        self.equation_view.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self.citations = QLabel()
        self.citations.setWordWrap(True)
        set_status(self.citations, "muted")
        self.link = QPushButton(LINK_TEXT)
        set_variant(self.link, "link")
        self.link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.link.clicked.connect(self.open_methods)

        if compact:
            self.title_label.setWordWrap(False)
            self.equation_view.hide()
            row = QHBoxLayout()
            row.setSpacing(12)
            row.addWidget(self.title_label)
            row.addWidget(self.citations, 1)
            row.addWidget(self.link)
            layout.addLayout(row)
            layout.addWidget(self.equation)
            return
        layout.addWidget(self.title_label)
        layout.addSpacing(6)
        layout.addWidget(self.equation_view)
        layout.addSpacing(6)
        layout.addWidget(self.citations)
        layout.addWidget(self.link, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.equation)

    def set_method(self, info: MethodInfo) -> None:
        self._key = method_key(info)
        self.title_label.setText(f"Method: {info.title}" if self.compact else info.title)
        plain = info.equation
        if info.equation_after:
            plain += "\n" + info.equation_after
        self.equation.setPlainText(plain)
        self.equation_view.set_lines(info.equation_tex)
        self.equation_view.setVisible(bool(info.equation_tex) and not self.compact)
        self.citations.setText(
            f"References: {html.escape(citation_text(info.refs))}" if info.refs else ""
        )
        self.citations.setVisible(bool(info.refs))
        self.link.setEnabled(self._key is not None)

    @property
    def key(self) -> Optional[str]:
        return self._key

    def refresh_theme(self) -> None:
        self.equation_view.refresh_theme()

    def open_methods(self) -> None:
        """Open the Methods panel at this method."""
        if self._key is None:
            return
        self.method_requested.emit(self._key)
        widget = self.parentWidget()
        while widget is not None:
            if hasattr(widget, "open_method"):
                widget.open_method(self._key)
                return
            if hasattr(widget, "show_panel"):
                widget.show_panel("methods", self._key)
                return
            widget = widget.parentWidget()
