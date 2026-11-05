"""Monte Carlo parity with the LRLC Rt chain (spec 4.8 cases a-d)."""
import numpy as np
import pytest

from modules import param_scopes as ps
from modules import uncertainty as U
from modules.pipeline import PARAM_DEFAULTS, run_pipeline
from tests.golden.cases import build_case
from tests.lrlc_teststeps import CALLS, register_test_steps  # noqa: F401
from tests.test_lrlc_pipeline import lrlc_p

PARITY = ("hcpv_net_pay", "hcpv_net_res", "net_pay", "avg_phie_pay", "avg_sw_pay")


def assert_parity(fw):
    got = U.evaluate(fw, {})
    s = fw.base_summary
    for k in PARITY:
        np.testing.assert_allclose(got["well"][k], s[k], rtol=1e-12, atol=0, equal_nan=True,
                                   err_msg=k)
    for row in s["zones"]:
        for k in ("hcpv_net_pay", "net_pay", "avg_phie_pay", "avg_sw_pay"):
            np.testing.assert_allclose(got["zones"][row["zone"]][k], row[k], rtol=1e-12, atol=0,
                                       equal_nan=True, err_msg=f"{row['zone']}:{k}")


def case_params(lrlc=None, rsh=3.0, plan=False):
    data, mapping, params, tops = build_case("lrlc_screening")
    params = {**params, "rsh": rsh}
    params.pop("lrlc")
    if lrlc is not None:
        params["lrlc"] = lrlc
    if plan:
        params["zone_plan"] = ps.zone_plan(
            {**PARAM_DEFAULTS, **params}, None,
            {"LOWER": {"m": ps.make_entry(ps.MANUAL, 1.8)}}, None, ("UPPER", "LOWER"))
    return data, mapping, params, tops


def freeze(**kw):
    data, mapping, params, tops = case_params(**kw)
    return U.freeze_well("w", "w", data, mapping, params, tops), (data, mapping, params, tops)


@pytest.mark.parametrize("plan", [False, True])
def test_a_no_lrlc(plan):
    fw, _ = freeze(plan=plan)
    assert all(seg.rt_sw is None and seg.chain_replay is None for seg in fw.segments)
    assert_parity(fw)


@pytest.mark.parametrize("plan", [False, True])
def test_b_lrlc_on_without_step(plan):
    fw, _ = freeze(lrlc=lrlc_p(rt_cutoff=True), plan=plan)
    assert all(seg.rt_sw is None and seg.chain_replay is None for seg in fw.segments)
    assert_parity(fw)
    off, _ = freeze(plan=plan)
    for k in PARITY:
        assert fw.base_summary[k] == off.base_summary[k]


@pytest.mark.parametrize("plan", [False, True])
def test_c_identity_step(register_test_steps, plan):
    fw, _ = freeze(lrlc=lrlc_p(steps=["test_identity"]), plan=plan)
    assert all(seg.rt_sw is not None and seg.chain_replay is None for seg in fw.segments)
    assert_parity(fw)
    off, _ = freeze(plan=plan)
    for k in PARITY:
        assert fw.base_summary[k] == off.base_summary[k]


@pytest.mark.parametrize("plan", [False, True])
def test_c_frozen_chain_is_not_rerun_per_realisation(register_test_steps, plan):
    fw, _ = freeze(lrlc=lrlc_p(steps=["test_scale"]), plan=plan)
    CALLS.clear()
    for theta in ({"m": 0.1}, {"rw": 0.2}, {"rw": -0.1, "n": 0.1, "sw_cutoff": 0.05}):
        U.evaluate(fw, theta)
    assert CALLS["test_scale"] == 0


@pytest.mark.parametrize("plan", [False, True])
def test_d_varied_step_parity_and_replay(register_test_steps, plan):
    fw, _ = freeze(lrlc=lrlc_p(steps=["test_rsh"]), plan=plan)
    assert all(seg.chain_replay is not None for seg in fw.segments)
    assert_parity(fw)
    # rsh = 3.0 differs from the step's reference 2.0, so the chain really changes Rt
    off, _ = freeze(plan=plan)
    assert fw.base_summary["hcpv_net_pay"] != off.base_summary["hcpv_net_pay"]


@pytest.mark.parametrize("plan", [False, True])
@pytest.mark.parametrize("theta", [{"rsh": 0.3}, {"rsh": -0.2, "n": -0.1}, {"rsh": 0.25, "rw": 0.2}])
def test_d_perturbed_rsh_equals_pipeline_at_that_rsh(register_test_steps, plan, theta):
    lrlc = lrlc_p(steps=["test_rsh"])
    fw, (data, mapping, params, tops) = freeze(lrlc=lrlc, plan=plan)
    base = fw.segments[0].params
    change = {k: U.apply_offset(k, base[k], off, U.DEFAULT_MODES[k])[0] for k, off in theta.items()}
    got = U.evaluate(fw, theta)
    p = {**params, **change}
    if plan:
        p["zone_plan"] = ps.zone_plan(
            {**PARAM_DEFAULTS, **p}, None, {"LOWER": {"m": ps.make_entry(ps.MANUAL, 1.8)}},
            None, ("UPPER", "LOWER"))
    _, summary = run_pipeline(data, mapping, p, None, tops)
    for k in PARITY:
        np.testing.assert_allclose(got["well"][k], summary[k], rtol=1e-10, equal_nan=True,
                                   err_msg=k)


def test_d_replay_runs_only_when_rsh_or_rw_varies(register_test_steps):
    fw, _ = freeze(lrlc=lrlc_p(steps=["test_rsh"]))
    zones = len(fw.segments[0].chain_replay.zones)          # the step runs once per zone
    assert zones == 2
    CALLS.clear()
    U.evaluate(fw, {"m": 0.1, "sw_cutoff": 0.02})
    assert CALLS["test_rsh"] == 0
    U.evaluate(fw, {"rsh": 0.2})
    assert CALLS["test_rsh"] == zones
    U.evaluate(fw, {"rw": 0.2})
    assert CALLS["test_rsh"] == 2 * zones


def test_d_perturbed_rsh_changes_the_result(register_test_steps):
    fw, _ = freeze(lrlc=lrlc_p(steps=["test_rsh"]))
    base = U.evaluate(fw, {})["well"]
    moved = U.evaluate(fw, {"rsh": 0.5})["well"]
    assert moved["hcpv_net_pay"] != base["hcpv_net_pay"]
