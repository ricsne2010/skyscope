#!/usr/bin/env python3
"""Click-to-start launcher for SkyScope on a Mac, Windows or Linux desktop.

Starts SkyScope's web radar in the background if it isn't already running,
then shows the radar in the browser. Used by the desktop shortcuts that
tools/make_mac_app.sh and tools/windows/create-shortcut.bat make; it can also
be run directly:  python3 tools/launch.py

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


def main() -> int:
    url = f"http://localhost:{port()}/radar"
    if running(url):
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
    for _ in range(60):
        if running(url):
            return 0
        time.sleep(0.5)
    alert(f"SkyScope didn't start. Details are in {LOG}.\n\n"
          "If it mentions pygame, install it with:  pip install pygame")
    return 1


if __name__ == "__main__":
    sys.exit(main())
