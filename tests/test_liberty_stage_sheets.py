"""Liberty's stage-keyed summary sheets (#767).

Six different Tableau sheets lead with "Stage No", and the Summary view used
to label every one of them "Proppant Summary" — so nothing on them could be
parsed. The first fixtures are the page text and the cell spans of 49367 (the
2025 vintage, VERMILION HZ MICA F09-21). The ones after them come from the
corpus check of 2026-10-03 (26 Liberty filings, AER and BCER, both drives):
00269 (AER Montney ARC, 0498236), 00738, 00470 and 00697 (AER Duvernay) and
00938 (BCER 2025, a one-stage job) -- the right-aligned sheets, the bbl,
bare-m3 and Gal flush columns, the three-line proppant header, the footer
sheet's own column list, and the pages that are not what their legend says.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import liberty_summary as ls      # noqa: E402


class _Page(object):
    """a page whose text layer is a list of (x0, y0, x1, y1, text) cells and,
    when `boxes` is given, whose drawings are those header rectangles"""
    def __init__(self, cells, boxes=None):
        self.cells = cells
        self.boxes = boxes

    def get_drawings(self):
        if self.boxes is None:
            raise AttributeError("no drawings")
        return [{"fill": (0.75, 0.75, 0.75), "rect": b} for b in self.boxes]

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


P85_PROPPANT = [  # 00269 p85, 58 spans
    (6.8, 129.0, 183.9, 147.3, 'PROPPANT SUMMARY'),
    (587.8, 156.0, 675.7, 170.0, 'Proppant Name'),
    (228.3, 173.2, 280.1, 183.6, '30/70 White'),
    (605.2, 173.2, 657.0, 183.6, '40/70 White'),
    (983.2, 172.5, 1034.8, 182.7, 'Grand Total'),
    (9.7, 189.0, 62.6, 203.0, 'Stage No'),
    (88.5, 190.5, 139.4, 200.9, 'Prop Actual'),
    (183.2, 190.5, 228.5, 200.9, 'Prop Screw'),
    (275.9, 190.5, 326.0, 200.9, 'Prop Design'),
    (349.9, 190.5, 443.3, 200.9, 'Proppant Actual-Desi..'),
    (465.3, 190.5, 516.2, 200.9, 'Prop Actual'),
    (560.0, 190.5, 605.3, 200.9, 'Prop Screw'),
    (653.1, 190.5, 703.3, 200.9, 'Prop Design'),
    (726.8, 190.5, 820.2, 200.9, 'Proppant Actual-Desi..'),
    (842.2, 190.5, 893.1, 200.9, 'Prop Actual'),
    (937.3, 190.5, 982.6, 200.9, 'Prop Screw'),
    (1030.0, 190.5, 1080.1, 200.9, 'Prop Design'),
    (1103.7, 190.5, 1197.1, 200.9, 'Proppant Actual-Desi..'),
    (31.7, 218.2, 38.5, 226.7, '1'),
    (504.0, 217.5, 534.5, 227.8, '50,000'),
    (598.5, 217.5, 629.0, 227.8, '49,936'),
    (693.0, 217.5, 723.5, 227.8, '50,000'),
    (809.2, 217.5, 817.5, 227.8, '0'),
    (881.2, 217.5, 911.8, 227.7, '50,000'),
    (975.8, 217.5, 1006.3, 227.7, '49,936'),
    (1069.5, 217.5, 1100.0, 227.7, '50,000'),
    (1186.5, 217.5, 1194.8, 227.7, '0'),
    (31.7, 252.0, 38.5, 260.4, '2'),
    (499.5, 251.2, 534.9, 261.6, '250,000'),
    (593.2, 251.2, 628.7, 261.6, '247,574'),
    (687.8, 251.2, 723.2, 261.6, '250,000'),
    (809.2, 251.2, 817.5, 261.6, '0'),
    (876.0, 250.5, 911.4, 260.7, '250,000'),
    (970.5, 250.5, 1005.9, 260.7, '247,574'),
    (1065.0, 250.5, 1100.4, 260.7, '250,000'),
    (1186.5, 250.5, 1194.8, 260.7, '0'),
    (31.7, 285.0, 38.5, 293.4, '3'),
    (122.2, 284.2, 157.7, 294.6, '250,000'),
    (216.8, 284.2, 252.2, 294.6, '253,656'),
    (310.5, 284.2, 345.9, 294.6, '250,000'),
    (432.0, 284.2, 440.2, 294.6, '0'),
    (876.0, 284.2, 911.4, 294.5, '250,000'),
    (970.5, 284.2, 1005.9, 294.5, '253,656'),
    (1065.0, 284.2, 1100.4, 294.5, '250,000'),
    (1186.5, 284.2, 1194.8, 294.5, '0'),
    (15.0, 1149.8, 57.2, 1158.1, 'Grand Total'),
    (114.8, 1149.0, 157.6, 1159.2, '6,400,000'),
    (209.2, 1149.0, 252.1, 1159.2, '6,330,848'),
    (303.0, 1149.0, 345.9, 1159.2, '6,400,000'),
    (432.0, 1149.0, 440.2, 1159.2, '0'),
    (499.5, 1149.0, 534.9, 1159.2, '300,000'),
    (593.2, 1149.0, 628.7, 1159.2, '297,510'),
    (687.8, 1149.0, 723.2, 1159.2, '300,000'),
    (809.2, 1149.0, 817.5, 1159.2, '0'),
    (868.5, 1149.0, 911.4, 1159.2, '6,700,000'),
    (963.0, 1149.0, 1005.9, 1159.2, '6,628,358'),
    (1057.5, 1149.0, 1100.4, 1159.2, '6,700,000'),
    (1186.5, 1149.0, 1194.8, 1159.2, '0'),
]
P85_PROPPANT_BOXES = [  # its header rectangles
    (63.8, 155.2, 1194.8, 170.2),
    (63.8, 170.2, 441.0, 185.2),
    (63.8, 185.2, 158.2, 206.2),
    (158.2, 185.2, 252.0, 206.2),
    (252.0, 185.2, 346.5, 206.2),
    (346.5, 185.2, 441.0, 206.2),
    (441.0, 170.2, 817.5, 185.2),
    (441.0, 185.2, 534.8, 206.2),
    (534.8, 185.2, 629.2, 206.2),
    (629.2, 185.2, 723.8, 206.2),
    (723.8, 185.2, 817.5, 206.2),
    (817.5, 170.2, 1194.8, 185.2),
    (817.5, 185.2, 912.0, 206.2),
    (912.0, 185.2, 1006.5, 206.2),
    (1006.5, 185.2, 1100.2, 206.2),
    (1100.2, 185.2, 1194.8, 206.2),
]
P137_PROPPANT = [  # 00738 p137, 31 spans
    (7.5, 143.5, 160.4, 160.1, 'PROPPANT SUMMARY'),
    (662.8, 168.5, 745.7, 183.7, 'Proppant Name'),
    (364.7, 186.1, 404.0, 195.3, '40/70 White'),
    (1005.4, 186.2, 1042.9, 195.3, 'Grand Total'),
    (10.4, 201.5, 58.6, 216.8, 'Stage No'),
    (125.9, 204.1, 162.8, 213.4, 'Prop Actual'),
    (286.5, 204.1, 322.5, 213.4, 'Prop Screw'),
    (445.5, 204.1, 483.8, 213.4, 'Prop Design'),
    (586.6, 204.1, 662.2, 213.4, 'Proppant Actual-Design'),
    (765.7, 204.1, 802.6, 213.4, 'Prop Actual'),
    (926.3, 204.1, 962.2, 213.4, 'Prop Screw'),
    (1085.2, 204.1, 1123.5, 213.4, 'Prop Design'),
    (1226.3, 204.1, 1301.9, 213.4, 'Proppant Actual-Design'),
    (32.1, 221.4, 36.1, 230.5, '1'),
    (181.5, 217.9, 221.1, 234.3, '45,000'),
    (341.2, 217.9, 380.8, 234.3, '43,602'),
    (501.0, 217.9, 540.6, 234.3, '50,000'),
    (664.5, 217.9, 700.7, 234.3, '-5,000'),
    (821.2, 218.0, 860.8, 234.1, '45,000'),
    (981.0, 218.0, 1020.6, 234.1, '43,602'),
    (1140.8, 218.0, 1180.3, 234.1, '50,000'),
    (1304.2, 218.0, 1340.5, 234.1, '-5,000'),
    (32.5, 236.4, 36.5, 245.5, '2'),
    (174.0, 232.2, 220.8, 248.5, '140,000'),
    (334.5, 232.2, 381.3, 248.5, '140,456'),
    (494.2, 232.2, 541.0, 248.5, '140,000'),
    (693.8, 232.2, 701.0, 248.5, '0'),
    (813.8, 232.2, 860.5, 248.4, '140,000'),
    (974.2, 232.2, 1021.0, 248.4, '140,456'),
    (1134.0, 232.2, 1180.8, 248.4, '140,000'),
    (1333.5, 232.2, 1340.7, 248.4, '0'),
]
P137_PROPPANT_BOXES = [  # its header rectangles
    (64.5, 168.0, 1344.0, 183.0),
    (64.5, 183.0, 704.2, 198.0),
    (64.5, 198.0, 224.2, 219.0),
    (224.2, 198.0, 384.8, 219.0),
    (384.8, 198.0, 544.5, 219.0),
    (544.5, 198.0, 704.2, 219.0),
    (704.2, 183.0, 1344.0, 198.0),
    (704.2, 198.0, 864.0, 219.0),
    (864.0, 198.0, 1024.5, 219.0),
    (1024.5, 198.0, 1184.2, 219.0),
    (1184.2, 198.0, 1344.0, 219.0),
]
P86_FLUID = [  # 00269 p86, 25 spans
    (6.8, 129.0, 144.4, 147.3, 'FLUID SUMMARY'),
    (147.8, 162.8, 200.4, 173.0, 'Fresh Water'),
    (340.0, 162.8, 378.1, 173.0, 'HCR Acid'),
    (532.0, 162.8, 556.1, 173.0, 'HVFR'),
    (712.0, 170.2, 753.1, 180.6, 'Ave Temp'),
    (900.4, 170.2, 936.9, 180.6, 'Ave Visc'),
    (1088.6, 170.2, 1118.0, 180.6, 'Avep H'),
    (20.4, 181.5, 66.2, 193.6, 'Stage No'),
    (163.6, 182.2, 184.0, 192.6, 'bbls'),
    (349.2, 182.2, 369.6, 192.6, 'bbls'),
    (534.4, 182.2, 554.9, 192.6, 'bbls'),
    (38.8, 207.0, 47.0, 217.2, '1'),
    (250.5, 207.0, 263.7, 217.4, '42'),
    (441.0, 207.0, 449.2, 217.4, '5'),
    (617.2, 207.0, 635.4, 217.4, '492'),
    (798.0, 207.0, 823.6, 217.4, '14.00'),
    (983.2, 207.0, 1008.8, 217.4, '14.00'),
    (1173.8, 207.0, 1194.4, 217.4, '7.00'),
    (38.8, 242.2, 47.0, 252.5, '2'),
    (250.5, 241.5, 263.7, 251.9, '84'),
    (441.0, 241.5, 449.2, 251.9, '5'),
    (609.8, 241.5, 635.3, 251.9, '1,270'),
    (798.0, 241.5, 823.6, 251.9, '18.10'),
    (988.5, 241.5, 1009.1, 251.9, '9.00'),
    (1173.8, 241.5, 1194.4, 251.9, '7.50'),
]
P86_FLUID_BOXES = [  # its header rectangles
    (78.8, 155.2, 264.8, 180.0),
    (78.8, 180.0, 264.8, 195.0),
    (264.8, 155.2, 450.0, 180.0),
    (264.8, 180.0, 450.0, 195.0),
    (450.0, 155.2, 635.2, 180.0),
    (450.0, 180.0, 635.2, 195.0),
    (638.2, 155.2, 823.5, 195.0),
    (823.5, 155.2, 1009.5, 195.0),
    (1009.5, 155.2, 1194.8, 195.0),
]
P87_PRESSURE = [  # 00269 p87, 66 spans
    (6.8, 129.0, 182.4, 147.3, 'PRESSURE SUMMARY'),
    (20.0, 172.5, 51.1, 184.6, 'Stage'),
    (70.6, 174.8, 141.9, 185.1, 'Max Working PSI'),
    (161.2, 174.8, 211.8, 185.1, 'Global Trips'),
    (242.0, 174.8, 292.3, 185.1, 'PopOﬀSet L'),
    (321.8, 174.8, 372.1, 185.1, 'PopOﬀSet H'),
    (409.5, 174.8, 447.7, 185.1, 'Ave Rate'),
    (493.3, 174.8, 527.8, 185.1, 'Ave PSI'),
    (570.5, 174.8, 610.7, 185.1, 'Max Rate'),
    (653.9, 174.8, 690.4, 185.1, 'Max PSI'),
    (737.6, 174.8, 765.6, 185.1, 'F_ISIP'),
    (812.9, 174.8, 852.3, 185.1, 'F_BHISIP'),
    (902.1, 174.8, 924.4, 185.1, 'F_FG'),
    (979.6, 174.8, 1009.0, 185.1, 'F 5Min'),
    (1057.7, 174.8, 1092.1, 185.1, 'F 10Min'),
    (1138.7, 174.8, 1173.1, 185.1, 'F 15Min'),
    (30.4, 196.5, 40.2, 208.6, '1'),
    (117.8, 196.5, 143.3, 206.9, '80.00'),
    (198.8, 196.5, 224.3, 206.9, '82.00'),
    (446.2, 196.5, 466.9, 206.9, '7.69'),
    (522.0, 196.5, 547.6, 206.9, '77.15'),
    (608.2, 196.5, 628.9, 206.9, '9.38'),
    (684.0, 196.5, 709.6, 206.9, '79.25'),
    (765.0, 196.5, 790.6, 206.9, '25.50'),
    (845.2, 196.5, 870.8, 206.9, '57.82'),
    (926.2, 196.5, 951.8, 206.9, '17.53'),
    (30.4, 229.5, 40.2, 241.6, '2'),
    (117.8, 229.5, 143.3, 239.9, '80.00'),
    (198.8, 229.5, 224.3, 239.9, '82.00'),
    (446.2, 229.5, 466.9, 239.9, '7.70'),
    (522.0, 229.5, 547.6, 239.9, '73.40'),
    (608.2, 229.5, 628.9, 239.9, '9.90'),
    (684.0, 229.5, 709.6, 239.9, '81.20'),
    (765.0, 229.5, 790.6, 239.9, '30.10'),
    (845.2, 229.5, 870.8, 239.9, '62.42'),
    (926.2, 229.5, 951.8, 239.9, '18.93'),
    (25.0, 1123.5, 46.5, 1135.6, 'Min'),
    (117.0, 1123.5, 144.9, 1134.7, '80.00'),
    (197.2, 1123.5, 225.1, 1134.7, '82.00'),
    (445.5, 1123.5, 468.0, 1134.7, '7.69'),
    (520.5, 1123.5, 548.4, 1134.7, '69.70'),
    (606.8, 1123.5, 629.2, 1134.7, '9.14'),
    (682.5, 1123.5, 710.4, 1134.7, '75.23'),
    (762.8, 1123.5, 790.6, 1134.7, '25.50'),
    (843.8, 1123.5, 871.6, 1134.7, '57.82'),
    (924.8, 1123.5, 952.6, 1134.7, '17.53'),
    (24.0, 1140.8, 48.2, 1152.8, 'Max'),
    (117.0, 1140.8, 144.9, 1151.9, '80.00'),
    (197.2, 1140.8, 225.1, 1151.9, '82.00'),
    (439.5, 1140.8, 467.4, 1151.9, '12.14'),
    (520.5, 1140.8, 548.4, 1151.9, '77.15'),
    (601.5, 1140.8, 629.4, 1151.9, '13.64'),
    (682.5, 1140.8, 710.4, 1151.9, '81.20'),
    (762.8, 1140.8, 790.6, 1151.9, '37.97'),
    (843.8, 1140.8, 871.6, 1151.9, '70.29'),
    (924.8, 1140.8, 952.6, 1151.9, '21.31'),
    (14.7, 1158.0, 57.1, 1170.1, 'Average'),
    (117.0, 1158.0, 144.9, 1169.2, '80.00'),
    (197.2, 1158.0, 225.1, 1169.2, '82.00'),
    (445.5, 1158.0, 468.0, 1169.2, '9.82'),
    (520.5, 1158.0, 548.4, 1169.2, '72.84'),
    (601.5, 1158.0, 629.4, 1169.2, '11.44'),
    (682.5, 1158.0, 710.4, 1169.2, '77.48'),
    (762.8, 1158.0, 790.6, 1169.2, '30.42'),
    (843.8, 1158.0, 871.6, 1169.2, '62.74'),
    (924.8, 1158.0, 952.6, 1169.2, '19.02'),
]
P87_PRESSURE_BOXES = [  # its header rectangles
    (63.0, 155.2, 144.0, 185.2),
    (144.0, 155.2, 225.0, 185.2),
    (225.0, 155.2, 305.2, 185.2),
    (305.2, 155.2, 386.2, 185.2),
    (386.2, 155.2, 467.2, 185.2),
    (467.2, 155.2, 548.2, 185.2),
    (548.2, 155.2, 629.2, 185.2),
    (629.2, 155.2, 709.5, 185.2),
    (709.5, 155.2, 790.5, 185.2),
    (790.5, 155.2, 871.5, 185.2),
    (871.5, 155.2, 952.5, 185.2),
    (952.5, 155.2, 1032.8, 185.2),
    (1032.8, 155.2, 1113.8, 185.2),
    (1113.8, 155.2, 1194.8, 185.2),
]
P90_WELLBORE = [  # 00269 p90, 26 spans
    (6.0, 129.0, 184.0, 147.3, 'WELLBORE SUMMARY'),
    (10.9, 164.2, 49.6, 174.5, 'Stage No'),
    (74.7, 165.0, 165.9, 175.3, 'Top Shot Flush Vol bbl'),
    (194.3, 165.0, 300.5, 175.3, 'Bottom Shot Flush Vol bbl'),
    (344.4, 165.0, 403.5, 175.3, 'PERF TopShot'),
    (464.0, 165.0, 538.1, 175.3, 'PERF BottomShot'),
    (580.2, 165.0, 675.0, 175.3, 'Sum of PERF PlugDepth'),
    (711.7, 165.0, 798.4, 175.3, 'PERF TotalNumShots'),
    (841.7, 165.0, 921.9, 175.3, 'PERF ClusterLength'),
    (962.8, 165.0, 1055.7, 175.3, 'PERF NumPerfClusters'),
    (1105.2, 165.0, 1164.6, 175.3, 'PERF PerfDiam'),
    (26.0, 197.2, 34.3, 207.5, '1'),
    (114.8, 196.5, 123.0, 206.9, '1'),
    (241.5, 196.5, 249.8, 206.9, '1'),
    (360.0, 196.5, 385.6, 206.9, '6,175'),
    (487.5, 196.5, 513.1, 206.9, '6,190'),
    (750.0, 196.5, 758.2, 206.9, '2'),
    (1004.2, 196.5, 1012.5, 206.9, '2'),
    (26.0, 232.5, 34.3, 242.7, '2'),
    (114.8, 231.8, 123.0, 242.1, '1'),
    (241.5, 231.8, 249.8, 242.1, '1'),
    (360.0, 231.8, 385.6, 242.1, '6,081'),
    (487.5, 231.8, 513.1, 242.1, '6,157'),
    (614.2, 231.8, 639.8, 242.1, '6,163'),
    (747.8, 231.8, 760.9, 242.1, '20'),
    (1004.2, 231.8, 1012.5, 242.1, '5'),
]
P90_WELLBORE_BOXES = [  # its header rectangles
    (54.0, 154.5, 180.8, 184.5),
    (180.8, 154.5, 308.2, 184.5),
    (308.2, 154.5, 435.0, 184.5),
    (435.0, 154.5, 562.5, 184.5),
    (562.5, 154.5, 689.2, 184.5),
    (689.2, 154.5, 816.8, 184.5),
    (816.8, 154.5, 943.5, 184.5),
    (943.5, 154.5, 1071.0, 184.5),
    (1071.0, 154.5, 1197.8, 184.5),
]
P141_WELLBORE = [  # 00738 p141, 19 spans
    (6.8, 143.5, 162.5, 160.1, 'WELLBORE SUMMARY'),
    (11.6, 177.0, 46.9, 188.2, 'Stage No'),
    (91.8, 177.9, 161.7, 187.1, 'Top Shot Flush Vol m3'),
    (229.3, 177.9, 311.4, 187.1, 'Bottom Shot Flush Vol m3'),
    (391.7, 177.9, 436.3, 187.1, 'PERF TopShot'),
    (529.2, 177.9, 586.1, 187.1, 'PERF BottomShot'),
    (663.9, 177.9, 738.6, 187.1, 'Sum of PERF PlugDepth'),
    (811.1, 177.9, 878.7, 187.1, 'PERF TotalNumShots'),
    (957.1, 177.9, 1019.9, 187.1, 'PERF ClusterLength'),
    (1095.8, 177.9, 1168.4, 187.1, 'PERF NumPerfClusters'),
    (1251.9, 177.9, 1299.6, 187.1, 'PERF PerfDiam'),
    (26.8, 200.4, 30.9, 209.5, '1'),
    (110.2, 196.1, 142.6, 212.6, '81.13'),
    (253.5, 196.1, 285.9, 212.6, '81.33'),
    (392.2, 196.1, 435.4, 212.6, '7,377.7'),
    (535.5, 196.1, 578.7, 212.6, '7,401.2'),
    (679.5, 196.1, 722.7, 212.6, '7,401.1'),
    (840.8, 196.1, 848.0, 212.6, '2'),
    (1128.0, 196.1, 1135.2, 212.6, '2'),
]
P141_WELLBORE_BOXES = [  # its header rectangles
    (54.8, 167.2, 198.8, 197.2),
    (198.8, 167.2, 342.0, 197.2),
    (342.0, 167.2, 486.0, 197.2),
    (486.0, 167.2, 629.2, 197.2),
    (629.2, 167.2, 773.2, 197.2),
    (773.2, 167.2, 916.5, 197.2),
    (916.5, 167.2, 1060.5, 197.2),
    (1060.5, 167.2, 1203.8, 197.2),
    (1203.8, 167.2, 1347.8, 197.2),
]
P127_WELLBORE = [  # 00697 p127, 14 spans
    (6.8, 143.5, 162.5, 160.1, 'WELLBORE SUMMARY'),
    (11.6, 177.0, 46.9, 188.2, 'Stage No'),
    (140.1, 177.9, 184.6, 187.1, 'PERF TopShot'),
    (349.6, 177.9, 406.4, 187.1, 'PERF BottomShot'),
    (556.3, 177.9, 631.0, 187.1, 'Sum of PERF PlugDepth'),
    (775.1, 177.9, 842.7, 187.1, 'PERF TotalNumShots'),
    (988.2, 177.9, 1060.8, 187.1, 'PERF NumPerfClusters'),
    (1204.9, 177.9, 1275.3, 187.1, 'Top Shot Flush Vol Gal'),
    (26.8, 204.9, 30.9, 214.0, '1'),
    (137.2, 200.6, 187.6, 217.1, '7,124.00'),
    (352.5, 200.6, 402.9, 217.1, '7,149.00'),
    (804.8, 200.6, 812.0, 217.1, '2'),
    (1020.8, 200.6, 1027.9, 217.1, '2'),
    (1223.2, 200.6, 1255.6, 217.1, '79.03'),
]
P127_WELLBORE_BOXES = [  # its header rectangles
    (54.8, 167.2, 270.0, 197.2),
    (270.0, 167.2, 486.0, 197.2),
    (486.0, 167.2, 701.2, 197.2),
    (701.2, 167.2, 916.5, 197.2),
    (916.5, 167.2, 1132.5, 197.2),
    (1132.5, 167.2, 1347.8, 197.2),
]
P40_PRESSURE = [  # 00938 p40, 47 spans
    (7.5, 143.5, 159.3, 160.1, 'PRESSURE SUMMARY'),
    (20.7, 184.4, 47.5, 197.6, 'Stage'),
    (92.7, 186.7, 163.0, 198.0, 'Max Working MPa'),
    (218.2, 186.7, 293.3, 198.0, 'Sum of Global Trips'),
    (366.3, 186.7, 400.9, 198.0, 'Ave Rate'),
    (495.1, 186.7, 528.7, 198.0, 'Ave MPa'),
    (621.9, 186.7, 658.4, 198.0, 'Max Rate'),
    (750.2, 186.7, 785.8, 198.0, 'Max MPa'),
    (883.5, 186.7, 908.3, 198.0, 'F_ISIP'),
    (1006.0, 186.7, 1042.2, 198.0, 'F_BHISIP'),
    (1142.1, 186.7, 1161.9, 198.0, 'F_FG'),
    (1266.0, 186.7, 1293.8, 198.0, 'BD_Psi'),
    (31.7, 725.4, 35.8, 734.5, '1'),
    (111.0, 721.1, 143.4, 737.6, '29.00'),
    (239.2, 721.1, 271.6, 737.6, '43.00'),
    (370.5, 721.1, 395.7, 737.6, '1.22'),
    (495.0, 721.1, 527.4, 737.6, '38.05'),
    (627.0, 721.1, 652.2, 737.6, '1.23'),
    (751.5, 721.1, 783.9, 737.6, '40.34'),
    (879.0, 721.1, 911.4, 737.6, '18.58'),
    (25.7, 1265.2, 43.3, 1278.3, 'Min'),
    (128.2, 1265.2, 152.5, 1277.4, '29.00'),
    (219.0, 1265.2, 243.3, 1277.4, '43.00'),
    (402.0, 1265.2, 426.3, 1277.4, '48.00'),
    (498.8, 1265.2, 517.6, 1277.4, '1.22'),
    (585.0, 1265.2, 609.3, 1277.4, '38.05'),
    (681.8, 1265.2, 700.6, 1277.4, '1.23'),
    (768.0, 1265.2, 792.3, 1277.4, '40.34'),
    (858.8, 1265.2, 883.0, 1277.4, '18.58'),
    (24.8, 1282.4, 44.2, 1295.6, 'Max'),
    (128.2, 1282.5, 152.5, 1294.6, '29.00'),
    (219.0, 1282.5, 243.3, 1294.6, '43.00'),
    (402.0, 1282.5, 426.3, 1294.6, '48.00'),
    (498.8, 1282.5, 517.6, 1294.6, '1.22'),
    (585.0, 1282.5, 609.3, 1294.6, '38.05'),
    (681.8, 1282.5, 700.6, 1294.6, '1.23'),
    (768.0, 1282.5, 792.3, 1294.6, '40.34'),
    (858.8, 1282.5, 883.0, 1294.6, '18.58'),
    (15.5, 1298.9, 53.5, 1312.1, 'Average'),
    (128.2, 1299.0, 152.5, 1311.1, '29.00'),
    (219.0, 1299.0, 243.3, 1311.1, '43.00'),
    (402.0, 1299.0, 426.3, 1311.1, '48.00'),
    (498.8, 1299.0, 517.6, 1311.1, '1.22'),
    (585.0, 1299.0, 609.3, 1311.1, '38.05'),
    (681.8, 1299.0, 700.6, 1311.1, '1.23'),
    (768.0, 1299.0, 792.3, 1311.1, '40.34'),
    (858.8, 1299.0, 883.0, 1311.1, '18.58'),
]
P40_PRESSURE_BOXES = [  # its header rectangles
    (63.8, 168.0, 192.0, 198.0),
    (192.0, 168.0, 319.5, 198.0),
    (319.5, 168.0, 447.8, 198.0),
    (447.8, 168.0, 576.0, 198.0),
    (576.0, 168.0, 704.2, 198.0),
    (704.2, 168.0, 831.8, 198.0),
    (831.8, 168.0, 960.0, 198.0),
    (960.0, 168.0, 1088.2, 198.0),
    (1088.2, 168.0, 1215.8, 198.0),
    (1215.8, 168.0, 1344.0, 198.0),
]
P139_PRESSURE = [  # 00738 p139, 35 spans
    (7.5, 143.5, 159.3, 160.1, 'PRESSURE SUMMARY'),
    (20.7, 169.4, 47.5, 182.6, 'Stage'),
    (86.7, 170.2, 157.0, 181.5, 'Max Working MPa'),
    (214.9, 170.2, 261.4, 181.5, 'Global Trips'),
    (331.7, 170.2, 377.9, 181.5, 'PopOﬀSet L'),
    (447.4, 170.2, 495.4, 181.5, 'PopOﬀSet H'),
    (570.3, 170.2, 604.9, 181.5, 'Ave Rate'),
    (687.1, 170.2, 720.7, 181.5, 'Ave MPa'),
    (801.9, 170.2, 838.4, 181.5, 'Max Rate'),
    (918.6, 170.2, 954.1, 181.5, 'Max MPa'),
    (1040.6, 170.2, 1065.4, 181.5, 'F_ISIP'),
    (1151.5, 170.2, 1187.7, 181.5, 'F_BHISIP'),
    (1276.0, 170.2, 1295.8, 181.5, 'F_FG'),
    (29.7, 185.4, 37.8, 194.5, '74'),
    (105.8, 181.8, 138.1, 198.4, '87.00'),
    (222.0, 181.8, 254.4, 198.4, '85.00'),
    (454.5, 181.8, 486.9, 198.4, '84.00'),
    (570.8, 181.8, 603.1, 198.4, '14.96'),
    (687.0, 181.8, 719.4, 198.4, '79.64'),
    (804.0, 181.8, 836.4, 198.4, '17.70'),
    (920.2, 181.8, 952.6, 198.4, '84.94'),
    (1036.5, 181.8, 1068.9, 198.4, '48.72'),
    (1152.8, 181.8, 1185.1, 198.4, '82.43'),
    (1269.0, 181.8, 1301.4, 198.4, '23.96'),
    (30.1, 200.4, 38.2, 209.5, '73'),
    (105.8, 196.1, 138.1, 212.6, '87.00'),
    (222.0, 196.1, 254.4, 212.6, '85.00'),
    (454.5, 196.1, 486.9, 212.6, '84.00'),
    (570.8, 196.1, 603.1, 212.6, '13.21'),
    (687.0, 196.1, 719.4, 212.6, '79.07'),
    (804.0, 196.1, 836.4, 212.6, '15.96'),
    (920.2, 196.1, 952.6, 212.6, '85.28'),
    (1036.5, 196.1, 1068.9, 212.6, '49.36'),
    (1152.8, 196.1, 1185.1, 212.6, '83.07'),
    (1269.0, 196.1, 1301.4, 212.6, '24.15'),
]
P139_PRESSURE_BOXES = [  # its header rectangles
    (63.8, 168.0, 180.0, 183.0),
    (180.0, 168.0, 296.2, 183.0),
    (296.2, 168.0, 413.2, 183.0),
    (413.2, 168.0, 529.5, 183.0),
    (529.5, 168.0, 645.8, 183.0),
    (645.8, 168.0, 762.0, 183.0),
    (762.0, 168.0, 878.2, 183.0),
    (878.2, 168.0, 994.5, 183.0),
    (994.5, 168.0, 1111.5, 183.0),
    (1111.5, 168.0, 1227.8, 183.0),
    (1227.8, 168.0, 1344.0, 183.0),
]

# page text of the pages a rule took for something they are not
T88_STEPDOWN = "\n".join(['Stage', 'FSD Start', 'Rate', 'FSD WB', 'Fric', 'FSD 1st', 'BHP', 'FSD NWB', 'Fric', 'FSD Perf', 'Fric', 'FSD T Fric', 'FSD Perfs', 'Open', 'F_ISIP', 'F_BHISIP', 'F_FG', 'F 1Min', 'F 5Min', 'F 15Min', '1', '25.50', '57.82', '17.532', 'FINAL STEP DOWN SUMMARY'])  # 00269 p88
T150_CHEMICAL = "\n".join(['Chemical Name', 'Chemic', 'al Uni..', 'Stage No', '1', '2', '3', 'B701', 'L', 'BLE-475U', 'kg', 'SODA ASH', 'kg', '0K', '1K', '2K', 'CHEMICAL COMPARISON', 'Proposed Quote vs Field Design vs Actual Pumped Volumes', 'Measure Names', 'Chemical Actual', 'Chemical Field Design'])  # 00470 p150
T154_COMPLETION = "\n".join(['Stage', '1', '2', '3', '% Complete', 'JOB COMPLETION PERCENTAGE', 'Measure Names', '% Design Clean', '% Design Proppant'])  # 00470 p154
T165_FLUIDCHART = "\n".join(['Stage No', '2', '4', '6', '0', '500', '1000', 'Fluid Vol (m3)', 'TREATMENT FLUID VOLUME BY STAGE', 'Fluid Name', 'HCR Acid', 'HCR-14', 'HVFR 1.75', 'HVFR 2.0'])  # 00470 p165


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

    def test_final_step_down_is_its_own_sheet_not_the_pressure_grid(self):
        # it prints F_BHISIP, which filed it under "pressure" beside p87
        self.assertEqual(ls._page_kind(T88_STEPDOWN), "stepdown")

    def test_a_measure_names_legend_alone_is_not_the_pressure_pivot(self):
        # every multi-measure chart prints that legend title
        self.assertEqual(ls._page_kind(T150_CHEMICAL), "chemical")
        self.assertIsNone(ls._page_kind(T154_COMPLETION))
        self.assertEqual(ls._page_kind(T116), "pressure_measures")

    def test_the_dark_theme_well_completions_summary(self):
        # 01124 p69: the late-2025 sheets say COMPLETIONS
        self.assertEqual(ls._page_kind(
            "WELL COMPLETIONS SUMMARY\nPETRONAS HZ TOWN d-4-C/94-G-1\n45031\n"
            "Lower Montney\nPlug and Perf\nWell Name\nAPI\nAFE"),
            "wellcompletion")

    def test_the_fluid_bar_chart_is_not_the_fluid_grid(self):
        self.assertEqual(ls._page_kind(T165_FLUIDCHART), "fluid_chart")

    def test_the_right_aligned_corpus_sheets_keep_their_kinds(self):
        for cells, kind in ((P85_PROPPANT, "proppant"), (P86_FLUID, "fluid"),
                            (P87_PRESSURE, "pressure"),
                            (P90_WELLBORE, "wellbore"),
                            (P141_WELLBORE, "wellbore"),
                            (P139_PRESSURE, "pressure")):
            self.assertEqual(ls._page_kind(_Page(cells).get_text()), kind)


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

    def test_the_footer_is_kept_as_printed(self):
        # its own sheet: its own pitch, and PopOffSet H (90.00) third
        self.assertEqual(self.tab["footer"]["Min"][:4],
                         ["82.00", "84.00", "90.00", "4.55"])

    def test_a_footer_no_column_agrees_with_is_not_shipped(self):
        # it summarises 77 stages and the fixture holds three; matched by
        # order it put PopOffSet H's 90.00 under Ave Rate, Ave Rate's 4.55
        # under Ave MPa, and so on to F_FG's under BD_Psi
        self.assertEqual(self.tab["totals"], {})


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
        self.assertEqual(self.tab["empty_columns"], ["HVFR 1.00 (m3)"])


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


class RightAlignedPressure(unittest.TestCase):
    """00269 p87: numbers flush right, names centred 25 pt to their left, five
    columns titled and never filled. A centre-x cluster named none of the
    nine filled columns (col1..col9) and listed all fourteen as empty."""
    WANT = ["Stage", "Max Working PSI", "Global Trips", "Ave Rate", "Ave PSI",
            "Max Rate", "Max PSI", "F_ISIP", "F_BHISIP", "F_FG"]

    def check(self, tab):
        self.assertEqual(tab["columns"], self.WANT)
        self.assertEqual(tab["empty_columns"], [
            "PopOﬀSet L", "PopOﬀSet H", "F 5Min", "F 10Min", "F 15Min"])
        self.assertEqual(tab["rows"][0], [
            "1", "80.00", "82.00", "7.69", "77.15", "9.38", "79.25",
            "25.50", "57.82", "17.53"])
        self.assertEqual(tab["rows"][1][0], "2")
        # the footer covers 28 stages; of the fixture's two, only the two
        # constant columns agree with it, and only they get a total
        self.assertEqual(tab["totals"]["Max"],
                         ["80.00", "82.00"] + [None] * 7)

    def test_by_the_header_rectangles(self):
        self.check(ls._stage_grid(_Page(P87_PRESSURE, P87_PRESSURE_BOXES)))

    def test_by_the_header_names_alone(self):
        self.check(ls._stage_grid(_Page(P87_PRESSURE)))


class FlushVolumeUnits(unittest.TestCase):
    """the wellbore flush column prints its unit "(m3)" (49367), "m3"
    (00738), "bbl" (00269) or "Gal" (00697); the column name carries it one
    way"""
    def test_bbl(self):
        for boxes in (P90_WELLBORE_BOXES, None):
            tab = ls._stage_grid(_Page(P90_WELLBORE, boxes))
            self.assertEqual(tab["columns"], [
                "Stage", "Top Shot Flush Vol (bbl)",
                "Bottom Shot Flush Vol (bbl)", "PERF TopShot",
                "PERF BottomShot", "Sum of PERF PlugDepth",
                "PERF TotalNumShots", "PERF NumPerfClusters"])
            # ClusterLength and PerfDiam sit between filled columns
            self.assertEqual(tab["empty_columns"],
                             ["PERF ClusterLength", "PERF PerfDiam"])
            self.assertEqual(tab["rows"][0],
                             ["1", "1", "1", "6175", "6190", None, "2", "2"])
            self.assertEqual(tab["rows"][1],
                             ["2", "1", "1", "6081", "6157", "6163", "20", "5"])

    def test_bare_m3(self):
        tab = ls._stage_grid(_Page(P141_WELLBORE, P141_WELLBORE_BOXES))
        self.assertEqual(tab["columns"][1:3], ["Top Shot Flush Vol (m3)",
                                               "Bottom Shot Flush Vol (m3)"])
        self.assertEqual(tab["rows"][0], ["1", "81.13", "81.33", "7377.7",
                                          "7401.2", "7401.1", "2", "2"])
        self.assertEqual(tab["empty_columns"],
                         ["PERF ClusterLength", "PERF PerfDiam"])

    def test_gal(self):
        tab = ls._stage_grid(_Page(P127_WELLBORE, P127_WELLBORE_BOXES))
        self.assertEqual(tab["columns"][-1], "Top Shot Flush Vol (Gal)")
        self.assertEqual(tab["rows"][0],
                         ["1", "7124.00", "7149.00", "2", "2", "79.03"])

    def test_bracketed_m3_unchanged(self):
        tab = ls._stage_grid(_Page(P125_WELLBORE))
        self.assertEqual(tab["columns"][-1], "Top Shot Flush Vol (m3)")


class ThreeLineProppantHeader(unittest.TestCase):
    """00269 p85: Proppant Name / one group per proppant and Grand Total /
    Prop Actual, Prop Screw, Prop Design, Proppant Actual-Design."""
    def setUp(self):
        self.tab = ls._stage_grid(_Page(P85_PROPPANT, P85_PROPPANT_BOXES))

    def test_group_labels_prefix_the_leaf_names(self):
        leaves = ["Prop Actual", "Prop Screw", "Prop Design",
                  "Proppant Actual-Desi.."]
        self.assertEqual(self.tab["columns"], ["Stage"] + [
            "%s: %s" % (g, n) for g in ("30/70 White", "40/70 White",
                                        "Grand Total") for n in leaves])
        self.assertEqual(self.tab["empty_columns"], [])

    def test_a_flush_right_zero_stays_in_its_column(self):
        # 00738 p137: "-5,000" and "0" of one column centre 20 pt apart, and
        # a centre-x cluster made two columns of them
        tab = ls._stage_grid(_Page(P137_PROPPANT, P137_PROPPANT_BOXES))
        self.assertEqual(tab["columns"][4], "40/70 White: Proppant Actual-Design")
        self.assertEqual(tab["rows"], [
            ["1", "45000", "43602", "50000", "-5000",
             "45000", "43602", "50000", "-5000"],
            ["2", "140000", "140456", "140000", "0",
             "140000", "140456", "140000", "0"]])

    def test_a_group_with_no_value_in_a_row_is_left_blank(self):
        self.assertEqual(self.tab["rows"][0], [
            "1", None, None, None, None, "50000", "49936", "50000", "0",
            "50000", "49936", "50000", "0"])
        self.assertEqual(self.tab["rows"][2], [
            "3", "250000", "253656", "250000", "0", None, None, None, None,
            "250000", "253656", "250000", "0"])

    def test_grand_total_footer(self):
        # 28 stages summed, three in the fixture: only the all-zero
        # Actual-Design columns add up, so only they carry it
        self.assertEqual(self.tab["footer"]["Grand Total"][-4:],
                         ["6700000", "6628358", "6700000", "0"])
        # (40/70 White is pumped on stages 1 and 2 only, so its total is
        # whole in the fixture and is matched)
        self.assertEqual(self.tab["totals"]["Grand Total"], [
            None, None, None, "0", "300000", "297510", "300000", "0",
            None, None, None, "0"])


class FooterTotals(unittest.TestCase):
    """00938 p40, a one-stage job: the whole sheet and its whole footer. The
    footer prints PopOffSet H (48.00) third, which the grid does not, and
    nothing for F_BHISIP / F_FG / BD_Psi."""
    def setUp(self):
        self.tab = ls._stage_grid(_Page(P40_PRESSURE, P40_PRESSURE_BOXES))

    def test_each_total_under_the_column_it_summarises(self):
        self.assertEqual(self.tab["columns"], [
            "Stage", "Max Working MPa", "Sum of Global Trips", "Ave Rate",
            "Ave MPa", "Max Rate", "Max MPa", "F_ISIP"])
        row = self.tab["rows"][0][1:]
        for lab in ("Min", "Max", "Average"):
            self.assertEqual(self.tab["totals"][lab], row, lab)
        self.assertEqual(self.tab["footer"]["Min"][2], "48.00")

    def test_by_value_through_the_rounding(self):
        rows = [["1", "8.78", "41.10"], ["2", "10.43", "67.90"],
                ["3", "10.66", "58.24"]]
        got = ls._footer_totals(2, rows, {
            "Min": ["90.00", "8.78", "41.10"],
            "Average": ["92.29", "9.96", "55.75"],
            "Grand Total": ["1", "29.87", "167.24"]})
        self.assertEqual(got, {"Min": ["8.78", "41.10"],
                               "Average": ["9.96", "55.75"],
                               "Grand Total": ["29.87", "167.24"]})
        self.assertEqual(ls._footer_totals(2, rows, {"Max": ["9.00"]}), {})

    def test_stitched_sheets_are_totalled_over_every_page(self):
        # 49367 p123 cut after stage 2, the Min row on page two carrying the
        # minima of stages 1-3 at the footer sheet's own x (PopOffSet H's
        # 90.00 third). Page two alone agrees only on its constant columns.
        head = [c for c in P123_PRESSURE if c[1] < 181]
        mins = iter(["84.00", "87.00", "90.00", "8.78", "77.45", "10.53",
                     "82.09", "24.20", "43.00", "22.04"])
        foot = [c if c[4] == "Min" else c[:4] + (next(mins),)
                for c in sorted((c for c in P123_PRESSURE
                                 if 1264 <= c[1] < 1265), key=lambda c: c[0])]
        one = head + [c for c in P123_PRESSURE if 181 <= c[1] < 209]
        two = head + [c for c in P123_PRESSURE if 209 <= c[1] < 223] + foot
        self.assertEqual(ls._stage_grid(_Page(two))["totals"]["Min"],
                         ["84.00", "87.00"] + [None] * 8)
        tab = ls.parse_pressure(_Doc([_Page(one), _Page(two)]))
        self.assertEqual([r[0] for r in tab["rows"]], ["1", "2", "3"])
        self.assertEqual(tab["totals"], {"Min": [
            "84.00", "87.00", "8.78", "77.45", "10.53", "82.09", "24.20",
            "43.00", "22.04", None]})


class TwoSheetFluidHeader(unittest.TestCase):
    """00269 p86: Fresh Water / HCR Acid / HVFR over a bbls line, then Ave
    Temp / Ave Visc / Avep H in one tall cell each, all flush right"""
    def test_names_units_and_the_side_sheet(self):
        tab = ls._stage_grid(_Page(P86_FLUID, P86_FLUID_BOXES))
        self.assertEqual(tab["columns"], [
            "Stage", "Fresh Water (bbls)", "HCR Acid (bbls)", "HVFR (bbls)",
            "Ave Temp", "Ave Visc", "Avep H"])
        self.assertEqual(tab["rows"], [
            ["1", "42", "5", "492", "14.00", "14.00", "7.00"],
            ["2", "84", "5", "1270", "18.10", "9.00", "7.50"]])


class Stitching(unittest.TestCase):
    def test_a_reprinted_sheet_is_read_once(self):
        # 00470 prints the whole sheet set twice; every stage came back twice
        doc = _Doc([_Page(P139_PRESSURE, P139_PRESSURE_BOXES),
                    _Page(P139_PRESSURE, P139_PRESSURE_BOXES)])
        tab = ls.parse_pressure(doc)
        self.assertEqual(tab["pages"], [1])
        self.assertEqual(tab["repeated_pages"], [2])
        self.assertEqual(len(tab["rows"]), 2)

    def test_rows_come_in_stage_order(self):
        # 00738 sorts its pressure grid 74 down to 1
        tab = ls.parse_pressure(_Doc([_Page(P139_PRESSURE,
                                            P139_PRESSURE_BOXES)]))
        self.assertEqual([r[0] for r in tab["rows"]], ["73", "74"])
        self.assertEqual(tab["rows"][1][:4], ["74", "87.00", "85.00", "84.00"])
        self.assertIn("PopOﬀSet H", tab["columns"])
        self.assertEqual(tab["empty_columns"], ["PopOﬀSet L"])

    def test_a_sheet_continued_on_a_second_page_stitches_by_name(self):
        # 49367 p122 cut after stage 2: page one fills HVFR 1.50 and not
        # 1.25, page two the other way round. Matched by position, page two's
        # HVFR 1.25 volumes landed under HVFR 1.50.
        head = [c for c in P122_FLUID if c[1] < 192]
        one = head + [c for c in P122_FLUID if 192 <= c[1] < 226]
        two = head + [c for c in P122_FLUID if c[1] >= 226] + [
            (38.8, 246.8, 43.7, 257.9, '4')]
        tab = ls.parse_fluid(_Doc([_Page(one), _Page(two)]))
        self.assertEqual(tab["pages"], [1, 2])
        self.assertEqual(tab["columns"], [
            "Stage", "Treated Water (m3)", "CAN HCl+WL 15 (m3)",
            "HVFR 1.25 (m3)", "HVFR 1.50 (m3)"])
        self.assertEqual(tab["empty_columns"], ["HVFR 1.00 (m3)"])
        self.assertEqual(tab["rows"], [
            ["1", "150.6", "4.0", None, "560.7"],
            ["2", "74.5", "1.0", None, "532.3"],
            ["3", "72.4", "1.0", "491.6", None],
            ["4", "71.8", "1.0", "491.1", None]])


if __name__ == "__main__":
    unittest.main()
