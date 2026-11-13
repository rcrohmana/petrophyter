"""Radial invasion plots of the LRLC Workbench (Remediation > Radial invasion).

``InvasionProfilePlot`` draws the step profile fitted at one depth with the tool readings and
the model's apparent values; ``TornadoPlot`` is the RS/RT against RM/RT crossplot with the
forward loci of the generic model. Both are read-only pictures: the owner supplies the arrays
and nothing here reads the model or runs the analysis.
"""

from typing import Dict, Optional, Sequence, Tuple

import numpy as np
from matplotlib import colormaps as _colormaps
from matplotlib.ticker import FuncFormatter
from PyQt6.QtCore import pyqtSignal

from modules.lrlc.invasion import forward_ra
from themes.colors import get_plot_chrome, get_plot_color

from .lrlc_ts_plot import _PlotBase

CONTRASTS = (0.05, 0.1, 0.3, 3.0, 10.0, 30.0)
MAX_POINTS = 4000
TOOL_NAMES = ("Deep", "Medium", "Shallow")


def _plain_major(value, _pos=None) -> str:
    return f"{value:g}"


def _plain_minor(value, _pos=None) -> str:
    """Label the 2 and 5 multiples of a decade; the others stay unlabelled."""
    if value <= 0:
        return ""
    lead = value / 10 ** np.floor(np.log10(value))
    return f"{value:g}" if round(lead, 6) in (2.0, 5.0) else ""


def _plain_log_axis(axis) -> None:
    """Plain numbers (20, 50, 100) on a log axis instead of 2 x 10^1, which is wide enough
    to push the axis label off the figure."""
    axis.set_major_formatter(FuncFormatter(_plain_major))
    axis.set_minor_formatter(FuncFormatter(_plain_minor))


def _fit_layout(figure) -> None:
    """Keep tick and axis labels inside the canvas, also after the canvas is resized (the
    tight layout engine runs on every draw)."""
    try:
        figure.set_layout_engine("tight", pad=0.8)
    except (ValueError, RuntimeError):     # a canvas too small to lay out; draw as it is
        pass


