"""LRLC settings: defaults, tolerant merge, ladder, curves, flat["lrlc"] and the service."""

import copy
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from models.app_model import AppModel
from models.project import Project
from modules.las_parser import find_curve
from modules.lrlc.config import (
    AUX_ROLES, LRLC_DEFAULTS, LRLC_PARAM_DEFAULTS, LRLC_RANGES, clean_curves, clean_param,
    clean_well_lrlc, lrlc_defaults, lrlc_in_use, merge_lrlc, resolve_lrlc, resolve_lrlc_sources)
from services.lrlc_service import LrlcService

from tests.test_session_v2 import three_wells  # noqa: F401


def test_defaults_shape_and_copy():
    d = lrlc_defaults()
    assert d == LRLC_DEFAULTS and d is not LRLC_DEFAULTS
    d["screening"]["use_rs"] = False
    d["pickett"]["iso_sw"].append(0.1)
    assert LRLC_DEFAULTS["screening"]["use_rs"] is True
    assert LRLC_DEFAULTS["pickett"]["iso_sw"] == [1.0, 0.8, 0.6, 0.4, 0.2]
    assert d["enabled"] is False and d["params"] == {"default": {}, "zones": {}}
    assert AUX_ROLES == ("RM", "RS", "RXO", "PEF", "DTS", "HIRES")


def test_merge_tolerant():
    assert merge_lrlc(None) == lrlc_defaults()
    assert merge_lrlc("junk") == lrlc_defaults()
    out = merge_lrlc({
        "enabled": True, "bogus": 1,
        "screening": {"use_rs": False, "use_gas_flag": "yes", "other": 1},
        "rt_cutoff": {"enabled": True},
        "movable": {"swirr_column": "SWIRR_BUCKLES"},
        "pickett": {"vsh_max": 0.3, "fit_mode": "nonsense", "n_bins": 6, "iso_sw": [1, 0.5]},
        "buckles": {"bvw_lines": "x"},
        "params": {"default": {"screen_rt_max": 8, "rt_steps": ["a", "zzz"], "bad": 1,
                               "screen_min_score": 99},
                   "zones": {"upper": {"movable_tol": 0.1}, "lower": {"movable_tol": 9}}},
    })
    assert out["enabled"] is True and "bogus" not in out
    assert out["screening"] == {"use_gas_flag": True, "use_rs": False}
    assert out["rt_cutoff"] == {"enabled": True}
    assert out["movable"]["swirr_column"] == "SWIRR_BUCKLES"
    assert out["pickett"]["vsh_max"] == 0.3 and out["pickett"]["fit_mode"] == "m_and_rw"
    assert out["pickett"]["n_bins"] == 6 and out["pickett"]["iso_sw"] == [1.0, 0.5]
    assert out["buckles"] == LRLC_DEFAULTS["buckles"]
    assert out["params"]["default"] == {"screen_rt_max": 8.0, "rt_steps": ["a", "zzz"]}
    assert out["params"]["zones"] == {"UPPER": {"movable_tol": 0.1}}


@pytest.mark.parametrize("key", sorted(LRLC_RANGES))
def test_clean_param_ranges(key):
    lo, hi = LRLC_RANGES[key]
    assert clean_param(key, lo)[1] and clean_param(key, hi)[1]
    assert clean_param(key, lo - 0.01 if key != "screen_min_score" else lo - 1) == (None, False)
    assert clean_param(key, hi + 1) == (None, False)
    assert clean_param(key, True) == (None, False)
    assert clean_param(key, float("nan")) == (None, False)
    assert clean_param(key, "3") == (None, False)


def test_clean_param_types():
    assert clean_param("screen_min_score", 5.0) == (5, True)
    assert clean_param("screen_min_score", 4.5) == (None, False)
    assert clean_param("cut_sw_target", None) == (None, True)
    assert clean_param("screen_rt_max", None) == (None, False)
    assert clean_param("rt_fallback", "previous") == ("previous", True)
    assert clean_param("rt_fallback", "zero") == (None, False)
    assert clean_param("rt_steps", ["unknown_step"]) == (["unknown_step"], True)
    assert clean_param("rt_steps", [1]) == (None, False)
    assert clean_param("rt_steps", "abc") == (None, False)
    assert clean_param("nope", 1) == (None, False)


