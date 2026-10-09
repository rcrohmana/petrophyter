# tests/test_icon_loader.py
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from themes import icon_loader
from themes.colors import set_current_theme


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_get_icon_returns_nonnull_icon(qapp):
    icon = icon_loader.get_icon("play")
    assert not icon.isNull()
    assert not icon.pixmap(18, 18).isNull()


def test_icon_cache_hit_and_theme_invalidation(qapp):
    set_current_theme("light")
    a = icon_loader.get_icon("save")
    assert icon_loader.get_icon("save") is a  # cached
    set_current_theme("dark")
    b = icon_loader.get_icon("save")
    assert b is not a  # theme keyed
    set_current_theme("light")


def test_unknown_icon_raises(qapp):
    with pytest.raises(FileNotFoundError):
        icon_loader.get_icon("no-such-icon")


def test_ensure_qss_icons_writes_files(qapp):
    d = Path(icon_loader.ensure_qss_icons("light"))
    for name in ("chevron-down", "chevron-up", "chevron-right", "check"):
        assert (d / f"{name}.svg").exists()
    assert "\\" not in str(icon_loader.ensure_qss_icons("light"))
