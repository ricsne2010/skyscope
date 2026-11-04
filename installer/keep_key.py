"""The FlightAware API key, kept through an uninstall when you ask: the uninstaller saves it beside SkyScope's folder
and the next install puts it back. Designed and Created by Project Moon Pi.

    keep_key.py save <settings.json> <kept file>      the key (and its daily limit) into the kept file
    keep_key.py restore <settings.json> <kept file>   back into settings.json (unless that has a key), then the kept
                                                      file goes
"""
import json
import os
import sys

FIELDS = ("flightaware_key", "flightaware_daily_limit")


def read(path):
    try:
        with open(path, encoding="utf-8-sig") as f:      # (-sig: a file written by Windows PowerShell starts with a BOM)
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    if os.name != "nt":
        os.chmod(path, 0o600)                            # yours alone: it's a key


def main(what, settings, kept):
    if what == "save":
        s = read(settings)
        if s.get("flightaware_key"):
            write(kept, {k: s[k] for k in FIELDS if k in s})
            print(f"Kept your FlightAware API key for the next install: {kept}")
    elif what == "restore" and os.path.exists(kept):
        if not os.path.exists(settings):
            # a new install: SkyScope's own defaults first (settings.py, beside settings.json, writes them), so the
            # key isn't all there is in the file
            sys.path.insert(0, os.path.dirname(os.path.abspath(settings)))
            try:
                from settings import Settings
                Settings.load()
            except Exception as e:                       # (then just the key: SkyScope fills in the rest)
                print(f"(couldn't write SkyScope's default settings first: {e})")
        k, s = read(kept), read(settings)
        if k.get("flightaware_key") and not s.get("flightaware_key"):
            s.update(k)
            write(settings, s)
            print("Brought back your FlightAware API key (kept when SkyScope was uninstalled)")
        os.remove(kept)


if __name__ == "__main__":
    main(*sys.argv[1:4])
