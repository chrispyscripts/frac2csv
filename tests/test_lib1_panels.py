"""Two plots on one page must not share a series just because they share a pen.

Liberty prints a Treatment Plot and a Chemicals Plot on every stage page.
Both draw a curve in pure red — Treating Pressure above, J475 Conc below —
and lib1 groups a page's series by COLOUR over every drawing on the page. So
the chemical curve was concatenated into the pressure: 36 red paths on
00949 p97 where every other colour has exactly 18.

The chemical curve sits well below the pressure frame, so it clips to the
bottom of the pressure axis and the series alternates between a real
pressure and ~0 once per x-slice. Measured on 00949 before the fix:

    stage 1   median step 28.592 MPa on a 0..59.5 range   56.7% of samples
    stage 2   median step 16.045 MPa on a 0..60.1 range   83.5%
    stage 3   median step 10.790                          37.9%
    stage 4   median step 10.576                          44.9%

and after it, 0.022 / 0.016 / 0.017 / 0.021 and 0.0% on all four. Note it
was never stage 1 only — the seven reports (#682-#687) are all stage 1
because that is the stage you open first. Stage 2 was worse.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lib1


class Panel(unittest.TestCase):
    """_value_panels off gridline positions, and _panel_of against them."""

    class FakePage:
        def __init__(self, rects):
            self._r = rects

        def get_drawings(self):
            import fitz
            return [{"type": "s", "color": (0, 0, 0), "rect": fitz.Rect(*r),
                     "items": []} for r in self._r]

    def page(self, ys, x0=100.0, x1=400.0):
        return self.FakePage([(x0, y, x1, y) for y in ys])

    def test_two_frames_are_two_panels(self):
        # 00949 p97's own gridlines: ten per plot, ~20 apart, ~140 between
        up = [110.2 + 20.1 * i for i in range(10)]
        lo = [431.5 + 20.8 * i for i in range(10)]
        got = lib1._value_panels(self.page(up + lo), True)
        self.assertEqual(len(got), 2)
        self.assertAlmostEqual(got[0][0], 110.2, places=1)
        self.assertAlmostEqual(got[1][0], 431.5, places=1)

    def test_one_frame_is_no_panels_at_all(self):
        # every other template we read; the filter must not engage
        ys = [110.0 + 20.0 * i for i in range(10)]
        self.assertEqual(lib1._value_panels(self.page(ys), True), [])

    def test_too_few_gridlines_to_judge(self):
        self.assertEqual(lib1._value_panels(self.page([100.0, 300.0]), True), [])

    def test_the_gap_is_taken_off_the_page_s_own_spacing(self):
        # a plot with gridlines 100 apart: a 140 gap is NOT a frame break
        ys = [100.0 + 100.0 * i for i in range(6)]
        self.assertEqual(lib1._value_panels(self.page(ys), True), [])

    def test_short_lines_are_not_gridlines(self):
        ys = [110.0 + 20.0 * i for i in range(10)] + \
             [431.0 + 20.0 * i for i in range(10)]
        # a value gridline runs the full width of its plot; tick marks do not
        self.assertEqual(lib1._value_panels(self.page(ys, 100.0, 150.0), True), [])

    def test_a_position_inside_a_panel(self):
        panels = [(110.2, 291.2), (431.5, 618.4)]
        self.assertEqual(lib1._panel_of(160.0, panels), 0)
        self.assertEqual(lib1._panel_of(570.0, panels), 1)

    def test_ink_past_the_outermost_gridline_still_belongs_to_its_panel(self):
        # the red pressure curve reaches y=310.9, past the last gridline at
        # 291.2 — a curve runs to the FRAME edge, not to a gridline
        panels = [(110.2, 291.2), (431.5, 618.4)]
        self.assertEqual(lib1._panel_of(310.9, panels), 0)
        self.assertEqual(lib1._panel_of(639.1, panels), 1)

    def test_the_legend_sitting_above_its_plot_still_resolves(self):
        # 00949's legends are at 88.5 (upper) and 417.7/425.4 (lower), each
        # ABOVE its own frame
        panels = [(110.2, 291.2), (431.5, 618.4)]
        self.assertEqual(lib1._panel_of(88.5, panels), 0)
        self.assertEqual(lib1._panel_of(425.4, panels), 1)

    def test_no_panels_means_no_opinion(self):
        self.assertIsNone(lib1._panel_of(160.0, []))


if __name__ == "__main__":
    unittest.main()
