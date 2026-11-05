import numpy as np
import pytest

from modules.lrlc import chain, pyrite

EP = dict(rho_f=1.0, u_fluid=0.36, rho_ma=2.65, pef_ma=1.81, rho_py=4.99, pef_py=16.97,
          rho_sh=2.45, pef_sh=3.4, pef_max=25.0, neg_tol=0.01, vpyr_max=0.25)


def forward(phi, vma, vpy, vsh=0.0):
    rhob = phi * EP["rho_f"] + vma * EP["rho_ma"] + vpy * EP["rho_py"] + vsh * EP["rho_sh"]
    u = (phi * EP["u_fluid"] + vma * EP["pef_ma"] * EP["rho_ma"]
         + vpy * EP["pef_py"] * EP["rho_py"] + vsh * EP["pef_sh"] * EP["rho_sh"])
    return rhob, u / rhob


def test_worked_forward_values():
    rhob, pef = forward(0.20, 0.77, 0.03)
    assert rhob == pytest.approx(2.3902, abs=1e-4)
    assert pef == pytest.approx(2.6382, abs=1e-3)


def test_round_trip_clean():
    rhob, pef = forward(0.20, 0.77, 0.03)
    r = pyrite.solve_volumes(np.array([rhob]), np.array([pef]), np.array([0.0]), **EP)
    assert r.vpyr[0] == pytest.approx(0.03, abs=1e-9)
    assert r.phi[0] == pytest.approx(0.20, abs=1e-9)
    assert r.vma[0] == pytest.approx(0.77, abs=1e-9)
    assert 100 < r.cond < 300
    assert not r.ill_conditioned


def test_round_trip_with_shale():
    rhob, pef = forward(0.15, 0.70, 0.04, vsh=0.11)
    r = pyrite.solve_volumes(rhob, pef, 0.11, **EP)
    assert r.vpyr[0] == pytest.approx(0.04, abs=1e-9)
    assert r.phi[0] == pytest.approx(0.15, abs=1e-9)
    assert r.vma[0] == pytest.approx(0.70, abs=1e-9)


def test_singular_matrix_guard():
    ep = dict(EP)
    ep.update(rho_py=EP["rho_ma"], pef_py=EP["pef_ma"])  # pyrite identical to matrix
    r = pyrite.solve_volumes(np.array([2.4]), np.array([2.6]), np.array([0.0]), **ep)
    assert r.ill_conditioned
    assert np.all(np.isnan(r.vpyr)) and np.all(np.isnan(r.phi)) and np.all(np.isnan(r.vma))


def test_negative_implausible_and_inputs():
    rhob0, pef0 = forward(0.20, 0.79, 0.01)
    rhob_n, pef_n = forward(0.20, 0.805, -0.005)     # within tolerance -> 0
    rhob_m, pef_m = forward(0.20, 0.83, -0.03)       # below -tol -> NaN
    rhob_i, pef_i = forward(0.10, 0.60, 0.30)        # above vpyr_max -> NaN
    rhob = np.array([rhob0, rhob_n, rhob_m, rhob_i, np.nan, 2.4, 2.4])
    pef = np.array([pef0, pef_n, pef_m, pef_i, 2.0, np.nan, 30.0])
    r = pyrite.solve_volumes(rhob, pef, np.zeros(7), **EP)
    assert r.vpyr[0] == pytest.approx(0.01, abs=1e-9)
    assert r.vpyr[1] == 0.0
    assert np.isnan(r.vpyr[2]) and np.isnan(r.vpyr[3])
    assert np.all(np.isnan(r.vpyr[4:]))
    assert r.counts == {"no_input": 3, "negative": 1, "rounded_zero": 1, "implausible": 1}


def test_identity_bit_exact():
    rt = np.array([0.3, 5.0, 17.123456789, 250.0])
    for f, vp in ((0.0, 0.05), (0.5, 0.0)):
        out, valid, counts = pyrite.pyrite_rt(rt, np.full(4, vp), f, 0.1, 0.8, 0.95)
        assert out.tobytes() == rt.tobytes()
        assert valid.all()
        assert counts["identity"] == 4


