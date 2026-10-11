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


def test_las_export_survives_input_curves_named_like_results(tmp_path):
    data = fixture_frame("sample_log_data")
    data["PHIE"] = 0.11
    data["SW"] = 0.9
    ds = WellDataset("W:X", "Xray")
    ds.las_data = data
    ds.curve_mapping = dict(FULL_MAPPING)
    results, summary = run_pipeline(data, FULL_MAPPING, {})
    ds.results, ds.summary, ds.calculated = results, summary, True
    assert results.columns.is_unique and "PHIE_IN" in results.columns
    out = tmp_path / "las"
    assert ExportService().export_las_wells([ds], str(out))
    header = (out / "Xray.las").read_text(encoding="utf-8").split("~A")[1].splitlines()[0].split()
    assert "PHIE_IN" in header and "SW_IN" in header


# ---- U2 / U3: parameter provenance, export freshness and provenance ------------------
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from services.export_service import (
    PROVENANCE_SHEET, _summary_frame, blockers_text, export_blockers, las_frame,
    provenance_block,
)
from version import APP_BUILD, APP_VERSION


def _stale(ds):
    ds.stale = True
    ds.run_time = "2026-10-11T09:00:00+00:00"
    ds.run_params_hash = "abc123"


def test_export_blockers_by_state(model):
    beta, gamma = model.project.get("W:B"), model.project.get("W:C")
    _stale(beta)
    broken = _well("W:D", "Delta")
    broken.error = "boom"
    model.project.add_well(broken, activate=False)
    failed_empty = _well("W:E", "Echo", run=False)
    failed_empty.error = "no formation"
    model.project.add_well(failed_empty, activate=False)
    blockers = export_blockers(model.project.wells)
    assert [d.key for d in blockers["ready"]] == ["W:A"]
    assert [d.key for d in blockers["out_of_date"]] == ["W:B"]
    assert [d.key for d in blockers["failed"]] == ["W:D"]
    assert [d.key for d in blockers["failed_no_results"]] == ["W:E"]
    assert [d.key for d in blockers["no_results"]] == ["W:C"]
    assert blockers_text(blockers, with_ready=True) == "1 well ready · 1 out of date · 2 latest run failed"
    assert blockers_text(blockers) == "1 well out of date · 2 latest run failed"
    assert gamma.status == "loaded"


def test_field_total_excludes_failed_well_and_counts_stale(model):
    alpha_net = wells_summary_frame(model.project.wells).loc[0, "Net"]
    beta = model.project.get("W:B")
    beta.error = "formation not found"
    frame = wells_summary_frame(model.project.wells)
    total = frame.iloc[-1]
    assert total["Status"] == "1 well"
    assert total["Net"] == pytest.approx(alpha_net)
    row = frame[frame["Well"] == "Beta/Two"].iloc[0]
    assert row["Status"] == "Error: formation not found"
    assert np.isnan(row["Net"]) and np.isnan(row["HCPV"])
    beta.error = None
    _stale(beta)
    frame = wells_summary_frame(model.project.wells)
    assert frame.iloc[-1]["Status"] == "2 wells (1 out of date)"
    assert frame.iloc[-1]["Net"] == pytest.approx(frame.loc[0, "Net"] + frame.loc[1, "Net"])


def test_summary_tab_issues_column(qtbot, model):
    model.project.get("W:A").summary["warnings"] = ["PHIE missing", "Rw fallback"]
    model.project.get("W:B").error = "boom"
    tab = SummaryTab(model)
    qtbot.addWidget(tab)
    tab._refresh_multi()
    assert tab.wells_model.columnCount() == 14
    assert tab.wells_model.headerData(13, Qt.Orientation.Horizontal) == "Issues"

    def cell(row):
        return tab.wells_model.index(row, 13).data()

    assert cell(0) == "2 warnings"
    assert cell(1) == "boom"
    assert cell(2) == ""


def test_summary_sheet_has_parameter_table_not_json(tmp_path, model):
    ds = model.project.get("W:A")
    path = tmp_path / "one.xlsx"
    assert ExportService().export_excel(ds.results, ds.summary, str(path))
    summary = pd.read_excel(path, sheet_name="Summary")
    assert list(summary.columns) == ["Parameter", "Scope", "Value", "Source"]
    assert not any('"(well)"' in str(v) for v in summary["Value"].dropna())   # no JSON dump
    assert "param_sources" not in set(summary["Parameter"])
    well_rows = summary[summary["Scope"] == "well"]
    row = well_rows[well_rows["Parameter"] == "vsh_cutoff"].iloc[0]
    assert row["Value"] == pytest.approx(0.4) and row["Source"] == "project"


