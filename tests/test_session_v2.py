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
    assert saved["_session_version"] == "2.0"
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
