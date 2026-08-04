#!/usr/bin/env python3
"""Turn tools/scan_sea_labels.py output into the SEA_LABEL_WINDOWS table.

Reads the per-zoom scan JSONs (z11.json .. z16.json, or the combined
sea_label_scan.json) and emits JS entry lines [lat, lng, halfW, halfH,
zMin, zMax] — one per measured label box, +MARGIN px slack all round,
merged across adjacent zooms whenever one entry still CONTAINS every
zoom's measured box (px slack checked at each zoom, since a fixed-px
entry covers different ground at different zooms). Boxes are tight on
purpose: the v400 hand-measured windows carried +34/38 px close-zoom
growth that swallowed the charted dashed lines next to some labels and
'lighten' popped the dashes through (Jan: "line is also showing
through") — measured boxes need no growth, so the runtime drift shift
was removed with this (v402).

Usage: gen_sea_windows.py <dir-with-zN.json-files>
"""
import json, math, os, sys

MARGIN = 5          # px slack around the measured ink
LAT_KEEP = (27.7, 30.3)
LNG_KEEP = -81.42   # drop inland Jacksonville-area strays

def ll2px(lng, lat, z):
    n = 2.0**z*256
    x = (lng+180)/360*n
    p = math.radians(lat)
    y = (1-math.log(math.tan(p)+1/math.cos(p))/math.pi)/2*n
    return x, y

def px2ll(x, y, z):
    n = 2.0**z*256
    lng = x/n*360-180
    lat = math.degrees(math.atan(math.sinh(math.pi*(1-2*y/n))))
    return lng, lat

def contains(entry, rec, z):
    lat, lng, hw, hh = entry
    cx, cy = ll2px(lng, lat, z)
    b = rec["box"]
    return (cx-hw <= b[0]-MARGIN+1 and cx+hw >= b[2]+MARGIN-1 and
            cy-hh <= b[1]-MARGIN+1 and cy+hh >= b[3]+MARGIN-1)

def entry_for(recs):
    """One [lat,lng,hw,hh] containing every (z, rec) box with margin."""
    # centre on the union of box centres in geo, then grow hw/hh until all fit
    lats = []; lngs = []
    for z, r in recs:
        b = r["box"]
        lng, lat = px2ll((b[0]+b[2])/2, (b[1]+b[3])/2, z)
        lats.append(lat); lngs.append(lng)
    lat, lng = sum(lats)/len(lats), sum(lngs)/len(lngs)
    hw = hh = 0
    for z, r in recs:
        cx, cy = ll2px(lng, lat, z)
        b = r["box"]
        hw = max(hw, cx-b[0]+MARGIN, b[2]+MARGIN-cx)
        hh = max(hh, cy-b[1]+MARGIN, b[3]+MARGIN-cy)
    return [round(lat, 6), round(lng, 6), math.ceil(hw), math.ceil(hh)]

def main():
    d = sys.argv[1]
    per_z = {}
    comb = os.path.join(d, "sea_label_scan.json")
    if os.path.exists(comb):
        per_z = {int(k): v for k, v in json.load(open(comb)).items()}
    else:
        for z in range(11, 17):
            p = os.path.join(d, f"z{z}.json")
            if os.path.exists(p):
                per_z[z] = json.load(open(p))
    # group measured boxes into labels by proximity (same printed name drifts
    # a little between zooms; 500 m groups it, different labels sit farther)
    items = []
    for z, data in sorted(per_z.items()):
        for r in data["labels"]:
            if not (LAT_KEEP[0] <= r["lat"] <= LAT_KEEP[1]) or r["lng"] < LNG_KEEP:
                continue
            items.append((z, r))
    groups = []
    for z, r in items:
        for g in groups:
            gz, gr = g[-1]
            if abs(gr["lat"]-r["lat"])*110540 < 500 and \
               abs(gr["lng"]-r["lng"])*math.cos(math.radians(r["lat"]))*111320 < 900:
                g.append((z, r))
                break
        else:
            groups.append([(z, r)])
    lines = []
    for g in groups:
        # split the group into runs of consecutive zooms that share one entry
        g.sort()
        runs = []
        for z, r in g:
            placed = False
            for run in runs:
                if run[-1][0] in (z, z-1):
                    cand = entry_for(run + [(z, r)])
                    if all(contains(cand, rr, zz) for zz, rr in run + [(z, r)]):
                        run.append((z, r))
                        placed = True
                        break
            if not placed:
                runs.append([(z, r)])
        name = max((r for _, r in g), key=lambda r: r["w"]).get("name", "?")
        for run in runs:
            e = entry_for(run)
            zmin, zmax = run[0][0], run[-1][0]
            lines.append((e[0], f"  [{e[0]},{e[1]},{e[2]},{e[3]},{zmin},{zmax}],  // {name}"))
    lines.sort(reverse=True)
    print("const SEA_LABEL_WINDOWS = [")
    out = [l for _, l in lines]
    if out:
        out[-1] = out[-1].replace("],  //", "]   //", 1)
    print("\n".join(out))
    print("];")

if __name__ == "__main__":
    main()
