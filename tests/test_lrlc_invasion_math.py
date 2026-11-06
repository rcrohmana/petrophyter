"""Radial invasion correction: forward model, vectorised inversion, chain step and issue helper."""

import numpy as np
import pytest

from modules.issue_codes import ISSUE_CODES
from modules.lrlc import chain, invasion
from modules.lrlc.chain import ChainContext
from modules.lrlc.invasion import (DI_LOWER, DI_UPPER, GENERIC_TOOLS, NONUNIQUE, OK, fit_invasion,
                                   forward_ra, pseudo_geometric_factor, rmf_at_temperature)

R50 = (80.0, 45.0, 20.0)
P = 2.5


def _ra(rt, rxo, di):
    return forward_ra(np.atleast_1d(rt), np.atleast_1d(rxo), np.atleast_1d(di), R50, P)


def test_generic_presets_are_labelled():
    assert set(GENERIC_TOOLS) == {"generic_induction", "generic_laterolog"}
    for tool in GENERIC_TOOLS.values():
        assert "confirm with tool charts" in tool["label"]
    assert GENERIC_TOOLS["generic_induction"]["deep"] == 80.0


def test_j_is_half_at_the_tool_diameter():
    assert pseudo_geometric_factor(45.0, 45.0, 2.5) == pytest.approx(0.5)
    assert pseudo_geometric_factor(1e6, 45.0, 2.5) == pytest.approx(1.0, abs=1e-9)
    assert pseudo_geometric_factor(1e-3, 45.0, 2.5) == pytest.approx(0.0, abs=1e-9)


def test_worked_check_j_and_ra():
    j = pseudo_geometric_factor(40.0, np.array(R50), P)
    assert np.round(j, 5).tolist() == [0.15022, 0.42691, 0.84978]
    ra = _ra(20.0, 2.0, 40.0)[0]
    assert np.round(ra, 4).tolist() == [8.5034, 4.1303, 2.3127]


def test_worked_check_round_trip():
    ra = _ra(20.0, 2.0, 40.0)[0]
    res = fit_invasion([ra[0]], [ra[1]], [ra[2]], r50=R50, p=P)
    assert res.status[0] == OK
    assert res.rt[0] == pytest.approx(20.0, abs=1e-6)
    assert res.rxo[0] == pytest.approx(2.0, abs=1e-6)
    assert res.di[0] == pytest.approx(40.0, abs=1e-6)
    # the rounded values quoted in the worked check recover the same answer to the rounding
    res2 = fit_invasion([8.5034], [4.1303], [2.3127], r50=R50, p=P)
    assert res2.rt[0] == pytest.approx(20.0, rel=1e-3)
    assert res2.di[0] == pytest.approx(40.0, rel=1e-3)


def test_analytic_jacobian_matches_finite_differences():
    rng = np.random.default_rng(1)
    x = np.stack([np.log(rng.uniform(1, 50, 6)), np.log(rng.uniform(0.3, 30, 6)),
                  np.log(rng.uniform(10, 100, 6))], axis=1)
    use = np.ones((6, 3))
    lnram = np.zeros((6, 3))
    r50 = np.array(R50)
    _, _, jac = invasion._model(x, lnram, use, r50, P, True)
    for k in range(3):
        h = np.zeros(3)
        h[k] = 1e-6
        fp = invasion._model(x + h, lnram, use, r50, P, False)[0]
        fm = invasion._model(x - h, lnram, use, r50, P, False)[0]
        assert np.allclose((fp - fm) / 2e-6, jac[:, :, k], atol=1e-6)


def test_vectorised_round_trip_many_samples():
    rng = np.random.default_rng(2)
    n = 400
    rt = np.exp(rng.uniform(np.log(1), np.log(100), n))
    ratio = np.where(rng.random(n) < 0.5, rng.uniform(0.05, 0.6, n), rng.uniform(1.8, 20, n))
    rxo = rt * ratio
    di = rng.uniform(15, 90, n)
    ra = forward_ra(rt, rxo, di, R50, P)
    res = fit_invasion(ra[:, 0], ra[:, 1], ra[:, 2], r50=R50, p=P)
    good = res.valid & (res.status == OK)
    assert good.mean() > 0.95
    assert np.allclose(res.rt[good], rt[good], rtol=1e-5)
    assert np.allclose(res.di[good], di[good], rtol=1e-4)


