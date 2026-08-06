#!/usr/bin/env python
"""Pass B: depth contours in FEET at MLLW for the WTF app.

BlueTopo (4 m / 8 m, the "best available" compiled bathymetry, 2022 IRL lidar
included) is authoritative; CUDEM 1/9" topobathy fills the shallows BlueTopo
does not reach, blended across BlueTopo's edge so the seam doesn't ladder.
Both are metres on NAVD88, so no vertical shift is needed between them.

DATUM (changed 2026-08-06, WTF v458 / board build 16).  The grids are NAVD88 and
always will be; what changed is the datum the LINES ARE CUT AT.  Through v457
the levels were integer feet below NAVD88 — near enough average water level —
so a line marked "6 ft" held about 3.75 ft at dead low and the app had to say so
in its help.  Jan's phone chart and the tide board both read MLLW, so one spot
showed three numbers and only WTF's needed arithmetic on the water.

The fix is NOT a relabel: subtracting 2.25 from an integer NAVD88 level lands on
a quarter foot (6 -> 3.75) and sends the two shallowest lines negative
(1 -> -1.25), so there is nothing honest to print.  Instead every level is CUT at
`label + NAVD88_ABOVE_MLLW` in NAVD88 feet and STORED as the label.  A "3 ft"
line is cut at 5.25 ft below NAVD88 and written to the block as 3.

Because the label SET is unchanged, nothing downstream had to move: the app's
tier table, DEPTH_TIER_PROMOTE (the fathom-curve promotion), DEPTH_WIDE_LEVELS,
DEPTH_MIN_PX and the label sort's `lv % 5` round-number preference are all keyed
on these same integers and keep their meaning.  Keep it that way — if a future
build changes the label set, walk that list in index.html first.

Two consequences that are correct but visible:
  * The old 1 and 2 ft NAVD88 lines have no MLLW label (that bottom dries at low
    water) and simply cease to exist.  Shorelines carry fewer lines now.
  * Every label inherits roughly the geometry of the line 2-3 ft deeper than the
    one that used to wear it, so the shallow lines sit further off the bank.

Output: one JSON block per 0.25 degree, delta-encoded integer polylines.
"""
import json, os, glob, warnings, math, sys
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling, transform_bounds
from rasterio.transform import from_origin
from rasterio.windows import from_bounds as win_from_bounds
from scipy import ndimage
from contourpy import contour_generator, LineType

warnings.filterwarnings('ignore')

DATA = '/Users/janneal/Desktop/WTF Files/depth-data'
HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(HERE, 'depth_out')
M2FT = 3.280839895

AOI = dict(w=-81.20, e=-80.30, s=28.40, n=29.48)   # index.html OFFLINE_BBOX
BLOCK = 0.25
MARGIN = 0.01                  # contour with a skirt so block seams line up
STEP = 1.0 / 16000.0           # ≈ 7 m
SIGMA = 2.5                    # cells of gaussian smoothing (~17 m)
BLEND_CELLS = 15               # BlueTopo→CUDEM feather at BlueTopo's edge
RDP_TOL_DEG = 2.0 / 111320.0   # ≈ 2 m — under one z16 pixel
MIN_LEN_DEG = 60.0 / 111320.0  # drop noise specks shorter than 60 m
# A contour cut close to the drying edge runs along the waterline, where a flat's
# own ripple breaks it into thousands of hairs; those have to earn their place
# with length.  The threshold is on the CUT depth below NAVD88, not on the label,
# because the edge sits at NAVD88 zero and that is what the rule is about.  Under
# the old NAVD88 labels this caught the 1 and 2 ft lines; at MLLW the shallowest
# line is cut 3.25 ft down and no longer hugs the bank, so it is expected to
# catch nothing — kept, correctly expressed, because it costs nothing and the
# next person to add a shallower level will need it.
MIN_LEN_SHOAL = 160.0 / 111320.0
SHOAL_CUT_FT = 2.0
Q = 100000                     # coordinate quantum: 1e-5 deg ≈ 1.1 m

# NOAA station 8721138 (Ponce de Leon Inlet) published datums: MLLW 2.94 ft,
# NAVD88 5.19 ft on the station datum, so NAVD88 stands 2.25 ft ABOVE chart
# datum.  MEASURED, not a guess, and LOCAL: if this layer ever reaches another
# tide station, re-read that station's own datums before assuming it holds.
# The app and the tide board carry the same constant.
NAVD88_ABOVE_MLLW = 2.25

