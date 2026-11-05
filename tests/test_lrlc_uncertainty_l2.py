"""Monte Carlo with laminated sands, pyrite and estimated Qv: parity with the deterministic run."""
import numpy as np
import pytest

from modules import uncertainty as U
from modules.lrlc import chain
from modules.lrlc.chain import StepResult, StepSpec, rerun_chain
from modules.pipeline import run_pipeline
from tests.golden.cases import build_case
from tests.test_lrlc_pipeline import lrlc_p
from tests.test_lrlc_pipeline_l2 import MAPPING, PARAMS, laminated_well, ts_p

PARITY = ("hcpv_net_pay", "hcpv_net_res", "net_pay", "avg_phie_pay", "avg_sw_pay")


def close(a, b, **kw):
    np.testing.assert_allclose(a, b, rtol=1e-12, atol=0, equal_nan=True, **kw)


def lam_case(steps=("laminated",), pyrite=False, qv=False, **over):
    frame, _ = laminated_well()
    mapping = dict(MAPPING)
    lrlc = ts_p(steps=steps)
    params = {**PARAMS, **over}
    if pyrite:
        frame["PEF"] = 2.0 + 0.4 * np.sin(frame["DEPTH"] / 5.0)
        mapping["PEF"] = "PEF"
        lrlc["curves"]["PEF"] = "PEF"
        lrlc["resolved"]["default"].update(pyr_method="rhob_pef", pyr_f=0.5, pyr_rpy=0.1)
        lrlc["pyrite"] = {"enabled": True, "u_fluid": 0.36}
    if qv:
        lrlc["resolved"]["default"]["qv_source"] = "estimate"
        params["sw_methods"] = ["Archie", "Waxman-Smits"]
        params["sw_primary_method"] = "Waxman-Smits"
    params["lrlc"] = lrlc
    return frame, mapping, params


def freeze(case):
    frame, mapping, params = case
    return U.freeze_well("w", "w", frame.copy(), mapping, params, None)


def det_summary(case, **over):
    frame, mapping, params = case
    return run_pipeline(frame.copy(), dict(mapping), {**params, **over})[1]


def test_theta_zero_matches_laminated_and_pyrite():
    case = lam_case(steps=("pyrite", "laminated"), pyrite=True, qv=True)
    fw = freeze(case)
    assert any(seg.chain_replay is not None for seg in fw.segments)
    assert any(seg.sand_basis is not None for seg in fw.segments)
    assert any(seg.qv_values is not None for seg in fw.segments)
    got = U.evaluate(fw, {})
    for k in PARITY:
        close(got["well"][k], fw.base_summary[k], err_msg=k)


def test_theta_zero_matches_with_shf_pay():
    data, mapping, params, tops = build_case("shf_core_pc")
    params = {**params, "rsh": 3.0, "rsh_mode": "manual", "lrlc": ts_p(steps=("laminated",))}
    fw = U.freeze_well("s", "s", data, mapping, params, tops)
    assert any(seg.sw_hold is not None for seg in fw.segments)
    got = U.evaluate(fw, {})
    for k in PARITY:
        close(got["well"][k], fw.base_summary[k], err_msg=k)


def test_rsh_offset_equals_deterministic_run_at_perturbed_rsh():
    case = lam_case(steps=("laminated",), pyrite=True)
    fw = freeze(case)
    modes = {"rsh": "additive"}
    got = U.evaluate(fw, {"rsh": 0.7}, modes)
    base = U.evaluate(fw, {})
    assert got["well"]["avg_sw_pay"] != base["well"]["avg_sw_pay"] or \
        got["well"]["hcpv_net_pay"] != base["well"]["hcpv_net_pay"]
    ref = det_summary(case, rsh=PARAMS["rsh"] + 0.7)
    for k in PARITY:
        close(got["well"][k], ref[k], err_msg=k)


def test_rw_offset_equals_deterministic_run_at_perturbed_rw():
    case = lam_case(steps=("laminated",))
    fw = freeze(case)
    got = U.evaluate(fw, {"rw": 0.005}, {"rw": "additive"})
    ref = det_summary(case, rw=PARAMS["rw"] + 0.005)
    for k in PARITY:
        close(got["well"][k], ref[k], err_msg=k)


