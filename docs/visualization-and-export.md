[Back to README](../README.md)

# Visualization and Export

## Interactive Log Display *(v1.1)*

The PyQtGraph display provides:

- OpenGL GPU-accelerated rendering
- Six-track composite log display, and a seventh **Rock Type** track when the results hold rock types *(v1.8.0)*
- Zoom, pan, and crosshair cursor
- Draggable depth-region selection
- Formation-top overlays
- Linked Y axes across all tracks
- Updates throttled to approximately 30 FPS for smooth interaction *(optimized in v1.2)*

## Classic Log Display *(v1.0)*

The Matplotlib display produces static, export-quality plots and includes a navigation toolbar for pan, zoom, and save operations. With rock types in the results it draws the same seventh track as the interactive display.

## Rock Type Track *(v1.8.0)*

Present in both displays only when the results hold `ROCK_TYPE` (rock typing on, definitions applied, and a run made):

- Categorical stepped bands across the track, one colour per rock type, from one ordered ramp (dark for rock type 1, the lowest flow zone indicator, to light for the highest). Unassigned depths (`ROCK_TYPE` 0) are grey.
- A band is faded and hatched where the rock type comes from the log rather than from core, or where the sample is within 0.05 log10 units of a rock-type boundary, so a solid band is a rock type taken from core.
- The legend lists the rock types present as RT 1, RT 2, and so on. In the interactive display the readout gives the rock type, the FZI and the source at the cursor depth.

