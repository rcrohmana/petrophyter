"""Session v2.0: wells, overrides and zone entries round-trip (spec §4.9, §5.7)."""

import json
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from models.app_model import AppModel
from modules.las_handler import LASHandler
from services.load_service import build_well, parse_file
from services.session_service import SessionService, attach_tops, _json_safe

TOPS_TEXT = "Formation\tTop (ft)\tBottom (ft)\nUpper\t1000\t1030\nLower\t1030\t1080\n"


def _las_text(well, uwi="", top=1000.0, bottom=1060.0):
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
        " GR.GAPI : Gamma\n RHOB.G/CC : Density\n NPHI.V/V : Neutron\n RT.OHMM : Resistivity\n"
        "~A\n" + rows + "\n"
    )


def _write(tmp_path, name, **kwargs):
    path = tmp_path / name
    path.write_text(_las_text(**kwargs))
    return str(path)


def _load(model, tmp_path, specs, merge=None):
    """Add wells to ``model``; ``specs`` = [(file name, kwargs)] per well."""
    for names in specs:
        files = [parse_file(_write(tmp_path, n, **kw)) for n, kw in names]
        assert all(f.ok for f in files)
        result = None
        if len(files) > 1:
            result = LASHandler().merge_las_files(
                [f.parser for f in files], file_identifiers=[f.name for f in files],
                step_ft=0.5, gap_limit_ft=5.0,
            )
        model.add_well(build_well(files, result), activate=False)


def _signature(model, ds):
    params = _json_safe(model.params_for_well(ds))
    return json.dumps(params, sort_keys=True, default=str)


@pytest.fixture
def three_wells(tmp_path):
    model = AppModel()
    _load(model, tmp_path, [
        [("a.las", dict(well="ALPHA-1", bottom=1060.0))],
        [("b1.las", dict(well="BETA-2", top=1000.0, bottom=1040.0)),
         ("b2.las", dict(well="BETA-2", top=1030.0, bottom=1080.0))],
        [("c.las", dict(well="GAMMA-3", bottom=1050.0))],
    ])
    keys = model.project.keys()
    tops_path = tmp_path / "beta_tops.txt"
    tops_path.write_text(TOPS_TEXT)
    beta = model.project.get(keys[1])
    assert attach_tops(beta, str(tops_path)) == []

    alpha = model.project.get(keys[0])
    alpha.curve_mapping["GR"] = "GR"
    beta.analysis_mode = "Per-Formation"
    beta.selected_formations = ["Upper"]
    model.rw, model.a = 0.07, 0.81
    model.set_entry("m", "manual", 1.9, scope="well", well=keys[0])
    model.set_entry("rw", "manual", 0.033, scope="well", well=keys[2], source="calibrated")
    model.set_entry("n", "manual", 2.2, scope="well", zone="UPPER", well=keys[1])
    model.set_entry("a", "manual", 0.7, scope="project", zone="LOWER")
    model.set_active_well(keys[1])
    return model, keys


def test_round_trip_three_wells(three_wells, tmp_path):
    model, keys = three_wells
    before = {k: _signature(model, model.project.get(k)) for k in keys}
    path = str(tmp_path / "s.json")
    svc = SessionService()
    assert svc.save_session(model, path)

    saved = json.loads(open(path, encoding="utf-8").read())
    assert saved["_session_version"] == "2.1"
    assert [w["key"] for w in saved["wells"]] == keys
    assert saved["active_key"] == keys[1]
    assert len(saved["wells"][1]["sources"]) == 2 and saved["wells"][1]["merged"]
    assert saved["wells"][1]["tops_path"].endswith("beta_tops.txt")
    assert saved["wells"][0]["tops_path"] is None

    fresh = AppModel()
    data = svc.load_session(path)
    assert svc.apply_session_to_model(fresh, data)
    assert len(fresh.project) == 0
    notes = svc.restore_wells(fresh, data)
    assert notes == []

    assert fresh.project.keys() == keys
    assert fresh.project.active_key == keys[1]
    assert fresh.project.get(keys[0]).curve_mapping["GR"] == "GR"
    beta = fresh.project.get(keys[1])
    assert beta.merged and len(beta.sources) == 2
    assert beta.analysis_mode == "Per-Formation" and beta.selected_formations == ["Upper"]
    assert [f.name for f in beta.formation_tops.formations] == ["Upper", "Lower"]
    assert fresh.project.get(keys[0]).formation_tops is None
    assert fresh.project.get(keys[2]).overrides["rw"]["source"] == "calibrated"
    assert fresh.project.zone_params["LOWER"]["a"]["value"] == 0.7
    assert beta.zone_overrides["UPPER"]["n"]["value"] == 2.2
    for key in keys:
        assert _signature(fresh, fresh.project.get(key)) == before[key]
        assert fresh.project.get(key).calculated is False
        assert fresh.project.get(key).status == "loaded"


