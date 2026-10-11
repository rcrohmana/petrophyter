[Back to README](../README.md)

# Calculation Methods

## Shale Volume (Vsh)

| Method | Description | Version |
|---|---|---|
| **GR Linear** | `Vsh = (GR - GRmin) / (GRmax - GRmin)` | v1.0 |
| **Larionov Tertiary** | `Vsh = 0.083 × (2^(3.7×IGR) - 1)` | v1.0 |
| **Larionov Older** | `Vsh = 0.33 × (2^(2×IGR) - 1)` | v1.0 |

`IGR = (GR - GRmin) / (GRmax - GRmin)`, clipped to 0–1. These three are the only Vsh methods; there is no
Clavier, Stieber, SP or neutron-density Vsh.

**Primary Vsh** *(v1.7.2)*. When several methods are selected, `VSH` (the curve every later step uses) comes
from the **Primary Vsh** method; the others remain as comparison curves. By default it is the first selected
method (Linear), and it falls back to the first selected method when the chosen one is no longer selected.
Before v1.7.2 `VSH` was the largest of the selected methods.

### GR baseline modes *(v1.0)*

- **Statistical (Auto):** Uses P5/P95 percentiles.
- **Custom (Manual):** Uses user-specified GRmin and GRmax.

**Zone baseline** *(v1.7.2)*. An automatic baseline set for a zone takes GRmin from the zone's P5. GRmax is the
zone's P95 only when it reaches at least `well GRmin + 0.75 × (well GRmax − well GRmin)`, i.e. when the zone
contains shale; otherwise GRmax is the well's, and the zone's diagnostics say "zone has no shale; GRmax from the
well". A clean sand with GR 30–60 in a well with baseline 20–120 thus gets a mean Vsh of about 0.15 instead of
0.48. The 20 API minimum separation still applies.

### Shale parameter estimation *(v1.0)*

- **Fixed Threshold:** User-specified Vsh threshold.
- **Quantile Mode:** Uses a Vsh distribution quantile from 0.80 to 0.99.
- **Stability Sweep:** Sweeps a threshold range to find the most stable parameters.
- Log gating and IQR outlier filtering are applied.

## Porosity

| Method | Description | Version |
|---|---|---|
| **Density (PHID)** | `PHID = (ρma - ρb) / (ρma - ρfl)`; `PHIE_D = PHID - Vsh × (ρma - ρsh) / (ρma - ρfl)` | v1.0 |
| **Neutron (PHIN)** | `PHIN = NPHI - NPHI_matrix`; `PHIE_N = PHIN - Vsh × (NPHI_shale - NPHI_matrix)` | v1.0, shale term v1.7.2 |
| **Sonic (PHIS)** | Wyllie time-average equation | v1.0 |
| **Density-Neutron (PHIE_DN)** | The shale-corrected PHIE_D and PHIE_N combined like PHIT (below) | v1.0, combination v1.7.2 |

A sample where no selected porosity method gives a value has no PHIE: it is left empty (NaN) and drops out of
Sw, pay and HCPV. The run lists how much of the interval has porosity; a fixed porosity is never substituted
*(v1.7.1)*.

**Neutron shale term** *(v1.7.2)*. PHIN is the neutron reading on the matrix scale (`NPHI − NPHI_matrix`), so
the shale reading is shifted the same way: pure shale gives `PHIE_N = 0`. Before v1.7.2 the raw `NPHI_shale`
was subtracted, which left 0.02 of porosity in pure shale with the sandstone matrix.

### Total porosity (PHIT) *(v1.7.2)*

Every porosity path has a total porosity, sample by sample:

| Inputs at the sample | PHIT |
|---|---|
| PHID and PHIN | **Average** `(PHID + PHIN) / 2`, signs kept (default), or **RMS** `√((PHID² + PHIN²) / 2)`; RMS on gas-flagged samples whatever the choice |
| PHID only | PHID |
| PHIN only | PHIN |
| PHIS only | PHIS |
| none | empty (NaN) |

PHIT is limited to 0–0.45 after the combination, so a negative mean becomes 0 instead of a positive square.
The combination, **D-N combination** (`dn_combination`), can be set per well and per zone. The arithmetic
average is the density-neutron total porosity of liquid-filled formations; the root-mean-square is the
Gaymard-Poupon (1968) gas-zone form, which is why gas-flagged samples always use it. Choosing **RMS**
everywhere reproduces the PHIT of v1.7.1 and older.

