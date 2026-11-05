#!/usr/bin/env python3
"""Build the downloads attached to each GitHub release, one file for each computer (as Aviator Trail's):

  dist/SkyScope-<version>-for-Mac.dmg                 Install SkyScope.app (the program inside it: build_mac_app()),
                                                      the guide and a READ ME FIRST note
  dist/Install-SkyScope-<version>-for-Windows.exe     the installer, carrying the program (Payload.cs)

and, for SkyScope 1.8.5's Update button (it looks for zips), SkyScope-<version>-for-Mac.zip and -for-Windows.zip.
Each is named with the version, so a download says what it is. It also points the README's download links at this
version's files.

Only files tracked by git go in, so a working copy's settings, logo cache and logs never end up in a download.

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

1. Double-click "Install SkyScope" (the radar icon) in this window.
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
Uninstall SkyScope asks whether to delete your FlightAware API key (if you added one) or keep it for the next
install.
To update, run the installer of a newer version: your settings are kept.
Once it's installed you can eject this disk image and delete the download. The full guide is "SkyScope Guide.pdf".
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


MARK = b"MOONPI-PAYLOAD-1"      # (installer/windows/src/Payload.cs reads it)


def program_files(windows: bool) -> list[Path]:
    files = tracked()
    program = [f for f in files if (f.parent == ROOT and f.suffix == ".py")
               or f.relative_to(ROOT).parts[0] in ("web", "data", "docs")
               or f.name in ("README.md", "LICENSE")
               or f.relative_to(ROOT).as_posix() == "installer/keep_key.py"]   # (both installers)
    if ROOT / "installer/filecheck.py" not in program:
        program.append(ROOT / "installer/filecheck.py")   # (both installers: Repair and Update check files with it)
    if windows:
        # the Windows programs (built from installer/windows/src by build.sh) and Python's side of running it
        launcher = ROOT / "tools" / "launcher"
        program += [ROOT / "installer/windows" / n for n in ("SkyScope.exe", "Uninstall SkyScope.exe", "run.py")]
        program += [launcher / n for n in ("skyscope-start.ico", "skyscope-stop.ico", "skyscope-uninstall.ico", "skyscope.ico",
                                          "skyscope-tray-on.ico", "skyscope-tray-off.ico")]
    return program


def zip_entry(z, name, data, mode=0o644):
    info = zipfile.ZipInfo(name, date_time=time.localtime()[:6])
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (mode | stat.S_IFREG) << 16
    z.writestr(info, data)


def build_windows() -> Path:
    """Install-SkyScope-<version>-for-Windows.exe: the installer with the program's files (a zip) added to its end,
    as NSIS and Inno Setup installers carry theirs (Payload.cs unpacks them). One file: download it, double-click it."""
    out = DIST / f"Install-SkyScope-{VERSION}-for-Windows.exe"
    for old in DIST.glob("Install-SkyScope-*-for-Windows.exe"):
        old.unlink()
    with tempfile.SpooledTemporaryFile() as buf:
        with zipfile.ZipFile(buf, "w") as z:
            for f in program_files(True):
                zip_entry(z, f.relative_to(ROOT).as_posix(), f.read_bytes())
        buf.seek(0)
        payload = buf.read()
    exe = (ROOT / "installer/windows/Install SkyScope.exe").read_bytes()
    out.write_bytes(exe + payload + len(payload).to_bytes(8, "little") + MARK)
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")
    return out


def build_mac() -> Path:
    """SkyScope-<version>-for-Mac.dmg: a disk image holding Install SkyScope.app, the guide and a READ ME. One file:
    download it, double-click it, double-click Install SkyScope."""
    out = DIST / f"SkyScope-{VERSION}-for-Mac.dmg"
    for old in DIST.glob("SkyScope-*-for-Mac.dmg"):
        old.unlink()
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / f"SkyScope {VERSION}"
        stage.mkdir()
        build_mac_app(stage, program_files(False))
        shutil.copy2(GUIDE, stage / "SkyScope Guide.pdf")
        (stage / "READ ME FIRST.txt").write_text(READ_ME["Mac"].format(v=VERSION))
        subprocess.run(["hdiutil", "create", "-quiet", "-volname", f"Install SkyScope {VERSION}", "-srcfolder", str(stage),
                        "-fs", "HFS+", "-format", "UDZO", "-ov", str(out)], check=True)
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")
    return out


def build_old_zip(platform: str) -> Path:
    """SkyScope-<version>-for-<platform>.zip: for SkyScope 1.8.5's Update button, which looks for a zip holding a
    "SkyScope <version> ..." folder with the installer in it (the one-file installer, on Windows)."""
    top = f"SkyScope {VERSION} for {platform}"
    out = DIST / f"SkyScope-{VERSION}-for-{platform}.zip"
    for old in DIST.glob(f"SkyScope-*for-{platform}.zip"):
        old.unlink()
    with zipfile.ZipFile(out, "w") as z:
        if platform == "Windows":
            zip_entry(z, f"{top}/Install SkyScope.exe", (DIST / f"Install-SkyScope-{VERSION}-for-Windows.exe").read_bytes())
        else:
            with tempfile.TemporaryDirectory() as tmp:
                app = build_mac_app(Path(tmp), program_files(False))
                for f in sorted(app.rglob("*")):
                    if f.is_file():
                        zip_entry(z, f"{top}/{f.relative_to(tmp).as_posix()}", f.read_bytes(), stat.S_IMODE(f.stat().st_mode))
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")
    return out


def update_readme() -> None:
    """The README's download links: this version's files on its GitHub release."""
    readme = ROOT / "README.md"
    text = readme.read_text()
    def link(m):
        name = (f"SkyScope-{VERSION}-for-Mac.dmg" if m.group(1) == "Mac"
                else f"Install-SkyScope-{VERSION}-for-Windows.exe")
        return f"https://github.com/projectmoonpi/skyscope/releases/download/v{VERSION}/{name}"
    new = re.sub(r"https://github\.com/projectmoonpi/skyscope/releases/[^)\s]*?SkyScope-[^)\s]*?for-(Mac|Windows)\.(?:zip|dmg|exe)",
                 link, text)
    new = re.sub(r"SkyScope [\d.]+ for (Mac|Windows)\]", lambda m: f"SkyScope {VERSION} for {m.group(1)}]", new)
    if new != text:
        readme.write_text(new)
        print(f"README.md: download links now point at {VERSION}")


if __name__ == "__main__":
    DIST.mkdir(exist_ok=True)
    for p in (sys.argv[1:] or ["Mac", "Windows"]):
        (build_mac if p == "Mac" else build_windows)()
        build_old_zip(p)
    update_readme()
