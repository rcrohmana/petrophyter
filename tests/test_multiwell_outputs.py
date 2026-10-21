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
    model.project.get("W:A").summary.pop("issues", None)   # count the plain warnings (v1.7.1 path)
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


def test_the_provenance_block_is_the_run_manifest_in_every_format(tmp_path, model):
    from importlib import metadata

    alpha = model.project.get("W:A")
    alpha.run_time = "2026-10-11T09:00:00+00:00"
    alpha.run_params_hash = "abc123"
    alpha.merged = True
    alpha.sources = [
        {"name": "a1.las", "path": "a1.las", "rows": 5, "sha256": "aa" * 32, "size": 111},
        {"name": "a2.las", "path": "a2.las", "rows": 5, "sha256": "bb" * 32, "size": 222},
    ]
    alpha.merge_recipe = {"step": 0.5, "gap_limit": 5.0, "policy": 2}
    alpha.tops_path, alpha.tops_sha256 = "tops.csv", "cc" * 32
    block = provenance_block(alpha)
    assert block["Source files"] == f"a1.las sha256:{'aa' * 32} (111 bytes); a2.las sha256:{'bb' * 32} (222 bytes)"
    assert block["Merge recipe"] == "step 0.5 ft, gap limit 5 ft, policy 2"
    assert block["Tops file"] == f"tops.csv sha256:{'cc' * 32}"
    assert block["Core file"] == "none"
    assert block["Parameter hash"] == "abc123"
    for name in ("numpy", "scipy", "pandas", "lasio"):
        assert block[name] == metadata.version(name)
    # a single-file well says so
    assert provenance_block(model.project.get("W:B"))["Merge recipe"] == "single file"

    svc = ExportService()
    xlsx = tmp_path / "one.xlsx"
    assert svc.export_excel(alpha.results, alpha.summary, str(xlsx), block)
    values = dict(zip(*[pd.read_excel(xlsx, sheet_name=PROVENANCE_SHEET)[c] for c in ("Item", "Value")]))
    assert values["Source files"] == block["Source files"] and values["numpy"] == block["numpy"]
    allx = tmp_path / "all.xlsx"
    assert svc.export_excel_wells(model.project.wells, str(allx))
    sheet = pd.read_excel(allx, sheet_name=PROVENANCE_SHEET)
    assert sheet.loc[0, "Merge recipe"] == block["Merge recipe"] and sheet.loc[0, "scipy"] == block["scipy"]
    las = tmp_path / "one.las"
    assert svc.export_las(las_frame(alpha), alpha.well_info, str(las), block)
    text = las.read_text(encoding="utf-8")
    assert f"Sources {block['Source files']}" in text
    assert "Merge recipe step 0.5 ft, gap limit 5 ft, policy 2" in text
    assert f"Libraries numpy {block['numpy']}, scipy {block['scipy']}" in text
    csv = tmp_path / "res.csv"
    assert svc.export_csv(alpha.results, str(csv), block)
    side = (tmp_path / "res.provenance.txt").read_text(encoding="utf-8")
    assert f"Source files: {block['Source files']}" in side and f"pandas: {block['pandas']}" in side
    assert "Merge recipe: step 0.5 ft" in side


def test_field_sw_is_weighted_by_pore_thickness_in_pay(model):
    a, b = model.project.wells[0], model.project.wells[1]
    a.summary.update({"net_pay": 10.0, "avg_sw_pay": 0.2, "phih_pay": 1.0})
    b.summary.update({"net_pay": 1.0, "avg_sw_pay": 0.6, "phih_pay": 3.0})
    total = wells_summary_frame(model.project.wells).iloc[-1]
    # (0.2 x 1.0 + 0.6 x 3.0) / (1.0 + 3.0) = 0.50; weighting by net pay would give 0.236
    assert total["Avg Sw"] == pytest.approx(0.50, rel=1e-12)
    # PHIE stays net-pay weighted
    expected = (a.summary["avg_phie_pay"] * 10.0 + b.summary["avg_phie_pay"] * 1.0) / 11.0
    assert total["Avg PHIE"] == pytest.approx(expected, rel=1e-12)