def test_summary_frame_scopes_zone_and_temperature():
    frame = _summary_frame({"net_pay": 1.5, "param_sources": {
        "(well)": {"rw": {"value": 0.1, "source": "project"}},
        "UPPER": {"rw": {"value": 0.04, "source": "zone"}},
        "temperature": {"tvd_source": "TVD curve TVDKB"},
    }})
    rows = {(r.Parameter, r.Scope): (r.Value, r.Source) for r in frame.itertuples()}
    assert rows[("net_pay", "")] == (1.5, "")
    assert rows[("rw", "well")] == (0.1, "project")
    assert rows[("rw", "UPPER")] == (0.04, "zone")
    assert rows[("tvd_source", "temperature")] == ("TVD curve TVDKB", "")


def test_every_format_carries_version_and_run_time(tmp_path, model):
    alpha = model.project.get("W:A")
    alpha.run_time = "2026-10-11T09:00:00+00:00"
    alpha.run_params_hash = "abc123"
    svc = ExportService()
    block = provenance_block(alpha)
    assert block["App version"] == APP_VERSION and block["Build"] == APP_BUILD
    assert block["Run time"] == alpha.run_time and block["Status at export"] == "Current"
    # single-well Excel: key/value rows
    xlsx = tmp_path / "one.xlsx"
    assert svc.export_excel(alpha.results, alpha.summary, str(xlsx), block)
    sheet = pd.read_excel(xlsx, sheet_name=PROVENANCE_SHEET)
    values = dict(zip(sheet["Item"], sheet["Value"]))
    assert values["App version"] == APP_VERSION and values["Run time"] == alpha.run_time
    # all-wells Excel: one row per well
    allx = tmp_path / "all.xlsx"
    assert svc.export_excel_wells(model.project.wells, str(allx))
    sheet = pd.read_excel(allx, sheet_name=PROVENANCE_SHEET)
    assert list(sheet["Well"]) == ["Alpha", "Beta/Two"]
    assert set(sheet["App version"]) == {APP_VERSION}
    assert sheet.loc[0, "Run time"] == alpha.run_time
    # LAS: ~OTHER section before the data
    las = tmp_path / "one.las"
    assert svc.export_las(las_frame(alpha), alpha.well_info, str(las), block)
    text = las.read_text(encoding="utf-8")
    assert "~OTHER" in text and text.index("~OTHER") < text.index("~A ")
    assert f"Exported by Petrophyter {APP_VERSION} (Build {APP_BUILD})" in text
    assert alpha.run_time in text and "Param hash abc123" in text
    out = tmp_path / "las"
    assert svc.export_las_wells(model.project.wells, str(out))
    assert f"Petrophyter {APP_VERSION}" in (out / "Alpha.las").read_text(encoding="utf-8")


def test_csv_sidecar_and_unchanged_csv(tmp_path, model):
    alpha = model.project.get("W:A")
    alpha.run_time = "2026-10-11T09:00:00+00:00"
    svc = ExportService()
    plain = tmp_path / "plain.csv"
    assert svc.export_csv(alpha.results, str(plain))
    assert not (tmp_path / "plain.provenance.txt").exists()
    with_prov = tmp_path / "res.csv"
    assert svc.export_csv(alpha.results, str(with_prov), provenance_block(alpha))
    assert with_prov.read_bytes() == plain.read_bytes()
    side = (tmp_path / "res.provenance.txt").read_text(encoding="utf-8")
    assert f"App version: {APP_VERSION}" in side and "Run time: 2026-10-11T09:00:00" in side
    allc = tmp_path / "all.csv"
    assert svc.export_csv_wells(model.project.wells, str(allc))
    side = (tmp_path / "all.provenance.txt").read_text(encoding="utf-8")
    assert "Well: Alpha" in side and "Well: Beta/Two" in side
    assert pd.read_csv(allc).columns[0] == "WELL"
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".")]   # no temp files left


# ---- Export tab: status line and confirmation ----------------------------------------
@pytest.fixture
def export_tab(qtbot, model, monkeypatch):
    tab = ExportTab(model)
    qtbot.addWidget(tab)
    tab.update_display()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: "")
    return tab


def _click(monkeypatch, which):
    """Patch the modal: record its buttons, then click the button named ``which``."""
    seen = {}

    def fake_exec(self):
        seen["buttons"] = [b.text().replace("&", "") for b in self.buttons()]
        seen["text"] = self.text()
        seen["info"] = self.informativeText()
        for button in self.buttons():
            if button.text().replace("&", "") == which:
                button.click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    return seen


def test_export_status_line(export_tab, model):
    assert export_tab.status_line.text() == "Ready — results current"
    assert export_tab.status_line.property("status") == "success"
    _stale(model.project.get("W:A"))
    model.project.well_updated.emit("W:A")
    assert export_tab.status_line.text() == "1 well out of date"
    assert export_tab.status_line.property("status") == "warning"
    assert export_tab.csv_btn.isEnabled()                 # the dialog decides, not the button
    model.project.get("W:B").error = "boom"
    export_tab.scope_combo.setCurrentIndex(1)
    assert export_tab.status_line.text() == "1 well out of date · 1 latest run failed"


