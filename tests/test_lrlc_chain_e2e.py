"""The whole LRLC Rt chain on one synthetic well with known answers (``tests/lrlc_synth.py``).

THIN (thin sands, all four steps), LAM (laminations, guard drops the deconvolution) and GOFF (the
same laminations, read again with the guard off). Tolerances are design values calibrated on the
generated well; the realised values at the time of writing are given next to each one (sand
interiors of THIN, 261 samples).
"""
import numpy as np
import pytest

from modules import uncertainty as U
from modules.lrlc import chain
from modules.lrlc.report import steps_frame, zones_frame
from modules.pipeline import run_pipeline
from tests import lrlc_synth as L

ALL_STEPS = {"THIN": ["decon", "invasion", "laminated", "pyrite"], "LAM": ["decon", "laminated"],
             "GOFF": ["decon"]}
NO_STEPS = {"THIN": [], "LAM": [], "GOFF": []}


@pytest.fixture(scope="module")
def well():
    return L.build_chain_well()


def run(well, steps=None, auto=False, **kw):
    params = {**L.PARAMS, **({"rw_mode": "auto", "rsh_mode": "auto"} if auto else {})}
    lrlc = L.lrlc_params(ALL_STEPS if steps is None else steps, **kw)
    return run_pipeline(well.data.copy(), dict(well.mapping), {**params, "lrlc": lrlc},
                        formation_tops=well.tops)


@pytest.fixture(scope="module")
def main(well):
    return run(well)


def codes(summary):
    return [i["code"] for i in summary["issues"]]


def rel_err(got, truth):
    return np.abs(np.asarray(got, dtype=float) / np.asarray(truth, dtype=float) - 1.0)


def test_the_well_is_what_the_docstring_says(well):
    depth = well.data["DEPTH"].to_numpy()
    assert depth[0] == 1000.0 and depth[-1] == 1899.5 and len(well.beds) >= 20
    assert {z for z, _, _ in L.ZONES} == {"THIN", "LAM", "GOFF"}
    assert well.sand_interior().sum() > 200
    # known answers: the deep curve is far from the true Rt in the sands before any correction
    inner = well.sand_interior()
    assert np.median(rel_err(well.data["RT"].to_numpy()[inner], well.rt_true[inner])) > 0.3


# ---- THIN: every step recovers its part of the known truth -----------------------------------
def test_each_step_recovers_its_truth_on_sand_interiors(well, main):
    r, _ = main
    inner = well.sand_interior(1.0)
    seen = {}
    for column, step in (("RT_DECON", "decon"), ("RT_INV", "invasion"), ("RT_SAND", "laminated"),
                         ("RT_PYR", "pyrite")):
        got = r[column].to_numpy()[inner]
        err = rel_err(got, well.stages[step][inner])
        assert np.isnan(got).mean() < 0.10, column
        seen[column] = (np.nanmedian(err), np.nanpercentile(err, 90))
    # realised: decon 0.046 / 0.08, invasion 0.073 / 0.2, laminated 0.088 / 0.5, pyrite 0.094 / 0.4
    assert seen["RT_DECON"][0] < 0.10 and seen["RT_DECON"][1] < 0.25
    assert seen["RT_INV"][0] < 0.15
    assert seen["RT_PYR"][0] < 0.15


def test_final_rt_and_sw_beat_the_measured_values(well, main):
    r, _ = main
    inner = well.sand_interior(1.0)
    err = rel_err(r["RT_SW"].to_numpy()[inner], well.rt_true[inner])
    measured = rel_err(well.data["RT"].to_numpy()[inner], well.rt_true[inner])
    # realised: median 0.093, 90th percentile 0.31 (measured: 0.45)
    assert np.nanmedian(err) < 0.15 and np.nanpercentile(err, 90) < 0.40
    assert np.nanmedian(err) < np.median(measured) / 3
    phie = r["PHIE"].to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        sw_true = np.minimum(np.sqrt(L.A * L.RW / (phie ** L.M * well.rt_true)), 1.0)
    sw_err = np.abs(r["SW"].to_numpy() - sw_true)[inner]
    base_err = np.abs(r["SW_BASE"].to_numpy() - sw_true)[inner]
    # realised: Sw error 0.0095 (median), the Sw from the measured Rt 0.078
    assert np.nanmedian(sw_err) < 0.03 and np.nanmedian(sw_err) < np.nanmedian(base_err) / 2


