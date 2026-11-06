"""Variable m/n and Radial invasion in the LRLC Workbench: service, form sections, plots, menus,
log display and design hygiene."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pathlib
import re

import numpy as np
import pandas as pd
import pytest
from PyQt6.QtWidgets import QCheckBox, QComboBox, QMessageBox

from models.project import WellDataset
from modules.lrlc.config import resolve_lrlc
from modules.lrlc.invasion import forward_ra
from modules.lrlc.methods import METHOD_TEXT
from modules.lrlc import SHIPPED_METHODS
from modules.pipeline import WELL_SOURCES_KEY
from services import lrlc_service as svc
from services.lrlc_service import LrlcService
from themes import tokens
from themes.colors import get_plot_color
from ui.main_window import MainWindow
from ui.widgets import track_specs as ts
from ui.widgets.interactive_log import InteractiveLogPlot
from ui.widgets.lrlc_invasion_plot import CONTRASTS, forward_loci, profile_steps
from ui.tabs.lrlc_tab import REMEDIATION_SECTIONS
from ui.widgets.lrlc_mn_invasion import parse_header_mud
from ui.widgets.lrlc_mn_plot import fitted_curves
from ui.widgets.plot_widget import CompositeLogPlot

TRUE_COEF = (1.9, 0.5, 0.3)
R50 = (80.0, 45.0, 20.0)


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A modal box would block the offscreen test run; fail loudly instead."""
    def refuse(*args, **kwargs):
        raise AssertionError(f"unexpected dialog: {args[1:3]}")

    for name in ("warning", "critical", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(refuse))


@pytest.fixture()
def window(qtbot):
    w = MainWindow()
    qtbot.addWidget(w, before_close_func=lambda w: w._set_busy(None))
    return w


