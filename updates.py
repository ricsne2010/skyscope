"""Is there a newer SkyScope? Asks GitHub for the newest release (projectmoonpi/skyscope) and compares it with this
one's version. Shown in Settings › About (with Check now), as a notice on the radar, and in the menu bar / taskbar
icon's menu; updating is the new version's installer (its Update keeps your settings).

It asks at most every 6 hours (every 30 minutes after a failed try), in the background, and only while the
check_updates setting is on: the request goes to api.github.com and says only which SkyScope version is asking.
Designed and Created by Project Moon Pi.
"""
import json
import sys
import threading
import time
import urllib.request

from version import VERSION

REPO = "projectmoonpi/skyscope"
EVERY = 6 * 3600
RETRY = 30 * 60

_lock = threading.Lock()
_state = {"at": 0.0, "info": None, "busy": False}


def numbers(v: str) -> tuple:
    """'v1.7.10' -> (1, 7, 10), for comparing versions."""
    out = []
    for part in v.strip().lstrip("vV").split("."):
        digits = "".join(c for c in part if c.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def platform_name():
    """The download for this computer: 'Mac', 'Windows', or None (a Raspberry Pi updates from the release page)."""
    return {"darwin": "Mac", "win32": "Windows"}.get(sys.platform)


def _ask() -> dict:
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases/latest",
                                 headers={"Accept": "application/vnd.github+json",
                                          "User-Agent": f"SkyScope/{VERSION} (update check)"})
    with urllib.request.urlopen(req, timeout=10) as r:
        rel = json.load(r)
    latest = str(rel.get("tag_name", "")).lstrip("vV")
    want = platform_name()
    download = next((a.get("browser_download_url") for a in rel.get("assets", [])
                     if want and a.get("name", "").endswith(f"-for-{want}.zip")), None)
    return {"latest": latest, "newer": numbers(latest) > numbers(VERSION), "page": rel.get("html_url"),
            "download": download, "error": None}


def _refresh():
    try:
        info = _ask()
    except (OSError, ValueError) as exc:
        info = {"latest": None, "newer": False, "page": f"https://github.com/{REPO}/releases", "download": None,
                "error": f"Couldn't reach GitHub to check ({exc.__class__.__name__})."}
    with _lock:
        _state.update(at=time.time(), info=info, busy=False)


def status(enabled: bool = True, now: bool = False) -> dict:
    """What's known: {current, enabled, latest, newer, page, download, error, checked}. now=True asks GitHub first
    (Check now); otherwise a check due runs in the background and the last answer is returned at once."""
    if now:
        _refresh()
    elif enabled:
        with _lock:
            info, at, busy = _state["info"], _state["at"], _state["busy"]
            due = not busy and time.time() - at > (RETRY if info is None or info.get("error") else EVERY)
            if due:
                _state["busy"] = True
        if due:
            threading.Thread(target=_refresh, name="update-check", daemon=True).start()
    with _lock:
        info, at = _state["info"], _state["at"]
    out = {"current": VERSION, "enabled": enabled, "latest": None, "newer": False,
           "page": f"https://github.com/{REPO}/releases", "download": None, "error": None, "checked": None}
    if info and (enabled or now):
        out.update(info)
        out["checked"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(at))
    return out
