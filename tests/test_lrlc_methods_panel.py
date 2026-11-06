"""Rendered equations, the Methods panel and the compact Method & Reference strip."""

import re

import pytest
from PyQt6.QtWidgets import QMessageBox

from modules import references
from modules.lrlc.methods import METHOD_TEXT
from tests.test_lrlc_tab import _enable, _well, window  # noqa: F401
from ui.widgets import equation_view
from ui.widgets.equation_view import EquationView, render_tex
from ui.widgets.lrlc_methods_panel import LrlcMethodsPanel, grouped_keys
from ui.widgets.method_box import MethodReferenceBox


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Ok)


def test_every_method_has_tex_and_legend():
    for key, info in METHOD_TEXT.items():
        assert info.equation_tex, key
        assert info.legend, key
        assert info.equation, key  # the plain text form stays


def test_every_tex_line_renders(qtbot):
    for key, info in METHOD_TEXT.items():
        for tex in list(info.equation_tex) + [sym for sym, _ in info.legend]:
            for color in ("black", "white"):
                pix = render_tex(tex, color, 1.0)
                assert not pix.isNull() and pix.width() > 0, (key, tex)


def test_render_cache_is_keyed_and_reused(qtbot):
    equation_view.clear_cache()
    tex = METHOD_TEXT["buckles"].equation_tex[0]
    first = render_tex(tex, "black", 1.0)
    assert render_tex(tex, "black", 1.0) is first
    assert render_tex(tex, "white", 1.0) is not first
    two = render_tex(tex, "black", 2.0)
    assert two is not first and two.devicePixelRatio() == 2.0
    assert two.width() > first.width()


def test_equation_view_sizes_and_follows_theme(qtbot):
    view = EquationView()
    qtbot.addWidget(view)
    assert view.sizeHint().height() == 0 or not view.lines
    view.set_lines(METHOD_TEXT["laminated"].equation_tex)
    assert view.sizeHint().height() > 40
    view.resize(view.sizeHint())
    view.show()
    light = view.grab().toImage()
    from themes.colors import set_current_theme
    try:
        set_current_theme("dark")
        view.refresh_theme()
        dark = view.grab().toImage()
    finally:
        set_current_theme("light")
    assert light != dark


def test_panel_lists_every_method(qtbot):
    panel = LrlcMethodsPanel()
    qtbot.addWidget(panel)
    listed = [k for _, keys in grouped_keys() for k in keys]
    assert sorted(listed) == sorted(METHOD_TEXT)
    assert sorted(panel.method_keys()) == sorted(METHOD_TEXT)
    for key in METHOD_TEXT:
        assert panel.show_method(key)
        assert panel.current_key == key
        assert panel.title_label.text().count(METHOD_TEXT[key].title.split(" ")[0]) >= 1
        assert panel.equation_view.lines == METHOD_TEXT[key].equation_tex
        assert panel.assumptions.text() == METHOD_TEXT[key].assumptions
        assert panel.limits.text() == METHOD_TEXT[key].limits
        assert panel.legend_grid.count() == 2 * len(METHOD_TEXT[key].legend)
    assert not panel.show_method("no_such_method")
    assert panel.current_key == "variable_mn" or panel.current_key == list(METHOD_TEXT)[-1]


def test_panel_criteria_and_references(qtbot):
    panel = LrlcMethodsPanel()
    qtbot.addWidget(panel)
    panel.show()
    panel.show_method("screening")
    assert panel.criteria.isVisible() and panel.criteria.rowCount() == 6
    panel.show_method("laminated")
    assert panel.criteria.isHidden()
    html = panel.references.text()
    assert "doi.org" in html or "href" in html
    first = references.format_full(METHOD_TEXT["laminated"].refs[0]).split(".")[0]
    assert first.split(",")[0] in html
    assert panel.references.openExternalLinks()
    panel.show_method("rt_chain")  # no references: the section is hidden
    assert panel.references.isHidden() and panel.references_heading.isHidden()


def test_panel_text_width_is_capped(qtbot):
    panel = LrlcMethodsPanel()
    qtbot.addWidget(panel)
    panel.resize(1800, 900)
    panel.show()
    qtbot.wait(20)
    assert panel.sheet.width() <= 800


def test_tab_has_methods_panel_and_show_panel_selects(window, qtbot):  # noqa: F811
    _well(window)
    _enable(window, qtbot)
    tab = window.lrlc_tab
    tab.show_panel("methods", "invasion")
    assert tab.panels.currentWidget() is tab.methods_panel
    assert tab.methods_panel.current_key == "invasion"
    tab.show_panel("methods", "pyrite")
    assert tab.methods_panel.current_key == "pyrite"


def test_goto_target_opens_a_method(window, qtbot):  # noqa: F811
    _well(window)
    _enable(window, qtbot)
    window._on_goto_target("lrlc.methods.variable_mn")
    tab = window.lrlc_tab
    assert window.tab_widget.currentWidget() is tab
    assert tab.panels.currentWidget() is tab.methods_panel
    assert tab.methods_panel.current_key == "variable_mn"


def test_strip_link_opens_methods_at_its_method(window, qtbot):  # noqa: F811
    _well(window)
    _enable(window, qtbot)
    tab = window.lrlc_tab
    tab.show_panel("screening")
    seen = []
    tab.rt_cutoff_box.method_requested.connect(seen.append)
    tab.rt_cutoff_box.link.click()
    assert seen == ["rt_cutoff"]
    assert tab.panels.currentWidget() is tab.methods_panel
    assert tab.methods_panel.current_key == "rt_cutoff"
    # a strip deep inside another panel reaches the tab as well
    tab.show_panel("remediation")
    box = tab.remediation_form.laminated_box
    box.link.click()
    assert tab.panels.currentWidget() is tab.methods_panel
    assert tab.methods_panel.current_key == "laminated"


def test_strip_is_compact(qtbot):
    box = MethodReferenceBox()
    qtbot.addWidget(box)
    box.set_method(METHOD_TEXT["invasion"])
    box.resize(700, 300)
    box.show()
    texts = " ".join(label.text() for label in box.findChildren(type(box.title_label)))
    assert METHOD_TEXT["invasion"].assumptions[:30] not in texts
    assert METHOD_TEXT["invasion"].limits[:30] not in texts
    assert box.link.isVisible() and box.equation_view.isVisible()
    assert not box.equation.isVisible()
    assert box.sizeHint().height() < 300


def test_no_internal_ids_in_method_texts():
    pattern = re.compile(r"\b(?:[LSP]\d{1,2}|spec)\b")
    for key, info in METHOD_TEXT.items():
        text = " ".join([info.title, info.assumptions, info.limits]
                        + [m for _, m in info.legend])
        assert not pattern.search(text), key
