"""Main-window wiring for multi-well: session v2, shared tops/core, zone hooks, lazy tabs."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QFileDialog

from tests.test_multiwell_loading import _write
from ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A modal box would block the offscreen test run; fail loudly instead."""
    from PyQt6.QtWidgets import QMessageBox

    def refuse(*args, **kwargs):
        raise AssertionError(f"unexpected dialog: {args[1:3]}")

    for name in ("warning", "critical", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(refuse))


@pytest.fixture
def window(qtbot):
    widget = MainWindow()
    qtbot.addWidget(widget)
    yield widget
    widget.close()


@pytest.fixture
def two_wells(window, tmp_path):
    """BKS-01 then BKS-02 (active)."""
    window._load_single_las(_write(tmp_path, "a.las", well="BKS-01"))
    window._load_single_las(_write(tmp_path, "b.las", well="BKS-02"))
    return window


def _shared_tops(tmp_path):
    path = tmp_path / "tops.csv"
    path.write_text(
        "Well\tFormation\tTop (ft)\tBottom (ft)\n"
        "BKS-01\tUpper\t1005\t1030\n"
        "BKS-01\tLower\t1030\t1055\n"
        "BKS-02\tUpper\t1010\t1040\n"
        "XYZ-9\tUpper\t1000\t1020\n"
    )
    return str(path)


def _key(window, name):
    return next(ds.key for ds in window.model.project.wells if ds.display_name == name)


def test_tops_with_well_column_feed_every_loaded_well(two_wells, tmp_path):
    window = two_wells
    path = _shared_tops(tmp_path)
    window._on_tops_file_selected(path)
    first = window.model.project.get(_key(window, "BKS-01"))
    active = window.model.active_well
    assert active.display_name == "BKS-02"
    assert [fm.name for fm in active.formation_tops.formations] == ["Upper"]
    assert [fm.name for fm in first.formation_tops.formations] == ["Upper", "Lower"]
    assert first.tops_path == path and active.tops_path == path
    text = window.banner.message_label.text()
    assert "XYZ-9" in text and "BKS-01" in text


def test_tops_without_a_match_for_the_active_well_leave_it_alone(two_wells, tmp_path):
    window = two_wells
    path = tmp_path / "tops.csv"
    path.write_text("Well\tFormation\tTop (ft)\tBottom (ft)\nBKS-01\tUpper\t1005\t1030\n")
    window._on_tops_file_selected(str(path))
    assert window.model.active_well.formation_tops is None
    assert window.model.project.get(_key(window, "BKS-01")).formation_tops is not None
    assert "active well" in window.banner.message_label.text()


def test_core_with_well_column_feeds_every_loaded_well(two_wells, tmp_path):
    window = two_wells
    path = tmp_path / "core.csv"
    path.write_text(
        "Well\tDepth (ft)\tPorosity\tPermeability\n"
        "BKS-01\t1010\t0.20\t15\nBKS-01\t1020\t0.22\t30\nBKS-02\t1015\t0.18\t8\n"
    )
    window._on_core_file_selected(str(path))
    first = window.model.project.get(_key(window, "BKS-01"))
    assert len(first.core_data.data) == 2 and first.core_path == str(path)
    assert len(window.model.core_data.data) == 1


def test_summary_row_activates_the_well(two_wells):
    window = two_wells
    key = _key(window, "BKS-01")
    window.summary_tab.well_activated.emit(key)
    assert window.model.project.active_key == key


def test_browser_zone_request_opens_the_zone_scope(two_wells, tmp_path):
    window = two_wells
    window._on_tops_file_selected(_shared_tops(tmp_path))
    window.data_browser.action_requested.emit("edit_zone:UPPER")
    assert window.model.edit_scope == "well"
    assert window.model.edit_zone == "UPPER"
    assert window.params_window.current_page() == "zones"


def test_zone_calculate_uses_the_zone(two_wells, tmp_path, monkeypatch):
    window = two_wells
    window._on_tops_file_selected(_shared_tops(tmp_path))
    seen = {}

    def fake(model, zone=None):
        seen["zone"] = zone
        return None

    monkeypatch.setattr(window.analysis_service, "calculate_rw_rsh", fake)
    monkeypatch.setattr("ui.main_window.QMessageBox.warning", staticmethod(lambda *a, **k: None))
    window._on_calculate_rw_rsh()
    assert seen["zone"] is None
    window.model.set_edit_scope("well", "UPPER")
    window._on_calculate_rw_rsh()
    assert seen["zone"] == "UPPER"


def test_zone_shale_calculate_uses_the_zone(two_wells, tmp_path, monkeypatch):
    window = two_wells
    window._on_tops_file_selected(_shared_tops(tmp_path))
    seen = []
    monkeypatch.setattr(window.analysis_service, "calculate_shale_parameters",
                        lambda model, zone=None: seen.append(zone))
    monkeypatch.setattr("ui.main_window.QMessageBox.warning", staticmethod(lambda *a, **k: None))
    window._on_calculate_shale()
    window.model.set_edit_scope("well", "UPPER")
    window._on_calculate_shale()
    assert seen == [None, "UPPER"]


def test_hidden_plot_tabs_redraw_when_shown(two_wells, monkeypatch):
    window = two_wells
    calls = []
    monkeypatch.setattr(window.log_tab, "update_display", lambda: calls.append("log"))
    window.tab_widget.setCurrentWidget(window.qc_tab)
    window._update_all_tabs()
    assert calls == []
    assert window.log_tab in window._dirty_tabs
    window.tab_widget.setCurrentWidget(window.log_tab)
    assert calls == ["log"]
    window.tab_widget.setCurrentWidget(window.qc_tab)
    window.tab_widget.setCurrentWidget(window.log_tab)
    assert calls == ["log"]                       # nothing changed since


def test_v2_session_round_trip_restores_wells(two_wells, tmp_path, monkeypatch):
    window = two_wells
    window._on_tops_file_selected(_shared_tops(tmp_path))
    first = _key(window, "BKS-01")
    window.model.set_entry("m", "manual", 1.8, scope="well", zone="", well=first)
    session = tmp_path / "s.json"
    assert window.session_service.save_session(window.model, str(session))

    window.batch_runner.cancel()
    window.model.reset()
    window.model.set_edit_scope("project")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(session), ""))
    )
    window._on_load_session()
    project = window.model.project
    assert [ds.display_name for ds in project.wells] == ["BKS-01", "BKS-02"]
    assert project.active.display_name == "BKS-02"
    restored = project.get(first)
    assert restored.formation_tops is not None
    assert window.model.get_entry("m", scope="well", zone="", well=first)["value"] == pytest.approx(1.8)
    assert window.model.edit_scope == "project"
    assert not any(ds.stale for ds in project.wells)    # nothing has run yet
