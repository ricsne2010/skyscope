#!/bin/bash
# The Mac installer's work, run by its window (installer/mac/window.py, in "Install SkyScope.app") with the answers
# already given: SS_PY=<python 3.10+> SS_PHONES=yes|no SS_AUTOSTART=yes|no SS_DESKTOP=yes|no
# Each step prints "@@ <percent> <what's happening>" for the window's progress bar; everything else goes to its log.
# It installs the program in ~/Library/Application Support/SkyScope, sets it up as a background service (started
# last, by the window), and puts Start, Stop and Uninstall SkyScope in Applications › SkyScope (Start and Stop on the
# Desktop too, if wanted). Run it again to update: your settings are kept. Designed and Created by Project Moon Pi.
SRC="$(cd "$(dirname "$0")/../.." && pwd)"           # the program's files (inside the installer app)
. "$SRC/installer/mac/common.sh"
set -e
step() { echo "@@ $1 $2"; }
PIP=(--disable-pip-version-check --no-input --progress-bar off)   # pip says what it fetches (for the details box)
PY=${SS_PY:?}; PHONES=${SS_PHONES:-yes}; AUTOSTART=${SS_AUTOSTART:-no}; DESKTOP=${SS_DESKTOP:-yes}

step 3 "Stopping SkyScope, if it's running..."
if launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1; then echo "Stopped the running SkyScope."; else echo "SkyScope wasn't running."; fi
mkdir -p "$APPDIR" "$APPS" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
echo "Program folder: $APPDIR"
echo "Apps folder: $APPS"

step 8 "Setting up Python for SkyScope..."
echo "Using $("$PY" -c 'import sys; print("Python", sys.version.split()[0])') ($PY)"
# a fresh environment if there's none, or its Python was removed or is too old
"$APPDIR/venv/bin/python" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null || {
  rm -rf "$APPDIR/venv"
  echo "Making SkyScope's own Python environment (venv)..."
  "$PY" -m venv "$APPDIR/venv"
} && echo "SkyScope's Python environment: $APPDIR/venv"
"$APPDIR/venv/bin/python" -m pip install --quiet "${PIP[@]}" --upgrade pip || true
step 20 "Installing pygame-ce (it draws the radar)..."
"$APPDIR/venv/bin/python" -m pip install "${PIP[@]}" --upgrade pygame-ce
step 45 "Installing the menu bar icon (pystray, Pillow)..."
# pystray and Pillow (with PyObjC) put SkyScope's icon in the menu bar; without them it runs without the icon
"$APPDIR/venv/bin/python" -m pip install "${PIP[@]}" --upgrade pystray pillow ||
  echo "(Couldn't install pystray and Pillow: SkyScope will run without its menu bar icon.)"

step 68 "Naming SkyScope for Activity Monitor..."
# venv/bin/SkyScope: Python under SkyScope's own name, so Activity Monitor shows "SkyScope". It's a copy of
# Python's own program, signed again for its new place (its signature belongs to Python.app); plain python if not.
EXE="$APPDIR/venv/bin/python"
REAL=$("$EXE" -c 'import os, sys; p = os.path.join(sys.base_prefix, "Resources/Python.app/Contents/MacOS/Python"); print(p if os.path.exists(p) else os.path.realpath(sys._base_executable))')
if cp "$REAL" "$APPDIR/venv/bin/SkyScope.new" && codesign --force -s - "$APPDIR/venv/bin/SkyScope.new" 2>/dev/null &&
   PYGAME_HIDE_SUPPORT_PROMPT=1 "$APPDIR/venv/bin/SkyScope.new" -c 'import sys, pygame; sys.exit(sys.prefix == sys.base_prefix)' 2>/dev/null; then
  mv -f "$APPDIR/venv/bin/SkyScope.new" "$APPDIR/venv/bin/SkyScope"
  EXE="$APPDIR/venv/bin/SkyScope"
  echo "Made $EXE (a signed copy of Python under SkyScope's name)"
else
  rm -f "$APPDIR/venv/bin/SkyScope.new"
  echo "(Activity Monitor will show SkyScope as Python.)"
fi

