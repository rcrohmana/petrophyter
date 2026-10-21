[Back to README](../README.md)

# Version History

## v1.10.0 (Build <build>) — Current Release

See the [release notes](releases/v1.10.0.md) for details. Saturation-height modelling is optional: **results
do not change** until you enable it, and sessions that do not use it are saved as before.

- **Load Pc Data…** and **Load Pc Data (Multi-Well)…** (File menu). Capillary pressure curves with the
  Pc unit and fluid system asked for when the file lacks them; porosity and permeability completed from
  the core data; excluded rows counted by reason. Loading changes no result.
- **Saturation-Height tab** (after Rock Typing). Confirmable fluid densities and interfacial tensions; power
  law or Brooks-Corey J-function fits per rock type (one fit for all samples when rock typing is off or
  fitted per zone) with plots, a fits table and **Apply fit**; **Fit from logs** as a cross-check only.
- **Contacts per well and zone.** Free water level (not the OWC), fluid and optional water density per
  zone, TVD or TVDSS with a typed KB; **Estimate FWL** then **Accept**.
- **Compute saturation-height Sw on Run** adds `SW_SHF`, `HAFWL` and `SW_SHF_RESID`; a misfit table
  (bias, RMSE, MAE, R2) for the well, each zone and each rock type.
- **Use SHF Sw for pay and HCPV** (core Pc fits only) reads `SW_PAY` for pay, N/G, average Sw and HCPV.
  Monte Carlo holds the saturation-height Sw fixed where it is used for pay.
- **Log display.** **Sw SHF** (dashed) and **Sw SHF (pay)** (dotted) on the Sw track, a **Sw − Sw SHF**
  residual track, and the height above the free water level in the interactive readout.
- **SHF** sheet in the Excel workbook; the new columns in CSV, Excel and LAS.
- **Session format 2.4** when the project holds saturation-height content; it opens in v1.9.x and older
  without that data. An uncertainty setup with every distribution switched off is now saved with the session.
- NNNN tests.

## v1.9.0 (Build 20261021)

See the [release notes](releases/v1.9.0.md) for details. Uncertainty analysis is optional: **results do
not change** until you enable a distribution, and sessions that do not use it are saved as before.

- **Uncertainty tab** (after Summary). Monte Carlo P90, P50 and P10 of HCPV net pay, HCPV net
  reservoir, net pay and the pay averages for the field, each well and each zone; histogram with an
  exceedance curve; tornado for HCPV net pay and net pay with signed inputs and rank correlations;
  clipped draws, zero-pay probability, excluded wells and a convergence warning; an out-of-date chip.
- **Parameters → Uncertainty.** Triangular, normal or uniform distributions for a, m, n, Rw, Rsh and
  the cutoffs, as relative or additive offsets of every well's and zone's resolved value; Suggested
  ranges; N (default 300), seed, Latin hypercube or random sampling; a rank correlation between m
  and n; the auto-Rw quality of the last run.
- **Analysis → Run Uncertainty… / Stop Monte Carlo.** Runs in the background with progress; needs an
  enabled distribution and a well with RT; cancelled by New Project and Load Session; quitting asks.
- **Uncertainty** and **Tornado** sheets in the Excel workbook when a result exists.
- **Session format 2.3** when a distribution is enabled; the result itself is not saved.
- Simandoux with n other than 2 is solved for all samples at once: identical results, about 30 times
  faster.
- 1704 tests.

## v1.8.0 (Build 20261013)

See the [release notes](releases/v1.8.0.md) for details. Rock typing is optional: **results do not change**
until you turn it on, and sessions that do not use it are still saved as format 2.1.

- **Rock Typing tab.** RQI and FZI from core porosity and permeability, every excluded core row counted
  by reason; rock types fitted on log10 FZI (pooled over the project, or per well or per zone) with a
  suggested count; **Fit** runs in the background, **Apply to project** writes the definitions; FZI,
  Phi-K, RQI-phiz (with a diagnostic free-slope fit per type), Winland R35 and Lorenz/SMLP plots; editable definitions; a banner when the core
  changed since the fit.
