# Makes SkyScope shortcuts, with the radar-screen icon, on the Desktop and in
# the Start menu. Clicking one starts SkyScope in the background (if it isn't
# running) and opens the radar in your browser. Run it through
# create-shortcut.bat (double-click), or:
#   powershell -ExecutionPolicy Bypass -File tools\windows\create-shortcut.ps1
# Run it again if you move the SkyScope folder or reinstall Python.
# Not 'Stop': Windows PowerShell 5.1 would treat pip's warnings on stderr as fatal.
$ErrorActionPreference = 'Continue'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

function Find-Python {
    # The py launcher (python.org installs) first, then python on PATH. The
    # Microsoft Store placeholder "python" prints nothing, so check the answer.
    $tries = @(@('py', '-3'), @('python'))
    foreach ($t in $tries) {
        $exe = $t[0]
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $pyArgs = @()
        if ($t.Count -gt 1) { $pyArgs += $t[1..($t.Count - 1)] }
        $pyArgs += @('-c', 'import sys; print(sys.executable)')
        try { $out = & $exe @pyArgs 2>$null } catch { continue }
        if ($out -and (Test-Path $out)) { return $out.Trim() }
    }
    return $null
}

Write-Host ''
Write-Host 'SkyScope shortcut setup' -ForegroundColor Green
Write-Host "SkyScope folder: $root"

$python = Find-Python
if (-not $python) {
    Write-Host ''
    Write-Host 'Python was not found.' -ForegroundColor Red
    Write-Host 'Install Python 3.10 or newer from https://www.python.org/downloads/'
    Write-Host '(tick "Add python.exe to PATH" in the installer), then run this again.'
    exit 1
}
Write-Host "Python: $python"

$version = & $python -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ([version]$version -lt [version]'3.10') {
    Write-Host "Python $version is too old: SkyScope needs 3.10 or newer." -ForegroundColor Red
    exit 1
}

$env:PYGAME_HIDE_SUPPORT_PROMPT = '1'
& $python -c 'import pygame' 2>$null
if ($LASTEXITCODE -ne 0) {
    # pygame-ce: the community edition of pygame, a drop-in replacement with
    # ready-made packages for the newest Python versions.
    Write-Host 'Installing pygame-ce (SkyScope needs it)...'
    & $python -m pip install --user --disable-pip-version-check pygame-ce
    & $python -c 'import pygame' 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host ''
        Write-Host 'pygame-ce could not be installed for this Python.' -ForegroundColor Red
        Write-Host 'Check the internet connection and run this again. If it still fails, install'
        Write-Host 'the previous Python version from python.org and try again.'
        exit 1
    }
}

# pythonw.exe runs SkyScope without a console window.
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path $pythonw)) { $pythonw = $python }

$shell = New-Object -ComObject WScript.Shell
$places = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))
foreach ($dir in $places) {
    $link = $shell.CreateShortcut((Join-Path $dir 'SkyScope.lnk'))
    $link.TargetPath = $pythonw
    $link.Arguments = '"' + (Join-Path $root 'tools\launch.py') + '"'
    $link.WorkingDirectory = $root
    $link.IconLocation = (Join-Path $root 'tools\launcher\skyscope.ico') + ',0'
    $link.Description = 'Start SkyScope and open the radar'
    $link.Save()
    Write-Host "Made $(Join-Path $dir 'SkyScope.lnk')"
}
Write-Host ''
Write-Host 'Done. Double-click SkyScope on the Desktop (or find it in the Start menu).' -ForegroundColor Green
Write-Host 'The first time, Windows may ask whether Python can use the network: allow it'
Write-Host 'on private networks so phones and Satellites can reach SkyScope.'
