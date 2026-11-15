"""Resolved shale beds and the laminated-zone check.

Interbedded sand and shale that the logs resolve is not a laminated sand: in a thick shale bed
Thomas-Stieber gives Vlam = Vsh (the laminar line), which used to make the zone "laminated" and
drop the deconvolution. The check now leaves shale beds at least one response width thick
(plus a margin on each side, and with a minimum retained share) out of the statistic. The
synthetic wells here are built in the test (alternating beds, optional log resolution as a
boxcar on GR and density, optional noise on GR); each goes through the real pipeline.
"""
import numpy as np
import pandas as pd
import pytest
from scipy.ndimage import gaussian_filter1d, uniform_filter1d

from modules.lrlc import l2
from modules.lrlc.config import GUARD_DEFAULTS
from modules.lrlc.guard import guard_summary, zone_state
from modules.lrlc.thomas_stieber import resolved_runs, widen_mask, zone_stats
from modules.pipeline import run_pipeline
from tests.test_lrlc_pipeline import lrlc_p

PHI_MAX, PHI_SH = 0.30, 0.08
STEP = 0.5
PARAMS = {
    "vsh_baseline_method": "Custom (Manual)", "gr_min_manual": 20.0, "gr_max_manual": 120.0,
    "sw_methods": ["Archie"], "sw_primary_method": "Archie",
    "rw": 0.05, "rw_mode": "manual", "rsh": 2.0, "rsh_mode": "manual", "a": 1.0, "m": 2.0, "n": 2.0,
}
MAPPING = {"GR": "GR", "RHOB": "RHOB", "NPHI": "None", "DT": "None", "RT": "RT"}


def _beds_to_frame(vsh, phit, top=1000.0, smooth_ft=0.0, kernel="box", noise=0.0, seed=1):
    vsh, phit = np.asarray(vsh, float), np.asarray(phit, float)
    depth = top + STEP * np.arange(len(vsh))
    gr = 20.0 + 100.0 * vsh
    rhob = 2.65 - 1.65 * phit
    if smooth_ft > 0:                       # log resolution: the same kernel on both curves
        if kernel == "gauss":
            sg = smooth_ft / 2.3548 / STEP
            gr, rhob = gaussian_filter1d(gr, sg, mode="nearest"), gaussian_filter1d(rhob, sg, mode="nearest")
        else:
            w = max(1, int(round(smooth_ft / STEP)))
            gr, rhob = uniform_filter1d(gr, w, mode="nearest"), uniform_filter1d(rhob, w, mode="nearest")
    if noise > 0:
        gr = gr + 100.0 * noise * np.random.default_rng(seed).standard_normal(len(gr))
    return pd.DataFrame({"DEPTH": depth, "GR": gr, "RHOB": rhob, "RT": 10.0})


def bed_well(beds, vsh_shale=0.90, vsh_sand=0.03, **kw):
    """beds: (thickness_ft, "sand" | "shale"); sand on the dispersed line, shale on the laminar one."""
    sand = (vsh_sand, PHI_MAX - vsh_sand * (1 - PHI_SH))
    shale = (vsh_shale, (1 - vsh_shale) * PHI_MAX + vsh_shale * PHI_SH)
    vsh, phit = [], []
    for thickness, kind in beds:
        v, p = sand if kind == "sand" else shale
        n = int(round(thickness / STEP))
        vsh += [v] * n
        phit += [p] * n
    return _beds_to_frame(vsh, phit, **kw)


def alternating(thick_sand, thick_shale, total=120.0, **kw):
    beds, z = [], 0.0
    while z < total - 1e-9:
        beds += [(thick_sand, "sand"), (thick_shale, "shale")]
        z += thick_sand + thick_shale
    return bed_well(beds, **kw)