def test_clean_scope_exports_without_dialog(export_tab, monkeypatch):
    seen = _click(monkeypatch, "Cancel")
    export_tab._on_export_csv()
    assert seen == {}


def test_dialog_has_three_buttons_and_cancel_exports_nothing(export_tab, model, monkeypatch):
    _stale(model.project.get("W:A"))
    model.project.get("W:B").error = "boom"
    export_tab.scope_combo.setCurrentIndex(1)
    seen = _click(monkeypatch, "Cancel")
    asked = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: asked.append(1) or ("", ""))
    export_tab._on_export_excel()
    assert set(seen["buttons"]) == {"Run out-of-date wells", "Export last successful results", "Cancel"}
    assert len(seen["buttons"]) == 3
    assert seen["text"] == "0 wells ready · 1 out of date · 1 latest run failed"
    assert "latest run failed are left out" in seen["info"]
    assert asked == []


def test_dialog_run_button_emits_keys_and_does_not_export(export_tab, model, monkeypatch):
    _stale(model.project.get("W:B"))
    export_tab.scope_combo.setCurrentIndex(1)
    _click(monkeypatch, "Run out-of-date wells")
    asked, got = [], []
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: asked.append(1) or ("", ""))
    export_tab.run_wells_requested.connect(got.append)
    export_tab._on_export_csv()
    assert got == [["W:B"]] and asked == []


def test_dialog_export_button_exports_with_status_written(export_tab, model, tmp_path, monkeypatch):
    _stale(model.project.get("W:B"))
    export_tab.scope_combo.setCurrentIndex(1)
    seen = _click(monkeypatch, "Export last successful results")
    path = str(tmp_path / "all.xlsx")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (path, ""))
    export_tab._on_export_excel()
    assert "Run out-of-date wells" in seen["buttons"]
    summary = pd.read_excel(path, sheet_name="Summary")
    assert summary.iloc[-1]["Status"] == "2 wells (1 out of date)"
    prov = pd.read_excel(path, sheet_name=PROVENANCE_SHEET)
    assert list(prov["Status at export"]) == ["Current", "Out of date"]


def test_failed_well_without_results_is_named_and_left_out(export_tab, model, monkeypatch):
    model.project.get("W:C").error = "no formation"
    export_tab.scope_combo.setCurrentIndex(1)
    seen = _click(monkeypatch, "Cancel")
    export_tab._on_export_csv()
    assert set(seen["buttons"]) == {"Export last successful results", "Cancel"}
    assert "Not exported" in seen["info"] and "Gamma" in seen["info"]


def test_single_well_export_writes_provenance(export_tab, tmp_path, monkeypatch):
    path = str(tmp_path / "one.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (path, ""))
    export_tab._on_export_csv()
    assert (tmp_path / "one.csv").exists() and (tmp_path / "one.provenance.txt").exists()


# ---- U9: the preview says what it shows; the interval applies to the export ----------
def _choose_interval(tab, top=1000.0, bottom=1019.0):
    tab.top_md_spin.setValue(top)
    tab.bottom_md_spin.setValue(bottom)
    tab.interval_combo.setCurrentIndex(1)


def _rows_in(model, key, top, bottom):
    depth = model.project.get(key).results["DEPTH"]
    return int(((depth >= top) & (depth <= bottom)).sum())


def _save_to(monkeypatch, path):
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))


def test_preview_title_says_rows_shown_and_total(export_tab, model):
    total = len(model.project.get("W:A").results)
    assert export_tab.preview_group.title() == (
        f"Preview — showing {min(total, 500):,} of {total:,} rows (well Alpha)")
    assert export_tab.depth_range() is None
    assert export_tab.interval_combo.itemText(0) == "All depths"


def test_preview_title_counts_the_chosen_interval(export_tab, model):
    _choose_interval(export_tab)
    n = _rows_in(model, "W:A", 1000.0, 1019.0)
    assert 0 < n < len(model.project.get("W:A").results)
    assert export_tab.interval_combo.itemText(1) == "Selected interval (1000–1019 ft)"
    assert export_tab.preview_group.title() == (
        f"Preview — showing {n:,} of {n:,} rows (well Alpha)")
    assert export_tab.preview_model.rowCount() == n


def test_preview_caps_at_500_rows_but_says_the_total(export_tab, model):
    ds = model.project.get("W:A")
    big = pd.concat([ds.results] * 60, ignore_index=True)
    ds.results = big
    export_tab._update_table_view()
    assert export_tab.preview_model.rowCount() == 500
    assert export_tab.preview_group.title() == (
        f"Preview — showing 500 of {len(big):,} rows (well Alpha)")


