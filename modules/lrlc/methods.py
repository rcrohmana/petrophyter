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
            "With no step switched on in a zone, RT_SW equals RT there. The listing shows the "
            "steps that can be switched on; the line Sw reads names the curves in use."
        ),
        refs=(),
    ),
    "thomas_stieber": MethodInfo(
        title="Thomas-Stieber laminar and dispersed shale",
        equation=(
            "phi_sand = phi_max - Vd_s * (1 - phi_sh)\n"
            "PHIT     = (1 - Vlam) * phi_sand + Vlam * phi_sh\n"
            "Vsh      = Vlam + (1 - Vlam) * Vd_s\n"
            "Vlam     = [PHIT - phi_max + Vsh * (1 - phi_sh)] / (1 - phi_max)\n"
            "Vdisp    = Vsh - Vlam"
        ),
        assumptions=(
            "Clean sand laminae carry dispersed clay in their pores and are interbedded with "
            "shale laminae of porosity phi_sh. phi_max is the porosity of the clean sand and "
            "phi_sh that of the shale; both are read from the clean and the shale samples of the "
            "well or zone and applied only when you confirm them. Samples are classed laminar, "
            "dispersed or mixed by the laminar share of the shale volume, and structural or "
            "clay-supported where they fall outside the triangle."
        ),
        limits=(
            "The result depends on both end-points and on a total porosity that is free of "
            "shale and gas effects. Samples outside the triangle are clamped to its edge and "
            "counted. The classes are a screening aid, not a lithofacies log."
        ),
        refs=SHIPPED_METHODS["thomas_stieber"],
    ),
    "laminated": MethodInfo(
        title="Laminated-sand resistivity (parallel conductance)",
        equation=(
            "1/Rt = (1 - Vlam) / Rsand + Vlam / Rsh\n"
            "s = Vlam * Rt / Rsh\n"
            "RT_SAND = (1 - Vlam) * Rt / (1 - s)"
        ),
        assumptions=(
            "Sand and shale laminae conduct in parallel because the tool current runs along the "
            "bedding. Vlam is the laminar shale volume from the Thomas-Stieber split or a "
            "constant. The sand-lamina resistivity then feeds the Sw model, which with the sand "
            "basis reads the porosity and shale volume of the sand laminae."
        ),
        limits=(
            "A relative error in Rt is amplified by 1 / (1 - s). Samples with s above the warning "
            "limit are counted and samples above the invalid limit are left empty. Where the "
            "shale volume is above the Hagiwara limit nothing is corrected. A curve that is "
            "already shoulder-bed corrected or deconvolved is not raw Rt; use the raw deep curve."
        ),
        refs=SHIPPED_METHODS["laminated"],
    ),
    "pyrite": MethodInfo(
        title="Pyrite volume and parallel-conductance correction",
        equation=(
            "RHOB     = phi*rho_f + Vma*rho_ma + Vpy*rho_py + Vsh*rho_sh\n"
            "PEF*RHOB = phi*U_f + Vma*U_ma + Vpy*U_py + Vsh*U_sh\n"
            "1 = phi + Vma + Vpy + Vsh\n"
            "RT_PYR = 1 / (1/Rt - f * Vpy / Rpy)"
        ),
        assumptions=(
            "Pyrite adds density and photoelectric absorption that a clean sand does not, so the "
            "volume is solved from RHOB and PEF with fixed end-points. Only the connected "
            "fraction f of the pyrite conducts; f and the pyrite resistivity Rpy are calibration "
            "values for the field, not defaults to trust."
        ),
        limits=(
            "Barite mud, siderite, heavy minerals and a padded PEF raise PEF without pyrite. "
            "Porosity from the bulk density is biased low where pyrite is present. Samples that "
            "remove most of the measured conductance are counted as sensitive."
        ),
        refs=SHIPPED_METHODS["pyrite"],
    ),
    "qv": MethodInfo(
        title="Cation exchange per pore volume (Qv)",
        equation=(
            "CEC_rock = Vsh * cec_shale          (meq/100 g)\n"
            "Qv = CEC_rock / 100 * rho_g * (1 - PHIT) / PHIT     (meq/mL)"
        ),
        assumptions=(
            "The clay exchange capacity of the rock scales with the shale volume. cec_shale is "
            "the capacity of the shale, taken from core measurements when they exist. The array "
            "replaces the single Qv of the Waxman-Smits model; the other Sw models do not read it."
        ),
        limits=(
            "Samples with porosity below the minimum or Qv above the maximum are left empty and "
            "use the constant Qv. Vsh from the gamma ray is only a proxy for clay capacity; "
            "calibrate against core CEC before relying on the values."
        ),
        refs=SHIPPED_METHODS["qv"],
    ),
}
