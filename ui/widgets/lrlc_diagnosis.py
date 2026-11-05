"""Zone diagnosis and Thomas-Stieber pages of the LRLC Workbench (Diagnosis panel).

``ZonesPanel`` lists the probable and possible causes per zone with the evidence behind each
and the remedy; ``ThomasStieberPanel`` shows the end-point proposals next to the applied
values, the class counts of the last run and the crossplot. Both read the model and the last
run only. A remedy or a proposal is handed on with ``prepare_requested``; nothing is written
here and the analysis is never run.
"""

import logging
from typing import Dict, List, Optional

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from modules.lrlc.config import resolve_lrlc
from modules.lrlc.methods import METHOD_TEXT
from modules.lrlc.thomas_stieber import check_endpoints, decompose
from modules.param_scopes import UNZONED
from services.lrlc_service import LrlcService

from ..tabs.rock_typing_tab import fit_table_height
from .lrlc_common import fmt, item, make_table, note, zone_title
from .lrlc_pickett import zone_labels
from .lrlc_ts_plot import CLASS_NAMES, TsCrossplot
from .method_box import MethodReferenceBox

logger = logging.getLogger(__name__)

RUN_FIRST = "Run the analysis first"
ZONE_COLUMNS = ("Zone", "Status", "Net reservoir (ft)", "Primary cause", "Other causes",
                "Laminated")
CRITERIA_COLUMNS = ("Cause", "Level", "Criterion", "Value", "Condition", "Met")
QV_COLUMNS = ("Zone", "Qv estimate (meq/mL)", "Clay conductivity", "Qv evidence (meq/mL)",
              "Mean Vsh", "Sw drop vs Archie")
TS_COLUMNS = ("Zone", "Proposed phi_max", "Proposed phi_sh", "Source", "Clean / shale samples",
              "Applied phi_max", "Applied phi_sh", "Status")
CLASS_COLUMNS = ("Zone", "Laminar", "Dispersed", "Mixed", "Structural", "Clay-supported",
                 "Not classified", "Laminar share", "Mean Vlam", "Outside triangle")

CRITERION_LABELS = {
    "lam_share": "Laminar share of the shale volume",
    "mean_vlam": "Mean laminar shale volume",
    "class13_share": "Share of laminar and mixed samples",
    "sw_median": "Median Sw",
    "water_free_share": "Water-free share",
    "bvw_cv": "BVW variation (CV)",
    "rw_median": "Median Rw (ohm.m)",
    "rt_ro_median": "Median Rt / Ro",
    "rt_median": "Median Rt (ohm.m)",
    "vpyr_median": "Median VPYR",
    "pef_median": "Median PEF (b/e)",
    "qv": "Qv (meq/mL)",
    "vsh_mean": "Mean Vsh",
    "dsw_median": "Median Sw drop vs Archie",
}
LEVEL_LABELS = {"probable": "Probable", "possible": "Possible"}
STATUS_LABELS = {"ok": "Evaluated", "insufficient": "Too few net reservoir samples"}


def lrlc_summary(ds) -> dict:
    return ((getattr(ds, "summary", None) or {}).get("lrlc") or {}) if ds is not None else {}


def _cause_text(cause: dict) -> str:
    return f"{cause['label']} ({LEVEL_LABELS.get(cause['level'], cause['level']).lower()})"


