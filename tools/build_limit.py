# Generates LIMIT_RINGS (the statewide state-waters limit the Topo Satellite
# view clips its ocean along and draws its dashed line from: 3 nautical miles
# on the Atlantic, 9 in the Gulf, joined along the Keys) and SEA_NAMES (the
# coastal place-name anchors printed over the flat blue), both embedded in
# index.html. Same setup as build_shore.py:
#   python3 -m venv geo && ./geo/bin/pip install shapely pyshp
#   curl -O https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_state_500k.zip
#   unzip cb_2023_us_state_500k.zip -d states500k
#   ./geo/bin/python build_limit.py   # writes limit_rings.js + limit_names.js

import shapefile, json, math
from shapely.geometry import shape, Point, box, Polygon as SPoly
from shapely.ops import unary_union, transform, nearest_points
from shapely import Polygon, MultiPolygon

sf = shapefile.Reader('states500k/cb_2023_us_state_500k')
fields = [f[0] for f in sf.fields[1:]]
want = {'FL','GA','AL','MS'}
geoms = []
for sr in sf.iterShapeRecords():
    rec = dict(zip(fields, sr.record))
    if rec['STUSPS'] in want:
        geoms.append(shape(sr.shape.__geo_interface__))
# Seals hug the island chains: earlier box seals stuck ~3 nm into the Gulf
# (a straight blue wall offshore Anna Maria/Egmont Key). Tampa's bridges
# Anna Maria -> Egmont Key -> Mullet Key; Mobile's bridges Dauphin Island ->
# Fort Morgan, both staying behind the islands' Gulf shores.
seals = [box(-82.77, 27.53, -82.68, 27.63), box(-88.10, 30.222, -87.96, 30.40)]
land = unary_union(geoms + seals)
CLOSE = 0.03
env = land.buffer(CLOSE, join_style='round').buffer(-CLOSE, join_style='round')

K = math.cos(math.radians(27.75))
fwd = lambda x, y, z=None: (x*K, y)
inv = lambda x, y, z=None: (x/K, y)
env_s = transform(fwd, env)
NM = 1/60.0
buf3 = transform(inv, env_s.buffer(3*NM, join_style='round'))
buf9 = transform(inv, env_s.buffer(9*NM, join_style='round'))

# Gulf/Atlantic split: Florida gets 9 nm in the Gulf, 3 nm on the Atlantic.
# The divider runs inland up the east coast (harmless on land), along the
# spine of the Keys, then west past the Marquesas so the Dry Tortugas sit on
# the Gulf side — matching how the charted lines meet near Key West.
GULF_MASK = SPoly([
    (-80.17,25.70),(-80.45,25.09),(-81.09,24.71),(-81.80,24.56),
    (-82.00,24.50),(-82.20,24.45),(-88.60,24.45),(-88.60,31.50),
    (-82.00,31.50),(-82.00,31.20),(-81.80,30.70),(-81.30,29.50),
    (-80.90,28.50),(-80.60,27.50),(-80.30,26.50),
])
WORLD = box(-89.5, 23.5, -78.5, 32.0)
ATL_MASK = WORLD.difference(GULF_MASK)
limit = unary_union([buf9.intersection(GULF_MASK), buf3.intersection(ATL_MASK)])

GATE = box(-88.4, 24.25, -79.25, 31.0)
limit_fill = limit.intersection(GATE).simplify(0.003, preserve_topology=True)
polys = list(limit_fill.geoms) if isinstance(limit_fill, MultiPolygon) else [limit_fill]
rings = []
for p in polys:
    if p.area < 2e-4: continue
    rings.append(list(p.exterior.coords))
rings.sort(key=lambda r: -abs(Polygon(r).area))
print('LIMIT rings:', len(rings), 'points:', sum(len(r) for r in rings))
solid = MultiPolygon([Polygon(r) for r in rings])

tests = [
 ('Daytona shore',            29.210, -81.005, True),
 ('2nm off Daytona',          29.210, -80.958, True),
 ('4nm off Daytona (Atl=3)',  29.210, -80.920, False),
 ('2nm off Boynton (Atl)',    26.526, -80.010, True),
 ('5nm off Boynton (Atl=3)',  26.526, -79.955, False),
 ('Tampa Bay mid',            27.700, -82.550, True),
 ('5nm off Clearwater (Gulf=9)', 27.977, -82.925, True),
 ('8nm off Clearwater (Gulf=9)', 27.977, -82.980, True),
 ('11nm off Clearwater',      27.977, -83.040, False),
 ('6nm off Pensacola (Gulf)', 30.235, -87.140, True),
 ('11nm off Pensacola',       30.150, -87.140, False),
 ('6nm N of Key West (Gulf)', 24.655, -81.780, True),
 ('4nm S of Key West (Atl=3)',24.488, -81.780, False),
 ('8nm W of Dry Tortugas',    24.628, -83.020, True),
 ('mid Gulf',                 27.000, -85.000, False),
 ('Florida Bay (Gulf side)',  25.000, -80.750, True),
 ('Okeechobee',               26.950, -80.850, True),
 ('Offshore GA (Atl=3, 5nm)', 30.900, -81.170, False),
]
allok = True
for name, lat, lon, expect in tests:
    got = solid.contains(Point(lon, lat))
    ok = got == expect; allok &= ok
    if not ok: print('FAIL', name, 'inside=' + str(got))