def test_ladder_order_per_key():
    project = {"default": {"screen_rt_max": 6.0, "movable_tol": 0.1},
               "zones": {"UPPER": {"screen_rt_max": 7.0, "movable_tol": 0.12,
                                   "screen_min_score": 4}}}
    well = {"default": {"screen_rt_max": 8.0},
            "zones": {"UPPER": {"screen_rt_max": 9.0}}}
    upper = resolve_lrlc(project, well, "upper")
    assert upper["screen_rt_max"] == 9.0          # well zone
    assert upper["movable_tol"] == 0.12           # project zone beats project default
    assert upper["screen_min_score"] == 4
    assert upper["rt_fallback"] == "nan"          # built-in
    lower = resolve_lrlc(project, well, "LOWER")
    assert lower["screen_rt_max"] == 8.0          # well default beats project
    assert lower["movable_tol"] == 0.1
    assert resolve_lrlc(project, well, None)["screen_rt_max"] == 8.0
    # well default beats project zone
    mixed = resolve_lrlc({"default": {}, "zones": {"UPPER": {"screen_rt_max": 7.0}}},
                         {"default": {"screen_rt_max": 8.0}, "zones": {}}, "UPPER")
    assert mixed["screen_rt_max"] == 8.0
    assert resolve_lrlc({}, {}, "UPPER") == LRLC_PARAM_DEFAULTS


def test_sources():
    project = {"default": {"screen_rt_max": 6.0},
               "zones": {"UPPER": {"movable_tol": 0.12}}}
    well = {"default": {"rt_fallback": "previous"},
            "zones": {"UPPER": {"screen_rt_max": 9.0}}}
    src = resolve_lrlc_sources(project, well, "UPPER")
    assert src["screen_rt_max"] == (9.0, "well zone")
    assert src["rt_fallback"] == ("previous", "well default")
    assert src["movable_tol"] == (0.12, "project zone")
    assert src["screen_contrast_max"] == (2.0, "built-in")
    assert resolve_lrlc_sources(project, well, "LOWER")["screen_rt_max"] == (6.0, "project default")
    assert resolve_lrlc_sources(project, well, "LOWER")["movable_tol"] == (0.05, "built-in")
    # resolving never mutates the stores nor the defaults
    src["rt_steps"][0].append("x")
    assert LRLC_PARAM_DEFAULTS["rt_steps"] == []


def test_clean_well_and_curves():
    assert clean_well_lrlc(None) == {} and clean_well_lrlc({"default": {}, "zones": {}}) == {}
    assert clean_well_lrlc({"default": {"bad": 1}}) == {}
    assert clean_well_lrlc({"default": {"movable_tol": 0.1}}) == {
        "default": {"movable_tol": 0.1}, "zones": {}}
    assert clean_curves({"RXO": "MSFL", "RM": None, "ZZZ": "x", "PEF": "", "DTS": 3}) == {
        "RXO": "MSFL", "RM": None}
    assert clean_curves("x") == {}


def test_aliases_appended():
    assert find_curve(["DEPT", "msfl"], "RXO") == "msfl"
    assert find_curve(["DTSM"], "DTS") == "DTSM"
    assert find_curve(["RXOZ"], "RS") == "RXOZ" and find_curve(["RXOZ"], "RXO") is None
    assert find_curve(["X"], "HIRES") is None


