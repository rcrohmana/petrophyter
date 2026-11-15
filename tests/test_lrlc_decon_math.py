"""Rt deconvolution maths: response weights, bed picking, edits, solvers, windows, validity, counts."""

import time
from dataclasses import replace

import numpy as np
import pytest
from scipy.integrate import quad
from scipy.ndimage import gaussian_filter1d

from modules.lrlc import decon
from modules.lrlc.decon import (GENERIC_LABEL, GENERIC_RESPONSES, REFS, DeconParams, apply_edits, deconvolve,
                                doll_gz, doll_table, pick_beds, response_weights)

FWHM = 4.0


# ---------------------------------------------------------------------------
# Synthetic wells
# ---------------------------------------------------------------------------
def _beds(n_beds=15, seed=1, thick=(3.0, 40.0), contrast=0.3):
    """Bed edges and resistivities (neighbours differ by at least ``contrast`` decades)."""
    rng = np.random.default_rng(seed)
    thickness = rng.uniform(*thick, n_beds)
    edges = np.concatenate([[0.0], np.cumsum(thickness)])
    rts = 10 ** rng.uniform(-0.3, 1.7, n_beds)
    for i in range(1, n_beds):
        while abs(np.log10(rts[i] / rts[i - 1])) < contrast:
            rts[i] = 10 ** rng.uniform(-0.3, 1.7)
    return edges, rts


def _measure(z, edges, rts, fwhm=FWHM, noise=0.0, seed=2):
    """Apparent resistivity of the bed model (Gaussian response, end beds extended) with relative noise."""
    tops, bottoms = edges[:-1].copy(), edges[1:].copy()
    tops[0], bottoms[-1] = -np.inf, np.inf
    sigma = response_weights(z, tops, bottoms, fwhm) @ (1.0 / rts)
    rng = np.random.default_rng(seed)
    return (1.0 / sigma) * (1.0 + noise * rng.standard_normal(z.size))


def _reference(z, edges, rts, fwhm=1.0, noise=0.03, seed=3):
    """High-resolution curve: different contrast from the deep curve, blurred, with noise."""
    ds = float(np.median(np.diff(z)))
    bed = np.searchsorted(edges[1:-1], z, side="right")
    log_ref = 0.5 * np.log10(rts[bed]) + 0.3
    smooth = gaussian_filter1d(log_ref, fwhm / 2.3548 / ds, mode="nearest")
    rng = np.random.default_rng(seed)
    return 10 ** smooth * (1.0 + noise * rng.standard_normal(z.size))


def _well(n_beds=15, seed=1, ds=0.5, noise=0.0, thick=(3.0, 40.0)):
    edges, rts = _beds(n_beds, seed, thick)
    z = np.arange(0.0, edges[-1], ds)
    rt = _measure(z, edges, rts, noise=noise)
    ref = _reference(z, edges, rts)
    bed = np.searchsorted(edges[1:-1], z, side="right")
    return z, rt, ref, edges, rts, bed


def _exact(params, z, ref, edges):
    """Params whose boundaries are the true ones (edits remove every pick and add the true edges)."""
    auto = pick_beds(z, ref, params.with_reference("RXO"), True).boundaries
    return replace(params, edit_tol_ft=0.25, edits={"remove": list(auto), "add": list(edges[1:-1])})


def _run(z, rt, ref, params, **kwargs):
    return deconvolve(z, rt, ref, params, np.ones(z.size, dtype=bool), **kwargs)


# ---------------------------------------------------------------------------
# Presets and settings
# ---------------------------------------------------------------------------
def test_generic_presets_are_labelled():
    assert set(GENERIC_RESPONSES) == {"array_induction_1ft", "array_induction_2ft", "array_induction_4ft",
                                      "laterolog_deep_2ft", "dual_induction_deep_8ft", "custom"}
    assert GENERIC_LABEL == "generic, confirm with tool charts"
    for preset in GENERIC_RESPONSES.values():
        assert preset["label"] == GENERIC_LABEL
    assert GENERIC_RESPONSES["dual_induction_deep_8ft"]["fwhm_ft"] == 8.0
    assert REFS == ("doll1949", "thadani1981", "coll1993")


