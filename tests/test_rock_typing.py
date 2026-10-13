"""Pure rock-typing module: equations, core table, fit, classify, Lorenz/SMLP (P1 spec section 9)."""

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from modules import rock_typing as rt


def _inp(phi, k, depth=None, key="W1", tvd=False, zone=None, **kw):
    n = len(phi)
    depth = np.arange(n, dtype=float) + 1000.0 if depth is None else np.asarray(depth, float)
    zone = np.full(n, "(unzoned)", dtype=object) if zone is None else np.asarray(zone, dtype=object)
    return rt.CoreInput(key, key, depth, np.asarray(phi, float), np.asarray(k, float),
                        zone, tvd, **kw)


def _mixture(seed=3, centres=(-0.5, 0.0, 0.6), n=60, sd=0.05):
    rng = np.random.default_rng(seed)
    x = np.concatenate([rng.normal(c, sd, n) for c in centres])
    phi = rng.uniform(0.08, 0.30, len(x))
    return x, phi


# ---------------------------------------------------------------------------
# Equations
# ---------------------------------------------------------------------------
def test_rqi_fzi_hand_values():
    k, phi = 100.0, 0.2
    assert rt.rqi(k, phi) == pytest.approx(0.0314 * np.sqrt(500.0))
    assert rt.phi_z(phi) == pytest.approx(0.25)
    assert rt.fzi(k, phi) == pytest.approx(0.0314 * np.sqrt(500.0) / 0.25)
    assert float(rt.fzi(k, phi)) == pytest.approx(2.8085, abs=1e-4)


def test_invalid_inputs_give_nan():
    assert np.isnan(rt.rqi(-1.0, 0.2)) and np.isnan(rt.rqi(1.0, 0.0))
    assert np.isnan(rt.phi_z(1.0)) and np.isnan(rt.fzi(10.0, 0.0))
    assert np.isnan(rt.winland_r35(0.0, 0.2))


def test_perm_from_fzi_round_trips():
    k = np.array([0.5, 10.0, 100.0, 2500.0])
    phi = np.array([0.05, 0.12, 0.2, 0.3])
    assert rt.perm_from_fzi(rt.fzi(k, phi), phi) == pytest.approx(k, rel=1e-12)


def test_corrected_form_not_the_phiz_cubed_form():
    k, phi = 100.0, 0.2
    f, z = float(rt.fzi(k, phi)), float(rt.phi_z(phi))
    wrong = f ** 2 * z ** 3 * phi / rt.K_RQI ** 2
    assert wrong == pytest.approx(k * z)           # off by exactly phi_z
    assert float(rt.perm_from_fzi(f, phi)) == pytest.approx(k)
    # equals the 1014.2 phi^3 / (1 - phi)^2 form
    assert float(rt.perm_from_fzi(f, phi)) == pytest.approx(1014.2 * f ** 2 * phi ** 3 / (1 - phi) ** 2, rel=1e-3)


def test_perm_from_fzi_is_clipped():
    assert float(rt.perm_from_fzi(1e-6, 0.1)) == 0.001
    assert float(rt.perm_from_fzi(1e3, 0.4)) == 50000.0


def test_winland_uses_percent_porosity():
    k, phi = 100.0, 0.2
    expect = 10 ** (0.732 + 0.588 * np.log10(100.0) - 0.864 * np.log10(20.0))
    assert float(rt.winland_r35(k, phi)) == pytest.approx(expect)
    # feeding the fraction as if it were percent would give a very different number
    wrong = 10 ** (0.732 + 0.588 * np.log10(100.0) - 0.864 * np.log10(0.2))
    assert float(rt.winland_r35(k, phi)) < wrong / 5


# ---------------------------------------------------------------------------
# Core table
# ---------------------------------------------------------------------------
def test_core_table_every_status_counted():
    nan = np.nan
    phi = [0.20, nan, 0.20, 0.20, 0.005, 0.60, 0.20, 0.15]
    k = [100., 50., nan, -1., 50., 50., 30., 10.]
    depth = [1, 2, 3, 4, 5, 6, nan, 8]
    table, rep = rt.build_core_table([_inp(phi, k, depth)], {})
    assert list(table["status"]) == ["ok", "no_porosity", "no_perm", "perm_not_positive",
                                     "phi_out_of_range", "phi_out_of_range", "no_depth", "ok"]
    assert rep["rows"] == 8 and rep["valid"] == 2
    assert rep["excluded"] == {"no_porosity": 1, "no_perm": 1, "perm_not_positive": 1,
                               "phi_out_of_range": 2, "no_depth": 1}
    assert rep["valid"] + sum(rep["excluded"].values()) == rep["rows"]
    assert rep["per_well"]["W1"]["valid"] == 2
    ok = table[table["status"] == "ok"]
    assert ok["fzi"].notna().all() and table.loc[table["status"] != "ok", "fzi"].isna().all()
    assert ok["fzi"].iloc[0] == pytest.approx(float(rt.fzi(100.0, 0.2)))


