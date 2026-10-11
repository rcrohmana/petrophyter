"""U6: Interactive engine axes, legends and readout (items and ticks, never pixels)."""

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pyqtgraph")

from ui.widgets.interactive_log import InteractiveLogPlot, RealValueAxis  # noqa: E402


def _results(**extra):
    n = 21
    sw = np.linspace(0.2, 0.9, n)
    data = {
        "DEPTH": np.linspace(1000.0, 1010.0, n),
        "GR": np.linspace(20.0, 120.0, n),
        "VSH": np.linspace(0.0, 1.0, n),
        "PHIE": np.full(n, 0.2),
        "SW": sw,
        "SW_SIMAN": sw,
        "SW_ARCHIE": sw * 0.9,
        "RT": np.linspace(1.0, 500.0, n),
        "PERM_WR": np.linspace(0.1, 900.0, n),
    }
    data.update(extra)
    return pd.DataFrame(data)


@pytest.fixture
def plot(qtbot):
    widget = InteractiveLogPlot(n_tracks=6)
    qtbot.addWidget(widget)
    return widget


def _legend_labels(track):
    return [label.text for _, label in track.legend.items]


def _tick_labels(axis):
    values = [pos for pos, _ in axis.real_ticks()]
    return axis.tickStrings(values, 1.0, 1.0)


def test_tracks_use_real_value_axes(plot):
    for track in plot.plot_widgets:
        assert isinstance(track.getAxis("bottom"), RealValueAxis)
        assert isinstance(track.getAxis("top"), RealValueAxis)


def test_gr_vsh_axes_labels_and_ticks(plot):
    plot.plot_curves(_results())
    track = plot.plot_widgets[0]
    bottom, top = track.getAxis("bottom"), track.getAxis("top")

    assert bottom.labelText == "GR (API)"
    assert _tick_labels(bottom) == ["0", "30", "60", "90", "120", "150"]
    assert track.getAxis("top").isVisible()
    assert top.labelText == "VSH (v/v)"
    assert _legend_labels(track) == ["GR (API)", "VSH (v/v)"]


def test_resistivity_log_ticks_and_permeability_top_axis(plot):
    plot.plot_curves(_results())
    track = plot.plot_widgets[3]
    bottom, top = track.getAxis("bottom"), track.getAxis("top")

    assert bottom.labelText == "RT (ohm·m, log)"
    assert _tick_labels(bottom) == ["1", "10", "100", "1000"]
    assert top.labelText == "K (mD, log)"
    assert _tick_labels(top) == ["0.01", "0.1", "1", "10", "100", "1000", "10000"]
    # Drawn on one normalised 0-1 range
    assert track.getViewBox().viewRange()[0][0] == pytest.approx(-0.02, abs=0.01)


def test_tick_values_follow_axis_range(plot):
    plot.plot_curves(_results())
    bottom = plot.plot_widgets[3].getAxis("bottom")
    (_, shown), = bottom.tickValues(0.0, 1.0, 200)
    assert len(shown) == 4
    (_, none_shown), = bottom.tickValues(0.0, 0.1, 200)
    assert none_shown == []


def test_porosity_range_is_reversed_half_to_zero(plot):
    plot.plot_curves(_results())
    axis = plot.plot_widgets[1].getAxis("bottom")
    assert axis.labelText == "PHI (v/v)"
    labels = _tick_labels(axis)
    assert labels[0] == "0.5" and labels[-1] == "0"


def test_sw_track_primary_label_and_dashed_secondary(plot):
    plot.plot_curves(_results())
    track = plot.plot_widgets[2]

    assert _legend_labels(track) == ["Sw — Simandoux (primary)", "Sw — Archie"]
    # SW_SIMAN equals SW, so it is not drawn a second time
    assert "SW_SIMAN" not in plot.curve_items
    assert plot.curve_items["SW"].opts["pen"].style().name == "SolidLine"
    assert plot.curve_items["SW_ARCHIE"].opts["pen"].style().name == "DashLine"


def test_wyllie_rose_only_run_shows_perm_wr(plot):
    plot.plot_curves(_results())
    assert "PERM_WR" in plot.curve_items
    assert "PERM_COATES" not in plot.curve_items
    assert "PERM_WR (mD)" in _legend_labels(plot.plot_widgets[3])


def test_axes_reset_when_data_is_cleared(plot):
    plot.plot_curves(_results())
    plot.plot_curves(pd.DataFrame({"DEPTH": [1.0, 2.0], "GR": [10.0, 20.0]}))
    track3 = plot.plot_widgets[3]
    assert track3.getAxis("bottom").real_ticks() == []
    assert not track3.getAxis("top").isVisible()
    assert _legend_labels(track3) == []


def test_readout_lists_all_curves_with_units_and_wraps(plot):
    plot.plot_curves(_results())
    text = plot.format_readout(plot._get_values_at_depth(1005.0))

    assert "GR: 70.000 API" in text
    assert "PERM_WR: " in text and text.rstrip().endswith("mD")
    assert len(text) > 80  # not truncated
    assert plot.value_label.wordWrap()