def test_rxo_fixed_mode_round_trip():
    ra = _ra(20.0, 2.0, 40.0)[0]
    res = fit_invasion([ra[0]], [ra[1]], None, [2.0], r50=R50, p=P, rxo_mode="fixed")
    assert res.status[0] == OK
    assert res.rt[0] == pytest.approx(20.0, rel=1e-6)
    assert res.di[0] == pytest.approx(40.0, rel=1e-6)
    assert res.rxo[0] == 2.0
    # shallow instead of medium
    res = fit_invasion([ra[0]], None, [ra[2]], [2.0], r50=R50, p=P)
    assert res.rt[0] == pytest.approx(20.0, rel=1e-6)
    # redundant fixed-mode fit with all three curves
    res = fit_invasion([ra[0]], [ra[1]], [ra[2]], [2.0], r50=R50, p=P)
    assert res.rt[0] == pytest.approx(20.0, rel=1e-6)


def test_rxo_ignored_needs_three_curves():
    ra = _ra(20.0, 2.0, 40.0)[0]
    res = fit_invasion([ra[0]], [ra[1]], None, [2.0], r50=R50, p=P, rxo_mode="ignore")
    assert res.counts["curves_missing"] == 1
    assert not res.valid[0]


def test_missing_curves_zone_is_skipped_with_counts():
    res = fit_invasion([5.0, 6.0], [4.0, 5.0], None, None, r50=R50)
    assert not res.valid.any()
    assert np.isnan(res.rt).all()
    assert res.counts["curves_missing"] == 2 and res.counts["missing"] == 2


def test_sample_with_missing_input_is_invalid():
    ra = _ra([20.0, 20.0], [2.0, 2.0], [40.0, 40.0])
    ra[1, 2] = np.nan
    res = fit_invasion(ra[:, 0], ra[:, 1], ra[:, 2], r50=R50)
    assert res.valid.tolist() == [True, False]
    assert res.counts["missing"] == 1


def test_non_unique_echoes_input_rt():
    ra = np.array([10.0, 10.2, 10.4])
    res = fit_invasion([ra[0]], [ra[1]], [ra[2]], r50=R50, min_contrast=1.15)
    assert res.status[0] == NONUNIQUE
    assert res.valid[0]
    assert res.rt[0] == 10.0
    assert np.isnan(res.di[0])
    assert res.counts["nonunique"] == 1


def test_diameter_bounds():
    # very deep invasion: all tools read the flushed zone
    ra = _ra(20.0, 2.0, 160.0)[0]
    res = fit_invasion([ra[0]], [ra[1]], [ra[2]], r50=R50, di_max=120.0)
    assert res.status[0] == DI_UPPER
    assert not res.valid[0]
    assert np.isnan(res.rt[0])
    # shallow invasion: valid and counted
    ra = _ra(20.0, 2.0, 4.0)[0]
    res = fit_invasion([ra[0]], [ra[1]], [ra[2]], r50=R50, di_min=8.0)
    assert res.status[0] == DI_LOWER
    assert res.valid[0]
    assert res.di[0] <= 8.0 * 1.01
    assert res.counts["di_lower"] == 1


def test_poor_fit_only_in_redundant_fit():
    ra = _ra(20.0, 2.0, 40.0)[0]
    bad = [ra[0], ra[1] * 1.5, ra[2]]          # inconsistent medium curve
    res = fit_invasion([bad[0]], [bad[1]], [bad[2]], [2.0], r50=R50, max_rms=0.05)
    assert res.counts["poor_fit"] == 1 and not res.valid[0]
    res = fit_invasion([bad[0]], [bad[1]], [bad[2]], r50=R50, max_rms=0.05)   # exactly determined
    assert res.counts["poor_fit"] == 0


def test_rt_bounds_are_respected():
    ra = _ra(20.0, 2.0, 40.0)[0]
    res = fit_invasion([ra[0]], [ra[1]], [ra[2]], r50=R50, rt_bounds=(0.05, 15.0))
    assert not np.isfinite(res.rt[0]) or res.rt[0] <= 15.0 + 1e-9


