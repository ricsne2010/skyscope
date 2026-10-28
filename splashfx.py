"""The splash screen's light show, drawn over the Project Moon Pi badge (the badge itself never moves):

  - a lens flare runs along the red swoosh, with faint ghost rings across the badge, and bursts into a
    starburst at the swoosh's tip
  - the stars in the blue ring twinkle
  - the lander's engine flames flicker
  - a band of light sweeps across the white rings and the lettering, like light on polished metal

Where everything is comes from <splash>.fx.json, .fx-sheen.png and .fx-flame.png beside the splash picture, made by
make_splash_fx.py (in the Project Moon Pi brand kit, _brand/animations). Without them (your own splash picture, say) the splash is shown still, as before.
Everything here is drawn once when the splash loads; each frame only adds those pictures onto the badge,
so it's light work for the Pi. No numpy needed.
"""
import json
import math
import os
import random

import pygame

FLARE = (0.3, 2.1)          # seconds: the flare runs along the swoosh
BURST = (2.1, 3.0)          # the starburst at the tip
SHEEN = (2.5, 3.7)          # the light band across the rings and lettering
WARM = (255, 236, 200)      # flare and sheen light
BLUE = (120, 190, 255)      # engine glow


def _glow(radius, colour, falloff=2.2):
    """A soft round glow on black, for adding onto the picture."""
    size = max(2, int(radius * 2))
    s = pygame.Surface((size, size))
    for i in range(int(radius), 0, -1):
        k = (1 - i / radius) ** falloff
        pygame.draw.circle(s, [int(c * k) for c in colour], (size // 2, size // 2), i)
    return s


def _ring(radius, colour, width):
    """A faint ring (a lens 'ghost'): bright at its rim, dark inside."""
    size = int(radius * 2 + 4)
    s = pygame.Surface((size, size))
    for i in range(width, 0, -1):
        k = 1 - i / width
        pygame.draw.circle(s, [int(c * k) for c in colour], (size // 2, size // 2), int(radius), i)
    return s


def _streak(length, height, colour):
    """A long thin horizontal streak: the flare's anamorphic flash."""
    s = pygame.Surface((int(length), max(2, int(height))))
    for x in range(int(length)):
        k = (1 - abs(2 * x / length - 1)) ** 3
        pygame.draw.line(s, [int(c * k) for c in colour], (x, 0), (x, s.get_height()))
    return _fade_rows(s)


def _fade_rows(s):
    """Darken a streak towards its top and bottom edges."""
    w, h = s.get_size()
    mask = pygame.Surface((w, h))
    for y in range(h):
        k = int(255 * (1 - abs(2 * y / max(1, h - 1) - 1)) ** 1.5)
        pygame.draw.line(mask, (k, k, k), (0, y), (w, y))
    s.blit(mask, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
    return s


def _burst(radius, colour, rays=12):
    """A starburst: thin rays of different lengths around a bright centre (drawn big, then shrunk smooth)."""
    big = int(radius * 4)
    s = pygame.Surface((big, big))
    rng = random.Random(7)
    c = big / 2
    for i in range(rays):
        a = 2 * math.pi * i / rays + rng.uniform(-0.08, 0.08)
        ln = radius * 2 * (1.0 if i % 2 == 0 else rng.uniform(0.45, 0.7))
        for w, k in ((7, 0.25), (4, 0.5), (2, 1.0)):
            col = [int(v * k) for v in colour]
            pygame.draw.line(s, col, (c, c), (c + ln * math.cos(a), c + ln * math.sin(a)), w)
    s.blit(_glow(radius * 0.6, colour, 1.6), (c - radius * 0.6, c - radius * 0.6), special_flags=pygame.BLEND_RGB_ADD)
    return pygame.transform.smoothscale(s, (big // 2, big // 2))


def _sparkle(size, colour):
    """A four-point star twinkle."""
    n = max(6, int(size * 8))
    s = pygame.Surface((n, n))
    c = n // 2
    for w, k in ((3, 0.35), (1, 1.0)):
        col = [int(v * k) for v in colour]
        pygame.draw.line(s, col, (0, c), (n, c), w)
        pygame.draw.line(s, col, (c, 0), (c, n), w)
    s.blit(_glow(n * 0.22, colour, 1.4), (c - n * 0.22, c - n * 0.22), special_flags=pygame.BLEND_RGB_ADD)
    return s


def _scaled(surf, k):
    """surf with its brightness times k (0..1), for adding."""
    out = surf.copy()
    v = max(0, min(255, int(255 * k)))
    out.fill((v, v, v), special_flags=pygame.BLEND_RGB_MULT)
    return out


def _ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def _bump(t, start, end):
    """0 -> 1 -> 0 over [start, end]."""
    if not start < t < end:
        return 0.0
    return math.sin(math.pi * (t - start) / (end - start))


class SplashFX:
    """Built for one splash picture placed at `rect` (its on-screen rectangle, after scaling)."""

    def __init__(self, picture_path, rect):
        base = os.path.splitext(picture_path)[0]
        with open(base + ".fx.json") as f:
            fx = json.load(f)
        k = rect.width / fx["size"][0]
        self.k = k

        def at(x, y):
            return rect.x + x * k, rect.y + y * k

        R = fx["radius"] * k
        self.radius = R
        self.centre = at(*fx["centre"])
        self.path = [at(x, y) for x, y in fx["path"]]
        seg = [math.dist(a, b) for a, b in zip(self.path, self.path[1:])]
        self.cum = [0.0]
        for d in seg:
            self.cum.append(self.cum[-1] + d)
        self.tip = at(*fx["tip"])

        rng = random.Random(11)
        self.stars = [(at(x, y), max(0.8, s * k), rng.uniform(0, 6.28), rng.uniform(1.6, 3.2))
                      for x, y, s in fx["stars"]]
        self.jets = [(at(x, y), w) for x, y, w in fx["jets"]]

        # the masks (white where it applies, black elsewhere), at screen size and tinted, cropped to what's lit
        self.sheen_src, self.sheen_rect = self._mask(base + ".fx-sheen.png", fx["sheen_box"], at, k, WARM)
        self.flame, self.flame_rect = self._mask(base + ".fx-flame.png", fx["flame_box"], at, k, (170, 215, 255))

        # the light band for the sheen: a diagonal soft stripe, wide enough to cross the whole badge
        bh = self.sheen_rect.height
        self.band_w = int(0.5 * R)
        row = pygame.Surface((self.band_w, 1))
        for x in range(self.band_w):
            v = int(255 * (1 - abs(2 * x / self.band_w - 1)) ** 2.2)
            row.set_at((x, 0), (v, v, v))
        self.band = pygame.Surface((self.band_w + int(bh * 0.45) + 1, bh))
        for y in range(bh):                          # leaning right: the light comes from the upper left
            self.band.blit(row, (int((bh - y) * 0.45), y))

        # flare pieces
        self.core = _glow(0.16 * R, WARM, 1.8)
        self.halo = _glow(0.45 * R, (110, 90, 70), 2.5)
        self.streak = _streak(1.6 * R, 0.05 * R, (200, 210, 255))
        self.ghosts = [(_ring(0.07 * R, (60, 90, 140), 4), -0.3), (_glow(0.05 * R, (90, 60, 120)), -0.55),
                       (_ring(0.13 * R, (50, 110, 90), 5), -0.75), (_glow(0.03 * R, (120, 100, 60)), 0.4)]
        self.burst = _burst(0.32 * R, (255, 240, 215))
        self.sparkles = {round(s): _sparkle(round(s), (255, 250, 235)) for _, s, _, _ in self.stars}
        self.jet_glow = _glow(0.11 * R, BLUE, 1.6)

    @staticmethod
    def _mask(path, box, at, k, colour):
        """The part of a mask picture inside box ([x, y, w, h] in the picture), scaled to the screen and tinted:
        (picture, its screen rectangle)."""
        x, y, w, h = box
        m = pygame.image.load(path).convert().subsurface((x, y, w, h))
        sx, sy = at(x, y)
        size = (max(1, round(w * k)), max(1, round(h * k)))
        m = pygame.transform.smoothscale(m, size)
        m.fill(colour, special_flags=pygame.BLEND_RGB_MULT)
        return m, pygame.Rect(round(sx), round(sy), *size)

    def _along(self, f):
        """The point a fraction f of the way along the swoosh path."""
        d = f * self.cum[-1]
        for i in range(1, len(self.cum)):
            if self.cum[i] >= d:
                a, b = self.path[i - 1], self.path[i]
                u = (d - self.cum[i - 1]) / max(1e-6, self.cum[i] - self.cum[i - 1])
                return a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u
        return self.path[-1]

    def _add(self, frame, surf, centre, k=1.0):
        if k <= 0.01:
            return
        if k < 0.99:
            surf = _scaled(surf, k)
        frame.blit(surf, (int(centre[0] - surf.get_width() / 2), int(centre[1] - surf.get_height() / 2)),
                   special_flags=pygame.BLEND_RGB_ADD)

    def draw(self, frame, t):
        """Add the light show at t seconds into the animation onto `frame` (the splash picture)."""
        add = pygame.BLEND_RGB_ADD

        # engines: a flicker on the flames and a glow under each nozzle
        flick = 0.45 + 0.25 * math.sin(t * 23.0) * math.sin(t * 7.3 + 1) + 0.15 * math.sin(t * 41.0)
        if self.flame is not None:
            frame.blit(_scaled(self.flame, max(0.0, flick)), self.flame_rect.topleft, special_flags=add)
        for i, (p, _) in enumerate(self.jets):
            self._add(frame, self.jet_glow, p, 0.35 + 0.25 * math.sin(t * 19.0 + i * 2.1))

        # stars: each glints now and then
        for (x, y), size, phase, speed in self.stars:
            v = math.sin(t * speed + phase)
            if v > 0.55:
                self._add(frame, self.sparkles[round(size)], (x, y), (v - 0.55) / 0.45)

        # the flare along the swoosh, its ghosts mirrored through the badge's centre
        if FLARE[0] < t < FLARE[1] + 0.25:
            f = _ease((t - FLARE[0]) / (FLARE[1] - FLARE[0]))
            p = self._along(f)
            k = min(1.0, (t - FLARE[0]) / 0.25) * (1.0 if t < FLARE[1] else 1 - (t - FLARE[1]) / 0.25)
            self._add(frame, self.halo, p, 0.6 * k)
            self._add(frame, self.streak, p, 0.7 * k)
            self._add(frame, self.core, p, k)
            cx, cy = self.centre
            for ghost, s in self.ghosts:                 # mirrored through the centre; fading where they'd leave it
                g = (cx + (p[0] - cx) * s, cy + (p[1] - cy) * s)
                out = math.dist(g, self.centre) / self.radius
                self._add(frame, ghost, g, 0.8 * k * max(0.0, min(1.0, (0.85 - out) / 0.25)))

        # the starburst at the tip
        b = _bump(t, *BURST)
        if b:
            u = (t - BURST[0]) / (BURST[1] - BURST[0])
            size = 0.6 + 0.6 * u
            burst = pygame.transform.rotozoom(self.burst, -25 * u, size)
            self._add(frame, burst, self.tip, b)
            self._add(frame, self.core, self.tip, b)

        # the sheen: the light band crossing the rings and lettering, left to right
        if SHEEN[0] < t < SHEEN[1]:
            u = _ease((t - SHEEN[0]) / (SHEEN[1] - SHEEN[0]))
            r = self.sheen_rect
            bw = self.band.get_width()
            x = int(-bw + u * (r.width + bw))
            strip = pygame.Rect(x, 0, bw, r.height).clip(pygame.Rect(0, 0, r.width, r.height))
            if strip.width:                              # light only the strip under the band
                lit = self.sheen_src.subsurface(strip).copy()
                lit.blit(self.band, (x - strip.x, 0), special_flags=pygame.BLEND_RGB_MULT)
                frame.blit(_scaled(lit, 0.85), (r.x + strip.x, r.y), special_flags=add)
