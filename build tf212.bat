@echo off
REM Petrophyter PyQt - Build Script
REM ================================
REM Creates portable executable using PyInstaller
REM Uses Conda environment: tf212

echo ============================================
echo   Petrophyter PyQt Build Script
echo   (Conda Environment: tf212)
echo ============================================
echo.

REM Change to script directory
cd /d "%~dp0"

REM Activate Conda environment tf212
echo Activating Conda environment: tf212...
call C:\ProgramData\anaconda3\Scripts\activate.bat C:\ProgramData\anaconda3\envs\tf212
if errorlevel 1 (
    echo ERROR: Failed to activate Conda environment tf212
    pause
    exit /b 1
)
echo Conda environment activated successfully.
echo.

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
echo Building Petrophyter executable...
echo This may take a few minutes...
echo.

REM Build using spec file (using python -m for conda compatibility)
python -m PyInstaller --clean --noconfirm petrophyter_pyqt.spec

if errorlevel 1 (
    echo.
    echo ============================================
    echo   BUILD FAILED!
    echo ============================================
    pause
    exit /b 1
)

echo.
echo ============================================
echo   BUILD SUCCESSFUL!
echo ============================================
echo.
echo Executable location: dist\Petrophyter\Petrophyter.exe
echo.
echo To distribute, copy the entire "dist\Petrophyter" folder.
echo.
pause

