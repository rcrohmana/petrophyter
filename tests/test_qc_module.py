"""
Tests for modules/qc_module.py quality scoring.

Imports the production QCModule directly (previously there were no tests for
this module). Pins the scoring fixes:
  - a 100%-null curve scores 0, not the old phantom floor of 60
  - an empty DataFrame does not score a perfect 100
  - null_count is a plain Python int (matches the type hint / outlier_count)
  - the unused CURVE_RANGES constant has been removed
"""

import numpy as np
import pandas as pd
import pytest

from modules.qc_module import QCModule, CurveQCResult, DataQCReport


# --------------------------------------------------------------------------- #
# High finding #1 - a fully-null curve is unusable and must score 0
# --------------------------------------------------------------------------- #
def test_all_null_curve_scores_zero():
    data = pd.DataFrame({
        'DEPTH': [1000.0, 1001.0, 1002.0],
        'GR': [np.nan, np.nan, np.nan],
    })
    report = QCModule(data, 'W1').run_qc()
    gr = report.curve_results['GR']
    assert gr.valid_points == 0
    assert gr.null_percentage == pytest.approx(100.0)
    assert gr.quality_score == 0.0  # was 60.0 before the fix


# --------------------------------------------------------------------------- #
# High finding #2 - an empty (0-row) DataFrame must not score a perfect 100
# --------------------------------------------------------------------------- #
def test_empty_dataframe_does_not_score_100():
    data = pd.DataFrame({
        'DEPTH': pd.Series([], dtype=float),
        'GR': pd.Series([], dtype=float),
    })
    report = QCModule(data).run_qc()
    gr = report.curve_results['GR']
    assert gr.total_points == 0
    assert gr.null_percentage == pytest.approx(100.0)
    assert gr.quality_score == 0.0
    assert report.overall_quality_score == 0.0


# --------------------------------------------------------------------------- #
# Quick win - null_count is a plain python int, like outlier_count
# --------------------------------------------------------------------------- #
def test_null_count_is_python_int():
    data = pd.DataFrame({
        'DEPTH': [1.0, 2.0, 3.0, 4.0],
        'GR': [50.0, np.nan, 60.0, np.nan],
    })
    report = QCModule(data).run_qc()
    gr = report.curve_results['GR']
    assert type(gr.null_count) is int
    assert gr.null_count == 2


# --------------------------------------------------------------------------- #
# High finding #3 - the unused CURVE_RANGES constant is gone
# --------------------------------------------------------------------------- #
def test_curve_ranges_removed():
    assert not hasattr(QCModule, 'CURVE_RANGES')


# --------------------------------------------------------------------------- #
# Sanity: a clean, complete curve still scores high; scoring stays bounded
# --------------------------------------------------------------------------- #
def test_clean_curve_scores_high():
    rng = np.random.default_rng(0)
    n = 200
    data = pd.DataFrame({
        'DEPTH': np.linspace(1000, 1100, n),
        'GR': rng.normal(75, 10, n),  # no nulls, few outliers
    })
    report = QCModule(data).run_qc()
    gr = report.curve_results['GR']
    assert gr.null_percentage == pytest.approx(0.0)
    assert gr.quality_score >= 90.0
    assert 0.0 <= gr.quality_score <= 100.0


def test_partial_null_curve_scored_between_zero_and_hundred():
    n = 100
    gr = np.full(n, 60.0)
    gr[:50] = np.nan  # 50% null
    data = pd.DataFrame({'DEPTH': np.linspace(1000, 1100, n), 'GR': gr})
    report = QCModule(data).run_qc()
    res = report.curve_results['GR']
    assert res.valid_points == 50
    assert res.null_percentage == pytest.approx(50.0)
    # Penalised for nulls but still has valid data -> strictly between 0 and 100.
    assert 0.0 < res.quality_score < 100.0


def test_run_qc_end_to_end_realistic():
    rng = np.random.default_rng(1)
    n = 300
    data = pd.DataFrame({
        'DEPTH': np.linspace(2000, 2150, n),
        'GR': rng.normal(70, 15, n),
        'RHOB': rng.normal(2.4, 0.1, n),
        'NPHI': rng.normal(0.2, 0.05, n),
    })
    report = QCModule(data, 'DEMO').run_qc()
    assert isinstance(report, DataQCReport)
    assert set(report.curves_available) == {'GR', 'RHOB', 'NPHI'}
    assert report.curves_missing == []  # all required curves present
    assert 0.0 <= report.overall_quality_score <= 100.0
    for res in report.curve_results.values():
        assert isinstance(res, CurveQCResult)
        assert 0.0 <= res.quality_score <= 100.0
