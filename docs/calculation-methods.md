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

With saturation-height modelling on, `SW_SHF` is a second saturation from the height above the free water level; it can optionally replace `SW` for pay and HCPV. See [Saturation-height modelling](#saturation-height-modelling-v1100).

### Per-sample m and n *(v1.13.0)*

In every equation above `m` and `n` can be one value per sample instead of one value per zone. The values come from the curves `M_VAR` and `N_VAR` that [Variable m and n](#variable-m-and-n-v1130) writes; the models are otherwise unchanged. A sample then reads `φ^m_i` and `Sw^n_i` with its own exponents. Archie, Indonesian, Waxman-Smits and Dual-Water take the exponent array directly. Simandoux is solved per sample: where `n_i = 2` (to within 1e-9) the quadratic above is used, and where `n_i` has any other value the root is found numerically. An array filled with one constant gives the scalar result exactly. The exponents must be finite and positive; a length that does not match the data is an error. With no variable m/n in use, the models are called with the single zone values, as before.

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

The run warns when more than 10 % of a zone's clean samples (Vsh below the Vsh cutoff; at least 10 of them) sit at the upper bound
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
| **Rock type** (`PERM_RT`) | `K = FZI² × φz² × φe / 0.0314²` with the FZI of the sample's rock type; no Swirr (see [Rock Typing](#rock-typing-v180)) | v1.8.0 |

- Core-calibrated fitting is available for coefficients C and P *(Q held, v1.7.2)*. Each core permeability sample is paired with the nearest core porosity sample within 0.5 ft, and `log10(K)` is fitted by least squares for `log C` and `P` with **Q held at the entered value** (2.0 by default). With Buckles Swirr the model is `K = C × kb^−Q × φ^(P+Q)`, so C, P and Q cannot all be fitted at once; holding Q makes the fit identifiable. At least five pairs are needed.
- Calibration and the run use the **same** Buckles Swirr *(v1.7.2)*: `Swirr = k_buckles / max(φ, 0.01)`, limited to 0.05–0.5. Before v1.7.2 the calibration limited it to 0.05–0.8 with no porosity floor, so at φ 0.025 the applied permeability was 2.56 × the fitted model. Plugs whose Swirr sits at a limit say nothing about the porosity exponent and are counted in the result.
- The fitted coefficients assume Buckles Swirr with the Buckles k used in the fit. **Apply** warns when the Swirr method is not Buckles Number or All Methods, or when `k_buckles` differs, because the fitted permeability would then not reproduce the core.
- The fit follows the edited scope. At well·zone scope only that zone's core pairs are used, with the zone's Buckles k. A zone with fewer than five pairs gives no result and is never widened to the whole well. Without core data, C, P, and Q are estimated from the mean PHIE of the scope (at least 10 samples): 10000, 4.0, 2.0 above 0.20; 8581, 4.4, 2.0 from 0.12 to 0.20; 5000, 5.0, 2.2 below 0.12.
- **Primary permeability** *(v1.8.0)*. `FLOW_UNIT` and the permeability quality flags are computed from the primary permeability: **Timur** (the default, which reproduces earlier versions), **Wyllie-Rose**, or **Rock type**. It is a project and well setting, not a zone setting, so one well never mixes formulas. *Rock type* needs rock typing turned on with applied definitions and an FZI for every rock type; otherwise the run uses Timur for that well and warns ("Primary permeability 'Rock type' not used (…); Timur is used."). Samples without a rock type have no `PERM_RT`, and are not filled from Timur.
- Flow units are classified as Tight, Poor, Fair, Good, or Excellent from the primary permeability. They are permeability classes, not rock types; `ROCK_TYPE` is a separate column.

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

**Per rock type** *(v1.8.0)*. With rock typing on, the same flags, thickness and weights are summed per rock type (and per zone and rock type), so gross sand, net reservoir, net pay and HCPV per rock type plus the unassigned samples add up to the well totals. See [Rock Typing](#rock-typing-v180).

**Saturation-height Sw** *(v1.10.0)*. When **Use SHF Sw for pay and HCPV** is on, the Sw cutoff and the averages read `SW_PAY` (the saturation-height Sw where it exists, else `SW`) instead of `SW`. See [Saturation-height modelling](#saturation-height-modelling-v1100).

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

## Saturation-height modelling *(v1.10.0)*

Saturation-height modelling gives a second water saturation, `SW_SHF`, from the height of each sample above the free water level and the sample's porosity and permeability. It is off by default; with it off, a run is exactly as in 1.9.0. `SW` stays the resistivity result in every case.

### Capillary pressure and the J-function

For each laboratory sample the capillary pressure `Pc` (psi) is turned into the Leverett J-function (Leverett 1941), which brings samples of one rock type onto one curve:

```
J = 0.2166 × Pc × sqrt(k / φ) / (σ cosθ)
```

with `k` in mD, `φ` as a fraction and `σ cosθ` in dyne/cm. The constant 0.2166 comes from the unit conversions (1 psi = 68 947.57 dyne/cm², 1 mD = 9.869233 × 10⁻¹² cm²). For a mercury-injection point the water saturation is `Sw = 1 − S_Hg`.

**Laboratory to reservoir conditions.** `Pc_res = Pc_lab × (σ cosθ)_res / (σ cosθ)_lab`. Because J uses the `σ cosθ` of the system it was measured in, J is the same from the laboratory or the reservoir pressure. The default values (dyne/cm, magnitudes) can be edited on the Saturation-Height tab:

| System | σ cosθ | Basis |
|---|---|---|
| Air-brine (laboratory) | 72 | 72 dyne/cm at 0° |
| Mercury-air (laboratory) | 367.7 | \|480 cos 140°\| |
| Oil-brine (laboratory) | 41.6 | 48 dyne/cm at 30° |
| Oil-water (reservoir) | 26 | 30 dyne/cm at 30° |
| Gas-water (reservoir) | 50 | 50 dyne/cm at 0° |

The system of each Pc file is chosen when the file is imported; J is computed with that system's `σ cosθ`, so no reservoir conversion enters the fit itself.

**Pressure and height.** `Pc_res = 0.433527 × Δρ × h` and `h = Pc_res / (0.433527 × Δρ)`, with `h` in feet above the free water level and `Δρ = ρ_water − ρ_hydrocarbon` in g/cc (0.433527 psi/ft per g/cc, the 62.428 lb/ft³ of fresh water divided by 144). On the logs the J-function at height `h` is `J = 0.2166 × 0.433527 × Δρ × h × sqrt(k / φ) / (σ cosθ)_res`. The water density can differ from zone to zone (it is set with each contact, 0.95 to 1.25 g/cc, blank = the project value); the project densities default to water 1.03, oil 0.75 and gas 0.25 g/cc, placeholders to confirm for your field. The water must be denser than the hydrocarbon.

### Fit forms

`Sw` is fitted as a function of J, for one rock type at a time, by a bounded robust least squares on the Sw residuals (soft-L1 loss, scale 0.05) from several starting points. The power law is the usual industry form; Brooks-Corey (Brooks and Corey 1964) has an entry J and a residual water saturation.

| Form | Equation | Parameters (bounds) |
|---|---|---|
| Power law | `Sw = min(1, c × J^d)` | `c` (0.001 to 10), `d` (-6 to -0.05) |
| Brooks-Corey | `Se = (J_d / J)^λ` for `J > J_d`, otherwise 1; `Sw = Swi + (1 - Swi) × Se` | `J_d` (0.001 to 20), `λ` (0.1 to 6), `Swi` (0 to 0.6) |

`Sw` is 1 where J is 0 or below and is limited to the range 0 to 1. A fit needs at least 3 samples and 8 points (power law) or 5 samples and 15 points (Brooks-Corey); with less, the tab reports "insufficient data" and the fit has no parameters. Points at or below the minimum Pc you set (closure), points with `Sw` outside 0 to 1, and samples without a positive porosity and permeability are left out. By default each sample has equal weight (a point weighs 1 / the number of points of its sample), so a long mercury-injection curve does not outweigh a short porous-plate one; weighting every point equally is an option.

### Core Pc fits and log-derived fits

| | Core Pc | Log-derived |
|---|---|---|
| Data | Laboratory Pc curves of the selected wells | Log `SW` against height, in a well with a known contact |
| J from | Laboratory Pc, porosity, permeability and `σ cosθ` | Height, log permeability and porosity, reservoir `σ cosθ` and `Δρ` |
| Independent of the resistivity Sw | Yes: a real cross-check | No: it is fitted to `SW` |
| Shown as | `core Pc` | `log-derived` |

A log-derived fit smooths and interpolates the resistivity Sw along a hydrostatic profile. Its residual measures how well `SW` follows height, not whether `SW` is right. **Log-derived fits are a cross-check only and are never used for pay**: when any fit in use for a well is log-derived, the option to use SHF Sw for pay and HCPV is refused for that well and a diagnostics note says so. Fits are stored per project and shown with their basis (`core_pc`, `log` or `mixed` in the summary).

### Free water level, OWC and height

The contact to enter is the **free water level** (FWL, where `Pc = 0`), not the oil-water or gas-water contact. The OWC sits higher than the FWL by the entry height of the rock; taking the OWC read from the logs as the FWL makes the transition-zone `Sw` too high.

Each well has a default contact and optionally one per zone (a zone without its own contact uses the default; a sample with neither has no `SW_SHF`). A contact has a depth, a fluid (oil or gas, which sets the density and the reservoir `σ cosθ`) and an optional water density. The height of a sample is `HAFWL = FWL (TVD) − TVD`, in feet, positive above the FWL.

- **TVD source.** Heights use the mapped TVD curve, else a TVD depth index, else measured depth assumed vertical, exactly as for temperature. The source used is named in the summary and in the notes of the run; for a deviated well measured depth gives a wrong height, so map a TVD curve.
- **TVD or TVDSS.** A contact is entered either on the log's TVD axis or as TVDSS. A TVDSS contact is converted with the kelly bushing elevation (`FWL (TVD) = FWL (TVDSS) + KB`). The KB must be typed in; the LAS header values are shown only as a hint and are never filled in automatically. A TVDSS contact with no KB is not used, and its samples count as having no contact. If the mapped depth curve looks like a subsea depth, the run warns, because the heights are then off by the KB.
- **Estimate FWL.** For a well with fitted curves, **Estimate FWL** scans candidate contacts (a 1 ft grid, 600 ft either side of the deepest sample with `SW` below 0.5, then refined) and picks the one whose `SW_SHF` best matches the log `SW` (a root-mean-square misfit over net reservoir samples, samples that differ by more than 0.35 counting half). The result is reported as not identifiable, and cannot be accepted, when the minimum is at the edge of the search, when the misfit hardly changes with the contact (a range below 10 % of its mean), when there are fewer than 10 usable samples or when there is no hydrocarbon-bearing sample. Nothing is changed until you accept it.

### Rock types

With rock typing on, a fit is made and applied per rock type. A Pc sample takes its rock type from the file's rock-type column, else from the rock-type definitions applied to its laboratory porosity and permeability, else it is `All`. On the logs a sample uses the fit of its `ROCK_TYPE`. A sample with no rock type, or with a rock type that has no fit, has no `SW_SHF`, unless the pooled fallback is on, which gives such a sample the `All` fit.

Rock-type numbers do not mean the same thing in two zones when the rock-type definitions are fitted per zone. In that case, and whenever rock typing is off, one `All` fit is used for every sample and a note says so.

### Circularity

- **Permeability.** The permeability used for J is chosen on the tab: automatic (the primary permeability, then `PERM_RT`, `PERM_WR`, `PERM_TIMUR`) or one of those columns. `PERM_WR` and `PERM_TIMUR` come from the irreducible water saturation and so from the resistivity Sw. `SW_SHF` computed with them is not independent of `SW`, and `SW_SHF_RESID` is then smaller than the real disagreement.
- **Log rock types.** The `ROCK_TYPE` of the logs is classified from one of those permeabilities, so a fit applied by log rock type inherits the same dependence (core-labelled samples override within the core distance).
- **Porosity.** J and `SW_SHF` use the porosity column chosen on the tab (default `PHIE`), and `SW` is the effective water saturation on the same basis. Pc data on a total-porosity basis should not be compared with the Waxman-Smits or Dual-Water total saturations.

### Outputs

| Column | Meaning |
|---|---|
| `SW_SHF` | Water saturation from the saturation-height model (fraction). 1 below the free water level; blank where it cannot be computed |
| `HAFWL` | Height above the free water level, ft (negative in the water leg) |
| `SW_SHF_RESID` | `SW − SW_SHF`: positive where the resistivity Sw is higher than the capillary model |
| `SW_PAY` | The saturation actually used for pay and HCPV: `SW_SHF` where it exists, else `SW`. Only present when SHF Sw is used for pay |

Permeability is floored at 0.001 mD and porosity at 0.01 before J is computed. Every sample lands in exactly one of these classes, and the counts are listed as notes: no contact, no TVD, no usable permeability or porosity, no rock type, no fit for its rock type (or pooled), water leg, modelled.

The summary gains an **SHF** block: the basis of the fits, the TVD, permeability and porosity sources, the contact and densities used for each zone, the counts, and the misfit of `SW` against `SW_SHF` for the well, each zone and each rock type: number of samples, bias (mean `SW − SW_SHF`), RMSE, MAE and R². These are taken over net reservoir samples above the free water level, so they compare between zones and wells. They are written to the SHF sheet of the Excel export.

**Pay and HCPV.** By default `SW_SHF` is a cross-check and pay, N/G, average Sw and HCPV use `SW`. With **Use SHF Sw for pay and HCPV** (core Pc fits only), the pay flags, net pay, N/G, average Sw in pay and HCPV use `SW_PAY`. Samples without a finite `SW_SHF` fall back to the resistivity Sw and are counted ("Pay Sw: saturation height, N samples from resistivity"). A water-leg sample has `SW_SHF` = 1. Irreducible water saturation and permeability are not recomputed from `SW_SHF`. Thickness and weights follow the rules of [Net Pay Analysis](#net-pay-analysis-v10).

**Monte Carlo.** In an [uncertainty](#uncertainty-monte-carlo-v190) run with SHF Sw used for pay, the samples that have a finite `SW_SHF` keep it in every realisation; the contact and the fit parameters are not varied. The other samples use the varied resistivity Sw, as `SW_PAY` does. The Uncertainty tab and sheet list "SHF Sw where used for pay" among the parameters that are not varied. With SHF Sw not used for pay, the Monte Carlo result is unchanged.

References:

- Leverett, M.C. (1941), *Capillary behavior in porous solids*, *Transactions of the AIME* 142.
- Brooks, R.H., Corey, A.T. (1964), *Hydraulic properties of porous media*, Colorado State University Hydrology Paper 3.
- Amyx, J.W., Bass, D.M., Whiting, R.L. (1960), *Petroleum Reservoir Engineering: Physical Properties*, McGraw-Hill.
- Purcell, W.R. (1949), *Capillary pressures: their measurement using mercury and the calculation of permeability therefrom*, *Transactions of the AIME* 186.

## LRLC screening and diagnostics *(v1.11.0)*

Low-resistivity low-contrast (LRLC) pay is hydrocarbon-bearing sand that a conventional Sw calls wet. The LRLC tools are optional and off by default; with them off, a run is exactly as in 1.10.0. With them on and none of the corrections below in use, they add diagnostic columns and leave `SW`, pay, HCPV, Swirr and permeability unchanged. The corrections (the invasion, laminated-sand and pyrite Rt steps, the Qv estimate, the sand basis and, from v1.13.0, variable m and n) are chosen per zone and change Sw, pay and HCPV only where you switch them on. They need a mapped resistivity curve. Citations marked *(to verify)* are listed in the reference registry (**Help → Scientific References…**) with details that are not yet confirmed against the original.

### Screening criteria and flag

Six criteria are tested at each sample, on the measured `RT` (never `RT_SW`):

| # | Criterion | Test | Evaluable when |
|---|---|---|---|
| 1 | Low Rt | `RT < screen_rt_max` | RT is valid |
| 2 | Hydrocarbon indicator | `GAS_FLAG = 1` (if used and present) or `RT / RS ≥ 1.0` (if used and the RS curve is mapped) | the gas flag exists, or RS and RT are valid |
| 3 | Porosity | `PHIE > phi_cutoff` | PHIE is valid |
| 4 | Shale volume | `VSH < vsh_cutoff` | VSH is valid |
| 5 | Contrast to shale | `RT / Rsh ≤ screen_contrast_max` | RT and the effective Rsh (temperature-corrected) are valid and positive |
| 6 | Sw high | `Sw ≥ sw_cutoff` | Sw is valid |

`phi_cutoff`, `vsh_cutoff` and `sw_cutoff` are the pay cutoffs of the zone (there are no separate LRLC cutoffs). `screen_rt_max` (default 5 ohm.m), `screen_contrast_max` (default 2) and `screen_min_score` (default 5) are **design defaults, not published constants; calibrate them per field**. The 1.0 limit on `RT / RS` is fixed: with fresh mud, deep resistivity at or above shallow indicates hydrocarbons and below it indicates water, but the indicator is weak with saline mud. Boyd et al. (1995), Worthington (2000) and Zemanek (1989) are the qualitative basis for the criteria, not for the numbers.

```
LRLC_SCORE = number of criteria met (0 to 6; a criterion that cannot be evaluated counts as not met)
LRLC_FLAG  = 1 when criteria 1, 3 and 6 are evaluable and met,
             and LRLC_SCORE ≥ min(screen_min_score, number of evaluable criteria)
```

Low resistivity in porous rock that the conventional Sw calls wet is the definition; criteria 2, 4 and 5 raise the confidence. The cap by the number of evaluable criteria lets the flag work when, for example, there is no hydrocarbon indicator. A sample with no valid Rt has score 0 and flag 0. A flagged sample is a candidate, not a pay zone: it needs a test, core or a recalibrated Sw model.

### Resistivity cutoff (`RT_CUT`)

For each sample, `RT_CUT` is the resistivity at which the **selected primary Sw model** returns the target Sw (`cut_sw_target`, by default the zone's Sw cutoff). A sample is pay by the Sw criterion when its resistivity is above `RT_CUT`. It is an overlay: it changes no Sw, flag or pay. With the Sw model's inputs of the sample (`PHIE`, `PHIT`, `Vsh`, effective Rw and Rsh, `a`, `m`, `n`, and for Waxman-Smits and Dual-Water their own terms), the closed forms are:

```
Archie        Rt_cut = a × Rw / (PHIE^m × Sw_t^n)
Simandoux     1 / Rt_cut = PHIE^m × Sw_t² / (a × Rw) + Vsh × Sw_t / Rsh      (n = 2)
Indonesian    1 / sqrt(Rt_cut) = [ Vsh^(1 − Vsh/2) / sqrt(Rsh) + PHIE^(m/2) / sqrt(a × Rw) ] × Sw_t^(n/2)
```

(`Sw_t` is the target. The Simandoux form is the model's own equation solved for Rt; for other values of n the model is solved numerically for Sw, and the bisection below applies.) Waxman-Smits and Dual-Water have no closed inverse, so the cutoff for every model is found the same way: a vectorised bisection of `log10 Rt` between 0.01 and 100 000 ohm.m (30 halvings, a width of 7 / 2³⁰ decades), using the app's own Sw function with the same per-sample inputs as the run, on a scratch calculator that leaves the run's results untouched. Sw is non-increasing in Rt for all five models, so the bisection is valid. The result reproduces the target within 10⁻⁶ when fed back through the model.

A sample has no cutoff (`RT_CUT` is empty) when its porosity is missing or at most 0.001, an input is missing, or the model cannot reach the target inside the bracket (very high porosity, for example, needs less than 0.01 ohm.m). Those without a root are counted and listed as notes; samples that are not eligible are not counted as failures. Liu et al. (2023) derived a field cutoff of about 4.2 ohm.m for one formation with a Simandoux-type model; that is a field result and not a default here.

**Zone cutoff.** For each zone one cutoff is also given, from the thickness-weighted means of PHIE, PHIT, Vsh, Rw, Rsh and the other inputs over the pay samples, or the net reservoir samples when there is no pay, or the gross sand samples when there is no net reservoir; with none of them, the zone has no value. The table in the Workbench names the basis.

References: Liu et al. (2023); Archie (1942); Simandoux (1963) *(to verify)*; Poupon and Leveaux (1971) *(to verify)*; Waxman and Smits (1968); Clavier, Coates and Dumanoir (1984).

### Bulk volume water and the water-free flag

```
BVW = PHIE × SW                                   (v/v)
WATER_FREE_FLAG = 1  when NET_RES_FLAG = 1 and SW ≤ SWIRR + movable_tol
```

`SW` is the effective primary Sw, so for Waxman-Smits and Dual-Water `BVW` is on the same basis as HCPV. `SWIRR` is the column chosen in the Workbench (`SWIRR` by default, the result of the Swirr method in use; or `SWIRR_BUCKLES`, `SWIRR_CLEANZONE`, `SWIRR_STAT`). A chosen column that is missing in a segment falls back to `SWIRR`, with a warning. Hierarchical `SWIRR` is capped at `SW`, so `SW − SWIRR` is the movable water saturation. A sample with a high Sw whose Sw is close to Swirr is at irreducible water (typically fine-grained or micro-porous rock) and can produce water-free; the flag is a screen, not a test result. It is not evaluated, and counted, for net-reservoir samples without a Swirr; `movable_tol` defaults to 0.05.

In the **Buckles** plot, points of one rock type at irreducible water lie on a hyperbola of constant bulk volume water, `Sw = k / PHIE` with `k = BVW`. References: Buckles (1965); Morris and Biggs (1967) *(to verify)*; Crain's Petrophysical Handbook *(to verify)*.

### Pickett plot and the wet-point fit

Archie's equation in logarithms is a straight line:

```
log10 Rt = −m × log10 PHI + log10(a × Rw) − n × log10 Sw
```

so water-bearing samples (`Sw = 1`) fall on a line of slope `−m` and intercept `log10(a × Rw)` at `PHI = 1`, and lines of constant Sw are parallel to it, shifted by `−n × log10 Sw`. The plot uses the measured `RT` (not `RT_SW`) against `PHIE` (or `PHIT`); with formation temperature on, `RT` is divided by the Arps factor first, so the fitted Rw is at the Rw reference temperature, like the Rw of the Parameters window.

**Wet points.** The automatic proposal takes samples with `VSH ≤ vsh_max` (default 0.25) and `PHI ≥ phi_min` (0.05), cuts `log10 PHI` into `n_bins` (8) equal bins, skips bins with fewer than 5 candidates, and in each bin keeps the candidates at or below the `wet_quantile` (0.10) of `log10 Rt`. Boxes added or removed by hand are applied afterwards.

**Fit.** A Huber robust fit by iteratively reweighted least squares on `y = log10 Rt`, `x = log10 PHI` over the wet points: start from ordinary least squares; scale `s = max(1.4826 × MAD(r), 10⁻⁶)` of the residuals `r`; weights `w = min(1, 1.345 × s / |r|)`; repeat the weighted fit until the change is below 10⁻⁸ or after 50 iterations. The slope `b` gives `m = −b`; the intercept `c` gives `a×Rw = 10^c`, and `Rw = a×Rw / a` with the `a` of the zone (never fitted). Standard errors are `s_w² (XᵀWX)⁻¹` with `s_w² = Σ w r² / (N − 2)`. In **Rw only** mode `m` is kept at its current value and the intercept is the Huber location of `y + m × x`.

| Status | Meaning |
|---|---|
| `ok` | fitted, and m and Rw are inside their allowed ranges (m 1.3–3.0, Rw 0.005–10 ohm.m) |
| `too_few_points` | fewer than `min_points` (10) wet points |
| `narrow_porosity_range` | the wet points span less than 0.2 decades of porosity (not tested in Rw only mode) |
| `m_outside_range`, `rw_outside_range` | fitted but outside the range: shown, and not applicable |
| `no_data` | no usable sample |

Limits: the wet points must really be water-bearing (a hydrocarbon-bearing envelope overstates Rw); clay conduction biases m low; Rw is assumed constant over the interval, after the temperature normalisation. References: Pickett (1966); Archie (1942).

### The Rt array path and the correction chain

Every Sw model (Archie, Indonesian, Simandoux, Waxman-Smits, Dual-Water) can read its resistivity from an array that holds one value per sample, instead of the `RT` column, in the same way Rw, Rsh and the Waxman-Smits `B` can already be per sample. The array is used only when a correction step has run in that part of the well. With none, the models are called exactly as in 1.10.0.

A correction step is a function that takes the resistivity of the previous step (the measured `RT` for the first) and returns a corrected one for a zone. Steps run in a fixed order, independent of how they are listed, once per zone, and the result of the last step is what the Sw models read:

```
RT (measured, never modified) → step 1 → step 2 → …  ⇒  RT_SW (what every Sw model reads)
```

`RT_SW` is written to the results only when at least one step is active somewhere in the well; where no step runs, it equals `RT`. Three steps ship: **radial invasion** (`RT_INV`), **laminated sand** (`RT_SAND`) and **pyrite** (`RT_PYR`), run in that order, so the laminated-sand step reads `RT_INV` where the invasion step is on and the measured `RT` otherwise. Each writes its own column, so the output of every step stays visible. With no step selected, Sw reads the measured Rt. A step's output must be finite and positive: anything else becomes empty (NaN), is counted and reported, and the Sw of that sample is empty, so it has no pay and no HCPV. The alternative setting, **Use the previous Rt**, substitutes the input of the step instead and counts that too. Nothing is clamped silently. **Auto Rw and auto Rsh always read the measured Rt**, so a correction never feeds back into its own inputs. The run records which steps ran in each zone, and the exports state it (see [Visualization and Export](visualization-and-export.md#lrlc-in-the-exports-v1110)).

### Thomas-Stieber decomposition

Thomas-Stieber is a two end-member model of a sand with shale laminae. The sand laminae are clean sand of porosity `phi_max` that holds dispersed clay in its pores, and the shale laminae have the porosity `phi_sh`. With `Vlam` the laminar shale volume, `Vd_s` the dispersed clay as a fraction of the sand laminae and `Vdisp` the dispersed volume of the rock:

```
phi_sand = phi_max − Vd_s × (1 − phi_sh)
PHIT     = (1 − Vlam) × phi_sand + Vlam × phi_sh
Vsh      = Vlam + (1 − Vlam) × Vd_s

Vlam  = [ PHIT − phi_max + Vsh × (1 − phi_sh) ] / (1 − phi_max)
Vdisp = Vsh − Vlam
```

`Vsh` is the shale volume named in the Thomas-Stieber settings (`VSH` by default) and `PHIT` is the total porosity of the run. The decomposition runs per zone with the end-points that are applied to that zone; it needs a GR curve (with the default constant shale volume it is skipped, with a note) and the two end-points. A zone without applied end-points, or with end-points that fail the checks below, gets empty `VLAM`, `VDISP`, `PHI_SAND` and `TS_CLASS` 0.

**Clamping.** `Vlam` is limited to the triangle of possible points: not below `max(0, (Vsh − phi_max) / (1 − phi_max))` (the clay-supported edge) and not above `Vsh` (all shale laminar). A sample whose unclamped `Vlam` lies more than `class_tol` (default 0.03) beyond an edge is counted as outside the triangle and takes the edge value.

**Classes (`TS_CLASS`).** Within the window `class_vsh_min` ≤ Vsh ≤ `class_vsh_max` (0.05 to 0.95), with the laminar share `f = Vlam / Vsh` and `class_share` = 0.20:

| Code | Class | Rule |
|---|---|---|
| 0 | Not classified | input missing or outside 0 to 1, no applied end-points, or Vsh outside the window |
| 1 | Laminar | `f ≥ 1 − class_share` |
| 2 | Dispersed | `f ≤ class_share`, or a point below the dispersed line (Vsh at or below `phi_max` and unclamped `Vlam` below −`class_tol`) |
| 3 | Mixed | `class_share < f < 1 − class_share` |
| 4 | Structural | unclamped `Vlam` above `Vsh` by more than `class_tol` (shale in the framework) |
| 5 | Clay-supported | beyond the clay-supported edge by more than `class_tol` |

The classes are a screening aid, not a lithofacies log.

**End-point proposals.** For each zone the Workbench proposes `phi_max` as the 90th percentile (`clean_pct`) of `PHIT` over the clean samples (`Vsh < clean_vsh`, default 0.05) and `phi_sh` as the median `PHIT` over the shale samples (`Vsh > shale_vsh`, default 0.80). A zone needs at least `clean_min_n` (30) clean samples that add up to at least 15 ft and `shale_min_n` (10) shale samples; a zone short of either takes the proposal of the whole well, and says so (source *well*). A proposal is usable only when `phi_max` is 0.10 to 0.45, `phi_sh` is 0 to 0.40 and `phi_sh` is at least 0.02 below `phi_max`. **A proposal is never applied by itself**: you apply the values in the Remediation panel.

The result depends on both end-points and on a `PHIT` free of shale and gas effects; gas lowers the density-neutron porosity contrast, and the run counts the gas samples that are classified. Reference: Thomas and Stieber (1975).

### Laminated-sand resistivity (Hagiwara)

When sand and shale laminae are thinner than the tool and current runs along the bedding, the two conduct in parallel. With `Rsh` the effective shale resistivity of the zone (temperature-corrected, as everywhere else):

```
1/Rt = (1 − Vlam) / Rsand + Vlam / Rsh
s    = Vlam × Rt / Rsh
RT_SAND = Rsand = (1 − Vlam) × Rt / (1 − s)
```

`s` is the share of the measured conductance that the shale laminae carry. A relative error in Rt is amplified in `RT_SAND` by `1 / (1 − s)`. `Vlam` is the Thomas-Stieber `VLAM` (**Thomas-Stieber split**) or a constant (`vlam_const`, 0 to 0.9). Settings and handling of each sample:

| Case | Condition | Result |
|---|---|---|
| Not applicable | `Vsh ≥ hag_vsh_max` (default 0.80) | `RT_SAND` is empty, counted |
| No input | Rt or Rsh missing or not positive, `Vlam` missing or negative | empty, counted |
| Identity | `Vlam = 0` | `RT_SAND = Rt` |
| Invalid | `s ≥ s_invalid` (default 0.95), or `Vlam ≥ 1` | empty, counted |
| Sensitive | `s ≥ s_warn` (default 0.80), error amplified five times or more | value kept, counted and warned |

Samples whose corrected Rt is still below Rsh are counted too. A step that gives an empty value follows the setting **When a step cannot produce a value** (see the chain above). Without a `Vlam` (Thomas-Stieber off or without end-points in the zone) the step returns nothing for the zone and says so. The correction is meant for the raw deep resistivity: a curve that is already shoulder-bed corrected or deconvolved is not raw Rt (see the guard below). References: Poupon, Loy and Tixier (1954); Hagiwara (1988, US patent 4,739,255); Hagiwara (1995, 1997).

### Pyrite volume and the pyrite Rt correction

**Volume from RHOB and PEF.** Pyrite adds density (about 4.99 g/cc) and photoelectric absorption (PEF about 17 b/e, a volumetric factor `U = PEF × RHOB`) that a clean sand does not. With the unknowns pore volume `phi`, matrix volume `Vma` and pyrite volume `Vpy` and the known `Vsh`, three equations are solved per zone:

```
1                 = phi + Vma + Vpy + Vsh
RHOB              = phi × rho_f + Vma × rho_ma + Vpy × rho_py + Vsh × rho_sh
PEF × RHOB        = phi × U_f  + Vma × U_ma  + Vpy × U_py  + Vsh × U_sh
```

`U_f` is the fluid value (`u_fluid`, 0.4), `U_ma = PEF_ma × rho_ma`, `U_py = PEF_py × rho_py`, `U_sh = PEF_sh × rho_sh`. Pyrite and matrix defaults are 4.99 g/cc with PEF 16.97, and 2.65 g/cc (the zone matrix density) with PEF 1.81; the shale density is the zone shale density with PEF 3.4. The fluid density is the run's fluid density. If the 3 × 3 end-point matrix has a condition number above 10⁴ the zone gets no `VPYR` and a warning. A sample needs RHOB, PEF (0 to `pef_max`, default 25) and Vsh. A negative `Vpy` below −`neg_tol` (0.01) is left empty, a negative one within the tolerance is set to 0, and a `Vpy` above `vpyr_max` (0.25) is left empty; each is counted. The other method, **Constant VPYR**, uses one value per zone (`pyr_vpyr`) and needs no PEF.

Limits: barite mud, siderite and other heavy minerals raise PEF without pyrite, and a PEF measured on a pad is a pad-contact measurement. Where pyrite is present the density porosity is biased low; the run notes this for the net reservoir.

**Rt correction.** Only the connected fraction `f` of the pyrite conducts, with the resistivity `Rpy` (default 0.01 ohm.m). The pyrite conductance is removed from the measured conductance as a parallel path:

```
RT_PYR = 1 / ( 1/Rt − f × Vpy / Rpy )
t = f × Vpy / Rpy        s = t × Rt        RT_PYR = Rt / (1 − s)
```

`f = 0` leaves Rt unchanged (the step is flagged as doing nothing), and so does `Vpy = 0`. A sample with `s ≥ s_invalid` (0.95) is empty and counted; `s ≥ s_warn` (0.80) is kept and counted as sensitive, because the correction then removes most of the measured conductance. `f` and `Rpy` are calibration values for the field, **not defaults to trust**. The step reads the output of the step before it, so with both steps on, `RT_PYR` is computed from `RT_SAND`. Reference: Clavier, Heim and Scala (1976).

### Qv from Vsh and the shale CEC

The Waxman-Smits model needs `Qv`, the cation exchange per pore volume. The estimate takes the exchange capacity of the rock as proportional to the shale volume:

```
CEC_rock = Vsh × cec_shale                                    (meq/100 g)
Qv       = CEC_rock / 100 × rho_g × (1 − PHIT) / PHIT          (meq/mL)
```

`cec_shale` is the capacity of the shale in meq/100 g (default 25) and `rho_g` the grain density (the zone matrix density unless set). A sample with `PHIT` below `phi_min` (0.03) or `Qv` above `qv_max` (3 meq/mL) is left empty and counted. The result is the array `QV_EST`. **Only Waxman-Smits reads it**; where `QV_EST` is empty the model uses the constant Qv of the Waxman-Smits parameters, and the run says how many samples fell back. A Qv estimate with Waxman-Smits not among the selected Sw methods is reported as not used.

**Calibration with core CEC.** When the well has core CEC (see [Core Data](data-formats.md#core-data)), each core sample is paired with the nearest log sample within `pair_tol_ft` (0.5 ft) and `cec_shale` is the least-squares slope through the origin of the pairs with `Vsh ≥ 0.05`:

```
cec_shale = Σ(CEC × Vsh) / Σ(Vsh²)
```

with R² against the mean of the core values. It needs at least `min_pairs` (5) pairs. The Remediation panel shows the proposal and writes it only when you press **Use core CEC** and apply. Vsh from the gamma ray is a proxy for clay capacity; calibrate before relying on the values. References: Waxman and Smits (1968); Hill, Shirley and Klein (1979); Juhasz (1981).

### Sand basis for Sw

After the laminated-sand correction, `RT_SAND` is the resistivity of the sand laminae, so the Sw model should also read the porosity and shale volume of the sand laminae. With the **sand basis** a zone's Sw models read, for samples with a finite Thomas-Stieber result and `Vlam < 1`:

```
Vd_s = Vdisp / (1 − Vlam)
PHIT → PHI_SAND         Vsh → Vd_s         PHIE → phi_max − Vd_s
```

The basis is chosen per zone: **Automatic** uses the sand basis where the laminated step is on and the bulk basis elsewhere; **Sand laminae** and **Bulk** force it. A sample in a sand-basis zone with no Thomas-Stieber result keeps the bulk values and is counted. The sand basis changes what the Sw models read, not the stored `PHIE`, `PHIT` or `VSH` columns, and pay and HCPV keep using the bulk `PHIE` and `VSH` cutoffs.

**Double counting.** With the **bulk** basis after the laminated-sand correction, the Sw model reads the bulk porosity (lower than the sand porosity) and, for Indonesian and Simandoux, the bulk `Vsh`, which already contains the laminar shale that the correction removed from Rt. Laminar shale is then counted twice and Sw comes out too high. The run warns for Indonesian and Simandoux in that case, and in every case warns that bulk porosity is read. Use the sand basis, or Archie or Waxman-Smits, after the laminated-sand correction.

### Shoulder-bed guard

Thomas-Stieber classifies each zone as **laminated** when, over the samples with `Vsh ≥ vsh_min` (default 0.10), the thickness-weighted laminar share of the shale volume `Σ(Vlam × dz) / Σ(Vsh × dz)` is at least `vlam_share` (0.50) and the thickness-weighted mean `Vlam` is at least `min_vlam` (0.05). A zone with no Thomas-Stieber result is not classified. The guard acts on laminated zones with these rules:

1. **Vertical-resolution steps** (deconvolution, a step kind that does not ship in this version) are dropped from a laminated zone when the guard is on, and only warned about when it is off. Use the laminated-sand correction instead.
2. **Marked curve.** When the mapped RT is declared shoulder-bed corrected (the check box in the Remediation panel) and the laminated-sand step is on in a laminated zone, everything is computed, a warning is raised and the zone is marked. The guard never makes a sample invalid. Map the raw deep RT instead.
3. **Hint.** With the guard on, a laminated zone without the laminated-sand step gets a hint to consider it.
4. A zone that is not classified is not blocked, and a warning says why.

A shoulder-bed-corrected or deconvolved curve is a result of a model that assumes thick beds; applying a laminated-sand correction on top of it is not valid.

### Diagnosis

The diagnosis scores five causes of low resistivity per zone from the net reservoir samples (`NET_RES_FLAG = 1`), with statistics weighted by the depth increment. Each cause has criteria; a criterion whose input is missing is not evaluated and not counted. The score is the share of evaluable criteria that are met.

| Cause | Criteria (all against the thresholds shown) |
|---|---|
| Thin beds / laminations | laminar share of Vsh ≥ `vlam_share` (0.50); mean `Vlam` ≥ `min_vlam` (0.05); share of laminar and mixed classes among the classified samples ≥ 0.5 |
| Microporosity / fine grain | median Sw ≥ the zone's Sw cutoff; share of water-free samples ≥ 0.5; variation (CV) of `BVW` ≤ `bvw_cv_max` (0.20) |
| Saline water / low contrast | median effective Rw ≤ `rw_low` (0.06 ohm.m); median `Rt / Ro` ≤ `contrast_low` (3), with `Ro = a × Rw / PHIT^m`; median Rt ≤ the screening Rt maximum |
| Conductive minerals (pyrite) | median `VPYR` ≥ `vpyr_flag` (0.01); median PEF ≥ `pef_flag` (4 b/e) |
| Clay conductivity / high CEC | median Qv (`QV_EST`, or the constant Qv) ≥ `qv_high` (0.30 meq/mL); mean Vsh ≥ `vsh_clay` (0.15); median Sw drop of the primary model against Archie ≥ `dsw_clay` (0.10) |

A cause is **probable** at a score of 0.67 or more with at least two evaluable criteria (the pyrite cause may be probable on one), and **possible** from 0.34. The **primary cause** is the probable cause with the highest score; ties go in the order of the table. A zone with fewer than `min_n` (10) net reservoir samples is not diagnosed. A diagnosis is a ranked hypothesis from the logs: it is not a test result, and the thresholds are design defaults to calibrate per field.

**Remedies.** Each cause points to a set of Remediation settings, which are only prepared in the Workbench and never applied by themselves:

| Cause | Remedy |
|---|---|
| Thin beds / laminations | laminated-sand Rt step, Vlam end-points, sand basis; Waxman-Smits or Archie (avoid Indonesian and Simandoux with the bulk basis) |
| Microporosity / fine grain | no Rt step; Buckles and movable-water check, saturation-height validation, the water-free flag; keep the Sw model |
| Saline water / low contrast | no Rt step; check Rw (auto Rwa, Pickett plot) and the temperature correction; Archie or Simandoux with the corrected Rw |
| Conductive minerals (pyrite) | pyrite step; calibrate the connected fraction and Rpy |
| Clay conductivity / high CEC | Qv estimate from Vsh and the shale CEC; Waxman-Smits or Dual-Water |

### Baseline Sw and pay for the validation

When a correction is active in a well (an Rt step, a Qv estimate or the sand basis), the run also computes the Sw the well gives **without any LRLC correction**: the measured `RT`, the constant Qv of the Waxman-Smits parameters and the bulk basis, with the same primary model, Rw, Rsh and cutoffs. This is `SW_BASE`, and the net pay flag from it is `NET_PAY_BASE_FLAG`. In a zone with no active correction `SW_BASE` equals `SW`. If saturation-height Sw is used for pay, the samples that hold it keep it in the baseline too, so the comparison changes pay only where the resistivity Sw is used. The validation compares the net pay, average Sw in pay and HCPV of the two (the **before** and **after** columns) and, when saturation-height results exist, the bias and RMSE of the resistivity Sw against the saturation-height Sw for both. The baseline is written only for wells with an active correction.

### Monte Carlo with the corrections

The Monte Carlo run uses the Rt correction and the sand basis of the analysis. `Rsh` is varied as before, and because it also enters the laminated-sand correction, a changed `Rsh` recomputes `RT_SAND` and so `Sw`; the uncertainty page and the export say so with the note **Rsh also varies the laminated-sand Rt**. The following are held at the values of the analysis and are added to the **Not varied** list when they are in use: the Thomas-Stieber `Vlam` (with the sand basis values), the pyrite volume and correction, and the estimated Qv. The end-points, `f`, `Rpy` and `cec_shale` are not among the varied parameters. With variable m and n, `m` and `n` move the whole curve by one additive offset, and the coefficients are held (see [Variable m and n](#variable-m-and-n-v1130)). The invasion-corrected Rt is also held, and the run adds *invasion-corrected Rt (frozen)* to the **Not varied** list.

### Results added

| Column | Unit | Meaning | Added when |
|---|---|---|---|
| `LRLC_SCORE` | count | screening criteria met, 0 to 6 | LRLC on and RT mapped |
| `LRLC_FLAG` | 0/1 | screening candidate | same |
| `BVW` | v/v | bulk volume water `PHIE × SW` | same |
| `WATER_FREE_FLAG` | 0/1 | net reservoir with `SW ≤ SWIRR + movable_tol` | same |
| `RT_CUT` | ohm.m | resistivity at the target Sw for the primary model | the Rt cutoff is on |
| `RT_SW` | ohm.m | resistivity the Sw models read | a correction step is active |
| `VLAM` | v/v | laminar shale volume (Thomas-Stieber) | Thomas-Stieber on, GR available, end-points applied |
| `VDISP` | v/v | dispersed shale volume, `Vsh − Vlam` | same |
| `PHI_SAND` | v/v | porosity of the sand laminae | same |
| `TS_CLASS` | code | 0 not classified, 1 laminar, 2 dispersed, 3 mixed, 4 structural, 5 clay-supported | same |
| `VPYR` | v/v | pyrite volume (from RHOB and PEF, or the constant) | the VPYR column is switched on, or the pyrite step uses RHOB and PEF |
| `QV_EST` | meq/mL | Qv estimated from Vsh and the shale CEC | a zone uses the Qv estimate |
| `RT_SAND` | ohm.m | resistivity of the sand laminae | the laminated-sand step is active |
| `RT_PYR` | ohm.m | resistivity after the pyrite correction | the pyrite step is active |
| `RT_INV` | ohm.m | invasion-corrected resistivity | the invasion step is active |
| `RXO_INV` | ohm.m | flushed-zone resistivity of the invasion step | same |
| `DI_INV` | in | invasion diameter of the invasion step | same |
| `M_VAR` | unitless | cementation exponent per sample | a zone is in curve mode for m and n |
| `N_VAR` | unitless | saturation exponent per sample | same |
| `SW_BASE` | v/v | Sw without any LRLC correction | a correction is active somewhere in the well |
| `NET_PAY_BASE_FLAG` | 0/1 | net pay flag computed from `SW_BASE` | same |

The summary gains an **LRLC** block with the resolved settings per zone, the candidate table, the cutoff table, the movable-water table, the correction steps that ran, the Thomas-Stieber end-points and class counts, the shoulder-bed guard decisions, the diagnosis per zone and the before-and-after validation. The Zones table of the summary and of the Excel export adds the pay before the corrections when a baseline exists.

## Variable m and n *(v1.13.0)*

A zone normally has one cementation exponent `m` and one saturation exponent `n`. Clay-bearing, fine-grained sands, the usual host of low-resistivity pay, often do not follow one pair. **Variable m/n** lets the exponents of a zone depend on porosity and shale volume, one value per sample, and gives those values to every Sw model. It is optional and set per zone. With every zone in the default **Scalar** mode, a run gives the results of v1.12.0.

### Formulas

With `φ` the porosity as a fraction (PHIE or PHIT, the **Porosity** setting; PHIE by default) and `Vsh` the shale volume:

```
m = c0 + c1 × φ + c2 × Vsh + c3 / φ          (formula)
m = 1.87 + 0.019 / φ                          (Shell)
n = d0 + d1 × Vsh                             (n from Vsh)   or   n = the n of the zone
```

The coefficients are `m_coef = [c0, c1, c2, c3]` and `n_coef = [d0, d1]`. Their defaults are `[2.15, 0, 0, 0]` and `[2.0, 0]`, so switching a zone to **Curve** with the defaults gives the constant 2.15 and 2.0 and changes nothing until you enter or apply coefficients. The default `c0` does not follow the `m` of the zone; **Set c0 to the zone m** copies it. Allowed ranges: `c0` 0.5 to 5, `c1` −10 to 10, `c2` −3 to 3, `c3` −0.5 to 0.5, `d0` 1 to 4, `d1` −3 to 3.

The porosity-and-clay form `c0 + c1 × φ + c2 × Vsh` is attributed to Guo et al. (2023) *(to verify)*. No published coefficients are shipped: you enter them or take them from the wet-point fit below. The `c3 / φ` term is there so that the Shell form can be written in the same formula.

**Shell formula.** `m = 1.87 + 0.019 / φ` gives m = 2.25 at φ = 0.05, 2.06 at 0.10 and 1.965 at 0.20: m rises as porosity falls. It is meant for low-porosity carbonates and is evaluated only in zones whose lithology preset is **Carbonate**. In any other zone it is refused, the zone keeps its constant `m`, and the run warns, unless you tick **Use Shell in this zone although the preset is not Carbonate**; the formula is then used and the run notes that you confirmed it. **Caveat.** Borai (1987) discusses this formula and its limits, and reports that in the tight, low-porosity carbonates he studied offshore Abu Dhabi `m` *decreases* as porosity decreases, the opposite trend. Check the Shell formula against core before relying on it.

Worked check: `m_coef = [1.9, 0.5, 0.3, 0]`, φ = 0.20 and Vsh = 0.30 give m = 1.9 + 0.10 + 0.09 = 2.09.

### Clipping and fallback

| Sample | Result |
|---|---|
| φ or Vsh missing, or φ below 0.02 | the constant `m` and `n` of the zone are used, and the samples are counted |
| the curve gives a value outside the clip range | the value is clipped to the range and the samples are counted, with the unclipped range |
| Shell in a zone that is not Carbonate, not confirmed | the constant `m` is used for `m`; `n` follows its own model |
| the stored coefficients are malformed, or a model is unknown | the zone is treated as Scalar and a warning is given |

The clip range is 1.0 to 4.0 for both exponents (the project settings `clip_m` and `clip_n`, the same as the Monte Carlo limits). The clipped value is stored; the count is reported per zone, as information below 5 % of the samples and as a warning above. Samples that fall back to the constant values are reported the same way. `M_VAR` and `N_VAR` are therefore always finite where Sw is computed, and a zone in curve mode never gives an empty Sw because of the curve alone.

### Where the curves are read

`M_VAR` and `N_VAR` are evaluated once per run for each sample, from the porosity and shale volume **the Sw model of that sample reads**: in a zone that uses the sand basis (see [Sand basis for Sw](#sand-basis-for-sw)) these are the sand-lamina porosity and shale volume, not the bulk ones. They are then read by every Sw model and by `RT_CUT`, so the cutoff is the resistivity at which the primary model, with the same exponents, returns the target Sw. Two things keep the constant `m` and `n` of the zone:

- **Automatic Rw and Rsh.** The estimators read the measured Rt and the constant exponents. A fit of `m` from wet points needs an Rw, so letting the curve feed the Rw estimate would make Rw depend on the curve it is used to fit. With an automatic Rw, a fitted `m` is therefore conditional on an Rw estimated with the constant `m`.
- **The baseline.** `SW_BASE` is the Sw with no LRLC correction, so it uses the constant exponents, and the comparison on the Validation panel includes the effect of variable m and n.

`M_VAR` and `N_VAR` are written for every segment of a well when at least one of its zones is in curve mode (a zone in Scalar mode carries its constant values), and not at all otherwise.

### Wet-point fit

At a water-bearing sample Archie gives `Rt = a × Rw / φ^m`, so `ln(a × Rw / Rt) = m × ln φ`. With `m = c0 + c1 × φ + c2 × Vsh` this is linear in the coefficients:

`e_i = ln(a × Rw_i / Rt_i) − (c0 + c1 × φ_i + c2 × Vsh_i) × ln φ_i`

The fit minimises `e_i` with a robust (soft L1) loss with scale 0.1, about 10 % in Rt, so a few non-wet points do not move it much. The residual is taken in `ln Rt`; the observed `m_i = ln(a × Rw_i / Rt_i) / ln φ_i` is used only for the plots, because it is unstable as φ approaches 1. `c3` is fixed at 0. The inputs are:

- the **wet points** of the Pickett selection (the automatic proposal plus the boxes you added or removed on the Pickett tab; the boxes are not saved, so after a restart the fit starts from the automatic proposal);
- `Rt` is `RT_SW` of the last run (the resistivity the Sw models read), or `RT` when there is none, so the fit moves when the Rt chain changes;
- `Rw` per sample at formation temperature, and the `a` of the zone;
- `φ` per the **Porosity** setting and `Vsh` from the last run; in a zone that reads the sand basis, the sand-lamina values, rebuilt from the result columns.

Points outside the porosity window 0.03 to 0.60, with missing values, or with `Rt` not positive are left out and counted. Which coefficients are free depends on the data:

| Free coefficients | Needs |
|---|---|
| `c0` only | at least 15 points; the result equals a constant-m Pickett fit |
| `c0`, `c1` | porosity spread (P95 − P05) of at least 0.05, and 30 points |
| `c0`, `c2` | Vsh spread of at least 0.10, and 30 points |
| `c0`, `c1`, `c2` | both spreads, and 45 points |

That is 15 points for each free coefficient. A coefficient whose normal equation is singular is fixed at 0 and the status says so. The coefficients are kept inside their allowed ranges. The standard errors are approximate (from the final robust weights). The result reports the points used and left out, the free coefficients, the RMSE in `ln Rt`, the RMSE, bias and R² of the fitted against the observed `m` (points with φ up to 0.5), the porosity, Vsh and `m` ranges, and a status: **ok**, **insufficient points**, **phi range too small, c1 fixed**, **vsh range too small, c2 fixed** or **implausible m**. If more than 5 % of the wet points get a fitted `m` outside the clip range, the status is **implausible m** and the fit cannot be applied. The fit is a proposal: nothing is stored until you press **Apply fit**, which writes Curve mode, the formula model, the coefficients and the porosity source to the scope you chose, and never changes the `n` model.

### Monte Carlo

In a run with `m` and `n` curves, the offset drawn for `m` (or `n`) is added to every sample of the curve and is bounded sample by sample to the Monte Carlo limits of 1.0 to 4.0. The offset is additive; a relative distribution for `m` or `n` is refused with *m and n are curves in this well: use additive offsets*. The coefficients, the clip range and the curve shape are not varied, and the run lists *m/n curve shape (coefficients; only a whole-curve offset is varied)* among the inputs not varied. At zero offset the run reproduces the deterministic result.

### Limits

- The formula is a statistical form, not a physical law. Check the fitted curve against core measurements of the formation factor, where there are any, and against the Pickett plot.
- The saturation exponent has no fit: wet points do not constrain `n`.
- Below 2 % porosity, or where porosity or Vsh is missing, the constant values apply.
- Wet points that are not water-bearing bias the fit toward high `m`; clay conduction biases `m` low.
- A fit on bulk wet points is applied to the sand-lamina values in a zone that reads the sand basis; check that the two are consistent.
- Core-derived `m` and `n` are not read; there is no import for them.

References: Archie (1942); Pickett (1966); Borai (1987); Guo et al. (2023) *(to verify)*.

## Radial invasion correction *(v1.13.0)*

Drilling mud filtrate pushes the formation fluid away from the hole. A deep resistivity curve then reads a mixture of the flushed zone (`Rxo`) and the undisturbed formation (`Rt`). With a medium and a shallow resistivity curve, and optionally a micro-resistivity curve, the **invasion** step fits a one-step radial profile to each sample and returns `Rt`, `Rxo` and the invasion diameter. It is an Rt correction step like the laminated-sand and pyrite steps: its output is `RT_INV`, and where the step is on the Sw models read `RT_INV`. It is optional and off by default; with it off, a run is unchanged.

### Model

Work in conductivity. The unknowns of a sample are `Ct = 1/Rt`, `Cxo = 1/Rxo` and the invasion diameter `di` (in). A tool `i` has a 50 percent investigation diameter `r_i` (in) and a shape exponent `p`. Its **pseudo-geometric factor** is the share of its signal that comes from inside the invaded cylinder:

```
J_i(di) = 1 / (1 + (r_i / di)^p)
Ca_i    = J_i × Cxo + (1 − J_i) × Ct          Ra_i = 1 / Ca_i
```

`J_i` is 0.5 when `di = r_i`, tends to 1 when `di` is much larger than `r_i` and to 0 when it is much smaller. The three observations are the deep curve (the Rt the step receives), `RM` (medium) and `RS` (shallow), read from the auxiliary curve roles (see [Auxiliary curve roles](data-formats.md#auxiliary-curve-roles-v1110)). Three curves fix three unknowns exactly. If `RXO` is mapped and **Use RXO as the flushed-zone resistivity** is selected, `Rxo` is taken from the micro-resistivity curve and the unknowns are `Rt` and `di`, so two curves are enough: the deep curve and `RM` or `RS`. With the deep curve, `RM`, `RS` and `RXO` together the fit has one more observation than unknowns, which allows the fit-quality check below. If the minimum set is not mapped, the step is skipped in that zone and the run says so.

The tool constants are generic placeholders, not specifications of any tool. **Confirm the diameters and the exponent against the chart book of the tool that was run.** The presets are:

| Preset | deep `r` (in) | medium `r` (in) | shallow `r` (in) | `p` |
|---|---|---|---|---|
| Generic induction | 80 | 45 | 20 | 2.5 |
| Generic laterolog | 70 | 35 | 25 | 2.5 |
| Custom radii | your values | your values | your values | your value |

Worked check (Generic induction, `di` = 40 in): `J` = 0.15022, 0.42691, 0.84978 for the deep, medium and shallow curve. With `Rt` = 20 and `Rxo` = 2 ohm.m the apparent resistivities are 8.5034, 4.1303 and 2.3127 ohm.m, and fitting those three values returns `Rt` = 20, `Rxo` = 2 and `di` = 40.

### Fit

The fit is done for all samples at once; there is no loop over samples. For a fixed `di` the model is linear in `(Ct, Cxo)` (or in `Ct` alone with `Rxo` fixed), so:

1. **Start (variable projection).** A grid of 48 diameters, spaced logarithmically between the smallest and the largest diameter, is tried. For each sample and each diameter the weighted linear least squares for `Ct` and `Cxo` is solved in closed form, with each observation weighted by its relative error in conductivity. Combinations with a non-positive conductivity are rejected, and the diameter with the smallest misfit gives the start.
2. **Refinement.** A Levenberg-Marquardt iteration in log space, with `x = (ln Rt, ln Rxo, ln di)` and residuals `f_i = ln Ra_i(x) − ln Ra_i(measured)`, so every decade weighs the same. With `q_i = (r_i/di)^p`, the derivatives are
   `∂f_i/∂ln Rt = (1 − J_i) × Ct / Ca_i`,
   `∂f_i/∂ln Rxo = J_i × Cxo / Ca_i`,
   `∂f_i/∂ln di = −(Cxo − Ct) × p × q_i × J_i² / Ca_i`.
   Each iteration solves the damped normal equations of every sample, keeps the parameters inside their bounds (`Rt` 0.05 to 20 000 ohm.m, `di` between the smallest and largest diameter, and `Rxo` not below `Rmf` at formation temperature when `Rmf` is set), and stops when no parameter moves by more than 1e-6, or after 40 iterations.

### Classification of each sample

| Class | Condition | `RT_INV` | Valid |
|---|---|---|---|
| Non-unique | the largest apparent conductivity is less than the **minimum curve contrast** (default 1.15) times the smallest, counting a fixed `Rxo` | the input Rt, unchanged | yes |
| Failed | the iteration did not converge | empty | no |
| Diameter at upper bound | `di` ≥ 0.99 × the largest diameter: every tool reads mostly flushed zone and `Rt` is an extrapolation | empty | no |
| Diameter at lower bound | `di` ≤ 1.01 × the smallest diameter: little invasion, `Rt` is well constrained | fitted | yes |
| Poor fit | only when there is a redundant observation: the rms of the log residual is above the **maximum rms** (default 0.15) | empty | no |
| Missing input | the deep curve or a needed curve is empty or not positive | empty | no |
| Fitted | otherwise | fitted | yes |

A non-unique sample is flat: the curves agree, so any correction is smaller than the tool tolerance. `DI_INV` is empty where the sample is non-unique or invalid. `RXO_INV` is the fitted `Rxo`, or the micro-resistivity reading when it is used as fixed; at a non-unique sample without a micro-resistivity curve it is empty. A sample with no valid output follows the setting **When a step cannot produce a value** (empty, or the previous Rt), as for the other Rt steps. The run counts every class per zone and gives a message for each. Non-unique samples give a warning when they are more than 25 % of the valid samples; a diameter at the upper bound gives a warning, at the lower bound information.

### Rmf at formation temperature

`Rmf`, with the temperature at which it was measured, is optional. It is used as a **bound and a check**, never as an input of the fit. It is brought to the temperature of each sample with Arps' equation (see [Formation temperature](#formation-temperature)):

`Rmf(T) = Rmf × (T_ref + 6.77) / (T + 6.77)`, temperatures in °F.

Because `Rxo = F × Rmf / Sxo^n` with `F ≥ 1` and `Sxo ≤ 1`, the flushed-zone resistivity cannot be below `Rmf(T)`; the fit keeps `Rxo` at or above it, and counts the samples where the observed or fitted `Rxo` was below it (information). The formation temperature comes from the surface temperature, gradient and datum of the temperature settings and the TVD of the sample, as in [Formation temperature](#formation-temperature), whether or not the temperature correction is on. When these settings are still the defaults, the run says so and gives the temperature range used. Measured resistivities are not temperature-corrected here: they are already at formation temperature. With no `Rmf`, `Rxo` has no lower bound and the run notes it.

### Inputs you must correct, and limits

- `RT`, `RM`, `RS` and `RXO` must already be corrected by you for borehole, mud and shoulder-bed effects. The step does not correct them.
- The profile is a single step: no annulus, no transition zone, no flushing gradient.
- When `Rt` is close to `Rxo` the result is not unique and the sample keeps the measured Rt.
- The result depends on the diameters and the exponent of the preset.
- Thin beds and shoulder beds make the three curves differ for reasons other than invasion; the correction is not valid there. In laminated sands the assumption of a homogeneous invaded zone is weaker.
- It is not a substitute for service-company tornado charts. Do not use it on resistivity that is already corrected for invasion.
- If the deep curve was changed by a vertical-resolution step, the medium and shallow curves are used as measured and have a different vertical resolution; the run warns.
- The pseudo-geometric function is a design choice, not a published fit. Doll (1949) gives the physical basis.
- The invasion step is not blocked by the shoulder-bed guard, which acts on vertical corrections only.
- In a Monte Carlo run the invasion-corrected Rt is held at its value; the tool constants and `Rmf` are not varied.

References: Doll (1949); Thadani and Hall (1981); Anderson (2001); Arps (1953).

## Uncertainty (Monte Carlo) *(v1.9.0)*

The deterministic HCPV and net pay depend on parameters that are never known exactly. The Monte Carlo analysis
repeats the saturation and pay stage N times with the parameters drawn from distributions you define, and
reports the spread. It reuses the same code as the analysis (the same Sw method selection, Rw and Rsh
temperature factor, cutoff comparisons and thickness rule), and it never changes the deterministic results.
HCPV here is the column thickness `Σ PHIE × (1 − Sw) × dz` in ft, as in the section above, not a volume: there
is no area, contact or fluid factor.

### Parameters varied

Eight parameters can be varied: `a`, `m`, `n`, `Rw`, `Rsh`, and the Vsh, PHIE and Sw cutoffs. One distribution
per parameter is defined for the whole project, and one realisation draws one offset `δ` per parameter. Each
well and zone segment then takes its own resolved value `v` (after scopes, lithology presets, automatic
estimates and calibrations) and uses

- relative mode: `v' = v × (1 + δ)`, with `δ` a fraction (0.10 is +10 %);
- additive mode: `v' = v + δ`, with `δ` in the unit of the parameter.

Relative is the default for `a`, `Rw` and `Rsh` (positive, skewed quantities), additive for `m`, `n` and the
cutoffs. An automatic Rw or Rsh is perturbed after it is estimated; it is not re-estimated for each draw. The
formation temperature factor is applied afterwards to the perturbed Rw and Rsh. Because the same `δ` applies to
every well and zone, the wells are perfectly dependent for each parameter: this is conservative, and it gives
the widest field spread.

Only the primary Sw model is evaluated in each realisation. A segment without an RT curve has Sw = 1, as in the
analysis, and samples with no valid resistivity or no valid Sw are excluded from pay and HCPV.

**Not varied:** porosity (matrix and fluid densities, shale point, NPHI matrix, gas correction and the
D-N combination), the GR baseline and Vsh, temperature, depth and the thickness rule, and the permeability
coefficients. Permeability, Swirr and flow units do not enter HCPV, net pay or the averages in pay, so they
are not computed. A tornado without the porosity and shale inputs understates the total uncertainty, and
the tab and the exports say so.

### Distributions and sampling

| Kind | Offset `δ` | Notes |
|---|---|---|
| Triangular | Low, Mid (mode), High | Needs Low ≤ Mid ≤ High |
| Normal | mean = Mid, standard deviation = Sd | Truncated at ±3 Sd; needs Sd ≥ 0 |
| Uniform | Low to High | Needs Low ≤ High |

A distribution with zero width is a constant. The marginals are the inverse CDFs of these distributions applied
to uniform numbers `u`. The numbers come from one random generator initialised with the **seed**:

- **Latin hypercube** (default): the unit interval is cut into N equal strata for each parameter and each
  stratum is hit exactly once, so the percentiles settle with fewer realisations than plain random draws.
- **Random**: independent uniform numbers.

The draws are generated before the realisations are evaluated, so the same configuration, seed, parameters and
data always give the same numbers.

**Correlation between m and n.** With a requested rank correlation `ρ`, the uniforms are mapped to standard
normals, `z = Φ⁻¹(u)`, correlated with the Cholesky factor of the correlation matrix, `z' = z Lᵀ`, and mapped
back, `u' = Φ(z')` (a Gaussian copula). The matrix entry is `2 sin(πρ / 6)`, which makes the rank (Spearman)
correlation of the draws close to `ρ`. The matrix must be positive definite and `|ρ| < 1`, and both parameters must be
enabled, or the run is refused. The default is `ρ = 0`, independent draws; published cementation and saturation
exponents are often positively related, and the choice is yours. `a` and `m` are also related in practice;
keeping `a` fixed is the usual alternative to correlating them.

### Physical limits

After the offset is applied, the value is clipped to these limits for every segment. The share of realisations in
which a parameter was clipped is reported in the diagnostics.

| Parameter | Limits |
|---|---|
| `a` | 0.1 to 5 |
| `m`, `n` | 1.0 to 4.0 |
| `Rw` | 0.001 to 100 ohm·m |
| `Rsh` | 0.05 to 5000 ohm·m |
| Vsh cutoff, Sw cutoff | above 0 up to 1 |
| PHIE cutoff | 0 to 0.5 |

### Exceedance statistics

The industry convention is used everywhere (tables, plots, exports): **P90 is the low case, the value exceeded
with 90 % probability; P10 is the high case.**

```
P90 = percentile(x, 10)     P50 = percentile(x, 50)     P10 = percentile(x, 90)
```

so `P90 ≤ P50 ≤ P10` always. Percentiles use linear interpolation. The mean, the standard deviation (N − 1),
the minimum and the maximum are reported with them. A realisation where a metric is undefined (for example the
average PHIE when no sample is pay) is left out of that metric's statistics and not counted in **N valid**.
**P(zero)** is the share of realisations with zero net pay in the scope, so a P90 of 0 is explained and not hidden.

**Convergence check.** P90, P50 and P10 are recomputed on the first and on the second half of the realisations
for the field HCPV net pay and net pay. If any differs between the halves by more than 2 % of the P50, the
result carries the warning *Percentiles not converged at N = ...; increase N*.

**Deterministic value.** Reported beside the percentiles, it is the same calculation with every `δ = 0`, on the
current parameters (it equals the Summary values for a well that is up to date).

### Aggregation over wells and zones

Within a realisation all wells and zones share the same draw. For each realisation the field values are

- HCPV and thickness (net pay, net reservoir): the sum over wells;
- average PHIE in pay: weighted by each well's net pay;
- average Sw in pay: weighted by each well's pore thickness over pay, `Σ PHIE × dz`, falling back to net pay weights
  in a realisation where no well has any; wells whose average is undefined are skipped.

These are the same rules as the **Field total** of the Summary. The percentiles are then taken on the vector of
the N field values, never by adding well percentiles: when wells respond in opposite directions to a parameter,
the field P90 differs from the sum of the wells' P90. A zone is evaluated in the same way, over its own samples,
within each well. A well that cannot be evaluated (no RT curve, no effective porosity, or a failed analysis) is
left out of every row, including the field, and is named in the diagnostics.

### Tornado and rank correlation

The tornado is one-at-a-time. For each enabled parameter the model is evaluated with that parameter at the 10th
and at the 90th percentile of its own distribution (clipped as above) and every other parameter at its base
value (`δ = 0`). The two outputs are reported as the *output at the low input* and the *output at the high
input*, not as P-values of the output, because the direction of the response differs by parameter. The bar
runs from the smaller to the larger output, the swing is `|output at high − output at low|`, the rows are sorted
by swing, and the deterministic value is the centre line. It is available for HCPV net pay and net pay, for the field,
each well and each zone.

One-at-a-time ignores interactions between parameters and any correlation. As a cross-check, the Monte Carlo
sample gives the Spearman rank correlation between each parameter's draws and the field value of the metric
over all realisations (positive: a larger offset gives a larger result).

## Rock Typing *(v1.8.0)*

Rock typing is optional and off by default. With it off, no column, summary entry or parameter is added and the
results are those of v1.7.2. With it on, core permeability and porosity are turned into rock types, which are
propagated to every well through the logs and used for permeability, net pay and HCPV per rock type. The fit is
made once, on the core pooled over the project, in the **Rock Typing** tab (see
[Rock Typing](user-guide.md#rock-typing)). The analysis only reads the stored definitions; it never fits.

### RQI, FZI and permeability

Amaefule et al. (1993), with `k` in mD and `φe` the effective (core helium) porosity as a fraction:

```
RQI = 0.0314 × √(k / φe)          [µm]
φz  = φe / (1 − φe)               (pore-to-grain volume ratio)
FZI = RQI / φz                    [µm]
```

On a log-log plot of RQI against φz, samples with the same FZI fall on one unit-slope line, a hydraulic flow
unit. Solving the definitions for permeability gives

`k = FZI² × φz² × φe / 0.0314² = 1014.2 × FZI² × φe³ / (1 − φe)²`

A form with `φz³ × φe` in place of `φz² × φe` is sometimes quoted; it has the wrong power of φz and is off by a
factor φz (a permeability 4 times too small at φe = 0.2). Petrophyter uses the form above, with the exact
`0.0314²` rather than the rounded 1014, so a sample's own FZI returns its own permeability. Unlike Timur and
Wyllie-Rose, this relation takes no Swirr.

### Core quality control

Every core row is given exactly one status, and the Rock Typing tab counts them by reason in **Core exclusions**:

| Status | Rule |
|---|---|
| `no_depth` | depth missing |
| `no_porosity`, `no_perm` | value missing. This includes null values such as −999.25 and non-physical values, which the core loader blanks and counts first; the tab shows them in **Of which excluded at load**, not as extra rows |
| `perm_not_positive` | permeability ≤ 0 (a logarithm cannot be taken) |
| `phi_out_of_range` | porosity ≤ 0.01 or above 0.50 |
| `ok` | everything else |

The porosity limits are core-plug quality limits, separate from the log limits (PHIT 0.45, PHIE 0.40). Carbonate
samples with vugs can legitimately exceed 0.40, so the ceiling is 0.50; the limits are parameters (`core_phi_min`
and `core_phi_max`, stored with the rock typing settings), not fixed in the equations. **Min PHIE** (0.02), set in
the tab, is the lower porosity limit for log samples.
Samples more than 3 standard deviations from the mean of log10(FZI) are counted and listed but kept. Wells whose
core depth is TVD still enter the fit, which does not use depth, but their samples are not used as core labels in
the log, because the logs are on measured depth.

**Overburden is not applied.** Core is used as measured, and the tab says so ("core measured as loaded;
overburden/Klinkenberg correction not applied"). If your core is not at stress, enter **Overburden phi factor**
and **Overburden k factor** (both 1.0 by default): porosity and permeability are multiplied by them before RQI.
The factors are your input, not a built-in correction; a stress correction for permeability is often 0.7 to 0.95.

A fit needs at least 20 usable rows and at least 5 samples in every rock type; otherwise Fit refuses and the
message names the counts.

### Hydraulic flow units by clustering

The feature is `x = log10(FZI)`, since FZI is close to log-normal within a flow unit. It is clustered with
k-means (`scipy.cluster.vq.kmeans2`, k-means++ start, seeds 0 to 9; the restart with the smallest within-cluster
sum of squares wins). In one dimension, nearest-centre assignment is the same as cutting at the midpoints between
the sorted centres, so a rock-type set is just the centres, the boundaries `b_i = (c_i + c_{i+1}) / 2` and a
representative `FZI_i = 10^c_i` (µm, the geometric mean). **Rock type 1 is the lowest FZI** and the numbers rise
with FZI; they are the same for the same data and settings, whatever the row order. Rock type 0 means unassigned.

**Suggested count.** Next to the **Rock types** count the tab shows **Suggested: n**, the count (2 to 8) with the
best mean silhouette (Rousseeuw 1987), considering only counts with at least 5 samples in every class. The count
that Fit uses is the one you set.

For each rock type the set also stores the root-mean-square of `log10(k_core) − log10(k_RT(φ_core))`, shown as
**k RMSE (log10)**: a direct statement of how well one FZI per type reproduces the core permeability.

**Fit scope.** *Project pooled* (default) fits one set on all wells' core, so a rock type number means the same
rock in every well. *Per well* and *Per zone* also fit a set for each well or zone with at least 20 usable
samples; wells and zones below that, and unzoned samples, use the pooled set, which is always fitted too. With
*Per well*, rock-type numbers are not comparable between wells.

### Winland R35

As an alternative to clustering, the method **Winland R35** classes each sample by its pore-throat radius at 35 %
mercury saturation, estimated from the Winland relation (Kolodzie 1980):

`log10(R35) = 0.732 + 0.588 × log10(k) − 0.864 × log10(φ%)`

with R35 in µm, `k` in mD and **φ in percent** (Petrophyter multiplies the fractional porosity by 100 inside).
The classes are fixed port-size classes (Martin et al. 1997): nano below 0.1 µm, micro 0.1 to 0.5, meso 0.5 to 2,
macro 2 to 10 and mega above 10, as rock types 1 to 5. Each class takes the geometric-mean FZI of its core
samples, so permeability per rock type works the same way; a class with no core sample has no FZI, and its
permeability is empty. The relation was derived on sandstones; on other lithologies treat the classes as a
descriptive grouping, not a measurement. **Add R35 column** writes `R35` to the results.

### Rock types on the logs

For every log sample, rock typing works from `PHIE` and a log permeability (Timur or Wyllie-Rose, set by **Log
permeability for rock types**). It computes `RQI` and `FZI` and classifies `log10(FZI)` with the well's
definitions (for Winland R35, `log10(R35)`).

**Eligibility.** A sample is left unassigned (`ROCK_TYPE = 0`) and `ROCK_TYPE_SOURCE` says why:

| `ROCK_TYPE_SOURCE` | Meaning |
|---|---|
| `core` | rock type taken from a core sample (below) |
| `log` | rock type classified from the log FZI |
| `x_vsh` | not gross sand (`VSH` at or above the Vsh cutoff); only when **Reservoir only** is on (default) |
| `x_phie` | `PHIE` missing or below **Min PHIE** (0.02) |
| `x_perm` | log permeability missing or at its limits (0.001 and 50 000 mD) |
| `x_nan` | any other missing input |

Every sample is counted in one of these, so assigned plus unassigned samples equal the samples of the well.

**Core labels.** With **Use core labels in the log** on (default), a log sample within the **Core Matching**
distance of a labelled core sample (2 ft by default) takes that sample's rock type and `ROCK_TYPE_SOURCE = core`.
The core label is the class of the core sample's own FZI, so it is independent of the log estimate. Where a
measured label exists it is shown instead of a modelled one; the jumps this can make at plug depths are reported
by the agreement count below.

**Flags.** Counted in the summary and shown in the Rock Typing tab:

- `RT_MARGIN`: the distance, in log10 units, from the sample's log10(FZI) to the nearest boundary. Samples with a
  margin below 0.05 (about 12 % in FZI) are counted as **near boundary** and drawn faded in the Rock Type track.
- **Outside range**: log10(FZI) more than 0.5 beyond the range of the fitted core.
- **Core vs log agreement**: at core-labelled samples, the share where the log classification gives the same
  rock type. This is the honest measure of how far the propagation can be trusted in that well.
- **Uncored well**: a well without a usable core row gets a warning, "No core labels for this well: rock types are
  log-derived with the project definitions."

**Caveat: the propagation is circular.** An uncored sample gets a rock type from an FZI computed from the logs, and
that FZI comes from a log permeability (Timur or Wyllie-Rose) that itself depends on `PHIE` and Swirr. It carries
grain-size information only through Swirr, so in uncored intervals the rock type, and `PERM_RT` below, inherit the
shape of the Timur or Wyllie-Rose permeability: they are a surrogate, not independent core evidence. Calibrating
Wyllie-Rose to core first (the **Calculate** button on the Permeability page) reduces the bias. The agreement
share, and the share of samples labelled from core (`pct_core`), tell you how much to rely on it.

### Permeability per rock type (`PERM_RT`)

`PERM_RT = clip(k(FZI_rt, PHIE), 0.001, 50000)` with `k` from the relation above, `FZI_rt` the representative FZI
of the sample's rock type and `PHIE` the log's. It is empty where `ROCK_TYPE` is 0: there is no silent
fallback to Timur. See [Permeability](#permeability) for how to make it the primary permeability.

### Lorenz coefficient and SMLP

The heterogeneity measures use the net reservoir samples with `PHIE` and the primary permeability:

- **Lorenz coefficient** (Schmalz and Rahme 1950; Lake and Jensen 1991): sort samples by `k/φ`, highest first; with
  `C` the cumulative `Σφh / Σφh_total` and `F` the cumulative `Σkh / Σkh_total`, `LC = 2 × ∫(F − C) dC` by the
  trapezoid rule. 0 is homogeneous; values towards 1 are heterogeneous.
- **Stratigraphic modified Lorenz plot** (SMLP; Gunter et al. 1997): the same `C` and `F` with the samples in
  depth order. The local slope `dF/dC = (k/φ) / (Σkh/Σφh)` is above 1 where the interval flows more than it
  stores (a speed zone) and below 1 for baffles and barriers.
- **Flow-unit segments.** The SMLP is simplified (Ramer-Douglas-Peucker, tolerance 0.02 in the unit square), and
  segments thinner than 5 ft are merged into the neighbour with the closer slope. Each segment is classed by
  slope: *speed* above 1.5, *intermediate* from 0.5 to 1.5, *baffle* from above 0.1 to below 0.5, *barrier* at 0.1
  or below. The segments are a table and an overlay, not a results column, so `FLOW_UNIT` and `ROCK_TYPE` keep
  their meanings.

On the core, the thickness `h` of a sample is half the distance to each neighbour, with each side limited to the
median spacing, so a gap in the core is a gap, not thickness. Log samples use the per-sample thickness of the
[net pay analysis](#net-pay-analysis-v10).

### Results added

When rock typing is on and definitions are applied: `RQI`, `FZI` (µm), `ROCK_TYPE` (integer, 0 = unassigned),
`ROCK_TYPE_SOURCE` and `RT_MARGIN`; `PERM_RT` when the primary permeability is *Rock type*; `R35` when **Add R35
column** is on. The summary gains a **Rock types** block: gross sand, net reservoir, net pay, N/G pay, average
PHIE and Sw in pay, HCPV, geometric-mean permeability and the share of core-labelled samples per rock type, per
zone and rock type, the counts above, the agreement, and the Lorenz coefficient with its segments. Net pay and
HCPV per rock type, plus the unassigned samples, add up to the well's totals.

References:

- Amaefule, J.O., Altunbay, M., Tiab, D., Kersey, D.G., Keelan, D.K. (1993), *Enhanced reservoir description:
  using core and log data to identify hydraulic (flow) units and predict permeability in uncored intervals/wells*,
  SPE 26436.
- Kolodzie, S. (1980), *Analysis of pore throat size and use of the Waxman-Smits equation to determine OOIP in
  Spindle Field, Colorado*, SPE 9382 (Winland relation).
- Gunter, G.W., Finneran, J.M., Hartmann, D.J., Miller, J.D. (1997), *Early determination of reservoir flow units
  using an integrated petrophysical method*, SPE 38679.
- Lake, L.W., Jensen, J.L. (1991), *A review of heterogeneity measures used in reservoir characterization*,
  *In Situ* 15(4).
- Schmalz, J.P., Rahme, H.D. (1950), *The variations in waterflood performance with variation in permeability
  profile*, *Producers Monthly* 15(9).
- Martin, A.J., Solomon, S.T., Hartmann, D.J. (1997), *Characterization of petrophysical flow units in carbonate
  reservoirs*, *AAPG Bulletin* 81(5).
- Rousseeuw, P.J. (1987), *Silhouettes: a graphical aid to the interpretation and validation of cluster analysis*,
  *Journal of Computational and Applied Mathematics* 20.

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
