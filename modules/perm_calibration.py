"""
Wyllie-Rose permeability coefficients from core data or from porosity (pure, no Qt).

``K = C · φ^P / Swirr^Q`` with Swirr from Buckles (``Swirr = k_buckles / φ``,
:func:`modules.petrophysics.swirr_buckles`, the same function the pipeline uses).
:func:`calibrate_from_core` fits C and P to core porosity/permeability pairs
with Q held at the entered value (with Buckles Swirr, K = C·kb^-Q·φ^(P+Q), so
C, P and Q together are not identifiable);
:func:`estimate_from_porosity` picks textbook coefficients from the mean
porosity when there is no usable core. :func:`zone_mask` restricts samples to
one zone so a calibration can run on the edited scope (multi-well follow-ups
spec §8).
"""

from typing import Dict, Optional

import numpy as np
import pandas as pd

from modules.petrophysics import swirr_buckles

MIN_CORE_PAIRS = 5
MIN_POROSITY_SAMPLES = 10
PAIR_TOLERANCE_FT = 0.5

# Initial guess and bounds of the core fit (Timur-like start); C is fitted as log10(C).
_X0 = (8581.0, 4.4)
_BOUNDS_LOG_C = (np.log10(10.0), np.log10(50000.0))
_BOUNDS_P = (2.0, 8.0)
DEFAULT_Q = 2.0
# Swirr from Buckles is clipped to [0.05, 0.5]; at the clip it no longer depends on φ.
_SWIRR_CLIP = (0.05, 0.5)
_PHI_FLOOR_BUCKLES = 0.01

APPLY_WARNING = (
    "The coefficients were fitted with Buckles Swirr; the current Swirr method differs, "
    "so the fitted permeability will not reproduce the core."
)
BUCKLES_SWIRR_METHODS = ("Buckles Number", "All Methods")


def predict_permeability(porosity, C: float, P: float, Q: float, k_buckles: float):
    """Wyllie-Rose permeability with Buckles Swirr, exactly as the pipeline computes it.

    ``K = C · max(φ, 0.001)^P / Swirr^Q`` with :func:`swirr_buckles`
    (the pipeline's additional clip of K to 0.001 to 50000 mD is not applied).
    """
    phi = np.asarray(porosity, dtype=float)
    swirr = swirr_buckles(phi, k_buckles)
    return C * np.power(np.maximum(phi, 0.001), P) / np.power(swirr, Q)


def apply_warning(fit: Dict, swirr_method: str, k_buckles: float) -> Optional[str]:
    """Warning text for applying a core fit, or None when the project matches the fit.

    The fit was made with Buckles Swirr at ``fit["k_buckles"]``; the coefficients
    reproduce the core only if the project also uses Buckles Swirr with that
    ``k_buckles``.
    """
    if fit is None or fit.get("method") != "core":
        return None
    same_k = abs(float(fit.get("k_buckles", k_buckles)) - float(k_buckles)) <= 1e-12
    if swirr_method in BUCKLES_SWIRR_METHODS and same_k:
        return None
    return APPLY_WARNING


def zone_mask(depths, formation_tops, zone: Optional[str]) -> np.ndarray:
    """Boolean mask of ``depths`` inside ``zone`` (all True without a zone)."""
    depths = np.asarray(depths, dtype=float)
    if not zone:
        return np.ones(len(depths), dtype=bool)
    if formation_tops is None or not getattr(formation_tops, "formations", None):
        return np.zeros(len(depths), dtype=bool)
    from modules.param_scopes import normalize_zone
    from modules.pipeline import assign_zones

    labels, _ = assign_zones(pd.Series(depths), formation_tops)
    return np.asarray(labels == normalize_zone(zone))


def pair_core_samples(perm_depths, perm, por_depths, por,
                      tolerance_ft: float = PAIR_TOLERANCE_FT):
    """Pair each permeability sample with the nearest porosity sample within tolerance.

    Returns ``(porosity, permeability)`` arrays of the matched pairs.
    """
    perm_depths, perm = np.asarray(perm_depths, float), np.asarray(perm, float)
    por_depths, por = np.asarray(por_depths, float), np.asarray(por, float)
    matched_por, matched_perm = [], []
    if len(por_depths) == 0:
        return np.array(matched_por), np.array(matched_perm)
    for i, depth in enumerate(perm_depths):
        idx = int(np.argmin(np.abs(por_depths - depth)))
        if abs(por_depths[idx] - depth) < tolerance_ft:
            matched_por.append(por[idx])
            matched_perm.append(perm[i])
    return np.array(matched_por), np.array(matched_perm)


