#!/usr/bin/env python3
"""Sweep USGS ImageryTopo tiles along the coast and measure every printed
place name the app's sea paint would dim, so SEA_LABEL_WINDOWS can be
GENERATED instead of hand-spotted (v402; Jan: "lots of labels have this
problem... can you fix these errors along the coastline").

Method: reproduce the app's painted-water zone exactly (SHORE_RINGS +
SHORE_PAD_M, minus the SEA_EDGE_FEATHER_M inward feather — a pixel is
"dimmed" once it sits past ring+300 m with >=20% paint alpha), fetch every
tile z11-16 whose bbox touches the coast strip in LAT_RANGE, threshold the
tiles for the topo's bright white label ink, cluster the ink into label
boxes (4 px grid cells + word/line merge), and match each box against the
GNIS gazetteer — the file the topo labels itself from, so a real label
always has an anchor just west of its box. Clusters with no GNIS match are
the charted dashed lines / symbols / surf: they are NOT windowed (that's
the v401-era "line is also showing through" bug — windows must never
contain loose white chart ink) and are written out as avoid-boxes instead.

Output: sea_label_scan.json in --out (per zoom: matched labels with global
pixel boxes + unmatched avoid boxes). tools/gen_sea_windows.py turns that
into the SEA_LABEL_WINDOWS table.

Usage:
  python3 tools/scan_sea_labels.py --cache /path/to/tilecache --out /path/out
Needs: pillow, numpy. Tiles are cached on disk; a full sweep is ~2000
requests cold, zero warm.
"""
import argparse, io, json, math, os, re, sys, urllib.request, zipfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "..", "index.html")
TILE_URL = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryTopo/MapServer/tile/{z}/{y}/{x}"
GNIS_URL = "https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/DomesticNames/DomesticNames_FL_Text.zip"

LAT_RANGE = (27.8, 30.2)     # Cape Canaveral .. north of St. Augustine
LNG_MIN = -81.8              # Atlantic side of the mainland ring only
ZOOMS = range(11, 17)
PAD_M = 1300                 # SHORE_PAD_M
FEATHER_M = 1000             # SEA_EDGE_FEATHER_M (inward)
DIM_M = PAD_M - FEATHER_M + 200   # >=20% paint alpha -> visibly dimmed
TAIL_PX = 280                # max label run east of its anchor, any zoom
BRIGHT = 200                 # white label ink: min(r,g,b) >= BRIGHT
CELL = 4                     # cluster grid cell (px); 8-neighbour merge

# Labels that must NEVER get a window at any zoom: USGS prints them in the
# wrong place and the app flattens them with SEA_LABEL_ERASERS instead
# (v401 — the town name "Ponce Inlet" printed ~700 m out in the ocean).
# Clusters near these points are reported under "erase" with their measured
# boxes so the eraser table can be extended to the zooms that need it.
EXCLUDE = [(29.1002, -80.9314, 1200)]   # lat, lng, radius m

def load_rings():
    src = open(INDEX, encoding="utf-8").read()
    m = re.search(r"const SHORE_RINGS = (\[\[.*?\]\]);", src)
    return json.loads(m.group(1))

def load_gnis(cache):
    path = os.path.join(cache, "gnis_fl.json")
    if os.path.exists(path):
        return json.load(open(path))
    zpath = os.path.join(cache, "gnis_fl.zip")
    if not os.path.exists(zpath):
        urllib.request.urlretrieve(GNIS_URL, zpath)
    feats = []
    with zipfile.ZipFile(zpath) as zf:
        name = [n for n in zf.namelist() if n.lower().endswith(".txt")][0]
        for i, line in enumerate(io.TextIOWrapper(zf.open(name), encoding="utf-8")):
            if i == 0:
                continue
            f = line.rstrip("\n").split("|")
            try:
                lat, lng = float(f[15]), float(f[16])
            except (ValueError, IndexError):
                continue
            if LAT_RANGE[0]-0.1 <= lat <= LAT_RANGE[1]+0.1 and LNG_MIN <= lng <= -80.2:
                feats.append([f[1], f[2], lat, lng])   # name, class, lat, lng
    json.dump(feats, open(path, "w"))
    return feats

