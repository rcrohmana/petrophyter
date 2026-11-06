"""LRLC Workbench tab shell, Specialized menu, Data Browser action and restore notice."""

import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QFileDialog, QLabel, QMessageBox, QWidget

from models.project import WellDataset
from modules.lrlc import chain
from services.lrlc_service import LrlcService
from tests.golden.cases import FULL_MAPPING, fixture_frame
from tests.lrlc_teststeps import register_test_steps  # noqa: F401
from tests.test_multiwell_loading import _write
from ui.main_window import MainWindow


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


def _well(window, tops=("Upper", "Lower")):
    ds = WellDataset(key="WELL:A", display_name="A")
    ds.las_data = fixture_frame("sample_log_data")
    ds.curve_mapping = dict(FULL_MAPPING)
    if tops:
        ds.formation_tops = SimpleNamespace(
            formations=[
                SimpleNamespace(name=n, top_depth=1000.0 + 30 * i, bottom_depth=1030.0 + 30 * i)
                for i, n in enumerate(tops)],
            get_formation_list=lambda: list(tops))
    window.model.project.add_well(ds, activate=True)
    return ds


def _enable(window, qtbot):
    with qtbot.waitSignal(window.lrlc_tab.stale_requested, timeout=500):
        window.lrlc_tab.enable_button.click()


# ---- tab wiring ---------------------------------------------------------------------------
def test_tab_sits_between_saturation_height_and_summary(window):
    texts = [window.tab_widget.tabText(i) for i in range(window.tab_widget.count())]
    i = texts.index("Saturation-Height")
    assert texts[i:i + 3] == ["Saturation-Height", "LRLC Workbench", "Summary"]
    assert window.tab_widget.widget(i + 1) is window.lrlc_tab
    assert window.lrlc_tab in window._lazy_tabs


def test_placeholder_until_enabled_and_enable_writes(window, qtbot):
    tab = window.lrlc_tab
    assert tab.stack.currentIndex() == 0
    assert window.model.project.lrlc["enabled"] is False
    _well(window)
    with qtbot.waitSignal(tab.stale_requested, timeout=500) as blocker:
        tab.enable_button.click()
    assert blocker.args == [["WELL:A"]]
    assert window.model.project.lrlc["enabled"] is True
    assert window.model.dirty
    assert tab.stack.currentIndex() == 1


def test_disable_keeps_settings_and_emits(window, qtbot):
    tab = window.lrlc_tab
    _enable(window, qtbot)
    LrlcService.set_param(window.model, "project", None, "screen_rt_max", 7.0)
    with qtbot.waitSignal(tab.stale_requested, timeout=500):
        tab.disable_check.setChecked(True)
    assert window.model.project.lrlc["enabled"] is False
    assert window.model.project.lrlc["params"]["default"]["screen_rt_max"] == 7.0
    assert tab.stack.currentIndex() == 0
    assert not tab.disable_check.isChecked()


def test_four_panels(window, qtbot):
    _well(window)
    _enable(window, qtbot)
    tab = window.lrlc_tab
    titles = [tab.panels.tabText(i) for i in range(tab.panels.count())]
    assert titles == ["Screening", "Diagnosis", "Remediation", "Validation"]
    tab.show_panel("remediation")
    assert tab.panels.currentIndex() == 2
    tab.show_panel("screening", "rt_cutoff")
    assert tab.panels.currentIndex() == 0
    assert "Vsh" in tab.cutoffs_label.text() or "cutoff" in tab.cutoffs_label.text().lower()
    tab.show_panel("validation")
    text = tab.validation_panel.status_label.text()
    assert "correction" in text and not re.search(r"\b[A-Z]\d\b|\bL\d\b|\bP\d\b", text)


def test_diagnosis_sub_tabs_and_swap(window, qtbot):
    _enable(window, qtbot)
    tab = window.lrlc_tab
    names = [tab.diagnosis_tabs.tabText(i) for i in range(tab.diagnosis_tabs.count())]
    assert names == ["Zones", "Thomas-Stieber", "Pickett", "Buckles"]
    assert tab.diagnosis_tabs.widget(2).objectName() == "pickettPage"
    assert tab.diagnosis_tabs.widget(3).objectName() == "bucklesPage"
    assert any(l.text() == "Run the analysis first"
               for l in tab.diagnosis_tabs.widget(2).findChildren(QLabel))
    p, b = QWidget(), QWidget()
    tab.set_diagnosis_pages(p, b)
    assert tab.diagnosis_tabs.widget(2) is p and p.objectName() == "pickettPage"
    assert tab.diagnosis_tabs.widget(3) is b and b.objectName() == "bucklesPage"
    assert tab.diagnosis_tabs.count() == 4


