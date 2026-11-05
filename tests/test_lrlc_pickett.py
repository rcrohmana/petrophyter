"""Pickett wet-point selection and the robust wet-line fit."""

import numpy as np
import pytest

from modules.lrlc import pickett
from modules.lrlc.pickett import (fit_pickett, iso_sw_line, normalise_rt_for_temperature,
                                  wet_points)
from modules.param_scopes import VALID_RANGES

A, M_TRUE, RW_TRUE = 1.0, 2.0, 0.05


def _wet(n=60, noise=0.0, seed=1):
    rng = np.random.default_rng(seed)
    phi = rng.uniform(0.06, 0.35, n)
    rt = A * RW_TRUE / phi ** M_TRUE
    rt = rt * 10 ** rng.normal(0, noise, n)
    return phi, rt


def test_ranges_match_param_scopes():
    assert pickett.M_RANGE == (1.3, 3.0) and pickett.RW_RANGE == (0.005, 10.0)
    assert pickett.M_RANGE == VALID_RANGES["m"] and pickett.RW_RANGE == VALID_RANGES["rw"]


def test_recovers_m_and_a_rw():
    phi, rt = _wet(noise=0.01)
    fit = fit_pickett(phi, rt, np.ones(len(phi), bool), a=A, m_current=2.0)
    assert fit.status == "ok" and fit.n_points == len(phi)
    assert fit.m == pytest.approx(M_TRUE, rel=0.01)
    assert fit.a_rw == pytest.approx(A * RW_TRUE, rel=0.01)
    assert fit.r2 > 0.99 and fit.se_m > 0 and fit.se_c > 0 and fit.iterations >= 1
    assert fit.phi_range == (phi.min(), phi.max())


def test_exact_data_does_not_blow_up():
    phi, rt = _wet(noise=0.0)
    fit = fit_pickett(phi, rt, np.ones(len(phi), bool), a=A, m_current=2.0)
    assert fit.status == "ok" and fit.m == pytest.approx(M_TRUE, rel=1e-6)


def test_rw_is_a_rw_over_a():
    phi = np.linspace(0.08, 0.3, 30)
    rt = 0.62 * 0.04 / phi ** 2.15
    fit = fit_pickett(phi, rt, np.ones(30, bool), a=0.62, m_current=2.0)
    assert fit.a_rw == pytest.approx(0.62 * 0.04, rel=1e-6)
    assert fit.rw == pytest.approx(0.04, rel=1e-6)
    assert fit.rw == pytest.approx(fit.a_rw / 0.62)


def test_huber_resists_outliers():
    phi, rt = _wet(n=60, noise=0.01)
    rt = rt.copy()
    rt[:6] *= 30.0     # hydrocarbon-like high-Rt outliers
    mask = np.ones(60, bool)
    robust = fit_pickett(phi, rt, mask, a=A, m_current=2.0)
    x, y = np.log10(phi), np.log10(rt)
    ols_m = -np.polyfit(x, y, 1)[0]
    assert abs(robust.m - M_TRUE) < abs(ols_m - M_TRUE)
    assert robust.m == pytest.approx(M_TRUE, rel=0.03)


def test_rw_only_mode():
    phi, rt = _wet(noise=0.01)
    fit = fit_pickett(phi, rt, np.ones(len(phi), bool), a=A, m_current=2.0, fit_mode="rw_only")
    assert fit.status == "ok" and fit.m == 2.0
    assert fit.rw == pytest.approx(RW_TRUE, rel=0.01)
    assert np.isnan(fit.se_m)
    # a wrong fixed m biases Rw, the slope is not refitted
    off = fit_pickett(phi, rt, np.ones(len(phi), bool), a=A, m_current=2.3, fit_mode="rw_only")
    assert off.m == 2.3 and abs(off.rw - RW_TRUE) > 0.01 * RW_TRUE


def test_rw_only_ignores_narrow_range():
    phi = np.full(15, 0.2)
    rt = np.full(15, A * RW_TRUE / 0.2 ** 2)
    assert fit_pickett(phi, rt, np.ones(15, bool), a=A, m_current=2.0).status \
        == "narrow_porosity_range"
    fit = fit_pickett(phi, rt, np.ones(15, bool), a=A, m_current=2.0, fit_mode="rw_only")
    assert fit.status == "ok" and fit.rw == pytest.approx(RW_TRUE, rel=1e-6)


def test_status_codes():
    phi, rt = _wet()
    ones = np.ones(len(phi), bool)
    assert fit_pickett(phi, rt, np.zeros(len(phi), bool), a=A, m_current=2.0).status == "no_data"
    assert fit_pickett([], [], [], a=A, m_current=2.0).status == "no_data"
    few = np.zeros(len(phi), bool)
    few[:5] = True
    f = fit_pickett(phi, rt, few, a=A, m_current=2.0, min_points=10)
    assert f.status == "too_few_points" and f.n_points == 5
    assert fit_pickett(phi, rt, few, a=A, m_current=2.0, min_points=5).status != "too_few_points"
    narrow = (phi > 0.20) & (phi < 0.22)
    p2 = np.linspace(0.20, 0.22, 20)
    assert fit_pickett(p2, A * RW_TRUE / p2 ** 2, np.ones(20, bool), a=A,
                       m_current=2.0).status == "narrow_porosity_range"
    assert narrow.sum() >= 0
    # slope far too steep / shallow
    hi_m = fit_pickett(phi, A * RW_TRUE / phi ** 3.5, ones, a=A, m_current=2.0)
    assert hi_m.status == "m_outside_range" and hi_m.m == pytest.approx(3.5, rel=0.01)
    lo_m = fit_pickett(phi, A * RW_TRUE / phi ** 1.0, ones, a=A, m_current=2.0)
    assert lo_m.status == "m_outside_range"
    big_rw = fit_pickett(phi, 100.0 / phi ** 2, ones, a=A, m_current=2.0)
    assert big_rw.status == "rw_outside_range" and big_rw.rw == pytest.approx(100.0, rel=0.01)
    small_rw = fit_pickett(phi, 0.0005 / phi ** 2, ones, a=A, m_current=2.0)
    assert small_rw.status == "rw_outside_range"


