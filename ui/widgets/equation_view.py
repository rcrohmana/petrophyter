"""Rendered equations: matplotlib mathtext lines drawn as transparent pixmaps.

No extra dependency: ``matplotlib.mathtext.math_to_image`` makes a PNG of each line, the text
colour comes from the theme and the pixel density from the screen's device pixel ratio.
Rendered lines are kept in a process-wide cache because the main window, with all its method
boxes, is built many times (in the test suite hundreds of times).
"""

import io
from collections import OrderedDict
from typing import Iterable, Tuple

from matplotlib import rc_context
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.mathtext import MathTextParser
from PyQt6.QtCore import QEvent, QSize, Qt
from PyQt6.QtGui import QImage, QPainter, QPixmap
from PyQt6.QtWidgets import QSizePolicy, QWidget

from themes.colors import get_color

EQUATION_PT = 13.5   # compact strips; fractions shrink their terms, so above body text
PANEL_PT = 15.0      # the Methods panel
LEGEND_PT = 13.0     # symbols in a legend table
LINE_GAP_EM = 0.6    # space between stacked lines, in em
PAD_PT = 3.0         # padding on every side of a rendered line: subscripts are never clipped
_BASE_DPI = 96.0     # Qt logical pixels per inch
_CACHE_MAX = 1024

# (tex, colour, dpr, size) -> pixmap (device pixel ratio already set)
_CACHE: "OrderedDict[Tuple[str, str, float, float], QPixmap]" = OrderedDict()


def render_tex(tex: str, color: str, dpr: float = 1.0, size_pt: float = EQUATION_PT) -> QPixmap:
    """Render one mathtext line to a transparent pixmap. Raises on invalid mathtext."""
    key = (tex, color, round(float(dpr), 2), float(size_pt))
    hit = _CACHE.get(key)
    if hit is not None:
        _CACHE.move_to_end(key)
        return hit
    buf = io.BytesIO()
    prop = FontProperties(size=size_pt)
    with rc_context({"mathtext.fontset": "stix"}):
        # math_to_image writes an opaque white page; the same steps with a transparent one.
        width, height, depth, _, _ = MathTextParser("path").parse(tex, dpi=72, prop=prop)
        full_w, full_h = width + 2 * PAD_PT, height + 2 * PAD_PT
        fig = Figure(figsize=(full_w / 72.0, full_h / 72.0))
        fig.text(PAD_PT / full_w, (depth + PAD_PT) / full_h, tex, fontproperties=prop,
                 color=color)
        fig.savefig(buf, dpi=_BASE_DPI * key[2], format="png", transparent=True)
    image = QImage.fromData(buf.getvalue(), "PNG")
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(key[2])
    _CACHE[key] = pixmap
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return pixmap


def clear_cache() -> None:
    _CACHE.clear()


class EquationView(QWidget):
    """Equation lines stacked and left-aligned; follows the theme text colour when painted."""

    def __init__(self, parent=None, size_pt: float = EQUATION_PT, color_key: str = "text_primary"):
        super().__init__(parent)
        self._lines: Tuple[str, ...] = ()
        self._size_pt = size_pt
        self._color_key = color_key
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    @property
    def lines(self) -> Tuple[str, ...]:
        return self._lines

    def set_lines(self, lines: Iterable[str]) -> None:
        self._lines = tuple(lines)
        self.setAccessibleDescription(" ; ".join(self._lines))
        self.updateGeometry()
        self.update()

    def refresh_theme(self) -> None:
        self.update()

    def changeEvent(self, event):
        super().changeEvent(event)
        # A light/dark switch restyles every widget; the lines are redrawn in the new colour.
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.PaletteChange):
            self.update()

    def _pixmaps(self):
        dpr = self.devicePixelRatioF()
        color = get_color(self._color_key)
        for tex in self._lines:
            yield render_tex(tex, color, dpr, self._size_pt)

    @staticmethod
    def _logical(pixmap: QPixmap) -> QSize:
        ratio = pixmap.devicePixelRatio() or 1.0
        return QSize(round(pixmap.width() / ratio), round(pixmap.height() / ratio))

    def sizeHint(self) -> QSize:
        sizes = [self._logical(p) for p in self._pixmaps()]
        if not sizes:
            return QSize(0, 0)
        width = max(s.width() for s in sizes)
        height = sum(s.height() for s in sizes) + self._gap() * (len(sizes) - 1)
        return QSize(width, height)

    def _gap(self) -> int:
        return round(LINE_GAP_EM * self._size_pt * _BASE_DPI / 72.0)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, self.sizeHint().height())

    def paintEvent(self, event):
        painter = QPainter(self)
        y = 0
        for pixmap in self._pixmaps():
            painter.drawPixmap(0, y, pixmap)
            y += self._logical(pixmap).height() + self._gap()
        painter.end()
