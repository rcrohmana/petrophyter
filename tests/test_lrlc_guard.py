"""Shoulder-bed guard (modules/lrlc/guard.py): zone state and the rule engine."""

import functools

import numpy as np
import pytest

from modules.lrlc import chain
from modules.lrlc.chain import StepResult, StepSpec, apply_rt_chain
from modules.lrlc.config import GUARD_DEFAULTS
from modules.lrlc.guard import RESERVED_RULES, evaluate_guard, guard_summary, zone_state
from modules.lrlc.laminated import STEP as LAM
from modules.param_scopes import UNZONED

G = dict(GUARD_DEFAULTS)


def _vert():
    return StepSpec(name="decon", order=0, column="RT_INV",
                    fn=lambda rt, c, p: StepResult(rt * 2.0, np.isfinite(rt)),
                    label="decon", description="d", refs=(), kind="vertical")


def _radial():
    return StepSpec(name="invasion", order=1, column="RT_TRUE",
                    fn=lambda rt, c, p: StepResult(rt, np.isfinite(rt)),
                    label="inv", description="d", refs=(), kind="radial")


LAMINATED = {"laminated": True, "lam_share": 0.7, "mean_vlam": 0.2, "n": 50, "classified": True}
CLEAN = {"laminated": False, "lam_share": 0.1, "mean_vlam": 0.02, "n": 50, "classified": True}
NO_TS = zone_state(None, G)


def run(specs, state, zone="A", enabled=True, sbc=False):
    gs = dict(G, enabled=enabled)
    return evaluate_guard(zone, specs, None, zone_states={zone: state},
                          guard_settings=gs, rt_sbc_marked=sbc)


def codes(dec):
    return [i[0] for i in dec.issues]


# ------------------------------------------------------------- classification

def test_zone_state_thresholds():
    ok = zone_state({"lam_share": 0.5, "mean_vlam": 0.05, "n": 10}, G)
    assert ok["laminated"] and ok["classified"] and ok["n"] == 10
    assert not zone_state({"lam_share": 0.499, "mean_vlam": 0.5, "n": 10}, G)["laminated"]
    assert not zone_state({"lam_share": 0.9, "mean_vlam": 0.049, "n": 10}, G)["laminated"]
    custom = zone_state({"lam_share": 0.3, "mean_vlam": 0.2, "n": 10}, dict(G, vlam_share=0.25))
    assert custom["laminated"]


def test_zone_state_without_ts():
    for stats in (None, {}, {"lam_share": float("nan"), "mean_vlam": float("nan"), "n": 0}):
        st = zone_state(stats, G)
        assert st["classified"] is False and st["laminated"] is False
    assert set(NO_TS) == {"laminated", "lam_share", "mean_vlam", "n", "classified"}


# ------------------------------------------------------------------------ G1

def test_g1_drops_vertical_step_in_laminated_zone():
    keep, dec = _radial(), None
    v = _vert()
    dec = run([v, keep, LAM], LAMINATED)
    assert [s.name for s in dec.specs_kept] == ["invasion", "laminated"]
    assert dec.blocked_steps == ["decon"]
    assert dec.invalid_mask is None
    blocked = [i for i in dec.issues if i[0] == "LRLC_GUARD_BLOCKED"]
    assert len(blocked) == 1
    assert blocked[0][1] == ("decon not applied in Zone A: laminated (guard); "
                             "use the laminated-sand correction.")
    assert blocked[0][2] == "A"
    assert "LRLC_GUARD_HINT" not in codes(dec)


def test_g1_not_in_clean_zone():
    dec = run([_vert()], CLEAN)
    assert [s.name for s in dec.specs_kept] == ["decon"] and not dec.issues
    assert dec.blocked_steps == []


def test_guard_off_warns_only():
    dec = run([_vert(), LAM], LAMINATED, enabled=False)
    assert [s.name for s in dec.specs_kept] == ["decon", "laminated"]
    assert codes(dec) == ["LRLC_GUARD_WARNED"]
    assert "(guard off)" in dec.issues[0][1]
    assert dec.blocked_steps == []
    # no hint when off
    assert "LRLC_GUARD_HINT" not in codes(run([], LAMINATED, enabled=False))


def test_unzoned_label():
    dec = run([_vert()], LAMINATED, zone=UNZONED)
    assert dec.issues[0][2] is None
    assert "the unzoned interval" in dec.issues[0][1]


# ------------------------------------------------------------------------ G2

def test_g2_marked_rt_with_laminated_keeps_everything():
    dec = run([LAM], LAMINATED, sbc=True)
    assert [s.name for s in dec.specs_kept] == ["laminated"]
    assert dec.invalid_mask is None and dec.sbc_rt is True
    assert codes(dec) == ["LRLC_GUARD_SBC_RT"]
    assert "shoulder-bed corrected in Zone A" in dec.issues[0][1]
    assert "(guard off)" not in dec.issues[0][1]
    off = run([LAM], LAMINATED, sbc=True, enabled=False)
    assert codes(off) == ["LRLC_GUARD_SBC_RT"] and "(guard off)" in off.issues[0][1]
    assert off.sbc_rt is True and off.invalid_mask is None


