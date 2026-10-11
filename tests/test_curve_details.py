"""Curve Mapping detail (U11): unit, coverage, range, auto or manual."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from models.app_model import AppModel
from models.project import WellDataset
from modules.las_parser import LASParser, find_curve
from services.curve_details import (
    DETAIL_COLUMNS, curve_detail_rows, detail_cells, detail_tooltip,
)


def _dataset(merged=False):
    n = 10
    data = pd.DataFrame({
        "DEPTH": np.arange(n, dtype=float),
        "GR": np.linspace(20, 120, n),
        "CGR": np.full(n, 50.0),
        "RHOB": [2.3] * 4 + [np.nan] * 6,
        "ILD": np.full(n, 10.0),
    })
    ds = WellDataset("W:A", "Alpha")
    ds.las_data = data
    file_units = {"GR": {"unit": "API"}, "CGR": {"unit": "API"}, "RHOB": {"unit": "g/cm3"},
                  "ILD": {"unit": ""}}
    ds.las_parser = SimpleNamespace(curve_info=file_units)
    if merged:
        ds.merged = True
        ds.merge_report = SimpleNamespace(curve_info={"GR": {"unit": "GAPI"}})
    ds.curve_mapping = {"GR": "CGR", "RHOB": "RHOB", "NPHI": "None", "DT": "None",
                        "RT": "None", "TVD": "None"}
    return ds


def test_find_curve_is_the_parser_rule_on_a_column_list():
    assert find_curve(["DEPTH", "cgr", "GR"], "GR") == "GR"        # alias order wins
    assert find_curve(["DEPTH", "rhoz"], "RHOB") == "rhoz"          # case-insensitive
    assert find_curve(["DEPTH"], "RHOB") is None
    assert find_curve(["GR"], "UNKNOWN") is None
    assert "CURVE_ALIASES" in vars(LASParser)


def test_rows_give_unit_coverage_range_and_mapping_source():
    rows = {r["type"]: r for r in curve_detail_rows(_dataset())}
    assert list(rows) == ["GR", "RHOB", "NPHI", "DT", "RT", "TVD"]

    gr = rows["GR"]                      # CGR chosen while detection picks GR
    assert (gr["curve"], gr["unit"], gr["mapping"], gr["detected"]) == ("CGR", "API", "Manual", "GR")
    assert gr["coverage"] == pytest.approx(1.0) and gr["range"] == (50.0, 50.0)

    rhob = rows["RHOB"]
    assert rhob["mapping"] == "Auto" and rhob["unit"] == "g/cm3"
    assert rhob["coverage"] == pytest.approx(0.4)
    assert "fewer than 50%" in detail_tooltip(rhob)

    rt = rows["RT"]                      # ILD would be detected, but RT is cleared
    assert (rt["curve"], rt["mapping"], rt["detected"]) == ("None", "Manual", "ILD")
    assert "detection would pick ILD" in detail_tooltip(rt)
    assert rows["NPHI"]["mapping"] == ""
    assert detail_cells(rows["NPHI"]) == ["NPHI", "None", "", "", "", ""]
    assert detail_cells(rhob) == ["RHOB", "RHOB", "g/cm3", "40.0 %", "2.3 – 2.3", "Auto"]


def test_missing_unit_reads_as_a_dash_with_a_reason():
    ds = _dataset()
    ds.curve_mapping["RT"] = "ILD"
    rt = {r["type"]: r for r in curve_detail_rows(ds)}["RT"]
    assert detail_cells(rt)[2] == "—"
    assert "no unit" in detail_tooltip(rt)


def test_merged_well_takes_units_from_the_merge():
    ds = _dataset(merged=True)
    ds.curve_mapping["GR"] = "GR"
    gr = {r["type"]: r for r in curve_detail_rows(ds)}["GR"]
    assert gr["unit"] == "GAPI" and gr["mapping"] == "Auto"


def test_no_well_no_rows():
    assert curve_detail_rows(None) == []


def test_parameters_window_fills_the_table_and_follows_mapping_edits(qtbot):
    from ui.parameters_window import ParametersWindow

    model = AppModel()
    ds = _dataset()
    model.project.add_well(ds)
    window = ParametersWindow(model)
    qtbot.addWidget(window)
    window.update_available_curves(list(ds.las_data.columns))
    table = window.curve_mapping_widget.details_table
    assert table.rowCount() == 6
    assert [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())] \
        == DETAIL_COLUMNS
    mapping_col = DETAIL_COLUMNS.index("Mapping")
    assert table.item(0, 1).text() == "CGR" and table.item(0, mapping_col).text() == "Manual"

    window.curve_mapping_widget.curve_combos["GR"].setCurrentText("GR")
    assert ds.curve_mapping["GR"] == "GR"
    assert table.item(0, 1).text() == "GR" and table.item(0, mapping_col).text() == "Auto"
