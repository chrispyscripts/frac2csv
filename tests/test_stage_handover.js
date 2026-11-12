// The handed-over tail has to survive the trip into the stage list.
//
//   node tests/test_stage_handover.js
//
// `stageItems` builds the objects the UI actually opens. It names every field
// it keeps, so a field left out of that literal is a field the chart never
// sees, however faithfully the server sends it — and nothing downstream
// errors, the tail just silently is not there.
//
// That is what happened to `handover`. It drew correctly when a stage was
// handed straight to setGraph, which is how it was tested, and never once on
// the path every user takes: drop, Extract, click a stage. Three releases
// went out saying the feature worked (#665, #668, #669, #679, #680, #681);
// on 00218 all 29 stages came back tail 0, band false, painted 0.
//
// So: lift stageItems out of index.html, run the server's own payload shape
// through it, and insist the tail comes out the other side.
const fs = require("fs");
const path = require("path");

const SRC = path.join(__dirname, "..", "lab", "public", "index.html");
const src = fs.readFileSync(SRC, "utf8");

function lift(name) {
  const at = src.indexOf("function " + name + "(");
  if (at < 0) throw new Error(`${name} is gone from index.html`);
  let depth = 0;
  for (let i = src.indexOf("{", at); i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}" && --depth === 0) return src.slice(at, i + 1);
  }
  throw new Error(`${name} is unbalanced`);
}
const stageNum = s => { const m = String(s).match(/\d+/); return m ? +m[0] : 1e9; };
// stageItems re-applies the "export the whole chart" setting as it builds the
// list — the single place every list in the app is built, so the setting
// cannot miss one. That pulls in the keepTail helpers and the store they read.
let keepTailStore = {};
let current = null;
function fileScope() { return (current && current.entry && current.entry.name) || ""; }
eval([lift("keepTailApply"), lift("keepTailApplyAll"), lift("keepTailOn"),
      lift("chartPlace"), lift("shiftChannel"), lift("stageTail"),
      lift("stageItems")].join("\n"));
const keepTailKey = meta => `${fileScope()}::${(meta && meta.stage) || "?"}`;

let pass = 0, fail = 0;
function is(got, want, what) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? pass++ : fail++;
  console.log(`${ok ? "  ok  " : "  FAIL"} ${what}`);
  if (!ok) console.log(`        got ${JSON.stringify(got)}  want ${JSON.stringify(want)}`);
}

// localapp._handover_payload's shape, not an invented one: {to, n, channels}.
const tail = (to, n) => ({ to, n, channels: [
  { key: "press", label: "Tr Press", values: Array(n).fill(40) },
  { key: "rate",  label: "Slurry Rate", values: Array(n).fill(8) }] });

// A chart's values run its full length: the tail is laid in where they end.
const chart = (stage, page, over) => ({
  kind: "image", meta: { stage, well: "00218" }, source: "trican_charts",
  page, n: 5760, sample_sec: 1,
  channels: [{ key: "press", label: "Tr Press", values: Array(5760).fill(30) }],
  handover: over || null });

console.log("the tail survives stageItems");

let items = stageItems([chart("1", 3, tail("2", 659)), chart("2", 5, tail("3", 660))]);
is(items.map(i => (i.handover || {}).n), [659, 660], "one chart per stage");
is((items[0].handover || {}).to, "2", "and it still names who it went to");
is(((items[0].handover || {}).channels || []).length, 2, "with its channels intact");

// A stage can be several charts — surface and bottom hole, or a continuation.
// Only the one that runs on hands anything over, so take whichever has it
// rather than grp[0], which is how this reads on a Calfrac pair.
items = stageItems([chart("1", 3, null), chart("1", 4, tail("2", 120))]);
is(items.length, 1, "two charts, one stage");
is((items[0].handover || {}).n, 120, "the tail comes off whichever chart carries it");

items = stageItems([chart("1", 3, tail("2", 200)), chart("1", 4, null)]);
is((items[0].handover || {}).n, 200, "in either order");

// The last stage of a file hands to nobody. null, not undefined: the drawing
// code tests it, and a missing key would read the same but says something else.
items = stageItems([chart("1", 3, tail("2", 90)), chart("2", 5, null)]);
is(items[1].handover, null, "a stage that hands over nothing says so");
is("handover" in items[1], true, "and says it explicitly, not by omission");

// Nothing else about the item may change on the way through.
items = stageItems([chart("7", 29, tail("8", 300))]);
is([items[0].key, items[0].seq, items[0].n, items[0].pages],
   ["7", 1, 5760, [29]], "the rest of the item is unchanged");

console.log("\nthe drawing side still reads what stageItems hands it");
// A one-line guard on the contract: the fields the chart reads off the tail
// are the fields localapp ships. If either side is renamed this fails here
// rather than in a screenshot three releases later.
for (const f of ["handover.channels", "handover.n"])
  is(src.includes(f), true, `index.html reads ${f}`);
const py = fs.readFileSync(path.join(__dirname, "..", "localapp.py"), "utf8");
for (const f of ['"to"', '"n"', '"channels"'])
  is(py.includes(f), true, `localapp ships ${f}`);


