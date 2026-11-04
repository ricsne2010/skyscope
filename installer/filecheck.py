"""Checks an app's installed files, for the installers' Repair and Update (Mac and Windows). The same file is in
Train Tracker's, SkyScope's and Aviator Trail's installers; FC_APP names the app in what it prints.

Run with the app's own Python (its venv) for check and compare:

  filecheck.py check
      Repair: checks every file of every installed package against the fingerprint (SHA-256) pip wrote down when it
      installed it (the package's RECORD). Prints "BAD <package> <file> (changed|missing)" for each damaged file,
      "REPAIR <package>==<version>" for each package that needs installing again, and a summary line last.
      Exit 0: all good; 1: something to repair.

  filecheck.py compare <wheel>
      Update: compares the files in the new installer's Train Tracker (a wheel, built from it) with the installed
      ones. Prints "CHANGED / NEW / GONE <file>" for each difference and a summary line last.
      Exit 0: the same; 1: different (or not installed).

  filecheck.py sync repair|update <from> <to> <item>...
      For a program that's copied rather than installed by pip: compares each of the installer's files (the items,
      folders or files, * allowed, under <from>) with the installed copy under <to>, and copies only those that are
      damaged, missing or different. Files an earlier install put there (listed in <to>/installed-files.json) that
      this installer no longer has are removed; anything else there, such as settings, is left alone. Prints
      "FIXED / CHANGED / NEW / GONE <file>" and a summary line last. Exit 0: nothing needed copying; 1: copied.

Designed and Created by Project Moon Pi.
"""
import base64
import csv
import glob
import hashlib
import io
import json
import os
import shutil
import sys
import zipfile
from importlib import metadata

APP = os.environ.get("FC_APP", "The program")
MANIFEST = "installed-files.json"
SKIP = ("__pycache__", ".DS_Store")


def digest(data):
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def file_digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return "sha256=" + base64.urlsafe_b64encode(h.digest()).rstrip(b"=").decode()


def record(dist):
    """[(path, fingerprint or "", where it is)] from the package's RECORD. (Read directly: dist.files leaves out
    files that are missing, since Python 3.12, and missing files are just what Repair looks for.)"""
    rows = []
    for row in csv.reader(io.StringIO(dist.read_text("RECORD") or "")):
        if row:
            rows.append((row[0].replace(os.sep, "/"), row[1] if len(row) > 1 else "", str(dist.locate_file(row[0]))))
    return rows


def norm(name):
    return name.lower().replace("_", "-").replace(".", "-")


def check():
    files = packages = 0
    bad = {}
    seen = set()
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if not name or norm(name) in seen:
            continue
        seen.add(norm(name))
        packages += 1
        for f, want, path in record(dist):
            if not want.startswith("sha256="):
                continue    # (RECORD itself, and files made at install time, such as .pyc, have no fingerprint)
            files += 1
            if not os.path.isfile(path):
                problem = "missing"
            elif file_digest(path) != want:
                problem = "changed"
            else:
                continue
            print(f"BAD {name} {f} ({problem})")
            bad.setdefault((name, dist.version), 0)
            bad[(name, dist.version)] += 1
    for name, version in sorted(bad):
        print(f"REPAIR {name}=={version}")
    count = sum(bad.values())
    print(f"Checked {files:,} files in {packages} packages: " + (f"{count} damaged or missing." if bad else "all good."))
    return 1 if bad else 0


def compare(wheel):
    with zipfile.ZipFile(wheel) as z:
        rec = next(n for n in z.namelist() if n.endswith(".dist-info/RECORD"))
        new = {}
        for row in csv.reader(io.StringIO(z.read(rec).decode())):
            if row and not row[0].endswith(".dist-info/RECORD"):
                new[row[0]] = row[1] or digest(z.read(row[0]))
    package = os.path.basename(wheel).split("-")[0]
    try:
        dist = metadata.distribution(package)
    except metadata.PackageNotFoundError:
        print(f"{APP} isn't installed yet: all {sum('.dist-info/' not in p for p in new)} files are new.")
        return 1
    old = {}
    for path, _, where in record(dist):
        if ".dist-info/" in path or path.endswith(".pyc") or path.startswith(".."):
            continue    # (the package's own notes, compiled caches and its command in bin/Scripts are made by pip)
        old[path] = where
    changed = gone = same = 0
    for path, want in sorted(new.items()):
        if ".dist-info/" in path:
            continue
        if path not in old or not os.path.isfile(old[path]):
            print(f"NEW {path}")
        elif file_digest(old[path]) != want:
            print(f"CHANGED {path}")
            changed += 1
        else:
            same += 1
    added = sum(1 for p in new if ".dist-info/" not in p and (p not in old or not os.path.isfile(old[p])))
    for path in sorted(set(old) - set(new)):
        print(f"GONE {path}")
        gone += 1
    if not (changed or added or gone):
        print(f"Compared {same} files: the installed {APP} already matches this installer's.")
        return 0
    print(f"Compared the installed {APP} {dist.version} with this installer's: {changed} file"
          f"{'s' * (changed != 1)} changed, {added} new, {gone} no longer needed and {same} the same. It was brought up to "
          f"date with them; the parts it runs on change only where this version needs them to.")
    return 1


def sync(why, src, dest, items):
    want = {}
    for item in items:
        for path in sorted(glob.glob(os.path.join(src, item))):
            walk = [(path, [], [])] if os.path.isfile(path) else os.walk(path)
            for top, dirs, names in walk:
                dirs[:] = [d for d in dirs if d not in SKIP]
                for name in names or [None]:
                    full = top if name is None else os.path.join(top, name)
                    if name is None and not os.path.isfile(full) or os.path.basename(full) in SKIP or full.endswith(".pyc"):
                        continue
                    want[os.path.relpath(full, src).replace(os.sep, "/")] = file_digest(full)
    try:
        with open(os.path.join(dest, MANIFEST)) as f:
            before = json.load(f)
    except (OSError, ValueError):
        before = {}
    copied = gone = same = 0
    for rel, d in want.items():
        target = os.path.join(dest, *rel.split("/"))
        if os.path.isfile(target) and file_digest(target) == d:
            same += 1
            continue
        if why == "repair":
            print(f"FIXED {rel} ({'changed' if os.path.isfile(target) else 'missing'})")
        else:
            print(f"{'CHANGED' if os.path.isfile(target) else 'NEW'} {rel}")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(os.path.join(src, *rel.split("/")), target)
        copied += 1
    for rel in sorted(set(before) - set(want)):
        target = os.path.join(dest, *rel.split("/"))
        if os.path.isfile(target):
            os.remove(target)
            print(f"GONE {rel}")
            gone += 1
    with open(os.path.join(dest, MANIFEST), "w") as f:
        json.dump(want, f, indent=0, sort_keys=True)
    total = len(want)
    if why == "repair":
        print(f"Checked {total:,} program files: " +
              (f"{copied} damaged or missing, put back from the installer." if copied else "all good."))
    elif not (copied or gone):
        print(f"Compared {total:,} program files: the installed {APP} already matches this installer's.")
    else:
        print(f"Compared {total:,} program files with the installed ones: copied {copied} new or changed, "
              f"removed {gone} no longer needed, {same} unchanged.")
    return 1 if copied or gone else 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["sync"] and len(sys.argv) >= 6 and sys.argv[2] in ("repair", "update"):
        sys.exit(sync(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5:]))
    if sys.argv[1:2] == ["check"]:
        sys.exit(check())
    if sys.argv[1:2] == ["compare"] and len(sys.argv) == 3:
        sys.exit(compare(sys.argv[2]))
    sys.exit(__doc__)
