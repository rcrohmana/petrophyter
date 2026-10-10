"""Phase 0 app-state tests: Rw/Rsh modes, sessions, well change, depth overlap."""

import json

import numpy as np
import pandas as pd
import pytest

from models.app_model import AppModel
from modules.core_handler import CoreDataHandler
from modules.formation_tops import Formation, FormationTops
from modules.las_parser import LASParser
from services.session_service import SessionService
from ui.main_window import MainWindow


@pytest.fixture
def window(qtbot):
    widget = MainWindow()
    qtbot.addWidget(widget)
    yield widget
    widget.close()


def _parser(well="WELL-A", start=1000.0, stop=1100.0):
    p = LASParser()
    depth = np.linspace(start, stop, 11)
    p.data = pd.DataFrame({"DEPTH": depth, "GR": np.linspace(30, 90, 11)})
    p.well_info = {"well_name": well, "uwi": "", "start": start, "stop": stop}
    return p


def _tops(top=1010.0, bottom=1090.0):
    t = FormationTops()
    t.formations = [Formation("Zone A", top, bottom, bottom - top)]
    return t


def _load(window, parser, name=None):
    """Load an in-memory parser as one well through the real load path."""
    from services.load_service import ParsedFile

    name = name or f"{parser.well_info.get('well_name') or 'unnamed'}.las"
    window._begin_load([[ParsedFile(name, name, parser)]])


def test_auto_checkbox_disables_spin_and_syncs_model(window):
    res = window.params_window.res_params_widget
    assert res.rsh_auto_cb.isChecked() and not res.rsh_spin.isEnabled()
    assert not res.rw_auto_cb.isChecked() and res.rw_spin.isEnabled()
    res.rw_auto_cb.setChecked(True)
    res.rsh_auto_cb.setChecked(False)
    assert not res.rw_spin.isEnabled() and res.rsh_spin.isEnabled()
    window.params_window.update_model_from_ui()
    assert window.model.rw_mode == "auto"
    assert window.model.rsh_mode == "manual"


def test_apply_calculated_switches_to_manual(window):
    res = window.params_window.res_params_widget
    res.rw_auto_cb.setChecked(True)
    res.rsh_auto_cb.setChecked(True)
    res.show_calculated_result(0.07, 4.0)
    res.apply_calculated()
    assert res.get_params() == {
        "rw": pytest.approx(0.07), "rsh": pytest.approx(4.0),
        "rw_mode": "manual", "rsh_mode": "manual",
    }


def test_modes_restored_from_model(window):
    window.model.rw_mode, window.model.rsh_mode = "auto", "manual"
    window._update_ui_from_model()
    res = window.params_window.res_params_widget
    assert res.rw_auto_cb.isChecked() and not res.rsh_auto_cb.isChecked()


def test_session_round_trip_modes(tmp_path):
    svc = SessionService()
    model = AppModel()
    model.rw_mode, model.rsh_mode = "auto", "manual"
    path = str(tmp_path / "s.json")
    assert svc.save_session(model, path)
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    assert data["_session_version"] == "2.1"
    fresh = AppModel()
    svc.apply_session_to_model(fresh, svc.load_session(path))
    assert (fresh.rw_mode, fresh.rsh_mode) == ("auto", "manual")


@pytest.mark.parametrize("rw,expected", [(0.01, "auto"), (0.05, "manual")])
def test_legacy_session_mode_mapping(tmp_path, rw, expected):
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"_session_version": "1.3", "rw": rw}))
    svc = SessionService()
    model = AppModel()
    model.rsh_mode = "manual"
    svc.apply_session_to_model(model, svc.load_session(str(path)))
    assert model.rw_mode == expected
    assert model.rsh_mode == "auto"


def test_session_load_marks_existing_results_stale(window, monkeypatch, tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"_session_version": "1.4", "rw": 0.1}))
    from PyQt6.QtWidgets import QFileDialog

    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), "")
    )
    _load(window, _parser("WELL-S"))
    window.model._well.calculated = True
    window._on_load_session()
    assert not window.stale_label.isHidden()
    window.model._well.calculated = False
    window._on_load_session()
    assert window.stale_label.isHidden()


def test_new_well_does_not_inherit_tops_and_core(window):
    _load(window, _parser("WELL-A"))
    window.model.formation_tops = _tops()
    window.model.core_data = CoreDataHandler()
    window.model.selected_formations = ["Zone A"]
    window.model.analysis_mode = "Per-Formation"
    _load(window, _parser("WELL-B"))
    assert window.model.formation_tops is None
    assert window.model.core_data is None
    assert window.model.selected_formations == []
    assert window.model.analysis_mode == "Whole Well"
    # Well A still owns its tops and scope.
    window.model.set_active_well("WELL:WELL-A")
    assert window.model.formation_tops is not None
    assert window.model.selected_formations == ["Zone A"]
    assert window.model.analysis_mode == "Per-Formation"


def test_reload_same_well_keeps_its_tops(window):
    _load(window, _parser("WELL-A"))
    window.model.formation_tops = _tops()
    window.model.selected_formations = ["Zone A"]
    _load(window, _parser("well-a"))
    assert len(window.model.project) == 1
    assert window.model.formation_tops is not None
    assert window.model.selected_formations == ["Zone A"]
    assert "Reloaded" in window.banner.message_label.text()


def test_unidentified_well_is_a_separate_well(window):
    _load(window, _parser("WELL-A"))
    window.model.formation_tops = _tops()
    _load(window, _parser(""), name="mystery.las")
    assert len(window.model.project) == 2
    assert window.model.formation_tops is None


