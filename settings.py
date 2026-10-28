"""Settings stored in settings.json next to this file (the Pi's stand-in for
the ESP32's NVS + setup portal fields)."""

import json
import math
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

SETTINGS_PATH = Path(__file__).resolve().parent / "settings.json"

KM_PER_MILE = 1.609344
KM_PER_NM = 1.852
FT_PER_M = 1 / 0.3048

# Display units. Internally distances are km, speeds knots, altitudes feet.
DISTANCE_UNITS = {"km": ("km", 1.0), "mi": ("mi", 1 / KM_PER_MILE), "nm": ("nm", 1 / KM_PER_NM)}
SPEED_UNITS = {"kt": ("kt", 1.0), "kmh": ("km/h", KM_PER_NM), "mph": ("mph", KM_PER_NM / KM_PER_MILE)}
ALTITUDE_UNITS = {"ft": ("ft", 1.0), "m": ("m", 0.3048)}

# Range presets: the distance to the outer ring, as round numbers in each
# distance unit. (The ESP32 labelled ring 3 of 4 instead; here every ring is
# labelled, so the range is simply how far the scope reaches.) The largest stay
# within adsb.fi's 250 nm query radius, including the ~11% fetched beyond the
# outer ring for the edge dots.
RANGE_PRESETS = {
    "km": [5, 10, 15, 25, 50, 100, 150, 200, 300, 400],
    "mi": [2, 5, 10, 15, 25, 50, 75, 100, 150, 200, 250],
    "nm": [2, 5, 10, 20, 40, 60, 80, 100, 150, 200],
}
MAX_RANGE_PRESETS = max(len(v) for v in RANGE_PRESETS.values())


def ring_count(r: float) -> int:
    """How many rings divide range r into a round step (1, 2, 2.5 or 5 × 10^k;
    whole numbers preferred from 4 up)."""
    for n in (4, 5, 3, 2):
        step = r / n
        mant = step / 10 ** math.floor(math.log10(step))
        if any(abs(mant - m) < 1e-9 for m in (1, 2, 2.5, 5)) and (step == int(step) or r < 4):
            return n
    return 4


