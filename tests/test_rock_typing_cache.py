"""Per-well core-label cache behind ``AppModel.params_for_well`` (rock typing on)."""

import copy
import time

import pytest

import modules.rock_typing as rt
from models.app_model import AppModel
from models.project import WellDataset
from services import rock_typing_service as svc
from tests.golden.cases import FULL_MAPPING, fixture_frame, make_tops
from tests.test_rock_typing_pipeline import _core, _model


@pytest.fixture
def calls(monkeypatch):
    counter = {"n": 0}
    real = rt.core_labels

    def counting(ci, rt_):
        counter["n"] += 1
        return real(ci, rt_)

    monkeypatch.setattr(rt, "core_labels", counting)
    return counter


def _well(model):
    return model.project.get("WELL:A")


def test_repeated_calls_compute_labels_once(calls):
    model = _model()
    well = _well(model)
    first = model.params_for_well(well)
    for _ in range(5):
        model.params_for_well(well)
        model.well_params_hash(well)
    assert calls["n"] == 1
    assert first["rock_core"] is not None


def test_returned_labels_cannot_mutate_the_cache():
    model = _model()
    well = _well(model)
    flat = model.params_for_well(well)
    flat["rock_core"]["rt"][0] = 99
    flat["rock_core"]["depth"].clear()
    again = model.params_for_well(well)
    assert again["rock_core"]["rt"][0] != 99 and again["rock_core"]["depth"]


def test_unrelated_parameter_edit_keeps_the_cache(calls):
    model = _model()
    well = _well(model)
    model.params_for_well(well)
    model.temp_gradient = 2.2
    model.params_for_well(well)
    assert calls["n"] == 1


def test_reapplied_definitions_invalidate(calls):
    model = _model()
    well = _well(model)
    before = model.params_for_well(well)["rock_core"]
    defs = copy.deepcopy(model.project.rock_types)
    defs["sets"]["*"]["boundaries"] = [-1.0, 3.0]
    svc.apply_definitions(model, defs)
    after = model.params_for_well(well)["rock_core"]
    assert calls["n"] == 2 and after["rt"] != before["rt"]


def test_project_assignment_bumps_revision_and_invalidates(calls):
    model = _model()
    well = _well(model)
    model.params_for_well(well)
    rev = model.project.rock_types_rev
    model.project.rock_types = copy.deepcopy(model.project.rock_types)
    assert model.project.rock_types_rev == rev + 1
    model.params_for_well(well)
    assert calls["n"] == 2


def test_in_place_edit_of_the_set_invalidates(calls):
    model = _model()
    well = _well(model)
    model.params_for_well(well)
    model.project.rock_types["sets"]["*"]["boundaries"] = [3.0, 4.0]
    model.params_for_well(well)
    assert calls["n"] == 2


def test_new_core_data_invalidates(calls):
    model = _model()
    well = _well(model)
    before = model.params_for_well(well)["rock_core"]
    depth = [1002.0 + 3 * i for i in range(10)]
    well.core_data = _core(depth, [0.2] * 10, [500.0] * 10)
    after = model.params_for_well(well)["rock_core"]
    assert calls["n"] == 2 and len(after["depth"]) == 10 != len(before["depth"])


def test_core_sha_change_invalidates(calls):
    model = _model()
    well = _well(model)
    model.params_for_well(well)
    well.core_sha256 = "abc"
    model.params_for_well(well)
    assert calls["n"] == 2


def test_tops_change_invalidates(calls):
    model = _model()
    well = _well(model)
    model.params_for_well(well)
    well.formation_tops.formations[0].top_depth += 5.0
    model.params_for_well(well)
    assert calls["n"] == 2
    well.formation_tops = make_tops()
    model.params_for_well(well)
    assert calls["n"] == 3


def test_core_max_dist_change_invalidates(calls):
    model = _model()
    well = _well(model)
    model.params_for_well(well)
    model.core_max_dist = 7.0
    assert model.params_for_well(well)["rock_types"]["core_max_dist"] == 7.0
    assert calls["n"] == 2


def test_wells_do_not_share_entries(calls):
    model = _model()
    for name in "ABC":
        model.params_for_well(model.project.get(f"WELL:{name}"))
    for name in "ABC":
        model.params_for_well(model.project.get(f"WELL:{name}"))
    assert calls["n"] == 3


def test_hash_equals_the_uncached_result(monkeypatch):
    model = _model("zone")
    wells = [model.project.get(f"WELL:{n}") for n in "ABC"]
    cached = [model.well_params_hash(w) for w in wells]
    cached_again = [model.well_params_hash(w) for w in wells]
    monkeypatch.setattr(
        AppModel, "_cached_core_labels",
        lambda self, ds, rt_, cl, wci: cl(wci(ds), rt_))
    uncached = [model.well_params_hash(w) for w in wells]
    assert cached == cached_again == uncached


@pytest.mark.slow
def test_params_for_well_ten_wells_twenty_rounds_stay_fast():
    model = _model()
    src = _well(model)
    for i in range(7):
        ds = WellDataset(key=f"WELL:X{i}", display_name=f"X{i}")
        ds.las_data = fixture_frame("sample_log_data")
        ds.curve_mapping = dict(FULL_MAPPING)
        ds.formation_tops = make_tops()
        ds.core_data = src.core_data
        model.add_well(ds)
    wells = list(model.project.wells)
    assert len(wells) == 10
    for w in wells:
        model.params_for_well(w)
    start = time.perf_counter()
    for _ in range(20):
        for w in wells:
            model.params_for_well(w)
    # Uncached this is ~1.2 s on the reference machine; cached ~0.2 s.
    assert time.perf_counter() - start < 1.5
