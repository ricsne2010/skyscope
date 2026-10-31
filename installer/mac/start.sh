#!/bin/bash
# Start SkyScope: starts the background service if it isn't running, then opens the radar.
# --no-browser: start it without opening the radar.
. "$(dirname "$0")/common.sh"
if ! up; then
  launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || launchctl bootstrap "$DOMAIN" "$PLIST"
  launchctl kickstart "$DOMAIN/$LABEL"
  notify "Starting SkyScope…"
  for _ in $(seq 1 90); do up && break; sleep 1; done
  if ! up; then
    alert "SkyScope didn't start" "Its messages are in ~/Library/Logs/SkyScope.log"
    exit 1
  fi
fi
[ "$1" = "--no-browser" ] || open "http://127.0.0.1:$PORT/radar"
