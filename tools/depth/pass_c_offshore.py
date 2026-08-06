#!/usr/bin/env python
"""Pass C: OFFSHORE depth contours for the WTF app (v407).

Everything east of the inshore build's edge (-80.30) out to -79.20, i.e. the
nearshore Atlantic, the reef grounds, the shelf break at the Steeples /
Rolldown and the Gulf Stream slope down onto the Blake Plateau (~3000 ft).

Deliberately a separate pass from pass_b_contours.py so the inshore blocks
cannot move: the lagoon design is settled and those files are byte-frozen.

DATUM: MLLW since 2026-08-06, exactly as in pass B — every level is cut at
`label + PB.NAVD88_ABOVE_MLLW` feet below NAVD88 and stored as the label.  This
pass had to move in the same change even though 2.25 ft is nothing on a 400 ft
slope: INSHORE_KEEP below carries every inshore level <= 200 ft through verbatim
so the lines run across the -80.30 seam without a step, and if the two passes cut
at different datums that seam breaks right off the beach — a 12 ft line arriving
from the lagoon at 9.75 ft of real water meeting a 12 ft line at 12.

Differences from inshore:
  * BlueTopo only.  CUDEM does not reach out here, and BlueTopo *is* the water
    mask offshore — it only maps navigable water — so the coarse connected-water
    gate (which exists to keep contours out of Volusia's borrow pits) is not
    needed and is not applied.
  * Coarser grids, matched to the source: 8 m tiles inshore of -79.80, 16 m
    beyond.  Contouring a 16 m tile on a 7 m grid only manufactures wiggle.
  * Levels: every inshore level <= 200 ft is kept, so the lines run straight
    through the -80.30 seam without a step, plus a deep set above 200 ft that
    opens out as the bottom falls away.
  * Harder simplification and longer minimum lengths, because the deep contours
    are long and there are a lot of them.
"""
import json, os, sys, warnings
import numpy as np
import rasterio
from rasterio.transform import from_origin
from scipy import ndimage
from contourpy import contour_generator, LineType

warnings.filterwarnings('ignore')

import pass_b_contours as PB   # BT index, read_into, rdp, clip_to_box, encode

HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(HERE, 'depth_out')
M2FT = 3.280839895
Q = PB.Q

# Explicit boxes, not a plain 0.25 grid: the west column starts at -80.30 so it
# butts exactly onto the inshore c6 column's east edge — no gap, no overlap.
COLS = [('c7', -80.30, -80.00), ('c8', -80.00, -79.75),
        ('c9', -79.75, -79.50), ('c10', -79.50, -79.20)]
ROWS = [(1, 28.40, 28.50), (2, 28.50, 28.75), (3, 28.75, 29.00),
        (4, 29.00, 29.25), (5, 29.25, 29.48)]
# ...plus the two c6 boxes the v405 build left blank. The Atlantic off Canaveral
# had no BlueTopo in that build, so its water never entered the coarse gate and
# the blocks came out empty; the 2026-08-04 pull covers it, and building it here
# — BlueTopo-only, gate-free — fills the hole without touching the gate that
# every inshore block already depends on.
EXTRA = [('c6_1', -80.50, 28.40, -80.30, 28.50),
         ('c6_2', -80.50, 28.50, -80.30, 28.75)]

MARGIN = 0.012

# Inshore levels (<=200 ft) carried through verbatim, with their inshore tiers,
# so the seam at -80.30 is continuous.
INSHORE_KEEP = {lv: t for lv, t in PB.LEVEL_TIER.items() if lv <= 200}

# Deep set.  Tight through 200-400 ft, which is where the ledges the offshore
# pins mark actually live, then opening out so the Gulf Stream slope stays a set
# of lines instead of a solid smear.
DEEP_TIERS = {
    0: [250, 300, 400, 600, 900, 1500, 2400],
    1: [220, 350, 500, 700, 1200, 1800, 2700],
    2: [260, 325, 450, 550, 800, 1000, 1350, 2100, 3000],
    3: [210, 230, 240, 275, 375, 425, 475, 650, 750, 850, 950, 1100,
        1650, 1950, 2250, 2550, 2850],
}
LEVEL_TIER = dict(INSHORE_KEEP)
for t, lvs in DEEP_TIERS.items():
    for lv in lvs:
        LEVEL_TIER[lv] = t
LEVELS = sorted(LEVEL_TIER)


def grid_step(cw):
    """8 m BlueTopo runs out at -79.80; past it the 16 m shelf tiles are all
    there is, and a fine grid would only sharpen their own sampling noise."""
    if cw < -80.30:
        return 1.0 / 16000.0                                    # 4 m tiles, ~7 m
    return (1.0 / 12000.0) if cw < -79.80 else (1.0 / 6000.0)   # ~9 m / ~19 m


