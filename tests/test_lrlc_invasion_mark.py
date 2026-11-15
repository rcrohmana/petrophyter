"""The mark "the mapped RT is invasion corrected": service, guard rule, plan, summary, session 2.9."""
import copy
import json

import pytest

from modules.lrlc import chain
from modules.lrlc.chain import StepResult, StepSpec
from modules.lrlc.config import CURVE_MARKERS, GUARD_DEFAULTS, lrlc_l2_configured
from modules.lrlc.guard import blocked_text, evaluate_guard
from modules.lrlc.l2 import make_plan
from modules.pipeline import run_pipeline
from services.lrlc_service import LrlcService
from services.session_service import SessionService, session_version_for
from tests.golden.cases import build_case
from tests.test_session_v2 import three_wells, _save, _restore  # noqa: F401

G = dict(GUARD_DEFAULTS)


def _radial():
    return StepSpec(name="invasion", order=1, column="RT_INV",
                    fn=lambda rt, c, p: StepResult(rt, rt == rt), label="Radial invasion",
                    description="d", refs=(), kind="radial")


def _vert():
    return StepSpec(name="decon", order=0, column="RT_DECON",
                    fn=lambda rt, c, p: StepResult(rt, rt == rt), label="Deconvolution",
                    description="d", refs=(), kind="vertical")


def decide(specs, ic, enabled=True, zone="UPPER"):
    return evaluate_guard(zone, specs, None, zone_states={}, guard_settings=dict(G, enabled=enabled),
                          rt_ic_marked=ic)


# ---- the guard rule ------------------------------------------------------------------------
def test_guard_on_drops_the_radial_step_of_an_invasion_corrected_rt():
    dec = decide([_radial()], True)
    assert dec.specs_kept == [] and dec.blocked_steps == ["invasion"]
    assert dec.reasons == {"invasion": "invasion"}
    assert [(i[0], i[1]) for i in dec.issues] == [(
        "LRLC_GUARD_BLOCKED",
        "Radial invasion not applied in Zone UPPER: RT is marked invasion corrected (guard).")]
    assert blocked_text("Radial invasion", "Zone UPPER", "invasion") == dec.issues[0][1]


def test_guard_off_warns_and_keeps_the_step():
    dec = decide([_radial()], True, enabled=False)
    assert [s.name for s in dec.specs_kept] == ["invasion"] and dec.blocked_steps == []
    assert dec.warned_steps == ["invasion"]
    assert [(i[0], i[1]) for i in dec.issues] == [(
        "LRLC_GUARD_WARNED",
        "Radial invasion applied in Zone UPPER: RT is marked invasion corrected (guard off).")]


def test_without_the_mark_or_without_a_radial_step_nothing_happens():
    assert decide([_radial()], False).issues == []
    dec = decide([_vert()], True)               # only the radial step reads the invasion mark
    assert [s.name for s in dec.specs_kept] == ["decon"]
    assert not [i for i in dec.issues if i[0] in ("LRLC_GUARD_BLOCKED", "LRLC_GUARD_WARNED")]


# ---- the marker and the plan ---------------------------------------------------------------
def test_markers_and_the_service(three_wells):  # noqa: F811
    model, keys = three_wells
    assert CURVE_MARKERS == ("RT_SBC", "RT_IC")
    ds = model.project.get(keys[0])
    ds.curve_mapping["RT"] = "RT"
    assert LrlcService.set_rt_ic(model, ds, True) is True
    assert ds.lrlc_curves == {"RT_IC": "RT"} and model.dirty
    assert LrlcService.set_rt_ic(model, ds, True) is False
    assert LrlcService.set_rt_marker(model, ds, "RT_SBC", True) is True
    assert ds.lrlc_curves == {"RT_IC": "RT", "RT_SBC": "RT"}
    assert LrlcService.set_rt_ic(model, ds, False) is True and "RT_IC" not in ds.lrlc_curves
    assert LrlcService.set_rt_ic(model, ds, False) is False
    assert LrlcService.set_rt_marker(model, ds, "RT_XX", True) is False
    ds.curve_mapping["RT"] = None
    assert LrlcService.set_rt_ic(model, ds, True) is False


