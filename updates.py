"""Is there a newer SkyScope? Asks GitHub for the newest release (projectmoonpi/skyscope) and compares it with this
one's version. Shown in Settings › About (with Check now), as a notice on the radar, and in the menu bar / taskbar
icon's menu; updating is the new version's installer (its Update keeps your settings).

It asks at most every 6 hours (every 30 minutes after a failed try), in the background, and only while the
check_updates setting is on: the request goes to api.github.com (or, if that can't be reached, github.com's page for
the newest release) and says only which SkyScope version is asking. A failure says why ("timed out", "certificate
verify failed"...).
Designed and Created by Project Moon Pi.
"""
import json
import sys
import threading
import time
import urllib.error
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
    asset = next((a for a in rel.get("assets", []) if want and a.get("name", "").endswith(f"-for-{want}.zip")), {})
    return {"latest": latest, "newer": numbers(latest) > numbers(VERSION), "page": rel.get("html_url"),
            "download": asset.get("browser_download_url"), "error": None,
            "size": asset.get("size"), "digest": asset.get("digest")}     # (digest: "sha256:...", for checking it)


def _ask_page() -> dict:
    """The second way: GitHub's ordinary page for the newest release redirects to /releases/tag/v<version>. (Some
    networks and antivirus programs let github.com through but not api.github.com.)"""
    class Stay(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None                                   # (the redirect's address is the answer)
    req = urllib.request.Request(f"https://github.com/{REPO}/releases/latest", method="HEAD",
                                 headers={"User-Agent": f"SkyScope/{VERSION} (update check)"})
    try:
        urllib.request.build_opener(Stay).open(req, timeout=10)
        raise ValueError("no redirect from the releases page")
    except urllib.error.HTTPError as exc:
        where = exc.headers.get("Location", "") if exc.code in (301, 302, 303, 307, 308) else ""
        if "/releases/tag/" not in where:
            raise
    latest = where.rsplit("/releases/tag/", 1)[1].lstrip("vV")
    want = platform_name()
    download = (f"https://github.com/{REPO}/releases/download/v{latest}/SkyScope-{latest}-for-{want}.zip"
                if want else None)
    return {"latest": latest, "newer": numbers(latest) > numbers(VERSION), "page": where, "download": download,
            "error": None}


def why(exc: Exception) -> str:
    """A failed request's reason in words ("certificate verify failed", "timed out"...), not just its kind."""
    reason = getattr(exc, "reason", None) or exc
    text = str(getattr(reason, "reason", None) or getattr(reason, "strerror", None) or reason).strip()
    return text or exc.__class__.__name__


def _refresh():
    try:
        info = _ask()
    except (OSError, ValueError) as first:
        try:
            info = _ask_page()
        except (OSError, ValueError) as exc:
            info = {"latest": None, "newer": False, "page": f"https://github.com/{REPO}/releases", "download": None,
                    "error": f"Couldn't reach GitHub to check: {why(first)}"
                             + (f"; the releases page: {why(exc)}" if why(exc) != why(first) else "") + ". "
                             "If this computer's antivirus or network filters web traffic, allow SkyScope "
                             "(Python) to reach github.com, or see the releases page."}
    with _lock:
        _state.update(at=time.time(), info=info, busy=False)


# --- updating from inside SkyScope --------------------------------------------------------
# Update to <version> (Settings › About, on the computer running SkyScope): the new version's zip is downloaded in the
# background, checked against the SHA-256 GitHub publishes for it (or at least its size), unpacked into a folder in
# the temporary folder, and its installer opened in front, ready for "Update to <version>". The installer does the
# rest, as when it's run by hand: it stops this SkyScope, updates it (settings kept) and starts it again.

_job = {"stage": "idle", "pct": 0, "text": "", "error": None, "version": None}


def job() -> dict:
    with _lock:
        return dict(_job)


def _say(stage, text, pct=None, error=None):
    with _lock:
        _job.update(stage=stage, text=text, error=error)
        if pct is not None:
            _job["pct"] = pct


def start() -> dict:
    """Begins the update (once at a time): False with why when there's nothing to update to here."""
    import os
    info = status(True)
    if not info.get("latest") or not info.get("digest"):
        info = status(True, now=True)              # (nothing heard from GitHub yet, or only from its plain page)
    if not info.get("newer") or not info.get("download"):
        return {"ok": False, "why": "There's no newer SkyScope to install on this computer."}
    if os.name != "nt" and sys.platform != "darwin":
        return {"ok": False, "why": "On this computer, update from the release page."}
    with _lock:
        if _job["stage"] in ("downloading", "checking", "unpacking", "opening"):
            return {"ok": True}
        _job.update(stage="downloading", pct=0, text="Downloading...", error=None, version=info["latest"])
    threading.Thread(target=_update, args=(info,), name="update", daemon=True).start()
    return {"ok": True}


def _update(info: dict):
    import hashlib
    import os
    import shutil
    import subprocess
    import tempfile
    import zipfile
    version = info["latest"]
    base = tempfile.gettempdir()
    try:
        # earlier updates' folders go (they were only needed until their installer ran)
        for old in os.listdir(base):
            if old.startswith("SkyScope update "):
                shutil.rmtree(os.path.join(base, old), ignore_errors=True)
        work = os.path.join(base, f"SkyScope update {version}")
        os.makedirs(work, exist_ok=True)
        zpath = os.path.join(work, os.path.basename(info["download"]))
        req = urllib.request.Request(info["download"], headers={"User-Agent": f"SkyScope/{VERSION} (update)"})
        sha = hashlib.sha256()
        with urllib.request.urlopen(req, timeout=30) as r, open(zpath, "wb") as f:
            total = int(r.headers.get("Content-Length") or info.get("size") or 0)
            got = 0
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                sha.update(chunk)
                got += len(chunk)
                _say("downloading", f"Downloading SkyScope {version}... {got // 1048576} of {max(1, total // 1048576)} MB",
                     int(got * 80 / total) if total else 40)
        _say("checking", "Checking the download...", 82)
        digest = (info.get("digest") or "").lower()
        if digest.startswith("sha256:") and sha.hexdigest() != digest[7:]:
            raise ValueError("the download isn't the file GitHub published (its checksum differs), so it wasn't used")
        if not digest and info.get("size") and os.path.getsize(zpath) != info["size"]:
            raise ValueError("the download is incomplete, so it wasn't used")
        _say("unpacking", "Unpacking it...", 88)
        if sys.platform == "darwin":
            # (ditto keeps the installer app whole: its permissions and signature)
            subprocess.run(["ditto", "-x", "-k", zpath, work], check=True, capture_output=True)
        else:
            with zipfile.ZipFile(zpath) as z:
                z.extractall(work)
        folder = next((os.path.join(work, d) for d in os.listdir(work)
                       if d.startswith("SkyScope ") and os.path.isdir(os.path.join(work, d))), None)
        if not folder:
            raise ValueError("the download didn't hold the installer")
        _say("opening", "Opening the installer...", 95)
        # the installer gets a clean environment: none of the installers' own answers (SS_PHONES and the like make
        # it install without asking) or notes (SS_INSTALLING) that this SkyScope may have been started with
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("SS_", "TT_", "AT_", "FC_"))}
        if sys.platform == "darwin":
            app = os.path.join(folder, "Install SkyScope.app")
            subprocess.run(["open", app], check=True, env=env)
        else:
            exe = os.path.join(folder, "Install SkyScope.exe")
            # on its own, not as part of SkyScope: the installer stops this SkyScope and starts the new one
            subprocess.Popen([exe], cwd=folder, close_fds=True, env=env,
                             creationflags=0x00000008 | 0x00000200)   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        _say("open", f"The installer is open: click Update to {version} in its window. SkyScope restarts when "
                     "it's done.", 100)
    except Exception as exc:
        _say("error", "", error=f"The update couldn't be prepared: {why(exc) if isinstance(exc, OSError) else exc}. "
                                f"You can download it yourself instead.")


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