# ---- remediation ---------------------------------------------------------------------------
def test_remediation_note_with_empty_registry(window, qtbot, monkeypatch):
    monkeypatch.setattr(chain, "STEPS", {})
    _enable(window, qtbot)
    tab = window.lrlc_tab
    assert tab.remediation_note.text() == (
        "No Rt correction steps are available in this version. Sw reads the measured Rt.")
    assert not tab.remediation_note.isHidden()
    assert tab.chain_note.text() == "Rsh and Rw estimators stay on the measured RT."
    assert tab.rt_source_table.columnCount() == 2
    assert tab.rt_source_table.item(0, 1).text() == "RT"


def test_remediation_follows_registry_and_writes_steps(window, qtbot, register_test_steps,
                                                       monkeypatch):
    monkeypatch.delitem(chain.STEPS, "invasion", raising=False)
    monkeypatch.delitem(chain.STEPS, "laminated")
    monkeypatch.delitem(chain.STEPS, "pyrite")
    _well(window)
    _enable(window, qtbot)
    tab = window.lrlc_tab
    tab.update_display()
    assert tab.remediation_note.isHidden()
    assert tab.rt_source_table.columnCount() == 2 + 5
    box = tab.rt_source_table.cellWidget(0, 2 + 1)         # row 0 = default, step test_scale
    with qtbot.waitSignal(tab.stale_requested, timeout=500) as blocker:
        box.setChecked(True)
    assert blocker.args == [["WELL:A"]]                     # well level: the active well only
    assert window.model.active_well.lrlc["default"]["rt_steps"] == ["test_scale"]
    assert tab.rt_source_table.item(0, 1).text() == "RT_X2 <- RT"
    tab.level_combo.setCurrentIndex(tab.level_combo.findData("project"))
    with qtbot.waitSignal(tab.stale_requested, timeout=500):
        tab.fallback_combo.setCurrentIndex(tab.fallback_combo.findData("previous"))
    assert window.model.project.lrlc["params"]["default"]["rt_fallback"] == "previous"


# ---- screening ladder ----------------------------------------------------------------------
def test_set_here_and_inherit_project_default(window, qtbot):
    _enable(window, qtbot)
    tab = window.lrlc_tab
    w = tab.param_widgets["screen_rt_max"]
    assert "built-in" in w["source"].text()
    w["spin"].setValue(7.5)
    with qtbot.waitSignal(tab.stale_requested, timeout=500):
        w["set"].click()
    assert window.model.project.lrlc["params"]["default"]["screen_rt_max"] == 7.5
    assert "project default" in w["source"].text()
    with qtbot.waitSignal(tab.stale_requested, timeout=500):
        w["inherit"].click()
    assert "screen_rt_max" not in window.model.project.lrlc["params"]["default"]
    assert "built-in" in w["source"].text()


def test_set_here_well_zone_writes_the_active_well(window, qtbot):
    ds = _well(window)
    _enable(window, qtbot)
    tab = window.lrlc_tab
    tab.scope_buttons["well_zone"].setChecked(True)
    tab.scope_zone_combo.setCurrentIndex(tab.scope_zone_combo.findData("UPPER"))
    w = tab.param_widgets["screen_min_score"]
    w["spin"].setValue(4)
    with qtbot.waitSignal(tab.stale_requested, timeout=500) as blocker:
        w["set"].click()
    assert blocker.args == [["WELL:A"]]
    assert ds.lrlc["zones"]["UPPER"]["screen_min_score"] == 4
    assert "well zone" in w["source"].text()


