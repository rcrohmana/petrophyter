"""Wyllie-Rose calibration module: identical to the former main-window code, plus zones."""
import io

import numpy as np
import pytest
from scipy import optimize

from modules.formation_tops import FormationTops
from modules.perm_calibration import (
    calibrate_from_core, estimate_from_porosity, pair_core_samples, zone_mask,
)


def _reference_fit(core_depths, core_perm, core_depths_por, core_por, k_buckles):
    """The fit as it was inlined in MainWindow._on_calculate_perm (before the move)."""
    matched_por, matched_perm = [], []
    for i, d in enumerate(core_depths):
        idx = np.argmin(np.abs(core_depths_por - d))
        if np.abs(core_depths_por[idx] - d) < 0.5:
            matched_por.append(core_por[idx])
            matched_perm.append(core_perm[i])
    matched_por, matched_perm = np.array(matched_por), np.array(matched_perm)
    swirr = np.clip(k_buckles / matched_por, 0.05, 0.8)

    def objective(params, phi, swi, k):
        C, P, Q = params
        k_pred = C * (phi ** P) / (swi ** Q)
        return np.sum((np.log10(k_pred + 0.001) - np.log10(k + 0.001)) ** 2)

    result = optimize.minimize(objective, [8581, 4.4, 2.0], args=(matched_por, swirr, matched_perm),
                               bounds=[(10, 50000), (2, 8), (0.5, 4)], method="L-BFGS-B")
    return result.x


def _core(n=12, seed=3):
    rng = np.random.default_rng(seed)
    depth = 1000.0 + np.arange(n) * 4.0
    phi = rng.uniform(0.08, 0.28, n)
    perm = 8000 * phi ** 4.3 / np.clip(0.03 / phi, 0.05, 0.8) ** 2.1 * rng.uniform(0.7, 1.3, n)
    return depth, phi, perm


def test_core_fit_matches_the_former_implementation():
    depth, phi, perm = _core()
    expected = _reference_fit(depth, perm, depth, phi, 0.03)
    por, k = pair_core_samples(depth, perm, depth, phi)
    result = calibrate_from_core(por, k, 0.03)
    assert result["method"] == "core" and result["pairs"] == len(depth)
    assert [result["C"], result["P"], result["Q"]] == pytest.approx(list(expected))


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
