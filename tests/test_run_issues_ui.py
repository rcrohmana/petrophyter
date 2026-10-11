"""Run outcome, Run issues and Stop analysis in the UI (P0-UI/UX U1 and U5)."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading

import pandas as pd
import pytest
from PyQt6.QtWidgets import QPushButton

import services.analysis_service as svc
from models.project import WellDataset
from tests.test_batch_run import _finish, _well
from ui.main_window import MainWindow
from ui.widgets.notification_banner import NotificationBanner

REPORT = {"failed": {}, "skipped": [], "cancelled": False}


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A modal box would block the offscreen run; fail loudly instead."""
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


def _add_wells(window, keys):
    for key in keys:
        window.model.project.add_well(_well(key))
    window.model.set_active_well(keys[0])
    return [window.model.project.get(k) for k in keys]


def _ran(window, qtbot, keys=("WELL:A",)):
    wells = _add_wells(window, list(keys))
    window._on_run_all()
    _finish(window, qtbot)
    return wells


def _report(ok, **extra):
    return {"ok": list(ok), **REPORT, **extra}


def _kind(window):
    return window.banner.property("kind")


# ---- banner action ---------------------------------------------------------------------

def test_banner_action_button_is_optional_and_calls_back(qtbot):
    banner = NotificationBanner()
    qtbot.addWidget(banner)
    calls = []
    banner.show_message("warning", "Careful", "Review", lambda: calls.append(1))
    assert banner.action_btn.isVisibleTo(banner) and banner.action_btn.text() == "Review"
    assert banner.action_btn.property("variant") == "ghost"
    banner.action_btn.click()
    assert calls == [1]
    banner.show_message("success", "Fine")
    assert not banner.action_btn.isVisibleTo(banner)
    banner.show_message("info", "Text only", "Review")  # no callback: no button
    assert not banner.action_btn.isVisibleTo(banner)


# ---- banner outcomes -------------------------------------------------------------------

def test_clean_run_shows_success_without_review(window, qtbot):
    _ran(window, qtbot)
    assert _kind(window) == "success"
    assert window.banner.message_label.text().startswith("Analysis complete — Net Pay")
    assert not window.banner.action_btn.isVisibleTo(window.banner)


def test_auto_rsh_unavailable_gives_a_warning_banner_with_review(window, qtbot):
    """The review probe: auto Rw/Rsh cannot be estimated, so the run has warnings."""
    window.model.rw_mode = "auto"
    window.model.rsh_mode = "auto"
    [ds] = _add_wells(window, ["WELL:A"])
    ds.las_data = ds.las_data.iloc[:12].copy()  # too few points for an estimate
    window._on_run_all()
    _finish(window, qtbot)
    assert ds.status == "run_ok"
    assert _kind(window) == "warning"
    assert "warning" in window.banner.message_label.text()
    assert window.banner.action_btn.text() == "Review"


def test_single_well_with_warnings_counts_them(window, qtbot):
    [ds] = _ran(window, qtbot)
    ds.summary["warnings"] = ["Rw could not be estimated automatically; using 0.05.",
                              "PHIE was substituted."]
    window._on_batch_finished(_report([ds.key]))
    text = window.banner.message_label.text()
    assert _kind(window) == "warning"
    assert text.startswith("Analysis complete with 2 warnings — Net Pay")
    assert window.banner.action_btn.text() == "Review"
    ds.summary["warnings"] = ["One only."]
    window._on_batch_finished(_report([ds.key]))
    assert window.banner.message_label.text().startswith("Analysis complete with 1 warning — ")


def test_infos_do_not_count_toward_the_banner(window, qtbot):
    [ds] = _ran(window, qtbot)
    ds.summary["warnings"] = []
    ds.summary["zone_diagnostics"] = {"Z": {"gross": 0, "pay": 0}}
    window._on_batch_finished(_report([ds.key]))
    assert _kind(window) in ("success", "warning")
    from services.issues import collect_issues, issue_counts
    counts = issue_counts(collect_issues(ds))
    expected = "warning" if counts["warning"] else "success"
    assert _kind(window) == expected


