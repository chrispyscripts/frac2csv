// The jump gate: filter only where the trace jumps.
//
//   node tests/test_filter_gate.js
//
// Carmine: the spikes worth removing are drastic, and a filter strong enough
// to take them also files off the fine detail where no filter was needed. A
// gated filter keeps every raw sample and takes the filtered value only where
// the raw trace leaves the filtered line by more than a share of its axis.
const fs = require("fs");
const path = require("path");
const src = fs.readFileSync(path.join(__dirname, "..", "lab", "public", "index.html"), "utf8");

function lift(name) {
  const at = src.indexOf("function " + name + "(");
  if (at < 0) throw new Error(`${name} is gone from index.html`);
  let d = 0;
  for (let i = src.indexOf("{", at); i < src.length; i++) {
    if (src[i] === "{") d++; else if (src[i] === "}" && --d === 0) return src.slice(at, i + 1);
  }
  throw new Error(`${name} is unterminated`);
}
const constLine = name => {
  const m = src.match(new RegExp("const " + name + " = [^;]+;"));
  if (!m) throw new Error(`${name} is gone from index.html`);
  return m[0];
};
eval([constLine("GATE_GROW"), ...["filtFinite", "filtMedianOf", "filtHampel", "filtMedian",
  "filtSavGolCoef", "filtSavGol", "filtLoess", "filtOdd", "filtParams", "filtApply",
  "filtRun", "filtIsOff", "gateLevel", "filtGate", "filtGated", "filtRunGated"].map(lift)].join("\n"));

let failed = 0, passed = 0;
function ok(c, what) { if (c) passed++; else { failed++; console.error("FAIL " + what); } }

// A pressure trace on a 0-100 axis: steady fine wobble (the detail to keep)
// with two drastic tracer spikes.
function trace() {
  const v = [];
  for (let i = 0; i < 400; i++) v.push(60 + 0.6 * Math.sin(i / 3) + 0.3 * Math.sin(i * 1.7));
  // a spike with shoulders: up 5, 14, 38, 14, 5
  [5, 14, 38, 14, 5].forEach((d, k) => { v[100 + k] += d; });
  // a one-sample plunge
  v[260] = 4;
  return v;
}
const SPEC = { kind: "both", amount: 60, gate: true, gatePct: 10 };

// ---- the spikes go, whole, shoulders and all --------------------------------
{
  const raw = trace();
  const g = filtRunGated(raw, SPEC, 100);
  ok(g.runs && g.runs.length === 2, `two gated stretches (${JSON.stringify(g.runs)})`);
  ok(g.runs[0][0] <= 100 && g.runs[0][1] >= 105, "the first spike's shoulders go with its tip");
  ok(Math.max(...g.values.slice(98, 108)) < 63, "nothing of the first spike is left standing");
  ok(g.values[260] > 55, "the plunge is filled from the line, not left at 4");
}

// ---- and everything else is exactly as read --------------------------------
{
  const raw = trace();
  const g = filtRunGated(raw, SPEC, 100);
  const inRun = i => g.runs.some(([a, b]) => i >= a && i < b);
  let same = 0, outside = 0;
  for (let i = 0; i < raw.length; i++) if (!inRun(i)) { outside++; if (g.values[i] === raw[i]) same++; }
  ok(same === outside, `every sample outside the gated stretches is the raw one (${same}/${outside})`);
  // the ungated filter, by contrast, moves the fine wobble
  const plain = filtRun(raw, SPEC);
  let moved = 0;
  for (let i = 150; i < 250; i++) if (Math.abs(plain[i] - raw[i]) > 0.05) moved++;
  ok(moved > 20, `the ungated filter does file the detail off (${moved} of 100 moved)`);
}

// ---- a real step is data, and the gate leaves it ----------------------------
{
  const v = [];
  for (let i = 0; i < 200; i++) v.push(i < 100 ? 70 : 20);     // pump shutdown
  const g = filtRunGated(v, SPEC, 100);
  ok(g.runs.length === 0, `a clean step is not gated (${JSON.stringify(g.runs)})`);
  ok(g.values.every((x, i) => x === v[i]), "the step comes back exactly as read");
}

// ---- a spike on top of a running step is still a spike ----------------------
{
  const v = [];
  for (let i = 0; i < 200; i++) v.push(i < 100 ? 70 : 20);
  v[150] = 95;                                   // after the step, a spike
  const g = filtRunGated(v, SPEC, 100);
  ok(g.runs.length === 1 && g.runs[0][0] <= 150 && g.runs[0][1] > 150,
     `the spike after the step is gated and the step is not (${JSON.stringify(g.runs)})`);
  ok(g.values[99] === 70 && g.values[100] === 20, "the step's two sides are as read");
}

// ---- off is off ------------------------------------------------------------
{
  const raw = trace();
  const noGate = filtRunGated(raw, { ...SPEC, gate: false }, 100);
  const plain = filtRun(raw, SPEC);
  ok(noGate.runs === null && noGate.values.every((x, i) => x === plain[i]),
     "with the box unticked the filter runs as it always did");
  ok(!filtGated({ kind: "none", amount: 0, gate: true, gatePct: 10 }),
     "a gate with no filter under it does nothing");
  const none = filtRunGated(raw, { kind: "none", amount: 0, gate: true, gatePct: 10 }, 100);
  ok(none.values.every((x, i) => x === raw[i]), "and leaves the curve as read");
}

// ---- the threshold is a share of the axis ----------------------------------
{
  const raw = trace();
  const tight = filtRunGated(raw, { ...SPEC, gatePct: 50 }, 100);   // 50 units
  ok(tight.runs.length === 1, `at 50% of the axis only the 56-unit plunge qualifies (${tight.runs.length})`);
  const big = filtRunGated(raw.map(x => x * 10), SPEC, 1000);       // same trace, x10 axis
  ok(big.runs.length === 2, "the same trace on a ten-times axis gates the same places");
}

// ---- a gap stays a gap; the input is never touched -------------------------
{
  const raw = trace();
  raw[50] = null; raw[103] = null;
  const before = raw.slice();
  const g = filtRunGated(raw, SPEC, 100);
  ok(g.values[50] === null && g.values[103] === null, "null samples stay null, inside a gated stretch too");
  ok(raw.every((x, i) => x === before[i]), "the raw trace is not mutated");
}

// ---- filtGate on its own ---------------------------------------------------
{
  const raw = [0, 0, 0, 5, 12, 30, 12, 5, 0, 0, 0];
  const filt = new Array(raw.length).fill(0);
  const g = filtGate(raw, filt, 10);
  ok(JSON.stringify(g.runs) === "[[3,8]]", `grown from the tip to the shoulders (${JSON.stringify(g.runs)})`);
  ok(g.values.every(x => x === 0), "and all of it replaced");
  ok(filtGate(raw, filt, 0).runs.length === 0, "a zero threshold gates nothing");
}

console.log(`${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
