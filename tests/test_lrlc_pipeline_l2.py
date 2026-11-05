"""LRLC laminated sands, minerals and Qv in the pipeline: off and idle stay untouched, the
laminated step recovers a forward model, per-zone steps, sand basis, pyrite, Qv."""
import numpy as np
import pandas as pd
import pytest

from modules.lrlc.config import LRLC_PARAM_DEFAULTS
from modules.pipeline import run_pipeline
from tests.test_lrlc_pipeline import case, codes, lrlc_p, planned, run  # noqa: F401

RW, RSH, A, M, N = 0.05, 2.0, 1.0, 2.0, 2.0
PHI_MAX, PHI_SH, SW_TRUE = 0.30, 0.08, 0.30
TS_COLUMNS = {"VLAM", "VDISP", "PHI_SAND", "TS_CLASS"}

PARAMS = {
    "vsh_baseline_method": "Custom (Manual)", "gr_min_manual": 20.0, "gr_max_manual": 120.0,
    "sw_methods": ["Archie"], "sw_primary_method": "Archie",
    "rw": RW, "rw_mode": "manual", "rsh": RSH, "rsh_mode": "manual",
    "a": A, "m": M, "n": N,
}
MAPPING = {"GR": "GR", "RHOB": "RHOB", "NPHI": "None", "DT": "None", "RT": "RT"}


def laminated_well(n=160, pef=False, vpyr=0.0):
    """Sand laminae (phi_max, Archie Sw 0.30) with shale laminae; Vsh = Vlam on the laminar line."""
    depth = np.linspace(1000.0, 1080.0, n)
    vlam = 0.12 + 0.36 * (0.5 + 0.5 * np.sin(depth / 3.0))
    phit = (1 - vlam) * PHI_MAX + vlam * PHI_SH
    rsand = A * RW / (PHI_MAX ** M * SW_TRUE ** N)
    rt = 1.0 / ((1 - vlam) / rsand + vlam / RSH)
    frame = pd.DataFrame({"DEPTH": depth, "GR": 20.0 + 100.0 * vlam,
                          "RHOB": 2.65 - 1.65 * phit, "RT": rt})
    return frame, vlam


def ts_p(steps=("laminated",), **ladder):
    lrlc = lrlc_p(steps=list(steps), zones=(), phi_max=PHI_MAX, phi_sh=PHI_SH, **ladder)
    lrlc["thomas_stieber"] = {"enabled": True}
    return lrlc


def run_well(frame, lrlc=None, **over):
    params = {**PARAMS, **over}
    if lrlc is not None:
        params["lrlc"] = lrlc
    return run_pipeline(frame.copy(), dict(MAPPING), params)


def interior(r):
    return r[(r["VSH"] > 0.1) & (r["VSH"] < 0.5)]


# ---- off and idle ------------------------------------------------------------------------
def test_off_has_no_new_keys_or_columns():
    frame, _ = laminated_well()
    r, s = run_well(frame)
    assert "lrlc" not in s
    assert not ({"VLAM", "VPYR", "QV_EST", "RT_SAND", "RT_PYR", "SW_BASE",
                 "NET_PAY_BASE_FLAG"} | TS_COLUMNS) & set(r.columns)


def test_on_nothing_selected_is_unchanged(case):  # noqa: F811
    off = run(case)
    on = run(case, lrlc_p())
    pd.testing.assert_frame_equal(on[0][list(off[0].columns)], off[0], check_exact=True)
    assert on[1]["net_pay"] == off[1]["net_pay"]
    assert on[1]["hcpv_net_pay"] == off[1]["hcpv_net_pay"]
    assert "zones" not in on[1]["lrlc"] and "validation" not in on[1]["lrlc"]
    assert not ({"SW_BASE", "NET_PAY_BASE_FLAG", "VLAM", "VPYR", "QV_EST"} & set(on[0].columns))


def test_thomas_stieber_adds_only_its_four_columns():
    frame, _ = laminated_well()
    off = run_well(frame, lrlc_p(zones=()))
    r, s = run_well(frame, ts_p(steps=()))
    assert set(r.columns) - set(off[0].columns) == TS_COLUMNS
    pd.testing.assert_series_equal(r["SW"], off[0]["SW"], check_exact=True)
    assert pd.api.types.is_integer_dtype(r["TS_CLASS"])
    assert "SW_BASE" not in r.columns
    ts = s["lrlc"]["ts"]["zones"][0]
    assert ts["phi_max"] == PHI_MAX and ts["lam_share"] == pytest.approx(1.0, abs=1e-6)


def test_thomas_stieber_recovers_the_forward_vlam():
    frame, vlam = laminated_well()
    r, _ = run_well(frame, ts_p(steps=()))
    np.testing.assert_allclose(r["VLAM"], vlam, atol=1e-9)
    assert (r["TS_CLASS"] == 1).all()


