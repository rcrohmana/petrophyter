[Back to README](../README.md)

# Building the Windows Installer

This procedure builds a Windows `setup.exe` for distribution.

## Prerequisites

1. Install Conda (Anaconda or Miniconda).
2. Use a Conda environment that has every dependency from `requirements.txt`, including **pyqtgraph** and **PyOpenGL**. Without them, the frozen app falls back to the Classic (matplotlib) log engine. Release builds use the `mldl` environment (Python 3.13, PyQt6 6.9, pyqtgraph 0.13.7).
3. Install PyInstaller in that environment: `pip install pyinstaller`.
4. Download and install [Inno Setup 6](https://jrsoftware.org/isinfo.php). Both system-wide and per-user installs are detected.

## Lock File

`requirements-lock.txt` pins the exact versions of the release environment (`mldl`, Python 3.13.14): the runtime packages from `requirements.txt` and their dependencies, PyInstaller with its hooks, and the test tools the build gate uses. `requirements.txt` stays the range file for development. CI installs from the lock file (`pip install -r requirements-lock.txt`). To refresh it after changing the release environment, list the environment with:

```powershell
conda run -n mldl --no-capture-output python -m pip list --format=freeze
```

Do not use `pip freeze` for this: Conda packages come out as `@ file:///` URLs that pip cannot install. Keep only what the app and the build need, and update the header comment (environment, Python version, date).

The PyPI wheels of numpy and scipy use OpenBLAS, while the `mldl` builds use Intel MKL. Results can differ in the last digits between the two.

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

# Skip the test gate (iteration only; prints a warning)
.\scripts\build-installer.ps1 -SkipTests
```

The script runs these steps in order:

1. **Test gate** (together with PyInstaller). It runs `conda run -n mldl --no-capture-output python -m pytest -q -rs` with `PYTEST_QT_API=pyqt6`, `QT_QPA_PLATFORM=offscreen`, and `RELEASE=1`, and stops on a non-zero exit. `RELEASE=1` makes `tests/conftest.py` turn every skipped test into a failure, so a missing optional package cannot hide. `-SkipTests` skips the gate for iteration and prints a loud warning; do not publish such a build.
2. **PyInstaller**.
3. **Self-test** of the frozen exe: `dist\Petrophyter\Petrophyter.exe --self-test --self-test-log build\selftest.log`. The build fails on a non-zero exit or when the log has no `SELFTEST OK` line.
4. **Inno Setup**, then the manifest files described under Output.

## Self-Test

`Petrophyter.exe --self-test` is a smoke test of a build. It runs offscreen, shows no dialog, and uses a temporary settings folder, so it never touches your saved settings. It prints one line per step and exits 0 only if all steps pass:

- imports numpy, scipy, pandas, matplotlib, lasio, openpyxl, pyqtgraph, and PyOpenGL;
- calls LAPACK routines (`scipy.linalg.solve`, `numpy.linalg.svd`, `scipy.optimize.curve_fit`), the kind of call that crashed in v1.7.0 on a PC without Anaconda;
- runs the pipeline on a small synthetic well built in code (`services/self_test.py`);
- builds the main window.

The frozen exe has no console, so `--self-test-log <path>` also writes the lines to a file. The last line is `SELFTEST OK` or `SELFTEST FAILED: <step>`. You can run the same check from source with `python main.py --self-test`.

## Output

| Output | Location |
|---|---|
| **Installer** | `installer/Output/Petrophyter_Setup_<version>_Build<build>.exe` (for example `Petrophyter_Setup_1.7.0_Build20261010.exe`) |
| **Portable application** | `dist/Petrophyter/` (can be copied directly) |
| **Manifest** | `installer/Output/pip-freeze.txt` (`pip list --format=freeze` of `mldl`) and `installer/Output/conda-explicit.txt` (`conda list -n mldl --explicit`) |
| **Checksums** | `installer/Output/SHA256SUMS.txt` (SHA-256 of the installer, `pip-freeze.txt`, and `conda-explicit.txt`) |

The script writes the manifest and the checksums after it builds the installer. Attach all of them to the release.

## Release Checklist

1. Update the version in **one** place, `version.py` (`APP_VERSION`, `APP_BUILD` = `YYYYMMDD`). Then update the strings that tests check against it:
   - `installer/Petrophyter.iss` (`AppVersion`, `AppVersionFile`);
   - `tests/test_version.py`;
   - the version badge and citation in `README.md`.
2. Add the release section to `docs/changelog.md` and mark it **Current Release**. Write `docs/releases/v<version>.md`.
3. The build script runs the full test suite as its gate (see Build Commands). To run it by hand, use the build environment. Use `conda run` so the environment's own DLLs come first on `PATH`; calling `envs\mldl\python.exe` directly can load the base Anaconda MKL instead and crash in scipy:

   ```powershell
   $env:QT_QPA_PLATFORM = "offscreen"
   $env:PYTEST_QT_API = "pyqt6"
   $env:RELEASE = "1"   # a skipped test fails
   conda run -n mldl --no-capture-output python -m pytest -q -rs
   ```

4. Build with `.\scripts\build-installer.ps1 -SkipInnoSetup` (test gate, PyInstaller, self-test). Launch `dist\Petrophyter\Petrophyter.exe`, confirm the main window opens, and confirm that **Log Display → Interactive** is available.
5. Build the installer with `.\scripts\build-installer.ps1 -SkipPyInstaller`. This also writes `pip-freeze.txt`, `conda-explicit.txt`, and `SHA256SUMS.txt` to `installer\Output`.
6. On a PC without Anaconda, run `dist\Petrophyter\Petrophyter.exe --self-test --self-test-log selftest.log`, then start the installed app by hand. CI cannot prove the no-Conda case.
7. Push `main`, then publish the GitHub release. The tag format is `Petrophyter_v<version>`:

   ```powershell
   gh release create Petrophyter_v<version> --target main `
     --title "Petrophyter v<version> — Windows Desktop Installer" `
     --notes-file docs\releases\v<version>.md `
     installer\Output\Petrophyter_Setup_<version>_Build<build>.exe installer\Output\SHA256SUMS.txt `
     installer\Output\pip-freeze.txt installer\Output\conda-explicit.txt
   ```

## Continuous Integration

`.github/workflows/ci.yml` runs on every push and pull request, on `windows-latest` with Python 3.13:

1. install `requirements-lock.txt` and `pytest-xdist`;
2. run the suite offscreen (`PYTEST_QT_API=pyqt6`, `RELEASE=1`, `-n auto`, without the `slow` timing tests);
3. build with PyInstaller from `petrophyter_pyqt_2.spec`;
4. run `Petrophyter.exe --self-test --self-test-log selftest.log` and fail on a non-zero exit;
5. upload `pip-freeze.txt`, `selftest.log`, and a `SHA256SUMS.txt` of the exe as the `build-manifest` artifact.

CI does not build the installer (no Inno Setup) and does not replace the by-hand test on a PC without Anaconda.

## MKL Libraries

numpy and scipy in the Conda environment reach BLAS and LAPACK through `libblas.dll` and `liblapack.dll`, which forward to Intel MKL (`mkl_rt.<N>.dll`). MKL loads its core, threading, and CPU-specific libraries at run time, so PyInstaller cannot find them. `petrophyter_pyqt_2.spec` therefore bundles `mkl_rt`, `mkl_core`, `mkl_sequential`, `mkl_def`, `mkl_mc3`, `mkl_avx2`, and `mkl_avx512`, and the runtime hook `installer/rth_mkl_sequential.py` selects the sequential threading layer. The build stops if `liblapack.dll` is present but no `mkl_rt.*.dll` is found. It also stops if pyqtgraph is missing from the environment, so a build cannot silently fall back to the Classic log engine.

To check a build on a PC without Anaconda, run `dist\Petrophyter\Petrophyter.exe --self-test --self-test-log selftest.log` and then start the app, both from a shell whose `PATH` has no Anaconda folders.

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
