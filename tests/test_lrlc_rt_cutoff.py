"""Rt cutoff RT_CUT: closed forms, round trips through the production Sw models."""

import numpy as np
import pandas as pd
import pytest

from modules.lrlc import rt_cutoff as rc
from modules.lrlc.rt_cutoff import MODELS, SwInputs, rt_cutoff, zone_scalar
from modules.petrophysics import PetrophysicsCalculator

N = 40
A, M, NEXP = 0.62, 2.1, 2.0


def _inputs(phie=None, vsh=None, **kw):
    rng = np.random.default_rng(5)
    phie = rng.uniform(0.08, 0.30, N) if phie is None else phie
    vsh = rng.uniform(0.05, 0.5, N) if vsh is None else vsh
    base = dict(phie=phie, phit=phie + 0.03, vsh=vsh, rw_eff=0.06, rsh_eff=3.0, rwb_eff=0.1,
                ws_b=0.8, a=A, m=M, n=NEXP, ws_qv=0.25, dw_swb=0.12)
    base.update(kw)
    return SwInputs(**base)


def test_archie_closed_form():
    inp = _inputs()
    cut, n_el, n_nr = rt_cutoff("Archie", inp, 0.6, pd.RangeIndex(N))
    expect = A * 0.06 / (inp.phie ** M * 0.6 ** NEXP)
    assert n_el == N and n_nr == 0
    np.testing.assert_allclose(cut, expect, rtol=1e-6)


def test_simandoux_n2_closed_form():
    inp = _inputs()
    t = 0.5
    cut, _, _ = rt_cutoff("Simandoux", inp, t, pd.RangeIndex(N))
    inv = inp.phie ** M * t ** 2 / (A * 0.06) + inp.vsh * t / 3.0
    np.testing.assert_allclose(cut, 1.0 / inv, rtol=1e-6)


def test_indonesian_closed_form():
    inp = _inputs()
    t = 0.5
    cut, _, _ = rt_cutoff("Indonesian", inp, t, pd.RangeIndex(N))
    inv_sqrt = (inp.vsh ** (1 - inp.vsh / 2) / np.sqrt(3.0)
                + inp.phie ** (M / 2) / np.sqrt(A * 0.06)) * t ** (NEXP / 2)
    np.testing.assert_allclose(cut, 1.0 / inv_sqrt ** 2, rtol=1e-6)


def _sw_back(model, inp, cut, index):
    calc = PetrophysicsCalculator(pd.DataFrame({"RT_TRIAL": np.ones(len(index))}, index=index))

    def s(v):
        return pd.Series(np.broadcast_to(v, len(index)).astype(float), index=index)

    if model == "Archie":
        return calc.calculate_sw_archie("RT_TRIAL", s(inp.phie), inp.rw_eff, A, M, NEXP, rt=cut)
    if model == "Indonesian":
        return calc.calculate_sw_indonesian("RT_TRIAL", s(inp.phie), s(inp.vsh), inp.rw_eff,
                                            inp.rsh_eff, A, M, NEXP, rt=cut)
    if model == "Simandoux":
        return calc.calculate_sw_simandoux("RT_TRIAL", s(inp.phie), s(inp.vsh), inp.rw_eff,
                                           inp.rsh_eff, A, M, NEXP, rt=cut)
    if model == "Waxman-Smits":
        return calc.calculate_sw_waxman_smits("RT_TRIAL", s(inp.phit), inp.rw_eff, A, M, NEXP,
                                              inp.ws_qv, inp.ws_b, phie=s(inp.phie), rt=cut)
    return calc.calculate_sw_dual_water("RT_TRIAL", s(inp.phit), inp.rw_eff, A, M, NEXP,
                                        inp.dw_swb, inp.rwb_eff, phie=s(inp.phie), rt=cut)


@pytest.mark.parametrize("model", MODELS)
def test_round_trip(model):
    inp = _inputs()
    index = pd.RangeIndex(N)
    cut, n_el, n_nr = rt_cutoff(model, inp, 0.55, index)
    assert n_el == N
    ok = np.isfinite(cut)
    assert ok.sum() == N - n_nr and ok.sum() > 0
    sw = np.asarray(_sw_back(model, inp, np.where(ok, cut, 1.0), index))
    np.testing.assert_allclose(sw[ok], 0.55, atol=1e-6)


@pytest.mark.parametrize("model", MODELS)
def test_monotone_in_target(model):
    inp = _inputs()
    lo, _, _ = rt_cutoff(model, inp, 0.3, pd.RangeIndex(N))
    hi, _, _ = rt_cutoff(model, inp, 0.7, pd.RangeIndex(N))
    both = np.isfinite(lo) & np.isfinite(hi)
    assert both.any() and np.all(lo[both] > hi[both])


def test_no_root_counted():
    phie = np.full(N, 0.2)
    phie[0] = 0.9   # needs Rt far below 0.01 ohm.m for Sw = 0.5
    inp = _inputs(phie=phie, rw_eff=0.0005)
    cut, n_el, n_nr = rt_cutoff("Archie", inp, 0.5, pd.RangeIndex(N))
    assert np.isnan(cut[0])
    assert n_el == N and n_nr == 1


