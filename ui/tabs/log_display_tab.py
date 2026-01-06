"""
Log Display Tab for Petrophyter PyQt v2.0
Hybrid log viewer: pyqtgraph for interactive, matplotlib for export.
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QGroupBox,
    QDoubleSpinBox,
    QScrollArea,
    QStackedWidget,
    QComboBox,
    QCheckBox,
    QPushButton,
    QButtonGroup,
    QRadioButton,
)
from PyQt6.QtCore import Qt, pyqtSignal

from ..widgets.plot_widget import CompositeLogPlot, CrossPlot
from ..widgets.interactive_log import InteractiveLogPlot, HAS_PYQTGRAPH


class LogDisplayTab(QWidget):
    """Log Display Tab - composite log and crossplots with hybrid viewer."""

    # Signals
    depth_selection_changed = pyqtSignal(float, float)  # (top, bottom)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self._updating_depth = False  # Guard for bi-directional sync
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create scroll area for the entire content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)

        # Container widget inside scroll area
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)

        # Title
        title = QLabel("📈 Log Display")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        # =====================================================================
        # CONTROLS BAR
        # =====================================================================
        controls_layout = QHBoxLayout()

        # Engine selector
        controls_layout.addWidget(QLabel("Plot Engine:"))
        self.engine_combo = QComboBox()

        # Always add Interactive option, let the widget handle fallback if missing
        self.engine_combo.addItems(["Interactive (pyqtgraph)", "Classic (matplotlib)"])

        if not HAS_PYQTGRAPH:
            self.engine_combo.setToolTip(
                "pyqtgraph not detected - Interactive mode will show warning"
            )

        self.engine_combo.currentIndexChanged.connect(self._on_engine_changed)
        controls_layout.addWidget(self.engine_combo)

        controls_layout.addSpacing(20)

        # Depth range controls
        controls_layout.addWidget(QLabel("Top Depth:"))
        self.top_spin = QDoubleSpinBox()
        self.top_spin.setRange(0, 100000)
        self.top_spin.setDecimals(1)
        self.top_spin.setSuffix(" ft")
        controls_layout.addWidget(self.top_spin)

        controls_layout.addWidget(QLabel("Bottom Depth:"))
        self.bottom_spin = QDoubleSpinBox()
        self.bottom_spin.setRange(0, 100000)
        self.bottom_spin.setDecimals(1)
        self.bottom_spin.setSuffix(" ft")
        controls_layout.addWidget(self.bottom_spin)

        controls_layout.addSpacing(10)

        # Show Formation Tops checkbox
        self.show_tops_check = QCheckBox("Show Formation Tops")
        self.show_tops_check.setChecked(True)
        self.show_tops_check.stateChanged.connect(self._on_show_tops_changed)
        controls_layout.addWidget(self.show_tops_check)

        # HCPV Display Options
        controls_layout.addSpacing(20)
        controls_layout.addWidget(QLabel("HCPV:"))

        # Checkbox for show/hide HCPV track
        self.show_hcpv_check = QCheckBox("Show")
        self.show_hcpv_check.setChecked(True)
        self.show_hcpv_check.stateChanged.connect(self._on_show_hcpv_changed)
        controls_layout.addWidget(self.show_hcpv_check)

        # ComboBox for HCPV mode
        self.hcpv_mode_combo = QComboBox()
        self.hcpv_mode_combo.addItems(
            [
                "Net Pay",  # Default: dHCPV_NET_PAY + HCPV_CUM_NET_PAY
                "Net Reservoir",  # dHCPV_NET_RES + HCPV_CUM_NET_RES
                "Gross",  # dHCPV + HCPV_CUM
                "Fraction Only",  # HCPV_FRAC only
            ]
        )
        self.hcpv_mode_combo.setToolTip("Select HCPV display mode")
        self.hcpv_mode_combo.currentIndexChanged.connect(self._on_hcpv_mode_changed)
        controls_layout.addWidget(self.hcpv_mode_combo)

        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        # =====================================================================
        # STACKED PLOT AREA (interactive / classic) - FIXED HEIGHT
        # =====================================================================
        self.plot_stack = QStackedWidget()
        self.plot_stack.setMinimumHeight(650)  # Fixed minimum height for log

        # Page 0: Interactive (pyqtgraph)
        self.interactive_log = InteractiveLogPlot(n_tracks=6)
        if HAS_PYQTGRAPH:
            self.interactive_log.depth_changed.connect(
                self._on_interactive_depth_changed
            )
            self.interactive_log.depth_region_changed.connect(
                self._on_region_selection_changed
            )
        self.plot_stack.addWidget(self.interactive_log)

        # Page 1: Classic (matplotlib)
        self.classic_log = CompositeLogPlot()
        self.plot_stack.addWidget(self.classic_log)

        # Default to interactive if available
        self.plot_stack.setCurrentIndex(0 if HAS_PYQTGRAPH else 1)

        layout.addWidget(self.plot_stack)

        # =====================================================================
        # CROSSPLOTS SECTION (Expands BELOW - not taking log space)
        # =====================================================================
        self.xplot_group = QGroupBox("Crossplots (click to expand)")
        self.xplot_group.setCheckable(True)
        self.xplot_group.setChecked(False)  # Collapsed by default
        xplot_layout = QHBoxLayout(self.xplot_group)

        self.nd_crossplot = CrossPlot()
        self.nd_crossplot.setFixedHeight(300)  # Fixed height
        self.pk_crossplot = CrossPlot()
        self.pk_crossplot.setFixedHeight(300)  # Fixed height

        xplot_layout.addWidget(self.nd_crossplot)
        xplot_layout.addWidget(self.pk_crossplot)

        # Connect toggle to show/hide contents
        self.xplot_group.toggled.connect(
            lambda checked: self._toggle_crossplots(self.xplot_group, checked)
        )
        self._toggle_crossplots(self.xplot_group, False)  # Initially hidden

        layout.addWidget(self.xplot_group)

        # Placeholder
        self.placeholder = QLabel("👈 Run analysis first to view log display")
        self.placeholder.setStyleSheet(
            "color: #4A4540; background-color: transparent; font-size: 14px;"
        )
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.placeholder)

        # Spacer to push content up when crossplots hidden
        layout.addStretch()

        # Set container to scroll area
        scroll_area.setWidget(container)
        main_layout.addWidget(scroll_area)

        # Connect depth spinboxes
        self.top_spin.valueChanged.connect(self._on_spinbox_depth_changed)
        self.bottom_spin.valueChanged.connect(self._on_spinbox_depth_changed)

    def _toggle_crossplots(self, group_box, checked: bool):
        """Toggle visibility of crossplots content."""
        for i in range(group_box.layout().count()):
            widget = group_box.layout().itemAt(i).widget()
            if widget:
                widget.setVisible(checked)
        if checked:
            group_box.setTitle("Crossplots")
            group_box.setFixedHeight(340)  # Header + 300px plots
        else:
            group_box.setTitle("Crossplots (click to expand)")
            group_box.setMaximumHeight(30)

    def _on_engine_changed(self, index: int):
        """Switch between interactive and classic plot engines."""
        if HAS_PYQTGRAPH:
            self.plot_stack.setCurrentIndex(index)
        else:
            self.plot_stack.setCurrentIndex(1)  # Always classic if no pyqtgraph

        # Refresh current view
        if self.model.calculated and self.model.results is not None:
            self._update_plot()

    def _on_spinbox_depth_changed(self):
        """Handle depth spinbox changes."""
        if self._updating_depth:
            return

        top = self.top_spin.value()
        bottom = self.bottom_spin.value()

        if top >= bottom:
            return

        # Update current viewer
        if self.plot_stack.currentIndex() == 0 and HAS_PYQTGRAPH:
            self._updating_depth = True
            self.interactive_log.set_depth_range(top, bottom)
            self._updating_depth = False
        else:
            self._update_classic_log()

        self.depth_selection_changed.emit(top, bottom)

    def _on_interactive_depth_changed(self, top: float, bottom: float):
        """Handle depth changes from interactive viewer."""
        if self._updating_depth:
            return

        self._updating_depth = True
        self.top_spin.setValue(top)
        self.bottom_spin.setValue(bottom)
        self._updating_depth = False

        self.depth_selection_changed.emit(top, bottom)

    def _on_region_selection_changed(self, top: float, bottom: float):
        """Handle region selection (drag) changes from interactive viewer."""
        if self._updating_depth:
            return

        self._updating_depth = True
        self.top_spin.setValue(top)
        self.bottom_spin.setValue(bottom)
        self._updating_depth = False

        self.depth_selection_changed.emit(top, bottom)

    def _on_show_tops_changed(self, state: int):
        """Toggle formation tops overlay."""
        if HAS_PYQTGRAPH and hasattr(self.interactive_log, "set_formation_tops"):
            if state:
                if self.model.formation_tops:
                    self.interactive_log.set_formation_tops(self.model.formation_tops)
            else:
                if hasattr(self.interactive_log, "clear_formation_tops"):
                    self.interactive_log.clear_formation_tops()

    def _on_show_hcpv_changed(self, state: int):
        """Toggle HCPV track visibility."""
        if self.model.calculated and self.model.results is not None:
            self._update_plot()

    def _on_hcpv_mode_changed(self, index: int):
        """Handle HCPV mode change."""
        if self.model.calculated and self.model.results is not None:
            self._update_plot()

    def _get_hcpv_curve_config(self, columns: list) -> list:
        """Get HCPV curve configuration based on selected mode."""
        if not self.show_hcpv_check.isChecked():
            return []

        mode = self.hcpv_mode_combo.currentText()

        if mode == "Net Pay":
            curves = []
            if "dHCPV_NET_PAY" in columns:
                curves.append(("dHCPV_NET_PAY", "#FF4500", False, None))
            if "HCPV_CUM_NET_PAY" in columns:
                curves.append(("HCPV_CUM_NET_PAY", "#228B22", False, None))
            return curves

        elif mode == "Net Reservoir":
            curves = []
            if "dHCPV_NET_RES" in columns:
                curves.append(("dHCPV_NET_RES", "#DAA520", False, None))
            if "HCPV_CUM_NET_RES" in columns:
                curves.append(("HCPV_CUM_NET_RES", "#4682B4", False, None))
            return curves

        elif mode == "Gross":
            curves = []
            if "dHCPV" in columns:
                curves.append(("dHCPV", "#FF6347", False, None))
            if "HCPV_CUM" in columns:
                curves.append(("HCPV_CUM", "#00CED1", False, None))
            return curves

        else:  # Fraction Only
            if "HCPV_FRAC" in columns:
                return [("HCPV_FRAC", "#FF8C00", False, (0, 0.5))]
            return []

    def _update_plot(self):
        """Update the current plot engine with data."""
        if self.plot_stack.currentIndex() == 0 and HAS_PYQTGRAPH:
            self._update_interactive_log()
        else:
            self._update_classic_log()

    def _update_interactive_log(self):
        """Update interactive pyqtgraph viewer."""
        if self.model.results is None:
            return

        # Get custom curve config with HCPV mode
        columns = self.model.results.columns.tolist()
        custom_config = None

        if hasattr(self, "show_hcpv_check"):
            # Build custom config including HCPV settings
            hcpv_curves = self._get_hcpv_curve_config(columns)
            # Always use custom config to properly control HCPV visibility
            default_config = self.interactive_log._default_curve_config(columns)
            default_config[5] = hcpv_curves  # Empty list if unchecked
            custom_config = default_config

        # Plot curves
        if custom_config:
            self.interactive_log.plot_curves(self.model.results, custom_config)
        else:
            self.interactive_log.plot_curves(self.model.results)

        # Add formation tops if enabled
        if self.show_tops_check.isChecked() and self.model.formation_tops:
            if hasattr(self.interactive_log, "set_formation_tops"):
                self.interactive_log.set_formation_tops(self.model.formation_tops)
            else:
                if hasattr(self.interactive_log, "clear_formation_tops"):
                    self.interactive_log.clear_formation_tops()

    def _update_classic_log(self):
        """Update classic matplotlib viewer."""
        if self.model.results is None:
            return

        top = self.top_spin.value()
        bottom = self.bottom_spin.value()

        # Get formation tops if checkbox enabled
        formation_tops = None
        if self.show_tops_check.isChecked() and self.model.formation_tops:
            formation_tops = self.model.formation_tops

        if top < bottom:
            self.classic_log.plot_petrophysics_summary(
                self.model.results,
                depth_range=(top, bottom),
                formation_tops=formation_tops,
            )
        else:
            self.classic_log.plot_petrophysics_summary(
                self.model.results, formation_tops=formation_tops
            )

    def update_display(self):
        """Update display with analysis results."""
        if not self.model.calculated or self.model.results is None:
            self.placeholder.setVisible(True)
            return

        self.placeholder.setVisible(False)

        results = self.model.results

        # Update depth range from data
        if "DEPTH" in results.columns:
            depth_min = float(results["DEPTH"].min())
            depth_max = float(results["DEPTH"].max())

            self._updating_depth = True
            self.top_spin.setRange(depth_min, depth_max)
            self.bottom_spin.setRange(depth_min, depth_max)
            self.top_spin.setValue(depth_min)
            self.bottom_spin.setValue(depth_max)
            self._updating_depth = False

        # Update current plot engine
        self._update_plot()

        # Update crossplots
        if "PHIN" in results.columns and "PHID" in results.columns:
            self.nd_crossplot.plot_crossplot(
                results["PHIN"],
                results["PHID"],
                color_data=results.get("VSH"),
                x_label="NPHI (v/v)",
                y_label="PHID (v/v)",
                title="Neutron-Density Crossplot",
                colorbar_label="Vsh",
            )

        if "PHIE" in results.columns and "PERM_TIMUR" in results.columns:
            import numpy as np

            perm_log = np.log10(results["PERM_TIMUR"].clip(0.001))
            self.pk_crossplot.plot_crossplot(
                results["PHIE"],
                perm_log,
                color_data=results.get("VSH"),
                x_label="PHIE (v/v)",
                y_label="log10(K) (mD)",
                title="Porosity-Permeability",
                colorbar_label="Vsh",
            )

    def get_current_depth_window(self) -> tuple:
        """Get the current depth selection for export."""
        return (self.top_spin.value(), self.bottom_spin.value())

    def is_interactive_mode(self) -> bool:
        """Check if interactive mode is active."""
        return HAS_PYQTGRAPH and self.plot_stack.currentIndex() == 0
