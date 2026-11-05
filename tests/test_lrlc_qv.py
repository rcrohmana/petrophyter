import numpy as np
import pytest

from modules.lrlc import qv


def test_conversion_example():
    assert qv.qv_from_cec(0.15 * 25.0, 2.65, 0.20) == pytest.approx(0.3975)


def test_estimate_and_out_of_range():
    vsh = np.array([0.15, 0.15, 0.15, 0.9, np.nan])
    phit = np.array([0.20, 0.02, np.nan, 0.05, 0.2])
    est, counts = qv.estimate_qv(vsh, phit, 25.0, 2.65, 0.03, 3.0)
    assert est[0] == pytest.approx(0.3975)
    assert np.isnan(est[1])          # phit below phi_min
    assert np.isnan(est[2])          # no input
    assert np.isnan(est[3])          # 0.9*25=22.5 -> Qv ~ 22.7 > qv_max
    assert np.isnan(est[4])
    assert counts["out_of_range"] == 2
    assert counts["no_input"] == 2


def test_fallback_count():
    est = np.array([0.4, np.nan, 0.1, np.nan])
    arr, n = qv.qv_for_model(est, 0.25)
    assert arr.tolist() == [0.4, 0.25, 0.1, 0.25]
    assert n == 2
    assert np.isnan(est[1])   # input untouched


def test_calibration_through_origin():
    vsh = np.array([0.1, 0.2, 0.4, 0.6, 0.8, 0.02])
    cec = 30.0 * vsh
    cec[-1] = 99.0                       # below min_vsh, ignored
    fit = qv.calibrate_cec_shale(cec, vsh)
    assert fit.ok and fit.n == 5
    assert fit.cec_shale == pytest.approx(30.0)
    assert fit.r2 == pytest.approx(1.0)
    noisy = cec.copy()
    noisy[:5] += np.array([1, -1, 1, -1, 1.0])
    f2 = qv.calibrate_cec_shale(noisy, vsh)
    assert f2.cec_shale == pytest.approx(np.sum(noisy[:5] * vsh[:5]) / np.sum(vsh[:5] ** 2))
    assert 0 < f2.r2 < 1


def test_calibration_too_few_pairs():
    fit = qv.calibrate_cec_shale([10, 20], [0.3, 0.5])
    assert not fit.ok and fit.n == 2 and "need 5" in fit.reason


def test_pair_core_cec():
    log_d = np.arange(1000.0, 1010.0, 0.5)
    log_v = np.linspace(0.1, 0.9, len(log_d))
    cec, vsh = qv.pair_core_cec([1000.1, 1004.0, 1020.0, np.nan], [5.0, 10.0, 7.0, 3.0],
                                log_d, log_v, 0.5)
    assert cec.tolist() == [5.0, 10.0]
    assert vsh[0] == pytest.approx(log_v[0])
    assert vsh[1] == pytest.approx(log_v[8])
    e, v = qv.pair_core_cec([1.0], [1.0], [], [], 0.5)
    assert e.size == 0 and v.size == 0
