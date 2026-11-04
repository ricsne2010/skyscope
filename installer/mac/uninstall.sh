#!/bin/bash
# Uninstall SkyScope: removes the service, the apps and the program, with its settings. Python stays.
# SS_WINDOW=1: run by the uninstaller's window (window.py --uninstall), which asked first: each step prints
# "@@ <percent> <what's happening>" for its progress bar, "@! <note>" for its last page. SS_UNATTENDED=1: no questions.
# Otherwise (no window: a Python without Tk) it asks and answers with dialogs.
. "$(dirname "$0")/common.sh"
step() { [ -n "$SS_WINDOW" ] && echo "@@ $1 $2"; return 0; }
if [ -z "$SS_UNATTENDED$SS_WINDOW" ]; then
  answer=$(osascript -e 'button returned of (display dialog "Remove SkyScope from this Mac?\n\nIts settings (location, filters, FlightAware key) are removed too." buttons {"Cancel", "Remove"} default button "Remove" with title "Uninstall SkyScope" with icon caution)' 2>/dev/null)
  [ "$answer" = "Remove" ] || exit 0
fi
step 10 "Stopping SkyScope..."
launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1
rm -f "$PLIST" "$LOG"
step 40 "Removing the program and its settings..."
rm -rf "$APPDIR"
step 75 "Removing the icons..."
# the Desktop icons: macOS asks once whether Uninstall SkyScope may change the Desktop
icons=("$HOME/Desktop/Start SkyScope" "$HOME/Desktop/Stop SkyScope" "$HOME/Desktop/Uninstall SkyScope")
rm -f "${icons[@]}" 2>/dev/null
left=""
for i in "${icons[@]}"; do [ -L "$i" ] || [ -e "$i" ] && left=yes; done
note="macOS didn't let it remove its icons from your Desktop: drag Start SkyScope and Stop SkyScope to the Bin."
if [ -n "$SS_WINDOW" ]; then
  [ -n "$left" ] && echo "@! $note"
elif [ -z "$SS_UNATTENDED" ]; then
  done_msg="SkyScope has been removed."
  [ -n "$left" ] && done_msg="SkyScope has been removed.\n\n$note"
  osascript -e "display dialog \"$done_msg\" buttons {\"OK\"} default button \"OK\" with title \"Uninstall SkyScope\"" >/dev/null 2>&1
fi
step 95 "Removing Start, Stop and Uninstall SkyScope..."
rm -rf "$HOME/Applications/SkyScope" "/Applications/SkyScope"   # last: this app lives in one of them
step 100 "Done."
