"""Saturation-height Sw overlay and residual track, in both log engines."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pytest

from themes import tokens
from themes.colors import get_plot_color
from ui.widgets import track_specs as ts
from ui.widgets.interactive_log import InteractiveLogPlot
from ui.widgets.plot_widget import CompositeLogPlot


def _results(shf=True, rt=False, pay=False):
    n = 40
    df = pd.DataFrame({
        "DEPTH": np.linspace(1000.0, 1015.0, n),
        "GR": np.linspace(30, 120, n),
        "PHIE": np.full(n, 0.2),
        "SW": np.full(n, 0.5),
    })
    if rt:
        df["ROCK_TYPE"] = 1
    if shf:
        df["SW_SHF"] = np.linspace(0.2, 0.9, n)
        df["HAFWL"] = np.linspace(80.0, 0.0, n)
        df["SW_SHF_RESID"] = df["SW"] - df["SW_SHF"]
    if pay:
        df["SW_PAY"] = 0.3
    return df


@pytest.fixture
def w(qtbot):
    widget = InteractiveLogPlot(n_tracks=8)
    qtbot.addWidget(widget)
    return widget


def test_shf_colour_tokens_in_both_themes():
    for key in ("SW_SHF", "SW_PAY", "SW_SHF_RESID"):
        assert key in tokens.PLOT_COLORS
        assert get_plot_color(key, "dark") != get_plot_color(key, "light")


def test_interactive_without_shf_unchanged(w):
    w.plot_curves(_results(shf=False))
    assert len(w.plot_widgets) == 8
    assert not w.plot_widgets[InteractiveLogPlot.RESID_TRACK].isVisible()
    assert not {"SW_SHF", "HAFWL", "SW_SHF_RESID"} & set(w.curves_data)


def test_interactive_with_shf(w):
    w.show()
    df = _results(pay=True)
    w.plot_curves(df)
    assert w.plot_widgets[InteractiveLogPlot.RESID_TRACK].isVisible()
    assert not w.plot_widgets[InteractiveLogPlot.RT_TRACK].isVisible()
    assert w.curve_labels["SW_SHF"] == "Sw SHF"
    assert "SW_SHF" in w.curve_items and "SW_PAY" in w.curve_items
    assert "SW_SHF_RESID" in w.curve_items
    depth = float(df["DEPTH"].iloc[5])
    text = w.format_readout(w._get_values_at_depth(depth), depth)
    assert "SW_SHF:" in text and "HAFWL:" in text and "ft" in text
    w.plot_curves(_results(shf=False))
    assert not w.plot_widgets[InteractiveLogPlot.RESID_TRACK].isVisible()


def test_classic_without_shf_unchanged(qtbot):
    plot = CompositeLogPlot()
    qtbot.addWidget(plot)
    plot.plot_petrophysics_summary(_results(shf=False))
    assert len(plot.figure.axes) == 6
    plot.plot_petrophysics_summary(_results(shf=False, rt=True))
    assert len(plot.figure.axes) == 7


def test_classic_with_shf_axis_index_follows_rock_type(qtbot):
    plot = CompositeLogPlot()
    qtbot.addWidget(plot)
    plot.plot_petrophysics_summary(_results(pay=True))
    axes = plot.figure.axes
    assert len(axes) == 7
    assert axes[6].get_title() == ts.SHF_RESID_TITLE
    labels = [t.get_text() for t in axes[2].get_legend().get_texts()]
    assert "Sw SHF" in labels and "Sw SHF (pay)" in labels
    plot.plot_petrophysics_summary(_results(rt=True))
    axes = plot.figure.axes
    assert len(axes) == 8
    assert axes[6].get_title() == "Rock Type"
    assert axes[7].get_title() == ts.SHF_RESID_TITLE
