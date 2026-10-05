"""Survey offsets to latitude and longitude, on NAD83's ellipsoid.

A directional survey gives each station's north-south and east-west offset in
metres from the surface location; the BCER publishes surface locations in
NAD83 (the test pad's well grid says so: DATUMID NAD83, UTM zone 10). Metres
become degrees through the ellipsoid's radii of curvature at the middle of the
offset, which over a few kilometres of lateral agrees with a mapping package's
bottom-hole positions to about 2 m (a flat 111,320 m per degree was 6-9 m off).
"""
import math

A = 6378137.0                    # GRS80, the ellipsoid of NAD83
F = 1 / 298.257222101
E2 = F * (2 - F)


def radii(lat_deg):
    """(meridian, prime-vertical) radii of curvature in metres at a latitude."""
    s = 1 - E2 * math.sin(math.radians(lat_deg)) ** 2
    return A * (1 - E2) / s ** 1.5, A / math.sqrt(s)


def offset(lat, lon, ns, ew):
    """The point `ns` metres north and `ew` metres east of (lat, lon)."""
    m0, _ = radii(lat)
    mid = lat + math.degrees(ns / 2 / m0)
    m, n = radii(mid)
    return lat + math.degrees(ns / m), lon + math.degrees(ew / (n * math.cos(math.radians(mid))))
