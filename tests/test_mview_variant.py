"""Which MView sheet a page is, and what survives when the pair collapses.

Calfrac prints each zone twice — a "… Surface" sheet and a "… Bottom Hole"
sheet — and both carry Treating Pressure with different values. The tag is
what keeps them under separate keys; without it they share one key and that
channel ends up holding two recordings (#341).

Reading only the FIRST line was the same fault calfrac_progress.is_chart_page
had. A portrait MView sheet rotates the plot and OCR reads the y-axis tick
ladder before the caption, so page 73 of 00340 leads with "1400" and BOTH
sheets of every zone in the eight rotated filings came back untagged — the
#341 collision, in the files that had just been recovered from yielding
nothing at all.

And only ONE of the two sheets prints a date. When the Bottom Hole sheet won
the choice the stage lost its date on the way out: 17 of 52 charts dated on
00339, 22 of 52 on 00342.

Run: python3 -m unittest discover tests -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline                                          # noqa: E402


class _Page(object):
    pass


class Variant(unittest.TestCase):
    def setUp(self):
        self._real = pipeline.ocr_labels.page_text

    def tearDown(self):
        pipeline.ocr_labels.page_text = self._real

    def _tag(self, text):
        pipeline.ocr_labels.page_text = lambda page: text
        return pipeline._mview_variant(_Page())

    def test_landscape_title_on_the_first_line(self):
        self.assertEqual(self._tag(
            "Arc Hz Anten (Surf: 02-02) 100/04-10-066-25W5M Surface\n"),
            " Surface")
        self.assertEqual(self._tag(
            "Arc Hz Anten (Surf: 02-02) 100/04-10-066-25W5M Bottom Hole\n"),
            " BH")

    def test_rotated_sheet_leads_with_the_axis_ladder(self):
        # 00340 p73 and p74
        self.assertEqual(self._tag(
            "1400\n1000\n"
            "Arc Hz Anten (Surf: 02-02) 100/04-10-066-25W5M Surface\n"
            "Zone: 1/85\n"), " Surface")
        self.assertEqual(self._tag(
            "1400\n1000\n"
            "Arc Hz Anten (Surf: 02-02) 100/04-10-066-25W5M Bottom Hole\n"
            "Zone: 1/85\n"), " BH")

    def test_the_chemicals_sheet_is_neither(self):
        self.assertEqual(self._tag(
            "1400\nArc Hz 100/04-10-066-25W5M Chemicals\n"), "")

    def test_a_later_line_must_look_like_a_title(self):
        # the word alone, with no well named, is a column heading — the same
        # thing is_chart_page refuses
        self.assertEqual(self._tag("Treatment Summary\nZone\nSurface\n"), "")

    def test_an_unreadable_page_is_untagged_not_an_error(self):
        def boom(page):
            raise RuntimeError("no")
        pipeline.ocr_labels.page_text = boom
        self.assertEqual(pipeline._mview_variant(_Page()), "")


def _chart(stage, data, date="", start=""):
    return {"type": "series", "source": "CalFrac chart",
            "data": {k: [1.0] for k in data},
            "meta": {"stage": stage, "date": date, "start_time": start}}


class Collapse(unittest.TestCase):
    """_pick_variant keeps one sheet per zone. What it keeps must not be
    poorer than what it dropped."""

    def test_surface_wins_when_it_carries_all_four(self):
        res = [_chart("1 Surface", pipeline._CANON4),
               _chart("1 BH", ("Tr Press",))]
        notes = []
        pipeline._pick_variant(res, notes)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["meta"]["stage"], "1")
        self.assertEqual(len(res[0]["data"]), 4)

    def test_bottom_hole_wins_when_surface_is_short(self):
        res = [_chart("2 Surface", ("Tr Press", "Slurry Rate")),
               _chart("2 BH", pipeline._CANON4)]
        pipeline._pick_variant(res, [])
        self.assertEqual(len(res), 1)
        self.assertEqual(len(res[0]["data"]), 4)

    def test_the_date_is_carried_from_the_sheet_that_printed_it(self):
        # the Bottom Hole sheet prints no date and here it wins the choice
        res = [_chart("3 Surface", ("Tr Press",),
                      date="2022-03-01", start="04:12:00"),
               _chart("3 BH", pipeline._CANON4)]
        pipeline._pick_variant(res, [])
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["meta"]["date"], "2022-03-01")
        self.assertEqual(res[0]["meta"]["start_time"], "04:12:00")

    def test_the_kept_sheet_keeps_its_OWN_date(self):
        res = [_chart("4 Surface", pipeline._CANON4,
                      date="2022-03-02", start="09:00:00"),
               _chart("4 BH", ("Tr Press",),
                      date="1999-01-01", start="23:59:00")]
        pipeline._pick_variant(res, [])
        self.assertEqual(res[0]["meta"]["date"], "2022-03-02")
        self.assertEqual(res[0]["meta"]["start_time"], "09:00:00")

    def test_a_zone_with_one_sheet_is_untouched(self):
        res = [_chart("5 Surface", ("Tr Press",))]
        pipeline._pick_variant(res, [])
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["meta"]["stage"], "5 Surface")


if __name__ == "__main__":
    unittest.main()


class Retreatment(unittest.TestCase):
    """A zone treated twice is two treatments, paired by PAGE ORDER.

    00886 prints zones 1..31 with none missing and 35 Surface sheets: zones
    1, 13, 17 and 30 each ran twice. Its Bottom Hole sheets carry no zone
    number of their own and inherit the page before them, so the sheets arrive
    Surface(13), BH(13), Chemicals(13), ... Surface(13), BH(13).

    Keyed on kind alone, a dict kept whichever Surface and whichever BH came
    last, paired sheets from DIFFERENT treatments and stranded the rest —
    Carmine got zone 13 as "13", "13 Surface" and "13 BH" at once (#617).
    """

    def _run(self, *pairs):
        res, page = [], 0
        for stage, data in pairs:
            page += 1
            c = _chart(stage, data)
            c["page"] = page
            res.append(c)
        notes = []
        pipeline._pick_variant(res, notes)
        return res, notes

    def test_two_treatments_of_one_zone_both_collapse(self):
        res, notes = self._run(
            ("13 Surface", pipeline._CANON4), ("13 BH", ("Tr Press",)),
            ("13 Surface", pipeline._CANON4), ("13 BH", ("Tr Press",)))
        self.assertEqual(len(res), 2)
        # the second run keeps its own key so it cannot merge into the first
        self.assertEqual(sorted(str(r["meta"]["stage"]) for r in res),
                         ["13", "13 (2)"])
        self.assertTrue(any("treated more than once" in n for n in notes), notes)

    def test_each_surface_pairs_with_the_BH_that_FOLLOWS_it(self):
        # the first Surface is short, the second carries all four; pairing
        # across treatments would keep the wrong sheet for both
        res, _ = self._run(
            ("7 Surface", ("Tr Press",)), ("7 BH", pipeline._CANON4),
            ("7 Surface", pipeline._CANON4), ("7 BH", ("Tr Press",)))
        self.assertEqual(len(res), 2)
        for r in res:
            self.assertEqual(len(r["data"]), 4, r["meta"]["stage"])

    def test_a_lone_extra_sheet_is_left_alone(self):
        # Surface, its BH, then a second BH with no Surface of its own
        res, _ = self._run(
            ("4 Surface", pipeline._CANON4), ("4 BH", ("Tr Press",)),
            ("4 BH", ("Tr Press",)))
        self.assertEqual(sorted(str(r["meta"]["stage"]) for r in res),
                         ["4", "4 BH"])

    def test_a_bottom_hole_arriving_first_is_not_paired_backwards(self):
        # Every sheet pair in the corpus runs Surface then Bottom Hole. A BH
        # that arrives with no Surface open is therefore an ordering nothing
        # here has seen, and both sheets are left alone and stay visible
        # rather than paired on an assumption. Asserted because the first
        # version of this test assumed the pairing instead of the layout.
        res, _ = self._run(
            ("9 BH", ("Tr Press",)), ("9 Surface", pipeline._CANON4))
        self.assertEqual(sorted(str(r["meta"]["stage"]) for r in res),
                         ["9 BH", "9 Surface"])

    def test_a_zone_treated_once_gets_no_suffix(self):
        res, notes = self._run(
            ("2 Surface", pipeline._CANON4), ("2 BH", ("Tr Press",)))
        self.assertEqual(str(res[0]["meta"]["stage"]), "2")
        self.assertFalse(any("treated more than once" in n for n in notes))


if __name__ == "__main__":
    unittest.main()
