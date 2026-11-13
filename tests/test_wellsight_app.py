"""A WellSight log dropped on the Lab is recognised and read to LAS.

No client log ships with the repo, so the full read runs only where the
SK-VIKING drive (or F2C_WS_SAMPLES, a folder of .sl6/.slg/.hl6/.hlg files)
is present; the rest needs nothing.

Run: python3 -m unittest tests.test_wellsight_app
"""
import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wellsight_app as wa                                    # noqa: E402

DRIVE = "/Volumes/CnC-2TB-ssd/SK-VIKING/WellSight/s-h-sl"
SAMPLES = os.environ.get("F2C_WS_SAMPLES") or DRIVE


def samples(n=4):
    out = []
    for sub in ("", "HLG", "SLG"):
        for ext in wa.EXTS:
            out += sorted(glob.glob(os.path.join(SAMPLES, sub, "*" + ext)))[:2]
    return out[:n]


class Recognise(unittest.TestCase):
    def test_names(self):
        for n in ("A.sl6", "b.SLG", "c.hl6", "D.HLG", "e.sl8", "f.ml6"):
            self.assertTrue(wa.is_wellsight_name(n), n)
        for n in ("report.pdf", "list.txt", "x.las", "x.sl6.pdf"):
            self.assertFalse(wa.is_wellsight_name(n), n)

    def test_signature(self):
        self.assertTrue(wa.looks_like_wellsight(b"AACS" + bytes(124)))
        self.assertTrue(wa.looks_like_wellsight(bytes(8) + b"STRIP.LOG 6.5.0" + bytes(9)))
        self.assertFalse(wa.looks_like_wellsight(b"%PDF-1.7\n"))

    def test_not_a_log_says_so(self):
        with self.assertRaises(wa.NotWellSight) as cm:
            wa.read(b"%PDF-1.7 this is not a strip log" + bytes(500), "oops.sl6")
        self.assertIn("oops.sl6", str(cm.exception))


@unittest.skipUnless(samples(), "no WellSight sample logs on this machine")
class Read(unittest.TestCase):
    def test_reads_to_las(self):
        for path in samples():
            with open(path, "rb") as f:
                out = wa.read(f.read(), os.path.basename(path))
            p, files = out["payload"], out["files"]
            name = os.path.basename(path)
            self.assertIn(name + ".las", files, name)
            self.assertTrue(files[name + ".las"].startswith(b"~V"), name)
            self.assertIn(name + ".json", files)
            if p["curves"]:
                self.assertIn(name + ".curves-0.2m.las", files)
                self.assertEqual(len(p["curves"][0]["values"]), p["rows"])
            self.assertIn(p["axis"], ("MD", "TVD"))
            # rock types, accessories and other symbols, read into one vocabulary
            a = p["analysis"]
            self.assertEqual(a["symbols"], len(p["symbols"]), name)
            self.assertEqual(len(p["rocks"]) > 0, len(a["rocks"]) > 0, name)
            if p["rocks"]:
                self.assertIn(name + ".rock-types.csv", files)
            if p["symbols"]:
                self.assertIn(name + ".symbols.csv", files)
                self.assertLessEqual(a["unknown_symbols"], 0.05 * a["symbols"], name)


if __name__ == "__main__":
    unittest.main()
