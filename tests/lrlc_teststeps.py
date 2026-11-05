"""Test-only Rt chain steps (spec 4.9). Import ``register_test_steps`` in a test module:

    from tests.lrlc_teststeps import register_test_steps  # noqa: F401

The steps are put into ``chain.STEPS`` with ``monkeypatch.setitem`` (restored automatically).
``CALLS`` counts how often each step function ran (reset by the fixture).
"""

from collections import Counter

import numpy as np
import pytest

from modules.lrlc import chain
from modules.lrlc.chain import StepResult, StepSpec

RSH_REF = 2.0
CALLS = Counter()


def _ok(rt):
    return np.isfinite(rt)


def _identity(rt, ctx, prm):
    CALLS["test_identity"] += 1
    return StepResult(rt.copy(), _ok(rt), {}, {}, ())


def _scale(rt, ctx, prm):
    CALLS["test_scale"] += 1
    return StepResult(2.0 * rt, _ok(rt), {}, {}, ())


def _bad(rt, ctx, prm):
    CALLS["test_bad"] += 1
    out = rt.copy()
    out[0::4] = 0.0
    out[1::4] = -1.0
    out[2::4] = np.inf
    return StepResult(out, np.ones(len(rt), dtype=bool), {}, {}, ())


def _rsh(rt, ctx, prm):
    CALLS["test_rsh"] += 1
    return StepResult(rt * ctx.rsh / RSH_REF, _ok(rt), {}, {}, ("test_ref",))


def _extra(rt, ctx, prm):
    CALLS["test_extra"] += 1
    return StepResult(rt.copy(), _ok(rt), {"n": 1}, {"TEST_AUX": ctx.vsh.copy()}, ())


def _spec(name, order, column, fn, **kw):
    return StepSpec(name=name, order=order, column=column, fn=fn, label=name,
                    description=f"test step {name}", refs=(), **kw)


def build_test_specs():
    return {
        "test_identity": _spec("test_identity", 5, "RT_ID", _identity),
        "test_scale": _spec("test_scale", 6, "RT_X2", _scale),
        "test_rsh": _spec("test_rsh", 7, "RT_RSH", _rsh, varied=("rsh",)),
        "test_bad": _spec("test_bad", 8, "RT_BAD", _bad),
        "test_extra": _spec("test_extra", 9, "RT_EXTRA", _extra, extra_columns=("TEST_AUX",)),
    }


@pytest.fixture
def register_test_steps(monkeypatch):
    CALLS.clear()
    for name, spec in build_test_specs().items():
        monkeypatch.setitem(chain.STEPS, name, spec)
    return CALLS
