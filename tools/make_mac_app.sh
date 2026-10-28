#!/bin/sh
# Makes a SkyScope icon (a small app with the radar-screen picture) on your Mac
# Desktop. Clicking it starts SkyScope in the background if it isn't running and
# opens the radar in your browser.
#
#   sh tools/make_mac_app.sh              # app on the Desktop
#   sh tools/make_mac_app.sh /Applications
#
# The app remembers where this SkyScope folder is and which python3 to use; run
# this again if you move the folder or reinstall Python.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$HOME/Desktop}"
PY="$(command -v python3 || true)"
[ -n "$PY" ] || { echo "python3 not found: install Python 3.10 or newer from python.org" >&2; exit 1; }
PYGAME_HIDE_SUPPORT_PROMPT=1 "$PY" -c "import pygame" 2>/dev/null || echo "Note: pygame isn't installed for $PY yet. Run:  $PY -m pip install pygame"

APP="$DEST/SkyScope.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$ROOT/tools/launcher/skyscope.icns" "$APP/Contents/Resources/SkyScope.icns"
VERSION="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$ROOT/version.py")"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>SkyScope</string>
  <key>CFBundleDisplayName</key><string>SkyScope</string>
  <key>CFBundleIdentifier</key><string>com.projectmoonpi.skyscope.launcher</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>SkyScope</string>
  <key>CFBundleIconFile</key><string>SkyScope</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
PLIST
cat > "$APP/Contents/MacOS/SkyScope" <<LAUNCHER
#!/bin/sh
# Made by tools/make_mac_app.sh: starts SkyScope (if needed) and opens the radar.
exec "$PY" "$ROOT/tools/launch.py"
LAUNCHER
chmod +x "$APP/Contents/MacOS/SkyScope"
touch "$APP"  # so Finder picks up the icon
echo "Made $APP"
echo "Click it to start SkyScope; the radar opens in your browser."
