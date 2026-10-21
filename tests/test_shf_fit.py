"""Saturation-height fits and FWL estimation on synthetic data (pure)."""

import numpy as np
import pytest

from modules import shf

POWER = {"c": 0.3, "d": -0.6}
BC = {"J_d": 0.4, "lam": 2.0, "Swi": 0.12}
SIGMA_LAB = 367.7


def _curves(model, params, n_samples=6, n_pts=12, noise=0.0, seed=0, pc_scale=1.0):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n_samples):
        k = 10 ** rng.uniform(0.5, 2.5)
        phi = rng.uniform(0.10, 0.28)
        j = np.geomspace(0.1, 20.0, n_pts) * rng.uniform(0.9, 1.1)
        pc = j * SIGMA_LAB / (shf.J_CONST * np.sqrt(k / phi)) * pc_scale
        jj = shf.leverett_j(pc, k, phi, SIGMA_LAB)
        sw = shf.sw_from_j(jj, model, params) + rng.normal(0, noise, n_pts)
        out.append(shf.PcCurve(pc, np.clip(sw, 0.01, 1.0), k, phi, SIGMA_LAB, well="A", sample=f"s{i}"))
    return out


def test_power_noise_free_recovery():
    fit = shf.fit_core_pc(_curves("power", POWER), "All", "power")
    assert fit.status == "ok" and fit.basis == "core_pc"
    assert fit.params["c"] == pytest.approx(POWER["c"], rel=0.01)
    assert fit.params["d"] == pytest.approx(POWER["d"], rel=0.01)
    assert fit.rmse < 1e-3 and fit.n_samples == 6 and fit.n_points == 72
    assert fit.wells == ["A"]


def test_brooks_corey_noise_free_recovery():
    fit = shf.fit_core_pc(_curves("brooks_corey", BC, n_samples=6, n_pts=20), "All", "brooks_corey")
    assert fit.status == "ok"
    for name, value in BC.items():
        assert fit.params[name] == pytest.approx(value, rel=0.01), name


def test_noisy_recovery_within_three_sigma():
    sigma = 0.02
    fit = shf.fit_core_pc(_curves("power", POWER, noise=sigma, seed=4), "All", "power")
    assert fit.status == "ok"
    for name in ("c", "d"):
        assert abs(fit.params[name] - POWER[name]) < 3 * fit.se[name], name
    assert fit.rmse == pytest.approx(sigma, abs=0.01)


def test_noisy_brooks_corey_close():
    fit = shf.fit_core_pc(_curves("brooks_corey", BC, n_pts=25, noise=0.015, seed=2), "All", "brooks_corey")
    assert fit.status == "ok"
    assert fit.params["Swi"] == pytest.approx(BC["Swi"], abs=0.04)
    assert fit.params["lam"] == pytest.approx(BC["lam"], rel=0.2)


def test_sample_weighting_keeps_short_curve_alive():
    # A long curve on law A and a short one on law B: per-sample weights give the short one
    # as much say as the long one, per-point weights let the long one dominate.
    law_a, law_b = {"c": 0.3, "d": -0.6}, {"c": 0.6, "d": -0.4}
    long_ = _curves("power", law_a, n_samples=1, n_pts=60, seed=1)
    short = _curves("power", law_b, n_samples=2, n_pts=6, seed=2)
    curves = long_ + short
    by_sample = shf.fit_core_pc(curves, "All", "power", weight_by="sample")
    by_point = shf.fit_core_pc(curves, "All", "power", weight_by="point")
    assert by_sample.status == by_point.status == "ok"
    assert by_sample.weight_by == "sample" and by_point.weight_by == "point"
    assert abs(by_point.params["d"] - law_a["d"]) < abs(by_sample.params["d"] - law_a["d"])
    assert abs(by_sample.params["d"] - law_b["d"]) < abs(by_point.params["d"] - law_b["d"])


def test_parameters_respect_bounds():
    # A near-flat curve wants d > -0.05: the fit stops at the bound.
    rng = np.random.default_rng(0)
    curves = []
    for i in range(4):
        pc = np.geomspace(1.0, 100.0, 10)
        curves.append(shf.PcCurve(pc, 0.5 + rng.normal(0, 0.001, 10), 50.0, 0.2, SIGMA_LAB))
    fit = shf.fit_core_pc(curves, "All", "power")
    lo, hi = shf.BOUNDS["power"]["d"]
    assert lo <= fit.params["d"] <= hi
    assert fit.params["d"] == pytest.approx(hi, abs=1e-2)
    assert shf.BOUNDS["power"]["c"][0] <= fit.params["c"] <= shf.BOUNDS["power"]["c"][1]


def test_min_pc_drops_closure_points():
    curves = _curves("power", POWER)
    all_pts = shf.fit_core_pc(curves, "All", "power")
    cut = shf.fit_core_pc(curves, "All", "power", min_pc_psi=float(np.median(curves[0].pc_psi)))
    assert cut.n_points < all_pts.n_points


@pytest.mark.parametrize("model,n_samples,n_pts", [("power", 2, 10), ("power", 4, 1),
                                                   ("brooks_corey", 4, 10), ("brooks_corey", 6, 2)])
def test_insufficient_data_status(model, n_samples, n_pts):
    fit = shf.fit_core_pc(_curves("power", POWER, n_samples=n_samples, n_pts=n_pts), "3", model)
    assert fit.status == shf.STATUS_INSUFFICIENT
    assert fit.params is None and fit.rock_type == "3" and "needs at least" in fit.message


