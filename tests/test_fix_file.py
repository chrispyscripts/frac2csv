"""The user's fix file: stage numbers, dates and times a report does not print.

00570 (AER Duvernay, #813) prints no date anywhere. Carmine: "allow in edit
mode to read a text file that has stage number year date one line per stage
or even for these odd case allow the text file to even say what page".

  python3 -m unittest tests.test_fix_file
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline                                          # noqa: E402

FIX = """# stage, date, time, page
1, 2018-09-03
2, 2018-09-03, 17:10
7, , , p154
3, 03-Sep-2018, 25:00
"""


class Parse(unittest.TestCase):
    def test_the_lines_and_what_is_not_understood(self):
        rows, problems = pipeline.parse_fix_file(FIX)
        self.assertEqual(rows[0], {"stage": "1", "date": "2018-09-03", "time": "", "page": None})
        self.assertEqual(rows[1]["time"], "17:10:00")
        self.assertEqual(rows[2]["page"], 154)
        self.assertEqual(rows[3]["date"], "2018-09-03")
        self.assertEqual(len(problems), 1)
        self.assertIn("25:00", problems[0])


class Doc:
    def __init__(self, name):
        self.name = name


def chart(page, stage, title=None):
    return {"type": "series", "page": page,
            "meta": {"stage": stage, "title": title or f"Interval {stage}", "date": "",
                     "start_time": "00:14:37", "warnings": []}}


class Apply(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.pdf = os.path.join(self.dir, "00570-X_COMP.pdf")
        open(self.pdf, "wb").write(b"%PDF-1.4\n")

    def test_no_file_changes_nothing(self):
        rs = [chart(152, "1")]
        self.assertEqual(pipeline._apply_fix_file(Doc(self.pdf), rs, []), 0)
        self.assertEqual(rs[0]["meta"]["date"], "")

    def test_dates_times_and_page_numbers_are_applied(self):
        open(os.path.join(self.dir, "00570-X_COMP.fix.txt"), "w").write(FIX)
        rs = [chart(152, "1"), chart(153, "2"), chart(154, "", "PRC Plot")]
        notes = []
        pipeline._apply_fix_file(Doc(self.pdf), rs, notes)
        self.assertEqual(rs[0]["meta"]["date"], "2018-09-03")
        self.assertEqual(rs[0]["meta"]["start_time"], "00:14:37")      # no time given
        self.assertEqual(rs[1]["meta"]["start_time"], "17:10:00")
        self.assertEqual(rs[2]["meta"]["stage"], "7")
        self.assertEqual(rs[2]["meta"]["title"], "Stage 7")
        self.assertIn("fix file 00570-X_COMP.fix.txt", notes[0])
        self.assertIn("Not understood", notes[0])

    def test_the_final_pass_puts_back_what_a_later_pass_changed(self):
        open(os.path.join(self.dir, "00570-X_COMP.fix.txt"), "w").write(FIX)
        rs = [chart(152, "1")]
        pipeline._apply_fix_file(Doc(self.pdf), rs, [])
        rs[0]["meta"]["date"] = "2018-09-02"
        notes = []
        pipeline._apply_fix_file(Doc(self.pdf), rs, notes, final=True)
        self.assertEqual(rs[0]["meta"]["date"], "2018-09-03")
        self.assertEqual(notes, [])


if __name__ == "__main__":
    unittest.main()