def test_params_from_settings_prefixed_keys_and_defaults():
    p = DeconParams.from_settings({"dec_fwhm_ft": 6.0, "dec_lambda": 0.01, "dec_solver": "mult", "rt_steps": ["decon"],
                                   "dec_unknown": 1, "dec_edits": {"add": [10.0], "remove": []}})
    assert (p.fwhm_ft, p.lam, p.solver) == (6.0, 0.01, "mult")
    assert p.edits == {"add": [10.0], "remove": []}
    d = DeconParams.from_settings({})
    assert d.lam is None and d.min_bed_ft is None and d.output == "blocky" and d.max_ratio == 10.0
    assert d.edits == {"add": [], "remove": []}
    preset = DeconParams.from_settings({"dec_tool": "array_induction_2ft", "dec_fwhm_ft": 9.0})
    assert preset.fwhm_ft == 2.0 and preset.response == "gaussian"


def test_min_bed_default_per_reference_kind():
    p = DeconParams()
    assert p.with_reference("RXO").min_bed_ft == 1.0
    assert p.with_reference("HIRES").min_bed_ft == 1.0
    assert p.with_reference("RHOB").min_bed_ft == 1.5
    assert p.with_reference("GR").min_bed_ft == 2.0
    assert replace(p, min_bed_ft=3.0).with_reference("GR").min_bed_ft == 3.0


# ---------------------------------------------------------------------------
# Response weights
# ---------------------------------------------------------------------------
def test_gaussian_row_sums_and_thick_bed():
    z = np.linspace(-40.0, 140.0, 721)
    edges = np.array([0.0, 30.0, 31.0, 80.0, 100.0])
    w = response_weights(z, edges[:-1], edges[1:], FWHM)
    interior = (z > 12.0) & (z < 88.0)
    assert np.allclose(w[interior].sum(axis=1), 1.0, atol=1e-9)
    assert w.shape == (z.size, 4)
    thick = response_weights(z, [0.0], [100.0], FWHM)[:, 0]
    assert np.all(np.isclose(thick[(z > 3 * FWHM) & (z < 100 - 3 * FWHM)], 1.0, atol=1e-6))


def test_gaussian_half_maximum_at_half_fwhm():
    h = 1e-3
    g = lambda zz: response_weights(np.atleast_1d(zz), [-h / 2], [h / 2], FWHM)[0, 0] / h
    assert g(FWHM / 2) == pytest.approx(g(0.0) / 2.0, rel=1e-4)
    assert g(-FWHM / 2) == pytest.approx(g(FWHM / 2), rel=1e-9)


def test_doll_response_checks():
    L = 3.333
    table = doll_table(L, half_range=50.0)
    assert table["raw_area"] == pytest.approx(1.0, abs=1e-3)
    assert float(doll_gz([0.0], L)[0]) == pytest.approx(1.0 / (2.0 * L), rel=1e-3)
    # never sampled at the singular points z = +/-L/2
    assert np.min(np.abs(np.abs(table["centres"]) - L / 2.0)) > 0.4 * L / decon.DOLL_CELLS_PER_L
    # agrees with direct quadrature at a point off the singularity
    z = 0.7 * L
    a, b = z + L / 2, z - L / 2
    f = lambda r: (L * L / np.pi) * r * r / ((r * r + a * a) ** 1.5 * (r * r + b * b) ** 1.5)
    ref = quad(f, 0, abs(a), limit=200)[0] + quad(f, abs(a), np.inf, limit=200)[0]
    assert float(doll_gz([z], L)[0]) == pytest.approx(ref, rel=1e-6)
    assert doll_table(L, half_range=50.0) is table                  # cached by L


def test_doll_weights_sum_to_one_and_resolve_thick_bed():
    z = np.linspace(-30.0, 130.0, 641)
    w = response_weights(z, [0.0, 50.0], [50.0, 100.0], 0.0, kind="doll", doll_l_ft=3.333)
    interior = (z > 15.0) & (z < 85.0)
    assert np.allclose(w[interior].sum(axis=1), 1.0, atol=2e-3)
    assert np.all(w >= -1e-9)
    assert w[np.argmin(np.abs(z - 25.0)), 0] > 0.97
    with pytest.raises(ValueError):
        response_weights(z, [0.0], [1.0], 4.0, kind="doll")


