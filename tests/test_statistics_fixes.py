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


def _make_rt_phi_frame(seed=0, n=80):
    rng = np.random.default_rng(seed)
    depth = np.arange(n, dtype=float)
    phi = np.clip(rng.normal(0.22, 0.01, n), 0.15, 0.35)
    # A water leg (RT about 1 ohm.m) over a hydrocarbon leg (RT about 8 ohm.m).
    rt = np.where(depth < 30, 1.0, 8.0) * (1.0 + rng.normal(0.0, 0.02, n))
    # Scatter NaN in BOTH curves at different rows (the common real-world case
    # that triggered the index-misalignment bug).
    rt[5:15] = np.nan
    phi[40:50] = np.nan
    return pd.DataFrame({"DEPTH": depth, "RT": rt, "PHIT": phi})


def _reference_rw(df, a=0.62, m=2.15, n=2.0, threshold=0.15):
    """Index-aligned Rwa reference: median Rwa of the samples with Sw >= 0.8 against the P5 seed."""
    valid = df[["RT", "PHIT"]].dropna()
    valid = valid[(valid["RT"] > 0) & (valid["PHIT"] > threshold)]
    if len(valid) < 10:
        return None
    rwa = valid["RT"] * valid["PHIT"] ** m / a
    seed = np.percentile(rwa, 5)
    water = rwa[rwa <= seed / 0.8 ** n]
    if len(water) < 10:
        return None
    return max(0.01, min(float(water.median()), 5.0))


class TestRwFromRtWaterZone:
    def test_does_not_crash_with_scattered_nan(self):
        df = _make_rt_phi_frame()
        # Must not raise despite NaN gaps in RT and PHI.
        rw, quality = StatisticsUtils(df).estimate_rw_from_rt_water_zone("RT", "PHIT")
        assert rw is not None and quality == "water_leg"
        assert 0.01 <= rw <= 5.0

    def test_matches_index_aligned_reference(self):
        df = _make_rt_phi_frame()
        rw, _quality = StatisticsUtils(df).estimate_rw_from_rt_water_zone("RT", "PHIT")
        assert rw == pytest.approx(_reference_rw(df), rel=1e-9)

    def test_nan_gaps_do_not_change_result_vs_dropped_rows(self):
        # Dropping the NaN rows entirely must give the same answer as leaving
        # them in place (proves the mask is computed on aligned indices only).
        df = _make_rt_phi_frame()
        clean = df.dropna(subset=["RT", "PHIT"]).reset_index(drop=True)
        rw_gappy, _ = StatisticsUtils(df).estimate_rw_from_rt_water_zone("RT", "PHIT")
        rw_clean, _ = StatisticsUtils(clean).estimate_rw_from_rt_water_zone("RT", "PHIT")
        assert rw_gappy == pytest.approx(rw_clean, rel=1e-9)

    def test_returns_none_when_rt_missing(self):
        df = pd.DataFrame({"DEPTH": [1.0, 2.0], "PHIT": [0.2, 0.25]})
        assert StatisticsUtils(df).estimate_rw_from_rt_water_zone("RT", "PHIT") == (None, "no_water")


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


class TestExternalSeriesAlignment:
    def test_reordered_vsh_is_aligned_by_index(self):
        data = pd.DataFrame(
            {"RT": [1.0, 10.0, 100.0]}, index=[10, 11, 12]
        )
        # The high-shale value belongs to row 11, despite arriving reordered.
        vsh = pd.Series([0.0, 0.0, 0.9], index=[12, 10, 11])

        rsh = StatisticsUtils(data).estimate_rsh("RT", vsh_series=vsh, min_samples=1)

        assert rsh == pytest.approx(10.0)

    def test_disjoint_external_index_fails_clearly(self):
        data = pd.DataFrame({"RHOB": [2.6, 2.7]}, index=[10, 11])
        vsh = pd.Series([0.1, 0.1], index=[0, 1])

        with pytest.raises(ValueError, match="index"):
            StatisticsUtils(data).estimate_matrix_density("RHOB", vsh)

    def test_disjoint_sw_index_fails_clearly(self):
        data = pd.DataFrame({"DEPTH": [1000.0, 1001.0]}, index=[10, 11])
        sw = pd.Series([0.2, 0.3], index=[0, 1])
        vsh = pd.Series([0.1, 0.1], index=[10, 11])

        with pytest.raises(ValueError, match="index"):
            StatisticsUtils(data).estimate_swi(sw, vsh)

    def test_all_null_gr_falls_back_for_rsh(self):
        data = pd.DataFrame({
            "RT": [1.0, 2.0, 3.0],
            "GR": [np.nan, np.nan, np.nan],
        })

        rsh = StatisticsUtils(data).estimate_rsh("RT", gr_curve="GR")

        assert np.isfinite(rsh)
        assert 0.5 <= rsh <= 50.0


# ---------------------------------------------------------------------------
# C8: auto-Rw needs a water leg; auto-Rsh needs enough shale; clamps warn
# ---------------------------------------------------------------------------
def _water_share_frame(share, n=500, rw=0.05, hc_sw=0.25, a=0.62, m=2.15, seed=11):
    """Clean porous samples: ``share`` of them water-bearing (Sw 1), the rest at Sw ``hc_sw``.

    Archie with n = 2: Rwa = Rw / Sw^2, so water reads Rwa = Rw = 0.05 and the
    hydrocarbon leg reads 0.05 / 0.25^2 = 0.8.
    """
    rng = np.random.default_rng(seed)
    phi = rng.normal(0.22, 0.005, n)
    n_water = int(round(share * n))
    sw = np.where(np.arange(n) < n_water, 1.0, hc_sw)
    rwa = rw / sw ** 2
    rt = rwa * a / phi ** m * (1.0 + rng.normal(0.0, 0.01, n))
    return pd.DataFrame({"DEPTH": np.arange(n, dtype=float), "RT": rt, "PHIT": phi})


