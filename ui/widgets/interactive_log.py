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

from themes.colors import get_plot_chrome, get_plot_color
from themes.helpers import set_status
from themes.icon_loader import get_icon
from themes.tokens import PLOT_COLORS

from . import track_specs as ts

try:
    import pyqtgraph as pg

    HAS_PYQTGRAPH = True
except Exception as e:
    print(f"Warning: Failed to import pyqtgraph: {e}")
    HAS_PYQTGRAPH = False
    pg = None


if HAS_PYQTGRAPH:

    class RealValueAxis(pg.AxisItem):
        """Axis of a normalised track whose ticks read in real curve values.

        The curves are plotted on a 0-1 display range for speed; ``set_real_ticks``
        gives the axis the ``(position, label)`` pairs of the real scale (for a
        log track 0.1, 1, 10, 100, 1000). With no ticks set it behaves like a
        normal axis.
        """

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._real_ticks = None

        def set_real_ticks(self, ticks):
            self._real_ticks = list(ticks) if ticks else None
            self.picture = None
            self.update()

        def real_ticks(self):
            return list(self._real_ticks) if self._real_ticks else []

        def tickValues(self, minVal, maxVal, size):
            if self._real_ticks is None:
                return super().tickValues(minVal, maxVal, size)
            lo, hi = min(minVal, maxVal), max(minVal, maxVal)
            eps = 1e-9
            return [(1.0, [p for p, _ in self._real_ticks if lo - eps <= p <= hi + eps])]

        def tickStrings(self, values, scale, spacing):
            if self._real_ticks is None:
                return super().tickStrings(values, scale, spacing)
            labels = []
            for v in values:
                text = ""
                for pos, label in self._real_ticks:
                    if abs(pos - v) < 1e-6:
                        text = label
                        break
                labels.append(text)
            return labels

else:  # pragma: no cover - pyqtgraph missing
    RealValueAxis = None


# Interactive track index -> track spec (track 3 shows resistivity on the bottom
# axis and permeability on the top axis).
TRACK_SPEC_KEYS = {0: "gr_vsh", 1: "porosity", 2: "sw", 3: "resistivity"}


# Deprecated module aliases retained for callers that imported these names.
_THEME_BG = get_plot_chrome("light")["figure"]
_THEME_GRID = get_plot_chrome("light")["grid"]

# Compatibility mapping for theme-invariant curve colors. RT is resolved at
# configuration/refresh time because dark mode intentionally overrides it.
CURVE_COLORS = {
    name: get_plot_color(name, "light")
    for name in (
        "GR", "VSH", "RHOB", "NPHI", "DT", "PHIE", "PHID", "PHIN",
        "PHIT", "SW", "PERM", "PAY", "HCPV_FRAC", "dHCPV", "HCPV_CUM",
        "dHCPV_NET_PAY", "HCPV_CUM_NET_PAY", "dHCPV_NET_RES",
        "HCPV_CUM_NET_RES",
    )
}


def _selection_brush():
    """Translucent depth-region brush derived from the theme selection token."""
    color = QColor(get_plot_chrome()["selection"])
    color.setAlpha(50)
    return pg.mkBrush(color)


def _current_curve_color(curve_name: str) -> str:
    """Resolve a curve color against the current theme at draw time."""
    if curve_name not in PLOT_COLORS:
        return get_plot_color("SW_DEFAULT")
    return get_plot_color(curve_name)


