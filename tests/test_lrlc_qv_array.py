"""Per-sample Qv in Waxman-Smits and the sand basis / qv_values of ``_primary_sw``."""

import numpy as np
import pandas as pd

from modules.issue_codes import IssueLog
from modules.petrophysics import PetrophysicsCalculator
from modules.pipeline import (
    PARAM_DEFAULTS, SandBasis, _compute_porosity, _compute_vsh, _primary_sw,
)
from modules.statistics_utils import StatisticsUtils
from tests.golden.cases import build_case

ALL = ["Archie", "Indonesian", "Simandoux", "Waxman-Smits", "Dual-Water"]


def _synthetic(n=40):
    rng = np.random.default_rng(3)
    data = pd.DataFrame({"DEPTH": 1000 + 0.5 * np.arange(n),
                         "RT": rng.uniform(3, 60, n)})
    phit = pd.Series(rng.uniform(0.12, 0.3, n))
    return data, phit


def _ws(qv, data, phit):
    calc = PetrophysicsCalculator(data)
    calc.calculate_sw_waxman_smits("RT", phit, 0.05, 1.0, 2.0, 2.0, qv, 0.046, phie=phit)
    return calc.results["SW_WS"].to_numpy(), calc.results["SWT_WS"].to_numpy()


def test_scalar_equals_constant_array_bitwise():
    data, phit = _synthetic()
    sw_s, swt_s = _ws(0.3, data, phit)
    sw_a, swt_a = _ws(np.full(len(data), 0.3), data, phit)
    assert np.array_equal(sw_s, sw_a, equal_nan=True)
    assert np.array_equal(swt_s, swt_a, equal_nan=True)


def test_per_sample_array_matches_scalar_runs_at_each_value():
    data, phit = _synthetic()
    qv = np.full(len(data), 0.2)
    qv[::3] = 0.6
    sw, swt = _ws(qv, data, phit)
    sw_lo, swt_lo = _ws(0.2, data, phit)
    sw_hi, swt_hi = _ws(0.6, data, phit)
    hi = np.zeros(len(data), dtype=bool)
    hi[::3] = True
    assert np.array_equal(sw[hi], sw_hi[hi], equal_nan=True)
    assert np.array_equal(swt[hi], swt_hi[hi], equal_nan=True)
    assert np.array_equal(sw[~hi], sw_lo[~hi], equal_nan=True)
    assert np.array_equal(swt[~hi], swt_lo[~hi], equal_nan=True)
    assert not np.array_equal(sw_lo, sw_hi, equal_nan=True)


def _prepared():
    data, mapping, params, _ = build_case("defaults_whole_well")
    p = {**PARAM_DEFAULTS, **params, "sw_methods": ALL}
    w = IssueLog()

    def fresh():
        calc = PetrophysicsCalculator(data)
        vsh, _, _ = _compute_vsh(calc, StatisticsUtils(data), data, mapping, p, w)
        _compute_porosity(calc, vsh, data, mapping, p, w)
        return calc, vsh

    return data, mapping, p, fresh


def _run(**kw):
    data, mapping, p, fresh = _prepared()
    calc, vsh = fresh()
    out = _primary_sw(calc, data, mapping, p, vsh, p["rw"], p["rsh"], None, IssueLog(), **kw)
    return calc, vsh, out


def test_defaults_none_equal_plain_call():
    c1, _, o1 = _run()
    c2, _, o2 = _run(rt_values=None, qv_values=None, basis=None)
    pd.testing.assert_frame_equal(c1.results, c2.results)
    pd.testing.assert_series_equal(o1[0], o2[0])


def test_basis_equal_to_bulk_is_identical_and_qv_values_only_touch_ws():
    c0, vsh, _ = _run()
    n = len(c0.results)
    same = SandBasis(phie=c0.results["PHIE"].to_numpy(), phit=c0.results["PHIT"].to_numpy(),
                     vsh=vsh.to_numpy())
    c1, _, _ = _run(basis=same)
    pd.testing.assert_frame_equal(c0.results, c1.results)

    qv = np.full(n, PARAM_DEFAULTS["ws_qv"])
    c2, _, _ = _run(qv_values=qv)
    pd.testing.assert_frame_equal(c0.results, c2.results)
    c3, _, _ = _run(qv_values=qv * 2)
    assert not c3.results["SW_WS"].equals(c0.results["SW_WS"])
    for col in ("SW_ARCHIE", "SW_INDO", "SW_SIMAN"):
        if col in c0.results:
            pd.testing.assert_series_equal(c3.results[col], c0.results[col])


def test_basis_phie_changes_archie_analytically():
    c0, vsh, _ = _run()
    basis = SandBasis(phie=c0.results["PHIE"].to_numpy() * 0.5,
                      phit=c0.results["PHIT"].to_numpy(), vsh=vsh.to_numpy())
    c1, _, out = _run(basis=basis)
    p = _prepared()[2]
    ratio = c1.results["SW_ARCHIE"] / c0.results["SW_ARCHIE"]
    ok = (np.isfinite(ratio) & (c0.results["SW_ARCHIE"] < 1) & (c1.results["SW_ARCHIE"] < 1)
          & (c1.results["SW_ARCHIE"] > 0))
    assert ok.any()
    # Archie: Sw = (a Rw / (phi^m Rt))^(1/n); halving phi scales Sw by 2^(m/n)
    assert np.allclose(ratio[ok], 2 ** (p["m"] / p["n"]))
    # the returned (bulk) porosity is untouched
    pd.testing.assert_series_equal(out[1], c0.results["PHIE"])
