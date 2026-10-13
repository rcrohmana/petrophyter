"""Uncertainty tab: table, plots, tornado, stale chip, buttons and main-window wiring.

The Monte Carlo result is faked (SimpleNamespace in the MCResult shape); the tab only reads it.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from PyQt6.QtCore import Qt

from models.app_model import AppModel
from models.project import WellDataset
from modules.param_scopes import params_hash
from modules.uncertainty import config_to_dict
from ui.main_window import MainWindow
from ui.tabs.uncertainty_tab import (
    DET_STALE_NOTE, EMPTY_TEXT, NO_TORNADO_NOTE, UncertaintyTab,
)


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    def refuse(*args, **kwargs):
        raise AssertionError(f"unexpected dialog: {args[1:3]}")

    for name in ("warning", "critical", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(refuse))


def _well(key):
    ds = WellDataset(key, key.split(":")[1])
    ds.las_data = pd.DataFrame({"DEPTH": [100.0, 100.5, 101.0], "GR": [40.0, 60.0, 80.0],
                                "RT": [10.0, 20.0, 5.0]})
    ds.curve_mapping = {"GR": "GR", "RT": "RT"}
    return ds


def _stats(base):
    return {"p90": base * 0.8, "p50": base, "p10": base * 1.2, "mean": base * 1.01,
            "std": 0.1, "min": base * 0.5, "max": base * 1.5, "n_valid": 200, "n": 200,
            "prob_zero": 0.05}


def _fake_result(model):
    rng = np.random.default_rng(1)
    scopes = ["field", "WELL:A", "WELL:B", ("WELL:A", "Z1"), ("WELL:A", "Z2")]
    metrics = ("hcpv_net_pay", "hcpv_net_res", "net_pay", "avg_phie_pay", "avg_sw_pay")
    values, det, stats = {}, {}, {}
    for si, scope in enumerate(scopes):
        for mi, metric in enumerate(metrics):
            base = 10.0 * (si + 1) + mi
            values[(scope, metric)] = rng.normal(base, 1.0, 200)
            det[(scope, metric)] = base + 0.2
            stats[(scope, metric)] = _stats(base)
    tornado = {}
    for scope in scopes:
        for metric in ("hcpv_net_pay", "net_pay"):
            tornado[(scope, metric)] = [
                {"name": n, "low_input": lo, "high_input": hi, "at_low_input": 9.0 - sw,
                 "at_high_input": 11.0 + sw, "bar_min": 9.0 - sw, "bar_max": 11.0 + sw,
                 "swing": 2.0 + 2 * sw, "base": 10.0}
                for n, lo, hi, sw in (("Rw", 0.04, 0.06, 0.5), ("m", 1.8, 2.2, 2.0),
                                      ("n", 1.8, 2.2, 1.0))]
    return SimpleNamespace(
        n=200, seed=42, sampling="lhs", elapsed_s=1.5, names=("Rw", "m", "n"),
        wells=[{"key": "WELL:A", "name": "A"}, {"key": "WELL:B", "name": "B"}],
        excluded=[{"key": "WELL:C", "name": "C", "reason": "no RT"}],
        zones={"WELL:A": ["Z1", "Z2"]}, values=values, deterministic=det, stats=stats,
        tornado=tornado,
        rank_corr={"hcpv_net_pay": {"Rw": -0.4, "m": -0.8, "n": -0.2}, "net_pay": {}},
        clipped={"Rw": 0.03, "m": 0.0}, warnings=["a warning line"],
        basis={ds.key: model.well_params_hash(ds) for ds in model.project.wells},
        config_hash=params_hash(config_to_dict(model.project.uncertainty)))


@pytest.fixture()
def model():
    m = AppModel()
    m.project.add_well(_well("WELL:A"))
    m.project.add_well(_well("WELL:B"))
    return m


@pytest.fixture()
def tab(qtbot, model):
    t = UncertaintyTab(model)
    qtbot.addWidget(t)
    t.resize(900, 1400)
    return t


def _store(model, tab):
    result = _fake_result(model)
    model.project.uncertainty_result = result
    tab.update_display()
    return result


def _cell(tab, row, col):
    return tab.table_view.model().index(row, col).data()


def test_empty_state(tab):
    assert tab.empty_label.text() == EMPTY_TEXT
    assert not tab.empty_label.isHidden()
    assert tab.content.isHidden()
    assert tab.table_view.model().rowCount() == 0


def test_table_rows_and_values(model, tab):
    result = _store(model, tab)
    assert tab.content.isHidden() is False and tab.empty_label.isHidden()
    labels = [_cell(tab, r, 0) for r in range(tab.table_view.model().rowCount())]
    assert labels == ["Field", "A", "  Z1", "  Z2", "B"] or labels == ["Field", "A", "  Z1", "  Z2", "B"]
    assert "C" not in labels
    st = result.stats[("field", "hcpv_net_pay")]
    assert float(_cell(tab, 0, 1)) == pytest.approx(st["p90"], abs=1e-3)
    assert float(_cell(tab, 0, 5)) == pytest.approx(
        result.deterministic[("field", "hcpv_net_pay")], abs=1e-3)
    assert _cell(tab, 0, 6) == "200"
    assert _cell(tab, 0, 7) == "5.0%"
    assert "Seed 42" in tab.header_label.text() and "N 200" in tab.header_label.text()
    assert "Not varied" in tab.not_varied_label.text()
    assert "P90 = low case" in tab.p90_label.text()


def test_metric_switch_changes_values(model, tab):
    _store(model, tab)
    before = _cell(tab, 0, 2)
    tab.metric_combo.setCurrentIndex(tab.metric_combo.findData("net_pay"))
    assert _cell(tab, 0, 2) != before
    assert float(_cell(tab, 0, 2)) == pytest.approx(12.0, abs=1e-3)


def test_unchanged_result_does_not_rebuild_table(model, tab):
    _store(model, tab)
    calls = []
    orig = tab._rebuild_table
    tab._rebuild_table = lambda: (calls.append(1), orig())
    tab.update_display()
    tab.refresh_stale()
    assert calls == []


def _vlines(ax):
    return sorted(round(float(l.get_xdata()[0]), 6) for l in ax.lines
                  if len(l.get_xdata()) == 2 and l.get_xdata()[0] == l.get_xdata()[1])


def test_row_selection_sets_histogram_scope(model, tab):
    result = _store(model, tab)
    tab.show()
    ax = tab.plot_hist.figure.axes[0]
    st = result.stats[("field", "hcpv_net_pay")]
    lines = _vlines(ax)
    for k in ("p90", "p50", "p10"):
        assert round(st[k], 6) in lines
    assert round(result.deterministic[("field", "hcpv_net_pay")], 6) in lines
    assert len(tab.plot_hist.figure.axes) == 2     # twin exceedance axis
    tab.table_view.selectRow(4)                     # well B
    assert tab._scope == "WELL:B"
    lines = _vlines(tab.plot_hist.figure.axes[0])
    stb = result.stats[("WELL:B", "hcpv_net_pay")]
    for k in ("p90", "p50", "p10"):
        assert round(stb[k], 6) in lines
    tab.table_view.selectRow(2)                     # zone Z1 of A
    assert tab._scope == ("WELL:A", "Z1")


def test_plots_not_drawn_while_hidden(model, tab):
    _store(model, tab)
    assert tab._plot_key is None
    tab.show()
    assert tab._plot_key is not None


def test_tornado_sorted_and_labels(model, tab):
    _store(model, tab)
    tab.show()
    ax = tab.plot_tornado.figure.axes[0]
    widths = [p.get_width() for p in ax.patches]
    assert widths == sorted(widths, reverse=True) and len(widths) == 3
    assert ax.yaxis_inverted()
    labels = [t.get_text() for t in ax.get_yticklabels()]
    assert labels[0].startswith("m (1.8 / 2.2)")
    m = tab.tornado_view.model()
    assert [m.index(r, 0).data() for r in range(3)] == ["m", "n", "Rw"]
    assert float(m.index(0, 6).data()) == pytest.approx(-0.8, abs=1e-3)
    assert any(abs(float(l.get_xdata()[0]) - 10.0) < 1e-9 for l in ax.lines)


def test_metric_without_tornado_shows_note(model, tab):
    _store(model, tab)
    tab.show()
    assert not tab.tornado_box.isHidden() and tab.tornado_note.isHidden()
    tab.metric_combo.setCurrentIndex(tab.metric_combo.findData("avg_sw_pay"))
    assert not tab.tornado_note.isHidden()
    assert tab.tornado_note.text() == NO_TORNADO_NOTE
    assert tab.tornado_box.isHidden()


def test_diagnostics_text(model, tab):
    _store(model, tab)
    text = tab.diag_label.text()
    assert "Rw 3.0%" in text and "m 0.0%" not in text
    assert "A 5.0%" in text
    assert "Excluded: C (no RT)" in text
    assert "a warning line" in text


def test_not_stale_after_matching_result(model, tab):
    _store(model, tab)
    assert tab.stale_chip.isHidden()
    assert tab.det_note.isHidden()


def test_stale_after_parameter_change(model, tab):
    _store(model, tab)
    model.rw = model.rw + 0.01
    tab.refresh_stale()
    assert not tab.stale_chip.isHidden()
    assert tab.stale_chip.text() == "Out of date"


def test_stale_after_config_change(model, tab):
    _store(model, tab)
    model.project.uncertainty.n = model.project.uncertainty.n + 100
    tab.refresh_stale()
    assert not tab.stale_chip.isHidden()


def test_stale_after_well_removed(model, tab):
    result = _store(model, tab)
    model.project._wells.pop("WELL:B")
    model.project.uncertainty_result = result      # remove_well would clear it; keep to test the check
    tab.refresh_stale()
    assert not tab.stale_chip.isHidden()


def test_stale_after_new_well_with_data(model, tab):
    _store(model, tab)
    model.project.add_well(_well("WELL:D"))
    model.project.uncertainty_result = tab._result    # add_well keeps it for a new key
    tab.refresh_stale()
    assert not tab.stale_chip.isHidden()


def test_remove_well_clears_result_and_tab(model, tab):
    _store(model, tab)
    model.project.remove_well("WELL:B")
    tab.update_display()
    assert tab.content.isHidden() and not tab.empty_label.isHidden()


def test_deterministic_note_when_well_stale(model, tab):
    _store(model, tab)
    model.project.get("WELL:A").stale = True
    tab.refresh_stale()
    assert not tab.det_note.isHidden()
    assert tab.det_note.text() == DET_STALE_NOTE


def test_set_running_toggles_buttons(tab):
    assert tab.run_button.isEnabled() and not tab.cancel_button.isEnabled()
    tab.set_running(True)
    assert not tab.run_button.isEnabled() and tab.cancel_button.isEnabled()
    tab.set_progress(3, 10)
    assert "3/10" in tab.progress_label.text()
    tab.set_running(False)
    assert tab.run_button.isEnabled() and not tab.cancel_button.isEnabled()
    assert tab.progress_label.text() == ""


def test_buttons_emit_signals(qtbot, tab):
    with qtbot.waitSignal(tab.run_requested, timeout=500):
        tab.run_button.click()
    tab.set_running(True)
    with qtbot.waitSignal(tab.cancel_requested, timeout=500):
        tab.cancel_button.click()


@pytest.fixture()
def window(qtbot):
    w = MainWindow()
    qtbot.addWidget(w, before_close_func=lambda w: w._set_busy(None))
    return w


def test_tab_order_and_no_emoji(window):
    texts = [window.tab_widget.tabText(i) for i in range(window.tab_widget.count())]
    assert texts.index("Uncertainty") == texts.index("Summary") + 1
    assert texts.index("Export") == texts.index("Uncertainty") + 1
    emoji = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️]")
    assert not emoji.search("".join(texts))
    assert window.tab_widget.widget(texts.index("Uncertainty")) is window.uncertainty_tab


def test_window_buttons_call_run_and_cancel(window, monkeypatch):
    calls = []
    monkeypatch.setattr(window, "run_uncertainty", lambda: calls.append("run"))
    monkeypatch.setattr(window, "cancel_uncertainty", lambda: calls.append("cancel"))
    window.uncertainty_tab.run_button.click()
    window.uncertainty_tab.set_running(True)
    window.uncertainty_tab.cancel_button.click()
    assert calls == ["run", "cancel"]


def test_window_runner_signals_toggle_buttons(window):
    tab = window.uncertainty_tab
    window.uncertainty_runner.started.emit(2, 100)
    assert tab.cancel_button.isEnabled() and not tab.run_button.isEnabled()
    window.uncertainty_runner.progress.emit(5, 100)
    assert "5/100" in tab.progress_label.text()
    window.uncertainty_runner.finished.emit()
    assert tab.run_button.isEnabled() and not tab.cancel_button.isEnabled()


def test_window_result_changed_updates_tab(window):
    model = window.model
    model.project.add_well(_well("WELL:A"))
    model.project.add_well(_well("WELL:B"))
    model.project.uncertainty_result = _fake_result(model)
    window.uncertainty_result_changed.emit()
    assert window.uncertainty_tab.table_view.model().rowCount() == 5
    assert window.uncertainty_tab.stale_chip.isHidden()
    window.model.project.uncertainty.n += 50
    window._recompute_stale()
    assert not window.uncertainty_tab.stale_chip.isHidden()


def test_config_edit_on_parameters_page_marks_tab_out_of_date(window):
    """An edit on Parameters → Uncertainty reaches the tab's stale check through the window."""
    window.model.project.add_well(_well("WELL:A"))
    window.model.project.add_well(_well("WELL:B"))
    window.model.project.uncertainty_result = _fake_result(window.model)
    window.uncertainty_tab.update_display()
    assert window.uncertainty_tab.stale_chip.isHidden()
    page = window.params_window.uncertainty_page
    page.n_spin.setValue(page.n_spin.value() + 50)
    assert not window.uncertainty_tab.stale_chip.isHidden()
