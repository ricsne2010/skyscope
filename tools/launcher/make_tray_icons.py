"""The Windows icon by the clock (SkyScope.exe --tray): green while SkyScope runs, red when it's stopped. Drawn as the
Mac menu bar's (tray.py's scope_icon), at the sizes Windows uses for it.

    python3 tools/launcher/make_tray_icons.py      # writes skyscope-tray-on.ico and skyscope-tray-off.ico here

Designed and Created by Project Moon Pi.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
from tray import scope_icon, GREEN  # noqa: E402

RED = (235, 64, 52)
for name, colour in (("on", GREEN), ("off", RED)):
    scope_icon(colour, 256).save(HERE / f"skyscope-tray-{name}.ico", sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (48, 48), (64, 64)])
    print(f"wrote skyscope-tray-{name}.ico")