def test_ineligible_not_counted():
    phie = np.full(N, 0.2)
    phie[:3] = [np.nan, 0.0, 0.001]
    inp = _inputs(phie=phie, phit=phie.copy())
    for model in MODELS:
        cut, n_el, n_nr = rt_cutoff(model, inp, 0.5, pd.RangeIndex(N))
        assert np.isnan(cut[:3]).all()
        assert n_el == N - 3 and n_nr == 0, model


def test_nonfinite_input_ineligible_no_raise():
    rsh = np.full(N, 3.0)
    rsh[5] = np.nan
    inp = _inputs(rsh_eff=rsh)
    cut, n_el, _ = rt_cutoff("Simandoux", inp, 0.5, pd.RangeIndex(N))
    assert np.isnan(cut[5]) and n_el == N - 1


def test_unknown_model():
    with pytest.raises(ValueError):
        rt_cutoff("Foo", _inputs(), 0.5, pd.RangeIndex(N))


def test_live_calculator_untouched():
    index = pd.RangeIndex(N)
    live = PetrophysicsCalculator(pd.DataFrame({"RT": np.full(N, 10.0)}, index=index))
    live.results["SW_ARCHIE"] = pd.Series(0.123, index=index)
    live.sw_flags["SW_ARCHIE"] = "sentinel"
    before = live.results.copy()
    for model in MODELS:
        rt_cutoff(model, _inputs(), 0.5, index)
    pd.testing.assert_frame_equal(live.results, before)
    assert live.sw_flags == {"SW_ARCHIE": "sentinel"}
    assert not live.solver_diagnostics


def test_per_sample_effective_inputs():
    rw = np.linspace(0.03, 0.09, N)
    inp = _inputs(rw_eff=rw)
    cut, _, _ = rt_cutoff("Archie", inp, 0.5, pd.RangeIndex(N))
    np.testing.assert_allclose(cut, A * rw / (inp.phie ** M * 0.25), rtol=1e-6)


def _zone_data():
    inp = _inputs(phie=np.linspace(0.1, 0.3, N), vsh=np.full(N, 0.2))
    zone = np.arange(N) < 20
    return inp, zone, np.ones(N)


def test_zone_scalar_basis_fallback():
    inp, zone, dz = _zone_data()
    zeros = np.zeros(N, dtype=int)
    pay = zeros.copy()
    pay[2:6] = 1
    res = zeros.copy()
    res[2:10] = 1
    gross = zeros.copy()
    gross[:15] = 1
    row = zone_scalar("Archie", inp, 0.5, zone_mask=zone, dz=dz, net_pay_flag=pay,
                      net_res_flag=res, gross_sand_flag=gross, zone="UP")
    assert row["basis"] == "pay" and row["n"] == 4 and row["zone"] == "UP"
    assert row["model"] == "Archie" and row["sw_target"] == 0.5
    mean_phi = inp.phie[2:6].mean()
    assert row["phie"] == pytest.approx(mean_phi)
    assert row["rt_cut"] == pytest.approx(A * 0.06 / (mean_phi ** M * 0.25), rel=1e-6)
    row = zone_scalar("Archie", inp, 0.5, zone_mask=zone, dz=dz, net_pay_flag=zeros,
                      net_res_flag=res, gross_sand_flag=gross)
    assert row["basis"] == "net reservoir" and row["n"] == 8
    row = zone_scalar("Archie", inp, 0.5, zone_mask=zone, dz=dz, net_pay_flag=zeros,
                      net_res_flag=zeros, gross_sand_flag=gross)
    assert row["basis"] == "gross sand" and row["n"] == 15
    assert zone_scalar("Archie", inp, 0.5, zone_mask=zone, dz=dz, net_pay_flag=zeros,
                       net_res_flag=zeros, gross_sand_flag=zeros) is None


def test_zone_scalar_thickness_weighted_and_zone_limited():
    inp, zone, _ = _zone_data()
    dz = np.ones(N)
    dz[3] = 5.0
    flag = np.zeros(N, dtype=int)
    flag[2:5] = 1
    flag[25] = 1  # sample 25 is outside the zone
    row = zone_scalar("Archie", inp, 0.5, zone_mask=zone, dz=dz, net_pay_flag=flag,
                      net_res_flag=flag, gross_sand_flag=flag)
    assert row["n"] == 3
    w = np.array([1, 5, 1.0])
    assert row["phie"] == pytest.approx((inp.phie[2:5] * w).sum() / w.sum())


def test_zone_scalar_all_models():
    inp, zone, dz = _zone_data()
    flag = np.zeros(N, dtype=int)
    flag[2:8] = 1
    for model in MODELS:
        row = zone_scalar(model, inp, 0.5, zone_mask=zone, dz=dz, net_pay_flag=flag,
                          net_res_flag=flag, gross_sand_flag=flag)
        assert np.isfinite(row["rt_cut"]) and row["rt_cut"] > 0, model


def test_bracket_constants():
    assert rc.BRACKET == (-2.0, 5.0) and rc.N_ITER == 30
