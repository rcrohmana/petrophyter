"""Rt correction chain framework (modules/lrlc/chain.py), pure array tests."""

import copy

import numpy as np
import pytest

from modules.lrlc import chain
from modules.lrlc.chain import (
    ChainContext, GuardDecision, StepResult, StepSpec, apply_rt_chain, available_steps,
    chain_active_anywhere, chain_path, register, rerun_chain, resolve_steps, step_params,
)
from modules.param_scopes import UNZONED
from tests.lrlc_teststeps import RSH_REF, register_test_steps  # noqa: F401


def lrlc_for(default=(), zones=None, fallback="nan"):
    def block(steps, fb=fallback):
        return {"rt_steps": list(steps), "rt_fallback": fb}
    return {"resolved": {"default": block(default),
                         "zones": {z: block(s) for z, s in (zones or {}).items()}}}


def arrays(n, **over):
    d = {"depth": np.arange(n, dtype=float), "rt_raw": None, "vsh": np.full(n, 0.2),
         "phit": np.full(n, 0.25), "phie": np.full(n, 0.22), "rsh": np.full(n, 4.0),
         "rw": np.full(n, 0.1)}
    d.pop("rt_raw")
    d.update(over)
    return d


def rt_of(n):
    return np.linspace(1.0, 10.0, n)


def zones_of(n, key=UNZONED):
    return np.array([key] * n, dtype=object)


def run(steps, n=8, **kw):
    rt = rt_of(n)
    return rt, apply_rt_chain(rt, arrays(n), zones_of(n), lrlc_for(steps, **kw), False)


# ---------------------------------------------------------------- registry

def _spec(name="x", order=1, column="RT_X", extra=(), fn=None):
    return StepSpec(name=name, order=order, column=column,
                    fn=fn or (lambda rt, c, p: StepResult(rt, np.isfinite(rt))),
                    label=name, description="d", refs=(), extra_columns=extra)


def test_registry_starts_empty(monkeypatch):
    monkeypatch.setattr(chain, "STEPS", {})
    monkeypatch.setattr(chain, "DERIVES", {})
    assert chain.STEPS == {} and chain.DERIVES == {}
    assert available_steps() == []
    assert chain_path([]) == "RT"


def test_register_duplicate_and_column_clash(monkeypatch):
    monkeypatch.setattr(chain, "STEPS", {})
    register(_spec("a", 2, "RT_A", extra=("A_EXTRA",)))
    with pytest.raises(ValueError):
        register(_spec("a", 3, "RT_OTHER"))
    with pytest.raises(ValueError):
        register(_spec("b", 3, "RT_A"))
    with pytest.raises(ValueError):
        register(_spec("c", 3, "A_EXTRA"))
    with pytest.raises(ValueError):
        register(_spec("d", 3, "RT_SW"))
    register(_spec("e", 1, "RT_E"))
    assert [s.name for s in available_steps()] == ["e", "a"]


def test_register_derive_validates(monkeypatch):
    monkeypatch.setattr(chain, "DERIVES", {})
    spec = chain.DeriveSpec("d", "segment", lambda **k: {}, ("x",))
    chain.register_derive(spec)
    with pytest.raises(ValueError):
        chain.register_derive(spec)
    with pytest.raises(ValueError):
        chain.register_derive(chain.DeriveSpec("e", "bogus", lambda **k: {}, ()))


def test_unzoned_constant_comes_from_param_scopes():
    from modules.shf_stage import UNZONED as shf_unzoned
    assert shf_unzoned == UNZONED


def test_available_steps_sorted_by_order(register_test_steps, monkeypatch):
    monkeypatch.delitem(chain.STEPS, "laminated")
    monkeypatch.delitem(chain.STEPS, "pyrite")
    assert [s.name for s in available_steps()] == [
        "test_identity", "test_scale", "test_rsh", "test_bad", "test_extra"]


def test_resolve_steps_order_unknown_and_duplicates(register_test_steps):
    specs, unknown = resolve_steps(["test_scale", "nope", "test_identity", "test_scale", "nope", "x"])
    assert [s.name for s in specs] == ["test_identity", "test_scale"]
    assert unknown == ["nope", "x"]
    assert resolve_steps(None) == ([], [])
    assert chain_path(specs) == "RT_X2 <- RT_ID <- RT"


def test_step_params_reads_declared_keys_only():
    spec = StepSpec("p", 1, "RT_P", lambda *a: None, "p", "d", (), params=("a", "b"))
    assert step_params({"a": 1, "c": 3}, spec) == {"a": 1, "b": None}


