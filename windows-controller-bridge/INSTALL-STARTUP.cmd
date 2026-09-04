@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$root='%~dp0'; & (Join-Path $root 'Start-SportsBigBoardControllerBridge.ps1'); $exe=Join-Path $env:LOCALAPPDATA 'SportsBigBoard\ControllerBridge\SportsBigBoardControllerBridge.exe'; if(!(Test-Path $exe)){throw 'Bridge executable not found'}; $startup=[Environment]::GetFolderPath('Startup'); $lnk=Join-Path $startup 'Sports Big Board Controller Bridge.lnk'; $w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut($lnk); $s.TargetPath=$exe; $s.WorkingDirectory=(Split-Path $exe); $s.Save(); Write-Host ('Installed startup shortcut: '+$lnk) -ForegroundColor Green"
if errorlevel 1 pause
endlocal
