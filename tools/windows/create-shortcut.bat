@echo off
rem Double-click to make SkyScope shortcuts (radar icon) on the Desktop and in
rem the Start menu. See create-shortcut.ps1.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0create-shortcut.ps1"
echo.
pause
