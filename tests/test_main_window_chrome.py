# tests/test_main_window_chrome.py
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QSettings

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
    for key, title, _menu, _icon in PAGES:
        action = window.actions_[f"page_{key}"]
        assert action.text() == f"{title}…"
        action.trigger()
        assert window.params_window.isVisible()
        assert window.params_window.current_page() == key
    keys = {k for k, _, _, _ in PAGES}
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
    assert [h.text() for h in headers] == ["ANALYSIS", "PARAMETERS", "CORRECTIONS", "SCOPES"]
    assert all(not (h.flags() & Qt.ItemFlag.ItemIsSelectable) for h in headers)


def test_merge_action_always_opens_multi_file_dialog(window):
    # Merging is decided per group in the Load Summary, so the action is
    # never tied to pending files; it opens the same multi-file open dialog.
    assert window.actions_["merge_las"].isEnabled()
    assert window._action_icons["merge_las"] == "merge"


def test_merge_dialog_values_reach_model(window):
    window.merge_dialog.step_spin.setValue(1.0)
    window.merge_dialog.gap_spin.setValue(8.0)
    window._sync_model_from_ui()
    assert window.model.merge_step == 1.0
    assert window.model.merge_gap_limit == 8.0


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
    browser.model.active_well.stale = True
    browser.rebuild()
    browser.set_results_stale(True)
    assert _group(browser, "Results")[1].text() == "out of date"


def test_browser_stale_flag_safe_without_results_and_reapplied(browser, sample_log_data):
    browser.set_results_stale(True)   # no tree yet: must not raise
    browser.model.las_data = sample_log_data
    browser.model.results = sample_log_data.assign(VSH=0.3)
    browser.model.active_well.stale = True
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


def test_no_information_messagebox_in_codebase():
    from pathlib import Path
    offenders = [
        str(p) for p in Path("ui").rglob("*.py")
        if "QMessageBox.information" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_analysis_complete_shows_banner_not_modal(window, qtbot, monkeypatch):
    import pandas as pd
    called = {"modal": False}
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: called.__setitem__("modal", True))
    results = pd.DataFrame({"DEPT": [1000.0], "PHIE": [0.2]})
    summary = {"net_pay": 1625.4, "gross_sand": 2768.8, "ng_pay": 0.587}
    window._on_analysis_completed(results, summary)
    assert called["modal"] is False
    assert window.banner.isVisibleTo(window)
    assert "1625.4" in window.banner.message_label.text()


def test_qc_chip(window):
    window.update_qc_chip(80)
    assert window.qc_chip.text() == "QC 80/100"
    assert window.qc_chip.property("status") == "warning"
    window.update_qc_chip(95)
    assert window.qc_chip.property("status") == "success"
    window.update_qc_chip(None)
    assert not window.qc_chip.isVisibleTo(window)


def test_parameter_change_marks_results_stale(window):
    window.model.calculated = True     # as after a successful analysis
    window.params_window.parameters_updated.emit()
    assert window.stale_label.isVisibleTo(window)
    assert window.stale_label.property("status") == "warning"
    window._on_analysis_started()
    assert not window.stale_label.isVisibleTo(window)


def test_no_stale_before_first_analysis(window):
    window.params_window.parameters_updated.emit()
    assert not window.stale_label.isVisibleTo(window)


def test_restore_does_not_mark_stale(window):
    window.model.calculated = True
    window._restoring = True
    window.params_window.parameters_updated.emit()
    window._restoring = False
    assert not window.stale_label.isVisibleTo(window)


def test_export_success_goes_to_banner(window):
    window.export_tab.show_export_success("done.csv")
    assert "Exported to done.csv" in window.banner.message_label.text()


def test_session_restore_guard_resets_flag(window):
    window._update_ui_from_model()
    assert window._restoring is False


def test_ui_state_persists(qtbot):
    w1 = MainWindow()
    qtbot.addWidget(w1)
    w1.tab_widget.setCurrentIndex(3)
    w1.close()
    settings = QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope, "Petrophyter Team", "Petrophyter")
    assert settings.value("ui/activeTab", type=int) == 3
    w2 = MainWindow()
    qtbot.addWidget(w2)
    assert w2.tab_widget.currentIndex() == 3
    w2.close()


