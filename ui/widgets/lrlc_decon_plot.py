"""Rt deconvolution plot of the LRLC Workbench (Remediation > Rt deconvolution).

``DeconPlot`` draws three depth tracks that share the depth axis: the reference curve with the
bed boundaries (automatic solid, added dashed, removed grey and crossed out), the measured RT with
the proposed deconvolved RT (stepped, log scale), and the relative residual of the bed model with
the misfit of each solve window. It is a picture: the owner supplies the arrays and the edit
lists, a click is reported with ``boundary_clicked(mode, depth)`` and nothing here reads the model
or runs the analysis.
"""

from typing import Optional

import numpy as np
from PyQt6.QtCore import pyqtSignal

from themes.colors import get_plot_chrome, get_plot_color
from themes.tokens import PLOT_COLORS

from .lrlc_invasion_plot import _fit_layout, _plain_log_axis
from .lrlc_ts_plot import _PlotBase

MODES = ("none", "add", "remove")
MAX_POINTS = 6000
REMOVE_PICK_PX = 8.0


def decon_color() -> str:
    """Colour of the deconvolved Rt (its own plot token when the theme has one)."""
    return get_plot_color("RT_DECON" if "RT_DECON" in PLOT_COLORS else "RT_SW")


def _thin(depth: np.ndarray, *arrays):
    """The same subset of the arrays, at most ``MAX_POINTS`` samples."""
    if len(depth) <= MAX_POINTS:
        return (depth,) + arrays
    pick = np.linspace(0, len(depth) - 1, MAX_POINTS).astype(int)
    return (depth[pick],) + tuple(None if a is None else a[pick] for a in arrays)


def classify_boundaries(auto, final, edits, tol: float):
    """``[(depth, origin)]`` sorted by depth; origin is ``auto``, ``added`` or ``removed``.

    A final boundary within ``tol`` of an automatic one is automatic, any other is added; an
    automatic boundary that is not final and sits within ``tol`` of a ``remove`` edit is removed.
    """
    auto = np.asarray(auto, dtype=float)
    final = np.asarray(final, dtype=float)
    rows = []
    for x in final:
        near = auto.size and float(np.min(np.abs(auto - x))) <= tol
        rows.append((float(x), "auto" if near else "added"))
    removes = [float(v) for v in (edits or {}).get("remove", [])]
    for a in auto:
        if final.size and float(np.min(np.abs(final - a))) <= tol:
            continue
        if any(abs(a - v) <= tol for v in removes):
            rows.append((float(a), "removed"))
    return sorted(rows)


class DeconPlot(_PlotBase):
    """Reference curve, RT and residual against depth. ``set_mode("add" | "remove" | "none")``
    chooses what a click does; ``boundary_clicked(mode, depth)`` is emitted for it."""

    boundary_clicked = pyqtSignal(str, float)

    def __init__(self, parent=None):
        super().__init__((8.0, 6.0), parent)
        self.plot.setMinimumHeight(420)
        self.mode = "none"
        self._axes = []
        self._lines = []
        self.plot.canvas.mpl_connect("button_press_event", self._on_click)

    def set_mode(self, mode: str):
        self.mode = mode if mode in MODES else "none"

    def set_data(self, data: dict, edits: Optional[dict], tol: float):
        """``data`` is the plot block of a proposal (see ``DeconWorker.compute``)."""
        self._args = (data, edits or {"add": [], "remove": []}, float(tol))
        self._draw(*self._args)

    def clear_data(self, message: str):
        self._args = None
        self._axes = []
        self._lines = []
        self._message(message)

    # ------------------------------------------------------------------ drawing
    def _draw(self, data, edits, tol):
        axes = self.plot.get_axes(1, 3, sharey=True)
        self._axes = list(axes)
        chrome = get_plot_chrome()
        depth = np.asarray(data["depth"], dtype=float)
        ref = data.get("hires")
        rt = data.get("rt")
        dec = np.asarray(data["rt_decon"], dtype=float)
        res = np.asarray(data["residual"], dtype=float)
        log_domain = bool(data.get("log_domain", True))
        name = (data.get("reference") or {}).get("column") or (data.get("reference") or {}).get("curve") or "reference"
        a1, a2, a3 = self._axes

        # track 1: reference curve and boundaries
        if ref is not None:
            d, h = _thin(depth, np.asarray(ref, dtype=float))
            a1.plot(h, d, color=get_plot_color("RXO_INV"), lw=1.0)
        if log_domain:
            a1.set_xscale("log")
            _plain_log_axis(a1.xaxis)
        a1.set_title(f"Reference: {name}", fontsize=8)
        a1.set_ylabel("Depth (ft)")
        a1.invert_yaxis()

        # tracks 2 and 3
        d, rt_thin, dec_thin, res_thin = _thin(depth, None if rt is None else np.asarray(rt, dtype=float),
                                               dec, res)
        if rt_thin is not None:
            a2.step(rt_thin, d, where="mid", color=get_plot_color("RT"), lw=1.0, label="RT")
        a2.step(dec_thin, d, where="mid", color=decon_color(), lw=1.5, label="RT deconvolved")
        a2.set_xscale("log")
        _plain_log_axis(a2.xaxis)
        a2.set_title("RT (ohm.m)", fontsize=8)
        a2.legend(loc="lower right", fontsize=6)
        a3.plot(res_thin, d, color=chrome["text"], lw=0.9)
        a3.axvline(0.0, color=chrome["spine"], lw=0.6)
        a3.set_title("Relative residual", fontsize=8)
        for w in data.get("windows", []):
            mid = 0.5 * (float(w["top"]) + float(w["bottom"]))
            if depth[0] <= mid <= depth[-1] and np.isfinite(w.get("misfit_rms", np.nan)):
                a3.annotate(f"{float(w['misfit_rms']):.3f}", (1.0, mid), xycoords=("axes fraction", "data"),
                            fontsize=6, color=chrome["text"], ha="right", va="center")

        # boundaries in the three tracks
        for x, origin in classify_boundaries(data["auto"], data["final"], edits, tol):
            for ax in (a1, a2):
                if origin == "removed":
                    ax.axhline(x, color=chrome["spine"], lw=0.8, ls=(0, (1, 2)), alpha=0.9)
                    ax.plot([0.0], [x], transform=ax.get_yaxis_transform(), marker="x", ms=5,
                            color=chrome["spine"], clip_on=False)
                else:
                    ax.axhline(x, color=chrome["text"], lw=0.7, alpha=0.8,
                               ls="-" if origin == "auto" else (0, (4, 2)))
        for ax in self._axes:
            ax.grid(True, alpha=0.3, which="both")
        a1.set_ylim(depth[-1], depth[0])
        _fit_layout(self.plot.figure)
        self.plot.canvas.draw_idle()

    # ------------------------------------------------------------------- clicks
    def _on_click(self, event):
        if self.mode == "none" or self._args is None or event.inaxes not in self._axes[:2]:
            return
        if event.ydata is None:
            return
        data, edits, tol = self._args
        depth = float(event.ydata)
        if self.mode == "remove":
            rows = [r for r in classify_boundaries(data["auto"], data["final"], edits, tol)
                    if r[1] != "removed"]
            if not rows:
                return
            ax = event.inaxes
            ys = np.array([ax.transData.transform((0.0, r[0]))[1] for r in rows])
            i = int(np.argmin(np.abs(ys - event.y)))
            if abs(ys[i] - event.y) > REMOVE_PICK_PX:
                return
            depth = rows[i][0]
        self.boundary_clicked.emit(self.mode, depth)
