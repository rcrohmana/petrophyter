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
    icon_path = resource_path(os.path.join('icons', 'app_icon.svg'))
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    # Set application style
    app.setStyle("Fusion")
    
    # Set application palette to theme colors (prevents white widgets)
    # NEW DARKER THEME: background #E8E3D9, surface #F0EBE1
    from PyQt6.QtGui import QPalette, QColor
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#E8E3D9"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#F0EBE1"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#E0DBD1"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#000000"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#000000"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#E0DBD1"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#000000"))
    app.setPalette(palette)
    
    # Set stylesheet for better appearance - White Sand background, Black text
    # Build absolute path to icons for stylesheet (forward slashes for Qt URLs)
    icons_dir = resource_path('icons').replace('\\', '/')
    stylesheet = """
        * {
            color: #000000;
        }
        QMainWindow {
            background-color: #E8E3D9;
        }
        QWidget {
            background-color: #E8E3D9;
            color: #000000;
        }
        QGroupBox {
            font-weight: bold;
            border: 1px solid #C9C0B0;
            border-radius: 5px;
            margin-top: 10px;
            padding-top: 10px;
            background-color: #E8E3D9;
            color: #000000;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px;
            color: #000000;
        }
        QTabWidget {
            background-color: #E8E3D9;
        }
        QTabWidget::pane {
            border: 1px solid #C9C0B0;
            border-radius: 5px;
            background-color: #E8E3D9;
        }
        QTabBar::tab {
            background-color: #E0DBD1;
            color: #000000;
            border: 1px solid #C9C0B0;
            padding: 8px 16px;
            margin-right: 2px;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
        }
        QTabBar::tab:selected {
            background-color: #E8E3D9;
            border-bottom-color: #E8E3D9;
            color: #000000;
        }
        QTabBar::tab:hover {
            background-color: #E5DFD4;
        }
        QScrollArea {
            border: none;
            background-color: #E8E3D9;
        }
        QScrollArea > QWidget > QWidget {
            background-color: #E8E3D9;
        }
        QAbstractScrollArea::viewport {
            background-color: #E8E3D9;
        }
        QFrame {
            background-color: #E8E3D9;
        }
        QGraphicsView, QListView, QTreeView {
            background-color: #F0EBE1;
            color: #000000;
        }
        QLabel {
            background-color: transparent;
            color: #000000;
        }
        QLineEdit {
            background-color: #F0EBE1;
            color: #000000;
            border: 1px solid #C9C0B0;
            border-radius: 4px;
            padding: 4px 8px;
        }
        QTextEdit, QPlainTextEdit {
            background-color: #F0EBE1;
            color: #000000;
            border: 1px solid #C9C0B0;
            border-radius: 4px;
        }
        FigureCanvas, FigureCanvasQTAgg {
            background-color: #F0EBE1;
        }
        QToolBar {
            background-color: #F0EBE1;
            border: 1px solid #C9C0B0;
            border-radius: 4px;
            spacing: 3px;
            padding: 4px;
        }
        QTableView {
            background-color: #F0EBE1;
            color: #000000;
            gridline-color: #D5CFC4;
            border: 1px solid #C9C0B0;
            border-radius: 4px;
        }
        QTableView::item {
            padding: 4px;
            color: #000000;
            background-color: #F0EBE1;
        }
        QTableView::item:selected {
            background-color: #1E88E5;
            color: #ffffff;
        }
        QHeaderView::section {
            background-color: #E0DBD1;
            color: #000000;
            padding: 6px;
            border: none;
            border-right: 1px solid #D5CFC4;
            border-bottom: 1px solid #D5CFC4;
            font-weight: bold;
        }
        QDoubleSpinBox, QSpinBox {
            padding: 4px 8px;
            border: 1px solid #C9C0B0;
            border-radius: 4px;
            background-color: #F0EBE1;
            color: #000000;
            min-height: 28px;
            min-width: 80px;
        }
        QDoubleSpinBox QLineEdit, QSpinBox QLineEdit {
            background-color: #F0EBE1;
            color: #000000;
            border: none;
            padding: 0px;
        }
        QDoubleSpinBox::up-button, QSpinBox::up-button,
        QDoubleSpinBox::down-button, QSpinBox::down-button {
            width: 0px;
            border: none;
            background: none;
        }
        QDoubleSpinBox::up-arrow, QSpinBox::up-arrow,
        QDoubleSpinBox::down-arrow, QSpinBox::down-arrow {
            width: 0px;
            height: 0px;
        }
        QComboBox {
            padding: 4px 24px 4px 8px;
            border: 1px solid #C9C0B0;
            border-radius: 4px;
            background-color: #F0EBE1;
            color: #000000;
            min-height: 26px;
        }
        QComboBox::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: center right;
            width: 20px;
            border-left: 1px solid #C9C0B0;
            border-top-right-radius: 3px;
            border-bottom-right-radius: 3px;
            background-color: #E0DBD1;
        }
        QComboBox::drop-down:hover {
            background-color: #E5DFD4;
        }
        QComboBox::down-arrow {
            image: url({{ICONS_DIR}}/chevron-down.svg);
            width: 12px;
            height: 12px;
        }
        QComboBox::down-arrow:on {
            top: 1px;
        }
        QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {
            border-color: #1E88E5;
        }
        QComboBox QAbstractItemView {
            background-color: #F0EBE1;
            color: #000000;
            selection-background-color: #1E88E5;
            selection-color: #ffffff;
        }
        QListWidget {
            background-color: #F0EBE1;
            color: #000000;
            border: 1px solid #C9C0B0;
        }
        QListWidget::item {
            color: #000000;
        }
        QListWidget::item:selected {
            background-color: #1E88E5;
            color: #ffffff;
        }
        QPushButton {
            padding: 6px 12px;
            border: 1px solid #C9C0B0;
            border-radius: 4px;
            background-color: #E0DBD1;
            color: #000000;
        }
        QPushButton:hover {
            background-color: #E5DFD4;
        }
        QPushButton:pressed {
            background-color: #D5CFC4;
        }
        QRadioButton, QCheckBox {
            background-color: transparent;
            color: #000000;
        }
        QSlider::groove:horizontal {
            height: 6px;
            background: #D5CFC4;
            border-radius: 3px;
        }
        QSlider::handle:horizontal {
            background: #1E88E5;
            width: 16px;
            height: 16px;
            margin: -5px 0;
            border-radius: 8px;
        }
        QSlider::sub-page:horizontal {
            background: #1E88E5;
            border-radius: 3px;
        }
        QProgressBar {
            border: 1px solid #C9C0B0;
            border-radius: 4px;
            text-align: center;
            background-color: #F0EBE1;
            color: #000000;
        }
        QProgressBar::chunk {
            background-color: #4CAF50;
            border-radius: 3px;
        }
        QFrame {
            background-color: #E8E3D9;
            color: #000000;
        }
        QSplitter {
            background-color: #E8E3D9;
        }
        QStatusBar {
            background-color: #E0DBD1;
            color: #000000;
        }
        QTabWidget::pane {
            background-color: #E8E3D9;
        }
        QToolTip {
            background-color: #2B2B2B;
            color: #FFFFFF;
            border: 1px solid #555555;
            padding: 4px;
            border-radius: 3px;
        }
        QLineEdit, QTextEdit, QPlainTextEdit {
            selection-background-color: #1E88E5;
            selection-color: #FFFFFF;
        }
        QSpinBox, QDoubleSpinBox, QComboBox {
            selection-background-color: #1E88E5;
            selection-color: #FFFFFF;
        }
    """
    app.setStyleSheet(stylesheet.replace("{{ICONS_DIR}}", icons_dir))
    
    # Create and show main window
    window = MainWindow()
    window.show()
    
    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
