"""Rock types in the pipeline and in the parameters handed to it (P1 spec 6, 9)."""

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from models.app_model import AppModel
from models.project import WellDataset
from modules import param_scopes as ps
from modules import rock_typing as rt
from modules.pipeline import PARAM_DEFAULTS, run_pipeline
from tests.golden.cases import FULL_MAPPING, fixture_frame, make_tops

BASE = {
    "rw_mode": "manual", "rw": 0.06, "rsh_mode": "manual", "rsh": 4.0,
    "vsh_baseline_method": ps.GR_MANUAL, "gr_min_manual": 30.0, "gr_max_manual": 120.0,
    "sw_methods": ["Archie", "Simandoux"],
}
NEW_COLUMNS = {"RQI", "FZI", "ROCK_TYPE", "ROCK_TYPE_SOURCE", "RT_MARGIN"}
# Every sample with a usable PHIE gets a type, so all three classes are populated.
OPEN = {"reservoir_only": False, "min_phie": 0.02}


def _set(boundaries, fzi=None, rng=(-3.0, 3.0)):
    n = len(boundaries) + 1
    return {"n_rt": n, "boundaries": list(boundaries), "centers": [0.0] * n,
            "fzi": list(fzi) if fzi is not None else [1.0 + i for i in range(n)],
            "feature_range": list(rng), "n_samples": [10] * n, "edited": False, "basis": "test"}


def _defs(set_, zone_sets=None, settings=None, **extra):
    return {"method": "fzi", "feature": "log10_fzi", "fit_scope": "project", "set": set_,
            "zone_sets": zone_sets or {}, "settings": {**OPEN, **(settings or {})},
            "basis": "pooled", "core_max_dist": 0.4, **extra}


def _run(extra=None, tops=True, plan=None):
    params = {**BASE, **(extra or {})}
    if plan is not None:
        params["zone_plan"] = plan
    return run_pipeline(fixture_frame("sample_log_data"), FULL_MAPPING, params,
                        formation_tops=make_tops() if tops else None)


@pytest.fixture(scope="module")
def fitted():
    """Three classes cut at the terciles of the log FZI of this log (and the data they cut)."""
    res, _ = _run({"rock_typing_enabled": True, "rock_types": _defs(_set([0.0, 1.0]))})
    lf = np.log10(res["FZI"].dropna())
    q = np.quantile(lf, [1 / 6, 1 / 3, 1 / 2, 2 / 3, 5 / 6])
    centres = [float(q[0]), float(q[2]), float(q[4])]
    return _set([float(q[1]), float(q[3])], fzi=[10 ** c for c in centres],
                rng=(float(lf.min()), float(lf.max())))


def _on(fitted, extra=None, defs=None, **kw):
    params = {"rock_typing_enabled": True, "rock_types": defs or _defs(fitted), **(extra or {})}
    return _run(params, **kw)


def _flow(k):
    k = np.asarray(k, dtype=float)
    return np.select([np.isnan(k), k < 1, k < 10, k < 100, k < 1000],
                     ["Unknown", "Tight", "Poor", "Fair", "Good"], default="Excellent")


def _plan():
    return ps.zone_plan({**PARAM_DEFAULTS, **BASE}, None,
                        {"LOWER": {"m": ps.make_entry(ps.MANUAL, 1.8)}}, None, ("UPPER", "LOWER"))


# ---- feature off: nothing changes -----------------------------------------
def test_disabled_run_has_no_rock_columns_key_or_warning():
    res, summary = _run()
    assert not (NEW_COLUMNS | {"PERM_RT", "R35"}) & set(res.columns)
    assert "rock_types" not in summary
    assert not any("ock" in w for w in summary["warnings"])
    assert not any("rock" in str(k).lower() for k in summary["param_sources"])


