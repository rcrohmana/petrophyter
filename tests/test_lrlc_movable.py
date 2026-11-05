"""BVW, WATER_FREE_FLAG and the per-zone movable rows."""

import numpy as np
import pytest

from modules.lrlc.movable import bvw, movable_zone_rows, water_free_flag


def test_bvw():
    out = bvw([0.2, np.nan, 0.1], [0.5, 0.5, np.nan])
    assert out[0] == pytest.approx(0.1) and np.isnan(out[1:]).all()


def test_water_free_rule_and_tolerance():
    res = [1, 1, 1, 0, 1, 1]
    sw = [0.30, 0.34, 0.36, 0.20, np.nan, 0.30]
    swirr = [0.30, 0.30, 0.30, 0.30, 0.30, np.nan]
    flag, missing = water_free_flag(res, sw, swirr, 0.05)
    assert list(flag) == [1, 1, 0, 0, 0, 0]
    assert missing == 1                      # only net-res sample 5 lacks Swirr
    flag0, _ = water_free_flag(res, sw, swirr, 0.0)
    assert list(flag0) == [1, 0, 0, 0, 0, 0]
    assert flag.dtype.kind == "i"


def test_missing_counts_only_net_res():
    flag, missing = water_free_flag([0, 0, 1], [0.3] * 3, [np.nan] * 3, 0.05)
    assert missing == 1 and flag.sum() == 0


def test_zone_rows():
    labels = ["A", "A", "A", "B", "B"]
    res = [1, 1, 0, 1, 1]
    wf = [1, 0, 0, 0, 0]
    phie = np.array([0.2, 0.2, 0.2, 0.1, 0.1])
    sw = np.array([0.3, 0.5, 0.9, 1.0, 1.0])
    swirr = np.array([0.3, 0.3, 0.3, 0.4, 0.4])
    dz = np.array([1.0, 3.0, 1.0, 2.0, 2.0])
    rows = movable_zone_rows(labels, res, wf, bvw(phie, sw), dz, sw=sw, swirr=swirr)
    a, b = rows
    assert a["zone"] == "A" and a["n"] == 2
    assert a["water_free_ft"] == 1.0 and a["net_res_ft"] == 4.0
    assert a["pct"] == pytest.approx(25.0)
    assert a["avg_bvw"] == pytest.approx((0.06 * 1 + 0.10 * 3) / 4)
    assert a["avg_movable_sw"] == pytest.approx((0.0 * 1 + 0.2 * 3) / 4)
    assert b["water_free_ft"] == 0.0 and b["pct"] == 0.0


def test_zone_rows_single_well_and_no_net_res():
    rows = movable_zone_rows(None, [0, 0], [0, 0], [0.1, 0.1], 1.0)
    assert rows[0]["zone"] == "WELL"
    assert np.isnan(rows[0]["pct"]) and np.isnan(rows[0]["avg_bvw"])
