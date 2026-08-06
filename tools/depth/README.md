# Depth-contour pipeline

These are the scripts that generated `depth/*.json` — the contour blocks the app
fetches for its depth layer. Nothing in the app runs them: `depth/` is a
committed build product, and these only matter if it ever has to be rebuilt or
extended.

## The datum (read this first)

**The lines are cut at MLLW since 2026-08-06 (WTF v458 / tide board build 16).**
Before that they were integer feet below NAVD88, which stands **2.25 ft above
MLLW** at Ponce — so a "6 ft" line held about 3.75 ft at dead low and the app's
help had to teach the subtraction, while Jan's phone chart and the tide board
both already read MLLW.

It could not be fixed by relabelling: subtracting 2.25 from an integer NAVD88
level lands on a quarter foot (6 → 3.75) and sends the two shallowest negative
(1 → −1.25). So each level is now **cut at `label + NAVD88_ABOVE_MLLW` feet
below NAVD88 and stored as the label** — a 3 ft line is contoured at 5.25 and
written to the block as `3`. The grids are still NAVD88 and always will be;
only the cut moved.

Two rules that fall out of this and must survive any future edit:

- **Keep the label set.** The app's tier table, `DEPTH_TIER_PROMOTE`,
  `DEPTH_WIDE_LEVELS`, `DEPTH_MIN_PX` and the label sort's `lv % 5` preference
  are all keyed on these integers. Change the set and every one of those needs
  a second look.
- **Passes B and C move together.** Pass C carries every inshore level ≤ 200 ft
  through verbatim so the lines cross the −80.30 seam without a step. Cut the
  two passes at different datums and the seam breaks right off the beach.

The 2026-08-06 rebuild: 29 blocks, 10,886 lines → 8,985, 2.4 MB → 2.1 MB. The
shallow end is where it shows — the old 1 and 2 ft NAVD88 lines have no MLLW
label (that bottom dries) and are simply gone, and each remaining label inherits
roughly the shape of the line 2–3 ft deeper. Seam gaps across −80.30 measured
2–6 m, unchanged in character from the NAVD88 build's 1–5 m.

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

- `DATA = '/Users/janneal/Desktop/WTF Files/depth-data'` — the source rasters.
  They are deleted between builds to reclaim ~2 GB; that folder's README carries
  the re-fetch recipe for both the BlueTopo tiles (URLs in `bluetopo_tiles.json`)
  and the 8 CUDEM tiles. Re-pull before running. **The re-fetch is faithful**:
  BlueTopo object keys embed the delivery date, so the URLs in that manifest
  return the same tiles that built the shipped blocks rather than whatever NOAA
  serves today — a rebuild is a clean change, not a survey update smuggled in
  with one. (Verified 2026-08-06: all 85 keys still return 200.)
- `pass_a_watermask.py`'s `OUT` pointed at the original dead scratchpad path
  until 2026-08-06; it now resolves next to the script, which is where pass B
  loads it from. **Pass A did not need re-running for the MLLW rebuild** — the
  water gate is a connectivity mask at NAVD88 −0.15 m and is datum-independent;
  the committed `watermask_coarse.npz` was reused as-is.
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
blocks serves them forever. It is at **5** as of the MLLW re-cut.

**And do the tide board in the same change.** `~/Documents/tides/depth/` is six
of these blocks copied verbatim (`c3_4`, `c3_5`, `c4_2`–`c4_5`) and the board
reads a depth off them by interpolating between levels. Re-copy the six, keep
its `DEPTH_DATA_V` equal to this one's, and check what its depth path does with
the datum — through build 15 it subtracted 2.25 on every read, and leaving that
in after the MLLW re-cut would have made every depth on the board read 2.25 ft
shallow with nothing looking obviously wrong.
