"""LRLC settings of session format 2.7: the version rung, tolerant restore, round trip, stale."""

import copy
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from modules.lrlc import chain
from modules.lrlc.config import (
    L3_BLOCKS, L3_PARAM_KEYS, LRLC_PARAM_DEFAULTS, clean_param, lrlc_defaults,
    lrlc_l3_configured, merge_lrlc)
from services.lrlc_service import LrlcService
from services.session_service import SessionService, session_version_for

from tests.test_session_v2 import three_wells, _save, _restore  # noqa: F401


def test_session_version_constant():
    assert SessionService.SESSION_VERSION == "2.7"


def test_scalar_only_project_stays_below_2_7(three_wells):  # noqa: F811
    model, keys = three_wells
    assert session_version_for(model) == "2.1"
    LrlcService.set_enabled(model, True)
    LrlcService.set_param(model, "project", None, "rt_steps", ["laminated"])
    assert not lrlc_l3_configured(model.project)
    assert session_version_for(model) == "2.6"
    LrlcService.set_param(model, "project", None, "rt_steps", [])
    assert session_version_for(model) == "2.5"


def test_default_blocks_are_not_configured(three_wells):  # noqa: F811
    model, keys = three_wells
    for block in L3_BLOCKS:
        model.project.lrlc[block] = copy.deepcopy(lrlc_defaults()[block])
    assert not lrlc_l3_configured(model.project)
    assert session_version_for(model) == "2.1"


def test_curve_mode_zone_makes_2_7(three_wells):  # noqa: F811
    model, keys = three_wells
    LrlcService.set_param(model, "project", "UPPER", "mn_mode", "curve")
    assert lrlc_l3_configured(model.project)
    assert session_version_for(model) == "2.7" == session_version_for(model.project)


def test_invasion_step_makes_2_7(three_wells):  # noqa: F811
    model, keys = three_wells
    LrlcService.set_param(model, "project", None, "rt_steps", ["invasion"])
    assert session_version_for(model) == "2.7"
    LrlcService.set_param(model, "project", None, "rt_steps", [])
    assert session_version_for(model) in ("2.1", "2.5")


def test_well_level_key_makes_2_7(three_wells):  # noqa: F811
    model, keys = three_wells
    beta = model.project.get(keys[1])
    LrlcService.set_param(model, "well", "UPPER", "inv_tool", "generic_laterolog", ds=beta)
    assert session_version_for(model) == "2.7"


@pytest.mark.parametrize("block,key,value", [("variable_mn", "clip_warn_fraction", 0.1),
                                              ("invasion", "max_iter", 60)])
def test_changed_block_makes_2_7(three_wells, block, key, value):  # noqa: F811
    model, keys = three_wells
    model.project.lrlc[block][key] = value
    assert session_version_for(model) == "2.7"


def test_round_trip_2_7(three_wells, tmp_path):  # noqa: F811
    model, keys = three_wells
    beta = model.project.get(keys[1])
    LrlcService.set_enabled(model, True)
    model.project.lrlc["variable_mn"]["clip_m"] = [1.2, 3.5]
    model.project.lrlc["invasion"]["chunk"] = 5000
    model.project.lrlc["invasion"]["rt_bounds"] = [0.1, 5000.0]
    LrlcService.set_param(model, "project", "UPPER", "mn_mode", "curve")
    LrlcService.set_param(model, "project", "UPPER", "m_coef", [1.9, 0.5, 0.3, 0.0])
    LrlcService.set_param(model, "project", "UPPER", "n_model", "vsh")
    LrlcService.set_param(model, "project", "UPPER", "n_coef", [1.8, 0.6])
    LrlcService.set_param(model, "project", None, "rt_steps", ["invasion"])
    LrlcService.set_param(model, "project", None, "inv_tool", "generic_laterolog")
    LrlcService.set_param(model, "well", None, "rmf", 0.4, ds=beta)
    path, saved = _save(model, tmp_path)
    assert saved["_session_version"] == "2.7"
    assert saved["lrlc"] == model.project.lrlc
    assert saved["lrlc"]["variable_mn"]["clip_m"] == [1.2, 3.5]
    fresh, notes, _ = _restore(path)
    assert notes == []
    assert fresh.project.lrlc == model.project.lrlc
    assert fresh.project.get(keys[1]).lrlc == beta.lrlc
    assert session_version_for(fresh) == "2.7"
    assert fresh.params_for_well(fresh.project.get(keys[1]))["lrlc"] == \
        model.params_for_well(beta)["lrlc"]
    carried = fresh.params_for_well(fresh.project.get(keys[0]))["lrlc"]
    assert carried["variable_mn"]["clip_m"] == [1.2, 3.5]
    assert carried["invasion"]["chunk"] == 5000


