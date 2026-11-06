"""Export of the variable m/n and invasion results: LAS units and descriptions and the
"Variable m/n" and "Invasion tool" provenance lines (present only when the feature was used)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd

from models.project import WellDataset
from modules.las_handler import export_merged_las
from modules.lrlc import invasion
from modules.lrlc.provenance import (
    invasion_tool_text, lrlc_curve_descriptions, variable_mn_text)
from services.export_service import _las_other_lines, provenance_block, provenance_lines

invasion.register_step()

MN_BLOCK = {"clip_m": [1.0, 4.0], "clip_n": [1.0, 4.0], "zones": [
    {"zone": "Upper", "mode": "curve", "m_model": "formula", "n_model": "constant",
     "n_eval": 100, "n_clipped_m": 1, "n_clipped_n": 0}]}
INV_BLOCK = {"zones": [{"zone": "WELL", "tool": "generic_induction", "generic": True,
                        "badge": "generic, confirm with tool charts"}]}
CHAIN = [{"zone": None, "segment": "zone", "step": "invasion", "curve": "RT_INV", "from": "RT",
          "params": {}, "refs": [], "n_valid": 5, "n_invalid": 0, "fallback": 0}]


def _ds(lrlc=None):
    ds = WellDataset("W:T", "T")
    ds.summary = {"lrlc": lrlc} if lrlc is not None else {}
    return ds


def _full():
    return _ds({"chain": CHAIN, "counts": {}, "variable_mn": MN_BLOCK, "invasion": INV_BLOCK})


def test_descriptions_for_the_new_columns():
    desc = lrlc_curve_descriptions(_full())
    assert desc["M_VAR"] == "MODELLED CEMENTATION EXPONENT (variable m, zone formula)"
    assert desc["N_VAR"] == "MODELLED SATURATION EXPONENT (variable n)"
    assert desc["RT_INV"] == "MODELLED INVASION-CORRECTED RT (step profile), FROM RT"
    assert desc["RXO_INV"] == "MODELLED FLUSHED-ZONE RESISTIVITY (step profile)"
    assert desc["DI_INV"] == "MODELLED INVASION DIAMETER (step profile)"
    assert all(":" not in text for text in desc.values())


def test_rt_inv_description_names_the_chain_input():
    rec = dict(CHAIN[0], **{"from": "RT_DECON"})
    desc = lrlc_curve_descriptions(_ds({"chain": [rec], "counts": {}}))
    assert desc["RT_INV"].endswith("FROM RT_DECON")


def test_las_carries_the_curves_with_units_and_descriptions():
    n = 4
    frame = pd.DataFrame({
        "DEPTH": np.linspace(2000, 2003, n), "M_VAR": 2.0, "N_VAR": 2.0, "RT_INV": 10.0,
        "RXO_INV": 3.0, "DI_INV": 30.0})
    out = export_merged_las(frame, {"well_name": "T"},
                            curve_descriptions=lrlc_curve_descriptions(_full()))
    section = out.split("~CURVE INFORMATION")[1].split("~A")[0]
    lines = {ln.split(".")[0].strip(): ln for ln in section.splitlines() if "." in ln}
    units = {"M_VAR": "UNITLESS", "N_VAR": "UNITLESS", "RT_INV": "OHMM", "RXO_INV": "OHMM",
             "DI_INV": "IN"}
    for col, unit in units.items():
        assert lines[col].lstrip().startswith(f"{col}.{unit}")
        assert not lines[col].rstrip().endswith(f": {col}")


def test_provenance_text_helpers():
    assert variable_mn_text(_full().summary["lrlc"]) == (
        "M_VAR = f(PHIE, VSH) formula, N_VAR = constant (zones: Upper); clipped 0.5 %")
    assert invasion_tool_text(_full().summary["lrlc"]) == "generic_induction (generic, unconfirmed)"
    for empty in ({}, None, {"variable_mn": {"zones": []}}, {"invasion": None}):
        assert variable_mn_text(empty) == "" and invasion_tool_text(empty) == ""


def test_lines_appear_in_every_provenance_output():
    block = provenance_block(_full())
    assert block["Variable m/n"].startswith("M_VAR = f(PHIE, VSH) formula")
    assert block["Invasion tool"] == "generic_induction (generic, unconfirmed)"
    assert "Variable m/n: " + block["Variable m/n"] in provenance_lines(block)
    assert "Invasion tool: " + block["Invasion tool"] in provenance_lines(block)
    other = _las_other_lines(block)
    assert f"Variable m/n {block['Variable m/n']}" in other
    assert f"Invasion tool {block['Invasion tool']}" in other
    assert "RT_INV" in block["Rt corrections"]


def test_lines_absent_without_the_features():
    for ds in (_ds({"chain": [], "counts": {}}), _ds()):
        block = provenance_block(ds)
        assert "Variable m/n" not in block and "Invasion tool" not in block
        assert not any(ln.startswith(("Variable m/n", "Invasion tool"))
                       for ln in _las_other_lines(block))
    only_inv = provenance_block(_ds({"chain": CHAIN, "counts": {}, "invasion": INV_BLOCK}))
    assert "Invasion tool" in only_inv and "Variable m/n" not in only_inv
