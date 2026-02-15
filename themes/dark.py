"""
Dark theme for Petrophyter PyQt.
"""

DARK_COLORS = {
    "background": "#1E1E1E",
    "surface": "#2D2D2D",
    "surface_alt": "#383838",
    "surface_hover": "#424242",
    "surface_pressed": "#303030",
    "primary": "#2196F3",
    "primary_dark": "#1976D2",
    "primary_darker": "#1565C0",
    "text": "#E0E0E0",
    "text_secondary": "#A0A0A0",
    "text_disabled": "#666666",
    "border": "#404040",
    "border_light": "#505050",
    "success": "#66BB6A",
    "warning": "#FFA726",
    "error": "#EF5350",
    "white": "#FFFFFF",
    "tooltip_bg": "#424242",
    "tooltip_text": "#E0E0E0",
    "handle": "#606060",
}

DARK_THEME = """
    * {
        color: #E0E0E0;
    }
    QMainWindow {
        background-color: #1E1E1E;
    }
    QWidget {
        background-color: #1E1E1E;
        color: #E0E0E0;
    }
    QGroupBox {
        font-weight: bold;
        border: 1px solid #404040;
        border-radius: 5px;
        margin-top: 10px;
        padding-top: 10px;
        background-color: #1E1E1E;
        color: #E0E0E0;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 5px;
        color: #E0E0E0;
    }
    QTabWidget {
        background-color: #1E1E1E;
    }
    QTabWidget::pane {
        border: 1px solid #404040;
        border-radius: 5px;
        background-color: #1E1E1E;
    }
    QTabBar::tab {
        background-color: #383838;
        color: #E0E0E0;
        border: 1px solid #404040;
        padding: 8px 16px;
        margin-right: 2px;
        border-top-left-radius: 4px;
        border-top-right-radius: 4px;
    }
    QTabBar::tab:selected {
        background-color: #1E1E1E;
        border-bottom-color: #1E1E1E;
        color: #E0E0E0;
    }
    QTabBar::tab:hover {
        background-color: #424242;
    }
    QScrollArea {
        border: none;
        background-color: #1E1E1E;
    }
    QScrollArea > QWidget > QWidget {
        background-color: #1E1E1E;
    }
    QAbstractScrollArea::viewport {
        background-color: #1E1E1E;
    }
    QFrame {
        background-color: #1E1E1E;
        color: #E0E0E0;
    }
    QGraphicsView, QListView, QTreeView {
        background-color: #2D2D2D;
        color: #E0E0E0;
    }
    QLabel {
        background-color: transparent;
        color: #E0E0E0;
    }
    QLineEdit {
        background-color: #2D2D2D;
        color: #E0E0E0;
        border: 1px solid #404040;
        border-radius: 4px;
        padding: 4px 8px;
    }
    QTextEdit, QPlainTextEdit {
        background-color: #2D2D2D;
        color: #E0E0E0;
        border: 1px solid #404040;
        border-radius: 4px;
    }
    FigureCanvas, FigureCanvasQTAgg {
        background-color: #2D2D2D;
    }
    QToolBar {
        background-color: #2D2D2D;
        border: 1px solid #404040;
        border-radius: 4px;
        spacing: 3px;
        padding: 4px;
    }
    QTableView {
        background-color: #2D2D2D;
        color: #E0E0E0;
        gridline-color: #505050;
        border: 1px solid #404040;
        border-radius: 4px;
    }
    QTableView::item {
        padding: 4px;
        color: #E0E0E0;
        background-color: #2D2D2D;
    }
    QTableView::item:selected {
        background-color: #2196F3;
        color: #FFFFFF;
    }
    QHeaderView::section {
        background-color: #383838;
        color: #E0E0E0;
        padding: 6px;
        border: none;
        border-right: 1px solid #505050;
        border-bottom: 1px solid #505050;
        font-weight: bold;
    }
    QDoubleSpinBox, QSpinBox {
        padding: 4px 8px;
        border: 1px solid #404040;
        border-radius: 4px;
        background-color: #2D2D2D;
        color: #E0E0E0;
        min-height: 28px;
        min-width: 80px;
    }
    QDoubleSpinBox QLineEdit, QSpinBox QLineEdit {
        background-color: #2D2D2D;
        color: #E0E0E0;
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
        border: 1px solid #404040;
        border-radius: 4px;
        background-color: #2D2D2D;
        color: #E0E0E0;
        min-height: 26px;
    }
    QComboBox::drop-down {
        subcontrol-origin: padding;
        subcontrol-position: center right;
        width: 20px;
        border-left: 1px solid #404040;
        border-top-right-radius: 3px;
        border-bottom-right-radius: 3px;
        background-color: #383838;
    }
    QComboBox::drop-down:hover {
        background-color: #424242;
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
        border-color: #2196F3;
    }
    QComboBox QAbstractItemView {
        background-color: #2D2D2D;
        color: #E0E0E0;
        selection-background-color: #2196F3;
        selection-color: #FFFFFF;
    }
    QListWidget {
        background-color: #2D2D2D;
        color: #E0E0E0;
        border: 1px solid #404040;
    }
    QListWidget::item {
        color: #E0E0E0;
    }
    QListWidget::item:selected {
        background-color: #2196F3;
        color: #FFFFFF;
    }
    QPushButton {
        padding: 6px 12px;
        border: 1px solid #404040;
        border-radius: 4px;
        background-color: #383838;
        color: #E0E0E0;
    }
    QPushButton:hover {
        background-color: #424242;
    }
    QPushButton:pressed {
        background-color: #303030;
    }
    QRadioButton, QCheckBox {
        background-color: transparent;
        color: #E0E0E0;
    }
    QSlider::groove:horizontal {
        height: 6px;
        background: #505050;
        border-radius: 3px;
    }
    QSlider::handle:horizontal {
        background: #2196F3;
        width: 16px;
        height: 16px;
        margin: -5px 0;
        border-radius: 8px;
    }
    QSlider::sub-page:horizontal {
        background: #2196F3;
        border-radius: 3px;
    }
    QProgressBar {
        border: 1px solid #404040;
        border-radius: 4px;
        text-align: center;
        background-color: #2D2D2D;
        color: #E0E0E0;
    }
    QProgressBar::chunk {
        background-color: #66BB6A;
        border-radius: 3px;
    }
    QSplitter {
        background-color: #1E1E1E;
    }
    QSplitter::handle:horizontal {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 transparent, stop:0.4 #606060, stop:0.6 #606060, stop:1 transparent);
        width: 6px;
        margin: 2px 0px;
    }
    QSplitter::handle:horizontal:hover {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 transparent, stop:0.3 #2196F3, stop:0.7 #2196F3, stop:1 transparent);
    }
    QSplitter::handle:horizontal:pressed {
        background: #1976D2;
    }
    QStatusBar {
        background-color: #383838;
        color: #E0E0E0;
    }
    QToolTip {
        background-color: #424242;
        color: #E0E0E0;
        border: 1px solid #606060;
        padding: 4px;
        border-radius: 3px;
    }
    QLineEdit, QTextEdit, QPlainTextEdit {
        selection-background-color: #2196F3;
        selection-color: #FFFFFF;
    }
    QSpinBox, QDoubleSpinBox, QComboBox {
        selection-background-color: #2196F3;
        selection-color: #FFFFFF;
    }
    #collapsibleHeader {
        background-color: #383838;
        border: 1px solid #404040;
    }
    #collapsibleHeader:hover {
        background-color: #424242;
    }
    #collapsibleContent {
        border: 1px solid #404040;
        background-color: #1E1E1E;
    }
"""
