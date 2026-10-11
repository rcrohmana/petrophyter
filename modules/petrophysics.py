"""
Petrophysics Calculations Module for Petrophyter
Core calculations for Vshale, Porosity, Sw, and Permeability
"""

import numpy as np
import pandas as pd
from typing import Dict, Tuple, Optional
from scipy.optimize import brentq

from modules.statistics_utils import gr_baseline_from_series


def _vectorized_brentq(func, lo, hi, active, xtol=2e-12,
                       rtol=4 * np.finfo(float).eps, maxiter=100):
    """Brent's root finder run on every element at once.

    A line-for-line vectorised port of scipy's ``brentq`` (same iterates, so
    results match the scalar solver bit for bit). ``func`` maps an array of
    abscissae to function values; ``lo``/``hi`` are scalar bracket ends and
    ``active`` flags the elements whose bracket holds a sign change (the
    others are left at ``lo``). Returns ``(roots, failed)`` where ``failed``
    flags elements that did not converge within ``maxiter``.
    """
    n = active.shape
    xpre = np.full(n, float(lo))
    xcur = np.full(n, float(hi))
    fpre = func(xpre)
    fcur = func(xcur)
    xblk = np.zeros(n)
    fblk = np.zeros(n)
    spre = np.zeros(n)
    scur = np.zeros(n)
    out = xpre.copy()
    done = ~active
    zero_lo = active & (fpre == 0)
    out[zero_lo] = xpre[zero_lo]
    zero_hi = active & ~zero_lo & (fcur == 0)
    out[zero_hi] = xcur[zero_hi]
    done = done | zero_lo | zero_hi

    for _ in range(maxiter):
        if done.all():
            break
        # New bracket when the sign changed
        flip = (fpre != 0) & (fcur != 0) & (np.signbit(fpre) != np.signbit(fcur))
        xblk = np.where(flip, xpre, xblk)
        fblk = np.where(flip, fpre, fblk)
        spre = np.where(flip, xcur - xpre, spre)
        scur = np.where(flip, xcur - xpre, scur)

        swap = np.abs(fblk) < np.abs(fcur)
        xpre_n = np.where(swap, xcur, xpre)
        xcur_n = np.where(swap, xblk, xcur)
        xblk = np.where(swap, xpre_n, xblk)
        fpre_n = np.where(swap, fcur, fpre)
        fcur_n = np.where(swap, fblk, fcur)
        fblk = np.where(swap, fpre_n, fblk)
        xpre, xcur, fpre, fcur = xpre_n, xcur_n, fpre_n, fcur_n

        delta = (xtol + rtol * np.abs(xcur)) / 2
        sbis = (xblk - xcur) / 2
        conv = ~done & ((fcur == 0) | (np.abs(sbis) < delta))
        out[conv] = xcur[conv]
        done = done | conv
        if done.all():
            break

        interp = (np.abs(spre) > delta) & (np.abs(fcur) < np.abs(fpre))
        secant = xpre == xblk
        stry_sec = -fcur * (xcur - xpre) / (fcur - fpre)
        dpre = (fpre - fcur) / (xpre - xcur)
        dblk = (fblk - fcur) / (xblk - xcur)
        stry_iqi = -fcur * (fblk * dblk - fpre * dpre) / (dblk * dpre * (fblk - fpre))
        stry = np.where(secant, stry_sec, stry_iqi)
        accept = interp & (
            2 * np.abs(stry) < np.minimum(np.abs(spre), 3 * np.abs(sbis) - delta)
        )
        spre_n = np.where(accept, scur, sbis)
        scur_n = np.where(accept, stry, sbis)
        spre, scur = spre_n, scur_n

        xpre = xcur
        fpre = fcur
        step = np.where(np.abs(scur) > delta, scur, np.where(sbis > 0, delta, -delta))
        xcur_new = xcur + step
        fcur_new = func(xcur_new)
        # Freeze finished elements
        xcur = np.where(done, xcur, xcur_new)
        fcur = np.where(done, fcur, fcur_new)

    # Elements that never converged mirror brentq raising: NaN + failed flag.
    failed = ~done
    return np.where(failed, np.nan, out), failed


# How PHID and PHIN are combined into PHIT / PHIE_DN.
DN_COMBINATIONS = ("Average", "RMS")

# A depth interval larger than GAP_STEP_FACTOR x the local logging step is a
# non-physical gap (e.g. Per-Formation mode selecting non-adjacent formations).
# Chosen > 2 so legitimate variable sampling (e.g. a 0.5 ft -> 1.0 ft
# transition) is preserved.
GAP_STEP_FACTOR = 3.0
# Number of depth intervals in the centred window that defines the local step.
DEPTH_STEP_WINDOW = 11


def depth_increments(depth) -> pd.Series:
    """Thickness represented by each sample, with local gap detection.

    1. Intervals ``d[i] - d[i-1]`` (absolute). The local step is the centred
       rolling median of the positive intervals over :data:`DEPTH_STEP_WINDOW`
       intervals, so a log that changes step (0.1524 ft to 0.5 ft) is read
       correctly on both sides.
    2. An interval larger than :data:`GAP_STEP_FACTOR` times the local step is a
       gap (for example the jump between non-adjacent formations); it is
       replaced by the local step.
    3. Midpoint rule: a sample's thickness is half the interval above plus half
       the interval below. The first and last samples take their one interval.

    Returns a float Series with the index of ``depth`` (zeros for fewer than
    two samples). On a uniform step every sample gets that step.
    """
    index = depth.index if isinstance(depth, pd.Series) else None
    values = np.asarray(depth, dtype=float)
    out = np.zeros(values.size)
    if values.size > 1:
        delta = np.abs(np.diff(values))
        positive = pd.Series(np.where(delta > 0, delta, np.nan))
        local = positive.rolling(DEPTH_STEP_WINDOW, center=True, min_periods=1).median()
        overall = positive.median()
        local = local.fillna(overall if np.isfinite(overall) else 0.0).to_numpy()
        with np.errstate(invalid="ignore"):
            gap = delta > GAP_STEP_FACTOR * local
        delta = np.where(gap | ~np.isfinite(delta), local, delta)
        out[0], out[-1] = delta[0], delta[-1]
        out[1:-1] = (delta[:-1] + delta[1:]) / 2.0
    return pd.Series(out, index=index)


def swirr_buckles(phi, k_buckles):
    """Buckles irreducible water saturation, Swirr = K_buckles / PHI.

    The one formula used by the pipeline and by core permeability calibration:
    porosity is floored at 0.01 (no division by a tiny number) and Swirr is
    clipped to [0.05, 0.5].
    """
    return np.clip(k_buckles / np.maximum(phi, 0.01), 0.05, 0.5)


def pay_summary(gross_flag, res_flag, pay_flag, vsh, phie, sw, dz) -> Dict[str, float]:
    """Thicknesses and weighted pay averages from boolean flags and per-sample ``dz``.

    ``dz`` is a per-sample thickness array (see :func:`depth_increments`) or a
    scalar step. ``avg_phie_pay`` and ``avg_vsh_pay`` are thickness weighted,
    sum(x * dz) / sum(dz); ``avg_sw_pay`` is pore-volume weighted,
    sum(phie * sw * dz) / sum(phie * dz). ``phih_pay`` is sum(phie * dz) over pay.
    With no weight (a single sample) the arithmetic mean is used.
    """
    gross_flag, res_flag, pay_flag = (
        np.asarray(f, dtype=bool) for f in (gross_flag, res_flag, pay_flag))
    vsh, phie, sw = (np.asarray(x, dtype=float) for x in (vsh, phie, sw))
    dz = np.broadcast_to(np.asarray(dz, dtype=float), gross_flag.shape)
    gross = float(dz[gross_flag].sum())
    net_res = float(dz[res_flag].sum())
    net_pay = float(dz[pay_flag].sum())
    phih = 0.0
    if pay_flag.any():
        w, f, s, v = dz[pay_flag], phie[pay_flag], sw[pay_flag], vsh[pay_flag]
        phih = float((f * w).sum())
        if w.sum() > 0:
            avg_phi = float((f * w).sum() / w.sum())
            avg_vsh = float((v * w).sum() / w.sum())
        else:
            avg_phi, avg_vsh = float(f.mean()), float(v.mean())
        avg_sw = float((f * s * w).sum() / phih) if phih > 0 else float(s.mean())
    else:
        avg_phi = avg_sw = avg_vsh = np.nan
    return {
        "gross_sand": gross,
        "net_reservoir": net_res,
        "net_pay": net_pay,
        "ng_reservoir": float(net_res / gross if gross > 0 else 0),
        "ng_pay": float(net_pay / gross if gross > 0 else 0),
        "avg_phie_pay": avg_phi,
        "avg_sw_pay": avg_sw,
        "avg_vsh_pay": avg_vsh,
        "phih_pay": phih,
    }


# A porosity at or below this holds no hydrocarbon: every Sw model returns 1.0.
SW_MIN_POROSITY = 0.001
# Sw above this before clipping is counted at the upper bound; a water leg scatters
# a little above 1, so 1.0 itself would flag half of every water zone.
SW_UPPER_TOLERANCE = 1.05


def _effective_sw_detail(swt, phit, phie):
    """``(swe, masks)`` of :func:`effective_sw`; ``masks`` holds the counted cases."""
    swt_a, phit_a, phie_a = (np.asarray(x, dtype=float) for x in (swt, phit, phie))
    swt_a, phit_a, phie_a = np.broadcast_arrays(swt_a, phit_a, phie_a)
    known = np.isfinite(swt_a) & np.isfinite(phit_a) & np.isfinite(phie_a)
    no_porosity = known & (phie_a <= SW_MIN_POROSITY)
    usable = known & ~no_porosity
    with np.errstate(all="ignore"):
        bvh_model = phit_a * (1.0 - swt_a)
        exceeds = usable & (bvh_model > phie_a)
        bvh = np.where(exceeds, phie_a, bvh_model)
        swe = np.clip(1.0 - bvh / phie_a, 0.0, 1.0)
    swe = np.where(usable, swe, np.nan)
    swe = np.where(no_porosity, 1.0, swe)
    return swe, {
        "no_porosity": no_porosity,
        "bvh_exceeds_phie": exceeds,
        "phie_above_phit": usable & (phie_a > phit_a),
    }


def effective_sw(swt, phit, phie):
    """Effective water saturation from total saturation by hydrocarbon-volume conservation.

    The total-porosity models (Waxman-Smits, Dual-Water) solve ``Swt`` on
    ``PHIT``. The hydrocarbon volume they describe is ``PHIT * (1 - Swt)``; the
    effective saturation that reproduces it on ``PHIE`` is::

        BVH = min(PHIT * (1 - Swt), PHIE)
        Swe = 1 - BVH / PHIE

    For Dual-Water with ``PHIE = PHIT * (1 - Swb)`` this is the textbook
    ``(Swt - Swb) / (1 - Swb)`` (Clavier, Coates and Dumanoir 1984). The volume
    is exact when ``PHIT * (1 - Swt) <= PHIE``; otherwise the result never holds
    more hydrocarbon than either porosity allows (``Swe`` then reaches 0). A
    ``PHIE`` at or below 0.001 has no pore space: ``Swe`` is 1. Any NaN input
    gives NaN. Returns a Series when ``swt`` is one, otherwise an array.
    """
    swe = _effective_sw_detail(swt, phit, phie)[0]
    if isinstance(swt, pd.Series):
        return pd.Series(swe, index=swt.index)
    return swe


