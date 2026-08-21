// The Sequence view's fault detector.
//
//   node tests/test_fv_sequence.js
//
// Carmine checks our exports in FracPrep by plotting STAGE against the clock:
// laid out correctly that is one ascending staircase, and a stage whose date
// or time is wrong drops out of the line. This is that rule.
//
// 00495 is why it exists — 66 stages, and exactly one of them, 3B, dated
// 2023-11-02 04:51, before stage 1 begins. Stage by stage it is invisible.
const fs = require("fs");
const path = require("path");
const SRC = path.join(__dirname, "..", "lab", "public", "fracview.html");
const src = fs.readFileSync(SRC, "utf8");
function lift(name) {
  const at = src.indexOf("function " + name + "(");
  if (at < 0) throw new Error(`${name} is gone from fracview.html`);
  let d = 0;
  for (let i = src.indexOf("{", at); i < src.length; i++) {
    if (src[i] === "{") d++; else if (src[i] === "}" && --d === 0) return src.slice(at, i + 1);
  }
}
eval(lift("seqBreaks"));

let pass = 0, fail = 0;
const is = (got, want, what) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? pass++ : fail++;
  console.log(`${ok ? "  ok  " : "  FAIL"} ${what}`);
  if (!ok) console.log(`        got ${JSON.stringify(got)}  want ${JSON.stringify(want)}`);
};
// a stage runs one hour from t
const T = s => Date.parse("2023-11-0" + s);
const stg = (startISO, hours = 1) => ({
  a: Date.parse(startISO),
  hi: Date.parse(startISO) + hours * 3600e3,
});

console.log("00495 — the real stage clocks, 3B two days out");
const real = [
  stg("2023-11-02T10:39:59"), stg("2023-11-03T03:41:00"),
  stg("2023-11-03T17:35:59"), stg("2023-11-04T03:29:59"),
  stg("2023-11-02T04:51:59"),                      // 3B
  stg("2023-11-04T20:17:59"), stg("2023-11-05T09:09:59"),
];
is(seqBreaks(real), [3], "one break, at the step INTO 3B");

console.log("\nthe same well with 3B put right");
const fixed = real.slice();
fixed[4] = stg("2023-11-04T11:51:59");
is(seqBreaks(fixed), [], "no breaks — a single ascending staircase");

console.log("\nboundaries");
is(seqBreaks([]), [], "no stages");
is(seqBreaks([stg("2023-11-02T10:00:00")]), [], "one stage cannot be out of order");
is(seqBreaks([stg("2023-11-02T10:00:00"), stg("2023-11-02T11:00:00")]), [],
   "back to back, next starts exactly as this one ends");
is(seqBreaks([stg("2023-11-02T10:00:00"), stg("2023-11-02T10:30:00")]), [0],
   "an OVERLAP counts: the next stage starts while this one is still pumping");
is(seqBreaks([stg("2023-11-02T10:00:00"), stg("2023-11-02T12:00:00")]), [],
   "a wait between them is not a fault — that is the ordinary case");

console.log("\nmore than one bad clock");
is(seqBreaks([stg("2023-11-02T10:00:00"), stg("2023-11-01T09:00:00"),
              stg("2023-11-02T14:00:00"), stg("2023-11-01T08:00:00")]),
   [0, 2], "each break is reported on its own step");

// ---------------------------------------------------------------------------
// The shape the app ACTUALLY sends.
//
// Everything above feeds seqBreaks in filing order. The Lab does not send
// filing order — it orders the stages by their clock before FracView ever
// sees them, so an out-of-order stage arrives already moved into place and
// the overlap rule finds nothing. 00495 read "the clock is consistent" on the
// well this view was built for.
//
// So each point now carries `seq`, the position the FILING prints, and a step
// DOWN in that number is a fault of its own: the clock put this stage here,
// the sheet numbered it somewhere else.
console.log("\n00495 again, in the order the Lab really sends it");
const sorted = [
  { ...stg("2023-11-02T04:51:59"), seq: 5 },   // 3B — earliest clock, 5th printed
  { ...stg("2023-11-02T10:39:59"), seq: 1 },
  { ...stg("2023-11-03T03:41:00"), seq: 2 },
  { ...stg("2023-11-03T17:35:59"), seq: 3 },
  { ...stg("2023-11-04T03:29:59"), seq: 4 },
  { ...stg("2023-11-04T20:17:59"), seq: 6 },
  { ...stg("2023-11-05T09:09:59"), seq: 7 },
];
is(seqBreaks(sorted), [0], "3B is caught where the overlap rule could not see it");

console.log("\na well whose clock agrees with its numbering");
const clean = [
  { ...stg("2023-11-02T04:00:00"), seq: 1 },
  { ...stg("2023-11-02T10:00:00"), seq: 2 },
  { ...stg("2023-11-03T04:00:00"), seq: 3 },
];
is(seqBreaks(clean), [], "no breaks — ascending clock, ascending numbers");

console.log("\nboth faults at once are still one break each");
const both = [
  { ...stg("2023-11-02T04:00:00", 8), seq: 3 },  // numbered late, and overlaps
  { ...stg("2023-11-02T10:00:00"), seq: 1 },
  { ...stg("2023-11-02T14:00:00"), seq: 2 },
];
is(seqBreaks(both), [0], "the pair is reported once, not twice");

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
