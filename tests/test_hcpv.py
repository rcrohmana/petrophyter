import pytest
import pandas as pd
import numpy as np
from modules.petrophysics import PetrophysicsCalculator, depth_increments


class TestHCPV:
    """Test suite for Hydrocarbon Pore Volume calculations."""

    @pytest.fixture
    def sample_data(self):
        """Create sample log data for testing."""
        depth = np.array([1000.0, 1000.5, 1001.0, 1001.5, 1002.0])
        # dz will be 0.5 for all

        data = pd.DataFrame(
            {
                "DEPTH": depth,
                # PHIE: 0.2, 0.25, 0.1, 0.3, 0.2
                "PHIE": [0.20, 0.25, 0.10, 0.30, 0.20],
                # SW: 0.5, 0.2, 0.8, 0.4, 1.0
                "SW": [0.50, 0.20, 0.80, 0.40, 1.00],
                # Flags for gating
                # Res: 1, 1, 0, 1, 1
                # Pay: 1, 1, 0, 1, 0
            }
        )
        return data

    def test_hcpv_calculation_basics(self, sample_data):
        """Test basic HCPV fraction and incremental calculations."""
        calc = PetrophysicsCalculator(sample_data)

        # Manually defined flags
        net_res_flag = pd.Series([1, 1, 0, 1, 1])
        net_pay_flag = pd.Series([1, 1, 0, 1, 0])

        results = calc.calculate_hcpv(
            phie=sample_data["PHIE"],
            sw=sample_data["SW"],
            depth=sample_data["DEPTH"],
            net_res_flag=net_res_flag,
            net_pay_flag=net_pay_flag,
        )

        # Expected calculations
        # Row 0: PHIE=0.2, Sw=0.5 -> HCPV_frac = 0.1. dz=0.5. dHCPV=0.05
        # Row 1: PHIE=0.25, Sw=0.2 -> HCPV_frac = 0.2. dz=0.5. dHCPV=0.1
        # Row 2: PHIE=0.1, Sw=0.8 -> HCPV_frac = 0.02. dz=0.5. dHCPV=0.01
        # Row 3: PHIE=0.3, Sw=0.4 -> HCPV_frac = 0.18. dz=0.5. dHCPV=0.09
        # Row 4: PHIE=0.2, Sw=1.0 -> HCPV_frac = 0.0. dz=0.5. dHCPV=0.0

        expected_frac = np.array([0.1, 0.2, 0.02, 0.18, 0.0])
        expected_dhcpv = expected_frac * 0.5

        np.testing.assert_allclose(results["HCPV_FRAC"], expected_frac, rtol=1e-5)
        np.testing.assert_allclose(results["dHCPV"], expected_dhcpv, rtol=1e-5)

        # Test Cumulative
        expected_cum = expected_dhcpv.cumsum()
        np.testing.assert_allclose(results["HCPV_CUM"], expected_cum, rtol=1e-5)

    def test_hcpv_net_pay(self, sample_data):
        """Test HCPV with Net Pay gating."""
        calc = PetrophysicsCalculator(sample_data)

        # Pay flag: 1, 1, 0, 1, 0
        net_pay_flag = pd.Series([1, 1, 0, 1, 0])

        results = calc.calculate_hcpv(
            phie=sample_data["PHIE"],
            sw=sample_data["SW"],
            depth=sample_data["DEPTH"],
            net_res_flag=pd.Series([1] * 5),
            net_pay_flag=net_pay_flag,
        )

        # Expected HCPV_frac (from before): [0.1, 0.2, 0.02, 0.18, 0.0]
        # Apply Pay Flag: [0.1, 0.2, 0.0, 0.18, 0.0]
        # dHCPV (dz=0.5): [0.05, 0.1, 0.0, 0.09, 0.0]

        expected_dhcpv_pay = np.array([0.05, 0.1, 0.0, 0.09, 0.0])
        expected_cum_pay = expected_dhcpv_pay.cumsum()

        np.testing.assert_allclose(
            results["dHCPV_NET_PAY"], expected_dhcpv_pay, rtol=1e-5
        )
        np.testing.assert_allclose(
            results["HCPV_CUM_NET_PAY"], expected_cum_pay, rtol=1e-5
        )

        # Verify Row 2 (index 2) is 0 because Pay Flag is 0, even though HCPV_frac is 0.02
        assert results["dHCPV_NET_PAY"][2] == 0

    def test_hcpv_defaults(self, sample_data):
        """Test that method works with internal results if args not provided."""
        calc = PetrophysicsCalculator(sample_data)

        # Setup internal results
        calc.results["PHIE"] = sample_data["PHIE"]
        calc.results["SW"] = sample_data["SW"]
        calc.results["NET_RES_FLAG"] = pd.Series([1] * 5)
        calc.results["NET_PAY_FLAG"] = pd.Series([1] * 5)

        # Call without args
        results = calc.calculate_hcpv()

        # Should calculate based on internal results
        assert "HCPV_CUM" in results
        assert len(results["HCPV_CUM"]) == 5

    def test_depth_handling(self):
        """Test variable depth steps."""
        depth = np.array([1000.0, 1001.0, 1003.0])  # intervals: 1.0, 2.0

        data = pd.DataFrame(
            {"DEPTH": depth, "PHIE": [0.2, 0.2, 0.2], "SW": [0.5, 0.5, 0.5]}
        )

        calc = PetrophysicsCalculator(data)
        results = calc.calculate_hcpv(
            phie=data["PHIE"], sw=data["SW"], depth=data["DEPTH"]
        )

        # HCPV_frac = 0.1 for all
        # Midpoint rule (depth_increments): intervals 1.0 and 2.0.
        # dz[0] = 1.0 (its one interval), dz[1] = (1.0 + 2.0) / 2 = 1.5,
        # dz[2] = 2.0 (its one interval)

        expected_dz = np.array([1.0, 1.5, 2.0])
        expected_dhcpv = 0.1 * expected_dz

        np.testing.assert_allclose(results["dHCPV"], expected_dhcpv, rtol=1e-5)

    def test_hcpv_filtered_index_alignment(self):
        """Test HCPV with filtered data (Per-Formation mode simulation).

        This is a regression test for the index mismatch bug where
        reset_index(drop=True) caused NaN values when DataFrame had
        non-contiguous indices (e.g., from formation filtering).
        """
        # Simulate filtered data with non-contiguous index
        # (like when Per-Formation filter is applied)
        depth = np.array([1500.0, 1500.5, 1501.0, 1501.5, 1502.0])

        data = pd.DataFrame(
            {
                "DEPTH": depth,
                "PHIE": [0.20, 0.25, 0.15, 0.30, 0.22],
                "SW": [0.40, 0.30, 0.50, 0.35, 0.45],
            },
            index=[500, 501, 502, 503, 504],  # Non-contiguous index!
        )

        calc = PetrophysicsCalculator(data)

        # Create flags with matching index
        net_res_flag = pd.Series([1, 1, 1, 1, 1], index=[500, 501, 502, 503, 504])
        net_pay_flag = pd.Series([1, 1, 0, 1, 1], index=[500, 501, 502, 503, 504])

        results = calc.calculate_hcpv(
            phie=data["PHIE"],
            sw=data["SW"],
            depth=data["DEPTH"],
            net_res_flag=net_res_flag,
            net_pay_flag=net_pay_flag,
        )

        # Verify NO NaN values in results (the bug would cause NaN)
        assert not results["HCPV_FRAC"].isna().any(), (
            "HCPV_FRAC contains NaN - index alignment bug!"
        )
        assert not results["dHCPV"].isna().any(), (
            "dHCPV contains NaN - index alignment bug!"
        )
        assert not results["HCPV_CUM"].isna().any(), (
            "HCPV_CUM contains NaN - index alignment bug!"
        )
        assert not results["HCPV_NET_PAY"].isna().any(), (
            "HCPV_NET_PAY contains NaN - index alignment bug!"
        )

        # Verify the index of results matches the original data index
        assert list(calc.results.index) == [500, 501, 502, 503, 504]

        # Verify results stored in calc.results are also correct (not NaN)
        assert not calc.results["HCPV_FRAC"].isna().any()
        assert not calc.results["dHCPV"].isna().any()

        # Verify actual calculated values are reasonable
        # HCPV_frac = PHIE * (1 - SW)
        # Row 0: 0.20 * (1 - 0.40) = 0.12
        expected_frac_0 = 0.20 * (1 - 0.40)
        np.testing.assert_allclose(
            results["HCPV_FRAC"].iloc[0], expected_frac_0, rtol=1e-5
        )


