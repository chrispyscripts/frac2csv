// FracView Discover: tools for an engineer to narrow the region's wells down to
// the ones that matter for a question. Loaded by the main menu (menu.js) when
// Discover is opened; the tables come from web/scripts/build_discover.py.
//
//   Well finder                 every well, filtered by what was pumped, where and how it produced
//   Completion vs production    any two measures against each other, by operator, with the trend
//   Stage benchmarks            one stage measure across operators, years, fields: box plots, flags
//   Type curves                 production aligned on first month: P10/P50/P90 per group
//   Parent & child              spacing labels with the limits in Settings, and how children produced
//   Seismicity                  b-value, moment vs volume, distance-time, traffic lights per pad
//   Earthquakes at stages       events that coincided with a stage: magnitude, timing, distance
//   Well spacing                each lateral's nearest neighbour, across and vertically
//
// The finder's filters are shared with every tool but the earthquakes list, and
// kept for this window (sessionStorage), so moving between tools keeps the
// question. Parent/child labels come from FVMetrics.relations() (metrics.js,
// loaded here when the page has not), so they follow the limits in Settings.
// Charts are SVG drawn at the size they show, redrawn on theme, text size and
// width changes; the pure sums are on window.StratumDiscover for the tests.
(() => {
'use strict';
const STATE_KEY = 'fv.discover';
let wellsP = null, spacingP = null, eventsP = null, stagesP = null, prodP = null, lightsP = null, areasP = null, metricsP = null;
const getJSON = u => fetch(u).then(r => { if (!r.ok) throw Error('Discover’s data is not available yet.'); return r.json(); });
const wells = () => wellsP || (wellsP = getJSON('data/discover/wells.json').then(d => d.rows.map(r => Object.fromEntries(d.columns.map((c, i) => [c, r[i]])))));
const spacing = () => spacingP || (spacingP = getJSON('data/discover/spacing.json').then(d => d.wells));
const events = () => eventsP || (eventsP = getJSON('data/seismic/events.json'));
const stagesD = () => stagesP || (stagesP = getJSON('data/metrics/stages.json').then(d => ({
  bit: Object.fromEntries((d.flags || []).map((f, i) => [f, i])), rows: d.rows.map(r => Object.fromEntries(d.columns.map((c, i) => [c, r[i]]))) })));
const prod = () => prodP || (prodP = getJSON('data/prod/wells.json'));
const lights = () => lightsP || (lightsP = getJSON('data/seismic/padlights.json').catch(() => ({ rules: {}, pads: {} })));
const areas = () => areasP || (areasP = fetch('data/region/featured.json').then(r => (r.ok ? r.json() : {})).then(d => d.areas || []).catch(() => []));
const mineGroups = () => (window.StratumMenu && StratumMenu.myGroups ? StratumMenu.myGroups().catch(() => []) : Promise.resolve([]));
// prepared areas and the person's own groups, one list: [{id, name, pads, own}]
const groupList = () => Promise.all([mineGroups(), areas()]).then(([own, pre]) => [
  ...(own || []).map(g => ({ id: g.id, name: g.name, pads: g.pads || [], own: true })), ...pre.map(a => ({ id: 'preset:' + a.name, name: a.name, pads: a.pads || [] }))]);
const pad5 = wa => String(wa).replace(/^0+/, '').padStart(5, '0');

// metrics.js is not on every page: load it once when it is missing
function metrics() {
  if (window.FVMetrics) return Promise.resolve(window.FVMetrics);
  if (typeof document === 'undefined' || !document.createElement) return Promise.resolve(null);
  return metricsP || (metricsP = new Promise(res => {
    const s = document.createElement('script'); s.src = 'metrics.js';
    s.onload = () => res(window.FVMetrics || null); s.onerror = () => { metricsP = null; res(null); };
    document.head.append(s);
  }));
}
// parent/child at the limits in Settings, onto the wells in place (wells.json carries the defaults)
let relKey = null;
async function relabel(W) {
  const M = await metrics();
  if (!M) return W;
  const lim = M.limits(), key = JSON.stringify(lim);
  if (key === relKey) return W;
  const map = await M.relations(lim);
  if (!map || !map.size) return W;                  // neighbours missing: keep the file's labels
  for (const w of W) {
    const r = map.get(String(w.wa));
    w.relation = r ? r.relation : 'standalone'; w.bounded = r ? r.bounded : 'unbounded';
    w.depletionDays = r ? r.depletionDays : null; w.parents = r ? r.parents : 0; w.neighbours = r ? r.near.length : 0;
    w.parentWas = r ? r.near.filter(n => n.rel === 'parent').map(n => n.wa) : [];
  }
  relKey = key;
  return W;
}
const REL_T = { parent: 'Parent', child: 'Child', 'co-completed': 'Co-completed', standalone: 'Standalone' };
const BND_T = { bounded: 'Bounded (both sides)', half: 'Half-bounded (one side)', unbounded: 'Unbounded' };
const relInk = r => (window.FVMetrics ? FVMetrics.relColour(r) : 'var(--m-faint)');

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
  firstProd: { t: 'First production' }, gas12: { t: 'Gas, first 12 months', u: 'e³m³', n: 1, d: 0 },
  gas12Per100m: { t: 'Gas, 12 months per 100 m', u: 'e³m³', n: 1, d: 0 }, liq12Per100m: { t: 'Liquids, 12 months per 100 m', u: 'm³', n: 1, d: 1 },
  cgr12: { t: 'CGR, 12 months', u: 'm³/e³m³', n: 1, d: 3 }, peakGas: { t: 'Peak gas rate', u: 'e³m³/d', n: 1, d: 1 }, cumGas: { t: 'Gas to date', u: 'e³m³', n: 1, d: 0 },
  pumpMin: { t: 'Pump time per stage', u: 'min', n: 1, d: 0 }, tph: { t: 'Sand rate', u: 't/h', n: 1, d: 0 }, fg: { t: 'Frac gradient', u: 'kPa/m', n: 1, d: 1 },
  flagged: { t: 'Stages flagged', n: 1, d: 0 }, screenouts: { t: 'Possible screenouts', n: 1, d: 0 }, propVsFiled: { t: 'Proppant, curves ÷ filed', n: 1, d: 2 },
  relation: { t: 'Parent / child', v: x => REL_T[x] || '–' }, bounded: { t: 'Bounded', v: x => (x === 'half' ? 'Half' : x ? x[0].toUpperCase() + x.slice(1) : '–') },
  depletionDays: { t: 'Parent producing before frac', u: 'days', n: 1, d: 0 },
};
const WELL_COLS = Object.keys(COL);                // the tools below add their own columns; these are the wells'
const label = (k, D = COL) => D[k].t + (D[k].u ? ` (${D[k].u})` : '');
const SHORT = { 'Canadian Natural Resources Limited': 'CNRL', 'Pacific Canbriam Energy Limited': 'Pacific Canbriam', 'Petronas Energy Canada Ltd.': 'Petronas',
                'ConocoPhillips Canada Resources Corp.': 'ConocoPhillips', 'Tourmaline Oil Corp.': 'Tourmaline', 'ARC Resources Ltd.': 'ARC' };
const short = op => !op ? 'Not filed' : SHORT[op] || op.replace(/\s+(Ltd\.?|Limited|Inc\.?|Corp\.?|Corporation|Canada|Energy|Resources|Exploration|Oil|Partnership).*$/i, '');
const RANGES = [['year', 'Year'], ['lateral', 'Lateral (m)'], ['stageSpacing', 'Stage spacing (m)'], ['proppantPerM', 'Proppant (t/m)'], ['fluidPerM', 'Fluid (m³/m)'],
                ['avgP', 'Avg treating pressure (MPa)'], ['isip', 'ISIP (MPa)'], ['gamma', 'Landing gamma (API)'], ['gasPerM', 'Gas per metre (e³m³/m)'], ['nnH', 'Nearest lateral across (m)']];
// production, the curves and spacing: folded under "More measures"
const RANGES2 = [['gas12Per100m', 'Gas, 12 months (e³m³/100 m)'], ['liq12Per100m', 'Liquids, 12 months (m³/100 m)'], ['cgr12', 'CGR (m³/e³m³)'], ['peakGas', 'Peak gas (e³m³/d)'],
                 ['firstProd', 'First production (YYYY-MM)'], ['pumpMin', 'Pump time (min)'], ['tph', 'Sand rate (t/h)'], ['fg', 'Frac gradient (kPa/m)'], ['flagged', 'Stages flagged'],
                 ['screenouts', 'Possible screenouts'], ['propVsFiled', 'Proppant, curves ÷ filed'], ['depletionDays', 'Parent producing before frac (days)']];
const FINDER_COLS = ['name', 'operator', 'year', 'lateral', 'stages', 'stageSpacing', 'proppantPerM', 'fluidPerM', 'avgP', 'isip', 'gamma', 'gasPerM', 'gas12Per100m', 'nnH', 'relation', 'quakes'];

function loadState() { try { return JSON.parse(sessionStorage.getItem(STATE_KEY) || '{}') || {}; } catch (e) { return {}; } }
const state = Object.assign({ tool: 'finder', q: '', operator: '', formation: '', field: '', relation: '', bounded: '', curves: false, quakes: false, ranges: {},
  sort: 'proppantPerM', dir: -1, x: 'proppantPerM', y: 'gasPerM', color: 'operator', minMag: 1, timing: 'all', maxKm: 5, spacingMax: 400, samePad: false, zone: true, cols: null }, loadState());
const NESTED = { bm: { k: 'pumpMin', by: 'operator', order: 'median', st: { sort: 'p50', dir: -1 } },
  tc: { fluid: 'gas', basis: 'rate', norm: 'none', by: 'operator', months: 24, sel: '' },
  pc: { st: { sort: 'ratio', dir: 1 } }, sz: { kind: 'finder', pad: '', area: '', group: '', km: 5, win: null, st: { sort: 'lv', dir: -1 } } };
for (const k in NESTED) state[k] = Object.assign({}, NESTED[k], state[k] && typeof state[k] === 'object' ? state[k] : {});
const saveState = () => { try { sessionStorage.setItem(STATE_KEY, JSON.stringify(state)); } catch (e) { /* private mode */ } };

const TOOLS = [
  ['finder', 'Well finder', 'Every well in the region, narrowed by what was pumped, where it landed and how it produced.'],
  ['scatter', 'Completion vs production', 'Any two measures against each other, by operator, with the median trend.'],
  ['bench', 'Stage benchmarks', 'One stage measure, read off the treatment charts, across operators, years or fields; flags per group.'],
  ['curves', 'Type curves', 'Production lined up on each well’s first month: the middle well and the spread, per group.'],
  ['pc', 'Parent & child', 'Which wells came in next to producing ones, and how much less the children made.'],
  ['seis', 'Seismicity', 'b-value, seismic moment against fluid pumped, distance over time and each pad’s traffic light.'],
  ['quakes', 'Earthquakes at stages', 'Earthquakes that coincided with a frac stage: magnitude, timing, distance. Opens the stage.'],
  ['spacing', 'Well spacing', 'Each lateral’s nearest neighbour, across and up or down. Opens the wine rack.'],
];

function pass(w, s = state) {
  if (s.q) { const q = s.q.toLowerCase(); if (!(`${w.name} ${w.wa} ${w.padName} ${w.field || ''}`.toLowerCase().includes(q))) return false; }
  if (s.operator && w.operator !== s.operator) return false;
  if (s.formation && w.formation !== s.formation) return false;
  if (s.field && w.field !== s.field) return false;
  if (s.relation && w.relation !== s.relation) return false;
  if (s.bounded && w.bounded !== s.bounded) return false;
  if (s.curves && !w.curves) return false;
  if (s.quakes && !w.quakes) return false;
  for (const [k, r] of Object.entries(s.ranges || {})) {
    if (r.min != null && !(w[k] != null && w[k] >= r.min)) return false;
    if (r.max != null && !(w[k] != null && w[k] <= r.max)) return false;
  }
  return true;
}
const median = xs => { const v = xs.filter(x => x != null && isFinite(x)).sort((a, b) => a - b); return v.length ? v[Math.floor((v.length - 1) / 2)] : null; };
// a percentile of sorted numbers, interpolated between neighbours
const pct = (v, p) => { if (!v.length) return null; const i = (v.length - 1) * p, lo = Math.floor(i), hi = Math.ceil(i); return v[lo] + (v[hi] - v[lo]) * (i - lo); };
function niceStep(span, n) { const raw = span / Math.max(1, n), p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p; }
// computed numbers to six figures for a file (filed numbers keep theirs)
const r6 = row => Object.fromEntries(Object.entries(row).map(([k, v]) => [k, typeof v === 'number' && !Number.isInteger(v) ? +v.toPrecision(6) : v]));
const csvCell = v => v == null ? '' : /[",\n]/.test(String(v)) ? '"' + String(v).replace(/"/g, '""') + '"' : String(v);
function download(name, cols, rows, D = COL) {
  const text = [cols.map(c => D[c] ? label(c, D) : c).map(csvCell).join(','), ...rows.map(r => cols.map(c => csvCell(r[c])).join(','))].join('\n');
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type: 'text/csv' })); a.download = name;
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}
const letters = () => Array.from({ length: 6 }, () => String.fromCharCode(97 + Math.floor(Math.random() * 26))).join('');
const openCharts = (wa, stage) => window.open(`wellview.html?wa=${encodeURIComponent(wa)}${stage ? '&stage=' + encodeURIComponent(stage) : ''}`, 'stratum-charts', 'popup,width=1280,height=860');
const openStage = (wa, stage) => window.open(`stages.html?s=${encodeURIComponent(wa)}:${encodeURIComponent(stage)}`, 'stratum-stages' + letters(), 'popup,width=1180,height=820');
const fmtN = n => Number(n).toLocaleString();
// replaceChildren would write a skipped (null) part out as the word "null"
const put = (el, ...kids) => el.replaceChildren(...kids.flat().filter(k => k != null && k !== false));
// a number to three figures, whatever its size (normalised production can be small)
const sig = (v, n = 3) => (v == null || !isFinite(v) ? '–' : Math.abs(v) >= 1000 ? Math.round(v).toLocaleString() : Number(Number(v).toPrecision(n)).toLocaleString(undefined, { maximumFractionDigits: 6 }));
const pctTxt = v => (v == null ? '–' : `${Math.round(v * 100)}%`);

// the tool on screen redraws on theme, text size, spacing limits and width
let live = null;
if (typeof window.addEventListener === 'function') {
  const again = () => { if (live && live.pane.isConnected) live.redraw(); };
  window.addEventListener('stratum:theme', again);
  window.addEventListener('stratum:prefs', again);
  window.addEventListener('stratum:spacing', () => { relKey = null; if (wellsP) wells().then(relabel).then(again); });
}

