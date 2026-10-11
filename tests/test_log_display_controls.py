"""U7: plot controls work in both log engines, or are disabled with a reason."""
import pytest

from models.app_model import AppModel
from models.project import WellDataset
from modules.pipeline import run_pipeline
from tests.golden.cases import FULL_MAPPING, fixture_frame, make_tops
from ui.tabs.log_display_tab import LogDisplayTab


def _model(with_tops=True):
    data = fixture_frame("sample_log_data")
    ds = WellDataset("W:A", "Alpha")
    ds.las_data = data
    ds.curve_mapping = dict(FULL_MAPPING)
    if with_tops:
        ds.formation_tops = make_tops()
    results, summary = run_pipeline(data, FULL_MAPPING, {}, formation_tops=ds.formation_tops)
    ds.results, ds.summary, ds.calculated = results, summary, True
    model = AppModel()
    model.project.add_well(ds)
    return model


@pytest.fixture
def tab(qtbot):
    widget = LogDisplayTab(_model())
    qtbot.addWidget(widget)
    widget.update_display()
    widget.plot_stack.setCurrentIndex(1)       # Classic
    widget._update_plot()
    return widget


def _hcpv_labels(widget):
    ax = widget.classic_log.figure.axes[5]
    return [line.get_label() for line in ax.get_lines()
            if not line.get_label().startswith("_")]   # skip the unlabeled tops lines


def _tops_lines(widget):
    """Dashed horizontal formation-top lines on the first Classic track."""
    return [line for line in widget.classic_log.figure.axes[0].get_lines()
            if line.get_linestyle() == "--" and len(set(line.get_ydata())) == 1]


def _depths(widget):
    d = widget.model.results["DEPTH"]
    return float(d.min()), float(d.max())


# ---- Classic honours HCPV show and mode ---------------------------------------------
def test_classic_hcpv_default_is_net_pay(tab):
    assert _hcpv_labels(tab) == ["dHCPV_NET_PAY", "HCPV_CUM_NET_PAY"]


def test_classic_hcpv_mode_changes_the_track(tab):
    tab.hcpv_mode_combo.setCurrentText("Gross")
    assert _hcpv_labels(tab) == ["dHCPV", "HCPV_CUM"]
    tab.hcpv_mode_combo.setCurrentText("Net Reservoir")
    assert _hcpv_labels(tab) == ["dHCPV_NET_RES", "HCPV_CUM_NET_RES"]
    tab.hcpv_mode_combo.setCurrentText("Fraction Only")
    assert _hcpv_labels(tab) == ["HCPV_FRAC"]
    assert tuple(tab.classic_log.figure.axes[5].get_xlim()) == (0, 0.5)


def test_classic_hcpv_show_off_empties_the_track(tab):
    tab.show_hcpv_check.setChecked(False)
    assert _hcpv_labels(tab) == []
    tab.show_hcpv_check.setChecked(True)
    assert _hcpv_labels(tab) == ["dHCPV_NET_PAY", "HCPV_CUM_NET_PAY"]


# ---- the tops toggle redraws Classic at once ----------------------------------------
def test_classic_tops_toggle_redraws_immediately(tab):
    assert _tops_lines(tab)
    tab.show_tops_check.setChecked(False)
    assert not _tops_lines(tab)
    tab.show_tops_check.setChecked(True)
    assert _tops_lines(tab)


# ---- crossplot sync -----------------------------------------------------------------
def test_sync_crossplot_follows_when_checked(tab):
    lo, hi = _depths(tab)
    mid = lo + (hi - lo) / 2
    tab._sync_crossplot(lo, mid)
    assert (tab.xplot_top_spin.value(), tab.xplot_bottom_spin.value()) == (
        pytest.approx(lo, abs=0.06), pytest.approx(mid, abs=0.06))
    tab.xplot_sync_check.setChecked(False)
    tab._sync_crossplot(mid, hi)
    assert tab.xplot_top_spin.value() == pytest.approx(lo, abs=0.06)


def test_classic_zoom_updates_the_crossplots(tab):
    lo, hi = _depths(tab)
    top, base = lo + (hi - lo) * 0.25, lo + (hi - lo) * 0.5
    ax = tab.classic_log.figure.axes[0]
    ax.set_ylim(base, top)                       # an inverted depth axis, as a zoom leaves it
    assert tab.top_spin.value() == pytest.approx(top, abs=0.06)
    assert tab.bottom_spin.value() == pytest.approx(base, abs=0.06)
    assert tab.xplot_top_spin.value() == pytest.approx(top, abs=0.06)
    assert tab.xplot_bottom_spin.value() == pytest.approx(base, abs=0.06)


