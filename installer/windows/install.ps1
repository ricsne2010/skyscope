# Install SkyScope on this PC (run by "Install SkyScope.bat"; run it again later to update; your settings are kept).
#
# Installs the program in %LOCALAPPDATA%\SkyScope and puts Start SkyScope and Stop SkyScope on the Desktop and in
# the Start menu. Needs Python 3.10 or newer from python.org.
# Designed and Created by Project Moon Pi.
#
# For unattended installs, answer the questions ahead: SS_PHONES=yes|no SS_AUTOSTART=yes|no SS_OPEN=no
$ErrorActionPreference = 'Stop'
$Src = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$AppDir = Join-Path $env:LOCALAPPDATA 'SkyScope'
Add-Type -AssemblyName System.Windows.Forms

function Ask($preset, $text) {
    if ($preset) { return $preset -eq 'yes' }
    return [System.Windows.Forms.MessageBox]::Show($text, 'Install SkyScope', 'YesNo', 'Question') -eq 'Yes'
}

function Run($exe, $argv, $what) {
    # pip writes notices on stderr; with 'Stop' Windows PowerShell 5.1 would treat them as fatal
    $ErrorActionPreference = 'Continue'
    & $exe @argv
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)" }
}

Write-Host 'SkyScope installer - Designed and Created by Project Moon Pi'

