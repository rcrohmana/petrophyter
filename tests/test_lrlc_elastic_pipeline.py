"""Elastic-attribute screening as the well-level pass of the pipeline: score +1 only where flagged,
LRLC_FLAG untouched, no DTS -> no columns and an info code, summary keys only when it ran."""
import numpy as np
import pandas as pd
import pytest

from modules.pipeline import run_pipeline
from tests.test_lrlc_pipeline import lrlc_p

MAPPING = {"GR": "GR", "RHOB": "RHOB", "NPHI": "None", "DT": "DT", "RT": "RT"}
PARAMS = {
    "vsh_baseline_method": "Custom (Manual)", "gr_min_manual": 20.0, "gr_max_manual": 120.0,
    "sw_methods": ["Archie"], "sw_primary_method": "Archie", "rw": 0.05, "rw_mode": "manual",
    "rsh": 2.0, "rsh_mode": "manual", "a": 1.0, "m": 2.0, "n": 2.0,
}
GAS = (1140.0, 1160.0)


def elastic_well(with_dts=True):
    """Clean sands in shale: wet sands on one elastic trend, a gas sand 12 percent slower in DT with
    unchanged DTS (so both AI and Vp/Vs fall below the wet trend). Deterministic."""
    depth = np.linspace(1000.0, 1200.0, 401)
    sand = np.zeros(len(depth), dtype=bool)
    for top, bottom in ((1010, 1050), (1060, 1100), (1110, 1170), (1180, 1195)):
        sand |= (depth >= top) & (depth < bottom)
    phi = np.where(sand, 0.15 + 0.12 * (0.5 + 0.5 * np.sin(depth / 9.0)), 0.04)
    gas = (depth >= GAS[0]) & (depth < GAS[1])
    dt = 55.0 + 130.0 * phi
    dts = 100.0 + 190.0 * phi
    rhob = 2.65 - 1.65 * phi
    dt = np.where(gas, dt * 1.12, dt)
    rhob = np.where(gas, rhob - 0.05, rhob)
    sw = np.where(gas, 0.30, 1.0)
    rt = np.where(sand, 0.05 / (phi ** 2 * sw ** 2), 2.0)
    frame = pd.DataFrame({"DEPTH": depth, "GR": np.where(sand, 25.0, 110.0), "RHOB": rhob,
                          "DT": dt, "RT": rt})
    if with_dts:
        frame["DTS"] = dts
    return frame


def run(frame, elastic=True, dts=True, **ladder):
    ladder = {"screen_rt_max": 0.3, **ladder}      # the wet sands are not LRLC candidates
    lrlc = lrlc_p(zones=(), curves={"DTS": "DTS" if dts else None}, **ladder)
    if elastic:
        lrlc["elastic"] = {"enabled": True}
    return run_pipeline(frame.copy(), dict(MAPPING), {**PARAMS, "lrlc": lrlc})


def codes(summary):
    return [i["code"] for i in summary["issues"]]


@pytest.fixture(scope="module")
def pair():
    frame = elastic_well()
    return frame, run(frame, elastic=False), run(frame)


def test_score_gains_one_exactly_where_flagged_and_lrlc_flag_is_identical(pair):
    _, (off, s_off), (on, s_on) = pair
    flagged = on["ELASTIC_FLAG"] == 1
    assert flagged.sum() > 10
    assert on.loc[flagged, "DEPTH"].between(GAS[0], GAS[1]).all()
    np.testing.assert_array_equal((on["LRLC_SCORE"] - off["LRLC_SCORE"]).to_numpy(),
                                  on["ELASTIC_FLAG"].to_numpy())
    for column in ("LRLC_FLAG", "SW", "NET_PAY_FLAG", "NET_RES_FLAG", "PHIE"):
        pd.testing.assert_series_equal(on[column], off[column], check_exact=True)
    assert pd.api.types.is_integer_dtype(on["ELASTIC_FLAG"])
    assert {"AI", "VPVS", "ELASTIC_FLAG"} <= set(on.columns)
    assert not {"AI", "VPVS", "ELASTIC_FLAG"} & set(off.columns)
    assert on["AI"].notna().all() and on["VPVS"].notna().all()


