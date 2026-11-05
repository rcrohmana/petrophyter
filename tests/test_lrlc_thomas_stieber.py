"""Thomas-Stieber decomposition (modules/lrlc/thomas_stieber.py), pure array tests."""

import numpy as np
import pytest

from modules.lrlc.config import THOMAS_STIEBER_DEFAULTS
from modules.lrlc.thomas_stieber import (
    check_endpoints, decompose, propose_endpoints, zone_stats,
)
from modules.param_scopes import UNZONED

S = dict(THOMAS_STIEBER_DEFAULTS)
PM, PS = 0.35, 0.10


def dec(vsh, phit, pm=PM, ps=PS, settings=S):
    return decompose(np.atleast_1d(vsh), np.atleast_1d(phit), pm, ps, settings)


def test_closed_form_vs_forward_model_random():
    rng = np.random.default_rng(7)
    n = 400
    pm = rng.uniform(0.2, 0.4, n)
    ps = rng.uniform(0.02, 0.12, n)
    vlam = rng.uniform(0.0, 0.6, n)
    vds = rng.uniform(0.0, 0.5, n)
    phi_sand = pm - vds * (1 - ps)
    phit = (1 - vlam) * phi_sand + vlam * ps
    vsh = vlam + (1 - vlam) * vds
    # loose class window so every point is evaluated (clamps would not trigger anyway)
    s = dict(S, class_vsh_min=0.0, class_vsh_max=1.0)
    r = decompose(vsh, phit, pm, ps, s)
    ok = (vsh <= 1.0) & (vds <= pm)
    assert ok.sum() > 100
    np.testing.assert_allclose(r.vlam[ok], vlam[ok], atol=1e-9)
    np.testing.assert_allclose(r.vdisp[ok], (vsh - vlam)[ok], atol=1e-9)
    np.testing.assert_allclose(r.phi_sand[ok], phi_sand[ok], atol=1e-9)
    # equivalent form of phi_sand for unclamped points
    alt = (phit - r.vlam * ps) / (1 - r.vlam)
    np.testing.assert_allclose(r.phi_sand[ok], alt[ok], atol=1e-9)


@pytest.mark.parametrize("vsh,phit,expected", [
    (0.0, PM, 0.0),                  # clean sand vertex
    (1.0, PS, 1.0),                  # shale vertex
    (PM, PM * PS, 0.0),              # dispersed apex
    (0.4, 0.25, 0.4),                # laminar line
    (0.2, 0.17, 0.0),                # dispersed line
])
def test_identities(vsh, phit, expected):
    r = dec(vsh, phit)
    assert r.vlam[0] == pytest.approx(expected, abs=1e-12)


def test_apex_to_shale_line():
    for vsh in (0.5, 0.7, 0.9):
        r = dec(vsh, vsh * PS)
        assert r.vlam[0] == pytest.approx((vsh - PM) / (1 - PM), abs=1e-12)


def test_worked_example():
    r = dec(0.44, 0.149)
    assert r.vlam[0] == pytest.approx(0.30, abs=1e-12)
    assert r.vdisp[0] == pytest.approx(0.14, abs=1e-12)
    assert r.phi_sand[0] == pytest.approx(0.17, abs=1e-12)
    assert r.phi_sand[0] == pytest.approx((0.149 - 0.30 * PS) / 0.70, abs=1e-12)
    assert r.ts_class[0] == 3          # f = 0.68: mixed


def test_classes():
    # laminar: on the laminar line
    assert dec(0.4, 0.25).ts_class[0] == 1
    # dispersed: on the dispersed line
    assert dec(0.2, 0.17).ts_class[0] == 2
    # structural: porosity above the laminar line
    r = dec(0.4, 0.31)
    assert r.ts_class[0] == 4
    assert r.vlam[0] == pytest.approx(0.4)
    assert r.counts["clamped"]["structural"] == 1
    # clay-supported: below the apex-to-shale line (Vsh > phi_max)
    r = dec(0.6, 0.02)
    assert r.ts_class[0] == 5
    assert r.vlam[0] == pytest.approx((0.6 - PM) / (1 - PM))
    assert r.counts["clamped"]["clay_supported"] == 1
    # below dispersed line with Vsh <= phi_max: dispersed, counted
    r = dec(0.2, 0.05)
    assert r.ts_class[0] == 2
    assert r.vlam[0] == pytest.approx(0.0)
    assert r.counts["clamped"]["below_dispersed"] == 1
    # clean and shale are class 0 but keep a VLAM value
    r = dec([0.02, 0.97], [0.34, 0.11])
    assert list(r.ts_class) == [0, 0]
    assert np.all(np.isfinite(r.vlam))
    assert 0.0 <= r.vlam[0] <= 0.02


def test_nan_and_missing_endpoints():
    r = dec([np.nan, 0.3, 1.5, -0.1, 0.4], [0.2, np.nan, 0.1, 0.2, 0.25])
    assert np.all(np.isnan(r.vlam[:4]))
    assert r.ts_class[:4].tolist() == [0, 0, 0, 0]
    assert r.counts["nan_input"] == 4
    assert r.vlam[4] == pytest.approx(0.4)
    r = dec([0.3, 0.4], [0.2, 0.25], pm=np.array([np.nan, PM]), ps=PS)
    assert np.isnan(r.vlam[0]) and np.isfinite(r.vlam[1])
    assert r.counts["no_endpoints"] == 1
    r = dec([0.3], [0.2], pm=None, ps=None)
    assert np.isnan(r.vlam[0]) and r.counts["no_endpoints"] == 1


