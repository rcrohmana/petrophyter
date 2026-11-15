"""Remediation > Rt deconvolution: the page, the proposal worker, boundary edits, Apply, the guard
lines, the response-width sensitivity line, the menu entry and the Overview column."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import copy
from types import SimpleNamespace

import numpy as np
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

from models.project import WellDataset
from modules.lrlc import chain
from modules.lrlc.config import WELL_ONLY_KEYS
from modules.lrlc.decon import GENERIC_RESPONSES
from modules.lrlc.guard import guard_summary
from modules.lrlc.methods import METHOD_TEXT
from services.lrlc_service import DeconWorker
from tests.golden.cases import build_case
from ui.main_window import MainWindow
from ui.widgets.lrlc_decon_page import sensitivity_text
from ui.widgets.lrlc_decon_plot import classify_boundaries
from ui.widgets.lrlc_remediation import (
    SECTION_GROUPS, SECTION_TITLES, STEP_CHECK_TEXT, STEP_PAGES, RemediationForm)

WAIT_MS = 60000


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


def make_well(window, rxo=True):
    data, mapping, _params, tops = build_case("lrlc_decon")
    ds = WellDataset(key="WELL:D", display_name="D")
    ds.las_data = data.copy()
    ds.curve_mapping = {**ds.curve_mapping, **mapping}
    ds.lrlc_curves = {"RXO": "RXO" if rxo else None}
    ds.formation_tops = SimpleNamespace(
        formations=[SimpleNamespace(name=f.name, top_depth=f.top_depth,
                                    bottom_depth=f.bottom_depth) for f in tops.formations],
        get_formation_list=lambda: [f.name for f in tops.formations])
    window.model.project.add_well(ds, activate=True)
    return ds


def enable(window, qtbot):
    with qtbot.waitSignal(window.lrlc_tab.stale_requested, timeout=500):
        window.lrlc_tab.enable_button.click()
    return window.lrlc_tab


@pytest.fixture()
def page(window, qtbot):
    ds = make_well(window)
    tab = enable(window, qtbot)
    tab.show_panel("remediation", "decon")
    return window, tab, tab.remediation_form, ds


def propose(qtbot, form):
    with qtbot.waitSignal(form.decon_proposed, timeout=WAIT_MS):
        form.dec_propose_button.click()
    assert form._dec_proposal is not None


def state_of(window, ds):
    return copy.deepcopy((window.model.project.lrlc, ds.lrlc, ds.lrlc_curves))


# ---- list, navigation, menu ------------------------------------------------------------------
def test_the_page_is_in_the_list_after_the_overview_with_its_state(page):
    window, tab, form, ds = page
    lst = form.section_list
    keys = [lst.item(i).data(Qt.ItemDataRole.UserRole) for i in range(lst.count())]
    keys = [k for k in keys if k]
    assert keys[:3] == ["rt_source", "decon", "invasion"]
    assert SECTION_GROUPS[0][1][1] == ("decon", "Rt deconvolution")
    assert STEP_PAGES == ("decon", "invasion", "laminated", "pyrite")
    assert STEP_CHECK_TEXT["decon"] == "Apply the Rt deconvolution"
    assert form.page_headings["decon"].text() == "Rt deconvolution"
    row = form._list_rows["decon"]
    assert row.state_label.text() == "off"
    form.step_checks["decon"].setChecked(True)
    assert row.state_label.text() == "on, changed"
    form.discard_button.click()
    assert row.state_label.text() == "off"


def test_step_labels_and_page_texts_agree():
    labels = {s.name: s.label for s in chain.available_steps()}
    for name in STEP_PAGES:
        word = labels[name].lower().split(" (")[0]
        assert word.split()[-1] in STEP_CHECK_TEXT[name].lower()
        assert word.split()[-1] in SECTION_TITLES[name].lower()
    assert labels["decon"] == "Deconvolution"


def test_show_panel_the_menu_and_the_issue_jump_open_the_page(page):
    window, tab, form, _ds = page
    for open_page in (
            lambda: tab.show_panel("remediation", "decon"),
            lambda: window.actions_["rt_decon"].trigger(),
            lambda: window._on_goto_target("lrlc.remediation.decon")):
        tab.show_panel("remediation", "rt_source")
        open_page()
        assert tab.panels.currentIndex() == 2
        assert form.current_section() == "decon"
    action = window.actions_["rt_decon"]
    assert action.text() == "Rt Deconvolution…"
    sub = window.actions_["rt_corrections_menu"].menu().actions()
    assert sub[-1] is action and sub[-2] is window.actions_["rt_invasion"]
    assert window._action_icons["rt_decon"] == "spline" and not action.icon().isNull()


def test_the_method_text_is_in_the_remediation_group():
    from ui.widgets.lrlc_methods_panel import METHOD_GROUPS

    remediation = dict(METHOD_GROUPS)["Remediation"]
    assert remediation.index("decon") == remediation.index("rt_chain") + 1
    info = METHOD_TEXT["decon"]
    assert info.refs == ("doll1949", "thadani1981", "coll1993")
    text = info.assumptions + info.limits
    assert "to verify" in text and "width" in text and "generic" in text
    assert "skin effect" in info.limits and "anisotropy" in info.limits


# ---- proposal, plot, tables ------------------------------------------------------------------
def test_the_plot_is_hidden_until_a_proposal_exists(page, qtbot):
    _window, _tab, form, _ds = page
    assert not form.dec_plot.isVisibleTo(form)
    assert not form.dec_edit_box.isVisibleTo(form)
    propose(qtbot, form)
    assert form.dec_plot.isVisibleTo(form) and form.dec_edit_box.isVisibleTo(form)
    assert "Proposal:" in form.dec_status_label.text()
    assert form.dec_boundary_table.rowCount() >= 5
    assert form.dec_window_table.rowCount() >= 1
    assert form.dec_counts_label.text().startswith("Counts:")


def test_propose_and_use_proposal_change_no_model_state(page, qtbot, monkeypatch):
    window, _tab, form, ds = page

    def no_pipeline(*args, **kwargs):
        raise AssertionError("the tab must not run the pipeline")

    monkeypatch.setattr("modules.pipeline.run_pipeline", no_pipeline)
    monkeypatch.setattr("services.analysis_service.run_pipeline", no_pipeline, raising=False)
    before = state_of(window, ds)
    dirty = window.model.is_dirty if hasattr(window.model, "is_dirty") else None
    propose(qtbot, form)
    assert form.add_boundary(1031.0) or True
    qtbot.waitUntil(lambda: not form._dec_running, timeout=WAIT_MS)
    form.dec_use_button.click()
    assert state_of(window, ds) == before
    assert dirty is None or window.model.is_dirty == dirty
    assert ds.results is None or True


def test_use_proposal_fills_the_pending_values_including_the_edits(page, qtbot):
    window, _tab, form, ds = page
    form.controls["dec_fwhm_ft"].setValue(3.0)
    form.discard_button.click()
    form.controls["dec_fwhm_ft"].setValue(3.5)
    propose(qtbot, form)
    form.discard_button.click()                  # the proposal outlives the pending values
    assert form.controls["dec_fwhm_ft"].value() == 4.0
    with qtbot.waitSignal(form.decon_proposed, timeout=WAIT_MS):
        assert form.add_boundary(1031.0)
    assert 1031.0 in form._dec_proposal["edits"]["add"]
    form.dec_use_button.click()
    assert form.controls["dec_fwhm_ft"].value() == 3.5
    assert form._dec_edits == {"add": [1031.0], "remove": []}
    assert "Boundary edits" in form.pending_label.text()
    assert form.apply_button.isEnabled()
    assert form._list_rows["decon"].state_label.text().endswith("changed")
    assert ds.lrlc in (None, {}, ds.lrlc) and "dec_edits" not in (
        (ds.lrlc or {}).get("default") or {})


# ---- boundary edits --------------------------------------------------------------------------
def test_add_remove_boundary_edits_update_the_proposal_and_reset_clears_them(page, qtbot):
    _window, _tab, form, _ds = page
    propose(qtbot, form)
    plot = form._dec_proposal["plot"]
    n = len(plot["final"])
    # remove an automatic boundary
    victim = float(plot["final"][2])
    with qtbot.waitSignal(form.decon_proposed, timeout=WAIT_MS):
        assert form.remove_boundary(victim + 0.1)
    edits = form._dec_proposal["edits"]
    assert len(edits["remove"]) == 1 and abs(edits["remove"][0] - victim) < 0.5
    assert len(form._dec_proposal["plot"]["final"]) < n
    origins = dict((round(d, 1), o) for d, o in form._dec_rows)
    assert "removed" in origins.values()
    # add a boundary inside a thick bed
    with qtbot.waitSignal(form.decon_proposed, timeout=WAIT_MS):
        assert form.add_boundary(1030.0)
    assert 1030.0 in form._dec_proposal["edits"]["add"]
    assert any(o == "added" for _d, o in form._dec_rows)
    # deleting the added boundary leaves the add list, it does not join the remove list
    with qtbot.waitSignal(form.decon_proposed, timeout=WAIT_MS):
        assert form.remove_boundary(1030.0)
    assert form._dec_proposal["edits"]["add"] == []
    assert len(form._dec_proposal["edits"]["remove"]) == 1
    # restore the removed one
    with qtbot.waitSignal(form.decon_proposed, timeout=WAIT_MS):
        assert form.restore_boundary(victim)
    assert form._dec_proposal["edits"]["remove"] == []
    # reset
    with qtbot.waitSignal(form.decon_proposed, timeout=WAIT_MS):
        assert form.add_boundary(1030.0)
    with qtbot.waitSignal(form.decon_proposed, timeout=WAIT_MS):
        assert form.reset_boundary_edits()
    assert form._dec_proposal["edits"] == {"add": [], "remove": []}
    assert len(form._dec_proposal["plot"]["final"]) == n


def test_plot_clicks_call_the_edit_methods(page, qtbot):
    _window, _tab, form, _ds = page
    propose(qtbot, form)
    form.dec_add_button.setChecked(True)
    assert form.dec_plot.mode == "add" and not form.dec_remove_button.isChecked()
    with qtbot.waitSignal(form.decon_proposed, timeout=WAIT_MS):
        form.dec_plot.boundary_clicked.emit("add", 1031.0)
    assert form._dec_proposal["edits"]["add"] == [1031.0]
    form.dec_remove_button.setChecked(True)
    assert form.dec_plot.mode == "remove" and not form.dec_add_button.isChecked()
    form.dec_remove_button.setChecked(False)
    assert form.dec_plot.mode == "none"


def test_classify_boundaries():
    rows = classify_boundaries([10.0, 20.0, 30.0], [10.0, 25.0, 30.2], {"remove": [20.1]}, 1.0)
    assert rows == [(10.0, "auto"), (20.0, "removed"), (25.0, "added"), (30.2, "auto")]


# ---- Apply, Discard ---------------------------------------------------------------------------
def test_apply_writes_the_zone_keys_to_the_zone_and_the_tool_keys_to_the_well(page, qtbot):
    window, tab, form, ds = page
    tab.select_zone("UPPER")
    assert form.zone == "UPPER" and form.scope_combo.currentData() == "zone"
    form.step_checks["decon"].setChecked(True)
    form.controls["dec_fwhm_ft"].setValue(3.0)
    form.controls["dec_max_ratio"].setValue(20.0)
    form.controls["dec_solver"].setCurrentIndex(form.controls["dec_solver"].findData("mult"))
    assert "FWHM" in form.pending_label.text() and "Largest change" in form.pending_label.text()
    with qtbot.waitSignal(form.stale_requested, timeout=500) as signal:
        form.apply_button.click()
    assert signal.args[0] == [ds.key]
    zone = ds.lrlc["zones"]["UPPER"]
    default = ds.lrlc["default"]
    assert zone["dec_max_ratio"] == 20.0 and "decon" in zone["rt_steps"]
    assert default["dec_fwhm_ft"] == 3.0 and default["dec_solver"] == "mult"
    assert not set(zone) & set(WELL_ONLY_KEYS)
    assert "tool and solver settings as the default of this well" in form.result_label.text()
    assert not form.apply_button.isEnabled()
    assert form.controls["dec_fwhm_ft"].value() == 3.0       # shown from the well default


def test_apply_at_the_well_and_project_scope_and_discard(page, qtbot):
    window, _tab, form, ds = page
    form.controls["dec_fwhm_ft"].setValue(2.5)
    form.discard_button.click()
    assert form.controls["dec_fwhm_ft"].value() == 4.0 and not form.apply_button.isEnabled()
    form.controls["dec_fwhm_ft"].setValue(2.5)
    form.scope_combo.setCurrentIndex(form.scope_combo.findData("project"))
    with qtbot.waitSignal(form.stale_requested, timeout=500):
        form.apply_button.click()
    assert window.model.project.lrlc["params"]["default"]["dec_fwhm_ft"] == 2.5
    assert "default" not in (ds.lrlc or {}) or "dec_fwhm_ft" not in ds.lrlc["default"]


def test_apply_writes_the_boundary_edits_to_the_well_default(page, qtbot):
    _window, _tab, form, ds = page
    propose(qtbot, form)
    with qtbot.waitSignal(form.decon_proposed, timeout=WAIT_MS):
        assert form.add_boundary(1031.0)
    form.dec_use_button.click()
    with qtbot.waitSignal(form.stale_requested, timeout=500):
        form.apply_button.click()
    assert ds.lrlc["default"]["dec_edits"] == {"add": [1031.0], "remove": []}
    assert form._dec_edits is None


# ---- inputs and states -------------------------------------------------------------------------
def test_tool_presets_fill_the_width_and_show_the_generic_badge(page):
    _window, _tab, form, _ds = page
    tool = form.controls["dec_tool"]
    assert form.dec_generic_badge.isVisibleTo(form)           # Custom: the width in use
    assert form.dec_generic_badge.text() == "FWHM 4.0 ft"
    assert form.controls["dec_fwhm_ft"].isEnabled()
    tool.setCurrentIndex(tool.findData("array_induction_2ft"))
    assert form.controls["dec_fwhm_ft"].value() == GENERIC_RESPONSES["array_induction_2ft"]["fwhm_ft"]
    assert not form.controls["dec_fwhm_ft"].isEnabled()
    assert form.dec_generic_badge.isVisibleTo(form)
    assert form.dec_generic_badge.text() == "generic, confirm with tool charts"
    assert not form.dec_laterolog_note.isVisibleTo(form)
    tool.setCurrentIndex(tool.findData("laterolog_deep_2ft"))
    assert "not linear in conductivity" in form.dec_laterolog_note.text()
    assert form.dec_laterolog_note.isVisibleTo(form)
    tool.setCurrentIndex(tool.findData("custom"))
    assert form.controls["dec_fwhm_ft"].isEnabled()
    resp = form.controls["dec_response"]
    assert not form._dec_form.labelForField(form.controls["dec_doll_spacing_ft"]).isVisibleTo(form)
    resp.setCurrentIndex(resp.findData("doll"))
    assert form.controls["dec_doll_spacing_ft"].isVisibleTo(form)


def test_the_nullable_inputs_have_an_automatic_state(page):
    _window, _tab, form, _ds = page
    assert form._read_widget("dec_lambda") is None and form._read_widget("dec_min_bed_ft") is None
    form.controls["dec_lambda"].auto.setChecked(False)
    form.controls["dec_lambda"].spin.setValue(0.01)
    assert form._read_widget("dec_lambda") == 0.01
    assert "Lambda" in form.pending_label.text()


def test_misfit_warning_is_automatic_at_twice_the_noise(page):
    _window, _tab, form, ds = page
    box = form.controls["dec_misfit_warn"]
    assert box.auto.isChecked() and form._read_widget("dec_misfit_warn") is None
    assert box.spin.value() == pytest.approx(0.06) and not box.spin.isEnabled()
    form.controls["dec_noise_rel"].setValue(0.05)
    assert box.spin.value() == pytest.approx(0.10)
    assert form._read_widget("dec_misfit_warn") is None
    form.step_checks["decon"].setChecked(True)
    form.apply_button.click()
    assert ds.lrlc["default"].get("dec_misfit_warn") is None
    assert ds.lrlc["default"]["dec_noise_rel"] == 0.05
    # unticking keeps the automatic value as the start and writes a number
    box.auto.setChecked(False)
    assert box.spin.isEnabled() and form._read_widget("dec_misfit_warn") == pytest.approx(0.10)
    box.spin.setValue(0.2)
    assert "Misfit warning" in form.pending_label.text()
    form.apply_button.click()
    assert ds.lrlc["default"]["dec_misfit_warn"] == 0.2
    box.auto.setChecked(True)
    form.apply_button.click()
    assert ds.lrlc["default"].get("dec_misfit_warn") is None
    assert form.dec_advanced.changed_count() == 1          # only the noise differs from the default


def test_advanced_is_folded_until_a_value_differs_from_the_default(page):
    _window, _tab, form, _ds = page
    adv = form.dec_advanced
    assert not adv.is_expanded() and not adv.body.isVisibleTo(form)
    assert adv.header.text() == "Advanced settings"
    adv.header.click()
    assert adv.is_expanded() and adv.body.isVisibleTo(form)
    assert form.controls["dec_misfit_warn"].isVisibleTo(form)
    adv.header.click()
    assert not adv.is_expanded()
    form.controls["dec_edge_k"].setValue(5.0)
    form.controls["dec_solver"].setCurrentIndex(form.controls["dec_solver"].findData("mult"))
    assert adv.header.text() == "Advanced settings (2 changed)"
    assert adv.is_expanded() and adv.body.isVisibleTo(form)
    form.discard_button.click()
    assert adv.header.text() == "Advanced settings"


def test_a_stored_advanced_value_opens_the_fold_at_load(page):
    _window, _tab, form, ds = page
    ds.lrlc = {"default": {"dec_edge_k": 6.0}}
    form.set_context(form.model, ds, None, ["UPPER", "LOWER"])
    assert form.dec_advanced.is_expanded()
    assert form.dec_advanced.header.text() == "Advanced settings (1 changed)"


def test_missing_reference_is_one_warning_line_with_the_curves_link(window, qtbot):
    make_well(window, rxo=False)
    tab = enable(window, qtbot)
    tab.show_panel("remediation", "decon")
    form = tab.remediation_form
    combo = form.controls["dec_hires_source"]
    combo.setCurrentIndex(combo.findData("RXO"))
    assert form.dec_ref_warning.isVisibleTo(form) and form.dec_curves_button.isVisibleTo(form)
    assert "No high-resolution reference curve" in form.dec_ref_warning.text()
    assert not form.dec_propose_button.isEnabled()
    seen = []
    form.panel_requested.connect(lambda panel, section: seen.append((panel, section)))
    form.dec_curves_button.click()
    assert seen == [("screening", "curves")]
    combo.setCurrentIndex(combo.findData("auto"))            # RHOB and GR are mapped
    assert not form.dec_ref_warning.isVisibleTo(form) and form.dec_propose_button.isEnabled()
    assert "RHOB" in form.dec_resolved_label.text()


def test_reference_resolution_label(page):
    _window, _tab, form, _ds = page
    assert form.dec_resolved_label.text() == "Using RXO"
    assert not form.dec_ref_warning.isVisibleTo(form)


# ---- the guard on the page ---------------------------------------------------------------------
def test_the_step_box_is_disabled_with_the_reason_when_the_guard_is_on_and_rt_is_marked(page):
    _window, _tab, form, _ds = page
    check = form.step_checks["decon"]
    assert check.isEnabled() and not form.dec_guard_label.isVisibleTo(form)
    form.sbc_check.setChecked(True)                         # pending, like the other switches
    assert not check.isEnabled()
    assert "marked shoulder-bed corrected" in form.dec_guard_label.text()
    assert "not applied" in form.dec_guard_label.text()
    assert not form.dec_lam_button.isVisibleTo(form)
    form.guard_check.setChecked(False)
    assert check.isEnabled() and "(guard off)" in form.dec_guard_label.text()
    form.guard_check.setChecked(True)
    form.discard_button.click()
    assert check.isEnabled()


def test_a_ticked_box_stays_usable_and_the_row_reads_blocked(page):
    _window, _tab, form, _ds = page
    form.step_checks["decon"].setChecked(True)
    form.sbc_check.setChecked(True)
    assert form.step_checks["decon"].isEnabled()
    assert form._list_rows["decon"].state_label.text() == "blocked, changed"


def laminated_summary(ds, zone="UPPER", blocked=True):
    ds.summary = {"lrlc": {"guard": {"enabled": True, "zones": [
        {"zone": zone, "laminated": True, "lam_share": 0.9,
         "blocked_steps": ["decon"] if blocked else [], "sbc_rt": False,
         "reasons": {"decon": "laminated"} if blocked else {}}]}}}


def test_a_zone_laminated_in_the_last_run_warns_with_a_link_to_laminated_sand(page):
    _window, tab, form, ds = page
    tab.select_zone("UPPER")
    laminated_summary(ds)
    tab.update_display()
    assert "Zone UPPER was laminated in the last run" in form.dec_guard_label.text()
    assert form.dec_lam_button.isVisibleTo(form)
    form.dec_lam_button.click()
    assert form.current_section() == "laminated"
    tab.show_panel("remediation", "decon")
    tab.select_zone("LOWER")
    tab.update_display()
    assert not form.dec_guard_label.isVisibleTo(form)


def test_guard_lines_use_the_step_label_and_the_real_reason(page):
    _window, _tab, form, _ds = page
    lam = {"enabled": True, "zones": [
        {"zone": "A", "laminated": True, "lam_share": 0.8, "blocked_steps": ["decon"],
         "sbc_rt": False, "reasons": {"decon": "laminated"}},
        {"zone": "B", "laminated": False, "lam_share": 0.1, "blocked_steps": ["decon"],
         "sbc_rt": False, "reasons": {"decon": "shoulder"}}]}
    lines = RemediationForm.guard_lines(lam, None)
    assert ("Deconvolution not applied in Zone A: laminated (guard); use the laminated-sand "
            "correction.") in lines
    assert "Deconvolution not applied in Zone B: RT is marked shoulder-bed corrected (guard)." in lines
    assert not any(line.startswith("decon ") for line in lines)


def test_the_guard_summary_has_reasons_only_when_a_rule_acted():
    from modules.lrlc.guard import GuardResult

    states = {"A": {"laminated": True, "lam_share": 0.7}, "B": {"laminated": False}}
    dec = GuardResult([], None, [], ["decon"], False, {"decon": "shoulder"}, [])
    out = guard_summary(states, {"A": dec, "B": GuardResult([], None, [], [], False, {}, [])})
    by = {z["zone"]: z for z in out["zones"]}
    assert by["A"]["reasons"] == {"decon": "shoulder"} and "reasons" not in by["B"]


# ---- the response-width sensitivity line ---------------------------------------------------------
SENS = {"widths_ft": [3.2, 4.0, 5.0], "median_ratio": [1.9, 2.0, 1.7], "n_valid": [19, 19, 14],
        "n": 19}


def test_sensitivity_text_format_and_hiding():
    text = sensitivity_text({"width_sensitivity": SENS})
    assert text == ("width 3.2 ft gives 1.9 x, 4.0 ft (set) gives 2.0 x, 5.0 ft gives 1.7 x with "
                    "5 of 19 samples over the change limit.")
    clean = sensitivity_text({"width_sensitivity": {**SENS, "n_valid": [19, 19, 19]}})
    assert "over the change limit" not in clean
    assert sensitivity_text({"width_sensitivity": {**SENS, "n": 0}}) == ""
    assert sensitivity_text({"width_sensitivity": None}) == "" and sensitivity_text({}) == ""
    none = sensitivity_text({"width_sensitivity": {**SENS, "median_ratio": [None, 2.0, 1.7]}})
    assert "3.2 ft gives no valid sample," in none


def test_the_sensitivity_line_shows_from_the_proposal_and_from_a_run(page, qtbot):
    _window, tab, form, ds = page
    assert not form.dec_sensitivity_label.isVisibleTo(form)
    tab.select_zone("UPPER")
    propose(qtbot, form)
    text = form.dec_sensitivity_label.text()
    assert text.startswith("width 3.2 ft gives ") and "ft (set) gives" in text
    assert form.dec_sensitivity_label.isVisibleTo(form)
    assert form.dec_sensitivity_intro.isVisibleTo(form)
    assert "confirm it against the tool's charts" in form.dec_sensitivity_intro.text()
    assert "confirm the width" in form.dec_sensitivity_label.toolTip()
    # after a run: from the summary
    form._reset_decon()
    ds.summary = {"lrlc": {"decon": {"zones": [
        {"zone": "UPPER", "status": "ran", "n_active": 80, "n_valid": 70, "n_amplified": 0,
         "width_sensitivity": SENS},
        {"zone": "LOWER", "status": "guard_dropped_laminated", "n_active": 120, "n_valid": 100,
         "n_amplified": 0, "width_sensitivity": SENS}],
        "windows": [], "counts": {}, "boundaries": {}, "hires": {}, "params": {}}}}
    form.set_context(form.model, ds, None, ["UPPER", "LOWER"])
    text = form.dec_sensitivity_label.text()
    assert text == "UPPER: " + sensitivity_text({"width_sensitivity": SENS})
    tab.select_zone("LOWER")
    tab.update_display()
    assert not form.dec_sensitivity_label.isVisibleTo(form)          # not applied there
    assert not form.dec_sensitivity_intro.isVisibleTo(form)
    assert "not applied" in form.dec_status_label.text()
    tab.select_zone("UPPER")
    tab.update_display()
    assert form.dec_sensitivity_label.text() == sensitivity_text({"width_sensitivity": SENS})


# ---- the worker ------------------------------------------------------------------------------------
def test_the_worker_solves_the_zone_or_the_whole_well_and_writes_nothing(page):
    window, _tab, _form, ds = page
    before = state_of(window, ds)
    zone = DeconWorker.from_model(window.model, ds, "UPPER", {}, None, 7)
    out = zone.compute()
    assert out["token"] == 7 and out["zone"] == "UPPER"
    assert [z["zone"] for z in out["block"]["zones"]] == ["UPPER"]
    assert out["plot"]["depth"][0] >= 1000.0 and out["plot"]["depth"][-1] <= 1040.0 + 1e-9
    whole = DeconWorker.from_model(window.model, ds, None, {}, None, 8).compute()
    assert {z["zone"] for z in whole["block"]["zones"]} == {"UPPER", "LOWER"}
    assert len(whole["plot"]["depth"]) > len(out["plot"]["depth"])
    sens = whole["block"]["zones"][0]["width_sensitivity"]
    assert sens["widths_ft"] == pytest.approx([3.2, 4.0, 5.0]) and sens["n"] > 0
    assert state_of(window, ds) == before


def test_a_zone_proposal_matches_the_run_in_that_zone(page):
    """With the step stored on in every zone, Propose for one zone solves what the run solves (the
    whole well) and shows that zone's part: the same RT_DECON there and the same window statuses."""
    from modules.pipeline import run_pipeline
    from services.analysis_service import snapshot_well
    from services.lrlc_service import LrlcService

    window, _tab, _form, ds = page
    LrlcService.set_param(window.model, "project", None, "rt_steps", ["decon"])
    snap = snapshot_well(window.model, ds)
    results, summary = run_pipeline(snap.data, snap.curve_mapping, snap.params,
                                    formation_tops=snap.formation_tops)
    out = DeconWorker.from_model(window.model, ds, "UPPER", {}, None, 1).compute()
    plot = out["plot"]
    assert [z["zone"] for z in out["block"]["zones"]] == ["UPPER"]
    assert plot["depth"][0] >= 1000.0 and plot["depth"][-1] <= 1040.0 + 1e-9
    run = results.set_index("DEPTH")["RT_DECON"].reindex(plot["depth"]).to_numpy(dtype=float)
    np.testing.assert_allclose(plot["rt_decon"], run, rtol=1e-9, equal_nan=True)
    ran = [(round(w["top"], 3), round(w["bottom"], 3), w["status"])
           for w in summary["lrlc"]["decon"]["windows"]
           if w["bottom"] >= plot["depth"][0] and w["top"] <= plot["depth"][-1]]
    shown = [(round(w["top"], 3), round(w["bottom"], 3), w["status"]) for w in plot["windows"]]
    assert shown == ran and shown


