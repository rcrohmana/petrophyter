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


def test_toggle_browser_hides_sidebar(window):
    window.actions_["toggle_browser"].setChecked(False)
    window._toggle_browser(False)
    assert window.sidebar.isHidden()
    window._toggle_browser(True)
    assert not window.sidebar.isHidden()


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


def test_sidebar_has_no_parameter_widgets(window):
    assert not hasattr(window.sidebar, "vsh_params_widget")
    assert not hasattr(window.sidebar, "analysis_mode_widget")


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
