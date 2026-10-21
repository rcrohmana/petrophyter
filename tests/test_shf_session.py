"""Saturation-height settings and contacts in the session (version 2.4) and on the Project."""

import itertools
import json
import os

import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from models.app_model import AppModel
from modules.shf_config import SHF_DEFAULTS, merge_shf, shf_defaults, shf_in_use
from modules.uncertainty import UncertaintyConfig
from services.session_service import SessionService, session_version_for

from tests.test_session_v2 import three_wells, _save, _restore  # noqa: F401

CONTACTS = {
    "datum": "TVDSS", "kb_ft": 25.0,
    "default": {"fwl": 7250.0, "fluid": "oil", "water_density": None},
    "zones": {"UPPER": {"fwl": 7180.0, "fluid": "gas", "water_density": 1.08}},
}


def test_defaults_shape_and_copy():
    d = shf_defaults()
    assert d == SHF_DEFAULTS and d is not SHF_DEFAULTS
    assert d["enabled"] is False and d["use_for_pay"] is False and d["fits"] == {}
    assert "log_derived_ack" not in d
    assert d["fluids"] == {"water": 1.03, "oil": 0.75, "gas": 0.25}
    d["fluids"]["oil"] = 0.9
    d["fits"]["All"] = {}
    assert SHF_DEFAULTS["fluids"]["oil"] == 0.75 and SHF_DEFAULTS["fits"] == {}
    json.dumps(SHF_DEFAULTS)


def test_merge_is_tolerant():
    assert merge_shf(None) == SHF_DEFAULTS and merge_shf([1]) == SHF_DEFAULTS
    merged = merge_shf({"enabled": True, "min_pc_psi": 2, "perm_source": "PERM_RT",
                        "fluids": {"oil": 0.8, "gas": "x", "brine": 5},
                        "fits": {1: {"model": "power"}}, "bogus": 1})
    assert merged["enabled"] is True and merged["min_pc_psi"] == 2.0
    assert merged["perm_source"] == "PERM_RT"
    assert merged["fluids"] == {"water": 1.03, "oil": 0.8, "gas": 0.25}
    assert merged["fits"] == {"1": {"model": "power"}} and "bogus" not in merged
    bad = merge_shf({"enabled": "yes", "perm_source": 3, "fallback": "", "fits": [1],
                     "sigma_cos": "x", "weight_by": None})
    assert bad == SHF_DEFAULTS


def test_project_has_shf_and_clear_resets_it():
    model = AppModel()
    assert model.project.shf == SHF_DEFAULTS
    model.project.shf["enabled"] = True
    model.project.shf["fits"]["All"] = {"model": "power"}
    model.project.clear()
    assert model.project.shf == SHF_DEFAULTS
    assert hasattr(model.project, "pc_changed")


def test_shf_in_use_triggers(three_wells):
    model, keys = three_wells
    project = model.project
    assert shf_in_use(project) is False
    project.shf["enabled"] = True
    assert shf_in_use(project)
    project.shf = shf_defaults()
    project.shf["fits"]["All"] = {"model": "power"}
    assert shf_in_use(project)
    project.shf = shf_defaults()
    ds = project.get(keys[0])
    ds.pc_data = pd.DataFrame()
    ds.shf_contacts = {}
    assert shf_in_use(project) is False
    ds.pc_data = pd.DataFrame({"pc": [1.0]})
    assert shf_in_use(project)
    ds.pc_data = None
    ds.shf_contacts = CONTACTS
    assert shf_in_use(project)


def _set(model, keys, shf, unc, rock):
    project = model.project
    project.shf = shf_defaults()
    project.uncertainty = UncertaintyConfig()
    project.rock_types = None
    model.rock_typing_enabled = False
    project.get(keys[0]).shf_contacts = {}
    if shf:
        project.shf["enabled"] = True
    if unc:
        project.uncertainty.distributions["rw"].enabled = True
    if rock:
        project.rock_types = {"classes": [{"name": "RT1"}]}


