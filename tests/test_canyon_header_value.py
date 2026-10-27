"""Canyon: an interval printed bare in the header, without its "#".

  python3 -m unittest tests.test_canyon_header_value

00232/00233 print "Interval: 1", 00240 "Comment: 1", and 00211 p57 / 00213
p75 drop the "#" on one page of a report that writes "#13" everywhere else.
The labels and the values come apart in the text stream, so the value is read
by position: the span on the label's own line, just to its right.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import canyon                                             # noqa: E402


def span(t, x0, x1, cy):
    return {"t": t, "x0": x0, "x1": x1, "cx": (x0 + x1) / 2, "cy": cy}


# the header block of 00240 p28, positions as the page gives them
HEADER = [
    span("Ticket #:", 330.1, 365.0, 20.5), span("40-019212", 372.0, 410.0, 20.5),
    span("Date:", 343.5, 365.0, 60.5), span("2017-11-08", 372.0, 415.0, 60.5),
    span("Comment:", 330.0, 365.0, 70.5), span("1", 372.0, 376.5, 70.5),
]


class HeaderValue(unittest.TestCase):

    def test_the_value_on_the_labels_line(self):
        self.assertEqual(canyon._header_value(HEADER, ("interval", "comment")), "1")

    def test_the_interval_label_reads_the_same_way(self):
        spans = [span("Interval:", 335.0, 365.0, 70.5), span("1", 372.0, 376.5, 70.5)]
        self.assertEqual(canyon._header_value(spans, ("interval", "comment")), "1")

    def test_a_value_on_another_line_is_not_taken(self):
        spans = [span("Comment:", 330.0, 365.0, 70.5), span("2017-11-08", 372.0, 415.0, 60.5)]
        self.assertIsNone(canyon._header_value(spans, ("interval", "comment")))

    def test_no_label_no_value(self):
        self.assertIsNone(canyon._header_value(HEADER[:4], ("interval", "comment")))


if __name__ == "__main__":
    unittest.main()