def test_g2_needs_laminated_step_and_laminated_zone():
    assert "LRLC_GUARD_SBC_RT" not in codes(run([], LAMINATED, sbc=True))
    assert not run([LAM], CLEAN, sbc=True).sbc_rt
    assert not run([LAM], LAMINATED, sbc=False).sbc_rt


def test_g2_through_chain_no_nan_no_mask(monkeypatch):
    monkeypatch.setitem(chain.STEPS, "laminated", LAM)
    n = 6
    rt = np.array([5.0, 5.5, 6.0, 4.0, 3.0, 2.5])
    zones = np.array([UNZONED] * n, dtype=object)
    ca = {"depth": np.arange(n, dtype=float), "vsh": np.full(n, 0.3), "phit": np.full(n, 0.25),
          "phie": np.full(n, 0.22), "rsh": np.full(n, 2.0), "rw": np.full(n, 0.1),
          "derived": {"VLAM": np.full(n, 0.3)}}
    lrlc = {"resolved": {"default": {"rt_steps": ["laminated"], "rt_fallback": "nan",
                                     "vlam_source": "ts", "vlam_const": 0.0,
                                     "hag_vsh_max": 0.8, "s_warn": 0.8, "s_invalid": 0.95},
                         "zones": {}}}
    guard = functools.partial(evaluate_guard, zone_states={UNZONED: LAMINATED},
                              guard_settings=G, rt_sbc_marked=True)
    out = apply_rt_chain(rt, ca, zones, lrlc, False, guard=guard)
    base = apply_rt_chain(rt, ca, zones, lrlc, False)
    np.testing.assert_array_equal(out.rt_sw, base.rt_sw)
    assert np.isfinite(out.rt_sw).all()
    assert out.guard_masked == {}
    assert any(i[0] == "LRLC_GUARD_SBC_RT" for i in out.issues)


# ----------------------------------------------------------------- hint, no TS

def test_hint_for_laminated_zone_without_step():
    dec = run([], LAMINATED)
    assert codes(dec) == ["LRLC_GUARD_HINT"]
    assert dec.issues[0][1] == ("Zone A is laminated by Thomas-Stieber; consider the "
                                "laminated-sand Rt (Hagiwara).")
    assert "LRLC_GUARD_HINT" not in codes(run([LAM], LAMINATED))
    assert run([], CLEAN).issues == []


def test_no_ts_blocks_nothing():
    dec = run([_vert(), LAM], NO_TS, sbc=True)
    assert [s.name for s in dec.specs_kept] == ["decon", "laminated"]
    assert codes(dec) == ["LRLC_GUARD_NO_TS"]
    assert dec.invalid_mask is None and dec.blocked_steps == [] and not dec.sbc_rt
    # zone missing from zone_states altogether
    d2 = evaluate_guard("Z", [_vert()], None, zone_states={}, guard_settings=G,
                        rt_sbc_marked=False)
    assert codes(d2) == ["LRLC_GUARD_NO_TS"] and len(d2.specs_kept) == 1
    # guard off: silent
    assert run([_vert()], NO_TS, enabled=False).issues == []


def test_kinds_come_from_stepspec_kind():
    dec = run([_radial(), LAM], LAMINATED)
    assert [s.name for s in dec.specs_kept] == ["invasion", "laminated"]
    renamed = StepSpec(name="whatever", order=0, column="RT_W",
                       fn=lambda rt, c, p: StepResult(rt, np.isfinite(rt)),
                       label="w", description="d", refs=(), kind="vertical")
    assert run([renamed], LAMINATED).blocked_steps == ["whatever"]


def test_partial_binding_and_input_untouched():
    specs = [_vert(), LAM]
    bound = functools.partial(evaluate_guard, zone_states={"A": LAMINATED},
                              guard_settings=G, rt_sbc_marked=False)
    dec = bound("A", specs, None)
    assert len(specs) == 2 and len(dec.specs_kept) == 1


# --------------------------------------------------------------------- G3, summary

def test_g3_is_reserved():
    assert "G3" in RESERVED_RULES
    # decon + laminated in a non-laminated zone: nothing happens
    dec = run([_vert(), LAM], CLEAN)
    assert [s.name for s in dec.specs_kept] == ["decon", "laminated"] and not dec.issues


def test_guard_summary_shape():
    states = {"A": LAMINATED, "B": CLEAN, UNZONED: NO_TS}
    decs = {"A": run([_vert(), LAM], LAMINATED, sbc=True), "B": run([], CLEAN)}
    s = guard_summary(states, decs)
    assert s["enabled"] is True
    by = {z["zone"]: z for z in s["zones"]}
    assert set(by) == {"A", "B", None}
    assert by["A"] == {"zone": "A", "laminated": True, "lam_share": 0.7,
                       "blocked_steps": ["decon"], "sbc_rt": True}
    assert by["B"]["blocked_steps"] == [] and by["B"]["sbc_rt"] is False
    assert by[None]["laminated"] is False
    assert guard_summary(states, decs, enabled=False)["enabled"] is False
