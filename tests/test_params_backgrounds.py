# tests/test_params_backgrounds.py
"""F3: no bg_base strips behind controls on Parameters pages; QSlider is tokenised."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QSlider

from themes.icon_loader import ensure_qss_icons
from themes.renderer import render_qss
from themes.tokens import COLORS
from ui.main_window import MainWindow
from ui.parameters_window import PAGES

SCRATCH = os.environ.get("PARAMS_GRAB_DIR")  # optional: save page grabs for eyeballing


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_qss_has_slider_and_scoped_transparent_rule(theme):
    qss = render_qss(theme)
    assert "QSlider::groove" in qss
    assert "QWidget#ParamsPage QWidget { background-color: transparent; }" in qss
    assert COLORS[theme]["accent_muted"] in qss
    assert COLORS[theme]["focus_ring"] in qss


@pytest.fixture()
def params_window(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    pw = w.params_window
    pw.show()
    return pw


def _page(pw, key):
    pw.open_page(key, show=False)
    scroll = pw.stack.currentWidget()
    QApplication.processEvents()
    return scroll.widget()


def _px(page, widget, dx, dy):
    """Color (hex) at an offset from widget's top-left, in page coords."""
    img = page.grab().toImage()
    p = widget.mapTo(page, widget.rect().topLeft())
    return img.pixelColor(p.x() + dx, p.y() + dy).name().upper()


def _gap_px(page, upper, lower, x_widget):
    img = page.grab().toImage()
    top = upper.mapTo(page, upper.rect().bottomLeft()).y()
    bot = lower.mapTo(page, lower.rect().topLeft()).y()
    assert bot - top >= 2, "no gap between rows to probe"
    x = x_widget.mapTo(page, x_widget.rect().center()).x()
    return img.pixelColor(x, (top + bot) // 2).name().upper()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_no_strips_on_pages(qtbot, params_window, theme):
    app = QApplication.instance()
    app.setStyleSheet(render_qss(theme, ensure_qss_icons(theme)))
    expected = COLORS[theme]["bg_surface"].upper()
    pw = params_window

    # Cutoffs: beside a slider (top row of its rect, away from the groove) and between rows.
    page = _page(pw, "cutoffs")
    g = pw.cutoff_params_widget
    assert _px(page, g.vsh_slider, g.vsh_slider.width() // 2, 0) == expected
    assert _gap_px(page, g.vsh_slider, g.phi_slider, g.vsh_slider) == expected
    # Alignment: sliders share x and width.
    assert g.vsh_slider.x() == g.phi_slider.x() == g.sw_slider.x()
    assert g.vsh_slider.width() == g.phi_slider.width() == g.sw_slider.width()

    # Core matching: gap between form rows.
    page = _page(pw, "core")
    assert _gap_px(page, pw.core_unit_combo, pw.core_dist_spin, pw.core_unit_combo) == expected

    # Every page: every slider's rect top row matches the surface; dump grabs if asked.
    for key, _title, _menu, _icon in PAGES:
        page = _page(pw, key)
        for s in page.findChildren(QSlider):
            assert _px(page, s, s.width() // 2, 0) == expected
        if SCRATCH:
            os.makedirs(SCRATCH, exist_ok=True)
            pw.stack.currentWidget().grab().save(os.path.join(SCRATCH, f"{key}_{theme}.png"))
