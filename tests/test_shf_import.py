"""Capillary pressure import: plan, dialog and main-window wiring (kind="pc")."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QDialog, QFileDialog

from models.project import Project
from modules.pc_handler import PcDataHandler
from modules.well_import import (
    ImportOptions, WellRef, build_import_plan, build_parts, import_record, parse_import_file,
)
from tests.test_multiwell_loading import _write
from ui.main_window import MainWindow
from ui.widgets.well_import_dialog import MultiWellImportDialog

ACCEPTED = QDialog.DialogCode.Accepted
REJECTED = QDialog.DialogCode.Rejected

PC = """Well,Sample,Depth (ft),Porosity,Perm (mD),Pc (psi),Sw,System
BKS-01,P1,1020,0.20,100,10,0.90,air-brine
BKS-01,P1,1020,0.20,100,100,0.30,air-brine
BKS-01,P2,1030,0.12,2,10,0.95,air-brine
BKS-01,P2,1030,0.12,2,100,0.60,air-brine
BKS-02,P1,1040,0.18,50,10,0.90,air-brine
BKS-02,P1,1040,0.18,50,100,0.35,air-brine
"""


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A modal box would block the offscreen test run; fail loudly instead."""
    from PyQt6.QtWidgets import QMessageBox

    def refuse(*args, **kwargs):
        raise AssertionError(f"unexpected dialog: {args[1:3]}")

    for name in ("warning", "critical", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(refuse))


def write(tmp_path, text, name="pc.csv"):
    path = tmp_path / name
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return str(path)


def ref(name, **kw):
    kw.setdefault("log_top", 0.0)
    kw.setdefault("log_bottom", 10000.0)
    return WellRef(key=f"WELL:{name}", display_name=name, well_info={"well_name": name}, **kw)


def plan_for(path, wells, **opts):
    options = ImportOptions(kind="pc", **opts)
    parsed = parse_import_file(path, options)
    return build_import_plan(parsed, path, wells, options)


class StubCore:
    def __init__(self, depths, phi, perm):
        self.d, self.phi, self.perm = depths, phi, perm

    def get_core_porosity(self):
        import numpy as np
        return np.array(self.d), np.array(self.phi)

    def get_core_permeability(self):
        import numpy as np
        return np.array(self.d), np.array(self.perm)


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------
def test_plan_rows_count_curves_and_match(tmp_path):
    plan = plan_for(write(tmp_path, PC), [ref("BKS-01"), ref("BKS-02")])
    assert [(r.file_well, r.rows) for r in plan.rows] == [("BKS-01", 2), ("BKS-02", 1)]
    assert plan.rows[0].target_key == "WELL:BKS-01"
    assert plan.rows[0].depth_range == (1020.0, 1030.0)
    assert "6 points" not in plan.rows[0].notes[0] and "4 points on 2 curves" in plan.rows[0].notes[0]
    assert plan.blockers() == []
    assert plan.changes() == 2


def test_pc_unit_and_system_are_blockers_until_chosen(tmp_path):
    text = ("Well,Sample,Depth (ft),Porosity,Perm,Pc,Sw\n"
            "BKS-01,P1,1020,0.2,100,10,0.9\nBKS-01,P1,1020,0.2,100,100,0.3\n")
    path = write(tmp_path, text)
    wells = [ref("BKS-01")]
    plan = plan_for(path, wells)
    assert "Choose the Pc unit" in plan.blockers()
    assert "Choose the fluid system" in plan.blockers()
    with pytest.raises(ValueError, match="Pc unit"):
        build_parts(plan, plan.wells)
    both = plan_for(path, wells, pc_unit="kpa", system="air-brine")
    assert both.blockers() == []
    part = build_parts(both, both.wells)["WELL:BKS-01"]
    assert part.data["PC_PSI"].iloc[0] == pytest.approx(1.450377)
    record = import_record(both, both.rows[0])
    assert record["pc_unit"] == "kpa" and record["system"] == "air-brine"
    assert record["porosity_scale"] == "fraction" and record["depth_unit"] == "FT"


