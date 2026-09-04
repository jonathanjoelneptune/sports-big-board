$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Source = Join-Path $Root 'SportsBigBoardControllerBridge.cs'
$Cache = Join-Path $env:LOCALAPPDATA 'SportsBigBoard\ControllerBridge'
$Exe = Join-Path $Cache 'SportsBigBoardControllerBridge.exe'
$Stamp = Join-Path $Cache 'source.sha256'
New-Item -ItemType Directory -Force -Path $Cache | Out-Null

$Hash = (Get-FileHash -Algorithm SHA256 $Source).Hash
$NeedBuild = -not (Test-Path $Exe) -or -not (Test-Path $Stamp) -or ((Get-Content $Stamp -ErrorAction SilentlyContinue) -ne $Hash)
if ($NeedBuild) {
    $Candidates = @(
        "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
        "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe"
    )
    $Csc = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $Csc) { throw 'Windows .NET Framework C# compiler was not found.' }
    Write-Host 'Building Sports Big Board Controller Bridge...' -ForegroundColor Cyan
    & $Csc /nologo /optimize+ /target:winexe /out:"$Exe" /reference:System.dll /reference:System.Core.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll "$Source"
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $Exe)) { throw 'Controller Bridge compilation failed.' }
    Set-Content -NoNewline -Path $Stamp -Value $Hash
}

$Existing = Get-Process -Name 'SportsBigBoardControllerBridge' -ErrorAction SilentlyContinue
if ($Existing) {
    Write-Host 'Sports Big Board Controller Bridge is already running.' -ForegroundColor Green
    exit 0
}
Start-Process -FilePath $Exe
Write-Host 'Sports Big Board Controller Bridge started.' -ForegroundColor Green
Write-Host 'Return to Sports Big Board and press a controller button. The header should show BR READY, then BR LIVE.' -ForegroundColor DarkGray
