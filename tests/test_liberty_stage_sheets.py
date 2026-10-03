"""Liberty's stage-keyed summary sheets (#767).

Six different Tableau sheets lead with "Stage No", and the Summary view used
to label every one of them "Proppant Summary" — so nothing on them could be
parsed. The fixtures are the page text and the cell spans of 49367 (the 2025
vintage, VERMILION HZ MICA F09-21), the one Liberty filing on the development
machine; the 14-filing check waits for the corpus drives.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import liberty_summary as ls      # noqa: E402


class _Page(object):
    """a page whose text layer is a list of (x0, y0, x1, y1, text) cells"""
    def __init__(self, cells):
        self.cells = cells

    def get_text(self, kind=None):
        if kind == "dict":
            return {"blocks": [{"lines": [{"spans": [
                {"bbox": c[:4], "text": c[4]} for c in self.cells]}]}]}
        # plain text reads line by line, cells on one line joined by a space
        return "\n".join(" ".join(c[4] for c in cs)
                         for _cy, cs in ls._rows(self.cells))


class _Doc(object):
    def __init__(self, pages):
        self.pages = pages
        self.page_count = len(pages)

    def __getitem__(self, i):
        return self.pages[i]


# --------------------------------------------------------------- fixtures
P123_PRESSURE = [  # 49367 p123, 90 spans
    (1227.0, 10.4, 1313.7, 22.7, 'Desired LOS Ticket #'),
    (1228.5, 23.9, 1260.9, 36.3, '172029'),
    (7.5, 143.5, 159.3, 160.1, 'PRESSURE SUMMARY'),
    (92.7, 170.2, 163.0, 181.5, 'Max Working MPa'),
    (232.5, 170.2, 279.0, 181.5, 'Global Trips'),
    (366.3, 170.2, 400.9, 181.5, 'Ave Rate'),
    (495.1, 170.2, 528.7, 181.5, 'Ave MPa'),
    (621.9, 170.2, 658.4, 181.5, 'Max Rate'),
    (750.2, 170.2, 785.8, 181.5, 'Max MPa'),
    (883.5, 170.2, 908.3, 181.5, 'F_ISIP'),
    (1006.0, 170.2, 1042.2, 181.5, 'F_BHISIP'),
    (1142.1, 170.2, 1161.9, 181.5, 'F_FG'),
    (1266.0, 170.2, 1293.8, 181.5, 'BD_Psi'),
    (20.7, 169.4, 47.5, 182.6, 'Stage'),
    (111.0, 181.1, 143.4, 197.6, '84.00'),
    (239.2, 181.1, 271.6, 197.6, '87.00'),
    (370.5, 181.1, 395.7, 197.6, '8.78'),
    (495.0, 181.1, 527.4, 197.6, '78.40'),
    (623.2, 181.1, 655.6, 197.6, '10.53'),
    (751.5, 181.1, 783.9, 197.6, '82.09'),
    (879.0, 181.1, 911.4, 197.6, '24.20'),
    (1007.2, 181.1, 1039.6, 197.6, '43.00'),
    (1135.5, 181.1, 1167.9, 197.6, '22.04'),
    (1263.8, 181.1, 1296.1, 197.6, '41.10'),
    (31.7, 185.4, 35.8, 194.5, '1'),
    (111.0, 195.3, 143.4, 211.9, '84.00'),
    (239.2, 195.3, 271.6, 211.9, '87.00'),
    (367.5, 195.3, 399.9, 211.9, '10.43'),
    (495.0, 195.3, 527.4, 211.9, '77.45'),
    (623.2, 195.3, 655.6, 211.9, '12.83'),
    (751.5, 195.3, 783.9, 211.9, '82.91'),
    (879.0, 195.3, 911.4, 211.9, '24.60'),
    (1007.2, 195.3, 1039.6, 211.9, '43.00'),
    (1135.5, 195.3, 1167.9, 211.9, '22.25'),
    (1263.8, 195.3, 1296.1, 211.9, '67.90'),
    (32.1, 199.7, 36.1, 208.8, '2'),
    (32.1, 213.2, 36.1, 222.3, '3'),
    (111.0, 209.6, 143.4, 226.1, '84.00'),
    (239.2, 209.6, 271.6, 226.1, '87.00'),
    (367.5, 209.6, 399.9, 226.1, '10.66'),
    (495.0, 209.6, 527.4, 226.1, '77.51'),
    (623.2, 209.6, 655.6, 226.1, '11.82'),
    (751.5, 209.6, 783.9, 226.1, '83.44'),
    (879.0, 209.6, 911.4, 226.1, '25.40'),
    (1007.2, 209.6, 1039.6, 226.1, '44.00'),
    (1135.5, 209.6, 1167.9, 226.1, '22.67'),
    (1263.8, 209.6, 1296.1, 226.1, '58.24'),
    (111.0, 223.1, 143.4, 239.6, '84.00'),
    (239.2, 223.1, 271.6, 239.6, '87.00'),
    (367.5, 223.1, 399.9, 239.6, '11.03'),
    (495.0, 223.1, 527.4, 239.6, '77.88'),
    (623.2, 223.1, 655.6, 239.6, '12.58'),
    (751.5, 223.1, 783.9, 239.6, '81.36'),
    (879.0, 223.1, 911.4, 239.6, '25.93'),
    (1007.2, 223.1, 1039.6, 239.6, '45.00'),
    (1135.5, 223.1, 1167.9, 239.6, '22.95'),
    (1263.8, 223.1, 1296.1, 239.6, '51.04'),
    (128.2, 1264.5, 152.5, 1276.6, '82.00'),
    (219.0, 1264.5, 243.3, 1276.6, '84.00'),
    (402.0, 1264.5, 426.3, 1276.6, '90.00'),
    (498.8, 1264.5, 517.6, 1276.6, '4.55'),
    (585.0, 1264.5, 609.3, 1276.6, '60.82'),
    (681.8, 1264.5, 700.6, 1276.6, '6.29'),
    (768.0, 1264.5, 792.3, 1276.6, '68.18'),
    (858.8, 1264.5, 883.0, 1276.6, '19.30'),
    (950.2, 1264.5, 974.5, 1276.6, '38.00'),
    (1041.8, 1264.5, 1066.0, 1276.6, '19.78'),
    (25.7, 1264.4, 43.3, 1277.6, 'Min'),
    (128.2, 1281.7, 152.5, 1293.9, '84.00'),
    (219.0, 1281.7, 243.3, 1293.9, '87.00'),
    (402.0, 1281.7, 426.3, 1293.9, '93.00'),
    (493.5, 1281.7, 517.8, 1293.9, '16.73'),
    (585.0, 1281.7, 609.3, 1293.9, '78.40'),
    (676.5, 1281.7, 700.8, 1293.9, '18.36'),
    (768.0, 1281.7, 792.3, 1293.9, '90.54'),
    (858.8, 1281.7, 883.0, 1293.9, '26.80'),
    (950.2, 1281.7, 974.5, 1293.9, '46.00'),
    (1041.8, 1281.7, 1066.0, 1293.9, '23.41'),
    (24.8, 1281.7, 44.2, 1294.8, 'Max'),
    (128.2, 1298.2, 152.5, 1310.4, '83.97'),
    (219.0, 1298.2, 243.3, 1310.4, '86.49'),
    (402.0, 1298.2, 426.3, 1310.4, '92.29'),
    (493.5, 1298.2, 517.8, 1310.4, '12.66'),
    (585.0, 1298.2, 609.3, 1310.4, '72.41'),
    (676.5, 1298.2, 700.8, 1310.4, '14.78'),
    (768.0, 1298.2, 792.3, 1310.4, '79.14'),
    (858.8, 1298.2, 883.0, 1310.4, '22.86'),
    (950.2, 1298.2, 974.5, 1310.4, '41.47'),
    (1041.8, 1298.2, 1066.0, 1310.4, '21.52'),
    (15.5, 1298.2, 53.5, 1311.3, 'Average'),
]

P125_WELLBORE = [  # 49367 p125, 27 spans
    (6.8, 143.5, 162.5, 160.1, 'WELLBORE SUMMARY'),
    (140.1, 177.9, 184.6, 187.1, 'PERF TopShot'),
    (349.6, 177.9, 406.4, 187.1, 'PERF BottomShot'),
    (556.3, 177.9, 631.0, 187.1, 'Sum of PERF PlugDepth'),
    (775.1, 177.9, 842.7, 187.1, 'PERF TotalNumShots'),
    (988.2, 177.9, 1060.8, 187.1, 'PERF NumPerfClusters'),
    (1202.7, 177.9, 1277.6, 187.1, 'Top Shot Flush Vol (m3)'),
    (11.6, 177.0, 46.9, 188.2, 'Stage No'),
    (26.8, 199.7, 30.9, 208.8, '1'),
    (137.2, 196.1, 187.6, 212.6, '6,149.40'),
    (352.5, 196.1, 402.9, 212.6, '6,190.40'),
    (567.8, 196.1, 618.1, 212.6, '6,194.90'),
    (1223.2, 196.1, 1255.6, 212.6, '52.61'),
    (137.2, 210.3, 187.6, 226.9, '6,095.40'),
    (352.5, 210.3, 402.9, 226.9, '6,136.40'),
    (567.8, 210.3, 618.1, 226.9, '6,142.60'),
    (1223.2, 210.3, 1255.6, 226.9, '52.21'),
    (27.2, 214.7, 31.3, 223.8, '2'),
    (137.2, 224.6, 187.6, 241.1, '6,041.40'),
    (352.5, 224.6, 402.9, 241.1, '6,082.40'),
    (567.8, 224.6, 618.1, 241.1, '6,088.60'),
    (1223.2, 224.6, 1255.6, 241.1, '51.81'),
    (27.2, 228.9, 31.3, 238.0, '3'),
    (137.2, 239.6, 187.6, 256.1, '5,987.40'),
    (352.5, 239.6, 402.9, 256.1, '6,028.40'),
    (567.8, 239.6, 618.1, 256.1, '6,033.60'),
    (1223.2, 239.6, 1255.6, 256.1, '51.41'),
]

P122_FLUID = [  # 49367 p122, 27 spans
    (6.8, 127.8, 125.4, 144.4, 'FLUID SUMMARY'),
    (160.6, 159.0, 217.4, 170.2, 'Treated Water'),
    (379.3, 159.0, 439.7, 170.2, 'CAN HCl+WL 15'),
    (609.8, 159.0, 650.2, 170.2, 'HVFR 1.00'),
    (830.3, 159.0, 870.7, 170.2, 'HVFR 1.25'),
    (1050.8, 159.0, 1091.2, 170.2, 'HVFR 1.50'),
    (182.9, 179.2, 195.1, 190.6, 'm3'),
    (403.4, 179.2, 415.6, 190.6, 'm3'),
    (623.9, 179.2, 636.1, 190.6, 'm3'),
    (844.4, 179.2, 856.6, 190.6, 'm3'),
    (1064.9, 179.2, 1077.1, 190.6, 'm3'),
    (20.4, 178.4, 62.1, 191.6, 'Stage No'),
    (38.8, 195.0, 43.7, 206.2, '1'),
    (172.5, 192.3, 204.9, 208.9, '150.6'),
    (400.5, 192.3, 418.5, 208.9, '4.0'),
    (1054.5, 192.3, 1086.9, 208.9, '560.7'),
    (176.2, 209.6, 201.4, 226.1, '74.5'),
    (400.5, 209.6, 418.5, 226.1, '1.0'),
    (1054.5, 209.6, 1086.9, 226.1, '532.3'),
    (38.8, 212.3, 43.7, 223.4, '2'),
    (38.8, 229.5, 43.7, 240.7, '3'),
    (176.2, 226.8, 201.4, 243.4, '72.4'),
    (400.5, 226.8, 418.5, 243.4, '1.0'),
    (834.0, 226.8, 866.4, 243.4, '491.6'),
    (176.2, 244.1, 201.4, 260.6, '71.8'),
    (400.5, 244.1, 418.5, 260.6, '1.0'),
    (834.0, 244.1, 866.4, 260.6, '491.1'),
]

T109 = "\n".join(['Desired LOS Ticket #', '172029', 'LIBERTY OILFIELD SERVICES - 950 17TH ST, SUITE 2400, DENVER, CO 80202', 'CUSTOMER:', 'CUSTOMER CONTACT:', 'Vermilion Energy Canada', 'Colin Robinson, P.Eng.', 'WHITE SAND 30/50 (HUALLEN Q2)', 'BROWN SAND 40/70 (BEAVERLODGE Q2)', 'BROWN SAND 30/50 (BEAVERLODGE Q2)', '40/70 Brown', '30/50 White', '30/50 Brown', 'WELL TYPE:', 'COMPLETION TYPE:', 'NUMBER OF INTERVALS:', 'MAX PRESSURE:', 'MAIN FLUID TYPE:', 'PROPPANT TYPES:', 'Horizontal ', 'Cemented, Plug & Perf ', '77', '84 MPa', 'HVFR 1.25', 'COMPLETION INFORMATION', 'CUSTOMER INFORMATION', 'WELL NAME:', 'COMPLETION DATE:'])  # p109
T110 = "\n".join(['Operator Name', 'Customer Contact', 'Vermilion Energy Canada', 'Colin Robinson, P.Eng.', 'WELL COMPLETION SUMMARY', 'Well Name', 'API', 'AFE', 'Bhst (C)', 'Formation', 'Completion Type', 'VERMILION HZ MICA F09-21-081-14', '100/03-10-081-14..', '49367', '66', 'Montney', 'Cemented, Plug & Perf', 'Start of Frac Time', 'End of Frac Time', 'Frac Pump Time', 'WL Pump Time (min)', 'MkW', 'Customer/3rd Party NPT/DT', 'Crew LOS NPT/DT', '5/23/2025 12\ue35303\ue35300\u202fPM', '6/3/2025 7\ue35322\ue35300\u202fAM', '3,185 min', '2,984 min'])  # p110
T114 = "\n".join(['.', 'Total Well', 'Fluid', 'Avg', 'Stage', 'Fluid', 'Max', 'Stage', 'Fluid', 'Min', 'Stage', 'Fluid', 'Fluids Pumped (m3)', 'CAN HCl+WL 15', 'HVFR 1.00', 'HVFR 1.25', 'HVFR 1.50', 'Treated Water', '       Well', 'Aggregates', '35,879', '466', '896', '336', 'Total:           3,402', 'Average:    44', 'Min:              7', 'Max:             160'])  # p114
T116 = "\n".join(['Measure Names', 'AcidDsplcRate', 'Ave BHPSI', 'Ave Backside PSI', 'Ave Coil PSI', 'Ave MPa', 'Ave PSI', 'Ave Rate', 'Ave Surface PSI', 'Ave Temp', 'Ave Visc', 'AveN2Rate', 'Avep H', 'BD_Psi', 'BD_Rate', 'BHN2Factor', 'CloseWHpsi', 'Count of Migrated Data', 'F 10Min', 'F 15Min', 'F 1Min', 'F 2Min', 'F 5Min', 'FSD 1st BHP', 'Desired LOS Ticket #', '172029', 'Measure Names', 'Ave MPa'])  # p116
T117 = "\n".join(['Desired LOS Ticket #', '172029', 'Pressure Summary Presets', 'Initial & Final Stepdowns', 'Stage No', 'Ball Hit Vol (m3)', 'Ball Rate (m3pm)', 'Ball Initial (MPa)', 'Ball Max (MPa)', 'Ball Final (MPa)', 'Ball Hit Diﬀ (MPa)', '0', '10', '20', '30', '40', '0.0', '0.5', '1.0', '1.5', '2.0', '0', '10', '20', '30', '40', '50 0', '10'])  # p117
T118 = "\n".join(['Stage No', 'Proppant Name', '30/50 Brown', '30/50 White', '40/70 Brown', 'BROWN SAND 30/50 (BEAVERLODGE Q2)', 'BROWN SAND 40/70 (BEAVERLODGE Q2)', 'WHITE SAND 30/50 (HUALLEN Q2)', '0K', '100K', '200K', 'Prop Actual (lbs)', '0K', '100K', '200K', 'Prop Design (lbs)', '-200K', '-100K', '0K', 'Proppant Actual-Des..', '0K', '100K', '200K', 'Prop Actual (lbs)', '0K', '100K', '200K', 'Prop Design (lbs)'])  # p118
T120 = "\n".join(['Chemical Name', 'Chemi..', 'Stage No', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', '13', '14', '15', '16', '17', '18', '19', '20', '21', '22', '23', '24', '25'])  # p120
T122 = "\n".join(['Desired LOS Ticket #', '172029', 'Stage No', 'Treated Water', 'm3', 'CAN HCl+WL 15', 'm3', 'HVFR 1.00', 'm3', 'HVFR 1.25', 'm3', 'HVFR 1.50', 'm3', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', '13', '14', '15'])  # p122
T123 = "\n".join(['Desired LOS Ticket #', '172029', 'Stage', 'Max Working MPa', 'Global Trips', 'Ave Rate', 'Ave MPa', 'Max Rate', 'Max MPa', 'F_ISIP', 'F_BHISIP', 'F_FG', 'BD_Psi', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', '13', '14', '15'])  # p123
T125 = "\n".join(['Stage No', 'PERF TopShot', 'PERF BottomShot', 'Sum of PERF PlugDepth', 'PERF TotalNumShots', 'PERF NumPerfClusters', 'Top Shot Flush Vol (m3)', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', '13', '14', '15', '16', '17', '18', '19', '20', '21'])  # p125


class PageKinds(unittest.TestCase):
    def test_every_49367_sheet_lands_on_its_own_kind(self):
        want = [(T110, "wellcompletion"), (T114, "fluid_totals"),
                (T116, "pressure_measures"), (T117, "ballhit"),
                (T118, "proppant_chart"), (T120, "chemical"),
                (T122, "fluid"), (T123, "pressure"), (T125, "wellbore")]
        for text, kind in want:
            self.assertEqual(ls._page_kind(text), kind, text[:40])
        self.assertEqual(len(set(k for _t, k in want)), len(want))

    def test_the_customer_information_page_is_not_a_sheet(self):
        self.assertIsNone(ls._page_kind(T109))

    def test_proppant_grid_stays_proppant(self):
        # the grid prints Prop Screw; only its bar-chart twin prints 0K/100K
        self.assertEqual(ls._page_kind(
            "PROPPANT SUMMARY\nStage No\nProp Actual\nProp Screw\nProp Design"),
            "proppant")
        self.assertEqual(ls._page_kind("PROPPANT SUMMARY"), "proppant")
        self.assertEqual(ls._page_kind("PROPPANT SUMMARY\n0K\n100K\n200K"),
                         "proppant_chart")

    def test_a_stage_page_nothing_claims_is_a_stage_table_not_proppant(self):
        self.assertEqual(ls._page_kind("Stage No\nSomething Else\n1\n2"),
                         "stagetable")

    def test_old_vintage_fluid_columns_name_the_sheet(self):
        self.assertEqual(ls._page_kind("Stage No\nFresh Water\nHCR Acid\n1\n2"),
                         "fluid")

    def test_a_long_page_is_classified_in_linear_time(self):
        # 00674 p566 is 27 KB of text; unpinned lookaheads took 6 s on it
        import time
        text = "\n".join("Row %d some cell text 12.5" % i for i in range(1500))
        t0 = time.time()
        self.assertIsNone(ls._page_kind(text))
        self.assertLess(time.time() - t0, 0.5)

    def test_every_kind_has_a_title(self):
        for kind, _pat in ls.SUMMARY_KINDS:
            self.assertIn(kind, ls.KIND_TITLES)
        self.assertIn("proppant_chart", ls.KIND_TITLES)


class PressureGrid(unittest.TestCase):
    def setUp(self):
        self.tab = ls._stage_grid(_Page(P123_PRESSURE))

    def test_columns_from_the_single_header_row(self):
        self.assertEqual(self.tab["columns"], [
            "Stage", "Max Working MPa", "Global Trips", "Ave Rate", "Ave MPa",
            "Max Rate", "Max MPa", "F_ISIP", "F_BHISIP", "F_FG", "BD_Psi"])
        self.assertEqual(self.tab["empty_columns"], [])

    def test_rows_keyed_by_stage(self):
        self.assertEqual([r[0] for r in self.tab["rows"]], ["1", "2", "3"])
        self.assertEqual(self.tab["rows"][0], [
            "1", "84.00", "87.00", "8.78", "78.40", "10.53", "82.09",
            "24.20", "43.00", "22.04", "41.10"])

    def test_footer_matched_by_order_not_by_x(self):
        # the Min/Max/Average sheet has its own column pitch
        self.assertEqual(set(self.tab["totals"]), {"Min", "Max", "Average"})
        self.assertEqual(self.tab["totals"]["Min"][3], "4.55")
        self.assertEqual(self.tab["totals"]["Average"][0], "83.97")
        self.assertEqual(self.tab["totals"]["Max"][-1], "23.41")


class WellboreGrid(unittest.TestCase):
    def setUp(self):
        self.tab = ls._stage_grid(_Page(P125_WELLBORE))

    def test_titled_but_unfilled_columns_are_reported_not_shipped(self):
        self.assertEqual(self.tab["columns"], [
            "Stage", "PERF TopShot", "PERF BottomShot",
            "Sum of PERF PlugDepth", "Top Shot Flush Vol (m3)"])
        self.assertEqual(self.tab["empty_columns"],
                         ["PERF TotalNumShots", "PERF NumPerfClusters"])

    def test_rows(self):
        self.assertEqual(len(self.tab["rows"]), 3)
        self.assertEqual(self.tab["rows"][0],
                         ["1", "6149.40", "6190.40", "6194.90", "52.61"])
        self.assertEqual(self.tab["totals"], {})


class FluidGrid(unittest.TestCase):
    def setUp(self):
        self.tab = ls._stage_grid(_Page(P122_FLUID))

    def test_units_under_the_names_join_them(self):
        self.assertEqual(self.tab["columns"], [
            "Stage", "Treated Water (m3)", "CAN HCl+WL 15 (m3)",
            "HVFR 1.25 (m3)", "HVFR 1.50 (m3)"])

    def test_sparse_cells_stay_in_their_own_column(self):
        self.assertEqual(self.tab["rows"][0], ["1", "150.6", "4.0", None, "560.7"])
        self.assertEqual(self.tab["rows"][2], ["3", "72.4", "1.0", "491.6", None])

    def test_a_column_with_no_cell_on_the_page_is_named_in_empty_columns(self):
        # HVFR 1.00 is pumped from stage 4 on; these three rows never fill it
        self.assertEqual(self.tab["empty_columns"], ["HVFR 1.00"])


class DocumentParse(unittest.TestCase):
    def setUp(self):
        self.doc = _Doc([_Page(P123_PRESSURE), _Page(P125_WELLBORE),
                         _Page(P122_FLUID)])

    def test_find_summary_pages_titles_each_sheet(self):
        self.assertEqual([g["title"] for g in ls.find_summary_pages(self.doc)],
                         ["Pressure Summary", "Wellbore Summary",
                          "Fluid Volumes by Stage"])

    def test_parse_stage_sheets_keys_tables_by_kind(self):
        tabs = ls.parse_stage_sheets(self.doc)
        self.assertEqual(set(tabs), {"pressure", "wellbore", "fluid"})
        self.assertEqual(tabs["pressure"]["pages"], [1])
        self.assertEqual(tabs["wellbore"]["rows"][2][0], "3")
        self.assertEqual(tabs["fluid"]["columns"][1], "Treated Water (m3)")

    def test_single_parsers_agree_with_the_sweep(self):
        self.assertEqual(ls.parse_pressure(self.doc),
                         ls.parse_stage_sheets(self.doc)["pressure"])
        self.assertIsNone(ls.parse_proppant(self.doc))


if __name__ == "__main__":
    unittest.main()
