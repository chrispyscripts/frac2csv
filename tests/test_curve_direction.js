// Which way a WellSight curve runs on the Lab's chart and the stacked view.
//
//   node tests/test_curve_direction.js
//
// Each curve is drawn the way the printout under it draws it (#855: on a
// horizontal log the chart ran high end up while the printout below ran high
// end down, so the two looked like mirror images). The printout is turned a
// quarter left under the chart, its tracks' left edge at the bottom. A
// printout whose tracks run the other way across (P.turned, a horizontal
// log's) or a scale printed high to low turns the curve over; both together
// leave it high end up. Scales here are [from depth, left, right].
const fs = require("fs");
const path = require("path");
function lifter(file) {
  const src = fs.readFileSync(path.join(__dirname, "..", "lab", "public", file), "utf8");
  return name => {
    const at = src.indexOf("function " + name + "(");
    if (at < 0) throw new Error(`${name} is gone from ${file}`);
    let d = 0;
    for (let i = src.indexOf("{", at); i < src.length; i++) {
      if (src[i] === "{") d++; else if (src[i] === "}" && --d === 0) return src.slice(at, i + 1);
    }
  };
}
const lab = lifter("index.html");
eval(lab("wsDown"));
eval(lab("wsAcross"));
// the stacked view's down() reads the page's printout info, P: give it ours
const stackDown = (c, info) => new Function("P", lifter("logstack.html")("down") + "\nreturn down;")(info)(c);

let pass = 0, fail = 0;
function eq(got, want, what) {
  if (got === want) { pass++; return; }
  fail++;
  console.log(`FAIL ${what}\n  got:  ${got}\n  want: ${want}`);
}

const up = { scale: [[null, 0, 150]] };                 // gamma, 0 on the left
const rev = { scale: [[null, 10, 0]] };                 // ROP printed high to low
const none = { scale: null };                           // no printed scale on file
const mixed = { scale: [[null, 0, 10], [1200, 10, 0], [1500, 10, 0]] };
const strip = { turned: false }, horiz = { turned: true };

for (const [f, name] of [[wsDown, "Lab"], [stackDown, "stacked view"]]) {
  eq(f(up, strip), false, `${name}: a strip log's 0-150 gamma runs high end up`);
  eq(f(up, horiz), true, `${name}: a horizontal log's 0-150 gamma runs high end down, as its printout`);
  eq(f(rev, strip), true, `${name}: a strip log's ROP printed 10-0 runs high end down`);
  eq(f(rev, horiz), false, `${name}: a horizontal log's ROP printed 10-0 runs high end up`);
  eq(f(none, horiz), true, `${name}: no scale on file: the printout's turn alone decides`);
  eq(f(none, null), false, `${name}: no printout, no scale: high end up`);
  eq(f(up, null), false, `${name}: no printout: the printed scale decides`);
  eq(f(rev, null), true, `${name}: no printout, a 10-0 scale: high end down`);
  eq(f(mixed, strip), true, `${name}: scales that change along the log go by most of them`);
}

// where a reading lands across a chart 100 high, on 0..10
eq(wsAcross(10, 0, 10, 100, false), 0, "high end up: 10 at the top");
eq(wsAcross(0, 0, 10, 100, false), 100, "high end up: 0 at the bottom");
eq(wsAcross(10, 0, 10, 100, true), 100, "high end down: 10 at the bottom");
eq(wsAcross(2.5, 0, 10, 100, true), 25, "high end down: 2.5 a quarter down");
eq(wsAcross(99, 0, 10, 100, true), 100, "past the range: held at the edge");

console.log(`${fail ? "FAIL" : "PASS"}: curve direction (${pass} checks${fail ? `, ${fail} failed` : ""})`);
process.exit(fail ? 1 : 0);
