"""8px status dot. Kinds: ok (green), off (muted), warn (amber)."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import QLabel

from themes.colors import get_color, get_current_theme

_KINDS = {"ok", "off", "warn"}
_DOT_TOKENS = {
    "success": "success",
    "warning": "warning",
    "error": "error",
    "off": "text_muted",
}
_dot_cache: dict[tuple, QPixmap] = {}


class StatusDot(QLabel):
    def __init__(self, kind: str = "off", parent=None):
        super().__init__("", parent)
        self.setObjectName("StatusDot")
        self.set_kind(kind)

    def set_kind(self, kind: str):
        if kind not in _KINDS:
            raise ValueError(f"unknown dot kind {kind!r}")
        self.setProperty("kind", kind)
        self.style().unpolish(self)
        self.style().polish(self)


def dot_pixmap(status: str, size: int = 8) -> QPixmap:
    """Filled status dot (Lucide `circle` is an outline ring, so it is painted)."""
    if status not in _DOT_TOKENS:
        raise ValueError(f"unknown dot status {status!r}")
    theme = get_current_theme()
    key = (status, size, theme)
    if key not in _dot_cache:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(get_color(_DOT_TOKENS[status], theme)))
        painter.drawEllipse(0, 0, size, size)
        painter.end()
        _dot_cache[key] = pixmap
    return _dot_cache[key]