class ZonesPanel(QWidget):
    """Causes, evidence and remedy per zone. Public: ``set_context``, ``select_zone``."""

    zone_selected = pyqtSignal(object)           # a zone name the user clicked in the table
    prepare_requested = pyqtSignal(object, dict)  # zone, remedy dict (no write)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = None
        self.ds = None
        self.zone: Optional[str] = None
        self._results: List[dict] = []
        self._remedy_rows: List[QWidget] = []
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.status_label = note("")
        root.addWidget(self.status_label)

        self.zone_table = make_table(ZONE_COLUMNS)
        self.zone_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.zone_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.zone_table.itemSelectionChanged.connect(self._on_row_selected)
        root.addWidget(self.zone_table)

        self.detail_group = QGroupBox("Evidence")
        dl = QVBoxLayout(self.detail_group)
        self.detail_note = note("")
        dl.addWidget(self.detail_note)
        self.criteria_table = make_table(CRITERIA_COLUMNS)
        dl.addWidget(self.criteria_table)
        root.addWidget(self.detail_group)

        self.remedy_group = QGroupBox("Remedy")
        self.remedy_layout = QVBoxLayout(self.remedy_group)
        self.remedy_note = note("Prepare remediation fills the Remediation panel; nothing is "
                                "written until you apply it there.")
        self.remedy_layout.addWidget(self.remedy_note)
        root.addWidget(self.remedy_group)

        self.qv_group = QGroupBox("Qv evidence")
        ql = QVBoxLayout(self.qv_group)
        self.qv_note = note("")
        ql.addWidget(self.qv_note)
        self.qv_table = make_table(QV_COLUMNS)
        ql.addWidget(self.qv_table)
        root.addWidget(self.qv_group)
        root.addStretch(1)

    # ----------------------------------------------------------------- context
    def set_context(self, model, ds, zone: Optional[str] = None):
        self.model = model
        self.ds = ds
        self.zone = zone or None
        self._render()

    def select_zone(self, zone: Optional[str]):
        """Select the table row of a zone (no signal)."""
        self.zone = zone or None
        self._select_row()
        self._render_detail()

    def selected_row_zone(self) -> Optional[str]:
        rows = self.zone_table.selectionModel().selectedRows() if self.zone_table.model() else []
        if not rows:
            return None
        cell = self.zone_table.item(rows[0].row(), 0)
        return cell.data(Qt.ItemDataRole.UserRole) if cell is not None else None

    # ------------------------------------------------------------------ render
    def _render(self):
        summary = lrlc_summary(self.ds)
        self._results = list(summary.get("zones") or [])
        guard = {(z.get("zone") if z.get("zone") is not None else UNZONED): z
                 for z in (summary.get("guard") or {}).get("zones", [])}
        blocker = self.zone_table.blockSignals(True)
        try:
            self.zone_table.setRowCount(len(self._results))
            for r, res in enumerate(self._results):
                name = res.get("zone")
                causes = res.get("causes") or []
                primary = next((c for c in causes if c["key"] == res.get("primary")), None)
                others = [_cause_text(c) for c in causes if c is not primary]
                g = guard.get(name) or res.get("guard") or {}
                lam = g.get("laminated")
                values = (zone_title(name), STATUS_LABELS.get(res.get("status"), res.get("status")),
                          fmt(res.get("thickness_ft"), 1),
                          _cause_text(primary) if primary else "None probable",
                          "; ".join(others), "Yes" if lam else ("No" if lam is False else ""))
                for c, text in enumerate(values):
                    cell = item(text, align_right=(c == 2))
                    if c == 0:
                        cell.setData(Qt.ItemDataRole.UserRole, name)
                    self.zone_table.setItem(r, c, cell)
        finally:
            self.zone_table.blockSignals(blocker)
        fit_table_height(self.zone_table)
        if not self._results:
            self.status_label.setText(
                RUN_FIRST + ". The diagnosis appears after a run with a correction, "
                "Thomas-Stieber or a Qv estimate switched on." if self.ds is not None
                else "No well loaded")
        else:
            self.status_label.setText(
                "Causes are scored from the net reservoir samples of each zone; a cause is "
                "probable at two thirds of its evaluable criteria and possible at one third.")
        self._select_row()
        self._render_detail()
        self._render_qv()

    def _row_for(self, zone: Optional[str]) -> int:
        if zone:
            for r, res in enumerate(self._results):
                if res.get("zone") == zone:
                    return r
            return -1
        return 0 if len(self._results) == 1 else -1

    def _select_row(self):
        blocker = self.zone_table.blockSignals(True)
        try:
            r = self._row_for(self.zone)
            if r >= 0:
                self.zone_table.selectRow(r)
            else:
                self.zone_table.clearSelection()
        finally:
            self.zone_table.blockSignals(blocker)

    def _on_row_selected(self):
        zone = self.selected_row_zone()
        self.zone = zone if zone not in (None, "WELL") else None
        self._render_detail()
        if zone is not None and zone != "WELL":
            self.zone_selected.emit(zone)

    def _current(self) -> Optional[dict]:
        r = self._row_for(self.zone)
        return self._results[r] if r >= 0 else None

    def _render_detail(self):
        res = self._current()
        for w in self._remedy_rows:
            self.remedy_layout.removeWidget(w)
            w.deleteLater()
        self._remedy_rows = []
        self.criteria_table.setRowCount(0)
        if res is None:
            self.detail_group.setTitle("Evidence")
            self.detail_note.setText("Select a zone in the table." if self._results else "")
            self.remedy_group.setVisible(bool(self._results))
            fit_table_height(self.criteria_table)
            return
        self.detail_group.setTitle(f"Evidence: {zone_title(res.get('zone'))}")
        causes = res.get("causes") or []
        if res.get("status") == "insufficient":
            self.detail_note.setText(
                f"Only {res.get('n_res', 0)} net reservoir samples; the diagnosis needs more.")
        elif not causes:
            self.detail_note.setText("No cause reaches the possible level in this zone.")
        else:
            self.detail_note.setText("")
        rows = [(c, crit) for c in causes for crit in c["criteria"]]
        self.criteria_table.setRowCount(len(rows))
        for r, (cause, crit) in enumerate(rows):
            met = crit.get("met")
            cond = ("" if crit.get("threshold") is None
                    else f"{crit['op']} {fmt(crit['threshold'], 3)}")
            values = (cause["label"], LEVEL_LABELS.get(cause["level"], cause["level"]),
                      CRITERION_LABELS.get(crit["id"], crit["id"]), fmt(crit.get("value"), 3), cond,
                      "n/a" if met is None else ("Yes" if met else "No"))
            for c, text in enumerate(values):
                self.criteria_table.setItem(r, c, item(text, align_right=(c == 3)))
        fit_table_height(self.criteria_table)
        self.remedy_group.setVisible(True)
        for cause in causes:
            remedy = cause.get("remedy") or {}
            line = QWidget()
            lay = QHBoxLayout(line)
            lay.setContentsMargins(0, 0, 0, 0)
            text = note(f"{cause['label']}: {remedy.get('text', '')}")
            text.setTextFormat(Qt.TextFormat.PlainText)
            lay.addWidget(text, 1)
            actionable = bool(remedy.get("rt_steps") or remedy.get("qv_source")
                              or remedy.get("sw_basis"))
            if actionable:
                button = QPushButton("Prepare remediation")
                button.setToolTip("Fill the Remediation panel with this remedy. Nothing is "
                                  "written until you apply it there.")
                zone = res.get("zone")
                button.clicked.connect(
                    lambda _=False, z=zone, rm=remedy: self.prepare_requested.emit(
                        None if z == "WELL" else z, dict(rm)))
                lay.addWidget(button)
            self.remedy_layout.addWidget(line)
            self._remedy_rows.append(line)

    def _qv_median(self, zone) -> Optional[float]:
        res = getattr(self.ds, "results", None)
        if res is None or "QV_EST" not in res.columns:
            return None
        mask = np.ones(len(res), dtype=bool)
        if zone not in (None, "WELL") and "ZONE" in res.columns:
            mask = zone_labels(res) == zone
        vals = res["QV_EST"].to_numpy(dtype=float)[mask]
        vals = vals[np.isfinite(vals)]
        return float(np.median(vals)) if len(vals) else None

    def _render_qv(self):
        rows = []
        for res in self._results:
            clay = next((c for c in res.get("causes") or [] if c["key"] == "clay_conductivity"),
                        None)
            crit = {c["id"]: c for c in (clay or {}).get("criteria", [])}
            rows.append((res.get("zone"), clay, crit))
        self.qv_table.setRowCount(len(rows))
        for r, (zone, clay, crit) in enumerate(rows):
            values = (zone_title(zone), fmt(self._qv_median(zone), 3),
                      LEVEL_LABELS.get(clay["level"], "") if clay else "Not indicated",
                      fmt(crit.get("qv", {}).get("value"), 3),
                      fmt(crit.get("vsh_mean", {}).get("value"), 3),
                      fmt(crit.get("dsw_median", {}).get("value"), 3))
            for c, text in enumerate(values):
                self.qv_table.setItem(r, c, item(text, align_right=c > 0))
        fit_table_height(self.qv_table)
        self.qv_group.setVisible(bool(rows))
        self.qv_note.setText(
            "Qv evidence is listed only for the causes that reach the possible level. "
            "The estimate column is filled when a Qv estimate was part of the last run."
            if rows else "")