def test_curves_and_settings_write(window, qtbot):
    ds = _well(window)
    _enable(window, qtbot)
    tab = window.lrlc_tab
    combo = tab.curve_combos["RXO"]
    with qtbot.waitSignal(tab.stale_requested, timeout=500):
        combo.setCurrentIndex(1)                            # Not used
    assert ds.lrlc_curves["RXO"] is None
    with qtbot.waitSignal(tab.stale_requested, timeout=500):
        combo.setCurrentIndex(0)                            # Auto
    assert "RXO" not in ds.lrlc_curves
    with qtbot.waitSignal(tab.stale_requested, timeout=500):
        tab.rt_cut_check.setChecked(True)
    assert window.model.project.lrlc["rt_cutoff"]["enabled"] is True
    with qtbot.waitSignal(tab.stale_requested, timeout=500):
        tab.use_rs_check.setChecked(False)
    assert window.model.project.lrlc["screening"]["use_rs"] is False


def test_candidate_table_reads_the_summary(window, qtbot):
    ds = _well(window)
    ds.summary = {"lrlc": {"screening": {"zones": [
        {"zone": "UPPER", "n": 30, "candidate_ft": 4.5, "candidate_not_pay_ft": 3.0,
         "pct_of_net_res": 12.0, "avg_phie": 0.2, "avg_vsh": 0.3, "avg_sw": 0.7, "avg_rt": 2.1,
         "rt_cut": 4.2}], "unavailable": []}}}
    _enable(window, qtbot)
    table = window.lrlc_tab.candidate_table
    assert table.rowCount() == 1 and table.item(0, 0).text() == "UPPER"
    assert table.item(0, 2).text() == "4.5"


# ---- Pickett Apply -------------------------------------------------------------------------
def test_apply_pickett_writes_scoped_entries_and_never_runs(window, monkeypatch, qtbot):
    ds = _well(window)
    calls = []
    monkeypatch.setattr("modules.pipeline.run_pipeline",
                        lambda *a, **k: calls.append(1) or pytest.fail("pipeline ran"))
    fit = SimpleNamespace(status="ok", m=2.1234, rw=0.05678)
    with qtbot.waitSignal(window.model.scoped_params_changed, timeout=500):
        assert LrlcService.apply_pickett(window.model, ds, "UPPER", fit, True)
    zone = ds.zone_overrides["UPPER"]
    assert zone["m"]["value"] == 2.123 and zone["m"]["source"] == "pickett"
    assert zone["rw"]["value"] == 0.0568 and zone["rw"]["source"] == "pickett"
    assert LrlcService.apply_pickett(window.model, ds, None, fit, False)
    assert ds.overrides["m"]["value"] == 2.123 and ds.overrides["m"]["source"] == "pickett"
    assert "rw" not in ds.overrides
    assert not LrlcService.apply_pickett(window.model, ds, None,
                                         SimpleNamespace(status="too_few_points", m=2, rw=1), True)
    assert calls == []


# ---- Data Browser --------------------------------------------------------------------------
def test_browser_menu_offers_lrlc_for_a_top_and_routes(window, qtbot, monkeypatch):
    from PyQt6.QtCore import Qt
    from ui.data_browser import _KIND_ROLE

    _well(window)
    window.data_browser.rebuild()
    model = window.data_browser.tree_model
    index = None

    def walk(item):
        nonlocal index
        for r in range(item.rowCount()):
            child = item.child(r, 0)
            if child.data(_KIND_ROLE) == "top" and child.text() == "Upper":
                index = child.index()
            walk(child)

    for r in range(model.rowCount()):
        walk(model.item(r, 0))
    assert index is not None
    menu = window.data_browser._build_menu(index)
    action = next(a for a in menu.actions() if a.text() == "Analyze as LRLC candidate")
    assert not action.icon().isNull()
    seen = []
    window.data_browser.action_requested.connect(seen.append)
    action.trigger()
    assert seen == ["lrlc_zone:UPPER"]
    # a well node has no such entry
    assert not any(a.text() == "Analyze as LRLC candidate"
                   for a in window.data_browser._build_menu(model.item(0, 0).index()).actions())
    assert Qt  # keep import used


def test_browser_action_opens_the_workbench_on_the_zone(window, qtbot):
    _well(window)
    window._on_browser_action("lrlc_zone:UPPER")
    assert window.tab_widget.currentWidget() is window.lrlc_tab
    assert window.lrlc_tab.panels.currentIndex() == 1
    assert window.lrlc_tab._pending_zone == "UPPER"          # LRLC off: remembered
    assert window.lrlc_tab.stack.currentIndex() == 0
    window.lrlc_tab.enable_button.click()                    # applied after Enable
    assert window.lrlc_tab.selected_zone() == "UPPER"
    assert window.lrlc_tab.scope_zone_combo.currentData() == "UPPER"
    window._on_browser_action("lrlc_zone:LOWER")             # LRLC on: immediate
    assert window.lrlc_tab.selected_zone() == "LOWER"


