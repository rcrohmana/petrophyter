"""Monte Carlo uncertainty on HCPV and pay: distributions, sampling, kernel, statistics, tornado.

Pure module: numpy, scipy and pandas only, never Qt. Parameters (a, m, n, Rw, Rsh and the three
cutoffs) become distributions defined once for the project. A realisation draws one perturbation per
parameter and applies it to the resolved value of every well and zone segment, so the scopes,
presets and auto estimates the resolver produced are kept. The deterministic results and summary
are never touched.

Convention: P90 is the low case (exceeded with 90 % probability), P10 the high case.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple

# Canonical parameter order: sampling columns follow this order, never the UI order.
PARAM_ORDER: Tuple[str, ...] = ("a", "m", "n", "rw", "rsh", "vsh_cutoff", "phi_cutoff", "sw_cutoff")

# Parameters that act on the saturation stage (class S) and on the pay flags only (class C).
SATURATION_PARAMS = ("a", "m", "n", "rw", "rsh")
CUTOFF_PARAMS = ("vsh_cutoff", "phi_cutoff", "sw_cutoff")

# Default perturbation mode: relative for positive, skewed quantities, additive otherwise.
DEFAULT_MODES: Dict[str, str] = {
    "a": "relative", "m": "additive", "n": "additive", "rw": "relative", "rsh": "relative",
    "vsh_cutoff": "additive", "phi_cutoff": "additive", "sw_cutoff": "additive",
}

# Hard physical bounds applied after perturbation, per segment. (low, high, low_open, high_open):
# an open end excludes the bound itself (a cutoff of 0 means nothing passes).
BOUNDS: Dict[str, Tuple[float, float, bool, bool]] = {
    "a": (0.1, 5.0, False, False),
    "m": (1.0, 4.0, False, False),
    "n": (1.0, 4.0, False, False),
    "rw": (1e-3, 100.0, False, False),
    "rsh": (0.05, 5000.0, False, False),
    "vsh_cutoff": (0.0, 1.0, True, False),
    "phi_cutoff": (0.0, 0.5, False, False),
    "sw_cutoff": (0.0, 1.0, True, False),
}

# Triangular [low, mid, high] offsets the "Suggested ranges" button fills (fractions for relative).
SUGGESTED_RANGES: Dict[str, Tuple[float, float, float]] = {
    "a": (-0.10, 0.0, 0.10),
    "m": (-0.15, 0.0, 0.15),
    "n": (-0.20, 0.0, 0.20),
    "rw": (-0.20, 0.0, 0.25),
    "rsh": (-0.20, 0.0, 0.25),
    "vsh_cutoff": (-0.05, 0.0, 0.05),
    "phi_cutoff": (-0.02, 0.0, 0.02),
    "sw_cutoff": (-0.05, 0.0, 0.05),
}

KINDS = ("triangular", "normal", "uniform")
MODES = ("relative", "additive")
SAMPLINGS = ("lhs", "random")

N_MIN, N_MAX = 50, 5000
DEFAULT_N = 300        # owner rule: 500 unless the 10-well Simandoux varying-n run exceeds 30 s
DEFAULT_SEED = 12345
NORMAL_TRUNCATION_SD = 3.0
CONVERGENCE_TOLERANCE = 0.02   # half-sample percentiles within 2 % of P50

# Inputs held at their base value in every realisation (stated in the result header and exports).
NOT_VARIED = "porosity, shale point, GR baseline"


@dataclass
class Distribution:
    """One parameter's perturbation; offsets are fractions (relative) or absolute units (additive)."""

    name: str
    enabled: bool = False
    kind: str = "triangular"     # "triangular" | "normal" | "uniform"
    mode: str = "relative"       # "relative" | "additive"
    low: float = 0.0             # triangular/uniform lower offset; normal: unused
    mid: float = 0.0             # triangular mode offset; normal: mean offset
    high: float = 0.0            # triangular/uniform upper offset
    sd: float = 0.0              # normal only (truncated at +/- NORMAL_TRUNCATION_SD)


def default_distributions() -> Dict[str, Distribution]:
    """Every parameter, disabled, with its default mode."""
    return {name: Distribution(name=name, mode=DEFAULT_MODES[name]) for name in PARAM_ORDER}


@dataclass
class UncertaintyConfig:
    n: int = DEFAULT_N
    seed: int = DEFAULT_SEED
    sampling: str = "lhs"
    distributions: Dict[str, Distribution] = field(default_factory=default_distributions)
    # Pairwise rank correlation applied by a Gaussian copula, keyed by a pair in PARAM_ORDER order.
    correlations: Dict[Tuple[str, str], float] = field(default_factory=dict)

    def enabled_names(self) -> Tuple[str, ...]:
        """Enabled parameters in canonical order."""
        return tuple(n for n in PARAM_ORDER
                     if n in self.distributions and self.distributions[n].enabled)
