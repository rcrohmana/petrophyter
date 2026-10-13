"""
Uncertainty Tab for Petrophyter PyQt
Shows the latest Monte Carlo result (P90/P50/P10 table, histogram with exceedance curve,
tornado, diagnostics). The tab only reads ``project.uncertainty_result``; the run itself is
started by the main window (P2 uncertainty spec, section 6).
"""

import logging

import numpy as np
import pandas as pd
from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from modules.uncertainty import NOT_VARIED
from services.uncertainty_service import result_is_stale
from themes.colors import get_plot_color
from themes.helpers import set_status
from ..widgets.plot_widget import PlotWidget
from ..widgets.table_model import PandasTableModel


logger = logging.getLogger(__name__)

METRICS = (
    ("hcpv_net_pay", "HCPV net pay (ft)"),
    ("hcpv_net_res", "HCPV net reservoir (ft)"),
    ("net_pay", "Net pay (ft)"),
    ("avg_phie_pay", "Avg PHIE in pay"),
    ("avg_sw_pay", "Avg Sw in pay"),
)
TORNADO_METRICS = ("hcpv_net_pay", "net_pay")
FIELD = "field"
EMPTY_TEXT = ("No Monte Carlo result yet. Enable distributions on Parameters → Uncertainty, "
              "then Analysis → Run Uncertainty…")
P90_NOTE = "P90 = low case (exceeded with 90 % probability)"
FIELD_NOTE = ("Field percentiles come from the per-realisation field totals, not from adding "
              "well percentiles.")
NO_TORNADO_NOTE = "The tornado is available for HCPV net pay and Net pay only."
DET_STALE_NOTE = ("Deterministic column uses the current parameters; the Summary tab is out of "
                  "date.")
TABLE_COLUMNS = ("Scope", "P90", "P50", "P10", "Mean", "Deterministic", "N valid", "P(zero)")
TORNADO_COLUMNS = ("Parameter", "Low input", "High input", "Output at low", "Output at high",
                   "Swing", "Rank corr. (field)")
PLOT_MIN_HEIGHT = 380


def _num(value, digits=3) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "" if value is None else str(value)
    return "" if not np.isfinite(v) else f"{v:.{digits}g}"


def _pct(frac) -> str:
    try:
        v = float(frac)
    except (TypeError, ValueError):
        return ""
    return "" if not np.isfinite(v) else f"{100.0 * v:.1f}%"


def _fit_table_height(table):
    """Show every row (no vertical scrollbar)."""
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    header = table.horizontalHeader()
    h = max(header.height(), header.sizeHint().height())
    h += sum(table.rowHeight(r) for r in range(table.model().rowCount()))
    h += 2 * table.frameWidth() + 2
    table.setFixedHeight(h)