def test_core_table_report_extras():
    a = _inp([0.2] * 30, np.r_[np.full(29, 50.0), 5e5], key="A", load_excluded={"null_sentinel": 4})
    b = _inp([0.2] * 5, [10.0] * 5, key="B", tvd=True, load_excluded={"nonpositive_perm": 1})
    table, rep = rt.build_core_table([a, b], {})
    assert rep["load_excluded"] == {"null_sentinel": 4, "nonpositive_perm": 1}
    assert rep["tvd_wells"] == ["B"]
    assert rep["outliers_z3"] == 1 and rep["outlier_rows"][0]["well_key"] == "A"
    assert any("not applied" in n for n in rep["notes"])
    assert not rep["overburden"]["applied"]
    assert set(table["well_key"]) == {"A", "B"}


def test_core_table_overburden_factors_applied_before_rqi():
    base, _ = rt.build_core_table([_inp([0.2], [100.0])], {})
    ob, rep = rt.build_core_table([_inp([0.2], [100.0])], {"ob_k_factor": 0.64, "ob_phi_factor": 1.0})
    assert ob["k"].iloc[0] == pytest.approx(64.0)
    assert ob["fzi"].iloc[0] == pytest.approx(base["fzi"].iloc[0] * 0.8)
    assert rep["overburden"]["applied"] and not any("not applied" in n for n in rep["notes"])


def test_core_table_empty():
    table, rep = rt.build_core_table([], {})
    assert len(table) == 0 and rep["rows"] == 0 and rep["valid"] == 0


def test_core_inputs_snapshot_and_zones():
    from models.project import Project  # noqa: F401  (import check only)

    fm = lambda name, top, bot: SimpleNamespace(name=name, top_depth=top, bottom_depth=bot)
    handler = SimpleNamespace(
        data=pd.DataFrame({"depth": [1000., 1010., 1030.], "por": [0.2, 0.1, 0.15],
                           "perm": [100., 5., 20.]}),
        depth_col="depth", porosity_col="por", perm_col="perm", depth_is_tvd=False,
        excluded_rows=[(3, "null sentinel in permeability (value excluded)")],
        excluded_row_wells={3: ""}, spellings=[])
    tvd = SimpleNamespace(**{**handler.__dict__, "depth_is_tvd": True})
    tops = SimpleNamespace(formations=[fm("Upper  sand", 990, 1020), fm("Lower", 1020, 1100)])
    wells = [SimpleNamespace(key="A", display_name="Alpha", core_data=handler, formation_tops=tops),
             SimpleNamespace(key="B", display_name="", core_data=tvd, formation_tops=tops),
             SimpleNamespace(key="C", display_name="C", core_data=None, formation_tops=None)]
    out = rt.core_inputs(SimpleNamespace(project=SimpleNamespace(wells=wells)))
    assert [c.well_key for c in out] == ["A", "B"]
    assert list(out[0].zone) == ["UPPER SAND", "UPPER SAND", "LOWER"]
    assert set(out[1].zone) == {"(unzoned)"} and out[1].depth_is_tvd
    assert out[0].load_excluded == {"null_sentinel": 1}
    out[0].phi[0] = 9.0                       # a copy: the handler is not touched
    assert handler.data["por"].iloc[0] == 0.2


# ---------------------------------------------------------------------------
# Fit
# ---------------------------------------------------------------------------
def test_fit_recovers_three_populations():
    x, phi = _mixture()
    s = rt.fit_rock_types(x, 3)
    assert s["n_rt"] == 3
    assert s["centers"] == pytest.approx([-0.5, 0.0, 0.6], abs=0.03)
    assert s["centers"] == sorted(s["centers"])          # 1 = lowest FZI
    assert s["boundaries"] == pytest.approx([(a + b) / 2 for a, b in zip(s["centers"], s["centers"][1:])])
    assert s["fzi"] == pytest.approx([10 ** c for c in s["centers"]])
    assert sum(s["n_samples"]) == len(x) and s["n_samples"] == [60, 60, 60]
    assert s["feature_range"] == [float(x.min()), float(x.max())]
    assert s["edited"] is False and "180" in s["basis"]