- **Rock types in the run.** `RQI`, `FZI`, `ROCK_TYPE`, `ROCK_TYPE_SOURCE`, `RT_MARGIN`, optional
  `PERM_RT` and `R35`; core labels win within the core matching distance; near-boundary,
  outside-range and core-versus-log agreement counted.
- **Primary permeability** (Timur, Wyllie-Rose or Rock type, project or well) feeds `FLOW_UNIT` and the
  quality flags.
- **Pay and HCPV per rock type** in the Summary and a **Rock Types** sheet in the Excel export; field
  totals only for project-wide definitions. **Export definitions** writes the definitions to CSV.
- **Rock Type log track** when the results hold rock types.
- **Session format 2.2** when rock typing is used; a session from a newer Petrophyter is refused with a
  message instead of being misread.
- The Rock Typing tab says what to do after enabling rock types and where they appear; it stays
  responsive while open, redrawing only what changed.
- 1519 tests.

## v1.7.3 (Build 20261011)

See the [release notes](releases/v1.7.3.md) for details, including the confirmed defaults. Results do not
change.

- **Curve Mapping detail.** Mapped curves table: unit, coverage (warning below 50 %), range, Auto or
  Manual mapping.
- **Changes since the last run.** The Parameters window lists what changed since the active well's
  last run; **Revert to last run** restores those parameters (project values are shared, tops are not
  reverted).
- **Plot engine under Advanced** on the Log Display tab.
- The Sw > 1.05 warning needs at least 10 clean samples in the zone.
- README: SmartScreen and SHA-256 check for the unsigned installer.
- 1338 tests.

## v1.7.2 (Build 20261011)

See the [release notes](releases/v1.7.2.md) for details, including the reference-case deltas. **Results change**;
sessions from 1.7.1 and older show a notice and every well is out of date until Run.

### Calculation changes

- **Porosity.** PHIT on every porosity path; D-N combination Average (default) or RMS, RMS on gas
  samples; RMS reproduces the old PHIT. Gas flag needs a 0.02 crossover and Vsh ≤ 0.40; PHIE_GAS ≤ PHIT. The
  neutron shale term uses `NPHI_shale − NPHI_matrix`.
- **Saturation.** Waxman-Smits and Dual-Water are solved on PHIT (`SWT_WS`, `SWT_DW`) and
  reported as effective Sw from the hydrocarbon volume; one validity rule (Sw 1 at porosity ≤ 0.001, Vsh 0–1)
  for every model; bound hits counted per model and zone. Waxman-Smits accepts Qv 0.
- **Rw, Rsh, shale.** Automatic Rw from the water-like samples (water leg, no contrast, or no
  water); automatic Rsh needs 10 shale samples; clamps warn. Zone GR baseline keeps the well's GRmax in a zone
  without shale. `VSH` from the Primary Vsh method.
- **Pay, HCPV, Swirr, permeability.** One thickness rule with local gap detection for
  pay and HCPV; thickness-weighted PHIE and Vsh, pore-volume-weighted Sw; Swirr floor applied last; the
  selected Swirr method feeds permeability; calibration fits C and P with Q held and the run's Buckles Swirr.

### Interface

- Log tracks in real units from one track definition; Sw track and histograms follow the primary model.
- Plot controls (HCPV mode, tops, crossplot sync) work on both engines; the export preview says what it shows
  and the depth interval applies to the export.
- Settings for the corrections: D-N combination, gas Crossover min and Gas Vsh max (per well and zone),
  Primary Vsh. Calculate Rw/Rsh shows its sample counts and warnings; the Permeability page shows the result's
  source, calibration notes and the Swirr mismatch warning while keeping Apply; temperature readout warns.
- Diagnostics: Sw Solver and Porosity Checks per model and zone (Sw above 1.05 before clipping is
  counted), Swirr method used and its limits, zones without shale; tables scroll sideways.
- Run issues carry codes, severities and field targets; counts below their limit are notes, so a normal run
  is a success banner.

