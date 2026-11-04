# Uninstall SkyScope, in a window: removes it, its shortcuts and its settings. Python stays.
# Designed and Created by Project Moon Pi.
# -Quiet (or SS_UNATTENDED=1): no window, no questions
param([switch]$Quiet, [string]$Installed)    # (-Installed: the Start menu shortcut's install time, only so Windows lists it)
$AppDir = $PSScriptRoot
$unattended = $Quiet -or [bool]$env:SS_UNATTENDED
$UI_Unattended = $unattended
. (Join-Path $AppDir 'ui.ps1')
$ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
# the FlightAware key, when you ask to keep it (install.ps1's KeptKey: the next install puts it back)
$KeptKey = Join-Path $env:APPDATA 'Project Moon Pi\SkyScope FlightAware key.json'

function Main {
    # a FlightAware key: asked about on its own (it's yours, from FlightAware's site; kept, it comes back next time)
    $fa = $null
    try { $fa = Get-Content (Join-Path $AppDir 'settings.json') -Raw -ErrorAction Stop | ConvertFrom-Json } catch { }
    $key = if ($fa -and $fa.flightaware_key) { [string]$fa.flightaware_key } else { '' }
    $dropKey = $true
    if (-not $unattended) {
        UI-Open 'Uninstall SkyScope' (Join-Path $AppDir 'logo.png') (Join-Path $AppDir 'skyscope-uninstall.ico') 'SkyScope'
        $boxes = @()
        if ($key) {
            $tail = $key.Substring([Math]::Max(0, $key.Length - 4))
            $boxes = @(@{ text = "Also delete my FlightAware API key (ending $tail)"; checked = $true })
        }
        $text = "Remove SkyScope from this PC?`n`nIt stops SkyScope and removes the program, its shortcuts and its settings (location, filters). Python stays, for anything else that uses it."
        if ($key) { $text += "`n`nTo keep your FlightAware API key for next time, untick the box: installing SkyScope again puts it back." }
        $answers = UI-Choices $text $boxes 'Uninstall' -TextHeight $(if ($key) { 150 } else { 106 })
        # (the button says whether to go ahead: with no boxes, the answers are an empty list either way)
        if ($script:UI.Clicked -ne 'ok') { UI-Close; return }
        if ($key) { $dropKey = [bool]$answers[0] }
    }
    if ($key -and -not $dropKey) {
        New-Item -ItemType Directory -Force -Path (Split-Path $KeptKey) | Out-Null
        @{ flightaware_key = $key; flightaware_daily_limit = [string]$fa.flightaware_daily_limit } | ConvertTo-Json |
            Out-File $KeptKey -Encoding utf8
    } elseif ($key) {
        Remove-Item $KeptKey -ErrorAction SilentlyContinue      # (one kept from an earlier uninstall goes too)
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
    if (Test-Path $AppDir) {
        # something in it was still in use (as Uninstall SkyScope.exe can be, a moment longer): a moment later
        # rmdir /s gets the rest, and the Project Moon Pi folder if that's then empty
        $tidy = if ((Split-Path (Split-Path $AppDir) -Leaf) -eq 'Project Moon Pi') { " & rmdir `"$(Split-Path $AppDir)`" 2>nul" } else { '' }
        Start-Process -WindowStyle Hidden -FilePath (Join-Path $env:SystemRoot 'System32\cmd.exe') -WorkingDirectory $env:TEMP `
            -ArgumentList "/c ping -n 4 127.0.0.1 >nul & rmdir /s /q `"$AppDir`"$tidy"
        Start-Sleep -Seconds 4
    }
    # and the Project Moon Pi folder it was in, once it's empty (no other Project Moon Pi app left there)
    $parent = Split-Path $AppDir
    if ((Split-Path $parent -Leaf) -eq 'Project Moon Pi' -and -not (Get-ChildItem $parent -Force -ErrorAction SilentlyContinue)) {
        Remove-Item $parent -Force -ErrorAction SilentlyContinue
    }
    if (-not $unattended) {
        $left = Test-Path $AppDir
        $kept = if ($key -and -not $dropKey) { "`n`nYour FlightAware API key is kept on this PC: installing SkyScope again puts it back." } else { '' }
        $null = UI-Done ("SkyScope has been removed." + $kept + $(if ($left) { "`n`nA few files in $AppDir were in use; they go when you restart the PC, or you can delete that folder." } else { '' })) 'Close'
    }
}

try { Main }
catch {
    if ($unattended) { throw }
    UI-Error "SkyScope wasn't fully removed.`n`n$_"
}
