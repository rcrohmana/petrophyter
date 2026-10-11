"""U6: shared track specs (pure lookup, no Qt)."""

import numpy as np
import pandas as pd
import pytest

from ui.widgets import track_specs as ts


def test_tracks_and_curve_order():
    assert set(ts.TRACK_SPECS) == {"gr_vsh", "resistivity", "porosity", "sw", "permeability"}
    assert ts.TRACK_SPECS["gr_vsh"].curve_names == ("GR", "VSH")
    assert ts.TRACK_SPECS["resistivity"].curve_names == ("RT", "RS")
    assert ts.TRACK_SPECS["porosity"].curve_names[:2] == ("PHIT", "PHIE")
    assert ts.TRACK_SPECS["sw"].curve_names == ("SW",)
    assert ts.TRACK_SPECS["permeability"].curve_names == ("PERM_TIMUR", "PERM_WR")


def test_scales_and_ranges():
    gr = ts.TRACK_SPECS["gr_vsh"]
    assert (gr.scale, gr.lo, gr.hi, gr.unit) == ("linear", 0.0, 150.0, "API")
    assert (ts.curve_spec("gr_vsh", "VSH").lo, ts.curve_spec("gr_vsh", "VSH").hi) == (0.0, 1.0)
    rt = ts.TRACK_SPECS["resistivity"]
    assert (rt.scale, rt.lo, rt.hi) == ("log", 0.2, 2000.0)
    por = ts.TRACK_SPECS["porosity"]
    assert (por.scale, por.lo, por.hi) == ("linear", 0.5, 0.0)
    sw = ts.TRACK_SPECS["sw"]
    assert (sw.lo, sw.hi) == (0.0, 1.0)
    perm = ts.TRACK_SPECS["permeability"]
    assert (perm.scale, perm.lo, perm.hi) == ("log", 0.01, 10000.0)


def test_pick_curve_first_present_wins():
    assert ts.pick_curve("porosity", ["PHIE", "PHIT", "NPHI"]) == "PHIT"
    assert ts.pick_curve("porosity", ["PHIE", "NPHI"]) == "PHIE"
    assert ts.pick_curve("resistivity", ["RS"]) == "RS"
    assert ts.pick_curve("resistivity", ["GR"]) is None


def test_perm_coates_is_not_looked_up():
    for spec in ts.TRACK_SPECS.values():
        assert "PERM_COATES" not in spec.curve_names
        assert "PERM" not in spec.curve_names
    assert ts.pick_curve("permeability", ["PERM_COATES", "PERM"]) is None


def test_wyllie_rose_only_run_picks_perm_wr():
    columns = ["DEPTH", "PHIE", "SW", "PERM_WR"]
    assert ts.pick_curve("permeability", columns) == "PERM_WR"
    assert ts.present_curves("permeability", columns) == ["PERM_WR"]
    assert ts.pick_curve("permeability", columns + ["PERM_TIMUR"]) == "PERM_TIMUR"


def test_axis_labels():
    assert ts.TRACK_SPECS["gr_vsh"].axis_label == "GR (API)"
    assert ts.TRACK_SPECS["resistivity"].axis_label == "RT (ohm·m, log)"
    assert ts.TRACK_SPECS["permeability"].axis_label == "K (mD, log)"


def test_log_ticks_are_real_decades():
    labels = [label for _, label in ts.axis_ticks(0.01, 10000.0, "log")]
    assert labels == ["0.01", "0.1", "1", "10", "100", "1000", "10000"]
    rt = ts.axis_ticks(0.2, 2000.0, "log")
    assert [label for _, label in rt] == ["1", "10", "100", "1000"]
    assert all(0.0 <= pos <= 1.0 for pos, _ in rt)


def test_linear_ticks_cover_reversed_porosity():
    ticks = ts.axis_ticks(0.5, 0.0, "linear")
    assert ticks[0] == (pytest.approx(0.0), "0.5")
    assert ticks[-1] == (pytest.approx(1.0), "0")


def test_normalize_log_and_linear():
    assert ts.normalize(1000.0, 0.01, 10000.0, "log") == pytest.approx(5 / 6)
    assert ts.normalize(0.0, 0.5, 0.0) == pytest.approx(1.0)
    assert np.isnan(ts.normalize(-1.0, 0.2, 2000.0, "log"))


def _frame(**cols):
    n = 5
    data = {"DEPTH": np.arange(n, dtype=float)}
    data.update({k: np.asarray(v, dtype=float) for k, v in cols.items()})
    return pd.DataFrame(data)


def test_primary_sw_model_read_from_data():
    sw = [0.2, 0.3, 0.4, 0.5, 0.6]
    df = _frame(SW=sw, SW_SIMAN=sw, SW_ARCHIE=[0.1, 0.2, 0.3, 0.4, 0.5])
    assert ts.primary_sw_model(df) == "Simandoux"
    assert ts.sw_primary_label("Simandoux") == "Sw — Simandoux (primary)"
    assert ts.sw_primary_label(None) == "Sw (primary)"
    assert ts.primary_sw_model(_frame(SW=sw)) is None


def test_primary_sw_model_hint_breaks_ties():
    sw = [0.2, 0.3, 0.4, 0.5, 0.6]
    df = _frame(SW=sw, SW_SIMAN=sw, SW_INDO=sw)
    assert ts.primary_sw_model(df, hint="Indonesian") == "Indonesian"


def test_method_column_helpers():
    cols = ["SW", "SW_INDO", "SW_ARCHIE", "SWT_X", "SWIRR", "PERM_WR", "PERM_TIMUR", "PERM"]
    assert ts.sw_method_columns(cols) == ["SW_ARCHIE", "SW_INDO"]
    assert ts.swt_columns(cols) == ["SWT_X"]
    assert ts.perm_columns(cols) == ["PERM_TIMUR", "PERM_WR"]


def test_readout_lists_every_curve_untruncated():
    values = {f"CURVE{i}": 1.5 for i in range(20)}
    units = {"CURVE0": "API"}
    text = ts.readout_text(values, units)
    assert len(text) > 80
    assert text.count("|") == 19
    assert "CURVE0: 1.500 API" in text
    assert ts.readout_text({"A": float("nan")}, {}) == ""


def test_porosity_plot_curves_prefers_derived_over_raw_inputs():
    assert ts.porosity_plot_curves(["PHIE", "NPHI", "RHOB"]) == ["PHIE"]
    assert ts.porosity_plot_curves(["NPHI", "RHOB"]) == ["NPHI", "RHOB"]