@pytest.mark.parametrize("shf,unc,rock", list(itertools.product([False, True], repeat=3)))
def test_version_ladder_is_the_max_over_features(three_wells, tmp_path, shf, unc, rock):
    model, keys = three_wells
    _set(model, keys, shf, unc, rock)
    expected = "2.4" if shf else "2.3" if unc else "2.2" if rock else "2.1"
    assert session_version_for(model) == expected == session_version_for(model.project)
    _, saved = _save(model, tmp_path)
    assert saved["_session_version"] == expected
    assert ("shf" in saved) is shf
    assert ("uncertainty" in saved) is unc
    assert ("rock_types" in saved) is rock


def test_contacts_alone_make_it_2_4_and_round_trip(three_wells, tmp_path):
    model, keys = three_wells
    model.project.get(keys[1]).shf_contacts = json.loads(json.dumps(CONTACTS))
    assert session_version_for(model) == "2.4"
    path, saved = _save(model, tmp_path)
    assert saved["_session_version"] == "2.4" and "shf" in saved
    assert "shf_contacts" not in saved["wells"][0] and "shf_contacts" not in saved["wells"][2]
    assert saved["wells"][1]["shf_contacts"] == CONTACTS
    fresh, notes, _ = _restore(path)
    assert notes == []
    assert fresh.project.get(keys[1]).shf_contacts == CONTACTS
    assert fresh.project.get(keys[0]).shf_contacts == {}
    assert fresh.project.shf == SHF_DEFAULTS


def test_project_shf_round_trips(three_wells, tmp_path):
    model, _ = three_wells
    shf = model.project.shf
    shf.update(enabled=True, use_for_pay=True, perm_source="PERM_WR", min_pc_psi=1.5,
               rock_type_source="all", weight_by="point")
    shf["fluids"]["oil"] = 0.8
    shf["fits"] = {"1": {"model": "power", "params": {"a": 0.5, "b": -0.4}, "basis": "core_pc"},
                   "All": {"model": "power", "params": {"a": 0.4, "b": -0.3}}}
    expected = json.loads(json.dumps(shf))
    path, saved = _save(model, tmp_path)
    assert saved["shf"] == expected
    fresh, notes, _ = _restore(path)
    assert notes == []
    assert fresh.project.shf == expected


@pytest.mark.parametrize("version", ["1.0", "2.1", "2.2", "2.3"])
def test_older_sessions_load_with_shf_defaults(tmp_path, version):
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"_session_version": version, "global_params": {"rw": 0.08},
                                "zone_params": {}, "wells": []}))
    svc = SessionService()
    model = AppModel()
    if version.startswith("2"):     # a 1.x file is flat and never touches the project
        model.project.shf["enabled"] = True
    assert svc.apply_session_to_model(model, svc.load_session(str(path)))
    assert model.project.shf == SHF_DEFAULTS


def test_unknown_shf_key_and_bad_contacts_are_tolerated(tmp_path):
    path = tmp_path / "odd.json"
    path.write_text(json.dumps({
        "_session_version": "2.4", "global_params": {}, "zone_params": {}, "wells": [],
        "shf": {"enabled": True, "from_the_future": {"x": 1}, "fluids": {"oil": 0.7}}}))
    svc = SessionService()
    model = AppModel()
    assert svc.apply_session_to_model(model, svc.load_session(str(path)))
    assert model.project.shf["enabled"] is True and "from_the_future" not in model.project.shf
    assert model.project.shf["fluids"]["oil"] == 0.7

    path.write_text(json.dumps({"_session_version": "2.4", "global_params": {}, "zone_params": {},
                                "wells": [], "shf": "nonsense"}))
    model2 = AppModel()
    assert svc.apply_session_to_model(model2, svc.load_session(str(path)))
    assert model2.project.shf == SHF_DEFAULTS


def test_malformed_contacts_are_dropped_on_restore(three_wells, tmp_path):
    model, keys = three_wells
    model.project.get(keys[0]).shf_contacts = CONTACTS
    path, saved = _save(model, tmp_path)
    saved["wells"][0]["shf_contacts"] = {
        "datum": "NOPE", "kb_ft": "x",
        "default": {"fwl": "deep", "fluid": "oil"},
        "zones": {"UPPER": {"fwl": 7100, "fluid": "mud"}, "LOWER": 5}}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(saved, fh)
    fresh, _, _ = _restore(path)
    assert fresh.project.get(keys[0]).shf_contacts == {
        "kb_ft": None,
        "zones": {"UPPER": {"fwl": 7100.0, "fluid": "oil", "water_density": None}}}