### Sessions and provenance

- Source files are fingerprinted (SHA-256); a changed file is noted on restore and a missing one can be located.
  The provenance block records fingerprints, merge recipe and library versions.

### Quality

- Hand-worked formula values and Hypothesis property tests; 1322 tests.

## v1.7.1 (Build 20261011)

See the [release notes](releases/v1.7.1.md) for details.

### Trust and safety

- **Run issues.** Runs with warnings show a warning banner with **Review**, which opens **Diagnostics → Run issues** (severity, zone, and **Go to** for each issue). The Data Browser shows the warning count of a well's last run, and the Summary Wells table has an **Issues** column. Calculate Rw/Rsh shows the estimate's warnings.
- **Used in last run.** The Summary cutoffs and the Diagnostics shale parameters show the values the last run used, with "Current settings differ — Run to update" when they changed, and "varies by zone" when zones differ.
- **Export freshness and provenance.** The Export tab shows whether results are current, and exporting out-of-date or failed wells asks first (Run out-of-date wells, Export last successful results, Cancel). Excel exports get a Provenance sheet and a Parameter / Scope / Value / Source summary table, LAS an `~OTHER` section, and CSV a `.provenance.txt` sidecar.
- **Field total** leaves out wells whose latest run failed; out-of-date wells count and are flagged ("4 wells (1 out of date)").
- **Stop analysis** in the Analysis menu, on the toolbar, and with `Esc` while a run is active.
- **Unsaved changes.** An asterisk in the window title, Save to the current file (`Ctrl+S`), **Save Session As…** (`Ctrl+Shift+S`), and a Save / Discard / Cancel prompt on Close, Load Session, and New Project.

### Intake and robustness

- Resistivity, RHOB, and DT samples ≤ 0 are set to NaN at load and in the run, and counted. A resistivity ≤ 0 no longer crashes the run.
- Core null sentinels and non-physical values are excluded and counted; a failed core calibration reports why.
- Declared curve units are checked against the values, depths outside −1 000 to 60 000 ft are refused, and a header TD or BHT without a unit is flagged in the temperature readout with an unusual-gradient warning.
- A tops column with `TVD` in its header is flagged and needs confirmation in the import dialog.
- A porosity of 0.15 is no longer substituted where no method gives a value.
- Input curves named like result columns are kept as `<NAME>_IN`; exports refuse duplicate column names with a clear error.
- A Per-Formation selection that matches no formation of a well fails that well instead of analysing all of it.
- Core samples are matched to the log only with valid log samples on both sides within the matching distance; cores beside log gaps are counted.
- Files over 500 MB, and merges over 2 000 000 depth points or about 1 GB, are refused before they start. Merge step and gap limit from sessions are clamped to the dialog's ranges.
- Exported text never becomes a spreadsheet formula (Excel literal text; CSV `'` prefix for `= + - @`).

### Merging and sessions

- Merging no longer extrapolates past a file's ends, keeps measured samples at gap edges, interpolates resistivity in log10, and accepts TVD and MD curves.
- Sessions store each merged well's own step, gap limit, and merge-rules version, and the Petrophyter version that saved them. Merged wells from v1.7.0 sessions are merged again under the new rules with a note.
- A session load that fails or skips every well keeps the open project.

### Build and documentation

- `requirements-lock.txt`, a test gate and `--self-test` check in the build script, `SHA256SUMS.txt` and environment manifest written by the build, and a GitHub Actions workflow.
- `docs/calculation-methods.md` matches the code (Vsh methods, Indonesian closed form, Simandoux form, automatic Rw and Rsh).
- 1078 tests; `pytest -n 8 -m "not slow"` runs them in about a minute.

## v1.7.0 (Build 20261010)

### Multi-well projects

