"""Capillary pressure reader (pure, no Qt)."""

import io

import numpy as np
import pandas as pd
import pytest

from modules.pc_handler import (
    PC_UNITS_TO_PSI, PcDataHandler, normalize_system, sigma_cos,
)

BASE = """Well,Sample,Depth (ft),Porosity,Perm (mD),Pc (psi),Sw,System
A-1,P1,5000.5,0.20,100,10,0.90,air-brine
A-1,P1,5000.5,0.20,100,50,0.50,air-brine
A-1,P1,5000.5,0.20,100,200,0.20,air-brine
A-1,P2,5010,0.12,2.5,10,0.95,air-brine
A-1,P2,5010,0.12,2.5,100,0.40,air-brine
"""


def read(text, **kw):
    handler = PcDataHandler()
    ok = handler.read_pc_from_buffer(io.StringIO(text), **kw)
    assert ok, handler.last_error
    return handler


class FakeCore:
    """The two accessors the completion step uses."""

    def __init__(self, depths, phi, perm):
        self.d, self.phi, self.perm = np.array(depths), np.array(phi), np.array(perm)

    def get_core_porosity(self):
        return self.d, self.phi

    def get_core_permeability(self):
        return self.d, self.perm


def test_columns_and_curves():
    h = read(BASE)
    assert list(h.data.columns) == ["SAMPLE", "WELL", "DEPTH", "PHI", "K", "PC_PSI", "SW",
                                    "SYSTEM", "ROCK_TYPE", "SIGMA_COS_LAB"]
    assert list(h.curves()) == ["P1", "P2"]
    p1 = h.curves()["P1"]
    assert list(p1["PC_PSI"]) == [10.0, 50.0, 200.0]            # sorted by Pc
    assert list(p1["SW"]) == [0.90, 0.50, 0.20]
    assert h.pc_unit == "psi" and h.system_in_file and not h.system_needed
    assert h.data["SIGMA_COS_LAB"].iloc[0] == pytest.approx(72.0)
    assert h.well_names() == ["A-1"]


@pytest.mark.parametrize("unit", ["psi", "kpa", "mpa", "bar", "atm"])
def test_pc_units_convert_to_psi(unit):
    text = f"Sample,Depth (ft),Porosity,Perm,Pc ({unit}),Sw,System\nS1,100,0.2,10,10,0.5,air-brine\n"
    h = read(text)
    assert h.pc_unit == unit
    assert h.data["PC_PSI"].iloc[0] == pytest.approx(10 * PC_UNITS_TO_PSI[unit])


def test_unit_missing_from_the_header_is_undetected_until_chosen():
    text = "Sample,Depth (ft),Porosity,Perm,Pc,Sw,System\nS1,100,0.2,10,10,0.5,air-brine\n"
    h = read(text)
    assert h.pc_unit is None and h.pc_unit_detected is None
    chosen = read(text, pc_unit="kPa")
    assert chosen.pc_unit == "kpa"
    assert chosen.data["PC_PSI"].iloc[0] == pytest.approx(1.450377)
    bad = PcDataHandler()
    assert not bad.read_pc_from_buffer(io.StringIO(text), pc_unit="furlong")
    assert "Unknown Pc unit" in bad.last_error


def test_hg_saturation_becomes_sw():
    text = ("Sample,Depth (ft),Porosity,Perm,Pc (psi),S_Hg (%),System\n"
            "S1,100,20,10,10,10,hg-air\nS1,100,20,10,100,70,hg-air\n")
    h = read(text)
    assert h.sw_is_hg
    assert list(h.data["SW"]) == pytest.approx([0.9, 0.3])
    assert h.data["SIGMA_COS_LAB"].iloc[0] == pytest.approx(480 * abs(np.cos(np.radians(140))))
    assert h.porosity_scale == "percent" and h.data["PHI"].iloc[0] == pytest.approx(0.2)


def test_percent_or_fraction_is_decided_per_well():
    text = ("Well,Sample,Depth (ft),Porosity,Perm,Pc (psi),Sw (%),System\n"
            "A,S1,100,20,10,10,80,air-brine\nA,S1,100,20,10,100,30,air-brine\n"
            "B,S1,200,0.15,5,10,0.9,air-brine\nB,S1,200,0.15,5,100,0.4,air-brine\n")
    h = read(text)
    assert h.porosity_scales == {"A": "percent", "B": "fraction"} and h.porosity_scale_mixed
    by_well = {w: p.data for w, p in h.split_by_well().items()}
    assert list(by_well["A"]["PHI"]) == pytest.approx([0.2, 0.2])
    assert list(by_well["B"]["PHI"]) == pytest.approx([0.15, 0.15])
    assert list(by_well["A"]["SW"]) == pytest.approx([0.8, 0.3])
    assert list(by_well["B"]["SW"]) == pytest.approx([0.9, 0.4])
    assert set(h.curves()) == {"A / S1", "B / S1"}            # same id in two wells


