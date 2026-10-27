"""Top-down aircraft silhouettes, chosen from the ADS-B emitter category and
ICAO type code.

Shapes are lists of polygons in model units: nose toward -y, the aircraft
spanning roughly -1..1 on both axes. They are rotated to the heading and
scaled per class when drawn.
"""

import math

import pygame
import pygame.gfxdraw


def _mirror(half):
    """Close a right-hand outline (nose → tail, x ≥ 0) into a full polygon."""
    return half + [(-x, y) for x, y in reversed(half) if x != 0]


# Narrow-body airliner: swept wing, underwing engines, swept tailplane.
JET = [
    _mirror([(0, -1.0), (0.07, -0.88), (0.09, -0.65), (0.09, 0.7), (0.05, 0.95), (0, 1.0)]),
    _mirror([(0, -0.25), (0.25, -0.12), (0.95, 0.22), (0.95, 0.3), (0.25, 0.12), (0, 0.15)]),
    _mirror([(0, 0.68), (0.12, 0.74), (0.38, 0.88), (0.38, 0.95), (0, 0.9)]),
    _mirror([(0.33, -0.12), (0.39, -0.12), (0.39, 0.06), (0.33, 0.06)]),
]

# Wide-body / four-engine: broader fuselage, longer wing, two pods per side.
HEAVY = [
    _mirror([(0, -1.0), (0.09, -0.86), (0.12, -0.6), (0.12, 0.7), (0.06, 0.95), (0, 1.0)]),
    _mirror([(0, -0.28), (0.3, -0.14), (1.0, 0.24), (1.0, 0.32), (0.3, 0.12), (0, 0.15)]),
    _mirror([(0, 0.66), (0.14, 0.72), (0.42, 0.87), (0.42, 0.95), (0, 0.9)]),
    _mirror([(0.31, -0.15), (0.38, -0.15), (0.38, 0.05), (0.31, 0.05)]),
    _mirror([(0.6, 0.0), (0.67, 0.0), (0.67, 0.18), (0.6, 0.18)]),
]

# Business jet: slim fuselage, small swept wing, rear engines, T-tail.
BIZJET = [
    _mirror([(0, -1.0), (0.06, -0.85), (0.08, -0.6), (0.08, 0.75), (0.04, 0.95), (0, 1.0)]),
    _mirror([(0, -0.1), (0.2, -0.02), (0.8, 0.25), (0.8, 0.33), (0.2, 0.2), (0, 0.22)]),
    _mirror([(0.08, 0.42), (0.2, 0.42), (0.2, 0.68), (0.08, 0.68)]),
    _mirror([(0, 0.78), (0.1, 0.82), (0.38, 0.92), (0.38, 0.99), (0, 0.97)]),
]

# Turboprop: straight wing, nacelles forward of the leading edge.
TURBOPROP = [
    _mirror([(0, -1.0), (0.07, -0.86), (0.09, -0.6), (0.09, 0.72), (0.05, 0.95), (0, 1.0)]),
    _mirror([(0, -0.2), (0.95, -0.14), (0.95, 0.02), (0, 0.06)]),
    _mirror([(0.28, -0.45), (0.36, -0.45), (0.38, 0.12), (0.26, 0.12)]),
    _mirror([(0, 0.72), (0.36, 0.76), (0.36, 0.88), (0, 0.9)]),
]

# Light single (Cessna-style): straight high wing, prop nose.
LIGHT = [
    _mirror([(0, -0.95), (0.1, -0.9), (0.12, -0.55), (0.06, 0.8), (0, 0.85)]),
    _mirror([(0.0, -1.0), (0.25, -1.0), (0.25, -0.94), (0.0, -0.94)]),
    _mirror([(0, -0.42), (1.0, -0.42), (1.0, -0.2), (0, -0.2)]),
    _mirror([(0, 0.62), (0.38, 0.62), (0.38, 0.8), (0, 0.82)]),
]

# Glider: very long, thin wing.
GLIDER = [
    _mirror([(0, -0.8), (0.06, -0.7), (0.05, 0.85), (0, 0.9)]),
    _mirror([(0, -0.38), (1.0, -0.3), (1.0, -0.24), (0, -0.24)]),
    _mirror([(0, 0.78), (0.25, 0.78), (0.25, 0.86), (0, 0.88)]),
]

# Helicopter: cabin, tail boom, tail rotor; the main rotor disc is drawn
# separately as a ring.
HELI_BODY = [
    _mirror([(0, -0.55), (0.2, -0.45), (0.24, -0.1), (0.15, 0.2), (0.04, 0.3), (0.035, 0.85), (0, 0.88)]),
    _mirror([(0, 0.78), (0.22, 0.78), (0.22, 0.86), (0, 0.86)]),
]

