@echo off
setlocal
cd /d "%~dp0"

set "SBBPY="
where python >nul 2>&1 && set "SBBPY=python"
if not defined SBBPY (
  where py >nul 2>&1 && set "SBBPY=py"
)
if not defined SBBPY (
  echo Python was not found. Install Python 3 and run this file again.
  pause
  exit /b 1
)

echo.
echo Sports Big Board v4.1.0 - Windows
echo ---------------------------------
%SBBPY% setup_credentials.py
if errorlevel 1 (
  echo API setup encountered an error.
  pause
  exit /b 1
)

%SBBPY% tools\ensure_history_v4.py
if errorlevel 1 (
  echo Historical catalog preflight failed. Existing database was left recoverable from backup.
  pause
  exit /b 1
)

echo.
echo Starting Sports Big Board at http://localhost:8080
start "" http://localhost:8080
%SBBPY% server.py
pause