def test_the_plan_and_the_stale_hash_follow_the_mark(three_wells):  # noqa: F811
    model, keys = three_wells
    ds = model.project.get(keys[0])
    ds.curve_mapping["RT"] = "RT"
    LrlcService.set_enabled(model, True)
    lrlc = {"curves": {"RT_IC": "RT"}, "resolved": {"default": {"rt_steps": []}, "zones": {}},
            "thomas_stieber": {}}
    assert make_plan(lrlc, [None], "RT").rt_ic is True
    assert make_plan(lrlc, [None], "ILD").rt_ic is False
    assert make_plan({**lrlc, "curves": {}}, [None], "RT").rt_ic is False
    before = model.well_params_hash(ds)
    LrlcService.set_rt_ic(model, ds, True)
    assert model._lrlc_params(ds)["curves"]["RT_IC"] == "RT"
    assert model.well_params_hash(ds) != before


# ---- through the pipeline ------------------------------------------------------------------
def invasion_run(marked, guard=True):
    data, mapping, params, _ = build_case("lrlc_invasion")
    params = copy.deepcopy(params)
    lrlc = params["lrlc"]
    lrlc["resolved"]["default"] = {**lrlc["resolved"]["default"], "rt_steps": ["invasion"]}
    if marked:
        lrlc["curves"]["RT_IC"] = mapping.get("RT", "RT")
    if not guard:
        lrlc["guard"] = {"enabled": False}
    return run_pipeline(data.copy(), mapping, params)


def test_the_invasion_step_is_not_applied_on_a_marked_curve():
    r, s = invasion_run(True)
    assert "RT_INV" not in r.columns or r["RT_INV"].isna().all()
    texts = [i["text"] for i in s["issues"] if i["code"] == "LRLC_GUARD_BLOCKED"]
    assert texts and all("Radial invasion not applied in" in t
                         and t.endswith("RT is marked invasion corrected (guard).") for t in texts)
    inv = s["lrlc"]["invasion"]
    assert inv["zones"] == [] and inv["not_applied"]
    assert all(row["reason"] == "RT is marked invasion corrected" for row in inv["not_applied"])


def test_the_step_runs_and_warns_with_the_guard_off():
    r, s = invasion_run(True, guard=False)
    assert r["RT_INV"].notna().any()
    texts = [i["text"] for i in s["issues"] if i["code"] == "LRLC_GUARD_WARNED"]
    assert texts and all(t.endswith("RT is marked invasion corrected (guard off).") for t in texts)
    assert "not_applied" not in s["lrlc"]["invasion"]


def test_an_unmarked_run_is_unchanged():
    r, s = invasion_run(False)
    assert r["RT_INV"].notna().any()
    assert not [i for i in s["issues"] if i["code"] in ("LRLC_GUARD_BLOCKED", "LRLC_GUARD_WARNED")]
    assert "not_applied" not in s["lrlc"]["invasion"]


# ---- session format ------------------------------------------------------------------------
def test_session_version_constant():
    assert SessionService.SESSION_VERSION == "2.9"


def test_the_mark_is_written_as_2_9_and_round_trips(three_wells, tmp_path):  # noqa: F811
    model, keys = three_wells
    ds = model.project.get(keys[2])
    ds.curve_mapping["RT"] = "RT"
    assert LrlcService.set_rt_ic(model, ds, True)
    assert session_version_for(model) == "2.9" == session_version_for(model.project)
    assert not lrlc_l2_configured(model.project)        # the new mark is not a 2.6 setting
    path, saved = _save(model, tmp_path)
    assert saved["_session_version"] == "2.9"
    fresh, _, _ = _restore(path)
    assert fresh.project.get(keys[2]).lrlc_curves == {"RT_IC": "RT"}
    assert session_version_for(fresh) == "2.9"
    svc = SessionService()
    assert svc.load_session(path) is not None and svc.last_notice == ""


def test_a_session_without_the_mark_is_still_written_as_2_8(three_wells, tmp_path):  # noqa: F811
    model, keys = three_wells
    ds = model.project.get(keys[0])
    ds.curve_mapping["RT"] = "RT"
    LrlcService.set_param(model, "project", None, "dec_fwhm_ft", 5.0, None)    # a 2.8 setting
    LrlcService.set_rt_sbc(model, ds, True)
    assert session_version_for(model) == "2.8"
    _, saved = _save(model, tmp_path)
    assert saved["_session_version"] == "2.8"
    LrlcService.set_rt_ic(model, ds, True)
    LrlcService.set_rt_ic(model, ds, False)
    assert session_version_for(model) == "2.8"


def test_a_newer_format_notice_for_2_10(tmp_path):
    path = tmp_path / "v.json"
    path.write_text(json.dumps({"_session_version": "2.10", "rw": 0.1}))
    svc = SessionService()
    assert svc.load_session(str(path)) is not None and svc.last_notice
