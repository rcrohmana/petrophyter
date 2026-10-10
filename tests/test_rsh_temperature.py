"""Rsh, Rwb and Waxman-Smits B with formation temperature (follow-ups spec section 4)."""

import io

import numpy as np
import pandas as pd
import pytest

from modules import param_scopes as ps
from modules.formation_tops import FormationTops
from modules.param_scopes import arps_factor, formation_temperature
from modules.petrophysics import PetrophysicsCalculator
from modules.pipeline import PARAM_DEFAULTS, run_pipeline

TS, GRAD, T_REF = 80.0, 1.5, 75.0
RSH_REF = 3.0
RW = 0.05
MAPPING = {"GR": "GR", "RHOB": "RHOB", "NPHI": "NPHI", "DT": "None", "RT": "RT"}


def temp_at(depth):
    return formation_temperature(np.asarray(depth, dtype=float), TS, GRAD)


def well(n=401):
    """Sands at RT 20 ohm.m with shale blocks whose RT is RSH_REF at T_REF, cooled by depth."""
    depth = 1000.0 + 5.0 * np.arange(n)
    shale = ((depth >= 1300) & (depth < 1500)) | ((depth >= 2300) & (depth < 2500))
    rt = np.where(shale, RSH_REF * arps_factor(temp_at(depth), T_REF), 20.0)
    return pd.DataFrame({
        "DEPTH": depth,
        "GR": np.where(shale, 115.0, 30.0),
        "RHOB": np.where(shale, 2.55, 2.35),
        "NPHI": np.where(shale, 0.40, 0.20),
        "RT": rt,
    })


def params(**extra):
    return {
        **PARAM_DEFAULTS,
        "vsh_baseline_method": ps.GR_MANUAL, "gr_min_manual": 20.0, "gr_max_manual": 120.0,
        "rw_mode": "manual", "rw": RW, "rsh_mode": "auto",
        "surface_temp": TS, "temp_gradient": GRAD, "rw_ref_temp": T_REF,
        "sw_methods": ["Indonesian", "Simandoux"], "sw_primary_method": "Simandoux",
        **extra,
    }


def factor_of(df):
    return arps_factor(temp_at(df["DEPTH"]), T_REF)


# ---- auto Rsh -------------------------------------------------------------------
def test_auto_rsh_with_correction_recovers_the_reference_value():
    df = well()
    _, corrected = run_pipeline(df, MAPPING, params(temp_correction=True))
    assert corrected["rsh"] == pytest.approx(RSH_REF, rel=1e-9)
    assert corrected["rsh_source"] == "auto"
    info = corrected["rsh_temperature"]
    assert info["corrected"] and info["ref_temp"] == T_REF
    factor = factor_of(df)
    assert info["range"][0] == pytest.approx(RSH_REF * factor.min())
    assert info["range"][1] == pytest.approx(RSH_REF * factor.max())
    # Without the correction the median mixes temperatures and is not the reference value.
    _, plain = run_pipeline(df, MAPPING, params(temp_correction=False))
    assert abs(plain["rsh"] - RSH_REF) > 0.1
    assert "rsh_temperature" not in plain


def test_auto_rsh_sw_uses_the_per_sample_value():
    df = well()
    results, summary = run_pipeline(df, MAPPING, params(temp_correction=True))
    factor = factor_of(df)
    calc = PetrophysicsCalculator(df)
    expected = calc.calculate_sw_indonesian(
        "RT", results["PHIE"], results["VSH"], RW * factor,
        summary["rsh"] * factor, 0.62, 2.15, 2.0,
    )
    np.testing.assert_allclose(results["SW_INDO"], expected, rtol=1e-12, equal_nan=True)


# ---- manual Rsh --------------------------------------------------------------------
def _direct_indo(df, results, rw, rsh):
    return PetrophysicsCalculator(df).calculate_sw_indonesian(
        "RT", results["PHIE"], results["VSH"], rw, rsh, 0.62, 2.15, 2.0)


def test_manual_rsh_without_reference_temperature_is_used_as_entered():
    df = well()
    results, summary = run_pipeline(
        df, MAPPING, params(temp_correction=True, rsh_mode="manual", rsh=4.0, rsh_ref_temp=None))
    assert summary["rsh_temperature"]["corrected"] is False
    expected = _direct_indo(df, results, RW * factor_of(df), 4.0)
    np.testing.assert_allclose(results["SW_INDO"], expected, rtol=1e-12, equal_nan=True)