def test_porosity_scale_can_be_forced_and_changed():
    text = "Well,Sample,Depth (ft),Porosity,Perm,Pc (psi),Sw,System\nA,S1,1,20,5,10,0.5,air-brine\n"
    h = read(text, porosity_scale="fraction")
    assert np.isnan(h.data["PHI"].iloc[0])                       # 20 as a fraction is invalid
    assert h.set_porosity_scale("percent") == 0
    assert h.data["PHI"].iloc[0] == pytest.approx(0.2)


def test_exclusions_carry_line_numbers_and_reasons():
    text = """Well,Sample,Depth (ft),Porosity,Perm,Pc (psi),Sw,System
A,S1,100,0.2,10,10,0.9,air-brine
A,S1,100,0.2,10,abc,0.8,air-brine
A,S1,100,0.2,10,-5,0.7,air-brine
A,S1,100,0.2,10,20,1.4,air-brine
A,S1,100,0.2,10,30,,air-brine
A,S1,100,0.2,10,40,0.6,foam
,S1,100,0.2,10,50,0.5,air-brine
A,S1,100,0.2,10,60,0.4,air-brine
"""
    h = read(text)
    reasons = dict(h.excluded_rows)
    assert reasons[3].startswith("non-numeric Pc")
    assert reasons[4] == "Pc not positive"
    assert reasons[5].startswith("Sw 1.4 out of range")
    assert reasons[6] == "missing saturation"
    assert reasons[7].startswith("unknown system")
    assert reasons[8] == "no well (blank well cell)"
    assert h.blank_well_rows == [8]
    assert len(h.data) == 2 and h.excluded_row_wells[3] == "A"


def test_null_sentinels_are_excluded_and_counted():
    text = """Sample,Depth (ft),Porosity,Perm,Pc (psi),Sw,System
S1,100,-999.25,10,10,0.9,air-brine
S1,100,0.2,10,-999.25,0.8,air-brine
S1,100,0.2,10,20,0.5,air-brine
"""
    h = read(text)
    assert len(h.data) == 2
    assert any("null sentinel in Pc" == r for _, r in h.excluded_rows)
    assert any("null sentinel in porosity" in r for _, r in h.excluded_rows)
    assert h.data["PHI"].iloc[0] == pytest.approx(0.2)           # filled from the sample's other row
    assert any("null sentinel" in n for n in h.notes)


def test_samples_without_an_id_group_by_depth_phi_and_k():
    text = """Depth (ft),Porosity,Perm,Pc (psi),Sw,System
100,0.2,10,10,0.9,air-brine
100,0.2,10,50,0.5,air-brine
110,0.1,1,10,0.95,air-brine
"""
    h = read(text)
    assert list(h.curves()) == ["S1", "S2"]
    assert len(h.curves()["S1"]) == 2


def test_sample_without_phi_or_k_is_completed_from_core_within_half_a_foot():
    text = """Well,Sample,Depth (ft),Pc (psi),Sw,System
A,P1,5000.2,10,0.9,air-brine
A,P1,5000.2,100,0.4,air-brine
A,P2,5100,10,0.9,air-brine
A,P2,5100,100,0.4,air-brine
"""
    h = read(text)
    assert h.incomplete_samples() == ["P1", "P2"]
    core = FakeCore([5000.0, 5050.0], [0.21, 0.18], [120.0, 7.0])
    part = h.split_by_well()["A"]
    assert part.complete_from_core(core) == 1
    assert list(part.curves()) == ["P1"]                          # P2 is 100 ft from any core
    assert part.data["PHI"].iloc[0] == pytest.approx(0.21)
    assert part.data["K"].iloc[0] == pytest.approx(120.0)
    assert ("no porosity / permeability" in [r for _, r in part.excluded_rows])
    assert part.complete_from_core(core) == 0                     # nothing left to do
    # No core at all: the samples are excluded.
    none_left = h.split_by_well()["A"]
    none_left.complete_from_core(None)
    assert none_left.curves() == {}


def test_core_beyond_the_tolerance_does_not_complete():
    text = "Sample,Depth (ft),Pc (psi),Sw,System\nP1,5000,10,0.9,air-brine\n"
    h = read(text)
    h.complete_from_core(FakeCore([5000.6], [0.2], [10.0]))
    assert h.curves() == {}


