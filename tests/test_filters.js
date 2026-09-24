// The digitiser filters: they must remove what the tracer got wrong and
// leave what the sheet actually drew.
//
//   node tests/test_filters.js
//
// The two properties that matter, and that a moving average fails:
//   * a genuine STEP (a pump shutdown) survives — it is data, not noise;
//   * a real PEAK keeps its height and its position — breakdown pressure is
//     read off that number.
const fs = require("fs");
const path = require("path");
const P = f => path.join(__dirname, "..", "lab", "public", f);
const src = fs.readFileSync(P("index.html"), "utf8");

function lift(name) {
  const at = src.indexOf("function " + name + "(");
  if (at < 0) throw new Error(`${name} is gone from index.html`);
  let d = 0;
  for (let i = src.indexOf("{", at); i < src.length; i++) {
    if (src[i] === "{") d++; else if (src[i] === "}" && --d === 0) return src.slice(at, i + 1);
  }
  throw new Error(`${name} is unterminated`);
}
const NAMES = ["filtFinite", "filtMedianOf", "filtHampel", "filtMedian",
               "filtSavGolCoef", "filtSavGol", "filtLoess", "filtOdd",
               "filtParams", "filtApply"];
eval(NAMES.map(lift).join("\n"));

let failed = 0;
function ok(cond, what) {
  if (!cond) { console.error("FAIL " + what); failed++; }
}
function close(a, b, tol, what) {
  ok(Math.abs(a - b) <= tol, `${what} (${a} vs ${b}, tol ${tol})`);
}

// ---- a straight run is reproduced exactly ---------------------------------
// The reason for a local POLYNOMIAL instead of an average: a frac curve is
// mostly straight lines, and an average bends every one of them.
{
  const ramp = [];
  for (let i = 0; i < 60; i++) ramp.push(2 + 0.5 * i);
  const sg = filtSavGol(ramp, 11, 2);
  let worst = 0;
  for (let i = 0; i < ramp.length; i++) worst = Math.max(worst, Math.abs(sg[i] - ramp[i]));
  close(worst, 0, 1e-9, "Savitzky-Golay reproduces a straight ramp");
}

// ---- a single spike goes, and the step beside it stays --------------------
{
  const v = [];
  for (let i = 0; i < 80; i++) v.push(i < 40 ? 70 : 20);   // a pump shutdown
  v[20] = 5;                                               // a tracer spike
  const h = filtHampel(v, 7, 3);
  close(h[20], 70, 0.001, "Hampel replaces the spike with the local median");
  close(h[39], 70, 0.001, "the sample before the step is untouched");
  close(h[40], 20, 0.001, "the sample after the step is untouched");
  ok(h[39] - h[40] === 50, "the step keeps its full height");
}

// ---- the peak keeps its height and its place ------------------------------
{
  const v = [];
  for (let i = 0; i < 101; i++) v.push(30 + 40 * Math.exp(-((i - 50) ** 2) / 200));
  const sg = filtSavGol(v, 15, 2);
  let at = 0;
  for (let i = 0; i < sg.length; i++) if (sg[i] > sg[at]) at = i;
  ok(at === 50, `the peak stays at 50 (got ${at})`);
  close(sg[50], v[50], 0.6, "the peak keeps its height");
  // what a moving average would have done to the same peak
  const mv = v.map((_, i) => {
    let s = 0, n = 0;
    for (let j = Math.max(0, i - 7); j <= Math.min(v.length - 1, i + 7); j++) { s += v[j]; n++; }
    return s / n;
  });
  ok(Math.abs(sg[50] - v[50]) < Math.abs(mv[50] - v[50]),
     "and keeps it better than a moving average does");
}

// ---- gaps stay gaps -------------------------------------------------------
{
  const v = [1, 2, 3, null, 5, 6, NaN, 8, 9, 10, 11, 12];
  for (const k of ["hampel", "sg", "both", "median", "loess"]) {
    const out = filtApply(v, k, 60);
    ok(out[3] == null, `${k}: a null sample stays null`);
    ok(!filtFinite(out[6]), `${k}: a NaN sample stays missing`);
    ok(out.length === v.length, `${k}: the sample count is unchanged`);
  }
}

// ---- the ends are not dragged ---------------------------------------------
{
  const v = [];
  for (let i = 0; i < 40; i++) v.push(10 + i);
  const sg = filtSavGol(v, 21, 2);
  close(sg[0], v[0], 1e-9, "the first sample is returned as it came");
  close(sg[v.length - 1], v[v.length - 1], 1e-9, "and so is the last");
}

