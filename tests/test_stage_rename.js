// Renaming a stage, and where the new name has to turn up.
//
//   node tests/test_stage_rename.js
//
// The reports are not always right about their own stage numbering, so the
// printed name cannot be the only name (Carmine, 2026-09-13). Two rules hold
// this together:
//
//   - a rename must not move anything. The KEY groups a stage's charts, joins
//     a table row to a chart and matches FracView's selection; only what is
//     SHOWN and what is EXPORTED changes.
//   - a rename belongs to ONE file. The store is keyed by file + stage, and
//     every export path walks files while the SELECTED file is whatever was
//     last clicked — so the file has to be passed, not read off the screen.
const fs = require("fs");
const path = require("path");
const SRC = path.join(__dirname, "..", "lab", "public", "index.html");
const src = fs.readFileSync(SRC, "utf8");

function lift(name) {
  const at = src.indexOf("function " + name + "(");
  if (at < 0) throw new Error(`${name} is gone from index.html`);
  let d = 0;
  for (let i = src.indexOf("{", at); i < src.length; i++) {
    if (src[i] === "{") d++; else if (src[i] === "}" && --d === 0) return src.slice(at, i + 1);
  }
}

// the store, standing in for localStorage
let stageName = {};
let current = null, scopeFile = "";
const fileScope = () => scopeFile ||
  (current && current.entry && current.entry.name) || "?";
const stageNameKey = (key, file) => `${file || fileScope()}::${key}`;
eval(lift("stageNameGet"));
eval(lift("stageLabel"));
eval(lift("stageDisplay"));
eval(lift("labelAddsInfo"));
const _VARIANT = /\s+(Surface|BH|Bottom\s*Hole)\s*$/i;
const stageNum = s => { const m = /(\d+)/.exec(String(s)); return m ? +m[1] : 1e9; };
eval(lift("chartStageLabels"));

let pass = 0, fail = 0;
const is = (got, want, what) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? pass++ : fail++;
  console.log(`${ok ? "  ok  " : "  FAIL"} ${what}`);
  if (!ok) console.log(`        got ${JSON.stringify(got)}  want ${JSON.stringify(want)}`);
};

const item = k => ({ type: "stage", key: k });

// ---- the label, and what it leaves alone -----------------------------
stageName = {};
scopeFile = "A.pdf";
is(stageLabel(item("3")), "3", "with no rename the sheet's own name stands");
stageName["A.pdf::3"] = "3 RE-FRAC";
is(stageLabel(item("3")), "3 RE-FRAC", "a rename shows instead");
is(item("3").key, "3", "the key is untouched — a rename must not move a stage");

// ---- one file's rename must not reach another ------------------------
scopeFile = "B.pdf";
is(stageLabel(item("3")), "3", "B.pdf's stage 3 is not renamed by A.pdf's");
is(stageLabel(item("3"), "A.pdf"), "3 RE-FRAC",
   "an export loop names the file it is on and gets that file's rename");
is(stageLabel(item("3"), "B.pdf"), "3", "...and the other file's stays its own");

// The bug this guards: every export path walks files while `current` still
// points at whatever was last clicked. Reading the scope there put one file's
// corrections on another's rows.
scopeFile = "";
current = { entry: { name: "A.pdf" } };
is(stageLabel(item("3"), "B.pdf"), "3",
   "an explicit file beats the selected one");

// ---- the join into a table ------------------------------------------
scopeFile = "A.pdf";
// bare numbers say nothing the Stage Number column does not already say, and
// filling the column with those dresses a duplicate as new information
is([...chartStageLabels([item("1"), item("2")], "A.pdf")], [],
   "a stage called '1' adds nothing to a table that already prints 1");
is([...chartStageLabels([item("1"), item("3")], "A.pdf")], [[3, "3 RE-FRAC"]],
   "a renamed stage DOES add something and joins");
is([...chartStageLabels([item("5 Surface")], "A.pdf")], [],
   "the Surface/BH suffix is a chart type, not a name");
stageName["A.pdf::7"] = "HRF 7A";
is([...chartStageLabels([item("7")], "A.pdf")], [[7, "HRF 7A"]],
   "a named zone joins");

// two charts for one number cannot be told apart, so neither is claimed
is([...chartStageLabels([item("3"), item("3 (2)")], "A.pdf")], [],
   "an ambiguous number refuses the join rather than guessing");

// ---- the export path exists -----------------------------------------
const ok = (c, w) => is(!!c, true, w);
ok(/function tableCSV\(t, entry\)/.test(src),
   "tableCSV takes the entry it is exporting, so it can name the file");
ok(/curateTable\(t, prov, chartStageLabels\(entry\.secItems, entry\.name\)\)/.test(src),
   "the table CSV curates with THIS entry's chart labels");
ok(/function wellModel\(stages, file\)/.test(src),
   "the seconds CSV is told which file's renames apply");
ok(!/tableCSV\(t\)\s*[,)]/.test(src),
   "no call site is left guessing the file");

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