# ---------------------------------------------------------------------------
# Bed picking and edits
# ---------------------------------------------------------------------------
def test_pick_beds_finds_every_boundary_within_one_foot():
    z, _, ref, edges, _, _ = _well()
    pick = pick_beds(z, ref, DeconParams().with_reference("RXO"), True)
    true = edges[1:-1]
    assert len(pick.boundaries) == len(true) == 14
    assert np.max(np.abs(pick.boundaries - true)) < 1.0


def test_pick_beds_minimum_thickness_merges_weaker_boundary():
    z = np.arange(0.0, 60.0, 0.25)
    ref = np.where(z < 30.0, 2.0, np.where(z < 31.5, 8.0, 40.0))     # a 1.5 ft bed between two steps
    thin = pick_beds(z, ref, replace(DeconParams(), min_bed_ft=0.5, smooth_ft=0.25), True)
    thick = pick_beds(z, ref, replace(DeconParams(), min_bed_ft=3.0, smooth_ft=0.25), True)
    assert len(thin.boundaries) == 2 and thin.n_dropped_thickness == 0
    assert len(thick.boundaries) == 1
    assert abs(thick.boundaries[0] - 31.5) < 0.5                       # the stronger of the two steps survives
    # a bed thinner than the minimum at the segment end: the weaker boundary is merged and counted
    ref_end = np.where(z < 1.0, 2.0, np.where(z < 30.0, 4.0, 40.0))
    end = pick_beds(z, ref_end, replace(DeconParams(), min_bed_ft=3.0, smooth_ft=0.25), True)
    assert len(end.boundaries) == 1 and end.n_dropped_thickness == 1
    assert abs(end.boundaries[0] - 30.0) < 0.5


def test_pick_beds_contrast_filter():
    z = np.arange(0.0, 80.0, 0.5)
    ref = np.where(z < 40.0, 10.0, 10.0 * 10 ** 0.2)          # a 0.2 decade step
    base = replace(DeconParams(), min_bed_ft=1.0)
    assert len(pick_beds(z, ref, replace(base, min_contrast=0.05), True).boundaries) == 1
    strict = pick_beds(z, ref, replace(base, min_contrast=0.5), True)
    assert len(strict.boundaries) == 0 and strict.n_dropped_contrast == 1
    # linear curve: the step is in robust-sigma units, a flat noisy curve gives no bed
    rng = np.random.default_rng(0)
    flat = 50.0 + rng.standard_normal(z.size)
    assert len(pick_beds(z, flat, replace(base, min_contrast=3.0), False).boundaries) == 0


def test_apply_edits_add_remove_tolerance_unmatched():
    auto = np.array([10.0, 20.0, 30.0])
    out, info = apply_edits(auto, {"add": [25.0], "remove": [20.4]}, 1.0)
    assert list(out) == [10.0, 25.0, 30.0] and info["removed"] == 1 and info["added"] == 1
    out, info = apply_edits(auto, {"add": [], "remove": [22.0]}, 1.0)          # beyond tolerance
    assert list(out) == [10.0, 20.0, 30.0] and info["unmatched"] == 1
    out, info = apply_edits(auto, {"add": [10.5]}, 1.0)                          # within tolerance of an existing one
    assert list(out) == [10.0, 20.0, 30.0] and info["skipped"] == 1
    out, info = apply_edits(auto, None, 1.0)
    assert list(out) == list(auto) and info["unmatched"] == 0
    assert list(auto) == [10.0, 20.0, 30.0]


# ---------------------------------------------------------------------------
# Solver recovery
# ---------------------------------------------------------------------------
def test_noise_free_recovery_with_exact_boundaries():
    z, rt, ref, edges, rts, bed = _well()
    p = _exact(DeconParams(lam=1e-6, noise_rel=0.005), z, ref, edges)
    r = _run(z, rt, ref, p)
    assert r.valid.sum() > 0.9 * z.size
    err = np.abs(r.rt_decon[r.valid] / rts[bed][r.valid] - 1.0)
    assert err.max() < 0.01