class PetrophysicsCalculator:
    """
    Petrophysics calculations engine.

    Implements:
    - Vshale (Linear GR method)
    - Porosity (Density, Neutron-Density, Sonic)
    - Water Saturation (Archie, Indonesian, Simandoux)
    - Permeability (Wyllie-Rose, Timur)
    """

    # See the module-level GAP_STEP_FACTOR and depth_increments().
    GAP_STEP_FACTOR = GAP_STEP_FACTOR

    # Minimum fraction of valid (non-NaN) samples a PHIE method must have before
    # it can be selected as the primary porosity. Guards against a mostly-broken
    # curve (e.g. partial DT) being chosen and leaving PHIE almost entirely NaN.
    MIN_METHOD_VALID_FRACTION = 0.5

    def __init__(self, data: pd.DataFrame):
        """
        Initialize calculator with log data.

        Args:
            data: DataFrame containing log curves
        """
        self.data = data.copy()
        self.results = pd.DataFrame(index=data.index)
        if "DEPTH" in data.columns:
            self.results["DEPTH"] = data["DEPTH"]
        # Per-method counts of solver fallbacks/failures, so callers can surface
        # how many points did not converge instead of failing silently.
        self.solver_diagnostics = {}
        # Per-sample boolean flags of each Sw model (``{"SW_ARCHIE": DataFrame}``):
        # samples at a bound, without pore space, without a root, and so on.
        # The pipeline sums them per zone into ``summary["solver_diagnostics"]``.
        self.sw_flags = {}
        # Per-sample flags and the info dict of the last Swirr calculation.
        self.swirr_flags = None
        self.swirr_info = None

    def _make_series(self, fill_value) -> pd.Series:
        """
        Create a Series with the correct index from self.data.

        This helper method ensures that fallback Series maintain proper
        index alignment, which is critical when data is filtered
        (e.g., Per-Formation mode with non-contiguous indices).

        Args:
            fill_value: The value to fill the series with (e.g., np.nan, 0, 0.15)

        Returns:
            pd.Series with the same index as self.data
        """
        return pd.Series([fill_value] * len(self.data), index=self.data.index)

    def _rw_values(self, rw):
        """Rw as a float, or as a float array aligned to the data rows.

        An array (or Series) Rw carries a per-sample value, e.g. Rw corrected
        to formation temperature (Arps); it must have one value per row.
        """
        if np.ndim(rw) == 0:
            return float(rw)
        values = np.asarray(rw, dtype=float)
        if values.shape != (len(self.data),):
            raise ValueError("rw array must have one value per data row")
        return values

    def _per_sample(self, value, name: str):
        """A scalar as a float, or an array aligned to the data rows (one value per row)."""
        if np.ndim(value) == 0:
            return float(value)
        values = np.asarray(value, dtype=float)
        if values.shape != (len(self.data),):
            raise ValueError(f"{name} array must have one value per data row")
        return values

    def _rsh_values(self, rsh):
        """Rsh as a float, or as a float array aligned to the data rows.

        Twin of :meth:`_rw_values`: an array carries a per-sample Rsh, e.g.
        shale resistivity corrected to formation temperature (Arps).
        """
        return self._per_sample(rsh, "rsh")

    @staticmethod
    def _validate_positive_parameter(name: str, value, allow_nan: bool = False):
        """Reject non-physical scalar/array parameters at formula boundaries."""
        try:
            values = np.asarray(value, dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must contain finite values greater than 0") from exc

        if values.size == 0:
            raise ValueError(f"{name} must contain finite values greater than 0")
        if allow_nan:
            invalid = np.isinf(values) | (np.isfinite(values) & (values <= 0))
        else:
            invalid = ~np.isfinite(values) | (values <= 0)
        if np.any(invalid):
            raise ValueError(f"{name} must contain finite values greater than 0")

    @staticmethod
    def _validate_nonnegative_parameter(name: str, value):
        """Reject negative or non-finite parameters where 0 is a valid limit (e.g. Qv of a clean sand)."""
        try:
            values = np.asarray(value, dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must contain finite values of 0 or more") from exc

        if values.size == 0 or np.any(~np.isfinite(values) | (values < 0)):
            raise ValueError(f"{name} must contain finite values of 0 or more")

    @staticmethod
    def _validate_gas_factor(name: str, value):
        """Require gas correction factors in the formula-safe range [0, 1)."""
        try:
            values = np.asarray(value, dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be finite and in the range [0, 1)") from exc
        if values.size == 0 or np.any(~np.isfinite(values)) or np.any(
            (values < 0) | (values >= 1)
        ):
            raise ValueError(f"{name} must be finite and in the range [0, 1)")

    # =========================================================================
    # VSHALE CALCULATIONS
    # =========================================================================

    def calculate_vshale_linear(
        self, gr_curve: str = "GR", gr_min: float = None, gr_max: float = None
    ) -> pd.Series:
        """
        Calculate Vshale using Linear GR method.

        Vsh = (GR - GR_min) / (GR_max - GR_min)

        Args:
            gr_curve: GR curve mnemonic
            gr_min: Clean sand GR (auto-calculated if None)
            gr_max: Pure shale GR (auto-calculated if None)

        Returns:
            Vshale series (0-1)
        """
        if gr_curve not in self.data.columns:
            return self._make_series(np.nan)

        gr = self.data[gr_curve]

        # An all-null GR curve has no baseline from which Vshale can be
        # defined. Return an aligned NaN series rather than asking NumPy for a
        # percentile of an all-NaN slice (which emits a RuntimeWarning).
        if gr.notna().sum() == 0:
            vsh = self._make_series(np.nan)
            self.results["VSH"] = vsh
            return vsh

        # Auto-derive baselines (single shared rule, including its minimum
        # separation check) only when the caller did not supply them. Explicit
        # baselines are used as given.
        if gr_min is None or gr_max is None:
            auto_min, auto_max = gr_baseline_from_series(gr)
            if gr_min is None:
                gr_min = auto_min
            if gr_max is None:
                gr_max = auto_max

        # Guard against zero (or inverted) separation, e.g. constant GR. Without
        # GR contrast Vshale is undefined, so return NaN rather than dividing by
        # zero (which would otherwise emit a silent warning and NaN result).
        if gr_max - gr_min <= 0:
            vsh = self._make_series(np.nan)
            self.results["VSH"] = vsh
            return vsh

        # Calculate Vshale
        vsh = (gr - gr_min) / (gr_max - gr_min)

        # Clip to 0-1 range
        vsh = np.clip(vsh, 0, 1)

        self.results["VSH"] = vsh
        return vsh

    def calculate_vshale_larionov_tertiary(self, igr: pd.Series) -> pd.Series:
        """
        Calculate Vshale using Larionov equation for Tertiary rocks.

        Vsh = 0.083 * (2^(3.7*IGR) - 1)

        Args:
            igr: GR index (linear Vsh)

        Returns:
            Vshale series
        """
        vsh = 0.083 * (np.power(2, 3.7 * igr) - 1)
        return np.clip(vsh, 0, 1)

    def calculate_vshale_larionov_older(self, igr: pd.Series) -> pd.Series:
        """
        Calculate Vshale using Larionov equation for older (consolidated) rocks.

        Vsh = 0.33 * (2^(2*IGR) - 1)

        Args:
            igr: GR index (linear Vsh)

        Returns:
            Vshale series
        """
        vsh = 0.33 * (np.power(2, 2 * igr) - 1)
        return np.clip(vsh, 0, 1)

    def calculate_all_vshale(
        self,
        gr_curve: str = "GR",
        gr_min: float = None,
        gr_max: float = None,
        methods: list = None,
    ) -> Dict[str, pd.Series]:
        """
        Calculate Vshale using multiple methods.

        Args:
            gr_curve: GR curve mnemonic
            gr_min: Clean sand GR baseline
            gr_max: Pure shale GR baseline
            methods: List of methods to calculate. Options:
                     'linear', 'larionov_tertiary', 'larionov_older'
                     If None, calculates all methods.

        Returns:
            Dictionary with Vshale for each method
        """
        if methods is None:
            methods = ["linear", "larionov_tertiary", "larionov_older"]

        # First calculate linear (IGR - Gamma Ray Index)
        igr = self.calculate_vshale_linear(gr_curve, gr_min, gr_max)

        results = {}

        if "linear" in methods:
            results["VSH_LINEAR"] = igr.copy()
            self.results["VSH_LINEAR"] = igr.copy()

        if "larionov_tertiary" in methods:
            vsh_tertiary = self.calculate_vshale_larionov_tertiary(igr)
            results["VSH_LARIO_TERT"] = vsh_tertiary
            self.results["VSH_LARIO_TERT"] = vsh_tertiary

        if "larionov_older" in methods:
            vsh_older = self.calculate_vshale_larionov_older(igr)
            results["VSH_LARIO_OLD"] = vsh_older
            self.results["VSH_LARIO_OLD"] = vsh_older

        # Set the default VSH from the FIRST selected method rather than relying
        # on the linear side-effect inside calculate_vshale_linear. Previously VSH
        # stayed Linear/IGR even when the user selected only Larionov, silently
        # feeding the wrong Vshale into every downstream PHIE/Sw/net-pay/HCPV
        # calculation.
        method_to_result_key = {
            "linear": "VSH_LINEAR",
            "larionov_tertiary": "VSH_LARIO_TERT",
            "larionov_older": "VSH_LARIO_OLD",
        }
        for method in methods:
            key = method_to_result_key.get(method)
            if key and key in results:
                self.results["VSH"] = results[key].copy()
                break

        return results

    # =========================================================================
    # POROSITY CALCULATIONS
    # =========================================================================

    def calculate_porosity_density(
        self, rhob_curve: str = "RHOB", rho_matrix: float = 2.65, rho_fluid: float = 1.0
    ) -> pd.Series:
        """
        Calculate density porosity (PHID).

        PHID = (RHO_ma - RHOB) / (RHO_ma - RHO_fl)

        Args:
            rhob_curve: Bulk density curve mnemonic
            rho_matrix: Matrix density (g/cc)
            rho_fluid: Fluid density (g/cc)

        Returns:
            Density porosity series
        """
        if rhob_curve not in self.data.columns:
            return self._make_series(np.nan)

        rhob = self.data[rhob_curve]

        phid = (rho_matrix - rhob) / (rho_matrix - rho_fluid)

        # Clip to reasonable range
        phid = np.clip(phid, -0.05, 0.50)

        self.results["PHID"] = phid
        return phid

    def calculate_porosity_neutron(
        self, nphi_curve: str = "NPHI", nphi_matrix: float = -0.02
    ) -> pd.Series:
        """
        Calculate neutron porosity (corrected).

        Args:
            nphi_curve: Neutron porosity curve mnemonic
            nphi_matrix: Matrix neutron porosity response

        Returns:
            Neutron porosity series
        """
        if nphi_curve not in self.data.columns:
            return self._make_series(np.nan)

        nphi = self.data[nphi_curve].copy()

        # Apply matrix correction if needed
        phin = nphi - nphi_matrix
        self._nphi_matrix_used = nphi_matrix

        # Clip to reasonable range
        phin = np.clip(phin, -0.05, 0.50)

        self.results["PHIN"] = phin
        return phin

    def calculate_porosity_sonic(
        self, dt_curve: str = "DT", dt_matrix: float = 55.5, dt_fluid: float = 189.0
    ) -> pd.Series:
        """
        Calculate sonic porosity using Wyllie time-average equation.

        PHIS = (DT - DT_ma) / (DT_fl - DT_ma)

        Args:
            dt_curve: Sonic transit time curve mnemonic
            dt_matrix: Matrix transit time (µs/ft)
            dt_fluid: Fluid transit time (µs/ft)

        Returns:
            Sonic porosity series
        """
        if dt_curve not in self.data.columns:
            return self._make_series(np.nan)

        dt = self.data[dt_curve]

        phis = (dt - dt_matrix) / (dt_fluid - dt_matrix)

        # Clip to reasonable range
        phis = np.clip(phis, 0, 0.50)

        self.results["PHIS"] = phis
        return phis

    @staticmethod
    def combine_density_neutron(a, b, dn_combination: str = "Average", rms_mask=None):
        """
        Combine two density / neutron porosities sample by sample.

        ``Average`` is the arithmetic mean (signs kept, liquid-filled formations);
        ``RMS`` is sqrt((a^2 + b^2) / 2). Samples in ``rms_mask`` (gas) always use
        RMS, the Gaymard-Poupon gas-zone total porosity.
        """
        if dn_combination not in DN_COMBINATIONS:
            raise ValueError(
                f"dn_combination must be one of {DN_COMBINATIONS}, got {dn_combination!r}"
            )
        a = np.asarray(a, dtype=float)
        b = np.asarray(b, dtype=float)
        mean = (a + b) / 2
        if dn_combination == "Average" and rms_mask is None:
            return mean
        rms = np.sqrt((a**2 + b**2) / 2)
        if dn_combination == "RMS":
            return rms
        return np.where(np.asarray(rms_mask, dtype=bool), rms, mean)

    def calculate_gas_flag(
        self,
        vsh: pd.Series = None,
        gas_crossover_min: float = 0.02,
        gas_vsh_max: float = 0.40,
    ) -> pd.Series:
        """
        Flag gas samples: (PHID - PHIN) >= gas_crossover_min and VSH <= gas_vsh_max.

        A bare crossover is noise within a few porosity units, and shale also
        crosses over, so a minimum separation and a Vsh gate are required.
        Samples with NaN in PHID, PHIN or Vsh are not flagged. Stored as the
        integer ``GAS_FLAG`` column and returned as a boolean Series.
        """
        phid = self.results.get("PHID", self._make_series(np.nan))
        phin = self.results.get("PHIN", self._make_series(np.nan))
        if vsh is None:
            vsh = self.results.get("VSH", self._make_series(0))
        flag = ((phid - phin) >= gas_crossover_min) & (vsh <= gas_vsh_max)
        flag = pd.Series(np.asarray(flag, dtype=bool), index=self.data.index)
        self.results["GAS_FLAG"] = flag.astype(int)
        return flag

    def calculate_phit_neutron_density(
        self,
        phid: pd.Series = None,
        phin: pd.Series = None,
        dn_combination: str = "Average",
        gas_flag: pd.Series = None,
    ) -> pd.Series:
        """
        Calculate total porosity from the density-neutron pair (and fallbacks).

        PHIT = (PHID + PHIN) / 2 (``Average``) or sqrt((PHID^2 + PHIN^2) / 2)
        (``RMS``); RMS on ``gas_flag`` samples whatever ``dn_combination``.
        Where only one of PHID / PHIN is present PHIT is that one; where neither,
        the sonic porosity PHIS; otherwise NaN. Clipped to [0, 0.45] after the
        combination, so a negative mean becomes 0.

        Args:
            phid: Density porosity series
            phin: Neutron porosity series
            dn_combination: "Average" or "RMS"
            gas_flag: Boolean series of gas samples (RMS there)

        Returns:
            Total porosity series
        """
        if phid is None:
            phid = self.results.get("PHID", self._make_series(np.nan))
        if phin is None:
            phin = self.results.get("PHIN", self._make_series(np.nan))
        phis = self.results.get("PHIS", self._make_series(np.nan))

        d = np.asarray(phid, dtype=float)
        n = np.asarray(phin, dtype=float)
        s = np.asarray(phis, dtype=float)
        both = np.isfinite(d) & np.isfinite(n)
        with np.errstate(invalid="ignore"):
            combined = self.combine_density_neutron(d, n, dn_combination, gas_flag)
        phit = np.where(
            both, combined,
            np.where(np.isfinite(d), d, np.where(np.isfinite(n), n, s)),
        )

        # Clip to reasonable range (NaN stays NaN)
        phit = pd.Series(np.clip(phit, 0, 0.45), index=self.data.index)

        self.results["PHIT"] = phit
        return phit

    def calculate_phie(
        self, phit: pd.Series = None, vsh: pd.Series = None
    ) -> pd.Series:
        """
        Calculate effective porosity from total porosity.

        PHIE = PHIT * (1 - Vsh)

        Args:
            phit: Total porosity series
            vsh: Vshale series

        Returns:
            Effective porosity series
        """
        if phit is None:
            phit = self.results.get("PHIT", self._make_series(np.nan))
        if vsh is None:
            vsh = self.results.get("VSH", self._make_series(0))

        phie = phit * (1 - vsh)

        # Clip to reasonable range
        phie = np.clip(phie, 0, 0.40)

        self.results["PHIE"] = phie
        return phie

    def calculate_phie_density(
        self,
        vsh: pd.Series = None,
        rhob_shale: float = 2.45,
        rho_matrix: float = 2.65,
        rho_fluid: float = 1.0,
    ) -> pd.Series:
        """
        Calculate effective porosity from density (PHIE_D).

        PHIE_D = PHID - (Vsh * PHID_shale)

        Args:
            vsh: Vshale series
            rhob_shale: Shale bulk density (g/cc)
            rho_matrix: Matrix density (g/cc)
            rho_fluid: Fluid density (g/cc)

        Returns:
            Effective density porosity series
        """
        phid = self.results.get("PHID", self._make_series(np.nan))
        if vsh is None:
            vsh = self.results.get("VSH", self._make_series(0))

        # Shale porosity from density
        phid_shale = (rho_matrix - rhob_shale) / (rho_matrix - rho_fluid)

        # Shale correction
        phie_d = phid - (vsh * phid_shale)
        phie_d = np.clip(phie_d, 0, 0.40)

        self.results["PHIE_D"] = phie_d
        return phie_d

    def _neutron_shale_porosity(self, nphi_shale: float, nphi_matrix: float = None) -> float:
        """Shale neutron response on the PHIN scale: NPHI_shale - NPHI_matrix."""
        if nphi_matrix is None:
            nphi_matrix = getattr(self, "_nphi_matrix_used", -0.02)
        return nphi_shale - nphi_matrix

    def calculate_phie_neutron(
        self, vsh: pd.Series = None, nphi_shale: float = 0.35, nphi_matrix: float = None
    ) -> pd.Series:
        """
        Calculate effective porosity from neutron (PHIE_N).

        PHIE_N = PHIN - Vsh * (NPHI_shale - NPHI_matrix)

        The shale response is shifted to the same matrix scale as PHIN, so pure
        shale gives 0.

        Args:
            vsh: Vshale series
            nphi_shale: Shale neutron porosity response
            nphi_matrix: Matrix neutron response used for PHIN (default: the one
                of the last ``calculate_porosity_neutron`` call)

        Returns:
            Effective neutron porosity series
        """
        phin = self.results.get("PHIN", self._make_series(np.nan))
        if vsh is None:
            vsh = self.results.get("VSH", self._make_series(0))

        # Shale correction
        phie_n = phin - (vsh * self._neutron_shale_porosity(nphi_shale, nphi_matrix))
        phie_n = np.clip(phie_n, 0, 0.40)

        self.results["PHIE_N"] = phie_n
        return phie_n

    def calculate_phie_sonic(
        self,
        vsh: pd.Series = None,
        dt_shale: float = 100.0,
        dt_matrix: float = 55.5,
        dt_fluid: float = 189.0,
    ) -> pd.Series:
        """
        Calculate effective porosity from sonic (PHIE_S).

        Apply shale correction to sonic porosity.

        Args:
            vsh: Vshale series
            dt_shale: Shale sonic transit time
            dt_matrix: Matrix sonic transit time
            dt_fluid: Fluid sonic transit time

        Returns:
            Effective sonic porosity series
        """
        phis = self.results.get("PHIS", self._make_series(np.nan))
        if vsh is None:
            vsh = self.results.get("VSH", self._make_series(0))

        # Shale porosity
        phi_shale = (dt_shale - dt_matrix) / (dt_fluid - dt_matrix)

        # Shale correction
        phie_s = phis - (vsh * phi_shale)
        phie_s = np.clip(phie_s, 0, 0.40)

        self.results["PHIE_S"] = phie_s
        return phie_s

    def calculate_phie_density_neutron(
        self,
        vsh: pd.Series = None,
        nphi_shale: float = 0.35,
        rhob_shale: float = 2.45,
        rho_matrix: float = 2.65,
        rho_fluid: float = 1.0,
        nphi_matrix: float = None,
        dn_combination: str = "Average",
        gas_flag: pd.Series = None,
    ) -> pd.Series:
        """
        Calculate effective porosity from density-neutron crossplot (PHIE_DN).

        Uses shale-corrected N-D crossplot, combined like PHIT (Average or RMS,
        RMS on gas-flagged samples).

        Args:
            vsh: Vshale series
            nphi_shale: Shale neutron porosity
            rhob_shale: Shale bulk density
            rho_matrix: Matrix density
            rho_fluid: Fluid density
            nphi_matrix: Matrix neutron response used for PHIN
            dn_combination: "Average" or "RMS"
            gas_flag: Boolean series of gas samples (RMS there)

        Returns:
            Effective density-neutron porosity series
        """
        phid = self.results.get("PHID", self._make_series(np.nan))
        phin = self.results.get("PHIN", self._make_series(np.nan))
        if vsh is None:
            vsh = self.results.get("VSH", self._make_series(0))

        # Shale porosity from density
        phid_shale = (rho_matrix - rhob_shale) / (rho_matrix - rho_fluid)

        # Corrected porosities
        phid_corr = phid - (vsh * phid_shale)
        phin_corr = phin - (vsh * self._neutron_shale_porosity(nphi_shale, nphi_matrix))

        # Clip negative values
        phid_corr = np.maximum(phid_corr, 0)
        phin_corr = np.maximum(phin_corr, 0)

        phie_dn = self.combine_density_neutron(
            phid_corr, phin_corr, dn_combination, gas_flag
        )
        phie_dn = pd.Series(np.clip(phie_dn, 0, 0.40), index=self.data.index)

        self.results["PHIE_DN"] = phie_dn
        return phie_dn

    def calculate_all_phie(
        self,
        vsh: pd.Series = None,
        nphi_shale: float = 0.35,
        rhob_shale: float = 2.45,
        dt_shale: float = 100.0,
        rho_matrix: float = 2.65,
        rho_fluid: float = 1.0,
        dt_matrix: float = 55.5,
        dt_fluid: float = 189.0,
        gas_correction: bool = False,
        gas_nphi_factor: float = 0.30,
        gas_rhob_factor: float = 0.15,
        primary_method: str = "PHIE_DN",
        nphi_matrix: float = None,
        dn_combination: str = "Average",
        gas_crossover_min: float = 0.02,
        gas_vsh_max: float = 0.40,
    ) -> Dict[str, pd.Series]:
        """
        Calculate all effective porosity methods.

        Args:
            vsh: Vshale series
            nphi_shale: Shale neutron porosity
            rhob_shale: Shale bulk density
            dt_shale: Shale sonic transit time
            rho_matrix: Matrix density
            rho_fluid: Fluid density
            dt_matrix: Matrix sonic transit time
            dt_fluid: Fluid sonic transit time
            gas_correction: Enable gas correction for PHIE
            gas_nphi_factor: Neutron gas correction factor (0.2-0.4 typical)
            gas_rhob_factor: Density gas correction factor (0.1-0.2 typical)
            primary_method: User's preferred PHIE method (PHIE_DN, PHIE_D, PHIE_N, PHIE_S, PHIE_GAS)
            nphi_matrix: Matrix neutron response used for PHIN (neutron shale correction)
            dn_combination: "Average" or "RMS" for PHIE_DN (RMS on gas samples)
            gas_crossover_min: Minimum PHID - PHIN to flag gas
            gas_vsh_max: Maximum Vsh for a gas flag

        Returns:
            Dictionary with all PHIE calculations
        """
        if vsh is None:
            vsh = self.results.get("VSH", self._make_series(0))

        # The gas flag exists whenever the correction is on, whatever the primary method.
        gas_flag = None
        if gas_correction:
            gas_flag = self.calculate_gas_flag(vsh, gas_crossover_min, gas_vsh_max)
        elif "GAS_FLAG" in self.results.columns:
            self.results.drop(columns=["GAS_FLAG"], inplace=True)

        # Reset the selected primary on every run so an unsuccessful reuse
        # cannot expose a PHIE series or method choice from an earlier run.
        if "PHIE" in self.results.columns:
            self.results.drop(columns=["PHIE"], inplace=True)
        self.phie_method_used = None

        results = {}
        results["PHIE_D"] = self.calculate_phie_density(
            vsh, rhob_shale, rho_matrix, rho_fluid
        )
        results["PHIE_N"] = self.calculate_phie_neutron(vsh, nphi_shale, nphi_matrix)
        results["PHIE_S"] = self.calculate_phie_sonic(
            vsh, dt_shale, dt_matrix, dt_fluid
        )
        results["PHIE_DN"] = self.calculate_phie_density_neutron(
            vsh, nphi_shale, rhob_shale, rho_matrix, rho_fluid,
            nphi_matrix, dn_combination, gas_flag,
        )

        # Gas correction (if enabled)
        if gas_correction:
            results["PHIE_GAS"] = self.calculate_phie_gas_corrected(
                vsh=vsh,
                nphi_shale=nphi_shale,
                rhob_shale=rhob_shale,
                rho_matrix=rho_matrix,
                rho_fluid=rho_fluid,
                gas_nphi_factor=gas_nphi_factor,
                gas_rhob_factor=gas_rhob_factor,
                nphi_matrix=nphi_matrix,
                gas_crossover_min=gas_crossover_min,
                gas_vsh_max=gas_vsh_max,
            )

        # Determine available methods. A method needs a meaningful fraction of
        # valid points (not just 1 of thousands) before it can be selected as
        # primary; otherwise a mostly-broken curve could make PHIE almost
        # entirely NaN with no warning.
        candidates = ["PHIE_DN", "PHIE_N", "PHIE_D", "PHIE_S", "PHIE_GAS"]

        def _valid_fraction(col):
            s = results.get(col)
            if s is None or len(s) == 0:
                return 0.0
            return float(s.notna().sum()) / float(len(s))

        available = [
            col
            for col in candidates
            if col in results and _valid_fraction(col) >= self.MIN_METHOD_VALID_FRACTION
        ]

        # Select primary PHIE based on user choice with fallback. If no method
        # clears the fraction bar, leave PHIE unset so callers can surface a
        # missing/insufficient porosity result instead of treating one valid
        # sample as a well-wide method.
        selected = None
        if primary_method in available:
            selected = primary_method
        else:
            # Fallback priority: PHIE_DN > PHIE_N > PHIE_D > PHIE_S > PHIE_GAS
            for fallback in candidates:
                if fallback in available:
                    selected = fallback
                    break

        self.phie_partial = None
        if selected:
            self.results["PHIE"] = results[selected]
            self.phie_method_used = selected  # Store which method was used
        else:
            # No method clears the bar: never fabricate porosity. PHIE is the
            # method with the largest valid fraction (first candidate on a
            # tie), NaN where it has no value, or all-NaN when none has any.
            present = [c for c in candidates if c in results]
            best = max(present, key=_valid_fraction, default=None)
            if best is not None and _valid_fraction(best) > 0:
                self.results["PHIE"] = results[best]
                self.phie_method_used = best
                self.phie_partial = (best, _valid_fraction(best))
            else:
                self.results["PHIE"] = pd.Series(np.nan, index=self.data.index)
                self.phie_method_used = None
                self.phie_partial = (None, 0.0)

        return results

    def calculate_phie_gas_corrected(
        self,
        vsh: pd.Series = None,
        nphi_shale: float = 0.35,
        rhob_shale: float = 2.45,
        rho_matrix: float = 2.65,
        rho_fluid: float = 1.0,
        gas_nphi_factor: float = 0.30,
        gas_rhob_factor: float = 0.15,
        nphi_matrix: float = None,
        gas_crossover_min: float = 0.02,
        gas_vsh_max: float = 0.40,
    ) -> pd.Series:
        """
        Calculate effective porosity with gas correction (PHIE_GAS).

        In gas zones, the neutron tool reads too low (gas has very low hydrogen index)
        and density tool reads too high (gas has low density). This method applies
        correction factors to compensate for the gas effect.

        Gas Correction Method:
        1. Detect gas zones: (PHID - PHIN) >= gas_crossover_min and VSH <= gas_vsh_max
        2. For gas zones:
           - PHIN_corrected = PHIN / (1 - gas_nphi_factor)
           - PHID_corrected = PHID * (1 - gas_rhob_factor)
        3. Calculate PHIE from corrected values with shale correction, averaged
           (the correction already removes the gas effect, so no RMS on top) and
           capped per sample at PHIT, then at 0.45

        Args:
            vsh: Vshale series
            nphi_shale: Shale neutron porosity response
            rhob_shale: Shale bulk density
            rho_matrix: Matrix density
            rho_fluid: Fluid density
            gas_nphi_factor: Neutron correction factor (0.2-0.4, higher = more correction)
            gas_rhob_factor: Density correction factor (0.1-0.2, higher = more correction)
            nphi_matrix: Matrix neutron response used for PHIN
            gas_crossover_min: Minimum PHID - PHIN to flag gas
            gas_vsh_max: Maximum Vsh for a gas flag

        Returns:
            Gas-corrected effective porosity series
        """
        self._validate_gas_factor("gas_nphi_factor", gas_nphi_factor)
        self._validate_gas_factor("gas_rhob_factor", gas_rhob_factor)

        phid = self.results.get("PHID", self._make_series(np.nan))
        phin = self.results.get("PHIN", self._make_series(np.nan))

        if vsh is None:
            vsh = self.results.get("VSH", self._make_series(0))

        # Shale porosity from density
        phid_shale = (rho_matrix - rhob_shale) / (rho_matrix - rho_fluid)

        # Detect gas zones: neutron below density by a minimum, in clean rock.
        # Gas effect causes PHIN to read low, PHID to read high
        gas_zone = self.calculate_gas_flag(vsh, gas_crossover_min, gas_vsh_max)
        gas_zone = np.asarray(gas_zone, dtype=bool)

        # Initialize corrected porosities
        phid_corr = phid.copy()
        phin_corr = phin.copy()

        # Apply gas correction only in gas zones.
        # Gas has low hydrogen index, so the neutron tool reads too LOW -> raise PHIN.
        # Gas lowers RHOB, so the density tool reads too HIGH (PHID over-read) -> reduce PHID.
        phin_corr = np.where(
            gas_zone,
            phin / (1 - gas_nphi_factor),  # Increase neutron in gas zones
            phin,
        )

        phid_corr = np.where(
            gas_zone,
            phid * (1 - gas_rhob_factor),  # Reduce over-read density porosity in gas
            phid,
        )

        # Apply shale correction
        phid_corr = phid_corr - (vsh * phid_shale)
        phin_corr = phin_corr - (vsh * self._neutron_shale_porosity(nphi_shale, nphi_matrix))

        # Clip negative values
        phid_corr = np.maximum(phid_corr, 0)
        phin_corr = np.maximum(phin_corr, 0)

        # Average of the corrected pair, never above that sample's total porosity
        phie_gas = (phid_corr + phin_corr) / 2
        phit = self.results.get("PHIT")
        if phit is not None:
            phit = np.asarray(phit, dtype=float)
            phie_gas = np.where(np.isfinite(phit), np.minimum(phie_gas, phit), phie_gas)
        phie_gas = np.clip(phie_gas, 0, 0.45)

        # Convert back to Series
        phie_gas = pd.Series(phie_gas, index=self.data.index)

        self.results["PHIE_GAS"] = phie_gas

        return phie_gas

    # =========================================================================
    # WATER SATURATION CALCULATIONS
    # =========================================================================

    def _column(self, value, name: str = "value") -> np.ndarray:
        """A scalar or one-value-per-row input as a float array of ``len(data)`` rows."""
        values = np.asarray(value, dtype=float)
        if values.ndim == 0:
            return np.full(len(self.data), float(values))
        if values.shape != (len(self.data),):
            raise ValueError(f"{name} must have one value per data row")
        return values

    @staticmethod
    def _sw_valid_mask(rt, porosity):
        """The one validity rule of every Sw model.

        Returns ``(solve, no_porosity)`` boolean arrays:

        - RT or the model's porosity NaN: neither (Sw is NaN);
        - the model's porosity at or below ``SW_MIN_POROSITY`` with a valid RT:
          ``no_porosity`` (Sw is 1.0, there is no pore space to hold hydrocarbon);
        - otherwise ``solve``.

        The model's porosity is PHIE for Archie, Indonesian and Simandoux and
        PHIT for Waxman-Smits and Dual-Water.
        """
        rt_a = np.asarray(rt, dtype=float)
        phi_a = np.asarray(porosity, dtype=float)
        known = ~(np.isnan(rt_a) | np.isnan(phi_a))
        no_porosity = known & (phi_a <= SW_MIN_POROSITY)
        return known & ~no_porosity, no_porosity

    def _finish_sw(self, key, raw, solve, no_porosity, upper=None, lower=None, extra=None):
        """Clip ``raw`` Sw to [0, 1], apply the validity rule, and record the bound counts.

        ``upper``/``lower`` default to the samples whose unclipped Sw is above
        ``SW_UPPER_TOLERANCE`` / at or below 0; solver models pass their own masks
        (bracket fallbacks).
        ``extra`` adds more per-sample flag columns to ``self.sw_flags[key]``.
        """
        raw = np.asarray(raw, dtype=float)
        with np.errstate(invalid="ignore"):
            if upper is None:
                upper = solve & (raw > SW_UPPER_TOLERANCE)
            if lower is None:
                lower = solve & (raw <= 0.0)
        sw = np.where(solve, np.clip(raw, 0.0, 1.0), np.nan)
        sw = np.where(no_porosity, 1.0, sw)
        flags = {"at_upper_bound": upper, "at_lower_bound": lower, "no_porosity": no_porosity}
        flags.update(extra or {})
        self.sw_flags[key] = pd.DataFrame(flags, index=self.data.index)
        return pd.Series(sw, index=self.data.index)

    def calculate_sw_archie(
        self,
        rt_curve: str = "RT",
        phie: pd.Series = None,
        rw: float = 0.05,
        a: float = 0.62,
        m: float = 2.15,
        n: float = 2.0,
    ) -> pd.Series:
        """
        Calculate water saturation using Archie equation.

        Sw = ((a * Rw) / (Rt * PHIE^m))^(1/n)

        Args:
            rt_curve: Resistivity curve mnemonic
            phie: Effective porosity series
            rw: Formation water resistivity (ohm.m)
            a: Tortuosity factor (Humble: 0.62)
            m: Cementation exponent (Humble: 2.15)
            n: Saturation exponent (2.0)

        Returns:
            Water saturation series (0-1); NaN without RT or porosity, 1.0
            where the porosity is at or below 0.001
        """
        if rt_curve not in self.data.columns:
            return self._make_series(np.nan)

        rt = self.data[rt_curve]
        self._validate_positive_parameter("rw", rw)
        rw = self._rw_values(rw)
        self._validate_positive_parameter("a", a)
        self._validate_positive_parameter("m", m)
        self._validate_positive_parameter("n", n)
        self._validate_positive_parameter("rt", rt, allow_nan=True)

        if phie is None:
            phie = self.results.get("PHIE", self._make_series(0.15))

        rt_a = self._column(rt, "rt")
        phie_a = self._column(phie, "phie")
        solve, no_porosity = self._sw_valid_mask(rt_a, phie_a)

        # Avoid division by zero
        phie_safe = np.maximum(phie_a, SW_MIN_POROSITY)
        rt_safe = np.maximum(rt_a, 0.001)

        # Archie equation
        with np.errstate(all="ignore"):
            raw = np.power((a * rw) / (rt_safe * np.power(phie_safe, m)), 1 / n)

        sw = self._finish_sw("SW_ARCHIE", raw, solve, no_porosity)
        self.results["SW_ARCHIE"] = sw
        return sw

    def calculate_sw_indonesian(
        self,
        rt_curve: str = "RT",
        phie: pd.Series = None,
        vsh: pd.Series = None,
        rw: float = 0.05,
        rsh: float = 5.0,
        a: float = 0.62,
        m: float = 2.15,
        n: float = 2.0,
    ) -> pd.Series:
        """
        Calculate water saturation using Indonesian equation.

        Suitable for shaly sands.

        1/sqrt(Rt) = sqrt(PHIE^m/(a*Rw)) * Sw^(n/2) + Vsh^(1-Vsh/2)/sqrt(Rsh) * Sw^(n/2)

        Args:
            rt_curve: Resistivity curve mnemonic
            phie: Effective porosity series
            vsh: Vshale series
            rw: Formation water resistivity (ohm.m), scalar or one value per row
            rsh: Shale resistivity (ohm.m), scalar or one value per row
            a, m, n: Archie parameters

        Returns:
            Water saturation series (0-1); NaN without RT or porosity, 1.0
            where the porosity is at or below 0.001
        """
        if rt_curve not in self.data.columns:
            return self._make_series(np.nan)

        rt = self.data[rt_curve]
        self._validate_positive_parameter("rw", rw)
        rw = self._rw_values(rw)
        self._validate_positive_parameter("rsh", rsh)
        rsh = self._rsh_values(rsh)
        self._validate_positive_parameter("a", a)
        self._validate_positive_parameter("m", m)
        self._validate_positive_parameter("n", n)
        self._validate_positive_parameter("rt", rt, allow_nan=True)

        if phie is None:
            phie = self.results.get("PHIE", self._make_series(0.15))
        if vsh is None:
            vsh = self.results.get("VSH", self._make_series(0.2))

        # The Indonesian (Poupon-Leveaux) equation factorizes as
        #   1/sqrt(Rt) = (term1 + term2) * Sw^(n/2)
        # so it has an exact closed form:  Sw = (lhs / (term1 + term2))^(2/n).
        # This replaces a per-row brentq solve whose fixed [0.001, 1.5] bracket
        # could fail (same-sign endpoints for very low Rt) and then silently fall
        # back to plain Archie -- dropping the Vsh term exactly where it matters.
        phie_v = self._column(phie, "phie")
        vsh_v = self._column(vsh, "vsh")
        rt_v = self._column(rt, "rt")
        solve, no_porosity = self._sw_valid_mask(rt_v, phie_v)

        # Clip Vsh to [0, 1] so the fractional power stays well-defined.
        vsh_clip = np.clip(vsh_v, 0.0, 1.0)

        with np.errstate(invalid="ignore", divide="ignore"):
            term1 = np.sqrt(np.power(phie_v, m) / (a * rw))
            term2 = np.power(vsh_clip, (1 - vsh_clip / 2)) / np.sqrt(rsh)
            lhs = 1.0 / np.sqrt(rt_v)
            raw = np.power(lhs / (term1 + term2), 2.0 / n)

        sw = self._finish_sw("SW_INDO", raw, solve, no_porosity)
        self.results["SW_INDO"] = sw
        return sw

    def calculate_sw_simandoux(
        self,
        rt_curve: str = "RT",
        phie: pd.Series = None,
        vsh: pd.Series = None,
        rw: float = 0.05,
        rsh: float = 5.0,
        a: float = 0.62,
        m: float = 2.15,
        n: float = 2.0,
    ) -> pd.Series:
        """
        Calculate water saturation using Simandoux equation.

        1/Rt = (PHIE^m * Sw^n)/(a*Rw) + (Vsh * Sw)/Rsh

        Solved as quadratic: A*Sw^2 + B*Sw - C = 0

        Args:
            rt_curve: Resistivity curve mnemonic
            phie: Effective porosity series
            vsh: Vshale series (clipped to 0-1)
            rw: Formation water resistivity (ohm.m), scalar or one value per row
            rsh: Shale resistivity (ohm.m), scalar or one value per row
            a, m, n: Archie parameters

        Returns:
            Water saturation series (0-1); NaN without RT or porosity, 1.0
            where the porosity is at or below 0.001
        """
        if rt_curve not in self.data.columns:
            return self._make_series(np.nan)

        rt = self.data[rt_curve]
        self._validate_positive_parameter("rw", rw)
        rw = self._rw_values(rw)
        self._validate_positive_parameter("rsh", rsh)
        rsh = self._rsh_values(rsh)
        self._validate_positive_parameter("a", a)
        self._validate_positive_parameter("m", m)
        self._validate_positive_parameter("n", n)
        self._validate_positive_parameter("rt", rt, allow_nan=True)

        if phie is None:
            phie = self.results.get("PHIE", self._make_series(0.15))
        if vsh is None:
            vsh = self.results.get("VSH", self._make_series(0.2))

        phie_a = self._column(phie, "phie")
        vsh_a = self._column(vsh, "vsh")
        rt_a = self._column(rt, "rt")
        solve, no_porosity = self._sw_valid_mask(rt_a, phie_a)

        # Simandoux:  1/Rt = A*Sw^n + B*Sw   with
        #   A = PHIE^m / (a*Rw)   (coefficient on Sw^n)
        #   B = Vsh / Rsh         (coefficient on Sw), Vsh clipped to [0, 1]
        #   C = 1 / Rt            (constant)
        phie_safe = np.maximum(phie_a, SW_MIN_POROSITY)
        rt_safe = np.maximum(rt_a, 0.001)

        A = np.power(phie_safe, m) / (a * rw)
        B = np.clip(vsh_a, 0.0, 1.0) / rsh
        C = 1 / rt_safe

        if abs(n - 2.0) < 1e-9:
            # n == 2: closed-form quadratic  A*Sw^2 + B*Sw - C = 0
            discriminant = B**2 + 4 * A * C
            discriminant = np.maximum(discriminant, 0)  # Ensure non-negative
            raw = (-B + np.sqrt(discriminant)) / (2 * A)
        else:
            # General n: f(Sw) = A*Sw^n + B*Sw - C is strictly increasing for
            # Sw > 0 (A > 0, B >= 0), so it has a unique root. Solve per row.
            # Previously the n argument was ignored and n=2 was always used.
            A_arr = np.broadcast_to(np.asarray(A, dtype=float), rt_safe.shape)
            B_arr = np.broadcast_to(np.asarray(B, dtype=float), rt_safe.shape)
            C_arr = np.asarray(C, dtype=float)

            sw_list = []
            for i in range(len(rt_safe)):
                A_i, B_i, C_i = A_arr[i], B_arr[i], C_arr[i]
                if np.isnan(A_i) or np.isnan(B_i) or np.isnan(C_i):
                    sw_list.append(np.nan)
                    continue

                def simandoux_func(sw_val):
                    return A_i * np.power(sw_val, n) + B_i * sw_val - C_i

                # f(0) = -C_i <= 0. If f(1) <= 0 the root is >= 1 (fully wet).
                if simandoux_func(1.0) <= 0:
                    sw_list.append(1.0)
                    continue
                try:
                    sw_list.append(brentq(simandoux_func, 0.0, 1.0))
                except Exception:
                    sw_list.append(np.nan)

            raw = np.array(sw_list, dtype=float)

        sw = self._finish_sw("SW_SIMAN", raw, solve, no_porosity)
        self.results["SW_SIMAN"] = sw
        return sw

    def _finish_total_sw(self, key, swt_key, swt_arr, solve_flags, phit_a, phie, rt_a, no_phi):
        """Store ``Swt`` in ``SWT_*`` and return the effective Sw of a total-porosity model.

        ``solve_flags`` are the solver's per-sample flags. ``phie`` is the
        effective porosity (``None``: the total porosity, so Swe = Swt). The
        effective Sw conserves the hydrocarbon volume (:func:`effective_sw`).
        """
        index = self.data.index
        phie_a = phit_a if phie is None else self._column(phie, "phie")
        swe, eff = _effective_sw_detail(swt_arr, phit_a, phie_a)
        # A PHIT below the floor is already counted as no_porosity by the solver.
        eff["no_porosity"] = eff["no_porosity"] & ~no_phi
        eff["bvh_exceeds_phie"] = eff["bvh_exceeds_phie"] & ~no_phi
        eff["phie_above_phit"] = eff["phie_above_phit"] & ~no_phi
        flags = dict(solve_flags)
        flags["no_porosity"] = no_phi | eff["no_porosity"]
        flags["bvh_exceeds_phie"] = eff["bvh_exceeds_phie"]
        flags["phie_above_phit"] = eff["phie_above_phit"]
        # PHIE is there but the total porosity is not: no basis for the total model.
        flags["no_phit"] = ~np.isnan(rt_a) & np.isnan(phit_a) & np.isfinite(phie_a)
        self.sw_flags[key] = pd.DataFrame(flags, index=index)
        self.results[swt_key] = pd.Series(swt_arr, index=index)
        sw = pd.Series(np.where(no_phi, 1.0, swe), index=index)
        self.results[key] = sw
        return sw

    def calculate_sw_waxman_smits(
        self,
        rt_curve: str = "RT",
        phit: pd.Series = None,
        rw: float = 0.05,
        a: float = 0.62,
        m: float = 2.15,
        n: float = 2.0,
        qv: float = 0.2,
        B: float = 1.0,
        phie: pd.Series = None,
    ) -> pd.Series:
        """
        Calculate water saturation using Waxman-Smits equation.

        Ct = (1/F*) * (Swt^n*) * (Cw + (B*Qv) / Swt)

        Where:
        - Ct = 1/Rt (Total conductivity)
        - F* = a / PHIT^m (total porosity)
        - Cw = 1/Rw
        - Qv = cation exchange capacity per unit pore volume
        - B = equivalent conductance of clay exchange cations

        The solver returns the total water saturation Swt, stored in ``SWT_WS``.
        ``SW_WS`` (and the return value) is the effective saturation from
        hydrocarbon-volume conservation, ``effective_sw(Swt, PHIT, PHIE)``; without
        ``phie`` (and without ``PHIE`` in the results) PHIE = PHIT and Swe = Swt.

        Args:
            rt_curve: Resistivity curve mnemonic
            phit: Total porosity series
            rw: Formation water resistivity (ohm.m)
            a, m, n: Archie parameters
            qv: Qv parameter (meq/ml)
            B: B parameter (mho cm^2/meq)
            phie: Effective porosity series for the effective Sw

        Returns:
            Effective water saturation series (0-1)
        """
        if rt_curve not in self.data.columns:
            return self._make_series(np.nan)

        rt = self.data[rt_curve]
        self._validate_positive_parameter("rw", rw)
        rw = self._rw_values(rw)
        self._validate_positive_parameter("a", a)
        self._validate_positive_parameter("m", m)
        self._validate_positive_parameter("n", n)
        self._validate_positive_parameter("rt", rt, allow_nan=True)
        self._validate_nonnegative_parameter("qv", qv)  # Qv 0 is a clean sand: Waxman-Smits = Archie
        self._validate_positive_parameter("B", B, allow_nan=False)
        if np.ndim(B):
            B = self._per_sample(B, "B")      # e.g. B from temperature, one value per row

        if phit is None:
            phit = self.results.get("PHIT", self.results.get("PHIE", self._make_series(0.15)))
        if phie is None:
            phie = self.results.get("PHIE")

        # Pre-calculate constants where possible
        cw = 1.0 / rw  # validated > 0; an array for per-sample Rw

        rt_arr = self._column(rt, "rt")
        phit_arr = self._column(phit, "phit")
        solve, no_phi = self._sw_valid_mask(rt_arr, phit_arr)
        size = len(rt_arr)
        swt_arr = np.full(size, np.nan)
        no_root = np.zeros(size, dtype=bool)
        failed_all = np.zeros(size, dtype=bool)
        upper = np.zeros(size, dtype=bool)
        lower = np.zeros(size, dtype=bool)

        if solve.any():
            with np.errstate(all="ignore"):
                f_star = a / np.power(phit_arr[solve], m)
                ct = 1.0 / rt_arr[solve]
                cw_v = cw[solve] if np.ndim(cw) else cw
                b_v = B[solve] if np.ndim(B) else B

                # Function to solve: f(Sw) = Model_Ct - Actual_Ct = 0
                # Model_Ct = (1/F*) * (Cw * Sw^n + B*Qv * Sw^(n-1))
                def ws_func(sw):
                    # Guard against small Sw
                    sw = np.maximum(sw, 1e-6)
                    term1 = cw_v * np.power(sw, n)
                    term2 = (b_v * qv) * np.power(sw, n - 1)
                    return (1.0 / f_star) * (term1 + term2) - ct

                f_lo = ws_func(np.full(f_star.shape, 0.001))
                f_hi = ws_func(np.full(f_star.shape, 1.0))
                bracketed = f_lo * f_hi < 0
                root, failed = _vectorized_brentq(ws_func, 0.001, 1.0, bracketed)
                # No root in range: the bound the conductivity points to (Sw > 1 or
                # below the lower bracket); counted as at_upper_bound / at_lower_bound.
                fallback_up = f_hi < 0
                fallback = np.where(fallback_up, 1.0, 0.0)
                solved = np.where(bracketed, np.clip(root, 0, 1), fallback)
            swt_arr[solve] = solved
            no_root[solve] = ~bracketed
            failed_all[solve] = failed
            beyond = ws_func(np.full(f_star.shape, SW_UPPER_TOLERANCE)) < 0
            upper[solve] = ~bracketed & fallback_up & beyond
            lower[solve] = ~bracketed & ~fallback_up
        swt_arr[no_phi] = 1.0

        self.solver_diagnostics["SW_WS"] = {
            "no_root": int(no_root.sum()),
            "failed": int(failed_all.sum()),
        }
        return self._finish_total_sw(
            "SW_WS", "SWT_WS", swt_arr,
            {"at_upper_bound": upper, "at_lower_bound": lower,
             "no_root": no_root, "failed": failed_all},
            phit_arr, phie, rt_arr, no_phi,
        )

    def calculate_sw_dual_water(
        self,
        rt_curve: str = "RT",
        phit: pd.Series = None,
        rw: float = 0.05,
        a: float = 0.62,
        m: float = 2.15,
        n: float = 2.0,
        swb: float = 0.1,
        rwb: float = 0.2,
        phie: pd.Series = None,
    ) -> pd.Series:
        """
        Calculate water saturation using Dual-Water model.

        Ct = (1/Ft) * [ (Swt - Swb) * Cw + Swb * Cwb ] / Swt * Swt^n
           = (1/Ft) * Swt^n * [ (Cwf * (Swt - Swb) / Swt) + (Cwb * Swb / Swt) ]
           Simplify:
           Ct = (Swt^n / Ft) * [ Cw + (Cwb - Cw) * (Swb / Swt) ]

        Where:
        - Swt = Total water saturation (what we solve for), stored in ``SWT_DW``
        - Swb = Bound water saturation (input)
        - Ft = a / PHIT^m (total porosity)

        ``SW_DW`` (and the return value) is the effective saturation from
        hydrocarbon-volume conservation, ``effective_sw(Swt, PHIT, PHIE)``; without
        ``phie`` (and without ``PHIE`` in the results) PHIE = PHIT and Swe = Swt.

        Args:
            rt_curve: Resistivity curve mnemonic
            phit: Total porosity series
            rw: Free water resistivity
            a, m, n: Archie parameters
            swb: Bound water saturation fraction
            rwb: Bound water resistivity
            phie: Effective porosity series for the effective Sw

        Returns:
            Effective water saturation series (0-1)
        """
        if rt_curve not in self.data.columns:
            return self._make_series(np.nan)

        rt = self.data[rt_curve]
        self._validate_positive_parameter("rw", rw)
        rw = self._rw_values(rw)
        self._validate_positive_parameter("rwb", rwb)
        rwb = self._per_sample(rwb, "rwb")      # array: Rwb corrected to formation temperature
        self._validate_positive_parameter("a", a)
        self._validate_positive_parameter("m", m)
        self._validate_positive_parameter("n", n)
        self._validate_positive_parameter("rt", rt, allow_nan=True)
        if not np.isfinite(swb) or not 0 <= swb < 1:
            raise ValueError("swb must be finite and in the range [0, 1)")

        if phit is None:
            phit = self.results.get("PHIT", self.results.get("PHIE", self._make_series(0.15)))
        if phie is None:
            phie = self.results.get("PHIE")

        cw = 1.0 / rw  # validated > 0; an array for per-sample Rw
        cwb = 1.0 / rwb  # validated > 0; an array for per-sample Rwb

        rt_arr = self._column(rt, "rt")
        phi_arr = self._column(phit, "phit")
        solve, no_phi = self._sw_valid_mask(rt_arr, phi_arr)
        size = len(rt_arr)
        swt_arr = np.full(size, np.nan)
        no_root = np.zeros(size, dtype=bool)
        failed_all = np.zeros(size, dtype=bool)
        upper = np.zeros(size, dtype=bool)
        lower = np.zeros(size, dtype=bool)

        if solve.any():
            with np.errstate(all="ignore"):
                # Formation factor based on total porosity
                f_t = a / np.power(phi_arr[solve], m)
                ct_measured = 1.0 / rt_arr[solve]
                cw_v = cw[solve] if np.ndim(cw) else cw
                cwb_v = cwb[solve] if np.ndim(cwb) else cwb

                # f(Swt) = Model_Ct - Measured_Ct
                def dw_func(swt):
                    # Swt must be >= Swb ideally; allow [Swb, 1] for stability.
                    swt = np.maximum(swt, swb + 1e-4)  # Ensure slightly above Swb
                    # Ct = (Swt^n / Ft) * (Cw + (Cwb - Cw) * Swb / Swt)
                    term = cw_v + (cwb_v - cw_v) * (swb / swt)
                    return (np.power(swt, n) / f_t) * term - ct_measured

                # Root search in [Swb, 1.0]
                lower_bound = min(max(swb + 0.001, 0.001), 0.99)

                val_low = dw_func(np.full(f_t.shape, lower_bound))
                val_high = dw_func(np.full(f_t.shape, 1.0))
                bracketed = val_low * val_high < 0
                root, failed = _vectorized_brentq(dw_func, lower_bound, 1.0, bracketed)
                # No root: if measured cond is very high, Sw -> 1; if very low, Sw -> Swb
                fallback_up = np.abs(val_high) < np.abs(val_low)
                fallback = np.where(fallback_up, 1.0, swb)
                solved = np.clip(np.where(bracketed, root, fallback), 0, 1)
            swt_arr[solve] = solved
            no_root[solve] = ~bracketed
            failed_all[solve] = failed
            beyond = dw_func(np.full(f_t.shape, SW_UPPER_TOLERANCE)) < 0
            upper[solve] = ~bracketed & fallback_up & beyond
            lower[solve] = ~bracketed & ~fallback_up
        swt_arr[no_phi] = 1.0

        self.solver_diagnostics["SW_DW"] = {
            "no_root": int(no_root.sum()),
            "failed": int(failed_all.sum()),
        }
        return self._finish_total_sw(
            "SW_DW", "SWT_DW", swt_arr,
            {"at_upper_bound": upper, "at_lower_bound": lower,
             "no_root": no_root, "failed": failed_all},
            phi_arr, phie, rt_arr, no_phi,
        )

    # =========================================================================
    # IRREDUCIBLE WATER SATURATION (Swirr) CALCULATIONS
    # =========================================================================

    def calculate_swirr_buckles(
        self, phie: pd.Series = None, k_buckles: float = 0.02
    ) -> pd.Series:
        """
        Calculate Swirr using Buckles number approach.

        Swirr = K_buckles / PHIE

        Args:
            phie: Effective porosity series
            k_buckles: Buckles number (0.01-0.04 for sandstone, higher for carbonate)

        Returns:
            Swirr series
        """
        if phie is None:
            phie = self.results.get("PHIE", self._make_series(0.15))

        swirr = swirr_buckles(phie, k_buckles)

        self.results["SWIRR_BUCKLES"] = swirr
        return swirr

    def calculate_swirr_clean_zone(
        self,
        sw: pd.Series = None,
        vsh: pd.Series = None,
        vsh_threshold: float = 0.2,
        sw_threshold: float = 0.5,
    ) -> pd.Series:
        """
        Calculate Swirr from clean zone approach.

        Identifies clean zones (low Vsh, low Sw) and uses minimum Sw as Swirr.

        Args:
            sw: Water saturation series
            vsh: Vshale series
            vsh_threshold: Maximum Vsh for clean zone
            sw_threshold: Maximum Sw for hydrocarbon zone

        Returns:
            Swirr series (constant value based on clean zone minimum)
        """
        if sw is None:
            sw = self.results.get(
                "SW_INDO",
                self.results.get("SW_ARCHIE", self._make_series(0.5)),
            )
        if vsh is None:
            vsh = self.results.get("VSH", self._make_series(0.3))

        # Identify clean hydrocarbon zones
        clean_hc_zone = (vsh < vsh_threshold) & (sw < sw_threshold)
        sw_valid = sw.dropna()

        if clean_hc_zone.sum() > 0:
            # Minimum Sw in clean HC zones = Swirr
            swirr_value = float(sw[clean_hc_zone].min())
        elif len(sw_valid) > 0:
            # Fallback: use P5 of all Sw as estimate
            swirr_value = float(np.percentile(sw_valid, 5))
        else:
            # No saturation observations: use the documented neutral default
            # rather than asking NumPy for a percentile of an empty array.
            swirr_value = 0.2

        # Bound to reasonable range
        swirr_value = np.clip(swirr_value, 0.05, 0.5)

        swirr = pd.Series([swirr_value] * len(self.data), index=self.data.index)

        self.results["SWIRR_CLEANZONE"] = swirr
        return swirr

    def calculate_swirr_statistical(
        self, sw: pd.Series = None, vsh: pd.Series = None, percentile: float = 5
    ) -> pd.Series:
        """
        Calculate Swirr using statistical approach.

        Uses percentile of Sw in clean zones as Swirr estimate.

        Args:
            sw: Water saturation series
            vsh: Vshale series
            percentile: Percentile to use (default P5)

        Returns:
            Swirr series
        """
        if sw is None:
            sw = self.results.get(
                "SW_INDO",
                self.results.get("SW_ARCHIE", self._make_series(0.5)),
            )
        if vsh is None:
            vsh = self.results.get("VSH", self._make_series(0.3))

        # Use Sw in relatively clean zones
        clean_mask = vsh < 0.4

        if clean_mask.sum() > 0:
            sw_clean = sw[clean_mask].dropna()
            if len(sw_clean) > 0:
                swirr_value = float(np.percentile(sw_clean, percentile))
            else:
                swirr_value = 0.2
        else:
            sw_valid = sw.dropna()
            swirr_value = (
                float(np.percentile(sw_valid, percentile))
                if len(sw_valid) > 0
                else 0.2
            )

        # Bound to reasonable range
        swirr_value = np.clip(swirr_value, 0.05, 0.5)

        swirr = pd.Series([swirr_value] * len(self.data), index=self.data.index)

        self.results["SWIRR_STAT"] = swirr
        return swirr

    def calculate_swirr_hierarchical(
        self,
        phie: pd.Series = None,
        sw: pd.Series = None,
        vsh: pd.Series = None,
        k_buckles: float = 0.02,
        vsh_clean_threshold: float = 0.10,
        sw_hc_threshold: float = 0.50,
    ) -> Tuple[pd.Series, Dict]:
        """
        Calculate Swirr using hierarchical workflow (recommended without core data).

        Workflow:
        1. Find Clean Hydrocarbon Zone: If clean zone (Vsh < 10%) with low Sw exists,
           use P10 of Sw in that zone as Swirr
        2. Buckles Fallback: If no clean HC zone, use Buckles number to estimate
           Swirr = k_buckles / PHIE
        3. Statistical Bound: Limit Swirr to 0.05-0.50 and never exceed Sw_observed

        Args:
            phie: Effective porosity series
            sw: Water saturation series
            vsh: Vshale series
            k_buckles: Buckles number (default 0.02 for sandstone)
            vsh_clean_threshold: Vsh threshold for identifying clean zone (default 0.10)
            sw_hc_threshold: Sw threshold for identifying hydrocarbon zone (default 0.50)

        Returns:
            Tuple of (Swirr series, info dictionary with method used)
        """
        if phie is None:
            phie = self.results.get("PHIE", self._make_series(0.15))
        if sw is None:
            sw = self.results.get(
                "SW_INDO",
                self.results.get("SW_ARCHIE", self._make_series(0.5)),
            )
        if vsh is None:
            vsh = self.results.get("VSH", self._make_series(0.3))

        info = {
            "method": "buckles_fallback",
            "clean_hc_zones_found": 0,
            "swirr_value": None,
            "warning": None,
        }

        # Step 1: Try to find Clean Hydrocarbon Zone (Vsh < 10%, Sw < 50%)
        clean_hc_zone = (
            (vsh < vsh_clean_threshold) & (sw < sw_hc_threshold) & (phie > 0.05)
        )
        clean_hc_count = clean_hc_zone.sum()
        info["clean_hc_zones_found"] = int(clean_hc_count)

        if clean_hc_count > 10:  # Need sufficient data points
            # Use P10 of Sw in clean HC zone as Swirr
            sw_clean_hc = sw[clean_hc_zone].dropna()
            swirr_from_clean = float(np.percentile(sw_clean_hc, 10))

            # Create Swirr profile (constant for simplicity)
            swirr = pd.Series(
                [swirr_from_clean] * len(self.data), index=self.data.index
            )
            info["method"] = "clean_hc_zone"
            info["swirr_value"] = swirr_from_clean

        else:
            # Step 2: Buckles Fallback - calculate profile from PHIE
            phie_safe = np.maximum(phie, 0.01)
            swirr = k_buckles / phie_safe
            info["method"] = "buckles_fallback"
            info["swirr_value"] = float(swirr.mean())

        # Step 3: Statistical Bounds, in this order so the floor always holds:
        # never above the observed Sw (illogical), then within [0.05, 0.60].
        # A Swirr floor of 0.05 may exceed a measured Sw below 0.05 (counted).
        estimate = np.asarray(swirr, dtype=float)
        sw_a = np.asarray(sw, dtype=float)
        with np.errstate(invalid="ignore"):
            limited = np.minimum(estimate, sw_a)
            by_sw = estimate > sw_a
            raised = limited < 0.05
            capped = limited > 0.60
        swirr = pd.Series(np.clip(limited, 0.05, 0.60), index=self.data.index)

        info["samples"] = int(np.isfinite(limited).sum())
        info["raised_to_floor"] = int(raised.sum())
        info["limited_by_sw"] = int(by_sw.sum())
        info["limited_to_max"] = int(capped.sum())
        notes = []
        if info["raised_to_floor"]:
            notes.append(f"{info['raised_to_floor']} samples raised to the 0.05 floor")
        if info["limited_by_sw"]:
            notes.append(f"{info['limited_by_sw']} samples limited to the measured Sw")
        if info["limited_to_max"]:
            notes.append(f"{info['limited_to_max']} samples limited to 0.60")
        if notes:
            info["warning"] = "Hierarchical Swirr: " + "; ".join(notes) + "."
        self.swirr_flags = pd.DataFrame(
            {"raised_to_floor": raised, "limited_by_sw": by_sw, "limited_to_max": capped},
            index=self.data.index,
        )
        self.swirr_info = info

        self.results["SWIRR"] = swirr
        self.results["SWIRR_METHOD"] = info["method"]

        return swirr, info

    def calculate_all_swirr(
        self,
        phie: pd.Series = None,
        sw: pd.Series = None,
        vsh: pd.Series = None,
        k_buckles: float = 0.02,
        vsh_threshold: float = 0.2,
        methods: list = None,
    ) -> Dict[str, pd.Series]:
        """
        Calculate Swirr using multiple methods for comparison.

        Args:
            phie: Effective porosity series
            sw: Water saturation series
            vsh: Vshale series
            k_buckles: Buckles number for Buckles method
            vsh_threshold: Vsh threshold for clean zone method
            methods: List of methods. Options: 'hierarchical', 'buckles', 'clean_zone', 'statistical'

        Returns:
            Dictionary with Swirr for each method
        """
        if methods is None:
            methods = ["hierarchical"]  # Default to hierarchical

        results = {}

        if "hierarchical" in methods:
            swirr, info = self.calculate_swirr_hierarchical(phie, sw, vsh, k_buckles)
            results["SWIRR"] = swirr
            results["info"] = info

        if "buckles" in methods:
            results["SWIRR_BUCKLES"] = self.calculate_swirr_buckles(phie, k_buckles)

        if "clean_zone" in methods:
            results["SWIRR_CLEANZONE"] = self.calculate_swirr_clean_zone(
                sw, vsh, vsh_threshold
            )

        if "statistical" in methods:
            results["SWIRR_STAT"] = self.calculate_swirr_statistical(sw, vsh)

        # SWIRR is the series of the selected method: hierarchical when asked for,
        # else the single method requested. Several methods ("All Methods") keep
        # Buckles as the one used.
        if "hierarchical" not in methods:
            chosen = None
            if len(methods) == 1 or "buckles" not in methods:
                chosen = next((m for m in methods if m in self._SWIRR_SERIES), None)
            else:
                chosen = "buckles"
            if chosen is not None:
                self._set_swirr_from(chosen, results, phie, k_buckles)

        return results

    # Swirr method key -> (results column, SWIRR_METHOD label)
    _SWIRR_SERIES = {
        "buckles": ("SWIRR_BUCKLES", "buckles"),
        "clean_zone": ("SWIRR_CLEANZONE", "clean_zone"),
        "statistical": ("SWIRR_STAT", "statistical"),
    }

    def _set_swirr_from(self, method, results, phie, k_buckles):
        """``SWIRR``/``SWIRR_METHOD`` from the selected method (spec C15).

        A sample where the selected series has no value falls back to Buckles;
        those samples are flagged in ``swirr_flags["buckles_fallback"]`` and
        labelled ``buckles`` in ``SWIRR_METHOD``.
        """
        column, label = self._SWIRR_SERIES[method]
        series = pd.Series(results[column], index=self.data.index, dtype=float)
        methods_label = pd.Series(label, index=self.data.index, dtype=object)
        fallback = pd.Series(False, index=self.data.index)
        if method != "buckles":
            missing = series.isna()
            if missing.any():
                buckles = results.get("SWIRR_BUCKLES")
                if buckles is None:
                    had_column = "SWIRR_BUCKLES" in self.results.columns
                    buckles = self.calculate_swirr_buckles(phie, k_buckles)
                    if not had_column:
                        self.results.drop(columns="SWIRR_BUCKLES", inplace=True)
                buckles = pd.Series(buckles, index=self.data.index, dtype=float)
                fallback = missing & buckles.notna()
                series = series.where(~missing, buckles)
                methods_label = methods_label.where(~fallback, "buckles")
        self.results["SWIRR"] = series
        self.results["SWIRR_METHOD"] = methods_label
        self.swirr_flags = pd.DataFrame({"buckles_fallback": fallback})
        self.swirr_info = {"method": label, "buckles_fallback": int(fallback.sum())}

    # =========================================================================
    # PERMEABILITY CALCULATIONS
    # =========================================================================

    def calculate_permeability_timur(
        self, phie: pd.Series = None, swi: pd.Series = None
    ) -> pd.Series:
        """
        Calculate permeability using Timur equation.

        K = 8581 * (PHIE^4.4) / (Swi^2)

        Args:
            phie: Effective porosity series
            swi: Irreducible water saturation series

        Returns:
            Permeability series (mD)
        """
        if phie is None:
            phie = self.results.get("PHIE", self._make_series(0.15))

        # Estimate Swi if not provided
        if swi is None:
            # Use the primary Sw (whatever method the user selected) as a proxy,
            # falling back to Archie only if no primary Sw is present. Previously
            # this looked up SW_ARCHIE specifically, so with Simandoux/Indonesian/
            # etc. it silently fell through to a flat 0.2 constant.
            sw = self.results.get("SW", self.results.get("SW_ARCHIE", None))
            if sw is not None:
                # In clean zones with hydrocarbons, Sw ~ Swi
                swi = np.clip(sw.copy(), 0.05, 0.9)
            else:
                swi = self._make_series(0.2)

        phie_safe = np.maximum(phie, 0.001)
        swi_safe = np.maximum(swi, 0.05)

        # Timur equation
        k = 8581 * np.power(phie_safe, 4.4) / np.power(swi_safe, 2)

        # Bound to reasonable range
        k = np.clip(k, 0.001, 50000)

        self.results["PERM_TIMUR"] = k
        return k

    def calculate_permeability_wyllie_rose(
        self,
        phie: pd.Series = None,
        swi: pd.Series = None,
        C: float = 100,
        P: float = 4.5,
        Q: float = 2.0,
    ) -> pd.Series:
        """
        Calculate permeability using Wyllie-Rose equation.

        K = C * (PHIE^P) / (Swi^Q)

        Args:
            phie: Effective porosity series
            swi: Irreducible water saturation series
            C, P, Q: Wyllie-Rose coefficients

        Returns:
            Permeability series (mD)
        """
        if phie is None:
            phie = self.results.get("PHIE", self._make_series(0.15))

        if swi is None:
            # Prefer the primary Sw; fall back to Archie, then a flat default.
            sw = self.results.get("SW", self.results.get("SW_ARCHIE", None))
            if sw is not None:
                swi = np.clip(sw, 0.05, 0.9)
            else:
                swi = self._make_series(0.2)

        phie_safe = np.maximum(phie, 0.001)
        swi_safe = np.maximum(swi, 0.05)

        # Wyllie-Rose equation
        k = C * np.power(phie_safe, P) / np.power(swi_safe, Q)

        # Bound to reasonable range
        k = np.clip(k, 0.001, 50000)

        self.results["PERM_WR"] = k
        return k

    def classify_flow_units(self, perm: pd.Series = None) -> pd.Series:
        """
        Classify permeability into Flow Unit Classes.

        Classification:
        - Tight: < 1 mD
        - Poor: 1-10 mD
        - Fair: 10-100 mD
        - Good: 100-1000 mD
        - Excellent: > 1000 mD

        Args:
            perm: Permeability series (mD)

        Returns:
            Series with flow unit classification
        """
        if perm is None:
            perm = self.results.get(
                "PERM_TIMUR",
                self.results.get("PERM_WR", self._make_series(10)),
            )

        k = np.asarray(perm, dtype=float)
        labels = np.select(
            [np.isnan(k), k < 1, k < 10, k < 100, k < 1000],
            ["Unknown", "Tight", "Poor", "Fair", "Good"],
            default="Excellent",
        )
        flow_unit = pd.Series(labels, index=perm.index, dtype=object)
        self.results["FLOW_UNIT"] = flow_unit
        return flow_unit

    def get_permeability_quality_flags(
        self, perm: pd.Series = None, swirr: pd.Series = None, phie: pd.Series = None
    ) -> Dict:
        """
        Generate quality flags/warnings for permeability calculation.

        Args:
            perm: Permeability series
            swirr: Swirr series used in calculation
            phie: PHIE series used in calculation

        Returns:
            Dictionary with flags and statistics
        """
        if perm is None:
            perm = self.results.get("PERM_TIMUR", pd.Series())
        if swirr is None:
            swirr = self.results.get("SWIRR", pd.Series())
        if phie is None:
            phie = self.results.get("PHIE", pd.Series())

        flags = {
            "warnings": [],
            "info": [],
            "extreme_high_k": 0,
            "extreme_low_k": 0,
            "low_swirr_count": 0,
            "quality_score": "Good",
        }

        if len(perm) == 0:
            flags["warnings"].append("No permeability data calculated")
            return flags

        # Check for extreme values
        extreme_high = (perm > 10000).sum()  # > 10 Darcy
        extreme_low = (perm < 0.01).sum()  # < 0.01 mD
        flags["extreme_high_k"] = int(extreme_high)
        flags["extreme_low_k"] = int(extreme_low)

        if extreme_high > 0:
            flags["warnings"].append(
                f"{extreme_high} points with k > 10,000 mD (unrealistic)"
            )

        if extreme_low > 0:
            flags["info"].append(f"{extreme_low} points with k < 0.01 mD (tight rock)")

        # Check Swirr quality
        if len(swirr) > 0:
            low_swirr = (swirr < 0.08).sum()
            flags["low_swirr_count"] = int(low_swirr)

            if low_swirr > len(swirr) * 0.1:  # > 10% have very low Swirr
                flags["warnings"].append(
                    f"{low_swirr} points with Swirr < 0.08 (may cause overestimated k)"
                )

        # Check PHIE quality
        if len(phie) > 0:
            low_phie = (phie < 0.02).sum()
            if low_phie > len(phie) * 0.3:  # > 30% have very low porosity
                flags["info"].append(
                    f"{low_phie} points with PHIE < 0.02 (tight formation)"
                )

        # Overall quality assessment
        if len(flags["warnings"]) > 0:
            flags["quality_score"] = "Warning"
        elif extreme_high > 0 or extreme_low > 0:
            flags["quality_score"] = "Review"
        else:
            flags["quality_score"] = "Good"

        # Flow unit distribution
        if "FLOW_UNIT" in self.results:
            flow_unit = self.results["FLOW_UNIT"]
            flags["flow_unit_distribution"] = flow_unit.value_counts().to_dict()

        return flags

    # =========================================================================
    # NET PAY CALCULATIONS
    # =========================================================================

    def calculate_net_pay(
        self,
        vsh: pd.Series = None,
        phie: pd.Series = None,
        sw: pd.Series = None,
        vsh_cutoff: float = 0.4,
        phi_cutoff: float = 0.08,
        sw_cutoff: float = 0.6,
        step: float = None,
    ) -> Dict[str, float]:
        """
        Calculate Gross Sand, Net Reservoir, and Net Pay thicknesses.

        Args:
            vsh: Vshale series
            phie: Effective porosity series
            sw: Water saturation series
            vsh_cutoff: Vshale cutoff for gross sand
            phi_cutoff: Porosity cutoff for net reservoir
            sw_cutoff: Sw cutoff for net pay
            step: Depth step (auto-detected if None)

        Returns:
            Dictionary with thickness values
        """
        if vsh is None:
            vsh = self.results.get("VSH", self._make_series(0))
        if phie is None:
            phie = self.results.get("PHIE", self._make_series(0))
        if sw is None:
            # Respect the selected primary saturation first; named method
            # columns are only fallbacks for direct calculator use.
            sw = self.results.get(
                "SW",
                self.results.get(
                    "SW_ARCHIE",
                    self.results.get(
                        "SW_INDO",
                        self.results.get("SW_SIMAN", self._make_series(1)),
                    ),
                ),
            )

        # Per-sample thickness (a scalar ``step`` is used as given)
        if step is None:
            if "DEPTH" in self.data.columns:
                step = depth_increments(self.data["DEPTH"]).to_numpy()
            else:
                step = 0.1

        # Create flags
        gross_sand_flag = vsh < vsh_cutoff
        net_res_flag = gross_sand_flag & (phie > phi_cutoff)
        net_pay_flag = net_res_flag & (sw < sw_cutoff)

        # Store flags
        self.results["GROSS_SAND_FLAG"] = gross_sand_flag.astype(int)
        self.results["NET_RES_FLAG"] = net_res_flag.astype(int)
        self.results["NET_PAY_FLAG"] = net_pay_flag.astype(int)

        # Thicknesses (sum of dz) and weighted pay averages
        return pay_summary(
            gross_sand_flag, net_res_flag, net_pay_flag, vsh, phie, sw, step
        )

    def calculate_hcpv(
        self,
        phie: pd.Series = None,
        sw: pd.Series = None,
        depth: pd.Series = None,
        net_res_flag: pd.Series = None,
        net_pay_flag: pd.Series = None,
    ) -> Dict[str, pd.Series]:
        """
        Calculate Hydrocarbon Pore Volume (HCPV).

        HCPV represents the volumetric fraction of hydrocarbons per unit depth.

        Calculation Steps:
        1. HCPV_frac = PHIE * (1 - Sw)        # Hydrocarbon fraction per depth
        2. dz = depth[i] - depth[i-1]         # Depth increment (feet)
        3. dHCPV = HCPV_frac * dz             # Incremental HCPV
        4. HCPV_cum = cumsum(dHCPV)           # Cumulative HCPV
        5. Net gating:
           - Apply NET_RES_FLAG to get Net Reservoir HCPV
           - Apply NET_PAY_FLAG to get Net Pay HCPV

        Args:
            phie: Effective porosity (v/v)
            sw: Water saturation (v/v) - primary Sw
            depth: Depth in feet
            net_res_flag: Net reservoir flag (0 or 1)
            net_pay_flag: Net pay flag (0 or 1)

        Returns:
            Dict with all HCPV curves:
            - HCPV_FRAC: Hydrocarbon fraction = PHIE * (1-Sw)
            - dHCPV: Incremental HCPV (gross)
            - HCPV_CUM: Cumulative HCPV (gross)
            - HCPV_NET_RES: HCPV fraction gated by net reservoir
            - dHCPV_NET_RES: Incremental HCPV for net reservoir
            - HCPV_CUM_NET_RES: Cumulative HCPV for net reservoir
            - HCPV_NET_PAY: HCPV fraction gated by net pay
            - dHCPV_NET_PAY: Incremental HCPV for net pay
            - HCPV_CUM_NET_PAY: Cumulative HCPV for net pay
        """
        # Get data from results if not provided
        if phie is None:
            phie = self.results.get("PHIE", self._make_series(0.15))
        if sw is None:
            sw = self.results.get("SW", self._make_series(0.5))
        if depth is None:
            depth = self.data.get("DEPTH", pd.Series(range(len(self.data))))
        if net_res_flag is None:
            net_res_flag = self.results.get("NET_RES_FLAG", self._make_series(1))
        if net_pay_flag is None:
            net_pay_flag = self.results.get("NET_PAY_FLAG", self._make_series(1))

        # Ensure proper types - preserve original index for DataFrame alignment
        # BUG FIX: Using reset_index(drop=True) creates index 0,1,2,... which
        # causes NaN when assigning to self.results (which has filtered index
        # like 500,501,... in Per-Formation mode). Use .values to extract raw
        # numpy arrays, then create Series with the correct original index.
        original_index = self.data.index
        phie = pd.Series(
            phie.values if hasattr(phie, "values") else phie, index=original_index
        )
        sw = pd.Series(sw.values if hasattr(sw, "values") else sw, index=original_index)
        depth = pd.Series(
            depth.values if hasattr(depth, "values") else depth, index=original_index
        )
        net_res_flag = pd.Series(
            net_res_flag.values if hasattr(net_res_flag, "values") else net_res_flag,
            index=original_index,
        )
        net_pay_flag = pd.Series(
            net_pay_flag.values if hasattr(net_pay_flag, "values") else net_pay_flag,
            index=original_index,
        )

        # Step 1: Calculate HCPV fraction (hydrocarbon fraction per depth)
        hcpv_frac = phie * (1 - sw)
        hcpv_frac = np.clip(hcpv_frac, 0, 1)  # Bound to 0-1

        # Step 2: per-sample thickness (dz) in feet, the same rule as net pay.
        # Gaps (Per-Formation boundaries between non-adjacent formations) are
        # neutralised against the LOCAL logging step.
        dz = depth_increments(depth)

        # Step 3: Incremental HCPV (gross)
        d_hcpv = hcpv_frac * dz
        d_hcpv = d_hcpv.fillna(0)

        # Step 4: Cumulative HCPV (gross)
        hcpv_cum = d_hcpv.cumsum()

        # Step 5: Net Gating
        # Net Reservoir
        hcpv_net_res = hcpv_frac * net_res_flag
        d_hcpv_net_res = hcpv_net_res * dz
        d_hcpv_net_res = d_hcpv_net_res.fillna(0)
        hcpv_cum_net_res = d_hcpv_net_res.cumsum()

        # Net Pay
        hcpv_net_pay = hcpv_frac * net_pay_flag
        d_hcpv_net_pay = hcpv_net_pay * dz
        d_hcpv_net_pay = d_hcpv_net_pay.fillna(0)
        hcpv_cum_net_pay = d_hcpv_net_pay.cumsum()

        # Store in results
        self.results["HCPV_FRAC"] = hcpv_frac
        self.results["dHCPV"] = d_hcpv
        self.results["HCPV_CUM"] = hcpv_cum
        self.results["HCPV_NET_RES"] = hcpv_net_res
        self.results["dHCPV_NET_RES"] = d_hcpv_net_res
        self.results["HCPV_CUM_NET_RES"] = hcpv_cum_net_res
        self.results["HCPV_NET_PAY"] = hcpv_net_pay
        self.results["dHCPV_NET_PAY"] = d_hcpv_net_pay
        self.results["HCPV_CUM_NET_PAY"] = hcpv_cum_net_pay

        return {
            "HCPV_FRAC": hcpv_frac,
            "dHCPV": d_hcpv,
            "HCPV_CUM": hcpv_cum,
            "HCPV_NET_RES": hcpv_net_res,
            "dHCPV_NET_RES": d_hcpv_net_res,
            "HCPV_CUM_NET_RES": hcpv_cum_net_res,
            "HCPV_NET_PAY": hcpv_net_pay,
            "dHCPV_NET_PAY": d_hcpv_net_pay,
            "HCPV_CUM_NET_PAY": hcpv_cum_net_pay,
        }

    def get_results(self) -> pd.DataFrame:
        """Get all calculated results as a DataFrame."""
        return self.results

    def export_results(self, include_original: bool = True) -> pd.DataFrame:
        """
        Export results with or without original data.

        Args:
            include_original: Whether to include original log data

        Returns:
            DataFrame with results
        """
        self.renamed_inputs = []
        if include_original:
            computed = self.results.drop(columns=["DEPTH"], errors="ignore")
            # Input curves named like a result column are kept as <NAME>_IN so
            # the columns stay unique and the measured data stays visible.
            clash = [c for c in self.data.columns if c in computed.columns]
            original = self.data
            if clash:
                original = self.data.rename(columns={c: f"{c}_IN" for c in clash})
                self.renamed_inputs = clash
            return pd.concat([original, computed], axis=1)
        return self.results
