"""LRLC Workbench Diagnosis panels: Pickett plot with Apply, and the Buckles plot."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pytest
from PyQt6.QtWidgets import QMessageBox

from models.app_model import AppModel
from models.project import WellDataset
from modules.lrlc import pickett
from ui.widgets.lrlc_buckles import BucklesPanel
from ui.widgets.lrlc_pickett import PickettPanel


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A modal box would block the offscreen test run; fail loudly instead."""
    def refuse(*args, **kwargs):
        raise AssertionError(f"unexpected dialog: {args[1:3]}")

    for name in ("warning", "critical", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(refuse))


def _results(n=400, seed=3):
    rng = np.random.default_rng(seed)
    phi = rng.uniform(0.08, 0.30, n)
    vsh = rng.uniform(0.0, 0.5, n)
    rt = 1.0 * 0.05 / phi ** 2.0 * rng.normal(1.0, 0.02, n)
    hc = rng.random(n) < 0.5
    rt = np.where(hc, rt * 6.0, rt)
    sw = np.where(hc, rng.uniform(0.2, 0.6, n), 1.0)
    swirr = np.full(n, 0.2)
    depth = 5000.0 + 0.5 * np.arange(n)
    zone = np.where(np.arange(n) < n // 2, "UPPER", "LOWER")
    return pd.DataFrame({
        "DEPTH": depth, "RT": rt, "PHIE": phi, "PHIT": phi + 0.02, "VSH": vsh, "SW": sw,
        "SWIRR": swirr, "NET_RES_FLAG": (vsh < 0.4).astype(int), "BVW": phi * sw,
        "WATER_FREE_FLAG": ((sw <= swirr + 0.05) & (vsh < 0.4)).astype(int), "ZONE": zone,
    })


def _sources():
    table = {"a": {"value": 1.0, "source": "project"}, "m": {"value": 2.0, "source": "project"},
             "n": {"value": 2.0, "source": "project"}, "rw": {"value": 0.05, "source": "project"},
             "k_buckles": {"value": 0.04, "source": "project"}}
    return {"(well)": table, "UPPER": table, "LOWER": table}


def _model(with_results=True):
    model = AppModel()
    ds = WellDataset(key="WELL:A", display_name="A")
    res = _results()
    ds.las_data = res[["DEPTH", "RT"]].copy()
    ds.curve_mapping = {"RT": "RT"}
    if with_results:
        ds.results = res
        ds.summary = {"param_sources": _sources()}
        ds.calculated = True
    model.add_well(ds)
    model.set_active_well("WELL:A")
    return model, ds


@pytest.fixture()
def pickett_panel(qtbot):
    model, ds = _model()
    panel = PickettPanel()
    qtbot.addWidget(panel)
    panel.set_context(model, ds, None)
    return panel, model, ds


def test_pickett_fit_ok_recovers_archie(pickett_panel):
    panel, _, _ = pickett_panel
    fit = panel._fit
    assert fit.status == "ok"
    assert fit.m == pytest.approx(2.0, rel=0.03)
    assert fit.rw == pytest.approx(0.05, rel=0.05)
    assert panel.apply_m_btn.isEnabled() and panel.apply_mrw_btn.isEnabled()
    assert "m" in panel.readout.text() and "Rw" in panel.readout.text()


def test_apply_m_writes_well_zone_entry_after_confirmation(pickett_panel, qtbot):
    panel, model, ds = pickett_panel
    panel.set_context(model, ds, "LOWER")
    assert panel._fit.status == "ok"
    with qtbot.waitSignal(panel.stale_requested) as sig:
        panel.apply_m_btn.click()
        assert panel.confirm_box.isVisibleTo(panel)
        assert "well-zone" in panel.confirm_label.text()
        assert "own segment" in panel.confirm_label.text()
        assert ds.zone_overrides.get("LOWER") is None       # nothing written before confirming
        panel.confirm_btn.click()
    assert sig.args == [["WELL:A"]]
    entry = ds.zone_overrides["LOWER"]["m"]
    assert entry["mode"] == "manual" and entry["source"] == "pickett"
    assert entry["value"] == pytest.approx(round(panel._fit.m, 3))
    assert "rw" not in ds.zone_overrides["LOWER"]
    assert ds.results is not None                         # the panel never ran the pipeline


def test_apply_m_and_rw_at_well_scope_and_cancel(pickett_panel):
    panel, model, ds = pickett_panel
    panel.apply_mrw_btn.click()
    assert "automatic to manual" in panel.confirm_label.text()
    assert "well scope" in panel.confirm_label.text()
    panel.cancel_btn.click()
    assert not panel.confirm_box.isVisibleTo(panel) and not ds.overrides.get("m")
    before = model.well_params_hash(ds)
    panel.apply_mrw_btn.click()
    panel.confirm_btn.click()
    assert model.well_params_hash(ds) != before
    assert ds.overrides["m"]["source"] == "pickett"
    assert ds.overrides["rw"]["value"] == pytest.approx(round(panel._fit.rw, 4))


def test_apply_disabled_for_non_ok_status(pickett_panel):
    panel, _, _ = pickett_panel
    panel.min_points.setValue(500)
    assert panel._fit.status == "too_few_points"
    assert not panel.apply_m_btn.isEnabled() and not panel.apply_mrw_btn.isEnabled()
    assert "Too few wet points" in panel.status_label.text()
    panel.request_apply(False)
    assert not panel.confirm_box.isVisibleTo(panel)


def test_settings_persist_without_changing_hash(pickett_panel):
    panel, model, ds = pickett_panel
    before = model.well_params_hash(ds)
    panel.vsh_max.setValue(0.15)
    panel.fit_mode.setCurrentIndex(panel.fit_mode.findData("rw_only"))
    panel.phi_source.setCurrentText("PHIT")
    stored = model.project.lrlc["pickett"]
    assert stored["vsh_max"] == pytest.approx(0.15)
    assert stored["fit_mode"] == "rw_only" and stored["phi_source"] == "PHIT"
    assert model.well_params_hash(ds) == before


def test_manual_boxes_change_wet_points_and_reset(pickett_panel):
    panel, _, _ = pickett_panel
    auto_n = panel._fit.n_points
    panel.add_manual_box("remove", 0.05, 0.40, 0.1, 1000.0)
    assert panel._fit.status == "no_data"
    assert len(panel.manual_boxes()) == 1
    panel.reset_manual()
    assert panel.manual_boxes() == [] and panel._fit.n_points == auto_n


def test_no_results_says_run_first(qtbot):
    model, ds = _model(with_results=False)
    panel = PickettPanel()
    qtbot.addWidget(panel)
    panel.set_context(model, ds, None)
    assert "Run the analysis first" in panel.status_label.text()
    assert not panel.apply_m_btn.isEnabled()
    panel.refresh_theme()
    buckles = BucklesPanel()
    qtbot.addWidget(buckles)
    buckles.set_context(model, ds, None)
    assert "Run the analysis first" in buckles.status_label.text()
    assert buckles.table.rowCount() == 0


def test_temperature_normalisation_is_used_when_on(qtbot):
    model, ds = _model()
    model.temp_correction = True
    flat = model.params_for_well(ds)
    if not flat.get("temp_correction"):
        pytest.skip("temperature correction not exposed on the model")
    panel = PickettPanel()
    qtbot.addWidget(panel)
    panel.set_context(model, ds, None)
    assert panel.plot.figure.axes[0].get_ylabel().startswith("Rt at Rw reference")


def test_buckles_lines_and_table(qtbot):
    model, ds = _model()
    panel = BucklesPanel()
    qtbot.addWidget(panel)
    panel.set_context(model, ds, None)
    assert panel.line_values == model.project.lrlc["buckles"]["bvw_lines"]
    ax = panel.plot.figure.axes[0]
    # one dashed line per BVW value plus the k_buckles hyperbola
    assert len(ax.lines) == len(panel.line_values) + 1
    zones = [r["zone"] for r in panel.rows]
    assert zones == ["LOWER", "UPPER", "All zones"]
    assert panel.table.rowCount() == 3 and panel.table.columnCount() == 5
    total = panel.rows[-1]
    assert total["n"] == sum(r["n"] for r in panel.rows[:2])
    assert total["water_free_ft"] > 0
    assert total["mean_bvw"] > 0
    panel.set_context(model, ds, "UPPER")
    assert [r["zone"] for r in panel.rows] == ["UPPER"]


def test_both_panels_refresh_theme(pickett_panel, qtbot):
    panel, model, ds = pickett_panel
    panel.refresh_theme()
    buckles = BucklesPanel()
    qtbot.addWidget(buckles)
    buckles.set_context(model, ds, None)
    buckles.refresh_theme()
    assert buckles.table.rowCount() > 0


def test_pickett_module_used_for_default_settings(pickett_panel):
    panel, _, _ = pickett_panel
    assert set(pickett.DEFAULT_SETTINGS) <= set(panel._settings)
