"""Aircraft photos for the browser display's aircraft card.

Only photos of the exact airframe, from Planespotters.net (looked up by ICAO
address, then registration); an aircraft without one gets no photo, rather
than a look-alike in another airline's paint. Their free API allows showing
photos with the photographer's credit and a link back, which the card does.

Only the photo's address and credit come through here; the browser loads the
image itself from Planespotters. Results are cached in memory.
"""

import json
import threading
import time
import urllib.parse
import urllib.request

USER_AGENT = "SkyScope/1.0 (+https://github.com/ricsne2010/skyscope)"
PLANESPOTTERS = "https://api.planespotters.net/pub/photos/{}/{}"
TIMEOUT_S = 8
AIRFRAME_TTL_S = 24 * 3600  # re-check an airframe's photo after a day
MIN_GAP_S = 1.0  # at most one outside request a second


def _get_json(url: str, params: dict | None = None) -> dict:
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return json.load(resp)


def fetch_image(src: str) -> bytes:
    """The photo itself, for the Pi display (kept in memory only, never saved)."""
    req = urllib.request.Request(src, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return resp.read()


class PhotoLookup:
    def __init__(self):
        self._airframes: dict[str, tuple[float, dict | None]] = {}
        self._lock = threading.Lock()  # one outside lookup at a time
        self._last = 0.0

    def _polite(self) -> None:
        wait = self._last + MIN_GAP_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def find(self, hex_id: str, reg: str) -> dict | None:
        """{"src", "link", "credit", "caption"} for this exact aircraft, or None."""
        with self._lock:
            return self._airframe(hex_id, reg)

    # --- exact airframe: Planespotters ---------------------------------------------

    def _airframe(self, hex_id: str, reg: str) -> dict | None:
        key = (hex_id or reg or "").lower()
        if not key or key.startswith("~"):  # TIS-B ids aren't real ICAO addresses
            return None
        cached = self._airframes.get(key)
        if cached and time.monotonic() - cached[0] < AIRFRAME_TTL_S:
            return cached[1]
        photo = None
        for kind, value in (("hex", hex_id), ("reg", reg)):
            if not value:
                continue
            try:
                self._polite()
                found = (_get_json(PLANESPOTTERS.format(kind, urllib.parse.quote(value))).get("photos") or [])
            except Exception as exc:  # offline, rate-limited: try again later
                print(f"photos: planespotters {value}: {exc}")
                return None
            if found:
                p = found[0]
                thumb = p.get("thumbnail_large") or p.get("thumbnail") or {}
                if thumb.get("src"):
                    photo = {"src": thumb["src"], "link": p.get("link", ""),
                             "credit": f"Photo: {p.get('photographer', 'unknown')} · Planespotters.net",
                             "caption": "This aircraft"}
                    break
        self._airframes[key] = (time.monotonic(), photo)
        return photo
