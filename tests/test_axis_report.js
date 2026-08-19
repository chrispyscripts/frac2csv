// What a flag report says an axis is (#571).
//
//   node tests/test_axis_report.js
//
// The channel table is the best diagnostic in the project, so the number in
// it has to be the number on the sheet. It used to print the FRAME — the
// axis read at the plot's frame edges, which is what ghost is positioned
// against — so #571 reported "scale for LIB-1 are not being extracted
// correctly" against a chart whose axes read -4.02..106.06 and 115.35..5.29
// on a page printing 0..100 and 10..110. Both frame numbers were honestly
// measured; neither is what the sheet prints.
const fs = require("fs");
const path = require("path");

const SRC = path.join(__dirname, "..", "lab", "public", "index.html");
const src = fs.readFileSync(SRC, "utf8");
const round2 = v => Math.round(v * 100) / 100;
function lift(name) {
  const at = src.indexOf("function " + name + "(");
  if (at < 0) throw new Error(`${name} is gone from index.html`);
  let d = 0;
  for (let i = src.indexOf("{", at); i < src.length; i++) {
    if (src[i] === "{") d++; else if (src[i] === "}" && --d === 0) return src.slice(at, i + 1);
  }
}
eval(lift("axisReport"));

let pass = 0, fail = 0;
const is = (got, want, what) => {
  const ok = got === want;
  ok ? pass++ : fail++;
  console.log(`${ok ? "  ok  " : "  FAIL"} ${what}`);
  if (!ok) console.log(`        got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
};

console.log("00494 — the real numbers from #571");
is(axisReport({ lo: -4.02, hi: 106.06, printed: true, pLo: 0, pHi: 100 }),
   "0..100 (frame -4.02..106.06)",
   "Treating Pressure: the sheet's 0..100 leads, the frame stays visible");
is(axisReport({ lo: 115.35, hi: 5.29, printed: true, pLo: 10, pHi: 110 }),
   "10..110 (frame 115.35..5.29)",
   "Hydr Pressure: Liberty prints this one INVERTED, and the frame shows it");
is(axisReport({ lo: 1750, hi: 0, printed: true, pLo: 0, pHi: 1750 }),
   "0..1750", "stage 1 conc: frame IS the printed range, so nothing is appended");
is(axisReport({ lo: -227.94, hi: 1640.05, printed: true, pLo: 0, pHi: 1750 }),
   "0..1750 (frame -227.94..1640.05)",
   "stage 60 conc, 13% out: the worst drift measured, and it must stay visible");

console.log("\nthe cases that are not Liberty");
is(axisReport({ lo: 0, hi: 90, printed: true, pLo: 0, pHi: 90 }),
   "0..90", "SLB after eb94869: frame and printed agree");
is(axisReport({ lo: 0, hi: 400, printed: false }),
   "0..400 (guessed)", "no axis recorded at all still says so");
is(axisReport({ lo: 0, hi: 100, printed: true }),
   "0..100", "the axisMax branch sets no pLo/pHi — lo..hi IS the printed range");
is(axisReport({ lo: 0, hi: 0, printed: true, pLo: 0, pHi: 0 }),
   "0..0", "a zero span cannot be divided by");

console.log("\nthe 1% threshold");
is(axisReport({ lo: 0, hi: 100.9, printed: true, pLo: 0, pHi: 100 }),
   "0..100", "0.9% off is the frame sitting a hair past the last tick — quiet");
is(axisReport({ lo: 0, hi: 101.5, printed: true, pLo: 0, pHi: 100 }),
   "0..100 (frame 0..101.5)", "1.5% off is worth seeing");

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
