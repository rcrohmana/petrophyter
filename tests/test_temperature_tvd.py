"""Formation temperature on TVD (follow-ups spec section 5.1 and 5.3)."""

import numpy as np
import pandas as pd
import pytest

from models.app_model import AppModel
from models.project import WellDataset
from modules import param_scopes as ps
from modules.las_utils import normalize_curve_units
from modules.pipeline import PARAM_DEFAULTS, run_pipeline, temperature_context

TS, GRAD = 80.0, 1.5


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    def refuse(*args, **kwargs):
        raise AssertionError(f"unexpected dialog: {args[1:3]}")

    for name in ("warning", "critical", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(refuse))


def tvd_of(md):
    """A deviated well: vertical to 1500 ft, then 0.8 ft of TVD per ft of MD."""
    md = np.asarray(md, dtype=float)
    return np.where(md <= 1500.0, md, 1500.0 + 0.8 * (md - 1500.0))


def frame(n=201, step=10.0, tvd=True):
    depth = 1000.0 + step * np.arange(n)
    rng = np.random.default_rng(3)
    df = pd.DataFrame({
        "DEPTH": depth,
        "GR": rng.uniform(30, 110, n),
        "RHOB": rng.uniform(2.2, 2.6, n),
        "NPHI": rng.uniform(0.1, 0.35, n),
        "RT": rng.uniform(1.0, 30.0, n),
    })
    if tvd:
        df["TVDKB"] = tvd_of(depth)
    return df


def params(**extra):
    return {**PARAM_DEFAULTS, "temp_correction": True, "surface_temp": TS,
            "temp_gradient": GRAD, **extra}


def analytic(tvd, datum=0.0):
    return TS + GRAD * (np.asarray(tvd) - datum) / 100.0


# ---- TVD curve ------------------------------------------------------------
def test_temperature_follows_the_mapped_tvd_curve_not_md():
    df = frame()
    ctx = temperature_context(df, params(), {"TVD": "TVDKB"})
    assert ctx.source["kind"] == "curve" and "TVD curve TVDKB" in ctx.source["tvd_source"]
    np.testing.assert_allclose(ctx.temp.to_numpy(), analytic(tvd_of(df["DEPTH"])))
    # Without the mapping the same well is treated as vertical.
    md_ctx = temperature_context(df, params(), {"TVD": "None"})
    np.testing.assert_allclose(md_ctx.temp.to_numpy(), analytic(df["DEPTH"]))
    assert md_ctx.temp.iloc[-1] > ctx.temp.iloc[-1]


def test_datum_depth_shifts_the_temperature_axis():
    df = frame()
    ctx = temperature_context(df, params(temp_datum_depth=100.0), {"TVD": "TVDKB"})
    np.testing.assert_allclose(ctx.temp.to_numpy(), analytic(tvd_of(df["DEPTH"]), 100.0))
    assert ctx.source["datum_depth"] == 100.0


def test_pipeline_records_the_tvd_source_and_uses_it_for_rw():
    df = frame()
    mapping = {"GR": "GR", "RHOB": "RHOB", "NPHI": "NPHI", "DT": "None", "RT": "RT",
               "TVD": "TVDKB"}
    _, summary = run_pipeline(df, mapping, params(rw=0.05, rw_mode="manual"))
    assert "TVD curve TVDKB" in summary["param_sources"]["temperature"]["tvd_source"]
    assert summary["temperature"]["kind"] == "curve"
    tmax = float(analytic(tvd_of(df["DEPTH"].max())))
    factor_min = (75.0 + ps.ARPS_OFFSET_F) / (tmax + ps.ARPS_OFFSET_F)
    assert summary["rw_at_depth_range"][0] == pytest.approx(0.05 * factor_min)


def test_tvd_indexed_log_uses_the_depth_index():
    df = frame(tvd=False)
    ctx = temperature_context(df, params(depth_reference="TVD"), {})
    assert ctx.source["kind"] == "index" and ctx.source["tvd_source"] == "depth index (TVD)"
    np.testing.assert_allclose(ctx.temp.to_numpy(), analytic(df["DEPTH"]))


