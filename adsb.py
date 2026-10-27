"""ADS-B client for adsb.fi — Python port of src/services/adsb_client.cpp.

A background thread polls the API and publishes a parsed aircraft list under a
lock; the render loop takes a snapshot each frame and dead-reckons positions
between fetches.
"""

import json
import math
import threading
import time
import urllib.request
from dataclasses import dataclass

API_BASE = "https://opendata.adsb.fi/api/v3/lat/"
KM_PER_NM = 1.852
REQUEST_TIMEOUT_S = 6.0
MIN_REQUEST_GAP_S = 1.5  # adsb.fi public limit is 1 req/s

# Local SDR receiver (readsb / dump1090). "auto" tries these in order: the
# decoders' own output files first, then their web servers.
SDR_AUTO_LOCATIONS = [
    "/run/readsb/aircraft.json",
    "/run/dump1090-fa/aircraft.json",
    "/run/dump1090/aircraft.json",
    "/run/adsbexchange-feed/aircraft.json",
    "http://127.0.0.1/tar1090/data/aircraft.json",
    "http://127.0.0.1:8080/data/aircraft.json",  # PiAware SkyAware
]
SDR_INTERVAL_S = 1.0
SDR_STALE_S = 60.0  # whole file this old → decoder not running
SDR_MAX_POS_AGE_S = 60.0  # drop aircraft whose last position is older
MAX_AIRCRAFT = 800  # 100 mi around a busy area can pass 300
# seen_pos is capped so a very stale fix isn't flung far by dead-reckoning.
MAX_POS_AGE_S = 30.0


@dataclass
class Aircraft:
    hex: str
    lat: float
    lon: float
    nose_deg: float
    track_deg: float
    gs_knots: float  # best available speed (gs, else tas, else ias), for dead-reckoning
    gs_kt: float | None  # ground speed as reported (None if not sent)
    tas_kt: float | None  # true airspeed (only some aircraft report airspeeds)
    ias_kt: float | None  # indicated airspeed
    pos_age_s: float
    callsign: str
    type: str
    desc: str
    reg: str
    alt_ft: int | None  # None when unknown
    on_ground: bool
    vert_rate_fpm: int | None
    squawk: str
    category: str  # ADS-B emitter category, e.g. A3 (large), A7 (rotorcraft)
    db_flags: int  # aircraft-database flags; bit 0 = military
    emergency: str  # ADS-B emergency status, "" when none


def _num(plane: dict, *keys: str) -> float | None:
    for key in keys:
        v = plane.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def _str(plane: dict, key: str) -> str:
    v = plane.get(key)
    return v.strip() if isinstance(v, str) else ""


def parse_aircraft(plane: dict) -> Aircraft | None:
    lat = _num(plane, "lat")
    lon = _num(plane, "lon")
    if lat is None or lon is None:
        return None

    on_ground = plane.get("alt_baro") == "ground"
    alt = _num(plane, "alt_baro", "alt_geom")
    vert = _num(plane, "baro_rate", "geom_rate")
    seen_pos = _num(plane, "seen_pos") or 0.0

    return Aircraft(
        hex=_str(plane, "hex"),
        lat=lat,
        lon=lon,
        nose_deg=_num(plane, "true_heading", "mag_heading", "track", "dir") or 0.0,
        track_deg=_num(plane, "track", "true_heading", "mag_heading", "dir") or 0.0,
        gs_knots=_num(plane, "gs", "tas", "ias") or 0.0,
        gs_kt=_num(plane, "gs"),
        tas_kt=_num(plane, "tas"),
        ias_kt=_num(plane, "ias"),
        pos_age_s=min(max(seen_pos, 0.0), MAX_POS_AGE_S),
        callsign=_str(plane, "flight") or _str(plane, "hex").upper(),
        type=_str(plane, "t"),
        desc=_str(plane, "desc"),
        reg=_str(plane, "r"),
        alt_ft=None if on_ground or alt is None else int(round(alt)),
        on_ground=on_ground,
        vert_rate_fpm=None if vert is None else int(round(vert)),
        squawk=_str(plane, "squawk"),
        category=_str(plane, "category"),
        db_flags=int(_num(plane, "dbFlags") or 0),
        emergency="" if _str(plane, "emergency") in ("", "none") else _str(plane, "emergency"),
    )


