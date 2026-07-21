"""
Regression tests for data-integrity fixes in modules/statistics_utils.py.

These import the production StatisticsUtils directly (previously there were no
direct tests for this module) and pin the behavior of the fixes:
  - estimate_rw_from_rt_water_zone: joint dropna so RT/PHI stay index-aligned
  - estimate_rw_from_sp: robust low percentile instead of raw min()
  - get_shale_zone_statistics: no scipy.stats shadowing
  - estimate_swi: clean-zone filtering unchanged after dead-code removal
"""

import numpy as np
import pandas as pd
import pytest

from modules.statistics_utils import StatisticsUtils
from modules import statistics_utils as su_module


def _make_rt_phi_frame(seed=0, n=60):
    rng = np.random.default_rng(seed)
    depth = np.arange(n, dtype=float)
    phi = np.clip(rng.normal(0.20, 0.06, n), 0.02, 0.35)
    rt = np.clip(rng.normal(8.0, 5.0, n), 0.5, 60.0)
    # Scatter NaN in BOTH curves at different rows (the common real-world case
    # that triggered the index-misalignment bug).
    rt[5:15] = np.nan
    phi[40:50] = np.nan
    return pd.DataFrame({"DEPTH": depth, "RT": rt, "PHIT": phi})


def _reference_rw(df, a=0.62, m=2.15, threshold=0.15):
    """Correct, index-aligned reference computation (joint dropna)."""
    valid = df[["RT", "PHIT"]].dropna()
    rt, phi = valid["RT"], valid["PHIT"]
    mask = (phi > threshold) & (rt < np.percentile(rt, 25))
    if mask.sum() == 0:
        return None
    rw = rt[mask].median() * (phi[mask].median() ** m) / a
    return max(0.01, min(float(rw), 5.0))


class TestRwFromRtWaterZone:
    def test_does_not_crash_with_scattered_nan(self):
        df = _make_rt_phi_frame()
        # Must not raise despite NaN gaps in RT and PHI.
        rw = StatisticsUtils(df).estimate_rw_from_rt_water_zone("RT", "PHIT")
        assert rw is not None
        assert 0.01 <= rw <= 5.0

    def test_matches_index_aligned_reference(self):
        df = _make_rt_phi_frame()
        rw = StatisticsUtils(df).estimate_rw_from_rt_water_zone("RT", "PHIT")
        assert rw == pytest.approx(_reference_rw(df), rel=1e-9)

    def test_nan_gaps_do_not_change_result_vs_dropped_rows(self):
        # Dropping the NaN rows entirely must give the same answer as leaving
        # them in place (proves the mask is computed on aligned indices only).
        df = _make_rt_phi_frame()
        clean = df.dropna(subset=["RT", "PHIT"]).reset_index(drop=True)
        rw_gappy = StatisticsUtils(df).estimate_rw_from_rt_water_zone("RT", "PHIT")
        rw_clean = StatisticsUtils(clean).estimate_rw_from_rt_water_zone("RT", "PHIT")
        assert rw_gappy == pytest.approx(rw_clean, rel=1e-9)

    def test_returns_none_when_rt_missing(self):
        df = pd.DataFrame({"DEPTH": [1.0, 2.0], "PHIT": [0.2, 0.25]})
        assert StatisticsUtils(df).estimate_rw_from_rt_water_zone("RT", "PHIT") is None


class TestRwFromSpRobustness:
    def _sp_frame(self, spike=False, seed=1, n=200):
        rng = np.random.default_rng(seed)
        sp = rng.normal(-80.0, 5.0, n)
        if spike:
            sp[0] = -5000.0  # single extreme washout/noise spike
        return pd.DataFrame({"DEPTH": np.arange(n, dtype=float), "SP": sp})

    def test_single_spike_does_not_dominate_estimate(self):
        rw_spike = StatisticsUtils(self._sp_frame(spike=True)).estimate_rw_from_sp("SP")
        rw_clean = StatisticsUtils(self._sp_frame(spike=False)).estimate_rw_from_sp("SP")
        assert rw_spike is not None and rw_clean is not None
        # A P1-based SSP is barely moved by one outlier; a raw min() would have
        # driven the estimate to the clamped floor (0.01).
        assert rw_spike == pytest.approx(rw_clean, rel=0.15)
        assert rw_spike > 0.011


class TestShaleZoneStatistics:
    def test_returns_stats_and_scipy_stats_not_shadowed(self):
        rng = np.random.default_rng(2)
        n = 200
        gr = np.concatenate([rng.normal(40, 5, n // 2), rng.normal(140, 8, n // 2)])
        rhob = rng.normal(2.45, 0.05, n)
        df = pd.DataFrame({"DEPTH": np.arange(n, dtype=float), "GR": gr, "RHOB": rhob})
        util = StatisticsUtils(df)
        zone_stats = util.get_shale_zone_statistics("GR", "RHOB", "NPHI", "DT")
        assert "shale_points" in zone_stats
        # scipy.stats must still be usable afterwards (the local var used to
        # shadow the module import); linregress lives on the module object.
        assert hasattr(su_module.stats, "linregress")


class TestEstimateSwi:
    def test_clean_zone_filtering(self):
        n = 100
        sw = np.full(n, 0.8)
        sw[:20] = 0.1  # clean, low-Sw zone
        vsh = np.full(n, 0.5)
        vsh[:20] = 0.05  # mark first 20 as clean (vsh < 0.3)
        util = StatisticsUtils(pd.DataFrame({"DEPTH": np.arange(n, dtype=float)}))
        swi = util.estimate_swi(pd.Series(sw), pd.Series(vsh))
        # Swi is driven by the clean-zone Sw (~0.1), clipped to >= 0.05.
        assert 0.05 <= swi <= 0.2
