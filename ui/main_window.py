"""
Main Window for Petrophyter PyQt
The main application window.
"""

from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QTabWidget,
    QStatusBar,
    QSizePolicy,
    QSplitter,
    QMessageBox,
    QMenu,
    QProgressBar,
    QDialog,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon

from .tabs import (
    QCTab,
    PetrophysicsTab,
    LogDisplayTab,
    DiagnosticsTab,
    SummaryTab,
    ExportTab,
)

from PyQt6.QtCore import Qt, QTimer, QSettings
from PyQt6.QtGui import QIcon
import functools
import traceback
import threading
import logging
import re

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.app_model import AppModel
from services.analysis_service import AnalysisService, BatchRunner
from services.merge_service import MergeService
from services.load_service import (
    LoadWorker,
    build_well,
    parse_file,
    sanitize_error_detail,
)
from services.export_service import ExportService
from services.session_service import SessionService, is_v2_session
from .widgets.about_dialog import AboutDialog
from .widgets.notification_banner import NotificationBanner
from .parameters_window import PAGES, ParametersWindow
from .data_browser import DataBrowserPanel
from themes.tokens import METRICS
from .widgets.merge_dialog import MergeDialog
from .widgets.load_summary_dialog import LoadSummaryDialog

try:  # provided by the multi-well data-browser work
    from .widgets.well_selector import WellSelector
except ImportError:  # pragma: no cover - until that module lands
    WellSelector = None
from .tabs.qc_tab import QCTab
from .tabs.petrophysics_tab import PetrophysicsTab
from .tabs.log_display_tab import LogDisplayTab
from .tabs.diagnostics_tab import DiagnosticsTab
from .tabs.summary_tab import SummaryTab
from .tabs.export_tab import ExportTab

from modules.formation_tops import FormationTops
from modules.core_handler import CoreDataHandler
from modules.well_matching import assign_to_wells, depth_coverage_warning


logger = logging.getLogger(__name__)


def _restoring_guard(method):
    """Programmatic widget updates emit parameters_updated; don't mark results stale."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        previous = getattr(self, "_restoring", False)
        self._restoring = True
        try:
            return method(self, *args, **kwargs)
        finally:
            self._restoring = previous

    return wrapper


_sanitize_error_detail = sanitize_error_detail


def _failure_message(generic: str, detail=None) -> str:
    """Build a concise user-facing failure message with optional detail."""
    safe_detail = _sanitize_error_detail(detail)
    return f"{generic}:\n{safe_detail}" if safe_detail else generic


class _WellIndicator(QWidget):
    """Toolbar-right widget: status dot + well summary text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WellIndicator")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(6)
        from ui.widgets.status_dot import StatusDot

        self.dot = StatusDot("off")
        self.label = QLabel("No data loaded")
        layout.addWidget(self.dot)
        layout.addWidget(self.label)

    def set_well(self, name: str, rows: int, curves: int):
        self.dot.set_kind("ok")
        self.label.setText(f"{name} · {rows:,} rows · {curves} curves")

    def set_empty(self):
        self.dot.set_kind("off")
        self.label.setText("No data loaded")


