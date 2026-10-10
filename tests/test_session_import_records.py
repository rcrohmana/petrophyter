"""Session 2.1: import records replay a multi-well import exactly (spec 3.10)."""

import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QDialog, QFileDialog

from tests.test_multiwell_loading import _write
from ui.main_window import MainWindow
from ui.widgets.well_import_dialog import MultiWellImportDialog


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A modal box would block the offscreen test run; fail loudly instead."""
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


TOPS = ("Well,Formation,Top (ft),Bottom (ft)\n"
        "BKS-1,Upper,1005,1030\nBKS-1,Lower,1030,1055\nBKS-02,Upper,1010,1040\n")


def key(window, name):
    return next(ds.key for ds in window.model.project.wells if ds.display_name == name)


def import_with_manual_mapping(window, path, file_well="BKS-1", target="BKS-01", monkeypatch=None):
    """Run the multi-well import with the file well mapped by hand (no auto match exists)."""
    def edit(dialog):
        index = next(i for i, r in enumerate(dialog.plan.rows) if r.file_well == file_well)
        assert dialog.plan.rows[index].target_key is None      # the names differ: no auto match
        dialog.plan.set_target(index, key(window, target))

    monkeypatch.setattr(MultiWellImportDialog, "exec",
                        lambda self: (edit(self), QDialog.DialogCode.Accepted)[1])
    window._import_multi_well("tops", path)


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
    return json.loads(session.read_text(encoding="utf-8"))


def test_manual_mapping_survives_a_session_round_trip(two_wells, tmp_path, monkeypatch):
    window = two_wells
    path = tmp_path / "tops.csv"
    path.write_text(TOPS)
    import_with_manual_mapping(window, str(path), monkeypatch=monkeypatch)
    first = window.model.project.get(key(window, "BKS-01"))
    assert [fm.name for fm in first.formation_tops.formations] == ["Upper", "Lower"]

    saved = save_and_reload(window, tmp_path, monkeypatch)
    assert saved["_session_version"] == "2.1"
    record = next(w for w in saved["wells"] if w["display_name"] == "BKS-01")["tops_import"]
    assert record["spellings"] == ["BKS-1"] and record["columns"]["top"] == "Top (ft)"
    assert record["depth_unit"] == "FT" and record["last_bottom"] == "log_bottom"

    project = window.model.project
    restored = project.get(key(window, "BKS-01"))
    assert [(fm.name, fm.top_depth, fm.bottom_depth) for fm in restored.formation_tops.formations] == [
        ("Upper", 1005.0, 1030.0), ("Lower", 1030.0, 1055.0)]
    assert restored.tops_import["file_well"] == "BKS-1"
    assert [fm.name for fm in project.get(key(window, "BKS-02")).formation_tops.formations] == ["Upper"]
    assert "no longer matches" not in window.banner.message_label.text()


def test_the_replay_uses_the_recorded_unit_and_columns(two_wells, tmp_path, monkeypatch):
    window = two_wells
    path = tmp_path / "tops.csv"
    path.write_text("Well,Surface,MD,Bottom (m)\nBKS-1,Upper,310,320\nBKS-02,Upper,310,320\n")
    import_with_manual_mapping(window, str(path), monkeypatch=monkeypatch)
    first = window.model.project.get(key(window, "BKS-01"))
    assert first.formation_tops.formations[0].top_depth == pytest.approx(310 * 3.28084)
    assert first.tops_import["columns"]["top"] == "MD"
    save_and_reload(window, tmp_path, monkeypatch)
    restored = window.model.project.get(key(window, "BKS-01"))
    assert restored.formation_tops.formations[0].top_depth == pytest.approx(310 * 3.28084)
    assert restored.tops_import["depth_unit"] == "M"


def test_an_edited_file_falls_back_to_identity_matching_with_a_note(two_wells, tmp_path, monkeypatch):
    window = two_wells
    path = tmp_path / "tops.csv"
    path.write_text(TOPS)
    import_with_manual_mapping(window, str(path), monkeypatch=monkeypatch)
    window.session_service.save_session(window.model, str(tmp_path / "keep.json"))
    path.write_text(TOPS.replace("BKS-1,", "BKS-01,"))      # the spelling in the record is gone
    save_and_reload(window, tmp_path, monkeypatch)
    project = window.model.project
    assert [ds.display_name for ds in project.wells] == ["BKS-01", "BKS-02"]
    restored = project.get(key(window, "BKS-01"))
    assert [fm.name for fm in restored.formation_tops.formations] == ["Upper", "Lower"]
    assert restored.tops_import is None               # matched by identity, not replayed
    assert "BKS-01: the stored import no longer matches the tops file" in window.banner.message_label.text()


def test_an_edited_file_without_the_well_does_not_fail_the_restore(two_wells, tmp_path, monkeypatch):
    window = two_wells
    path = tmp_path / "tops.csv"
    path.write_text(TOPS)
    import_with_manual_mapping(window, str(path), monkeypatch=monkeypatch)
    path.write_text(TOPS.replace("BKS-1,", "ZZZ-9,"))
    save_and_reload(window, tmp_path, monkeypatch)
    project = window.model.project
    assert [ds.display_name for ds in project.wells] == ["BKS-01", "BKS-02"]
    assert project.get(key(window, "BKS-01")).formation_tops is None
    text = window.banner.message_label.text()
    assert "no longer matches" in text and "has no tops for well BKS-01" in text


def test_a_session_without_import_records_still_loads(two_wells, tmp_path, monkeypatch):
    window = two_wells
    path = tmp_path / "tops.csv"
    path.write_text(TOPS.replace("BKS-1,", "BKS-01,"))
    from services.session_service import attach_tops
    first = window.model.project.get(key(window, "BKS-01"))
    assert attach_tops(first, str(path)) == []

    def downgrade(data):
        data["_session_version"] = "2.0"
        for entry in data["wells"]:
            entry.pop("tops_import", None)
            entry.pop("core_import", None)

    save_and_reload(window, tmp_path, monkeypatch, mutate=downgrade)
    restored = window.model.project.get(key(window, "BKS-01"))
    assert [fm.name for fm in restored.formation_tops.formations] == ["Upper", "Lower"]
    assert restored.tops_import is None
    assert "no longer matches" not in window.banner.message_label.text()


def test_attach_tops_extends_a_last_formation_without_a_bottom(two_wells, tmp_path):
    from services.session_service import attach_tops

    path = tmp_path / "tops.txt"
    path.write_text("Formation\tTop (ft)\nA\t1005\nB\t1030\n")
    ds = two_wells.model.project.get(key(two_wells, "BKS-01"))
    assert attach_tops(ds, str(path)) == []
    assert ds.formation_tops.formations[-1].bottom_depth == pytest.approx(float(ds.las_data["DEPTH"].max()))


def test_a_shared_file_is_parsed_once_per_restore(two_wells, tmp_path, monkeypatch):
    window = two_wells
    path = tmp_path / "tops.csv"
    path.write_text(TOPS.replace("BKS-1,", "BKS-01,"))
    monkeypatch.setattr(MultiWellImportDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    window._import_multi_well("tops", str(path))
    assert all(ds.tops_import for ds in window.model.project.wells)

    import modules.well_import as well_import
    calls = []
    original = well_import.parse_import_file
    monkeypatch.setattr(well_import, "parse_import_file",
                        lambda *a, **k: (calls.append(a[0]), original(*a, **k))[1])
    save_and_reload(window, tmp_path, monkeypatch)
    assert len(calls) == 1
    assert all(ds.formation_tops is not None for ds in window.model.project.wells)


def test_import_records_are_not_part_of_the_parameter_hash(two_wells, tmp_path, monkeypatch):
    window = two_wells
    path = tmp_path / "tops.csv"
    path.write_text(TOPS)
    import_with_manual_mapping(window, str(path), monkeypatch=monkeypatch)
    ds = window.model.project.get(key(window, "BKS-01"))
    before = window.model.well_params_hash(ds)
    ds.tops_import = dict(ds.tops_import, columns={"top": "Something else"})
    ds.core_import = {"anything": 1}
    assert window.model.well_params_hash(ds) == before
