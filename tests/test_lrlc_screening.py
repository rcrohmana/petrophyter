"""LRLC screening criteria, score/flag rules, zone table, and the shipped-method refs map."""

import inspect

import numpy as np
import pytest

from modules.lrlc import SHIPPED_METHODS, movable, pickett, rt_cutoff, screening
from modules.lrlc.screening import (CRITERIA, RS_SEPARATION_MIN, criteria_counts, screen,
                                    unavailable_criteria, zone_table)

KW = dict(screen_rt_max=5.0, screen_contrast_max=3.0, screen_min_score=4, phi_cutoff=0.1,
          vsh_cutoff=0.4, sw_cutoff=0.6)


def _one(rt=3.0, rs=None, gas=None, phie=0.2, vsh=0.2, rsh=2.0, sw=0.9, **over):
    kw = dict(KW)
    kw.update(over)
    return screen(np.array([rt]), None if rs is None else np.array([rs]),
                  None if gas is None else np.array([gas]), np.array([phie]), np.array([vsh]),
                  rsh, np.array([sw]), **kw)


def test_constant():
    assert RS_SEPARATION_MIN == 1.0


def test_each_criterion():
    r = _one(rt=3.0)
    assert r.met["LOW_RT"][0] and not _one(rt=5.0).met["LOW_RT"][0]            # strict <
    assert r.met["PHI"][0] and not _one(phie=0.1).met["PHI"][0]                # strict >
    assert r.met["VSH"][0] and not _one(vsh=0.4).met["VSH"][0]                 # strict <
    assert r.met["SW_HIGH"][0] and _one(sw=0.6).met["SW_HIGH"][0]              # >=
    assert not _one(sw=0.59).met["SW_HIGH"][0]
    assert _one(rt=3.0, rsh=1.0).met["CONTRAST"][0]                            # 3 <= 3
    assert not _one(rt=4.0, rsh=1.0).met["CONTRAST"][0]


def test_hc_paths():
    assert not _one().evaluable["HC"][0]
    assert _one(gas=1).met["HC"][0] and _one(gas=1).evaluable["HC"][0]
    g0 = _one(gas=0)
    assert g0.evaluable["HC"][0] and not g0.met["HC"][0]
    assert _one(rt=3.0, rs=3.0).met["HC"][0]                                   # ratio 1
    assert _one(rt=3.0, rs=2.0).met["HC"][0]
    rs_water = _one(rt=3.0, rs=6.0)
    assert rs_water.evaluable["HC"][0] and not rs_water.met["HC"][0]
    assert not _one(rt=3.0, rs=-1.0).evaluable["HC"][0]
    assert not _one(gas=1, use_gas_flag=False).evaluable["HC"][0]
    assert not _one(rt=3.0, rs=2.0, use_rs=False).evaluable["HC"][0]
    assert _one(rt=3.0, rs=6.0, gas=1).met["HC"][0]                            # either route


def test_evaluability():
    r = _one(phie=np.nan, vsh=np.nan, sw=np.nan, rsh=np.nan)
    for name in ("PHI", "VSH", "SW_HIGH", "CONTRAST"):
        assert not r.evaluable[name][0] and not r.met[name][0]
    assert not _one(rsh=0.0).evaluable["CONTRAST"][0]


def test_score_and_flag_full():
    r = _one(gas=1)
    assert r.score[0] == 6 and r.flag[0] == 1
    assert r.score.dtype.kind == "i" and r.flag.dtype.kind == "i"


def test_core_required():
    # score 5 but the core Sw criterion fails
    r = _one(gas=1, sw=0.3)
    assert r.score[0] == 5 and r.flag[0] == 0
    assert _one(gas=1, phie=0.05).flag[0] == 0
    assert _one(gas=1, rt=9.0).flag[0] == 0


def test_min_score_cap():
    # no HC info: only 5 evaluable; min_score 6 is capped at n_eval
    r = _one(screen_min_score=6)
    assert r.score[0] == 5 and r.flag[0] == 1
    # a supporting criterion fails and the score is below the cap
    r = _one(vsh=0.9, rsh=0.1, screen_min_score=5)
    assert r.score[0] == 3 and r.flag[0] == 0
    assert _one(vsh=0.9, rsh=0.1, screen_min_score=3).flag[0] == 1
    assert _one(vsh=0.9, rsh=0.1, screen_min_score=0).flag[0] == 1


def test_core_must_be_evaluable():
    assert _one(sw=np.nan, screen_min_score=0).flag[0] == 0


def test_rt_nan_gives_zero():
    r = _one(rt=np.nan, rs=1.0, gas=1)
    assert r.score[0] == 0 and r.flag[0] == 0
    assert not any(r.met[name][0] for name in CRITERIA)


