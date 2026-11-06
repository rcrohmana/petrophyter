"""Mud values of the LAS header, the formation-temperature derive and the vertical-step mismatch note."""

import io

import numpy as np
import pytest

from modules.lrlc import chain, invasion
from modules.lrlc.chain import StepResult, StepSpec, apply_rt_chain
from modules.las_parser import LASParser, mud_header_proposal
from modules.param_scopes import formation_temperature
from tests.test_well_identity import make_las, parse


@pytest.fixture(autouse=True)
def _registered():
    invasion.register_step()


def info_of(params):
    return parse(make_las(params=params)).well_info


# ---------------------------------------------------------------------------
# Header parsing
# ---------------------------------------------------------------------------
def test_header_mud_values_are_captured_with_units():
    info = info_of(
        " RMF .OHMM   0.35 : MUD FILTRATE RESISTIVITY\n"
        " MFST.DEGF   68 : MUD FILTRATE SAMPLE TEMPERATURE\n"
        " RM  .OHMM   0.50 : MUD RESISTIVITY\n"
        " MST .DEGF   70 : MUD SAMPLE TEMPERATURE\n")
    assert info["rmf"] == 0.35 and info["rmf_unit"] == "OHMM"
    assert info["rmf_temp"] == 68.0 and info["rmf_temp_unit"] == "DEGF"
    assert info["mud_rm"] == 0.5 and info["mud_rm_temp"] == 70.0
    prop = mud_header_proposal(info)
    assert prop["rmf"] == pytest.approx(0.35) and prop["rmf_temp"] == pytest.approx(68.0)
    assert prop["mud_rm"] == pytest.approx(0.5) and prop["mud_rm_temp"] == pytest.approx(70.0)
    assert prop["assumed"] == [] and prop["skipped"] == {}


@pytest.mark.parametrize("mnemonic", ["MFT", "RMFT", "RMF_TEMP"])
def test_filtrate_temperature_mnemonics(mnemonic):
    info = info_of(f" RMF .OHMM   0.35 : RMF\n {mnemonic}.DEGF   75 : TEMP\n")
    assert info["rmf_temp"] == 75.0


def test_celsius_temperature_is_converted_to_fahrenheit():
    info = info_of(" RMF .OHM.M   0.4 : RMF\n MFST.DEGC   20 : TEMP\n BHT .DEGC   90 : BHT\n")
    prop = mud_header_proposal(info)
    assert prop["rmf"] == pytest.approx(0.4)
    assert prop["rmf_temp"] == pytest.approx(68.0)
    assert prop["bht"] == pytest.approx(194.0)


def test_missing_values_give_an_empty_proposal():
    info = info_of(" KB.M 25 : KB\n")
    for key in ("rmf", "rmf_temp", "mud_rm", "mud_rm_temp"):
        assert key not in info
    prop = mud_header_proposal(info)
    assert set(prop) == {"assumed", "skipped"} and not prop["assumed"] and not prop["skipped"]
    assert mud_header_proposal(None) == {"assumed": [], "skipped": {}}


def test_blank_and_null_values_are_ignored():
    info = info_of(" RMF .OHMM   -999.25 : RMF\n MFST.DEGF   : TEMP\n")
    assert "rmf" not in info and "rmf_temp" not in info


def test_unitless_values_are_assumed_and_flagged():
    prop = mud_header_proposal(info_of(" RMF .   0.3 : RMF\n MFST.   80 : TEMP\n"))
    assert prop["rmf"] == pytest.approx(0.3) and prop["rmf_temp"] == pytest.approx(80.0)
    assert set(prop["assumed"]) == {"rmf", "rmf_temp"}


def test_unknown_unit_or_implausible_value_is_shown_but_not_offered():
    prop = mud_header_proposal(info_of(
        " RMF .MMHO   3.0 : RMF\n MFST.KELVIN   300 : TEMP\n RM  .OHMM   0.5 : MUD\n"))
    assert "rmf" not in prop and "rmf_temp" not in prop
    assert prop["skipped"]["rmf"] == "unit is not ohm.m"
    assert prop["skipped"]["rmf_temp"] == "unit is not degF or degC"
    assert prop["mud_rm"] == pytest.approx(0.5)
    prop = mud_header_proposal(info_of(" RMF .OHMM   500 : RMF\n"))
    assert "rmf" not in prop and prop["skipped"]["rmf"] == "outside the plausible range"


