"""LRLC in the pipeline: off means untouched, the Rt chain, the segment merge, the summary."""
import math

import numpy as np
import pandas as pd
import pytest

from modules import param_scopes as ps
from modules.issue_codes import ISSUE_CODES
from modules.lrlc.config import AUX_ROLES, LRLC_PARAM_DEFAULTS
from modules.pipeline import PARAM_DEFAULTS, run_pipeline
from tests.golden.cases import build_case
from tests.lrlc_teststeps import register_test_steps  # noqa: F401

BASE_NEW = {"LRLC_SCORE", "LRLC_FLAG", "BVW", "WATER_FREE_FLAG"}
FLAG_COLUMNS = ("LRLC_SCORE", "LRLC_FLAG", "WATER_FREE_FLAG")


def lrlc_p(steps=None, zone_steps=None, rt_cutoff=False, curves=None, fallback="nan",
           zones=("UPPER", "LOWER"), **ladder):
    """A ``p["lrlc"]`` payload as ``AppModel.params_for_well`` builds it (5.3)."""
    default = {**LRLC_PARAM_DEFAULTS, "rt_steps": list(steps or []), "rt_fallback": fallback,
               **ladder}
    zone_rows = {z: {**default, "rt_steps": list((zone_steps or {}).get(z, steps or []))}
                 for z in zones}
    return {"enabled": True, "screening": {"use_gas_flag": True, "use_rs": True},
            "rt_cutoff": {"enabled": rt_cutoff}, "movable": {"swirr_column": "SWIRR"},
            "curves": {**{r: None for r in AUX_ROLES}, "RS": "RS", **(curves or {})},
            "resolved": {"default": default, "zones": zone_rows}}


@pytest.fixture(scope="module")
def case():
    data, mapping, params, tops = build_case("lrlc_screening")
    params = dict(params)
    params.pop("lrlc")
    return data, mapping, params, tops


def planned(params, zone="LOWER"):
    plan = ps.zone_plan({**PARAM_DEFAULTS, **params}, None,
                        {zone: {"m": ps.make_entry(ps.MANUAL, 1.8)}}, None, ("UPPER", "LOWER"))
    return {**params, "zone_plan": plan}


def run(case, lrlc=None, tops=True, **over):
    data, mapping, params, ftops = case
    params = {**params, **over}
    if lrlc is not None:
        params["lrlc"] = lrlc
    return run_pipeline(data.copy(), dict(mapping), params, formation_tops=ftops if tops else None)


def codes(summary):
    return [i["code"] for i in summary["issues"]]


def assert_same(a, b, where="summary"):
    if isinstance(a, dict):
        assert set(a) == set(b), where
        for k in a:
            assert_same(a[k], b[k], f"{where}.{k}")
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b), where
        for i, (x, y) in enumerate(zip(a, b)):
            assert_same(x, y, f"{where}[{i}]")
    elif isinstance(a, float) and math.isnan(a):
        assert isinstance(b, float) and math.isnan(b), where
    else:
        assert a == b, where


def assert_unchanged(off, on):
    """Everything the run produced without LRLC is bit-identical with it."""
    (r0, s0), (r1, s1) = off, on
    pd.testing.assert_frame_equal(r1[list(r0.columns)], r0, check_exact=True)
    skip = {"issues", "warnings", "lrlc"}
    s1 = dict(s1)
    # An active correction adds the before columns and may add a diagnosis note.
    s1["zones"] = [{k: v for k, v in z.items() if not k.endswith("_base")}
                   for z in s1.get("zones", [])]
    if "zone_diagnostics" in s1:
        s1["zone_diagnostics"] = {z: {k: v for k, v in d.items() if k != "lrlc_note"}
                                  for z, d in s1["zone_diagnostics"].items()}
    assert_same({k: v for k, v in s1.items() if k not in skip},
                {k: v for k, v in s0.items() if k not in skip})


