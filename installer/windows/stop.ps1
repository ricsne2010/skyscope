# Stop SkyScope: shuts it down. The radar stops until it's started again.
# -Quiet: no message afterwards (used by the installer and uninstaller).
# Designed and Created by Project Moon Pi.
param([switch]$Quiet)
$AppDir = $PSScriptRoot
$cfg = Get-Content (Join-Path $AppDir 'install.json') -Raw | ConvertFrom-Json
$port = $cfg.port
$pidFile = Join-Path $AppDir 'skyscope.pid'

function Test-Up {
    try { $null = Invoke-WebRequest "http://127.0.0.1:$port/radar" -UseBasicParsing -TimeoutSec 1; return $true }
    catch { return $false }
}
function Stop-IfPython($id) {
    # SkyScope.exe is Python under SkyScope's name (see brand_exe.py)
    $p = Get-Process -Id $id -ErrorAction SilentlyContinue
    if ($p -and ($p.ProcessName -like 'python*' -or $p.ProcessName -eq 'SkyScope')) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }
}
$wasUp = Test-Up
if (Test-Path $pidFile) {
    Stop-IfPython ([int](Get-Content $pidFile))
    Remove-Item $pidFile -ErrorAction SilentlyContinue
}
# also whatever Python program is serving SkyScope on our port (the real process behind the venv's launcher,
# or one started some other way)
Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-IfPython $_.OwningProcess }
# and its icon by the clock: it goes by itself within a few seconds of SkyScope (closing it by force would leave a
# dead icon there until the mouse passes over it), so only if it hasn't
for ($i = 0; $i -lt 16; $i++) {
    $icon = @(Get-Process -Name SkyScope -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$AppDir\*" })
    if (-not $icon) { break }
    Start-Sleep -Milliseconds 500
}
$icon | Stop-Process -Force -ErrorAction SilentlyContinue

$still = $true
for ($i = 0; $i -lt 20; $i++) {
    if (-not (Test-Up)) { $still = $false; break }
    Start-Sleep -Milliseconds 500
}
if (-not $Quiet) {
    $shell = New-Object -ComObject WScript.Shell
    if ($still) { $null = $shell.Popup("SkyScope is still running: something else may be using port $port.", 0, 'SkyScope', 48) }
    elseif ($wasUp) { $null = $shell.Popup('SkyScope has stopped.', 4, 'SkyScope', 64) }
    else { $null = $shell.Popup("SkyScope wasn't running.", 4, 'SkyScope', 64) }
}