function render(box, ctx) {
  const { h } = ctx;
  if (!document.querySelector('link[href="discover.css"]')) document.head.append(h('link', { rel: 'stylesheet', href: 'discover.css' }));
  const nav = h('div', { class: 'fvm-items' });
  const pane = h('div', { class: 'fvm-detail fvd' });
  box.append(h('div', { class: 'fvm-list' }, h('div', { class: 'fvm-list-head' }, h('h1', { text: 'Discover' }),
    h('p', { class: 'fvm-sub', style: 'margin:0', text: 'The region’s wells as filed with the BC Energy Regulator, for finding the ones that answer a question. More to come as data is added.' })), nav), pane);
  if (ctx.tool) state.tool = ctx.tool;
  if (!TOOLS.some(t => t[0] === state.tool)) state.tool = 'finder';
  const drawNav = () => nav.replaceChildren(...TOOLS.map(([id, t, d]) => h('button', { type: 'button', class: 'fvm-item', 'aria-selected': String(state.tool === id),
    onclick: () => { state.tool = id; saveState(); drawNav(); tool(); } }, h('b', { text: t }), h('span', { text: d, style: 'white-space:normal' }))));
  drawNav();
  const RUN = { finder: [finder], scatter: [scatter], bench: [bench, stagesD, 'the stage measures'], curves: [curves, () => Promise.all([prod(), groupList()]), 'the region’s production'],
    pc: [parentChild], seis: [seismic, () => Promise.all([events(), lights(), groupList(), stagesD()]), 'the earthquakes and stages'],
    quakes: [quakes, events], spacing: [spacingTool, spacing] };
  let seq = 0;
  const tool = () => {
    ctx.hideTip(); live = null;
    const [fn, more, what] = RUN[state.tool], my = ++seq;
    pane.replaceChildren(h('div', { class: 'fvm-empty', text: `Loading the region’s wells${what ? ' and ' + what : ''}…` }));
    Promise.all([wells().then(relabel), more ? more() : null])
      .then(([W, X]) => { if (my !== seq) return; pane.replaceChildren(); pane.scrollTop = 0; fn(pane, W, ctx, X); })
      .catch(e => { if (my === seq) pane.replaceChildren(h('div', { class: 'fvm-empty', text: e.message })); });
  };
  tool();
  // a chart drawn at one width is redrawn at the next
  if (window.ResizeObserver) {
    let w0 = 0, t = 0;
    new ResizeObserver(() => { const w = pane.clientWidth; if (Math.abs(w - w0) < 30) return; w0 = w; clearTimeout(t); t = setTimeout(() => { if (live && live.charts && pane.isConnected) live.redraw(); }, 150); }).observe(pane);
  }
}

// ---------- the filters every tool but the earthquakes shares ----------
function filters(W, ctx, onChange, opts = {}) {
  const { h } = ctx;
  const opts_ = k => [...new Set(W.map(w => w[k]).filter(Boolean))].sort((a, b) => W.filter(w => w[k] === b).length - W.filter(w => w[k] === a).length);
  const sel = (k, all, list) => { const s = h('select', { 'aria-label': k, onchange: e => { state[k] = e.target.value; changed(); } }, h('option', { value: '', text: all }),
    (list || opts_(k).map(v => [v, k === 'operator' ? short(v) : v])).map(([v, t]) => h('option', { value: v, text: t })));
    s.value = state[k] || ''; return s; };
  let t = 0;
  const changed = () => { clearTimeout(t); t = setTimeout(() => { saveState(); onChange(); }, 120); };
  const range = (k, lab) => {
    const r = state.ranges[k] || {}, month = k === 'firstProd';
    const mk = (which, ph) => h('input', { type: month ? 'text' : 'number', step: month ? null : 'any', placeholder: month ? (which === 'min' ? 'from' : 'to') : ph, value: r[which] ?? '',
      inputmode: month ? 'numeric' : null, 'aria-label': `${lab} ${which}`,
      oninput: e => {
        const cur = state.ranges[k] || {}, s = e.target.value.trim();
        // a month as text: a year alone means its first or last month
        cur[which] = s === '' ? null : month ? (/^\d{4}$/.test(s) ? s + (which === 'min' ? '-01' : '-12') : s) : +s;
        if (cur.min == null && cur.max == null) delete state.ranges[k]; else state.ranges[k] = cur; changed();
      } });
    return h('label', null, lab, h('div', { class: 'fvm-pair' }, mk('min', 'min'), mk('max', 'max')));
  };
  const skip = opts.skip || [];
  const more = RANGES2.filter(([k]) => !skip.includes(k));
  const box = h('div', { class: 'fvm-filters' },
    h('label', null, 'Search', h('input', { type: 'search', placeholder: 'Well, WA, pad or field', value: state.q, oninput: e => { state.q = e.target.value.trim(); changed(); } })),
    h('label', null, 'Operator', sel('operator', 'All operators')),
    h('label', null, 'Formation', sel('formation', 'All formations')),
    h('label', null, 'Field', sel('field', 'All fields')),
    skip.includes('relation') ? null : h('label', null, 'Parent / child', sel('relation', 'Any', Object.entries(REL_T))),
    skip.includes('bounded') ? null : h('label', null, 'Bounded', sel('bounded', 'Any', Object.entries(BND_T))),
    ...RANGES.filter(([k]) => !skip.includes(k)).map(([k, l]) => range(k, l)),
    more.length ? h('details', { class: 'wide fvd-more', open: more.some(([k]) => state.ranges[k]) || null }, h('summary', { text: 'More measures: production, the curves, spacing' }),
      h('div', { class: 'fvd-more-grid' }, ...more.map(([k, l]) => range(k, l)))) : null,
    h('div', { class: 'wide' },
      h('label', { class: 'fvm-check', style: 'margin:0' }, h('input', { type: 'checkbox', checked: state.curves, onchange: e => { state.curves = e.target.checked; changed(); } }), h('span', { text: 'Only wells with treatment charts' })),
      h('label', { class: 'fvm-check', style: 'margin:0' }, h('input', { type: 'checkbox', checked: state.quakes, onchange: e => { state.quakes = e.target.checked; changed(); } }), h('span', { text: 'Only wells with an earthquake at a stage' })),
      h('button', { type: 'button', text: 'Clear filters', onclick: () => { Object.assign(state, { q: '', operator: '', formation: '', field: '', relation: '', bounded: '', curves: false, quakes: false, ranges: {} }); saveState(); ctx.show('discover', { tool: state.tool }); } })));
  return box;
}
// what the filters are set to, in words
function filterWords() {
  const bits = [state.q && `“${state.q}”`, state.operator && short(state.operator), state.formation, state.field, state.relation && (REL_T[state.relation] || state.relation).toLowerCase(),
    state.bounded && (BND_T[state.bounded] || state.bounded).toLowerCase(), state.curves && 'with charts', state.quakes && 'with earthquakes',
    ...Object.entries(state.ranges || {}).map(([k, r]) => `${(COL[k] || { t: k }).t.toLowerCase()} ${r.min != null ? '≥ ' + r.min : ''}${r.min != null && r.max != null ? ', ' : ''}${r.max != null ? '≤ ' + r.max : ''}`)].filter(Boolean);
  return bits;
}
// the same filters folded away under what they are set to, for tools whose answer comes first
function folded(W, ctx, onChange, opts) {
  const { h } = ctx;
  const words = () => { const b = filterWords(); return b.length ? 'Filtered: ' + b.join(' · ') : 'Filter the wells (all of them now)'; };
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
    h('button', { type: 'button', text: 'Download CSV', disabled: !rows.length, onclick: () => download('fracview-wells.csv',
      ['wa', 'name', 'padName', 'operator', 'formation', 'field', 'year', 'firstProd', 'relation', 'bounded', ...WELL_COLS.filter(k => COL[k].n && k !== 'year')], rows) }),
    msg);
}

// a sortable table; `cols` keys of COL (or o.defs), `onRow` for a click; o.st keeps its own sort
function table(rows, cols, ctx, onRow, limit = 300, o = {}) {
  const { h, fmt } = ctx, D = o.defs || COL, st = o.st || state;
  const t = h('table', { class: 'fvm-table' + (o.cls ? ' ' + o.cls : '') });
  const draw = () => {
    const k = cols.includes(st.sort) ? st.sort : cols.find(c => D[c] && D[c].n) || cols[0], dir = st.dir || -1;
    const val = r => (D[k] && D[k].sv ? D[k].sv(r) : r[k]);
    const sorted = rows.slice().sort((a, b) => { const x = val(a), y = val(b); if (x == null) return 1; if (y == null) return -1; return (x > y ? 1 : x < y ? -1 : 0) * dir; });
    t.replaceChildren(
      h('thead', null, h('tr', null, cols.map(c => h('th', { class: D[c] && D[c].n ? 'num' : null, 'aria-sort': c === k ? (dir > 0 ? 'ascending' : 'descending') : null },
        h('button', { type: 'button', text: (D[c] ? D[c].t : c) + (c === k ? (dir > 0 ? ' ↑' : ' ↓') : ''), title: D[c] && D[c].u ? D[c].u : null,
          onclick: () => { st.dir = st.sort === c ? -(st.dir || -1) : (D[c] && D[c].n ? -1 : 1); st.sort = c; saveState(); draw(); } }))))),
      h('tbody', null, sorted.slice(0, limit).map(r => h('tr', { onclick: onRow ? e => onRow(r, e) : null, tabindex: onRow ? 0 : null, class: onRow ? null : 'still',
        onkeydown: onRow ? e => { if (e.key === 'Enter') onRow(r, e); } : null }, cols.map(c => {
        const v = r[c], m = D[c], node = o.cell && o.cell(c, r);
        if (node) return h('td', { class: m && m.n ? 'num' : null }, node);
        // a well's name without the operator and "HZ" in front, as the map's list has it
        const nm = (c === 'name' || c === 'nbName') && v ? String(v).replace(/^\S+(\s+\S+)?\s+HZ\s+/i, '') : null;
        return h('td', { class: m && m.n ? 'num' : null, title: c === 'operator' || nm ? `${v}${r.wa && c === 'name' ? ' · WA ' + r.wa : ''}` : null,
          text: nm || (c === 'operator' ? short(v) : m && m.v ? m.v(v, r) : m && m.n ? (m.plain ? (v ?? '–') : fmt(v, m.d)) : (v ?? '–')) });
      })))));
  };
  draw();
  return h('div', { class: 'fvm-tablewrap' }, t);
}
// where a keyboard-opened menu or tip should sit: the element's own box
const at = e => (e && e.clientX != null && (e.clientX || e.clientY) ? e : (() => { const b = (e && e.currentTarget || document.activeElement).getBoundingClientRect(); return { clientX: b.left + 24, clientY: b.top + b.height / 2 }; })());
// a well's next steps, at the pointer
function wellMenu(w, e, ctx) {
  const { h } = ctx;
  const p = at(e);
  document.querySelectorAll('.fvm-pop').forEach(x => x.remove());
  const pop = h('div', { class: 'fvm-card fvm-pop', role: 'menu', style: 'position:fixed;z-index:215;padding:.5em;display:flex;flex-direction:column;gap:.35em;min-width:14em;box-shadow:0 10px 26px rgba(0,0,0,.18)' },
    h('b', { text: w.name, style: 'font-size:.85em;padding:.2em .3em' }),
    h('button', { type: 'button', class: 'go', text: 'Show it on the map', onclick: () => { pop.remove(); ctx.toMap({ wells: [w.wa], wa: w.wa, title: w.name }); } }),
    w.curves ? h('button', { type: 'button', text: 'Its treatment charts ↗', onclick: () => { pop.remove(); openCharts(w.wa); } }) : null,
    h('button', { type: 'button', text: 'Its pad’s wine rack ↗', onclick: () => { pop.remove(); ctx.toMap({ pads: [w.pad], racks: true, title: w.padName }); } }));
  document.querySelector('.fvm').append(pop);
  pop.style.left = Math.max(8, Math.min(innerWidth - pop.offsetWidth - 8, p.clientX + 6)) + 'px';
  pop.style.top = Math.max(8, Math.min(innerHeight - pop.offsetHeight - 8, p.clientY + 6)) + 'px';
  const off = ev => { if (!pop.contains(ev.target)) { pop.remove(); document.removeEventListener('pointerdown', off, true); } };
  setTimeout(() => document.addEventListener('pointerdown', off, true));
  pop.querySelector('button').focus();
}

