
import pytest
import pandas as pd
import numpy as np
from modules.petrophysics import PetrophysicsCalculator

class TestWaterSaturationAdvancedModels:
    
    def test_waxman_smits_calculation(self):
        # Setup synthetic data
        data = pd.DataFrame({
            'DEPTH': [1000, 1001],
            'RT': [10.0, 1.0],   # High res (oil), Low res (water)
            'PHIE': [0.2, 0.2]
        })
        
        calc = PetrophysicsCalculator(data)
        
        # Calculate WS
        sw_ws = calc.calculate_sw_waxman_smits(
            rt_curve='RT',
            phit=data['PHIE'],
            rw=0.05,
            a=1.0, m=2.0, n=2.0,
            qv=0.2, B=1.0
        )
        
        assert 'SW_WS' in calc.results.columns
        assert len(sw_ws) == 2
        
        # Basic sanity checks
        # 1. Sw should be valid
        assert not np.isnan(sw_ws[0])
        assert not np.isnan(sw_ws[1])
        
        # 2. Constraints
        assert np.all(sw_ws >= 0) & np.all(sw_ws <= 1)
        
        # 3. Trend: Lower resistivity -> Higher Sw
        assert sw_ws[1] > sw_ws[0]

    def test_dual_water_calculation(self):
        # Setup synthetic data
        data = pd.DataFrame({
            'DEPTH': [1000, 1001],
            'RT': [20.0, 0.5],
            'PHIT': [0.25, 0.25] # DW typically uses PHIT
        })
        
        calc = PetrophysicsCalculator(data)
        
        # Calculate DW
        sw_dw = calc.calculate_sw_dual_water(
            rt_curve='RT',
            phit=data['PHIT'],
            rw=0.04,
            a=1.0, m=2.0, n=2.0,
            swb=0.1, rwb=0.2
        )
        
        assert 'SW_DW' in calc.results.columns
        
        # 1. Sw should be valid
        assert not np.isnan(sw_dw[0])
        assert not np.isnan(sw_dw[1])
        
        # 2. Constraints
        assert np.all(sw_dw >= 0) & np.all(sw_dw <= 1)
        
        # 3. Logic: DW should result in valid saturation >= Swb (approx)
        # However, due to noise, we just check bounded 0-1.
        
        # 4. Trend
        assert sw_dw[1] > sw_dw[0]


def test_pipeline_runs_waxman_smits_with_qv_zero():
    """Qv 0 (the spin box minimum) used to abort the run; it is a clean sand, i.e. Archie."""
    from modules.pipeline import PARAM_DEFAULTS, run_pipeline

    n = 40
    df = pd.DataFrame({
        "DEPTH": 1000.0 + 0.5 * np.arange(n),
        "GR": np.linspace(30.0, 60.0, n),
        "RHOB": np.full(n, 2.35),
        "NPHI": np.full(n, 0.20),
        "RT": np.linspace(5.0, 50.0, n),
    })
    mapping = {"GR": "GR", "RHOB": "RHOB", "NPHI": "NPHI", "DT": "None", "RT": "RT"}
    params = {**PARAM_DEFAULTS, "sw_methods": ["Archie", "Waxman-Smits"],
              "sw_primary_method": "Waxman-Smits", "ws_qv": 0.0}
    results, _ = run_pipeline(df, mapping, params)
    assert results["SW_WS"].notna().all()
    assert ((results["SW_WS"] >= 0) & (results["SW_WS"] <= 1)).all()


if __name__ == "__main__":
    pytest.main([__file__])


# ---------------------------------------------------------------------------
# P0 v1.7.2 saturation group: C2, C3, C6, C14
# ---------------------------------------------------------------------------
from modules.formation_tops import FormationTops
from modules.petrophysics import effective_sw
from modules.pipeline import PARAM_DEFAULTS, run_pipeline

_MAPPING = {"GR": "GR", "RHOB": "RHOB", "NPHI": "NPHI", "DT": "None", "RT": "RT"}
# Defaults of spec section 2.1: Rw 0.05, a 0.62, m 2.15, n 2, Qv 0.2, B 1, Swb 0.1, Rwb 0.2.
_ARCHIE = dict(rw=0.05, a=0.62, m=2.15, n=2.0)