# ---------------------------------------------------------------------------
# C10: one local-step dz rule for thickness and HCPV
# ---------------------------------------------------------------------------
def _mixed_step_depth():
    """500 ft sampled every 0.1524 ft, then 100 ft every 0.5 ft."""
    fine = 1000.0 + 0.1524 * np.arange(int(500 / 0.1524) + 1)
    coarse = fine[-1] + 0.5 * np.arange(1, 201)
    return np.concatenate([fine, coarse]), len(fine)


class TestOneDzRule:
    def _run(self, depth):
        n = len(depth)
        data = pd.DataFrame({"DEPTH": depth})
        calc = PetrophysicsCalculator(data)
        vsh, phie, sw = (pd.Series(np.full(n, v)) for v in (0.1, 0.2, 0.5))
        pay = calc.calculate_net_pay(vsh, phie, sw)
        hcpv = calc.calculate_hcpv(phie=phie, sw=sw, depth=data["DEPTH"])
        return calc, pay, hcpv

    def test_mixed_step_thickness_matches_the_depth_range_for_net_pay_and_hcpv(self):
        depth, n_fine = _mixed_step_depth()
        calc, pay, hcpv = self._run(depth)
        length = depth[-1] - depth[0]
        # Whole log: its length plus the two end half-intervals (within one step).
        assert pay["net_pay"] == pytest.approx(length, abs=0.5)
        # HCPV_frac = 0.2 x 0.5 = 0.1 everywhere, so dHCPV / 0.1 is the thickness.
        thickness = hcpv["dHCPV"] / 0.1
        assert thickness.sum() == pytest.approx(pay["net_pay"], rel=1e-12)
        # The coarse part is worth 100 ft (the old HCPV rule gave 30.46 ft).
        coarse = thickness.iloc[n_fine:].sum()
        assert coarse == pytest.approx(100.0, abs=0.5)
        fine = thickness.iloc[:n_fine].sum()
        assert fine == pytest.approx(500.0, abs=0.5)

    def test_net_pay_and_hcpv_use_the_same_dz(self):
        depth, _ = _mixed_step_depth()
        calc, pay, hcpv = self._run(depth)
        np.testing.assert_allclose(hcpv["dHCPV"].to_numpy() / 0.1,
                                   depth_increments(pd.Series(depth)).to_numpy(), rtol=1e-12)
        assert pay["net_pay"] == pytest.approx(hcpv["dHCPV"].sum() / 0.1, rel=1e-12)

    def test_per_formation_zones_300_ft_apart_add_one_local_step(self):
        upper = 1000.0 + 0.5 * np.arange(21)          # 1000 to 1010 ft
        lower = 1310.0 + 0.5 * np.arange(21)          # 300 ft further down
        depth = np.concatenate([upper, lower])
        calc, pay, hcpv = self._run(depth)
        # 42 samples x 0.5 ft: the 300 ft hole between the zones counts as one 0.5 ft step.
        assert pay["net_pay"] == pytest.approx(21.0, rel=1e-12)
        assert (hcpv["dHCPV"] / 0.1).sum() == pytest.approx(21.0, rel=1e-12)

    def test_pipeline_zone_rows_sum_to_the_well(self):
        from modules.pipeline import run_pipeline
        from tests.golden.cases import FULL_MAPPING, build_case, make_tops

        data, mapping, params, _ = build_case("mixed_depth_step")
        tops = _tops_for(data)
        _, summary = run_pipeline(data, mapping, params, formation_tops=tops)
        zones = summary["zones"]
        assert len(zones) == 2
        assert sum(z["net_pay"] for z in zones) == pytest.approx(summary["net_pay"], rel=1e-9)
        assert sum(z["phih_pay"] for z in zones) == pytest.approx(summary["phih_pay"], rel=1e-9)


