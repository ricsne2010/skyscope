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

function Show-Note($text, $ms) {
    $note = New-Object System.Windows.Forms.NotifyIcon
    $note.Icon = New-Object System.Drawing.Icon (Join-Path $AppDir 'skyscope-start.ico')
    $note.Visible = $true
    $note.ShowBalloonTip($ms, 'SkyScope', $text, 'Info')
    return $note
}

if (Test-Up) {
    # already running: say so (the radar opens below)
    if (-not $NoBrowser) { $n = Show-Note 'SkyScope is already running. Opening the radar...' 3000; Start-Sleep -Seconds 3; $n.Dispose() }
} else {
    $argv = @("`"$(Join-Path $AppDir 'run.py')`"", '--tray')
    if (-not $cfg.phones) { $argv += @('--host', '127.0.0.1') }
    $exe = if ($cfg.exe -and (Test-Path $cfg.exe)) { $cfg.exe } else { Join-Path $AppDir 'venv\Scripts\pythonw.exe' }
    $p = Start-Process -FilePath $exe -ArgumentList $argv `
        -WorkingDirectory $AppDir -PassThru
    Set-Content -Path (Join-Path $AppDir 'skyscope.pid') -Value $p.Id

    $note = Show-Note 'Starting SkyScope...' 5000
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