def test_fit_ids_independent_of_order_and_stable():
    x, _ = _mixture()
    a = rt.fit_rock_types(x, 3)
    shuffled = np.random.default_rng(9).permutation(x)
    b = rt.fit_rock_types(shuffled, 3)
    assert a == b
    ids_a, _ = rt.classify(x, a)
    ids_b, _ = rt.classify(x, b)
    assert (ids_a == ids_b).all()
    # lowest FZI is rock type 1
    assert ids_a[x.argmin()] == 1 and ids_a[x.argmax()] == 3
    # every seed 0..9 alone finds the same classes on separated data
    for seed in range(10):
        c, _ = rt._kmeans_1d(np.sort(x), 3, [seed])
        assert np.sort(c) == pytest.approx(a["centers"], abs=0.02)


def test_fit_k_rmse_with_core_pairs():
    x, phi = _mixture()
    k = rt.perm_from_fzi(10 ** x, phi)
    s = rt.fit_rock_types(x, 3, phi=phi, k=k, basis="pooled, 1 wells, 180 samples")
    assert all(v is not None and v < 0.3 for v in s["k_rmse_log10"])
    assert s["basis"] == "pooled, 1 wells, 180 samples"


def test_suggest_n_rt_returns_three():
    x, _ = _mixture()
    n, info = rt.suggest_n_rt(x)
    assert n == 3
    assert set(info["silhouette"]) <= set(range(2, 9)) and info["silhouette"][3] == max(info["silhouette"].values())
    assert info["subsampled"] is False


def test_suggest_n_rt_large_input_is_deterministic():
    rng = np.random.default_rng(1)
    x = np.concatenate([rng.normal(c, 0.05, 2500) for c in (-0.4, 0.4)])
    n1, i1 = rt.suggest_n_rt(x)
    n2, i2 = rt.suggest_n_rt(rng.permutation(x))
    assert n1 == n2 == 2 and i1["subsampled"] and i1 == i2


def test_suggest_n_rt_too_few_samples():
    assert rt.suggest_n_rt(np.arange(6.0))[0] is None


def test_fit_refuses_too_few_samples():
    with pytest.raises(rt.RockTypingError, match=r"Only 10 valid core samples.*20"):
        rt.fit_rock_types(np.linspace(-1, 1, 10), 2)
    assert issubclass(rt.RockTypingError, ValueError)


def test_fit_refuses_small_class():
    x = np.concatenate([np.random.default_rng(0).normal(0, 0.05, 40), [3.0, 3.01]])
    with pytest.raises(rt.RockTypingError, match=r"class with 2 samples.*at least 5"):
        rt.fit_rock_types(x, 2)


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_fit_refuses_when_all_restarts_fail():
    x = np.zeros(30)                                       # identical values: empty clusters
    with pytest.raises(rt.RockTypingError, match=r"failed in all 10 restarts"):
        rt.fit_rock_types(x, 3)
    with pytest.raises(rt.RockTypingError, match="At least 2"):
        rt.fit_rock_types(np.linspace(0, 1, 30), 1)


# ---------------------------------------------------------------------------
# Classify and R35
# ---------------------------------------------------------------------------
def test_classify_and_margins():
    s = {"boundaries": [-0.25, 0.3]}
    x = np.array([-1.0, -0.25, -0.2, 0.0, 0.3, 0.9, np.nan])
    r, m = rt.classify(x, s)
    assert list(r) == [1, 1, 2, 2, 2, 3, 0]       # searchsorted(left): a value on a boundary is the lower type
    assert m[0] == pytest.approx(0.75) and m[3] == pytest.approx(0.25)
    assert m[2] == pytest.approx(0.05) and m[1] == 0.0
    assert np.isnan(m[6])
    assert r.dtype.kind == "i"


def test_default_r35_set():
    s = rt.default_r35_set()
    assert s["boundaries"] == [-1.0, -0.301, 0.301, 1.0] and s["n_rt"] == 5
    assert len(s["centers"]) == 5 and s["fzi"] == [None] * 5 and s["edited"] is False
    r, _ = rt.classify(np.log10([0.05, 0.3, 1.0, 5.0, 20.0]), s)
    assert list(r) == [1, 2, 3, 4, 5]
    json.dumps(s)


