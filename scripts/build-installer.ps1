<#
.SYNOPSIS
    Build Petrophyter Windows Installer

.DESCRIPTION
    This script automates the build process for Petrophyter:
    1. Runs PyInstaller to create dist/Petrophyter/ (one-folder mode)
    2. Compiles Inno Setup script to create the Windows installer

.PARAMETER SkipPyInstaller
    Skip PyInstaller build step. Use this when dist folder already exists
    and you only want to rebuild the installer.

.PARAMETER SkipInnoSetup
    Skip Inno Setup compilation. Use this when you only want to build
    the PyInstaller distribution without creating the installer.

.EXAMPLE
    .\build-installer.ps1
    Full build: PyInstaller + Inno Setup

.EXAMPLE
    .\build-installer.ps1 -SkipPyInstaller
    Only compile Inno Setup (use existing dist folder)

.EXAMPLE
    .\build-installer.ps1 -SkipInnoSetup
    Only run PyInstaller (don't create installer)

.NOTES
    Prerequisites:
    - Conda environment 'qceda' with PyInstaller installed
    - Inno Setup 6 installed: https://jrsoftware.org/isinfo.php
    
    Environment Variables:
    - ISCC_PATH: Custom path to ISCC.exe (optional)
    - CONDA_ENV: Conda environment name (default: qceda)
#>

[CmdletBinding()]
param(
    [switch]$SkipPyInstaller,
    [switch]$SkipInnoSetup
)

# Strict error handling
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# Get script and project paths
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# Configuration
$SpecFile = "petrophyter_pyqt_2.spec"
$IssFile = "installer\Petrophyter.iss"
$DistFolder = "dist\Petrophyter"
$OutputFolder = "installer\Output"
$CondaEnv = if ($env:CONDA_ENV) { $env:CONDA_ENV } else { "qceda" }

function Write-Banner {
    param([string]$Text, [string]$Color = "Cyan")
    $line = "=" * 60
    Write-Host ""
    Write-Host $line -ForegroundColor $Color
    Write-Host "  $Text" -ForegroundColor $Color
    Write-Host $line -ForegroundColor $Color
    Write-Host ""
}

function Write-Step {
    param([string]$Step, [string]$Message)
    Write-Host "[$Step] $Message" -ForegroundColor Yellow
}

function Write-Success {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Green
}

function Write-Info {
    param([string]$Message)
    Write-Host "  $Message" -ForegroundColor Gray
}

function Find-IsccExe {
    <#
    .SYNOPSIS
        Find ISCC.exe (Inno Setup Command-Line Compiler)
    #>
    
    # Check environment variable first
    if ($env:ISCC_PATH -and (Test-Path $env:ISCC_PATH)) {
        return $env:ISCC_PATH
    }
    
    # Check default installation paths (including user-local installs)
    $defaultPaths = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "$env:USERPROFILE\AppData\Local\Programs\Inno Setup 6\ISCC.exe",
        "C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
        "C:\Program Files\Inno Setup 5\ISCC.exe"
    )
    
    foreach ($path in $defaultPaths) {
        if (Test-Path $path) {
            return $path
        }
    }
    
    # Not found
    return $null
}

# =============================================================================
# MAIN BUILD PROCESS
# =============================================================================

Write-Banner "Petrophyter Windows Installer Builder"

# Change to project root
Push-Location $ProjectRoot
Write-Info "Working directory: $ProjectRoot"