def test_a_mapped_curve_beats_the_tvd_index():
    df = frame()
    ctx = temperature_context(df, params(depth_reference="TVD"), {"TVD": "TVDKB"})
    assert ctx.source["kind"] == "curve"


def test_the_depth_index_is_never_taken_as_the_tvd_curve():
    df = frame(tvd=False)
    ctx = temperature_context(df, params(), {"TVD": "DEPTH"})
    assert ctx.source["kind"] == "md"


def test_md_fallback_notes_an_unmapped_tvd_like_curve():
    ctx = temperature_context(frame(), params(), {"TVD": "None"})
    assert ctx.source["kind"] == "md" and ctx.source["tvd_source"] == "MD (assumed vertical)"
    assert any("TVDKB" in note and "not mapped" in note for note in ctx.source["notes"])


def test_md_fallback_notes_header_deviation():
    ctx = temperature_context(frame(tvd=False), params(header_deviation=True), {})
    assert any("inclination/deviation" in note for note in ctx.source["notes"])
    plain = temperature_context(frame(tvd=False), params(), {})
    assert plain.source["notes"] == []


def test_non_monotonic_tvd_curve_is_rejected():
    df = frame()
    df.loc[100, "TVDKB"] -= 50.0
    ctx = temperature_context(df, params(), {"TVD": "TVDKB"})
    assert ctx.source["kind"] == "md"
    assert any("not non-decreasing" in note for note in ctx.source["notes"])
    np.testing.assert_allclose(ctx.temp.to_numpy(), analytic(df["DEPTH"]))


def test_tvd_deeper_than_md_is_rejected():
    df = frame()
    df["TVDKB"] = df["DEPTH"] + 5.0          # e.g. a wrong curve
    ctx = temperature_context(df, params(), {"TVD": "TVDKB"})
    assert ctx.source["kind"] == "md"
    assert any("exceeds MD" in note for note in ctx.source["notes"])
    df["TVDKB"] = df["DEPTH"] + 0.5          # within the 1 ft tolerance
    assert temperature_context(df, params(), {"TVD": "TVDKB"}).source["kind"] == "curve"


def test_gaps_inside_the_curve_are_interpolated_linearly():
    df = frame()
    df.loc[60:80, "TVDKB"] = np.nan
    ctx = temperature_context(df, params(), {"TVD": "TVDKB"})
    # tvd_of is piecewise linear and the gap lies on one segment, so the
    # interpolation reproduces it exactly.
    np.testing.assert_allclose(ctx.temp.to_numpy(), analytic(tvd_of(df["DEPTH"])))
    assert ctx.source["extrapolated_fraction"] == 0.0


def test_outside_the_curve_the_edge_slope_extrapolates_and_is_recorded():
    df = frame()
    df.loc[:19, "TVDKB"] = np.nan             # 20 samples above the curve
    df.loc[170:, "TVDKB"] = np.nan            # 31 samples below it
    ctx = temperature_context(df, params(), {"TVD": "TVDKB"})
    np.testing.assert_allclose(ctx.temp.to_numpy(), analytic(tvd_of(df["DEPTH"])))
    assert ctx.source["extrapolated_fraction"] == pytest.approx(51 / len(df))
    assert "% of samples extrapolated" in ctx.source["tvd_source"]


def test_a_metre_tvd_curve_is_converted_to_feet():
    df = pd.DataFrame({"DEPTH": [0.0, 1.0], "TVDKB": [100.0, 200.0]})
    info = {"TVDKB": {"unit": "M", "description": ""}}
    out, info, warnings = normalize_curve_units(df, info)
    assert out["TVDKB"].tolist() == pytest.approx([328.084, 656.168])
    assert info["TVDKB"]["unit"] == "FT" and warnings