def test_lrlc_in_use(three_wells):  # noqa: F811
    model, keys = three_wells
    project = model.project
    assert lrlc_in_use(project) is False
    project.lrlc["pickett"]["vsh_max"] = 0.3
    project.lrlc["buckles"]["bvw_lines"] = [0.05]
    assert lrlc_in_use(project) is False           # Workbench-only blocks do not count
    project.lrlc["screening"]["use_rs"] = False
    assert lrlc_in_use(project) is True
    project.lrlc = lrlc_defaults()
    project.lrlc["params"]["zones"]["UPPER"] = {"movable_tol": 0.1}
    assert lrlc_in_use(project) is True
    project.lrlc = lrlc_defaults()
    project.lrlc["enabled"] = True
    assert lrlc_in_use(project) is True
    project.lrlc = lrlc_defaults()
    project.get(keys[0]).lrlc_curves = {"RXO": None}
    assert lrlc_in_use(project) is True
    project.get(keys[0]).lrlc_curves = {}
    project.get(keys[1]).lrlc = {"default": {"movable_tol": 0.1}, "zones": {}}
    assert lrlc_in_use(project) is True
    project.get(keys[1]).lrlc = {}
    assert lrlc_in_use(project) is False
    assert lrlc_in_use(object()) is False


def test_project_and_well_defaults(three_wells):  # noqa: F811
    model, keys = three_wells
    p = model.project
    assert p.lrlc == lrlc_defaults()
    ds = p.get(keys[0])
    assert ds.lrlc == {} and ds.lrlc_curves == {}
    p.lrlc["enabled"] = True
    p.clear()
    assert p.lrlc == lrlc_defaults()
    assert Project().lrlc == lrlc_defaults()


# ---------------------------------------------------------------------------
# flat["lrlc"]
# ---------------------------------------------------------------------------
def test_flat_absent_and_hash_unchanged_when_off(three_wells):  # noqa: F811
    model, keys = three_wells
    ds = model.project.get(keys[0])
    before = model.params_for_well(ds)
    h = model.well_params_hash(ds)
    assert "lrlc" not in before
    LrlcService.set_enabled(model, True)
    assert "lrlc" in model.params_for_well(ds)
    LrlcService.set_enabled(model, False)
    after = model.params_for_well(ds)
    assert "lrlc" not in after and after == before
    assert model.well_params_hash(ds) == h
    # configured but disabled: still no key
    LrlcService.set_param(model, "project", None, "screen_rt_max", 7.0)
    assert "lrlc" not in model.params_for_well(ds)


def test_flat_content_and_resolution(three_wells):  # noqa: F811
    model, keys = three_wells
    alpha, beta = model.project.get(keys[0]), model.project.get(keys[1])
    LrlcService.set_enabled(model, True)
    LrlcService.set_param(model, "project", None, "screen_rt_max", 6.0)
    LrlcService.set_param(model, "project", "lower", "movable_tol", 0.1)
    LrlcService.set_param(model, "well", "SHALEZONE", "screen_min_score", 4, ds=beta)
    LrlcService.set_setting(model, "rt_cutoff", "enabled", True)
    LrlcService.set_setting(model, "pickett", "vsh_max", 0.3)

    flat = model.params_for_well(alpha)["lrlc"]
    assert flat["enabled"] is True and flat["rt_cutoff"] == {"enabled": True}
    assert flat["screening"] == {"use_gas_flag": True, "use_rs": True}
    assert flat["movable"] == {"swirr_column": "SWIRR"}
    assert "pickett" not in flat and "buckles" not in flat
    assert set(flat["curves"]) == set(AUX_ROLES)
    assert flat["curves"]["RM"] is None and flat["curves"]["RXO"] is None
    assert flat["resolved"]["default"]["screen_rt_max"] == 6.0
    assert flat["resolved"]["zones"]["LOWER"]["movable_tol"] == 0.1
    assert flat["resolved"]["zones"]["LOWER"]["screen_rt_max"] == 6.0
    assert "SHALEZONE" not in flat["resolved"]["zones"]       # alpha's ladder only

    zones = model.zones_for(beta)
    fb = model.params_for_well(beta)["lrlc"]["resolved"]["zones"]
    assert "SHALEZONE" in fb and fb["SHALEZONE"]["screen_min_score"] == 4
    for z in zones:
        assert z in fb
    assert "LOWER" in fb                                      # named in the project ladder


