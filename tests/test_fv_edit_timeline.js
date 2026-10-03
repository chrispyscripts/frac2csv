// A FracView edit belongs to the timeline it was drawn on.
//
//   node tests/test_fv_edit_timeline.js
//
// The edit is a set of ABSOLUTE cut points, and applyFvEdits compares them
// against where the stages sit NOW. Exact, until the stages move — and a date
// correction moves them. On 00100, fixing interval 19's year shifted that
// stage by sixteen years: it then fell outside every stored boundary and
// contributed nothing, while its neighbours were cut at points meant for a
// timeline that no longer existed. "after you make changes to the date, the
// adjust feature ... pulls data backwards and cuts off instead of adjusting
// between the 2 stages".
const fs = require("fs");
const path = require("path");
const src = fs.readFileSync(
  path.join(__dirname, "..", "lab", "public", "index.html"), "utf8");
function lift(name) {
  const at = src.indexOf("function " + name + "(");
  if (at < 0) throw new Error(`${name} is gone from index.html`);
  let d = 0;
  for (let i = src.indexOf("{", at); i < src.length; i++) {
    if (src[i] === "{") d++; else if (src[i] === "}" && --d === 0) return src.slice(at, i + 1);
  }
}
eval([lift("fvStageStart"), lift("fvLayout"), lift("fvTimeline"),
      lift("fvEditFits")].join("\n"));

let pass = 0, fail = 0;
const is = (got, want, what) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? pass++ : fail++;
  console.log(`${ok ? "  ok  " : "  FAIL"} ${what}`);
  if (!ok) console.log(`        got ${JSON.stringify(got)} want ${JSON.stringify(want)}`);
};
const at = (d, t) => Date.parse(`${d}T${t}`);
const S = (stage, date, time, mins) => ({
  meta: { stage, date, start_time: time }, n: mins * 60, sample_sec: 1 });

// 00100's shape around the stage whose year was wrong
const WELL = () => [S("18", "2016-01-28", "19:57:16", 45),
                    S("19", "2016-01-28", "20:37:16", 45),
                    S("20", "2016-01-28", "21:19:16", 45)];
const MOVED = () => [S("18", "2016-01-28", "19:57:16", 45),
                     S("19", "2000-01-01", "20:37:16", 45),   // before the fix
                     S("20", "2016-01-28", "21:19:16", 45)];

console.log("an edit drawn on this timeline applies to it");
{
  const raw = WELL();
  const ed = { bounds: [at("2016-01-28","19:57:16"), at("2016-01-28","20:40:00"),
                        at("2016-01-28","21:19:16"), at("2016-01-28","22:04:16")],
               tl: fvTimeline(raw) };
  is(fvEditFits(raw, ed), true, "same timeline, accepted");
}

console.log("an edit drawn BEFORE a date was corrected does not");
{
  const before = MOVED();
  const ed = { bounds: [at("2000-01-01","20:37:16"), at("2000-01-01","21:00:00"),
                        at("2000-01-01","21:22:16")],
               tl: fvTimeline(before) };
  is(fvEditFits(WELL(), ed), false,
     "the stages moved sixteen years — refused rather than mis-cut");
  is(fvEditFits(before, ed), true, "and still fits the one it was drawn on");
}

console.log("an edit from before edits carried a timeline");
{
  // no `tl`: accepted once if its span still lies inside the well's own...
  const raw = WELL();
  const near = { bounds: [at("2016-01-28","20:00:00"), at("2016-01-28","21:30:00")] };
  is(fvEditFits(raw, near), true, "a plausible span is adopted");
  is(typeof near.tl, "string", "and stamped, so it is only judged once");

  const far = { bounds: [at("2000-01-01","20:00:00"), at("2000-01-01","21:30:00")] };
  is(fvEditFits(WELL(), far), false, "a span sixteen years away is not");
}

console.log("nothing to apply");
{
  is(fvEditFits(WELL(), null), false, "no edit");
  is(fvEditFits(WELL(), { bounds: [1] }), false, "a single bound is not a span");
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
