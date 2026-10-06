// FracView Discover: tools for an engineer to narrow the region's wells down to
// the ones that matter for a question. Loaded by the main menu (menu.js) when
// Discover is opened; the tables come from web/scripts/build_discover.py.
//
//   Well finder                 every well, filtered by what was pumped, where and how it produced
//   Completion vs production    any two measures against each other, by operator, with the trend
//   Earthquakes at stages       events that coincided with a stage: magnitude, timing, distance
//   Well spacing                each lateral's nearest neighbour, across and vertically
//
// The finder's filters are shared with the chart and spacing tools, and kept for
// this window (sessionStorage), so moving between tools keeps the question.
(() => {
'use strict';
const STATE_KEY = 'fv.discover';
let wellsP = null, spacingP = null, eventsP = null;
const getJSON = u => fetch(u).then(r => { if (!r.ok) throw Error('Discover’s data is not available yet.'); return r.json(); });
const wells = () => wellsP || (wellsP = getJSON('data/discover/wells.json').then(d => d.rows.map(r => Object.fromEntries(d.columns.map((c, i) => [c, r[i]])))));
const spacing = () => spacingP || (spacingP = getJSON('data/discover/spacing.json').then(d => d.wells));
const events = () => eventsP || (eventsP = getJSON('data/seismic/events.json'));

// the measures, as people read them
const COL = {
  name: { t: 'Well' }, wa: { t: 'WA' }, padName: { t: 'Pad' }, operator: { t: 'Operator' }, formation: { t: 'Formation' }, field: { t: 'Field' },
  year: { t: 'Year', n: 1, d: 0, plain: 1 }, lateral: { t: 'Lateral', u: 'm', n: 1, d: 0 }, tvd: { t: 'TVD', u: 'm', n: 1, d: 0 },
  stages: { t: 'Stages', n: 1, d: 0 }, stageSpacing: { t: 'Stage spacing', u: 'm', n: 1, d: 0 },
  proppant: { t: 'Proppant', u: 't', n: 1, d: 0 }, proppantPerM: { t: 'Proppant intensity', u: 't/m', n: 1, d: 2 },
  fluid: { t: 'Fluid', u: 'm³', n: 1, d: 0 }, fluidPerM: { t: 'Fluid intensity', u: 'm³/m', n: 1, d: 1 },
  rate: { t: 'Rate (median)', u: 'm³/min', n: 1, d: 1 }, avgP: { t: 'Avg treating pressure', u: 'MPa', n: 1, d: 1 }, maxP: { t: 'Peak pressure', u: 'MPa', n: 1, d: 1 },
  isip: { t: 'ISIP', u: 'MPa', n: 1, d: 1 }, breakdown: { t: 'Breakdown', u: 'MPa', n: 1, d: 1 }, gamma: { t: 'Landing gamma', u: 'API', n: 1, d: 0 },
  gas: { t: 'Cumulative gas', u: 'e³m³', n: 1, d: 0 }, gasPerM: { t: 'Gas per lateral metre', u: 'e³m³/m', n: 1, d: 1 },
  nnH: { t: 'Nearest lateral, across', u: 'm', n: 1, d: 0 }, nnV: { t: 'Nearest lateral, vertical', u: 'm', n: 1, d: 0 }, quakes: { t: 'Earthquakes at stages', n: 1, d: 0 },
};
const label = k => COL[k].t + (COL[k].u ? ` (${COL[k].u})` : '');
const SHORT = { 'Canadian Natural Resources Limited': 'CNRL', 'Pacific Canbriam Energy Limited': 'Pacific Canbriam', 'Petronas Energy Canada Ltd.': 'Petronas',
                'ConocoPhillips Canada Resources Corp.': 'ConocoPhillips', 'Tourmaline Oil Corp.': 'Tourmaline', 'ARC Resources Ltd.': 'ARC' };
const short = op => !op ? 'Not filed' : SHORT[op] || op.replace(/\s+(Ltd\.?|Limited|Inc\.?|Corp\.?|Corporation|Canada|Energy|Resources|Exploration|Oil|Partnership).*$/i, '');
const RANGES = [['year', 'Year'], ['lateral', 'Lateral (m)'], ['stageSpacing', 'Stage spacing (m)'], ['proppantPerM', 'Proppant (t/m)'], ['fluidPerM', 'Fluid (m³/m)'],
                ['avgP', 'Avg treating pressure (MPa)'], ['isip', 'ISIP (MPa)'], ['gamma', 'Landing gamma (API)'], ['gasPerM', 'Gas per metre (e³m³/m)'], ['nnH', 'Nearest lateral across (m)']];

function loadState() { try { return JSON.parse(sessionStorage.getItem(STATE_KEY) || '{}') || {}; } catch (e) { return {}; } }
const state = Object.assign({ tool: 'finder', q: '', operator: '', formation: '', field: '', curves: false, quakes: false, ranges: {},
  sort: 'proppantPerM', dir: -1, x: 'proppantPerM', y: 'gasPerM', color: 'operator', minMag: 1, timing: 'all', maxKm: 5, spacingMax: 400, samePad: false, zone: true }, loadState());
const saveState = () => { try { sessionStorage.setItem(STATE_KEY, JSON.stringify(state)); } catch (e) { /* private mode */ } };

const TOOLS = [
  ['finder', 'Well finder', 'Every well in the region, narrowed by what was pumped, where it landed and how it produced.'],
  ['scatter', 'Completion vs production', 'Any two measures against each other, by operator, with the median trend.'],
  ['quakes', 'Earthquakes at stages', 'Earthquakes that coincided with a frac stage: magnitude, timing, distance. Opens the stage.'],
  ['spacing', 'Well spacing', 'Each lateral’s nearest neighbour, across and up or down. Opens the wine rack.'],
];

function pass(w, s = state) {
  if (s.q) { const q = s.q.toLowerCase(); if (!(`${w.name} ${w.wa} ${w.padName} ${w.field || ''}`.toLowerCase().includes(q))) return false; }
  if (s.operator && w.operator !== s.operator) return false;
  if (s.formation && w.formation !== s.formation) return false;
  if (s.field && w.field !== s.field) return false;
  if (s.curves && !w.curves) return false;
  if (s.quakes && !w.quakes) return false;
  for (const [k, r] of Object.entries(s.ranges || {})) {
    if (r.min != null && !(w[k] != null && w[k] >= r.min)) return false;
    if (r.max != null && !(w[k] != null && w[k] <= r.max)) return false;
  }
  return true;
}
const median = xs => { const v = xs.filter(x => x != null && isFinite(x)).sort((a, b) => a - b); return v.length ? v[Math.floor((v.length - 1) / 2)] : null; };
function niceStep(span, n) { const raw = span / Math.max(1, n), p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p; }
const csvCell = v => v == null ? '' : /[",\n]/.test(String(v)) ? '"' + String(v).replace(/"/g, '""') + '"' : String(v);
function download(name, cols, rows) {
  const text = [cols.map(c => COL[c] ? label(c) : c).map(csvCell).join(','), ...rows.map(r => cols.map(c => csvCell(r[c])).join(','))].join('\n');
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type: 'text/csv' })); a.download = name;
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}
const letters = () => Array.from({ length: 6 }, () => String.fromCharCode(97 + Math.floor(Math.random() * 26))).join('');
const openCharts = (wa, stage) => window.open(`wellview.html?wa=${encodeURIComponent(wa)}${stage ? '&stage=' + encodeURIComponent(stage) : ''}`, 'stratum-charts', 'popup,width=1280,height=860');
const openStage = (wa, stage) => window.open(`stages.html?s=${encodeURIComponent(wa)}:${encodeURIComponent(stage)}`, 'stratum-stages' + letters(), 'popup,width=1180,height=820');