def test_field_sw_without_phih_pay_falls_back_to_net_pay_weights(model):
    a, b = model.project.wells[0], model.project.wells[1]
    for ds, net, sw in ((a, 10.0, 0.2), (b, 1.0, 0.6)):
        ds.summary.update({"net_pay": net, "avg_sw_pay": sw})
        ds.summary.pop("phih_pay", None)
    total = wells_summary_frame(model.project.wells).iloc[-1]
    assert total["Avg Sw"] == pytest.approx((0.2 * 10.0 + 0.6 * 1.0) / 11.0, rel=1e-12)


# ---- rock types (P1): Summary table, Rock Types sheet, LAS curves, definitions CSV ----
from services.export_service import (
    ROCKTYPES_SHEET, WELL_COLUMNS, ZONE_COLUMNS, rock_type_definitions_frame,
    rock_type_field_total, rock_types_frame,
)

_RT_SET = {"n_rt": 3, "boundaries": [-0.2, 0.2], "centers": [-0.5, 0.0, 0.5],
           "fzi": [0.3, 1.0, 3.2], "feature_range": [-3.0, 3.0], "n_samples": [10, 20, 10],
           "k_rmse_log10": [0.2, 0.1, 0.3], "edited": False, "basis": "pooled, test"}
_RT_DEFS = {"method": "fzi", "feature": "log10_fzi", "fit_scope": "project", "set": _RT_SET,
            "zone_sets": {}, "basis": "pooled",
            "settings": {"reservoir_only": False, "min_phie": 0.02}}


def _rock_well(key, name, fit_scope="project", tops=True):
    data = fixture_frame("sample_log_data")
    ds = WellDataset(key, name)
    ds.identity = {"well_name": name, "uwi": f"UWI-{name}"}
    ds.las_data = data
    ds.curve_mapping = dict(FULL_MAPPING)
    if tops:
        ds.formation_tops = make_tops()
    params = {"rock_typing_enabled": True, "rock_types": {**_RT_DEFS, "fit_scope": fit_scope}}
    ds.results, ds.summary = run_pipeline(
        data, FULL_MAPPING, params, formation_tops=ds.formation_tops)
    ds.calculated = True
    return ds


@pytest.fixture
def rock_model():
    m = AppModel()
    m.project.add_well(_rock_well("W:A", "Alpha"))
    m.project.add_well(_rock_well("W:B", "Beta", tops=False), activate=False)
    m.project.set_active("W:A")
    return m


def test_rock_pipeline_fixture_has_assigned_samples(rock_model):
    rock = rock_model.project.get("W:A").summary["rock_types"]
    assert sum(r["samples"] for r in rock["by_rt"]) > 0


def test_existing_column_sets_are_unchanged():
    assert WELL_COLUMNS == [
        "Well", "Status", "Gross", "Net", "N/G", "Avg PHIE", "Avg Sw", "HCPV",
        "Rw", "Rw source", "Rsh", "Rsh source", "QC score"]
    assert ZONE_COLUMNS == [
        "Well", "Zone", "Top", "Bottom", "Gross", "Net", "N/G", "Avg PHIE", "Avg Sw", "HCPV",
        "a", "m", "n", "Rw", "Rsh", "Vsh cutoff", "Phi cutoff", "Sw cutoff", "Param sources"]


def test_rock_types_sheet_only_when_rock_typing_is_on(tmp_path, model, rock_model):
    off = tmp_path / "off.xlsx"
    assert ExportService().export_excel_wells(model.project.wells, str(off))
    assert ROCKTYPES_SHEET not in pd.ExcelFile(off).sheet_names

    on = tmp_path / "on.xlsx"
    assert ExportService().export_excel_wells(rock_model.project.wells, str(on))
    book = pd.ExcelFile(on)
    assert ROCKTYPES_SHEET in book.sheet_names
    sheet = book.parse(ROCKTYPES_SHEET)
    assert list(sheet.columns)[:3] == ["Well", "Rock type", "Samples"]
    assert {"Alpha", "Beta", "Field total"} <= set(sheet["Well"])
    # the well sheets carry the new result columns
    alpha = book.parse("Alpha")
    assert {"RQI", "FZI", "ROCK_TYPE", "ROCK_TYPE_SOURCE", "RT_MARGIN"} <= set(alpha.columns)
    assert "Zones" in book.sheet_names and "Provenance" in book.sheet_names