def _tops_for(data):
    import io

    from modules.formation_tops import FormationTops

    mid = float(data["DEPTH"].iloc[len(data) // 2])
    top, bottom = float(data["DEPTH"].iloc[0]), float(data["DEPTH"].iloc[-1])
    tops = FormationTops()
    assert tops.read_tops_from_buffer(io.StringIO(
        f"Formation\tTop (ft)\tBottom (ft)\nUpper\t{top}\t{mid}\nLower\t{mid}\t{bottom}\n"))
    return tops


# ---------------------------------------------------------------------------
# C12: weighted pay averages
# ---------------------------------------------------------------------------
class TestWeightedPayAverages:
    def test_pipeline_averages_follow_the_definition(self):
        from modules.pipeline import run_pipeline
        from tests.golden.cases import build_case

        data, mapping, params, _ = build_case("mixed_depth_step")
        results, summary = run_pipeline(data, mapping, params)
        pay = results["NET_PAY_FLAG"].astype(bool).to_numpy()
        dz = depth_increments(data["DEPTH"]).to_numpy()
        phie, sw, vsh = (results[c].to_numpy() for c in ("PHIE", "SW", "VSH"))
        assert pay.any()
        assert summary["net_pay"] == pytest.approx(dz[pay].sum(), rel=1e-12)
        assert summary["phih_pay"] == pytest.approx((phie[pay] * dz[pay]).sum(), rel=1e-12)
        assert summary["avg_phie_pay"] == pytest.approx(
            (phie[pay] * dz[pay]).sum() / dz[pay].sum(), rel=1e-12)
        assert summary["avg_vsh_pay"] == pytest.approx(
            (vsh[pay] * dz[pay]).sum() / dz[pay].sum(), rel=1e-12)
        assert summary["avg_sw_pay"] == pytest.approx(
            (phie[pay] * sw[pay] * dz[pay]).sum() / (phie[pay] * dz[pay]).sum(), rel=1e-12)
        # With varying porosity the pore-volume weighted Sw differs from the plain mean.
        assert summary["avg_sw_pay"] != pytest.approx(sw[pay].mean(), rel=1e-6)

    def test_calculator_matches_the_pipeline_helper(self):
        depth, _ = _mixed_step_depth()
        n = len(depth)
        rng = np.random.default_rng(5)
        phie = pd.Series(rng.uniform(0.1, 0.3, n))
        sw = pd.Series(rng.uniform(0.1, 0.5, n))
        calc = PetrophysicsCalculator(pd.DataFrame({"DEPTH": depth}))
        pay = calc.calculate_net_pay(pd.Series(np.full(n, 0.1)), phie, sw)
        dz = depth_increments(pd.Series(depth)).to_numpy()
        assert pay["avg_sw_pay"] == pytest.approx(
            (phie * sw * dz).sum() / (phie * dz).sum(), rel=1e-12)
        assert pay["phih_pay"] == pytest.approx((phie * dz).sum(), rel=1e-12)
