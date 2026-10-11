"""Diagnostics tab for P0's C items (U10): Sw checks table, Swirr lines, no-shale note, core gap line."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt

from models.app_model import AppModel
from models.project import WellDataset
from modules.pipeline import ZONE_NO_SHALE_NOTE, run_pipeline
from tests.golden.cases import FULL_MAPPING, fixture_frame, make_tops
from ui.tabs.diagnostics_tab import (
    CHECK_STATE_ROLE, SW_CHECK_COLUMNS, DiagnosticsTab, build_sw_check_rows,
    swirr_summary_lines,
)

DISPLAY = Qt.ItemDataRole.DisplayRole


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    def refuse(*args, **kwargs):
        raise AssertionError(f"unexpected dialog: {args[1:3]}")

    for name in ("warning", "critical", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(refuse))


def _counts(samples=100, **over):
    base = {"no_root": 0, "failed": 0, "at_upper_bound": 0, "at_lower_bound": 0,
            "no_porosity": 0, "no_phit": 0, "bvh_exceeds_phie": 0, "phie_above_phit": 0}
    base.update(over)
    if samples is not None:
        base["samples"] = samples
    return base


def _model(with_tops=True):
    data = fixture_frame("sample_log_data")
    ds = WellDataset("W:A", "Alpha")
    ds.identity = {"well_name": "Alpha", "uwi": "UWI-A"}
    ds.las_data = data
    ds.curve_mapping = dict(FULL_MAPPING)
    if with_tops:
        ds.formation_tops = make_tops()
    ds.results, ds.summary = run_pipeline(
        data, FULL_MAPPING, {}, formation_tops=ds.formation_tops if with_tops else None)
    ds.calculated = True
    model = AppModel()
    model.project.add_well(ds)
    return model, ds


def _cell(model, row, column):
    col = SW_CHECK_COLUMNS.index(column)
    return model.index(row, col)


def test_rows_per_model_and_zone_with_thresholds():
    diag = {
        "SW_ARCHIE": {**_counts(None), "zones": {
            "UPPER": _counts(100, at_upper_bound=11, bvh_exceeds_phie=5, phie_above_phit=6),
            "LOWER": _counts(100, at_upper_bound=10, no_porosity=3),
        }},
        "SW_WS": {**_counts(None), "zones": {"UPPER": _counts(50, no_root=2)}},
    }
    rows, warn = build_sw_check_rows(diag)
    assert [r[:3] for r in rows] == [
        ["Archie", "UPPER", "100"], ["Archie", "LOWER", "100"], ["Waxman-Smits", "UPPER", "50"]]
    col = SW_CHECK_COLUMNS.index
    assert (0, col("At upper bound")) in warn            # 11 > 10 % of 100
    assert (0, col("PHIE > PHIT")) in warn               # 6 > 5 % of 100
    assert (0, col("BVH capped")) not in warn            # 5 is not above 5 %
    assert (1, col("At upper bound")) not in warn
    assert (1, col("No porosity")) not in warn           # a count, no threshold
    assert (2, col("No root")) in warn
    assert rows[0][col("No root")] == "-"                # not a solver model


def test_whole_well_row_without_zones_and_only_computed_models():
    rows, warn = build_sw_check_rows({"SW_SIMAN": _counts(None, at_lower_bound=4)}, 200)
    assert rows == [["Simandoux", "Whole well", "200", "0", "0", "4", "0", "0", "-", "-"]]
    assert not warn
    assert build_sw_check_rows({}) == ([], set())


def test_tab_table_warning_state_and_empty_state(qtbot):
    model, ds = _model()
    tab = DiagnosticsTab(model)
    qtbot.addWidget(tab)
    tab.reset_ui()
    assert not tab.sw_checks_group.isVisibleTo(tab)
    ds.summary["solver_diagnostics"] = {}
    tab.update_display()
    assert tab.sw_checks_group.isVisibleTo(tab)
    assert tab.sw_checks_empty.isVisibleTo(tab) and tab.sw_checks_model.rowCount() == 0

    zones = [z["zone"] for z in ds.summary["zones"]]
    ds.summary["solver_diagnostics"] = {"SW_DW": {**_counts(None), "zones": {
        zones[0]: _counts(80, at_upper_bound=20, failed=1), zones[1]: _counts(80)}}}
    tab.update_display()
    m = tab.sw_checks_model
    assert not tab.sw_checks_empty.isVisibleTo(tab)
    assert m.rowCount() == 2
    assert _cell(m, 0, "Model").data(DISPLAY) == "Dual-Water"
    assert _cell(m, 0, "Zone").data(DISPLAY) == zones[0]
    assert _cell(m, 0, "At upper bound").data(CHECK_STATE_ROLE) == "warning"
    assert _cell(m, 0, "Failed").data(CHECK_STATE_ROLE) == "warning"
    assert _cell(m, 0, "Samples").data(CHECK_STATE_ROLE) is None
    assert _cell(m, 1, "At upper bound").data(CHECK_STATE_ROLE) is None
    assert _cell(m, 0, "At upper bound").data(Qt.ItemDataRole.ForegroundRole) is not None

    tab.reset_ui()
    assert m.rowCount() == 0 and not tab.sw_checks_group.isVisibleTo(tab)


def test_swirr_lines_and_status(qtbot):
    summary = {"swirr_method": "Hierarchical (Recommended)",
               "swirr_diagnostics": {"method_used": "Hierarchical (Recommended)", "samples": 300,
                                     "fallback_samples": 4, "floor_samples": 7,
                                     "limited_by_sw": 2, "limited_to_max": 1}}
    lines, warn = swirr_summary_lines(summary)
    assert lines[0] == "Swirr method used: Hierarchical (Recommended)"
    assert "7 of 300 samples raised to the 0.05 floor" in lines
    assert "2 of 300 samples limited to Sw" in lines
    assert "1 of 300 samples limited to 0.60" in lines
    assert "4 of 300 samples taken from Buckles (fallback)" in lines
    assert warn

    # Older summary without swirr_diagnostics: the method only, no warning.
    assert swirr_summary_lines({"swirr_method": "Buckles Number"}) == (
        ["Swirr method used: Buckles Number"], False)
    assert swirr_summary_lines({}) == ([], False)

    model, ds = _model()
    ds.summary.update(summary)
    tab = DiagnosticsTab(model)
    qtbot.addWidget(tab)
    tab.update_display()
    assert "7 of 300 samples raised to the 0.05 floor" in tab.swirr_summary.text()
    assert tab.swirr_summary.property("status") == "warning"
    ds.summary["swirr_diagnostics"] = {**summary["swirr_diagnostics"], "fallback_samples": 0,
                                       "floor_samples": 0, "limited_by_sw": 0, "limited_to_max": 0}
    tab.update_display()
    assert tab.swirr_summary.property("status") in (None, "")


def test_no_shale_zone_note_listed(qtbot):
    model, ds = _model()
    zones = [z["zone"] for z in ds.summary["zones"]]
    ds.summary["zone_diagnostics"] = {zones[0]: {"status": "ok", "note": ZONE_NO_SHALE_NOTE},
                                      zones[1]: {"status": "ok"}}
    tab = DiagnosticsTab(model)
    qtbot.addWidget(tab)
    tab.update_display()
    m = tab.zone_notes_model
    assert m.rowCount() == 1
    assert m.index(0, 0).data(DISPLAY) == zones[0]
    assert m.index(0, 1).data(DISPLAY) == ZONE_NO_SHALE_NOTE
    del ds.summary["zone_diagnostics"]
    tab.update_display()
    assert m.rowCount() == 0 and not tab.zone_notes_table.isVisibleTo(tab)


def test_real_run_fills_the_table(qtbot):
    model, ds = _model(with_tops=False)
    tab = DiagnosticsTab(model)
    qtbot.addWidget(tab)
    tab.update_display()
    names = {tab.sw_checks_model.index(r, 0).data(DISPLAY)
             for r in range(tab.sw_checks_model.rowCount())}
    assert names and names <= {"Archie", "Indonesian", "Simandoux", "Waxman-Smits", "Dual-Water"}
    assert tab.sw_checks_model.index(0, 1).data(DISPLAY) == "Whole well"
    assert tab.sw_checks_model.index(0, 2).data(DISPLAY) == str(len(ds.results))
