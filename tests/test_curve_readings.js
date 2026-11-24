// Where the Lab's chart and the stacked view draw a WellSight curve's line.
//
//   node tests/test_curve_readings.js
//
// The payload puts every curve on one 0.2 m step, each depth taking the
// nearest reading (as the LAS export does). A gas or ROP curve recorded every
// 0.5 m then repeats each reading over two or three steps, and a line through
// those steps is a staircase. So a curve recorded on another step carries its
// own readings (wellsight_app.readings) and the views draw from those, as
// LogViewer prints them (measured on the drive's printouts):
//   - a line from reading to reading, each half its step shallower than its
//     depth (the middle of the interval it ends);
//   - a curve the log says to draw in steps (c.steps, ROP often): each
//     reading held level over the interval that ends at its depth.
const fs = require("fs");
const path = require("path");
function lifter(file) {
  const src = fs.readFileSync(path.join(__dirname, "..", "lab", "public", file), "utf8");
  return name => {
    const at = src.indexOf("function " + name + "(");
    if (at < 0) throw new Error(`${name} is gone from ${file}`);
    let d = 0;
    for (let i = src.indexOf("{", at); i < src.length; i++) {
      if (src[i] === "{") d++; else if (src[i] === "}" && --d === 0) return src.slice(at, i + 1);
    }
  };
}
eval(lifter("index.html")("wsTrace"));
// the stacked view's trace() reads the page's payload, D: give it ours
const stackTrace = (c, p, d0, d1) =>
  new Function("D", lifter("logstack.html")("trace") + "\nreturn trace;")(p)(c, d0, d1);

let pass = 0, fail = 0;
function eq(got, want, what) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { pass++; return; }
  fail++;
  console.log(`FAIL ${what}\n  got:  ${g}\n  want: ${w}`);
}
const r4 = pts => pts.map(([d, v]) => [Math.round(d * 1e4) / 1e4, v]);
const inside = (pts, a, b) => pts.filter(([d]) => d >= a - 1e-9 && d <= b + 1e-9);

// a 3 m log from 100 m on the payload's 0.2 m step: 16 rows
const p = { depth0: 100, step: 0.2, rows: 16 };
// gas read every 0.5 m: 10, 20, 30, 40, 50, 60, 70; on the 0.2 m rows each
// depth takes the nearest (ties deeper), so the rows hold stairs
const gasRows = [10, 10, 20, 20, 30, 30, 30, 40, 40, 50, 50, 60, 60, 60, 70, 70];
const gas = { values: gasRows, readings: { depth0: 100, step: 0.5, values: [10, 20, 30, 40, 50, 60, 70] } };
// the same readings, a curve the log draws in steps (ROP)
const rop = { ...gas, steps: true };
// gamma read every 0.2 m, as the payload: no readings of its own
const gamma = { values: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16], readings: null };

for (const [name, fn] of [["chart", wsTrace], ["stacked view", stackTrace]]) {
  // a line through gas's own readings, each a quarter metre shallower
  eq(r4(fn(gas, p, 100, 103)),
     [[99.75, 10], [100.25, 20], [100.75, 30], [101.25, 40], [101.75, 50], [102.25, 60], [102.75, 70]],
     `${name}: gas, a line through its readings half a step up`);
  // a window: it reaches past each end, so the line runs on to the edges
  const w = r4(fn(gas, p, 101.2, 101.8));
  eq(w[0][0] < 101.2 && w[w.length - 1][0] > 101.8, true, `${name}: the line reaches past the window`);
  eq(inside(w, 101.2, 101.8), [[101.25, 40], [101.75, 50]], `${name}: the readings inside a window`);
  // ROP in steps: each reading level over the half metre that ends at it
  eq(r4(fn(rop, p, 100.4, 101.1)).filter(([d]) => d >= 100 && d <= 101.5),
     [[100, 10], [100, 20], [100.5, 20], [100.5, 30], [101, 30], [101, 40], [101.5, 40], [101.5, 50]],
     `${name}: ROP in steps, each over the interval ending at its depth`);
  // a curve on the payload's own step: its rows are its readings
  eq(inside(r4(fn(gamma, p, 100.5, 100.7)), 100.5, 100.7), [[100.5, 4], [100.7, 5]],
     `${name}: gamma from the payload's rows, a tenth of a metre up`);
  // a gap in the readings stays a gap (the pen lifts)
  const gappy = { values: gasRows, readings: { depth0: 100, step: 0.5, values: [10, null, 30] } };
  eq(r4(fn(gappy, p, 100, 101)), [[99.75, 10], [100.5, null], [100.75, 30]], `${name}: a missing reading stays missing`);
  // a payload from before the readings were sent: the rows, on their step
  eq(inside(r4(fn({ values: gasRows }, p, 100.1, 100.5)), 100.1, 100.5), [[100.1, 10], [100.3, 20], [100.5, 20]],
     `${name}: no readings, the rows`);
}

console.log(`${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
