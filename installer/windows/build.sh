#!/bin/sh
# Builds the three Windows programs from src/*.cs, each with its own icon: Install SkyScope.exe, Uninstall
# SkyScope.exe and SkyScope.exe (one program; what it does goes by its name). On a Mac, with Mono's C# compiler
# (Mono.framework); on Windows use build.ps1. Commit the .exe files: tools/make_downloads.py puts them in the zip.
#   sh installer/windows/build.sh
set -e
cd "$(dirname "$0")"
CSC=${CSC:-csc}
ICONS=../../tools/launcher
# built against .NET Framework 4.8's reference assemblies (as Windows has them), not Mono's own libraries, which
# have methods Windows' .NET Framework lacks (Mono's String.Split(char, options) once slipped in that way)
API=${API:-/Library/Frameworks/Mono.framework/Versions/Current/lib/mono/4.8-api}
for spec in "Install SkyScope.exe:skyscope.ico" "Uninstall SkyScope.exe:skyscope-uninstall.ico" "SkyScope.exe:skyscope.ico"; do
  out=${spec%%:*}; ico=${spec##*:}
  "$CSC" -nologo -target:winexe -optimize+ -platform:anycpu -langversion:7.3 -nostdlib -noconfig \
    -reference:"$API/mscorlib.dll" -reference:"$API/System.dll" -reference:"$API/System.Core.dll" \
    -reference:"$API/System.Windows.Forms.dll" -reference:"$API/System.Drawing.dll" \
    -reference:"$API/System.Web.Extensions.dll" -reference:"$API/Microsoft.CSharp.dll" \
    -win32icon:"$ICONS/$ico" -out:"$out" src/*.cs
  echo "built $out"
done