### Gas correction *(v1.1)*

- Enable or disable gas correction for PHIE.
- Configure the NPHI factor from 0.10 to 0.50.
- Configure the RHOB factor from 0.05 to 0.30.
- **Gas flag** *(v1.7.2)*: a sample is flagged when `PHID − PHIN ≥ gas_crossover_min` (0.02 v/v by default)
  and `Vsh ≤ gas_vsh_max` (0.40 by default). A bare crossover is noise within a few porosity units, and shale
  also crosses over. The flag (`GAS_FLAG`) is computed whenever gas correction is on, whatever the primary
  PHIE method, and it switches PHIT to RMS on those samples.
- **PHIE_GAS** *(v1.7.2)*: on flagged samples PHIN is divided by `(1 − NPHI factor)` and PHID multiplied by
  `(1 − RHOB factor)`; both are shale-corrected and averaged (the correction already removes the gas effect,
  so RMS on top would count it twice), and the result is limited to the sample's PHIT, then to 0.45.
  Effective porosity never exceeds total porosity.

## Water Saturation

| Model | Description | Version |
|---|---|---|
| **Archie** | Clean-sand equation: `Sw = (a × Rw / (φ^m × Rt))^(1/n)` | v1.0 |
| **Indonesian** | Closed form for shaly sands (below) | v1.0 |
| **Simandoux** | `1/Rt = φe^m × Sw^n / (a × Rw) + Vsh × Sw / Rsh` (below) | v1.0 |
| **Waxman-Smits** | Uses Qv and B parameters; solved on PHIT | v1.2, PHIT v1.7.2 |
| **Dual-Water** | Uses Swb and Rwb parameters; solved on PHIT | v1.2, PHIT v1.7.2 |

`SW`, the curve that pay, HCPV, Swirr and permeability read, is the **effective** water saturation of the
primary model for every model *(v1.7.2)*.

### Valid samples and bounds *(v1.7.2)*

One rule for all five models:

| At the sample | Sw |
|---|---|
| RT missing, or the model's porosity missing | empty (NaN) |
| the model's porosity ≤ 0.001, RT valid | 1.0 (no pore space holds no hydrocarbon) |

The model's porosity is PHIE for Archie, Indonesian and Simandoux, and PHIT for the Waxman-Smits and
Dual-Water solve. Vsh is limited to 0–1 in every model. Before v1.7.2, Indonesian, Waxman-Smits and Dual-Water
gave no Sw at porosity ≤ 0.001, and Simandoux did not limit Vsh.

Sw stays limited to 0–1 (a value outside it has no physical meaning and would corrupt averages and HCPV), but
every limited sample is counted per model and per zone in `summary["solver_diagnostics"]`:

