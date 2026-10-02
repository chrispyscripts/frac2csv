// A filter default belongs to the READER, not to the service company.
//
//   node tests/test_filter_reader_key.js
//
// The Lab's provider table maps a source string to a company, and more than
// one reader lands in each bucket. Measured on the flag reports actually
// filed:
//
//   Halliburton  "Halliburton IFS chart"              vector, no digitising
//                "Halliburton treatment plot (raster)"  pixel-traced
//   STEP         "STEP chart" (vector) + two raster readers
//   CalFrac      "CalFrac chart" + "MView chart"
//
// Hanging the default on the company meant a Hampel window dialled in on the
// traced charts was also applied to the vector ones, where there is no
// digitising noise for it to remove and it can only take something away.
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
  throw new Error(`${name} is unterminated`);
}

// the page's own state, as the functions expect to find it
let current = null, entries = [], filtStore = { byStage: {}, byProvider: {} };
const FILT_OFF = { kind: "none", amount: 0, kind2: "none", amount2: 0 };
function fileScope() { return (current && current.entry && current.entry.name) || ""; }
const filtStageKey = meta => `${fileScope()}::${(meta && meta.stage) || "?"}`;
eval(["filtReaderKey", "filtCompanyKey", "filtProvider", "filtSpecFor",
      "filtSourceOf"].map(lift).join("\n"));

let failed = 0;
function ok(cond, what) {
  if (cond) { console.log("  ok   " + what); return; }
  failed++; console.log("  FAIL " + what);
}

function open(source, company, file) {
  const entry = { name: file || "f.pdf", provider: company };
  entries = [entry];
  current = { entry, item: { source } };
}

const HAMPEL = { kind: "hampel", amount: 50, kind2: "none", amount2: 0 };

console.log("the two Halliburton readers are separate settings");
{
  filtStore = { byStage: {}, byProvider: {} };
  open("Halliburton treatment plot (raster)", "Halliburton");
  filtStore.byProvider[filtReaderKey()] = { ...HAMPEL };
  ok(filtSpecFor({}).kind === "hampel", "the raster reader keeps what it was given");
  open("Halliburton IFS chart", "Halliburton");
  ok(filtSpecFor({}).kind === "none",
     "the VECTOR reader under the same company is untouched");
}

console.log("all three STEP readers are separate");
{
  filtStore = { byStage: {}, byProvider: {} };
  open("STEP surface chart (raster)", "STEP");
  filtStore.byProvider[filtReaderKey()] = { ...HAMPEL };
  for (const other of ["STEP chart", "STEP chemical chart (raster)"]) {
    open(other, "STEP");
    ok(filtSpecFor({}).kind === "none", `${other} does not inherit it`);
  }
  open("STEP surface chart (raster)", "STEP");
  ok(filtSpecFor({}).kind === "hampel", "and the one it was saved on still has it");
}

console.log("a default saved under the old company key still works");
{
  filtStore = { byStage: {}, byProvider: {} };
  filtStore.byProvider["Trican"] = { ...HAMPEL };          // pre-change store
  open("Trican treatment chart (raster)", "Trican");
  ok(filtSpecFor({}).kind === "hampel",
     "an existing setting is not silently dropped");
  ok(filtSourceOf({}) === "provider", "and it still reads as a default");
}

console.log("a stage's own setting still beats both");
{
  filtStore = { byStage: {}, byProvider: {} };
  open("STEP surface chart (raster)", "STEP", "w.pdf");
  filtStore.byProvider[filtReaderKey()] = { ...HAMPEL };
  filtStore.byStage[filtStageKey({ stage: "3" })] = { kind: "sg", amount: 20 };
  ok(filtSpecFor({ stage: "3" }).kind === "sg", "the chart overrules the default");
  ok(filtSpecFor({ stage: "4" }).kind === "hampel", "its neighbour does not");
}

console.log("with no source at all it falls back to the company");
{
  filtStore = { byStage: {}, byProvider: {} };
  entries = [{ name: "f.pdf", provider: "Liberty" }];
  current = { entry: entries[0], item: {} };
  ok(filtReaderKey() === "Liberty", "so a chart with no source is never keyless");
}

console.log(failed ? `\n${failed} FAILED` : "\nfilter reader key: all assertions passed");
process.exit(failed ? 1 : 0);
