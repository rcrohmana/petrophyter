"""Capture screenshots of every tab in one or both themes.

Usage:
    python scripts/capture_ui.py --out docs/archive/screens/baseline
    python scripts/capture_ui.py --out shots --las "C:/path/Atti_A-01.las" --theme both
"""
import argparse
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import QEventLoop, QSettings, QTimer
from PyQt6.QtWidgets import QApplication


def wait_for(signal, timeout_ms=120_000):
    """Spin the event loop until `signal` fires or timeout."""
    loop = QEventLoop()
    signal.connect(loop.quit)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()


def settle(ms=400):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def left_panel(window):
    """The old sidebar (baseline) or the Data Browser (after Task 12C)."""
    panel = getattr(window, "data_browser", None)
    return panel if panel is not None else window.sidebar


def capture_all(window, theme_manager, out_dir: Path, theme: str):
    theme_manager.set_theme(theme)
    settle(600)
    out_dir.mkdir(parents=True, exist_ok=True)
    tab_names = ["qc", "petro", "log", "diag", "summary", "export"]
    for i, name in enumerate(tab_names):
        window.tab_widget.setCurrentIndex(i)
        settle(400)
        window.grab().save(str(out_dir / f"{theme}_{i}_{name}.png"))
    left_panel(window).grab().save(str(out_dir / f"{theme}_left_panel.png"))

    # Rev 2 surfaces: absent in the baseline run, so feature-detect them.
    params = getattr(window, "params_window", None)
    if params is not None:
        from ui.parameters_window import PAGES
        for key, _title, _menu, _icon in PAGES:
            params.open_page(key)
            settle(300)
            params.grab().save(str(out_dir / f"{theme}_params_{key}.png"))
        params.hide()
    merge = getattr(window, "merge_dialog", None)
    if merge is not None:
        merge.set_files([("Well_A-01_run1.las", 6544, 4500.0, 7772.0),
                         ("Well_A-01_run2.las", 4210, 7700.0, 9805.0)])
        merge.show()          # show(), not exec(): capture must not block
        settle(300)
        merge.grab().save(str(out_dir / f"{theme}_merge_dialog.png"))
        merge.hide()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--las", default=None)
    ap.add_argument("--theme", default="light", choices=["light", "dark", "both"])
    args = ap.parse_args()

    # Throwaway settings so a capture run never touches the user's saved theme/geometry.
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp()
    )

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    from PyQt6.QtWidgets import QMessageBox
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)

    from themes.theme_manager import ThemeManager
    icons_dir = str(Path(__file__).resolve().parents[1] / "icons").replace("\\", "/")
    theme_manager = ThemeManager(app, icons_dir)
    theme_manager.set_theme("light")

    from ui.main_window import MainWindow
    window = MainWindow(theme_manager)
    window.resize(1600, 950)
    window.show()
    settle(800)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    themes = ["light", "dark"] if args.theme == "both" else [args.theme]
    if args.las:
        # Empty-state left panel, grabbed before any data is loaded.
        for theme in themes:
            theme_manager.set_theme(theme)
            settle(600)
            left_panel(window).grab().save(str(out / f"{theme}_left_panel_empty.png"))
        window._load_single_las(args.las)
        settle(800)
        window._on_run_analysis()
        wait_for(window.model.analysis_complete)
        settle(800)
    for theme in themes:
        capture_all(window, theme_manager, out, theme)
    theme_manager.set_theme("light")
    print(f"Saved screenshots to {out.resolve()}")
    window.close()


if __name__ == "__main__":
    main()
