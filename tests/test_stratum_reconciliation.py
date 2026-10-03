import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('reconcile', Path(__file__).parents[1] / 'web/scripts/reconcile_stages.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReconciliationTest(unittest.TestCase):
    def run_audit(self, summaries, depths):
        return module.reconcile(dict(well={'wa': 'test'}, engineering_stages=summaries,
                                     depth_intervals=depths))

    def test_missing_middle_stage_does_not_shift_later_depths(self):
        r = self.run_audit([dict(n=1,label='1',top_m=4000),dict(n=2,label='2',top_m=3900)],
            [dict(n=1,top_m=4000,base_m=4000.1),dict(n=2,top_m=3950,base_m=3950.1),dict(n=3,top_m=3900,base_m=3900.1)])
        self.assertEqual([x['depth_order'] for x in r['rows']], [1,3])
        self.assertEqual(r['intervals_without_verified_summary'][0]['depth_order'], 2)

    def test_equal_numbers_without_depths_are_unverified(self):
        r = self.run_audit([dict(n=1,label='1',top_m=None)], [dict(n=1,top_m=4000,base_m=4000.1)])
        self.assertIsNone(r['rows'][0]['depth_order'])
        self.assertEqual(r['rows'][0]['status'], 'no_printed_depth')

    def test_duplicate_and_missing_depths_are_not_silently_matched(self):
        r = self.run_audit([dict(n=1,label='1',top_m=4000),dict(n=2,label='2',top_m=3900)],
            [dict(n=1,top_m=4000,base_m=4000.1),dict(n=2,top_m=4000,base_m=4000.1)])
        self.assertEqual([x['status'] for x in r['rows']], ['ambiguous_depth','summary_depth_only'])

    def test_rounding_and_multiple_treatments_preserved(self):
        r = self.run_audit([dict(n=1,label='1',top_m=4000.1),dict(n=2,label='1A',top_m=4000)],
            [dict(n=9,top_m=4000,base_m=4000.1)])
        self.assertEqual([x['depth_order'] for x in r['rows']], [9,9])


if __name__ == '__main__': unittest.main()