def test_rmf_bound_projection_and_count():
    ra = _ra(20.0, 0.5, 40.0)[0]
    free = fit_invasion([ra[0]], [ra[1]], [ra[2]], r50=R50)
    assert free.rxo[0] == pytest.approx(0.5, rel=1e-5)
    res = fit_invasion([ra[0]], [ra[1]], [ra[2]], r50=R50, rmf_t=2.0)
    assert res.counts["rxo_below_rmf"] == 1
    # fixed Rxo below the bound is counted too
    res = fit_invasion([ra[0]], [ra[1]], None, [0.5], r50=R50, rmf_t=2.0)
    assert res.counts["rxo_below_rmf"] == 1


def test_rmf_at_temperature_arps():
    assert rmf_at_temperature(0.35, 68.0, 68.0) == pytest.approx(0.35)
    assert rmf_at_temperature(0.35, 68.0, 200.0) == pytest.approx(0.35 * 74.77 / 206.77)
    t = np.array([100.0, 200.0])
    assert rmf_at_temperature(1.0, 75.0, t).shape == (2,)


# ---------------------------------------------------------------------------
# Chain step
# ---------------------------------------------------------------------------
def _prm(**kw):
    base = {"inv_tool": "generic_induction", "inv_r50": {"deep": 80.0, "medium": 45.0, "shallow": 20.0},
            "inv_p": 2.5, "inv_rxo_mode": "fixed", "inv_di_min": 8.0, "inv_di_max": 120.0,
            "inv_min_contrast": 1.15, "inv_max_rms": 0.15, "rmf": None, "rmf_temp": 75.0}
    base.update(kw)
    return base


def _ctx(n, rm=None, rs=None, rxo=None, derived=None):
    nan = None
    return ChainContext(
        depth=np.arange(n, dtype=float), zone="A", rows=np.arange(n), rt_raw=np.ones(n),
        vsh=np.zeros(n), phit=np.zeros(n), phie=np.zeros(n), rsh=np.ones(n), rw=np.ones(n),
        temperature=nan, rhob=nan, pef=nan, rm=rm, rs=rs, rxo=rxo, hires=nan,
        segment_depth=np.arange(n, dtype=float), flags={}, derived=derived or {})


def test_step_spec_shape():
    spec = invasion.STEP
    assert spec.name == "invasion" and spec.column == "RT_INV"
    assert spec.extra_columns == ("RXO_INV", "DI_INV")
    assert spec.kind == "radial" and spec.varied == ()
    assert spec.order < chain.CHAIN_ORDER.index("laminated")
    assert spec.order == chain.CHAIN_ORDER.index("invasion")


def test_register_step_idempotent():
    invasion.register_step()
    invasion.register_step()
    assert chain.STEPS["invasion"] is invasion.STEP


def test_step_function_outputs_and_counts():
    ra = _ra([20.0, 20.0], [2.0, 10.0], [40.0, 40.0])
    ra[1, :] = [10.0, 10.1, 10.2]               # non-unique sample
    n = 2
    res = invasion.step_invasion(ra[:, 0].copy(), _ctx(n, rm=ra[:, 1], rs=ra[:, 2]), _prm())
    assert res.rt_out[0] == pytest.approx(20.0, rel=1e-6)
    assert res.rt_out[1] == pytest.approx(10.0)
    assert res.valid_mask.all()
    assert set(res.extra_columns) == {"RXO_INV", "DI_INV"}
    assert res.extra_columns["RXO_INV"][0] == pytest.approx(2.0, rel=1e-5)
    assert np.isnan(res.extra_columns["DI_INV"][1])
    assert res.counts["ok"] == 1 and res.counts["nonunique"] == 1
    assert res.counts["generic"] == 1 and res.counts["rmf_missing"] == 1


