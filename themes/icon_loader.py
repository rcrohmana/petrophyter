# themes/icon_loader.py
"""Theme-aware Lucide icon loading. Icons recolor per theme via currentColor."""
import tempfile
from pathlib import Path

from PyQt6.QtCore import QByteArray, Qt, QRectF
from PyQt6.QtGui import QIcon, QImage, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from .colors import get_color, get_current_theme

_ICON_DIR = Path(__file__).resolve().parent.parent / "icons" / "lucide"
_SIZES = (16, 18, 24)
_QSS_ICON_NAMES = ("chevron-down", "chevron-up", "chevron-right", "check")
_cache: dict[tuple, QIcon] = {}


def _colored_svg(name: str, color: str) -> str:
    path = _ICON_DIR / f"{name}.svg"
    if not path.exists():
        raise FileNotFoundError(f"Icon not bundled: {name} ({path})")
    return path.read_text(encoding="utf-8").replace("currentColor", color)


def get_icon(name: str, color_token: str = "text_secondary") -> QIcon:
    theme = get_current_theme()
    key = (name, theme, color_token)
    if key not in _cache:
        svg = _colored_svg(name, get_color(color_token, theme))
        renderer = QSvgRenderer(QByteArray(svg.encode()))
        icon = QIcon()
        for size in _SIZES:
            for dpr in (1, 2):
                image = QImage(size * dpr, size * dpr, QImage.Format.Format_ARGB32)
                image.fill(Qt.GlobalColor.transparent)
                painter = QPainter(image)
                renderer.render(painter, QRectF(0, 0, size * dpr, size * dpr))
                painter.end()
                pixmap = QPixmap.fromImage(image)
                pixmap.setDevicePixelRatio(dpr)
                icon.addPixmap(pixmap)
        _cache[key] = icon
    return _cache[key]


def clear_icon_cache() -> None:
    _cache.clear()


def ensure_qss_icons(theme: str) -> str:
    """Write recolored SVGs for QSS image: url() references; return posix dir."""
    out = Path(tempfile.gettempdir()) / "petrophyter_qss_icons" / theme
    out.mkdir(parents=True, exist_ok=True)
    color = get_color("text_secondary", theme)
    check_color = get_color("text_on_accent", theme)
    for name in _QSS_ICON_NAMES:
        icon_color = check_color if name == "check" else color
        (out / f"{name}.svg").write_text(
            _colored_svg(name, icon_color), encoding="utf-8"
        )
    return out.as_posix()