def test_classic_zoom_does_not_redraw_or_drift(tab):
    lo, hi = _depths(tab)
    figure = tab.classic_log.figure
    tab.classic_log.figure.axes[0].set_ylim(hi, lo + (hi - lo) * 0.5)
    assert tab.classic_log.figure is figure and len(figure.axes) == 6   # no re-plot from a zoom


def test_crossplot_title_shows_the_synced_range(tab):
    lo, hi = _depths(tab)
    tab.xplot_group.setChecked(True)
    tab._sync_crossplot(lo, lo + (hi - lo) / 2)
    title = tab.nd_crossplot.figure.axes[0].get_title()
    assert f"{lo:.0f}-{lo + (hi - lo) / 2:.0f} ft" in title


def test_interactive_zoom_and_region_update_the_crossplots(qtbot):
    pytest.importorskip("pyqtgraph")
    from ui.tabs import log_display_tab
    if not log_display_tab.HAS_PYQTGRAPH:
        pytest.skip("pyqtgraph engine unavailable")
    widget = LogDisplayTab(_model())
    qtbot.addWidget(widget)
    widget.update_display()
    widget.plot_stack.setCurrentIndex(0)
    lo, hi = _depths(widget)
    # zoom
    top, base = lo + (hi - lo) * 0.2, lo + (hi - lo) * 0.4
    widget.interactive_log.set_depth_range(top, base)
    assert widget.xplot_top_spin.value() == pytest.approx(top, abs=0.06)
    assert widget.xplot_bottom_spin.value() == pytest.approx(base, abs=0.06)
    # region selection
    top, base = lo + (hi - lo) * 0.5, lo + (hi - lo) * 0.7
    widget.interactive_log.depth_region.setRegion([top, base])
    assert widget.xplot_top_spin.value() == pytest.approx(top, abs=0.06)
    assert widget.xplot_bottom_spin.value() == pytest.approx(base, abs=0.06)
    assert widget.top_spin.value() == pytest.approx(top, abs=0.06)


def test_interactive_tops_toggle_clears_and_restores(qtbot):
    pytest.importorskip("pyqtgraph")
    from ui.tabs import log_display_tab
    if not log_display_tab.HAS_PYQTGRAPH:
        pytest.skip("pyqtgraph engine unavailable")
    widget = LogDisplayTab(_model())
    qtbot.addWidget(widget)
    widget.update_display()
    widget.plot_stack.setCurrentIndex(0)
    widget.show_tops_check.setChecked(False)
    widget.show_tops_check.setChecked(True)      # both directions run without a dead branch


# ---- a control that cannot act is disabled with a reason ----------------------------
def test_controls_without_data_are_disabled_with_a_tooltip(qtbot):
    widget = LogDisplayTab(AppModel())
    qtbot.addWidget(widget)
    for control in (widget.show_tops_check, widget.show_hcpv_check, widget.hcpv_mode_combo):
        assert not control.isEnabled()
        assert len(control.toolTip()) > 10


def test_tops_control_disabled_without_tops(qtbot):
    widget = LogDisplayTab(_model(with_tops=False))
    qtbot.addWidget(widget)
    widget.update_display()
    assert not widget.show_tops_check.isEnabled()
    assert "formation tops" in widget.show_tops_check.toolTip().lower()
    assert widget.show_hcpv_check.isEnabled()


def test_hcpv_mode_disabled_when_show_is_off(tab):
    assert tab.hcpv_mode_combo.isEnabled()
    tab.show_hcpv_check.setChecked(False)
    assert not tab.hcpv_mode_combo.isEnabled()
    assert "HCPV Show" in tab.hcpv_mode_combo.toolTip()
    tab.show_hcpv_check.setChecked(True)
    assert tab.hcpv_mode_combo.isEnabled()


def test_engine_combo_without_pyqtgraph_is_disabled_with_a_tooltip(qtbot, monkeypatch):
    from ui.tabs import log_display_tab
    monkeypatch.setattr(log_display_tab, "HAS_PYQTGRAPH", False)
    widget = LogDisplayTab(_model())
    qtbot.addWidget(widget)
    assert not widget.engine_combo.model().item(0).isEnabled()
    assert "pyqtgraph" in widget.engine_combo.toolTip()
