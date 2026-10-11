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

### GR baseline modes *(v1.0)*

- **Statistical (Auto):** Uses P5/P95 percentiles.
- **Custom (Manual):** Uses user-specified GRmin and GRmax.

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
| **Waxman-Smits** | Uses Qv and B parameters | v1.2 |
| **Dual-Water** | Uses Swb and Rwb parameters | v1.2 |

### Indonesian

The Indonesian (Poupon-Leveaux) equation

`1/√Rt = [ √(φe^m / (a × Rw)) + Vsh^(1 − Vsh/2) / √Rsh ] × Sw^(n/2)`

is solved in closed form, `Sw = ( (1/√Rt) / (√(φe^m / (a × Rw)) + Vsh^(1 − Vsh/2) / √Rsh) )^(2/n)`, with Vsh
clipped to 0–1 and Sw clipped to 0–1. A sample with no RT, no PHIE or PHIE ≤ 0.001 gives no Sw. No iterative
solver is involved.

### Simandoux

The form used is

`1/Rt = φe^m × Sw^n / (a × Rw) + Vsh × Sw / Rsh`

(the shale term carries no (1 − Vsh) factor). With n = 2 it is the quadratic `A × Sw² + B × Sw − C = 0` with
`A = φe^m / (a × Rw)`, `B = Vsh / Rsh`, `C = 1 / Rt`, and `Sw = (−B + √(B² + 4AC)) / (2A)`. For any other n the
single root of `A × Sw^n + B × Sw − C` in 0–1 is found numerically per sample (Brent's method); a sample whose
root lies above 1 gets Sw = 1. Sw is clipped to 0–1.

### Automatic Rw and Rsh

When Rw or Rsh is set to automatic, the run estimates it from the well's own logs *(v1.7.0–v1.7.1; the method
is revised in v1.7.2)*:

- **Rw (apparent water resistivity).** Candidate samples are clean (Vsh < 0.3), porous (PHIE > 0.15; PHIT when
  there is no PHIE) and have RT > 0. For each, `Rwa = RT × φ^m / a`. Rw is the median of the Rwa values at or
  below their 25th percentile, the water-bearing end of the distribution, limited to 0.01–5 ohm·m. Fewer than
  10 candidates means no estimate.
- **Rsh.** The median RT of the shale samples (Vsh > 0.8), limited to 0.5–50 ohm·m. No shale sample means no
  estimate.

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
| **All Methods** | Calculates every method for comparison | v1.0 |

## Permeability

| Method | Equation | Version |
|---|---|---|
| **Timur** | `K = 8581 × (PHIE^4.4) / (Swirr^2)` | v1.0 |
| **Wyllie-Rose** | `K = C × (PHIE^P) / (Swirr^Q)` | v1.0 |

- Core-calibrated fitting is available for coefficients C, P, and Q. Each core permeability sample is paired with the nearest core porosity sample within 0.5 ft, and `log10(K)` is fitted by least squares with `Swirr = k_buckles / PHIE` (clipped to 0.05 to 0.8). At least five pairs are needed.
- The fit follows the edited scope. At well·zone scope only that zone's core pairs are used, with the zone's Buckles k. A zone with fewer than five pairs gives no result and is never widened to the whole well. Without core data, C, P, and Q are estimated from the mean PHIE of the scope (at least 10 samples): 10000, 4.0, 2.0 above 0.20; 8581, 4.4, 2.0 from 0.12 to 0.20; 5000, 5.0, 2.2 below 0.12.
- Flow units are classified as Tight, Poor, Fair, Good, or Excellent.

## Net Pay Analysis *(v1.0)*

- **Gross Sand:** Vsh is below its cutoff.
- **Net Reservoir:** Gross Sand and PHIE is above its cutoff.
- **Net Pay:** Net Reservoir and Sw is below its cutoff.
- **N/G Ratios:** Net-to-gross values are calculated for reservoir and pay.
- **Average Properties:** Mean PHIE, Sw, and Vsh are reported within net pay.

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

- **HCPV Fraction:** `PHIE × (1 - Sw)`
- **Incremental HCPV (dHCPV):** Value for each depth interval
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
