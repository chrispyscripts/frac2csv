// Stage summary (DRAFT, #767) — the join from a chart to Liberty's stage sheets.
//
//   node tests/test_stage_summary_join.js
//
// The functions live inside lab/public/index.html, so they are read straight
// OUT of it rather than copied: a copy would pass forever while the shipped
// rule drifted away from it.
//
// What is pinned is the join, because the panel is only as honest as it:
//
//   - a chart key carries qualifiers the sheets never print ("4 (2)",
//     "4 Plug Slip") and joins on its leading stage number
//   - a sheet's Stage cell may be "04", "4" or the number 4
//   - a sheet with no row for the stage is REPORTED (fields null), not hidden
//   - a sheet the filing does not print at all is left out
//   - several charts on one stage are listed so the panel can say so
//   - other providers' tables never light the panel up
const fs = require("fs");
const path = require("path");

const SRC = path.join(__dirname, "..", "lab", "public", "index.html");
const src = fs.readFileSync(SRC, "utf8");

function lift(name) {
  const at = src.indexOf("function " + name + "(");
  if (at < 0) throw new Error(`${name} is gone from index.html`);
  let depth = 0;
  for (let i = src.indexOf("{", at); i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}" && --depth === 0) return src.slice(at, i + 1);
  }
  throw new Error(`${name} is unbalanced`);
}
eval(lift("stageSheetKind"));
eval(lift("stageJoinNum"));
eval(lift("stageSummary"));
eval(lift("stageSumPages"));