def test_two_percent_noise_recovery_p95():
    z, rt, ref, edges, rts, bed = _well(noise=0.02)
    p = _exact(DeconParams(noise_rel=0.02), z, ref, edges)
    r = _run(z, rt, ref, p)
    err = np.abs(r.rt_decon[r.valid] / rts[bed][r.valid] - 1.0)
    assert np.percentile(err, 95) < 0.15
    assert r.windows and all(win.lam > 0 for win in r.windows)


def test_picked_boundaries_recovery_away_from_edges():
    z, rt, ref, edges, rts, bed = _well(noise=0.02)
    r = _run(z, rt, ref, DeconParams(noise_rel=0.02))
    far = np.min(np.abs(z[:, None] - edges[None, 1:-1]), axis=1) > 1.0
    ok = r.valid & far
    err = np.abs(r.rt_decon[ok] / rts[bed][ok] - 1.0)
    assert ok.sum() > 0.8 * z.size and np.percentile(err, 95) < 0.15


def test_thick_beds_return_the_measured_values():
    edges = np.array([0.0, 60.0, 130.0, 200.0, 280.0])
    rts = np.array([2.0, 15.0, 4.0, 30.0])
    z = np.arange(0.0, 280.0, 0.5)
    rt = _measure(z, edges, rts)
    ref = _reference(z, edges, rts)
    r = _run(z, rt, ref, DeconParams(noise_rel=0.01))
    inside = np.min(np.abs(z[:, None] - edges[None, 1:-1]), axis=1) > 2.0 * FWHM       # beds are > 4 FWHM thick
    both = r.valid & inside
    assert both.sum() > 0.6 * z.size
    assert np.max(np.abs(r.rt_decon[both] / rt[both] - 1.0)) < 0.02


def test_lsq_and_mult_agree():
    z, rt, ref, edges, rts, bed = _well(noise=0.0)
    base = _exact(DeconParams(noise_rel=0.005, mult_max_iter=500), z, ref, edges)
    a = _run(z, rt, ref, replace(base, solver="lsq"))
    b = _run(z, rt, ref, replace(base, solver="mult"))
    both = a.valid & b.valid
    assert both.sum() > 0.8 * z.size
    assert np.max(np.abs(a.rt_decon[both] / b.rt_decon[both] - 1.0)) < 0.10


def test_residual_output_equals_blocky_when_fit_is_exact():
    z, rt, ref, edges, rts, bed = _well()
    base = _exact(DeconParams(lam=1e-6, noise_rel=0.005), z, ref, edges)
    blocky = _run(z, rt, ref, base)
    resid = _run(z, rt, ref, replace(base, output="residual"))
    both = blocky.valid & resid.valid
    assert both.sum() > 0.8 * z.size
    assert np.max(np.abs(resid.rt_decon[both] / blocky.rt_decon[both] - 1.0)) < 0.01


def test_auto_lambda_picks_largest_passing_value_and_falls_back():
    z, rt, ref, edges, rts, bed = _well(noise=0.02)
    tops, bots = edges[:-1].copy(), edges[1:].copy()
    tops[0], bots[-1] = -np.inf, np.inf
    w = response_weights(z, tops, bots, FWHM)
    w /= w.sum(axis=1, keepdims=True)
    sigma_a = 1.0 / rt
    sigma0 = np.array([np.median(sigma_a[bed == k]) for k in range(len(rts))])
    A = w * sigma0 / sigma_a[:, None]
    AtA, Atr = A.T @ A, A.T @ (1.0 - A.sum(axis=1))
    target = 1.1 * 0.02
    lam = decon._auto_lambda(A, AtA, Atr, 0.02)
    mis = lambda lm: decon._rms(A @ decon._ridge(AtA, Atr, lm) - 1.0)
    assert 1e-4 <= lam <= 1.0
    assert mis(lam) <= target
    assert lam == 1.0 or mis(lam * 10 ** 0.3) > target             # bisection resolution of 0.25 decade
    assert decon._auto_lambda(A, AtA, Atr, 1e-9) == decon.LAM_FALLBACK


