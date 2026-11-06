"""Variable m / n in the pipeline: scalar mode is untouched, the curves reach every Sw consumer,
columns are written in every segment, and RT_CUT reads exactly the inputs of the primary Sw."""
import numpy as np
import pandas as pd
import pytest

from modules.lrlc.config import LRLC_PARAM_DEFAULTS
from modules.lrlc.variable_mn import m_formula, n_formula
from modules.petrophysics import PetrophysicsCalculator
from modules.pipeline import PARAM_DEFAULTS, run_pipeline
from tests.test_lrlc_pipeline import case, codes, lrlc_p, planned  # noqa: F401
from tests.test_lrlc_pipeline_l2 import MAPPING, PARAMS, PHI_MAX, laminated_well, ts_p

CURVE = {"mn_mode": "curve", "m_coef": [1.9, 0.5, 0.3, 0.0], "n_model": "vsh",
         "n_coef": [1.8, 0.6]}
SIMANDOUX = {"sw_methods": ["Archie", "Simandoux"], "sw_primary_method": "Simandoux"}


def run_well(frame, lrlc=None, **over):
    params = {**PARAMS, **over}
    if lrlc is not None:
        params["lrlc"] = lrlc
    return run_pipeline(frame.copy(), dict(MAPPING), params)


def lam_frame():
    frame, _ = laminated_well()
    return frame


# ---- scalar mode is untouched ----------------------------------------------------------------
def test_scalar_mode_writes_nothing_and_changes_nothing():
    frame = lam_frame()
    off = run_well(frame, **SIMANDOUX)
    on_r, on_s = run_well(frame, lrlc_p(zones=()), **SIMANDOUX)
    assert not {"M_VAR", "N_VAR"} & set(on_r.columns)
    assert "variable_mn" not in on_s["lrlc"]
    for col in ("SW", "SW_SIMAN", "SW_ARCHIE"):
        pd.testing.assert_series_equal(on_r[col], off[0][col], check_exact=True)


def test_curve_mode_with_constant_coefficients_reproduces_the_scalar_run():
    frame = lam_frame()
    base_r, _ = run_well(frame, lrlc_p(zones=()), **SIMANDOUX)
    ladder = {"mn_mode": "curve", "m_coef": [PARAMS["m"], 0.0, 0.0, 0.0]}
    r, s = run_well(frame, lrlc_p(zones=(), **ladder), **SIMANDOUX)
    assert {"M_VAR", "N_VAR"} <= set(r.columns)
    assert (r["M_VAR"] == PARAMS["m"]).all() and (r["N_VAR"] == PARAMS["n"]).all()
    for col in ("SW", "SW_SIMAN", "SW_ARCHIE"):
        pd.testing.assert_series_equal(r[col], base_r[col], check_exact=True)


# ---- the curves reach the Sw models ----------------------------------------------------------
def test_curves_follow_the_formula_and_feed_every_selected_model():
    frame = lam_frame()
    methods = {"sw_methods": ["Archie", "Indonesian", "Simandoux"],
               "sw_primary_method": "Simandoux"}
    r, s = run_well(frame, lrlc_p(zones=(), **CURVE), **methods)
    ok = r["PHIE"].ge(0.02) & r["VSH"].notna()
    exp_m = np.clip(m_formula(r["PHIE"][ok], r["VSH"][ok], CURVE["m_coef"]), 1.0, 4.0)
    exp_n = np.clip(n_formula(r["VSH"][ok], CURVE["n_coef"]), 1.0, 4.0)
    np.testing.assert_allclose(r["M_VAR"][ok], exp_m, rtol=0, atol=1e-12)
    np.testing.assert_allclose(r["N_VAR"][ok], exp_n, rtol=0, atol=1e-12)
    # Independent evaluation of each model with the same arrays.
    calc = PetrophysicsCalculator(frame)
    phie = r["PHIE"]
    m, n = r["M_VAR"].to_numpy(), r["N_VAR"].to_numpy()
    rw, rsh = PARAMS["rw"], PARAMS["rsh"]
    arch = calc.calculate_sw_archie("RT", phie, rw, 1.0, m, n)
    indo = calc.calculate_sw_indonesian("RT", phie, r["VSH"], rw, rsh, 1.0, m, n)
    siman = calc.calculate_sw_simandoux("RT", phie, r["VSH"], rw, rsh, 1.0, m, n)
    np.testing.assert_array_equal(r["SW_ARCHIE"].to_numpy(), np.asarray(arch))
    np.testing.assert_array_equal(r["SW_INDO"].to_numpy(), np.asarray(indo))
    np.testing.assert_array_equal(r["SW_SIMAN"].to_numpy(), np.asarray(siman))
    assert r["SW"].equals(r["SW_SIMAN"])
    assert not np.allclose(r["SW_ARCHIE"], run_well(frame, lrlc_p(zones=()))[0]["SW_ARCHIE"],
                           equal_nan=True)


