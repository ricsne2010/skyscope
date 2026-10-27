"""Which aircraft to show: class (airliner, GA, ...), type codes, operators,
country of registration and an altitude band. Shared by both displays.
"""

import fnmatch
import json
import re
from pathlib import Path

import symbols

HERE = Path(__file__).resolve().parent
COUNTRIES_PATH = HERE / "data" / "icao_countries.json"

# Aircraft classes, in the order shown on the settings page.
CLASSES = [
    ("airliner", "Airliners"),
    ("bizjet", "Business jets"),
    ("ga", "General aviation"),
    ("helicopter", "Helicopters"),
    ("military", "Military"),
    ("other", "Other / unknown"),
]
CLASS_LABELS = dict(CLASSES)

# Altitude blocks (barometric altitude, feet). FL180 is where US Class A
# airspace starts; ADS-B traffic above FL600 is practically never seen.
ALT_BANDS = [
    ("low", "10,000 ft and below"),
    ("mid", "10,001 ft to FL180"),
    ("high", "FL180 to FL600"),
]


def altitude_band(alt_ft: int) -> str:
    if alt_ft <= 10000:
        return "low"
    if alt_ft < 18000:
        return "mid"
    return "high"

AIRLINE_CALLSIGN_RE = re.compile(r"^[A-Z]{3}\d")
DB_FLAG_MILITARY = 1  # adsb.fi / readsb "dbFlags" bit
GROUND_STATION_TYPES = {"TWR", "GND", "GRND", "SERV"}


def split_codes(text: str) -> list[str]:
    """'b738, A32*  c172' → ['B738', 'A32*', 'C172']"""
    return [c for c in re.split(r"[\s,;]+", (text or "").upper()) if c]


class AircraftFilter:
    def __init__(self):
        data = json.loads(COUNTRIES_PATH.read_text(encoding="utf-8"))
        # Narrowest range first, so a small block inside a bigger one wins.
        self._ranges = sorted(((r["start"], r["end"], r["country"]) for r in data["ranges"]),
                              key=lambda r: r[1] - r[0])
        self.countries = sorted({r[2] for r in self._ranges})
        self._country_cache: dict[str, str | None] = {}

    def country(self, hex_id: str) -> str | None:
        """Country of registration from the 24-bit ICAO address. None for
        non-ICAO addresses (e.g. TIS-B '~' ids) or unallocated blocks."""
        if hex_id in self._country_cache:
            return self._country_cache[hex_id]
        found = None
        try:
            addr = int(hex_id, 16)
        except ValueError:
            addr = None
        if addr is not None:
            for start, end, name in self._ranges:
                if start <= addr <= end:
                    found = name
                    break
        self._country_cache[hex_id] = found
        return found

    @staticmethod
    def aircraft_class(ac) -> str:
        """One class per aircraft. A light aircraft flying a school's
        airline-style callsign is still GA; a turboprop is an airliner only
        when it flies an airline callsign."""
        if (ac.type or "").upper() in GROUND_STATION_TYPES:
            return "other"  # fixed transmitters, not aircraft
        if ac.db_flags & DB_FLAG_MILITARY:
            return "military"
        kind = symbols.classify(ac.category, ac.type)
        if kind == "heli":
            return "helicopter"
        if not ac.type and ac.category in ("", "A0", "B0", "C0", "C1", "C2", "C3"):
            return "other"  # nothing known about it (e.g. TIS-B, ground vehicles)
        if kind == "bizjet":
            return "bizjet"
        if kind in ("jet", "heavy"):
            return "airliner"
        if kind == "turboprop" and AIRLINE_CALLSIGN_RE.match(ac.callsign or ""):
            return "airliner"
        return "ga"

    @staticmethod
    def active(st) -> bool:
        """True when any filter beyond the ground-traffic switch is on."""
        return bool(st.hidden_classes
                    or (st.type_mode != "off" and split_codes(st.type_filter))
                    or (st.operator_mode != "off" and split_codes(st.operator_filter))
                    or (st.country_mode != "off" and st.country_filter)
                    or st.hidden_alt_bands)

    def passes(self, ac, st) -> bool:
        if self.aircraft_class(ac) in st.hidden_classes:
            return False

        types = split_codes(st.type_filter) if st.type_mode != "off" else []
        if types:
            hit = any(fnmatch.fnmatchcase((ac.type or "").upper(), p) for p in types)
            if hit != (st.type_mode == "only"):
                return False

        operators = split_codes(st.operator_filter) if st.operator_mode != "off" else []
        if operators:
            m = AIRLINE_CALLSIGN_RE.match(ac.callsign or "")
            hit = bool(m) and any(fnmatch.fnmatchcase(ac.callsign[:3], p) for p in operators)
            if hit != (st.operator_mode == "only"):
                return False

        if st.country_mode != "off" and st.country_filter:
            hit = self.country(ac.hex) in st.country_filter
            if hit != (st.country_mode == "only"):
                return False

        if st.hidden_alt_bands:
            if ac.on_ground:
                return "low" not in st.hidden_alt_bands
            if ac.alt_ft is None:
                return False  # unknown altitude can't be placed in a block
            if altitude_band(ac.alt_ft) in st.hidden_alt_bands:
                return False
        return True