def forward_loci(r50: Sequence[float], p: float, di_min: float, di_max: float,
                 contrasts: Sequence[float] = CONTRASTS, n: int = 60
                 ) -> Dict[float, Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """``{Rxo/Rt: (RM/RT, RS/RT, di)}`` of the generic model as ``di`` runs from ``di_min`` to
    ``di_max``. ``r50`` is ``(deep, medium, shallow)``; the ratios are taken to the apparent
    deep reading, which is what the data crossplot divides by."""
    di = np.geomspace(float(di_min), float(di_max), n)
    out = {}
    for c in contrasts:
        ra = forward_ra(np.ones_like(di), np.full_like(di, float(c)), di, r50, p)
        out[float(c)] = (ra[:, 1] / ra[:, 0], ra[:, 2] / ra[:, 0], di)
    return out


def profile_steps(rt: float, rxo: float, di: float, x_max: float):
    """``(x, y)`` of the step profile: ``rxo`` out to the diameter ``di``, ``rt`` beyond."""
    return (np.array([0.0, di, di, x_max]), np.array([rxo, rxo, rt, rt]))


class InvasionProfilePlot(_PlotBase):
    """Resistivity against investigation diameter at one depth."""

    def __init__(self, parent=None):
        super().__init__((6.0, 4.0), parent)
        self.plot.setMinimumHeight(300)

    def set_data(self, depth: float, readings: Sequence[Optional[float]], rt: float,
                 rxo: Optional[float], di: Optional[float], r50: Sequence[float], p: float,
                 note: str = ""):
        """``readings`` are the measured ``(deep, medium, shallow)`` values (None if missing);
        ``rt``, ``rxo`` and ``di`` the fitted profile (``di`` None or NaN: no profile)."""
        self._args = (depth, readings, rt, rxo, di, r50, p, note)
        self._draw(*self._args)

    def clear_data(self, message: str):
        self._args = None
        self._message(message)

    def _draw(self, depth, readings, rt, rxo, di, r50, p, note):
        ax = self.plot.get_axes()
        chrome = get_plot_chrome()
        r50 = [float(r) for r in r50]
        has_profile = (di is not None and np.isfinite(di) and rxo is not None
                       and np.isfinite(rxo) and rt is not None and np.isfinite(rt))
        x_max = max(max(r50) * 1.5, (float(di) * 1.4) if has_profile else 0.0)
        values = [float(v) for v in readings if v is not None and np.isfinite(v)]
        if has_profile:
            x, y = profile_steps(float(rt), float(rxo), float(di), x_max)
            ax.step(x, y, where="post", color=get_plot_color("RT_INV"), lw=1.8, zorder=3,
                    label="Fitted step profile")
            ax.axvline(float(di), color=chrome["spine"], lw=0.8, ls=":", zorder=1)
            ax.annotate(f"di {float(di):.0f} in", (float(di), min(rxo, rt)), fontsize=7,
                        color=chrome["text"], xytext=(4, 4), textcoords="offset points")
            ra = forward_ra(float(rt), float(rxo), float(di), r50, p)
            ax.scatter(r50, ra, marker="x", s=46, color=get_plot_color("RXO_INV"), zorder=5,
                       label="Model apparent")
            values += [float(v) for v in ra] + [float(rt), float(rxo)]
        marks = [(r, v) for r, v in zip(r50, readings) if v is not None and np.isfinite(v)]
        if marks:
            ax.scatter([m[0] for m in marks], [m[1] for m in marks], s=40, zorder=6,
                       facecolors="none", edgecolors=get_plot_color("RT"), linewidths=1.4,
                       label="Tool readings")
            for (r, v), name in zip(marks, TOOL_NAMES):
                ax.annotate(name, (r, v), fontsize=7, color=chrome["text"], xytext=(4, -10),
                            textcoords="offset points")
        ax.set_yscale("log")
        ax.set_xlim(0.0, x_max)
        if values:
            ax.set_ylim(min(values) / 1.6, max(values) * 1.6)
        ax.set_xlabel("Investigation diameter (in)")
        ax.set_ylabel("Resistivity (ohm.m)")
        title = f"Depth {float(depth):.1f}"
        if note:
            title += f": {note}"
        ax.set_title(title, fontsize=9)
        ax.grid(True, alpha=0.3, which="both")
        ax.legend(loc="best", fontsize=7)
        _plain_log_axis(ax.yaxis)
        _fit_layout(self.plot.figure)
        self.plot.canvas.draw_idle()


class TornadoPlot(_PlotBase):
    """RS/RT (y) against RM/RT (x), log-log, with the forward loci of the generic model.

    A click on the cloud emits ``depth_picked`` with the depth of the nearest plotted sample
    (when ``depth`` was given), which the owner uses to choose the profile depth.
    """

    depth_picked = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__((6.0, 4.6), parent)
        self.plot.setMinimumHeight(320)
        self.n_drawn = 0
        self._pts: Optional[tuple] = None        # (x, y, depth) of the plotted samples
        self.plot.canvas.mpl_connect("button_press_event", self._on_click)

    def set_data(self, rt, rm, rs, di=None, r50: Sequence[float] = (80.0, 45.0, 20.0),
                 p: float = 2.5, di_min: float = 8.0, di_max: float = 120.0,
                 generic: bool = True, depth=None):
        self._args = (rt, rm, rs, di, r50, p, di_min, di_max, generic, depth)
        self._draw(*self._args)

    def _on_click(self, event):
        if self._pts is None or event.xdata is None or event.ydata is None:
            return
        x, y, depth = self._pts
        if depth is None or not len(x) or event.xdata <= 0 or event.ydata <= 0:
            return
        d2 = (np.log10(x) - np.log10(event.xdata)) ** 2 + (np.log10(y) - np.log10(event.ydata)) ** 2
        self.depth_picked.emit(float(depth[int(np.argmin(d2))]))

    def clear_data(self, message: str):
        self._args = None
        self.n_drawn = 0
        self._pts = None
        self._message(message)

    def _draw(self, rt, rm, rs, di, r50, p, di_min, di_max, generic, depth):
        ax = self.plot.get_axes()
        chrome = get_plot_chrome()
        rt = np.asarray(rt, dtype=float)
        rm = np.asarray(rm, dtype=float)
        rs = np.asarray(rs, dtype=float)
        ok = np.isfinite(rt) & np.isfinite(rm) & np.isfinite(rs) & (rt > 0) & (rm > 0) & (rs > 0)
        x, y = rm[ok] / rt[ok], rs[ok] / rt[ok]
        dcol = None if di is None else np.asarray(di, dtype=float)[ok]
        dep = None if depth is None else np.asarray(depth, dtype=float)[ok]
        self.n_drawn = int(ok.sum())
        if len(x) > MAX_POINTS:
            keep = np.linspace(0, len(x) - 1, MAX_POINTS).astype(int)
            x, y = x[keep], y[keep]
            dcol = None if dcol is None else dcol[keep]
            dep = None if dep is None else dep[keep]
        self._pts = (x, y, dep)
        if len(x):
            if dcol is not None and np.isfinite(dcol).any():
                pts = ax.scatter(x, y, s=8, c=dcol, cmap="viridis", alpha=0.7, linewidths=0,
                                 zorder=3, label=f"Samples ({self.n_drawn})")
                bar = self.plot.figure.colorbar(pts, ax=ax, pad=0.02)
                bar.set_label("DI_INV (in)", color=chrome["text"])
                bar.ax.tick_params(colors=chrome["text"])
            else:
                ax.scatter(x, y, s=8, alpha=0.6, linewidths=0, zorder=3,
                           color=get_plot_color("RT_SW"), label=f"Samples ({self.n_drawn})")
        loci = forward_loci(r50, p, di_min, di_max)
        cmap = _colormaps["coolwarm"]
        lo, hi = np.log10(min(loci)), np.log10(max(loci))
        for c, (lx, ly, _di) in loci.items():
            colour = cmap(0.1 + 0.8 * (np.log10(c) - lo) / (hi - lo))
            ax.plot(lx, ly, color=colour, lw=1.3, zorder=4,
                    label=f"Rxo/Rt {c:g}" + (" (generic model)" if c == min(loci) and generic
                                             else ""))
        ax.axhline(1.0, color=chrome["spine"], lw=0.7, ls=":")
        ax.axvline(1.0, color=chrome["spine"], lw=0.7, ls=":")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("RM / RT")
        ax.set_ylabel("RS / RT")
        ax.grid(True, alpha=0.3, which="both")
        ax.legend(loc="upper left", fontsize=7, ncol=2)
        _plain_log_axis(ax.xaxis)
        _plain_log_axis(ax.yaxis)
        _fit_layout(self.plot.figure)
        self.plot.canvas.draw_idle()
