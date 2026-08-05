#!/usr/bin/env python
"""Pass A: coarse (≈37 m) connected water mask for the WTF depth-contour build.

CUDEM is a *topobathy* DEM — it carries land as well as seafloor, and plenty of
inland Florida (borrow pits, marsh, canals, retention ponds) sits below the
NAVD88 zero we use as the water datum.  A plain elev<0 test would therefore
sprinkle depth contours across pastures.  So: build one coarse water mask over
the whole area, keep only the components that actually touch BlueTopo's
navigable-water coverage, and use that as a gate in pass B.
"""
import glob, warnings
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling, transform_bounds
from rasterio.transform import from_origin
from scipy import ndimage

warnings.filterwarnings('ignore')

DATA = '/Users/janneal/Desktop/WTF Files/depth-data'
OUT  = '/private/tmp/claude-501/-Users-janneal/43d5b7c7-e9a2-4d91-ae08-90e9492cba43/scratchpad/watermask_coarse.npz'

# The app's own fishing-area box (OFFLINE_BBOX in index.html), so the contour
# layer can never extend past the imagery Jan pre-caches.
W, E, S, N = -81.20, -80.30, 28.40, 29.48
STEP = 1.0 / 3000.0            # ≈ 37 m — fine enough to keep creeks connected
WATER_M = -0.15                # metres NAVD88; below this is water

nx = int(round((E - W) / STEP))
ny = int(round((N - S) / STEP))
dst_tf = from_origin(W, N, STEP, STEP)
print('coarse grid', nx, 'x', ny)

# --- BlueTopo presence (navigable water, the seed for connectivity) ----------
bt_seed = np.zeros((ny, nx), bool)
bts = sorted(glob.glob(DATA + '/bluetopo/*.tiff'))
for i, f in enumerate(bts):
    with rasterio.open(f) as d:
        b = transform_bounds(d.crs, 'EPSG:4326', *d.bounds)
        if b[2] < W or b[0] > E or b[3] < S or b[1] > N:
            continue
        src = d.read(1)
        tmp = np.full((ny, nx), np.nan, np.float32)
        reproject(src, tmp, src_transform=d.transform, src_crs=d.crs,
                  src_nodata=np.nan, dst_transform=dst_tf, dst_crs='EPSG:4326',
                  dst_nodata=np.nan, resampling=Resampling.min)
        bt_seed |= np.isfinite(tmp)
    if (i + 1) % 10 == 0:
        print('  bluetopo', i + 1, '/', len(bts))
print('bluetopo seed cells', int(bt_seed.sum()))

# --- CUDEM elevation, min-resampled so narrow channels survive --------------
cu_elev = np.full((ny, nx), 9999.0, np.float32)
cus = sorted(glob.glob(DATA + '/cudem/*.tif'))
for f in cus:
    with rasterio.open(f) as d:
        b = d.bounds
        if b[2] < W or b[0] > E or b[3] < S or b[1] > N:
            continue
        src = d.read(1).astype(np.float32)
        src[src <= -9000] = 9999.0
        tmp = np.full((ny, nx), 9999.0, np.float32)
        reproject(src, tmp, src_transform=d.transform, src_crs=d.crs,
                  src_nodata=9999.0, dst_transform=dst_tf, dst_crs='EPSG:4326',
                  dst_nodata=9999.0, resampling=Resampling.min)
        cu_elev = np.minimum(cu_elev, tmp)
    print('  cudem', f.split('/')[-1])

wet = bt_seed | (cu_elev < WATER_M)
print('wet cells', int(wet.sum()))

# Close one-cell gaps so a bridge or a causeway pixel doesn't sever a lagoon.
wet_c = ndimage.binary_closing(wet, np.ones((3, 3), bool))
lab, n = ndimage.label(wet_c, np.ones((3, 3), int))
print('components', n)
keep = np.unique(lab[bt_seed & (lab > 0)])
print('components touching BlueTopo', len(keep))
mask = np.isin(lab, keep) & wet_c
# Grow it back a touch — pass B works at ~7 m, and the gate must not clip the
# real shoreline off the fine grid.
mask = ndimage.binary_dilation(mask, np.ones((3, 3), bool), iterations=2)
print('gate cells', int(mask.sum()), '(%.1f%%)' % (100.0 * mask.mean()))

np.savez_compressed(OUT, mask=np.packbits(mask), shape=np.array([ny, nx]),
                    bbox=np.array([W, S, E, N]), step=np.array([STEP]))
print('wrote', OUT)
