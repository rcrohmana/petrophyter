"""Save -> reset -> load -> run reproduces the results (P0-Hardening H6a, spec 4.5).

Every well is written to LAS files first (the shape ``test_session_v2._load`` builds), so the
restore re-reads real files. Results and summaries are compared exactly (rtol 1e-12), which
would catch a restored merged well that used another well's step.
"""

import os

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from models.app_model import AppModel
from modules.las_handler import LASHandler
from modules.pipeline import run_pipeline
from services.analysis_service import snapshot_well
from services.load_service import build_well, parse_file
from services.session_service import SessionService, attach_tops
from tests.test_session_v2 import TOPS_TEXT, _write

RTOL = 1e-12


def _run(model, ds):
    snap = snapshot_well(model, ds)
    return run_pipeline(snap.data, snap.curve_mapping, snap.params,
                        formation_tops=snap.formation_tops)


def _merged(model, tmp_path, tag, step, gap):
    files = [
        parse_file(_write(tmp_path, f"{tag}1.las", well=tag, top=1000.0, bottom=1040.0)),
        parse_file(_write(tmp_path, f"{tag}2.las", well=tag, top=1030.0, bottom=1080.0)),
    ]
    result = LASHandler().merge_las_files(
        [f.parser for f in files], file_identifiers=[f.name for f in files],
        step_ft=step, gap_limit_ft=gap)
    ds = build_well(files, result)
    model.add_well(ds, activate=False)
    return ds


def _same(a, b, path="summary"):
    if isinstance(a, dict):
        assert isinstance(b, dict) and a.keys() == b.keys(), path
        for key in a:
            _same(a[key], b[key], f"{path}.{key}")
    elif isinstance(a, pd.DataFrame):
        pd.testing.assert_frame_equal(a, b, rtol=RTOL, atol=0)
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b)):
            _same(x, y, f"{path}[{i}]")
    elif isinstance(a, (float, np.floating)):
        assert np.isclose(a, b, rtol=RTOL, atol=0, equal_nan=True), path
    elif isinstance(a, np.ndarray):
        np.testing.assert_allclose(a, b, rtol=RTOL, equal_nan=True, err_msg=path)
    else:
        assert a == b, path


@pytest.mark.parametrize("steps", [
    pytest.param(((0.5, 5.0), (0.5, 5.0)), id="same-step"),
    pytest.param(((0.25, 3.0), (1.0, 8.0)), id="different-steps", marks=pytest.mark.xfail(
        strict=True, reason="needs H1 merge_recipe from build_well")),
])
def test_save_load_run_reproduces_results(tmp_path, steps):
    model = AppModel()
    (step_a, gap_a), (step_b, gap_b) = steps
    first = _merged(model, tmp_path, "ALPHA", step_a, gap_a)
    second = _merged(model, tmp_path, "BETA", step_b, gap_b)
    model.merge_step, model.merge_gap_limit = step_b, gap_b      # the last merge, as in the app
    single = build_well([parse_file(_write(tmp_path, "g.las", well="GAMMA", bottom=1070.0))])
    model.add_well(single, activate=False)
    tops = tmp_path / "gamma_tops.txt"
    tops.write_text(TOPS_TEXT)
    assert attach_tops(single, str(tops)) == []
    single.analysis_mode = "Per-Formation"
    single.selected_formations = ["Upper"]
    model.set_entry("n", "manual", 2.2, scope="well", zone="UPPER", well=single.key)
    model.set_entry("rw", "manual", 0.033, scope="well", well=first.key)
    keys = [first.key, second.key, single.key]
    assert len(first.las_data) != len(second.las_data) or steps[0] == steps[1]

    before = {k: _run(model, model.project.get(k)) for k in keys}
    rows = {k: len(model.project.get(k).las_data) for k in keys}

    path = str(tmp_path / "s.json")
    svc = SessionService()
    assert svc.save_session(model, path)
    model.reset()
    model.merge_step, model.merge_gap_limit = 0.9, 40.0          # unrelated global values
    data = svc.load_session(path)
    assert svc.apply_session_to_model(model, data)
    svc.restore_wells(model, data)                               # synchronous wrapper

    assert model.project.keys() == keys
    for key in keys:
        ds = model.project.get(key)
        assert len(ds.las_data) == rows[key], key
        results, summary = _run(model, ds)
        _same(before[key][0], results)
        _same(before[key][1], summary)
