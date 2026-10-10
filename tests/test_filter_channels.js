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
for (const k of ["FILT_OFF", "FILT_KINDS", "GATE_GROW", "FILT_SCALE"])
  eval(liftConst(k).replace(/^const /, "var "));
const NAMES = ["filtFinite", "filtMedianOf", "filtHampel", "filtMedian", "filtSavGolCoef",
  "filtSavGol", "filtLoess", "filtOdd", "filtParams", "filtApply", "filtRun", "filtIsOff",
  "filtGate", "gateLevel", "filtGated", "filtRunGated", "filtOwnOn", "filtChanKey",
  "filtChanEntry", "filtMaster", "filtChanSpec", "filtAreaSpec", "filtChanAreas",
  "filtChansNorm", "filtClean", "filtSpecEq", "filtBase", "filtToChannels"];
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

// ---- areas, each through a filter of its own -------------------------------
{
  const r = chan("Slurry Rate", 200), base = r.values.slice();
  const spec = { ...SG, chans: { "Slurry Rate": { use: "master", areas: [
    { a: 20, b: 50, use: "own", kind: "median", amount: 60 },
    { a: 120, b: 150, use: "own", kind: "none", amount: 0 }] } } };
  filtToChannels([r], spec);
  const sg = filtApply(base, "sg", 40), med = filtApply(base, "median", 60);
  ok(same(r.values.slice(0, 20), sg.slice(0, 20)), "outside the areas: the master");
  ok(same(r.values.slice(20, 50), med.slice(20, 50)),
     "the first area: its own median, as it reads over the whole curve");
  ok(same(r.values.slice(50, 120), sg.slice(50, 120)), "between them: the master again");
  ok(same(r.values.slice(120, 150), base.slice(120, 150)), "the 'None' area: as read");
  const st = r.__filtAreas;
  ok(st.length === 2 && st[0].n === 30 && st[0].changed > 0 && st[1].changed === 0,
     "each area says how many samples it changed");
  ok(r.__filtStats.changed > 0 && r.__filtStats.maxd > 0, "and so does the chart");
}
{
  // where two areas overlap, the later one wins
  const r = chan("Slurry Rate", 120), base = r.values.slice();
  filtToChannels([r], { ...FILT_OFF, chans: { "Slurry Rate": { use: "master", areas: [
    { a: 10, b: 60, use: "own", kind: "sg", amount: 50 },
    { a: 40, b: 80, use: "own", kind: "none", amount: 0 }] } } });
  ok(same(r.values.slice(40, 80), base.slice(40, 80)), "the later area wins the overlap");
  ok(same(r.values.slice(10, 40), filtApply(base, "sg", 50).slice(10, 40)),
     "the earlier one keeps the rest of its stretch");
}

// ---- a v1.11.44 setting keeps its meaning ----------------------------------
// One stretch read through the chart's filter, the rest of the chart as read.
{
  const r = chan("Slurry Rate", 200), base = r.values.slice();
  filtToChannels([r], { ...SG, chans: { "Slurry Rate": { use: "master", range: [40, 90] } } });
  const full = filtApply(base, "sg", 40);
  ok(same(r.values.slice(0, 40), base.slice(0, 40)), "v1.11.44 range: before it, as read");
  ok(same(r.values.slice(90), base.slice(90)), "v1.11.44 range: after it, as read");
  ok(same(r.values.slice(40, 90), full.slice(40, 90)), "v1.11.44 range: inside it, the filter");
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
  ok(filtIsOff({ ...FILT_OFF, chans: { "Surface Pressure": { use: "master",
       areas: [{ a: 0, b: 9, use: "master" }] } } }),
     "an area following an off master filters nothing");
  ok(!filtIsOff({ ...FILT_OFF, chans: { "Surface Pressure": { use: "master",
       areas: [{ a: 0, b: 9, use: "own", kind: "hampel", amount: 40 }] } } }),
     "an area with a filter of its own is on with the master off");
}

// ---- a channel set to no filter of its own --------------------------------
{
  const p = chan("Surface Pressure", 120), base = p.values.slice();
  filtToChannels([p], { ...SG, chans: { "Surface Pressure": { use: "own", kind: "none", amount: 0 } } });
  ok(same(p.values, base), "own 'None' turns the master off for that channel alone");
}

// ---- comparing, cleaning, and the wider scopes ----------------------------
{
  const A = { use: "master", areas: [{ a: 1, b: 5, use: "master" }] };
  const a = { ...SG, chans: { B: { use: "own", kind: "sg", amount: 20 }, A } };
  const b = { ...SG, chans: { A, B: { use: "own", kind: "sg", amount: 20, areas: [] } } };
  ok(filtSpecEq(a, b), "the same channels in another order are the same spec");
  ok(!filtSpecEq(a, SG), "channel settings make a different spec");
  ok(filtSpecEq({ ...SG, chans: { A: { use: "master" } } }, SG),
     "an entry that only says 'follow the master' changes nothing");
  const wide = filtChansNorm(a.chans, false);
  ok(!wide.A && wide.B && wide.B.areas.length === 0,
     "applied to the well, areas are dropped and an entry left saying nothing goes");
  const c = filtClean({ kind: "bogus", amount: 250, chans: { X: { use: "own", kind: "evil",
    amount: -4, areas: [{ a: 3.2, b: 9.7, use: "own", kind: "worse", amount: 400 },
                        { a: 9, b: 2 }] } } });
  ok(c.kind === "none" && c.amount === 100, "an unknown kind is off and amounts are held to 0..100");
  ok(c.chans.X.kind === "none" && c.chans.X.amount === 0, "so are a channel's");
  ok(c.chans.X.areas.length === 1 && c.chans.X.areas[0].a === 3 && c.chans.X.areas[0].b === 10
     && c.chans.X.areas[0].kind === "none" && c.chans.X.areas[0].amount === 100,
     "and an area's, whole samples, and one that runs backwards is dropped");
}

console.log(failed ? `${failed} FAILED` : "filter channels: all assertions passed");
process.exit(failed ? 1 : 0);