# --- geometry: distance (m) from a point OUTSIDE the rings to the ring edge ---
class Coast:
    def __init__(self, rings):
        self.rings = rings
        self.segs = []           # (x1,y1,x2,y2) in scaled-lng/lat degree space
        self.k = math.cos(math.radians(sum(LAT_RANGE)/2))
        lo, hi = LAT_RANGE[0]-0.3, LAT_RANGE[1]+0.3
        for r in rings:
            n = len(r)
            for i in range(0, n, 2):
                j = (i+2) % n
                y1, y2 = r[i+1], r[j+1]
                if max(y1, y2) < lo or min(y1, y2) > hi:
                    continue
                if max(r[i], r[j]) < LNG_MIN:
                    continue
                self.segs.append((r[i]*self.k, y1, r[j]*self.k, y2))
        self.grid = {}
        for s in self.segs:
            for gy in range(int(min(s[1], s[3])/0.05), int(max(s[1], s[3])/0.05)+1):
                self.grid.setdefault(gy, []).append(s)

    def dist_m(self, lng, lat):
        x, y = lng*self.k, lat
        best = 1e18
        for gy in (int(lat/0.05)-1, int(lat/0.05), int(lat/0.05)+1):
            for (x1, y1, x2, y2) in self.grid.get(gy, ()):  # noqa
                dx, dy = x2-x1, y2-y1
                t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((x-x1)*dx+(y-y1)*dy)/(dx*dx+dy*dy)))
                ex, ey = x1+t*dx-x, y1+t*dy-y
                d = ex*ex+ey*ey
                if d < best:
                    best = d
        return math.sqrt(best)*111320

    def inside(self, lng, lat):
        ins = False
        for r in self.rings:
            n = len(r)
            j = n-2
            for i in range(0, n, 2):
                xi, yi, xj, yj = r[i], r[i+1], r[j], r[j+1]
                if (yi > lat) != (yj > lat) and lng < (xj-xi)*(lat-yi)/(yj-yi)+xi:
                    ins = not ins
                j = i
        return ins

def t2ll(x, y, z):
    n = 2.0**z
    lng = x/n*360-180
    lat = math.degrees(math.atan(math.sinh(math.pi*(1-2*y/n))))
    return lng, lat

def ll2t(lng, lat, z):
    n = 2.0**z
    x = (lng+180)/360*n
    p = math.radians(lat)
    y = (1-math.log(math.tan(p)+1/math.cos(p))/math.pi)/2*n
    return x, y

def coast_tiles(coast, z):
    """Tiles whose bbox comes within the label strip of the coast."""
    m_per_px = 40075016.686*math.cos(math.radians(29.0))/(2**z*256)
    reach = PAD_M + TAIL_PX*m_per_px + 800       # seaward + slack
    cand = set()
    for (x1, y1, x2, y2) in coast.segs:
        steps = max(1, int(math.hypot(x2-x1, y2-y1)*111320/(128*m_per_px)))
        for s in range(steps+1):
            lng = (x1+(x2-x1)*s/steps)/coast.k
            lat = y1+(y2-y1)*s/steps
            if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1]):
                continue
            tx, ty = ll2t(lng, lat, z)
            r_t = reach/(m_per_px*256)+0.71
            for dx in range(-int(r_t)-1, int(r_t)+2):
                for dy in range(-int(r_t)-1, int(r_t)+2):
                    cand.add((int(tx)+dx, int(ty)+dy))
    # keep only tiles that hold any sea (a sample point outside the rings)
    # and aren't wholly beyond the label strip
    diag_m = 256*m_per_px*0.75
    out = []
    for (x, y) in cand:
        pts = [t2ll(x+fx, y+fy, z) for fx, fy in ((0.5, 0.5), (0, 0), (1, 0), (0, 1), (1, 1))]
        if not any(not coast.inside(lng, lat) for lng, lat in pts):
            continue
        if coast.dist_m(*pts[0]) - diag_m > reach:
            continue
        out.append((x, y))
    return sorted(out)

def fetch_tile(cache, z, x, y):
    path = os.path.join(cache, "tiles", str(z), f"{x}_{y}.png")
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        for attempt in range(4):
            try:
                d = urllib.request.urlopen(TILE_URL.format(z=z, y=y, x=x), timeout=40).read()
                Image.open(io.BytesIO(d)).convert("RGB").save(path)
                break
            except Exception:
                if attempt == 3:
                    return None
    try:
        return np.asarray(Image.open(path).convert("RGB"))
    except Exception:
        return None

