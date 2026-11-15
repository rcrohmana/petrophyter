"""Elastic screening maths: equations, validity, baselines, wet trend, flag (no pipeline)."""
import numpy as np
import pandas as pd
import pytest

from modules.lrlc import elastic
from modules.lrlc.elastic import elastic_screen
from modules.param_scopes import UNZONED

A0, A1 = 1.20, -1.00        # AI_REL wet = A0 + A1 * PHIE
C0, C1 = 1.10, -0.60        # VPVS_REL wet = C0 + C1 * PHIE
AI_SH, VP_SH = 6500.0, 2.0


def synth(seed=3, blocks=12, size=60, gas_blocks=(3,), zones=("UP", "LO"), noise=0.002,
          shale_ai=AI_SH, shale_vp=VP_SH):
    """Alternating shale / sand blocks; sand blocks listed in gas_blocks carry gas (lower AI, VPVS)."""
    rng = np.random.default_rng(seed)
    n = blocks * size
    depth = 5000.0 + 0.5 * np.arange(n)
    vsh = np.empty(n)
    phie = np.empty(n)
    sw = np.empty(n)
    net = np.zeros(n, dtype=int)
    ai = np.empty(n)
    vp = np.empty(n)
    gas = np.zeros(n, dtype=bool)
    for b in range(blocks):
        s = slice(b * size, (b + 1) * size)
        if b % 2 == 0:                                   # shale
            vsh[s], phie[s], sw[s] = 0.9, 0.05, 1.0
            ai[s] = shale_ai * (1 + noise * rng.standard_normal(size))
            vp[s] = shale_vp * (1 + noise * rng.standard_normal(size))
        else:                                            # sand
            phi = rng.uniform(0.10, 0.30, size)
            vsh[s], phie[s], net[s] = 0.1, phi, 1
            is_gas = b in gas_blocks
            gas[s] = is_gas
            sw[s] = 0.2 if is_gas else 0.97
            fa = 0.88 if is_gas else 1.0
            fv = 0.90 if is_gas else 1.0
            ai[s] = shale_ai * (A0 + A1 * phi) * fa * (1 + noise * rng.standard_normal(size))
            vp[s] = shale_vp * (C0 + C1 * phi) * fv * (1 + noise * rng.standard_normal(size))
    rhob = np.full(n, 2.45)
    dt = elastic.VP_FACTOR * rhob / ai
    dts = dt * vp
    zone = np.where(np.arange(n) < n // 2, zones[0], zones[1]).astype(object)
    res = pd.DataFrame({"VSH": vsh, "PHIE": phie, "SW": sw, "NET_RES_FLAG": net,
                        "LRLC_FLAG": np.zeros(n, dtype=int)})
    curves = {"DEPTH": depth, "DT": dt, "DTS": dts, "RHOB": rhob}
    params = {z: {} for z in zones}
    return res, curves, params, zone, gas


def run(data, **over):
    res, curves, params, zone, gas = data
    merged = {z: {**params[z], **over} for z in params}
    return elastic_screen(res, curves, merged, zone)


def test_worked_check():
    assert elastic.acoustic_impedance(100.0, 2.30) == pytest.approx(7010.4, abs=0.05)
    assert elastic.vp_vs_ratio(100.0, 180.0) == pytest.approx(1.80)
    out = elastic_screen(
        pd.DataFrame({"VSH": [0.5], "PHIE": [0.2], "SW": [1.0], "NET_RES_FLAG": [0], "LRLC_FLAG": [0]}),
        {"DEPTH": np.array([1.0]), "DT": np.array([100.0]), "DTS": np.array([180.0]),
         "RHOB": np.array([2.30])}, {"A": {}}, np.array(["A"], dtype=object))
    assert out.ai[0] == pytest.approx(7010.4, abs=0.05)
    assert out.vpvs[0] == pytest.approx(1.80)


def test_validity_ranges_and_ratio():
    dt = np.array([100.0, 39.0, 201.0, 100.0, 100.0, 100.0, 100.0, 100.0, np.nan])
    dts = np.array([180.0, 180.0, 180.0, 59.0, 180.0, 180.0, 110.0, 410.0, 180.0])
    rho = np.array([2.3, 2.3, 2.3, 2.3, 1.4, 3.3, 2.3, 2.3, 2.3])
    got = elastic.validity_mask(dt, dts, rho)
    assert got.tolist() == [True, False, False, False, False, False, False, False, False]
    # ratio bounds 1.15 and 4.0
    assert elastic.validity_mask([100.0, 100.0, 100.0], [114.0, 116.0, 401.0], [2.3] * 3).tolist() \
        == [False, True, False]


def test_invalid_samples_are_nan_zero_flag_and_counted():
    data = synth()
    data[1]["DTS"][100] = 10.0                           # out of range
    data[1]["DTS"][101] = np.nan
    out = run(data)
    assert np.isnan(out.ai[100]) and np.isnan(out.vpvs[100]) and out.flag[100] == 0
    assert out.flag.dtype.kind == "i" and set(np.unique(out.flag)) <= {0, 1}
    assert out.summary["counts"]["invalid"] == 2
    assert any(i[0] == "LRLC_ELASTIC_INVALID" and i[3] == "info" for i in out.issues)


def test_invalid_share_above_five_percent_warns():
    data = synth()
    data[1]["DTS"][: len(data[0]) // 10] = 10.0
    out = run(data)
    assert any(i[0] == "LRLC_ELASTIC_INVALID" and i[3] == "warning" for i in out.issues)


def test_us_per_m_detection_skips_the_stage():
    data = synth()
    data[1]["DT"] = data[1]["DT"] / 0.3048
    data[1]["DTS"] = data[1]["DTS"] / 0.3048
    out = run(data)
    assert not out.ran and out.flag.sum() == 0 and np.isnan(out.ai).all()
    assert [i[0] for i in out.issues] == ["LRLC_ELASTIC_UNITS"]
    assert elastic.looks_like_us_per_m([300.0], [400.0])
    assert elastic.looks_like_us_per_m([100.0], [600.0])
    assert not elastic.looks_like_us_per_m([100.0], [180.0])


def test_missing_dts_gives_info_and_no_run():
    res, curves, params, zone, _ = synth()
    curves = {k: v for k, v in curves.items() if k != "DTS"}
    out = elastic_screen(res, curves, params, zone)
    assert not out.ran and out.issues[0][0] == "LRLC_ELASTIC_NO_DTS" and out.issues[0][1].find("DTS") > 0


def test_wet_trend_recovers_the_synthetic_within_two_percent():
    out = run(synth(gas_blocks=(3, 7)))
    wet = out.summary["wet"]
    assert wet["source"] == "sw" and wet["scope"] == "well"
    assert wet["ai"]["a0"] == pytest.approx(A0, rel=0.02)
    assert wet["ai"]["a1"] == pytest.approx(A1, rel=0.02)
    assert wet["vpvs"]["c0"] == pytest.approx(C0, rel=0.02)
    assert wet["vpvs"]["c1"] == pytest.approx(C1, rel=0.02)
    assert wet["phi_span"] > 0.15 and wet["ai"]["r2"] > 0.9


def test_gas_sand_is_flagged_and_wet_sand_and_shale_are_not():
    data = synth(gas_blocks=(3, 7))
    out = run(data)
    gas = data[4]
    net = data[0]["NET_RES_FLAG"].to_numpy() == 1
    assert out.flag[gas].mean() > 0.95
    assert out.flag[net & ~gas].mean() < 0.02
    assert out.flag[~net].sum() == 0
    s = out.summary
    assert s["counts"]["flag"] == int(out.flag.sum())
    assert sum(z["n_flag"] for z in s["zones"]) == int(out.flag.sum())
    assert s["counts"]["unevaluable"] == 0


def test_thresholds_and_modes():
    data = synth(gas_blocks=(3,))
    gas = data[4]
    base = run(data)
    assert base.flag[gas].mean() > 0.95
    # drop of 12 percent in AI and 10 percent in VPVS: thresholds above it switch the flag off
    assert run(data, el_ai_drop=0.2).flag.sum() == 0
    assert run(data, el_vpvs_drop=0.2).flag.sum() == 0
    # one attribute only
    assert run(data, el_mode="ai", el_vpvs_drop=0.2).flag[gas].mean() > 0.95
    assert run(data, el_mode="vpvs", el_ai_drop=0.2).flag[gas].mean() > 0.95
    assert run(data, el_mode="ai", el_ai_drop=0.2).flag.sum() == 0
    # a looser threshold flags a mild anomaly
    mild = synth(gas_blocks=(3,))
    assert run(mild, el_ai_drop=0.01, el_vpvs_drop=0.01).flag.sum() >= base.flag.sum()


def test_zone_thresholds_apply_per_zone():
    data = synth(gas_blocks=(3, 9))                      # one gas block per zone
    res, curves, params, zone, gas = data
    params["LO"] = {"el_ai_drop": 0.3}
    out = elastic_screen(res, curves, params, zone)
    up = zone == "UP"
    assert out.flag[gas & up].mean() > 0.95
    assert out.flag[gas & ~up].sum() == 0


def test_rolling_baseline_follows_a_depth_trend():
    # shale AI rises with depth; the rolling baseline tracks it so wet sand stays unflagged
    data = synth(gas_blocks=())
    res, curves, params, zone, _ = data
    trend = np.linspace(1.0, 1.15, len(res))
    n = len(res)
    rho = curves["RHOB"]
    ai = elastic.acoustic_impedance(curves["DT"], rho) * trend
    dt = elastic.VP_FACTOR * rho / ai
    curves = {**curves, "DT": dt, "DTS": dt * (curves["DTS"] / curves["DT"])}
    for z in params:
        params[z] = {"el_baseline_mode": "rolling", "el_shale_window_ft": 100.0, "el_shale_min_n": 10}
    rolling = elastic_screen(res, curves, params, zone)
    assert rolling.summary["baseline"]["mode"] == "rolling"
    assert rolling.flag.sum() == 0
    for z in params:
        params[z] = {"el_baseline_mode": "zone"}
    assert elastic_screen(res, curves, params, zone).summary["baseline"]["mode"] == "zone"


def test_zone_baseline_is_the_zone_shale_median():
    data = synth(gas_blocks=())
    out = run(data, el_baseline_mode="zone")
    rows = {r["zone"]: r for r in out.summary["baseline"]["zones"]}
    assert rows["UP"]["ai_shale_median"] == pytest.approx(AI_SH, rel=0.005)
    assert rows["UP"]["vpvs_shale_median"] == pytest.approx(VP_SH, rel=0.005)
    assert rows["UP"]["fallback"] is None and rows["UP"]["n_shale"] > 100


def test_window_baseline_reads_the_user_interval():
    # shale of the zone is 6500, the user window sits on a stiffer streak
    res, curves, params, zone, _ = synth(gas_blocks=())
    depth = curves["DEPTH"]
    lo, hi = depth[0], depth[59]                         # first shale block
    params["UP"] = {"el_baseline_mode": "window", "el_shale_interval": [lo, hi]}
    params["LO"] = {"el_baseline_mode": "window", "el_shale_interval": None}
    out = elastic_screen(res, curves, params, zone)
    rows = {r["zone"]: r for r in out.summary["baseline"]["zones"]}
    assert rows["UP"]["n_shale"] == 60 and rows["UP"]["fallback"] is None
    assert rows["LO"]["fallback"] == "zone"              # no interval: zone median
    assert any(i[0] == "LRLC_ELASTIC_NO_SHALE" for i in out.issues)


def test_baseline_falls_back_zone_then_well():
    res, curves, params, zone, _ = synth(gas_blocks=())
    # zone UP keeps its shale; LO loses every shale sample except a few
    lo = np.flatnonzero((zone == "LO") & (res["VSH"].to_numpy() > 0.5))
    res = res.copy()
    res.loc[lo[3:], "VSH"] = 0.3
    out = elastic_screen(res, curves, {"UP": {"el_baseline_mode": "zone"},
                                       "LO": {"el_baseline_mode": "zone"}}, zone)
    rows = {r["zone"]: r for r in out.summary["baseline"]["zones"]}
    assert rows["UP"]["fallback"] is None
    assert rows["LO"]["fallback"] == "well"
    assert rows["LO"]["ai_shale_median"] == pytest.approx(AI_SH, rel=0.005)
    assert any(i[0] == "LRLC_ELASTIC_NO_SHALE" and i[2] == "LO" for i in out.issues)
    # rolling mode: too few shales near a depth fall back to the zone median
    res2, curves2, params2, zone2, _ = synth(gas_blocks=())
    res2 = res2.copy()
    keep = np.flatnonzero(res2["VSH"].to_numpy() > 0.5)
    res2.loc[keep[(keep > 300) & (keep < 420)], "VSH"] = 0.3   # remove a shale block of the zone
    out2 = elastic_screen(res2, curves2, {"UP": {"el_shale_window_ft": 20.0},
                                          "LO": {"el_shale_window_ft": 20.0}}, zone2)
    rows2 = {r["zone"]: r for r in out2.summary["baseline"]["zones"]}
    assert rows2["UP"]["fallback"] in ("zone", "well")


def test_no_shale_at_all_leaves_samples_unevaluable_and_flag_zero():
    res, curves, params, zone, _ = synth(gas_blocks=(3,))
    res = res.copy()
    res["VSH"] = 0.3
    out = elastic_screen(res, curves, params, zone)
    assert out.flag.sum() == 0
    assert out.summary["counts"]["unevaluable"] == int(res["NET_RES_FLAG"].sum())
    assert not np.isnan(out.flag.astype(float)).any()


def test_trend_unavailable_counts_unevaluable_and_never_nan():
    data = synth(gas_blocks=(3,))
    out = run(data, el_min_wet_n=10000)
    net = int(data[0]["NET_RES_FLAG"].sum())
    assert out.flag.sum() == 0
    assert out.summary["counts"]["unevaluable"] == net
    assert out.summary["wet"]["ai"] is None
    assert any(i[0] == "LRLC_ELASTIC_NO_WET" and i[3] is None for i in out.issues)
    narrow = run(synth(), el_min_phi_span=0.5)
    assert narrow.summary["counts"]["unevaluable"] == net and narrow.flag.sum() == 0


def test_unevaluable_samples_are_zero_where_phie_is_missing():
    data = synth(gas_blocks=(3,))
    gas = data[4]
    idx = np.flatnonzero(gas)[:5]
    data[0].loc[idx, "PHIE"] = np.nan
    out = run(data)
    assert out.flag[idx].sum() == 0
    assert out.summary["counts"]["unevaluable"] == 5


def test_wet_set_excludes_the_base_lrlc_flag():
    data = synth(gas_blocks=())
    res = data[0]
    clean = run(data)
    # candidates are wet-looking sand with a different trend: flagged samples must not reach the fit
    cand = np.flatnonzero((res["NET_RES_FLAG"] == 1).to_numpy())[:120]
    data2 = synth(gas_blocks=())
    r2, c2, p2, z2, _ = data2
    r2 = r2.copy()
    c2 = {k: np.array(v, copy=True) for k, v in c2.items()}
    c2["DT"][cand] = c2["DT"][cand] * 1.15              # slower, so lower AI, still Sw high
    r2.loc[cand, "LRLC_FLAG"] = 1
    excl = elastic_screen(r2, c2, p2, z2)
    assert excl.summary["wet"]["n"] == clean.summary["wet"]["n"] - len(cand)
    assert excl.summary["wet"]["ai"]["a0"] == pytest.approx(A0, rel=0.02)
    r3 = r2.copy()
    r3["LRLC_FLAG"] = 0
    assert elastic_screen(r3, c2, p2, z2).summary["wet"]["n"] == clean.summary["wet"]["n"]


def test_wet_interval_overrides_the_sw_rule():
    res, curves, params, zone, _ = synth(gas_blocks=(3,))
    depth = curves["DEPTH"]
    iv = [depth[0], depth[-1]]
    res = res.copy()
    res["SW"] = 0.1                                      # the Sw rule would find no wet sample
    sw_rule = elastic_screen(res, curves, params, zone)
    assert sw_rule.summary["wet"]["n"] == 0
    for z in params:
        params[z] = {"el_wet_interval": iv}
    out = elastic_screen(res, curves, params, zone)
    assert out.summary["wet"]["source"] == "interval" and out.summary["wet"]["n"] > 0


def test_zone_scope_trend_falls_back_to_the_well_trend():
    data = synth(gas_blocks=(3,))
    out = run(data, el_trend_scope="zone")
    assert out.summary["wet"]["scope"] == "zone"
    assert out.flag[data[4]].mean() > 0.95
    thin = run(data, el_trend_scope="zone", el_min_wet_n=200)    # each zone has under 200 wet samples
    assert thin.summary["counts"]["unevaluable"] == 0          # the well trend serves both zones
    assert any(i[0] == "LRLC_ELASTIC_NO_WET" and i[3] == "info" and i[2] in ("UP", "LO")
               for i in thin.issues)
    assert thin.flag[data[4]].mean() > 0.95


def test_inputs_are_not_modified():
    res, curves, params, zone, _ = synth(gas_blocks=(3,))
    res0 = res.copy(deep=True)
    curves0 = {k: v.copy() for k, v in curves.items()}
    zone0 = zone.copy()
    out = elastic_screen(res, curves, params, zone)
    pd.testing.assert_frame_equal(res, res0)
    assert all(np.array_equal(curves[k], curves0[k], equal_nan=True) for k in curves)
    assert (zone == zone0).all() and params == {"UP": {}, "LO": {}}
    out.flag[:] = 1                                       # outputs are independent arrays
    assert np.array_equal(res["NET_RES_FLAG"].to_numpy(), res0["NET_RES_FLAG"].to_numpy())


def test_unzoned_label_and_dz_thickness():
    res, curves, params, zone, gas = synth(gas_blocks=(3,))
    keys = np.full(len(res), UNZONED, dtype=object)
    out = elastic_screen(res, curves, {UNZONED: {}}, keys)
    assert [z["zone"] for z in out.summary["zones"]] == ["WELL"]
    assert out.summary["zones"][0]["thickness_flag_ft"] == pytest.approx(0.5 * out.flag.sum())
    assert set(out.summary) >= {"curves", "params", "baseline", "wet", "zones", "counts"}