def test_chain_active_anywhere(register_test_steps):
    zk = np.array(["UP", "LOW", UNZONED], dtype=object)
    assert not chain_active_anywhere(lrlc_for(), zk)
    assert not chain_active_anywhere(lrlc_for(["unknown_step"]), zk)
    assert chain_active_anywhere(lrlc_for(["test_identity"]), zk)
    assert chain_active_anywhere(lrlc_for([], {"LOW": ["test_scale"]}), zk)
    assert not chain_active_anywhere(lrlc_for([], {"OTHER": ["test_scale"]}), zk)
    assert not chain_active_anywhere({}, zk)


# ---------------------------------------------------------------- invariants

def test_inv1_domain_only_positive_finite_or_nan(register_test_steps):
    rt, out = run(["test_bad"], n=12)
    v = out.rt_values
    ok = np.isfinite(v)
    assert np.all(v[ok] > 0)
    assert np.isnan(v[0::4]).all() and np.isnan(v[1::4]).all() and np.isnan(v[2::4]).all()
    assert out.records[0]["n_invalid"] == 9 and out.records[0]["n_valid"] == 3


def test_inv1_nan_input_is_not_counted(register_test_steps):
    rt = rt_of(6)
    rt[2] = np.nan
    out = apply_rt_chain(rt, arrays(6), zones_of(6), lrlc_for(["test_identity"]), False)
    assert np.isnan(out.rt_values[2])
    assert out.records[0]["n_invalid"] == 0 and out.records[0]["n_valid"] == 5
    assert out.issues == []


def test_inv2_alignment_one_value_per_row(register_test_steps):
    rt, out = run(["test_scale"], n=9)
    assert out.rt_values.shape == (9,)
    np.testing.assert_array_equal(out.rt_values, 2 * rt)


def test_inv2_wrong_shape_from_step_is_a_programming_error(monkeypatch):
    bad = _spec("short", 1, "RT_S", fn=lambda rt, c, p: StepResult(rt[:-1], np.isfinite(rt)[:-1]))
    monkeypatch.setitem(chain.STEPS, "short", bad)
    with pytest.raises(ValueError):
        run(["short"])


def test_inv3_no_silent_clamping_nan_with_issue(register_test_steps):
    rt, out = run(["test_bad"], n=8)
    assert np.isnan(out.rt_values[[0, 1, 2]]).all()
    codes = [i[0] for i in out.issues]
    assert codes == ["LRLC_STEP_INVALID"]
    assert out.records[0]["fallback"] == 0


def test_inv4_rt_values_none_when_no_step_ran():
    rt, out = run([], n=5)
    assert out.rt_values is None and not out.write_rt_sw
    np.testing.assert_array_equal(out.rt_sw, rt)
    assert out.columns == {} and out.records == [] and out.replay is None


def test_inv4_force_rt_sw_writes_but_values_stay_none():
    rt = rt_of(5)
    out = apply_rt_chain(rt, arrays(5), zones_of(5), lrlc_for(["unknown_step"]), True)
    assert out.rt_values is None and out.write_rt_sw
    np.testing.assert_array_equal(out.rt_sw, rt)
    assert [i[0] for i in out.issues] == ["LRLC_STEP_UNKNOWN"]


def test_inv5_order_by_spec_order_and_duplicates_collapse(register_test_steps):
    rt, out = run(["test_scale", "test_identity", "test_scale"], n=6)
    assert [r["step"] for r in out.records] == ["test_identity", "test_scale"]
    np.testing.assert_array_equal(out.rt_values, 2 * rt)
    assert out.records[1]["from"] == "RT_ID"


def test_inv6_zones_are_independent(register_test_steps):
    n = 8
    zk = np.array(["UP"] * 4 + ["LOW"] * 4, dtype=object)
    rt = rt_of(n)
    out = apply_rt_chain(rt, arrays(n), zk, lrlc_for([], {"UP": ["test_scale"]}), False)
    np.testing.assert_array_equal(out.rt_values[:4], 2 * rt[:4])
    np.testing.assert_array_equal(out.rt_values[4:], rt[4:])
    assert np.isnan(out.columns["RT_X2"][4:]).all()
    assert [r["zone"] for r in out.records] == ["UP"]


def test_inv6_step_sees_only_its_zone_rows_and_whole_segment_depth(monkeypatch):
    seen = {}

    def fn(rt, ctx, prm):
        seen[ctx.zone] = (ctx.rows.copy(), ctx.depth.copy(), ctx.segment_depth.copy())
        return StepResult(rt, np.isfinite(rt))

    monkeypatch.setitem(chain.STEPS, "spy", _spec("spy", 1, "RT_SPY", fn=fn))
    zk = np.array(["A", "B", "A", "B"], dtype=object)
    apply_rt_chain(rt_of(4), arrays(4), zk, lrlc_for(["spy"]), False)
    np.testing.assert_array_equal(seen["A"][0], [0, 2])
    np.testing.assert_array_equal(seen["B"][1], [1.0, 3.0])
    np.testing.assert_array_equal(seen["A"][2], [0, 1, 2, 3])