def test_one_to_one_rule_blocks_two_file_wells_on_one_well(tmp_path):
    plan = plan_for(write(tmp_path, PC), [ref("BKS-01"), ref("BKS-02")])
    plan.set_target(1, "WELL:BKS-01")
    assert any("assigned to the same well" in b for b in plan.blockers())
    plan.set_action(1, "skip")
    assert plan.blockers() == []


def test_keep_and_replace_on_a_well_with_pc_curves(tmp_path):
    path = write(tmp_path, PC)
    existing = WellRef(key="WELL:BKS-01", display_name="BKS-01", well_info={"well_name": "BKS-01"},
                       log_top=0.0, log_bottom=10000.0, existing_count=3,
                       existing_path=str(tmp_path / "other.csv"))
    plan = plan_for(path, [existing, ref("BKS-02")])
    assert plan.rows[0].existing == "3 Pc curves (other.csv)"
    assert plan.rows[0].action == "keep"
    assert "WELL:BKS-01" not in build_parts(plan, plan.wells)
    plan.set_action(0, "replace")
    assert "WELL:BKS-01" in build_parts(plan, plan.wells)


def test_porosity_and_permeability_come_from_the_wells_core(tmp_path):
    text = ("Well,Sample,Depth (ft),Pc (psi),Sw,System\n"
            "BKS-01,P1,1020.2,10,0.9,air-brine\nBKS-01,P1,1020.2,100,0.3,air-brine\n"
            "BKS-02,P1,1020.3,10,0.9,air-brine\nBKS-02,P1,1020.3,100,0.3,air-brine\n")
    core = StubCore([1020.0], [0.2], [100.0])
    wells = [ref("BKS-01", core=core), ref("BKS-02", core=core)]
    plan = plan_for(write(tmp_path, text), wells)
    assert any("without porosity or permeability" in n for n in plan.rows[0].notes)
    parts = build_parts(plan, plan.wells)
    assert parts["WELL:BKS-01"].data["PHI"].iloc[0] == pytest.approx(0.2)
    assert parts["WELL:BKS-02"].data["K"].iloc[0] == pytest.approx(100.0)
    # Only the sample 20 ft from any core stays incomplete and is excluded.
    far = plan_for(write(tmp_path, text.replace("1020.3,", "1060,"), "far.csv"),
                   [ref("BKS-01", core=core), ref("BKS-02", core=core)])
    with pytest.raises(ValueError, match="BKS-02"):
        build_parts(far, far.wells)


def test_a_well_with_no_usable_sample_fails_the_whole_build(tmp_path):
    text = ("Well,Sample,Depth (ft),Pc (psi),Sw,System\n"
            "BKS-01,P1,1020,10,0.9,air-brine\nBKS-01,P1,1020,100,0.3,air-brine\n")
    plan = plan_for(write(tmp_path, text), [ref("BKS-01")])
    with pytest.raises(ValueError, match="Could not build the data for BKS-01"):
        build_parts(plan, plan.wells)


def test_tvd_depth_needs_confirmation(tmp_path):
    text = PC.replace("Depth (ft)", "TVD (ft)")
    path = write(tmp_path, text)
    plan = plan_for(path, [ref("BKS-01"), ref("BKS-02")])
    assert "Confirm that TVD Pc depths may be used" in plan.blockers()
    with pytest.raises(ValueError, match="TVD Pc"):
        build_parts(plan, plan.wells)
    assert plan_for(path, [ref("BKS-01")], tvd_confirmed=True).blockers() == []


def test_a_file_without_depth_needs_no_depth_unit(tmp_path):
    text = ("Well,Sample,Porosity,Perm,Pc (psi),Sw,System\n"
            "BKS-01,P1,0.2,100,10,0.9,air-brine\nBKS-01,P1,0.2,100,100,0.3,air-brine\n")
    plan = plan_for(write(tmp_path, text), [ref("BKS-01")])
    assert plan.effective_unit == "FT" and plan.blockers() == []
    assert plan.rows[0].depth_range is None


