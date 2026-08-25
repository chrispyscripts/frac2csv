// The column-heading patterns behind Our Terms.
//
//   node tests/test_our_terms.js
//
// Measured over 43 real extracted tables from six provider folders, with the
// user's own mappings cleared so it is the PATTERNS being judged: the two
// depth terms were the worst on the set. Halliburton's IFS Treatment Summary
// prints "Top of treatment (m)" and "Bottom of treatment (m)" and neither
// pattern reached them, so Carmine had to point at those columns by hand on
// every IFS file.
//
// Widening a pattern is the easy half. The half that matters is that it does
// not start claiming a column it should not, so most of this file is the
// headings that must STAY unmatched.
const fs = require("fs");
const path = require("path");
const SRC = path.join(__dirname, "..", "lab", "public", "index.html");
const src = fs.readFileSync(SRC, "utf8");

const at = src.indexOf("const OUR_TERMS = [");
const end = src.indexOf("\n];", at);
if (at < 0 || end < 0) throw new Error("OUR_TERMS is gone from index.html");
const OUR_TERMS = eval(src.slice(at + "const OUR_TERMS = ".length, end + 2));

let pass = 0, fail = 0;
const is = (got, want, what) => {
  const ok = got === want;
  ok ? pass++ : fail++;
  console.log(`${ok ? "  ok  " : "  FAIL"} ${what}`);
  if (!ok) console.log(`        got ${got}  want ${want}`);
};
const term = k => OUR_TERMS.find(t => t.key === k);
const claims = (k, heading) => {
  const t = term(k);
  if (!t || !t.accept) return false;
  if (t.reject && t.reject.test(heading)) return false;
  return t.accept.test(heading);
};

console.log("the depth headings the sheets actually print");
for (const h of ["Top of treatment (m)", "Top of Treatment (m)",
                 "Treatment Top Perf (m)", "Interval Top (m)",
                 "Top Depth (m)", "Top Perf (m)", "Perforation Top",
                 "Top Packer (mMD)"]) {
  is(claims("top", h), true, `top  <- ${h}`);
}
for (const h of ["Bottom of treatment (m)", "Bottom of Treatment (m)",
                 "Treatment Bottom Perf (m)", "Interval Bottom (m)",
                 "Bottom Depth (m)", "Base Perf (m)", "Perforation Bottom",
                 "Interval Base (m)"]) {
  is(claims("base", h), true, `base <- ${h}`);
}

console.log("\nand what they must NOT claim");
// top and base must never claim each other
is(claims("top", "Bottom of treatment (m)"), false, "top does not take bottom");
is(claims("base", "Top of treatment (m)"), false, "base does not take top");
// the reject list still bites
is(claims("top", "Proposed Top (m)"), false, "top rejects a PROPOSED depth");
is(claims("base", "Interval Length (m)"), false, "base rejects a length");
// neighbouring columns on the same sheets
for (const h of ["Total Depth (m)", "TVD (m)", "Plug Depth (m)",
                 "Hole Volume (m3)", "Top Prop Conc (kg/m3)",
                 "Treatment Number", "Pump Time (min)"]) {
  is(claims("top", h) || claims("base", h), false, `neither takes ${h}`);
}

console.log("\nthe terms that were already right stay right");
is(claims("uwi", "UWI"), true, "uwi <- UWI");
is(claims("stageno", "Stage Number"), true, "stageno <- Stage Number");
is(claims("pmax", "Max Treating Pressure (kPa)"), true, "pmax <- Max Treating Pressure");
is(claims("pmax", "Avg Treating Pressure (MPa)"), false, "pmax does not take the average");
is(claims("pavg", "Avg Treating Pressure (MPa)"), true, "pavg <- Avg Treating Pressure");

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
