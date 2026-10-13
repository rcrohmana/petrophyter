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
    cfg = make_cfg(); cfg.correlations[("a", "n")] = 0.3   # n not enabled
    assert U.validate_config(cfg)
    cfg = make_cfg(); cfg.correlations[("a", "m")] = 1.0
    assert U.validate_config(cfg)


def test_non_pd_refused():
    cfg = make_cfg()
    cfg.correlations = {("a", "m"): 0.9, ("m", "rw"): 0.9, ("a", "rw"): -0.9}
    assert any("positive definite" in e for e in U.validate_config(cfg))
    with pytest.raises(ValueError, match="positive definite"):
        U.sample_parameters(cfg)


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
