#!/usr/bin/env python3
"""SkyScope: a live ADS-B radar scope for a Raspberry Pi + HDMI screen, or a browser.

Grew out of the ESP32-Plane-Radar firmware's radar UI, ported to pygame: radar scope on the left (full
screen height), info panel on the right, rotating sweep with a fading trail.

    python3 skyscope.py                       # fullscreen at the display's resolution
    python3 skyscope.py --window 1280x720     # windowed, for testing on a desktop

Keys: R/Space/→ next range, ← previous range, U km/mi, W runways, G ground
traffic, S sweep on/off, A aircraft symbol style, L airline logos (off/panel/all),
D dots for aircraft beyond the range, F fullscreen, Q/Esc quit.
"""

import argparse
import io
import threading
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import pygame
import pygame.gfxdraw

import symbols
import airports
from overlays import Overlays, centroid
from adsb import AdsbFeed, Aircraft
from filters import (ALT_BANDS, CLASS_COLORS, CLASS_LABELS, CLASSES, SINGLE_COLOR, WATCH_COLOR,
                     AircraftFilter, all_presets, emergency_label, is_watched, matching_preset,
                     watch_patterns)
from gps import GpsReader
from logos import LogoStore, airline_code
from photos import fetch_image
from web import PHOTOS, SettingsServer, lan_address
from settings import Settings

HERE = Path(__file__).resolve().parent

KM_PER_DEG = 111.0
DEG = math.pi / 180.0

# Palette — same targets as include/ui/radar_theme.h.
BG = (4, 10, 28)
GRID = (16, 100, 32)
RING_LABEL = (40, 170, 70)  # a little brighter than the grid so ring distances read
LABEL = (255, 255, 255)
AIRCRAFT = (255, 0, 0)
TRACK = (255, 0, 255)
TAG_TYPE = (255, 200, 0)
TAG_ALT = (90, 200, 255)
# ATC-style video map: light grey-blue runways, dim extended centrelines.
RUNWAY = (165, 185, 205)
CENTERLINE = (70, 110, 135)
RUNWAY_LABEL = (110, 210, 230)
RUNWAY_NUMBER = (120, 140, 165)
# Airspace (chart convention: B solid blue, C solid magenta, D dashed blue) and
# procedure routes (STAR amber, SID teal), dimmed to sit under the traffic.
AIRSPACE_COLORS = {"B": (70, 115, 210), "C": (165, 95, 185), "D": (70, 115, 210)}
STAR_COLOR = (210, 150, 55)
SID_COLOR = (55, 180, 180)
SWEEP = (70, 255, 120)
PANEL_BG = (7, 16, 40)
PANEL_DIM = (120, 140, 170)
HIGHLIGHT = (255, 200, 0)
ERROR = (255, 90, 90)
EMERGENCY_BG = (120, 10, 10)
WATCH_BG = (90, 70, 0)

# Speed vector: the distance flown in one minute at the scope's true scale,
# kept between a readable minimum and a cap (like an ATC prediction line).
# Lengths in px at 1080p.
TRACK_HORIZON_S = 60.0
TRACK_MIN_PX = 8
TRACK_MAX_PX = 70

# GPS: ignore position changes smaller than this (receiver jitter), and treat
# a fix older than GPS_STALE_S as lost.
GPS_MIN_MOVE_KM = 0.05
GPS_STALE_S = 10.0


class Layout:
    """All pixel geometry, derived from the window size."""

    def __init__(self, w: int, h: int):
        self.w = w
        self.h = h
        self.s = h / 1080.0  # scale factor vs. a 1080p reference
        s = self.s

        # The panel needs ~0.5×H of width to be useful; narrower screens get
        # the radar alone, centred.
        self.has_panel = w - h >= 0.5 * h
        self.radar_w = h if self.has_panel else w
        self.cx = self.radar_w // 2
        self.cy = h // 2

        self.rim_r = int(h / 2 - 10 * s)  # beyond-ring dots and cardinals sit out here
        self.grid_r = int(self.rim_r - 52 * s)  # outer range ring
        self.dot_r = self.grid_r + int(16 * s)
        self.cardinal_r = self.grid_r + int(36 * s)

        self.stroke = max(1, round(2 * s))
        self.nose = round(16 * s)
        self.tail = round(6 * s)
        self.tail_half = round(9 * s)
        self.dot_size = max(3, round(7 * s))

        self.font_cardinal = max(12, round(40 * s))
        self.font_scale = max(10, round(24 * s))
        self.font_tag = max(10, round(26 * s))
        self.font_runway = max(10, round(26 * s))

        self.panel_x = self.radar_w
        self.panel_w = w - self.panel_x
        self.pad = round(36 * s)


class TextCache:
    """pygame text rendering is slow; cache surfaces by (size, text, colour)."""

    def __init__(self):
        self._fonts: dict[int, pygame.font.Font] = {}
        self._cache: dict[tuple, pygame.Surface] = {}

    def font(self, size: int) -> pygame.font.Font:
        if size not in self._fonts:
            self._fonts[size] = pygame.font.Font(None, size)  # bundled FreeSansBold
        return self._fonts[size]

    def render(self, text: str, size: int, color) -> pygame.Surface:
        key = (size, text, color)
        surf = self._cache.get(key)
        if surf is None:
            if len(self._cache) > 3000:
                self._cache.clear()
            surf = self.font(size).render(text, True, color)
            self._cache[key] = surf
        return surf

    def draw(self, target, text, size, color, pos, anchor="topleft"):
        surf = self.render(text, size, color)
        rect = surf.get_rect(**{anchor: (round(pos[0]), round(pos[1]))})
        target.blit(surf, rect)
        return rect