# Feet levels — LABELS, at MLLW.  Each is cut at label + NAVD88_ABOVE_MLLW feet
# below NAVD88 and stored as the label; see the datum note at the top.
# 1 ft steps through the lagoon range, opening out offshore.
# tier 0 draws from z11, tier 1 from z13, tier 2 from z14, tier 3 from z15.
# The 3 ft line is the busiest thing in this water, so it is NOT in tier 0: at
# z12 the Halifax is ten pixels wide and its own 3 ft wiggle filled it solid.
# 4 ft IS in tier 0 (v408).  The shallow west-side bays — Turnbull, Rose,
# Strickland, Tomoka Basin — run 2-3 ft over most of their area and so had
# nothing at all to show until z13; 4 ft is the shallowest line that draws them
# as an outline.  It is one step off 3 ft but a far quieter line: it sits out in
# open basin water rather than along the ripple at the water's edge, and the
# screen-length cull (DEPTH_MIN_PX in the app) keeps it off the narrow Halifax.
TIERS = {
    0: [4, 6, 12, 20, 30, 50, 100, 200],
    1: [3, 9, 16, 25, 40, 60, 80, 150],
    2: [2, 8, 10, 14, 18, 35, 70],
    3: [1, 5, 7, 11, 90, 120, 140, 160, 180],
}
LEVEL_TIER = {lv: t for t, lvs in TIERS.items() for lv in lvs}
LEVELS = sorted(LEVEL_TIER)

# ---------------------------------------------------------------- water gate
_wm = np.load(os.path.join(HERE, 'watermask_coarse.npz'))
WM_SHAPE = tuple(int(v) for v in _wm['shape'])
WM = np.unpackbits(_wm['mask'])[:WM_SHAPE[0] * WM_SHAPE[1]].reshape(WM_SHAPE).astype(bool)
WM_BBOX = _wm['bbox']            # W,S,E,N
WM_STEP = float(_wm['step'][0])


def gate_for(w, s, e, n, nx, ny):
    """Nearest-neighbour lift of the coarse connected-water gate onto a fine grid."""
    lons = w + (np.arange(nx) + 0.5) * ((e - w) / nx)
    lats = n - (np.arange(ny) + 0.5) * ((n - s) / ny)
    ci = np.clip(((lons - WM_BBOX[0]) / WM_STEP).astype(int), 0, WM_SHAPE[1] - 1)
    ri = np.clip(((WM_BBOX[3] - lats) / WM_STEP).astype(int), 0, WM_SHAPE[0] - 1)
    return WM[np.ix_(ri, ci)]


# ---------------------------------------------------------------- source index
def index_sources():
    bt = []
    for f in sorted(glob.glob(DATA + '/bluetopo/*.tiff')):
        with rasterio.open(f) as d:
            bt.append((f, transform_bounds(d.crs, 'EPSG:4326', *d.bounds), d.res[0]))
    cu = []
    for f in sorted(glob.glob(DATA + '/cudem/*.tif')):
        with rasterio.open(f) as d:
            cu.append((f, tuple(d.bounds)))
    # finest BlueTopo last, so 4 m overwrites 8 m where they overlap
    bt.sort(key=lambda t: -t[2])
    return bt, cu


BT, CU = index_sources()


def read_into(path, bbox, dst, dst_tf, nodata_in, fill, geographic):
    """Windowed read of `path` reprojected into `dst` (EPSG:4326). True if any data."""
    w, s, e, n = bbox
    with rasterio.open(path) as d:
        if geographic:
            win = win_from_bounds(w, s, e, n, d.transform)
        else:
            xs, ys = rasterio.warp.transform('EPSG:4326', d.crs,
                                             [w, e, e, w], [s, s, n, n])
            win = win_from_bounds(min(xs), min(ys), max(xs), max(ys), d.transform)
        win = win.round_offsets().round_lengths()
        win = win.intersection(rasterio.windows.Window(0, 0, d.width, d.height))
        if win.width < 2 or win.height < 2:
            return False
        src = d.read(1, window=win).astype(np.float32)
        if nodata_in is not None:
            src[src <= nodata_in] = np.nan
        if not np.isfinite(src).any():
            return False
        tmp = np.full(dst.shape, np.nan, np.float32)
        reproject(src, tmp, src_transform=d.window_transform(win), src_crs=d.crs,
                  src_nodata=np.nan, dst_transform=dst_tf, dst_crs='EPSG:4326',
                  dst_nodata=np.nan, resampling=Resampling.bilinear)
        ok = np.isfinite(tmp)
        if not ok.any():
            return False
        dst[ok] = tmp[ok]
        return True


