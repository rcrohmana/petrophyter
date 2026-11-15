"""A section that is folded by default: a one-line clickable header over a body.

The header reads ``<title>`` or ``<title> (N changed)`` and carries a chevron (right when folded,
down when open). The body is a plain widget with a vertical layout (``body_layout``); it is hidden
while folded. The owner opens it when something in it differs from the default, so no setting is
hidden; it never closes it again by itself.
"""

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from themes.icon_loader import get_icon


class FoldSection(QWidget):
    """Header button plus a body that shows only while the section is open."""

    toggled = pyqtSignal(bool)

    def __init__(self, title: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._title = title
        self._changed = 0
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        self.header = QToolButton()
        self.header.setCheckable(True)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.header.toggled.connect(self._on_toggled)
        head.addWidget(self.header)
        head.addStretch(1)
        outer.addLayout(head)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.body)
        self.body.setVisible(False)
        self._sync()

    # ------------------------------------------------------------------ state
    def is_expanded(self) -> bool:
        return self.header.isChecked()

    def set_expanded(self, on: bool):
        self.header.setChecked(bool(on))

    def set_changed_count(self, n: int):
        """Show how many values of the body differ from the defaults (0: no count)."""
        self._changed = max(0, int(n))
        self._sync()

    def changed_count(self) -> int:
        return self._changed

    def header_text(self) -> str:
        return f"{self._title} ({self._changed} changed)" if self._changed else self._title

    def refresh_theme(self):
        self._sync()

    # --------------------------------------------------------------- internals
    def _on_toggled(self, on: bool):
        self.body.setVisible(on)
        self._sync()
        self.toggled.emit(on)

    def _sync(self):
        self.header.setText(self.header_text())
        self.header.setIcon(get_icon("chevron-down" if self.is_expanded() else "chevron-right"))
        self.header.setToolTip("Hide these settings" if self.is_expanded()
                               else "Show these settings")