try {
    $stepNum = 0
    $totalSteps = 2
    if ($SkipPyInstaller) { $totalSteps-- }
    if ($SkipInnoSetup) { $totalSteps-- }
    
    if ($totalSteps -eq 0) {
        Write-Host "Nothing to do. Both steps are skipped." -ForegroundColor Yellow
        exit 0
    }

    # -------------------------------------------------------------------------
    # STEP 1: PyInstaller Build (in conda environment)
    # -------------------------------------------------------------------------
    if (-not $SkipPyInstaller) {
        $stepNum++
        Write-Step "$stepNum/$totalSteps" "Running PyInstaller in conda env '$CondaEnv'..."
        
        # Check spec file exists
        if (-not (Test-Path $SpecFile)) {
            throw "PyInstaller spec file not found: $SpecFile"
        }
        Write-Info "Spec file: $SpecFile"
        Write-Info "Conda environment: $CondaEnv"
        
        # Check conda is available
        $condaPath = Get-Command conda -ErrorAction SilentlyContinue
        if (-not $condaPath) {
            throw "Conda not found. Please ensure Anaconda/Miniconda is installed and in PATH."
        }
        Write-Info "Conda: $($condaPath.Source)"
        
        # Run PyInstaller via conda run
        Write-Host ""
        & conda run -n $CondaEnv --no-capture-output pyinstaller --noconfirm --clean $SpecFile
        
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller failed with exit code $LASTEXITCODE"
        }
        
        # Verify output
        if (-not (Test-Path $DistFolder)) {
            throw "PyInstaller did not create expected output: $DistFolder"
        }
        
        $exePath = Join-Path $DistFolder "Petrophyter.exe"
        if (-not (Test-Path $exePath)) {
            throw "Executable not found: $exePath"
        }
        
        $exeSize = (Get-Item $exePath).Length / 1MB
        Write-Host ""
        Write-Success "PyInstaller completed successfully!"
        Write-Info "Output: $DistFolder"
        Write-Info "Executable size: $([math]::Round($exeSize, 1)) MB"
    }
    else {
        Write-Step "SKIP" "PyInstaller (using existing dist folder)"
        
        # Verify dist folder exists
        if (-not (Test-Path $DistFolder)) {
            throw "Dist folder not found: $DistFolder. Run without -SkipPyInstaller first."
        }
    }

    # -------------------------------------------------------------------------
    # STEP 2: Inno Setup Compilation
    # -------------------------------------------------------------------------
    if (-not $SkipInnoSetup) {
        $stepNum++
        Write-Host ""
        Write-Step "$stepNum/$totalSteps" "Compiling Inno Setup..."
        
        # Find ISCC.exe
        $isccPath = Find-IsccExe
        if (-not $isccPath) {
            Write-Host ""
            Write-Host "ERROR: ISCC.exe (Inno Setup Compiler) not found." -ForegroundColor Red
            Write-Host ""
            Write-Host "Solutions:" -ForegroundColor Yellow
            Write-Host "  1. Install Inno Setup 6 from: https://jrsoftware.org/isinfo.php"
            Write-Host "  2. Or set ISCC_PATH environment variable:"
            Write-Host '     $env:ISCC_PATH = "D:\Path\To\ISCC.exe"'
            Write-Host ""
            throw "Inno Setup not found"
        }
        Write-Info "ISCC.exe: $isccPath"
        
        # Check ISS file exists
        if (-not (Test-Path $IssFile)) {
            throw "Inno Setup script not found: $IssFile"
        }
        Write-Info "Script: $IssFile"
        
        # Check icon file exists (required by ISS)
        $iconPath = "icons\app_icon.ico"
        if (-not (Test-Path $iconPath)) {
            Write-Host ""
            Write-Host "WARNING: Icon file not found: $iconPath" -ForegroundColor Yellow
            Write-Host "Run this first: python scripts\convert_svg_to_ico.py" -ForegroundColor Yellow
            Write-Host ""
        }
        
        # Run Inno Setup Compiler
        Write-Host ""
        & $isccPath $IssFile
        
        if ($LASTEXITCODE -ne 0) {
            throw "Inno Setup compilation failed with exit code $LASTEXITCODE"
        }
        
        # Find output file (pattern matches versioned filename)
        $outputPattern = Join-Path $OutputFolder "Petrophyter_Setup_*.exe"
        $installerFile = Get-ChildItem $outputPattern -ErrorAction SilentlyContinue | 
                         Sort-Object LastWriteTime -Descending | 
                         Select-Object -First 1
        
        if ($installerFile) {
            $installerSize = $installerFile.Length / 1MB
            Write-Host ""
            Write-Success "Inno Setup compilation completed!"
            Write-Info "Installer: $($installerFile.FullName)"
            Write-Info "Size: $([math]::Round($installerSize, 1)) MB"
        }
    }
    else {
        Write-Step "SKIP" "Inno Setup compilation"
    }

    # -------------------------------------------------------------------------
    # BUILD COMPLETE
    # -------------------------------------------------------------------------
    Write-Banner "BUILD SUCCESSFUL!" "Green"
    
    if (-not $SkipInnoSetup) {
        Write-Host "Output location:" -ForegroundColor White
        Write-Host "  $ProjectRoot\$OutputFolder\" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "The installer is ready for distribution!" -ForegroundColor Green
    }
    
    if (-not $SkipPyInstaller) {
        Write-Host ""
        Write-Host "Portable version (no installer):" -ForegroundColor White
        Write-Host "  $ProjectRoot\$DistFolder\" -ForegroundColor Cyan
    }
    
    Write-Host ""
}
catch {
    Write-Host ""
    Write-Host "=" * 60 -ForegroundColor Red
    Write-Host "  BUILD FAILED" -ForegroundColor Red
    Write-Host "=" * 60 -ForegroundColor Red
    Write-Host ""
    Write-Host "Error: $_" -ForegroundColor Red
    Write-Host ""
    exit 1
}
finally {
    Pop-Location
}
