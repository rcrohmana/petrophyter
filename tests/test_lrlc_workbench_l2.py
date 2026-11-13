"""LRLC Workbench panels for laminated sands, pyrite, Qv and the before / after comparison."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pathlib
import re
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from PyQt6.QtWidgets import QMessageBox

from models.project import WellDataset
from modules.lrlc.config import resolve_lrlc
from modules.pipeline import run_pipeline
from services.lrlc_service import LrlcService
from tests.golden.cases import build_case
from tests.test_lrlc_pipeline import lrlc_p
from ui.main_window import MainWindow
from ui.widgets.lrlc_ts_plot import ISO_VLAM, mixing_curve, triangle_lines


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


@pytest.fixture(scope="module")
def run_result():
    """A laminated and pyritic two-zone well, run with the corrections in the upper zone."""
    data, mapping, params, tops = build_case("lrlc_screening")
    params = dict(params)
    params.pop("lrlc")
    data = data.copy()
    rng = np.random.default_rng(1)
    data["PEF"] = 2.2 + 1.2 * rng.random(len(data))
    lrlc = lrlc_p(zone_steps={"UPPER": ["laminated", "pyrite"], "LOWER": []},
                  curves={"PEF": "PEF"}, phi_max=0.30, phi_sh=0.08, pyr_method="rhob_pef",
                  pyr_f=0.4, pyr_rpy=0.1)
    lrlc["thomas_stieber"] = {"enabled": True}
    lrlc["pyrite"] = {"enabled": True, "u_fluid": 0.36}
    results, summary = run_pipeline(data, dict(mapping), {**params, "lrlc": lrlc},
                                    formation_tops=tops)
    return data, mapping, tops, results, summary


def make_well(window, run_result, with_run=True, endpoints=True):
    data, mapping, tops, results, summary = run_result
    ds = WellDataset(key="WELL:A", display_name="A")
    ds.las_data = data.copy()
    ds.curve_mapping = {**ds.curve_mapping, **mapping}
    ds.formation_tops = SimpleNamespace(
        formations=[SimpleNamespace(name=f.name, top_depth=f.top_depth,
                                    bottom_depth=f.bottom_depth) for f in tops.formations],
        get_formation_list=lambda: [f.name for f in tops.formations])
    if with_run:
        ds.results = results.copy()
        ds.summary = {**summary, "lrlc": {k: v for k, v in summary["lrlc"].items()}}
        ds.calculated = True
    window.model.project.add_well(ds, activate=True)
    if endpoints:
        assert LrlcService.apply_endpoints(window.model, "project", None, 0.30, 0.08)
    return ds


def enable(window, qtbot):
    with qtbot.waitSignal(window.lrlc_tab.stale_requested, timeout=500):
        window.lrlc_tab.enable_button.click()
    return window.lrlc_tab


def labels(widget):
    from PyQt6.QtWidgets import QLabel
    return " ".join(label.text() for label in widget.findChildren(QLabel))


def column(table, c):
    return [table.item(r, c).text() for r in range(table.rowCount())]


# ---- plot geometry ------------------------------------------------------------------------
def test_triangle_lines_pass_through_the_vertices():
    lines = triangle_lines(0.30, 0.08)
    assert lines["laminar"][1].tolist() == [0.30, 0.08]
    assert lines["dispersed"][0].tolist() == [0.0, 0.30]
    assert lines["dispersed"][1][1] == pytest.approx(0.30 * 0.08)
    assert lines["apex_shale"][1].tolist() == pytest.approx([0.30 * 0.08, 0.08])
    for v in ISO_VLAM:                       # iso-Vlam lines start on the laminar line
        x, y = lines[f"iso_{v:g}"]
        assert y[0] == pytest.approx(0.30 + x[0] * (0.08 - 0.30))
    assert ISO_VLAM == (0.2, 0.4, 0.6, 0.8)


def test_mixing_curve_starts_at_the_matrix_and_ends_at_pyrite():
    rho, pef, marks = mixing_curve((2.65, 1.81), (4.99, 16.97))
    assert (rho[0], pef[0]) == pytest.approx((2.65, 1.81))
    assert (rho[-1], pef[-1]) == pytest.approx((4.99, 16.97))
    assert set(marks) == {0.02, 0.05, 0.10} and marks[0.05][1] > marks[0.02][1] > 1.81


# ---- diagnosis ----------------------------------------------------------------------------
def test_zone_table_lists_causes_and_follows_the_zone(window, qtbot, run_result):
    make_well(window, run_result)
    tab = enable(window, qtbot)
    panel = tab.zones_panel
    assert column(panel.zone_table, 0) == ["UPPER", "LOWER"]
    assert "Thin beds / laminations" in panel.zone_table.item(0, 3).text()
    assert panel.zone_table.item(0, 5).text() == "Yes"
    tab.select_zone("LOWER")                                  # preselects the table row
    assert panel.selected_row_zone() == "LOWER"
    assert "Evidence: LOWER" in panel.detail_group.title()
    assert panel.criteria_table.rowCount() >= 3
    assert "Laminar share of the shale volume" in column(panel.criteria_table, 2)
    panel.zone_table.selectRow(0)                             # a click in the table
    assert tab.selected_zone() == "UPPER"
    assert not re.search(r"\b[LP]\d\b|spec", labels(panel))


def test_zone_table_without_a_run(window, qtbot, run_result):
    make_well(window, run_result, with_run=False)
    tab = enable(window, qtbot)
    assert tab.zones_panel.zone_table.rowCount() == 0
    assert "Run the analysis first" in tab.zones_panel.status_label.text()
    assert tab.validation_panel.status_label.text().startswith("Run the analysis first")


def test_show_panel_sections(window, qtbot, run_result):
    make_well(window, run_result)
    tab = enable(window, qtbot)
    tab.show_panel("diagnosis", "thomas_stieber")
    assert tab.panels.currentIndex() == 1 and tab.diagnosis_tabs.currentIndex() == 1
    tab.show_panel("diagnosis", "buckles")
    assert tab.diagnosis_tabs.currentIndex() == 3
    window.show()
    window.resize(1400, 900)
    window.show_lrlc("remediation", "pyrite")
    form = tab.remediation_form
    assert form.current_section() == "pyrite"
    assert form.section_stack.currentWidget().widget() is form.scroll_target("pyrite")
    window.show_lrlc("remediation", "laminated")
    assert form.current_section() == "laminated"
    window.show_lrlc("diagnosis", zone="UPPER")
    assert tab.panels.currentIndex() == 1
    assert tab.zones_panel.selected_row_zone() == "UPPER"


def test_thomas_stieber_page(window, qtbot, run_result):
    ds = make_well(window, run_result)
    tab = enable(window, qtbot)
    ts = tab.ts_panel
    tab.select_zone("UPPER")
    assert ts.endpoint_table.rowCount() >= 1
    assert ts.class_table.rowCount() == 2
    row = [ts.class_table.item(0, c).text() for c in range(ts.class_table.columnCount())]
    assert row[:7] == ["UPPER", "14", "4", "9", "30", "0", "23"]
    assert row[9] == "32"                                     # structural + clay + below the line
    assert ts.plot.n_drawn > 0
    assert "last run" in ts.plot_note.text()
    # without any applied end-points the preview falls back to the proposal or none
    ds.results = ds.results.drop(columns=["TS_CLASS"])
    ts.set_context(window.model, ds, "UPPER")
    assert "Preview" in ts.plot_note.text() or "end-points" in ts.plot_note.text()
    ds.results = None
    ts.set_context(window.model, ds, "UPPER")
    assert "Run the analysis" in ts.status_label.text()


def test_ts_preview_uses_the_proposal_when_nothing_is_applied(window, qtbot, run_result):
    ds = make_well(window, run_result, with_run=False, endpoints=False)
    rng = np.random.default_rng(3)
    n = 1200
    vsh = rng.random(n)
    ds.results = pd.DataFrame({
        "DEPTH": np.linspace(1000.0, 2000.0, n), "ZONE": "UPPER", "VSH": vsh,
        "PHIT": 0.30 + vsh * (0.08 - 0.30) + rng.normal(0, 0.005, n)})
    tab = enable(window, qtbot)
    ts = tab.ts_panel
    prop = ts._proposals["UPPER"]
    assert prop.ok and prop.phi_max == pytest.approx(0.30, abs=0.02)
    tab.select_zone("UPPER")
    assert "proposed end-points (not applied)" in ts.plot_note.text()
    assert ts.endpoint_table.item(0, 7).text().startswith("Not applied")
    assert ts.prepare_button.isEnabled()
    ts.prepare_button.click()
    form = tab.remediation_form
    assert form.controls["phi_max"].value() == pytest.approx(prop.phi_max, abs=1e-3)
    assert form.controls["phi_sh"].value() == pytest.approx(prop.phi_sh, abs=1e-3)
    assert {"phi_max", "phi_sh"} <= form._dirty and tab.panels.currentIndex() == 2
    assert not window.model.project.lrlc["params"]["default"]


# ---- remediation: Rt source ---------------------------------------------------------------
def test_rt_source_lines_and_marked_rt(window, qtbot, run_result):
    ds = make_well(window, run_result)
    tab = enable(window, qtbot)
    form = tab.remediation_form
    assert form.sw_reads_label.text().startswith("Sw reads: RT")
    assert form.chain_note.text() == "Rsh and Rw estimators stay on the measured RT."
    LrlcService.set_param(window.model, "well", "UPPER", "rt_steps", ["laminated", "pyrite"], ds)
    tab.select_zone("UPPER")
    assert form.sw_reads_label.text().startswith("Sw reads: RT_PYR <- RT_SAND <- RT")
    assert not form.sbc_check.isChecked()
    form.sbc_check.setChecked(True)                            # pending until Apply
    assert "RT_SBC" not in ds.lrlc_curves
    assert "RT shoulder-bed mark" in form.pending_label.text()
    with qtbot.waitSignal(tab.stale_requested, timeout=500) as blocker:
        form.apply_button.click()
    assert blocker.args == [["WELL:A"]]
    assert ds.lrlc_curves["RT_SBC"] == "RT"
    ds.curve_mapping["RT"] = "RS"                              # remapped: the mark is ignored
    tab.update_display()
    assert not form.sbc_check.isChecked() and "no longer the mapped RT" in form.sbc_note.text()
    ds.curve_mapping["RT"] = "RT"
    tab.update_display()
    assert form.sbc_check.isChecked()
    form.sbc_check.setChecked(False)
    with qtbot.waitSignal(tab.stale_requested, timeout=500):
        form.apply_button.click()
    assert "RT_SBC" not in ds.lrlc_curves


def test_guard_status_texts_and_toggle(window, qtbot, run_result):
    ds = make_well(window, run_result)
    tab = enable(window, qtbot)
    tab.select_zone("UPPER")
    form = tab.remediation_form
    assert "The guard is on." in form.guard_status.text()
    assert "Zone UPPER: laminated (laminar share 0.98)." in form.guard_status.text()
    guard = ds.summary["lrlc"]["guard"]["zones"][0]
    guard["blocked_steps"] = ["decon"]
    guard["sbc_rt"] = True
    tab.update_display()
    text = form.guard_status.text()
    assert "decon not applied in Zone UPPER: laminated (guard); use the laminated-sand " \
           "correction." in text
    assert "RT is marked shoulder-bed corrected in Zone UPPER, which is laminated" in text
    seen = []
    tab.guard_toggled.connect(seen.append)
    form.guard_check.setChecked(False)                         # pending until Apply
    assert window.model.project.lrlc["guard"]["enabled"] is not False and seen == []
    assert "The guard is off" in form.guard_status.text()
    with qtbot.waitSignal(tab.stale_requested, timeout=500) as blocker:
        form.apply_button.click()
    assert blocker.args == [["WELL:A"]] and seen == [False]
    assert window.model.project.lrlc["guard"]["enabled"] is False
    assert "The guard is off" in form.guard_status.text()


def test_guard_status_before_a_run(window, qtbot, run_result):
    make_well(window, run_result, with_run=False)
    tab = enable(window, qtbot)
    assert "Thomas-Stieber" in tab.remediation_form.guard_status.text()


# ---- remediation: form --------------------------------------------------------------------
def test_changing_a_control_writes_nothing(window, qtbot, run_result, monkeypatch):
    ds = make_well(window, run_result)
    tab = enable(window, qtbot)
    monkeypatch.setattr("modules.pipeline.run_pipeline",
                        lambda *a, **k: pytest.fail("pipeline ran"))
    form = tab.remediation_form
    before = (dict(window.model.project.lrlc["params"]["default"]), dict(ds.lrlc or {}))
    form.controls["phi_max"].setValue(0.31)
    form.controls["pyr_f"].setValue(0.6)
    form.controls["qv_source"].setCurrentIndex(1)
    assert {"phi_max", "pyr_f", "qv_source"} <= form._dirty
    assert form.apply_button.isEnabled()
    assert "Not yet written" in form.pending_label.text()
    assert (window.model.project.lrlc["params"]["default"], ds.lrlc or {}) == before
    form.discard_button.click()
    assert not form._dirty and not form.apply_button.isEnabled()
    assert form.controls["phi_max"].value() == pytest.approx(0.30)       # the stored value


def test_apply_writes_the_scope_and_asks_for_a_recheck(window, qtbot, run_result, monkeypatch):
    ds = make_well(window, run_result)
    tab = enable(window, qtbot)
    monkeypatch.setattr("modules.pipeline.run_pipeline",
                        lambda *a, **k: pytest.fail("pipeline ran"))
    form = tab.remediation_form
    tab.select_zone("UPPER")
    form.controls["phi_max"].setValue(0.32)
    form.controls["phi_sh"].setValue(0.09)
    form.scope_combo.setCurrentIndex(form.scope_combo.findData("zone"))
    with qtbot.waitSignal(tab.stale_requested, timeout=500) as blocker:
        form.apply_button.click()
    assert blocker.args == [["WELL:A"]]
    assert ds.lrlc["zones"]["UPPER"]["phi_max"] == 0.32 and ds.lrlc["zones"]["UPPER"]["phi_sh"] == 0.09
    assert "default" not in ds.lrlc or "phi_max" not in ds.lrlc["default"]
    assert not form._dirty and "Written" in form.result_label.text()
    assert window.model.dirty
    # project default
    form.controls["pyr_f"].setValue(0.5)
    form.scope_combo.setCurrentIndex(form.scope_combo.findData("project"))
    with qtbot.waitSignal(tab.stale_requested, timeout=500):
        form.apply_button.click()
    assert window.model.project.lrlc["params"]["default"]["pyr_f"] == 0.5


def test_apply_refuses_a_broken_rule_with_a_message(window, qtbot, run_result):
    ds = make_well(window, run_result)
    tab = enable(window, qtbot)
    form = tab.remediation_form
    form.controls["phi_max"].setValue(0.32)
    form.controls["phi_sh"].setValue(0.31)                    # within 0.02 of phi_max
    emitted = []
    tab.stale_requested.connect(emitted.append)
    form.apply_button.click()
    assert emitted == [] and not ds.lrlc
    assert "Nothing was written" in form.result_label.text()


def test_apply_writes_the_switches_through_settings(window, qtbot, run_result):
    make_well(window, run_result)
    tab = enable(window, qtbot)
    form = tab.remediation_form
    form.ts_check.setChecked(True)
    assert window.model.project.lrlc["thomas_stieber"]["enabled"] is False   # not yet written
    with qtbot.waitSignal(tab.stale_requested, timeout=500) as blocker:
        form.apply_button.click()
    assert window.model.project.lrlc["thomas_stieber"]["enabled"] is True
    assert blocker.args == [["WELL:A"]]


def test_prepare_remedy_fills_the_form_without_writing(window, qtbot, run_result):
    ds = make_well(window, run_result)
    tab = enable(window, qtbot)
    panel = tab.zones_panel
    tab.select_zone("UPPER")
    buttons = [b for b in panel.findChildren(type(tab.enable_button))
               if b.text() == "Prepare remediation"]
    assert buttons
    buttons[0].click()
    form = tab.remediation_form
    assert tab.panels.currentIndex() == 2
    assert form.zone == "UPPER" and form._step_toggles == {"laminated": True}
    assert form.step_checks["laminated"].isChecked() and "sw_basis" in form._dirty
    assert form.scope_combo.currentData() == "zone"          # a zone in the header writes the zone
    assert form.controls["sw_basis"].currentData() == "sand"
    assert form.ts_check.isChecked() and "thomas_stieber" not in ds.lrlc_curves
    assert not ds.lrlc
    assert window.model.project.lrlc["params"]["default"] == {"phi_max": 0.3, "phi_sh": 0.08}
    assert "Thomas-Stieber on" in form.pending_label.text()
    with qtbot.waitSignal(tab.stale_requested, timeout=500):
        form.apply_button.click()
    assert ds.lrlc["zones"]["UPPER"]["rt_steps"] == ["laminated"]
    assert "rt_steps" not in (ds.lrlc.get("default") or {})
    assert resolve_lrlc({}, ds.lrlc, "UPPER")["sw_basis"] == "sand"


def test_clay_section_reads_core_cec(window, qtbot, run_result):
    ds = make_well(window, run_result)
    depth = ds.results["DEPTH"].to_numpy()[::10]
    vsh = ds.results["VSH"].to_numpy()[::10]
    ds.core_data = SimpleNamespace(data=pd.DataFrame({"DEPTH": depth, "CEC": 20.0 * vsh}),
                                   depth_col="DEPTH", get_summary=lambda: {})
    tab = enable(window, qtbot)
    form = tab.remediation_form
    assert "From core CEC" in form.cec_label.text() and form.use_cec_button.isEnabled()
    form.use_cec_button.click()
    assert form.controls["cec_shale"].value() == pytest.approx(20.0, abs=0.2)
    assert "cec_shale" in form._dirty
    ds.core_data = None
    form.set_context(window.model, ds, None, [])
    assert not form.use_cec_button.isEnabled() and "No core CEC" in form.cec_label.text()


def test_sw_basis_and_model_link(window, qtbot, run_result):
    make_well(window, run_result)
    tab = enable(window, qtbot)
    form = tab.remediation_form
    tab.select_zone("UPPER")
    assert "bulk" in form.basis_label.text()
    assert "Waxman-Smits or Archie" in form.suggestion_label.text()
    form.controls["sw_basis"].setCurrentIndex(form.controls["sw_basis"].findData("sand"))
    assert "sand-lamina" in form.basis_label.text()
    seen = []
    tab.navigate_requested.connect(seen.append)
    form.sw_models_button.click()
    assert seen == ["params.sat"]


def test_laminated_hint_and_method_boxes(window, qtbot, run_result):
    make_well(window, run_result)
    tab = enable(window, qtbot)
    form = tab.remediation_form
    tab.select_zone("LOWER")
    assert "Zone LOWER is laminated by Thomas-Stieber; consider the laminated-sand Rt" in \
        form.hint_label.text()
    assert tab.ts_panel.method_box.title().replace("&&", "&") == "Method & Reference"
    for box in (form.laminated_box, form.pyrite_box, form.qv_box, tab.ts_panel.method_box):
        assert "References:" in box.citations.text()
    for box in (form.laminated_box, form.pyrite_box, form.qv_box):   # one-line strips
        assert box.compact and box.title() == "" and box.equation_view.isHidden()
        assert box.title_label.text().startswith("Method: ")
    assert "Hagiwara" in form.laminated_box.citations.text()


def test_pyrite_preview_and_plot(window, qtbot, run_result):
    make_well(window, run_result)
    tab = enable(window, qtbot)
    form = tab.remediation_form
    tab.select_zone("UPPER")
    assert "VPYR in the last run" in form.vpyr_label.text()
    form.controls["pyr_pef"].setValue(20.0)
    assert form.pef_plot.plot.figure.axes
    form.controls["pyr_method"].setCurrentIndex(0)
    assert form.controls["pyr_vpyr"].isEnabled()


# ---- validation ---------------------------------------------------------------------------
def test_validation_tables(window, qtbot, run_result):
    ds = make_well(window, run_result)
    tab = enable(window, qtbot)
    panel = tab.validation_panel
    val = ds.summary["lrlc"]["validation"]
    assert column(panel.pay_table, 0) == ["Whole well", "UPPER", "LOWER"]
    assert panel.pay_table.item(0, 1).text() == f"{val['well']['net_pay_base']:.1f}"
    assert panel.pay_table.item(0, 2).text() == f"{val['well']['net_pay']:.1f}"
    assert panel.pay_table.item(0, 3).text() == f"{val['well']['delta']:+.1f}"
    assert panel.pay_table.item(1, 6).text() == f"{val['zones'][0]['hcpv_net_pay_base']:.3f}"
    assert "measured RT, scalar Qv, bulk basis" in panel.basis_label.text()
    assert panel.pay_label.text() == "Pay Sw: resistivity Sw."
    assert panel.shf_group.isHidden()
    assert panel.plot.figure.axes and len(panel.plot.figure.axes[0].lines) == 2
    tab.select_zone("UPPER")
    assert len(panel.plot.figure.axes[0].lines) == 2


def test_validation_shf_block(window, qtbot, run_result):
    ds = make_well(window, run_result)
    stats = {"n": 40, "bias": 0.12, "rmse": 0.2, "mae": 0.1, "r2": 0.5}
    better = {"n": 40, "bias": 0.03, "rmse": 0.1, "mae": 0.05, "r2": 0.8}
    val = ds.summary["lrlc"]["validation"]
    val["shf"] = {"well": {"base": stats, "corrected": better},
                  "zones": [{"zone": "UPPER", "base": stats, "corrected": None}]}
    val["pay_sw"] = "SHF where available"
    val["n_shf_held"] = 12
    ds.results["SW_SHF"] = 0.5
    tab = enable(window, qtbot)
    panel = tab.validation_panel
    assert not panel.shf_group.isHidden()
    assert column(panel.shf_table, 0) == ["Whole well", "UPPER"]
    assert [panel.shf_table.item(0, c).text() for c in range(2, 6)] == [
        "0.120", "0.030", "0.200", "0.100"]
    assert "12 sample(s) are held by saturation height" in panel.pay_label.text()
    assert len(panel.plot.figure.axes[0].lines) == 3


# ---- theme and hygiene --------------------------------------------------------------------
def test_refresh_theme_redraws(window, qtbot, run_result):
    make_well(window, run_result)
    tab = enable(window, qtbot)
    tab.select_zone("UPPER")
    tab.refresh_theme()
    assert tab.ts_panel.plot.n_drawn > 0


def test_new_sources_have_no_hex_emoji_or_phase_ids():
    root = pathlib.Path(__file__).resolve().parents[1]
    names = ("ui/widgets/lrlc_ts_plot.py", "ui/widgets/lrlc_remediation.py",
             "ui/widgets/lrlc_diagnosis.py", "ui/widgets/lrlc_validation.py",
             "ui/widgets/lrlc_common.py", "ui/tabs/lrlc_tab.py")
    for name in names:
        text = root.joinpath(name).read_text(encoding="utf-8")
        assert not re.search(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b", text), name
        assert not re.search("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️]", text), name
        assert "setStyleSheet" not in text, name
        assert not re.search(r"\b(L[1-4]|P[0-9])\b", text), name
