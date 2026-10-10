[Back to README](../README.md)

# Calculation Methods

## Shale Volume (Vsh)

| Method | Description | Version |
|---|---|---|
| **GR Linear** | `Vsh = (GR - GRmin) / (GRmax - GRmin)` | v1.0 |
| **Larionov Tertiary** | `Vsh = 0.083 × (2^(3.7×IGR) - 1)` | v1.0 |
| **Larionov Older** | `Vsh = 0.33 × (2^(2×IGR) - 1)` | v1.0 |
| **Clavier** | GR-index shale-volume correlation | — |
| **Stieber** | GR-index shale-volume correlation | — |
| **SP** | Spontaneous Potential method | v1.0 |
| **Neutron-Density** | Crossplot-separation method | v1.0 |

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
| **Density (PHID)** | `PHIE = (ρma - ρb) / (ρma - ρfl) - Vsh × correction` | v1.0 |
| **Neutron (PHIN)** | Matrix and shale correction | v1.0 |
| **Sonic (PHIS)** | Wyllie time-average equation | v1.0 |
| **Neutron-Density (PHIT)** | RMS average from the crossplot | v1.0 |

### Gas correction *(v1.1)*

- Enable or disable gas correction for PHIE.
- Configure the NPHI factor from 0.10 to 0.50.
- Configure the RHOB factor from 0.05 to 0.30.
- Detect gas zones automatically from neutron-density crossover.

## Water Saturation

| Model | Description | Version |
|---|---|---|
| **Archie** | Clean-sand equation: `Sw = (a × Rw / (φ^m × Rt))^(1/n)` | v1.0 |
| **Indonesian** | Iterative solver for shaly sands | v1.0 |
| **Simandoux** | Quadratic solution for shaly sands | v1.0 |
| **Waxman-Smits** | Uses Qv and B parameters | v1.2 |
| **Dual-Water** | Uses Swb and Rwb parameters | v1.2 |

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
- Display porosity core-versus-log crossplots with a 1:1 reference line.
- Display permeability core-versus-log crossplots in the log10 domain.
- Display depth tracks with core overlays.

## Quality Control *(v1.0)*

- **Curve QC:** Valid percentage, minimum, maximum, mean, standard deviation, and quality score
- **Bad-hole detection:** Derived from the caliper log
- **Data-gap detection:** Evaluated per curve
- **Outlier detection:** IQR method
- **Triple-combo preview:** GR, RT, RHOB/NPHI/DT with gas-crossover shading