def test_invalid_interval_is_not_selectable(export_tab):
    export_tab.top_md_spin.setValue(1050.0)
    export_tab.bottom_md_spin.setValue(1050.0)
    assert not export_tab.interval_combo.model().item(1).isEnabled()
    assert export_tab.depth_range() is None


@pytest.mark.parametrize("kind", ["csv", "xlsx", "las"])
def test_interval_applies_to_single_well_export(export_tab, model, tmp_path, monkeypatch, kind):
    _choose_interval(export_tab)
    n = _rows_in(model, "W:A", 1000.0, 1019.0)
    path = tmp_path / f"one.{kind}"
    _save_to(monkeypatch, path)
    {"csv": export_tab._on_export_csv, "xlsx": export_tab._on_export_excel,
     "las": export_tab._on_export_las}[kind]()
    assert path.exists()
    if kind == "csv":
        assert len(pd.read_csv(path)) == n
        assert "Depth interval: Selected interval (1000–1019 ft)" in (
            tmp_path / "one.provenance.txt").read_text(encoding="utf-8")
    elif kind == "xlsx":
        assert len(pd.read_excel(path, sheet_name="Results")) == n
        prov = pd.read_excel(path, sheet_name=PROVENANCE_SHEET)
        row = prov[prov["Item"] == "Depth interval"].iloc[0]
        assert row["Value"] == "Selected interval (1000–1019 ft)"
    else:
        text = path.read_text(encoding="utf-8")
        data = [ln for ln in text.split("~A")[1].splitlines()[1:] if ln.strip()]
        assert len(data) == n
        assert "Depth interval Selected interval (1000–1019 ft)" in text


def test_all_depths_export_is_unfiltered_and_recorded(export_tab, model, tmp_path, monkeypatch):
    path = tmp_path / "full.csv"
    _save_to(monkeypatch, path)
    export_tab._on_export_csv()
    assert len(pd.read_csv(path)) == len(model.project.get("W:A").results)
    assert "Depth interval: All depths" in (
        tmp_path / "full.provenance.txt").read_text(encoding="utf-8")


def test_interval_applies_to_all_wells_exports(export_tab, model, tmp_path, monkeypatch):
    export_tab.scope_combo.setCurrentIndex(1)
    _choose_interval(export_tab, 1000.0, 1019.0)
    expected = {"Alpha": _rows_in(model, "W:A", 1000.0, 1019.0),
                "Beta/Two": _rows_in(model, "W:B", 1000.0, 1019.0)}
    csv_path = tmp_path / "all.csv"
    _save_to(monkeypatch, csv_path)
    export_tab._on_export_csv()
    frame = pd.read_csv(csv_path)
    assert frame["WELL"].value_counts().to_dict() == expected
    xlsx = tmp_path / "all.xlsx"
    _save_to(monkeypatch, xlsx)
    export_tab._on_export_excel()
    assert len(pd.read_excel(xlsx, sheet_name="Alpha")) == expected["Alpha"]
    prov = pd.read_excel(xlsx, sheet_name=PROVENANCE_SHEET)
    assert set(prov["Depth interval"]) == {"Selected interval (1000–1019 ft)"}
    out = tmp_path / "las"
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(out))
    export_tab._on_export_las()
    text = (out / "Alpha.las").read_text(encoding="utf-8")
    data = [ln for ln in text.split("~A")[1].splitlines()[1:] if ln.strip()]
    assert len(data) == expected["Alpha"]


def test_all_wells_scope_shows_active_well_and_a_note(export_tab, model):
    assert export_tab.scope_note.isHidden()
    export_tab.scope_combo.setCurrentIndex(1)
    rows = sum(len(model.project.get(k).results) for k in ("W:A", "W:B"))
    assert export_tab.scope_note.text() == f"Export contains 2 wells, {rows:,} rows"
    assert "(well Alpha)" in export_tab.preview_group.title()
    _choose_interval(export_tab)
    n = _rows_in(model, "W:A", 1000.0, 1019.0) + _rows_in(model, "W:B", 1000.0, 1019.0)
    assert export_tab.scope_note.text() == f"Export contains 2 wells, {n:,} rows"
    export_tab.scope_combo.setCurrentIndex(0)
    assert export_tab.scope_note.isHidden()


def test_scope_change_refreshes_the_preview(export_tab, model, monkeypatch):
    calls = []
    original = export_tab._update_table_view
    monkeypatch.setattr(export_tab, "_update_table_view",
                        lambda: (calls.append(1), original())[1])
    export_tab.scope_combo.setCurrentIndex(1)
    assert calls
