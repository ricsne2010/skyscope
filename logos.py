"""Airline logos, keyed by the ICAO airline code at the start of a callsign
(KLM25J → KLM).

Logos are not shipped with the code (they are the airlines' trademarks). They
are downloaded on first sight into logos_cache/ and reused from there. PNGs you
put in logos/ (named like KLM.png) take priority over downloaded ones.
"""

import queue
import re
import threading
import urllib.request
from pathlib import Path

import pygame

HERE = Path(__file__).resolve().parent
USER_DIR = HERE / "logos"
CACHE_DIR = HERE / "logos_cache"
MISSING_FILE = CACHE_DIR / "missing.txt"
SOURCE_URL = "https://raw.githubusercontent.com/Jxck-S/airline-logos/main/flightaware_logos/{}.png"

TILE_BG = (232, 236, 242)
CALLSIGN_RE = re.compile(r"^([A-Z]{3})\d")


def airline_code(callsign: str) -> str | None:
    m = CALLSIGN_RE.match(callsign or "")
    return m.group(1) if m else None


class LogoStore:
    def __init__(self):
        CACHE_DIR.mkdir(exist_ok=True)
        try:
            self._missing = set(MISSING_FILE.read_text().split())
        except FileNotFoundError:
            self._missing = set()
        self._requested: set[str] = set()
        self._images: dict[str, pygame.Surface | None] = {}
        self._tiles: dict[tuple[str, int], pygame.Surface] = {}
        self._lock = threading.Lock()
        self._queue: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._download_loop, name="logos", daemon=True).start()

    def _path(self, code: str) -> Path | None:
        for d in (USER_DIR, CACHE_DIR):
            p = d / f"{code}.png"
            if p.exists():
                return p
        return None

    def file_for(self, code: str) -> Path | None:
        """Path to the airline's logo, or None. The first ask for an unknown
        logo queues its download, so a later ask may succeed."""
        path = self._path(code)
        if path is None:
            with self._lock:
                if code not in self._missing and code not in self._requested:
                    self._requested.add(code)
                    self._queue.put(code)
        return path

    def is_missing(self, code: str) -> bool:
        with self._lock:
            return code in self._missing

    def _image(self, code: str) -> pygame.Surface | None:
        if code in self._images:
            return self._images[code]
        path = self.file_for(code)
        if path is None:
            if self.is_missing(code):
                self._images[code] = None
            return None  # not downloaded yet; try again next frame
        try:
            img = pygame.image.load(str(path)).convert_alpha()
        except pygame.error as exc:
            print(f"logos: can't load {path}: {exc}")
            img = None
        self._images[code] = img
        return img

    def tile(self, callsign: str, size: int) -> pygame.Surface | None:
        """The airline's logo on a light rounded tile, or None if unknown."""
        code = airline_code(callsign)
        if code is None or size < 8:
            return None
        key = (code, size)
        tile = self._tiles.get(key)
        if tile is not None:
            return tile
        img = self._image(code)
        if img is None:
            return None
        tile = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.rect(tile, TILE_BG, tile.get_rect(), border_radius=max(2, size // 6))
        inner = round(size * 0.86)
        w, h = img.get_size()
        k = inner / max(w, h)
        logo = pygame.transform.smoothscale(img, (max(1, round(w * k)), max(1, round(h * k))))
        tile.blit(logo, logo.get_rect(center=(size // 2, size // 2)))
        self._tiles[key] = tile
        return tile

    def _download_loop(self) -> None:
        while True:
            code = self._queue.get()
            url = SOURCE_URL.format(code)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "SkyScope/1.0 (+https://github.com/ricsne2010/skyscope)"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = resp.read()
                (CACHE_DIR / f"{code}.png").write_bytes(data)
            except urllib.error.HTTPError as exc:
                if exc.code == 404:  # no logo for this airline; don't ask again
                    with self._lock:
                        self._missing.add(code)
                        MISSING_FILE.write_text("\n".join(sorted(self._missing)) + "\n")
                else:
                    print(f"logos: {code}: {exc}")
            except Exception as exc:  # offline etc.; retried after restart
                print(f"logos: {code}: {exc}")
