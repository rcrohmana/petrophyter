"""Monte Carlo kernel budgets: 10 wells x 10k samples (spec section 3.4, scaled down to N = 100).

Measured on the dev machine (Ryzen AI 9 365, Anaconda 3.12, single thread, kernel only, wells
frozen beforehand, after a warm-up run); budgets keep 3x to 10x headroom:

* N = 100, Simandoux with n varying (all eight parameters enabled): 8.0 s, budget 20 s.
* N = 100, Archie (all eight parameters enabled): 1.3 s, budget 5 s.
* Simandoux n varying, N = 300 and N = 500 are measured by hand, not tested (23.6 s and 36.8 s).

MEASURED (seconds, run_monte_carlo including the tornado and statistics):
    Simandoux varying n: N = 100: 8.0 s   N = 300: 23.6 s   N = 500: 36.8 s (over the 30 s rule, so the default N is 300)
    Archie:              N = 100: 1.3 s
"""

import time

import pytest

from modules import uncertainty as U
from tests.golden.cases import FULL_MAPPING
from tests.test_perf_multiwell import N_WELLS, _well


def _frozen(sw_method):
    params = {"sw_methods": [sw_method], "sw_primary_method": sw_method}
    return [U.freeze_well(f"w{i}", f"W{i}", _well(i), FULL_MAPPING, params) for i in range(N_WELLS)]


def _cfg(n):
    cfg = U.UncertaintyConfig(n=n, seed=1)
    for name in U.PARAM_ORDER:
        lo, mid, hi = U.SUGGESTED_RANGES[name]
        cfg.distributions[name] = U.Distribution(
            name=name, enabled=True, kind="triangular", mode=U.DEFAULT_MODES[name],
            low=lo, mid=mid, high=hi)
    return cfg


def _timed(wells, n):
    U.run_monte_carlo(wells, _cfg(U.N_MIN))          # warm-up (imports, first solver calls)
    start = time.perf_counter()
    result = U.run_monte_carlo(wells, _cfg(n))
    elapsed = time.perf_counter() - start
    assert result is not None and result.n == n
    return elapsed


@pytest.mark.slow
def test_ten_wells_simandoux_varying_n_n100_under_20_seconds():
    assert _timed(_frozen("Simandoux"), 100) < 20.0


@pytest.mark.slow
def test_ten_wells_archie_n100_under_5_seconds():
    assert _timed(_frozen("Archie"), 100) < 5.0
