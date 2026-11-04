#!/usr/bin/env python3
"""Build the two downloads attached to each GitHub release (as the US Train Tracker's):

  dist/SkyScope-for-Mac.zip       Install SkyScope.command + the Mac installer pieces
  dist/SkyScope-for-Windows.zip   Install SkyScope.exe + the Windows installer pieces

Each holds the program (copied into place by the installer), the guide and a READ ME FIRST note. Only files
tracked by git go in, so a working copy's settings, logo cache and logs never end up in a download.

    python3 tools/make_downloads.py
"""
import re
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
GUIDE = ROOT / "docs" / "SkyScope-Guide.pdf"
VERSION = re.search(r'VERSION = "([^"]+)"', (ROOT / "version.py").read_text()).group(1)

READ_ME = {
    "Mac": """SkyScope {v} for Mac
Designed and Created by Project Moon Pi

1. Double-click "Install SkyScope.command".
   If macOS says it can't verify the developer: System Settings > Privacy & Security > Open Anyway.
   If Python isn't installed yet, it offers to install it from python.org (click Install Python;
   it asks for your Mac password).
2. Answer its three questions (phones, start at login, Desktop icons). It installs SkyScope, starts
   it and opens the radar.
   If macOS asks whether SkyScope (or Python) may accept incoming network connections, click Allow
   (that lets phones and SkyScope Satellite displays reach it).

Afterwards use Start SkyScope and Stop SkyScope in Applications > SkyScope (and on your Desktop if you
chose). To remove it, double-click Uninstall SkyScope in Applications > SkyScope.
While SkyScope runs, its radar icon is in the menu bar: click it for the radar, settings or Stop.
To update, run the installer of a newer version: your settings are kept.
You can delete this folder once it's installed. The full guide is "SkyScope Guide.pdf".
""",
    "Windows": """SkyScope {v} for Windows
Designed and Created by Project Moon Pi

1. Extract this zip (right-click it, Extract All), then double-click "Install SkyScope" (the radar icon).
   If Windows says it protected your PC: More info > Run anyway.
2. Choose where to install it (or keep the folder it suggests), whether phones and SkyScope Satellite
   displays on your Wi-Fi may open it, whether it starts when you sign in, and whether Start and Stop
   go on the Desktop, then click Install. If this PC doesn't have Python 3.10 or newer, it installs
   Python from python.org for you too (no admin permission needed).
   If you chose phones, a note comes up before Windows asks to allow Windows PowerShell to make changes:
   click Yes (that opens the firewall for them).
3. Click Finish. Leave "Open the radar now" ticked to see the radar.

Afterwards use Start SkyScope and Stop SkyScope in the Start menu (and on your Desktop if you chose).
To remove it: Remove SkyScope in the Start menu, or Uninstall SkyScope in the folder it's installed in
or beside the installer in this folder; or Settings > Apps.
While SkyScope runs, its green radar icon is by the clock (click ^ if it's hidden): click it for the
radar, right-click for the settings or Stop.
To update, run the installer of a newer version: your settings are kept.
You can delete this folder once it's installed. The full guide is "SkyScope Guide.pdf".
""",
}


def tracked() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [ROOT / line for line in out.splitlines()]


def build(platform: str) -> Path:
    top = f"SkyScope for {platform}"
    out = DIST / f"SkyScope-for-{platform}.zip"
    windows = platform == "Windows"
    files = tracked()
    program = [f for f in files if (f.parent == ROOT and f.suffix == ".py")
               or f.relative_to(ROOT).parts[0] in ("web", "data", "docs")
               or f.name in ("README.md", "LICENSE")]
    launcher = ROOT / "tools" / "launcher"
    if windows:
        extra = sorted(f for f in (ROOT / "installer/windows").iterdir() if f.is_file() and f.name != "Install SkyScope.exe")
        extra += [launcher / n for n in ("skyscope-start.ico", "skyscope-stop.ico", "skyscope-uninstall.ico", "skyscope.ico")]
    else:
        extra = [ROOT / "Install SkyScope.command"] + sorted((ROOT / "installer/mac").glob("*.sh"))
        extra += [launcher / n for n in ("skyscope-start.icns", "skyscope-stop.icns", "skyscope-uninstall.icns", "skyscope.icns")]

    def add(z, name, data, executable=False):
        info = zipfile.ZipInfo(f"{top}/{name}", date_time=time.localtime()[:6])
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = ((0o755 if executable else 0o644) | stat.S_IFREG) << 16
        z.writestr(info, data)

    DIST.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w") as z:
        for f in program + extra:
            data = f.read_bytes()
            if f.suffix in (".bat", ".ps1"):              # Windows line endings, whatever the checkout has
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            add(z, f.relative_to(ROOT).as_posix(), data, executable=f.suffix in (".command", ".sh"))
        if windows:   # the launchers, with their icons, open the installer's or uninstaller's window (build_launcher.ps1)
            for exe in ("Install SkyScope.exe", "Uninstall SkyScope.exe"):
                add(z, exe, (ROOT / "installer/windows" / exe).read_bytes())
        add(z, "SkyScope Guide.pdf", GUIDE.read_bytes())
        note = READ_ME[platform].format(v=VERSION)
        add(z, "READ ME FIRST.txt", note.replace("\n", "\r\n") if windows else note)
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB, {len(program) + len(extra) + 2 + 2 * windows} files)")
    return out


if __name__ == "__main__":
    for p in (sys.argv[1:] or ["Mac", "Windows"]):
        build(p)
