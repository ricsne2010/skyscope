@echo off
rem Install SkyScope on this PC. Double-click to run; run it again later to update (your settings are kept).
rem Needs Python 3.10 or newer from python.org. Designed and Created by Project Moon Pi.
title Install SkyScope
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\windows\install.ps1"
if errorlevel 1 (echo. & echo The install did not finish: see the messages above.)
pause