def test_missing_boundary_is_reported_as_misfit_not_hidden():
    z, rt, ref, edges, rts, bed = _well()
    flat_ref = np.full(z.size, 5.0)                                  # the reference shows no bed at all
    p = replace(DeconParams(misfit_warn=0.02), min_bed_ft=1.0)
    r = _run(z, rt, flat_ref, p)
    assert r.counts["windows_bad_misfit"] >= 1
    codes = {i[0] for i in r.issues}
    assert "LRLC_DECON_MISFIT" in codes
    assert any(win.status == "high_misfit" for win in r.windows)


# ---------------------------------------------------------------------------
# Bounds, amplification, validity
# ---------------------------------------------------------------------------
def _thin_sand():
    edges = np.array([0.0, 60.0, 62.0, 120.0])
    rts = np.array([2.0, 30.0, 2.0])
    z = np.arange(0.0, 120.0, 0.5)
    return z, _measure(z, edges, rts), _reference(z, edges, rts, noise=0.0), edges, rts


def test_bed_on_a_bound_is_nan_and_counted():
    z, rt, ref, edges, rts = _thin_sand()
    p = _exact(DeconParams(lam=1e-6, max_ratio=2.0), z, ref, edges)
    r = _run(z, rt, ref, p)
    sand = (z > 60.0) & (z < 62.0)
    assert not r.valid[sand].any() and np.all(np.isnan(r.rt_decon[sand]))
    assert r.counts["amplified"] >= sand.sum()
    assert any(b.at_bound for b in r.beds)
    issue = [i for i in r.issues if i[0] == "LRLC_DECON_AMPLIFIED"]
    assert issue and len(issue[0]) == 4 and issue[0][3] in ("info", "warning")
    wide = _run(z, rt, ref, replace(p, max_ratio=100.0))
    assert wide.valid[sand].all()
    assert wide.counts["amplified"] == 0
    assert np.all(np.abs(wide.rt_decon[sand] / 30.0 - 1.0) < 0.1)


def test_amplification_ratio_is_per_zone():
    z, rt, ref, edges, rts = _thin_sand()
    zones = np.where(z < 60.0, "UPPER", "LOWER").astype(object)
    p = _exact(DeconParams(lam=1e-6, max_ratio=100.0), z, ref, edges)
    free = _run(z, rt, ref, p, zone_labels=zones)
    tight = _run(z, rt, ref, p, zone_labels=zones, max_ratio_by_zone={"LOWER": 1.5})
    sand = (z > 60.0) & (z < 62.0)
    assert free.valid[sand].all()
    assert not tight.valid[sand].any()
    assert tight.valid[(z > 5.0) & (z < 40.0)].all()
    assert tight.zone_stats["LOWER"]["n_amplified"] > 0 and tight.zone_stats["UPPER"]["n_amplified"] == 0
    assert tight.zone_stats["LOWER"]["max_ratio"] == 1.5


def test_segment_ends_are_nan_within_one_fwhm():
    z, rt, ref, edges, rts, bed = _well()
    r = _run(z, rt, ref, DeconParams())
    assert np.all(np.isnan(r.rt_decon[z < z[0] + FWHM - 1e-9]))
    assert np.all(np.isnan(r.rt_decon[z > z[-1] - FWHM + 1e-9]))
    assert r.counts["edge"] >= 2 * int(FWHM / 0.5)
    assert any(i[0] == "LRLC_DECON_EDGE" for i in r.issues)


def test_depth_gap_splits_the_segment():
    z, rt, ref, edges, rts, bed = _well()
    shift = np.where(z > 150.0, 30.0, 0.0)                           # a 30 ft jump
    zg = z + shift
    r = _run(zg, rt, ref, DeconParams())
    assert r.counts["gap"] >= 1
    assert any(i[0] == "LRLC_DECON_GAP" for i in r.issues)
    assert r.valid[(zg < 140.0) & (zg > 10.0)].mean() > 0.9
    assert r.valid[(zg > 190.0) & (zg < zg[-1] - 10.0)].mean() > 0.9


