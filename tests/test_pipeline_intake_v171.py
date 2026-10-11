"""v1.7.1 pipeline items: I1/I2 non-positive masking, I11 no fabricated porosity,
I12 input curves named like results, I13 unmatched formation selection."""
import numpy as np
import pandas as pd
import pytest

from modules.pipeline import PipelineError, run_pipeline
from tests.golden.cases import FULL_MAPPING, fixture_frame, make_tops


def _frame():
    return fixture_frame("sample_log_data")


# Manual baseline, Rw and Rsh so removing rows cannot move the auto estimates.
FIXED = {"vsh_baseline_method": "Custom (Manual)", "gr_min_manual": 20.0,
         "gr_max_manual": 120.0, "rw_mode": "manual", "rsh_mode": "manual"}


def _run(data, params=None, tops=None, mapping=None):
    return run_pipeline(data, dict(mapping or FULL_MAPPING), params or {}, formation_tops=tops)


# ---- I1 / I2 ------------------------------------------------------------------------
def test_rt_zero_and_negative_become_nan_sw_and_other_rows_unchanged():
    data = _frame()
    data.loc[50, "RT"] = 0.0
    data.loc[60, "RT"] = -5.0
    results, summary = _run(data, FIXED)
    assert np.isnan(results.loc[50, "SW"]) and np.isnan(results.loc[60, "SW"])
    assert any("RT: 2 samples" in w and "NaN" in w for w in summary["warnings"])
    # The caller's frame is not mutated.
    assert data.loc[50, "RT"] == 0.0 and data.loc[60, "RT"] == -5.0

    removed = _frame().drop(index=[50, 60]).reset_index(drop=True)
    expected, _ = _run(removed, FIXED)
    keep = results.drop(index=[50, 60]).reset_index(drop=True)
    assert np.allclose(keep["SW"].to_numpy(float), expected["SW"].to_numpy(float),
                       equal_nan=True)


def test_rhob_nonpositive_gives_nan_phid_and_one_still_gives_half():
    data = _frame()
    data.loc[10, "RHOB"] = 0.0
    data.loc[11, "RHOB"] = -1.0
    data.loc[12, "RHOB"] = 1.0
    results, summary = _run(data)
    assert np.isnan(results.loc[10, "PHID"]) and np.isnan(results.loc[11, "PHID"])
    assert results.loc[12, "PHID"] == pytest.approx(0.5)   # still clipped, not masked
    assert any("RHOB: 2 samples" in w for w in summary["warnings"])


def test_dt_nonpositive_is_masked_and_counted():
    data = _frame()
    data.loc[5, "DT"] = 0.0
    results, summary = _run(data)
    assert any("DT: 1 samples" in w for w in summary["warnings"])
    assert np.isnan(results.loc[5, "PHIS"])


def test_clean_data_adds_no_masking_warning():
    _, summary = _run(_frame())
    assert not [w for w in summary["warnings"] if "set to NaN" in w]


# ---- I11 ----------------------------------------------------------------------------
def test_partial_porosity_is_kept_nan_elsewhere_and_never_pay():
    n = 20
    depth = np.arange(1000.0, 1000.0 + n)
    rhob = np.full(n, np.nan)
    rhob[:8] = 2.3
    data = pd.DataFrame({"DEPTH": depth, "GR": np.linspace(30.0, 100.0, n), "RHOB": rhob,
                         "NPHI": np.full(n, np.nan), "RT": np.full(n, 50.0)})
    mapping = {"GR": "GR", "RHOB": "RHOB", "NPHI": "NPHI", "DT": "None", "RT": "RT"}
    results, summary = _run(data, mapping=mapping)
    assert "PHIE" in results.columns
    assert results["PHIE"].notna().sum() == 8
    assert results.loc[8:, "PHIE"].isna().all()
    assert not results.loc[8:, "NET_PAY_FLAG"].astype(bool).any()
    assert results.loc[8:, "SW"].isna().all()
    assert any("covers 40 %" in w for w in summary["warnings"])
    valid = results["PHIE"].dropna()
    assert not (valid == 0.15).all()


def test_no_porosity_curve_gives_all_nan_phie():
    n = 10
    data = pd.DataFrame({"DEPTH": np.arange(1000.0, 1000.0 + n), "GR": np.full(n, 30.0),
                         "RT": np.full(n, 50.0)})
    mapping = {"GR": "GR", "RHOB": "None", "NPHI": "None", "DT": "None", "RT": "RT"}
    results, summary = _run(data, mapping=mapping)
    assert results["PHIE"].isna().all()
    assert not any("0.15" in w for w in summary["warnings"])
    assert any("no valid samples" in w for w in summary["warnings"])


# ---- I12 ----------------------------------------------------------------------------
def test_input_curves_named_like_results_are_renamed_in():
    data = _frame()
    data["PHIE"] = 0.11
    data["SW"] = 0.9
    results, summary = _run(data)
    assert results.columns.is_unique
    assert "PHIE_IN" in results.columns and "SW_IN" in results.columns
    assert (results["PHIE_IN"] == 0.11).all() and (results["SW_IN"] == 0.9).all()
    assert not (results["PHIE"] == 0.11).all()
    assert any("PHIE_IN" in w and "SW_IN" in w for w in summary["warnings"])


def test_no_clash_no_rename_warning():
    results, summary = _run(_frame())
    assert not [c for c in results.columns if c.endswith("_IN")]
    assert not [w for w in summary["warnings"] if "kept as" in w]


# ---- I13 ----------------------------------------------------------------------------
def test_unmatched_selection_raises():
    params = {"analysis_mode": "Per-Formation", "selected_formations": ["Missing"]}
    with pytest.raises(PipelineError, match=r"none of the selected formations \(Missing\)"):
        _run(_frame(), params, make_tops())


def test_partial_selection_analyses_matched_and_warns():
    params = {"analysis_mode": "Per-Formation", "selected_formations": ["Upper", "Missing"]}
    results, summary = _run(_frame(), params, make_tops())
    assert len(results) > 0 and results["DEPTH"].max() < 1040 + 1e-9
    assert any("Missing" in w for w in summary["warnings"])


def test_filter_by_formations_unmatched_is_empty_and_reports_missing():
    tops = make_tops()
    data = _frame()
    assert len(tops.filter_by_formations(data, ["Missing"])) == 0
    assert tops.missing_formations(["upper", "Missing"]) == ["Missing"]
