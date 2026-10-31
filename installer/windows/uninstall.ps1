# Uninstall SkyScope: removes it, its shortcuts and its settings.
# Designed and Created by Project Moon Pi.
$AppDir = $PSScriptRoot
Add-Type -AssemblyName System.Windows.Forms
$unattended = [bool]$env:SS_UNATTENDED     # no questions
if (-not $unattended) {
    $ok = [System.Windows.Forms.MessageBox]::Show("Remove SkyScope from this PC?`n`nIts settings (location, filters, FlightAware key) are removed too.", 'Uninstall SkyScope', 'OKCancel', 'Warning')
    if ($ok -ne 'OK') { exit 0 }
}
& (Join-Path $AppDir 'stop.ps1') -Quiet
$cfg = Get-Content (Join-Path $AppDir 'install.json') -Raw | ConvertFrom-Json
if (Test-Path (Join-Path $AppDir 'firewall.ps1')) { $null = & (Join-Path $AppDir 'firewall.ps1') -Port $cfg.port }   # close the port again

$desktop = [Environment]::GetFolderPath('Desktop')
Remove-Item (Join-Path $desktop 'Start SkyScope.lnk'), (Join-Path $desktop 'Stop SkyScope.lnk') -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath('Startup')) 'SkyScope.lnk') -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath('Programs')) 'SkyScope') -Recurse -ErrorAction SilentlyContinue

Set-Location $env:TEMP      # Windows won't delete a folder that's in use
Remove-Item $AppDir -Recurse -Force -ErrorAction SilentlyContinue
if (-not $unattended) {
    [System.Windows.Forms.MessageBox]::Show('SkyScope has been removed.', 'Uninstall SkyScope', 'OK', 'Information') | Out-Null
}
