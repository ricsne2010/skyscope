# Builds the three Windows programs from src\*.cs with the C# compiler that comes with Windows (.NET Framework 4):
# Install SkyScope.exe, Uninstall SkyScope.exe and SkyScope.exe (one program; what it does goes by its name).
# On a Mac use build.sh (Mono). Commit the .exe files: tools/make_downloads.py puts them in the Windows zip.
#   powershell -File installer\windows\build.ps1
$here = $PSScriptRoot
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path $csc)) { $csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe' }
foreach ($b in @(@('Install SkyScope.exe', 'skyscope.ico'), @('Uninstall SkyScope.exe', 'skyscope-uninstall.ico'), @('SkyScope.exe', 'skyscope.ico'))) {
    & $csc /nologo /target:winexe /optimize+ /reference:System.Windows.Forms.dll /reference:System.Drawing.dll `
        /reference:System.Core.dll /reference:System.Web.Extensions.dll /reference:Microsoft.CSharp.dll /reference:System.IO.Compression.dll `
        "/win32icon:$(Join-Path $here "..\..\tools\launcher\$($b[1])")" "/out:$(Join-Path $here $b[0])" (Join-Path $here 'src\*.cs')
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
}
