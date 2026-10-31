# Start SkyScope: starts it in the background if it isn't running, then opens the radar.
# -NoBrowser: start it without opening the radar (used at sign-in).
# Designed and Created by Project Moon Pi.
param([switch]$NoBrowser)
$AppDir = $PSScriptRoot
$cfg = Get-Content (Join-Path $AppDir 'install.json') -Raw | ConvertFrom-Json
$port = $cfg.port
Add-Type -AssemblyName System.Windows.Forms, System.Drawing

function Test-Up {
    try { $null = Invoke-WebRequest "http://127.0.0.1:$port/radar" -UseBasicParsing -TimeoutSec 2; return $true }
    catch { return $false }
}

if (-not (Test-Up)) {
    $argv = @("`"$(Join-Path $AppDir 'run.py')`"")
    if (-not $cfg.phones) { $argv += @('--host', '127.0.0.1') }
    $p = Start-Process -FilePath (Join-Path $AppDir 'venv\Scripts\pythonw.exe') -ArgumentList $argv `
        -WorkingDirectory $AppDir -PassThru
    Set-Content -Path (Join-Path $AppDir 'skyscope.pid') -Value $p.Id

    $note = New-Object System.Windows.Forms.NotifyIcon
    $note.Icon = New-Object System.Drawing.Icon (Join-Path $AppDir 'skyscope-start.ico')
    $note.Visible = $true
    $note.ShowBalloonTip(5000, 'SkyScope', 'Starting SkyScope...', 'Info')
    for ($i = 0; $i -lt 90; $i++) {
        if ((Test-Up) -or $p.HasExited) { break }
        Start-Sleep -Seconds 1
    }
    $note.Dispose()
    if (-not (Test-Up)) {
        [System.Windows.Forms.MessageBox]::Show("SkyScope didn't start. Its messages are in $(Join-Path $AppDir 'skyscope.log')", 'SkyScope', 'OK', 'Error') | Out-Null
        exit 1
    }
}
if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$port/radar" }
