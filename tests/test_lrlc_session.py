"""LRLC settings in the session (format 2.5) and the minor-version notice."""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from modules.lrlc.config import lrlc_defaults
from services.lrlc_service import LrlcService
from services.session_service import SessionService, session_version_for

from tests.test_session_v2 import three_wells, _save, _restore  # noqa: F401


def test_version_constant():
    assert SessionService.SESSION_VERSION == "2.5"


def test_not_in_use_stays_old_version(three_wells, tmp_path):  # noqa: F811
    model, keys = three_wells
    assert session_version_for(model) == "2.1"
    # Workbench-only blocks never raise the version
    model.project.lrlc["pickett"]["vsh_max"] = 0.3
    assert session_version_for(model) == "2.1"
    _, saved = _save(model, tmp_path)
    assert saved["_session_version"] == "2.1" and "lrlc" not in saved
    for w in saved["wells"]:
        assert "lrlc" not in w and "lrlc_curves" not in w


def test_in_use_is_2_5_and_round_trips(three_wells, tmp_path):  # noqa: F811
    model, keys = three_wells
    alpha, beta = model.project.get(keys[0]), model.project.get(keys[1])
    LrlcService.set_enabled(model, True)
    LrlcService.set_param(model, "project", None, "screen_rt_max", 7.5)
    LrlcService.set_param(model, "project", "LOWER", "rt_steps", ["whatever_step"])
    LrlcService.set_param(model, "well", "UPPER", "movable_tol", 0.1, ds=beta)
    LrlcService.set_curve(model, alpha, "RXO", "MSFL")
    LrlcService.set_curve(model, alpha, "DTS", None)
    LrlcService.set_setting(model, "rt_cutoff", "enabled", True)
    LrlcService.set_setting(model, "movable", "swirr_column", "SWIRR_BUCKLES")
    LrlcService.set_setting(model, "pickett", "vsh_max", 0.3)
    assert session_version_for(model) == "2.5" == session_version_for(model.project)

    path, saved = _save(model, tmp_path)
    assert saved["_session_version"] == "2.5"
    assert saved["lrlc"] == model.project.lrlc
    by_key = {w["key"]: w for w in saved["wells"]}
    assert by_key[keys[0]]["lrlc_curves"] == {"RXO": "MSFL", "DTS": None}
    assert "lrlc" not in by_key[keys[0]]
    assert by_key[keys[1]]["lrlc"] == {"default": {}, "zones": {"UPPER": {"movable_tol": 0.1}}}
    assert "lrlc_curves" not in by_key[keys[1]]
    assert "lrlc" not in by_key[keys[2]] and "lrlc_curves" not in by_key[keys[2]]

    fresh, notes, _ = _restore(path)
    assert notes == []
    assert fresh.project.lrlc == model.project.lrlc
    assert fresh.project.get(keys[0]).lrlc_curves == {"RXO": "MSFL", "DTS": None}
    assert fresh.project.get(keys[0]).lrlc == {}
    assert fresh.project.get(keys[1]).lrlc == beta.lrlc
    assert fresh.project.get(keys[2]).lrlc == {} and fresh.project.get(keys[2]).lrlc_curves == {}
    assert fresh.params_for_well(fresh.project.get(keys[1]))["lrlc"] == \
        model.params_for_well(beta)["lrlc"]


def test_well_only_levels_make_it_2_5(three_wells, tmp_path):  # noqa: F811
    model, keys = three_wells
    model.project.get(keys[2]).lrlc_curves = {"PEF": "PEFZ"}
    assert session_version_for(model) == "2.5"
    path, saved = _save(model, tmp_path)
    assert saved["_session_version"] == "2.5"
    fresh, _, _ = _restore(path)
    assert fresh.project.get(keys[2]).lrlc_curves == {"PEF": "PEFZ"}
    assert fresh.project.lrlc == lrlc_defaults() or "lrlc" in saved


def test_older_session_loads_with_defaults(three_wells, tmp_path):  # noqa: F811
    model, keys = three_wells
    model.project.lrlc["enabled"] = True
    model.project.get(keys[0]).lrlc = {"default": {"movable_tol": 0.1}, "zones": {}}
    path, saved = _save(model, tmp_path)
    saved.pop("lrlc")
    for w in saved["wells"]:
        w.pop("lrlc", None)
    saved["_session_version"] = "2.4"
    old = tmp_path / "old.json"
    old.write_text(json.dumps(saved))
    fresh, _, _ = _restore(str(old))
    assert fresh.project.lrlc == lrlc_defaults()
    assert fresh.project.get(keys[0]).lrlc == {}
    svc = SessionService()
    assert svc.load_session(str(old)) is not None and svc.last_notice == ""


def test_restore_drops_unknown_and_invalid(three_wells, tmp_path):  # noqa: F811
    model, keys = three_wells
    LrlcService.set_enabled(model, True)
    path, saved = _save(model, tmp_path)
    saved["lrlc"]["future_key"] = {"x": 1}
    saved["lrlc"]["params"] = {"default": {"screen_rt_max": 8, "future_param": 1, "movable_tol": 9},
                               "zones": {"upper": {"rt_fallback": "bogus"}}}
    saved["wells"][0]["lrlc"] = {"default": {"junk": 1}, "zones": {}}
    saved["wells"][0]["lrlc_curves"] = {"RXO": "MSFL", "NEWROLE": "X"}
    p = tmp_path / "x.json"
    p.write_text(json.dumps(saved))
    fresh, _, _ = _restore(str(p))
    assert "future_key" not in fresh.project.lrlc
    assert fresh.project.lrlc["params"] == {"default": {"screen_rt_max": 8.0}, "zones": {}}
    assert fresh.project.get(keys[0]).lrlc == {}
    assert fresh.project.get(keys[0]).lrlc_curves == {"RXO": "MSFL"}


@pytest.mark.parametrize("version,notice", [
    ("2.4", False), ("2.5", False), ("2.6", True), ("2.9", True), ("1.9", False)])
def test_minor_notice(tmp_path, version, notice):
    path = tmp_path / "v.json"
    path.write_text(json.dumps({"_session_version": version, "rw": 0.1}))
    svc = SessionService()
    assert svc.load_session(str(path)) is not None
    if notice:
        assert svc.last_notice == (
            f"This session was saved by a newer Petrophyter (format {version}); "
            "settings this version does not know were not loaded.")
    else:
        assert svc.last_notice == ""


def test_notice_reset_on_next_load_and_major_guard(tmp_path):
    newer = tmp_path / "n.json"
    newer.write_text(json.dumps({"_session_version": "2.8", "rw": 0.1}))
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps({"_session_version": "2.1", "rw": 0.1}))
    major = tmp_path / "m.json"
    major.write_text(json.dumps({"_session_version": "3.0", "rw": 0.1}))
    svc = SessionService()
    assert svc.load_session(str(newer)) is not None and svc.last_notice
    assert svc.load_session(str(ok)) is not None and svc.last_notice == ""
    assert svc.load_session(str(newer)) is not None and svc.last_notice
    assert svc.load_session(str(major)) is None
    assert svc.last_notice == "" and "newer Petrophyter" in svc.last_error