def test_chain_order_and_provenance(well, main):
    r, s = main
    thin = [c for c in s["lrlc"]["chain"] if c["zone"] == "THIN"]
    assert [(c["step"], c["curve"], c["from"]) for c in thin] == [
        ("decon", "RT_DECON", "RT"), ("invasion", "RT_INV", "RT_DECON"),
        ("laminated", "RT_SAND", "RT_INV"), ("pyrite", "RT_PYR", "RT_SAND")]
    chain_text = " <- ".join([c["curve"] for c in reversed(thin)] + ["RT"])
    assert chain_text == "RT_PYR <- RT_SAND <- RT_INV <- RT_DECON <- RT"
    mask = well.zone_mask("THIN")
    np.testing.assert_array_equal(r["RT_SW"].to_numpy()[mask], r["RT_PYR"].to_numpy()[mask])
    np.testing.assert_array_equal(r["RT"].to_numpy(), well.data["RT"].to_numpy())
    assert {"RT_DECON", "RT_INV", "RT_SAND", "RT_PYR", "RT_SW", "SW_BASE"} <= set(r.columns)


def test_issue_codes_of_the_thin_zone(main):
    _, s = main
    found = codes(s)
    assert "LRLC_INV_DECON_MISMATCH" in found
    combined = [i for i in s["issues"] if i["code"] == "LRLC_GUARD_COMBINED"]
    assert combined and all(i["severity"] == "info" for i in combined)
    assert "LRLC_GUARD_NO_TS" in found


def test_thin_zone_with_endpoints_is_classified_and_still_runs_the_deconvolution(well, main):
    """Resolved shale beds between the sands no longer make THIN laminated."""
    r0, _ = main
    r, s = run(well, thin_endpoints=True)
    thin = well.zone_mask("THIN")
    zones = {z["zone"]: z for z in s["lrlc"]["decon"]["zones"]}
    assert zones["THIN"]["status"] == "ran"
    assert r["RT_DECON"][thin].notna().mean() > 0.9
    guard = {z["zone"]: z for z in s["lrlc"]["guard"]["zones"]}
    assert guard["THIN"]["laminated"] is False and guard["THIN"]["resolved_ft"] > 50.0
    assert guard["THIN"]["class_changed"] is True
    assert s["lrlc"]["guard"]["resolved_beds_left_out"] is True
    assert not [i for i in s["issues"] if i["code"] == "LRLC_GUARD_NO_TS"
                and "THIN" in i["text"]]
    assert not [i for i in s["issues"] if i["code"] in ("LRLC_GUARD_BLOCKED", "LRLC_GUARD_HINT")
                and "THIN" in i["text"]]
    # the deconvolved Rt is the one the run without end-points gives
    np.testing.assert_allclose(r["RT_DECON"].to_numpy()[thin], r0["RT_DECON"].to_numpy()[thin],
                               equal_nan=True)
    # LAM stays laminated (the laminations are not resolved shale beds)
    assert guard["LAM"]["laminated"] is True and "resolved_ft" not in guard["LAM"]


# ---- LAM: the guard drops the deconvolution; the laminated step recovers the truth ---------
def test_guard_drops_decon_in_laminated_zones(well, main):
    r, s = main
    lam = well.zone_mask("LAM")
    assert r["RT_DECON"][lam].isna().all()
    assert "LRLC_GUARD_BLOCKED" in codes(s)
    zones = {z["zone"]: z for z in s["lrlc"]["decon"]["zones"]}
    assert zones["LAM"]["status"] == "guard_dropped_laminated"
    assert zones["GOFF"]["status"] == "guard_dropped_laminated"
    assert zones["THIN"]["status"] == "ran"
    lam_chain = [c for c in s["lrlc"]["chain"] if c["zone"] == "LAM"]
    assert [(c["step"], c["from"]) for c in lam_chain] == [("laminated", "RT")]
    err = rel_err(r["RT_SW"].to_numpy()[lam], well.rt_true[lam])
    assert np.nanmedian(err) < 0.05 and np.nanpercentile(err, 95) < 0.15      # 0.03 / 0.08


# ---- GOFF: guard off, the step runs and warns ---------------------------------------------
def test_guard_off_runs_the_step_and_warns(well):
    r, s = run(well, guard=False)
    goff = well.zone_mask("GOFF")
    assert np.isfinite(r["RT_DECON"].to_numpy()[goff]).mean() > 0.9
    found = codes(s)
    assert "LRLC_GUARD_WARNED" in found and "LRLC_GUARD_BLOCKED" not in found
    assert {z["zone"]: z["status"] for z in s["lrlc"]["decon"]["zones"]}["GOFF"] == "ran"


