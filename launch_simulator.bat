@echo off
REM ==========================================================================
REM  AntennaMaster - production launch wrapper (Windows)
REM
REM     launch_simulator.bat              start both servers + open browser
REM     launch_simulator.bat --no-browser start without opening a browser
REM ==========================================================================
setlocal
cd /d "%~dp0"

set "BACKEND_PORT=8000"
set "FRONTEND_PORT=3000"
set "VENV_PY=%CD%\backend\.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
  echo Not installed. Run install.bat first.
  exit /b 1
)
if not exist "frontend\.next" (
  echo Frontend not built. Run install.bat first.
  exit /b 1
)

echo Starting AntennaMaster...

REM Backend in its own window.
start "AntennaMaster backend" cmd /c ^
  "cd /d "%CD%\backend" ^&^& "%VENV_PY%" -m uvicorn app.main:app --host 0.0.0.0 --port %BACKEND_PORT% --workers 2"

REM Frontend in its own window — standalone Node server (matches Docker).
start "AntennaMaster frontend" cmd /c ^
  "cd /d "%CD%\frontend\.next\standalone" ^&^& set PORT=%FRONTEND_PORT% ^&^& set HOSTNAME=0.0.0.0 ^&^& node server.js"

REM ---- wait for the frontend to answer -------------------------------------
echo Waiting for the servers to become healthy...
set /a tries=0
:waitloop
set /a tries+=1
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing http://localhost:%BACKEND_PORT%/api/health -TimeoutSec 2) ^| Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 goto ready
if %tries% GEQ 60 ( echo Timed out waiting for the backend. & exit /b 1 )
timeout /t 1 /nobreak >nul
goto waitloop

:ready
echo.
echo AntennaMaster is running.
echo   App:      http://localhost:%FRONTEND_PORT%
echo   API docs: http://localhost:%BACKEND_PORT%/docs
echo   Close the two server windows to stop.

if not "%1"=="--no-browser" (
  start "" "http://localhost:%FRONTEND_PORT%"
)
endlocal
