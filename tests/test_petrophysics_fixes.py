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
        # PHIE_GAS = (0.334848 + 0.07)/2 = 0.202424 (average of the corrected pair, C4)
        np.testing.assert_allclose(phie_gas.iloc[0], 0.202424, rtol=1e-3)

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
        # Midpoint rule: intervals 1.0 and 2.0 give dz = [1.0, 1.5, 2.0]; HCPV_frac = 0.1
        np.testing.assert_allclose(
            results["dHCPV"].values, [0.1, 0.15, 0.2], rtol=1e-6
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

    def test_all_null_gr_returns_nan_without_crashing(self):
        calc = PetrophysicsCalculator(
            pd.DataFrame({"GR": [np.nan, np.nan, np.nan]})
        )
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            vsh = calc.calculate_vshale_linear("GR")
        assert vsh.isna().all()
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

    def test_swirr_clean_zone_handles_all_null_sw(self):
        calc = PetrophysicsCalculator(
            pd.DataFrame({"RT": [1.0, 2.0, 3.0]})
        )
        sw = pd.Series([np.nan, np.nan, np.nan])
        vsh = pd.Series([0.5, 0.5, 0.5])

        result = calc.calculate_swirr_clean_zone(sw=sw, vsh=vsh)
        statistical = calc.calculate_swirr_statistical(sw=sw, vsh=vsh)

        assert result.notna().all()
        assert statistical.notna().all()
        assert ((result >= 0.05) & (result <= 0.5)).all()
        assert ((statistical >= 0.05) & (statistical <= 0.5)).all()


class TestPrimarySwFallback:
    def test_net_pay_prefers_primary_sw_over_archie(self):
        data = pd.DataFrame({"DEPTH": [1000.0, 1001.0]})
        calc = PetrophysicsCalculator(data)
        calc.results["SW"] = pd.Series([0.2, 0.2])
        calc.results["SW_ARCHIE"] = pd.Series([0.9, 0.9])

        summary = calc.calculate_net_pay(
            vsh=pd.Series([0.1, 0.1]),
            phie=pd.Series([0.2, 0.2]),
            step=1.0,
        )

        assert summary["net_pay"] == pytest.approx(2.0)


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

    def test_no_method_is_selected_when_all_curves_are_mostly_nan(self):
        n = 100
        data = pd.DataFrame({
            "RHOB": [np.nan] * n,
            "NPHI": [np.nan] * n,
        })
        data.loc[0, "RHOB"] = 2.3
        data.loc[0, "NPHI"] = 0.2
        calc = PetrophysicsCalculator(data)
        calc.calculate_porosity_density("RHOB")
        calc.calculate_porosity_neutron("NPHI")

        calc.calculate_all_phie(
            vsh=pd.Series([0.0] * n), primary_method="PHIE_DN"
        )

        # No method clears the >=50% bar: PHIE is the best partial method
        # (NaN elsewhere), never a fabricated value (I11).
        assert calc.phie_method_used == "PHIE_DN"
        assert calc.phie_partial[0] == "PHIE_DN"
        assert calc.results["PHIE"].notna().sum() == 1

    def test_reuse_clears_stale_primary_when_no_method_is_available(self):
        n = 10
        data = pd.DataFrame({
            "RHOB": [2.3] * n,
            "NPHI": [0.2] * n,
        })
        calc = PetrophysicsCalculator(data)
        calc.calculate_porosity_density("RHOB")
        calc.calculate_porosity_neutron("NPHI")

        calc.calculate_all_phie(
            vsh=pd.Series([0.0] * n), primary_method="PHIE_DN"
        )
        assert calc.phie_method_used == "PHIE_DN"
        assert calc.results["PHIE"].notna().all()

        nulls = pd.Series([np.nan] * n)
        calc.results["PHID"] = nulls.copy()
        calc.results["PHIN"] = nulls.copy()
        calc.results["PHIS"] = nulls.copy()
        calc.calculate_all_phie(
            vsh=pd.Series([0.0] * n), primary_method="PHIE_DN"
        )

        assert calc.results["PHIE"].isna().all()
        assert calc.phie_method_used is None
        assert calc.phie_partial == (None, 0.0)


# ---------------------------------------------------------------------------
# P0 v1.7.2 porosity: C1 (PHIT on every path), C4 (gas flag), C5 (neutron shale)
# ---------------------------------------------------------------------------
def _porosity_calc(**columns):
    """Calculator whose results already hold the given porosity columns."""
    n = len(next(iter(columns.values())))
    calc = PetrophysicsCalculator(pd.DataFrame({"X": np.zeros(n)}))
    for name, values in columns.items():
        calc.results[name] = pd.Series(values, dtype=float)
    return calc


class TestPhitCombination:
    def test_average_keeps_signs(self):
        calc = _porosity_calc(PHID=[-0.05, 0.152], PHIN=[0.00, 0.35])
        phit = calc.calculate_phit_neutron_density(dn_combination="Average")
        assert phit.iloc[0] == 0.0                      # mean -0.025 clipped, never a positive square
        assert phit.iloc[1] == pytest.approx(0.251)

    def test_rms_reproduces_the_old_value(self):
        calc = _porosity_calc(PHID=[-0.05, 0.152], PHIN=[0.00, 0.35])
        phit = calc.calculate_phit_neutron_density(dn_combination="RMS")
        assert phit.iloc[0] == pytest.approx(0.0354, abs=1e-4)
        assert phit.iloc[1] == pytest.approx(0.2698, abs=1e-4)

    def test_default_is_average(self):
        calc = _porosity_calc(PHID=[0.10], PHIN=[0.30])
        assert calc.calculate_phit_neutron_density().iloc[0] == pytest.approx(0.20)

    def test_gas_samples_use_rms_whatever_the_setting(self):
        calc = _porosity_calc(PHID=[0.35, 0.35], PHIN=[0.22, 0.22])
        flag = pd.Series([True, False])
        phit = calc.calculate_phit_neutron_density(dn_combination="Average", gas_flag=flag)
        assert phit.iloc[0] == pytest.approx(np.sqrt((0.35**2 + 0.22**2) / 2))
        assert phit.iloc[1] == pytest.approx(0.285)

    def test_single_input_paths(self):
        assert _porosity_calc(PHID=[0.2]).calculate_phit_neutron_density().iloc[0] == 0.2
        assert _porosity_calc(PHIN=[0.18]).calculate_phit_neutron_density().iloc[0] == 0.18
        assert _porosity_calc(PHIS=[0.12]).calculate_phit_neutron_density().iloc[0] == 0.12
        assert _porosity_calc(PHIS=[0.12], PHID=[0.2]).calculate_phit_neutron_density().iloc[0] == 0.2
        none = _porosity_calc(VSH=[0.1]).calculate_phit_neutron_density()
        assert none.isna().all()

    def test_per_sample_fallback_where_one_curve_has_a_gap(self):
        calc = _porosity_calc(PHID=[0.20, 0.20], PHIN=[np.nan, 0.30])
        phit = calc.calculate_phit_neutron_density()
        assert phit.iloc[0] == 0.20 and phit.iloc[1] == pytest.approx(0.25)

    def test_clipped_to_045(self):
        calc = _porosity_calc(PHID=[0.5], PHIN=[0.5])
        assert calc.calculate_phit_neutron_density().iloc[0] == 0.45

    def test_unknown_combination_rejected(self):
        calc = _porosity_calc(PHID=[0.2], PHIN=[0.2])
        with pytest.raises(ValueError):
            calc.calculate_phit_neutron_density(dn_combination="Geometric")

    def test_phie_dn_follows_the_combination(self):
        calc = _porosity_calc(PHID=[0.30], PHIN=[0.10], VSH=[0.0])
        avg = calc.calculate_phie_density_neutron(nphi_matrix=0.0, dn_combination="Average")
        rms = calc.calculate_phie_density_neutron(nphi_matrix=0.0, dn_combination="RMS")
        assert avg.iloc[0] == pytest.approx(0.20)
        assert rms.iloc[0] == pytest.approx(np.sqrt((0.09 + 0.01) / 2))


class TestGasFlagAndPhieGas:
    def _gas_pair(self, nphi, vsh=0.0):
        data = pd.DataFrame({"RHOB": [2.155], "NPHI": [nphi]})
        calc = PetrophysicsCalculator(data)
        calc.calculate_porosity_density("RHOB", 2.65, 1.0)
        calc.calculate_porosity_neutron("NPHI", -0.02)
        calc.calculate_phit_neutron_density()
        calc.calculate_all_phie(
            vsh=pd.Series([vsh]), gas_correction=True, primary_method="PHIE_GAS",
            nphi_matrix=-0.02,
        )
        return calc

    def test_small_crossover_is_not_gas(self):
        # Crossover 0.002 in both: no flag, and 0.004 of NPHI moves PHIE by ~0.002, not 0.05.
        a, b = self._gas_pair(0.282), self._gas_pair(0.278)
        assert a.results["GAS_FLAG"].iloc[0] == 0 and b.results["GAS_FLAG"].iloc[0] == 0
        assert abs(a.results["PHIE"].iloc[0] - b.results["PHIE"].iloc[0]) < 0.005

    def test_real_gas_is_flagged_and_capped_at_phit(self):
        calc = _porosity_calc(PHID=[0.35], PHIN=[0.22], VSH=[0.0])
        flag = calc.calculate_gas_flag(calc.results["VSH"])
        assert bool(flag.iloc[0])
        calc.calculate_phit_neutron_density(gas_flag=flag)
        phie_gas = calc.calculate_phie_gas_corrected(
            vsh=calc.results["VSH"], nphi_matrix=0.0
        )
        assert calc.results["GAS_FLAG"].iloc[0] == 1
        phit = calc.results["PHIT"].iloc[0]
        assert phit == pytest.approx(0.2923, abs=1e-4)
        assert phie_gas.iloc[0] <= 0.2925        # the spec's "<= 0.292", to rounding
        assert phie_gas.iloc[0] <= phit

    def test_phie_gas_never_exceeds_phit_per_sample(self):
        calc = _porosity_calc(PHID=[0.35, -0.05, 0.30], PHIN=[0.22, 0.00, 0.31], VSH=[0.0] * 3)
        flag = calc.calculate_gas_flag(calc.results["VSH"])
        calc.calculate_phit_neutron_density(gas_flag=flag)
        phie_gas = calc.calculate_phie_gas_corrected(vsh=calc.results["VSH"], nphi_matrix=0.0)
        assert (phie_gas <= calc.results["PHIT"] + 1e-12).all()

    def test_vsh_gate_and_threshold_parameters(self):
        calc = _porosity_calc(PHID=[0.35, 0.35, 0.35], PHIN=[0.22, 0.22, 0.34], VSH=[0.0, 0.5, 0.0])
        flag = calc.calculate_gas_flag(calc.results["VSH"], 0.02, 0.40)
        assert flag.tolist() == [True, False, False]
        strict = calc.calculate_gas_flag(calc.results["VSH"], 0.20, 0.60)
        assert strict.tolist() == [False, False, False]
        lax = calc.calculate_gas_flag(calc.results["VSH"], 0.10, 0.60)
        assert lax.tolist() == [True, True, False]

    def test_nan_inputs_are_not_flagged(self):
        calc = _porosity_calc(PHID=[np.nan, 0.35], PHIN=[0.2, 0.22], VSH=[0.0, np.nan])
        assert calc.calculate_gas_flag(calc.results["VSH"]).tolist() == [False, False]

    def test_gas_flag_dropped_when_correction_is_off(self):
        calc = _porosity_calc(PHID=[0.35], PHIN=[0.22], VSH=[0.0])
        calc.calculate_all_phie(vsh=calc.results["VSH"], gas_correction=True, nphi_matrix=0.0)
        assert "GAS_FLAG" in calc.results.columns
        calc.calculate_all_phie(vsh=calc.results["VSH"], gas_correction=False, nphi_matrix=0.0)
        assert "GAS_FLAG" not in calc.results.columns


class TestNeutronShaleCorrection:
    def test_pure_shale_gives_zero(self):
        data = pd.DataFrame({"NPHI": [0.35]})
        calc = PetrophysicsCalculator(data)
        calc.calculate_porosity_neutron("NPHI", -0.02)         # sandstone
        phie_n = calc.calculate_phie_neutron(pd.Series([1.0]), nphi_shale=0.35, nphi_matrix=-0.02)
        assert phie_n.iloc[0] == pytest.approx(0.0, abs=1e-12)

    def test_matrix_defaults_to_the_one_used_for_phin(self):
        data = pd.DataFrame({"NPHI": [0.35]})
        calc = PetrophysicsCalculator(data)
        calc.calculate_porosity_neutron("NPHI", 0.02)          # dolomite-like scale
        assert calc.calculate_phie_neutron(pd.Series([1.0]), 0.35).iloc[0] == pytest.approx(0.0, abs=1e-12)

    def test_clean_rock_unchanged(self):
        data = pd.DataFrame({"NPHI": [0.20]})
        calc = PetrophysicsCalculator(data)
        calc.calculate_porosity_neutron("NPHI", -0.02)
        assert calc.calculate_phie_neutron(pd.Series([0.0]), 0.35).iloc[0] == pytest.approx(0.22)


class TestPipelinePorosityPaths:
    def _run(self, data, mapping, **params):
        from modules.pipeline import run_pipeline
        return run_pipeline(data, mapping, params)

    def test_gas_flag_exists_with_phie_dn_primary(self, gas_zone_data):
        mapping = {"GR": "GR", "RHOB": "RHOB", "NPHI": "NPHI", "DT": "DT", "RT": "RT"}
        results, _ = self._run(gas_zone_data, mapping, gas_correction_enabled=True,
                               primary_phie_method="PHIE_DN")
        assert "GAS_FLAG" in results.columns and results["GAS_FLAG"].sum() > 0
        gas = results["GAS_FLAG"] == 1
        d, n = results["PHID"], results["PHIN"]
        rms = np.sqrt((d**2 + n**2) / 2).clip(0, 0.45)
        np.testing.assert_allclose(results.loc[gas, "PHIT"], rms[gas])

    def test_no_gas_flag_when_correction_is_off(self, gas_zone_data):
        mapping = {"GR": "GR", "RHOB": "RHOB", "NPHI": "NPHI", "DT": "DT", "RT": "RT"}
        results, _ = self._run(gas_zone_data, mapping)
        assert "GAS_FLAG" not in results.columns

    def test_dn_combination_selects_phit(self, sample_log_data):
        mapping = {"GR": "GR", "RHOB": "RHOB", "NPHI": "NPHI", "DT": "DT", "RT": "RT"}
        avg, _ = self._run(sample_log_data, mapping, dn_combination="Average")
        rms, _ = self._run(sample_log_data, mapping, dn_combination="RMS")
        d, n = avg["PHID"], avg["PHIN"]
        np.testing.assert_allclose(avg["PHIT"], ((d + n) / 2).clip(0, 0.45))
        np.testing.assert_allclose(rms["PHIT"], np.sqrt((d**2 + n**2) / 2).clip(0, 0.45))

    def test_sonic_only_run_has_phit(self, sample_log_data):
        mapping = {"GR": "GR", "RHOB": "None", "NPHI": "None", "DT": "DT", "RT": "RT"}
        results, _ = self._run(sample_log_data, mapping)
        np.testing.assert_allclose(results["PHIT"], results["PHIS"])


# ---------------------------------------------------------------------------
# C7 Hierarchical Swirr: floor last, counts reach the summary
# C15 The selected Swirr method feeds SWIRR and permeability
# ---------------------------------------------------------------------------
from modules.pipeline import PARAM_DEFAULTS, run_pipeline

_FULL_MAPPING = {"GR": "GR", "RHOB": "RHOB", "NPHI": "NPHI", "DT": "DT", "RT": "RT"}


class TestHierarchicalSwirrOrder:
    def _calc(self, n):
        return PetrophysicsCalculator(pd.DataFrame({"RT": np.ones(n)}))

    def test_floor_is_applied_last(self):
        calc = self._calc(4)
        phie = pd.Series([0.25] * 4)
        sw = pd.Series([0.02, 0.04, 0.30, 0.90])      # first two below the 0.05 floor
        swirr, info = calc.calculate_swirr_hierarchical(
            phie=phie, sw=sw, vsh=pd.Series([0.5] * 4), k_buckles=0.02)
        assert (swirr >= 0.05).all()
        assert swirr.tolist() == pytest.approx([0.05, 0.05, 0.08, 0.08])
        assert info["raised_to_floor"] == 2

    def test_counts_are_taken_before_clipping(self):
        calc = self._calc(5)
        phie = pd.Series([0.25, 0.25, 0.25, 0.02, 0.02])   # Buckles 0.08, 0.08, 0.08, 1.0, 1.0
        sw = pd.Series([0.9, 0.9, 0.06, 1.0, 1.0])
        swirr, info = calc.calculate_swirr_hierarchical(
            phie=phie, sw=sw, vsh=pd.Series([0.5] * 5), k_buckles=0.02)
        assert info["limited_by_sw"] == 1      # 0.08 > 0.06
        assert info["limited_to_max"] == 2     # 1.0 -> 0.60
        assert info["raised_to_floor"] == 0
        assert swirr.tolist() == pytest.approx([0.08, 0.08, 0.06, 0.60, 0.60])

    def test_nan_sw_gives_nan_swirr_and_is_not_counted(self):
        calc = self._calc(2)
        swirr, info = calc.calculate_swirr_hierarchical(
            phie=pd.Series([0.25, 0.25]), sw=pd.Series([np.nan, 0.5]),
            vsh=pd.Series([0.5, 0.5]), k_buckles=0.02)
        assert np.isnan(swirr[0]) and info["samples"] == 1

    def _hydrocarbon_well(self, rt):
        n = 30
        return pd.DataFrame({
            "DEPTH": np.linspace(1000, 1029, n), "GR": np.full(n, 25.0),
            "RHOB": np.full(n, 2.35), "NPHI": np.full(n, 0.20), "DT": np.full(n, 90.0),
            "RT": np.full(n, rt),
        })

    def test_counts_reach_the_summary_warnings(self):
        params = {**PARAM_DEFAULTS, "vsh_baseline_method": "Custom (Manual)"}
        results, summary = run_pipeline(self._hydrocarbon_well(2000.0), _FULL_MAPPING, params)
        assert (results["SW"] < 0.05).all()
        assert (results["SWIRR"] >= 0.05).all()
        assert ("Hierarchical Swirr: 30 samples were raised to the 0.05 floor "
                "(Swirr is never below 0.05, even where the measured Sw is).") in summary["warnings"]

    def test_limit_to_maximum_reaches_the_summary_warnings(self):
        data = self._hydrocarbon_well(1.0)
        data["RHOB"] = 2.64      # tight: Buckles Swirr above 0.60
        data["NPHI"] = -0.01
        params = {**PARAM_DEFAULTS, "vsh_baseline_method": "Custom (Manual)"}
        results, summary = run_pipeline(data, _FULL_MAPPING, params)
        assert (results["SWIRR"] <= 0.60).all()
        assert any(w.startswith("Hierarchical Swirr:") and "limited to the 0.60 maximum" in w
                   for w in summary["warnings"])


class TestSelectedSwirrMethod:
    def _data(self):
        n = 40
        rng = np.random.default_rng(3)
        return pd.DataFrame({
            "DEPTH": np.linspace(1000, 1039, n), "GR": rng.uniform(20, 45, n),
            "RHOB": rng.uniform(2.28, 2.42, n), "NPHI": rng.uniform(0.18, 0.26, n),
            "DT": np.full(n, 90.0), "RT": rng.uniform(40, 120, n),
        })

    def _run(self, method, data=None):
        params = {**PARAM_DEFAULTS, "vsh_baseline_method": "Custom (Manual)", "swirr_method": method}
        return run_pipeline(self._data() if data is None else data, _FULL_MAPPING, params)

    def test_clean_zone_value_feeds_swirr_and_permeability(self):
        results, summary = self._run("Clean Zone")
        value = results["SWIRR_CLEANZONE"].iloc[0]
        assert results["SWIRR_CLEANZONE"].nunique() == 1
        np.testing.assert_allclose(results["SWIRR"], value)
        assert (results["SWIRR_METHOD"] == "clean_zone").all()
        phie = results["PHIE"].clip(lower=0.001)
        p = PARAM_DEFAULTS
        expected = (p["perm_C"] * phie ** p["perm_P"] / max(value, 0.05) ** p["perm_Q"]).clip(0.001, 50000)
        np.testing.assert_allclose(results["PERM_WR"], expected, rtol=1e-12)
        assert summary["swirr_method"] == "Clean Zone"

    def test_a_clean_zone_value_of_0_0993_is_used_for_permeability(self, monkeypatch):
        def fixed(self, sw=None, vsh=None, vsh_threshold=0.2, sw_threshold=0.5):
            series = pd.Series(0.0993, index=self.data.index)
            self.results["SWIRR_CLEANZONE"] = series
            return series
        monkeypatch.setattr(PetrophysicsCalculator, "calculate_swirr_clean_zone", fixed)
        results, _ = self._run("Clean Zone")
        np.testing.assert_allclose(results["SWIRR"], 0.0993)
        phie = results["PHIE"].clip(lower=0.001)
        p = PARAM_DEFAULTS
        expected = (p["perm_C"] * phie ** p["perm_P"] / 0.0993 ** p["perm_Q"]).clip(0.001, 50000)
        np.testing.assert_allclose(results["PERM_WR"], expected, rtol=1e-12)
        # The old constant 0.2 gave a K (0.0993 / 0.2)^2 = 4.06 times lower (Q = 2).
        old = (p["perm_C"] * phie ** p["perm_P"] / 0.2 ** p["perm_Q"]).clip(0.001, 50000)
        assert (expected > 3 * old).all()

    def test_statistical_value_feeds_swirr(self):
        results, summary = self._run("Statistical")
        np.testing.assert_allclose(results["SWIRR"], results["SWIRR_STAT"])
        assert (results["SWIRR_METHOD"] == "statistical").all()
        assert summary["swirr_method"] == "Statistical"

    def test_buckles_number_feeds_swirr(self):
        results, _ = self._run("Buckles Number")
        np.testing.assert_allclose(results["SWIRR"], results["SWIRR_BUCKLES"])

    def test_all_methods_keeps_buckles(self):
        results, summary = self._run("All Methods")
        np.testing.assert_allclose(results["SWIRR"], results["SWIRR_BUCKLES"])
        assert {"SWIRR_BUCKLES", "SWIRR_CLEANZONE", "SWIRR_STAT"} <= set(results.columns)
        assert summary["swirr_method"] == "All methods (Buckles used)"

    def test_missing_value_falls_back_to_buckles_with_a_warning(self, monkeypatch):
        def partial(self, sw=None, vsh=None, vsh_threshold=0.2, sw_threshold=0.5):
            series = pd.Series(0.12, index=self.data.index)
            series.iloc[:5] = np.nan
            self.results["SWIRR_CLEANZONE"] = series
            return series
        monkeypatch.setattr(PetrophysicsCalculator, "calculate_swirr_clean_zone", partial)
        results, summary = self._run("Clean Zone")
        buckles = (PARAM_DEFAULTS["k_buckles"] / results["PHIE"].clip(lower=0.01)).clip(0.05, 0.5)
        np.testing.assert_allclose(results["SWIRR"].iloc[:5], buckles.iloc[:5])
        np.testing.assert_allclose(results["SWIRR"].iloc[5:], 0.12)
        assert results["SWIRR_METHOD"].iloc[:5].eq("buckles").all()
        assert "SWIRR_BUCKLES" not in results.columns     # computed for the fallback only
        assert ("Swirr method Clean Zone: no value for 5 samples; "
                "Buckles Swirr was used for them.") in summary["warnings"]
        assert summary["swirr_method"] == "Clean Zone (Buckles used for 5 samples)"

    def test_no_constant_fallback_without_rt(self):
        data = self._data().drop(columns="RT")
        mapping = {**_FULL_MAPPING, "RT": "None"}
        params = {**PARAM_DEFAULTS, "vsh_baseline_method": "Custom (Manual)",
                  "swirr_method": "Buckles Number"}
        results, _ = run_pipeline(data, mapping, params)
        assert not (results["SWIRR"] == 0.2).all()