function render(box, ctx) {
  const { h, fmt } = ctx;
  const nav = h('div', { class: 'fvm-items' });
  const pane = h('div', { class: 'fvm-detail' });
  box.append(h('div', { class: 'fvm-list' }, h('div', { class: 'fvm-list-head' }, h('h1', { text: 'Discover' }),
    h('p', { class: 'fvm-sub', style: 'margin:0', text: 'The region’s wells as filed with the BC Energy Regulator, for finding the ones that answer a question. More to come as data is added.' })), nav), pane);
  if (ctx.tool) state.tool = ctx.tool;
  const drawNav = () => nav.replaceChildren(...TOOLS.map(([id, t, d]) => h('button', { type: 'button', class: 'fvm-item', 'aria-selected': String(state.tool === id),
    onclick: () => { state.tool = id; saveState(); drawNav(); tool(); } }, h('b', { text: t }), h('span', { text: d, style: 'white-space:normal' }))));
  drawNav();
  const tool = () => {
    ctx.hideTip();
    pane.replaceChildren(h('div', { class: 'fvm-empty', text: 'Loading the region’s wells…' }));
    Promise.all([wells(), state.tool === 'spacing' ? spacing() : null, state.tool === 'quakes' ? events() : null])
      .then(([W, S, E]) => { pane.replaceChildren(); ({ finder, scatter, quakes, spacingTool }[state.tool === 'spacing' ? 'spacingTool' : state.tool])(pane, W, ctx, S, E); })
      .catch(e => pane.replaceChildren(h('div', { class: 'fvm-empty', text: e.message })));
  };
  tool();
}