# ---- off means untouched ----------------------------------------------------------------
def test_off_has_no_lrlc_key_column_or_issue(case):
    r, s = run(case)
    assert "lrlc" not in s
    assert not ({"RT_SW", "RT_CUT", *BASE_NEW} & set(r.columns))
    assert not [c for c in codes(s) if c.startswith("LRLC")]


def test_falsy_lrlc_param_is_off(case):
    r, s = run(case, lrlc={})
    assert "lrlc" not in s and "LRLC_FLAG" not in r.columns


# ---- on without a step --------------------------------------------------------------------
@pytest.mark.parametrize("zoned", [True, False])
def test_on_no_step_adds_only_documented_columns_and_changes_nothing(case, zoned):
    off = run(case, tops=zoned)
    on = run(case, lrlc_p(), tops=zoned)
    assert set(on[0].columns) - set(off[0].columns) == BASE_NEW
    assert_unchanged(off, on)
    block = on[1]["lrlc"]
    assert block["version"] == 1 and block["chain"] == []
    assert block["counts"]["rt_sw_written"] is False
    assert "RT_SW" not in on[0].columns and "rt_cutoff" not in block


def test_on_no_step_with_rt_cutoff(case):
    off = run(case)
    r, s = run(case, lrlc_p(rt_cutoff=True))
    assert set(r.columns) - set(off[0].columns) == BASE_NEW | {"RT_CUT"}
    assert_unchanged(off, (r, s))
    cut = s["lrlc"]["rt_cutoff"]
    assert cut["model"] == "Simandoux" and cut["no_root"] == 0 and cut["eligible"] > 0
    assert {row["zone"] for row in cut["zones"]} == {"UPPER", "LOWER"}


def test_rt_cut_reproduces_target_sw_through_the_primary_model(case):
    """Simandoux (n = 2) closed form at Rt = RT_CUT gives the target Sw (same inputs as SW)."""
    r, s = run(case, lrlc_p(rt_cutoff=True))
    p = {**PARAM_DEFAULTS, **case[2]}
    ok = r["RT_CUT"].notna() & (r["PHIE"] > 0.02)
    assert ok.sum() > 20
    sw, phie, vsh = p["sw_cutoff"], r.loc[ok, "PHIE"], r.loc[ok, "VSH"]
    inverse = (phie ** p["m"] * sw ** 2 / (p["a"] * p["rw"]) + vsh * sw / p["rsh"])
    np.testing.assert_allclose(1.0 / r.loc[ok, "RT_CUT"], inverse, rtol=1e-6)


def test_screening_summary_and_flag_types(case):
    r, s = run(case, lrlc_p(rt_cutoff=True, zones=("UPPER", "LOWER")))
    for name in FLAG_COLUMNS:
        assert pd.api.types.is_integer_dtype(r[name]), name
    assert set(r["LRLC_FLAG"].unique()) <= {0, 1}
    assert r["LRLC_SCORE"].between(0, 6).all()
    block = s["lrlc"]
    assert block["counts"]["n"] == len(r)
    assert block["counts"]["flag"] == int(r["LRLC_FLAG"].sum())
    assert block["counts"]["water_free"] == int(r["WATER_FREE_FLAG"].sum())
    rows = {row["zone"]: row for row in block["screening"]["zones"]}
    assert set(rows) == {"UPPER", "LOWER"}
    for zone, row in rows.items():
        assert row["n"] == int((r["ZONE"] == zone).sum())
        assert row["rt_cut"] > 0
    assert block["screening"]["unavailable"] == []
    assert block["movable"]["swirr_method"] == s["swirr_method"]