def test_disabled_run_equals_the_run_without_the_parameters_bit_for_bit(fitted):
    res0, sum0 = _run()
    stuffed = {"rock_typing_enabled": False, "rock_types": _defs(fitted),
               "rock_core": {"depth": [1010.0], "rt": [1]}}
    res1, sum1 = _run(stuffed)
    pd.testing.assert_frame_equal(res0, res1, check_exact=True)
    assert json.dumps(sum0, default=str, sort_keys=True) == json.dumps(sum1, default=str,
                                                                       sort_keys=True)


def test_enabled_without_definitions_warns_and_adds_nothing():
    res, summary = _run({"rock_typing_enabled": True})
    assert not NEW_COLUMNS & set(res.columns) and "rock_types" not in summary
    issues = [i for i in summary["issues"] if i["code"] == "ROCK_TYPES_NO_DEFINITIONS"]
    assert len(issues) == 1


# ---- columns, eligibility, counts -----------------------------------------
def test_columns_and_summary_only_when_enabled(fitted):
    res, summary = _on(fitted)
    assert NEW_COLUMNS <= set(res.columns)
    assert "PERM_RT" not in res.columns and "R35" not in res.columns
    assert "rock_types" in summary
    assert res["ROCK_TYPE"].dtype.kind in "iu"


def test_optional_columns_follow_their_switches(fitted):
    res, _ = _on(fitted, defs=_defs(fitted, settings={"r35_column": True, "perm_rt_column": True}))
    assert {"R35", "PERM_RT"} <= set(res.columns)
    k, phi = res["PERM_TIMUR"], res["PHIE"]
    assert res["R35"].iloc[50] == pytest.approx(float(rt.winland_r35(k.iloc[50], phi.iloc[50])))


def test_eligibility_codes_and_counts_reconcile(fitted):
    cut = PARAM_DEFAULTS["vsh_cutoff"]
    defs = _defs(fitted, settings={"reservoir_only": True, "min_phie": 0.1})
    res, summary = _on(fitted, defs=defs)
    vsh, phie, src = res["VSH"], res["PHIE"], res["ROCK_TYPE_SOURCE"]
    assert (src[vsh >= cut] == "x_vsh").all()
    assert (src[(vsh < cut) & (phie < 0.1)] == "x_phie").all()
    assert set(src) <= {"log", "core", "x_vsh", "x_phie", "x_perm", "x_nan"}
    assigned = res["ROCK_TYPE"] > 0
    assert (assigned == src.isin(["log", "core"])).all()
    section = summary["rock_types"]
    counts = section["counts"]
    assert counts["x_vsh"] > 0 and counts["x_phie"] > 0 and counts["log"] > 0
    assert sum(counts[c] for c in rt.SOURCE_CODES) == len(res)
    by_rt_samples = sum(r["samples"] for r in section["by_rt"])
    assert by_rt_samples == int(assigned.sum())
    assert by_rt_samples + section["unassigned"]["samples"] == len(res)
    assert (res.loc[~assigned, "RT_MARGIN"].isna()).all()


def test_log_classification_matches_the_definitions(fitted):
    res, _ = _on(fitted)
    ok = res["ROCK_TYPE"] > 0
    expected, margin = rt.classify(np.log10(res.loc[ok, "FZI"]), fitted)
    assert (res.loc[ok, "ROCK_TYPE"].to_numpy() == expected).all()
    assert res.loc[ok, "RT_MARGIN"].to_numpy() == pytest.approx(margin)
    assert set(res.loc[ok, "ROCK_TYPE"]) == {1, 2, 3}


def test_counts_near_boundary_and_outside_range(fitted):
    narrow = dict(fitted, feature_range=[fitted["boundaries"][0], fitted["boundaries"][1]])
    res, summary = _on(fitted, defs=_defs(narrow, settings={"margin_min": 0.2}))
    counts = summary["rock_types"]["counts"]
    ok = res["ROCK_TYPE"] > 0
    assert counts["near_boundary"] == int((res.loc[ok, "RT_MARGIN"] < 0.2).sum()) > 0
    lf = np.log10(res.loc[ok, "FZI"])
    lo, hi = narrow["feature_range"]
    assert counts["outside_range"] == int(((lf < lo - 0.5) | (lf > hi + 0.5)).sum())