def test_missing_source_is_noted_and_skipped(three_wells, tmp_path):
    model, keys = three_wells
    path = str(tmp_path / "s.json")
    svc = SessionService()
    svc.save_session(model, path)
    os.remove(tmp_path / "c.las")
    fresh = AppModel()
    data = svc.load_session(path)
    svc.apply_session_to_model(fresh, data)
    notes = svc.restore_wells(fresh, data)
    assert fresh.project.keys() == keys[:2]
    assert len(notes) == 1 and "c.las" in notes[0] and "GAMMA-3" in notes[0]
    assert fresh.project.active_key == keys[1]


def test_missing_tops_file_is_noted(three_wells, tmp_path):
    model, keys = three_wells
    path = str(tmp_path / "s.json")
    svc = SessionService()
    svc.save_session(model, path)
    os.remove(tmp_path / "beta_tops.txt")
    fresh = AppModel()
    data = svc.load_session(path)
    notes = svc.restore_wells(fresh, data)
    assert len(fresh.project) == 3
    assert any("beta_tops.txt" in n for n in notes)
    assert fresh.project.get(keys[1]).formation_tops is None


def test_unknown_curve_in_mapping_is_noted(three_wells, tmp_path):
    model, keys = three_wells
    path = str(tmp_path / "s.json")
    svc = SessionService()
    svc.save_session(model, path)
    data = svc.load_session(path)
    data["wells"][0]["curve_mapping"]["GR"] = "GR_OLD"
    notes = svc.restore_wells(AppModel(), data)
    assert any("GR_OLD" in n for n in notes)


def test_numpy_values_are_json_safe(three_wells, tmp_path):
    model, keys = three_wells
    model.project.get(keys[0]).overrides["rw"] = {
        "mode": "manual", "value": np.float64(0.04), "source": "calibrated",
    }
    path = str(tmp_path / "s.json")
    assert SessionService().save_session(model, path)
    saved = json.loads(open(path, encoding="utf-8").read())
    assert saved["wells"][0]["overrides"]["rw"]["value"] == 0.04


def test_v1_session_loads_into_one_well_project(tmp_path):
    model = AppModel()
    _load(model, tmp_path, [[("a.las", dict(well="ALPHA-1"))]])
    path = tmp_path / "old.json"
    path.write_text(json.dumps({
        "_session_version": "1.4", "rw": 0.09, "rw_mode": "manual", "a": 0.75,
        "_las_filename": "old.las",
    }))
    svc = SessionService()
    data = svc.load_session(str(path))
    assert svc.apply_session_to_model(model, data)
    ds = model.project.active
    assert model.rw == 0.09 and model.a == 0.75
    assert ds.overrides["rw"]["mode"] == "manual" and ds.overrides["rw"]["value"] == 0.09
    assert model.params_for_well(ds)["rw"] == 0.09
    assert svc.restore_wells(model, data) == []


def test_v1_session_without_well_says_to_open_las(tmp_path):
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"_session_version": "1.2", "_las_filename": "C:/x/old.las"}))
    svc = SessionService()
    model = AppModel()
    data = svc.load_session(str(path))
    notes = svc.restore_wells(model, data)
    assert len(notes) == 1 and "Open the LAS file manually" in notes[0] and "old.las" in notes[0]
    assert len(model.project) == 0


def test_newer_unknown_version_warns_but_loads(tmp_path, caplog):
    path = tmp_path / "new.json"
    path.write_text(json.dumps({"_session_version": "3.0", "rw": 0.1}))
    with caplog.at_level("WARNING"):
        assert SessionService().load_session(str(path)) is not None
    assert "3.0" in caplog.text