def fit_core(porosity, permeability, k_buckles: float,
             min_pairs: int = MIN_CORE_PAIRS, q: float = DEFAULT_Q, x0=None):
    """Core fit with a reason: ``(fit, None)`` on success, ``(None, reason)`` on failure.

    Fits log10(C) and P with Q held at ``q``; ``x0`` is an optional starting
    ``(C, P)``. Pairs that are not finite or not positive are not usable and are
    left out of the fit; ``reason`` names the cause (too few usable pairs, or
    the optimiser not converging). Plugs whose Buckles Swirr sits at the clip
    carry no information on the porosity exponent; they stay in the fit (the
    pipeline clips them the same way) and are counted in ``clipped_swirr``.
    """
    from scipy import optimize

    porosity = np.asarray(porosity, float)
    permeability = np.asarray(permeability, float)
    usable = (np.isfinite(porosity) & np.isfinite(permeability)
              & (porosity > 0) & (permeability > 0))
    porosity, permeability = porosity[usable], permeability[usable]
    if len(porosity) < min_pairs:
        return None, f"{len(porosity)} usable plugs; need {min_pairs}"
    q = float(q)
    swirr = swirr_buckles(porosity, k_buckles)
    raw = k_buckles / np.maximum(porosity, _PHI_FLOOR_BUCKLES)
    clipped = int(np.sum((raw < _SWIRR_CLIP[0]) | (raw > _SWIRR_CLIP[1])))
    phi_k = np.maximum(porosity, 0.001)
    target = np.log10(permeability + 0.001)

    def objective(params):
        log_c, P = params
        k_pred = 10.0 ** log_c * np.power(phi_k, P) / np.power(swirr, q)
        return np.sum((np.log10(k_pred + 0.001) - target) ** 2)

    start = _X0 if x0 is None else tuple(x0)
    start = (np.log10(start[0]), start[1])
    result = optimize.minimize(
        objective, start, bounds=[_BOUNDS_LOG_C, _BOUNDS_P], method="L-BFGS-B",
    )
    if not result.success:
        return None, f"{len(porosity)} usable plugs; the fit did not converge"
    log_c, P = result.x
    return {"method": "core", "C": float(10.0 ** log_c), "P": float(P), "Q": q,
            "pairs": int(len(porosity)), "clipped_swirr": clipped,
            "swirr": "Buckles", "k_buckles": float(k_buckles)}, None


def calibrate_from_core(porosity, permeability, k_buckles: float,
                        min_pairs: int = MIN_CORE_PAIRS, q: float = DEFAULT_Q,
                        x0=None) -> Optional[Dict]:
    """Least-squares fit of log10(C) and P in log10(k) to matched core pairs, Q held at ``q``.

    Returns ``{"method": "core", "C", "P", "Q", "pairs", "clipped_swirr",
    "swirr": "Buckles", "k_buckles"}``, or None when there are fewer than
    ``min_pairs`` usable pairs or the optimiser does not converge
    (:func:`fit_core` also gives the reason).
    """
    return fit_core(porosity, permeability, k_buckles, min_pairs, q, x0)[0]


def estimate_from_porosity(phie) -> Optional[Dict]:
    """Textbook coefficients from the mean PHIE, or None with too few samples."""
    phie = pd.Series(phie, dtype=float).dropna()
    if len(phie) < MIN_POROSITY_SAMPLES:
        return None
    phi_mean = float(phie.mean())
    if phi_mean > 0.20:
        C, P, Q = 10000.0, 4.0, 2.0      # high porosity, unconsolidated
    elif phi_mean > 0.12:
        C, P, Q = 8581.0, 4.4, 2.0       # typical sandstone (Timur)
    else:
        C, P, Q = 5000.0, 5.0, 2.2       # tight formation
    return {"method": "porosity", "C": C, "P": P, "Q": Q,
            "phi_mean": phi_mean, "samples": int(len(phie))}
