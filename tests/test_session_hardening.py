"""Session hardening (P0-Hardening H1, H4 shape check, H5 clamps; P0 I10 app version)."""

import json
import os
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from models.app_model import AppModel
from modules.las_handler import MERGE_POLICY, LASHandler
from services import session_service
from services.load_service import build_well, parse_file
from services.session_service import (
    SessionService, app_version_notes, clamp_merge, session_app_version, session_level_notes,
    validate_session,
)
from tests.test_session_v2 import _write
from version import version_tuple


def _merged_well(model, tmp_path, tag, step, gap, recipe=True):
    """A two-file merged well built at ``step``; its recipe is set by hand when ``recipe``."""
    files = [
        parse_file(_write(tmp_path, f"{tag}1.las", well=tag, top=1000.0, bottom=1040.0)),
        parse_file(_write(tmp_path, f"{tag}2.las", well=tag, top=1030.0, bottom=1080.0)),
    ]
    result = LASHandler().merge_las_files(
        [f.parser for f in files], file_identifiers=[f.name for f in files],
        step_ft=step, gap_limit_ft=gap)
    ds = build_well(files, result)
    if recipe:
        ds.merge_recipe = {"step": step, "gap_limit": gap, "policy": MERGE_POLICY}
    model.add_well(ds, activate=False)
    return ds


def _save(model, tmp_path):
    path = str(tmp_path / "s.json")
    assert SessionService().save_session(model, path)
    with open(path, encoding="utf-8") as handle:
        return path, json.load(handle)


def _restore(data):
    model = AppModel()
    svc = SessionService()
    svc.apply_session_to_model(model, data)
    notes = svc.restore_wells(model, data)
    return model, notes


# ---- I10 ----
def test_app_version_is_written_and_read(tmp_path):
    model = AppModel()
    _, data = _save(model, tmp_path)
    assert data["_app_version"] == session_service.APP_VERSION
    assert session_app_version(data) == session_service.APP_VERSION
    assert session_app_version({}) is None


def test_version_tuple_compares_numerically():
    assert version_tuple("1.10.0") > version_tuple("1.9.0")


def test_no_notice_while_the_running_app_is_older_than_the_calc_change(monkeypatch):
    monkeypatch.setattr(session_service, "APP_VERSION", "1.7.1")
    assert app_version_notes({}) == []
    assert session_level_notes({"_session_version": "2.1"}) == []


def test_old_or_unversioned_session_gets_the_notice_from_1_7_2(monkeypatch):
    monkeypatch.setattr(session_service, "APP_VERSION", "1.7.2")
    note, = app_version_notes({})
    assert "Saved by Petrophyter 1.7.0 or older" in note and "Calculations changed in 1.7.2" in note
    note, = app_version_notes({"_app_version": "1.7.1"})
    assert "Saved by Petrophyter 1.7.1" in note
    assert app_version_notes({"_app_version": "1.7.2"}) == []
    assert app_version_notes({"_app_version": "1.10.0"}) == []


# ---- H1 ----
def test_each_well_keeps_its_own_merge_recipe(tmp_path):
    model = AppModel()
    first = _merged_well(model, tmp_path, "ALPHA", 0.25, 3.0)
    second = _merged_well(model, tmp_path, "BETA", 1.0, 8.0)
    assert len(first.las_data) != len(second.las_data)
    model.merge_step, model.merge_gap_limit = 0.6, 20.0        # a third, unrelated global value
    _, data = _save(model, tmp_path)
    saved = {w["display_name"]: w for w in data["wells"]}
    assert (saved["ALPHA"]["merge_step"], saved["ALPHA"]["merge_gap_limit"]) == (0.25, 3.0)
    assert (saved["BETA"]["merge_step"], saved["BETA"]["merge_gap_limit"]) == (1.0, 8.0)
    assert saved["ALPHA"]["merge_policy"] == saved["BETA"]["merge_policy"] == MERGE_POLICY

    restored, notes = _restore(data)
    assert notes == []
    by_name = {ds.display_name: ds for ds in restored.project.wells}
    assert len(by_name["ALPHA"].las_data) == len(first.las_data)
    assert len(by_name["BETA"].las_data) == len(second.las_data)
    assert by_name["ALPHA"].merge_recipe["step"] == 0.25
    assert by_name["BETA"].merge_recipe["gap_limit"] == 8.0


def test_a_single_file_well_stores_no_merge_recipe(tmp_path):
    model = AppModel()
    model.add_well(build_well([parse_file(_write(tmp_path, "a.las", well="ALPHA"))]), activate=False)
    model.merge_step = 0.9
    _, data = _save(model, tmp_path)
    assert not {"merge_step", "merge_gap_limit", "merge_policy"} & set(data["wells"][0])


def test_a_merged_well_built_before_the_recipe_existed_falls_back_to_the_model(tmp_path):
    model = AppModel()
    _merged_well(model, tmp_path, "ALPHA", 0.5, 5.0, recipe=False)
    model.merge_step, model.merge_gap_limit = 0.5, 5.0
    _, data = _save(model, tmp_path)
    assert data["wells"][0]["merge_step"] == 0.5 and data["wells"][0]["merge_policy"] == MERGE_POLICY


def test_a_session_without_merge_policy_adds_the_note_naming_both_causes(tmp_path):
    model = AppModel()
    ds = _merged_well(model, tmp_path, "ALPHA", 0.5, 5.0)
    _, data = _save(model, tmp_path)
    del data["wells"][0]["merge_policy"]
    restored, notes = _restore(data)
    note, = notes
    assert "ALPHA" in note and "merge rules" in note and "step of a later merge" in note
    assert "0.5 ft" in note and f"({len(ds.las_data)} rows)" in note

    data["wells"][0]["merge_policy"] = MERGE_POLICY            # same policy: nothing to say
    assert _restore(data)[1] == []
    data["wells"][0]["merge_policy"] = MERGE_POLICY - 1        # lower policy: the note again
    assert len(_restore(data)[1]) == 1


