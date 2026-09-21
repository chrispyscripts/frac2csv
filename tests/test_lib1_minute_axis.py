"""A chart captioned "Time (min)" must read whichever way round it is drawn.

Liberty prints a treatment plot and a chemical plot per stage. The treatment
plot carries a wall clock; the chemical plot captions its axis "Time (min)"
and prints elapsed minutes. _horizontal decided orientation ONLY from clock
labels, so a chemical plot — no clocks — was called "rotated", the spans were
never swapped, the minute ladder was looked for down a column that does not
exist, and the page died with "time labels not found".

01004 (#691): 26 of 100 charts, every one a chemical plot, while all 50
treatment plots read perfectly. After: 99 read, 1 left — and that one is a
genuine OCR loss, its right-hand time label coming back as "Ss".

These pages are OCR'd (their text layer is unreadable), which breaks two more
assumptions: the caption arrives as two spans, "Time" and "(min)", and an
edge label can be swallowed by whatever sits beside it — 01004 p202 prints
9 / 52 / 95 and the 9 comes back merged into the orange axis label as "0.09".
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lib1


def span(t, cx, cy, color=0, ocr=True):
    return {"t": t, "cx": cx, "cy": cy, "color": color, "ocr": ocr}


def chemical_page(horizontal=True):
    """01004 p202's spans, to scale: caption split in two, ladder 52/95."""
    out = [span("Time", 329.8, 517.3), span("(min)", 354.2, 518.2),
           span("52", 383.9, 498.2), span("95", 667.8, 498.2),
           # the value ladder down the right-hand edge, which must NOT be read
           # as time
           span("2.0", 720.9, 124.9), span("1.6", 721.3, 196.6),
           span("1.2", 721.3, 268.4), span("0.8", 720.9, 341.3),
           span("0.4", 720.9, 412.9), span("0.0", 720.9, 484.7)]
    if not horizontal:
        return out
    return out


class Caption(unittest.TestCase):

    def test_ocr_splits_the_caption_and_it_is_still_found(self):
        got = lib1._min_caption(chemical_page())
        self.assertIsNotNone(got)
        self.assertAlmostEqual(got[0], 342.0, places=1)

    def test_it_is_found_after_the_landscape_swap_too(self):
        sw = [{**s, "cx": s["cy"], "cy": s["cx"]} for s in chemical_page()]
        self.assertIsNotNone(lib1._min_caption(sw))

    def test_a_single_span_caption_still_works(self):
        self.assertIsNotNone(lib1._min_caption([span("Time (min)", 342.0, 517.7)]))

    def test_no_caption_means_none(self):
        self.assertIsNone(lib1._min_caption([span("Pressure (kPa)", 342.0, 517.7)]))


class Orientation(unittest.TestCase):

    def test_a_chemical_plot_with_no_clock_reads_as_landscape(self):
        self.assertTrue(lib1._horizontal(chemical_page()))

    def test_a_clock_still_decides_when_there_is_one(self):
        # two clocks spread along x -> landscape, whatever the minute ladder says
        s = chemical_page() + [span("13:52", 200.0, 498.2),
                               span("15:27", 600.0, 498.2)]
        self.assertTrue(lib1._horizontal(s))

    def test_a_rotated_elapsed_page_is_not_called_landscape(self):
        # the ladder runs DOWN a column: 00628's shape
        s = [span("Time (min)", 60.0, 300.0)]
        s += [span(str(v), 60.0, 100.0 + i * 40.0)
              for i, v in enumerate((0, 11, 22, 33, 44, 55))]
        self.assertFalse(lib1._horizontal(s))


class Ladder(unittest.TestCase):

    def test_two_ticks_are_enough_on_an_ocr_page(self):
        self.assertTrue(lib1._even_ladder([(52.0, 383.9), (95.0, 667.8)], 2))

    def test_but_not_when_the_text_layer_was_readable(self):
        self.assertFalse(lib1._even_ladder([(52.0, 383.9), (95.0, 667.8)], 3))

    def test_a_ladder_must_ascend(self):
        self.assertFalse(lib1._even_ladder([(95.0, 383.9), (52.0, 667.8)], 2))

    def test_uneven_steps_are_a_value_axis_not_a_time_one(self):
        self.assertFalse(
            lib1._even_ladder([(0.0, 10.0), (1.0, 20.0), (9.0, 30.0)], 3))

    def test_the_value_ladder_is_not_mistaken_for_time(self):
        # 2.0 .. 0.0 down the right edge is nowhere near the caption
        got = lib1._minute_ladder(chemical_page(), True)
        self.assertEqual([v for v, _ in got], [52.0, 95.0])


if __name__ == "__main__":
    unittest.main()
