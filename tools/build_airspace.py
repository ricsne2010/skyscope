#!/usr/bin/env python3
"""Build data/airspace_us.json: US Class B, C and D airspace outlines from the
FAA's open "Class Airspace" dataset (public domain), for the scope's
ATC-style map.

    python3 pi/tools/build_airspace.py
"""

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "airspace_us.json"
SERVICE = ("https://services6.arcgis.com/ssFJjBXIUyZDrSYZ/arcgis/rest/services/"
           "Class_Airspace/FeatureServer/0/query")
FIELDS = "NAME,CLASS,ICAO_ID,LOWER_VAL,LOWER_CODE,UPPER_VAL,UPPER_CODE"
TOLERANCE_DEG = 0.0004  # ~40 m: invisible at scope scale, shrinks the file a lot


def fetch(cls: str) -> list[dict]:
    """All shapes of one class, a page at a time (the service caps responses)."""
    features, offset, page_size = [], 0, 200
    while True:
        query = urllib.parse.urlencode({
            "where": f"CLASS='{cls}'", "outFields": FIELDS, "returnGeometry": "true",
            "outSR": 4326, "geometryPrecision": 5, "resultOffset": offset,
            "resultRecordCount": page_size, "f": "geojson"})
        for attempt in range(4):
            req = urllib.request.Request(f"{SERVICE}?{query}", headers={"User-Agent": "SkyScope/1.0 (+https://github.com/ricsne2010/skyscope)"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                doc = json.load(resp)
            if "features" in doc:
                break
            print(f"  service said {doc.get('error', doc)}; retrying")
            time.sleep(3 * (attempt + 1))
        else:
            raise RuntimeError(f"FAA service kept refusing class {cls} at offset {offset}")
        features += doc["features"]
        more = doc.get("properties", {}).get("exceededTransferLimit") or len(doc["features"]) == page_size
        if not more or not doc["features"]:
            return features
        offset += len(doc["features"])


def simplify(points: list, tol: float) -> list:
    """Douglas-Peucker line simplification (points as [lon, lat])."""
    if len(points) < 3:
        return points
    (x0, y0), (x1, y1) = points[0], points[-1]
    dx, dy = x1 - x0, y1 - y0
    norm = (dx * dx + dy * dy) ** 0.5
    best, index = 0.0, 0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        d = abs(dy * px - dx * py + x1 * y0 - y1 * x0) / norm if norm else ((px - x0) ** 2 + (py - y0) ** 2) ** 0.5
        if d > best:
            best, index = d, i
    if best <= tol:
        return [points[0], points[-1]]
    return simplify(points[:index + 1], tol)[:-1] + simplify(points[index:], tol)


def altitude(val, code) -> str:
    """ATC/chart style: hundreds of feet, or SFC."""
    if code == "SFC" or not val:
        return "SFC"
    return str(round(val / 100))


def main() -> int:
    shapes = []
    for cls in "BCD":
        feats = fetch(cls)
        print(f"class {cls}: {len(feats)} shapes")
        for f in feats:
            p, geom = f["properties"], f["geometry"]
            if not geom:
                continue
            polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
            rings = [[[round(x, 5), round(y, 5)] for x, y in simplify(ring, TOLERANCE_DEG)]
                     for poly in polys for ring in poly]
            shapes.append({"class": cls, "name": p["NAME"], "icao": p["ICAO_ID"] or "",
                           "floor": altitude(p["LOWER_VAL"], p["LOWER_CODE"]),
                           "ceiling": altitude(p["UPPER_VAL"], p["UPPER_CODE"]),
                           "rings": [r for r in rings if len(r) >= 3]})
    OUT.write_text(json.dumps({"source": "FAA Class Airspace (public domain), adds-faa.opendata.arcgis.com",
                               "fields": "rings are [lon, lat]; floor/ceiling in hundreds of feet MSL or SFC",
                               "shapes": shapes}, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB, {len(shapes)} shapes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