def test_several_wells_banner_counts_wells_with_warnings(window, qtbot):
    a, b = _ran(window, qtbot, ("WELL:A", "WELL:B"))
    b.summary["warnings"] = ["Rsh could not be estimated automatically; using 5.0."]
    window._on_batch_finished(_report([a.key, b.key], skipped=["WELL:C"]))
    assert _kind(window) == "warning"
    assert (window.banner.message_label.text()
            == "Analysis complete for 2 wells (1 unchanged) · 1 with warnings")
    assert window.banner.action_btn.text() == "Review"
    window.banner.action_btn.click()
    assert window.model.project.active_key == b.key


def test_failed_wells_banner_gets_review(window, qtbot):
    a, b = _ran(window, qtbot, ("WELL:A", "WELL:B"))
    b.error = "No formation matched"
    window._on_batch_finished({"ok": [a.key], "failed": {b.key: "No formation matched"},
                               "skipped": [], "cancelled": False})
    assert _kind(window) == "warning"
    assert window.banner.message_label.text().startswith("1 well failed: ")
    assert window.banner.action_btn.text() == "Review"


def test_review_opens_diagnostics_with_the_list(window, qtbot):
    a, b = _ran(window, qtbot, ("WELL:A", "WELL:B"))
    b.summary["warnings"] = ["Rw could not be estimated automatically; using 0.05.",
                             "PHIE was substituted."]
    window._on_batch_finished(_report([a.key, b.key]))
    window.banner.action_btn.click()
    diag = window.diag_tab
    assert window.tab_widget.currentWidget() is diag
    assert window.model.project.active_key == b.key
    assert diag.run_issues_group.isVisibleTo(diag)
    assert len(diag._issue_rows) == 2
    assert not diag.run_issues_empty.isVisibleTo(diag)
    assert diag._scroll.verticalScrollBar().value() == 0


# ---- Diagnostics Run issues ------------------------------------------------------------

def test_run_issues_empty_state_after_a_clean_run(window, qtbot):
    _ran(window, qtbot)
    diag = window.diag_tab
    diag.show_run_issues()
    assert diag.run_issues_group.isVisibleTo(diag)
    assert diag.run_issues_empty.text() == "No issues in the last run."
    assert diag.run_issues_empty.isVisibleTo(diag) and diag._issue_rows == []


def test_run_issues_list_has_severity_zone_and_go_to(window, qtbot):
    [ds] = _ran(window, qtbot)
    ds.summary["warnings"] = ["Rw could not be estimated automatically; using 0.05.",
                              "Selected formations not in the tops: X."]
    ds.summary["zone_diagnostics"] = {}
    diag = window.diag_tab
    diag.show_run_issues()
    rows = diag._issue_rows
    assert len(rows) == 2
    badges = [r.findChildren(type(diag.run_issues_empty))[0] for r in rows]
    assert [b.text() for b in badges] == ["Warning", "Warning"]
    assert all(b.property("status") == "warning" for b in badges)
    buttons = [r.findChild(QPushButton) for r in rows]
    assert [b.text() for b in buttons] == ["Go to", "Go to"]
    assert all(b.property("variant") == "ghost" for b in buttons)
    buttons[0].click()
    assert window.params_window.current_page() == "sat"
    buttons[1].click()
    assert window.params_window.current_page() == "scope"


def test_go_to_porosity_and_row_without_target(window, qtbot):
    [ds] = _ran(window, qtbot)
    ds.summary["warnings"] = ["PHIE was substituted for 4 samples.", "Something else."]
    diag = window.diag_tab
    diag.show_run_issues()
    with_button = [r for r in diag._issue_rows if r.findChild(QPushButton) is not None]
    assert len(with_button) == 1 and len(diag._issue_rows) == 2
    with_button[0].findChild(QPushButton).click()
    assert window.params_window.current_page() == "porosity"