def test_nonpositive_and_nan_points_dropped():
    phi, rt = _wet(n=30)
    phi[0], rt[1], rt[2] = np.nan, -1.0, np.nan
    fit = fit_pickett(phi, rt, np.ones(30, bool), a=A, m_current=2.0)
    assert fit.n_points == 27 and fit.status == "ok"


def test_wet_points_proposal_picks_low_rt_envelope():
    rng = np.random.default_rng(2)
    n = 600
    phi = rng.uniform(0.06, 0.35, n)
    wet_rt = A * RW_TRUE / phi ** M_TRUE
    rt = wet_rt * 10 ** rng.uniform(0, 1.0, n)        # up to 10x above the wet line
    vsh = rng.uniform(0, 0.4, n)
    s = {"vsh_max": 0.25, "phi_min": 0.05, "wet_quantile": 0.10, "n_bins": 8}
    mask = wet_points(phi, rt, vsh, s)
    assert 0 < mask.sum() < 0.25 * n
    assert not mask[vsh > 0.25].any()
    assert np.median(rt[mask] / wet_rt[mask]) < 1.8
    fit = fit_pickett(phi, rt, mask, a=A, m_current=2.0)
    assert fit.status == "ok" and fit.m == pytest.approx(M_TRUE, rel=0.15)


def test_wet_points_sparse_bins_and_filters():
    phi = np.array([0.1] * 4 + [0.3] * 20)
    rt = np.linspace(1, 20, 24)
    mask = wet_points(phi, rt, np.zeros(24), {"n_bins": 2})
    assert not mask[:4].any() and mask[4:].any()       # 4-sample bin skipped
    assert not wet_points(phi, rt, np.zeros(24), {"phi_min": 0.5}).any()
    assert not wet_points(phi, rt, np.ones(24), {"vsh_max": 0.25}).any()
    assert wet_points(phi, rt, None, {"n_bins": 2}).any()


def test_manual_boxes_applied_in_order():
    phi, rt = _wet(n=100, noise=0.05)
    vsh = np.zeros(100)
    s = {"n_bins": 4}
    auto = wet_points(phi, rt, vsh, s)
    box_all = (0.0, 1.0, 1e-3, 1e6)
    removed = wet_points(phi, rt, vsh, s, [("remove",) + box_all])
    assert not removed.any()
    added = wet_points(phi, rt, vsh, s, [("add",) + box_all])
    assert added.all()
    both = wet_points(phi, rt, vsh, s, [("add",) + box_all, ("remove", 0.0, 0.2, 1e-3, 1e6)])
    assert both.sum() == (phi > 0.2).sum()
    first_remove = wet_points(phi, rt, vsh, s, [("remove", 0.0, 0.2, 1e-3, 1e6)])
    assert first_remove.sum() <= auto.sum() and not first_remove[phi <= 0.2].any()
    with pytest.raises(ValueError):
        wet_points(phi, rt, vsh, s, [("zap",) + box_all])


def test_iso_sw_line():
    phi = np.array([0.1, 0.2])
    assert iso_sw_line(phi, 0.62, 0.05, 2.0, 2.0, 1.0) == pytest.approx(0.62 * 0.05 / phi ** 2)
    assert iso_sw_line(phi, 1.0, 0.05, 2.0, 2.0, 0.5) == pytest.approx(
        4 * iso_sw_line(phi, 1.0, 0.05, 2.0, 2.0, 1.0))


def test_temperature_normalisation():
    rt = np.array([10.0, 20.0, 5.0])
    factor = np.array([2.0, 0.5, np.nan])
    out = normalise_rt_for_temperature(rt, factor)
    assert out[0] == 5.0 and out[1] == 40.0 and np.isnan(out[2])
    assert normalise_rt_for_temperature(rt, 2.0) == pytest.approx(rt / 2.0)
    # fitted Rw at reference temperature equals the Rw the formation had at reference
    phi = np.linspace(0.08, 0.3, 30)
    f = np.full(30, 0.6)                    # hot formation: Rw and Rt lower by the factor
    rt_hot = f * A * RW_TRUE / phi ** 2
    raw = fit_pickett(phi, rt_hot, np.ones(30, bool), a=A, m_current=2.0)
    norm = fit_pickett(phi, normalise_rt_for_temperature(rt_hot, f), np.ones(30, bool),
                       a=A, m_current=2.0)
    assert raw.rw == pytest.approx(0.6 * RW_TRUE, rel=1e-6)
    assert norm.rw == pytest.approx(RW_TRUE, rel=1e-6)
