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
