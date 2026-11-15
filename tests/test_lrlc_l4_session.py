"""LRLC settings of session format 2.8 (deconvolution, elastic screening): the config keys, tolerant
restore, the version rung, round trip, the hash, the summary filter."""

import copy
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from modules.lrlc import chain
from modules.lrlc.config import (
    L4_BLOCKS, L4_PARAM_KEYS, LRLC_CHOICES, LRLC_PARAM_DEFAULTS, LRLC_RANGES, WELL_ONLY_KEYS,
    clean_param, lrlc_defaults, lrlc_l3_configured, lrlc_l4_configured, merge_lrlc, resolve_lrlc,
    resolve_lrlc_sources)
from modules.lrlc.decon import GENERIC_RESPONSES
from modules.lrlc.stage import _summary_params
from services.lrlc_service import LrlcService
from services.session_service import SessionService, session_version_for

from tests.test_session_v2 import three_wells, _save, _restore  # noqa: F401


def test_key_sets_follow_the_spec():
    assert len([k for k in L4_PARAM_KEYS if k.startswith("dec_")]) == 20
    assert len([k for k in L4_PARAM_KEYS if k.startswith("el_")]) == 13
    zone_capable = set(L4_PARAM_KEYS) - set(WELL_ONLY_KEYS)
    assert zone_capable == {"dec_max_ratio", "dec_misfit_warn", "el_shale_interval", "el_sw_wet",
                            "el_ai_drop", "el_vpvs_drop"}
    assert L4_BLOCKS == ("elastic",) and lrlc_defaults()["elastic"] == {"enabled": False}
    assert set(LRLC_CHOICES["dec_tool"]) == set(GENERIC_RESPONSES)
    assert LRLC_PARAM_DEFAULTS["dec_edits"] == {"add": [], "remove": []}
    for key, (lo, hi) in LRLC_RANGES.items():
        if key.startswith(("dec_", "el_")):
            default = LRLC_PARAM_DEFAULTS[key]
            assert default is None or lo <= default <= hi, key


@pytest.mark.parametrize("key,value,ok", [
    ("dec_fwhm_ft", 8.0, True), ("dec_fwhm_ft", 0.1, False), ("dec_fwhm_ft", "x", False),
    ("dec_lambda", None, True), ("dec_lambda", 0.01, True), ("dec_lambda", 100.0, False),
    ("dec_min_bed_ft", None, True), ("dec_min_bed_ft", 0.0, False),
    ("dec_mult_max_iter", 50, True), ("dec_mult_max_iter", 50.5, False),
    ("dec_solver", "mult", True), ("dec_solver", "bogus", False),
    ("dec_hires_source", "GR", True), ("dec_tool", "array_induction_2ft", True),
    ("dec_edits", {"add": [1010.0], "remove": [1020, 1030]}, True),
    ("dec_edits", {"add": []}, True), ("dec_edits", {"add": "x", "remove": []}, False),
    ("dec_edits", [1, 2], False), ("dec_edits", {"add": [True], "remove": []}, False),
    ("el_wet_interval", [1100.0, 1150.0], True), ("el_wet_interval", None, True),
    ("el_wet_interval", [1150.0, 1100.0], False), ("el_wet_interval", [1100.0], False),
    ("el_wet_interval", "x", False), ("el_shale_interval", [1.0, 2.0], True),
    ("el_shale_min_n", 12, True), ("el_shale_min_n", 12.5, False),
    ("el_mode", "ai", True), ("el_mode", "x", False), ("el_ai_drop", 0.0, False),
    ("el_ai_drop", 0.1, True),
])
def test_clean_param(key, value, ok):
    out, valid = clean_param(key, value)
    assert valid is ok
    if ok and value is not None and not isinstance(value, (dict, list, str)):
        assert out == value


def test_tolerant_restore_of_wrong_l4_types():
    stored = {"enabled": True, "elastic": {"enabled": "yes", "future": 1},
              "params": {"default": {"dec_edits": "none", "el_wet_interval": {"a": 1},
                                     "dec_fwhm_ft": 6.0, "el_mode": 7},
                         "zones": {"UPPER": {"el_shale_interval": [5.0, 1.0],
                                             "dec_max_ratio": 4.0}}}}
    out = merge_lrlc(stored)
    assert out["elastic"] == {"enabled": False}
    assert out["params"]["default"] == {"dec_fwhm_ft": 6.0}
    assert out["params"]["zones"] == {"UPPER": {"dec_max_ratio": 4.0}}
    assert merge_lrlc({"elastic": {"enabled": True}})["elastic"] == {"enabled": True}


def test_resolve_returns_the_well_default_of_a_well_only_key_at_every_zone():
    project = {"default": {"el_min_wet_n": 20}, "zones": {"UPPER": {"el_min_wet_n": 99,
                                                                    "el_ai_drop": 0.2}}}
    well = {"default": {"el_trend_scope": "zone"},
            "zones": {"UPPER": {"el_trend_scope": "well", "el_sw_wet": 0.8}}}
    upper = resolve_lrlc_sources(project, well, "UPPER")
    assert upper["el_min_wet_n"] == (20, "project default")
    assert upper["el_trend_scope"] == ("zone", "well default")
    assert upper["el_ai_drop"][0] == 0.2 and upper["el_sw_wet"][0] == 0.8
    assert resolve_lrlc(project, well, "UPPER")["el_min_wet_n"] == 20
    assert resolve_lrlc(project, {}, "UPPER")["dec_fwhm_ft"] == 4.0


