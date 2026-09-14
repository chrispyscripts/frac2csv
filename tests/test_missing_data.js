// The stacked view's "Missing Data" overlay.
//
//   node tests/test_missing_data.js
//
// Two faults look identical once a trace is drawn, and only one of them is
// honest. A GAP is the chart having no ink to read. A FLAT RUN is something
// that is not the curve — a horizontal rule — read as if it were, and that
// one exports a number, which gets believed.
//
// 01350 page 226 is why this exists: 44% of its WH Prop Conc samples sat at
// exactly 698.29, from sample 9 to 3019, the full width of the plot, against
// a report printing a maximum of 504. The identical 698.29 turns up on five
// pages of a different well. A curve does not do that.
const fs = require("fs");
const path = require("path");
const SRC = path.join(__dirname, "..", "lab", "public", "stacked.html");
const src = fs.readFileSync(SRC, "utf8");
function lift(name) {
  const at = src.indexOf("function " + name + "(");
  if (at < 0) throw new Error(`${name} is gone from stacked.html`);
  let d = 0;
  for (let i = src.indexOf("{", at); i < src.length; i++) {
    if (src[i] === "{") d++; else if (src[i] === "}" && --d === 0) return src.slice(at, i + 1);
  }
}
const m = src.match(/const FLAT_MIN_FRAC = ([\d.]+)/);
if (!m) throw new Error("FLAT_MIN_FRAC is gone from stacked.html");
const FLAT_MIN_FRAC = parseFloat(m[1]);
eval(lift("flatRuns"));
eval(lift("gapRuns"));

let pass = 0, fail = 0;
const is = (got, want, what) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? pass++ : fail++;
  console.log(`${ok ? "  ok  " : "  FAIL"} ${what}`);
  if (!ok) console.log(`        got ${JSON.stringify(got)}  want ${JSON.stringify(want)}`);
};

const n = 200;

// ---- a rule traced as data -------------------------------------------
const pinned = [];
for (let i = 0; i < n; i++) pinned.push(i < 88 ? 698.29 : 100 + i * 0.5);
is(flatRuns(pinned, 0, 700), [[0, 88, 698.29]],
   "a long run pinned to one value is reported, with the value");

// ---- a real curve is left alone --------------------------------------
const curve = [];
for (let i = 0; i < n; i++) curve.push(50 + 40 * Math.sin(i / 9));
is(flatRuns(curve, 0, 100), [], "a moving curve has no flat runs");

// ---- a genuine hold is not a rule ------------------------------------
const hold = [];
for (let i = 0; i < n; i++) hold.push(i >= 80 && i < 90 ? 70 : 70 + (i % 7));
is(flatRuns(hold, 0, 100), [],
   "a SHORT hold is a plateau in the data, not a rule, and is not flagged");

// ...but a hold that runs most of the chart is
const longHold = [];
for (let i = 0; i < n; i++) longHold.push(i < 150 ? 70 : 70 + (i % 7));
is(flatRuns(longHold, 0, 100).length, 1,
   "a hold spanning most of the chart IS flagged — that is the shape of a rule");

// ---- gaps ------------------------------------------------------------
const gappy = [];
for (let i = 0; i < n; i++) gappy.push(i >= 40 && i < 60 ? null : i);
is(gapRuns(gappy), [[40, 60]], "a blank span is one gap run");
is(gapRuns([]), [], "no samples, no gaps");
is(gapRuns([1, 2, 3]), [], "a complete channel has no gaps");

const nanny = [1, 2, NaN, NaN, 5];
is(gapRuns(nanny), [[2, 4]], "NaN counts as missing, not as a value");

// ---- the two are independent -----------------------------------------
const both = [];
for (let i = 0; i < n; i++) both.push(i < 88 ? 698.29 : (i < 100 ? null : 100 + i));
is(flatRuns(both, 0, 700), [[0, 88, 698.29]], "flat run found beside a gap");
is(gapRuns(both), [[88, 100]], "gap found beside a flat run");

// ---- a flat run of NOTHING is a gap, not a flat run -------------------
const empty = new Array(n).fill(null);
is(flatRuns(empty, 0, 100), [], "all-blank is not a flat run");
is(gapRuns(empty), [[0, n]], "all-blank is one long gap");

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
