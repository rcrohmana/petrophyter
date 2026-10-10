"""
Wyllie-Rose permeability coefficients from core data or from porosity (pure, no Qt).

``K = C · φ^P / Swirr^Q`` with Swirr from Buckles (``Swirr = k_buckles / φ``).
:func:`calibrate_from_core` fits C, P, Q to core porosity/permeability pairs;
:func:`estimate_from_porosity` picks textbook coefficients from the mean
porosity when there is no usable core. :func:`zone_mask` restricts samples to
one zone so a calibration can run on the edited scope (multi-well follow-ups
spec §8).
"""

from typing import Dict, Optional

import numpy as np
import pandas as pd

MIN_CORE_PAIRS = 5
MIN_POROSITY_SAMPLES = 10
PAIR_TOLERANCE_FT = 0.5

# Initial guess and bounds of the core fit (Timur-like start).
_X0 = [8581, 4.4, 2.0]
_BOUNDS = [(10, 50000), (2, 8), (0.5, 4)]


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


def calibrate_from_core(porosity, permeability, k_buckles: float,
                        min_pairs: int = MIN_CORE_PAIRS) -> Optional[Dict]:
    """Least-squares fit of C, P, Q in log10(k) to matched core pairs.

    Returns ``{"method": "core", "C", "P", "Q", "pairs"}``, or None when there
    are fewer than ``min_pairs`` pairs or the optimiser does not converge.
    """
    from scipy import optimize

    porosity = np.asarray(porosity, float)
    permeability = np.asarray(permeability, float)
    if len(porosity) < min_pairs:
        return None
    swirr = np.clip(k_buckles / porosity, 0.05, 0.8)

    def objective(params, phi, swi, k):
        C, P, Q = params
        k_pred = C * (phi ** P) / (swi ** Q)
        return np.sum((np.log10(k_pred + 0.001) - np.log10(k + 0.001)) ** 2)

    result = optimize.minimize(
        objective, _X0, args=(porosity, swirr, permeability),
        bounds=_BOUNDS, method="L-BFGS-B",
    )
    if not result.success:
        return None
    C, P, Q = result.x
    return {"method": "core", "C": float(C), "P": float(P), "Q": float(Q),
            "pairs": int(len(porosity))}


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
