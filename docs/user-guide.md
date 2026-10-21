[Back to README](../README.md)

# User Guide

This guide walks through a complete Petrophyter session: loading data, setting parameters, running the analysis, reviewing results, and saving your work.

**Contents**

1. [Getting started](#getting-started)
2. [Loading data](#loading-data)
3. [Setting parameters](#setting-parameters)
4. [Running the analysis](#running-the-analysis)
5. [Reviewing results](#reviewing-results)
6. [Sessions](#sessions)
7. [Appearance](#appearance)
8. [Keyboard shortcuts](#keyboard-shortcuts)
9. [Troubleshooting](#troubleshooting)

## Getting started

### Launching the application

- **From source, double-click launcher:** run `run_petrophyter.bat` in the repository root. It uses the `mldl` conda environment, which includes pyqtgraph. If that environment is missing, it falls back to the Anaconda base environment, where the Interactive log engine is unavailable. Run `run_petrophyter.bat debug` to keep a console window open for error messages.
- **From source, command line:** activate the `mldl` conda environment and run `python main.py` from the repository root. See [Installation](installation.md) for dependencies.
- **From the installed app:** start Petrophyter from the Windows Start menu.

### Window tour

The main window has five areas:

- **Menu bar.** From left to right: **File**, **Session**, **Analysis**, **Parameters**, **Corrections**, **View**, and **Help**.
- **Main toolbar.** Four controls on the left: **Open LAS File(s)…**, **Save Session…**, **Parameters Window**, and **Run Analysis**, plus **Run All Wells** once two or more wells are loaded. On the right, a well selector appears once two or more wells are loaded, next to a well indicator that shows a status dot and a summary of the active well such as `Well name · 12,345 rows · 18 curves`, or `No data loaded`.
- **Data Browser.** A read-only tree on the left that summarizes the loaded well. See [What the Data Browser shows](#what-the-data-browser-shows).
- **Result tabs.** Nine tabs in the central area: **Data QC**, **Petrophysics**, **Log Display**, **Diagnostics**, **Rock Typing**, **Saturation-Height**, **Summary**, **Uncertainty**, and **Export**. A notification banner appears above the tabs when there is something to report.
- **Status bar.** The left side shows the latest message. The right side holds the stale-results label, a progress bar, and the QC chip. See [Running the analysis](#running-the-analysis).

Parameters are not part of the main window. They live in the separate [Parameters window](#the-parameters-window).

### Typical workflow

1. Open a LAS file with **File → Open LAS File(s)…**.
2. Optionally load formation tops and core data from the **File** menu.
3. Review or adjust parameters in the Parameters window (**View → Parameters Window**).
4. Run the analysis with **Analysis → Run Analysis**, or every well at once with **Analysis → Run All Wells**.
5. Optionally, with core porosity and permeability loaded, fit rock types in the **Rock Typing** tab and run again (see [Rock Typing](#rock-typing)).
6. Review the result tabs.
7. Optionally, give parameters distributions on **Parameters → Uncertainty** and run **Analysis → Run Uncertainty…** to get P90/P50/P10 (see [Uncertainty (Monte Carlo)](#uncertainty-monte-carlo)).
8. Optionally, with capillary pressure data loaded, fit and apply saturation-height curves, set a free water level and compute `SW_SHF` (see [Saturation-height](#saturation-height)).
9. Save the results from the **Export** tab, and save the project with **Session → Save Session…**.

## Loading data

### Opening LAS files

Use **File → Open LAS File(s)…** (or the **Open LAS File(s)…** toolbar button) and select one or more `.las` files.

- **One file** loads directly as one well. Curves are detected and mapped automatically, common NULL values such as `-999.25` and `-9999` are replaced with NaN, and the depth unit (feet or meters) is detected. If the depth unit is ambiguous, or a curve unit was converted or could not be recognized, a warning banner lists it.
- **Two or more files** are read in the background and then open the [Load Summary](#load-summary-several-files-several-wells), where you decide which files belong to the same well.

Loading a LAS file runs the data quality check for that well, enables **Analysis → Run Analysis**, updates the well indicator and window title, and fills the Data Browser and the **Data QC** tab. All notes from a load (depth-unit and curve-unit warnings from every file, merge warnings, and reloaded wells) are collected in one banner. **File → New Project** (`Ctrl+N`) removes all wells and resets the window after a confirmation.

### Load Summary: several files, several wells

When you select two or more files, the **Load LAS Files** dialog lists one row per file: file name, the well name from the header, the well key, depth range, depth step, number of curves, and notes (the number of unit or depth warnings, or the reason a file could not be read; hover for details). Files that could not be read are shown greyed out and are skipped.

The **Group** column proposes a grouping. Files whose header identifies the same well (same UWI, or same API number, or the same well name after ignoring case, spaces, hyphens, and underscores) share a group such as **Well 1: BKS-01**. A file with no usable well identifier gets a group of its own. Change a file's group in the combo box, or choose **Separate well**.

- Files in the same group are merged into one well. Files from different wells are never merged: if you put files with clearly different identities in one group, the load button is disabled and its tooltip names the conflicting files.
- **Merge step (ft)** (0.1 to 1.0, default 0.5) and **Merge gap limit** (1.0 to 50.0, default 5.0) are enabled only while some group has more than one file. They are the depth step the files are resampled to and the largest gap that is filled by interpolation.
- The button reads **Load N wells**. Each group becomes one well, and the last well loaded becomes the active well.

Merging selects the best curve for each type using quality scoring and interpolates short gaps. After a merge:

- The Data QC tab shows a **LAS Merge Report** that identifies the source file, coverage, QC score, and gaps filled for each curve.
- **File → Save Merged LAS…** is available while the active well is a merged well, so you can write its data to a new `.las` file.
- **File → Merge LAS Files…** opens the same multi-file open dialog as **Open LAS File(s)…**; merging happens per group in the Load Summary.

### Working with several wells

A project can hold any number of wells. Exactly one is the **active well**, and everything else in the window (the Parameters window curve mapping, analysis scope, the result tabs, the QC chip, the well indicator, and the window title) shows that well. The window title reads `Well name · 3 wells — Petrophyter` when more than one well is loaded.

- **Switch wells** by clicking a well (or anything under it) in the Data Browser, or by choosing it in the well selector in the toolbar.
- **Formation tops and core data belong to a well.** A file without a well column is attached to the active well; a file with a well column is shared out to the loaded wells it names through the [multi-well import dialog](#assigning-tops-and-core-data-to-several-wells). A newly loaded well never inherits another well's tops, core data, or formation selection. Switching back to a well restores its own.
- **Reloading a well** replaces it. A file whose well key matches a loaded well (for example `WELL:BKS-01`) replaces that well's data and results, keeps its tops, core data, and scope, and the banner reads **Reloaded BKS-01**.
- **Results and the out-of-date flag are per well.** If you switch wells while an analysis is running, the results are stored in the well that started the run. Changing a parameter marks out of date exactly the wells whose effective parameters changed: a project value affects every well that inherits it, a well value only that well. See [Stale results](#stale-results).
- **Summary and Export cover all wells.** With two or more wells the **Summary** tab adds a **Wells** table with a field total, and the **Export** tab can export **All wells**. See [Summary](#summary) and [Export](#export).
- **Remove a well** from the Data Browser context menu; Petrophyter asks for confirmation first.

### Opening formation tops

Use **File → Open Formation Tops…** and select a `.txt`, `.csv`, `.tsv`, or `.xlsx` file. Load a LAS file first. Without a well column the tops are attached to the active well. A file with a well column opens the [multi-well import dialog](#assigning-tops-and-core-data-to-several-wells) instead, so you decide which loaded well gets which rows.

- Depths are converted to feet when the file is in meters. If the file does not say which unit it uses, the depths are left as written and a warning banner suggests checking the unit; the same check applies to core data.
- If a formation has no bottom depth in the file, it runs to the next top. The last formation then runs to the bottom of the log.
- Rows that cannot be used (a missing or non-numeric depth, a blank formation name) are left out and counted in the load banner, with the first file line numbers and the reason.
- If the tops do not overlap the log depth range at all, a warning banner suggests checking the depth unit.

Each formation is also a **zone** that can carry its own parameters (see [Parameter scopes and zones](#parameter-scopes-and-zones)). The formations appear in the Data Browser and in the **Analysis Scope** page of the Parameters window, where you can restrict the analysis to selected formations. On the **Log Display** tab, **Show Formation Tops** overlays them on the log.

### Opening core data

Use **File → Open Core Data…** and select a `.txt`, `.csv`, `.tsv`, or `.xlsx` file containing depth and at least porosity or permeability. Load a LAS file first. Core data go to the active well; a file with a well column opens the multi-well import dialog. Core porosity given in percent is converted to a fraction, and core depths are matched to log depths. Loading core data enables the **Core Matching** page in the Parameters window, and core validation results appear in the **Diagnostics** tab. Excluded rows and warnings (for example, a TVD depth column) appear in the load banner. The **Rock Typing** tab needs porosity and permeability in the same row of the core file; core that has only one of them still feeds the core comparison but not rock typing.

See [Supported Data Formats](data-formats.md) for the complete column names, aliases, and unit rules for LAS, tops, and core files.

### Opening capillary pressure data

Use **File → Open Pc Data…** to load laboratory capillary pressure (Pc) curves (mercury injection, porous plate or centrifuge) for the active well, or **File → Open Pc Data (Multi-Well)…** for one file that holds the samples of several wells. Load a LAS file first. Neither entry has a keyboard shortcut. The file has one row per Pc point; the rows of one sample form one curve. Column names, units and the rows that are left out are in [Supported Data Formats](data-formats.md#capillary-pressure-data).

- **Pc unit.** The unit comes from the column header. When the header names none, Petrophyter asks for it; in the multi-well dialog the import stays disabled until you choose.
- **Fluid system.** A file without a system column asks for the system of the measurement (air-brine, mercury-air or oil-brine). The system sets the interfacial tension and contact angle used for the J-function.
- **Porosity and permeability.** Every sample needs both. When the file has none, or a cell is blank, the value is taken from the well's core data at the nearest core depth within 0.5 ft, so load core data first if the Pc file lacks them. A sample that still has neither is left out and counted in the load banner.
- **Several wells.** A file with a well column opens the same assignment dialog as tops and core data (see [Assigning tops and core data to several wells](#assigning-tops-and-core-data-to-several-wells)), with the Pc unit and system choices added.

Loading Pc data changes no log result and does not mark a well as out of date. The number of curves and points appears in the status bar.

### Assigning tops and core data to several wells

One tops or core file can hold the data of many wells. Load the LAS files of those wells first, then open the file from any of these places:

- **File → Open Formation Tops (Multi-Well)…** or **File → Open Core Data (Multi-Well)…**;
- the same two entries in the right-click menu of a well in the Data Browser; or
- **File → Open Formation Tops…** or **Open Core Data…**, which route a file with a well column to the same dialog.

The entries are disabled until a well is loaded. The dialog is titled **Assign formation tops** or **Assign core data**. Nothing changes until you press OK, and Cancel changes nothing.

1. **Check how the file was read.** The line under the title shows the file name, the delimiter or sheet, the encoding, and **decimal comma** when one was found. The column combos (Well, Formation, Top, Bottom for tops; Well, Depth, Porosity, Permeability, Grain density for core) show the columns that were detected. Choose another column, or **none**, and the file is read again.
2. **Set the depth unit** (**Auto**, **M**, or **FT**). With **Auto**, the label beside it reads **detected: metres** or **detected: feet**, or **not detected; choose M or FT** when the file does not say.
3. **Set the file options.** **Blank well cells continue the well above** is for tables exported from merged cells; it is switched on by itself when the blank cells look like merged cells. For tops, **Last formation: extend to log bottom** (the default) or **stop at its top** applies to a last formation without a bottom depth. For a workbook with several sheets, a **Sheet** combo appears. For core data whose depth column is TVD, check **Core depths are TVD; use them as measured depth** to accept them.
4. **Look at the preview.** The first five rows of the selected file well are shown, with the role of each mapped column above its header. Click a row of the well table to change the preview.
5. **Assign each file well.** The table has one row per well in the file (spellings such as `BKS-01`, `bks 01`, and `BKS_01` are one well). Its columns are the file well, row count, depth range in feet, the loaded well it **Match**es and **How** (UWI, API, name, or manual), what that well **Existing**ly holds, the **Action**, the **Porosity** scale (core only), and **Notes**. Change **Match** to pick another loaded well or **Skip**. A file well that fits several loaded wells starts as **Choose** and must be resolved.
6. **Choose the action.** A well with no data of this kind is simply assigned. A well that already has data offers **Keep existing** or **Replace**. The default is **Replace** when the existing data came from this same file (a reload), and **Keep existing** otherwise, so data is never overwritten unless you choose it. For core data, **Porosity** shows how the values of each well are read (**Percent** or **Fraction**); it is decided from the median of the well, and you can override it.
7. **Press the OK button**, which reads **Assign to N wells**. It stays disabled, and its tooltip lists the reasons, while the depth unit is undecided, a file well still needs a match, two file wells are assigned to one loaded well, TVD core depths are not accepted, or no well would receive data.

Warnings stay in the dialog instead of popping up: the notes under the options (rows without a well, reversed top and bottom, porosity warnings), the **Notes** cell of each row (hover for all of them: excluded rows with line numbers, a depth range that misses the log, a depth unit that fits the logs better, zone parameters that will no longer apply), and **Loaded wells not in this file**.

After OK, the chosen wells receive their data in one step; if any part cannot be built, nothing changes. Analysis-scope formations that the new tops lack are removed from the well's scope, and zone parameters whose zone no longer exists are kept and listed in the banner. Wells whose results depend on the new data are marked out of date. One banner reports how many wells received data, how many kept their existing data or were skipped, and every note.

### What the Data Browser shows

The Data Browser is a read-only tree. You cannot edit values in it; use the menus and the Parameters window for that. It shows:

| Node | Contents |
|---|---|
| Well name | Depth range of the loaded data; with several wells, one such node per well, and clicking a well makes it the active well |
| **LAS files** | File count and row count per file; marked **merged** when the well was merged from several files |
| **Curves** | Every curve with its unit; curves mapped to GR, RHOB, NPHI, DT, or RT carry that role tag |
| **Formation tops** | Formation names with top and bottom depth, or **Not loaded**; a zone with its own parameters is marked, and its tooltip lists them |
| **Core data** | Sample count and depth unit, or **Not loaded** |
| **Results** | Calculated curves after a run; reads **out of date** when parameters changed since the last run, or a count such as **2 warnings** with a warning dot when the last run had warnings (hover to read the first five) |

Right-click a row for a context menu of related actions, such as **Open LAS File(s)…**, **Merge LAS Files…**, **Open Formation Tops…**, **Open Core Data…**, **Run Analysis**, and the matching Parameters pages. Double-click **Not loaded** on Formation tops or Core data to open the corresponding file dialog, double-click a curve to open the **Curve Mapping** page, or double-click a formation to edit that zone's parameters for the well (the Parameters window opens on the **Zones** page at **Well** scope with the zone selected). Before any data is loaded, the browser shows **No data loaded** with an **Open LAS File(s)…** link.

## Setting parameters

### The Parameters window

Open the Parameters window with **View → Parameters Window** (`Ctrl+P`) or the **Parameters Window** toolbar button. You can also jump straight to a page from the **Analysis**, **Parameters**, and **Corrections** menus.

The window is modeless: it stays open next to the main window, so you can change a parameter, press `F5` to run, and watch the result tabs update without closing it. Use the **Close** button to hide it. Petrophyter remembers its position, size, and last page between runs.

A page list on the left groups the pages under four headings:

| Menu | Page | What it controls |
|---|---|---|
| **Analysis** | **Analysis Scope** | Whole Well or Per-Formation analysis, and which formations to include |
| **Analysis** | **Curve Mapping** | Which curve is used as GR, RHOB, NPHI, DT, and RT, and optionally TVD (used for formation temperature). The **Mapped curves** table below the choices shows each curve's unit from the file, its coverage (share of the well's samples with a value, in warning colour below 50 %), its range, and **Auto** (the curve detected from the curve names) or **Manual** (chosen by you; the tooltip names the curve detection would pick) |
| **Analysis** | **Uncertainty** | The Monte Carlo setup: a distribution for each of a, m, n, Rw, Rsh and the three cutoffs, the number of realisations, the seed, the sampling and the m–n correlation. Nothing is varied until you enable a distribution; see [Uncertainty (Monte Carlo)](#uncertainty-monte-carlo) |
| **Analysis** | **Core Matching** | Core depth unit (Auto, M, FT) and the maximum distance for matching core samples to log depths; enabled after core data is loaded |
| **Parameters** | **Porosity Method** | Primary PHIE method used downstream for Sw, permeability, and HCPV, and the **D-N combination** (Average or RMS) for PHIT and PHIE_DN |
| **Parameters** | **VShale** | GR baseline (statistical or custom GRmin and GRmax), the Vshale methods (Linear, Larionov Tertiary, Larionov Older) and the **Primary Vsh** |
| **Parameters** | **Cutoffs** | Net-pay cutoffs for Vsh, PHIE, and Sw |
| **Parameters** | **Rock Properties** | Matrix and fluid densities and sonic transit times, and shale parameters, including statistical estimation |
| **Parameters** | **Saturation Models** | Archie constants and lithology presets, the Sw methods to calculate and the primary Sw, and the Rw and Rsh values with a data-driven estimate |
| **Parameters** | **Permeability** | Wyllie-Rose coefficients C, P, and Q, with a calculate option, the Swirr estimation method, the **Primary permeability**, and the **Log permeability for rock types** |
| **Corrections** | **Gas Correction** | Enables the gas correction and sets the NPHI and RHOB factors, and the gas flag thresholds **Crossover min** and **Gas Vsh max** |
| **Scopes** | **Zones** | One row per zone and one column per zone parameter (a, m, n, Rw, Rsh, ρ matrix, and the three cutoffs) for the edited scope |

On the **Saturation Models** page, each of Rw and Rsh has an **Auto** checkbox. When it is checked, the value is estimated from the loaded data on every run and the field is disabled; clear it to enter a value yourself. Rw starts in manual mode and Rsh in auto mode. **Apply Calculated Values** fills both fields and switches both to manual.

The **Saturation Models** page also has a **Temperature** section; see [Formation temperature](#formation-temperature).

**D-N combination** sets how density and neutron porosity combine into PHIT and PHIE_DN: **Average** (the default, for liquid-filled rock) or **RMS** (the form of earlier versions). Gas-flagged samples always use RMS. With gas correction on, a sample is flagged as gas when PHID − PHIN is at least **Crossover min** (0.02 v/v by default) and Vsh is at most **Gas Vsh max** (0.40). Both can be set per well and per zone. **Primary Vsh** chooses which selected Vshale method gives the `VSH` curve used by every later step; **First selected** (the default) takes the first checked method. It is a project setting. See [Calculation Methods](calculation-methods.md) for the rules.

The **Rock Properties**, **Saturation Models**, and **Permeability** pages are divided into labeled sections. The shale, Rw/Rsh, and permeability sections have **Calculate** and **Apply** buttons that estimate values from the loaded data and let you accept them. The permeability estimate needs a completed analysis, and it uses core data when available. See [Calculation Methods](calculation-methods.md) for the equations, presets, and valid ranges.

**Calculate** for Rw and Rsh also says how many samples the estimate rests on, for example `42 water-leg samples for Rw; 15 shale samples for Rsh (Rw quality: water_leg)`, and shows the estimate's warnings (no water leg, no water/hydrocarbon contrast, a value at its limit) on the page. On the **Permeability** page the result line names its source, for example `Calculated: C=5000, P=4.00, Q=2.00 (core calibration in UPPER, 6 pairs)` or `(estimated from porosity, mean 0.165)`. Notes appear under it without removing the result or **Apply**: why a core calibration failed, how many plugs have a Buckles Swirr at its limit, and a warning when the current Swirr method or Buckles k differs from the one the fit used (the fitted permeability would then not reproduce the core). Q is held at the entered value during the fit.

**Primary permeability** chooses the permeability that feeds `FLOW_UNIT` and the permeability quality flags: **Timur** (the default), **Wyllie-Rose**, or **Rock type**. **Log permeability for rock types** (Timur or Wyllie-Rose) is the permeability that rock typing uses to place log samples. Both are project or well settings, not zone settings. **Rock type** is disabled, with the tooltip **Turn on rock typing in the Rock Typing tab to use this.**, until rock typing is on; if it is chosen and no definitions are applied, the run uses Timur for that well and warns. See [Permeability](calculation-methods.md#permeability).

### Parameter scopes and zones

Petrophysical parameters can differ between wells and between formations, so most of them can be set at four levels. The **scope bar** at the top of the Parameters window chooses which level you are editing:

- **Project** or **Well: <name>** (the active well), and
- **Zone:** **All zones** or one zone (formation) name.

The caption under the bar says what an edit affects, for example **Values for every well**, **UPPER in every well**, or **UPPER in BKS-01**. When a well is analysed, each value is taken from the most specific level that sets it:

**well · zone** › **project · zone** › **well** › **project**

So a zone value entered at project scope applies to that formation in every well, unless a well sets its own value for that formation. Samples outside every zone use the well and project values.

| Can be set per well and per zone | Per well only | Project only |
|---|---|---|
| a, m, n, lithology preset; matrix and shale ρ, Δt, NPHI; gas correction and its crossover and Vsh thresholds; D-N combination; GR clean/shale baseline; Rw and Rsh (and the Rsh reference temperature); Waxman-Smits and Dual-Water constants; permeability C, P, Q and Buckles k; Vsh, PHIE, and Sw cutoffs | fluid ρ and Δt; the temperature correction settings (including the datum depth and Waxman-Smits B from temperature); curve mapping and analysis scope (whole well or selected formations) | methods (VShale, primary Vsh, porosity, Sw methods, primary Sw), merge settings |

At any scope other than flat **Project**, each field has a small mode button beside it:

- **Auto** estimates the value from the data in that scope (available for Rw, Rsh, the GR baseline, the shale point (ρ, Δt, and NPHI shale), and the temperature gradient). A value set to Auto for a zone is estimated from that zone's samples only; when a zone has too few samples it falls back to the project-zone or well value, and the source says so. The shale point uses the shale selection settings of the **Rock Properties** page.
- **Manual** uses the value you type.
- **Inherit** removes the entry so the value comes from the next level down; inherited values are shown muted with a tooltip naming where they come from.
- **Copy to…** copies the entry to other wells or zones, and **Set as project default** moves it to the project.

**Calculate** for Rw and Rsh and for the shale point uses the edited scope: at **Well** scope with a zone selected, only that zone's samples are used. **Apply** writes the calculated values to the edited scope. The permeability **Calculate** also follows the edited scope: at **Well** scope with a zone selected it fits Wyllie-Rose C, P, and Q to that zone's core samples only (see [Permeability](calculation-methods.md#permeability)). A zone with fewer than five core pairs gives no result; the status text under the button reads, for example, `3 core pairs in UPPER (need 5). Switch the scope to Well: BKS-01 to calibrate on the whole well.` Petrophyter does not widen the fit by itself. Without core data, the coefficients are estimated from the mean PHIE of that zone.

A named **lithology preset** at a well or zone scope supplies a, m, and n at that scope. The values are not copied: a, m, and n show the source **<scope> (lithology preset)**, and changing the preset later changes them. An explicit a, m, or n at the same or a more specific scope still wins. Typing a value into a, m, or n while a preset is active switches the preset to **Custom** and keeps the three values as explicit entries. At flat **Project** scope the preset fills the a, m, and n fields as before.

The **Zones** page shows every zone of the active well (Well scope) or of all wells (Project scope) in one grid. Type a value to override, clear a cell to inherit again, or type `auto` in an Rw or Rsh cell. Values outside the valid range are flagged in the cell. After a run, the **Summary** tab lists the parameters each zone actually used and their source.

### Formation temperature

Resistivities are usually measured at a reference temperature, while formation temperature rises with depth. In the **Temperature** section of the **Saturation Models** page, check **Correct resistivities for formation temperature** to scale Rw to formation temperature with Arps' equation at every sample. The same correction applies to an auto Rsh, a manual Rsh that has a reference temperature, and the Dual-Water Rwb. The settings are per well:

- **Surface temp** and **Gradient.** With **Auto** checked (at **Well** scope), the gradient is computed from the LAS header (bottom-hole temperature and total depth) when available, and otherwise falls back to the entered value.
- **Datum depth.** The depth, on the log's depth axis, at which the surface temperature applies. Leave it at 0 for logs measured from ground level; use the KB height, or the water depth plus air gap offshore. The header gradient uses the same datum.
- **Rw ref. temp.** The temperature at which the entered Rw was measured.
- **Rsh ref. temp.** The temperature at which a manual Rsh was read. When it is **not set**, a manual Rsh is used as entered at every depth, and the note **Rw is corrected, Rsh is not** appears under the fields. An auto Rsh needs no entry: it is estimated from the shale resistivity brought to the Rw reference temperature. **Apply** on a calculated Rsh stores the Rw reference temperature with it when the correction is on, so the applied value stays corrected. Rsh ref. temp can also be set per zone, like Rsh.
- **Waxman-Smits B from temperature.** Calculates B from formation temperature and Rw at that temperature (Juhasz, 1981) instead of using the entered B. If the resistivity correction is off, Rw is used as entered and a warning says so.

**Which depth is used.** Temperature follows true vertical depth (TVD). Petrophyter uses, in this order: a TVD curve mapped on the **Curve Mapping** page (the **TVD** row; mnemonics `TVD`, `TVDKB`, `TVDRKB`, `TVDRT`, and `TVDBRT` are mapped automatically, and a curve in metres is converted to feet); the depth index itself when the LAS header says the log is on TVD; and otherwise measured depth, assuming a vertical well. If a TVD-like curve exists but is not mapped, or the header has an inclination entry, a warning says that a vertical well was assumed. A mapped curve that is not non-decreasing with depth, or that exceeds measured depth by more than 1 ft, is rejected with a note and measured depth is used.

Below the fields, a live readout shows the temperature at the top and bottom of the log with the depth source used, and the gradient implied by the header, for example `T at log top / bottom: 85 / 176 °F (MD (assumed vertical))`. The correction is off by default.

### Stale results

A well's results are out of date when its current effective parameters (including its formation tops) differ from the ones used for its last run. For the active well:

- the status bar shows **Parameters changed — press F5 to update results**; and
- the **Results** row in the Data Browser reads **out of date**, and the well's dot turns to the warning colour;
- the Summary and Diagnostics tabs still show the parameters used in the last run, with the hint **Current settings differ — Run to update**; and
- the Export tab's status line counts the well as out of date, and exporting it asks first (see [Export](#export)).

The existing result tabs keep showing the previous run until you run the analysis again. Changing a value back to what was used clears the flag, and so does running the analysis or loading new data.

**What changed, and Revert.** At the bottom of the Parameters window, a line lists what changed since the active well's last run, for example **2 changes since the last run: m: 2 → 2.25; UPPER SAND · rw: 0.05 → 0.06**; hover it for the full list (the stale-results label in the status bar has the same list in its tooltip). A zone is listed only where it does not simply follow the well. **Revert to last run** puts back the parameters that run used, after a confirmation: project values, project zone values, the well's own and zone values, curve mapping, and analysis scope. Project values are shared, so other wells get the restored project values too; the confirmation says so. Formation tops are data, not parameters: a tops change is listed but not reverted. After loading a session there is no last run yet (results are not saved), so the line appears after the first run.

## Running the analysis

Choose **Analysis → Run Analysis** (`F5`) or click **Run Analysis** on the toolbar to analyse the active well; it always runs, even when the results are up to date. The action is disabled until a LAS file is loaded and while the active well is running. Because the `F5` shortcut is application-wide, it also works while the Parameters window has focus.

**Analysis → Run All Wells** (`Ctrl+Shift+R`, also on the toolbar) analyses every loaded well that has no results or whose results are out of date, in the background (up to four at a time), each with its own effective parameters. Wells that are up to date are skipped. You can keep working, switch wells, or edit parameters meanwhile; results always go to the well they were computed for.

While the analysis runs:

- a progress bar appears in the status bar, and the status message shows the current step. For one well this is the stage, such as `Calculating water saturation...`. For several wells the bar shows the combined progress, and the message names the well and its stage, for example `Analysing 2 of 4 wells · BKS-01: Calculating Swirr...`;
- result tabs refresh when the run completes; and
- a success banner reports the net pay, gross sand, and net-to-gross ratio, for example `Analysis complete — Net Pay 42.5 ft · Gross Sand 120.0 ft · N/G 35.4%`. When the run had warnings (for example, Rw could not be estimated automatically, or part of the interval has no porosity), the banner is a warning, such as `Analysis complete with 2 warnings — …`, with a **Review** button that opens **Diagnostics → Run issues** for that well. Only warnings and errors count: notes (information), such as how many samples Swirr limited, keep the banner a success.

**Analysis → Stop analysis**, the **Stop analysis** toolbar button next to Run, or `Esc` while a run is active stops the run. Wells that finished keep their new results, wells that were not run keep their earlier state, and an info banner reports, for example, `Analysis stopped — 3 wells finished, 2 not run`. The action is disabled when nothing is running.

**Analysis → Run Uncertainty…** starts the Monte Carlo analysis and **Analysis → Stop Monte Carlo** stops it; both are described under [Uncertainty (Monte Carlo)](#uncertainty-monte-carlo). Neither has a keyboard shortcut.

If the analysis fails, an **Analysis Error** dialog opens and the status bar shows **Analysis failed**. When several wells run and only some fail, the others keep their results and one warning banner names each failed well and the reason; a failed well's dot in the Data Browser turns to the error colour. After a multi-well run the banner reads, for example, **Analysis complete for 4 wells (2 unchanged)**, and **· 1 with warnings · Review** when any well had warnings.

### While files are loading

While LAS files are read or merged, these actions are unavailable (greyed out; the status tip says "Unavailable while files are loading"):

- **New Project**, **Open LAS File(s)…**, **Open Formation Tops…**, **Open Core Data…** and their multi-well variants
- **Load Session…**
- **Merge LAS Files…**
- **Run Analysis** and **Run All Wells**

Save Session, export, the **View** and **Help** menus, the Parameters window, and theme switching stay available.

An analysis run does not lock the window. **Run Analysis** is disabled only while the active well is running, so you can switch to another well and run it. **New Project** and **Load Session…** cancel a run in progress; its results are discarded.

Closing the window while an analysis runs asks **Analysis is still running. Quit anyway?** (or **Files are still loading. Quit anyway?**, or **A session is still loading. Quit anyway?**). Choosing **Yes** quits without waiting for the result.

### QC chip

After a LAS file is loaded or merged, the status bar shows a QC chip with the overall data quality score, for example **QC 87/100**. It is hidden when no data is loaded.

| Score | State |
|---|---|
| 90 and above | Success |
| 70 to 89 | Warning |
| Below 70 | Error |

The same score appears as **Quality Score** on the **Data QC** tab.

### Notification banners

Non-blocking messages appear in a banner above the tabs. A banner has one of three kinds: success, warning, or info. Click the close button on the banner to dismiss it. Typical banners are:

- a warning when a LAS, tops, or core file has an ambiguous depth unit;
- a success message when an analysis completes, or a warning with **Review** when it completed with warnings;
- a warning naming the failed wells after **Run All Wells**, with **Review**;
- an info message when you stop an analysis;
- one banner with the notes from loading a session or a tops or core file (unmatched well names, missing files, depth coverage); and
- a success message with the file path after a CSV or Excel export.

The banner is cleared when a new analysis starts. A single failed run opens a dialog that you must dismiss; failed wells in a multi-well run, and runs with warnings, are shown in a warning banner with **Review**.

## Reviewing results

Before the first run, the tabs show a placeholder such as **Run analysis to view summary**. The **Data QC** tab fills in as soon as a LAS file is loaded.

### Data QC

Data quality for the loaded well: well name, depth range, total points, and quality score; available and missing required curves; per-curve statistics (valid percentage, minimum, maximum, mean, standard deviation, score); the formation tops table when tops are loaded; the declared NULL value; the **LAS Merge Report** after a merge; and a triple-combo preview of the logs.

### Petrophysics

Data-driven parameters used in the run (GR min, GR max, Rw, Rsh), a **Calculated Results Preview** table that you can restrict with **Top MD** and **Bottom MD** and **Update View**, and histograms of the main properties: Vshale, PHIE, Sw, and permeability. The Sw histogram shows the primary Sw (titled, for example, **Sw — Simandoux (primary)**); the selector above it lists every other Sw method present in the run. The permeability histogram has a selector over the permeability curves present (Timur, Wyllie-Rose). The results table shows Sw, every Sw method present, PHIT, and permeability; a curve the run did not produce is not shown.

### Log Display

A six-track composite log with a shared depth axis, a seventh **Rock Type** track once the results hold rock types, and a **Sw − Sw SHF** residual track once the results hold saturation-height Sw. Controls above the log:

- **Plot Engine** (under **Advanced** at the right of the controls; its tooltip names the engine in use): **Interactive (pyqtgraph)** or **Classic (matplotlib)**. When pyqtgraph is not installed, the first item reads **Interactive (requires pyqtgraph)**, cannot be selected, and **Classic (matplotlib)** is used.
- **Top Depth** and **Bottom Depth:** the visible depth range.
- **Show Formation Tops:** toggles the formation overlay in either engine; it is disabled, with a tooltip, when the well has no tops.
- **Zone shading:** shades each zone in the log tracks.
- **HCPV Show** and the HCPV mode: **Net Pay**, **Net Reservoir**, **Gross**, or **Fraction Only**. Both engines draw the track you choose. The controls are disabled, with a tooltip saying why, before the results hold HCPV curves, and the mode is disabled while **Show** is off.

The two engines differ as follows:

| Engine | Description |
|---|---|
| **Interactive (pyqtgraph)** | GPU-accelerated and the default when pyqtgraph is installed. Zoom and pan with the mouse wheel and drag, read depth and values at the crosshair cursor, and drag the depth region to select an interval. |
| **Classic (matplotlib)** | Static, export-quality plots with a navigation toolbar for pan, zoom, and save. |

Both engines draw the same tracks on the same ranges: GR (0–150 API) with Vsh (0–1) on a second axis, porosity from 0.5 to 0 v/v, Sw from 0 to 1 with the primary Sw solid (**Sw — <model> (primary)**) and the other Sw methods dashed, resistivity on a log axis (0.2–2000 ohm·m), and permeability on a log axis (0.01–10 000 mD). A Wyllie-Rose-only run shows the Wyllie-Rose permeability.

**Rock Type track.** When rock typing is on and applied, both engines add a seventh track of stepped bands, one colour per rock type. The colours come from one ordered ramp, dark for rock type 1 (lowest flow zone indicator) to light for the highest, and unassigned depths are grey. A band is faded and hatched where the rock type comes from the log rather than from core, or where the sample lies close to a boundary between two rock types (a margin below 0.05 in log10 FZI), so a solid band is a rock type measured on core. In the Interactive engine the readout under the log gives the rock type, the FZI and the source at the cursor depth. The track is absent when the run has no rock types.

**Saturation-height Sw.** When the results hold `SW_SHF`, both engines draw it on the Sw track as a dashed line labelled **Sw SHF**; with SHF Sw used for pay, **Sw SHF (pay)** is drawn dotted. The **Sw − Sw SHF** track, last in the log, shows `SW − SW_SHF` between −0.5 and 0.5: positive where the resistivity Sw is higher than the capillary model. In the Interactive engine the readout under the log also gives the height above the free water level (`HAFWL`, ft) at the cursor depth. Without saturation-height results the tracks are as before.

In the Interactive engine every track has axes with real values and units (for example **GR (API)** and **RT (ohm·m, log)**) and a legend. The readout under the log lists every curve at the cursor depth with its unit and wraps instead of cutting off. **Reset View** returns every track to its automatic range after you have zoomed or panned.

Below the log, the **Crossplots** section is collapsed by default; click it to expand a neutron-density crossplot and a porosity-permeability crossplot. Use its depth filter and **Update Crossplots**, or leave **Sync with Log Depth** checked to follow the log's depth range: zooming or panning either engine, or dragging the depth region in the Interactive engine, moves the crossplots to the same interval.

See [Visualization and Export](visualization-and-export.md) for more about plots and output formats.

### Diagnostics

**Run issues** comes first: the errors, warnings, and notes of the active well's last run, warnings first. Each row shows the severity, the zone when there is one, and a **Go to** button that opens the related Parameters page (Rw and Rsh, porosity, Swirr, or the analysis scope), selecting the Rw or Rsh field when the issue is about one of them, or the Diagnostics section concerned. A warning means something was substituted or fell back (an automatic Rw that could not be estimated, missing porosity, a Swirr method with no value), or that a count passed its limit; counts below their limit are notes (**Info**). It reads **No issues in the last run.** when the list is empty, and is hidden before the well has run.

Below it, cross-validation of the results: **Shale Parameters Cross-Validation** (current versus statistical values and deviation), **Porosity (PHIE) Cross-Validation** with a selectable method, **Water Saturation (Sw) Cross-Validation**, **Permeability (k) Validation**, and **Net Pay Validation**. When core data is loaded, **Core Data Validation** compares core porosity and permeability with the log-derived curves, with core points plotted on a depth track. The shale parameters are the ones **used in the last run**; when the current settings differ, a hint says **Current settings differ — Run to update**. Core samples beside a gap in the log are left out of the comparison and counted (`3 core samples beside a log gap excluded`). Warnings appear under each section when values look suspicious.

**Sw Solver and Porosity Checks** lists, for each Sw model and zone (or **Whole well**), the samples with no porosity (Sw set to 1), **Sw > 1.05** (Sw above 1.05 before the limit; a water leg's scatter just above 1 is not counted), at the lower bound, **BVH capped** (the total-porosity hydrocarbon volume of Waxman-Smits or Dual-Water limited to PHIE), **PHIE > PHIT**, and the Waxman-Smits and Dual-Water solver's no-root and failed counts. Columns fit their contents; scroll the table sideways when they do not fit. A cell above its limit (10 % of the zone's samples above 1.05, 5 % BVH capped or PHIE > PHIT, any solver failure) is in the warning colour, with a tooltip. Below the table, **Swirr method used** names the series that fed permeability and how many samples were raised to the 0.05 floor, limited to Sw, limited to 0.60, or taken from Buckles; a zone whose automatic GR baseline found no shale is listed with **zone has no shale; GRmax from the well**. Use the core-calibrated permeability coefficients from the **Permeability** page when the core comparison supports them.

### Rock Typing

The **Rock Typing** tab turns core porosity and permeability into rock types, which the analysis then carries to every well through the logs. It is optional: until you turn it on, no rock-type column or summary is added and the results are unchanged. The equations and their limits are in [Calculation Methods](calculation-methods.md#rock-typing-v180).

**Workflow**

1. Load core data with porosity and permeability in the same row (**File → Open Core Data…**). Without it the tab shows **No core data loaded. Rock typing needs core with porosity and permeability in the same row. Load core data to begin.**
2. Choose the **Method** (**FZI clustering**, or **Winland R35** with fixed port-size classes), the **Fit scope**, and the number of **Rock types**. **Suggested: n** next to the count is the count with the best silhouette; the count you set is the one that is used. **Winland R35** always gives five types.
3. Press **Fit**. The fit runs in the background with a progress bar and **Cancel**; nothing is changed until you apply. A fit that cannot be made says why in the status text (too few usable core rows, or a rock type with fewer than 5 samples), without a dialog.
4. Review the proposal: the **FZI** plot (histogram of log10 FZI with the boundaries, and a normal-probability plot), **Phi-K** (core porosity against permeability, coloured by rock type, with a dashed curve of constant FZI for each type), **RQI-phiz** (core points with a dashed unit-slope line at each type's FZI, and a solid free-slope fit per type whose slope and R² are listed below the plot; a slope near 1 and a high R² mean one hydraulic unit, and the fit is a diagnostic only, the representative FZI is unchanged), **R35** (with the 0.1, 0.5, 2 and 10 µm lines), and **Lorenz** (the Lorenz curve, the stratigraphic modified Lorenz plot, and a table of its flow-unit segments). Below them, **Rock type definitions** lists each type's samples, centre, FZI, boundaries and **k RMSE (log10)**, and **Core exclusions** counts every core row left out, by reason and well.
5. Press **Apply to project**. This is the only step that writes the definitions to the project; the status text reads **Applied to the project. Run Analysis (or Run All Wells) to use the rock types.**
6. Check **Enable rock typing in the analysis**. Without applied definitions it warns **No definitions applied yet: fit and apply rock types first.** Turning it on does not compute anything by itself.
7. Run the analysis (**Analysis → Run Analysis**, or **Run All Wells**). Applying or enabling changes the parameters of every well, so wells already run are marked out of date (see [Stale results](#stale-results)). Until the active well has been run, the line under the checkbox reads **Rock typing is on. Run the analysis (or Run All Wells) to compute rock types.** and a **Run All Wells** button sits below it. After the run it reads **Rock types are in the results: Summary → Rock types, Log Display → Rock Type track, and the exports.** If you turn rock typing off while the results still have rock types, it reads **Rock types are in the current results. The next run drops them.**

**Settings** in the left column: **Reservoir only (gross sand)** (default on), **Use core labels in the log** (default on), **Lorenz coefficient and SMLP**, **Add R35 column**, **Min PHIE** (0.02), and the **Overburden phi factor** and **Overburden k factor** (both 1.0). Core is used as loaded: overburden and Klinkenberg corrections are not applied unless you enter the factors, which multiply core porosity and permeability before the fit and apply from the next Fit.

**Fit scope.** **Project pooled** fits one set on the core of all wells, so a rock type number means the same rock in every well. **Per well** and **Per zone** also fit a set for each well or zone with at least 20 usable samples; the others use the pooled set, and the status text lists them. A **Set** selector then switches the plots and tables between the sets, and a note says that rock type numbers are not comparable between wells. The scope is a project setting; one scope is active at a time.

**Editing the definitions.** In the definitions table, the **FZI** and the lower and upper boundaries can be edited. Boundaries must increase from rock type 1 upward and FZI must be positive. Counts and **k RMSE** are recomputed from the core at once, and the table shows **edited manually**. Edits never refit. On definitions that are already applied, an edit takes effect in the project immediately and marks the wells out of date; on a proposal that is not applied yet, it changes the proposal.

**Banners.** **Core data changed since this fit; refit.** appears when the core of any well differs from the core the definitions were fitted on, and **Fit settings changed since this fit; refit.** when the overburden factors differ. Petrophyter never refits by itself. The other settings (reservoir only, core labels, Lorenz, R35 column, Min PHIE) change the applied definitions at once and need no refit.

**Results for the active well.** After a run, **Pay per rock type (active well)** lists samples, gross sand, net reservoir, net pay, N/G pay, average PHIE and Sw, HCPV, geometric-mean permeability, FZI and the share of core-labelled samples per rock type, with an **unassigned** row; below it, the counts of samples by source (`core`, `log`, `x_vsh`, `x_phie`, `x_perm`, `x_nan`), near-boundary and outside-range samples, and the core-versus-log agreement. A well without core shows a warning that its rock types are log-derived with the project definitions: treat those as a surrogate, because they inherit the shape of the Timur or Wyllie-Rose permeability (see the caveat in [Calculation Methods](calculation-methods.md#rock-typing-v180)).

### Saturation-height

The **Saturation-Height** tab (after Rock Typing) turns capillary pressure data into a second water saturation, `SW_SHF`, from the height of each sample above the free water level. It is optional: until you turn on **Compute saturation-height Sw on Run**, no column is added and results, exports and saved sessions are the same as in version 1.9.0. `SW` stays the resistivity result. The equations and their limits are in [Calculation Methods](calculation-methods.md#saturation-height-modelling-v1100).

**Workflow**

1. Load Pc data (**File → Open Pc Data…**, see [Opening capillary pressure data](#opening-capillary-pressure-data)). Without it **Fit** is disabled and its tooltip says to import capillary pressure data first.
2. **Confirm the fluids and tensions** in the left column: the water, oil and gas densities (g/cc) and the interfacial tension times cosine of the contact angle (dyne/cm) of each laboratory and reservoir system. The values are typical defaults, marked **Defaults, confirm** until you edit them or press **Confirm**; check them for your field. The water must be denser than the hydrocarbon.
3. Under **Fit settings**, choose the **Model** (**Power law** or **Brooks-Corey**), the **Weighting** (each sample or each point equally), the **Minimum Pc (psi)** at or below which points are left out as closure, the **Rock type source**, the **Permeability** and **Porosity** columns used for J, and the **Fallback** for a rock type without its own curve (**None** or **Pooled curve (All)**).
4. Press **Fit**. It fits one curve per rock type to the core Pc data of all wells, in the background with **Cancel**; nothing is changed until you apply. The J-Sw, Sw versus height and FWL profile plots, and the **Fits per rock type** table (parameters with standard errors, samples, points, RMSE, basis and status), show the proposal. A fit with too little data says so in the status column. With rock typing on, one fit is made per rock type. With rock typing off, or when the rock types are fitted per zone, there is one fit for every sample, shown as **All**, and a note says so.
5. Press **Apply fit**. This is the only step that writes the fits to the project; wells already run are marked out of date.
6. Set the **Contacts (active well)**. The table has a **Default** row and one row per zone; a zone without its own value uses the default, and a sample with no contact gets no `SW_SHF`. For each row give the **FWL (ft)**, the **Fluid** (oil or gas) and optionally the **Water density (g/cc)** (blank = the project value). Enter the free water level, not the oil-water contact: the contact sits higher by the entry height of the rock, and using it as the FWL makes Sw too high in the transition zone. The **Datum** is **TVD** (on the log's TVD axis) or **TVDSS**; a TVDSS contact needs the **KB (ft)** typed in. The LAS header values appear only as a hint under the fields and are never filled in. A TVDSS contact with no KB is not used (the status reads **KB required for TVDSS**). Heights follow the mapped TVD curve, else a TVD depth index, else measured depth assumed vertical, as for [formation temperature](#formation-temperature).
7. Optionally press **Estimate FWL**. It scans candidate contacts for the one where `SW_SHF` best matches the log `SW`, and reports it, or reports that it is not identifiable (for example when the misfit hardly changes with the contact). Nothing changes until you press **Accept**, which stores the contacts for the well and marks it out of date.
8. Check **Compute saturation-height Sw on Run**. A line under it says what is still missing (**Fit and apply a curve to compute saturation-height Sw.**, **Set a free water level for the well below, then accept it.**, or **Run Analysis (or Run All Wells) to update the saturation-height Sw.** with a **Run All Wells** button).
9. Run the analysis (`F5`, or **Run All Wells**).
10. Read the **Misfit (active well, last run)** table: for the well, each zone and each rock type, the samples, bias (mean `SW − SW_SHF`), RMSE, MAE and R², with the basis. They are taken over net reservoir samples above the free water level. A large bias means the contact, the fit or the resistivity inputs need a second look. The same numbers are on the **SHF** sheet of the Excel export.

**Fit from logs.** After a run, **Fit from logs** fits the curve to the log `Sw` above the contacts instead of to core Pc. It is not independent of the resistivity `Sw` (it smooths `SW` along a hydrostatic profile), so it is a cross-check only: the fits are shown as **log-derived**, and **Use SHF Sw for pay and HCPV** is disabled for any well that uses one.

**Use SHF Sw for pay and HCPV.** By default `SW_SHF` is a cross-check and pay, N/G, average Sw and HCPV use `SW`. When you check **Use SHF Sw for pay and HCPV** (core Pc fits only), the pay flags, net pay, N/G, average Sw and HCPV use `SW_PAY`, the saturation-height Sw where there is one and `SW` elsewhere; the counts are listed in the run's notes. In a Monte Carlo run, the samples that use the saturation-height Sw keep it in every realisation (see [Uncertainty (Monte Carlo)](#uncertainty-monte-carlo)).

**What to keep in mind.** The permeability used for J can come from the resistivity Sw (through Swirr), and the log rock types are classified from the same permeability, so the residual `SW − SW_SHF` can look smaller than the real disagreement. Core permeability is the independent choice. There is no pressure-gradient free water level and no closure correction beyond the minimum Pc.

### Summary

Results at a glance: the analysis scope (whole well or the selected formations), **Net Pay Analysis** (gross sand, net reservoir, net pay, N/G reservoir, N/G pay, and the average PHIE and Vsh in pay weighted by thickness and the average Sw weighted by pore volume), **HCPV Summary** (gross, net reservoir, and net pay), a **Thickness Summary** chart, and **Used in last run**: the Vsh, PHIE, and Sw cutoffs that run used (not the current settings). When the zones used different cutoffs, the cell reads, for example, **varies by zone (0.25–0.40)**. Before a run it shows **—** and **Run to see the parameters used**; when the current settings differ from the run, a hint says **Current settings differ — Run to update**.

When the active well has formation tops, a **Zones** table gives one row per zone: top and bottom, gross, net, N/G, average PHIE and Sw, HCPV, and the a, m, n, Rw, and cutoffs used; hover a parameter to see its source (for example **well·zone** or **auto (fallback: well)**).

A zone that ends up with no gross, no net reservoir, or no net pay is marked so you can check whether that is expected. Hover the zone, top, or bottom cell for the reason:

| Zone result | Row | Meaning |
|---|---|---|
| No valid samples | Muted | VSH, PHIE, or Sw is missing over the whole zone. |
| No gross | Muted | No sample passes the Vsh cutoff: shale by this cutoff, as expected for a seal. |
| No net reservoir | Warning colour | Gross exists but no sample passes the PHIE cutoff. Tight rock, or check the cutoff and the porosity inputs. |
| No net pay | Muted | Net reservoir exists but no sample passes the Sw cutoff. May be water-bearing; check the Rw inputs if pay is expected. |
| Zone has no shale | Info colour | The zone's automatic GR baseline found no shale, so GRmax comes from the well. |

These marks are diagnostic, not errors, and no dialog opens. On the Parameters window **Zones** page, the cutoff cell that caused the result (Vsh, PHIE, or Sw) is marked the same way and carries the same tooltip, at **Well** scope for the active well while its results are up to date.

With two or more wells, a **Wells** table lists every well with its status, pay summary, and **Issues** (the number of warnings, or the error of a failed well), plus a **Field total** row (thickness and HCPV summed, PHIE and Vsh weighted by net pay, Sw weighted by pore volume). The Field total counts wells whose results are current or out of date and leaves out wells whose latest run failed; its status reads, for example, **4 wells (1 out of date)**. Check **Show zones per well** to add each well's zones. Click a well's row to make it the active well.

When the run has rock types, a **Rock types** group sits below the Zones table. For the active well it lists, per rock type and for the unassigned samples, the gross sand, net reservoir and net pay thickness, N/G pay, the average PHIE and Sw in pay, the HCPV, the geometric-mean permeability, the FZI and the share of core-labelled samples; with two or more wells it also lists each well's rock types. A **Field total** per rock type is shown only for a **Project pooled** fit, where a rock type means the same rock in every well; for a per-well or per-zone fit the table reads **mixed definitions** and shows no field total. The group is hidden while rock typing is off and no run has rock types. When rock typing is on but the active well has not been run with it, the group shows a hint instead: **Rock typing is on. Run the analysis for this well (or Run All Wells) to see pay and HCPV per rock type here.**, or, when no definitions are applied, **Rock typing is on but no definitions are applied. Fit and apply them in the Rock Typing tab.**

### Uncertainty (Monte Carlo)

The **Uncertainty** tab turns the deterministic HCPV and net pay into a range. You give some parameters a distribution, Petrophyter re-evaluates the saturation and pay stage many times with values drawn from those distributions, and the tab reports **P90 / P50 / P10** for the field, each well and each zone, plus a histogram, an exceedance curve and a tornado. It is optional: until you enable a distribution nothing is computed, and the deterministic results, the Summary and the exports are never changed by it. The equations are in [Calculation Methods](calculation-methods.md#uncertainty-monte-carlo-v190).

**Setting up the distributions.** Open **Parameters → Uncertainty** in the Parameters window (page group **Analysis**). Each row is one parameter: **a**, **m**, **n**, **Rw (ohm·m)**, **Rsh (ohm·m)**, **Vsh cutoff**, **PHIE cutoff** and **Sw cutoff**. For a row:

- check the box on the left to vary that parameter (the other controls stay disabled until you do);
- **Kind** is **Triangular** (Low, Mid and High), **Normal** (Mid is the mean offset, Sd the standard deviation; draws are truncated at three standard deviations) or **Uniform** (Low and High);
- **Mode** is **Relative** or **Additive**. A relative offset is a percentage of the value (Low `-10 %` and High `+10 %` give values between 0.9 and 1.1 times the value); an additive offset is in the unit of the parameter (m `-0.15` to `+0.15`). Rw, Rsh and a start as relative, m, n and the three cutoffs as additive.

Low, Mid, High and Sd are offsets from the value the analysis resolved for each well and zone, not absolute values. The same draw is applied to every well and zone in a realisation, on top of whatever scopes, lithology presets or automatic estimates gave each of them its own value, so the wells move together (the widest field spread). A line under the table repeats this and names what is not varied: **porosity, shale point, GR baseline**. A tornado without them understates the total uncertainty.

**Suggested ranges** fills every row with a triangular range and its default mode: a ±10 %, m ±0.15, n ±0.20, Rw and Rsh −20 % to +25 %, Vsh cutoff ±0.05, PHIE cutoff ±0.02, Sw cutoff ±0.05. It overwrites the values you typed but enables nothing; use it as a starting point and edit the ranges to what you know about the field.

Below the table:

- **N** is the number of realisations, from 50 to 5000 (300 by default). Use more for smoother percentiles.
- **Seed** and **New seed**: the same seed, N, sampling and ranges always give the same numbers, so a result can be reproduced; **New seed** draws a different random seed.
- **Sampling** is **Latin hypercube** (the default; it covers each range evenly, so percentiles settle with fewer realisations) or **Random**.
- **rho(m, n)** is the rank correlation between the m and n draws, from −0.95 to 0.95. The default 0 draws them independently; a non-zero value needs both m and n enabled, otherwise the page reports it and the run is refused.

Edits are stored in the project at once and mark the session as changed, but they never make a well out of date. A message under the controls explains an invalid setting (for example a triangular range whose Low is above its High). Nothing enabled is a normal starting state, not an error.

**Running and stopping.** Choose **Analysis → Run Uncertainty…** (or press **Run Monte Carlo** on the Uncertainty tab; there is no keyboard shortcut). It uses the current parameters of every well that has data and an RT curve, whether or not the wells have been run. The status bar shows `Monte Carlo 230/300`, and you can keep working. **Analysis → Stop Monte Carlo** (or **Cancel** on the tab) stops the run and keeps no partial result. The action is greyed out, with a tooltip saying why, when no distribution is enabled, when a Monte Carlo run is already going, or while an analysis run is in progress; starting it with no well that has an RT curve shows a warning banner instead. The run works on its own copy of the data and parameters. **New Project** or **Load Session…** cancels a Monte Carlo run and discards its result. Closing the window while it runs asks **Monte Carlo is still running. Quit anyway?** If it fails, a **Monte Carlo failed** dialog gives the reason.

**Reading the tab.** Choose the **Metric**: HCPV net pay, HCPV net reservoir, Net pay, Avg PHIE in pay or Avg Sw in pay. HCPV and thickness are in ft (HCPV is a column thickness per unit area, not a volume). The header line gives the seed, N, sampling and the run time.

- **Table.** One row for the **Field**, then each well with its zones indented, with **P90**, **P50**, **P10**, **Mean**, **Deterministic**, **N valid** (realisations where the metric is defined) and **P(zero)** (the share of realisations with no net pay). The convention is the industry one: **P90 is the low case, the value exceeded with 90 % probability; P10 is the high case**, so P90 ≤ P50 ≤ P10. **Deterministic** is the same calculation with every offset at zero, on the current parameters. The Field row is computed from the per-realisation field totals, not by adding well percentiles, so it can differ from the sum of the wells' P90 values. Select a row to draw it.
- **Histogram and exceedance.** Bars of the realisations for the selected row, with P90, P50 and P10 as vertical lines and the deterministic value dashed, and the exceedance curve (the percent of realisations at or above each value) on the right axis.
- **Tornado.** For HCPV net pay and Net pay, one bar per enabled parameter: the output when only that parameter is at the 10th and at the 90th percentile of its own distribution and everything else is at its base value, sorted by swing, with the deterministic value as the centre line. The table below gives the input values, the outputs, the swing and a **Rank corr. (field)** column, the rank correlation of the parameter's draws with the field value of the selected metric over all realisations. The tornado changes one parameter at a time, so it misses interactions; the rank correlation, which uses the whole sample, is the cross-check.
- **Diagnostics.** The share of draws clipped to the physical limits of each parameter, the share of realisations with no net pay for each well, any well left out and why (for example no RT curve), and warnings. **Percentiles not converged at N = ...; increase N** appears when P90, P50 or P10 of the field HCPV net pay or net pay differ by more than 2 % of the P50 between the first and the second half of the realisations; raise N and run again.

**Out of date.** An **Out of date** chip appears when the result no longer matches the project: a well's parameters changed (or it was removed), a well with an RT curve was added, or the distributions, N, seed or sampling changed. The result stays readable. When a well's deterministic run is out of date, a note says that the **Deterministic** column uses the current parameters while the Summary tab is out of date. Run Uncertainty again to refresh.

**Reproducing a result.** Results are not saved in a session; the configuration is. Open the session, run Uncertainty with the same seed, and the numbers are identical. The Excel export (below) records the seed, N and sampling next to the statistics.

### Export

Choose the **Scope**: **Active well** or, with two or more wells, **All wells**. Use **Download CSV** to save the full results table, **Download Excel** to save a workbook with the results and a summary, or **Download LAS** to save the results as LAS. For **All wells**, the CSV has a `WELL` column, the workbook has a **Summary** sheet with the field total, a **Zones** sheet, and one results sheet per analysed well, and LAS asks for a folder and writes one file per well with its own header. The **Results Preview** title says what it shows, for example **Preview — showing 500 of 4,812 rows (well Alpha)**; the preview always shows the active well, and with **All wells** a note reads, for example, **Export contains 3 wells, 12,340 rows**. **Depth interval** is an explicit choice: **All depths**, or **Selected interval (1000–1019 ft)** using **Top MD** and **Bottom MD**. The choice applies to the preview and to every export (CSV, Excel and LAS, for one well or all wells), and is written in the provenance as **Depth interval**. The Excel **Summary** sheet still describes the whole run. A success banner reports the saved path.

With a Monte Carlo result, the workbook also gets an **Uncertainty** and a **Tornado** sheet (see [Visualization and Export](visualization-and-export.md#uncertainty-in-the-exports-v190)); CSV and LAS are unchanged.

With saturation-height modelling run, the results (CSV, Excel and LAS) carry `SW_SHF`, `HAFWL` and `SW_SHF_RESID`, plus `SW_PAY` when SHF Sw is used for pay, and the workbook adds an **SHF** sheet (see [Visualization and Export](visualization-and-export.md#saturation-height-in-the-exports-v1100)). Without it, nothing is added.

With rock typing on, the results (CSV, and the well sheets and the combined sheet of the workbook) carry the extra columns `RQI`, `FZI`, `ROCK_TYPE`, `ROCK_TYPE_SOURCE` and `RT_MARGIN`, plus `PERM_RT` and `R35` when those are turned on. The workbook adds a **Rock Types** sheet with one row per well and rock type, an **Unassigned** row per well, and **Field total** rows when the definitions are project-wide. **Export definitions** (shown once definitions are applied) saves the rock-type definitions table to CSV. LAS writes `ROCK_TYPE`, `FZI`, `RQI`, `RT_MARGIN` and `PERM_RT` as numeric curves; the text column `ROCK_TYPE_SOURCE` is left out, like the other text columns. Without rock typing, nothing is added.

A status line above the preview reads **Ready — results current**, or for example **2 wells out of date · 1 latest run failed**. Before exporting wells that are out of date or whose latest run failed, a dialog offers **Run out-of-date wells** (runs them and returns to the Export tab; it does not export), **Export last successful results** (the status is written in the file), or **Cancel**. Failed wells without earlier results are left out and named. Every export records the Petrophyter version, the run time, the status, and the parameter hash: a **Provenance** sheet in Excel, an `~OTHER` section in LAS, and a `<name>.provenance.txt` file next to a CSV. See [Data Formats](data-formats.md#exported-files). Merged data is saved as LAS with **File → Save Merged LAS…**.

## Sessions

A session is a JSON file that stores the project, so you can reopen it later.

- **Session → Save Session…** (`Ctrl+S`) writes the project to the current session file, and asks for a file the first time; **Session → Save Session As…** (`Ctrl+Shift+S`) always asks. The session holds the project parameters and project zone parameters, and for every well its LAS file paths, curve mapping, analysis scope, well and well-zone parameters, and the paths of its tops and core files. **Save Session** is also on the toolbar.
- **Session → Load Session…** (`Ctrl+Shift+O`) replaces the loaded wells with the saved ones: it reads the LAS, tops, and core files again from their saved paths, restores every parameter scope, and re-activates the saved active well. A well whose files are missing is skipped; one banner lists everything that could not be restored. The wells are rebuilt in the background with the progress in the status bar (`Restoring 3 of 10: BKS-03`); **New Project** or another **Load Session…** cancels it.

An asterisk at the start of the window title (`*BKS-01 — Petrophyter`) means there are unsaved changes: loaded or removed wells, tops, core data, merges, parameters, or curve mapping. Running an analysis does not count. Closing the window, loading a session, or starting a new project with unsaved changes asks **Save**, **Discard**, or **Cancel**; **Cancel**, or cancelling the Save's file dialog, keeps everything as it is.

Sessions store paths, not the data or the results. Restored wells need a run: press **Run All Wells** to reproduce the results. A session saved by an older version (format 1.x) holds parameters only; loading it applies them to the project and the active well, and leaves the loaded wells in place. The rock-type definitions and settings are saved with the session, so a loaded session keeps them. So are the Monte Carlo distributions, N, seed and sampling, but not the Monte Carlo result: run **Analysis → Run Uncertainty…** again and the seed reproduces it. A session that holds saturation-height content (the settings, applied fits, Pc data or contacts) is saved as format 2.4; Pc files are read again from their saved paths. See [Session Management](session-management.md) for the complete list of saved parameters.

## Appearance

- **Theme:** choose **View → Theme → Light** or **View → Theme → Dark**. The whole application, including icons, plots, the Parameters window, and dialogs, switches immediately. Petrophyter remembers your choice.
- **Data Browser:** choose **View → Data Browser** (`Ctrl+B`) to hide or show the panel and give the result tabs more room. A check mark indicates that it is visible.
- **Layout:** Petrophyter remembers the window geometry, splitter position and Data Browser visibility between runs. It always opens on the **Data QC** tab.

## Keyboard shortcuts

| Shortcut | Action | Menu path |
|---|---|---|
| `Ctrl+N` | Start a new project | **File → New Project** |
| `Ctrl+O` | Open LAS file(s) | **File → Open LAS File(s)…** |
| `Ctrl+S` | Save session | **Session → Save Session…** |
| `Ctrl+Shift+S` | Save session as | **Session → Save Session As…** |
| `Ctrl+Shift+O` | Load session | **Session → Load Session…** |
| `F5` | Run analysis | **Analysis → Run Analysis** |
| `Ctrl+Shift+R` | Run all wells | **Analysis → Run All Wells** |
| `Esc` | Stop the running analysis (only while a run is active) | **Analysis → Stop analysis** |
| `Ctrl+P` | Open the Parameters window | **View → Parameters Window** |
| `Ctrl+B` | Show or hide the Data Browser | **View → Data Browser** |

`F5`, `Ctrl+P`, and `Ctrl+B` work from any window of the application. Other menu items, including **Open Formation Tops…**, **Open Core Data…**, **Merge LAS Files…**, **Save Merged LAS…**, and **Exit**, have no shortcut. The Export tab buttons have no shortcut either.

## Troubleshooting

- **Plot Engine shows Interactive (requires pyqtgraph) and it cannot be selected.** pyqtgraph is missing from the Python environment. Launch Petrophyter with `run_petrophyter.bat`, which uses the `mldl` environment, or install it with `pip install pyqtgraph`. Meanwhile, choose **Classic (matplotlib)** under **Advanced → Plot Engine**.
- **Run Analysis is greyed out.** Load a LAS file first. The action is also disabled while a run is in progress.
- **Run Uncertainty… is greyed out.** Enable at least one distribution on **Parameters → Uncertainty**; hover the action for the reason. It is also disabled while a Monte Carlo run or an analysis run is in progress. If a warning says no well has an RT curve, map an RT curve in **Curve Mapping** and load a well that has one.
- **A well is missing from the Uncertainty tab.** It could not be evaluated (no RT curve, no effective porosity, or the analysis failed). The Diagnostics list on the tab names it and gives the reason; the field row leaves it out.
- **The Uncertainty tab shows Out of date.** A well's parameters, the distributions, N, the seed or the sampling changed since the run. Press **Analysis → Run Uncertainty…** again.
- **Percentiles not converged at N = …; increase N.** The field P90, P50 or P10 moved by more than 2 % of the P50 between the first and the second half of the realisations. Raise **N** on **Parameters → Uncertainty** (up to 5000) and run again.
- **Saturation-height Sw is blank.** `SW_SHF` is empty where the sample has no contact (set and accept a free water level for the well or its zone), the fit is missing or not applied (press **Fit**, then **Apply fit**), the permeability or porosity chosen for J is missing, or the contact is TVDSS and no KB is typed. The notes of the run count the samples in each class. Also check that **Compute saturation-height Sw on Run** is on and that the well was run after the last change.
- **Use SHF Sw for pay and HCPV is greyed out.** A fit in use for the well is log-derived. Fit from core Pc data and apply it, or keep the resistivity Sw for pay.
- **Fit is greyed out on the Saturation-Height tab.** No well has Pc data. Load it with **File → Open Pc Data…**.
- **Core Matching is greyed out.** Load core data with **File → Open Core Data…** first.
- **Run All Wells skips a well.** Its results are up to date. Use **Run Analysis** (`F5`) to rerun the active well anyway.
- **In the import dialog, a file well has no match.** The name in the well column does not match the header of any loaded well. Pick the loaded well by hand in the **Match** column, check the spelling or the UWI, or load the well's LAS file first. The **Assign to N wells** button stays disabled while a file well that fits several loaded wells is unresolved; hover it to see why.
- **A file I opened was not merged.** Only files placed in the same group in the Load Summary are merged. Files with different well identities are loaded as separate wells; change the group only if the header names differ but the files belong to the same well.
- **Numbers use a decimal point even though Windows uses a decimal comma.** This is intended. Petrophyter always shows and accepts numbers in English (US) format, with a period as the decimal separator and no thousands separator (for example, `4500.0 ft`), whatever the Windows regional setting.
- **Results look wrong.** Check the curve units, the curve mapping, and the shale parameters, and confirm that the depth unit is correct.

For these and other issues, see [Troubleshooting](troubleshooting.md).