- A project holds any number of wells. **Open LAS File(s)…** reads several files in the background and shows a **Load Summary** that groups them by well identity (UWI, API, or name). Files of one well are merged; files of different wells are never merged. Reloading a well with the same key replaces its data and keeps its tops, core data, and parameters.
- The Data Browser has one root per well, and a well selector appears in the toolbar. Tops, core data, analysis scope, and results belong to each well; a new well never inherits another well's tops or core data.
- **Run All Wells** (`Ctrl+Shift+R`) analyses every well in the background and skips wells whose parameters have not changed since their last run. **Run Analysis** (`F5`) always reruns the active well. Run is disabled only while the active well is running, so other wells can run meanwhile.
- The Summary tab adds a Zones pay table for the active well and, with two or more wells, a Wells table with a field total. Export writes the active well or all wells: Excel with Summary, Zones, and one sheet per well; CSV with a WELL column; one LAS file per well. The log can shade zones.

### Parameter scopes and zones

- Parameters can be set for the project, a well, a zone (formation), or a well · zone; the most specific entry wins. The Parameters window has a scope bar, a mode menu per field (Auto, Manual, Inherit, Copy to…, Set as project default), and a **Zones** grid.
- Zones run as their own segments with their own a, m, n, matrix and shale points, Rw, Rsh, and cutoffs. Auto estimates (Rw, Rsh, shale point) use only that scope's samples and fall back to the next scope when a zone is too thin; the source of every value is shown.
- The shale point accepts **Auto** per well and per zone. Calculate and Apply work on the edited scope.
- A lithology preset at a well or zone scope supplies a, m, and n there and stays linked; typing a value switches it to Custom. Older sessions with explicit values equal to the preset are collapsed on load.
- Permeability **Calculate** fits Wyllie-Rose coefficients to the edited scope. A zone with fewer than five core pairs reports it instead of widening the fit.
- Zones with no gross, no net reservoir, or no net pay are marked in the Summary Zones table, and the limiting cutoff is marked in the Zones grid, with a tooltip that explains the likely cause. Results are stored in `summary["zone_diagnostics"]`.

### Rw, Rsh, and formation temperature

- Rw and Rsh each have an **Auto** checkbox. Manual values are used as entered, and **Apply Calculated Values** switches both to manual.
- Auto Rw uses the Rwa method on clean (Vsh < 0.3), porous samples.
- **Correct resistivities for formation temperature** corrects Rw with Arps' equation at every sample, and also an auto Rsh, a manual Rsh with a new **Rsh ref. temp**, and the Dual-Water Rwb. **Waxman-Smits B from temperature** (Juhasz, 1981) is optional. Applying a calculated Rsh stores its reference temperature. All options are off by default.
- Formation temperature follows true vertical depth: a mapped **TVD** curve in Curve Mapping, then a TVD depth index, then measured depth. A **Datum depth** sets where the surface temperature applies, the gradient can come from the LAS header (BHT and TD), and a live readout shows the temperature at the log ends.

### Multi-well tops and core import

- Added **File → Open Formation Tops (Multi-Well)…** and **Open Core Data (Multi-Well)…**, also in the Data Browser well menu. One file with a well column is assigned to the loaded wells in a preview dialog: detected delimiter and encoding, column mapping, depth unit, fill-down for merged cells, sheet, a raw preview, and one row per file well with its match, existing data, Keep or Replace action, porosity scale, and notes. Nothing changes until you confirm, and a failed assignment changes nothing.
- **Open Formation Tops…** and **Open Core Data…** send a file with a well column to the same dialog. The last formation of a tops file without bottom depths runs to the bottom of the log.
- Tops and core files can be `.xlsx`, and can be delimited by tab, comma, semicolon, or pipe, with UTF-8 or Windows-1252 text, comment and preamble lines, a unit row, and decimal commas. Commas that all read as thousands groups (`1,250`) are thousands separators.
- Every excluded row is counted with its file line number and reason. Core porosity is read as percent or fraction per well from its median, with an override in the dialog. A TVD core depth column raises a warning. Petrel `Surface` and `MD` columns and `wellbore` or `borehole` well columns are recognised.

### LAS loading