def test_ai_and_vpvs_follow_the_equations(pair):
    frame, _, (on, _) = pair
    np.testing.assert_allclose(on["AI"], frame["RHOB"] * 304800.0 / frame["DT"], rtol=1e-12)
    np.testing.assert_allclose(on["VPVS"], frame["DTS"] / frame["DT"], rtol=1e-12)


def test_summary_keys_only_when_the_pass_ran(pair):
    _, (_, s_off), (_, s_on) = pair
    assert "elastic" not in s_off["lrlc"] and "ELASTIC" not in s_off["lrlc"]["screening"]["criteria"]
    assert "score_max" not in s_off["lrlc"]["screening"]
    block = s_on["lrlc"]
    assert block["screening"]["score_max"] == 7
    crit = block["screening"]["criteria"]["ELASTIC"]
    assert crit["met"] == block["elastic"]["counts"]["flag"] > 10 and crit["evaluable"] > crit["met"]
    assert block["elastic"]["curves"] == {"DT": "DT", "DTS": "DTS", "RHOB": "RHOB"}
    assert block["elastic"]["wet"]["source"] == "sw"
    assert not [k for k in block["params"]["default"] if k.startswith("el_")]


def test_no_dts_writes_no_columns_and_keeps_the_info_code():
    frame = elastic_well(with_dts=False)
    on, s = run(frame, dts=False)
    off, _ = run(frame, elastic=False, dts=False)
    assert not {"AI", "VPVS", "ELASTIC_FLAG"} & set(on.columns)
    pd.testing.assert_series_equal(on["LRLC_SCORE"], off["LRLC_SCORE"], check_exact=True)
    codes_ = [i for i in s["issues"] if i["code"] == "LRLC_ELASTIC_NO_DTS"]
    assert len(codes_) == 1 and codes_[0]["severity"] == "info" and "DTS" in codes_[0]["text"]
    assert "elastic" not in s["lrlc"] and "score_max" not in s["lrlc"]["screening"]


def test_us_per_m_curves_skip_the_stage_with_a_warning():
    frame = elastic_well()
    frame["DT"] = frame["DT"] / 0.3048
    frame["DTS"] = frame["DTS"] / 0.3048
    on, s = run(frame)
    assert "ELASTIC_FLAG" not in on.columns
    issue = [i for i in s["issues"] if i["code"] == "LRLC_ELASTIC_UNITS"]
    assert len(issue) == 1 and issue[0]["severity"] == "warning"


def test_threshold_settings_resolve_per_well_when_no_zones_are_given():
    frame = elastic_well()
    strict, _ = run(frame, el_ai_drop=0.5)
    assert strict["ELASTIC_FLAG"].sum() == 0
    wide, _ = run(frame, el_mode="ai", el_ai_drop=0.01)
    assert wide["ELASTIC_FLAG"].sum() >= run(frame)[0]["ELASTIC_FLAG"].sum()


def test_switch_off_means_no_elastic_work_even_with_dts_mapped():
    frame = elastic_well()
    r, s = run(frame, elastic=False)
    assert not {"AI", "VPVS", "ELASTIC_FLAG"} & set(r.columns)
    assert not [c for c in codes(s) if c.startswith("LRLC_ELASTIC")]


def test_input_curves_named_ai_or_vpvs_are_kept_as_in():
    frame = elastic_well()
    frame["VPVS"] = 7.0
    frame["AI"] = 1.0
    out, s = run(frame)
    assert (out["VPVS_IN"] == 7.0).all() and (out["AI_IN"] == 1.0).all()
    assert out["VPVS"].dropna().between(1.15, 4.0).all()
    assert "INPUT_RENAMED" in codes(s)