def test_flat_curves_auto_and_assigned(three_wells):  # noqa: F811
    model, keys = three_wells
    ds = model.project.get(keys[0])
    LrlcService.set_enabled(model, True)
    h0 = model.well_params_hash(ds)
    ds.las_data["MSFL"] = 1.0
    ds.las_data["RILM"] = 2.0
    flat = model.params_for_well(ds)["lrlc"]["curves"]
    assert flat["RXO"] == "MSFL" and flat["RM"] == "RILM"
    LrlcService.set_curve(model, ds, "RXO", None)               # explicit not-used
    LrlcService.set_curve(model, ds, "RM", "GR")
    LrlcService.set_curve(model, ds, "PEF", "NOT_THERE")        # dropped at resolution
    flat = model.params_for_well(ds)["lrlc"]["curves"]
    assert flat["RXO"] is None and flat["RM"] == "GR" and flat["PEF"] is None
    LrlcService.clear_curve(model, ds, "RXO")
    assert model.params_for_well(ds)["lrlc"]["curves"]["RXO"] == "MSFL"
    assert model.well_params_hash(ds) != h0


def test_workbench_blocks_do_not_change_params(three_wells):  # noqa: F811
    model, keys = three_wells
    ds = model.project.get(keys[0])
    LrlcService.set_enabled(model, True)
    before = model.params_for_well(ds)
    LrlcService.set_setting(model, "pickett", "n_bins", 6)
    LrlcService.set_setting(model, "buckles", "bvw_lines", [0.05])
    assert model.params_for_well(ds) == before
    LrlcService.set_setting(model, "screening", "use_rs", False)
    assert model.params_for_well(ds) != before


# ---------------------------------------------------------------------------
# service
# ---------------------------------------------------------------------------
def test_service_marks_dirty_and_validates(three_wells):  # noqa: F811
    model, keys = three_wells
    ds = model.project.get(keys[0])
    model.dirty = False
    assert LrlcService.set_param(model, "project", None, "screen_rt_max", 500) is False
    assert model.dirty is False
    assert model.project.lrlc["params"] == {"default": {}, "zones": {}}
    assert LrlcService.set_param(model, "project", "upper", "screen_rt_max", 7) is True
    assert model.dirty is True
    assert model.project.lrlc["params"]["zones"] == {"UPPER": {"screen_rt_max": 7.0}}
    assert LrlcService.clear_param(model, "project", "UPPER", "screen_rt_max") is True
    assert model.project.lrlc["params"] == {"default": {}, "zones": {}}
    assert LrlcService.clear_param(model, "project", "UPPER", "screen_rt_max") is False

    assert LrlcService.set_param(model, "well", None, "rt_steps", ["x"], ds=ds)
    assert ds.lrlc == {"default": {"rt_steps": ["x"]}, "zones": {}}
    assert LrlcService.clear_param(model, "well", None, "rt_steps", ds=ds)
    assert ds.lrlc == {}                                         # empty = not in use
    assert LrlcService.set_setting(model, "movable", "bogus", 1) is False
    assert LrlcService.set_setting(model, "nope", "x", 1) is False
    assert LrlcService.set_curve(model, ds, "BOGUS", "X") is False


class _Fit:
    def __init__(self, status="ok", m=1.987, rw=0.04321):
        self.status, self.m, self.rw = status, m, rw


def test_apply_pickett(three_wells):  # noqa: F811
    model, keys = three_wells
    ds = model.project.get(keys[1])
    model.dirty = False
    assert LrlcService.apply_pickett(model, ds, "UPPER", _Fit("too_few_points"), True) is False
    assert model.dirty is False and "m" not in ds.overrides
    assert LrlcService.apply_pickett(model, ds, "upper", _Fit(), True) is True
    entry_m = ds.zone_overrides["UPPER"]["m"]
    entry_rw = ds.zone_overrides["UPPER"]["rw"]
    assert entry_m["value"] == 1.987 and entry_m["source"] == "pickett"
    assert entry_m["method"] == "Pickett wet-point fit" and entry_m.get("date")
    assert entry_rw["value"] == 0.0432 and entry_rw["mode"] == "manual"
    assert model.dirty is True
    assert LrlcService.apply_pickett(model, ds, None, _Fit(m=2.1), False) is True
    assert ds.overrides["m"]["value"] == 2.1
    assert ds.overrides["rw"]["mode"] == "auto"
