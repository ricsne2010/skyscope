#!/usr/bin/env python3
"""Build the two downloads attached to each GitHub release (as the US Train Tracker's):

  dist/SkyScope-<version>-for-Mac.zip       Install SkyScope.app (the program inside it: build_mac_app())
  dist/SkyScope-<version>-for-Windows.zip   Install SkyScope.exe + the Windows installer pieces

(named with the version, as is the folder inside, so a download says what it is). It also points the README's
download links at this version's files.

Each holds the program (copied into place by the installer), the guide and a READ ME FIRST note. Only files
tracked by git go in, so a working copy's settings, logo cache and logs never end up in a download.

    python3 tools/make_downloads.py
"""
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
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

1. Double-click "Install SkyScope" (the radar icon).
   The first time, macOS may say it can't check the developer: open System Settings > Privacy & Security,
   scroll down to the message about Install SkyScope and click Open Anyway.
   If this Mac hasn't got Python yet, it offers to install it from python.org first (click Install Python;
   your Mac asks for your password).
2. The installer's window checks this Mac, then asks: phones and SkyScope Satellite displays on your Wi-Fi,
   start at login, and Start and Stop on the Desktop. Click Install and watch its progress.
   If macOS asks whether SkyScope (or Python) may accept incoming network connections, click Allow
   (that lets phones and Satellites reach it).
3. Click Finish. Leave "Open the radar now" ticked to see the radar.

Start, Stop and Uninstall SkyScope are in Applications > SkyScope (Start and Stop on your Desktop too, if you
chose). While SkyScope runs, its radar icon is in the menu bar: click it for the radar, settings or Stop.
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


# "Install SkyScope.app": opens the installer's window (installer/mac/window.py) with no Terminal window, as the
# M.O.S.S. RPi SD Card Creator does. If the Mac has no Python that can draw it, it offers to install python.org's
# (macOS's own progress window while it downloads; the Mac's password to install it), then opens the window.
INSTALLER_SCRIPT = """set here to POSIX path of (path to me)
set mac to here & "Contents/Resources/skyscope/installer/mac/"
try
    do shell script quoted form of (mac & "launch.sh")
on error errMsg number errNum
    if errNum is 3 then
        set pyv to do shell script quoted form of (mac & "get_python.sh") & " version"
        set b to button returned of (display dialog "SkyScope runs on Python, which isn't on this Mac yet." & return & return & "Install Python " & pyv & " from python.org now? It's about 80 MB, and your Mac asks for your password to install it. Then the installer opens." buttons {"Cancel", "Install Python"} default button "Install Python" with title "Install SkyScope" with icon note)
        if b is "Install Python" then
            try
                set progress total steps to -1
                set progress description to "Installing Python " & pyv & " for SkyScope"
                set progress additional description to "Downloading it from python.org..."
                set pkg to do shell script quoted form of (mac & "get_python.sh") & " download"
                set progress additional description to "Installing it (your Mac asks for your password)..."
                do shell script quoted form of (mac & "get_python.sh") & " install " & quoted form of pkg with prompt "Install SkyScope wants to install Python " & pyv & " from python.org." with administrator privileges
                do shell script quoted form of (mac & "launch.sh")
            on error errMsg2 number errNum2
                if errNum2 is not -128 then display dialog "Python wasn't installed: " & errMsg2 buttons {"OK"} default button "OK" with title "Install SkyScope" with icon stop
            end try
        end if
    else
        display dialog "The installer couldn't start: " & errMsg buttons {"OK"} default button "OK" with title "Install SkyScope" with icon stop
    end if
end try
"""


