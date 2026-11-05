"""Thomas-Stieber crossplot and the PEF versus RHOB plot of the LRLC Workbench.

Both are read-only pictures: ``TsCrossplot`` draws the laminar / dispersed triangle in the
Vsh - PHIT plane with the samples coloured by Thomas-Stieber class, ``PefRhobPlot`` draws the
log samples with the matrix, shale and pyrite points and the direction pyrite pulls them. The
owner supplies the arrays; nothing here reads the model or runs the analysis.
"""

from typing import Dict, Optional, Sequence, Tuple

import numpy as np
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from themes.colors import get_plot_chrome, get_plot_color

from .lrlc_pickett import forward_wheel_to_scroll
from .plot_widget import PlotWidget

PLOT_MIN_HEIGHT = 340

CLASS_KEYS = {0: "ts_na", 1: "ts_laminar", 2: "ts_dispersed", 3: "ts_mixed", 4: "ts_structural",
              5: "ts_clay"}
CLASS_NAMES = {0: "Not classified", 1: "Laminar", 2: "Dispersed", 3: "Mixed", 4: "Structural",
               5: "Clay-supported"}
ISO_VLAM = (0.2, 0.4, 0.6, 0.8)
MIX_FRACTIONS = (0.02, 0.05, 0.10)


def class_color(ts_class: int) -> str:
    """Theme colour of a Thomas-Stieber class."""
    return get_plot_color(CLASS_KEYS.get(int(ts_class), "ts_na"))


def triangle_lines(phi_max: float, phi_sh: float) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
    """The named lines of the Thomas-Stieber triangle as ``(vsh, phit)`` arrays.

    ``laminar`` joins the clean-sand and shale vertices, ``dispersed`` runs from the clean-sand
    vertex to the dispersed apex, ``apex_shale`` from the apex to the shale vertex. Iso-Vlam
    lines (``iso_0.2`` ...) run parallel to the dispersed line from the laminar line.
    """
    apex = (phi_max, phi_max * phi_sh)
    out = {
        "laminar": (np.array([0.0, 1.0]), np.array([phi_max, phi_sh])),
        "dispersed": (np.array([0.0, apex[0]]), np.array([phi_max, apex[1]])),
        "apex_shale": (np.array([apex[0], 1.0]), np.array([apex[1], phi_sh])),
    }
    vd = np.linspace(0.0, phi_max, 20)
    for v in ISO_VLAM:
        vsh = v + (1.0 - v) * vd
        phit = (1.0 - v) * (phi_max - vd * (1.0 - phi_sh)) + v * phi_sh
        out[f"iso_{v:g}"] = (vsh, phit)
    return out


def mixing_curve(ma: Tuple[float, float], py: Tuple[float, float], n: int = 60
                 ) -> Tuple[np.ndarray, np.ndarray, Dict[float, Tuple[float, float]]]:
    """``(rhob, pef, marks)`` of pyrite replacing matrix volume; ``ma`` and ``py`` are
    ``(rhob, pef)``. PEF follows the volumetric absorption U = PEF * RHOB, which mixes
    linearly, so the path is a curve in this plane. ``marks`` holds the points at 2, 5 and 10
    percent pyrite."""
    def point(t):
        rho = (1.0 - t) * ma[0] + t * py[0]
        u = (1.0 - t) * ma[1] * ma[0] + t * py[1] * py[0]
        return rho, u / rho

    ts = np.linspace(0.0, 1.0, n)
    pts = np.array([point(t) for t in ts])
    return pts[:, 0], pts[:, 1], {t: point(t) for t in MIX_FRACTIONS}