def test_params_window_page_persists_but_starts_closed(qtbot):
    w1 = MainWindow()
    qtbot.addWidget(w1)
    w1.params_window.open_page("sat")
    w1.close()
    w2 = MainWindow()
    qtbot.addWidget(w2)
    assert w2.params_window.current_page() == "sat"
    assert not w2.params_window.isVisible()
    w2.close()


def test_data_browser_visibility_persists(qtbot):
    w1 = MainWindow()
    qtbot.addWidget(w1)
    w1.actions_["toggle_browser"].setChecked(False)
    w1.close()
    w2 = MainWindow()
    qtbot.addWidget(w2)
    assert not w2.data_browser.isVisibleTo(w2)
    assert not w2.actions_["toggle_browser"].isChecked()
    w2.close()


def test_tests_use_isolated_settings(tmp_path):
    settings = QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope, "Petrophyter Team", "Petrophyter")
    assert tmp_path.as_posix() in settings.fileName()


def test_restoring_guard_is_reentrant(window):
    from ui.main_window import _restoring_guard

    @_restoring_guard
    def outer(win):
        win._update_ui_from_model()          # guarded; its finally must not clear the flag
        assert win._restoring is True
        win.params_window.parameters_updated.emit()

    window.model.calculated = True
    outer(window)
    assert window._restoring is False
    assert not window.stale_label.isVisibleTo(window)


def _write_las(path, top, bottom):
    import lasio
    import numpy as np

    depth = np.arange(top, bottom + 0.25, 0.5)
    las = lasio.LASFile()
    las.well.WELL.value = "T-01"
    las.well.NULL.value = -999.25
    las.append_curve("DEPT", depth, unit="FT")
    las.append_curve("GR", 50 + 20 * np.sin(depth / 10), unit="GAPI")
    las.append_curve("RHOB", np.full_like(depth, 2.4), unit="G/C3")
    with open(path, "w") as handle:
        las.write(handle, version=2.0)
    return len(depth)


def test_merge_keeps_per_source_row_counts(window, qtbot, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QDialog
    from ui.widgets.load_summary_dialog import LoadSummaryDialog

    n1 = _write_las(tmp_path / "a.las", 1000, 1100)
    n2 = _write_las(tmp_path / "b.las", 1090, 1300)
    monkeypatch.setattr(
        LoadSummaryDialog, "exec", lambda self: QDialog.DialogCode.Accepted
    )
    window._on_las_files_selected([str(tmp_path / "a.las"), str(tmp_path / "b.las")])
    qtbot.waitUntil(lambda: window.model.las_data is not None and not window._bulk_loading,
                    timeout=20000)
    well = window.model.active_well
    assert well.merged
    assert [(s["name"], s["rows"]) for s in well.sources] == [("a.las", n1), ("b.las", n2)]
    assert len(window.model.las_data) > n1
    assert len(well.las_parser.data) == len(window.model.las_data)


def test_load_session_marks_results_stale(window, monkeypatch, tmp_path):
    # Sessions restore parameters only, so results in memory stay stale.
    from PyQt6.QtWidgets import QFileDialog

    window.model.calculated = True
    window.params_window.parameters_updated.emit()
    assert window.stale_label.isVisibleTo(window)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("x.json", ""))
    )
    monkeypatch.setattr(window.session_service, "load_session", lambda p: {"k": 1})
    monkeypatch.setattr(
        window.session_service, "apply_session_to_model", lambda m, d: None
    )
    window._on_load_session()
    assert window.stale_label.isVisibleTo(window)
    window.model.calculated = False
    window._on_load_session()
    assert not window.stale_label.isVisibleTo(window)


def test_fresh_load_clears_stale(window, tmp_path):
    _write_las(tmp_path / "c.las", 1000, 1050)
    window.model.calculated = True
    window.params_window.parameters_updated.emit()
    assert window.stale_label.isVisibleTo(window)
    window._load_single_las(str(tmp_path / "c.las"))
    assert not window.stale_label.isVisibleTo(window)


