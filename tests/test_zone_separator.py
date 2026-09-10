"""How a chart's stage/zone caption is separated from its number.

Three separators, all real caption forms in this corpus:
  "Zone 7"      the plain one
  "Zone #1"     MView's 2021 Strathcona charts (#579 — requiring whitespace
                missed every one, and a 100-chart filing came through with the
                stage unknown on all of it, merged under one "?" key)
  "Zone: 1/85"  the MView PORTRAIT sheet — zone, then the job's zone count.
                8 filings, 2,798 pages, same failure as #579.

And two that must NOT match:
  "Zone1"               no separator; also guards a bare "Zone12" inside a
                        longer token
  "Zone / 403-999-6540" a phone number under a "Zone" column header on the
                        daily-report sheets. Slash-separated, so the colon
                        does not reopen it.

Run: python3 -m unittest discover tests -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re                                                # noqa: E402
import inspect                                           # noqa: E402

import frac_core                                         # noqa: E402


def _pattern():
    """The live pattern out of detect_text_meta, so this test cannot drift
    from the code it is asserting about."""
    src = inspect.getsource(frac_core.detect_text_meta)
    m = re.search(r'm = re\.search\(r"(\(\?:Zone\|Stage\).*?)", text\)', src)
    assert m, "the Zone/Stage pattern moved — update this test"
    return re.compile(m.group(1))


class ZoneSeparator(unittest.TestCase):
    def setUp(self):
        self.pat = _pattern()

    def _stage(self, text):
        m = self.pat.search(text)
        return m.group(1) if m else None

    def test_plain_space(self):
        self.assertEqual(self._stage("Zone 7"), "7")

    def test_hash(self):
        self.assertEqual(self._stage("102/06-21 - Zone #1"), "1")

    def test_colon_with_a_zone_count(self):
        # "Zone: 1/85" — the number wanted is the zone, not the count
        self.assertEqual(self._stage("Zone: 1/85"), "1")
        self.assertEqual(self._stage("Zone: 12/85"), "12")

    def test_stage_reads_the_same_three_ways(self):
        for t, want in (("Stage 4", "4"), ("Stage #4", "4"), ("Stage: 04", "04")):
            self.assertEqual(self._stage(t), want, t)

    def test_no_separator_does_not_match(self):
        self.assertIsNone(self._stage("Zone1"))
        self.assertIsNone(self._stage("Zone12 of the pad"))

    def test_a_phone_number_under_a_zone_header_does_not_match(self):
        self.assertIsNone(self._stage("Zone / 403-999-6540"))
        self.assertIsNone(self._stage("Zone\n/ 780-779-3782"))


if __name__ == "__main__":
    unittest.main()
