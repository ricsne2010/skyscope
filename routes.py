"""Flight routes (origin and destination airports).

ADS-B doesn't carry a flight plan. Two kinds of source fill the gap:

* FlightAware AeroAPI (optional, the user's own key): the actual filed flight
  plan. Looked up only for the aircraft on the card, within a daily limit, so
  it stays inside FlightAware's free monthly allowance.
* Free community databases, adsbdb.com and hexdb.io, looked up by callsign:
  the published route of that flight number, not the filed plan.

Community routes: flight numbers get reused and the databases can be out of
date, so a route is only shown when it fits where the aircraft actually is: on
or near the line between the two airports (or close to one of them); low only
near one of them; and, well away from the destination, heading roughly toward
it. Better no route than a wrong one. Only airline-style callsigns are looked
up there (three letters then a digit, such as SWA2382): private and VFR
traffic flies under its registration and has no published route. Lookups run
in the background, one at a time, at most one every MIN_GAP_S, and are kept
in memory for a while.

With a FlightAware key, any callsign on the card is looked up, so a private
aircraft on an IFR flight plan shows its route too.
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
HEXDB = "https://hexdb.io/api/v1/route/icao/{}"
HEXDB_FRESH_S = 2 * 365 * 86400  # a hexdb route updated within two years is preferred
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


def _local_airport(a: dict) -> dict:
    """An airports.AirportIndex entry in the shape routes use."""
    return {"icao": a["ident"], "iata": a.get("iata") or "", "city": a.get("city") or a.get("name") or "",
            "lat": float(a["lat"]), "lon": float(a["lon"])}


def _airport(a: dict) -> dict:
    return {"icao": a.get("icao_code") or "", "iata": a.get("iata_code") or "",
            "city": a.get("municipality") or a.get("name") or "",
            "lat": float(a["latitude"]), "lon": float(a["longitude"])}


class RouteLookup:
    """The free community sources (adsbdb.com, then hexdb.io), checked against
    the aircraft's position. airports: an airports.AirportIndex, for the
    positions and cities of hexdb's airport codes."""

    def __init__(self, airports=None):
        self._airports = airports
        self._cache: dict[str, tuple[float, list[dict]]] = {}  # callsign -> candidate routes
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
        if not hit:
            return None
        return next((r for r in hit[1] if plausible(r, lat, lon, track, alt_ft)), None)

    def _start(self) -> None:
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._run, name="routes", daemon=True)
            self._worker.start()

    def _run(self) -> None:
        while True:
            cs = self._queue.get()
            first = self._adsbdb(cs)
            time.sleep(MIN_GAP_S)
            second = self._hexdb(cs)
            with self._lock:
                if first is False and second is False:  # both unreachable: try again later
                    self._queued.discard(cs)
                else:
                    # A recently updated hexdb route first, then adsbdb, then older hexdb ones.
                    fresh = [r for r in (second or []) if r.get("fresh")]
                    stale = [r for r in (second or []) if not r.get("fresh")]
                    self._cache[cs] = (time.time(), fresh + (first or []) + stale)
                    self._queued.discard(cs)
            time.sleep(MIN_GAP_S)

    def _adsbdb(self, callsign: str):
        """[route] from adsbdb.com, [] if it has none, False if unreachable."""
        url = ADSBDB.format(urllib.parse.quote(callsign))
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as exc:
            return [] if exc.code == 404 else False  # 404: no route for this callsign
        except (OSError, ValueError):
            return False
        fr = data.get("response")
        fr = fr.get("flightroute") if isinstance(fr, dict) else None
        try:
            return [{"from": _airport(fr["origin"]), "to": _airport(fr["destination"])}] if fr else []
        except (KeyError, TypeError, ValueError):
            return []

    def _hexdb(self, callsign: str):
        """Routes from hexdb.io ("KPHX-KLAX", or several legs "KPHX-KLAX-KSFO":
        each leg is a candidate), [] if none, False if unreachable."""
        req = urllib.request.Request(HEXDB.format(urllib.parse.quote(callsign)), headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as exc:
            return [] if exc.code == 404 else False
        except (OSError, ValueError):
            return False
        if not isinstance(data, dict) or not data.get("route") or self._airports is None:
            return []
        fresh = time.time() - float(data.get("updatetime") or 0) < HEXDB_FRESH_S
        stops = [self._airports.get(code) for code in str(data["route"]).split("-")]
        legs = []
        for a, b in zip(stops, stops[1:]):
            if a and b:
                legs.append({"from": _local_airport(a), "to": _local_airport(b), "fresh": fresh})
        return legs


# --- FlightAware AeroAPI: the filed flight plan, for the card's aircraft only ----------------

AEROAPI = "https://aeroapi.flightaware.com/aeroapi/flights/{}"
FA_FOUND_TTL_S = 3 * 3600       # a flight's filed route won't change in flight
FA_MISSING_TTL_S = 30 * 60      # no plan yet: maybe one gets filed; ask again later


class FlightAware:
    """Filed routes from FlightAware AeroAPI with the user's own key.
    settings() returns (key, daily_limit). Lookups run one at a time in the
    background; the count per day is kept in usage_path so restarts don't
    reset it, and no lookup is made past the limit."""

    def __init__(self, settings, usage_path):
        self._settings = settings
        self._usage_path = usage_path
        self._cache: dict[str, tuple[float, dict | None]] = {}
        self._pending: set[str] = set()
        self._lock = threading.Lock()
        self._error = ""
        self._bad_key = ""  # a key FlightAware refused: no more lookups until it changes
        self._day, self._count = self._load_usage()

    # Usage today, kept on disk.
    def _load_usage(self) -> tuple[str, int]:
        try:
            data = json.loads(self._usage_path.read_text(encoding="utf-8"))
            return str(data["day"]), int(data["count"])
        except (OSError, ValueError, KeyError, TypeError):
            return time.strftime("%Y-%m-%d"), 0

    def _use_one(self) -> bool:
        """Count a lookup if today's limit allows it."""
        _, limit = self._settings()
        today = time.strftime("%Y-%m-%d")
        if today != self._day:
            self._day, self._count = today, 0
        if self._count >= limit:
            return False
        self._count += 1
        try:
            self._usage_path.write_text(json.dumps({"day": self._day, "count": self._count}), encoding="utf-8")
        except OSError:
            pass
        return True

    def enabled(self) -> bool:
        key = self._settings()[0]
        return bool(key) and key != self._bad_key

    def status(self) -> str:
        key, limit = self._settings()
        if not key:
            return "No FlightAware key: routes come from the free community databases."
        if key == self._bad_key or self._error:
            return self._error or "FlightAware didn't accept the key: check it on the settings page."
        today = time.strftime("%Y-%m-%d")
        used = self._count if today == self._day else 0
        return f"FlightAware: {used} of {limit} lookups used today."

    def filed(self, callsign: str, registration: str = ""):
        """The filed route {"from", "to", "filed": True} once known; "pending"
        while it's being looked up; None when there's none (or no key, or
        today's limit is used up)."""
        cs = (callsign or "").strip().upper()
        if not cs or not self.enabled():
            return None
        with self._lock:
            hit = self._cache.get(cs)
            if hit and time.time() - hit[0] < (FA_FOUND_TTL_S if hit[1] else FA_MISSING_TTL_S):
                return hit[1]
            if cs in self._pending:
                return "pending"
            self._pending.add(cs)
        threading.Thread(target=self._lookup, args=(cs, registration), name="flightaware", daemon=True).start()
        return "pending"

    def _lookup(self, cs: str, registration: str) -> None:
        result, keep = None, True
        with self._lock:
            allowed = self._use_one()
        if allowed:
            result, keep = self._fetch(cs, registration)
        with self._lock:
            # A network problem: ask again in a minute, not on every screen update.
            self._cache[cs] = (time.time(), result) if keep else (time.time() - FA_MISSING_TTL_S + 60, None)
            self._pending.discard(cs)

    def _fetch(self, cs: str, registration: str) -> tuple[dict | None, bool]:
        """(route or None, whether to remember the answer)."""
        key, _ = self._settings()
        req = urllib.request.Request(AEROAPI.format(urllib.parse.quote(cs)) + "?max_pages=1",
                                     headers={"User-Agent": USER_AGENT, "x-apikey": key, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                self._bad_key = key
                self._error = "FlightAware didn't accept the key: check it on the settings page."
                return None, False
            if exc.code == 404:
                return None, True
            self._error = f"FlightAware answered {exc.code}; trying again later."
            return None, False
        except (OSError, ValueError):
            return None, False
        self._error, self._bad_key = "", ""
        flights = [f for f in data.get("flights") or [] if f.get("origin") and f.get("destination")]
        if not flights:
            return None, True
        airborne = [f for f in flights if f.get("actual_off") and not f.get("actual_on")]
        if registration:  # several flights with that number in the air: the one this aircraft is flying
            mine = [f for f in airborne if (f.get("registration") or "").upper() == registration.upper()]
            airborne = mine or airborne
        flight = (airborne or flights)[0]

        def place(a: dict) -> dict:
            return {"icao": a.get("code_icao") or a.get("code") or "", "iata": a.get("code_iata") or "",
                    "city": a.get("city") or a.get("name") or ""}
        return {"from": place(flight["origin"]), "to": place(flight["destination"]), "filed": True}, True


def route_text(route: dict) -> tuple[str, str]:
    """("KPHX → KOAK", "Phoenix → Oakland") for the card."""
    codes = f"{route['from']['icao'] or route['from']['iata']} → {route['to']['icao'] or route['to']['iata']}"
    cities = f"{route['from']['city']} → {route['to']['city']}" if route["from"]["city"] and route["to"]["city"] else ""
    return codes, cities