def test_errors_sort_first_and_failed_well_shows_its_error(window, qtbot):
    [ds] = _ran(window, qtbot)
    ds.summary["warnings"] = ["W1"]
    ds.error = "Run failed badly"
    diag = window.diag_tab
    diag.show_run_issues()
    first = diag._issue_rows[0].findChildren(type(diag.run_issues_empty))[0]
    assert first.text() == "Error" and first.property("status") == "error"


def test_run_issues_hidden_before_a_run_and_after_reset(window, qtbot):
    _add_wells(window, ["WELL:A"])
    diag = window.diag_tab
    diag.show_run_issues()
    assert not diag.run_issues_group.isVisibleTo(diag)
    _ran_ds = window.model.project.get("WELL:A")
    window._on_run_all()
    _finish(window, qtbot)
    diag.show_run_issues()
    assert diag.run_issues_group.isVisibleTo(diag)
    diag.reset_ui()
    assert not diag.run_issues_group.isVisibleTo(diag)
    assert _ran_ds.status == "run_ok"


def test_solver_label_is_fed_by_the_issue_list(window, qtbot):
    [ds] = _ran(window, qtbot)
    ds.summary["warnings"] = ["SW_WS: 2 no-root, 1 failed solver points."]
    window.diag_tab.update_display()
    assert "2 no-root" in window.diag_tab.sw_warnings.text()


class _CoreStub:
    def get_summary(self):
        return {"n_samples": 5, "depth_range": (1000, 1010), "properties": ["POR"]}

    def validate_porosity(self, *args, **kwargs):
        from modules.core_handler import CoreValidationResult
        return CoreValidationResult(5, 0.0, 0.01, 0.01, 0.9, 0.9, 0.01, n_in_log_gaps=3)

    def validate_permeability(self, *args, **kwargs):
        return None

    def get_matched_data(self, *args, **kwargs):
        return pd.DataFrame()


def test_core_samples_in_log_gaps_line(window, qtbot, monkeypatch):
    [ds] = _ran(window, qtbot)
    diag = window.diag_tab
    monkeypatch.setattr(diag, "_plot_depth_track_with_core", lambda *a: [])
    ds.core_data = _CoreStub()
    diag.update_display()
    assert "3 core samples in log gaps" in diag.core_warnings.text()
    assert diag.core_warnings.property("status") == "warning"


# ---- Data Browser ----------------------------------------------------------------------

def _results_info(window):
    browser = window.data_browser
    root = browser.tree_model.item(0, 0)
    group = browser._find_group(root, "results")
    return root.child(group.row(), 1)


def test_browser_results_row_shows_warning_count_without_widgets(window, qtbot):
    [ds] = _ran(window, qtbot)
    assert _results_info(window).text().endswith("curves")
    ds.summary["warnings"] = [f"Warning number {i}." for i in range(7)][:2]
    window.data_browser.rebuild()
    info = _results_info(window)
    assert info.text() == "2 warnings"
    tip = info.toolTip().split("\n")
    assert tip == ["Warning number 0.", "Warning number 1."]
    ds.summary["warnings"] = [f"Warning number {i}." for i in range(7)]
    window.data_browser.rebuild()
    assert len(_results_info(window).toolTip().split("\n")) == 5
    ds.summary["warnings"] = ["Only one."]
    window.data_browser.rebuild()
    assert _results_info(window).text() == "1 warning"
    assert window.data_browser.findChildren(QPushButton) == []


# ---- Parameters ------------------------------------------------------------------------

