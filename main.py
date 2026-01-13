"""
Petrophyter PyQt - Desktop Petrophysics Application
Main entry point.

Author: Petrophyter Team
Version: 1.2.0
"""

import sys
import os

# Add the current directory to path for module imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller."""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))

    return os.path.join(base_path, relative_path)


from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon

from ui.main_window import MainWindow
from themes import ThemeManager


def main():
    """Main application entry point."""
    # Enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # Create application
    app = QApplication(sys.argv)
    app.setApplicationName("Petrophyter")
    app.setOrganizationName("Petrophyter Team")
    app.setApplicationVersion("1.2.0")

    # Set application icon (rock/stone icon)
    icon_path = resource_path(os.path.join("icons", "app_icon.svg"))
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Set application style
    app.setStyle("Fusion")

    # Build absolute path to icons for stylesheet (forward slashes for Qt URLs)
    icons_dir = resource_path("icons").replace("\\", "/")

    # Initialize theme manager
    theme_manager = ThemeManager(app, icons_dir)

    # Apply saved theme (or default light theme)
    theme_manager.set_theme(theme_manager.get_current_theme())

    # OLD CODE - Now handled by ThemeManager
    # Keep this commented for reference
    # OLD CODE - Now handled by ThemeManager
    # Keep this commented for reference if needed
    # """

    # Create and show main window
    window = MainWindow(theme_manager)
    window.show()

    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