def test_system_column_and_dialog_default():
    text = """Sample,Depth (ft),Porosity,Perm,Pc (psi),Sw,System
S1,100,0.2,10,10,0.9,
S1,100,0.2,10,50,0.5,Hg-air
"""
    needs = read(text)
    assert needs.system_needed and needs.system_in_file
    filled = read(text, system="oil-brine")
    assert not filled.system_needed
    assert list(filled.data["SYSTEM"]) == ["oil-brine", "hg-air"]       # the column wins
    assert filled.data["SIGMA_COS_LAB"].iloc[0] == pytest.approx(48 * np.cos(np.radians(30)))
    plain = "Sample,Depth (ft),Porosity,Perm,Pc (psi),Sw\nS1,100,0.2,10,10,0.9\n"
    assert read(plain).system_needed
    assert not read(plain, system="air-brine").system_needed


def test_system_names_and_sigma_overrides():
    assert normalize_system("Mercury") == "hg-air"
    assert normalize_system("MICP") == "hg-air"
    assert normalize_system("oil-water") == "oil-brine"
    assert normalize_system("Air/Brine") == "air-brine"
    assert normalize_system("foam") is None
    assert sigma_cos("air-brine", np.nan, np.nan) == pytest.approx(72.0)
    assert sigma_cos("air-brine", 70.0, 60.0) == pytest.approx(35.0)
    text = ("Sample,Depth (ft),Porosity,Perm,Pc (psi),Sw,System,Sigma,Theta\n"
            "S1,100,0.2,10,10,0.9,air-brine,70,60\n")
    assert read(text).data["SIGMA_COS_LAB"].iloc[0] == pytest.approx(35.0)


def test_tvd_depth_column_warns():
    text = "Sample,TVD (ft),Porosity,Perm,Pc (psi),Sw,System\nS1,100,0.2,10,10,0.9,air-brine\n"
    h = read(text)
    assert h.depth_is_tvd and "TVD" in h.tvd_warning


def test_depth_in_metres_is_converted_and_unknown_unit_is_flagged():
    text = "Sample,Depth (m),Porosity,Perm,Pc (psi),Sw,System\nS1,100,0.2,10,10,0.9,air-brine\n"
    h = read(text)
    assert h.depth_unit_detected and h.converted_to_feet
    assert h.data["DEPTH"].iloc[0] == pytest.approx(328.084)
    bare = read(text.replace("Depth (m)", "Depth"))
    assert not bare.depth_unit_detected and bare.depth_unit_warning


def test_semicolon_decimal_comma_file(tmp_path):
    path = tmp_path / "pc.csv"
    path.write_text("Sample;Depth (ft);Porosity;Perm;Pc (psi);Sw;System\n"
                    "S1;100,5;0,2;10,5;10,5;0,9;air-brine\nS1;100,5;0,2;10,5;50;0,5;air-brine\n",
                    encoding="utf-8")
    h = PcDataHandler()
    assert h.read_pc_file(str(path))
    assert h.data["K"].iloc[0] == pytest.approx(10.5)
    assert h.data["DEPTH"].iloc[0] == pytest.approx(100.5)


def test_xlsx_file(tmp_path):
    pytest.importorskip("openpyxl")
    path = tmp_path / "pc.xlsx"
    pd.read_csv(io.StringIO(BASE)).to_excel(path, index=False)
    h = PcDataHandler()
    assert h.read_pc_file(str(path))
    assert list(h.curves()) == ["P1", "P2"]


def test_rock_type_label_and_split_by_well_spellings():
    text = """Well,Sample,Depth (ft),Porosity,Perm,Pc (psi),Sw,System,Rock type
BKS-01,S1,100,0.2,10,10,0.9,air-brine,RT1
bks 01,S2,120,0.2,10,10,0.9,air-brine,
BKS-02,S1,100,0.2,10,10,0.9,air-brine,
"""
    h = read(text)
    parts = h.split_by_well(group=True)
    assert list(parts) == ["BKS-01", "BKS-02"]
    assert parts["BKS-01"].spellings == ["BKS-01", "bks 01"]
    assert set(parts["BKS-01"].curves()) == {"S1", "S2"}
    assert parts["BKS-01"].data["ROCK_TYPE"].iloc[0] == "RT1"


def test_missing_required_columns_report_why():
    h = PcDataHandler()
    assert not h.read_pc_from_buffer(io.StringIO("Sample,Depth\nS1,100\n"))
    assert h.last_error
    h2 = PcDataHandler()
    assert not h2.read_pc_from_buffer(io.StringIO("Porosity,Pc (psi),Sw\n0.2,10,0.5\n"))
    assert "required columns" in h2.last_error


def test_a_handler_is_reusable():
    h = PcDataHandler()
    assert h.read_pc_from_buffer(io.StringIO(BASE))
    assert not h.read_pc_from_buffer(io.StringIO("junk\n1\n"))
    assert h.data is None
    assert h.read_pc_from_buffer(io.StringIO(BASE))
    assert len(h.data) == 5