# Python 3.10 or newer: the "py" launcher from python.org, or python on the PATH
$check = @('-c', 'import sys; sys.exit(sys.version_info < (3, 10))')
$py = $null
foreach ($c in @(@{exe = 'py'; pre = @('-3')}, @{exe = 'python'; pre = @()})) {
    if (-not (Get-Command $c.exe -ErrorAction SilentlyContinue)) { continue }
    $argv = $c.pre + $check
    try { & $c.exe @argv 2>$null } catch { continue }    # e.g. the Microsoft Store's "python" placeholder
    if ($LASTEXITCODE -eq 0) { $py = $c; break }
}
if (-not $py) {
    Write-Host 'SkyScope needs Python 3.10 or newer from https://www.python.org/downloads/'
    $go = [System.Windows.Forms.MessageBox]::Show(
        "SkyScope needs Python 3.10 or newer.`n`nClick OK to open python.org. In the installer, tick `"Add python.exe to PATH`", then run Install SkyScope again.",
        'Install SkyScope', 'OKCancel', 'Information')
    if ($go -eq 'OK') { Start-Process 'https://www.python.org/downloads/' }
    exit 1
}

$phones = Ask $env:SS_PHONES "Should phones, tablets and SkyScope Satellite displays on your Wi-Fi be able to open SkyScope?`n`nThe settings page's About tab shows the address to use. If the firewall needs opening for them, Windows asks for permission once (click Yes)."
$autostart = Ask $env:SS_AUTOSTART "Start SkyScope by itself whenever you sign in to Windows?`n`nOtherwise, use the Start SkyScope icon when you want it."

# an update: stop the running copy first
if (Test-Path (Join-Path $AppDir 'stop.ps1')) { & (Join-Path $AppDir 'stop.ps1') -Quiet }

Write-Host "Installing into $AppDir (about a minute)..."
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
$venvPy = Join-Path $AppDir 'venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) { Run $py.exe ($py.pre + @('-m', 'venv', (Join-Path $AppDir 'venv'))) 'Setting up Python' }
Run $venvPy @('-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', '--upgrade', 'pip') 'Updating pip'
Run $venvPy @('-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', '--upgrade', 'pygame-ce') 'Installing pygame-ce'

# the program: replaced on every install; settings.json, the logo cache and the FlightAware count stay
foreach ($d in 'web', 'data', 'docs') { Remove-Item (Join-Path $AppDir $d) -Recurse -Force -ErrorAction SilentlyContinue }
Get-ChildItem $AppDir -Filter *.py -File | Remove-Item -Force
Copy-Item (Join-Path $Src '*.py') $AppDir -Force
foreach ($d in 'web', 'data', 'docs') { Copy-Item (Join-Path $Src $d) $AppDir -Recurse -Force }
foreach ($f in 'README.md', 'LICENSE') { if (Test-Path (Join-Path $Src $f)) { Copy-Item (Join-Path $Src $f) $AppDir -Force } }
foreach ($f in 'run.py', 'start.ps1', 'stop.ps1', 'uninstall.ps1', 'firewall.ps1') { Copy-Item (Join-Path $PSScriptRoot $f) $AppDir -Force }
foreach ($f in 'skyscope-start.ico', 'skyscope-stop.ico', 'skyscope.ico') { Copy-Item (Join-Path $Src "tools\launcher\$f") $AppDir -Force }
Get-ChildItem $AppDir -Recurse -File | Unblock-File      # drop the "downloaded from the internet" mark on our copies
Push-Location $AppDir
$version = & $venvPy -c 'from version import VERSION; print(VERSION)'
# (no double quotes inside: Windows PowerShell 5.1 drops them from a program's arguments)
$port = & $venvPy -c 'import json, os; p = ''settings.json''; print((json.load(open(p)).get(''web_port'') if os.path.exists(p) else 0) or 7700)'
Pop-Location
@{ port = [int]$port; phones = $phones; autostart = $autostart; version = "$version" } | ConvertTo-Json |
    Set-Content (Join-Path $AppDir 'install.json')

# shortcuts: Desktop and Start menu, plus the Startup folder when it should start at sign-in
$shell = New-Object -ComObject WScript.Shell
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
function New-Shortcut($path, $script, $icon, $desc, $extra = '') {
    $s = $shell.CreateShortcut($path)
    $s.TargetPath = $powershell
    $s.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$(Join-Path $AppDir $script)`" $extra"
    $s.IconLocation = "$(Join-Path $AppDir $icon),0"
    $s.WorkingDirectory = $AppDir
    $s.Description = $desc
    $s.WindowStyle = 7
    $s.Save()
}
$desktop = [Environment]::GetFolderPath('Desktop')
$menu = Join-Path ([Environment]::GetFolderPath('Programs')) 'SkyScope'
New-Item -ItemType Directory -Force -Path $menu | Out-Null
foreach ($dir in $desktop, $menu) {
    New-Shortcut (Join-Path $dir 'Start SkyScope.lnk') 'start.ps1' 'skyscope-start.ico' 'Start SkyScope and open the radar'
    New-Shortcut (Join-Path $dir 'Stop SkyScope.lnk') 'stop.ps1' 'skyscope-stop.ico' 'Stop SkyScope'
}
New-Shortcut (Join-Path $menu 'Uninstall SkyScope.lnk') 'uninstall.ps1' 'skyscope.ico' 'Remove SkyScope from this PC'
$startupLink = Join-Path ([Environment]::GetFolderPath('Startup')) 'SkyScope.lnk'
if ($autostart) { New-Shortcut $startupLink 'start.ps1' 'skyscope-start.ico' 'Start SkyScope at sign-in' '-NoBrowser' }
else { Remove-Item $startupLink -ErrorAction SilentlyContinue }

# phones and Satellites: make sure the firewall lets them in on home networks (Windows asks only if needed)
$fw = Join-Path $AppDir 'firewall.ps1'
$networkNote = ''
if ($phones) {
    $pythonw = & $venvPy -c "import os, sys; print(os.path.join(sys.base_prefix, 'pythonw.exe'))"   # the program that listens
    Write-Host 'Checking that phones on your home network can reach SkyScope...'
    $state = & $fw -Allow -Port ([int]$port) -Program $pythonw
    $public = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue | Where-Object NetworkCategory -eq 'Public').Count
    if ($state -eq 'Declined') {
        $networkNote = "Windows didn't allow the firewall change, so phones and Satellites can't reach SkyScope yet. Run the installer again and click Yes when Windows asks."
    } elseif ($public -and $state -ne 'AllowedPublic') {
        $networkNote = "This PC's network is set to Public, where Windows keeps other devices out. For phones and Satellites to reach SkyScope, set your home Wi-Fi to Private: Settings > Network & Internet > (your connection) > Private."
    }
} else {
    & $fw -Port ([int]$port)
}
if ($networkNote) { Write-Host $networkNote }

Write-Host "Installed SkyScope $version. Starting it..."
if ($env:SS_OPEN -eq 'no') { & (Join-Path $AppDir 'start.ps1') -NoBrowser } else { & (Join-Path $AppDir 'start.ps1') }
Write-Host 'Done. Use Start SkyScope and Stop SkyScope on your Desktop (also in the Start menu).'
if (-not $env:SS_PHONES) {
    [System.Windows.Forms.MessageBox]::Show(
        "SkyScope is installed and running.`n`nUse Start SkyScope and Stop SkyScope on your Desktop (also in the Start menu, under SkyScope).`n`nYou can delete the downloaded folder now." + $(if ($networkNote) { "`n`n$networkNote" } else { '' }),
        'Install SkyScope', 'OK', 'Information') | Out-Null
}
