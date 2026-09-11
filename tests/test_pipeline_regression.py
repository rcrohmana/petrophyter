"""Pipeline contract: pure callable, Qt-free, identical to the pre-refactor worker.

Golden files in ``tests/golden/`` were produced by the v1.5.0 ``AnalysisWorker``
before the pipeline was extracted (ADR 0015). Regenerate them only for a
deliberate formula or default change, with ``python -m tests.golden.generate``.
"""

import io
import json
import math
import pathlib
import subprocess
import sys

import pandas as pd
import pytest

from models.app_model import AppModel
from modules.formation_tops import FormationTops
from modules.pipeline import PARAM_DEFAULTS, PipelineError, run_pipeline
from services.analysis_service import AnalysisWorker
from tests.golden.cases import CASES, build_case

GOLDEN = pathlib.Path(__file__).resolve().parent / "golden"
ROOT = GOLDEN.parent.parent


def _load_golden(name):
    results = pd.read_csv(GOLDEN / f"{name}.results.csv", index_col=0)
    summary = json.loads((GOLDEN / f"{name}.summary.json").read_text())
    return results, summary


def _assert_summary_equal(actual, expected, path="summary"):
    assert set(actual) == set(expected), f"{path}: keys {set(actual) ^ set(expected)}"
    for key in expected:
        a, e = actual[key], expected[key]
        where = f"{path}.{key}"
        if isinstance(e, dict):
            _assert_summary_equal(a, e, where)
        elif isinstance(e, list):
            assert list(a) == e, where
        elif isinstance(e, float):
            if math.isnan(e):
                assert a is None or (isinstance(a, float) and math.isnan(a)), where
            else:
                assert a == pytest.approx(e, rel=1e-12, abs=1e-15), where
        else:
            assert a == e, where


def _assert_matches_golden(name, results, summary):
    exp_results, exp_summary = _load_golden(name)
    pd.testing.assert_frame_equal(
        results,
        exp_results,
        check_dtype=False,
        check_index_type=False,
        check_column_type=False,
        rtol=1e-12,
        atol=1e-15,
    )
    _assert_summary_equal(summary, exp_summary)


def _model_for(data, mapping, params, tops):
    model = AppModel()
    model.las_data = data
    model.curve_mapping = mapping
    model.formation_tops = tops
    for key, value in params.items():
        setattr(model, key, value)
    return model


@pytest.mark.parametrize("name", sorted(CASES))
def test_run_pipeline_matches_golden(name):
    data, mapping, params, tops = build_case(name)
    results, summary = run_pipeline(data, mapping, params, formation_tops=tops)
    _assert_matches_golden(name, results, summary)


@pytest.mark.parametrize("name", sorted(CASES))
def test_worker_matches_golden(name):
    data, mapping, params, tops = build_case(name)
    worker = AnalysisWorker(_model_for(data, mapping, params, tops))
    out, errors = [], []
    worker.signals.completed.connect(lambda r, s: out.append((r, s)))
    worker.signals.error.connect(errors.append)
    worker.run()
    assert not errors, errors
    _assert_matches_golden(name, *out[0])


def test_pipeline_module_never_imports_qt():
    code = (
        "import sys, modules.pipeline;"
        "bad = sorted(m for m in sys.modules if m.startswith('PyQt'));"
        "print(','.join(bad))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True
    )
    assert proc.stdout.strip() == "", f"pipeline pulled in Qt: {proc.stdout}"


def test_pipeline_does_not_mutate_input():
    data, mapping, params, tops = build_case("defaults_whole_well")
    before = data.copy()
    run_pipeline(data, mapping, params, formation_tops=tops)
    pd.testing.assert_frame_equal(data, before)


def test_progress_callback_is_monotonic_and_ends_at_100():
    data, mapping, params, tops = build_case("defaults_whole_well")
    seen = []
    run_pipeline(data, mapping, params, progress=lambda msg, pct: seen.append(pct), formation_tops=tops)
    assert seen == sorted(seen)
    assert seen[0] == 5 and seen[-1] == 100


def test_missing_params_take_defaults():
    data, mapping, _, _ = build_case("defaults_whole_well")
    results_a, summary_a = run_pipeline(data, mapping, {})
    results_b, summary_b = run_pipeline(data, mapping, dict(PARAM_DEFAULTS))
    pd.testing.assert_frame_equal(results_a, results_b)
    _assert_summary_equal(summary_a, summary_b)


def _tops_outside_data():
    """One formation far below the fixture interval (1000-1100 ft)."""
    tops = FormationTops()
    assert tops.read_tops_from_buffer(io.StringIO("Formation\tTop (ft)\tBottom (ft)\nDeep\t2000\t2100\n"))
    return tops


def test_empty_formation_selection_raises_pipeline_error():
    data, mapping, params, _ = build_case("per_formation_lower")
    params["selected_formations"] = ["Deep"]
    with pytest.raises(PipelineError, match="No data in selected formation"):
        run_pipeline(data, mapping, params, formation_tops=_tops_outside_data())


def test_none_data_raises_pipeline_error():
    with pytest.raises(PipelineError, match="No data loaded"):
        run_pipeline(None, dict(build_case("defaults_whole_well")[1]), {})


def test_to_params_is_detached_from_model():
    model = AppModel()
    model.sw_methods = ["Archie", "Indonesian"]
    params = model.to_params()
    assert set(PARAM_DEFAULTS) <= set(params)
    assert params["curve_mapping"] == model.curve_mapping
    params["sw_methods"].append("Simandoux")
    params["curve_mapping"]["GR"] = "CHANGED"
    assert model.sw_methods == ["Archie", "Indonesian"]
    assert model.curve_mapping["GR"] != "CHANGED"


def test_worker_snapshots_model_at_construction():
    data, mapping, params, tops = build_case("defaults_whole_well")
    model = _model_for(data, mapping, params, tops)
    worker = AnalysisWorker(model)
    model.vsh_cutoff = 0.0  # would zero out net pay if the worker read the live model
    model.las_data = None
    out = []
    worker.signals.completed.connect(lambda r, s: out.append(s))
    worker.run()
    assert out and out[0]["net_pay"] > 0


def test_worker_reports_pipeline_errors_without_traceback():
    data, mapping, params, _ = build_case("per_formation_lower")
    params["selected_formations"] = ["Deep"]
    worker = AnalysisWorker(_model_for(data, mapping, params, _tops_outside_data()))
    errors = []
    worker.signals.error.connect(errors.append)
    worker.run()
    assert errors == ["No data in selected formation(s)"]