def test_show_lrlc_forwards_panel_section_zone(window, qtbot):
    _well(window)
    _enable(window, qtbot)
    window.show_lrlc("remediation")
    assert window.lrlc_tab.panels.currentIndex() == 2
    window.show_lrlc(zone="UPPER")
    assert window.lrlc_tab.panels.currentIndex() == 0 and window.lrlc_tab.selected_zone() == "UPPER"


# ---- menus ---------------------------------------------------------------------------------
def test_specialized_menu_entries_and_order(window):
    titles = [a.text().replace("&", "") for a in window.menuBar().actions()]
    assert titles == ["File", "Session", "Analysis", "Specialized", "Parameters", "Corrections",
                      "View", "Help"]
    menu = window._menus["specialized"]
    assert menu.title() == "Speciali&zed"
    acts = menu.actions()
    assert acts[0] is window.actions_["lrlc_workbench"]
    assert acts[1].isSeparator()
    sub = window.actions_["saturation_tools_menu"]
    assert acts[2] is sub and sub.text() == "Saturation Tools"
    assert sub.menu().actions() == [window.actions_["rt_cutoff_overlay"],
                                    window.actions_["shf_shortcut"]]
    help_actions = [a for a in window.menuBar().actions() if a.text() == "&Help"][0].menu().actions()
    assert window.actions_["references"] in help_actions
    for key in ("lrlc_workbench", "rt_cutoff_overlay", "shf_shortcut", "saturation_tools_menu",
                "references"):
        assert key in window._action_icons and not window.actions_[key].icon().isNull()


def test_ctrl_l_and_menu_actions_route(window, qtbot):
    assert window.actions_["lrlc_workbench"].shortcut().toString() == "Ctrl+L"
    window.actions_["lrlc_workbench"].trigger()
    assert window.tab_widget.currentWidget() is window.lrlc_tab
    window.tab_widget.setCurrentWidget(window.qc_tab)
    window.actions_["rt_cutoff_overlay"].trigger()
    assert window.tab_widget.currentWidget() is window.lrlc_tab
    window.actions_["shf_shortcut"].trigger()
    assert window.tab_widget.currentWidget() is window.shf_tab


def test_references_action_opens_the_dialog(window, monkeypatch):
    from ui.widgets.references_dialog import ReferencesDialog

    opened = []
    monkeypatch.setattr(ReferencesDialog, "exec", lambda self: opened.append(self) or 0)
    window.actions_["references"].trigger()
    assert len(opened) == 1 and isinstance(opened[0], ReferencesDialog)


# ---- restore notice ------------------------------------------------------------------------
def test_restore_appends_the_newer_minor_notice(window, tmp_path, monkeypatch, qtbot):
    window._load_single_las(_write(tmp_path, "a.las", well="BKS-01"))
    path = tmp_path / "s.json"
    assert window.session_service.save_session(window.model, str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["_session_version"] = "2.9"
    path.write_text(json.dumps(data), encoding="utf-8")
    window.model.reset()
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(path), "")))
    window._on_load_session()
    qtbot.waitUntil(lambda: window._restore_worker is None, timeout=15000)
    text = window.banner.message_label.text()
    assert "saved by a newer Petrophyter (format 2.9)" in text
    window._cancel_restore()


# ---- hygiene -------------------------------------------------------------------------------
def test_source_has_no_emoji_or_hex_colours():
    import pathlib

    source = pathlib.Path(__file__).resolve().parents[1].joinpath(
        "ui", "tabs", "lrlc_tab.py").read_text(encoding="utf-8")
    assert not re.search("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️]", source)
    assert not re.search(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b", source)
    assert "pipeline" not in source.replace("pipeline code", "")


def test_new_project_resets_the_tab(window, qtbot):
    _enable(window, qtbot)
    window.lrlc_tab.select_zone("UPPER")
    window.model.reset()
    window.lrlc_tab.reset_ui()
    assert window.lrlc_tab.stack.currentIndex() == 0
    assert window.lrlc_tab._pending_zone is None
