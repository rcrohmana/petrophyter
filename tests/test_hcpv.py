import pytest
import pandas as pd
import numpy as np
from petrophyter_pyqt.modules.petrophysics import PetrophysicsCalculator


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
        depth = np.array([1000.0, 1001.0, 1003.0])  # dz: 1.0, 2.0
        # dz[0] takes dz[1] -> 1.0

        data = pd.DataFrame(
            {"DEPTH": depth, "PHIE": [0.2, 0.2, 0.2], "SW": [0.5, 0.5, 0.5]}
        )

        calc = PetrophysicsCalculator(data)
        results = calc.calculate_hcpv(
            phie=data["PHIE"], sw=data["SW"], depth=data["DEPTH"]
        )

        # HCPV_frac = 0.1 for all
        # dz: [1.0, 1.0, 2.0] -> Wait, diff gives [1.0, 2.0].
        # Logic: dz = abs(depth.diff())
        # dz[0] = NaN -> filled with dz[1] = 1.0.
        # dz[1] = 1001-1000 = 1.0
        # dz[2] = 1003-1001 = 2.0

        expected_dz = np.array([1.0, 1.0, 2.0])
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