def test_array_scalar_parity():
    rng = np.random.default_rng(3)
    vsh = rng.uniform(0.0, 1.0, 200)
    phit = rng.uniform(0.0, 0.4, 200)
    a = decompose(vsh, phit, PM, PS, S)
    b = decompose(vsh, phit, np.full(200, PM), np.full(200, PS), S)
    np.testing.assert_array_equal(a.vlam, b.vlam)
    np.testing.assert_array_equal(a.phi_sand, b.phi_sand)
    np.testing.assert_array_equal(a.ts_class, b.ts_class)
    for i in (0, 17, 99):
        one = decompose(vsh[i:i + 1], phit[i:i + 1], PM, PS, S)
        assert one.ts_class[0] == a.ts_class[i]
        np.testing.assert_allclose(one.vlam[0], a.vlam[i], equal_nan=True)
    assert a.counts["classes"][0] + sum(a.counts["classes"][c] for c in range(1, 6)) == 200


def test_check_endpoints():
    assert check_endpoints(0.35, 0.10) == (True, None)
    assert not check_endpoints(0.35, 0.34)[0]
    assert not check_endpoints(0.35, 0.33)[0]
    assert check_endpoints(0.35, 0.32)[0]
    assert not check_endpoints(0.5, 0.1)[0]
    assert not check_endpoints(0.05, 0.0)[0]
    assert not check_endpoints(0.35, -0.01)[0]
    ok, reason = check_endpoints(None, 0.1)
    assert not ok and reason
    assert not check_endpoints(0.35, float("nan"))[0]


def _well(n_clean=60, n_shale=20, n_mid=20, clean_phi=0.30, shale_phi=0.12):
    vsh = np.r_[np.full(n_clean, 0.02), np.full(n_mid, 0.4), np.full(n_shale, 0.9)]
    phit = np.r_[np.linspace(clean_phi - 0.05, clean_phi, n_clean), np.full(n_mid, 0.2),
                 np.full(n_shale, shale_phi)]
    depth = np.arange(len(vsh)) * 0.5
    return vsh, phit, depth


def test_proposals_whole_well_and_percentile():
    vsh, phit, depth = _well()
    p = propose_endpoints(vsh, phit, depth, None, S)
    assert list(p) == [UNZONED]
    pr = p[UNZONED]
    assert pr.ok and pr.source == "well"
    assert pr.phi_max == pytest.approx(np.percentile(phit[vsh < 0.05], 90))
    assert pr.phi_sh == pytest.approx(0.12)
    assert pr.n_clean == 60 and pr.n_shale == 20


def test_proposals_zone_and_well_fallback():
    v1, p1, d1 = _well()
    v2, p2, d2 = _well(n_clean=5, n_shale=4, n_mid=3, clean_phi=0.28)
    vsh = np.r_[v1, v2]
    phit = np.r_[p1, p2]
    depth = np.arange(len(vsh)) * 0.5
    zones = np.array(["A"] * len(v1) + ["B"] * len(v2), dtype=object)
    p = propose_endpoints(vsh, phit, depth, zones, S)
    assert p["A"].source == "zone" and p["A"].ok
    assert p["B"].source == "well" and p["B"].ok     # B lacks samples: whole-well values
    clean = vsh < 0.05
    assert p["B"].phi_max == pytest.approx(np.percentile(phit[clean], 90))


def test_proposals_thickness_and_minimum_counts():
    vsh, phit, _ = _well()
    depth = np.arange(len(vsh)) * 0.1                # 60 clean samples = 6 ft < 15 ft
    pr = propose_endpoints(vsh, phit, depth, None, S)[UNZONED]
    assert not pr.ok and pr.source is None and pr.reason
    vsh, phit, depth = _well(n_shale=3)
    pr = propose_endpoints(vsh, phit, depth, None, S)[UNZONED]
    assert not pr.ok and "shale" in pr.reason


def test_proposal_failing_check_is_not_ok():
    vsh, phit, depth = _well(clean_phi=0.15, shale_phi=0.14)
    pr = propose_endpoints(vsh, phit, depth, None, S)[UNZONED]
    assert pr.source == "well" and not pr.ok and pr.reason


def test_zone_stats():
    vsh = np.array([0.5, 0.5, 0.05, 0.4, 0.4])
    vlam = np.array([0.4, 0.2, 0.0, np.nan, 0.1])
    cls = np.array([1, 3, 0, 0, 2])
    dz = np.array([1.0, 1.0, 1.0, 1.0, 2.0])
    zones = np.array(["A", "A", "A", "B", "B"], dtype=object)
    st = zone_stats(vsh, vlam, cls, dz, zones, 0.10)
    a, b = st["A"], st["B"]
    assert a["n"] == 2
    assert a["lam_share"] == pytest.approx((0.4 + 0.2) / (0.5 + 0.5))
    assert a["mean_vlam"] == pytest.approx(0.3)
    assert a["class_counts"][1] == 1 and a["class_counts"][3] == 1 and a["class_counts"][0] == 1
    assert b["n"] == 1                               # NaN VLAM sample excluded
    assert b["lam_share"] == pytest.approx(0.1 * 2 / (0.4 * 2))
    assert b["mean_vlam"] == pytest.approx(0.1)
    none = zone_stats(vsh, vlam, cls, dz, None, 0.9)[UNZONED]
    assert none["n"] == 0 and np.isnan(none["lam_share"]) and np.isnan(none["mean_vlam"])