def synth_results(n=900, seed=5, rw=0.05, with_invasion=False):
    """Two zones; 70 percent of the samples are water-bearing and follow the variable-m line."""
    rng = np.random.default_rng(seed)
    phi = rng.uniform(0.08, 0.30, n)
    vsh = rng.uniform(0.0, 0.25, n)
    m = TRUE_COEF[0] + TRUE_COEF[1] * phi + TRUE_COEF[2] * vsh
    rt = rw / phi ** m
    rt[rng.random(n) < 0.3] *= 5.0
    res = pd.DataFrame({
        "DEPTH": 1000.0 + 0.5 * np.arange(n), "PHIE": phi, "PHIT": phi + 0.02, "VSH": vsh,
        "RT": rt, "RT_SW": rt, "SW": 0.5,
        "ZONE": np.where(np.arange(n) < n // 2, "UPPER", "LOWER")})
    if with_invasion:
        rt_true = rt
        rxo = rt_true / 6.0
        di = rng.uniform(20.0, 90.0, n)
        ra = forward_ra(rt_true, rxo, di, R50, 2.5)
        res["RT"], res["RM"], res["RS"] = ra[:, 0], ra[:, 1], ra[:, 2]
        res["RT_INV"], res["RXO_INV"], res["DI_INV"] = rt_true, rxo, di
        res.loc[::7, "DI_INV"] = np.nan
    return res


def make_synth_well(window, results=None, rw=0.05, rw_mode="manual", invasion=False):
    res = results if results is not None else synth_results(with_invasion=invasion)
    ds = WellDataset(key="WELL:S", display_name="S")
    log = res[["DEPTH", "RT"]].copy()
    if invasion:
        log["RM"], log["RS"] = res["RM"], res["RS"]
    ds.las_data = log
    ds.curve_mapping = {**ds.curve_mapping, "RT": "RT"}
    ds.results = res
    table = {"a": {"value": 1.0, "mode": "manual"}, "m": {"value": 2.0, "mode": "manual"},
             "n": {"value": 2.0, "mode": "manual"}}
    if rw is not None:
        table["rw"] = {"value": rw, "mode": rw_mode}
    ds.summary = {"param_sources": {WELL_SOURCES_KEY: table}, "lrlc": {}}
    ds.calculated = True
    window.model.project.add_well(ds, activate=True)
    return ds


def enable(window, qtbot):
    with qtbot.waitSignal(window.lrlc_tab.stale_requested, timeout=500):
        window.lrlc_tab.enable_button.click()
    return window.lrlc_tab


def stored(window, key, zone=None, ds=None):
    present, value = LrlcService._stored_value(window.model, "well", zone, key, ds)
    return value if present else None


# ---- service: fit proposal -----------------------------------------------------------------
def test_fit_proposal_recovers_the_coefficients_and_writes_nothing(window):
    ds = make_synth_well(window)
    before = (dict(window.model.project.lrlc.get("params") or {}), dict(ds.lrlc or {}))
    prop = svc.variable_m_proposal(window.model, ds)
    assert prop.status == "fit" and prop.ok
    assert prop.rt_curve == "RT_SW" and prop.basis == "bulk" and prop.phi_source == "phie"
    assert prop.fit.coef[:3] == pytest.approx(TRUE_COEF, abs=1e-6)
    assert prop.rw == 0.05 and prop.a == 1.0 and prop.n_wet > 40
    assert (dict(window.model.project.lrlc.get("params") or {}), dict(ds.lrlc or {})) == before


def test_fit_proposal_zone_uses_that_zone_and_phit_option(window):
    ds = make_synth_well(window)
    prop = svc.variable_m_proposal(window.model, ds, "UPPER")
    assert prop.zone == "UPPER" and prop.n_rows == 450
    phit = svc.variable_m_proposal(window.model, ds, None, phi_source="phit")
    assert phit.phi_source == "phit"
    assert phit.fit.coef[0] != pytest.approx(TRUE_COEF[0], abs=1e-3)   # PHIT is not on the line


def test_fit_proposal_reads_rt_sw_before_rt(window):
    res = synth_results()
    res["RT_SW"] = res["RT"] * 1.0
    res["RT"] = res["RT"] * 3.0                  # the measured curve would give another fit
    ds = make_synth_well(window, res)
    prop = svc.variable_m_proposal(window.model, ds)
    assert prop.rt_curve == "RT_SW" and prop.fit.coef[0] == pytest.approx(1.9, abs=1e-6)
    ds.results = res.drop(columns=["RT_SW"])
    assert svc.variable_m_proposal(window.model, ds).rt_curve == "RT"


def test_fit_proposal_states_when_it_cannot_run(window):
    ds = make_synth_well(window, rw=None)
    prop = svc.variable_m_proposal(window.model, ds)
    assert prop.status == "no_rw" and prop.fit is None and not prop.ok
    ds.results = None
    assert svc.variable_m_proposal(window.model, ds).status == "no_results"
    assert svc.variable_m_proposal(window.model, None).status == "no_results"


def test_fit_proposal_flags_an_automatic_rw(window):
    ds = make_synth_well(window, rw_mode="auto")
    prop = svc.variable_m_proposal(window.model, ds)
    assert prop.rw_mode == "auto" and any("automatically" in n for n in prop.notes)


def test_fit_proposal_uses_the_shared_manual_boxes(window):
    ds = make_synth_well(window)
    free = svc.variable_m_proposal(window.model, ds)
    box = [("remove", 0.0, 1.0, 0.0, 1.0e9)]
    none = svc.variable_m_proposal(window.model, ds, manual=box)
    assert free.n_wet > 0 and none.n_wet == 0 and not none.ok


def test_sand_basis_is_rebuilt_from_the_result_columns(window):
    res = synth_results()
    n = len(res)
    res["VLAM"] = 0.3
    res["VDISP"] = 0.07
    res["PHI_SAND"] = 0.22
    ds = make_synth_well(window, res)
    assert LrlcService.apply_endpoints(window.model, "well", "UPPER", 0.30, 0.08, ds)
    assert LrlcService.apply_remediation(window.model, "well", "UPPER",
                                         {"rt_steps": ["laminated"]}, ds) == ["rt_steps"]
    phie, phit, vsh, basis = svc.zone_exponent_basis(window.model, ds, ds.results, "UPPER")
    assert basis == "sand"
    up = (ds.results["ZONE"] == "UPPER").to_numpy()
    assert phit[up] == pytest.approx(0.22)
    assert vsh[up] == pytest.approx(0.07 / 0.7)
    assert phie[up] == pytest.approx(0.30 - 0.07 / 0.7)
    assert phie[~up] == pytest.approx(ds.results["PHIE"].to_numpy()[~up])   # LOWER stays bulk
    assert svc.zone_exponent_basis(window.model, ds, ds.results, "LOWER")[3] == "bulk"
    assert svc.zone_exponent_basis(window.model, ds, ds.results, None)[3] == "mixed"
    prop = svc.variable_m_proposal(window.model, ds, "UPPER")
    assert prop.basis == "sand" and any("Sand basis" in x for x in prop.notes)
    assert n == len(phie)


def test_apply_variable_m_fit_writes_the_curve_settings(window):
    ds = make_synth_well(window)
    prop = svc.variable_m_proposal(window.model, ds)
    keys = svc.apply_variable_m_fit(window.model, "well", "UPPER", prop.fit, "phie", ds)
    assert set(keys) == {"mn_mode", "m_model", "m_coef", "phi_source"}
    prm = resolve_lrlc({}, ds.lrlc, "UPPER")
    assert prm["mn_mode"] == "curve" and prm["m_model"] == "formula"
    assert prm["m_coef"][:3] == pytest.approx(TRUE_COEF, abs=1e-5) and prm["m_coef"][3] == 0.0
    assert prm["n_model"] == "constant"                       # n is never touched
    assert resolve_lrlc({}, ds.lrlc, "LOWER")["mn_mode"] == "scalar"
    assert window.model.dirty
    assert svc.apply_variable_m_fit(window.model, "well", "UPPER", prop.fit, "phie", ds) == []


def test_apply_variable_m_fit_refuses_an_unusable_fit(window):
    ds = make_synth_well(window)
    prop = svc.variable_m_proposal(window.model, ds)
    prop.fit.apply_allowed = False
    assert svc.apply_variable_m_fit(window.model, "well", None, prop.fit, "phie", ds) == []
    assert svc.apply_variable_m_fit(window.model, "well", None, None, "phie", ds) == []
    assert not ds.lrlc


def test_summary_record_accepts_lists_and_dicts():
    rows = [{"zone": "UPPER", "n_ok": 3}, {"zone": "LOWER", "n_ok": 5}]
    assert svc.summary_record(rows, "LOWER")["n_ok"] == 5
    assert svc.summary_record(rows, None) is None
    assert svc.summary_record([{"zone": "WELL", "n_ok": 1}], None)["n_ok"] == 1
    assert svc.summary_record({"UPPER": {"n_ok": 2}}, "UPPER")["n_ok"] == 2
    assert svc.summary_record({"UPPER": {"n_ok": 2}}, None)["n_ok"] == 2
    assert svc.summary_record(None, "UPPER") is None


# ---- form: variable m/n ---------------------------------------------------------------------
def test_sections_exist_and_are_scroll_targets(window, qtbot):
    make_synth_well(window)
    tab = enable(window, qtbot)
    form = tab.remediation_form
    assert form.scroll_target("variable_mn").title() == "Variable m/n"
    assert form.scroll_target("invasion").title() == "Radial invasion"
    tab.show_panel("remediation", "variable_mn")
    tab.show_panel("remediation", "invasion")
    assert tab.panels.currentIndex() == 2
    assert "Shell model: m = 1.87 + 0.019 / phi (phi as a fraction)." in (
        METHOD_TEXT["variable_mn"].assumptions)
    assert "Guo et al. (2023)" in METHOD_TEXT["variable_mn"].assumptions
    assert SHIPPED_METHODS["variable_mn"] == ("archie1942", "borai1987", "guo2023")
    assert SHIPPED_METHODS["invasion"] == ("doll1949", "thadani1981", "anderson2001", "arps1953")
    assert METHOD_TEXT["invasion"].refs == SHIPPED_METHODS["invasion"]

REMEDIATION_TABS = {"rt_source": "Rt chain", "laminated": "Laminated sand", "pyrite": "Pyrite",
                    "clay": "Clay Qv", "sw_basis": "Sw basis", "variable_mn": "Variable m/n",
                    "invasion": "Radial invasion"}


def test_show_panel_selects_the_inner_remediation_tab(window, qtbot):
    make_synth_well(window)
    tab = enable(window, qtbot)
    tabs = tab.remediation_form.section_tabs
    assert [tabs.tabText(i) for i in range(tabs.count())] == list(REMEDIATION_TABS.values())
    for key, title in REMEDIATION_TABS.items():
        tab.show_panel("diagnosis")
        tab.show_panel("remediation", key)
        assert tab.panels.currentIndex() == 2
        assert tabs.tabText(tabs.currentIndex()) == title
    assert set(REMEDIATION_TABS) == set(REMEDIATION_SECTIONS)


def test_pending_change_on_one_tab_shows_in_the_shared_header(window, qtbot):
    make_synth_well(window)
    tab = enable(window, qtbot)
    form = tab.remediation_form
    tab.show_panel("remediation", "variable_mn")
    combo = form.controls["m_model"]
    combo.setCurrentIndex(1 - combo.currentIndex())
    assert form.apply_button.isEnabled()
    assert "m model" in form.pending_label.text()
    tab.show_panel("remediation", "invasion")
    spin = form.controls["inv_p"]
    spin.setValue(spin.value() + 0.1)
    text = form.pending_label.text()
    assert "m model" in text and "Shape exponent" in text
    tab.show_panel("remediation", "rt_source")
    assert form.apply_button.isEnabled() and form.pending_label.isVisibleTo(form)
    form.discard_button.click()
    assert not form.apply_button.isEnabled()



def test_controls_change_nothing_until_apply(window, qtbot):
    ds = make_synth_well(window)
    tab = enable(window, qtbot)
    form = tab.remediation_form
    before = (dict(window.model.project.lrlc["params"]), dict(ds.lrlc or {}))
    form.controls["mn_mode"].setCurrentIndex(form.controls["mn_mode"].findData("curve"))
    form.controls["m_coef"].spins[0].setValue(2.3)
    form.controls["n_model"].setCurrentIndex(form.controls["n_model"].findData("vsh"))
    form.controls["n_coef"].spins[1].setValue(0.5)
    assert (dict(window.model.project.lrlc["params"]), dict(ds.lrlc or {})) == before
    assert form.apply_button.isEnabled()
    with qtbot.waitSignal(form.stale_requested, timeout=500):
        form.apply_button.click()
    prm = resolve_lrlc({}, ds.lrlc, None)
    assert prm["mn_mode"] == "curve" and prm["n_model"] == "vsh"
    assert prm["m_coef"] == [2.3, 0.0, 0.0, 0.0] and prm["n_coef"] == [2.0, 0.5]


def test_coefficient_enabling_and_shell_badge(window, qtbot, monkeypatch):
    make_synth_well(window)
    tab = enable(window, qtbot)
    form = tab.remediation_form
    monkeypatch.setattr(form, "_flat_params",
                        lambda: {"m": 2.15, "n": 2.0, "lithology_preset": "Sandstone (Humble)"})
    assert not form.controls["n_coef"].isEnabled() and form.controls["m_coef"].isEnabled()
    form.controls["m_model"].setCurrentIndex(form.controls["m_model"].findData("shell"))
    assert not form.controls["m_coef"].isEnabled() and form.shell_check.isEnabled()
    assert "refused" in form.shell_badge.text()
    form.shell_check.setChecked(True)
    assert "because you confirmed it" in form.shell_badge.text()
    monkeypatch.setattr(form, "_flat_params",
                        lambda: {"m": 2.0, "n": 2.0, "lithology_preset": "Carbonate"})
    form._refresh_info()
    assert "Shell is evaluated." in form.shell_badge.text()
    assert "Zone values: m 2.000" in form.scoped_m_label.text()


def test_set_c0_to_the_zone_m_is_a_pending_edit(window, qtbot, monkeypatch):
    ds = make_synth_well(window)
    tab = enable(window, qtbot)
    form = tab.remediation_form
    monkeypatch.setattr(form, "_flat_params", lambda: {"m": 1.85, "n": 2.0})
    form.set_c0_button.click()
    assert form.controls["m_coef"].get()[0] == pytest.approx(1.85)
    assert "m_coef" in form._dirty and not ds.lrlc


def test_fit_button_shows_the_proposal_and_apply_fit_writes_it(window, qtbot):
    ds = make_synth_well(window)
    tab = enable(window, qtbot)
    form = tab.remediation_form
    assert form.mn_fit_button.isEnabled() and not form.mn_apply_fit_button.isEnabled()
    form.mn_fit_button.click()
    assert form.mn_fit_table.rowCount() == 4
    assert form.mn_fit_table.item(0, 1).text() == "1.9000"
    assert form.mn_fit_table.item(3, 0).text() == "c3 (fixed)"
    assert "Rt curve RT_SW" in form.mn_fit_inputs.text() and "bulk basis" in form.mn_fit_inputs.text()
    assert "Status: ok" in form.mn_fit_status.text()
    assert form.mn_plot.n_drawn > 40
    assert form.mn_apply_fit_button.isEnabled()
    assert not ds.lrlc                                        # fitting wrote nothing
    with qtbot.waitSignal(form.stale_requested, timeout=500):
        form.mn_apply_fit_button.click()
    assert stored(window, "mn_mode", ds=ds) == "curve"
    assert form.controls["m_coef"].get()[:3] == pytest.approx(TRUE_COEF, abs=1e-5)
    assert form.controls["mn_mode"].currentData() == "curve"
    assert "m_coef" not in form._dirty


def test_apply_fit_is_disabled_for_an_implausible_fit(window, qtbot):
    ds = make_synth_well(window)
    tab = enable(window, qtbot)
    form = tab.remediation_form
    window.model.project.lrlc["variable_mn"]["clip_m"] = [1.0, 1.5]
    form.mn_fit_button.click()
    assert "implausible m" in form.mn_fit_status.text()
    assert not form.mn_apply_fit_button.isEnabled()
    assert not ds.lrlc


def test_fit_button_reports_a_missing_rw(window, qtbot):
    make_synth_well(window, rw=None)
    tab = enable(window, qtbot)
    form = tab.remediation_form
    form.mn_fit_button.click()
    assert "Rw is unknown" in form.mn_fit_status.text()
    assert form.mn_fit_table.rowCount() == 0 and not form.mn_apply_fit_button.isEnabled()


def test_last_run_statistics_read_the_result_columns(window, qtbot):
    res = synth_results()
    res["M_VAR"], res["N_VAR"] = 2.1, 1.9
    ds = make_synth_well(window, res)
    ds.summary["lrlc"] = {"variable_mn": {"zones": [{"zone": "UPPER", "n_eval": 400,
                                                     "n_fallback": 50, "n_clipped_m": 3,
                                                     "n_clipped_n": 0}]}}
    tab = enable(window, qtbot)
    form = tab.remediation_form
    assert "m 2.10 / 2.10 / 2.10" in form.mn_last_label.text()
    form.zone = "UPPER"
    form._refresh_info()
    assert "400 evaluated" in form.mn_last_label.text() and "3 m clipped" in form.mn_last_label.text()
    assert "clipped to m 1 to 4" in form.clip_label.text()


# ---- form: radial invasion ------------------------------------------------------------------
def test_invasion_defaults_badge_and_r50(window, qtbot):
    make_synth_well(window, invasion=True)
    tab = enable(window, qtbot)
    form = tab.remediation_form
    assert not form.generic_badge.isHidden()
    assert form.generic_badge.text() == "generic, confirm with tool charts"
    assert form.controls["inv_r50"].get() == {"deep": 80.0, "medium": 45.0, "shallow": 20.0}
    assert not form.controls["inv_r50"].isEnabled()           # presets are read-only
    assert form._read_widget("inv_r50") is None
    assert form._read_widget("rmf") is None
    assert "RM, RS and RXO must already be corrected" in form.inv_banner.text()
    assert "The Invasion step is off" in form.inv_step_label.text()
    assert "RM RM" in form.inv_curves_label.text() and "RXO not mapped" in form.inv_curves_label.text()


def test_tool_change_loads_the_preset_and_custom_writes_radii(window, qtbot):
    ds = make_synth_well(window, invasion=True)
    tab = enable(window, qtbot)
    form = tab.remediation_form
    tool = form.controls["inv_tool"]
    tool.setCurrentIndex(tool.findData("generic_laterolog"))
    assert form.controls["inv_r50"].get() == {"deep": 70.0, "medium": 35.0, "shallow": 25.0}
    assert "inv_r50" not in form._dirty and not form.generic_badge.isHidden()
    tool.setCurrentIndex(tool.findData("custom"))
    assert form.controls["inv_r50"].isEnabled()
    form.controls["inv_r50"].spins[0].setValue(95.0)
    assert form.generic_badge.isHidden()
    form.controls["inv_p"].setValue(3.0)
    form.controls["rmf"].setValue(0.4)
    form.controls["rmf_temp"].setValue(68.0)
    assert not ds.lrlc
    with qtbot.waitSignal(form.stale_requested, timeout=500):
        form.apply_button.click()
    prm = resolve_lrlc({}, ds.lrlc, None)
    assert prm["inv_tool"] == "custom" and prm["inv_r50"] == {
        "deep": 95.0, "medium": 70.0 * 0 + 35.0, "shallow": 25.0}
    assert prm["inv_p"] == 3.0 and prm["rmf"] == 0.4 and prm["rmf_temp"] == 68.0


def test_back_to_a_preset_clears_the_stored_radii_value(window, qtbot):
    ds = make_synth_well(window, invasion=True)
    assert LrlcService.apply_remediation(
        window.model, "well", None,
        {"inv_tool": "custom", "inv_r50": {"deep": 90.0, "medium": 50.0, "shallow": 22.0}}, ds)
    tab = enable(window, qtbot)
    form = tab.remediation_form
    assert form.controls["inv_r50"].get()["deep"] == 90.0
    tool = form.controls["inv_tool"]
    tool.setCurrentIndex(tool.findData("generic_induction"))
    assert "inv_r50" in form._dirty and form._read_widget("inv_r50") is None
    form.apply_button.click()
    assert resolve_lrlc({}, ds.lrlc, None)["inv_r50"] is None


def test_header_rmf_proposal_is_offered_only_with_a_header_value(window, qtbot):
    ds = make_synth_well(window, invasion=True)
    tab = enable(window, qtbot)
    form = tab.remediation_form
    assert form.header_button.isHidden()
    ds.identity = {"rmf": 0.35, "rmf_temp": 20.0, "rmf_temp_unit": "degC"}
    form._refresh_info()
    assert not form.header_button.isHidden()
    assert "Rmf 0.3500 ohm.m at 68.0 degF" in form.header_label.text()
    form.header_button.click()
    assert form.controls["rmf"].value() == pytest.approx(0.35)
    assert form.controls["rmf_temp"].value() == pytest.approx(68.0)
    assert "rmf" in form._dirty


def test_parse_header_mud():
    assert parse_header_mud(None) is None and parse_header_mud({}) is None
    out = parse_header_mud({"rmf": 0.35, "rmf_unit": "OHMM", "rmf_temp": 68.0,
                            "rmf_temp_unit": "DEGF"})
    assert out == {"rmf": 0.35, "rmf_temp": 68.0, "note": ""}
    out = parse_header_mud({"rmf": 0.4, "rmf_unit": "OHM.M", "rmf_temp": 20.0,
                            "rmf_temp_unit": "DEGC"})
    assert out["rmf_temp"] == pytest.approx(68.0) and out["note"] == ""
    out = parse_header_mud({"rmf": 0.35, "rmf_temp": 68.0})
    assert "unit not stated" in out["note"] and out["rmf_temp"] == 68.0
    odd = parse_header_mud({"rmf": 0.3, "rmf_unit": "OHMM", "rmf_temp": 300.0,
                            "rmf_temp_unit": "K"})
    assert odd["rmf_temp"] is None and "temperature not offered" in odd["note"]
    assert parse_header_mud({"rmf": 0.3, "rmf_unit": "MS/M"}) is None
    assert parse_header_mud({"rmf": -1.0, "rmf_unit": "OHMM"}) is None
    assert parse_header_mud({"mud_rm": 0.5, "mud_rm_unit": "OHMM"}) is None


def test_l3_blocks_are_saved_through_set_setting(window):
    model = window.model
    assert LrlcService.set_setting(model, "variable_mn", "clip_m", [1.2, 3.5])
    assert model.project.lrlc["variable_mn"]["clip_m"] == [1.2, 3.5]
    assert not LrlcService.set_setting(model, "variable_mn", "clip_m", [3.0, 2.0])
    assert not LrlcService.set_setting(model, "variable_mn", "clip_m", [0.1, 2.0])
    assert not LrlcService.set_setting(model, "variable_mn", "clip_m", [1.0])
    assert LrlcService.set_setting(model, "variable_mn", "clip_warn_fraction", 0.1)
    assert not LrlcService.set_setting(model, "variable_mn", "clip_warn_fraction", 2.0)
    fit = dict(model.project.lrlc["variable_mn"]["fit"], min_phi_range=0.1)
    assert LrlcService.set_setting(model, "variable_mn", "fit", fit)
    assert model.project.lrlc["variable_mn"]["fit"]["min_phi_range"] == 0.1
    assert not LrlcService.set_setting(model, "variable_mn", "fit", {**fit, "f_scale": 99.0})
    assert not LrlcService.set_setting(model, "variable_mn", "fit", 3)
    assert LrlcService.set_setting(model, "invasion", "max_iter", 60)
    assert not LrlcService.set_setting(model, "invasion", "max_iter", 2)
    assert LrlcService.set_setting(model, "invasion", "rt_bounds", [0.1, 5000.0])
    assert not LrlcService.set_setting(model, "invasion", "rt_bounds", [5000.0, 0.1])
    assert not LrlcService.set_setting(model, "invasion", "nope", 1)


def test_invasion_plots_draw_from_the_last_run(window, qtbot):
    make_synth_well(window, invasion=True)
    tab = enable(window, qtbot)
    form = tab.remediation_form
    assert form.tornado_plot.n_drawn == 900
    assert form.depth_spin.isEnabled()
    form.depth_spin.setValue(1010.0)
    ax = form.profile_plot.plot.figure.axes[0]
    assert ax.get_yscale() == "log" and "1010" in ax.get_title()
    picked = []
    form.tornado_plot.depth_picked.connect(picked.append)
    x, y, depth = form.tornado_plot._pts
    k = 100
    ax_t = form.tornado_plot.plot.figure.axes[0]

    class Event:
        xdata, ydata = float(x[k]), float(y[k])

    form.tornado_plot._on_click(Event)
    assert picked == [pytest.approx(float(depth[k]))]
    assert form.depth_spin.value() == pytest.approx(float(depth[k]), abs=0.01)
    assert ax_t.get_xscale() == "log"


def test_profile_has_no_curve_where_the_fit_is_empty(window, qtbot):
    ds = make_synth_well(window, invasion=True)
    tab = enable(window, qtbot)
    form = tab.remediation_form
    row = 7                                                   # DI_INV is NaN every 7th row
    form.depth_spin.setValue(float(ds.results["DEPTH"].iloc[row]))
    assert "no profile" in form.profile_plot.plot.figure.axes[0].get_title()


def test_tornado_works_before_a_run_and_needs_rm_rs(window, qtbot):
    ds = make_synth_well(window, invasion=True)
    ds.results = None
    tab = enable(window, qtbot)
    form = tab.remediation_form
    assert form.tornado_plot.n_drawn == 900           # RT, RM and RS come from the log
    assert not form.depth_spin.isEnabled() or form.depth_spin.value() >= 1000.0
    ds.las_data = ds.las_data.drop(columns=["RS"])
    form._refresh_info()
    assert form.tornado_plot._args is None


def test_counts_table_reads_the_summary_records(window, qtbot):
    ds = make_synth_well(window, invasion=True)
    ds.summary["lrlc"] = {"invasion": {"zones": [
        {"zone": "UPPER", "tool": "generic_induction", "generic": True, "n_valid": 400,
         "n_ok": 380, "n_nonunique": 10, "n_di_lower": 5, "n_di_upper": 3, "n_poor_fit": 1,
         "n_failed": 1, "n_missing": 50, "rt_ratio_p50": 0.9, "di_p50": 42.0}]}}
    tab = enable(window, qtbot)
    table = tab.remediation_form.inv_counts
    assert table.rowCount() == 1
    assert [table.item(0, c).text() for c in (0, 1, 2, 3, 10, 11)] == [
        "UPPER", "generic_induction (generic)", "400", "380", "0.900", "42.0"]


def test_empty_state_without_summary_keys(window, qtbot):
    make_synth_well(window)
    tab = enable(window, qtbot)
    form = tab.remediation_form
    assert form.inv_counts.rowCount() == 0
    assert "not in the last run" in form.mn_last_label.text()


# ---- plot geometry --------------------------------------------------------------------------
def test_forward_loci_pass_through_unity_for_no_contrast():
    loci = forward_loci(R50, 2.5, 8.0, 120.0, contrasts=(1.0, 0.1, 10.0))
    x, y, di = loci[1.0]
    assert x == pytest.approx(1.0) and y == pytest.approx(1.0)
    assert di[0] == pytest.approx(8.0) and di[-1] == pytest.approx(120.0)
    x, y, _ = loci[0.1]
    assert x.max() < 1.0 and y.max() < 1.0                    # a resistive Rt reads low inside
    assert y[0] < x[0] < 1.0                                  # shallow reads more flushed zone
    x, y, _ = loci[10.0]
    assert x.min() > 1.0 and y.min() > 1.0
    assert tuple(forward_loci(R50, 2.5, 8.0, 120.0)) == CONTRASTS


def test_profile_steps_and_fitted_curves():
    x, y = profile_steps(20.0, 2.0, 40.0, 100.0)
    assert x.tolist() == [0.0, 40.0, 40.0, 100.0] and y.tolist() == [2.0, 2.0, 20.0, 20.0]
    curves = fitted_curves([1.9, 0.5, 0.3, 0.0], (0.1, 0.3), [0.0, 0.1, 0.2, 0.3, 0.4])
    grid, m = curves[50]
    assert m[0] == pytest.approx(1.9 + 0.5 * grid[0] + 0.3 * 0.2)
    assert (curves[90][1] > curves[10][1]).all()


# ---- menus and navigation -------------------------------------------------------------------
def test_goto_target_opens_the_remediation_section(window, monkeypatch):
    seen = []
    monkeypatch.setattr(window, "show_lrlc", lambda *a, **k: seen.append(a))
    window._on_goto_target("lrlc.remediation.variable_mn")
    window._on_goto_target("lrlc.remediation.invasion")
    window._on_goto_target("lrlc.diagnosis")
    assert seen == [("remediation", "variable_mn"), ("remediation", "invasion"),
                    ("diagnosis", None)]


def test_goto_target_for_parameters_is_unchanged(window, monkeypatch):
    opened = []
    monkeypatch.setattr(window.params_window, "open_page", lambda p: opened.append(p))
    window._on_goto_target("params.rw")
    assert opened == ["sat"]


def test_menu_actions_open_the_sections(window, qtbot):
    make_synth_well(window)
    window.actions_["variable_mn"].trigger()
    assert window.tab_widget.currentWidget() is window.lrlc_tab
    window.actions_["rt_invasion"].trigger()
    assert window.lrlc_tab.panels.currentIndex() == 2


# ---- log display ----------------------------------------------------------------------------
def test_colour_tokens_for_the_new_curves_in_both_themes():
    for key in ("RT_INV", "RXO_INV", "DI_INV", "M_VAR", "N_VAR"):
        assert key in tokens.PLOT_COLORS
        assert get_plot_color(key, "dark") != get_plot_color(key, "light")


def test_new_curves_are_not_sw_methods_and_are_readout_or_resistivity():
    cols = ["SW_ARCHIE", "M_VAR", "N_VAR", "RT_INV", "RXO_INV", "DI_INV"]
    assert ts.sw_method_columns(cols) == ["SW_ARCHIE"]
    names = [c.name for c in ts.TRACK_SPECS["resistivity"].curves]
    assert "RT_INV" in names and "RXO_INV" in names
    assert ts.READOUT_ONLY_COLUMNS["DI_INV"] == "in"
    assert {"M_VAR", "N_VAR"} <= set(ts.READOUT_ONLY_COLUMNS)


def _log_results(n=40):
    res = pd.DataFrame({
        "DEPTH": np.linspace(1000.0, 1015.0, n), "GR": np.linspace(30, 120, n),
        "PHIE": 0.2, "SW": 0.5, "RT": np.linspace(1.0, 50.0, n)})
    res["RT_SW"] = res["RT_INV"] = res["RT"] * 1.2
    res["RXO_INV"] = res["RT"] / 5.0
    res["DI_INV"] = 40.0
    res["M_VAR"], res["N_VAR"] = 2.1, 1.9
    return res


def test_classic_engine_draws_rt_inv_and_rxo_inv(qtbot):
    plot = CompositeLogPlot()
    qtbot.addWidget(plot)
    plot.plot_petrophysics_summary(_log_results())
    ax = [a for a in plot.figure.axes if a.get_title() == "Resistivity"][0]
    styles = {ln.get_label(): ln.get_linestyle() for ln in ax.get_lines()}
    assert styles["RT_INV"] == "-" and styles["RXO_INV"] == ":"


@pytest.fixture
def w(qtbot):
    widget = InteractiveLogPlot(n_tracks=8)
    qtbot.addWidget(widget)
    return widget


def test_interactive_engine_draws_resistivity_and_reads_the_rest(w):
    config = w._default_curve_config(_log_results().columns.tolist())
    entries = {c[0]: c for c in config[3]}
    assert "RT_INV" in entries and entries["RXO_INV"][4]["dotted"] is True
    assert not entries["RT_INV"][4].get("dotted")
    w.plot_curves(_log_results())
    assert "RT_INV" in w.curve_items and "RXO_INV" in w.curve_items
    for name in ("M_VAR", "N_VAR", "DI_INV"):
        assert name not in w.curve_items and name in w.curves_data
    depth = float(_log_results()["DEPTH"].iloc[5])
    text = w.format_readout(w._get_values_at_depth(depth), depth)
    assert "DI_INV" in text and "M_VAR" in text and "RT_INV" in text


# ---- hygiene ----------------------------------------------------------------------------------
def test_new_sources_have_no_hex_emoji_or_internal_ids():
    root = pathlib.Path(__file__).resolve().parents[1]
    names = ("ui/widgets/lrlc_mn_invasion.py", "ui/widgets/lrlc_mn_plot.py",
             "ui/widgets/lrlc_invasion_plot.py", "ui/widgets/lrlc_remediation.py",
             "ui/tabs/lrlc_tab.py", "services/lrlc_service.py", "modules/lrlc/methods.py")
    for name in names:
        text = root.joinpath(name).read_text(encoding="utf-8")
        assert not re.search(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b", text), name
        assert not re.search("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️]", text), name
        assert "setStyleSheet" not in text, name
        assert not re.search(r"\b(L[1-4]|S[1-8]|P[0-9])\b", text), name
        if name.startswith("ui/widgets/lrlc_mn") or name.startswith("ui/widgets/lrlc_inv"):
            assert not re.search(r"(?i)spec", text), name


def test_new_icons_exist_in_the_lucide_set():
    root = pathlib.Path(__file__).resolve().parents[1] / "icons" / "lucide"
    assert (root / "calculator.svg").exists() and (root / "move.svg").exists()


def test_check_boxes_are_registered_controls(window, qtbot):
    make_synth_well(window)
    tab = enable(window, qtbot)
    form = tab.remediation_form
    assert isinstance(form.controls["shell_confirm"], QCheckBox)
    assert isinstance(form.controls["phi_source"], QComboBox)

def test_remediation_inner_tabs_fit_the_selected_section(window, qtbot):
    """No inner scroll: the tab widget is as tall as the selected section, so a short section
    leaves no empty space and a long one is shown whole in the page scroll."""
    make_synth_well(window)
    tab = enable(window, qtbot)
    window.show_lrlc("remediation", "clay")
    tabs = tab.remediation_form.section_tabs
    width = 1200
    short = tabs.heightForWidth(width)
    window.show_lrlc("remediation", "invasion")
    tall = tabs.heightForWidth(width)
    assert tall > short + 300
    assert tabs.currentWidget().parent() is not None
    from PyQt6.QtWidgets import QScrollArea
    assert not any(isinstance(tabs.widget(i), QScrollArea) for i in range(tabs.count()))