# ---- core labels ----------------------------------------------------------
def test_core_labels_override_only_within_core_max_dist(fitted):
    base, _ = _on(fitted)
    ok = base[base["ROCK_TYPE"] > 0]
    near, far = ok.iloc[3], ok.iloc[10]
    wrong = int(near["ROCK_TYPE"] % 3 + 1)
    defs = _defs(fitted)                                            # core_max_dist = 0.4
    core = {"depth": [float(near["DEPTH"]) + 0.3, float(far["DEPTH"]) + 0.5], "rt": [wrong, wrong]}
    res, summary = _on(fitted, {"rock_core": core}, defs=defs)
    i, j = near.name, far.name
    assert res.loc[i, "ROCK_TYPE"] == wrong and res.loc[i, "ROCK_TYPE_SOURCE"] == "core"
    assert res.loc[j, "ROCK_TYPE"] == far["ROCK_TYPE"] and res.loc[j, "ROCK_TYPE_SOURCE"] == "log"
    assert (res["ROCK_TYPE_SOURCE"] == "core").sum() == 1
    assert res.loc[i, "RT_MARGIN"] == base.loc[i, "RT_MARGIN"]       # the margin stays the log's
    section = summary["rock_types"]
    assert section["counts"]["core"] == 1
    assert section["agreement"]["n"] == 1 and section["agreement"]["fraction"] == 0.0
    confusion = np.array(section["agreement"]["confusion"])
    assert confusion[wrong - 1, int(near["ROCK_TYPE"]) - 1] == 1 and confusion.sum() == 1
    assert not any("No core labels" in w for w in summary["warnings"])


def test_core_labels_off_and_ineligible_samples_keep_their_status(fitted):
    base, _ = _on(fitted)
    ok = base[base["ROCK_TYPE"] > 0].iloc[2]
    core = {"depth": [float(ok["DEPTH"])], "rt": [1 if ok["ROCK_TYPE"] != 1 else 2]}
    off, _ = _on(fitted, {"rock_core": core}, defs=_defs(fitted, settings={"use_core_labels": False}))
    pd.testing.assert_series_equal(off["ROCK_TYPE"], base["ROCK_TYPE"])
    shaly = _defs(fitted, settings={"reservoir_only": True})
    shale_depth = float(base[base["VSH"] >= PARAM_DEFAULTS["vsh_cutoff"]].iloc[0]["DEPTH"])
    res, _ = _on(fitted, {"rock_core": {"depth": [shale_depth], "rt": [1]}}, defs=shaly)
    assert (res["ROCK_TYPE_SOURCE"] != "core").all()


def test_uncored_well_is_flagged(fitted):
    res, summary = _on(fitted)
    assert (res["ROCK_TYPE_SOURCE"] != "core").all()
    assert sum("No core labels" in w for w in summary["warnings"]) == 1
    assert summary["rock_types"]["counts"]["core"] == 0
    assert any("log-derived" in n for n in summary["rock_types"]["notes"])


# ---- zone sets ------------------------------------------------------------
@pytest.mark.parametrize("planned", [False, True])
def test_zone_sets_apply_per_zone(fitted, planned):
    all_three = _set([-50.0, -49.0])                               # every sample is type 3
    defs = _defs(fitted, zone_sets={"UPPER": all_three})
    res, _ = _on(fitted, defs=defs, plan=_plan() if planned else None)
    upper = res["ZONE"] == "UPPER"
    ok = res["ROCK_TYPE"] > 0
    assert set(res.loc[upper & ok, "ROCK_TYPE"]) == {3}
    other = ~upper & ok
    expected, _ = rt.classify(np.log10(res.loc[other, "FZI"]), fitted)
    assert (res.loc[other, "ROCK_TYPE"].to_numpy() == expected).all()
    assert (other.sum() > 0) and (upper & ok).sum() > 0