# --- colours, emergencies, watchlist, presets ------------------------------------

# Symbol colours when "colour by kind" is on (RGB). Chosen to stay distinct
# from each other and from the green grid/sweep on the dark background.
CLASS_COLORS = {
    "airliner": (255, 77, 77),
    "bizjet": (255, 165, 60),
    "ga": (80, 200, 255),
    "helicopter": (210, 120, 255),
    "military": (215, 200, 110),
    "other": (160, 168, 180),
}
SINGLE_COLOR = (255, 0, 0)  # everything red, as on the ESP32
WATCH_COLOR = (255, 214, 10)

EMERGENCY_SQUAWKS = {"7500": "HIJACK", "7600": "RADIO FAILURE", "7700": "EMERGENCY"}
EMERGENCY_STATUS = {
    "general": "EMERGENCY", "lifeguard": "MEDICAL", "minfuel": "MINIMUM FUEL",
    "nordo": "RADIO FAILURE", "unlawful": "UNLAWFUL INTERFERENCE", "downed": "DOWNED AIRCRAFT",
    "reserved": "EMERGENCY",
}


def emergency_label(ac) -> str:
    """'7700 EMERGENCY' etc., or "" if the aircraft isn't declaring one."""
    if ac.squawk in EMERGENCY_SQUAWKS:
        return f"{ac.squawk} {EMERGENCY_SQUAWKS[ac.squawk]}"
    if ac.emergency:
        return EMERGENCY_STATUS.get(ac.emergency, "EMERGENCY")
    return ""


def watch_patterns(text: str) -> list[str]:
    """Watchlist entries: split on commas, semicolons, spaces or new lines."""
    return [w for w in re.split(r"[\s,;]+", (text or "").upper()) if w]


def is_watched(ac, patterns: list[str]) -> bool:
    """Matches callsign, registration, ICAO address or type code."""
    if not patterns:
        return False
    keys = [k.upper() for k in (ac.callsign, ac.reg, ac.hex, ac.type) if k]
    return any(fnmatch.fnmatchcase(k, p) for p in patterns for k in keys)


# Presets: named sets of filter values. Built-in ones can't be deleted.
PRESET_FIELDS = ["hidden_classes", "type_mode", "type_filter", "operator_mode",
                 "operator_filter", "country_mode", "country_filter",
                 "hidden_alt_bands", "show_ground"]
_ALL = [c for c, _ in CLASSES]
_NONE = {"hidden_classes": [], "type_mode": "off", "type_filter": "",
         "operator_mode": "off", "operator_filter": "", "country_mode": "off",
         "country_filter": [], "hidden_alt_bands": [], "show_ground": False}
BUILTIN_PRESETS = {
    "Everything": dict(_NONE),
    "Airliners only": {**_NONE, "hidden_classes": [c for c in _ALL if c != "airliner"]},
    "GA & helicopters, 10,000 ft and below": {
        **_NONE, "hidden_classes": [c for c in _ALL if c not in ("ga", "helicopter")],
        "hidden_alt_bands": ["mid", "high"]},
    "Helicopters": {**_NONE, "hidden_classes": [c for c in _ALL if c != "helicopter"]},
    "Military": {**_NONE, "hidden_classes": [c for c in _ALL if c != "military"]},
}


def all_presets(st) -> dict:
    return {**BUILTIN_PRESETS, **st.filter_presets}


def current_filter_values(st) -> dict:
    return {f: getattr(st, f) for f in PRESET_FIELDS}


def matching_preset(st) -> str | None:
    """Name of the preset the current filters equal, if any."""
    now = current_filter_values(st)
    norm = lambda v: sorted(v) if isinstance(v, list) else v
    for name, values in all_presets(st).items():
        if all(norm(values.get(f, _NONE[f])) == norm(now[f]) for f in PRESET_FIELDS):
            return name
    return None


def preset_changes(st, name: str) -> dict:
    """Settings changes that apply preset `name` (empty if unknown)."""
    values = all_presets(st).get(name)
    if values is None:
        return {}
    return {f: values.get(f, _NONE[f]) for f in PRESET_FIELDS}
