@echo off
REM ==========================================================================
REM  AntennaMaster - one-command local install (Windows)
REM
REM     install.bat
REM
REM  Checks prerequisites, creates a Python virtualenv, installs backend and
REM  frontend dependencies, and builds the frontend. Re-runnable.
REM ==========================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ---- colour support (ANSI on Windows 10+) --------------------------------
for /f %%A in ('echo prompt $E ^| cmd') do set "ESC=%%A"
set "GRN=%ESC%[32m"
set "RED=%ESC%[31m"
set "BLU=%ESC%[36m"
set "BLD=%ESC%[1m"
set "RST=%ESC%[0m"

echo %BLD%AntennaMaster installer%RST%
echo Project: %CD%
echo.

REM ---- 1. prerequisites ----------------------------------------------------
echo %BLU%==^> Checking prerequisites%RST%

set "PYBIN="
for %%P in (python py) do (
  if not defined PYBIN (
    %%P -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3,10) else 1)" >nul 2>&1
    if !errorlevel! == 0 set "PYBIN=%%P"
  )
)
if not defined PYBIN (
  echo %RED%X Python 3.10+ is required. Install it from https://www.python.org/downloads/%RST%
  exit /b 1
)
for /f "delims=" %%V in ('!PYBIN! -c "import sys;print(''.join([str(x)+'.' for x in sys.version_info[:3]]).rstrip('.'))"') do set "PYVER=%%V"
echo   %GRN%OK%RST% Python !PYVER! (!PYBIN!)

where node >nul 2>&1
if errorlevel 1 (
  echo %RED%X Node.js is required. Install the LTS from https://nodejs.org/%RST%
  exit /b 1
)
for /f "delims=" %%V in ('node -v') do set "NODEVER=%%V"
echo   %GRN%OK%RST% Node.js !NODEVER!

REM ---- 2. python venv ------------------------------------------------------
echo %BLU%==^> Creating the Python virtual environment (backend\.venv)%RST%
if not exist "backend\.venv" (
  !PYBIN! -m venv backend\.venv
  if errorlevel 1 ( echo %RED%X venv creation failed%RST% & exit /b 1 )
)
set "VENV_PY=%CD%\backend\.venv\Scripts\python.exe"

REM ---- 3. backend deps -----------------------------------------------------
echo %BLU%==^> Installing backend dependencies%RST%
"%VENV_PY%" -m pip install --upgrade pip >nul
"%VENV_PY%" -m pip install -r backend\requirements.txt
if errorlevel 1 ( echo %RED%X Backend dependency install failed%RST% & exit /b 1 )
echo   %GRN%OK%RST% Backend dependencies installed

REM ---- 4. frontend deps + build --------------------------------------------
echo %BLU%==^> Installing frontend dependencies (npm)%RST%
pushd frontend
if exist package-lock.json ( call npm ci ) else ( call npm install )
if errorlevel 1 ( echo %RED%X npm install failed%RST% & popd & exit /b 1 )
echo %BLU%==^> Building the frontend (npm run build)%RST%
call npm run build
if errorlevel 1 ( echo %RED%X Frontend build failed%RST% & popd & exit /b 1 )
popd

echo.
echo %GRN%%BLD%Install complete.%RST%
echo.
echo Start the platform with:  %BLD%launch_simulator.bat%RST%
echo It will open http://localhost:3000 in your browser.
endlocal