print('LIMIT TESTS:', 'ALL PASS' if allok else 'FAILURES')

out = []
for r in rings:
    flat = []
    for x, y in r[:-1]:
        flat.append(round(x, 4)); flat.append(round(y, 4))
    out.append(flat)
js = json.dumps(out, separators=(',', ':'))
open('limit_rings.js','w').write(js)
print('LIMIT JS size:', round(len(js)/1024,1), 'KB')

CITIES = [
 (1,'Jacksonville Beach',30.283,-81.394),(2,'Fernandina Beach',30.669,-81.463),
 (1,'St. Augustine',29.901,-81.312),(2,'Palm Coast',29.585,-81.208),
 (2,'Flagler Beach',29.475,-81.127),(2,'Ormond Beach',29.286,-81.056),
 (1,'Daytona Beach',29.211,-81.023),(2,'Port Orange',29.108,-80.996),
 (2,'Ponce Inlet',29.096,-80.937),(1,'New Smyrna Beach',29.026,-80.927),
 (2,'Edgewater',28.989,-80.902),(2,'Oak Hill',28.864,-80.851),
 (2,'Titusville',28.612,-80.808),(1,'Cocoa Beach',28.320,-80.610),
 (2,'Satellite Beach',28.176,-80.590),(1,'Melbourne',28.083,-80.608),
 (2,'Sebastian',27.816,-80.470),(1,'Vero Beach',27.638,-80.397),
 (1,'Fort Pierce',27.447,-80.326),(2,'Jensen Beach',27.254,-80.216),
 (2,'Stuart',27.197,-80.253),(2,'Jupiter',26.934,-80.094),
 (1,'West Palm Beach',26.715,-80.054),(2,'Lake Worth Beach',26.617,-80.057),
 (2,'Boynton Beach',26.526,-80.066),(2,'Delray Beach',26.461,-80.073),
 (1,'Boca Raton',26.359,-80.083),(2,'Pompano Beach',26.238,-80.125),
 (1,'Fort Lauderdale',26.122,-80.137),(2,'Hollywood',26.011,-80.149),
 (1,'Miami Beach',25.790,-80.130),(2,'Miami',25.762,-80.192),
 (2,'Key Biscayne',25.691,-80.163),(1,'Key Largo',25.086,-80.447),
 (2,'Islamorada',24.924,-80.628),(1,'Marathon',24.714,-81.090),
 (2,'Big Pine Key',24.670,-81.354),(1,'Key West',24.555,-81.782),
 (2,'Marco Island',25.941,-81.718),(1,'Naples',26.142,-81.795),
 (2,'Bonita Springs',26.340,-81.845),(2,'Fort Myers Beach',26.452,-81.948),
 (2,'Sanibel',26.449,-82.022),(2,'Punta Gorda',26.930,-82.045),
 (2,'Venice',27.099,-82.454),(1,'Sarasota',27.336,-82.531),
 (2,'Bradenton',27.499,-82.575),(1,'St. Petersburg',27.768,-82.640),
 (1,'Clearwater',27.966,-82.800),(2,'Tarpon Springs',28.146,-82.757),
 (2,'New Port Richey',28.244,-82.719),(2,'Homosassa',28.781,-82.615),
 (2,'Crystal River',28.902,-82.593),(1,'Cedar Key',29.135,-83.035),
 (2,'Steinhatchee',29.671,-83.387),(2,'St. Marks',30.157,-84.207),
 (2,'Carrabelle',29.853,-84.664),(1,'Apalachicola',29.726,-84.986),
 (2,'Port St. Joe',29.811,-85.303),(2,'Mexico Beach',29.948,-85.417),
 (1,'Panama City Beach',30.176,-85.805),(1,'Destin',30.393,-86.496),
 (2,'Fort Walton Beach',30.420,-86.617),(2,'Navarre',30.402,-86.863),
 (2,'Pensacola Beach',30.335,-87.139),(1,'Pensacola',30.421,-87.217),
 (2,'Perdido Key',30.310,-87.440),
]
# Names anchor just seaward of the SHORELINE cut (the views clip at the shore
# envelope since Build 203), not the state-waters line: 1.3 nm clears the
# 1300 m photo pad and lands the name on the blue right off the town's beach.
line_s = transform(fwd, env).boundary
OFF = 1.3/60.0
names = []
for rank, name, lat, lon in CITIES:
    c = Point(lon*K, lat)
    p = nearest_points(line_s, c)[0]
    dx, dy = p.x - c.x, p.y - c.y
    d = math.hypot(dx, dy) or 1e-9
    ax, ay = p.x + dx/d*OFF, p.y + dy/d*OFF
    ux = dx/d
    align = 'l' if ux > 0.45 else ('r' if ux < -0.45 else 'c')
    names.append([round(ay,4), round(ax/K,4), align, rank, name])
js2 = json.dumps(names, separators=(',', ':'), ensure_ascii=False)
open('limit_names.js','w').write(js2)
print('names:', len(names), 'sample gulf:', [n for n in names if n[4]=='Clearwater'][0])
