"""Rt Corrections menu, shoulder-bed guard action, Diagnosis routing, log curves of the laminated
and pyrite columns in both engines, and the conditional Summary zone columns."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pytest
from PyQt6.QtWidgets import QMessageBox

from models.app_model import AppModel
from models.project import WellDataset
from modules.pipeline import run_pipeline
from services.lrlc_service import LrlcService
from tests.golden.cases import FULL_MAPPING, fixture_frame, make_tops
from themes import tokens
from ui.main_window import MainWindow
from ui.tabs.summary_tab import ZONE_BASE_COLUMNS, ZONE_TABLE_COLUMNS, SummaryTab
from ui.widgets import track_specs as ts
from ui.widgets.interactive_log import InteractiveLogPlot
from ui.widgets.plot_widget import CompositeLogPlot


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError(f"unexpected dialog: {args[1:3]}")

    for name in ("warning", "critical", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(refuse))


@pytest.fixture()
def window(qtbot):
    w = MainWindow()
    qtbot.addWidget(w, before_close_func=lambda w: w._set_busy(None))
    return w


# ---- menu ---------------------------------------------------------------------------------
def test_specialized_menu_has_rt_corrections_and_guard(window):
    acts = window._menus["specialized"].actions()
    assert acts[0] is window.actions_["lrlc_workbench"] and acts[1].isSeparator()
    assert acts[2] is window.actions_["saturation_tools_menu"]
    sub = window.actions_["rt_corrections_menu"]
    assert acts[3] is sub and sub.text() == "Rt Corrections"
    assert sub.menu().actions() == [window.actions_["rt_laminated"], window.actions_["rt_pyrite"]]
    assert window.actions_["rt_laminated"].text() == "Laminated Sand Rt (Hagiwara)…"
    assert window.actions_["rt_pyrite"].text() == "Pyrite Correction…"
    assert acts[4].isSeparator()
    guard = window.actions_["lrlc_guard"]
    assert acts[5] is guard and guard.isCheckable() and guard.isChecked()
    assert guard.text() == "Shoulder-bed Guard (laminated zones)"
    assert guard.icon().isNull() and "lrlc_guard" not in window._action_icons
    expected = {"rt_corrections_menu": "waves-horizontal", "rt_laminated": "layers",
                "rt_pyrite": "hexagon"}
    for key, icon in expected.items():
        assert window._action_icons[key] == icon
        assert not window.actions_[key].icon().isNull()


def test_icons_refresh_covers_new_actions(window):
    iconed = {k for k, a in window.actions_.items() if not a.icon().isNull()}
    assert iconed == set(window._action_icons)
    window._refresh_action_icons()
    assert not window.actions_["rt_laminated"].icon().isNull()


def test_rt_corrections_actions_route_to_the_remediation_panel(window, monkeypatch):
    seen = []
    monkeypatch.setattr(window, "show_lrlc", lambda *a, **k: seen.append((a, k)))
    window.actions_["rt_laminated"].trigger()
    window.actions_["rt_pyrite"].trigger()
    assert seen == [(("remediation", "laminated"), {}), (("remediation", "pyrite"), {})]


# ---- guard action -------------------------------------------------------------------------
def test_guard_action_writes_the_project_setting(window):
    model = window.model
    assert model.project.lrlc.get("guard", {}).get("enabled", True) is True
    guard = window.actions_["lrlc_guard"]
    guard.trigger()
    assert not guard.isChecked()
    assert model.project.lrlc["guard"]["enabled"] is False
    guard.trigger()
    assert model.project.lrlc["guard"]["enabled"] is True


def test_guard_toggle_requests_a_stale_recheck(window, monkeypatch):
    calls = []
    monkeypatch.setattr(window, "_recompute_stale", lambda keys=None: calls.append(keys))
    window.actions_["lrlc_guard"].trigger()
    assert calls == [None]


def test_guard_action_follows_the_project(window):
    LrlcService.set_guard_enabled(window.model, False)
    window._sync_lrlc_guard_action()
    assert not window.actions_["lrlc_guard"].isChecked()
    window._update_ui_from_model()
    assert not window.actions_["lrlc_guard"].isChecked()
    window.model.reset()
    window._reset_ui()
    assert window.actions_["lrlc_guard"].isChecked()
    # syncing writes nothing and does not dirty the project
    window.model.mark_clean()
    window._sync_lrlc_guard_action()
    assert not window.model.dirty


# ---- browser routing ----------------------------------------------------------------------
def test_zone_request_opens_diagnosis(window, monkeypatch):
    seen = []
    monkeypatch.setattr(window, "show_lrlc", lambda *a, **k: seen.append((a, k)))
    window._on_browser_action("lrlc_zone:UPPER")
    assert seen == [(("diagnosis",), {"zone": "UPPER"})]


# ---- log curves ---------------------------------------------------------------------------
def _results(extra=True, n=40):
    df = pd.DataFrame({
        "DEPTH": np.linspace(1000.0, 1015.0, n), "GR": np.linspace(30, 120, n),
        "VSH": np.linspace(0.1, 0.6, n), "PHIE": np.full(n, 0.2), "SW": np.full(n, 0.5),
        "RT": np.linspace(1.0, 50.0, n),
    })
    if extra:
        df["VLAM"] = df["VSH"] * 0.8
        df["SW_BASE"] = df["SW"] + 0.1
        df["RT_SAND"] = df["RT"] * 2
        df["RT_PYR"] = df["RT"] * 1.5
        df["VPYR"] = 0.03
        df["QV_EST"] = 0.2
    return df


def test_colour_tokens_exist_in_both_themes():
    for key in ("RT_SAND", "RT_PYR", "SW_BASE", "VLAM", "VPYR", "QV_EST"):
        assert key in tokens.PLOT_COLORS


def test_new_columns_are_not_sw_methods():
    cols = ["SW_ARCHIE", "SW_BASE", "RT_SAND", "RT_PYR", "VLAM", "VPYR", "QV_EST", "SW_PAY"]
    assert ts.sw_method_columns(cols) == ["SW_ARCHIE"]
    names = [c.name for c in ts.TRACK_SPECS["resistivity"].curves]
    assert "RT_SAND" in names and "RT_PYR" in names
    assert "VLAM" in [c.name for c in ts.TRACK_SPECS["gr_vsh"].curves]
    assert ts.pick_curve("resistivity", ["RT_PYR"]) == "RT_PYR"
    assert ts.pick_curve("sw", ["SW_BASE", "VPYR"]) is None


def test_interactive_log_draws_laminated_and_pyrite_curves(qtbot):
    w = InteractiveLogPlot(n_tracks=6)
    qtbot.addWidget(w)
    config = w._default_curve_config(_results().columns.tolist())
    assert {c[0]: c for c in config[0]}["VLAM"][4]["dotted"] is True
    sw = {c[0]: c for c in config[2]}
    assert sw["SW_BASE"][4]["dashed"] and sw["SW_BASE"][4]["thin"]
    rt = {c[0] for c in config[3]}
    assert {"RT_SAND", "RT_PYR"} <= rt
    w.plot_curves(_results())
    for name in ("VLAM", "SW_BASE", "RT_SAND", "RT_PYR"):
        assert name in w.curve_items
    for name in ("VPYR", "QV_EST"):
        assert name in w.curves_data and name not in w.curve_items
    assert w.curve_units["QV_EST"] == "meq/cc"


def test_interactive_log_without_the_columns_adds_nothing(qtbot):
    w = InteractiveLogPlot(n_tracks=6)
    qtbot.addWidget(w)
    w.plot_curves(_results(extra=False))
    for name in ("VLAM", "SW_BASE", "RT_SAND", "RT_PYR", "VPYR", "QV_EST"):
        assert name not in w.curve_items and name not in w.curves_data


def test_classic_log_draws_laminated_and_pyrite_curves(qtbot):
    plot = CompositeLogPlot()
    qtbot.addWidget(plot)
    plot.plot_petrophysics_summary(_results())
    axes = plot.figure.axes
    assert "Resistivity" in [a.get_title() for a in axes]
    labels = {ln.get_label(): ln for ax in axes for ln in ax.get_lines()}
    assert labels["Vlam (v/v)"].get_linestyle() == ":"
    assert labels["Sw base"].get_linestyle() == "--"
    assert labels["RT_SAND"].get_linestyle() == "-" and labels["RT_PYR"].get_linestyle() == "--"
    assert "VPYR" not in labels and "QV_EST" not in labels
    plot.plot_petrophysics_summary(_results(extra=False))
    labels = {ln.get_label() for ax in plot.figure.axes for ln in ax.get_lines()}
    assert not {"Vlam (v/v)", "Sw base", "RT_SAND", "RT_PYR"} & labels


def test_classic_resistivity_track_for_pyrite_only(qtbot):
    plot = CompositeLogPlot()
    qtbot.addWidget(plot)
    df = _results(extra=False)
    df["RT_PYR"] = df["RT"] * 1.5
    plot.plot_petrophysics_summary(df)
    assert "Resistivity" in [a.get_title() for a in plot.figure.axes]


# ---- summary ------------------------------------------------------------------------------
def _summary_model(with_base):
    ds = WellDataset("W:A", "Alpha")
    data = fixture_frame("sample_log_data")
    ds.las_data = data
    ds.curve_mapping = dict(FULL_MAPPING)
    ds.formation_tops = make_tops()
    results, summary = run_pipeline(data, FULL_MAPPING, {}, formation_tops=ds.formation_tops)
    if with_base:
        for z in summary["zones"]:
            z.update(net_pay_base=z["net_pay"] + 1.0, avg_sw_pay_base=0.42,
                     hcpv_net_pay_base=0.123)
    ds.results, ds.summary, ds.calculated = results, summary, True
    m = AppModel()
    m.project.add_well(ds)
    m.project.set_active("W:A")
    return m


def test_summary_zone_columns_conditional(qtbot):
    tab = SummaryTab(_summary_model(False))
    qtbot.addWidget(tab)
    tab.update_display()
    assert tab.zones_model.columnCount() == len(ZONE_TABLE_COLUMNS)

    tab = SummaryTab(_summary_model(True))
    qtbot.addWidget(tab)
    tab.update_display()
    zm = tab.zones_model
    assert zm.columnCount() == len(ZONE_TABLE_COLUMNS) + len(ZONE_BASE_COLUMNS)
    heads = [zm.headerData(c, tab.zones_table.horizontalHeader().orientation())
             for c in range(zm.columnCount())]
    assert heads[-3:] == ZONE_BASE_COLUMNS
    assert zm.index(0, zm.columnCount() - 2).data() == "42.0%"


def test_workbench_guard_switch_updates_the_menu(window):
    LrlcService.set_guard_enabled(window.model, False)
    window.lrlc_tab.guard_toggled.emit(False)
    assert not window.actions_["lrlc_guard"].isChecked()


def test_menu_guard_switch_refreshes_the_workbench(window, monkeypatch):
    calls = []
    monkeypatch.setattr(window.lrlc_tab, "update_display", lambda: calls.append(1))
    window.actions_["lrlc_guard"].trigger()
    assert calls == [1]


def test_workbench_sw_model_link_opens_the_parameters_page(window, monkeypatch):
    pages = []
    monkeypatch.setattr(window.params_window, "open_page", lambda page, **k: pages.append(page))
    window.lrlc_tab.navigate_requested.emit("params.sat")
    assert pages == ["sat"]
