"""LRLC settings of session format 2.6: the version rung, the round trip, older sessions, stale."""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from modules.lrlc.config import lrlc_defaults
from services.lrlc_service import LrlcService
from services.session_service import SessionService, session_version_for

from tests.test_session_v2 import three_wells, _save, _restore  # noqa: F401


def test_session_version_constant():
    assert SessionService.SESSION_VERSION == "2.6"


def test_rung_guard_default_is_not_configured(three_wells):  # noqa: F811
    model, keys = three_wells
    LrlcService.set_enabled(model, True)
    assert session_version_for(model) == "2.5"
    # guard on is the default, so writing it again does not raise the version
    LrlcService.set_guard_enabled(model, True)
    assert session_version_for(model) == "2.5"


def test_rung_guard_off(three_wells):  # noqa: F811
    model, keys = three_wells
    assert LrlcService.set_guard_enabled(model, False)
    assert session_version_for(model) == "2.6" == session_version_for(model.project)


def test_rung_block_setting_and_ladder_keys(three_wells):  # noqa: F811
    model, keys = three_wells
    assert LrlcService.set_setting(model, "qv", "min_pairs", 8)
    assert session_version_for(model) == "2.6"
    LrlcService.set_setting(model, "qv", "min_pairs", 5)
    assert session_version_for(model) == "2.1"
    LrlcService.set_param(model, "project", "LOWER", "hag_vsh_max", 0.7)
    assert session_version_for(model) == "2.6"


def test_rung_laminated_step_and_rt_sbc(three_wells):  # noqa: F811
    model, keys = three_wells
    LrlcService.set_param(model, "project", None, "rt_steps", ["laminated"])
    assert session_version_for(model) == "2.6"
    LrlcService.set_param(model, "project", None, "rt_steps", [])
    assert session_version_for(model) == "2.5" or session_version_for(model) == "2.1"
    ds = model.project.get(keys[0])
    ds.curve_mapping["RT"] = "RT"
    LrlcService.set_rt_sbc(model, ds, True)
    assert session_version_for(model) == "2.6"


def test_l1_only_stays_2_5(three_wells):  # noqa: F811
    model, keys = three_wells
    LrlcService.set_enabled(model, True)
    LrlcService.set_param(model, "project", None, "screen_rt_max", 7.5)
    assert session_version_for(model) == "2.5"


def test_round_trip_2_6(three_wells, tmp_path):  # noqa: F811
    model, keys = three_wells
    alpha, beta = model.project.get(keys[0]), model.project.get(keys[1])
    alpha.curve_mapping["RT"] = "RT"
    LrlcService.set_enabled(model, True)
    assert LrlcService.set_setting(model, "thomas_stieber", "enabled", True)
    assert LrlcService.set_setting(model, "thomas_stieber", "clean_pct", 85.0)
    assert LrlcService.set_setting(model, "pyrite", "u_fluid", 0.5)
    assert LrlcService.set_setting(model, "qv", "min_pairs", 7)
    assert LrlcService.set_setting(model, "diagnosis", "bvw_cv_max", 0.3)
    LrlcService.set_guard_enabled(model, False)
    assert LrlcService.set_setting(model, "guard", "vlam_share", 0.6)
    assert LrlcService.apply_endpoints(model, "project", None, 0.30, 0.10)
    LrlcService.set_param(model, "project", "LOWER", "rt_steps", ["laminated", "pyrite"])
    LrlcService.set_param(model, "well", None, "s_warn", 0.7, ds=beta)
    LrlcService.set_param(model, "well", "UPPER", "pyr_method", "rhob_pef", ds=beta)
    LrlcService.set_param(model, "well", "UPPER", "ma_rho", 2.7, ds=beta)
    LrlcService.set_param(model, "project", None, "qv_source", "estimate")
    assert LrlcService.set_rt_sbc(model, alpha, True)
    assert session_version_for(model) == "2.6"

    path, saved = _save(model, tmp_path)
    assert saved["_session_version"] == "2.6"
    assert saved["lrlc"] == model.project.lrlc
    by_key = {w["key"]: w for w in saved["wells"]}
    assert by_key[keys[0]]["lrlc_curves"] == {"RT_SBC": "RT"}

    fresh, notes, _ = _restore(path)
    assert notes == []
    assert fresh.project.lrlc == model.project.lrlc
    assert fresh.project.lrlc["guard"]["enabled"] is False
    assert fresh.project.lrlc["params"]["default"]["phi_max"] == 0.30
    assert fresh.project.get(keys[0]).lrlc_curves == {"RT_SBC": "RT"}
    assert fresh.project.get(keys[1]).lrlc == beta.lrlc
    assert fresh.project.get(keys[1]).lrlc["zones"]["UPPER"]["ma_rho"] == 2.7
    assert session_version_for(fresh) == "2.6"
    svc = SessionService()
    assert svc.load_session(path) is not None and svc.last_notice == ""


