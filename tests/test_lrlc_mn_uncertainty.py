"""Monte Carlo with m / n curves and the invasion step: parity with the deterministic run."""
import numpy as np
import pytest

from modules import uncertainty as U
from modules.pipeline import run_pipeline
from tests.test_lrlc_invasion_glue import invaded_well
from tests.test_lrlc_mn_pipeline import CURVE, SIMANDOUX
from tests.test_lrlc_pipeline import lrlc_p
from tests.test_lrlc_pipeline_l2 import MAPPING, PARAMS, laminated_well, ts_p

PARITY = ("hcpv_net_pay", "hcpv_net_res", "net_pay", "avg_phie_pay", "avg_sw_pay")


def close(a, b, **kw):
    np.testing.assert_allclose(a, b, rtol=1e-10, atol=0, equal_nan=True, **kw)


def curve_params(**ladder):
    return {**PARAMS, **SIMANDOUX, "lrlc": lrlc_p(zones=(), **{**CURVE, **ladder})}


def freeze(params, frame=None):
    frame = laminated_well()[0] if frame is None else frame
    return U.freeze_well("w", "w", frame.copy(), dict(MAPPING), params, None)


def det(params, frame=None):
    frame = laminated_well()[0] if frame is None else frame
    return run_pipeline(frame.copy(), dict(MAPPING), params)[1]


def test_segment_carries_the_frozen_curves():
    fw = freeze(curve_params())
    (seg,) = fw.segments
    assert seg.m_values is not None and seg.n_values is not None
    assert np.nanmin(seg.n_values) != np.nanmax(seg.n_values)      # n differs from 2: per-sample branches
    assert U.LRLC_MN_CURVE in U.lrlc_not_varied([fw])[0]


def test_theta_zero_equals_the_deterministic_summary_in_curve_mode():
    fw = freeze(curve_params())
    got = U.evaluate(fw, {})
    for k in PARITY:
        close(got["well"][k], fw.base_summary[k], err_msg=k)


def test_m_offset_equals_a_deterministic_run_with_shifted_c0():
    fw = freeze(curve_params())
    got = U.evaluate(fw, {"m": 0.1}, {"m": "additive"})
    ref = det(curve_params(m_coef=[CURVE["m_coef"][0] + 0.1] + CURVE["m_coef"][1:]))
    base = U.evaluate(fw, {})
    assert got["well"]["avg_sw_pay"] != base["well"]["avg_sw_pay"]
    for k in PARITY:
        close(got["well"][k], ref[k], err_msg=k)
    assert not got["clipped"]["m"]


def test_n_offset_equals_a_deterministic_run_with_shifted_d0():
    fw = freeze(curve_params())
    got = U.evaluate(fw, {"n": -0.1}, {"n": "additive"})
    ref = det(curve_params(n_coef=[CURVE["n_coef"][0] - 0.1, CURVE["n_coef"][1]]))
    for k in PARITY:
        close(got["well"][k], ref[k], err_msg=k)


def test_offset_is_bounded_per_sample_and_flags_clipping():
    fw = freeze(curve_params(m_coef=[3.95, 0.0, 0.0, 0.0]))
    got = U.evaluate(fw, {"m": 0.2}, {"m": "additive"})
    assert got["clipped"]["m"] is True
    (seg,) = fw.segments
    value, was = U.apply_offset("m", seg.m_values, 0.2, "additive")
    assert value.max() == 4.0 and was.all()


def test_relative_mode_is_rejected_in_a_curve_well():
    cfg = U.UncertaintyConfig(distributions=U.default_distributions())
    cfg.distributions["m"].enabled = True
    cfg.distributions["m"].mode = "relative"
    assert not any(U.CURVE_RELATIVE_ERROR in e for e in U.validate_config(cfg))
    errors = U.validate_config(cfg, curve_mn=True)
    assert any(U.CURVE_RELATIVE_ERROR in e for e in errors)
    fw = freeze(curve_params())
    with pytest.raises(ValueError, match="use additive offsets"):
        U.run_monte_carlo([fw], cfg)
    cfg.distributions["m"].mode = "additive"
    assert U.validate_config(cfg, curve_mn=True) == []


def test_run_names_the_curve_shape_as_not_varied():
    fw = freeze(curve_params())
    cfg = U.UncertaintyConfig(distributions=U.default_distributions())
    cfg.distributions["m"].enabled = True
    cfg.n = 50
    res = U.run_monte_carlo([fw], cfg)
    assert U.LRLC_MN_CURVE in res.lrlc_items
    assert any(U.LRLC_MN_CURVE in w for w in res.warnings)
    close(res.deterministic[("field", "hcpv_net_pay")], fw.base_summary["hcpv_net_pay"])


def test_curve_params_detection():
    assert U.curve_mn_in_params(curve_params())
    assert not U.curve_mn_in_params({**PARAMS, "lrlc": lrlc_p(zones=())})
    assert not U.curve_mn_in_params(PARAMS)


# ---- invasion is frozen ----------------------------------------------------------------------
def invasion_case():
    frame, _ = invaded_well()
    lrlc = ts_p(steps=("invasion", "laminated"))
    lrlc["curves"].update(RM="RM", RS="RS")
    return frame, {**PARAMS, "lrlc": lrlc}


def test_invasion_is_part_of_the_frozen_chain():
    frame, params = invasion_case()
    fw = freeze(params, frame)
    (seg,) = fw.segments
    assert "RT_INV" in {c for c in run_pipeline(frame.copy(), dict(MAPPING), params)[0].columns}
    replay = seg.chain_replay
    assert replay is not None
    names = [s.name for rz in replay.zones for s in rz.specs]
    assert "laminated" in names and "invasion" not in names
    assert U.LRLC_INVASION in U.lrlc_not_varied([fw])[0]


def test_theta_zero_and_rsh_offset_with_invasion_active():
    frame, params = invasion_case()
    fw = freeze(params, frame)
    got = U.evaluate(fw, {})
    for k in PARITY:
        close(got["well"][k], fw.base_summary[k], err_msg=k)
    moved = U.evaluate(fw, {"rsh": 0.5}, {"rsh": "additive"})
    ref = det({**params, "rsh": PARAMS["rsh"] + 0.5}, frame)
    for k in PARITY:
        close(moved["well"][k], ref[k], err_msg=k)
