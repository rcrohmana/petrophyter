"""Multi-well outputs: summary tables, exports, zone shading, zone markers."""
import numpy as np
import pandas as pd
import pytest

from models.app_model import AppModel
from models.project import WellDataset
from modules.pipeline import run_pipeline
from services.export_service import (
    ExportService, wells_summary_frame, zones_frame, unique_names,
)
from tests.golden.cases import FULL_MAPPING, fixture_frame, make_tops
from ui.data_browser import DataBrowserPanel
from ui.tabs.export_tab import ExportTab
from ui.tabs.log_display_tab import LogDisplayTab
from ui.tabs.summary_tab import SummaryTab


def _well(key, name, with_tops=True, run=True):
    data = fixture_frame("sample_log_data")
    ds = WellDataset(key, name)
    ds.identity = {"well_name": name, "uwi": f"UWI-{name}"}
    ds.las_data = data
    ds.curve_mapping = dict(FULL_MAPPING)
    if with_tops:
        ds.formation_tops = make_tops()
    if run:
        results, summary = run_pipeline(
            data, FULL_MAPPING, {}, formation_tops=ds.formation_tops)
        ds.results, ds.summary, ds.calculated = results, summary, True
    return ds


@pytest.fixture
def model():
    m = AppModel()
    m.project.add_well(_well("W:A", "Alpha"))
    m.project.add_well(_well("W:B", "Beta/Two", with_tops=False), activate=False)
    m.project.add_well(_well("W:C", "Gamma", run=False), activate=False)
    m.project.set_active("W:A")
    return m


def test_wells_frame_rows_and_field_totals(model):
    frame = wells_summary_frame(model.project.wells)
    assert list(frame["Well"]) == ["Alpha", "Beta/Two", "Gamma", "Field total"]
    assert list(frame["Status"][:3]) == ["Run", "Run", "Not run"]
    assert np.isnan(frame.loc[2, "Net"])
    a, b, total = frame.loc[0], frame.loc[1], frame.loc[3]
    assert total["Gross"] == pytest.approx(a["Gross"] + b["Gross"])
    assert total["Net"] == pytest.approx(a["Net"] + b["Net"])
    assert total["HCPV"] == pytest.approx(a["HCPV"] + b["HCPV"])
    expected = (a["Avg PHIE"] * a["Net"] + b["Avg PHIE"] * b["Net"]) / (a["Net"] + b["Net"])
    assert total["Avg PHIE"] == pytest.approx(expected)
    assert total["N/G"] == pytest.approx(total["Net"] / total["Gross"])


def test_zones_frame_has_one_row_per_zone(model):
    frame = zones_frame(model.project.wells)
    assert set(frame["Well"]) == {"Alpha"}   # Beta has no tops, so no zones
    alpha = frame[frame["Well"] == "Alpha"]
    assert list(alpha["Zone"]) == ["UPPER", "LOWER"]


def test_summary_tab_tables(qtbot, model):
    tab = SummaryTab(model)
    qtbot.addWidget(tab)
    tab.update_display()
    assert not tab.zones_group.isHidden()
    assert tab.zones_model.rowCount() == 2
    assert tab.zones_model.columnCount() == 14
    assert not tab.wells_group.isHidden()
    assert tab.wells_model.rowCount() == 4            # 3 wells + field total
    assert tab.wells_model._df.iloc[3, 0] == "Field total"
    tab.wells_zone_check.setChecked(True)
    assert tab.wells_model.rowCount() == 4 + 2 + len(model.project.get("W:B").summary["zones"])


def test_summary_tab_well_row_click_and_refresh(qtbot, model):
    tab = SummaryTab(model)
    qtbot.addWidget(tab)
    tab.update_display()
    with qtbot.waitSignal(tab.well_activated) as blocker:
        tab._on_well_row_clicked(tab.wells_model.index(1, 0))
    assert blocker.args == ["W:B"]
    model.project.remove_well("W:C")
    model.project.remove_well("W:B")
    assert tab.wells_group.isHidden()                  # < 2 wells


def test_zone_source_tooltip(qtbot, model):
    model.project.get("W:A").summary["zones"][0]["params"]["rw"]["source"] = "well·zone"
    tab = SummaryTab(model)
    qtbot.addWidget(tab)
    tab.update_display()
    assert "well·zone" in tab.zones_model.tooltips[(0, 12)]