def sine_laminated(shale_beds=None):
    """Laminated sand: Vsh = Vlam on the laminar line, 0.12 to 0.48; optional resolved shale."""
    d = np.arange(1000.0, 1100.0, 0.5)
    v = 0.12 + 0.36 * (0.5 + 0.5 * np.sin(d / 3.0))
    if shale_beds == "one 20 ft":
        v[(d >= 1040) & (d < 1060)] = 0.90
    elif shale_beds == "10/10":
        v = np.where(((d - 1000) // 10) % 2 == 1, 0.90, v)
    ph = (1 - v) * PHI_MAX + v * PHI_SH
    return pd.DataFrame({"DEPTH": d, "GR": 20 + 100 * v, "RHOB": 2.65 - 1.65 * ph, "RT": 5.0})


def run_ts(frame, guard=None):
    lrlc = lrlc_p(steps=[], zones=(), phi_max=PHI_MAX, phi_sh=PHI_SH)
    lrlc["thomas_stieber"] = {"enabled": True}
    if guard:
        lrlc["guard"] = dict(guard)
    return run_pipeline(frame.copy(), dict(MAPPING), {**PARAMS, "lrlc": lrlc})


def verdict(frame, guard=None):
    """``(laminated, guard row, ts row)`` of the one zone of the well."""
    _, summary = run_ts(frame, guard)
    g = summary["lrlc"]["guard"]["zones"][0]
    t = summary["lrlc"]["ts"]["zones"][0]
    return g["laminated"], g, t


THIN_SHALE = [(20, "shale"), (3, "sand")] * 6

# name -> (frame builder, expected: laminated by the new rule)
CASES = {
    "1a 10/10 ft sharp": (lambda: alternating(10, 10), False),
    "1d 10/10 ft, 2 ft log resolution": (lambda: alternating(10, 10, smooth_ft=2.0), False),
    "1g 10/10 ft, 4 ft log resolution": (lambda: alternating(10, 10, smooth_ft=4.0), False),
    "1i 10/10 ft, 2 ft resolution, GR noise": (
        lambda: alternating(10, 10, smooth_ft=2.0, noise=0.04), False),
    "2a laminated sand (sine)": (sine_laminated, True),
    "2c 0.5/0.5 ft laminae through 2 ft resolution": (
        lambda: alternating(0.5, 0.5, 100, smooth_ft=2.0), True),
    "2f 1.5/0.5 ft laminae through 2 ft resolution": (
        lambda: alternating(1.5, 0.5, 100, smooth_ft=2.0), True),
    "3a 4/4 ft sharp (one response width)": (lambda: alternating(4, 4), False),
    "3c 4/4 ft through 2 ft resolution": (lambda: alternating(4, 4, smooth_ft=2.0), True),
    "3d 2/2 ft through 2 ft resolution": (lambda: alternating(2, 2, smooth_ft=2.0), True),
    "3e clean sand with one 20 ft shale, sharp": (
        lambda: bed_well([(40, "sand"), (20, "shale"), (40, "sand")]), False),
    "3f clean sand with one 20 ft shale, 2 ft resolution": (
        lambda: bed_well([(40, "sand"), (20, "shale"), (40, "sand")], smooth_ft=2.0), False),
    "3i mostly shale with 3 ft sands, sharp": (lambda: bed_well(THIN_SHALE), False),
    "3j mostly shale with 3 ft sands, 2 ft resolution": (
        lambda: bed_well(THIN_SHALE, smooth_ft=2.0), False),
    "3m laminated sand with one 20 ft shale": (lambda: sine_laminated("one 20 ft"), True),
    "3n laminated sand interbedded 10/10 with shale": (lambda: sine_laminated("10/10"), True),
    "3o clean sand with 3 ft shale beds": (
        lambda: bed_well([(20, "sand"), (3, "shale")] * 5, smooth_ft=2.0), True),
    "3p clean sand with 5 ft shale beds": (
        lambda: bed_well([(25, "sand"), (5, "shale")] * 4, smooth_ft=2.0), True),
}


@pytest.mark.parametrize("name", list(CASES))
def test_laminated_class_of_the_synthetic_cases(name):
    build, expected = CASES[name]
    laminated, guard_row, ts_row = verdict(build())
    assert laminated is expected, name
    # the guard and the Diagnosis statistic read the same numbers
    assert guard_row["lam_share"] == pytest.approx(ts_row["lam_share"], nan_ok=True)


@pytest.mark.parametrize("name", ["1a 10/10 ft sharp", "1d 10/10 ft, 2 ft log resolution",
                                  "3e clean sand with one 20 ft shale, sharp"])
def test_the_rule_off_gives_the_old_class(name):
    laminated, guard_row, _ = verdict(CASES[name][0](), {"exclude_resolved": False})
    assert laminated is True
    assert "resolved_ft" not in guard_row


def test_a_zone_emptied_by_the_rule_is_classified_and_not_laminated():
    _, summary = run_ts(alternating(10, 10))
    codes = [i["code"] for i in summary["issues"]]
    assert "LRLC_GUARD_NO_TS" not in codes
    g = summary["lrlc"]["guard"]
    row = g["zones"][0]
    assert row["laminated"] is False and row["class_changed"] is True
    assert row["resolved_ft"] == pytest.approx(60.0, abs=1.0)       # six 10 ft shale beds
    assert g["resolved_beds_left_out"] is True


def test_the_summary_is_unchanged_when_nothing_is_left_out():
    _, summary = run_ts(sine_laminated())
    g = summary["lrlc"]["guard"]
    assert "resolved_beds_left_out" not in g
    assert all("resolved_ft" not in z and "class_changed" not in z for z in g["zones"])


def test_the_class_counts_leave_the_resolved_beds_out():
    _, summary = run_ts(bed_well([(40, "sand"), (20, "shale"), (40, "sand")]))
    counts = summary["lrlc"]["ts"]["zones"][0]["class_counts"]
    _, off = run_ts(bed_well([(40, "sand"), (20, "shale"), (40, "sand")]),
                    {"exclude_resolved": False})
    counts_off = off["lrlc"]["ts"]["zones"][0]["class_counts"]
    assert sum(counts.values()) < sum(counts_off.values())
    assert counts["1"] < counts_off["1"]


def test_the_edge_margin_setting():
    frame = alternating(10, 10, smooth_ft=2.0)
    assert verdict(frame)[0] is False
    # without the margin and the minimum share the smeared boundaries still read laminated
    laminated, _, _ = verdict(frame, {"edge_ft": 0.0, "min_frac": 0.0})
    assert laminated is True


# ---- the statistic itself ------------------------------------------------------------------
RULE = {"shale_vsh": 0.80, "run_ft": 4.0, "edge_ft": 3.0, "min_frac": 0.10}


def _stats(vsh, vlam, depth, labels=None, rule=RULE):
    vsh, vlam = np.asarray(vsh, float), np.asarray(vlam, float)
    return zone_stats(vsh, vlam, np.ones(len(vsh), int), np.full(len(vsh), 0.5), labels, 0.10,
                      depth=np.asarray(depth, float), resolved=rule)


def test_runs_break_at_depth_gaps_and_zone_changes():
    depth = np.arange(0.0, 6.0, 0.5)
    vsh = np.full(12, 0.9)
    dz = np.full(12, 0.5)
    keys = np.array(["A"] * 12, dtype=object)
    assert resolved_runs(vsh, depth, dz, keys, 0.8, 4.0).all()
    gap = depth.copy()
    gap[6:] += 20.0                         # a 20 ft gap: two 3 ft runs, each too thin
    assert not resolved_runs(vsh, gap, dz, keys, 0.8, 4.0).any()
    two = np.array(["A"] * 6 + ["B"] * 6, dtype=object)
    assert not resolved_runs(vsh, depth, dz, two, 0.8, 4.0).any()
    vsh2 = vsh.copy()
    vsh2[6] = np.nan                        # a missing Vsh ends the run
    assert not resolved_runs(vsh2, depth, dz, keys, 0.8, 4.0).any()


def test_widen_mask_stays_inside_the_zone():
    depth = np.arange(0.0, 10.0, 0.5)
    keys = np.array(["A"] * 10 + ["B"] * 10, dtype=object)
    mask = np.zeros(20, dtype=bool)
    mask[8:10] = True
    out = widen_mask(mask, depth, keys, 1.0)
    assert out[6:10].all() and not out[10:].any() and not out[:6].any()


def test_a_run_of_exactly_the_response_width_counts():
    depth = np.arange(0.0, 8.0, 0.5)
    vsh = np.where((depth >= 2) & (depth < 6), 0.9, 0.3)        # a 4 ft bed
    vlam = vsh.copy()
    st = _stats(vsh, vlam, depth)[list(_stats(vsh, vlam, depth))[0]]
    assert st["excluded_ft"] == pytest.approx(4.0)
    thin = _stats(vsh, vlam, depth, rule={**RULE, "run_ft": 4.5})
    assert next(iter(thin.values()))["excluded_ft"] == 0.0


def test_the_rule_needs_depth():
    vsh = np.full(10, 0.9)
    st = zone_stats(vsh, vsh, np.ones(10, int), np.full(10, 0.5), None, 0.1, resolved=RULE)
    assert next(iter(st.values()))["n"] == 10 and "excluded_ft" not in next(iter(st.values()))


def test_zone_state_of_an_emptied_zone():
    state = zone_state({"lam_share": float("nan"), "mean_vlam": float("nan"), "n": 0,
                        "emptied": True, "excluded_ft": 10.0, "lam_share_all": 1.0,
                        "mean_vlam_all": 0.9}, GUARD_DEFAULTS)
    assert state["classified"] is True and state["laminated"] is False
    assert state["laminated_all"] is True
    plain = zone_state({"lam_share": float("nan"), "mean_vlam": float("nan"), "n": 0},
                       GUARD_DEFAULTS)
    assert plain["classified"] is False
    row = guard_summary({"A": state}, {})["zones"][0]
    assert row["resolved_ft"] == 10.0 and row["class_changed"] is True


def test_the_rule_reads_the_deconvolution_width_even_when_it_is_off():
    lrlc = {"resolved": {"default": {"dec_fwhm_ft": 6.0, "rt_steps": []}, "zones": {}}}
    rule = l2.resolved_rule(lrlc)
    assert rule["run_ft"] == 6.0 and rule["shale_vsh"] == 0.80
    assert rule["edge_ft"] == 3.0 and rule["min_frac"] == 0.10
    assert l2.resolved_rule({**lrlc, "guard": {"exclude_resolved": False}}) is None
