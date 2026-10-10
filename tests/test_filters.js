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
               "filtParams", "filtApply", "filtRun", "filtIsOff", "filtRescale"];
var FILT_SCALE = 2;
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
  // the window filters reach 101 samples since v1.11.46 (41 and 51 before;
  // Carmine: "increase the limit on all filters from 41 to 100")
  ok(filtParams("hampel", 100).win === 101, "Hampel reaches 101 samples");
  ok(filtParams("median", 100).win === 101, "median reaches 101 samples");
  ok(hi.win === 101, "SG reaches 101 samples");
  ok(filtParams("both", 100).win === 101 && filtParams("both", 100).win2 === 101,
     "both halves of Hampel → SG reach 101");
  ok(Math.abs(filtParams("loess", 100).frac - 0.30) < 1e-9,
     "LOESS reaches a 30% span");
  // the workflow's 11-21 SG window is still reachable, now at 6-17%
  ok(filtParams("sg", 6).win === 11 && filtParams("sg", 17).win === 21,
     "the workflow's 11-21 window sits at 6-17% of the slider");
  ok(filtParams("sg", 0).win === 5, "and the bottom of the slider is unchanged");
  ok(filtParams("hampel", 0).win === 3, "for every filter");
  ok(filtParams("hampel", 100).nSigma === 3, "the Hampel threshold stays at 3 MAD");
}

// ---- the coefficients are a real least-squares fit ------------------------
{
  const w = filtSavGolCoef(2, 2);          // the classic 5-point quadratic
  const want = [-3 / 35, 12 / 35, 17 / 35, 12 / 35, -3 / 35];
  for (let i = 0; i < 5; i++) close(w[i], want[i], 1e-9, `SG 5-point weight ${i}`);
  close(w.reduce((a, b) => a + b, 0), 1, 1e-9, "the weights sum to one");
}

// ---- two filters, in order ------------------------------------------------
{
  // spiky, stepped, staircased — the real shape
  const truth = [];
  for (let i = 0; i < 200; i++) truth.push(i < 100 ? 60 : 25);
  const v = truth.slice();
  for (let i = 0; i < v.length; i++) v[i] += (i % 7 - 3) * 0.15;
  for (const i of [17, 43, 71, 132, 168]) v[i] = 2;
  const err = a => {
    let s = 0;
    for (let i = 0; i < a.length; i++) if (Math.abs(i - 100) > 12) s += Math.abs(a[i] - truth[i]);
    return s / a.length;
  };
  const strip_then_smooth = filtRun(v, { kind: "hampel", amount: 50, kind2: "sg", amount2: 50 });
  const smooth_then_strip = filtRun(v, { kind: "sg", amount: 50, kind2: "hampel", amount2: 50 });
  ok(err(strip_then_smooth) < err(v), "the chain improves on the raw trace");
  // THE point of letting the order be chosen: it is not commutative. Smoothing
  // first spreads each spike into a hump the stripper can no longer see.
  ok(err(strip_then_smooth) < err(smooth_then_strip),
     "strip-then-smooth beats smooth-then-strip");
  const once = filtRun(v, { kind: "hampel", amount: 50 });
  ok(err(strip_then_smooth) < err(once), "and the second filter earns its place");
}

// ---- a spec saved before there was a second filter still reads ------------
{
  const v = [3, 9, 1, 7, 2, 8, 4, 6, 5, 9, 2, 7, 3];
  const old = { kind: "hampel", amount: 40 };              // no kind2 at all
  const same = filtRun(v, old);
  const explicit = filtApply(v, "hampel", 40);
  ok(same.every((x, i) => x === explicit[i]),
     "one-filter spec runs exactly as it did before the chain existed");
  ok(filtRun(v, { kind: "hampel", amount: 40, kind2: "none", amount2: 80 })
       .every((x, i) => x === explicit[i]),
     "a second filter set to none does nothing however far its slider is up");
}

// ---- off is a state, not an absence --------------------------------------
{
  ok(filtIsOff(undefined) && filtIsOff({}), "no spec is off");
  ok(filtIsOff({ kind: "none", amount: 0, kind2: "none", amount2: 0 }), "none/0 is off");
  ok(filtIsOff({ kind: "sg", amount: 0 }), "a filter at zero is off");
  ok(!filtIsOff({ kind: "sg", amount: 10 }), "a filter above zero is on");
  // the one that mattered: a chart set to off in the SECOND slot only
  ok(!filtIsOff({ kind: "none", amount: 0, kind2: "sg", amount2: 20 }),
     "a second filter alone still counts as on");
}

// ---- never past the samples it was fitted to ------------------------------
// Carmine, 2026-10-09: the SG filter sometimes put the curve below zero. A
// pump shutdown is a sharp corner, and a polynomial through a corner rings:
// 60 MPa dropping to 0 in three samples came out at -4.2 below the floor and
// 64.8 over a 60.8 hold.
{
  const v = [];
  for (let i = 0; i < 80; i++)
    v.push(i < 40 ? 60 + (i % 3) * 0.4 : i < 43 ? 60 - (i - 39) * 20
           : 0.3 * ((i * 7) % 3 === 0 ? 1 : 0));
  const top = Math.max(...v);
  for (const [kind, amt] of [["sg", 30], ["sg", 80], ["both", 50], ["loess", 30]]) {
    const o = filtApply(v, kind, amt);
    ok(Math.min(...o) >= 0, `${kind} ${amt} stays at or above the floor (${Math.min(...o)})`);
    ok(Math.max(...o) <= top + 1e-9, `${kind} ${amt} stays under the hold (${Math.max(...o)})`);
  }
}

// ---- a setting saved on the old slider keeps its window ------------------
// Rescaled as it is read, so a chart saved at Hampel 35% (17 samples) opens
// at 17 samples on the longer slider, not at 37.
{
  const oldWin = (kind, a) => kind === "sg" ? filtOdd(5 + a / 100 * 46) : filtOdd(3 + a / 100 * 38);
  for (const kind of ["hampel", "median", "sg"]) for (const a of [5, 14, 35, 60, 100]) {
    const r = filtRescale({ kind, amount: a });
    ok(Math.abs(filtParams(kind, r.amount).win - oldWin(kind, a)) <= 2,
       `${kind} ${a}% keeps its ${oldWin(kind, a)}-sample window (${filtParams(kind, r.amount).win})`);
  }
  const r = filtRescale({ kind: "both", amount: 35, kind2: "loess", amount2: 40,
    chans: { P: { use: "own", kind: "sg", amount: 35,
                  areas: [{ a: 1, b: 9, use: "own", kind: "hampel", amount: 100 }] } } });
  ok(filtParams("both", r.amount).win === 17, "Hampel → SG keeps its Hampel half");
  ok(r.amount2 === 40, "LOESS did not change");
  ok(filtParams("sg", r.chans.P.amount).win === 21 &&
     filtParams("hampel", r.chans.P.areas[0].amount).win === 41,
     "a chart's own filter and its areas are rescaled too");
  ok(r.scale === 2 && filtRescale(r) === r, "and a rescaled spec is left alone");
  ok(filtRescale({ kind: "sg", amount: 1 }).amount === 1, "a filter that was on stays on");
}

console.log(failed ? `${failed} FAILED` : "filters: all assertions passed");
process.exit(failed ? 1 : 0);
