"""Analytic hand-value and property tests for the core petrophysics formulas.

Every expected number below is worked out by hand from the textbook formula
(the arithmetic is in the comment beside it); none were produced by running the
calculator. Porosity is passed positionally to the Sw models because the
WS/DW porosity keyword is renamed in a later change.
"""

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings, strategies as st

from modules.petrophysics import PetrophysicsCalculator

TIGHT = 1e-9


def _calc(**cols):
    n = len(next(iter(cols.values())))
    data = pd.DataFrame({"DEPTH": np.arange(n, dtype=float) + 1000.0, **cols})
    return PetrophysicsCalculator(data)


def _sw(model, rt, phi, vsh=0.0, rw=0.1, a=1.0, m=2.0, n=2.0):
    """Run one Sw model on scalar/array inputs; phi is passed positionally."""
    rt = np.atleast_1d(np.asarray(rt, dtype=float))
    phi_s = pd.Series(np.broadcast_to(phi, rt.shape).astype(float))
    vsh_s = pd.Series(np.broadcast_to(vsh, rt.shape).astype(float))
    calc = _calc(RT=rt)
    if model == "archie":
        return np.asarray(calc.calculate_sw_archie("RT", phi_s, rw, a, m, n))
    if model == "indo":
        return np.asarray(
            calc.calculate_sw_indonesian("RT", phi_s, vsh_s, rw, 5.0, a, m, n)
        )
    if model == "siman":
        return np.asarray(
            calc.calculate_sw_simandoux("RT", phi_s, vsh_s, rw, 5.0, a, m, n)
        )
    if model == "ws":
        return np.asarray(
            calc.calculate_sw_waxman_smits("RT", phi_s, rw, a, m, n, 0.2, 1.0)
        )
    if model == "dw":
        return np.asarray(
            calc.calculate_sw_dual_water("RT", phi_s, rw, a, m, n, 0.1, 0.2)
        )
    raise AssertionError(model)


MODELS = ["archie", "indo", "siman", "ws", "dw"]


# ---------------------------------------------------------------------------
# Vshale
# ---------------------------------------------------------------------------
class TestVshaleHandValues:
    def test_linear_igr(self):
        # IGR = (GR - GRmin)/(GRmax - GRmin), GRmin 30, GRmax 90
        # GR 30 -> 0 ; GR 45 -> 15/60 = 0.25 ; GR 60 -> 30/60 = 0.5 ; GR 90 -> 1
        calc = _calc(GR=[30.0, 45.0, 60.0, 90.0])
        vsh = np.asarray(calc.calculate_vshale_linear("GR", gr_min=30.0, gr_max=90.0))
        assert vsh == pytest.approx([0.0, 0.25, 0.5, 1.0], rel=TIGHT, abs=TIGHT)

    def test_larionov_tertiary(self):
        calc = _calc(GR=[1.0])
        igr = pd.Series([0.0, 0.5, 1.0])
        out = np.asarray(calc.calculate_vshale_larionov_tertiary(igr))
        # Vsh = 0.083*(2^(3.7*IGR) - 1)
        # IGR 0   : 0.083*(1 - 1)            = 0
        # IGR 0.5 : 0.083*(2^1.85 - 1)       = 0.083*(3.60500 - 1) = 0.216215
        # IGR 1   : 0.083*(2^3.7 - 1)        = 0.083*(12.99604 - 1) = 0.995671
        assert out[0] == pytest.approx(0.0, abs=TIGHT)
        assert out[1] == pytest.approx(0.083 * (2**1.85 - 1), rel=TIGHT)
        assert out[1] == pytest.approx(0.216215, abs=1e-5)
        assert out[2] == pytest.approx(0.083 * (2**3.7 - 1), rel=TIGHT)
        assert out[2] == pytest.approx(0.995671, abs=1e-5)

    def test_larionov_older(self):
        calc = _calc(GR=[1.0])
        igr = pd.Series([0.0, 0.5, 1.0])
        out = np.asarray(calc.calculate_vshale_larionov_older(igr))
        # Vsh = 0.33*(2^(2*IGR) - 1)
        # IGR 0   : 0.33*(1 - 1) = 0
        # IGR 0.5 : 0.33*(2 - 1) = 0.33
        # IGR 1   : 0.33*(4 - 1) = 0.99
        assert out == pytest.approx([0.0, 0.33, 0.99], rel=TIGHT, abs=TIGHT)