def test_rt_sbc_only_session_round_trips(three_wells, tmp_path):  # noqa: F811
    model, keys = three_wells
    ds = model.project.get(keys[2])
    ds.curve_mapping["RT"] = "RT"
    assert LrlcService.set_rt_sbc(model, ds, True)
    path, saved = _save(model, tmp_path)
    assert saved["_session_version"] == "2.6"
    fresh, _, _ = _restore(path)
    assert fresh.project.get(keys[2]).lrlc_curves == {"RT_SBC": "RT"}


@pytest.mark.parametrize("version", ["2.5", "2.4", "2.1", "1.4", "1.0"])
def test_older_sessions_load_with_l2_defaults(three_wells, tmp_path, version):  # noqa: F811
    model, keys = three_wells
    LrlcService.set_enabled(model, True)
    path, saved = _save(model, tmp_path)
    saved["_session_version"] = version
    saved["lrlc"] = {k: v for k, v in saved["lrlc"].items()
                     if k in ("enabled", "screening", "rt_cutoff", "movable", "params")}
    old = tmp_path / "old.json"
    old.write_text(json.dumps(saved))
    fresh, _, _ = _restore(str(old))
    defaults = lrlc_defaults()
    for block in ("thomas_stieber", "pyrite", "qv", "guard", "diagnosis"):
        assert fresh.project.lrlc[block] == defaults[block]
    assert fresh.project.lrlc["guard"]["enabled"] is True
    svc = SessionService()
    assert svc.load_session(str(old)) is not None and svc.last_notice == ""


def test_l2_values_in_a_2_5_file_are_cleaned(three_wells, tmp_path):  # noqa: F811
    model, keys = three_wells
    LrlcService.set_enabled(model, True)
    path, saved = _save(model, tmp_path)
    saved["lrlc"]["qv"] = {"min_pairs": 0, "phi_min": 9.0, "junk": 1}
    saved["lrlc"]["params"] = {"default": {"s_warn": 5.0, "phi_max": 0.3, "bogus": 1}, "zones": {}}
    saved["wells"][0]["lrlc_curves"] = {"RT_SBC": "RT", "NEWMARK": "X"}
    p = tmp_path / "x.json"
    p.write_text(json.dumps(saved))
    fresh, _, _ = _restore(str(p))
    assert fresh.project.lrlc["qv"] == lrlc_defaults()["qv"]
    assert fresh.project.lrlc["params"]["default"] == {"phi_max": 0.3}
    assert fresh.project.get(keys[0]).lrlc_curves == {"RT_SBC": "RT"}


def test_session_without_lrlc_keeps_its_version(three_wells, tmp_path):  # noqa: F811
    model, keys = three_wells
    assert session_version_for(model) == "2.1"
    _, saved = _save(model, tmp_path)
    assert saved["_session_version"] == "2.1" and "lrlc" not in saved


def test_minor_notice_for_newer_minor():
    pass  # covered in test_lrlc_session.test_minor_notice


def _hash(model, ds):
    return model.well_params_hash(ds)


def test_stale_hash_ignores_l2_settings_while_lrlc_is_off(three_wells):  # noqa: F811
    model, keys = three_wells
    ds = model.project.get(keys[0])
    before = _hash(model, ds)
    LrlcService.set_setting(model, "qv", "min_pairs", 9)
    LrlcService.set_guard_enabled(model, False)
    LrlcService.apply_endpoints(model, "project", None, 0.3, 0.1)
    assert _hash(model, ds) == before


def test_stale_hash_follows_l2_ladder_keys_while_lrlc_is_on(three_wells):  # noqa: F811
    model, keys = three_wells
    LrlcService.set_enabled(model, True)
    ds = model.project.get(keys[0])
    h0 = _hash(model, ds)
    LrlcService.set_param(model, "project", None, "hag_vsh_max", 0.7)
    h1 = _hash(model, ds)
    assert h1 != h0


def test_stale_hash_follows_l2_blocks_while_lrlc_is_on(three_wells):  # noqa: F811
    model, keys = three_wells
    LrlcService.set_enabled(model, True)
    ds = model.project.get(keys[0])
    h0 = _hash(model, ds)
    LrlcService.set_guard_enabled(model, False)
    h1 = _hash(model, ds)
    assert h1 != h0
    LrlcService.set_setting(model, "qv", "min_pairs", 9)
    assert _hash(model, ds) != h1
