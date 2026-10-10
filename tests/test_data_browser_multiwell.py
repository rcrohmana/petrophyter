"""Multi-well Data Browser tree and WellSelector."""
import numpy as np
import pandas as pd
import pytest
from PyQt6.QtCore import Qt

from models.app_model import AppModel
from models.project import WellDataset
from ui.data_browser import DataBrowserPanel, _KIND_ROLE, _WELL_ROLE
from ui.widgets import WellSelector


def _frame(extra=()):
    data = {"DEPTH": np.linspace(1000, 1100, 5), "GR": np.arange(5.0)}
    for name in extra:
        data[name] = np.arange(5.0)
    return pd.DataFrame(data)


def _well(key, name, extra=()):
    ds = WellDataset(key=key, display_name=name)
    ds.las_data = _frame(extra)
    ds.sources = [{"name": f"{name}.las", "path": "", "rows": 5}]
    return ds


@pytest.fixture()
def model():
    m = AppModel()
    m.add_well(_well("WELL:A", "Alpha"))
    m.add_well(_well("WELL:B", "Beta", extra=("RHOB",)), activate=False)
    m.add_well(_well("WELL:C", "Gamma"), activate=False)
    return m


@pytest.fixture()
def panel(qtbot, model):
    p = DataBrowserPanel(model)
    qtbot.addWidget(p)
    return p


def _roots(panel):
    return [panel.tree_model.item(r, 0) for r in range(panel.tree_model.rowCount())]


def _child(root, name):
    for r in range(root.rowCount()):
        if root.child(r, 0).text() == name:
            return root.child(r, 0), root.child(r, 1)
    raise AssertionError(name)


def test_one_root_per_well_in_order(panel):
    assert [r.text() for r in _roots(panel)] == ["Alpha", "Beta", "Gamma"]
    assert [r.data(_WELL_ROLE) for r in _roots(panel)] == ["WELL:A", "WELL:B", "WELL:C"]


def test_active_root_bold_with_tooltip(panel, model):
    a, b, _c = _roots(panel)
    assert a.font().bold() and a.toolTip() == "Active well"
    assert not b.font().bold() and b.toolTip() != "Active well"
    model.set_active_well("WELL:B")          # rebuilds through the project signal
    a, b, _c = _roots(panel)
    assert b.font().bold() and not a.font().bold()
    assert panel.tree.isExpanded(b.index())
    assert not panel.tree.isExpanded(_roots(panel)[2].index())


def test_default_expansion_only_for_active(panel):
    a, b, _c = _roots(panel)
    assert panel.tree.isExpanded(a.index())
    assert not panel.tree.isExpanded(b.index())


def test_click_child_emits_owning_well(panel, qtbot):
    b = _roots(panel)[1]
    curves, _ = _child(b, "Curves")
    with qtbot.waitSignal(panel.well_selected) as sig:
        panel.tree.clicked.emit(curves.child(0, 0).index())
    assert sig.args == ["WELL:B"]
    with qtbot.waitSignal(panel.well_selected) as sig:
        panel.tree.clicked.emit(b.index())
    assert sig.args == ["WELL:B"]


def test_every_item_carries_well_key(panel):
    for root in _roots(panel):
        seen = []
        panel._walk(root, lambda it: seen.append(it.data(_WELL_ROLE)))
        assert seen and set(seen) == {root.data(_WELL_ROLE)}


def test_root_context_menu_actions(panel, qtbot):
    b = _roots(panel)[1]
    menu = panel._build_menu(b.index())
    texts = [a.text() for a in menu.actions() if a.text()]
    assert "Set as Active Well" in texts and "Remove Well" in texts
    by_text = {a.text(): a for a in menu.actions()}
    with qtbot.waitSignal(panel.well_selected) as sig:
        by_text["Set as Active Well"].trigger()
    assert sig.args == ["WELL:B"]
    with qtbot.waitSignal(panel.remove_well_requested) as sig:
        by_text["Remove Well"].trigger()
    assert sig.args == ["WELL:B"]
    # children keep their per-kind actions and get no well actions
    curves, _ = _child(b, "Curves")
    child_menu = panel._build_menu(curves.index())
    assert "Remove Well" not in [a.text() for a in child_menu.actions()]