def test_zoned_summary_rows_reconcile_with_the_zone_table(fitted):
    res, summary = _on(fitted, plan=_plan())
    section = summary["rock_types"]
    for zone in summary["zones"]:
        rows = [r for r in section["by_zone_rt"] if r["zone"] == zone["zone"]]
        assert sum(r["samples"] for r in rows) == zone["samples"]
        assert sum(r["net_pay"] for r in rows) == pytest.approx(zone["net_pay"])
        assert sum(r["hcpv_net_pay"] for r in rows) == pytest.approx(zone["hcpv_net_pay"])


# ---- permeability: PERM_RT and perm_primary --------------------------------
def test_perm_rt_is_nan_for_type_zero_and_the_fzi_form_elsewhere(fitted):
    res, _ = _on(fitted, {"perm_primary": "Rock type"})
    zero = res["ROCK_TYPE"] == 0
    assert zero.sum() > 0 and res.loc[zero, "PERM_RT"].isna().all()
    for t in (1, 2, 3):
        sel = res["ROCK_TYPE"] == t
        expected = rt.perm_from_fzi(fitted["fzi"][t - 1], res.loc[sel, "PHIE"])
        assert res.loc[sel, "PERM_RT"].to_numpy() == pytest.approx(expected)
    assert res["PERM_RT"].dropna().between(0.001, 50000).all()


@pytest.mark.parametrize("choice,column", [("Timur", "PERM_TIMUR"), ("Wyllie-Rose", "PERM_WR"),
                                           ("Rock type", "PERM_RT")])
def test_perm_primary_picks_the_series_behind_flow_unit(fitted, choice, column):
    res, summary = _on(fitted, {"perm_primary": choice, "perm_C": 300.0})
    assert (res["FLOW_UNIT"].to_numpy() == _flow(res[column])).all()
    assert (res["FLOW_UNIT"].to_numpy() != _flow(res["PERM_TIMUR"])).any() == (choice != "Timur")
    assert summary["rock_types"]["lorenz"]["basis"] == column


def test_default_primary_is_timur_with_rock_typing_on(fitted):
    res, _ = _on(fitted)
    assert (res["FLOW_UNIT"].to_numpy() == _flow(res["PERM_TIMUR"])).all()


def test_rock_type_primary_without_definitions_falls_back_to_timur_with_one_warning():
    for extra in ({"perm_primary": "Rock type"},
                  {"perm_primary": "Rock type", "rock_typing_enabled": True}):
        res, summary = _run(extra)
        assert "PERM_RT" not in res.columns
        assert (res["FLOW_UNIT"].to_numpy() == _flow(res["PERM_TIMUR"])).all()
        fallback = [i for i in summary["issues"] if i["code"] == "PERM_PRIMARY_FALLBACK"]
        assert len(fallback) == 1 and "Timur" in fallback[0]["text"]


def test_rock_type_primary_with_a_type_without_fzi_falls_back(fitted):
    holes = dict(fitted, fzi=[fitted["fzi"][0], None, fitted["fzi"][2]])
    res, summary = _on(fitted, {"perm_primary": "Rock type"}, defs=_defs(holes))
    assert (res["FLOW_UNIT"].to_numpy() == _flow(res["PERM_TIMUR"])).all()
    assert any(i["code"] == "PERM_PRIMARY_FALLBACK" for i in summary["issues"])
    assert "lorenz" in summary["rock_types"] and summary["rock_types"]["lorenz"]["basis"] == "PERM_TIMUR"
    # the optional column still shows the missing type as NaN, counted
    res2, summary2 = _on(fitted, defs=_defs(holes, settings={"perm_rt_column": True}))
    assert summary2["rock_types"]["counts"]["perm_rt_missing"] == int((res2["ROCK_TYPE"] == 2).sum())
    assert res2.loc[res2["ROCK_TYPE"] == 2, "PERM_RT"].isna().all()


def test_log_permeability_choice_changes_the_feature(fitted):
    timur, _ = _on(fitted)
    wr, _ = _on(fitted, {"rt_log_perm": "Wyllie-Rose", "perm_C": 300.0})   # default C equals Timur
    ok = wr["ROCK_TYPE"] > 0
    expected = rt.fzi(wr.loc[ok, "PERM_WR"], wr.loc[ok, "PHIE"])
    assert wr.loc[ok, "FZI"].to_numpy() == pytest.approx(expected)
    assert not np.allclose(timur["FZI"].fillna(0), wr["FZI"].fillna(0))


