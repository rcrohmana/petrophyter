"""Per-sample cementation and saturation exponents in every Sw model."""
import numpy as np
import pandas as pd
import pytest

from modules.petrophysics import PetrophysicsCalculator

N = 40


def _frame():
    rng = np.random.default_rng(7)
    rt = np.exp(rng.uniform(np.log(0.3), np.log(400.0), N))
    phi = rng.uniform(0.04, 0.32, N)
    vsh = rng.uniform(0.0, 0.7, N)
    # Edge cases: missing Rt, missing / zero / negative porosity, very low and
    # very high Rt (Sw clipped to 1 and to the lower bound), shale outside 0-1.
    rt[3] = np.nan
    phi[5] = np.nan
    phi[6] = 0.0
    phi[7] = -0.02
    phi[8] = 0.0005
    rt[10] = 0.02
    rt[11] = 5000.0
    vsh[12] = 1.2
    vsh[13] = -0.1
    vsh[14] = np.nan
    return pd.DataFrame({
        "DEPTH": np.arange(N, dtype=float), "RT": rt,
        "PHIE": phi, "PHIT": phi + 0.03, "VSH": vsh,
    })


def _call(model, calc, data, m, n):
    common = dict(rt_curve="RT", rw=0.05, a=0.62, m=m, n=n)
    if model == "archie":
        return calc.calculate_sw_archie(phie=data["PHIE"], **common)
    if model == "indonesian":
        return calc.calculate_sw_indonesian(phie=data["PHIE"], vsh=data["VSH"], rsh=4.0, **common)
    if model == "simandoux":
        return calc.calculate_sw_simandoux(phie=data["PHIE"], vsh=data["VSH"], rsh=4.0, **common)
    if model == "waxman_smits":
        return calc.calculate_sw_waxman_smits(
            phit=data["PHIT"], qv=0.25, B=1.0, phie=data["PHIE"], **common)
    if model == "dual_water":
        return calc.calculate_sw_dual_water(
            phit=data["PHIT"], swb=0.1, rwb=0.2, phie=data["PHIE"], **common)
    raise AssertionError(model)


MODELS = ["archie", "indonesian", "simandoux", "waxman_smits", "dual_water"]
KEYS = {"archie": "SW_ARCHIE", "indonesian": "SW_INDO", "simandoux": "SW_SIMAN",
        "waxman_smits": "SW_WS", "dual_water": "SW_DW"}


def _same(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    return np.array_equal(a, b, equal_nan=True)


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("m,n", [(2.15, 2.0), (1.9, 1.8), (2.0, 2.4), (1.0, 2.0)])
def test_constant_arrays_equal_scalar(model, m, n):
    data = _frame()
    scalar_calc = PetrophysicsCalculator(data)
    scalar = _call(model, scalar_calc, data, m, n)
    array_calc = PetrophysicsCalculator(data)
    arr = _call(model, array_calc, data, np.full(N, m), np.full(N, n))
    assert _same(scalar, arr)
    key = KEYS[model]
    assert _same(scalar_calc.results[key], array_calc.results[key])
    assert scalar_calc.sw_flags[key].equals(array_calc.sw_flags[key])


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("which", ["m", "n"])
def test_one_array_one_scalar(model, which):
    data = _frame()
    ref = _call(model, PetrophysicsCalculator(data), data, 2.0, 2.2)
    if which == "m":
        got = _call(model, PetrophysicsCalculator(data), data, np.full(N, 2.0), 2.2)
    else:
        got = _call(model, PetrophysicsCalculator(data), data, 2.0, np.full(N, 2.2))
    assert _same(ref, got)


@pytest.mark.parametrize("model", MODELS)
def test_mixed_arrays_equal_sample_by_sample(model):
    data = _frame()
    rng = np.random.default_rng(11)
    m_arr = rng.uniform(1.6, 2.4, N)
    n_arr = rng.uniform(1.7, 2.6, N)
    # Some rows exactly on the closed-form Simandoux exponent.
    n_arr[::4] = 2.0
    got = _call(model, PetrophysicsCalculator(data), data, m_arr, n_arr)

    expected = np.full(N, np.nan)
    for i in range(N):
        row = data.iloc[[i]].reset_index(drop=True)
        value = _call(model, PetrophysicsCalculator(row), row, float(m_arr[i]), float(n_arr[i]))
        expected[i] = value.iloc[0]
    assert _same(got, expected)


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("which", ["m", "n"])
def test_wrong_length_raises(model, which):
    data = _frame()
    kwargs = {"m": 2.0, "n": 2.0}
    kwargs[which] = np.full(N - 1, 2.0)
    with pytest.raises(ValueError, match=f"{which} array must have one value per data row"):
        _call(model, PetrophysicsCalculator(data), data, kwargs["m"], kwargs["n"])


@pytest.mark.parametrize("model", MODELS)
def test_non_positive_array_value_raises(model):
    data = _frame()
    m_arr = np.full(N, 2.0)
    m_arr[4] = 0.0
    with pytest.raises(ValueError, match="m must contain finite values greater than 0"):
        _call(model, PetrophysicsCalculator(data), data, m_arr, 2.0)