// ---------- the filters every tool but the earthquakes shares ----------
function filters(W, ctx, onChange, opts = {}) {
  const { h } = ctx;
  const opts_ = k => [...new Set(W.map(w => w[k]).filter(Boolean))].sort((a, b) => W.filter(w => w[k] === b).length - W.filter(w => w[k] === a).length);
  const sel = (k, all) => { const s = h('select', { 'aria-label': k, onchange: e => { state[k] = e.target.value; changed(); } }, h('option', { value: '', text: all }), opts_(k).map(v => h('option', { value: v, text: k === 'operator' ? short(v) : v })));
    s.value = state[k] || ''; return s; };
  let t = 0;
  const changed = () => { clearTimeout(t); t = setTimeout(() => { saveState(); onChange(); }, 120); };
  const range = (k, lab) => {
    const r = state.ranges[k] || {}, mk = (which, ph) => h('input', { type: 'number', step: 'any', placeholder: ph, value: r[which] ?? '', 'aria-label': `${lab} ${which}`,
      oninput: e => { const cur = state.ranges[k] || {}; cur[which] = e.target.value === '' ? null : +e.target.value; if (cur.min == null && cur.max == null) delete state.ranges[k]; else state.ranges[k] = cur; changed(); } });
    return h('label', null, lab, h('div', { class: 'fvm-pair' }, mk('min', 'min'), mk('max', 'max')));
  };
  const box = h('div', { class: 'fvm-filters' },
    h('label', null, 'Search', h('input', { type: 'search', placeholder: 'Well, WA, pad or field', value: state.q, oninput: e => { state.q = e.target.value.trim(); changed(); } })),
    h('label', null, 'Operator', sel('operator', 'All operators')),
    h('label', null, 'Formation', sel('formation', 'All formations')),
    h('label', null, 'Field', sel('field', 'All fields')),
    ...RANGES.filter(([k]) => !(opts.skip || []).includes(k)).map(([k, l]) => range(k, l)),
    h('div', { class: 'wide' },
      h('label', { class: 'fvm-check', style: 'margin:0' }, h('input', { type: 'checkbox', checked: state.curves, onchange: e => { state.curves = e.target.checked; changed(); } }), h('span', { text: 'Only wells with treatment charts' })),
      h('label', { class: 'fvm-check', style: 'margin:0' }, h('input', { type: 'checkbox', checked: state.quakes, onchange: e => { state.quakes = e.target.checked; changed(); } }), h('span', { text: 'Only wells with an earthquake at a stage' })),
      h('button', { type: 'button', text: 'Clear filters', onclick: () => { Object.assign(state, { q: '', operator: '', formation: '', field: '', curves: false, quakes: false, ranges: {} }); saveState(); ctx.show('discover', { tool: state.tool }); } })));
  return box;
}
// the same filters folded away under what they are set to, for tools whose answer comes first
function folded(W, ctx, onChange, opts) {
  const { h } = ctx;
  const words = () => {
    const bits = [state.q && `“${state.q}”`, state.operator && short(state.operator), state.formation, state.field, state.curves && 'with charts', state.quakes && 'with earthquakes',
      ...Object.entries(state.ranges || {}).map(([k, r]) => `${(COL[k] || { t: k }).t.toLowerCase()} ${r.min != null ? '≥ ' + r.min : ''}${r.min != null && r.max != null ? ', ' : ''}${r.max != null ? '≤ ' + r.max : ''}`)].filter(Boolean);
    return bits.length ? 'Filtered: ' + bits.join(' · ') : 'Filter the wells (all of them now)';
  };
  const sum = h('summary', { text: words(), style: 'cursor:pointer;font-weight:600;font-size:.9em;margin:0 0 .6em' });
  const box = h('details', { style: 'margin-top:1em' }, sum, filters(W, ctx, () => { sum.textContent = words(); onChange(); }, opts));
  return box;
}

// what can be done with a set of wells: the map, a group, a file
function actions(rows, ctx, name) {
  const { h } = ctx;
  const msg = h('span', { class: 'fvm-msg', role: 'status' });
  const pads = [...new Set(rows.map(w => w.pad))];
  return h('div', { class: 'fvm-count' },
    h('button', { type: 'button', class: 'go', text: 'Show on the map', disabled: !rows.length, title: rows.length > 1500 ? 'The first 1,500' : null,
      onclick: () => ctx.toMap({ wells: rows.slice(0, 1500).map(w => w.wa), title: name }) }),
    h('button', { type: 'button', text: `Save their ${fmtN(pads.length)} pad${pads.length === 1 ? '' : 's'} as a group`, disabled: !pads.length || pads.length > 80,
      title: pads.length > 80 ? 'A group holds up to 80 pads: narrow the filters' : null,
      onclick: async () => { const n = prompt('Name the group', name); if (!n) return; try { const g = await ctx.saveGroup({ name: n, pads, note: `From Discover: ${rows.length} wells` }); msg.textContent = `Saved “${g.name}”.`; } catch (e) { msg.textContent = e.message; } } }),
    h('button', { type: 'button', text: 'Download CSV', disabled: !rows.length, onclick: () => download('fracview-wells.csv', ['wa', 'name', 'padName', 'operator', 'formation', 'field', 'year', ...Object.keys(COL).filter(k => COL[k].n && k !== 'year')], rows) }),
    msg);
}
const fmtN = n => Number(n).toLocaleString();