class MainWindow(QMainWindow):
    """
    Main application window for Petrophyter PyQt.
    """

    def __init__(self, theme_manager=None):
        super().__init__()

        # Store theme manager
        self.theme_manager = theme_manager

        # Initialize model
        self.model = AppModel()

        # Initialize services
        self.analysis_service = AnalysisService()
        self.batch_runner = BatchRunner(self)
        self.merge_service = MergeService()
        self.export_service = ExportService()
        self.session_service = SessionService()

        # Multi-file load state (see _begin_load)
        self._load_queue = []
        self._load_current = None
        self._load_notes = []
        self._load_added = []
        self._load_multi_file = False
        self._load_step = 0.5
        self._load_gap = 5.0
        self._bulk_loading = False
        self._load_worker = None
        # Batch analysis: number of wells in the current run.
        self._batch_total = 0

        # Setup UI
        self._build_actions()
        self._setup_ui()
        self._setup_connections()

        # Listen for theme changes
        if self.theme_manager:
            self.theme_manager.on_theme_changed(self._handle_theme_change)

        # Set window properties
        self.setWindowTitle("Petrophyter")

        self.setMinimumSize(1400, 900)
        self._restore_ui_state()

        # Set initial theme action state
        if self.theme_manager:
            current = self.theme_manager.get_current_theme()
            self.actions_["theme_dark" if current == "dark" else "theme_light"].setChecked(True)
            self._handle_theme_change(current)

    def _setup_ui(self):
        """Setup the main UI layout."""
        self._build_menus()
        self._build_toolbar()

        # Central widget with splitter
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create splitter with proper configuration
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(6)  # Visible handle for resizing
        splitter.setChildrenCollapsible(False)  # Prevent accidental collapse

        # =====================================================================
        # LEFT DATA BROWSER
        # =====================================================================
        self.data_browser = DataBrowserPanel(self.model)
        splitter.addWidget(self.data_browser)
        self.data_browser.set_actions(self.actions_)
        self.data_browser.action_requested.connect(self._on_browser_action)
        self.params_window = ParametersWindow(self.model, self)
        self.merge_dialog = MergeDialog(self)

        # =====================================================================
        # MAIN CONTENT (TABS)
        # =====================================================================
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(10, 10, 10, 10)

        self.banner = NotificationBanner()
        content_layout.addWidget(self.banner)

        # Tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.TabPosition.North)

        # Create tabs
        self.qc_tab = QCTab(self.model)
        self.petro_tab = PetrophysicsTab(self.model)
        self.log_tab = LogDisplayTab(self.model)
        self.diag_tab = DiagnosticsTab(self.model)
        self.summary_tab = SummaryTab(self.model)
        self.export_tab = ExportTab(self.model)

        self.tab_widget.addTab(self.qc_tab, "Data QC")
        self.tab_widget.addTab(self.petro_tab, "Petrophysics")
        self.tab_widget.addTab(self.log_tab, "Log Display")
        self.tab_widget.addTab(self.diag_tab, "Diagnostics")
        self.tab_widget.addTab(self.summary_tab, "Summary")
        self.tab_widget.addTab(self.export_tab, "Export")
        # Plot tabs redraw only while visible; the others are marked dirty
        # and catch up when they become current.
        self._lazy_tabs = (self.qc_tab, self.petro_tab, self.log_tab, self.diag_tab)
        self._dirty_tabs = set()
        self.tab_widget.currentChanged.connect(self._refresh_current_tab)

        content_layout.addWidget(self.tab_widget)

        splitter.addWidget(content_widget)

        # Use stretch factors for responsive sizing
        splitter.setStretchFactor(0, 0)  # Data Browser: fixed width, don't stretch
        splitter.setStretchFactor(1, 1)  # Content: stretch to fill available space

        # Set initial sizes (data browser : content)
        splitter.setSizes([METRICS["panel_default_width"], 1140])

        # Store reference for potential later use
        self.main_splitter = splitter

        main_layout.addWidget(splitter)

        # =====================================================================
        # STATUS BAR
        # =====================================================================
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Ready. Load a LAS file to begin.")
        self.status_progress = QProgressBar()
        self.status_progress.setFixedWidth(120)
        self.status_progress.setTextVisible(False)
        self.status_progress.setVisible(False)
        self.qc_chip = QLabel()
        self.qc_chip.setObjectName("QcChip")
        self.qc_chip.setVisible(False)
        self.stale_label = QLabel("Parameters changed — press F5 to update results")
        self.stale_label.setObjectName("StaleLabel")
        self.stale_label.setVisible(False)
        self.statusBar.addPermanentWidget(self.stale_label)
        self.statusBar.addPermanentWidget(self.status_progress)
        self.statusBar.addPermanentWidget(self.qc_chip)
        self._restoring = False

    def _setup_connections(self):
        """Connect signals and slots."""
        # Data browser refresh on any data change
        for signal in (
            self.model.formation_tops_loaded,
            self.model.core_data_loaded,
            self.params_window.curve_mapping_widget.mapping_changed,
        ):
            signal.connect(lambda *_: self.data_browser.rebuild())
        self.params_window.calculate_rw_rsh_clicked.connect(self._on_calculate_rw_rsh)
        self.params_window.calculate_shale_clicked.connect(self._on_calculate_shale)
        self.params_window.apply_shale_clicked.connect(self._on_apply_shale)
        self.params_window.calculate_perm_clicked.connect(self._on_calculate_perm)

        self.params_window.parameters_updated.connect(self._on_parameters_updated)
        self.model.parameters_changed.connect(self._on_parameters_updated)
        self.model.scoped_params_changed.connect(self._on_scoped_params_changed)
        self.model.formation_tops_loaded.connect(self._on_tops_or_core_changed)
        self.model.core_data_loaded.connect(self._on_tops_or_core_changed)
        self.export_tab.export_succeeded.connect(
            lambda path: self.show_banner("success", f"Exported to {path}")
        )
        self.summary_tab.well_activated.connect(self._on_well_selected)

        # Batch analysis signals
        self.batch_runner.started.connect(self._on_batch_started)
        self.batch_runner.progress.connect(self._on_batch_progress)
        self.batch_runner.well_completed.connect(self._on_well_completed)
        self.batch_runner.well_failed.connect(self._on_well_failed)
        self.batch_runner.finished.connect(self._on_batch_finished)

        # Merge service signals
        self.merge_service.started.connect(self._on_merge_started)
        self.merge_service.progress.connect(self._on_merge_progress)
        self.merge_service.completed.connect(self._on_merge_completed)
        self.merge_service.error.connect(self._on_merge_error)

        # Export signals
        self.export_tab.export_csv.connect(self._on_export_csv)
        self.export_tab.export_excel.connect(self._on_export_excel)
        self.export_service.export_complete.connect(self.export_tab.show_export_success)
        self.export_service.export_error.connect(self.export_tab.show_export_error)

        # Wells
        project = self.model.project
        project.active_well_changed.connect(self._on_active_well_changed)
        project.wells_changed.connect(self._on_wells_changed)
        if hasattr(self.data_browser, "well_selected"):
            self.data_browser.well_selected.connect(self._on_well_selected)
        if hasattr(self.data_browser, "remove_well_requested"):
            self.data_browser.remove_well_requested.connect(self._on_remove_well_requested)

        # Model signals
        self.model.data_loaded.connect(self._on_data_loaded)
        self.model.analysis_complete.connect(self._on_results_updated)

    def _on_about_triggered(self):
        """Show the About dialog."""
        dialog = AboutDialog(self)
        dialog.exec()

    def _set_theme(self, name: str):
        """Switch theme through the theme manager (if any)."""
        if self.theme_manager:
            self.theme_manager.set_theme(name)

    def _open_las_dialog(self):
        """Open LAS file dialog."""
        from PyQt6.QtWidgets import QFileDialog

        files, _ = QFileDialog.getOpenFileNames(
            self, "Open LAS File(s)", "", "LAS Files (*.las *.LAS);;All Files (*)"
        )
        if files:
            self._on_las_files_selected(files)

    def _open_tops_dialog(self):
        """Open formation tops file dialog."""
        from PyQt6.QtWidgets import QFileDialog

        file, _ = QFileDialog.getOpenFileName(
            self, "Open Formation Tops", "", "Text Files (*.txt *.csv);;All Files (*)"
        )
        if file:
            self._on_tops_file_selected(file)

    def _open_core_dialog(self):
        """Open core data file dialog."""
        from PyQt6.QtWidgets import QFileDialog

        file, _ = QFileDialog.getOpenFileName(
            self, "Open Core Data", "", "Text Files (*.txt *.csv);;All Files (*)"
        )
        if file:
            self._on_core_file_selected(file)

    def closeEvent(self, event):
        settings = QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope, "Petrophyter Team", "Petrophyter")
        settings.setValue("ui/geometry", self.saveGeometry())
        settings.setValue("ui/windowState", self.saveState())
        settings.setValue("ui/splitterSizes", self.main_splitter.saveState())
        settings.setValue(
            "ui/dataBrowserVisible", self.actions_["toggle_browser"].isChecked()
        )
        settings.setValue("ui/activeTab", self.tab_widget.currentIndex())
        settings.setValue("ui/paramsWindowGeometry", self.params_window.saveGeometry())
        settings.setValue("ui/paramsWindowPage", self.params_window.current_page())
        self.params_window.close()
        super().closeEvent(event)

    def _restore_ui_state(self):
        settings = QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope, "Petrophyter Team", "Petrophyter")
        geometry = settings.value("ui/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.showMaximized()
        state = settings.value("ui/windowState")
        if state is not None:
            self.restoreState(state)
        splitter = settings.value("ui/splitterSizes")
        if splitter is not None:
            self.main_splitter.restoreState(splitter)
        visible = settings.value("ui/dataBrowserVisible", True, type=bool)
        self.data_browser.setVisible(visible)
        self.actions_["toggle_browser"].setChecked(visible)
        pw_geometry = settings.value("ui/paramsWindowGeometry")
        if pw_geometry is not None:
            self.params_window.restoreGeometry(pw_geometry)
        page = settings.value("ui/paramsWindowPage", "scope", type=str)
        if page in {key for key, _title, _menu, _icon in PAGES}:
            self.params_window.open_page(page, show=False)
        tab = settings.value("ui/activeTab", 0, type=int)
        if 0 <= tab < self.tab_widget.count():
            self.tab_widget.setCurrentIndex(tab)

    def _toggle_browser(self, checked: bool):
        """Show or hide the left panel (retargeted to the Data Browser in Task 12C)."""
        self.data_browser.setVisible(checked)

    def _open_user_guide(self):
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "docs",
            "user-guide.md",
        )
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _refresh_window_title(self):
        name = None
        active = self.model.active_well
        if active is not None:
            name = active.display_name or os.path.basename(str(active.las_filename))
        elif self.model.las_filename:
            name = os.path.basename(str(self.model.las_filename))
        if name and len(self.model.project) > 1:
            name = f"{name} · {len(self.model.project)} wells"
        self.setWindowTitle(f"{name} — Petrophyter" if name else "Petrophyter")

    def _build_actions(self):
        from PyQt6.QtGui import QAction, QActionGroup, QKeySequence
        from themes.icon_loader import get_icon

        def act(key, text, icon=None, shortcut=None, slot=None, checkable=False):
            action = QAction(text, self)
            if icon:
                action.setIcon(get_icon(icon))
                self._action_icons[key] = icon
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            if slot:
                action.triggered.connect(slot)
            action.setCheckable(checkable)
            self.actions_[key] = action
            return action

        self.actions_ = {}
        self._action_icons = {}
        act("new_project", "New Project", "file-plus", "Ctrl+N", self._on_new_project)
        act("open_las", "Open LAS File(s)…", "folder-open", "Ctrl+O", self._open_las_dialog)
        act("open_tops", "Open Formation Tops…", "layers", None, self._open_tops_dialog)
        act("open_core", "Open Core Data…", "database", None, self._open_core_dialog)
        act("merge_las", "Merge LAS Files…", "merge", None, self._open_las_dialog)
        act("save_merged", "Save Merged LAS…", "download", None, self._on_download_merged)
        act("exit", "Exit", "log-out", None, self.close)
        act("save_session", "Save Session…", "save", "Ctrl+S", self._on_save_session)
        act("load_session", "Load Session…", "folder-input", "Ctrl+Shift+O", self._on_load_session)
        act("run_analysis", "Run Analysis", "play", "F5", self._on_run_analysis)
        act("run_all", "Run All Wells", "layers", "Ctrl+Shift+R", self._on_run_all)
        act("toggle_browser", "Data Browser", "panel-left", "Ctrl+B",
            self._toggle_browser, checkable=True)
        act("theme_light", "Light", "sun", None, lambda: self._set_theme("light"), checkable=True)
        act("theme_dark", "Dark", "moon", None, lambda: self._set_theme("dark"), checkable=True)
        act("user_guide", "User Guide", "book-open", None, self._open_user_guide)
        act("about", "About Petrophyter", "info", None, self._on_about_triggered)
        for key, title, _menu, icon in PAGES:
            act(f"page_{key}", f"{title}…", icon, None,
                lambda _=False, k=key: self.params_window.open_page(k))
        act("params_window", "Parameters Window", "sliders-horizontal", "Ctrl+P",
            lambda: self.params_window.open_page(self.params_window.current_page()))
        for key in ("run_analysis", "run_all", "toggle_browser", "params_window"):
            self.actions_[key].setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.actions_["page_core"].setEnabled(False)
        group = QActionGroup(self)
        group.addAction(self.actions_["theme_light"])
        group.addAction(self.actions_["theme_dark"])
        self.actions_["run_analysis"].setEnabled(False)
        self.actions_["run_all"].setEnabled(False)
        self.actions_["save_merged"].setEnabled(False)
        self.actions_["toggle_browser"].setChecked(True)

    def _build_menus(self):
        from themes.icon_loader import get_icon

        bar = self.menuBar()
        self._menus = {}
        file_menu = bar.addMenu("&File")
        self._menus["file"] = file_menu
        for key in ("new_project", None, "open_las", "open_tops", "open_core",
                    "merge_las", None, "save_merged", None, "exit"):
            file_menu.addSeparator() if key is None else file_menu.addAction(self.actions_[key])
        session = bar.addMenu("&Session")
        session.addAction(self.actions_["save_session"])
        session.addAction(self.actions_["load_session"])
        analysis = bar.addMenu("&Analysis")
        analysis.addAction(self.actions_["run_analysis"])
        analysis.addAction(self.actions_["run_all"])
        self._menus["analysis"] = analysis
        view = bar.addMenu("&View")
        view.addAction(self.actions_["toggle_browser"])
        self._menus["view"] = view
        self._menus["view_theme_sep"] = view.addSeparator()
        analysis.addSeparator()
        menus = {"Analysis": analysis}
        for name in ("Parameters", "Corrections"):
            menus[name] = QMenu(f"&{name}", self)
            bar.insertMenu(view.menuAction(), menus[name])
        for key, _title, menu, _icon in PAGES:
            if key == "rock":
                menus[menu].addSeparator()  # Basic | Advanced split (spec §2.2)
            menus[menu].addAction(self.actions_[f"page_{key}"])
        view.insertAction(self._menus["view_theme_sep"], self.actions_["params_window"])
        theme_menu = view.addMenu("Theme")
        self._action_icons["theme_menu"] = "palette"
        self.actions_["theme_menu"] = theme_menu.menuAction()
        theme_menu.menuAction().setIcon(get_icon("palette"))
        theme_menu.addAction(self.actions_["theme_light"])
        theme_menu.addAction(self.actions_["theme_dark"])
        help_menu = bar.addMenu("&Help")
        help_menu.addAction(self.actions_["user_guide"])
        help_menu.addAction(self.actions_["about"])

    def _build_toolbar(self):
        from PyQt6.QtCore import QSize
        from PyQt6.QtWidgets import QToolBar, QToolButton

        toolbar = QToolBar("Main")
        toolbar.setObjectName("MainToolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setIconSize(QSize(18, 18))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.addAction(self.actions_["open_las"])
        toolbar.addAction(self.actions_["save_session"])
        params_button = QToolButton()
        params_button.setDefaultAction(self.actions_["params_window"])
        params_button.setText("Parameters")
        params_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        params_button.setProperty("variant", "ghost")
        toolbar.addWidget(params_button)
        self.params_button = params_button
        toolbar.addSeparator()
        self.run_button = QToolButton()
        self.run_button.setDefaultAction(self.actions_["run_analysis"])
        self.run_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.run_button.setProperty("variant", "primary")
        toolbar.addWidget(self.run_button)
        self.run_all_button = QToolButton()
        self.run_all_button.setDefaultAction(self.actions_["run_all"])
        self.run_all_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.run_all_button.setProperty("variant", "ghost")
        self._run_all_action = toolbar.addWidget(self.run_all_button)
        self._run_all_action.setVisible(False)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        self.well_selector = None
        self._well_selector_action = None
        if WellSelector is not None:
            self.well_selector = WellSelector()
            self.well_selector.set_project(self.model.project)
            self.well_selector.well_selected.connect(self._on_well_selected)
            self._well_selector_action = toolbar.addWidget(self.well_selector)
            self._well_selector_action.setVisible(False)
        self.well_indicator = _WellIndicator()
        toolbar.addWidget(self.well_indicator)
        self.addToolBar(toolbar)
        self.main_toolbar = toolbar

    def show_banner(self, kind: str, message: str):
        self.banner.show_message(kind, message)

    def update_qc_chip(self, score):
        from themes.helpers import set_status

        if score is None:
            self.qc_chip.setVisible(False)
            return
        self.qc_chip.setText(f"QC {score}/100")
        set_status(
            self.qc_chip,
            "success" if score >= 90 else "warning" if score >= 70 else "error",
        )
        self.qc_chip.setVisible(True)

    def _refresh_qc_chip(self):
        score = getattr(self.model.qc_report, "overall_quality_score", None)
        self.update_qc_chip(None if score is None else round(score))

    def _set_progress(self, value: int, message: str = None):
        self.status_progress.setVisible(0 < value < 100)
        self.status_progress.setValue(value)
        if message:
            self.statusBar.showMessage(message)

    def _recompute_stale(self, keys=None):
        """Stale = the well's current parameters differ from those of its last run (§5.5)."""
        project = self.model.project
        wells = project.wells if keys is None else [
            ds for ds in (project.get(k) for k in keys) if ds is not None
        ]
        changed = []
        for ds in wells:
            stale = bool(ds.calculated and self.model.well_params_hash(ds) != ds.run_params_hash)
            if stale != ds.stale:
                ds.stale = stale
                changed.append(ds.key)
        self._sync_stale_label()
        for key in changed:
            project.well_updated.emit(key)

    def _on_parameters_updated(self, *_):
        """A project-level or active-well parameter changed (programmatic restores are ignored)."""
        if not self._restoring:
            self._recompute_stale()

    def _on_scoped_params_changed(self, key: str):
        if not self._restoring:
            self._recompute_stale([key] if key else None)

    def _on_tops_or_core_changed(self, *_):
        active = self.model.project.active_key
        if active is not None and not self._restoring:
            self._recompute_stale([active])

    def _sync_stale_label(self):
        """Show the stale label for the active well's flag."""
        from themes.helpers import set_status

        active = self.model.active_well
        stale = bool(active is not None and active.calculated and active.stale)
        if stale:
            set_status(self.stale_label, "warning")
        self.stale_label.setVisible(stale)
        self.data_browser.set_results_stale(stale)

    # ---- well identity / depth sanity helpers ---------------------------

    @staticmethod
    def _fmt_depth(value: float) -> str:
        from PyQt6.QtCore import QLocale

        return QLocale().toString(float(value), "f", 1)

    def _log_depth_range(self):
        data = self.model.las_data
        if data is None or len(data) == 0:
            return None
        col = "DEPTH" if "DEPTH" in data.columns else data.columns[0]
        series = data[col].dropna()
        if series.empty:
            return None
        return float(series.min()), float(series.max())

    def _depth_overlap_warnings(self) -> list:
        """Warn when tops or core lie entirely outside the log depth range."""
        rng = self._log_depth_range()
        if rng is None:
            return []
        lo, hi = rng
        spans = []
        tops = self.model.formation_tops
        if tops is not None and getattr(tops, "formations", None):
            spans.append((
                "Formation tops",
                min(f.top_depth for f in tops.formations),
                max(f.bottom_depth for f in tops.formations),
            ))
        core = self.model.core_data
        cdata = getattr(core, "data", None)
        ccol = getattr(core, "depth_col", None)
        if cdata is not None and ccol in getattr(cdata, "columns", []):
            depths = cdata[ccol].dropna()
            if not depths.empty:
                spans.append(("Core depths", float(depths.min()), float(depths.max())))
        out = []
        for label, a, b in spans:
            if b < lo or a > hi:
                out.append(
                    f"{label} ({self._fmt_depth(a)}–{self._fmt_depth(b)} ft) "
                    f"do not overlap the log depth range "
                    f"({self._fmt_depth(lo)}–{self._fmt_depth(hi)} ft). "
                    "Check the depth unit."
                )
        return out

    def _show_load_notes(self, parser=None, extra=()):
        """One banner for load-time notes so none hides another."""
        lines = list(extra)
        if parser is not None:
            if getattr(parser, "depth_unit_warning", None):
                lines.append(parser.depth_unit_warning)
            lines.extend(getattr(parser, "unit_warnings", None) or [])
        lines.extend(self._depth_overlap_warnings())
        if lines:
            only_info = all(l.startswith("Reloaded ") for l in lines)
            self.show_banner("info" if only_info else "warning", "\n".join(lines))

    def _sync_model_from_ui(self):
        self.params_window.update_model_from_ui()
        self.merge_dialog.update_model(self.model)

    def _refresh_core_actions(self):
        self.actions_["page_core"].setEnabled(self.params_window.core_unit_combo.isEnabled())

    def _refresh_action_icons(self):
        """Re-render action icons in the current theme's color."""
        from themes.icon_loader import get_icon

        for key, name in self._action_icons.items():
            self.actions_[key].setIcon(get_icon(name))

    def _handle_theme_change(self, theme: str):
        """Refresh widgets when theme changes."""
        self._refresh_action_icons()
        self.data_browser.refresh_theme()
        self.params_window.refresh_theme()
        self.merge_dialog.refresh_theme()
        self.banner.refresh_theme()
        for tab in [
            getattr(self, "qc_tab", None),
            getattr(self, "petro_tab", None),
            getattr(self, "log_tab", None),
            getattr(self, "diag_tab", None),
            getattr(self, "summary_tab", None),
            getattr(self, "export_tab", None),
        ]:
            if tab and hasattr(tab, "refresh_theme"):
                tab.refresh_theme()

    # =========================================================================
    # LAS FILE HANDLING
    # =========================================================================

    def _on_las_files_selected(self, file_paths: list):
        """Open one or more LAS files (several files go through the Load Summary)."""
        paths = [p for p in file_paths if p]
        if not paths:
            return
        if self._bulk_loading:
            self.statusBar.showMessage("Another load is still running")
            return
        if len(paths) == 1:
            self._load_single_las(paths[0])
        else:
            self._start_multi_load(paths)

    @_restoring_guard
    def _load_single_las(self, file_path: str):
        """Load a single LAS file as one well."""
        try:
            self.statusBar.showMessage(f"Loading {os.path.basename(file_path)}...")
            item = parse_file(file_path)
            if not item.ok:
                QMessageBox.critical(
                    self,
                    "Error",
                    _failure_message("Failed to load LAS file", item.error),
                )
                self.statusBar.showMessage("Failed to load LAS file")
                return
            self._begin_load([[item]])
        except Exception as e:
            self._abort_load()
            logger.exception("Unexpected failure loading LAS file %s", file_path)
            QMessageBox.critical(
                self, "Error", _failure_message("Failed to load LAS file", e)
            )
            self.statusBar.showMessage("Error loading file")

    def _start_multi_load(self, paths: list):
        """Parse several files off the GUI thread, then show the Load Summary."""
        from PyQt6.QtCore import QThreadPool

        self._bulk_loading = True
        self._set_load_actions_enabled(False)
        self.statusBar.showMessage(f"Reading {len(paths)} LAS files...")
        self._set_progress(1, None)
        worker = LoadWorker(paths)
        worker.signals.progress.connect(self._on_load_progress)
        worker.signals.completed.connect(self._on_files_parsed)
        worker.signals.error.connect(self._on_load_error)
        self._load_worker = worker  # keep the signal object alive
        if not hasattr(self, "_load_pool"):
            self._load_pool = QThreadPool()
        self._load_pool.start(worker)

    def _on_load_progress(self, message: str, percent: int):
        self._set_progress(max(percent, 1), message)

    def _on_load_error(self, error: str):
        self._abort_load()
        QMessageBox.critical(self, "Error", error)
        self.statusBar.showMessage("Failed to read LAS files")

    def _on_files_parsed(self, parsed: list):
        """Show the Load Summary for parsed files, then load the chosen groups."""
        self._load_worker = None
        self._set_progress(0, "")
        if not any(item.ok for item in parsed):
            details = "\n".join(f"{p.name}: {p.error}" for p in parsed if p.error)
            self._abort_load()
            QMessageBox.warning(
                self, "Warning", "None of the selected files could be read." + (
                    f"\n{details}" if details else ""
                ),
            )
            self.statusBar.showMessage("Failed to load LAS files")
            return
        dialog = LoadSummaryDialog(
            parsed, self.model.merge_step, self.model.merge_gap_limit, self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._abort_load()
            self.statusBar.showMessage("Load cancelled")
            return
        step, gap = dialog.merge_settings()
        notes = [f"{p.name}: {p.error}" for p in parsed if not p.ok]
        self._begin_load(dialog.groups(), step, gap, multi_file=True, notes=notes)

    def _set_load_actions_enabled(self, enabled: bool):
        self.actions_["open_las"].setEnabled(enabled)
        self.actions_["merge_las"].setEnabled(enabled)

    def _abort_load(self):
        self._bulk_loading = False
        self._load_queue = []
        self._load_current = None
        self._load_worker = None
        self._set_load_actions_enabled(True)
        self._set_progress(0, "")

    def _begin_load(self, groups, step=None, gap=None, multi_file=False, notes=()):
        """Build one well per group (merging multi-file groups), then activate the last."""
        self._bulk_loading = True
        self._set_load_actions_enabled(False)
        self._load_queue = [list(group) for group in groups if group]
        self._load_notes = list(notes)
        self._load_added = []
        self._load_multi_file = multi_file
        self._load_current = None
        if step is not None:
            self._load_step, self._load_gap = float(step), float(gap)
            self.model.merge_step, self.model.merge_gap_limit = self._load_step, self._load_gap
            self.merge_dialog.step_spin.setValue(self._load_step)
            self.merge_dialog.gap_spin.setValue(self._load_gap)
        self._advance_load()

    def _advance_load(self):
        """Build singles immediately; start the next merge and wait for it."""
        while self._load_queue:
            group = self._load_queue.pop(0)
            if len(group) == 1:
                self._add_built_well(group, None)
                continue
            self._load_current = group
            self.merge_service.merge_files(
                [item.parser for item in group],
                [item.name for item in group],
                self._load_step,
                self._load_gap,
            )
            return
        self._finish_load()

    def _add_built_well(self, files, merge_result, extra_notes=()):
        names = ", ".join(item.name for item in files)
        try:
            ds = build_well(files, merge_result)
        except Exception as exc:
            logger.exception("Failed to build a well from %s", names)
            self._load_notes.append(
                _failure_message(f"Could not load {names}", exc).replace("\n", " ")
            )
            return
        previous = self.model.project.get(ds.key)
        if previous is not None:
            # Same well key: a reload. The well's own tops/core/scope carry over.
            for field in ("formation_tops", "core_data", "analysis_mode",
                          "selected_formations", "overrides", "zone_overrides"):
                setattr(ds, field, getattr(previous, field))
            ds.display_name = previous.display_name or ds.display_name
            self._load_notes.append(f"Reloaded {ds.display_name}")
        prefix = f"{ds.display_name}: " if self._load_multi_file else ""
        for item in files:
            parser = item.parser
            if getattr(parser, "depth_unit_warning", None):
                self._load_notes.append(prefix + parser.depth_unit_warning)
            self._load_notes.extend(
                prefix + line for line in (getattr(parser, "unit_warnings", None) or [])
            )
        self._load_notes.extend(prefix + line for line in extra_notes)
        key = self.model.add_well(ds, activate=False)
        self._load_added.append(key)

    def _finish_load(self):
        self._bulk_loading = False
        self._load_current = None
        self._set_load_actions_enabled(True)
        self._set_progress(0, "")
        added = self._load_added
        notes = list(dict.fromkeys(self._load_notes))
        if added:
            # Always refresh, even when the last well was already active (reload).
            self.model.project.set_active(added[-1], force=True)
            active = self.model.active_well
            if len(added) == 1 and not self._load_multi_file and active is not None:
                self.statusBar.showMessage(
                    f"Loaded: {active.display_name} ({len(active.las_data)} rows)"
                )
            else:
                self.statusBar.showMessage(f"Loaded {len(added)} well(s)")
        elif notes:
            self.statusBar.showMessage("No wells were loaded")
        self._show_load_notes(None, notes)

    # ---- merge of one group ----
    def _on_merge_started(self):
        """Handle merge started."""
        self._set_progress(1, "Merging...")
        self.statusBar.showMessage("Merging LAS files...")

    def _on_merge_progress(self, message: str, percent: int):
        """Handle merge progress."""
        self._set_progress(percent, message)

    def _on_merge_completed(self, merged_df, merge_report):
        """One group finished merging: build its well, then continue the queue."""
        group = self._load_current
        if group is None:
            return
        self._load_current = None
        self._set_progress(100, "Complete")
        extra = list(getattr(merge_report, "warnings", None) or [])
        self._add_built_well(
            group, {"merged_df": merged_df, "merge_report": merge_report}, extra
        )
        self._advance_load()

    def _on_merge_error(self, error: str):
        """A group could not be merged: report it and carry on with the rest."""
        group = self._load_current or []
        self._load_current = None
        self._set_progress(0, "")
        names = ", ".join(item.name for item in group)
        self._load_notes.append(f"Could not merge {names}: {error}")
        self.statusBar.showMessage("Merge failed")
        self._advance_load()

    def _on_download_merged(self):
        """Handle merged LAS download for the active well."""
        from PyQt6.QtWidgets import QFileDialog

        active = self.model.active_well
        if active is None or not active.merged:
            QMessageBox.warning(self, "Warning", "The active well is not a merged well.")
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Merged LAS",
            "merged_output.las",
            "LAS Files (*.las);;All Files (*)",
        )

        if file_path:
            self.export_service.export_las(
                active.las_data, active.las_parser.well_info, file_path
            )

    # =========================================================================
    # ACTIVE WELL
    # =========================================================================

    def _on_wells_changed(self):
        self._refresh_window_title()
        self._refresh_run_action()
        run_all = getattr(self, "_run_all_action", None)
        if run_all is not None:
            run_all.setVisible(len(self.model.project) > 1)
        action = getattr(self, "_well_selector_action", None)
        if action is not None:
            action.setVisible(len(self.model.project) > 1)

    def _on_well_selected(self, key: str):
        if key and key in self.model.project:
            self.model.set_active_well(key)

    def _on_remove_well_requested(self, key: str):
        ds = self.model.project.get(key)
        if ds is None:
            return
        reply = QMessageBox.question(
            self,
            "Remove Well",
            f"Remove {ds.display_name} from the project?\n\n"
            "Its tops, core data and results will be discarded.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.model.project.remove_well(key)

    def _on_active_well_changed(self, key: str):
        if self._bulk_loading:
            return  # _finish_load refreshes once at the end
        self._refresh_active_well_ui()

    def _refresh_run_action(self):
        """Run is disabled only while the ACTIVE well is running; other wells may run."""
        project = self.model.project
        runner = self.batch_runner
        self.actions_["run_analysis"].setEnabled(
            self.model.active_well is not None and not runner.is_pending(project.active_key)
        )
        self.actions_["run_all"].setEnabled(
            not runner.is_running()
            and any(ds.las_data is not None for ds in project.wells)
        )

    @_restoring_guard
    def _refresh_active_well_ui(self):
        """Point every control and tab at the active well."""
        ds = self.model.active_well
        if ds is None:
            self._reset_ui()
            return
        pw = self.params_window
        data = ds.las_data
        if ds.las_parser is not None:
            curves = list(ds.las_parser.get_available_curves())
        else:
            curves = list(data.columns) if data is not None else []
        detected = {k: v for k, v in ds.curve_mapping.items() if v and v != "None"}
        pw.update_available_curves(curves, detected)
        for ctype, combo in pw.curve_mapping_widget.curve_combos.items():
            wanted = ds.curve_mapping.get(ctype, "None") or "None"
            if wanted != "None" and combo.findText(wanted) < 0:
                combo.addItem(wanted)
            combo.blockSignals(True)
            combo.setCurrentText(wanted)
            combo.blockSignals(False)

        mode_widget = pw.analysis_mode_widget
        formations = (
            ds.formation_tops.get_formation_list() if ds.formation_tops is not None else []
        )
        mode_widget.formation_list.blockSignals(True)
        pw.update_formations_list(formations)
        for index in range(mode_widget.formation_list.count()):
            item = mode_widget.formation_list.item(index)
            item.setSelected(item.text() in ds.selected_formations)
        mode_widget.formation_list.blockSignals(False)
        per_formation = ds.analysis_mode == "Per-Formation"
        (mode_widget.per_formation_radio if per_formation
         else mode_widget.whole_well_radio).setChecked(True)
        mode_widget.formation_label.setVisible(per_formation)
        mode_widget.formation_list.setVisible(per_formation)

        pw.set_core_available(ds.core_data is not None)
        self._refresh_core_actions()

        if data is not None:
            self.well_indicator.set_well(ds.display_name, len(data), len(data.columns))
        else:
            self.well_indicator.set_empty()
        self.actions_["save_merged"].setEnabled(bool(ds.merged))
        self._refresh_run_action()
        self._refresh_qc_chip()
        self._sync_stale_label()
        self._refresh_window_title()
        self._update_all_tabs()

    def _reset_ui(self):
        """Fresh-state UI: no well is active."""
        self.banner.clear()
        self.update_qc_chip(None)
        self.stale_label.setVisible(False)
        self.data_browser.set_results_stale(False)
        self.data_browser.rebuild()
        self.params_window.reset_ui()
        self._refresh_core_actions()
        self.actions_["save_merged"].setEnabled(False)
        self.well_indicator.set_empty()
        self._refresh_run_action()
        self._refresh_window_title()
        self.qc_tab.reset_ui()
        self.petro_tab.reset_ui()
        self.log_tab.reset_ui()
        self.diag_tab.reset_ui()
        self.summary_tab.reset_ui()
        self.export_tab.reset_ui()

    # =========================================================================
    # FORMATION TOPS & CORE DATA
    # =========================================================================

    def _require_active_well(self, what: str) -> bool:
        if self.model.active_well is not None:
            return True
        QMessageBox.warning(
            self, "Warning",
            f"Load a LAS file first. The {what} are attached to the active well.",
        )
        return False

    def _assign_per_well(self, parsed, file_path: str, kind: str, apply):
        """Hand a tops/core file to its wells; returns ``(active_part, notes)``.

        Without a well column the whole file belongs to the active well. With
        one, each part goes to the loaded well it matches (UWI/API or name);
        ``apply(ds, part)`` attaches a part to a non-active well. Unmatched
        names and parts whose depths miss a well's logs are reported.
        """
        project = self.model.project
        active = project.active
        if not parsed.well_names():
            return parsed, []
        matches, unmatched = assign_to_wells(
            parsed.split_by_well(),
            [(ds.key, ds.well_info) for ds in project.wells],
            parsed.well_kind,
        )
        notes = []
        name = os.path.basename(file_path)
        others = [key for key in matches if key != active.key]
        for key in others:
            ds = project.get(key)
            apply(ds, matches[key])
            note = self._coverage_note(ds, matches[key], kind)
            if note:
                notes.append(note)
            project.well_updated.emit(key)
        if others:
            self._recompute_stale(others)
        assigned = [project.get(key).display_name for key in matches]
        if assigned:
            notes.append(f"{name}: {kind} assigned to {', '.join(assigned)}.")
        if unmatched:
            notes.append(
                f"{name}: no loaded well matches {', '.join(unmatched)}; "
                "those rows were not used."
            )
        if active.key not in matches:
            notes.append(f"{name} has no {kind} for the active well {active.display_name}.")
        return matches.get(active.key), notes

    @staticmethod
    def _coverage_note(ds, part, kind: str):
        """Depth-coverage warning for a part attached to a non-active well."""
        data = ds.las_data
        if data is None or "DEPTH" not in data.columns or data["DEPTH"].dropna().empty:
            return None
        depth = data["DEPTH"].dropna()
        if kind == "formation tops":
            formations = getattr(part, "formations", None) or []
            if not formations:
                return None
            top = min(fm.top_depth for fm in formations)
            bottom = max(fm.bottom_depth for fm in formations)
        else:
            frame = getattr(part, "data", None)
            col = getattr(part, "depth_col", None)
            if frame is None or col not in getattr(frame, "columns", []):
                return None
            depths = frame[col].dropna()
            if depths.empty:
                return None
            top, bottom = float(depths.min()), float(depths.max())
        label = f"{ds.display_name}: {kind}"
        return depth_coverage_warning(label, top, bottom, depth.min(), depth.max())

    def _on_tops_file_selected(self, file_path: str):
        """Handle formation tops file selection.

        Tops belong to the active well, unless the file has a well column: then
        every loaded well gets its own rows.
        """
        if not self._require_active_well("formation tops"):
            return
        try:
            tops = FormationTops()
            with open(file_path, "r") as f:
                if tops.read_tops_from_buffer(f):
                    # convert_to_feet() only converts when the unit was detected
                    # as meters; feet/undetected files are left unchanged.
                    tops.convert_to_feet()

                    def attach(ds, part):
                        ds.formation_tops = part
                        ds.tops_path = file_path

                    tops, notes = self._assign_per_well(
                        tops, file_path, "formation tops", attach
                    )
                    if tops is None:
                        self._show_load_notes(None, notes)
                        return
                    self.model.active_well.tops_path = file_path
                    self.model.formation_tops = tops

                    self.params_window.update_formations_list(tops.get_formation_list())

                    self.statusBar.showMessage(
                        f"Loaded {len(tops.formations)} formations"
                    )

                    self._show_load_notes(tops, notes)

                    # Update QC tab
                    self.qc_tab.update_display()
                else:
                    detail = getattr(tops, "last_error", None)
                    logger.error(
                        "Failed to parse formation tops file %s: %s",
                        file_path,
                        detail,
                    )
                    QMessageBox.warning(
                        self,
                        "Warning",
                        _failure_message("Failed to parse formation tops file", detail),
                    )

        except Exception as e:
            logger.exception("Unexpected failure loading formation tops %s", file_path)
            QMessageBox.critical(
                self, "Error", _failure_message("Failed to load formation tops", e)
            )

    def _on_core_file_selected(self, file_path: str):
        """Handle core data file selection.

        Core belongs to the active well, unless the file has a well column:
        then every loaded well gets its own samples.
        """
        if not self._require_active_well("core data"):
            return
        try:
            self._sync_model_from_ui()

            handler = CoreDataHandler()
            depth_unit = self.model.core_depth_unit
            with open(file_path, "r") as f:
                if handler.read_core_from_buffer(f, depth_unit=depth_unit):

                    def attach(ds, part):
                        ds.core_data = part
                        ds.core_path = file_path
                        ds.core_depth_unit = depth_unit

                    handler, notes = self._assign_per_well(
                        handler, file_path, "core data", attach
                    )
                    if handler is None:
                        self._show_load_notes(None, notes)
                        return
                    self.model.active_well.core_path = file_path
                    self.model.core_data = handler
                    self.params_window.set_core_available(True)
                    self._refresh_core_actions()

                    summary = handler.get_summary()

                    self.statusBar.showMessage(
                        f"Loaded {summary['n_samples']} core samples"
                    )

                    self._show_load_notes(handler, notes)
                else:
                    QMessageBox.warning(
                        self, "Warning", "Failed to parse core data file"
                    )

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load core data:\n{str(e)}")

    # =========================================================================
    # ANALYSIS
    # =========================================================================

    def _on_run_analysis(self):
        """Run the active well (always, even when its results are up to date)."""
        if self.model.las_data is None:
            QMessageBox.warning(
                self, "Warning", "No data loaded. Please load a LAS file first."
            )
            return
        self._start_runs([self.model.project.active_key], force=True)

    def _on_run_all(self):
        """Run every well with data; wells whose parameters are unchanged are skipped."""
        keys = [ds.key for ds in self.model.project.wells if ds.las_data is not None]
        if not keys:
            QMessageBox.warning(
                self, "Warning", "No data loaded. Please load a LAS file first."
            )
            return
        self._start_runs(keys, force=False)

    def _start_runs(self, keys, force: bool):
        # Update the model from the UI and disable Run before the background
        # workers can report back.
        self._sync_model_from_ui()
        if self.model.project.active_key in keys:
            self.actions_["run_analysis"].setEnabled(False)
        self.batch_runner.run(
            self.model, keys, force=force, extend=self.batch_runner.is_running()
        )
        self._refresh_run_action()

    def _on_batch_started(self, total: int):
        self._batch_total = total
        self.banner.clear()
        self._set_progress(1, "Analyzing..." if total == 1 else f"Running 0/{total} wells…")
        self._refresh_run_action()

    def _on_batch_progress(self, done: int, total: int):
        self._batch_total = total
        message = "Analyzing..." if total == 1 else f"Running {done}/{total} wells…"
        self._set_progress(max(1, min(99, int(100 * done / max(total, 1)))), message)
        self._refresh_run_action()

    def _on_well_completed(self, key: str, results, summary, params_hash: str):
        """Store results in the well named by ``key`` (dropped if it is gone)."""
        project = self.model.project
        ds = project.get(key)
        if ds is None:
            return
        ds.error = None
        ds.run_params_hash = params_hash
        ds.stale = self.model.well_params_hash(ds) != params_hash
        if key == project.active_key:
            # Results and summary are stored together so observers see a
            # matching pair and only one completion refresh.
            self.model.set_analysis_results(results, summary)
            self._sync_stale_label()
        else:
            ds.results, ds.summary, ds.calculated = results, summary, True
        project.well_updated.emit(key)

    def _on_well_failed(self, key: str, message: str):
        ds = self.model.project.get(key)
        if ds is None:
            return
        ds.error = _sanitize_error_detail(message) or "Analysis failed"
        self.model.project.well_updated.emit(key)

    def _on_batch_finished(self, report: dict):
        """Report the whole run once: status bar, a banner or one error dialog."""
        self._set_progress(0, "")
        self._refresh_run_action()
        project = self.model.project
        ok, failed = list(report.get("ok", [])), dict(report.get("failed", {}))
        skipped = list(report.get("skipped", []))
        if report.get("cancelled"):
            self.statusBar.showMessage("Analysis cancelled")
            return

        def name(key):
            ds = project.get(key)
            return ds.display_name if ds is not None and ds.display_name else key

        if failed:
            if len(failed) == 1 and not ok:
                (message,) = failed.values()
                QMessageBox.critical(self, "Analysis Error", message)
                self.statusBar.showMessage("Analysis failed")
                return
            parts = ", ".join(
                f"{name(k)} ({_sanitize_error_detail(m) or 'Analysis failed'})"
                for k, m in failed.items()
            )
            noun = "well" if len(failed) == 1 else "wells"
            self.show_banner("warning", f"{len(failed)} {noun} failed: {parts}")
            self.statusBar.showMessage(
                f"{len(ok)} analysed, {len(failed)} failed" if ok else "Analysis failed"
            )
            return
        if not ok:
            if skipped:
                self.statusBar.showMessage("All wells are up to date")
            return
        if len(ok) == 1:
            ds = project.get(ok[0])
            summary = (ds.summary if ds is not None else None) or {}
            message = (
                f"Net Pay {summary.get('net_pay', 0):.1f} ft · "
                f"Gross Sand {summary.get('gross_sand', 0):.1f} ft · "
                f"N/G {summary.get('ng_pay', 0) * 100:.1f}%"
            )
            if ok[0] == project.active_key:
                self.statusBar.showMessage("Analysis complete")
                self.show_banner("success", f"Analysis complete — {message}")
            else:
                self.statusBar.showMessage(f"Analysis complete for {name(ok[0])}")
                self.show_banner("success", f"Analysis complete for {name(ok[0])} — {message}")
            return
        text = f"Analysis complete for {len(ok)} wells"
        if skipped:
            text += f" ({len(skipped)} unchanged)"
        self.statusBar.showMessage(text)
        self.show_banner("success", text)

    def _on_browser_action(self, key: str):
        """Data Browser request: an action key, or ``edit_zone:<ZONE>``."""
        if key.startswith("edit_zone:"):
            self._edit_zone(key.split(":", 1)[1])
        elif key in self.actions_:
            self.actions_[key].trigger()

    def _edit_zone(self, zone: str):
        """Open the Parameters window on the active well's ``zone`` (Zones page)."""
        if self.model.active_well is None:
            return
        self.model.set_edit_scope("well", zone)
        self.params_window.open_page("zones")

    def _on_data_loaded(self):
        """Refresh every tab after data replacement invalidates derived state."""
        self._update_all_tabs()

    def _on_results_updated(self):
        """Handle results updated signal."""
        self._update_all_tabs()

    def _update_all_tabs(self):
        """Update the tabs with current results (hidden plot tabs lazily)."""
        self.data_browser.rebuild()
        self._dirty_tabs.update(self._lazy_tabs)
        self._refresh_current_tab()
        self.summary_tab.update_display()
        self.export_tab.update_display()

    def _refresh_current_tab(self, *_):
        """Redraw the current tab if results changed while it was hidden."""
        tab = self.tab_widget.currentWidget()
        if tab in self._dirty_tabs:
            self._dirty_tabs.discard(tab)
            tab.update_display()

    # =========================================================================
    # PARAMETER CALCULATIONS
    # =========================================================================

    def _on_calculate_rw_rsh(self):
        """Calculate Rw and Rsh from data."""
        if self.model.las_data is None:
            QMessageBox.warning(self, "Warning", "No data loaded")
            return

        self._sync_model_from_ui()
        # At the well · zone scope only that zone's samples are used.
        zone = self.model.edit_zone if self.model.edit_scope == "well" else None
        result = self.analysis_service.calculate_rw_rsh(self.model, zone=zone)

        if result:
            self.params_window.show_calculated_rw_rsh(result["rw"], result["rsh"])
        else:
            QMessageBox.warning(self, "Warning", "Could not calculate Rw/Rsh from data")

    def _on_calculate_shale(self):
        """Calculate shale parameters from data."""
        if self.model.las_data is None:
            QMessageBox.warning(self, "Warning", "No data loaded")
            return

        self._sync_model_from_ui()
        # At the well · zone scope only that zone's samples are used.
        zone = self.model.edit_zone if self.model.edit_scope == "well" else None
        result = self.analysis_service.calculate_shale_parameters(self.model, zone=zone)

        if result:
            self.model.calculated_shale = result
            self.params_window.show_calculated_shale(result)
        else:
            QMessageBox.warning(
                self, "Warning", "Could not calculate shale parameters from data"
            )

    def _on_apply_shale(self):
        """Apply calculated shale parameters."""
        if self.model.calculated_shale:
            self.params_window.shale_params_widget.set_params(
                self.model.calculated_shale["rho_shale"],
                self.model.calculated_shale["dt_shale"],
                self.model.calculated_shale["nphi_shale"],
            )
            self.model.shale_method_used = "statistical"
            # Keep calculated_shale for Diagnostics Tab reference
            # (previously was set to None, causing Statistical Values to not display)

    def _on_calculate_perm(self):
        """Wyllie-Rose coefficients for the edited scope: core fit, else porosity bands.

        At the well · zone scope only that zone's core samples and results are
        used, and a zone with too few core pairs gives no result (never a
        silently widened fit). Buckles k comes from the edited scope.
        """
        from modules.param_scopes import normalize_zone
        from modules.perm_calibration import (
            MIN_CORE_PAIRS, calibrate_from_core, estimate_from_porosity,
            pair_core_samples, zone_mask,
        )

        if not self.model.calculated or self.model.results is None:
            QMessageBox.warning(self, "Warning", "Please run analysis first")
            return
        results = self.model.results
        if "PHIE" not in results.columns:
            QMessageBox.warning(
                self, "Warning", "PHIE not calculated. Run analysis first."
            )
            return

        ds = self.model.active_well
        zone = self.model.edit_zone if self.model.edit_scope == "well" else None
        well_name = (ds.display_name or ds.key) if ds is not None else "the well"
        flat, _info = self.model.scope_view()
        k_buckles = float(flat.get("k_buckles", self.model.k_buckles))
        widget = self.params_window.perm_params_widget
        stale = " Results are out of date; run the analysis first." if ds is not None and ds.stale else ""
        tops = ds.formation_tops if ds is not None else None

        core = self.model.core_data
        if core is not None:
            try:
                perm_depths, perm = core.get_core_permeability()
                por_depths, por = core.get_core_porosity()
                keep = zone_mask(perm_depths, tops, zone)
                perm_depths, perm = perm_depths[keep], perm[keep]
                keep = zone_mask(por_depths, tops, zone)
                por_depths, por = por_depths[keep], por[keep]
                matched_por, matched_perm = pair_core_samples(
                    perm_depths, perm, por_depths, por
                )
                fit = calibrate_from_core(matched_por, matched_perm, k_buckles)
                if fit is not None:
                    widget.show_calculated_result(fit["C"], fit["P"], fit["Q"])
                    where = f" in {zone}" if zone else ""
                    self.statusBar.showMessage(
                        f"Core-calibrated{where} ({fit['pairs']} pairs): "
                        f"C={fit['C']:.0f}, P={fit['P']:.2f}, Q={fit['Q']:.2f}"
                    )
                    return
                if zone:
                    widget.show_message(
                        f"{len(matched_por)} core pairs in {zone} (need {MIN_CORE_PAIRS}). "
                        f"Switch the scope to Well: {well_name} to calibrate on the whole well."
                    )
                    return
            except Exception:
                logger.exception(
                    "Core permeability fit failed; using statistical estimation"
                )

        phie = results["PHIE"]
        if zone:
            labels = results["ZONE"] if "ZONE" in results.columns else None
            phie = phie[labels == normalize_zone(zone)] if labels is not None else phie.iloc[0:0]
        estimate = estimate_from_porosity(phie)
        if estimate is None:
            if zone:
                widget.show_message(f"Too few PHIE samples in {zone} to estimate.")
            else:
                QMessageBox.warning(self, "Warning", "Insufficient data for regression")
            return
        C, P, Q = estimate["C"], estimate["P"], estimate["Q"]
        widget.show_calculated_result(C, P, Q)
        where = f" in {zone}" if zone else ""
        self.statusBar.showMessage(
            f"Estimated from porosity{where} (mean={estimate['phi_mean']:.3f}): "
            f"C={C:.0f}, P={P:.2f}, Q={Q:.2f}.{stale}"
        )

    # =========================================================================
    # EXPORT
    # =========================================================================

    def _on_export_csv(self, file_path: str):
        """Handle CSV export."""
        if self.model.calculated and self.model.results is not None:
            self.export_service.export_csv(self.model.results, file_path)

    def _on_export_excel(self, file_path: str):
        """Handle Excel export."""
        if (
            self.model.calculated
            and self.model.results is not None
            and self.model.summary is not None
        ):
            self.export_service.export_excel(
                self.model.results, self.model.summary, file_path
            )

    # =========================================================================
    # SESSION SAVE/LOAD (v1.2)
    # =========================================================================

    def _on_save_session(self):
        """Handle save session button click."""
        from PyQt6.QtWidgets import QFileDialog

        # Update model from UI first
        self._sync_model_from_ui()

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Session",
            "petrophyter_session.json",
            "Session Files (*.json);;All Files (*)",
        )

        if file_path:
            if self.session_service.save_session(self.model, file_path):
                self.statusBar.showMessage(f"Session saved to {file_path}")
            else:
                QMessageBox.critical(self, "Error", "Failed to save session")

    def _on_load_session(self):
        """Handle load session button click."""
        from PyQt6.QtWidgets import QFileDialog

        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Session", "", "Session Files (*.json);;All Files (*)"
        )

        if not file_path:
            return
        session_data = self.session_service.load_session(file_path)
        if not session_data:
            QMessageBox.critical(self, "Error", "Failed to load session")
            return
        # Restoring writes the saved values where they belong; it must never
        # create entries at whatever scope the user happened to be editing.
        self.model.set_edit_scope("project")
        if is_v2_session(session_data):
            # A v2.0 session is a whole project: it replaces the loaded wells.
            self.batch_runner.cancel()
            self.model.reset()
            self.session_service.apply_session_to_model(self.model, session_data)
            notes = self.session_service.restore_wells(
                self.model, session_data,
                progress=lambda message, percent: self._set_progress(
                    min(max(percent, 1), 99), message),
            )
            self._set_progress(100)
            self._update_ui_from_model()
            self._refresh_active_well_ui()
        else:
            self.session_service.apply_session_to_model(self.model, session_data)
            notes = self.session_service.restore_wells(self.model, session_data)
            self._update_ui_from_model()
        # Results in memory (v1.x) were computed with the old parameters;
        # restored wells (v2.0) have none and need a run.
        self._recompute_stale()
        self._show_load_notes(None, notes)
        self.statusBar.showMessage(f"Session loaded from {file_path}")

    def _on_new_project(self):
        """Handle new project button click - clear all data and reset to fresh state."""
        # Confirm with user if data is loaded
        if self.model.las_data is not None or self.model.results is not None:
            reply = QMessageBox.question(
                self,
                "New Project",
                "Are you sure you want to start a new project?\n\nAll current data will be cleared.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # Removing every well also resets the UI through active_well_changed.
        self.batch_runner.cancel()
        self.model.reset()

        # Reset status bar
        self.statusBar.showMessage("Ready. Load a LAS file to begin.")

    @_restoring_guard
    def _update_ui_from_model(self):
        """Restore persisted controls independently after loading a session."""

        def restore_analysis_mode():
            per_formation = self.model.analysis_mode == "Per-Formation"
            self.params_window.analysis_mode_widget.per_formation_radio.setChecked(
                per_formation
            )
            formation_list = self.params_window.analysis_mode_widget.formation_list
            existing = {
                formation_list.item(index).text()
                for index in range(formation_list.count())
            }
            for formation in self.model.selected_formations:
                if formation not in existing:
                    formation_list.addItem(formation)
            for index in range(formation_list.count()):
                item = formation_list.item(index)
                item.setSelected(item.text() in self.model.selected_formations)

        def restore_curve_mapping():
            for curve_type, curve_name in self.model.curve_mapping.items():
                combo = self.params_window.curve_mapping_widget.curve_combos.get(curve_type)
                if combo is None:
                    continue
                if curve_name != "None" and combo.findText(curve_name) < 0:
                    combo.addItem(curve_name)
                combo.setCurrentText(curve_name)

        restored_widgets = [
            self.params_window.analysis_mode_widget,
            self.params_window.curve_mapping_widget,
            self.params_window.vsh_params_widget,
            self.params_window.porosity_method_widget,
            self.params_window.matrix_params_widget,
            self.params_window.fluid_params_widget,
            self.params_window.shale_params_widget,
            self.params_window.archie_params_widget,
            self.params_window.sw_models_widget,
            self.params_window.res_params_widget,
            self.params_window.perm_params_widget,
            self.params_window.swir_params_widget,
            self.params_window.cutoff_params_widget,
            self.params_window.gas_correction_widget,
        ]
        for widget in restored_widgets:
            widget.blockSignals(True)

        actions = [
            ("analysis mode", restore_analysis_mode),
            ("curve mapping", restore_curve_mapping),
            (
                "VShale",
                lambda: self.params_window.vsh_params_widget.set_params(
                    self.model.vsh_baseline_method,
                    self.model.gr_min_manual,
                    self.model.gr_max_manual,
                    self.model.vsh_methods,
                ),
            ),
            (
                "porosity method",
                lambda: self.params_window.porosity_method_widget.set_params(
                    {"primary_phie_method": self.model.primary_phie_method}
                ),
            ),
            (
                "matrix",
                lambda: self.params_window.matrix_params_widget.set_params(
                    self.model.rho_matrix, self.model.dt_matrix
                ),
            ),
            (
                "fluid",
                lambda: self.params_window.fluid_params_widget.set_params(
                    self.model.rho_fluid, self.model.dt_fluid
                ),
            ),
            (
                "shale",
                lambda: self.params_window.shale_params_widget.set_params(
                    self.model.rho_shale,
                    self.model.dt_shale,
                    self.model.nphi_shale,
                    approach=self.model.shale_approach,
                    selection_mode=self.model.shale_selection_mode,
                    vsh_threshold=self.model.shale_vsh_threshold,
                    vsh_quantile=self.model.shale_vsh_quantile,
                    min_points=self.model.shale_min_points,
                    sweep_tmin=self.model.shale_sweep_tmin,
                    sweep_tmax=self.model.shale_sweep_tmax,
                    sweep_step=self.model.shale_sweep_step,
                    gate_logs=self.model.shale_gate_logs,
                    iqr_filter=self.model.shale_iqr_filter,
                ),
            ),
            (
                "Archie",
                lambda: self.params_window.archie_params_widget.set_params(
                    self.model.a,
                    self.model.m,
                    self.model.n,
                    self.model.lithology_preset,
                ),
            ),
            (
                "water saturation",
                lambda: self.params_window.sw_models_widget.set_params(
                    {
                        "sw_methods": self.model.sw_methods,
                        "sw_primary_method": self.model.sw_primary_method,
                        "ws_qv": self.model.ws_qv,
                        "ws_b": self.model.ws_b,
                        "dw_swb": self.model.dw_swb,
                        "dw_rwb": self.model.dw_rwb,
                    }
                ),
            ),
            (
                "resistivity",
                lambda: self.params_window.res_params_widget.set_params(
                    self.model.rw, self.model.rsh,
                    getattr(self.model, "rw_mode", "manual"),
                    getattr(self.model, "rsh_mode", "auto"),
                ),
            ),
            (
                "permeability",
                lambda: self.params_window.perm_params_widget.set_params(
                    self.model.perm_C, self.model.perm_P, self.model.perm_Q
                ),
            ),
            (
                "Swirr",
                lambda: self.params_window.swir_params_widget.set_params(
                    self.model.swirr_method,
                    self.model.buckles_preset,
                    self.model.k_buckles,
                ),
            ),
            (
                "cutoffs",
                lambda: self.params_window.cutoff_params_widget.set_params(
                    self.model.vsh_cutoff,
                    self.model.phi_cutoff,
                    self.model.sw_cutoff,
                ),
            ),
            (
                "merge settings",
                lambda: (
                    self.merge_dialog.step_spin.setValue(self.model.merge_step),
                    self.merge_dialog.gap_spin.setValue(
                        self.model.merge_gap_limit
                    ),
                ),
            ),
            (
                "core settings",
                lambda: (
                    self.params_window.core_unit_combo.setCurrentText(
                        self.model.core_depth_unit
                    ),
                    self.params_window.core_dist_spin.setValue(self.model.core_max_dist),
                ),
            ),
            (
                "gas correction",
                lambda: self.params_window.gas_correction_widget.set_params(
                    self.model.gas_correction_enabled,
                    self.model.gas_nphi_factor,
                    self.model.gas_rhob_factor,
                ),
            ),
        ]

        try:
            for group_name, restore in actions:
                try:
                    restore()
                except Exception:
                    logger.exception(
                        "Failed to restore %s session controls", group_name
                    )
        finally:
            for widget in restored_widgets:
                widget.blockSignals(False)

        # Reconcile the model once after every supported control has restored.
        self._sync_model_from_ui()