def test_reset_clears_selected_formations():
    model = AppModel()
    model.selected_formations = ["Zone A"]
    model.analysis_mode = "Per-Formation"
    model.reset()
    assert model.selected_formations == []
    assert model.analysis_mode == "Whole Well"


def test_overlap_warning_only_without_overlap(window):
    _load(window, _parser(start=5000.0, stop=6000.0))
    window.model.formation_tops = _tops(1000.0, 1100.0)
    window.banner.clear()
    window._show_load_notes(None)
    text = window.banner.message_label.text()
    assert "do not overlap" in text and "Check the depth unit" in text
    window.banner.clear()
    window.model.formation_tops = _tops(5500.0, 6500.0)  # partial overlap
    window._show_load_notes(None)
    assert window.banner.isHidden()


def test_unit_warnings_joined_in_one_banner(window):
    p = _parser()
    p.depth_unit_warning = "Depth unit unclear."
    p.unit_warnings = ["GR converted."]
    _load(window, p)
    text = window.banner.message_label.text()
    assert "Depth unit unclear." in text and "GR converted." in text


# ---- end-to-end: real LAS files through MainWindow._load_single_las ----------

def _las_text(well, uwi="", nphi_unit="V/V", nphi_scale=1.0):
    rows = "\n".join(
        f"{d:.1f} {60 + i:.1f} {2.35 + 0.01 * i:.3f} {(0.20 + 0.005 * i) * nphi_scale:.4f} {10 + i:.1f}"
        for i, d in enumerate(np.arange(1000.0, 1011.0, 1.0))
    )
    return (
        "~VERSION INFORMATION\n VERS. 2.0 : CWLS LAS\n WRAP. NO : One line per depth\n"
        "~WELL INFORMATION\n"
        " STRT.FT 1000.0 : START\n STOP.FT 1010.0 : STOP\n STEP.FT 1.0 : STEP\n"
        " NULL. -999.25 : NULL\n"
        f" WELL. {well} : WELL\n UWI. {uwi} : UWI\n"
        "~CURVE INFORMATION\n DEPT.FT : Depth\n GR.GAPI : Gamma\n RHOB.G/CC : Density\n"
        f" NPHI.{nphi_unit} : Neutron\n RT.OHMM : Resistivity\n"
        "~A\n" + rows + "\n"
    )


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


@pytest.fixture
def banners(window, monkeypatch):
    shown = []
    monkeypatch.setattr(window, "show_banner", lambda kind, text: shown.append((kind, text)))
    return shown


def test_e2e_different_well_gets_its_own_tops(window, banners, tmp_path):
    window._load_single_las(_write(tmp_path, "a.las", _las_text("WELL A")))
    window.model.formation_tops = _tops(1002.0, 1008.0)
    window.model.selected_formations = ["Zone A"]
    window._load_single_las(_write(tmp_path, "b.las", _las_text("WELL B")))
    assert len(window.model.project) == 2
    assert window.model.formation_tops is None
    assert window.model.selected_formations == []


def test_e2e_same_well_reload_keeps_tops(window, banners, tmp_path):
    window._load_single_las(_write(tmp_path, "a1.las", _las_text("WELL A")))
    window.model.formation_tops = _tops(1002.0, 1008.0)
    window._load_single_las(_write(tmp_path, "a2.las", _las_text("well_a ")))
    assert len(window.model.project) == 1
    assert window.model.formation_tops is not None
    assert any("Reloaded" in text for _, text in banners)


def test_e2e_percent_neutron_converted_and_reported(window, banners, tmp_path):
    window._load_single_las(_write(tmp_path, "p.las", _las_text("WELL A", nphi_unit="PU", nphi_scale=100.0)))
    nphi = window.model.las_data["NPHI"]
    assert nphi.max() < 1.0
    assert window.model.las_parser.curve_info["NPHI"]["unit"] == "V/V"
    assert any("NPHI converted to V/V" in text for _, text in banners)


def test_e2e_merge_refuses_different_wells(tmp_path):
    from services.merge_service import MergeWorker

    parsers = []
    for name, well in (("a.las", "WELL A"), ("b.las", "WELL B")):
        p = LASParser()
        with open(_write(tmp_path, name, _las_text(well)), "r") as f:
            assert p.read_las_from_buffer(f)
        parsers.append(p)
    errors, completed = [], []
    worker = MergeWorker(parsers, ["a.las", "b.las"], 0.5, 5.0)
    worker.signals.error.connect(errors.append)
    worker.signals.completed.connect(lambda df, report: completed.append(report))
    worker.run()
    assert completed == [] and "different wells" in errors[0]


def test_merge_completion_shows_report_and_all_file_unit_warnings(window, banners):
    from modules.las_handler import MergeReport
    from services.load_service import ParsedFile

    first, second = _parser("WELL A"), _parser("WELL A")
    second.unit_warnings = ["NPHI converted to V/V (from PU)."]
    group = [ParsedFile("a.las", "a.las", first), ParsedFile("b.las", "b.las", second)]
    report = MergeReport(
        curves={}, master_depth={"min": 1000.0, "max": 1100.0, "step": 0.5, "points": 201},
        files_processed=["a.las", "b.las"],
        warnings=["Curve RHOB has different units across files (G/C3, KG/M3)."],
        well_name="WELL A",
    )
    window._bulk_loading = True
    window._load_queue, window._load_notes, window._load_added = [], [], []
    window._load_current = group
    window._on_merge_completed(first.data.copy(), report)
    text = "\n".join(t for _, t in banners)
    assert "different units across files" in text
    assert "NPHI converted to V/V" in text
    assert window.model.active_well.merged
