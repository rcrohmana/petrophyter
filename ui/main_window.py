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
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon

from themes.colors import get_color

from .sidebar_panel import SidebarPanel
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

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.app_model import AppModel
from services.analysis_service import AnalysisService
from services.merge_service import MergeService
from services.export_service import ExportService
from services.session_service import SessionService
from .sidebar_panel import SidebarPanel
from .widgets.about_dialog import AboutDialog
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
        self._setup_ui()
        self._setup_connections()

        # Listen for theme changes
        if self.theme_manager:
            self.theme_manager.on_theme_changed(self._handle_theme_change)

        # Set window properties
        self.setWindowTitle("Petrophyter - Petrophysics Master")

        self.setMinimumSize(1400, 900)
        self.showMaximized()

        # Set initial theme button state
        if self.theme_manager:
            self.sidebar.update_theme_button(self.theme_manager.is_dark())
            self._handle_theme_change(self.theme_manager.get_current_theme())

    def _setup_ui(self):
        """Setup the main UI layout."""
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
        # LEFT SIDEBAR
        # =====================================================================
        self.sidebar = SidebarPanel(self.model)
        splitter.addWidget(self.sidebar)

        # =====================================================================
        # MAIN CONTENT (TABS)
        # =====================================================================
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(10, 10, 10, 10)

        # Title
        from PyQt6.QtWidgets import QLabel

        self.title_label = QLabel(
            f"<h1 style='color: {get_color('primary')}; text-align: center;'>Petrophyter</h1>"
        )
        self.subtitle_label = QLabel(
            f"<p style='color: {get_color('text_secondary')}; background-color: transparent; text-align: center;'>Petrophysics Master: Semi-Automatic LAS QC & Analysis</p>"
        )

        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(self.title_label)
        content_layout.addWidget(self.subtitle_label)

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

        self.tab_widget.addTab(self.qc_tab, "📊 Data QC")
        self.tab_widget.addTab(self.petro_tab, "🧮 Petrophysics")
        self.tab_widget.addTab(self.log_tab, "📈 Log Display")
        self.tab_widget.addTab(self.diag_tab, "🔍 Diagnostics")
        self.tab_widget.addTab(self.summary_tab, "📋 Summary")
        self.tab_widget.addTab(self.export_tab, "💾 Export")

        content_layout.addWidget(self.tab_widget)

        splitter.addWidget(content_widget)

        # Use stretch factors for responsive sizing
        splitter.setStretchFactor(0, 0)  # Sidebar: fixed width, don't stretch
        splitter.setStretchFactor(1, 1)  # Content: stretch to fill available space

        # Set initial sizes (sidebar : content)
        splitter.setSizes([360, 1040])

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
        # Sidebar signals
        self.sidebar.las_files_selected.connect(self._on_las_files_selected)
        self.sidebar.merge_requested.connect(self._on_merge_requested)
        self.sidebar.tops_file_selected.connect(self._on_tops_file_selected)
        self.sidebar.core_file_selected.connect(self._on_core_file_selected)
        self.sidebar.run_analysis_clicked.connect(self._on_run_analysis)
        self.sidebar.download_merged_clicked.connect(self._on_download_merged)
        self.sidebar.calculate_rw_rsh_clicked.connect(self._on_calculate_rw_rsh)
        self.sidebar.calculate_shale_clicked.connect(self._on_calculate_shale)
        self.sidebar.apply_shale_clicked.connect(self._on_apply_shale)
        self.sidebar.calculate_perm_clicked.connect(self._on_calculate_perm)

        # Session signals (v1.2)
        self.sidebar.new_project_clicked.connect(self._on_new_project)
        self.sidebar.save_session_clicked.connect(self._on_save_session)
        self.sidebar.load_session_clicked.connect(self._on_load_session)
        self.sidebar.help_clicked.connect(self._on_about_triggered)

        # Theme toggle signal
        self.sidebar.theme_toggle_clicked.connect(self._on_theme_toggle)

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

    def _on_theme_toggle(self):
        """Handle theme toggle button click."""
        if self.theme_manager:
            self.theme_manager.toggle_theme()

    def _handle_theme_change(self, theme: str):
        """Refresh widgets when theme changes."""
        is_dark = self.theme_manager.is_dark() if self.theme_manager else False
        if hasattr(self, "sidebar"):
            self.sidebar.update_theme_button(is_dark)
            self.sidebar.refresh_theme()
        for tab in [
            getattr(self, "qc_tab", None),
            getattr(self, "petrophysics_tab", None),
            getattr(self, "log_display_tab", None),
            getattr(self, "diagnostics_tab", None),
            getattr(self, "summary_tab", None),
            getattr(self, "export_tab", None),
        ]:
            if tab and hasattr(tab, "refresh_theme"):
                tab.refresh_theme()
        if hasattr(self, "title_label"):
            self.title_label.setText(
                f"<h1 style='color: {get_color('primary')}; text-align: center;'>Petrophyter</h1>"
            )
        if hasattr(self, "subtitle_label"):
            self.subtitle_label.setText(
                f"<p style='color: {get_color('text_secondary')}; background-color: transparent; text-align: center;'>Petrophysics Master: Semi-Automatic LAS QC & Analysis</p>"
            )

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

                # Update sidebar
                self.sidebar.update_las_info(
                    file_path, len(parser.data), len(parser.data.columns)
                )

                # Update curve mapping
                curves = parser.get_available_curves()
                detected = {}
                for ctype in ["GR", "RHOB", "NPHI", "DT", "RT"]:
                    found = parser.find_curve_by_type(ctype)
                    if found:
                        detected[ctype] = found
                self.sidebar.update_available_curves(curves, detected)

                self.statusBar.showMessage(
                    f"Loaded: {os.path.basename(file_path)} ({len(parser.data)} rows)"
                )
            else:
                QMessageBox.critical(self, "Error", "Failed to load LAS file")
                self.statusBar.showMessage("Failed to load LAS file")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load LAS file:\n{str(e)}")
            self.statusBar.showMessage("Error loading file")

    def _prepare_merge(self, file_paths: list):
        """Prepare multiple LAS files for merge."""
        try:
            self._loaded_parsers = []
            self._loaded_file_names = []

            for path in file_paths:
                parser = LASParser()
                with open(path, "r") as f:
                    if parser.read_las_from_buffer(f):
                        self._loaded_parsers.append(parser)
                        self._loaded_file_names.append(os.path.basename(path))

            if len(self._loaded_parsers) >= 2:
                self.sidebar.update_multiple_files_info(len(self._loaded_parsers))
                self.statusBar.showMessage(
                    f"{len(self._loaded_parsers)} LAS files ready for merge"
                )
            else:
                QMessageBox.warning(
                    self, "Warning", "Need at least 2 valid LAS files to merge"
                )

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to prepare files:\n{str(e)}")

    def _on_merge_requested(self):
        """Handle merge request."""
        if len(self._loaded_parsers) < 2:
            QMessageBox.warning(self, "Warning", "Need at least 2 LAS files to merge")
            return

        self.sidebar.update_model_from_ui()

        self.merge_service.merge_files(
            self._loaded_parsers,
            self._loaded_file_names,
            self.model.merge_step,
            self.model.merge_gap_limit,
        )

    def _on_merge_started(self):
        """Handle merge started."""
        self.sidebar.set_progress(0, "Merging...")
        self.statusBar.showMessage("Merging LAS files...")

    def _on_merge_progress(self, message: str, percent: int):
        """Handle merge progress."""
        self.sidebar.set_progress(percent, message)

    def _on_merge_completed(self, merged_df, merge_report):
        """Handle merge completion."""
        self.sidebar.set_progress(100, "Complete")

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

        # Update sidebar
        self.sidebar.update_las_info(
            self.model.las_filename,
            len(merged_df),
            len(merged_df.columns),
            is_merged=True,
        )

        # Update curve mapping
        curves = self.model.las_parser.get_available_curves()
        detected = {}
        for ctype in ["GR", "RHOB", "NPHI", "DT", "RT"]:
            found = self.model.las_parser.find_curve_by_type(ctype)
            if found:
                detected[ctype] = found
        self.sidebar.update_available_curves(curves, detected)

        self.statusBar.showMessage(
            f"Merged {len(self._loaded_parsers)} files ({len(merged_df)} rows)"
        )

        # Update QC tab
        self.qc_tab.update_display()

    def _on_merge_error(self, error: str):
        """Handle merge error."""
        self.sidebar.set_progress(0, "")
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
                    tops.convert_to_feet()
                    self.model.formation_tops = tops

                    self.sidebar.update_tops_info(len(tops.formations))
                    self.sidebar.update_formations_list(tops.get_formation_list())

                    self.statusBar.showMessage(
                        f"Loaded {len(tops.formations)} formations"
                    )

                    # Update QC tab
                    self.qc_tab.update_display()
                else:
                    QMessageBox.warning(
                        self, "Warning", "Failed to parse formation tops file"
                    )

        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Failed to load formation tops:\n{str(e)}"
            )

    def _on_core_file_selected(self, file_path: str):
        """Handle core data file selection."""
        try:
            self.sidebar.update_model_from_ui()

            handler = CoreDataHandler()
            with open(file_path, "r") as f:
                if handler.read_core_from_buffer(
                    f, depth_unit=self.model.core_depth_unit
                ):
                    self.model.core_data = handler

                    summary = handler.get_summary()
                    self.sidebar.update_core_info(
                        summary["n_samples"],
                        summary.get("depth_unit", "FT"),
                        handler.porosity_converted,
                    )

                    self.statusBar.showMessage(
                        f"Loaded {summary['n_samples']} core samples"
                    )
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

        # Update model from UI
        self.sidebar.update_model_from_ui()

        # Start analysis
        self.analysis_service.run_analysis(self.model)

    def _on_analysis_started(self):
        """Handle analysis started."""
        self.sidebar.run_btn.setEnabled(False)
        self.sidebar.set_progress(0, "Analyzing...")
        self.statusBar.showMessage("Running petrophysics analysis...")

    def _on_analysis_progress(self, message: str, percent: int):
        """Handle analysis progress."""
        self.sidebar.set_progress(percent, message)
        self.statusBar.showMessage(message)

    def _on_analysis_completed(self, results, summary):
        """Handle analysis completion."""
        # print(
        #     f"[DEBUG MainWindow] _on_analysis_completed called on Thread: {threading.current_thread().name}"
        # )
        # print(f"[DEBUG MainWindow] results.shape = {results.shape}")
        # print(f"[DEBUG MainWindow] results.columns = {list(results.columns)[:10]}...")

        self.sidebar.set_progress(100, "Complete")
        self.sidebar.run_btn.setEnabled(True)

        # Store results
        self.model.results = results
        self.model.summary = summary

        # print(
        #     f"[DEBUG MainWindow] After storing: model.calculated = {self.model.calculated}"
        # )
        # print(
        #     f"[DEBUG MainWindow] After storing: model.results is None = {self.model.results is None}"
        # )

        self.statusBar.showMessage("✅ Analysis complete!")

        # Explicitly update all tabs (in case signal doesn't propagate)
        # print("[DEBUG MainWindow] Calling _update_all_tabs()")
        self._update_all_tabs()

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
        self.sidebar.set_progress(0, "")
        self.sidebar.run_btn.setEnabled(True)
        QMessageBox.critical(self, "Analysis Error", error)
        self.statusBar.showMessage("Analysis failed")

    def _on_data_loaded(self):
        """Handle data loaded signal."""
        self.qc_tab.update_display()

    def _on_results_updated(self):
        """Handle results updated signal."""
        self._update_all_tabs()

    def _update_all_tabs(self):
        """Update all tabs with current results."""
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

        self.sidebar.update_model_from_ui()
        result = self.analysis_service.calculate_rw_rsh(self.model)

        if result:
            self.sidebar.show_calculated_rw_rsh(result["rw"], result["rsh"])
        else:
            QMessageBox.warning(self, "Warning", "Could not calculate Rw/Rsh from data")

    def _on_calculate_shale(self):
        """Calculate shale parameters from data."""
        if self.model.las_data is None:
            QMessageBox.warning(self, "Warning", "No data loaded")
            return

        self.sidebar.update_model_from_ui()
        result = self.analysis_service.calculate_shale_parameters(self.model)

        if result:
            self.model.calculated_shale = result
            self.sidebar.show_calculated_shale(result)
        else:
            QMessageBox.warning(
                self, "Warning", "Could not calculate shale parameters from data"
            )

    def _on_apply_shale(self):
        """Apply calculated shale parameters."""
        if self.model.calculated_shale:
            self.sidebar.shale_params_widget.set_params(
                self.model.calculated_shale["rho_shale"],
                self.model.calculated_shale["dt_shale"],
                self.model.calculated_shale["nphi_shale"],
            )
            self.model.shale_method_used = "statistical"
            # Keep calculated_shale for Diagnostics Tab reference
            # (previously was set to None, causing Statistical Values to not display)

    def _on_calculate_perm(self):
        """Calculate permeability coefficients (with or without core data)."""
        if self.model.results is None:
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
                            self.sidebar.perm_params_widget.show_calculated_result(
                                C, P, Q
                            )
                            self.statusBar.showMessage(
                                f"Core-calibrated: C={C:.0f}, P={P:.2f}, Q={Q:.2f}"
                            )
                            return
            except Exception as e:
                pass  # Fall through to statistical estimation

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

            self.sidebar.perm_params_widget.show_calculated_result(C, P, Q)
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
        if self.model.results is not None:
            self.export_service.export_csv(self.model.results, file_path)

    def _on_export_excel(self, file_path: str):
        """Handle Excel export."""
        if self.model.results is not None and self.model.summary is not None:
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
        self.sidebar.update_model_from_ui()

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

        # Reset sidebar UI
        self.sidebar.reset_ui()

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
        """Update UI widgets from model values after loading session."""
        # Update sidebar widgets from model values
        # This refreshes all parameter fields
        try:
            # VShale
            self.sidebar.vsh_params_widget.set_baseline_method(
                self.model.vsh_baseline_method
            )
            self.sidebar.vsh_params_widget.set_gr_range(
                self.model.gr_min_manual, self.model.gr_max_manual
            )

            # Matrix
            self.sidebar.matrix_params_widget.set_params(
                self.model.rho_matrix, self.model.dt_matrix
            )

            # Fluid
            self.sidebar.fluid_params_widget.set_params(
                self.model.rho_fluid, self.model.dt_fluid
            )

            # Shale
            self.sidebar.shale_params_widget.set_params(
                self.model.rho_shale, self.model.dt_shale, self.model.nphi_shale
            )

            # Archie
            self.sidebar.archie_params_widget.set_params(
                self.model.a, self.model.m, self.model.n
            )

            # Resistivity
            self.sidebar.res_params_widget.set_params(self.model.rw, self.model.rsh)

            # Perm
            self.sidebar.perm_params_widget.set_params(
                self.model.perm_C, self.model.perm_P, self.model.perm_Q
            )

            # Cutoffs
            self.sidebar.cutoff_params_widget.set_params(
                self.model.vsh_cutoff, self.model.phi_cutoff, self.model.sw_cutoff
            )

            # Gas correction (v1.2)
            self.sidebar.gas_correction_widget.set_params(
                self.model.gas_correction_enabled,
                self.model.gas_nphi_factor,
                self.model.gas_rhob_factor,
            )
        except Exception:
            pass  # Best effort - some widgets may not support set_params
