"""Survey offsets to latitude and longitude on NAD83's ellipsoid (web/scripts/geodesy.py)."""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web", "scripts"))
from geodesy import offset, radii  # noqa: E402


def test_no_offset_is_the_same_point():
    assert offset(56.74, -122.14, 0, 0) == (56.74, -122.14)


def test_a_degree_of_latitude_at_gundy():
    # GRS80's meridian radius at 56.74 N makes a degree about 111,354 m (a flat 111,320 is 34 m short)
    m, _ = radii(56.74)
    per_degree = m * math.pi / 180
    assert abs(per_degree - 111354) < 5
    lat, lon = offset(56.74, -122.14, per_degree, 0)
    assert abs(lat - 57.74) < 1e-4 and lon == -122.14


def test_east_shrinks_with_latitude():
    _, lon_south = offset(50.0, -120.0, 0, 1000)
    _, lon_north = offset(58.0, -120.0, 0, 1000)
    assert lon_north - (-120.0) > lon_south - (-120.0) > 0


def test_there_and_back():
    lat, lon = offset(56.74, -122.14, 3200, -2100)
    back = offset(lat, lon, -3200, 2100)
    assert abs(back[0] - 56.74) < 2e-6 and abs(back[1] - -122.14) < 2e-6
