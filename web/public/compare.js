(() => {
'use strict';
// The compare window: wells stacked one above another, each drawn on the same
// axis so the rows read against each other. Opened from a well view, which
// hands wells over through localStorage (so the window can be reloaded or
// opened cold) and a BroadcastChannel (so an already-open window updates).
//
// Nothing is aggregated or resampled across wells. Each row is that well's own
// stages at their own depths; a channel a well does not carry is disabled for
// that well rather than drawn as zero.

const KEY = 'stratum.compare';
const chan = 'BroadcastChannel' in self ? new BroadcastChannel('stratum-compare') : null;
const $ = id => document.getElementById(id);

const COLOURS = ['#4d8dff', '#ff8a4d', '#3ecf8e', '#e35d9a', '#f2c94c',
                 '#8f6bff', '#4dd0e1', '#ff6b6b', '#9ccc65', '#ba68c8'];

// curve channels come from the per-second export; metrics from the stage table
const CHANNELS = {
  press:    { label: 'Treating pressure', short: 'Press',   unit: 'MPa',    kind: 'curve',  colour: '#ff6b6b' },
  rate:     { label: 'Slurry rate',       short: 'Rate',    unit: 'm³/min', kind: 'curve',  colour: '#4d8dff' },
  wh_conc:  { label: 'WH proppant conc',  short: 'WH',      unit: 'kg/m³',  kind: 'curve',  colour: '#3ecf8e' },
  bh_conc:  { label: 'BH proppant conc',  short: 'BH',      unit: 'kg/m³',  kind: 'curve',  colour: '#c79bff' },
  proppant_t:       { label: 'Proppant placed', short: 'Prop t',   unit: 't',   kind: 'metric', colour: '#f2c94c' },
  avg_pressure_mpa: { label: 'Average pressure', short: 'Avg P',   unit: 'MPa', kind: 'metric', colour: '#ff9f6b' },
  avg_rate_m3_min:  { label: 'Average rate', short: 'Avg rate', unit: 'm³/min', kind: 'metric', colour: '#7fd1ff' },
};
const on = { press: true, rate: false, wh_conc: false, bh_conc: false,
             proppant_t: true, avg_pressure_mpa: false, avg_rate_m3_min: false };

let wells = [];              // {wa, doc, colour, off:Set}
let axis = 'md', shared = true;

const num = v => (v == null || v === '' || Number.isNaN(+v)) ? null : +v;
const fmt = (v, d = 0) => v == null ? '–' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d });

function listFromStorage() {
  try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch (e) { return []; }
}
function saveList() {
  try { localStorage.setItem(KEY, JSON.stringify(wells.map(w => w.wa))); } catch (e) {}
}

async function addWell(wa) {
  wa = String(wa);
  if (wells.some(w => w.wa === wa)) return;
  let doc;
  try { doc = await (await fetch(`data/wells/${encodeURIComponent(wa)}.json`)).json(); }
  catch (e) { return; }
  wells.push({ wa, doc, colour: COLOURS[wells.length % COLOURS.length], off: new Set() });
  saveList(); renderAll();
}

function removeWell(wa) {
  wells = wells.filter(w => w.wa !== wa);
  wells.forEach((w, i) => { w.colour = COLOURS[i % COLOURS.length]; });
  saveList(); renderAll();
}

// ------------------------------------------------------- what a well carries
function stagesOf(w) {
  return (w.doc.stages || []).slice().sort((a, b) => (a.n || 0) - (b.n || 0));
}
function engOf(w) {
  const m = new Map();
  for (const e of w.doc.engineering_stages || []) {
    m.set(String(e.label), e);
    if (!m.has('n:' + e.n)) m.set('n:' + e.n, e);
  }
  return m;
}
function has(w, key) {
  const c = CHANNELS[key];
  if (c.kind === 'curve') {
    return stagesOf(w).some(s => s.series && Array.isArray(s.series[key]) && s.series[key].some(v => v != null));
  }
  return (w.doc.engineering_stages || []).some(e => num(e[key]) != null);
}
function active(w, key) { return on[key] && has(w, key) && !w.off.has(key); }

