"""Regenerate golden pipeline outputs.

Run only when a deliberate formula or default change is made, and commit the
diff with the change that caused it:

    QT_QPA_PLATFORM=offscreen .venv/bin/python -m tests.golden.generate
"""

import json
import pathlib

import numpy as np

from models.app_model import AppModel
from services.analysis_service import AnalysisWorker
from tests.golden.cases import CASES, build_case

HERE = pathlib.Path(__file__).resolve().parent


def run_worker(data, mapping, params, tops):
    model = AppModel()
    model.las_data = data
    model.curve_mapping = mapping
    model.formation_tops = tops
    for key, value in params.items():
        assert hasattr(model, key), key
        setattr(model, key, value)
    out, errors = [], []
    worker = AnalysisWorker(model)
    worker.signals.completed.connect(lambda r, s: out.append((r, s)))
    worker.signals.error.connect(errors.append)
    worker.run()
    assert not errors, errors
    return out[0]


def _json_default(value):
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(type(value))


def main():
    for name in CASES:
        results, summary = run_worker(*build_case(name))
        results.to_csv(HERE / f"{name}.results.csv", float_format="%.17g")
        (HERE / f"{name}.summary.json").write_text(
            json.dumps(summary, indent=1, sort_keys=True, default=_json_default) + "\n"
        )
        print(f"{name}: {results.shape[0]} rows, {results.shape[1]} cols")


if __name__ == "__main__":
    main()