def test_worked_example_and_ordering():
    out, valid, counts = pyrite.pyrite_rt(np.array([5.0]), np.array([0.02]), 0.05, 0.1, 0.8, 0.95)
    assert out[0] == pytest.approx(5.263, abs=1e-3)
    assert out[0] == pytest.approx(1.0 / (1 / 5.0 - 0.01))
    rt = np.array([0.5, 1.0, 3.0, 8.0, 20.0])
    out, valid, _ = pyrite.pyrite_rt(rt, np.full(5, 0.02), 0.1, 0.5, 0.8, 0.95)
    assert valid.all()
    assert np.all(out >= rt)


def test_sensitivity_counts_and_no_input():
    # t = 0.1*0.1/0.1 = 0.1; s = 0.1*rt
    rt = np.array([1.0, 8.5, 9.6, 20.0, np.nan])
    vpyr = np.array([0.1, 0.1, 0.1, 0.1, 0.1])
    out, valid, c = pyrite.pyrite_rt(rt, vpyr, 0.1, 0.1, 0.8, 0.95)
    assert valid.tolist() == [True, True, False, False, False]
    assert np.isnan(out[2]) and np.isnan(out[3]) and np.isnan(out[4])
    assert c["sensitive"] == 1 and c["invalid"] == 2 and c["no_input"] == 0
    out, valid, c = pyrite.pyrite_rt(np.array([5.0, 5.0]), np.array([np.nan, 0.02]), 0.05, 0.1, 0.8, 0.95)
    assert c["no_input"] == 1
    assert not valid[0] and valid[1]


def _ctx(n, derived=None):
    return chain.ChainContext(
        depth=np.arange(n, dtype=float), zone="Z", rows=np.arange(n), rt_raw=np.ones(n),
        vsh=np.zeros(n), phit=np.full(n, 0.2), phie=np.full(n, 0.2), rsh=np.full(n, 3.0),
        rw=np.full(n, 0.1), temperature=None, rhob=None, pef=None, rm=None, rs=None,
        rxo=None, hires=None, segment_depth=np.arange(n, dtype=float), flags={},
        derived=derived or {})


PRM = {"pyr_method": "manual", "pyr_vpyr": 0.02, "pyr_f": 0.05, "pyr_rpy": 0.1,
       "s_warn": 0.8, "s_invalid": 0.95}


def test_step_manual_and_derived():
    rt = np.array([5.0, 5.0])
    res = pyrite.pyrite_step(rt, _ctx(2), PRM)
    assert res.refs == ("clavier1976",)
    assert res.rt_out[0] == pytest.approx(5.263, abs=1e-3)
    prm = dict(PRM, pyr_method="rhob_pef")
    res = pyrite.pyrite_step(rt, _ctx(2), prm)
    assert not res.valid_mask.any() and res.counts["no_input"] == 2
    res = pyrite.pyrite_step(rt, _ctx(2, {"VPYR": np.array([0.02, np.nan])}), prm)
    assert res.valid_mask.tolist() == [True, False]


def test_step_spec_through_chain(monkeypatch):
    monkeypatch.setitem(chain.STEPS, "pyrite", pyrite.STEP)
    assert pyrite.STEP.order == chain.CHAIN_ORDER.index("pyrite")
    n = 4
    rt = np.array([2.0, 5.0, 10.0, 5.0])
    arrays = dict(depth=np.arange(n, dtype=float), vsh=np.zeros(n), phit=np.full(n, 0.2),
                  phie=np.full(n, 0.2), rsh=np.full(n, 3.0), rw=np.full(n, 0.1),
                  derived={"VPYR": np.array([0.02, 0.02, 0.02, np.nan])})
    prm = dict(PRM, pyr_method="rhob_pef", rt_steps=["pyrite"], rt_fallback="nan")
    lrlc = {"resolved": {"default": prm, "zones": {}}}
    out = chain.apply_rt_chain(rt, arrays, np.array(["Z"] * n, dtype=object), lrlc, False)
    assert out.write_rt_sw
    assert "RT_PYR" in out.columns
    assert out.rt_sw[0] == pytest.approx(1.0 / (1 / 2.0 - 0.01))
    assert np.isnan(out.rt_sw[3])
    assert out.records[0]["step"] == "pyrite"


def test_register_step_only_if_absent(monkeypatch):
    monkeypatch.setattr(chain, "STEPS", dict(chain.STEPS))
    pyrite.register_step()
    assert "pyrite" in chain.STEPS
    pyrite.register_step()  # no error the second time