def dim_fraction_map(coast, z, tx, ty, step=8):
    """Sampled map over the tile: 1 where the sea paint dims ink, 0 where not."""
    pts = np.zeros(((256//step)+1, (256//step)+1), dtype=bool)
    for gy in range(pts.shape[0]):
        for gx in range(pts.shape[1]):
            lng, lat = t2ll(tx+gx*step/256, ty+gy*step/256, z)
            if coast.inside(lng, lat):
                continue
            if coast.dist_m(lng, lat) > DIM_M:
                pts[gy, gx] = True
    return pts

def split_fine(g, cells):
    """Re-cluster one giant component's cells, connecting neighbours only when
    their actual ink bboxes come within 3 px — letters stay joined, dashes
    (>=6 px apart) fall apart."""
    gs = set(g)
    parent = {c: c for c in g}
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for (cx, cy) in g:
        b = cells[(cx, cy)]
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nb = (cx+dx, cy+dy)
                if nb == (cx, cy) or nb not in gs:
                    continue
                o = cells[nb]
                hgap = max(0, o[0]-b[1], b[0]-o[1])
                vgap = max(0, o[2]-b[3], b[2]-o[3])
                if hgap <= 3 and vgap <= 3:
                    ra, rb = find((cx, cy)), find(nb)
                    if ra != rb:
                        parent[ra] = rb
    sub = {}
    for c in g:
        sub.setdefault(find(c), []).append(c)
    out = []
    for s in sub.values():
        x0 = min(cells[c][0] for c in s); x1 = max(cells[c][1] for c in s)
        y0 = min(cells[c][2] for c in s); y1 = max(cells[c][3] for c in s)
        out.append([x0, y0, x1, y1, any(cells[c][4] for c in s)])
    return out

def scan_zoom(coast, gnis, cache, z, eraser_boxes):
    tiles = coast_tiles(coast, z)
    print(f"z{z}: {len(tiles)} tiles", flush=True)
    bright_px = {}
    dimmed = {}
    with ThreadPoolExecutor(8) as ex:
        arrs = list(ex.map(lambda t: fetch_tile(cache, z, *t), tiles))
    for (t, arr) in zip(tiles, arrs):
        if arr is None:
            continue
        mask = (arr.min(axis=2) >= BRIGHT)
        if not mask.any():
            continue
        ys, xs = np.nonzero(mask)
        bright_px[t] = (xs, ys)
        dm = dim_fraction_map(coast, z, t[0], t[1])
        dimmed[t] = dm[np.minimum(ys//8, dm.shape[0]-1), np.minimum(xs//8, dm.shape[1]-1)]
    # keep tiles that have dimmed ink, plus their 8-neighbours (cross-tile labels)
    hot = {t for t in bright_px if dimmed[t].any()}
    keep = set()
    for (x, y) in hot:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                keep.add((x+dx, y+dy))
    cells = {}
    for t in bright_px:
        if t not in keep:
            continue
        xs, ys = bright_px[t]
        gx = (t[0]*256+xs)//CELL
        gy = (t[1]*256+ys)//CELL
        di = dimmed[t]
        for i in range(len(xs)):
            c = cells.setdefault((int(gx[i]), int(gy[i])), [1e18, -1, 1e18, -1, False])
            px, py = t[0]*256+int(xs[i]), t[1]*256+int(ys[i])
            c[0] = min(c[0], px); c[1] = max(c[1], px)
            c[2] = min(c[2], py); c[3] = max(c[3], py)
            c[4] = c[4] or bool(di[i])
    # union-find over 8-neighbour cells
    parent = {c: c for c in cells}
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for (cx, cy) in cells:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nb = (cx+dx, cy+dy)
                if nb in cells:
                    ra, rb = find((cx, cy)), find(nb)
                    if ra != rb:
                        parent[ra] = rb
    groups = {}
    for c in cells:
        groups.setdefault(find(c), []).append(c)
    boxes = []
    for g in groups.values():
        x0 = min(cells[c][0] for c in g); x1 = max(cells[c][1] for c in g)
        y0 = min(cells[c][2] for c in g); y1 = max(cells[c][3] for c in g)
        dim = any(cells[c][4] for c in g)
        if x1-x0 > 310 or y1-y0 > 88:
            # a charted dash line chained everything within ~10 px into one
            # giant component, swallowing any label that touches it — split it
            # back apart at 2 px cells (dashes sit >=6 px apart, letters <=3)
            boxes.extend(split_fine(g, cells))
        else:
            boxes.append([x0, y0, x1, y1, dim])
    # merge word gaps (same line) and stacked lines (multi-line labels)
    merged = True
    while merged:
        merged = False
        out = []
        while boxes:
            b = boxes.pop()
            i = 0
            while i < len(boxes):
                o = boxes[i]
                vs = min(b[3], o[3])-max(b[1], o[1])   # vertical overlap
                hg = max(b[0], o[0])-min(b[2], o[2])   # horizontal gap
                hs = min(b[2], o[2])-max(b[0], o[0])   # horizontal overlap
                vg = max(b[1], o[1])-min(b[3], o[3])   # vertical gap
                u = [min(b[0], o[0]), min(b[1], o[1]), max(b[2], o[2]), max(b[3], o[3]), b[4] or o[4]]
                # size cap: never merge into something no label could be —
                # without it the charted dash lines chain into one giant box
                # that swallows every real label near them
                if ((vs > 4 and hg < 16) or (hs > 8 and vg < 10)) \
                        and u[2]-u[0] <= 310 and u[3]-u[1] <= 88:
                    b = u
                    boxes.pop(i)
                    merged = True
                else:
                    i += 1
            out.append(b)
        boxes = out
    labels, avoid, erase = [], [], []
    m_per_px = 40075016.686*math.cos(math.radians(29.0))/(2**z*256)
    for (x0, y0, x1, y1, dim) in boxes:
        w, h = x1-x0+1, y1-y0+1
        cx, cy = (x0+x1)/2, (y0+y1)/2
        lng, lat = t2ll(cx/256, cy/256, z)
        rec = {"box": [x0, y0, x1, y1], "lat": round(lat, 6), "lng": round(lng, 6), "w": w, "h": h}
        if not dim:
            continue
        if any(not (x1 < e[0] or x0 > e[2] or y1 < e[1] or y0 > e[3]) for e in eraser_boxes.get(z, [])):
            continue
        if any(math.hypot((lng-elo)*math.cos(math.radians(lat))*111320, (lat-ela)*110540) < r
               for (ela, elo, r) in EXCLUDE):
            erase.append(rec)
            continue
        text_like = 7 <= h <= 78 and 14 <= w <= 300 and w >= h*0.7
        best = None
        if text_like:
            # GNIS anchor sits near the box's west edge (USGS left-anchors);
            # allow it well west of the box: for a label half on land only the
            # dimmed tail clusters, so the anchor can sit ~140 px left of it
            for (name, cls, la, lo) in gnis:
                ax, ay = ll2t(lo, la, z)
                ax, ay = ax*256, ay*256
                if x0-140 <= ax <= x0+w*0.6 and y0-20 <= ay <= y1+20:
                    d = abs(ax-x0)+abs(ay-(y0+y1)/2)
                    if best is None or d < best[0]:
                        best = (d, name, cls, la, lo)
        # far-fetched matches are dash-line clusters that happened to sit near
        # some GNIS point (the county-line ink matched creeks 100+ px away) —
        # never window those
        if best and best[0] > 70:
            best = None
        if best:
            rec.update({"name": best[1], "cls": best[2], "d": round(best[0], 1)})
            labels.append(rec)
        else:
            avoid.append(rec)
    return labels, avoid, erase

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.makedirs(args.cache, exist_ok=True)
    rings = load_rings()
    coast = Coast(rings)
    gnis = load_gnis(args.cache)
    print(f"{len(coast.segs)} coast segments, {len(gnis)} GNIS features", flush=True)
    # v401 eraser rect ("Ponce Inlet" printed in the ocean) must never get a window
    src = open(INDEX, encoding="utf-8").read()
    em = re.search(r"const SEA_LABEL_ERASERS = \[(.*?)\];", src, re.S)
    eraser_boxes = {}
    for row in re.findall(r"\[([-0-9.,\s]+)\]", em.group(1)):
        v = [float(x) for x in row.split(",")]
        for z in range(int(v[5]), int(v[6])+1):
            ax, ay = ll2t(v[1], v[0], z)
            ax, ay = ax*256, ay*256
            eraser_boxes.setdefault(z, []).append([ax-v[2]-8, ay-v[4]-8, ax+v[3]+8, ay+v[4]+8])
    result = {}
    for z in ZOOMS:
        labels, avoid, erase = scan_zoom(coast, gnis, args.cache, z, eraser_boxes)
        result[str(z)] = {"labels": labels, "avoid": avoid, "erase": erase}
        print(f"z{z}: {len(labels)} dimmed labels, {len(avoid)} avoid, {len(erase)} erase", flush=True)
        for L in labels:
            print("   ", L["name"], L["w"], "x", L["h"], "@", L["lat"], L["lng"], flush=True)
    json.dump(result, open(os.path.join(args.out, "sea_label_scan.json"), "w"), indent=1)

if __name__ == "__main__":
    main()