def test_zone_scoped_threshold_reaches_the_screen(case):
    tight = run(case, lrlc_p(screen_rt_max=0.3))[0]
    assert tight["LRLC_FLAG"].sum() == 0                  # nothing reads below 0.3 ohm.m
    lrlc = lrlc_p(screen_rt_max=0.3)
    lrlc["resolved"]["zones"]["LOWER"]["screen_rt_max"] = 50.0
    r, s = run(case, lrlc)
    assert r.loc[r["ZONE"] == "UPPER", "LRLC_FLAG"].sum() == 0
    assert r.loc[r["ZONE"] == "LOWER", "LRLC_FLAG"].sum() > 0
    assert s["lrlc"]["screening"]["thresholds"]["LOWER"]["screen_rt_max"] == 50.0


def test_unavailable_criterion_is_reported(case):
    r, s = run(case, lrlc_p())
    data = case[0].drop(columns=["RS"])
    r2, s2 = run_pipeline(data, dict(case[1]), {**case[2], "lrlc": lrlc_p()},
                          formation_tops=case[3])
    assert s2["lrlc"]["screening"]["unavailable"] == ["HC"]
    assert "LRLC_CRITERION_UNAVAILABLE" in codes(s2)
    assert "LRLC_CRITERION_UNAVAILABLE" not in codes(s)


# ---- the Rt chain ---------------------------------------------------------------------------
def test_identity_step_keeps_sw_bit_identical(case, register_test_steps):
    off = run(case)
    r, s = run(case, lrlc_p(steps=["test_identity"]))
    assert_unchanged(off, (r, s))
    pd.testing.assert_series_equal(r["RT_SW"], r["RT"], check_exact=True, check_names=False)
    pd.testing.assert_series_equal(r["RT_ID"], r["RT"], check_exact=True, check_names=False)
    chain = s["lrlc"]["chain"]
    assert {rec["zone"] for rec in chain} == {"UPPER", "LOWER"}
    assert all(rec["step"] == "test_identity" and rec["from"] == "RT" for rec in chain)
    assert s["lrlc"]["counts"]["rt_sw_written"] is True


def test_scale_step_changes_sw_and_feeds_every_model(case, register_test_steps):
    off = run(case, sw_methods=["Archie", "Indonesian", "Simandoux", "Waxman-Smits", "Dual-Water"])
    r, s = run(case, lrlc_p(steps=["test_scale"]),
               sw_methods=["Archie", "Indonesian", "Simandoux", "Waxman-Smits", "Dual-Water"])
    np.testing.assert_array_equal(r["RT_SW"], 2.0 * r["RT"])
    np.testing.assert_array_equal(r["RT_X2"], 2.0 * r["RT"])
    for column in ("SW_ARCHIE", "SW_INDO", "SW_SIMAN", "SW_WS", "SW_DW"):
        assert not np.array_equal(r[column].to_numpy(), off[0][column].to_numpy()), column
        assert (r[column] <= off[0][column] + 1e-12).all(), column     # more Rt, less water
    assert (r["SW"] < off[0]["SW"]).any()
    np.testing.assert_array_equal(r["RT"], off[0]["RT"])               # measured RT never modified


def test_chain_order_and_provenance(case, register_test_steps):
    r, s = run(case, lrlc_p(steps=["test_scale", "test_identity"]), tops=False)
    chain = s["lrlc"]["chain"]
    assert [rec["step"] for rec in chain] == ["test_identity", "test_scale"]   # by order, not list
    assert [rec["from"] for rec in chain] == ["RT", "RT_ID"]
    assert chain[0]["zone"] is None and chain[0]["segment"] == "well"
    assert chain[0]["n_invalid"] == 0 and chain[0]["n_valid"] == int(r["RT"].notna().sum())
    np.testing.assert_array_equal(r["RT_SW"], 2.0 * r["RT"])
    assert s["lrlc"]["screening"]["zones"][0]["zone"] == "WELL"


