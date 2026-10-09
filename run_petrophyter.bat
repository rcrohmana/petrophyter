@echo off
rem Launch Petrophyter from source by double-clicking this file.
rem Uses the "mldl" conda env (has pyqtgraph). Falls back to Anaconda base.
rem Run "run_petrophyter.bat debug" to keep a console window open for errors.

setlocal
cd /d "%~dp0"

set "ENV_DIR=%USERPROFILE%\anaconda3\envs\mldl"
if not exist "%ENV_DIR%\python.exe" (
    echo [!] Conda env "mldl" not found, falling back to Anaconda base.
    echo     The Interactive log engine needs pyqtgraph, so it will be unavailable.
    set "ENV_DIR=%USERPROFILE%\anaconda3"
)
if not exist "%ENV_DIR%\python.exe" (
    echo [x] Python not found at "%ENV_DIR%".
    pause
    exit /b 1
)

rem Make conda DLLs (Qt, MKL) resolvable without "conda activate".
set "PATH=%ENV_DIR%;%ENV_DIR%\Library\bin;%ENV_DIR%\Scripts;%PATH%"

if /i "%~1"=="debug" (
    "%ENV_DIR%\python.exe" main.py
    echo.
    echo Petrophyter exited with code %errorlevel%.
    pause
) else (
    start "" "%ENV_DIR%\pythonw.exe" main.py
)
endlocal
