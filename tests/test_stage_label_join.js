// Stage Label joined from the chart — the guards, pinned.
//
//   node tests/test_stage_label_join.js
//
// The functions under test live inside lab/public/index.html, which is one
// 5,000-line file with a single inline <script> and no module boundary. So
// this reads them straight OUT of that file rather than keeping a copy: a
// copy would pass forever while the shipped rule drifted away from it.
//
// What is being protected is not the happy path — it is the two refusals.
// A joined label that is wrong invents a stage name and puts it in the
// column Carmine reads as fact, so both guards matter more than the fill:
//
//   - one chart per stage number, or no join (BJ 00636 charts stage 5 twice)
//   - the name must say more than the number ("Stage 05" says nothing new)
const fs = require("fs");
const path = require("path");

const SRC = path.join(__dirname, "..", "lab", "public", "index.html");
const src = fs.readFileSync(SRC, "utf8");

// the two helpers the joins depend on, which live far from them in the file
const stageNum = s => { const m = String(s).match(/\d+/); return m ? +m[0] : 1e9; };
const _VARIANT = /\s+(Surface|BH|Bottom\s*Hole)\s*$/i;
const stageDisplay = key => String(key).replace(_VARIANT, "");
const stageLabel = item => item.key;

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
eval(lift("labelAddsInfo"));
eval(lift("chartStageLabels"));
eval(lift("deriveStageLabel"));

let pass = 0, fail = 0;
function is(got, want, what) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? pass++ : fail++;
  console.log(`${ok ? "  ok  " : "  FAIL"} ${what}`);
  if (!ok) console.log(`        got ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
}
const charts = keys => keys.map(k => ({ type: "stage", key: k }));

console.log("labelAddsInfo — the number alone is not a name");
is(labelAddsInfo("5", 5), false, '"5"');
is(labelAddsInfo("05", 5), false, '"05" — leading zero is still just the number');
is(labelAddsInfo("Stage 05", 5), false, '"Stage 05"');
is(labelAddsInfo("Zone 3", 3), false, '"Zone 3"');
is(labelAddsInfo("Interval 12", 12), false, '"Interval 12"');
is(labelAddsInfo("HRF 5A", 5), true, '"HRF 5A" — 5A is not 5');
is(labelAddsInfo("Zone 3 - Montney C", 3), true, '"Zone 3 - Montney C"');
is(labelAddsInfo("5 (2)", 5), true, '"5 (2)"');

console.log("chartStageLabels — BJ 00636, the real keys it extracts");
is([...chartStageLabels(charts(["1", "2", "3", "4", "5", "5 (2)"]))], [],
   "bare numbers say nothing new and stage 5 is charted twice -> no join");

console.log("chartStageLabels — the guards");
is([...chartStageLabels(charts(["HRF 5A"]))], [[5, "HRF 5A"]],
   "one chart, and it names the stage -> join");
is([...chartStageLabels(charts(["HRF 5A", "HRF 5B"]))], [],
   "two charts on stage 5 -> refuse, rather than pick one for the single row");
is([...chartStageLabels(charts(["Zone 3 Surface"]))], [],
   "#546: the Surface/BH variant is a chart type, stripped before judging");
is([...chartStageLabels(charts(["Zone 3 - Montney C Surface"]))],
   [[3, "Zone 3 - Montney C"]], "variant stripped, the zone name survives it");
is([...chartStageLabels(charts(["?"]))], [], "no number to join on -> skipped");
is([...chartStageLabels([])], [], "no charts");
is([...chartStageLabels(undefined)], [], "no chart list at all");

console.log("deriveStageLabel — keyed on the table's own number, not row order");
const stageno = { term: { key: "stageno" }, parts: [{ i: 1, f: 1 }] };
const known = new Map([[5, "HRF 5A"], [7, "HRF 7A"]]);
const derive = deriveStageLabel([stageno], known);
is(derive(["uwi", "5"]), "HRF 5A", "row for stage 5");
is(derive(["uwi", "07"]), "HRF 7A", '"07" reads as 7');
is(derive(["uwi", "6"]), "", "a stage with no chart stays empty, not guessed");
is(derive(["uwi", ""]), "", "blank stage cell stays empty");
is(deriveStageLabel([{ term: { key: "stageno" }, parts: [] }], known), null,
   "no stage-number column -> nothing to key off, so no join");
is(deriveStageLabel([stageno], new Map()), null, "no named charts -> no join");

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
