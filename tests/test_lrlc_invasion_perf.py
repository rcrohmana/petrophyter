"""Invasion inversion: performance and scaling (slow)."""

import time
import tracemalloc

import numpy as np
import pytest

from modules.lrlc.invasion import fit_invasion, forward_ra

R50 = (80.0, 45.0, 20.0)


def _synthetic(n, seed=7):
    rng = np.random.default_rng(seed)
    rt = np.exp(rng.uniform(np.log(0.5), np.log(100.0), n))
    ratio = np.where(rng.random(n) < 0.5, rng.uniform(0.05, 0.9, n), rng.uniform(1.1, 20.0, n))
    di = rng.uniform(10.0, 100.0, n)
    return rt, rt * ratio, di, ratio


def _fit(ra):
    return fit_invasion(ra[:, 0], ra[:, 1], ra[:, 2], r50=R50, p=2.5)


@pytest.mark.slow
def test_invasion_10k_samples():
    rt, rxo, di, ratio = _synthetic(10000)
    ra = forward_ra(rt, rxo, di, R50, 2.5)
    half = np.arange(10000) < 5000
    rng = np.random.default_rng(11)
    noisy = ra.copy()
    noisy[~half] *= np.exp(rng.normal(0.0, 0.02, (int((~half).sum()), 3)))

    _fit(noisy[:500])                                   # warm-up
    t0 = time.perf_counter()
    res = _fit(noisy)
    t_10k = time.perf_counter() - t0
    assert t_10k < 5.0

    t0 = time.perf_counter()
    _fit(noisy[:1000])
    t_1k = time.perf_counter() - t0
    assert t_1k < 0.15 * t_10k + 0.05

    tracemalloc.start()
    _fit(noisy)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 100 * 1024 * 1024

    clean = half & res.valid & np.isfinite(res.rt)
    err = np.abs(res.rt[clean] / rt[clean] - 1.0)
    assert np.median(err) < 1e-4

    away = (ratio < 0.87) | (ratio > 1.15)
    converged = res.status[away] != 2        # 2 = did not converge
    assert converged.mean() > 0.95