def test_inv7_deterministic(register_test_steps):
    a = run(["test_scale", "test_bad"], n=10)[1]
    b = run(["test_scale", "test_bad"], n=10)[1]
    np.testing.assert_array_equal(a.rt_values, b.rt_values)
    assert a.records == b.records and a.issues == b.issues


# ---------------------------------------------------------------- fallback, extras, zones

def test_fallback_nan_vs_previous_counts(register_test_steps):
    rt, nan_out = run(["test_scale", "test_bad"], n=12, fallback="nan")
    _, prev_out = run(["test_scale", "test_bad"], n=12, fallback="previous")
    bad = np.zeros(12, dtype=bool)
    bad[[i for i in range(12) if i % 4 in (0, 1, 2)]] = True
    assert np.isnan(nan_out.rt_values[bad]).all()
    np.testing.assert_array_equal(prev_out.rt_values[bad], (2 * rt)[bad])
    assert nan_out.records[1]["n_invalid"] == 9 and nan_out.records[1]["fallback"] == 0
    assert prev_out.records[1]["n_invalid"] == 9 and prev_out.records[1]["fallback"] == 9
    assert [i[0] for i in nan_out.issues] == ["LRLC_STEP_INVALID"]
    assert [i[0] for i in prev_out.issues] == ["LRLC_STEP_FALLBACK"]


def test_extra_columns_checked_against_spec(register_test_steps, monkeypatch):
    rt, out = run(["test_extra"], n=5)
    np.testing.assert_array_equal(out.columns["TEST_AUX"], np.full(5, 0.2))
    assert set(out.columns) == {"RT_EXTRA", "TEST_AUX"}
    rogue = _spec("rogue", 1, "RT_R",
                  fn=lambda rt, c, p: StepResult(rt, np.isfinite(rt), {}, {"UNDECLARED": rt}))
    monkeypatch.setitem(chain.STEPS, "rogue", rogue)
    with pytest.raises(ValueError):
        run(["rogue"])


def test_multi_zone_rest_segment_with_default_and_unknown(register_test_steps):
    n = 9
    zk = np.array(["UP"] * 3 + ["LOW"] * 3 + [UNZONED] * 3, dtype=object)
    rt = rt_of(n)
    lr = lrlc_for(["test_identity"],
                  {"UP": ["test_scale", "ghost"], "LOW": ["test_scale", "test_rsh"]})
    out = apply_rt_chain(rt, arrays(n), zk, lr, False, segment="rest")
    exp = rt.copy()
    exp[:3] *= 2
    exp[3:6] = rt[3:6] * 2 * 4.0 / RSH_REF
    np.testing.assert_allclose(out.rt_values, exp)
    by = {(r["zone"], r["step"]): r for r in out.records}
    assert set(by) == {("UP", "test_scale"), ("LOW", "test_scale"), ("LOW", "test_rsh"),
                       (None, "test_identity")}
    assert by[("LOW", "test_rsh")]["from"] == "RT_X2"
    assert all(r["segment"] == "rest" for r in out.records)
    assert [(i[0], i[2]) for i in out.issues] == [("LRLC_STEP_UNKNOWN", "UP")]
    assert np.isnan(out.columns["RT_ID"][:6]).all()
    assert np.isfinite(out.columns["RT_ID"][6:]).all()


def test_provenance_record_shape(register_test_steps):
    _, out = run(["test_rsh"])
    assert set(out.records[0]) == {"zone", "segment", "step", "curve", "from", "params", "refs",
                                   "n_valid", "n_invalid", "fallback", "counts"}
    r = out.records[0]
    assert r["zone"] is None and r["curve"] == "RT_RSH" and r["from"] == "RT"
    assert r["refs"] == ["test_ref"] and r["params"] == {}


# ---------------------------------------------------------------- guard

def test_guard_drops_a_step(register_test_steps):
    def guard(zone, specs, ctx):
        assert isinstance(ctx, ChainContext)
        return GuardDecision([s for s in specs if s.name != "test_scale"], None,
                             [("LRLC_STEP_UNKNOWN", "dropped", None, "info")])

    rt = rt_of(6)
    out = apply_rt_chain(rt, arrays(6), zones_of(6),
                         lrlc_for(["test_identity", "test_scale"]), False, guard=guard)
    assert [r["step"] for r in out.records] == ["test_identity"]
    assert out.issues[-1][3] == "info"
    np.testing.assert_array_equal(out.rt_values, rt)