def test_a_well_named_rock_types_gets_a_unique_sheet(tmp_path, rock_model):
    rock_model.project.get("W:B").display_name = ROCKTYPES_SHEET
    path = tmp_path / "clash.xlsx"
    assert ExportService().export_excel_wells(rock_model.project.wells, str(path))
    names = pd.ExcelFile(path).sheet_names
    assert len(names) == len({n.lower() for n in names})


def test_single_well_excel_gets_the_sheet_only_when_on(tmp_path, model, rock_model):
    svc = ExportService()
    for m, expected in ((model, False), (rock_model, True)):
        ds = m.project.active
        path = tmp_path / f"single_{expected}.xlsx"
        assert svc.export_excel(ds.results, ds.summary, str(path), {"Well": "Alpha"})
        assert (ROCKTYPES_SHEET in pd.ExcelFile(path).sheet_names) is expected


def test_csv_all_wells_carries_rock_type_columns(tmp_path, rock_model):
    path = tmp_path / "all.csv"
    assert ExportService().export_csv_wells(rock_model.project.wells, str(path))
    header = pd.read_csv(path, nrows=1).columns
    assert {"WELL", "RQI", "FZI", "ROCK_TYPE", "ROCK_TYPE_SOURCE", "RT_MARGIN"} <= set(header)


def test_las_has_numeric_rock_curves_and_no_text_source(tmp_path, rock_model):
    ds = rock_model.project.get("W:A")
    ds.results = ds.results.assign(PERM_RT=10.0)
    out = tmp_path / "las"
    assert ExportService().export_las_wells(rock_model.project.wells, str(out))
    text = (out / "Alpha.las").read_text(encoding="utf-8")
    header = text.split("~A")[1].splitlines()[0].split()
    for curve in ("ROCK_TYPE", "FZI", "RQI", "RT_MARGIN", "PERM_RT"):
        assert curve in header
    assert "ROCK_TYPE_SOURCE" not in text.split("~A")[0]
    assert "ROCK_TYPE_SOURCE" not in header


def test_field_total_sums_measures_and_weights_averages(rock_model):
    a, b = rock_model.project.wells
    for ds, net, sw, phie, phih, vsh in ((a, 10.0, 0.2, 0.10, 1.0, 0.1),
                                         (b, 5.0, 0.6, 0.30, 3.0, 0.3)):
        row = ds.summary["rock_types"]["by_rt"][0]
        row.update({"samples": 10, "gross_sand": 20.0, "net_reservoir": 15.0, "net_pay": net,
                    "avg_sw_pay": sw, "avg_phie_pay": phie, "avg_vsh_pay": vsh,
                    "phih_pay": phih, "hcpv_net_pay": 2.0, "perm_geomean": 10.0,
                    "pct_core": 50.0})
    state = rock_type_field_total(rock_model.project.wells)
    assert state["state"] == "ok"
    row = next(r for r in state["rows"] if r["Rock type"] == 1)
    assert row["Net pay"] == pytest.approx(15.0) and row["HCPV"] == pytest.approx(4.0)
    assert row["Gross"] == pytest.approx(40.0)
    assert row["Avg PHIE"] == pytest.approx((0.10 * 10 + 0.30 * 5) / 15)       # net pay weights
    assert row["Avg Sw"] == pytest.approx((0.2 * 1.0 + 0.6 * 3.0) / 4.0)       # pore thickness
    assert row["Perm geomean"] == pytest.approx(10.0)
    assert row["% core"] == pytest.approx(50.0)


