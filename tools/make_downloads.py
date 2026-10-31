#!/usr/bin/env python3
"""Build the two downloads attached to each GitHub release (as the US Train Tracker's):

  dist/SkyScope-for-Mac.zip       Install SkyScope.command + the Mac installer pieces
  dist/SkyScope-for-Windows.zip   Install SkyScope.bat + the Windows installer pieces

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

1. Install Python 3.10 or newer from https://www.python.org/downloads/ (once).
2. Double-click "Install SkyScope.command".
   If macOS says it can't verify the developer: System Settings > Privacy & Security > Open Anyway.
3. Answer its two questions. It installs SkyScope, starts it and opens the radar.
   If macOS asks whether Python may accept incoming network connections, click Allow
   (that lets phones and SkyScope Satellite displays reach it).

Afterwards use Start SkyScope and Stop SkyScope on your Desktop (also in Applications > SkyScope).
To update, run the installer of a newer version: your settings are kept.
You can delete this folder once it's installed. The full guide is "SkyScope Guide.pdf".
""",
    "Windows": """SkyScope {v} for Windows
Designed and Created by Project Moon Pi

1. Install Python 3.10 or newer from https://www.python.org/downloads/ (once).
   In its installer, tick "Add python.exe to PATH".
2. Double-click "Install SkyScope.bat".
   If Windows says it protected your PC: More info > Run anyway.
3. Answer its two questions. It installs SkyScope, starts it and opens the radar.
   If you choose phones, click Yes if Windows asks to allow changes (that opens the firewall for them).

Afterwards use Start SkyScope and Stop SkyScope on your Desktop (also in the Start menu).
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
        extra = [ROOT / "Install SkyScope.bat"] + sorted((ROOT / "installer/windows").iterdir())
        extra += [launcher / n for n in ("skyscope-start.ico", "skyscope-stop.ico", "skyscope.ico")]
    else:
        extra = [ROOT / "Install SkyScope.command"] + sorted((ROOT / "installer/mac").glob("*.sh"))
        extra += [launcher / n for n in ("skyscope-start.icns", "skyscope-stop.icns", "skyscope.icns")]

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
        add(z, "SkyScope Guide.pdf", GUIDE.read_bytes())
        note = READ_ME[platform].format(v=VERSION)
        add(z, "READ ME FIRST.txt", note.replace("\n", "\r\n") if windows else note)
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB, {len(program) + len(extra) + 2} files)")
    return out


if __name__ == "__main__":
    for p in (sys.argv[1:] or ["Mac", "Windows"]):
        build(p)