def build_mac_app(dest: Path, program: list[Path]) -> Path:
    """Install SkyScope.app in `dest`: an AppleScript app (osacompile) with the SkyScope icon, holding the program and
    the Mac installer in Contents/Resources/skyscope/, laid out as the project folder."""
    app = dest / "Install SkyScope.app"
    script = dest / "installer.applescript"
    script.write_text(INSTALLER_SCRIPT)
    subprocess.run(["osacompile", "-o", str(app), str(script)], check=True)
    script.unlink()
    res = app / "Contents" / "Resources"
    inside = res / "skyscope"
    launcher = ROOT / "tools" / "launcher"
    for f in program + sorted((ROOT / "installer/mac").iterdir()) + sorted(launcher.glob("*.icns")) + \
            [launcher / "skyscope-1024.png"]:
        if f.is_file() and "__pycache__" not in f.parts:
            to = inside / f.relative_to(ROOT)
            to.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, to)
            if f.suffix == ".sh":
                to.chmod(0o755)
    shutil.copy2(launcher / "skyscope.icns", res / "applet.icns")
    (res / "Assets.car").unlink(missing_ok=True)
    plist = app / "Contents" / "Info.plist"
    subprocess.run(["plutil", "-remove", "CFBundleIconName", str(plist)], capture_output=True)
    for key, kind, value in (("CFBundleName", "string", "Install SkyScope"),
                             ("CFBundleDisplayName", "string", "Install SkyScope"),
                             ("CFBundleIdentifier", "string", "com.projectmoonpi.skyscope.installer"),
                             ("CFBundleShortVersionString", "string", VERSION),
                             ("NSHumanReadableCopyright", "string", "Designed and Created by Project Moon Pi"),
                             ("NSDesktopFolderUsageDescription", "string", "To put Start and Stop SkyScope on your Desktop.")):
        subprocess.run(["plutil", "-replace", key, "-" + kind, value, str(plist)], check=True)
    # sealed (ad hoc: no Apple developer certificate), so macOS sees the app whole after the download
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True, capture_output=True)
    return app


def tracked() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [ROOT / line for line in out.splitlines()]


def build(platform: str) -> Path:
    top = f"SkyScope {VERSION} for {platform}"
    out = DIST / f"SkyScope-{VERSION}-for-{platform}.zip"
    for old in DIST.glob(f"SkyScope-*for-{platform}.zip"):   # earlier versions' builds
        old.unlink()
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
        extra = []        # (the program and the installer go inside Install SkyScope.app)

    def add(z, name, data, executable=False):
        info = zipfile.ZipInfo(f"{top}/{name}", date_time=time.localtime()[:6])
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = ((0o755 if executable else 0o644) | stat.S_IFREG) << 16
        z.writestr(info, data)

    DIST.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w") as z:
        if not windows:
            with tempfile.TemporaryDirectory() as tmp:
                app = build_mac_app(Path(tmp), program)
                for f in sorted(app.rglob("*")):
                    if f.is_file():
                        info = zipfile.ZipInfo(f"{top}/{f.relative_to(tmp).as_posix()}", date_time=time.localtime()[:6])
                        info.compress_type = zipfile.ZIP_DEFLATED
                        info.external_attr = (stat.S_IMODE(f.stat().st_mode) | stat.S_IFREG) << 16
                        z.writestr(info, f.read_bytes())
            program = []
        for f in program + extra:
            data = f.read_bytes()
            if f.suffix in (".bat", ".ps1"):              # Windows line endings, whatever the checkout has
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            add(z, f.relative_to(ROOT).as_posix(), data, executable=f.suffix == ".sh")
        if windows:   # the launchers, with their icons, open the installer's or uninstaller's window (build_launcher.ps1)
            for exe in ("Install SkyScope.exe", "Uninstall SkyScope.exe"):
                add(z, exe, (ROOT / "installer/windows" / exe).read_bytes())
        add(z, "SkyScope Guide.pdf", GUIDE.read_bytes())
        note = READ_ME[platform].format(v=VERSION)
        add(z, "READ ME FIRST.txt", note.replace("\n", "\r\n") if windows else note)
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")
    return out


def update_readme() -> None:
    """The README's download links: this version's files on its GitHub release."""
    readme = ROOT / "README.md"
    text = readme.read_text()
    new = re.sub(r"https://github\.com/projectmoonpi/skyscope/releases/[^)\s]*?SkyScope-[^)\s]*?for-(Mac|Windows)\.zip",
                 lambda m: f"https://github.com/projectmoonpi/skyscope/releases/download/v{VERSION}/SkyScope-{VERSION}-for-{m.group(1)}.zip",
                 text)
    new = re.sub(r"SkyScope [\d.]+ for (Mac|Windows)\]", lambda m: f"SkyScope {VERSION} for {m.group(1)}]", new)
    if new != text:
        readme.write_text(new)
        print(f"README.md: download links now point at {VERSION}")


if __name__ == "__main__":
    for p in (sys.argv[1:] or ["Mac", "Windows"]):
        build(p)
    update_readme()
