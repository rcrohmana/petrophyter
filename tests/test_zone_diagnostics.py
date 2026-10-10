"""Zone cutoff validation: why a zone has no gross / net reservoir / net pay (spec §9)."""
import numpy as np
import pytest
from PyQt6.QtCore import Qt

from models.app_model import AppModel
from models.project import WellDataset
from modules import param_scopes as ps
from modules.pipeline import (
    PARAM_DEFAULTS, _zone_diagnostics, run_pipeline, zone_diagnostic_note,
)
from tests.golden.cases import FULL_MAPPING, fixture_frame, make_tops
from ui.tabs.summary_tab import STATE_ROLE as ROW_STATE_ROLE, SummaryTab
from ui.widgets.zone_grid import STATE_ROLE, ZoneParamGrid

TIP = Qt.ItemDataRole.ToolTipRole
CUT = {"vsh_cutoff": 0.4, "phi_cutoff": 0.08, "sw_cutoff": 0.6}


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    def refuse(*args, **kwargs):
        raise AssertionError(f"unexpected dialog: {args[1:3]}")

    for name in ("warning", "critical", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(refuse))


def _diag(vsh, phie, sw, cutoffs=CUT, step=1.0):
    return _zone_diagnostics(vsh, phie, sw, cutoffs, step)


# ---- the pure rules ---------------------------------------------------------
def test_no_gross_when_nothing_passes_vsh():
    d = _diag([0.9] * 10, [0.2] * 10, [0.3] * 10)
    assert d["status"] == "no_gross" and d["limiting"] == "vsh_cutoff"
    assert d["gross"] == 0 and d["pass_vsh"] == 0.0 and d["valid"] == 10
    assert zone_diagnostic_note(d)[0] == "info"


def test_no_reservoir_when_gross_but_nothing_passes_phie():
    d = _diag([0.1] * 10, [0.03] * 10, [0.3] * 10)
    assert d["status"] == "no_reservoir" and d["limiting"] == "phi_cutoff"
    assert d["gross"] == 10 and d["net_reservoir"] == 0 and d["pass_phi"] == 0.0
    level, text = zone_diagnostic_note(d)
    assert level == "warning"
    assert text.startswith("No net reservoir: PHIE cutoff 0.08 passes 0% of 10 ft gross.")
    assert "check the cutoff and the porosity inputs" in text


def test_no_pay_when_reservoir_but_nothing_passes_sw():
    d = _diag([0.1] * 10, [0.2] * 10, [0.9] * 10)
    assert d["status"] == "no_pay" and d["limiting"] == "sw_cutoff"
    assert d["net_reservoir"] == 10 and d["net_pay"] == 0 and d["pass_sw"] == 0.0
    level, text = zone_diagnostic_note(d)
    assert level == "info"
    assert text.startswith("No net pay: the Sw cutoff 0.60 passes 0% of 10 ft net reservoir.")


def test_ok_and_limiting_is_lowest_pass_fraction_among_others_passing():
    # 10 samples: all pass Vsh; phie passes 8/10; sw passes 3 of the 8 reservoir samples
    vsh = [0.1] * 10
    phie = [0.2] * 8 + [0.01] * 2
    sw = [0.3] * 3 + [0.9] * 5 + [0.3] * 2
    d = _diag(vsh, phie, sw, step=0.5)
    assert d["status"] == "ok" and zone_diagnostic_note(d) is None
    assert d["limiting"] == "sw_cutoff"                    # 3/8 beats phi's 8/10 and vsh's 10/10
    assert d["pass_phi"] == pytest.approx(0.8)
    assert (d["gross"], d["net_reservoir"], d["net_pay"]) == (5.0, 4.0, 1.5)


def test_limiting_can_be_the_phie_cutoff():
    vsh = [0.1] * 10
    phie = [0.2] * 2 + [0.01] * 8
    sw = [0.3] * 10
    assert _diag(vsh, phie, sw)["limiting"] == "phi_cutoff"


def test_nothing_limits_when_every_cutoff_passes_everything():
    d = _diag([0.1] * 5, [0.2] * 5, [0.3] * 5)
    assert d["status"] == "ok" and d["limiting"] is None


def test_nan_samples_are_not_valid_and_count_nowhere():
    nan = np.nan
    d = _diag([0.1, 0.1, nan, 0.1], [0.2, nan, 0.2, 0.2], [0.3, 0.3, 0.3, nan])
    assert d["valid"] == 1 and d["gross"] == 1.0 and d["status"] == "ok"
    assert d["pass_vsh"] == 1.0


def test_zone_without_valid_samples_is_no_data():
    d = _diag([np.nan] * 3, [0.2] * 3, [0.3] * 3)
    assert d["status"] == "no_data" and d["valid"] == 0
    assert d["pass_vsh"] is None and d["limiting"] is None
    assert zone_diagnostic_note(d)[0] == "info"


# ---- through the pipeline ---------------------------------------------------
def test_pipeline_whole_well_has_no_zone_diagnostics():
    _, summary = run_pipeline(fixture_frame("sample_log_data"), FULL_MAPPING, {})
    assert summary["zones"] == [] and "zone_diagnostics" not in summary


