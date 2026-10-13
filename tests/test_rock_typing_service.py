"""Rock typing service: worker, proposal shape, fingerprint, apply (P1 spec sections 3, 5.2, 5.3)."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import copy
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from models.app_model import AppModel
from modules import rock_typing as rt
from services import rock_typing_service as svc


def _handler(n_per_pop, seed, centres=(-0.5, 0.0, 0.6)):
    rng = np.random.default_rng(seed)
    lf = np.concatenate([rng.normal(c, 0.05, n_per_pop) for c in centres])
    phi = rng.uniform(0.10, 0.30, len(lf))
    k = rt.perm_from_fzi(10.0 ** lf, phi)
    depth = 1000.0 + np.arange(len(lf)) * 0.5
    return SimpleNamespace(
        data=pd.DataFrame({"depth": depth, "por": phi, "perm": k}),
        depth_col="depth", porosity_col="por", perm_col="perm", depth_is_tvd=False,
        excluded_rows=[], excluded_row_wells={}, spellings=[])


def _model(n_per_pop=(20, 20, 20)):
    model = AppModel()
    for i, n in enumerate(n_per_pop):
        key = f"WELL:W{i}"
        model.project._wells[key] = SimpleNamespace(
            key=key, display_name=f"W{i}", core_data=_handler(n, i), formation_tops=None)
    return model


def _run_sync(worker):
    done, errors, cancelled = [], [], []
    worker.signals.completed.connect(done.append)
    worker.signals.error.connect(errors.append)
    worker.signals.cancelled.connect(lambda: cancelled.append(True))
    worker.run()       # the pool only adds a thread; the logic is the same
    return done, errors, cancelled


def test_worker_completes_with_spec_shape(qtbot):
    model = _model()
    before = copy.deepcopy(model.project.rock_types)
    worker = svc.RockTypingWorker.from_model(model, n_rt=3)
    from PyQt6.QtCore import QThreadPool
    pool = QThreadPool()
    with qtbot.waitSignal(worker.signals.completed, timeout=60000) as blocker:
        pool.start(worker)
    prop = blocker.args[0]
    pool.waitForDone()
    assert prop["version"] == 1 and prop["method"] == "fzi"
    assert prop["feature"] == "log10_fzi" and prop["fit_scope"] == "project"
    pooled = prop["sets"]["*"]
    assert pooled["n_rt"] == 3
    assert pooled["centers"] == pytest.approx([-0.5, 0.0, 0.6], abs=0.05)
    assert pooled["n_samples"] == [60, 60, 60]
    assert prop["fit_report"]["valid"] == 180
    assert set(prop["fingerprint"]["core"]) == {"WELL:W0", "WELL:W1", "WELL:W2"}
    assert set(prop) == {"version", "method", "feature", "fit_scope", "sets", "settings",
                         "fingerprint", "fit_report", "_display"}
    disp = prop["_display"]
    assert isinstance(disp["table"], pd.DataFrame) and len(disp["table"]) == 180
    assert disp["suggestion"]["n_rt"] == 3
    assert before is None and model.project.rock_types is None      # never writes the model


def test_proposal_without_display_is_plain_json():
    done, errors, _ = _run_sync(svc.RockTypingWorker.from_model(_model(), n_rt=3))
    assert not errors
    stripped = {k: v for k, v in done[0].items() if k != "_display"}
    assert json.loads(json.dumps(stripped)) == stripped


def test_suggested_count_used_when_none():
    done, errors, _ = _run_sync(svc.RockTypingWorker.from_model(_model(), n_rt=None))
    assert not errors and done[0]["sets"]["*"]["n_rt"] == 3


def test_too_few_rows_reaches_error():
    model = _model((2, 2, 2))
    done, errors, _ = _run_sync(svc.RockTypingWorker.from_model(model, n_rt=3))
    assert not done and len(errors) == 1
    assert "at least 20" in errors[0] and "18" in errors[0]


def test_no_core_reaches_error():
    done, errors, _ = _run_sync(svc.RockTypingWorker.from_model(AppModel(), n_rt=3))
    assert not done and errors


def test_cancel_before_run_emits_cancelled_only():
    worker = svc.RockTypingWorker.from_model(_model(), n_rt=3)
    worker.cancel()
    done, errors, cancelled = _run_sync(worker)
    assert not done and not errors and cancelled == [True]


def test_cancel_mid_run_at_progress():
    worker = svc.RockTypingWorker.from_model(_model(), n_rt=3)
    worker.signals.progress.connect(lambda msg, pct: worker.cancel() if pct >= 40 else None)
    done, errors, cancelled = _run_sync(worker)
    assert not done and not errors and cancelled == [True]


def test_well_scope_thin_well_falls_back_to_pooled():
    model = _model((20, 20, 20))
    thin = "WELL:THIN"
    model.project._wells[thin] = SimpleNamespace(
        key=thin, display_name="THIN", core_data=_handler(3, 9), formation_tops=None)
    done, errors, _ = _run_sync(
        svc.RockTypingWorker.from_model(model, n_rt=3, fit_scope="well"))
    assert not errors
    sets = done[0]["sets"]
    assert set(sets) == {"*", "WELL:W0", "WELL:W1", "WELL:W2"}
    assert thin in done[0]["fit_report"]["fallback"]
    assert done[0]["_display"]["fallback"] == done[0]["fit_report"]["fallback"]


def test_zone_scope_uses_zones_and_skips_unzoned():
    model = _model((20, 20, 20))
    # Two named zones over the core depth range of every well.
    tops = SimpleNamespace(formations=[SimpleNamespace(name="Upper", top_depth=990.0, bottom_depth=1015.0),
                                       SimpleNamespace(name="Lower", top_depth=1015.0, bottom_depth=1100.0)])
    for w in model.project.wells:
        w.formation_tops = tops
    done, errors, _ = _run_sync(
        svc.RockTypingWorker.from_model(model, n_rt=2, fit_scope="zone",
                                        settings={"min_per_rt": 3}))
    assert not errors
    assert "*" in done[0]["sets"] and "(unzoned)" not in done[0]["sets"]


def test_r35_method_shape():
    done, errors, _ = _run_sync(svc.RockTypingWorker.from_model(_model(), method="r35"))
    assert not errors
    prop = done[0]
    assert prop["feature"] == "log10_r35"
    assert prop["sets"]["*"]["n_rt"] == 5
    assert prop["sets"]["*"]["boundaries"] == rt.R35_BOUNDARIES


def test_apply_definitions_writes_plain_json_and_notifies(qtbot):
    model = _model()
    done, _, _ = _run_sync(svc.RockTypingWorker.from_model(model, n_rt=3))
    proposal = done[0]
    proposal["sets"]["*"]["centers"] = tuple(proposal["sets"]["*"]["centers"])
    proposal["sets"]["*"]["n_rt"] = np.int64(3)
    seen = []
    model.parameters_changed.connect(lambda: seen.append(1))
    with qtbot.waitSignal(model.dirty_changed):
        stored = svc.apply_definitions(model, proposal)
    assert seen == [1] and model.dirty
    assert model.project.rock_types is stored
    assert "_display" not in stored and "_display" in proposal        # input untouched
    assert json.loads(json.dumps(stored)) == stored
    assert json.dumps(stored, default=str) == json.dumps(
        json.loads(json.dumps(stored)), default=str)
    assert type(stored["sets"]["*"]["n_rt"]) is int


def test_fingerprint_stale_after_core_edit_and_settings():
    model = _model()
    done, _, _ = _run_sync(svc.RockTypingWorker.from_model(model, n_rt=3))
    defs = svc.apply_definitions(model, done[0])
    assert svc.core_fingerprint(model, defs["settings"]) == defs["fingerprint"]
    assert not svc.fingerprint_is_stale(defs, model)
    model.project.get("WELL:W1").core_data.data.loc[5, "perm"] *= 2.0
    assert svc.fingerprint_is_stale(defs, model)
    model.project.get("WELL:W1").core_data.data.loc[5, "perm"] /= 2.0
    assert not svc.fingerprint_is_stale(defs, model)
    # Display-only settings do not matter; a fit setting does.
    assert svc._settings_digest({"lorenz": False}) == svc._settings_digest({})
    assert svc._settings_digest({"ob_k_factor": 0.8}) != svc._settings_digest({})
    assert not svc.fingerprint_is_stale(None, model)


def test_fingerprint_reflects_row_removal():
    model = _model()
    done, _, _ = _run_sync(svc.RockTypingWorker.from_model(model, n_rt=3))
    defs = svc.apply_definitions(model, done[0])
    h = model.project.get("WELL:W0").core_data
    h.data = h.data.iloc[:-1].copy()
    assert svc.fingerprint_is_stale(defs, model)
