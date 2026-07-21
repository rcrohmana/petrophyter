[Back to README](../README.md)

# Version History

## v1.4.0 (Build 20260113) — Current Release

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
