"""LRLC export: LAS curve descriptions, unit defaults and the Rt corrections provenance."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd

from models.project import WellDataset
from modules.las_handler import _LAS_UNIT_DEFAULTS, export_merged_las
from modules.lrlc.provenance import lrlc_curve_descriptions, rt_corrections_text
from services.export_service import _las_other_lines, provenance_block


def _frame():
    n = 5
    return pd.DataFrame({
        "DEPTH": np.linspace(1000.0, 1002.0, n),
        "RT": np.full(n, 10.0),
        "RT_SW": np.full(n, 12.0),
        "LRLC_FLAG": np.array([0, 1, 1, 0, 0]),
    })


def _rec(zone, step, curve, frm, segment="zone"):
    return {"zone": zone, "segment": segment, "step": step, "curve": curve,
            "from": frm, "params": {}, "refs": [], "n_valid": 5,
            "n_invalid": 0, "fallback": 0}


def _ds(lrlc=None):
    ds = WellDataset("W:T", "T")
    ds.summary = {} if lrlc is None else {"lrlc": lrlc}
    return ds


def _curve_lines(content):
    section = content.split("~CURVE INFORMATION")[1].split("~A")[0]
    return [ln for ln in section.splitlines() if ln.strip()]


def test_default_las_is_byte_identical():
    df = _frame()
    base = export_merged_las(df, {"well_name": "T"})
    assert export_merged_las(df, {"well_name": "T"}, curve_descriptions=None) == base
    assert export_merged_las(df, {"well_name": "T"}, curve_descriptions={}) == base


def test_descriptions_applied_and_sanitised():
    out = export_merged_las(
        _frame(), {"well_name": "T"},
        curve_descriptions={"RT_SW": "MODELLED RT: read by Sw", "UNKNOWN": "x"},
    )
    lines = {ln.split(".")[0].strip(): ln for ln in _curve_lines(out)}
    assert lines["RT_SW"].endswith(": MODELLED RT_ read by Sw")
    assert lines["RT"].endswith(": RT")  # not in the mapping: column name as before
    assert lines["LRLC_FLAG"].endswith(": LRLC_FLAG")


def test_unit_defaults():
    for col in ("RT_SW", "RT_CUT", "RT_SAND", "RT_PYR", "RT_INV", "RT_DECON", "RXO_INV"):
        assert _LAS_UNIT_DEFAULTS[col] == "OHMM"
    for col in ("BVW", "VLAM", "VDISP", "PHI_SAND", "VPYR", "SW_BASE"):
        assert _LAS_UNIT_DEFAULTS[col] == "V/V"
    assert _LAS_UNIT_DEFAULTS["QV_EST"] == "MEQ/ML"
    assert _LAS_UNIT_DEFAULTS["DI_INV"] == "IN"
    for col in ("AI", "LRLC_FLAG", "LRLC_SCORE", "WATER_FREE_FLAG", "NET_PAY_BASE_FLAG",
                "TS_CLASS", "ELASTIC_FLAG", "M_VAR", "N_VAR", "VPVS"):
        assert _LAS_UNIT_DEFAULTS[col] == "UNITLESS"
    out = export_merged_las(_frame(), {"well_name": "T"})
    assert any(ln.lstrip().startswith("RT_SW.OHMM") for ln in _curve_lines(out))


def test_descriptions_empty_without_lrlc_block():
    assert lrlc_curve_descriptions(_ds()) == {}
    assert lrlc_curve_descriptions(object()) == {}
    desc = lrlc_curve_descriptions(_ds({"chain": [], "counts": {}}))
    assert desc["LRLC_FLAG"] == "FLAG LRLC SCREENING CANDIDATE"
    assert desc["RT_SW"].startswith("MODELLED RT READ BY SW MODELS")
    assert all(":" not in text for text in desc.values())


def test_rt_sw_description_names_the_chain_path():
    chain = [_rec("UPPER", "laminated", "RT_SAND", "RT"),
             _rec("UPPER", "pyrite", "RT_PYR", "RT_SAND")]
    desc = lrlc_curve_descriptions(_ds({"chain": chain, "counts": {"rt_sw_written": True}}))
    assert "RT_PYR <- RT_SAND <- RT" in desc["RT_SW"]


def test_provenance_key_only_with_lrlc_summary():
    assert "Rt corrections" not in provenance_block(_ds())
    block = provenance_block(_ds({"chain": [], "counts": {}}))
    keys = list(block)
    assert keys[-1] == "Rt corrections" and keys[-2] == "Depth interval"
    assert block["Rt corrections"] == "none (RT_SW not written)"
    assert _las_other_lines(block)[-1] == "Rt corrections none (RT_SW not written)"
    assert not any(ln.startswith("Rt corrections") for ln in _las_other_lines(provenance_block(_ds())))


def test_rt_corrections_grouping():
    chain = [
        _rec("UPPER", "laminated", "RT_SAND", "RT"),
        _rec("UPPER", "pyrite", "RT_PYR", "RT_SAND"),
        _rec("LOWER", "laminated", "RT_SAND", "RT"),
        _rec("LOWER", "pyrite", "RT_PYR", "RT_SAND"),
        _rec(None, "laminated", "RT_SAND", "RT", segment="rest"),
    ]
    text = rt_corrections_text({"chain": chain})
    assert text == ("RT_SW = RT_PYR <- RT_SAND <- RT (zones: UPPER, LOWER); "
                    "RT_SW = RT_SAND <- RT (zones: other)")
    assert rt_corrections_text({"chain": []}) == "none (RT_SW not written)"
    assert rt_corrections_text({}) == "none (RT_SW not written)"