// ---- a zero-MAD window still has a scale ----------------------------------
// A window flat apart from one sample has MAD exactly 0, and that is the case
// Hampel exists for. Refusing to judge it — the obvious guard — skips every
// isolated spike on a steady curve. What must NOT move is a genuine step,
// which the case above already pins.
{
  const flat = new Array(40).fill(86.5);
  flat[20] = 5;
  const h = filtHampel(flat, 9, 3);
  close(h[20], 86.5, 1e-9, "an isolated sample in a flat run is a spike");
  const truly = new Array(40).fill(7);
  ok(filtHampel(truly, 9, 3).every(x => x === 7),
     "a constant window has nothing to judge and is returned as it came");
  const l = filtLoess(new Array(40).fill(5), 0.2, 2);
  ok(l.every(x => filtFinite(x)), "LOESS on perfectly flat data stays finite");
}

// ---- amount 0 is off ------------------------------------------------------
{
  const v = [3, 9, 1, 7, 2, 8, 4];
  for (const k of ["hampel", "sg", "both", "median", "loess"]) {
    const out = filtApply(v, k, 0);
    ok(out.every((x, i) => x === v[i]), `${k} at 0 returns the curve untouched`);
  }
  const untouched = [3, 9, 1, 7, 2, 8, 4];
  filtApply(untouched, "both", 80);
  ok(untouched.every((x, i) => x === v[i]), "filtApply never mutates its input");
}

// ---- the two-step pipeline beats either half on spiky, stepped data -------
{
  const truth = [];
  for (let i = 0; i < 200; i++) truth.push(i < 100 ? 60 : 25);
  const v = truth.slice();
  for (let i = 0; i < v.length; i++) v[i] += (i % 7 - 3) * 0.15;   // staircase
  for (const i of [17, 43, 71, 132, 168]) v[i] = 2;                // spikes
  const err = a => {
    let s = 0;
    // the step itself is a transition no filter should be scored on
    for (let i = 0; i < a.length; i++) if (Math.abs(i - 100) > 12) s += Math.abs(a[i] - truth[i]);
    return s / a.length;
  };
  const both = filtApply(v, "both", 50);
  ok(err(both) < err(v), "the pipeline is closer to the truth than the raw trace");
  ok(err(both) < err(filtApply(v, "sg", 50)),
     "smoothing alone leaves the spikes as humps");
  ok(err(both) < err(filtApply(v, "hampel", 50)),
     "stripping alone leaves the staircase");
  // An SG window straddling a discontinuity blends it: that is what a local
  // polynomial does, and no smoother avoids it. What must survive is the
  // LEVEL either side, a window clear of the step, and its full height.
  const h = (filtParams("both", 50).win2 - 1) / 2;
  close(both[99 - h - 1], 60, 0.4, "the level before the step is intact");
  close(both[101 + h + 1], 25, 0.4, "and the level after it");
  close(both[99 - h - 1] - both[101 + h + 1], 35, 0.8,
        "so the step keeps its full height");
}

// ---- the slider dial ------------------------------------------------------
{
  ok(filtOdd(4) % 2 === 1 && filtOdd(3) === 3, "windows are odd");
  ok(filtOdd(1) >= 3, "and never smaller than three samples");
  const lo = filtParams("sg", 0), hi = filtParams("sg", 100);
  ok(lo.win < hi.win, "more slider is a wider window");
  ok(filtParams("sg", 40).win >= 11 && filtParams("sg", 40).win <= 21,
     "the workflow's 11-21 window sits mid-slider");
  ok(filtParams("hampel", 100).nSigma === 3, "the Hampel threshold stays at 3 MAD");
}

// ---- the coefficients are a real least-squares fit ------------------------
{
  const w = filtSavGolCoef(2, 2);          // the classic 5-point quadratic
  const want = [-3 / 35, 12 / 35, 17 / 35, 12 / 35, -3 / 35];
  for (let i = 0; i < 5; i++) close(w[i], want[i], 1e-9, `SG 5-point weight ${i}`);
  close(w.reduce((a, b) => a + b, 0), 1, 1e-9, "the weights sum to one");
}

console.log(failed ? `${failed} FAILED` : "filters: all assertions passed");
process.exit(failed ? 1 : 0);