// a sortable table; `cols` keys of COL, `onRow` for a click
function table(rows, cols, ctx, onRow, limit = 300) {
  const { h, fmt } = ctx;
  const t = h('table', { class: 'fvm-table' });
  const draw = () => {
    const k = cols.includes(state.sort) ? state.sort : cols.find(c => COL[c] && COL[c].n) || cols[0], dir = state.dir || -1;
    const sorted = rows.slice().sort((a, b) => { const x = a[k], y = b[k]; if (x == null) return 1; if (y == null) return -1; return (x > y ? 1 : x < y ? -1 : 0) * dir; });
    t.replaceChildren(
      h('thead', null, h('tr', null, cols.map(c => h('th', { class: COL[c] && COL[c].n ? 'num' : null, 'aria-sort': c === k ? (dir > 0 ? 'ascending' : 'descending') : null },
        h('button', { type: 'button', text: (COL[c] ? COL[c].t : c) + (c === k ? (dir > 0 ? ' ↑' : ' ↓') : ''), title: COL[c] && COL[c].u ? COL[c].u : null,
          onclick: () => { state.dir = state.sort === c ? -(state.dir || -1) : (COL[c] && COL[c].n ? -1 : 1); state.sort = c; saveState(); draw(); } }))))),
      h('tbody', null, sorted.slice(0, limit).map(r => h('tr', { onclick: e => onRow(r, e) }, cols.map(c => {
        const v = r[c], m = COL[c];
        // a well's name without the operator and "HZ" in front, as the map's list has it
        const nm = (c === 'name' || c === 'nbName') && v ? String(v).replace(/^\S+(\s+\S+)?\s+HZ\s+/i, '') : null;
        return h('td', { class: m && m.n ? 'num' : null, title: c === 'operator' || nm ? `${v}${r.wa && c === 'name' ? ' · WA ' + r.wa : ''}` : null,
          text: nm || (c === 'operator' ? short(v) : m && m.n ? (m.plain ? (v ?? '–') : fmt(v, m.d)) : (v ?? '–')) });
      })))));
  };
  draw();
  return h('div', { class: 'fvm-tablewrap' }, t);
}
// a well's next steps, at the pointer
function wellMenu(w, e, ctx) {
  const { h } = ctx;
  document.querySelectorAll('.fvm-pop').forEach(x => x.remove());
  const pop = h('div', { class: 'fvm-card fvm-pop', role: 'menu', style: 'position:fixed;z-index:215;padding:.5em;display:flex;flex-direction:column;gap:.35em;min-width:14em;box-shadow:0 10px 26px rgba(0,0,0,.18)' },
    h('b', { text: w.name, style: 'font-size:.85em;padding:.2em .3em' }),
    h('button', { type: 'button', class: 'go', text: 'Show it on the map', onclick: () => { pop.remove(); ctx.toMap({ wells: [w.wa], wa: w.wa, title: w.name }); } }),
    w.curves ? h('button', { type: 'button', text: 'Its treatment charts ↗', onclick: () => { pop.remove(); openCharts(w.wa); } }) : null,
    h('button', { type: 'button', text: 'Its pad’s wine rack ↗', onclick: () => { pop.remove(); ctx.toMap({ pads: [w.pad], racks: true, title: w.padName }); } }));
  document.querySelector('.fvm').append(pop);
  pop.style.left = Math.min(innerWidth - pop.offsetWidth - 8, e.clientX + 6) + 'px';
  pop.style.top = Math.min(innerHeight - pop.offsetHeight - 8, e.clientY + 6) + 'px';
  const off = ev => { if (!pop.contains(ev.target)) { pop.remove(); document.removeEventListener('pointerdown', off, true); } };
  setTimeout(() => document.addEventListener('pointerdown', off, true));
  pop.querySelector('button').focus();
}