def test_header_rm_is_not_the_medium_resistivity_curve():
    text = make_las(params=" RM  .OHMM   0.5 : MUD\n",
                    curves=(("GR", "API", [50.0, 60.0, 70.0]), ("RILM", "OHMM", [5.0, 6.0, 7.0])))
    parser = parse(text)
    assert parser.well_info["mud_rm"] == 0.5
    assert parser.find_curve_by_type("RM") == "RILM"


def test_existing_columns_and_header_fields_are_unchanged():
    base = parse(make_las(params=" BHT .DEGC   85 : BHT\n"))
    mud = parse(make_las(params=" BHT .DEGC   85 : BHT\n RMF .OHMM   0.35 : RMF\n MFST.DEGF 68 : T\n"))
    assert list(base.data.columns) == list(mud.data.columns)
    assert base.data.equals(mud.data)
    for key, value in base.well_info.items():
        assert mud.well_info[key] == value


# ---------------------------------------------------------------------------
# T_FM_F derive
# ---------------------------------------------------------------------------
def lrlc_with(rmf=0.35, steps=("invasion",), zones=None):
    def block(s, r=rmf):
        return {"rt_steps": list(s), "rt_fallback": "nan", "rmf": r}
    return {"resolved": {"default": dict(block(steps), rmf_temp=68.0),
                         "zones": {z: block(*a) for z, a in (zones or {}).items()}}}


TVD = np.array([5000.0, 6000.0, 7000.0])
KEYS = np.array(["__none__"] * 3, dtype=object)


def test_derive_is_registered_with_well_scope():
    spec = chain.DERIVES["formation_temperature"]
    assert spec.scope == "well" and spec.outputs == ("T_FM_F",)
    invasion.register_step()                    # idempotent
    assert chain.DERIVES["formation_temperature"] is spec


def test_derive_matches_the_app_formation_temperature_with_options_off():
    from modules.param_scopes import UNZONED
    keys = np.array([UNZONED] * 3, dtype=object)
    params = {"surface_temp": 70.0, "temp_gradient": 1.8, "temp_datum_depth": 100.0,
              "temp_correction": False, "ws_b_auto": False}
    out = chain.DERIVES["formation_temperature"].fn(tvd=TVD, params=params, zone_keys=keys, lrlc=lrlc_with())
    assert set(out) == {"T_FM_F"}
    assert np.allclose(out["T_FM_F"], formation_temperature(TVD, 70.0, 1.8, 100.0))


def test_derive_skipped_without_invasion_or_without_rmf():
    from modules.param_scopes import UNZONED
    keys = np.array([UNZONED] * 3, dtype=object)
    fn = chain.DERIVES["formation_temperature"].fn
    assert fn(tvd=TVD, params={}, zone_keys=keys, lrlc=lrlc_with(steps=())) == {}
    assert fn(tvd=TVD, params={}, zone_keys=keys, lrlc=lrlc_with(rmf=None)) == {}
    assert fn(tvd=TVD, params={}, zone_keys=keys, lrlc=None) == {}


def test_derive_needs_only_one_zone_with_invasion_and_rmf():
    keys = np.array(["A", "B", "B"], dtype=object)
    lrlc = lrlc_with(steps=(), zones={"B": (("invasion",), 0.4)})
    assert invasion.temperature_needed(lrlc, keys)
    assert not invasion.temperature_needed(lrlc, keys[:1])


def test_default_temperature_setup_raises_the_info_issue():
    from modules.param_scopes import UNZONED
    keys = np.array([UNZONED] * 3, dtype=object)
    fn = chain.DERIVES["formation_temperature"].fn
    issues = []
    out = fn(tvd=TVD, params={"surface_temp": 80.0, "temp_gradient": 1.5, "temp_datum_depth": 0.0},
             zone_keys=keys, lrlc=lrlc_with(), issues=issues)
    assert "T_FM_F" in out
    assert [i[0] for i in issues] == ["LRLC_INV_TEMP_DEFAULT"]
    assert "degF" in issues[0][1]
    issues = []
    fn(tvd=TVD, params={"surface_temp": 75.0, "temp_gradient": 1.5}, zone_keys=keys,
       lrlc=lrlc_with(), issues=issues)
    assert issues == []
    issues = []
    fn(tvd=TVD, params={"surface_temp": 80.0, "temp_gradient": 1.5}, zone_keys=keys,
       lrlc=lrlc_with(rmf=None), issues=issues)
    assert issues == []