def test_excel_all_wells(tmp_path, model):
    path = tmp_path / "all.xlsx"
    assert ExportService().export_excel_wells(model.project.wells, str(path))
    sheets = pd.ExcelFile(path).sheet_names
    assert sheets[0] == "Summary" and "Zones" in sheets
    assert "Alpha" in sheets and "Beta_Two" in sheets
    assert "Gamma" not in sheets                      # no results
    summary = pd.read_excel(path, sheet_name="Summary")
    assert list(summary["Well"])[-1] == "Field total"


def test_sheet_names_are_unique_and_short():
    names = unique_names(["x" * 40, "x" * 40, "Summary"], 31, reserved=("Summary",))
    assert len(set(n.lower() for n in names)) == 3
    assert all(len(n) <= 31 for n in names)


def test_csv_all_wells_has_well_column(tmp_path, model):
    path = tmp_path / "all.csv"
    assert ExportService().export_csv_wells(model.project.wells, str(path))
    frame = pd.read_csv(path)
    assert frame.columns[0] == "WELL"
    assert set(frame["WELL"]) == {"Alpha", "Beta/Two"}


def test_las_per_well_has_own_header(tmp_path, model):
    out = tmp_path / "las"
    assert ExportService().export_las_wells(model.project.wells, str(out))
    files = sorted(p.name for p in out.iterdir())
    assert files == ["Alpha.las", "Beta_Two.las", "Gamma.las"]
    assert "Beta/Two" in (out / "Beta_Two.las").read_text(encoding="utf-8")
    assert "Alpha" in (out / "Alpha.las").read_text(encoding="utf-8")
    # Analysed wells export their results; text curves (ZONE) are left out.
    alpha = (out / "Alpha.las").read_text(encoding="utf-8")
    header = alpha.split("~A")[1].splitlines()[0].split()
    assert "PHIE" in header and "ZONE" not in header


def test_export_tab_scope(qtbot, model):
    tab = ExportTab(model)
    qtbot.addWidget(tab)
    tab.update_display()
    assert tab.scope_combo.model().item(1).isEnabled()
    assert tab.csv_btn.isEnabled()
    tab.scope_combo.setCurrentIndex(1)
    assert tab.export_scope() == "all"
    model.project.remove_well("W:C")
    model.project.remove_well("W:B")                  # single well: All disabled
    assert not tab.scope_combo.model().item(1).isEnabled()
    assert tab.export_scope() == "active"


def test_browser_zone_markers(qtbot, model):
    ds = model.project.get("W:A")
    ds.zone_overrides = {"UPPER": {"rw": {"mode": "manual", "value": 0.04}}}
    model.project.zone_params = {"lower": {"a": {"mode": "manual", "value": 1.0}}}
    panel = DataBrowserPanel(model)
    qtbot.addWidget(panel)
    panel.rebuild()
    root = panel.tree_model.item(0, 0)
    tops = panel._find_group(root, "tops")
    marked = {}
    for row in range(tops.rowCount()):
        item = tops.child(row, 0)
        marked[item.text()] = item.toolTip()
    assert "rw" in marked["Upper"]
    assert "a" in marked["Lower"]
    upper = tops.child(0, 0).index()
    with qtbot.waitSignal(panel.action_requested) as blocker:
        panel._on_double_clicked(upper)
    assert blocker.args == ["edit_zone:UPPER"]
    # a well without overrides has no marker
    beta_tops = panel._find_group(panel.tree_model.item(1, 0), "tops")
    assert beta_tops.rowCount() == 0 or not beta_tops.child(0, 0).toolTip().startswith("Zone")


def test_zone_shading_toggle(qtbot, model):
    tab = LogDisplayTab(model)
    qtbot.addWidget(tab)
    tab.update_display()
    assert not tab.show_zones_check.isChecked()
    tab.show_zones_check.setChecked(True)
    tab.plot_stack.setCurrentIndex(1)
    tab._update_plot()
    assert any(ax.patches for ax in tab.classic_log.figure.axes)
    tab.show_zones_check.setChecked(False)
    assert not any(ax.patches for ax in tab.classic_log.figure.axes)
    tab.plot_stack.setCurrentIndex(0)
    tab.show_zones_check.setChecked(True)
    tab.show_zones_check.setChecked(False)
