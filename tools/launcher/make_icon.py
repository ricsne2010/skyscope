"""Draws SkyScope's 1024px radar-scope app icon (needs Pillow).

    python3 tools/launcher/make_icon.py tools/launcher/skyscope-1024.png
    python3 tools/launcher/make_icon.py tools/launcher/skyscope-stop-1024.png --stop

skyscope.icns (Mac) and skyscope.ico (Windows) are made from that PNG; see
make_mac_app.sh for the Mac steps."""
import math
import sys
from PIL import Image, ImageDraw, ImageFilter

S = 1024
SS = 2  # supersample
W = S * SS
img = Image.new("RGBA", (W, W), (0, 0, 0, 0))

# macOS-style tile: 824px rounded square centred in 1024, with a soft shadow.
tile = 824 * SS
off = (W - tile) // 2
shadow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
ImageDraw.Draw(shadow).rounded_rectangle([off, off + 18 * SS, off + tile, off + tile + 18 * SS], radius=185 * SS,
                                         fill=(0, 0, 0, 110))
shadow = shadow.filter(ImageFilter.GaussianBlur(22 * SS))
img.alpha_composite(shadow)

face = Image.new("RGBA", (W, W), (0, 0, 0, 0))
fd = ImageDraw.Draw(face)
# vertical gradient body
for y in range(off, off + tile):
    t = (y - off) / tile
    c = (int(10 + 6 * t), int(22 + 4 * t), int(46 - 14 * t), 255)
    fd.line([(off, y), (off + tile, y)], fill=c)
mask = Image.new("L", (W, W), 0)
ImageDraw.Draw(mask).rounded_rectangle([off, off, off + tile, off + tile], radius=185 * SS, fill=255)

cx = cy = W // 2
R = 330 * SS
scope = Image.new("RGBA", (W, W), (0, 0, 0, 0))
sd = ImageDraw.Draw(scope)
sd.ellipse([cx - R - 22 * SS, cy - R - 22 * SS, cx + R + 22 * SS, cy + R + 22 * SS], fill=(14, 30, 26, 255),
           outline=(40, 70, 60, 255), width=10 * SS)
sd.ellipse([cx - R, cy - R, cx + R, cy + R], fill=(4, 18, 12, 255))

# sweep: a beam with a fading trail (clockwise, head pointing up-right)
head = 52  # degrees from north
trail = 95
sweep = Image.new("RGBA", (W, W), (0, 0, 0, 0))
swd = ImageDraw.Draw(sweep)
steps = 190
for i in range(steps):
    a0 = head - trail * (i + 1) / steps
    a1 = head - trail * i / steps
    alpha = int(170 * (1 - i / steps) ** 1.6)
    # PIL angles: 0 = east, clockwise; north = -90
    swd.pieslice([cx - R, cy - R, cx + R, cy + R], a0 - 90, a1 - 90 + 0.3, fill=(70, 255, 120, alpha))
scope.alpha_composite(sweep)

green = (70, 255, 120, 255)
dim = (46, 150, 82, 255)
for f in (0.25, 0.5, 0.75, 1.0):
    r = R * f
    sd.ellipse([cx - r, cy - r, cx + r, cy + r], outline=dim, width=6 * SS)
sd.line([cx - R, cy, cx + R, cy], fill=dim, width=5 * SS)
sd.line([cx, cy - R, cx, cy + R], fill=dim, width=5 * SS)
for deg in range(0, 360, 30):
    a = math.radians(deg)
    sd.line([cx + math.sin(a) * (R - 26 * SS), cy - math.cos(a) * (R - 26 * SS), cx + math.sin(a) * R,
             cy - math.cos(a) * R], fill=green, width=7 * SS)
# beam leading edge
a = math.radians(head)
sd.line([cx, cy, cx + math.sin(a) * R, cy - math.cos(a) * R], fill=(170, 255, 190, 255), width=10 * SS)

# blips: bright just behind the beam, fading further back; one amber "selected"
blips = [(30, 0.62, 1.0), (8, 0.36, 0.85), (-30, 0.82, 0.55), (150, 0.55, 0.35), (215, 0.7, 0.3), (280, 0.3, 0.3)]
glow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
for deg, rf, b in blips:
    a = math.radians(deg)
    x, y = cx + math.sin(a) * R * rf, cy - math.cos(a) * R * rf
    r = 17 * SS
    gd.ellipse([x - r * 2.2, y - r * 2.2, x + r * 2.2, y + r * 2.2], fill=(90, 255, 140, int(120 * b)))
    sd.ellipse([x - r, y - r, x + r, y + r], fill=(190, 255, 210, int(255 * max(b, 0.45))))
a = math.radians(115)
x, y = cx + math.sin(a) * R * 0.45, cy - math.cos(a) * R * 0.45
gd.ellipse([x - 40 * SS, y - 40 * SS, x + 40 * SS, y + 40 * SS], fill=(255, 200, 0, 110))
sd.ellipse([x - 18 * SS, y - 18 * SS, x + 18 * SS, y + 18 * SS], fill=(255, 210, 60, 255))
sd.ellipse([x - 34 * SS, y - 34 * SS, x + 34 * SS, y + 34 * SS], outline=(255, 200, 0, 255), width=6 * SS)
glow = glow.filter(ImageFilter.GaussianBlur(14 * SS))
face.alpha_composite(scope)
face.alpha_composite(glow)
sd2 = ImageDraw.Draw(face)
sd2.ellipse([cx - 9 * SS, cy - 9 * SS, cx + 9 * SS, cy + 9 * SS], fill=(220, 255, 230, 255))

# glass highlight on the top half of the tile
hl = Image.new("RGBA", (W, W), (0, 0, 0, 0))
ImageDraw.Draw(hl).ellipse([off - tile * 0.2, off - tile * 0.75, off + tile * 1.2, off + tile * 0.42],
                           fill=(255, 255, 255, 18))
face.alpha_composite(hl)

body = Image.new("RGBA", (W, W), (0, 0, 0, 0))
body.paste(face, (0, 0), mask)
img.alpha_composite(body)
if "--stop" in sys.argv:
    # The Stop SkyScope icon: a red stop badge over the scope's lower right.
    bx, by, br = off + tile * 0.80, off + tile * 0.80, 175 * SS
    badge = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    bd = ImageDraw.Draw(badge)
    bd.ellipse([bx - br - 14 * SS, by - br - 14 * SS + 16 * SS, bx + br + 14 * SS, by + br + 14 * SS + 16 * SS],
               fill=(0, 0, 0, 120))
    badge = badge.filter(ImageFilter.GaussianBlur(12 * SS))
    bd = ImageDraw.Draw(badge)
    bd.ellipse([bx - br - 14 * SS, by - br - 14 * SS, bx + br + 14 * SS, by + br + 14 * SS], fill=(255, 255, 255, 255))
    bd.ellipse([bx - br, by - br, bx + br, by + br], fill=(222, 38, 38, 255))
    q = br * 0.42
    bd.rounded_rectangle([bx - q, by - q, bx + q, by + q], radius=14 * SS, fill=(255, 255, 255, 255))
    img.alpha_composite(badge)
img.resize((S, S), Image.LANCZOS).save(sys.argv[1])