def _single(rt=20.0):
    return PetrophysicsCalculator(pd.DataFrame({"RT": [rt]}))


class TestTotalPorosityModels:
    """C2: Waxman-Smits and Dual-Water are solved on PHIT."""

    def test_dual_water_on_phit_matches_the_spec_repro(self):
        phit, phie = pd.Series([0.25]), pd.Series([0.225])
        on_phit = _single()
        on_phit.calculate_sw_dual_water("RT", phit, **_ARCHIE, swb=0.1, rwb=0.2, phie=phie)
        on_phie = _single().calculate_sw_dual_water("RT", phie, **_ARCHIE, swb=0.1, rwb=0.2)
        assert on_phit.results["SWT_DW"][0] == pytest.approx(0.2162, abs=5e-5)
        assert on_phie[0] == pytest.approx(0.2368, abs=5e-5)

    def test_waxman_smits_on_phit_matches_the_spec_repro(self):
        phit, phie = pd.Series([0.25]), pd.Series([0.225])
        on_phit = _single()
        on_phit.calculate_sw_waxman_smits("RT", phit, **_ARCHIE, qv=0.2, B=1.0, phie=phie)
        on_phie = _single().calculate_sw_waxman_smits("RT", phie, **_ARCHIE, qv=0.2, B=1.0)
        assert on_phit.results["SWT_WS"][0] == pytest.approx(0.1698, abs=5e-5)
        assert on_phie[0] == pytest.approx(0.1908, abs=5e-5)

    def test_missing_total_porosity_gives_nan_and_is_counted(self):
        calc = PetrophysicsCalculator(pd.DataFrame({"RT": [20.0, 20.0]}))
        phit, phie = pd.Series([np.nan, 0.25]), pd.Series([0.2, 0.2])
        for name, call in (("SW_WS", calc.calculate_sw_waxman_smits),
                           ("SW_DW", calc.calculate_sw_dual_water)):
            sw = call("RT", phit, phie=phie)
            assert np.isnan(sw[0]) and np.isfinite(sw[1])
            assert calc.sw_flags[name]["no_phit"].tolist() == [True, False]

    def test_pipeline_passes_phit_to_the_total_porosity_models(self, dual_water_data):
        params = {**PARAM_DEFAULTS, "sw_methods": ["Waxman-Smits", "Dual-Water"],
                  "sw_primary_method": "Dual-Water"}
        results, _ = run_pipeline(dual_water_data, _MAPPING, params)
        assert not np.allclose(results["PHIT"], results["PHIE"])
        for column, call in (("DW", PetrophysicsCalculator.calculate_sw_dual_water),
                             ("WS", PetrophysicsCalculator.calculate_sw_waxman_smits)):
            ref = PetrophysicsCalculator(dual_water_data)
            call(ref, "RT", results["PHIT"], 0.05, 0.62, 2.15, 2.0)
            np.testing.assert_allclose(results[f"SWT_{column}"], ref.results[f"SWT_{column}"],
                                       rtol=1e-12, equal_nan=True)


