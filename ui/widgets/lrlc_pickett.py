"""Pickett plot panel of the LRLC Workbench (Diagnosis > Pickett).

Log-log Rt versus porosity of the last run, the automatic wet points with manual add and
remove boxes, the robust wet-line fit and the explicit Apply step. The panel never runs the
analysis: Apply writes the scoped ``m`` (and ``rw``) of the active well and asks the owner to
mark the well stale (``stale_requested``).
"""

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from matplotlib.widgets import RectangleSelector
from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from modules.lrlc import pickett
from modules.lrlc.methods import METHOD_TEXT
from modules.pipeline import WELL_SOURCES_KEY, temperature_factor
from services.lrlc_service import LrlcService
from themes.colors import get_plot_chrome, get_plot_color, get_rock_type_color
from themes.helpers import set_status

from .method_box import MethodReferenceBox
from .plot_widget import PlotWidget

logger = logging.getLogger(__name__)

PLOT_MIN_HEIGHT = 380
CONTROLS_WIDTH = 340
ALL_ZONES_KEY = ""

STATUS_TEXT = {
    "ok": "The fit is usable. Check that the wet points really lie on the water line.",
    "too_few_points": ("Too few wet points ({n} found, {min} needed). Raise the clay limit or "
                       "the wet quantile, or add points with Add box."),
    "narrow_porosity_range": ("The wet points cover less than 0.2 decades of porosity, which "
                              "is too narrow to fit a slope. Widen the selection, or switch "
                              "the fit mode to Rw only."),
    "m_outside_range": ("The fitted m is outside 1.3 to 3.0. It is shown for inspection and "
                        "cannot be applied."),
    "rw_outside_range": ("The fitted Rw is outside 0.005 to 10 ohm.m. It is shown for "
                         "inspection and cannot be applied."),
    "no_data": "No usable wet points. Check the clay limit and the porosity cut-off.",
}


def forward_wheel_to_scroll(widget: QWidget, event) -> bool:
    """Hand a wheel event from a matplotlib canvas to the nearest scroll area above it."""
    parent = widget.parent()
    while parent is not None and not isinstance(parent, QScrollArea):
        parent = parent.parent()
    if parent is None:
        return False
    QApplication.sendEvent(parent.verticalScrollBar(), event)
    return True


def zone_labels(df: pd.DataFrame) -> np.ndarray:
    """Zone label of every result row ('' when the run had no zones)."""
    if "ZONE" in df.columns:
        return df["ZONE"].fillna("").astype(str).to_numpy()
    return np.full(len(df), "", dtype=object)


def zone_sources(ds, zone: Optional[str]) -> Dict:
    """Parameter table of the last run for a zone (the well table when the zone is not there)."""
    sources = (getattr(ds, "summary", None) or {}).get("param_sources") or {}
    if zone and isinstance(sources.get(zone), dict):
        return sources[zone]
    return sources.get(WELL_SOURCES_KEY) or {}


def source_value(table: Dict, name: str, default: float) -> float:
    try:
        return float(table[name]["value"])
    except (KeyError, TypeError, ValueError):
        return default