def test_bad_step_is_counted_not_fatal(case, register_test_steps):
    r, s = run(case, lrlc_p(steps=["test_bad"]))
    assert "LRLC_STEP_INVALID" in codes(s)
    assert np.isfinite(r["SW"]).sum() < r["SW"].size       # invalid samples have no Sw
    ok = run(case, lrlc_p(steps=["test_bad"], fallback="previous"))
    assert "LRLC_STEP_FALLBACK" in codes(ok[1])
    assert ok[0]["SW"].notna().sum() > r["SW"].notna().sum()


def test_unknown_step_is_skipped_with_a_warning(case):
    off = run(case)
    r, s = run(case, lrlc_p(steps=["not_a_step"]))
    assert "LRLC_STEP_UNKNOWN" in codes(s)
    assert "RT_SW" not in r.columns
    assert_unchanged(off, (r, s))


def test_extra_columns_are_written(case, register_test_steps):
    r, s = run(case, lrlc_p(steps=["test_extra"]))
    assert {"RT_EXTRA", "TEST_AUX"} <= set(r.columns)
    pd.testing.assert_series_equal(r["TEST_AUX"], r["VSH"], check_exact=True, check_names=False)


# ---- segments and the merge ----------------------------------------------------------------
def test_step_in_one_zone_still_writes_rt_sw_everywhere(case, register_test_steps):
    lrlc = lrlc_p(zone_steps={"LOWER": ["test_scale"], "UPPER": []})
    r, s = run(case, lrlc)
    lower = r["ZONE"] == "LOWER"
    np.testing.assert_array_equal(r.loc[lower, "RT_SW"], 2.0 * r.loc[lower, "RT"])
    np.testing.assert_array_equal(r.loc[~lower, "RT_SW"], r.loc[~lower, "RT"])
    assert r.loc[~lower, "RT_X2"].isna().all() and r.loc[lower, "RT_X2"].notna().all()
    assert {rec["zone"] for rec in s["lrlc"]["chain"]} == {"LOWER"}


@pytest.mark.parametrize("active", ["LOWER", "UPPER"])
def test_planned_zone_runs_its_own_segment(case, register_test_steps, active):
    other = "UPPER" if active == "LOWER" else "LOWER"
    lrlc = lrlc_p(zone_steps={active: ["test_scale"], other: []})
    params = planned(case[2])
    data, mapping, _, tops = case
    r, s = run_pipeline(data.copy(), dict(mapping), {**params, "lrlc": lrlc}, formation_tops=tops)
    mask = r["ZONE"] == active
    np.testing.assert_array_equal(r.loc[mask, "RT_SW"], 2.0 * r.loc[mask, "RT"])
    np.testing.assert_array_equal(r.loc[~mask, "RT_SW"], r.loc[~mask, "RT"])
    assert r["RT_SW"].notna().sum() == r["RT"].notna().sum()
    (rec,) = s["lrlc"]["chain"]
    assert rec["segment"] == ("zone" if active == "LOWER" else "rest")
    for name in FLAG_COLUMNS:
        assert pd.api.types.is_integer_dtype(r[name]), name
    assert r[list(BASE_NEW)].notna().all().all()
    # The planned run still agrees with an LRLC-off planned run.
    off = run_pipeline(data.copy(), dict(mapping), params, formation_tops=tops)
    other_rows = ~mask
    pd.testing.assert_series_equal(r.loc[other_rows, "SW"], off[0].loc[other_rows, "SW"],
                                   check_exact=True)


def test_planned_no_step_changes_nothing(case):
    params = planned(case[2])
    data, mapping, _, tops = case
    off = run_pipeline(data.copy(), dict(mapping), params, formation_tops=tops)
    on = run_pipeline(data.copy(), dict(mapping), {**params, "lrlc": lrlc_p(rt_cutoff=True)},
                      formation_tops=tops)
    assert_unchanged(off, on)
    for name in FLAG_COLUMNS:
        assert pd.api.types.is_integer_dtype(on[0][name]), name
    assert {row["zone"] for row in on[1]["lrlc"]["screening"]["zones"]} == {"UPPER", "LOWER"}
    assert on[1]["lrlc"]["rt_cutoff"]["eligible"] > 0


