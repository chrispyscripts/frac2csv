"""The per-sample deduced flag, on its way from the reader to the Lab.

`_true_runs` turns the reader's per-sample bool into the [start, end) spans
the chart draws in pulsing black. It shipped in v1.10.0 written as
`enumerate(flags or ())`, which raises on a numpy array of more than one
element — that is to say, on every real channel. Nothing caught it: the
commit was written where fitz and pytest could not run, so the line was
parsed and never executed, and the whole feature was dead on real data
while looking correct in review.

The cases below are therefore mostly about TYPE, not about run-finding. The
reader hands this a numpy bool array and always has.

Run: python3 -m unittest discover tests -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                       # noqa: E402

import localapp                                          # noqa: E402


class TrueRuns(unittest.TestCase):
    def test_numpy_array_is_what_the_reader_sends(self):
        # trican_charts builds this as `np.nan_to_num(...) >= 0.5`
        flags = np.array([False, True, True, False, True])
        self.assertEqual(localapp._true_runs(flags), [[1, 3], [4, 5]])

    def test_all_false_array_is_no_runs_not_an_exception(self):
        # `flags or ()` raised here too, so a channel with nothing deduced
        # took the whole read down with it.
        self.assertEqual(localapp._true_runs(np.array([False, False, False])), [])

    def test_all_true_array_closes_at_the_end(self):
        self.assertEqual(localapp._true_runs(np.array([True, True, True])), [[0, 3]])

    def test_run_reaching_the_last_sample_is_closed(self):
        self.assertEqual(localapp._true_runs(np.array([False, True, True])), [[1, 3]])

    def test_no_flag_at_all(self):
        # a channel the reader never deduced anything for sends None
        self.assertEqual(localapp._true_runs(None), [])

    def test_empty(self):
        self.assertEqual(localapp._true_runs(np.array([], dtype=bool)), [])

    def test_lists_still_work(self):
        # the flatten sites are free to hand over a plain list
        self.assertEqual(localapp._true_runs([False, True, False, True]),
                         [[1, 2], [3, 4]])

    def test_single_element(self):
        self.assertEqual(localapp._true_runs(np.array([True])), [[0, 1]])


if __name__ == "__main__":
    unittest.main()
