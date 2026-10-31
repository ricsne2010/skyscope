#!/bin/bash
# Stop SkyScope: shuts down the background service. The radar stops until it's started again.
. "$(dirname "$0")/common.sh"
launchctl kill SIGTERM "$DOMAIN/$LABEL" >/dev/null 2>&1
for _ in $(seq 1 20); do up || break; sleep 0.5; done
if up; then
  alert "SkyScope is still running" "Something else is using port $PORT (another copy of SkyScope?), or it didn't stop. Try again, or restart the Mac."
else
  notify "SkyScope has stopped."
fi