def test_fit_r35_method_geometric_mean_fzi():
    rng = np.random.default_rng(2)
    phi = rng.uniform(0.08, 0.3, 80)
    k = 10 ** rng.uniform(-0.5, 2.5, 80)
    x = np.log10(rt.winland_r35(k, phi))
    lf = np.log10(rt.fzi(k, phi))
    s = rt.fit_rock_types(x, 5, method="r35", phi=phi, k=k, log_fzi=lf)
    assert s["boundaries"] == rt.R35_BOUNDARIES and sum(s["n_samples"]) == 80
    cls = np.searchsorted(rt.R35_BOUNDARIES, x)
    for i in range(5):
        sel = cls == i
        if sel.any():
            assert s["fzi"][i] == pytest.approx(10 ** np.mean(lf[sel]))
        else:
            assert s["fzi"][i] is None
    with pytest.raises(rt.RockTypingError):
        rt.fit_rock_types(x[:5], 5, method="r35")


# ---------------------------------------------------------------------------
# Lorenz and SMLP
# ---------------------------------------------------------------------------
def test_lorenz_homogeneous_is_zero():
    phi = np.full(50, 0.2)
    assert rt.lorenz_coefficient(phi, np.full(50, 80.0), np.full(50, 0.5)) == pytest.approx(0.0, abs=1e-12)
    # k proportional to phi is also homogeneous in flow per storage
    p = np.linspace(0.1, 0.3, 50)
    assert rt.lorenz_coefficient(p, 400 * p, np.ones(50)) == pytest.approx(0.0, abs=1e-12)


def test_lorenz_extreme_tends_to_one():
    n = 400
    k = np.full(n, 1e-6)
    k[0] = 1e4
    lc = rt.lorenz_coefficient(np.full(n, 0.2), k, np.ones(n))
    assert 0.99 < lc <= 1.0
    mid = rt.lorenz_coefficient(np.full(n, 0.2), np.linspace(1, 100, n), np.ones(n))
    assert 0.0 < mid < lc
    assert np.isnan(rt.lorenz_coefficient([], [], []))


def test_core_thickness_caps_gaps():
    h = rt.core_thickness([10.0, 11.0, 12.0, 50.0, 51.0])
    assert h[1] == pytest.approx(1.0)                # 0.5 + 0.5
    assert h[2] == pytest.approx(0.5 + 0.5)          # the 38 ft gap is capped at the median (1 ft)
    assert h[3] == pytest.approx(0.5 + 0.5)
    assert h[0] == pytest.approx(1.0) and h[4] == pytest.approx(1.0)
    assert (rt.core_thickness([5.0]) == 0).all()
    h2 = rt.core_thickness([12.0, 10.0, 11.0])      # unsorted input keeps its order
    assert list(h2) == [1.0, 1.0, 1.0]


def _two_slope_curve():
    n = 100
    depth = np.arange(n, dtype=float) + 0.5
    phi = np.full(n, 0.2)
    k = np.r_[np.full(50, 180.0), np.full(50, 20.0)]
    return rt.smlp(depth, phi, k, np.ones(n))


def test_smlp_curve_shape():
    c = _two_slope_curve()
    assert list(c.columns) == ["depth", "top", "base", "h", "C", "F"]
    assert c["C"].iloc[-1] == pytest.approx(1.0) and c["F"].iloc[-1] == pytest.approx(1.0)
    assert c["C"].iloc[49] == pytest.approx(0.5) and c["F"].iloc[49] == pytest.approx(0.9)
    assert c["top"].iloc[0] == 0.0 and c["base"].iloc[-1] == 100.0


def test_smlp_units_break_at_slope_change():
    units = rt.smlp_units(_two_slope_curve())
    assert len(units) == 2
    assert units[0]["top"] == 0.0 and units[0]["bottom"] == pytest.approx(50.0) == units[1]["top"]
    assert units[1]["bottom"] == pytest.approx(100.0)
    assert units[0]["slope"] == pytest.approx(1.8) and units[0]["class"] == "speed"
    assert units[1]["slope"] == pytest.approx(0.2) and units[1]["class"] == "baffle"
    assert units[0]["storage_fraction"] == pytest.approx(0.5)
    assert units[0]["flow_fraction"] == pytest.approx(0.9)
    assert sum(u["thickness"] for u in units) == pytest.approx(100.0)


