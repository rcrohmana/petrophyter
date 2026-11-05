"""Method texts for the Method & Reference box (pure text, no Qt).

Equations use the notation of docs/calculation-methods.md. The reference keys of the
shipped tools come from SHIPPED_METHODS so the box and the registry cannot drift apart.
"""

from dataclasses import dataclass
from typing import Dict, Tuple

from modules.lrlc import SHIPPED_METHODS


@dataclass(frozen=True)
class MethodInfo:
    title: str
    equation: str
    assumptions: str
    limits: str
    refs: Tuple[str, ...]
    # Optional criteria table shown between ``equation`` and ``equation_after``:
    # rows of (code, condition), numbered from 1 in the box.
    criteria: Tuple[Tuple[str, str], ...] = ()
    equation_after: str = ""


METHOD_TEXT: Dict[str, MethodInfo] = {
    "screening": MethodInfo(
        title="Low-resistivity low-contrast screening",
        equation="score = number of criteria met (0 to 6)",
        criteria=(
            ("LOW_RT", "RT < screen_rt_max"),
            ("HC", "GAS_FLAG = 1  or  RT/RS >= 1.0"),
            ("PHI", "PHIE > phi_cutoff"),
            ("VSH", "VSH < vsh_cutoff"),
            ("CONTRAST", "RT/Rsh <= screen_contrast_max"),
            ("SW_HIGH", "Sw >= sw_cutoff"),
        ),
        equation_after=(
            "flag = 1 when criteria 1, 3 and 6 are met\n"
            "       and score >= min(screen_min_score, criteria evaluable)"
        ),
        assumptions=(
            "A sample that is porous, low in resistivity and called wet by the conventional Sw is "
            "a candidate; the hydrocarbon indicator, the shale volume and the resistivity contrast "
            "to the shale raise confidence. Screening reads measured values and changes no Sw, "
            "flag or pay. Thresholds are design defaults, calibrate per field; Boyd 1995 and "
            "Worthington 2000 are the qualitative basis."
        ),
        limits=(
            "A candidate is not a pay zone: it needs a test, core or a recalibrated model. The "
            "RT/RS separation is a weak indicator with saline mud. A criterion without its input "
            "is counted as not met and listed as unavailable."
        ),
        refs=SHIPPED_METHODS["screening"],
    ),
    "rt_cutoff": MethodInfo(
        title="Resistivity cutoff (RT_CUT)",
        equation=(
            "RT_CUT = Rt at which the selected Sw model returns sw_target\n"
            "Archie form: Rt_cut = a * Rw / (PHIE^m * sw_target^n)\n"
            "Simandoux: 1/Rt = PHIE^m * Sw^n / (a * Rw) + Vsh * Sw / Rsh\n"
            "Indonesian: 1/sqrt(Rt) = [Vsh^(1-Vsh/2) / sqrt(Rsh) + PHIE^(m/2) / sqrt(a * Rw)] * Sw^(n/2)"
        ),
        assumptions=(
            "The cutoff is found per sample by solving the same Sw model that produces SW, with "
            "the same inputs, for the Rt that gives sw_target. A sample is pay by the Sw criterion "
            "when its Rt is above RT_CUT. The curve is an overlay: it changes no Sw, flag or pay."
        ),
        limits=(
            "No cutoff is returned where the model cannot reach the target inside 0.01 to 100000 "
            "ohm.m, or where porosity is missing or at most 0.001. A published field cutoff, such "
            "as the value Liu et al. 2023 derived for their formation, is a field result and not "
            "a default here."
        ),
        refs=SHIPPED_METHODS["rt_cutoff"],
    ),
    "bvw": MethodInfo(
        title="Bulk volume water and water-free flag",
        equation=(
            "BVW = PHIE * Sw\n"
            "WATER_FREE_FLAG = 1 when net reservoir and Sw <= Swirr + movable_tol"
        ),
        assumptions=(
            "Sw is the effective saturation of the primary model, so BVW is on the same basis as "
            "HCPV. Where Sw is close to Swirr the water is irreducible, so a sample with high Sw "
            "can still produce water-free."
        ),
        limits=(
            "The flag is a screen, not a test result. It depends on the Swirr method in use and is "
            "not evaluated where Swirr is missing."
        ),
        refs=SHIPPED_METHODS["bvw"],
    ),
    "buckles": MethodInfo(
        title="Buckles plot",
        equation="BVW = PHIE * Sw = k   ->   Sw = k / PHIE",
        assumptions=(
            "Points of one rock type at irreducible water lie on a hyperbola of constant bulk "
            "volume water. The line drawn for each zone uses its Buckles number."
        ),
        limits=(
            "Points that do not follow a hyperbola are not at irreducible water or mix rock types. "
            "The plot shows net-reservoir samples only."
        ),
        refs=SHIPPED_METHODS["buckles"],
    ),
    "pickett": MethodInfo(
        title="Pickett plot and wet-point fit",
        equation=(
            "log10(Rt) = -m * log10(PHI) + log10(a * Rw) - n * log10(Sw)\n"
            "wet points (Sw = 1): slope = -m, intercept at PHI = 1 is log10(a * Rw)\n"
            "Rw = a_Rw / a"
        ),
        assumptions=(
            "Wet points are chosen as the low-resistivity envelope of the clean samples in "
            "porosity bins and fitted with a robust (Huber) line. Rw is taken as constant, after "
            "the temperature normalisation when that is on."
        ),
        limits=(
            "The wet points must be water-bearing: a hydrocarbon-bearing envelope overstates Rw. "
            "Clay conduction biases m low. The fit needs enough points over a wide enough porosity "
            "range, and results outside the valid ranges are shown but cannot be applied."
        ),
        refs=SHIPPED_METHODS["pickett"],
    ),
    "rt_chain": MethodInfo(
        title="Rt correction chain",
        equation="RT (measured, never modified) -> step 1 -> step 2 -> ... -> RT_SW",
        assumptions=(
            "Each correction step reads the output of the step before it, in a fixed order, per "
            "zone. Every water-saturation model reads RT_SW, the result of the last step; the "
            "measured RT is kept unchanged."
        ),
        limits=(
            "No correction step is installed in this release, so RT_SW equals RT. The listing "
            "shows the steps that can be switched on."
        ),
        refs=(),
    ),
}
