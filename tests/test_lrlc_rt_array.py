"""The Rt array path of the five Sw models: ``rt=None`` is v1.10.0, an array is bit-exact."""

import numpy as np
import pandas as pd
import pytest

from modules.petrophysics import PetrophysicsCalculator

N = 400
RW, RSH, A_, M_ = 0.05, 5.0, 0.62, 2.15


def _data(seed=3):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "DEPTH": np.arange(N, dtype=float),
        "RT": rng.lognormal(2.0, 1.0, N),
    }, index=pd.RangeIndex(100, 100 + N))  # non-default index: alignment is positional
    df.loc[df.index[::41], "RT"] = np.nan
    return df


def _porosity(seed=4):
    rng = np.random.default_rng(seed)
    idx = pd.RangeIndex(100, 100 + N)
    return (pd.Series(rng.uniform(0.05, 0.3, N), index=idx),
            pd.Series(rng.uniform(0.0, 0.7, N), index=idx))


def _run(model, calc, phi, vsh, n, rt=None):
    kw = {} if rt is None else {"rt": rt}
    if model == "archie":
        return calc.calculate_sw_archie("RT", phi, RW, A_, M_, n, **kw)
    if model == "indonesian":
        return calc.calculate_sw_indonesian("RT", phi, vsh, RW, RSH, A_, M_, n, **kw)
    if model == "simandoux":
        return calc.calculate_sw_simandoux("RT", phi, vsh, RW, RSH, A_, M_, n, **kw)
    if model == "waxman_smits":
        return calc.calculate_sw_waxman_smits("RT", phi + 0.02, RW, A_, M_, n, 0.3, 1.0,
                                              phie=phi, **kw)
    return calc.calculate_sw_dual_water("RT", phi + 0.02, RW, A_, M_, n, 0.15, 0.2,
                                        phie=phi, **kw)


CASES = [("archie", 2.0), ("indonesian", 2.0), ("simandoux", 2.0), ("simandoux", 2.3),
         ("waxman_smits", 2.0), ("dual_water", 2.0)]


@pytest.mark.parametrize("model,n", CASES)
def test_array_of_the_same_values_is_bit_exact(model, n):
    df = _data()
    phi, vsh = _porosity()
    base = _run(model, PetrophysicsCalculator(df), phi, vsh, n)
    arr = _run(model, PetrophysicsCalculator(df), phi, vsh, n, rt=df["RT"].to_numpy())
    assert base.notna().sum() > 0
    pd.testing.assert_series_equal(base, arr, check_exact=True)


@pytest.mark.parametrize("model,n", CASES)
def test_modified_array_equals_a_calculator_on_modified_data(model, n):
    df = _data()
    phi, vsh = _porosity()
    new_rt = df["RT"].to_numpy() * 1.7 + 0.3
    other = df.copy()
    other["RT"] = new_rt
    expected = _run(model, PetrophysicsCalculator(other), phi, vsh, n)
    got = _run(model, PetrophysicsCalculator(df), phi, vsh, n, rt=new_rt)
    pd.testing.assert_series_equal(expected, got, check_exact=True)
    # the array did not leak into the calculator's data
    pd.testing.assert_series_equal(PetrophysicsCalculator(df).data["RT"], df["RT"])


@pytest.mark.parametrize("model,n", CASES)
def test_shape_mismatch_raises(model, n):
    df = _data()
    phi, vsh = _porosity()
    with pytest.raises(ValueError, match="one value per data row"):
        _run(model, PetrophysicsCalculator(df), phi, vsh, n, rt=np.ones(N - 1))
    with pytest.raises(ValueError, match="one value per data row"):
        _run(model, PetrophysicsCalculator(df), phi, vsh, n, rt=np.ones((N, 1)))


@pytest.mark.parametrize("model,n", CASES)
def test_nan_in_the_array_gives_nan_sw(model, n):
    df = _data()
    phi, vsh = _porosity()
    rt = df["RT"].to_numpy().copy()
    rt[5] = np.nan
    rt[6] = np.nan
    rt[7] = 30.0  # keep one valid neighbour
    sw = _run(model, PetrophysicsCalculator(df), phi, vsh, n, rt=rt)
    assert np.isnan(sw.iloc[5]) and np.isnan(sw.iloc[6])
    assert np.isfinite(sw.iloc[7])


@pytest.mark.parametrize("bad", [0.0, -1.0, np.inf])
def test_non_physical_values_still_raise_in_the_validator(bad):
    df = _data()
    phi, vsh = _porosity()
    rt = df["RT"].to_numpy().copy()
    rt[3] = bad
    with pytest.raises(ValueError, match="rt"):
        _run("archie", PetrophysicsCalculator(df), phi, vsh, 2.0, rt=rt)


def test_missing_rt_column_still_returns_nan_even_with_an_array():
    df = _data().drop(columns=["RT"])
    phi, vsh = _porosity()
    sw = _run("archie", PetrophysicsCalculator(df), phi, vsh, 2.0, rt=np.ones(N))
    assert sw.isna().all()


def test_primary_sw_without_rt_values_matches_the_explicit_none_and_the_array():
    """``_primary_sw(rt_values=None)`` is the v1.10.0 call; the goldens pin it end to end."""
    from modules import pipeline as pl

    df = _data()
    phi, vsh = _porosity()
    p = {"a": A_, "m": M_, "n": 2.0, "sw_methods": ["Archie", "Indonesian", "Simandoux"],
         "sw_primary_method": "Simandoux", "ws_b": 1.0, "dw_rwb": 0.2, "ws_qv": 0.3,
         "dw_swb": 0.15}

    def go(**kw):
        calc = PetrophysicsCalculator(df)
        calc.results["PHIE"] = phi
        calc.results["PHIT"] = phi + 0.02
        sw, _, _, fb = pl._primary_sw(calc, df, {"RT": "RT"}, p, vsh, RW, RSH, None,
                                      pl.IssueLog() if hasattr(pl, "IssueLog") else None, **kw)
        return calc.results.copy(), sw, fb

    base, sw0, fb0 = go()
    none_res, sw1, fb1 = go(rt_values=None)
    arr_res, sw2, fb2 = go(rt_values=df["RT"].to_numpy())
    pd.testing.assert_frame_equal(base, none_res, check_exact=True)
    pd.testing.assert_frame_equal(base, arr_res, check_exact=True)
    assert fb0 == fb1 == fb2 is None


def test_sw_effective_inputs_without_temperature_context():
    from modules import pipeline as pl

    df = _data()
    p = {"dw_rwb": 0.2, "ws_b": 1.0}
    eff = pl._sw_effective_inputs(p, RW, RSH, False, None, df)
    assert eff.rw == RW and eff.rsh == RSH and eff.rwb == 0.2 and eff.ws_b == 1.0
    rw_eff, rsh_eff, rwb_eff, ws_b = eff
    assert (rw_eff, rsh_eff, rwb_eff, ws_b) == (RW, RSH, 0.2, 1.0)
