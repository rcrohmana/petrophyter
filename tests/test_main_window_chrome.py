# tests/test_main_window_chrome.py
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from ui.main_window import MainWindow


@pytest.fixture()
def window(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    return w


def test_menu_bar_actions_exist(window):
    for key in ("new_project", "open_las", "open_tops", "open_core", "save_session",
                "load_session", "run_analysis", "toggle_browser", "theme_light",
                "theme_dark", "about"):
        assert key in window.actions_, key


def test_no_giant_header(window):
    assert not hasattr(window, "title_label")
    assert not hasattr(window, "subtitle_label")


def test_tab_labels_have_no_emoji(window):
    import re
    emoji = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️]")
    for i in range(window.tab_widget.count()):
        assert not emoji.search(window.tab_widget.tabText(i))


def test_run_disabled_until_data(window):
    assert not window.run_button.isEnabled()
    assert not window.actions_["run_analysis"].isEnabled()


def test_window_title_updates(window):
    assert window.windowTitle() == "Petrophyter"


def test_menu_registry_keys(window):
    for key in ("file", "analysis", "view", "view_theme_sep"):
        assert key in window._menus, key
    assert window._menus["view_theme_sep"].isSeparator()


def test_toggle_browser_hides_data_browser(window):
    window.actions_["toggle_browser"].setChecked(False)
    window._toggle_browser(False)
    assert window.data_browser.isHidden()
    window._toggle_browser(True)
    assert not window.data_browser.isHidden()


def test_well_indicator_states(window):
    window.well_indicator.set_well("Atti_A-01", 45581, 12)
    assert "45,581 rows" in window.well_indicator.label.text()
    assert window.well_indicator.dot.property("kind") == "ok"
    window.well_indicator.set_empty()
    assert window.well_indicator.dot.property("kind") == "off"
    assert window.banner.isHidden()


def test_action_icons_refresh_on_theme_change(window):
    from themes.colors import set_current_theme
    from themes.icon_loader import clear_icon_cache

    iconed = {k for k, a in window.actions_.items() if not a.icon().isNull()}
    assert iconed == set(window._action_icons)
    assert "play" == window._action_icons["run_analysis"]

    set_current_theme("light")
    clear_icon_cache()
    window._refresh_action_icons()
    before = window.actions_["run_analysis"].icon().cacheKey()
    try:
        set_current_theme("dark")
        clear_icon_cache()
        window._refresh_action_icons()
        after = window.actions_["run_analysis"].icon().cacheKey()
    finally:
        set_current_theme("light")
        clear_icon_cache()
    assert before != after


def test_parameters_window_is_modeless_tool(window):
    from PyQt6.QtCore import Qt
    pw = window.params_window
    assert not pw.isModal()
    assert pw.windowFlags() & Qt.WindowType.Tool
    assert pw.parent() is window


def test_parameter_menus_cover_pages(window):
    from ui.parameters_window import PAGES
    window.params_window.set_core_available(True)  # page_core is disabled without core data
    window._refresh_core_actions()
    for key, title, _menu in PAGES:
        action = window.actions_[f"page_{key}"]
        assert action.text() == f"{title}…"
        action.trigger()
        assert window.params_window.isVisible()
        assert window.params_window.current_page() == key
    keys = {k for k, _, _ in PAGES}
    page_actions = {k[5:] for k in window.actions_ if k.startswith("page_")}
    assert page_actions == keys


def test_menu_order(window):
    titles = [a.text().replace("&", "") for a in window.menuBar().actions()]
    assert titles == ["File", "Session", "Analysis", "Parameters", "Corrections", "View", "Help"]


def test_core_matching_needs_core(window):
    assert not window.actions_["page_core"].isEnabled()
    assert not window.params_window.core_unit_combo.isEnabled()
    window.params_window.set_core_available(True)
    window._refresh_core_actions()
    assert window.actions_["page_core"].isEnabled()
    assert window.params_window.core_unit_combo.isEnabled()


def test_params_actions_and_shortcuts(window):
    from PyQt6.QtCore import Qt
    assert window.actions_["params_window"].text() == "Parameters Window"
    assert window.actions_["params_window"].shortcut().toString() == "Ctrl+P"
    for key in ("run_analysis", "toggle_browser", "params_window"):
        assert window.actions_[key].shortcutContext() == Qt.ShortcutContext.ApplicationShortcut
    assert window._action_icons["params_window"] == "sliders-horizontal"
    assert window.params_button.property("variant") == "ghost"


