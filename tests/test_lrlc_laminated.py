"""Hagiwara laminated-sand Rt (modules/lrlc/laminated.py) and its chain step."""

import numpy as np
import pytest

from modules.lrlc import chain
from modules.lrlc.chain import apply_rt_chain
from modules.lrlc.laminated import STEP, hagiwara_rt, laminated_step, register_step
from modules.param_scopes import UNZONED

ARGS = dict(hag_vsh_max=0.8, s_warn=0.8, s_invalid=0.95)


def hag(rt, vlam=0.3, rsh=2.0, vsh=0.3, **kw):
    a = dict(ARGS, **kw)
    return hagiwara_rt(np.atleast_1d(np.asarray(rt, dtype=float)), vlam, rsh, vsh,
                       a["hag_vsh_max"], a["s_warn"], a["s_invalid"])


def test_worked_values():
    out, valid, counts = hag([5.0, 5.5, 6.0, 6.5])
    assert out[0] == pytest.approx(14.0)
    assert out[1] == pytest.approx(22.0)
    assert out[2] == pytest.approx(42.0)
    assert np.isnan(out[3])
    assert valid.tolist() == [True, True, True, False]
    assert counts["invalid"] == 1
    # s = 0.75, 0.825, 0.90 -> the last two are sensitive
    assert counts["sensitive"] == 2


def test_vlam_zero_is_bit_exact_identity():
    rt = np.array([0.7, 1.0 / 3.0, 12.345678901234567, 1e-3 * np.pi])
    out, valid, counts = hag(rt, vlam=0.0)
    assert out.tobytes() == rt.tobytes()
    assert valid.all() and counts["identity"] == 4


def test_s_thresholds():
    # s = vlam*rt/rsh with vlam=0.5, rsh=1  ->  s = 0.5*rt
    out, _, c = hag([1.5999], vlam=0.5, rsh=1.0)          # s just under 0.8
    assert c["sensitive"] == 0 and np.isfinite(out[0])
    out, _, c = hag([1.6], vlam=0.5, rsh=1.0)             # s = 0.8 -> sensitive
    assert c["sensitive"] == 1 and np.isfinite(out[0])
    out, valid, c = hag([1.8999], vlam=0.5, rsh=1.0)
    assert c["invalid"] == 0 and c["sensitive"] == 1 and valid[0]
    out, valid, c = hag([1.9], vlam=0.5, rsh=1.0)         # s = 0.95 -> invalid
    assert c["invalid"] == 1 and np.isnan(out[0]) and not valid[0]
    # custom thresholds
    out, valid, c = hag([5.0], s_invalid=0.7)
    assert np.isnan(out[0]) and c["invalid"] == 1


def test_shale_passthrough_is_valid_not_invalid():
    rt = np.array([3.0, 4.0])
    out, valid, c = hag(rt, vsh=np.array([0.8, 0.95]))
    np.testing.assert_array_equal(out, rt)
    assert valid.all()
    assert c["not_applicable"] == 2 and c["invalid"] == 0 and c["no_input"] == 0
    out, valid, c = hag([3.0], vsh=0.79)
    assert c["not_applicable"] == 0


def test_no_input():
    out, valid, c = hag([np.nan, -1.0, 0.0, 5.0, 5.0, 5.0],
                        vlam=np.array([0.3, 0.3, 0.3, np.nan, 0.3, 0.3]),
                        rsh=np.array([2.0, 2.0, 2.0, 2.0, np.nan, 2.0]),
                        vsh=np.array([0.3, 0.3, 0.3, 0.3, 0.3, np.nan]))
    assert np.isnan(out).all() and not valid.any()
    assert c["no_input"] == 6


def test_monotonicity():
    rts = np.linspace(2.5, 5.9, 30)
    out = hag(rts)[0]
    assert np.all(np.diff(out) > 0)                       # increases with Rt
    vl = np.linspace(0.05, 0.4, 20)
    out = hag(np.full(20, 5.0), vlam=vl, rsh=2.0)[0]
    assert np.all(np.diff(out[np.isfinite(out)]) > 0)     # increases with Vlam (Rt > Rsh)
    rsh = np.linspace(2.0, 10.0, 20)   # first value: s = 0.75, still valid
    out = hag(np.full(20, 5.0), vlam=0.3, rsh=rsh)[0]
    assert np.all(np.diff(out) < 0)                       # decreases with Rsh


def test_rt_sand_ge_rt_iff_rt_ge_rsh():
    rng = np.random.default_rng(1)
    rt = rng.uniform(0.5, 8.0, 500)
    rsh = rng.uniform(0.8, 6.0, 500)
    out, valid, _ = hagiwara_rt(rt, 0.2, rsh, 0.3, **{"hag_vsh_max": 0.8, "s_warn": 0.8, "s_invalid": 0.95})
    ok = valid
    # rt_in >= rsh  <=>  RT_SAND >= rt  (strict away from the equality)
    assert np.array_equal((out[ok] >= rt[ok]), (rt[ok] >= rsh[ok]))
    _, _, c = hagiwara_rt(rt, 0.2, rsh, 0.3, 0.8, 0.8, 0.95)
    assert c["below_rsh"] == int(((rt < rsh) & ok).sum())