def test_temperature_settings_round_trip(tmp_path):
    from models.app_model import AppModel
    from services.session_service import SessionService

    model = AppModel()
    model.temp_correction, model.surface_temp = True, 70.0
    model.temp_gradient, model.rw_ref_temp = 1.8, 68.0
    path = tmp_path / "t.json"
    svc = SessionService()
    assert svc.save_session(model, str(path))
    fresh = AppModel()
    assert svc.apply_session_to_model(fresh, svc.load_session(str(path)))
    assert (fresh.temp_correction, fresh.surface_temp, fresh.temp_gradient, fresh.rw_ref_temp) == (
        True, 70.0, 1.8, 68.0)


# ---- H3: source fingerprints, changed / missing sources ------------------------------
import hashlib
import shutil

from services.session_service import relocate_missing_sources


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _save(model, tmp_path, name="s.json"):
    path = str(tmp_path / name)
    assert SessionService().save_session(model, path)
    return path, json.loads(open(path, encoding="utf-8").read())


def _restore(path):
    svc = SessionService()
    fresh = AppModel()
    data = svc.load_session(path)
    svc.apply_session_to_model(fresh, data)
    return fresh, svc.restore_wells(fresh, data), data


def test_fingerprints_are_written_for_single_merged_and_tops(three_wells, tmp_path):
    model, keys = three_wells
    _, saved = _save(model, tmp_path)
    alpha, beta, _gamma = saved["wells"]
    # sources keeps its v1.7.0 type: a list of path strings
    assert all(isinstance(p, str) for w in saved["wells"] for p in w["sources"])
    assert saved["_session_version"] == "2.1"
    assert alpha["source_fingerprints"] == [{
        "path": str(tmp_path / "a.las"), "sha256": _sha(tmp_path / "a.las"),
        "size": os.path.getsize(tmp_path / "a.las")}]
    assert [f["path"] for f in beta["source_fingerprints"]] == beta["sources"]
    assert [f["sha256"] for f in beta["source_fingerprints"]] == [
        _sha(tmp_path / "b1.las"), _sha(tmp_path / "b2.las")]
    assert beta["tops_sha256"] == _sha(tmp_path / "beta_tops.txt")
    assert "tops_sha256" not in alpha and "core_sha256" not in alpha


def test_an_unchanged_session_restores_without_notes(three_wells, tmp_path):
    model, _ = three_wells
    path, _ = _save(model, tmp_path)
    _, notes, _ = _restore(path)
    assert notes == []


def test_an_overwritten_source_gets_the_changed_note_and_stays_stale(three_wells, tmp_path):
    model, keys = three_wells
    path, _ = _save(model, tmp_path)
    (tmp_path / "b2.las").write_text(_las_text("BETA-2", top=1030.0, bottom=1085.0))
    fresh, notes, _ = _restore(path)
    assert len(notes) == 1
    assert "b2.las changed since the session was saved (hash differs)" in notes[0]
    assert "results will differ from the saved project" in notes[0]
    assert fresh.project.get(keys[1]).calculated is False
    assert fresh.project.get(keys[1]).status == "loaded"


def test_a_changed_tops_file_gets_a_note(three_wells, tmp_path):
    model, keys = three_wells
    path, _ = _save(model, tmp_path)
    (tmp_path / "beta_tops.txt").write_text(TOPS_TEXT.replace("1080", "1070"))
    fresh, notes, _ = _restore(path)
    assert any("beta_tops.txt changed since the session was saved" in n for n in notes)
    assert fresh.project.get(keys[1]).formation_tops is not None


def test_a_session_without_fingerprints_restores_as_before(three_wells, tmp_path):
    model, keys = three_wells
    path, saved = _save(model, tmp_path)
    for entry in saved["wells"]:
        for name in ("source_fingerprints", "tops_sha256", "core_sha256"):
            entry.pop(name, None)
    open(path, "w", encoding="utf-8").write(json.dumps(saved))
    (tmp_path / "a.las").write_text(_las_text("ALPHA-1", bottom=1070.0))     # changed, unnoticed
    fresh, notes, data = _restore(path)
    assert notes == [] and fresh.project.keys() == keys
    # and nothing is asked for a missing file: no fingerprints, so no relocation
    os.remove(tmp_path / "c.las")
    asked = []
    assert relocate_missing_sources(data, lambda p: asked.append(p)) == 0 and asked == []


