"""Rw/Rsh modes, the Rwa estimator, the shared GR baseline rule, and VSH consistency."""

import numpy as np
import pandas as pd
import pytest

from models.app_model import AppModel
from modules.petrophysics import PetrophysicsCalculator
from modules.pipeline import estimate_rw_rsh, run_pipeline
from modules.statistics_utils import StatisticsUtils, gr_baseline_from_series
from services.analysis_service import AnalysisService

MAPPING = {"GR": "GR", "RHOB": "RHOB", "NPHI": "NPHI", "DT": "None", "RT": "RT"}
WATER_RT = 1.0


def _zoned_frame(shale_rt=0.2):
    """Clean water sand, clean hydrocarbon sand, then low-RT shale.

    The shale is built so that raw NPHI (0.40) with Sw = 1 gives a lower Rwa than
    the clean water sand; the old estimator picked it up.
    """
    t = np.linspace(0.0, 1.0, 60)
    water = pd.DataFrame(
        {"GR": 25 + t, "RHOB": 2.2375 + 0.001 * t, "NPHI": 0.25 + 0.001 * t, "RT": WATER_RT + 0.01 * t}
    )
    oil = water.assign(RT=30.0 + t)
    n_shale = 80
    s = np.linspace(0.0, 1.0, n_shale)
    shale = pd.DataFrame(
        {"GR": 120 - s, "RHOB": 2.5 + 0.001 * s, "NPHI": 0.40 + 0.001 * s, "RT": shale_rt + 0.001 * s}
    )
    frame = pd.concat([water, oil, shale], ignore_index=True)
    frame.insert(0, "DEPTH", np.arange(len(frame), dtype=float) + 1000.0)
    return frame


def _clean_frame(n=60):
    frame = _zoned_frame().iloc[:n].copy()
    frame["RT"] = 5.0 + np.linspace(0, 1, len(frame))
    return frame


class TestRshModes:
    def test_manual_rsh_is_respected(self):
        _, summary = run_pipeline(_zoned_frame(), MAPPING, {"rsh": 7.5, "rsh_mode": "manual"})
        assert summary["rsh"] == 7.5
        assert summary["rsh_source"] == "manual"

    def test_auto_rsh_is_estimated(self):
        data = _zoned_frame()
        results, summary = run_pipeline(data, MAPPING, {"rsh": 7.5, "rsh_mode": "auto"})
        expected = StatisticsUtils(data).estimate_rsh("RT", results["VSH"])
        assert summary["rsh"] == pytest.approx(expected)
        assert summary["rsh"] != 7.5
        assert summary["rsh_source"] == "auto"

    def test_auto_rsh_fallback_warns(self):
        # No sample has VSH > 0.8 in a single-GR-value frame.
        data = _clean_frame()
        data["GR"] = np.linspace(20.0, 60.0, len(data))
        _, summary = run_pipeline(
            data, MAPPING, {"rsh": 7.5, "rsh_mode": "auto", "vsh_baseline_method": "Custom (Manual)",
                            "gr_min_manual": 20.0, "gr_max_manual": 200.0}
        )
        assert summary["rsh"] == 7.5
        assert summary["rsh_source"] == "manual (auto estimate unavailable)"
        assert any("Rsh could not be estimated" in w for w in summary["warnings"])


class TestRwModes:
    def test_manual_rw_used_even_when_below_old_sentinel(self):
        _, summary = run_pipeline(_zoned_frame(), MAPPING, {"rw": 0.008, "rw_mode": "manual"})
        assert summary["rw"] == 0.008
        assert summary["rw_source"] == "manual"

    def test_auto_rw_uses_phie_and_clean_filter(self):
        data = _zoned_frame()
        results, summary = run_pipeline(data, MAPPING, {"rw": 0.5, "rw_mode": "auto"})

        water = results.iloc[:60]
        expected = float((water["RT"] * water["PHIE"] ** 2.15 / 0.62).median())
        # Samples at or below P25 of Rwa are the clean water sand.
        assert summary["rw"] == pytest.approx(expected, rel=0.1)
        assert summary["rw_source"] == "auto"

        # Without the clean filter the low-RT shale wins, which is the old failure mode.
        shale_fooled = StatisticsUtils(data).estimate_rw_from_rt_water_zone("RT", "NPHI")
        assert shale_fooled < 0.75 * summary["rw"]

    def test_too_few_samples_falls_back_with_warning(self):
        data = _zoned_frame().iloc[:8]
        _, summary = run_pipeline(data, MAPPING, {"rw": 0.123, "rw_mode": "auto"})
        assert summary["rw"] == 0.123
        assert summary["rw_source"] == "manual (auto estimate unavailable)"
        assert any("Rw could not be estimated" in w for w in summary["warnings"])

    def test_estimator_requires_minimum_candidates(self):
        data = _zoned_frame()
        util = StatisticsUtils(data)
        assert util.estimate_rw_from_rt_water_zone("RT", "NPHI", min_samples=10_000) is None


class TestSingleGrBaseline:
    def test_calculate_rw_rsh_matches_pipeline_auto_run(self):
        data = _zoned_frame()
        model = AppModel()
        model.las_data = data
        model.curve_mapping = dict(MAPPING)
        model.rw_mode = "auto"
        model.rsh_mode = "auto"

        calculated = AnalysisService().calculate_rw_rsh(model)
        _, summary = run_pipeline(data, MAPPING, model.to_params())

        assert calculated["rw"] == round(summary["rw"], 4)
        assert calculated["rsh"] == round(summary["rsh"], 2)
        helper = estimate_rw_rsh(data, MAPPING, model.to_params())
        assert (helper["gr_min"], helper["gr_max"]) == (summary["gr_min"], summary["gr_max"])
        assert (helper["gr_min"], helper["gr_max"]) == gr_baseline_from_series(data["GR"])

    def test_vshale_auto_baseline_uses_shared_rule(self):
        # P5/P95 are about 15 API apart: more than the old Vshale limit (10), less
        # than the shared limit (20), so the shared rule widens to min/max.
        gr = pd.Series(np.r_[np.full(5, 10.0), np.linspace(40, 55, 90), np.full(5, 90.0)])
        data = pd.DataFrame({"DEPTH": np.arange(len(gr), dtype=float), "GR": gr})
        low, high = gr_baseline_from_series(gr)
        assert (low, high) == (10.0, 90.0)

        vsh = PetrophysicsCalculator(data).calculate_vshale_linear("GR")
        assert vsh.equals(((gr - low) / (high - low)).clip(0, 1))


class TestVshColumnMatchesDownstream:
    def test_vsh_column_is_the_reference_series_with_several_methods(self):
        data = _zoned_frame()
        results, _ = run_pipeline(
            data, MAPPING, {"vsh_methods": ["Larionov Older", "Linear"]}
        )
        reference = results[["VSH_LARIO_OLD", "VSH_LINEAR"]].max(axis=1)
        assert results["VSH"].equals(reference)
        assert not results["VSH"].equals(results["VSH_LARIO_OLD"])


class TestNphiPercentGuard:
    def test_percent_nphi_adds_warning(self):
        data = _zoned_frame()
        data["NPHI"] = data["NPHI"] * 100.0
        _, summary = run_pipeline(data, MAPPING, {})
        assert any("percent" in w for w in summary["warnings"])

    def test_fractional_nphi_has_no_warning(self):
        _, summary = run_pipeline(_zoned_frame(), MAPPING, {})
        assert not any("percent" in w for w in summary["warnings"])