def test_params_page_headers_not_selectable(window):
    from PyQt6.QtCore import Qt
    lst = window.params_window.page_list
    headers = [lst.item(i) for i in range(lst.count()) if not lst.item(i).data(Qt.ItemDataRole.UserRole + 1)]
    assert [h.text() for h in headers] == ["ANALYSIS", "PARAMETERS", "CORRECTIONS"]
    assert all(not (h.flags() & Qt.ItemFlag.ItemIsSelectable) for h in headers)


def test_merge_action_disabled_without_pending_files(window):
    assert not window.actions_["merge_las"].isEnabled()
    assert window._action_icons["merge_las"] == "merge"


def test_merge_dialog_values_reach_model(window):
    window.merge_dialog.step_spin.setValue(1.0)
    window.merge_dialog.gap_spin.setValue(8.0)
    window._sync_model_from_ui()
    assert window.model.merge_step == 1.0
    assert window.model.merge_gap_limit == 8.0


def test_prepare_merge_populates_dialog_and_enables_action(window, monkeypatch):
    import pandas as pd
    from PyQt6.QtWidgets import QDialog
    import ui.main_window as mw

    class FakeParser:
        data = pd.DataFrame({"DEPTH": [100.0, 200.0]})

        def read_las_from_buffer(self, f):
            return True

        def get_depth_range(self):
            return (100.0, 200.0)

    monkeypatch.setattr(mw, "LASParser", FakeParser)
    monkeypatch.setattr(mw, "open", lambda *a, **k: __import__("io").StringIO(""), raising=False)
    monkeypatch.setattr(window.merge_dialog, "exec", lambda: QDialog.DialogCode.Rejected)
    window._prepare_merge(["a.las", "b.las"])
    assert window.actions_["merge_las"].isEnabled()
    assert window.merge_dialog.file_model.rowCount() == 2
    assert "2 LAS files" in window.merge_dialog.summary_label.text()


# Tree tests use a standalone panel: setting model data on the window would fire
# data_loaded -> _update_all_tabs, which needs a full QC report.
@pytest.fixture()
def browser(qtbot):
    from models.app_model import AppModel
    from ui.data_browser import DataBrowserPanel
    panel = DataBrowserPanel(AppModel())
    qtbot.addWidget(panel)
    return panel


def _group(panel, name):
    root = panel.tree_model.item(0)
    for row in range(root.rowCount()):
        if root.child(row, 0).text() == name:
            return root.child(row, 0), root.child(row, 1)
    raise AssertionError(name)


def test_browser_empty_state(browser):
    browser.rebuild()
    assert browser.empty_label.isVisibleTo(browser)
    assert not browser.tree.isVisibleTo(browser)


def test_browser_tree_from_model(browser, sample_log_data):
    browser.model.las_data = sample_log_data
    browser.set_las_sources([("Atti_A-01.las", len(sample_log_data))], merged=False, pending=False)
    browser.rebuild()
    root = browser.tree_model.item(0)
    assert [root.child(r, 0).text() for r in range(root.rowCount())] == [
        "LAS files", "Curves", "Formation tops", "Core data"]   # Results appears only after analysis
    curves, _info = _group(browser, "Curves")
    assert curves.rowCount() == len(sample_log_data.columns)
    assert _group(browser, "Formation tops")[1].text() == "Not loaded"


def test_browser_results_stale(browser, sample_log_data):
    browser.model.las_data = sample_log_data
    browser.model.results = sample_log_data.assign(VSH=0.3)   # any non-None frame marks results
    browser.rebuild()
    browser.set_results_stale(True)
    assert _group(browser, "Results")[1].text() == "out of date"


def test_browser_stale_flag_safe_without_results_and_reapplied(browser, sample_log_data):
    browser.set_results_stale(True)   # no tree yet: must not raise
    browser.model.las_data = sample_log_data
    browser.model.results = sample_log_data.assign(VSH=0.3)
    browser.rebuild()
    assert _group(browser, "Results")[1].text() == "out of date"


def test_browser_role_tags_and_muted_missing_groups(browser, sample_log_data):
    browser.model.las_data = sample_log_data
    browser.model.curve_mapping = {"GR": "GR", "RHOB": "None"}
    browser.rebuild()
    curves, _ = _group(browser, "Curves")
    infos = {curves.child(r, 0).text(): curves.child(r, 1).text() for r in range(curves.rowCount())}
    assert infos["GR"].startswith("GR")
    from PyQt6.QtCore import Qt
    tops_info = _group(browser, "Formation tops")[1]
    assert tops_info.data(Qt.ItemDataRole.ForegroundRole) is not None


def test_browser_action_requested_from_empty_link(browser, qtbot):
    with qtbot.waitSignal(browser.action_requested) as blocker:
        browser.empty_label.linkActivated.emit("open")
    assert blocker.args == ["open_las"]


def test_no_sidebar_left(window):
    assert not hasattr(window, "sidebar")
