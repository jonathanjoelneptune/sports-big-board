@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-SportsBigBoardControllerBridge.ps1"
if errorlevel 1 (
  echo.
  echo Controller Bridge failed to start.
  pause
)
endlocal
