// FracView's row axis must name the CSV's own line. Pinned.
//
//   node tests/test_fracview_rows.js
//
// The number under the cursor is the number Carmine types into Excel to find
// the same sample, so an off-by-one here is worse than no feature: it points
// confidently at the wrong reading. wellCSV (index.html) writes
//
//   line 1  head
//   line 2  units
//   line 3  first sample of stage 1
//
// and the xlsx MAIN sheet is built from the same model, so Excel's row
// numbers agree. This test rebuilds that file from the same stage data
// FracView is handed and checks rowAt() against the actual line index —
// including the cases that shift it: a boundary dragged into a stage, an
// idle tail with no samples, and stages at different sample rates.
const fs = require("fs");
const path = require("path");

const SRC = path.join(__dirname, "..", "lab", "public", "fracview.html");
const src = fs.readFileSync(SRC, "utf8");

let well = null, edits = null;
const nStages = () => edits.bounds.length - 1;
const srcAt = t => {
  for (const st of well.stages) {
    if (t >= st.t0 && t < st.t0 + st.n * st.dsec * 1000) return st;
  }
  return null;
};
const fmtDay = ms => {
  const d = new Date(ms), p = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
};

function lift(name, kind) {
  const at = src.indexOf((kind || "function ") + name + (kind ? "" : "("));
  if (at < 0) throw new Error(`${name} is gone from fracview.html`);
  let depth = 0;
  for (let i = src.indexOf("{", at); i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}" && --depth === 0) return src.slice(at, i + 1);
  }
  throw new Error(`${name} is unbalanced`);
}
const CSV_HEADER_ROWS = +(/const CSV_HEADER_ROWS = (\d+)/.exec(src) || [])[1];
let rowMap = [];
eval(lift("buildRowMap"));
eval(lift("rowAt"));
eval(lift("printedDay"));

let pass = 0, fail = 0;
function is(got, want, what) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? pass++ : fail++;
  console.log(`${ok ? "  ok  " : "  FAIL"} ${what}`);
  if (!ok) console.log(`        got ${JSON.stringify(got)}  want ${JSON.stringify(want)}`);
}

// The CSV as wellCSV would write it: two header lines, then every stage's
// samples in order. -> array where index is the 1-based line, value is the
// absolute time of the sample on it.
function csvLines() {
  const lines = [null, null, null];         // 1 and 2 are head/units
  for (let i = 0; i < nStages(); i++) {
    const a = edits.bounds[i], b = edits.bounds[i + 1];
    const parts = [];
    for (const st of well.stages) {
      const step = st.dsec * 1000;
      if (st.t0 + st.n * step <= a || st.t0 >= b) continue;
      const j0 = Math.max(0, Math.ceil((a - st.t0) / step));
      const j1 = Math.min(st.n, Math.ceil((b - st.t0) / step));
      if (j1 > j0) parts.push({ st, step, j0, j1 });
    }
    parts.sort((x, y) => (x.st.t0 + x.j0 * x.step) - (y.st.t0 + y.j0 * y.step));
    for (const p of parts)
      for (let j = p.j0; j < p.j1; j++) lines.push(p.st.t0 + j * p.step);
  }
  lines.length -= 1;
  return lines;
}
// every exported line's own time must map back to that line
function checkAllLines(what) {
  buildRowMap();
  const lines = csvLines();
  let bad = 0, first = null;
  for (let n = 3; n < lines.length; n++) {
    const got = rowAt(lines[n]);
    if (got !== n) { bad++; if (first === null) first = `line ${n} -> ${got}`; }
  }
  is(bad === 0 ? "all" : first, "all", `${what} — ${lines.length - 3} lines round-trip`);
  return lines;
}

const T0 = Date.parse("2024-05-26T21:59:54Z");
const mk = (t0, n, dsec, date) => ({ t0, n, dsec, date, channels: [] });

console.log("one stage — the first sample is CSV line 3");
well = { stages: [mk(T0, 10, 1, "2024-05-26")], synthetic: false };
edits = { bounds: [T0, T0 + 10000] };
buildRowMap();
is(CSV_HEADER_ROWS, 2, "header is head + units");
is(rowAt(T0), 3, "first sample");
is(rowAt(T0 + 1000), 4, "second sample");
is(rowAt(T0 + 9000), 12, "last sample");
is(rowAt(T0 + 10000), 0, "past the end exports nothing");
is(rowAt(T0 - 1000), 0, "before the start exports nothing");
checkAllLines("one stage");

console.log("\ntwo stages with a real void between them");
// stage 1: 10 samples, then 8 minutes of nothing, then stage 2
const B = T0 + 10000 + 480000;
well = { stages: [mk(T0, 10, 1, "2024-05-26"), mk(B, 5, 1, "2024-05-27")],
         synthetic: false };
