"""Multi-well loading: grouping, Load Summary, per-well state and delivery."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pytest
from PyQt6.QtWidgets import QDialog, QMessageBox

from modules.formation_tops import Formation, FormationTops
from modules.las_parser import LASParser
from services.load_service import (
    LoadWorker, ParsedFile, build_well, group_files, parse_file,
)
from ui.main_window import MainWindow
from ui.widgets.load_summary_dialog import LoadSummaryDialog


def _las_text(well, uwi="", top=1000.0, bottom=1060.0, gr="GR"):
    depths = np.arange(top, bottom + 0.5, 1.0)
    rows = "\n".join(
        f"{d:.1f} {60 + i % 7:.1f} {2.35 + 0.001 * (i % 9):.3f} {0.20 + 0.002 * (i % 5):.4f} {10 + i % 4:.1f}"
        for i, d in enumerate(depths)
    )
    return (
        "~VERSION INFORMATION\n VERS. 2.0 : CWLS LAS\n WRAP. NO : One line per depth\n"
        "~WELL INFORMATION\n"
        f" STRT.FT {top} : START\n STOP.FT {bottom} : STOP\n STEP.FT 1.0 : STEP\n"
        " NULL. -999.25 : NULL\n"
        f" WELL. {well} : WELL\n UWI. {uwi} : UWI\n"
        "~CURVE INFORMATION\n DEPT.FT : Depth\n"
        f" {gr}.GAPI : Gamma\n RHOB.G/CC : Density\n NPHI.V/V : Neutron\n RT.OHMM : Resistivity\n"
        "~A\n" + rows + "\n"
    )


def _write(tmp_path, name, **kwargs):
    path = tmp_path / name
    path.write_text(_las_text(**kwargs))
    return str(path)


def _parsed(tmp_path, name, **kwargs):
    item = parse_file(_write(tmp_path, name, **kwargs))
    assert item.ok, item.error
    return item


def _fake(well="", uwi=""):
    parser = LASParser()
    parser.data = pd.DataFrame({"DEPTH": [1.0, 2.0], "GR": [1.0, 2.0]})
    parser.well_info = {"well_name": well, "uwi": uwi}
    return ParsedFile(f"{well or 'x'}.las", f"{well or 'x'}.las", parser)


def _tops(top=1010.0, bottom=1050.0):
    tops = FormationTops()
    tops.formations = [Formation("Zone A", top, bottom, bottom - top)]
    return tops


@pytest.fixture
def window(qtbot):
    widget = MainWindow()
    qtbot.addWidget(widget)
    yield widget
    widget.close()


@pytest.fixture
def two_wells(window, tmp_path):
    """BKS-01 (GR curve 'GR') then BKS-02 (GR curve 'CGR'); BKS-02 is active."""
    window._load_single_las(_write(tmp_path, "a.las", well="BKS-01"))
    window._load_single_las(_write(tmp_path, "b.las", well="BKS-02", gr="CGR"))
    return window


# ---- group_files ------------------------------------------------------------

def test_group_files_name_variants_share_a_group():
    files = [_fake("BKS-01"), _fake("bks_01 "), _fake("BKS 01")]
    assert [len(g) for g in group_files(files)] == [3]


def test_group_files_different_wells_split_in_input_order():
    a1, b, a2 = _fake("A"), _fake("B"), _fake("a")
    groups = group_files([a1, b, a2])
    assert groups == [[a1, a2], [b]]


def test_group_files_uwi_conflict_splits_even_with_same_name():
    a, b = _fake("BKS-01", uwi="111"), _fake("BKS-01", uwi="222")
    assert len(group_files([a, b])) == 2


def test_group_files_unidentified_files_stay_alone():
    u1, u2, named = _fake(""), _fake(""), _fake("A")
    assert group_files([u1, named, u2]) == [[u1], [named], [u2]]


def test_group_files_skips_failed_parses():
    bad = ParsedFile("bad.las", "bad.las", None, "broken")
    good = _fake("A")
    assert group_files([bad, good]) == [[good]]


# ---- build_well ---------------------------------------------------------------

def test_build_well_single(tmp_path):
    item = _parsed(tmp_path, "a.las", well="BKS-01", uwi="")
    ds = build_well([item])
    assert ds.key == "WELL:BKS-01" and ds.display_name == "BKS-01"
    assert not ds.merged and ds.las_filename == item.path
    assert ds.las_data is item.parser.data
    assert ds.sources == [{"name": "a.las", "path": item.path, "rows": len(item.parser.data)}]
    assert ds.curve_mapping["GR"] == "GR" and ds.curve_mapping["RT"] == "RT"
    assert ds.qc_report is not None


def test_build_well_unidentified_uses_file_key(tmp_path):
    ds = build_well([_parsed(tmp_path, "mystery.las", well="")])
    assert ds.key == "FILE:MYSTERY"


def test_build_well_merged_keeps_sources_intact(tmp_path):
    from modules.las_handler import LASHandler

    first = _parsed(tmp_path, "a.las", well="BKS-01", top=1000.0, bottom=1040.0)
    second = _parsed(tmp_path, "b.las", well="BKS-01", top=1030.0, bottom=1080.0)
    n_first = len(first.parser.data)
    result = LASHandler().merge_las_files(
        [first.parser, second.parser], file_identifiers=["a.las", "b.las"],
        step_ft=0.5, gap_limit_ft=5.0,
    )
    ds = build_well([first, second], result)
    assert ds.merged and ds.las_filename == "MERGED_2_files"
    assert ds.key == "WELL:BKS-01"
    assert ds.merge_report is result["merge_report"]
    assert len(ds.las_data) > n_first and len(first.parser.data) == n_first
    assert ds.las_parser is not first.parser
    assert [s["rows"] for s in ds.sources] == [n_first, len(second.parser.data)]


# ---- worker + Load Summary -------------------------------------------------------

def test_load_worker_parses_all_files(tmp_path):
    paths = [_write(tmp_path, "a.las", well="A"), str(tmp_path / "missing.las")]
    done = []
    worker = LoadWorker(paths)
    worker.signals.completed.connect(done.append)
    worker.run()
    parsed = done[0]
    assert [p.ok for p in parsed] == [True, False]
    assert parsed[1].error


def test_summary_dialog_groups_and_refuses_conflicts(qtbot, tmp_path):
    items = [
        _parsed(tmp_path, "a1.las", well="A"),
        _parsed(tmp_path, "a2.las", well="A", top=1050.0, bottom=1100.0),
        _parsed(tmp_path, "b.las", well="B"),
        ParsedFile("bad.las", "bad.las", None, "broken file"),
    ]
    dialog = LoadSummaryDialog(items, 0.5, 5.0)
    qtbot.addWidget(dialog)
    assert [[f.name for f in g] for g in dialog.groups()] == [["a1.las", "a2.las"], ["b.las"]]
    assert dialog._ok_button.text() == "Load 2 wells" and dialog._ok_button.isEnabled()
    assert dialog.step_spin.isEnabled()
    assert dialog.table.item(3, 6).text() == "broken file"
    # Put the B file into well A's group: refused.
    combo = dialog._combos[2]
    combo.setCurrentIndex(combo.findData(0))
    assert not dialog._ok_button.isEnabled() and "different wells" in dialog._ok_button.toolTip()
    # Split A's files apart: nothing merges, merge settings are disabled.
    for row in (0, 1, 2):
        dialog._combos[row].setCurrentIndex(dialog._combos[row].findData(-1))
    assert len(dialog.groups()) == 3 and dialog._ok_button.isEnabled()
    assert not dialog.step_spin.isEnabled()
    assert dialog.merge_settings() == (0.5, 5.0)


# ---- opening several files -------------------------------------------------------

def test_open_three_files_two_wells_one_merged(window, qtbot, tmp_path, monkeypatch):
    paths = [
        _write(tmp_path, "a1.las", well="BKS-01", top=1000.0, bottom=1040.0),
        _write(tmp_path, "b.las", well="BKS-02"),
        _write(tmp_path, "a2.las", well="bks_01", top=1030.0, bottom=1080.0),
    ]
    monkeypatch.setattr(LoadSummaryDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    window._on_las_files_selected(paths)
    qtbot.waitUntil(
        lambda: len(window.model.project) == 2 and not window._bulk_loading, timeout=20000
    )
    project = window.model.project
    assert project.keys() == ["WELL:BKS-01", "WELL:BKS-02"]
    assert project.get("WELL:BKS-01").merged and not project.get("WELL:BKS-02").merged
    assert [s["name"] for s in project.get("WELL:BKS-01").sources] == ["a1.las", "a2.las"]
    assert project.active_key == "WELL:BKS-02"  # last added
    assert window.windowTitle() == "BKS-02 · 2 wells — Petrophyter"
    assert window.actions_["merge_las"].isEnabled() and window.actions_["open_las"].isEnabled()


def test_cancelled_summary_loads_nothing(window, qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(LoadSummaryDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    window._on_las_files_selected([
        _write(tmp_path, "a.las", well="A"), _write(tmp_path, "b.las", well="B"),
    ])
    qtbot.waitUntil(lambda: not window._bulk_loading, timeout=20000)
    assert len(window.model.project) == 0
    assert window.actions_["open_las"].isEnabled()


def test_merge_action_opens_the_open_dialog(window, monkeypatch):
    from PyQt6.QtWidgets import QFileDialog

    calls = []
    monkeypatch.setattr(
        QFileDialog, "getOpenFileNames",
        staticmethod(lambda *a, **k: calls.append(1) or ([], "")),
    )
    window.actions_["merge_las"].trigger()
    assert calls == [1]


def test_notes_from_every_file_go_into_one_banner(window, qtbot, tmp_path, monkeypatch):
    paths = [
        _write(tmp_path, "a.las", well="A"), _write(tmp_path, "b.las", well="B"),
    ]
    monkeypatch.setattr(LoadSummaryDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    shown = []
    monkeypatch.setattr(window, "show_banner", lambda kind, text: shown.append((kind, text)))
    original = window._add_built_well

    def with_warning(files, merge_result, extra=()):
        files[0].parser.unit_warnings = [f"warning for {files[0].name}"]
        original(files, merge_result, extra)

    monkeypatch.setattr(window, "_add_built_well", with_warning)
    window._on_las_files_selected(paths)
    qtbot.waitUntil(lambda: len(window.model.project) == 2 and not window._bulk_loading,
                    timeout=20000)
    assert len(shown) == 1
    assert "A: warning for a.las" in shown[0][1] and "B: warning for b.las" in shown[0][1]


# ---- switching the active well ---------------------------------------------------

def test_switching_wells_updates_mapping_title_and_results(two_wells):
    window = two_wells
    combos = window.params_window.curve_mapping_widget.curve_combos
    assert combos["GR"].currentText() == "CGR"
    assert window.windowTitle() == "BKS-02 · 2 wells — Petrophyter"

    a = window.model.project.get("WELL:BKS-01")
    a.results = pd.DataFrame({"DEPTH": [1.0]})
    window.model.set_active_well("WELL:BKS-01")
    assert combos["GR"].currentText() == "GR"
    assert window.model.curve_mapping["GR"] == "GR"
    assert window.model.results is a.results
    assert window.windowTitle() == "BKS-01 · 2 wells — Petrophyter"
    assert "BKS-01" in window.well_indicator.label.text()
    window.model.set_active_well("WELL:BKS-02")
    assert combos["GR"].currentText() == "CGR"
    assert window.model.results is None


def test_switching_wells_does_not_mark_results_stale(two_wells):
    window = two_wells
    window.model.project.get("WELL:BKS-01").calculated = True
    window.model.set_active_well("WELL:BKS-01")
    assert window.stale_label.isHidden()
    assert not window.model.project.get("WELL:BKS-01").stale


def test_formation_scope_follows_the_active_well(two_wells):
    window = two_wells
    window.model.set_active_well("WELL:BKS-01")
    window.model.formation_tops = _tops()
    window.params_window.update_formations_list(["Zone A"])
    mode = window.params_window.analysis_mode_widget
    mode.per_formation_radio.setChecked(True)
    mode.formation_list.item(0).setSelected(True)
    window.params_window.update_model_from_ui()
    assert window.model.analysis_mode == "Per-Formation"
    window.model.set_active_well("WELL:BKS-02")
    assert mode.formation_list.count() == 0
    assert mode.get_mode() == "Whole Well"
    window.model.set_active_well("WELL:BKS-01")
    assert mode.get_mode() == "Per-Formation"
    assert mode.get_selected_formations() == ["Zone A"]
    assert window.model.selected_formations == ["Zone A"]


def test_selector_and_data_browser_signals_switch_wells(two_wells):
    window = two_wells
    window._on_well_selected("WELL:BKS-01")
    assert window.model.project.active_key == "WELL:BKS-01"
    window._on_well_selected("NOT-A-KEY")
    assert window.model.project.active_key == "WELL:BKS-01"


def test_remove_well_asks_and_activates_another(two_wells, monkeypatch):
    window = two_wells
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    window._on_remove_well_requested("WELL:BKS-02")
    assert len(window.model.project) == 2
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    window._on_remove_well_requested("WELL:BKS-02")
    assert window.model.project.keys() == ["WELL:BKS-01"]
    assert window.model.project.active_key == "WELL:BKS-01"
    assert window.windowTitle() == "BKS-01 — Petrophyter"
    window._on_remove_well_requested("WELL:BKS-01")
    assert window.windowTitle() == "Petrophyter"
    assert not window.actions_["run_analysis"].isEnabled()


# ---- stale flag, delivery ------------------------------------------------------------

def test_stale_flag_is_per_well(two_wells):
    window = two_wells
    a, b = (window.model.project.get(k) for k in ("WELL:BKS-01", "WELL:BKS-02"))
    a.calculated = b.calculated = True
    window.params_window.parameters_updated.emit()  # B is active
    assert b.stale and not a.stale
    assert not window.stale_label.isHidden()
    window.model.set_active_well("WELL:BKS-01")
    assert window.stale_label.isHidden()
    window.model.set_active_well("WELL:BKS-02")
    assert not window.stale_label.isHidden()
    window._clear_results_stale()
    assert not b.stale and window.stale_label.isHidden()


def test_analysis_results_go_to_the_well_that_started_the_run(two_wells, monkeypatch):
    window = two_wells
    monkeypatch.setattr(window.analysis_service, "run_analysis", lambda model: None)
    window.model.set_active_well("WELL:BKS-01")
    window._on_run_analysis()
    window.model.set_active_well("WELL:BKS-02")  # switch while it "runs"

    results = pd.DataFrame({"DEPTH": [1.0]})
    summary = {"net_pay": 1.0, "gross_sand": 2.0, "ng_pay": 0.5}
    window._on_analysis_completed(results, summary)

    a, b = (window.model.project.get(k) for k in ("WELL:BKS-01", "WELL:BKS-02"))
    assert a.results is results and a.summary is summary and a.calculated
    assert b.results is None and not b.calculated
    assert window.model.results is None  # active well B is untouched
    assert window.actions_["run_analysis"].isEnabled()
    window.model.set_active_well("WELL:BKS-01")
    assert window.model.results is results


def test_analysis_error_is_recorded_on_the_starting_well(two_wells, monkeypatch):
    window = two_wells
    monkeypatch.setattr(window.analysis_service, "run_analysis", lambda model: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    window.model.set_active_well("WELL:BKS-01")
    window._on_run_analysis()
    window.model.set_active_well("WELL:BKS-02")
    window._on_analysis_error("Analysis failed: boom")
    a, b = (window.model.project.get(k) for k in ("WELL:BKS-01", "WELL:BKS-02"))
    assert a.status == "error" and b.status == "loaded"


def test_analysis_result_for_a_removed_well_is_dropped(two_wells, monkeypatch):
    window = two_wells
    monkeypatch.setattr(window.analysis_service, "run_analysis", lambda model: None)
    window._on_run_analysis()  # B
    window.model.project.remove_well("WELL:BKS-02")
    window._on_analysis_completed(pd.DataFrame({"DEPTH": [1.0]}), {})
    assert window.model.project.get("WELL:BKS-01").results is None


def test_real_analysis_delivers_to_origin_after_switch(two_wells, qtbot):
    window = two_wells
    window.model.set_active_well("WELL:BKS-01")
    window._on_run_analysis()
    window.model.set_active_well("WELL:BKS-02")
    a = window.model.project.get("WELL:BKS-01")
    qtbot.waitUntil(lambda: bool(a.calculated or a.error), timeout=30000)
    assert a.error is None and a.results is not None
    assert window.model.project.get("WELL:BKS-02").results is None


# ---- reload, tops, core -------------------------------------------------------------

def test_reload_replaces_by_key_and_says_so(window, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(window, "show_banner", lambda kind, text: shown.append((kind, text)))
    window._load_single_las(_write(tmp_path, "a.las", well="BKS-01", bottom=1040.0))
    first = window.model.active_well
    window._load_single_las(_write(tmp_path, "a_again.las", well="bks_01", bottom=1080.0))
    assert len(window.model.project) == 1
    assert window.model.active_well is not first
    assert len(window.model.las_data) > len(first.las_data)
    assert shown[-1][0] == "info" and "Reloaded BKS-01" in shown[-1][1]


def test_tops_attach_to_the_active_well_only(two_wells, tmp_path):
    window = two_wells
    path = tmp_path / "tops.txt"
    path.write_text("Formation\tTop\tBottom\nZone A\t1010\t1050\n")
    window.model.set_active_well("WELL:BKS-01")
    window._on_tops_file_selected(str(path))
    a, b = (window.model.project.get(k) for k in ("WELL:BKS-01", "WELL:BKS-02"))
    assert a.formation_tops is not None and b.formation_tops is None
    assert window.params_window.analysis_mode_widget.formation_list.count() == 1
    window.model.set_active_well("WELL:BKS-02")
    assert window.model.formation_tops is None
    assert window.params_window.analysis_mode_widget.formation_list.count() == 0


def test_tops_and_core_are_refused_without_a_well(window, monkeypatch):
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    window._on_tops_file_selected("nothing.txt")
    window._on_core_file_selected("nothing.txt")
    assert len(warned) == 2 and all("Load a LAS file first" in w for w in warned)


def test_new_project_clears_every_well(two_wells, monkeypatch):
    window = two_wells
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    window._on_new_project()
    assert len(window.model.project) == 0
    assert window.windowTitle() == "Petrophyter"
    assert not window.actions_["run_analysis"].isEnabled()
    assert window.well_indicator.label.text() == "No data loaded"


def test_save_merged_follows_the_active_well(window, qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(LoadSummaryDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    window._on_las_files_selected([
        _write(tmp_path, "a1.las", well="A", bottom=1040.0),
        _write(tmp_path, "a2.las", well="A", top=1030.0, bottom=1080.0),
    ])
    qtbot.waitUntil(lambda: len(window.model.project) == 1 and not window._bulk_loading,
                    timeout=20000)
    assert window.actions_["save_merged"].isEnabled()
    window._load_single_las(_write(tmp_path, "b.las", well="B"))
    assert not window.actions_["save_merged"].isEnabled()
    window.model.set_active_well("WELL:A")
    assert window.actions_["save_merged"].isEnabled()