class ThomasStieberPanel(QWidget):
    """End-point proposals and applied values, class counts and the crossplot."""

    prepare_requested = pyqtSignal(object, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = None
        self.ds = None
        self.zone: Optional[str] = None
        self._proposals: Dict[str, object] = {}
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.status_label = note("")
        root.addWidget(self.status_label)

        self.endpoint_table = make_table(TS_COLUMNS)
        root.addWidget(self.endpoint_table)
        buttons = QHBoxLayout()
        self.prepare_button = QPushButton("Prepare end-points in Remediation")
        self.prepare_button.setToolTip(
            "Copy the proposal of the selected zone into the Remediation panel. Nothing is "
            "written until you apply it there.")
        self.prepare_button.clicked.connect(self._on_prepare)
        buttons.addWidget(self.prepare_button)
        buttons.addStretch(1)
        root.addLayout(buttons)

        self.plot_group = QGroupBox("Crossplot")
        pl = QVBoxLayout(self.plot_group)
        self.plot_note = note("")
        pl.addWidget(self.plot_note)
        self.plot = TsCrossplot()
        pl.addWidget(self.plot)
        root.addWidget(self.plot_group)

        self.class_group = QGroupBox("Classes in the last run")
        cl = QVBoxLayout(self.class_group)
        self.class_note = note("")
        cl.addWidget(self.class_note)
        self.class_table = make_table(CLASS_COLUMNS)
        cl.addWidget(self.class_table)
        root.addWidget(self.class_group)

        self.method_box = MethodReferenceBox()
        self.method_box.set_method(METHOD_TEXT["thomas_stieber"])
        root.addWidget(self.method_box)
        root.addStretch(1)

    # ----------------------------------------------------------------- context
    def set_context(self, model, ds, zone: Optional[str] = None):
        self.model = model
        self.ds = ds
        self.zone = zone or None
        self._render()

    def refresh_theme(self):
        self.plot.refresh_theme()

    # ------------------------------------------------------------------ helpers
    def _settings(self) -> dict:
        return (self.model.project.lrlc.get("thomas_stieber") or {}) if self.model else {}

    def _zone_names(self) -> List[str]:
        """Zones of the table: the proposal keys (the unzoned interval reads as the well)."""
        return list(self._proposals)

    def _resolved(self, zone):
        project = self.model.project.lrlc.get("params") or {}
        well = (getattr(self.ds, "lrlc", None) or {}) if self.ds is not None else {}
        key = None if zone in (None, UNZONED, "WELL") else zone
        return resolve_lrlc(project, well, key)

    def _applied(self, zone):
        r = self._resolved(zone)
        return r.get("phi_max"), r.get("phi_sh")

    def _effective_zone(self) -> Optional[str]:
        names = self._zone_names()
        if self.zone and self.zone in names:
            return self.zone
        if not self.zone and len(names) == 1:
            return names[0]
        return None

    # ------------------------------------------------------------------ render
    def _render(self):
        self._proposals = {}
        if self.model is None or self.ds is None:
            self.status_label.setText("No well loaded")
            self.endpoint_table.setRowCount(0)
            self.plot.clear_data("No well loaded")
            self.class_group.setVisible(False)
            return
        proposals = LrlcService.ts_proposals(self.model, self.ds)
        if proposals is None:
            self.status_label.setText(RUN_FIRST + " to propose Thomas-Stieber end-points.")
            self.endpoint_table.setRowCount(0)
            fit_table_height(self.endpoint_table)
            self.plot.clear_data(RUN_FIRST)
            self.plot_note.setText("")
            self._render_classes()
            self.prepare_button.setEnabled(False)
            return
        self._proposals = proposals
        enabled = bool(self._settings().get("enabled"))
        self.status_label.setText(
            "Thomas-Stieber is switched on for the next run." if enabled else
            "Thomas-Stieber is off. Switch it on in Remediation > Laminated sand to compute the "
            "laminar shale volume; the proposals and the preview below work either way.")
        rows = list(proposals.items())
        self.endpoint_table.setRowCount(len(rows))
        for r, (zone, prop) in enumerate(rows):
            applied = self._applied(zone)
            ok_applied, _ = check_endpoints(*applied)
            if applied[0] is None or applied[1] is None:
                status = "Not applied" if not prop.ok else "Not applied; the proposal can be used"
            elif not ok_applied:
                status = "Applied values are not usable"
            elif prop.ok and (abs(applied[0] - prop.phi_max) < 5e-4
                              and abs(applied[1] - prop.phi_sh) < 5e-4):
                status = "Applied equals the proposal"
            else:
                status = "Applied"
            if not prop.ok:
                status = f"{status}. {prop.reason}" if prop.reason else status
            values = (zone_title(None if zone == UNZONED else zone),
                      fmt(prop.phi_max, 3), fmt(prop.phi_sh, 3), prop.source or "",
                      f"{prop.n_clean} / {prop.n_shale}", fmt(applied[0], 3), fmt(applied[1], 3),
                      status)
            for c, text in enumerate(values):
                cell = item(text, align_right=1 <= c <= 6 and c != 3)
                if c == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, zone)
                self.endpoint_table.setItem(r, c, cell)
        fit_table_height(self.endpoint_table)
        zone = self._effective_zone()
        self.prepare_button.setEnabled(zone is not None and proposals[zone].ok)
        self._render_plot(zone)
        self._render_classes()

    def _on_prepare(self):
        zone = self._effective_zone()
        prop = self._proposals.get(zone) if zone is not None else None
        if prop is None or not prop.ok:
            return
        self.prepare_requested.emit(None if zone == UNZONED else zone,
                                    {"phi_max": float(prop.phi_max), "phi_sh": float(prop.phi_sh)})

    def _sample_arrays(self, zone):
        res = self.ds.results
        col = self._settings().get("vsh_column")
        col = col if col in res.columns else "VSH"
        vsh = res[col].to_numpy(dtype=float)
        phit = res["PHIT"].to_numpy(dtype=float)
        mask = np.ones(len(res), dtype=bool)
        if zone is not None and "ZONE" in res.columns:
            mask = zone_labels(res) == ("" if zone == UNZONED else zone)
        return res, vsh, phit, mask

    def _render_plot(self, zone):
        if zone is None:
            self.plot.clear_data("Select a zone to see the crossplot")
            self.plot_note.setText("")
            return
        res, vsh, phit, mask = self._sample_arrays(zone)
        prop = self._proposals[zone]
        applied = self._applied(zone)
        pm_ps = applied if check_endpoints(*applied)[0] else None
        proposal = (prop.phi_max, prop.phi_sh) if prop.ok else None
        if pm_ps is None and proposal is None:
            self.plot.set_data(vsh[mask], phit[mask], None, title=zone_title(zone))
            self.plot_note.setText(prop.reason or "No usable end-points; samples are not classed.")
            return
        use = pm_ps if pm_ps is not None else proposal
        if "TS_CLASS" in res.columns and pm_ps is not None and self._run_used(zone, pm_ps):
            cls = res["TS_CLASS"].to_numpy()[mask]
            source = "Classes from the last run."
        else:
            cls = decompose(vsh[mask], phit[mask], float(use[0]), float(use[1]),
                            self._settings()).ts_class
            source = ("Preview with the applied end-points." if pm_ps is not None
                      else "Preview with the proposed end-points (not applied).")
        self.plot.set_data(vsh[mask], phit[mask], cls, pm_ps[0] if pm_ps else None,
                           pm_ps[1] if pm_ps else None, proposal=proposal,
                           title=zone_title(zone))
        self.plot_note.setText(source)

    def _run_used(self, zone, applied) -> bool:
        """The last run classed this zone with the end-points that are applied now."""
        for row in (lrlc_summary(self.ds).get("ts") or {}).get("zones", []):
            if row.get("zone") == zone or (zone == UNZONED and row.get("zone") == "WELL"):
                pm, ps = row.get("phi_max"), row.get("phi_sh")
                return (pm is not None and ps is not None
                        and abs(pm - applied[0]) < 1e-9 and abs(ps - applied[1]) < 1e-9)
        return False

    def _render_classes(self):
        ts = lrlc_summary(self.ds).get("ts") or {}
        rows = ts.get("zones") or []
        self.class_group.setVisible(bool(rows))
        self.class_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            counts = {int(k): v for k, v in (row.get("class_counts") or {}).items()}
            clamped = row.get("clamped") or {}
            outside = sum(int(v) for v in clamped.values())
            values = (zone_title(row.get("zone")),
                      *(str(counts.get(c, 0)) for c in (1, 2, 3, 4, 5, 0)),
                      fmt(row.get("lam_share"), 2), fmt(row.get("mean_vlam"), 3), str(outside))
            for c, text in enumerate(values):
                self.class_table.setItem(r, c, item(text, align_right=c > 0))
        fit_table_height(self.class_table)
        if rows:
            names = ", ".join(f"{n.lower()}" for k, n in CLASS_NAMES.items() if k)
            self.class_note.setText(
                f"Classes: {names}. The laminar share is the laminar shale volume divided by "
                "the shale volume over samples above the guard shale minimum.")
