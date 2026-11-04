# Builds "Install SkyScope.exe" (radar icon) and "Uninstall SkyScope.exe" (bin badge) from launcher.cs with the C#
# compiler that comes with Windows (.NET Framework 4). Run on Windows (or on a Mac with Mono: see the README's
# "Building the downloads"), then commit both .exe files: tools/make_downloads.py puts them in the Windows zip, and
# the installer copies the uninstaller into the install folder.
#   powershell -ExecutionPolicy Bypass -File installer\windows\build_launcher.ps1
$here = $PSScriptRoot
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path $csc)) { $csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe' }
foreach ($b in @(@('Install SkyScope.exe', 'skyscope.ico'), @('Uninstall SkyScope.exe', 'skyscope-uninstall.ico'))) {
    & $csc /nologo /target:winexe /optimize+ /reference:System.Windows.Forms.dll `
        "/win32icon:$(Join-Path $here "..\..\tools\launcher\$($b[1])")" "/out:$(Join-Path $here $b[0])" (Join-Path $here 'launcher.cs')
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
}
