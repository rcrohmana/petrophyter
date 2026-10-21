"""Saturation-height physics: constants, conversions, Leverett J, height and Sw(J) (pure)."""

import json

import numpy as np
import pytest

from modules import shf


def test_constants():
    assert shf.PSI_PER_FT_PER_GCC == 0.433527
    assert shf.J_CONST == pytest.approx(0.2166, abs=1e-4)
    assert shf.SIGMA_COS_DEFAULTS["hg-air"] == pytest.approx(abs(480 * np.cos(np.radians(140))), abs=0.05)
    assert shf.SIGMA_COS_DEFAULTS["oil-water"] == pytest.approx(30 * np.cos(np.radians(30)), abs=0.05)
    assert shf.SIGMA_COS_DEFAULTS["oil-brine"] == pytest.approx(48 * np.cos(np.radians(30)), abs=0.05)


def test_worked_j_check():
    j = shf.leverett_j(10.0, 100.0, 0.20, 367.7)
    assert j == pytest.approx(0.1317, abs=5e-4)


def test_worked_hg_to_oil_water_height():
    pc_res = shf.lab_to_reservoir(100.0, 367.7, 26.0)
    assert pc_res == pytest.approx(7.07, abs=0.01)
    assert shf.height_from_pc(pc_res, 0.28) == pytest.approx(58.2, abs=0.1)


def test_j_same_from_lab_or_reservoir_pc():
    pc_lab, s_lab, s_res = 55.0, 367.7, 26.0
    pc_res = shf.lab_to_reservoir(pc_lab, s_lab, s_res)
    assert shf.leverett_j(pc_lab, 30, 0.15, s_lab) == pytest.approx(shf.leverett_j(pc_res, 30, 0.15, s_res))


def test_height_pc_roundtrip_and_j_at_height():
    h = np.array([10.0, 50.0, 200.0])
    pc = shf.pc_from_height(h, 0.28)
    assert shf.height_from_pc(pc, 0.28) == pytest.approx(h)
    j = shf.j_at_height(h, 100.0, 0.2, 0.28, 26.0)
    assert j == pytest.approx(shf.leverett_j(pc, 100.0, 0.2, 26.0))
    assert j == pytest.approx(0.2166 * 0.433527 * 0.28 * h * np.sqrt(500) / 26.0, rel=1e-3)


def test_leverett_j_invalid_inputs_are_nan():
    j = shf.leverett_j([1.0, 1.0, 1.0], [0.0, 10.0, -1.0], [0.2, 0.0, 0.2], 26.0)
    assert np.isnan(j).all()


def test_delta_rho_inputs_and_errors():
    assert shf.delta_rho(0.28) == pytest.approx(0.28)
    assert shf.delta_rho({"water_density": 1.03, "fluid_density": 0.75}) == pytest.approx(0.28)
    assert shf.delta_rho(shf.ZoneFluids(1.10, 0.75)) == pytest.approx(0.35)
    with pytest.raises(ValueError):
        shf.delta_rho(shf.ZoneFluids(0.7, 0.75))
    with pytest.raises(ValueError):
        shf.height_from_pc(5.0, 0.0)


def test_sw_from_j_power():
    p = {"c": 0.3, "d": -0.6}
    entry = p["c"] ** (-1 / p["d"])
    j = np.array([0.0, entry * 0.5, entry, 1.0, 10.0, np.nan])
    sw = shf.sw_from_j(j, "power", p)
    assert sw[0] == 1.0 and sw[1] == 1.0 and sw[2] == pytest.approx(1.0)
    assert sw[3] == pytest.approx(0.3) and sw[4] == pytest.approx(0.3 * 10 ** -0.6)
    assert np.isnan(sw[5])