def test_summary_params_hold_l4_keys_only_when_they_differ():
    resolved = {"default": dict(LRLC_PARAM_DEFAULTS), "zones": {
        "UPPER": {**LRLC_PARAM_DEFAULTS, "dec_max_ratio": 5.0, "rt_steps": ["decon"]}}}
    out = _summary_params(resolved)
    assert not [k for k in out["default"] if k in L4_PARAM_KEYS]
    assert [k for k in out["zones"]["UPPER"] if k in L4_PARAM_KEYS] == ["dec_max_ratio"]


# ---- version rung --------------------------------------------------------------------------
def test_decon_step_or_l4_key_makes_2_8(three_wells):  # noqa: F811
    model, keys = three_wells
    assert not lrlc_l4_configured(model.project)
    LrlcService.set_param(model, "project", None, "rt_steps", ["decon"])
    assert lrlc_l4_configured(model.project)
    assert session_version_for(model) == "2.8" == session_version_for(model.project)
    LrlcService.set_param(model, "project", None, "rt_steps", [])
    assert session_version_for(model) in ("2.1", "2.5")
    beta = model.project.get(keys[1])
    LrlcService.set_param(model, "well", "UPPER", "dec_max_ratio", 5.0, ds=beta)
    assert session_version_for(model) == "2.8"


def test_elastic_switch_makes_2_8_and_default_block_does_not(three_wells):  # noqa: F811
    model, keys = three_wells
    model.project.lrlc["elastic"] = copy.deepcopy(lrlc_defaults()["elastic"])
    assert not lrlc_l4_configured(model.project) and session_version_for(model) == "2.1"
    assert LrlcService.set_setting(model, "elastic", "enabled", True)
    assert session_version_for(model) == "2.8"
    assert not LrlcService.set_setting(model, "elastic", "enabled", "yes")
    assert not LrlcService.set_setting(model, "elastic", "other", True)


def test_older_rungs_are_unchanged(three_wells):  # noqa: F811
    model, keys = three_wells
    LrlcService.set_param(model, "project", None, "rt_steps", ["invasion"])
    assert session_version_for(model) == "2.7" and not lrlc_l4_configured(model.project)
    assert lrlc_l3_configured(model.project)


def test_round_trip_2_8(three_wells, tmp_path):  # noqa: F811
    model, keys = three_wells
    beta = model.project.get(keys[1])
    LrlcService.set_enabled(model, True)
    LrlcService.set_setting(model, "elastic", "enabled", True)
    LrlcService.set_param(model, "project", None, "rt_steps", ["decon"])
    LrlcService.set_param(model, "project", None, "dec_fwhm_ft", 6.0)
    LrlcService.set_param(model, "project", "UPPER", "dec_max_ratio", 4.0)
    LrlcService.set_param(model, "well", None, "dec_edits", {"add": [1020.0], "remove": [1031.5]},
                          ds=beta)
    LrlcService.set_param(model, "well", None, "el_wet_interval", [1100.0, 1150.0], ds=beta)
    path, saved = _save(model, tmp_path)
    assert saved["_session_version"] == "2.8"
    assert saved["lrlc"]["elastic"] == {"enabled": True}
    fresh, notes, _ = _restore(path)
    assert notes == []
    assert fresh.project.lrlc == model.project.lrlc
    assert fresh.project.get(keys[1]).lrlc == beta.lrlc
    assert fresh.project.get(keys[1]).lrlc["default"]["dec_edits"] == {"add": [1020.0], "remove": [1031.5]}
    assert session_version_for(fresh) == "2.8"
    assert fresh.params_for_well(fresh.project.get(keys[1]))["lrlc"] == \
        model.params_for_well(beta)["lrlc"]
    assert fresh.params_for_well(fresh.project.get(keys[1]))["lrlc"]["elastic"] == {"enabled": True}


@pytest.mark.parametrize("version", ["2.7", "2.6", "2.5", "2.1"])
def test_older_sessions_load_with_l4_defaults(three_wells, tmp_path, version):  # noqa: F811
    model, keys = three_wells
    LrlcService.set_enabled(model, True)
    path, saved = _save(model, tmp_path)
    saved["_session_version"] = version
    saved["lrlc"] = {k: v for k, v in saved["lrlc"].items() if k not in L4_BLOCKS}
    old = tmp_path / "old.json"
    old.write_text(json.dumps(saved))
    fresh, _, _ = _restore(str(old))
    assert fresh.project.lrlc["elastic"] == {"enabled": False}
    svc = SessionService()
    assert svc.load_session(str(old)) is not None and svc.last_notice == ""


def test_decon_is_registered_first_and_vertical():
    spec = chain.STEPS["decon"]
    assert spec.order == 0 and spec.kind == "vertical" and spec.label == "Deconvolution"
    assert spec.column == "RT_DECON" and spec.varied == ()
    assert chain.DERIVES["decon_well"].scope == "well"
    assert chain.DERIVES["decon_well"].outputs == ("rt_decon", "decon_valid")
    assert set(spec.params) >= {"dec_max_ratio", "dec_misfit_warn", "dec_fwhm_ft"}
