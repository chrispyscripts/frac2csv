// What a flag says about where its file came from.
//
//   node tests/test_flag_paths.js
//
// Carmine asked for the path on a flag (#355), to know which drive or folder
// a file came from. The whole path also put a user name and scratch folders
// on the public tracker, so the drive and its folders stay and the rest goes.
const fs = require("fs");
const path = require("path");
const src = fs.readFileSync(path.join(__dirname, "..", "lab", "public", "index.html"), "utf8");
function lift(name) {
  const at = src.indexOf("function " + name + "(");
  if (at < 0) throw new Error(`${name} is gone from index.html`);
  let d = 0;
  for (let i = src.indexOf("{", at); i < src.length; i++) {
    if (src[i] === "{") d++; else if (src[i] === "}" && --d === 0) return src.slice(at, i + 1);
  }
}
eval(lift("shareablePath"));
eval(lift("scrubPaths"));
eval(lift("flagBody"));

let pass = 0, fail = 0;
function eq(got, want, what) {
  if (got === want) { pass++; return; }
  fail++;
  console.log(`FAIL ${what}\n  got:  ${got}\n  want: ${want}`);
}

// the drive and its folders stay
eq(shareablePath("/Volumes/CnC-2TB-ssd/AER-Frac-Montney-ARC/00349-100012706405W600_0500220_COMP.pdf"),
   "CnC-2TB-ssd/AER-Frac-Montney-ARC/00349-100012706405W600_0500220_COMP.pdf", "Mac drive");
eq(shareablePath("K:\\BCER-Frac\\_STEP-Type\\00180-200A038L094H0500_31976_COMP_2016DEC09_INITIAL COMPLETION.PDF"),
   "K:\\BCER-Frac\\_STEP-Type\\00180-200A038L094H0500_31976_COMP_2016DEC09_INITIAL COMPLETION.PDF",
   "Windows drive kept as it is");
// a home folder loses the user name
eq(shareablePath("/Users/chrisharder/frac-data/BCER-Frac-Spud-2026/00022-x.pdf"),
   "~/frac-data/BCER-Frac-Spud-2026/00022-x.pdf", "Mac home");
eq(shareablePath("C:\\Users\\Carmine\\Documents\\frac\\00022-x.PDF"),
   "~\\Documents\\frac\\00022-x.PDF", "Windows home");
// a temp copy says nothing useful about where the file lives: name only
eq(shareablePath("/private/tmp/claude-501/abc/scratchpad/pdfs-184/00270-H10-04.PDF"),
   "00270-H10-04.PDF", "Mac temp copy");
eq(shareablePath("C:\\Users\\Carmine\\AppData\\Local\\Temp\\00270-H10-04.PDF"),
   "00270-H10-04.PDF", "Windows temp copy");

// in running text: a batch report line, a read-only notice
eq(scrubPaths("- /Users/chrisharder/frac-data/B/00022-x.pdf  —  5 page(s) skipped"),
   "- ~/frac-data/B/00022-x.pdf  —  5 page(s) skipped", "batch line");
eq(scrubPaths("/Volumes/CnC-2TB-ssd/AER-Frac-Montney-ARC is read-only — exports saved to /Users/chrisharder/Downloads instead."),
   "CnC-2TB-ssd/AER-Frac-Montney-ARC is read-only — exports saved to ~/Downloads instead.",
   "folder paths in a sentence");
eq(scrubPaths("no path here, 3 MPa at 12:00"), "no path here, 3 MPa at 12:00", "plain text untouched");

// the whole request body: every string, nested, but not the screenshot
const body = JSON.parse(flagBody({
  description: "see /private/tmp/x/scratchpad/00270.PDF",
  diagnostics: { path: "/Users/chrisharder/d/00270.PDF", notes: ["- /Volumes/V/f/00270.pdf  —  x"],
                 samples: 15832 },
  screenshot: "data:image/png;base64,/Users/AAAA",
}));
eq(body.description, "see 00270.PDF", "description");
eq(body.diagnostics.path, "~/d/00270.PDF", "diagnostics.path");
eq(body.diagnostics.notes[0], "- V/f/00270.pdf  —  x", "notes array");
eq(body.diagnostics.samples, 15832, "numbers untouched");
eq(body.screenshot, "data:image/png;base64,/Users/AAAA", "screenshot untouched");
eq(/\/Users\/|\/private\/|\/Volumes\//.test(JSON.stringify(body).replace(body.screenshot, "")), false,
   "nothing left");

// every sender goes through flagBody
const senders = src.split("fetch(FLAG_ENDPOINT").length - 1;
const scrubbed = (src.match(/fetch\(FLAG_ENDPOINT, \{\s*method: "POST", headers: \{ "Content-Type": "application\/json" \},\s*body: flagBody\(/g) || []).length;
eq(scrubbed, senders, `all ${senders} flag senders scrub their body`);

console.log(`${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