def test_summary_block_and_cut_keys():
    frame = lam_frame()
    _, s = run_well(frame, lrlc_p(zones=(), **CURVE), **SIMANDOUX)
    blk = s["lrlc"]["variable_mn"]
    assert set(blk) == {"clip_m", "clip_n", "zones"}
    (row,) = blk["zones"]
    assert row["zone"] == "WELL" and row["mode"] == "curve"
    assert row["m_model"] == "formula" and row["n_model"] == "vsh"
    assert row["m_coef"] == CURVE["m_coef"] and row["n_coef"] == CURVE["n_coef"]
    assert row["phi_source"] == "phie"
    for key in ("m_p05", "m_p50", "m_p95", "n_p05", "n_p50", "n_p95", "n_samples", "n_eval",
                "n_fallback", "n_clipped_m", "n_clipped_n"):
        assert key in row
    assert row["m_p05"] <= row["m_p50"] <= row["m_p95"]


def test_issues_are_routed_like_the_chain_issues():
    frame = lam_frame()
    ladder = {"mn_mode": "curve", "m_coef": [3.8, 0.0, 0.0, 0.0], "n_model": "vsh",
              "n_coef": [3.0, 3.0]}
    _, s = run_well(frame, lrlc_p(zones=(), **ladder))
    assert "LRLC_MN_CLIPPED" in codes(s)
    shell = {"mn_mode": "curve", "m_model": "shell"}
    _, s2 = run_well(frame, lrlc_p(zones=(), **shell))
    assert "LRLC_MN_SHELL_LITHOLOGY" in codes(s2)
    issue = next(i for i in s2["issues"] if i["code"] == "LRLC_MN_SHELL_LITHOLOGY")
    assert issue["zone"] is None and "(unzoned)" not in issue["text"]


def test_auto_rw_ignores_the_curves():
    frame = lam_frame()
    auto = {"rw_mode": "auto"}
    scalar = run_well(frame, lrlc_p(zones=()), **auto)[1]
    curve = run_well(frame, lrlc_p(zones=(), **CURVE), **auto)[1]
    assert curve["rw"] == scalar["rw"]


# ---- columns in every segment ----------------------------------------------------------------
def zone_lrlc(lower_curve=True):
    lrlc = lrlc_p()
    if lower_curve:
        lrlc["resolved"]["zones"]["LOWER"].update(CURVE)
    return lrlc


def test_columns_are_written_in_every_segment(case):  # noqa: F811
    for params in (case[2], planned(case[2])):
        data, mapping, _, tops = case
        r, s = run_pipeline(data.copy(), dict(mapping), {**params, "lrlc": zone_lrlc()},
                            formation_tops=tops)
        assert r["M_VAR"].notna().all() and r["N_VAR"].notna().all()
        upper = r["ZONE"] == "UPPER"
        # Scalar zone: the segment's own m and n.
        assert upper.any() and (r.loc[upper, "M_VAR"] == r.loc[upper, "M_VAR"].iloc[0]).all()
        lower = ~upper
        assert r.loc[lower, "M_VAR"].nunique() > 1
        (row,) = s["lrlc"]["variable_mn"]["zones"]
        assert row["zone"] == "LOWER"


def test_no_curve_zone_no_columns(case):  # noqa: F811
    data, mapping, params, tops = case
    r, s = run_pipeline(data.copy(), dict(mapping), {**params, "lrlc": zone_lrlc(False)},
                        formation_tops=tops)
    assert "M_VAR" not in r.columns and "variable_mn" not in s["lrlc"]


def test_planned_zone_scalar_m_is_the_fallback_value(case):  # noqa: F811
    data, mapping, params, tops = case
    p = planned(params)                      # LOWER has its own scalar m of 1.8
    ladder = {"mn_mode": "curve", "m_coef": [1.8, 0.0, 0.0, 0.0]}
    base = run_pipeline(data.copy(), dict(mapping), {**p, "lrlc": zone_lrlc(False)},
                        formation_tops=tops)[0]
    lrlc = zone_lrlc(False)
    lrlc["resolved"]["zones"]["LOWER"].update(ladder)
    r = run_pipeline(data.copy(), dict(mapping), {**p, "lrlc": lrlc}, formation_tops=tops)[0]
    lower = r["ZONE"] == "LOWER"
    assert (r.loc[lower, "M_VAR"] == 1.8).all()
    pd.testing.assert_series_equal(r["SW"], base["SW"], check_exact=True)


