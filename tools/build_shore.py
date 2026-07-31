# Generates the SHORE_RINGS coastline envelope embedded in index.html (the ICW
# Channel view's ocean-clip boundary). Run it if the coastline data ever needs
# regenerating or tuning (pad/closing/seals), then paste shore_rings.js over the
# SHORE_RINGS literal in index.html.
#
# Usage:
#   python3 -m venv geo && ./geo/bin/pip install shapely pyshp
#   curl -O https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_state_500k.zip
#   unzip cb_2023_us_state_500k.zip -d states500k
#   ./geo/bin/python build_shore.py     # writes shore_rings.js, prints test results

import shapefile, json
from shapely.geometry import shape, Point, box
from shapely.ops import unary_union
from shapely import Polygon, MultiPolygon

sf = shapefile.Reader('states500k/cb_2023_us_state_500k')
fields = [f[0] for f in sf.fields[1:]]
want = {'FL','GA','AL','MS'}
geoms = []
for sr in sf.iterShapeRecords():
    rec = dict(zip(fields, sr.record))
    if rec['STUSPS'] in want:
        geoms.append(shape(sr.shape.__geo_interface__))

# Wide bay mouths the 3.3 km closing can't seal on its own: bridge them so the
# whole estuary stays "inside" (keeps its photo) like the sealed lagoons do.
seals = [
    box(-82.80, 27.52, -82.60, 27.72),   # Tampa Bay mouth (Anna Maria - Egmont Key - Ft De Soto)
    box(-88.10, 30.20, -87.96, 30.32),   # Mobile Bay mouth (Ft Morgan - Dauphin Is.)
]
land = unary_union(geoms + seals)

CLOSE = 0.03
env = land.buffer(CLOSE, join_style='round').buffer(-CLOSE, join_style='round')
GATE = box(-88.4, 24.25, -79.25, 31.0)
env = env.intersection(GATE)
env = env.simplify(0.002, preserve_topology=True)

polys = list(env.geoms) if isinstance(env, MultiPolygon) else [env]
rings = []
for p in polys:
    if p.area < 2e-5: continue
    rings.append(list(p.exterior.coords))
rings.sort(key=lambda r: -abs(Polygon(r).area))
print('rings:', len(rings), 'points:', sum(len(r) for r in rings))

solid = MultiPolygon([Polygon(r) for r in rings])
tests = [
 ('Daytona Beach land',        29.210, -81.005, True),
 ('2km offshore Daytona',      29.210, -80.960, False),
 ('Halifax River (lagoon)',    29.140, -80.970, True),
 ('Mosquito Lagoon mid',       28.750, -80.750, True),
 ('Cape Canaveral tip shore',  28.462, -80.527, True),
 ('1.5km east of cape tip',    28.462, -80.512, False),
 ('Tampa Bay mid',             27.700, -82.550, True),
 ('Gulf offshore Clearwater',  27.970, -82.950, False),
 ('Charlotte Harbor mid',      26.800, -82.100, True),
 ('Apalachicola Bay',          29.650, -84.950, True),
 ('St Joseph Bay',             29.780, -85.350, True),
 ('Pensacola Bay',             30.350, -87.100, True),
 ('Santa Rosa Island',         30.338, -87.140, True),
 ('Gulf off Pensacola',        30.200, -87.140, False),
 ('Mobile Bay mid',            30.450, -88.000, True),
 ('Key West',                  24.555, -81.780, True),
 ('Key Largo',                 25.090, -80.440, True),
 ('Florida Bay open',          24.900, -80.900, False),
 ('Atlantic off Key Largo',    25.090, -80.300, False),
 ('Okeechobee mid',            26.950, -80.850, True),
 ('Georgia land',              30.900, -81.900, True),
 ('Offshore GA',               30.900, -81.150, False),
 ('Dry Tortugas',              24.628, -82.873, True),
]
allok = True
for name, lat, lon, expect in tests:
    got = solid.contains(Point(lon, lat))
    ok = got == expect
    allok &= ok
    if not ok: print('FAIL', name, 'inside=' + str(got))
print('ALL TESTS PASS' if allok else 'SOME TESTS FAILED')
for name, lat, lon in [('Ponce jetty tip',29.063,-80.904), ('St Johns jetty tip',30.400,-81.383), ('Canaveral Port jetty',28.408,-80.585), ('St Marys jetty tip',30.720,-81.377)]:
    p = Point(lon, lat)
    print(f'{name}: inside={solid.contains(p)} dist-deg={solid.boundary.distance(p):.4f}')

out = []
for r in rings:
    flat = []
    for x, y in r[:-1]:
        flat.append(round(x, 4)); flat.append(round(y, 4))
    out.append(flat)
js = json.dumps(out, separators=(',', ':'))
open('shore_rings.js','w').write(js)
print('JS size:', round(len(js)/1024, 1), 'KB')