class TestEffectiveSw:
    """C3: SW is effective Sw by hydrocarbon-volume conservation."""

    @pytest.mark.parametrize("phit, phie, swt, swe, bvh", [
        (0.25, 0.225, 0.2162, 0.1291, 0.1959),     # exact: BVH = PHIT * (1 - Swt)
        (0.25, 0.10, 0.20, 0.0, 0.10),             # BVH limited to PHIE
        (0.25, 0.30, 0.20, 1 / 3, 0.20),           # PHIE above PHIT: exact, Swe > Swt
        (0.25, 0.0005, 0.20, 1.0, 0.0),            # no effective pore space
    ])
    def test_validity_table(self, phit, phie, swt, swe, bvh):
        got = effective_sw(swt, phit, phie)
        assert float(got) == pytest.approx(swe, abs=1e-4)
        assert phie * (1 - float(got)) == pytest.approx(bvh, abs=1e-4)

    def test_hydrocarbon_volume_is_conserved_exactly_in_range(self):
        rng = np.random.default_rng(1)
        phit = rng.uniform(0.1, 0.3, 200)
        swt = rng.uniform(0.1, 1.0, 200)
        phie = phit * rng.uniform(0.6, 1.0, 200)
        ok = phit * (1 - swt) <= phie
        swe = effective_sw(swt, phit, phie)
        np.testing.assert_allclose((phie * (1 - swe))[ok], (phit * (1 - swt))[ok], rtol=1e-12)
        assert ((swe >= 0) & (swe <= 1)).all()

    def test_dual_water_reduces_to_the_textbook_form(self):
        phit = np.array([0.2, 0.25, 0.3])
        swt = np.array([0.3, 0.5, 0.8])
        phie = phit * (1 - 0.1)
        np.testing.assert_allclose(effective_sw(swt, phit, phie), (swt - 0.1) / 0.9, rtol=1e-12)

    def test_nan_in_any_input_gives_nan(self):
        got = effective_sw(np.array([np.nan, 0.2, 0.2]), np.array([0.2, np.nan, 0.2]),
                           np.array([0.2, 0.2, np.nan]))
        assert np.isnan(got).all()

    def test_solvers_return_effective_sw_and_keep_swt(self):
        calc = _single()
        phit, phie = pd.Series([0.25]), pd.Series([0.225])
        sw = calc.calculate_sw_dual_water("RT", phit, **_ARCHIE, swb=0.1, rwb=0.2, phie=phie)
        assert calc.results["SW_DW"][0] == sw[0] == pytest.approx(0.1291, abs=5e-5)
        assert calc.results["SWT_DW"][0] == pytest.approx(0.2162, abs=5e-5)
        assert 0.225 * (1 - sw[0]) == pytest.approx(0.1959, abs=5e-5)

    def test_pipeline_sw_is_effective_for_the_primary_total_porosity_model(self, dual_water_data):
        params = {**PARAM_DEFAULTS, "sw_methods": ["Dual-Water"], "sw_primary_method": "Dual-Water"}
        results, _ = run_pipeline(dual_water_data, _MAPPING, params)
        pd.testing.assert_series_equal(results["SW"], results["SW_DW"], check_names=False)
        np.testing.assert_allclose(
            results["SW_DW"], effective_sw(results["SWT_DW"], results["PHIT"], results["PHIE"]),
            rtol=1e-12)
        exact = results["PHIT"] * (1 - results["SWT_DW"]) <= results["PHIE"]
        assert exact.any() and (~exact).any()
        np.testing.assert_allclose(
            (results["PHIE"] * (1 - results["SW"]))[exact],
            (results["PHIT"] * (1 - results["SWT_DW"]))[exact], rtol=1e-12)
        # Never more hydrocarbon than PHIE allows where the model's volume does not fit.
        assert (results["PHIE"] * (1 - results["SW"]))[~exact].le(results["PHIE"][~exact] + 1e-12).all()

    def test_porosity_inconsistency_is_counted_per_zone_and_warned(self, dual_water_data):
        tops = FormationTops()
        import io
        assert tops.read_tops_from_buffer(io.StringIO(
            "Formation\tTop (ft)\tBottom (ft)\nA\t2000\t2030\nB\t2030\t2061\n"))
        params = {**PARAM_DEFAULTS, "sw_methods": ["Dual-Water"], "sw_primary_method": "Dual-Water"}
        results, summary = run_pipeline(dual_water_data, _MAPPING, params, formation_tops=tops)
        diag = summary["solver_diagnostics"]["SW_DW"]
        assert {"no_root", "failed", "at_upper_bound", "at_lower_bound", "no_porosity",
                "bvh_exceeds_phie", "phie_above_phit"} <= set(diag)
        exceeds = (results["PHIT"] * (1 - results["SWT_DW"]) > results["PHIE"]).sum()
        assert diag["bvh_exceeds_phie"] == exceeds > 0
        assert sum(z["bvh_exceeds_phie"] for z in diag["zones"].values()) == exceeds
        assert sum(z["samples"] for z in diag["zones"].values()) == len(results)
        assert any(w.startswith("Dual-Water (zone ") and "effective porosity" in w
                   for w in summary["warnings"])

    def test_solver_diagnostics_keep_the_no_root_and_failed_keys(self, dual_water_data):
        params = {**PARAM_DEFAULTS, "sw_methods": ["Waxman-Smits"],
                  "sw_primary_method": "Waxman-Smits"}
        _, summary = run_pipeline(dual_water_data, _MAPPING, params)
        assert summary["solver_diagnostics"]["SW_WS"]["no_root"] == 0
        assert summary["solver_diagnostics"]["SW_WS"]["failed"] == 0
        assert "zones" not in summary["solver_diagnostics"]["SW_WS"]