def test_step_custom_tool_is_not_generic_and_uses_settings():
    r50 = (100.0, 60.0, 30.0)
    ra = forward_ra(np.array([15.0]), np.array([1.5]), np.array([50.0]), r50, 3.0)
    prm = _prm(inv_tool="custom", inv_r50={"deep": 100.0, "medium": 60.0, "shallow": 30.0}, inv_p=3.0)
    res = invasion.step_invasion(ra[:, 0].copy(), _ctx(1, rm=ra[:, 1], rs=ra[:, 2]), prm)
    assert res.rt_out[0] == pytest.approx(15.0, rel=1e-6)
    assert res.counts["generic"] == 0


def test_step_missing_curves_is_skipped():
    res = invasion.step_invasion(np.array([5.0, 6.0]), _ctx(2), _prm())
    assert not res.valid_mask.any()
    assert res.counts["curves_missing"] == 2


def test_step_rmf_uses_formation_temperature_derive():
    ra = _ra([20.0], [0.5], [40.0])
    ctx = _ctx(1, rm=ra[:, 1], rs=ra[:, 2], derived={"T_FM_F": np.array([200.0])})
    res = invasion.step_invasion(ra[:, 0].copy(), ctx, _prm(rmf=2.0, rmf_temp=68.0))
    assert res.counts["rxo_below_rmf"] == 1
    assert "no_temperature" not in res.counts or res.counts["no_temperature"] == 0
    res = invasion.step_invasion(ra[:, 0].copy(), _ctx(1, rm=ra[:, 1], rs=ra[:, 2]), _prm(rmf=2.0))
    assert res.counts["no_temperature"] == 1 and res.counts["rxo_below_rmf"] == 0


def test_step_runs_through_the_chain_with_zone_parameters():
    invasion.register_step()
    ra = _ra([20.0, 20.0], [2.0, 2.0], [40.0, 40.0])
    arrays = {"depth": np.array([1.0, 2.0]), "vsh": [0, 0], "phit": [0.2, 0.2], "phie": [0.2, 0.2],
              "rsh": [3, 3], "rw": [0.1, 0.1], "rm": ra[:, 1], "rs": ra[:, 2]}
    res_a = {"rt_steps": ["invasion"], "rt_fallback": "nan"}
    res_a.update(_prm())
    lrlc = {"resolved": {"default": res_a, "zones": {}}}
    zone_keys = np.array(["A", "A"], dtype=object)
    out = chain.apply_rt_chain(ra[:, 0].copy(), arrays, zone_keys, lrlc, False)
    assert out.rt_sw == pytest.approx([20.0, 20.0], rel=1e-6)
    assert set(out.columns) == {"RT_INV", "RXO_INV", "DI_INV"}
    rec = out.records[0]
    assert rec["step"] == "invasion" and rec["counts"]["ok"] == 2


def test_issue_codes_registered_and_helper_uses_them():
    for code in ("LRLC_INV_CURVES_MISSING", "LRLC_INV_TOOL_GENERIC", "LRLC_INV_NONUNIQUE",
                 "LRLC_INV_DI_BOUND", "LRLC_INV_POOR_FIT", "LRLC_INV_FAIL", "LRLC_INV_RXO_BELOW_RMF",
                 "LRLC_INV_RMF_MISSING", "LRLC_INV_DECON_MISMATCH", "LRLC_INV_TEMP_DEFAULT"):
        assert code in ISSUE_CODES
    rec = {"step": "invasion", "zone": "A", "n_valid": 10, "n_invalid": 0,
           "counts": {"generic": 1, "nonunique": 5, "di_upper": 1, "di_lower": 1, "poor_fit": 1,
                      "failed": 1, "rxo_below_rmf": 1, "rmf_missing": 1}}
    issues = invasion.invasion_count_issues([rec])
    codes = [i[0] for i in issues]
    assert set(codes) <= set(ISSUE_CODES)
    assert codes.count("LRLC_INV_DI_BOUND") == 2
    sev = {i[0]: i[3] for i in issues if i[0] == "LRLC_INV_NONUNIQUE"}
    assert sev["LRLC_INV_NONUNIQUE"] == "warning"
    skipped = invasion.invasion_count_issues([{"step": "invasion", "zone": None, "counts": {"curves_missing": 3}}])
    assert [i[0] for i in skipped] == ["LRLC_INV_CURVES_MISSING"]
    assert all(("invasion" in i[1].lower() or "mud" in i[1].lower()) for i in issues)
