#!/bin/bash
# Install SkyScope on this Mac. Double-click to run; run it again later to update (your settings are kept).
#
# It installs the program in ~/Library/Application Support/SkyScope, sets it up as a background service, and
# puts Start SkyScope and Stop SkyScope on your Desktop and in Applications › SkyScope.
# Needs Python 3.10 or newer from python.org. Designed and Created by Project Moon Pi.
#
# For unattended installs, answer the questions ahead: SS_PHONES=yes|no SS_AUTOSTART=yes|no SS_OPEN=no
SRC="$(cd "$(dirname "$0")" && pwd)"
. "$SRC/installer/mac/common.sh"
set -e

ask() {   # ask "question" "no-button" "yes-button" -> prints yes or no
  local b
  b=$(osascript -e "button returned of (display dialog \"$1\" buttons {\"$2\", \"$3\"} default button \"$3\" with title \"Install SkyScope\")" 2>/dev/null) || b=""
  [ "$b" = "$3" ] && echo yes || echo no
}

find_python() {
  for p in python3.15 python3.14 python3.13 python3.12 python3.11 python3.10 \
           /Library/Frameworks/Python.framework/Versions/Current/bin/python3 /opt/homebrew/bin/python3 \
           /usr/local/bin/python3 python3; do
    if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
      command -v "$p"; return 0
    fi
  done
  return 1
}

echo "SkyScope installer - Designed and Created by Project Moon Pi"
PY=$(find_python) || {
  echo "SkyScope needs Python 3.10 or newer: install it from https://www.python.org/downloads/ and run this again."
  osascript -e 'display dialog "SkyScope needs Python 3.10 or newer.\n\nClick Download to get it from python.org, install it, then double-click Install SkyScope again." buttons {"Cancel", "Download"} default button "Download" with title "Install SkyScope"' \
    -e 'if button returned of result is "Download" then open location "https://www.python.org/downloads/"' >/dev/null 2>&1 || true
  exit 1
}

PHONES=${SS_PHONES:-$(ask "Should phones, tablets and SkyScope Satellite displays on your Wi-Fi be able to open SkyScope?\n\nThe settings page's About tab shows the address to use." "This Mac only" "Phones too")}
AUTOSTART=${SS_AUTOSTART:-$(ask "Start SkyScope by itself whenever you log in?\n\nOtherwise, use the Start SkyScope icon when you want it." "No" "Yes")}

# an update: stop the running service first
launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true

echo "Installing with $("$PY" --version) into $APPDIR (about a minute)…"
mkdir -p "$APPDIR" "$APPS" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
[ -x "$APPDIR/venv/bin/python" ] || "$PY" -m venv "$APPDIR/venv"
"$APPDIR/venv/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade pip
"$APPDIR/venv/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade pygame-ce

# the program: replaced on every install; your settings, logo cache and FlightAware count stay
( cd "$APPDIR" && rm -rf web data docs ./*.py )
cp "$SRC"/*.py "$APPDIR/"
cp -R "$SRC/web" "$SRC/data" "$SRC/docs" "$APPDIR/"
cp "$SRC/README.md" "$SRC/LICENSE" "$APPDIR/" 2>/dev/null || true
VERSION=$(cd "$APPDIR" && "$APPDIR/venv/bin/python" -c 'from version import VERSION; print(VERSION)')
PORT=$(cd "$APPDIR" && "$APPDIR/venv/bin/python" -c 'import json; print(json.load(open("settings.json")).get("web_port") or 7700)' 2>/dev/null || echo 7700)
printf 'PORT=%s\nPHONES=%s\nAUTOSTART=%s\n' "$PORT" "$PHONES" "$AUTOSTART" > "$APPDIR/settings.sh"

# the background service (a LaunchAgent: runs as you, only while you're logged in)
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
    <string>$APPDIR/venv/bin/python</string>
    <string>$APPDIR/skyscope.py</string>
    <string>--web-only</string><string>--no-browser</string>
    $HOSTARGS
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>PYGAME_HIDE_SUPPORT_PROMPT</key><string>1</string><key>PYTHONUNBUFFERED</key><string>1</string></dict>
  <key>WorkingDirectory</key><string>$APPDIR</string>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
  <key>RunAtLoad</key><$RUNATLOAD/>
  <key>ProcessType</key><string>Background</string>
</dict>
</plist>
PLIST

# the apps: Start, Stop and Uninstall, each a tiny app wrapping its script
make_app() {   # make_app "Name" script icon id
  local app="$APPS/$1.app"
  rm -rf "$app"
  mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
  cp "$SRC/installer/mac/$2" "$app/Contents/MacOS/run"
  cp "$SRC/installer/mac/common.sh" "$app/Contents/MacOS/common.sh"
  chmod +x "$app/Contents/MacOS/run"
  cp "$SRC/tools/launcher/$3.icns" "$app/Contents/Resources/icon.icns"
  cat > "$app/Contents/Info.plist" <<INFO
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$1</string>
  <key>CFBundleDisplayName</key><string>$1</string>
  <key>CFBundleIdentifier</key><string>$LABEL.$4</string>
  <key>CFBundleExecutable</key><string>run</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>NSHumanReadableCopyright</key><string>Designed and Created by Project Moon Pi</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
INFO
  touch "$app"
}
make_app "Start SkyScope" start.sh skyscope-start start
make_app "Stop SkyScope" stop.sh skyscope-stop stop
make_app "Uninstall SkyScope" uninstall.sh skyscope uninstall
# files from a downloaded zip carry macOS's "downloaded" flag; apps built here shouldn't
xattr -dr com.apple.quarantine "$APPS" "$APPDIR" 2>/dev/null || true
ln -sfn "$APPS/Start SkyScope.app" "$HOME/Desktop/Start SkyScope"
ln -sfn "$APPS/Stop SkyScope.app" "$HOME/Desktop/Stop SkyScope"

launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Installed SkyScope $VERSION. Starting it…"
if [ "${SS_OPEN:-yes}" = no ]; then
  "$APPS/Start SkyScope.app/Contents/MacOS/run" --no-browser
else
  "$APPS/Start SkyScope.app/Contents/MacOS/run"
fi
echo "Done. Use Start SkyScope and Stop SkyScope on your Desktop (also in Applications › SkyScope)."
[ -n "$SS_PHONES" ] || osascript -e 'display dialog "SkyScope is installed and running.\n\nUse Start SkyScope and Stop SkyScope on your Desktop (also in your Applications folder, under SkyScope).\n\nYou can delete the downloaded folder now." buttons {"OK"} default button "OK" with title "Install SkyScope"' >/dev/null 2>&1 || true