- The LAS parser reads UWI, API, location, service company, date, KB/GL/DF elevations, BHT, and TD. The depth unit falls back to the depth curve's unit.
- Neutron in percent, density in kg/m³, and sonic in µs/m are converted to V/V, g/cm³, and µs/ft at load (inferred from the value range when the unit is missing), with a note.
- Merging refuses files from different wells and reports per-curve units and sources. Merge warnings and every file's unit notes appear in one banner.

### Sessions

- Session format 2.0 stores the whole project: project and zone parameters, and for each well its LAS paths, merge settings, curve mapping, analysis scope, parameters, and tops and core files. Loading it re-reads the files; results are not stored, so restored wells need a run.
- Format 2.1 adds an import record for each well's tops and core data and replays it exactly on load, with a fallback to name matching and a note.
- Loading a session rebuilds its wells in the background. The window stays responsive, the status bar shows `Restoring 3 of 10: BKS-03`, and New Project or Load Session cancels the restore.
- Format 1.x sessions still load: their parameters are applied to the project. Sessions saved by v1.7.0 cannot be opened by v1.6.0 or older.

### Interface and responsiveness

- Every menu action has an icon, and menus use a fixed icon column.
- The Parameters pages no longer show background bands behind sliders and forms. The Cutoffs page is a single label, slider, and value grid.
- The Diagnostics porosity table marks the selected method with bold text, a check icon, and a tooltip instead of a "(selected)" suffix.
- Chart titles and labels use normal weight consistently.
- Without pyqtgraph, the log engine combo disables the Interactive item, labels it "Interactive (requires pyqtgraph)", and selects Classic.
- Interactive log track titles, formation-top lines, and the depth region follow the theme.
- Loading a LAS file refreshes the result tabs once instead of twice, and hidden plot tabs redraw only when shown.
- The status bar shows the stage of the running well, or the combined progress and the current well and stage when several wells run.
- Merge interpolation and the Waxman-Smits and Dual-Water solvers are vectorised; both models on 10,000 samples take about 10 ms instead of 0.7 s.

### Fixes

- While LAS files are loading or merging, New Project, Open LAS/Formation Tops/Core Data (single and multi-well), Load Session, Merge LAS Files, Run Analysis, and Run All Wells are disabled, so they cannot replace the data in use. Data Browser shortcuts honour the same state.
- Quitting during an analysis, a load, or a session restore asks for confirmation.
- Numbers use the English (US) format (decimal point) regardless of the Windows regional setting.
- The Diagnostics method name is no longer truncated.
- Loading a LAS file of a different well no longer keeps the previous well's tops, core data, and formation selection.
- The installer bundles the Intel MKL libraries that scipy needs. Without Anaconda on the PC, v1.6.0 could close with "Intel oneMKL FATAL ERROR: Cannot load mkl_intel_thread.2.dll" when a feature used scipy's linear algebra, for example permeability calibration from core.

### Calculation changes from v1.6.0

- A manual Rsh is used as entered; v1.6.0 replaced it with the estimate from the data.
- Auto Rw uses the Rwa method on clean, porous samples instead of raw NPHI and the lowest RT quartile. When no estimate exists (for example, shale-only data), the entered Rw is used with a warning.
- Calculate Rw/Rsh and VShale use the same GR baseline rule as the analysis (P5/P95 with at least 20 API separation).
- With several VShale methods selected, the VSH column holds the series used downstream.
- Curves in non-standard units (see LAS loading) are converted before the analysis.

On the reference test cases, results with default settings are unchanged from v1.6.0 except for shale-only data with auto Rw. Session files from v1.6.0 or older that store Rw ≤ 0.01 load with Rw in Auto mode.

## v1.6.0 (Build 20261009)

### New interface

- Replaced the left sidebar with a menu bar (File, Session, Analysis, Parameters, Corrections, View, Help) and a main toolbar.
- Added a read-only **Data Browser** tree that lists loaded LAS files, curves, formation tops, and core data.
- Moved every analysis setting into a modeless **Parameters** window with ten pages, so parameters stay open while you review results.
- Added a **Merge LAS Files** dialog in place of the sidebar merge block.
- Added a status bar with analysis progress, a QC status chip, and a stale-results indicator that appears after parameters change.
- Replaced informational pop-ups with non-blocking notification banners.
- The window layout, Data Browser visibility, and Parameters window position are remembered between launches.