# ---- shoulder-bed marker (G4), with and without Thomas-Stieber -----------------------------
@pytest.mark.parametrize("thomas_stieber", [True, False])
def test_marked_rt_drops_decon_in_thin(well, thomas_stieber):
    lrlc = L.lrlc_params(ALL_STEPS, marked=True)
    lrlc["thomas_stieber"] = {"enabled": thomas_stieber}
    r, s = run_pipeline(well.data.copy(), dict(well.mapping), {**L.PARAMS, "lrlc": lrlc},
                        formation_tops=well.tops)
    thin = well.zone_mask("THIN")
    assert r["RT_DECON"][thin].isna().all()
    zones = {z["zone"]: z for z in s["lrlc"]["decon"]["zones"]}
    assert zones["THIN"]["status"] == "guard_dropped_shoulder"
    steps = [c["step"] for c in s["lrlc"]["chain"] if c["zone"] == "THIN"]
    assert steps == ["invasion", "laminated", "pyrite"]


# ---- what the chain must not touch ---------------------------------------------------------
def test_rw_and_rsh_estimates_ignore_the_steps(well):
    _, with_steps = run(well, auto=True)
    _, without = run(well, steps=NO_STEPS, auto=True)
    for key in ("rw", "rsh", "rw_source", "rsh_source"):
        assert with_steps[key] == without[key], key


def test_deconvolution_is_solved_once_per_well(well, monkeypatch):
    calls = []
    real = chain.DERIVES["decon_well"]

    def counting(**kw):
        calls.append(1)
        return real.fn(**kw)

    monkeypatch.setitem(chain.DERIVES, "decon_well",
                        chain.DeriveSpec(real.name, real.scope, counting, real.outputs))
    run(well)
    assert len(calls) == 1


def test_fallback_previous_keeps_the_input_where_a_step_fails(well, main):
    nan_run, _ = main
    prev_run, _ = run(well, fallback="previous")
    thin = well.zone_mask("THIN")
    nan_missing = nan_run["RT_SW"][thin].isna().sum()
    prev_missing = prev_run["RT_SW"][thin].isna().sum()
    assert nan_missing > 0 and prev_missing < nan_missing
    # a sample that every step valued gives the same answer in both runs
    both = nan_run["RT_SW"].notna().to_numpy() & thin
    np.testing.assert_allclose(prev_run["RT_SW"].to_numpy()[both], nan_run["RT_SW"].to_numpy()[both])


# ---- the response width and the report ------------------------------------------------------
def test_width_sensitivity_is_reported_for_the_thin_zone(main):
    _, s = main
    zone = [z for z in s["lrlc"]["decon"]["zones"] if z["zone"] == "THIN"][0]
    sens = zone["width_sensitivity"]
    assert sens["widths_ft"] == pytest.approx([3.2, 4.0, 5.0])
    ratios = sens["median_ratio"]
    assert ratios[0] < ratios[1] < ratios[2] and ratios[1] > 1.2     # realised 1.35 / 1.54 / 2.1


def test_report_frames_describe_the_run(well, main):
    r, s = main
    triple = [("CHAIN", s, r)]
    zones = zones_frame(triple).set_index("Zone")
    assert {"THIN", "LAM", "GOFF", "(well)"} <= set(zones.index)
    assert zones.loc["THIN", "Decon_status"] == "ran"
    assert zones.loc["LAM", "Decon_status"] == "guard_dropped_laminated"
    assert zones.loc["THIN", "Rt_source"].startswith("RT_PYR")
    steps = steps_frame(triple)
    thin = steps[steps["Zone"] == "THIN"].sort_values("Order")
    assert list(thin["Step"]) == ["decon", "invasion", "laminated", "pyrite"]


# ---- Monte Carlo base case equals the deterministic run -------------------------------------
def test_monte_carlo_base_case_matches_with_all_steps(well):
    params = {**L.PARAMS, "lrlc": L.lrlc_params(ALL_STEPS)}
    fw = U.freeze_well("chain", "chain", well.data.copy(), dict(well.mapping), params, well.tops)
    got = U.evaluate(fw, {})
    s = fw.base_summary
    for key in ("hcpv_net_pay", "hcpv_net_res", "net_pay", "avg_phie_pay", "avg_sw_pay"):
        np.testing.assert_allclose(got["well"][key], s[key], rtol=1e-12, atol=0,
                                   equal_nan=True, err_msg=key)
