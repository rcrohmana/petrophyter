"""Elastic flag section of the LRLC Workbench (Screening): presence, curves and the DTS warning,
the project switch, Set here / Inherit through the service, compact strips, the crossplots and
the score maximum."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QLabel, QMessageBox

from models.project import WellDataset
from modules.lrlc.config import WELL_ONLY_KEYS
from modules.lrlc.methods import METHOD_TEXT
from modules.pipeline import run_pipeline
from services.lrlc_service import LrlcService
from tests.golden.cases import FULL_MAPPING, fixture_frame
from tests.test_lrlc_elastic_pipeline import MAPPING, PARAMS, elastic_well
from tests.test_lrlc_pipeline import lrlc_p
from ui.main_window import MainWindow
from ui.widgets.lrlc_elastic_section import ELASTIC_ROWS
from ui.widgets.lrlc_methods_panel import grouped_keys

SPEC_IDS = re.compile(r"\b[LSP]\d\b|\bS4[a-z]\b|\bspec\b|section \d", re.IGNORECASE)


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


def two_zone_tops():
    return SimpleNamespace(
        formations=[SimpleNamespace(name="UPPER", top_depth=1000.0, bottom_depth=1105.0),
                    SimpleNamespace(name="LOWER", top_depth=1105.0, bottom_depth=1200.0)],
        get_formation_list=lambda: ["UPPER", "LOWER"])


@pytest.fixture(scope="module")
def elastic_run():
    """Results and summary of a two-zone well with DTS, elastic flag on (a gas sand in LOWER)."""
    frame = elastic_well()
    lrlc = lrlc_p(zones=("UPPER", "LOWER"), curves={"DTS": "DTS"}, screen_rt_max=0.3)
    lrlc["elastic"] = {"enabled": True}
    results, summary = run_pipeline(frame.copy(), dict(MAPPING), {**PARAMS, "lrlc": lrlc},
                                    formation_tops=two_zone_tops())
    return frame, results, summary


def plain_well(window):
    ds = WellDataset(key="WELL:A", display_name="A")
    ds.las_data = fixture_frame("sample_log_data")
    ds.curve_mapping = dict(FULL_MAPPING)
    window.model.project.add_well(ds, activate=True)
    return ds


def run_well(window, elastic_run, with_run=True):
    frame, results, summary = elastic_run
    ds = WellDataset(key="WELL:E", display_name="E")
    ds.las_data = frame.copy()
    ds.curve_mapping = {**ds.curve_mapping, **MAPPING}
    ds.formation_tops = two_zone_tops()
    if with_run:
        ds.results = results.copy()
        ds.summary = {**summary, "lrlc": dict(summary["lrlc"])}
        ds.calculated = True
    window.model.project.add_well(ds, activate=True)
    return ds


def enable(window, qtbot):
    with qtbot.waitSignal(window.lrlc_tab.stale_requested, timeout=500):
        window.lrlc_tab.enable_button.click()
    return window.lrlc_tab


def all_text(widget):
    return " ".join(label.text() for label in widget.findChildren(QLabel))


# ---- presence --------------------------------------------------------------------------------
def test_section_only_with_lrlc_on(window, qtbot):
    plain_well(window)
    tab = window.lrlc_tab
    assert tab.stack.currentIndex() == 0
    assert not tab.stack.widget(0).isAncestorOf(tab.elastic_section)
    enable(window, qtbot)
    assert tab.stack.currentIndex() == 1
    assert tab.stack.widget(1).isAncestorOf(tab.elastic_section)
    assert tab.elastic_section.isVisibleTo(tab.stack.widget(1))


def test_switch_is_off_and_never_pre_ticked_even_with_dts(window, qtbot, elastic_run):
    run_well(window, elastic_run, with_run=False)
    tab = enable(window, qtbot)
    assert tab.elastic_section.curve_names()["DTS"] == "DTS"
    assert tab.elastic_section.enable_check.isChecked() is False
    assert window.model.project.lrlc["elastic"]["enabled"] is False


def test_switch_writes_at_once_and_marks_stale(window, qtbot):
    plain_well(window)
    tab = enable(window, qtbot)
    with qtbot.waitSignal(tab.stale_requested, timeout=500):
        tab.elastic_section.enable_check.setChecked(True)
    assert window.model.project.lrlc["elastic"]["enabled"] is True
    assert window.model.dirty
    tab.elastic_section.enable_check.setChecked(False)
    assert window.model.project.lrlc["elastic"]["enabled"] is False
    tab.update_display()       # a redraw shows the stored state and writes nothing
    assert tab.elastic_section.enable_check.isChecked() is False


# ---- curves and the DTS warning -------------------------------------------------------------
def test_missing_dts_shows_one_warning_line_with_a_link_to_curves(window, qtbot, monkeypatch):
    plain_well(window)
    tab = enable(window, qtbot)
    sec = tab.elastic_section
    assert sec.warning_box.isVisibleTo(sec)
    assert "DTS" in sec.warning_label.text() and "Curves" in sec.warning_label.text()
    assert "DTS: not mapped" in sec.curves_label.text()
    assert "DT: DT" in sec.curves_label.text() and "RHOB: RHOB" in sec.curves_label.text()
    seen = []
    monkeypatch.setattr(tab, "show_panel", lambda name, section=None: seen.append((name, section)))
    sec.curves_link.click()
    assert seen == [("screening", "curves")]


def test_dts_assigned_in_curves_clears_the_warning(window, qtbot, elastic_run):
    run_well(window, elastic_run, with_run=False)
    tab = enable(window, qtbot)
    sec = tab.elastic_section
    assert not sec.warning_box.isVisibleTo(sec)
    assert "DTS: DTS" in sec.curves_label.text()
    ds = window.model.active_well
    LrlcService.set_curve(window.model, ds, "DTS", None)      # "Not used"
    tab.update_display()
    assert sec.warning_box.isVisibleTo(sec) and "DTS: not mapped" in sec.curves_label.text()


# ---- Set here / Inherit ----------------------------------------------------------------------
def test_set_here_and_inherit_write_through_the_service(window, qtbot):
    plain_well(window)
    tab = enable(window, qtbot)
    sec = tab.elastic_section
    row = sec.rows["el_ai_drop"]
    row["inputs"][0].setValue(0.08)
    with qtbot.waitSignal(tab.stale_requested, timeout=500):
        row["set"].click()
    assert window.model.project.lrlc["params"]["default"]["el_ai_drop"] == pytest.approx(0.08)
    assert "0.08" in row["source"].text() and "project" in row["source"].text()
    with qtbot.waitSignal(tab.stale_requested, timeout=500):
        row["inherit"].click()
    assert "el_ai_drop" not in window.model.project.lrlc["params"]["default"]
    assert row["inputs"][0].value() == pytest.approx(0.05)


def test_every_row_writes_a_valid_value(window, qtbot):
    plain_well(window)
    tab = enable(window, qtbot)
    for key, *_ in ELASTIC_ROWS:
        tab.elastic_section.rows[key]["set"].click()
        assert key in window.model.project.lrlc["params"]["default"], key
    assert window.model.project.lrlc["params"]["default"]["el_baseline_mode"] == "rolling"
    assert window.model.project.lrlc["params"]["default"]["el_shale_interval"] is None


def test_interval_rows_write_a_pair_or_nothing(window, qtbot):
    plain_well(window)
    tab = enable(window, qtbot)
    row = tab.elastic_section.rows["el_wet_interval"]
    row["inputs"][0].setValue(1100.0)
    row["inputs"][1].setValue(1050.0)                       # top below bottom: invalid
    row["set"].click()
    assert "el_wet_interval" not in window.model.project.lrlc["params"]["default"] or \
        window.model.project.lrlc["params"]["default"]["el_wet_interval"] is None
    assert "not valid" in tab.elastic_section.write_label.text()
    row["inputs"][1].setValue(1150.0)
    row["set"].click()
    assert window.model.project.lrlc["params"]["default"]["el_wet_interval"] == [1100.0, 1150.0]


def test_well_wide_key_at_a_zone_scope_goes_to_the_default_and_says_so(window, qtbot,
                                                                      elastic_run):
    ds = run_well(window, elastic_run)
    tab = enable(window, qtbot)
    sec = tab.elastic_section
    assert "el_min_wet_n" in WELL_ONLY_KEYS and "el_ai_drop" not in WELL_ONLY_KEYS
    tab.scope_buttons["well_zone"].setChecked(True)
    tab.scope_zone_combo.setCurrentIndex(tab.scope_zone_combo.findData("LOWER"))
    assert "well-wide" in sec.rows["el_min_wet_n"]["source"].text()
    assert "well-wide" not in sec.rows["el_ai_drop"]["source"].text()
    sec.rows["el_min_wet_n"]["inputs"][0].setValue(40)
    sec.rows["el_min_wet_n"]["set"].click()
    assert ds.lrlc["default"]["el_min_wet_n"] == 40
    assert "el_min_wet_n" not in (ds.lrlc["zones"].get("LOWER") or {})
    assert "well default" in sec.write_label.text() and "LOWER" in sec.write_label.text()
    assert "well default" in tab.status_label.text()
    sec.rows["el_ai_drop"]["inputs"][0].setValue(0.1)
    sec.rows["el_ai_drop"]["set"].click()
    assert ds.lrlc["zones"]["LOWER"]["el_ai_drop"] == pytest.approx(0.1)
    assert "zone LOWER" in sec.write_label.text()
    sec.rows["el_min_wet_n"]["inherit"].click()
    assert "el_min_wet_n" not in ds.lrlc["default"]
    assert "well default" in sec.write_label.text()


def test_rows_read_the_shipped_ranges_and_choices(window, qtbot):
    plain_well(window)
    tab = enable(window, qtbot)
    sec = tab.elastic_section
    combo = sec.rows["el_baseline_mode"]["inputs"][0]
    assert [combo.itemData(i) for i in range(combo.count())] == ["rolling", "zone", "window"]
    spin = sec.rows["el_vsh_shale"]["inputs"][0]
    assert (spin.minimum(), spin.maximum()) == (0.5, 1.0)


# ---- strips ----------------------------------------------------------------------------------
def test_strips_on_screening_are_compact(window, qtbot):
    plain_well(window)
    tab = enable(window, qtbot)
    for box in (tab.screening_box, tab.rt_cutoff_box, tab.elastic_section.method_box):
        assert box.compact is True
        assert not box.equation_view.isVisibleTo(box)
    assert tab.elastic_section.method_box._key == "elastic"
    assert tab.screening_box._key == "screening" and tab.rt_cutoff_box._key == "rt_cutoff"


def test_elastic_strip_opens_the_methods_panel_with_a_way_back(window, qtbot):
    plain_well(window)
    tab = enable(window, qtbot)
    tab.elastic_section.method_box.link.click()
    assert tab.panels.currentIndex() == 4
    assert tab.methods_panel.back_button.isVisibleTo(tab.methods_panel)
    tab.methods_panel.back_button.click()
    assert tab.panels.currentIndex() == 0


# ---- results and plots -----------------------------------------------------------------------
def test_plots_and_table_hidden_before_a_run(window, qtbot, elastic_run):
    run_well(window, elastic_run, with_run=False)
    tab = enable(window, qtbot)
    sec = tab.elastic_section
    assert not sec.plot_box.isVisibleTo(sec)
    assert not sec.zone_table.isVisibleTo(sec)
    assert sec.intro_note.isVisibleTo(sec)


def test_plots_and_table_after_a_run_with_the_flag(window, qtbot, elastic_run):
    _frame, _results, summary = elastic_run
    run_well(window, elastic_run)
    tab = enable(window, qtbot)
    sec = tab.elastic_section
    assert sec.plot_box.isVisibleTo(sec) and sec.zone_table.isVisibleTo(sec)
    assert not sec.intro_note.isVisibleTo(sec)
    assert len(sec.plot.figure.axes) == 2
    zones = [sec.zone_table.item(r, 0).text() for r in range(sec.zone_table.rowCount())]
    assert zones == ["UPPER", "LOWER"]
    flagged = {sec.zone_table.item(r, 0).text(): int(sec.zone_table.item(r, 2).text())
               for r in range(2)}
    assert flagged == {z["zone"]: z["n_flag"] for z in summary["lrlc"]["elastic"]["zones"]}
    assert flagged["LOWER"] > 0
    frame = sec.plot_frame(summary["lrlc"]["elastic"])
    assert frame["FLAG"].sum() == summary["lrlc"]["elastic"]["counts"]["flag"]
    assert frame["AI_REL"].notna().all()
    tab.select_zone("LOWER")
    only = sec.plot_frame(summary["lrlc"]["elastic"])
    assert set(only["ZONE"]) == {"LOWER"}
    assert "flagged" in sec.result_label.text()


def test_plots_stay_hidden_when_the_last_run_had_no_elastic_flag(window, qtbot, elastic_run):
    _frame, results, summary = elastic_run
    ds = run_well(window, elastic_run)
    lr = {k: v for k, v in summary["lrlc"].items() if k != "elastic"}
    ds.summary = {**summary, "lrlc": lr}
    ds.results = results.drop(columns=["AI", "VPVS", "ELASTIC_FLAG"])
    tab = enable(window, qtbot)
    assert not tab.elastic_section.plot_box.isVisibleTo(tab.elastic_section)


def test_theme_refresh_redraws(window, qtbot, elastic_run):
    run_well(window, elastic_run)
    tab = enable(window, qtbot)
    tab.refresh_theme()
    assert len(tab.elastic_section.plot.figure.axes) == 2


# ---- score maximum ---------------------------------------------------------------------------
def test_score_maximum_follows_score_max(window, qtbot, elastic_run):
    _frame, _results, summary = elastic_run
    assert summary["lrlc"]["screening"]["score_max"] == 7
    run_well(window, elastic_run)
    tab = enable(window, qtbot)
    assert tab.score_maximum() == 7
    assert "0 to 7" in tab.score_note.text() and tab.score_note.isVisibleTo(tab.stack.widget(1))
    ds = window.model.active_well
    screening = {k: v for k, v in ds.summary["lrlc"]["screening"].items() if k != "score_max"}
    ds.summary = {**ds.summary, "lrlc": {**ds.summary["lrlc"], "screening": screening}}
    tab.update_display()
    assert tab.score_maximum() == 6 and "0 to 6" in tab.score_note.text()


def test_methods_text_states_both_score_maxima():
    text = METHOD_TEXT["screening"].equation
    assert "0 to 6" in text and "0 to 7" in text


# ---- navigation and text ---------------------------------------------------------------------
def test_show_panel_and_issue_target_scroll_to_the_section(window, qtbot, elastic_run):
    run_well(window, elastic_run)
    enable(window, qtbot)
    window.resize(1400, 900)
    window.show()
    qtbot.waitExposed(window)
    tab = window.lrlc_tab
    window.show_lrlc("screening", "elastic")
    assert tab.panels.currentIndex() == 0
    bar = tab.page_scroll.verticalScrollBar()
    assert bar.value() > 0
    section_top = tab.elastic_section.mapTo(tab.page_scroll_widget, tab.elastic_section.rect().topLeft()).y()
    assert abs(bar.value() - section_top) <= 8 or bar.value() == bar.maximum()
    tab.show_panel("screening", "curves")
    window._on_goto_target("lrlc.screening.elastic")       # the target of the elastic issue codes
    assert tab.panels.currentIndex() == 0
    assert abs(bar.value() - section_top) <= 8 or bar.value() == bar.maximum()


def test_elastic_issue_codes_point_at_the_section():
    from modules.issue_codes import ISSUE_CODES
    targets = {c: t for c, (_s, t) in ISSUE_CODES.items() if c.startswith("LRLC_ELASTIC_")}
    assert targets and set(targets.values()) == {"lrlc.screening.elastic"}


def test_methods_panel_lists_elastic_under_screening():
    groups = dict(grouped_keys())
    assert "elastic" in groups["Screening"] and "elastic" not in groups.get("Other", [])


def test_method_text_is_generic_and_names_no_assignee():
    info = METHOD_TEXT["elastic"]
    text = " ".join([info.title, info.equation, info.assumptions, info.limits])
    assert "not a reproduction" in text and "design defaults" in text
    assert "304800" in info.equation and "Gassmann" in info.limits
    assert info.refs == ("ashfaq_us11709287",)
    assert not SPEC_IDS.search(text)
    assert "assignee" not in text.lower()


def test_section_text_has_no_internal_ids(window, qtbot, elastic_run):
    run_well(window, elastic_run)
    tab = enable(window, qtbot)
    text = all_text(tab.elastic_section)
    assert "design defaults" in text and "Advanced".upper() in text
    assert not SPEC_IDS.search(text)
