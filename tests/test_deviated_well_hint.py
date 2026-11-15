"""A deviated well without a TVD curve says so: header entry, inclination curve, thresholds."""

import io
import os

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from models.app_model import AppModel
from modules.las_parser import LASParser
from modules.param_scopes import (
    header_deviation_hint, inclination_curve_hint, resolve_tvd, temperature_readout)
from modules.pipeline import run_pipeline
from modules.shf import BASIS_CORE, ShfFit
from services.load_service import build_well, parse_file
from tests import synth_deviated as synth


def las_text(parameters="", curves=(), depth=(1000.0, 1001.0, 1002.0)):
    cols = [("GR", "GAPI", [50.0, 60.0, 70.0])] + list(curves)
    rows = "".join(f"{d}  " + "  ".join(str(v[i]) for _, _, v in cols) + "\n"
                   for i, d in enumerate(depth))
    return ("~VERSION INFORMATION\n VERS. 2.0 : CWLS\n WRAP. NO : ONE LINE\n"
            "~WELL INFORMATION\n STRT.FT 1000.0 : S\n STOP.FT 1002.0 : S\n STEP.FT 1.0 : S\n"
            " NULL. -999.25 : N\n WELL. DEV : WELL\n"
            + (f"~PARAMETER INFORMATION\n{parameters}" if parameters else "")
            + "~CURVE INFORMATION\n DEPT.FT : DEPTH\n"
            + "".join(f" {m}.{u} : {m}\n" for m, u, _ in cols) + "~ASCII\n" + rows)


def info_of(parameters):
    parser = LASParser()
    assert parser.read_las_from_buffer(io.StringIO(las_text(parameters))), parser.last_error
    return parser.well_info


# ---- header entries ------------------------------------------------------------------------
@pytest.mark.parametrize("line, hint", [
    (" MDEV.DEG 32.0 : MAX DEVIATION\n", True),
    (" MAXDEV. 32.0 : MAX DEVIATION\n", True),
    (" HDEV.DEGR 12.0 : DEVIATION\n", True),
    (" INCL.DEGREES 20.0 : INCLINATION\n", True),
    (" DEVI. 8.0 : INCLINATION\n", True),
    (" DEV. 8.0 : INCLINATION\n", True),
    (" MDEV.RAD 0.6 : MAX DEVIATION\n", True),          # 34 degrees
    (" MDEV.RAD 0.05 : MAX DEVIATION\n", False),        # under 3 degrees
    (" MDEV.DEG 4.0 : MAX DEVIATION\n", False),         # below the 5 degree threshold
    (" MDEV.DEG 120.0 : NOT AN ANGLE\n", False),        # above 90 is ignored
    (" MHD.DEG 25.0 : MAX HOLE DEVIATION\n", True),
    (" MHD.FT 2500.0 : MEASURED HOLE DEPTH\n", False),  # MHD without a degree unit
    (" MHD. 25.0 : NO UNIT\n", False),
    (" MDEV.FT 25.0 : WRONG UNIT\n", False),
])
def test_header_entries(line, hint):
    assert header_deviation_hint(info_of(line)) is hint


def test_header_value_is_kept_in_degrees():
    assert info_of(" MDEV.RAD 0.6 : X\n")["max_deviation"] == pytest.approx(34.377, abs=1e-3)
    assert info_of(" INCL.DEG 20.0 : X\n")["inclination"] == 20.0
    assert "max_deviation" not in info_of("")


def test_old_key_presence_no_longer_triggers():
    assert header_deviation_hint({"inclination_note": "x", "devi_text": "y"}) is False


# ---- curves --------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["DEVI", "dev", "Incl", "HDEV", "DEVIATION", "inclination"])
def test_curve_names_are_case_insensitive(name):
    data = pd.DataFrame({"DEPTH": [1.0, 2.0, 3.0], name: [0.0, 10.0, 32.0]})
    assert inclination_curve_hint(data) == (name, 32.0)


