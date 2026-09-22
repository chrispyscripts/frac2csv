"""Two plots on a page share more than a pen: they share the whole key.

`_value_panels` stopped the chemical plot's INK being concatenated into the
pressure, which is what killed the red comb (#682-#687). Everything else on
the page was still keyed by COLOUR alone, and on v1.11.25 that left three
defects behind on the same files:

  * **J475 Conc never shipped.** `named.setdefault(colour, ...)` kept
    "Treating Pressure" for red, so the chemical channel was not drawn wrong,
    it was absent — with the comb gone and nothing to say a channel was
    missing. 00619 the same, where green collides with `DR42430 CONC`.
  * **Treating Pressure was fitted through BOTH red ladders**, the 0..100 MPa
    one and the chemical plot's 0..0.3. 00949 stage 1 reported 34.9..60.0
    against a chart that plainly runs 0..77. On 00619 the green collision put
    `BH Prop Conc` at 3.1..3.8 kg/m3 where the chart draws 409 — no comb
    there, so nothing looked wrong at all.
  * **the axis zero never snapped.** There is no gridline at the bottom of a
    plot; the frame edge is that line. So the zero label kept its raw offset
    and tilted every fit on the page: both proppant concentrations on 00949
    read 12 and 23 kg/m3 through the third of the stage the chart draws flat
    on the axis.

And one that is not about panels but was found by them: `_axis_column`
measured "one row" against a flat 2pt, which left-aligned labels break by
~2.1, so every Liberty black ladder was refused and the channel borrowed a
coloured axis instead of reading its own.

  python3 -m unittest tests.test_lib1_panel_axes
"""
import glob
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lib1                                                # noqa: E402


class PanelOfNothing(unittest.TestCase):

    def test_a_span_with_no_position_has_no_panel(self):
        # legend spans are read with .get("cx"); a missing one must key the
        # same way a single-plot page does, not raise inside the comparison
        self.assertIsNone(lib1._panel_of(None, [(110.2, 291.2), (431.5, 618.4)]))
        self.assertIsNone(lib1._panel_of(None, []))


class LeftAlignedAxisColumn(unittest.TestCase):
    """_axis_column is what lets a black series read its OWN printed ladder."""

    @staticmethod
    def _column(values, x0=137.4, pitch=66.7, cy=94.6):
        return [(v, x0 + i * pitch, cy) for i, v in enumerate(values)]

    def test_a_short_zero_label_does_not_disqualify_the_ladder(self):
        # 00949 p97: the labels are aligned on their LEFT edge, so "0.0" has
        # its centre 2.1pt off the "0.200" above it and a flat 2.0 tolerance
        # threw the whole column out. Dry FR Conc then borrowed a coloured
        # axis printed 0..1000 against its own 0..1.0.
        pts = self._column([0.0, 0.200, 0.400, 0.600, 0.800, 1.000])
        pts[0] = (pts[0][0], pts[0][1], pts[0][2] - 2.1)
        self.assertTrue(lib1._axis_column(pts))

    def test_scattered_black_numerics_are_still_refused(self):
        # page numbers and a well name's digits: tens of points apart, which
        # is what the tolerance is actually there to reject
        pts = [(v, x, cy) for v, x, cy in self._column([1.0, 2.0, 3.0, 4.0])]
        pts = [(v, x, cy + i * 40) for i, (v, x, cy) in enumerate(pts)]
        self.assertFalse(lib1._axis_column(pts))


BC = "/Volumes/CnC-2TB-ssd/BCER-Frac/Spud-2019-2023/"
P949 = glob.glob(BC + "00949-100010807914W600_40662_COMP_2021AUG24.pdf")
P974 = glob.glob(BC + "00974-200C027I094B1600_41212_COMP_2021OCT11.pdf")
P619 = glob.glob(BC + "00619-100080707917W600_29974_COMP_2021SEP03.pdf")


def _page(path, pno):
    import fitz
    return lib1.extract_page(fitz.open(path)[pno - 1])


def _finite(data, name):
    v = np.asarray(data[name], float)
    return v[np.isfinite(v)]