def test_loaded_well_records_its_source_files(window, tmp_path):
    _write_las(tmp_path / "d.las", 1000, 1050)
    window._load_single_las(str(tmp_path / "d.las"))
    # The loader records the source file on the well; the browser shows it.
    assert window.model.active_well.sources[0]["name"] == "d.las"
    root = window.data_browser.tree_model.item(0)
    las_group = root.child(0, 0)
    assert las_group.toolTip() == "LAS files"
    assert las_group.child(0, 0).toolTip() == "d.las"


def test_table_model_float_decimals():
    import pandas as pd
    from ui.widgets.table_model import PandasTableModel

    df = pd.DataFrame({"Top": [4500.0], "Frac": [0.123456]})
    default = PandasTableModel(df)
    assert default.data(default.index(0, 0)) == "4500.0000"
    one = PandasTableModel(df, float_decimals=1)
    assert one.data(one.index(0, 0)) == "4500.0"
    per_col = PandasTableModel(df, float_decimals={"Top": 1})
    assert per_col.data(per_col.index(0, 0)) == "4500.0"
    assert per_col.data(per_col.index(0, 1)) == "0.1235"


def test_plot_text_chrome_follows_theme(qtbot):
    import pandas as pd
    from matplotlib.colors import to_hex
    from themes import colors as theme_colors
    from themes.colors import get_plot_chrome
    from ui.widgets.plot_widget import HistogramPlot

    plot = HistogramPlot()
    qtbot.addWidget(plot)
    plot.plot_histogram(pd.Series([0.1, 0.2, 0.2, 0.3]), title="PHIE", x_label="v")
    ax = plot.figure.axes[0]
    ax.legend()
    try:
        for theme in ("light", "dark"):
            theme_colors.set_current_theme(theme)
            plot.update_theme_colors()
            plot.canvas.draw()
            chrome = get_plot_chrome()
            assert to_hex(ax.title.get_color()).lower() == chrome["text"].lower()
            frame = ax.get_legend().get_frame()
            assert to_hex(frame.get_facecolor()).lower() == chrome["axes"].lower()
    finally:
        theme_colors.set_current_theme("light")


def test_table_model_aligns_numeric_strings_right():
    import pandas as pd
    from PyQt6.QtCore import Qt
    from ui.widgets.table_model import PandasTableModel

    df = pd.DataFrame({
        "Name": ["GR", "RHOB"],
        "Pct": ["100.0%", "-"],
        "Val": ["0.1234", ""],
        "Mixed": ["1.0", "abc"],
    })
    model = PandasTableModel(df)
    right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    align = lambda c: model.data(model.index(0, c), Qt.ItemDataRole.TextAlignmentRole)
    assert align(0) == Qt.AlignmentFlag.AlignCenter
    assert align(1) == right and align(2) == right
    assert align(3) == Qt.AlignmentFlag.AlignCenter


def test_theme_change_recolors_cached_icons(window):
    from themes.colors import get_current_theme, set_current_theme
    from themes.icon_loader import clear_icon_cache

    start = get_current_theme()
    try:
        perm = window.params_window.perm_params_widget
        merge_ok = window.merge_dialog._ok_button
        before = (perm.calc_btn.icon().cacheKey(), merge_ok.icon().cacheKey())
        set_current_theme("dark" if start == "light" else "light")
        clear_icon_cache()
        window._handle_theme_change(get_current_theme())
        after = (perm.calc_btn.icon().cacheKey(), merge_ok.icon().cacheKey())
        assert before[0] != after[0]
        assert before[1] != after[1]
    finally:
        set_current_theme(start)
        clear_icon_cache()
        window._handle_theme_change(start)


def test_banner_refresh_theme_rerenders_kind_icon(window):
    from themes.colors import get_current_theme, set_current_theme
    from themes.icon_loader import clear_icon_cache

    start = get_current_theme()
    try:
        window.show_banner("success", "ok")
        before = window.banner.icon_label.pixmap().cacheKey()
        set_current_theme("dark" if start == "light" else "light")
        clear_icon_cache()
        window.banner.refresh_theme()
        assert window.banner.icon_label.pixmap().cacheKey() != before
    finally:
        set_current_theme(start)
        clear_icon_cache()


def test_run_disabled_while_analysis_running(window):
    window._on_analysis_started()
    assert not window.actions_["run_analysis"].isEnabled()


