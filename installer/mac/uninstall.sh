#!/bin/bash
# Uninstall SkyScope: removes the service, the apps and the program, with its settings.
. "$(dirname "$0")/common.sh"
# SS_UNATTENDED=1: no questions
if [ -z "$SS_UNATTENDED" ]; then
  answer=$(osascript -e 'button returned of (display dialog "Remove SkyScope from this Mac?\n\nIts settings (location, filters, FlightAware key) are removed too." buttons {"Cancel", "Remove"} default button "Remove" with title "Uninstall SkyScope" with icon caution)' 2>/dev/null)
  [ "$answer" = "Remove" ] || exit 0
fi
launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1
rm -f "$PLIST" "$HOME/Desktop/Start SkyScope" "$HOME/Desktop/Stop SkyScope" "$LOG"
rm -rf "$APPDIR"
[ -n "$SS_UNATTENDED" ] || osascript -e 'display dialog "SkyScope has been removed." buttons {"OK"} default button "OK" with title "Uninstall SkyScope"' >/dev/null 2>&1
rm -rf "$APPS"     # last: this app lives in there
