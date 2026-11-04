#!/bin/bash
# Uninstall SkyScope: removes the service, the apps and the program, with its settings.
. "$(dirname "$0")/common.sh"
# SS_UNATTENDED=1: no questions
if [ -z "$SS_UNATTENDED" ]; then
  answer=$(osascript -e 'button returned of (display dialog "Remove SkyScope from this Mac?\n\nIts settings (location, filters, FlightAware key) are removed too." buttons {"Cancel", "Remove"} default button "Remove" with title "Uninstall SkyScope" with icon caution)' 2>/dev/null)
  [ "$answer" = "Remove" ] || exit 0
fi
launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1
rm -f "$PLIST" "$LOG"
rm -rf "$APPDIR"
# the Desktop icons: macOS asks once whether Uninstall SkyScope may change the Desktop
icons=("$HOME/Desktop/Start SkyScope" "$HOME/Desktop/Stop SkyScope" "$HOME/Desktop/Uninstall SkyScope")
rm -f "${icons[@]}" 2>/dev/null
left=""
for i in "${icons[@]}"; do [ -L "$i" ] || [ -e "$i" ] && left=yes; done
done_msg="SkyScope has been removed."
[ -n "$left" ] && done_msg="SkyScope has been removed.\n\nmacOS didn't let it remove its icons from your Desktop: drag Start SkyScope, Stop SkyScope and Uninstall SkyScope to the Bin."
[ -n "$SS_UNATTENDED" ] || osascript -e "display dialog \"$done_msg\" buttons {\"OK\"} default button \"OK\" with title \"Uninstall SkyScope\"" >/dev/null 2>&1
rm -rf "$HOME/Applications/SkyScope" "/Applications/SkyScope"   # last: this app lives in one of them
