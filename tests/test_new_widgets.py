# tests/test_new_widgets.py
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QLabel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_set_status_sets_clears_and_validates(qapp):
    from themes.helpers import set_status
    label = QLabel("x")
    set_status(label, "success")
    assert label.property("status") == "success"
    set_status(label, None)
    assert label.property("status") is None
    with pytest.raises(ValueError):
        set_status(label, "purple")


def test_status_dot_kinds(qapp):
    from ui.widgets.status_dot import StatusDot
    dot = StatusDot()
    assert dot.objectName() == "StatusDot"
    dot.set_kind("ok")
    assert dot.property("kind") == "ok"
    with pytest.raises(ValueError):
        dot.set_kind("purple")


def test_dot_pixmap_filled_and_cached(qapp):
    from themes.colors import get_color, set_current_theme
    from ui.widgets.status_dot import dot_pixmap
    set_current_theme("light")
    pm = dot_pixmap("success")
    assert (pm.width(), pm.height()) == (8, 8)
    assert dot_pixmap("success") is pm
    image = pm.toImage()
    assert image.pixelColor(4, 4).name().lower() == get_color("success", "light").lower()
    assert image.pixelColor(0, 0).alpha() == 0  # corner outside the circle
    with pytest.raises(ValueError):
        dot_pixmap("purple")


def test_banner_show_and_clear(qapp):
    from ui.widgets.notification_banner import NotificationBanner
    banner = NotificationBanner()
    assert banner.isHidden()  # constructed hidden
    banner.show_message("success", "Analysis complete — Net Pay 1625.4 ft")
    assert banner.property("kind") == "success"
    assert "Net Pay" in banner.message_label.text()
    banner.clear()
    assert banner.isHidden()


def test_banner_rejects_error_kind(qapp):
    # errors stay modal per design.md — banner must refuse them
    from ui.widgets.notification_banner import NotificationBanner
    banner = NotificationBanner()
    with pytest.raises(ValueError):
        banner.show_message("error", "boom")


def test_info_strip_blocks(qapp):
    from ui.widgets.info_strip import InfoStrip
    strip = InfoStrip()
    strip.add_block("well", "WELL")
    strip.add_block("points", "POINTS")
    strip.set_value("well", "Atti_A-01")
    strip.set_value("points", "45,581")
    assert strip.value_label("well").text() == "Atti_A-01"
    with pytest.raises(KeyError):
        strip.set_value("nope", "x")


def test_table_model_numeric_styling(qapp):
    import pandas as pd
    from PyQt6.QtCore import Qt
    from ui.widgets.table_model import PandasTableModel
    model = PandasTableModel(pd.DataFrame({"Curve": ["GR"], "Mean": [77.02]}))
    numeric_index = model.index(0, 1)
    text_index = model.index(0, 0)
    font = model.data(numeric_index, Qt.ItemDataRole.FontRole)
    assert font is not None and font.family() == "Consolas"
    align = model.data(numeric_index, Qt.ItemDataRole.TextAlignmentRole)
    assert align & Qt.AlignmentFlag.AlignRight
    assert model.data(text_index, Qt.ItemDataRole.FontRole) is None
