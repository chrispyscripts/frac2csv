// FracView's stage order must be the CLOCK's, not the filing's page order.
//
//   node tests/test_fv_order.js
//
// rawBounds walks w.stages and pushes each t0 in array order, so an
// out-of-order stage does not merely look odd — it makes the bounds
// non-monotonic and the whole band layout incoherent, and it makes fvStarts
// judge a perfectly good clock non-monotonic and fall back to the synthetic
// axis, which is what removes every void from Real Time.
//
// SLB 00011 is the real case: 46 charts whose dates are strictly sequential
// when read by interval, but the filing prints interval 41's chart AFTER
// 45's.
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
eval(lift("fvStageStart"));
eval(lift("fvOrdered"));
eval(lift("fvStarts"));

let pass = 0, fail = 0;
const is = (got, want, what) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? pass++ : fail++;
  console.log(`${ok ? "  ok  " : "  FAIL"} ${what}`);
  if (!ok) console.log(`        got ${JSON.stringify(got)}  want ${JSON.stringify(want)}`);
};
const st = (stage, date, start_time, n = 100) =>
  ({ meta: { stage, date, start_time }, n, sample_sec: 1 });
const stages = a => a.map(x => x.meta.stage);

console.log("SLB 00011: interval 41's chart is printed after 45's");
const slb = [st("43", "2018-08-02", "03:47:34"), st("44", "2018-08-02", "08:19:33"),
             st("45", "2018-08-02", "18:05:06"), st("41", "2018-07-31", "07:20:01"),
             st("46", "2018-08-03", "01:22:08")];
is(stages(fvOrdered(slb)), ["41", "43", "44", "45", "46"], "reordered onto the clock");
is(fvStarts(fvOrdered(slb)).synthetic, false,
   "a real clock is now seen as real — this is what puts the voids back");
is(fvStarts(slb).synthetic, true,
   "and in page order it was not: the regression this fixes");

console.log("\nwhat it must NOT disturb");
const ordered = [st("1", "2024-05-26", "21:59:54"), st("2", "2024-05-27", "03:00:54"),
                 st("3", "2024-05-27", "07:45:55")];
is(stages(fvOrdered(ordered)), ["1", "2", "3"], "an already-ordered well is untouched");

const undated = [st("2", "", ""), st("1", "2024-05-26", "21:59:54")];
is(stages(fvOrdered(undated)), ["2", "1"],
   "a stage with no printed clock: nothing to sort on, so the order stands");
is(fvStarts(fvOrdered(undated)).synthetic, true,
   "and it still goes synthetic, as it must");

const tied = [st("2", "2024-05-26", "10:00:00"), st("1", "2024-05-26", "10:00:00")];
is(stages(fvOrdered(tied)), ["2", "1"],
   "equal starts keep their printed order — the sort is stable, not inventive");
is(fvStarts(fvOrdered(tied)).synthetic, true,
   "two stages on one clock reading still cannot be laid on a real axis");

is(stages(fvOrdered([])), [], "no stages");
is(stages(fvOrdered([st("1", "2024-05-26", "21:59:54")])), ["1"], "one stage");

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
