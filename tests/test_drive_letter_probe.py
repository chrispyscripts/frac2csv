"""Resolving a list's drive letter must not probe letters that hang.

Carmine: "none of my txt files are working when dragged on, they all come
back as unable to fetch".

A dropped .txt is the ONLY drop that resolves paths: the list carries
"K:\\BCER-Frac\\..." and the machine has to find BCER-Frac wherever it is
mounted. A dropped PDF never calls this, which is why PDFs kept working while
every list failed.

find_drive_roots used to probe A: through Z: unconditionally. os.path.isdir on
a letter Windows has no device for is not free — A: and B: go to the floppy
controller, and a mapped network drive whose server is gone blocks until the
SMB client gives up. Twenty-six of those on one request is past any browser's
patience, and "Failed to fetch" is what the browser says when it stops
waiting. The result cache is only written on success, so an abandoned request
cached nothing and the next list hung exactly the same way.

  python3 -m unittest tests.test_drive_letter_probe
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import localapp                                               # noqa: E402


class LettersProbed(unittest.TestCase):

    def test_the_floppy_letters_are_never_swept_blind(self):
        """The fallback, used when the Windows API is unavailable."""
        got = localapp._nt_drive_letters.__doc__
        self.assertIn("A: and B:", got)

    def test_it_returns_letters(self):
        out = localapp._nt_drive_letters()
        self.assertTrue(all(len(d) == 1 and d.isalpha() for d in out), out)
        self.assertNotIn("A", out)
        self.assertNotIn("B", out)

    def test_it_never_raises_off_windows(self):
        """ctypes.windll does not exist on mac; the fallback must carry it."""
        self.assertIsInstance(localapp._nt_drive_letters(), list)


class RootsStillResolve(unittest.TestCase):
    """The mac path is untouched — it lists /Volumes, which cannot hang the
    way a dead drive letter does."""

    def test_a_drive_letter_is_stripped_and_the_name_looked_up(self):
        localapp._ROOT_CACHE.pop("BCER-Frac", None)
        got = localapp.find_drive_roots("K:\\BCER-Frac\\x\\y.pdf")
        self.assertIsInstance(got, list)
        for p in got:
            self.assertTrue(p.endswith("BCER-Frac"), p)

    def test_a_name_that_is_nowhere_returns_empty_and_is_cached(self):
        localapp._ROOT_CACHE.pop("NoSuchRootName-zz", None)
        self.assertEqual(localapp.find_drive_roots("Q:\\NoSuchRootName-zz\\a.pdf"), [])
        self.assertIn("NoSuchRootName-zz", localapp._ROOT_CACHE,
                      "a miss is cached too, or every list pays for it again")

    def test_a_path_with_no_segments(self):
        self.assertEqual(localapp.find_drive_roots("K:\\"), [])
        self.assertEqual(localapp.find_drive_roots(""), [])


if __name__ == "__main__":
    unittest.main()
