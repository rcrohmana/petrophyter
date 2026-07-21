[Back to README](../README.md)

# User Guide

## Quick Start

1. **Load LAS File:** Click **Load LAS File** and select your well log file.
2. **Set Parameters:** Adjust shale parameters, matrix density, and cutoffs in the sidebar.
3. **Run Analysis:** Click **Run Analysis** to calculate all properties.
4. **Review Results:** Navigate through the tabs to view results.
5. **Export:** Open the Export tab to save results.

## Loading Data

### LAS files

- Load one or multiple LAS files.
- Curves are detected and mapped automatically.
- Common NULL values such as `-999.25` and `-9999` are handled.
- Depth units in feet or meters are detected automatically *(v1.0)*.

### Multi-LAS merge *(v1.0)*

- Intelligent curve selection with quality scoring
- Configurable merge step from 0.1 to 1.0 ft
- Gap interpolation with a configurable limit from 1.0 to 50.0 ft
- Same-well validation
- Detailed merge report identifying curve sources

#### Workflow

1. Click **Load LAS Files** and select multiple files.
2. Review curve QC and select the best curves for each type.
3. Configure the merge step and gap limit.
4. Click **Merge** to combine the files.
5. Download the merged LAS or continue with analysis.

### Formation tops *(v1.0)*

- Load formation tops from TXT or CSV.
- Depth units are converted automatically.
- Formations can be overlaid on the log display.

See [Supported Data Formats](data-formats.md) for complete column and unit requirements.

### Core data

- Load TXT or CSV core data with flexible column detection.
- Core depths are matched and interpolated automatically.
- Porosity can be converted automatically from percent to fraction.

#### Validation workflow

1. Load the LAS file first.
2. Click **Load Core Data** in the sidebar.
3. Select a TXT or CSV file containing depth and at least porosity or permeability.
4. View validation results in the Diagnostics tab.
5. Use core-calibrated permeability coefficients when appropriate.

## Session Save and Load *(v1.1)*

1. Configure the analysis parameters.
2. Click **Save Session** to export them to JSON.
3. Click **Load Session** later to restore the settings.

See [Session Management](session-management.md) for the complete list of saved parameters.

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+O` | Open LAS file |
| `Ctrl+R` | Run analysis |
| `Ctrl+E` | Export results |
| `Ctrl+Q` | Quit application |
