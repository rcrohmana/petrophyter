"""
Interactive Log Plot Widget for Petrophyter PyQt v1.2
Multi-track log display with zoom, pan, and crosshair features.
Uses pyqtgraph for better interactivity than Matplotlib.
"""

import time
import numpy as np
import pandas as pd
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QLabel,
    QCheckBox,
    QGroupBox,
    QScrollArea,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPen

try:
    import pyqtgraph as pg

    HAS_PYQTGRAPH = True
except Exception as e:
    print(f"Warning: Failed to import pyqtgraph: {e}")
    HAS_PYQTGRAPH = False
    pg = None


# Theme colors
_THEME_BG = "#F0EBE1"
_THEME_GRID = "#D0C9BC"

# Default curve colors
CURVE_COLORS = {
    "GR": "#00AA00",  # Green
    "VSH": "#8B4513",  # Brown
    "RHOB": "#FF0000",  # Red
    "NPHI": "#0000FF",  # Blue
    "DT": "#FF00FF",  # Magenta
    "RT": "#000000",  # Black
    "PHIE": "#1E90FF",  # Dodger Blue
    "PHID": "#FF6347",  # Tomato
    "PHIN": "#008B8B",  # Dark Cyan
    "SW": "#9400D3",  # Dark Violet
    "PERM": "#FFD700",  # Gold
    # HCPV colors
    "HCPV_FRAC": "#FF8C00",  # Dark Orange
    "dHCPV": "#FF6347",  # Tomato
    "HCPV_CUM": "#00CED1",  # Dark Cyan
    "dHCPV_NET_PAY": "#FF4500",  # Orange Red
    "HCPV_CUM_NET_PAY": "#228B22",  # Forest Green
    "dHCPV_NET_RES": "#DAA520",  # Goldenrod
    "HCPV_CUM_NET_RES": "#4682B4",  # Steel Blue
}


