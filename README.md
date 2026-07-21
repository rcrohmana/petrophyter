# Petrophyter

**Desktop Petrophysics Application** — A comprehensive tool for well-log analysis and petrophysical calculations.

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![PyQt6](https://img.shields.io/badge/PyQt6-6.5+-green.svg)
![License](https://img.shields.io/badge/License-Apache--2.0%20OR%20GPL--3.0-blue.svg)
![Version](https://img.shields.io/badge/Version-1.4.0_(Build_20260113)-orange.svg)

![Petrophyter application](<icons/Screenshot 1.2.png>)

## Overview

Petrophyter is a PyQt6 desktop application for loading, analyzing, visualizing, and exporting petrophysical well-log data.

Key capabilities include:

- LAS loading, automatic curve mapping, and intelligent multi-file merging
- Shale-volume, porosity, water-saturation, Swirr, and permeability calculations
- Archie, Indonesian, Simandoux, Waxman-Smits, and Dual-Water saturation models
- Core-calibrated permeability and statistical core-data validation
- HCPV and configurable net-pay analysis
- Formation-top overlays and quality-control diagnostics
- Interactive GPU-accelerated six-track log visualization
- Excel, CSV, and LAS export
- JSON session save and load
- Light and Dark application themes

## Quick Start

### Requirements

- Python 3.10 or higher
- pip package manager

### Install and Run

```bash
cd petrophyter_pyqt
pip install -r requirements.txt
python main.py
```

See [Installation](docs/installation.md) for dependency versions and complete setup information.

## Basic Workflow

1. **Load data:** Open a LAS file or merge multiple files from the same well.
2. **Configure:** Select calculation methods and adjust shale, matrix, fluid, and cutoff parameters.
3. **Analyze:** Run the petrophysical calculations.
4. **Review:** Inspect logs, crossplots, diagnostics, core validation, and net-pay results.
5. **Export:** Save the results or session for later use.

See the [User Guide](docs/user-guide.md) for multi-LAS merging, core validation, session handling, and keyboard shortcuts.

## Documentation

Documentation is organized by topic so every reader can access technical and operational details directly.

| Topic | Contents |
|---|---|
| [Installation](docs/installation.md) | Prerequisites, setup, and dependency versions |
| [User Guide](docs/user-guide.md) | Data-loading and analysis workflows, core validation, and shortcuts |
| [Supported Data Formats](docs/data-formats.md) | LAS support and complete core/formation column requirements |
| [Calculation Methods](docs/calculation-methods.md) | Equations, models, presets, parameter ranges, net pay, and QC |
| [Visualization and Export](docs/visualization-and-export.md) | Interactive and classic plots, crossplots, and output formats |
| [Session Management](docs/session-management.md) | JSON save/load behavior and persisted parameters |
| [Troubleshooting](docs/troubleshooting.md) | Common loading and calculation problems |
| [Building the Windows Installer](docs/building-installer.md) | PyInstaller and Inno Setup build procedure |
| [Version History](docs/changelog.md) | Complete release history and project origins |
| [Licensing](docs/licensing.md) | Detailed dual-license explanation and third-party notices |

## License

Petrophyter is dual-licensed:

- Core calculation modules may be used under [Apache-2.0](LICENSE-APACHE-2.0).
- The complete application with its PyQt6 interface is distributed under [GPL-3.0](LICENSE-GPL-3.0).

See [Licensing](docs/licensing.md) for the detailed scope, commercial PyQt6 option, and third-party notices.

## Citation

Rohmana, R. C. (2026). *Petrophyter: An Application for Petrophysical Analysis* (Version 1.4) [Computer software]. Petrophysics TAU Research Group, Petroleum Engineering, Tanri Abeng University. Supported by GeoPangea Research Group (GPRG).

---

*Built with PyQt6 and Python*
