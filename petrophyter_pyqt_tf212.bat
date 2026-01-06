@echo off
REM Petrophyter PyQt - Windows Launcher
REM ===================================
REM Uses Anaconda environment: tf212

echo Starting Petrophyter PyQt...
echo.

REM Change to script directory
cd /d "%~dp0"

REM Set Python path from Anaconda environment
set PYTHON_EXE=C:\ProgramData\anaconda3\envs\tf212\python.exe
set PIP_EXE=C:\ProgramData\anaconda3\envs\tf212\Scripts\pip.exe

REM Check if Python exists
if not exist "%PYTHON_EXE%" (
    echo ERROR: Python not found at: %PYTHON_EXE%
    echo Please ensure the Anaconda environment tf212 exists.
    pause
    exit /b 1
)

echo Using Python: %PYTHON_EXE%
echo.

REM Check if PyQt6 is installed
"%PYTHON_EXE%" -c "import PyQt6" 2>nul
if errorlevel 1 (
    echo Installing PyQt6 and dependencies...
    "%PIP_EXE%" install PyQt6 PyQt6-Qt6 matplotlib openpyxl
    if errorlevel 1 (
        echo ERROR: Failed to install dependencies
        pause
        exit /b 1
    )
)

REM Run the application
"%PYTHON_EXE%" main.py

if errorlevel 1 (
    echo.
    echo Application exited with error
    pause
)
