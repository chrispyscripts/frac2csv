// A curve switched off stays off across charts and files.
//
//   node tests/test_hidden_channels.js
//
// Carmine: a data set disabled on the main graph came back when cycling
// through files and charts. The hidden set is now keyed by channel name and
// persists; a chart that lacks the channel hides nothing; switching on again
// is the only way back.
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
eval(lift("hiddenIdentity"));
eval(lift("applyHidden"));
eval(lift("toggleHidden"));

let pass = 0, fail = 0;
const is = (got, want, what) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? pass++ : fail++;
  console.log(`${ok ? "  ok  " : "  FAIL"} ${what}`);
  if (!ok) console.log(`        got ${JSON.stringify(got)}  want ${JSON.stringify(want)}`);
};
const ch = (key, label) => ({ key, label: label || key });

// file A, stage 1: WH Prop Conc is third
const a1 = [ch("Tr Press"), ch("Slurry Rate"), ch("WH Prop Conc"), ch("BH Prop Conc")];
const keys = new Set();
is([...applyHidden(a1, keys)], [], "nothing hidden to begin with");
toggleHidden(a1[2], keys);
is([...keys], ["WH Prop Conc"], "switching a curve off records its name, not its position");
is([...applyHidden(a1, keys)], [2], "…and hides it on this chart");

// file B, stage 7: a different template puts WH Prop Conc first, and has a monitor channel
const b7 = [ch("WH Prop Conc"), ch("Monitor Pressure"), ch("Tr Press")];
is([...applyHidden(b7, keys)], [0], "the same curve stays off on the next file, wherever it sits");

// a chart that does not carry the channel hides nothing
const c3 = [ch("Tr Press"), ch("Slurry Rate")];
is([...applyHidden(c3, keys)], [], "a chart without the channel is drawn whole");

// the "As extracted" label mode does not change what is hidden
const raw = [ch("WH Prop Conc", "WH Conc. (100kg/m³)"), ch("Tr Press", "Surface Pressure (MPa)")];
is([...applyHidden(raw, keys)], [0], "identity is the key, not the shown label");

// switching on again is the only way back
toggleHidden(b7[0], keys);
is([...keys], [], "switched on again: the name is gone from the set");
is([...applyHidden(a1, keys)], [], "…and the curve is back on every chart");

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
