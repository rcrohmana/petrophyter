"""Tests for curve unit normalisation (neutron, density, sonic, resistivity)."""

import io

import numpy as np
import pandas as pd
import pytest

from modules.las_parser import LASParser
from modules.las_utils import normalize_curve_units
from tests.test_well_identity import make_las


def _norm(mnemonic, unit, values):
    df = pd.DataFrame({"DEPTH": np.arange(len(values), dtype=float), mnemonic: values})
    return normalize_curve_units(df, {mnemonic: {"unit": unit, "description": "d"}})


@pytest.mark.parametrize("unit", ["%", "PU", "P.U.", "PERCENT", "pu (%)"])
def test_neutron_percent_units_converted(unit):
    df, info, warns = _norm("NPHI", unit, [20.0, 30.0, 40.0])
    assert df["NPHI"].tolist() == pytest.approx([0.2, 0.3, 0.4])
    assert info["NPHI"]["unit"] == "V/V"
    assert info["NPHI"]["description"] == "d"
    assert not any("inferred" in w for w in warns)


def test_neutron_fraction_untouched():
    df, info, warns = _norm("NPHI", "V/V", [0.2, 0.3, 0.4])
    assert df["NPHI"].tolist() == [0.2, 0.3, 0.4]
    assert warns == []


def test_neutron_unknown_unit_inferred_from_range():
    df, info, warns = _norm("TNPH", "", [20.0, 30.0, 40.0])
    assert df["TNPH"].tolist() == pytest.approx([0.2, 0.3, 0.4])
    assert info["TNPH"]["unit"] == "V/V"
    assert any("inferred from the value range" in w for w in warns)


def test_neutron_unknown_unit_fraction_range_untouched():
    df, _, warns = _norm("NPHI", "", [0.2, 0.3])
    assert df["NPHI"].tolist() == [0.2, 0.3] and warns == []


@pytest.mark.parametrize("unit", ["KG/M3", "kg/m3", "Kg/M³"])
def test_density_kgm3_converted(unit):
    df, info, _ = _norm("RHOB", unit, [2300.0, 2500.0])
    assert df["RHOB"].tolist() == pytest.approx([2.3, 2.5])
    assert info["RHOB"]["unit"] == "G/C3"


def test_density_unknown_unit_inferred():
    df, info, warns = _norm("RHOZ", "", [2300.0, 2500.0])
    assert df["RHOZ"].tolist() == pytest.approx([2.3, 2.5])
    assert any("inferred from the value range" in w for w in warns)


def test_density_gcc_untouched():
    df, _, warns = _norm("RHOB", "G/CC", [2.3, 2.5])
    assert df["RHOB"].tolist() == [2.3, 2.5] and warns == []


@pytest.mark.parametrize("unit", ["US/M", "USEC/M", "µS/M", "μs/m"])
def test_sonic_us_per_m_converted(unit):
    df, info, _ = _norm("DT", unit, [300.0, 400.0])
    assert df["DT"].tolist() == pytest.approx([91.44, 121.92])
    assert info["DT"]["unit"] == "US/F"


def test_sonic_unknown_unit_inferred():
    df, _, warns = _norm("DTC", "", [350.0, 400.0])
    assert df["DTC"].tolist() == pytest.approx([106.68, 121.92])
    assert any("inferred from the value range" in w for w in warns)


def test_sonic_us_per_ft_untouched():
    df, _, warns = _norm("DT", "US/F", [80.0, 90.0])
    assert df["DT"].tolist() == [80.0, 90.0] and warns == []


@pytest.mark.parametrize("unit", ["MMHO/M", "MS/M"])
def test_conductivity_flagged_not_converted(unit):
    df, info, warns = _norm("RT", unit, [10.0, 20.0])
    assert df["RT"].tolist() == [10.0, 20.0]
    assert info["RT"]["unit"] == unit
    assert any("conductivity" in w for w in warns)


def test_no_double_conversion():
    df = pd.DataFrame({"DEPTH": [0.0, 1.0], "NPHI": [20.0, 30.0]})
    info = {"NPHI": {"unit": "%"}}
    df, info, _ = normalize_curve_units(df, info)
    df, info, warns = normalize_curve_units(df, info)
    assert df["NPHI"].tolist() == pytest.approx([0.2, 0.3])
    assert warns == []


def test_unrelated_curves_untouched():
    df, info, warns = _norm("GR", "%", [20.0, 30.0])
    assert df["GR"].tolist() == [20.0, 30.0] and warns == []


def test_parser_applies_conversion_and_exposes_warnings():
    text = make_las(
        strt_unit="F",
        curves=(
            ("NPHI", "%", [20.0, 30.0, 40.0]),
            ("RHOB", "KG/M3", [2300.0, 2400.0, 2500.0]),
            ("DT", "US/M", [300.0, 330.0, 360.0]),
        ),
    )
    parser = LASParser()
    assert parser.read_las_from_buffer(io.StringIO(text))
    assert parser.data["NPHI"].tolist() == pytest.approx([0.2, 0.3, 0.4])
    assert parser.data["RHOB"].tolist() == pytest.approx([2.3, 2.4, 2.5])
    assert parser.curve_info["NPHI"]["unit"] == "V/V"
    assert parser.curve_info["DT"]["unit"] == "US/F"
    assert len(parser.unit_warnings) == 3


def test_parser_unit_warnings_default_empty():
    assert LASParser().unit_warnings == []
