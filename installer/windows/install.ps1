# Install SkyScope on this PC, in a window (started by "Install SkyScope.exe"; run it again later to update; your
# settings are kept).
#
# Installs the program in %LOCALAPPDATA%\SkyScope (or a folder you choose), with Uninstall SkyScope.exe in it; puts
# Start, Stop and Remove SkyScope (the uninstaller) in the Start menu, and Start and Stop on the Desktop if you like; and lists it in
# Windows' Settings > Apps (with its Uninstall button). Needs Python 3.10 or newer; if it
# isn't there, it installs Python from python.org for this user only (checked: the expected download, signed by the
# Python Software Foundation). What it does is logged in %TEMP%\SkyScope install.log.
# Designed and Created by Project Moon Pi.
#
# SS_MODE=update|repair|fresh: what to do when it's already installed (unattended installs; otherwise the window asks).
# For unattended installs, answer the questions ahead: SS_PHONES=yes|no SS_AUTOSTART=yes|no SS_DESKTOP=yes|no
# SS_OPEN=no SS_PYTHON=yes|no (install Python if needed) SS_DIR=<folder>; the window then needs no clicks.
$ErrorActionPreference = 'Stop'
$Src = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
# (Project Moon Pi's apps go together under %LOCALAPPDATA%\Programs\Project Moon Pi, where Windows keeps programs installed
# for one user; earlier installs elsewhere stay where they are when updated)
$DefaultDir = Join-Path $env:LOCALAPPDATA 'Programs\Project Moon Pi\SkyScope'
$AppDir = $DefaultDir      # (the folder chosen in the window)
$UninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ProjectMoonPi.SkyScope'
$Log = Join-Path $env:TEMP 'SkyScope install.log'
$UI_Unattended = [bool]$env:SS_PHONES
"== $(Get-Date) SkyScope installer" | Out-File $Log -Append -Encoding utf8    # (Install SkyScope.exe reads from here)
# anything that stops it before its window is up goes in the log too; "Install SkyScope.exe" then shows it (a hidden
# PowerShell has no other way to tell anyone)
trap {
    "$(Get-Date -Format 'HH:mm:ss') ERROR before the window opened: $_ $($_.InvocationInfo.PositionMessage)" |
        Out-File $Log -Append -Encoding utf8
    exit 2
}
. (Join-Path $PSScriptRoot 'ui.ps1')

function Log($text) { "$(Get-Date -Format 'HH:mm:ss') $text" | Out-File $Log -Append -Encoding utf8 }

