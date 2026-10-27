"""ATC map overlays (US only): Class B/C/D airspace (FAA Class Airspace) and
SID/STAR routes (FAA CIFP), built by tools/build_airspace.py and
tools/build_procedures.py. Shared by both displays. Not for navigation.
"""

import json
import math
import re
import threading
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"


class Overlays:
    """Loads each data file on first use (airspace ~1.6 MB, procedures ~2 MB)."""

    def __init__(self):
        self._airspace = None
        self._procedures = None
        self._lock = threading.Lock()

    def _load(self, name: str):
        path = DATA / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def airspace_near(self, lat: float, lon: float, reach_km: float) -> list[dict]:
        """Class B/C/D shapes with any point within reach_km of the centre."""
        with self._lock:
            if self._airspace is None:
                self._airspace = (self._load("airspace_us.json") or {}).get("shapes", [])
        cos_lat = math.cos(math.radians(lat))
        out = []
        for s in self._airspace:
            if any(math.hypot((x - lon) * 111 * cos_lat, (y - lat) * 111) <= reach_km
                   for ring in s["rings"] for x, y in ring[::4]):
                out.append(s)
        return out

    def _procs(self) -> dict:
        with self._lock:
            if self._procedures is None:
                self._procedures = (self._load("procedures_us.json") or {}).get("airports", {})
        return self._procedures

    def procedures_for(self, selection: dict, mask: str = "both") -> list[dict]:
        """SID and/or STAR polylines. selection: {airport: "sid"|"star"|"both"};
        mask: the overall switch ("off", "sid", "star", "both").
        Each item: {airport, kind, name, lines}."""
        if mask not in ("sid", "star", "both"):
            return []
        out = []
        for ap, choice in selection.items():
            kinds = [k for k in ("SID", "STAR")
                     if choice in (k.lower(), "both") and mask in (k.lower(), "both")]
            for kind in kinds:
                for name, lines in self._procs().get(ap, {}).get(kind, {}).items():
                    out.append({"airport": ap, "kind": kind, "name": name, "lines": lines})
        return out

    def counts(self, ident: str) -> tuple[int, int]:
        """(number of SIDs, number of STARs) published for an airport."""
        p = self._procs().get(ident, {})
        return len(p.get("SID", {})), len(p.get("STAR", {}))

    def airports_near(self, lat: float, lon: float, reach_km: float, index) -> list[dict]:
        """Airports with published SIDs/STARs within reach_km, larger ones
        first, then nearest. index: an AirportIndex for names and positions."""
        cos_lat = math.cos(math.radians(lat))
        out = []
        for ident in self._procs():
            ap = index.get(ident)
            if not ap:
                continue
            d = math.hypot((ap["lon"] - lon) * 111 * cos_lat, (ap["lat"] - lat) * 111)
            if d <= reach_km:
                sids, stars = self.counts(ident)
                out.append({"ident": ident, "name": ap["name"], "type": ap["type"],
                            "dist_km": d, "sids": sids, "stars": stars})
        order = {"large": 0, "medium": 1, "small": 2}
        return sorted(out, key=lambda a: (order.get(a["type"], 3), a["dist_km"]))


def centroid(ring: list) -> tuple[float, float, float]:
    """(lon, lat, |area|) of a polygon ring of [lon, lat] points."""
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(a) < 1e-12:
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        return sum(xs) / len(xs), sum(ys) / len(ys), 0.0
    return cx / (3 * a), cy / (3 * a), abs(a) / 2
