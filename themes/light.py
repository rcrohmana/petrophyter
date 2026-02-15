"""
Light theme for Petrophyter PyQt.
"""

LIGHT_COLORS = {
    "background": "#E8E3D9",
    "surface": "#F0EBE1",
    "surface_alt": "#E0DBD1",
    "surface_hover": "#E5DFD4",
    "surface_pressed": "#D5CFC4",
    "primary": "#1E88E5",
    "primary_dark": "#1976D2",
    "primary_darker": "#1565C0",
    "text": "#000000",
    "text_secondary": "#4A4540",
    "text_disabled": "#999999",
    "border": "#C9C0B0",
    "border_light": "#D5CFC4",
    "success": "#4CAF50",
    "warning": "#FF8C00",
    "error": "#F44336",
    "white": "#FFFFFF",
    "tooltip_bg": "#2B2B2B",
    "tooltip_text": "#FFFFFF",
    "handle": "#A09080",
}

LIGHT_THEME = """
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
        color: #000000;
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
    QSplitter {
        background-color: #E8E3D9;
    }
    QSplitter::handle:horizontal {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 transparent, stop:0.4 #A09080, stop:0.6 #A09080, stop:1 transparent);
        width: 6px;
        margin: 2px 0px;
    }
    QSplitter::handle:horizontal:hover {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 transparent, stop:0.3 #1E88E5, stop:0.7 #1E88E5, stop:1 transparent);
    }
    QSplitter::handle:horizontal:pressed {
        background: #1565C0;
    }
    QStatusBar {
        background-color: #E0DBD1;
        color: #000000;
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
    #collapsibleHeader {
        background-color: #D5CFC4;
        border: 1px solid #C9C0B0;
    }
    #collapsibleHeader:hover {
        background-color: #CEC8BC;
    }
    #collapsibleContent {
        border: 1px solid #C9C0B0;
        background-color: #E8E3D9;
    }
"""
