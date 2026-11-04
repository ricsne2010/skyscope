"""SkyScope's icon in the Mac menu bar or the Windows taskbar (by the clock),
there while SkyScope runs in the background and gone when it stops. On a Mac
it's drawn like the menu bar's other icons (black or white to suit a light or
dark menu bar), faint if SkyScope stops answering; on Windows it's green, grey
if SkyScope stops answering. Its menu opens the radar or the settings, or stops
SkyScope.

Started by skyscope.py --tray (the installed copies do this) and gone again
when SkyScope stops. Needs pystray and Pillow (and PyObjC on a Mac), which the
installers add; without them SkyScope simply runs without the icon.

    python tray.py --port 7700 --parent <SkyScope's process id>

Designed and Created by Project Moon Pi.
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLL_S = 3
GREEN = (61, 220, 132)
GREY = (138, 138, 138)


def scope_icon(color: tuple[int, int, int], size: int = 64, opacity: float = 1.0):
    """A little radar scope: two rings, a sweep and a blip, on clear."""
    from PIL import Image, ImageDraw
    ss = 4
    w = size * ss
    img = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = w / 2
    line = round(w * 0.075)

    def ring(r):
        d.ellipse([c - r, c - r, c + r, c + r], outline=color + (255,), width=line)

    ring(w * 0.46)
    ring(w * 0.25)
    d.pieslice([c - w * 0.46, c - w * 0.46, c + w * 0.46, c + w * 0.46], -90, -30, fill=color + (110,))
    d.line([(c, c), (c + w * 0.40 * 0.866, c - w * 0.40 * 0.5)], fill=color + (255,), width=line)
    b = w * 0.075
    bx, by = c - w * 0.17, c + w * 0.20
    d.ellipse([bx - b, by - b, bx + b, by + b], fill=color + (255,))
    if opacity < 1:
        img.putalpha(img.getchannel("A").point(lambda a: round(a * opacity)))
    return img.resize((size, size), Image.LANCZOS)


def sharp_on_retina(icon, points: int = 18) -> None:
    """pystray gives the Mac menu bar a picture one pixel per point, which a
    Retina screen blurs; this gives it twice that, shown at the usual size."""
    import io
    import AppKit
    import Foundation
    from PIL import Image

    def assert_image():
        if icon._icon_image is not None:
            return
        b = io.BytesIO()
        icon._icon.resize((points * 2, points * 2), Image.LANCZOS).save(b, "png")
        image = AppKit.NSImage.alloc().initWithData_(Foundation.NSData(b.getvalue()))
        image.setSize_((points, points))
        image.setTemplate_(True)  # macOS colours it to suit a light or dark menu bar
        icon._icon_image = image
        icon._status_item.button().setImage_(image)

    icon._assert_image = assert_image


def first_time(icon) -> None:
    """Once: say where the icon is (Windows tucks new ones under the ^ by the clock)."""
    marker = HERE / "tray-shown"
    if marker.exists():
        return
    try:
        icon.notify("SkyScope is running in the background. Click its icon by the clock for the radar, "
                    "the settings or to stop it.", "SkyScope")
        marker.touch()
    except (OSError, NotImplementedError):
        pass


def alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not h:
            return False
        try:
            return k.WaitForSingleObject(h, 0) == 0x102  # WAIT_TIMEOUT: still running
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)  # (on Windows this would end the process, hence the above)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


class Tray:
    def __init__(self, port: int, parent: int):
        self.port = port
        self.parent = parent
        self.base = f"http://127.0.0.1:{port}"
        self.status = None  # the last /api/status, or None if it didn't answer
        self.stopping = False
        self.icon = None

    def fetch(self):
        try:
            with urllib.request.urlopen(self.base + "/api/status", timeout=2) as r:
                return json.load(r)
        except (OSError, ValueError):
            return None

    # menu text, worked out when the menu is shown
    def headline(self, _item=None) -> str:
        s = self.status
        if self.stopping:
            return "SkyScope is stopping…"
        if s is None:
            return "SkyScope isn't answering"
        return f"SkyScope {s.get('version', '')} is running"

    def detail(self, _item=None) -> str:
        s = self.status
        if not s or self.stopping:
            return "Its messages are in the log file"
        since = datetime.fromtimestamp(s.get("since", time.time())).strftime("%-I:%M %p" if sys.platform != "win32"
                                                                            else "%#I:%M %p")
        n = s.get("aircraft", 0)
        return f"Since {since.lower()} · {n} aircraft in range"

    def open_radar(self, *_):
        webbrowser.open(self.base + "/radar")

    def open_settings(self, *_):
        webbrowser.open(self.base + "/radar_config")

    def stop(self, *_):
        """As the Stop SkyScope icon does (same messages); SkyScope's own
        shutdown request if this isn't an installed copy."""
        self.stopping = True
        self.icon.update_menu()
        mac_app = next((p for p in (Path(base) / "SkyScope/Stop SkyScope.app/Contents" / run
                                    for base in ("/Applications", Path.home() / "Applications")
                                    for run in ("Resources/run.sh", "MacOS/run")) if p.exists()),
                       Path("/nonexistent"))
        win_exe = HERE / "SkyScope.exe"   # (the installed copy's own program: Stop SkyScope's shortcut opens it too)
        if sys.platform == "darwin" and mac_app.exists() and HERE == Path.home() / "Library/Application Support/SkyScope":
            subprocess.Popen([str(mac_app)], start_new_session=True)
        elif sys.platform == "win32" and win_exe.exists():
            subprocess.Popen([str(win_exe), "--stop"], creationflags=0x00000008)  # DETACHED_PROCESS: it outlives this one
        else:
            try:
                req = urllib.request.Request(self.base + "/api/shutdown", data=b"", method="POST",
                                             headers={"X-SkyScope": "stop"})
                urllib.request.urlopen(req, timeout=3).close()
            except OSError:
                pass

    def watch(self):
        """Keeps the icon and menu current; leaves when SkyScope has gone."""
        lit = True
        while alive(self.parent):
            s = self.fetch()
            self.status = s
            if (s is not None) != lit:
                lit = s is not None
                self.icon.icon = self.on if lit else self.off
            self.icon.title = self.headline()
            self.icon.update_menu()
            time.sleep(POLL_S)
        self.icon.stop()

    def run(self):
        import pystray
        from pystray import Menu, MenuItem as Item
        if sys.platform == "darwin":
            self.on, self.off = scope_icon((0, 0, 0)), scope_icon((0, 0, 0), opacity=0.35)
        else:
            self.on, self.off = scope_icon(GREEN), scope_icon(GREY)
        self.status = self.fetch()
        menu = Menu(
            Item(self.headline, None, enabled=False),
            Item(self.detail, None, enabled=False),
            Menu.SEPARATOR,
            Item("Open the radar", self.open_radar, default=True),
            Item("Settings", self.open_settings),
            Menu.SEPARATOR,
            Item("Stop SkyScope", self.stop, enabled=lambda _i: not self.stopping),
        )
        self.icon = pystray.Icon("SkyScope", self.on if self.status is not None else self.off,
                                 self.headline(), menu)
        if sys.platform == "darwin":
            sharp_on_retina(self.icon)
            import AppKit
            # menu bar only: no Python icon in the Dock or the app switcher
            AppKit.NSApplication.sharedApplication().setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

        def setup(icon):
            icon.visible = True
            if sys.platform == "win32":
                first_time(icon)
            threading.Thread(target=self.watch, name="tray-watch", daemon=True).start()

        self.icon.run(setup)


def main() -> int:
    p = argparse.ArgumentParser(description="SkyScope's menu bar / taskbar icon")
    p.add_argument("--port", type=int, default=7700)
    p.add_argument("--parent", type=int, default=os.getppid(), help="leave when this process ends")
    a = p.parse_args()
    try:
        import pystray  # noqa: F401
        import PIL  # noqa: F401
    except ImportError as exc:
        print(f"SkyScope's menu bar icon isn't available ({exc.name} isn't installed)", file=sys.stderr)
        return 1
    Tray(a.port, a.parent).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
