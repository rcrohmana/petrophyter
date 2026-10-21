"""classify_pairs: rock type of loose (phi, k) pairs agrees with the core labels path."""

import numpy as np
import pytest

from modules import rock_typing as rt


def _defs(settings=None, method="fzi", fit_scope="project", zone_sets=None):
    centres = [-0.3, 0.1, 0.5]
    bounds = [(a + b) / 2 for a, b in zip(centres, centres[1:])]
    s = {"n_rt": 3, "centers": centres, "boundaries": bounds, "fzi": [10 ** c for c in centres],
         "feature_range": [-0.6, 0.8]}
    return {"method": method, "fit_scope": fit_scope, "set": s, "zone_sets": zone_sets or {},
            "settings": settings or {}}


def _pairs(n=40, seed=1):
    rng = np.random.default_rng(seed)
    phi = rng.uniform(0.08, 0.30, n)
    k = 10 ** rng.uniform(-1, 3, n)
    return phi, k


def _core_input(phi, k):
    n = len(phi)
    return rt.CoreInput("W", "W", np.arange(n, dtype=float) + 1000.0, phi, k,
                        np.full(n, "(unzoned)", dtype=object), False)


@pytest.mark.parametrize("method", ["fzi", "r35"])
def test_agrees_with_core_labels(method):
    defs = _defs(method=method)
    if method == "r35":
        defs["set"] = rt.default_r35_set()
    phi, k = _pairs()
    labels, reasons = rt.classify_pairs(phi, k, defs)
    expected = rt.core_labels(_core_input(phi, k), defs)
    assert expected is not None
    got = {1000.0 + i: int(lab) for i, lab in enumerate(labels) if lab > 0}
    assert dict(zip(expected["depth"], expected["rt"])) == got
    assert (reasons == "ok").all()


def test_overburden_factors_applied():
    phi, k = _pairs()
    plain, _ = rt.classify_pairs(phi, k, _defs())
    scaled, _ = rt.classify_pairs(phi, k, _defs({"ob_k_factor": 0.2, "ob_phi_factor": 0.95}))
    direct, _ = rt.classify_pairs(phi * 0.95, k * 0.2, _defs())
    assert np.array_equal(scaled, direct)
    assert not np.array_equal(plain, scaled)


def test_exclusions_and_reasons():
    phi = np.array([0.2, 0.2, np.nan, 0.2, 0.6, 0.005, 0.2])
    k = np.array([100.0, 0.0, 50.0, np.nan, 50.0, 50.0, -3.0])
    labels, reasons = rt.classify_pairs(phi, k, _defs())
    assert list(reasons) == ["ok", "perm_not_positive", "no_porosity", "no_perm",
                             "phi_out_of_range", "phi_out_of_range", "perm_not_positive"]
    assert labels[0] > 0 and (labels[1:] == 0).all()


def test_zone_sets_used_per_pair():
    other = dict(_defs()["set"], boundaries=[-5.0, -4.0])      # everything lands in class 3
    defs = _defs(zone_sets={"B": other})
    phi, k = _pairs(10)
    zone = np.array(["A", "B"] * 5, dtype=object)
    labels, _ = rt.classify_pairs(phi, k, defs, zone=zone)
    base, _ = rt.classify_pairs(phi, k, defs)
    assert (labels[1::2] == 3).all()
    assert np.array_equal(labels[0::2], base[0::2])
    single, _ = rt.classify_pairs(phi, k, defs, zone="B")
    assert (single == 3).all()


def test_zone_scoped_helper():
    assert rt.rock_types_zone_scoped(_defs(fit_scope="zone"))
    assert not rt.rock_types_zone_scoped(_defs(fit_scope="project"))
    assert not rt.rock_types_zone_scoped(None)


def test_no_definitions_gives_unassigned():
    labels, reasons = rt.classify_pairs([0.2], [10.0], {"set": None, "settings": {}})
    assert labels[0] == 0 and reasons[0] == "ok"