class TestAutoRwWaterLeg:
    @pytest.mark.parametrize("share, expected_rw, expected_quality", [
        (0.5, 0.05, "water_leg"),
        (0.1, 0.05, "water_leg"),
        (0.0, 0.8, "uniform"),
    ])
    def test_scout_repro(self, share, expected_rw, expected_quality):
        util = StatisticsUtils(_water_share_frame(share))
        rw, quality = util.estimate_rw_from_rt_water_zone("RT", "PHIT")
        assert rw == pytest.approx(expected_rw, rel=0.03)
        assert quality == expected_quality
        warnings = util.rw_info["warnings"]
        if quality == "uniform":
            assert any("no water/hydrocarbon contrast" in w for w in warnings)
        else:
            assert warnings == []

    def test_sample_counts_are_kept(self):
        util = StatisticsUtils(_water_share_frame(0.5))
        util.estimate_rw_from_rt_water_zone("RT", "PHIT")
        assert util.rw_info["n_water"] == 250 and util.rw_info["n_hc"] == 250

    def test_no_water_when_fewer_than_ten_water_like_samples(self):
        # Spread of Rwa with no cluster at its minimum: the seed has fewer than ten
        # samples within Sw >= 0.8 of it.
        n = 60
        phi = np.full(n, 0.2)
        rt = np.geomspace(5.0, 500.0, n)
        df = pd.DataFrame({"DEPTH": np.arange(n, dtype=float), "RT": rt, "PHIT": phi})
        rw, quality = StatisticsUtils(df).estimate_rw_from_rt_water_zone("RT", "PHIT")
        assert (rw, quality) == (None, "no_water")

    def test_clamp_warns_when_it_bites(self):
        df = _water_share_frame(0.5, rw=0.001)
        util = StatisticsUtils(df)
        rw, quality = util.estimate_rw_from_rt_water_zone("RT", "PHIT")
        assert rw == 0.01 and quality == "water_leg"
        assert any("outside the allowed range" in w for w in util.rw_info["warnings"])

    def test_pipeline_reports_quality_and_counts(self):
        from modules.pipeline import estimate_rw_rsh

        n = 400
        rng = np.random.default_rng(3)
        df = _water_share_frame(0.5, n=n)
        # Pipeline-ready logs: a clean sand whose density and neutron give PHIE about 0.21.
        df = df.rename(columns={"PHIT": "PHI_IN"}).drop(columns="PHI_IN")
        df["GR"] = 30.0 + rng.random(n)
        df["RHOB"] = 2.65 - 0.21 * 1.65 + rng.normal(0.0, 0.001, n)
        df["NPHI"] = 0.21 + 0.02 + rng.normal(0.0, 0.001, n)
        df["RT"] = _water_share_frame(0.5, n=n)["RT"] * (0.21 / 0.22) ** 2.15
        mapping = {"GR": "GR", "RHOB": "RHOB", "NPHI": "NPHI", "DT": "None", "RT": "RT"}
        out = estimate_rw_rsh(df, mapping, {
            "rw": 0.5, "vsh_baseline_method": "Custom (Manual)",
            "gr_min_manual": 20.0, "gr_max_manual": 120.0})
        assert out["rw_quality"] == "water_leg"
        assert out["rw_water_samples"] > 100 and out["rw_hc_samples"] > 100
        assert out["rw_source"] == "auto"


class TestAutoRshMinimum:
    def _frame(self, n_shale):
        n = 40
        rt = np.full(n, 20.0)
        rt[:n_shale] = 3.0
        vsh = np.zeros(n)
        vsh[:n_shale] = 0.9
        return pd.DataFrame({"RT": rt}), pd.Series(vsh)

    def test_nine_shale_samples_are_not_enough(self):
        data, vsh = self._frame(9)
        util = StatisticsUtils(data)
        assert util.estimate_rsh("RT", vsh, unavailable_default=None) is None
        assert util.rsh_info["n_shale"] == 9

    def test_ten_shale_samples_are_enough(self):
        data, vsh = self._frame(10)
        util = StatisticsUtils(data)
        assert util.estimate_rsh("RT", vsh, unavailable_default=None) == pytest.approx(3.0)
        assert util.rsh_info["n_shale"] == 10 and util.rsh_info["warnings"] == []

    def test_clamp_warns_when_it_bites(self):
        data, vsh = self._frame(12)
        data.loc[:11, "RT"] = 0.1
        util = StatisticsUtils(data)
        assert util.estimate_rsh("RT", vsh, unavailable_default=None) == 0.5
        assert any("outside the allowed range" in w for w in util.rsh_info["warnings"])

    def test_pipeline_warns_and_falls_back(self):
        from modules.pipeline import _auto_rsh

        data, vsh = self._frame(4)
        info = {}
        assert _auto_rsh(StatisticsUtils(data), vsh, "RT", None, info) is None
        assert any("only 4 samples with Vsh above 0.8" in w for w in info["warnings"])