def test_nan_run_splits_the_segment():
    z, rt, ref, edges, rts, bed = _well()
    rt = rt.copy()
    hole = (z > 150.0) & (z < 162.0)                                 # 12 ft > 2 FWHM
    rt[hole] = np.nan
    r = _run(z, rt, ref, DeconParams())
    assert r.counts["gap"] >= 1
    assert np.all(np.isnan(r.rt_decon[hole]))
    short = (z > 200.0) & (z < 202.0)
    rt2 = rt.copy()
    rt2[hole] = _measure(z, edges, rts)[hole]
    rt2[short] = np.nan                                              # 2 ft hole: no split, NaN output only
    r2 = _run(z, rt2, ref, DeconParams())
    assert r2.counts["gap"] == 0
    assert np.all(np.isnan(r2.rt_decon[short]))


def test_undersampled_log_is_invalid():
    z = np.arange(0.0, 300.0, 3.0)                                   # step 3 ft > FWHM / 2
    edges, rts = _beds(5, seed=4, thick=(30.0, 60.0))
    rt = _measure(z, edges, rts)
    ref = _reference(z, edges, rts)
    r = _run(z, rt, ref, DeconParams())
    assert not r.valid.any()
    assert r.counts["undersampled"] == z.size
    assert any(i[0] == "LRLC_DECON_UNDERSAMPLED" for i in r.issues)


def test_no_reference_and_no_rt_and_unordered_depth():
    z, rt, ref, edges, rts, bed = _well()
    r = _run(z, rt, np.full(z.size, np.nan), DeconParams())
    assert r.counts["no_hires"] == z.size and not r.valid.any()
    assert r.issues[0][0] == "LRLC_DECON_NO_HIRES"
    assert _run(z, rt, None, DeconParams()).counts["no_hires"] == z.size
    r = _run(z, np.full(z.size, np.nan), ref, DeconParams())
    assert r.counts["no_rt"] == z.size and r.issues[0][0] == "LRLC_DECON_NO_RT"
    r = _run(z[::-1], rt[::-1], ref[::-1], DeconParams())
    assert r.counts["no_rt"] == z.size and "not ascending" in r.issues[0][1]
    assert not r.valid.any()


def test_non_positive_reference_is_unusable_in_log_domain():
    z, rt, ref, edges, rts, bed = _well()
    r = _run(z, rt, np.zeros(z.size), DeconParams())
    assert r.counts["no_hires"] == z.size


def test_active_rows_only_and_data_mask():
    z, rt, ref, edges, rts, bed = _well()
    p = _exact(DeconParams(lam=1e-4), z, ref, edges)
    full = _run(z, rt, ref, p)
    active = (z > 100.0) & (z < 200.0)
    part = deconvolve(z, rt, ref, p, active)
    assert not part.valid[~active].any()
    both = active & full.valid & part.valid
    assert both.sum() > 0.8 * active.sum()
    assert np.max(np.abs(part.rt_decon[both] / full.rt_decon[both] - 1.0)) < 0.05
    mask = np.ones(z.size, dtype=bool)
    mask[(z > 140.0) & (z < 143.0)] = False
    masked = deconvolve(z, rt, ref, p, np.ones(z.size, dtype=bool), data_mask=mask)
    assert np.all(np.isnan(masked.rt_decon[~mask]))
    assert masked.valid[(z > 20.0) & (z < 100.0)].mean() > 0.9


# ---------------------------------------------------------------------------
# Windows, steps, counts
# ---------------------------------------------------------------------------
def test_window_seam_matches_single_window():
    z, rt, ref, edges, rts, bed = _well(n_beds=15, noise=0.02)
    base = _exact(DeconParams(lam=1e-3), z, ref, edges)
    single = _run(z, rt, ref, replace(base, window_ft=1000.0))
    multi = _run(z, rt, ref, replace(base, window_ft=100.0))
    assert len(single.windows) == 1 and len(multi.windows) >= 3
    both = single.valid & multi.valid
    assert both.sum() > 0.9 * single.valid.sum()
    assert np.max(np.abs(multi.rt_decon[both] / single.rt_decon[both] - 1.0)) < 0.01