def test_relocation_with_the_same_file_is_silent(three_wells, tmp_path):
    model, keys = three_wells
    path, _ = _save(model, tmp_path)
    moved = tmp_path / "moved"
    moved.mkdir()
    shutil.move(str(tmp_path / "c.las"), str(moved / "c.las"))
    svc = SessionService()
    data = svc.load_session(path)
    asked = []
    assert relocate_missing_sources(data, lambda p: (asked.append(p), str(moved / "c.las"))[1]) == 1
    assert [os.path.basename(p) for p in asked] == ["c.las"]
    fresh = AppModel()
    notes = svc.restore_wells(fresh, data)
    assert notes == [] and fresh.project.keys() == keys
    assert fresh.project.get(keys[2]).sources[0]["path"] == str(moved / "c.las")


def test_relocating_to_a_different_file_gets_the_changed_note(three_wells, tmp_path):
    model, keys = three_wells
    path, _ = _save(model, tmp_path)
    os.remove(tmp_path / "c.las")
    other = tmp_path / "other.las"
    other.write_text(_las_text("GAMMA-3", bottom=1055.0))
    svc = SessionService()
    data = svc.load_session(path)
    relocate_missing_sources(data, lambda p: str(other))
    fresh = AppModel()
    notes = svc.restore_wells(fresh, data)
    assert len(notes) == 1 and "other.las changed since the session was saved" in notes[0]
    assert fresh.project.keys() == keys


def test_skip_keeps_the_missing_source_behaviour(three_wells, tmp_path):
    model, keys = three_wells
    path, _ = _save(model, tmp_path)
    os.remove(tmp_path / "c.las")
    svc = SessionService()
    data = svc.load_session(path)
    assert relocate_missing_sources(data, lambda p: None) == 0
    fresh = AppModel()
    notes = svc.restore_wells(fresh, data)
    assert fresh.project.keys() == keys[:2]
    assert len(notes) == 1 and "c.las" in notes[0] and "source file not found" in notes[0]


def test_the_relocated_folder_is_tried_first_for_other_files(three_wells, tmp_path):
    model, keys = three_wells
    path, _ = _save(model, tmp_path)
    moved = tmp_path / "moved"
    moved.mkdir()
    for name in ("a.las", "c.las"):
        shutil.move(str(tmp_path / name), str(moved / name))
    data = SessionService().load_session(path)
    asked = []

    def prompt(p):
        asked.append(os.path.basename(p))
        return str(moved / os.path.basename(p))

    assert relocate_missing_sources(data, prompt) == 2
    assert asked == ["a.las"]            # c.las was found in the remembered folder, silently
    assert data["wells"][2]["sources"] == [str(moved / "c.las")]


def test_porosity_keys_round_trip_with_a_zone_override(tmp_path):
    model = AppModel()
    model.dn_combination, model.gas_crossover_min, model.gas_vsh_max = "RMS", 0.03, 0.30
    model.set_entry("dn_combination", "manual", "Average", scope="project", zone="LOWER")
    model.set_entry("gas_crossover_min", "manual", 0.05, scope="project", zone="LOWER")
    path = str(tmp_path / "p.json")
    svc = SessionService()
    assert svc.save_session(model, path)
    saved = json.loads(open(path, encoding="utf-8").read())
    assert saved["_session_version"] == "2.1"
    flat = saved["global_params"]
    assert flat["dn_combination"] == "RMS"
    assert flat["gas_crossover_min"] == 0.03 and flat["gas_vsh_max"] == 0.30

    fresh = AppModel()
    assert svc.apply_session_to_model(fresh, svc.load_session(path))
    assert (fresh.dn_combination, fresh.gas_crossover_min, fresh.gas_vsh_max) == ("RMS", 0.03, 0.30)
    lower = fresh.project.zone_params["LOWER"]
    assert lower["dn_combination"]["value"] == "Average"
    assert lower["gas_crossover_min"]["value"] == 0.05


def test_old_session_without_porosity_keys_keeps_defaults(tmp_path):
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"_session_version": "2.1", "rw": 0.1}))
    svc = SessionService()
    model = AppModel()
    assert svc.apply_session_to_model(model, svc.load_session(str(path)))
    assert (model.dn_combination, model.gas_crossover_min, model.gas_vsh_max) == ("Average", 0.02, 0.40)
    path.write_text(json.dumps({"_session_version": "2.1", "dn_combination": "Bogus"}))
    assert svc.apply_session_to_model(model, svc.load_session(str(path)))
    assert model.dn_combination == "Average"