def test_array_scalar_parity_and_arps_rsh():
    rt = np.array([4.0, 5.0, 3.0, 6.0])
    rsh = np.array([2.0, 2.2, 1.8, 2.5])                  # per-sample (Arps corrected) Rsh
    arr = hagiwara_rt(rt, np.full(4, 0.25), rsh, np.full(4, 0.3), 0.8, 0.8, 0.95)[0]
    for i in range(4):
        one = hagiwara_rt(rt[i:i + 1], 0.25, float(rsh[i]), 0.3, 0.8, 0.8, 0.95)[0]
        assert one[0] == arr[i]
        expect = 0.75 * rt[i] / (1 - 0.25 * rt[i] / rsh[i])
        assert arr[i] == pytest.approx(expect)


def test_inputs_not_mutated():
    rt = np.array([5.0, 5.5])
    copy = rt.copy()
    hag(rt)
    np.testing.assert_array_equal(rt, copy)


# ------------------------------------------------------------------ the step

def _ctx_arrays(n, vlam=None, rsh=2.0, vsh=0.3):
    d = {"depth": np.arange(n, dtype=float), "vsh": np.full(n, vsh), "phit": np.full(n, 0.25),
         "phie": np.full(n, 0.22), "rsh": np.full(n, rsh), "rw": np.full(n, 0.1)}
    if vlam is not None:
        d["derived"] = {"VLAM": np.asarray(vlam, dtype=float)}
    return d


def _lrlc(**prm):
    base = {"rt_steps": ["laminated"], "rt_fallback": "nan", "vlam_source": "ts",
            "vlam_const": 0.0, "hag_vsh_max": 0.8, "s_warn": 0.8, "s_invalid": 0.95}
    base.update(prm)
    return {"resolved": {"default": base, "zones": {}}}


def test_step_spec_shape():
    assert STEP.name == "laminated" and STEP.column == "RT_SAND" and STEP.kind == "lamination"
    assert STEP.order == chain.CHAIN_ORDER.index("laminated")
    assert STEP.varied == ("rsh",)
    assert STEP.params == ("vlam_source", "vlam_const", "hag_vsh_max", "s_warn", "s_invalid")
    assert STEP.refs == ("poupon1954", "hagiwara_us4739255", "hagiwara1995", "hagiwara1997")


def test_register_step_is_idempotent(monkeypatch):
    monkeypatch.setattr(chain, "STEPS", {})
    register_step()
    register_step()
    assert list(chain.STEPS) == ["laminated"]


def test_runs_through_apply_rt_chain(monkeypatch):
    monkeypatch.setitem(chain.STEPS, "laminated", STEP)
    rt = np.array([5.0, 5.5, 6.0, 6.5, 3.0, 4.0])
    n = len(rt)
    zones = np.array([UNZONED] * n, dtype=object)
    vsh = np.full(n, 0.3)
    ca = _ctx_arrays(n, vlam=np.full(n, 0.3))
    ca["vsh"] = vsh
    ca["vsh"][5] = 0.9                                   # shale sample: passes through
    out = apply_rt_chain(rt, ca, zones, _lrlc(), False)
    assert out.rt_values is not None and out.write_rt_sw
    sand = out.columns["RT_SAND"]
    np.testing.assert_allclose(sand[:3], [14.0, 22.0, 42.0])
    assert np.isnan(sand[3])
    assert sand[5] == 4.0
    np.testing.assert_array_equal(out.rt_sw, sand)
    rec = out.records[0]
    assert rec["step"] == "laminated" and rec["curve"] == "RT_SAND" and rec["n_invalid"] == 1
    assert "hagiwara1997" in rec["refs"]
    assert any(i[0] == "LRLC_STEP_INVALID" for i in out.issues)
    # previous-Rt fallback
    out = apply_rt_chain(rt, ca, zones, _lrlc(rt_fallback="previous"), False)
    assert out.columns["RT_SAND"][3] == 6.5


def test_constant_source_and_missing_vlam(monkeypatch):
    monkeypatch.setitem(chain.STEPS, "laminated", STEP)
    rt = np.array([5.0, 5.5])
    zones = np.array([UNZONED] * 2, dtype=object)
    out = apply_rt_chain(rt, _ctx_arrays(2), zones,
                         _lrlc(vlam_source="constant", vlam_const=0.3), False)
    np.testing.assert_allclose(out.columns["RT_SAND"], [14.0, 22.0])
    # ts source without a VLAM array: nothing computed, counted
    out = apply_rt_chain(rt, _ctx_arrays(2), zones, _lrlc(), False)
    assert np.isnan(out.columns["RT_SAND"]).all()


def test_step_counts_and_no_vlam():
    from modules.lrlc.chain import _ctx_for, _normalise
    rt = np.array([5.0, 5.0, 5.0])
    arrays = _normalise(_ctx_arrays(3), rt)
    ctx = _ctx_for(arrays, UNZONED, np.arange(3))
    res = laminated_step(rt.copy(), ctx, {"vlam_source": "ts"})
    assert res.counts["no_vlam"] == 3 and res.counts["no_input"] == 3
    assert not res.valid_mask.any()
    res = laminated_step(rt.copy(), ctx, {"vlam_source": "constant", "vlam_const": 0.0})
    assert res.counts["identity"] == 3 and res.valid_mask.all()
    assert res.rt_out.tobytes() == rt.tobytes()
    assert res.refs == ("poupon1954", "hagiwara_us4739255", "hagiwara1995", "hagiwara1997")