// ---------- charts: SVG at the size it shows, one y axis, text in ink ----------
const NS = 'http://www.w3.org/2000/svg';
const sv = (tag, a, parent, text) => { const e = document.createElementNS(NS, tag); for (const k in a) if (a[k] != null) e.setAttribute(k, a[k]); if (text != null) e.textContent = text; if (parent) parent.append(e); return e; };
const tscale = () => { try { return parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--fv-ts')) || 1; } catch (e) { return 1; } };
const SUP = '⁰¹²³⁴⁵⁶⁷⁸⁹';
const pow10 = n => '10' + String(n).replace('-', '⁻').replace(/\d/g, d => SUP[d]);
// on a log axis that runs past 100,000 every label is a power of ten, so they read alike
const fmtLog = (v, pow) => { const e = Math.floor(Math.log10(v) + 1e-9), m = Math.round(v / 10 ** e); return !pow && Math.abs(e) < 5 ? Number(v.toPrecision(3)).toLocaleString() : (m === 1 ? '' : m + '×') + pow10(e); };
// categorical colours in their fixed order (the operators' palette); never cycled
const ink = i => (i < 0 ? 'var(--m-faint)' : window.StratumTheme ? StratumTheme.padColor(i) : ['#2563eb', '#e8590c', '#0b8ea3', '#9c36b5', '#5c940d', '#c2255c', '#9a6b00', '#7048e8'][i % 8]);
function frame(host, o) {
  const k = tscale(), fs = 11 * k;
  const W = Math.max(260, Math.floor(host.clientWidth || 640));
  const H = o.h || Math.round(Math.min(380 * Math.max(1, k), Math.max(220, W * .5)));
  const P = { l: o.l != null ? o.l : Math.round(fs * (o.yw || 4.6) + 10), r: o.r != null ? o.r : Math.round(fs * 1.2), t: o.t != null ? o.t : Math.round(fs * 2.2), b: o.b != null ? o.b : Math.round(fs * 3.6) };
  const pw = Math.max(40, W - P.l - P.r), ph = Math.max(40, H - P.t - P.b);
  const svg = sv('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': o.aria || '' });
  const scale = (a, lo, hi) => (a.log ? v => lo + (Math.log10(Math.max(v, a.min)) - Math.log10(a.min)) / ((Math.log10(a.max) - Math.log10(a.min)) || 1) * (hi - lo)
                                      : v => lo + (v - a.min) / ((a.max - a.min) || 1) * (hi - lo));
  const X = scale(o.x, P.l, P.l + pw), Y = o.y ? scale(o.y, P.t + ph, P.t) : null;
  const ticks = (a, n) => {
    if (a.ticks) return a.ticks.filter(v => v >= a.min - 1e-9 && v <= a.max + 1e-9);
    if (a.log) {
      const lo = Math.ceil(Math.log10(a.min) - 1e-9), hi = Math.floor(Math.log10(a.max) + 1e-9), dec = [];
      for (let e = lo; e <= hi; e++) dec.push(10 ** e);
      if (dec.length >= 3) { const s = Math.ceil(dec.length / n); return dec.filter((_, i) => i % s === 0); }
      const m = []; for (let e = lo - 1; e <= hi; e++) for (const f of [1, 2, 5]) { const v = f * 10 ** e; if (v >= a.min && v <= a.max) m.push(v); }
      return m;
    }
    const s = niceStep(a.max - a.min, n), out = [];
    for (let v = Math.ceil(a.min / s - 1e-9) * s; v <= a.max + s * 1e-6; v += s) out.push(+v.toFixed(10));
    a._step = s; return out;
  };
  const tf = (a, v) => (a.fmt ? a.fmt(v) : a.log ? fmtLog(v, a.max >= 1e5 || a.min < 1e-2) : Number(v).toLocaleString(undefined, { maximumFractionDigits: a._step < 1 ? (a._step < .1 ? 2 : 1) : 0 }));
  const ax = sv('g', { class: 'ax' }, svg);
  for (const v of ticks(o.x, Math.max(2, Math.floor(pw / (fs * 7))))) {
    sv('line', { x1: X(v), x2: X(v), y1: P.t, y2: P.t + ph }, ax);
    sv('text', { x: X(v), y: P.t + ph + fs * 1.45, 'text-anchor': 'middle' }, ax, tf(o.x, v));
  }
  if (o.y) for (const v of ticks(o.y, Math.max(2, Math.floor(ph / (fs * 3))))) {
    sv('line', { x1: P.l, x2: P.l + pw, y1: Y(v), y2: Y(v) }, ax);
    sv('text', { x: P.l - 6, y: Y(v) + fs * .35, 'text-anchor': 'end' }, ax, tf(o.y, v));
  }
  sv('line', { x1: P.l, x2: P.l + pw, y1: P.t + ph, y2: P.t + ph, class: 'base' }, ax);
  if (o.x.label) sv('text', { x: P.l + pw / 2, y: H - fs * .5, 'text-anchor': 'middle', class: 't' }, ax, o.x.label);
  if (o.y && o.y.label) sv('text', { x: Math.max(4, P.l - fs * 3.5), y: fs * 1.2, class: 't' }, ax, o.y.label);
  host.replaceChildren(svg);
  return { svg, W, H, P, pw, ph, X, Y, fs, k };
}
// the tooltip, with a short line in each series' colour for the rows that carry one
// (the tip lives outside the menu, so a CSS variable is read off the menu first)
const solid = c => { if (!/^var\(/.test(c)) return c; const el = document.querySelector('.fvm'); return (el && getComputedStyle(el).getPropertyValue(c.slice(4, -1)).trim()) || '#888'; };
function tipK(ctx, e, lines) {
  const kept = lines.filter(Boolean);
  ctx.tip(at(e), kept.map(l => [l[0], l[1]]));
  const el = document.querySelector('body > .fvm-tip'); if (!el) return;
  [...el.children].forEach((c, i) => {
    const col = kept[i] && kept[i][2]; if (!col) return;
    const k = sv('svg', { width: 16, height: 8, class: 'fvd-key', 'aria-hidden': 'true', style: 'margin-right:6px;vertical-align:1px' });
    sv('line', { x1: 1, x2: 14, y1: 4, y2: 4, stroke: solid(col), 'stroke-width': 2.5, 'stroke-linecap': 'round' }, k); c.prepend(k);
  });
}
// dense dots: the pointer only has to be nearest (within 24 px), not on the mark
function nearest(F, pts, ctx, lines, onClick) {
  const ring = sv('circle', { r: 0, class: 'ring' }, F.svg);
  const hit = sv('rect', { x: 0, y: 0, width: F.W, height: F.H, fill: 'transparent', class: 'hit' }, F.svg);
  const find = e => {
    const b = F.svg.getBoundingClientRect(), s = F.W / (b.width || F.W), x = (e.clientX - b.left) * s, y = (e.clientY - b.top) * s;
    let best = null, bd = 24 * s; for (const p of pts) { const d = Math.hypot(p.x - x, p.y - y); if (d < bd) { bd = d; best = p; } } return best;
  };
  const move = e => {
    const p = find(e);
    if (!p) { ring.setAttribute('r', 0); ctx.hideTip(); hit.style.cursor = ''; return; }
    ring.setAttribute('cx', p.x); ring.setAttribute('cy', p.y); ring.setAttribute('r', (p.r || 4) + 3);
    hit.style.cursor = onClick ? 'pointer' : ''; tipK(ctx, e, lines(p.d));
  };
  hit.addEventListener('pointermove', move); hit.addEventListener('pointerdown', move);
  hit.addEventListener('pointerleave', () => { ring.setAttribute('r', 0); ctx.hideTip(); });
  if (onClick) hit.addEventListener('click', e => { const p = find(e); if (p) { ctx.hideTip(); onClick(p.d, e); } });
}
// lines over time: a hairline snaps to the nearest x and the tip lists every series there
function crosshair(F, xs, ctx, lines) {
  const xh = sv('line', { y1: F.P.t, y2: F.P.t + F.ph, class: 'xh', visibility: 'hidden' }, F.svg);
  const hit = sv('rect', { x: F.P.l, y: 0, width: F.pw, height: F.H, fill: 'transparent', class: 'hit' }, F.svg);
  const move = e => {
    const b = F.svg.getBoundingClientRect(), x = (e.clientX - b.left) * F.W / (b.width || F.W);
    let i = 0; for (let j = 1; j < xs.length; j++) if (Math.abs(xs[j] - x) < Math.abs(xs[i] - x)) i = j;
    xh.setAttribute('x1', xs[i]); xh.setAttribute('x2', xs[i]); xh.setAttribute('visibility', 'visible');
    tipK(ctx, e, lines(i));
  };
  hit.addEventListener('pointermove', move); hit.addEventListener('pointerdown', move);
  hit.addEventListener('pointerleave', () => { xh.setAttribute('visibility', 'hidden'); ctx.hideTip(); });
}
// a column with a 4 px rounded top, square on the baseline
const colPath = (x, y, w, hh, r = 4) => { r = Math.min(r, w / 2, hh); return `M${x},${y + hh}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + hh}Z`; };
// the median of y in equal-count bands along x
function trend(pts, bands = 8, min = 8) {
  const s = pts.slice().sort((a, b) => a[0] - b[0]), n = Math.max(min, Math.floor(s.length / bands)), out = [];
  for (let i = 0; i + n <= s.length; i += n) { const g = s.slice(i, i + n); out.push([median(g.map(p => p[0])), median(g.map(p => p[1]))]); }
  return out;
}
const legendBox = (h, items) => h('div', { class: 'fvm-legend' }, items.filter(Boolean).map(it => it.on
  ? h('button', { type: 'button', class: 'fvd-lg', 'aria-pressed': String(!!it.pressed), onclick: it.on, title: it.title || null }, h('i', { class: it.kind || null, style: `--c:${it.c}` }), it.t)
  : h('span', null, h('i', { class: it.kind || null, style: `--c:${it.c}` }), it.t)));
const card = (h, title, ...kids) => h('section', { class: 'fvm-card fvd-card' }, title ? h('h3', { text: title }) : null, ...kids);
const plotBox = h => h('div', { class: 'fvd-plot' });

// categories for a grouping, colours in a fixed order that a filter never repaints
const YEARS = ['2013–15', '2016–18', '2019–21', '2022 on'];
const yearBin = y => (y == null ? '?' : y < 2016 ? YEARS[0] : y < 2019 ? YEARS[1] : y < 2022 ? YEARS[2] : YEARS[3]);
function categories(by, W, glist = []) {
  if (by === 'relation') { const ks = Object.keys(REL_T); return { of: w => [REL_T[w.relation] || REL_T.standalone], order: ks.map(k => REL_T[k]), col: t => relInk(ks.find(k => REL_T[k] === t)) }; }
  if (by === 'bounded') { const ks = Object.keys(BND_T); return { of: w => [BND_T[w.bounded] || BND_T.unbounded], order: ks.map(k => BND_T[k]), col: t => ink(ks.findIndex(k => BND_T[k] === t)) }; }
  if (by === 'year') return { of: w => [yearBin(w.year)], order: [...YEARS, '?'], col: t => ink(YEARS.indexOf(t)) };
  if (by === 'groups') {
    const gs = glist.slice(0, 8), sets = gs.map(g => new Set(g.pads));
    return { of: w => gs.filter((g, i) => sets[i].has(w.pad)).map(g => g.name), order: gs.map(g => g.name), col: t => ink(gs.findIndex(g => g.name === t)) };
  }
  const name = w => (by === 'operator' ? short(w.operator) : w[by] || 'Not filed');
  const cnt = new Map(); W.forEach(w => cnt.set(name(w), (cnt.get(name(w)) || 0) + 1));
  const top = [...cnt].sort((a, b) => b[1] - a[1]).map(x => x[0]), named = top.slice(0, 8);
  return { of: w => [named.includes(name(w)) ? name(w) : 'Other'], order: [...named, ...(top.length > 8 ? ['Other'] : [])], col: t => ink(named.indexOf(t)) };
}

// ---------- Well finder ----------
function finder(pane, W, ctx) {
  const { h, fmt } = ctx;
  const out = h('div');
  const cols = () => (Array.isArray(state.cols) && state.cols.length ? ['name', ...state.cols.filter(c => c !== 'name' && WELL_COLS.includes(c))] : FINDER_COLS);
  const picker = h('details', { class: 'fvd-cols' }, h('summary', { text: 'Columns' }),
    h('div', null, WELL_COLS.filter(c => c !== 'name').map(c => h('label', { class: 'fvm-check' },
      h('input', { type: 'checkbox', checked: cols().includes(c), onchange: e => {
        const cur = cols().filter(x => x !== c && x !== 'name');
        state.cols = WELL_COLS.filter(x => x !== 'name' && (cur.includes(x) || (e.target.checked && x === c))); saveState(); draw(); } }),
      h('span', { text: label(c) }))),
    h('button', { type: 'button', text: 'The usual columns', onclick: () => { state.cols = null; saveState(); pane.replaceChildren(); finder(pane, W, ctx); } })));
  const draw = () => {
    const rows = W.filter(w => pass(w));
    const med = k => median(rows.map(w => w[k]));
    put(out,
      h('div', { class: 'fvm-count' }, h('b', { text: `${fmtN(rows.length)} of ${fmtN(W.length)} wells` }),
        h('span', { class: 'fvm-pill', text: `median ${fmt(med('proppantPerM'), 2)} t/m` }), h('span', { class: 'fvm-pill', text: `${fmt(med('stageSpacing'))} m stage spacing` }),
        h('span', { class: 'fvm-pill', text: `${fmt(med('gas12Per100m'))} e³m³ gas per 100 m in 12 months` }), h('span', { class: 'fvm-pill', text: `${fmt(med('nnH'))} m to the nearest lateral` })),
      actions(rows, ctx, 'Discover: well finder'),
      table(rows, cols(), ctx, (w, e) => wellMenu(w, e, ctx)),
      rows.length > 300 ? h('p', { class: 'fvm-note', text: `The first 300 of ${fmtN(rows.length)} by the column sorted; narrow the filters, or download them all.` }) : null,
      h('p', { class: 'fvm-note', text: 'As filed with the BCER. Intensities are per metre of lateral; stage spacing is the mean gap between filed stage tops; gamma is the median along the lateral where a log was filed (or estimated from offsets); cumulative gas is to the filing date, so older wells have had longer to produce; 12-month gas and liquids are the first twelve producing months from the BCER’s monthly volumes, per 100 m of lateral; pump time, sand rate and frac gradient are medians over the stages read off the treatment charts; the nearest lateral is measured where two run side by side. Parent and child follow the limits in Settings (Parent & child sets them too).' }));
  };
  pane.append(h('h1', { text: 'Well finder' }), h('p', { class: 'fvm-sub', text: 'Narrow the region’s wells; click a well for the map, its charts or its wine rack.' }), filters(W, ctx, draw), picker, out);
  draw();
}

// ---------- Completion vs production ----------
function scatter(pane, W, ctx) {
  const { h, fmt, tip, hideTip } = ctx;
  const nums = WELL_COLS.filter(k => COL[k].n && k !== 'quakes');
  const axisSel = (k, lab) => { const s = h('select', { 'aria-label': lab, onchange: e => { state[k] = e.target.value; saveState(); draw(); } }, nums.map(c => h('option', { value: c, text: label(c) }))); s.value = state[k]; return s; };
  const colorSel = h('select', { 'aria-label': 'Colour by', onchange: e => { state.color = e.target.value; saveState(); draw(); } },
    [['operator', 'Operator'], ['year', 'Year drilled'], ['formation', 'Formation'], ['relation', 'Parent / child']].map(([v, t]) => h('option', { value: v, text: t })));
  colorSel.value = state.color;
  const out = h('div');
  const draw = () => {
    hideTip();
    const xk = nums.includes(state.x) ? state.x : 'proppantPerM', yk = nums.includes(state.y) ? state.y : 'gasPerM';
    const rows = W.filter(w => pass(w) && w[xk] != null && w[yk] != null && isFinite(w[xk]) && isFinite(w[yk]));
    if (rows.length < 3) { out.replaceChildren(h('div', { class: 'fvm-empty', text: 'Too few wells with both measures under these filters.' })); return; }
    // categories: fixed order by size, at most eight named, the rest "Other" (one colour each, never cycled)
    // categories in a fixed order (by size over the whole region), at most eight named, the rest "Other"; a filter never repaints them
    const cat = categories(state.color, W), catOf = w => cat.of(w)[0], inkOf = c => cat.col(c);
    const counts = new Map(); rows.forEach(w => counts.set(catOf(w), (counts.get(catOf(w)) || 0) + 1));
    const named = cat.order.filter(c => c !== 'Other' && counts.has(c)), other = counts.has('Other');
    const q = (xs, f) => { const v = xs.slice().sort((a, b) => a - b); return v[Math.floor(f * (v.length - 1))]; };
    // the bulk of the data, not the stray filings, sets the frame
    const xsAll = rows.map(w => w[xk]), ysAll = rows.map(w => w[yk]);
    const x0 = Math.min(q(xsAll, 0), q(xsAll, .005)), x1 = q(xsAll, .995), y0 = Math.min(q(ysAll, 0), q(ysAll, .005)), y1 = q(ysAll, .995);
    const plot = plotBox(h);
    const clipped = rows.filter(w => w[xk] > x1 || w[yk] > y1 || w[xk] < x0 || w[yk] < y0).length;
    const legend = legendBox(h, [...named.map(c => ({ c: inkOf(c), t: `${c} · ${counts.get(c)}` })),
      other ? { c: 'var(--m-faint)', t: `Other · ${counts.get('Other')}` } : null, { c: 'var(--m-ink)', kind: 'line', t: 'median trend' }]);
    put(out, h('div', { class: 'fvm-count' }, h('b', { text: `${fmtN(rows.length)} wells` }), clipped ? h('span', { class: 'fvm-pill', text: `${clipped} outliers held at the edge` }) : null),
      h('div', { class: 'fvm-chart' }, plot, legend), actions(rows, ctx, `Discover: ${COL[yk].t} vs ${COL[xk].t}`),
      h('p', { class: 'fvm-note', text: 'Each dot is a well. Cumulative gas is to the filing date, so a well drilled last year has had less time than one from 2014: colour by year drilled to see it, or use the 12-month measures. The line is the median of the y measure in ten equal-count bands along x.' }));
    const F = frame(plot, { x: { min: x0, max: x1, label: label(xk) }, y: { min: y0, max: y1, label: label(yk) }, aria: `${label(yk)} against ${label(xk)} for ${rows.length} wells` });
    const cl = (v, a, b) => Math.max(a, Math.min(b, v));
    const pts = [];
    const dots = sv('g', {}, F.svg);
    rows.slice().sort((a, b) => (named.indexOf(catOf(b)) < 0) - (named.indexOf(catOf(a)) < 0)).forEach(w => {
      const x = F.X(cl(w[xk], x0, x1)), y = F.Y(cl(w[yk], y0, y1));
      sv('circle', { cx: x.toFixed(1), cy: y.toFixed(1), r: 4, fill: inkOf(catOf(w)), class: 'dot', 'fill-opacity': .8 }, dots);
      pts.push({ x, y, r: 4, d: w });
    });
    const tr = trend(rows.map(w => [w[xk], w[yk]]), 10, 5);
    if (tr.length > 2) for (const [st, sw] of [['var(--m-panel)', 6], ['var(--m-ink)', 2]]) sv('polyline', { points: tr.map(([a, b]) => `${F.X(a).toFixed(1)},${F.Y(cl(b, y0, y1)).toFixed(1)}`).join(' '), fill: 'none', stroke: st, 'stroke-width': sw, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, F.svg);
    nearest(F, pts, ctx, w => [[w.name, 1], [`${short(w.operator)} · ${w.year || '?'} · ${w.padName}`], [`${COL[xk].t}: ${fmt(w[xk], COL[xk].d)} ${COL[xk].u || ''}`], [`${COL[yk].t}: ${fmt(w[yk], COL[yk].d)} ${COL[yk].u || ''}`], ['Click for the map, its charts or its wine rack']],
      (w, e) => wellMenu(w, e, ctx));
  };
  pane.append(h('h1', { text: 'Completion vs production' }), h('p', { class: 'fvm-sub', text: 'Pick two measures; the filters below narrow the wells.' }),
    h('div', { class: 'fvm-filters', style: 'grid-template-columns:repeat(auto-fill,minmax(14em,1fr))' },
      h('label', null, 'Across (x)', axisSel('x', 'Across')), h('label', null, 'Up (y)', axisSel('y', 'Up')), h('label', null, 'Colour by', colorSel)),
    out, folded(W, ctx, draw));
  live = { pane, redraw: draw, charts: true };
  draw();
}

// ---------- Stage benchmarks ----------
const BM = ['pumpMin', 'rampMin', 'avgP', 'maxP', 'pSlope', 'avgRate', 'tph', 'prop', 'clean', 'isip', 'fg', 'maxConc'];
const BM_BY = [['operator', 'Operator'], ['year', 'Year pumped'], ['field', 'Field'], ['formation', 'Formation'], ['relation', 'Parent / child'], ['bounded', 'Bounded']];
const OPF = ['screenout', 'shutdown', 'spike', 'drop', 'short'];
const OPF_T = { screenout: 'Screenout', shutdown: 'Shutdown', spike: 'Spike', drop: 'Break', short: 'Short' };
const stageGroup = (by, w, r) => (by === 'year' ? (r && r.date ? r.date.slice(0, 4) : String(w.year || '?')) : by === 'operator' ? short(w.operator)
  : by === 'relation' ? REL_T[w.relation] || 'Standalone' : by === 'bounded' ? BND_T[w.bounded] || 'Unbounded' : w[by] || 'Not filed');
// per group: the spread of one stage measure (P10–P90), and the share of stages with each operational flag
function benchmark(S, byWa, o) {
  const M = window.FVMetrics, val = r => (M ? M.value(r, o.k) : r[o.k]), minN = o.minN || 30;
  const G = new Map();
  for (const r of S.rows) {
    const w = byWa.get(String(+r.wa)); if (!w || !(o.pass ? o.pass(w) : true)) continue;
    const key = stageGroup(o.by, w, r);
    let g = G.get(key); if (!g) G.set(key, g = { key, vals: [], wells: new Set(), all: 0, f: Object.fromEntries(OPF.map(f => [f, 0])) });
    g.all++; g.wells.add(w.wa);
    for (const f of OPF) if (S.bit[f] != null && (r.flags >> S.bit[f]) & 1) g.f[f]++;
    const v = val(r); if (v != null && isFinite(v)) g.vals.push(v);
  }
  // groups too small to read pool together, last
  let big = [...G.values()].filter(g => g.vals.length >= minN), small = [...G.values()].filter(g => g.vals.length < minN);
  if (small.length) {
    const o2 = { key: small.length === 1 ? small[0].key : `Other (${small.length} groups)`, other: small.length > 1, vals: small.flatMap(g => g.vals), wells: new Set(small.flatMap(g => [...g.wells])),
      all: small.reduce((n, g) => n + g.all, 0), f: Object.fromEntries(OPF.map(f => [f, small.reduce((n, g) => n + g.f[f], 0)])) };
    if (o2.vals.length) big.push(o2);
  }
  return big.filter(g => g.vals.length).map(g => {
    const v = g.vals.sort((a, b) => a - b);
    return { key: g.key, other: !!g.other, n: v.length, stages: g.all, nWells: g.wells.size, wells: [...g.wells], p10: pct(v, .1), p25: pct(v, .25), p50: pct(v, .5), p75: pct(v, .75), p90: pct(v, .9),
             ...Object.fromEntries(OPF.map(f => [f, g.all ? g.f[f] / g.all : null])) };
  });
}
function bench(pane, W, ctx, S) {
  const { h, fmt } = ctx;
  const byWa = new Map(W.map(w => [String(w.wa), w]));
  const M = window.FVMetrics, BY = M ? M.BY : {};
  const keys = BM.filter(k => BY[k] || COL[k]);
  const mt = k => BY[k] || { t: k, u: '', d: 1 };
  const B = state.bm;
  const sel = (key, lab, list) => { const s = h('select', { 'aria-label': lab, onchange: e => { B[key] = e.target.value; saveState(); draw(); } }, list.map(([v, t]) => h('option', { value: v, text: t }))); s.value = B[key]; return s; };
  if (!keys.includes(B.k)) B.k = keys[0];
  const out = h('div');
  const draw = () => {
    ctx.hideTip();
    const m = mt(B.k), unit = m.u ? ` (${m.u})` : '';
    let G = benchmark(S, byWa, { k: B.k, by: B.by, pass: w => pass(w) });
    if (!G.length) { out.replaceChildren(h('div', { class: 'fvm-empty', text: 'No charted stages with this measure under these filters.' })); return; }
    G.sort((a, b) => (a.other - b.other) || (B.order === 'name' ? String(a.key).localeCompare(String(b.key), undefined, { numeric: true }) : b.p50 - a.p50));
    const all = G.reduce((n, g) => n + g.n, 0), nW = new Set(G.flatMap(g => g.wells)).size;
    const show = g => ctx.toMap({ wells: g.wells.slice(0, 1500), title: `Discover: ${m.t}, ${g.key}` });
    const byT = (BM_BY.find(b => b[0] === B.by) || [, 'Group'])[1];
    const D = { key: { t: byT }, n: { t: 'Stages', n: 1, d: 0 }, nWells: { t: 'Wells', n: 1, d: 0 },
      p10: { t: 'P10', n: 1, d: m.d }, p25: { t: 'P25', n: 1, d: m.d }, p50: { t: 'Median', n: 1, d: m.d }, p75: { t: 'P75', n: 1, d: m.d }, p90: { t: 'P90', n: 1, d: m.d },
      stages: { t: 'Stages charted', n: 1, d: 0 }, ...Object.fromEntries(OPF.map(f => [f, { t: OPF_T[f], u: 'share of stages', n: 1, d: 1, v: x => (x == null ? '–' : (x * 100).toFixed(1) + '%') }])) };
    const plot = plotBox(h);
    put(out,
      h('div', { class: 'fvm-count' }, h('b', { text: `${fmtN(all)} stages · ${fmtN(nW)} wells` }), h('span', { class: 'fvm-pill', text: `${G.length} groups` })),
      card(h, `${m.t}${unit} per stage, by ${byT.toLowerCase()}`, plot,
        legendBox(h, [{ c: ink(0), kind: 'box', t: 'middle half (P25–P75), median marked' }, { c: ink(0), kind: 'line', t: 'P10 to P90' }])),
      h('div', { class: 'fvm-count', style: 'margin-top:.8em' },
        h('button', { type: 'button', text: 'Download CSV', onclick: () => download(`fracview-stage-${B.k}-by-${B.by}.csv`, ['key', 'n', 'nWells', 'p10', 'p25', 'p50', 'p75', 'p90', 'stages', ...OPF], G.map(r6), D) }),
        h('span', { class: 'fvm-note', style: 'margin:0', text: 'Click a group, here or on the chart, for its wells on the map.' })),
      table(G, ['key', 'n', 'nWells', 'p10', 'p25', 'p50', 'p75', 'p90'], ctx, g => show(g), 300, { defs: D, st: B.st }),
      card(h, 'Operational flags, share of charted stages', table(G, ['key', 'stages', ...OPF], ctx, g => show(g), 300, { defs: D, st: B.fst || (B.fst = { sort: 'screenout', dir: -1 }), cls: 'fvd-compact' })),
      h('p', { class: 'fvm-note', text: `Every stage read off the treatment charts, for the wells the filters keep${M ? '' : ' (metrics.js did not load, so ISIP is the falloff only)'}. P10 to P90 are the 10th to 90th percentiles of the stages in a group (low to high); groups with fewer than 30 stages are pooled as Other. ${m.t === 'ISIP' ? 'ISIP is the operator’s filed value where given, else read from the falloff. ' : ''}Flags: ${OPF.map(f => `${OPF_T[f].toLowerCase()}: ${M ? M.FLAG_INFO[f].d.replace(/\.$/, '').toLowerCase() : f}`).join('; ')}. Spikes, breaks and shutdowns need second-by-second curves, so wells charted from the coarser series show fewer. Differences between groups describe the jobs, not their causes: operators, years and fields differ in many ways at once.` }));
    // the boxes
    const k = tscale(), fs = 11 * k, rowH = Math.round(28 * k);
    const lab = g => (g.key.length > 22 ? g.key.slice(0, 21) + '…' : g.key);
    const lw = Math.min(Math.round((plot.clientWidth || 600) * .4), Math.round(fs * .62 * Math.max(6, ...G.map(g => lab(g).length))) + 12);
    const lo = Math.min(...G.map(g => g.p10)), hi = Math.max(...G.map(g => g.p90)), padX = (hi - lo) * .04 || Math.abs(hi) * .05 || 1;
    const F = frame(plot, { x: { min: lo - padX, max: hi + padX, label: `${m.t}${unit}` }, y: null, l: lw + 10, t: Math.round(fs * .5), h: G.length * rowH + Math.round(fs * .5) + Math.round(fs * 3.6),
      aria: `${m.t} per stage by group: ${G.map(g => `${g.key} median ${sig(g.p50)}`).join(', ')}` });
    const c = ink(0), bh = Math.min(16 * k, rowH - 8);
    G.forEach((g, i) => {
      const yc = F.P.t + i * rowH + rowH / 2;
      sv('text', { x: F.P.l - 8, y: yc + fs * .35, 'text-anchor': 'end', class: 'lab' }, F.svg, lab(g));
      sv('line', { x1: F.X(g.p10), x2: F.X(g.p90), y1: yc, y2: yc, stroke: c, 'stroke-width': 2, 'stroke-linecap': 'round', 'stroke-opacity': .6 }, F.svg);
      sv('rect', { x: F.X(g.p25), y: yc - bh / 2, width: Math.max(3, F.X(g.p75) - F.X(g.p25)), height: bh, rx: 4, fill: c, 'fill-opacity': g.other ? .4 : .85 }, F.svg);
      sv('line', { x1: F.X(g.p50), x2: F.X(g.p50), y1: yc - bh / 2, y2: yc + bh / 2, stroke: 'var(--m-panel)', 'stroke-width': 2.5 }, F.svg);
      const tipL = () => [[`${g.key}`, 1], [`median ${sig(g.p50)}${m.u ? ' ' + m.u : ''}`], [`middle half ${sig(g.p25)}–${sig(g.p75)} · P10–P90 ${sig(g.p10)}–${sig(g.p90)}`],
        [`${fmtN(g.n)} stages · ${fmtN(g.nWells)} wells`], ['Click for these wells on the map']];
      const hit = sv('rect', { x: 0, y: yc - rowH / 2, width: F.W, height: rowH, fill: 'transparent', class: 'hit row', tabindex: 0, role: 'button', 'aria-label': `${g.key}: median ${sig(g.p50)} ${m.u || ''}, ${g.n} stages. Show on the map` }, F.svg);
      hit.addEventListener('pointermove', e => tipK(ctx, e, tipL())); hit.addEventListener('pointerleave', ctx.hideTip);
      hit.addEventListener('focus', e => tipK(ctx, e, tipL())); hit.addEventListener('blur', ctx.hideTip);
      hit.addEventListener('click', () => { ctx.hideTip(); show(g); });
      hit.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); show(g); } });
    });
  };
  pane.append(h('h1', { text: 'Stage benchmarks' }),
    h('p', { class: 'fvm-sub', text: 'How one stage measure, read off the treatment charts, spreads across operators, years or fields, stage by stage.' }),
    h('div', { class: 'fvm-filters fvd-controls' },
      h('label', null, 'Stage measure', sel('k', 'Stage measure', keys.map(k => [k, mt(k).t + (mt(k).u ? ` (${mt(k).u})` : '')]))),
      h('label', null, 'Group by', sel('by', 'Group by', BM_BY)),
      h('label', null, 'Order', sel('order', 'Order', [['median', 'By median, high first'], ['name', 'By name']]))),
    out, folded(W, ctx, draw));
  live = { pane, redraw: draw, charts: true };
  draw();
}