# ---- header gradient on the same datum -----------------------------------------
def _model_with_header(header, datum=0.0, mapping=None):
    model = AppModel()
    ds = WellDataset(key="W", display_name="W")
    ds.las_data = frame()
    ds.identity = dict(header)
    ds.curve_mapping = {**ds.curve_mapping, **(mapping or {})}
    ds.overrides = {"temp_gradient": ps.make_entry(ps.AUTO)}
    model.add_well(ds)
    model.temp_correction = True
    model.surface_temp = TS
    model.temp_datum_depth = datum
    return model, ds


@pytest.mark.parametrize("datum", [0.0, 60.0])
def test_header_gradient_reproduces_bht_at_td_on_the_tvd_axis(datum):
    td_md = 3000.0
    header = {"bht": 140.0, "td": td_md, "td_unit": "FT", "bht_unit": "DEGF"}
    model, ds = _model_with_header(header, datum, {"TVD": "TVDKB"})
    flat = model.params_for_well(ds)
    td_tvd = float(tvd_of(td_md))
    assert flat["temp_gradient"] == pytest.approx((140.0 - TS) / (td_tvd - datum) * 100.0, abs=1e-4)
    t_td = ps.formation_temperature(td_tvd, TS, flat["temp_gradient"], datum)
    assert t_td == pytest.approx(140.0, abs=0.05)
    assert flat["param_info"]["temp_gradient"]["source"] == "auto (LAS header)"


def test_header_gradient_without_a_tvd_curve_uses_md_at_td():
    header = {"bht": 140.0, "td": 3000.0}
    model, ds = _model_with_header(header)
    flat = model.params_for_well(ds)
    assert flat["temp_gradient"] == pytest.approx((140.0 - TS) / 3000.0 * 100.0, abs=1e-4)


def test_header_gradient_ignores_a_rejected_tvd_curve():
    header = {"bht": 140.0, "td": 3000.0}
    model, ds = _model_with_header(header, mapping={"TVD": "TVDKB"})
    ds.las_data.loc[5, "TVDKB"] = 0.0         # breaks monotonicity
    flat = model.params_for_well(ds)
    assert flat["temp_gradient"] == pytest.approx((140.0 - TS) / 3000.0 * 100.0, abs=1e-4)


def test_readout_lines():
    df = frame()
    flat = {"surface_temp": TS, "temp_gradient": GRAD, "temp_datum_depth": 0.0}
    header = {"bht": 210.0, "td": 9800.0}
    lines = ps.temperature_readout(df, "TVDKB", None, header, flat)
    top, bottom = analytic(tvd_of([df["DEPTH"].min(), df["DEPTH"].max()]))
    assert lines[0] == (f"T at log top / bottom: {top:.0f} / {bottom:.0f} °F (TVD curve TVDKB)")
    assert lines[1].startswith("header: 210 °F at TD 9,800 ft (MD, TVD ")
    assert "gradient" in lines[1]
    plain = ps.temperature_readout(df, None, None, header, flat)
    assert plain[0].endswith("(MD (assumed vertical))")
    assert plain[1] == "header: 210 °F at TD 9,800 ft (MD) → gradient 1.33 °F/100 ft"
    assert ps.temperature_readout(None, None, None, {}, flat) == []


# ---- params and hash -------------------------------------------------------------
def test_new_parameters_change_the_well_hash():
    model = AppModel()
    model.las_data = frame()
    ds = model.active_well
    base = model.well_params_hash(ds)
    seen = {base}
    for change in (
        lambda: setattr(model, "temp_datum_depth", 25.0),
        lambda: setattr(model, "rsh_ref_temp", 75.0),
        lambda: setattr(model, "ws_b_auto", True),
        lambda: model.set_curve_mapping("TVD", "TVDKB"),
    ):
        change()
        h = model.well_params_hash(ds)
        assert h not in seen
        seen.add(h)