def test_small_or_missing_inclination_gives_no_hint():
    flat = pd.DataFrame({"DEPTH": [1.0, 2.0], "INCL": [0.5, 4.9]})
    assert inclination_curve_hint(flat) is None
    other = pd.DataFrame({"DEPTH": [1.0, 2.0], "GR": [50.0, 120.0]})
    assert inclination_curve_hint(other) is None
    nan = pd.DataFrame({"DEPTH": [1.0, 2.0], "INCL": [np.nan, np.nan]})
    assert inclination_curve_hint(nan) is None
    odd = pd.DataFrame({"DEPTH": [1.0, 2.0], "INCL": [3.0, 250.0]})   # 250 is not an angle
    assert inclination_curve_hint(odd) is None


def test_resolve_tvd_texts():
    data = pd.DataFrame({"DEPTH": [1000.0, 1001.0, 1002.0], "DEVI": [5.0, 20.0, 32.4]})
    src = resolve_tvd(data, None, None, False, noun="heights")
    assert src.notes == ["Curve DEVI reads up to 32 degrees, so the well looks deviated, but no "
                         "TVD curve is mapped; heights assume a vertical well. Map a TVD curve "
                         "in Curve Mapping."]
    src = resolve_tvd(data, None, None, False, noun="temperatures")
    assert "temperatures assume a vertical well. Map a TVD curve" in src.notes[0]
    header = resolve_tvd(data[["DEPTH"]], None, None, 32.0, noun="heights")
    assert header.notes == ["The header has an inclination/deviation entry (maximum deviation "
                            "32 degrees) but no TVD curve is mapped; heights assume a vertical "
                            "well."]
    vertical = resolve_tvd(data[["DEPTH"]], None, None, False)
    assert vertical.notes == []


def test_temperature_readout_uses_both_triggers():
    data = pd.DataFrame({"DEPTH": [1000.0, 1100.0], "DEVI": [0.0, 30.0]})
    flat = {"surface_temp": 70.0, "temp_gradient": 1.5, "temp_datum_depth": 0.0}
    lines = temperature_readout(data, None, None, {"max_deviation": 30.0}, flat)
    assert lines and "MD (assumed vertical)" in lines[0]


# ---- synthetic wells through the real loader and pipeline -----------------------------------
@pytest.fixture(scope="module")
def wells(tmp_path_factory):
    folder = tmp_path_factory.mktemp("deviated")
    paths = synth.write_deviated_wells(folder)
    model = AppModel()
    keys = {}
    for key in ("header", "incl", "incl_tvd"):
        parsed = parse_file(paths[key])
        assert parsed.ok
        keys[key] = model.add_well(build_well([parsed], None), activate=False)
    return model, keys, paths


def shf_payload(contact=synth.FWL_TVD_FT):
    fit = ShfFit(rock_type="All", model="power", params={"c": 0.45, "d": -0.55},
                 basis=BASIS_CORE, n_samples=10, n_points=100).to_dict()
    return {"enabled": True, "use_for_pay": False, "phie_source": "PHIE", "perm_source": "auto",
            "fallback": "none", "fits": {"All": fit},
            "fluids": {"water": 1.03, "oil": 0.75, "gas": 0.25}, "fluids_confirmed": True,
            "sigma_cos_res": {"oil": 26.0, "gas": 50.0},
            "contacts": {"datum": "TVD", "kb_ft": None,
                         "default": {"fwl": contact, "fluid": "oil"}, "zones": {}}}


def run_well(model, key):
    ds = model.project.get(key)
    params = model.params_for_well(ds)
    params["shf"] = shf_payload()
    return run_pipeline(ds.las_data.copy(), dict(ds.curve_mapping), params)


def tvd_notes(summary):
    return [i for i in summary["issues"] if i["code"] == "SHF_TVD_NOTE"]


def test_profile_gives_a_few_hundred_feet_of_md_minus_tvd():
    md = synth.md_grid()
    tvd = synth.tvd_ft(md)
    assert tvd[0] == md[0] and abs(tvd[-1] - 7188.0) < 2.0
    assert 300.0 < md[-1] - tvd[-1] < 330.0
    assert synth.inclination_deg(md).max() == synth.HOLD_DEG
    assert np.all(np.diff(tvd) > 0)