# ---------------------------------------------------------------- geometry
def rdp(pts, tol):
    """Ramer–Douglas–Peucker, iterative so a 100k-point contour can't blow the stack."""
    n = len(pts)
    if n < 3:
        return pts
    keep = np.zeros(n, bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        seg = pts[a + 1:b]
        pa, pb = pts[a], pts[b]
        d = pb - pa
        L2 = d[0] * d[0] + d[1] * d[1]
        if L2 == 0:
            dist = np.hypot(seg[:, 0] - pa[0], seg[:, 1] - pa[1])
        else:
            t = np.clip(((seg - pa) @ d) / L2, 0, 1)
            proj = pa + t[:, None] * d
            dist = np.hypot(seg[:, 0] - proj[:, 0], seg[:, 1] - proj[:, 1])
        i = int(np.argmax(dist))
        if dist[i] > tol:
            k = a + 1 + i
            keep[k] = True
            stack.append((a, k))
            stack.append((k, b))
    return pts[keep]


def clip_to_box(pts, w, s, e, n):
    """Split a polyline into the runs that fall inside the box, keeping one
    point of overhang on each side so the line still reaches the edge."""
    inside = (pts[:, 0] >= w) & (pts[:, 0] <= e) & (pts[:, 1] >= s) & (pts[:, 1] <= n)
    if inside.all():
        return [pts]
    if not inside.any():
        return []
    out, i, n_ = [], 0, len(pts)
    while i < n_:
        if not inside[i]:
            i += 1
            continue
        j = i
        while j + 1 < n_ and inside[j + 1]:
            j += 1
        a = max(0, i - 1)
        b = min(n_ - 1, j + 1)
        out.append(pts[a:b + 1])
        i = j + 1
    return out


def encode(pts, w, s):
    xs = np.round((pts[:, 0] - w) * Q).astype(int)
    ys = np.round((pts[:, 1] - s) * Q).astype(int)
    # collapse points that quantise onto each other
    keep = np.ones(len(xs), bool)
    keep[1:] = (np.diff(xs) != 0) | (np.diff(ys) != 0)
    xs, ys = xs[keep], ys[keep]
    if len(xs) < 2:
        return None
    out = [int(xs[0]), int(ys[0])]
    dx = np.diff(xs)
    dy = np.diff(ys)
    for a, b in zip(dx.tolist(), dy.tolist()):
        out.append(a)
        out.append(b)
    return out


# ---------------------------------------------------------------- per block
def do_block(bw, bs):
    be, bn = bw + BLOCK, bs + BLOCK
    # clipped output bounds: the block ∩ the app's fishing area
    cw, ce = max(bw, AOI['w']), min(be, AOI['e'])
    cs, cn = max(bs, AOI['s']), min(bn, AOI['n'])
    if cw >= ce or cs >= cn:
        return None
    gw, gs, ge, gn = bw - MARGIN, bs - MARGIN, be + MARGIN, bn + MARGIN
    nx = int(round((ge - gw) / STEP))
    ny = int(round((gn - gs) / STEP))
    tf = from_origin(gw, gn, STEP, STEP)

    bt = np.full((ny, nx), np.nan, np.float32)
    got_bt = False
    for f, b, _ in BT:
        if b[2] < gw or b[0] > ge or b[3] < gs or b[1] > gn:
            continue
        got_bt |= read_into(f, (gw, gs, ge, gn), bt, tf, None, np.nan, False)
    cu = np.full((ny, nx), np.nan, np.float32)
    got_cu = False
    for f, b in CU:
        if b[2] < gw or b[0] > ge or b[3] < gs or b[1] > gn:
            continue
        got_cu |= read_into(f, (gw, gs, ge, gn), cu, tf, -9000.0, np.nan, True)
    if not (got_bt or got_cu):
        return None

    bt_ok = np.isfinite(bt)
    cu_ok = np.isfinite(cu)

    # BlueTopo wins; CUDEM fills.  Feather across BlueTopo's rim wherever CUDEM
    # is there to blend with, so the two surveys don't step against each other.
    elev = np.where(bt_ok, bt, np.where(cu_ok, cu, np.nan)).astype(np.float32)
    if bt_ok.any() and cu_ok.any():
        d_in = ndimage.distance_transform_edt(bt_ok)
        band = bt_ok & cu_ok & (d_in < BLEND_CELLS)
        if band.any():
            wgt = (d_in[band] / BLEND_CELLS).astype(np.float32)
            elev[band] = wgt * bt[band] + (1.0 - wgt) * cu[band]

    valid = np.isfinite(elev)
    water = valid & (elev < 0.0) & gate_for(gw, gs, ge, gn, nx, ny)
    # BlueTopo only maps navigable water, so anything it surveyed is water even
    # if it rounds to a hair above zero.
    water |= bt_ok & (bt < 0.15) & gate_for(gw, gs, ge, gn, nx, ny)
    if water.sum() < 500:
        return None

    depth = np.where(water, -elev * M2FT, np.nan).astype(np.float32)

    # Smooth through the NaNs (nan-aware gaussian) so the land edge doesn't
    # drag the shallow contours seaward.
    filled = np.nan_to_num(depth, nan=0.0)
    wts = water.astype(np.float32)
    num = ndimage.gaussian_filter(filled, SIGMA, mode='nearest')
    den = ndimage.gaussian_filter(wts, SIGMA, mode='nearest')
    with np.errstate(invalid='ignore', divide='ignore'):
        sm = num / den
    sm[~water] = np.nan
    sm[den < 0.15] = np.nan

    xs = gw + (np.arange(nx) + 0.5) * STEP
    ys = gn - (np.arange(ny) + 0.5) * STEP
    zm = np.ma.masked_invalid(sm)
    cg = contour_generator(x=xs, y=ys, z=zm, line_type=LineType.Separate,
                           corner_mask=True, chunk_size=0)

    lines = []
    for lv in LEVELS:
        # lv is the MLLW label; cut is where that depth actually sits in the
        # NAVD88 grid.  Only the label is ever written to the block.
        cut = lv + NAVD88_ABOVE_MLLW
        if cut > np.nanmax(sm) or cut < np.nanmin(sm):
            continue
        tier = LEVEL_TIER[lv]
        for seg in cg.lines(float(cut)):
            seg = np.asarray(seg, float)
            if len(seg) < 3:
                continue
            for part in clip_to_box(seg, cw, cs, ce, cn):
                if len(part) < 3:
                    continue
                d = np.diff(part, axis=0)
                lim = MIN_LEN_SHOAL if cut <= SHOAL_CUT_FT else MIN_LEN_DEG
                if float(np.hypot(d[:, 0], d[:, 1]).sum()) < lim:
                    continue
                sp = rdp(part, RDP_TOL_DEG)
                enc = encode(sp, cw, cs)
                if enc:
                    lines.append([int(lv), tier] + enc)
    if not lines:
        return None
    return dict(b=[round(cw, 6), round(cs, 6), round(ce, 6), round(cn, 6)],
                q=Q, L=lines)


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    blocks = []
    lon0 = math.floor(AOI['w'] / BLOCK) * BLOCK
    lat0 = math.floor(AOI['s'] / BLOCK) * BLOCK
    bw = lon0
    while bw < AOI['e']:
        bs = lat0
        while bs < AOI['n']:
            blocks.append((round(bw, 4), round(bs, 4)))
            bs += BLOCK
        bw += BLOCK
    only = sys.argv[1:] or None
    index = []
    for bw, bs in blocks:
        key = 'c%d_%d' % (round((bw + 82) / BLOCK), round((bs - 28) / BLOCK))
        if only and key not in only:
            continue
        res = do_block(bw, bs)
        if not res:
            print(key, 'empty')
            continue
        path = os.path.join(OUTDIR, key + '.json')
        with open(path, 'w') as fh:
            json.dump(res, fh, separators=(',', ':'))
        kb = os.path.getsize(path) / 1024.0
        print('%s  %5d lines  %7.0f KB' % (key, len(res['L']), kb))
        index.append(dict(k=key, b=res['b'], n=len(res['L'])))
    if not only:
        with open(os.path.join(OUTDIR, 'index.json'), 'w') as fh:
            json.dump(dict(blocks=index, tiers=TIERS), fh, separators=(',', ':'))
    print('done')


if __name__ == '__main__':
    main()
