"""F2: honest engine combo, interactive log theme refresh and Reset View."""

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

import themes.colors as theme_colors
from themes.tokens import PLOT_CHROME


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _restore_theme():
    before = theme_colors.get_current_theme()
    yield
    theme_colors.set_current_theme(before)


def test_engine_combo_disabled_without_pyqtgraph(qapp, monkeypatch):
    import ui.tabs.log_display_tab as mod

    monkeypatch.setattr(mod, "HAS_PYQTGRAPH", False)
    tab = mod.LogDisplayTab(MagicMock())
    combo = tab.engine_combo
    assert not combo.model().item(0).isEnabled()
    assert combo.itemText(0) == "Interactive (requires pyqtgraph)"
    assert combo.currentIndex() == 1
    assert tab.plot_stack.currentWidget() is tab.classic_log


def _hex(color):
    return QColor(color).name().lower()


def _log():
    pytest.importorskip("pyqtgraph")
    from ui.widgets.interactive_log import InteractiveLogPlot

    depth = np.linspace(1000, 1100, 200)
    df = pd.DataFrame(
        {
            "DEPTH": depth,
            "GR": 60 + 30 * np.sin(depth / 7),
            "RT": 10 ** (1 + np.cos(depth / 9)),
        }
    )
    w = InteractiveLogPlot(n_tracks=6)
    w.plot_curves(df)
    w.set_formation_tops([{"name": "A", "top_depth": 1030.0}])
    return w


def test_theme_switch_recolors_chrome(qapp):
    theme_colors.set_current_theme("light")
    w = _log()
    theme_colors.set_current_theme("dark")
    w.refresh_theme()
    dark = PLOT_CHROME["dark"]
    plot = w.plot_widgets[0]
    assert _hex(w.graphics_layout.backgroundBrush().color()) == _hex(dark["figure"])
    assert _hex(plot.getViewBox().state["background"]) == _hex(dark["axes"])
    for name in ("left", "bottom"):
        assert _hex(plot.getAxis(name).pen().color()) == _hex(dark["spine"])
        assert _hex(plot.getAxis(name).textPen().color()) == _hex(dark["text"])
    v_line, h_line = w.crosshairs[0]
    assert _hex(v_line.pen.color()) == _hex(dark["crosshair"])
    assert _hex(h_line.pen.color()) == _hex(dark["crosshair"])
    assert _hex(w.depth_region.brush.color()) == _hex(dark["selection"])
    assert _hex(plot.titleLabel.opts["color"]) == _hex(dark["text"])
    assert _hex(w.curve_items["RT"].opts["pen"].color()) == _hex(
        theme_colors.get_plot_color("RT", "dark")
    )
    assert len(w.formation_lines) == 1


def test_reset_view_restores_data_range(qapp):
    w = _log()
    w.resize(900, 700)
    w.show()  # auto-range is applied lazily; needs a shown widget
    w.reset_view()
    qapp.processEvents()
    w.set_depth_range(1040, 1050)
    qapp.processEvents()
    top, bottom = sorted(w.plot_widgets[0].getViewBox().viewRange()[1])
    assert (bottom - top) < 20
    w.reset_view()
    qapp.processEvents()
    top, bottom = sorted(w.plot_widgets[0].getViewBox().viewRange()[1])
    assert 900 < top <= 1001
    assert 1099 <= bottom < 1200
