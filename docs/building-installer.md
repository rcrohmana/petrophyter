[Back to README](../README.md)

# Building the Windows Installer

This procedure builds a Windows `setup.exe` for distribution.

## Prerequisites

1. Install Conda and create an environment with the dependencies from `requirements.txt`.
2. Install PyInstaller in that environment with `pip install pyinstaller`.
3. Download and install [Inno Setup 6](https://jrsoftware.org/isinfo.php).

## Build Commands

Run the PowerShell build script from the `petrophyter_pyqt` folder:

```powershell
# Select the Conda environment (defaults to qceda when omitted)
$env:CONDA_ENV = "your-environment"

# Full build: PyInstaller and Inno Setup
.\scripts\build-installer.ps1

# Skip PyInstaller and use the existing dist folder
.\scripts\build-installer.ps1 -SkipPyInstaller

# Run PyInstaller only; do not create the installer
.\scripts\build-installer.ps1 -SkipInnoSetup
```

## Output

| Output | Location |
|---|---|
| **Installer** | `installer/Output/Petrophyter_Setup_1.5.0_Build20260814.exe` |
| **Portable application** | `dist/Petrophyter/` (can be copied directly) |

## Custom Inno Setup Path

If Inno Setup is installed outside its default location, set `ISCC_PATH`:

```powershell
$env:ISCC_PATH = "D:\Tools\Inno Setup 6\ISCC.exe"
.\scripts\build-installer.ps1
```

## Installer Behavior

The installer:

- Installs Petrophyter to `C:\Program Files\Petrophyter\`.
- Creates Start Menu shortcuts for Petrophyter and its uninstaller.
- Offers an optional Desktop shortcut.
- Registers an uninstall entry under Windows Settings > Apps.
- Offers to launch the application after installation.