// value of a metric per stage, and the curve samples per stage
function seriesFor(w) {
  const eng = engOf(w);
  return stagesOf(w).map(s => ({
    s, eng: eng.get(String(s.label)) || eng.get('n:' + s.n) || {},
  }));
}

// ------------------------------------------------------------------ domains
function domain() {
  if (axis === 'stage') {
    const n = Math.max(1, ...wells.map(w => stagesOf(w).length));
    return [1, n];
  }
  let lo = Infinity, hi = -Infinity;
  for (const w of wells) for (const s of stagesOf(w)) {
    const v = num(s.top_m); if (v == null) continue;
    if (v < lo) lo = v; if (v > hi) hi = v;
  }
  if (!Number.isFinite(lo)) return [0, 1];
  const pad = (hi - lo) * 0.02 || 1;
  return [lo - pad, hi + pad];
}

// one vertical scale per channel; shared across wells when asked, so the rows
// can actually be read against each other
function ranges() {
  const out = {};
  for (const key of Object.keys(CHANNELS)) {
    if (!on[key]) continue;
    const c = CHANNELS[key];
    const per = new Map();
    for (const w of wells) {
      if (!active(w, key)) continue;
      let hi = -Infinity, lo = Infinity;
      for (const { s, eng } of seriesFor(w)) {
        if (c.kind === 'curve') {
          const a = s.series && s.series[key];
          if (Array.isArray(a)) for (const v of a) if (v != null) { if (v > hi) hi = v; if (v < lo) lo = v; }
        } else {
          const v = num(eng[key]); if (v != null) { if (v > hi) hi = v; if (v < lo) lo = v; }
        }
      }
      if (Number.isFinite(hi)) per.set(w.wa, [Math.min(0, lo), hi]);
    }
    if (shared && per.size) {
      const lo = Math.min(...[...per.values()].map(r => r[0]));
      const hi = Math.max(...[...per.values()].map(r => r[1]));
      for (const k of per.keys()) per.set(k, [lo, hi]);
    }
    out[key] = per;
  }
  return out;
}

