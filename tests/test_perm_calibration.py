"""Wyllie-Rose calibration module: C and P fitted with Q held (C13), plus zones."""
import io

import numpy as np
import pandas as pd
import pytest

from modules.formation_tops import FormationTops
from modules.perm_calibration import (
    APPLY_WARNING, apply_warning, calibrate_from_core, estimate_from_porosity,
    pair_core_samples, predict_permeability, zone_mask,
)
from modules.petrophysics import PetrophysicsCalculator, swirr_buckles


def _core(n=12, seed=3):
    rng = np.random.default_rng(seed)
    depth = 1000.0 + np.arange(n) * 4.0
    phi = rng.uniform(0.08, 0.28, n)
    perm = 8000 * phi ** 4.3 / np.clip(0.03 / phi, 0.05, 0.8) ** 2.1 * rng.uniform(0.7, 1.3, n)
    return depth, phi, perm


def _synthetic(c=5000.0, p=4.0, q=1.5, kb=0.02, n=30):
    """Noise-free core set generated with the Buckles Wyllie-Rose model."""
    phi = np.linspace(0.08, 0.28, n)
    return phi, predict_permeability(phi, c, p, q, kb)


def test_core_fit_holds_q_and_records_the_swirr_basis():
    depth, phi, perm = _core()
    por, k = pair_core_samples(depth, perm, depth, phi)
    result = calibrate_from_core(por, k, 0.03, q=2.3)
    assert result["method"] == "core" and result["pairs"] == len(depth)
    assert result["Q"] == 2.3
    assert result["swirr"] == "Buckles" and result["k_buckles"] == 0.03
    default_q = calibrate_from_core(por, k, 0.03)
    assert default_q["Q"] == 2.0


@pytest.mark.parametrize("start", [(100.0, 2.5), (30000.0, 7.0), (8581.0, 4.4)])
def test_c13_recovers_c_and_p_with_q_given_from_three_starts(start):
    phi, perm = _synthetic(c=5000.0, p=4.0, q=1.5, kb=0.02)
    fit = calibrate_from_core(phi, perm, 0.02, q=1.5, x0=start)
    assert fit["C"] == pytest.approx(5000.0, rel=0.05)
    assert fit["P"] == pytest.approx(4.0, rel=0.05)


def test_c13_pipeline_permeability_equals_the_fit_prediction():
    # Includes plugs whose Buckles Swirr sits at both clips (0.02, 0.04, 0.3).
    phi = np.array([0.02, 0.04, 0.08, 0.12, 0.18, 0.25, 0.3, 0.1, 0.15])
    perm = predict_permeability(phi, 5000.0, 4.0, 1.5, 0.02)
    fit = calibrate_from_core(phi, perm, 0.02, q=1.5, min_pairs=5)
    predicted = predict_permeability(phi, fit["C"], fit["P"], fit["Q"], 0.02)
    calc = PetrophysicsCalculator(pd.DataFrame({"DEPTH": np.arange(len(phi), dtype=float)}))
    swirr = calc.calculate_swirr_buckles(pd.Series(phi), 0.02)
    k = calc.calculate_permeability_wyllie_rose(
        pd.Series(phi), swirr, fit["C"], fit["P"], fit["Q"])
    # The pipeline also clips K to [0.001, 50000]; the plugs here stay inside.
    assert np.all((predicted > 0.001) & (predicted < 50000))
    np.testing.assert_allclose(np.asarray(k), predicted, rtol=1e-12)


def test_c13_clipped_swirr_plugs_are_counted():
    phi = np.array([0.02, 0.04, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30])
    # kb 0.02 / phi: 1.0 (clipped to 0.5), 0.5 (not clipped), 0.2, ..., 0.067 (not), 0.05 ... ok
    perm = predict_permeability(phi, 5000.0, 4.0, 2.0, 0.02)
    fit = calibrate_from_core(phi, perm, 0.02)
    raw = 0.02 / np.maximum(phi, 0.01)
    assert fit["clipped_swirr"] == int(np.sum((raw < 0.05) | (raw > 0.5)))
    assert fit["clipped_swirr"] >= 1


def test_swirr_buckles_floors_porosity_and_clips():
    out = swirr_buckles(np.array([0.001, 0.01, 0.1, 0.5]), 0.02)
    # 0.02/0.01 = 2 -> 0.5 (clip), 0.02/0.01 -> 0.5, 0.02/0.1 = 0.2, 0.02/0.5 = 0.04 -> 0.05
    np.testing.assert_allclose(out, [0.5, 0.5, 0.2, 0.05], rtol=1e-12)


def test_apply_warning_when_the_project_swirr_differs():
    fit = {"method": "core", "swirr": "Buckles", "k_buckles": 0.02, "Q": 2.0}
    assert apply_warning(fit, "Buckles Number", 0.02) is None
    assert apply_warning(fit, "Hierarchical (Recommended)", 0.02) == APPLY_WARNING
    assert apply_warning(fit, "Clean Zone", 0.02) == APPLY_WARNING
    assert apply_warning(fit, "Buckles Number", 0.03) == APPLY_WARNING
    assert "coefficients were fitted with Buckles Swirr" in APPLY_WARNING
    assert "will not reproduce the core" in APPLY_WARNING


def test_pairing_respects_tolerance():
    por, k = pair_core_samples([100.0, 200.0], [10.0, 20.0], [100.3, 205.0], [0.2, 0.25])
    assert list(por) == [0.2] and list(k) == [10.0]
    por, k = pair_core_samples([100.0], [10.0], [], [])
    assert len(por) == 0


def test_too_few_pairs_gives_no_result():
    assert calibrate_from_core([0.2, 0.21, 0.22, 0.23], [10, 12, 14, 16], 0.03) is None


@pytest.mark.parametrize("mean,expected", [(0.25, (10000.0, 4.0, 2.0)),
                                           (0.15, (8581.0, 4.4, 2.0)),
                                           (0.08, (5000.0, 5.0, 2.2))])
def test_porosity_estimate_bands(mean, expected):
    result = estimate_from_porosity(np.full(20, mean))
    assert (result["C"], result["P"], result["Q"]) == expected
    assert estimate_from_porosity(np.full(9, mean)) is None


def test_zone_mask():
    tops = FormationTops()
    assert tops.read_tops_from_buffer(io.StringIO(
        "Formation\tTop (ft)\tBottom (ft)\nUpper\t1000\t1020\nLower\t1020\t1050\n"))
    depths = [1005.0, 1019.0, 1025.0, 1060.0]
    assert list(zone_mask(depths, tops, "upper")) == [True, True, False, False]
    assert list(zone_mask(depths, tops, None)) == [True] * 4
    assert list(zone_mask(depths, None, "UPPER")) == [False] * 4


def test_i6_calibration_reports_a_reason_and_survives_sentinels():
    from modules.perm_calibration import fit_core

    fit, reason = fit_core([0.2, 0.21], [10, 12], 0.03)
    assert fit is None and "2 usable plugs" in reason and "need 5" in reason

    por = np.linspace(0.10, 0.25, 20)
    k = 5 * np.exp(18 * por)
    por_s, k_s = por.copy(), k.copy()
    por_s[[2, 5, 8, 11, 14]] = -999.25
    k_s[[2, 5, 8, 11, 14]] = -999.25
    fit, reason = fit_core(por_s, k_s, 0.03)
    assert fit is not None and reason is None and fit["pairs"] == 15