# ---- summary reconciliation ------------------------------------------------
@pytest.mark.parametrize("variant", ["plain", "tops", "planned"])
def test_net_pay_and_hcpv_per_rock_type_sum_to_the_well_totals(fitted, variant):
    kwargs = {"plain": {"tops": False}, "tops": {}, "planned": {"plan": _plan()}}[variant]
    res, summary = _on(fitted, {"vsh_cutoff": 0.9, "phi_cutoff": 0.02, "sw_cutoff": 0.99}, **kwargs)
    section = summary["rock_types"]
    rows = section["by_rt"] + [section["unassigned"]]
    assert sum(r["samples"] for r in rows) == len(res)
    for key in ("gross_sand", "net_reservoir", "net_pay"):
        assert sum(r[key] for r in rows) == pytest.approx(summary[key]), key
    assert summary["net_pay"] > 0
    assert sum(r["hcpv_net_pay"] for r in rows) == pytest.approx(summary["hcpv_net_pay"])
    assert summary["hcpv_net_pay"] > 0
    assert all(r["fzi"] == fitted["fzi"][r["rt"] - 1] for r in section["by_rt"])
    assert section["unassigned"]["rt"] == 0 and section["unassigned"]["fzi"] is None


def test_lorenz_block_only_when_asked(fitted):
    _, with_it = _on(fitted)
    _, without = _on(fitted, defs=_defs(fitted, settings={"lorenz": False}))
    assert 0.0 <= with_it["rock_types"]["lorenz"]["coefficient"] <= 1.0
    assert isinstance(with_it["rock_types"]["lorenz"]["units"], list)
    assert "lorenz" not in without["rock_types"]


# ---- params_for_well ------------------------------------------------------
def _core(depth, phi, k, tvd=False):
    return SimpleNamespace(
        data=pd.DataFrame({"depth": depth, "por": phi, "perm": k}), depth_col="depth",
        porosity_col="por", perm_col="perm", depth_is_tvd=tvd, excluded_rows=[],
        excluded_row_wells={}, spellings=[])


def _model(scope="project"):
    model = AppModel()
    depth = [1002.0 + 3 * i for i in range(30)]
    phi = [0.08 + 0.004 * i for i in range(30)]
    k = [10 ** (-0.5 + i / 8) for i in range(30)]
    cores = {"A": _core(depth, phi, k), "B": _core(depth, phi, k, tvd=True), "C": None}
    for name in "ABC":
        ds = WellDataset(key=f"WELL:{name}", display_name=name)
        ds.las_data = fixture_frame("sample_log_data")
        ds.curve_mapping = dict(FULL_MAPPING)
        ds.formation_tops = make_tops()
        ds.core_data = cores[name]
        model.add_well(ds)
    pooled = _set([0.0, 0.5])
    sets = {"*": pooled}
    if scope == "well":
        sets["WELL:A"] = _set([-0.5, 0.2])
    if scope == "zone":
        sets["UPPER"] = _set([-1.0, 1.0])
    model.project.rock_types = {
        "version": 1, "method": "fzi", "feature": "log10_fzi", "fit_scope": scope, "sets": sets,
        "settings": dict(OPEN), "fingerprint": {}, "fit_report": {}}
    model.rock_typing_enabled = True
    return model


def _plain(value):
    """True when only dict, list, str, int, float, bool and None occur (no numpy, no tuples)."""
    if isinstance(value, dict):
        return all(isinstance(k, str) and _plain(v) for k, v in value.items())
    if isinstance(value, list):
        return all(_plain(v) for v in value)
    return value is None or type(value) in (str, int, float, bool)