### Design system

- Introduced a token-based design system (`themes/tokens.py`) that renders the Light and Dark stylesheets from one template.
- Replaced emoji and ad-hoc icons with a bundled, theme-aware Lucide icon set (ISC license); icons recolor immediately when the theme changes.
- Unified result tables (shared table model, consistent decimals and alignment) and themed all plot text, axes, and toolbars.
- Added automated design-system compliance tests (no hard-coded colors, inline styles, emoji, or informational modals).

### Fixes

- The Interactive log now opens fitted to the data's depth range instead of starting at depth 0, which had squeezed the curves into the bottom of the tracks.
- Per-file row counts in the Data Browser are correct after a LAS merge.
- The stale-results indicator is cleared when new data is loaded.
- Chart text is readable in the Dark theme.
- Cancelling or failing a merge preparation no longer leaves the merge state inconsistent.

### Build and packaging

- `pyqtgraph` and `PyOpenGL` are now listed in `requirements.txt` (required for the Interactive log engine).
- Build scripts default to the `mldl` Conda environment used for release builds.
- The installer now ships `LICENSE`, `LICENSE-APACHE-2.0`, `LICENSE-GPL-3.0`, and `NOTICE`.
- Added `run_petrophyter.bat` to launch the application from source with a double-click.

## v1.5.0 (Build 20260814)

### New features

- Added explicit, configurable neutron matrix responses for quartz, limestone, and dolomite; values persist in saved sessions.
- Added Waxman-Smits and Dual-Water results to saturation diagnostics, including visible no-root and solver-failure warnings.
- Added resilient rotating file logging initialized during application startup.

### Data integrity and calculation improvements

- Hardened LAS, core, and formation-top parsing with per-load state resets, clearer caller-visible errors, UTF-8-first decoding, depth-alias resolution, sorted depth data, and safer overlap handling.
- Hardened LAS merge/export validation, curve mnemonic and metadata handling, null replacement, and numeric dtype checks.
- Added validation for petrophysical formula parameters, safer PHIE selection and fallback behavior, and consistent external-series alignment for statistics.
- Made analysis-result storage, session files, and exported outputs safer through atomic state updates and atomic writes.

### UI and visualization improvements

- Restored supported analysis parameters more completely when loading sessions and added `set_params` helpers to parameter widgets.
- Displayed every available water-saturation curve in the composite log and improved summary handling for NaN and numeric values.
- Standardized theme APIs and refreshed diagnostic plots, histograms, QC charts, summary charts, and interactive logs immediately when the theme changes.
- Reset tabs and derived results reliably when source LAS/QC/analysis data changes or becomes unavailable.
- Sanitized detailed error messages shown in the UI while preserving actionable information in logs.

### Documentation and quality

- Reorganized the README into focused installation, user-guide, formats, calculations, visualization/export, session, troubleshooting, build, changelog, and licensing documentation.
- Removed committed bytecode and other local/sensitive artifacts from version control.
- Hardened Windows packaging by using the selected Conda interpreter, bundling forwarded MKL runtime dependencies, removing stale duplicate Qt MSVC runtimes, and supporting current-user registry installation.
- Added broad regression coverage for I/O, statistics, petrophysics, services, models, themes, QC, UI state, and build configuration.

## v1.4.0 (Build 20260113)

### New features

- Added Light and Dark themes, with the selection saved for future launches.
- Theme switching now updates the entire application immediately without a restart.

### Improvements

- Advanced Parameters groups expand and collapse smoothly and remain reliably visible.
- The About dialog is consistent with both themes, with improved license-table readability.
- Sidebar toolbar and helper buttons use more consistent colors.

### Bug fixes

- Fixed a crash when opening the About dialog.
- Fixed cases where Advanced Parameters appeared blank because of collapsed-container sizing.

## v1.3.0 (Build 20260109)