step 74 "Copying SkyScope..."
# the program: replaced on every install; your settings, logo cache and FlightAware count stay
( cd "$APPDIR" && rm -rf web data docs installer ./*.py )
cp "$SRC"/*.py "$APPDIR/"
cp -R "$SRC/web" "$SRC/data" "$SRC/docs" "$APPDIR/"
cp "$SRC/README.md" "$SRC/LICENSE" "$APPDIR/" 2>/dev/null || true
# the uninstaller's window and work, run by Uninstall SkyScope
mkdir -p "$APPDIR/installer/mac"
cp "$SRC/installer/mac/window.py" "$SRC/installer/mac/uninstall.sh" "$SRC/installer/mac/common.sh" "$APPDIR/installer/mac/"
VERSION=$(cd "$APPDIR" && "$APPDIR/venv/bin/python" -c 'from version import VERSION; print(VERSION)')
PORT=$(cd "$APPDIR" && "$APPDIR/venv/bin/python" -c 'import json; print(json.load(open("settings.json")).get("web_port") or 7700)' 2>/dev/null || echo 7700)
echo "Copied SkyScope $VERSION ($(ls "$APPDIR"/*.py | wc -l | tr -d ' ') program files, web pages, data, guide)"
echo "Web port $PORT; phones and Satellites: $PHONES; start at login: $AUTOSTART"
printf 'PORT=%s\nPHONES=%s\nAUTOSTART=%s\nDESKTOP=%s\nAPPS="%s"\n' "$PORT" "$PHONES" "$AUTOSTART" "$DESKTOP" "$APPS" > "$APPDIR/settings.sh"

step 80 "Setting up the background service..."
# a LaunchAgent: runs as you, only while you're logged in
HOSTARGS=""
[ "$PHONES" = yes ] || HOSTARGS="<string>--host</string><string>127.0.0.1</string>"
RUNATLOAD=false
[ "$AUTOSTART" = yes ] && RUNATLOAD=true
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$EXE</string>
    <string>$APPDIR/skyscope.py</string>
    <string>--web-only</string><string>--no-browser</string><string>--tray</string>
    $HOSTARGS
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>PYGAME_HIDE_SUPPORT_PROMPT</key><string>1</string><key>PYTHONUNBUFFERED</key><string>1</string></dict>
  <key>WorkingDirectory</key><string>$APPDIR</string>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
  <key>RunAtLoad</key><$RUNATLOAD/>
  <key>ProcessType</key><string>Standard</string>
</dict>
</plist>
PLIST
echo "Wrote the service: $PLIST"

step 84 "Making Start, Stop and Uninstall SkyScope..."
# Each is a small AppleScript app (made by macOS's osacompile) that runs its script from Contents/Resources. A real
# app, not a script in a folder, so macOS can ask about it by name: Uninstall needs your OK, once, to remove the
# icons from the Desktop.
make_app() {   # make_app "Name" script icon id
  local app="$APPS/$1.app" plist="$APPS/$1.app/Contents/Info.plist"
  rm -rf "$app"
  osacompile -o "$app" -e 'on run' \
    -e 'try' \
    -e 'do shell script quoted form of (POSIX path of (path to me) & "Contents/Resources/run.sh")' \
    -e 'end try' -e 'end run'   # (the script shows its own messages)
  cp "$SRC/installer/mac/$2" "$app/Contents/Resources/run.sh"
  cp "$SRC/installer/mac/common.sh" "$app/Contents/Resources/common.sh"
  chmod +x "$app/Contents/Resources/run.sh"
  cp "$SRC/tools/launcher/$3.icns" "$app/Contents/Resources/applet.icns"
  rm -f "$app/Contents/Resources/Assets.car"
  plutil -remove CFBundleIconName "$plist" >/dev/null 2>&1 || true
  plutil -replace CFBundleName -string "$1" "$plist"
  plutil -replace CFBundleDisplayName -string "$1" "$plist"
  plutil -replace CFBundleIdentifier -string "$LABEL.$4" "$plist"
  plutil -replace CFBundleShortVersionString -string "$VERSION" "$plist"
  plutil -replace NSHumanReadableCopyright -string "Designed and Created by Project Moon Pi" "$plist"
  plutil -replace NSDesktopFolderUsageDescription -string "To remove the SkyScope icons from your Desktop." "$plist"
  plutil -replace LSUIElement -bool YES "$plist"
  codesign --force -s - "$app" 2>/dev/null || true   # signed again after the changes, so macOS knows it
  touch "$app"
  echo "Made $app"
}
# an earlier SkyScope kept its apps in your own Applications folder
[ "$APPS" = "$HOME/Applications/SkyScope" ] || rm -rf "$HOME/Applications/SkyScope"
make_app "Start SkyScope" start.sh skyscope-start start
make_app "Stop SkyScope" stop.sh skyscope-stop stop
make_app "Uninstall SkyScope" uninstall-window.sh skyscope-uninstall uninstall
# files from a downloaded zip carry macOS's "downloaded" flag; apps built here shouldn't
xattr -dr com.apple.quarantine "$APPS" "$APPDIR" 2>/dev/null || true

step 92 "Adding the icons..."
if [ "$DESKTOP" = yes ]; then
  # (macOS asks once whether the installer may change the Desktop)
  { ln -sfn "$APPS/Start SkyScope.app" "$HOME/Desktop/Start SkyScope" &&
    ln -sfn "$APPS/Stop SkyScope.app" "$HOME/Desktop/Stop SkyScope"; } 2>/dev/null && echo "Put Start and Stop SkyScope on the Desktop" ||
    echo "@! macOS didn't let the installer put Start and Stop SkyScope on your Desktop: they're in Applications › SkyScope."
else
  rm -f "$HOME/Desktop/Start SkyScope" "$HOME/Desktop/Stop SkyScope" 2>/dev/null || true
  echo "No Desktop icons (as chosen)"
fi
rm -f "$HOME/Desktop/Uninstall SkyScope" 2>/dev/null || true   # (1.6.1 put one there; it lives in Applications › SkyScope)

step 95 "Starting SkyScope..."
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl kickstart "$DOMAIN/$LABEL"
echo "Started the service; waiting for SkyScope to answer on port $PORT..."
for _ in $(seq 1 90); do up && break; sleep 1; done
up && echo "SkyScope is running: http://localhost:$PORT"
up || { echo "SkyScope didn't start: its messages are in $LOG"; exit 2; }
step 100 "Done."
echo "VERSION=$VERSION PORT=$PORT"