def test_mixed_definitions_have_no_field_total(rock_model):
    rock_model.project.get("W:B").summary["rock_types"]["fit_scope"] = "well"
    state = rock_type_field_total(rock_model.project.wells)
    assert state["state"] == "mixed" and state["rows"] == []
    assert "Field total" not in set(rock_types_frame(rock_model.project.wells)["Well"])


def test_no_rock_types_means_none(model):
    assert rock_type_field_total(model.project.wells) == {"state": "none", "rows": []}
    assert rock_types_frame(model.project.wells).empty


def test_summary_rock_table_hidden_without_the_key(qtbot, model):
    tab = SummaryTab(model)
    qtbot.addWidget(tab)
    tab.update_display()
    assert tab.rock_group.isHidden()


def test_summary_rock_table_shown_with_field_total_for_project_scope(qtbot, rock_model):
    tab = SummaryTab(rock_model)
    qtbot.addWidget(tab)
    tab.update_display()
    assert not tab.rock_group.isHidden()
    assert str(tab.rock_model._df.iloc[0, 0]) == "RT 1"
    assert "core-labelled" in tab.rock_note.text()
    assert "Field total" in set(tab.rock_wells_model._df["Well"])
    assert "mixed definitions" not in tab.rock_wells_note.text()
    swatch = tab.rock_model.data(tab.rock_model.index(0, 0), Qt.ItemDataRole.DecorationRole)
    assert swatch is not None


def test_summary_rock_table_has_no_field_total_for_mixed_definitions(qtbot, rock_model):
    rock_model.project.get("W:B").summary["rock_types"]["fit_scope"] = "zone"
    tab = SummaryTab(rock_model)
    qtbot.addWidget(tab)
    tab.update_display()
    assert "Field total" not in set(tab.rock_wells_model._df["Well"])
    assert "mixed definitions" in tab.rock_wells_note.text()


def test_rock_definitions_frame_and_csv(tmp_path, export_tab, model):
    defs = {**_RT_DEFS, "sets": {"*": _RT_SET}}
    frame = rock_type_definitions_frame(defs)
    assert list(frame["Rock type"]) == [1, 2, 3]
    assert np.isnan(frame.loc[0, "Lower boundary"]) and np.isnan(frame.loc[2, "Upper boundary"])
    assert frame.loc[1, "Lower boundary"] == pytest.approx(-0.2)
    assert frame.loc[1, "Upper boundary"] == pytest.approx(0.2)
    assert frame.loc[2, "FZI"] == pytest.approx(3.2) and set(frame["Set"]) == {"Project"}
    path = tmp_path / "defs.csv"
    assert ExportService().export_rock_type_definitions(defs, str(path))
    assert len(pd.read_csv(path)) == 3
    assert not ExportService().export_rock_type_definitions({}, str(tmp_path / "none.csv"))
    # the Export tab offers the action only once definitions exist
    assert export_tab.definitions_btn.isHidden()
    model.project.rock_types = defs
    export_tab.update_display()
    assert not export_tab.definitions_btn.isHidden()


def _strip_rock_types(m):
    for ds in m.project.wells:
        ds.summary.pop("rock_types", None)


def test_summary_rock_group_hints_to_run_when_enabled_without_results(qtbot, rock_model):
    _strip_rock_types(rock_model)
    rock_model.project.rock_types = {"sets": {}}
    rock_model.rock_typing_enabled = True
    tab = SummaryTab(rock_model)
    qtbot.addWidget(tab)
    tab.update_display()
    assert not tab.rock_group.isHidden()
    assert tab.rock_note.text() == (
        "Rock typing is on. Run the analysis for this well (or Run All Wells) to see pay and "
        "HCPV per rock type here.")
    assert tab.rock_note.property("status") == "warning"
    assert tab.rock_table.isHidden()


def test_summary_rock_group_hints_to_apply_definitions(qtbot, rock_model):
    _strip_rock_types(rock_model)
    rock_model.project.rock_types = None
    rock_model.rock_typing_enabled = True
    tab = SummaryTab(rock_model)
    qtbot.addWidget(tab)
    tab.update_display()
    assert not tab.rock_group.isHidden()
    assert tab.rock_note.text() == (
        "Rock typing is on but no definitions are applied. Fit and apply them in the Rock "
        "Typing tab.")


