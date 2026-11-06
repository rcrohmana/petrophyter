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
    # Matplotlib-mathtext lines of the equation (one line per entry), shown rendered; the
    # plain ``equation`` stays the copyable text form.
    equation_tex: Tuple[str, ...] = ()
    # "Where" rows of (tex symbol, plain-English meaning with units).
    legend: Tuple[Tuple[str, str], ...] = ()


METHOD_TEXT: Dict[str, MethodInfo] = {
    "screening": MethodInfo(
        title="Low-resistivity low-contrast screening",
        equation_tex=(
            r"$\mathrm{score} = \sum_{i=1}^{6} c_i, \qquad c_i \in \{0,\ 1\}$",
            r"$\mathrm{flag} = 1 \quad \mathrm{when} \quad c_1 = c_3 = c_6 = 1$",
            r"$\mathrm{and} \quad \mathrm{score} \geq \min(s_{\mathrm{min}},\ N_{\mathrm{eval}})$",
        ),
        legend=(
            (r"$c_i$",
             "criterion i of the table, 1 when met, 0 when not met or unavailable"),
            (r"$s_{\mathrm{min}}$",
             "minimum criteria met (screen_min_score)"),
            (r"$N_{\mathrm{eval}}$",
             "number of criteria that can be evaluated for the sample"),
        ),
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
        equation_tex=(
            r"$R_{t,\mathrm{cut}} = R_t \ \mathrm{such\ that}\ S_w(R_t) = S_{w,\mathrm{target}}$",
            r"$\mathrm{Archie:}\quad R_{t,\mathrm{cut}} = \frac{a\,R_w}{\phi_e^{\,m}\,S_{w,\mathrm{target}}^{\,n}}$",
            r"$\mathrm{Simandoux:}\quad \frac{1}{R_t} = \frac{\phi_e^{\,m}\,S_w^{\,n}}{a\,R_w} + \frac{V_{\mathrm{sh}}\,S_w}{R_{\mathrm{sh}}}$",
            r"$\mathrm{Indonesian:}\quad \frac{1}{\sqrt{R_t}} = \left[\frac{V_{\mathrm{sh}}^{\,1 - V_{\mathrm{sh}}/2}}{\sqrt{R_{\mathrm{sh}}}} + \frac{\phi_e^{\,m/2}}{\sqrt{a\,R_w}}\right] S_w^{\,n/2}$",
        ),
        legend=(
            (r"$R_{t,\mathrm{cut}}$",
             "resistivity cutoff, ohm.m (RT_CUT)"),
            (r"$S_{w,\mathrm{target}}$",
             "Sw the cutoff is solved for (Rt cutoff Sw target)"),
            (r"$R_w,\ R_{\mathrm{sh}}$",
             "formation water and shale resistivity, ohm.m"),
            (r"$\phi_e,\ V_{\mathrm{sh}}$",
             "effective porosity and shale volume, fractions"),
            (r"$a,\ m,\ n$",
             "tortuosity factor, cementation and saturation exponents"),
        ),
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
        equation_tex=(
            r"$\mathrm{BVW} = \phi_e\,S_w$",
            r"$F_{\mathrm{wf}} = 1 \quad \mathrm{if} \quad S_w \leq S_{\mathrm{wirr}} + \Delta S_{\mathrm{mov}}$",
        ),
        legend=(
            (r"$\mathrm{BVW}$",
             "bulk volume water, fraction of the rock volume"),
            (r"$F_{\mathrm{wf}}$",
             "WATER_FREE_FLAG; evaluated in net reservoir only"),
            (r"$S_{\mathrm{wirr}}$",
             "irreducible water saturation"),
            (r"$\Delta S_{\mathrm{mov}}$",
             "movable water tolerance (movable_tol)"),
        ),
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
        equation_tex=(
            r"$\mathrm{BVW} = \phi_e\,S_w = k \quad \Rightarrow \quad S_w = \frac{k}{\phi_e}$",
        ),
        legend=(
            (r"$k$",
             "Buckles number, the constant bulk volume water of the zone"),
            (r"$\phi_e,\ S_w$",
             "effective porosity and water saturation"),
        ),
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
        equation_tex=(
            r"$\log_{10} R_t = -m \log_{10} \phi + \log_{10}(a\,R_w) - n \log_{10} S_w$",
            r"$S_w = 1:\quad \mathrm{slope} = -m, \quad \mathrm{intercept} = \log_{10}(a\,R_w)$",
            r"$R_w = \frac{a_{\mathrm{Rw}}}{a}$",
        ),
        legend=(
            (r"$a_{\mathrm{Rw}}$",
             "product a * Rw read from the fitted intercept"),
            (r"$m,\ n$",
             "cementation and saturation exponents"),
            (r"$\phi$",
             "porosity, fraction"),
            (r"$R_t,\ R_w$",
             "true and formation water resistivity, ohm.m"),
            (r"$S_w = 1$",
             "the wet points of the fit; the intercept is read at porosity 1"),
        ),
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
        equation_tex=(
            r"$R_t \ \rightarrow\ \mathrm{step}_1 \ \rightarrow\ \mathrm{step}_2 \ \rightarrow\ \cdots \ \rightarrow\ R_{t,\mathrm{sw}}$",
        ),
        legend=(
            (r"$R_t$",
             "measured resistivity, never modified"),
            (r"$\mathrm{step}_k$",
             "a correction switched on for the zone, applied in a fixed order"),
            (r"$R_{t,\mathrm{sw}}$",
             "RT_SW, the resistivity every Sw model reads"),
        ),
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
        equation_tex=(
            r"$\phi_{\mathrm{sand}} = \phi_{\mathrm{max}} - V_{d,s}\,(1 - \phi_{\mathrm{sh}})$",
            r"$\phi_t = (1 - V_{\mathrm{lam}})\,\phi_{\mathrm{sand}} + V_{\mathrm{lam}}\,\phi_{\mathrm{sh}}$",
            r"$V_{\mathrm{sh}} = V_{\mathrm{lam}} + (1 - V_{\mathrm{lam}})\,V_{d,s}$",
            r"$V_{\mathrm{lam}} = \frac{\phi_t - \phi_{\mathrm{max}} + V_{\mathrm{sh}}\,(1 - \phi_{\mathrm{sh}})}{1 - \phi_{\mathrm{max}}}$",
            r"$V_{\mathrm{disp}} = V_{\mathrm{sh}} - V_{\mathrm{lam}}$",
        ),
        legend=(
            (r"$\phi_{\mathrm{max}}$",
             "porosity of the clean sand"),
            (r"$\phi_{\mathrm{sh}}$",
             "porosity of the shale"),
            (r"$\phi_t$",
             "total porosity (PHIT)"),
            (r"$V_{\mathrm{lam}}$",
             "laminar shale volume (VLAM)"),
            (r"$V_{\mathrm{disp}}$",
             "dispersed shale volume (VDISP)"),
            (r"$V_{d,s}$",
             "dispersed clay as a share of the sand laminae pore space"),
            (r"$\phi_{\mathrm{sand}}$",
             "porosity of the sand laminae (PHI_SAND)"),
        ),
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
        equation_tex=(
            r"$\frac{1}{R_t} = \frac{1 - V_{\mathrm{lam}}}{R_{\mathrm{sand}}} + \frac{V_{\mathrm{lam}}}{R_{\mathrm{sh}}}$",
            r"$s = \frac{V_{\mathrm{lam}}\,R_t}{R_{\mathrm{sh}}}$",
            r"$R_{\mathrm{sand}} = \frac{(1 - V_{\mathrm{lam}})\,R_t}{1 - s}$",
        ),
        legend=(
            (r"$R_t$",
             "measured deep resistivity, ohm.m"),
            (r"$R_{\mathrm{sand}}$",
             "resistivity of the sand laminae, ohm.m (RT_SAND)"),
            (r"$R_{\mathrm{sh}}$",
             "resistivity of the shale laminae, ohm.m"),
            (r"$V_{\mathrm{lam}}$",
             "laminar shale volume, fraction"),
            (r"$s$",
             "share of the conductance carried by the shale; errors in Rt grow as 1 / (1 - s)"),
        ),
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
        equation_tex=(
            r"$\rho_b = \phi\,\rho_f + V_{\mathrm{ma}}\,\rho_{\mathrm{ma}} + V_{\mathrm{py}}\,\rho_{\mathrm{py}} + V_{\mathrm{sh}}\,\rho_{\mathrm{sh}}$",
            r"$\mathrm{PEF}\,\rho_b = \phi\,U_f + V_{\mathrm{ma}}\,U_{\mathrm{ma}} + V_{\mathrm{py}}\,U_{\mathrm{py}} + V_{\mathrm{sh}}\,U_{\mathrm{sh}}$",
            r"$1 = \phi + V_{\mathrm{ma}} + V_{\mathrm{py}} + V_{\mathrm{sh}}$",
            r"$R_{t,\mathrm{pyr}} = \frac{1}{\frac{1}{R_t} - f\,\frac{V_{\mathrm{py}}}{R_{\mathrm{py}}}}$",
        ),
        legend=(
            (r"$\rho,\ U$",
             "bulk density (g/cm3) and volumetric photoelectric factor (PEF * density) of each end-point"),
            (r"$V_{\mathrm{py}}$",
             "pyrite volume, fraction (VPYR)"),
            (r"$f$",
             "connected fraction of the pyrite that conducts"),
            (r"$R_{\mathrm{py}}$",
             "pyrite resistivity, ohm.m"),
            (r"$R_{t,\mathrm{pyr}}$",
             "resistivity without the pyrite conductance, ohm.m (RT_PYR)"),
        ),
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
        equation_tex=(
            r"$\mathrm{CEC}_{\mathrm{rock}} = V_{\mathrm{sh}}\,\mathrm{CEC}_{\mathrm{sh}}$",
            r"$Q_v = \frac{\mathrm{CEC}_{\mathrm{rock}}}{100}\,\rho_g\,\frac{1 - \phi_t}{\phi_t}$",
        ),
        legend=(
            (r"$\mathrm{CEC}_{\mathrm{rock}},\ \mathrm{CEC}_{\mathrm{sh}}$",
             "cation exchange capacity of the rock and of the shale, meq/100 g"),
            (r"$\rho_g$",
             "grain density, g/cm3"),
            (r"$\phi_t$",
             "total porosity, fraction"),
            (r"$Q_v$",
             "cation exchange per pore volume, meq/mL (QV_EST)"),
        ),
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
    "variable_mn": MethodInfo(
        title="Variable m and n",
        equation_tex=(
            r"$m = c_0 + c_1\,\phi + c_2\,V_{\mathrm{sh}} + \frac{c_3}{\phi}$",
            r"$n = d_0 + d_1\,V_{\mathrm{sh}}$",
            r"$\mathrm{Shell:}\quad m = 1.87 + \frac{0.019}{\phi}$",
            r"$\ln\frac{a\,R_w}{R_t} = m\,\ln\phi \quad (S_w = 1)$",
        ),
        legend=(
            (r"$c_0 \ldots c_3$",
             "coefficients of the m formula; c0 equal to the zone m gives a constant"),
            (r"$d_0,\ d_1$",
             "coefficients of the n formula; n is the zone constant when the formula is off"),
            (r"$S_w = 1$",
             "the fit uses the wet points of the Pickett plot"),
            (r"$\phi$",
             "porosity as a fraction"),
            (r"$V_{\mathrm{sh}}$",
             "shale volume, fraction"),
            (r"$R_t,\ R_w$",
             "resistivity the Sw models read and zone Rw, ohm.m"),
        ),
        equation=(
            "m = c0 + c1 * PHI + c2 * Vsh + c3 / PHI        (PHI as a fraction)\n"
            "n = d0 + d1 * Vsh        or the constant n of the zone\n"
            "Shell: m = 1.87 + 0.019 / PHI\n"
            "Fit on wet points (Sw = 1): ln(a * Rw / Rt) = m * ln(PHI)"
        ),
        assumptions=(
            "Every Sw model reads one m and one n per sample instead of the single zone values; "
            "with the default coefficients (c0 = the zone m) the curve is a constant and nothing "
            "changes. The fit uses the wet points of the Pickett plot, the Rt that the Sw models "
            "read and the zone Rw, solves for the coefficients the data can support, and is a "
            "proposal until you apply it. Values are clipped to the range shown and the number "
            "clipped is reported. "
            "Shell model: m = 1.87 + 0.019 / phi (phi as a fraction). m rises as porosity falls: "
            "2.25 at 5 percent, 2.06 at 10 percent, 1.965 at 20 percent. It is meant for "
            "carbonates and is only evaluated in zones whose lithology preset is Carbonate, "
            "unless you confirm it for the zone. Borai (1987) discusses this formula and its "
            "limits and reports that in tight, low-porosity carbonates offshore Abu Dhabi m "
            "decreases as porosity decreases, the opposite trend; check against core before "
            "relying on it. The linear porosity-and-clay form of the user formula is attributed "
            "to Guo et al. (2023); no published coefficients are shipped."
        ),
        limits=(
            "The formula is not evaluated below 2 percent porosity or where PHI or Vsh is "
            "missing; those samples keep the zone m and n and are counted. With an automatic Rw "
            "the fitted m depends on an Rw estimated with the constant m. A fit on bulk wet "
            "points is applied to the sand-lamina values in zones that read the sand basis. "
            "Wet points that are not water-bearing bias the fit, and the Rt that the fit reads "
            "moves when the Rt chain changes. The saturation exponent n has no fit."
        ),
        refs=SHIPPED_METHODS["variable_mn"],
    ),
    "invasion": MethodInfo(
        title="Radial invasion correction",
        equation_tex=(
            r"$J_i = \frac{1}{1 + \left(r_i / d_{\mathrm{inv}}\right)^{p}}$",
            r"$\frac{1}{R_{a,i}} = \frac{J_i}{R_{\mathrm{xo}}} + \frac{1 - J_i}{R_t}$",
            r"$R_{\mathrm{xo}} \geq R_{\mathrm{mf}}(T_{\mathrm{f}})$",
        ),
        legend=(
            (r"$J_i$",
             "share of tool i inside the invaded cylinder"),
            (r"$r_i$",
             "50 percent investigation diameter of the tool curve"),
            (r"$d_{\mathrm{inv}}$",
             "diameter of the invaded cylinder (di in the panel)"),
            (r"$p$",
             "exponent of the geometric function"),
            (r"$R_{a,i}$",
             "apparent resistivity read by tool i (deep, medium, shallow)"),
            (r"$R_{\mathrm{xo}},\ R_t$",
             "flushed-zone and true resistivity, ohm.m; Rxo is fixed if RXO is mapped"),
            (r"$R_{\mathrm{mf}}(T_{\mathrm{f}})$",
             "mud filtrate resistivity at formation temperature (Arps)"),
        ),
        equation=(
            "J_i = 1 / (1 + (r_i / di)^p)\n"
            "    share of tool i inside the invaded cylinder\n"
            "1 / Ra_i = J_i / Rxo + (1 - J_i) / Rt\n"
            "Unknowns: Rt, Rxo, di from the deep, medium\n"
            "    and shallow readings (Rxo fixed if RXO is mapped)\n"
            "Rxo >= Rmf at formation temperature (Arps)"
        ),
        assumptions=(
            "A one-step profile: a flushed cylinder of diameter di with resistivity Rxo around "
            "the hole and the undisturbed formation beyond it. The geometric factor is a generic "
            "function of the 50 percent investigation diameter r_i of each curve. The tool "
            "presets are generic placeholders, not specifications of any tool: confirm the radii "
            "and the exponent against the chart book of the tool that was run. RT, RM, RS and "
            "RXO must already be corrected by you for borehole, mud and shoulder-bed effects."
        ),
        limits=(
            "Step profile only: no annulus, no transition zone, no flushing gradient. The result "
            "is not unique when Rt is close to Rxo (those samples keep the measured Rt). It is "
            "sensitive to the radii and the exponent of the preset, and invalid in thin beds "
            "and near shoulder beds. It is not a substitute for service-company tornado charts: "
            "do not use it on vendor-corrected Rt. The pseudo-geometric function is a design "
            "choice, not a published fit; Doll (1949) is the physical basis."
        ),
        refs=SHIPPED_METHODS["invasion"],
    ),
}
