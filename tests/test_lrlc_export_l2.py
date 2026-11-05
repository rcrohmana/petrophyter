"""Export of the laminated-sand, pyrite and Qv results: LAS units and descriptions, the
"LRLC inputs" provenance line and the conditional zone-sheet columns."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from models.project import WellDataset
from modules.las_handler import export_merged_las
from modules.lrlc.provenance import lrlc_curve_descriptions, lrlc_inputs_text
from modules.pipeline import run_pipeline
from services.export_service import (
    ZONE_COLUMNS, _las_other_lines, provenance_block, zones_frame)
from tests.golden.cases import build_case

NEW_COLUMNS = ("VLAM", "VDISP", "PHI_SAND", "TS_CLASS", "RT_SAND", "RT_PYR", "VPYR", "QV_EST",
               "SW_BASE", "NET_PAY_BASE_FLAG")


def _ds(summary=None):
    ds = WellDataset("W:T", "T")
    ds.summary = summary or {}
    return ds


def _ran(case):
    data, mapping, params, tops = build_case(case)
    results, summary = run_pipeline(data, mapping, params, formation_tops=tops)
    ds = WellDataset("W:" + case, case)
    ds.las_data, ds.results, ds.summary, ds.calculated = data, results, summary, True
    return ds


@pytest.fixture(scope="module")
def laminated():
    return _ran("lrlc_laminated")


@pytest.fixture(scope="module")
def pyrite():
    return _ran("lrlc_pyrite")


def _rec(step, curve, frm, zone="UPPER"):
    return {"zone": zone, "segment": "zone", "step": step, "curve": curve, "from": frm,
            "params": {}, "refs": [], "n_valid": 5, "n_invalid": 0, "fallback": 0}


def test_descriptions_for_the_new_columns():
    block = {"chain": [_rec("laminated", "RT_SAND", "RT"), _rec("pyrite", "RT_PYR", "RT_SAND")],
             "params": {"default": {"pyr_method": "rhob_pef"}, "zones": {}}}
    desc = lrlc_curve_descriptions(_ds({"lrlc": block}))
    assert desc["VLAM"] == "MODELLED LAMINAR SHALE VOLUME (THOMAS-STIEBER)"
    for col in ("VDISP", "PHI_SAND", "TS_CLASS"):
        assert "THOMAS-STIEBER" in desc[col]
    assert desc["RT_SAND"] == "MODELLED LAMINATED-SAND RT (HAGIWARA), FROM RT"
    assert desc["RT_PYR"] == "MODELLED PYRITE-CORRECTED RT, FROM RT_SAND"
    assert desc["VPYR"] == "MODELLED PYRITE VOLUME FROM RHOB/PEF"
    assert desc["QV_EST"] == "ESTIMATED QV FROM VSH AND CEC"
    assert desc["SW_BASE"] == "SW FROM MEASURED RT, NO LRLC CORRECTION"
    assert desc["NET_PAY_BASE_FLAG"] == "NET PAY FLAG FROM SW_BASE"
    assert all(":" not in text for text in desc.values())


def test_vpyr_description_for_a_user_set_volume():
    block = {"chain": [], "params": {"default": {"pyr_method": "manual"}, "zones": {}}}
    assert lrlc_curve_descriptions(_ds({"lrlc": block}))["VPYR"] == "USER-SET PYRITE VOLUME"


def test_inputs_line_text():
    block = {
        "chain": [_rec("laminated", "RT_SAND", "RT")],
        "ts": {"zones": [{"zone": "UPPER", "phi_max": 0.35, "phi_sh": 0.10}]},
        "params": {"default": {"qv_source": "estimate", "cec_shale": 25.0}, "zones": {}},
        "guard": {"enabled": True, "zones": []},
    }
    assert lrlc_inputs_text(block) == (
        "Thomas-Stieber UPPER phi_max 0.35 phi_sh 0.1; Qv estimate cec_shale 25; "
        "Sw basis sand; guard on")
    assert lrlc_inputs_text({"chain": [], "counts": {}}) == ""
    assert lrlc_inputs_text({}) == ""
    assert lrlc_inputs_text(None) == ""


def test_inputs_line_in_every_provenance_output(laminated):
    block = provenance_block(laminated)
    text = block["LRLC inputs"]
    assert "Thomas-Stieber" in text and "phi_max 0.3" in text and "guard on" in text
    assert list(block)[-2:] == ["Rt corrections", "LRLC inputs"]
    assert _las_other_lines(block)[-1] == f"LRLC inputs {text}"


def test_no_inputs_line_without_a_feature():
    block = provenance_block(_ds({"lrlc": {"chain": [], "counts": {}}}))
    assert "LRLC inputs" not in block
    assert not any(ln.startswith("LRLC inputs") for ln in _las_other_lines(block))
    assert "LRLC inputs" not in provenance_block(_ds())


def test_las_carries_the_new_curves_with_units_and_descriptions(laminated, pyrite):
    for ds, expected in ((laminated, ("VLAM", "VDISP", "PHI_SAND", "TS_CLASS", "RT_SAND",
                                      "SW_BASE", "NET_PAY_BASE_FLAG")),
                         (pyrite, ("VPYR", "RT_PYR", "SW_BASE"))):
        assert set(expected) <= set(ds.results.columns)
        out = export_merged_las(ds.results, {"well_name": "T"},
                                curve_descriptions=lrlc_curve_descriptions(ds))
        section = out.split("~CURVE INFORMATION")[1].split("~A")[0]
        lines = {ln.split(".")[0].strip(): ln for ln in section.splitlines() if "." in ln}
        units = {"VLAM": "V/V", "VDISP": "V/V", "PHI_SAND": "V/V", "VPYR": "V/V",
                 "SW_BASE": "V/V", "RT_SAND": "OHMM", "RT_PYR": "OHMM"}
        for col in expected:
            assert col in lines
            if col in units:
                assert lines[col].lstrip().startswith(f"{col}.{units[col]}")
            assert not lines[col].rstrip().endswith(f": {col}")      # a description, not the name


def test_zone_columns_unchanged_without_lrlc():
    frame = zones_frame([])
    assert list(frame.columns) == ZONE_COLUMNS


def test_zone_sheet_gains_baseline_and_diagnosis_columns(laminated):
    frame = zones_frame([laminated])
    assert list(frame.columns[:len(ZONE_COLUMNS)]) == ZONE_COLUMNS
    extra = list(frame.columns[len(ZONE_COLUMNS):])
    assert extra == ["Net pay (before)", "Avg Sw (before)", "HCPV (before)",
                     "LRLC probable cause", "LRLC level"]
    upper = frame[frame["Zone"] == "UPPER"].iloc[0]
    assert upper["Net pay (before)"] <= upper["Net"]
    assert np.isfinite(upper["HCPV (before)"]) and np.isfinite(upper["Avg Sw (before)"])
    assert isinstance(upper["LRLC probable cause"], str)


def test_zone_sheet_without_a_diagnosis_keeps_the_baseline_columns(pyrite):
    ds = _ds()
    ds.results, ds.calculated = pyrite.results, True
    ds.summary = {"zones": [{"zone": "Z", "net_pay": 1.0, "net_pay_base": 0.5,
                             "avg_sw_pay_base": 0.4, "hcpv_net_pay_base": 0.1}]}
    frame = zones_frame([ds])
    assert "Net pay (before)" in frame.columns and "LRLC level" not in frame.columns
    assert frame.loc[0, "Net pay (before)"] == pytest.approx(0.5)


def test_laminated_results_columns_are_all_present(laminated):
    assert {"VLAM", "VDISP", "PHI_SAND", "TS_CLASS", "RT_SAND", "SW_BASE",
            "NET_PAY_BASE_FLAG"} <= set(laminated.results.columns)