// ---------- Type curves ----------
const ymN = s => { const [y, m] = String(s).split('-').map(Number); return y * 12 + (m || 1) - 1; };
const daysIn = n => { const y = Math.floor(n / 12), m = n % 12 + 1; return m === 2 ? ((y % 4 === 0 && y % 100) || y % 400 === 0 ? 29 : 28) : [4, 6, 9, 11].includes(m) ? 30 : 31; };
// every well lined up on its first producing month (prod `f`): at month i the
// calendar-day rate (volume over the days in that month) or the cumulative,
// optionally per 100 m of lateral or per tonne of proppant; a well counts at a
// month only if it reported that month; a group's curve stops below `minN` wells
function typeCurves(rows, P, o) {
  const thr = ymN(P.through), M = o.months || 24, minN = o.minN ?? 5, keyOf = o.keys || (() => ['All']), G = new Map();
  for (const w of rows) {
    const p = P.wells[pad5(w.wa)]; if (!p || !p.f) continue;
    const k = o.norm === 'lat' ? (w.lateral > 0 ? 100 / w.lateral : null) : o.norm === 'prop' ? (w.proppant > 0 ? 1 / w.proppant : null) : 1;
    if (k == null) continue;
    const s = o.fluid === 'water' ? p.w : o.fluid === 'liquids' ? p.c.map((v, i) => (v || 0) + ((p.o || [])[i] || 0)) : p.g;
    const f = ymN(p.f), vals = [];
    let cum = 0;
    for (let i = 0; i < M && i < s.length && f + i <= thr; i++) { const v = s[i] || 0; cum += v; vals.push((o.basis === 'cum' ? cum : v / daysIn(f + i)) * k); }
    if (!vals.length) continue;
    for (const key of keyOf(w)) {
      let g = G.get(key); if (!g) G.set(key, g = { key, wells: [], at: Array.from({ length: M }, () => []) });
      g.wells.push(w.wa); vals.forEach((v, i) => g.at[i].push(v));
    }
  }
  return [...G.values()].map(g => {
    let stop = false;
    const months = g.at.map((a, i) => {
      a.sort((x, y) => x - y);
      if (a.length < minN) stop = true;
      return stop ? { m: i + 1, n: a.length, p10: null, p50: null, p90: null } : { m: i + 1, n: a.length, p10: pct(a, .1), p50: pct(a, .5), p90: pct(a, .9) };
    });
    return { key: g.key, n: g.wells.length, wells: g.wells, months };
  });
}
function curves(pane, W, ctx, [P, glist]) {
  const { h } = ctx;
  const T = state.tc;
  const sel = (key, lab, list, num) => { const s = h('select', { 'aria-label': lab, onchange: e => { T[key] = num ? +e.target.value : e.target.value; saveState(); draw(); } }, list.map(([v, t]) => h('option', { value: v, text: t }))); s.value = String(T[key]); return s; };
  const BYS = [['operator', 'Operator'], ['year', 'Year completed'], ['relation', 'Parent / child'], ['formation', 'Formation'], ['field', 'Field'], ['groups', glist.some(g => g.own) ? 'Prepared areas and my groups' : 'Prepared areas']];
  const out = h('div');
  const draw = () => {
    ctx.hideTip();
    const cat = categories(T.by, W, glist);
    const rows = W.filter(w => pass(w));
    const M = Math.max(T.months, 24);
    const G = typeCurves(rows, P, { fluid: T.fluid, basis: T.basis, norm: T.norm, months: M, keys: cat.of });
    G.sort((a, b) => cat.order.indexOf(a.key) - cat.order.indexOf(b.key));
    const vol = { gas: 'e³m³', liquids: 'm³', water: 'm³' }[T.fluid], fl = { gas: 'Gas', liquids: 'Condensate and oil', water: 'Water' }[T.fluid];
    const per = { none: '', lat: ' per 100 m', prop: ' per t' }[T.norm];
    const unit = (T.basis === 'cum' ? vol : vol + '/d') + per;
    const ytitle = `${fl}, ${T.basis === 'cum' ? 'cumulative' : 'calendar-day rate'} (${unit})`;
    if (!G.length) { out.replaceChildren(h('div', { class: 'fvm-empty', text: 'No wells with production under these filters.' })); return; }
    if (!G.some(g => g.key === T.sel)) T.sel = (G.slice().sort((a, b) => b.n - a.n)[0] || {}).key;
    const D = { key: { t: 'Group' }, n: { t: 'Wells', n: 1, d: 0 }, m3: { t: 'Month 3', u: unit, n: 1 }, m6: { t: 'Month 6', u: unit, n: 1 }, m12: { t: 'Month 12', u: unit, n: 1 }, m24: { t: 'Month 24', u: unit, n: 1 } };
    ['m3', 'm6', 'm12', 'm24'].forEach(k => { D[k].v = x => sig(x); });
    const p50At = (g, m) => (g.months[m - 1] || {}).p50 ?? null;
    const tab = G.map(g => ({ key: g.key, n: g.n, m3: p50At(g, 3), m6: p50At(g, 6), m12: p50At(g, 12), m24: p50At(g, 24), wells: g.wells }));
    const plot = plotBox(h);
    const csv = () => download(`fracview-type-curves-${T.fluid}-${T.basis}.csv`, ['group', 'month', 'wells', 'p10', 'p50', 'p90'],
      G.flatMap(g => g.months.map(m => r6({ group: g.key, month: m.m, wells: m.n, p10: m.p10, p50: m.p50, p90: m.p90 }))), {});
    put(out,
      h('div', { class: 'fvm-count' }, h('b', { text: `${fmtN(new Set(G.flatMap(g => g.wells)).size)} wells with production` }), h('span', { class: 'fvm-pill', text: `through ${P.through}` })),
      card(h, `${fl}${per ? per.replace(' per', ', per') : ''}, ${T.basis === 'cum' ? 'cumulative' : 'rate'}: the middle well per ${(BYS.find(b => b[0] === T.by) || [, 'group'])[1].toLowerCase().replace('prepared areas and my groups', 'group').replace('prepared areas', 'area')}`, plot, legendBox(h, [...G.map(g => ({ c: cat.col(g.key), kind: 'line', t: `${g.key} · ${g.n} wells`, pressed: g.key === T.sel, title: 'Show this group’s P10–P90 band',
        on: () => { T.sel = g.key; saveState(); draw(); } })), { c: cat.col(T.sel), kind: 'band', t: `P10–P90, ${T.sel}` }])),
      h('div', { class: 'fvm-count', style: 'margin-top:.8em' }, h('button', { type: 'button', text: 'Download CSV', onclick: csv }),
        h('span', { class: 'fvm-note', style: 'margin:0', text: 'The middle well (P50) of each group at 3, 6, 12 and 24 months; click a group for its wells on the map.' })),
      table(tab, ['key', 'n', 'm3', 'm6', 'm12', 'm24'], ctx, g => ctx.toMap({ wells: g.wells.slice(0, 1500), title: `Discover: type curve, ${g.key}` }), 300, { defs: D, st: T.st || (T.st = { sort: 'n', dir: -1 }) }),
      h('p', { class: 'fvm-note', text: `From the BCER’s monthly volumes${T.fluid === 'liquids' ? ' (condensate plus oil)' : ''}. Each well starts at its first producing month; a calendar-day rate is the month’s volume over the days in that month, so the first, part month reads low. A well counts at a month only if it had reported that far, so later months lean towards older wells, and a curve stops where fewer than 5 wells remain. P10 and P90 here are the 10th and 90th percentiles of the wells (low to high), not the reserves convention. ${T.by === 'groups' ? 'A well in two groups counts in both. ' : ''}${T.by === 'relation' ? 'Parent and child follow the limits in Settings. ' : ''}Groups differ in more than the one thing they are grouped by.` }));
    // the chart
    const shown = G.map(g => ({ ...g, pts: g.months.slice(0, T.months) }));
    const band = shown.find(g => g.key === T.sel);
    const ymax = Math.max(...shown.flatMap(g => g.pts.map(p => (g === band ? p.p90 : p.p50) || 0)), 1e-9);
    const F = frame(plot, { x: { min: 1, max: T.months, label: 'Months from first production', ticks: (st => [1, ...Array.from({ length: Math.floor(T.months / st) }, (_, i) => (i + 1) * st).filter(v => v > 1)])(T.months <= 12 ? 1 : T.months <= 24 ? 3 : T.months <= 36 ? 6 : 12) },
      y: { min: 0, max: ymax * 1.04, label: ytitle, fmt: sig }, yw: 4.2, aria: `${ytitle}, median per group` });
    if (band) {
      const ok = band.pts.filter(p => p.p50 != null);
      if (ok.length > 1) sv('path', { d: 'M' + ok.map(p => `${F.X(p.m).toFixed(1)},${F.Y(p.p90).toFixed(1)}`).join('L') + 'L' + ok.slice().reverse().map(p => `${F.X(p.m).toFixed(1)},${F.Y(p.p10).toFixed(1)}`).join('L') + 'Z',
        fill: cat.col(band.key), 'fill-opacity': .13, stroke: 'none' }, F.svg);
    }
    for (const g of shown) {
      const ok = g.pts.filter(p => p.p50 != null); if (!ok.length) continue;
      const c = cat.col(g.key);
      sv('polyline', { points: ok.map(p => `${F.X(p.m).toFixed(1)},${F.Y(p.p50).toFixed(1)}`).join(' '), fill: 'none', stroke: c, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, F.svg);
      const e = ok[ok.length - 1]; sv('circle', { cx: F.X(e.m), cy: F.Y(e.p50), r: 4, fill: c, class: 'end' }, F.svg);
    }
    const xs = Array.from({ length: T.months }, (_, i) => F.X(i + 1));
    crosshair(F, xs, ctx, i => [[`Month ${i + 1}`, 1], ...shown.map(g => { const p = g.pts[i]; return p && p.p50 != null ? [`${g.key}: ${sig(p.p50)} ${unit} · ${p.n} wells${g === band ? ` (P10–P90 ${sig(p.p10)}–${sig(p.p90)})` : ''}`, 0, cat.col(g.key)] : [`${g.key}: ${p ? p.n : 0} wells, too few`, 0, cat.col(g.key)]; })]);
  };
  pane.append(h('h1', { text: 'Type curves' }),
    h('p', { class: 'fvm-sub', text: 'Production lined up on each well’s first producing month: the middle well of each group and the spread around it.' }),
    h('div', { class: 'fvm-filters fvd-controls' },
      h('label', null, 'Fluid', sel('fluid', 'Fluid', [['gas', 'Gas'], ['liquids', 'Condensate and oil'], ['water', 'Water']])),
      h('label', null, 'Basis', sel('basis', 'Basis', [['rate', 'Rate per month (calendar day)'], ['cum', 'Cumulative']])),
      h('label', null, 'Normalise', sel('norm', 'Normalise', [['none', 'None'], ['lat', 'Per 100 m of lateral'], ['prop', 'Per tonne of proppant']])),
      h('label', null, 'Group by', sel('by', 'Group by', BYS)),
      h('label', null, 'Months shown', sel('months', 'Months shown', [[12, '12'], [24, '24'], [36, '36'], [60, '60']], true))),
    out, folded(W, ctx, draw));
  live = { pane, redraw: draw, charts: true };
  draw();
}

// ---------- Parent & child ----------
// a child's first-year gas per 100 m against the mean of its parents' (those with the number)
function degradation(rows, byWa) {
  const out = [];
  for (const w of rows) {
    if (w.relation !== 'child' || w.gas12Per100m == null) continue;
    const ps = (w.parentWas || []).map(wa => byWa.get(String(wa))).filter(p => p && p.gas12Per100m != null);
    if (!ps.length) continue;
    const mean = ps.reduce((n, p) => n + p.gas12Per100m, 0) / ps.length;
    if (!(mean > 0)) continue;
    out.push({ w, parents: ps, parentMean: mean, ratio: w.gas12Per100m / mean });
  }
  return out;
}
function parentChild(pane, W, ctx) {
  const { h, fmt } = ctx;
  const Mx = window.FVMetrics;
  const byWa = new Map(W.map(w => [String(w.wa), w]));
  const out = h('div');
  const lim = Mx ? Mx.limits() : { across: 400, vertical: 100, siblingDays: 90 };
  let t = 0;
  const setLim = () => { clearTimeout(t); t = setTimeout(() => { const v = {}; for (const [k, el] of Object.entries(inputs)) if (el.value !== '' && +el.value > 0) v[k] = +el.value; if (Mx) Mx.setLimits(v); }, 350); };
  const inputs = Object.fromEntries([['across', 10], ['vertical', 10], ['siblingDays', 5]].map(([k, step]) => [k, h('input', { type: 'number', min: 1, step, value: lim[k], oninput: setLim })]));
  const draw = () => {
    ctx.hideTip();
    const rows = W.filter(w => pass(w));
    const rels = Object.keys(REL_T), bnds = Object.keys(BND_T);
    const n = (r, b) => rows.filter(w => w.relation === r && (!b || w.bounded === b)).length;
    const deg = degradation(rows, byWa).sort((a, b) => a.ratio - b.ratio);
    const ratios = deg.map(d => d.ratio), medR = pct(ratios, .5), q1 = pct(ratios, .25), q3 = pct(ratios, .75);
    const sc = rows.filter(w => w.nnH != null && w.gas12Per100m != null);
    const plotA = plotBox(h), plotB = plotBox(h), plotC = plotBox(h);
    const D = { name: COL.name, wa: COL.wa, padName: COL.padName, nPar: { t: 'Parents', n: 1, d: 0 }, parentNames: { t: 'Parent wells' }, depletionDays: COL.depletionDays,
      gas12Per100m: { t: 'Child gas, 12 mo per 100 m', u: 'e³m³', n: 1, d: 0 }, parentMean: { t: 'Parents’ mean', u: 'e³m³', n: 1, d: 0 }, ratio: { t: 'Child ÷ parents', n: 1, v: x => pctTxt(x) } };
    const tab = deg.map(d => ({ ...d.w, nPar: d.parents.length, parentNames: d.parents.map(p => p.wa).join(', '), parentMean: d.parentMean, ratio: d.ratio, _d: d }));
    put(out,
      card(h, 'Wells by relation and boundedness',
        h('div', { class: 'fvm-tablewrap fvd-auto' }, h('table', { class: 'fvm-table fvd-compact' },
          h('thead', null, h('tr', null, h('th', { text: 'Relation' }), ...bnds.map(b => h('th', { class: 'num', text: BND_T[b].replace(/ \(.*/, '') })), h('th', { class: 'num', text: 'All' }))),
          h('tbody', null, rels.map(r => h('tr', { class: 'still' }, h('td', null, h('i', { class: 'fvd-sw', style: `--c:${relInk(r)}` }), REL_T[r]), ...bnds.map(b => h('td', { class: 'num', text: fmtN(n(r, b)) })), h('td', { class: 'num', text: fmtN(n(r)) }))),
            h('tr', { class: 'still fvd-total' }, h('td', { text: 'All' }), ...bnds.map(b => h('td', { class: 'num', text: fmtN(rows.filter(w => w.bounded === b).length) })), h('td', { class: 'num', text: fmtN(rows.length) }))))),
        h('p', { class: 'fvm-note', text: `${Object.entries(REL_T).map(([k, v]) => `${v}: ${Mx ? Mx.REL[k].d.toLowerCase() : k}`).join('. ')}. Bounded: offsets within the limits on both sides of the lateral, at any time.` })),
      card(h, 'Spacing against first-year gas', plotA, legendBox(h, rels.map(r => ({ c: relInk(r), t: `${REL_T[r]} · ${sc.filter(w => w.relation === r).length}` })).concat([{ c: 'var(--m-mut)', kind: 'line', t: 'lines: median per relation' }])),
        h('p', { class: 'fvm-note', text: 'Each dot is a well: its nearest lateral across (measured where the two run side by side) against its first 12 producing months of gas per 100 m of lateral. Lines are the median gas in equal-count bands of spacing, per relation.' })),
      deg.length ? h('div', { class: 'fvd-head' }, h('b', { text: `Children made a median of ${pctTxt(medR)} of their parents’ first-year gas per 100 m` }),
        h('span', { text: ` (${fmtN(deg.length)} child wells with a parent that has the number; middle half ${pctTxt(q1)}–${pctTxt(q3)}).` })) : h('div', { class: 'fvm-empty', text: 'No child wells with a parent’s first-year gas under these filters and limits.' }),
      deg.length ? h('div', { class: 'fvd-grid2' },
        card(h, 'Child ÷ parents, how many wells', plotB),
        card(h, 'Child ÷ parents against how long the parents had produced', plotC)) : null,
      deg.length ? h('div', { class: 'fvm-count', style: 'margin-top:.8em' }, h('button', { type: 'button', text: 'Download CSV', onclick: () => download('fracview-child-wells.csv', ['wa', 'name', 'padName', 'nPar', 'parentNames', 'depletionDays', 'gas12Per100m', 'parentMean', 'ratio'], tab.map(({ _d, ...r }) => r6(r)), D) }),
        h('span', { class: 'fvm-note', style: 'margin:0', text: 'Click a child for the wine racks of its pad and its parents’.' })) : null,
      deg.length ? table(tab, ['name', 'wa', 'padName', 'nPar', 'depletionDays', 'gas12Per100m', 'parentMean', 'ratio'], ctx,
        r => ctx.toMap({ pads: [...new Set([r.pad, ...r._d.parents.map(p => p.pad)])].filter(Boolean), racks: true, title: r.padName }), 300, { defs: D, st: state.pc.st }) : null,
      h('p', { class: 'fvm-note', text: 'A child here is a well fracked while an offset within the limits had been producing; its ratio is its first 12 producing months of gas per 100 m of lateral over the mean of its parents’ (their own first 12 months, so earlier and often in fresher rock). This is an association: children also differ from their parents in year, design, landing and operator, and some came in on purpose to drain what the parent left. Wells reported to the BCER, so liquids-rich wells and short histories are left out where the first 12 months are not complete.' }));
    // a: spacing vs gas
    if (sc.length > 2) {
      const xs = sc.map(w => w.nnH).sort((a, b) => a - b), ys = sc.map(w => w.gas12Per100m).sort((a, b) => a - b);
      const x1 = pct(xs, .99), y1 = pct(ys, .99);
      const F = frame(plotA, { x: { min: 0, max: x1, label: 'Nearest lateral across (m)' }, y: { min: 0, max: y1, label: 'Gas, first 12 months per 100 m (e³m³)' }, aria: `First-year gas per 100 m against spacing for ${sc.length} wells` });
      const pts = [];
      const g = sv('g', {}, F.svg);
      for (const w of sc) { const x = F.X(Math.min(w.nnH, x1)), y = F.Y(Math.min(w.gas12Per100m, y1)); sv('circle', { cx: x.toFixed(1), cy: y.toFixed(1), r: 4, fill: relInk(w.relation), 'fill-opacity': .7, class: 'dot' }, g); pts.push({ x, y, d: w }); }
      for (const r of rels) {
        const tr = trend(sc.filter(w => w.relation === r).map(w => [w.nnH, w.gas12Per100m]), 6, 12);
        if (tr.length < 2) continue;
        const pl = tr.map(([a, b]) => `${F.X(Math.min(a, x1)).toFixed(1)},${F.Y(Math.min(b, y1)).toFixed(1)}`).join(' ');
        sv('polyline', { points: pl, fill: 'none', stroke: 'var(--m-panel)', 'stroke-width': 6, 'stroke-linejoin': 'round', 'stroke-opacity': .9 }, F.svg);    // a halo over the dots
        sv('polyline', { points: pl, fill: 'none', stroke: relInk(r), 'stroke-width': 2.5, 'stroke-linejoin': 'round', class: 'trend' }, F.svg);
      }
      nearest(F, pts, ctx, w => [[w.name, 1], [`${REL_T[w.relation]} · ${short(w.operator)} · ${w.year}`, 0, relInk(w.relation)], [`${fmt(w.nnH)} m to the nearest lateral`], [`${fmt(w.gas12Per100m)} e³m³ per 100 m in 12 months`], ['Click for the map, its charts or its wine rack']], (w, e) => wellMenu(w, e, ctx));
    } else plotA.replaceChildren(h('div', { class: 'fvm-empty', text: 'Too few wells with both numbers.' }));
    if (!deg.length) return;
    // b: histogram of ratios, 10% bands to 200%+
    const bins = Array.from({ length: 21 }, (_, i) => ({ lo: i / 10, n: 0 }));
    for (const r of ratios) bins[Math.min(20, Math.max(0, Math.floor(r * 10)))].n++;
    const top = Math.max(...bins.map(b => b.n));
    const Fb = frame(plotB, { x: { min: 0, max: 2.1, label: 'Child ÷ mean of parents (first-year gas per 100 m)', ticks: [0, .5, 1, 1.5, 2], fmt: v => `${Math.round(v * 100)}%${v >= 2 ? '+' : ''}` },
      y: { min: 0, max: top * 1.08, label: 'Child wells' }, yw: 3.4, aria: `Histogram of child to parent ratios, median ${pctTxt(medR)}` });
    const bw = Fb.X(.1) - Fb.X(0);
    bins.forEach(b => {
      const x = Fb.X(b.lo) + 1, y = Fb.Y(b.n), hh = Fb.Y(0) - y;
      if (b.n) sv('path', { d: colPath(x, y, Math.max(1, bw - 2), hh), fill: ink(0), 'fill-opacity': .85 }, Fb.svg);
      const hit = sv('rect', { x: Fb.X(b.lo), y: Fb.P.t, width: bw, height: Fb.ph, fill: 'transparent', class: 'hit' }, Fb.svg);
      const tl = () => [[`${b.n} child well${b.n === 1 ? '' : 's'}`, 1], [b.lo >= 2 ? '200% of the parents or more' : `${Math.round(b.lo * 100)}–${Math.round(b.lo * 100 + 10)}% of the parents`]];
      hit.addEventListener('pointermove', e => tipK(ctx, e, tl())); hit.addEventListener('pointerleave', ctx.hideTip);
    });
    sv('line', { x1: Fb.X(medR), x2: Fb.X(medR), y1: Fb.P.t, y2: Fb.P.t + Fb.ph, stroke: 'var(--m-ink)', 'stroke-width': 2 }, Fb.svg);
    sv('text', { x: Fb.X(medR) + 5, y: Fb.P.t + Fb.fs, class: 'lab' }, Fb.svg, `median ${pctTxt(medR)}`);
    sv('line', { x1: Fb.X(1), x2: Fb.X(1), y1: Fb.P.t, y2: Fb.P.t + Fb.ph, class: 'ref' }, Fb.svg);
    // c: ratio against depletion days
    const dd = deg.filter(d => d.w.depletionDays != null);
    if (dd.length > 2) {
      const xs = dd.map(d => d.w.depletionDays).sort((a, b) => a - b), x1 = Math.max(30, pct(xs, .99));
      const y1 = Math.max(1.2, Math.min(3, pct(ratios, .98)));
      const Fc = frame(plotC, { x: { min: 0, max: x1, label: 'Days the parents had produced before the child’s frac' }, y: { min: 0, max: y1, label: 'Child ÷ parents', fmt: v => `${Math.round(v * 100)}%` }, yw: 3.4,
        aria: `Child to parent ratio against depletion days for ${dd.length} wells` });
      sv('line', { x1: Fc.P.l, x2: Fc.P.l + Fc.pw, y1: Fc.Y(1), y2: Fc.Y(1), class: 'ref' }, Fc.svg);
      const pts = [];
      for (const d of dd) { const x = Fc.X(Math.min(d.w.depletionDays, x1)), y = Fc.Y(Math.min(d.ratio, y1)); sv('circle', { cx: x.toFixed(1), cy: y.toFixed(1), r: 4, fill: relInk('child'), 'fill-opacity': .7, class: 'dot' }, Fc.svg); pts.push({ x, y, d }); }
      const tr = trend(dd.map(d => [d.w.depletionDays, d.ratio]), 6, 10);
      if (tr.length > 1) for (const [st, sw] of [['var(--m-panel)', 6], ['var(--m-ink)', 2]]) sv('polyline', { points: tr.map(([a, b]) => `${Fc.X(Math.min(a, x1)).toFixed(1)},${Fc.Y(Math.min(b, y1)).toFixed(1)}`).join(' '), fill: 'none', stroke: st, 'stroke-width': sw, 'stroke-linejoin': 'round' }, Fc.svg);
      nearest(Fc, pts, ctx, d => [[d.w.name, 1], [`${pctTxt(d.ratio)} of its parents’ first-year gas per 100 m`], [`parents producing ${fmtN(d.w.depletionDays)} days before its frac`], [`${d.parents.length} parent${d.parents.length === 1 ? '' : 's'}: ${d.parents.map(p => p.wa).join(', ')}`], ['Click for the wine racks']],
        d => ctx.toMap({ pads: [...new Set([d.w.pad, ...d.parents.map(p => p.pad)])].filter(Boolean), racks: true, title: d.w.padName }));
      plotC.after(h('p', { class: 'fvm-note', text: `The line is the median ratio in equal-count bands of depletion time; the faint line marks 100%.${ratios.some(r => r > y1) ? ` Ratios above ${Math.round(y1 * 100)}% are held at the top edge.` : ''}` }));
    } else plotC.replaceChildren(h('div', { class: 'fvm-empty', text: 'Too few children with dated parents.' }));
  };
  pane.append(h('h1', { text: 'Parent & child' }),
    h('p', { class: 'fvm-sub', text: 'Which wells came in next to producing ones, and how much gas the children made against their parents.' }),
    h('div', { class: 'fvm-filters fvd-controls' },
      h('label', null, 'Offset within, across (m)', inputs.across), h('label', null, 'and vertically (m)', inputs.vertical), h('label', null, 'Fracked together within (days)', inputs.siblingDays),
      h('div', { class: 'wide' }, h('span', { class: 'fvm-note', style: 'margin:0', text: Mx ? 'These are the limits in Settings: changing them here relabels every view.' : 'The spacing labels could not be loaded; showing the defaults.' }),
        h('button', { type: 'button', text: 'Defaults', disabled: !Mx, onclick: () => { const d = Mx.DEF_LIMITS; Object.entries(inputs).forEach(([k, el]) => { el.value = d[k]; }); Mx.setLimits(d); } }))),
    out, folded(W, ctx, draw));
  live = { pane, redraw: draw, charts: true };
  draw();
}

// ---------- Seismicity ----------
const LOG10E = Math.LOG10E;
// Gutenberg–Richter: counts in ΔM bins, Mc by maximum curvature (+ corr), b by
// Aki–Utsu maximum likelihood with Utsu's bin correction, Shi & Bolt's error
function gr(mags, o = {}) {
  const dM = o.dM || 0.1, corr = o.corr ?? 0.2, key = m => Math.round(m / dM);
  const cnt = new Map();
  for (const m of mags) if (m != null && isFinite(m)) cnt.set(key(m), (cnt.get(key(m)) || 0) + 1);
  if (!cnt.size) return { bins: [], n: 0, nAbove: 0, mc: null, b: null, sb: null, a: null };
  const ks = [...cnt.keys()].sort((a, b) => a - b), bins = [];
  for (let k = ks[0]; k <= ks[ks.length - 1]; k++) bins.push({ m: +(k * dM).toFixed(4), n: cnt.get(k) || 0, cum: 0 });
  for (let i = bins.length - 1, c = 0; i >= 0; i--) { c += bins[i].n; bins[i].cum = c; }
  const peak = bins.reduce((a, b) => (b.n > a.n ? b : a));
  const mc = +(peak.m + corr).toFixed(4);
  const above = mags.filter(m => m != null && isFinite(m) && key(m) * dM >= mc - dM / 2 + 1e-9).map(m => key(m) * dM);
  const n = above.length;
  if (n < 2) return { bins, n: mags.length, nAbove: n, mc, b: null, sb: null, a: null };
  const mean = above.reduce((s, m) => s + m, 0) / n;
  const b = LOG10E / (mean - (mc - dM / 2));
  const v = above.reduce((s, m) => s + (m - mean) ** 2, 0) / (n * (n - 1));
  const sb = 2.3 * b * b * Math.sqrt(v);
  return { bins, n: mags.length, nAbove: n, mc, b, sb, a: Math.log10(n) + b * mc, mean };
}
const moment = m => 10 ** (1.5 * m + 9.1);               // N·m, from Mw (ML taken as Mw)
const G_SHEAR = 3e10;                                       // Pa
const mcgarr = dv => G_SHEAR * dv;                          // McGarr (2014): M0max = G·ΔV, ΔV in m³
// plan distance (km) from a point to the segment a–b, all {x, y} in km
function segDist(p, a, b) {
  const dx = b.x - a.x, dy = b.y - a.y, L = dx * dx + dy * dy;
  const t = L ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / L)) : 0;
  return Math.hypot(p.x - a.x - t * dx, p.y - a.y - t * dy);
}
const LOCAL = -7 * 3600e3;                                  // NE BC keeps UTC-7 all year
const dayMs = s => Date.parse(String(s).slice(0, 10) + 'T00:00:00Z') - LOCAL;
const localDay = t => new Date(t + LOCAL).toISOString().slice(0, 10);
const addDays = (s, n) => new Date(Date.parse(s + 'T00:00:00Z') + n * 864e5).toISOString().slice(0, 10);
const SRC_T = { bcsrc: 'BCSRC relocated', bcer: 'BCER', nrcan: 'Earthquakes Canada' };
const srcT = s => SRC_T[s] || 'Earthquakes Canada';
const LV = { none: [0, '●', 'None'], below: [1, '○', 'Below notify'], notify: [2, '▲', 'Notify'], mitigate: [3, '◆', 'Mitigate'], suspend: [4, '■', 'Suspend'] };
// the earthquakes within `km` of any of the wells' laterals (heel to toe, straight), between two local dates
function nearLaterals(E, ws, km, from, to) {
  const lat0 = ws.reduce((s, w) => s + w.lat, 0) / ws.length, kx = 111.32 * Math.cos(lat0 * Math.PI / 180), ky = 110.574;
  const xy = (lat, lon) => ({ x: lon * kx, y: lat * ky });
  const segs = ws.filter(w => w.lat != null && w.lon != null).map(w => {
    const a = xy(w.lat, w.lon), b = xy(w.toeLat ?? w.lat, w.toeLon ?? w.lon);
    return { a, b, x0: Math.min(a.x, b.x) - km, x1: Math.max(a.x, b.x) + km, y0: Math.min(a.y, b.y) - km, y1: Math.max(a.y, b.y) + km };
  });
  // each lateral filed under the grid cells its reach covers, so an event checks only its own cell's
  const cs = Math.max(2, km), grid = new Map(), cell = (i, j) => i + ',' + j;
  for (const s of segs) for (let i = Math.floor(s.x0 / cs); i <= Math.floor(s.x1 / cs); i++) for (let j = Math.floor(s.y0 / cs); j <= Math.floor(s.y1 / cs); j++) {
    const k = cell(i, j); if (!grid.has(k)) grid.set(k, []); grid.get(k).push(s);
  }
  const t0 = dayMs(from), t1 = dayMs(to) + 864e5, F = E.fields || ['t', 'lat', 'lon', 'depth_km', 'mag', 'mag_type', 'fixed', 'industry', 'src', 'herr_m', 'derr_m', 'match'];
  const I = Object.fromEntries(F.map((f, i) => [f, i])), out = [];
  for (const r of E.rows) {
    const m = r[I.mag]; if (m == null) continue;
    const t = Date.parse(r[I.t]); if (!(t >= t0 && t < t1)) continue;
    const p = xy(r[I.lat], r[I.lon]), near = grid.get(cell(Math.floor(p.x / cs), Math.floor(p.y / cs)));
    if (!near) continue;
    let d = Infinity;
    for (const s of near) { if (p.x < s.x0 || p.x > s.x1 || p.y < s.y0 || p.y > s.y1) continue; const v = segDist(p, s.a, s.b); if (v < d) d = v; }
    if (d <= km) out.push({ t, time: r[I.t], lat: r[I.lat], lon: r[I.lon], depth: r[I.depth_km], mag: m, type: r[I.mag_type] || 'ML', fixed: !!r[I.fixed], src: r[I.src], km: d, match: r[I.match] || null });
  }
  return out.sort((a, b) => a.t - b.t);
}
// fluid pumped by local day: the charts' clean volume per stage, or a well's filed fluid spread over its frac days
function injection(ws, S) {
  const charted = new Set(), days = new Map();
  const add = (d, v) => { if (d && v > 0) days.set(d, (days.get(d) || 0) + v); };
  const want = new Set(ws.map(w => String(w.wa)));
  for (const r of S.rows) { const wa = String(+r.wa); if (want.has(wa)) charted.add(wa); }
  const wById = new Map(ws.map(w => [String(w.wa), w]));
  for (const r of S.rows) { const wa = String(+r.wa); if (!charted.has(wa)) continue; add(r.date || (wById.get(wa) || {}).fracStart, r.clean); }
  let spread = 0;
  for (const w of ws) {
    if (charted.has(String(w.wa)) || !w.fluid || !w.fracStart) continue;
    const n = Math.max(1, Math.round((dayMs(w.fracEnd || w.fracStart) - dayMs(w.fracStart)) / 864e5) + 1);
    for (let i = 0; i < n; i++) add(addDays(w.fracStart, i), w.fluid / n);
    spread++;
  }
  const list = [...days].sort((a, b) => (a[0] < b[0] ? -1 : 1));
  let c = 0; const cum = list.map(([d, v]) => [d, (c += v)]);
  return { cum, total: c, charted: charted.size, spread, upTo: d => { let lo = 0, hi = cum.length - 1, best = 0; while (lo <= hi) { const m = (lo + hi) >> 1; if (cum[m][0] <= d) { best = cum[m][1]; lo = m + 1; } else hi = m - 1; } return best; } };
}
function seismic(pane, W, ctx, [E, L, glist, S]) {
  const { h, fmt } = ctx;
  const Z = state.sz;
  const padNames = new Map(); W.forEach(w => { if (!padNames.has(w.pad)) padNames.set(w.pad, w.padName || w.pad); });
  const own = glist.filter(g => g.own), pre = glist.filter(g => !g.own);
  const opt = (v, t, dis) => h('option', { value: v, text: t, disabled: dis || null });
  const kindSel = h('select', { 'aria-label': 'Selection', onchange: e => { Z.kind = e.target.value; saveState(); controls(); draw(); } },
    opt('finder', 'The finder’s wells'), opt('pad', 'A pad'), opt('area', 'A prepared area'), opt('group', own.length ? 'One of my groups' : 'One of my groups (none saved)', !own.length));
  const padSel = h('select', { 'aria-label': 'Pad', onchange: e => { Z.pad = e.target.value; saveState(); draw(); } }, [...padNames].sort((a, b) => String(a[1]).localeCompare(b[1], undefined, { numeric: true })).map(([id, n]) => opt(id, n)));
  const areaSel = h('select', { 'aria-label': 'Prepared area', onchange: e => { Z.area = e.target.value; saveState(); draw(); } }, pre.map(g => opt(g.id, g.name)));
  const groupSel = h('select', { 'aria-label': 'My group', onchange: e => { Z.group = e.target.value; saveState(); draw(); } }, own.map(g => opt(g.id, g.name)));
  const km = h('input', { type: 'number', min: .5, max: 50, step: .5, value: Z.km, oninput: e => { if (+e.target.value > 0) { Z.km = +e.target.value; saveState(); later(); } } });
  const from = h('input', { type: 'date', 'aria-label': 'From', onchange: () => setWin() }), to = h('input', { type: 'date', 'aria-label': 'To', onchange: () => setWin() });
  let t = 0; const later = () => { clearTimeout(t); t = setTimeout(draw, 300); };
  const lPad = h('label', null, 'Pad', padSel), lArea = h('label', null, 'Prepared area', areaSel), lGroup = h('label', null, 'My group', groupSel);
  const filt = h('div');
  const controls = () => {
    if (Z.kind === 'group' && !own.length) Z.kind = 'finder';
    kindSel.value = Z.kind;
    if (!padNames.has(Z.pad)) Z.pad = (W.find(w => w.quakes) || W[0]).pad;
    padSel.value = Z.pad;
    if (!pre.some(g => g.id === Z.area)) Z.area = (pre[0] || {}).id || ''; areaSel.value = Z.area;
    if (!own.some(g => g.id === Z.group)) Z.group = (own[0] || {}).id || ''; groupSel.value = Z.group;
    lPad.hidden = Z.kind !== 'pad'; lArea.hidden = Z.kind !== 'area'; lGroup.hidden = Z.kind !== 'group';
    filt.replaceChildren(Z.kind === 'finder' ? folded(W, ctx, draw) : '');
  };
  const pick = () => {
    if (Z.kind === 'pad') return { ws: W.filter(w => w.pad === Z.pad), name: padNames.get(Z.pad), key: 'pad:' + Z.pad };
    const g = (Z.kind === 'area' ? pre : Z.kind === 'group' ? own : []).find(x => x.id === (Z.kind === 'area' ? Z.area : Z.group));
    if (g) { const s = new Set(g.pads); return { ws: W.filter(w => s.has(w.pad)), name: g.name, key: 'g:' + g.id }; }
    const ws = W.filter(w => pass(w)), words = filterWords();
    return { ws, name: ws.length === W.length ? 'the whole region' : `the finder’s ${fmtN(ws.length)} wells`, key: 'f:' + JSON.stringify(words), region: ws.length === W.length };
  };
  let sel = null;
  const setWin = () => { if (from.value && to.value && sel) { Z.win = { key: sel.key, from: from.value, to: to.value }; saveState(); draw(); } };
  const out = h('div');
  let cache = { key: null }, chartProp = null;
  const draw = () => {
    ctx.hideTip();
    sel = pick();
    const ws = sel.ws.filter(w => w.lat != null);
    if (!ws.length) { out.replaceChildren(h('div', { class: 'fvm-empty', text: 'No wells in this selection.' })); return; }
    const starts = ws.map(w => w.fracStart).filter(Boolean).sort(), ends = ws.map(w => w.fracEnd || w.fracStart).filter(Boolean).sort();
    const dFrom = starts[0], dTo = addDays(ends[ends.length - 1], 30);
    const win = Z.win && Z.win.key === sel.key ? Z.win : { from: dFrom, to: dTo };
    from.value = win.from; to.value = win.to;
    const key = `${sel.key}|${Z.km}|${win.from}|${win.to}`;
    if (cache.key !== key) cache = { key, ev: nearLaterals(E, ws, Z.km, win.from, win.to), inj: injection(ws, S) };
    const ev = cache.ev, inj = cache.inj, t0 = dayMs(dFrom);
    const G = gr(ev.map(e => e.mag));
    const pads = sel.region ? Object.keys(L.pads || {}) : [...new Set(ws.map(w => w.pad))];
    const plotA = plotBox(h), plotB = plotBox(h), plotC = plotBox(h), plotE = plotBox(h);
    const types = [...new Set(ev.map(e => e.type))];
    const csvCols = ['time_utc', 'lat', 'lon', 'depth_km', 'magnitude', 'mag_type', 'catalogue', 'km_from_laterals', 'days_since_first_frac', 'matched_wa', 'matched_stage'];
    const csv = () => download('fracview-seismicity-events.csv', csvCols, ev.map(e => ({ time_utc: e.time, lat: e.lat, lon: e.lon, depth_km: e.depth, magnitude: e.mag, mag_type: e.type, catalogue: srcT(e.src),
      km_from_laterals: +e.km.toFixed(2), days_since_first_frac: +((e.t - t0) / 864e5).toFixed(2), matched_wa: e.match ? +e.match[0] : null, matched_stage: e.match ? e.match[1] : null })), {});
    const LD = { padName: { t: 'Pad' }, rule: { t: 'Rule area' }, max: { t: 'Largest', u: 'ML', n: 1, d: 1 }, maxKm: { t: 'Distance', u: 'km', n: 1, d: 1 }, maxDate: { t: 'Date' }, maxSrc: { t: 'Catalogue' },
      n15: { t: 'Events ≥ 1.5', n: 1, d: 0 }, lv: { t: 'Traffic light', n: 1, sv: r => LV[r.level] ? LV[r.level][0] * 10 + (r.max || 0) / 10 : -1 } };
    const lrows = pads.map(id => { const p = (L.pads || {})[id]; return p ? { pad: id, padName: padNames.get(id) || id, rule: p.rule, max: p.max, maxKm: p.maxKm, maxDate: p.maxAt ? localDay(Date.parse(p.maxAt)) : null, maxSrc: p.maxSrc ? srcT(p.maxSrc) : null, n15: p.n15, level: p.level, lv: LV[p.level] ? LV[p.level][0] : null } : null; }).filter(Boolean);
    const rules = L.rules || {};
    put(out,
      h('div', { class: 'fvm-count' }, h('b', { text: `${fmtN(ev.length)} earthquakes within ${Z.km} km of ${sel.name}` }),
        h('span', { class: 'fvm-pill', text: `${win.from} to ${win.to}` }), h('span', { class: 'fvm-pill', text: (n => `${fmtN(ws.length)} well${ws.length === 1 ? '' : 's'} · ${fmtN(n)} pad${n === 1 ? '' : 's'}`)(new Set(ws.map(w => w.pad)).size) }),
        ev.length ? h('span', { class: 'fvm-pill', text: `largest M${Math.max(...ev.map(e => e.mag)).toFixed(1)}` }) : null,
        h('button', { type: 'button', text: 'Download the events (CSV)', disabled: !ev.length, onclick: csv })),
      h('div', { class: 'fvd-grid2' },
        card(h, 'How many, how big: frequency–magnitude', G.b != null ? h('div', { class: 'fvd-head' }, h('b', { text: `b = ${G.b.toFixed(2)} ± ${G.sb.toFixed(2)}` }),
          h('span', { text: ` · Mc ${G.mc.toFixed(1)} · ${fmtN(G.nAbove)} events above Mc` })) : null,
          G.b != null && G.nAbove < 50 ? h('p', { class: 'fvd-warn', role: 'note', text: `▲ Only ${G.nAbove} events above Mc: the b-value is uncertain; widen the radius, the dates or the selection.` }) : null,
          plotA, ev.length ? legendBox(h, [{ c: ink(0), t: 'N(≥M), cumulative' }, { c: ink(1), kind: 'ring', t: 'per 0.1 bin' }, { c: 'var(--m-ink)', kind: 'line', t: 'fitted line above Mc' }]) : null,
          h('p', { class: 'fvm-note', text: `Mc by maximum curvature plus 0.2; b by Aki–Utsu maximum likelihood with Shi & Bolt’s uncertainty. Magnitudes are ${types.join(', ') || 'ML'} as catalogued. Catalogues with different thresholds are mixed here (the BCER’s list is complete from ML 1.5; the relocated BCSRC list goes lower), which can bend the curve.` })),
        card(h, 'Seismic moment against fluid pumped', plotB,
          ev.length ? legendBox(h, [{ c: ink(0), kind: 'line', t: 'cumulative moment of the events' }, { c: 'var(--m-ink)', kind: 'line', t: 'McGarr (2014) bound, G·ΔV' }]) : null,
          h('p', { class: 'fvm-note', text: `Moment from magnitude as M₀ = 10^(1.5 M + 9.1) N·m, taking ML as Mw (an approximation; ML and Mw part ways for small events). Fluid pumped is the clean volume read off the treatment charts per stage, by day (${fmtN(inj.charted)} wells), or a well’s filed fluid spread evenly over its frac days (${fmtN(inj.spread)} wells without charts). The line is McGarr’s bound with G = 30 GPa: points above it released more moment than that much fluid is expected to allow. Both axes are logarithmic.` }))),
      card(h, 'Distance from the laterals over time', plotC,
        ev.length ? legendBox(h, [{ c: ink(0), t: 'M1', kind: 's1' }, { c: ink(0), t: 'M2', kind: 's2' }, { c: ink(0), t: 'M3', kind: 's3' }, { c: 'var(--m-mut)', kind: 'box', t: 'frac periods' }]) : null,
        h('p', { class: 'fvm-note', text: 'Each dot is an earthquake, sized by magnitude, by how far it lay from the nearest lateral (a straight line heel to toe, in plan) and when it came. Shaded spans are when the selection’s wells were being fracked (first to last filed stage).' })),
      card(h, 'Traffic lights per pad',
        h('p', { class: 'fvm-note', style: 'margin-top:0', text: `Each pad’s largest event within its rule’s distance of a lateral while it was fracked (to two days after the last stage), graded against the rules in force today (ML within the distance): ${Object.entries(rules).map(([k, r]) => `${k === 'BC' ? 'province-wide' : k} ${[['notify', r.notify], ['mitigate', r.mitigate], ['suspend', r.suspend]].filter(x => x[1] != null).map(x => x.join(' ')).join(', ')} within ${r.km} km`).join('; ')}. NMSMMA rules started 13 Feb 2025, so older jobs are graded against rules that did not yet apply.` }),
        table(lrows, ['padName', 'rule', 'max', 'maxKm', 'maxDate', 'maxSrc', 'n15', 'lv'], ctx, r => ctx.toMap({ pads: [r.pad], pad: r.pad, title: r.padName }), 500, { defs: LD, st: Z.st,
          cell: (c, r) => (c === 'lv' ? h('span', { class: 'fvd-lv', 'data-lv': r.level }, h('i', { text: (LV[r.level] || ['', '?'])[1], 'aria-hidden': 'true' }), (LV[r.level] || ['', '', r.level])[2]) : null) })),
      card(h, 'Proppant intensity against the largest event, per pad', plotE, null,
        h('p', { class: 'fvm-note', text: 'A pad’s median proppant per metre of lateral (all its wells) against its largest event while it was fracked, coloured by the rule area it sits in; the selection’s pads are drawn over the rest of the region’s. Pads with no located event in that time are left off. An association across pads, not a cause: depth, faults, rate, volume and the rock all differ.' })));
    // a: frequency–magnitude
    if (G.bins.length > 1) {
      const top = G.bins[0].cum, mmin = G.bins[0].m, mmax = G.bins[G.bins.length - 1].m;
      const F = frame(plotA, { x: { min: mmin - .05, max: mmax + .05, label: 'Magnitude' }, y: { min: .8, max: top * 1.5, log: true, label: 'Events' }, yw: 3.6, aria: `Frequency–magnitude for ${ev.length} events; b ${G.b ? G.b.toFixed(2) : 'not found'}` });
      sv('line', { x1: F.X(G.mc), x2: F.X(G.mc), y1: F.P.t, y2: F.P.t + F.ph, class: 'ref' }, F.svg);
      sv('text', { x: F.X(G.mc) + 4, y: F.P.t + F.fs, class: 'lab' }, F.svg, `Mc ${G.mc.toFixed(1)}`);
      if (G.b != null) { const y = m => 10 ** (G.a - G.b * m); sv('line', { x1: F.X(G.mc), y1: F.Y(y(G.mc)), x2: F.X(mmax), y2: F.Y(Math.max(.8, y(mmax))), stroke: 'var(--m-ink)', 'stroke-width': 2, 'stroke-linecap': 'round' }, F.svg); }
      const pts = [];
      for (const b of G.bins) {
        if (b.n) { sv('circle', { cx: F.X(b.m), cy: F.Y(b.n), r: 4, fill: 'var(--m-panel)', stroke: ink(1), 'stroke-width': 2 }, F.svg); }
        sv('circle', { cx: F.X(b.m), cy: F.Y(b.cum), r: 4, fill: ink(0), class: 'end' }, F.svg);
        pts.push({ x: F.X(b.m), y: F.Y(b.cum), d: b });
      }
      crosshair(F, pts.map(p => p.x), ctx, i => { const b = G.bins[i]; return [[`M ${b.m.toFixed(1)}`, 1], [`${fmtN(b.cum)} events at M ${b.m.toFixed(1)} or more`, 0, ink(0)], [`${fmtN(b.n)} in this 0.1 bin`, 0, ink(1)],
        G.b != null && b.m >= G.mc - 1e-9 ? [`fit: ${sig(10 ** (G.a - G.b * b.m))}`, 0, 'var(--m-ink)'] : null]; });
    } else plotA.replaceChildren(h('div', { class: 'fvm-empty', text: 'Too few earthquakes to plot.' }));
    // b: cumulative moment against cumulative volume
    let c = 0, before = 0;
    const mv = []; for (const e of ev) { c += moment(e.mag); const v = inj.upTo(localDay(e.t)); if (v > 0) mv.push({ v, m0: c, e }); else before++; }
    if (mv.length > 1) {
      const vmin = mv[0].v, vmax = Math.max(inj.total, mv[mv.length - 1].v);
      const ymin = Math.min(mv[0].m0, mcgarr(vmin)) / 2, ymax = Math.max(mv[mv.length - 1].m0, mcgarr(vmax)) * 2;
      const F = frame(plotB, { x: { min: vmin / 1.5, max: vmax * 1.5, log: true, label: 'Fluid pumped, cumulative (m³)' }, y: { min: ymin, max: ymax, log: true, label: 'Seismic moment, cumulative (N·m)' }, yw: 3.8,
        aria: `Cumulative seismic moment against cumulative fluid for ${mv.length} events` });
      sv('line', { x1: F.X(vmin / 1.5), y1: F.Y(mcgarr(vmin / 1.5)), x2: F.X(vmax * 1.5), y2: F.Y(mcgarr(vmax * 1.5)), stroke: 'var(--m-ink)', 'stroke-width': 2, class: 'clip' }, F.svg);
      // a step: the moment holds while fluid goes in, and rises at each event; on to the fluid pumped by the window's end
      const vEnd = Math.max(mv[mv.length - 1].v, inj.upTo(win.to));
      sv('path', { d: mv.map((p, i) => `${i ? `H${F.X(p.v).toFixed(1)}V` : `M${F.X(p.v).toFixed(1)},`}${F.Y(p.m0).toFixed(1)}`).join('') + `H${F.X(vEnd).toFixed(1)}`,
        fill: 'none', stroke: ink(0), 'stroke-width': 2, 'stroke-linejoin': 'round' }, F.svg);
      const pts = mv.map(p => ({ x: F.X(p.v), y: F.Y(p.m0), d: p }));
      const last = pts[pts.length - 1]; sv('circle', { cx: last.x, cy: last.y, r: 4, fill: ink(0), class: 'end' }, F.svg);
      nearest(F, pts, ctx, p => [[`${p.e.time.slice(0, 16).replace('T', ' ')} UTC · M${p.e.mag.toFixed(1)}`, 1], [`${fmtN(Math.round(p.v))} m³ pumped by that day`], [`cumulative moment ${p.m0.toExponential(2)} N·m`, 0, ink(0)],
        [`McGarr bound at that volume ${mcgarr(p.v).toExponential(2)} N·m (${(p.m0 / mcgarr(p.v) * 100).toPrecision(2)}%)`, 0, 'var(--m-ink)']]);
      if (before) plotB.append(h('p', { class: 'fvm-note', style: 'margin:.2em .4em', text: `${before} event${before === 1 ? '' : 's'} before the first fluid was pumped are counted in the moment but not drawn.` }));
    } else plotB.replaceChildren(h('div', { class: 'fvm-empty', text: inj.total ? 'Too few earthquakes after the first stage to plot.' : 'No fluid volumes for these wells.' }));
    // c: distance–time
    if (ev.length) {
      const dmin = Math.min(0, (dayMs(win.from) - t0) / 864e5), dmax = Math.max(1, (dayMs(win.to) + 864e5 - t0) / 864e5);
      const F = frame(plotC, { x: { min: dmin, max: dmax, label: `Days since the first frac stage (${dFrom})` }, y: { min: 0, max: Z.km, label: 'Distance from the nearest lateral (km)' }, yw: 3.2,
        h: Math.round(Math.max(240, Math.min(360, (plotC.clientWidth || 600) * .4))), aria: `Distance against time for ${ev.length} events` });
      // when the wells were being fracked, merged into spans
      const spans = ws.filter(w => w.fracStart).map(w => [(dayMs(w.fracStart) - t0) / 864e5, (dayMs(w.fracEnd || w.fracStart) + 864e5 - t0) / 864e5]).sort((a, b) => a[0] - b[0]);
      const merged = []; for (const s of spans) { const m = merged[merged.length - 1]; if (m && s[0] <= m[1] + .5) m[1] = Math.max(m[1], s[1]); else merged.push(s.slice()); }
      for (const [a, b] of merged) { const x = F.X(Math.max(dmin, a)), w = Math.max(1.5, F.X(Math.min(dmax, b)) - x); if (b < dmin || a > dmax) continue; sv('rect', { x, y: F.P.t, width: w, height: F.ph, class: 'span' }, F.svg); sv('rect', { x, y: F.P.t + F.ph - 5, width: w, height: 5, class: 'spanbar' }, F.svg); }
      // sized by magnitude; many events on a small chart are drawn fainter and a little smaller so the pattern shows
      const dense = ev.length / F.pw > 1.5, r = m => 4 + Math.max(0, m - 1) * (dense ? 1.6 : 2.4);
      const pts = [];
      ev.slice().sort((a, b) => b.mag - a.mag).forEach(e => { const x = F.X((e.t - t0) / 864e5), y = F.Y(e.km); sv('circle', { cx: x.toFixed(1), cy: y.toFixed(1), r: r(e.mag), fill: ink(0), 'fill-opacity': dense ? .3 : .55, class: 'dot' }, F.svg); pts.push({ x, y, r: r(e.mag), d: e }); });
      nearest(F, pts, ctx, e => [[`M${e.mag.toFixed(1)} ${e.type} · ${e.time.slice(0, 16).replace('T', ' ')} UTC`, 1], [`${e.km.toFixed(1)} km from the nearest lateral · day ${Math.floor((e.t - t0) / 864e5)}`],
        [`${srcT(e.src)}${e.depth != null ? ` · depth ${e.depth} km${e.fixed ? ' (fixed)' : ''}` : ''}`], e.match ? [`at stage ${e.match[1]} of WA ${+e.match[0]} (${e.match[2] === 'after' ? `${e.match[3]} min after it ended` : 'while pumping'})`] : null,
        e.match ? ['Click for that stage’s chart'] : null], e => { if (e.match) openStage(+e.match[0], e.match[1]); });
    } else plotC.replaceChildren(h('div', { class: 'fvm-empty', text: 'No earthquakes in this window.' }));
    // e: intensity against the largest event, per pad
    // a well's filed proppant per metre, or the charts' sum where nothing was filed
    const inSel = new Set(lrows.map(r => r.pad)), byPad = new Map();
    if (!chartProp) { chartProp = new Map(); for (const r of S.rows) if (r.prop > 0) chartProp.set(String(+r.wa), (chartProp.get(String(+r.wa)) || 0) + r.prop); }
    let fromCharts = 0;
    W.forEach(w => {
      let v = w.proppantPerM;
      if (v == null && w.lateral > 0 && chartProp.has(String(w.wa))) { v = chartProp.get(String(w.wa)) / w.lateral; if (sel.region || inSel.has(w.pad)) fromCharts++; }
      if (!byPad.has(w.pad)) byPad.set(w.pad, []); byPad.get(w.pad).push(v);
    });
    const pp = Object.entries(L.pads || {}).map(([id, p]) => ({ pad: id, padName: padNames.get(id) || id, rule: p.rule, max: p.max, maxKm: p.maxKm, maxDate: p.maxAt ? localDay(Date.parse(p.maxAt)) : null, level: p.level, sel: sel.region || inSel.has(id), int: median(byPad.get(id) || []) }));
    const pin = pp.filter(r => r.max != null && r.int != null).sort((a, b) => a.sel - b.sel), none = pp.filter(r => r.sel && r.max == null).length;
    const RULES = ['KSMMA', 'NMSMMA', 'BC'], rk = r => (RULES.includes(r) ? r : 'BC');
    if (pin.length > 1) {
      const xs = pin.map(p => p.int).sort((a, b) => a - b);
      const xm = Math.max(.5, pct(xs, .99) * 1.05);
      const F = frame(plotE, { x: { min: 0, max: xm, label: 'Median proppant intensity of the pad (t/m)' }, y: { min: Math.min(0, ...pin.map(p => p.max)), max: Math.max(...pin.map(p => p.max)) + .3, label: 'Largest event while fracked (ML)' }, yw: 3,
        h: Math.round(Math.max(240, Math.min(340, (plotE.clientWidth || 600) * .42))), aria: `Largest event against proppant intensity for ${pin.length} pads` });
      const pts = pin.map(p => ({ x: F.X(Math.min(p.int, xm)), y: F.Y(p.max), d: p }));
      pts.forEach(p => sv('circle', { cx: p.x.toFixed(1), cy: p.y.toFixed(1), r: p.d.sel && !sel.region ? 6 : 4.5, fill: ink(RULES.indexOf(rk(p.d.rule))), 'fill-opacity': p.d.sel ? .85 : .22,
        class: p.d.sel && !sel.region ? 'dot end picked' : 'dot' }, F.svg));
      nearest(F, pts, ctx, p => [[p.padName, 1], [`${p.rule} · ${(LV[p.level] || ['', '', p.level])[2]}`, 0, ink(RULES.indexOf(rk(p.rule)))], [`median ${fmt(p.int, 2)} t/m`], [`largest ML ${fmt(p.max, 1)}, ${fmt(p.maxKm, 1)} km, ${p.maxDate}`], ['Click for the pad on the map']],
        p => ctx.toMap({ pads: [p.pad], pad: p.pad, title: p.padName }));
      plotE.after(...[legendBox(h, [...RULES.map((k, i) => ({ c: ink(i), t: `${k === 'BC' ? 'Province-wide' : k} · ${pin.filter(p => p.sel && rk(p.rule) === k).length}` })),
        sel.region ? null : { c: 'var(--m-ink)', kind: 'ring', t: `the selection’s pads, larger; the region’s faint` }, none ? { c: 'var(--m-faint)', kind: 'ring', t: `${none} pad${none === 1 ? '' : 's'} in the selection with no event, not shown` } : null]),
        fromCharts ? h('p', { class: 'fvm-note', style: 'margin:.2em .5em', text: `${fmtN(fromCharts)} of the selection’s wells have no filed proppant; their intensity is the sum read off their treatment charts.` }) : null].filter(Boolean));
    } else plotE.replaceChildren(h('div', { class: 'fvm-empty', text: 'No pads with an event to plot.' }));
  };
  pane.append(h('h1', { text: 'Seismicity' }),
    h('p', { class: 'fvm-sub', text: 'Earthquakes around a selection of wells: how many and how big, their moment against the fluid pumped, where and when, and each pad’s traffic light.' }),
    h('div', { class: 'fvm-filters fvd-controls' },
      h('label', null, 'Selection', kindSel), lPad, lArea, lGroup,
      h('label', null, 'Within (km of a lateral)', km),
      h('label', null, 'From (local date)', from), h('label', null, 'To', to),
      h('div', { class: 'wide' }, h('button', { type: 'button', text: 'Dates of the fracs', title: 'From the first frac start to 30 days after the last frac end', onclick: () => { Z.win = null; saveState(); draw(); } }))),
    filt, out);
  controls();
  live = { pane, redraw: draw, charts: true };
  draw();
}

