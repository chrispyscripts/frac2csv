// Where FracView puts each stage on the axis.
//
//   node tests/test_fvlayout.js
//
// The axis is supposed to be real elapsed time: a two-hour wait between two
// stages is two hours of empty chart, and a stage whose clock is wrong draws
// out of step with its own number. Everything here is about NOT throwing that
// away — the old rule needed every stage dated and strictly increasing, and
// one undated stage in forty sent the whole well to a made-up axis where no
// fault can show.
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
eval(lift("fvStageStart"));
eval(lift("fvLayout"));

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
const at = (d, t) => Date.parse(`${d}T${t}`);
const labels = L => L.stages.map(s => String(s.meta.stage));

console.log("a clean well keeps its printed clock");
{
  const a = [st("1", "2024-03-01", "06:00:00"), st("2", "2024-03-01", "09:00:00")];
  const L = fvLayout(a);
  is(L.synthetic, false, "not synthetic");
  is(L.starts, [at("2024-03-01","06:00:00"), at("2024-03-01","09:00:00")],
     "starts are exactly what the sheets print");
  is([...L.invented], [], "nothing invented");
  is(L.jumps, [], "no jumps");
}

console.log("\nthe three-hour wait between them is three hours of axis");
{
  const a = [st("1", "2024-03-01", "06:00:00", 60), st("2", "2024-03-01", "09:00:00", 60)];
  const L = fvLayout(a);
  is(L.starts[1] - L.starts[0], 3 * 3600 * 1000, "gap is the real elapsed time");
}

console.log("\nnothing printed a clock anywhere — end to end, and says so");
{
  const a = [st("1", "", "", 30), st("2", "", "", 45)];
  const L = fvLayout(a);
  is(L.synthetic, true, "synthetic");
  is(L.starts[1] - L.starts[0], 30 * 60 * 1000, "laid end to end by duration");
  is([...L.invented], [0, 1], "every start invented");
}

console.log("\nONE undated stage no longer costs the other two their clock");
{
  const a = [st("1", "2024-03-01", "06:00:00", 60),
             st("2", "", "", 30),
             st("3", "2024-03-01", "12:00:00", 60)];
  const L = fvLayout(a);
  is(L.synthetic, false, "still a real clock");
  is(L.starts[0], at("2024-03-01","06:00:00"), "stage 1 as printed");
  is(L.starts[2], at("2024-03-01","12:00:00"), "stage 3 as printed");
  is(L.starts[1], at("2024-03-01","07:00:00"), "stage 2 placed after stage 1");
  is([...L.invented], [1], "only the undated one is invented");
}

console.log("\nan undated run at the FRONT hangs back off the first real start");
{
  const a = [st("1", "", "", 30), st("2", "2024-03-01", "06:00:00", 60)];
  const L = fvLayout(a);
  is(L.starts[0], at("2024-03-01","05:30:00"), "stage 1 ends where stage 2 begins");
  is([...L.invented], [0], "only the undated one");
}

console.log("\na stage printed OUT OF ORDER draws where its clock says");
{
  // 00495: 3B dated before stage 1 — the fault this view exists for
  const a = [st("1", "2023-11-02", "10:39:59", 60),
             st("2", "2023-11-03", "03:41:00", 60),
             st("3B", "2023-11-02", "04:51:00", 60),
             st("4", "2023-11-03", "08:00:00", 60)];
  const L = fvLayout(a);
  is(L.synthetic, false, "NOT sent to the synthetic axis");
  is(labels(L), ["3B", "1", "2", "4"], "3B draws first — out of step with its number");
  is(L.jumps.length, 1, "one backward jump");
  is([L.jumps[0].from, L.jumps[0].to], ["2", "3B"], "named in printed order");
  is(L.jumps[0].tTo, at("2023-11-02","04:51:00"), "the moment it lands on");
  is([...L.invented], [], "nothing invented — every stage printed a time");
}

console.log("\ntwo stages on the same stamp: the later one is pushed clear");
{
  const a = [st("1", "2024-03-01", "06:00:00", 60), st("2", "2024-03-01", "06:00:00", 60)];
  const L = fvLayout(a);
  is(L.starts[1] > L.starts[0], true, "no zero-width band");
  is([...L.invented], [1], "the push is marked invented");
}

console.log("\na well dated to the DAY is not a wall clock, whatever it prints");
{
  const a = ["1","2","3","4"].map(k => st(k, "2024-03-01", "00:00:00", 60));
  const L = fvLayout(a);
  is(L.synthetic, true, "past half the axis invented — called synthetic");
  is([...L.invented].length, 4, "and the whole axis is flagged, not just the pushes");
}

console.log("\nstage order out of the sort is stable on a tie");
{
  const a = [st("7", "", "", 10), st("8", "", "", 10), st("9", "", "", 10)];
  is(labels(fvLayout(a)), ["7", "8", "9"], "printed order kept");
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
