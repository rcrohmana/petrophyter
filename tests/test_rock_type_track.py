"""Rock Type log track: present only with ROCK_TYPE, colours from tokens."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pytest

from themes import tokens
from themes.colors import get_rock_type_color
from ui.widgets import track_specs as ts
from ui.widgets.interactive_log import InteractiveLogPlot
from ui.widgets.plot_widget import CompositeLogPlot


def _results(with_rt=True):
    n = 40
    df = pd.DataFrame({
        "DEPTH": np.linspace(1000.0, 1020.0, n),
        "GR": np.linspace(30, 120, n),
        "PHIE": np.full(n, 0.2),
        "SW": np.full(n, 0.5),
    })
    if with_rt:
        df["ROCK_TYPE"] = [1] * 10 + [2] * 10 + [3] * 10 + [0] * 10
        df["FZI"] = np.linspace(0.5, 4.0, n)
        df["RQI"] = 0.1
        df["RT_MARGIN"] = [0.5] * 15 + [0.01] * 5 + [0.5] * 20
        df["ROCK_TYPE_SOURCE"] = ["core"] * 30 + ["x_nan"] * 10
        df.loc[20:24, "ROCK_TYPE_SOURCE"] = "log"
    return df


def test_bands_fade_on_low_margin_and_log_source():
    df = _results()
    bands = ts.rock_type_bands(df["DEPTH"], df["ROCK_TYPE"], df["RT_MARGIN"],
                               df["ROCK_TYPE_SOURCE"], 0.05)
    faded = [(b[2], b[3]) for b in bands]
    assert (2, True) in faded and (3, True) in faded    # low margin, log source
    assert (0, False) in faded                          # unassigned is never hatched
    assert bands[0][0] < df["DEPTH"].iloc[0]


def test_colours_come_from_the_token_ramp():
    assert get_rock_type_color(1, 3) == tokens.ROCK_TYPE_RAMP[0]
    assert get_rock_type_color(3, 3) == tokens.ROCK_TYPE_RAMP[-1]
    assert get_rock_type_color(0) == tokens.PLOT_COLORS["ROCK_TYPE_NONE"]
    for rt in range(1, 12):
        assert get_rock_type_color(rt) in tokens.ROCK_TYPE_RAMP


def test_interactive_track_only_with_rock_type(qtbot):
    widget = InteractiveLogPlot(n_tracks=7)
    qtbot.addWidget(widget)
    widget.plot_curves(_results(with_rt=False))
    assert len(widget.plot_widgets) == 7
    assert not widget.plot_widgets[6].isVisible()
    assert "ROCK_TYPE" not in widget.curves_data
    widget.plot_curves(_results())
    assert widget.plot_widgets[6].isVisible()
    assert "ROCK_TYPE" in widget.curves_data
    widget.plot_curves(_results(with_rt=False))
    assert not widget.plot_widgets[6].isVisible()


def test_interactive_hover_shows_rt_fzi_source(qtbot):
    widget = InteractiveLogPlot(n_tracks=7)
    qtbot.addWidget(widget)
    df = _results()
    widget.plot_curves(df)
    depth = float(df["DEPTH"].iloc[5])
    text = widget.format_readout(widget._get_values_at_depth(depth), depth)
    assert "RT: 1" in text and "FZI:" in text and "source: core" in text


def test_classic_log_track_only_with_rock_type(qtbot):
    plot = CompositeLogPlot()
    qtbot.addWidget(plot)
    plot.plot_petrophysics_summary(_results(with_rt=False))
    assert len(plot.figure.axes) == 6
    plot.plot_petrophysics_summary(_results())
    axes = plot.figure.axes
    assert len(axes) == 7
    assert axes[6].get_title() == "Rock Type"


def _naive_bands(depth, rt, faded):
    """Reference: per-sample half-step intervals, merged when (rt, faded) repeat."""
    n = len(depth)
    mid = (depth[1:] + depth[:-1]) / 2.0
    edges = np.concatenate(([depth[0] - (mid[0] - depth[0])], mid,
                            [depth[-1] + (depth[-1] - mid[-1])]))
    out = []
    for i in range(n):
        key = (int(rt[i]), bool(faded[i]))
        if out and out[-1][2:] == key:
            out[-1] = (out[-1][0], float(edges[i + 1]), *key)
        else:
            out.append((float(edges[i]), float(edges[i + 1]), *key))
    return out


def _random_results(n, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "DEPTH": 1000 + np.arange(n) * 0.5,
        "GR": rng.random(n) * 100, "PHIE": rng.random(n) * 0.3, "SW": rng.random(n),
        "ROCK_TYPE": rng.integers(0, 6, n),
        "RT_MARGIN": np.where(rng.random(n) < 0.2, 0.01, 0.5),
        "ROCK_TYPE_SOURCE": np.where(rng.random(n) < 0.1, "log", "core"),
    })


def test_bands_match_naive_reference():
    df = _random_results(500, seed=3)
    bands = ts.rock_type_bands(df["DEPTH"], df["ROCK_TYPE"], df["RT_MARGIN"],
                               df["ROCK_TYPE_SOURCE"], 0.05)
    faded = ((df["RT_MARGIN"].values < 0.05) | (df["ROCK_TYPE_SOURCE"].values == "log")) \
        & (df["ROCK_TYPE"].values > 0)
    ref = _naive_bands(df["DEPTH"].values, df["ROCK_TYPE"].values, faded)
    assert len(bands) == len(ref)
    for got, want in zip(bands, ref):
        assert got[2:] == want[2:]
        assert got[0] == pytest.approx(want[0]) and got[1] == pytest.approx(want[1])


def _band_artists(plot):
    ax = plot.figure.axes[-1]
    return ax, len(ax.collections) + len(ax.patches)


def test_classic_track_artist_count_is_bounded(qapp):
    plot = CompositeLogPlot()
    plot.plot_petrophysics_summary(_random_results(2000), rt_count=5)
    assert _band_artists(plot)[1] <= 2 * 5 + 3
    # same bound for a much larger, equally varied column
    plot.plot_petrophysics_summary(_random_results(6000, seed=1), rt_count=5)
    ax, n_artists = _band_artists(plot)
    assert n_artists <= 2 * 5 + 3
    labels = [t.get_text() for t in ax.get_legend().get_texts()]
    assert labels == [f"RT {i}" for i in range(1, 6)] or set(labels) <= {f"RT {i}" for i in range(1, 6)}


def test_classic_track_covers_all_depths(qapp):
    from matplotlib.collections import PolyCollection
    df = _random_results(300, seed=5)
    plot = CompositeLogPlot()
    plot.plot_petrophysics_summary(df, rt_count=5)
    ax = plot.figure.axes[-1]
    spans = []
    for coll in ax.collections:
        if isinstance(coll, PolyCollection):
            for path in coll.get_paths():
                ys = path.vertices[:, 1]
                spans.append((ys.min(), ys.max()))
    spans.sort()
    assert spans[0][0] == pytest.approx(1000 - 0.25)
    assert spans[-1][1] == pytest.approx(1000 + 299 * 0.5 + 0.25)
    for (_, hi), (lo, _) in zip(spans, spans[1:]):
        assert lo == pytest.approx(hi)


@pytest.mark.slow
def test_classic_track_random_labels_fast(qapp):
    import time
    plot = CompositeLogPlot()
    df = _random_results(8000)
    t = time.perf_counter()
    plot.plot_petrophysics_summary(df, rt_count=5)
    plot.canvas.draw()
    assert time.perf_counter() - t < 4.0