class TestOneValidityRule:
    """C6: the same rule for all five models."""

    def _all(self, rt, phie, vsh=None, phit=None):
        data = pd.DataFrame({"RT": rt})
        calc = PetrophysicsCalculator(data)
        phie = pd.Series(phie, dtype=float)
        vsh = pd.Series([0.1] * len(data) if vsh is None else vsh, dtype=float)
        phit = phie if phit is None else pd.Series(phit, dtype=float)
        return {
            "archie": calc.calculate_sw_archie("RT", phie),
            "indo": calc.calculate_sw_indonesian("RT", phie, vsh),
            "siman": calc.calculate_sw_simandoux("RT", phie, vsh),
            "ws": calc.calculate_sw_waxman_smits("RT", phit, phie=phie),
            "dw": calc.calculate_sw_dual_water("RT", phit, phie=phie),
        }

    @pytest.mark.parametrize("phi", [0.0, 0.0005, 0.001])
    def test_no_pore_space_is_sw_one_for_every_model(self, phi):
        for name, sw in self._all([20.0], [phi]).items():
            assert sw[0] == 1.0, name

    def test_nan_rt_or_porosity_is_nan_for_every_model(self):
        for name, sw in self._all([np.nan, 20.0], [0.2, np.nan]).items():
            assert sw.isna().all(), name

    def test_no_porosity_is_counted(self):
        data = pd.DataFrame({"RT": [20.0, 20.0, 20.0]})
        calc = PetrophysicsCalculator(data)
        phie = pd.Series([0.0, 0.2, np.nan])
        calc.calculate_sw_archie("RT", phie)
        calc.calculate_sw_waxman_smits("RT", phie)
        assert calc.sw_flags["SW_ARCHIE"]["no_porosity"].tolist() == [True, False, False]
        assert calc.sw_flags["SW_WS"]["no_porosity"].tolist() == [True, False, False]

    def test_total_models_use_phit_for_the_rule(self):
        # PHIE fine, PHIT at zero: no pore space for the total-porosity solve.
        calc = PetrophysicsCalculator(pd.DataFrame({"RT": [20.0]}))
        sw = calc.calculate_sw_dual_water("RT", pd.Series([0.0]), phie=pd.Series([0.2]))
        assert sw[0] == 1.0 and calc.results["SWT_DW"][0] == 1.0

    def test_simandoux_clips_vsh_to_the_unit_interval(self):
        calc = PetrophysicsCalculator(pd.DataFrame({"RT": [10.0, 10.0, 10.0, 10.0]}))
        phie = pd.Series([0.2] * 4)
        sw = calc.calculate_sw_simandoux("RT", phie, pd.Series([1.5, 1.0, -0.3, 0.0]))
        assert sw[0] == pytest.approx(sw[1], rel=1e-12)
        assert sw[2] == pytest.approx(sw[3], rel=1e-12)
        archie = calc.calculate_sw_archie("RT", phie)
        assert sw[3] == pytest.approx(archie[3], rel=1e-9)

    def test_simandoux_general_n_clips_vsh_too(self):
        calc = PetrophysicsCalculator(pd.DataFrame({"RT": [10.0, 10.0]}))
        sw = calc.calculate_sw_simandoux("RT", pd.Series([0.2, 0.2]), pd.Series([1.5, 1.0]), n=2.3)
        assert sw[0] == pytest.approx(sw[1], rel=1e-12)


