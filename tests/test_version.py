import re
from pathlib import Path

from PyQt6.QtWidgets import QLabel, QTextEdit

from version import APP_BUILD, APP_VERSION, APP_VERSION_DISPLAY


ROOT = Path(__file__).resolve().parents[1]


def test_release_version_metadata():
    assert APP_VERSION == "1.5.0"
    assert APP_BUILD == "20260814"
    assert APP_VERSION_DISPLAY == "1.5.0 (Build 20260814)"
    assert re.fullmatch(r"\d+\.\d+\.\d+", APP_VERSION)
    assert re.fullmatch(r"\d{8}", APP_BUILD)


def test_main_uses_shared_application_version():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "from version import APP_VERSION" in source
    assert "app.setApplicationVersion(APP_VERSION)" in source


def test_about_dialog_uses_shared_release_metadata(qtbot):
    from ui.widgets.about_dialog import AboutDialog

    dialog = AboutDialog()
    qtbot.addWidget(dialog)

    label_text = "\n".join(label.text() for label in dialog.findChildren(QLabel))
    citation_text = "\n".join(
        box.toPlainText() for box in dialog.findChildren(QTextEdit)
    )

    assert f"v{APP_VERSION_DISPLAY}" in label_text
    assert f"Version {APP_VERSION}" in citation_text


def test_inno_setup_version_matches_shared_metadata():
    source = (ROOT / "installer" / "Petrophyter.iss").read_text(encoding="utf-8")
    assert f'#define AppVersion      "{APP_VERSION_DISPLAY}"' in source
    assert f'#define AppVersionFile  "{APP_VERSION}_Build{APP_BUILD}"' in source