def clip_segment_to_circle(p0, p1, c, r):
    """Clip segment p0→p1 to the disc (c, r). Returns (q0, q1) or None."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    fx, fy = p0[0] - c[0], p0[1] - c[1]
    a = dx * dx + dy * dy
    if a == 0:
        return (p0, p1) if fx * fx + fy * fy <= r * r else None
    b = 2 * (fx * dx + fy * dy)
    cc = fx * fx + fy * fy - r * r
    disc = b * b - 4 * a * cc
    if disc < 0:
        return None
    root = math.sqrt(disc)
    t0 = max(0.0, (-b - root) / (2 * a))
    t1 = min(1.0, (-b + root) / (2 * a))
    if t0 >= t1:
        return None
    return ((p0[0] + dx * t0, p0[1] + dy * t0), (p0[0] + dx * t1, p0[1] + dy * t1))


def aa_wide_line(surf, color, p0, p1, width):
    """Anti-aliased line of a given pixel width (pygame's wide lines are jagged)."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dy)
    if length < 0.5:
        return
    if width <= 4.5:
        # Thin lines: overlapping 1 px anti-aliased strokes. A filled polygon
        # this narrow comes out stair-stepped.
        n = max(1, round(width))
        ux, uy = -dy / length, dx / length
        for i in range(n):
            off = i - (n - 1) / 2
            pygame.draw.aaline(surf, color, (p0[0] + ux * off, p0[1] + uy * off),
                               (p1[0] + ux * off, p1[1] + uy * off))
        return
    nx, ny = -dy / length * width / 2, dx / length * width / 2
    pts = [(p0[0] + nx, p0[1] + ny), (p1[0] + nx, p1[1] + ny),
           (p1[0] - nx, p1[1] - ny), (p0[0] - nx, p0[1] - ny)]
    ipts = [(round(x), round(y)) for x, y in pts]
    pygame.gfxdraw.aapolygon(surf, ipts, color)
    pygame.gfxdraw.filled_polygon(surf, ipts, color)


def aa_ring(surf, color, c, r, width):
    for i in range(width):
        pygame.gfxdraw.aacircle(surf, c[0], c[1], r - i, color)


def aa_disc(surf, color, c, r):
    pygame.gfxdraw.aacircle(surf, round(c[0]), round(c[1]), r, color)
    pygame.gfxdraw.filled_circle(surf, round(c[0]), round(c[1]), r, color)


class SkyScope:
    def __init__(self, screen: pygame.Surface, settings: Settings, feed: AdsbFeed):
        self.screen = screen
        self.settings = settings
        self.feed = feed
        self.text = TextCache()
        self.logos = LogoStore()
        self.filter = AircraftFilter()
        self.counts = (0, 0)  # (shown, total) after filtering, for the panel
        self.styles: dict[int, dict] = {}  # id(aircraft) → style(), this frame
        self._watch: list[str] = []  # watchlist patterns, refreshed each frame
        self.web_url = ""  # shown in the panel footer when the settings page is up
        self.gps = GpsReader()
        self._gps_pending = True  # apply the next fix regardless of interval/distance
        self._gps_last_check = 0.0
        if settings.location_source != "manual":
            self.gps.start()
        self.airports = airports.load_map()
        self.airport_index = airports.AirportIndex()
        self.overlays = Overlays()
        # Aircraft photo for the card (shares the web page's lookup and cache).
        self._photo_key = None  # aircraft the photo is for
        self._photo = None  # (pygame Surface or None, credit) once fetched
        self._photo_images: dict[str, pygame.Surface] = {}  # src → full image, in memory
        self._photo_thumb = (None, None, None)  # (image id, size, scaled thumbnail)
        self.static: pygame.Surface | None = None
        self.static_obstacles: list[pygame.Rect] = []  # fixed labels tags must avoid
        self.layout = Layout(*screen.get_size())
        self.sweep_t0 = time.monotonic()
        self.update_query()

    # --- geometry -----------------------------------------------------------

    def offset_km(self, lat: float, lon: float) -> tuple[float, float]:
        """East/north offset from the radar centre. Longitude degrees shrink
        toward the poles, so scale by cos(centre latitude)."""
        s = self.settings
        dx = (lon - s.lon) * KM_PER_DEG * math.cos(s.lat * DEG)
        dy = (lat - s.lat) * KM_PER_DEG
        return dx, dy

    def px_per_km(self) -> float:
        return self.layout.grid_r / self.settings.outer_km

    def to_screen(self, lat: float, lon: float) -> tuple[float, float]:
        dx, dy = self.offset_km(lat, lon)
        k = self.px_per_km()
        return self.layout.cx + dx * k, self.layout.cy - dy * k

    def fetch_radius_km(self) -> float:
        """Fetch out to the rim, so beyond-ring dots have data."""
        return self.settings.outer_km * self.layout.rim_r / self.layout.grid_r

    def gps_fix(self):
        fix = self.gps.latest()
        if fix is None or time.monotonic() - fix.when > GPS_STALE_S:
            return None
        return fix

    def update_location(self) -> None:
        """Move the radar centre to the GPS position, per location_source:
        gps_once takes one fix (at start-up, or on "Read GPS now"); gps_live
        re-centres every gps_update_s seconds once it has moved past jitter."""
        st = self.settings
        if st.location_source == "manual":
            return
        fix = self.gps_fix()
        if fix is None:
            return
        now = time.monotonic()
        if not self._gps_pending:
            if st.location_source != "gps_live" or now - self._gps_last_check < st.gps_update_s:
                return
            self._gps_last_check = now
            if math.hypot(*self.offset_km(fix.lat, fix.lon)) < GPS_MIN_MOVE_KM:
                return
        self._gps_pending = False
        self._gps_last_check = now
        st.lat, st.lon = round(fix.lat, 6), round(fix.lon, 6)
        print(f"Location from GPS: {st.lat:.5f}, {st.lon:.5f}")
        self.invalidate()

    def centre_airport(self) -> dict | None:
        st = self.settings
        if st.location_source != "manual" or not st.center_airport:
            return None
        return self.airport_index.get(st.center_airport)

    def location_text(self) -> str:
        """Coordinates, or the airport the scope is centred on."""
        ap = self.centre_airport()
        if ap:
            return f"{ap['ident']}  ·  {ap['name']}"
        return f"{self.settings.lat:.4f}, {self.settings.lon:.4f}"

    def location_label(self) -> tuple[str, tuple]:
        """Short location-source note for the panel, and its colour."""
        src = self.settings.location_source
        if src == "manual":
            return "", PANEL_DIM
        if self.gps_fix() is None:
            return "GPS: no fix, last known position", ERROR
        return ("GPS live" if src == "gps_live" else "GPS"), SWEEP

    def location_status(self) -> str:
        """Longer status for the settings page."""
        if self.settings.location_source == "manual":
            return "Using the latitude/longitude entered above."
        return self.gps.status()

    def web_statuses(self) -> dict[str, str]:
        """Status lines for the settings page, by section."""
        return {"Location": self.location_status(), "Aircraft data": self.feed.sdr_status()}

    def update_query(self) -> None:
        s = self.settings
        self.feed.set_query(s.lat, s.lon, self.fetch_radius_km())

    def extrapolate(self, ac: Aircraft, base_time: float) -> tuple[float, float]:
        """Dead-reckon along the ground track since the fix was measured."""
        if base_time == 0 or ac.gs_knots <= 0:
            return ac.lat, ac.lon
        elapsed_h = (time.monotonic() - base_time + ac.pos_age_s) / 3600.0
        dist_km = ac.gs_knots * 1.852 * elapsed_h
        rad = ac.track_deg * DEG
        lat = ac.lat + dist_km * math.cos(rad) / KM_PER_DEG
        lon = ac.lon + dist_km * math.sin(rad) / (KM_PER_DEG * math.cos(ac.lat * DEG))
        return lat, lon

    # --- static layer (redrawn only when range/settings/size change) --------

    def invalidate(self) -> None:
        self.static = None
        self.update_query()
        self.settings.save()

    def build_static(self) -> pygame.Surface:
        L = self.layout
        # Draw on a 24-bit surface: some displays (macOS) have an alpha channel,
        # and pygame copies anti-aliased text pixels outright onto alpha-0
        # targets instead of blending. Converted once at the end for fast blits.
        surf = pygame.Surface((L.w, L.h), 0, 24)
        surf.fill(BG)
        c = (L.cx, L.cy)

        rings = self.settings.rings()
        for frac, _ in rings:
            aa_ring(surf, GRID, c, round(L.grid_r * frac), L.stroke)
        aa_wide_line(surf, GRID, (L.cx, L.cy - L.grid_r), (L.cx, L.cy + L.grid_r), L.stroke)
        aa_wide_line(surf, GRID, (L.cx - L.grid_r, L.cy), (L.cx + L.grid_r, L.cy), L.stroke)
        # Faint 30° bearing ticks between the cardinals.
        for deg in range(0, 360, 10):
            rad = deg * DEG
            inner = L.grid_r - (12 if deg % 30 == 0 else 6) * L.s
            p0 = (L.cx + math.sin(rad) * inner, L.cy - math.cos(rad) * inner)
            p1 = (L.cx + math.sin(rad) * L.grid_r, L.cy - math.cos(rad) * L.grid_r)
            aa_wide_line(surf, GRID, p0, p1, L.stroke)

        ov = self.overlay_features()
        self.draw_overlays(surf, ov)
        feats = self.draw_runways(surf) if self.settings.show_runways else None

        aa_disc(surf, LABEL, c, max(2, round(4 * L.s)))

        self.static_obstacles = []
        for text, deg in (("N", 0), ("E", 90), ("S", 180), ("W", 270)):
            rad = deg * DEG
            pos = (L.cx + math.sin(rad) * L.cardinal_r, L.cy - math.cos(rad) * L.cardinal_r)
            rect = self.text.draw(surf, text, L.font_cardinal, LABEL, pos, "center")
            self.static_obstacles.append(rect.inflate(round(8 * L.s), round(4 * L.s)))

        # Each ring's distance, just inside the ring above the east spoke, with
        # a background knockout so lines don't run through the text.
        for frac, label in rings:
            img = self.text.render(label, L.font_scale, RING_LABEL)
            rect = img.get_rect(bottomright=(L.cx + round(L.grid_r * frac) - round(6 * L.s),
                                             L.cy - round(5 * L.s)))
            surf.fill(BG, rect.inflate(round(8 * L.s), round(2 * L.s)))
            surf.blit(img, rect)
            self.static_obstacles.append(rect.inflate(round(8 * L.s), round(4 * L.s)))

        # Map labels avoid each other and the fixed labels; aircraft labels only
        # avoid the fixed ones (traffic is drawn over the map).
        self.map_labels = list(self.static_obstacles)
        if feats:
            self.draw_airport_codes(surf, feats)
        self.draw_overlay_labels(surf, ov)

        if L.has_panel:
            surf.fill(PANEL_BG, (L.panel_x, 0, L.panel_w, L.h))
            pygame.draw.line(surf, GRID, (L.panel_x, 0), (L.panel_x, L.h), L.stroke)
        return surf.convert()

    def map_features(self) -> dict:
        st = self.settings
        return airports.map_features(self.airports, st.lat, st.lon, self.fetch_radius_km(),
                                     st.outer_km, st.runway_types, st.runway_centerlines)

    def procedure_table(self) -> list[dict]:
        """Airports offered on the settings page's SID/STAR list: those with
        published procedures within reach of the scope, plus any already
        chosen elsewhere. Each with its current choice."""
        st = self.settings
        rows = self.overlays.airports_near(st.lat, st.lon, self.fetch_radius_km() + 40, self.airport_index)
        listed = {r["ident"] for r in rows}
        for ident in st.procedure_airports:
            if ident not in listed:
                ap = self.airport_index.get(ident) or {"name": "", "type": ""}
                sids, stars = self.overlays.counts(ident)
                rows.insert(0, {"ident": ident, "name": ap["name"], "type": ap["type"],
                                "dist_km": None, "sids": sids, "stars": stars})
        for r in rows:
            r["choice"] = st.procedure_airports.get(r["ident"], "")
        return rows

    def overlay_features(self) -> dict:
        st = self.settings
        reach = self.fetch_radius_km() + 40
        return {
            "airspace": self.overlays.airspace_near(st.lat, st.lon, reach) if st.show_airspace else [],
            "procedures": self.overlays.procedures_for(st.procedure_airports, st.procedure_mode),
        }

    def draw_polyline(self, surf, color, pts, width=1, dash=0.0):
        """Screen polyline clipped to the outer ring; dash > 0 draws it dashed."""
        L = self.layout
        c, R = (L.cx, L.cy), L.grid_r
        for p0, p1 in zip(pts, pts[1:]):
            seg = clip_segment_to_circle(p0, p1, c, R)
            if not seg:
                continue
            if not dash:
                aa_wide_line(surf, color, seg[0], seg[1], width)
                continue
            (x0, y0), (x1, y1) = seg
            length = math.hypot(x1 - x0, y1 - y0)
            n = max(1, int(length / (2 * dash)))
            for i in range(n):
                a, b = (2 * i) / (2 * n), (2 * i + 1) / (2 * n)
                aa_wide_line(surf, color, (x0 + (x1 - x0) * a, y0 + (y1 - y0) * a),
                             (x0 + (x1 - x0) * b, y0 + (y1 - y0) * b), width)

    def draw_overlays(self, surf: pygame.Surface, ov: dict) -> None:
        """Airspace outlines and procedure routes (lines only; labels later)."""
        L = self.layout
        for shape in ov["airspace"]:
            color = AIRSPACE_COLORS[shape["class"]]
            for ring in shape["rings"]:
                pts = [self.to_screen(lat, lon) for lon, lat in ring]
                self.draw_polyline(surf, color, pts + pts[:1], max(1.0, 1.5 * L.s),
                                   dash=6 * L.s if shape["class"] == "D" else 0)
        for proc in ov["procedures"]:
            color = STAR_COLOR if proc["kind"] == "STAR" else SID_COLOR
            for line in proc["lines"]:
                self.draw_polyline(surf, color, [self.to_screen(p[0], p[1]) for p in line],
                                   max(1.0, 1.5 * L.s), dash=5 * L.s)

    def place_label(self, surf, text, size, color, pos, anchor="center") -> bool:
        """Draw a static label unless it would overlap one already placed."""
        img = self.text.render(text, size, color)
        rect = img.get_rect(**{anchor: (round(pos[0]), round(pos[1]))})
        L = self.layout
        if math.hypot(rect.centerx - L.cx, rect.centery - L.cy) > L.grid_r - 8 * L.s:
            return False
        box = rect.inflate(round(6 * L.s), round(2 * L.s))
        if box.collidelist(self.map_labels) != -1:
            return False
        self.map_labels.append(box)
        surf.blit(img, rect)
        return True

    def draw_overlay_labels(self, surf: pygame.Surface, ov: dict) -> None:
        """Shelf altitudes (ceiling/floor, hundreds of ft), fix names and
        procedure names, each only where it fits."""
        L, st = self.layout, self.settings
        small = max(10, round(18 * L.s))
        for shape in ov["airspace"]:
            limit = 80 if shape["class"] in "BC" else 40  # km of range up to which shelves are labelled
            if st.outer_km > limit or not shape["rings"]:
                continue
            lon, lat, _ = max((centroid(r) for r in shape["rings"]), key=lambda c: c[2])
            self.place_label(surf, f"{shape['ceiling']}/{shape['floor']}", small,
                             AIRSPACE_COLORS[shape["class"]], self.to_screen(lat, lon))
        if not ov["procedures"]:
            return
        if st.outer_km <= 100:  # fix names, once each
            seen = set()
            for proc in ov["procedures"]:
                color = STAR_COLOR if proc["kind"] == "STAR" else SID_COLOR
                for line in proc["lines"]:
                    for lat, lon, fix in line:
                        if fix in seen or fix.startswith("RW"):
                            continue
                        seen.add(fix)
                        x, y = self.to_screen(lat, lon)
                        if math.hypot(x - L.cx, y - L.cy) > L.grid_r:
                            continue
                        pygame.gfxdraw.aatrigon(surf, round(x), round(y - 4 * L.s), round(x - 3.5 * L.s),
                                                round(y + 2.5 * L.s), round(x + 3.5 * L.s), round(y + 2.5 * L.s), color)
                        self.place_label(surf, fix, small, color, (x + 6 * L.s, y), "midleft")
        for proc in ov["procedures"]:  # name at the route's last on-scope fix
            color = STAR_COLOR if proc["kind"] == "STAR" else SID_COLOR
            longest = max(proc["lines"], key=len)
            for lat, lon, _ in reversed(longest):
                x, y = self.to_screen(lat, lon)
                if math.hypot(x - L.cx, y - L.cy) < L.grid_r - 30 * L.s:
                    self.place_label(surf, proc["name"], small + 2, color, (x, y + 16 * L.s), "midtop")
                    break

    def draw_runways(self, surf: pygame.Surface) -> dict:
        """Runways as on an ATC video map: true length (and width, once it's
        wider than 2 px), 10 nm extended centrelines with a tick each mile and
        a longer one each 5, runway numbers when zoomed in, airport codes."""
        L = self.layout
        c, R = (L.cx, L.cy), L.grid_r
        k = self.px_per_km()
        feats = self.map_features()
        nm_px = 1.852 * k
        tick = max(2.0, 4 * L.s)

        for rw in feats["runways"]:
            a = self.to_screen(rw["ends"][0], rw["ends"][1])
            b = self.to_screen(rw["ends"][2], rw["ends"][3])
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            if length < 0.5:
                continue
            ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length  # le → he
            if rw["centerline"]:
                for end, sx, sy in ((a, -ux, -uy), (b, ux, uy)):  # outward from each threshold
                    far = (end[0] + sx * nm_px * feats["centerline_nm"], end[1] + sy * nm_px * feats["centerline_nm"])
                    seg = clip_segment_to_circle(end, far, c, R)
                    if seg:
                        aa_wide_line(surf, CENTERLINE, seg[0], seg[1], 1)
                    if nm_px >= 6:  # ticks only when miles are far enough apart to read
                        for n in range(1, feats["centerline_nm"] + 1):
                            px, py = end[0] + sx * nm_px * n, end[1] + sy * nm_px * n
                            if math.hypot(px - L.cx, py - L.cy) > R:
                                continue
                            h = tick * (2 if n % 5 == 0 else 1)
                            aa_wide_line(surf, CENTERLINE, (px - uy * h, py + ux * h), (px + uy * h, py - ux * h), 1)
            seg = clip_segment_to_circle(a, b, c, R)
            if seg:
                width = max(2.0, rw["width_ft"] * 0.0003048 * k)
                aa_wide_line(surf, RUNWAY, seg[0], seg[1], width)
            if length > 70 * L.s:  # runway numbers just beyond each threshold
                for ident, end, sx, sy in ((rw["le"], a, -ux, -uy), (rw["he"], b, ux, uy)):
                    pos = (end[0] + sx * 14 * L.s, end[1] + sy * 14 * L.s)
                    if ident and math.hypot(pos[0] - L.cx, pos[1] - L.cy) < R - 10 * L.s:
                        self.text.draw(surf, ident, max(10, round(18 * L.s)), RUNWAY_NUMBER, pos, "center")

        return feats

    def draw_airport_codes(self, surf: pygame.Surface, feats: dict) -> None:
        """Airport codes: bigger airports first; one that would overlap another
        (or a ring label) is left off. The centre airport is named in the panel."""
        L, R = self.layout, self.layout.grid_r
        for ap in sorted((a for a in feats["airports"] if a["label"]), key=lambda a: "LMS".index(a["type"])):
            x, y = self.to_screen(ap["lat"], ap["lon"])
            dx, dy = x - L.cx, y - L.cy
            d = math.hypot(dx, dy)
            if d > R + 20 * L.s or d < 12 * L.s:
                continue  # off the scope, or the centre airport
            if d > R:
                x, y = L.cx + dx / d * R, L.cy + dy / d * R
            x, y = x + dx / d * 22 * L.s, y + dy / d * 22 * L.s  # beside the field, away from the centre
            img = self.text.render(ap["ident"], L.font_runway, RUNWAY_LABEL)
            rect = img.get_rect(center=(round(x), round(y)))
            if rect.inflate(round(6 * L.s), 0).collidelist(self.map_labels) != -1:
                continue
            self.map_labels.append(rect.inflate(round(6 * L.s), 0))
            surf.blit(img, rect)

    # --- per-frame drawing --------------------------------------------------

    def sweep_angle(self) -> float:
        period = max(0.5, self.settings.sweep_period_s)
        return ((time.monotonic() - self.sweep_t0) / period * 360.0) % 360.0

    def draw_sweep(self) -> None:
        """Rotating beam with a fading wedge of afterglow behind it."""
        L = self.layout
        r = L.grid_r - L.stroke
        head = self.sweep_angle()
        trail = max(5.0, self.settings.sweep_trail_deg)
        steps = max(8, int(trail / 1.5))
        step = trail / steps

        # Work in a bounding box around the wedge, not the whole screen —
        # alpha blits are the expensive part on a Pi.
        pts_all = [(L.cx, L.cy)]
        arc = []
        for i in range(steps + 1):
            rad = (head - i * step) * DEG
            p = (L.cx + math.sin(rad) * r, L.cy - math.cos(rad) * r)
            arc.append(p)
            pts_all.append(p)
        # Include any compass extreme the arc sweeps past.
        for deg in (0, 90, 180, 270):
            if (head - deg) % 360 <= trail:
                pts_all.append((L.cx + math.sin(deg * DEG) * r, L.cy - math.cos(deg * DEG) * r))
        x0 = int(min(p[0] for p in pts_all)) - 2
        y0 = int(min(p[1] for p in pts_all)) - 2
        x1 = int(max(p[0] for p in pts_all)) + 3
        y1 = int(max(p[1] for p in pts_all)) + 3
        layer = pygame.Surface((x1 - x0, y1 - y0), pygame.SRCALPHA)
        cx, cy = L.cx - x0, L.cy - y0

        for i in range(steps):
            fade = (1.0 - i / steps) ** 1.8
            alpha = int(110 * fade)
            if alpha <= 0:
                break
            a, b = arc[i], arc[i + 1]
            pygame.draw.polygon(layer, (*SWEEP, alpha),
                                [(cx, cy), (a[0] - x0, a[1] - y0), (b[0] - x0, b[1] - y0)])

        tip = (arc[0][0] - x0, arc[0][1] - y0)
        aa_wide_line(layer, (*SWEEP, 90), (cx, cy), tip, max(3, round(8 * L.s)))
        aa_wide_line(layer, (200, 255, 210, 255), (cx, cy), tip, max(2, round(3 * L.s)))
        self.screen.blit(layer, (x0, y0))

    def symbol_kind(self, ac: Aircraft) -> str | None:
        """Silhouette class, or None for the ESP32-style triangle."""
        if self.settings.aircraft_symbol != "silhouette":
            return None
        return symbols.classify(ac.category, ac.type)

    def symbol_radius(self, kind: str | None) -> float:
        """Rough radius of the drawn symbol, for spacing rings and tags."""
        L = self.layout
        if kind is None:
            return L.nose
        return symbols.shape_length_px(kind, L.s) / 2

    def style(self, ac: Aircraft) -> dict:
        """Colour and alert state for one aircraft this frame."""
        st = self.settings
        cls = self.filter.aircraft_class(ac)
        color = CLASS_COLORS[cls] if st.color_by_kind else SINGLE_COLOR
        emergency = emergency_label(ac) if st.highlight_emergencies else ""
        if emergency and int(time.monotonic() * 2) % 2:
            color = (255, 255, 255)  # flash red/white twice a second
        elif emergency:
            color = (255, 30, 30)
        return {"cls": cls, "color": color, "emergency": emergency,
                "watched": is_watched(ac, self._watch)}

    def draw_symbol(self, x, y, ac: Aircraft, kind: str | None, color=AIRCRAFT):
        """Draws the aircraft; returns its nose point (where the speed vector starts)."""
        L = self.layout
        if kind is None:
            return self.draw_aircraft_symbol(x, y, ac.nose_deg, color)
        symbols.draw_silhouette(self.screen, kind, x, y, ac.nose_deg, L.s, color)
        nose = symbols.nose_offset_px(kind, L.s)
        rad = ac.nose_deg * DEG
        return x + math.sin(rad) * nose, y - math.cos(rad) * nose

    def draw_aircraft_symbol(self, x, y, nose_deg, color=AIRCRAFT):
        L = self.layout
        rad = nose_deg * DEG
        sh, ch = math.sin(rad), math.cos(rad)
        tip = (x + sh * L.nose, y - ch * L.nose)
        bx, by = x - sh * L.tail, y + ch * L.tail
        wx, wy = ch * L.tail_half, sh * L.tail_half
        pts = [(round(tip[0]), round(tip[1])), (round(bx + wx), round(by + wy)),
               (round(bx - wx), round(by - wy))]
        pygame.gfxdraw.aapolygon(self.screen, pts, color)
        pygame.gfxdraw.filled_polygon(self.screen, pts, color)
        return tip

    def draw_speed_vector(self, tip, ac: Aircraft, color=TRACK):
        L = self.layout
        if ac.gs_knots <= 0:
            return
        km = ac.gs_knots * 1.852 * TRACK_HORIZON_S / 3600.0
        length = min(TRACK_MAX_PX, max(TRACK_MIN_PX, km * self.px_per_km() / L.s)) * L.s
        rad = ac.track_deg * DEG
        end = (tip[0] + math.sin(rad) * length, tip[1] - math.cos(rad) * length)
        seg = clip_segment_to_circle(tip, end, (L.cx, L.cy), L.grid_r)
        if seg:
            aa_wide_line(self.screen, color, seg[0], seg[1], L.stroke)

    def draw_tag(self, x, y, ac: Aircraft, symbol_r: float, placed: list, sty: dict) -> bool:
        """Label an aircraft where it doesn't overlap labels already in `placed`.
        Tries toward the centre first, then the far side, above and below; if
        none fit, the aircraft is left unlabelled (it's still in the table).
        Returns True if a label was drawn."""
        L, st, t = self.layout, self.settings, self.text
        lines = [(ac.callsign, WATCH_COLOR if sty["watched"] else LABEL), (ac.type, TAG_TYPE),
                 (st.format_altitude(ac.alt_ft, ac.on_ground), TAG_ALT)]
        if sty["emergency"]:
            lines.insert(0, (sty["emergency"], ERROR))
        lines = [(text, color) for text, color in lines if text and text != "—"]
        size = L.font_tag
        line_h = t.font(size).get_linesize()
        tile = None
        if st.airline_logos == "all":
            tile = self.logos.tile(ac.callsign, min(2, len(lines)) * line_h - round(4 * L.s))
        logo_w = tile.get_width() + round(6 * L.s) if tile else 0
        text_w = max(t.render(text, size, color).get_width() for text, color in lines)
        w, h = logo_w + text_w, line_h * len(lines)
        gap = symbol_r + round(10 * L.s)

        right = pygame.Rect(round(x + gap), round(y - h / 2), w, h)
        left = pygame.Rect(round(x - gap - w), round(y - h / 2), w, h)
        above = pygame.Rect(round(x - w / 2), round(y - gap - h), w, h)
        below = pygame.Rect(round(x - w / 2), round(y + gap), w, h)
        toward_centre = [right, left] if x < L.cx else [left, right]
        bounds = pygame.Rect(0, 0, L.radar_w, L.h)

        for rect in toward_centre + [above, below]:
            if not bounds.contains(rect) or rect.collidelist(placed) != -1:
                continue
            placed.append(rect.inflate(round(6 * L.s), round(2 * L.s)))
            # Left-hand labels read right-to-left from the aircraft: text
            # right-aligned, logo nearest the symbol.
            on_left = rect is left
            if tile:
                lx = rect.right - tile.get_width() if on_left else rect.left
                self.screen.blit(tile, (lx, rect.top + round(2 * L.s)))
            for i, (text, color) in enumerate(lines):
                ty = rect.top + i * line_h
                if on_left:
                    t.draw(self.screen, text, size, color, (rect.right - logo_w, ty), "topright")
                else:
                    t.draw(self.screen, text, size, color, (rect.left + logo_w, ty), "topleft")
            return True
        return False

    def visible_planes(self, planes) -> list:
        """Aircraft that pass the ground switch and the filters. Also records
        (shown, total) so the panel can say "23 of 165 aircraft"."""
        st = self.settings
        self._watch = watch_patterns(st.watchlist)
        base = [ac for ac in planes if st.show_ground or not ac.on_ground]
        # Watched aircraft and emergencies show even when filtered out.
        shown = [ac for ac in base if self.filter.passes(ac, st) or is_watched(ac, self._watch)
                 or (st.highlight_emergencies and emergency_label(ac))]
        # Count what's inside the outer ring (the list and scope show the same
        # set); aircraft fetched beyond it only feed the edge dots.
        outer = st.outer_km
        in_range = lambda ac: math.hypot(*self.offset_km(ac.lat, ac.lon)) <= outer
        self.counts = (sum(map(in_range, shown)), sum(map(in_range, base)))
        return shown

    def count_text(self) -> str:
        shown, total = self.counts
        if self.filter.active(self.settings):
            return f"{shown} of {total} aircraft (filtered)"
        return f"{shown} aircraft"

    def draw_traffic(self, planes, base_time):
        """Draws the radar contacts; returns [(dist_km, bearing, ac)] nearest first."""
        L = self.layout
        # Drawn as soon as they're inside the outer ring (a symbol right at the
        # edge pokes out by at most half its size); the list shows the same set,
        # plus emergencies and watched aircraft just beyond it.
        inside_km = self.settings.outer_km
        inside, beyond, listing = [], [], []

        self.styles = {}
        for ac in self.visible_planes(planes):
            sty = self.styles[id(ac)] = self.style(ac)
            lat, lon = self.extrapolate(ac, base_time)
            dx, dy = self.offset_km(lat, lon)
            dist = math.hypot(dx, dy)
            bearing = math.degrees(math.atan2(dx, dy)) % 360.0
            if dist <= inside_km or sty["emergency"] or sty["watched"]:
                listing.append((dist, bearing, ac))
            if dist <= inside_km:
                x, y = self.to_screen(lat, lon)
                inside.append((dist, x, y, ac))
            elif dist > 0.01 and (self.settings.show_beyond_dots or sty["emergency"] or sty["watched"]):
                rad = bearing * DEG
                beyond.append((L.cx + math.sin(rad) * L.dot_r, L.cy - math.cos(rad) * L.dot_r, sty))

        # Table order: emergencies, then watched aircraft, then nearest first.
        listing.sort(key=lambda t: (not self.styles[id(t[2])]["emergency"],
                                    not self.styles[id(t[2])]["watched"], t[0]))

        for x, y, sty in beyond:
            aa_disc(self.screen, sty["color"], (x, y), L.dot_size)
            if sty["watched"] or sty["emergency"]:
                ring = ERROR if sty["emergency"] else WATCH_COLOR
                pygame.gfxdraw.aacircle(self.screen, round(x), round(y), L.dot_size + round(5 * L.s), ring)

        inside.sort(key=lambda t: -t[0])  # far first, so nearer symbols draw on top
        kinds = [self.symbol_kind(ac) for _, _, _, ac in inside]
        by_kind = self.settings.color_by_kind
        for (_, x, y, ac), kind in zip(inside, kinds):
            sty = self.styles[id(ac)]
            # Vector first so the symbol sits on top of it.
            rad = ac.nose_deg * DEG
            nose = symbols.nose_offset_px(kind, L.s) if kind else L.nose
            self.draw_speed_vector((x + math.sin(rad) * nose, y - math.cos(rad) * nose), ac,
                                   sty["color"] if by_kind else TRACK)
            self.draw_symbol(x, y, ac, kind, sty["color"])
            r = self.symbol_radius(kind)
            if sty["watched"]:
                for k in (8, 10):
                    pygame.gfxdraw.aacircle(self.screen, round(x), round(y), round(r + k * L.s), WATCH_COLOR)
            if sty["emergency"]:
                pulse = 10 + 8 * (time.monotonic() * 1.5 % 1.0)  # expanding ring
                for k in (0, 1.5):
                    pygame.gfxdraw.aacircle(self.screen, round(x), round(y),
                                            round(r + (pulse + k) * L.s), ERROR)
        nearest = min(inside, key=lambda t: t[0]) if inside else None
        if nearest:
            # Mark the nearest contact to tie it to the panel's "Nearest" card.
            _, x, y, ac = nearest
            pygame.gfxdraw.aacircle(self.screen, round(x), round(y),
                                    round(self.symbol_radius(self.symbol_kind(ac)) + 8 * L.s), HIGHLIGHT)
        # Labels avoid each other, every aircraft symbol, and the fixed labels.
        # Emergencies and watched aircraft are labelled first, then nearest
        # first, so close traffic gets labels and the crowded far edges give way.
        placed = list(self.static_obstacles)
        for (_, x, y, _), kind in zip(inside, kinds):
            r = round(self.symbol_radius(kind))
            placed.append(pygame.Rect(round(x) - r, round(y) - r, 2 * r, 2 * r))
        order = sorted(zip(inside, kinds), key=lambda t: (
            not self.styles[id(t[0][3])]["emergency"], not self.styles[id(t[0][3])]["watched"], t[0][0]))
        for (_, x, y, ac), kind in order:
            self.draw_tag(x, y, ac, self.symbol_radius(kind), placed, self.styles[id(ac)])
        return listing

    def draw_panel(self, listing, base_time, error):
        L = self.layout
        s, t = L.s, self.text
        x = L.panel_x + L.pad
        right = L.w - L.pad
        y = L.pad
        st = self.settings

        t.draw(self.screen, "SKYSCOPE", round(54 * s), SWEEP, (x, y))
        now = datetime.now()
        t.draw(self.screen, now.strftime("%H:%M:%S"), round(54 * s), LABEL, (right, y), "topright")
        y += round(56 * s)
        utc = datetime.now(timezone.utc).strftime("%H:%M UTC")
        r = t.draw(self.screen, self.location_text()[:48], round(28 * s), PANEL_DIM, (x, y))
        note, note_color = self.location_label()
        if note:
            t.draw(self.screen, f"  ·  {note}", round(28 * s), note_color, (r.right, y))
        t.draw(self.screen, utc, round(28 * s), PANEL_DIM, (right, y), "topright")
        y += round(36 * s)

        if error and base_time == 0:
            status, color = f"No data: {error}"[:60], ERROR
        elif base_time == 0:
            status, color = "Waiting for data...", PANEL_DIM
        else:
            age = int(time.monotonic() - base_time)
            status = f"{self.count_text()}  ·  {self.feed.source_label()}  ·  {age}s ago"
            color = ERROR if error else LABEL
        t.draw(self.screen, status, round(30 * s), color, (x, y))
        preset = matching_preset(st)
        rng = f"{preset}  ·  Range {st.range_label()}" if preset and preset != "Everything" \
            else f"Range {st.range_label()}"
        t.draw(self.screen, rng, round(30 * s), GRID if not st.sweep_enabled else SWEEP,
               (right, y), "topright")
        y += round(48 * s)
        pygame.draw.line(self.screen, GRID, (x, y), (right, y), L.stroke)
        y += round(20 * s)

        y = self.draw_alerts(listing, x, y, right)
        if listing:
            y = self.draw_nearest_card(min(listing, key=lambda e: e[0]), x, y, right)
            y += round(16 * s)
            pygame.draw.line(self.screen, GRID, (x, y), (right, y), L.stroke)
            y += round(16 * s)

        # Table of contacts, nearest first. Header: column name, unit beneath.
        show_logos = st.airline_logos != "off"
        logo_w = round(46 * s) if show_logos else 0
        cols = [("CALLSIGN", "", 0.0, "topleft"), ("TYPE", "", 0.27, "topleft")]
        if st.show_airspeed:
            cols += [("ALT", st.altitude_symbol, 0.52, "topright"),
                     ("DIST", st.distance_symbol, 0.65, "topright"),
                     ("BRG", "°", 0.75, "topright"),
                     ("GS", st.speed_symbol, 0.875, "topright"),
                     (st.airspeed_symbol, st.speed_symbol, 1.0, "topright")]
        else:
            cols += [("ALT", st.altitude_symbol, 0.56, "topright"),
                     ("DIST", st.distance_symbol, 0.72, "topright"),
                     ("BRG", "°", 0.85, "topright"),
                     ("GS", st.speed_symbol, 1.0, "topright")]
        width = right - x
        hsize = round(24 * s)
        for i, (name, unit, frac, anchor) in enumerate(cols):
            cx = x + frac * width + (logo_w if i == 0 else 0)
            t.draw(self.screen, name, hsize, PANEL_DIM, (cx, y), anchor)
            if unit:
                t.draw(self.screen, unit, max(14, round(22 * s)), PANEL_DIM,
                       (cx, y + round(25 * s)), anchor)
        y += round(56 * s)

        row_size = round(30 * s)
        row_h = round(38 * s)
        footer_h = round(140 * s if st.color_by_kind else 110 * s)
        rows_fit = max(0, (L.h - footer_h - y) // row_h)
        for dist, bearing, ac in listing[:rows_fit]:
            airspeed = ac.ias_kt if st.airspeed_type == "ias" else ac.tas_kt
            sty = self.styles.get(id(ac), {})
            call_color = ERROR if sty.get("emergency") else WATCH_COLOR if sty.get("watched") else LABEL
            cells = [(ac.callsign, call_color), (ac.type or "—", TAG_TYPE),
                     (st.format_altitude(ac.alt_ft, ac.on_ground, unit=False), TAG_ALT),
                     (st.format_distance(dist, unit=False), LABEL), (f"{bearing:03.0f}", LABEL),
                     (st.format_speed(ac.gs_kt, unit=False), LABEL)]
            if st.show_airspeed:
                cells.append((st.format_speed(airspeed, unit=False), PANEL_DIM if airspeed is None else LABEL))
            if show_logos:
                tile = self.logos.tile(ac.callsign, row_h - round(6 * s))
                if tile is not None:
                    self.screen.blit(tile, (x, y - round(4 * s)))
            for i, ((text, color), (_, _, frac, anchor)) in enumerate(zip(cells, cols)):
                t.draw(self.screen, text, row_size, color,
                       (x + frac * width + (logo_w if i == 0 else 0), y), anchor)
            y += row_h
        if len(listing) > rows_fit > 0:
            more = f"+ {len(listing) - rows_fit} more"
            t.draw(self.screen, more, round(24 * s), PANEL_DIM, (x, y))

        if st.color_by_kind:
            # Colour key, just above the footer.
            lx, ly, sw = x, L.h - L.pad - round(64 * s), round(14 * s)
            for cid, label in CLASSES:
                pygame.draw.rect(self.screen, CLASS_COLORS[cid], (lx, ly - sw, sw, sw), border_radius=3)
                r = t.draw(self.screen, label, round(20 * s), PANEL_DIM, (lx + sw + round(6 * s), ly), "bottomleft")
                lx = r.right + round(16 * s)
        if self.web_url:
            t.draw(self.screen, f"Settings:  {self.web_url}", round(26 * s), SWEEP,
                   (x, L.h - L.pad - round(30 * s)), "bottomleft")
        keys = "R range · U distance units · W runways · S sweep · A symbols · L logos · D dots · Q quit"
        t.draw(self.screen, keys, round(22 * s), PANEL_DIM, (x, L.h - L.pad), "bottomleft")

    def draw_alerts(self, listing, x, y, right) -> int:
        """Banner for emergencies (red) and, if enabled, watched aircraft
        (gold) in range. Returns the y below it."""
        s, t, st = self.layout.s, self.text, self.settings
        lines = []
        for dist, bearing, ac in listing:
            sty = self.styles.get(id(ac), {})
            where = f"{st.format_distance(dist)} at {bearing:03.0f}°"
            if sty.get("emergency"):
                lines.append((EMERGENCY_BG, ERROR, f"{sty['emergency']}:  {ac.callsign} {ac.type}  {where}"))
            elif sty.get("watched") and st.watch_notice:
                lines.append((WATCH_BG, WATCH_COLOR, f"WATCHLIST:  {ac.callsign} {ac.type}  {where}"))
        for bg, fg, text in lines[:3]:
            h = round(40 * s)
            pygame.draw.rect(self.screen, bg, (x, y, right - x, h), border_radius=round(8 * s))
            t.draw(self.screen, text, round(26 * s), fg, (x + round(12 * s), y + h // 2), "midleft")
            y += h + round(8 * s)
        if lines:
            y += round(8 * s)
        return y

    def card_photo(self, ac: Aircraft):
        """(Surface, credit) for this exact aircraft once fetched in the
        background, else None. Only photos of the airframe itself (see photos.py)."""
        key = ac.hex or ac.reg
        if key != self._photo_key:
            self._photo_key, self._photo = key, None

            def fetch(key=key, hex_id=ac.hex, reg=ac.reg):
                found = PHOTOS.find(hex_id, reg)
                image = None
                if found:
                    try:
                        image = self._photo_images.get(found["src"]) or \
                            pygame.image.load(io.BytesIO(fetch_image(found["src"])))
                        if len(self._photo_images) > 30:
                            self._photo_images.clear()
                        self._photo_images[found["src"]] = image
                    except Exception as exc:  # offline or a bad image: no photo
                        print(f"photos: {exc}")
                if self._photo_key == key:  # still the aircraft on the card
                    self._photo = (image, found["credit"].replace("Photo: ", "© ").replace(
                        " · Planespotters.net", "") if found else "")

            threading.Thread(target=fetch, daemon=True).start()
        return self._photo if self._photo and self._photo[0] is not None else None

    def draw_fit(self, text, size, color, pos, max_w) -> None:
        """Draw text in max_w pixels: a slightly smaller font if needed, then '...'."""
        t = self.text
        for sz in range(size, round(size * 0.78) - 1, -1):
            if t.render(text, sz, color).get_width() <= max_w:
                t.draw(self.screen, text, sz, color, pos)
                return
        sz = round(size * 0.78)
        while len(text) > 4 and t.render(text + "...", sz, color).get_width() > max_w:
            text = text[:-1]
        t.draw(self.screen, text.rstrip() + "...", sz, color, pos)

    def draw_nearest_card(self, entry, x, y, right):
        dist, bearing, ac = entry
        s, t, st = self.layout.s, self.text, self.settings
        label = CLASS_LABELS[self.filter.aircraft_class(ac)].upper()
        t.draw(self.screen, f"NEAREST  ·  {label}", round(24 * s), HIGHLIGHT, (x, y))
        y += round(30 * s)
        # Photo of this exact aircraft, as a thumbnail at the card's right.
        photo = self.card_photo(ac) if st.show_photos else None
        if photo:
            pw, ph = round(209 * s), round(132 * s)
            img, credit = photo
            if self._photo_thumb[:2] != (id(img), (pw, ph)):  # scale once per photo, not per frame
                k = max(pw / img.get_width(), ph / img.get_height())  # cover the box, then crop
                scaled = pygame.transform.smoothscale(
                    img.convert(), (round(img.get_width() * k), round(img.get_height() * k)))
                crop = pygame.Rect((scaled.get_width() - pw) // 2, (scaled.get_height() - ph) // 2, pw, ph)
                self._photo_thumb = (id(img), (pw, ph), scaled.subsurface(crop).copy())
            box = pygame.Rect(right - pw, y + round(26 * s), pw, ph)
            self.screen.blit(self._photo_thumb[2], box)
            pygame.draw.rect(self.screen, GRID, box, 1)
            self.draw_fit(credit, round(16 * s), PANEL_DIM, (box.x, box.bottom + round(3 * s)), pw)
            right = box.x - round(16 * s)  # card text stays left of the photo
        if st.airline_logos != "off":
            tile = self.logos.tile(ac.callsign, round(96 * s))
            if tile is not None:
                self.screen.blit(tile, (x, y + round(4 * s)))
                x += tile.get_width() + round(20 * s)
        width = right - x
        self.draw_fit(ac.callsign, round(64 * s), LABEL, (x, y), width)
        y += round(62 * s)
        desc = ac.desc or ac.type or "Unknown type"
        if ac.reg and ac.reg != ac.callsign:  # once, on the type line (GA callsigns are the reg)
            desc = f"{desc[:30]}  ·  {ac.reg}"
        self.draw_fit(desc, round(32 * s), TAG_TYPE, (x, y), width)
        y += round(42 * s)

        self.draw_fit(self.altitude_summary(ac), round(30 * s), TAG_ALT, (x, y), width)
        y += round(38 * s)
        line = (f"{st.format_distance(dist)}  ·  bearing {bearing:03.0f}°  ·  "
                f"track {ac.track_deg:03.0f}°")
        self.draw_fit(line, round(30 * s), LABEL, (x, y), width)
        y += round(38 * s)
        self.draw_fit(self.speed_summary(ac), round(30 * s), LABEL, (x, y), width)
        return y + round(38 * s)

    def altitude_summary(self, ac: Aircraft) -> str:
        st = self.settings
        alt = st.format_altitude(ac.alt_ft, ac.on_ground)
        if ac.vert_rate_fpm is not None and not ac.on_ground and abs(ac.vert_rate_fpm) >= 200:
            verb = "climbing" if ac.vert_rate_fpm > 0 else "descending"
            alt += f"  ({verb} {st.format_vertical_rate(ac.vert_rate_fpm)})"
        return alt

    def speed_summary(self, ac: Aircraft) -> str:
        """Ground speed, plus whichever airspeeds the aircraft reports."""
        st = self.settings
        speeds = [f"GS {st.format_speed(ac.gs_kt)}"]
        if st.show_airspeed:
            if ac.tas_kt is not None:
                speeds.append(f"TAS {st.format_speed(ac.tas_kt)}")
            if ac.ias_kt is not None:
                speeds.append(f"IAS {st.format_speed(ac.ias_kt)}")
            if len(speeds) == 1:
                speeds.append("no airspeed reported")
        return "  ·  ".join(speeds)

    # --- browser display (/radar) -------------------------------------------
    # The page draws the scope itself; these supply the data, formatted with
    # the same units and classification as the pygame display.

    def web_static_key(self) -> str:
        st = self.settings
        return (f"{st.lat:.5f},{st.lon:.5f},{st.outer_km:.3f},{st.show_runways},"
                f"{''.join(st.runway_types)},{st.runway_centerlines},{st.show_airspace},{st.procedure_mode},"
                f"{sorted(st.procedure_airports.items())}")

    def web_static(self) -> dict:
        """Runway map near the centre, and the silhouette shapes."""
        feats = self.map_features() if self.settings.show_runways else \
            {"airports": [], "runways": [], "centerline_nm": airports.CENTERLINE_NM}
        return {
            "key": self.web_static_key(),
            **feats,
            **self.overlay_features(),
            "shapes": {k: {"polys": polys, "length": length}
                       for k, (polys, length) in symbols.SHAPES.items()},
        }

    def web_state(self) -> dict:
        """Settings, status and aircraft (positions as of now), for one poll."""
        st = self.settings
        planes, base_time, error = self.feed.snapshot()
        rows = []
        for ac in self.visible_planes(planes):
            lat, lon = self.extrapolate(ac, base_time)
            dx, dy = self.offset_km(lat, lon)
            dist = math.hypot(dx, dy)
            airspeed = ac.ias_kt if st.airspeed_type == "ias" else ac.tas_kt
            cls = self.filter.aircraft_class(ac)
            color = CLASS_COLORS[cls] if st.color_by_kind else SINGLE_COLOR
            rows.append({
                "id": ac.hex or ac.callsign, "lat": lat, "lon": lon,
                "track": ac.track_deg, "nose": ac.nose_deg, "gs_motion": ac.gs_knots,
                "kind": self.symbol_kind(ac),
                "callsign": ac.callsign, "type": ac.type, "desc": ac.desc, "reg": ac.reg,
                "airline": airline_code(ac.callsign),
                "alt": st.format_altitude(ac.alt_ft, ac.on_ground),
                "alt_short": st.format_altitude(ac.alt_ft, ac.on_ground, unit=False),
                "alt_summary": self.altitude_summary(ac),
                "dist_km": dist, "dist": st.format_distance(dist, unit=False),
                "dist_long": st.format_distance(dist),
                "bearing": math.degrees(math.atan2(dx, dy)) % 360.0,
                "gs": st.format_speed(ac.gs_kt, unit=False),
                "airspeed": st.format_speed(airspeed, unit=False),
                "speed_summary": self.speed_summary(ac),
                "class_label": CLASS_LABELS[cls],
                "in_range": dist <= st.outer_km,  # inside the outer ring (listed and drawn)
                "color": "#%02x%02x%02x" % color,
                "emergency": emergency_label(ac) if st.highlight_emergencies else "",
                "watched": is_watched(ac, self._watch),
            })
        # Emergencies, then watched aircraft, then nearest first.
        rows.sort(key=lambda r: (not r["emergency"], not r["watched"], r["dist_km"]))
        note, note_color = self.location_label()
        return {
            "static_key": self.web_static_key(),
            "settings": {
                "lat": st.lat, "lon": st.lon, "outer_km": st.outer_km,
                "range_label": st.range_label(),
                "rings": [{"frac": f, "label": label} for f, label in st.rings()],
                "color_by_kind": st.color_by_kind, "watch_notice": st.watch_notice,
                "show_photos": st.show_photos,
                "legend": [{"label": label, "color": "#%02x%02x%02x" % CLASS_COLORS[cid]}
                           for cid, label in CLASSES],
                "presets": list(all_presets(st)), "preset": matching_preset(st) or "",
                "location_text": self.location_text(),
                "altitude_choice": self.altitude_choice(), "procedure_mode": st.procedure_mode,
                "hidden_classes": st.hidden_classes, "hidden_alt_bands": st.hidden_alt_bands,
                "classes": [{"id": c, "label": label} for c, label in CLASSES],
                "alt_bands": [{"id": b, "label": label} for b, label in ALT_BANDS],
                "has_procedures": bool(st.procedure_airports),
                "distance_symbol": st.distance_symbol, "speed_symbol": st.speed_symbol,
                "altitude_symbol": st.altitude_symbol, "airspeed_symbol": st.airspeed_symbol,
                "show_airspeed": st.show_airspeed, "show_beyond_dots": st.show_beyond_dots,
                "sweep_enabled": st.sweep_enabled, "sweep_period_s": st.sweep_period_s,
                "sweep_trail_deg": st.sweep_trail_deg, "airline_logos": st.airline_logos,
                "aircraft_symbol": st.aircraft_symbol,
            },
            "status": {
                "source": self.feed.source_label(),
                "count_text": self.count_text(),
                "age_s": None if base_time == 0 else time.monotonic() - base_time,
                "error": error,
                "location_note": note, "location_note_color": "#%02x%02x%02x" % note_color,
            },
            "aircraft": rows,
        }

    # Altitude dropdown on the radar page → hidden altitude blocks.
    ALTITUDE_CHOICES = {
        "all": [], "low": ["mid", "high"], "mid": ["low", "high"], "high": ["low", "mid"],
        "below_fl180": ["high"], "above_10000": ["low"],
    }

    def altitude_choice(self) -> str:
        hidden = sorted(self.settings.hidden_alt_bands)
        return next((k for k, v in self.ALTITUDE_CHOICES.items() if sorted(v) == hidden), "custom")

    def web_quick(self, req: dict) -> dict:
        """Change set for the radar page's quick dropdowns (validated)."""
        changes = {}
        if req.get("altitude") in self.ALTITUDE_CHOICES:
            changes["hidden_alt_bands"] = list(self.ALTITUDE_CHOICES[req["altitude"]])
        if req.get("procedures") in ("off", "sid", "star", "both"):
            changes["procedure_mode"] = req["procedures"]
        # The radar page's filter panel sends the full lists of hidden kinds/blocks.
        if isinstance(req.get("hidden_classes"), list):
            known = {c for c, _ in CLASSES}
            changes["hidden_classes"] = [c for c in req["hidden_classes"] if c in known]
        if isinstance(req.get("hidden_alt_bands"), list):
            known = {b for b, _ in ALT_BANDS}
            changes["hidden_alt_bands"] = [b for b in req["hidden_alt_bands"] if b in known]
        return changes

    # --- SkyScope Satellite feed (/api/satellite, /api/satellite/map) --------------
    # Compact data for small ESP32 displays that mirror this radar. Positions are
    # relative to the outer ring: x right, y down, the ring at radius 1.0.

    SAT_KINDS = {None: 0, "jet": 1, "heavy": 2, "bizjet": 3, "turboprop": 4, "light": 5, "glider": 6, "heli": 7}
    SAT_MAX_AIRCRAFT = 250  # a satellite's memory budget; nearest and alerts kept first

    def _ring_xy(self, lat: float, lon: float) -> tuple[float, float]:
        dx, dy = self.offset_km(lat, lon)
        return dx / self.settings.outer_km, -dy / self.settings.outer_km

    def web_satellite(self) -> dict:
        st = self.settings
        planes, base_time, error = self.feed.snapshot()
        rows = []
        for ac in self.visible_planes(planes):
            lat, lon = self.extrapolate(ac, base_time)
            x, y = self._ring_xy(lat, lon)
            r = math.hypot(x, y)
            emergency = bool(emergency_label(ac)) and st.highlight_emergencies
            watched = is_watched(ac, self._watch)
            if r > 1.0 and not (st.show_beyond_dots or emergency or watched):
                continue
            cls = self.filter.aircraft_class(ac)
            color = CLASS_COLORS[cls] if st.color_by_kind else SINGLE_COLOR
            # Velocity in ring units per second, for smooth motion between polls.
            v = ac.gs_knots * 1.852 / 3600.0 / st.outer_km
            t = ac.track_deg * DEG
            flags = (1 if emergency else 0) | (2 if watched else 0) | (8 if r > 1.0 else 0)
            rows.append([r, [
                (ac.hex or ac.callsign)[:8], round(x, 4), round(y, 4),
                round(v * math.sin(t), 6), round(-v * math.cos(t), 6), round(ac.nose_deg), round(ac.track_deg),
                self.SAT_KINDS.get(self.symbol_kind(ac), 1), (color[0] << 16) | (color[1] << 8) | color[2],
                ac.callsign[:8], ac.type[:4], st.format_altitude(ac.alt_ft, ac.on_ground, unit=False),
                flags, emergency_label(ac) if emergency else ""]])
        rows.sort(key=lambda r: (not r[1][12] & 3, r[0]))  # alerts first, then nearest
        rows = rows[:self.SAT_MAX_AIRCRAFT]
        inside = [r for r in rows if r[0] <= 1.0]
        nearest = min(inside, key=lambda r: r[0]) if inside else None
        if nearest:
            nearest[1][12] |= 4
        card = None
        listing = []
        by_id = {(ac.hex or ac.callsign)[:8]: ac for ac in planes}
        for r, row in sorted(rows, key=lambda r: (not r[1][12] & 3, r[0])):
            if r > 1.0 and not row[12] & 3:
                continue
            ac = by_id.get(row[0])
            if ac is None:
                continue
            dist = r * st.outer_km
            bearing = math.degrees(math.atan2(row[1], -row[2])) % 360.0
            if len(listing) < 14:
                listing.append([ac.callsign[:8], ac.type[:4], st.format_altitude(ac.alt_ft, ac.on_ground, unit=False),
                                st.format_distance(dist, unit=False), f"{bearing:03.0f}",
                                st.format_speed(ac.gs_kt, unit=False), row[12]])
            if row is (nearest[1] if nearest else None):
                desc = ac.desc or ac.type or "Unknown type"
                if ac.reg and ac.reg != ac.callsign:
                    desc = f"{desc[:26]} · {ac.reg}"
                card = {"call": ac.callsign, "desc": desc[:40], "cls": CLASS_LABELS[self.filter.aircraft_class(ac)],
                        "alt": self.altitude_summary(ac)[:44],
                        "pos": f"{st.format_distance(dist)} · brg {bearing:03.0f}° · trk {ac.track_deg:03.0f}°",
                        "spd": self.speed_summary(ac)[:44], "hex": ac.hex, "reg": ac.reg}
        age = None if base_time == 0 else round(time.monotonic() - base_time, 1)
        return {
            "v": 1, "map": self.web_static_key(),
            "range": st.range_label(), "rings": [[round(f, 4), label] for f, label in st.rings()],
            "sweep": [st.sweep_enabled, st.sweep_period_s, st.sweep_trail_deg],
            "loc": self.location_text()[:48], "count": self.count_text(), "src": self.feed.source_label(),
            "age": age, "err": (error or "")[:60],
            "units": [st.altitude_symbol, st.distance_symbol, st.speed_symbol],
            "ac": [row for _, row in rows], "card": card, "list": listing,
        }

    def web_satellite_map(self) -> dict:
        """The map as clipped segments in ring units, with style codes:
        1 runway, 2 centreline/ticks, 3/4/5 airspace B/C/D, 6 SID, 7 STAR.
        Labels: [style, x, y, text] with 8 airport, 9 fix, 10 airspace shelf."""
        st = self.settings
        lines, labels = [], []
        budget = [6000]  # points: keeps the JSON small for an ESP32

        def seg(style, p0, p1):
            clipped = clip_segment_to_circle(p0, p1, (0.0, 0.0), 1.0)
            if clipped and budget[0] > 0:
                (x0, y0), (x1, y1) = clipped
                lines.append([style, round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)])
                budget[0] -= 2

        def inside(x, y, margin=0.0):
            return math.hypot(x, y) <= 1.0 - margin

        ov = self.overlay_features()
        for shape in ov["airspace"]:
            style = {"B": 3, "C": 4, "D": 5}[shape["class"]]
            for ring in shape["rings"]:
                pts = [self._ring_xy(lat, lon) for lon, lat in ring]
                for a, b in zip(pts, pts[1:] + pts[:1]):
                    seg(style, a, b)
            if shape["rings"] and st.outer_km <= (80 if shape["class"] in "BC" else 40):
                lon, lat, _ = max((centroid(r) for r in shape["rings"]), key=lambda c: c[2])
                x, y = self._ring_xy(lat, lon)
                if inside(x, y, 0.05):
                    labels.append([10 + 0, round(x, 4), round(y, 4), f"{shape['ceiling']}/{shape['floor']}"])
        fixes = set()
        for proc in ov["procedures"]:
            style = 7 if proc["kind"] == "STAR" else 6
            for line in proc["lines"]:
                pts = [self._ring_xy(p[0], p[1]) for p in line]
                for a, b in zip(pts, pts[1:]):
                    seg(style, a, b)
                if st.outer_km <= 100:
                    for (lat, lon, fix), (x, y) in zip(line, pts):
                        if fix not in fixes and not fix.startswith("RW") and inside(x, y, 0.03):
                            fixes.add(fix)
                            labels.append([9, round(x, 4), round(y, 4), fix])
        if st.show_runways:
            feats = self.map_features()
            nm = 1.852 / st.outer_km
            for rw in feats["runways"]:
                a = self._ring_xy(rw["ends"][0], rw["ends"][1])
                b = self._ring_xy(rw["ends"][2], rw["ends"][3])
                seg(1, a, b)
                length = math.hypot(b[0] - a[0], b[1] - a[1])
                if not rw["centerline"] or length == 0:
                    continue
                ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
                for (ex, ey), sx, sy in ((a, -ux, -uy), (b, ux, uy)):
                    far = feats["centerline_nm"] * nm
                    seg(2, (ex, ey), (ex + sx * far, ey + sy * far))
                    if nm >= 0.012:  # ticks only when miles are far enough apart
                        for n in range(1, feats["centerline_nm"] + 1):
                            px, py, h = ex + sx * nm * n, ey + sy * nm * n, (0.012 if n % 5 == 0 else 0.006)
                            seg(2, (px - uy * h, py + ux * h), (px + uy * h, py - ux * h))
            for ap in feats["airports"]:
                x, y = self._ring_xy(ap["lat"], ap["lon"])
                if ap["label"] and 0.03 < math.hypot(x, y) < 0.97:
                    labels.append([8, round(x, 4), round(y, 4), ap["ident"]])
        return {"v": 1, "key": self.web_static_key(), "lines": lines, "labels": labels[:150]}

    def web_next_range(self) -> dict:
        """Change set for a tap on the browser scope."""
        return {"range_index": (self.settings.range_index + 1) % len(self.settings.range_presets())}

    def render(self) -> None:
        if self.static is None:
            self.static = self.build_static()
        self.screen.blit(self.static, (0, 0))
        if self.settings.sweep_enabled:
            self.draw_sweep()
        planes, base_time, error = self.feed.snapshot()
        listing = self.draw_traffic(planes, base_time)
        if self.layout.has_panel:
            self.draw_panel(listing, base_time, error)

    # --- input --------------------------------------------------------------

    def handle_key(self, key) -> bool:
        """Returns False to quit."""
        st = self.settings
        if key in (pygame.K_q, pygame.K_ESCAPE):
            return False
        if key in (pygame.K_r, pygame.K_SPACE, pygame.K_RIGHT, pygame.K_UP):
            st.next_range()
        elif key in (pygame.K_LEFT, pygame.K_DOWN):
            st.prev_range()
        elif key == pygame.K_u:
            st.next_distance_unit()
        elif key == pygame.K_w:
            st.show_runways = not st.show_runways
        elif key == pygame.K_g:
            st.show_ground = not st.show_ground
        elif key == pygame.K_d:
            st.show_beyond_dots = not st.show_beyond_dots
        elif key == pygame.K_s:
            st.sweep_enabled = not st.sweep_enabled
        elif key == pygame.K_a:
            st.aircraft_symbol = "triangle" if st.aircraft_symbol == "silhouette" else "silhouette"
        elif key == pygame.K_l:
            modes = ["off", "panel", "all"]
            st.airline_logos = modes[(modes.index(st.airline_logos) + 1) % 3
                                     if st.airline_logos in modes else 0]
        else:
            return True
        self.invalidate()
        return True

    def apply_changes(self, changes: dict) -> None:
        """Apply settings saved from the web page."""
        old_source = self.settings.location_source
        if changes.pop("_gps_now", False):
            self._gps_pending = True
        # The form's range refers to the unit the page was showing; apply it
        # first, then convert to the nearest preset if the unit changed.
        new_unit = changes.pop("distance_unit", self.settings.distance_unit)
        for name, value in changes.items():
            setattr(self.settings, name, value)
        self.settings.range_index %= len(self.settings.range_presets())
        if new_unit != self.settings.distance_unit:
            self.settings.set_distance_unit(new_unit)
        self.feed.set_source(self.settings.data_source, self.settings.sdr_location)
        if self.settings.location_source != "manual":
            self.settings.center_airport = ""  # GPS owns the position now
            self.gps.start()
            if self.settings.location_source != old_source:
                self._gps_pending = True  # switching to GPS: use the next fix
        self.invalidate()

    def resize(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self.layout = Layout(*screen.get_size())
        self.invalidate()


def run_web_only(settings: Settings) -> int:
    """Data, GPS and web server only; the browser draws the radar."""
    import webbrowser
    if not settings.web_port:
        print("web_port is 0 in settings.json; nothing to serve")
        return 1
    feed = AdsbFeed(settings.fetch_interval_s, settings.data_source, settings.sdr_location)
    # Geometry only: an off-screen surface stands in for the window.
    app = SkyScope(pygame.Surface((1920, 1080)), settings, feed)
    feed.start()
    web = SettingsServer(settings, settings.web_port, app.web_statuses, app)
    if not web.start():
        return 1
    url = f"http://localhost:{settings.web_port}/radar"
    print(f"Radar: {url}   (Ctrl+C to stop)")
    webbrowser.open(url)
    try:
        while True:
            web.apply_pending(app.apply_changes)
            app.update_location()
            time.sleep(0.05)
    except KeyboardInterrupt:
        return 0


def parse_size(text: str) -> tuple[int, int]:
    w, h = text.lower().split("x")
    return int(w), int(h)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--window", type=parse_size, metavar="WxH",
                    help="run in a window of this size instead of fullscreen")
    ap.add_argument("--screenshot", metavar="PNG",
                    help="render for --seconds, save a PNG and exit (for testing)")
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--web-only", action="store_true",
                    help="no window: serve the radar to a browser at /radar (sharp on any screen)")
    args = ap.parse_args()

    settings = Settings.load()
    if args.web_only:
        return run_web_only(settings)
    pygame.init()
    pygame.display.set_caption("SkyScope")
    if args.window:
        screen = pygame.display.set_mode(args.window)
    else:
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)

    feed = AdsbFeed(settings.fetch_interval_s, settings.data_source, settings.sdr_location)
    app = SkyScope(screen, settings, feed)
    feed.start()
    web = SettingsServer(settings, settings.web_port, app.web_statuses, app) if settings.web_port else None
    if web and web.start():
        app.web_url = f"http://{lan_address()}:{settings.web_port}/radar_config"

    clock = pygame.time.Clock()
    started = time.monotonic()
    fullscreen = not args.window
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_f:
                    fullscreen = not fullscreen
                    if fullscreen:
                        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
                    else:
                        screen = pygame.display.set_mode(args.window or (1280, 720))
                    pygame.mouse.set_visible(not fullscreen)
                    app.resize(screen)
                else:
                    running = app.handle_key(event.key)

        if web:
            web.apply_pending(app.apply_changes)
        app.update_location()
        app.render()
        pygame.display.flip()
        clock.tick(settings.fps)

        if args.screenshot and time.monotonic() - started >= args.seconds:
            pygame.image.save(screen, args.screenshot)
            print(f"Saved {args.screenshot}  (avg {clock.get_fps():.1f} fps)")
            running = False

    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