function Run($exe, $argv, $what, $upTo, $seconds = 60) {
    # a program run hidden, its output in the log, while the window keeps going
    Log "$what`: $exe $($argv -join ' ')"
    $out = Join-Path $env:TEMP "ss-step-$PID.txt"
    $p = Start-Process $exe -ArgumentList ($argv | ForEach-Object { if ($_ -match '\s') { "`"$_`"" } else { $_ } }) `
        -NoNewWindow -PassThru -RedirectStandardOutput $out -RedirectStandardError "$out.err"
    $code = UI-Wait $p $upTo $seconds
    $text = (Get-Content $out, "$out.err" -Raw -ErrorAction SilentlyContinue) -join ''
    Remove-Item $out, "$out.err" -ErrorAction SilentlyContinue
    if ($text) { Log $text.Trim() }
    if ($code -ne 0) { throw "$what didn't work (exit code $code)." }
    return $text
}

# Python 3.10 or newer: the "py" launcher from python.org, python on the PATH, a Python Windows has on record as
# installed, or python.org's usual folders (a window opened before Python was installed still has the old PATH)
function Find-Python {
    $env:Path = (@($env:Path, [Environment]::GetEnvironmentVariable('Path', 'User'),
                   [Environment]::GetEnvironmentVariable('Path', 'Machine')) | Where-Object { $_ }) -join ';'
    $check = @('-c', 'import sys; sys.exit(sys.version_info < (3, 10))')
    $found = @(@{exe = 'py'; pre = @('-3')}, @{exe = 'python'; pre = @()})
    foreach ($key in 'HKCU:\Software\Python\PythonCore', 'HKLM:\Software\Python\PythonCore',
                     'HKLM:\Software\WOW6432Node\Python\PythonCore') {
        Get-ChildItem $key -ErrorAction SilentlyContinue | ForEach-Object {
            $exe = (Get-ItemProperty (Join-Path $_.PSPath 'InstallPath') -ErrorAction SilentlyContinue).ExecutablePath
            if ($exe -and (Test-Path $exe)) { $found += @{exe = $exe; pre = @()} }
        }
    }
    $found += @(Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python3*\python.exe'), (Join-Path $env:ProgramFiles 'Python3*\python.exe') -ErrorAction SilentlyContinue |
        Sort-Object { [int]($_.Directory.Name -replace '\D', '') } -Descending | ForEach-Object { @{exe = $_.FullName; pre = @()} })
    foreach ($c in $found) {
        if (-not (Get-Command $c.exe -ErrorAction SilentlyContinue)) { continue }
        $argv = $c.pre + $check
        try { & $c.exe @argv 2>$null } catch { continue }    # e.g. the Microsoft Store's "python" placeholder
        if ($LASTEXITCODE -eq 0) { return $c }
    }
    return $null
}

# otherwise Python from python.org, installed for this user only (no admin needed). This version is the one
# SkyScope's packages were tested with; move it on (with its checksums) once a newer one has been tried.
$PyVersion = '3.15.2'
$PyFiles = @{    # the installer for each kind of PC, and its SHA-256 from python.org
    AMD64 = @{file = "python-$PyVersion-amd64.exe"; sha256 = '06e225a228191b0f4d1dcf6905fbb21bf9f6970d13a2ec63137ab9bee76f15aa'}
    ARM64 = @{file = "python-$PyVersion-arm64.exe"; sha256 = 'a3957667a6305f0fa4c5ce6c73def927ddcad36190b9e27eb4a04e1a9a153c93'}
    x86   = @{file = "python-$PyVersion.exe";       sha256 = 'a1040151c8af7a31dcfa3d4da2648040806dfe86050622166cbebc7747f23027'}
}

function Install-Python {
    $arch = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
    $want = $PyFiles[$arch]
    if (-not $want) { $want = $PyFiles['x86'] }
    $exe = Join-Path $env:TEMP $want.file
    $url = "https://www.python.org/ftp/python/$PyVersion/$($want.file)"
    Log "downloading $url"
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    # downloaded in the background, the bar following the file's size (Windows PowerShell can't run script code on
    # the download's own progress events, so they're only used to say it's finished)
    try {
        $head = [Net.WebRequest]::Create($url); $head.Method = 'HEAD'
        $r = $head.GetResponse(); $total = $r.ContentLength; $r.Close()
    } catch { throw "Python couldn't be downloaded. Check the internet connection, then run the installer again." }
    $wc = New-Object System.Net.WebClient
    $null = Register-ObjectEvent $wc DownloadFileCompleted -SourceIdentifier 'ss-python-download'
    $wc.DownloadFileAsync([Uri]$url, $exe)
    $finished = $null
    while (-not $finished) {
        $have = (Get-Item $exe -ErrorAction SilentlyContinue).Length
        $pc = if ($total -gt 0 -and $have) { [Math]::Min(100, [int](100 * $have / $total)) } else { 0 }
        UI-Progress "Downloading Python $PyVersion from python.org..." (2 + 18 * $pc / 100) "$pc% of $([Math]::Round($total / 1MB)) MB"
        Start-Sleep -Milliseconds 60
        $finished = Get-Event -SourceIdentifier 'ss-python-download' -ErrorAction SilentlyContinue
    }
    $err = $finished.SourceEventArgs.Error
    Unregister-Event -SourceIdentifier 'ss-python-download'; Remove-Event -SourceIdentifier 'ss-python-download'
    if ($err) { Log "download: $err"; throw "Python couldn't be downloaded. Check the internet connection, then run the installer again." }
    try {
        UI-Progress 'Checking the Python download...' 21
        if ((Get-FileHash $exe -Algorithm SHA256).Hash -ne $want.sha256) {
            throw "The Python download wasn't the expected file, so it wasn't installed."
        }
        $sig = Get-AuthenticodeSignature $exe
        if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'O="?Python Software Foundation') {
            throw "The Python download isn't signed by the Python Software Foundation, so it wasn't installed."
        }
        UI-Progress "Installing Python $PyVersion for you..." 22 'This takes a minute or two.'
        $p = Start-Process $exe -PassThru -ArgumentList @('/quiet', 'InstallAllUsers=0', 'PrependPath=1',
            'Include_launcher=1', 'InstallLauncherAllUsers=0', 'Include_test=0', 'Include_doc=0')
        $code = UI-Wait $p 40 90
        Log "Python installer exit code $code"
        if ($code -notin 0, 3010) { throw "Python's installer stopped (exit code $code)." }
    } finally { Remove-Item $exe -Force -ErrorAction SilentlyContinue }
}

# Where it's installed now, if anywhere (Settings > Apps knows), so an update goes to the same place
function Installed-Dir {
    $at = (Get-ItemProperty $UninstallKey -ErrorAction SilentlyContinue).InstallLocation
    if ($at -and (Test-Path (Join-Path $at 'install.json'))) { return $at }
    $before = Join-Path $env:LOCALAPPDATA 'SkyScope'      # (the default before)
    if (Test-Path (Join-Path $before 'install.json')) { return $before }
    return $null
}

# The folder SkyScope goes in: the one chosen, unless that already holds other things (then a SkyScope folder inside
# it), so uninstalling can never take anything else with it
function Resolve-AppDir($chosen) {
    $chosen = [Environment]::ExpandEnvironmentVariables($chosen).TrimEnd('\')
    if ((Test-Path $chosen) -and (Get-ChildItem $chosen -Force -ErrorAction SilentlyContinue | Select-Object -First 1) -and
        -not (Test-Path (Join-Path $chosen 'install.json')) -and (Split-Path $chosen -Leaf) -ne 'SkyScope') {
        return Join-Path $chosen 'SkyScope'
    }
    return $chosen
}

function Check-Folder($path) {
    # an error to show, or nothing if SkyScope can go there
    if (-not $path -or -not [IO.Path]::IsPathRooted([Environment]::ExpandEnvironmentVariables($path))) { return 'Choose a whole folder path, such as C:\Users\you\Apps.' }
    $dir = Resolve-AppDir $path
    foreach ($bad in $env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:SystemRoot) {
        if ($bad -and $dir.StartsWith($bad, [StringComparison]::OrdinalIgnoreCase)) {
            return "SkyScope installs just for you, without asking for admin permission, so it can't go in $bad. Choose a folder of your own, such as the one it suggests."
        }
    }
    try {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        $probe = Join-Path $dir ".write-test-$PID"
        Set-Content $probe 'ok'; Remove-Item $probe
    } catch { return "SkyScope can't write to $dir. Choose another folder." }
    return $null
}

# Installing needs the internet (Python from python.org, SkyScope's packages from pypi.org): check first, before
# anything is changed
function Test-Internet {
    foreach ($url in 'https://pypi.org/simple/pip/', 'https://www.python.org/') {
        try {
            $r = [Net.WebRequest]::Create($url); $r.Method = 'HEAD'; $r.Timeout = 10000
            $r.GetResponse().Close()
            return $true
        } catch { Log "no answer from $url`: $($_.Exception.InnerException.Message)" }
    }
    return $false
}

function Newer($a, $b) {
    # is version $a newer than $b? (1 newer, 0 the same, -1 older)
    try { return ([version]$a).CompareTo([version]$b) } catch { return [string]::Compare("$a", "$b") }
}

function Main {
    UI-Open 'Install SkyScope' (Join-Path $Src 'docs\images\moon-pi-logo-128.png') (Join-Path $Src 'tools\launcher\skyscope.ico') 'SkyScope'
    Log 'window shown'

    $py = Find-Python
    $intro = "A live aircraft radar, in your web browser. This installs SkyScope for you on this PC; it runs quietly in the background, with a radar icon by the clock."
    if (-not $py) { $intro += "`n`nIt also installs Python $PyVersion from python.org (about 36 MB), which SkyScope runs on." }
    $was = Installed-Dir
    $suggest = if ($env:SS_DIR) { $env:SS_DIR } elseif ($was) { $was } else { $DefaultDir }

    # already installed? Then update (this one's newer), repair (the same) or reinstall from scratch; the choices
    # start as the installed copy has them
    $newVersion = (Select-String -Path (Join-Path $Src 'version.py') -Pattern 'VERSION = "([^"]+)"').Matches[0].Groups[1].Value
    $have = if ($was) { (Get-ItemProperty $UninstallKey -ErrorAction SilentlyContinue).DisplayVersion } else { $null }
    if ($was -and -not $have) { try { $have = (Get-Content (Join-Path $was 'install.json') -Raw | ConvertFrom-Json).version } catch { } }
    $prev = $null
    if ($was) { try { $prev = Get-Content (Join-Path $was 'install.json') -Raw | ConvertFrom-Json } catch { } }
    $fresh = "Reinstall from scratch (keeps your settings and FlightAware key)"
    $modes = @('install'); $options = @(); $okText = 'Install'
    if ($have) {
        $okText = 'Continue'
        switch (Newer $newVersion $have) {
            1 { $intro = "SkyScope $have is installed on this PC. This installer has version $newVersion.`n`nUpdate keeps everything as it is; reinstalling from scratch removes the program first."
                $options = @("Update to $newVersion", $fresh); $modes = @('update', 'fresh') }
            0 { $intro = "SkyScope $have is already installed on this PC.`n`nRepair installs it again over itself and rebuilds its Python set-up; reinstalling from scratch removes the program first. Both keep your settings."
                $options = @("Repair", $fresh); $modes = @('repair', 'fresh') }
            default { $intro = "A newer SkyScope ($have) is installed on this PC than this installer's version ($newVersion).`n`nClick Cancel to keep the newer one."
                $options = @("Install $newVersion over it anyway", $fresh); $modes = @('update', 'fresh') }
        }
        if (-not $py) { $intro += "`n`nIt also installs Python $PyVersion from python.org, which SkyScope runs on." }
    }
    $wasPhones = if ($prev) { [bool]$prev.phones } else { $true }
    $wasAuto = if ($prev) { [bool]$prev.autostart } else { $false }
    $wasDesk = if ($prev -and $null -ne $prev.desktop) { [bool]$prev.desktop } else { $true }
    $choices = UI-Choices $intro @(
        @{ text = "Let phones, tablets and SkyScope Satellite displays on my Wi-Fi open it"; checked = $(if ($env:SS_PHONES) { $env:SS_PHONES -ne 'no' } else { $wasPhones }) },
        @{ text = "Start SkyScope when I sign in to Windows"; checked = $(if ($env:SS_AUTOSTART) { $env:SS_AUTOSTART -eq 'yes' } else { $wasAuto }) },
        @{ text = "Put Start and Stop SkyScope on the Desktop"; checked = $(if ($env:SS_DESKTOP) { $env:SS_DESKTOP -ne 'no' } else { $wasDesk }) }) $okText `
        -Folder $suggest -FolderCheck { param($path) Check-Folder $path } -Options $options
    if ($null -eq $choices) { UI-Close; return }
    $mode = $modes[$UI_Option]
    if ($UI_Unattended -and $env:SS_MODE -and $have) { $mode = $env:SS_MODE }
    $phones, $autostart, $onDesktop = $choices
    if ($UI_Unattended) { $phones = $env:SS_PHONES -eq 'yes'; $autostart = $env:SS_AUTOSTART -eq 'yes'; $onDesktop = $env:SS_DESKTOP -ne 'no' }
    $problem = Check-Folder $UI_Folder
    if ($problem) { throw $problem }
    $script:AppDir = Resolve-AppDir $UI_Folder
    Log "mode=$mode ($have -> $newVersion) folder=$AppDir phones=$phones autostart=$autostart desktop=$onDesktop"

    UI-Progress 'Checking the internet connection...' 1
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    if (-not (Test-Internet)) {
        throw ("Installing needs an internet connection, to download what SkyScope runs on from python.org and " +
               "pypi.org, and this PC can't reach them. Nothing was changed" + $(if ($was) { ': the SkyScope you have keeps working' } else { '' }) +
               ". Connect to the internet, then run the installer again.")
    }

    if (-not $py) {
        if ($env:SS_PYTHON -eq 'no') { throw 'SkyScope needs Python 3.10 or newer, and this PC doesn''t have it.' }
        Install-Python
        $py = Find-Python
        if (-not $py) { throw 'Python was installed but can''t be found. Restart the PC and run the installer again.' }
    }

    # an update: stop the running copy first (also one in another folder, when it's moving)
    UI-Progress 'Getting ready...' 42
    $ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $others = @($was) | Where-Object { $_ -and $_ -ne $AppDir -and (Test-Path $_) }
    foreach ($d in @($AppDir) + $others) {
        if (Test-Path (Join-Path $d 'stop.ps1')) {
            # (if this install goes wrong after this, the copy that was running is started again)
            $p = 7700
            try { $p = (Get-Content (Join-Path $d 'install.json') -Raw | ConvertFrom-Json).port } catch { }
            try { $null = Invoke-WebRequest "http://127.0.0.1:$p/radar" -UseBasicParsing -TimeoutSec 2; $script:WasRunning = $d } catch { }
            $null = Run $ps @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $d 'stop.ps1'), '-Quiet') 'Stopping SkyScope' 45 10
        }
    }

    if ($mode -eq 'fresh' -and (Test-Path (Join-Path $AppDir 'install.json'))) {
        # from scratch: everything in the program's folder goes except your settings, the logo cache and the
        # FlightAware count
        UI-Progress 'Removing the installed copy...' 44
        Get-ChildItem $AppDir -Force | Where-Object { $_.Name -notin 'settings.json', 'flightaware_usage.json', 'logos_cache' } |
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
    if ($mode -eq 'repair') { Remove-Item (Join-Path $AppDir 'venv') -Recurse -Force -ErrorAction SilentlyContinue }   # rebuilt below
    # moving: your settings, the logo cache and the FlightAware count come along
    foreach ($d in $others) {
        foreach ($f in 'settings.json', 'flightaware_usage.json', 'logos_cache') {
            $from = Join-Path $d $f
            if ((Test-Path $from) -and -not (Test-Path (Join-Path $AppDir $f))) { Copy-Item $from $AppDir -Recurse -Force }
        }
    }
    $venvPy = Join-Path $AppDir 'venv\Scripts\python.exe'
    # a fresh environment if there's none, or its Python was removed or is too old
    $venvOk = $false
    if (Test-Path $venvPy) {
        try { & $venvPy -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>$null; $venvOk = $LASTEXITCODE -eq 0 } catch { }
    }
    if (-not $venvOk) {
        UI-Progress 'Setting up Python for SkyScope...' 45
        Remove-Item (Join-Path $AppDir 'venv') -Recurse -Force -ErrorAction SilentlyContinue
        $null = Run $py.exe ($py.pre + @('-m', 'venv', (Join-Path $AppDir 'venv'))) 'Setting up Python' 52 20
    }
    UI-Progress 'Installing what SkyScope runs on...' 52 'Downloading pygame-ce; about a minute.'
    try { $null = Run $venvPy @('-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', '--upgrade', 'pip') 'Updating pip' 56 20 }
    catch { Log "$_ - carrying on with the pip it has" }
    $null = Run $venvPy @('-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', '--upgrade', 'pygame-ce') 'Installing pygame-ce' 68 60
    # pystray and Pillow put SkyScope's icon by the clock; without them it runs without the icon
    UI-Progress 'Installing the icon by the clock...' 68
    try { $null = Run $venvPy @('-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', '--upgrade', 'pystray', 'pillow') 'Installing pystray and Pillow' 76 30 }
    catch { Log "$_ - no icon by the clock" }

    # the program: replaced on every install; settings.json, the logo cache and the FlightAware count stay
    UI-Progress 'Copying SkyScope...' 77
    foreach ($d in 'web', 'data', 'docs') { Remove-Item (Join-Path $AppDir $d) -Recurse -Force -ErrorAction SilentlyContinue }
    Get-ChildItem $AppDir -Filter *.py -File | Remove-Item -Force
    Copy-Item (Join-Path $Src '*.py') $AppDir -Force
    foreach ($d in 'web', 'data', 'docs') { Copy-Item (Join-Path $Src $d) $AppDir -Recurse -Force }
    foreach ($f in 'README.md', 'LICENSE') { if (Test-Path (Join-Path $Src $f)) { Copy-Item (Join-Path $Src $f) $AppDir -Force } }
    foreach ($f in 'run.py', 'start.ps1', 'stop.ps1', 'uninstall.ps1', 'firewall.ps1', 'ui.ps1', 'Uninstall SkyScope.exe') { Copy-Item (Join-Path $PSScriptRoot $f) $AppDir -Force }
    foreach ($f in 'skyscope-start.ico', 'skyscope-stop.ico', 'skyscope-uninstall.ico', 'skyscope.ico') { Copy-Item (Join-Path $Src "tools\launcher\$f") $AppDir -Force }
    Copy-Item (Join-Path $Src 'docs\images\moon-pi-logo-128.png') (Join-Path $AppDir 'logo.png') -Force
    # a FlightAware key kept when SkyScope was last uninstalled comes back
    $keptKey = Join-Path $env:APPDATA 'Project Moon Pi\SkyScope FlightAware key.json'
    if (Test-Path $keptKey) {
        try { $null = Run $venvPy @((Join-Path $Src 'installer\keep_key.py'), 'restore', (Join-Path $AppDir 'settings.json'), $keptKey) 'Bringing back the FlightAware key' 77 10 }
        catch { Log "$_ - the kept FlightAware key stays where it is" }
    }
    Get-ChildItem $AppDir -Recurse -File | Unblock-File      # drop the "downloaded from the internet" mark on our copies
    # SkyScope.exe: Python under SkyScope's own name and icon, so Task Manager shows "SkyScope" (pythonw.exe if not)
    UI-Progress 'Naming SkyScope for Task Manager...' 80
    $exe = $null
    try { $exe = ((Run $venvPy @((Join-Path $PSScriptRoot 'brand_exe.py'), $AppDir) 'Naming SkyScope' 85 20) -split "`r?`n" | Where-Object { $_ } | Select-Object -Last 1) } catch { Log $_ }
    if (-not $exe -or -not (Test-Path $exe)) { $exe = Join-Path $AppDir 'venv\Scripts\pythonw.exe' }
    Push-Location $AppDir
    $version = (& $venvPy -c 'from version import VERSION; print(VERSION)').Trim()
    # (no double quotes inside: Windows PowerShell 5.1 drops them from a program's arguments)
    $port = [int](& $venvPy -c 'import json, os; p = ''settings.json''; print((json.load(open(p)).get(''web_port'') if os.path.exists(p) else 0) or 7700)')
    Pop-Location
    @{ port = $port; phones = $phones; autostart = $autostart; desktop = $onDesktop; version = "$version"; exe = "$exe" } | ConvertTo-Json |
        Set-Content (Join-Path $AppDir 'install.json')

    # shortcuts: the Start menu, the Desktop if wanted (Start and Stop only), and the Startup folder when it should
    # start at sign-in
    UI-Progress 'Adding the shortcuts...' 86
    $shell = New-Object -ComObject WScript.Shell
    function New-Shortcut($path, $script, $icon, $desc, $extra = '') {
        $s = $shell.CreateShortcut($path)
        $s.TargetPath = $ps
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
    $places = @($menu)
    if ($onDesktop) { $places += $desktop }
    else { Remove-Item (Join-Path $desktop 'Start SkyScope.lnk'), (Join-Path $desktop 'Stop SkyScope.lnk') -ErrorAction SilentlyContinue }
    Remove-Item (Join-Path $desktop 'Uninstall SkyScope.lnk') -ErrorAction SilentlyContinue    # (1.6.1 put one there)
    foreach ($dir in $places) {
        New-Shortcut (Join-Path $dir 'Start SkyScope.lnk') 'start.ps1' 'skyscope-start.ico' 'Start SkyScope and open the radar'
        New-Shortcut (Join-Path $dir 'Stop SkyScope.lnk') 'stop.ps1' 'skyscope-stop.ico' 'Stop SkyScope'
    }
    # Remove runs the uninstaller's script through PowerShell, like Start and Stop. Two things keep Windows' Start
    # menu from hiding it (found in the Win11 VM): no description (one about removing the program hides it), and a
    # new command on every install (-Installed <time>, ignored by the script), made as a new shortcut: Windows
    # remembers a Remove shortcut that went with an uninstall and hides any later one with the same command.
    Remove-Item (Join-Path $menu 'Uninstall SkyScope.lnk') -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $menu 'Remove SkyScope.lnk') -ErrorAction SilentlyContinue
    New-Shortcut (Join-Path $menu 'Remove SkyScope.lnk') 'uninstall.ps1' 'skyscope-uninstall.ico' '' "-Installed $(Get-Date -Format yyyyMMddHHmmss)"
    $startupLink = Join-Path ([Environment]::GetFolderPath('Startup')) 'SkyScope.lnk'
    if ($autostart) { New-Shortcut $startupLink 'start.ps1' 'skyscope-start.ico' 'Start SkyScope at sign-in' '-NoBrowser' }
    else { Remove-Item $startupLink -ErrorAction SilentlyContinue }

    # Settings > Apps (and Control Panel > Programs) list it, with an Uninstall button that runs Uninstall SkyScope.exe
    UI-Progress 'Listing SkyScope in Settings > Apps...' 87
    $size = [int]((Get-ChildItem $AppDir -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum / 1KB)
    $uninstall = "`"$(Join-Path $AppDir 'Uninstall SkyScope.exe')`""
    New-Item -Path $UninstallKey -Force | Out-Null
    foreach ($v in @(@('DisplayName', 'SkyScope'), @('DisplayVersion', "$version"), @('Publisher', 'Project Moon Pi'),
                     @('DisplayIcon', (Join-Path $AppDir 'skyscope.ico')), @('InstallLocation', $AppDir),
                     @('UninstallString', $uninstall), @('QuietUninstallString', "$uninstall -Quiet"),
                     @('URLInfoAbout', 'https://github.com/projectmoonpi/skyscope'),
                     @('InstallDate', (Get-Date -Format 'yyyyMMdd')))) {
        New-ItemProperty -Path $UninstallKey -Name $v[0] -Value $v[1] -PropertyType String -Force | Out-Null
    }
    foreach ($v in @(@('NoModify', 1), @('NoRepair', 1), @('EstimatedSize', $size))) {
        New-ItemProperty -Path $UninstallKey -Name $v[0] -Value $v[1] -PropertyType DWord -Force | Out-Null
    }

    # moved from another folder: it's stopped, its settings came along and everything else has been replaced, so it
    # can go
    foreach ($d in $others) { if (Test-Path (Join-Path $d 'install.json')) { Remove-Item $d -Recurse -Force -ErrorAction SilentlyContinue } }

    # phones and Satellites: make sure the firewall lets them in on home networks (Windows asks for permission only
    # if needed; firewall.ps1 says so first, over this window)
    $fw = Join-Path $AppDir 'firewall.ps1'
    $networkNote = ''
    if ($phones) {
        UI-Progress 'Letting phones and Satellites on your home network reach SkyScope...' 89
        $state = & $fw -Allow -Port $port -Program $exe -Quiet:$UI_Unattended
        Log "firewall: $state"
        $public = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue | Where-Object NetworkCategory -eq 'Public').Count
        if ($state -eq 'Declined') {
            $networkNote = "Windows didn't allow the firewall change, so phones and Satellites can't reach SkyScope yet. Run the installer again and click Yes when Windows asks."
        } elseif ($public -and $state -ne 'AllowedPublic') {
            $networkNote = "This PC's network is set to Public, where Windows keeps other devices out. For phones and Satellites to reach SkyScope, set your home Wi-Fi to Private: Settings > Network & Internet > (your connection) > Private."
        }
    } else {
        & $fw -Port $port -Quiet:$UI_Unattended
    }
    if ($networkNote) { Log $networkNote }

    UI-Progress 'Starting SkyScope...' 90
    $env:SS_INSTALLING = '1'    # (Start needn't put up its own notice)
    $p = Start-Process $ps -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', "`"$(Join-Path $AppDir 'start.ps1')`"", '-NoBrowser') -WindowStyle Hidden -PassThru
    $null = UI-Wait $p 100 30
    $up = $false
    try { $null = Invoke-WebRequest "http://127.0.0.1:$port/api/status" -UseBasicParsing -TimeoutSec 5; $up = $true } catch { }
    Log "installed $version, running=$up"

    $did = @{ install = 'is installed'; update = 'is installed (updated from ' + $have + ')'; repair = 'is repaired'; fresh = 'is reinstalled from scratch' }[$mode]
    $done = "SkyScope $version $did" + $(if ($up) { ' and running.' } else { ', but it didn''t start yet: use Start SkyScope in the Start menu.' }) +
        "`n`nIts radar icon is by the clock (click ^ if Windows has tucked it away there): click it for the radar, right-click for the settings or Stop. Start and Stop SkyScope are in the Start menu" + $(if ($onDesktop) { ', and on your Desktop' } else { '' }) + ". To remove it, use Remove SkyScope in the Start menu, Uninstall SkyScope in $AppDir, or Settings > Apps." +
        $(if ($networkNote) { "`n`n$networkNote" } else { '' })
    $open = UI-Done $done 'Finish' @(@{ text = 'Open the radar now'; checked = ($up -and $env:SS_OPEN -ne 'no') })
    if ($up -and $open -and $open[0] -and -not $UI_Unattended) { Start-Process "http://127.0.0.1:$port/radar" }
}

$WasRunning = $null
try { Main }
catch {
    Log "ERROR: $_"
    # it was running before the update began: start that copy again
    $again = ''
    if ($WasRunning -and (Test-Path (Join-Path $WasRunning 'start.ps1'))) {
        Start-Process (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') -WindowStyle Hidden -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', "`"$(Join-Path $WasRunning 'start.ps1')`"", '-NoBrowser')
        $again = "`n`nThe SkyScope you already had is running again."
        Log "restarted $WasRunning"
    }
    UI-Error "SkyScope wasn't installed.`n`n$_$again`n`nWhat the installer did is in $Log."
    exit 1
}
