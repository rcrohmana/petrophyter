"""General-n Simandoux: the vectorised solver equals the old per-row brentq loop."""

import numpy as np
import pandas as pd
import pytest
from scipy.optimize import brentq

from modules.petrophysics import SW_MIN_POROSITY, PetrophysicsCalculator

RW, RSH, A_, M_ = 0.05, 5.0, 0.62, 2.15


def old_simandoux_raw(rt, phie, vsh, rw, rsh, a, m, n):
    """Private copy of the per-row loop that solved general-n Simandoux."""
    A = np.power(np.maximum(phie, SW_MIN_POROSITY), m) / (a * rw)
    B = np.clip(vsh, 0.0, 1.0) / rsh
    C = 1 / np.maximum(rt, 0.001)
    sw_list = []
    for i in range(len(rt)):
        A_i, B_i, C_i = A[i], B[i], C[i]
        if np.isnan(A_i) or np.isnan(B_i) or np.isnan(C_i):
            sw_list.append(np.nan)
            continue

        def f(sw_val):
            return A_i * np.power(sw_val, n) + B_i * sw_val - C_i

        if f(1.0) <= 0:
            sw_list.append(1.0)
            continue
        try:
            sw_list.append(brentq(f, 0.0, 1.0))
        except Exception:
            sw_list.append(np.nan)
    return np.array(sw_list, dtype=float)


def _calc(rt):
    df = pd.DataFrame({"DEPTH": np.arange(len(rt), dtype=float), "RT": rt})
    return PetrophysicsCalculator(df)


def _realistic(seed=0, size=3000):
    rng = np.random.default_rng(seed)
    return (
        rng.lognormal(2.0, 1.2, size),
        rng.uniform(0.02, 0.35, size),
        rng.uniform(0.0, 0.8, size),
    )


def _stress(seed=5, size=4000):
    rng = np.random.default_rng(seed)
    rt = rng.uniform(0.05, 300, size)
    phie = rng.uniform(0, 0.35, size)
    vsh = rng.uniform(-0.1, 1.2, size)
    rt[::97] = np.nan
    phie[::89] = np.nan
    vsh[::83] = np.nan
    phie[::53] = 0.0005
    rt[::71] = 1e-4
    return rt, phie, vsh


def _reference(rt, phie, vsh, n):
    calc = _calc(rt)
    raw = old_simandoux_raw(rt, phie, vsh, RW, RSH, A_, M_, n)
    solve, no_phi = calc._sw_valid_mask(rt, phie)
    return calc._finish_sw("SW_SIMAN", raw, solve, no_phi).to_numpy()


def _got(rt, phie, vsh, n):
    calc = _calc(rt)
    idx = calc.data.index
    return calc.calculate_sw_simandoux(
        "RT", pd.Series(phie, index=idx), pd.Series(vsh, index=idx), RW, RSH, A_, M_, n
    ).to_numpy()


@pytest.mark.parametrize("n", [1.7, 2.1, 2.6])
@pytest.mark.parametrize("kind", ["realistic", "stress"])
def test_general_n_matches_old_loop_exactly(kind, n):
    rt, phie, vsh = _realistic() if kind == "realistic" else _stress()
    got = _got(rt, phie, vsh, n)
    ref = _reference(rt, phie, vsh, n)
    np.testing.assert_array_equal(got, ref)


def test_stress_set_covers_wet_and_nan_rows():
    rt, phie, vsh = _stress()
    got = _got(rt, phie, vsh, 2.1)
    assert np.isnan(got).any()
    assert (got == 1.0).any()
    # rows where f(1) <= 0 are present
    A = np.power(np.maximum(phie, SW_MIN_POROSITY), M_) / (A_ * RW)
    B = np.clip(vsh, 0, 1) / RSH
    C = 1 / np.maximum(rt, 0.001)
    assert np.nansum((A + B - C) <= 0) > 0


def test_n_equal_two_uses_closed_form():
    rt, phie, vsh = _realistic(seed=2)
    got = _got(rt, phie, vsh, 2.0)
    A = np.power(np.maximum(phie, SW_MIN_POROSITY), M_) / (A_ * RW)
    B = np.clip(vsh, 0, 1) / RSH
    C = 1 / np.maximum(rt, 0.001)
    closed = np.clip((-B + np.sqrt(np.maximum(B**2 + 4 * A * C, 0))) / (2 * A), 0, 1)
    calc = _calc(rt)
    solve, no_phi = calc._sw_valid_mask(rt, phie)
    expected = np.where(no_phi, 1.0, np.where(solve, closed, np.nan))
    np.testing.assert_array_equal(got, expected)