# ---------------------------------------------------------------------------
# Porosity
# ---------------------------------------------------------------------------
class TestPorosityHandValues:
    def test_density(self):
        # PHID = (rho_ma - rho_b)/(rho_ma - rho_fl), rho_ma 2.65, rho_fl 1.0
        # rho_b 2.35 : 0.30/1.65 = 0.181818...
        # rho_b 2.20 : 0.45/1.65 = 0.272727...
        calc = _calc(RHOB=[2.35, 2.20])
        out = np.asarray(calc.calculate_porosity_density("RHOB", 2.65, 1.0))
        assert out == pytest.approx([0.30 / 1.65, 0.45 / 1.65], rel=TIGHT)
        assert out[0] == pytest.approx(0.181818, abs=1e-6)

    def test_neutron_as_code_defines(self):
        # Code convention: PHIN = NPHI - nphi_matrix (matrix response -0.02).
        # NPHI 0.25 -> 0.25 - (-0.02) = 0.27 ; NPHI 0.10 -> 0.12
        calc = _calc(NPHI=[0.25, 0.10])
        out = np.asarray(calc.calculate_porosity_neutron("NPHI", -0.02))
        assert out == pytest.approx([0.27, 0.12], rel=TIGHT)

    def test_sonic_wyllie(self):
        # PHIS = (dt - dt_ma)/(dt_fl - dt_ma), dt_ma 55.5, dt_fl 189
        # dt 100   : 44.5/133.5 = 1/3
        # dt 122.25: 66.75/133.5 = 0.5
        calc = _calc(DT=[100.0, 122.25])
        out = np.asarray(calc.calculate_porosity_sonic("DT", 55.5, 189.0))
        assert out == pytest.approx([1.0 / 3.0, 0.5], rel=TIGHT)


# ---------------------------------------------------------------------------
# Water saturation
# ---------------------------------------------------------------------------
class TestSwHandValues:
    def test_archie(self):
        # Sw = (a*Rw/(phi^m*Rt))^(1/n) = (1*0.1/(0.04*10))^0.5 = 0.25^0.5 = 0.5
        sw = _sw("archie", 10.0, 0.2)
        assert sw[0] == pytest.approx(0.5, rel=TIGHT)

    def test_archie_second_point(self):
        # a 1, m 2, n 2, Rw 0.1, phi 0.1, Rt 40:
        # (0.1/(0.01*40))^0.5 = 0.25^0.5 = 0.5
        assert _sw("archie", 40.0, 0.1)[0] == pytest.approx(0.5, rel=TIGHT)

    def test_archie_n3(self):
        # a 1, m 2, n 3, Rw 0.1, phi 0.2, Rt 10: (0.25)^(1/3) = 0.629960525
        sw = _sw("archie", 10.0, 0.2, n=3.0)
        assert sw[0] == pytest.approx(0.25 ** (1.0 / 3.0), rel=TIGHT)
        assert sw[0] == pytest.approx(0.6299605, abs=1e-7)

    def test_simandoux_vsh0_equals_archie(self):
        # B = Vsh/Rsh = 0 -> A*Sw^2 = 1/Rt -> Sw = sqrt(Rw*a/(phi^m Rt)) = 0.5
        assert _sw("siman", 10.0, 0.2, vsh=0.0)[0] == pytest.approx(0.5, rel=TIGHT)

    def test_simandoux_n3_vsh0_equals_archie(self):
        # Iterative brentq branch (n != 2): tolerance is the solver's, not 1e-9.
        sw = _sw("siman", 10.0, 0.2, vsh=0.0, n=3.0)
        assert sw[0] == pytest.approx(0.25 ** (1.0 / 3.0), rel=1e-6)

    def test_simandoux_shaly_closed_form(self):
        # n=2: A*Sw^2 + B*Sw - C = 0 with a 1, m 2, Rw 0.1, phi 0.2, Rt 10,
        # Vsh 0.2, Rsh 5:  A = 0.04/0.1 = 0.4 ; B = 0.2/5 = 0.04 ; C = 0.1
        # Sw = (-0.04 + sqrt(0.0016 + 4*0.4*0.1)) / (0.8)
        #    = (-0.04 + sqrt(0.1616)) / 0.8 = (-0.04 + 0.401995) / 0.8 = 0.452494
        sw = _sw("siman", 10.0, 0.2, vsh=0.2)
        assert sw[0] == pytest.approx((-0.04 + 0.1616 ** 0.5) / 0.8, rel=TIGHT)
        assert sw[0] == pytest.approx(0.452494, abs=1e-6)

    def test_indonesian_vsh0_equals_archie(self):
        # Vsh 0: 1/sqrt(Rt) = sqrt(phi^m/(a Rw)) * Sw^(n/2)
        # Sw = (1/sqrt(10) / sqrt(0.04/0.1))^(2/2) = sqrt(1/(10*0.4)) = 0.5
        assert _sw("indo", 10.0, 0.2, vsh=0.0)[0] == pytest.approx(0.5, rel=TIGHT)

    def test_waxman_smits_tiny_qv_equals_archie(self):
        # Qv = 0 is rejected by the validator (must be > 0), so use Qv = 1e-12.
        # Then B*Qv/F* is ~1e-12 relative to Cw/F*; the iterative solve
        # (xtol 2e-12) is the limiting tolerance, hence rel=1e-6 not 1e-9.
        rt = np.array([10.0])
        calc = _calc(RT=rt)
        phi = pd.Series([0.2])
        sw = np.asarray(
            calc.calculate_sw_waxman_smits("RT", phi, 0.1, 1.0, 2.0, 2.0, 1e-12, 1.0)
        )
        assert sw[0] == pytest.approx(0.5, rel=1e-6)