def test_pipeline_uses_the_cutoffs_applied_in_each_zone():
    base = {**PARAM_DEFAULTS}
    plan = ps.zone_plan(base, None, {"LOWER": {"phi_cutoff": ps.make_entry(ps.MANUAL, 0.99)}},
                        None, ["UPPER", "LOWER"])
    _, summary = run_pipeline(fixture_frame("sample_log_data"), FULL_MAPPING,
                              {"zone_plan": plan}, formation_tops=make_tops())
    diag = summary["zone_diagnostics"]
    assert set(diag) == {z["zone"] for z in summary["zones"]}
    assert diag["LOWER"]["cutoffs"]["phi_cutoff"] == 0.99
    assert diag["LOWER"]["status"] == "no_reservoir"
    assert diag["UPPER"]["cutoffs"]["phi_cutoff"] == base["phi_cutoff"]
    assert diag["UPPER"]["status"] != "no_reservoir"
    for zone in summary["zones"]:                       # same thickness arithmetic as the rows
        assert diag[zone["zone"]]["gross"] == pytest.approx(zone["gross_sand"])
        assert diag[zone["zone"]]["net_pay"] == pytest.approx(zone["net_pay"])


# ---- UI ---------------------------------------------------------------------
def _diagnostics(status, limiting, **extra):
    base = {"valid": 40, "gross": 300.0, "pass_vsh": 0.7, "pass_phi": 0.0, "pass_sw": 0.0,
            "net_reservoir": 0.0, "net_pay": 0.0, "status": status, "limiting": limiting,
            "cutoffs": dict(CUT)}
    base.update(extra)
    return base


def _model(stale=False):
    data = fixture_frame("sample_log_data")
    ds = WellDataset("W:A", "Alpha")
    ds.identity = {"well_name": "Alpha", "uwi": "UWI-A"}
    ds.las_data = data
    ds.curve_mapping = dict(FULL_MAPPING)
    ds.formation_tops = make_tops()
    ds.results, ds.summary = run_pipeline(
        data, FULL_MAPPING, {}, formation_tops=ds.formation_tops)
    ds.calculated = True
    zones = [z["zone"] for z in ds.summary["zones"]]
    ds.summary["zone_diagnostics"] = {
        zones[0]: _diagnostics("no_reservoir", "phi_cutoff"),
        zones[1]: _diagnostics("no_pay", "sw_cutoff", net_reservoir=120.0, pass_phi=0.5),
    }
    ds.stale = stale
    model = AppModel()
    model.project.add_well(ds)
    return model, zones


def test_summary_rows_carry_state_and_tooltip(qtbot):
    model, zones = _model()
    tab = SummaryTab(model)
    qtbot.addWidget(tab)
    tab.update_display()
    zm = tab.zones_model
    assert zm.index(0, 0).data(ROW_STATE_ROLE) == "warning"
    assert zm.index(1, 0).data(ROW_STATE_ROLE) == "info"
    assert zm.index(0, 0).data(TIP).startswith("No net reservoir: PHIE cutoff 0.08")
    assert zm.index(1, 4).data(TIP) == (
        "No net pay: the Sw cutoff 0.60 passes 0% of 120 ft net reservoir. May be "
        "water-bearing; check the cutoff and the Rw inputs if pay is expected.")
    assert zm.index(0, 5).data(Qt.ItemDataRole.ForegroundRole) is not None      # foreground colour set (ForegroundRole)


def test_summary_rows_without_diagnostics_have_no_state(qtbot):
    model, _ = _model()
    del model.project.active.summary["zone_diagnostics"]
    tab = SummaryTab(model)
    qtbot.addWidget(tab)
    tab.update_display()
    assert tab.zones_model.index(0, 0).data(ROW_STATE_ROLE) is None


def _grid_states(grid):
    cols = {name: i for i, name in enumerate(grid.columns)}
    return {(row, name): grid.table.item(row, c).data(STATE_ROLE)
            for row in range(grid.table.rowCount()) for name, c in cols.items()
            if name in ("vsh_cutoff", "phi_cutoff", "sw_cutoff")}


def test_zone_grid_marks_limiting_cutoff_for_a_fresh_run(qtbot):
    model, zones = _model(stale=False)
    model.set_edit_scope("well")
    grid = ZoneParamGrid(model)
    qtbot.addWidget(grid)
    states = _grid_states(grid)
    assert states[(0, "phi_cutoff")] == "warning"
    assert states[(1, "sw_cutoff")] == "info"
    assert states[(0, "sw_cutoff")] == "inherited"
    assert "No net reservoir" in grid.table.item(0, grid.columns.index("phi_cutoff")).toolTip()


def test_zone_grid_shows_nothing_for_a_stale_run(qtbot):
    model, _ = _model(stale=True)
    model.set_edit_scope("well")
    grid = ZoneParamGrid(model)
    qtbot.addWidget(grid)
    assert set(_grid_states(grid).values()) == {"inherited"}


def test_zone_grid_shows_nothing_at_project_scope(qtbot):
    model, _ = _model()
    grid = ZoneParamGrid(model)
    qtbot.addWidget(grid)
    assert set(_grid_states(grid).values()) == {"inherited"}