def _curve_pen(curve_name: str, dashed: bool = False):
    style = Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine
    return pg.mkPen(_current_curve_color(curve_name), width=1.5, style=style)


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
        self.curve_units = {}  # curve name -> unit, for the crosshair readout
        self.curve_labels = {}  # curve name -> legend label
        self._dashed = set()  # curves drawn dashed (non-primary Sw)
        self.crosshairs = []
        self.depth_region = None  # LinearRegionItem for selection
        self.formation_lines = []  # InfiniteLine items for tops
        self.formation_labels = []  # TextItem items for tops
        self._depth_array = None  # Cached sorted depth array for fast lookup
        self._updating_region = False  # Guard for bi-directional sync
        self._last_mouse_update = 0  # Timestamp for throttling mouse updates
        self._mouse_throttle_ms = 33  # ~30 FPS limit (33ms between updates)
        self._chrome = get_plot_chrome()

        self._setup_ui()
        self.refresh_theme()

    def _setup_ui(self):
        """Setup the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(2)  # Reduce spacing between widgets

        if not HAS_PYQTGRAPH:
            # Fallback if pyqtgraph not installed
            fallback_label = QLabel(
                "pyqtgraph not installed.\n"
                "Install with: pip install pyqtgraph\n"
                "Using static plots instead."
            )
            fallback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            set_status(fallback_label, "warning")
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
        self.graphics_layout.setBackground(self._chrome["figure"])
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
        self.depth_label.setObjectName("SubsectionLabel")
        self.depth_label.setMinimumWidth(120)
        controls_layout.addWidget(self.depth_label)

        # Value readout
        self.value_label = QLabel("")
        self.value_label.setObjectName("SubsectionLabel")
        self.value_label.setWordWrap(True)
        self.value_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        controls_layout.addWidget(self.value_label, stretch=1)

        # Reset view button
        from PyQt6.QtWidgets import QPushButton

        self.reset_btn = QPushButton("Reset View")
        self.reset_btn.setIcon(get_icon("refresh-cw"))
        self.reset_btn.clicked.connect(self.reset_view)
        controls_layout.addWidget(self.reset_btn)

        layout.addWidget(controls)

    def refresh_theme(self):
        """Apply theme-aware plot chrome while keeping curve colors stable."""
        self._chrome = get_plot_chrome()
        if hasattr(self, "reset_btn"):  # refresh_theme also runs during __init__
            self.reset_btn.setIcon(get_icon("refresh-cw"))
        if not HAS_PYQTGRAPH or not self.plot_widgets:
            return

        self.graphics_layout.setBackground(self._chrome["figure"])
        for plot in self.plot_widgets:
            plot.getViewBox().setBackgroundColor(self._chrome["axes"])
            for axis_name in ("left", "bottom", "top", "right"):
                axis = plot.getAxis(axis_name)
                axis.setPen(pg.mkPen(self._chrome["spine"]))
                axis.setTextPen(pg.mkPen(self._chrome["text"]))
        for plot in self.plot_widgets:
            plot.titleLabel.setText(plot.titleLabel.text, color=self._chrome["text"])
            legend = getattr(plot, "legend", None)
            if legend is not None:
                legend.setBrush(pg.mkBrush(self._chrome["axes"]))
                legend.setLabelTextColor(self._chrome["text"])
        for line in self.formation_lines:
            line.setPen(
                pg.mkPen(
                    get_plot_color("FORMATION_TOP"),
                    width=2,
                    style=Qt.PenStyle.DashLine,
                )
            )
        for v_line, h_line in self.crosshairs:
            v_line.setPen(pg.mkPen(self._chrome["crosshair"], width=1))
            h_line.setPen(
                pg.mkPen(
                    self._chrome["crosshair"], width=1, style=Qt.PenStyle.DashLine
                )
            )
        if self.depth_region is not None:
            self.depth_region.setBrush(_selection_brush())
        for curve_name, curve_item in self.curve_items.items():
            if curve_name in CURVE_COLORS or curve_name == "RT":
                curve_item.setPen(_curve_pen(curve_name, curve_name in self._dashed))

    def _create_tracks(self):
        """Create the plot tracks."""
        if not HAS_PYQTGRAPH:
            return

        # Track titles
        track_titles = ["GR/Vsh", "Porosity", "Sw", "RT/Perm", "Flags", "HCPV"]

        self.plot_widgets = []

        for i in range(self.n_tracks):
            # Add plot to layout
            plot = self.graphics_layout.addPlot(
                row=0,
                col=i,
                axisItems={
                    "bottom": RealValueAxis("bottom"),
                    "top": RealValueAxis("top"),
                },
            )
            plot.hideAxis("top")
            plot.addLegend(offset=(4, 4))

            # Configure plot
            plot.setTitle(
                track_titles[i] if i < len(track_titles) else f"Track {i + 1}",
                color=self._chrome["text"],
            )
            plot.showGrid(x=True, y=True, alpha=0.3)
            plot.setLabel("left", "")

            # Invert Y-axis (depth increases downward)
            plot.invertY(True)

            # Set background via ViewBox
            plot.getViewBox().setBackgroundColor(self._chrome["axes"])

            # Link Y-axis to first track
            if i > 0 and len(self.plot_widgets) > 0:
                plot.setYLink(self.plot_widgets[0])

            # Add crosshair
            vLine = pg.InfiniteLine(
                angle=90,
                movable=False,
                pen=pg.mkPen(self._chrome["crosshair"], width=1),
            )
            hLine = pg.InfiniteLine(
                angle=0,
                movable=False,
                pen=pg.mkPen(
                    self._chrome["crosshair"],
                    width=1,
                    style=Qt.PenStyle.DashLine,
                ),
            )
            plot.addItem(vLine, ignoreBounds=True)
            plot.addItem(hLine, ignoreBounds=True)
            self.crosshairs.append((vLine, hLine))

            # Add depth region selector to first track only
            if i == 0:
                self.depth_region = pg.LinearRegionItem(
                    orientation="horizontal",
                    brush=_selection_brush(),
                    movable=True,
                )
                self.depth_region.setZValue(-10)  # Behind curves
                # ignoreBounds: the default [0, 1] region must not pull auto-range to depth 0
                plot.addItem(self.depth_region, ignoreBounds=True)
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
                    self.value_label.setText(self.format_readout(values))

                self.cursor_moved.emit(depth, values)
                break

    def format_readout(self, values: dict) -> str:
        """Readout of every curve with its unit; the label wraps, nothing is cut."""
        return ts.readout_text(values, self.curve_units)

    def plot_curves(self, data: pd.DataFrame, curve_config: dict = None):
        """
        Plot curves on the tracks.

        Args:
            data: DataFrame with DEPTH and curve columns
            curve_config: dict mapping track_index ->
                [(curve_name, color, log_scale, [range], [opts]), ...]
                ``opts`` (dict, optional) carries what the track specs define:
                ``label``, ``unit``, ``lo``, ``hi``, ``scale``, ``axis``
                ("bottom"/"top"), ``axis_label``, ``dashed``, ``sw_primary``,
                ``sw_other``. Curves with ``lo``/``hi`` are normalised to 0-1
                and their axis shows the real values.
        """
        if not HAS_PYQTGRAPH or "DEPTH" not in data.columns:
            return

        # searchsorted-based cursor lookup requires monotonically increasing depth.
        data = data.sort_values("DEPTH", kind="stable")
        self.clear()

        depth = data["DEPTH"].values

        # Default configuration if not provided
        if curve_config is None:
            curve_config = self._default_curve_config(data.columns.tolist())

        sw_model = ts.primary_sw_model(data)

        # Plot each track
        for track_idx, curves in curve_config.items():
            if track_idx >= len(self.plot_widgets):
                continue

            plot = self.plot_widgets[track_idx]
            axes_used = {}  # "bottom"/"top" -> (lo, hi, scale, label)
            spec_normalised = False

            for curve_info in curves:
                curve_name, color, log_scale = curve_info[:3]
                value_range = curve_info[3] if len(curve_info) > 3 else None
                opts = curve_info[4] if len(curve_info) > 4 else {}

                if curve_name in CURVE_COLORS or curve_name == "RT":
                    color = _current_curve_color(curve_name)

                if curve_name not in data.columns:
                    continue
                if opts.get("sw_other") and "SW" in data.columns:
                    # The primary's own source column would only repeat the solid line.
                    if np.allclose(
                        data[curve_name].values.astype(float),
                        data["SW"].values.astype(float),
                        equal_nan=True,
                    ):
                        continue

                raw = data[curve_name].values
                curve_data = raw.astype(float).copy()
                dashed = bool(opts.get("dashed"))
                label = opts.get("label") or curve_name
                if opts.get("sw_primary"):
                    label = ts.sw_primary_label(sw_model)

                # Store original data for crosshair lookup
                self.curves_data[curve_name] = (depth, raw)
                self.curve_units[curve_name] = opts.get("unit", "")
                self.curve_labels[curve_name] = label

                if "lo" in opts and "hi" in opts:
                    # Normalised display; the axis carries the real scale.
                    scale = opts.get("scale", "linear")
                    curve_data = ts.normalize(curve_data, opts["lo"], opts["hi"], scale)
                    spec_normalised = True
                    axes_used.setdefault(
                        opts.get("axis", "bottom"),
                        (opts["lo"], opts["hi"], scale, opts.get("axis_label", label)),
                    )
                elif log_scale:
                    # Legacy log display (curves without a track spec)
                    curve_data = np.log10(np.maximum(curve_data, 0.001))
                elif value_range is not None:
                    # Normalize to 0-1 range for display
                    vmin, vmax = value_range
                    curve_data = (curve_data - vmin) / (vmax - vmin)

                style = Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine
                pen = pg.mkPen(color, width=1.5, style=style)
                if dashed:
                    self._dashed.add(curve_name)
                curve_item = plot.plot(curve_data, depth, pen=pen, name=label)
                self.curve_items[curve_name] = curve_item

            self._apply_track_axes(plot, axes_used)

            # Set X range for normalized tracks (0-1)
            if spec_normalised or track_idx in [0, 1, 2, 4]:
                plot.setXRange(0, 1, padding=0.02)

        # Auto-range Y only on first track (others are linked)
        if self.plot_widgets:
            self.plot_widgets[0].enableAutoRange(axis="y")
            # Disable Y auto-range on linked tracks to prevent conflicts
            for plot in self.plot_widgets[1:]:
                plot.disableAutoRange(axis="y")

    def _apply_track_axes(self, plot, axes_used: dict):
        """Give a track's axes real-value ticks and labels (or reset them)."""
        for side in ("bottom", "top"):
            axis = plot.getAxis(side)
            if not isinstance(axis, RealValueAxis):
                continue
            if side in axes_used:
                lo, hi, scale, label = axes_used[side]
                axis.set_real_ticks(ts.axis_ticks(lo, hi, scale))
                plot.setLabel(side, label)
                if side == "top":
                    plot.showAxis("top", True)
            else:
                axis.set_real_ticks(None)
                plot.setLabel(side, "")
                if side == "top":
                    plot.hideAxis("top")

    @staticmethod
    def _spec_curve(track: str, name: str, **extra):
        """Curve-config entry for ``name`` of the track spec ``track``."""
        spec = ts.TRACK_SPECS[track]
        cs = ts.curve_spec(track, name)
        opts = {
            "label": f"{name} ({cs.unit})",
            "unit": cs.unit,
            "lo": cs.lo,
            "hi": cs.hi,
            "scale": cs.scale,
            "axis": "top" if cs.secondary else "bottom",
            "axis_label": (
                ts.axis_label(name, cs.unit, cs.scale) if cs.secondary else spec.axis_label
            ),
        }
        opts.update(extra)
        return (name, _current_curve_color(name), cs.scale == "log", (cs.lo, cs.hi), opts)

    def _default_curve_config(self, columns: list) -> dict:
        """Generate the default curve configuration from the shared track specs."""
        config = {}
        cols = list(columns)

        # Track 0: GR (bottom axis, API) and Vsh (top axis, v/v)
        config[0] = [self._spec_curve("gr_vsh", n) for n in ts.present_curves("gr_vsh", cols)]

        # Track 1: Porosity, reversed 0.5-0 v/v
        config[1] = [
            self._spec_curve("porosity", n) for n in ts.porosity_plot_curves(cols)
        ]

        # Track 2: Sw. SW is the effective (primary) curve; other SW_* are dashed.
        track2 = []
        if "SW" in cols:
            track2.append(self._spec_curve("sw", "SW", sw_primary=True))
        for c in ts.sw_method_columns(cols):
            track2.append(
                (
                    c,
                    _current_curve_color(c),
                    False,
                    (0.0, 1.0),
                    {
                        "label": f"Sw — {ts.sw_method_name(c)}",
                        "unit": "v/v",
                        "lo": 0.0,
                        "hi": 1.0,
                        "scale": "linear",
                        "axis": "bottom",
                        "axis_label": ts.TRACK_SPECS["sw"].axis_label,
                        "dashed": True,
                        "sw_other": True,
                    },
                )
            )
        config[2] = track2

        # Track 3: Resistivity (bottom axis, log) and permeability (top axis, log)
        track3 = [
            self._spec_curve("resistivity", n)
            for n in ts.present_curves("resistivity", cols)
        ]
        perm_label = ts.TRACK_SPECS["permeability"].axis_label
        for c in ts.present_curves("permeability", cols):
            track3.append(
                self._spec_curve("permeability", c, axis="top", axis_label=perm_label)
            )
        config[3] = track3

        # Track 4: Pay Flags (0-1 range) - use correct column names
        track4 = []
        if "NET_PAY_FLAG" in columns:
            track4.append(("NET_PAY_FLAG", get_plot_color("PAY"), False, (0, 1)))
        if "NET_RES_FLAG" in columns:
            track4.append(("NET_RES_FLAG", get_plot_color("RESERVOIR"), False, (0, 1)))
        config[4] = track4

        # Track 5: HCPV (dHCPV + HCPV_CUM)
        # Default: Net Pay version. Toggle available for Gross.
        track5 = []
        # Default curves - Net Pay version
        if "dHCPV_NET_PAY" in columns:
            track5.append(
                ("dHCPV_NET_PAY", get_plot_color("dHCPV_NET_PAY"), False, None)
            )  # Orange Red - auto scale
        if "HCPV_CUM_NET_PAY" in columns:
            track5.append(
                ("HCPV_CUM_NET_PAY", get_plot_color("HCPV_CUM_NET_PAY"), False, None)
            )  # Forest Green - auto scale
        # Fallback to gross if net pay not available
        if not track5:
            if "dHCPV" in columns:
                track5.append(("dHCPV", get_plot_color("dHCPV"), False, None))
            if "HCPV_CUM" in columns:
                track5.append(("HCPV_CUM", get_plot_color("HCPV_CUM"), False, None))
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
                angle=90,
                movable=False,
                pen=pg.mkPen(self._chrome["crosshair"], width=1),
            )
            hLine = pg.InfiniteLine(
                angle=0,
                movable=False,
                pen=pg.mkPen(
                    self._chrome["crosshair"],
                    width=1,
                    style=Qt.PenStyle.DashLine,
                ),
            )
            plot.addItem(vLine, ignoreBounds=True)
            plot.addItem(hLine, ignoreBounds=True)
            self.crosshairs[i] = (vLine, hLine)

            # Re-add depth region to first track
            if i == 0 and self.depth_region is not None:
                plot.addItem(self.depth_region, ignoreBounds=True)

        for plot in self.plot_widgets:
            for side in ("bottom", "top"):
                axis = plot.getAxis(side)
                if isinstance(axis, RealValueAxis):
                    axis.set_real_ticks(None)
            plot.hideAxis("top")
        self.curves_data.clear()
        self.curve_items.clear()
        self.curve_units.clear()
        self.curve_labels.clear()
        self._dashed.clear()
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
                pen=pg.mkPen(
                    get_plot_color("FORMATION_TOP"),
                    width=2,
                    style=Qt.PenStyle.DashLine,
                ),
            )
            plot.addItem(line)
            self.formation_lines.append(line)

            # Create label
            label = pg.TextItem(
                name, color=get_plot_color("FORMATION_TOP"), anchor=(0, 1)
            )
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
