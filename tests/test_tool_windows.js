// The Directional Survey and Geology tools: their menu cards in the Lab and
// the small pure helpers of their windows (survey.html, geology.html).
//
//   node tests/test_tool_windows.js
const fs = require("fs");
const path = require("path");
const assert = require("assert/strict");
const P = f => path.join(__dirname, "..", "lab", "public", f);
const lab = fs.readFileSync(P("index.html"), "utf8");
const survey = fs.readFileSync(P("survey.html"), "utf8");
const geology = fs.readFileSync(P("geology.html"), "utf8");

function lift(src, name, where) {
  const at = src.indexOf("function " + name + "(");
  if (at < 0) throw new Error(`${name} is gone from ${where}`);
  let d = 0;
  for (let i = src.indexOf("{", at); i < src.length; i++) {
    if (src[i] === "{") d++; else if (src[i] === "}" && --d === 0) return src.slice(at, i + 1);
  }
}
const S = new Function(["niceTicks", "joinCsv", "csvName", "nearestStation"].map(n => lift(survey, n, "survey.html")).join("\n")
  + "\nreturn { niceTicks, joinCsv, csvName, nearestStation };")();
const G = new Function(["joinCsv", "csvName", "interleave"].map(n => lift(geology, n, "geology.html")).join("\n")
  + "\nreturn { joinCsv, csvName, interleave };")();

// the menu: two more cards, each opening its own window
for (const [tool, page] of [["survey", "survey.html"], ["geology", "geology.html"]]) {
  assert.match(lab, new RegExp(`class="homecard"[^>]*data-tool="${tool}"`), `${tool} card on the menu`);
  assert.match(lab, new RegExp(`${tool}: \\{ page: "${page}"`), `${tool} opens ${page}`);
  assert.ok(fs.existsSync(P(page)), `${page} ships in lab/public`);
}
assert.match(lab, /window\.open\(T\.page, winName\(tool\)/, "a window of its own, named per Lab window");
assert.match(lab, /\.homecard\[data-mode\]/, "the mode cards keep their own handler");
// each window posts its files to the desktop app's own endpoint
assert.match(survey, /fetch\("\/api\/survey"/);
assert.match(geology, /fetch\("\/api\/geology"/);
const server = fs.readFileSync(path.join(__dirname, "..", "localapp.py"), "utf8");
assert.match(server, /self\.path == "\/api\/survey"/);
assert.match(server, /self\.path == "\/api\/geology"/);

// axis ticks: round steps across the range
assert.deepEqual(S.niceTicks(0, 1000, 5), [0, 200, 400, 600, 800, 1000]);
assert.deepEqual(S.niceTicks(-37, 52, 4), [-20, 0, 20, 40]);
assert.deepEqual(S.niceTicks(5, 5, 5).length > 0, true, "a flat range still gets ticks");

// CSVs joined: one header, every file's rows
const a = "UWI,MD (m)\r\nW1,0\r\nW1,10\r\n", b = "UWI,MD (m)\r\nW2,0\r\n";
for (const J of [S.joinCsv, G.joinCsv]) {
  assert.equal(J([a, b]), "UWI,MD (m)\r\nW1,0\r\nW1,10\r\nW2,0\r\n");
  assert.equal(J([]), "");
  assert.equal(J(["", b]), b);
}
// a UWI's slashes are not in a file name
assert.equal(S.csvName("100/01-02-003-04W5/00", "x.pdf", "_survey"), "100_01-02-003-04W5_00_survey.csv");
assert.equal(G.csvName(null, "my report.pdf", "_tops"), "my_report_tops.csv");

// the station nearest the pointer on a view
const st = [{ ew: 0, ns: 0 }, { ew: 100, ns: 5 }, { ew: 200, ns: 9 }];
assert.equal(S.nearestStation(st, 120, 0, s => s.ew, s => s.ns), 1);
assert.equal(S.nearestStation(st, 999, 0, s => s.ew, s => s.ns), 2);

// tops sit above the first interval at or below them
const rows = G.interleave([{ top: 500, base: 520 }, { top: 520, base: 540 }],
                          [{ md: 520, name: "B" }, { md: 400, name: "A" }, { md: 900, name: "C" }]);
assert.deepEqual(rows.map(r => r.top ? r.top.name : r.sample.top), ["A", 500, "B", 520, "C"]);

console.log("PASS: survey and geology tool windows, menu cards and helpers");