// ---------- Earthquakes at stages ----------
function quakes(pane, W, ctx, E) {
  const { h } = ctx;
  const byWa = new Map(W.map(w => [String(w.wa), w]));
  const all = E.rows.filter(r => r[11]).map(r => {
    const m = r[11], w = byWa.get(String(+m[0])) || { wa: String(+m[0]), name: `WA ${+m[0]}`, padName: '', operator: null, pad: null };
    return { t: r[0], date: r[0].slice(0, 16).replace('T', ' '), mag: r[4], type: r[5], depth: r[3], src: srcT(r[8]),
             wa: w.wa, name: w.name, padName: w.padName, operator: w.operator, pad: w.pad, stage: String(m[1]), timing: m[2], after: m[3], km: m[4], dz: m[5] };
  });
  const COLS = { date: { t: 'Date (UTC)' }, mag: { t: 'M', n: 1, d: 1 }, name: { t: 'Well' }, operator: { t: 'Operator' }, stage: { t: 'Stage' }, when: { t: 'Timing' },
                 km: { t: 'Distance', u: 'km', n: 1, d: 1 }, dz: { t: 'Depth vs well', u: 'm', n: 1, d: 0 }, src: { t: 'Catalogue' } };
  const D = { ...COL, ...COLS };
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
    put(out,
      h('div', { class: 'fvm-count' }, h('b', { text: `${fmtN(rows.length)} earthquakes` }),
        rows.length ? h('span', { class: 'fvm-pill', text: `largest M${Math.max(...rows.map(q => q.mag || 0))}` }) : null,
        h('span', { class: 'fvm-pill', text: `${new Set(rows.map(q => q.wa)).size} wells · ${new Set(rows.map(q => q.pad)).size} pads` })),
      ops.length ? h('div', { class: 'fvm-card', style: 'margin-bottom:1em' }, h('h3', { text: 'By operator' }),
        h('div', { style: 'display:grid;grid-template-columns:max-content 1fr max-content;gap:.3em .7em;align-items:center;font-size:.85em' },
          ...ops.slice(0, 8).flatMap(([op, n]) => [h('span', { text: op }), h('div', { style: `height:.7em;border-radius:.2em;background:var(--m-acc);width:${Math.max(2, n / big * 100)}%` }), h('span', { text: String(n) })]))) : null,
      table(rows, ['date', 'mag', 'name', 'stage', 'when', 'km', 'operator', 'dz', 'src'], ctx, q => openStage(q.wa, q.stage), 300, { defs: D }),
      h('p', { class: 'fvm-note', text: `Click a row for that stage’s chart in a window of its own. An earthquake is matched to a stage on a well within reach (5 km for an Earthquakes Canada location, less for the better-located catalogues) that was pumping, or had ended shortly before; that names the stage, it does not prove the stage caused it.${c && c.share_beyond_chance != null ? ` Across the region about ${Math.round(c.share_beyond_chance * 100)}% of such coincidences are more than chance (the same events with dates shifted by weeks match ${c.by_chance} of ${c.matched}).` : ''} Depth vs well is the event’s solved depth less the well’s, where both are known. Catalogue: BCSRC relocated (the BC Seismic Research Consortium, May 2022–Apr 2024), BCER (the regulator’s list, ML 1.5 and up) or Earthquakes Canada.` }));
  };
  if (!['date', 'mag', 'km'].includes(state.sort)) { state.sort = 'mag'; state.dir = -1; }
  pane.append(h('h1', { text: 'Earthquakes at stages' }), h('p', { class: 'fvm-sub', text: 'Earthquakes Canada, the BC Energy Regulator’s catalogue and the BC Seismic Research Consortium’s relocations, matched to the frac stages in the region.' }),
    h('div', { class: 'fvm-filters' }, num('minMag', 'Magnitude at least', '0.1'), num('maxKm', 'Within (km of the stage)', '0.5'), h('label', null, 'Timing', timing)), out);
  draw();
}