def test_auto_rsh_with_arps_matches_a_direct_chain_replay():
    frame, mapping, params = lam_case(steps=("laminated",), rsh_mode="auto",
                                      temp_correction=True, surface_temp=80.0, temp_gradient=1.5)
    frame.loc[frame.index[-20:], ["GR", "RT", "RHOB"]] = [118.0, 2.2, 2.45]   # a shale interval
    case = (frame, mapping, params)
    fw = freeze(case)
    seg = fw.segments[0]
    assert seg.rsh_auto and seg.chain_replay is not None
    theta = {"rsh": 0.2}
    got = U.evaluate(fw, theta, {"rsh": "relative"})
    sp = seg.params
    rsh = seg.rsh * 1.2
    eff = U._sw_effective_inputs(sp, seg.rw, rsh, seg.rsh_auto, seg.tctx, seg.data)
    rt = rerun_chain(seg.chain_replay, {"rsh": eff.rsh, "rw": eff.rw})
    sw = U._primary_sw_values(seg, fw.curve_mapping, sp, seg.rw, rsh, U.IssueLog(),
                              rt_values=rt, qv_values=seg.qv_values, basis=seg.sand_basis)
    g = seg.vsh < sp["vsh_cutoff"]
    r = g & (seg.phie > sp["phi_cutoff"])
    pay = r & (sw < sp["sw_cutoff"])
    assert got["well"]["net_pay"] == pytest.approx(float(np.sum(pay * fw.dz)), rel=1e-12)
    assert not np.array_equal(rt, seg.rt_sw)


def test_replay_starts_at_the_laminated_step(monkeypatch):
    calls = []

    def before(rt, ctx, prm):
        calls.append(1)
        return StepResult(2.0 * rt, np.isfinite(rt), {}, {}, ())

    spec = StepSpec(name="test_before", order=0, column="RT_BEFORE", fn=before,
                    label="test_before", description="test step", refs=())
    monkeypatch.setitem(chain.STEPS, "test_before", spec)
    frame, mapping, params = lam_case(steps=("test_before", "laminated"))
    fw = U.freeze_well("w", "w", frame.copy(), mapping, params, None)
    assert calls
    calls.clear()
    U.evaluate(fw, {"rsh": 0.5}, {"rsh": "additive"})
    assert not calls                       # the frozen earlier step is not re-run
    ref = run_pipeline(frame.copy(), dict(mapping), {**params, "rsh": PARAMS["rsh"] + 0.5})[1]
    got = U.evaluate(fw, {"rsh": 0.5}, {"rsh": "additive"})
    for k in PARITY:
        close(got["well"][k], ref[k], err_msg=k)


def test_not_varied_text_lists_lrlc_items_only_when_relevant():
    assert U.not_varied_text() == U.NOT_VARIED
    assert U.not_varied_text(False, ()) == U.NOT_VARIED
    full = U.not_varied_text(True, ("Thomas-Stieber Vlam", "estimated Qv"))
    assert full == (U.NOT_VARIED + ", SHF Sw where used for pay, "
                    "Thomas-Stieber Vlam, estimated Qv")

    plain = U.freeze_well("p", "p", *build_case("lrlc_screening")[:3],
                          build_case("lrlc_screening")[3])
    assert U.lrlc_not_varied([plain]) == ((), False)

    fw = freeze(lam_case(steps=("pyrite", "laminated"), pyrite=True, qv=True))
    items, laminated = U.lrlc_not_varied([fw])
    assert laminated
    assert items == ("Thomas-Stieber Vlam", "pyrite volume and correction", "estimated Qv")

    pyr_only = freeze(lam_case(steps=("pyrite",), pyrite=True))
    items, laminated = U.lrlc_not_varied([pyr_only])
    assert not laminated and items == ("pyrite volume and correction",)


def test_result_and_export_header_state_the_rsh_note():
    from services.export_service import uncertainty_header_frame

    fw = freeze(lam_case(steps=("laminated",), pyrite=False, qv=True))
    cfg = U.UncertaintyConfig(
        n=50, seed=1,
        distributions={**U.default_distributions(), "rsh": U.Distribution(
            name="rsh", enabled=True, kind="uniform", mode="relative", low=-0.2, high=0.2)})
    res = U.run_monte_carlo([fw], cfg)
    assert res.lrlc_laminated and "estimated Qv" in res.lrlc_items
    assert U.RSH_LAMINATED_NOTE in res.warnings
    frame = uncertainty_header_frame(res, False)
    items = dict(zip(frame["Item"], frame["Value"]))
    assert items["Rsh"] == U.RSH_LAMINATED_NOTE
    assert "Thomas-Stieber Vlam" in items["Not varied"]