def test_manual_rsh_with_reference_temperature_is_corrected_per_sample():
    df = well()
    results, summary = run_pipeline(
        df, MAPPING, params(temp_correction=True, rsh_mode="manual", rsh=4.0, rsh_ref_temp=90.0))
    rsh = 4.0 * arps_factor(temp_at(df["DEPTH"]), 90.0)
    expected = _direct_indo(df, results, RW * factor_of(df), rsh)
    np.testing.assert_allclose(results["SW_INDO"], expected, rtol=1e-12, equal_nan=True)
    assert summary["rsh_temperature"]["ref_temp"] == 90.0
    assert summary["rsh"] == 4.0
    uncorrected, _ = run_pipeline(
        df, MAPPING, params(temp_correction=True, rsh_mode="manual", rsh=4.0, rsh_ref_temp=None))
    assert not np.allclose(results["SW_INDO"], uncorrected["SW_INDO"], equal_nan=True)


def test_rsh_reference_temperature_is_ignored_when_correction_is_off():
    df = well()
    base, _ = run_pipeline(df, MAPPING, params(rsh_mode="manual", rsh=4.0))
    other, _ = run_pipeline(df, MAPPING, params(rsh_mode="manual", rsh=4.0, rsh_ref_temp=90.0))
    pd.testing.assert_frame_equal(base, other)


def test_zone_runs_carry_the_rsh_correction():
    df = well()
    tops = FormationTops()
    assert tops.read_tops_from_buffer(io.StringIO(
        "Formation\tTop (ft)\tBottom (ft)\nUpper\t1000\t2000\nLower\t2000\t3000\n"))
    zone_plan = ps.zone_plan({**params(temp_correction=True)}, None, None,
                             {"UPPER": {"rw": ps.make_entry(ps.MANUAL, RW)}}, ["UPPER", "LOWER"])
    results, summary = run_pipeline(
        df, MAPPING, params(temp_correction=True, zone_plan=zone_plan), formation_tops=tops)
    whole, _ = run_pipeline(df, MAPPING, params(temp_correction=True))
    assert summary["rsh_temperature"]["corrected"]
    np.testing.assert_allclose(results["SW_SIMAN"], whole["SW_SIMAN"], rtol=1e-6, equal_nan=True)


# ---- calculator level ---------------------------------------------------------------
@pytest.mark.parametrize("method", ["calculate_sw_indonesian", "calculate_sw_simandoux"])
def test_array_rsh_equals_the_scalar_path_when_the_factor_is_one(method):
    df = well(80)
    phie = pd.Series(np.linspace(0.08, 0.3, len(df)), index=df.index)
    vsh = pd.Series(np.linspace(0.0, 0.9, len(df)), index=df.index)
    calc = PetrophysicsCalculator(df)
    scalar = getattr(calc, method)("RT", phie, vsh, RW, 5.0, 0.62, 2.15, 2.0)
    array = getattr(calc, method)("RT", phie, vsh, RW, np.full(len(df), 5.0), 0.62, 2.15, 2.0)
    pd.testing.assert_series_equal(scalar, array)
    varying = getattr(calc, method)("RT", phie, vsh, RW, np.linspace(2.0, 8.0, len(df)), 0.62, 2.15, 2.0)
    assert not np.allclose(scalar, varying, equal_nan=True)


def test_simandoux_general_n_accepts_an_rsh_array():
    df = well(40)
    phie = pd.Series(np.full(len(df), 0.2), index=df.index)
    vsh = pd.Series(np.full(len(df), 0.3), index=df.index)
    calc = PetrophysicsCalculator(df)
    scalar = calc.calculate_sw_simandoux("RT", phie, vsh, RW, 5.0, 0.62, 2.15, 2.3)
    array = calc.calculate_sw_simandoux("RT", phie, vsh, RW, np.full(len(df), 5.0), 0.62, 2.15, 2.3)
    np.testing.assert_allclose(scalar, array)


def test_rsh_array_must_match_the_rows_and_be_positive():
    df = well(20)
    calc = PetrophysicsCalculator(df)
    with pytest.raises(ValueError, match="rsh array"):
        calc.calculate_sw_indonesian("RT", rsh=np.ones(3))
    with pytest.raises(ValueError, match="rsh"):
        calc.calculate_sw_simandoux("RT", rsh=np.zeros(len(df)))