def test_ts_without_endpoints_and_defaulted_vsh():
    frame, _ = laminated_well()
    lrlc = lrlc_p(zones=())
    lrlc["thomas_stieber"] = {"enabled": True}
    r, s = run_well(frame, lrlc)
    assert r["VLAM"].isna().all() and "LRLC_TS_NO_ENDPOINTS" in codes(s)
    bad = ts_p(steps=())
    bad["resolved"]["default"]["phi_sh"] = 0.29
    assert "LRLC_TS_ENDPOINTS_INVALID" in codes(run_well(frame, bad)[1])
    r2, s2 = run_pipeline(frame.drop(columns=["GR"]), {**MAPPING, "GR": "None"},
                          {**PARAMS, "lrlc": ts_p(steps=())})
    assert "LRLC_TS_VSH_DEFAULTED" in codes(s2) and "VLAM" not in r2.columns


# ---- the laminated step ------------------------------------------------------------------
def test_laminated_step_recovers_the_forward_model_sw():
    frame, _ = laminated_well()
    r, s = run_well(frame, ts_p())
    body = interior(r)
    assert len(body) > 100
    np.testing.assert_allclose(body["SW"], SW_TRUE, atol=1e-6)
    assert (body["SW_BASE"] > SW_TRUE + 0.05).all()          # the uncorrected Sw is too high
    assert (body["RT_SAND"] > body["RT"]).all()
    assert "RT_SAND" in r.columns and r["RT_SW"].equals(r["RT_SAND"])
    rec = s["lrlc"]["chain"][0]
    assert rec["step"] == "laminated" and rec["counts"]["not_applicable"] == 0


def test_laminated_without_vlam_is_flagged():
    frame, _ = laminated_well()
    r, s = run_well(frame, lrlc_p(steps=["laminated"], zones=()))
    assert "LRLC_HAG_NO_VLAM" in codes(s) and r["RT_SAND"].isna().all()


def test_constant_vlam_needs_no_thomas_stieber():
    frame, _ = laminated_well()
    lrlc = lrlc_p(steps=["laminated"], zones=(), vlam_source="constant", vlam_const=0.3)
    r, s = run_well(frame, lrlc)
    assert r["RT_SAND"].notna().any() and "LRLC_HAG_NO_VLAM" not in codes(s)
    assert "VLAM" not in r.columns


def test_sensitivity_counts_become_issues():
    frame, _ = laminated_well()
    frame["RT"] = frame["RT"] * 1.25                         # pushes s towards the limit
    r, s = run_well(frame, ts_p())
    assert {"LRLC_STEP_INVALID", "LRLC_HAG_SENSITIVE"} & set(codes(s))


# ---- per-zone lists inside one segment and across segments --------------------------------
def test_per_zone_step_lists_in_one_segment(case):  # noqa: F811
    lrlc = lrlc_p(zone_steps={"UPPER": ["laminated"], "LOWER": []}, vlam_source="constant",
                  vlam_const=0.2)
    off = run(case)
    r, s = run(case, lrlc)
    upper, lower = r["ZONE"] == "UPPER", r["ZONE"] == "LOWER"
    assert r.loc[lower, "RT_SAND"].isna().all() and r.loc[upper, "RT_SAND"].notna().any()
    pd.testing.assert_series_equal(r.loc[lower, "RT_SW"], r.loc[lower, "RT"], check_exact=True,
                                   check_names=False)
    pd.testing.assert_series_equal(r.loc[lower, "SW"], off[0].loc[lower, "SW"], check_exact=True)
    assert not r.loc[upper, "SW"].equals(off[0].loc[upper, "SW"])
    assert s["lrlc"]["chain"] and {rec["zone"] for rec in s["lrlc"]["chain"]} == {"UPPER"}


# ---- sand basis ---------------------------------------------------------------------------
def test_bulk_basis_warns_about_double_counting():
    frame, _ = laminated_well()
    lrlc = ts_p(sw_basis="bulk")
    r, s = run_well(frame, lrlc, sw_methods=["Simandoux"], sw_primary_method="Simandoux")
    assert {"LRLC_LAM_VSH_DOUBLE", "LRLC_LAM_BULK_PHI"} <= set(codes(s))
    ra, sa = run_well(frame, lrlc)
    assert "LRLC_LAM_VSH_DOUBLE" not in codes(sa) and "LRLC_LAM_BULK_PHI" in codes(sa)
    assert (interior(ra)["SW"] > SW_TRUE + 0.02).all()       # bulk porosity: Sw biased high


def test_auto_basis_is_bulk_without_the_step():
    frame, _ = laminated_well()
    off = run_well(frame, lrlc_p(zones=()))
    r, s = run_well(frame, ts_p(steps=()))
    pd.testing.assert_series_equal(r["SW"], off[0]["SW"], check_exact=True)
    assert "LRLC_LAM_NO_SAND_BASIS" not in codes(s)


