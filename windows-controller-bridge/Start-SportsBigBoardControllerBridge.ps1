$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Source = Join-Path $Root 'SportsBigBoardControllerBridge.cs'
$Cache = Join-Path $env:LOCALAPPDATA 'SportsBigBoard\ControllerBridge'
$Exe = Join-Path $Cache 'SportsBigBoardControllerBridge.exe'
$Stamp = Join-Path $Cache 'source.sha256'
New-Item -ItemType Directory -Force -Path $Cache | Out-Null

function Stop-ExistingBridge {
    $Existing = @(Get-Process -Name 'SportsBigBoardControllerBridge' -ErrorAction SilentlyContinue)
    if (-not $Existing -or $Existing.Count -eq 0) { return }

    Write-Host 'Stopping the currently running Sports Big Board Controller Bridge for update...' -ForegroundColor Yellow
    $Existing | Stop-Process -Force -ErrorAction SilentlyContinue

    # Wait briefly for Windows to release the executable image/file handle.
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 100
        if (-not (Get-Process -Name 'SportsBigBoardControllerBridge' -ErrorAction SilentlyContinue)) { return }
    }
    throw 'Could not stop the existing Controller Bridge process. Close it from Task Manager and run this launcher again.'
}

function Replace-WithRetry([string]$From, [string]$To) {
    $last = $null
    for ($i = 0; $i -lt 20; $i++) {
        try {
            if (Test-Path $To) { Remove-Item -Force $To -ErrorAction Stop }
            Move-Item -Force $From $To -ErrorAction Stop
            return
        } catch {
            $last = $_
            Start-Sleep -Milliseconds 150
        }
    }
    if ($last) { throw $last }
    throw 'Could not replace Controller Bridge executable.'
}

$Hash = (Get-FileHash -Algorithm SHA256 $Source).Hash
$NeedBuild = -not (Test-Path $Exe) -or -not (Test-Path $Stamp) -or ((Get-Content $Stamp -ErrorAction SilentlyContinue) -ne $Hash)
$Existing = @(Get-Process -Name 'SportsBigBoardControllerBridge' -ErrorAction SilentlyContinue)

if ($NeedBuild) {
    # IMPORTANT: stop the old process BEFORE compiling/replacing the cached EXE.
    # v5.4.7 original launcher checked this too late, causing CS0016 on upgrades.
    Stop-ExistingBridge

    $Candidates = @(
        "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
        "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe"
    )
    $Csc = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $Csc) { throw 'Windows .NET Framework C# compiler was not found.' }

    $BuildExe = Join-Path $Cache ("SportsBigBoardControllerBridge.build." + [Guid]::NewGuid().ToString('N') + '.exe')
    try {
        Write-Host 'Building Sports Big Board Controller Bridge...' -ForegroundColor Cyan
        & $Csc /nologo /optimize+ /target:winexe /out:"$BuildExe" /reference:System.dll /reference:System.Core.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll "$Source"
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $BuildExe)) { throw 'Controller Bridge compilation failed.' }
        Replace-WithRetry -From $BuildExe -To $Exe
        Set-Content -NoNewline -Path $Stamp -Value $Hash
    } finally {
        if (Test-Path $BuildExe) { Remove-Item -Force $BuildExe -ErrorAction SilentlyContinue }
    }
}
elseif ($Existing.Count -gt 0) {
    Write-Host 'Sports Big Board Controller Bridge is already running and is up to date.' -ForegroundColor Green
    exit 0
}

Start-Process -FilePath $Exe
Write-Host 'Sports Big Board Controller Bridge started.' -ForegroundColor Green
Write-Host 'Return to Sports Big Board and press a controller button. The header should show BR READY, then BR LIVE.' -ForegroundColor DarkGray
