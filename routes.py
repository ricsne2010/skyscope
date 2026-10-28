"""Flight routes (origin and destination airports) for airline flights.

ADS-B doesn't carry a flight plan, so routes come from adsbdb.com's community
database, looked up by callsign: the published route of that flight number,
not the filed plan. Flight numbers get reused and the database can be out of
date, so a route is only shown when it fits where the aircraft actually is:
on or near the line between the two airports (or close to one of them); low
only near one of them; and, well away from the destination, heading roughly
toward it. Better no route than a wrong one.

Only airline-style callsigns are looked up (three letters then a digit, such as
SWA2382). Private and VFR traffic flies under its registration and has no
published route. Lookups run in the background, one at a time, at most one
every MIN_GAP_S, and are kept in memory for a while.
"""

import json
import math
import queue
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "SkyScope/1.0 (+https://github.com/ricsne2010/skyscope)"
ADSBDB = "https://api.adsbdb.com/v0/callsign/{}"
TIMEOUT_S = 8
MIN_GAP_S = 1.5        # at most one outside request every 1.5 s
FOUND_TTL_S = 12 * 3600
MISSING_TTL_S = 6 * 3600
QUEUE_MAX = 200
AIRLINE_CALLSIGN = re.compile(r"^[A-Z]{3}\d[A-Z0-9]{0,4}$")
NM_PER_KM = 1 / 1.852


def is_airline_callsign(callsign: str) -> bool:
    return bool(AIRLINE_CALLSIGN.match((callsign or "").strip().upper()))


def _distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(a))) * NM_PER_KM


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360.0


def plausible(route: dict, lat: float, lon: float, track: float | None, alt_ft: int | None = None) -> bool:
    """Does this route fit an aircraft at (lat, lon) flying `track` at `alt_ft`?"""
    o, d = route["from"], route["to"]
    total = _distance_nm(o["lat"], o["lon"], d["lat"], d["lon"])
    to_origin = _distance_nm(lat, lon, o["lat"], o["lon"])
    to_dest = _distance_nm(lat, lon, d["lat"], d["lon"])
    if to_origin < 40 or to_dest < 40:  # departing or arriving
        return True
    if to_origin + to_dest - total > max(50.0, 0.06 * total):  # well off the line between them
        return False
    if alt_ft is not None and alt_ft < 10000 and min(to_origin, to_dest) > 80:
        return False  # this low, it's climbing out of or descending into some other airport
    if track is not None and to_dest > 60:
        off = abs((_bearing_deg(lat, lon, d["lat"], d["lon"]) - track + 180) % 360 - 180)
        if off > 75:  # heading away from the destination
            return False
    return True


def _airport(a: dict) -> dict:
    return {"icao": a.get("icao_code") or "", "iata": a.get("iata_code") or "",
            "city": a.get("municipality") or a.get("name") or "",
            "lat": float(a["latitude"]), "lon": float(a["longitude"])}


class RouteLookup:
    def __init__(self):
        self._cache: dict[str, tuple[float, dict | None]] = {}
        self._queued: set[str] = set()
        self._queue: queue.Queue[str] = queue.Queue(maxsize=QUEUE_MAX)
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    def route(self, callsign: str, lat: float, lon: float, track: float | None,
              alt_ft: int | None = None) -> dict | None:
        """{"from": airport, "to": airport} when known and it fits this
        aircraft's position, else None (and a lookup is queued if needed).
        airport = {"icao", "iata", "city", "lat", "lon"}."""
        cs = (callsign or "").strip().upper()
        if not is_airline_callsign(cs):
            return None
        with self._lock:
            hit = self._cache.get(cs)
            fresh = hit and time.time() - hit[0] < (FOUND_TTL_S if hit[1] else MISSING_TTL_S)
            if not fresh and cs not in self._queued:
                try:
                    self._queue.put_nowait(cs)
                    self._queued.add(cs)
                except queue.Full:
                    pass
                self._start()
        if not hit or not hit[1]:
            return None
        return hit[1] if plausible(hit[1], lat, lon, track, alt_ft) else None

    def _start(self) -> None:
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._run, name="routes", daemon=True)
            self._worker.start()

    def _run(self) -> None:
        while True:
            cs = self._queue.get()
            result = self._fetch(cs)
            with self._lock:
                if result is not False:  # False: a network problem; try again later
                    self._cache[cs] = (time.time(), result)
                self._queued.discard(cs)
            time.sleep(MIN_GAP_S)

    def _fetch(self, callsign: str):
        url = ADSBDB.format(urllib.parse.quote(callsign))
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as exc:
            return None if exc.code == 404 else False  # 404: no route for this callsign
        except (OSError, ValueError):
            return False
        fr = data.get("response")
        fr = fr.get("flightroute") if isinstance(fr, dict) else None
        try:
            return {"from": _airport(fr["origin"]), "to": _airport(fr["destination"])} if fr else None
        except (KeyError, TypeError, ValueError):
            return None


def route_text(route: dict) -> tuple[str, str]:
    """("KPHX → KOAK", "Phoenix → Oakland") for the card."""
    codes = f"{route['from']['icao'] or route['from']['iata']} → {route['to']['icao'] or route['to']['iata']}"
    cities = f"{route['from']['city']} → {route['to']['city']}" if route["from"]["city"] and route["to"]["city"] else ""
    return codes, cities
