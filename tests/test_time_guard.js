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
// the thresholds the guard uses, lifted so the test cannot drift from them
const OVERLAP_FRAC = parseFloat(src.match(/const OVERLAP_FRAC = ([\d.]+)/)[1]);
const OVERLAP_FLOOR_MS = eval(src.match(/const OVERLAP_FLOOR_MS = ([^;]+);/)[1]);
eval(lift("stageHasClock"));
eval(lift("stageStartMs"));
eval(lift("stageEndMs"));
eval(lift("overlapWorthFlagging"));
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


console.log("\n00540 — one stage drawn as TWO plots is still one stage (#589)");
// STEP prints a Surface and a Chemical plot of the same stage on one page, and
// serialize() sends one entry per CHART. The pair starts seconds apart, so
// comparing a stage against its own other plot flagged all 51 stages of a well
// that runs perfectly in order. Carmine caught it: "they appear to be
// sequencing properly."
const pair = (stage, date, t1, t2, mins = 120) =>
  [st(stage, date, t1, mins), st(stage, date, t2, mins)];
is(flagged([...pair("1", "2023-03-12", "17:20:04", "17:19:58"),
            ...pair("2", "2023-03-13", "01:31:29", "01:31:30"),
            ...pair("3", "2023-03-13", "10:24:14", "10:24:17")]),
   [], "51-stage well: no plot is compared against its own twin");
// and the guard still bites when the NEXT stage really does overlap
is(flagged([...pair("1", "2023-03-12", "17:20:04", "17:19:58"),
            ...pair("2", "2023-03-12", "18:00:00", "18:00:02")]),
   ["2"], "a real overlap between two-plot stages is still caught");
// an unnumbered stage must not merge with the next unnumbered one
is(flagged([st("", "2023-03-12", "10:00:00", 60),
            st("", "2023-03-12", "10:30:00", 60)]),
   [""], "blank stage names are not treated as one stage");

// ---- no clock read is not a clock that is WRONG (#768) --------------------
//
// 00009 (BJ) has 38 charts; 23 carry a clock and 15 do not. A chart with no
// time read is written 00:00:00 — the reader's own default, and what
// "no time" means everywhere else in the pipeline — so all fifteen landed on
// one instant and thirteen were reported as starting before the stage before
// them finished. Carmine: "lots of time errors that appear to be false
// flags? everything looks correct in fracview". They were all false: nothing
// was wrong with the clock, there was no clock.
console.log("\na stage with no clock read is not judged against its neighbours");
{
  const S = (stage, t, mins, clock) => ({
    meta: { stage, date: "2019-03-01", start_time: t, clock_chart: !!clock },
    n: mins * 60, sample_sec: 1 });

  const clockless = [];
  for (let i = 24; i <= 38; i++) clockless.push(S(String(i), "00:00:00", 115));
  is(stageTimeIssues(clockless).length, 0,
     "fifteen clockless charts raise nothing (thirteen before)");

  // ...but a chart that CLOCKED ITSELF at midnight is a real reading
  is(stageTimeIssues([S("1", "00:00:00", 120, true),
                      S("2", "00:30:00", 120, true)]).length, 1,
     "a real midnight start is still judged");

  is(stageHasClock(S("1", "00:00:00", 60)), false, "bare midnight: no clock");
  is(stageHasClock(S("1", "00:00:00", 60, true)), true,
     "midnight on a self-clocking chart IS a clock");
  is(stageHasClock(S("1", "08:37:00", 60)), true, "any other time is a clock");
  is(stageHasClock(S("1", "", 60)), false, "and blank is not");

  // the guard still works on a well that has clocks
  is(stageTimeIssues([S("1", "08:00:00", 60), S("2", "09:05:00", 60)]).length, 0,
     "a clean well is still clean");
  is(stageTimeIssues([S("1", "08:00:00", 120), S("2", "08:05:00", 120)]).length, 1,
     "and a real overlap still flags");
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
