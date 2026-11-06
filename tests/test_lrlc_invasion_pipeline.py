"""Invasion step through the pipeline: off guard, documented columns only, golden truth recovery,
fallback modes and the chain order with the laminated step."""
import numpy as np
import pandas as pd
import pytest

from modules.pipeline import run_pipeline
from tests.golden.cases import INVASION_INTERVALS, build_case, invasion_truth
from tests.test_lrlc_invasion_glue import invaded_well
from tests.test_lrlc_pipeline import lrlc_p
from tests.test_lrlc_pipeline_l2 import MAPPING, PARAMS, laminated_well, ts_p

NEW_COLUMNS = {"RT_INV", "RXO_INV", "DI_INV", "RT_SW"}
# Baseline columns every active chain step writes (the uncorrected Sw and pay flag).
BASELINE = {"SW_BASE", "NET_PAY_BASE_FLAG"}
# Intervals of the golden case that are well posed: the first, second and last.
WELL_POSED = (INVASION_INTERVALS[0], INVASION_INTERVALS[1], INVASION_INTERVALS[4])


def run_case(steps=("invasion",), fallback="nan", lrlc=True):
    data, mapping, params, tops = build_case("lrlc_invasion")
    params = dict(params)
    if lrlc:
        resolved = params["lrlc"]["resolved"]
        resolved["default"] = {**resolved["default"], "rt_steps": list(steps),
                               "rt_fallback": fallback}
    else:
        params.pop("lrlc")
    return data, run_pipeline(data.copy(), mapping, params)


# ---- off guard and documented columns --------------------------------------------------------
def test_off_and_idle_add_no_invasion_columns():
    _, (off, off_s) = run_case(lrlc=False)
    _, (idle, idle_s) = run_case(steps=())
    assert not NEW_COLUMNS & set(off.columns)
    assert not (NEW_COLUMNS - {"RT_SW"}) & set(idle.columns)
    assert "invasion" not in idle_s["lrlc"]
    for col in ("SW", "PHIE", "VSH"):
        pd.testing.assert_series_equal(idle[col], off[col], check_exact=True)


def test_step_on_adds_only_the_documented_columns_and_keeps_rt():
    data, (idle, _) = run_case(steps=())
    _, (on, s) = run_case()
    assert set(on.columns) - set(idle.columns) >= {"RT_INV", "RXO_INV", "DI_INV"}
    assert (set(on.columns) - set(idle.columns)) - NEW_COLUMNS - BASELINE == set()
    np.testing.assert_array_equal(on["RT"].to_numpy(), data["RT"].to_numpy())
    assert "invasion" in s["lrlc"]


# ---- the golden case recovers the known Rt ----------------------------------------------------
def test_golden_case_recovers_the_known_rt_where_well_posed():
    data, (r, s) = run_case()
    depth = data["DEPTH"].to_numpy()
    rt_true, rxo_true, di_true = invasion_truth(depth)
    seen = 0
    for top, bottom, _, _, _ in WELL_POSED:
        sel = (depth >= top) & (depth < bottom)
        got = r["RT_INV"].to_numpy()[sel]
        ok = np.isfinite(got)
        assert ok.sum() > 0.8 * sel.sum()
        np.testing.assert_allclose(got[ok], rt_true[sel][ok], rtol=1e-6)
        np.testing.assert_allclose(r["RXO_INV"].to_numpy()[sel][ok], rxo_true[sel][ok], rtol=1e-6)
        np.testing.assert_allclose(r["DI_INV"].to_numpy()[sel][ok], di_true[sel][ok], rtol=1e-6)
        seen += ok.sum()
    assert seen > 100
    # samples missing a curve and the interval with di above the upper bound have no answer
    missing = r.index[np.isnan(data[["RT", "RM", "RS"]].to_numpy()).any(axis=1)]
    assert r.loc[missing, "RT_INV"].isna().all()
    top, bottom = INVASION_INTERVALS[3][:2]
    assert r["RT_INV"][(r["DEPTH"] >= top) & (r["DEPTH"] < bottom)].isna().all()
    row = s["lrlc"]["invasion"]["zones"][0]
    assert row["n_di_upper"] > 0 and row["n_nonunique"] > 0 and row["n_missing"] > 0


def test_fallback_previous_keeps_the_input_where_the_fit_is_invalid():
    data, (nan_r, _) = run_case(fallback="nan")
    _, (prev_r, _) = run_case(fallback="previous")
    bad = nan_r["RT_INV"].isna() & data["RT"].notna()
    assert bad.any()
    assert nan_r.loc[bad, "RT_SW"].isna().all()
    np.testing.assert_array_equal(prev_r.loc[bad, "RT_SW"].to_numpy(), data.loc[bad, "RT"].to_numpy())
    good = nan_r["RT_INV"].notna()
    np.testing.assert_array_equal(prev_r.loc[good, "RT_SW"].to_numpy(),
                                  nan_r.loc[good, "RT_SW"].to_numpy())


# ---- chain order with the laminated step ------------------------------------------------------
def test_laminated_reads_the_invasion_corrected_rt():
    invaded, rt_true = invaded_well()
    clean, _ = laminated_well()
    lrlc = ts_p(steps=("invasion", "laminated"))
    lrlc["curves"].update(RM="RM", RS="RS")
    chained, s = run_pipeline(invaded.copy(), dict(MAPPING), {**PARAMS, "lrlc": lrlc})
    assert [c["step"] for c in s["lrlc"]["chain"]] == ["invasion", "laminated"]
    alone, _ = run_pipeline(clean.copy(), dict(MAPPING), {**PARAMS, "lrlc": ts_p()})
    ok = chained["RT_SAND"].notna() & alone["RT_SAND"].notna()
    assert ok.sum() > 100
    np.testing.assert_allclose(chained["RT_SAND"][ok], alone["RT_SAND"][ok], rtol=1e-3)
    # without the invasion step the laminated step would read the invaded deep curve
    no_inv, _ = run_pipeline(invaded.copy(), dict(MAPPING), {**PARAMS, "lrlc": ts_p()})
    assert not np.allclose(no_inv["RT_SAND"][ok], chained["RT_SAND"][ok], rtol=1e-2)