edits = { bounds: [T0, B, B + 5000] };
buildRowMap();
is(rowAt(T0 + 9000), 12, "stage 1 last sample");
is(rowAt(T0 + 20000), 0, "inside the void — no line exists for it");
is(rowAt(B), 13, "stage 2 starts on the next line, the void costs nothing");
is(rowAt(B + 4000), 17, "stage 2 last sample");
checkAllLines("two stages");

console.log("\na dragged boundary moves the rows with the export");
edits = { bounds: [T0 + 3000, B, B + 5000] };   // stage 1 starts 3 samples in
buildRowMap();
is(rowAt(T0), 0, "trimmed-off head is no longer exported");
is(rowAt(T0 + 3000), 3, "the new first sample is line 3");
is(rowAt(B), 10, "stage 2 shifted up by the three dropped lines");
checkAllLines("dragged boundary");

console.log("\nstages at different sample rates");
const C = T0 + 60000;
well = { stages: [mk(T0, 6, 10, "2024-05-26"), mk(C, 4, 1, "2024-05-26")],
         synthetic: false };
edits = { bounds: [T0, C, C + 4000] };
buildRowMap();
is(rowAt(T0 + 50000), 8, "10-second stage counts one line per sample, not per second");
is(rowAt(C), 9, "the 1-second stage picks up straight after");
checkAllLines("mixed rates");

console.log("\nprintedDay uses the stage's own date, never the synthetic clock");
well = { stages: [mk(T0, 6, 10, "2024-05-26"), mk(C, 4, 1, "2024-05-27")],
         synthetic: true };
is(printedDay(T0), "2024-05-26", "stage 1's printed date");
is(printedDay(C), "2024-05-27", "stage 2's printed date");
is(printedDay(T0 - 99999), "", "off a synthetic clock, no date is invented");
well.synthetic = false;
is(printedDay(T0 - 99999), fmtDay(T0 - 99999), "on a real clock, fall back to it");

console.log("\nPlot by row: two stages whose clocks overlap sit side by side");
// Carmine, 2026-10-09: "plot by row, there is an example that is coming in
// where the 2 stages still overlap". Stage 1 runs 10 s and stage 2 starts 6 s
// into it, so 4 s of the two clocks are the same. The CSV writes stage 1's
// four samples and then stage 2's five, one after the other — and the plot,
// which placed every sample by its clock, drew both blocks on the same x.
{
  let dispMap = [];
  const spacing = () => "row";
  eval(lift("buildDispMap"));
  eval(lift("partAt"));
  eval(lift("toDisp"));
  eval(lift("fromDisp"));
  eval(lift("rowAtDisp"));
  eval(lift("stageAtDisp"));
  const S2 = T0 + 6000;
  well = { stages: [mk(T0, 10, 1, "2024-05-26"), mk(S2, 5, 1, "2024-05-26")],
           synthetic: false };
  edits = { bounds: [T0, S2, S2 + 5000] };
  buildRowMap();
  buildDispMap();
  // every sample, as (stage, index), in the order the CSV writes them
  const want = [];
  for (let i = 0; i < nStages(); i++) {
    const a = edits.bounds[i], b = edits.bounds[i + 1], parts = [];
    well.stages.forEach((st, k) => {
      const step = st.dsec * 1000;
      if (st.t0 + st.n * step <= a || st.t0 >= b) return;
      const j0 = Math.max(0, Math.ceil((a - st.t0) / step));
      const j1 = Math.min(st.n, Math.ceil((b - st.t0) / step));
      if (j1 > j0) parts.push({ k, st, step, j0, j1 });
    });
    parts.sort((x, y) => (x.st.t0 + x.j0 * x.step) - (y.st.t0 + y.j0 * y.step));
    for (const p of parts)
      for (let j = p.j0; j < p.j1; j++) want.push({ k: p.k, t: p.st.t0 + j * p.step });
  }
  const xs = want.map(s => toDisp(s.t, s.k));
  is(new Set(xs).size, want.length, "every sample has a position of its own");
  is(xs.every((x, i) => i === 0 || x > xs[i - 1]), true,
     "positions run in the CSV's own order");
  is(want.map((s, i) => rowAtDisp(xs[i])), want.map((_, i) => i + 3),
     "the row under each sample is its own CSV line");
  is(stageAtDisp(toDisp(T0 + 7000, 0)), 1, "stage 1's tail is in band 2, where the CSV puts it");
  is(fromDisp(toDisp(S2 + 2000, 1)), S2 + 2000, "a position maps back to its own clock");
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