def test_porosity_scale_override_per_well(tmp_path):
    text = PC.replace("0.20,100", "20,100").replace("0.12,2,", "12,2,")
    plan = plan_for(write(tmp_path, text), [ref("BKS-01"), ref("BKS-02")])
    assert plan.rows[0].porosity_scale == "percent"
    forced = plan_for(write(tmp_path, text), [ref("BKS-01")],
                      porosity_scales={"BKS-01": "fraction"})
    assert forced.rows[0].porosity_scale == "fraction"
    assert any("without porosity or permeability" in n for n in forced.rows[0].notes)


def test_a_file_without_a_well_column_has_no_plan(tmp_path):
    text = "Sample,Depth (ft),Porosity,Perm,Pc (psi),Sw,System\nP1,1020,0.2,100,10,0.9,air-brine\n"
    path = write(tmp_path, text)
    with pytest.raises(ValueError, match="no well column"):
        plan_for(path, [ref("BKS-01")])


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------
def pick(combo, data):
    index = combo.findData(data)
    assert index >= 0, f"{data!r} not in combo"
    combo.setCurrentIndex(index)
    combo.activated.emit(index)


def make(qtbot, path, wells, **opts):
    dialog = MultiWellImportDialog("pc", path, wells, options=ImportOptions(kind="pc", **opts))
    qtbot.addWidget(dialog)
    return dialog


def test_dialog_roles_and_controls(qtbot, tmp_path):
    dialog = make(qtbot, write(tmp_path, PC), [ref("BKS-01"), ref("BKS-02")])
    assert set(dialog._column_combos) == {"well", "sample", "depth", "pc", "sw", "porosity",
                                          "permeability"}
    assert dialog._column_combos["pc"].currentData() == "Pc (psi)"
    assert dialog._column_combos["sw"].currentData() == "Sw"
    assert dialog.pc_unit_combo.currentData() == "psi"
    assert dialog.ok_button.isEnabled()
    assert dialog.table.cellWidget(0, dialog._col["Porosity"]) is not None
    assert not dialog.pc_unit_combo.isHidden() and not dialog.system_combo.isHidden()
    assert dialog.windowTitle() == "Assign capillary pressure data"


def test_dialog_ok_waits_for_the_unit_and_the_system(qtbot, tmp_path):
    text = ("Well,Sample,Depth (ft),Porosity,Perm,Pc,Sw\n"
            "BKS-01,P1,1020,0.2,100,10,0.9\nBKS-01,P1,1020,0.2,100,100,0.3\n")
    dialog = make(qtbot, write(tmp_path, text), [ref("BKS-01")])
    assert not dialog.ok_button.isEnabled()
    assert "Choose the Pc unit" in dialog.ok_button.toolTip()
    pick(dialog.pc_unit_combo, "bar")
    assert not dialog.ok_button.isEnabled()
    assert "Choose the fluid system" in dialog.ok_button.toolTip()
    pick(dialog.system_combo, "hg-air")
    assert dialog.ok_button.isEnabled()
    assert dialog.plan.options.pc_unit == "bar" and dialog.plan.options.system == "hg-air"


def test_dialog_tvd_gate(qtbot, tmp_path):
    dialog = make(qtbot, write(tmp_path, PC.replace("Depth (ft)", "TVD (ft)")), [ref("BKS-01")])
    assert not dialog.ok_button.isEnabled()
    assert not dialog.tvd_check.isHidden()
    dialog.tvd_check.click()
    assert dialog.ok_button.isEnabled()


def test_dialog_porosity_scale_combo_reparses(qtbot, tmp_path):
    text = PC.replace("0.20,100", "20,100").replace("0.12,2,", "12,2,")
    dialog = make(qtbot, write(tmp_path, text), [ref("BKS-01"), ref("BKS-02")])
    combo = dialog._scale_combos[0]
    assert combo.currentData() == "percent"
    pick(combo, "fraction")
    assert dialog.plan.rows[0].porosity_scale == "fraction"


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
@pytest.fixture
def window(qtbot):
    widget = MainWindow()
    qtbot.addWidget(widget)
    yield widget
    widget.close()


@pytest.fixture
def three_wells(window, tmp_path):
    for name, well in (("a.las", "BKS-01"), ("b.las", "BKS-02"), ("c.las", "BKS-03")):
        window._load_single_las(_write(tmp_path, name, well=well))
    return window


