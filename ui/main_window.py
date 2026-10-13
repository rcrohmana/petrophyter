"""
Main Window for Petrophyter PyQt
The main application window.
"""

from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
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
from PyQt6.QtCore import Qt, QSettings, QElapsedTimer, QTimer, pyqtSignal
from datetime import datetime, timezone
import functools
import logging

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.app_model import AppModel
from services.analysis_service import AnalysisService, BatchRunner
from services.uncertainty_service import UncertaintyRunner
from services.merge_service import MergeService
from services.load_service import (
    LoadWorker,
    build_well,
    parse_file,
    sanitize_error_detail,
)
from services.export_service import ExportService
from services.issues import collect_issues, issue_counts
from services.session_service import (
    SessionService, is_v2_session, relocate_missing_sources, session_level_notes,
    validate_session,
)
from modules.fingerprint import fingerprint_file
from services.restore_service import RestoreWorker
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
from .tabs.rock_typing_tab import RockTypingTab
from .tabs.summary_tab import SummaryTab
from .tabs.uncertainty_tab import UncertaintyTab
from .tabs.export_tab import ExportTab

from modules.formation_tops import FormationTops, extend_last_bottom
from modules.core_handler import CoreDataHandler
from modules.well_import import ImportOptions, build_parts, import_record, parse_import_file, well_refs
from .widgets.well_import_dialog import MultiWellImportDialog


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
        self.uncertainty_runner = UncertaintyRunner(self)
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
        # Session restore on a worker thread (see _start_restore): the current
        # worker, its generation token and workers still winding down.
        self._restore_worker = None
        self._restore_generation = 0
        self._restore_retired = []
        self._restore_active_key = None
        self._restore_path = ""
        self._restore_pool = None
        # Batch analysis: number of wells in the current run, wells finished,
        # the stage percent of every running well and the throttled status text.
        self._batch_total = 0
        self._batch_done = 0
        self._batch_pct = {}
        self._batch_last = None  # (key, message) of the most recent stage report
        self._progress_timer = QElapsedTimer()
        # (key, data_version) the UI was last refreshed for; see _on_data_loaded.
        self._refreshed_for = None
        # Busy state: see _set_busy. Analysis runs are not a busy state; the
        # batch runner gates Run per well and New Project / Load Session cancel it.
        self._busy = None  # None, "load" or "restore"
        self._busy_status_tips = {}

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
        self.rock_tab = RockTypingTab(self.model)
        self.summary_tab = SummaryTab(self.model)
        self.uncertainty_tab = UncertaintyTab(self.model)
        self.export_tab = ExportTab(self.model)

        self.tab_widget.addTab(self.qc_tab, "Data QC")
        self.tab_widget.addTab(self.petro_tab, "Petrophysics")
        self.tab_widget.addTab(self.log_tab, "Log Display")
        self.tab_widget.addTab(self.diag_tab, "Diagnostics")
        self.tab_widget.addTab(self.rock_tab, "Rock Typing")
        self.tab_widget.addTab(self.summary_tab, "Summary")
        self.tab_widget.addTab(self.uncertainty_tab, "Uncertainty")
        self.tab_widget.addTab(self.export_tab, "Export")
        # Plot tabs redraw only while visible; the others are marked dirty
        # and catch up when they become current.
        self._lazy_tabs = (self.qc_tab, self.petro_tab, self.log_tab, self.diag_tab,
                           self.rock_tab)
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
        # True while a session is being installed: its signals are not user edits.
        self._session_swap = False

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
        self.params_window.revert_applied.connect(self._on_params_reverted)
        self.params_window.uncertainty_config_changed.connect(self._refresh_uncertainty_actions)
        self.uncertainty_runner.started.connect(self._refresh_uncertainty_actions)
        self.uncertainty_runner.finished.connect(self._refresh_uncertainty_actions)
        self.model.parameters_changed.connect(self._on_parameters_updated)
        self.model.scoped_params_changed.connect(self._on_scoped_params_changed)

        # Unsaved-changes tracking: only signals that change saved content. Not
        # well_updated (results, stale flags, errors), analysis_complete,
        # scope_changed or active_well_changed.
        self.model.dirty_changed.connect(lambda _dirty: self._refresh_window_title())
        for signal in (
            self.model.data_loaded,
            self.model.merge_complete,
            self.model.core_data_loaded,
            self.model.formation_tops_loaded,
            self.model.project.wells_changed,
            self.model.project.tops_changed,
        ):
            signal.connect(self._on_content_changed)
        for signal in (self.model.parameters_changed, self.model.scoped_params_changed):
            signal.connect(self._on_parameter_edited)
        self.model.formation_tops_loaded.connect(self._on_tops_or_core_changed)
        self.model.core_data_loaded.connect(self._on_tops_or_core_changed)
        self.export_tab.export_succeeded.connect(
            lambda path: self.show_banner("success", f"Exported to {path}")
        )
        self.summary_tab.well_activated.connect(self._on_well_selected)
        # Rock typing switch / applied definitions: only the Summary's Rock types group follows.
        self.model.parameters_changed.connect(self.summary_tab.refresh_rock_types)
        self.rock_tab.run_all_requested.connect(self._on_run_all)

        # Batch analysis signals
        self.batch_runner.started.connect(self._on_batch_started)
        self.batch_runner.progress.connect(self._on_batch_progress)
        self.batch_runner.well_progress.connect(self._on_well_progress)
        self.batch_runner.well_completed.connect(self._on_well_completed)
        self.batch_runner.well_failed.connect(self._on_well_failed)
        self.batch_runner.finished.connect(self._on_batch_finished)

        # Monte Carlo lifecycle (the tab and menu action come later)
        self.uncertainty_runner.progress.connect(self._on_uncertainty_progress)
        self.uncertainty_runner.completed.connect(self._on_uncertainty_completed)
        self.uncertainty_runner.failed.connect(self._on_uncertainty_failed)
        self.uncertainty_runner.finished.connect(self._on_uncertainty_finished)
        # The Uncertainty tab draws lazily (when visible); stale checks are cheap hash compares.
        tab = self.uncertainty_tab
        self.uncertainty_result_changed.connect(tab.update_display)
        self.uncertainty_runner.started.connect(lambda *_: tab.set_running(True))
        self.uncertainty_runner.finished.connect(lambda *_: tab.set_running(False))
        self.uncertainty_runner.progress.connect(tab.set_progress)
        tab.run_requested.connect(lambda: self.run_uncertainty())
        tab.cancel_requested.connect(lambda: self.cancel_uncertainty())
        for signal in (self.model.parameters_changed, self.model.scoped_params_changed,
                       self.params_window.uncertainty_config_changed):
            signal.connect(lambda *_: tab.refresh_stale())
        # Adding or removing a well can drop the result (Project clears it); update_display
        # notices that and is otherwise a no-op.
        self.model.project.wells_changed.connect(lambda *_: tab.update_display())
        self.diag_tab.goto_requested.connect(self._on_goto_target)

        # Merge service signals
        self.merge_service.started.connect(self._on_merge_started)
        self.merge_service.progress.connect(self._on_merge_progress)
        self.merge_service.completed.connect(self._on_merge_completed)
        self.merge_service.error.connect(self._on_merge_error)

        # Export signals
        self.export_tab.export_csv.connect(self._on_export_csv)
        self.export_tab.export_excel.connect(self._on_export_excel)
        self.export_tab.run_wells_requested.connect(self._on_export_run_wells)
        self.batch_runner.finished.connect(self._return_to_export_tab)
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
        # The Rock Typing tab also follows the core and the wells; a new active well reaches it
        # through _on_active_well_changed (well part only).
        # Bursts (core for N wells, several wells_changed) coalesce into one refresh.
        self._rock_timer = QTimer(self)
        self._rock_timer.setSingleShot(True)
        self._rock_timer.setInterval(0)
        self._rock_timer.timeout.connect(self._refresh_current_tab)
        for signal in (self.model.core_data_loaded, self.model.project.wells_changed):
            signal.connect(self._mark_rock_tab_dirty)

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
            self, "Open Formation Tops", "", "Tables (*.txt *.csv *.tsv *.xlsx);;All Files (*)"
        )
        if file:
            self._on_tops_file_selected(file)

    def _open_core_dialog(self):
        """Open core data file dialog."""
        from PyQt6.QtWidgets import QFileDialog

        file, _ = QFileDialog.getOpenFileName(
            self, "Open Core Data", "", "Tables (*.txt *.csv *.tsv *.xlsx);;All Files (*)"
        )
        if file:
            self._on_core_file_selected(file)

    def closeEvent(self, event):
        if not self._confirm_discard("close"):
            event.ignore()
            return
        busy = self._busy or (
            "analysis" if self.batch_runner.is_running()
            else "uncertainty" if self.uncertainty_runner.is_running() else None
        )
        if busy:
            if not self._confirm_quit(busy):
                event.ignore()
                return
            # Don't wait for the workers: late results are dropped and queued
            # runnables are discarded.
            self.batch_runner.cancel()
            self.uncertainty_runner.cancel()
            self.merge_service.thread_pool.clear()
            if hasattr(self, "_load_pool"):
                self._load_pool.clear()
        self._cancel_restore()
        settings = QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope, "Petrophyter Team", "Petrophyter")
        settings.setValue("ui/geometry", self.saveGeometry())
        settings.setValue("ui/windowState", self.saveState())
        settings.setValue("ui/splitterSizes", self.main_splitter.saveState())
        settings.setValue(
            "ui/dataBrowserVisible", self.actions_["toggle_browser"].isChecked()
        )
        settings.remove("ui/activeTab")  # the app always opens on Data QC
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
        self.tab_widget.setCurrentWidget(self.qc_tab)

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
        title = f"{name} — Petrophyter" if name else "Petrophyter"
        self.setWindowTitle(f"*{title}" if self.model.dirty else title)

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
        act("open_tops_multi", "Open Formation Tops (Multi-Well)…", "layers", None,
            self._open_tops_multi_dialog)
        act("open_core_multi", "Open Core Data (Multi-Well)…", "database", None,
            self._open_core_multi_dialog)
        act("merge_las", "Merge LAS Files…", "merge", None, self._open_las_dialog)
        act("save_merged", "Save Merged LAS…", "download", None, self._on_download_merged)
        act("exit", "Exit", "log-out", None, self.close)
        act("save_session", "Save Session…", "save", "Ctrl+S", self._on_save_session)
        act("save_session_as", "Save Session As…", "save", "Ctrl+Shift+S", self._on_save_session_as)
        act("load_session", "Load Session…", "folder-input", "Ctrl+Shift+O", self._on_load_session)
        act("run_analysis", "Run Analysis", "play", "F5", self._on_run_analysis)
        act("run_all", "Run All Wells", "layers", "Ctrl+Shift+R", self._on_run_all)
        act("run_uncertainty", "Run Uncertainty…", "sigma", None, self.run_uncertainty)
        act("stop_uncertainty", "Stop Monte Carlo", "circle-stop", None, self.cancel_uncertainty)
        # Esc is bound to the action, which is enabled only while a run is active.
        act("stop_analysis", "Stop analysis", "circle-stop", "Esc", self._on_stop_analysis)
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
        self.actions_["open_tops_multi"].setEnabled(False)
        self.actions_["open_core_multi"].setEnabled(False)
        group = QActionGroup(self)
        group.addAction(self.actions_["theme_light"])
        group.addAction(self.actions_["theme_dark"])
        self.actions_["run_analysis"].setEnabled(False)
        self.actions_["run_all"].setEnabled(False)
        self.actions_["stop_analysis"].setEnabled(False)
        self.actions_["run_uncertainty"].setEnabled(False)
        self.actions_["stop_uncertainty"].setEnabled(False)
        self.actions_["save_merged"].setEnabled(False)
        self.actions_["toggle_browser"].setChecked(True)

    def _build_menus(self):
        from themes.icon_loader import get_icon

        bar = self.menuBar()
        self._menus = {}
        file_menu = bar.addMenu("&File")
        self._menus["file"] = file_menu
        for key in ("new_project", None, "open_las", "open_tops", "open_core",
                    "open_tops_multi", "open_core_multi", "merge_las", None, "save_merged", None, "exit"):
            file_menu.addSeparator() if key is None else file_menu.addAction(self.actions_[key])
        session = bar.addMenu("&Session")
        session.addAction(self.actions_["save_session"])
        session.addAction(self.actions_["save_session_as"])
        session.addAction(self.actions_["load_session"])
        analysis = bar.addMenu("&Analysis")
        analysis.addAction(self.actions_["run_analysis"])
        analysis.addAction(self.actions_["run_all"])
        analysis.addAction(self.actions_["run_uncertainty"])
        analysis.addAction(self.actions_["stop_uncertainty"])
        analysis.addAction(self.actions_["stop_analysis"])
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
        self.stop_button = QToolButton()
        self.stop_button.setDefaultAction(self.actions_["stop_analysis"])
        self.stop_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.stop_button.setProperty("variant", "ghost")
        toolbar.addWidget(self.stop_button)
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

    def show_banner(self, kind: str, message: str, action_text: str = None, on_action=None):
        self.banner.show_message(kind, message, action_text, on_action)

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
        self.uncertainty_tab.refresh_stale()

    def _on_content_changed(self, *_):
        """Wells, tops, core or merge data changed (not while a session is being installed)."""
        if not self._session_swap:
            self.model.mark_dirty()

    def _on_parameter_edited(self, *_):
        """A parameter changed; programmatic widget refreshes and session installs do not count."""
        if not self._restoring and not self._session_swap:
            self.model.mark_dirty()

    def _on_parameters_updated(self, *_):
        """A project-level or active-well parameter changed (programmatic restores are ignored)."""
        if not self._restoring:
            self._recompute_stale()

    def _on_scoped_params_changed(self, key: str):
        if not self._restoring:
            self._recompute_stale([key] if key else None)

    def _on_params_reverted(self, key: str):
        """Revert to last run restored parameters: reload the well's controls (U12)."""
        if key == self.model.project.active_key:
            self._refresh_active_well_ui()
        # Project values are shared, so any well's stale state may have changed.
        self._recompute_stale()

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
            pw = getattr(self, "params_window", None)
            lines = pw.change_lines() if pw is not None else []
            self.stale_label.setToolTip(
                "Changes since the last run:\n" + "\n".join(lines) if lines else "")
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

    @staticmethod
    def _parser_diagnostics(parser) -> list:
        """Notes a tops / core parser collected: rows left out, TVD and porosity warnings."""
        lines = list(getattr(parser, "notes", None) or [])
        excluded = list(getattr(parser, "excluded_rows", None) or [])
        if excluded:
            first = ", ".join(str(line) for line, _ in excluded[:3] if line is not None)
            lines.append(
                f"{len(excluded)} row(s) excluded (line {first}"
                f"{'...' if len(excluded) > 3 else ''}): {excluded[0][1]}"
            )
        for name in ("tvd_warning", "porosity_warning"):
            text = getattr(parser, name, None)
            if text:
                lines.append(text)
        return lines

    def _show_load_notes(self, parser=None, extra=()):
        """One banner for load-time notes so none hides another."""
        lines = list(extra)
        if parser is not None:
            if getattr(parser, "depth_unit_warning", None):
                lines.append(parser.depth_unit_warning)
            lines.extend(getattr(parser, "unit_warnings", None) or [])
            lines.extend(self._parser_diagnostics(parser))
        lines.extend(self._depth_overlap_warnings())
        if lines:
            only_info = all(l.startswith("Reloaded ") for l in lines)
            self.show_banner("info" if only_info else "warning", "\n".join(lines))

    def _sync_model_from_ui(self):
        self.params_window.update_model_from_ui()
        self.merge_dialog.update_model(self.model)

    def _refresh_core_actions(self):
        self.actions_["page_core"].setEnabled(self.params_window.core_unit_combo.isEnabled())

    # Actions that could replace the data under a running worker, per busy kind.
    _LOAD_ACTIONS = (
        "open_las", "open_tops", "open_core", "open_tops_multi", "open_core_multi",
        "merge_las", "run_analysis", "run_all",
    )
    _BUSY_ACTIONS = {
        "load": ("new_project", "load_session") + _LOAD_ACTIONS,
        # New Project and Load Session stay available: they cancel the restore.
        # Save Session would save a half-restored project.
        "restore": _LOAD_ACTIONS + ("save_session", "save_session_as"),
    }
    _BUSY_TIPS = {
        "load": "Unavailable while files are loading",
        "restore": "Unavailable while a session is loading",
    }
    _QUIT_QUESTIONS = {
        "analysis": "Analysis is still running. Quit anyway?",
        "uncertainty": "Monte Carlo is still running. Quit anyway?",
        "load": "Files are still loading. Quit anyway?",
        "restore": "A session is still loading. Quit anyway?",
    }

    def _set_busy(self, kind):
        """The only place that disables actions for a running load or restore.

        ``kind`` is "load", "restore" or None (idle: normal gating applies).
        """
        if self._busy:
            for key, tip in self._busy_status_tips.items():
                self.actions_[key].setStatusTip(tip)
            self._busy_status_tips = {}
        self._busy = kind or None
        if kind:
            keys = self._BUSY_ACTIONS[kind]
            self._busy_status_tips = {key: self.actions_[key].statusTip() for key in keys}
            for key in keys:
                self.actions_[key].setEnabled(False)
                self.actions_[key].setStatusTip(self._BUSY_TIPS[kind])
        self._refresh_action_states()

    def _refresh_action_states(self):
        """Normal gating of the data and run actions; busy actions stay disabled."""
        busy = set(self._BUSY_ACTIONS.get(self._busy, ()))
        for key in ("new_project", "open_las", "open_tops", "open_core",
                    "load_session", "save_session", "save_session_as", "merge_las"):
            if key not in busy:
                self.actions_[key].setEnabled(True)
        self._refresh_import_actions()
        self._refresh_run_action()

    def _confirm_quit(self, kind: str) -> bool:
        reply = QMessageBox.question(
            self,
            "Quit Petrophyter",
            self._QUIT_QUESTIONS[kind],
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

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
            getattr(self, "rock_tab", None),
            getattr(self, "summary_tab", None),
            getattr(self, "uncertainty_tab", None),
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
        self._set_busy("load")
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

    def _abort_load(self):
        self._bulk_loading = False
        self._load_queue = []
        self._load_current = None
        self._load_worker = None
        self._set_busy(None)
        self._set_progress(0, "")

    def _begin_load(self, groups, step=None, gap=None, multi_file=False, notes=()):
        """Build one well per group (merging multi-file groups), then activate the last."""
        self._bulk_loading = True
        self._set_busy("load")
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
        self._set_busy(None)
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
        self._refresh_import_actions()
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
        # The Data Browser listens to the same signal (connected earlier) and
        # has already rebuilt itself for this change.
        self._refresh_active_well_ui(browser_fresh=True, rock_well_only=True)

    def _refresh_uncertainty_page(self):
        """The project's Monte Carlo setup was replaced (session load, New Project)."""
        self.params_window.refresh_uncertainty()
        self._refresh_uncertainty_actions()

    def _refresh_uncertainty_actions(self, *_args):
        """Run Uncertainty needs an enabled distribution, no MC run and no batch; Stop needs a run."""
        mc_running = self.uncertainty_runner.is_running()
        if not self.model.project.uncertainty.enabled_names():
            tip = "Enable a distribution on Parameters → Uncertainty"
        elif mc_running:
            tip = "Monte Carlo is running"
        elif self.batch_runner.is_running():
            tip = "Wait for the analysis to finish"
        else:
            tip = ""
        run = self.actions_["run_uncertainty"]
        run.setEnabled(not tip)
        run.setToolTip(tip or "Run the Monte Carlo uncertainty analysis")
        self.actions_["stop_uncertainty"].setEnabled(mc_running)

    def _refresh_run_action(self):
        """Run is disabled only while the ACTIVE well is running; other wells may run."""
        self.actions_["stop_analysis"].setEnabled(self.batch_runner.is_running())
        self._refresh_uncertainty_actions()
        self.rock_tab.set_batch_running(self.batch_runner.is_running())
        if self._busy:
            return  # _set_busy(None) refreshes
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
    def _refresh_active_well_ui(self, browser_fresh: bool = False, rock_well_only: bool = False):
        """Point every control and tab at the active well.

        ``rock_well_only``: only the active well changed, so the Rock Typing tab refreshes its
        well part (pay table, log overlay) instead of everything.
        """
        ds = self.model.active_well
        if ds is None:
            self._refreshed_for = None
            self._reset_ui()
            return
        self._refreshed_for = (ds.key, ds.data_version)
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
        self._update_all_tabs(rebuild_browser=not browser_fresh, rock_well_only=rock_well_only)

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
        self.rock_tab.reset_ui()
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

    def _on_tops_file_selected(self, file_path: str):
        """Handle formation tops file selection.

        Tops belong to the active well, unless the file has a well column: then
        the multi-well dialog decides which loaded well gets which rows.
        """
        if not self._require_active_well("formation tops"):
            return
        try:
            tops = FormationTops()
            with open(file_path, "rb") as f:
                if tops.read_tops_from_buffer(f):
                    if tops.well_column:
                        self._import_multi_well("tops", file_path)
                        return
                    # convert_to_feet() only converts when the unit was detected
                    # as meters; feet/undetected files are left unchanged.
                    tops.convert_to_feet()
                    bounds = self._log_depth_range()
                    if bounds is not None:
                        extend_last_bottom(tops, bounds[1])
                    active = self.model.active_well
                    active.tops_path = file_path
                    active.tops_import = None
                    active.tops_sha256 = fingerprint_file(file_path)[0]
                    self.model.formation_tops = tops

                    self.params_window.update_formations_list(tops.get_formation_list())

                    self.statusBar.showMessage(
                        f"Loaded {len(tops.formations)} formations"
                    )

                    self._show_load_notes(tops)

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

        Core belongs to the active well, unless the file has a well column: then
        the multi-well dialog decides which loaded well gets which samples.
        """
        if not self._require_active_well("core data"):
            return
        try:
            self._sync_model_from_ui()

            handler = CoreDataHandler()
            depth_unit = self.model.core_depth_unit
            with open(file_path, "rb") as f:
                if handler.read_core_from_buffer(f, depth_unit=depth_unit):
                    if handler.well_col:
                        self._import_multi_well("core", file_path)
                        return
                    active = self.model.active_well
                    active.core_path = file_path
                    active.core_depth_unit = depth_unit
                    active.core_import = None
                    active.core_sha256 = fingerprint_file(file_path)[0]
                    self.model.core_data = handler
                    self.params_window.set_core_available(True)
                    self._refresh_core_actions()

                    summary = handler.get_summary()

                    self.statusBar.showMessage(
                        f"Loaded {summary['n_samples']} core samples"
                    )

                    self._show_load_notes(handler)
                else:
                    QMessageBox.warning(
                        self, "Warning", "Failed to parse core data file"
                    )

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load core data:\n{str(e)}")

    # ---- multi-well import (one file, many wells) ----

    def _open_tops_multi_dialog(self):
        """Pick a tops file holding the tops of several wells."""
        self._open_multi_dialog("tops", "Open Formation Tops (Multi-Well)")

    def _open_core_multi_dialog(self):
        """Pick a core file holding the samples of several wells."""
        self._open_multi_dialog("core", "Open Core Data (Multi-Well)")

    def _open_multi_dialog(self, kind: str, title: str):
        from PyQt6.QtWidgets import QFileDialog

        file, _ = QFileDialog.getOpenFileName(
            self, title, "", "Tables (*.txt *.csv *.tsv *.xlsx);;All Files (*)"
        )
        if file:
            self._import_multi_well(kind, file)

    def _refresh_import_actions(self, *_):
        if self._busy:
            return  # _set_busy(None) refreshes
        enabled = len(self.model.project) > 0
        for key in ("open_tops_multi", "open_core_multi"):
            self.actions_[key].setEnabled(enabled)

    def _import_multi_well(self, kind: str, file_path: str):
        """Show the import dialog for a tops / core file with a well column; apply on OK."""
        what = "Formation tops" if kind == "tops" else "Core data"
        if len(self.model.project) == 0:
            self.show_banner("warning", f"Load a LAS file first. {what} are assigned to loaded wells.")
            return
        try:
            if kind == "core":
                self._sync_model_from_ui()
            options = ImportOptions(kind=kind)
            parsed = parse_import_file(file_path, options)
            if (kind == "core" and not parsed.depth_unit_detected
                    and self.model.core_depth_unit in ("M", "FT")):
                options.depth_unit = self.model.core_depth_unit   # the Core Matching setting
            dialog = MultiWellImportDialog(
                kind, file_path, well_refs(self.model.project, kind),
                parsed=parsed, options=options, parent=self,
            )
        except ValueError as exc:
            name = os.path.basename(file_path)
            if str(exc) == "no well column":
                self.show_banner(
                    "warning",
                    f"{name} has no well column. Use Open {what}… to attach it to the active well.",
                )
            else:
                logger.error("Failed to read %s: %s", file_path, exc)
                QMessageBox.warning(
                    self, "Warning", _failure_message(f"Failed to parse {what.lower()} file", exc)
                )
            return
        except Exception as exc:
            logger.exception("Unexpected failure reading %s", file_path)
            QMessageBox.critical(
                self, "Error", _failure_message(f"Failed to load {what.lower()}", exc)
            )
            return
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._apply_import_plan(dialog.plan)

    @_restoring_guard
    def _apply_import_plan(self, plan) -> None:
        """Write a confirmed import plan to the project (GUI thread, all or nothing).

        Every part is built first (``build_parts``, in feet); if that fails one banner
        reports it and nothing changes. Then, for each Assign / Replace row, the well's
        tops or core, file path and import record are set; the active well goes through
        the model setters so ``formation_tops_loaded`` / ``core_data_loaded`` fire.

        ``ds.core_depth_unit`` is the plan's effective unit ("M" or "FT"), not "FT": the
        stored core is already in feet, but a session written by 2.0-style code (or the
        fallback when the import record no longer matches) re-reads the file with this
        value, and "FT" on a metres file would skip the conversion.
        """
        project = self.model.project
        try:
            parts = build_parts(plan, plan.wells)
        except ValueError as exc:
            self.show_banner("warning", f"Nothing was changed: {exc}")
            return
        kind = plan.kind
        active_key = project.active_key
        changed, details = [], []
        for row in plan.rows:
            key = row.target_key
            if row.action not in ("assign", "replace") or key not in parts:
                continue
            ds = project.get(key)
            part, record = parts[key], import_record(plan, row)
            if kind == "tops":
                ds.tops_path, ds.tops_import = plan.path, record
                ds.tops_sha256 = fingerprint_file(plan.path)[0]
                if key == active_key:
                    self.model.formation_tops = part
                else:
                    ds.formation_tops = part
                details.extend(self._tops_scope_notes(ds, part, row))
            else:
                ds.core_path, ds.core_import = plan.path, record
                ds.core_sha256 = fingerprint_file(plan.path)[0]
                ds.core_depth_unit = plan.effective_unit
                if key == active_key:
                    self.model.core_data = part
                else:
                    ds.core_data = part
            changed.append(key)
            if row.coverage_note:
                details.append(row.coverage_note)
            details.extend(f"{ds.display_name}: {n}" for n in row.notes)
        for key in changed:
            project.well_updated.emit(key)
        if changed:
            # Core for a non-active well emits only well_updated.
            self.model.mark_dirty()
        if kind == "tops":
            project.tops_changed.emit(list(changed))
        self._recompute_stale(changed)
        if active_key in changed:
            self._refresh_active_well_ui()
        else:
            self._refresh_core_actions()

        kept = sum(1 for r in plan.rows if r.action == "keep" and r.target_key)
        skipped = len(plan.rows) - len(changed) - kept
        head = f"{'Formation tops' if kind == 'tops' else 'Core data'} assigned to " \
               f"{len(changed)} well{'' if len(changed) == 1 else 's'}"
        extra = ([f"{kept} kept existing"] if kept else []) + \
                ([f"{skipped} skipped"] if skipped else [])
        head += f" ({', '.join(extra)})." if extra else "."
        if plan.no_well_rows:
            n = len(plan.no_well_rows)
            head += f" {n} row{'' if n == 1 else 's'} without a well " \
                    f"{'was' if n == 1 else 'were'} excluded."
        details.extend(n for n in plan.notes if "without a well" not in n)
        self.statusBar.showMessage(head)
        self.show_banner("warning" if details else "success", "\n".join([head] + details))

    @staticmethod
    def _tops_scope_notes(ds, part, row) -> list:
        """Drop analysis-scope formations the new tops lack; note orphaned zone parameters."""
        from modules.param_scopes import normalize_zone

        notes = []
        known = {normalize_zone(name) for name in part.get_formation_list()}
        gone = [z for z in ds.selected_formations if normalize_zone(z) not in known]
        if gone:
            ds.selected_formations = [z for z in ds.selected_formations if z not in gone]
            notes.append(f"{ds.display_name}: {', '.join(gone)} removed from the analysis scope.")
        for text in row.zone_impact:
            if text.startswith("zone parameters for"):
                notes.append(f"{ds.display_name}: "
                             + text.replace("will no longer apply", "match no zone now (kept)") + ".")
        return notes

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
        if self._busy:
            return
        # Update the model from the UI and disable Run before the background
        # workers can report back.
        self._sync_model_from_ui()
        if self.model.project.active_key in keys:
            self.actions_["run_analysis"].setEnabled(False)
        self.batch_runner.run(
            self.model, keys, force=force, extend=self.batch_runner.is_running()
        )
        self._refresh_run_action()

    # Set by Stop analysis so its cancelled report gets the "stopped" banner; a
    # cancel from New Project, Load Session, Close or a new run stays quiet.
    _stop_requested = False

    def _on_stop_analysis(self):
        """Stop the running analysis; wells that finished keep their results."""
        if not self.batch_runner.is_running():
            return
        self._stop_requested = True
        self.batch_runner.cancel()
        self._stop_requested = False

    # ---- Monte Carlo lifecycle ----
    # Emitted when the project's uncertainty_result is replaced or cleared (the future tab listens).
    uncertainty_result_changed = pyqtSignal()

    def run_uncertainty(self):
        """Start a Monte Carlo run; a refusal is shown as a warning banner."""
        if self.batch_runner.is_running():
            self.show_banner("warning", "Wait for the analysis to finish before running Monte Carlo.")
            return
        self._sync_model_from_ui()
        error = self.uncertainty_runner.start(self.model)
        if error:
            self.show_banner("warning", error)
            return
        self.banner.clear()
        self._set_progress(1, "Monte Carlo starting...")

    def cancel_uncertainty(self):
        self.uncertainty_runner.cancel()

    def _discard_uncertainty(self):
        """New Project / session swap: stop a run and drop its result."""
        self.uncertainty_runner.cancel()
        self.model.project.uncertainty_result = None
        self._set_progress(0, "")
        self.uncertainty_result_changed.emit()

    def _on_uncertainty_progress(self, done: int, total: int):
        pct = int(100 * done / total) if total else 0
        self._set_progress(max(1, min(99, pct)), f"Monte Carlo {done}/{total}")

    def _on_uncertainty_completed(self, result):
        self.model.project.uncertainty_result = result
        self.uncertainty_result_changed.emit()

    def _on_uncertainty_failed(self, message: str):
        # The banner has no "error" kind (errors are modal in this app).
        QMessageBox.critical(self, "Monte Carlo failed", message)

    def _on_uncertainty_finished(self):
        self._set_progress(0, "")

    # Status-bar updates from running wells are limited to this many per second.
    _PROGRESS_MAX_HZ = 10

    def _on_batch_started(self, total: int):
        self._batch_total = total
        self._batch_done = 0
        self._batch_pct = {}
        self._batch_last = None
        self._progress_timer.invalidate()
        self.banner.clear()
        self._set_progress(1, "Analyzing..." if total == 1 else f"Running 0/{total} wells…")
        self._refresh_run_action()

    def _on_batch_progress(self, done: int, total: int):
        self._batch_total = total
        self._batch_done = done
        # Finished wells count as done; only wells still running add their stage.
        runner = self.batch_runner
        self._batch_pct = {k: v for k, v in self._batch_pct.items() if runner.is_pending(k)}
        self._show_batch_progress(force=True)
        self._refresh_run_action()

    def _on_well_progress(self, key: str, message: str, percent: int):
        """One stage report from a running well (key, stage text, 0-100)."""
        self._batch_pct[key] = max(0, min(100, int(percent)))
        self._batch_last = (key, message)
        self._show_batch_progress(force=percent >= 100)

    def _show_batch_progress(self, force: bool = False):
        timer = self._progress_timer
        if not force and timer.isValid() and timer.elapsed() < 1000 // self._PROGRESS_MAX_HZ:
            return
        timer.restart()
        total = max(self._batch_total, 1)
        done = self._batch_done
        last = self._batch_last
        project = self.model.project
        if total == 1:
            percent = next(iter(self._batch_pct.values()), 0)
            message = last[1] if last else "Analyzing..."
        else:
            percent = (100 * done + sum(self._batch_pct.values())) / total
            if last:
                ds = project.get(last[0])
                name = ds.display_name if ds is not None and ds.display_name else last[0]
                message = (
                    f"Analysing {min(done + 1, total)} of {total} wells · "
                    f"{name}: {last[1]}"
                )
            else:
                message = f"Running {done}/{total} wells…"
        # 100 only once the whole batch has finished (_on_batch_finished clears it).
        self._set_progress(max(1, min(99, int(percent))), message)

    def _on_well_completed(self, key: str, results, summary, params_hash: str):
        """Store results in the well named by ``key`` (dropped if it is gone)."""
        project = self.model.project
        ds = project.get(key)
        if ds is None:
            return
        ds.error = None
        ds.run_params_hash = params_hash
        ds.run_time = datetime.now(timezone.utc).isoformat(timespec="seconds")
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
            if not self._stop_requested:
                self.statusBar.showMessage("Analysis cancelled")
                return
            finished = len(ok) + len(failed)
            not_run = max(0, self._batch_total - finished)
            noun = "well" if finished == 1 else "wells"
            self.statusBar.showMessage("Analysis stopped")
            self.show_banner(
                "info",
                f"Analysis stopped — {finished} {noun} finished, {not_run} not run",
            )
            return

        def name(key):
            ds = project.get(key)
            return ds.display_name if ds is not None and ds.display_name else key

        # Warnings and errors only (infos stay in Diagnostics); ok wells are listed first.
        warned = {}
        for key in ok:
            ds = project.get(key)
            counts = issue_counts(collect_issues(ds)) if ds is not None else {}
            n = counts.get("warning", 0) + counts.get("error", 0)
            if n:
                warned[key] = n

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
            review = next(iter(warned), None) or next(iter(failed))
            self.show_banner(
                "warning", f"{len(failed)} {noun} failed: {parts}",
                "Review", lambda k=review: self._review_issues(k),
            )
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
            n = warned.get(ok[0], 0)
            with_warnings = f" with {n} warning" + ("" if n == 1 else "s") if n else ""
            if ok[0] == project.active_key:
                head = f"Analysis complete{with_warnings}"
                self.statusBar.showMessage(head)
            else:
                head = f"Analysis complete for {name(ok[0])}{with_warnings}"
                self.statusBar.showMessage(head)
            if n:
                self.show_banner("warning", f"{head} — {message}",
                                 "Review", lambda k=ok[0]: self._review_issues(k))
            else:
                self.show_banner("success", f"{head} — {message}")
            return
        text = f"Analysis complete for {len(ok)} wells"
        if skipped:
            text += f" ({len(skipped)} unchanged)"
        self.statusBar.showMessage(text)
        if warned:
            text += f" · {len(warned)} with warnings"
            self.show_banner("warning", text, "Review",
                             lambda k=next(iter(warned)): self._review_issues(k))
        else:
            self.show_banner("success", text)

    def _review_issues(self, key: str):
        """Banner "Review": the Diagnostics tab on ``key``, at its Run issues."""
        if key not in self.model.project:
            return
        self.model.set_active_well(key)
        self.tab_widget.setCurrentWidget(self.diag_tab)
        self.diag_tab.show_run_issues()

    def _on_goto_target(self, target: str):
        """Run issues "Go to": open the Parameters page that holds the setting.

        ``target`` is ``section[.group[.field]]``; the section picks the page and a
        third part, when the window can focus fields, the field.
        """
        parts = (target or "").split(".")
        if parts[0] == "params" and len(parts) > 1:
            section = parts[1]
            field = parts[2] if len(parts) > 2 else None
        else:
            section, field = parts[0], None
        page = {"rw": "sat", "sat": "sat", "porosity": "porosity", "swirr": "perm", "tops": "scope"}.get(section)
        if page:
            self.params_window.open_page(page)
            focus = getattr(self.params_window, "focus_field", None)
            if field and focus is not None:
                focus(field)

    def _on_browser_action(self, key: str):
        """Data Browser request: an action key, or ``edit_zone:<ZONE>``."""
        if key.startswith("edit_zone:"):
            self._edit_zone(key.split(":", 1)[1])
        elif key in self.actions_ and self.actions_[key].isEnabled():
            # QAction.trigger() ignores isEnabled(), so honour the busy state here.
            self.actions_[key].trigger()

    def _edit_zone(self, zone: str):
        """Open the Parameters window on the active well's ``zone`` (Zones page)."""
        if self.model.active_well is None:
            return
        self.model.set_edit_scope("well", zone)
        self.params_window.open_page("zones")

    def _on_data_loaded(self):
        """Refresh every tab after data replacement invalidates derived state.

        Skipped during a bulk load (``_finish_load`` refreshes once) and when
        the active well was already refreshed for this very data.
        """
        if self._bulk_loading:
            return
        ds = self.model.active_well
        if ds is not None:
            if self._refreshed_for == (ds.key, ds.data_version):
                return
            self._refreshed_for = (ds.key, ds.data_version)
        self._update_all_tabs()

    def _on_results_updated(self):
        """Handle results updated signal."""
        self._update_all_tabs()

    def _update_all_tabs(self, rebuild_browser: bool = True, rock_well_only: bool = False):
        """Update the tabs with current results (hidden plot tabs lazily)."""
        if rebuild_browser:
            self.data_browser.rebuild()
        rock_clean = (rock_well_only and self.tab_widget.currentWidget() is self.rock_tab
                      and self.rock_tab not in self._dirty_tabs)
        self._dirty_tabs.update(t for t in self._lazy_tabs
                                if not (rock_well_only and t is self.rock_tab))
        if rock_well_only:
            if rock_clean:
                self.rock_tab.update_active_well()
            else:
                self._dirty_tabs.add(self.rock_tab)
        self._refresh_current_tab()
        self.summary_tab.update_display()
        self.export_tab.update_display()

    def _mark_rock_tab_dirty(self, *_):
        """Core or wells changed: the Rock Typing tab catches up once, when visible."""
        self._dirty_tabs.add(self.rock_tab)
        self._rock_timer.start()

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
            self.params_window.show_calculated_rw_rsh(
                result["rw"], result["rsh"], result.get("warnings") or [],
                water_samples=result.get("rw_water_samples"),
                shale_samples=result.get("rsh_shale_samples"),
                quality=result.get("rw_quality"),
            )
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
            MIN_CORE_PAIRS, apply_warning, calibrate_from_core, estimate_from_porosity,
            fit_core, pair_core_samples, zone_mask,
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
        perm_q = float(flat.get("perm_Q", self.model.perm_Q))
        swirr_method = flat.get("swirr_method", self.model.swirr_method)
        widget = self.params_window.perm_params_widget
        stale = " Results are out of date; run the analysis first." if ds is not None and ds.stale else ""
        tops = ds.formation_tops if ds is not None else None

        core = self.model.core_data
        core_failure = ""
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
                fit = calibrate_from_core(matched_por, matched_perm, k_buckles, q=perm_q)
                if fit is not None:
                    where = f" in {zone}" if zone else ""
                    widget.show_calculated_result(
                        fit["C"], fit["P"], fit["Q"],
                        source=f"core calibration{where}, {fit['pairs']} pairs")
                    notes = [apply_warning(fit, swirr_method, k_buckles)]
                    if fit.get("clipped_swirr"):
                        notes.append(
                            f"{fit['clipped_swirr']} of {fit['pairs']} plugs have a Buckles "
                            "Swirr at its limit (0.05 or 0.5) and say nothing about the "
                            "porosity exponent.")
                    notes = " ".join(n for n in notes if n)
                    if notes:
                        widget.show_message(notes, "warning", keep_result=True)
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
                _, reason = fit_core(matched_por, matched_perm, k_buckles, q=perm_q)
                core_failure = f"Core calibration failed ({reason}); coefficients estimated from porosity instead"
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
        where = f" in {zone}" if zone else ""
        widget.show_calculated_result(
            C, P, Q, source=f"estimated from porosity{where}, mean {estimate['phi_mean']:.3f}")
        if core_failure:
            widget.show_message(core_failure + ".", "warning", keep_result=True)
        head = f"{core_failure}{where}" if core_failure else f"Estimated from porosity{where}"
        self.statusBar.showMessage(
            f"{head} "
            f"(mean={estimate['phi_mean']:.3f}): "
            f"C={C:.0f}, P={P:.2f}, Q={Q:.2f}.{stale}"
        )

    # =========================================================================
    # EXPORT
    # =========================================================================

    def _on_export_run_wells(self, keys: list):
        """Export tab asked to run its out-of-date wells; come back to it when done."""
        if self._busy or not keys:
            return
        self._start_runs(list(keys), force=True)
        # Only a batch that started returns to the Export tab when it finishes.
        self._export_return = self.batch_runner.is_running()

    def _return_to_export_tab(self, report: dict):
        """After a batch started from the Export tab, show that tab again (no export)."""
        if not getattr(self, "_export_return", False):
            return
        self._export_return = False
        if not report.get("cancelled"):
            self.tab_widget.setCurrentWidget(self.export_tab)

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
        """Save to the current session file; the first save asks for a file (Save As)."""
        self._save_session(as_new=False)

    def _on_save_session_as(self):
        """Save under a new file name."""
        self._save_session(as_new=True)

    def _save_session(self, as_new: bool) -> bool:
        """Write the session; False when the file dialog was cancelled or the write failed."""
        from PyQt6.QtWidgets import QFileDialog

        # Update model from UI first
        self._sync_model_from_ui()

        file_path = None if as_new else self.model.session_path
        if not file_path:
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Session",
                self.model.session_path or "petrophyter_session.json",
                "Session Files (*.json);;All Files (*)",
            )
        if not file_path:
            return False
        if not self.session_service.save_session(self.model, file_path):
            QMessageBox.critical(self, "Error", "Failed to save session")
            return False
        self.model.session_path = file_path
        self.model.mark_clean()
        self._refresh_window_title()
        self.statusBar.showMessage(f"Session saved to {file_path}")
        return True

    def _confirm_discard(self, action: str) -> bool:
        """Offer to save unsaved changes before ``action`` ("close", "load" or "new").

        True when the action may go on (saved or discarded); False on Cancel, or when
        the Save was cancelled in its file dialog or failed.
        """
        if not self.model.dirty:
            return True
        verb = {"close": "closing", "load": "loading a session",
                "new": "starting a new project"}.get(action, action)
        text = f"You have unsaved changes. Save them before {verb}?"
        if action == "new":
            text += "\n\nAll current data will be cleared."
        box = QMessageBox.StandardButton
        reply = QMessageBox.question(
            self, "Unsaved changes", text,
            box.Save | box.Discard | box.Cancel, box.Save,
        )
        if reply == box.Save:
            return self._save_session(as_new=False)
        return reply == box.Discard

    def _prompt_relocate(self, path: str):
        """Ask where a source file of the session has moved to (H3); None means Skip.

        A decision, so a modal file dialog. Runs on the GUI thread before the restore
        worker starts. Tests patch this method.
        """
        from PyQt6.QtWidgets import QFileDialog

        name = os.path.basename(str(path))
        chosen, _ = QFileDialog.getOpenFileName(
            self, f"Locate {name}", os.path.dirname(str(path)),
            f"{name} (*{os.path.splitext(name)[1]});;All Files (*)"
        )
        return chosen or None

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
            QMessageBox.critical(self, "Error",
                                 self.session_service.last_error or "Failed to load session")
            return
        problems = validate_session(session_data)
        if problems:
            QMessageBox.critical(self, "Error", f"Failed to load session: {problems[0]}")
            return
        # Asked only once the file is known to be loadable; nothing is replaced before this.
        if not self._confirm_discard("load"):
            return
        if is_v2_session(session_data):
            # A v2.0 session is a whole project: it replaces the loaded wells, but only
            # once every well is built. Here nothing of the open project is touched; the
            # swap (batch cancel, reset, parameters, wells) is in _on_restore_completed.
            relocate_missing_sources(session_data, self._prompt_relocate)
            self._cancel_restore()
            self._start_restore(session_data, file_path)
            return
        else:
            # Restoring writes the saved values where they belong; it must never
            # create entries at whatever scope the user happened to be editing.
            self._session_swap = True
            try:
                self.model.set_edit_scope("project")
                self.session_service.apply_session_to_model(self.model, session_data)
                notes = session_level_notes(session_data)
                notes += self.session_service.restore_wells(self.model, session_data)
                self._update_ui_from_model()
                self._refresh_uncertainty_page()
            finally:
                self._session_swap = False
            # A 1.x file holds parameters only: the open wells stay, so the project
            # does not match the file, and Save must not overwrite it in 2.x format.
            self.model.mark_dirty()
        # Results in memory (v1.x) were computed with the old parameters;
        # restored wells (v2.0) have none and need a run.
        self._recompute_stale()
        self._show_load_notes(None, notes)
        self.statusBar.showMessage(f"Session loaded from {file_path}")

    # ---- session restore on a worker thread ----

    def _start_restore(self, session_data: dict, file_path: str):
        from PyQt6.QtCore import QThreadPool

        self._restore_generation += 1
        worker = RestoreWorker(session_data, self._restore_generation)
        self._restore_worker = worker
        self._restore_active_key = session_data.get("active_key")
        self._restore_path = file_path
        self._restore_session = session_data
        self._set_busy("restore")
        self._set_progress(1, "Restoring session...")
        worker.signals.progress.connect(
            lambda message, percent, w=worker: self._on_restore_progress(w, message, percent))
        worker.signals.completed.connect(
            lambda datasets, notes, w=worker: self._on_restore_completed(w, datasets, notes))
        worker.signals.error.connect(
            lambda message, w=worker: self._on_restore_error(w, message))
        worker.signals.finished.connect(
            lambda w=worker: self._on_restore_finished(w))
        self._restore_retired.append(worker)    # keeps the signal object alive until finished
        if self._restore_pool is None:
            self._restore_pool = QThreadPool()
        self._restore_pool.start(worker)

    def _is_current_restore(self, worker) -> bool:
        return worker is self._restore_worker and worker.generation == self._restore_generation

    def _on_restore_progress(self, worker, message: str, percent: int):
        if self._is_current_restore(worker):
            self._set_progress(min(max(percent, 1), 99), message)

    def _on_restore_finished(self, worker):
        if worker in self._restore_retired:
            self._restore_retired.remove(worker)

    def _end_restore(self):
        self._restore_worker = None
        self._set_busy(None)
        self._set_progress(0, "")

    def _cancel_restore(self):
        """Drop the running restore (if any); its wells never reach the model."""
        worker = self._restore_worker
        if worker is None:
            return
        worker.cancel()
        self._restore_generation += 1
        self._end_restore()

    def _on_restore_error(self, worker, message: str):
        if not self._is_current_restore(worker):
            return
        self._end_restore()
        # The open project is untouched: nothing was reset before the wells were built.
        self.show_banner("warning", f"Session not loaded: {message}; your open project is unchanged")
        self.statusBar.showMessage("Failed to load session")

    def _on_restore_completed(self, worker, datasets, notes):
        if not self._is_current_restore(worker):
            return
        session_data = getattr(self, "_restore_session", None) or {}
        if not datasets and session_data.get("wells"):
            # Every source was missing or unreadable: a failed restore, not an empty project.
            self._end_restore()
            lines = ["Session not loaded: no well could be restored; your open project is unchanged"]
            self.show_banner("warning", "\n".join(lines + list(notes)))
            self.statusBar.showMessage("Failed to load session")
            return
        self._restore_worker = None
        self._set_busy(None)
        self._set_progress(0, "")
        # The swap: every well is built, so the old project can go.
        self.batch_runner.cancel()
        self._discard_uncertainty()
        self._session_swap = True
        try:
            self.model.reset()
            self.model.set_edit_scope("project")
            self.session_service.apply_session_to_model(self.model, session_data)
            notes = session_level_notes(session_data) + list(notes)
            self._bulk_loading = True
            try:
                notes = self.session_service.install_wells(
                    self.model, datasets, self._restore_active_key, notes)
            finally:
                self._bulk_loading = False
            self._update_ui_from_model()
            self._refresh_active_well_ui()
            self._refresh_uncertainty_page()
        finally:
            self._session_swap = False
        self._mark_session_loaded(self._restore_path)
        # Restored wells have no results and need a run.
        self._recompute_stale()
        self._show_load_notes(None, notes)
        self.statusBar.showMessage(f"Session loaded from {self._restore_path}")

    def _mark_session_loaded(self, file_path: str):
        """The project now matches ``file_path``: Save writes there, nothing is unsaved."""
        self.model.session_path = file_path
        self.model.mark_clean()
        self._refresh_window_title()

    def _on_new_project(self):
        """Handle new project button click - clear all data and reset to fresh state."""
        if self.model.dirty:
            # The save prompt also carries the "all data will be cleared" sentence.
            if not self._confirm_discard("new"):
                return
        elif self.model.las_data is not None or self.model.results is not None:
            # Confirm with user if data is loaded
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
        self._cancel_restore()
        self.batch_runner.cancel()
        self._discard_uncertainty()
        self.model.reset()
        self._refresh_uncertainty_page()
        self.model.session_path = None
        self.model.mark_clean()
        self._refresh_window_title()

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
                    getattr(self.model, "vsh_primary_method", None),
                ),
            ),
            (
                "porosity method",
                lambda: self.params_window.porosity_method_widget.set_params(
                    {"primary_phie_method": self.model.primary_phie_method,
                     "dn_combination": self.model.dn_combination}
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
                    self.model.gas_crossover_min,
                    self.model.gas_vsh_max,
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
