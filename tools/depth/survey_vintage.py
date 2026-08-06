#!/usr/bin/env python3
"""
How old is the bottom under these contours?

BlueTopo publishes a per-tile raster attribute table (RAT) alongside every
GeoTIFF: band 3 of the tile is a contributor ID, and the RAT resolves each ID to
a source survey, an institution, and survey start/end dates. That table is the
only place a survey DATE exists anywhere in this pipeline — the contour blocks
this app ships carry none, and the source GeoTIFFs were deleted 2026-08-04 once
the contours had shipped.

The RATs are small (~80 KB each) and still fetchable from the same URLs already
listed in depth-data/bluetopo_tiles.json, so this runs without re-downloading
660 MB of rasters.

    python3 survey_vintage.py                      # inshore box, text report
    python3 survey_vintage.py --md > SURVEY_VINTAGE.md
    python3 survey_vintage.py --box -81.1 28.85 -80.85 29.45

THE ONE THING TO UNDERSTAND BEFORE READING THE OUTPUT: most cells are not
measurements. A contributor row whose source_survey_id ends in ".interpolated"
is FILL — BlueTopo carrying a survey's value across water that survey never
sounded. Counting raw cells makes 1970s work look dominant; separating measured
from interpolated is what tells you whether a spot rests on data or on inference.
Both numbers are reported, and the measured column is the honest one.

Delivery date != survey date. A tile stamped 2026 is a COMPILATION republished
in 2026; the soundings inside it can be from 1874. The filenames in
bluetopo_tiles.json give delivery; only this RAT gives survey.
"""

import sys
import json
import os
import collections
import urllib.request
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
TILES_JSON = os.path.expanduser(
    '~/Desktop/WTF Files/depth-data/bluetopo_tiles.json')
CACHE = os.path.join(HERE, '.rat_cache')

# The inshore water this app is actually about: Mosquito Lagoon up to Bulow.
DEFAULT_BOX = (-81.10, 28.85, -80.85, 29.45)

# Tiles whose bbox contains a named spot, for the per-area breakdown. A tile is
# 0.075 deg on a side inshore, so one tile covers several of these.
AREAS = [
    ('Ponce Inlet',                   29.077867, -80.908517),
    ('Spruce Creek / Turnbull Bay',   29.043000, -80.959817),
    ('Rose Bay / Dunlawton',          29.146600, -80.976900),
    ('Ormond',                        29.286600, -81.046400),
    ('Mosquito Lagoon / Turtle Mound', 28.960000, -80.820000),
]


def load_tiles(box):
    tiles = json.load(open(TILES_JSON))
    hit = lambda b: not (b[2] < box[0] or b[0] > box[2]
                         or b[3] < box[1] or b[1] > box[3])
    return [t for t in tiles if hit(t['bbox'])]


