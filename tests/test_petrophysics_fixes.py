"""
Regression tests for verified numeric bugs in modules/petrophysics.py.

Each test imports the production PetrophysicsCalculator directly (no
reimplementation) and pins the corrected numeric behaviour so the bugs
cannot silently return. Scout review reference: 2026-07-07.
"""

import warnings

import numpy as np
import pandas as pd
import pytest

from modules.petrophysics import PetrophysicsCalculator


# ---------------------------------------------------------------------------
# High finding #1 - Simandoux must honour the saturation exponent n
# ---------------------------------------------------------------------------
class TestSimandouxSaturationExponent:
    def _calc(self):
        # 3 identical rows; RT read from data, phie/vsh passed explicitly.
        data = pd.DataFrame({"RT": [10.0, 10.0, 10.0]})
        return PetrophysicsCalculator(data)

    def test_n2_matches_closed_form_quadratic(self):
        calc = self._calc()
        phie = pd.Series([0.2, 0.2, 0.2])
        vsh = pd.Series([0.3, 0.3, 0.3])
        sw = calc.calculate_sw_simandoux(
            "RT", phie, vsh, rw=0.1, rsh=4.0, a=1.0, m=2.0, n=2.0
        )
        # A=0.4, B=0.075, C=0.1 -> Sw = (-B+sqrt(B^2+4AC))/(2A) = 0.414963
        np.testing.assert_allclose(sw.iloc[0], 0.414963, rtol=1e-4)

    def test_n_actually_changes_result(self):
        calc = self._calc()
        phie = pd.Series([0.2, 0.2, 0.2])
        vsh = pd.Series([0.3, 0.3, 0.3])
        sw1 = calc.calculate_sw_simandoux(
            "RT", phie, vsh, rw=0.1, rsh=4.0, a=1.0, m=2.0, n=1.0
        ).iloc[0]
        sw2 = calc.calculate_sw_simandoux(
            "RT", phie, vsh, rw=0.1, rsh=4.0, a=1.0, m=2.0, n=2.0
        ).iloc[0]
        sw3 = calc.calculate_sw_simandoux(
            "RT", phie, vsh, rw=0.1, rsh=4.0, a=1.0, m=2.0, n=3.0
        ).iloc[0]

        # Hand-solved roots of A*Sw^n + B*Sw - C = 0
        np.testing.assert_allclose(sw1, 0.210526, rtol=1e-4)   # linear in Sw
        np.testing.assert_allclose(sw2, 0.414963, rtol=1e-4)
        np.testing.assert_allclose(sw3, 0.531700, rtol=1e-3)

        # The whole point: they must not collapse to the n=2 answer.
        assert abs(sw1 - sw2) > 0.05
        assert abs(sw3 - sw2) > 0.05


# ---------------------------------------------------------------------------
# High finding #2 - gas correction for PHID must reduce (not inflate) porosity
# ---------------------------------------------------------------------------
class TestGasCorrectionDirection:
    def _gas_calc(self):
        # RHOB low + NPHI low => neutron-density crossover (gas zone).
        data = pd.DataFrame({"RHOB": [2.0, 2.0, 2.0], "NPHI": [0.05, 0.05, 0.05]})
        calc = PetrophysicsCalculator(data)
        calc.calculate_porosity_density("RHOB", rho_matrix=2.65, rho_fluid=1.0)
        calc.calculate_porosity_neutron("NPHI")  # nphi_matrix default -0.02
        return calc

    def test_phid_gas_correction_reduces_porosity(self):
        calc = self._gas_calc()
        vsh0 = pd.Series([0.0, 0.0, 0.0])

        phie_dn = calc.calculate_phie_density_neutron(
            vsh=vsh0, nphi_shale=0.35, rhob_shale=2.45, rho_matrix=2.65, rho_fluid=1.0
        )
        # Isolate the density leg: no neutron correction, no shale correction.
        phie_gas = calc.calculate_phie_gas_corrected(
            vsh=vsh0,
            nphi_shale=0.35,
            rhob_shale=2.45,
            rho_matrix=2.65,
            rho_fluid=1.0,
            gas_nphi_factor=0.0,
            gas_rhob_factor=0.15,
        )

        # PHID = 0.393939, reduced by *(1-0.15) = 0.334848; PHIN = 0.07
        # PHIE_GAS = sqrt((0.334848^2 + 0.07^2)/2) = 0.241892
        np.testing.assert_allclose(phie_gas.iloc[0], 0.241892, rtol=1e-3)

        # Correcting a gas over-read must LOWER effective porosity, never raise it.
        assert phie_gas.iloc[0] < phie_dn.iloc[0]

    def test_gas_flag_marks_crossover(self):
        calc = self._gas_calc()
        calc.calculate_phie_gas_corrected(vsh=pd.Series([0.0, 0.0, 0.0]))
        assert calc.results["GAS_FLAG"].sum() == 3


