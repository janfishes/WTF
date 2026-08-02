# Generates the app's home-screen / PWA icons: icon-512.png, icon-192.png and
# apple-touch-icon.png. Orange ground with the WTF lettering over a solid white
# redfish (Build 292, 2026-08-01; teal before that).
#
# The artwork is NOT redrawn here -- it is read straight out of index.html's
# <path id="fishP">, which is a pure polygon trace (comma-separated linetos, no
# curves) of the splash fish. Its four subpaths are, in order: the fish outline,
# then the W, F and T letterforms that the splash knocks OUT of the fish. This
# script fills the outline solid instead and sets the W/T/F block above it.
# So the icon and the splash can never drift apart -- retrace one, rerun this.
#
# Layout stays inside the central 80% of the square (Android's maskable crop).
# The files are full-bleed squares on purpose: iOS and Android round the corners
# themselves, and a PNG that rounds its own would show doubled corners.
#
# Usage:
#   python3 tools/build_icon.py      # overwrites the three PNGs in the repo root
#
# Requires Pillow. Changing the ground color: edit BRAND below, and keep it in step
# with --brand in index.html (the splash ground darkens the same value to 80%).

import re, io, json
from PIL import Image, ImageDraw

BRAND  = (242, 102, 12)      # #f2660c - same --brand the splash ground derives from
WHITE  = (254, 254, 254)
BLACK  = (0, 0, 0)

src = io.open('/Users/janneal/Documents/WTF/index.html', encoding='utf-8').read()
d = re.search(r'<path id="fishP" fill-rule="evenodd" d="(.*?)"/>', src, re.S).group(1)
parts = [p for p in d.split('Z') if p.strip()]

def pts(p):
    n = [float(x) for x in re.findall(r'-?\d+(?:\.\d+)?', p)]
    return list(zip(n[0::2], n[1::2]))

fish    = pts(parts[0])                       # silhouette, no letter holes
letters = [pts(parts[1]), pts(parts[3]), pts(parts[2])]   # W, T, F
EYE = (709.0, 89.0, 19.3)

L_X0, L_Y0, L_X1, L_Y1 = 217.0, 82.0, 491.0, 173.0        # letter block bbox
F_W, F_H = 760.0, 294.0

SS = 4                                        # supersample for clean edges

def render(size):
    S = size * SS
    img = Image.new('RGB', (S, S), BRAND)
    dr  = ImageDraw.Draw(img)

    # Layout, in icon units, then scaled. Build 301: the mark was reading small on the
    # home screen / desktop with a wide band of orange all round, so fish and lettering
    # both grew and the WTF took a stroke for weight (same trick .logo-wtf uses in the
    # banner, where Comic Neue's 700 is the heaviest cut there is). The block still
    # clears the corners iOS and Android round off; it now runs closer to the edges
    # than Android's central-80% maskable circle, which is a deliberate trade for a
    # legible mark - the letters and the fish body stay well inside it, only the tail
    # and snout tips reach past.
    fish_w = 0.90 * size           # was 0.801
    wtf_w  = 0.62 * size           # was 0.488
    gap    = 0.05 * size
    fs = fish_w / F_W
    ls = wtf_w / (L_X1 - L_X0)
    wtf_h, fish_h = (L_Y1 - L_Y0) * ls, F_H * fs
    top = (size - (wtf_h + gap + fish_h)) / 2

    lx, ly = (size - wtf_w) / 2, top
    # The traced letterforms carry one weight, so the extra heft comes from a stroke
    # ridden round each outline rather than from a bolder cut - the banner's -webkit-text-stroke
    # in PNG form. Centred on the path, so it thickens the glyph instead of ringing it.
    bold = max(1, round(0.018 * size * SS))
    for poly in letters:
        p = [(((x - L_X0) * ls + lx) * SS, ((y - L_Y0) * ls + ly) * SS) for x, y in poly]
        dr.polygon(p, fill=WHITE)
        dr.line(p + [p[0]], fill=WHITE, width=bold, joint='curve')
        # joint='curve' rounds the corners it turns but leaves the line ENDS square, so
        # each vertex still needs a dot of its own or the outline shows nicks.
        for x, y in p:
            dr.ellipse([x - bold / 2, y - bold / 2, x + bold / 2, y + bold / 2], fill=WHITE)

    fx, fy = (size - fish_w) / 2, top + wtf_h + gap
    dr.polygon([((x * fs + fx) * SS, (y * fs + fy) * SS) for x, y in fish], fill=WHITE)

    ex, ey, er = EYE[0] * fs + fx, EYE[1] * fs + fy, EYE[2] * fs
    dr.ellipse([(ex - er) * SS, (ey - er) * SS, (ex + er) * SS, (ey + er) * SS], fill=BLACK)

    return img.resize((size, size), Image.LANCZOS)

for name, size in [('icon-512.png', 512), ('icon-192.png', 192), ('apple-touch-icon.png', 180)]:
    render(size).save('/Users/janneal/Documents/WTF/' + name, optimize=True)
    print(name, size)
