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
- **Result tabs.** Six tabs in the central area: **Data QC**, **Petrophysics**, **Log Display**, **Diagnostics**, **Summary**, and **Export**. A notification banner appears above the tabs when there is something to report.
- **Status bar.** The left side shows the latest message. The right side holds the stale-results label, a progress bar, and the QC chip. See [Running the analysis](#running-the-analysis).

Parameters are not part of the main window. They live in the separate [Parameters window](#the-parameters-window).

### Typical workflow

1. Open a LAS file with **File → Open LAS File(s)…**.
2. Optionally load formation tops and core data from the **File** menu.
3. Review or adjust parameters in the Parameters window (**View → Parameters Window**).
4. Run the analysis with **Analysis → Run Analysis**, or every well at once with **Analysis → Run All Wells**.
5. Review the result tabs.
6. Save the results from the **Export** tab, and save the project with **Session → Save Session…**.

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
- **Formation tops and core data belong to a well.** A file without a well column is attached to the active well; a file with a well column is shared out to every loaded well it names (see [Opening formation tops](#opening-formation-tops)). A newly loaded well never inherits another well's tops, core data, or formation selection. Switching back to a well restores its own.
- **Reloading a well** replaces it. A file whose well key matches a loaded well (for example `WELL:BKS-01`) replaces that well's data and results, keeps its tops, core data, and scope, and the banner reads **Reloaded BKS-01**.
- **Results and the out-of-date flag are per well.** If you switch wells while an analysis is running, the results are stored in the well that started the run. Changing a parameter marks out of date exactly the wells whose effective parameters changed: a project value affects every well that inherits it, a well value only that well. See [Stale results](#stale-results).
- **Summary and Export cover all wells.** With two or more wells the **Summary** tab adds a **Wells** table with a field total, and the **Export** tab can export **All wells**. See [Summary](#summary) and [Export](#export).
- **Remove a well** from the Data Browser context menu; Petrophyter asks for confirmation first.

### Opening formation tops

Use **File → Open Formation Tops…** and select a `.txt` or `.csv` file. Load a LAS file first. Without a well column the tops are attached to the active well. With a well column (`Well`, `Well Name`, `UWI`, or `API`) each well's rows go to the loaded well they name, matched on UWI or API when the column holds them and on the well name otherwise (case, spaces, hyphens, and underscores are ignored). One banner lists the wells that received tops, the names in the file that match no loaded well, and any well whose tops lie outside its log depth range. Depths are converted to feet when the file is in meters. If the tops do not overlap the log depth range at all, a warning banner suggests checking the depth unit; the same check applies to core data. Each formation is also a **zone** that can carry its own parameters (see [Parameter scopes and zones](#parameter-scopes-and-zones)). The formations appear in the Data Browser and in the **Analysis Scope** page of the Parameters window, where you can restrict the analysis to selected formations. On the **Log Display** tab, **Show Formation Tops** overlays them on the log.

### Opening core data

Use **File → Open Core Data…** and select a `.txt` or `.csv` file containing depth and at least porosity or permeability. Load a LAS file first. As with tops, core data go to the active well, or, when the file has a well column, each well's samples go to the matching loaded well. Core porosity given in percent is converted to a fraction, and core depths are matched to log depths. Loading core data enables the **Core Matching** page in the Parameters window, and core validation results appear in the **Diagnostics** tab.

See [Supported Data Formats](data-formats.md) for the complete column names, aliases, and unit rules for LAS, tops, and core files.

### What the Data Browser shows

The Data Browser is a read-only tree. You cannot edit values in it; use the menus and the Parameters window for that. It shows:

| Node | Contents |
|---|---|
| Well name | Depth range of the loaded data; with several wells, one such node per well, and clicking a well makes it the active well |
| **LAS files** | File count and row count per file; marked **merged** when the well was merged from several files |
| **Curves** | Every curve with its unit; curves mapped to GR, RHOB, NPHI, DT, or RT carry that role tag |
| **Formation tops** | Formation names with top and bottom depth, or **Not loaded**; a zone with its own parameters is marked, and its tooltip lists them |
| **Core data** | Sample count and depth unit, or **Not loaded** |
| **Results** | Calculated curves after a run; reads **out of date** when parameters changed since the last run |

Right-click a row for a context menu of related actions, such as **Open LAS File(s)…**, **Merge LAS Files…**, **Open Formation Tops…**, **Open Core Data…**, **Run Analysis**, and the matching Parameters pages. Double-click **Not loaded** on Formation tops or Core data to open the corresponding file dialog, double-click a curve to open the **Curve Mapping** page, or double-click a formation to edit that zone's parameters for the well (the Parameters window opens on the **Zones** page at **Well** scope with the zone selected). Before any data is loaded, the browser shows **No data loaded** with an **Open LAS File(s)…** link.

## Setting parameters

### The Parameters window

Open the Parameters window with **View → Parameters Window** (`Ctrl+P`) or the **Parameters Window** toolbar button. You can also jump straight to a page from the **Analysis**, **Parameters**, and **Corrections** menus.

The window is modeless: it stays open next to the main window, so you can change a parameter, press `F5` to run, and watch the result tabs update without closing it. Use the **Close** button to hide it. Petrophyter remembers its position, size, and last page between runs.

A page list on the left groups the pages under four headings:

| Menu | Page | What it controls |
|---|---|---|
| **Analysis** | **Analysis Scope** | Whole Well or Per-Formation analysis, and which formations to include |
| **Analysis** | **Curve Mapping** | Which curve is used as GR, RHOB, NPHI, DT, and RT |
| **Analysis** | **Core Matching** | Core depth unit (Auto, M, FT) and the maximum distance for matching core samples to log depths; enabled after core data is loaded |
| **Parameters** | **Porosity Method** | Primary PHIE method used downstream for Sw, permeability, and HCPV |
| **Parameters** | **VShale** | GR baseline (statistical or custom GRmin and GRmax) and the Vshale methods: Linear, Larionov Tertiary, Larionov Older |
| **Parameters** | **Cutoffs** | Net-pay cutoffs for Vsh, PHIE, and Sw |
| **Parameters** | **Rock Properties** | Matrix and fluid densities and sonic transit times, and shale parameters, including statistical estimation |
| **Parameters** | **Saturation Models** | Archie constants and lithology presets, the Sw methods to calculate and the primary Sw, and the Rw and Rsh values with a data-driven estimate |
| **Parameters** | **Permeability** | Wyllie-Rose coefficients C, P, and Q, with a calculate option, and the Swirr estimation method |
| **Corrections** | **Gas Correction** | Enables the gas correction and sets the NPHI and RHOB factors |
| **Scopes** | **Zones** | One row per zone and one column per zone parameter (a, m, n, Rw, Rsh, ρ matrix, and the three cutoffs) for the edited scope |

On the **Saturation Models** page, each of Rw and Rsh has an **Auto** checkbox. When it is checked, the value is estimated from the loaded data on every run and the field is disabled; clear it to enter a value yourself. Rw starts in manual mode and Rsh in auto mode. **Apply Calculated Values** fills both fields and switches both to manual.

The **Saturation Models** page also has a **Temperature** section; see [Formation temperature](#formation-temperature).

The **Rock Properties**, **Saturation Models**, and **Permeability** pages are divided into labeled sections. The shale, Rw/Rsh, and permeability sections have **Calculate** and **Apply** buttons that estimate values from the loaded data and let you accept them. The permeability estimate needs a completed analysis, and it uses core data when available. See [Calculation Methods](calculation-methods.md) for the equations, presets, and valid ranges.

### Parameter scopes and zones

Petrophysical parameters can differ between wells and between formations, so most of them can be set at four levels. The **scope bar** at the top of the Parameters window chooses which level you are editing:

- **Project** or **Well: <name>** (the active well), and
- **Zone:** **All zones** or one zone (formation) name.

The caption under the bar says what an edit affects, for example **Values for every well**, **UPPER in every well**, or **UPPER in BKS-01**. When a well is analysed, each value is taken from the most specific level that sets it:

**well · zone** › **project · zone** › **well** › **project**

So a zone value entered at project scope applies to that formation in every well, unless a well sets its own value for that formation. Samples outside every zone use the well and project values.

| Can be set per well and per zone | Per well only | Project only |
|---|---|---|
| a, m, n, lithology preset; matrix and shale ρ, Δt, NPHI; gas correction; GR clean/shale baseline; Rw and Rsh; Waxman-Smits and Dual-Water constants; permeability C, P, Q and Buckles k; Vsh, PHIE, and Sw cutoffs | fluid ρ and Δt; the temperature correction settings; curve mapping and analysis scope (whole well or selected formations) | methods (VShale, porosity, Sw methods, primary Sw), merge settings |

At any scope other than flat **Project**, each field has a small mode button beside it:

- **Auto** estimates the value from the data in that scope (available for Rw, Rsh, the GR baseline, the shale point (ρ, Δt, and NPHI shale), and the temperature gradient). A value set to Auto for a zone is estimated from that zone's samples only; when a zone has too few samples it falls back to the project-zone or well value, and the source says so. The shale point uses the shale selection settings of the **Rock Properties** page.
- **Manual** uses the value you type.
- **Inherit** removes the entry so the value comes from the next level down; inherited values are shown muted with a tooltip naming where they come from.
- **Copy to…** copies the entry to other wells or zones, and **Set as project default** moves it to the project.

**Calculate** for Rw and Rsh and for the shale point uses the edited scope: at **Well** scope with a zone selected, only that zone's samples are used. **Apply** writes the calculated values to the edited scope. The lithology preset at a well or zone scope writes explicit a, m, and n entries for that scope.

The **Zones** page shows every zone of the active well (Well scope) or of all wells (Project scope) in one grid. Type a value to override, clear a cell to inherit again, or type `auto` in an Rw or Rsh cell. Values outside the valid range are flagged in the cell. After a run, the **Summary** tab lists the parameters each zone actually used and their source.

### Formation temperature

Rw is usually measured at a reference temperature, while formation temperature rises with depth. In the **Temperature** section of the **Saturation Models** page, check **Correct Rw for formation temperature** to scale Rw to formation temperature with Arps' equation at every sample. Enter the **Surface temp**, the **Gradient**, and the **Rw ref. temp** (the temperature at which the entered Rw was measured). With **Auto** checked (at **Well** scope), the gradient is computed from the LAS header (bottom-hole temperature and total depth) when available, and otherwise falls back to the entered value. These settings are per well. Temperature is computed from measured depth, and Rsh is not temperature-corrected.

### Stale results

A well's results are out of date when its current effective parameters (including its formation tops) differ from the ones used for its last run. For the active well:

- the status bar shows **Parameters changed — press F5 to update results**; and
- the **Results** row in the Data Browser reads **out of date**, and the well's dot turns to the warning colour.

The existing result tabs keep showing the previous run until you run the analysis again. Changing a value back to what was used clears the flag, and so does running the analysis or loading new data.

## Running the analysis

Choose **Analysis → Run Analysis** (`F5`) or click **Run Analysis** on the toolbar to analyse the active well; it always runs, even when the results are up to date. The action is disabled until a LAS file is loaded and while an analysis is running. Because the `F5` shortcut is application-wide, it also works while the Parameters window has focus.

**Analysis → Run All Wells** (`Ctrl+Shift+R`, also on the toolbar) analyses every loaded well that has no results or whose results are out of date, in the background (up to four at a time), each with its own effective parameters. Wells that are up to date are skipped. You can keep working, switch wells, or edit parameters meanwhile; results always go to the well they were computed for.

While the analysis runs:

- a progress bar appears in the status bar, and the status message shows the current step;
- result tabs refresh when the run completes; and
- a success banner reports the net pay, gross sand, and net-to-gross ratio, for example `Analysis complete — Net Pay 42.5 ft · Gross Sand 120.0 ft · N/G 35.4%`.

If the analysis fails, an **Analysis Error** dialog opens and the status bar shows **Analysis failed**. When several wells run and only some fail, the others keep their results and one warning banner names each failed well and the reason; a failed well's dot in the Data Browser turns to the error colour. After a multi-well run the banner reads, for example, **Analysis complete for 4 wells (2 unchanged)**.

### While files are loading

While LAS files are read or merged, these actions are unavailable (greyed out; the status tip says "Unavailable while files are loading"):

- **New Project**, **Open LAS File(s)…**, **Open Formation Tops…**, **Open Core Data…** and their multi-well variants
- **Load Session…**
- **Merge LAS Files…**
- **Run Analysis** and **Run All Wells**

Save Session, export, the **View** and **Help** menus, the Parameters window, and theme switching stay available.

An analysis run does not lock the window. **Run Analysis** is disabled only while the active well is running, so you can switch to another well and run it. **New Project** and **Load Session…** cancel a run in progress; its results are discarded.

Closing the window while an analysis runs asks **Analysis is still running. Quit anyway?** (or **Files are still loading. Quit anyway?**). Choosing **Yes** quits without waiting for the result.

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
- a success message when an analysis completes;
- a warning naming the failed wells after **Run All Wells**;
- one banner with the notes from loading a session or a tops or core file (unmatched well names, missing files, depth coverage); and
- a success message with the file path after a CSV or Excel export.

The banner is cleared when a new analysis starts. Errors are never shown as banners; they open a dialog that you must dismiss.

## Reviewing results

Before the first run, the tabs show a placeholder such as **Run analysis to view summary**. The **Data QC** tab fills in as soon as a LAS file is loaded.

### Data QC

Data quality for the loaded well: well name, depth range, total points, and quality score; available and missing required curves; per-curve statistics (valid percentage, minimum, maximum, mean, standard deviation, score); the formation tops table when tops are loaded; the declared NULL value; the **LAS Merge Report** after a merge; and a triple-combo preview of the logs.

### Petrophysics

Data-driven parameters used in the run (GR min, GR max, Rw, Rsh), a **Calculated Results Preview** table that you can restrict with **Top MD** and **Bottom MD** and **Update View**, and histograms of the main properties: Vshale, PHIE, Sw, and permeability.

### Log Display

A six-track composite log with a shared depth axis. Controls above the log:

- **Plot Engine:** **Interactive (pyqtgraph)** or **Classic (matplotlib)**. When pyqtgraph is not installed, the first item reads **Interactive (requires pyqtgraph)**, cannot be selected, and **Classic (matplotlib)** is used.
- **Top Depth** and **Bottom Depth:** the visible depth range.
- **Show Formation Tops:** toggles the formation overlay.
- **Zone shading:** shades each zone in the log tracks.
- **HCPV Show** and the HCPV mode: **Net Pay**, **Net Reservoir**, **Gross**, or **Fraction Only**.

The two engines differ as follows:

| Engine | Description |
|---|---|
| **Interactive (pyqtgraph)** | GPU-accelerated and the default when pyqtgraph is installed. Zoom and pan with the mouse wheel and drag, read depth and values at the crosshair cursor, and drag the depth region to select an interval. |
| **Classic (matplotlib)** | Static, export-quality plots with a navigation toolbar for pan, zoom, and save. |

In the Interactive engine, **Reset View** returns every track to its automatic range after you have zoomed or panned.

Below the log, the **Crossplots** section is collapsed by default; click it to expand a neutron-density crossplot and a porosity-permeability crossplot. Use its depth filter and **Update Crossplots**, or leave **Sync with Log Depth** checked to follow the log's depth range.

See [Visualization and Export](visualization-and-export.md) for more about plots and output formats.

### Diagnostics

Cross-validation of the results: **Shale Parameters Cross-Validation** (current versus statistical values and deviation), **Porosity (PHIE) Cross-Validation** with a selectable method, **Water Saturation (Sw) Cross-Validation**, **Permeability (k) Validation**, and **Net Pay Validation**. When core data is loaded, **Core Data Validation** compares core porosity and permeability with the log-derived curves, with core points plotted on a depth track. Warnings appear under each section when values look suspicious. Use the core-calibrated permeability coefficients from the **Permeability** page when the core comparison supports them.

### Summary

Results at a glance: the analysis scope (whole well or the selected formations), **Net Pay Analysis** (gross sand, net reservoir, net pay, N/G reservoir, N/G pay, and the average PHIE, Sw, and Vsh in pay), **HCPV Summary** (gross, net reservoir, and net pay), a **Thickness Summary** chart, and the **Cutoff Parameters Used** (Vsh, PHIE, and Sw).

When the active well has formation tops, a **Zones** table gives one row per zone: top and bottom, gross, net, N/G, average PHIE and Sw, HCPV, and the a, m, n, Rw, and cutoffs used; hover a parameter to see its source (for example **well·zone** or **auto (fallback: well)**).

With two or more wells, a **Wells** table lists every well with its status and pay summary, plus a **Field total** row (thickness and HCPV summed, averages weighted by net pay). Check **Show zones per well** to add each well's zones. Click a well's row to make it the active well.

### Export

Choose the **Scope**: **Active well** or, with two or more wells, **All wells**. Use **Download CSV** to save the full results table, **Download Excel** to save a workbook with the results and a summary, or **Download LAS** to save the results as LAS. For **All wells**, the CSV has a `WELL` column, the workbook has a **Summary** sheet with the field total, a **Zones** sheet, and one results sheet per analysed well, and LAS asks for a folder and writes one file per well with its own header. The **Results Preview** below can be limited with **Top MD**, **Bottom MD**, and **Update View**. A success banner reports the saved path. Merged data is saved as LAS with **File → Save Merged LAS…**.

## Sessions

A session is a JSON file that stores the project, so you can reopen it later.

- **Session → Save Session…** (`Ctrl+S`) writes the project to a `.json` file: the project parameters and project zone parameters, and for every well its LAS file paths, curve mapping, analysis scope, well and well-zone parameters, and the paths of its tops and core files. The same command is on the toolbar.
- **Session → Load Session…** (`Ctrl+Shift+O`) replaces the loaded wells with the saved ones: it reads the LAS, tops, and core files again from their saved paths, restores every parameter scope, and re-activates the saved active well. A well whose files are missing is skipped; one banner lists everything that could not be restored.

Sessions store paths, not the data or the results. Restored wells need a run: press **Run All Wells** to reproduce the results. A session saved by an older version (format 1.x) holds parameters only; loading it applies them to the project and the active well, and leaves the loaded wells in place. See [Session Management](session-management.md) for the complete list of saved parameters.

## Appearance

- **Theme:** choose **View → Theme → Light** or **View → Theme → Dark**. The whole application, including icons, plots, the Parameters window, and dialogs, switches immediately. Petrophyter remembers your choice.
- **Data Browser:** choose **View → Data Browser** (`Ctrl+B`) to hide or show the panel and give the result tabs more room. A check mark indicates that it is visible.
- **Layout:** Petrophyter remembers the window geometry, splitter position, Data Browser visibility, and active tab between runs.

## Keyboard shortcuts

| Shortcut | Action | Menu path |
|---|---|---|
| `Ctrl+N` | Start a new project | **File → New Project** |
| `Ctrl+O` | Open LAS file(s) | **File → Open LAS File(s)…** |
| `Ctrl+S` | Save session | **Session → Save Session…** |
| `Ctrl+Shift+O` | Load session | **Session → Load Session…** |
| `F5` | Run analysis | **Analysis → Run Analysis** |
| `Ctrl+Shift+R` | Run all wells | **Analysis → Run All Wells** |
| `Ctrl+P` | Open the Parameters window | **View → Parameters Window** |
| `Ctrl+B` | Show or hide the Data Browser | **View → Data Browser** |

`F5`, `Ctrl+P`, and `Ctrl+B` work from any window of the application. Other menu items, including **Open Formation Tops…**, **Open Core Data…**, **Merge LAS Files…**, **Save Merged LAS…**, and **Exit**, have no shortcut. The Export tab buttons have no shortcut either.

## Troubleshooting

- **Plot Engine shows Interactive (requires pyqtgraph) and it cannot be selected.** pyqtgraph is missing from the Python environment. Launch Petrophyter with `run_petrophyter.bat`, which uses the `mldl` environment, or install it with `pip install pyqtgraph`. Meanwhile, choose **Classic (matplotlib)** under **Plot Engine**.
- **Run Analysis is greyed out.** Load a LAS file first. The action is also disabled while a run is in progress.
- **Core Matching is greyed out.** Load core data with **File → Open Core Data…** first.
- **Run All Wells skips a well.** Its results are up to date. Use **Run Analysis** (`F5`) to rerun the active well anyway.
- **A tops or core file reports unmatched wells.** The names in its well column do not match the header of any loaded well. Check the spelling or the UWI, or load the well's LAS file first.
- **A file I opened was not merged.** Only files placed in the same group in the Load Summary are merged. Files with different well identities are loaded as separate wells; change the group only if the header names differ but the files belong to the same well.
- **Numbers use a decimal point even though Windows uses a decimal comma.** This is intended. Petrophyter always shows and accepts numbers in English (US) format, with a period as the decimal separator and no thousands separator (for example, `4500.0 ft`), whatever the Windows regional setting.
- **Results look wrong.** Check the curve units, the curve mapping, and the shale parameters, and confirm that the depth unit is correct.

For these and other issues, see [Troubleshooting](troubleshooting.md).