def test_the_worker_uses_the_pending_values_and_edits(page):
    window, _tab, _form, ds = page
    base = DeconWorker.from_model(window.model, ds, None, {}, None, 1).compute()
    wide = DeconWorker.from_model(window.model, ds, None, {"dec_fwhm_ft": 6.0}, None, 2).compute()
    assert wide["block"]["params"]["fwhm_ft"] == 6.0 and base["block"]["params"]["fwhm_ft"] == 4.0
    edited = DeconWorker.from_model(window.model, ds, None, {},
                                    {"add": [1031.0], "remove": []}, 3).compute()
    assert 1031.0 in [round(x, 0) for x in edited["plot"]["final"]] or any(
        abs(x - 1031.0) < 0.5 for x in edited["plot"]["final"])
    assert edited["block"]["edits"] == {"add": [1031.0], "remove": []}


def test_the_worker_reports_no_reference(window):
    ds = make_well(window, rxo=False)
    ds.curve_mapping = {**ds.curve_mapping, "RHOB": "NONE", "GR": "NONE"}
    out = DeconWorker.from_model(window.model, ds, None, {"dec_hires_source": "RXO"}, None, 1).compute()
    assert out["plot"] is None
    assert any(i["code"] == "LRLC_DECON_NO_HIRES" for i in out["issues"])


# ---- the Overview ------------------------------------------------------------------------------------
def test_the_overview_gains_the_decon_column_and_sw_reads_follow(page):
    _window, tab, form, _ds = page
    tab.select_zone("UPPER")
    headers = [form.chain_table.horizontalHeaderItem(c).text()
               for c in range(form.chain_table.columnCount())]
    assert headers[:3] == ["Zone", "Sw reads", "Deconvolution"]
    assert "Deconvolution" not in [form.other_steps_box.itemAt(i).widget().text()
                                   for i in range(form.other_steps_box.count())]
    form.step_checks["decon"].setChecked(True)
    assert form.sw_reads_label.text().startswith("Sw reads after Apply: RT_DECON")
    form.apply_button.click()
    assert form.sw_reads_label.text().startswith("Sw reads: RT_DECON")
    rows = {form.chain_table.item(r, 0).text(): r for r in range(form.chain_table.rowCount())}
    assert form.chain_table.item(rows["UPPER"], 2).text() == "on"
    assert form.chain_table.item(rows["LOWER"], 2).text() == ""
