"""English (US) locale is the app default (see main.py / conftest)."""
from PyQt6.QtCore import QLocale
from PyQt6.QtWidgets import QDoubleSpinBox


def test_default_locale_is_english_us():
    assert QLocale().language() == QLocale.Language.English
    assert QLocale().country() == QLocale.Country.UnitedStates


def test_spinbox_uses_decimal_point(qtbot):
    box = QDoubleSpinBox()
    qtbot.addWidget(box)
    box.setDecimals(2)
    box.setValue(0.5)
    assert box.text() == "0.50"


def test_depth_spinbox_has_no_group_separator(qtbot):
    box = QDoubleSpinBox()
    qtbot.addWidget(box)
    box.setRange(0, 20000)
    box.setDecimals(1)
    box.setSuffix(" ft")
    box.setValue(4500.0)
    assert box.text() == "4500.0 ft"


def test_spinbox_parses_point_input(qtbot):
    box = QDoubleSpinBox()
    qtbot.addWidget(box)
    box.setDecimals(2)
    assert box.valueFromText("1.25") == 1.25