class InteractiveLogPlot(QWidget):
    """
    Interactive multi-track log display using pyqtgraph.

    Features:
    - Multiple synchronized tracks sharing Y-axis (depth)
    - Zoom/pan with mouse wheel and drag
    - Crosshair cursor with depth/value readout
    - Region depth selection (interval picking)
    - Formation tops overlay
    - Inverted Y-axis (depth increases downward)
    """

    depth_changed = pyqtSignal(float, float)  # (top, bottom)
    depth_region_changed = pyqtSignal(
        float, float
    )  # (top, bottom) from region selection
    cursor_moved = pyqtSignal(float, dict)  # (depth, {curve: value})

    def __init__(self, n_tracks: int = 6, parent=None):
        super().__init__(parent)
        self.n_tracks = n_tracks
        self.plot_widgets = []
        self.curves_data = {}
        self.curve_items = {}
        self.crosshairs = []
        self.depth_region = None  # LinearRegionItem for selection
        self.formation_lines = []  # InfiniteLine items for tops
        self.formation_labels = []  # TextItem items for tops
        self._depth_array = None  # Cached sorted depth array for fast lookup
        self._updating_region = False  # Guard for bi-directional sync
        self._last_mouse_update = 0  # Timestamp for throttling mouse updates
        self._mouse_throttle_ms = 33  # ~30 FPS limit (33ms between updates)

        self._setup_ui()

    def _setup_ui(self):
        """Setup the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(2)  # Reduce spacing between widgets

        if not HAS_PYQTGRAPH:
            # Fallback if pyqtgraph not installed
            fallback_label = QLabel(
                "⚠️ pyqtgraph not installed.\n"
                "Install with: pip install pyqtgraph\n"
                "Using static plots instead."
            )
            fallback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fallback_label.setStyleSheet("color: #CC6600; padding: 20px;")
            layout.addWidget(fallback_label)
            return

        # Configure pyqtgraph for optimal performance
        pg.setConfigOptions(
            antialias=True,
            useOpenGL=True,  # GPU acceleration (Radeon 880M compatible)
            enableExperimental=True,  # Experimental optimizations
        )

        # =====================================================================
        # PLOT AREA
        # =====================================================================
        self.graphics_layout = pg.GraphicsLayoutWidget()
        self.graphics_layout.setBackground(_THEME_BG)
        # Add bottom margin so axis labels don't get cut off by controls bar
        self.graphics_layout.ci.layout.setContentsMargins(0, 0, 0, 25)
        layout.addWidget(self.graphics_layout, stretch=1)

        # Create tracks
        self._create_tracks()

        # =====================================================================
        # CONTROLS BAR
        # =====================================================================
        controls = QFrame()
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(2, 2, 2, 2)

        # Depth readout
        self.depth_label = QLabel("Depth: -")
        self.depth_label.setMinimumWidth(120)
        controls_layout.addWidget(self.depth_label)

        # Value readout
        self.value_label = QLabel("")
        self.value_label.setMinimumWidth(300)
        controls_layout.addWidget(self.value_label)

        controls_layout.addStretch()

        # Reset view button
        from PyQt6.QtWidgets import QPushButton

        reset_btn = QPushButton("🔄 Reset View")
        reset_btn.clicked.connect(self.reset_view)
        controls_layout.addWidget(reset_btn)

        layout.addWidget(controls)

    def _create_tracks(self):
        """Create the plot tracks."""
        if not HAS_PYQTGRAPH:
            return

        # Track titles
        track_titles = ["GR/Vsh", "Porosity", "Sw", "Perm", "Flags", "HCPV"]

        self.plot_widgets = []

        for i in range(self.n_tracks):
            # Add plot to layout
            plot = self.graphics_layout.addPlot(row=0, col=i)

            # Configure plot
            plot.setTitle(
                track_titles[i] if i < len(track_titles) else f"Track {i + 1}"
            )
            plot.showGrid(x=True, y=True, alpha=0.3)
            plot.setLabel("left", "")

            # Invert Y-axis (depth increases downward)
            plot.invertY(True)

            # Set background via ViewBox
            plot.getViewBox().setBackgroundColor(_THEME_BG)

            # Link Y-axis to first track
            if i > 0 and len(self.plot_widgets) > 0:
                plot.setYLink(self.plot_widgets[0])

            # Add crosshair
            vLine = pg.InfiniteLine(
                angle=90, movable=False, pen=pg.mkPen("#888888", width=1)
            )
            hLine = pg.InfiniteLine(
                angle=0,
                movable=False,
                pen=pg.mkPen("#888888", width=1, style=Qt.PenStyle.DashLine),
            )
            plot.addItem(vLine, ignoreBounds=True)
            plot.addItem(hLine, ignoreBounds=True)
            self.crosshairs.append((vLine, hLine))

            # Add depth region selector to first track only
            if i == 0:
                self.depth_region = pg.LinearRegionItem(
                    orientation="horizontal",
                    brush=pg.mkBrush(100, 150, 200, 50),
                    movable=True,
                )
                self.depth_region.setZValue(-10)  # Behind curves
                plot.addItem(self.depth_region)
                self.depth_region.sigRegionChanged.connect(self._on_region_changed)

                # Connect zoom/pan to emit depth_changed
                plot.getViewBox().sigRangeChanged.connect(self._on_view_range_changed)

            self.plot_widgets.append(plot)

        # Connect mouse move signal ONCE (not per track) - critical for performance
        if self.plot_widgets:
            self.plot_widgets[0].scene().sigMouseMoved.connect(self._on_mouse_moved)

    def _on_mouse_moved(self, pos):
        """Handle mouse movement for crosshair (throttled for performance)."""
        if not HAS_PYQTGRAPH or not self.plot_widgets:
            return

        # Throttle updates to ~30 FPS to reduce CPU usage
        current_time = time.time() * 1000  # Convert to milliseconds
        if current_time - self._last_mouse_update < self._mouse_throttle_ms:
            return
        self._last_mouse_update = current_time

        # Find which plot contains the mouse
        for i, plot in enumerate(self.plot_widgets):
            if plot.sceneBoundingRect().contains(pos):
                mousePoint = plot.getViewBox().mapSceneToView(pos)
                depth = mousePoint.y()
                x_val = mousePoint.x()

                # Update all crosshairs
                for j, (vLine, hLine) in enumerate(self.crosshairs):
                    if j == i:
                        vLine.setPos(x_val)
                    hLine.setPos(depth)

                # Update depth label
                self.depth_label.setText(f"Depth: {depth:.1f} ft")

                # Get values at this depth
                values = self._get_values_at_depth(depth)
                if values:
                    val_str = " | ".join(
                        [f"{k}: {v:.3f}" for k, v in values.items() if not np.isnan(v)]
                    )
                    self.value_label.setText(val_str[:80])  # Truncate if too long

                self.cursor_moved.emit(depth, values)
                break

    def plot_curves(self, data: pd.DataFrame, curve_config: dict = None):
        """
        Plot curves on the tracks.

        Args:
            data: DataFrame with DEPTH and curve columns
            curve_config: dict mapping track_index -> [(curve_name, color, log_scale, [range]), ...]
        """
        if not HAS_PYQTGRAPH or "DEPTH" not in data.columns:
            return

        self.clear()

        depth = data["DEPTH"].values

        # Default configuration if not provided
        if curve_config is None:
            curve_config = self._default_curve_config(data.columns.tolist())

        # Plot each track
        for track_idx, curves in curve_config.items():
            if track_idx >= len(self.plot_widgets):
                continue

            plot = self.plot_widgets[track_idx]

            for curve_info in curves:
                # Handle both 3-tuple and 4-tuple formats
                if len(curve_info) == 4:
                    curve_name, color, log_scale, value_range = curve_info
                else:
                    curve_name, color, log_scale = curve_info[:3]

                if curve_name in data.columns:
                    curve_data = data[curve_name].values.copy()

                    # Store original data for crosshair lookup
                    self.curves_data[curve_name] = (depth, data[curve_name].values)

                    # Create pen
                    pen = pg.mkPen(color, width=1.5)

                    # Apply transformations
                    if log_scale:
                        # Use log scale for resistivity/perm
                        curve_data = np.log10(np.maximum(curve_data, 0.001))
                    elif value_range is not None:
                        # Normalize to 0-1 range for display
                        vmin, vmax = value_range
                        curve_data = (curve_data - vmin) / (vmax - vmin)

                    curve_item = plot.plot(curve_data, depth, pen=pen, name=curve_name)
                    self.curve_items[curve_name] = curve_item

            # Set X range for normalized tracks (0-1), skip log scale tracks
            if track_idx in [0, 1, 2, 4]:  # All normalized tracks
                plot.setXRange(0, 1, padding=0.02)

        # Auto-range Y only on first track (others are linked)
        if self.plot_widgets:
            self.plot_widgets[0].enableAutoRange(axis="y")
            # Disable Y auto-range on linked tracks to prevent conflicts
            for plot in self.plot_widgets[1:]:
                plot.disableAutoRange(axis="y")

    def _default_curve_config(self, columns: list) -> dict:
        """Generate default curve configuration."""
        config = {}

        # Track 0: GR (normalized to 0-1) and Vsh
        # Note: GR is normalized to 0-1 range for display with VSH
        track0 = []
        if "GR" in columns:
            track0.append(
                ("GR", CURVE_COLORS["GR"], False, (0, 150))
            )  # GR normalized 0-150 → 0-1
        if "VSH" in columns:
            track0.append(("VSH", CURVE_COLORS["VSH"], False, (0, 1)))
        config[0] = track0

        # Track 1: Porosity (0-0.5 range)
        track1 = []
        for c in ["PHIE", "PHID", "PHIN", "PHIT"]:
            if c in columns:
                track1.append((c, CURVE_COLORS.get(c, "#1E90FF"), False, (0, 0.5)))
        config[1] = track1

        # Track 2: Water Saturation (0-1 range)
        track2 = []
        for c in ["SW", "SW_ARCHIE", "SW_INDO"]:
            if c in columns:
                track2.append((c, CURVE_COLORS.get("SW", "#9400D3"), False, (0, 1)))
                break
        config[2] = track2

        # Track 3: Permeability (log scale, no normalization)
        track3 = []
        for c in ["PERM", "PERM_TIMUR", "PERM_COATES"]:
            if c in columns:
                track3.append((c, CURVE_COLORS.get("PERM", "#FFD700"), True, None))
                break
        config[3] = track3

        # Track 4: Pay Flags (0-1 range) - use correct column names
        track4 = []
        if "NET_PAY_FLAG" in columns:
            track4.append(("NET_PAY_FLAG", "#228B22", False, (0, 1)))  # Green for Pay
        if "NET_RES_FLAG" in columns:
            track4.append(("NET_RES_FLAG", "#FFD700", False, (0, 1)))  # Yellow for Res
        config[4] = track4

        # Track 5: HCPV (dHCPV + HCPV_CUM)
        # Default: Net Pay version. Toggle available for Gross.
        track5 = []
        # Default curves - Net Pay version
        if "dHCPV_NET_PAY" in columns:
            track5.append(
                ("dHCPV_NET_PAY", "#FF4500", False, None)
            )  # Orange Red - auto scale
        if "HCPV_CUM_NET_PAY" in columns:
            track5.append(
                ("HCPV_CUM_NET_PAY", "#228B22", False, None)
            )  # Forest Green - auto scale
        # Fallback to gross if net pay not available
        if not track5:
            if "dHCPV" in columns:
                track5.append(("dHCPV", "#FF6347", False, None))  # Tomato
            if "HCPV_CUM" in columns:
                track5.append(("HCPV_CUM", "#00CED1", False, None))  # Dark Cyan
        config[5] = track5

        return config

    def clear(self):
        """Clear all curves from the plot."""
        if not HAS_PYQTGRAPH:
            return

        for i, plot in enumerate(self.plot_widgets):
            plot.clear()
            # Re-add crosshairs
            vLine = pg.InfiniteLine(
                angle=90, movable=False, pen=pg.mkPen("#888888", width=1)
            )
            hLine = pg.InfiniteLine(
                angle=0,
                movable=False,
                pen=pg.mkPen("#888888", width=1, style=Qt.PenStyle.DashLine),
            )
            plot.addItem(vLine, ignoreBounds=True)
            plot.addItem(hLine, ignoreBounds=True)

            # Re-add depth region to first track
            if i == 0 and self.depth_region is not None:
                plot.addItem(self.depth_region)

        self.curves_data.clear()
        self.curve_items.clear()
        self._depth_array = None
        self.clear_formation_tops()

    def reset_view(self):
        """Reset all plots to auto-range."""
        if not HAS_PYQTGRAPH:
            return

        for plot in self.plot_widgets:
            plot.enableAutoRange()

    def set_depth_range(self, top: float, bottom: float):
        """Set the visible depth range."""
        if not HAS_PYQTGRAPH or not self.plot_widgets:
            return

        self._updating_region = True
        self.plot_widgets[0].setYRange(top, bottom)
        if self.depth_region:
            self.depth_region.setRegion([top, bottom])
        self._updating_region = False
        self.depth_changed.emit(top, bottom)

    def set_region(self, top: float, bottom: float):
        """Set the depth region selection programmatically."""
        if not HAS_PYQTGRAPH or not self.depth_region:
            return

        self._updating_region = True
        self.depth_region.setRegion([top, bottom])
        self._updating_region = False

    def get_region(self) -> tuple:
        """Get the current depth region selection."""
        if not HAS_PYQTGRAPH or not self.depth_region:
            return (0, 0)
        region = self.depth_region.getRegion()
        return (float(min(region)), float(max(region)))

    def _on_region_changed(self):
        """Handle depth region drag."""
        if self._updating_region or not self.depth_region:
            return

        region = self.depth_region.getRegion()
        top = float(min(region))
        bottom = float(max(region))
        self.depth_region_changed.emit(top, bottom)

    def _on_view_range_changed(self, viewbox, ranges):
        """Handle zoom/pan on viewbox."""
        if self._updating_region:
            return

        # ranges is [[xmin, xmax], [ymin, ymax]]
        if len(ranges) >= 2:
            y_range = ranges[1]
            top = float(min(y_range))
            bottom = float(max(y_range))
            self.depth_changed.emit(top, bottom)

    # =========================================================================
    # FORMATION TOPS OVERLAY (M3)
    # =========================================================================

    def set_formation_tops(self, tops):
        """
        Set formation tops overlay.

        Args:
            tops: FormationTops object or list of dict {name, top_depth, bottom_depth(optional)}
        """
        if not HAS_PYQTGRAPH or not self.plot_widgets:
            return

        self.clear_formation_tops()

        # Convert FormationTops object to list
        tops_list = []
        if hasattr(tops, "formations") and isinstance(tops.formations, list):
            # FormationTops object with formations: List[Formation]
            for fm in tops.formations:
                tops_list.append(
                    {
                        "name": fm.name,
                        "top_depth": fm.top_depth,
                        "bottom_depth": fm.bottom_depth,
                    }
                )
        elif hasattr(tops, "tops") and isinstance(tops.tops, dict):
            # Legacy format: tops dict
            for name, (top_depth, bottom_depth) in tops.tops.items():
                tops_list.append(
                    {"name": name, "top_depth": top_depth, "bottom_depth": bottom_depth}
                )
        elif isinstance(tops, list):
            tops_list = tops
        elif isinstance(tops, dict):
            for name, depths in tops.items():
                if isinstance(depths, tuple) and len(depths) >= 2:
                    tops_list.append(
                        {
                            "name": name,
                            "top_depth": depths[0],
                            "bottom_depth": depths[1],
                        }
                    )

        if not tops_list:
            return

        # Add lines and labels to first track
        plot = self.plot_widgets[0]

        for top in tops_list:
            name = top.get("name", "")
            top_depth = top.get("top_depth", 0)

            # Create horizontal line at top_depth
            line = pg.InfiniteLine(
                pos=top_depth,
                angle=0,
                movable=False,
                pen=pg.mkPen("#FF6600", width=2, style=Qt.PenStyle.DashLine),
            )
            plot.addItem(line)
            self.formation_lines.append(line)

            # Create label
            label = pg.TextItem(name, color="#FF6600", anchor=(0, 1))
            label.setPos(0, top_depth)
            plot.addItem(label)
            self.formation_labels.append(label)

    def clear_formation_tops(self):
        """Clear all formation tops overlay."""
        if not HAS_PYQTGRAPH or not self.plot_widgets:
            return

        plot = self.plot_widgets[0]

        for line in self.formation_lines:
            try:
                plot.removeItem(line)
            except:
                pass

        for label in self.formation_labels:
            try:
                plot.removeItem(label)
            except:
                pass

        self.formation_lines.clear()
        self.formation_labels.clear()

    # =========================================================================
    # PERFORMANCE OPTIMIZATIONS
    # =========================================================================

    def _get_values_at_depth(self, depth: float) -> dict:
        """Get curve values at specified depth (optimized with searchsorted)."""
        values = {}

        for curve_name, (depth_data, curve_data) in self.curves_data.items():
            if len(depth_data) > 0:
                # Use cached sorted indices for faster lookup
                if self._depth_array is None or len(self._depth_array) != len(
                    depth_data
                ):
                    self._depth_array = np.array(depth_data)

                idx = np.searchsorted(self._depth_array, depth)
                idx = min(idx, len(curve_data) - 1)
                if idx < len(curve_data):
                    values[curve_name] = float(curve_data[idx])

        return values