def rat_rows(tile):
    """Fetch (and cache) one tile's RAT; return a list of dict rows."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, tile['tile'] + '.xml')
    if not os.path.exists(path):
        urllib.request.urlretrieve(tile['rat'], path)
    rat = ET.parse(path).getroot().find('.//GDALRasterAttributeTable')
    if rat is None:
        return []
    fields = [f.find('Name').text for f in rat.findall('FieldDefn')]
    return [dict(zip(fields, [c.text for c in r])) for r in rat.findall('Row')]


def tally(tiles):
    """-> measured Counter, interpolated Counter, {survey: (start, end, inst)}"""
    meas, interp, dates = collections.Counter(), collections.Counter(), {}
    per_tile = {}
    for t in tiles:
        tm, ti = collections.Counter(), collections.Counter()
        for row in rat_rows(t):
            sid = row['source_survey_id']
            # value 0 is BlueTopo's own smoothing pass, not a survey
            if sid == 'NBS Generalization':
                continue
            base = sid.replace('.interpolated', '')
            n = int(row['count'])
            (ti if '.interpolated' in sid else tm)[base] += n
            dates.setdefault(base, (row['survey_date_start'][:10],
                                    row['survey_date_end'][:10],
                                    row['source_institution'].split('--')[-1].strip()))
        meas.update(tm)
        interp.update(ti)
        per_tile[t['tile']] = (t, tm, ti)
    return meas, interp, dates, per_tile


def tile_for(per_tile, lat, lng):
    for name, (t, tm, ti) in per_tile.items():
        b = t['bbox']
        if b[0] <= lng <= b[2] and b[1] <= lat <= b[3]:
            yield name, t, tm, ti


def report(box, md=False):
    tiles = load_tiles(box)
    meas, interp, dates, per_tile = tally(tiles)
    M, I = sum(meas.values()), sum(interp.values())
    out = []
    h1 = (lambda s: '# ' + s) if md else (lambda s: s + '\n' + '=' * len(s))
    h2 = (lambda s: '\n## ' + s) if md else (lambda s: '\n' + s + '\n' + '-' * len(s))

    out.append(h1('BlueTopo survey vintage'))
    out.append('')
    out.append('Box %s, %d tiles.' % (list(box), len(tiles)))
    out.append('')
    out.append('Cells: %s measured, %s interpolated fill '
               '-> **%.0f%% of the grid is fill, not measurement.**'
               % (format(M, ','), format(I, ','), 100.0 * I / (M + I)))

    out.append(h2('Measured cells by decade of survey'))
    out.append('')
    dec = collections.Counter()
    for s, c in meas.items():
        dec[dates[s][1][:3] + '0s'] += c
    if md:
        out.append('| decade | cells | share |')
        out.append('|---|---:|---:|')
    for d, c in sorted(dec.items()):
        out.append(('| %s | %s | %.1f%% |' if md else '  %-8s %14s  %5.1f%%')
                   % (d, format(c, ','), 100.0 * c / M))

    out.append(h2('Top surveys, measured cells only'))
    out.append('')
    if md:
        out.append('| survey | cells | share | dates | institution |')
        out.append('|---|---:|---:|---|---|')
    for s, c in meas.most_common(12):
        ds, de, inst = dates[s]
        out.append(('| `%s` | %s | %.1f%% | %s .. %s | %s |' if md
                    else '  %-42s %12s %5.1f%%  %s..%s  %s')
                   % (s, format(c, ','), 100.0 * c / M, ds, de, inst[:38]))

    out.append(h2('By area'))
    for name, lat, lng in AREAS:
        for tname, t, tm, ti in tile_for(per_tile, lat, lng):
            tot = sum(tm.values()) + sum(ti.values())
            if not tot:
                continue
            out.append('')
            out.append(('**%s** — tile `%s` (%s, delivered %s)' if md
                        else '%s  [tile %s, %s, delivered %s]')
                       % (name, tname, t['res'], t['link'].split('_')[-1][:8]))
            out.append('')
            combined = tm + ti
            for s, c in combined.most_common(5):
                ds, de, _ = dates[s]
                out.append(('  - `%s` %.1f%% of the tile — %s measured, %s filled — %s..%s' if md
                            else '    %-34s %5.1f%%  meas %9s  fill %9s  %s..%s')
                           % ((s, 100.0 * c / tot, format(tm[s], ','), format(ti[s], ','), ds, de)
                              if md else
                              (s, 100.0 * c / tot, format(tm[s], ','), format(ti[s], ','), ds, de)))

    out.append(h2('What this means'))
    out.append('''
Read the measured column, not the raw share. The 1966-74 H-surveys look
dominant by cell count and are almost entirely `.interpolated` — fill carried
across water nobody sounded. Real measurement here is overwhelmingly modern
lidar.

The catch is WHERE the lidar failed. Green topobathy lidar reaches roughly
1.5-2 Secchi depths and gets no bottom return from dark water, so a deep hole
in a tannic creek drops out of the measured set and is interpolated off the
surrounding bar — which the lidar did see. That is the mechanism behind the
Crook's Corner error on the tide board (contours put a hole that holds 8-10 ft
at about -0.8 ft of water at dead low). Expect the same at dark-water holes and
channels, not on open flats. Interpolation cannot fix missing data, and a
sounded depth beats the survey every time in skinny water.

Delivery date is not survey date. Tile filenames in bluetopo_tiles.json give
the date NOAA published the compilation; only this RAT gives the date anyone
went out and measured.

Not done here: point-level attribution. Contributor ID is per CELL, and reading
it at a coordinate needs the tile raster itself (band 3), which was deleted
2026-08-04. Re-fetch from the `link` field in bluetopo_tiles.json if a specific
spot ever needs its own survey named.''')
    out.append('')
    return '\n'.join(out)


def main(argv):
    md = '--md' in argv
    box = DEFAULT_BOX
    if '--box' in argv:
        i = argv.index('--box')
        box = tuple(float(x) for x in argv[i + 1:i + 5])
    print(report(box, md))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
