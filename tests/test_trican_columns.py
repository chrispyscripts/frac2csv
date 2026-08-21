"""Trican's per-product columns, and the sum they must not contradict.

  python3 -m unittest tests.test_trican_columns

A chemical or a proppant is named by the JOB, not by the template — one
six-file sample prints four additives and six proppants — so they cannot live
in a fixed column list. They were handled by not being emitted at all
(chemicals: 141 of 141 stage pages populated, none reaching the output) or by
being summed into one number plus a names string (proppant), which is how a
stage that pumped 0.17 t of 50/140 beside 48 t of 40/70 came out as a single
figure.

The split is only safe if it IS a split: proppant_t and proppant_types keep
their old meaning exactly, so nothing already reading them changes.
"""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import trican2


class Slug(unittest.TestCase):
    def test_product_names_become_stable_column_names(self):
        self.assertEqual(trican2._slug("Sand 50/140"), "sand_50_140")
        self.assertEqual(trican2._slug("CRC-C 30/50"), "crc_c_30_50")
        self.assertEqual(trican2._slug("Busan 94"), "busan_94")
        self.assertEqual(trican2._slug("PowerProp 40/70"), "powerprop_40_70")

    def test_the_same_product_always_slugs_the_same(self):
        # two files of one job must line up column for column
        self.assertEqual(trican2._slug("Prime Plus 40/70"),
                         trican2._slug("prime plus 40/70"))

    def test_a_name_with_nothing_usable_still_yields_a_column(self):
        self.assertEqual(trican2._slug("///"), "x")
        self.assertEqual(trican2._slug(""), "x")


class ColumnsFor(unittest.TestCase):
    def test_the_fixed_schema_keeps_its_order(self):
        rows = [{"stage": 1, "max_mpa": 58.6, "start": "10:41"}]
        self.assertEqual(trican2.columns_for(rows),
                         ["stage", "start", "max_mpa"])

    def test_a_column_no_row_carries_is_left_out(self):
        self.assertNotIn("isip_mpa", trican2.columns_for([{"stage": 1}]))

    def test_products_come_after_the_schema_chemicals_first(self):
        rows = [{"stage": 1, "proppant_t": 60.07,
                 "prop_sand_40_70_t": 48.05, "prop_sand_50_140_t": 3.79,
                 "chem_fr_9_l": 634.44, "chem_busan_94_l": 255.23}]
        self.assertEqual(
            trican2.columns_for(rows),
            ["stage", "proppant_t", "chem_busan_94_l", "chem_fr_9_l",
             "prop_sand_40_70_t", "prop_sand_50_140_t"])

    def test_products_are_alphabetical_so_two_files_line_up(self):
        a = trican2.columns_for([{"prop_b_t": 1, "prop_a_t": 2}])
        b = trican2.columns_for([{"prop_a_t": 3, "prop_b_t": 4}])
        self.assertEqual(a, b)

    def test_the_volume_column_is_not_mistaken_for_a_product(self):
        # prop_vol_m3 starts with "prop_" and is part of the fixed schema
        cols = trican2.columns_for([{"stage": 1, "prop_vol_m3": 384.88}])
        self.assertEqual(cols, ["stage", "prop_vol_m3"])
        self.assertEqual(cols.count("prop_vol_m3"), 1)

    def test_rows_carrying_different_products_are_unioned(self):
        cols = trican2.columns_for([{"prop_a_t": 1}, {"prop_z_t": 2}])
        self.assertEqual(cols, ["prop_a_t", "prop_z_t"])


class FieldMap(unittest.TestCase):
    def test_the_two_rows_that_had_no_key(self):
        # printed on 140 and 9 stage pages measured, dropped for want of a key
        self.assertEqual(trican2.FIELD_MAP[("DH RATE", "Average Pad")],
                         "rate_avg_pad_m3min")
        self.assertEqual(trican2.FIELD_MAP[("DH SLURRY VOLUME", "Flush/Spacer")],
                         "flush_spacer_m3")

    def test_both_are_in_the_schema(self):
        for c in ("rate_avg_pad_m3min", "flush_spacer_m3"):
            self.assertIn(c, trican2.COLUMNS)

    def test_the_old_columns_are_all_still_there(self):
        # an ADDITIVE change: anything already exported must still export
        for c in ("stage", "start", "finish", "total_time_min", "breakdown_mpa",
                  "max_mpa", "avg_mpa", "min_mpa", "isip_mpa", "avg_pad_mpa",
                  "avg_prop_mpa", "rate_max_m3min", "rate_avg_m3min",
                  "rate_min_m3min", "conc_max_kgm3", "conc_avg_kgm3",
                  "pad_vol_m3", "prop_vol_m3", "water_m3", "proppant_t",
                  "proppant_types"):
            self.assertIn(c, trican2.COLUMNS)


if __name__ == "__main__":
    unittest.main()
