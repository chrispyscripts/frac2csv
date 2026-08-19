// The strip between the two charts must name the stage the way the CSV does.
//
//   node tests/test_stage_identity.js
//
// STAGE and LABEL are columns in the exported file. If the strip and
// wellModel ever disagree about either, the screen says one stage and the
// deliverable says another — and the strip exists precisely so someone can
// read the identity off the chart and go find it. So this checks
// stageIdentity against wellModel's OWN rule, both lifted out of
// index.html, over the stage keys the corpus actually produces.
const fs = require("fs");
const path = require("path");

const SRC = path.join(__dirname, "..", "lab", "public", "index.html");
const src = fs.readFileSync(SRC, "utf8");

const stageNum = s => { const m = String(s).match(/\d+/); return m ? +m[0] : 1e9; };
const _VARIANT = /\s+(Surface|BH|Bottom\s*Hole)\s*$/i;
const stageDisplay = key => String(key).replace(_VARIANT, "");
const stageVariant = key => {
  const m = _VARIANT.exec(String(key));
  return m ? m[1].replace(/bottom\s*hole/i, "BH") : "";
};

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
eval(lift("stageIdentity"));

// wellModel's own two lines, quoted from index.html rather than paraphrased:
//   const seqNo = String(bi + 1);
//   const label = (String(key) === "?" || String(key) === "") ? seqNo : String(key);
// Ordering is wellModel's sort, which stageItems also uses, so seq matches bi+1.
function exported(keys) {
  const order = [...new Set(keys.map(k => String(k || "?")))]
    .sort((a, b) => (stageNum(a) - stageNum(b)) || (a < b ? -1 : a > b ? 1 : 0));
  return order.map((key, bi) => {
    const seqNo = String(bi + 1);
    return { STAGE: seqNo,
             LABEL: (key === "?" || key === "") ? seqNo : String(key), key,
             seq: bi + 1 };
  });
}

let pass = 0, fail = 0;
function is(got, want, what) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? pass++ : fail++;
  console.log(`${ok ? "  ok  " : "  FAIL"} ${what}`);
  if (!ok) console.log(`        got ${JSON.stringify(got)}  want ${JSON.stringify(want)}`);
}

// the strip agrees with the export on every stage of a well
function agrees(keys, what) {
  const rows = exported(keys);
  const bad = [];
  for (const r of rows) {
    const id = stageIdentity({ type: "stage", key: r.key, seq: r.seq });
    // LABEL carries the variant; the strip splits it out as its own tag, so
    // put it back before comparing — that split is display, not disagreement.
    const rebuilt = id.variant ? `${id.label} ${id.variant}` : id.label;
    const want = r.LABEL.replace(/\s+Bottom\s*Hole\s*$/i, " BH");
    if (id.no !== r.STAGE || rebuilt !== want)
      bad.push(`key ${r.key}: strip ${id.no}/${rebuilt} vs csv ${r.STAGE}/${want}`);
  }
  is(bad, [], `${what} (${rows.length} stages)`);
}

console.log("the strip and the CSV name the same stage");
agrees(["1", "2", "3", "4", "5", "5 (2)"], "BJ 00636, doubled stage 5");
agrees(["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"], "BJ 00440");
agrees(["HRF 5A", "HRF 5B", "1", "2"], "Liberty HRF naming");
agrees(["Zone 1 Surface", "Zone 1 BH", "Zone 2 Surface"], "Calfrac Surface/BH pairs");
agrees(["1-30"], "a whole job landing as one stage (#362)");

console.log("\nthe pieces individually");
let id = stageIdentity({ type: "stage", key: "5 (2)", seq: 6 });
is([id.no, id.label, id.variant], ["6", "5 (2)", ""],
   "position and printed name are different numbers, and both show");
id = stageIdentity({ type: "stage", key: "Zone 3 Bottom Hole", seq: 3 });
is([id.no, id.label, id.variant], ["3", "Zone 3", "BH"],
   "#546: the variant leaves the label and becomes its own tag");
id = stageIdentity({ type: "stage", key: "?", seq: 2 });
is([id.no, id.label], ["2", "2"],
   'a template printing no name falls back to the position, as the export does');
id = stageIdentity({ type: "stage", key: "", seq: 4 });
is([id.no, id.label], ["4", "4"], "and so does an empty one");
id = stageIdentity({ type: "stage", key: "7", seq: undefined });
is([id.no, id.label], ["", "7"],
   "no sequence number: show the name alone rather than inventing a position");

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
