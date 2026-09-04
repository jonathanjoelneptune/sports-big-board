@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$lnk=Join-Path ([Environment]::GetFolderPath('Startup')) 'Sports Big Board Controller Bridge.lnk'; if(Test-Path $lnk){Remove-Item $lnk -Force; Write-Host 'Removed Sports Big Board Controller Bridge from Windows startup.' -ForegroundColor Green}else{Write-Host 'No startup shortcut was installed.'}"
if errorlevel 1 pause
endlocal
