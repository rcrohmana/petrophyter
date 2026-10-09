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

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon
import traceback
import threading
import logging
import re

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.app_model import AppModel
from services.analysis_service import AnalysisService
from services.merge_service import MergeService
from services.export_service import ExportService
from services.session_service import SessionService
from .widgets.about_dialog import AboutDialog
from .widgets.notification_banner import NotificationBanner
from .parameters_window import PAGES, ParametersWindow
from .data_browser import DataBrowserPanel
from themes.tokens import METRICS
from .widgets.merge_dialog import MergeDialog
from .tabs.qc_tab import QCTab
from .tabs.petrophysics_tab import PetrophysicsTab
from .tabs.log_display_tab import LogDisplayTab
from .tabs.diagnostics_tab import DiagnosticsTab
from .tabs.summary_tab import SummaryTab
from .tabs.export_tab import ExportTab

from modules.las_parser import LASParser
from modules.qc_module import QCModule
from modules.formation_tops import FormationTops
from modules.core_handler import CoreDataHandler


logger = logging.getLogger(__name__)


def _sanitize_error_detail(detail, max_length: int = 240) -> str:
    """Keep actionable first-line errors while removing secrets and paths."""
    if detail is None:
        return ""
    first_line = next(
        (line.strip() for line in str(detail).splitlines() if line.strip()), ""
    )
    first_line = re.sub(
        r"(?i)\b(password|token|secret|api[_ -]?key)\b\s*[:=]\s*\S+",
        r"\1=[redacted]",
        first_line,
    )
    first_line = re.sub(r"(?i)(?:[A-Za-z]:[\\/]|/)[^\s)]+", "<path>", first_line)
    return first_line[:max_length]


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
        self.merge_service = MergeService()
        self.export_service = ExportService()
        self.session_service = SessionService()

        # Store loaded LAS parsers for merge
        self._loaded_parsers = []
        self._loaded_file_names = []

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
        self.showMaximized()

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
        self.data_browser.action_requested.connect(
            lambda key: self.actions_[key].trigger()
        )
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

        # Analysis service signals
        self.analysis_service.started.connect(self._on_analysis_started)
        self.analysis_service.progress.connect(self._on_analysis_progress)
        self.analysis_service.completed.connect(
            self._on_analysis_completed, type=Qt.ConnectionType.QueuedConnection
        )
        self.analysis_service.error.connect(self._on_analysis_error)

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
        if self.model.las_filename:
            name = os.path.basename(str(self.model.las_filename))
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
        act("merge_las", "Merge LAS Files…", "merge", None, self._open_merge_dialog)
        act("save_merged", "Save Merged LAS…", "download", None, self._on_download_merged)
        act("exit", "Exit", None, None, self.close)
        act("save_session", "Save Session…", "save", "Ctrl+S", self._on_save_session)
        act("load_session", "Load Session…", "folder-input", "Ctrl+Shift+O", self._on_load_session)
        act("run_analysis", "Run Analysis", "play", "F5", self._on_run_analysis)
        act("toggle_browser", "Data Browser", "panel-left", "Ctrl+B",
            self._toggle_browser, checkable=True)
        act("theme_light", "Light", "sun", None, lambda: self._set_theme("light"), checkable=True)
        act("theme_dark", "Dark", "moon", None, lambda: self._set_theme("dark"), checkable=True)
        act("user_guide", "User Guide", "book-open", None, self._open_user_guide)
        act("about", "About Petrophyter", "info", None, self._on_about_triggered)
        for key, title, _menu in PAGES:
            act(f"page_{key}", f"{title}…", None, None,
                lambda _=False, k=key: self.params_window.open_page(k))
        act("params_window", "Parameters Window", "sliders-horizontal", "Ctrl+P",
            lambda: self.params_window.open_page(self.params_window.current_page()))
        for key in ("run_analysis", "toggle_browser", "params_window"):
            self.actions_[key].setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.actions_["page_core"].setEnabled(False)
        group = QActionGroup(self)
        group.addAction(self.actions_["theme_light"])
        group.addAction(self.actions_["theme_dark"])
        self.actions_["run_analysis"].setEnabled(False)
        self.actions_["merge_las"].setEnabled(False)
        self.actions_["save_merged"].setEnabled(False)
        self.actions_["toggle_browser"].setChecked(True)

    def _build_menus(self):
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
        for key, _title, menu in PAGES:
            if key == "rock":
                menus[menu].addSeparator()  # Basic | Advanced split (spec §2.2)
            menus[menu].addAction(self.actions_[f"page_{key}"])
        view.insertAction(self._menus["view_theme_sep"], self.actions_["params_window"])
        theme_menu = view.addMenu("Theme")
        theme_menu.addAction(self.actions_["theme_light"])
        theme_menu.addAction(self.actions_["theme_dark"])
        help_menu = bar.addMenu("&Help")
        help_menu.addAction(self.actions_["user_guide"])
        help_menu.addAction(self.actions_["about"])

    def _build_toolbar(self):
        from PyQt6.QtCore import QSize
        from PyQt6.QtWidgets import QToolBar, QToolButton

        toolbar = QToolBar("Main")
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
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        self.well_indicator = _WellIndicator()
        toolbar.addWidget(self.well_indicator)
        self.addToolBar(toolbar)
        self.main_toolbar = toolbar

    def _set_progress(self, value: int, message: str = None):
        """Interim progress sink (replaced by the status-bar progress in Task 13)."""
        if message:
            self.statusBar.showMessage(message)

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
        is_dark = self.theme_manager.is_dark() if self.theme_manager else False
        if hasattr(self, "data_browser"):
            self.data_browser.refresh_theme()
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
        """Handle LAS file selection."""
        if len(file_paths) == 1:
            # Single file - load directly
            self._load_single_las(file_paths[0])
        else:
            # Multiple files - prepare for merge
            self._prepare_merge(file_paths)

    def _load_single_las(self, file_path: str):
        """Load a single LAS file."""
        try:
            self.statusBar.showMessage(f"Loading {os.path.basename(file_path)}...")

            parser = LASParser()
            with open(file_path, "r") as f:
                success = parser.read_las_from_buffer(f)

            if success and parser.data is not None:
                self.model.las_parser = parser
                self.model.las_data = parser.data
                self.model.las_filename = file_path
                self.model.calculated = False
                self.model.merge_report = None

                # Run QC
                well_name = parser.well_info.get("well_name", "Unknown")
                qc = QCModule(parser.data, well_name)
                self.model.qc_report = qc.run_qc()

                self.data_browser.set_las_sources(
                    [(os.path.basename(file_path), len(parser.data))],
                    merged=False,
                    pending=False,
                )

                # Update curve mapping
                curves = parser.get_available_curves()
                detected = {}
                for ctype in ["GR", "RHOB", "NPHI", "DT", "RT"]:
                    found = parser.find_curve_by_type(ctype)
                    if found:
                        detected[ctype] = found
                self.params_window.update_available_curves(curves, detected)
                self.model.curve_mapping = {
                    ctype: detected.get(ctype, "None")
                    for ctype in ["GR", "RHOB", "NPHI", "DT", "RT"]
                }

                self.actions_["run_analysis"].setEnabled(True)
                self.actions_["save_merged"].setEnabled(False)
                self.well_indicator.set_well(
                    well_name, len(parser.data), len(parser.data.columns)
                )
                self._refresh_window_title()

                self.statusBar.showMessage(
                    f"Loaded: {os.path.basename(file_path)} ({len(parser.data)} rows)"
                )

                # Refresh once more after QC and mapping are ready. The model's
                # data_loaded signal fires earlier to clear stale result content.
                self._on_data_loaded()

                # Surface an ambiguous depth-unit instead of silently (mis)converting.
                if getattr(parser, "depth_unit_warning", None):
                    QMessageBox.warning(self, "Depth Unit", parser.depth_unit_warning)
            else:
                detail = getattr(parser, "last_error", None)
                logger.error("Failed to load LAS file %s: %s", file_path, detail)
                QMessageBox.critical(
                    self,
                    "Error",
                    _failure_message("Failed to load LAS file", detail),
                )
                self.statusBar.showMessage("Failed to load LAS file")

        except Exception as e:
            logger.exception("Unexpected failure loading LAS file %s", file_path)
            QMessageBox.critical(
                self, "Error", _failure_message("Failed to load LAS file", e)
            )
            self.statusBar.showMessage("Error loading file")

    def _prepare_merge(self, file_paths: list):
        """Prepare multiple LAS files for merge."""
        try:
            self._loaded_parsers = []
            self._loaded_file_names = []
            parse_details = []

            for path in file_paths:
                parser = LASParser()
                with open(path, "r") as f:
                    if parser.read_las_from_buffer(f):
                        self._loaded_parsers.append(parser)
                        self._loaded_file_names.append(os.path.basename(path))
                    else:
                        detail = getattr(parser, "last_error", None)
                        logger.error("Failed to parse LAS file %s: %s", path, detail)
                        safe_detail = _sanitize_error_detail(detail)
                        if safe_detail:
                            parse_details.append(
                                f"{os.path.basename(path)}: {safe_detail}"
                            )

            if len(self._loaded_parsers) >= 2:
                self.merge_dialog.set_files(
                    [
                        (name, len(parser.data), *parser.get_depth_range())
                        for name, parser in zip(
                            self._loaded_file_names, self._loaded_parsers
                        )
                    ]
                )
                self.actions_["merge_las"].setEnabled(True)
                self.data_browser.set_las_sources(
                    [
                        (name, len(parser.data))
                        for name, parser in zip(
                            self._loaded_file_names, self._loaded_parsers
                        )
                    ],
                    merged=False,
                    pending=True,
                )
                self.data_browser.rebuild()
                self.statusBar.showMessage(
                    f"{len(self._loaded_parsers)} LAS files ready for merge"
                )
                self._open_merge_dialog()
            else:
                message = "Need at least 2 valid LAS files to merge"
                if parse_details:
                    message += "\n" + "\n".join(parse_details)
                QMessageBox.warning(self, "Warning", message)

        except Exception as e:
            logger.exception("Unexpected failure preparing LAS files")
            QMessageBox.critical(
                self, "Error", _failure_message("Failed to prepare files", e)
            )

    def _open_merge_dialog(self):
        """Show the Merge LAS Files dialog; merge on accept."""
        if self.merge_dialog.exec() == QDialog.DialogCode.Accepted:
            self._on_merge_requested()

    def _on_merge_requested(self):
        """Handle merge request."""
        if len(self._loaded_parsers) < 2:
            QMessageBox.warning(self, "Warning", "Need at least 2 LAS files to merge")
            return

        self._sync_model_from_ui()
        self.actions_["merge_las"].setEnabled(False)

        self.merge_service.merge_files(
            self._loaded_parsers,
            self._loaded_file_names,
            self.model.merge_step,
            self.model.merge_gap_limit,
        )

    def _on_merge_started(self):
        """Handle merge started."""
        self._set_progress(0, "Merging...")
        self.statusBar.showMessage("Merging LAS files...")

    def _on_merge_progress(self, message: str, percent: int):
        """Handle merge progress."""
        self._set_progress(percent, message)

    def _on_merge_completed(self, merged_df, merge_report):
        """Handle merge completion."""
        self.actions_["merge_las"].setEnabled(False)  # nothing pending any more
        self._set_progress(100, "Complete")

        # Store merged data
        self.model.las_parser = self._loaded_parsers[0]
        self.model.las_parser.data = merged_df
        self.model.las_data = merged_df
        self.model.las_filename = f"MERGED_{len(self._loaded_parsers)}_files"
        self.model.merge_report = merge_report
        self.model.calculated = False

        # Run QC on merged data
        qc = QCModule(merged_df, merge_report.well_name)
        self.model.qc_report = qc.run_qc()

        self.data_browser.set_las_sources(
            [
                (name, len(parser.data))
                for name, parser in zip(self._loaded_file_names, self._loaded_parsers)
            ],
            merged=True,
            pending=False,
        )

        # Update curve mapping
        curves = self.model.las_parser.get_available_curves()
        detected = {}
        for ctype in ["GR", "RHOB", "NPHI", "DT", "RT"]:
            found = self.model.las_parser.find_curve_by_type(ctype)
            if found:
                detected[ctype] = found
        self.params_window.update_available_curves(curves, detected)
        self.model.curve_mapping = {
            ctype: detected.get(ctype, "None")
            for ctype in ["GR", "RHOB", "NPHI", "DT", "RT"]
        }

        self.actions_["run_analysis"].setEnabled(True)
        self.actions_["save_merged"].setEnabled(True)
        self.well_indicator.set_well(
            merge_report.well_name, len(merged_df), len(merged_df.columns)
        )
        self._refresh_window_title()

        self.statusBar.showMessage(
            f"Merged {len(self._loaded_parsers)} files ({len(merged_df)} rows)"
        )

        self._on_data_loaded()

    def _on_merge_error(self, error: str):
        """Handle merge error."""
        self.actions_["merge_las"].setEnabled(True)
        self._set_progress(0, "")
        QMessageBox.critical(self, "Merge Error", error)
        self.statusBar.showMessage("Merge failed")

    def _on_download_merged(self):
        """Handle merged LAS download."""
        from PyQt6.QtWidgets import QFileDialog

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Merged LAS",
            "merged_output.las",
            "LAS Files (*.las);;All Files (*)",
        )

        if file_path:
            success = self.export_service.export_las(
                self.model.las_data, self.model.las_parser.well_info, file_path
            )

    # =========================================================================
    # FORMATION TOPS & CORE DATA
    # =========================================================================

    def _on_tops_file_selected(self, file_path: str):
        """Handle formation tops file selection."""
        try:
            tops = FormationTops()
            with open(file_path, "r") as f:
                if tops.read_tops_from_buffer(f):
                    # convert_to_feet() only converts when the unit was detected
                    # as meters; feet/undetected files are left unchanged.
                    tops.convert_to_feet()
                    self.model.formation_tops = tops

                    self.params_window.update_formations_list(tops.get_formation_list())

                    self.statusBar.showMessage(
                        f"Loaded {len(tops.formations)} formations"
                    )

                    if getattr(tops, "depth_unit_warning", None):
                        QMessageBox.warning(self, "Depth Unit", tops.depth_unit_warning)

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
        """Handle core data file selection."""
        try:
            self._sync_model_from_ui()

            handler = CoreDataHandler()
            with open(file_path, "r") as f:
                if handler.read_core_from_buffer(
                    f, depth_unit=self.model.core_depth_unit
                ):
                    self.model.core_data = handler
                    self.params_window.set_core_available(True)
                    self._refresh_core_actions()

                    summary = handler.get_summary()

                    self.statusBar.showMessage(
                        f"Loaded {summary['n_samples']} core samples"
                    )

                    if getattr(handler, "depth_unit_warning", None):
                        QMessageBox.warning(self, "Depth Unit", handler.depth_unit_warning)
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
        """Handle run analysis button click."""
        if self.model.las_data is None:
            QMessageBox.warning(
                self, "Warning", "No data loaded. Please load a LAS file first."
            )
            return

        # Update model from UI and close the double-click window before the
        # background worker can emit its asynchronous started signal.
        self._sync_model_from_ui()
        self.actions_["run_analysis"].setEnabled(False)

        # Start analysis
        self.analysis_service.run_analysis(self.model)

    def _on_analysis_started(self):
        """Handle analysis started."""
        self.actions_["run_analysis"].setEnabled(False)
        self._set_progress(0, "Analyzing...")
        self.statusBar.showMessage("Running petrophysics analysis...")

    def _on_analysis_progress(self, message: str, percent: int):
        """Handle analysis progress."""
        self._set_progress(percent, message)
        self.statusBar.showMessage(message)

    def _on_analysis_completed(self, results, summary):
        """Handle analysis completion."""
        # print(
        #     f"[DEBUG MainWindow] _on_analysis_completed called on Thread: {threading.current_thread().name}"
        # )
        # print(f"[DEBUG MainWindow] results.shape = {results.shape}")
        # print(f"[DEBUG MainWindow] results.columns = {list(results.columns)[:10]}...")

        self._set_progress(100, "Complete")
        self.actions_["run_analysis"].setEnabled(True)

        # Store both pieces of the analysis result atomically so observers see
        # a matching results/summary pair and only one completion refresh.
        self.model.set_analysis_results(results, summary)

        # print(
        #     f"[DEBUG MainWindow] After storing: model.calculated = {self.model.calculated}"
        # )
        # print(
        #     f"[DEBUG MainWindow] After storing: model.results is None = {self.model.results is None}"
        # )

        self.statusBar.showMessage("✅ Analysis complete!")

        # Show success message
        QMessageBox.information(
            self,
            "Analysis Complete",
            f"Analysis completed successfully!\n\n"
            f"Net Pay: {summary.get('net_pay', 0):.1f} ft\n"
            f"Gross Sand: {summary.get('gross_sand', 0):.1f} ft\n"
            f"N/G Pay: {summary.get('ng_pay', 0) * 100:.1f}%",
        )

    def _on_analysis_error(self, error: str):
        """Handle analysis error."""
        self._set_progress(0, "")
        self.actions_["run_analysis"].setEnabled(True)
        QMessageBox.critical(self, "Analysis Error", error)
        self.statusBar.showMessage("Analysis failed")

    def _on_data_loaded(self):
        """Refresh every tab after data replacement invalidates derived state."""
        self._update_all_tabs()

    def _on_results_updated(self):
        """Handle results updated signal."""
        self._update_all_tabs()

    def _update_all_tabs(self):
        """Update all tabs with current results."""
        self.data_browser.rebuild()
        self.qc_tab.update_display()
        self.petro_tab.update_display()
        self.log_tab.update_display()
        self.diag_tab.update_display()
        self.summary_tab.update_display()
        self.export_tab.update_display()

    # =========================================================================
    # PARAMETER CALCULATIONS
    # =========================================================================

    def _on_calculate_rw_rsh(self):
        """Calculate Rw and Rsh from data."""
        if self.model.las_data is None:
            QMessageBox.warning(self, "Warning", "No data loaded")
            return

        self._sync_model_from_ui()
        result = self.analysis_service.calculate_rw_rsh(self.model)

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
        result = self.analysis_service.calculate_shale_parameters(self.model)

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
        """Calculate permeability coefficients (with or without core data)."""
        if not self.model.calculated or self.model.results is None:
            QMessageBox.warning(self, "Warning", "Please run analysis first")
            return

        results = self.model.results

        if "PHIE" not in results.columns:
            QMessageBox.warning(
                self, "Warning", "PHIE not calculated. Run analysis first."
            )
            return

        import numpy as np

        # If core data available, use core-based fitting
        if self.model.core_data is not None:
            try:
                from scipy import optimize

                core = self.model.core_data

                # Get core data
                core_depths, core_perm = core.get_core_permeability()
                core_depths_por, core_por = core.get_core_porosity()

                if len(core_perm) >= 5 and len(core_por) >= 5:
                    # Match porosity with permeability at same depths
                    matched_por = []
                    matched_perm = []
                    for i, d in enumerate(core_depths):
                        idx = np.argmin(np.abs(core_depths_por - d))
                        if np.abs(core_depths_por[idx] - d) < 0.5:  # Within 0.5 ft
                            matched_por.append(core_por[idx])
                            matched_perm.append(core_perm[i])

                    if len(matched_por) >= 5:
                        matched_por = np.array(matched_por)
                        matched_perm = np.array(matched_perm)

                        # Estimate Swirr using Buckles
                        swirr = self.model.k_buckles / matched_por
                        swirr = np.clip(swirr, 0.05, 0.8)

                        # Fit Wyllie-Rose: K = C * phi^P / Swi^Q
                        def wyllie_rose(phi, swi, C, P, Q):
                            return C * (phi**P) / (swi**Q)

                        def objective(params, phi, swi, k):
                            C, P, Q = params
                            k_pred = wyllie_rose(phi, swi, C, P, Q)
                            return np.sum(
                                (np.log10(k_pred + 0.001) - np.log10(k + 0.001)) ** 2
                            )

                        # Initial guess
                        x0 = [8581, 4.4, 2.0]
                        bounds = [(10, 50000), (2, 8), (0.5, 4)]

                        result = optimize.minimize(
                            objective,
                            x0,
                            args=(matched_por, swirr, matched_perm),
                            bounds=bounds,
                            method="L-BFGS-B",
                        )

                        if result.success:
                            C, P, Q = result.x
                            self.params_window.perm_params_widget.show_calculated_result(
                                C, P, Q
                            )
                            self.statusBar.showMessage(
                                f"Core-calibrated: C={C:.0f}, P={P:.2f}, Q={Q:.2f}"
                            )
                            return
            except Exception:
                logger.exception(
                    "Core permeability fit failed; using statistical estimation"
                )

        # Statistical estimation based on porosity (works without core)
        try:
            phie = results["PHIE"].dropna()

            if len(phie) < 10:
                QMessageBox.warning(self, "Warning", "Insufficient data for regression")
                return

            phi_mean = phie.mean()

            # Adjust coefficients based on porosity distribution
            if phi_mean > 0.20:
                # High porosity - unconsolidated
                C, P, Q = 10000.0, 4.0, 2.0
            elif phi_mean > 0.12:
                # Medium porosity - typical sandstone (Timur defaults)
                C, P, Q = 8581.0, 4.4, 2.0
            else:
                # Low porosity - tight formation
                C, P, Q = 5000.0, 5.0, 2.2

            self.params_window.perm_params_widget.show_calculated_result(C, P, Q)
            self.statusBar.showMessage(
                f"Estimated from porosity (mean={phi_mean:.3f}): C={C:.0f}, P={P:.2f}, Q={Q:.2f}"
            )

        except Exception as e:
            QMessageBox.warning(
                self, "Error", f"Failed to calculate coefficients:\n{str(e)}"
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
                QMessageBox.information(
                    self, "Session Saved", "Session parameters saved successfully!"
                )
            else:
                QMessageBox.critical(self, "Error", "Failed to save session")

    def _on_load_session(self):
        """Handle load session button click."""
        from PyQt6.QtWidgets import QFileDialog

        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Session", "", "Session Files (*.json);;All Files (*)"
        )

        if file_path:
            session_data = self.session_service.load_session(file_path)
            if session_data:
                self.session_service.apply_session_to_model(self.model, session_data)
                self._update_ui_from_model()
                self.statusBar.showMessage(f"Session loaded from {file_path}")
                QMessageBox.information(
                    self, "Session Loaded", "Session parameters restored!"
                )
            else:
                QMessageBox.critical(self, "Error", "Failed to load session")

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

        # Reset model data
        self.model.reset()

        # Clear loaded parsers for merge
        self._loaded_parsers = []
        self._loaded_file_names = []

        # Reset data browser
        self.data_browser.set_las_sources([], merged=False, pending=False)
        self.data_browser.rebuild()
        self.params_window.reset_ui()
        self._refresh_core_actions()
        self.actions_["run_analysis"].setEnabled(False)
        self.actions_["merge_las"].setEnabled(False)
        self.actions_["save_merged"].setEnabled(False)
        self.well_indicator.set_empty()
        self._refresh_window_title()

        # Reset all tabs UI to fresh state
        self.qc_tab.reset_ui()
        self.petro_tab.reset_ui()
        self.log_tab.reset_ui()
        self.diag_tab.reset_ui()
        self.summary_tab.reset_ui()
        self.export_tab.reset_ui()

        # Reset status bar
        self.statusBar.showMessage("Ready. Load a LAS file to begin.")

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
                    self.model.rw, self.model.rsh
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