@pytest.fixture
def dialogs(monkeypatch):
    seen = []
    state = {"result": ACCEPTED, "edit": None}

    def fake_exec(self):
        seen.append(self)
        if state["edit"]:
            state["edit"](self)
        return state["result"]

    monkeypatch.setattr(MultiWellImportDialog, "exec", fake_exec)
    return type("Dialogs", (), {"seen": seen, "state": state})


def well(window, name):
    return next(ds for ds in window.model.project.wells if ds.display_name == name)


@pytest.fixture
def pc_signal(window):
    calls = []
    if hasattr(window.model.project, "pc_changed"):
        window.model.project.pc_changed.connect(lambda keys: calls.append(list(keys)))
    return calls


def test_pc_actions_exist_and_follow_the_loaded_wells(window, tmp_path):
    assert "open_pc" in window.actions_ and "open_pc_multi" in window.actions_
    assert window.actions_["open_pc"].isEnabled()
    assert not window.actions_["open_pc_multi"].isEnabled()
    window._load_single_las(_write(tmp_path, "a.las", well="BKS-01"))
    assert window.actions_["open_pc_multi"].isEnabled()
    labels = [a.text() for a in window._menus["file"].actions()]
    assert "Open Pc Data…" in labels and "Open Pc Data (Multi-Well)…" in labels
    assert "open_pc" in window._LOAD_ACTIONS and "open_pc_multi" in window._LOAD_ACTIONS


def test_menu_action_opens_the_dialog_and_assigns(three_wells, tmp_path, monkeypatch, dialogs,
                                                  pc_signal):
    path = write(tmp_path, PC)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (path, "")))
    core_before = three_wells.model.core_data
    three_wells.actions_["open_pc_multi"].trigger()
    assert len(dialogs.seen) == 1 and dialogs.seen[0].kind == "pc"
    first, second = well(three_wells, "BKS-01"), well(three_wells, "BKS-02")
    assert list(first.pc_data.curves()) == ["P1", "P2"]
    assert list(second.pc_data.curves()) == ["P1"]
    assert first.pc_path == path and first.pc_import["pc_unit"] == "psi"
    assert first.pc_sha256 and well(three_wells, "BKS-03").pc_data is None
    assert three_wells.model.core_data is core_before
    assert all(ds.core_data is None for ds in three_wells.model.project.wells)
    assert three_wells.model.dirty
    if hasattr(Project, "pc_changed"):
        assert len(pc_signal) == 1 and sorted(pc_signal[0]) == sorted(
            [first.key, second.key])


def test_pc_import_does_not_mark_wells_stale(three_wells, tmp_path, dialogs):
    for ds in three_wells.model.project.wells:
        ds.calculated = True
        ds.run_params_hash = three_wells.model.well_params_hash(ds)
        ds.stale = False
    three_wells._import_multi_well("pc", write(tmp_path, PC))
    assert not any(ds.stale for ds in three_wells.model.project.wells)


def test_cancel_changes_nothing(three_wells, tmp_path, dialogs, pc_signal):
    dialogs.state["result"] = REJECTED
    three_wells._import_multi_well("pc", write(tmp_path, PC))
    assert all(ds.pc_data is None for ds in three_wells.model.project.wells)
    assert pc_signal == []


def test_apply_is_atomic_when_one_well_cannot_be_built(three_wells, tmp_path, dialogs, pc_signal):
    text = ("Well,Sample,Depth (ft),Pc (psi),Sw,System\n"
            "BKS-01,P1,1020,10,0.9,air-brine\nBKS-01,P1,1020,100,0.3,air-brine\n"
            "BKS-02,P1,1040,10,0.9,air-brine\nBKS-02,P1,1040,100,0.3,air-brine\n")
    # BKS-02 gets porosity and permeability from core; BKS-01 has no core: its build fails.
    second = well(three_wells, "BKS-02")
    second.core_data = StubCore([1040.0], [0.2], [50.0])
    three_wells._import_multi_well("pc", write(tmp_path, text))
    assert "Nothing was changed" in three_wells.banner.message_label.text()
    assert all(ds.pc_data is None for ds in three_wells.model.project.wells)
    assert pc_signal == []