def test_invalid_points_are_dropped():
    c = shf.PcCurve([1, 2, 3, np.nan, 5], [0.9, 1.5, 0.0, 0.5, np.nan], 10.0, 0.2, 72.0)
    fit = shf.fit_core_pc([c], "All", "power")
    assert fit.n_points == 1 and fit.status == shf.STATUS_INSUFFICIENT


def test_unknown_model_and_weight_rejected():
    with pytest.raises(ValueError):
        shf.fit_core_pc([], "All", "thomeer")
    with pytest.raises(ValueError):
        shf.fit_core_pc([], "All", "power", weight_by="well")


def _log_profile(fwl=7300.0, noise=0.0, seed=0, model="power", params=POWER):
    rng = np.random.default_rng(seed)
    tvd = np.arange(7000.0, 7400.0, 0.5)
    k = 10 ** (1.5 + 0.5 * np.sin(tvd / 11.0))
    phi = 0.18 + 0.03 * np.cos(tvd / 7.0)
    fit = shf.ShfFit("All", model, dict(params), "core_pc")
    sw = shf.sw_shf(fwl - tvd, k, phi, fit, 0.28, 26.0)
    sw = np.clip(sw + rng.normal(0, noise, len(sw)), 0.02, 1.0)
    return tvd, k, phi, sw, fit


def test_log_basis_fit_recovers_and_is_labelled():
    tvd, k, phi, sw, _ = _log_profile()
    fit = shf.fit_log_sw(7300.0 - tvd, k, phi, sw, "All", "power", 0.28, 26.0, wells=["A"])
    assert fit.basis == "log" and fit.status == "ok"
    assert fit.params["c"] == pytest.approx(POWER["c"], rel=0.02)
    assert fit.params["d"] == pytest.approx(POWER["d"], rel=0.02)
    assert fit.to_dict()["basis"] == "log"


def test_log_fit_insufficient_and_uses_zone_density():
    tvd, k, phi, sw, _ = _log_profile()
    few = shf.fit_log_sw((7300.0 - tvd)[:5], k[:5], phi[:5], sw[:5], "All", "power", 0.28, 26.0)
    assert few.status == shf.STATUS_INSUFFICIENT
    f1 = shf.fit_log_sw(7300.0 - tvd, k, phi, sw, "All", "power", shf.ZoneFluids(1.03, 0.75), 26.0)
    f2 = shf.fit_log_sw(7300.0 - tvd, k, phi, sw, "All", "power", shf.ZoneFluids(1.13, 0.75), 26.0)
    assert f1.params["c"] != pytest.approx(f2.params["c"], rel=1e-3)


def test_estimate_fwl_within_two_feet():
    tvd, k, phi, sw, fit = _log_profile(fwl=7300.0, noise=0.02, seed=3)
    est = shf.estimate_fwl(tvd, k, phi, sw, ["All"] * len(tvd), {"All": fit}, 0.28, 26.0)
    assert est.status == "ok" and est.identifiable
    assert abs(est.fwl_ft - 7300.0) < 2.0
    assert est.interval_ft[0] <= est.fwl_ft <= est.interval_ft[1]
    assert len(est.grid_ft) == len(est.rmse_profile) > 1000


def test_estimate_fwl_per_rock_type_and_zone_density():
    tvd, k, phi, sw, fit = _log_profile(fwl=7250.0)
    labels = np.where(tvd < 7150, "1", "2")
    fits = {"1": fit, "2": fit}
    est = shf.estimate_fwl(tvd, k, phi, sw, labels, fits, 0.28, 26.0)
    assert abs(est.fwl_ft - 7250.0) < 2.0
    # With another brine density the same logs imply a different contact.
    other = shf.estimate_fwl(tvd, k, phi, sw, labels, fits, shf.ZoneFluids(1.13, 0.75), 26.0)
    assert abs(other.fwl_ft - est.fwl_ft) > 2.0 or not other.identifiable


def test_estimate_fwl_all_water_not_identifiable():
    tvd, k, phi, _, fit = _log_profile()
    est = shf.estimate_fwl(tvd, k, phi, np.ones(len(tvd)), ["All"] * len(tvd), {"All": fit}, 0.28, 26.0)
    assert est.status == shf.FWL_NOT_IDENTIFIABLE and est.fwl_ft is None and not est.identifiable
    assert "not identifiable" in est.reason


def test_estimate_fwl_plateau_not_identifiable():
    # Hydrocarbon at the irreducible saturation everywhere: any deeper contact fits equally.
    tvd = np.arange(7000.0, 7020.0, 0.5)
    k, phi = np.full(len(tvd), 100.0), np.full(len(tvd), 0.2)
    fit = shf.ShfFit("All", "brooks_corey", dict(BC), "core_pc")
    sw = np.full(len(tvd), BC["Swi"])
    est = shf.estimate_fwl(tvd, k, phi, sw, ["All"] * len(tvd), {"All": fit}, 0.28, 26.0)
    assert est.status == shf.FWL_NOT_IDENTIFIABLE and est.fwl_ft is None


def test_estimate_fwl_insufficient_samples():
    tvd, k, phi, sw, fit = _log_profile()
    est = shf.estimate_fwl(tvd[:3], k[:3], phi[:3], sw[:3], ["All"] * 3, {"All": fit}, 0.28, 26.0)
    assert est.status == shf.FWL_INSUFFICIENT
    est = shf.estimate_fwl(tvd, k, phi, sw, ["9"] * len(tvd), {}, 0.28, 26.0)
    assert est.status == shf.FWL_INSUFFICIENT