def test_guard_invalid_mask_nan_or_previous(register_test_steps):
    mask = np.array([True, False, True, False, False, False])

    def guard(zone, specs, ctx):
        return GuardDecision(specs, mask)

    rt = rt_of(6)
    nan_out = apply_rt_chain(rt, arrays(6), zones_of(6), lrlc_for(["test_identity"]), False, guard=guard)
    assert np.isnan(nan_out.rt_values[mask]).all()
    assert nan_out.guard_masked == {UNZONED: 2}
    prev = apply_rt_chain(rt, arrays(6), zones_of(6),
                          lrlc_for(["test_identity"], fallback="previous"), False, guard=guard)
    np.testing.assert_array_equal(prev.rt_values, rt)


def test_guard_mask_alone_makes_rt_values_present():
    mask = np.array([True, False, False])
    out = apply_rt_chain(rt_of(3), arrays(3), zones_of(3), lrlc_for([]), False,
                         guard=lambda z, s, c: GuardDecision(s, mask))
    assert out.rt_values is not None and np.isnan(out.rt_values[0])


# ---------------------------------------------------------------- replay

def test_rerun_chain_reproduces_base_and_reacts_to_rsh(register_test_steps):
    from tests.lrlc_teststeps import CALLS
    n = 8
    rt = rt_of(n)
    ar = arrays(n)
    out = apply_rt_chain(rt, ar, zones_of(n), lrlc_for(["test_identity", "test_scale", "test_rsh"]), False)
    assert out.replay is not None
    base_calls = dict(CALLS)
    assert base_calls == {"test_identity": 1, "test_scale": 1, "test_rsh": 1}
    np.testing.assert_array_equal(rerun_chain(out.replay, {}), out.rt_values)
    assert CALLS["test_identity"] == 1 and CALLS["test_scale"] == 1 and CALLS["test_rsh"] == 2
    new = rerun_chain(out.replay, {"rsh": np.full(n, 8.0)})
    np.testing.assert_allclose(new, rt * 2 * 8.0 / RSH_REF)
    assert CALLS["test_identity"] == 1 and CALLS["test_scale"] == 1 and CALLS["test_rsh"] == 3
    assert not np.allclose(new, out.rt_values)


def test_no_replay_without_varied_step(register_test_steps):
    assert run(["test_identity", "test_scale"])[1].replay is None


def test_rerun_leaves_zones_without_varied_steps_frozen(register_test_steps):
    n = 6
    zk = np.array(["A"] * 3 + ["B"] * 3, dtype=object)
    rt = rt_of(n)
    out = apply_rt_chain(rt, arrays(n), zk, lrlc_for([], {"A": ["test_rsh"], "B": ["test_scale"]}), False)
    new = rerun_chain(out.replay, {"rsh": 8.0})
    np.testing.assert_allclose(new[:3], rt[:3] * 4.0)
    np.testing.assert_array_equal(new[3:], 2 * rt[3:])


def test_rerun_emits_no_issues_and_sanitises(register_test_steps):
    n = 8
    out = apply_rt_chain(rt_of(n), arrays(n), zones_of(n), lrlc_for(["test_rsh"]), False)
    new = rerun_chain(out.replay, {"rsh": np.array([-1.0] + [4.0] * 7)})
    assert np.isnan(new[0]) and np.isfinite(new[1:]).all()


# ---------------------------------------------------------------- purity

def test_inputs_never_mutated(register_test_steps):
    n = 12
    rt = rt_of(n)
    ar = arrays(n, rhob=np.full(n, 2.4), flags={"shoulder_corrected": False},
                derived={"vlam": np.linspace(0, 1, n)})
    zk = np.array(["A"] * 6 + ["B"] * 6, dtype=object)
    lr = lrlc_for(["test_identity"], {"A": ["test_scale", "test_bad", "test_rsh"]})
    snap = (rt.copy(), copy.deepcopy(ar), zk.copy(), copy.deepcopy(lr))
    out = apply_rt_chain(rt, ar, zk, lr, True)
    rerun_chain(out.replay, {"rsh": np.full(n, 9.0)})
    np.testing.assert_array_equal(rt, snap[0])
    for k, v in snap[1].items():
        if isinstance(v, np.ndarray):
            np.testing.assert_array_equal(ar[k], v)
    assert ar["flags"] == snap[1]["flags"]
    np.testing.assert_array_equal(zk, snap[2])
    assert lr == snap[3]


def test_missing_required_array_is_an_error():
    ar = arrays(4)
    del ar["vsh"]
    with pytest.raises(ValueError):
        apply_rt_chain(rt_of(4), ar, zones_of(4), lrlc_for([]), False)
