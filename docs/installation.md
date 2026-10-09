[Back to README](../README.md)

# Installation

## Windows Installer (recommended for users)

1. Download `Petrophyter_Setup_<version>_Build<build>.exe` from the [latest release](https://github.com/rcrohmana/petrophyter/releases/latest).
2. Optionally verify it against `SHA256SUMS.txt` from the same release:

   ```powershell
   Get-FileHash .\Petrophyter_Setup_<version>_Build<build>.exe -Algorithm SHA256
   ```

3. Run the installer and launch **Petrophyter** from the Start Menu. Installing a newer version over an older one upgrades it in place.

## Running from Source

### Prerequisites

- Python 3.10 or higher (release builds use Python 3.13)
- pip, or Conda (Anaconda or Miniconda)

### Setup with pip

```bash
# From the repository root
pip install -r requirements.txt
python main.py
```

### Setup with Conda

```bash
conda create -n petrophyter python=3.13
conda activate petrophyter
pip install -r requirements.txt
python main.py
```

### Reference development environment

On the maintainer's machine, the reference environment is the Conda env **`mldl`** (Python 3.13, PyQt6 6.9, pyqtgraph 0.13.7). It is used for development, tests, and release builds. Launch the app in it either way:

- Double-click **`run_petrophyter.bat`** in the repository root. It uses `mldl`, and falls back to Anaconda base if `mldl` is missing. Run `run_petrophyter.bat debug` from a terminal to keep the console open for error messages.
- Or run `conda activate mldl`, then `python main.py`.

> Without **pyqtgraph**, Petrophyter still runs, but the Interactive log engine is unavailable and the Log Display tab uses the Classic (matplotlib) engine.

### Running the tests

```bash
pip install -r requirements-dev.txt
# PowerShell: $env:QT_QPA_PLATFORM = "offscreen"
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

## Dependencies

| Package | Version | Purpose |
|---|---:|---|
| PyQt6 | ≥6.5.0 | GUI framework |
| pandas | ≥2.0.0, <3.0 | Data processing |
| numpy | ≥1.24.0 | Numerical computing |
| scipy | ≥1.11.0 | Scientific computing |
| matplotlib | ≥3.7.0 | Static plotting |
| pyqtgraph | ≥0.13.0 | Interactive log display |
| PyOpenGL | ≥3.1.0 | GPU-accelerated rendering for pyqtgraph |
| lasio | ≥0.31 | LAS file parsing |
| openpyxl | ≥3.1.0 | Excel export |
