"""Pure tests for modules.uncertainty sampling and statistics (no Qt)."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

from modules import uncertainty as U

ROOT = Path(__file__).resolve().parent.parent


def make_cfg(names=("a", "m", "rw"), kind="triangular", n=200, sampling="lhs", seed=7):
    cfg = U.UncertaintyConfig(n=n, seed=seed, sampling=sampling)
    for nm in names:
        lo, mid, hi = U.SUGGESTED_RANGES[nm]
        cfg.distributions[nm] = U.Distribution(
            name=nm, enabled=True, kind=kind, mode=U.DEFAULT_MODES[nm],
            low=lo, mid=mid, high=hi, sd=(hi - lo) / 6)
    return cfg


def test_validate_ok_and_errors():
    assert U.validate_config(make_cfg()) == []
    assert U.validate_config(U.UncertaintyConfig())
    assert U.validate_config(make_cfg(n=10))
    assert U.validate_config(make_cfg(n=10**6))
    cfg = make_cfg(); cfg.sampling = "sobol"
    assert U.validate_config(cfg)
    cfg = make_cfg(); cfg.distributions["a"].kind = "weibull"
    assert U.validate_config(cfg)
    cfg = make_cfg(); cfg.distributions["a"].mode = "x"
    assert U.validate_config(cfg)
    cfg = make_cfg(); cfg.distributions["a"].mid = 5.0
    assert U.validate_config(cfg)
    cfg = make_cfg(kind="uniform"); cfg.distributions["a"].low = 1.0
    assert U.validate_config(cfg)
    cfg = make_cfg(kind="normal"); cfg.distributions["a"].sd = -1
    assert U.validate_config(cfg)
    cfg = make_cfg(); cfg.correlations[("a", "n")] = 0.3   # n not enabled: ignored, not an error
    assert not U.validate_config(cfg)
    cfg = make_cfg(); cfg.correlations[("a", "m")] = 1.0
    assert U.validate_config(cfg)


def test_non_pd_refused():
    cfg = make_cfg()
    cfg.correlations = {("a", "m"): 0.9, ("m", "rw"): 0.9, ("a", "rw"): -0.9}
    assert any("positive definite" in e for e in U.validate_config(cfg))
    with pytest.raises(ValueError, match="positive definite"):
        U.sample_parameters(cfg)


def test_correlation_with_disabled_parameter_is_ignored():
    ref = U.sample_parameters(make_cfg(names=("a", "m", "rw")))
    cfg = make_cfg(names=("a", "m", "rw"))
    cfg.correlations = {("m", "n"): 0.7, ("a", "n"): -0.4}
    assert U.validate_config(cfg) == []
    got = U.sample_parameters(cfg)
    np.testing.assert_array_equal(got.offsets, ref.offsets)      # identical draws, no copula
    # An enabled pair next to a dropped one still correlates.
    cfg.correlations[("a", "m")] = 0.6
    off = U.sample_parameters(cfg).offsets
    assert abs(stats.spearmanr(off[:, 0], off[:, 1])[0] - 0.6) < 0.1
    # A non-positive-definite matrix among enabled parameters is still refused.
    cfg.correlations = {("a", "m"): 0.9, ("m", "rw"): 0.9, ("a", "rw"): -0.9, ("m", "n"): 0.2}
    assert any("positive definite" in e for e in U.validate_config(cfg))


def test_rw_quality_text():
    from types import SimpleNamespace as NS
    assert U.rw_quality_text(NS()) == ""
    assert U.rw_quality_text(NS(rw_quality={"w1": [], "w2": []})) == ""
    assert U.rw_quality_text(NS(rw_quality={"w1": ["water_leg"]})) == "Auto Rw: from water leg"
    assert U.rw_quality_text(NS(rw_quality={"w1": ["uniform"], "w2": ["water_leg"]})) ==         "Auto Rw: from water leg, uniform estimate"


def test_seed_reproducible_and_different():
    cfg = make_cfg()
    a = U.sample_parameters(cfg, seed=1).offsets
    b = U.sample_parameters(cfg, seed=1).offsets
    c = U.sample_parameters(cfg, seed=2).offsets
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)
    assert a.shape == (200, 3)
    assert U.sample_parameters(cfg, seed=1).names == ("a", "m", "rw")


@pytest.mark.parametrize("sampling", ["lhs", "random"])
def test_random_and_lhs_shapes(sampling):
    d = U.sample_parameters(make_cfg(sampling=sampling), n=64)
    assert d.offsets.shape == (64, 3) and d.uniforms.shape == (64, 3)


def test_lhs_stratification():
    n = 100
    d = U.sample_parameters(make_cfg(n=n), n=n)
    for j in range(d.uniforms.shape[1]):
        strata = np.floor(d.uniforms[:, j] * n).astype(int)
        assert sorted(strata) == list(range(n))


def test_triangular_and_truncnorm_quantiles():
    t = U.Distribution("a", True, "triangular", "relative", -0.1, 0.0, 0.3)
    assert U.marginal_quantile(t, 0.0) == pytest.approx(-0.1)
    assert U.marginal_quantile(t, 1.0) == pytest.approx(0.3)
    c = 0.1 / 0.4
    assert U.marginal_quantile(t, c) == pytest.approx(0.0, abs=1e-9)
    assert U.marginal_quantile(t, 0.5) == pytest.approx(stats.triang.ppf(0.5, c, -0.1, 0.4))
    nrm = U.Distribution("m", True, "normal", "additive", 0, 0.2, 0, 0.1)
    assert U.marginal_quantile(nrm, 0.5) == pytest.approx(0.2)
    assert U.marginal_quantile(nrm, 1e-15) >= 0.2 - 0.3 - 1e-9
    assert U.marginal_quantile(nrm, 0.9) == pytest.approx(
        stats.truncnorm.ppf(0.9, -3, 3, loc=0.2, scale=0.1))
    uni = U.Distribution("n", True, "uniform", "additive", 1.0, 0, 3.0)
    assert U.marginal_quantile(uni, 0.25) == pytest.approx(1.5)


def test_zero_width_constant():
    cfg = make_cfg(names=("a",))
    cfg.distributions["a"].low = cfg.distributions["a"].mid = cfg.distributions["a"].high = 0.05
    assert np.all(U.sample_parameters(cfg).offsets == 0.05)
    cfg = make_cfg(names=("a",), kind="normal")
    cfg.distributions["a"].sd = 0.0
    cfg.distributions["a"].mid = -0.02
    assert np.all(U.sample_parameters(cfg).offsets == -0.02)


def test_sampled_offsets_within_support():
    d = U.sample_parameters(make_cfg(), n=500)
    lo, _, hi = U.SUGGESTED_RANGES["a"]
    assert d.offsets[:, 0].min() >= lo and d.offsets[:, 0].max() <= hi


def test_apply_offset_modes_and_clipping():
    v, c = U.apply_offset("a", 1.0, 0.1, "relative")
    assert v == pytest.approx(1.1) and c is False
    v, c = U.apply_offset("m", 2.0, np.array([-0.5, 0.1, 5.0]), "additive")
    assert np.allclose(v, [1.5, 2.1, 4.0])
    assert list(c) == [False, False, True]
    v, c = U.apply_offset("m", 1.1, np.array([-0.5]), "additive")
    assert v[0] == 1.0 and c[0]
    # open low end: a cutoff of 0 is not allowed, nearest value inside
    v, c = U.apply_offset("vsh_cutoff", 0.1, np.array([-0.5, 0.0]), "additive")
    assert v[0] == np.nextafter(0, 1) and v[0] > 0 and c[0] and not c[1]
    v, c = U.apply_offset("sw_cutoff", 0.9, np.array([0.5]), "additive")
    assert v[0] == 1.0 and c[0]
    assert int(c.sum()) == 1


def test_correlation_spearman_near_requested():
    cfg = make_cfg(names=("a", "m"), n=2000)
    cfg.correlations = {("a", "m"): 0.6}
    assert U.validate_config(cfg) == []
    off = U.sample_parameters(cfg).offsets
    rho = stats.spearmanr(off[:, 0], off[:, 1])[0]
    assert abs(rho - 0.6) < 0.05


def test_exceedance_stats_order_and_hand_value():
    rng = np.random.default_rng(0)
    s = U.exceedance_stats(rng.lognormal(size=1000))
    assert s["p90"] <= s["p50"] <= s["p10"]
    s = U.exceedance_stats([1, 2, 3, 4, 5])
    assert s["p90"] == pytest.approx(1.4) and s["p50"] == 3 and s["p10"] == pytest.approx(4.6)
    assert s["mean"] == 3 and s["min"] == 1 and s["max"] == 5 and s["n"] == 5


def test_exceedance_nan_zero_and_all_nan():
    s = U.exceedance_stats([0, 0, 1, 2, np.nan, np.nan])
    assert s["n"] == 6 and s["n_valid"] == 4 and s["prob_zero"] == pytest.approx(0.5)
    s = U.exceedance_stats([5.0, 6.0, np.nan], zero_mask=[True, False, False, False])
    assert s["prob_zero"] == pytest.approx(0.25)
    s = U.exceedance_stats([np.nan, np.nan])
    assert s["n_valid"] == 0 and np.isnan(s["p50"]) and np.isnan(s["p90"])


def test_convergence_warning():
    x = np.concatenate([np.full(500, 1.0), np.full(500, 2.0)])
    assert U.convergence_warning(x) == "Percentiles not converged at N = 1000; increase N"
    x = np.random.default_rng(3).normal(100, 1, 200000)
    assert U.convergence_warning(x) is None


def test_tornado_sort_and_swing():
    rows = U.tornado_rows(10.0, {
        "a": (9.0, 11.0, 0.9, 1.1),
        "m": (12.0, 6.0, 1.8, 2.2),
        "n": (10.0, 10.5, 1.9, 2.1),
    })
    assert [r["name"] for r in rows] == ["m", "a", "n"]
    assert rows[0]["swing"] == 6.0 and rows[0]["bar_min"] == 6.0 and rows[0]["bar_max"] == 12.0
    assert rows[0]["at_low_input"] == 12.0 and rows[0]["low_input"] == 1.8


def test_rank_correlations_nan_safe():
    rng = np.random.default_rng(1)
    off = rng.random((300, 2))
    y = off[:, 0] * 2 + 0.01 * rng.random(300)
    y[::17] = np.nan
    r = U.rank_correlations(off, ("a", "m"), y)
    assert r["a"] > 0.95 and abs(r["m"]) < 0.3
    assert np.isnan(U.rank_correlations(off, ("a", "m"), np.ones(300))["a"])


def test_config_roundtrip_and_partial():
    cfg = make_cfg()
    cfg.correlations = {("a", "m"): 0.4}
    cfg.seed = 99
    d = json.loads(json.dumps(U.config_to_dict(cfg)))
    back = U.config_from_dict(d)
    assert back.n == cfg.n and back.seed == 99 and back.sampling == cfg.sampling
    assert back.correlations == {("a", "m"): 0.4}
    assert back.enabled_names() == cfg.enabled_names()
    assert back.distributions["rw"] == cfg.distributions["rw"]
    part = U.config_from_dict({"n": 100, "bogus": 1, "distributions": {"a": {"enabled": True}, "zz": {}},
                               "correlations": [["m", "a", 0.2], ["x", "y", 0.1], "junk"]})
    assert part.n == 100 and part.seed == U.DEFAULT_SEED
    assert part.distributions["a"].enabled and part.distributions["a"].mode == "relative"
    assert part.correlations == {("a", "m"): 0.2}
    assert U.config_from_dict(None).n == U.DEFAULT_N
    assert U.config_from_dict({}).enabled_names() == ()


def test_uncertainty_module_never_imports_qt():
    code = ("import sys, modules.uncertainty;"
            "bad = sorted(m for m in sys.modules if m.startswith('PyQt'));"
            "print(','.join(bad))")
    proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                          text=True, check=True)
    assert proc.stdout.strip() == "", f"uncertainty pulled in Qt: {proc.stdout}"


# =============================================================================================
# Kernel: freeze_well / evaluate / run_monte_carlo
# =============================================================================================
import copy  # noqa: E402

import pandas as pd  # noqa: E402

from modules import param_scopes as ps  # noqa: E402
from modules.pipeline import PARAM_DEFAULTS, run_pipeline  # noqa: E402
from tests.golden.cases import CASES, FULL_MAPPING, build_case  # noqa: E402

PARITY_WELL = ("hcpv_net_pay", "hcpv_net_res", "net_pay", "avg_phie_pay", "avg_sw_pay")
PARITY_ZONE = ("hcpv_net_pay", "net_pay", "avg_phie_pay", "avg_sw_pay")


def assert_parity(fw):
    got = U.evaluate(fw, {})
    s = fw.base_summary
    for k in PARITY_WELL:
        np.testing.assert_allclose(got["well"][k], s[k], rtol=1e-12, atol=0, equal_nan=True, err_msg=k)
    assert [r["zone"] for r in s["zones"]] == fw.zones
    for row in s["zones"]:
        for k in PARITY_ZONE:
            np.testing.assert_allclose(got["zones"][row["zone"]][k], row[k], rtol=1e-12, atol=0,
                                       equal_nan=True, err_msg=f"{row['zone']}:{k}")


def zone_plan_for(params):
    return ps.zone_plan({**PARAM_DEFAULTS, **params}, None,
                        {"LOWER": {"m": ps.make_entry(ps.MANUAL, 1.8)}}, None, ("UPPER", "LOWER"))


@pytest.mark.parametrize("name", sorted(n for n in CASES if n != "no_rt_no_dt"))
def test_parity_golden_cases(name):
    data, mapping, params, tops = build_case(name)
    assert_parity(U.freeze_well(name, name, data, mapping, params, tops))


def test_no_rt_is_excluded():
    data, mapping, params, tops = build_case("no_rt_no_dt")
    with pytest.raises(U.UncertaintyExcluded, match="RT"):
        U.freeze_well("w", "w", data, mapping, params, tops)


def test_no_phie_is_excluded():
    data, mapping, params, tops = build_case("defaults_whole_well")
    mapping = {**mapping, "RHOB": "None", "NPHI": "None", "DT": "None"}
    with pytest.raises(U.UncertaintyExcluded):
        U.freeze_well("w", "w", data, mapping, params, tops)


@pytest.mark.parametrize("name", ["per_formation_lower", "rock_typing_enabled"])
def test_parity_zoned_with_zone_m_override(name):
    data, mapping, params, tops = build_case(name)
    params = {**params, "zone_plan": zone_plan_for(params)}
    fw = U.freeze_well(name, name, data, mapping, params, tops)
    assert fw.zones
    assert len(fw.segments) >= 1
    assert_parity(fw)
    if name == "rock_typing_enabled":
        assert len(fw.segments) == 2          # LOWER planned + the rest


@pytest.mark.parametrize("rw_mode,rsh_mode,rsh_ref", [
    ("manual", "manual", None), ("manual", "manual", 75.0),
    ("auto", "auto", None), ("auto", "manual", 80.0)])
@pytest.mark.parametrize("zoned", [False, True])
def test_parity_temperature_correction(rw_mode, rsh_mode, rsh_ref, zoned):
    data, mapping, params, tops = build_case("rock_typing_enabled" if zoned else "defaults_whole_well")
    params = {**params, "temp_correction": True, "rw_mode": rw_mode, "rsh_mode": rsh_mode,
              "rsh_ref_temp": rsh_ref, "rw": 0.08, "rsh": 4.0}
    if zoned:
        params["zone_plan"] = zone_plan_for(params)
    fw = U.freeze_well("t", "t", data, mapping, params, tops)
    assert fw.segments[0].tctx is not None and fw.segments[0].tctx.factor is not None
    assert_parity(fw)


def test_parity_temperature_with_waxman_smits_auto_b():
    data, mapping, params, tops = build_case("gas_all_sw_models")
    params = {**params, "temp_correction": True, "ws_b_auto": True}
    assert_parity(U.freeze_well("t", "t", data, mapping, params, tops))


@pytest.mark.parametrize("theta", [
    {"m": 0.1}, {"rw": 0.2}, {"sw_cutoff": -0.05, "phi_cutoff": 0.01},
    {"n": 0.15, "a": -0.1, "vsh_cutoff": 0.05}, {"rsh": 0.3, "m": -0.1, "n": -0.2}])
def test_perturbed_evaluate_equals_pipeline_with_changed_params(theta):
    """Theta moves the resolved values exactly like editing them in the parameters would."""
    data, mapping, params, tops = build_case("defaults_whole_well")
    params = {**params, "rw": 0.05, "rw_mode": "manual", "rsh_mode": "manual", "rsh": 4.0}
    fw = U.freeze_well("w", "w", data, mapping, params, tops)
    base = fw.segments[0].params
    change = {k: U.apply_offset(k, base[k], off, U.DEFAULT_MODES[k])[0] for k, off in theta.items()}
    assert all(change[k] != base[k] for k in theta)
    got = U.evaluate(fw, theta)
    _, summary = run_pipeline(data, mapping, {**params, **change}, None, tops)
    for k in ("hcpv_net_pay", "hcpv_net_res", "net_pay", "avg_phie_pay", "avg_sw_pay"):
        np.testing.assert_allclose(got["well"][k], summary[k], rtol=1e-10, equal_nan=True, err_msg=k)


def test_evaluate_clipped_flags_and_cutoff_only_reuses_sw():
    data, mapping, params, tops = build_case("defaults_whole_well")
    fw = U.freeze_well("w", "w", data, mapping, params, tops)
    r = U.evaluate(fw, {"m": 10.0, "sw_cutoff": 0.01})
    assert r["clipped"] == {"m": True, "sw_cutoff": False}
    base_sw = [s.sw_base for s in fw.segments]
    U.evaluate(fw, {"vsh_cutoff": 0.05, "phi_cutoff": -0.01})     # cutoffs only: sw_base untouched
    assert all(a is b for a, b in zip(base_sw, [s.sw_base for s in fw.segments]))


# ---- synthetic wells -------------------------------------------------------

def synth_well(phi, sw_target, n=300, seed=0, rt_zero=0):
    """Clean sand whose Archie Sw (a=1, m=2, n=2, Rw=0.05) is ~sw_target; first rt_zero RT <= 0."""
    rng = np.random.default_rng(seed)
    phi = np.broadcast_to(np.asarray(phi, dtype=float), n).copy()
    sw = np.broadcast_to(np.asarray(sw_target, dtype=float), n) * (1 + 0.05 * rng.standard_normal(n))
    rt = 0.05 / (phi ** 2 * sw ** 2)
    rt[:rt_zero] = 0.0
    return pd.DataFrame({
        "DEPTH": 1000.0 + 0.5 * np.arange(n),
        "GR": np.full(n, 20.0), "RHOB": 2.65 - 1.65 * phi, "NPHI": phi, "DT": np.full(n, 70.0),
        "RT": rt})


SYNTH_PARAMS = {"vsh_baseline_method": "Custom (Manual)", "gr_min_manual": 20.0, "gr_max_manual": 120.0,
                "sw_methods": ["Archie"], "sw_primary_method": "Archie", "rw": 0.05,
                "a": 1.0, "m": 2.0, "n": 2.0,
                "rw_mode": "manual", "rsh_mode": "manual", "rsh": 4.0}


def synth_frozen(key, phi, sw_target, **kw):
    return U.freeze_well(key, key, synth_well(phi, sw_target, **kw), FULL_MAPPING, SYNTH_PARAMS)


def cfg_for(names, n=100, seed=5, **kw):
    cfg = make_cfg(names=names, n=n, seed=seed)
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


def test_synth_well_basics():
    fw = synth_frozen("a", 0.25, 0.4)
    det = U.evaluate(fw, {})["well"]
    assert det["net_pay"] == pytest.approx(fw.dz.sum()) and 0.35 < det["avg_sw_pay"] < 0.45


def test_run_monte_carlo_carries_rw_quality():
    a, b = synth_frozen("a", 0.25, 0.5), synth_frozen("b", 0.12, 0.3, seed=1)
    assert all(sg.rw_quality is None for sg in a.segments)    # fixed Rw: nothing to report
    b.segments[0].rw_quality = "uniform"
    res = U.run_monte_carlo([a, b], cfg_for(("rw",), n=50))
    assert res.rw_quality == {"a": [], "b": ["uniform"]}
    assert U.rw_quality_text(res) == "Auto Rw: uniform estimate"


def test_run_monte_carlo_seed_reproducible_and_different():
    wells = [synth_frozen("a", 0.25, 0.5), synth_frozen("b", 0.12, 0.3, seed=1)]
    cfg = cfg_for(("rw", "sw_cutoff", "phi_cutoff"))
    r1, r2 = U.run_monte_carlo(wells, cfg), U.run_monte_carlo(wells, cfg)
    assert r1.values.keys() == r2.values.keys()
    for k in r1.values:
        np.testing.assert_array_equal(r1.values[k], r2.values[k])
    np.testing.assert_array_equal(r1.offsets, r2.offsets)
    cfg3 = cfg_for(("rw", "sw_cutoff", "phi_cutoff"), seed=6)
    r3 = U.run_monte_carlo(wells, cfg3)
    assert not np.array_equal(r1.values[("field", "hcpv_net_pay")], r3.values[("field", "hcpv_net_pay")])


def test_result_fields_and_progress():
    wells = [synth_frozen("a", 0.25, 0.5)]
    cfg = cfg_for(("rw", "sw_cutoff"), n=200)
    calls = []
    res = U.run_monte_carlo(wells, cfg, progress=lambda d, t: calls.append((d, t)),
                            excluded=[{"key": "x", "name": "X", "reason": "no RT curve"}])
    assert res.n == 200 and res.seed == 5 and res.sampling == "lhs"
    assert res.names == ("rw", "sw_cutoff") and res.offsets.shape == (200, 2)
    assert res.wells == [{"key": "a", "name": "a"}] and res.zones == {"a": []}
    assert res.excluded[0]["key"] == "x"
    assert any("X excluded" in w for w in res.warnings) and any("Not varied" in w for w in res.warnings)
    assert res.config == U.config_to_dict(cfg) and res.elapsed_s > 0
    assert calls[-1] == (200, 200) and [c[0] for c in calls] == sorted(c[0] for c in calls)
    assert len(calls) <= 101
    assert set(res.clipped) == {"rw", "sw_cutoff"}
    assert set(res.rank_corr) == set(U.METRICS)
    # deterministic column equals the base summary
    s = wells[0].base_summary
    assert res.deterministic[("a", "hcpv_net_pay")] == pytest.approx(s["hcpv_net_pay"], rel=1e-12)
    assert res.deterministic[("field", "net_pay")] == pytest.approx(s["net_pay"], rel=1e-12)


def test_run_monte_carlo_refuses_bad_input():
    with pytest.raises(ValueError):
        U.run_monte_carlo([synth_frozen("a", 0.25, 0.5)], U.UncertaintyConfig())
    with pytest.raises(ValueError):
        U.run_monte_carlo([], cfg_for(("rw",)))


@pytest.mark.parametrize("case", ["defaults_whole_well", "per_formation_lower", "mixed_depth_step"])
def test_exceedance_ordering_every_metric(case):
    data, mapping, params, tops = build_case(case)
    fw = U.freeze_well("w", "w", data, mapping, params, tops)
    res = U.run_monte_carlo([fw], cfg_for(U.PARAM_ORDER, n=100))
    assert len(res.stats) == (1 + 1 + len(fw.zones)) * len(U.METRICS)
    for key, st in res.stats.items():
        if st["n_valid"]:
            assert st["p90"] <= st["p50"] <= st["p10"], key
            assert st["min"] <= st["p90"] and st["p10"] <= st["max"], key
    # the deterministic zone value is among the zone scopes
    for z in fw.zones:
        assert ((("w", z)), "hcpv_net_pay") in res.values


def test_aggregation_field_is_sum_not_sum_of_percentiles_and_weighted_averages():
    # Well A reacts to Rw (Sw close to the cutoff), well B to the porosity cutoff (phie straddles it).
    a = synth_frozen("a", 0.25, np.linspace(0.45, 0.75, 300))
    b = synth_frozen("b", np.linspace(0.06, 0.11, 300), 0.15, seed=1)
    cfg = cfg_for(("rw", "phi_cutoff"), n=300)
    res = U.run_monte_carlo([a, b], cfg)
    v = res.values
    hcpv = v[("field", "hcpv_net_pay")]
    np.testing.assert_allclose(hcpv, v[("a", "hcpv_net_pay")] + v[("b", "hcpv_net_pay")], rtol=1e-12)
    p90_sum = res.stats[("a", "hcpv_net_pay")]["p90"] + res.stats[("b", "hcpv_net_pay")]["p90"]
    p90_field = res.stats[("field", "hcpv_net_pay")]["p90"]
    assert abs(p90_field - p90_sum) > 1e-3 * abs(p90_sum)
    assert p90_field == pytest.approx(np.percentile(hcpv, 10))
    # avg PHIE: net-pay weighted mean per realisation
    net = np.vstack([v[("a", "net_pay")], v[("b", "net_pay")]])
    phie = np.vstack([v[("a", "avg_phie_pay")], v[("b", "avg_phie_pay")]])
    ok = np.isfinite(phie) & (net > 0)
    expect = (np.where(ok, phie, 0) * net).sum(0) / np.where(ok, net, 0).sum(0)
    np.testing.assert_allclose(v[("field", "avg_phie_pay")], expect, rtol=1e-12)
    # avg Sw: weighted by phih_pay
    phih = np.vstack([v[("a", "phih_pay")], v[("b", "phih_pay")]])
    sw = np.vstack([v[("a", "avg_sw_pay")], v[("b", "avg_sw_pay")]])
    ok = np.isfinite(sw) & (phih > 0)
    expect = (np.where(ok, sw, 0) * phih).sum(0) / np.where(ok, phih, 0).sum(0)
    np.testing.assert_allclose(v[("field", "avg_sw_pay")], expect, rtol=1e-12)


def test_field_skips_wells_with_undefined_average():
    full = {m: np.array([1.0, 1.0]) for m in U.METRICS}
    empty = {m: np.array([0.0, 0.0]) for m in U.METRICS}
    empty["avg_phie_pay"] = empty["avg_sw_pay"] = np.array([np.nan, np.nan])
    full["avg_phie_pay"], full["avg_sw_pay"] = np.array([0.2, 0.2]), np.array([0.4, 0.4])
    out = U.aggregate_field([full, empty])
    np.testing.assert_allclose(out["avg_phie_pay"], 0.2)
    np.testing.assert_allclose(out["avg_sw_pay"], 0.4)
    # no well has phih_pay: Sw falls back to the net pay weights
    a = {m: np.array([2.0]) for m in U.METRICS}
    b = {m: np.array([1.0]) for m in U.METRICS}
    a["phih_pay"] = b["phih_pay"] = np.array([0.0])
    a["avg_sw_pay"], b["avg_sw_pay"] = np.array([0.3]), np.array([0.6])
    np.testing.assert_allclose(U.aggregate_field([a, b])["avg_sw_pay"], (0.3 * 2 + 0.6 * 1) / 3)


def test_tornado_monotone_single_parameter_and_structure():
    fw = synth_frozen("a", 0.25, np.linspace(0.3, 0.9, 300))
    cfg = cfg_for(("sw_cutoff",))
    res = U.run_monte_carlo([fw], cfg)
    d = cfg.distributions["sw_cutoff"]
    lo, hi = (float(U.marginal_quantile(d, q)) for q in (0.10, 0.90))
    out_lo = U.evaluate(fw, {"sw_cutoff": lo})["well"]["hcpv_net_pay"]
    out_hi = U.evaluate(fw, {"sw_cutoff": hi})["well"]["hcpv_net_pay"]
    assert out_hi > out_lo
    for scope in ("field", "a"):
        (row,) = res.tornado[(scope, "hcpv_net_pay")]
        assert row["name"] == "sw_cutoff"
        assert row["swing"] == pytest.approx(out_hi - out_lo, rel=1e-12)
        assert row["at_low_input"] == pytest.approx(out_lo) and row["at_high_input"] == pytest.approx(out_hi)
        assert (row["low_input"], row["high_input"]) == pytest.approx((lo, hi))
        assert row["base"] == res.deterministic[(scope, "hcpv_net_pay")]
        assert row["bar_min"] <= row["base"] <= row["bar_max"]
    assert ("field", "net_pay") in res.tornado and ("field", "avg_sw_pay") not in res.tornado


def test_tornado_sorted_base_center_and_only_enabled_parameters():
    fw = synth_frozen("a", 0.25, np.linspace(0.3, 0.9, 300))
    res = U.run_monte_carlo([fw], cfg_for(("rw", "sw_cutoff", "phi_cutoff")))
    rows = res.tornado[("field", "hcpv_net_pay")]
    assert {r["name"] for r in rows} == {"rw", "sw_cutoff", "phi_cutoff"}
    assert "m" not in {r["name"] for r in rows}
    swings = [r["swing"] for r in rows]
    assert swings == sorted(swings, reverse=True)
    assert all(r["base"] == res.deterministic[("field", "hcpv_net_pay")] for r in rows)
    assert res.deterministic[("field", "hcpv_net_pay")] == pytest.approx(
        fw.base_summary["hcpv_net_pay"], rel=1e-12)
    # phi_cutoff far below the porosity of this well changes nothing
    assert [r for r in rows if r["name"] == "phi_cutoff"][0]["swing"] == 0.0


def test_rt_nonpositive_samples_never_pay():
    fw = synth_frozen("a", 0.25, 0.3, rt_zero=50)
    res = U.run_monte_carlo([fw], cfg_for(("rw", "sw_cutoff", "vsh_cutoff", "phi_cutoff")))
    expected = fw.dz[50:].sum()
    np.testing.assert_allclose(res.values[("a", "net_pay")], expected, rtol=1e-12)
    np.testing.assert_allclose(res.deterministic[("a", "net_pay")], expected, rtol=1e-12)
    # even with the loosest cutoffs the 50 NaN-Sw samples stay out
    loose = U.evaluate(fw, {"sw_cutoff": 0.9, "phi_cutoff": -0.5, "vsh_cutoff": 0.9})
    assert loose["well"]["net_pay"] <= expected + 1e-9
    assert np.isnan(fw.segments[0].sw_base[:50]).all()


def test_all_zero_pay_stats():
    fw = synth_frozen("a", 0.25, 5.0)          # Sw clips to 1: nothing passes any Sw cutoff
    res = U.run_monte_carlo([fw], cfg_for(("rw", "sw_cutoff")))
    for scope in ("a", "field"):
        np.testing.assert_array_equal(res.values[(scope, "net_pay")], 0.0)
        assert res.stats[(scope, "net_pay")]["prob_zero"] == 1.0
        assert res.stats[(scope, "hcpv_net_pay")]["prob_zero"] == 1.0
        for m in ("avg_phie_pay", "avg_sw_pay"):
            assert res.stats[(scope, m)]["n_valid"] == 0
            assert np.isnan(res.stats[(scope, m)]["p50"])
        assert res.stats[(scope, "hcpv_net_pay")]["n_valid"] == 100


def test_cancel_mid_run_returns_none():
    wells = [synth_frozen("a", 0.25, 0.5)]
    cfg = cfg_for(("rw", "sw_cutoff"), n=200)
    polled = []

    def cancel():
        polled.append(1)
        return len(polled) > 30

    assert U.run_monte_carlo(wells, cfg, cancel=cancel) is None
    assert len(polled) == 31
    assert U.run_monte_carlo(wells, cfg, cancel=lambda: True) is None
    assert U.run_monte_carlo(wells, cfg, cancel=lambda: False) is not None


def test_inputs_are_not_mutated():
    data, mapping, params, tops = build_case("rock_typing_enabled")
    params = {**params, "zone_plan": zone_plan_for(params)}
    data0, mapping0 = data.copy(deep=True), copy.deepcopy(mapping)
    params0 = copy.deepcopy(params)
    tops_state = repr(vars(tops))
    fw = U.freeze_well("w", "w", data, mapping, params, tops)
    summary0 = copy.deepcopy(fw.base_summary)
    cfg = cfg_for(("m", "rw", "sw_cutoff"))
    cfg0 = U.config_to_dict(cfg)
    U.evaluate(fw, {"m": 0.1, "rw": -0.1})
    U.run_monte_carlo([fw], cfg)
    pd.testing.assert_frame_equal(data, data0)
    assert mapping == mapping0 and repr(params) == repr(params0) and repr(vars(tops)) == tops_state
    assert repr(fw.base_summary) == repr(summary0)
    assert U.config_to_dict(cfg) == cfg0