class UncertaintyTab(QWidget):
    """Uncertainty tab: header, controls, percentile table, histogram, tornado, diagnostics."""

    run_requested = pyqtSignal()
    cancel_requested = pyqtSignal()

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self._result = None             # the result the table and plots were built from
        self._table_key = None          # (result, metric) the table shows
        self._plot_key = None           # (result, metric, scope) the plots show
        self._scope = FIELD
        self._row_scopes = []
        self._updating = False
        self._setup_ui()
        self.update_display()

    # ------------------------------------------------------------------ UI
    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.page_scroll = QScrollArea()
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.page = QWidget()
        v = QVBoxLayout(self.page)
        v.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Controls
        row = QHBoxLayout()
        row.addWidget(QLabel("Metric"))
        self.metric_combo = QComboBox()
        for key, text in METRICS:
            self.metric_combo.addItem(text, key)
        row.addWidget(self.metric_combo)
        self.run_button = QPushButton("Run Monte Carlo")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        row.addWidget(self.run_button)
        row.addWidget(self.cancel_button)
        self.progress_label = QLabel("")
        set_status(self.progress_label, "muted")
        row.addWidget(self.progress_label)
        row.addStretch(1)
        v.addLayout(row)
        self.run_button.clicked.connect(self.run_requested.emit)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self.metric_combo.currentIndexChanged.connect(self._on_metric_changed)

        # Empty state
        self.empty_label = QLabel(EMPTY_TEXT)
        self.empty_label.setWordWrap(True)
        self.empty_label.setObjectName("PlaceholderLabel")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.empty_label)

        # Result content
        self.content = QWidget()
        cl = QVBoxLayout(self.content)
        cl.setContentsMargins(0, 0, 0, 0)

        self.header_label = QLabel("")
        self.header_label.setWordWrap(True)
        cl.addWidget(self.header_label)
        self.p90_label = QLabel(P90_NOTE)
        set_status(self.p90_label, "muted")
        cl.addWidget(self.p90_label)
        self.not_varied_label = QLabel("Not varied: " + NOT_VARIED)
        self.not_varied_label.setWordWrap(True)
        set_status(self.not_varied_label, "muted")
        cl.addWidget(self.not_varied_label)
        self.stale_chip = QLabel("Out of date")
        set_status(self.stale_chip, "warning")
        self.stale_chip.setVisible(False)
        cl.addWidget(self.stale_chip)
        self.det_note = QLabel(DET_STALE_NOTE)
        self.det_note.setWordWrap(True)
        set_status(self.det_note, "warning")
        self.det_note.setVisible(False)
        cl.addWidget(self.det_note)

        self.table_view = QTableView()
        self.table_view.setModel(PandasTableModel(pd.DataFrame(), float_decimals=3))
        self.table_view.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        cl.addWidget(self.table_view)
        self.table_note = QLabel(FIELD_NOTE)
        self.table_note.setWordWrap(True)
        set_status(self.table_note, "muted")
        cl.addWidget(self.table_note)

        self.scope_label = QLabel("")
        self.scope_label.setObjectName("SectionLabel")
        cl.addWidget(self.scope_label)
        self.plot_hist = PlotWidget(figsize=(8, 4))
        self.plot_hist.setMinimumHeight(PLOT_MIN_HEIGHT)
        self.plot_hist.canvas.installEventFilter(self)
        cl.addWidget(self.plot_hist)

        self.tornado_note = QLabel(NO_TORNADO_NOTE)
        self.tornado_note.setWordWrap(True)
        set_status(self.tornado_note, "muted")
        cl.addWidget(self.tornado_note)
        self.tornado_box = QWidget()
        tl = QVBoxLayout(self.tornado_box)
        tl.setContentsMargins(0, 0, 0, 0)
        self.plot_tornado = PlotWidget(figsize=(8, 4))
        self.plot_tornado.setMinimumHeight(PLOT_MIN_HEIGHT)
        self.plot_tornado.canvas.installEventFilter(self)
        tl.addWidget(self.plot_tornado)
        self.tornado_view = QTableView()
        self.tornado_view.setModel(PandasTableModel(pd.DataFrame(), float_decimals=3))
        self.tornado_view.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.tornado_view.model().modelReset.connect(lambda: _fit_table_height(self.tornado_view))
        tl.addWidget(self.tornado_view)
        cl.addWidget(self.tornado_box)

        diag_title = QLabel("DIAGNOSTICS")
        diag_title.setObjectName("SectionLabel")
        cl.addWidget(diag_title)
        self.diag_label = QLabel("")
        self.diag_label.setWordWrap(True)
        self.diag_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cl.addWidget(self.diag_label)

        v.addWidget(self.content)
        self.page_scroll.setWidget(self.page)
        outer.addWidget(self.page_scroll)

        self.table_view.selectionModel().currentRowChanged.connect(self._on_row_changed)

    def eventFilter(self, obj, event):
        """The matplotlib canvas swallows wheel events; hand them to the page scroll area."""
        if event.type() == QEvent.Type.Wheel:
            QApplication.sendEvent(self.page_scroll.verticalScrollBar(), event)
            return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------ running
    def set_running(self, running: bool):
        self.run_button.setEnabled(not running)
        self.cancel_button.setEnabled(bool(running))
        if not running:
            self.progress_label.setText("")

    def set_progress(self, done: int, total: int):
        self.progress_label.setText(f"Running {int(done)}/{int(total)}")

    # ------------------------------------------------------------- state
    @property
    def current_metric(self) -> str:
        return self.metric_combo.currentData()

    def _result_now(self):
        return getattr(self.model.project, "uncertainty_result", None)

    def update_display(self):
        """Rebuild the table when the result or metric changed; draw plots when visible."""
        result = self._result_now()
        if result is not self._result:
            self._result = result
            self._table_key = None
            self._plot_key = None
            self._scope = FIELD
        has = result is not None
        self.empty_label.setVisible(not has)
        self.content.setVisible(has)
        if has:
            if self._table_key is None or self._table_key[0] is not result \
                    or self._table_key[1] != self.current_metric:
                self._rebuild_table()
            self._draw_plots_if_needed()
        self.refresh_stale()

    def refresh_stale(self):
        """Cheap: recompute the Out-of-date chip and the Summary note; no table or plot work."""
        result = self._result_now()
        if result is None:
            self.stale_chip.setVisible(False)
            self.det_note.setVisible(False)
            return
        self.stale_chip.setVisible(self._is_stale(result))
        included = [self.model.project.get(k) for k in getattr(result, "basis", {})]
        self.det_note.setVisible(any(ds is not None and ds.stale for ds in included))

    def _is_stale(self, result) -> bool:
        return result_is_stale(self.model, result)

    # ------------------------------------------------------------- table
    def _on_metric_changed(self, *_):
        if self._result is not None:
            self.update_display()

    def _rebuild_table(self):
        result, metric = self._result, self.current_metric
        self._table_key = (result, metric)
        self._plot_key = None
        rows, scopes = [], []

        def add(label, scope):
            st = result.stats.get((scope, metric))
            det = result.deterministic.get((scope, metric))
            nan = float("nan")
            if st:
                rows.append([label, st["p90"], st["p50"], st["p10"], st["mean"],
                             det if det is not None else nan,
                             str(int(st["n_valid"])), _pct(st.get("prob_zero"))])
            else:
                rows.append([label, nan, nan, nan, nan, det if det is not None else nan, "", ""])
            scopes.append(scope)

        add("Field", FIELD)
        for w in result.wells:
            add(w["name"], w["key"])
            for zone in (result.zones or {}).get(w["key"], []):
                add("  " + str(zone), (w["key"], zone))
        df = pd.DataFrame(rows, columns=list(TABLE_COLUMNS))
        self._row_scopes = scopes
        self._updating = True
        try:
            self.table_view.model().set_dataframe(df)
            if self._scope not in scopes:
                self._scope = FIELD
            self.table_view.selectRow(scopes.index(self._scope))
        finally:
            self._updating = False
        self.table_view.resizeColumnsToContents()
        self.table_view.horizontalHeader().setStretchLastSection(True)
        _fit_table_height(self.table_view)
        self._render_header()
        self._render_diagnostics()

    def _on_row_changed(self, current, _previous):
        if self._updating or not current.isValid():
            return
        row = current.row()
        if 0 <= row < len(self._row_scopes) and self._row_scopes[row] != self._scope:
            self._scope = self._row_scopes[row]
            self._draw_plots_if_needed()

    # ------------------------------------------------------------ header
    def _render_header(self):
        r = self._result
        sampling = str(getattr(r, "sampling", "") or "")
        self.header_label.setText(
            f"Seed {r.seed}  |  N {r.n}  |  Sampling {sampling}  |  "
            f"{float(r.elapsed_s):.1f} s")

    def _render_diagnostics(self):
        r = self._result
        lines = []
        clipped = [(p, s) for p, s in (getattr(r, "clipped", None) or {}).items()
                   if s and float(s) > 0]
        if clipped:
            lines.append("Clipped to bounds: " + ", ".join(f"{p} {_pct(s)}" for p, s in clipped))
        pz = []
        for w in r.wells:
            st = r.stats.get((w["key"], "net_pay"))
            if st:
                pz.append(f"{w['name']} {_pct(st.get('prob_zero'))}")
        if pz:
            lines.append("P(zero net pay): " + ", ".join(pz))
        for e in getattr(r, "excluded", None) or []:
            lines.append(f"Excluded: {e['name']} ({e['reason']})")
        lines.extend(str(w) for w in (getattr(r, "warnings", None) or []))
        self.diag_label.setText("\n".join(lines) if lines else "No diagnostics.")

    # ------------------------------------------------------------- plots
    def showEvent(self, event):
        super().showEvent(event)
        self._draw_plots_if_needed()

    def _scope_title(self) -> str:
        r, scope = self._result, self._scope
        if scope == FIELD:
            return "Field"
        names = {w["key"]: w["name"] for w in r.wells}
        if isinstance(scope, tuple):
            return f"{names.get(scope[0], scope[0])} / {scope[1]}"
        return names.get(scope, str(scope))

    def _draw_plots_if_needed(self):
        if self._result is None or not self.isVisible():
            return
        key = (self._result, self.current_metric, self._scope)
        if self._plot_key is not None and self._plot_key[0] is key[0] \
                and self._plot_key[1:] == key[1:]:
            return
        self._plot_key = key
        self.scope_label.setText(f"{self._scope_title()} – {self.metric_combo.currentText()}")
        self._draw_hist()
        self._draw_tornado()

    def _draw_hist(self):
        r, metric, scope = self._result, self.current_metric, self._scope
        ax = self.plot_hist.get_axes()
        vals = np.asarray(r.values.get((scope, metric), []), dtype=float)
        vals = vals[np.isfinite(vals)]
        if vals.size == 0:
            ax.text(0.5, 0.5, "No finite values", ha="center", va="center",
                    transform=ax.transAxes)
            self.plot_hist.refresh()
            return
        ax.hist(vals, bins=30, color=get_plot_color("HCPV"), alpha=0.6)
        ax.set_xlabel(self.metric_combo.currentText())
        ax.set_ylabel("Realisations")
        st = r.stats.get((scope, metric)) or {}
        top = ax.get_ylim()[1]
        for name, colour in (("p90", "SW"), ("p50", "NET_PAY"), ("p10", "PHIE")):
            if name in st and np.isfinite(st[name]):
                ax.axvline(st[name], color=get_plot_color(colour), lw=1.5)
                ax.text(st[name], top, f" {name.upper()}", color=get_plot_color(colour),
                        va="top", ha="left", fontsize=8)
        det = r.deterministic.get((scope, metric))
        if det is not None and np.isfinite(det):
            ax.axvline(det, color=get_plot_color("RT"), ls="--", lw=1.5, label="Deterministic")
            ax.legend(loc="upper right", fontsize=8)
        ax2 = ax.twinx()
        xs = np.sort(vals)
        ax2.step(xs, 100.0 * (xs.size - np.arange(xs.size)) / xs.size, where="post",
                 color=get_plot_color("GROSS_SAND"), lw=1.2)
        ax2.set_ylim(0, 100)
        ax2.set_ylabel("Exceedance (%)")
        self.plot_hist.refresh()

    def _draw_tornado(self):
        r, metric, scope = self._result, self.current_metric, self._scope
        show = metric in TORNADO_METRICS
        self.tornado_note.setVisible(not show)
        self.tornado_box.setVisible(show)
        if not show:
            return
        entries = sorted(((getattr(r, "tornado", None) or {}).get((scope, metric)) or []),
                         key=lambda e: -float(e["swing"]))
        ax = self.plot_tornado.get_axes()
        if not entries:
            ax.text(0.5, 0.5, "No tornado for this scope", ha="center", va="center",
                    transform=ax.transAxes)
            self.plot_tornado.refresh()
            self.tornado_view.model().set_dataframe(pd.DataFrame(columns=list(TORNADO_COLUMNS)))
            return
        ypos = np.arange(len(entries))
        lo = np.array([float(e["bar_min"]) for e in entries])
        hi = np.array([float(e["bar_max"]) for e in entries])
        ax.barh(ypos, hi - lo, left=lo, color=get_plot_color("NET_PAY"), alpha=0.8)
        ax.axvline(float(entries[0]["base"]), color=get_plot_color("RT"), lw=1.2)
        ax.set_yticks(ypos)
        ax.set_yticklabels([f"{e['name']} ({_num(e['low_input'])} / {_num(e['high_input'])})"
                            for e in entries], fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel(self.metric_combo.currentText())
        self.plot_tornado.refresh()
        rank = (getattr(r, "rank_corr", None) or {}).get(metric, {})
        rows = []
        for e in entries:
            rho = rank.get(e["name"])
            rows.append([e["name"], _num(e["low_input"]), _num(e["high_input"]),
                         float(e["at_low_input"]), float(e["at_high_input"]),
                         float(e["swing"]), float(rho) if rho is not None else float("nan")])
        self.tornado_view.model().set_dataframe(pd.DataFrame(rows, columns=list(TORNADO_COLUMNS)))

    def refresh_theme(self):
        self.plot_hist.refresh_theme()
        self.plot_tornado.refresh_theme()
        self._plot_key = None
        self._draw_plots_if_needed()