def test_core_depth_unit_comes_from_the_dataset_only(tmp_path):
    model = AppModel()
    model.add_well(build_well([parse_file(_write(tmp_path, "a.las", well="ALPHA"))]), activate=False)
    model.core_depth_unit = "M"
    _, data = _save(model, tmp_path)
    assert data["wells"][0]["core_depth_unit"] is None
    model.project.wells[0].core_depth_unit = "FT"
    assert _save(model, tmp_path)[1]["wells"][0]["core_depth_unit"] == "FT"


class _Parsed:
    def __init__(self, tvd):
        self.depth_is_tvd = tvd
        self.well_kind = "name"


def _spy_replay(monkeypatch, tvd):
    """Patch the import machinery so only the TVD gate of ``replay_import`` is exercised."""
    import modules.well_import as well_import

    reached = []
    monkeypatch.setattr(well_import, "parse_import_file", lambda path, options: _Parsed(tvd))
    monkeypatch.setattr(well_import, "well_refs", lambda project, kind: [])

    def stop(parsed, path, wells, options):
        reached.append(options.tvd_confirmed)
        raise RuntimeError("stop here")

    monkeypatch.setattr(well_import, "build_import_plan", stop)
    return reached


@pytest.mark.parametrize("kind", ["tops", "core"])
def test_tvd_replay_needs_the_stored_confirmation(monkeypatch, kind):
    well = types.SimpleNamespace(key="K", display_name="K", well_info={})
    for record in ({}, {"tvd_confirmed": False}):          # absent (older session) or declined
        reached, notes = _spy_replay(monkeypatch, True), []
        assert not session_service.replay_import(well, kind, "x.txt", record, notes=notes)
        assert reached == [] and "TVD depth column" in notes[0]

    reached, notes = _spy_replay(monkeypatch, True), []
    session_service.replay_import(well, kind, "x.txt", {"tvd_confirmed": True}, notes=notes)
    assert reached == [True] and notes == []                # past the gate (the spy stops it)

    reached, notes = _spy_replay(monkeypatch, False), []
    session_service.replay_import(well, kind, "x.txt", {}, notes=notes)
    assert reached == [False] and notes == []               # not TVD: as before


def test_a_refused_tvd_import_is_not_retried_by_well_name(monkeypatch):
    calls = []

    def refuse(well, kind, path, record, cache=None, notes=None):
        notes.append("the core file now has a TVD depth column; import it again to confirm.")
        return False

    monkeypatch.setattr(session_service, "replay_import", refuse)
    monkeypatch.setattr(session_service, "attach_core", lambda *a, **k: calls.append(a) or [])
    notes = session_service._restore_core(object(), "x.txt", {"file_well": "A"}, "Auto", {})
    assert calls == [] and "TVD depth column" in notes[0]


# ---- H5 (session side) ----
def test_clamp_merge_limits_both_values_and_names_the_change():
    assert clamp_merge(0.5, 5.0) == (0.5, 5.0, [])
    step, gap, notes = clamp_merge(1e-6, 500, "ALPHA")
    assert (step, gap) == (0.1, 50.0) and len(notes) == 2 and notes[0].startswith("ALPHA:")


def test_app_model_setters_clamp():
    model = AppModel()
    model.merge_step, model.merge_gap_limit = 1e-6, 0
    assert (model.merge_step, model.merge_gap_limit) == (0.1, 1.0)
    model.merge_step, model.merge_gap_limit = 7, 1e9
    assert (model.merge_step, model.merge_gap_limit) == (1.0, 50.0)
    model.merge_step = float("nan")                         # not a number: keep the old value
    assert model.merge_step == 1.0


def test_a_wild_session_step_is_clamped_on_restore_with_a_note(tmp_path):
    model = AppModel()
    ds = _merged_well(model, tmp_path, "ALPHA", 0.5, 5.0)
    _, data = _save(model, tmp_path)
    data["wells"][0]["merge_step"] = 1e-6
    data["merge_step"] = data["global_params"]["merge_step"] = 1e-6
    restored, notes = _restore(data)
    assert restored.merge_step == 0.1
    well = restored.project.wells[0]
    assert well.merge_recipe["step"] == 0.1
    assert any("ALPHA: merge step" in n for n in notes)
    assert any("merge step" in n for n in session_level_notes(data))
    assert len(well.las_data) > len(ds.las_data)            # the step really was 0.1, not 1e-6


# ---- H4 shape check ----
@pytest.mark.parametrize("data, fragment", [
    ([], "JSON object"),
    ({"wells": "nope"}, "wells is not a list"),
    ({"wells": ["x"]}, "not an object"),
    ({"wells": [{"sources": "a.las"}]}, "sources"),
    ({"wells": [{"sources": [1]}]}, "sources"),
    ({"merge_step": "wide"}, "merge_step"),
    ({"wells": [{"sources": [], "merge_gap_limit": float("inf")}]}, "merge_gap_limit"),
])
def test_validate_session_rejects_bad_shapes(data, fragment):
    problems = validate_session(data)
    assert problems and fragment in problems[0]


def test_validate_session_accepts_real_and_empty_sessions(tmp_path):
    model = AppModel()
    _merged_well(model, tmp_path, "ALPHA", 0.5, 5.0)
    assert validate_session(_save(model, tmp_path)[1]) == []
    assert validate_session({"_session_version": "2.1", "wells": []}) == []
    assert validate_session({"rw": 0.05}) == []