// --------------------------------------------------------------------- draw
function drawRow(cnv, w, dom, rng) {
  const g = cnv.getContext('2d');
  const dpr = Math.min(devicePixelRatio || 1, 2);
  const r = cnv.getBoundingClientRect();
  cnv.width = Math.max(1, Math.round(r.width * dpr));
  cnv.height = Math.max(1, Math.round(r.height * dpr));
  g.clearRect(0, 0, cnv.width, cnv.height);
  const L = 44 * dpr, R = 12 * dpr, T = 10 * dpr, B = 20 * dpr;
  const rows = seriesFor(w);
  const X = v => L + (v - dom[0]) / ((dom[1] - dom[0]) || 1) * (cnv.width - L - R);
  const Y = (v, rr) => cnv.height - B - (v - rr[0]) / ((rr[1] - rr[0]) || 1) * (cnv.height - T - B);

  // baseline + depth ticks
  g.strokeStyle = '#172836'; g.lineWidth = 1 * dpr;
  g.beginPath(); g.moveTo(L, cnv.height - B); g.lineTo(cnv.width - R, cnv.height - B); g.stroke();
  g.fillStyle = '#5d7585'; g.font = `${10 * dpr}px ui-monospace,Menlo,monospace`;
  for (let i = 0; i <= 4; i++) {
    const v = dom[0] + (dom[1] - dom[0]) * i / 4;
    const x = X(v);
    g.strokeStyle = '#122230'; g.beginPath(); g.moveTo(x, T); g.lineTo(x, cnv.height - B); g.stroke();
    g.textAlign = i === 0 ? 'left' : i === 4 ? 'right' : 'center';
    g.fillText(axis === 'md' ? fmt(v) : fmt(v, 0), x, cnv.height - 6 * dpr);
  }
  g.textAlign = 'left';

  const xOf = (s, i) => axis === 'stage' ? X(i + 1) : (num(s.top_m) == null ? null : X(num(s.top_m)));
  // slot width: how much room one stage gets for its own trace
  const xs = rows.map((d, i) => xOf(d.s, i)).filter(v => v != null).sort((a, b) => a - b);
  let slot = (cnv.width - L - R) / Math.max(1, rows.length);
  for (let i = 1; i < xs.length; i++) slot = Math.min(slot, Math.abs(xs[i] - xs[i - 1]));
  slot = Math.max(slot, 2 * dpr);

  let drew = false, lab = 0;
  for (const key of Object.keys(CHANNELS)) {
    if (!active(w, key)) continue;
    const rr = (rng[key] && rng[key].get(w.wa)) || null;
    if (!rr) continue;
    const c = CHANNELS[key];
    g.strokeStyle = c.colour; g.fillStyle = c.colour;
    if (c.kind === 'curve') {
      // each stage's own samples, laid inside that stage's slot
      g.lineWidth = 1 * dpr;
      rows.forEach((d, i) => {
        const a = d.s.series && d.s.series[key];
        if (!Array.isArray(a) || !a.some(v => v != null)) return;
        const x0 = xOf(d.s, i); if (x0 == null) return;
        const left = x0 - slot * 0.45;
        g.beginPath(); let pen = false;
        for (let k = 0; k < a.length; k++) {
          if (a[k] == null) { pen = false; continue; }   // gaps stay gaps
          const px = left + (k / Math.max(1, a.length - 1)) * slot * 0.9;
          const py = Y(a[k], rr);
          if (!pen) { g.moveTo(px, py); pen = true; } else g.lineTo(px, py);
        }
        g.stroke(); drew = true;
      });
    } else {
      // one point per stage, joined -- the reported number along the well
      g.lineWidth = 1.6 * dpr; g.beginPath(); let pen = false;
      rows.forEach((d, i) => {
        const v = num(d.eng[key]); const x = xOf(d.s, i);
        if (v == null || x == null) { pen = false; return; }
        const py = Y(v, rr);
        if (!pen) { g.moveTo(x, py); pen = true; } else g.lineTo(x, py);
      });
      g.stroke();
      rows.forEach((d, i) => {
        const v = num(d.eng[key]); const x = xOf(d.s, i);
        if (v == null || x == null) return;
        g.beginPath(); g.arc(x, Y(v, rr), 2 * dpr, 0, 7); g.fill(); drew = true;
      });
    }
    // each drawn channel's top-of-scale, stacked down the left edge
    g.fillStyle = c.colour; g.font = `${9.5 * dpr}px ui-monospace,Menlo,monospace`;
    g.fillText(`${fmt(rr[1], 1)} ${c.unit}`, 4 * dpr, T + 8 * dpr + lab * 11 * dpr);
    lab++;
  }
  if (!drew) {
    g.fillStyle = '#6d8794'; g.font = `${12 * dpr}px -apple-system,Segoe UI,sans-serif`;
    g.textAlign = 'center';
    g.fillText('none of the selected channels are held for this well', cnv.width / 2, cnv.height / 2);
    g.textAlign = 'left';
  }
}

