# Shared by the SkyScope apps on macOS (copied into each app when installed).
LABEL=com.projectmoonpi.skyscope
APPDIR="$HOME/Library/Application Support/SkyScope"
APPS="$HOME/Applications/SkyScope"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/SkyScope.log"
DOMAIN="gui/$(id -u)"
PORT=7700
[ -f "$APPDIR/settings.sh" ] && . "$APPDIR/settings.sh"

up() { curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$PORT/radar"; }
notify() { osascript -e "display notification \"$1\" with title \"SkyScope\"" >/dev/null 2>&1; }
alert() { osascript -e "display alert \"$1\" message \"$2\"" >/dev/null 2>&1; }
