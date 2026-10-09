"""Non-modal inline banner. Success/warning/info only — errors stay modal."""
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from themes.icon_loader import get_icon

_KIND_ICONS = {"success": "circle-check", "warning": "triangle-alert", "info": "info"}
_KIND_TOKENS = {"success": "success", "warning": "warning", "info": "accent"}


class NotificationBanner(QFrame):
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NotificationBanner")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)
        self.icon_label = QLabel()
        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        close_btn = QPushButton()
        close_btn.setProperty("variant", "ghost")
        close_btn.setIcon(get_icon("x"))
        close_btn.setFixedSize(22, 22)
        close_btn.clicked.connect(self.clear)
        layout.addWidget(self.icon_label)
        layout.addWidget(self.message_label, stretch=1)
        layout.addWidget(close_btn)
        self.hide()

    def show_message(self, kind: str, message: str):
        if kind not in _KIND_ICONS:
            raise ValueError(f"banner kind {kind!r} not allowed (errors are modal)")
        self.setProperty("kind", kind)
        self.style().unpolish(self)
        self.style().polish(self)
        self.icon_label.setPixmap(
            get_icon(_KIND_ICONS[kind], _KIND_TOKENS[kind]).pixmap(16, 16)
        )
        self.message_label.setText(message)
        self.show()

    def clear(self):
        self.hide()
        self.closed.emit()
