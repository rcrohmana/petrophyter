"""Pc data in a session: import records replay, a missing file keeps the rest (no fits here)."""

import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QDialog, QFileDialog

from tests.test_multiwell_loading import _write
from ui.main_window import MainWindow
from ui.widgets.well_import_dialog import MultiWellImportDialog

PC = """Well,Sample,Depth (m),Porosity (%),Perm (mD),Pc (kPa),S_Hg (%),System
BKS-1,P1,310,20,100,100,10,hg-air
BKS-1,P1,310,20,100,1000,70,hg-air
BKS-02,P1,311,18,50,100,15,hg-air
BKS-02,P1,311,18,50,1000,80,hg-air
"""


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    def refuse(*args, **kwargs):
        raise AssertionError(f"unexpected dialog: {args[1:3]}")

    for name in ("warning", "critical", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(refuse))


@pytest.fixture
def window(qtbot):
    widget = MainWindow()
    qtbot.addWidget(widget)
    yield widget
    widget.close()


@pytest.fixture
def two_wells(window, tmp_path):
    window._load_single_las(_write(tmp_path, "a.las", well="BKS-01"))
    window._load_single_las(_write(tmp_path, "b.las", well="BKS-02"))
    return window


def well(window, name):
    return next(ds for ds in window.model.project.wells if ds.display_name == name)


def import_pc(window, path, monkeypatch):
    """Multi-well import with the file well BKS-1 mapped by hand onto BKS-01."""
    def edit(dialog):
        index = next(i for i, r in enumerate(dialog.plan.rows) if r.file_well == "BKS-1")
        assert dialog.plan.rows[index].target_key is None
        dialog.plan.set_target(index, well(window, "BKS-01").key)

    monkeypatch.setattr(MultiWellImportDialog, "exec",
                        lambda self: (edit(self), QDialog.DialogCode.Accepted)[1])
    window._import_multi_well("pc", path)


def wait_for_restore(window, timeout_ms=15000):
    from PyQt6.QtCore import QElapsedTimer
    from PyQt6.QtTest import QTest

    clock = QElapsedTimer()
    clock.start()
    while window._restore_worker is not None and clock.elapsed() < timeout_ms:
        QTest.qWait(10)
    assert window._restore_worker is None, "session restore did not finish"


def save_and_reload(window, tmp_path, monkeypatch, mutate=None):
    session = tmp_path / "s.json"
    assert window.session_service.save_session(window.model, str(session))
    if mutate:
        data = json.loads(session.read_text(encoding="utf-8"))
        mutate(data)
        session.write_text(json.dumps(data), encoding="utf-8")
    window.batch_runner.cancel()
    window.model.reset()
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(session), "")))
    window._on_load_session()
    wait_for_restore(window)
    return json.loads(session.read_text(encoding="utf-8"))


@pytest.fixture
def imported(two_wells, tmp_path, monkeypatch):
    path = tmp_path / "pc.csv"
    path.write_text(PC, encoding="utf-8")
    import_pc(two_wells, str(path), monkeypatch)
    assert list(well(two_wells, "BKS-01").pc_data.curves()) == ["P1"]
    return two_wells, path


def test_round_trip_replays_the_import_record(imported, tmp_path, monkeypatch):
    window, path = imported
    saved = save_and_reload(window, tmp_path, monkeypatch)
    entry = next(w for w in saved["wells"] if w["display_name"] == "BKS-01")
    assert entry["pc_path"] == str(path) and entry["pc_sha256"]
    record = entry["pc_import"]
    assert record["spellings"] == ["BKS-1"]
    assert record["pc_unit"] == "kpa" and record["depth_unit"] == "M"
    assert record["porosity_scale"] == "percent"

    restored = well(window, "BKS-01")
    data = restored.pc_data.data
    assert restored.pc_path == str(path) and restored.pc_sha256 == entry["pc_sha256"]
    assert restored.pc_import["file_well"] == "BKS-1"
    assert data["DEPTH"].iloc[0] == pytest.approx(310 * 3.28084)
    assert data["PC_PSI"].iloc[0] == pytest.approx(100 * 0.1450377)
    assert list(data["SW"]) == pytest.approx([0.9, 0.3])
    assert data["PHI"].iloc[0] == pytest.approx(0.2)
    assert list(well(window, "BKS-02").pc_data.curves()) == ["P1"]
    assert "no longer matches" not in window.banner.message_label.text()


def test_a_session_without_pc_has_no_pc_keys(two_wells, tmp_path, monkeypatch):
    saved = save_and_reload(two_wells, tmp_path, monkeypatch)
    for entry in saved["wells"]:
        assert not any(k.startswith("pc_") for k in entry)
    assert all(ds.pc_data is None for ds in two_wells.model.project.wells)


def test_a_missing_pc_file_is_noted_and_the_rest_loads(imported, tmp_path, monkeypatch):
    window, path = imported
    session = tmp_path / "s.json"
    window.session_service.save_session(window.model, str(session))
    path.unlink()
    window.batch_runner.cancel()
    window.model.reset()
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(session), "")))
    window._on_load_session()
    wait_for_restore(window)
    restored = well(window, "BKS-01")
    assert restored.pc_data is None
    assert restored.pc_path == str(path) and restored.pc_import["pc_unit"] == "kpa"
    assert "Pc file not found; fits kept, plots without points" in window.banner.message_label.text()


def test_an_edited_file_falls_back_to_well_name_matching(imported, tmp_path, monkeypatch):
    window, path = imported
    path.write_text(PC.replace("BKS-1,", "BKS-01,"), encoding="utf-8")   # the stored spelling is gone
    save_and_reload(window, tmp_path, monkeypatch)
    restored = well(window, "BKS-01")
    assert list(restored.pc_data.curves()) == ["P1"]
    assert restored.pc_data.pc_unit == "kpa"                            # the stored unit is reused
    assert "the stored import no longer matches the Pc file" in window.banner.message_label.text()


def test_a_changed_file_hash_is_reported(imported, tmp_path, monkeypatch):
    window, path = imported
    path.write_text(PC + "BKS-02,P1,311,18,50,2000,90,hg-air\n", encoding="utf-8")
    save_and_reload(window, tmp_path, monkeypatch, mutate=lambda d: None)
    # The session was saved with the hash taken at import; the file changed before reload.
    assert well(window, "BKS-02").pc_data is not None
    assert "changed since the session was saved" in window.banner.message_label.text()


def test_single_well_record_restores_through_the_file(two_wells, tmp_path, monkeypatch):
    text = ("Sample,Depth (ft),Porosity,Perm,Pc,Sw\n"
            "P1,1020,0.2,100,10,0.9\nP1,1020,0.2,100,100,0.3\n")
    path = tmp_path / "single.csv"
    path.write_text(text, encoding="utf-8")
    from PyQt6.QtWidgets import QInputDialog
    answers = {"Pc unit": "bar", "Fluid system": "Oil-brine"}
    monkeypatch.setattr(QInputDialog, "getItem",
                        staticmethod(lambda p, title, *a, **k: (answers[title], True)))
    two_wells._on_pc_file_selected(str(path))
    active = two_wells.model.active_well
    assert active.pc_data.pc_unit == "bar"
    saved = save_and_reload(two_wells, tmp_path, monkeypatch)
    assert next(w for w in saved["wells"] if w["key"] == active.key)["pc_import"]["system"] == "oil-brine"
    restored = well(two_wells, active.display_name)
    assert restored.pc_data.data["PC_PSI"].iloc[0] == pytest.approx(10 * 14.50377)
    assert restored.pc_data.data["SYSTEM"].iloc[0] == "oil-brine"