class AdsbFeed:
    """Polls for aircraft on a daemon thread. Call start(), then snapshot().
    Ground traffic is kept; the display decides whether to show it.

    Two sources:
      "internet" — the adsb.fi API (rate-limited, polled every interval_s)
      "sdr"      — a local receiver: the aircraft.json written by readsb or
                   dump1090 (same field names as adsb.fi), read every second
    """

    def __init__(self, interval_s: float, source: str = "internet", sdr_location: str = "auto"):
        self._interval_s = interval_s
        self._source = source
        self._sdr_location = sdr_location
        self._sdr_found = ""  # where "auto" found the receiver's data
        self._lock = threading.Lock()
        self._aircraft: list[Aircraft] = []
        self._base_time = 0.0  # monotonic time of last successful fetch
        self._last_error = ""
        self._query: tuple[float, float, float] | None = None  # set_query() first
        self._wake = threading.Event()

    def set_query(self, lat: float, lon: float, radius_km: float) -> None:
        with self._lock:
            changed = self._query != (lat, lon, radius_km)
            self._query = (lat, lon, radius_km)
        if changed:
            self._wake.set()  # fetch the new area right away

    def set_source(self, source: str, sdr_location: str) -> None:
        with self._lock:
            changed = (self._source, self._sdr_location) != (source, sdr_location)
            self._source, self._sdr_location = source, sdr_location
            if changed:
                # Don't show one source's aircraft under the other's name.
                self._aircraft, self._base_time, self._last_error = [], 0.0, ""
                self._sdr_found = ""
        if changed:
            self._wake.set()

    def source_label(self) -> str:
        with self._lock:
            return "SDR receiver" if self._source == "sdr" else "adsb.fi"

    def sdr_status(self) -> str:
        """Where SDR data is coming from, for the settings page."""
        with self._lock:
            if self._source != "sdr":
                return ""
            if self._last_error:
                return f"Receiver: {self._last_error}"
            if self._sdr_found:
                return f"Receiver: reading {self._sdr_found}"
            return "Receiver: looking for readsb / dump1090 ..."

    def start(self) -> None:
        threading.Thread(target=self._run, name="adsb", daemon=True).start()

    def snapshot(self) -> tuple[list[Aircraft], float, str]:
        with self._lock:
            return list(self._aircraft), self._base_time, self._last_error

    def _run(self) -> None:
        last = 0.0
        self._wake.wait()  # no location yet
        while True:
            with self._lock:
                sdr = self._source == "sdr"
            if not sdr:
                # Range changes wake us early; still respect the API's 1 req/s limit.
                time.sleep(max(0.0, last + MIN_REQUEST_GAP_S - time.monotonic()))
            self._wake.clear()
            last = time.monotonic()
            try:
                parsed = self._fetch_sdr() if sdr else self._fetch_internet()
            except Exception as exc:  # network down, timeout, bad JSON, no receiver
                with self._lock:
                    self._last_error = str(exc) or exc.__class__.__name__
                print(f"adsb: {self._last_error}")
            else:
                with self._lock:
                    self._aircraft = parsed[:MAX_AIRCRAFT]
                    self._base_time = time.monotonic()
                    self._last_error = ""
            self._wake.wait(SDR_INTERVAL_S if sdr else self._interval_s)

    def _fetch_internet(self) -> list[Aircraft]:
        with self._lock:
            lat, lon, radius_km = self._query
        url = f"{API_BASE}{lat:.6f}/lon/{lon:.6f}/dist/{radius_km / KM_PER_NM:.1f}"
        doc = _load_json(url)
        return [ac for ac in map(parse_aircraft, doc.get("ac") or []) if ac is not None]

    def _fetch_sdr(self) -> list[Aircraft]:
        with self._lock:
            lat, lon, radius_km = self._query
            location = self._sdr_location
        doc, found = _load_sdr(location)
        with self._lock:
            self._sdr_found = found

        now = doc.get("now")
        if isinstance(now, (int, float)) and time.time() - now > SDR_STALE_S:
            raise RuntimeError(f"data in {found} is {int(time.time() - now)}s old "
                               "(has the decoder stopped?)")

        # A local receiver reports everything it hears; keep what's in range.
        cos_lat = math.cos(math.radians(lat))
        out = []
        for plane in doc.get("aircraft") or []:
            seen_pos = plane.get("seen_pos")
            if isinstance(seen_pos, (int, float)) and seen_pos > SDR_MAX_POS_AGE_S:
                continue  # position too old; the aircraft has likely left
            ac = parse_aircraft(plane)
            if ac is None:
                continue
            dx = (ac.lon - lon) * 111.0 * cos_lat
            dy = (ac.lat - lat) * 111.0
            if math.hypot(dx, dy) <= radius_km:
                out.append(ac)
        return out


def _load_json(location: str) -> dict:
    if location.startswith(("http://", "https://")):
        req = urllib.request.Request(location, headers={"User-Agent": "SkyScope/1.0 (+https://github.com/ricsne2010/skyscope)"})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
            return json.load(resp)
    with open(location, encoding="utf-8") as f:
        return json.load(f)


def _load_sdr(location: str) -> tuple[dict, str]:
    """Read the receiver's aircraft.json; "auto" tries the usual places."""
    if location != "auto":
        return _load_json(location), location
    for candidate in SDR_AUTO_LOCATIONS:
        try:
            return _load_json(candidate), candidate
        except (OSError, ValueError):
            continue
    raise RuntimeError("no readsb or dump1090 data found (is the decoder installed and running?)")
