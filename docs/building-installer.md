[Back to README](../README.md)

# Building the Windows Installer

This procedure builds a Windows `setup.exe` for distribution.

## Prerequisites

1. Install Conda (Anaconda or Miniconda).
2. Use a Conda environment that has every dependency from `requirements.txt`, including **pyqtgraph** and **PyOpenGL**. Without them, the frozen app falls back to the Classic (matplotlib) log engine. Release builds use the `mldl` environment (Python 3.13, PyQt6 6.9, pyqtgraph 0.13.7).
3. Install PyInstaller in that environment: `pip install pyinstaller`.
4. Download and install [Inno Setup 6](https://jrsoftware.org/isinfo.php). Both system-wide and per-user installs are detected.

## Build Commands

Run the PowerShell build script from the repository root:

```powershell
# Select the Conda environment (defaults to mldl when omitted)
$env:CONDA_ENV = "mldl"

# Full build: PyInstaller and Inno Setup
.\scripts\build-installer.ps1

# Run PyInstaller only; do not create the installer
.\scripts\build-installer.ps1 -SkipInnoSetup

# Skip PyInstaller and use the existing dist folder
.\scripts\build-installer.ps1 -SkipPyInstaller
```

## Output

| Output | Location |
|---|---|
| **Installer** | `installer/Output/Petrophyter_Setup_<version>_Build<build>.exe` (for example `Petrophyter_Setup_1.7.0_Build20261010.exe`) |
| **Portable application** | `dist/Petrophyter/` (can be copied directly) |

## Release Checklist

1. Update the version in **one** place, `version.py` (`APP_VERSION`, `APP_BUILD` = `YYYYMMDD`). Then update the strings that tests check against it:
   - `installer/Petrophyter.iss` (`AppVersion`, `AppVersionFile`);
   - `tests/test_version.py`;
   - the version badge and citation in `README.md`.
2. Add the release section to `docs/changelog.md` and mark it **Current Release**. Write `docs/releases/v<version>.md`.
3. Run the full test suite in the build environment. Use `conda run` so the environment's own DLLs come first on `PATH`; calling `envs\mldl\python.exe` directly can load the base Anaconda MKL instead and crash in scipy:

   ```powershell
   $env:QT_QPA_PLATFORM = "offscreen"
   $env:PYTEST_QT_API = "pyqt6"
   conda run -n mldl --no-capture-output python -m pytest -q
   ```

4. Build with `.\scripts\build-installer.ps1 -SkipInnoSetup`. Launch `dist\Petrophyter\Petrophyter.exe`, confirm the main window opens, and confirm that **Log Display → Interactive** is available.
5. Build the installer with `.\scripts\build-installer.ps1 -SkipPyInstaller`.
6. Write the checksum manifest:

   ```powershell
   cd installer\Output
   $f = "Petrophyter_Setup_<version>_Build<build>.exe"
   "$((Get-FileHash $f -Algorithm SHA256).Hash.ToLower()) *$f" | Set-Content -Encoding ascii SHA256SUMS.txt
   ```

7. Push `main`, then publish the GitHub release. The tag format is `Petrophyter_v<version>`:

   ```powershell
   gh release create Petrophyter_v<version> --target main `
     --title "Petrophyter v<version> — Windows Desktop Installer" `
     --notes-file docs\releases\v<version>.md `
     installer\Output\Petrophyter_Setup_<version>_Build<build>.exe installer\Output\SHA256SUMS.txt
   ```

## MKL Libraries

numpy and scipy in the Conda environment reach BLAS and LAPACK through `libblas.dll` and `liblapack.dll`, which forward to Intel MKL (`mkl_rt.<N>.dll`). MKL loads its core, threading, and CPU-specific libraries at run time, so PyInstaller cannot find them. `petrophyter_pyqt_2.spec` therefore bundles `mkl_rt`, `mkl_core`, `mkl_sequential`, `mkl_def`, `mkl_mc3`, `mkl_avx2`, and `mkl_avx512`, and the runtime hook `installer/rth_mkl_sequential.py` selects the sequential threading layer. The build stops if `liblapack.dll` is present but no `mkl_rt.*.dll` is found.

To check a build on a PC without Anaconda, start `dist\Petrophyter\Petrophyter.exe` from a shell whose `PATH` has no Anaconda folders.

## Custom Inno Setup Path

If Inno Setup is installed outside the default locations, set `ISCC_PATH`:

```powershell
$env:ISCC_PATH = "D:\Tools\Inno Setup 6\ISCC.exe"
.\scripts\build-installer.ps1
```

## Installer Behavior

The installer:

- Installs Petrophyter to `C:\Program Files\Petrophyter\`, or to the per-user location when it is installed for the current user only.
- Installs `LICENSE`, `LICENSE-APACHE-2.0`, `LICENSE-GPL-3.0`, and `NOTICE` (third-party notices, including the Lucide icons) next to the application.
- Creates Start Menu shortcuts for Petrophyter and its uninstaller.
- Offers an optional Desktop shortcut.
- Registers an uninstall entry under Windows Settings > Apps.
- Upgrades an existing installation in place, because the `AppId` is the same across versions.
- Offers to launch the application after installation.