# ---- Dual-Water Rwb --------------------------------------------------------------------
def test_dual_water_rwb_is_corrected_with_the_rw_reference_temperature():
    df = well()
    dw = params(sw_methods=["Dual-Water"], sw_primary_method="Dual-Water", dw_rwb=0.2, dw_swb=0.1)
    results, _ = run_pipeline(df, MAPPING, {**dw, "temp_correction": True})
    factor = factor_of(df)
    expected = PetrophysicsCalculator(df).calculate_sw_dual_water(
        "RT", results["PHIE"], RW * factor, 0.62, 2.15, 2.0, 0.1, 0.2 * factor)
    np.testing.assert_allclose(results["SW_DW"], expected, rtol=1e-12, equal_nan=True)
    wrong = PetrophysicsCalculator(df).calculate_sw_dual_water(
        "RT", results["PHIE"], RW * factor, 0.62, 2.15, 2.0, 0.1, 0.2)
    assert not np.allclose(results["SW_DW"], wrong, equal_nan=True)


def test_dual_water_scalar_rwb_matches_a_constant_array():
    df = well(60)
    phie = pd.Series(np.full(len(df), 0.2), index=df.index)
    calc = PetrophysicsCalculator(df)
    scalar = calc.calculate_sw_dual_water("RT", phie, RW, 0.62, 2.15, 2.0, 0.1, 0.2)
    array = calc.calculate_sw_dual_water("RT", phie, RW, 0.62, 2.15, 2.0, 0.1, np.full(len(df), 0.2))
    np.testing.assert_allclose(scalar, array, rtol=1e-12)


# ---- Waxman-Smits B from temperature ------------------------------------------------------
def juhasz_by_hand(temp_f, rw):
    t = (temp_f - 32.0) * 5.0 / 9.0
    return (-1.28 + 0.225 * t - 0.0004059 * t * t) / (1.0 + rw ** 1.23 * (0.045 * t - 0.27))


def test_juhasz_b_matches_the_hand_computed_formula_at_two_depths():
    for depth in (1500.0, 2500.0):
        t_f = float(temp_at(depth))
        rw_eff = RW * float(arps_factor(t_f, T_REF))
        assert float(ps.juhasz_b(t_f, rw_eff)) == pytest.approx(juhasz_by_hand(t_f, rw_eff), rel=1e-12)
    # Literature spot value: 25 C, Rw 1 ohm.m -> B about 2.2.
    assert float(ps.juhasz_b(77.0, 1.0)) == pytest.approx(2.2, abs=0.01)


def test_ws_b_from_temperature_uses_rw_at_formation_temperature():
    df = well()
    ws = params(sw_methods=["Waxman-Smits"], sw_primary_method="Waxman-Smits", temp_correction=True,
                ws_qv=0.2, ws_b=1.0)
    off, _ = run_pipeline(df, MAPPING, ws)
    on, summary = run_pipeline(df, MAPPING, {**ws, "ws_b_auto": True})
    factor = factor_of(df)
    rw_eff = RW * factor
    b = np.array([juhasz_by_hand(float(t), float(r)) for t, r in zip(temp_at(df["DEPTH"]), rw_eff)])
    expected = PetrophysicsCalculator(df).calculate_sw_waxman_smits(
        "RT", on["PHIE"], rw_eff, 0.62, 2.15, 2.0, 0.2, b)
    np.testing.assert_allclose(on["SW_WS"], expected, rtol=1e-12, equal_nan=True)
    # Rw at the reference temperature would give a different B, and so a different Sw.
    b_ref = np.array([juhasz_by_hand(float(t), RW) for t in temp_at(df["DEPTH"])])
    wrong = PetrophysicsCalculator(df).calculate_sw_waxman_smits(
        "RT", on["PHIE"], rw_eff, 0.62, 2.15, 2.0, 0.2, b_ref)
    assert not np.allclose(on["SW_WS"], wrong, equal_nan=True)
    assert not np.allclose(on["SW_WS"], off["SW_WS"], equal_nan=True)
    assert summary["temperature"]["kind"] == "md"


def test_ws_b_from_temperature_without_rw_correction_warns_and_uses_entered_rw():
    df = well()
    ws = params(sw_methods=["Waxman-Smits"], sw_primary_method="Waxman-Smits", ws_b_auto=True,
                temp_correction=False)
    results, summary = run_pipeline(df, MAPPING, ws)
    assert any("WS B from temperature uses Rw as entered" in w for w in summary["warnings"])
    b = np.array([juhasz_by_hand(float(t), RW) for t in temp_at(df["DEPTH"])])
    expected = PetrophysicsCalculator(df).calculate_sw_waxman_smits(
        "RT", results["PHIE"], RW, 0.62, 2.15, 2.0, 0.2, b)
    np.testing.assert_allclose(results["SW_WS"], expected, rtol=1e-12, equal_nan=True)


def test_ws_b_array_must_match_the_rows():
    df = well(20)
    with pytest.raises(ValueError, match="B array"):
        PetrophysicsCalculator(df).calculate_sw_waxman_smits("RT", B=np.ones(4))