def test_smlp_units_thin_segments_merge_and_classes():
    n = 100
    k = np.r_[np.full(46, 180.0), np.full(4, 0.05), np.full(50, 20.0)]
    curve = rt.smlp(np.arange(n) + 0.5, np.full(n, 0.2), k, np.ones(n))
    assert len(rt.smlp_units(curve, eps=0.002, min_thickness_ft=1.0)) >= 3
    merged = rt.smlp_units(curve, eps=0.002, min_thickness_ft=5.0)
    assert len(merged) == 2 and all(u["thickness"] >= 5.0 for u in merged)
    assert rt.smlp_units(pd.DataFrame()) == []
    barrier = rt.smlp(np.arange(20) + 0.5, np.full(20, 0.2),
                      np.r_[np.full(10, 100.0), np.full(10, 1e-3)], np.ones(20))
    assert [u["class"] for u in rt.smlp_units(barrier)] == ["speed", "barrier"]


# ---------------------------------------------------------------------------
# JSON stability
# ---------------------------------------------------------------------------
def _plain_types(obj):
    if isinstance(obj, dict):
        return all(_plain_types(v) for v in obj.values())
    if isinstance(obj, list):
        return all(_plain_types(v) for v in obj)
    return obj is None or type(obj) in (int, float, str, bool)


def test_set_json_round_trip_is_byte_identical():
    x, phi = _mixture()
    k = rt.perm_from_fzi(10 ** x, phi)
    sets = {"*": rt.fit_rock_types(x, 3, phi=phi, k=k),
            "R35": rt.fit_rock_types(np.log10(rt.winland_r35(k, phi)), 5, method="r35",
                                     phi=phi, k=k, log_fzi=x),
            "default": rt.default_r35_set()}
    defs = {"version": 1, "method": "fzi", "sets": sets, "settings": dict(rt.DEFAULT_SETTINGS)}
    assert _plain_types(defs)
    first = json.dumps(defs, sort_keys=True, default=str)
    again = json.dumps(json.loads(first), sort_keys=True, default=str)
    assert first == again


# ---------------------------------------------------------------------------
# Free-slope fit (diagnostic)
# ---------------------------------------------------------------------------
def test_free_slope_fit_recovers_power_law():
    pz = np.linspace(0.1, 0.5, 12)
    f = rt.free_slope_fits(pz, 2.0 * pz ** 1.5, np.ones(12, int), 2)
    assert f[0]["slope"] == pytest.approx(1.5)
    assert f[0]["intercept_fzi"] == pytest.approx(2.0)
    assert f[0]["r2"] == pytest.approx(1.0)
    assert (f[0]["phiz_min"], f[0]["phiz_max"]) == (pz.min(), pz.max())
    assert f[1]["n"] == 0 and f[1]["slope"] is None


def test_free_slope_fit_too_few_or_identical_phiz_is_none():
    f = rt.free_slope_fits([0.1, 0.2], [0.1, 0.3], [1, 1], 1)
    assert f[0]["n"] == 2 and f[0]["slope"] is None and f[0]["r2"] is None
    f = rt.free_slope_fits([0.2, 0.2, 0.2], [0.1, 0.3, 0.2], [1, 1, 1], 1)
    assert f[0]["slope"] is None and f[0]["intercept_fzi"] is None


def test_free_slope_fit_ignores_label_zero_and_bad_values():
    pz = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7])
    rq = 2.0 * pz ** 1.5
    labels = np.array([1, 1, 1, 1, 0, 1, 1])
    pz = pz.copy()
    rq = rq.copy()
    rq[4] = 99.0                       # unassigned outlier: ignored
    pz[5], rq[6] = np.nan, -1.0        # NaN and non-positive: dropped
    f = rt.free_slope_fits(pz, rq, labels, 1)
    assert f[0]["n"] == 4
    assert f[0]["slope"] == pytest.approx(1.5)
    assert f[0]["phiz_max"] == pytest.approx(0.4)


def test_free_slope_fit_flat_rqi_has_no_r2():
    f = rt.free_slope_fits([0.1, 0.2, 0.4], [1.0, 1.0, 1.0], [1, 1, 1], 1)
    assert f[0]["slope"] == pytest.approx(0.0, abs=1e-9) and f[0]["r2"] is None
