"""One QSS template for both themes. $tokens are substituted by renderer.py.

Rules live in docs/design.md. Never hardcode a color here — only $tokens.
"""

QSS_TEMPLATE = """
/* ============ Base ============ */
* { font-family: "$font_family"; font-size: $font_body; }
QMainWindow, QDialog { background-color: $bg_base; }
QWidget { background-color: $bg_base; color: $text_primary; }
QLabel { background-color: transparent; }

/* ============ Menu bar & menus ============ */
QMenuBar { background-color: $bg_base; border-bottom: 1px solid $border; padding: 1px; }
QMenuBar::item { padding: 4px 10px; background: transparent; border-radius: $radius; }
QMenuBar::item:selected { background-color: $bg_hover; }
QMenu { background-color: $bg_surface; border: 1px solid $border; padding: 4px 0; }
QMenu::item { padding: 5px 24px 5px 28px; }
QMenu::item:selected { background-color: $accent_subtle; }
QMenu::item:disabled { color: $text_disabled; }
QMenu::separator { height: 1px; background: $border; margin: 4px 8px; }

/* ============ Toolbar ============ */
QToolBar { background-color: $bg_base; border-bottom: 1px solid $border;
           min-height: $toolbar_height; spacing: $space_xs; padding: 2px $space_sm; }
QToolBar::separator { width: 1px; background: $border; margin: 6px $space_sm; }
QToolButton { background: transparent; border: none; border-radius: $radius;
              padding: 4px $space_sm; color: $text_secondary; }
QToolButton:hover { background-color: $bg_hover; }
QToolButton:pressed { background-color: $bg_pressed; }
QToolButton:disabled { color: $text_disabled; }
QToolButton[variant="primary"] { background-color: $accent; color: $text_on_accent; font-weight: 600; }
QToolButton[variant="primary"]:hover { background-color: $accent_hover; }
QToolButton[variant="primary"]:pressed { background-color: $accent_pressed; }
QToolButton[variant="primary"]:disabled { background-color: $bg_sunken; color: $text_disabled; }

/* ============ Buttons ============ */
QPushButton { background-color: $bg_surface; color: $text_primary;
              border: 1px solid $border; border-radius: $radius;
              min-height: $control_height; padding: 0 $space_md; }
QPushButton:hover { background-color: $bg_hover; }
QPushButton:pressed { background-color: $bg_pressed; }
QPushButton:disabled { background-color: $bg_sunken; color: $text_disabled; border-color: $border; }
QPushButton:focus { border-color: $accent; }
QPushButton[variant="primary"] { background-color: $accent; color: $text_on_accent;
                                 border: none; font-weight: 600; }
QPushButton[variant="primary"]:hover { background-color: $accent_hover; }
QPushButton[variant="primary"]:pressed { background-color: $accent_pressed; }
QPushButton[variant="primary"]:disabled { background-color: $bg_sunken; color: $text_disabled; }
QPushButton[variant="ghost"] { background: transparent; border: none; color: $text_secondary; }
QPushButton[variant="ghost"]:hover { background-color: $bg_hover; }
QPushButton[variant="ghost"]:pressed { background-color: $bg_pressed; }
QPushButton[variant="link"] { background: transparent; border: none; color: $accent;
                              text-align: left; padding: 0; min-height: 0; }
QPushButton[variant="link"]:hover { text-decoration: underline; }

/* ============ Inputs ============ */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: $bg_surface; color: $text_primary;
    border: 1px solid $border; border-radius: $radius;
    min-height: $control_height; padding: 0 $space_sm; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: $accent; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    background-color: $bg_sunken; color: $text_disabled; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: url($qss_icons/chevron-down.svg); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background-color: $bg_surface; border: 1px solid $border;
    selection-background-color: $accent_subtle; selection-color: $text_primary; outline: none; }
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button { border: none; background: transparent; width: 16px; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url($qss_icons/chevron-up.svg); width: 10px; height: 10px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url($qss_icons/chevron-down.svg); width: 10px; height: 10px; }

/* ============ Checkbox / radio ============ */
QCheckBox, QRadioButton { background: transparent; spacing: $space_sm; }
QCheckBox::indicator, QRadioButton::indicator { width: 14px; height: 14px;
    border: 1px solid $border_strong; background-color: $bg_surface; }
QCheckBox::indicator { border-radius: 2px; }
QRadioButton::indicator { border-radius: 7px; }
QCheckBox::indicator:checked { background-color: $accent; border-color: $accent;
    image: url($qss_icons/check.svg); }
QRadioButton::indicator:checked { border: 4px solid $accent; background-color: $bg_surface;
    width: 8px; height: 8px; border-radius: 8px; }
QCheckBox:disabled, QRadioButton:disabled { color: $text_disabled; }

/* ============ Tabs ============ */
QTabWidget::pane { border: none; border-top: 1px solid $border; background-color: $bg_base; }
QTabBar { background: transparent; }
QTabBar::tab { background: transparent; border: none; padding: $space_sm $space_lg;
               color: $text_secondary; border-bottom: 2px solid transparent; }
QTabBar::tab:hover { color: $text_primary; }
QTabBar::tab:selected { color: $text_primary; border-bottom: 2px solid $accent; }

/* ============ Tables ============ */
QTableView { background-color: $bg_surface; alternate-background-color: $bg_surface;
    border: 1px solid $border; gridline-color: transparent;
    selection-background-color: $accent_subtle; selection-color: $text_primary; }
QTableView::item { border-bottom: 1px solid $border; padding: 2px $space_sm; }
QHeaderView { background-color: $bg_base; }
QHeaderView::section { background-color: $bg_base; color: $text_secondary;
    font-size: $font_caption; font-weight: 600; border: none;
    border-bottom: 1px solid $border_strong; padding: 4px $space_sm; }
QTableCornerButton::section { background-color: $bg_base; border: none;
    border-bottom: 1px solid $border_strong; }

/* ============ Group boxes (borderless per design.md) ============ */
QGroupBox { border: none; margin-top: $space_lg; padding-top: $space_xs;
            background: transparent; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 0; padding: 0;
                   color: $text_muted; font-size: $font_caption; font-weight: 600; }

/* ============ Lists ============ */
QListWidget, QListView { background-color: $bg_surface; border: 1px solid $border;
    border-radius: $radius; outline: none; }
QListWidget::item:selected, QListView::item:selected {
    background-color: $accent_subtle; color: $text_primary; }

/* ============ Scroll areas / bars ============ */
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: $scrollbar_width; margin: 0; }
QScrollBar::handle:vertical { background: $border_strong; border-radius: 4px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: $text_muted; }
QScrollBar:horizontal { background: transparent; height: $scrollbar_width; margin: 0; }
QScrollBar::handle:horizontal { background: $border_strong; border-radius: 4px; min-width: 24px; }
QScrollBar::handle:horizontal:hover { background: $text_muted; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* ============ Splitter / progress / status bar / tooltip ============ */
QSplitter::handle { background-color: $bg_base; }
QSplitter::handle:hover { background-color: $border_strong; }
QProgressBar { background-color: $bg_sunken; border: none; border-radius: 3px;
               max-height: 6px; text-align: center; }
QProgressBar::chunk { background-color: $accent; border-radius: 3px; }
QStatusBar { background-color: $bg_base; border-top: 1px solid $border; color: $text_secondary; }
QStatusBar::item { border: none; }
QToolTip { background-color: $tooltip_bg; color: $tooltip_text;
           border: 1px solid $border_strong; padding: 4px 6px; }

/* ============ Status properties (set via themes.set_status) ============ */
QLabel[status="success"] { color: $success; }
QLabel[status="warning"] { color: $warning; }
QLabel[status="error"] { color: $error; }
QLabel[status="muted"] { color: $text_muted; }
QLabel[status="accent"] { color: $accent; }

/* ============ Named structural widgets ============ */
QLabel#SectionLabel { color: $text_muted; font-size: $font_caption;
                      font-weight: 600; letter-spacing: 1px; }
QLabel#SubsectionLabel { color: $text_secondary; font-size: $font_caption; font-weight: 600; }
QLabel#PlaceholderLabel { color: $text_muted; }
QFrame#SectionHeader { background: transparent; border: none; border-bottom: 1px solid $border; }
QFrame#SectionHeader:hover { background-color: $bg_hover; }
QFrame#SectionContent { background: transparent; border: none; }
QWidget#WellIndicator { background: transparent; }
QWidget#WellIndicator QLabel { color: $text_secondary; }
QFrame#InfoStrip { background: transparent; border: none; }
QFrame#InfoStripRule { background-color: $border; max-width: 1px; }
QLabel#InfoStripLabel { color: $text_muted; font-size: $font_caption; font-weight: 600; }
QLabel#InfoStripValue { color: $text_primary; font-size: $font_subheading; font-weight: 600; }
QLabel#QcChip { font-size: $font_caption; font-weight: 600; }
QFrame#NotificationBanner { border: 1px solid $border; border-radius: $radius; }
QFrame#NotificationBanner[kind="success"] { background-color: $success_subtle; border-color: $success; }
QFrame#NotificationBanner[kind="warning"] { background-color: $warning_subtle; border-color: $warning; }
QFrame#NotificationBanner[kind="info"] { background-color: $accent_subtle; border-color: $accent; }
QFrame#NotificationBanner QLabel { background: transparent; }
QLabel#AboutTitle { font-size: $font_max; font-weight: 600; }
QLabel#StatusDot { min-width: 8px; max-width: 8px; min-height: 8px; max-height: 8px;
                   border-radius: 4px; background-color: $text_muted; }
QLabel#StatusDot[kind="ok"] { background-color: $success; }
QLabel#StatusDot[kind="warn"] { background-color: $warning; }
QDialog#ParametersWindow { background-color: $bg_base; }
QListWidget#ParamsPageList { background: transparent; border: none; padding: 4px 0; }
QListWidget#ParamsPageList::item { height: 26px; padding-left: 12px; border: none;
    border-left: 2px solid transparent; color: $text_primary; }
QListWidget#ParamsPageList::item:hover { background-color: $bg_hover; }
QListWidget#ParamsPageList::item:selected { background-color: $accent_subtle;
    color: $text_primary; border-left: 2px solid $accent; }
QListWidget#ParamsPageList::item:disabled { color: $text_muted; padding-top: 8px; }
QStackedWidget#ParamsStack { background-color: $bg_surface; border: none;
    border-left: 1px solid $border; }
QWidget#ParamsPage { background-color: $bg_surface; }
QWidget#ParamsFooter { background-color: $bg_base; border-top: 1px solid $border; }
QWidget#DataBrowser { background-color: $bg_base; }
QTreeView#DataTree { background-color: $bg_base; border: none; outline: none;
    show-decoration-selected: 1; }
QTreeView#DataTree::item { height: 22px; color: $text_primary; border: none; }
QTreeView#DataTree::item:hover { background-color: $bg_hover; }
QTreeView#DataTree::item:selected { background-color: $accent_subtle; color: $text_primary; }
QTreeView#DataTree::branch { background: transparent; }
QTreeView#DataTree::branch:has-children:closed { image: url($qss_icons/chevron-right.svg); }
QTreeView#DataTree::branch:has-children:open { image: url($qss_icons/chevron-down.svg); }
"""
