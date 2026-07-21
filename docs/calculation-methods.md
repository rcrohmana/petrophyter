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

- Core-calibrated fitting is available for coefficients C, P, and Q.
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
