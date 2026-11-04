// The panel under the graph reads the same way up as the graph, whichever way
// the chart sits on the page, and the arrow keys walk the list clicked last.
//
//   node tests/test_page_rotation.js
//
// The geometry is in the UNROTATED page (00047 p188, displayed 792x612 under
// /Rotate 90, has a chart running down to y 622). pdf.js takes an absolute
// rotation, so the chart's direction alone decides, whatever the page's flag.
const assert = require("assert");
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

// pdf.js's PageViewport transforms, for a 612x792 mediabox
const TURN = { 0: [1, 0, 0, -1], 90: [0, 1, 1, 0], 180: [-1, 0, 0, 1], 270: [0, -1, -1, 0] };
function fakePage(rotate) {
  return {
    rotate, view: [0, 0, 612, 792],
    getViewport({ rotation = rotate }) {
      const [a, b, c, d] = TURN[rotation];
      return { convertToViewportPoint: (x, y) => [a * x + c * y, b * x + d * y] };
    },
  };
}

let current, orig, navigated;
const list = [{ name: "a" }, { name: "b" }, { name: "c" }];
for (const e of list) e.head = { scrollIntoView() {} };
const navigableEntries = () => list;
const selectFile = e => { navigated = e.name; current = { entry: e }; };
const document = { body: { dataset: {} } };
const { chartRotation, pageRotation, setNavList, navFile } = eval("(() => {"
  + [lift("geomToPdf"), lift("chartRotation"), lift("pageRotation"),
     lift("setNavList"), lift("navFile")].join("\n")
  + "\nreturn { chartRotation, pageRotation, setNavList, navFile }; })()");

// time along the unrotated page's width, either way
for (const flag of [0, 90, 180, 270]) {
  assert.strictEqual(chartRotation(fakePage(flag), { axis: "x", tb: 30 }), 0, `x+ under ${flag}`);
  assert.strictEqual(chartRotation(fakePage(flag), { axis: "x", tb: -30 }), 180, `x- under ${flag}`);
  // up the page (CalFrac 00002 p84, tb -5.95) and down it
  assert.strictEqual(chartRotation(fakePage(flag), { axis: "y", tb: -6 }), 90, `y- under ${flag}`);
  assert.strictEqual(chartRotation(fakePage(flag), { axis: "y", tb: 6 }), 270, `y+ under ${flag}`);
}

// the full-page view follows the chart; with no geometry, the page's own flag
orig = { pageIdx: 0 };
current = { item: { srcs: [{ page: 188, geom: { axis: "x", tb: 30 } }] } };
assert.strictEqual(pageRotation(fakePage(90)), 0);   // 00047 p188 was sideways
current = { item: { srcs: [{ page: 84, geom: { axis: "y", tb: -6 } }] } };
assert.strictEqual(pageRotation(fakePage(0)), 90);   // sideways on a flagless page
current = { item: { srcs: [{ page: 5 }] } };
assert.strictEqual(pageRotation(fakePage(90)), 90);
current = null;
assert.strictEqual(pageRotation(fakePage(270)), 270);

// the file list: one step at a time, stopping at each end
setNavList("files");
assert.strictEqual(document.body.dataset.nav, "files");
current = { entry: list[1] };
navFile(1); assert.strictEqual(navigated, "c");
navigated = null; navFile(1); assert.strictEqual(navigated, null, "stops at the last file");
navFile(-1); assert.strictEqual(navigated, "b");
navFile(-1); assert.strictEqual(navigated, "a");
navigated = null; navFile(-1); assert.strictEqual(navigated, null, "stops at the first file");
current = null;
navFile(1); assert.strictEqual(navigated, "a", "nothing open: starts at the top");
current = null;
navFile(-1); assert.strictEqual(navigated, "c", "nothing open, going up: starts at the end");

console.log("ok");
