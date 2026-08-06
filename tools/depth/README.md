# Depth-contour pipeline

These are the scripts that generated `depth/*.json` — the contour blocks the app
fetches for its depth layer. They ran once, from a session scratchpad, on
2026-08-04; they are saved here because that scratchpad lives in `/private/tmp`
and macOS clears it. Nothing in the app runs them: `depth/` is a committed
build product, and these only matter if it ever has to be rebuilt or extended.

Copied verbatim from the run that produced the shipped data — see "Paths to fix"
below before running any of them again.

## The passes

| Script | What it does |
|---|---|
| `pass_a_watermask.py` | Builds one coarse (~37 m) connected water mask over the inshore area and keeps only components touching BlueTopo's navigable-water coverage. This is the gate that stops CUDEM's sub-zero *inland* ground — borrow pits, marsh, retention ponds — from sprouting depth contours across pastures. Output: `watermask_coarse.npz` (saved alongside; 30 KB, regenerable). |
| `pass_b_contours.py` | The inshore build, blocks `c3_*`–`c6_*`. BlueTopo authoritative, CUDEM feathered in across BlueTopo's edge (15 cells) for the shallows it doesn't reach; both are metres NAVD88 so no vertical shift. ~7 m grid, gaussian smoothed, RDP-simplified to ~2 m, emitted as delta-encoded integer polylines at 1e-5° quantum, one JSON per 0.25°. |
| `survey_vintage.py` | **Not part of the build** — asks how OLD the bottom under these contours is, which nothing else here records. Fetches each tile's BlueTopo raster attribute table (small, and still available with the source GeoTIFFs deleted) and separates measured cells from `.interpolated` fill by survey and date. `--md` regenerates `SURVEY_VINTAGE.md`. Reads `depth-data/bluetopo_tiles.json` on the Desktop; caches RATs in `.rat_cache/` (gitignored, re-fetchable). |
| `pass_c_offshore.py` | The v407 offshore build, blocks `c7_*`–`c8_*`, from −80.30 east to −79.20. **Imports `pass_b_contours` as a module** for its BlueTopo index, readers, RDP and encoder — keep the two files in the same directory. BlueTopo only (CUDEM doesn't reach; BlueTopo *is* the water mask offshore, so pass A's gate isn't applied). Coarser grids matched to the source: 8 m tiles inshore of −79.80, 16 m beyond. Deliberately separate from pass B so the settled lagoon blocks stay byte-frozen. |

`rebuild_b.log` is the pass-B run log — per-block line counts and sizes, useful
as a regression check that a rebuild produced roughly the same thing.

## Paths to fix before re-running

Both are absolute in the scripts as saved:

- `DATA = '/Users/janneal/Desktop/WTF Files/depth-data'` — the source rasters.
  **These were deleted on 2026-08-04** once the contours shipped; that folder's
  README carries the re-fetch recipe for both the BlueTopo tiles (URLs in
  `bluetopo_tiles.json`) and the 8 CUDEM tiles. Re-pull before running.
- `pass_a_watermask.py`'s `OUT` still points at the original scratchpad path,
  which no longer exists. Point it at this directory.
- `OUTDIR` in passes B and C is `depth_out/` next to the script — the run
  wrote there and the blocks were copied into `depth/` afterwards, not written
  in place. Keep that habit; it makes a rebuild diffable against the shipped set.

## Environment

Python 3.14 venv (the scratchpad venv was not kept):

```
pip install rasterio==1.5.0 numpy==2.5.1 scipy==1.18.0 contourpy==1.3.3
```

## After any rebuild

**Bump `DEPTH_DATA_V` in `index.html`.** Blocks are fetched cache-first through
the tile cache, so without a bump every device that has already seen the old
blocks serves them forever.
