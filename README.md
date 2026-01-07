# Petrophyter

**Desktop Petrophysics Application** - A comprehensive tool for well log analysis and petrophysical calculations.

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![PyQt6](https://img.shields.io/badge/PyQt6-6.5+-green.svg)
![License](https://img.shields.io/badge/License-Apache--2.0%20OR%20GPL--3.0-blue.svg)
![Version](https://img.shields.io/badge/Version-1.2_(Build_20260106)-orange.svg)

![alt text](<icons/Screenshot 1.2.png>)

## Overview

Petrophyter PyQt is a desktop application for petrophysical analysis, providing tools for:
- LAS file loading and intelligent merging
- Shale volume calculation (GR Linear, Larionov, Clavier, Stieber, SP, Neutron-Density)
- Porosity estimation (Density, Neutron, Sonic, Neutron-Density) with gas correction *(v1.1)*
- Water saturation calculation (Archie, Indonesian, Simandoux, Waxman-Smits, Dual-Water)
- Permeability prediction (Timur, Wyllie-Rose) with core calibration
- HCPV (Hydrocarbon Pore Volume) calculation *(v1.2)*
- Net pay analysis with configurable cutoffs
- Core data validation with statistical metrics
- Session save/load for project management *(v1.1)*
- Interactive GPU-accelerated log visualization *(v1.1)*

## Installation

### Prerequisites
- Python 3.10 or higher
- pip package manager

### Setup

```bash
# Clone or navigate to the directory
cd petrophyter_pyqt

# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

### Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| PyQt6 | ≥6.5.0 | GUI Framework |
| pandas | ≥2.0.0 | Data Processing |
| numpy | ≥1.24.0 | Numerical Computing |
| scipy | ≥1.10.0 | Scientific Computing |
| matplotlib | ≥3.7.0 | Static Plotting |
| pyqtgraph | ≥0.13.0 | Interactive Log Display *(v1.1)* |
| PyOpenGL | ≥3.1.0 | GPU Accelerated Rendering *(v1.1)* |
| lasio | ≥0.30 | LAS File Parsing |
| openpyxl | ≥3.1.0 | Excel Export |

## Project Structure

```
petrophyter/
├── main.py                 # Application entry point
├── requirements.txt        # Python dependencies
├── petrophyter_pyqt.bat    # Windows launcher
├── icons/                  # SVG icons for UI
├── models/                 # Data models
│   └── app_model.py        # Application state model
├── modules/                # Core calculation modules
│   ├── core_handler.py     # Core data validation
│   ├── formation_tops.py   # Formation top management
│   ├── las_handler.py      # LAS file merging
│   ├── las_parser.py       # LAS file parsing
│   ├── petrophysics.py     # Petrophysical calculations
│   ├── qc_module.py        # Quality control
│   ├── statistics_utils.py # Statistical utilities
│   └── visualization.py    # Plotting utilities
├── services/               # Business logic services
│   ├── analysis_service.py # Background analysis (v1.1)
│   ├── merge_service.py    # LAS merge service
│   ├── export_service.py   # Export service
│   └── session_service.py  # Session management (v1.1)
├── tests/                  # Unit tests (v1.1)
│   ├── test_petrophysics.py
│   └── test_session.py
└── ui/                     # User interface components
    ├── main_window.py      # Main application window
    ├── sidebar_panel.py    # Parameter input panel
    ├── tabs/               # Tab widgets
    │   ├── log_display_tab.py
    │   ├── petrophysics_tab.py
    │   ├── qc_tab.py
    │   ├── diagnostics_tab.py
    │   ├── summary_tab.py
    │   └── export_tab.py
    └── widgets/            # Reusable widgets
        ├── plot_widget.py
        ├── interactive_log.py  # (v1.1)
        ├── parameter_groups.py
        └── about_dialog.py
```

## Features

### 1. Data Loading

#### LAS File Loading
- Single and multiple LAS file support
- Automatic curve detection and type mapping
- NULL value handling (-999.25, -9999, etc.)
- Depth unit detection (feet/meters) *(v1.0)*

#### Multi-LAS Merge *(v1.0)*
- Intelligent curve selection with quality scoring
- Configurable merge step (0.1-1.0 ft)
- Gap interpolation with configurable limit (1.0-50.0 ft)
- Same-well validation
- Detailed merge report with curve sources

#### Formation Tops *(v1.0)*
- Load formation tops from TXT/CSV
- Automatic depth unit conversion
- Formation overlay on log display

#### Core Data
- Load core data (TXT/CSV) with flexible column detection
- Automatic depth matching and interpolation
- Porosity unit conversion (% to fraction)

### 2. Shale Volume (Vsh) Methods

| Method | Description | Version |
|--------|-------------|---------|
| **GR Linear** | `Vsh = (GR - GRmin) / (GRmax - GRmin)` | v1.0 |
| **Larionov Tertiary** | `Vsh = 0.083 × (2^(3.7×IGR) - 1)` | v1.0 |
| **Larionov Older** | `Vsh = 0.33 × (2^(2×IGR) - 1)` | v1.0 |
| **SP** | Spontaneous Potential method | v1.0 |
| **Neutron-Density** | Cross-plot separation method | v1.0 |

#### GR Baseline Modes *(v1.0)*
- **Statistical (Auto)**: Uses P5/P95 percentiles
- **Custom (Manual)**: User-specified GRmin/GRmax

#### Shale Parameter Estimation *(v1.0)*
- **Fixed Threshold**: User-specified Vsh threshold
- **Quantile Mode**: Use Vsh distribution quantile (0.80-0.99)
- **Stability Sweep**: Sweep threshold range for most stable parameters
- Log gating and IQR outlier filtering

### 3. Porosity Methods

| Method | Description | Version |
|--------|-------------|---------|
| **Density (PHID)** | `PHIE = (ρma - ρb) / (ρma - ρfl) - Vsh × correction` | v1.0 |
| **Neutron (PHIN)** | With matrix and shale correction | v1.0 |
| **Sonic (PHIS)** | Wyllie time-average equation | v1.0 |
| **Neutron-Density (PHIT)** | RMS average from crossplot | v1.0 |

#### Gas Correction *(v1.1)*
- Enable/disable gas correction for PHIE
- Configurable NPHI factor (0.10-0.50)
- Configurable RHOB factor (0.05-0.30)
- Auto-detection of gas zones via N-D crossover

### 4. Water Saturation Methods

| Model | Description | Version |
|-------|-------------|---------|
| **Archie** | Clean sand equation: `Sw = (a × Rw / (φ^m × Rt))^(1/n)` | v1.0 |
| **Indonesian** | For shaly sands (iterative solver) | v1.0 |
| **Simandoux** | Quadratic solution for shaly sands | v1.0 |
| **Waxman-Smits** | With Qv and B parameters | v1.2 |
| **Dual-Water** | With Swb and Rwb parameters | v1.2 |

#### Archie Parameter Presets
- **Sandstone (Humble)**: a=0.62, m=2.15, n=2.0
- **Carbonate**: a=1.0, m=2.0, n=2.0
- **Custom**: User-defined a, m, n

### 5. Irreducible Water Saturation (Swirr)

| Method | Description | Version |
|--------|-------------|---------|
| **Hierarchical** | Recommended for no-core calibration | v1.0 |
| **Buckles Number** | `Swirr = k_buckles / PHIE` | v1.0 |
| **Clean Zone** | Minimum Sw in clean HC zones | v1.0 |
| **Statistical** | P5 of Sw in clean zones | v1.0 |
| **All Methods** | Calculate all for comparison | v1.0 |

### 6. Permeability Correlations

| Method | Equation | Version |
|--------|----------|---------|
| **Timur** | `K = 8581 × (PHIE^4.4) / (Swirr^2)` | v1.0 |
| **Wyllie-Rose** | `K = C × (PHIE^P) / (Swirr^Q)` | v1.0 |

- Core-calibrated coefficient fitting (C, P, Q)
- Flow Unit Classification: Tight, Poor, Fair, Good, Excellent

### 7. Net Pay Analysis *(v1.0)*

- **Gross Sand**: Where Vsh < cutoff
- **Net Reservoir**: Gross Sand AND PHIE > cutoff
- **Net Pay**: Net Reservoir AND Sw < cutoff
- **N/G Ratios**: Net-to-Gross for reservoir and pay
- **Average Properties**: Mean PHIE, Sw, Vsh in net pay

#### Configurable Cutoffs (via sliders) *(v1.0)*
- Vsh cutoff (0-100%)
- PHIE cutoff (0-30%)
- Sw cutoff (0-100%)

### 8. HCPV Calculation *(v1.2)*

- **HCPV Fraction**: `PHIE × (1 - Sw)`
- **Incremental HCPV (dHCPV)**: Per depth interval
- **Cumulative HCPV**: Running total
- Multiple display modes: Net Pay, Net Reservoir, Gross, Fraction Only
- Toggle visibility via checkbox control

### 9. Core Data Validation

- Import core data (TXT/CSV)
- Automatic depth matching with configurable interpolation
- **Statistical Metrics**: Bias, MAE, RMSE, R², Spearman ρ
- **Visual Crossplots**: 
  - Porosity (Core vs Log) with 1:1 reference line
  - Permeability (Core vs Log) in log10 domain
  - Depth tracks with core overlay

### 10. Quality Control *(v1.0)*

- **Curve QC Analysis**: Valid %, Min, Max, Mean, Std, Quality Score
- **Bad Hole Detection**: From caliper log
- **Data Gap Detection**: Per curve
- **Outlier Detection**: IQR method
- **Triple Combo Log Preview**: GR, RT, RHOB/NPHI/DT with gas crossover shading

### 11. Visualization

#### Interactive Log Display (PyQtGraph) *(v1.1)*
- GPU-accelerated rendering (OpenGL)
- 6-track composite log display
- Zoom, pan, and crosshair cursor
- Depth region selection (drag to select interval)
- Formation tops overlay
- Linked Y-axes across all tracks
- ~30 FPS throttled updates for smooth performance *(optimized in v1.2)*

#### Classic Log Display (Matplotlib) *(v1.0)*
- Static plots for export quality
- Navigation toolbar (pan, zoom, save)

#### Crossplots
- Neutron-Density crossplot (color-coded by Vsh)
- Porosity-Permeability crossplot

### 12. Export Options

| Format | Description | Version |
|--------|-------------|---------|
| **Excel (.xlsx)** | Multi-sheet workbook with results and summary | v1.0 |
| **CSV (.csv)** | Full results DataFrame | v1.0 |
| **LAS (.las)** | Merged LAS file with calculated curves | v1.0 |

### 13. Session Management *(v1.1)*

- **Save Session**: Export all parameters to JSON file
- **Load Session**: Restore all parameters from JSON file
- **Version Compatibility**: Session version tracking

Saved parameters include:
- Analysis mode and formations
- All VShale, porosity, Sw, permeability parameters
- Archie coefficients and lithology settings
- Cutoff values
- Gas correction settings *(v1.1)*
- Merge and core settings

### 14. Background Processing *(v1.1)*

- **Async Calculations**: Prevent UI freeze during analysis
- **Progress Indicators**: Real-time progress feedback
- **Cancellable Operations**: Stop long-running tasks

## User Interface

### Tab System (6 Tabs)

| Tab | Purpose |
|-----|---------|
| **Data QC** | Input data quality control and curve statistics |
| **Petrophysics** | Calculation results and histograms |
| **Log Display** | Composite log visualization (interactive/classic) |
| **Diagnostics** | Cross-validation, core comparison, warnings |
| **Summary** | Net pay analysis and HCPV summary |
| **Export** | Download results in various formats |

### Sidebar Parameter Groups (13 Collapsible Sections)

1. Analysis Mode
2. Curve Mapping
3. VShale Parameters
4. Matrix Parameters
5. Fluid Parameters
6. Shale Parameters
7. Archie Parameters
8. Sw Models
9. Resistivity Parameters
10. Permeability Coefficients
11. Swirr Estimation
12. Cutoff Parameters
13. Gas Correction (PHIE) *(v1.1)*

## Usage

### Quick Start

1. **Load LAS File**: Click "Load LAS File" and select your well log file
2. **Set Parameters**: Adjust shale parameters, matrix density, and cutoffs in the sidebar
3. **Run Analysis**: Click "Run Analysis" to calculate all properties
4. **Review Results**: Navigate through tabs to view results
5. **Export**: Go to Export tab to save results

### Multi-LAS Merge Workflow

1. Click "Load LAS Files" (multiple selection)
2. Review curve QC and select best curves per type
3. Configure merge step and gap limit
4. Click "Merge" to combine files
5. Download merged LAS or continue with analysis

### Core Data Validation

1. Load your LAS file first
2. Click "Load Core Data" in the sidebar
3. Select your core data file (TXT/CSV with columns: Depth, Porosity, Permeability)
4. View validation results in the Diagnostics tab
5. Use core-calibrated coefficients for permeability

### Session Save/Load *(v1.1)*

1. Configure all parameters as needed
2. Click "Save Session" to export to JSON
3. Later, click "Load Session" to restore all settings

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+O` | Open LAS file |
| `Ctrl+R` | Run analysis |
| `Ctrl+E` | Export results |
| `Ctrl+Q` | Quit application |

## Configuration

### Recommended Shale Parameters

| Lithology | ρ shale (g/cc) | NPHI shale | DT shale (µs/ft) |
|-----------|----------------|------------|------------------|
| Shale | 2.45-2.65 | 0.30-0.45 | 90-120 |
| Clay-rich | 2.35-2.50 | 0.35-0.50 | 100-140 |

### Cutoff Guidelines

| Parameter | Typical Clean Sand | Pay Zone |
|-----------|-------------------|----------|
| Vsh | < 0.40 | < 0.30 |
| PHIE | > 0.08 | > 0.10 |
| Sw | - | < 0.60 |

### Buckles Number Presets

| Lithology | k_buckles |
|-----------|-----------|
| Sandstone (Clean) | 0.02 |
| Sandstone (Shaly) | 0.03 |
| Carbonate | 0.04 |

## Troubleshooting

### Common Issues

**Application won't start**
```bash
# Ensure PyQt6 is properly installed
pip install --upgrade PyQt6 PyQt6-Qt6
```

**PyQtGraph OpenGL errors** *(v1.1+)*
```bash
# Install PyOpenGL for GPU acceleration
pip install PyOpenGL PyOpenGL_accelerate
```

**LAS file not loading**
- Check file encoding (UTF-8 recommended)
- Verify LAS file version (1.2 or 2.0)

**Calculations seem wrong**
- Verify input curve units (check LAS header)
- Check shale parameter values
- Ensure depth is in correct units (ft or m)

**Interactive plot is slow** *(v1.1+)*
- Ensure PyOpenGL is installed
- GPU acceleration requires compatible graphics driver

## Version History

### v1.2 (Build 20260106) - Current Release
**New Features:**
- Added HCPV (Hydrocarbon Pore Volume) calculation module
- Added Waxman-Smits water saturation model
- Added Dual-Water water saturation model
- Multiple HCPV display modes (Net Pay, Net Reservoir, Gross, Fraction Only)

**Improvements:**
- Optimized PyQtGraph log engine with OpenGL GPU acceleration
- Added mouse event throttling (~30 FPS) for smoother interactive plots
- Performance improvements for large datasets (~6800+ data points)

**Bug Fixes:**
- Fixed HCPV visibility toggle checkbox functionality
- Fixed signal connection issue causing 6x redundant mouse event calls

---

### v1.1 (Dec 30, 2025)
**New Features:**
- Interactive Log Display using PyQtGraph (GPU-accelerated)
- Session Save/Load functionality (JSON format)
- Gas Correction for PHIE calculation
- Async background calculations (prevent UI freeze)
- Unit tests foundation for development

**Improvements:**
- 6-track composite log with zoom, pan, crosshair
- Depth region selection via drag
- Formation tops overlay on interactive plot
- Progress indicators during analysis

**Bug Fixes:**
- Various UI/UX bug fixes
- Improved responsiveness during long calculations

---

### v1.0 Final (Dec 23, 2025) - Initial Release
**Core Features:**
- LAS file loading with automatic curve detection
- Depth unit detection (feet/meters)
- Multi-LAS file merging with quality scoring
- Formation tops loading and overlay

**Calculations:**
- VShale: GR Linear, Larionov (Tertiary/Older), SP, Neutron-Density
- GR Baseline: Statistical (P5/P95) and Manual modes
- Shale Parameter Estimation (3 methods for robustness)
- Porosity: Density, Neutron, Sonic, Neutron-Density
- Water Saturation: Archie, Indonesian, Simandoux
- Swirr Estimation: Hierarchical, Buckles, Clean Zone, Statistical
- Permeability: Timur, Wyllie-Rose with core calibration
- Net Pay Analysis with configurable cutoffs

**Visualization:**
- Classic Log Display (Matplotlib)
- Triple Combo Log Preview
- Crossplots (N-D, Porosity-Permeability)

**Quality Control:**
- Curve QC with quality scoring
- Bad hole and data gap detection
- Outlier detection (IQR method)

**Export:**
- Excel (.xlsx), CSV (.csv), LAS (.las) formats

---

## Build Windows Installer

This section explains how to build a Windows installer (`setup.exe`) for distribution.

### Prerequisites

1. **Python Environment**: All dependencies from `requirements.txt` installed
2. **PyInstaller**: Install with `pip install pyinstaller`
3. **Inno Setup 6**: Download and install from [jrsoftware.org/isinfo.php](https://jrsoftware.org/isinfo.php)

### Build Steps

Run the PowerShell build script from the `petrophyter_pyqt` folder:

```powershell
# Full build (PyInstaller + Inno Setup)
.\scripts\build-installer.ps1

# Skip PyInstaller (use existing dist folder)
.\scripts\build-installer.ps1 -SkipPyInstaller

# Only run PyInstaller (don't create installer)
.\scripts\build-installer.ps1 -SkipInnoSetup
```

### Output

| Output | Location |
|--------|----------|
| **Installer** | `installer/Output/Petrophyter_Setup_1.2.exe` |
| **Portable** | `dist/Petrophyter/` (can be copied directly) |

### Custom Inno Setup Path

If Inno Setup is installed in a non-default location, set the `ISCC_PATH` environment variable:

```powershell
$env:ISCC_PATH = "D:\Tools\Inno Setup 6\ISCC.exe"
.\scripts\build-installer.ps1
```

### What the Installer Does

- Installs application to `C:\Program Files\Petrophyter\`
- Creates Start Menu shortcuts (Petrophyter + Uninstall)
- Optional Desktop shortcut (user choice during installation)
- Registers uninstall entry in Windows Settings > Apps
- Offers to launch application after installation

---

## License

This project is **dual-licensed** under your choice of:

| License | File | Use Case |
|---------|------|----------|
| **Apache-2.0** | [LICENSE-APACHE-2.0](LICENSE-APACHE-2.0) | Permissive reuse of core modules |
| **GPL-3.0** | [LICENSE-GPL-3.0](LICENSE-GPL-3.0) | Full application with PyQt6 |

### License Summary

```
+-----------------------------------------------------------------------+
|                      PETROPHYTER LICENSING                            |
+-----------------------------------------------------------------------+
|                                                                       |
|  +---------------------------+    +---------------------------+       |
|  |      CORE MODULES         |    |     FULL APPLICATION      |       |
|  |      (modules/*.py)       |    |     (with PyQt6 UI)       |       |
|  |                           |    |                           |       |
|  |      Apache-2.0           |    |      GPL-3.0              |       |
|  |      - Permissive         |    |      - Copyleft           |       |
|  |      - Commercial OK      |    |      - Source required    |       |
|  |      - No GPL spread      |    |      - PyQt6 compliant    |       |
|  +---------------------------+    +---------------------------+       |
|                                                                       |
+-----------------------------------------------------------------------+
```

### What This Means

- **If you use the core calculation modules only** (`modules/petrophysics.py`, etc.) 
  without PyQt6 UI: You may use Apache-2.0 (permissive, no copyleft).

- **If you use the complete application** (including PyQt6 UI): 
  GPL-3.0 applies due to PyQt6's licensing terms.

- **If you want to use PyQt6 without GPL**: Purchase a [commercial PyQt6 license](https://www.riverbankcomputing.com/commercial/pyqt).

### Third-Party Licenses

See [NOTICE](NOTICE) for complete list of third-party components and their licenses.

## Citation

Rohmana, R. C. (2026). Petrophyter: An Application for Petrophysical Analysis (Version 1.2). Petrophysics TAU Research Group, Petroleum Engineering, Tanri Abeng University."

---

*Built with PyQt6 and Python*