def test_well_overrides_of_the_new_parameters_reach_the_flat_params():
    model = AppModel()
    model.las_data = frame()
    model.set_edit_scope("well")
    model.set_entry("temp_datum_depth", ps.MANUAL, 30.0)
    model.set_entry("rsh_ref_temp", ps.MANUAL, 70.0)
    model.set_entry("ws_b_auto", ps.MANUAL, True)
    flat = model.params_for_well()
    assert (flat["temp_datum_depth"], flat["rsh_ref_temp"], flat["ws_b_auto"]) == (30.0, 70.0, True)
    with pytest.raises(ValueError):
        model.set_entry("temp_datum_depth", ps.MANUAL, 1.0, zone="A")     # well-only


def test_new_parameters_are_hidden_from_the_sources_table_until_set():
    df = frame()
    mapping = {"GR": "GR", "RHOB": "RHOB", "NPHI": "NPHI", "DT": "None", "RT": "RT"}
    _, summary = run_pipeline(df, mapping, dict(PARAM_DEFAULTS))
    table = summary["param_sources"]["(well)"]
    assert not {"temp_datum_depth", "rsh_ref_temp", "ws_b_auto"} & set(table)
    assert "temperature" not in summary["param_sources"] and "temperature" not in summary


def test_default_curve_mapping_and_aliases_know_tvd():
    from models.project import default_curve_mapping
    from modules.las_parser import LASParser

    assert default_curve_mapping()["TVD"] == "None"
    assert LASParser.CURVE_ALIASES["TVD"] == ["TVD", "TVDKB", "TVDRKB", "TVDRT", "TVDBRT"]


def test_session_round_trips_the_new_fields(tmp_path):
    from services.session_service import SessionService

    model = AppModel()
    model.las_data = frame()
    model.temp_datum_depth, model.rsh_ref_temp, model.ws_b_auto = 40.0, 72.0, True
    model.set_curve_mapping("TVD", "TVDKB")
    service = SessionService()
    path = str(tmp_path / "s.json")
    assert service.save_session(model, path)
    data = service.load_session(path)
    fresh = AppModel()
    assert service.apply_session_to_model(fresh, data)
    assert (fresh.temp_datum_depth, fresh.rsh_ref_temp, fresh.ws_b_auto) == (40.0, 72.0, True)


# ---- UI --------------------------------------------------------------------------
def test_temperature_section_shows_the_readout_and_the_curve_mapping_has_tvd(qtbot):
    from ui.parameters_window import ParametersWindow

    model = AppModel()
    ds = WellDataset(key="W", display_name="W")
    ds.las_data = frame()
    ds.identity = {"bht": 210.0, "td": 9800.0}
    ds.curve_mapping = {**ds.curve_mapping, "TVD": "TVDKB"}
    model.add_well(ds)
    win = ParametersWindow(model)
    qtbot.addWidget(win)
    win.refresh_scope_view()
    tmp = win.temperature_widget
    assert "TVD" in win.curve_mapping_widget.curve_combos
    assert tmp.readout.text().startswith("T at log top / bottom:")
    assert "(TVD curve TVDKB)" in tmp.readout.text()
    assert "header: 210 °F at TD 9,800 ft" in tmp.readout.text()
    assert tmp.enable_check.text() == "Correct resistivities for formation temperature"


def test_rsh_note_appears_only_for_a_manual_unreferenced_rsh_with_correction_on(qtbot):
    from ui.widgets.parameter_groups import TemperatureGroup

    group = TemperatureGroup()
    qtbot.addWidget(group)
    group.set_rsh_manual(True)
    assert group.rsh_note.isHidden()                       # correction off
    group.enable_check.setChecked(True)
    assert not group.rsh_note.isHidden() and group.rsh_note.text() == "Rw is corrected, Rsh is not"
    group.rsh_ref_spin.setValue(75.0)
    assert group.rsh_note.isHidden() and group.get_params()["rsh_ref_temp"] == 75.0
    group.rsh_ref_spin.setValue(group.rsh_ref_spin.minimum())
    assert not group.rsh_note.isHidden() and group.get_params()["rsh_ref_temp"] is None
    group.set_rsh_manual(False)                            # auto Rsh is corrected
    assert group.rsh_note.isHidden()