// ---------- Well finder ----------
function finder(pane, W, ctx) {
  const { h, fmt } = ctx;
  const out = h('div');
  const draw = () => {
    const rows = W.filter(w => pass(w));
    const med = k => median(rows.map(w => w[k]));
    out.replaceChildren(
      h('div', { class: 'fvm-count' }, h('b', { text: `${fmtN(rows.length)} of ${fmtN(W.length)} wells` }),
        h('span', { class: 'fvm-pill', text: `median ${fmt(med('proppantPerM'), 2)} t/m` }), h('span', { class: 'fvm-pill', text: `${fmt(med('stageSpacing'))} m stage spacing` }),
        h('span', { class: 'fvm-pill', text: `${fmt(med('gasPerM'), 1)} e³m³ gas per m` }), h('span', { class: 'fvm-pill', text: `${fmt(med('nnH'))} m to the nearest lateral` })),
      actions(rows, ctx, 'Discover: well finder'),
      table(rows, ['name', 'operator', 'year', 'lateral', 'stages', 'stageSpacing', 'proppantPerM', 'fluidPerM', 'avgP', 'isip', 'gamma', 'gasPerM', 'nnH', 'quakes'], ctx, (w, e) => wellMenu(w, e, ctx)),
      rows.length > 300 ? h('p', { class: 'fvm-note', text: `The first 300 of ${fmtN(rows.length)} by the column sorted; narrow the filters, or download them all.` }) : null,
      h('p', { class: 'fvm-note', text: 'As filed with the BCER. Intensities are per metre of lateral; stage spacing is the mean gap between filed stage tops; gamma is the median along the lateral where a log was filed (or estimated from offsets); gas is cumulative to the filing date, so older wells have had longer to produce; the nearest lateral is measured where two run side by side.' }));
  };
  pane.append(h('h1', { text: 'Well finder' }), h('p', { class: 'fvm-sub', text: 'Narrow the region’s wells; click a well for the map, its charts or its wine rack.' }), filters(W, ctx, draw), out);
  draw();
}

