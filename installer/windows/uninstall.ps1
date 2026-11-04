# Uninstall SkyScope, in a window: removes it, its shortcuts and its settings. Python stays.
# Designed and Created by Project Moon Pi.
# -Quiet (or SS_UNATTENDED=1): no window, no questions
param([switch]$Quiet, [string]$Installed)    # (-Installed: the Start menu shortcut's install time, only so Windows lists it)
$AppDir = $PSScriptRoot
$unattended = $Quiet -or [bool]$env:SS_UNATTENDED
$UI_Unattended = $unattended
. (Join-Path $AppDir 'ui.ps1')
$ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

function Main {
    if (-not $unattended) {
        UI-Open 'Uninstall SkyScope' (Join-Path $AppDir 'logo.png') (Join-Path $AppDir 'skyscope-uninstall.ico') 'SkyScope'
        $null = UI-Choices "Remove SkyScope from this PC?`n`nIt stops SkyScope and removes the program, its shortcuts and its settings (location, filters, FlightAware key). Python stays, for anything else that uses it." @() 'Uninstall'
        # (no boxes, so it returns nothing either way: the button says)
        if ($script:UI.Clicked -ne 'ok') { UI-Close; return }
    }

    if (-not $unattended) { UI-Progress 'Stopping SkyScope...' 10 }
    $p = Start-Process $ps -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', "`"$(Join-Path $AppDir 'stop.ps1')`"", '-Quiet') -WindowStyle Hidden -PassThru
    if ($unattended) { $p.WaitForExit() } else { $null = UI-Wait $p 40 10 }
    $cfg = Get-Content (Join-Path $AppDir 'install.json') -Raw | ConvertFrom-Json

    # close the port for phones and Satellites (Windows asks for permission only if there's a rule to remove;
    # firewall.ps1 says so first)
    if (-not $unattended) { UI-Progress 'Closing the firewall for phones and Satellites...' 50 }
    if (Test-Path (Join-Path $AppDir 'firewall.ps1')) { $null = & (Join-Path $AppDir 'firewall.ps1') -Port $cfg.port -Quiet:$unattended }

    if (-not $unattended) { UI-Progress 'Removing the shortcuts...' 65 }
    $desktop = [Environment]::GetFolderPath('Desktop')
    Remove-Item (Join-Path $desktop 'Start SkyScope.lnk'), (Join-Path $desktop 'Stop SkyScope.lnk'),
        (Join-Path $desktop 'Uninstall SkyScope.lnk') -ErrorAction SilentlyContinue
    Remove-Item 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ProjectMoonPi.SkyScope' -Recurse -ErrorAction SilentlyContinue   # Settings > Apps
    Remove-Item (Join-Path ([Environment]::GetFolderPath('Startup')) 'SkyScope.lnk') -ErrorAction SilentlyContinue
    Remove-Item (Join-Path ([Environment]::GetFolderPath('Programs')) 'SkyScope') -Recurse -ErrorAction SilentlyContinue

    if (-not $unattended) { UI-Progress 'Removing the program and its settings...' 90 }
    # Windows won't delete a folder a program is in: step out of it (PowerShell's location and the process's own)
    Set-Location $env:TEMP
    [Environment]::CurrentDirectory = $env:TEMP
    Remove-Item $AppDir -Recurse -Force -ErrorAction SilentlyContinue
    # and the Project Moon Pi folder it was in, once it's empty (no other Project Moon Pi app left there)
    $parent = Split-Path $AppDir
    if ((Split-Path $parent -Leaf) -eq 'Project Moon Pi' -and -not (Get-ChildItem $parent -Force -ErrorAction SilentlyContinue)) {
        Remove-Item $parent -Force -ErrorAction SilentlyContinue
    }
    if (-not $unattended) {
        $left = Test-Path $AppDir
        $null = UI-Done ("SkyScope has been removed." + $(if ($left) { "`n`nA few files in $AppDir were in use; they go when you restart the PC, or you can delete that folder." } else { '' })) 'Close'
    }
}

try { Main }
catch {
    if ($unattended) { throw }
    UI-Error "SkyScope wasn't fully removed.`n`n$_"
}
