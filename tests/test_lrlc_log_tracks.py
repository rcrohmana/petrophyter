"""LRLC columns in both log engines: resistivity track, dashed RT_CUT, shaded flags."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pytest
from PyQt6.QtWidgets import QMessageBox

from themes import tokens
from themes.colors import get_plot_color
from ui.widgets import track_specs as ts
from ui.widgets.interactive_log import InteractiveLogPlot
from ui.widgets.plot_widget import CompositeLogPlot


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("modal dialog opened in a test")

    for name in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(boom))


def _results(lrlc=True, rock=False, flags=True, rt_name="RT"):
    n = 40
    df = pd.DataFrame({
        "DEPTH": np.linspace(1000.0, 1015.0, n),
        "GR": np.linspace(30, 120, n),
        "PHIE": np.full(n, 0.2),
        "SW": np.full(n, 0.5),
        rt_name: np.linspace(1.0, 50.0, n),
    })
    if rock:
        df["ROCK_TYPE"] = 1
    if lrlc:
        df["RT_SW"] = df[rt_name] * 1.2
        df["RT_CUT"] = 8.0
        if flags:
            df["LRLC_FLAG"] = (np.arange(n) % 5 == 0).astype(int)
            df["WATER_FREE_FLAG"] = (np.arange(n) % 7 == 0).astype(int)
    return df


def test_colour_tokens_in_both_themes():
    for key in ("RT_SW", "RT_CUT", "BVW", "LRLC_FLAG", "WATER_FREE_FLAG"):
        assert key in tokens.PLOT_COLORS
        assert get_plot_color(key, "dark") != get_plot_color(key, "light")


def test_track_spec_and_alias():
    names = [c.name for c in ts.TRACK_SPECS["resistivity"].curves]
    assert "RT_SW" in names and "RT_CUT" in names
    assert ts.SHF_NON_METHOD_COLUMNS is ts.NON_METHOD_SW_COLUMNS
    assert ts.sw_method_columns(["SW_ARCHIE", "RT_SW", "RT_CUT"]) == ["SW_ARCHIE"]


def test_classic_axes_counts(qtbot):
    plot = CompositeLogPlot()
    qtbot.addWidget(plot)
    plot.plot_petrophysics_summary(_results(lrlc=False))
    assert len(plot.figure.axes) == 6
    plot.plot_petrophysics_summary(_results(lrlc=False, rock=True))
    assert len(plot.figure.axes) == 7
    plot.plot_petrophysics_summary(_results())
    assert len(plot.figure.axes) == 7
    plot.plot_petrophysics_summary(_results(rock=True))
    assert len(plot.figure.axes) == 8


def test_classic_resistivity_track_and_shaded_flags(qtbot):
    plot = CompositeLogPlot()
    qtbot.addWidget(plot)
    plot.plot_petrophysics_summary(_results(rock=True))
    axes = plot.figure.axes
    assert axes[3].get_title() == "Resistivity"
    assert axes[3].get_xscale() == "log"
    styles = {ln.get_label(): ln.get_linestyle() for ln in axes[3].get_lines()}
    assert styles["RT_SW"] == "-" and styles["RT_CUT"] == "--"
    assert axes[4].get_title() == "Permeability"
    assert axes[5].get_title() == "Pay Flags"
    legend = [t.get_text() for t in axes[5].get_legend().get_texts()]
    assert "LRLC" in legend and "Water-free" in legend
    assert axes[7].get_title() == "Rock Type"


def test_classic_uses_the_mapped_rt_mnemonic(qtbot):
    plot = CompositeLogPlot()
    qtbot.addWidget(plot)
    df = _results(rt_name="ILD")
    plot.plot_petrophysics_summary(df)  # default "RT" is absent: no track
    assert len(plot.figure.axes) == 6
    plot.plot_petrophysics_summary(df, rt_curve="ILD")
    assert len(plot.figure.axes) == 7


@pytest.fixture
def w(qtbot):
    widget = InteractiveLogPlot(n_tracks=8)
    qtbot.addWidget(widget)
    return widget


def test_interactive_lists_lrlc_curves_only_when_present(w):
    absent = [c[0] for c in w._default_curve_config(_results(lrlc=False).columns.tolist())[3]]
    assert "RT_SW" not in absent and "RT_CUT" not in absent
    config = w._default_curve_config(_results().columns.tolist())
    entries = {c[0]: c for c in config[3]}
    assert "RT_SW" in entries and entries["RT_CUT"][4]["dashed"] is True
    assert not entries["RT_SW"][4].get("dashed")
    flags = {c[0]: c for c in config[4]}
    assert flags["LRLC_FLAG"][4] == {"label": "LRLC", "shade": True}
    assert flags["WATER_FREE_FLAG"][4]["shade"] is True


def test_interactive_flag_columns_absent_without_lrlc(w):
    config = w._default_curve_config(_results(lrlc=False).columns.tolist())
    assert [c[0] for c in config[4]] == []


def test_interactive_draws_shaded_flags_and_readout(w):
    df = _results()
    w.plot_curves(df)
    assert "LRLC_FLAG" in w.curve_items and "WATER_FREE_FLAG" in w.curve_items
    assert "RT_CUT" in w._dashed and "RT_SW" in w.curve_items
    depth = float(df["DEPTH"].iloc[5])
    text = w.format_readout(w._get_values_at_depth(depth), depth)
    assert "RT_SW" in text and "LRLC_FLAG" in text