| Count | Meaning |
|---|---|
| `at_upper_bound` | Sw above 1.05 before the limit (and the Waxman-Smits / Dual-Water solver's upper fallback with its root above 1.05); a water leg scatters a little above 1, so that scatter is not counted |
| `at_lower_bound` | Sw below 0 (Dual-Water: below Swb) before the limit, and the solver's lower fallback |
| `no_porosity` | porosity ≤ 0.001, Sw set to 1 |
| `no_phit` | Waxman-Smits / Dual-Water sample with PHIE but no PHIT, left empty |
| `bvh_exceeds_phie`, `phie_above_phit` | inconsistent porosities (below) |
| `no_root`, `failed` | solver counts of Waxman-Smits and Dual-Water |

The run warns when more than 10 % of a zone's clean samples (Vsh below the Vsh cutoff) sit at the upper bound
("Sw > 1.05 before clipping in N clean samples: check Rw, m, n or Rt"), and when more than 5 % of a zone's
samples have inconsistent porosities. Smaller counts are listed as information. The Diagnostics tab shows the
counts per model and zone.

### Waxman-Smits and Dual-Water: total and effective Sw *(v1.7.2)*

Both models are written for total porosity (`F* = a / φt^m`), so they are solved on PHIT. The solved total
saturation is kept as `SWT_WS` / `SWT_DW`; `SW_WS` / `SW_DW` hold the effective saturation, from the
hydrocarbon volume:

`BVH = min(PHIT × (1 − Swt), PHIE)`, `Swe = 1 − BVH / PHIE`

so that `PHIE × (1 − Swe) = BVH`. For Dual-Water with `PHIE = PHIT × (1 − Swb)` this is the textbook
`Swe = (Swt − Swb) / (1 − Swb)` (Clavier, Coates and Dumanoir 1984). Example: Rt 20 ohm·m, PHIT 0.25,
PHIE 0.225, Dual-Water gives Swt 0.2162, Swe 0.1291 and an HCPV fraction of 0.1959.

The hydrocarbon volume is reproduced exactly when `PHIT × (1 − Swt) ≤ PHIE`. When the two porosities disagree,
no more hydrocarbon is reported than either allows:

| Case | Example (PHIT, PHIE, Swt) | Result | Counted as |
|---|---|---|---|
| `PHIT × (1 − Swt) > PHIE` | 0.25, 0.10, 0.20 | Swe 0, BVH = PHIE | `bvh_exceeds_phie` |
| PHIE > PHIT | 0.25, 0.30, 0.20 | Swe 0.333, BVH exact | `phie_above_phit` |
| PHIE ≤ 0.001 | any | Swe 1, BVH 0 | `no_porosity` |

These cases arise when PHIE and PHIT come from different tools or parameters (for example a sonic PHIE with a
density-neutron PHIT). Before v1.7.2 both models were solved on PHIE and `SW_WS` / `SW_DW` held that value.

### Indonesian

The Indonesian (Poupon-Leveaux) equation

`1/√Rt = [ √(φe^m / (a × Rw)) + Vsh^(1 − Vsh/2) / √Rsh ] × Sw^(n/2)`

is solved in closed form, `Sw = ( (1/√Rt) / (√(φe^m / (a × Rw)) + Vsh^(1 − Vsh/2) / √Rsh) )^(2/n)`, with Vsh
clipped to 0–1 and Sw clipped to 0–1. Samples without RT or PHIE, and PHIE ≤ 0.001, follow the rule in
[Valid samples and bounds](#valid-samples-and-bounds-v172). No iterative solver is involved.

### Simandoux

The form used is

`1/Rt = φe^m × Sw^n / (a × Rw) + Vsh × Sw / Rsh`

(the shale term carries no (1 − Vsh) factor). With n = 2 it is the quadratic `A × Sw² + B × Sw − C = 0` with
`A = φe^m / (a × Rw)`, `B = Vsh / Rsh`, `C = 1 / Rt`, and `Sw = (−B + √(B² + 4AC)) / (2A)`. For any other n the
single root of `A × Sw^n + B × Sw − C` in 0–1 is found numerically per sample (Brent's method); a sample whose
root lies above 1 gets Sw = 1. Sw is clipped to 0–1.

### Automatic Rw and Rsh

When Rw or Rsh is set to automatic, the run estimates it from the well's own logs *(v1.7.2)*:

- **Rw (apparent water resistivity, Rwa method).**
  1. Candidate samples are clean (Vsh < 0.3), porous (PHIE > 0.15; PHIT when there is no PHIE) and have
     RT > 0. For each, `Rwa = RT × φ^m / a`.
  2. The seed is the 5th percentile of Rwa.
  3. Against the seed, a sample is **water-like** when its Archie Sw would be at least 0.8
     (`Rwa ≤ seed / 0.8^n`) and **hydrocarbon-like** when it would be at most 0.5 (`Rwa ≥ seed / 0.5^n`).
  4. With fewer than 10 water-like samples there is no estimate ("no water-bearing samples found").
  5. Otherwise Rw is the median Rwa of the water-like samples. With at least 10 hydrocarbon-like samples the
     estimate is a water leg; with fewer, Rwa shows no water/hydrocarbon contrast and the run warns that the
     estimate assumes these samples are water-bearing: check it against a known water zone. No log-only
     method can tell a uniform hydrocarbon column from water.
  6. Rw is limited to 0.01–5 ohm·m, with a warning when the limit applies.

  The Rw/Rsh page and the run summary report the quality (`water_leg`, `uniform`, `no_water`) and the number
  of water-like and hydrocarbon-like samples. References: Hingle (1959); Pickett (1966).
- **Rsh.** The median RT of the shale samples (Vsh > 0.8), limited to 0.5–50 ohm·m with a warning when the
  limit applies. Fewer than 10 shale samples means no estimate.

Before v1.7.2, Rw was the median of the Rwa values at or below their 25th percentile, which followed the
hydrocarbon column when the water leg was short (a well with 10 % water gave 0.80 ohm·m instead of 0.050), and
a single shale sample was enough for Rsh.

When an estimate is not available, the entered value is used and the run reports it as a warning
("Rw could not be estimated automatically; using the entered Rw of …"). With the formation-temperature
correction on, both estimates are made at the Rw reference temperature (see
[Formation temperature](#formation-temperature)).

### Archie presets

- **Sandstone (Humble):** a=0.62, m=2.15, n=2.0
- **Carbonate:** a=1.0, m=2.0, n=2.0
- **Custom:** User-defined a, m, and n

At a well, project·zone, or well·zone scope, a named preset supplies a, m, and n at that scope. An explicit a, m, or n at the same or a more specific scope wins over the preset.

### Formation temperature

When **Correct resistivities for formation temperature** is on, resistivities are brought from their reference temperature to the formation temperature of each sample with Arps' equation, with temperatures in °F:

`R(T2) = R(T1) × (T1 + 6.77) / (T2 + 6.77)`

Formation temperature is `T(z) = Ts + g × (TVD(z) − d0) / 100`, where `Ts` is the surface temperature, `g` the gradient in °F per 100 ft, `d0` the temperature datum depth (the depth at which `Ts` applies, 0 by default), and `TVD(z)` the true vertical depth at the sample.

**TVD source**, in this order:

1. A TVD curve mapped in Curve Mapping. Gaps inside the curve are interpolated linearly, and samples outside its coverage are extrapolated with the slope at its edge (limited to 0 to 1). The share of extrapolated samples is reported with the source.
2. The depth index, when the LAS header says the log is on TVD.
3. Measured depth, assumed vertical. A note is added when a TVD-like curve exists but is not mapped, or when the header has an inclination or deviation entry.

A mapped curve is rejected, with a note, and the next source is used if it has fewer than two valid samples, decreases with measured depth by more than 0.01 ft, or exceeds measured depth by more than 1 ft (a wrong curve, TVDSS, or wrong units).

**Auto gradient.** `g = (BHT − Ts) / (TD_TVD − d0) × 100`, using the header bottom-hole temperature and total depth. `TD_TVD` is the total depth on the same TVD source and datum as the samples; without a TVD curve, the header total depth is used as measured depth. The header temperature is a measured value and is not corrected to static formation temperature.

**What is corrected.**

- **Rw** is corrected from the Rw reference temperature.
- **Rsh, auto.** The shale resistivity of each sample (Vsh > 0.8) is first normalised to the Rw reference temperature, and its median is the Rsh. The Rsh used in Sw is then corrected back to formation temperature at each sample.
- **Rsh, manual.** Corrected from the Rsh reference temperature when one is set. Without one, Rsh is used as entered. Applying a calculated Rsh stores the Rw reference temperature with it when the correction is on.
- **Rwb** (Dual-Water) is corrected from the Rw reference temperature.
- **Waxman-Smits B** can be calculated from temperature (opt-in) with the Juhasz (1981) correlation, per sample:

  `B = (−1.28 + 0.225 T − 0.0004059 T²) / (1 + Rw^1.23 × (0.045 T − 0.27))`

  with `T` in °C and `Rw` the brine resistivity at that temperature (the Arps-corrected Rw; the entered Rw when the correction is off, with a warning). `T` is floored at 25 °C, because the correlation is fitted to roughly 25 to 200 °C data and its numerator turns negative below about 6 °C.

All of these are off by default, and with the options off the results are identical to earlier versions. Indonesian and Simandoux use the per-sample Rsh, and the run summary records the temperature range, the TVD source, and the Rsh reference.

## Irreducible Water Saturation (Swirr)

| Method | Description | Version |
|---|---|---|
| **Hierarchical** | Recommended when core calibration is unavailable | v1.0 |
| **Buckles Number** | `Swirr = k_buckles / PHIE` | v1.0 |
| **Clean Zone** | Minimum Sw in clean hydrocarbon zones | v1.0 |
| **Statistical** | P5 of Sw in clean zones | v1.0 |
| **All Methods** | Calculates every method for comparison; Buckles is the one used | v1.0 |

**Hierarchical.** With more than 10 clean hydrocarbon samples (Vsh < 0.10, Sw < 0.50, PHIE > 0.05), Swirr is
the P10 of their Sw; otherwise it is Buckles (`k_buckles / PHIE`, PHIE floored at 0.01). The estimate is then
limited in this order *(v1.7.2)*: `Swirr = clip(min(estimate, Sw), 0.05, 0.60)`. The floor is applied last, so
Swirr is never below 0.05, even where the measured Sw is. The samples raised to the floor, limited to the
measured Sw and limited to 0.60 are counted in the run and shown in Diagnostics. The floor and 0.60 counts
are information unless they are more than 10 % of the samples, when they are a warning; the samples limited to
the measured Sw are always information, since `min(estimate, Sw)` is how the method is defined. Before v1.7.2
the floor came first, so Swirr could fall below 0.05.

**The selected method is the one used** *(v1.7.2)*. `SWIRR`, which feeds permeability, comes from the selected
method: Clean Zone → `SWIRR_CLEANZONE`, Statistical → `SWIRR_STAT`, Buckles Number → `SWIRR_BUCKLES`. All Methods
keeps Buckles as the one used and is shown as "All methods (Buckles used)". Where the selected method has no
value (for example no clean samples), the sample takes Buckles, with a warning and a count; `SWIRR_METHOD`
names the series used per sample, and the run summary names the method actually used. Before v1.7.2 a method
other than Hierarchical only filled its comparison curve, and permeability used Buckles or a constant 0.2.

## Permeability

| Method | Equation | Version |
|---|---|---|
| **Timur** | `K = 8581 × (PHIE^4.4) / (Swirr^2)` | v1.0 |
| **Wyllie-Rose** | `K = C × (PHIE^P) / (Swirr^Q)` | v1.0 |

- Core-calibrated fitting is available for coefficients C and P *(Q held, v1.7.2)*. Each core permeability sample is paired with the nearest core porosity sample within 0.5 ft, and `log10(K)` is fitted by least squares for `log C` and `P` with **Q held at the entered value** (2.0 by default). With Buckles Swirr the model is `K = C × kb^−Q × φ^(P+Q)`, so C, P and Q cannot all be fitted at once; holding Q makes the fit identifiable. At least five pairs are needed.
- Calibration and the run use the **same** Buckles Swirr *(v1.7.2)*: `Swirr = k_buckles / max(φ, 0.01)`, limited to 0.05–0.5. Before v1.7.2 the calibration limited it to 0.05–0.8 with no porosity floor, so at φ 0.025 the applied permeability was 2.56 × the fitted model. Plugs whose Swirr sits at a limit say nothing about the porosity exponent and are counted in the result.
- The fitted coefficients assume Buckles Swirr with the Buckles k used in the fit. **Apply** warns when the Swirr method is not Buckles Number or All Methods, or when `k_buckles` differs, because the fitted permeability would then not reproduce the core.
- The fit follows the edited scope. At well·zone scope only that zone's core pairs are used, with the zone's Buckles k. A zone with fewer than five pairs gives no result and is never widened to the whole well. Without core data, C, P, and Q are estimated from the mean PHIE of the scope (at least 10 samples): 10000, 4.0, 2.0 above 0.20; 8581, 4.4, 2.0 from 0.12 to 0.20; 5000, 5.0, 2.2 below 0.12.
- Flow units are classified as Tight, Poor, Fair, Good, or Excellent.

## Net Pay Analysis *(v1.0)*

- **Gross Sand:** Vsh is below its cutoff.
- **Net Reservoir:** Gross Sand and PHIE is above its cutoff.
- **Net Pay:** Net Reservoir and Sw is below its cutoff.
- **N/G Ratios:** Net-to-gross values are calculated for reservoir and pay.
- **Average Properties** *(weighted, v1.7.2)*: within net pay, PHIE and Vsh are thickness-weighted
  (`Σx × dz / Σdz`) and Sw is pore-volume weighted (`ΣPHIE × Sw × dz / ΣPHIE × dz`), so the average Sw is the
  one that reproduces the hydrocarbon volume. Example: PHIE 0.30 and 0.10 with Sw 0.2 and 0.6 average to Sw
  0.30 (0.40 as a plain mean, before v1.7.2). On a uniform depth step the PHIE and Vsh averages are unchanged.
  The field total in exports weights each well's Sw by its `ΣPHIE × dz` over pay (`phih_pay`).

**Thickness of a sample (dz)** *(v1.7.2)*. One rule for gross, net reservoir, net pay and HCPV:

1. The intervals between samples, `Δi = di − di−1`, and the local step `si`, the median Δ over a centred window
   of 11 intervals.
2. An interval larger than 3 × its local step is a gap (for example between two formations in a
   Per-Formation run), and counts as one local step.
3. Each sample's thickness is the midpoint rule, `dzi = (Δi + Δi+1) / 2`; the first and last samples take their
   one interval.

On a uniform step this equals the previous rule. Before v1.7.2 the gap test used the median step of the whole
well, so in a log that changes from 0.1524 ft to 0.5 ft the coarse section counted as gaps (HCPV reported
30.5 ft for a 100 ft section), and net pay and HCPV used different rules.

Configurable slider cutoffs are:

- Vsh: 0–100%
- PHIE: 0–30%
- Sw: 0–100%

### Zone cutoff diagnostics

For a run with zones, each zone is checked against the cutoffs applied in that zone (which can differ from zone to zone). A sample counts only when Vsh, PHIE, and Sw are all valid. The pass tests are `Vsh < cutoff`, `PHIE > cutoff`, and `Sw < cutoff`. The result is stored per zone in `summary["zone_diagnostics"]`, with the number of valid samples, gross, net reservoir, and net pay thickness, and the pass fraction of each cutoff.

| Status | Condition | Limiting cutoff |
|---|---|---|
| `no_data` | No valid sample | none |
| `no_gross` | No sample passes the Vsh cutoff | Vsh |
| `no_reservoir` | Gross exists, no sample passes the PHIE cutoff | PHIE |
| `no_pay` | Net reservoir exists, no sample passes the Sw cutoff | Sw |
| `ok` | Net pay exists | see below |

For an `ok` zone, the limiting cutoff is the one with the lowest pass fraction among the samples that pass the other two cutoffs. It is `None` when every cutoff passes everything. A zone without gross, reservoir, or pay always names the cutoff that removed everything.

## Hydrocarbon Pore Volume (HCPV) *(v1.2)*

- **HCPV Fraction:** `PHIE × (1 - Sw)`, with `Sw` the effective saturation of every model (see
  [Waxman-Smits and Dual-Water](#waxman-smits-and-dual-water-total-and-effective-sw-v172))
- **Incremental HCPV (dHCPV):** `HCPV fraction × dz` for each sample, with the same dz as net pay
  ([Thickness of a sample](#net-pay-analysis-v10)) *(v1.7.2)*
- **Cumulative HCPV:** Running total
- Display modes: Net Pay, Net Reservoir, Gross, and Fraction Only
- Visibility can be toggled with a checkbox.

## Core Data Validation

- Import TXT or CSV core data.
- Match depths automatically with configurable interpolation.
- Report Bias, MAE, RMSE, R², and Spearman ρ.
- A core sample is compared with the log only when valid log samples lie within the matching distance on
  both sides of it (an exact depth match counts), so a core is never matched across a gap in the log. Cores
  beside a gap are left out of the statistics and counted ("N core samples in log gaps") *(v1.7.1)*.
- Core null values (such as −999.25, in porosity, permeability and grain density) and non-physical values
  (negative porosity, permeability ≤ 0) are excluded and counted with a reason, before statistics or
  calibration *(v1.7.1)*.
- Display porosity core-versus-log crossplots with a 1:1 reference line.
- Display permeability core-versus-log crossplots in the log10 domain.
- Display depth tracks with core overlays.

## Quality Control *(v1.0)*

- **Curve QC:** Valid percentage, minimum, maximum, mean, standard deviation, and quality score
- **Non-positive values:** At load, resistivity, RHOB and DT samples ≤ 0 are set to empty (NaN) and counted
  in the load notes, since logarithms and the Sw equations are undefined there. NPHI is not masked (slightly
  negative neutron porosity is real) *(v1.7.1)*.
- **Data-gap detection:** Evaluated per curve
- **Outlier detection:** IQR method
- **Triple-combo preview:** GR, RT, RHOB/NPHI/DT with gas-crossover shading
