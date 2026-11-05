"""LrlcService additions for the laminated-sand / mineral / Qv settings."""

import os

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from modules.lrlc.config import lrlc_defaults
from services.lrlc_service import LrlcService

from tests.test_session_v2 import three_wells  # noqa: F401


@pytest.fixture
def well(three_wells):  # noqa: F811
    model, keys = three_wells
    model.mark_clean()
    return model, model.project.get(keys[0]), model.project.get(keys[1])


def _results(n=200, zones=True):
    depth = np.arange(1000.0, 1000.0 + 0.5 * n, 0.5)
    vsh = np.tile(np.concatenate([np.full(25, 0.02), np.full(25, 0.9)]), n // 50 + 1)[:n]
    phit = np.where(vsh < 0.5, 0.26, 0.08)
    df = pd.DataFrame({"DEPTH": depth, "VSH": vsh, "PHIT": phit})
    if zones:
        df["ZONE"] = np.where(depth < 1050.0, "UPPER", "LOWER")
    return df


# ---- set_setting ---------------------------------------------------------------------
@pytest.mark.parametrize("block,key,value", [
    ("qv", "min_pairs", 1), ("qv", "min_pairs", 2.5), ("qv", "pair_tol_ft", -1.0),
    ("qv", "qv_max", "x"), ("qv", "qv_max", True), ("qv", "qv_max", float("nan")),
    ("guard", "enabled", 1), ("guard", "vlam_share", 0.99), ("thomas_stieber", "enabled", "yes"),
    ("thomas_stieber", "clean_pct", 120.0), ("thomas_stieber", "vsh_column", ""),
    ("thomas_stieber", "vsh_column", 3), ("pyrite", "u_fluid", 5.0), ("diagnosis", "min_n", 0),
    ("qv", "nokey", 1), ("nonblock", "x", 1)])
def test_set_setting_rejects_invalid(well, block, key, value):
    model, _, _ = well
    before = dict(model.project.lrlc.get(block) or {})
    assert LrlcService.set_setting(model, block, key, value) is False
    assert (model.project.lrlc.get(block) or {}) == before
    assert not model.dirty


def test_set_setting_accepts_valid_and_coerces(well):
    model, _, _ = well
    assert LrlcService.set_setting(model, "qv", "min_pairs", 8.0)
    assert model.project.lrlc["qv"]["min_pairs"] == 8 and isinstance(
        model.project.lrlc["qv"]["min_pairs"], int)
    assert LrlcService.set_setting(model, "qv", "qv_max", 4)
    assert isinstance(model.project.lrlc["qv"]["qv_max"], float)
    assert LrlcService.set_setting(model, "thomas_stieber", "vsh_column", "VSH_GR")
    assert LrlcService.set_setting(model, "diagnosis", "rw_low", 0.05)
    assert model.dirty


def test_set_setting_unchanged_writes_nothing(well):
    model, _, _ = well
    assert LrlcService.set_setting(model, "qv", "min_pairs", 5)
    assert not model.dirty


def test_set_setting_old_blocks_still_work(well):
    model, _, _ = well
    assert LrlcService.set_setting(model, "movable", "swirr_column", "SWIRR_BUCKLES")
    assert model.dirty


# ---- guard / RT_SBC ------------------------------------------------------------------
def test_set_guard_enabled(well):
    model, _, _ = well
    assert LrlcService.set_guard_enabled(model, True) is False
    assert not model.dirty
    assert LrlcService.set_guard_enabled(model, False) is True
    assert model.project.lrlc["guard"]["enabled"] is False and model.dirty
    assert LrlcService.set_guard_enabled(model, False) is False
    assert LrlcService.set_guard_enabled(model, True) is True
    assert model.project.lrlc["guard"] == lrlc_defaults()["guard"]


def test_set_rt_sbc(well):
    model, alpha, _ = well
    alpha.curve_mapping["RT"] = "ILD"
    assert LrlcService.set_rt_sbc(model, alpha, True) is True
    assert alpha.lrlc_curves["RT_SBC"] == "ILD" and model.dirty
    model.mark_clean()
    assert LrlcService.set_rt_sbc(model, alpha, True) is False and not model.dirty
    alpha.curve_mapping["RT"] = "RT2"
    assert LrlcService.set_rt_sbc(model, alpha, True) is True
    assert alpha.lrlc_curves["RT_SBC"] == "RT2"
    assert LrlcService.set_rt_sbc(model, alpha, False) is True
    assert "RT_SBC" not in alpha.lrlc_curves
    assert LrlcService.set_rt_sbc(model, alpha, False) is False


def test_set_rt_sbc_needs_mapped_rt_and_well(well):
    model, alpha, beta = well
    beta.curve_mapping["RT"] = ""
    assert LrlcService.set_rt_sbc(model, beta, True) is False
    assert LrlcService.set_rt_sbc(model, None, True) is False
    assert not model.dirty and "RT_SBC" not in beta.lrlc_curves


# ---- Thomas-Stieber proposals / apply --------------------------------------------------
def test_ts_proposals_none_without_results(well):
    model, alpha, _ = well
    assert LrlcService.ts_proposals(model, alpha) is None
    alpha.results = pd.DataFrame({"DEPTH": [1.0, 2.0]})
    assert LrlcService.ts_proposals(model, alpha) is None


def test_ts_proposals_per_zone(well):
    model, alpha, _ = well
    alpha.results = _results(400)
    props = LrlcService.ts_proposals(model, alpha)
    assert set(props) == {"UPPER", "LOWER"}
    for p in props.values():
        assert p.ok and p.phi_max == pytest.approx(0.26) and p.phi_sh == pytest.approx(0.08)


def test_ts_proposals_unzoned_and_vsh_column(well):
    model, alpha, _ = well
    df = _results(400, zones=False)
    df["VSH_X"] = df["VSH"]
    df["VSH"] = 0.5
    alpha.results = df
    props = LrlcService.ts_proposals(model, alpha)
    assert len(props) == 1 and not next(iter(props.values())).ok
    LrlcService.set_setting(model, "thomas_stieber", "vsh_column", "VSH_X")
    props = LrlcService.ts_proposals(model, alpha)
    assert next(iter(props.values())).ok


@pytest.mark.parametrize("level,zone,use_ds", [
    ("project", None, False), ("project", "Upper", False),
    ("well", None, True), ("well", "Upper", True)])
def test_apply_endpoints_levels(well, level, zone, use_ds):
    model, alpha, beta = well
    ds = beta if use_ds else None
    assert LrlcService.apply_endpoints(model, level, zone, 0.30, 0.10, ds=ds) is True
    store = model.project.lrlc["params"] if level == "project" else beta.lrlc
    d = store["default"] if zone is None else store["zones"]["UPPER"]
    assert d["phi_max"] == 0.30 and d["phi_sh"] == 0.10
    assert model.dirty
    model.mark_clean()
    assert LrlcService.apply_endpoints(model, level, zone, 0.30, 0.10, ds=ds) is False
    assert not model.dirty


@pytest.mark.parametrize("pm,ps", [(0.30, 0.29), (0.30, 0.285), (0.05, 0.01), (0.3, None),
                                   (None, 0.1), (0.3, float("nan")), (0.5, 0.1), (0.3, -0.1)])
def test_apply_endpoints_rejects_invalid(well, pm, ps):
    model, _, _ = well
    assert LrlcService.apply_endpoints(model, "project", None, pm, ps) is False
    assert model.project.lrlc["params"] == {"default": {}, "zones": {}}
    assert not model.dirty


def test_apply_endpoints_bad_level(well):
    model, _, _ = well
    assert LrlcService.apply_endpoints(model, "nowhere", None, 0.3, 0.1) is False


# ---- CEC -------------------------------------------------------------------------------
class _Core:
    def __init__(self, depth, cec):
        self.depth_col = "Depth"
        self.data = pd.DataFrame({"Depth": depth, "CEC": cec})


def test_cec_proposal(well):
    model, alpha, _ = well
    assert LrlcService.cec_proposal(model, alpha, None) is None      # no core, no results
    res = _results(400)
    alpha.results = res
    assert LrlcService.cec_proposal(model, alpha, None) is None      # still no core
    depths = [1015.0, 1017.5, 1040.0, 1045.0, 1070.0, 1095.0]
    vsh = [float(res.loc[(res.DEPTH - d).abs().idxmin(), "VSH"]) for d in depths]
    alpha.core_data = _Core(depths, [30.0 * v for v in vsh])
    LrlcService.set_setting(model, "qv", "min_pairs", 2)
    fit = LrlcService.cec_proposal(model, alpha, None)
    assert fit is not None and fit.ok and fit.cec_shale == pytest.approx(30.0)
    LrlcService.set_setting(model, "qv", "min_pairs", 50)
    fit = LrlcService.cec_proposal(model, alpha, None)
    assert fit is not None and not fit.ok
    LrlcService.set_setting(model, "qv", "min_pairs", 2)
    zone_fit = LrlcService.cec_proposal(model, alpha, "UPPER")
    assert zone_fit is not None and zone_fit.n == 4


def test_cec_proposal_without_cec_column(well):
    model, alpha, _ = well
    alpha.results = _results(100)
    core = _Core([1005.0], [1.0])
    core.data = core.data.drop(columns="CEC")
    alpha.core_data = core
    assert LrlcService.cec_proposal(model, alpha, None) is None


# ---- apply_remediation --------------------------------------------------------------------
def test_apply_remediation_writes_valid_keys(well):
    model, _, beta = well
    written = LrlcService.apply_remediation(
        model, "project", "Lower", {"s_warn": 0.7, "pyr_vpyr": 0.02})
    assert sorted(written) == ["pyr_vpyr", "s_warn"]
    assert model.project.lrlc["params"]["zones"]["LOWER"] == {"s_warn": 0.7, "pyr_vpyr": 0.02}
    assert model.dirty
    model.mark_clean()
    assert LrlcService.apply_remediation(
        model, "project", "Lower", {"s_warn": 0.7, "pyr_vpyr": 0.02}) == []
    assert not model.dirty
    assert LrlcService.apply_remediation(model, "well", None, {"qv_source": "estimate"},
                                         ds=beta) == ["qv_source"]
    assert beta.lrlc["default"] == {"qv_source": "estimate"}


def test_apply_remediation_all_or_nothing(well):
    model, _, _ = well
    assert LrlcService.apply_remediation(
        model, "project", None, {"s_warn": 0.7, "not_a_key": 1}) == []
    assert LrlcService.apply_remediation(
        model, "project", None, {"s_warn": 0.7, "pyr_vpyr": 9.0}) == []
    assert LrlcService.apply_remediation(model, "project", None, {}) == []
    assert LrlcService.apply_remediation(model, "bad", None, {"s_warn": 0.7}) == []
    assert model.project.lrlc["params"] == {"default": {}, "zones": {}}
    assert not model.dirty


def test_apply_remediation_cross_key_rules(well):
    model, alpha, _ = well
    # s_warn must stay below s_invalid (built-in 0.95)
    assert LrlcService.apply_remediation(model, "project", None, {"s_warn": 0.97}) == []
    assert LrlcService.apply_remediation(
        model, "project", None, {"s_warn": 0.97, "s_invalid": 0.98}) == ["s_warn", "s_invalid"]
    # against the resolved value at a lower level
    assert LrlcService.apply_remediation(model, "well", None, {"s_warn": 0.99}, ds=alpha) == []
    assert alpha.lrlc in ({}, None)
    # end-points: phi_sh < phi_max - 0.02
    assert LrlcService.apply_remediation(
        model, "project", None, {"phi_max": 0.3, "phi_sh": 0.29}) == []
    assert LrlcService.apply_remediation(
        model, "project", None, {"phi_max": 0.3, "phi_sh": 0.1}) == ["phi_max", "phi_sh"]
    assert LrlcService.apply_remediation(model, "well", "Upper", {"phi_sh": 0.29}, ds=alpha) == []
    assert alpha.lrlc in ({}, None)


def test_apply_remediation_well_without_ds_uses_active(well):
    model, alpha, beta = well
    assert model.active_well is beta
    assert LrlcService.apply_remediation(model, "well", None, {"cec_shale": 40.0}) == ["cec_shale"]
    assert beta.lrlc["default"]["cec_shale"] == 40.0


# ---- stale ---------------------------------------------------------------------------------
def test_ladder_writes_change_the_hash_when_lrlc_is_on(well):
    model, alpha, _ = well
    LrlcService.set_enabled(model, True)
    h0 = model.well_params_hash(alpha)
    LrlcService.apply_endpoints(model, "project", None, 0.3, 0.1)
    h1 = model.well_params_hash(alpha)
    assert h1 != h0
    LrlcService.apply_remediation(model, "well", None, {"s_warn": 0.7}, ds=alpha)
    assert model.well_params_hash(alpha) != h1
    h2 = model.well_params_hash(alpha)
    LrlcService.apply_remediation(model, "well", None, {"s_warn": 0.7}, ds=alpha)   # unchanged
    assert model.well_params_hash(alpha) == h2
