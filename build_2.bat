@echo off
REM Petrophyter PyQt - Optimized Build Script
REM ==========================================
REM Uses petrophyter_pyqt_2.spec with reduced Qt modules
REM Expected dist size: ~30-50%% smaller than original

echo ============================================
echo   Petrophyter PyQt - OPTIMIZED Build
echo ============================================
echo.
echo This build excludes unused Qt modules:
echo   - Qt3D, QML, WebEngine, SQL, Multimedia
echo   - Network, PrintSupport, Bluetooth, etc.
echo.

REM Change to script directory
cd /d "%~dp0"

REM Initialize conda for batch file usage
echo Activating conda environment: qceda
if defined CONDA_EXE (
    REM Use CONDA_EXE if available
    for %%i in ("%CONDA_EXE%") do set "CONDA_ROOT=%%~dpi.."
) else (
    REM Try common conda installation paths
    if exist "%USERPROFILE%\anaconda3\Scripts\conda.exe" (
        set "CONDA_ROOT=%USERPROFILE%\anaconda3"
    ) else if exist "%USERPROFILE%\miniconda3\Scripts\conda.exe" (
        set "CONDA_ROOT=%USERPROFILE%\miniconda3"
    ) else if exist "C:\ProgramData\anaconda3\Scripts\conda.exe" (
        set "CONDA_ROOT=C:\ProgramData\anaconda3"
    ) else if exist "C:\ProgramData\miniconda3\Scripts\conda.exe" (
        set "CONDA_ROOT=C:\ProgramData\miniconda3"
    ) else (
        echo ERROR: Could not find conda installation
        echo Please run this script from an Anaconda/Miniconda prompt, or
        echo set CONDA_ROOT manually in the script
        pause
        exit /b 1
    )
)

REM Initialize conda
call "%CONDA_ROOT%\Scripts\activate.bat" "%CONDA_ROOT%"
if errorlevel 1 (
    echo ERROR: Failed to initialize conda
    pause
    exit /b 1
)

REM Activate the specific environment
call conda activate qceda
if errorlevel 1 (
    echo ERROR: Failed to activate conda environment 'qceda'
    echo Please ensure the environment exists: conda env list
    pause
    exit /b 1
)

REM Check if PyInstaller is installed
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    pip install pyinstaller
    if errorlevel 1 (
        echo ERROR: Failed to install PyInstaller
        pause
        exit /b 1
    )
)

echo.
echo Cleaning previous builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo Building Petrophyter executable (OPTIMIZED)...
echo Using: petrophyter_pyqt_2.spec
echo This may take a few minutes...
echo.

REM Build using optimized spec file
pyinstaller --clean --noconfirm petrophyter_pyqt_2.spec

if errorlevel 1 (
    echo.
    echo ============================================
    echo   BUILD FAILED!
    echo ============================================
    echo.
    echo Check the error messages above.
    echo Common issues:
    echo   - Missing dependencies
    echo   - Module import errors
    echo.
    pause
    exit /b 1
)

REM Calculate and display folder size
echo.
echo Calculating dist folder size...
for /f "tokens=3" %%a in ('dir /s /-c dist 2^>nul ^| findstr "bytes"') do set SIZE=%%a
echo.
echo ============================================
echo   BUILD SUCCESSFUL! (OPTIMIZED)
echo ============================================
echo.
echo Executable location: dist\Petrophyter\Petrophyter.exe
echo.
echo To distribute, copy the entire "dist\Petrophyter" folder.
echo.
echo TIP: Compare size with original build to see reduction.
echo.
pause