// ---------- Well spacing ----------
function spacingTool(pane, W, ctx, S) {
  const { h, fmt } = ctx;
  const byWa = new Map(W.map(w => [String(w.wa), w]));
  const COLS = { nbName: { t: 'Nearest lateral' }, nbPad: { t: 'Its pad' }, across: { t: 'Across', u: 'm', n: 1, d: 0 }, vertical: { t: 'Vertical', u: 'm', n: 1, d: 0 }, overlap: { t: 'Side by side for', u: 'm', n: 1, d: 0 } };
  const D = { ...COL, ...COLS };
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
    put(out,
      h('div', { class: 'fvm-count' }, h('b', { text: `${fmtN(rows.length)} wells` }), h('span', { class: 'fvm-pill', text: `median ${fmt(median(rows.map(r => r.across)))} m across` }),
        h('span', { class: 'fvm-pill', text: `${rows.filter(r => r.across < 100).length} under 100 m` })),
      h('div', { class: 'fvm-card', style: 'margin-bottom:1em' }, h('h3', { text: 'Nearest lateral across, in 25 m bands' }),
        h('div', { class: 'fvm-bars', role: 'img', 'aria-label': 'How many wells have their nearest lateral at each spacing' }, bins.map((n, i) => h('i', { style: `height:${n / top * 100}%`, title: `${i * 25}${i === 16 ? '+' : '–' + (i * 25 + 25)} m: ${n} wells` }))),
        h('div', { style: 'display:flex;justify-content:space-between;font:11px ui-monospace,Menlo,monospace;color:var(--m-mut)' }, h('span', { text: '0 m' }), h('span', { text: '200 m' }), h('span', { text: '400 m +' }))),
      actions(rows, ctx, 'Discover: well spacing'),
      table(rows, ['name', 'across', 'vertical', 'nbName', 'overlap', 'operator', 'year', 'nbPad', 'gasPerM'], ctx, r => ctx.toMap({ pads: [...new Set([r.pad, (byWa.get(String(r.nb)) || {}).pad].filter(Boolean))], racks: true, title: r.padName }), 300, { defs: D }),
      h('p', { class: 'fvm-note', text: 'Click a row for the wine rack of its pad (and its neighbour’s, if on another pad). Across is the plan distance between the two laterals where they run side by side, the median over that stretch; vertical is the neighbour’s TVD less this well’s. “Same zone” keeps neighbours within 60 m vertically, so a well stacked in another zone above or below is not counted as the nearest.' }));
  };
  if (!['across', 'vertical', 'overlap'].includes(state.sort)) { state.sort = 'across'; state.dir = 1; }
  pane.append(h('h1', { text: 'Well spacing' }), h('p', { class: 'fvm-sub', text: 'Each lateral against its nearest neighbour, on its own pad or the next one over.' }),
    h('div', { class: 'fvm-filters' }, num('spacingMax', 'Across at most (m)'), h('div', { class: 'wide' }, chk('zone', 'Same zone only (within 60 m vertically)'), chk('samePad', 'Neighbours on the same pad only'))),
    out, folded(W, ctx, draw, { skip: ['nnH'] }));
  draw();
}

window.StratumDiscover = { render, pass, short, TOOLS, COL, RANGES, RANGES2, pct, gr, moment, mcgarr, G_SHEAR, segDist, nearLaterals, injection, typeCurves, degradation, benchmark, categories, ymN, daysIn };
})();
