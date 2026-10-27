#!/usr/bin/env python3
"""Build the Pi app's airport data from OurAirports (public domain).

Writes two files in pi/data/:
  airports.json       runway map: large, medium and paved small airports, with
                      runway ends, widths and numbers (for drawing the scope)
  airport_index.json  every open large/medium/small airport worldwide, for the
                      "centre on an airport" search on the settings page

    python3 pi/tools/build_airports.py              # downloads the latest CSVs
    python3 pi/tools/build_airports.py --csv DIR    # or uses airports.csv/runways.csv in DIR
"""

import argparse
import csv
import io
import json
import math
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data"
BASE_URL = "https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/"

TYPE_CODES = {"large_airport": "L", "medium_airport": "M", "small_airport": "S"}
HARD_SURFACES = ("ASP", "CON", "PEM", "BIT", "TAR", "PAV", "MAC", "ASFALT", "CEMENT", "CONCRETE")
MIN_SMALL_RUNWAY_FT = 2000  # small airfields: paved runways at least this long


def load_csv(name: str, csv_dir: Path | None) -> list[dict]:
    if csv_dir:
        text = (csv_dir / f"{name}.csv").read_text(encoding="utf-8")
    else:
        print(f"downloading {name}.csv ...")
        with urllib.request.urlopen(BASE_URL + f"{name}.csv", timeout=120) as resp:
            text = resp.read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def num(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_hard(surface: str) -> bool:
    s = surface.upper()
    return any(s.startswith(h) or h in s for h in HARD_SURFACES)


def runway_ends(r: dict, ap_lat: float, ap_lon: float):
    """(le_lat, le_lon, he_lat, he_lon) from the runway's own coordinates, or
    from its true heading and length about the airport's position."""
    coords = [num(r[k]) for k in ("le_latitude_deg", "le_longitude_deg", "he_latitude_deg", "he_longitude_deg")]
    if None not in coords:
        return coords
    heading, length_ft = num(r["le_heading_degT"]), num(r["length_ft"])
    if heading is None or not length_ft:
        return None  # only a runway number: no reliable position or direction
    half_km = length_ft * 0.0003048 / 2
    dlat = half_km * math.cos(math.radians(heading)) / 111.0
    dlon = half_km * math.sin(math.radians(heading)) / (111.0 * math.cos(math.radians(ap_lat)))
    return [ap_lat - dlat, ap_lon - dlon, ap_lat + dlat, ap_lon + dlon]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--csv", type=Path, help="folder with airports.csv and runways.csv")
    args = ap.parse_args()

    airports = {a["ident"]: a for a in load_csv("airports", args.csv)
                if a["type"] in TYPE_CODES and num(a["latitude_deg"]) is not None}
    runways = load_csv("runways", args.csv)

    # Search index: every open airport.
    index = sorted(
        ([a["ident"], a["iata_code"], a["name"], a["municipality"], a["iso_country"],
          round(float(a["latitude_deg"]), 5), round(float(a["longitude_deg"]), 5), TYPE_CODES[a["type"]]]
         for a in airports.values()),
        key=lambda row: ("LMS".index(row[7]), row[0]))

    # Runway map.
    map_airports: dict[str, int] = {}
    map_rows, map_runways = [], []
    for r in runways:
        a = airports.get(r["airport_ident"])
        if a is None or r["closed"] == "1":
            continue
        length = num(r["length_ft"]) or 0
        if a["type"] == "small_airport" and (not is_hard(r["surface"]) or length < MIN_SMALL_RUNWAY_FT):
            continue
        if r["le_ident"].upper().startswith("H"):
            continue  # helipad
        ends = runway_ends(r, float(a["latitude_deg"]), float(a["longitude_deg"]))
        if ends is None:
            continue
        if a["ident"] not in map_airports:
            map_airports[a["ident"]] = len(map_rows)
            map_rows.append({"ident": a["ident"], "name": a["name"], "type": TYPE_CODES[a["type"]],
                             "lat": round(float(a["latitude_deg"]), 5),
                             "lon": round(float(a["longitude_deg"]), 5)})
        map_runways.append([map_airports[a["ident"]]] + [round(v, 6) for v in ends]
                           + [round(num(r["width_ft"]) or 0), r["le_ident"], r["he_ident"], round(length)])

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "airports.json").write_text(json.dumps(
        {"source": "OurAirports (public domain), https://ourairports.com/data/",
         "runway_fields": ["airport", "le_lat", "le_lon", "he_lat", "he_lon", "width_ft",
                           "le_ident", "he_ident", "length_ft"],
         "airports": map_rows, "runways": map_runways}, separators=(",", ":")), encoding="utf-8")
    (OUT / "airport_index.json").write_text(json.dumps(
        {"source": "OurAirports (public domain), https://ourairports.com/data/",
         "fields": ["ident", "iata", "name", "city", "country", "lat", "lon", "type"],
         "airports": index}, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    counts = {t: sum(1 for a in map_rows if a["type"] == t) for t in "LMS"}
    print(f"airports.json: {len(map_rows)} airports {counts}, {len(map_runways)} runways")
    print(f"airport_index.json: {len(index)} airports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