@dataclass
class Settings:
    # "manual" (lat/lon below), "gps_once" (fix at start-up, then fixed) or
    # "gps_live" (re-centre every gps_update_s). GPS fixes are written to lat/lon.
    location_source: str = "manual"
    lat: float = 52.3676
    lon: float = 4.9041
    center_airport: str = ""  # ICAO ident when centred on an airport (manual source)
    gps_update_s: float = 30.0
    range_index: int = 1  # index into RANGE_PRESETS[distance_unit]
    distance_unit: str = "km"  # km, mi or nm
    speed_unit: str = "kt"  # kt, kmh or mph
    altitude_unit: str = "ft"  # ft or m
    show_runways: bool = True
    runway_types: list = field(default_factory=lambda: ["L", "M", "S"])  # airports shown: L major, M regional, S small paved
    runway_centerlines: bool = True  # ATC-style extended centrelines with mile ticks
    show_airspace: bool = True  # US Class B/C/D outlines (FAA data)
    # SIDs/STARs: per airport, e.g. {"KPHX": "both", "KDVT": "star"}; procedure_mode
    # is an overall switch on top ("off", "sid", "star" or "both" = as chosen).
    procedure_airports: dict = field(default_factory=dict)
    procedure_mode: str = "both"
    show_ground: bool = False
    show_beyond_dots: bool = True  # rim dots for aircraft just outside the range
    # Filters (see filters.py). Classes: airliner, bizjet, ga, helicopter, military, other.
    hidden_classes: list = field(default_factory=list)
    type_mode: str = "off"  # "off", "only" (show only these) or "hide"
    type_filter: str = ""  # ICAO type codes, wildcards allowed: "B738, A32*, C172"
    operator_mode: str = "off"
    operator_filter: str = ""  # airline codes from the callsign: "AAL, SWA"
    country_mode: str = "off"
    country_filter: list = field(default_factory=list)  # country names
    hidden_alt_bands: list = field(default_factory=list)  # "low", "mid", "high" (filters.ALT_BANDS)
    sweep_enabled: bool = True
    color_by_kind: bool = False  # colour symbols by class (airliner, GA, ...)
    show_photos: bool = True  # aircraft photo on the browser display's card
    show_routes: bool = True  # an airline flight's route (from -> to) on the card
    highlight_emergencies: bool = True  # flash 7500/7600/7700 and emergency status
    # Watchlist: callsigns, registrations, ICAO hex addresses or type codes
    # (wildcards allowed). Matches are highlighted and shown despite filters.
    watchlist: str = ""
    watch_notice: bool = True  # banner when a watched aircraft is in range
    filter_presets: dict = field(default_factory=dict)  # your saved presets: name → filter values
    aircraft_symbol: str = "silhouette"  # "silhouette" or "triangle" (the ESP32 look)
    airline_logos: str = "all"  # "off", "panel" (side panel only) or "all" (panel + radar tags)
    sweep_period_s: float = 4.0  # one full turn
    sweep_trail_deg: float = 90.0  # length of the fading afterglow
    # "internet" (adsb.fi) or "sdr" (local receiver via readsb/dump1090)
    data_source: str = "internet"
    # "auto", or a path/URL to the decoder's aircraft.json
    sdr_location: str = "auto"
    fetch_interval_s: float = 5.0  # adsb.fi public limit is 1 req/s
    fps: int = 30
    web_port: int = 7700  # settings page; 0 = off

    def range_value(self) -> float:
        """The current range in the display unit (e.g. 25 for 25 mi)."""
        return self.range_presets()[self.range_index % len(self.range_presets())]

    @property
    def outer_km(self) -> float:
        return self.range_value() / self.distance(1.0)

    # --- units ---------------------------------------------------------------

    @property
    def distance_symbol(self) -> str:
        return DISTANCE_UNITS.get(self.distance_unit, DISTANCE_UNITS["km"])[0]

    @property
    def speed_symbol(self) -> str:
        return SPEED_UNITS.get(self.speed_unit, SPEED_UNITS["kt"])[0]

    @property
    def altitude_symbol(self) -> str:
        return ALTITUDE_UNITS.get(self.altitude_unit, ALTITUDE_UNITS["ft"])[0]

    def distance(self, km: float) -> float:
        return km * DISTANCE_UNITS.get(self.distance_unit, DISTANCE_UNITS["km"])[1]

    def speed(self, kt: float) -> float:
        return kt * SPEED_UNITS.get(self.speed_unit, SPEED_UNITS["kt"])[1]

    def altitude(self, ft: float) -> float:
        return ft * ALTITUDE_UNITS.get(self.altitude_unit, ALTITUDE_UNITS["ft"])[1]

    def range_label(self) -> str:
        return f"{self.range_value():g}{self.distance_symbol}"

    def rings(self) -> list[tuple[float, str]]:
        """Range rings as (fraction of the outer radius, label), at a round
        step: 25 mi → 5/10/15/20/25, 50 km → 10…50, 2 mi → 0.5/1/1.5/2."""
        r = self.range_value()
        n = ring_count(r)
        return [(i / n, f"{r * i / n:g}{self.distance_symbol}") for i in range(1, n + 1)]

    def format_distance(self, km: float, unit: bool = True) -> str:
        text = f"{self.distance(km):.1f}"
        return f"{text} {self.distance_symbol}" if unit else text

    def format_speed(self, kt: float | None, unit: bool = True) -> str:
        if kt is None:
            return "—"
        text = f"{self.speed(kt):.0f}"
        return f"{text} {self.speed_symbol}" if unit else text

    def format_altitude(self, ft: int | None, on_ground: bool, unit: bool = True) -> str:
        if on_ground:
            return "GND"
        if ft is None:
            return "—"
        text = f"{self.altitude(ft):,.0f}"
        return f"{text} {self.altitude_symbol}" if unit else text

    def format_vertical_rate(self, fpm: int) -> str:
        """ft/min with feet; m/s with metres (the usual pairing)."""
        if self.altitude_unit == "m":
            return f"{abs(fpm) * 0.00508:.1f} m/s"
        return f"{abs(fpm):,} ft/min"

    def next_distance_unit(self) -> None:
        units = list(DISTANCE_UNITS)
        self.set_distance_unit(units[(units.index(self.distance_unit) + 1) % len(units)
                                     if self.distance_unit in units else 0])

    def range_presets(self) -> list:
        """Ring 3 distances for the current unit, in that unit."""
        return RANGE_PRESETS.get(self.distance_unit, RANGE_PRESETS["km"])

    def next_range(self) -> None:
        self.range_index = (self.range_index + 1) % len(self.range_presets())

    def prev_range(self) -> None:
        self.range_index = (self.range_index - 1) % len(self.range_presets())

    def set_distance_unit(self, unit: str) -> None:
        """Switch unit and move to that unit's preset nearest the current range,
        so the view stays about the same (e.g. 50 km → 25 mi)."""
        km = self.outer_km
        self.distance_unit = unit
        self.range_index = min(range(len(self.range_presets())),
                               key=lambda i: abs(self.range_presets()[i] / self.distance(1.0) - km))

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        try:
            raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            s.save()  # write defaults so there's a file to edit
            return s
        except (OSError, ValueError) as exc:
            print(f"settings: ignoring unreadable {SETTINGS_PATH}: {exc}")
            return s
        # Older settings files.
        if "runway_detail" in raw and "runway_types" not in raw:
            raw["runway_types"] = list({"major": "L", "regional": "LM"}.get(raw["runway_detail"], "LMS"))
        if isinstance(raw.get("procedure_airports"), str):  # was "KPHX, KDVT" + a global mode
            mode = raw.get("procedure_mode", "off")
            names = [a for a in raw["procedure_airports"].replace(",", " ").upper().split() if a]
            raw["procedure_airports"] = {a: (mode if mode != "off" else "both") for a in names} \
                if mode != "off" else {}
            raw["procedure_mode"] = "both"  # the overall switch: show what's ticked per airport
        if "use_miles" in raw and "distance_unit" not in raw:
            s.distance_unit = "mi" if raw["use_miles"] else "km"
        for f in fields(cls):
            if f.name in raw:
                setattr(s, f.name, type(getattr(s, f.name))(raw[f.name]))
        if s.distance_unit not in RANGE_PRESETS:
            s.distance_unit = "km"
        if "range_unit" not in raw:  # file from before per-unit presets: keep about the same range
            old_km = [5.0, 10.0, 15.0, 25.0, 50.0][s.range_index % 5]
            unit, s.distance_unit = s.distance_unit, "km"
            s.range_index = [5, 10, 15, 25, 50, 100].index(old_km)
            s.set_distance_unit(unit)
        elif raw.get("range_unit") == "per-unit":  # presets were ring 3; now the outer ring
            unit = s.distance_unit
            outer_km = RANGE_PRESETS[unit][s.range_index % len(RANGE_PRESETS[unit])] \
                / DISTANCE_UNITS[unit][1] * 4 / 3
            s.range_index = min(range(len(RANGE_PRESETS[unit])), key=lambda i: abs(
                RANGE_PRESETS[unit][i] / DISTANCE_UNITS[unit][1] - outer_km))
        s.range_index %= len(s.range_presets())
        return s

    def save(self) -> None:
        try:
            data = asdict(self)
            data["range_unit"] = "outer"  # range_index is per distance unit, outer-ring presets
            SETTINGS_PATH.write_text(json.dumps(data, indent=2) + "\n",
                                     encoding="utf-8")
        except OSError as exc:
            print(f"settings: could not save: {exc}")
