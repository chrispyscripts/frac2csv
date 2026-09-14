// Per-dataset y scaling: the stacked view's fit-to-data, and FracView's
// per-channel stretch.
//
//   node tests/test_chart_scale.js
//
// The complaint behind both: a chart drawn against the axis its SHEET prints
// is drawn against the same axis on every stage of the file. A conc axis of
// 0..1000 is 0..1000 whether the stage peaked at 950 or at 40, so the small
// stage spends its whole row in the bottom twentieth and its shape cannot be
// read at all (Carmine, 2026-09-13).
const fs = require("fs");
const path = require("path");
const P = f => path.join(__dirname, "..", "lab", "public", f);
const stacked = fs.readFileSync(P("stacked.html"), "utf8");
const fv = fs.readFileSync(P("fracview.html"), "utf8");

function lift(src, name, where) {
  const at = src.indexOf("function " + name + "(");
  if (at < 0) throw new Error(`${name} is gone from ${where}`);
  let d = 0;
  for (let i = src.indexOf("{", at); i < src.length; i++) {
    if (src[i] === "{") d++; else if (src[i] === "}" && --d === 0) return src.slice(at, i + 1);
  }
}
// Declarations here are comma-joined (`const GAIN_MIN = .., GAIN_MAX = ..`),
// so match the binding rather than the statement.
function konst(src, name, where) {
  const m = src.match(new RegExp("\\b" + name + "\\s*=\\s*([\\d.]+)"));
  if (!m) throw new Error(`${name} is gone from ${where}`);
  return parseFloat(m[1]);
}

eval(lift(stacked, "niceCeil", "stacked.html"));
eval(lift(stacked, "dataScale", "stacked.html"));

const GAIN_MIN = konst(fv, "GAIN_MIN", "fracview.html");
const GAIN_MAX = konst(fv, "GAIN_MAX", "fracview.html");
const SLIDER_N = konst(fv, "SLIDER_N", "fracview.html");
// Lifted, not re-implemented: a copy here would let the test pass while the
// window did something else.
eval(lift(fv, "gainToPos", "fracview.html"));
eval(lift(fv, "posToGain", "fracview.html"));

let pass = 0, fail = 0;
const is = (got, want, what) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? pass++ : fail++;
  console.log(`${ok ? "  ok  " : "  FAIL"} ${what}`);
  if (!ok) console.log(`        got ${JSON.stringify(got)}  want ${JSON.stringify(want)}`);
};
const ok = (cond, what) => is(!!cond, true, what);

// ---- the axis tops out at a number worth printing ---------------------
is(niceCeil(0), 1, "nothing to scale gives a usable axis, not zero");
is(niceCeil(352.5), 500, "352.5 tops out at 500");
is(niceCeil(14.26), 20, "14.26 tops out at 20");
is(niceCeil(1), 1, "an exact decade is left alone");

// ---- fit to data ------------------------------------------------------
is(dataScale({ dataLo: 0, dataHi: 352.5 }), { lo: 0, hi: 500 },
   "a stage peaking at 352 is drawn against 500, not the sheet's 1000");
is(dataScale({ dataLo: null, dataHi: null }), null,
   "a channel with no finite sample has no data scale — fall back to printed");
is(dataScale({ dataLo: NaN, dataHi: 5 }), null, "NaN is not a range");

// A flat channel must NOT be stretched to fill the row. 14.0 +/- 0.05 drawn
// min-to-max is a mountain range made of noise, which is the exact misreading
// the flat-run shading exists to catch.
const flat = dataScale({ dataLo: 13.95, dataHi: 14.05 });
is(flat.lo, 0, "a flat channel is still anchored at zero");
ok(flat.hi >= 14.05, "a flat channel's top clears its data");
ok((14.05 - 13.95) / (flat.hi - flat.lo) < 0.05,
   "a flat channel stays visibly flat instead of filling its row with noise");

// Below zero only when the data actually goes there.
const neg = dataScale({ dataLo: -12, dataHi: 40 });
ok(neg.lo <= -12, "a channel that goes negative keeps its negative room");
ok(neg.hi >= 40, "and still clears its top");

// ---- the stretch slider ----------------------------------------------
ok(GAIN_MIN * GAIN_MAX === 1 || Math.abs(GAIN_MIN * GAIN_MAX - 1) < 1e-9,
   "the stretch range is symmetric about 1, so centred means untouched");
is(gainToPos(1), SLIDER_N / 2, "1x sits exactly halfway along the travel");
is(posToGain(gainToPos(1)), 1, "1x survives a round trip");
is(posToGain(0), GAIN_MIN, "the bottom of the travel is the minimum");
is(posToGain(SLIDER_N), GAIN_MAX, "the top of the travel is the maximum");
ok(posToGain(SLIDER_N / 2 + 1) === 1 && posToGain(SLIDER_N / 2 - 1) === 1,
   "there is a detent at 1x, so it can be found without eyeballing it");

// Geometric travel: equal steps are equal RATIOS, not equal amounts. A linear
// 0.125..8 slider spends seven eighths of itself above 1.
const a = posToGain(SLIDER_N * 0.25), b = posToGain(SLIDER_N * 0.75);
ok(Math.abs(a * b - 1) < 0.02,
   "a quarter down is the reciprocal of a quarter up");

// ---- the stretch is a way of LOOKING, not an edit ---------------------
ok(/f2c\.fvGain/.test(fv), "the stretch is written down like the channel switches");
ok(!/chanGain/.test(fs.readFileSync(P("index.html"), "utf8")),
   "the Lab knows nothing about it — it changes no value and no export");

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