# ---------------------------------------------------------------------------
# Swirr / permeability
# ---------------------------------------------------------------------------
class TestSwirrPermHandValues:
    def test_buckles(self):
        # Swirr = kb/phi = 0.02/0.1 = 0.2 ; 0.03/0.15 = 0.2 ; 0.02/0.2 = 0.1
        calc = _calc(RT=[1.0, 1.0, 1.0])
        out = np.asarray(
            calc.calculate_swirr_buckles(pd.Series([0.1, 0.2, 0.2]), 0.02)
        )
        assert out == pytest.approx([0.2, 0.1, 0.1], rel=TIGHT)
        out2 = np.asarray(calc.calculate_swirr_buckles(pd.Series([0.15]), 0.03))
        assert out2[0] == pytest.approx(0.2, rel=TIGHT)

    def test_timur(self):
        # K = 8581*phi^4.4/Swi^2 ; phi 0.1, Swi 0.5
        # = 8581 * 10^-4.4 / 0.25 = 34324 * 3.98107e-5 = 1.36645 mD
        calc = _calc(RT=[1.0])
        k = np.asarray(
            calc.calculate_permeability_timur(pd.Series([0.1]), pd.Series([0.5]))
        )
        assert k[0] == pytest.approx(34324.0 * 10 ** -4.4, rel=TIGHT)
        assert k[0] == pytest.approx(1.36645, abs=1e-4)

    def test_wyllie_rose(self):
        # K = C*phi^P/Swi^Q ; C 100, P 4.5, Q 2, phi 0.1, Swi 0.5
        # = 100 * 10^-4.5 / 0.25 = 400 * 3.162278e-5 = 0.0126491 mD
        calc = _calc(RT=[1.0])
        k = np.asarray(
            calc.calculate_permeability_wyllie_rose(
                pd.Series([0.1]), pd.Series([0.5]), C=100, P=4.5, Q=2.0
            )
        )
        assert k[0] == pytest.approx(400.0 * 10 ** -4.5, rel=TIGHT)
        assert k[0] == pytest.approx(0.0126491, abs=1e-7)


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("model", MODELS)
@settings(deadline=None, max_examples=25)
@given(
    phi=st.floats(0.02, 0.4),
    vsh=st.floats(0.0, 1.0),
    rw=st.floats(0.01, 1.0),
)
def test_nan_rt_propagates(model, phi, vsh, rw):
    sw = _sw(model, [np.nan, 10.0], phi, vsh=vsh, rw=rw)
    assert np.isnan(sw[0])


@pytest.mark.parametrize("model", MODELS)
@settings(deadline=None, max_examples=40)
@given(
    rt=st.floats(0.5, 2000.0),
    phi=st.floats(0.02, 0.4),
    vsh=st.floats(0.0, 1.0),
    rw=st.floats(0.01, 1.0),
)
def test_sw_within_unit_interval(model, rt, phi, vsh, rw):
    sw = _sw(model, rt, phi, vsh=vsh, rw=rw)
    assert np.all(np.isfinite(sw))
    assert np.all((sw >= 0.0) & (sw <= 1.0))


@settings(deadline=None, max_examples=100)
@given(igr=st.floats(0.0, 1.0))
def test_larionov_not_above_linear(igr):
    calc = _calc(GR=[1.0])
    s = pd.Series([igr])
    tert = float(calc.calculate_vshale_larionov_tertiary(s)[0])
    old = float(calc.calculate_vshale_larionov_older(s)[0])
    assert 0.0 <= tert <= igr + 1e-12
    assert 0.0 <= old <= igr + 1e-12


@settings(deadline=None, max_examples=50)
@given(
    gr=st.lists(st.floats(0.0, 300.0), min_size=2, max_size=20),
    lo=st.floats(10.0, 60.0),
    span=st.floats(10.0, 150.0),
)
def test_linear_vsh_within_unit_interval(gr, lo, span):
    calc = _calc(GR=gr)
    vsh = np.asarray(calc.calculate_vshale_linear("GR", gr_min=lo, gr_max=lo + span))
    assert np.all((vsh >= 0.0) & (vsh <= 1.0))
