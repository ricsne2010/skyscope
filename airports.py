"""Airport data (OurAirports, built by tools/build_airports.py): the runway map
drawn on the scope, and the worldwide index behind "centre on an airport"."""

import json
import math
import threading
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
TYPE_ORDER = {"L": 0, "M": 1, "S": 2}
TYPE_NAMES = {"L": "large", "M": "medium", "S": "small"}

# Extended centrelines (ATC-style approach courses) for runways this long.
CENTERLINE_MIN_FT = 5000
CENTERLINE_NM = 10


def load_map() -> dict:
    return json.loads((DATA / "airports.json").read_text(encoding="utf-8"))


class AirportIndex:
    """Searchable list of ~48,000 airports, loaded on first use."""

    def __init__(self):
        self._rows: list | None = None
        self._by_ident: dict[str, list] = {}
        self._lock = threading.Lock()

    def _load(self) -> list:
        with self._lock:
            if self._rows is None:
                data = json.loads((DATA / "airport_index.json").read_text(encoding="utf-8"))
                self._rows = data["airports"]
                self._by_ident = {r[0].upper(): r for r in self._rows}
        return self._rows

    @staticmethod
    def as_dict(row: list) -> dict:
        ident, iata, name, city, country, lat, lon, kind = row
        return {"ident": ident, "iata": iata, "name": name, "city": city, "country": country,
                "lat": lat, "lon": lon, "type": TYPE_NAMES[kind]}

    def get(self, ident: str) -> dict | None:
        self._load()
        row = self._by_ident.get((ident or "").upper())
        return self.as_dict(row) if row else None

    def search(self, query: str, limit: int = 12) -> list[dict]:
        """Codes first (exact ICAO/IATA, then prefixes), then airports whose
        name or town has a word starting with the query, then any substring
        match. Within each tier: bigger airports first, then ones with a proper
        four-letter ICAO code."""
        q = (query or "").strip().upper()
        if len(q) < 2:
            return []
        scored = []
        for row in self._load():
            ident, iata, name, city = row[0].upper(), row[1].upper(), row[2].upper(), row[3].upper()
            if q == ident or q == iata:
                tier = 0
            elif ident.startswith(q) or (iata and iata.startswith(q)):
                tier = 1
            elif f" {name} ".replace("-", " ").find(" " + q) >= 0:
                tier = 2  # a word in the airport's name starts with the query
            elif f" {city} ".replace("-", " ").find(" " + q) >= 0:
                tier = 3  # ... or in its town
            elif q in name or q in city:
                tier = 4
            else:
                continue
            # Proper ICAO-style code (EGLL, KE25), not a local id (23AZ, US-5914).
            icao_like = len(ident) == 4 and ident[0].isalpha() and ident.isalnum()
            scored.append((tier, TYPE_ORDER[row[7]], not icao_like, ident, row))
        scored.sort(key=lambda t: t[:4])
        return [self.as_dict(t[4]) for t in scored[:limit]]


def map_features(data: dict, lat: float, lon: float, radius_km: float, outer_km: float,
                 kinds: list, centerlines: bool) -> dict:
    """Airports and runways to draw around (lat, lon), as plain lists shared by
    both displays. Airports up to 25 km past the edge are included so runways
    and centrelines that reach into the scope still appear."""
    cos_lat = math.cos(math.radians(lat))
    reach = radius_km + 25
    near = {}
    for i, ap in enumerate(data["airports"]):
        if ap["type"] not in kinds:
            continue
        dx = (ap["lon"] - lon) * 111.0 * cos_lat
        dy = (ap["lat"] - lat) * 111.0
        if abs(dx) <= reach and abs(dy) <= reach and math.hypot(dx, dy) <= reach:
            near[i] = ap
    runways, longest = [], {}
    for idx, le_lat, le_lon, he_lat, he_lon, width_ft, le_id, he_id, length_ft in data["runways"]:
        if idx in near:
            runways.append({"ends": [le_lat, le_lon, he_lat, he_lon], "width_ft": width_ft or 100,
                            "le": le_id, "he": he_id,
                            "centerline": centerlines and length_ft >= CENTERLINE_MIN_FT})
            longest[idx] = max(longest.get(idx, 0), length_ft)
    # Airport codes: large always; medium ones, and any with a 5,000 ft+ runway
    # (many busy GA fields are "small" in the data), up to ~120 km ranges;
    # the rest up to ~50 km.
    def labelled(i, ap):
        if ap["type"] == "L":
            return True
        if ap["type"] == "M" or longest.get(i, 0) >= CENTERLINE_MIN_FT:
            return outer_km <= 120
        return outer_km <= 50
    airports = [{"ident": ap["ident"], "lat": ap["lat"], "lon": ap["lon"], "type": ap["type"],
                 "label": labelled(i, ap)} for i, ap in near.items()]
    return {"airports": airports, "runways": runways, "centerline_nm": CENTERLINE_NM}
