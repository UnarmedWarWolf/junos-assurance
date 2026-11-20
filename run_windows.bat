@echo off
REM ==========================================================================
REM  Junos Assurance - Windows launcher
REM  Finds a working Python 3.9+, installs the required packages for your
REM  user account on first run, then starts the app.
REM  Run "run_windows.bat console" to keep a console window open for errors.
REM ==========================================================================
setlocal EnableExtensions
cd /d "%~dp0"
title Junos Assurance

REM ---- 1. Find a Python that really runs (skips the Microsoft Store stub)
set "PYEXE="
for %%C in ("py -3" "python" "python3") do (
  if not defined PYEXE (
    for /f "usebackq delims=" %%P in (`%%~C -c "import sys; assert sys.version_info >= (3, 9); print(sys.executable)" 2^>nul`) do set "PYEXE=%%P"
  )
)
if not defined PYEXE (
  echo.
  echo  Python 3.9 or newer was not found on this PC.
  echo  Install it from https://www.python.org/downloads/windows/
  echo  and tick "Add python.exe to PATH" during setup, then run this file again.
  echo.
  pause
  exit /b 1
)
echo Using Python: %PYEXE%

REM ---- 2. Install packages on first run
"%PYEXE%" -c "import PySide6, paramiko, openpyxl, docx, keyring" 1>nul 2>nul
if errorlevel 1 (
  echo.
  echo Installing required packages for first use - this can take a few minutes...
  "%PYEXE%" -m pip install --user --upgrade -r requirements.txt
  if errorlevel 1 "%PYEXE%" -m pip install --upgrade -r requirements.txt
  "%PYEXE%" -c "import PySide6, paramiko, openpyxl, docx, keyring" 1>nul 2>nul
  if errorlevel 1 (
    echo.
    echo  Package install failed. If you are behind a corporate proxy, run:
    echo      set HTTPS_PROXY=http://your-proxy:port
    echo  in this window and start run_windows.bat again, or ask IT to allow pypi.org.
    echo.
    pause
    exit /b 1
  )
)

REM ---- 3. Start the app (pythonw = no console window)
if /i "%~1"=="console" (
  "%PYEXE%" "%~dp0main.py"
  pause
  exit /b
)
set "PYW=%PYEXE:python.exe=pythonw.exe%"
if not exist "%PYW%" set "PYW=%PYEXE%"
start "" "%PYW%" "%~dp0main.py"