### New features

- Added a **New Project** button to reset application state.
- Added a Porosity Method selector for PHIE_DN, PHIE_D, PHIE_N, PHIE_S, and PHIE_GAS, with intelligent fallback logic.

### Improvements

- The Sw histogram in the Diagnostics tab uses density mode and supports multiple-method overlays.
- Added count labels to histogram bars in single-method display.
- Standardized histogram binning to a 0–1 range with 30 bins.

### Bug fixes

- Fixed **New Project** not clearing Top MD and Bottom MD spinboxes in the Petrophysics and Export tabs.
- Fixed `calculated_shale` being cleared before the Diagnostics tab could show its statistics.
- Added `reset_ui()` to every tab for complete project reset.

## v1.2 (Build 20260106)

### New features

- Added HCPV calculation.
- Added Waxman-Smits and Dual-Water saturation models.
- Added Net Pay, Net Reservoir, Gross, and Fraction Only HCPV display modes.

### Improvements

- Accelerated the PyQtGraph log engine with OpenGL.
- Throttled mouse events to approximately 30 FPS.
- Improved performance for datasets containing approximately 6,800 or more points.

### Bug fixes

- Fixed the HCPV visibility checkbox.
- Fixed a signal connection that caused mouse events to run six times redundantly.

## v1.1 (December 30, 2025)

### New features

- Interactive GPU-accelerated PyQtGraph log display
- JSON session save and load
- Gas correction for PHIE
- Asynchronous calculations to prevent UI freezes
- Unit-test foundation for development

### Improvements

- Six-track composite log with zoom, pan, and crosshair
- Draggable depth-region selection
- Formation-top overlay
- Analysis progress indicators

### Bug fixes

- Various UI and UX corrections
- Better responsiveness during long calculations

## v1.0 Final (December 23, 2025) — Initial Release

### Core features

- LAS loading with automatic curve detection
- Feet/meters depth-unit detection
- Multi-LAS merging with quality scoring
- Formation-top loading and overlays

### Calculations

- Vsh: GR Linear, Larionov Tertiary/Older, SP, and Neutron-Density
- Statistical P5/P95 and manual GR baselines
- Three shale-parameter estimation methods
- Density, Neutron, Sonic, and Neutron-Density porosity
- Archie, Indonesian, and Simandoux water saturation
- Hierarchical, Buckles, Clean Zone, and Statistical Swirr
- Timur and Wyllie-Rose permeability with core calibration
- Net-pay analysis with configurable cutoffs

### Visualization

- Matplotlib classic-log display
- Triple-combo preview
- Neutron-density and porosity-permeability crossplots

### Quality control

- Curve QC with quality scoring
- Bad-hole and data-gap detection
- IQR outlier detection

### Export

- Excel (`.xlsx`), CSV (`.csv`), and LAS (`.las`)

## Pre-Release History: Alpha to Beta

**Origins: October 2024 – January 2025**

Petrophyter began as an academic and research project intended to simplify petrophysics teaching and exploration workflows.

| Phase | Period | Platform | Description |
|---|---|---|---|
| **Concept & Research** | Oct 2024 | Jupyter Notebook | Initial idea development and algorithm prototypes with interactive cells |
| **Alpha** | Jan 2025 | Jupyter Notebook | Integrated notebook with interactive petrophysical-calculation widgets |
| **Beta** | Feb–Sep 2025 | Streamlit | Web prototype with improved UI and UX for user testing |
| **v1.0 Development** | Oct 2025 | PyQt6 | Migration to a desktop application |

Initial Notebook and Streamlit features included LAS loading and parsing, Vsh, porosity, Sw and permeability calculations, core-data validation, and result export.

## Migration to PyQt6 (October 2025)

The Streamlit-to-PyQt6 transition was driven by:

- Better performance for large LAS files and complex calculations.
- Straightforward compilation to a Windows executable for distribution.

> **Development note:** Advanced AI coding agents significantly accelerated the PyQt6 migration and later feature development by assisting with architecture design and debugging.
