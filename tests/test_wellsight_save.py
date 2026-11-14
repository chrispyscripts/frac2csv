"""Save LAS (wellsight_server.save): one LAS file, the curve track only.

The store's records are made up here; with the WellSight sample logs on
this machine (F2C_WS_SAMPLES), real logs are decoded and saved too.

Run: python3 -m unittest tests.test_wellsight_save
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import wellsight_server as wss                                  # noqa: E402


def keep(folder, _dest):
    return folder, ""


class Save(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="f2c-save-")

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def put(self, i, las, files=None):
        wss._put({"id": i, "payload": {"file": i + ".sl6"}, "files": files or {}, "native": b"",
                  "strip": b"%PDF-strip", "strip_info": {}, "printout_raw": b"%PDF-printout", "las": las})

    def test_one_las_file_and_nothing_else(self):
        self.put("s1", ("s1.las", b"~Version\n"),
                 {"s1.sl6.csv": b"x", "s1.sl6.json": b"{}", "s1.sl6.rock-types.csv": b"x"})
        code, out = wss.save({"id": "s1", "folder": self.out}, keep)
        self.assertEqual(code, 200)
        self.assertEqual(out["written"], ["s1.las"])
        self.assertEqual(sorted(os.listdir(self.out)), ["s1.las"])
        with open(os.path.join(self.out, "s1.las"), "rb") as f:
            self.assertEqual(f.read(), b"~Version\n")

    def test_a_log_with_no_curve_track(self):
        self.put("s2", None)
        code, out = wss.save({"id": "s2", "folder": self.out}, keep)
        self.assertEqual(code, 422)
        self.assertEqual(os.listdir(self.out), [])

    def test_names(self):
        self.assertEqual(wss._las_file("0229--LOG_HZ.slg", b"x", ".las"), ("0229--LOG_HZ.las", b"x"))
        self.assertEqual(wss._las_file("0229--LOG_HZ.pdf", b"x", ".from-printout.las"),
                         ("0229--LOG_HZ.from-printout.las", b"x"))
        self.assertIsNone(wss._las_file("a.sl6", None, ".las"))


SAMPLES = os.environ.get("F2C_WS_SAMPLES", "")


def samples():
    import glob
    out = []
    for ext in (".sl6", ".slg", ".hl6", ".hlg"):
        out += sorted(glob.glob(os.path.join(SAMPLES, "*" + ext)))
    return out[:2] if SAMPLES else []


@unittest.skipUnless(samples(), "no WellSight sample logs on this machine")
class RealLogs(unittest.TestCase):
    def test_the_curve_track_on_its_finest_step(self):
        import base64
        import wellsight_app as wa
        import wellsight as ws
        import export_las as el
        out = tempfile.mkdtemp(prefix="f2c-save-")
        try:
            for path in samples():
                with open(path, "rb") as f:
                    data = f.read()
                code, resp = wss.decode({"filename": os.path.basename(path),
                                         "data": base64.b64encode(data).decode()})
                self.assertEqual(code, 200)
                code, saved = wss.save({"id": resp["id"], "folder": out}, keep)
                self.assertEqual(code, 200, path)
                stem = os.path.splitext(os.path.basename(path))[0]
                self.assertEqual(saved["written"], [stem + ".las"])
                with open(os.path.join(out, stem + ".las"), encoding="utf-8", errors="replace") as f:
                    las = f.read()
                log = ws.read_log(data)
                track = el.curve_track_curves(log)
                step_line = next(ln for ln in las.splitlines() if ln.split(".")[0].strip() == "STEP")
                step = float(step_line.split(":")[0].split()[-1])
                self.assertAlmostEqual(step, min(c["step"] for c in track), places=4)
                ascii_head = las.split("~A")[1].splitlines()[0].split()
                self.assertEqual(len(ascii_head), len(track) + 1)           # DEPT + one per curve
                self.assertNotIn("~A", las.split("~A")[1])
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
