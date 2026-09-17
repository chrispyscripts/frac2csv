"""Stream a shapefile to newline-delimited GeoJSON for tippecanoe.

Streams because NTSQTR is 1.6M polygons / 220 MB — nothing here holds more
than one record. The grids are EPSG:4269, degrees already, so no reprojection:
NAD83 sits within a couple of metres of WGS84, far under a grid line's width.

Coordinates are rounded to 6 decimals (~0.1 m), which is finer than any survey
corner needs and roughly halves the bytes tippecanoe has to chew through.
"""
import struct, os, sys, json

def dbf_reader(path, want):
    f = open(path, "rb")
    hdr = f.read(32)
    n = struct.unpack("<I", hdr[4:8])[0]
    hlen = struct.unpack("<H", hdr[8:10])[0]
    rlen = struct.unpack("<H", hdr[10:12])[0]
    fields, o = [], 1
    while True:
        d = f.read(32)
        if not d or d[0] == 0x0D:
            break
        name = d[:11].split(b"\0")[0].decode("latin-1").strip()
        fields.append((name, o, d[16])); o += d[16]
    pick = [(nm, s, ln) for nm, s, ln in fields if nm in want]
    f.seek(hlen)
    for _ in range(n):
        rec = f.read(rlen)
        if len(rec) < rlen:
            return
        yield {nm: rec[s:s + ln].decode("latin-1").strip() for nm, s, ln in pick}
    f.close()

def ring_area(pts):
    s = 0.0
    for i in range(len(pts) - 1):
        s += pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]
    return s / 2.0

def shp_reader(path):
    size = os.path.getsize(path)
    f = open(path, "rb")
    f.seek(100)
    while f.tell() < size:
        hd = f.read(8)
        if len(hd) < 8:
            break
        body = f.read(struct.unpack(">i", hd[4:8])[0] * 2)
        st = struct.unpack("<i", body[:4])[0]
        if st != 5:                                   # polygon only
            yield None; continue
        nparts, npts = struct.unpack("<ii", body[36:44])
        parts = struct.unpack(f"<{nparts}i", body[44:44 + 4 * nparts])
        o = 44 + 4 * nparts
        flat = struct.unpack(f"<{2 * npts}d", body[o:o + 16 * npts])
        rings = []
        for i in range(nparts):
            a = parts[i]; b = parts[i + 1] if i + 1 < nparts else npts
            rings.append([[round(flat[2 * j], 6), round(flat[2 * j + 1], 6)]
                          for j in range(a, b)])
        yield rings
    f.close()

def convert(shp_path, out_path, level):
    dbf = shp_path[:-4] + ".dbf"
    n = 0
    with open(out_path, "w") as out:
        for rings, attrs in zip(shp_reader(shp_path), dbf_reader(dbf, {"LABELTEXT"})):
            if not rings:
                continue
            # Shapefile rings: clockwise is an outer ring, counter-clockwise a
            # hole in the one before it. Grid cells are single-ring in
            # practice, but a township clipped by the province edge is not.
            polys = []
            for r in rings:
                if len(r) < 4:
                    continue
                if ring_area(r) < 0 or not polys:
                    polys.append([r])
                else:
                    polys[-1].append(r)
            if not polys:
                continue
            geom = ({"type": "Polygon", "coordinates": polys[0]} if len(polys) == 1
                    else {"type": "MultiPolygon", "coordinates": polys})
            # The cell's own centroid, carried as a property. A cell that
            # straddles a tile boundary arrives at the client in two pieces,
            # and a label placed on a piece's centre lands off the cell and
            # lands twice; this rides along on every piece and is the same
            # point for both, so the client can place one label, correctly.
            # Area-weighted over the outer rings (holes are rare here and a
            # township clipped by the province edge still labels sensibly).
            cx = cy = wsum = 0.0
            for poly in polys:
                r = poly[0]
                a2 = 0.0; fx = 0.0; fy = 0.0
                for i in range(len(r) - 1):
                    cr = r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1]
                    a2 += cr
                    fx += (r[i][0] + r[i + 1][0]) * cr
                    fy += (r[i][1] + r[i + 1][1]) * cr
                if a2:
                    w = abs(a2) / 2.0
                    cx += (fx / (3.0 * a2)) * w; cy += (fy / (3.0 * a2)) * w
                    wsum += w
            props = {"label": attrs.get("LABELTEXT", ""), "level": level}
            if wsum:
                props["cx"] = round(cx / wsum, 6); props["cy"] = round(cy / wsum, 6)
            out.write(json.dumps({"type": "Feature", "properties": props,
                                  "geometry": geom}, separators=(",", ":")) + "\n")
            n += 1
    return n

if __name__ == "__main__":
    print(convert(sys.argv[1], sys.argv[2], sys.argv[3]), "features")