def test_chain_records_are_merged_in_depth_order(case, register_test_steps):
    params = planned(case[2])
    data, mapping, _, tops = case
    lrlc = lrlc_p(steps=["test_identity"])
    _, s = run_pipeline(data.copy(), dict(mapping), {**params, "lrlc": lrlc}, formation_tops=tops)
    assert [rec["zone"] for rec in s["lrlc"]["chain"]] == ["UPPER", "LOWER"]
    assert [rec["segment"] for rec in s["lrlc"]["chain"]] == ["rest", "zone"]


# ---- no RT, auxiliary curves, cutoff issues -------------------------------------------------
def test_on_without_rt_is_skipped_with_an_info_issue(case):
    data, mapping, params, tops = case
    data = data.drop(columns=["RT"])
    mapping = {**mapping, "RT": "None"}
    r, s = run_pipeline(data, mapping, {**params, "lrlc": lrlc_p()}, formation_tops=tops)
    assert s["lrlc"] == {"version": 1, "skipped": "no RT"}
    assert "LRLC_NO_RT" in codes(s)
    assert not ({"RT_SW", "LRLC_FLAG", "BVW"} & set(r.columns))


def test_aux_curve_issues(case):
    data, mapping, params, tops = case
    data = data.copy()
    data.loc[data.index[:3], "RS"] = [0.0, -1.0, 0.0]
    lrlc = lrlc_p(curves={"RS": "RS", "RM": "RILM"})
    r, s = run_pipeline(data, mapping, {**params, "lrlc": lrlc}, formation_tops=tops)
    found = {i["code"]: i for i in s["issues"] if i["code"].startswith("LRLC_AUX")}
    assert found["LRLC_AUX_MISSING"]["severity"] == "warning"
    assert found["LRLC_AUX_NONPOSITIVE"]["severity"] == "info"
    assert "3 samples" in found["LRLC_AUX_NONPOSITIVE"]["text"]
    assert s["lrlc"]["curves"] == {"RS": "RS"}
    assert (data["RS"].iloc[:3] <= 0).all()               # the input frame is not modified


def test_cut_without_root_is_a_warning_above_five_percent(case):
    r, s = run(case, lrlc_p(rt_cutoff=True), sw_methods=["Archie"], sw_primary_method="Archie",
               rw=5000.0)
    issue = next(i for i in s["issues"] if i["code"] == "LRLC_CUT_NO_ROOT")
    assert issue["severity"] == "warning"
    assert s["lrlc"]["rt_cutoff"]["no_root"] == s["lrlc"]["rt_cutoff"]["eligible"]
    assert r["RT_CUT"].isna().all()


def test_swirr_column_fallback_warns(case):
    lrlc = lrlc_p()
    lrlc["movable"]["swirr_column"] = "SWIRR_BUCKLES"
    r, s = run(case, lrlc)
    assert "LRLC_SWIRR_COLUMN" in codes(s)
    assert s["lrlc"]["movable"]["swirr_column"] == "SWIRR_BUCKLES"


@pytest.mark.parametrize("variant", ["plain", "step", "planned", "cut", "no_rt"])
def test_every_emitted_code_is_registered(case, register_test_steps, variant):
    data, mapping, params, tops = case
    lrlc = lrlc_p(steps=["test_bad", "nope"] if variant == "step" else None,
                  rt_cutoff=variant == "cut", curves={"RM": "MISSING"})
    if variant == "planned":
        params = planned(params)
    if variant == "no_rt":
        data, mapping = data.drop(columns=["RT"]), {**mapping, "RT": "None"}
    _, s = run_pipeline(data.copy(), dict(mapping), {**params, "lrlc": lrlc}, formation_tops=tops)
    assert s["issues"]
    for issue in s["issues"]:
        assert issue["code"] in ISSUE_CODES
