"""The header window's data (wellsight_server.header and its pictures).

The logs here are made up in the shape the decoder leaves them in the
server's store: a header page's fields, its boxes, a custom header page's
lines, picture headers among the converter's files, and a printout.

Run: python3 -m unittest tests.test_wellsight_header
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wellsight_server as wss                                  # noqa: E402


def rec(i, header, head, files=None, printout=None, info=None):
    r = {"id": i, "payload": {"file": i + ".sl6", "well": header.get("well_name", ""), "header": header},
         "header": head, "files": files or {}, "native": b"", "strip": None, "strip_info": info}
    if printout:
        r["printout_raw"], r["printout_doc"] = printout, None
    wss._put(r)
    return i


def blank_pdf(pages):
    import fitz
    d = fitz.open()
    for _ in range(pages):
        d.new_page(width=612, height=792)
    return d.tobytes()


class Fields(unittest.TestCase):
    def test_template_fields_in_the_page_order_with_their_units(self):
        i = rec("t1", {"total_depth": "2947", "well_name": "Made-up Hz", "kb_elevation": "604.5",
                       "logged_interval_top": "575", "logged_interval_bottom": "815", "licence": "00A000",
                       "operator": "Made-up Resources", "completion_date": ""},
                {"source": "template", "boxes": []})
        code, h = wss.header({"id": i})
        self.assertEqual(code, 200)
        self.assertEqual([f["label"] for f in h["fields"]],
                         ["Well name", "Licence", "K.B. elevation (m)", "Logged interval (m)", "Total depth (m)",
                          "Operator"])
        self.assertEqual(h["fields"][3]["value"], "575 to 815")

    def test_a_custom_page_states_its_own_units(self):
        i = rec("c1", {"total_depth": "1403.00 m MD", "well_name": "Made-up Hz"},
                {"source": "custom header page", "boxes": [], "custom": ["WELL INFORMATION", "OPERATOR: MADE-UP"]})
        _c, h = wss.header({"id": i})
        self.assertIn("Total depth", [f["label"] for f in h["fields"]])
        self.assertEqual(h["custom"], ["WELL INFORMATION", "OPERATOR: MADE-UP"])

    def test_boxes_with_their_field_names_and_no_repeats(self):
        i = rec("b1", {"well_name": "Made-up Hz", "operator": "Made-up Resources", "geologist_company": "Rocks Ltd."},
                {"source": "template", "boxes": [
                    {"title": "OPERATOR", "kind": 2, "fields": ["", "Made-up Resources", ""], "text": ""},
                    {"title": "GEOLOGIST", "kind": 3, "fields": ["A. Person", "Rocks Ltd.", "1 Street\nTown"], "text": ""},
                    {"title": "DRILLING", "kind": 4, "fields": [], "text": "Drilling Rig: 1\n\nSupervisor: B\n"},
                    {"title": "EMPTY", "kind": 6, "fields": [], "text": ""}]})
        _c, h = wss.header({"id": i})
        self.assertEqual([f["label"] for f in h["fields"]], ["Well name"])    # the boxes say the rest
        self.assertEqual([b["title"] for b in h["boxes"]], ["OPERATOR", "GEOLOGIST", "DRILLING"])
        self.assertEqual(h["boxes"][0]["rows"], [{"label": "Company", "value": "Made-up Resources"}])
        self.assertEqual([r["label"] for r in h["boxes"][1]["rows"]], ["Name", "Company", "Address"])
        self.assertEqual([r["value"] for r in h["boxes"][2]["rows"]], ["Drilling Rig: 1", "Supervisor: B"])

    def test_a_log_no_longer_loaded(self):
        self.assertEqual(wss.header({"id": "gone"})[0], 404)


class Pages(unittest.TestCase):
    def test_the_printout_pages_before_the_log(self):
        info = {"placed": [{"page": 3}, {"page": 4}], "left_out": [1, 2, 5], "source": "x.pdf"}
        i = rec("p1", {"well_name": "W"}, {"source": "template", "boxes": []}, printout=blank_pdf(5), info=info)
        _c, h = wss.header({"id": i})
        self.assertEqual(h["pages"], [1, 2])               # not the page after the log
        code, png = wss.header_page_png({"id": i, "page": "1", "w": "600"})
        self.assertEqual(code, 200)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(wss.header_page_png({"id": i, "page": "9"})[0], 404)

    def test_no_printout(self):
        i = rec("n1", {"well_name": "W"}, {"source": "template", "boxes": []})
        _c, h = wss.header({"id": i})
        self.assertEqual((h["pages"], h["printout"]), ([], ""))
        self.assertEqual(wss.header_page_png({"id": i})[0], 404)

    def test_picture_headers_in_order(self):
        files = {"x.sl6.picture-10.png": b"ten", "x.sl6.picture-2.png": b"two", "x.sl6.las": b""}
        i = rec("g1", {}, {"source": None, "boxes": []}, files=files)
        _c, h = wss.header({"id": i})
        self.assertEqual(h["pictures"], 2)
        self.assertEqual(wss.header_picture_png({"id": i, "n": "1"}), (200, b"two"))
        self.assertEqual(wss.header_picture_png({"id": i, "n": "2"}), (200, b"ten"))
        self.assertEqual(wss.header_picture_png({"id": i, "n": "3"})[0], 404)


if __name__ == "__main__":
    unittest.main()