# class name → (polygons, length in px at 1080p)
SHAPES = {
    "jet": (JET, 34),
    "heavy": (HEAVY, 46),
    "bizjet": (BIZJET, 26),
    "turboprop": (TURBOPROP, 28),
    "light": (LIGHT, 24),
    "glider": (GLIDER, 26),
    "heli": (HELI_BODY, 30),
}

HELI_TYPES = ("EC", "AS3", "AS5", "AS6", "H1", "H2", "H6", "R22", "R44", "R66",
              "B06", "B407", "B412", "B429", "A109", "A119", "A139", "A169", "A189",
              "AW", "S61", "S76", "S92", "BK17", "EH10", "NH90", "MI8", "UH1")
TURBOPROP_TYPES = ("AT4", "AT7", "DH8", "SF34", "F50", "D328", "JS3", "JS4", "B190",
                   "C208", "PC12", "BE20", "BE9", "SW4", "L410", "C130", "A400",
                   "DHC6", "E120", "SB20", "P180", "TBM")
BIZJET_TYPES = ("C25", "C5", "C6", "C68", "C7", "E50P", "E55P", "LJ", "GLF", "GL5",
                "GL6", "GL7", "GLEX", "CL30", "CL35", "CL60", "F2TH", "F900", "FA",
                "PC24", "HDJT", "H25", "PRM1", "SF50", "BE40")
# Common light aircraft (Cessna singles, Pipers, Cirrus, Beech, Diamond, Mooney,
# Grumman, Van's ...), for when the feed gives a type but no category.
LIGHT_TYPES = ("C15", "C17", "C18", "C182", "C195", "C206", "C207", "C210", "P210", "C310",
               "C340", "C402", "C414", "C421", "P28", "PA", "SR2", "S22", "BE23", "BE24",
               "BE33", "BE35", "BE36", "BE55", "BE58", "BE76", "DA2", "DA4", "DA62", "M20",
               "AA1", "AA5", "RV", "GLAS", "LA4", "CH7", "J3", "PC6", "T206", "T210", "AC11")
# Airliner families, likewise.
AIRLINER_TYPES = ("A31", "A32", "A33", "A34", "A35", "A38", "A2", "A19N", "B71", "B72", "B73",
                  "B37", "B38", "B39", "B3XM", "B75", "B76", "B77", "B78", "BCS", "CRJ", "E13",
                  "E14", "E17", "E19", "E29", "E75", "MD8", "MD9", "B46", "RJ")
HEAVY_TYPES = ("A33", "A34", "A35", "A38", "B74", "B76", "B77", "B78", "IL96",
               "MD11", "DC10", "A3ST", "BLCF")


def classify(category: str, type_code: str) -> str:
    """Pick a silhouette class. Type code wins where it is specific; the
    emitter category (A1 light … A5 heavy, A7 rotorcraft, B1 glider) fills in."""
    t = (type_code or "").upper()
    if t.startswith(HELI_TYPES) or category == "A7":
        return "heli"
    if category == "B1" or t.startswith(("GLID", "DG", "ASK", "LS")):
        return "glider"
    if t.startswith(HEAVY_TYPES) or category == "A5":
        return "heavy"
    if t.startswith(TURBOPROP_TYPES):
        return "turboprop"
    if t.startswith(BIZJET_TYPES) or category == "A6":
        return "bizjet"
    if t.startswith(LIGHT_TYPES) or category in ("A1", "B4"):
        return "light"
    if t.startswith(AIRLINER_TYPES) or category in ("A3", "A4"):
        return "jet"
    if category == "A2":
        return "bizjet"
    # No category and an unrecognised type: far more often a light aircraft
    # than an airliner (airliners nearly always report a category).
    return "light" if not category else "jet"


def shape_length_px(kind: str, scale: float) -> float:
    return SHAPES[kind][1] * scale


def nose_offset_px(kind: str, scale: float) -> float:
    """Distance from the symbol centre to its nose (where the speed vector starts)."""
    return shape_length_px(kind, scale) / 2


def draw_silhouette(surf, kind, x, y, heading_deg, scale, color):
    polys, length = SHAPES[kind]
    half = length * scale / 2
    rad = math.radians(heading_deg)
    s, c = math.sin(rad), math.cos(rad)
    for poly in polys:
        # Model: nose at -y. Screen: heading 0 = up, clockwise.
        pts = [(round(x + (px * c - py * s) * half), round(y + (px * s + py * c) * half))
               for px, py in poly]
        pygame.gfxdraw.aapolygon(surf, pts, color)
        pygame.gfxdraw.filled_polygon(surf, pts, color)
    if kind == "heli":
        r = round(half * 0.82)
        cx = x - s * half * -0.2  # rotor hub sits over the cabin, ahead of centre
        cy = y + c * half * -0.2
        pygame.gfxdraw.aacircle(surf, round(cx), round(cy), r, color)
        pygame.gfxdraw.aacircle(surf, round(cx), round(cy), r - 1, color)