def _walk_menu_actions(menu):
    for action in menu.actions():
        if action.isSeparator():
            continue
        yield action
        if action.menu() is not None:
            yield from _walk_menu_actions(action.menu())


def test_every_menu_action_has_icon(window):
    """F9: every menubar action (submenus included) carries an icon."""
    seen = []
    for top in window.menuBar().actions():
        for action in _walk_menu_actions(top.menu()):
            seen.append(action.text())
            assert not action.icon().isNull(), action.text()
    assert "Theme" in seen and "Exit" in seen


def test_page_actions_use_pages_icons(window):
    from themes.icon_loader import get_icon
    from ui.parameters_window import PAGES
    for key, _title, _menu, icon in PAGES:
        assert window._action_icons[f"page_{key}"] == icon
        action = window.actions_[f"page_{key}"]
        assert action.icon().cacheKey() == get_icon(icon).cacheKey()
    assert window._action_icons["exit"] == "log-out"
    assert window._action_icons["theme_menu"] == "palette"


def test_parameters_page_list_items_have_icons(window):
    from PyQt6.QtCore import Qt
    from ui.parameters_window import EXTRA_PAGES, PAGES
    pw = window.params_window
    icons = {key: icon for key, _t, _m, icon in PAGES + EXTRA_PAGES}
    found = set()
    for row in range(pw.page_list.count()):
        item = pw.page_list.item(row)
        key = item.data(Qt.ItemDataRole.UserRole + 1)
        if key is None:
            assert item.icon().isNull()  # group headers carry no icon
            continue
        found.add(key)
        assert not item.icon().isNull(), key
    assert found == set(icons)


def test_data_browser_context_actions_have_icons(window):
    from ui.data_browser import _CONTEXT_ACTIONS
    for keys in _CONTEXT_ACTIONS.values():
        for key in keys:
            assert not window.actions_[key].icon().isNull(), key


def test_disabled_icon_uses_text_disabled(qapp):
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QIcon
    from themes.colors import get_color, get_current_theme
    from themes.icon_loader import get_icon
    icon = get_icon("merge")
    img = icon.pixmap(QSize(16, 16), QIcon.Mode.Disabled).toImage()
    target = get_color("text_disabled", get_current_theme()).lstrip("#").lower()
    colors = {img.pixelColor(x, y).name()[1:] for x in range(16) for y in range(16)
              if img.pixelColor(x, y).alpha() == 255}
    assert target in colors


def test_menu_geometry_and_checked_icon_frame(window, qtbot):
    """Icon sits ~8px from the border, text x is identical on every row, and a
    checked action's icon gets the accent frame (QMenu::icon:checked)."""
    from themes import ThemeManager
    from themes.colors import get_color, get_current_theme
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    manager = ThemeManager(app, "")
    manager.set_theme("light")
    try:
        menu = window._menus["view"]
        menu.popup(window.mapToGlobal(window.rect().center()))
        qtbot.waitExposed(menu)
        img = menu.grab().toImage()
        accent = get_color("accent", get_current_theme()).lstrip("#").lower()
        first, second = menu.actions()[0], menu.actions()[1]
        assert first.isChecked()
        g1, g2 = menu.actionGeometry(first), menu.actionGeometry(second)
        bg = img.pixelColor(img.width() // 2, g1.top() + 1)

        def first_x(g, skip_bg):
            for x in range(2, img.width() - 2):
                for y in range(g.top() + 2, g.bottom() - 1):
                    if img.pixelColor(x, y) != skip_bg:
                        return x
        icon_x = first_x(g2, bg)  # unchecked row: bare icon pixels
        assert 5 <= icon_x <= 10, icon_x
        frame_pixels = [img.pixelColor(x, y).name()[1:]
                        for x in range(2, 30) for y in range(g1.top() + 1, g1.bottom())]
        assert accent in frame_pixels  # checked icon frame is drawn
        # text column: scan right of the icon column for the first glyph pixel
        def text_x(g):
            for x in range(30, img.width() - 2):
                for y in range(g.top() + 2, g.bottom() - 1):
                    if img.pixelColor(x, y) != bg:
                        return x
        assert text_x(g1) == text_x(g2)
    finally:
        menu.hide()
        app.setStyleSheet("")