// ---------- Completion vs production ----------
function scatter(pane, W, ctx) {
  const { h, fmt, tip, hideTip } = ctx;
  const nums = Object.keys(COL).filter(k => COL[k].n && k !== 'quakes');
  const axisSel = (k, lab) => { const s = h('select', { 'aria-label': lab, onchange: e => { state[k] = e.target.value; saveState(); draw(); } }, nums.map(c => h('option', { value: c, text: label(c) }))); s.value = state[k]; return s; };
  const colorSel = h('select', { 'aria-label': 'Colour by', onchange: e => { state.color = e.target.value; saveState(); draw(); } },
    [['operator', 'Operator'], ['year', 'Year drilled'], ['formation', 'Formation']].map(([v, t]) => h('option', { value: v, text: t })));
  colorSel.value = state.color;
  const out = h('div');
  const NS = 'http://www.w3.org/2000/svg';
  const draw = () => {
    hideTip();
    const xk = state.x, yk = state.y, rows = W.filter(w => pass(w) && w[xk] != null && w[yk] != null && isFinite(w[xk]) && isFinite(w[yk]));
    if (rows.length < 3) { out.replaceChildren(h('div', { class: 'fvm-empty', text: 'Too few wells with both measures under these filters.' })); return; }
    // categories: fixed order by size, at most eight named, the rest "Other" (one colour each, never cycled)
    const catOf = w => state.color === 'year' ? (w.year == null ? '?' : w.year < 2016 ? '2013–15' : w.year < 2019 ? '2016–18' : w.year < 2022 ? '2019–21' : '2022 on')
      : state.color === 'formation' ? (w.formation || 'Not filed') : short(w.operator);
    const counts = new Map(); rows.forEach(w => counts.set(catOf(w), (counts.get(catOf(w)) || 0) + 1));
    let cats = state.color === 'year' ? ['2013–15', '2016–18', '2019–21', '2022 on', '?'].filter(c => counts.has(c)) : [...counts.keys()].sort((a, b) => counts.get(b) - counts.get(a));
    const named = cats.slice(0, 8), other = cats.length > 8;
    const ink = c => { const i = named.indexOf(c); return i >= 0 && window.StratumTheme ? StratumTheme.padColor(i) : 'var(--m-faint)'; };
    const q = (xs, f) => { const v = xs.slice().sort((a, b) => a - b); return v[Math.floor(f * (v.length - 1))]; };
    // the bulk of the data, not the stray filings, sets the frame
    const xsAll = rows.map(w => w[xk]), ysAll = rows.map(w => w[yk]);
    const x0 = Math.min(q(xsAll, 0), q(xsAll, .005)), x1 = q(xsAll, .995), y0 = Math.min(q(ysAll, 0), q(ysAll, .005)), y1 = q(ysAll, .995);
    const Wd = 820, Ht = 440, P = { l: 64, r: 18, t: 14, b: 50 }, pw = Wd - P.l - P.r, ph = Ht - P.t - P.b;
    const X = v => P.l + (Math.max(x0, Math.min(x1, v)) - x0) / Math.max(1e-9, x1 - x0) * pw, Y = v => P.t + ph - (Math.max(y0, Math.min(y1, v)) - y0) / Math.max(1e-9, y1 - y0) * ph;
    const svg = document.createElementNS(NS, 'svg'); svg.setAttribute('viewBox', `0 0 ${Wd} ${Ht}`); svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', `${label(yk)} against ${label(xk)} for ${rows.length} wells`);
    const el = (tag, a, text, parent = svg) => { const e = document.createElementNS(NS, tag); for (const k in a) e.setAttribute(k, a[k]); if (text != null) e.textContent = text; parent.append(e); return e; };
    const ax = el('g', { class: 'ax' });
    const xs = niceStep(x1 - x0, 8), ys = niceStep(y1 - y0, 6);
    for (let v = Math.ceil(x0 / xs) * xs; v <= x1 + 1e-9; v += xs) { el('line', { x1: X(v), x2: X(v), y1: P.t, y2: P.t + ph }, null, ax); el('text', { x: X(v), y: P.t + ph + 16, 'text-anchor': 'middle' }, fmt(v, xs < 1 ? 2 : 0), ax); }
    for (let v = Math.ceil(y0 / ys) * ys; v <= y1 + 1e-9; v += ys) { el('line', { x1: P.l, x2: P.l + pw, y1: Y(v), y2: Y(v) }, null, ax); el('text', { x: P.l - 8, y: Y(v) + 4, 'text-anchor': 'end' }, fmt(v, ys < 1 ? 2 : 0), ax); }
    el('text', { x: P.l + pw / 2, y: Ht - 8, 'text-anchor': 'middle', class: 't' }, label(xk), ax);
    el('text', { x: 14, y: P.t + ph / 2, 'text-anchor': 'middle', class: 't', transform: `rotate(-90 14 ${P.t + ph / 2})` }, label(yk), ax);
    // the median trend: the middle of y in ten equal-count bands of x
    const byX = rows.slice().sort((a, b) => a[xk] - b[xk]), band = Math.max(5, Math.floor(byX.length / 10)), trend = [];
    for (let i = 0; i + band <= byX.length; i += band) { const g = byX.slice(i, i + band); trend.push([median(g.map(w => w[xk])), median(g.map(w => w[yk]))]); }
    const dots = el('g', {});
    rows.slice().sort((a, b) => (named.indexOf(catOf(b)) < 0) - (named.indexOf(catOf(a)) < 0)).forEach(w => {
      const c = el('circle', { cx: X(w[xk]).toFixed(1), cy: Y(w[yk]).toFixed(1), r: 3.6, fill: ink(catOf(w)), class: 'dot', 'fill-opacity': .78 }, null, dots);
      c.addEventListener('pointerenter', e => tip(e, [[w.name, 1], [`${short(w.operator)} · ${w.year || '?'} · ${w.padName}`], [`${COL[xk].t}: ${fmt(w[xk], COL[xk].d)} ${COL[xk].u || ''}`], [`${COL[yk].t}: ${fmt(w[yk], COL[yk].d)} ${COL[yk].u || ''}`], ['Click for the map, its charts or its wine rack']]));
      c.addEventListener('pointerleave', hideTip);
      c.addEventListener('click', e => { hideTip(); wellMenu(w, e, ctx); });
    });
    if (trend.length > 2) el('polyline', { points: trend.map(([a, b]) => `${X(a).toFixed(1)},${Y(b).toFixed(1)}`).join(' '), fill: 'none', stroke: 'var(--m-ink)', 'stroke-width': 2, 'stroke-dasharray': '6 4', 'stroke-linejoin': 'round' });
    const legend = h('div', { class: 'fvm-legend' }, ...named.map(c => h('span', null, h('i', { style: `background:${ink(c)}` }), `${c} · ${counts.get(c)}`)),
      other ? h('span', null, h('i', { style: 'background:var(--m-faint)' }), `Other · ${cats.slice(8).reduce((n, c) => n + counts.get(c), 0)}`) : null,
      h('span', null, h('i', { style: 'background:none;border-top:2px dashed var(--m-ink);border-radius:0;height:0;width:1.4em' }), 'median trend'));
    const clipped = rows.filter(w => w[xk] > x1 || w[yk] > y1 || w[xk] < x0 || w[yk] < y0).length;
    out.replaceChildren(h('div', { class: 'fvm-count' }, h('b', { text: `${fmtN(rows.length)} wells` }), clipped ? h('span', { class: 'fvm-pill', text: `${clipped} outliers held at the edge` }) : null),
      h('div', { class: 'fvm-chart' }, svg, legend), actions(rows, ctx, `Discover: ${COL[yk].t} vs ${COL[xk].t}`),
      h('p', { class: 'fvm-note', text: 'Each dot is a well. Cumulative gas is to the filing date, so a well drilled last year has had less time than one from 2014: colour by year drilled to see it. The dashed line is the median of the y measure in ten equal-count bands along x.' }));
  };
  pane.append(h('h1', { text: 'Completion vs production' }), h('p', { class: 'fvm-sub', text: 'Pick two measures; the filters below narrow the wells.' }),
    h('div', { class: 'fvm-filters', style: 'grid-template-columns:repeat(auto-fill,minmax(14em,1fr))' },
      h('label', null, 'Across (x)', axisSel('x', 'Across')), h('label', null, 'Up (y)', axisSel('y', 'Up')), h('label', null, 'Colour by', colorSel)),
    out, folded(W, ctx, draw));
  draw();
}

