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
- **Main toolbar.** Four controls on the left: **Open LAS File(s)…**, **Save Session…**, **Parameters Window**, and **Run Analysis**. On the right, a well indicator shows a status dot and a summary such as `Well name · 12,345 rows · 18 curves`, or `No data loaded`.
- **Data Browser.** A read-only tree on the left that summarizes the loaded well. See [What the Data Browser shows](#what-the-data-browser-shows).
- **Result tabs.** Six tabs in the central area: **Data QC**, **Petrophysics**, **Log Display**, **Diagnostics**, **Summary**, and **Export**. A notification banner appears above the tabs when there is something to report.
- **Status bar.** The left side shows the latest message. The right side holds the stale-results label, a progress bar, and the QC chip. See [Running the analysis](#running-the-analysis).

Parameters are not part of the main window. They live in the separate [Parameters window](#the-parameters-window).

### Typical workflow

1. Open a LAS file with **File → Open LAS File(s)…**.
2. Optionally load formation tops and core data from the **File** menu.
3. Review or adjust parameters in the Parameters window (**View → Parameters Window**).
4. Run the analysis with **Analysis → Run Analysis**.
5. Review the result tabs.
6. Save the results from the **Export** tab, and save your parameters with **Session → Save Session…**.

## Loading data

### Opening LAS files

Use **File → Open LAS File(s)…** (or the **Open LAS File(s)…** toolbar button) and select one or more `.las` files.

- **One file** loads directly. Curves are detected and mapped automatically, common NULL values such as `-999.25` and `-9999` are replaced with NaN, and the depth unit (feet or meters) is detected. If the depth unit is ambiguous, a warning banner appears.
- **Two or more files** open the [Merge LAS Files dialog](#merging-las-files) so you can combine them into one well dataset.

Loading a LAS file runs the data quality check, enables **Analysis → Run Analysis**, updates the well indicator and window title, and fills the Data Browser and the **Data QC** tab. **File → New Project** (`Ctrl+N`) clears all data and resets the window after a confirmation.

### Merging LAS files

When you select two or more files in **File → Open LAS File(s)…**, the **Merge LAS Files** dialog opens automatically. The dialog lists each file with its row count and top and bottom depth, and offers two settings:

| Setting | Range | Default | Meaning |
|---|---|---|---|
| **Step (ft)** | 0.1 to 1.0 | 0.5 | Depth step the files are resampled to |
| **Gap limit** | 1.0 to 50.0 | 5.0 | Largest gap that is filled by interpolation |

Click **Merge** to combine the files, or **Cancel** to close the dialog without merging. If you cancel, the files stay pending; reopen the dialog later with **File → Merge LAS Files…**. That menu item is enabled only while two or more files are waiting to be merged.

Merging selects the best curve for each type using quality scoring and interpolates short gaps. The merge warns, without stopping, if the files appear to come from different wells. After the merge:

- The Data Browser shows the sources as **n files merged**.
- The **Data QC** tab shows a **LAS Merge Report** that identifies the source file, coverage, QC score, and gaps filled for each curve.
- **File → Save Merged LAS…** becomes available so you can write the merged data to a new `.las` file.

### Opening formation tops

Use **File → Open Formation Tops…** and select a `.txt` or `.csv` file. Depths are converted to feet when the file is in meters. The formations appear in the Data Browser and in the **Analysis Scope** page of the Parameters window, where you can restrict the analysis to selected formations. On the **Log Display** tab, **Show Formation Tops** overlays them on the log.

### Opening core data

Use **File → Open Core Data…** and select a `.txt` or `.csv` file containing depth and at least porosity or permeability. Load the LAS file first. Core porosity given in percent is converted to a fraction, and core depths are matched to log depths. Loading core data enables the **Core Matching** page in the Parameters window, and core validation results appear in the **Diagnostics** tab.

See [Supported Data Formats](data-formats.md) for the complete column names, aliases, and unit rules for LAS, tops, and core files.

### What the Data Browser shows

The Data Browser is a read-only tree. You cannot edit values in it; use the menus and the Parameters window for that. It shows:

| Node | Contents |
|---|---|
| Well name | Depth range of the loaded data |
| **LAS files** | File count and row count per file; marked **not merged** while a merge is pending and **merged** afterward |
| **Curves** | Every curve with its unit; curves mapped to GR, RHOB, NPHI, DT, or RT carry that role tag |
| **Formation tops** | Formation names with top and bottom depth, or **Not loaded** |
| **Core data** | Sample count and depth unit, or **Not loaded** |
| **Results** | Calculated curves after a run; reads **out of date** when parameters changed since the last run |

Right-click a row for a context menu of related actions, such as **Open LAS File(s)…**, **Merge LAS Files…**, **Open Formation Tops…**, **Open Core Data…**, **Run Analysis**, and the matching Parameters pages. Double-click **Not loaded** on Formation tops or Core data to open the corresponding file dialog, or double-click a curve to open the **Curve Mapping** page. Before any data is loaded, the browser shows **No data loaded** with an **Open LAS File(s)…** link.

## Setting parameters

### The Parameters window

Open the Parameters window with **View → Parameters Window** (`Ctrl+P`) or the **Parameters Window** toolbar button. You can also jump straight to a page from the **Analysis**, **Parameters**, and **Corrections** menus.

The window is modeless: it stays open next to the main window, so you can change a parameter, press `F5` to run, and watch the result tabs update without closing it. Use the **Close** button to hide it. Petrophyter remembers its position, size, and last page between runs.

A page list on the left groups ten pages under three headings:

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

The **Rock Properties**, **Saturation Models**, and **Permeability** pages are divided into labeled sections. The shale, Rw/Rsh, and permeability sections have **Calculate** and **Apply** buttons that estimate values from the loaded data and let you accept them. The permeability estimate needs a completed analysis, and it uses core data when available. See [Calculation Methods](calculation-methods.md) for the equations, presets, and valid ranges.

### Stale results

Once an analysis has run, changing any parameter marks the results as out of date:

- the status bar shows **Parameters changed — press F5 to update results**; and
- the **Results** row in the Data Browser reads **out of date**.

The existing result tabs keep showing the previous run until you run the analysis again. Running the analysis, loading new data, or loading a session clears the indicator.

## Running the analysis

Choose **Analysis → Run Analysis** (`F5`) or click **Run Analysis** on the toolbar. The action is disabled until a LAS file is loaded and while an analysis is running. Because the `F5` shortcut is application-wide, it also works while the Parameters window has focus.

While the analysis runs:

- a progress bar appears in the status bar, and the status message shows the current step;
- result tabs refresh when the run completes; and
- a success banner reports the net pay, gross sand, and net-to-gross ratio, for example `Analysis complete — Net Pay 42.5 ft · Gross Sand 120.0 ft · N/G 35.4%`.

If the analysis fails, an **Analysis Error** dialog opens and the status bar shows **Analysis failed**.

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
- a success message when an analysis completes; and
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

### Export

Use **Download CSV** to save the full results table, or **Download Excel** to save a workbook with the results and a summary. The **Results Preview** below can be limited with **Top MD**, **Bottom MD**, and **Update View**. A success banner reports the saved path. Merged data is saved as LAS with **File → Save Merged LAS…**.

## Sessions

A session is a JSON file that stores your analysis parameters, so you can restore a configuration later.

- **Session → Save Session…** (`Ctrl+S`) writes the current parameters to a `.json` file. The same command is on the toolbar.
- **Session → Load Session…** (`Ctrl+Shift+O`) restores parameters from a saved file, updates the Parameters window to match, and clears the stale-results indicator.

Sessions store parameters and settings, not the LAS file itself. Load the LAS file again and press `F5` to reproduce the results. See [Session Management](session-management.md) for the complete list of saved parameters.

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
| `Ctrl+P` | Open the Parameters window | **View → Parameters Window** |
| `Ctrl+B` | Show or hide the Data Browser | **View → Data Browser** |

`F5`, `Ctrl+P`, and `Ctrl+B` work from any window of the application. Other menu items, including **Open Formation Tops…**, **Open Core Data…**, **Merge LAS Files…**, **Save Merged LAS…**, and **Exit**, have no shortcut. The Export tab buttons have no shortcut either.

## Troubleshooting

- **Plot Engine shows Interactive (requires pyqtgraph) and it cannot be selected.** pyqtgraph is missing from the Python environment. Launch Petrophyter with `run_petrophyter.bat`, which uses the `mldl` environment, or install it with `pip install pyqtgraph`. Meanwhile, choose **Classic (matplotlib)** under **Plot Engine**.
- **Run Analysis is greyed out.** Load a LAS file first. The action is also disabled while a run is in progress.
- **Core Matching is greyed out.** Load core data with **File → Open Core Data…** first.
- **Merge LAS Files… is greyed out.** It is enabled only while two or more LAS files from **Open LAS File(s)…** are waiting to be merged.
- **Numbers use a decimal point even though Windows uses a decimal comma.** This is intended. Petrophyter always shows and accepts numbers in English (US) format, with a period as the decimal separator and no thousands separator (for example, `4500.0 ft`), whatever the Windows regional setting.
- **Results look wrong.** Check the curve units, the curve mapping, and the shale parameters, and confirm that the depth unit is correct.

For these and other issues, see [Troubleshooting](troubleshooting.md).
