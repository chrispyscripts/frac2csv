"""A sideways Halliburton plot gets chart geometry too (00370 p129).

The turned filings were read through np.rot90(img, -1) and given no geometry, so
the Lab could only show the sheet as printed, sideways under an upright graph:
588 of the 661 Halliburton raster charts in the Lab's results. Each case here
plants a marker where the frame says a moment in time sits, embeds the image,
and finds the marker on the rendered unrotated page where the geometry says.

Run: python3 -m unittest tests.test_hal_turned_geom
"""
import os
import sys
import unittest

import fitz
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hal1                                                # noqa: E402

W, H = 300, 200                                            # the image as stored
PLOT = (20, 30, 180, 270)                                  # frame, in the turned image
DUR = 3200.0


def stored_image(e, frac):
    """The stored image, with a marker e seconds in and frac of the way down the
    frame, drawn in the turned image and turned back."""
    x0, y0, x1, y1 = PLOT
    turned = np.full((W, H, 3), 255, np.uint8)             # np.rot90 swaps the sides
    x = int(round(x0 + (x1 - x0) * e / DUR))
    y = int(round(y0 + (y1 - y0) * frac))
    turned[y - 3:y + 4, x - 3:x + 4] = (255, 0, 0)
    return np.rot90(turned, 1).copy()                      # undoes np.rot90(img, -1)


def marker(page):
    """Where the marker lands on the unrotated page, in page units."""
    was = page.rotation
    page.set_rotation(0)
    pix = page.get_pixmap(dpi=144)
    page.set_rotation(was)
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
    ys, xs = np.nonzero((a[..., 0] > 200) & (a[..., 1] < 90) & (a[..., 2] < 90))
    return float(xs.mean()) / 2.0, float(ys.mean()) / 2.0


def geom_on(rect, rotate=0, page_rotate=0, e=800.0, frac=0.25):
    img = stored_image(e, frac)
    pm = fitz.Pixmap(fitz.csRGB, W, H, img.tobytes(), False)
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_image(rect, pixmap=pm, rotate=rotate)
    page.set_rotation(page_rotate)
    xref = page.get_images(full=True)[0][0]
    _r, m = page.get_image_rects(xref, transform=True)[0]
    info = {"plot": PLOT, "t0_seconds": 120.0, "duration_s": int(DUR)}
    return hal1._turned_geom(info, W, H, m), marker(page)


class TurnedGeom(unittest.TestCase):

    def check(self, g, at, e=800.0, frac=0.25, tol=1.5):
        along = (e - g["ta"]) / g["tb"]
        across = g["v0"] + (g["v1"] - g["v0"]) * frac
        x, y = (across, along) if g["axis"] == "y" else (along, across)
        self.assertAlmostEqual(x, at[0], delta=tol)
        self.assertAlmostEqual(y, at[1], delta=tol)

    def test_a_sideways_image_runs_time_up_the_page(self):
        g, at = geom_on(fitz.Rect(100, 150, 400, 350))
        self.assertEqual(g["axis"], "y")
        self.assertLess(g["tb"], 0)
        self.check(g, at)

    def test_every_moment_lands_on_its_marker(self):
        for e, frac in ((0.0, 0.1), (1600.0, 0.5), (3200.0, 0.9)):
            g, at = geom_on(fitz.Rect(100, 150, 400, 350), e=e, frac=frac)
            self.check(g, at, e, frac)

    def test_a_stretched_image(self):
        # page units per pixel differ across and along: the frame still lands
        g, at = geom_on(fitz.Rect(50, 100, 550, 700))
        self.check(g, at)

    def test_a_rotate_flag_on_the_page_changes_nothing(self):
        # geometry is in the unrotated page, as every other reader's is
        plain, _ = geom_on(fitz.Rect(100, 150, 400, 350))
        flagged, at = geom_on(fitz.Rect(100, 150, 400, 350), page_rotate=90)
        self.assertEqual(plain, flagged)
        self.check(flagged, at)

    def test_an_image_placed_turned_runs_time_across(self):
        # placed a quarter turn on the page, the same stored pixels read upright
        g, at = geom_on(fitz.Rect(100, 150, 300, 450), rotate=90)
        self.assertEqual(g["axis"], "x")
        self.check(g, at)

    def test_nothing_to_go_by(self):
        m = fitz.Matrix(300, 0, 0, 200, 100, 150)
        self.assertIsNone(hal1._turned_geom({"plot": PLOT, "duration_s": 0}, W, H, m))
        self.assertIsNone(hal1._turned_geom({"duration_s": 60}, W, H, m))


if __name__ == "__main__":
    unittest.main()
