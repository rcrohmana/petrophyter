"""Invasion step in the pipeline: formation temperature for the Rmf bound, issue routing and the
summary block."""
import numpy as np
import pytest

from modules.lrlc.invasion import GENERIC_LABEL, GENERIC_TOOLS, forward_ra
from modules.pipeline import run_pipeline
from tests.test_lrlc_pipeline import codes, lrlc_p
from tests.test_lrlc_pipeline_l2 import MAPPING, PARAMS, laminated_well

DI = 40.0
TOOL = GENERIC_TOOLS["generic_induction"]


def invaded_well(contrast=0.2):
    frame, _ = laminated_well()
    rt_true = frame["RT"].to_numpy()
    ra = forward_ra(rt_true, contrast * rt_true, np.full(len(frame), DI),
                    (TOOL["deep"], TOOL["medium"], TOOL["shallow"]), TOOL["p"])
    out = frame.copy()
    out["RT"], out["RM"], out["RS"] = ra[:, 0], ra[:, 1], ra[:, 2]
    return out, rt_true


def run_invaded(frame, **ladder):
    lrlc = lrlc_p(steps=["invasion"], zones=(), curves={"RM": "RM", "RS": "RS"}, **ladder)
    return run_pipeline(frame.copy(), dict(MAPPING), {**PARAMS, "lrlc": lrlc})


def test_invasion_recovers_rt_and_leaves_rt_alone():
    frame, rt_true = invaded_well()
    r, s = run_invaded(frame)
    ok = r["RT_INV"].notna()
    assert ok.sum() > 100
    np.testing.assert_allclose(r["RT_INV"][ok], rt_true[ok.to_numpy()], rtol=1e-4)
    np.testing.assert_array_equal(r["RT"].to_numpy(), frame["RT"].to_numpy())
    assert {"RT_INV", "RXO_INV", "DI_INV", "RT_SW"} <= set(r.columns)


def test_summary_block_keys_and_generic_badge():
    frame, _ = invaded_well()
    _, s = run_invaded(frame)
    (row,) = s["lrlc"]["invasion"]["zones"]
    assert row["zone"] == "WELL" and row["tool"] == "generic_induction"
    assert row["generic"] is True and row["badge"] == GENERIC_LABEL
    assert row["r50"] == {"deep": 80.0, "medium": 45.0, "shallow": 20.0} and row["p"] == 2.5
    for key in ("n_valid", "n_ok", "n_nonunique", "n_di_lower", "n_di_upper", "n_poor_fit",
                "n_failed", "n_missing", "n_rxo_below_rmf", "rt_ratio_p50", "rxo_p50", "di_p50"):
        assert key in row
    assert row["n_ok"] > 100 and row["rt_ratio_p50"] > 1.0
    assert row["di_p50"] == pytest.approx(DI, rel=1e-3)
    assert "LRLC_INV_TOOL_GENERIC" in codes(s)


def test_rmf_gets_a_temperature_bound_and_the_default_setup_is_reported():
    frame, _ = invaded_well()
    _, s = run_invaded(frame, rmf=0.5, rmf_temp=75.0)
    (rec,) = [c for c in s["lrlc"]["chain"] if c["step"] == "invasion"]
    assert not rec["counts"].get("no_temperature")
    assert "LRLC_INV_TEMP_DEFAULT" in codes(s)
    assert "LRLC_INV_RMF_MISSING" not in codes(s)
    _, s2 = run_invaded(frame)
    assert "LRLC_INV_TEMP_DEFAULT" not in codes(s2) and "LRLC_INV_RMF_MISSING" in codes(s2)


def test_entered_temperature_setup_is_not_reported_as_default():
    frame, _ = invaded_well()
    lrlc = lrlc_p(steps=["invasion"], zones=(), curves={"RM": "RM", "RS": "RS"}, rmf=0.5)
    params = {**PARAMS, "lrlc": lrlc, "surface_temp": 60.0, "temp_gradient": 1.2}
    _, s = run_pipeline(frame.copy(), dict(MAPPING), params)
    assert "LRLC_INV_TEMP_DEFAULT" not in codes(s)