The **Rock Typing** tab has its own plots: the FZI histogram and probability plot, porosity-permeability with constant-FZI curves, RQI against φz, Winland R35 lines, and the Lorenz and stratigraphic modified Lorenz plots. See the [User Guide](user-guide.md#rock-typing).

## Saturation-Height Sw and Residual Track *(v1.10.0)*

Present in both displays only when the results hold `SW_SHF` (saturation-height modelling on, a fit and a contact set, and a run made):

- **Sw track.** `SW_SHF` is drawn dashed and labelled **Sw SHF**. When SHF Sw is used for pay and HCPV, `SW_PAY` is also drawn, dotted, as **Sw SHF (pay)**. The resistivity `SW` keeps its usual line.
- **Residual track.** A last track, after the Rock Type track, titled **Sw − Sw SHF**, shows `SW_SHF_RESID` (`SW − SW_SHF`) on a fixed range of −0.5 to 0.5 with a zero line. Positive values mean the resistivity Sw is higher than the capillary model. The track is absent without `SW_SHF_RESID`.
- **Readout.** In the interactive display the readout under the log gives the height above the free water level (`HAFWL`, ft) at the cursor depth.

The **Saturation-Height** tab has its own plots: J against Sw with the fitted curves, Sw against height, and the profile around the free water level. See the [User Guide](user-guide.md#saturation-height).

## Resistivity Track and Shaded Flags *(v1.11.0)*

Present only when the results hold LRLC columns (LRLC analysis on, and a run made); without them both displays are as before.

- **Resistivity track (Classic).** The Classic display gains a **Resistivity** track right after the Sw track, so the Permeability, Pay Flags, HCPV, Rock Type and residual tracks each move one place to the right. It draws the measured Rt, `RT_SW` (solid), `RT_SAND` (solid), `RT_PYR` (dashed) and `RT_CUT` (dashed) on a log axis from 0.2 to 2000 ohm·m. It appears when `RT_SW`, `RT_CUT`, `RT_SAND`, `RT_PYR` or `LRLC_FLAG` is in the results; `RT_SW`, `RT_SAND` and `RT_PYR` exist only where an Rt correction step is active, so without one the track shows Rt and `RT_CUT`.
- **Resistivity track (Interactive).** The existing resistivity track lists `RT_SW`, `RT_SAND`, `RT_PYR` and `RT_CUT` with the other resistivity curves when the columns exist; `RT_CUT` and `RT_PYR` are dashed. The cursor readout includes them.
- **Invasion curves** *(v1.13.0)*. When the invasion step has run, `RT_INV` (solid) and `RXO_INV` (dotted) are added to the resistivity track in both displays, on the same log axis. In the Classic display they also make the track appear.
- **Laminar shale volume.** `VLAM` is drawn dotted on the Vsh axis of the gamma ray track, in both displays, when the results hold it. In the Classic display a gamma ray track with `VLAM` but no `VSH` still gets the Vsh axis.
- **Baseline Sw.** `SW_BASE`, the Sw without the LRLC corrections, is drawn in the Sw track as a thin dashed line, so it can be compared with the corrected Sw. It is not one of the Sw methods and has no entry among them.
- **Readout only.** `VPYR` (v/v) and `QV_EST` (meq/mL) are not drawn. The Interactive display shows them in the cursor readout; the Classic display does not show them.
- **Readout only** *(v1.13.0)*. `M_VAR` and `N_VAR` (unitless) and `DI_INV` (in) are not drawn. The Interactive display shows them in the cursor readout; the Classic display does not.
- **Shaded flags.** The Pay Flags track shades the depth intervals flagged by `LRLC_FLAG` (**LRLC**) and `WATER_FREE_FLAG` (**Water-free**) with a translucent fill, in the legend of the track. In the Interactive display the readout gives the flag values at the cursor depth.

The **LRLC Workbench** tab has its own plots: Pickett, Buckles, the Thomas-Stieber crossplot of `PHIT` against `Vsh` coloured by class, the PEF against RHOB crossplot of the pyrite tool, the Sw before and after plot of the Validation panel, and, from v1.13.0, the plots of the Remediation panel: the fitted against observed `m` and `m` against porosity of the variable m/n fit, and the invasion profile at a depth and the RS/RT against RM/RT crossplot of the radial invasion tool. See the [User Guide](user-guide.md#lrlc-workbench).

## Uncertainty Tab *(v1.9.0)*

The **Uncertainty** tab (after Summary) draws the latest Monte Carlo result for the row selected in its table (the field, a well, or a zone) and the selected metric.

- **Histogram and exceedance.** A histogram of the realisations (30 bins) with vertical lines at P90, P50 and P10 and a dashed line at the deterministic value. A second axis on the right shows the exceedance curve: the percent of realisations at or above each value. P90 is the low case, exceeded with 90 % probability.
- **Tornado.** For HCPV net pay and Net pay: one horizontal bar per enabled parameter, running between the outputs with that parameter at the 10th and at the 90th percentile of its own distribution (the other parameters at their base values), sorted by swing, with a vertical line at the deterministic value. Each label shows the low and high input as a signed change: a percentage for a relative parameter (for example -15 % / +15 %), or a signed amount with its unit for an additive one (ohm.m for Rw and Rsh, v/v for the cutoffs). A table below lists the inputs, the outputs, the swing and the rank correlation with the field metric.

The plots follow the light and dark themes. See the [User Guide](user-guide.md#uncertainty-monte-carlo) for how to set up and read an analysis.

## Crossplots

- Neutron-density crossplot, color-coded by Vsh
- Porosity-permeability crossplot

## Export Options

| Format | Description | Version |
|---|---|---|
| Excel (`.xlsx`) | Multi-sheet workbook containing results and a summary | v1.0 |
| CSV (`.csv`) | Full results DataFrame | v1.0 |

Merged data can also be downloaded as LAS (`.las`).

### Uncertainty in the exports *(v1.9.0)*

The Excel workbook gets two more sheets when a Monte Carlo result exists; without one, the workbook is as before. A result that is out of date is exported as it is, with the stale flag set in the header. CSV and LAS exports are unchanged.

- **Uncertainty sheet.** A header block gives the seed, N, sampling, the exceedance convention (*P90 = low case, exceeded with 90% probability*), the parameters that are not varied (porosity, shale point, GR baseline), and whether the result is out of date. The table has one row for each metric of the field, each well, and each well and zone, with the columns Scope, Metric, P90, P50, P10, Mean, Std, Min, Max, N valid, P(zero) and Deterministic.
- **Tornado sheet.** One row for each parameter, with its mode, the low and high input (numeric offsets, plus a text column for each that adds the percent sign or unit), the output at each, the swing and the rank correlation with the field metric.

A well named *Uncertainty* or *Tornado* gets a numbered sheet name such as *Uncertainty (2)*, so it never collides with these sheets.

### Rock typing in the exports *(v1.8.0)*

Added only when rock typing is on and applied; without it, the files are as before.

- **Columns.** The results table of CSV and Excel (each well sheet, and the combined table of an all-wells export) gains `RQI`, `FZI` (µm), `ROCK_TYPE` (integer, 0 = unassigned), `ROCK_TYPE_SOURCE` (`core`, `log`, `x_vsh`, `x_phie`, `x_perm` or `x_nan`) and `RT_MARGIN` (log10 units to the nearest boundary); `PERM_RT` when the primary permeability is Rock type; `R35` when the R35 column is on.
- **Rock Types sheet.** The Excel workbook gains a **Rock Types** sheet with one row per well and rock type: samples, gross sand, net reservoir, net pay, N/G pay, average PHIE and Sw in pay, HCPV, geometric-mean permeability, FZI and the share of core-labelled samples, then an **Unassigned** row per well and, for a project-wide fit, **Field total** rows (thickness and HCPV summed, Sw weighted by pore thickness).
- **LAS.** `ROCK_TYPE`, `FZI`, `RQI`, `RT_MARGIN` and `PERM_RT` are written as numeric curves. The text column `ROCK_TYPE_SOURCE` is not written, as for other text columns.

### Saturation height in the exports *(v1.10.0)*

When saturation-height modelling has run, the results table of CSV, Excel (each well sheet, and the combined table of an all-wells export) and LAS gains `SW_SHF` (Sw from the saturation-height model), `HAFWL` (height above the free water level, ft, negative in the water leg) and `SW_SHF_RESID` (`SW - SW_SHF`), plus `SW_PAY` when SHF Sw is used for pay and HCPV. Without saturation-height content the exports are exactly as before.

The Excel workbook gets an **SHF** sheet, in the all-wells workbook for every well that has saturation-height results and in a single-well workbook for that well. It has one row for the well, then one row for each zone and one for each rock type, with the columns:

- **Well**, **Zone** and **Rock type**: the well row reads *All zones* and *All*; a zone row names the zone and a rock-type row the rock type.
- **n**, **Bias**, **RMSE**, **MAE** and **R2**: the misfit of `SW` against `SW_SHF` (bias is the mean of `SW - SW_SHF`) over net reservoir samples above the free water level, and **Basis**: *core Pc*, *log-derived* or *mixed*.
- **FWL (TVD)**, **Fluid**, **Water density** and **Delta rho**: the contact, hydrocarbon and densities used in the zone (blank on the well and rock-type rows).
- **Perm source** and **PHIE source**: the columns J was computed from.
- **SHF Sw for pay**: *used*, *not used* or *refused (log-derived fit)*.

A well named *SHF* gets a numbered sheet name such as *SHF (2)*. The *Rock Types*, *Uncertainty* and *Tornado* sheets and the Summary and Zones columns are unchanged. With SHF Sw used for pay, the Uncertainty sheet header lists "SHF Sw where used for pay" among the parameters that are not varied.

### LRLC in the exports *(v1.11.0)*

Added only when the LRLC analysis is on and has run; without it, the files are as before.

- **Columns.** The results table of CSV, Excel and LAS gains `LRLC_SCORE`, `LRLC_FLAG`, `BVW` and `WATER_FREE_FLAG`; `RT_CUT` when the Rt cutoff is on; `RT_SW` when an Rt correction step is active; and the columns of the corrections that are in use, `VLAM`, `VDISP`, `PHI_SAND`, `TS_CLASS`, `VPYR`, `QV_EST`, `RT_SAND`, `RT_PYR`, `SW_BASE` and `NET_PAY_BASE_FLAG`, and from v1.13.0 `RT_INV`, `RXO_INV`, `DI_INV`, `M_VAR` and `N_VAR` (see [Data Formats](data-formats.md#lrlc-result-columns)). The flags and `TS_CLASS` are integers. There is no separate LRLC sheet.
- **LAS curves.** The LRLC curves are written with a plain-text description and a unit instead of the column name. Derived curves are marked `MODELLED`; the text has no colon and is ASCII.

| Curve | Unit | Description |
|---|---|---|
| `RT_SW` | OHMM | `MODELLED RT READ BY SW MODELS (<path>)`, the path being the correction chain, for example `RT_SAND <- RT` |
| `RT_CUT` | OHMM | `MODELLED RT AT TARGET SW (primary model)` |
| `BVW` | V/V | `MODELLED BULK VOLUME WATER PHIE*SW` |
| `WATER_FREE_FLAG` | UNITLESS | `FLAG SW AT OR BELOW SWIRR PLUS TOL IN NET RES` |
| `LRLC_FLAG` | UNITLESS | `FLAG LRLC SCREENING CANDIDATE` |
| `LRLC_SCORE` | UNITLESS | `COUNT OF SCREENING CRITERIA MET` |
| `RT_SAND` | OHMM | `MODELLED LAMINATED-SAND RT (HAGIWARA), FROM RT` |
| `RT_PYR` | OHMM | `MODELLED PYRITE-CORRECTED RT, FROM RT_SAND`, or `FROM RT` where the laminated-sand step did not run (`RT_SAND OR RT` when both occur) |
| `VLAM` | V/V | `MODELLED LAMINAR SHALE VOLUME (THOMAS-STIEBER)` |
| `RT_INV` | OHMM | `MODELLED INVASION-CORRECTED RT (step profile), FROM RT` |
| `RXO_INV` | OHMM | `MODELLED FLUSHED-ZONE RESISTIVITY (step profile)` |
| `DI_INV` | IN | `MODELLED INVASION DIAMETER (step profile)` |
| `M_VAR` | UNITLESS | `MODELLED CEMENTATION EXPONENT (variable m, zone formula)` |
| `N_VAR` | UNITLESS | `MODELLED SATURATION EXPONENT (variable n)` |
| `VDISP` | V/V | `MODELLED DISPERSED SHALE VOLUME (THOMAS-STIEBER)` |
| `PHI_SAND` | V/V | `MODELLED SAND POROSITY (THOMAS-STIEBER)` |
| `TS_CLASS` | UNITLESS | `THOMAS-STIEBER CLASS CODE 0 TO 5` |
| `VPYR` | V/V | `MODELLED PYRITE VOLUME FROM RHOB/PEF`, or `USER-SET PYRITE VOLUME` when the constant is used |
| `QV_EST` | MEQ/ML | `ESTIMATED QV FROM VSH AND CEC` |
| `SW_BASE` | V/V | `SW FROM MEASURED RT, NO LRLC CORRECTION` |
| `NET_PAY_BASE_FLAG` | UNITLESS | `NET PAY FLAG FROM SW_BASE` |

- **Provenance.** The block gains a line **Rt corrections** after **Depth interval**, saying which resistivity the Sw models read in each zone, for example `RT_SW = RT_SAND <- RT (zones: UPPER); RT_SW = RT (zones: other)`, or `none (RT_SW not written)` when no correction step ran. It appears on the Excel **Provenance** sheet, in the CSV `.provenance.txt` file and as the line `Rt corrections` in the LAS `~OTHER INFORMATION` section. Runs without LRLC have no such line. When the run used Thomas-Stieber end-points, the Qv estimate, the pyrite step or the laminated-sand step, a second line **LRLC inputs** follows it, in the same three places (the LAS line reads `LRLC inputs`). It names the Thomas-Stieber end-points of each zone (`phi_max` and `phi_sh`), the shale CEC of the Qv estimate, the pyrite method with the connected fraction and `Rpy`, the Sw basis (sand, bulk or both) and whether the shoulder-bed guard was on, for example `Thomas-Stieber UPPER phi_max 0.3 phi_sh 0.12; Qv estimate cec_shale 25; Sw basis sand; guard on`. A run that used none of them has no such line.
- **Provenance, variable m/n and invasion** *(v1.13.0)*. `RT_INV` is listed in the **Rt corrections** line like any other step (for example `RT_SW = RT_SAND <- RT_INV <- RT`), and the LAS text of a later step names its real source. Two more lines are added, in the same three places, only when they apply. **Variable m/n** appears when a zone is in Curve mode and names the models, the zones and the share of values that were clipped, for example `M_VAR = f(PHIE, VSH) formula, N_VAR = constant (zones: Upper); clipped 0.4 %`. **Invasion tool** appears when the step ran and names the tool for each zone, marking an unchanged preset as unconfirmed, for example `generic_induction (generic, unconfirmed)`. The Uncertainty sheet header lists *m/n curve shape (coefficients; only a whole-curve offset is varied)* and *invasion-corrected Rt (frozen)* among the inputs not varied when they apply.
- **Excel zone columns.** On the Zones sheet, a run with an active correction adds **Net pay (before)**, **Avg Sw (before)** and **HCPV (before)** (the pay without the corrections, from `SW_BASE`), and a run with a diagnosis adds **LRLC probable cause** (the primary cause, or *none*) and **LRLC level** (*probable* when there is a primary cause; otherwise the diagnosis status, *ok* when no cause is probable and *insufficient* when the zone has too few net reservoir samples). The Uncertainty sheet header lists the corrected inputs among those not varied, and adds the line *Rsh also varies the laminated-sand Rt* when it applies.
