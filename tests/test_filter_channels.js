// Per-channel filters from the stacked window: each curve follows the master
// or takes a filter of its own, and either can be held to one stretch.
//
//   node tests/test_filter_channels.js
//
// Asked for by Carmine (2026-10-09): "add the filter to each individual data
// set in stacked view, and allow for the filter to only be applied to a
// certain area". The export reads the channels filtToChannels writes, so
// these are the numbers that reach the CSV.
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
function liftConst(name) {
  const m = new RegExp("const " + name + " = [\\s\\S]*?;\\n").exec(src);
  if (!m) throw new Error(`${name} is gone from index.html`);
  return m[0];
}
for (const k of ["FILT_OFF", "FILT_KINDS", "GATE_GROW"])
  eval(liftConst(k).replace(/^const /, "var "));
const NAMES = ["filtFinite", "filtMedianOf", "filtHampel", "filtMedian", "filtSavGolCoef",
  "filtSavGol", "filtLoess", "filtOdd", "filtParams", "filtApply", "filtRun", "filtIsOff",
  "filtGate", "gateLevel", "filtGated", "filtRunGated", "filtOwnOn", "filtChanKey",
  "filtChanEntry", "filtChanSpec", "filtChanRange", "filtChansNorm", "filtClean",
  "filtSpecEq", "filtBase", "filtToChannels"];
eval(NAMES.map(lift).join("\n"));
function filtGateSpan() { return 100; }

let failed = 0;
const ok = (c, what) => { if (!c) { console.error("FAIL " + what); failed++; } };
const same = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);

// a noisy staircase, so every filter changes something
const noisy = n => Array.from({ length: n }, (_, i) =>
  (i < n / 2 ? 20 : 60) + ((i * 37) % 7) - 3);
const chan = (key, n) => ({ key, values: noisy(n) });
const SG = { ...FILT_OFF, kind: "sg", amount: 40 };

// ---- a channel with its own filter ----------------------------------------
{
  const p = chan("Surface Pressure", 200), r = chan("Slurry Rate", 200);
  const base = p.values.slice(), rbase = r.values.slice();
  const spec = { ...SG, chans: { "Surface Pressure": { use: "own", kind: "hampel", amount: 50 } } };
  filtToChannels([p, r], spec);
  ok(same(p.values, filtApply(base, "hampel", 50)), "the pressure takes its own Hampel");
  ok(same(r.values, filtApply(rbase, "sg", 40)), "the rate still follows the master SG");
  ok(p.__filt && p.__filt.kind === "hampel", "the pressure says which filter it is read through");
}

// ---- held to one stretch ---------------------------------------------------
{
  const r = chan("Slurry Rate", 200), base = r.values.slice();
  const spec = { ...SG, chans: { "Slurry Rate": { use: "master", range: [40, 90] } } };
  filtToChannels([r], spec);
  const full = filtApply(base, "sg", 40);
  ok(same(r.values.slice(0, 40), base.slice(0, 40)), "before the stretch: as read");
  ok(same(r.values.slice(90), base.slice(90)), "after the stretch: as read");
  ok(same(r.values.slice(40, 90), full.slice(40, 90)),
     "inside it: the filter as it reads over the whole curve, edges included");
  ok(r.__filtRange && r.__filtRange[0] === 40 && r.__filtRange[1] === 90, "the stretch is reported");
}

// ---- the master off, one channel on ---------------------------------------
{
  const p = chan("Surface Pressure", 120), r = chan("Slurry Rate", 120);
  const rbase = r.values.slice();
  const spec = { ...FILT_OFF, chans: { "Surface Pressure": { use: "own", kind: "sg", amount: 60 } } };
  ok(!filtIsOff(spec), "a channel's own filter keeps the spec on with the master off");
  filtToChannels([p, r], spec);
  ok(same(r.values, rbase) && !r.__filt, "the other channel is untouched");
  ok(!!p.__filt, "the channel with its own filter is filtered");
  ok(filtIsOff({ ...FILT_OFF, chans: { "Surface Pressure": { use: "master", range: [0, 9] } } }),
     "a stretch under an off master filters nothing");
}

// ---- a channel set to no filter of its own --------------------------------
{
  const p = chan("Surface Pressure", 120), base = p.values.slice();
  filtToChannels([p], { ...SG, chans: { "Surface Pressure": { use: "own", kind: "none", amount: 0 } } });
  ok(same(p.values, base), "own 'None' turns the master off for that channel alone");
}

// ---- comparing, cleaning, and the wider scopes ----------------------------
{
  const a = { ...SG, chans: { B: { use: "own", kind: "sg", amount: 20 }, A: { use: "master", range: [1, 5] } } };
  const b = { ...SG, chans: { A: { use: "master", range: [1, 5] }, B: { use: "own", kind: "sg", amount: 20 } } };
  ok(filtSpecEq(a, b), "the same channels in another order are the same spec");
  ok(!filtSpecEq(a, SG), "channel settings make a different spec");
  ok(filtSpecEq({ ...SG, chans: { A: { use: "master" } } }, SG),
     "an entry that only says 'follow the master' changes nothing");
  const noRange = filtChansNorm(a.chans, false);
  ok(!noRange.A && noRange.B && noRange.B.range === null,
     "applied to the well, stretches are dropped and an entry left saying nothing goes");
  const c = filtClean({ kind: "bogus", amount: 250, chans: { X: { use: "own", kind: "evil", amount: -4 } } });
  ok(c.kind === "none" && c.amount === 100, "an unknown kind is off and amounts are held to 0..100");
  ok(c.chans.X.kind === "none" && c.chans.X.amount === 0, "so are a channel's");
}

console.log(failed ? `${failed} FAILED` : "filter channels: all assertions passed");
process.exit(failed ? 1 : 0);