def test_sand_basis_counts_samples_without_ts_output():
    frame, _ = laminated_well()
    lrlc = lrlc_p(steps=["laminated"], zones=(), vlam_source="constant", vlam_const=0.2)
    r, s = run_well(frame, lrlc)
    assert "LRLC_LAM_NO_SAND_BASIS" in codes(s)              # sand basis, no TS output


# ---- pyrite -------------------------------------------------------------------------------
def pyritic_well(n=120, vpyr=0.03):
    depth = np.linspace(2000.0, 2060.0, n)
    phi, vsh = 0.20, 0.0
    rho_ma, rho_py, rho_f, u_f = 2.65, 4.99, 1.0, 0.36
    pef_ma, pef_py = 1.81, 16.97
    vma = 1.0 - phi - vpyr
    rhob = phi * rho_f + vma * rho_ma + vpyr * rho_py
    u = phi * u_f + vma * pef_ma * rho_ma + vpyr * pef_py * rho_py
    frame = pd.DataFrame({"DEPTH": depth, "GR": np.full(n, 20.0), "RHOB": rhob,
                          "PEF": u / rhob, "RT": np.full(n, 4.0)})
    return frame


def pyrite_p(f=0.5, rpy=0.1, **extra):
    lrlc = lrlc_p(steps=["pyrite"], zones=(), pyr_method="rhob_pef", pyr_f=f, pyr_rpy=rpy,
                  curves={"PEF": "PEF"}, **extra)
    lrlc["pyrite"] = {"enabled": True, "u_fluid": 0.36}
    return lrlc


def test_pyrite_step_on_a_synthetic_interval():
    frame = pyritic_well()
    off = run_well(frame, lrlc_p(zones=(), curves={"PEF": "PEF"}))
    r, s = run_well(frame, pyrite_p(), sw_primary_method="Archie")
    np.testing.assert_allclose(r["VPYR"], 0.03, atol=1e-9)
    expected = 1.0 / (1.0 / 4.0 - 0.5 * 0.03 / 0.1)
    np.testing.assert_allclose(r["RT_PYR"], expected, rtol=1e-9)
    assert (r["SW"] < off[0]["SW"]).all()
    assert {"LRLC_PYR_PEF_CAUTION", "LRLC_PYR_PHI_BIAS"} <= set(codes(s))
    assert "VPYR" not in off[0].columns


def test_pyrite_f_zero_changes_nothing_and_missing_pef_is_reported():
    frame = pyritic_well()
    off = run_well(frame, lrlc_p(zones=(), curves={"PEF": "PEF"}))
    r, s = run_well(frame, pyrite_p(f=0.0))
    pd.testing.assert_series_equal(r["SW"], off[0]["SW"], check_exact=True)
    assert "LRLC_PYR_F_ZERO" in codes(s)
    r2, s2 = run_well(frame.drop(columns=["PEF"]), pyrite_p(), )
    assert "LRLC_PYR_NO_INPUT" in codes(s2) and r2["VPYR"].isna().all()


# ---- Qv -----------------------------------------------------------------------------------
def test_qv_estimate_changes_only_waxman_smits():
    frame, _ = laminated_well()
    methods = {"sw_methods": ["Archie", "Waxman-Smits"], "sw_primary_method": "Waxman-Smits"}
    off = run_well(frame, lrlc_p(zones=()), **methods)
    r, s = run_well(frame, lrlc_p(zones=(), qv_source="estimate"), **methods)
    pd.testing.assert_series_equal(r["SW_ARCHIE"], off[0]["SW_ARCHIE"], check_exact=True)
    assert not r["SW_WS"].equals(off[0]["SW_WS"])
    assert r["QV_EST"].notna().any()
    assert "RT_SW" not in r.columns                          # no Rt step: RT_SW unchanged contract
    r2, s2 = run_well(frame, lrlc_p(zones=(), qv_source="estimate"))
    assert "LRLC_QV_NOT_USED" in codes(s2)
    pd.testing.assert_series_equal(r2["SW"], run_well(frame, lrlc_p(zones=()))[0]["SW"],
                                   check_exact=True)


def test_qv_fallback_for_out_of_range_samples():
    frame, _ = laminated_well()
    lrlc = lrlc_p(zones=(), qv_source="estimate")
    lrlc["qv"] = {"qv_max": 0.3}
    r, s = run_well(frame, lrlc, sw_methods=["Waxman-Smits"], sw_primary_method="Waxman-Smits")
    assert r["QV_EST"].isna().any() and "LRLC_QV_FALLBACK" in codes(s)
    assert r["SW"].notna().all()


def test_new_ladder_defaults_are_inert():
    assert LRLC_PARAM_DEFAULTS["sw_basis"] == "auto" and LRLC_PARAM_DEFAULTS["qv_source"] == "manual"