@pytest.mark.parametrize("version", ["2.6", "2.5", "2.1"])
def test_older_sessions_load_with_l3_defaults(three_wells, tmp_path, version):  # noqa: F811
    model, keys = three_wells
    LrlcService.set_enabled(model, True)
    path, saved = _save(model, tmp_path)
    saved["_session_version"] = version
    saved["lrlc"] = {k: v for k, v in saved["lrlc"].items() if k not in L3_BLOCKS}
    old = tmp_path / "old.json"
    old.write_text(json.dumps(saved))
    fresh, _, _ = _restore(str(old))
    defaults = lrlc_defaults()
    for block in L3_BLOCKS:
        assert fresh.project.lrlc[block] == defaults[block]
    svc = SessionService()
    assert svc.load_session(str(old)) is not None and svc.last_notice == ""


def test_tolerant_restore_of_wrong_types():
    stored = {
        "enabled": True,
        "variable_mn": {"clip_m": "wide", "clip_n": [4.0, 1.0], "clip_warn_fraction": "x",
                        "fit": {"f_scale": [1]}, "unknown": 1},
        "invasion": {"rt_bounds": [5.0, 1.0], "chunk": -3, "max_iter": "many"},
        "params": {"default": {"m_coef": "abc", "n_coef": [1.8], "mn_mode": 3,
                               "inv_p": "x", "inv_r50": {"deep": 1}, "rmf": "salty",
                               "inv_tool": "no_such_tool", "future_key": 1},
                   "zones": {"UPPER": {"m_coef": [1.9, 0.5, 0.3, 99.0], "mn_mode": "curve"}}},
    }
    out = merge_lrlc(stored)
    defaults = lrlc_defaults()
    assert out["variable_mn"] == defaults["variable_mn"]
    assert out["invasion"] == defaults["invasion"]
    assert out["params"]["default"] == {}
    assert out["params"]["zones"]["UPPER"] == {"mn_mode": "curve"}
    assert out["enabled"] is True


def test_tolerant_restore_of_non_dict_blocks():
    out = merge_lrlc({"variable_mn": [1], "invasion": "x", "params": 7})
    assert out == lrlc_defaults()


def test_bad_m_coef_values_are_dropped():
    for bad in ("abc", [1.0], [float("nan"), 0, 0, 0], [9.0, 0, 0, 0], None, True):
        value, ok = clean_param("m_coef", bad)
        assert not ok and value is None
    value, ok = clean_param("m_coef", [1.9, 0.5, 0.3, 0.0])
    assert ok and value == [1.9, 0.5, 0.3, 0.0]


def test_session_file_with_wrong_types_loads(three_wells, tmp_path):  # noqa: F811
    model, keys = three_wells
    LrlcService.set_enabled(model, True)
    path, saved = _save(model, tmp_path)
    saved["lrlc"]["params"] = {"default": {"m_coef": "oops", "mn_mode": "curve"}, "zones": {}}
    saved["lrlc"]["invasion"] = {"chunk": "big"}
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(saved))
    fresh, _, _ = _restore(str(bad))
    assert fresh.project.lrlc["params"]["default"] == {"mn_mode": "curve"}
    assert fresh.project.lrlc["invasion"] == lrlc_defaults()["invasion"]


def test_older_app_drops_the_unknown_invasion_step(monkeypatch):
    from modules.lrlc import invasion
    invasion.register_step()
    assert "invasion" in chain.STEPS
    monkeypatch.delitem(chain.STEPS, "invasion")
    specs, unknown = chain.resolve_steps(["invasion"])
    assert specs == [] and unknown == ["invasion"]
    # the stored value itself survives the cleaning, so a newer app reads it back
    assert clean_param("rt_steps", ["invasion"]) == (["invasion"], True)


def test_l3_keys_are_registered_ladder_keys():
    for key in L3_PARAM_KEYS:
        assert key in LRLC_PARAM_DEFAULTS


def _hash(model, ds):
    return model.well_params_hash(ds)


def test_stale_hash_ignores_l3_settings_while_lrlc_is_off(three_wells):  # noqa: F811
    model, keys = three_wells
    ds = model.project.get(keys[0])
    before = _hash(model, ds)
    model.project.lrlc["invasion"]["max_iter"] = 55
    assert _hash(model, ds) == before


def test_stale_hash_follows_l3_ladder_keys_while_lrlc_is_on(three_wells):  # noqa: F811
    model, keys = three_wells
    LrlcService.set_enabled(model, True)
    ds = model.project.get(keys[0])
    h0 = _hash(model, ds)
    LrlcService.set_param(model, "project", None, "mn_mode", "curve")
    h1 = _hash(model, ds)
    assert h1 != h0
    LrlcService.set_param(model, "project", None, "m_coef", [2.0, 0.1, 0.0, 0.0])
    assert _hash(model, ds) != h1


def test_stale_hash_follows_l3_blocks_while_lrlc_is_on(three_wells):  # noqa: F811
    model, keys = three_wells
    LrlcService.set_enabled(model, True)
    ds = model.project.get(keys[0])
    h0 = _hash(model, ds)
    model.project.lrlc["variable_mn"]["clip_m"] = [1.1, 3.0]
    h1 = _hash(model, ds)
    assert h1 != h0
    model.project.lrlc["invasion"]["chunk"] = 1000
    assert _hash(model, ds) != h1
