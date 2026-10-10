"""Vectorised implementations versus private copies of the old per-row loops."""

import time

import numpy as np
import pandas as pd
import pytest
from scipy.optimize import brentq

from modules import las_utils
from modules.las_handler import LASHandler, export_merged_las
from modules.petrophysics import PetrophysicsCalculator


# ---------------------------------------------------------------------------
# Reference (old) implementations
# ---------------------------------------------------------------------------
def old_linear(x_new, x, y, gap_limit):
    result = np.full(len(x_new), np.nan)
    sort_idx = np.argsort(x)
    xs, ys = x[sort_idx], y[sort_idx]
    for i, xi in enumerate(x_new):
        r = np.searchsorted(xs, xi)
        if r == 0:
            if abs(xi - xs[0]) <= gap_limit:
                result[i] = ys[0]
        elif r >= len(xs):
            if abs(xi - xs[-1]) <= gap_limit:
                result[i] = ys[-1]
        else:
            xl, xr = xs[r - 1], xs[r]
            if (xr - xl) <= gap_limit:
                t = (xi - xl) / (xr - xl)
                result[i] = ys[r - 1] * (1 - t) + ys[r] * t
    return result


def old_nearest(x_new, x, y, max_dist):
    dtype = float if np.issubdtype(y.dtype, np.number) else object
    result = np.full(len(x_new), np.nan, dtype=dtype)
    for i, xi in enumerate(x_new):
        d = np.abs(x - xi)
        k = np.argmin(d)
        if d[k] <= max_dist:
            result[i] = y[k]
    return result


def old_replace_null(df, null_values, depth_col="DEPTH", tolerance=1e-6):
    for col in df.columns:
        if col == depth_col:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            for null in null_values:
                mask = np.abs(df[col] - null) < tolerance
                df.loc[mask, col] = np.nan
    return df


def old_ws(rt, phie, rw, a, m, n, qv, B):
    out, no_root, fail = [], 0, 0
    cw = 1.0 / rw
    for rt_i, phie_i in zip(rt, phie):
        if np.isnan(rt_i) or np.isnan(phie_i) or phie_i <= 0.001 or rt_i <= 0:
            out.append(np.nan)
            continue
        f_star = a / np.power(phie_i, m)
        ct = 1.0 / rt_i

        def f(sw):
            sw = max(sw, 1e-6)
            return (1.0 / f_star) * (cw * np.power(sw, n) + (B * qv) * np.power(sw, n - 1)) - ct

        try:
            if f(0.001) * f(1.0) < 0:
                sol = np.clip(brentq(f, 0.001, 1.0), 0, 1)
            else:
                no_root += 1
                sol = 1.0 if f(1.0) < 0 else 0.0
        except Exception:
            fail += 1
            sol = np.nan
        out.append(sol)
    return np.array(out), {"no_root": no_root, "failed": fail}


def old_dw(rt, phie, rw, a, m, n, swb, rwb):
    out, no_root, fail = [], 0, 0
    cw, cwb = 1.0 / rw, 1.0 / rwb
    for rt_i, phi_i in zip(rt, phie):
        if np.isnan(rt_i) or np.isnan(phi_i) or phi_i <= 0.001 or rt_i <= 0:
            out.append(np.nan)
            continue
        f_t = a / np.power(phi_i, m)
        ctm = 1.0 / rt_i

        def f(swt):
            swt = max(swt, swb + 1e-4)
            return (np.power(swt, n) / f_t) * (cw + (cwb - cw) * (swb / swt)) - ctm

        try:
            lb = min(max(swb + 0.001, 0.001), 0.99)
            lo, hi = f(lb), f(1.0)
            if lo * hi < 0:
                sol = brentq(f, lb, 1.0)
            else:
                no_root += 1
                sol = 1.0 if abs(hi) < abs(lo) else swb
            sol = np.clip(sol, 0, 1)
        except Exception:
            fail += 1
            sol = np.nan
        out.append(sol)
    return np.array(out), {"no_root": no_root, "failed": fail}


def old_classify(k):
    if np.isnan(k):
        return "Unknown"
    elif k < 1:
        return "Tight"
    elif k < 10:
        return "Poor"
    elif k < 100:
        return "Fair"
    elif k < 1000:
        return "Good"
    return "Excellent"


def _same_nan(a, b):
    assert np.array_equal(np.isnan(a), np.isnan(b))


def _calc(rt, phi):
    df = pd.DataFrame({"DEPTH": np.arange(len(rt), dtype=float), "RT": rt})
    return PetrophysicsCalculator(df)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("seed", range(4))
def test_linear_gap_interp_matches_old(seed):
    rng = np.random.default_rng(seed)
    x = np.sort(rng.uniform(100, 500, 400))
    x[rng.integers(0, 400, 20)] = x[rng.integers(0, 400, 20)]  # duplicates
    x = rng.permutation(x)  # unsorted input
    y = rng.normal(size=400)
    x_new = np.arange(50, 560, 0.5)
    for gap in (1.0, 3.0, 50.0):
        got = LASHandler()._linear_interp_with_gap_limit(x_new, x, y, gap)
        ref = old_linear(x_new, x, y, gap)
        _same_nan(got, ref)
        assert np.nanmax(np.abs(got - ref)) < 1e-12


