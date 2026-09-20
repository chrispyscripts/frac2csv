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
eval(lift("stageItems"));

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

const chart = (stage, page, over) => ({
  kind: "image", meta: { stage, well: "00218" }, source: "trican_charts",
  page, n: 5760, sample_sec: 1,
  channels: [{ key: "press", label: "Tr Press", values: [] }],
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

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