def sigma_for(cw):
    """Cells of gaussian. The 16 m shelf tiles cover a plateau that is nearly
    flat at 2400-2800 ft, where an unsmoothed contour wanders for miles and
    breaks into hair; smooth them harder than the 8 m ledge tiles, where the
    wiggle in the line IS the ledge."""
    return 5.0 if cw >= -79.80 else 3.0


def tol_for(lv):
    """Simplification tolerance, degrees. A 2500 ft contour is a shape, not a
    survey: nobody navigates it, and every kept vertex is bytes on a phone."""
    if lv <= 200:
        return 6.0 / 111320.0
    if lv <= 500:
        return 12.0 / 111320.0
    return 30.0 / 111320.0


def minlen_for(lv):
    if lv <= 500:
        return 250.0 / 111320.0
    # Deeper than 1500 ft the bottom is nearly flat and a short contour is a
    # sampling artefact, not a feature.
    return (500.0 if lv <= 1500 else 900.0) / 111320.0


def do_block(cw, cs, ce, cn):
    gw, gs, ge, gn = cw - MARGIN, cs - MARGIN, ce + MARGIN, cn + MARGIN
    step = grid_step(cw)
    nx = int(round((ge - gw) / step))
    ny = int(round((gn - gs) / step))
    tf = from_origin(gw, gn, step, step)

    bt = np.full((ny, nx), np.nan, np.float32)
    got = False
    for f, b, _ in PB.BT:
        if b[2] < gw or b[0] > ge or b[3] < gs or b[1] > gn:
            continue
        got |= PB.read_into(f, (gw, gs, ge, gn), bt, tf, None, np.nan, False)
    if not got:
        return None
    bt[bt < -11000.0] = np.nan          # BlueTopo sentinel guard

    # BlueTopo only maps navigable water, so its coverage is the water mask.
    water = np.isfinite(bt) & (bt < 0.15)
    if water.sum() < 2000:
        return None
    depth = np.where(water, -bt * M2FT, np.nan).astype(np.float32)

    filled = np.nan_to_num(depth, nan=0.0)
    wts = water.astype(np.float32)
    sig = sigma_for(cw)
    num = ndimage.gaussian_filter(filled, sig, mode='nearest')
    den = ndimage.gaussian_filter(wts, sig, mode='nearest')
    with np.errstate(invalid='ignore', divide='ignore'):
        sm = num / den
    sm[~water] = np.nan
    sm[den < 0.15] = np.nan

    lo, hi = float(np.nanmin(sm)), float(np.nanmax(sm))
    xs = gw + (np.arange(nx) + 0.5) * step
    ys = gn - (np.arange(ny) + 0.5) * step
    cg = contour_generator(x=xs, y=ys, z=np.ma.masked_invalid(sm),
                           line_type=LineType.Separate, corner_mask=True,
                           chunk_size=0)

    lines = []
    for lv in LEVELS:
        # MLLW label -> where it sits in the NAVD88 grid.  Only the label ships.
        cut = lv + PB.NAVD88_ABOVE_MLLW
        if cut > hi or cut < lo:
            continue
        tier = LEVEL_TIER[lv]
        tol, lim = tol_for(lv), minlen_for(lv)
        for seg in cg.lines(float(cut)):
            seg = np.asarray(seg, float)
            if len(seg) < 3:
                continue
            for part in PB.clip_to_box(seg, cw, cs, ce, cn):
                if len(part) < 3:
                    continue
                d = np.diff(part, axis=0)
                if float(np.hypot(d[:, 0], d[:, 1]).sum()) < lim:
                    continue
                enc = PB.encode(PB.rdp(part, tol), cw, cs)
                if enc:
                    lines.append([int(lv), tier] + enc)
    if not lines:
        return None
    return dict(b=[round(cw, 6), round(cs, 6), round(ce, 6), round(cn, 6)],
                q=Q, L=lines, _lo=lo, _hi=hi)


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    only = sys.argv[1:] or None
    index = []
    todo = [('%s_%d' % (cn_, rn), cw, cs, ce, cnn)
            for cn_, cw, ce in COLS for rn, cs, cnn in ROWS] + EXTRA
    for key, cw, cs, ce, cnn in todo:
        if only and key not in only:
            continue
        res = do_block(cw, cs, ce, cnn)
        if not res:
            print(key, 'empty')
            continue
        lo, hi = res.pop('_lo'), res.pop('_hi')
        path = os.path.join(OUTDIR, key + '.json')
        with open(path, 'w') as fh:
            json.dump(res, fh, separators=(',', ':'))
        kb = os.path.getsize(path) / 1024.0
        print('%-6s %5d lines %8.0f KB   depth %.0f-%.0f ft'
              % (key, len(res['L']), kb, lo, hi))
        index.append(dict(k=key, b=res['b'], n=len(res['L'])))
    with open(os.path.join(OUTDIR, 'index_offshore.json'), 'w') as fh:
        json.dump(dict(blocks=index, tiers=DEEP_TIERS), fh, separators=(',', ':'))
    print('done')


if __name__ == '__main__':
    main()
