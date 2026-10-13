"""U1: ``run_pipeline(capture=...)`` and ``_primary_sw`` (P2 uncertainty basis)."""

import numpy as np
import pandas as pd
import pytest

from modules import param_scopes as ps
from modules.petrophysics import PetrophysicsCalculator
from modules.pipeline import (
    PARAM_DEFAULTS, SW_DEFAULTED, SegmentBasis, _compute_porosity, _compute_vsh, _primary_sw,
    run_pipeline,
)
from modules.issue_codes import IssueLog
from modules.statistics_utils import StatisticsUtils
from tests.golden.cases import CASES, build_case

ZONED = ("per_formation_lower", "rock_typing_enabled")


def _plan(params):
    """A project-zone m override for LOWER, so LOWER runs as its own segment."""
    return ps.zone_plan({**PARAM_DEFAULTS, **params}, None,
                        {"LOWER": {"m": ps.make_entry(ps.MANUAL, 1.8)}}, None, ("UPPER", "LOWER"))


def _case(name, zoned=False):
    data, mapping, params, tops = build_case(name)
    if zoned:
        params = {**params, "zone_plan": _plan(params)}
    return data, mapping, params, tops


def _run(name, zoned=False, capture=None):
    data, mapping, params, tops = _case(name, zoned)
    return run_pipeline(data, mapping, params, formation_tops=tops, capture=capture)


def _assert_same(a, b):
    pd.testing.assert_frame_equal(a[0], b[0])
    assert repr(a[1]) == repr(b[1])


@pytest.mark.parametrize("name", sorted(CASES))
def test_capture_changes_nothing_and_positions_do_not_overlap(name):
    plain = _run(name)
    capture = []
    captured = _run(name, capture=capture)
    _assert_same(plain, captured)
    assert capture and all(isinstance(b, SegmentBasis) for b in capture)
    positions = np.concatenate([b.positions for b in capture])
    assert len(np.unique(positions)) == len(positions)
    n = len(plain[0])
    assert len(positions) == n          # unzoned: one segment over the whole well
    for b in capture:
        assert len(b.vsh) == len(b.phie) == len(b.phit) == len(b.positions)
        assert b.params["rw"] == b.rw


@pytest.mark.parametrize("name", ZONED)
def test_zoned_capture_one_basis_per_planned_zone_plus_rest(name):
    plain = _run(name, zoned=True)
    capture = []
    results, summary = _run(name, zoned=True, capture=capture)
    _assert_same(plain, (results, summary))

    planned = [row["zone"] for row in summary["zones"]
               if row["zone"] in _plan(build_case(name)[2])]
    assert planned == ["LOWER"]
    planned_bases = [b for b in capture if b.zone is not None]
    assert [b.zone for b in planned_bases] == planned
    rest = [b for b in capture if b.zone is None]
    n_rest = int((results["ZONE"] != "LOWER").sum())
    assert len(rest) == (1 if n_rest else 0)
    assert len(capture) == len(planned) + len(rest)

    positions = np.concatenate([b.positions for b in capture])
    assert len(np.unique(positions)) == len(positions) == len(results)
    for b in planned_bases:
        assert (results["ZONE"].to_numpy()[b.positions] == b.zone).all()
        assert b.params["rw"] == summary["param_sources"][b.zone]["rw"]["value"]
        assert b.params["m"] == 1.8
        assert b.params["rw_mode"] == b.params["rsh_mode"] == "manual"
    for b in rest:
        assert b.rw == summary["rw"] and b.rsh == summary["rsh"]
        assert (results["ZONE"].to_numpy()[b.positions] != "LOWER").all()


def test_unzoned_basis_matches_summary():
    capture = []
    _, summary = _run("shaly_manual_baseline", capture=capture)
    (basis,) = capture
    assert basis.zone is None and basis.has_rt
    assert basis.params["rw"] == summary["rw"] == basis.rw
    assert basis.rsh == summary["rsh"]
    assert basis.rw_quality == summary.get("rw_quality")
    assert basis.sw_fallback is None


def test_no_rt_has_rt_false():
    capture = []
    results, _ = _run("no_rt_no_dt", capture=capture)
    (basis,) = capture
    assert basis.has_rt is False
    assert "SW" not in results.columns


def test_capture_copies_do_not_alias_calculator_results():
    capture = []
    _run("defaults_whole_well", capture=capture)
    (basis,) = capture
    assert isinstance(basis.vsh, np.ndarray) and isinstance(basis.positions, np.ndarray)
    assert basis.positions.dtype.kind == "i"


# ---- _primary_sw --------------------------------------------------------
def _prepared(name, **override):
    data, mapping, params, _ = build_case(name)
    p = {**PARAM_DEFAULTS, **params, **override}
    warnings = IssueLog()

    def fresh():
        calc = PetrophysicsCalculator(data)
        vsh, _, _ = _compute_vsh(calc, StatisticsUtils(data), data, mapping, p, warnings)
        _compute_porosity(calc, vsh, data, mapping, p, warnings)
        return calc, vsh

    return data, mapping, p, fresh


def _both(name, **override):
    data, mapping, p, fresh = _prepared(name, **override)
    out = []
    for only in (False, True):
        calc, vsh = fresh()
        w = IssueLog()
        out.append((_primary_sw(calc, data, mapping, p, vsh, p["rw"], p["rsh"], None, w,
                                only_primary=only), calc, list(w)))
    return out


@pytest.mark.parametrize("name", sorted(CASES))
def test_only_primary_sw_equals_full_path(name):
    (full, calc_full, w_full), (fast, calc_fast, w_fast) = _both(name)
    if full[0] is None:
        assert fast[0] is None and "SW" not in calc_fast.results.columns
        return
    pd.testing.assert_series_equal(full[0], fast[0])
    assert full[3] == fast[3]
    assert w_full == w_fast
    pd.testing.assert_series_equal(full[1], fast[1])
    pd.testing.assert_series_equal(full[2], fast[2])
    # only the chosen column was computed
    sw_cols = [c for c in calc_fast.results.columns if c.startswith("SW_")]
    assert len(sw_cols) == 1


def test_only_primary_fallback_when_primary_not_selected():
    (full, _, _), (fast, calc_fast, _) = _both(
        "gas_all_sw_models", sw_methods=["Indonesian", "Archie"], sw_primary_method="Dual-Water")
    pd.testing.assert_series_equal(full[0], fast[0])
    assert full[3] == fast[3] == "SW_ARCHIE"      # SW_COLUMN_MAP order, not selection order
    assert [c for c in calc_fast.results.columns if c.startswith("SW_")] == ["SW_ARCHIE"]


def test_only_primary_no_method_defaults_to_one():
    (full, _, w_full), (fast, _, w_fast) = _both("defaults_whole_well", sw_methods=[])
    assert (full[0] == 1.0).all() and (fast[0] == 1.0).all()
    assert full[3] == fast[3] == SW_DEFAULTED
    assert w_full == w_fast and len(w_full) == 1