def test_calculate_rw_rsh_shows_estimate_warnings(window, qtbot, monkeypatch):
    _add_wells(window, ["WELL:A"])
    estimate = {"rw": 0.05, "rsh": 4.0, "rw_source": "auto", "rsh_source": "auto",
                "warnings": ["Rsh: only 3 shale samples; using the default."]}
    monkeypatch.setattr(window.analysis_service, "calculate_rw_rsh",
                        lambda model, zone=None: estimate)
    window._on_calculate_rw_rsh()
    label = window.params_window.res_params_widget.message_label
    assert label.isVisibleTo(window.params_window.res_params_widget)
    assert label.text() == "Rsh: only 3 shale samples; using the default."
    assert label.property("status") == "warning"
    estimate["warnings"] = []
    window._on_calculate_rw_rsh()
    assert not label.isVisibleTo(window.params_window.res_params_widget)


# ---- Stop analysis ---------------------------------------------------------------------

def test_stop_is_disabled_when_idle_and_bound_to_esc(window, qtbot):
    stop = window.actions_["stop_analysis"]
    assert stop.text() == "Stop analysis" and stop.shortcut().toString() == "Esc"
    assert not stop.isEnabled()
    assert stop in window._menus["analysis"].actions()
    assert window.stop_button.defaultAction() is stop
    _add_wells(window, ["WELL:A"])
    assert not stop.isEnabled()


def _slow_after_first(monkeypatch):
    """The first well runs normally, every later one waits for the gate."""
    gate, lock, calls = threading.Event(), threading.Lock(), []
    real = svc.run_pipeline

    def run(*args, **kwargs):
        with lock:
            calls.append(1)
            first = len(calls) == 1
        if not first:
            gate.wait(10)
        return real(*args, **kwargs)

    monkeypatch.setattr(svc, "run_pipeline", run)
    return gate


def test_stop_enabled_while_running_then_reports_what_finished(window, qtbot, monkeypatch):
    gate = _slow_after_first(monkeypatch)
    window.batch_runner._pool.setMaxThreadCount(1)
    wells = _add_wells(window, ["WELL:A", "WELL:B", "WELL:C"])
    stop = window.actions_["stop_analysis"]
    window._on_run_all()
    assert stop.isEnabled()
    qtbot.waitUntil(lambda: wells[0].status == "run_ok", timeout=60000)
    assert stop.isEnabled() and window.batch_runner.is_running()
    stop.trigger()
    gate.set()
    assert not stop.isEnabled() and not window.batch_runner.is_running()
    assert _kind(window) == "info"
    assert (window.banner.message_label.text()
            == "Analysis stopped — 1 well finished, 2 not run")
    assert window.statusBar.currentMessage() == "Analysis stopped"
    assert not window.banner.action_btn.isVisibleTo(window.banner)
    qtbot.wait(300)  # a late result of a stopped well is ignored
    assert wells[0].status == "run_ok"
    assert wells[1].status == "loaded" and wells[2].status == "loaded"
    assert wells[1].results is None and wells[2].results is None


def test_stopped_stale_well_stays_stale(window, qtbot, monkeypatch):
    [a] = _ran(window, qtbot)
    a.run_params_hash = "older settings"
    a.stale = True
    gate = threading.Event()
    real = svc.run_pipeline
    monkeypatch.setattr(svc, "run_pipeline", lambda *a, **k: (gate.wait(10), real(*a, **k))[1])
    window._start_runs(["WELL:A"], force=True)
    window.actions_["stop_analysis"].trigger()
    gate.set()
    assert a.stale and a.status == "stale"
    assert window.banner.message_label.text() == "Analysis stopped — 0 wells finished, 1 not run"


def test_cancel_from_elsewhere_does_not_show_the_stopped_banner(window, qtbot, monkeypatch):
    gate = _slow_after_first(monkeypatch)
    gate.set()
    _add_wells(window, ["WELL:A", "WELL:B"])
    window._on_run_all()
    window.batch_runner.cancel()
    assert window.statusBar.currentMessage() == "Analysis cancelled"
    assert not window.banner.isVisibleTo(window)


def test_stop_does_nothing_when_idle(window):
    window._on_stop_analysis()
    assert window._stop_requested is False
    assert not window.banner.isVisibleTo(window)