class PickettPanel(QWidget):
    """Pickett plot with wet-point fit. Public: ``set_context``, ``refresh_theme``."""

    stale_requested = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = None
        self.ds = None
        self.zone: Optional[str] = None
        self._loading = False
        self._manual: Dict[Tuple[str, str], List[tuple]] = {}
        self._box_mode: Optional[str] = None
        self._selector = None
        self._fit: Optional[pickett.PickettFit] = None
        self._pending_rw: Optional[bool] = None
        self._settings = dict(pickett.DEFAULT_SETTINGS)
        self._build()

    # ------------------------------------------------------------------ layout
    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        left = QWidget()
        left.setFixedWidth(CONTROLS_WIDTH)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox("Wet-point selection")
        form = QFormLayout(group)
        self.phi_source = QComboBox()
        self.phi_source.addItems(["PHIE", "PHIT"])
        self.color_by = QComboBox()
        self.color_by.addItem("VSH", "VSH")
        self.color_by.addItem("Zone", "zone")
        self.vsh_max = self._dspin(0.0, 1.0, 0.05, 2)
        self.phi_min = self._dspin(0.0, 0.5, 0.01, 3)
        self.wet_quantile = self._dspin(0.01, 0.5, 0.05, 2)
        self.n_bins = QSpinBox()
        self.n_bins.setRange(2, 40)
        self.min_points = QSpinBox()
        self.min_points.setRange(3, 500)
        self.fit_mode = QComboBox()
        self.fit_mode.addItem("m and Rw", "m_and_rw")
        self.fit_mode.addItem("Rw only (m fixed)", "rw_only")
        for label, widget in (("Porosity", self.phi_source), ("Colour by", self.color_by),
                              ("Clay limit (VSH max)", self.vsh_max),
                              ("Porosity cut-off", self.phi_min),
                              ("Wet quantile", self.wet_quantile),
                              ("Porosity bins", self.n_bins),
                              ("Minimum wet points", self.min_points),
                              ("Fit", self.fit_mode)):
            form.addRow(label, widget)
        ll.addWidget(group)

        boxes = QGroupBox("Manual wet points")
        bl = QVBoxLayout(boxes)
        row = QHBoxLayout()
        self.add_box_btn = QPushButton("Add box")
        self.remove_box_btn = QPushButton("Remove box")
        for btn in (self.add_box_btn, self.remove_box_btn):
            btn.setCheckable(True)
            row.addWidget(btn)
        bl.addLayout(row)
        self.reset_btn = QPushButton("Reset to automatic")
        bl.addWidget(self.reset_btn)
        self.box_note = QLabel("Drag a rectangle on the plot while Add box or Remove box is "
                               "on. Boxes are kept for this session only.")
        self.box_note.setWordWrap(True)
        set_status(self.box_note, "muted")
        bl.addWidget(self.box_note)
        ll.addWidget(boxes)
        ll.addStretch(1)
        root.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        set_status(self.status_label, "muted")
        rl.addWidget(self.status_label)

        self.plot = PlotWidget(figsize=(8, 5))
        self.plot.setMinimumHeight(PLOT_MIN_HEIGHT)
        self.plot.canvas.installEventFilter(self)
        rl.addWidget(self.plot, 1)

        self.readout = QLabel("")
        self.readout.setWordWrap(True)
        self.readout.setTextFormat(Qt.TextFormat.RichText)
        rl.addWidget(self.readout)
        self.fit_note = QLabel("")
        self.fit_note.setWordWrap(True)
        set_status(self.fit_note, "muted")
        rl.addWidget(self.fit_note)

        apply_row = QHBoxLayout()
        self.apply_m_btn = QPushButton("Apply m")
        self.apply_mrw_btn = QPushButton("Apply m and Rw")
        apply_row.addWidget(self.apply_m_btn)
        apply_row.addWidget(self.apply_mrw_btn)
        apply_row.addStretch(1)
        rl.addLayout(apply_row)

        self.confirm_box = QWidget()
        cl = QVBoxLayout(self.confirm_box)
        cl.setContentsMargins(0, 0, 0, 0)
        self.confirm_label = QLabel("")
        self.confirm_label.setWordWrap(True)
        set_status(self.confirm_label, "warning")
        cl.addWidget(self.confirm_label)
        crow = QHBoxLayout()
        self.confirm_btn = QPushButton("Write to well")
        self.cancel_btn = QPushButton("Cancel")
        crow.addWidget(self.confirm_btn)
        crow.addWidget(self.cancel_btn)
        crow.addStretch(1)
        cl.addLayout(crow)
        self.confirm_box.setVisible(False)
        rl.addWidget(self.confirm_box)

        self.method_box = MethodReferenceBox()
        self.method_box.set_method(METHOD_TEXT["pickett"])
        rl.addWidget(self.method_box)
        root.addWidget(right, 1)

        for w in (self.phi_source, self.color_by, self.fit_mode):
            w.currentIndexChanged.connect(self._on_setting)
        for w in (self.vsh_max, self.phi_min, self.wet_quantile, self.n_bins, self.min_points):
            w.valueChanged.connect(self._on_setting)
        self.add_box_btn.toggled.connect(lambda on: self._set_box_mode("add", on))
        self.remove_box_btn.toggled.connect(lambda on: self._set_box_mode("remove", on))
        self.reset_btn.clicked.connect(self.reset_manual)
        self.apply_m_btn.clicked.connect(lambda: self.request_apply(False))
        self.apply_mrw_btn.clicked.connect(lambda: self.request_apply(True))
        self.confirm_btn.clicked.connect(self.confirm_apply)
        self.cancel_btn.clicked.connect(self.cancel_apply)
        self._update_buttons()

    @staticmethod
    def _dspin(lo, hi, step, decimals) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(lo, hi)
        spin.setSingleStep(step)
        spin.setDecimals(decimals)
        return spin

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel and forward_wheel_to_scroll(self, event):
            return True
        return super().eventFilter(obj, event)

    # ----------------------------------------------------------------- context
    def set_context(self, model, ds, zone: Optional[str] = None):
        """Show the well ``ds`` (None = nothing) for a zone (None = all zones)."""
        self.model = model
        self.ds = ds
        self.zone = zone or None
        self.cancel_apply()
        self._load_settings()
        self._replot()

    def refresh_theme(self):
        self.plot.update_theme_colors()
        self._replot()

    # ---------------------------------------------------------------- settings
    def _load_settings(self):
        s = dict(pickett.DEFAULT_SETTINGS)
        if self.model is not None:
            stored = self.model.project.lrlc.get("pickett")
            if isinstance(stored, dict):
                s.update({k: v for k, v in stored.items() if k in s})
        self._settings = s
        self._loading = True
        try:
            self.phi_source.setCurrentText(str(s["phi_source"]))
            self.color_by.setCurrentIndex(max(self.color_by.findData(s["color_by"]), 0))
            self.fit_mode.setCurrentIndex(max(self.fit_mode.findData(s["fit_mode"]), 0))
            self.vsh_max.setValue(float(s["vsh_max"]))
            self.phi_min.setValue(float(s["phi_min"]))
            self.wet_quantile.setValue(float(s["wet_quantile"]))
            self.n_bins.setValue(int(s["n_bins"]))
            self.min_points.setValue(int(s["min_points"]))
        finally:
            self._loading = False

    def _on_setting(self, *_):
        if self._loading:
            return
        values = {
            "phi_source": self.phi_source.currentText(),
            "color_by": self.color_by.currentData(),
            "fit_mode": self.fit_mode.currentData(),
            "vsh_max": self.vsh_max.value(),
            "phi_min": self.phi_min.value(),
            "wet_quantile": self.wet_quantile.value(),
            "n_bins": self.n_bins.value(),
            "min_points": self.min_points.value(),
        }
        for key, value in values.items():
            if self._settings.get(key) != value:
                self._settings[key] = value
                if self.model is not None:
                    LrlcService.set_setting(self.model, "pickett", key, value)
        self.cancel_apply()
        self._replot()

    # ------------------------------------------------------------ manual boxes
    @property
    def _manual_key(self) -> Tuple[str, str]:
        return (getattr(self.ds, "key", ""), self.zone or ALL_ZONES_KEY)

    def manual_boxes(self) -> List[tuple]:
        return list(self._manual.get(self._manual_key, []))

    def manual_boxes_for(self, well_key: str, zone: Optional[str]) -> List[tuple]:
        """The manual boxes held for a well and zone (what the fit of the m curve shares)."""
        return list(self._manual.get((well_key, zone or ALL_ZONES_KEY), []))

    def add_manual_box(self, kind: str, phi_lo, phi_hi, rt_lo, rt_hi):
        """Add an 'add' or 'remove' box in plot coordinates (what the selector calls)."""
        if kind not in ("add", "remove"):
            raise ValueError(kind)
        box = (kind, float(min(phi_lo, phi_hi)), float(max(phi_lo, phi_hi)),
               float(min(rt_lo, rt_hi)), float(max(rt_lo, rt_hi)))
        self._manual.setdefault(self._manual_key, []).append(box)
        self.cancel_apply()
        self._replot()

    def reset_manual(self):
        self._manual.pop(self._manual_key, None)
        self.cancel_apply()
        self._replot()

    def _set_box_mode(self, kind, on):
        other = self.remove_box_btn if kind == "add" else self.add_box_btn
        if on:
            other.blockSignals(True)
            other.setChecked(False)
            other.blockSignals(False)
            self._box_mode = kind
        elif self._box_mode == kind:
            self._box_mode = None
        if self._selector is not None:
            self._selector.set_active(self._box_mode is not None)

    def _on_select(self, press, release):
        if self._box_mode is None or press.xdata is None or release.xdata is None:
            return
        if press.xdata == release.xdata or press.ydata == release.ydata:
            return
        self.add_manual_box(self._box_mode, press.xdata, release.xdata,
                            press.ydata, release.ydata)

    # -------------------------------------------------------------------- data
    def _frame(self):
        """Filtered result rows for the zone, or None."""
        ds = self.ds
        if ds is None or getattr(ds, "results", None) is None or len(ds.results) == 0:
            return None
        df = ds.results
        if self.zone:
            df = df[zone_labels(df) == self.zone]
        return df

    def _rt_column(self, df) -> Optional[str]:
        mapped = (self.ds.curve_mapping or {}).get("RT")
        for name in (mapped, "RT"):
            if name and name in df.columns:
                return name
        return None

    def _temperature_factor(self, df) -> Optional[np.ndarray]:
        """Arps factor per sample from the well's current parameters (None when it is off).

        Computed with ``pipeline.temperature_factor`` on the result rows; a mapped TVD curve
        that is not in the results is interpolated from the log onto the result depths.
        """
        if self.model is None or "DEPTH" not in df.columns:
            return None
        try:
            params = self.model.params_for_well(self.ds)
            if not params.get("temp_correction"):
                return None
            mapping = dict(self.ds.curve_mapping or {})
            frame = df[["DEPTH"]].copy()
            tvd = mapping.get("TVD")
            if tvd and tvd in df.columns:
                frame[tvd] = df[tvd]
            elif tvd and tvd not in ("None", "DEPTH"):
                log = getattr(self.ds, "las_data", None)
                if log is not None and tvd in log.columns and "DEPTH" in log.columns:
                    ok = log["DEPTH"].notna() & log[tvd].notna()
                    frame[tvd] = np.interp(frame["DEPTH"].to_numpy(dtype=float),
                                           log.loc[ok, "DEPTH"].to_numpy(dtype=float),
                                           log.loc[ok, tvd].to_numpy(dtype=float))
            factor = temperature_factor(frame, params, mapping)
            return None if factor is None else np.asarray(factor, dtype=float)
        except Exception:      # noqa: BLE001 - the plot falls back to the raw Rt
            logger.exception("Pickett temperature factor failed; plotting raw Rt")
            return None

    # -------------------------------------------------------------------- plot
    def _replot(self):
        self._selector = None
        self._fit = None
        fig = self.plot.figure
        fig.clear()
        df = self._frame()
        if df is None:
            self._show_message("Run the analysis first")
            self._finish_plot()
            return
        rt_col = self._rt_column(df)
        phi_col = self._settings["phi_source"]
        if rt_col is None or phi_col not in df.columns:
            self._show_message("Run the analysis first" if rt_col is None else
                               f"{phi_col} is not in the results.")
            self._finish_plot()
            return

        s = self._settings
        phi = pd.to_numeric(df[phi_col], errors="coerce").to_numpy(dtype=float)
        rt = pd.to_numeric(df[rt_col], errors="coerce").to_numpy(dtype=float)
        vsh = (pd.to_numeric(df["VSH"], errors="coerce").to_numpy(dtype=float)
               if "VSH" in df.columns else np.full(len(df), np.nan))
        zones = zone_labels(df)
        factor = self._temperature_factor(df)
        normalised = factor is not None
        if normalised:
            rt = pickett.normalise_rt_for_temperature(rt, factor)

        with np.errstate(invalid="ignore"):
            keep = np.isfinite(phi) & np.isfinite(rt) & (rt > 0) & (phi >= s["phi_min"]) & (phi > 0)
        if not keep.any():
            self._show_message("No samples with a usable porosity and Rt for this selection.")
            self._finish_plot()
            return
        phi, rt, vsh, zones = phi[keep], rt[keep], vsh[keep], zones[keep]

        manual = self.manual_boxes()
        wet = pickett.wet_points(phi, rt, vsh, s, manual)
        table = zone_sources(self.ds, self.zone)
        a = source_value(table, "a", 1.0)
        m_cur = source_value(table, "m", 2.0)
        n_cur = source_value(table, "n", 2.0)
        rw_cur = source_value(table, "rw", float("nan"))
        fit = pickett.fit_pickett(phi, rt, wet, a=a, m_current=m_cur, fit_mode=s["fit_mode"],
                                  min_points=int(s["min_points"]))
        self._fit = fit

        chrome = get_plot_chrome()
        ax = fig.add_subplot(111)
        self.plot._style_axes(ax)
        ax.set_xscale("log")
        ax.set_yscale("log")
        self._scatter(ax, fig, phi, rt, vsh, zones, chrome)
        if wet.any():
            ax.scatter(phi[wet], rt[wet], s=14, facecolors="none",
                       edgecolors=get_plot_color("PAY"), linewidths=1.0,
                       label=f"Wet points ({int(wet.sum())})", zorder=4)
        x_lo, x_hi = float(phi.min()) * 0.9, float(phi.max()) * 1.1
        grid = np.logspace(np.log10(x_lo), np.log10(x_hi), 60)
        if np.isfinite(rw_cur):
            for sw in s["iso_sw"]:
                y = pickett.iso_sw_line(grid, a, rw_cur, m_cur, n_cur, sw)
                is_wet = abs(float(sw) - 1.0) < 1e-9
                label = "Archie Sw = 1 (current parameters)" if is_wet else None
                ax.plot(grid, y, color=get_plot_color("BVW") if is_wet else chrome["spine"],
                        lw=1.4 if is_wet else 0.8, ls="-" if is_wet else "--",
                        label=label, zorder=3)
                if not is_wet:
                    ax.annotate(f"Sw {float(sw):.1f}", (grid[-1], y[-1]), fontsize=7,
                                color=chrome["text"], ha="right", va="bottom")
        if fit.status != "no_data" and np.isfinite(fit.a_rw):
            fm = fit.m if s["fit_mode"] != "rw_only" else m_cur
            ax.plot(grid, fit.a_rw * np.power(grid, -fm), color=get_plot_color("LRLC_FLAG"),
                    lw=1.8, label="Wet-line fit", zorder=5)
        ytop = float(np.nanmax(rt))
        ybot = float(np.nanmin(rt))
        ax.set_xlim(x_lo, x_hi)
        ax.set_ylim(ybot * 0.8, ytop * 1.25)
        for kind, p0, p1, r0, r1 in manual:
            color = get_plot_color("PAY") if kind == "add" else get_plot_color("SW_ARCHIE")
            ax.fill([p0, p1, p1, p0], [r0, r0, r1, r1], facecolor=color, alpha=0.12,
                    edgecolor=color, lw=1.0, zorder=2)
        ax.set_xlabel(f"{phi_col} (v/v)")
        ax.set_ylabel("Rt at Rw reference temperature (ohm.m)" if normalised
                      else "Rt (ohm.m)")
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(loc="upper right", fontsize=8)

        self._selector = RectangleSelector(ax, self._on_select, useblit=False, interactive=False,
                                           button=[1], minspanx=0, minspany=0)
        self._selector.set_active(self._box_mode is not None)
        self._finish_plot()
        self._show_fit(fit, a, rw_cur, int(wet.sum()), normalised)

    def _scatter(self, ax, fig, phi, rt, vsh, zones, chrome):
        if self._settings["color_by"] == "zone" and len(set(zones)) > 0:
            names = sorted(set(zones), key=str)
            for i, name in enumerate(names):
                sel = zones == name
                ax.scatter(phi[sel], rt[sel], s=6, alpha=0.55, linewidths=0,
                           color=get_rock_type_color(i + 1, max(len(names), 2)),
                           label=str(name) if name else "All samples", zorder=2)
            return
        finite = np.isfinite(vsh)
        if finite.any():
            sc = ax.scatter(phi[finite], rt[finite], c=vsh[finite], cmap="viridis", vmin=0.0,
                            vmax=max(float(np.nanmax(vsh)), 0.05), s=6, alpha=0.6,
                            linewidths=0, zorder=2)
            cbar = fig.colorbar(sc, ax=ax, pad=0.02)
            cbar.set_label("VSH (v/v)", color=chrome["text"])
            cbar.ax.tick_params(colors=chrome["text"])
            cbar.outline.set_edgecolor(chrome["spine"])
        if (~finite).any():
            ax.scatter(phi[~finite], rt[~finite], s=6, alpha=0.5, linewidths=0,
                       color=chrome["spine"], zorder=2)

    def _show_message(self, text):
        ax = self.plot.figure.add_subplot(111)
        self.plot._style_axes(ax)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.text(0.5, 0.5, text, ha="center", va="center", transform=ax.transAxes,
                color=get_plot_chrome()["text"])
        self.status_label.setText(text)
        set_status(self.status_label, "muted")
        self.readout.setText("")
        self.fit_note.setText("")
        self._update_buttons()

    def _finish_plot(self):
        self.plot.canvas.draw_idle()
        self._update_buttons()

    # ----------------------------------------------------------------- readout
    def _show_fit(self, fit, a, rw_cur, n_wet, normalised):
        status = fit.status
        text = STATUS_TEXT.get(status, status).format(n=n_wet, min=int(self._settings["min_points"]))
        scope = f"zone {self.zone}" if self.zone else "the whole well"
        self.status_label.setText(f"Pickett fit for {scope}: {text}")
        set_status(self.status_label, "success" if status == "ok" else "warning")
        if np.isfinite(fit.m):
            m_text = (f"{fit.m:.2f} (fixed)" if self._settings["fit_mode"] == "rw_only"
                      else f"{fit.m:.2f} ± {fit.se_m:.2f}")
            self.readout.setText(
                f"<b>m</b> {m_text} &nbsp; <b>a·Rw</b> {fit.a_rw:.4f} &nbsp; "
                f"<b>Rw</b> {fit.rw:.4f} ohm.m (a = {a:g}) &nbsp; <b>wet points</b> "
                f"{fit.n_points} &nbsp; <b>r²</b> {fit.r2:.3f}")
        else:
            self.readout.setText(f"<b>Wet points</b> {n_wet}")
        notes = []
        if np.isfinite(rw_cur):
            notes.append(f"Current Rw {rw_cur:.4f} ohm.m.")
        notes.append("Wet points must be water-bearing: a hydrocarbon-bearing envelope "
                     "overstates Rw." if status != "ok" else
                     "Check that the wet points are water-bearing.")
        self.fit_note.setText(" ".join(notes))
        self._update_buttons()

    # ------------------------------------------------------------------- apply
    def _update_buttons(self):
        ok = self._fit is not None and self._fit.status == "ok" and self.ds is not None \
            and self.model is not None
        self.apply_m_btn.setEnabled(bool(ok))
        self.apply_mrw_btn.setEnabled(bool(ok))

    def request_apply(self, apply_rw: bool):
        """Show the inline confirmation (the write happens in :meth:`confirm_apply`)."""
        if not (self.apply_m_btn.isEnabled() and self._fit is not None):
            return
        self._pending_rw = bool(apply_rw)
        well = getattr(self.ds, "display_name", None) or getattr(self.ds, "key", "")
        if self.zone:
            where = (f"the well-zone scope of {well}, zone {self.zone}. That zone becomes its "
                     "own segment, so it re-estimates its Swirr and other automatic values")
        else:
            where = f"the well scope of {well}"
        what = f"m = {self._fit.m:.3f}"
        extra = ""
        if apply_rw:
            what += f" and Rw = {self._fit.rw:.4f} ohm.m"
            extra = " Rw in that scope switches from automatic to manual."
        self.confirm_label.setText(
            f"Write {what} to {where}.{extra} Nothing is recomputed until you run the analysis.")
        self.confirm_box.setVisible(True)

    def cancel_apply(self):
        self._pending_rw = None
        self.confirm_box.setVisible(False)

    def confirm_apply(self) -> bool:
        if self._pending_rw is None or self._fit is None or self.model is None:
            return False
        apply_rw = self._pending_rw
        fit, ds, zone = self._fit, self.ds, self.zone
        self.cancel_apply()
        if not LrlcService.apply_pickett(self.model, ds, zone, fit, apply_rw):
            return False
        what = "m and Rw" if apply_rw else "m"
        self.status_label.setText(
            f"Applied {what} to the well. Run the analysis to use the new values.")
        set_status(self.status_label, "success")
        self.stale_requested.emit([ds.key])
        return True