// ---------- Earthquakes at stages ----------
function quakes(pane, W, ctx, S, E) {
  const { h, fmt } = ctx;
  const byWa = new Map(W.map(w => [String(w.wa), w]));
  const all = E.rows.filter(r => r[11]).map(r => {
    const m = r[11], w = byWa.get(String(+m[0])) || { wa: String(+m[0]), name: `WA ${+m[0]}`, padName: '', operator: null, pad: null };
    return { t: r[0], date: r[0].slice(0, 16).replace('T', ' '), mag: r[4], type: r[5], depth: r[3], src: r[8] === 'bcsrc' ? 'relocated' : 'NRCan',
             wa: w.wa, name: w.name, padName: w.padName, operator: w.operator, pad: w.pad, stage: String(m[1]), timing: m[2], after: m[3], km: m[4], dz: m[5] };
  });
  const COLS = { date: { t: 'Date (UTC)' }, mag: { t: 'M', n: 1, d: 1 }, name: { t: 'Well' }, operator: { t: 'Operator' }, stage: { t: 'Stage' }, when: { t: 'Timing' },
                 km: { t: 'Distance', u: 'km', n: 1, d: 1 }, dz: { t: 'Depth vs well', u: 'm', n: 1, d: 0 }, src: { t: 'Location' } };
  Object.entries(COLS).forEach(([k, v]) => { if (!COL[k]) COL[k] = v; });
  const out = h('div');
  const num = (k, lab, step) => h('label', null, lab, h('input', { type: 'number', step, value: state[k], oninput: e => { state[k] = e.target.value === '' ? null : +e.target.value; saveState(); draw(); } }));
  const timing = h('select', { onchange: e => { state.timing = e.target.value; saveState(); draw(); } },
    [['all', 'During or after a stage'], ['during', 'While a stage was pumping'], ['after', 'After a stage ended']].map(([v, t]) => h('option', { value: v, text: t })));
  timing.value = state.timing;
  const draw = () => {
    const rows = all.filter(q => (state.minMag == null || (q.mag != null && q.mag >= state.minMag)) && (state.maxKm == null || q.km <= state.maxKm)
      && (state.timing === 'all' || (state.timing === 'during' ? q.timing !== 'after' : q.timing === 'after'))).map(q => ({ ...q, when: q.timing === 'after' ? `${q.after} min after` : 'pumping' }));
    const byOp = new Map(); rows.forEach(q => byOp.set(short(q.operator), (byOp.get(short(q.operator)) || 0) + 1));
    const ops = [...byOp].sort((a, b) => b[1] - a[1]), big = Math.max(1, ...ops.map(o => o[1]));
    const c = E.control;
    out.replaceChildren(
      h('div', { class: 'fvm-count' }, h('b', { text: `${fmtN(rows.length)} earthquakes` }),
        rows.length ? h('span', { class: 'fvm-pill', text: `largest M${Math.max(...rows.map(q => q.mag || 0))}` }) : null,
        h('span', { class: 'fvm-pill', text: `${new Set(rows.map(q => q.wa)).size} wells · ${new Set(rows.map(q => q.pad)).size} pads` })),
      ops.length ? h('div', { class: 'fvm-card', style: 'margin-bottom:1em' }, h('h3', { text: 'By operator' }),
        h('div', { style: 'display:grid;grid-template-columns:max-content 1fr max-content;gap:.3em .7em;align-items:center;font-size:.85em' },
          ...ops.slice(0, 8).flatMap(([op, n]) => [h('span', { text: op }), h('div', { style: `height:.7em;border-radius:.2em;background:var(--m-acc);width:${Math.max(2, n / big * 100)}%` }), h('span', { text: String(n) })]))) : null,
      table(rows, ['date', 'mag', 'name', 'stage', 'when', 'km', 'operator', 'dz', 'src'], ctx, q => openStage(q.wa, q.stage)),
      h('p', { class: 'fvm-note', text: `Click a row for that stage’s chart in a window of its own. An earthquake is matched to a stage on a well within 5 km that was pumping, or had ended up to a week before; that names the stage, it does not prove the stage caused it.${c && c.share_beyond_chance != null ? ` Across the region about ${Math.round(c.share_beyond_chance * 100)}% of such coincidences are more than chance (the same events with dates shifted by weeks match ${c.by_chance} of ${c.matched}).` : ''} Depth vs well is the event’s solved depth less the well’s, where both are known.` }));
  };
  if (!['date', 'mag', 'km'].includes(state.sort)) { state.sort = 'mag'; state.dir = -1; }
  pane.append(h('h1', { text: 'Earthquakes at stages' }), h('p', { class: 'fvm-sub', text: 'Earthquakes Canada and the BC Seismic Research Consortium, matched to the frac stages in the region.' }),
    h('div', { class: 'fvm-filters' }, num('minMag', 'Magnitude at least', '0.1'), num('maxKm', 'Within (km of the stage)', '0.5'), h('label', null, 'Timing', timing)), out);
  draw();
}