def test_irregular_step_still_recovers_and_is_reported():
    edges, rts = _beds(12, seed=5)
    rng = np.random.default_rng(6)
    z = np.cumsum(rng.uniform(0.3, 0.7, int(edges[-1] / 0.5)))
    z = z[z < edges[-1]]
    rt = _measure(z, edges, rts)
    ref = _reference(z, edges, rts, noise=0.0)
    bed = np.searchsorted(edges[1:-1], z, side="right")
    p = _exact(DeconParams(lam=1e-4, noise_rel=0.005), z, ref, edges)
    r = _run(z, rt, ref, p)
    assert r.counts["step_irregular"] == 1
    assert any(i[0] == "LRLC_DECON_STEP_IRREGULAR" for i in r.issues)
    err = np.abs(r.rt_decon[r.valid] / rts[bed][r.valid] - 1.0)
    assert r.valid.sum() > 0.8 * z.size and np.percentile(err, 95) < 0.03


def test_multiplicative_cap_reports_not_converged():
    z, rt, ref, edges, rts, bed = _well()
    p = _exact(DeconParams(solver="mult", mult_max_iter=3, noise_rel=1e-6), z, ref, edges)
    r = _run(z, rt, ref, p)
    assert r.counts["not_converged"] >= 1
    assert any(i[0] == "LRLC_DECON_NOT_CONVERGED" for i in r.issues)
    assert r.valid.any()                                              # values kept


def test_more_than_150_beds_splits_the_window():
    edges = np.concatenate([[0.0], np.cumsum(np.full(320, 4.0))])
    rts = np.where(np.arange(320) % 2 == 0, 3.0, 12.0)
    z = np.arange(0.0, edges[-1], 0.25)
    rt = _measure(z, edges, rts, fwhm=1.0)
    ref = _reference(z, edges, rts, fwhm=0.5, noise=0.0)
    p = replace(DeconParams(fwhm_ft=1.0, window_ft=1000.0, overlap_ft=10.0, smooth_ft=0.25, min_bed_ft=1.0))
    r = _run(z, rt, ref, p)
    assert r.counts["window_split"] >= 1
    assert any(i[0] == "LRLC_DECON_WINDOW_SPLIT" for i in r.issues)
    assert all(win.n_beds <= decon.MAX_BEDS_PER_WINDOW for win in r.windows)


def test_boundary_edits_are_counted_and_used():
    z, rt, ref, edges, rts, bed = _well()
    auto = pick_beds(z, ref, DeconParams().with_reference("RXO"), True).boundaries
    p = replace(DeconParams(), edits={"add": [], "remove": [float(auto[3]) + 0.2, float(auto[0] + auto[1]) / 2.0]})
    r = _run(z, rt, ref, p)
    assert r.counts["edits_unmatched"] == 1
    assert any(i[0] == "LRLC_DECON_BED_EDIT_UNMATCHED" for i in r.issues)
    plain = _run(z, rt, ref, DeconParams())
    assert len(r.beds) == len(plain.beds) - 1


def test_issue_tuples_use_the_chain_shape_and_known_names():
    z, rt, ref, edges, rts, bed = _well()
    zones = np.where(z < 150.0, "UPPER", "LOWER").astype(object)
    r = _run(z, rt, ref, DeconParams(), zone_labels=zones)
    assert r.issues
    for item in r.issues:
        assert len(item) == 4 and item[0].startswith("LRLC_DECON_")
        assert item[2] in (None, "UPPER", "LOWER")
    assert set(r.counts) == set(decon.COUNT_KEYS)