def test_issue_code_is_registered():
    from modules.issue_codes import ISSUE_CODES
    assert "LRLC_INV_TEMP_DEFAULT" in ISSUE_CODES and "LRLC_INV_DECON_MISMATCH" in ISSUE_CODES


def test_step_reads_the_derived_temperature_through_the_chain():
    from modules.param_scopes import UNZONED
    n = 2
    ra = invasion.forward_ra(np.array([20.0, 20.0]), np.array([0.5, 0.5]), np.array([40.0, 40.0]),
                             (80.0, 45.0, 20.0), 2.5)
    keys = np.array([UNZONED] * n, dtype=object)
    out = chain.DERIVES["formation_temperature"].fn(
        tvd=np.array([7000.0, 7000.0]), params={"surface_temp": 60.0, "temp_gradient": 2.0},
        zone_keys=keys, lrlc=lrlc_with(rmf=2.0))
    arrays = {"depth": np.arange(n, dtype=float), "vsh": [0, 0], "phit": [0.2, 0.2], "phie": [0.2, 0.2],
              "rsh": [3, 3], "rw": [0.1, 0.1], "rm": ra[:, 1], "rs": ra[:, 2], "derived": out}
    res = apply_rt_chain(ra[:, 0].copy(), arrays, keys, lrlc_with(rmf=2.0, ), False)
    rec = [r for r in res.records if r["step"] == "invasion"][0]
    assert rec["counts"].get("no_temperature", 0) == 0
    assert rec["counts"]["rxo_below_rmf"] == 2          # Rmf 2.0 at 68 degF is about 0.72 at 200 degF; Rxo here is 0.5
    no_t = apply_rt_chain(ra[:, 0].copy(), {k: v for k, v in arrays.items() if k != "derived"}, keys,
                          lrlc_with(rmf=2.0), False)
    rec = [r for r in no_t.records if r["step"] == "invasion"][0]
    assert rec["counts"]["no_temperature"] == 2


# ---------------------------------------------------------------------------
# Vertical-resolution step next to the invasion step
# ---------------------------------------------------------------------------
def _vertical_step():
    return StepSpec(name="vtest", order=chain.CHAIN_ORDER.index("decon"), column="RT_VTEST",
                    fn=lambda rt, ctx, prm: StepResult(rt.copy(), np.isfinite(rt), {}, {}, ()),
                    label="Vertical test", description="TEST", refs=(), kind="vertical")


def _run(monkeypatch, steps, zone_steps=None):
    from modules.param_scopes import UNZONED
    monkeypatch.setitem(chain.STEPS, "vtest", _vertical_step())
    ra = invasion.forward_ra(np.array([20.0, 20.0]), np.array([2.0, 2.0]), np.array([40.0, 40.0]),
                             (80.0, 45.0, 20.0), 2.5)
    keys = np.array(["A", "B"], dtype=object)
    lrlc = {"resolved": {"default": {"rt_steps": [], "rt_fallback": "nan"},
                         "zones": {"A": {"rt_steps": list(steps), "rt_fallback": "nan"},
                                   "B": {"rt_steps": ["invasion"], "rt_fallback": "nan"}}}}
    arrays = {"depth": np.arange(2, dtype=float), "vsh": [0, 0], "phit": [0.2, 0.2], "phie": [0.2, 0.2],
              "rsh": [3, 3], "rw": [0.1, 0.1], "rm": ra[:, 1], "rs": ra[:, 2]}
    return apply_rt_chain(ra[:, 0].copy(), arrays, keys, lrlc, False)


def test_vertical_step_with_invasion_in_one_zone_warns_for_that_zone(monkeypatch):
    out = _run(monkeypatch, ("vtest", "invasion"))
    issues = invasion.invasion_count_issues(out.records)
    mism = [i for i in issues if i[0] == "LRLC_INV_DECON_MISMATCH"]
    assert len(mism) == 1 and mism[0][2] == "A"
    from modules.issue_codes import ISSUE_CODES
    assert ISSUE_CODES["LRLC_INV_DECON_MISMATCH"][0] == "warning"


def test_no_mismatch_without_a_vertical_step(monkeypatch):
    out = _run(monkeypatch, ("invasion",))
    assert not [i for i in invasion.invasion_count_issues(out.records)
                if i[0] == "LRLC_INV_DECON_MISMATCH"]
    out = _run(monkeypatch, ("vtest",))
    assert not [i for i in invasion.invasion_count_issues(out.records)
                if i[0] == "LRLC_INV_DECON_MISMATCH"]
