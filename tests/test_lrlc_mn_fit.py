"""Variable m fit: recovery, robustness, parameter dropping, minimum points, implausible m."""

import numpy as np
import pytest

from modules.lrlc import variable_mn as vm


def _wet_data(n=200, coef=(1.9, 0.5, 0.3), a=1.0, rw=0.05, seed=3, phi_rng=(0.08, 0.30),
              vsh_rng=(0.0, 0.5)):
    rng = np.random.default_rng(seed)
    phi = rng.uniform(*phi_rng, n)
    vsh = rng.uniform(*vsh_rng, n)
    m = coef[0] + coef[1] * phi + coef[2] * vsh
    rt = a * rw / phi ** m
    return phi, vsh, rt


def test_noise_free_recovery():
    phi, vsh, rt = _wet_data()
    r = vm.fit_variable_m(phi, rt, vsh, 0.05, 1.0)
    assert r.status == "ok" and r.apply_allowed
    assert r.free == ("c0", "c1", "c2")
    assert r.coef[:3] == pytest.approx([1.9, 0.5, 0.3], abs=1e-8)
    assert r.coef[3] == 0.0
    assert r.rmse_ln_rt < 1e-8 and r.n_used == 200
    assert r.m_fit == pytest.approx(r.m_obs, abs=1e-8)
    assert r.se[0] is not None and r.se[3] is None


def test_a_and_rw_array():
    phi, vsh, rt = _wet_data(a=0.81)
    depth = np.linspace(0, 1, phi.size)
    rw = 0.05 * (1.0 + 0.5 * depth)             # temperature-corrected style Rw array
    rt = 0.81 * rw / phi ** (1.9 + 0.5 * phi + 0.3 * vsh)
    r = vm.fit_variable_m(phi, rt, vsh, rw, 0.81)
    assert r.coef[:3] == pytest.approx([1.9, 0.5, 0.3], abs=1e-8)


def test_robust_to_outliers():
    phi, vsh, rt = _wet_data(n=300)
    rng = np.random.default_rng(9)
    bad = rng.choice(300, 15, replace=False)    # 5 percent
    rt = rt.copy()
    rt[bad] *= 8.0
    r = vm.fit_variable_m(phi, rt, vsh, 0.05, 1.0)
    true_m = 1.9 + 0.5 * phi[r.index] + 0.3 * vsh[r.index]
    robust = np.median(np.abs(r.m_fit - true_m))
    cols = np.column_stack([np.log(phi), phi * np.log(phi), vsh * np.log(phi)])
    ols = np.linalg.lstsq(cols, np.log(0.05 / rt), rcond=None)[0]
    plain = np.median(np.abs(cols[r.index] @ ols / np.log(phi[r.index]) - true_m))
    assert robust < 0.02 and robust < 0.5 * plain
    assert r.status == "ok"


def test_narrow_porosity_range_fixes_c1():
    phi, vsh, rt = _wet_data(coef=(2.0, 0.0, 0.3), phi_rng=(0.20, 0.23))
    r = vm.fit_variable_m(phi, rt, vsh, 0.05, 1.0)
    assert r.free == ("c0", "c2") and r.coef[1] == 0.0
    assert r.status == "phi range too small, c1 fixed"
    assert r.apply_allowed
    assert r.coef[0] == pytest.approx(2.0, abs=1e-8)


def test_narrow_vsh_range_fixes_c2_and_both_gives_pickett_m():
    phi, vsh, rt = _wet_data(coef=(2.0, 0.0, 0.0), vsh_rng=(0.1, 0.12))
    r = vm.fit_variable_m(phi, rt, vsh, 0.05, 1.0)
    assert r.free == ("c0", "c1") and "c2 fixed" in r.status
    phi, vsh, rt = _wet_data(coef=(2.1, 0, 0), phi_rng=(0.2, 0.22), vsh_rng=(0.1, 0.12))
    r = vm.fit_variable_m(phi, rt, vsh, 0.05, 1.0)
    assert r.free == ("c0",) and r.pickett_equivalent
    assert r.coef[0] == pytest.approx(2.1, abs=1e-8)
    assert "Pickett" in r.message


def test_minimum_points():
    phi, vsh, rt = _wet_data(n=40)
    r = vm.fit_variable_m(phi, rt, vsh, 0.05, 1.0)       # 3 free -> 45 needed
    assert r.status == "insufficient points" and r.coef is None and not r.apply_allowed
    phi, vsh, rt = _wet_data(n=45)
    assert vm.fit_variable_m(phi, rt, vsh, 0.05, 1.0).status == "ok"
    phi, vsh, rt = _wet_data(n=14, coef=(2.0, 0, 0), phi_rng=(0.2, 0.21), vsh_rng=(0.1, 0.11))
    assert vm.fit_variable_m(phi, rt, vsh, 0.05, 1.0).status == "insufficient points"
    r = vm.fit_variable_m(np.array([]), np.array([]), np.array([]), 0.05, 1.0)
    assert r.status == "insufficient points"


def test_exclusion_counts():
    phi, vsh, rt = _wet_data(n=120)
    phi = phi.copy(); rt = rt.copy()
    phi[0] = np.nan
    rt[1] = -1.0
    phi[2] = 0.01                                   # outside the window
    wet = np.ones(120, dtype=bool)
    wet[3:13] = False
    r = vm.fit_variable_m(phi, rt, vsh, 0.05, 1.0, wet_mask=wet)
    assert r.excluded == {"not_wet": 10, "nan": 2, "window": 1}
    assert r.n_used == 120 - 10 - 2 - 1
    assert 0 not in r.index and 3 not in r.index


def test_implausible_m_blocks_apply():
    phi, vsh, rt = _wet_data(coef=(4.4, 0.0, 0.0))
    r = vm.fit_variable_m(phi, rt, vsh, 0.05, 1.0)
    assert r.status == "implausible m" and not r.apply_allowed
    assert r.n_implausible == r.n_used
    assert r.message == f"fitted m is outside 1-4 for {r.n_used} points"
    assert r.coef is not None                       # shown, but not appliable


def test_options_override():
    phi, vsh, rt = _wet_data(n=100)
    r = vm.fit_variable_m(phi, rt, vsh, 0.05, 1.0, options={"phi_window": [0.15, 0.25]})
    assert r.excluded["window"] > 0 and r.n_used < 100
    r = vm.fit_variable_m(phi, rt, vsh, 0.05, 1.0, options={"min_points_per_param": 40})
    assert r.status == "insufficient points"


def test_fit_writes_nothing():
    phi, vsh, rt = _wet_data()
    snapshot = (phi.copy(), vsh.copy(), rt.copy())
    vm.fit_variable_m(phi, rt, vsh, 0.05, 1.0)
    for a, b in zip((phi, vsh, rt), snapshot):
        assert np.array_equal(a, b)