# ---------------------------------------------------------------------------
# High finding #3 - results["VSH"] must reflect the selected method
# ---------------------------------------------------------------------------
class TestVshDefaultMethod:
    def _calc(self):
        data = pd.DataFrame({"GR": np.linspace(30.0, 140.0, 20)})
        return PetrophysicsCalculator(data)

    def test_larionov_tertiary_only(self):
        calc = self._calc()
        res = calc.calculate_all_vshale("GR", 20, 150, methods=["larionov_tertiary"])
        assert "VSH_LARIO_TERT" in res
        np.testing.assert_allclose(
            calc.results["VSH"].values, res["VSH_LARIO_TERT"].values
        )
        # And it must NOT be the linear IGR any more.
        igr = np.clip((np.linspace(30.0, 140.0, 20) - 20) / (150 - 20), 0, 1)
        assert not np.allclose(calc.results["VSH"].values, igr)

    def test_larionov_older_only(self):
        calc = self._calc()
        res = calc.calculate_all_vshale("GR", 20, 150, methods=["larionov_older"])
        np.testing.assert_allclose(
            calc.results["VSH"].values, res["VSH_LARIO_OLD"].values
        )

    def test_first_selected_method_wins(self):
        calc = self._calc()
        res = calc.calculate_all_vshale(
            "GR", 20, 150, methods=["linear", "larionov_tertiary"]
        )
        np.testing.assert_allclose(calc.results["VSH"].values, res["VSH_LINEAR"].values)

        calc2 = self._calc()
        res2 = calc2.calculate_all_vshale(
            "GR", 20, 150, methods=["larionov_tertiary", "linear"]
        )
        np.testing.assert_allclose(
            calc2.results["VSH"].values, res2["VSH_LARIO_TERT"].values
        )


# ---------------------------------------------------------------------------
# High finding #4 - HCPV must not explode across a depth gap
# ---------------------------------------------------------------------------
class TestHcpvDepthGap:
    def test_non_adjacent_formation_gap_is_neutralized(self):
        # Formation A (1000-1002) and C (2000-2002) selected, B skipped.
        depth = pd.Series([1000.0, 1001.0, 1002.0, 2000.0, 2001.0, 2002.0])
        phie = pd.Series([0.15] * 6)
        sw = pd.Series([0.30] * 6)
        data = pd.DataFrame({"DEPTH": depth})
        calc = PetrophysicsCalculator(data)

        results = calc.calculate_hcpv(phie=phie, sw=sw, depth=depth)

        # HCPV_frac = 0.15*0.7 = 0.105 everywhere; median step = 1 ft.
        # Gap dz (~998 ft) must be capped -> every dHCPV == 0.105.
        np.testing.assert_allclose(results["dHCPV"].values, [0.105] * 6, rtol=1e-6)
        # Cumulative must be ~0.63, not the ~105 the raw gap would produce.
        np.testing.assert_allclose(results["HCPV_CUM"].iloc[-1], 0.63, rtol=1e-6)
        assert results["dHCPV"].max() < 1.0

    def test_legitimate_variable_step_preserved(self):
        # A 2x step is normal sampling variation, not a gap: keep it.
        depth = pd.Series([1000.0, 1001.0, 1003.0])
        phie = pd.Series([0.2, 0.2, 0.2])
        sw = pd.Series([0.5, 0.5, 0.5])
        calc = PetrophysicsCalculator(pd.DataFrame({"DEPTH": depth}))
        results = calc.calculate_hcpv(phie=phie, sw=sw, depth=depth)
        # dz filled = [1.0, 1.0, 2.0]; HCPV_frac = 0.1
        np.testing.assert_allclose(
            results["dHCPV"].values, [0.1, 0.1, 0.2], rtol=1e-6
        )


# ---------------------------------------------------------------------------
# High finding #5 - Indonesian closed form (no silent Archie fallback)
# ---------------------------------------------------------------------------
class TestIndonesianClosedForm:
    def test_known_value(self):
        data = pd.DataFrame({"RT": [20.0]})
        calc = PetrophysicsCalculator(data)
        sw = calc.calculate_sw_indonesian(
            "RT", pd.Series([0.15]), pd.Series([0.2]),
            rw=0.05, rsh=5.0, a=0.62, m=2.15, n=2.0,
        )
        # Closed form Sw = (lhs/(term1+term2))^(2/n) = 0.264932
        np.testing.assert_allclose(sw.iloc[0], 0.264932, rtol=1e-4)

    def test_uses_vsh_not_archie_fallback(self):
        # Shaly point: Indonesian must sit BELOW pure Archie (shale adds
        # conductivity attributed to clay, not water).
        data = pd.DataFrame({"RT": [20.0]})
        calc = PetrophysicsCalculator(data)
        sw_indo = calc.calculate_sw_indonesian(
            "RT", pd.Series([0.15]), pd.Series([0.2]),
            rw=0.05, rsh=5.0, a=0.62, m=2.15, n=2.0,
        ).iloc[0]
        sw_archie = calc.calculate_sw_archie(
            "RT", pd.Series([0.15]), rw=0.05, a=0.62, m=2.15, n=2.0
        ).iloc[0]
        assert sw_indo < sw_archie

    def test_anomalous_low_rt_no_nan_no_crash(self):
        # RT=0.05 made the old brentq bracket fail (same-sign endpoints).
        data = pd.DataFrame({"RT": [20.0, 0.05, 100.0]})
        calc = PetrophysicsCalculator(data)
        sw = calc.calculate_sw_indonesian(
            "RT", pd.Series([0.15, 0.15, 0.2]), pd.Series([0.2, 0.3, 0.1]),
            rw=0.05, rsh=5.0, a=0.62, m=2.15, n=2.0,
        )
        assert not sw.isna().any()
        assert (sw >= 0).all() and (sw <= 1).all()
        # Over-conductive zone saturates to water.
        np.testing.assert_allclose(sw.iloc[1], 1.0, rtol=1e-6)