// ---------- Well spacing ----------
function spacingTool(pane, W, ctx, S) {
  const { h, fmt } = ctx;
  const byWa = new Map(W.map(w => [String(w.wa), w]));
  const COLS = { nbName: { t: 'Nearest lateral' }, nbPad: { t: 'Its pad' }, across: { t: 'Across', u: 'm', n: 1, d: 0 }, vertical: { t: 'Vertical', u: 'm', n: 1, d: 0 }, overlap: { t: 'Side by side for', u: 'm', n: 1, d: 0 } };
  Object.entries(COLS).forEach(([k, v]) => { if (!COL[k]) COL[k] = v; });
  const out = h('div');
  const num = (k, lab) => h('label', null, lab, h('input', { type: 'number', step: '10', value: state[k] ?? '', oninput: e => { state[k] = e.target.value === '' ? null : +e.target.value; saveState(); draw(); } }));
  const chk = (k, lab) => h('label', { class: 'fvm-check', style: 'margin:0' }, h('input', { type: 'checkbox', checked: !!state[k], onchange: e => { state[k] = e.target.checked; saveState(); draw(); } }), h('span', { text: lab }));
  const draw = () => {
    const rows = [];
    for (const w of W) {
      if (!pass(w)) continue;
      const nb = (S[String(w.wa)] || []).find(n => (!state.samePad || n[4]) && (!state.zone || Math.abs(n[2]) <= 60));
      if (!nb || (state.spacingMax != null && nb[1] > state.spacingMax)) continue;
      const o = byWa.get(String(nb[0])) || {};
      rows.push({ ...w, nb: nb[0], nbName: o.name || `WA ${nb[0]}`, nbPad: o.padName || '', across: nb[1], vertical: nb[2], overlap: nb[3] });
    }
    // the spread of spacings, 25 m bands
    const bins = new Array(17).fill(0); rows.forEach(r => { bins[Math.min(16, Math.floor(r.across / 25))]++; });
    const top = Math.max(1, ...bins);
    out.replaceChildren(
      h('div', { class: 'fvm-count' }, h('b', { text: `${fmtN(rows.length)} wells` }), h('span', { class: 'fvm-pill', text: `median ${fmt(median(rows.map(r => r.across)))} m across` }),
        h('span', { class: 'fvm-pill', text: `${rows.filter(r => r.across < 100).length} under 100 m` })),
      h('div', { class: 'fvm-card', style: 'margin-bottom:1em' }, h('h3', { text: 'Nearest lateral across, in 25 m bands' }),
        h('div', { class: 'fvm-bars', role: 'img', 'aria-label': 'How many wells have their nearest lateral at each spacing' }, bins.map((n, i) => h('i', { style: `height:${n / top * 100}%`, title: `${i * 25}${i === 16 ? '+' : '–' + (i * 25 + 25)} m: ${n} wells` }))),
        h('div', { style: 'display:flex;justify-content:space-between;font:11px ui-monospace,Menlo,monospace;color:var(--m-mut)' }, h('span', { text: '0 m' }), h('span', { text: '200 m' }), h('span', { text: '400 m +' }))),
      actions(rows, ctx, 'Discover: well spacing'),
      table(rows, ['name', 'across', 'vertical', 'nbName', 'overlap', 'operator', 'year', 'nbPad', 'gasPerM'], ctx, r => ctx.toMap({ pads: [...new Set([r.pad, (byWa.get(String(r.nb)) || {}).pad].filter(Boolean))], racks: true, title: r.padName })),
      h('p', { class: 'fvm-note', text: 'Click a row for the wine rack of its pad (and its neighbour’s, if on another pad). Across is the plan distance between the two laterals where they run side by side, the median over that stretch; vertical is the neighbour’s TVD less this well’s. “Same zone” keeps neighbours within 60 m vertically, so a well stacked in another zone above or below is not counted as the nearest.' }));
  };
  if (!['across', 'vertical', 'overlap'].includes(state.sort)) { state.sort = 'across'; state.dir = 1; }
  pane.append(h('h1', { text: 'Well spacing' }), h('p', { class: 'fvm-sub', text: 'Each lateral against its nearest neighbour, on its own pad or the next one over.' }),
    h('div', { class: 'fvm-filters' }, num('spacingMax', 'Across at most (m)'), h('div', { class: 'wide' }, chk('zone', 'Same zone only (within 60 m vertically)'), chk('samePad', 'Neighbours on the same pad only'))),
    out, folded(W, ctx, draw, { skip: ['nnH'] }));
  draw();
}

window.StratumDiscover = { render, pass, short, TOOLS };
})();
