"""Project / WellDataset model and the AppModel single-well facade."""

import pandas as pd

from models.app_model import AppModel
from models.project import Project, WellDataset, display_name_for, make_well_key


class _Parser:
    def __init__(self, well_info):
        self.well_info = well_info
        self.data = pd.DataFrame({"DEPTH": [1000.0, 1001.0], "GR": [50.0, 60.0]})


def _well(name, key=None):
    ds = WellDataset(key=key or f"WELL:{name}", display_name=name)
    ds.las_data = pd.DataFrame({"DEPTH": [1.0, 2.0], "GR": [10.0, 20.0]})
    return ds


def test_make_well_key_prefers_identity_then_file_stem():
    assert make_well_key({"uwi": "100/01", "well_name": "A"}, "x.las") == "UWI:100/01"
    assert make_well_key({"well_name": "bks 01"}, "x.las") == "WELL:BKS-01"
    assert make_well_key({"well_name": "Unknown"}, r"C:\data\run_2.las") == "FILE:RUN-2"
    assert display_name_for({"well_name": " BKS-01 "}, "x.las") == "BKS-01"
    assert display_name_for({"well_name": ""}, "dir/run2.las") == "run2"


def test_project_add_activate_remove(qtbot):
    project = Project()
    changes, actives = [], []
    project.wells_changed.connect(lambda: changes.append(1))
    project.active_well_changed.connect(actives.append)

    project.add_well(_well("A"))
    project.add_well(_well("B"), activate=False)
    assert project.keys() == ["WELL:A", "WELL:B"]
    assert project.active_key == "WELL:A"

    project.set_active("WELL:B")
    assert project.active.display_name == "B"
    project.remove_well("WELL:B")
    assert project.active_key == "WELL:A"
    assert actives[-1] == "WELL:A"
    assert changes


def test_project_same_key_replaces_unless_asked_not_to():
    project = Project()
    project.add_well(_well("A"))
    replacement = _well("A")
    project.add_well(replacement)
    assert len(project) == 1 and project.active is replacement
    project.add_well(_well("A"), replace=False)
    assert project.keys() == ["WELL:A", "WELL:A#2"]


def test_facade_first_assignment_creates_a_well():
    model = AppModel()
    assert model.las_data is None and len(model.project) == 0
    model.las_parser = _Parser({"well_name": "BKS-01"})
    model.las_filename = "bks.las"
    model.las_data = model.las_parser.data
    assert len(model.project) == 1
    assert model.project.active_key == "WELL:BKS-01"
    assert model.active_well.display_name == "BKS-01"
    assert model.las_parser.well_info["well_name"] == "BKS-01"


def test_facade_follows_active_well_and_keeps_each_wells_results():
    model = AppModel()
    a, b = _well("A"), _well("B")
    model.add_well(a)
    model.set_analysis_results(pd.DataFrame({"PHIE": [0.2]}), {"net_pay": 3.0})
    model.curve_mapping = {"GR": "GR", "RHOB": "None", "NPHI": "None", "DT": "None", "RT": "None"}
    model.add_well(b)
    assert model.results is None and model.calculated is False
    assert model.curve_mapping["GR"] == "None"

    model.set_active_well("WELL:A")
    assert model.summary == {"net_pay": 3.0}
    assert model.curve_mapping["GR"] == "GR"
    assert model.to_params()["curve_mapping"]["GR"] == "GR"


def test_replacing_active_data_clears_only_that_wells_results():
    model = AppModel()
    model.add_well(_well("A"))
    model.set_analysis_results(pd.DataFrame({"PHIE": [0.2]}), {})
    model.add_well(_well("B"))
    model.set_analysis_results(pd.DataFrame({"PHIE": [0.3]}), {})
    model.las_data = pd.DataFrame({"DEPTH": [5.0], "GR": [1.0]})
    assert model.results is None
    model.set_active_well("WELL:A")
    assert model.results is not None


def test_reset_removes_all_wells():
    model = AppModel()
    model.add_well(_well("A"))
    model.add_well(_well("B"))
    model.reset()
    assert len(model.project) == 0
    assert model.las_data is None and model.results is None


def test_well_status():
    ds = WellDataset("WELL:A")
    assert ds.status == "empty"
    ds.las_data = pd.DataFrame({"DEPTH": [1.0]})
    assert ds.status == "loaded"
    ds.calculated = True
    assert ds.status == "run_ok"
    ds.stale = True
    assert ds.status == "stale"
    ds.error = "boom"
    assert ds.status == "error"