class _PlotBase(QWidget):
    def __init__(self, figsize, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.plot = PlotWidget(figsize=figsize)
        self.plot.setMinimumHeight(PLOT_MIN_HEIGHT)
        self.plot.canvas.installEventFilter(self)
        root.addWidget(self.plot)
        self._args: Optional[tuple] = None

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel and forward_wheel_to_scroll(self, event):
            return True
        return super().eventFilter(obj, event)

    def refresh_theme(self):
        self.plot.update_theme_colors()
        if self._args is not None:
            self._draw(*self._args)

    def _message(self, text: str):
        ax = self.plot.get_axes()
        chrome = get_plot_chrome()
        ax.set_xticks([])
        ax.set_yticks([])
        ax.text(0.5, 0.5, text, ha="center", va="center", transform=ax.transAxes,
                color=chrome["text"], wrap=True)
        self.plot.canvas.draw_idle()


class TsCrossplot(_PlotBase):
    """Vsh (x) against PHIT (y) with the Thomas-Stieber triangle.

    ``set_data(vsh, phit, ts_class, phi_max, phi_sh)`` takes the samples to draw and the applied
    end-points (None when nothing is applied). ``proposal=(phi_max, phi_sh)`` adds the proposed
    end-points as hollow markers when they differ from the applied ones. With no end-points the
    triangle is skipped and the samples are drawn uncoloured.
    """

    def __init__(self, parent=None):
        super().__init__((6.5, 5), parent)
        self.n_drawn = 0

    def set_data(self, vsh, phit, ts_class, phi_max=None, phi_sh=None, proposal=None,
                 title: str = ""):
        self._args = (vsh, phit, ts_class, phi_max, phi_sh, proposal, title)
        self._draw(*self._args)

    def clear_data(self, message: str):
        self._args = None
        self.n_drawn = 0
        self._message(message)

    def _draw(self, vsh, phit, ts_class, phi_max, phi_sh, proposal, title):
        ax = self.plot.get_axes()
        chrome = get_plot_chrome()
        vsh = np.asarray(vsh, dtype=float)
        phit = np.asarray(phit, dtype=float)
        cls = (np.zeros(len(vsh), dtype=int) if ts_class is None
               else np.asarray(ts_class, dtype=int))
        ok = np.isfinite(vsh) & np.isfinite(phit)
        vsh, phit, cls = vsh[ok], phit[ok], cls[ok]
        self.n_drawn = int(len(vsh))

        if phi_max is not None and phi_sh is not None:
            lines = triangle_lines(float(phi_max), float(phi_sh))
            for v in ISO_VLAM:
                x, y = lines[f"iso_{v:g}"]
                ax.plot(x, y, color=chrome["spine"], lw=0.7, ls=":", zorder=1)
                ax.annotate(f"Vlam {v:g}", (x[0], y[0]), fontsize=7, color=chrome["text"],
                            xytext=(3, 3), textcoords="offset points")
            for name, key, label in (("laminar", "ts_laminar", "Laminar line"),
                                     ("dispersed", "ts_dispersed", "Dispersed line"),
                                     ("apex_shale", "ts_clay", "Apex to shale")):
                x, y = lines[name]
                ax.plot(x, y, color=get_plot_color(key), lw=1.6, label=label, zorder=2)
            pm, ps = float(phi_max), float(phi_sh)
            ax.scatter([0.0, 1.0, pm], [pm, ps, pm * ps], s=60, marker="s",
                       color=get_plot_color("VLAM"), zorder=6, label="End-points (applied)")
        if proposal is not None:
            qm, qs = float(proposal[0]), float(proposal[1])
            if (phi_max is None or phi_sh is None
                    or abs(qm - float(phi_max)) > 1e-9 or abs(qs - float(phi_sh)) > 1e-9):
                ax.scatter([0.0, 1.0], [qm, qs], s=70, marker="s", facecolors="none",
                           edgecolors=get_plot_color("ts_na"), linewidths=1.5, zorder=5,
                           label="End-points (proposed)")

        for c in sorted(set(cls.tolist())):
            sel = cls == c
            ax.scatter(vsh[sel], phit[sel], s=9, alpha=0.7, linewidths=0, zorder=3,
                       color=class_color(c), label=f"{CLASS_NAMES.get(c, str(c))} ({int(sel.sum())})")
        ax.set_xlim(0.0, 1.0)
        top = 0.45
        for arr in (phit, [phi_max] if phi_max is not None else [], [proposal[0]] if proposal else []):
            arr = np.asarray(arr, dtype=float)
            if arr.size and np.isfinite(arr).any():
                top = max(top, float(np.nanmax(arr)) * 1.1)
        ax.set_ylim(0.0, min(top, 0.6))
        ax.set_xlabel("Vsh (v/v)")
        ax.set_ylabel("PHIT (v/v)")
        if title:
            ax.set_title(title, fontsize=9)
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper right", fontsize=7)
        self.plot.canvas.draw_idle()


class PefRhobPlot(_PlotBase):
    """PEF (y) against RHOB (x) with the matrix, shale and pyrite points and the mixing path.

    Points are ``(rhob, pef)`` pairs; ``samples`` is ``(rhob, pef)`` arrays or None.
    """

    def __init__(self, parent=None):
        super().__init__((5.5, 4), parent)
        self.plot.setMinimumHeight(300)

    def set_data(self, samples: Optional[Tuple[Sequence[float], Sequence[float]]],
                 matrix: Tuple[float, float], shale: Tuple[float, float],
                 pyrite: Tuple[float, float], vpyr=None):
        self._args = (samples, matrix, shale, pyrite, vpyr)
        self._draw(*self._args)

    def clear_data(self, message: str):
        self._args = None
        self._message(message)

    def _draw(self, samples, matrix, shale, pyrite, vpyr):
        ax = self.plot.get_axes()
        chrome = get_plot_chrome()
        xs, ys = [matrix[0], shale[0]], [matrix[1], shale[1]]
        if samples is not None:
            rhob = np.asarray(samples[0], dtype=float)
            pef = np.asarray(samples[1], dtype=float)
            ok = np.isfinite(rhob) & np.isfinite(pef) & (pef > 0)
            rhob, pef = rhob[ok], pef[ok]
            if len(rhob):
                vp = None if vpyr is None else np.asarray(vpyr, dtype=float)[ok]
                if vp is not None and np.isfinite(vp).any():
                    pts = ax.scatter(rhob, pef, s=9, c=vp, cmap="YlOrBr", alpha=0.8, linewidths=0,
                                     zorder=3)
                    bar = self.plot.figure.colorbar(pts, ax=ax, pad=0.02)
                    bar.set_label("VPYR (v/v)", color=chrome["text"])
                    bar.ax.tick_params(colors=chrome["text"])
                else:
                    ax.scatter(rhob, pef, s=9, alpha=0.6, linewidths=0, zorder=3,
                               color=get_plot_color("RHOB"), label=f"Samples ({len(rhob)})")
                xs += [float(rhob.min()), float(rhob.max())]
                ys += [float(pef.min()), float(pef.max())]
        mx, my, marks = mixing_curve(matrix, pyrite)
        ax.plot(mx, my, color=get_plot_color("VPYR"), lw=1.6, zorder=4,
                label="Pyrite mixing direction")
        for frac, (px, py) in marks.items():
            ax.scatter([px], [py], s=14, color=get_plot_color("VPYR"), zorder=5)
            ax.annotate(f"{frac * 100:g}%", (px, py), fontsize=7, color=chrome["text"],
                        xytext=(4, 2), textcoords="offset points")
        ax.scatter([matrix[0]], [matrix[1]], s=60, marker="s", color=get_plot_color("PHIT"),
                   zorder=6, label="Matrix")
        ax.scatter([shale[0]], [shale[1]], s=60, marker="s", color=get_plot_color("VSH"),
                   zorder=6, label="Shale")
        ax.scatter([pyrite[0]], [pyrite[1]], s=60, marker="s", color=get_plot_color("VPYR"),
                   zorder=6, label="Pyrite")
        x_lo, x_hi = min(xs), max(xs)
        pad_x = 0.08 * max(x_hi - x_lo, 0.5)
        pad_y = 0.1 * max(max(ys) - min(ys), 1.0)
        ax.set_xlim(x_lo - pad_x, x_hi + pad_x)
        ax.set_ylim(max(0.0, min(ys) - pad_y), max(ys) + pad_y)
        ax.set_xlabel("RHOB (g/cc)")
        ax.set_ylabel("PEF (b/e)")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper right", fontsize=7)
        self.plot.canvas.draw_idle()
