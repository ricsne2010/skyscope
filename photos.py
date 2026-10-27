"""Aircraft photos for the browser display's aircraft card.

First choice: a photo of the exact airframe from Planespotters.net (looked up
by ICAO address, then registration). Their free API allows showing photos
with the photographer's credit and a link back, which the card does.
Fallback: a representative photo of the aircraft type from Wikipedia's article,
taken from Wikimedia Commons with its licence and author.

Only the photo's address and credit come through here; the browser loads the
image itself from Planespotters / Wikimedia. Results are cached in memory.
"""

import html
import json
import re
import threading
import time
import urllib.parse
import urllib.request

USER_AGENT = "SkyScope/1.0 (+https://github.com/ricsne2010/skyscope)"
PLANESPOTTERS = "https://api.planespotters.net/pub/photos/{}/{}"
WIKIPEDIA = "https://en.wikipedia.org/w/api.php"
COMMONS = "https://commons.wikimedia.org/w/api.php"
TIMEOUT_S = 8
AIRFRAME_TTL_S = 24 * 3600  # re-check an airframe's photo after a day
MIN_GAP_S = 1.0  # at most one outside request a second


def _get_json(url: str, params: dict | None = None) -> dict:
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return json.load(resp)


def _plain(text: str) -> str:
    """Strip the HTML Commons puts in author fields."""
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def _author(text: str) -> str:
    """Just the name: drop web addresses, contact details and trailing notes."""
    text = re.sub(r"^\S+\.(?:jpe?g|png|tiff?|gif)\s*:\s*", "", _plain(text), flags=re.I)  # "File.jpg: Name"
    name = re.split(r"\s{2,}|[\n\t]|\s*(?:https?://|www\.|\(|,| - |\S+@|\S+ \[at\])", text)[0].strip()
    return name[:50] or "unknown"


def _model_tokens(desc: str) -> set[str]:
    """Model numbers in a type description: 'AIRBUS A-321neo' → {'A321NEO', 'A321'},
    'BOEING 737-800' → {'737800', '737', '800'}."""
    tokens = set()
    for word in re.findall(r"[A-Za-z0-9-]+", desc.upper()):
        if not re.search(r"\d", word):
            continue
        tokens.add(word.replace("-", ""))
        tokens.update(part for part in word.split("-") if re.search(r"\d", part))
        m = re.match(r"([A-Z]*\d+)", word.replace("-", ""))
        if m:
            tokens.add(m.group(1))
    return {t for t in tokens if len(t) >= 2}


def _search_text(desc: str) -> str:
    """'AIRBUS A-321neo' → 'AIRBUS A321neo'; 'EMBRAER ERJ-170-200 (long wing)' →
    'EMBRAER ERJ170-200' (hyphens inside model names confuse the search)."""
    text = re.sub(r"\([^)]*\)", "", desc)
    return re.sub(r"\b([A-Za-z]{1,3})-(\d)", r"\1\2", text).strip()


def _title_matches(title: str, tokens: set[str]) -> bool:
    flat = re.sub(r"[^A-Z0-9]", "", title.upper())
    return not tokens or any(t in flat for t in tokens)


class PhotoLookup:
    def __init__(self):
        self._airframes: dict[str, tuple[float, dict | None]] = {}
        self._types: dict[str, dict | None] = {}
        self._lock = threading.Lock()  # one outside lookup at a time
        self._last = 0.0

    def _polite(self) -> None:
        wait = self._last + MIN_GAP_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def find(self, hex_id: str, reg: str, desc: str, type_code: str) -> dict | None:
        """{"src", "link", "credit", "kind": "aircraft"|"type", "caption"} or None."""
        with self._lock:
            photo = self._airframe(hex_id, reg)
            if photo is None and (desc or type_code):
                photo = self._type_photo(desc or type_code)
            return photo

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
                    photo = {"src": thumb["src"], "link": p.get("link", ""), "kind": "aircraft",
                             "credit": f"Photo: {p.get('photographer', 'unknown')} · Planespotters.net",
                             "caption": "This aircraft"}
                    break
        self._airframes[key] = (time.monotonic(), photo)
        return photo

    # --- type: Wikipedia lead image from Commons ------------------------------------

    def _type_photo(self, name: str) -> dict | None:
        key = name.strip().lower()
        if key in self._types:
            return self._types[key]
        photo = None
        try:
            self._polite()
            pages = _get_json(WIKIPEDIA, {
                "action": "query", "format": "json", "generator": "search", "gsrlimit": 6,
                "gsrsearch": f"{_search_text(name)} aircraft", "prop": "pageimages|info|extracts", "piprop": "name",
                "inprop": "url", "exintro": 1, "explaintext": 1, "exsentences": 3, "exlimit": "max",
                }).get("query", {}).get("pages", {})
            # A search hit whose title names the same model; failing that, one whose
            # opening sentences do (family articles: "Airbus A320neo family" covers
            # the A321neo). Never an airline or airport that merely mentions it.
            tokens = _model_tokens(name)
            hits = [p for p in sorted(pages.values(), key=lambda p: p.get("index", 99)) if p.get("pageimage")]
            not_operator = lambda p: not re.search(r"\b(airline|airways|airport|carrier|air force base)\b",
                                                   p["title"] + " " + p.get("extract", "")[:160], re.I)
            maker = name.split()[0].lower() if name.split() else ""
            page = next((p for p in hits if _title_matches(p["title"], tokens)), None) or \
                next((p for p in hits if tokens and not_operator(p)
                      and _title_matches(p.get("extract", "")[:400], tokens)), None) or \
                next((p for p in hits[:1] if maker and maker in p["title"].lower()
                      and p["title"].lower() != maker and not_operator(p)), None)
            if page:
                self._polite()
                files = _get_json(COMMONS, {
                    "action": "query", "format": "json", "titles": f"File:{page['pageimage']}",
                    "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 640,
                }).get("query", {}).get("pages", {})
                info = (next(iter(files.values()), {}).get("imageinfo") or [None])[0]
                if info:  # on Commons, so freely licensed (not a fair-use local file)
                    meta = info.get("extmetadata", {})
                    licence = _plain(meta.get("LicenseShortName", {}).get("value", ""))
                    author = _author(meta.get("Artist", {}).get("value", ""))
                    photo = {"src": info.get("thumburl") or info["url"],
                             "link": info.get("descriptionurl", page.get("fullurl", "")),
                             "kind": "type", "caption": f"Type: {page['title']}",
                             "credit": f"Photo: {author} · {licence or 'licence: see link'} · Wikimedia Commons"}
        except Exception as exc:
            print(f"photos: wikipedia {name}: {exc}")
            return None  # not cached: try again next time
        self._types[key] = photo
        return photo