def test_summary_rock_group_hidden_when_disabled_without_results(qtbot, rock_model):
    _strip_rock_types(rock_model)
    rock_model.rock_typing_enabled = False
    tab = SummaryTab(rock_model)
    qtbot.addWidget(tab)
    tab.update_display()
    assert tab.rock_group.isHidden()


def test_summary_rock_group_follows_the_switch_cheaply(qtbot, rock_model, monkeypatch):
    _strip_rock_types(rock_model)
    rock_model.project.rock_types = {"sets": {}}
    tab = SummaryTab(rock_model)
    qtbot.addWidget(tab)
    tab.update_display()
    assert tab.rock_group.isHidden()
    full = []
    monkeypatch.setattr(SummaryTab, "update_display", lambda self: full.append(1))
    rock_model.rock_typing_enabled = True
    tab.refresh_rock_types()
    assert not tab.rock_group.isHidden() and not full
    rock_model.rock_typing_enabled = False
    tab.refresh_rock_types()
    assert tab.rock_group.isHidden()



# ---------------------------------------------------------------------------
# Excel: Uncertainty and Tornado sheets
# ---------------------------------------------------------------------------
def _mc_result():
    from modules import uncertainty as U

    cfg = U.UncertaintyConfig(n=20, seed=7)
    cfg.distributions["rw"].enabled = True
    cfg.distributions["rw"].low, cfg.distributions["rw"].mid, cfg.distributions["rw"].high = \
        -0.1, 0.0, 0.1
    metrics = U.METRICS
    vals = np.linspace(1.0, 2.0, 20)
    values, stats, det, torn = {}, {}, {}, {}
    scopes = ["field", "W:A", ("W:A", "Z1")]
    for sc in scopes:
        for m in metrics:
            values[(sc, m)] = vals
            stats[(sc, m)] = U.exceedance_stats(vals)
            det[(sc, m)] = 1.5
    for sc in scopes:
        for m in U.TORNADO_METRICS:
            torn[(sc, m)] = U.tornado_rows(1.5, {"rw": (1.4, 1.7, 0.9, 1.1),
                                                  "sw_cutoff": (1.45, 1.5, 0.4, 0.6)})
    return U.MCResult(
        config=U.config_to_dict(cfg), n=20, seed=7, sampling="lhs", names=("rw",),
        offsets=np.zeros((20, 1)), wells=[{"key": "W:A", "name": "Alpha"}], excluded=[],
        zones={"W:A": ["Z1"]}, values=values, deterministic=det, stats=stats, tornado=torn,
        rank_corr={m: {"rw": 0.5, "sw_cutoff": -0.2} for m in metrics}, clipped={}, warnings=[],
        elapsed_s=0.1)


def test_excel_without_uncertainty_has_no_mc_sheets(tmp_path, model):
    path = tmp_path / "plain.xlsx"
    assert ExportService().export_excel_wells(model.project.wells, str(path))
    sheets = pd.ExcelFile(path).sheet_names
    assert "Uncertainty" not in sheets and "Tornado" not in sheets


def test_excel_with_uncertainty_sheets(tmp_path, model):
    result = _mc_result()
    path = tmp_path / "mc.xlsx"
    assert ExportService().export_excel_wells(
        model.project.wells, str(path), uncertainty={"result": result, "stale": True})
    book = pd.ExcelFile(path)
    assert "Uncertainty" in book.sheet_names and "Tornado" in book.sheet_names
    raw = pd.read_excel(path, sheet_name="Uncertainty", header=None)
    head = dict(zip(raw[0][:6], raw[1][:6]))
    assert head["Seed"] == 7 and head["N"] == 20 and head["Sampling"] == "lhs"
    assert head["Stale"] == "Yes"
    assert head["Convention"].startswith("P90 = low case")
    assert "porosity" in head["Not varied"]
    table = pd.read_excel(path, sheet_name="Uncertainty", header=7)
    assert list(table.columns[:4]) == ["Scope", "Well", "Zone", "Metric"]
    assert len(table) == 3 * 7                         # field, well, zone x 7 metrics
    row = table[(table["Scope"] == "Zone") & (table["Metric"] == "Net pay (ft)")].iloc[0]
    assert row["Well"] == "Alpha" and row["Zone"] == "Z1"
    st = result.stats[(("W:A", "Z1"), "net_pay")]
    assert row["P90"] == pytest.approx(st["p90"]) and row["P10"] == pytest.approx(st["p10"])
    assert row["Deterministic"] == pytest.approx(1.5) and row["N valid"] == 20


