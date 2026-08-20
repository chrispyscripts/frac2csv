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

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
