"""
Plot Widget for Petrophyter PyQt
Matplotlib/pyqtgraph wrapper for plotting.
"""

import os
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QIcon, QPalette, QColor
import matplotlib

matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import numpy as np
import pandas as pd
from typing import Optional, List, Tuple, Dict

# Get icons directory path
_ICONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "icons"
)

# Theme colors - DARKER THEME
_THEME_SURFACE = QColor("#F0EBE1")


class PlotWidget(QWidget):
    """
    Widget for displaying Matplotlib plots.
    Provides a canvas and optional toolbar for interactive plots.
    """

    def __init__(
        self, parent=None, show_toolbar: bool = True, figsize: Tuple[int, int] = (8, 6)
    ):
        super().__init__(parent)

        # Fixed theme colors for consistent appearance - DARKER THEME
        self._bg_color = "#F0EBE1"
        self._axes_color = "#F0EBE1"

        # Set figure with theme background
        self.figure = Figure(figsize=figsize, dpi=100, facecolor=self._bg_color)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setStyleSheet(f"background-color: {self._bg_color};")
        self.canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        # Set canvas palette to theme color (fixes debug mode detection)
        canvas_palette = self.canvas.palette()
        canvas_palette.setColor(QPalette.ColorRole.Window, _THEME_SURFACE)
        canvas_palette.setColor(QPalette.ColorRole.Base, _THEME_SURFACE)
        self.canvas.setPalette(canvas_palette)
        self.canvas.setAutoFillBackground(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if show_toolbar:
            self.toolbar = NavigationToolbar(self.canvas, self)

            # Set toolbar palette to theme color
            toolbar_palette = self.toolbar.palette()
            toolbar_palette.setColor(QPalette.ColorRole.Window, _THEME_SURFACE)
            toolbar_palette.setColor(QPalette.ColorRole.Base, _THEME_SURFACE)
            self.toolbar.setPalette(toolbar_palette)
            self.toolbar.setAutoFillBackground(True)

            # Force toolbar and all actions enabled to prevent pale/disabled icons
            self.toolbar.setEnabled(True)
            for action in self.toolbar.actions():
                action.setEnabled(True)

            # Style toolbar with explicit foreground color for icon visibility
            self.toolbar.setStyleSheet("""
                QToolBar {
                    background-color: #F0EBE1;
                    border: 1px solid #C9C0B0;
                    border-radius: 4px;
                    spacing: 3px;
                    padding: 4px;
                }
                QToolButton {
                    color: #111;
                    background-color: transparent;
                    border: 1px solid transparent;
                    border-radius: 4px;
                    padding: 4px;
                    margin: 1px;
                }
                QToolButton:hover {
                    background-color: rgba(0,0,0,0.06);
                    border-color: #CCCCCC;
                }
                QToolButton:pressed {
                    background-color: rgba(0,0,0,0.1);
                }
                QToolButton:checked {
                    background-color: rgba(0,0,0,0.1);
                    border-color: #AAAAAA;
                }
                QToolButton:disabled {
                    color: #777;
                }
            """)

            # Override toolbar icons with custom dark SVG icons for visibility
            self._apply_custom_toolbar_icons()

            layout.addWidget(self.toolbar)
        else:
            self.toolbar = None

        layout.addWidget(self.canvas)

    def update_theme_colors(self):
        """Update plot colors to match theme."""
        # Use fixed theme color, not dynamic palette - DARKER THEME
        self._bg_color = "#F0EBE1"
        self.figure.set_facecolor(self._bg_color)
        self.canvas.setStyleSheet(f"background-color: {self._bg_color};")
        for ax in self.figure.axes:
            ax.set_facecolor(self._axes_color)
        self.canvas.draw_idle()

    def _apply_custom_toolbar_icons(self):
        """Override Matplotlib toolbar icons with custom dark SVG icons."""
        if self.toolbar is None:
            return

        for action in self.toolbar.actions():
            action_text = action.text().lower()
            action_tooltip = action.toolTip().lower()

            # Determine which icon to use based on action text/tooltip
            icon_file = None

            if "home" in action_text or "home" in action_tooltip:
                icon_file = "home.svg"
            elif "back" in action_text or "back" in action_tooltip:
                icon_file = "back.svg"
            elif "forward" in action_text or "forward" in action_tooltip:
                icon_file = "forward.svg"
            elif "pan" in action_text or "pan" in action_tooltip:
                icon_file = "pan.svg"
            elif "zoom" in action_text or "zoom" in action_tooltip:
                icon_file = "zoom.svg"
            elif "save" in action_text or "save" in action_tooltip:
                icon_file = "save.svg"
            # "Configure subplots" or "Edit axis, curve and image parameters"
            elif (
                "axis, curve" in action_tooltip
                or "edit axis" in action_tooltip
                or "customize" in action_text
            ):
                icon_file = "tune.svg"
            # Regular "Subplots" button (grid layout)
            elif "subplots" in action_text or "subplot" in action_tooltip:
                icon_file = "subplots.svg"

            if icon_file:
                icon_path = os.path.join(_ICONS_DIR, icon_file)
                if os.path.exists(icon_path):
                    action.setIcon(QIcon(icon_path))

    def clear(self):
        """Clear the figure."""
        self.figure.clear()
        self.canvas.draw()

    def get_axes(self, rows: int = 1, cols: int = 1, **kwargs):
        """Get axes for plotting."""
        self.figure.clear()
        if rows == 1 and cols == 1:
            ax = self.figure.add_subplot(111, **kwargs)
            ax.set_facecolor(self._axes_color)
            return ax
        else:
            axes = self.figure.subplots(rows, cols, **kwargs)
            # Set facecolor for all axes
            if hasattr(axes, "flat"):
                for ax in axes.flat:
                    ax.set_facecolor(self._axes_color)
            return axes

    def refresh(self):
        """Refresh the canvas."""
        self.figure.tight_layout()
        self.canvas.draw()


class LogTrackPlot(PlotWidget):
    """
    Specialized widget for multi-track log display.
    """

    def __init__(self, parent=None, n_tracks: int = 5):
        super().__init__(parent, show_toolbar=True, figsize=(12, 8))
        self.n_tracks = n_tracks
        self.axes = []

    def create_tracks(self, depth: np.ndarray, depth_range: Tuple[float, float] = None):
        """Create the track axes."""
        self.figure.clear()
        self.axes = []

        # Create subplots with shared y-axis
        for i in range(self.n_tracks):
            if i == 0:
                ax = self.figure.add_subplot(1, self.n_tracks, i + 1)
            else:
                ax = self.figure.add_subplot(
                    1, self.n_tracks, i + 1, sharey=self.axes[0]
                )

            ax.invert_yaxis()
            ax.grid(True, alpha=0.3)
            ax.set_facecolor(self._axes_color)
            self.axes.append(ax)

        # Set depth range
        if depth_range:
            self.axes[0].set_ylim(depth_range[1], depth_range[0])

        # Only show y-axis label on first track
        self.axes[0].set_ylabel("Depth (ft)")
        for ax in self.axes[1:]:
            ax.tick_params(labelleft=False)

        return self.axes

    def plot_curve(
        self,
        track_idx: int,
        x_data: np.ndarray,
        y_data: np.ndarray,
        color: str = "black",
        label: str = None,
        x_range: Tuple[float, float] = None,
        log_scale: bool = False,
        linewidth: float = 0.8,
    ):
        """Plot a curve on a specific track."""
        if track_idx >= len(self.axes):
            return

        ax = self.axes[track_idx]
        ax.plot(x_data, y_data, color=color, linewidth=linewidth, label=label)

        if x_range:
            ax.set_xlim(x_range)

        if log_scale:
            ax.set_xscale("log")

        if label:
            ax.legend(loc="upper right", fontsize=8)

    def set_track_title(self, track_idx: int, title: str):
        """Set title for a track."""
        if track_idx < len(self.axes):
            self.axes[track_idx].set_title(title, fontsize=10)


class HistogramPlot(PlotWidget):
    """Widget for histogram plots."""

    def __init__(self, parent=None):
        super().__init__(parent, show_toolbar=False, figsize=(4, 3))

    def plot_histogram(
        self,
        data: pd.Series,
        title: str = "Histogram",
        bins: int = 50,
        color: str = "#1E90FF",
        x_label: str = None,
    ):
        """Plot a histogram."""
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.set_facecolor(self._axes_color)

        # Remove NaN
        clean_data = data.dropna()

        ax.hist(clean_data, bins=bins, color=color, alpha=0.7, edgecolor="white")
        ax.set_title(title, fontsize=10)

        if x_label:
            ax.set_xlabel(x_label, fontsize=9)
        ax.set_ylabel("Frequency", fontsize=9)

        # Add mean and median lines
        mean_val = clean_data.mean()
        median_val = clean_data.median()

        ax.axvline(
            mean_val,
            color="red",
            linestyle="--",
            linewidth=1,
            label=f"Mean: {mean_val:.3f}",
        )
        ax.axvline(
            median_val,
            color="green",
            linestyle=":",
            linewidth=1,
            label=f"Median: {median_val:.3f}",
        )
        ax.legend(fontsize=8)

        self.figure.tight_layout()
        self.canvas.draw()


class CrossPlot(PlotWidget):
    """Widget for crossplot visualization."""

    def __init__(self, parent=None):
        super().__init__(parent, show_toolbar=True, figsize=(5, 4))

    def plot_crossplot(
        self,
        x_data: pd.Series,
        y_data: pd.Series,
        color_data: pd.Series = None,
        x_label: str = "X",
        y_label: str = "Y",
        title: str = "Crossplot",
        colorbar_label: str = None,
    ):
        """Create a crossplot."""
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.set_facecolor(self._axes_color)

        # Remove NaN from both series
        mask = x_data.notna() & y_data.notna()
        x = x_data[mask]
        y = y_data[mask]

        if color_data is not None:
            c = color_data[mask]
            scatter = ax.scatter(x, y, c=c, cmap="viridis", alpha=0.6, s=5)
            cbar = self.figure.colorbar(scatter, ax=ax)
            if colorbar_label:
                cbar.set_label(colorbar_label, fontsize=9)
        else:
            ax.scatter(x, y, alpha=0.6, s=5, color="#1E90FF")

        ax.set_xlabel(x_label, fontsize=9)
        ax.set_ylabel(y_label, fontsize=9)
        ax.set_title(title, fontsize=10)
        ax.grid(True, alpha=0.3)

        self.figure.tight_layout()
        self.canvas.draw()


class CompositeLogPlot(PlotWidget):
    """Widget for composite petrophysics log display."""

    # Default color scheme
    COLORS = {
        "GR": "#00AA00",
        "VSH": "#8B4513",
        "RHOB": "#FF0000",
        "NPHI": "#0000FF",
        "DT": "#FF00FF",
        "RT": "#000000",
        "PHIE": "#00CED1",
        "PHID": "#FF6347",
        "PHIN": "#4169E1",
        "SW": "#FF8C00",
        "PERM": "#8B008B",
        "PAY": "#228B22",
    }

    def __init__(self, parent=None):
        super().__init__(parent, show_toolbar=True, figsize=(14, 10))

    def plot_petrophysics_summary(
        self,
        results: pd.DataFrame,
        depth_range: Tuple[float, float] = None,
        formation_tops=None,
    ):
        """
        Create a 5-track petrophysics summary log:
        Track 1: GR + Vsh
        Track 2: Porosity (PHIE, PHID, PHIN)
        Track 3: Water Saturation (SW methods)
        Track 4: Permeability (log scale)
        Track 5: Pay flags

        Args:
            results: DataFrame with petrophysics results
            depth_range: Optional tuple (top, bottom) for depth filtering
            formation_tops: Optional FormationTops object for overlay
        """
        self.figure.clear()

        if "DEPTH" not in results.columns:
            return

        depth = results["DEPTH"].values

        # Apply depth filter
        if depth_range:
            mask = (depth >= depth_range[0]) & (depth <= depth_range[1])
            depth = depth[mask]
            filtered = results[mask]
        else:
            filtered = results
            mask = np.ones(len(depth), dtype=bool)

        # Create 6 tracks
        axes = []
        for i in range(6):
            if i == 0:
                ax = self.figure.add_subplot(1, 6, i + 1)
            else:
                ax = self.figure.add_subplot(1, 6, i + 1, sharey=axes[0])
            ax.invert_yaxis()
            ax.grid(True, alpha=0.3)
            ax.set_facecolor(self._axes_color)
            axes.append(ax)

        axes[0].set_ylabel("Depth (ft)", fontsize=9)
        for ax in axes[1:]:
            ax.tick_params(labelleft=False)

        # Apply global tick params for smaller scale numbers
        for ax in axes:
            ax.tick_params(axis="both", labelsize=6)

        # Track 1: GR + Vsh
        if "VSH" in filtered.columns:
            axes[0].plot(
                filtered["VSH"].values,
                depth,
                color=self.COLORS["VSH"],
                linewidth=0.8,
                label="Vsh",
            )
            axes[0].fill_betweenx(
                depth, 0, filtered["VSH"].values, color=self.COLORS["VSH"], alpha=0.3
            )
        axes[0].set_xlim(0, 1)
        axes[0].set_title("GR / Vsh", fontsize=9)
        axes[0].set_xlabel("Vsh (v/v)", fontsize=8)

        # Track 2: Porosity
        porosity_curves = ["PHIE", "PHID", "PHIN", "PHIT"]
        colors = ["#00CED1", "#FF6347", "#4169E1", "#32CD32"]
        for curve, color in zip(porosity_curves, colors):
            if curve in filtered.columns:
                axes[1].plot(
                    filtered[curve].values,
                    depth,
                    color=color,
                    linewidth=0.8,
                    label=curve,
                )
        axes[1].set_xlim(0, 0.4)
        axes[1].set_title("Porosity", fontsize=9)
        axes[1].set_xlabel("φ (v/v)", fontsize=8)
        axes[1].legend(loc="upper right", fontsize=6)

        # Track 3: Water Saturation
        sw_curves = ["SW_ARCHIE", "SW_INDO", "SW_SIMAN"]
        if (
            hasattr(self, "model")
            and hasattr(self.model, "curve_mapping")
            and "RT" in self.model.curve_mapping
        ):
            sw_curves = ["SW", "SW_ARCHIE", "SW_INDO", "SW_SIMAN", "SW_WS", "SW_DW"]
        sw_colors = [
            "#FF4500",
            "#1E90FF",
            "#32CD32",
            "#FF8C00",
            "#00BFFF",
            "#8A2BE2",
        ]  # Added colors for SW, SW_WS, SW_DW

        # Ensure sw_colors has enough elements for sw_curves
        # If sw_curves is extended, sw_colors should also be extended or handled.
        # For now, assuming sw_colors is extended as per the change.

        for curve, color in zip(sw_curves, sw_colors):
            if curve in filtered.columns:
                axes[2].plot(
                    filtered[curve].values,
                    depth,
                    color=color,
                    linewidth=0.8,
                    label=curve.replace("SW_", ""),
                )
        axes[2].set_xlim(0, 1)
        axes[2].set_title("Sw", fontsize=9)
        axes[2].set_xlabel("Sw (v/v)", fontsize=8)
        axes[2].legend(loc="upper right", fontsize=6)

        # Track 4: Permeability (log scale)
        perm_curves = ["PERM_TIMUR", "PERM_WR"]
        perm_colors = ["#8B008B", "#FF8C00"]
        for curve, color in zip(perm_curves, perm_colors):
            if curve in filtered.columns:
                perm_data = np.clip(filtered[curve].values, 0.001, 100000)
                axes[3].plot(
                    perm_data,
                    depth,
                    color=color,
                    linewidth=0.8,
                    label=curve.replace("PERM_", ""),
                )
        axes[3].set_xscale("log")
        axes[3].set_xlim(0.01, 10000)
        axes[3].set_title("Permeability", fontsize=9)
        axes[3].set_xlabel("K (mD)", fontsize=8)
        axes[3].legend(loc="upper right", fontsize=6)

        # Track 5: Pay flags (if available)
        if "NET_PAY_FLAG" in filtered.columns:
            pay = filtered["NET_PAY_FLAG"].values
            axes[4].fill_betweenx(depth, 0, pay, color="green", alpha=0.7, label="Pay")
        if "NET_RES_FLAG" in filtered.columns:
            res = filtered["NET_RES_FLAG"].values
            # Only show reservoir where not already pay
            res_only = res.copy()
            if "NET_PAY_FLAG" in filtered.columns:
                res_only = res - filtered["NET_PAY_FLAG"].values
                res_only = np.clip(res_only, 0, 1)
            axes[4].fill_betweenx(
                depth, 0, res_only, color="yellow", alpha=0.5, label="Res"
            )
        axes[4].set_xlim(0, 1)
        axes[4].set_title("Pay Flags", fontsize=9)
        axes[4].set_xlabel("Flag", fontsize=8)
        if "NET_PAY_FLAG" in filtered.columns or "NET_RES_FLAG" in filtered.columns:
            axes[4].legend(loc="upper right", fontsize=6)

        # Track 6: HCPV (Net Pay default)
        # CONSOLIDATED SINGLE SCALE
        if (
            "dHCPV_NET_PAY" in filtered.columns
            or "HCPV_CUM_NET_PAY" in filtered.columns
        ):
            if "dHCPV_NET_PAY" in filtered.columns:
                d_hcpv_data = filtered["dHCPV_NET_PAY"].values
                axes[5].plot(
                    d_hcpv_data,
                    depth,
                    color="#FF4500",
                    linewidth=0.8,
                    label="dHCPV Pay",
                )

            if "HCPV_CUM_NET_PAY" in filtered.columns:
                hcpv_cum_data = filtered["HCPV_CUM_NET_PAY"].values
                axes[5].plot(
                    hcpv_cum_data,
                    depth,
                    color="#228B22",
                    linewidth=1.0,
                    linestyle="--",
                    label="HCPV Cum",
                )

        axes[5].set_title("HCPV", fontsize=9)
        axes[5].set_xlabel("Volume (ft)", fontsize=8)
        # axes[5].tick_params(axis="x", colors="#FF4500")
        if (
            "dHCPV_NET_PAY" in filtered.columns
            or "HCPV_CUM_NET_PAY" in filtered.columns
        ):
            axes[5].legend(loc="upper right", fontsize=6)

        # Add formation tops overlay
        if formation_tops is not None:
            tops_list = []
            if hasattr(formation_tops, "formations") and isinstance(
                formation_tops.formations, list
            ):
                for fm in formation_tops.formations:
                    tops_list.append({"name": fm.name, "top_depth": fm.top_depth})

            for top in tops_list:
                top_depth = top.get("top_depth", 0)
                name = top.get("name", "")

                # Draw horizontal line on all axes
                for ax in axes:
                    ax.axhline(
                        y=top_depth,
                        color="#FF6600",
                        linestyle="--",
                        linewidth=1,
                        alpha=0.8,
                    )

                # Add label on first axis
                axes[0].text(
                    0.02,
                    top_depth,
                    name,
                    fontsize=6,
                    color="#FF6600",
                    verticalalignment="bottom",
                    transform=axes[0].get_yaxis_transform(),
                )

        # Explicitly set margins to ensure x-axis labels visible
        # Revert bottom margin to normal since we use single scale
        self.figure.subplots_adjust(
            left=0.06, right=0.98, top=0.95, bottom=0.08, wspace=0.15
        )
        self.canvas.draw()


class TripleComboPlot(PlotWidget):
    """Widget for triple combo log display (raw input data)."""

    def __init__(self, parent=None):
        super().__init__(parent, show_toolbar=True, figsize=(12, 8))

    def plot_triple_combo(self, data: pd.DataFrame, curve_mapping: Dict[str, str]):
        """
        Plot triple combo log with professional layout:
        Track 1: GR (0-150 API) - green
        Track 2: RT (log scale 0.2-2000) - black
        Track 3: RHOB (1.95-2.95), NPHI (0.45--0.15), DT (optional) overlay

        Features:
        - Depth inverted (increasing downward)
        - RHOB and NPHI scaled for gas crossover visualization
        - Interactive toolbar for zoom/pan/reset
        """
        self.figure.clear()

        if "DEPTH" not in data.columns:
            return

        depth = data["DEPTH"].values

        # Get curves from mapping
        gr_curve = curve_mapping.get("GR", "None")
        rt_curve = curve_mapping.get("RT", "None")
        rhob_curve = curve_mapping.get("RHOB", "None")
        nphi_curve = curve_mapping.get("NPHI", "None")
        dt_curve = curve_mapping.get("DT", "None")

        # Count available tracks
        has_gr = gr_curve != "None" and gr_curve in data.columns
        has_rt = rt_curve != "None" and rt_curve in data.columns
        has_rhob = rhob_curve != "None" and rhob_curve in data.columns
        has_nphi = nphi_curve != "None" and nphi_curve in data.columns
        has_dt = dt_curve != "None" and dt_curve in data.columns

        # Need at least one track
        if not (has_gr or has_rt or has_rhob or has_nphi or has_dt):
            return

        # Create 3 tracks
        n_tracks = 3
        axes = []

        for i in range(n_tracks):
            if i == 0:
                ax = self.figure.add_subplot(1, n_tracks, i + 1)
            else:
                ax = self.figure.add_subplot(1, n_tracks, i + 1, sharey=axes[0])
            axes.append(ax)

        # Set depth range (inverted - increasing downward)
        depth_min, depth_max = depth.min(), depth.max()
        axes[0].set_ylim(depth_max, depth_min)  # Inverted!

        # =====================================================================
        # TRACK 1: GR (Gamma Ray)
        # =====================================================================
        ax1 = axes[0]
        ax1.set_ylabel("Depth (ft)", fontsize=10, fontweight="bold")
        ax1.set_xlabel("GR (API)", fontsize=9, color="#228B22")
        ax1.set_title("Track 1: GR", fontsize=10, fontweight="bold")
        ax1.grid(True, alpha=0.3, linestyle="--")
        ax1.set_facecolor(self._axes_color)

        if has_gr:
            gr_data = data[gr_curve].values
            ax1.plot(gr_data, depth, color="#228B22", linewidth=0.8, label="GR")
            ax1.fill_betweenx(depth, 0, gr_data, color="#90EE90", alpha=0.4)
            ax1.set_xlim(0, 150)
            ax1.axvline(75, color="#228B22", linestyle=":", alpha=0.5)  # Shale baseline
        else:
            ax1.set_xlim(0, 150)
            ax1.text(
                75,
                (depth_max + depth_min) / 2,
                "No GR",
                ha="center",
                va="center",
                fontsize=12,
                alpha=0.5,
            )

        # =====================================================================
        # TRACK 2: RT (Resistivity - Log Scale)
        # =====================================================================
        ax2 = axes[1]
        ax2.tick_params(labelleft=False)
        ax2.set_xlabel("RT (Ω.m)", fontsize=9, color="#000000")
        ax2.set_title("Track 2: RT", fontsize=10, fontweight="bold")
        ax2.grid(True, alpha=0.3, linestyle="--", which="both")
        ax2.set_facecolor(self._axes_color)

        if has_rt:
            rt_data = np.clip(data[rt_curve].values, 0.1, 10000)
            ax2.plot(rt_data, depth, color="#000000", linewidth=1.0, label="RT")
            ax2.set_xscale("log")
            ax2.set_xlim(0.2, 2000)
        else:
            ax2.set_xscale("log")
            ax2.set_xlim(0.2, 2000)
            ax2.text(
                10,
                (depth_max + depth_min) / 2,
                "No RT",
                ha="center",
                va="center",
                fontsize=12,
                alpha=0.5,
            )

        # =====================================================================
        # TRACK 3: RHOB + NPHI + DT (Density-Neutron-Sonic Overlay)
        # =====================================================================
        ax3 = axes[2]
        ax3.tick_params(labelleft=False)
        ax3.set_title("Track 3: ρ-N-DT", fontsize=10, fontweight="bold")
        ax3.grid(True, alpha=0.3, linestyle="--")
        ax3.set_facecolor(self._axes_color)

        # We want overlay:
        # NPHI: 0.45 (Left) -> -0.15 (Right) (High porosity left)
        # RHOB: 1.95 (Left) -> 2.95 (Right) (Low density/High porosity left)

        # Plot NPHI on primary axis (Blue)
        if has_nphi:
            nphi_data = data[nphi_curve].values
            ax3.plot(
                nphi_data,
                depth,
                color="#0000FF",
                linewidth=1.0,
                linestyle="-",
                label="NPHI",
            )
            ax3.set_xlim(0.45, -0.15)  # Reversed scale
            ax3.set_xlabel("NPHI (v/v)", fontsize=9, color="#0000FF")
            ax3.tick_params(axis="x", colors="#0000FF")
        else:
            ax3.set_xlim(0.45, -0.15)

        # Plot RHOB on twin axis (Red)
        if has_rhob:
            ax3_rhob = ax3.twiny()
            rhob_data = data[rhob_curve].values
            ax3_rhob.plot(
                rhob_data,
                depth,
                color="#FF0000",
                linewidth=1.0,
                linestyle="-",
                label="RHOB",
            )
            ax3_rhob.set_xlim(1.95, 2.95)  # Standard scale
            ax3_rhob.set_xlabel("RHOB (g/cc)", fontsize=9, color="#FF0000")
            ax3_rhob.tick_params(axis="x", colors="#FF0000")

            if has_nphi:
                # Normalize to 0-1 range (0 = Left, 1 = Right)
                # NPHI ax: 0.45 -> -0.15.  Value x. Norm = (0.45 - x) / (0.45 - (-0.15)) = (0.45 - x) / 0.6
                nphi_norm = (0.45 - nphi_data) / 0.60

                # RHOB ax: 1.95 -> 2.95. Value y. Norm = (y - 1.95) / (2.95 - 1.95) = y - 1.95
                rhob_norm = rhob_data - 1.95

                # Crossover: RHOB is LEFT of NPHI
                # In normalized space (0=Left), this means rhob_norm < nphi_norm

                # We need to handle NaNs for fill_between
                valid_mask = ~np.isnan(nphi_norm) & ~np.isnan(rhob_norm)
                d_valid = depth[valid_mask]
                n_valid = nphi_data[
                    valid_mask
                ]  # Use original NPHI data for plotting fill on ax3

                # Calculate corresponding RHOB values in NPHI scale for fill
                # rhob_norm = nphi_norm_equivalent
                # rhob_val - 1.95 = (0.45 - nphi_eq) / 0.6
                # nphi_eq = 0.45 - (rhob_val - 1.95) * 0.6
                rhob_on_nphi_scale = 0.45 - (rhob_data[valid_mask] - 1.95) * 0.6

                # Fill where RHOB (on NPHI scale) is LEFT of NPHI
                # i.e., rhob_on_nphi_scale > nphi_data (Keep in mind axis is 0.45 -> -0.15)
                # Left means LARGER value on NPHI axis.
                # So if rhob_on_nphi_scale > nphi_data, RHOB is to the Left.

                ax3.fill_betweenx(
                    d_valid,
                    n_valid,
                    rhob_on_nphi_scale,
                    where=(rhob_on_nphi_scale > n_valid),
                    interpolate=True,
                    color="#FFD700",
                    alpha=0.5,
                    label="Gas X-over",
                )

        # DT axis (if available) - typically dashed
        if has_dt:
            ax3_dt = ax3.twiny()
            ax3_dt.spines["top"].set_position(("outward", 35))
            dt_data = data[dt_curve].values
            ax3_dt.plot(
                dt_data,
                depth,
                color="#8B008B",
                linewidth=0.8,
                linestyle=":",
                label="DT",
            )
            ax3_dt.set_xlim(140, 40)  # Inverted
            ax3_dt.set_xlabel("DT (µs/ft)", fontsize=8, color="#8B008B")
            ax3_dt.tick_params(axis="x", colors="#8B008B", labelsize=8)

        # Add legend
        legend_items = []
        if has_rhob:
            legend_items.append("RHOB (red)")
        if has_nphi:
            legend_items.append("NPHI (blue)")
        if has_dt:
            legend_items.append("DT (magenta)")
        if legend_items:
            ax3.text(
                0.02,
                0.98,
                "  ".join(legend_items),
                transform=ax3.transAxes,
                fontsize=7,
                verticalalignment="top",
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.8),
            )

        # Final layout
        self.figure.suptitle(
            "Triple Combo Log (Input QC)", fontsize=12, fontweight="bold", y=0.98
        )
        self.figure.tight_layout(rect=[0, 0, 1, 0.96])
        self.canvas.draw()