def test_excel_uncertainty_fresh_flag_and_tornado_rows(tmp_path, model):
    result = _mc_result()
    path = tmp_path / "mc.xlsx"
    ExportService().export_excel_wells(
        model.project.wells, str(path), uncertainty={"result": result, "stale": False})
    raw = pd.read_excel(path, sheet_name="Uncertainty", header=None)
    assert dict(zip(raw[0][:6], raw[1][:6]))["Stale"] == "No"
    tor = pd.read_excel(path, sheet_name="Tornado")
    assert len(tor) == sum(len(v) for v in result.tornado.values())
    field = tor[(tor["Scope"] == "Field") & (tor["Metric"] == "Net pay (ft)")]
    expected = result.tornado[("field", "net_pay")]
    assert list(field["Parameter"]) == [e["name"] for e in expected]
    assert list(field["Swing"]) == pytest.approx([e["swing"] for e in expected])
    assert list(field["Output at low"]) == pytest.approx([e["at_low_input"] for e in expected])
    rw = field[field["Parameter"] == "rw"].iloc[0]
    assert rw["Rank correlation (field)"] == pytest.approx(0.5) and rw["Mode"] == "relative"
    assert tor[tor["Scope"] != "Field"]["Rank correlation (field)"].isna().all()
    # numeric offsets stay numeric; the text columns carry the mode and unit
    assert pd.api.types.is_numeric_dtype(tor["Low input"])
    from modules import uncertainty as U
    lo, hi = expected_rw = [e for e in expected if e["name"] == "rw"][0]["low_input"],         [e for e in expected if e["name"] == "rw"][0]["high_input"]
    assert rw["Low input (text)"] == U.format_offset("rw", "relative", lo)
    assert rw["Low input (text)"].endswith(" %") and rw["High input (text)"].endswith(" %")


def test_well_named_uncertainty_does_not_collide(tmp_path, model):
    model.project.add_well(_well("W:U", "Uncertainty"), activate=False)
    model.project.add_well(_well("W:T", "Tornado"), activate=False)
    path = tmp_path / "clash.xlsx"
    ExportService().export_excel_wells(
        model.project.wells, str(path), uncertainty={"result": _mc_result(), "stale": False})
    sheets = pd.ExcelFile(path).sheet_names
    assert len(sheets) == len({s.lower() for s in sheets})
    assert sheets.count("Uncertainty") == 1 and sheets.count("Tornado") == 1
    assert any(s.startswith("Uncertainty") and s != "Uncertainty" for s in sheets)
    assert any(s.startswith("Tornado") and s != "Tornado" for s in sheets)


def test_export_tab_passes_result_and_stale_flag(export_tab, model, tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(export_tab._service, "export_excel_wells",
                        lambda wells, path, depth=None, uncertainty=None:
                        seen.update(u=uncertainty) or True)
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(tmp_path / "x.xlsx"), "")))
    monkeypatch.setattr(export_tab, "_proceed", lambda: True)
    monkeypatch.setattr(export_tab, "export_scope", lambda: "all")
    export_tab._on_export_excel()
    assert seen["u"] is None
    result = _mc_result()
    result.basis, result.config_hash = {}, "x"       # config hash differs from the project's
    model.project.uncertainty_result = result
    export_tab._on_export_excel()
    assert seen["u"]["result"] is result and seen["u"]["stale"] is True