def test_array_cutoffs_and_vectors():
    rt = np.array([3.0, 3.0, 8.0])
    phie = np.array([0.2, 0.2, 0.2])
    r = screen(rt, None, None, phie, np.full(3, 0.2), np.array([2.0, 2.0, 2.0]),
               np.array([0.9, 0.9, 0.9]), screen_rt_max=np.array([5.0, 2.0, 10.0]),
               screen_contrast_max=3.0, screen_min_score=3, phi_cutoff=0.1, vsh_cutoff=0.4,
               sw_cutoff=0.6)
    assert list(r.flag) == [1, 0, 1]


def test_counts_and_unavailable():
    rt = np.array([3.0, 3.0])
    r = screen(rt, None, None, np.array([0.2, 0.2]), np.array([0.2, 0.2]), 2.0,
               np.array([0.9, np.nan]), **KW)
    counts = criteria_counts(r)
    assert counts["SW_HIGH"] == {"met": 1, "evaluable": 1}
    assert counts["LOW_RT"] == {"met": 2, "evaluable": 2}
    assert unavailable_criteria(r) == ["HC"]
    r2 = screen(rt, rt, None, np.array([0.2, 0.2]), np.array([0.2, 0.2]), 2.0,
                np.array([np.nan, np.nan]), **KW)
    assert unavailable_criteria(r2) == ["SW_HIGH"]


def test_zone_table():
    flag = [1, 1, 0, 1, 0]
    pay = [1, 0, 0, 0, 0]
    res = [1, 1, 1, 1, 0]
    dz = [1.0, 3.0, 1.0, 2.0, 2.0]
    phie = [0.2, 0.1, 0.3, 0.15, 0.2]
    vsh = [0.1, 0.3, 0.1, 0.2, 0.1]
    sw = [0.5, 0.9, 0.5, 0.8, 0.5]
    rt = [4.0, 2.0, 9.0, 3.0, 9.0]
    labels = ["A", "A", "A", "B", "B"]
    rows = zone_table(flag, pay, res, dz, phie, vsh, sw, rt, labels, rt_cut={"A": 6.5})
    a, b = rows
    assert a["zone"] == "A" and a["n"] == 3
    assert a["candidate_ft"] == 4.0 and a["candidate_not_pay_ft"] == 3.0
    assert a["net_res_ft"] == 5.0 and a["pct_of_net_res"] == pytest.approx(80.0)
    assert a["avg_phie"] == pytest.approx((0.2 * 1 + 0.1 * 3) / 4)
    assert a["avg_rt"] == pytest.approx((4.0 + 2.0 * 3) / 4)
    assert a["rt_cut"] == 6.5 and np.isnan(b["rt_cut"])
    assert b["candidate_ft"] == 2.0 and b["avg_sw"] == pytest.approx(0.8)


def test_zone_table_no_labels_and_no_candidates():
    rows = zone_table([0, 0], [0, 0], [0, 0], [1.0, 1.0], [0.2, 0.2], [0.1, 0.1],
                      [0.5, 0.5], [3.0, 3.0])
    assert len(rows) == 1 and rows[0]["zone"] == "WELL"
    assert rows[0]["candidate_ft"] == 0.0 and np.isnan(rows[0]["avg_phie"])
    assert np.isnan(rows[0]["pct_of_net_res"])


# ---------------------------------------------------------------------------
# Shipped-method reference map
# ---------------------------------------------------------------------------

def _public_functions(module):
    return {name: fn for name, fn in inspect.getmembers(module, inspect.isfunction)
            if not name.startswith("_") and fn.__module__ == module.__name__}


@pytest.mark.parametrize("module", [screening, rt_cutoff, movable, pickett])
def test_public_functions_carry_refs(module):
    fns = _public_functions(module)
    assert fns
    for name, fn in fns.items():
        refs = getattr(fn, "refs", None)
        assert isinstance(refs, tuple) and refs, f"{module.__name__}.{name} has no refs"


def _union(module):
    out = set()
    for fn in _public_functions(module).values():
        out |= set(fn.refs)
    return out


def test_refs_union_equals_shipped_methods():
    assert _union(screening) == set(SHIPPED_METHODS["screening"])
    assert _union(rt_cutoff) == set(SHIPPED_METHODS["rt_cutoff"])
    assert _union(pickett) == set(SHIPPED_METHODS["pickett"])
    assert _union(movable) == set(SHIPPED_METHODS["bvw"]) == set(SHIPPED_METHODS["buckles"])
    assert movable.bvw.refs == tuple(SHIPPED_METHODS["bvw"])
    assert movable.water_free_flag.refs == tuple(SHIPPED_METHODS["buckles"])