# ---- RT_CUT reads exactly what the primary Sw read -------------------------------------------
TARGET = 0.45


def cut_ladder(**extra):
    return {"cut_sw_target": TARGET, **extra}


def test_rt_cut_is_the_target_sw_in_a_curve_zone():
    frame = lam_frame()
    lrlc = lrlc_p(zones=(), rt_cutoff=True, **cut_ladder(**CURVE))
    r, s = run_well(frame, lrlc, **SIMANDOUX)
    ok = r["RT_CUT"].notna()
    assert ok.sum() > 50 and r.loc[ok, "N_VAR"].nunique() > 5
    calc = PetrophysicsCalculator(pd.DataFrame({"RT_X": r["RT_CUT"].where(ok, 1.0)}))
    back = calc.calculate_sw_simandoux(
        "RT_X", r["PHIE"].where(ok, 0.2), r["VSH"].where(ok, 0.2), PARAMS["rw"], PARAMS["rsh"],
        1.0, r["M_VAR"].to_numpy(), r["N_VAR"].to_numpy(), rt=r["RT_CUT"].where(ok, 1.0).to_numpy())
    np.testing.assert_allclose(np.asarray(back)[ok.to_numpy()], TARGET, atol=1e-6)
    # With the scalar exponents the same Rt does not return the target: the cut moved.
    scalar = run_well(frame, lrlc_p(zones=(), rt_cutoff=True, **cut_ladder()), **SIMANDOUX)[0]
    assert not np.allclose(scalar["RT_CUT"], r["RT_CUT"], equal_nan=True)


def test_rt_cut_is_the_target_sw_in_a_sand_basis_and_estimated_qv_zone():
    frame = lam_frame()
    methods = {"sw_methods": ["Archie", "Waxman-Smits"], "sw_primary_method": "Waxman-Smits"}
    lrlc = ts_p(steps=("laminated",), qv_source="estimate", cut_sw_target=TARGET)
    lrlc["rt_cutoff"] = {"enabled": True}
    r, s = run_well(frame, lrlc, **methods)
    assert r["QV_EST"].notna().any() and r["VLAM"].notna().any()
    vlam, vdisp = r["VLAM"].to_numpy(), r["VDISP"].to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        vd_s = vdisp / (1.0 - vlam)
    phit_s = r["PHI_SAND"].to_numpy()
    phie_s = PHI_MAX - vd_s
    qv = np.where(np.isfinite(r["QV_EST"]), r["QV_EST"], PARAM_DEFAULTS["ws_qv"])
    ok = (r["RT_CUT"].notna().to_numpy() & np.isfinite(phit_s) & np.isfinite(phie_s)
          & np.isfinite(r["QV_EST"].to_numpy()))
    assert ok.sum() > 20
    rt = np.where(ok, r["RT_CUT"].to_numpy(), 1.0)
    calc = PetrophysicsCalculator(pd.DataFrame({"RT_X": rt}))
    back = calc.calculate_sw_waxman_smits(
        "RT_X", pd.Series(np.where(ok, phit_s, 0.2)), PARAMS["rw"], 1.0, PARAMS["m"],
        PARAMS["n"], np.where(ok, qv, 0.0), PARAM_DEFAULTS["ws_b"],
        phie=pd.Series(np.where(ok, phie_s, 0.2)), rt=rt)
    np.testing.assert_allclose(np.asarray(back)[ok], TARGET, atol=1e-6)
    # The same Rt through the bulk basis and the constant Qv does not return the target.
    bulk = calc.calculate_sw_waxman_smits(
        "RT_X", r["PHIT"].fillna(0.2), PARAMS["rw"], 1.0, PARAMS["m"], PARAMS["n"],
        PARAM_DEFAULTS["ws_qv"], PARAM_DEFAULTS["ws_b"], phie=r["PHIE"].fillna(0.2), rt=rt)
    assert not np.allclose(np.asarray(bulk)[ok], TARGET, atol=1e-3)


def test_zone_cut_row_uses_the_curve_means():
    frame = lam_frame()
    lrlc = lrlc_p(zones=(), rt_cutoff=True, **cut_ladder(**CURVE))
    _, s = run_well(frame, lrlc, **SIMANDOUX)
    (row,) = s["lrlc"]["rt_cutoff"]["zones"]
    assert np.isfinite(row["rt_cut"]) and row["model"] == "Simandoux"
