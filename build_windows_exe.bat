@echo off
REM ==========================================================================
REM  Builds a stand-alone Windows app so engineers don't need Python.
REM  Output: dist\JunosAssurance\JunosAssurance.exe  (zip and share that folder)
REM ==========================================================================
setlocal EnableExtensions
cd /d "%~dp0"
set "PYEXE="
for %%C in ("py -3" "python" "python3") do (
  if not defined PYEXE (
    for /f "usebackq delims=" %%P in (`%%~C -c "import sys; assert sys.version_info >= (3, 9); print(sys.executable)" 2^>nul`) do set "PYEXE=%%P"
  )
)
if not defined PYEXE (
  echo Python 3.9+ not found. Install it from https://www.python.org/downloads/windows/
  pause
  exit /b 1
)
echo Using Python: %PYEXE%
"%PYEXE%" -m pip install --user --upgrade -r requirements.txt pyinstaller
if errorlevel 1 "%PYEXE%" -m pip install --upgrade -r requirements.txt pyinstaller
"%PYEXE%" -m PyInstaller --noconfirm --clean --windowed --name JunosAssurance ^
  --collect-submodules keyring.backends --hidden-import win32ctypes.core ^
  --workpath "%TEMP%\JunosAssurance_build" main.py
if errorlevel 1 (
  echo Build failed - see messages above.
  pause
  exit /b 1
)
echo.
echo Done:  %~dp0dist\JunosAssurance\JunosAssurance.exe
pause
