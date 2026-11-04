#!/bin/bash
# Uninstall SkyScope's app runs this: the uninstaller's window (window.py --uninstall, kept in SkyScope's folder) with
# SkyScope's own Python, in the background so the app can quit (one Dock icon). If that Python can't draw a window
# (no Tk), uninstall.sh asks with plain dialogs instead. Designed and Created by Project Moon Pi.
. "$(dirname "$0")/common.sh"
PY="$APPDIR/venv/bin/python"
WIN="$APPDIR/installer/mac/window.py"
if [ -f "$WIN" ] && "$PY" -c 'import tkinter' 2>/dev/null; then
  "$PY" "$WIN" --uninstall > /dev/null 2>&1 < /dev/null &
  exit 0
fi
# (an install from before the window: its uninstall.sh beside this, or the copy in SkyScope's folder)
for u in "$(dirname "$0")/uninstall.sh" "$APPDIR/installer/mac/uninstall.sh"; do
  [ -f "$u" ] && exec bash "$u"
done
osascript -e 'display dialog "SkyScope seems to be removed already." buttons {"OK"} default button "OK" with title "Uninstall SkyScope"' >/dev/null 2>&1