def test_sw_from_j_brooks_corey_goes_to_swi():
    p = {"J_d": 0.5, "lam": 2.0, "Swi": 0.15}
    sw = shf.sw_from_j([0.1, 0.5, 1.0, 1e6], "brooks_corey", p)
    assert sw[0] == 1.0 and sw[1] == pytest.approx(1.0)
    assert sw[2] == pytest.approx(0.15 + 0.85 * 0.25)
    assert sw[3] == pytest.approx(0.15, abs=1e-6)
    assert ((sw >= 0) & (sw <= 1)).all()


def test_sw_from_j_unknown_model():
    with pytest.raises(ValueError):
        shf.sw_from_j([1.0], "thomeer", {})


def test_sw_from_hg():
    assert shf.sw_from_hg([0.0, 0.7, 1.2]) == pytest.approx([1.0, 0.3, 0.0])


def _fit(model="brooks_corey", params=None):
    params = params or {"J_d": 0.5, "lam": 2.0, "Swi": 0.15}
    return shf.ShfFit(rock_type="All", model=model, params=params, basis="core_pc")


def test_sw_shf_vectorised_and_below_contact():
    fit = _fit()
    h = np.array([-5.0, 0.0, 10.0, 100.0, np.nan, 100.0, 100.0])
    k = np.array([100.0, 100.0, 100.0, 100.0, 100.0, 0.0, np.nan])
    phi = np.full(7, 0.2)
    sw = shf.sw_shf(h, k, phi, fit, 0.28, 26.0)
    assert sw[0] == 1.0 and sw[1] == 1.0
    assert 0.15 <= sw[3] < sw[2] <= 1.0
    assert np.isnan(sw[4:]).all()
    j = shf.j_at_height(100.0, 100.0, 0.2, 0.28, 26.0)
    assert sw[3] == pytest.approx(float(shf.sw_from_j(j, "brooks_corey", fit.params)))


def test_sw_shf_zone_brine_density_follows_analytic_ratio():
    fit = _fit("power", {"c": 0.3, "d": -0.6})
    h, k, phi = 80.0, 150.0, 0.18
    base = float(shf.sw_shf(h, k, phi, fit, shf.ZoneFluids(1.03, 0.75), 26.0))
    salty = float(shf.sw_shf(h, k, phi, fit, shf.ZoneFluids(1.13, 0.75), 26.0))
    ratio = (1.13 - 0.75) / (1.03 - 0.75)
    assert salty / base == pytest.approx(ratio ** fit.params["d"], rel=1e-6)


def test_sw_shf_no_params_gives_nan():
    fit = shf.ShfFit(rock_type="All", model="power", params=None, basis="core_pc",
                     status=shf.STATUS_INSUFFICIENT)
    assert np.isnan(shf.sw_shf([10.0, 20.0], 100.0, 0.2, fit, 0.28, 26.0)).all()


def test_shf_fit_round_trips_as_json():
    fit = shf.ShfFit(rock_type="2", model="power", params={"c": 0.3, "d": -0.6}, basis="log",
                     n_samples=4, n_points=30, rmse=0.02, bias=float("nan"), r2=0.9,
                     se={"c": 0.01, "d": float("inf")}, wells=["A"], status="ok")
    d = json.loads(json.dumps(fit.to_dict(), allow_nan=False))
    assert d["bias"] is None and d["se"]["d"] is None
    back = shf.ShfFit.from_dict(d)
    assert back.rock_type == "2" and back.basis == "log" and back.params == {"c": 0.3, "d": -0.6}
    assert back.to_dict() == d


def test_empty_fit_round_trip_and_estimate_dict():
    fit = shf.ShfFit(rock_type="All", model="power", params=None, basis="core_pc",
                     status=shf.STATUS_INSUFFICIENT, message="x")
    d = json.loads(json.dumps(fit.to_dict(), allow_nan=False))
    assert shf.ShfFit.from_dict(d).params is None
    est = shf.FwlEstimate(shf.FWL_NOT_IDENTIFIABLE, reason="r", rmse_profile=[None, 0.1])
    assert shf.FwlEstimate.from_dict(json.loads(json.dumps(est.to_dict()))).to_dict() == est.to_dict()