// ------------------------------------------------------------------- render
function renderSide() {
  $('cmp-channels').innerHTML = Object.entries(CHANNELS).map(([k, c]) =>
    `<label class="tog"><input type="checkbox" data-ch="${k}" ${on[k] ? 'checked' : ''}>
       <i style="background:${c.colour}"></i>${c.label} <span style="color:var(--c-mut);font-size:11px">${c.unit}</span></label>`).join('');
  $('cmp-channels').querySelectorAll('input').forEach(i => i.onchange = () => { on[i.dataset.ch] = i.checked; renderRows(); renderSide(); });

  $('cmp-wells').innerHTML = wells.length ? wells.map(w => {
    const st = stagesOf(w);
    const curves = st.filter(s => s.series && Object.keys(s.series).length).length;
    return `<div class="cmp-well" data-wa="${w.wa}">
      <div class="top"><span class="sw" style="background:${w.colour}"></span>
        <span class="nm" title="${w.doc.well.name}">${w.doc.well.name}</span>
        <button class="x" data-rm="${w.wa}" title="Remove">×</button></div>
      <div class="meta">WA ${w.wa} · ${st.length} stages · ${curves} with curves</div>
      <div class="chans">${Object.entries(CHANNELS).map(([k, c]) => {
        const held = has(w, k);
        return `<button data-w="${w.wa}" data-k="${k}" ${held ? '' : 'disabled'}
                 class="${held && !w.off.has(k) && on[k] ? 'on' : ''}"
                 title="${held ? c.label : c.label + ' — not held for this well'}">${c.short}</button>`;
      }).join('')}</div></div>`;
  }).join('') : '<div class="cmp-empty" style="padding:8px 0">Open a well and choose “Add to compare”.</div>';

  $('cmp-wells').querySelectorAll('[data-rm]').forEach(b => b.onclick = () => removeWell(b.dataset.rm));
  $('cmp-wells').querySelectorAll('[data-k]').forEach(b => b.onclick = () => {
    const w = wells.find(x => x.wa === b.dataset.w); if (!w) return;
    w.off.has(b.dataset.k) ? w.off.delete(b.dataset.k) : w.off.add(b.dataset.k);
    renderSide(); renderRows();
  });
}

function renderRows() {
  const box = $('cmp-rows');
  if (!wells.length) {
    box.innerHTML = '<div class="cmp-empty">No wells yet.<br>Open a well view and press “Add to compare”. Wells stack here, drawn on one shared axis.</div>';
    $('cmp-sub').textContent = 'no wells added';
    $('cmp-foot').textContent = '';
    return;
  }
  const dom = domain(), rng = ranges();
  box.innerHTML = wells.map(w => {
    const st = stagesOf(w);
    return `<div class="cmp-row"><header>
      <span class="sw" style="background:${w.colour}"></span>
      <span>${w.doc.well.name}</span>
      <span class="m">${st.length} stages · MD ${fmt(w.doc.well.td_m)} m · lateral ${fmt(w.doc.well.lateral_m)} m</span>
      </header><canvas data-wa="${w.wa}"></canvas></div>`;
  }).join('');
  box.querySelectorAll('canvas').forEach(c => {
    const w = wells.find(x => x.wa === c.dataset.wa);
    if (w) drawRow(c, w, dom, rng);
  });
  $('cmp-sub').textContent = `${wells.length} well${wells.length > 1 ? 's' : ''} · ${axis === 'md' ? 'measured depth' : 'stage number'} axis · ${shared ? 'shared' : 'per-well'} scale`;
  $('cmp-foot').textContent = axis === 'md'
    ? 'Each stage is drawn at its own measured depth; curve samples are laid inside that stage’s slot. Gaps in the source stay gaps, and a channel a well does not hold is left out rather than drawn as zero.'
    : 'Stages are placed by number, so wells with different stage counts line up at the start, not by depth.';
}

function renderAll() { renderSide(); renderRows(); }

// ----------------------------------------------------------------- controls
document.querySelectorAll('input[name=axis]').forEach(i => i.onchange = () => { axis = i.value; renderRows(); });
$('cmp-shared').onchange = e => { shared = e.target.checked; renderRows(); };
$('cmp-clear').onclick = () => { wells = []; saveList(); renderAll(); };
addEventListener('resize', renderRows);
if (chan) chan.onmessage = e => {
  if (e.data && e.data.type === 'add') addWell(e.data.wa);
  if (e.data && e.data.type === 'clear') { wells = []; saveList(); renderAll(); }
};
addEventListener('storage', e => { if (e.key === KEY) sync(); });

async function sync() {
  const want = listFromStorage().map(String);
  for (const wa of want) await addWell(wa);
  if (wells.some(w => !want.includes(w.wa))) {
    wells = wells.filter(w => want.includes(w.wa));
    wells.forEach((w, i) => { w.colour = COLOURS[i % COLOURS.length]; });
    renderAll();
  }
}

(async () => { renderAll(); await sync(); })();
})();
