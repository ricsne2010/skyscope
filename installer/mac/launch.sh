#!/bin/bash
# "Install SkyScope.app" runs this: the installer's window (window.py beside this) with the first Python on this Mac
# that can draw it: 3.10 or newer, with Tk (python.org's has it; Apple's own and some others don't). In the
# background, so the app can quit (one Dock icon). Exit 3: no such Python (the app then offers to install one).
# Designed and Created by Project Moon Pi.
HERE="$(cd "$(dirname "$0")" && pwd)"
LOG="$HOME/Library/Logs/Install SkyScope - errors.log"
mkdir -p "$HOME/Library/Logs"
for py in /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
          /Library/Frameworks/Python.framework/Versions/3.1[0-9]/bin/python3 \
          /usr/local/bin/python3 /opt/homebrew/bin/python3 /opt/local/bin/python3; do
    if [ -x "$py" ] && "$py" -c "import sys, tkinter; sys.exit(sys.version_info < (3, 10))" 2> /dev/null; then
        "$py" "$HERE/window.py" "$@" > "$LOG" 2>&1 < /dev/null &
        exit 0
    fi
done
exit 3
