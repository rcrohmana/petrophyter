"""Uncertainty setup in the session (version 2.3) and on the Project."""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from models.app_model import AppModel
from modules.uncertainty import UncertaintyConfig
from services.session_service import SessionService, session_version_for

# Reuse the session fixtures and helpers of the v2 suite.
from tests.test_session_v2 import three_wells, _save, _restore  # noqa: F401


def _enable_uncertainty(model):
    cfg = UncertaintyConfig(n=200, seed=7, sampling="random")
    cfg.distributions["rw"].enabled = True
    cfg.distributions["rw"].low, cfg.distributions["rw"].high = -0.2, 0.25
    cfg.distributions["m"].enabled = True
    cfg.distributions["m"].kind = "normal"
    cfg.distributions["m"].sd = 0.1
    cfg.correlations[("m", "n")] = -0.5
    model.project.uncertainty = cfg
    return cfg


def test_uncertainty_round_trips_as_2_3(three_wells, tmp_path):
    model, _ = three_wells
    cfg = _enable_uncertainty(model)
    assert session_version_for(model) == "2.3"
    path, saved = _save(model, tmp_path)
    assert saved["_session_version"] == "2.3"
    assert saved["uncertainty"]["distributions"]["rw"]["enabled"] is True
    assert saved["uncertainty"]["correlations"] == [["m", "n", -0.5]]
    fresh, notes, _ = _restore(path)
    assert notes == []
    assert fresh.project.uncertainty == cfg
    assert fresh.project.uncertainty_result is None


def test_session_without_uncertainty_key_loads_nothing_enabled(three_wells, tmp_path):
    model, _ = three_wells
    path, saved = _save(model, tmp_path)
    assert saved["_session_version"] == "2.1" and "uncertainty" not in saved
    fresh, _, _ = _restore(path)
    assert fresh.project.uncertainty.enabled_names() == ()


def test_a_22_session_loads(three_wells, tmp_path):
    model, _ = three_wells
    model.rock_typing_enabled = True
    model.project.rock_types = {"classes": [{"name": "RT1"}]}
    path, saved = _save(model, tmp_path)
    assert saved["_session_version"] == "2.2" and "uncertainty" not in saved
    fresh, notes, _ = _restore(path)
    assert notes == [] and fresh.project.rock_types == {"classes": [{"name": "RT1"}]}
    assert fresh.project.uncertainty.enabled_names() == ()


def test_rock_typing_plus_uncertainty_is_2_3(three_wells, tmp_path):
    model, _ = three_wells
    model.rock_typing_enabled = True
    model.project.rock_types = {"classes": [{"name": "RT1"}]}
    _enable_uncertainty(model)
    _, saved = _save(model, tmp_path)
    assert saved["_session_version"] == "2.3"
    assert "rock_types" in saved and "uncertainty" in saved


def test_configured_but_nothing_enabled_keeps_2_1(three_wells, tmp_path):
    model, _ = three_wells
    model.project.uncertainty = UncertaintyConfig(n=500)
    _, saved = _save(model, tmp_path)
    assert saved["_session_version"] == "2.1" and "uncertainty" not in saved


def test_malformed_uncertainty_falls_back_to_defaults(tmp_path):
    base = {"_session_version": "2.3", "global_params": {}, "zone_params": {}, "wells": []}
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({**base, "uncertainty": {
        "n": "x", "sampling": 5,
        "distributions": {"rw": "nope", "m": {"enabled": 1, "low": "a"}},
        "correlations": [["rw"], 3]}}))
    svc = SessionService()
    model = AppModel()
    svc.apply_session_to_model(model, svc.load_session(str(path)))
    cfg = model.project.uncertainty
    assert cfg.enabled_names() == () and cfg.correlations == {}
    path.write_text(json.dumps({**base, "uncertainty": [1, 2]}))
    model2 = AppModel()
    svc.apply_session_to_model(model2, svc.load_session(str(path)))
    assert model2.project.uncertainty.enabled_names() == ()


def test_project_clear_resets_uncertainty(three_wells):
    model, _ = three_wells
    _enable_uncertainty(model)
    model.project.uncertainty_result = object()
    model.project.clear()
    assert model.project.uncertainty.enabled_names() == ()
    assert model.project.uncertainty_result is None


def test_removing_a_well_clears_the_result_not_the_config(three_wells):
    model, keys = three_wells
    cfg = _enable_uncertainty(model)
    model.project.uncertainty_result = object()
    model.project.remove_well(keys[0])
    assert model.project.uncertainty_result is None
    assert model.project.uncertainty == cfg


def test_replacing_a_well_clears_the_result(three_wells):
    model, keys = three_wells
    model.project.uncertainty_result = object()
    model.project.add_well(model.project.get(keys[0]))
    assert model.project.uncertainty_result is None


def test_uncertainty_result_is_never_saved(three_wells, tmp_path):
    model, _ = three_wells
    _enable_uncertainty(model)
    model.project.uncertainty_result = {"p50": 1.0}
    path, saved = _save(model, tmp_path)
    assert "uncertainty_result" not in saved and "uncertainty_result" not in saved["uncertainty"]
    assert "p50" not in open(path, encoding="utf-8").read()