# ---------------------------------------------------------------------------
# High finding #6 - permeability Swi falls back to primary SW, not SW_ARCHIE
# ---------------------------------------------------------------------------
class TestPermeabilitySwiFallback:
    def test_timur_uses_primary_sw(self):
        calc = PetrophysicsCalculator(pd.DataFrame({"X": [1, 2, 3]}))
        calc.results["SW"] = pd.Series([0.3, 0.3, 0.3])  # no SW_ARCHIE present
        k = calc.calculate_permeability_timur(phie=pd.Series([0.2, 0.2, 0.2]))
        # 8581 * 0.2^4.4 / 0.3^2 = 80.27 (uses SW=0.3, not the flat 0.2 fallback)
        np.testing.assert_allclose(k.iloc[0], 80.27, rtol=1e-2)

    def test_wyllie_rose_uses_primary_sw(self):
        calc = PetrophysicsCalculator(pd.DataFrame({"X": [1, 2, 3]}))
        calc.results["SW"] = pd.Series([0.3, 0.3, 0.3])
        k = calc.calculate_permeability_wyllie_rose(phie=pd.Series([0.2, 0.2, 0.2]))
        # 100 * 0.2^4.5 / 0.3^2 = 0.7947
        np.testing.assert_allclose(k.iloc[0], 0.7947, rtol=1e-2)


# ---------------------------------------------------------------------------
# Quick wins
# ---------------------------------------------------------------------------
class TestQuickWins:
    def test_constant_gr_returns_nan_without_warning(self):
        calc = PetrophysicsCalculator(pd.DataFrame({"GR": [50.0, 50.0, 50.0, 50.0]}))
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            vsh = calc.calculate_vshale_linear("GR")
        assert vsh.isna().all()
        assert "VSH" in calc.results.columns
        assert calc.results["VSH"].isna().all()

    def test_dual_water_runs_and_records_diagnostics(self):
        data = pd.DataFrame({"RT": [50.0, 2.0, 10.0, 0.5]})
        calc = PetrophysicsCalculator(data)
        sw = calc.calculate_sw_dual_water(
            "RT", pd.Series([0.2, 0.2, 0.2, 0.2]), rw=0.05, swb=0.1, rwb=0.2
        )
        assert "SW_DW" in calc.results.columns
        valid = sw.dropna()
        assert ((valid >= 0) & (valid <= 1)).all()
        assert "SW_DW" in calc.solver_diagnostics

    def test_waxman_smits_records_diagnostics(self):
        data = pd.DataFrame({"RT": [50.0, 2.0, 10.0]})
        calc = PetrophysicsCalculator(data)
        calc.calculate_sw_waxman_smits("RT", pd.Series([0.2, 0.2, 0.2]), rw=0.05)
        assert "SW_WS" in calc.solver_diagnostics


# ---------------------------------------------------------------------------
# Medium finding - PHIE method needs a meaningful valid fraction
# ---------------------------------------------------------------------------
class TestPhieAvailabilityThreshold:
    def test_mostly_nan_method_not_selected_as_primary(self):
        n = 100
        data = pd.DataFrame(
            {
                "RHOB": [2.3] * n,
                "NPHI": [0.2] * n,
            }
        )
        calc = PetrophysicsCalculator(data)
        calc.calculate_porosity_density("RHOB")
        calc.calculate_porosity_neutron("NPHI")

        # Build a PHIE_S that is valid in only 1 of 100 rows.
        phis = pd.Series([np.nan] * n)
        phis.iloc[0] = 0.2
        calc.results["PHIS"] = phis

        vsh0 = pd.Series([0.0] * n)
        calc.calculate_all_phie(vsh=vsh0, primary_method="PHIE_S")

        # Primary must fall back off the almost-empty PHIE_S.
        assert calc.phie_method_used != "PHIE_S"
        assert calc.results["PHIE"].notna().sum() > n * 0.5