@unittest.skipUnless(P949, "the BC drive is not mounted")
class TreatmentOverChemical(unittest.TestCase):
    """00949 page 97 — stage 1 of 22, the page six of seven reports name."""

    @classmethod
    def setUpClass(cls):
        cls.meta, cls.samples, cls.data, cls.units = _page(P949[0], 97)

    def test_the_chemical_plot_keeps_its_own_red(self):
        # absent entirely on v1.11.25: red was taken by Treating Pressure
        self.assertIn("J475 Conc", self.data)
        self.assertEqual(self.meta.axes["J475 Conc"], (0.0, 0.3))
        self.assertLessEqual(_finite(self.data, "J475 Conc").max(), 0.3)

    def test_the_pressure_reads_off_its_own_ladder(self):
        # the chart's red curve tops out just under 80 MPa. Fitted through a
        # tick set that also held the chemical plot's 0..0.3 it came back
        # 34.9..60.0 — compressed AND lifted off the floor.
        v = _finite(self.data, "Treating Pressure")
        self.assertAlmostEqual(v.max(), 77.0, delta=0.6)
        self.assertLess(v.min(), 1.0)

    def test_the_black_chemical_reads_its_printed_axis(self):
        # Dry FR Conc prints 0.0 .. 1.000 of its own; it must not borrow
        self.assertEqual(self.meta.axes["Dry FR Conc"], (0.0, 1.0))

    def test_a_curve_drawn_on_the_axis_reads_zero(self):
        # both proppant concentrations are flat on the axis for the first
        # third of the stage; they used to floor at 12 and 23 kg/m3
        for name in ("Prop Conc", "BH Prop Conc"):
            self.assertLess(_finite(self.data, name).min(), 1.0, name)

    def test_geom_quotes_one_plot_only(self):
        # the ghost view puts the page behind our chart and one rectangle
        # cannot stand for two, so the chemical channels go without a frame
        self.assertIn("Treating Pressure", self.meta.axes_frame)
        self.assertNotIn("J475 Conc", self.meta.axes_frame)


@unittest.skipUnless(P619, "the BC drive is not mounted")
class TheCollisionWithNoComb(unittest.TestCase):
    """00619 page 194 — green is BH Prop Conc above and DR42430 CONC below.

    Nothing about this page LOOKED wrong: the concentration sat flat and low
    instead of combing, because the chemical curve dominates the merged
    series. It shipped 3.1..3.8 kg/m3 against a chart drawing 409.
    """

    @classmethod
    def setUpClass(cls):
        cls.meta, cls.samples, cls.data, cls.units = _page(P619[0], 194)

    def test_the_proppant_concentration_is_not_a_chemical(self):
        v = _finite(self.data, "BH Prop Conc")
        self.assertGreater(v.max(), 350.0)
        self.assertLess(v.min(), 1.0)

    def test_the_chemical_survives_as_its_own_channel(self):
        self.assertIn("DR42430 CONC", self.data)
        self.assertEqual(self.meta.axes["DR42430 CONC"], (0.0, 2.0))


@unittest.skipUnless(P974, "the BC drive is not mounted")
class ChemicalPageAlone(unittest.TestCase):
    """00974 page 129 — four chemicals, no treatment plot, one frame.

    The page is the control for the axis-column fix: B596 Conc is the black
    series and prints its own 0..2.400, while J475 shares its kg/m3 unit on a
    0..1.000. Borrowing put B596 on the wrong one of the two.
    """

    @classmethod
    def setUpClass(cls):
        cls.meta, cls.samples, cls.data, cls.units = _page(P974[0], 129)

    def test_the_black_chemical_reads_its_own_ladder(self):
        self.assertEqual(self.meta.axes["B596 Conc"], (0.0, 2.4))

    def test_the_spiking_channels_are_left_alone(self):
        # B701 and B487 really do touch their axis tops on this page — the
        # fix must not "correct" a reading the chart actually draws
        self.assertAlmostEqual(_finite(self.data, "B701 Conc").max(), 1.0, delta=0.01)
        self.assertAlmostEqual(_finite(self.data, "B487 Conc").max(), 1.6, delta=0.01)


if __name__ == "__main__":
    unittest.main()