class TestBoundCounts:
    """C14: samples at a bound are counted, per model and zone."""

    def test_archie_counts_clipped_samples(self):
        calc = PetrophysicsCalculator(pd.DataFrame({"RT": [0.5, 100.0, 20.0]}))
        calc.calculate_sw_archie("RT", pd.Series([0.2, 0.2, 0.2]))
        flags = calc.sw_flags["SW_ARCHIE"]
        assert flags["at_upper_bound"].tolist() == [True, False, False]
        assert flags["at_lower_bound"].sum() == 0

    def test_water_leg_scatter_up_to_the_tolerance_is_not_counted(self):
        # Archie a=0.62 m=2.15 n=2 Rw=0.05 at PHIE 0.2: Sw = 1 at Rt ~ 0.99 ohm.m;
        # Rt 0.95 gives Sw ~ 1.02 (scatter, not counted), Rt 0.80 gives Sw ~ 1.11.
        calc =PetrophysicsCalculator(pd.DataFrame({"RT": [0.95, 0.80]}))
        sw = calc.calculate_sw_archie("RT", pd.Series([0.2, 0.2]))
        assert sw.tolist() == [1.0, 1.0]
        flags = calc.sw_flags["SW_ARCHIE"]
        assert flags["at_upper_bound"].tolist() == [False, True]

    def test_solver_fallbacks_are_counted_as_bounds(self):
        # Very low RT: conductivity above the model at Sw 1; very high RT: below it at the lower end.
        calc = PetrophysicsCalculator(pd.DataFrame({"RT": [1e-3, 1e9, 20.0]}))
        phit = pd.Series([0.2, 0.2, 0.2])
        calc.calculate_sw_waxman_smits("RT", phit, **_ARCHIE)
        calc.calculate_sw_dual_water("RT", phit, **_ARCHIE)
        for name in ("SW_WS", "SW_DW"):
            flags = calc.sw_flags[name]
            assert flags["at_upper_bound"].tolist() == [True, False, False], name
            assert flags["at_lower_bound"].tolist() == [False, True, False], name
            assert flags["no_root"].tolist() == [True, True, False], name
        assert calc.solver_diagnostics["SW_WS"]["no_root"] == 2

    def _clean_well(self, rt):
        n = 20
        return pd.DataFrame({
            "DEPTH": np.linspace(1000, 1019, n), "GR": np.full(n, 25.0),
            "RHOB": np.full(n, 2.35), "NPHI": np.full(n, 0.20), "RT": np.full(n, rt),
        })

    def test_warning_when_clean_samples_sit_at_the_upper_bound(self):
        params = {**PARAM_DEFAULTS, "sw_methods": ["Archie"], "sw_primary_method": "Archie",
                  "vsh_baseline_method": "Custom (Manual)"}
        _, summary = run_pipeline(self._clean_well(0.5), _MAPPING, params)
        assert summary["solver_diagnostics"]["SW_ARCHIE"]["at_upper_bound"] == 20
        assert "Archie: Sw > 1.05 before clipping in 20 clean samples: check Rw, m, n or Rt." \
            in summary["warnings"]

    def test_no_warning_below_ten_clean_samples(self):
        params = {**PARAM_DEFAULTS, "sw_methods": ["Archie"], "sw_primary_method": "Archie",
                  "vsh_baseline_method": "Custom (Manual)"}
        data = self._clean_well(0.5)
        data.loc[9:, "GR"] = 110.0   # 9 clean samples, all above the bound
        _, summary = run_pipeline(data, _MAPPING, params)
        assert summary["solver_diagnostics"]["SW_ARCHIE"]["at_upper_bound"] >= 9
        assert not any("before clipping" in w for w in summary["warnings"])

    def test_no_warning_for_a_hydrocarbon_well(self):
        params = {**PARAM_DEFAULTS, "sw_methods": ["Archie"], "sw_primary_method": "Archie",
                  "vsh_baseline_method": "Custom (Manual)"}
        _, summary = run_pipeline(self._clean_well(200.0), _MAPPING, params)
        assert summary["solver_diagnostics"]["SW_ARCHIE"]["at_upper_bound"] == 0
        assert not any("before clipping" in w for w in summary["warnings"])

    def test_shaly_samples_do_not_trigger_the_clean_sample_warning(self):
        data = self._clean_well(0.5)
        data["GR"] = 110.0   # Vsh near 1: above the Vsh cutoff
        params = {**PARAM_DEFAULTS, "sw_methods": ["Archie"], "sw_primary_method": "Archie",
                  "vsh_baseline_method": "Custom (Manual)"}
        _, summary = run_pipeline(data, _MAPPING, params)
        assert not any("before clipping" in w for w in summary["warnings"])