// ---- "export the whole chart": the tail spliced back on --------------------
//
// The seconds export counts its rows from item.n and reads each channel by
// index, so values and n have to move together. A longer values array alone
// would sit in memory and never reach a CSV.
console.log("\nexporting the whole chart");
{
  current = { entry: { name: "w.pdf" } };
  keepTailStore = {};
  const mk = () => stageItems([chart("1", 3, tail("2", 659))])[0];

  let it = mk();
  is(it.n, 5760, "off by default — the chart stops at the handover");
  is(it.channels[0].values.length, 5760, "and the values stop there too");

  keepTailStore["w.pdf::1"] = true;
  it = mk();
  is(it.n, 5760 + 659, "on: item.n grows by the tail, so the CSV gets the rows");
  is(it.channels[0].values.length, 5760 + 659, "and the channel carries the tail");
  is([it.channels[0].values[5759], it.channels[0].values[5760]], [30, 40],
     "laid in right where the chart ends");

  // a round trip, not a tail on a tail
  keepTailApply(it, false);
  is(it.n, 5760, "off again restores n");
  is(it.channels[0].values.length, 5760, "and the values");
  keepTailApply(it, true); keepTailApply(it, true);
  is(it.n, 5760 + 659, "twice on is still one tail");
  is(it.channels[0].values.length, 5760 + 659, "on the values as well");
  keepTailStore = {};
  current = null;
}


// ---- a stage's charts on one timeline (#846, #847, #849, #850) --------------
//
// 00270: STEP prints each stage as a Treatment page (treatment plot +
// chemical plot) and an Offset Analysis page, each with its own clock.
console.log("\ncharts placed by their own clock");
{
  const mk = (stage, page, start, n, keys, over, src) => ({
    kind: "image", source: src || "STEP surface chart (raster)", page, n, sample_sec: 1,
    meta: { stage, date: "2017-06-24", start_time: start },
    channels: keys.map(k => ({ key: k, label: k, values: Array(n).fill(1),
                               deducedRuns: [[0, 10]] })),
    handover: over || null });
  const tailOf = (to, n, keys) => ({ to, n, channels: keys.map(k => ({
    key: k, label: k, values: Array(n).fill(2) })) });

  // stage 17: treatment 13:39:53 cut at 2400 s with 608 s handed to 18;
  // chemical plot on the same page runs to 14:30; offset page opens 13:45:58
  const items = stageItems([
    mk("17", 50, "13:39:53", 2400, ["Tr Press", "Slurry Rate"], tailOf("18", 608, ["Tr Press", "Slurry Rate"])),
    mk("17", 50, "13:39:52", 3007, ["Combined Clean Rate"], null, "STEP chemical chart (raster)"),
    mk("17", 51, "13:45:58", 2644, ["Tr Press", "G Well"]),
  ]);
  const it = items[0];
  const g = it.channels.find(c => c.key === "G Well");
  is(g.values.slice(364, 367), [null, 1, 1], "the offset page's pens open 6:05 in, where its clock says");
  is(g.deducedRuns, [[365, 375]], "and what the reader deduced moves with them");
  is(it.channels.find(c => c.key === "Combined Clean Rate").values[0], 1,
     "a plot on the first chart's page stays where it was");
  is(it.n, 365 + 2644, "the stage runs to the end of its last chart");
  is(it.handover.channels.map(c => [c.key, c.at]), [["Tr Press", 2400], ["Slurry Rate", 2400]],
     "the treatment's tail starts where the treatment chart ends, not after the longest one");
  is([it.handover.at, it.handover.end, it.handover.to], [2400, 3008, "18"], "and spans its own minutes");

  // stage 1: the offset page's window opens 2 h 45 min before the stage
  const one = stageItems([
    mk("1", 18, "21:20:38", 5670, ["Tr Press"], tailOf("2", 217, ["Tr Press"])),
    mk("1", 19, "18:35:13", 15832, ["Tr Press", "G Well"], tailOf("1", 5907, ["Tr Press", "G Well"])),
  ])[0];
  is(one.n, 15832 - 9925, "an offset page that opened hours early does not stretch the stage (#846)");
  is(one.channels.find(c => c.key === "G Well").values.length, 15832 - 9925,
     "its minutes before the stage began are not this stage's");
  is(one.handover.channels.map(c => c.key), ["Tr Press"],
     "a tail handed to its own stage is not drawn");

  // a clock wholly outside the first chart cannot be this stage's
  const re = stageItems([
    mk("23", 62, "19:45:16", 2269, ["Tr Press"]),
    mk("23", 63, "20:23:28", 2339, ["Tr Press", "G Well"]),
  ])[0];
  is(re.channels.find(c => c.key === "G Well").values[0], 1, "is not followed");
  is(re.n, 2339, "and the stage keeps its length");

  // stage 35: treatment and chemical plot each hand over, from their own ends
  const both = stageItems([
    mk("35", 86, "02:43:51", 1808, ["Tr Press"], tailOf("36", 125, ["Tr Press"])),
    mk("35", 86, "02:38:31", 1794, ["Combined Clean Rate"], tailOf("36", 489, ["Combined Clean Rate"]),
       "STEP chemical chart (raster)"),
  ])[0];
  is(both.handover.channels.map(c => [c.key, c.at]),
     [["Tr Press", 1808], ["Combined Clean Rate", 1794]], "every chart's tail, each from its own end");
  is(both.handover.end, 1794 + 489, "the band reaches the last of them");
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