def test_a_well_with_core_completes_missing_phi_and_k(three_wells, tmp_path, dialogs):
    text = ("Well,Sample,Depth (ft),Pc (psi),Sw,System\n"
            "BKS-01,P1,1020.2,10,0.9,air-brine\nBKS-01,P1,1020.2,100,0.3,air-brine\n")
    well(three_wells, "BKS-01").core_data = StubCore([1020.0], [0.2], [100.0])
    three_wells._import_multi_well("pc", write(tmp_path, text))
    data = well(three_wells, "BKS-01").pc_data.data
    assert data["PHI"].iloc[0] == pytest.approx(0.2) and data["K"].iloc[0] == pytest.approx(100.0)


def test_single_well_loader_routes_a_well_column_file_to_the_dialog(three_wells, tmp_path, dialogs):
    three_wells._on_pc_file_selected(write(tmp_path, PC))
    assert len(dialogs.seen) == 1 and dialogs.seen[0].kind == "pc"
    assert list(well(three_wells, "BKS-01").pc_data.curves()) == ["P1", "P2"]


def test_single_well_loader_attaches_to_the_active_well(three_wells, tmp_path, pc_signal):
    text = ("Sample,Depth (ft),Porosity,Perm,Pc (psi),Sw,System\n"
            "P1,1020,0.2,100,10,0.9,air-brine\nP1,1020,0.2,100,100,0.3,air-brine\n")
    path = write(tmp_path, text, "single.csv")
    three_wells._on_pc_file_selected(path)
    active = three_wells.model.active_well
    assert active.display_name == "BKS-03"
    assert list(active.pc_data.curves()) == ["P1"]
    assert active.pc_path == path and active.pc_sha256
    assert active.pc_import["pc_unit"] == "psi"
    assert all(ds.pc_data is None for ds in three_wells.model.project.wells if ds is not active)
    if hasattr(Project, "pc_changed"):
        assert pc_signal == [[active.key]]


def test_single_well_loader_asks_for_a_missing_unit_and_system(three_wells, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QInputDialog

    text = ("Sample,Depth (ft),Porosity,Perm,Pc,Sw\n"
            "P1,1020,0.2,100,10,0.9\nP1,1020,0.2,100,100,0.3\n")
    asked = []

    def fake_get_item(parent, title, label, items, current, editable):
        asked.append(title)
        return ("kPa" if title == "Pc unit" else "Hg-air (MICP)"), True

    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(fake_get_item))
    three_wells._on_pc_file_selected(write(tmp_path, text, "ask.csv"))
    assert asked == ["Pc unit", "Fluid system"]
    data = three_wells.model.active_well.pc_data.data
    assert data["PC_PSI"].iloc[0] == pytest.approx(1.450377)
    assert data["SYSTEM"].iloc[0] == "hg-air"
    assert three_wells.model.active_well.pc_import["system"] == "hg-air"


def test_single_well_loader_cancelled_question_loads_nothing(three_wells, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QInputDialog

    text = "Sample,Depth (ft),Porosity,Perm,Pc,Sw,System\nP1,1020,0.2,100,10,0.9,air-brine\n"
    monkeypatch.setattr(QInputDialog, "getItem",
                        staticmethod(lambda *a, **k: ("psi", False)))
    three_wells._on_pc_file_selected(write(tmp_path, text, "ask.csv"))
    assert three_wells.model.active_well.pc_data is None


def test_multi_well_action_on_a_file_without_a_well_column_says_so(three_wells, tmp_path, dialogs):
    text = "Sample,Depth (ft),Porosity,Perm,Pc (psi),Sw,System\nP1,1020,0.2,100,10,0.9,air-brine\n"
    three_wells._import_multi_well("pc", write(tmp_path, text, "plain.csv"))
    assert not dialogs.seen
    assert "no well column" in three_wells.banner.message_label.text()
    assert "Open Pc Data" in three_wells.banner.message_label.text()
