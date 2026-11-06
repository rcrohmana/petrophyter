"""Variable-m fit plot of the LRLC Workbench (Remediation > Variable m/n).

A read-only picture: the observed m of the wet points against porosity (coloured by Vsh) with
the fitted formula at the P10, P50 and P90 of Vsh and the zone's constant m for reference. The
owner supplies the arrays; nothing here reads the model or runs the analysis.
"""

from typing import Dict, Optional, Sequence

import numpy as np

from modules.lrlc.variable_mn import m_formula
from themes.colors import get_plot_chrome, get_plot_color

from .lrlc_ts_plot import _PlotBase

VSH_LEVELS = (10, 50, 90)


def fitted_curves(coef: Sequence[float], phi_range, vsh, n: int = 80) -> Dict[int, tuple]:
    """``{percentile: (phi_grid, m)}`` of the formula at the P10 / P50 / P90 of ``vsh``."""
    lo, hi = float(phi_range[0]), float(phi_range[1])
    grid = np.linspace(max(lo, 0.02), max(hi, lo + 1e-3), n)
    v = np.asarray(vsh, dtype=float)
    v = v[np.isfinite(v)]
    out = {}
    for q in VSH_LEVELS:
        level = float(np.percentile(v, q)) if v.size else 0.0
        out[q] = (grid, m_formula(grid, np.full_like(grid, level), coef))
    return out


class MnFitPlot(_PlotBase):
    """Observed m (points) and the fitted m against porosity."""

    def __init__(self, parent=None):
        super().__init__((6.5, 4.2), parent)
        self.plot.setMinimumHeight(300)
        self.n_drawn = 0

    def set_data(self, phi, vsh, index, m_obs, coef, scoped_m: Optional[float] = None,
                 clip=(1.0, 4.0), phi_label: str = "PHIE"):
        """``phi`` and ``vsh`` are the zone arrays, ``index`` the positions of the fitted points
        and ``m_obs`` their observed m; ``coef`` the fitted coefficients (None: no curve)."""
        self._args = (phi, vsh, index, m_obs, coef, scoped_m, clip, phi_label)
        self._draw(*self._args)

    def clear_data(self, message: str):
        self._args = None
        self.n_drawn = 0
        self._message(message)

    def _draw(self, phi, vsh, index, m_obs, coef, scoped_m, clip, phi_label):
        ax = self.plot.get_axes()
        chrome = get_plot_chrome()
        phi = np.asarray(phi, dtype=float)
        vsh = np.asarray(vsh, dtype=float)
        idx = np.asarray(index, dtype=int)
        m_obs = np.asarray(m_obs, dtype=float)
        x, v = phi[idx], vsh[idx]
        ok = np.isfinite(x) & np.isfinite(m_obs)
        x, y, v = x[ok], m_obs[ok], v[ok]
        self.n_drawn = int(len(x))
        if len(x):
            if np.isfinite(v).any():
                pts = ax.scatter(x, y, s=12, c=v, cmap="viridis", alpha=0.85, linewidths=0,
                                 zorder=3, label=f"Wet points ({len(x)})")
                bar = self.plot.figure.colorbar(pts, ax=ax, pad=0.02)
                bar.set_label("Vsh (v/v)", color=chrome["text"])
                bar.ax.tick_params(colors=chrome["text"])
            else:
                ax.scatter(x, y, s=12, alpha=0.85, linewidths=0, zorder=3,
                           color=get_plot_color("PHIE"), label=f"Wet points ({len(x)})")
        if coef is not None and len(x):
            curves = fitted_curves(coef, (float(x.min()), float(x.max())), v)
            styles = {10: ":", 50: "-", 90: "--"}
            for q, (grid, m) in curves.items():
                ax.plot(grid, m, color=get_plot_color("M_VAR"), lw=1.6 if q == 50 else 1.1,
                        ls=styles[q], zorder=4, label=f"Fitted m at Vsh P{q}")
        if scoped_m is not None and np.isfinite(scoped_m):
            ax.axhline(float(scoped_m), color=chrome["spine"], lw=1.0, ls="-.", zorder=2,
                       label=f"Zone m {float(scoped_m):.2f}")
        for edge in clip:
            ax.axhline(float(edge), color=chrome["spine"], lw=0.7, ls=":", zorder=1)
        ax.set_xlabel(f"{phi_label} (v/v)")
        ax.set_ylabel("m")
        lo, hi = float(clip[0]), float(clip[1])
        if len(y):
            lo, hi = min(lo, float(y.min())), max(hi, float(y.max()))
        ax.set_ylim(lo - 0.1, hi + 0.1)
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper right", fontsize=7)
        self.plot.canvas.draw_idle()
