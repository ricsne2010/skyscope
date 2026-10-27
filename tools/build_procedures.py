#!/usr/bin/env python3
"""Build data/procedures_us.json: SIDs and STARs for US airports from the FAA
CIFP (Coded Instrument Flight Procedures, ARINC 424; public domain).

Each procedure becomes polylines of the fixes it flies through, one per
transition. Legs without a fix (e.g. "climb on heading 078 to 1550, then
vectors") are skipped, so a route starts or ends where vectoring takes over.

    python3 pi/tools/build_procedures.py                  # downloads the current cycle
    python3 pi/tools/build_procedures.py --cifp FAACIFP18 # or reads an unzipped file

Not for navigation: the drawing is an approximation (arcs become chords).
"""

import argparse
import io
import json
import re
import urllib.request
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "procedures_us.json"
DOWNLOAD_PAGE = "https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/cifp/download/"


def latlon(text: str) -> float | None:
    """'N33254393' / 'W112040812' (hemisphere, degrees, minutes, seconds,
    hundredths) → decimal degrees."""
    text = text.strip()
    if len(text) < 9 or text[0] not in "NSEW":
        return None
    deg_len = 2 if text[0] in "NS" else 3
    d, rest = int(text[1:1 + deg_len]), text[1 + deg_len:]
    value = d + int(rest[0:2]) / 60 + int(rest[2:4]) / 3600 + int(rest[4:6]) / 360000
    return -value if text[0] in "SW" else value


def point(line: str, lat_at: int = 32, lon_at: int = 41) -> tuple[float, float] | None:
    lat, lon = latlon(line[lat_at:lat_at + 9]), latlon(line[lon_at:lon_at + 10])
    return (round(lat, 5), round(lon, 5)) if lat is not None and lon is not None else None


def current_cycle_url() -> str:
    """Link to the cycle in effect today (the page also lists the next one)."""
    req = urllib.request.Request(DOWNLOAD_PAGE, headers={"User-Agent": "Mozilla/5.0"})
    page = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    links = sorted(set(re.findall(r'https://[^"]+CIFP_(\d{6})\.zip', page)))
    today = date.today().strftime("%y%m%d")
    current = [c for c in links if c <= today] or links
    return next(u for u in re.findall(r'https://[^"]+CIFP_\d{6}\.zip', page) if current[-1] in u)


def read_lines(path: Path | None) -> list[str]:
    if path:
        return path.read_text(encoding="latin-1").splitlines()
    url = current_cycle_url()
    print(f"downloading {url} ...")
    data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "SkyScope/1.0 (+https://github.com/ricsne2010/skyscope)"}), timeout=300).read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = next(n for n in z.namelist() if n.upper().startswith("FAACIFP"))
        return z.read(name).decode("latin-1").splitlines()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cifp", type=Path, help="an unzipped FAACIFP18 file")
    args = ap.parse_args()
    lines = [l for l in read_lines(args.cifp) if l.startswith("SUSA")]

    # Fix positions, keyed as procedure legs refer to them.
    terminal, enroute, navaid, runway = {}, {}, {}, {}
    for l in lines:
        sec, sub = l[4], l[5]
        if sec == "P" and l[12] in "CN":  # terminal waypoint / terminal NDB
            terminal[(l[6:10].strip(), l[13:18].strip())] = point(l)
        elif sec == "P" and l[12] == "G":  # runway threshold
            runway[(l[6:10].strip(), l[13:18].strip())] = point(l)
        elif sec == "E" and sub == "A":  # enroute waypoint
            enroute[(l[13:18].strip(), l[19:21])] = point(l)
        elif sec == "D":  # VOR / NDB (VOR position, else the DME's)
            navaid[(l[13:17].strip(), l[19:21])] = point(l) or point(l, 55, 64)

    def fix_position(airport: str, l: str):
        ident, region, sec, sub = l[29:34].strip(), l[34:36], l[36], l[37]
        if not ident:
            return None
        if sec == "P" and sub == "G":
            return runway.get((airport, ident))
        if sec == "P":
            return terminal.get((airport, ident))
        if sec == "E":
            return enroute.get((ident, region))
        if sec == "D":
            return navaid.get((ident, region))
        return None

    # Legs, in order, per (airport, SID/STAR, procedure, transition).
    legs = defaultdict(list)
    for l in lines:
        if l[4] != "P" or l[12] not in "DE" or l[38] not in "01":  # primary records only
            continue
        airport = l[6:10].strip()
        kind = "SID" if l[12] == "D" else "STAR"
        key = (airport, kind, l[13:19].strip(), l[20:25].strip())
        pos = fix_position(airport, l)
        if pos:
            legs[key].append((int(l[26:29]), pos[0], pos[1], l[29:34].strip()))

    procedures = defaultdict(lambda: {"SID": defaultdict(list), "STAR": defaultdict(list)})
    for (airport, kind, proc, transition), pts in legs.items():
        pts.sort()
        line = [[lat, lon, fix] for _, lat, lon, fix in pts]
        line = [p for i, p in enumerate(line) if i == 0 or p[:2] != line[i - 1][:2]]  # drop repeats
        if len(line) >= 2:
            procedures[airport][kind][proc].append(line)

    OUT.write_text(json.dumps({
        "source": "FAA CIFP (public domain), not for navigation",
        "format": "airport → SID/STAR → procedure → list of polylines [lat, lon, fix]",
        "airports": procedures}, separators=(",", ":")), encoding="utf-8")
    n_sid = sum(len(p["SID"]) for p in procedures.values())
    n_star = sum(len(p["STAR"]) for p in procedures.values())
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB): {len(procedures)} airports, "
          f"{n_sid} SIDs, {n_star} STARs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