@pytest.mark.parametrize("seed", range(4))
def test_nearest_numeric_and_string_match_old(seed):
    rng = np.random.default_rng(seed)
    x = np.unique(np.round(rng.uniform(100, 500, 300), 1))
    x_new = np.arange(90, 520, 0.25)  # many exact ties on the 0.1 grid
    y = rng.integers(0, 5, len(x)).astype(float)
    ys = np.array(["SAND", "SHALE", "COAL"], dtype=object)[rng.integers(0, 3, len(x))]
    m = LASHandler()
    for dist in (0.2, 1.0):
        got = m._nearest_neighbor_interp(x_new, x, y, dist)
        ref = old_nearest(x_new, x, y, dist)
        _same_nan(got, ref)
        assert np.array_equal(got[~np.isnan(got)], ref[~np.isnan(ref)])
        gs = m._nearest_neighbor_interp(x_new, x, ys, dist)
        rs = old_nearest(x_new, x, ys, dist)
        assert gs.dtype == object and list(gs) == list(rs) or all(
            (a is b) or (a == b) or (a != a and b != b) for a, b in zip(gs, rs)
        )


def test_replace_null_values_matches_old():
    rng = np.random.default_rng(1)
    nulls = [-999.25, -999, -9999, 9999.0]
    df = pd.DataFrame(
        {
            "DEPTH": np.arange(1000.0),
            "A": rng.normal(size=1000),
            "B": rng.choice([-999.25, -999.0, 1.5, -9999.0], 1000),
            "C": pd.array(rng.choice([-999, 3, 7], 1000), dtype="Int64"),
            "D": rng.choice(["x", "y"], 1000),
        }
    )
    df.loc[5:20, "A"] = -999.2500004
    ref = old_replace_null(df.copy(), nulls)
    out = df.copy()
    ret = las_utils.replace_null_values(out, nulls)
    assert ret is out
    pd.testing.assert_frame_equal(out, ref)


@pytest.mark.parametrize("seed", range(3))
def test_ws_dw_match_old(seed):
    rng = np.random.default_rng(seed)
    n = 3000
    rt = rng.lognormal(2.0, 1.5, n)
    phi = rng.uniform(0.0, 0.35, n)
    rt[rng.integers(0, n, 50)] = np.nan
    phi[rng.integers(0, n, 50)] = np.nan
    calc = _calc(rt, phi)
    phie = pd.Series(phi, index=calc.data.index)

    got = calc.calculate_sw_waxman_smits("RT", phie, rw=0.05, a=1.0, m=2.0, n=2.0, qv=0.3, B=4.0)
    ref, diag = old_ws(rt, phi, 0.05, 1.0, 2.0, 2.0, 0.3, 4.0)
    _same_nan(got.to_numpy(), ref)
    assert np.nanmax(np.abs(got.to_numpy() - ref)) < 1e-6
    assert calc.solver_diagnostics["SW_WS"] == diag

    got = calc.calculate_sw_dual_water("RT", phie, rw=0.05, a=1.0, m=2.0, n=2.0, swb=0.15, rwb=0.2)
    ref, diag = old_dw(rt, phi, 0.05, 1.0, 2.0, 2.0, 0.15, 0.2)
    _same_nan(got.to_numpy(), ref)
    assert np.nanmax(np.abs(got.to_numpy() - ref)) < 1e-6
    assert calc.solver_diagnostics["SW_DW"] == diag


def test_perm_classify_matches_old():
    rng = np.random.default_rng(3)
    k = pd.Series(np.concatenate([10 ** rng.uniform(-3, 4, 500), [1, 10, 100, 1000, np.nan, 0]]))
    calc = _calc(np.ones(len(k)), None)
    got = calc.classify_flow_units(k)
    ref = k.apply(old_classify)
    assert list(got) == list(ref)


def test_export_formats_numeric_nan_and_strings():
    df = pd.DataFrame(
        {
            "DEPTH": [1.0, 2.0, 3.0],
            "GR": [10.12345, np.nan, 3.0],
            "LITH": ["SAND", None, "SHALE"],
            "FLAG": pd.array([1, None, 3], dtype="Int64"),
        }
    )
    text = export_merged_las(df, {"well_name": "W"})
    rows = text.split("\n")[-3:]
    assert rows[0].split() == ["1.00", f"{10.12345:.4f}", "SAND", "1.0000"]
    assert rows[1].split()[:2] == ["2.00", "-999.2500"]
    assert rows[1].split()[3] == "-999.2500"  # LITH None -> NaN null


def test_vectorised_ws_is_fast():
    rng = np.random.default_rng(5)
    n = 20000
    rt = rng.lognormal(2.0, 1.0, n)
    phi = rng.uniform(0.05, 0.35, n)
    calc = _calc(rt, phi)
    t0 = time.perf_counter()
    calc.calculate_sw_waxman_smits(
        "RT", pd.Series(phi, index=calc.data.index), rw=0.05, a=1.0, m=2.0, n=2.0, qv=0.3, B=4.0
    )
    assert time.perf_counter() - t0 < 2.0
