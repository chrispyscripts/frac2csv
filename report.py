"""Frac2CSV report: self-contained interactive HTML viewer for extracted data.

Written next to each CSV. Opens in any browser, no dependencies, no network.
Features: min/max envelope rendering (spikes stay visible zoomed out),
drag-to-zoom synced across channels, crosshair readout to the exact second,
pinnable cursors with delta comparison, and quality-flag shading for raster
extractions (amber = interpolated span, hatched = overlapping curves).
"""
import json

import numpy as np

CHANNELS = [
    ("Tr Press", "Treating Pressure", "MPa", "#1d5bd8"),
    ("Slurry Rate", "Slurry Rate", "m3/min", "#c8372d"),
    ("WH Prop Conc", "Prop Conc @ Blender (WH)", "kg/m3", "#1e7a34"),
    ("BH Prop Conc", "Prop Conc @ Formation (BH)", "kg/m3", "#7a3b9b"),
]


def write_report(path, meta, samples, data, sample_sec=1.0, kind="vector",
                 quality=None):
    channels = []
    for key, label, unit, color in CHANNELS:
        if key not in data:
            continue
        vals = [None if np.isnan(v) else round(float(v), 4) for v in data[key]]
        q = quality.get(key) if quality else None
        channels.append({
            "key": key, "label": label, "unit": unit, "color": color,
            "values": vals,
            "gaps": [[round(a, 1), round(b, 1)] for a, b in q.gaps] if q else [],
            "overlaps": [[round(a, 1), round(b, 1), o] for a, b, o in q.overlaps] if q else [],
            "caveats": q.caveats() if q else [],
        })
    payload = {
        "meta": {"title": meta.title, "uwi": meta.uwi, "stage": meta.stage,
                 "date": meta.date, "duration_min": meta.duration_min,
                 "kind": kind, "warnings": meta.warnings},
        "n": int(len(samples)), "sample_sec": float(sample_sec),
        "channels": channels,
    }
    html = _TEMPLATE.replace("__PAYLOAD__", json.dumps(payload, separators=(",", ":")))
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Frac2CSV report</title>
<style>
  :root { --bg:#f7f9fb; --card:#fff; --ink:#17222e; --mut:#5b6b7b; --line:#dfe6ec;
          --acc:#1d5bd8; --amber:#e8b34b; --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:14.5px/1.5 -apple-system,"Segoe UI",system-ui,sans-serif; }
  .wrap { max-width:1100px; margin:0 auto; padding:22px 18px 60px; }
  h1 { font-size:20px; margin:0 0 4px; }
  .sub { color:var(--mut); font-size:13.5px; margin-bottom:10px; }
  .chips { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:8px; }
  .chip { font-family:var(--mono); font-size:12px; background:var(--card);
          border:1px solid var(--line); border-radius:4px; padding:3px 9px; color:var(--mut); }
  .chip b { color:var(--ink); }
  .chip.warn { border-color:#ecd9b6; background:#fdf6ec; color:#8a5a14; }
  .hint { color:var(--mut); font-size:12.5px; margin:6px 0 10px; }
  .readout { position:sticky; top:0; z-index:5; background:var(--card); border:1px solid var(--line);
             border-radius:6px; padding:8px 14px; font-family:var(--mono); font-size:12.5px;
             display:flex; flex-wrap:wrap; gap:4px 22px; min-height:36px; align-items:center;
             box-shadow:0 2px 8px rgba(23,34,46,.06); }
  .readout .t { font-weight:700; }
  .readout .pin { color:var(--mut); }
  .chart { background:var(--card); border:1px solid var(--line); border-radius:6px;
           margin-top:12px; padding:10px 12px 6px; }
  .chart .head { display:flex; justify-content:space-between; align-items:baseline; flex-wrap:wrap; }
  .chart .name { font-weight:600; font-size:13.5px; }
  .chart .cav { font-size:12px; color:#8a5a14; }
  canvas { width:100%; display:block; cursor:crosshair; touch-action:none; }
  .legendbar { display:flex; gap:18px; align-items:center; margin:10px 2px 0; font-size:12px; color:var(--mut); }
  .sw { display:inline-block; width:14px; height:10px; border-radius:2px; vertical-align:-1px; margin-right:5px; }
  button { font:inherit; font-size:12.5px; border:1px solid var(--line); background:var(--card);
           border-radius:5px; padding:4px 12px; cursor:pointer; color:var(--ink); }
  button:hover { border-color:var(--acc); color:var(--acc); }
  button:focus-visible { outline:2px solid var(--acc); outline-offset:1px; }
</style>
</head>
<body>
<div class="wrap">
  <h1 id="title"></h1>
  <div class="sub" id="sub"></div>
  <div class="chips" id="chips"></div>
  <div class="hint">Drag to zoom &middot; double-click to reset &middot; hover for values at any second &middot;
    click to pin a cursor (two pins show &Delta;) &middot; <button id="reset">Reset zoom</button></div>
  <div class="readout" id="readout"><span class="pin">Hover a chart&hellip;</span></div>
  <div id="charts"></div>
  <div class="legendbar" id="legendbar" hidden>
    <span><span class="sw" style="background:rgba(232,179,75,.45)"></span>interpolated estimate (curve unreadable)</span>
    <span><span class="sw" id="hatchsw"></span>overlapping curves &mdash; less reliable</span>
  </div>
</div>
<script>
const D = __PAYLOAD__;
const N = D.n, DT = D.sample_sec;
const tOf = i => i * DT;
const fmt = s => {
  const m = Math.floor(s / 60), ss = s % 60;
  return String(m).padStart(2, "0") + ":" + (ss < 10 ? "0" : "") +
         (Number.isInteger(ss) ? ss : ss.toFixed(1));
};
const fmtv = v => v == null ? "—" : (Math.abs(v) >= 100 ? v.toFixed(1) : v.toFixed(3));

// header
const M = D.meta;
document.getElementById("title").textContent = M.title || "Frac stage extraction";
document.title = (M.uwi ? M.uwi + " stage " + M.stage : "Frac2CSV") + " — report";
document.getElementById("sub").textContent =
  [M.uwi && "UWI " + M.uwi, M.stage && "stage " + M.stage, M.date,
   M.duration_min + " min", N.toLocaleString() + " samples @ " + DT + " s"].filter(Boolean).join("  ·  ");
const chips = document.getElementById("chips");
const addChip = (html, cls) => {
  const el = document.createElement("span");
  el.className = "chip" + (cls ? " " + cls : ""); el.innerHTML = html; chips.appendChild(el);
};
addChip(D.meta.kind === "vector" ? "input: <b>vector PDF</b> — near-lossless geometry"
        : "input: <b>raster</b> — pixel-traced, see flagged spans", D.meta.kind === "vector" ? "" : "warn");
(M.warnings || []).forEach(w => addChip("&#9888; " + w, "warn"));

// hatch pattern for overlap shading
function hatch(color) {
  const c = document.createElement("canvas"); c.width = c.height = 8;
  const g = c.getContext("2d");
  g.strokeStyle = color; g.lineWidth = 1.4;
  g.beginPath(); g.moveTo(-2, 10); g.lineTo(10, -2); g.stroke();
  return c;
}
const hatchTile = hatch("rgba(122,59,155,.55)");
const sw = document.getElementById("hatchsw");
if (sw) sw.style.background = "url(" + hatchTile.toDataURL() + ")";
if (D.channels.some(ch => ch.gaps.length || ch.overlaps.length))
  document.getElementById("legendbar").hidden = false;

// state
let w0 = 0, w1 = N - 1;          // visible sample window
let hover = null;                 // hovered sample index
let pins = [];                    // pinned sample indices (max 2)
const charts = [];

const PADL = 56, PADR = 12, PADT = 8, PADB = 20, CH = 170;

function niceTicks(max) {
  const raw = max / 4, pow = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  const step = [1, 2, 2.5, 5, 10].map(k => k * pow).find(s => max / s <= 5) || pow * 10;
  const out = []; for (let v = 0; v <= max * 1.0001; v += step) out.push(v);
  return out;
}

function makeChart(ch) {
  const box = document.createElement("div"); box.className = "chart";
  const head = document.createElement("div"); head.className = "head";
  head.innerHTML = '<span class="name" style="color:' + ch.color + '">' + ch.label +
                   ' (' + ch.unit + ')</span>' +
                   (ch.caveats.length ? '<span class="cav">&#9888; ' + ch.caveats.join(" · ") + '</span>' : "");
  const cv = document.createElement("canvas"); cv.height = CH;
  cv.setAttribute("role", "img");
  cv.setAttribute("aria-label", ch.label + " time series");
  box.appendChild(head); box.appendChild(cv);
  document.getElementById("charts").appendChild(box);
  const obj = { ch, cv, drag: null };
  charts.push(obj);

  cv.addEventListener("mousemove", ev => {
    const r = cv.getBoundingClientRect(), x = ev.clientX - r.left;
    if (obj.drag != null) { obj.dragEnd = x; drawAll(); return; }
    hover = xToIdx(x, r.width); drawAll();
  });
  cv.addEventListener("mouseleave", () => { hover = null; drawAll(); });
  cv.addEventListener("mousedown", ev => {
    const r = cv.getBoundingClientRect(); obj.drag = ev.clientX - r.left; obj.dragEnd = null;
  });
  window.addEventListener("mouseup", ev => {
    if (obj.drag == null) return;
    const r = cv.getBoundingClientRect(), x = ev.clientX - r.left;
    const a = obj.drag, b = x; obj.drag = null; obj.dragEnd = null;
    if (Math.abs(b - a) > 6) {                     // drag = zoom
      let i0 = xToIdx(Math.min(a, b), r.width), i1 = xToIdx(Math.max(a, b), r.width);
      if (i1 - i0 >= 4) { w0 = i0; w1 = i1; hover = null; }
    } else {                                        // click = pin
      const i = xToIdx(x, r.width);
      if (i != null) { pins = pins.includes(i) ? pins.filter(p => p !== i) : [...pins, i].slice(-2); }
    }
    drawAll();
  });
  cv.addEventListener("dblclick", () => { w0 = 0; w1 = N - 1; drawAll(); });
}
document.getElementById("reset").addEventListener("click", () => { w0 = 0; w1 = N - 1; drawAll(); });

function xToIdx(x, W) {
  const f = (x - PADL) / (W - PADL - PADR);
  if (f < 0 || f > 1) return null;
  return Math.max(w0, Math.min(w1, Math.round(w0 + f * (w1 - w0))));
}

function drawChart(o) {
  const { ch, cv } = o;
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = CH;
  cv.width = W * dpr; cv.height = H * dpr;
  const g = cv.getContext("2d"); g.scale(dpr, dpr);
  const plotW = W - PADL - PADR, plotH = H - PADT - PADB;
  const xOf = i => PADL + (i - w0) / (w1 - w0) * plotW;

  // y-scale fits the visible window
  let vmax = 0;
  for (let i = w0; i <= w1; i++) { const v = ch.values[i]; if (v != null && v > vmax) vmax = v; }
  vmax = vmax > 0 ? vmax * 1.08 : 1;
  const yOf = v => PADT + (1 - v / vmax) * plotH;

  // quality shading first (under the data)
  const spanX = s => PADL + (s / DT - w0) / (w1 - w0) * plotW;
  const clip = x => Math.max(PADL, Math.min(W - PADR, x));
  for (const [a, b] of ch.gaps) {
    const x1 = clip(spanX(a)), x2 = clip(spanX(b));
    if (x2 > x1) { g.fillStyle = "rgba(232,179,75,.28)"; g.fillRect(x1, PADT, x2 - x1, plotH); }
  }
  const pat = g.createPattern(hatchTile, "repeat");
  for (const [a, b] of ch.overlaps) {
    const x1 = clip(spanX(a)), x2 = clip(spanX(b));
    if (x2 > x1) { g.fillStyle = pat; g.globalAlpha = .5; g.fillRect(x1, PADT, x2 - x1, plotH); g.globalAlpha = 1; }
  }

  // grid + y labels
  g.font = "10.5px " + getComputedStyle(document.body).getPropertyValue("--mono");
  g.fillStyle = "#5b6b7b"; g.strokeStyle = "#eceff3"; g.textAlign = "right"; g.textBaseline = "middle";
  for (const v of niceTicks(vmax / 1.08)) {
    const y = yOf(v);
    g.beginPath(); g.moveTo(PADL, y); g.lineTo(W - PADR, y); g.stroke();
    g.fillText(v >= 1000 ? (v / 1000) + "k" : String(Math.round(v * 100) / 100), PADL - 6, y);
  }
  // x labels
  g.textAlign = "center"; g.textBaseline = "top";
  const secs = (w1 - w0) * DT;
  const xstep = secs > 3000 ? 600 : secs > 1200 ? 300 : secs > 300 ? 60 : secs > 60 ? 15 : 5;
  for (let s = Math.ceil(tOf(w0) / xstep) * xstep; s <= tOf(w1); s += xstep)
    g.fillText(fmt(s), spanX(s), H - PADB + 4);

  // data: envelope when >2 samples per px, else polyline
  const perPx = (w1 - w0) / plotW;
  g.strokeStyle = ch.color; g.fillStyle = ch.color;
  if (perPx > 2) {
    g.globalAlpha = .85;
    for (let px = 0; px < plotW; px++) {
      const i0 = Math.floor(w0 + px * perPx), i1 = Math.min(w1, Math.floor(w0 + (px + 1) * perPx));
      let lo = Infinity, hi = -Infinity;
      for (let i = i0; i <= i1; i++) { const v = ch.values[i]; if (v == null) continue;
        if (v < lo) lo = v; if (v > hi) hi = v; }
      if (lo <= hi) g.fillRect(PADL + px, yOf(hi), 1, Math.max(1, yOf(lo) - yOf(hi)));
    }
    g.globalAlpha = 1;
  } else {
    g.lineWidth = perPx < .12 ? 2 : 1.4; g.beginPath();
    let pen = false;
    for (let i = w0; i <= w1; i++) {
      const v = ch.values[i];
      if (v == null) { pen = false; continue; }
      const x = xOf(i), y = yOf(v);
      pen ? g.lineTo(x, y) : g.moveTo(x, y); pen = true;
    }
    g.stroke();
    if (perPx < .12) {           // deep zoom: mark individual seconds
      for (let i = w0; i <= w1; i++) { const v = ch.values[i]; if (v == null) continue;
        g.beginPath(); g.arc(xOf(i), yOf(v), 2.4, 0, 7); g.fill(); }
    }
  }

  // cursors
  const drawCursor = (i, color, dash) => {
    if (i == null || i < w0 || i > w1) return;
    g.strokeStyle = color; g.lineWidth = 1; g.setLineDash(dash);
    g.beginPath(); g.moveTo(xOf(i), PADT); g.lineTo(xOf(i), H - PADB); g.stroke(); g.setLineDash([]);
    const v = ch.values[i];
    if (v != null) { g.fillStyle = color; g.beginPath(); g.arc(xOf(i), yOf(v), 3.2, 0, 7); g.fill(); }
  };
  pins.forEach((p, k) => drawCursor(p, k ? "#7a3b9b" : "#1d5bd8", []));
  drawCursor(hover, "#5b6b7b", [3, 3]);

  // drag-zoom selection
  if (o.drag != null && o.dragEnd != null) {
    g.fillStyle = "rgba(29,91,216,.12)";
    g.fillRect(Math.min(o.drag, o.dragEnd), PADT, Math.abs(o.dragEnd - o.drag), plotH);
  }
}

function readout() {
  const el = document.getElementById("readout");
  const row = i => D.channels.map(ch =>
    '<span style="color:' + ch.color + '">' + ch.key + ' <b>' + fmtv(ch.values[i]) + '</b></span>').join("");
  let html = "";
  if (hover != null) html += '<span class="t">t ' + fmt(tOf(hover)) + '</span>' + row(hover);
  pins.forEach((p, k) => {
    html += '<span class="pin">| pin' + (k + 1) + '</span><span class="t">' + fmt(tOf(p)) + '</span>' + row(p);
  });
  if (pins.length === 2) {
    const [a, b] = [...pins].sort((x, y) => x - y);
    html += '<span class="pin">| &Delta;t ' + fmt(tOf(b) - tOf(a)) + '</span>' +
      D.channels.map(ch => {
        const va = ch.values[a], vb = ch.values[b];
        return '<span style="color:' + ch.color + '">&Delta; <b>' +
               (va == null || vb == null ? "—" : fmtv(vb - va)) + '</b></span>';
      }).join("");
  }
  el.innerHTML = html || '<span class="pin">Hover a chart&hellip;</span>';
}

function drawAll() { charts.forEach(drawChart); readout(); }
D.channels.forEach(makeChart);
window.addEventListener("resize", drawAll);
drawAll();
</script>
</body>
</html>
"""
