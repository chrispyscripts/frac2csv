"""A legend that half-read keeps the chart's clean rate.

A STEP chemical chart names its pens in a legend under the plot, and those
replace the colour table's. On 00050 p140 (2026 STEP) the legend read two of
its three columns, the SFR-990Z pens, and not the clean rate, so the chart
lost the Combined Clean Rate that v1.11.53 read. Now the colour table's rate
pen stays wherever the legend did not name a clean rate.

Run: python3 -m unittest discover tests -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import step1                                             # noqa: E402


def pen(label):
    return {"label": label}


def labels(chs):
    return [c["label"] for c in chs]


class LegendCleanRate(unittest.TestCase):
    TABLE = [pen("Slurry Rate"), pen("Surface Pressure"), pen("Prop Conc")]

    def test_the_00050_p140_shape_keeps_the_rate_pen(self):
        out = step1._with_legend_pens(self.TABLE, [pen("SFR-9902Z"), pen("Sfr -9907")], "rate")
        self.assertEqual(labels(out), ["SFR-9902Z", "Sfr -9907", "Slurry Rate"])

    def test_a_legend_that_names_the_clean_rate_replaces_everything(self):
        out = step1._with_legend_pens(
            self.TABLE, [pen("Combined Clean Rate"), pen("SFR-202 Conc")], "rate")
        self.assertEqual(labels(out), ["Combined Clean Rate", "SFR-202 Conc"])

    def test_a_clean_rate_already_named_in_the_table_stays(self):
        out = step1._with_legend_pens(
            [pen("Clean Rate"), pen("Surface Pressure")], [pen("Aqucar 742 Conc")], "conc")
        self.assertEqual(labels(out), ["Aqucar 742 Conc", "Clean Rate"])

    def test_a_pressure_legend_adds_to_the_table(self):
        out = step1._with_legend_pens(self.TABLE, [pen("G Well Offset Pressure")], "pressure")
        self.assertEqual(labels(out), labels(self.TABLE) + ["G Well Offset Pressure"])

    def test_the_table_is_not_changed_in_place(self):
        table = list(self.TABLE)
        step1._with_legend_pens(table, [pen("SFR-9902Z")], "rate")
        self.assertEqual(labels(table), labels(self.TABLE))


if __name__ == "__main__":
    unittest.main()