def test_children_reflect_each_wells_own_data(panel, model):
    a, b, _c = _roots(panel)
    assert _child(a, "Curves")[0].rowCount() == 2
    assert _child(b, "Curves")[0].rowCount() == 3
    model.project.get("WELL:C").curve_mapping = {"GR": "GR"}
    model.project.well_updated.emit("WELL:C")
    c = _roots(panel)[2]
    curves, _ = _child(c, "Curves")
    assert curves.child(1, 1).text().startswith("GR")
    assert _child(_roots(panel)[0], "LAS files")[0].child(0, 0).text() == "Alpha.las"
    assert _child(_roots(panel)[1], "Formation tops")[1].text() == "Not loaded"


def test_results_and_stale_dot_on_right_well(panel, model):
    ds = model.project.get("WELL:B")
    ds.results = ds.las_data.assign(VSH=0.3)
    ds.calculated = True
    ds.stale = True
    model.project.well_updated.emit("WELL:B")
    a, b, _c = _roots(panel)
    assert _child(b, "Results")[1].text() == "out of date"
    assert _child(b, "Results")[0].rowCount() == 1
    assert all(r.text() != "Results" for r in
               (a.child(i, 0) for i in range(a.rowCount())))
    assert b.model().item(b.row(), 1).data(Qt.ItemDataRole.DecorationRole) is not None
    assert ds.status == "stale"


def test_set_results_stale_refreshes_active_row(panel, model):
    ds = model.project.get("WELL:A")
    ds.results = ds.las_data.assign(VSH=0.3)
    panel.rebuild()
    assert _child(_roots(panel)[0], "Results")[1].text() == "1 curves"
    ds.stale = True
    panel.set_results_stale(True)
    assert _child(_roots(panel)[0], "Results")[1].text() == "out of date"


def test_empty_project_shows_placeholder(qtbot):
    p = DataBrowserPanel(AppModel())
    qtbot.addWidget(p)
    assert p.empty_label.isVisibleTo(p) and not p.tree.isVisibleTo(p)


def test_rebuilds_on_project_signals(panel, model):
    model.add_well(_well("WELL:D", "Delta"), activate=False)
    assert len(_roots(panel)) == 4
    model.project.remove_well("WELL:D")
    assert len(_roots(panel)) == 3
    model.project.clear()
    assert panel.tree_model.rowCount() == 0
    assert panel.empty_label.isVisibleTo(panel)


def test_expanded_state_kept_per_well(panel):
    b = _roots(panel)[1]
    panel.tree.setExpanded(b.index(), True)
    panel.rebuild()
    assert panel.tree.isExpanded(_roots(panel)[1].index())


# ---- WellSelector ----
def test_selector_empty_disabled(qtbot):
    m = AppModel()
    sel = WellSelector()
    qtbot.addWidget(sel)
    sel.set_project(m.project)
    assert not sel.isEnabled() and sel.currentText() == "No wells"


def test_selector_populates_and_follows_active(qtbot, model):
    sel = WellSelector()
    qtbot.addWidget(sel)
    sel.set_project(model.project)
    assert sel.isEnabled() and sel.count() == 3
    assert [sel.itemText(i) for i in range(3)] == ["Alpha", "Beta", "Gamma"]
    assert sel.itemData(1) == "WELL:B"
    assert sel.itemData(1, Qt.ItemDataRole.ToolTipRole) == "WELL:B"
    assert sel.currentData() == "WELL:A"
    with qtbot.assertNotEmitted(sel.well_selected):
        model.set_active_well("WELL:C")
    assert sel.currentData() == "WELL:C"


def test_selector_emits_only_on_user_selection(qtbot, model):
    sel = WellSelector()
    qtbot.addWidget(sel)
    sel.set_project(model.project)
    with qtbot.assertNotEmitted(sel.well_selected):
        sel.setCurrentIndex(1)               # programmatic
    with qtbot.waitSignal(sel.well_selected) as sig:
        sel.activated.emit(2)                # user pick
    assert sig.args == ["WELL:C"]
    model.project.remove_well("WELL:C")
    assert sel.count() == 2
