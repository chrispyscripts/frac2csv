// A stage whose clock runs backwards, and the correction for it.
//
//   node tests/test_time_guard.js
//
// Carmine: mislabelled times happen more often than they should. They are
// invisible one stage at a time and obvious across a well — 00495 has 66
// stages and exactly one, 3B, dated 2023-11-02 04:51, which is before stage 1
// begins. This is the rule that finds them.
const fs = require("fs");
const path = require("path");
const SRC = path.join(__dirname, "..", "lab", "public", "index.html");
const src = fs.readFileSync(SRC, "utf8");
function lift(name) {
  const at = src.indexOf("function " + name + "(");
  if (at < 0) throw new Error(`${name} is gone from index.html`);
  let d = 0;
  for (let i = src.indexOf("{", at); i < src.length; i++) {
    if (src[i] === "{") d++; else if (src[i] === "}" && --d === 0) return src.slice(at, i + 1);
  }
}
// no corrections stored in this harness
const timeFixGet = () => null;
eval(lift("stageStartMs"));
eval(lift("stageEndMs"));
eval(lift("stageTimeIssues"));

let pass = 0, fail = 0;
const is = (got, want, what) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? pass++ : fail++;
  console.log(`${ok ? "  ok  " : "  FAIL"} ${what}`);
  if (!ok) console.log(`        got ${JSON.stringify(got)}  want ${JSON.stringify(want)}`);
};
// a stage of `mins` minutes at 1 s/sample
const st = (stage, date, start_time, mins = 60) =>
  ({ meta: { stage, date, start_time }, n: mins * 60, sample_sec: 1 });
const flagged = a => stageTimeIssues(a).map(x => String(x.st.meta.stage));

console.log("00495 — 3B is dated two days before the well starts");
is(flagged([st("1", "2023-11-02", "10:39:59"), st("2", "2023-11-03", "03:41:00"),
            st("3", "2023-11-03", "17:35:59"), st("HRF 3A", "2023-11-04", "03:29:59"),
            st("3B", "2023-11-02", "04:51:59"), st("4", "2023-11-04", "20:17:59")]),
   ["3B"], "one stage flagged, and it is the right one");

console.log("\nthe same well with 3B corrected");
is(flagged([st("1", "2023-11-02", "10:39:59"), st("2", "2023-11-03", "03:41:00"),
            st("3", "2023-11-03", "17:35:59"), st("HRF 3A", "2023-11-04", "03:29:59"),
            st("3B", "2023-11-04", "11:51:59"), st("4", "2023-11-04", "20:17:59")]),
   [], "nothing flagged");

console.log("\nwhat must NOT be flagged");
is(flagged([st("1", "2024-05-26", "22:00:00", 30),
            st("2", "2024-05-27", "08:00:00", 30)]),
   [], "a long wait between stages is the ordinary case, not a fault");
is(flagged([st("1", "2024-05-26", "22:00:00", 30),
            st("2", "2024-05-26", "22:30:00", 30)]),
   [], "back to back, the next starting exactly as this one ends");
is(flagged([st("1", "", ""), st("2", "2024-05-27", "08:00:00")]),
   [], "a stage with no printed clock is skipped, not guessed at");
is(flagged([st("1", "2024-05-26", "22:00:00")]), [], "one stage");
is(flagged([]), [], "no stages");

console.log("\noverlap IS a fault");
is(flagged([st("1", "2024-05-26", "22:00:00", 60),
            st("2", "2024-05-26", "22:30:00", 60)]),
   ["2"], "the next stage starts while this one is still pumping");

console.log("\nmore than one bad clock, each reported");
is(flagged([st("1", "2024-05-26", "10:00:00", 30),
            st("2", "2024-05-25", "10:00:00", 30),
            st("3", "2024-05-27", "10:00:00", 30),
            st("4", "2024-05-24", "10:00:00", 30)]),
   ["2", "4"], "both");

console.log("\nan undated stage does not break the chain either side of it");
is(flagged([st("1", "2024-05-26", "10:00:00", 30), st("2", "", ""),
            st("3", "2024-05-26", "09:00:00", 30)]),
   ["3"], "3 is still measured against 1");

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
