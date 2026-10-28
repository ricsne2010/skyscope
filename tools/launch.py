#!/usr/bin/env python3
"""Click-to-start launcher for SkyScope on a Mac, Windows or Linux desktop.

Starts SkyScope's web radar in the background if it isn't already running,
then shows the radar in the browser. With --stop, stops it instead. Used by
the SkyScope and Stop SkyScope icons that tools/make_mac_app.sh and
tools/windows/create-shortcut.bat make; it can also be run directly:
    python3 tools/launch.py          python3 tools/launch.py --stop

Output goes to skyscope.log in the SkyScope folder. On Windows, run it with
pythonw.exe so no console window appears.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "skyscope.log"


def port() -> int:
    try:
        return int(json.loads((ROOT / "settings.json").read_text(encoding="utf-8")).get("web_port") or 7700)
    except (OSError, ValueError):
        return 7700


def running(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1):
            return True
    except OSError:
        return False


def alert(message: str) -> None:
    """A message box (there's no terminal to print to)."""
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "SkyScope", 0x10)
    elif sys.platform == "darwin":
        subprocess.run(["osascript", "-e", f'display alert "SkyScope" message {json.dumps(message)}'], check=False)
    else:
        print(message, file=sys.stderr)


def notify(message: str) -> None:
    """A short, friendly confirmation."""
    if sys.platform == "darwin":
        subprocess.run(["osascript", "-e", f'display notification {json.dumps(message)} with title "SkyScope"'],
                       check=False)
    elif sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "SkyScope", 0x40)
    else:
        print(message)


def kill_processes() -> bool:
    """Last resort: end any running skyscope.py (an older SkyScope without
    the shutdown request, or one that's stuck)."""
    if sys.platform == "win32":
        ps = ("$p = Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*skyscope.py*' }; "
              "$p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; if ($p) { exit 0 } else { exit 1 }")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], creationflags=0x08000000, check=False)
    else:
        r = subprocess.run(["pkill", "-f", "[Pp]ython.* skyscope\\.py"], check=False)  # not an editor with the file open
    return r.returncode == 0


def stop() -> int:
    probe = f"http://127.0.0.1:{port()}/radar"
    if not running(probe):
        notify("SkyScope isn't running.")
        return 0
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port()}/api/shutdown", data=b"", method="POST",
                                     headers={"X-SkyScope": "stop"})
        urllib.request.urlopen(req, timeout=3).close()
    except OSError:
        pass  # older SkyScope: no shutdown request; handled below
    for _ in range(20):
        time.sleep(0.25)
        if not running(probe):
            notify("SkyScope stopped.")
            return 0
    if kill_processes():
        time.sleep(1)
        if not running(probe):
            notify("SkyScope stopped.")
            return 0
    alert("SkyScope didn't stop. Quit its Python process in "
          + ("Task Manager." if sys.platform == "win32" else "Activity Monitor."))
    return 1


def main() -> int:
    if "--stop" in sys.argv[1:]:
        return stop()
    url = f"http://localhost:{port()}/radar"
    # Check on 127.0.0.1: on Windows "localhost" tries IPv6 first and SkyScope
    # listens on IPv4, so each check would stall for about two seconds.
    probe = f"http://127.0.0.1:{port()}/radar"
    if running(probe):
        webbrowser.open(url)
        return 0
    python = Path(sys.executable)  # pythonw.exe on Windows: SkyScope gets no console window either
    with open(LOG, "a", encoding="utf-8") as log:
        log.write(f"--- {time.ctime()}: starting SkyScope\n")
        log.flush()
        options = {}
        if sys.platform == "win32":
            options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True  # keeps running after the launcher exits
        subprocess.Popen([str(python), "skyscope.py", "--web-only"], cwd=ROOT, stdout=log,
                         stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **options)
    # SkyScope opens the radar in the browser itself once it's ready.
    for _ in range(90):  # the first start on Windows can be slow (antivirus scans)
        if running(probe):
            return 0
        time.sleep(0.5)
    alert(f"SkyScope didn't start within 45 seconds. Details are in {LOG}.\n\n"
          "If it mentions pygame, install it with:  pip install pygame-ce")
    return 1


if __name__ == "__main__":
    sys.exit(main())