let pass = 0, fail = 0;
function is(got, want, what) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? pass++ : fail++;
  console.log(`${ok ? "  ok  " : "  FAIL"} ${what}`);
  if (!ok) console.log(`        got ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
}

// the shapes pipeline.py publishes: columns[0] "Stage", rows keyed on the
// stage as printed. Values are 49367's own where they matter.
const wellbore = {
  title: "Wellbore Summary (Liberty)",
  columns: ["Stage", "PERF TopShot", "PERF BottomShot", "Top Shot Flush Vol (m3)"],
  rows: [["1", "5480.0", "5440.0", "30.1"], ["2", "5420.0", "5380.0", null],
         ["4", "5300.0", "5260.0", "29.7"]],
};
const pressure = {
  title: "Pressure Summary (Liberty)",
  columns: ["Stage", "Max Working MPa", "Ave Rate"],
  rows: [["01", "68.2", "12.1"], ["2", "70.0", "12.0"], ["04", "71.5", "11.8"]],
};
const fluid = {                       // printed for fewer stages than charted
  title: "Fluid Summary — volumes by stage (Liberty)",
  columns: ["Stage", "Treated Water (m3)"],
  rows: [[1, "410"], [2, "395"]],     // a number, not a string
};
const groups = [
  { kind: "fluid", title: "Fluid Volumes by Stage", pages: [122] },
  { kind: "pressure", title: "Pressure Summary", pages: [123, 124] },
  { kind: "wellbore", title: "Wellbore Summary", pages: [125] },
  { kind: "proppant_chart", title: "Proppant Summary (chart)", pages: [126] },
];
const TABLES = [pressure, fluid, wellbore];   // parser order, not panel order

console.log("stageSheetKind — only Liberty's stage sheets");
is(stageSheetKind("Wellbore Summary (Liberty)").kind, "wellbore", "wellbore");
is(stageSheetKind("Pressure Summary (Liberty)").kind, "pressure", "pressure");
is(stageSheetKind("Proppant Summary (Liberty)").kind, "proppant", "proppant");
is(stageSheetKind("Fluid Summary — volumes by stage (Liberty)").kind, "fluid",
   "fluid, with the em-dash subtitle");
is(stageSheetKind("Stimulation Summary"), null,
   "Liberty's Stimulation Summary is a different shape — not a stage sheet");
is(stageSheetKind("Treatment Summary"), null, "Calfrac");
is(stageSheetKind("Totals — per-interval frac summary"), null, "BJ");
is(stageSheetKind(undefined), null, "no title");

console.log("stageJoinNum — the leading stage number");
is(stageJoinNum("4"), 4, '"4"');
is(stageJoinNum("04"), 4, '"04" — a leading zero is the same stage');
is(stageJoinNum(4), 4, "the number 4");
is(stageJoinNum("4 (2)"), 4, '"4 (2)" — a second chart for stage 4');
is(stageJoinNum("4 Plug Slip"), 4, '"4 Plug Slip"');
is(stageJoinNum("4 Surface"), 4, '"4 Surface" — the Calfrac variant tag');
is(stageJoinNum("12"), 12, '"12" is twelve, not one');
is(stageJoinNum("?"), null, '"?" has no number');
is(stageJoinNum(""), null, "blank");
is(stageJoinNum(null), null, "null");
is(stageJoinNum(4.5), null, "a fraction is no stage");

console.log("stageSummary — a plain stage");
let S = stageSummary(TABLES, groups, "1", ["1", "2", "3", "4"]);
is(S.n, 1, "stage 1");
is(S.sections.map(s => s.kind), ["wellbore", "pressure", "fluid"],
   "Wellbore / Pressure / Fluid in that order; proppant not printed -> no section");
is(S.sections[0].fields, [{ name: "PERF TopShot", value: "5480.0" },
                          { name: "PERF BottomShot", value: "5440.0" },
                          { name: "Top Shot Flush Vol (m3)", value: "30.1" }],
   "every column but Stage, as label: value");
is(S.sections[1].fields[0], { name: "Max Working MPa", value: "68.2" },
   'sheet cell "01" joins chart "1"');
is(S.sections[2].fields, [{ name: "Treated Water (m3)", value: "410" }],
   "sheet cell the number 1 joins chart \"1\"");
is(S.charts, ["1"], "one chart on stage 1");
is(S.sections.map(s => s.pages), [[125], [123, 124], [122]],
   "pages come from the Summary view's groups of the same kind");

console.log("stageSummary — qualified chart keys");
S = stageSummary(TABLES, groups, "4 (2)", ["1", "2", "4", "4 (2)", "4 Plug Slip"]);
is(S.n, 4, '"4 (2)" joins stage 4');
is(S.charts, ["4", "4 (2)", "4 Plug Slip"], "all three charts on stage 4 are named");
is(S.sections[0].fields[0].value, "5300.0", "wellbore row 4");
is(S.sections[1].fields[0].value, "71.5", 'pressure row "04"');
S = stageSummary(TABLES, groups, "4 Plug Slip", ["4 Plug Slip"]);
is(S.sections[0].fields[0].value, "5300.0", '"4 Plug Slip" -> row 4');

console.log("stageSummary — missing rows are said, not hidden");
S = stageSummary(TABLES, groups, "3", ["1", "2", "3", "4"]);
is(S.sections.map(s => s.fields === null), [true, true, true],
   "no sheet prints stage 3 -> every section reports it");
is(S.sections.length, 3, "...and none of them is dropped");
S = stageSummary(TABLES, groups, "4", ["4"]);
is(S.sections[2].fields, null, "fluid stops at stage 2 -> not printed for stage 4");
is([S.sections[2].first, S.sections[2].last], [1, 2], "and says which stages it does list");
is(S.sections[0].fields[2], { name: "Top Shot Flush Vol (m3)", value: "29.7" },
   "the other sheets still fill");
S = stageSummary(TABLES, groups, "2", ["2"]);
is(S.sections[0].fields[2], { name: "Top Shot Flush Vol (m3)", value: null },
   "a blank cell stays blank (the panel shows a dash), not dropped");

console.log("stageSummary — no number, no sheets, other providers");
S = stageSummary(TABLES, groups, "?", ["?"]);
is(S.n, null, '"?" -> no stage number');
is(S.sections.map(s => s.fields), [null, null, null], "...so nothing is matched");
is(stageSummary([], groups, "1", ["1"]), null, "no tables -> no panel");
is(stageSummary([{ title: "Treatment Summary", columns: ["Stage", "x"],
                   rows: [["1", "2"]] }], [], "1", ["1"]), null,
   "a non-Liberty filing -> no panel");
is(stageSummary(undefined, undefined, "1", undefined), null, "nothing at all");
const dup = { ...wellbore, rows: [["4", "a"], ["04", "b"]], columns: ["Stage", "x"] };
S = stageSummary([dup], [], "4", ["4"]);
is([S.sections[0].nrows, S.sections[0].fields[0].value], [2, "a"],
   "two rows on one stage -> the first, and the count is kept to say so");
is(S.sections[0].pages, [], "no page groups -> no pages, nothing invented");

console.log("stageSummary — the table as the Lab actually receives it (49367)");
// pipeline.py puts UWI in front of Stage and joins Stage Label / Date / Start
// Time in after it from the charts. Those are not the sheet's, and the key
// column is "Stage", not "Stage Label".
const served = {
  title: "Wellbore Summary (Liberty)",
  columns: ["UWI", "Stage", "Stage Label", "Date", "Start Time", "PERF TopShot",
            "PERF BottomShot", "Sum of PERF PlugDepth", "Top Shot Flush Vol (m3)"],
  rows: [["", "1", "1", "2025-05-23", "12:03:00", "6149.40", "6190.40", "6194.90", "52.61"],
         ["", "77", "77", "2025-06-03", "06:52:00", "2045.40", "2086.40", "2092.60", "22.24"]],
};
S = stageSummary([served], [{ kind: "wellbore", pages: [125] }], "77", ["77"]);
is(S.sections[0].fields.map(f => f.name),
   ["PERF TopShot", "PERF BottomShot", "Sum of PERF PlugDepth", "Top Shot Flush Vol (m3)"],
   "UWI / Stage / Stage Label / Date / Start Time are left out");
is(S.sections[0].fields[0].value, "2045.40", "joined on Stage, row 77");
is([S.sections[0].first, S.sections[0].last], [1, 77], "range read off the Stage column");

console.log("stageSumPages");
is(stageSumPages([125]), "p. 125", "one page");
is(stageSumPages([123, 124]), "pp. 123–124", "a run");
is(stageSumPages([12, 40]), "pp. 12, 40", "a reprint elsewhere");
is(stageSumPages([]), "", "none");

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