def test_header_only_well_warns_about_the_header(wells):
    model, keys, _ = wells
    ds = model.project.get(keys["header"])
    assert ds.well_info["max_deviation"] == 35.0 and "DEVI" not in ds.las_data.columns
    _, summary = run_well(model, keys["header"])
    notes = tvd_notes(summary)
    assert [n["severity"] for n in notes] == ["warning"]
    assert notes[0]["text"] == synth.HEADER_DEVIATION_NOTE.format(noun="heights")
    assert summary["shf"]["tvd_source"] == "MD (assumed vertical)"


def test_curve_only_well_warns_about_the_curve(wells):
    model, keys, _ = wells
    ds = model.project.get(keys["incl"])
    assert ds.well_info.get("max_deviation") is None
    _, summary = run_well(model, keys["incl"])
    notes = tvd_notes(summary)
    assert [n["severity"] for n in notes] == ["warning"]
    assert notes[0]["text"] == synth.CURVE_DEVIATION_NOTE.format(noun="heights")


def test_well_with_a_tvd_curve_has_no_deviation_warning(wells):
    model, keys, _ = wells
    _, summary = run_well(model, keys["incl_tvd"])
    assert tvd_notes(summary) == []
    assert summary["shf"]["tvd_source"].startswith("TVD curve TVD")


def test_temperature_note_follows_the_same_trigger(wells):
    model, keys, _ = wells
    for key, expected in (("header", "The header has an inclination"), ("incl", "Curve DEVI")):
        ds = model.project.get(keys[key])
        params = model.params_for_well(ds)
        params["temp_correction"] = True
        _, summary = run_pipeline(ds.las_data.copy(), dict(ds.curve_mapping), params)
        notes = [i["text"] for i in summary["issues"] if i["code"] == "TEMPERATURE_NOTE"]
        assert len(notes) == 1 and notes[0].startswith(expected) and "temperatures" in notes[0]


def test_vertical_well_keeps_the_info_line(wells):
    model, keys, _ = wells
    ds = model.project.get(keys["header"])
    data = ds.las_data.copy()
    params = model.params_for_well(ds)
    params.pop("header_deviation", None)
    params["shf"] = shf_payload(contact=5500.0)
    _, summary = run_pipeline(data, dict(ds.curve_mapping), params)
    notes = tvd_notes(summary)
    assert [(n["severity"], n["text"]) for n in notes] == [
        ("info", "Height computed on MD (assumed vertical).")]


def test_small_inclination_gives_no_warning(wells):
    model, keys, _ = wells
    ds = model.project.get(keys["incl"])
    data = ds.las_data.copy()
    data["DEVI"] = np.minimum(data["DEVI"], 4.0)
    params = model.params_for_well(ds)
    params["shf"] = shf_payload()
    _, summary = run_pipeline(data, dict(ds.curve_mapping), params)
    assert [(n["severity"], n["text"]) for n in tvd_notes(summary)] == [
        ("info", "Height computed on MD (assumed vertical).")]


def test_heights_differ_by_md_minus_tvd(wells):
    model, keys, _ = wells
    res2, _ = run_well(model, keys["incl"])
    res3, _ = run_well(model, keys["incl_tvd"])
    i2 = (res2["DEPTH"] - synth.README_DEPTH_MD_FT).abs().idxmin()
    i3 = (res3["DEPTH"] - synth.README_DEPTH_MD_FT).abs().idxmin()
    h2, h3 = res2.loc[i2, "HAFWL"], res3.loc[i3, "HAFWL"]
    assert h2 == pytest.approx(synth.FWL_TVD_FT - synth.README_DEPTH_MD_FT, abs=0.6)
    tvd = float(np.interp(synth.README_DEPTH_MD_FT, synth.md_grid(), synth.tvd_ft(synth.md_grid())))
    assert h3 == pytest.approx(synth.FWL_TVD_FT - tvd, abs=0.6)
    assert h3 - h2 == pytest.approx(synth.README_DEPTH_MD_FT - tvd, abs=1.0)


def test_readme_names_the_exact_messages(wells):
    _, _, paths = wells
    text = open(paths["readme"], encoding="utf-8").read()
    assert synth.HEADER_DEVIATION_NOTE.format(noun="heights") in text
    assert synth.CURVE_DEVIATION_NOTE.format(noun="heights") in text
    for name in synth.FILE_NAMES:
        assert name in text and os.path.exists(os.path.join(os.path.dirname(paths["readme"]), name))
