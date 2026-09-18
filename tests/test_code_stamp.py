"""The cache key has to change when the build does.

code_stamp() stamped the cache with the newest reader .py mtime. A PyInstaller
onefile build has no reader .py on disk — the modules are compiled into the PYZ
and loaded by its own importer, and only data files reach _MEIPASS — so the
loop found nothing, `newest` stayed 0, and the stamp was the string "0" on
every build ever shipped. The cache key never changed between versions.

The consequence was not theoretical. The chart handover trim shipped in
v1.10.0; Carmine kept being served pre-v1.10.0 results for every file he had
read before, and only saw it when reuse was removed in v1.11.2 — at which
point it arrived across five providers in one night and read as a regression.

Nothing caught it because from source the loop works, and from source is the
only place the tests and the developer ever run.

Run: python3 -m unittest discover tests -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import localapp                                          # noqa: E402
from version import VERSION                              # noqa: E402


class CodeStamp(unittest.TestCase):
    def setUp(self):
        localapp._CODE_STAMP = None
        self._frozen = getattr(sys, "frozen", None)
        self._meipass = getattr(sys, "_MEIPASS", None)

    def tearDown(self):
        localapp._CODE_STAMP = None
        for name, val in (("frozen", self._frozen), ("_MEIPASS", self._meipass)):
            if val is None:
                if hasattr(sys, name):
                    delattr(sys, name)
            else:
                setattr(sys, name, val)

    def test_frozen_stamps_the_version_not_zero(self):
        sys.frozen = True
        self.assertEqual(localapp.code_stamp(), "v" + VERSION)

    def test_frozen_stamp_is_never_the_old_constant(self):
        # The exact shape of the bug: every build stamped "0".
        sys.frozen = True
        self.assertNotEqual(localapp.code_stamp(), "0")

    def test_meipass_alone_is_enough_to_be_frozen(self):
        sys._MEIPASS = "/tmp/nowhere"
        self.assertEqual(localapp.code_stamp(), "v" + VERSION)

    def test_from_source_still_uses_the_reader_mtimes(self):
        # Unfrozen, the stamp is an mtime — digits, and not the version.
        for name in ("frozen", "_MEIPASS"):
            if hasattr(sys, name):
                delattr(sys, name)
        stamp = localapp.code_stamp()
        self.assertTrue(stamp.isdigit(), f"expected an mtime, got {stamp!r}")
        self.assertNotEqual(stamp, "0")

    def test_the_stamp_reaches_the_cache_key(self):
        # A stamp nobody consults is not a fix. cache_key stats the file, so
        # this needs a real one.
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(b"%PDF-1.4\n"); f.flush()
            localapp._CODE_STAMP = None
            sys.frozen = True
            a = localapp.cache_key(f.name)
            localapp._CODE_STAMP = "a-different-build"
            b = localapp.cache_key(f.name)
        self.assertNotEqual(a, b, "cache_key ignores code_stamp")


if __name__ == "__main__":
    unittest.main()
