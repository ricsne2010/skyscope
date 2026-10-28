"""Ground elevation at the radar's centre, for the "low" altitude band
(10,000 ft above the ground, not above the sea: in Denver that's about
15,200 ft MSL).

Looked up from Open-Meteo's free elevation service (worldwide, no key) in
the background and kept for each spot, so it's asked about once per place.
"""

import json
import threading
import urllib.parse
import urllib.request

USER_AGENT = "SkyScope/1.0 (+https://github.com/ricsne2010/skyscope)"
OPEN_METEO = "https://api.open-meteo.com/v1/elevation"
TIMEOUT_S = 8
FT_PER_M = 3.28084


class ElevationLookup:
    def __init__(self):
        self._cache: dict[tuple[float, float], float | None] = {}  # (lat, lon) to 0.01 degree -> feet
        self._pending: set[tuple[float, float]] = set()
        self._lock = threading.Lock()

    def get(self, lat: float, lon: float) -> float | None:
        """Ground elevation in feet, or None until it's known (a lookup is
        started if needed) or if the service can't be reached."""
        key = (round(lat, 2), round(lon, 2))
        with self._lock:
            if key in self._cache:
                return self._cache[key]
            if key in self._pending:
                return None
            self._pending.add(key)
        threading.Thread(target=self._lookup, args=(key,), name="elevation", daemon=True).start()
        return None

    def _lookup(self, key: tuple[float, float]) -> None:
        url = OPEN_METEO + "?" + urllib.parse.urlencode({"latitude": key[0], "longitude": key[1]})
        feet = None
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                feet = float(json.load(resp)["elevation"][0]) * FT_PER_M
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            pass
        with self._lock:
            if feet is not None:
                self._cache[key] = feet
            self._pending.discard(key)  # on failure, the next get() tries again