def test_params_for_well_shape_and_core_labels():
    model = _model()
    flat = model.params_for_well(model.project.get("WELL:A"))
    defs = flat["rock_types"]
    assert set(defs) == {"method", "feature", "fit_scope", "set", "zone_sets", "settings", "basis",
                         "core_max_dist"}
    assert defs["basis"] == "pooled" and defs["zone_sets"] == {} and defs["core_max_dist"] == 2.0
    assert defs["set"]["boundaries"] == [0.0, 0.5]
    core = flat["rock_core"]
    assert set(core) == {"depth", "rt"} and len(core["depth"]) == len(core["rt"]) == 30
    assert core["depth"] == sorted(core["depth"])
    phi = [0.08 + 0.004 * i for i in range(30)]
    k = [10 ** (-0.5 + i / 8) for i in range(30)]
    expected = np.searchsorted([0.0, 0.5], np.log10(rt.fzi(k, phi))) + 1
    assert core["rt"] == expected.tolist()
    assert _plain(flat["rock_types"]) and _plain(flat["rock_core"])
    # a TVD core is not labelled, an uncored well has none; both still carry the definitions
    assert model.params_for_well(model.project.get("WELL:B"))["rock_core"] is None
    flat_c = model.params_for_well(model.project.get("WELL:C"))
    assert flat_c["rock_core"] is None and flat_c["rock_types"]["set"] == defs["set"]


def test_params_for_well_core_max_dist_follows_the_model():
    model = _model()
    model.core_max_dist = 5.0
    assert model.params_for_well(model.project.get("WELL:A"))["rock_types"]["core_max_dist"] == 5.0


def test_params_for_well_scope_resolution():
    well_model = _model("well")
    a = well_model.params_for_well(well_model.project.get("WELL:A"))["rock_types"]
    c = well_model.params_for_well(well_model.project.get("WELL:C"))["rock_types"]
    assert a["basis"] == "well" and a["set"]["boundaries"] == [-0.5, 0.2]
    assert c["basis"] == "pooled fallback" and c["set"]["boundaries"] == [0.0, 0.5]
    zone_model = _model("zone")
    z = zone_model.params_for_well(zone_model.project.get("WELL:A"))
    assert list(z["rock_types"]["zone_sets"]) == ["UPPER"] and z["rock_types"]["basis"] == "zone"
    zones = z["rock_core"]
    assert zones and len(zones["depth"]) == 30


def test_params_for_well_disabled_carries_nothing_and_ignores_the_definitions():
    model = _model()
    model.rock_typing_enabled = False
    well = model.project.get("WELL:A")
    flat = model.params_for_well(well)
    assert flat["rock_types"] is None and flat["rock_core"] is None
    before = model.well_params_hash(well)
    model.project.rock_types["sets"]["*"]["boundaries"] = [3.0, 4.0]
    assert model.well_params_hash(well) == before
    model.rock_typing_enabled = True
    assert model.well_params_hash(well) != before


@pytest.mark.parametrize("scope", ["project", "well", "zone"])
def test_hash_is_identical_after_a_json_round_trip_of_the_definitions(scope):
    model = _model(scope)
    hashes = {k: model.well_params_hash(model.project.get(f"WELL:{k}")) for k in "ABC"}
    model.project.rock_types = json.loads(json.dumps(model.project.rock_types))
    for k in "ABC":
        assert model.well_params_hash(model.project.get(f"WELL:{k}")) == hashes[k]
    flat = model.params_for_well(model.project.get("WELL:A"))
    assert json.loads(json.dumps(flat["rock_types"])) == flat["rock_types"]
    assert json.loads(json.dumps(flat["rock_core"])) == flat["rock_core"]


def test_handed_over_parameters_run_through_the_pipeline():
    model = _model()
    flat = model.params_for_well(model.project.get("WELL:A"))
    flat.update({"rw_mode": "manual", "rw": 0.06, "rsh_mode": "manual", "rsh": 4.0})
    res, summary = run_pipeline(fixture_frame("sample_log_data"), FULL_MAPPING, flat,
                                formation_tops=make_tops())
    assert NEW_COLUMNS <= set(res.columns)
    assert summary["rock_types"]["counts"]["core"] > 0
