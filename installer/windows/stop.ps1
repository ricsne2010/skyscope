# Stop SkyScope: shuts it down. The radar stops until it's started again.
# -Quiet: no message afterwards (used by the installer and uninstaller).
# Designed and Created by Project Moon Pi.
param([switch]$Quiet)
$AppDir = $PSScriptRoot
$cfg = Get-Content (Join-Path $AppDir 'install.json') -Raw | ConvertFrom-Json
$port = $cfg.port
$pidFile = Join-Path $AppDir 'skyscope.pid'

function Stop-IfPython($id) {
    $p = Get-Process -Id $id -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -like 'python*') { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }
}
if (Test-Path $pidFile) {
    Stop-IfPython ([int](Get-Content $pidFile))
    Remove-Item $pidFile -ErrorAction SilentlyContinue
}
# also whatever Python program is serving SkyScope on our port (the real process behind the venv's launcher,
# or one started some other way)
Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-IfPython $_.OwningProcess }

$still = $true
for ($i = 0; $i -lt 20; $i++) {
    try { $null = Invoke-WebRequest "http://127.0.0.1:$port/radar" -UseBasicParsing -TimeoutSec 1 }
    catch { $still = $false; break }
    Start-Sleep -Milliseconds 500
}
if (-not $Quiet) {
    $shell = New-Object -ComObject WScript.Shell
    if ($still) { $null = $shell.Popup("SkyScope is still running: something else may be using port $port.", 0, 'SkyScope', 48) }
    else { $null = $shell.Popup('SkyScope has stopped.', 4, 'SkyScope', 64) }
}