def test_zone_stats_and_misfit_warning_by_zone():
    z, rt, ref, edges, rts, bed = _well(noise=0.02)
    zones = np.where(z < 150.0, "UPPER", "LOWER").astype(object)
    p = DeconParams(noise_rel=0.02)
    r = _run(z, rt, ref, p, zone_labels=zones, misfit_warn_by_zone={"UPPER": 1e-6})
    assert set(r.zone_stats) == {"UPPER", "LOWER"}
    assert r.zone_stats["UPPER"]["n_active"] == int((zones == "UPPER").sum())
    assert r.zone_stats["UPPER"]["misfit_rms"] > 0
    bad = [i for i in r.issues if i[0] == "LRLC_DECON_MISFIT"]
    assert bad and all(i[2] == "UPPER" for i in bad)


def test_inputs_are_not_modified_and_arrays_stay_aligned():
    z, rt, ref, edges, rts, bed = _well()
    act = np.ones(z.size, dtype=bool)
    mask = np.ones(z.size, dtype=bool)
    snapshot = [a.copy() for a in (z, rt, ref, act, mask)]
    p = DeconParams(edits={"add": [100.0], "remove": []})
    r = deconvolve(z, rt, ref, p, act, data_mask=mask)
    for before, after in zip(snapshot, (z, rt, ref, act, mask)):
        assert np.array_equal(before, after)
    assert p.edits == {"add": [100.0], "remove": []}
    assert r.rt_decon.shape == r.valid.shape == z.shape
    assert np.array_equal(np.isfinite(r.rt_decon), r.valid)


def test_doll_response_deconvolves_too():
    edges, rts = _beds(8, seed=7, thick=(15.0, 40.0))
    z = np.arange(0.0, edges[-1], 0.25)
    tops, bots = edges[:-1].copy(), edges[1:].copy()
    tops[0], bots[-1] = -np.inf, np.inf
    rt = 1.0 / (response_weights(z, tops, bots, 0.0, "doll", 3.333) @ (1.0 / rts))
    ref = _reference(z, edges, rts, noise=0.0)
    bed = np.searchsorted(edges[1:-1], z, side="right")
    p = DeconParams(response="doll", doll_spacing_ft=3.333, lam=1e-4, noise_rel=0.01)
    r = _run(z, rt, ref, _exact(p, z, ref, edges))
    err = np.abs(r.rt_decon[r.valid] / rts[bed][r.valid] - 1.0)
    assert r.valid.sum() > 0.8 * z.size and np.percentile(err, 95) < 0.03


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------
@pytest.mark.slow
def test_performance_budget_10000_samples():
    edges, rts = _beds(400, seed=11, thick=(5.0, 20.0))
    z = np.arange(0.0, 5000.0, 0.5)
    edges = edges[edges <= 5000.0]
    rts = rts[:len(edges) - 1]
    z = z[z < edges[-1]]
    rt = _measure(z, edges, rts, noise=0.02)
    ref = _reference(z, edges, rts)
    assert z.size >= 9000
    start = time.perf_counter()
    r = _run(z, rt, ref, DeconParams(noise_rel=0.02))
    elapsed = time.perf_counter() - start
    print(f"decon 10k samples: {elapsed:.2f} s, {len(r.beds)} beds, {len(r.windows)} windows")
    assert elapsed < 10.0
    assert len(r.beds) >= 300
    assert r.valid.mean() > 0.7

def test_pick_beds_dense_alternating_thin_beds():
    """Closely alternating 2 ft beds: every boundary is found (the noise estimate does not grow with the edges)."""
    edges = np.arange(201) * 2.0
    rts = np.where(np.arange(200) % 2 == 0, 2.0, 20.0)
    z = np.arange(0.0, edges[-1], 0.5)
    for noise in (0.0, 0.03):
        ref = _reference(z, edges, rts, noise=noise)
        pick = pick_beds(z, ref, replace(DeconParams(), smooth_ft=0.25).with_reference("RXO"), True)
        assert len(pick.boundaries) == 199
        assert np.max(np.abs(pick.boundaries - edges[1:-1])) < 1.0


def test_pick_beds_no_boundary_on_flat_noisy_curve():
    z = np.arange(0.0, 300.0, 0.5)
    for seed in range(30):
        rng = np.random.default_rng(seed)
        ref = 10.0 * (1.0 + 0.03 * rng.standard_normal(z.size))
        assert len(pick_beds(z, ref, DeconParams().with_reference("RXO"), True).boundaries) == 0
