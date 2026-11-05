"""LRLC before / after baseline: SW_BASE, NET_PAY_BASE_FLAG, zone columns, validation block."""
import numpy as np
import pandas as pd
import pytest

from tests.golden.cases import build_case
from tests.lrlc_teststeps import register_test_steps  # noqa: F401
from tests.test_lrlc_pipeline import case, codes, lrlc_p, planned, run  # noqa: F401
from tests.test_lrlc_pipeline_l2 import interior, laminated_well, run_well, ts_p

BASE_COLUMNS = {"SW_BASE", "NET_PAY_BASE_FLAG"}


def test_baseline_equals_an_lrlc_off_run():
    frame, _ = laminated_well()
    off_r, off_s = run_well(frame)
    r, s = run_well(frame, ts_p())
    pd.testing.assert_series_equal(r["SW_BASE"], off_r["SW"], check_exact=True, check_names=False)
    pd.testing.assert_series_equal(r["NET_PAY_BASE_FLAG"], off_r["NET_PAY_FLAG"],
                                   check_exact=True, check_names=False)
    val = s["lrlc"]["validation"]
    assert val["well"]["net_pay_base"] == off_s["net_pay"]
    assert val["well"]["hcpv_net_pay_base"] == pytest.approx(off_s["hcpv_net_pay"])
    assert val["well"]["net_pay"] == s["net_pay"]
    assert val["well"]["delta"] == pytest.approx(s["net_pay"] - off_s["net_pay"])
    assert val["pay_sw"] == "resistivity" and val["n_shf_held"] == 0
    assert "shf" not in val


def test_correction_adds_pay_in_the_laminated_well():
    frame, _ = laminated_well()
    r, s = run_well(frame, ts_p(), sw_cutoff=0.5)
    assert s["lrlc"]["validation"]["well"]["delta"] > 0
    assert int(r["NET_PAY_FLAG"].sum()) > int(r["NET_PAY_BASE_FLAG"].sum())


def test_columns_absent_without_an_active_step():
    frame, _ = laminated_well()
    r, s = run_well(frame, ts_p(steps=()))
    assert not BASE_COLUMNS & set(r.columns)
    assert "validation" not in s["lrlc"]


def test_zone_rows_carry_before_columns(case):  # noqa: F811
    lrlc = lrlc_p(zone_steps={"UPPER": ["laminated"], "LOWER": []}, vlam_source="constant",
                  vlam_const=0.2)
    r, s = run(case, lrlc)
    for row in s["zones"]:
        assert {"net_pay_base", "avg_sw_pay_base", "hcpv_net_pay_base"} <= set(row)
    lower = next(z for z in s["zones"] if z["zone"] == "LOWER")
    assert lower["net_pay_base"] == lower["net_pay"]          # no correction there
    assert lower["hcpv_net_pay_base"] == pytest.approx(lower["hcpv_net_pay"])
    names = [z["zone"] for z in s["lrlc"]["validation"]["zones"]]
    assert names == [z["zone"] for z in s["zones"]]
    off = run(case)
    assert all("net_pay_base" not in z for z in off[1]["zones"])


def test_every_segment_writes_the_columns_when_one_zone_has_a_step(case):  # noqa: F811
    data, mapping, params, tops = case
    params = planned(params, "LOWER")
    lrlc = lrlc_p(zone_steps={"UPPER": [], "LOWER": ["laminated"]}, vlam_source="constant",
                  vlam_const=0.2)
    r, s = run_pipeline_with(case, params, lrlc)
    assert BASE_COLUMNS <= set(r.columns)
    assert r["SW_BASE"].notna().sum() == r["SW"].notna().sum()
    assert pd.api.types.is_integer_dtype(r["NET_PAY_BASE_FLAG"])
    upper = r["ZONE"] == "UPPER"
    pd.testing.assert_series_equal(r.loc[upper, "SW_BASE"], r.loc[upper, "SW"],
                                   check_exact=True, check_names=False)
    lower = r["ZONE"] == "LOWER"
    assert not r.loc[lower, "SW_BASE"].equals(r.loc[lower, "SW"])
    assert {rec["segment"] for rec in s["lrlc"]["chain"]} == {"zone"}


def run_pipeline_with(case_tuple, params, lrlc):
    from modules.pipeline import run_pipeline
    data, mapping, _, tops = case_tuple
    return run_pipeline(data.copy(), dict(mapping), {**params, "lrlc": lrlc}, formation_tops=tops)


def test_shf_pay_switch_baseline_differs_only_on_fallback_samples(register_test_steps):  # noqa: F811
    from modules.pipeline import run_pipeline
    data, mapping, params, tops = build_case("shf_core_pc")
    off = run_pipeline(data.copy(), dict(mapping), dict(params), formation_tops=tops)
    lrlc = lrlc_p(steps=["test_scale"], zones=())
    r, s = run_pipeline(data.copy(), dict(mapping), {**params, "lrlc": lrlc}, formation_tops=tops)
    assert s["shf"]["pay_active"]
    held = r["SW_SHF"].notna()
    assert held.any() and (~held).any()
    diff = r["NET_PAY_FLAG"] != r["NET_PAY_BASE_FLAG"]
    assert not diff[held].any()                               # SHF Sw decides there, both ways
    val = s["lrlc"]["validation"]
    assert val["pay_sw"] == "SHF where available" and val["n_shf_held"] == int(held.sum())
    assert "LRLC_BASE_SHF_HELD" in codes(s)
    base, corrected = val["shf"]["well"]["base"], val["shf"]["well"]["corrected"]
    assert corrected == s["shf"]["stats"]["well"]
    assert set(base) == {"n", "bias", "rmse", "mae", "r2"} and base["n"] == corrected["n"]
    # the baseline Sw is the Sw of the run without LRLC
    pd.testing.assert_series_equal(r["SW_BASE"], off[0]["SW"], check_exact=True, check_names=False)
