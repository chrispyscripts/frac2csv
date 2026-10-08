// FracView — one well's stage report: what was pumped where, stage by stage,
// from the treatment curves and as filed with the BC Energy Regulator, the
// checks between the two, the flags, every stage's curves overlaid, and what
// the well has produced since. Prints on Letter or A4 and downloads as CSV.
//
//   report.html?wa=<WA>
//
// Data: data/wells/<WA>.json (the well, its stages and their thinned curves),
// metrics.js (each stage's numbers: data/metrics/pads/<pad>.json),
// data/metrics/summary.json (how curves and filings agree across the region),
// data/region/pads/<pad>.json (the pad's other wells, to compare with) and
// data/prod/wells.json (monthly production; 5 MB, fetched once the rest is up).
//
// The working parts are pure and on window.FVReport (tests/test_stratum_report.js).
(() => {
'use strict';
const FVM = window.FVMetrics;
const num = v => v != null && typeof v === 'number' && isFinite(v);
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = (v, d = 0) => !num(v) ? '—'
  : (Math.abs(v) < 0.5 * Math.pow(10, -d) ? 0 : v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d });
const getJSON = u => fetch(u).then(r => (r.ok ? r.json() : null)).catch(() => null);
const pad5 = wa => String(wa).replace(/^0+/, '').padStart(5, '0');

// ---------- the numbers ----------
// a sorted list's p-quantile, linear between neighbours
function quantile(sorted, p) {
  if (!sorted.length) return null;
  const x = (sorted.length - 1) * p, i = Math.floor(x), f = x - i;
  return i + 1 < sorted.length ? sorted[i] + (sorted[i + 1] - sorted[i]) * f : sorted[i];
}
const median = v => quantile(v.filter(num).sort((a, b) => a - b), 0.5);

// what the overlay can show: wellhead concentration where the chart has it, else bottomhole
const CHANNELS = {
  press: { t: 'Treating pressure', short: 'Pressure', u: 'MPa', d: 1, keys: ['press'] },
  rate: { t: 'Slurry rate', short: 'Rate', u: 'm³/min', d: 2, keys: ['rate'] },
  conc: { t: 'Proppant concentration', short: 'Concentration', u: 'kg/m³', d: 0, keys: ['wh_conc', 'bh_conc'] },
};
// One stage's curve for the overlay: x is minutes from the chart's start (sample
// i at i × step_s), or the slurry pumped so far in m³ (rate × time; a gap in the
// rate adds nothing). Null where the stage has no such curve.
function stageCurve(s, ch, xMode) {
  const ser = (s && s.series) || {}, step = s.step_s || 1;
  const key = CHANNELS[ch].keys.find(k => Array.isArray(ser[k]) && ser[k].some(num));
  if (!key) return null;
  const y = ser[key], rate = ser.rate || [], x = new Array(y.length);
  let vol = 0;
  for (let i = 0; i < y.length; i++) {
    if (i && xMode === 'vol') { const r = rate[i - 1]; if (num(r) && r > 0) vol += r * step / 60; }
    x[i] = xMode === 'vol' ? vol : i * step / 60;
  }
  if (xMode === 'vol' && !(vol > 0)) return null;
  return { x, y: y.map(v => (num(v) ? v : null)), key };
}
// a curve's value at x, straight between samples; across a gap, the nearer edge
function valueAt(c, X) {
  const xs = c.x, n = xs.length;
  if (!n || !(X >= xs[0]) || X > xs[n - 1]) return null;
  let lo = 0, hi = n - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (xs[m] <= X) lo = m; else hi = m; }
  const a = c.y[lo], b = c.y[hi];
  if (a == null || b == null) return a != null ? a : b;
  const span = xs[hi] - xs[lo];
  return span > 0 ? a + (b - a) * (X - xs[lo]) / span : a;
}
const grid = (x1, n = 240) => Array.from({ length: n + 1 }, (_, i) => x1 * i / n);
// Across the stages at each x: how many reach it, and their 10th, 50th and 90th
// percentiles. Where fewer than minN stages reach, the envelope stops (a tail
// of two long stages is not the well's typical curve).
function envelope(curves, xs, minN = 3) {
  return xs.map(X => {
    const v = curves.map(c => valueAt(c, X)).filter(num).sort((a, b) => a - b);
    return v.length < minN ? { x: X, n: v.length, p10: null, p50: null, p90: null }
      : { x: X, n: v.length, p10: quantile(v, 0.1), p50: quantile(v, 0.5), p90: quantile(v, 0.9) };
  });
}
const minStages = n => Math.max(3, Math.ceil(n * 0.2));

// the curves against the filing, in a few plain figures
function qc(totals, rows) {
  const t = totals || {}, pct = (a, b) => (num(a) && num(b) && b > 0 ? 100 * a / b : null);
  const d = rows.filter(r => num(r.isip) && num(r.fIsip)).map(r => r.isip - r.fIsip).sort((a, b) => a - b);
  return {
    charted: t.stagesCharted || 0, filed: t.stagesFiled || 0,
    prop: { curves: t.prop, filed: t.propFiledCharted, pct: pct(t.prop, t.propFiledCharted) },
    fluid: { curves: t.clean, filed: t.fluidFiledCharted, pct: pct(t.clean, t.fluidFiledCharted) },
    isip: { n: d.length, median: quantile(d, 0.5), within2: d.filter(x => Math.abs(x) <= 2).length },
    matched: { n: t.matchedByTime || 0, of: t.stagesCharted || 0 },
    depth: rows.filter(r => FVM.flags(r).includes('depth')).length,
  };
}
// each flag on the well and the stages it is on, in metrics.js's order
function flagGroups(rows) {
  return FVM.FLAGS.map(k => ({ k, info: FVM.FLAG_INFO[k], rows: rows.filter(r => FVM.flags(r).includes(k)) })).filter(g => g.rows.length);
}

// ---------- the stage table and the CSV ----------
// v: the number a column sorts by; filed: the figure is the operator's own,
// shown where the curves give none
const pick = (a, b) => (num(a) ? a : num(b) ? b : null);
const TABLE = [
  { k: 'label', t: 'Stage', text: 1 },
  { k: 'md', t: 'MD top–base', u: 'm', v: r => r.top, s: r => (num(r.top) ? `${fmt(r.top)}–${fmt(num(r.base) ? r.base : r.top)}` : '—'), filed: r => r.mdFrom === 'chart' },
  { k: 'tvd', t: 'TVD', u: 'm', d: 0 },
  { k: 'when', t: 'Date, start', text: 1, v: r => `${r.date || ''} ${r.start || ''}`.trim() || null,
    s: r => [r.date, r.start && String(r.start).slice(0, 5)].filter(Boolean).join(' ') || '—' },
  { k: 'pumpMin', t: 'Pump', u: 'min', d: 0 },
  { k: 'rampMin', t: 'Ramp', u: 'min', d: 1 },
  { k: 'avgP', t: 'Avg P', u: 'MPa', d: 1, v: r => pick(r.avgP, r.fAvgP), filed: r => !num(r.avgP) && num(r.fAvgP) },
  { k: 'maxP', t: 'Peak P', u: 'MPa', d: 1, v: r => pick(r.maxP, r.fMaxP), filed: r => !num(r.maxP) && num(r.fMaxP) },
  { k: 'isip', t: 'ISIP curves', u: 'MPa', d: 1 },
  { k: 'fIsip', t: 'ISIP filed', u: 'MPa', d: 1 },
  { k: 'fg', t: 'Frac gradient', u: 'kPa/m', d: 1 },
  { k: 'avgRate', t: 'Rate', u: 'm³/min', d: 1, v: r => pick(r.avgRate, r.fRate), filed: r => !num(r.avgRate) && num(r.fRate) },
  { k: 'prop', t: 'Proppant curves', u: 't', d: 1 },
  { k: 'fProp', t: 'Proppant filed', u: 't', d: 1 },
  { k: 'clean', t: 'Fluid curves', u: 'm³', d: 0 },
  { k: 'fFluid', t: 'Fluid filed', u: 'm³', d: 0 },
  { k: 'tph', t: 'Sand rate', u: 't/h', d: 0 },
  { k: 'shape', t: 'Pressure at rate', text: 1 },
  { k: 'flags', t: 'Flags', text: 1, v: r => FVM.flags(r).length || null },
];
// one row per stage, toe to heel (the order the rows come in): each cell's sort value, text, and whether it was filed
function tableRows(rows) {
  return rows.map((r, i) => ({ r, i, cells: TABLE.map(c => {
    const v = c.v ? c.v(r) : r[c.k];
    return { v: v == null || v === '' ? null : v, s: c.s ? c.s(r) : c.text ? (v == null || v === '' ? '—' : String(v)) : fmt(v, c.d), filed: !!(c.filed && c.filed(r)) };
  }) }));
}
const SRC = { '1 s': '1-second export', filed: 'none (filed only)' };
const CSV_COLS = [
  ['label', 'Stage'], ['fN', 'Filed stage number'], ['date', 'Date'], ['start', 'Start'], ['top', 'Top MD (m)'], ['base', 'Base MD (m)'], ['tvd', 'TVD (m)'],
  ['src', 'Curves from'], ['dtMin', 'Chart start minus filed start (min)'],
  ['pumpMin', 'Pump time (min)'], ['spanMin', 'First to last pumping (min)'], ['atRateMin', 'Time at rate (min)'], ['rampMin', 'Ramp-up time (min)'],
  ['shutdowns', 'Mid-stage shutdowns'], ['shutMin', 'Time shut down (min)'],
  ['avgP', 'Avg treating pressure (MPa)'], ['maxP', 'Peak pressure (MPa)'], ['pSlope', 'Pressure trend at rate (MPa/min)'],
  ['pEndSlope', 'Pressure trend over the last 3 min (MPa/min)'], ['avgRate', 'Avg slurry rate (m3/min)'], ['maxRate', 'Peak slurry rate (m3/min)'],
  ['maxConc', 'Peak proppant concentration (kg/m3)'], ['slurry', 'Slurry from the curves (m3)'], ['clean', 'Clean fluid from the curves (m3)'],
  ['prop', 'Proppant from the curves (t)'], ['tph', 'Sand rate (t/h)'], ['isip', 'ISIP from the falloff (MPa)'], ['isipFall', 'Falloff recorded (s)'],
  ['fg', 'Frac gradient (kPa/m)'], ['fProp', 'Filed proppant (t)'], ['fFluid', 'Filed fluid (m3)'], ['fIsip', 'Filed ISIP (MPa)'],
  ['fBreak', 'Filed breakdown pressure (MPa)'], ['fAvgP', 'Filed avg pressure (MPa)'], ['fMaxP', 'Filed max pressure (MPa)'],
  ['fRate', 'Filed avg rate (m3/min)'], ['shape', 'Pressure at rate'], ['flags', 'Flags'],
];
// the stage table with every column, the filed ones too, under a line naming the sources
function csv(m) {
  const q = v => { if (v == null) return ''; const s = String(v); return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const plain = s => String(s || '').replace(/[,\r\n]+/g, ' ').trim();
  const src = m.totals && m.totals.src;
  const head = `# FracView stage report · ${plain(m.well.name) || 'WA ' + m.wa} · WA ${m.wa} · curves: the Lab's read of ${plain(m.file) || 'the frac report'}`
    + `${src ? ` (${src === '1 s' ? '1-second export' : 'thinned to one point every ' + src})` : ''} · filed numbers: BC Energy Regulator hydraulic fracture table`
    + ' · contains information licensed under the BC Energy Regulator Open Data Licence';
  const cell = (r, k) => (k === 'flags' ? FVM.flags(r).map(f => FVM.FLAG_INFO[f].t).join('; ') : k === 'src' ? SRC[r.src] || (r.src ? 'thinned, every ' + r.src : '') : r[k]);
  return [head, CSV_COLS.map(c => q(c[1])).join(','), ...m.rows.map(r => CSV_COLS.map(c => q(cell(r, c[0]))).join(','))].join('\n') + '\n';
}

// ---------- production ----------
const daysIn = ym => { const [y, mo] = ym.split('-').map(Number); return new Date(Date.UTC(y, mo, 0)).getUTCDate(); };
const addMonths = (ym, k) => { const [y, mo] = ym.split('-').map(Number), t = y * 12 + mo - 1 + k; return `${Math.floor(t / 12)}-${String(t % 12 + 1).padStart(2, '0')}`; };
// month by month from first production: calendar-day rates (the month's volume over its days)
function prodSeries(p) {
  if (!p || !p.f || !Array.isArray(p.g)) return [];
  return p.g.map((g, i) => {
    const ym = addMonths(p.f, i), days = daysIn(ym), liq = (p.c ? p.c[i] || 0 : 0) + (p.o ? p.o[i] || 0 : 0);
    return { ym, gas: num(g) ? g / days : null, liq: liq / days, water: p.w && num(p.w[i]) ? p.w[i] / days : null, on: p.d ? p.d[i] : null };
  });
}

// ---------- the well, put together ----------
// a chart (a stage in the well file with curves) and its row of numbers: same
// label, date and start, as build_stage_metrics.py pairs them; else the label
function joinCharts(stages, rows) {
  const charted = rows.filter(r => r.src !== 'filed'), used = new Set(), lab = x => String(x).toLowerCase();
  return (stages || []).filter(s => s.series && Object.values(s.series).some(a => Array.isArray(a) && a.some(num))).map(s => {
    const same = r => lab(r.label) === lab(s.label);
    const r = charted.find(x => !used.has(x) && same(x) && (x.date || '') === (s.date || '') && (x.start || '') === (s.start || ''))
      || charted.find(x => !used.has(x) && same(x)) || null;
    if (r) used.add(r);
    return { s, r, label: String(s.label) };
  });
}
async function load(wa) {
  wa = pad5(wa);
  const d = await getJSON(`data/wells/${encodeURIComponent(wa)}.json`);
  if (!d) return null;
  const padId = d.pad && d.pad.id;
  const [rows, totals, padFile, summary, padMetrics] = await Promise.all([
    padId ? FVM.rows(padId, wa) : [], padId ? FVM.totals(padId, wa) : null,
    padId ? getJSON(`data/region/pads/${encodeURIComponent(padId)}.json`) : null, getJSON('data/metrics/summary.json'),
    padId ? FVM.pad(padId) : null]);
  const prow = padFile && (padFile.wells || []).find(x => pad5(x.well.wa) === wa);
  const well = { ...((prow && prow.well) || {}), ...(d.well || {}) };
  const dates = rows.map(r => r.date).filter(Boolean).sort();
  // the pad's other wells with curves, for "Compare with"
  const others = padMetrics ? Object.entries(padMetrics.wells).filter(([w, x]) => w !== wa && x.totals && x.totals.stagesCharted > 0)
    .map(([w]) => { const p = padFile && padFile.wells.find(x => pad5(x.well.wa) === w); return { wa: w, name: p ? p.well.name : '' }; }) : [];
  const charts = joinCharts(d.stages, rows || []);
  // a chart's row with no filed interval takes the chart's own, and says so
  for (const c of charts) if (c.r && c.r.top == null && num(c.s.top_m)) Object.assign(c.r, { top: c.s.top_m, base: num(c.s.base_m) ? c.s.base_m : c.s.top_m, mdFrom: 'chart' });
  // toe to heel: deepest first, then by stage number (not as text)
  const ordered = (rows || []).slice().sort((a, b) => (a.top == null) - (b.top == null) || (num(a.top) && num(b.top) ? b.top - a.top : 0)
    || (+a.n || 0) - (+b.n || 0) || String(a.label).localeCompare(String(b.label), undefined, { numeric: true }));
  return { wa, d, well, pad: d.pad || {}, file: (totals && totals.file) || d.file || '', rows: ordered, totals, summary,
           charts, first: dates[0] || null, last: dates[dates.length - 1] || null, others };
}

window.FVReport = { quantile, median, CHANNELS, stageCurve, valueAt, grid, envelope, minStages, qc, flagGroups, TABLE, tableRows,
                    CSV_COLS, csv, prodSeries, daysIn, addMonths, joinCharts, load };

// ====================== the page ======================
const $ = id => document.getElementById(id);
if (typeof document === 'undefined' || !document.getElementById || !$('rp-main')) return;
const WA = new URLSearchParams(location.search).get('wa') || '';
let M = null;                           // the well, as load() puts it together
const view = { ch: 'press', x: 'min', cmp: '' };
try { Object.assign(view, JSON.parse(sessionStorage.getItem('stratum.report') || '{}')); } catch (e) { /* private mode */ }
if (!CHANNELS[view.ch]) view.ch = 'press';
if (view.x !== 'vol') view.x = 'min';
const keepView = () => { try { sessionStorage.setItem('stratum.report', JSON.stringify(view)); } catch (e) { /* private mode */ } };
const h = (tag, props, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v; else if (k === 'text') e.textContent = v; else if (k === 'html') e.innerHTML = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) e.append(c);
  return e;
};
const LEVEL = { serious: 'Serious', warning: 'Warning', info: 'Check' };
const glyph = lvl => (lvl === 'info' ? '•' : '▲');

// a stage's chart, in the stage charts window: stacked there when one is open from here
let stagesWin = null;
const stageUrl = label => `stages.html?s=${encodeURIComponent(M.wa)}:${encodeURIComponent(label)}`;
function openStage(label) {
  try {
    if (stagesWin && !stagesWin.closed && stagesWin.stratumStages) { stagesWin.stratumStages.add(M.wa, label); stagesWin.focus(); return; }
  } catch (e) { /* not reachable: open afresh */ }
  stagesWin = window.open(stageUrl(label), 'stratum-stages');
  if (stagesWin) { try { stagesWin.focus(); } catch (e) { /* the browser decides */ } }
  else say(`Your browser blocked the stage window. <a href="${stageUrl(label)}" target="_blank" rel="noopener">Open stage ${esc(label)}</a>`);
}
let sayT = 0;
function say(html) { const n = $('rp-note'); n.innerHTML = html; n.hidden = false; clearTimeout(sayT); sayT = setTimeout(() => { n.hidden = true; }, 9000); }
const stageBtn = (label, extra) => h('button', { type: 'button', class: 'rp-st', title: `Open stage ${label}'s chart`, onclick: () => openStage(label) }, extra || String(label));

// ---------- header ----------
function header() {
  const w = M.well, t = M.totals || {}, q = qc(M.totals, M.rows);
  document.title = `FracView — ${w.name || 'WA ' + M.wa} · stage report`;
  $('rp-name').textContent = w.name || `WA ${M.wa}`;
  $('rp-ident').textContent = [`WA ${M.wa}`, w.uwi, w.operator].filter(Boolean).join(' · ');
  const facts = [
    ['Pad', M.pad.name], ['Field', w.field], ['Formation', w.formation],
    ['Frac dates', M.first ? (M.last && M.last !== M.first ? `${M.first} to ${M.last}` : M.first) : null],
    ['Lateral', num(w.lateral_m) ? `${fmt(w.lateral_m)} m` : null],
    ['TD', num(w.td_m) ? `${fmt(w.td_m)} m MD${num(w.tvd_m) ? ` · ${fmt(w.tvd_m)} m TVD` : ''}` : null],
    ['Stages', t.stagesFiled != null ? `${fmt(t.stagesFiled)} filed · ${fmt(q.charted)} charted` : `${fmt(M.rows.length)}`],
  ].filter(f => f[1]);
  $('rp-facts').replaceChildren(...facts.map(([k, v]) => h('div', null, h('dt', { text: k }), h('dd', { text: v }))));
  const curves = !q.charted ? 'No treatment curves: the Lab has not read this well’s frac report, so the stages below are as filed.'
    : t.src === '1 s' ? 'Curves: the Lab’s 1-second export of each chart. The overlay below draws them as thinned for the web.'
    : `Curves: the Lab’s read of each chart, thinned to one point every ${t.src || 'few seconds'}.`;
  $('rp-prov').replaceChildren(
    h('span', null, 'Treatment report: ', h('b', { text: M.file || 'not on file' }), '. '),
    h('span', { text: curves + ' ' }),
    h('span', { text: 'Filed numbers: BC Energy Regulator hydraulic fracture table. ' }),
    h('span', { text: 'Contains information licensed under the BC Energy Regulator Open Data Licence.' }));
}

// ---------- the checks ----------
function badges() {
  const q = qc(M.totals, M.rows), S = M.summary || {}, out = [];
  const state = (ok, warn) => (ok ? 'good' : warn ? 'warning' : 'serious');
  const chip = s => h('span', { class: 'rp-chip ' + s }, h('i', { 'aria-hidden': 'true', text: s === 'good' ? '✓' : '!' }), { good: 'Close', warning: 'Check', serious: 'Far off' }[s]);
  const card = (title, big, s, text, foot) => h('div', { class: 'rp-badge' },
    h('div', { class: 'rp-badge-h' }, h('span', { text: title }), s ? chip(s) : null),
    h('div', { class: 'rp-big', text: big }), h('p', { text }), foot ? h('p', { class: 'rp-foot', text: foot }) : null);
  if (!q.charted) {
    $('rp-qc').replaceChildren(h('p', { class: 'rp-empty', text: 'Nothing to check yet: this well has no treatment curves, only its filing.' }));
    return;
  }
  const off = p => Math.abs(p - 100);
  if (num(q.prop.pct)) out.push(card('Proppant, curves vs filed', `${fmt(q.prop.pct)}%`, state(off(q.prop.pct) <= 10, off(q.prop.pct) <= 20),
    `${fmt(q.prop.curves)} t integrated from the curves against ${fmt(q.prop.filed)} t filed for the same ${fmt(q.charted)} stages.`,
    num(S.propWithin10pct) ? `Across the region, ${fmt(S.propWithin10pct * 100)}% of charted wells come within 10%.` : null));
  if (num(q.fluid.pct)) out.push(card('Clean fluid, curves vs filed', `${fmt(q.fluid.pct)}%`, state(off(q.fluid.pct) <= 10, off(q.fluid.pct) <= 20),
    `${fmt(q.fluid.curves)} m³ from the curves against ${fmt(q.fluid.filed)} m³ filed for the same stages.`,
    num(S.fluidWithin10pct) ? `Across the region, ${fmt(S.fluidWithin10pct * 100)}% of charted wells come within 10%.` : null));
  if (q.isip.n) out.push(card('ISIP, falloff vs filed', `${q.isip.median > 0 ? '+' : ''}${fmt(q.isip.median, 1)} MPa`,
    state(Math.abs(q.isip.median) <= 1, Math.abs(q.isip.median) <= 3),
    `The median difference between the ISIP read from the falloff and the filed ISIP, over the ${fmt(q.isip.n)} stages that have both; ${fmt(q.isip.within2)} are within 2 MPa.`,
    num(S.isipWithin2MPa) ? `Across the region, ${fmt(S.isipWithin2MPa * 100)}% of stages are within 2 MPa.` : null));
  else out.push(card('ISIP, falloff vs filed', '—', null, 'No stage has both a falloff long enough to read an ISIP from and a filed ISIP.'));
  out.push(card('Charts matched by time', `${fmt(q.matched.n)} of ${fmt(q.matched.of)}`, state(q.matched.n >= q.matched.of * 0.95, q.matched.n >= q.matched.of * 0.8),
    'Charts paired with a filed stage by when they were pumped. The rest are paired by stage number.'));
  out.push(card('Depth vs filing', q.depth ? `${fmt(q.depth)} chart${q.depth > 1 ? 's' : ''}` : 'None', state(!q.depth, q.depth <= 2),
    q.depth ? 'Charts whose printed depth lies outside the interval filed for the stage pumped at that time.' : 'Every chart’s printed depth lies inside the interval filed for the stage pumped at that time.'));
  $('rp-qc').replaceChildren(...out);
}

// ---------- flags ----------
function flagList() {
  const groups = flagGroups(M.rows);
  if (!groups.length) {
    $('rp-flags').replaceChildren(h('p', { class: 'rp-empty', text: M.charts.length ? 'No stage was flagged.' : 'Flags come from the treatment curves; this well has none yet.' }));
    return;
  }
  $('rp-flags').replaceChildren(...groups.map(g => h('div', { class: 'rp-flag ' + g.info.level },
    h('div', { class: 'rp-flag-h' }, h('i', { 'aria-hidden': 'true', text: glyph(g.info.level) }), h('b', { text: g.info.t }),
      h('span', { class: 'rp-lvl', text: LEVEL[g.info.level] }), h('span', { class: 'rp-n', text: `${g.rows.length} stage${g.rows.length > 1 ? 's' : ''}` })),
    h('p', { text: g.info.d }),
    h('div', { class: 'rp-sts' }, g.rows.map(r => String(r.label)).sort((x, y) => x.localeCompare(y, undefined, { numeric: true })).map(l => stageBtn(l))))));
}

// ---------- the overlay ----------
const CH_VAR = { press: 'var(--press)', rate: 'var(--rate)', conc: 'var(--conc)' };
let OV = null;                         // this drawing's scales and curves, for hover
let cmpCache = new Map();              // wa -> its stages from the well file
function niceStep(span, n) {
  const raw = span / Math.max(1, n), p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
}
const niceCeil = v => { if (!(v > 0)) return 1; const s = niceStep(v, 5); return Math.ceil(v / s) * s; };
const levelOf = r => { const f = r ? FVM.opFlags(r) : []; return f.some(k => FVM.FLAG_INFO[k].level === 'serious') ? 'serious' : f.length ? 'warning' : ''; };
let printW = 0;                         // the page's width on paper, while printing
async function overlay() {
  const box = $('rp-ov'), W = printW || box.clientWidth;
  const chOk = M.charts.length > 0;
  $('rp-ov-ctl').hidden = !chOk;
  if (!chOk) { box.innerHTML = '<p class="rp-empty">No treatment curves for this well yet: the Lab has not read its frac report.</p>'; $('rp-ov-legend').replaceChildren(); $('rp-ov-cap').textContent = ''; return; }
  const ch = CHANNELS[view.ch];
  const lines = M.charts.map(c => ({ ...c, c: stageCurve(c.s, view.ch, view.x), lvl: levelOf(c.r) })).filter(x => x.c);
  if (!lines.length) { box.innerHTML = `<p class="rp-empty">None of this well’s charts has a ${esc(ch.t.toLowerCase())} curve.</p>`; $('rp-ov-legend').replaceChildren(); return; }
  // the x range: the longest stage, unless a few run far past the rest
  const ends = lines.map(l => l.c.x[l.c.x.length - 1]).sort((a, b) => a - b), mid = quantile(ends, 0.5);
  const xMax = niceCeil(Math.min(ends[ends.length - 1], mid * 2)), past = ends.filter(e => e > xMax).length;
  const ys = []; lines.forEach(l => l.c.y.forEach(v => { if (v != null) ys.push(v); }));
  ys.sort((a, b) => a - b);
  const yMax = niceCeil(quantile(ys, 0.998) * 1.04);
  const xs = grid(xMax, 240), env = envelope(lines.map(l => l.c), xs, minStages(lines.length));
  // the other well's median, on the same grid
  let cmp = null;
  if (view.cmp) {
    if (!cmpCache.has(view.cmp)) cmpCache.set(view.cmp, getJSON(`data/wells/${encodeURIComponent(view.cmp)}.json`));
    const od = await cmpCache.get(view.cmp);
    const oc = od ? (od.stages || []).map(s => stageCurve(s, view.ch, view.x)).filter(Boolean) : [];
    if (oc.length) cmp = { wa: view.cmp, n: oc.length, env: envelope(oc, xs, minStages(oc.length)), name: (od.well && od.well.name) || '' };
  }
  const Ht = W < 560 ? 250 : 330, ml = 50, mr = 14, mt = 14, mb = 38;
  const X = v => ml + v / xMax * (W - ml - mr), Y = v => mt + (1 - Math.max(0, Math.min(1.02, v / yMax))) * (Ht - mt - mb);
  const path = (xa, ya) => { let d = '', pen = false; for (let i = 0; i < xa.length; i++) { const y = ya[i]; if (y == null || xa[i] > xMax) { pen = false; continue; } d += (pen ? 'L' : 'M') + X(xa[i]).toFixed(1) + ' ' + Y(y).toFixed(1); pen = true; } return d; };
  const out = [`<defs><clipPath id="ov-clip"><rect x="${ml}" y="${mt - 2}" width="${W - ml - mr}" height="${Ht - mt - mb + 4}"/></clipPath></defs>`];
  const xt = niceStep(xMax, (W - ml - mr) / 80), yt = niceStep(yMax, (Ht - mt - mb) / 44);
  for (let v = 0; v <= yMax + 1e-9; v += yt) out.push(`<line class="gr" x1="${ml}" x2="${W - mr}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}"/><text class="ax" x="${ml - 6}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end">${fmt(v, yt < 1 ? 1 : 0)}</text>`);
  for (let v = 0; v <= xMax + 1e-9; v += xt) out.push(`<line class="gr" x1="${X(v).toFixed(1)}" x2="${X(v).toFixed(1)}" y1="${mt}" y2="${Ht - mb}"/><text class="ax" x="${X(v).toFixed(1)}" y="${Ht - mb + 15}" text-anchor="middle">${fmt(v)}</text>`);
  out.push(`<text class="ax-t" x="${ml}" y="${mt - 3}" dy="-1">${esc(ch.u)}</text>`
    + `<text class="ax-t" x="${(ml + W - mr) / 2}" y="${Ht - 6}" text-anchor="middle">${view.x === 'vol' ? 'Slurry pumped since the start of the stage, m³' : 'Minutes from the start of the stage'}</text>`);
  out.push(`<g clip-path="url(#ov-clip)">`);
  // the band, the stages, the flagged stages over them, the median on top
  const ok = env.filter(e => e.p10 != null);
  if (ok.length > 1) {
    out.push(`<path class="band" d="M${ok.map(e => `${X(e.x).toFixed(1)} ${Y(e.p90).toFixed(1)}`).join('L')}L${ok.slice().reverse().map(e => `${X(e.x).toFixed(1)} ${Y(e.p10).toFixed(1)}`).join('L')}Z"/>`);
  }
  out.push(`<g class="lns">${lines.filter(l => !l.lvl).map(l => `<path d="${path(l.c.x, l.c.y)}"/>`).join('')}</g>`);
  for (const lvl of ['warning', 'serious']) out.push(`<g class="lns fl ${lvl}">${lines.filter(l => l.lvl === lvl).map(l => `<path d="${path(l.c.x, l.c.y)}"/>`).join('')}</g>`);
  out.push(`<path class="med" d="${path(env.map(e => e.x), env.map(e => e.p50))}"/>`);
  if (cmp) out.push(`<path class="cmp" d="${path(cmp.env.map(e => e.x), cmp.env.map(e => e.p50))}"/>`);
  out.push('<g id="ov-hl"></g></g>');
  // the channel's colour, for the chart, its tooltip and its key
  box.style.setProperty('--ch', CH_VAR[view.ch]); $('rp-ov-legend').style.setProperty('--ch', CH_VAR[view.ch]);
  box.innerHTML = `<svg width="${W}" height="${Ht}" viewBox="0 0 ${W} ${Ht}" role="img" aria-label="${esc(`${ch.t} of ${lines.length} stages overlaid, with the 10th to 90th percentile band and the median`)}">${out.join('')}</svg><div class="rp-tip" id="ov-tip" hidden></div>`;
  OV = { lines, env, X, Y, xMax, yMax, ml, mr, mt, mb, W, Ht, ch, cmp, hot: null };
  const svg = box.querySelector('svg');
  svg.addEventListener('pointermove', ovMove);
  svg.addEventListener('pointerleave', () => { OV.hot = null; $('ov-tip').hidden = true; $('ov-hl').innerHTML = ''; svg.style.cursor = ''; });
  svg.addEventListener('click', () => { if (OV.hot) openStage(OV.hot.label); });
  // the key: every mark on the chart, named
  const lvls = new Set(lines.map(l => l.lvl).filter(Boolean));
  const key = (cls, text) => h('span', { class: 'rp-key' }, h('i', { class: cls, 'aria-hidden': 'true' }), text);
  $('rp-ov-legend').replaceChildren(...[
    key('k-ln', `Each charted stage (${lines.length})`), key('k-band', '10th to 90th percentile across stages'), key('k-med', 'Median'),
    lvls.has('serious') && key('k-serious', 'Stage with a serious flag'), lvls.has('warning') && key('k-warning', 'Stage with a warning flag'),
    cmp && key('k-cmp', `Median of ${cmp.name || 'WA ' + cmp.wa} (${cmp.n} stages)`)].filter(Boolean));
  const steps = lines.map(l => l.s.step_s).filter(num), s0 = Math.min(...steps), s1 = Math.max(...steps);
  $('rp-ov-cap').textContent = `${ch.t}, ${ch.u}, from the curves as thinned for the web (one point every ${s0 === s1 ? fmt(s0) : `${fmt(s0)}–${fmt(s1)}`} s). `
    + `The band and median are drawn where at least ${minStages(lines.length)} stages are still pumping${past ? `; ${past} longer stage${past > 1 ? 's run' : ' runs'} past the right edge` : ''}. Hover a line for its stage; click it for the chart.`;
}
function ovMove(e) {
  const r = e.currentTarget.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top, O = OV;
  const xv = (mx - O.ml) / (O.W - O.ml - O.mr) * O.xMax;
  const tip = $('ov-tip');
  if (xv < 0 || xv > O.xMax || my < O.mt - 4 || my > O.Ht - O.mb + 4) { tip.hidden = true; $('ov-hl').innerHTML = ''; O.hot = null; return; }
  // the stage line nearest the pointer, within a few pixels
  let best = null, bd = 12;
  for (const l of O.lines) { const v = valueAt(l.c, xv); if (v == null) continue; const d = Math.abs(O.Y(v) - my); if (d < bd) { bd = d; best = { l, v }; } }
  O.hot = best ? best.l : null;
  const i = Math.round(xv / O.xMax * (O.env.length - 1)), e_ = O.env[i], u = O.ch.u, d = O.ch.d;
  const at = view.x === 'vol' ? `${fmt(xv)} m³ pumped` : `${fmt(xv, 1)} min in`;
  const hl = [`<line x1="${mx.toFixed(1)}" x2="${mx.toFixed(1)}" y1="${O.mt}" y2="${O.Ht - O.mb}" class="xh"/>`];
  const rows = [];
  if (best) {
    const l = best.l, m = l.r, path = [];
    let pen = false;
    for (let k = 0; k < l.c.x.length; k++) { const y = l.c.y[k]; if (y == null || l.c.x[k] > O.xMax) { pen = false; continue; } path.push((pen ? 'L' : 'M') + O.X(l.c.x[k]).toFixed(1) + ' ' + O.Y(y).toFixed(1)); pen = true; }
    hl.push(`<path class="hot" d="${path.join('')}"/><circle class="dot" cx="${mx.toFixed(1)}" cy="${O.Y(best.v).toFixed(1)}" r="4.5"/>`);
    rows.push(`<div class="tt-h"><b>Stage ${esc(l.label)}</b> <span>${esc(at)}: <b>${fmt(best.v, d)} ${esc(u)}</b></span></div>`);
    if (m) {
      const bits = [num(m.top) && `${fmt(m.top)}–${fmt(num(m.base) ? m.base : m.top)} m MD`, num(m.avgP) && `avg ${fmt(m.avgP, 1)} MPa`,
        num(m.fIsip) ? `ISIP ${fmt(m.fIsip, 1)} MPa filed` : num(m.isip) && `ISIP ${fmt(m.isip, 1)} MPa from the falloff`,
        num(m.prop) && `${fmt(m.prop)} t proppant`, num(m.pumpMin) && `${fmt(m.pumpMin)} min pumping`].filter(Boolean);
      if (bits.length) rows.push(`<div class="m">${esc(bits.join(' · '))}</div>`);
      FVM.flags(m).forEach(f => { const fi = FVM.FLAG_INFO[f]; rows.push(`<div class="tt-f ${fi.level}"><i>${glyph(fi.level)}</i>${esc(fi.t)}</div>`); });
    }
    rows.push('<div class="m">Click for its chart</div>');
  } else rows.push(`<div class="tt-h"><b>${esc(at)}</b></div>`);
  if (e_ && e_.p50 != null) rows.push(`<div class="tt-k"><i class="k-med"></i>Median <b>${fmt(e_.p50, d)} ${esc(u)}</b> <span class="m">· 10th–90th ${fmt(e_.p10, d)}–${fmt(e_.p90, d)} · ${e_.n} stages</span></div>`);
  if (O.cmp) { const c = O.cmp.env[i]; if (c && c.p50 != null) rows.push(`<div class="tt-k"><i class="k-cmp"></i>${esc(O.cmp.name || 'WA ' + O.cmp.wa)} median <b>${fmt(c.p50, d)} ${esc(u)}</b></div>`); }
  $('ov-hl').innerHTML = hl.join('');
  tip.innerHTML = rows.join('');
  tip.hidden = false;
  const box = $('rp-ov'), tw = tip.offsetWidth, th = tip.offsetHeight;
  let tx = mx + 14, ty = my - th - 10;
  if (tx + tw > box.clientWidth - 4) tx = mx - tw - 14;
  if (ty < 0) ty = Math.min(my + 16, box.clientHeight - th);
  tip.style.left = Math.max(0, tx) + 'px'; tip.style.top = ty + 'px';
  e.currentTarget.style.cursor = best ? 'pointer' : 'crosshair';
}
function controls() {
  const seg = (id, opts, cur, set) => {
    const g = $(id); g.replaceChildren(...opts.map(([v, t]) => h('button', { type: 'button', 'aria-pressed': String(v === cur), text: t,
      onclick: () => { set(v); keepView(); controls(); overlay(); } })));
  };
  seg('rp-ch', Object.entries(CHANNELS).map(([k, c]) => [k, c.short]), view.ch, v => { view.ch = v; });
  seg('rp-x', [['min', 'Minutes'], ['vol', 'Slurry volume']], view.x, v => { view.x = v; });
  const sel = $('rp-cmp');
  if (!sel.options.length) {
    sel.append(new Option('Compare with: none', ''));
    for (const o of M.others) sel.append(new Option(`${o.name || 'WA ' + o.wa}`, o.wa));
    sel.onchange = () => { view.cmp = sel.value; keepView(); overlay(); };
  }
  if (!M.others.some(o => o.wa === view.cmp)) view.cmp = '';
  sel.value = view.cmp; sel.hidden = !M.others.length;
}

// ---------- the stage table ----------
let sortBy = null, sortDir = 1;
function table() {
  const tr = tableRows(M.rows);
  if (!tr.length) { $('rp-table-wrap').replaceChildren(h('p', { class: 'rp-empty', text: 'No stages on file for this well.' })); return; }
  if (sortBy != null) {
    tr.sort((a, b) => {
      const x = a.cells[sortBy].v, y = b.cells[sortBy].v;
      if (x == null || y == null) return x == null && y == null ? a.i - b.i : x == null ? 1 : -1;     // blanks last, either way
      return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true })) * sortDir || a.i - b.i;
    });
  }
  const head = h('tr', null, TABLE.map((c, j) => h('th', { scope: 'col', class: c.text ? 'tx' : null, 'aria-sort': sortBy === j ? (sortDir > 0 ? 'ascending' : 'descending') : null },
    h('button', { type: 'button', title: `Sort by ${c.t.toLowerCase()}`, onclick: () => {
      if (sortBy === j) { if (sortDir > 0) sortDir = -1; else { sortBy = null; sortDir = 1; } } else { sortBy = j; sortDir = 1; }
      table(); const b = $('rp-table').querySelectorAll('thead button')[j]; if (b) b.focus();
    } }, c.t, c.u ? h('span', { class: 'u', text: c.u }) : null, h('span', { class: 'ar', 'aria-hidden': 'true', text: sortBy === j ? (sortDir > 0 ? '▲' : '▼') : '' })))));
  const body = tr.map(({ r, cells }) => h('tr', { class: r.src === 'filed' ? 'filed' : null }, cells.map((c, j) => {
    const col = TABLE[j];
    if (col.k === 'label') return h('th', { scope: 'row', class: 'tx' }, r.src !== 'filed' ? stageBtn(r.label) : h('span', { text: String(r.label), title: 'Filed only: no chart' }));
    if (col.k === 'flags') return h('td', { class: 'tx fl' }, FVM.flags(r).map(f => { const i = FVM.FLAG_INFO[f]; return h('span', { class: 'rp-fchip ' + i.level, title: `${i.t}: ${i.d}` }, h('i', { 'aria-hidden': 'true', text: glyph(i.level) }), SHORT_FLAG[f]); }));
    return h('td', { class: (col.text ? 'tx' : '') + (c.filed ? ' fd' : ''), title: c.filed ? (col.k === 'md' ? 'From the chart (the filing gives no interval)' : 'As filed (the curves give none)') : null, text: c.s });
  })));
  $('rp-table').replaceChildren(h('thead', null, head), h('tbody', null, body));
}
const SHORT_FLAG = { screenout: 'screenout', shutdown: 'shutdown', spike: 'spike', drop: 'pressure break', short: 'short', gaps: 'gaps',
  qcProp: 'proppant vs filed', qcFluid: 'fluid vs filed', qcIsip: 'ISIP vs filed', depth: 'depth vs filed' };

// ---------- production ----------
let PROD = null;
async function production() {
  const box = $('rp-prod');
  box.replaceChildren(h('p', { class: 'rp-empty', text: 'Loading production…' }));
  const all = await getJSON('data/prod/wells.json');
  const p = all && all.wells && all.wells[M.wa];
  const ser = prodSeries(p);
  if (!p || !ser.length) { box.replaceChildren(h('p', { class: 'rp-empty', text: `No production reported for this well${all && all.through ? ` through ${all.through}` : ''}.` })); PROD = null; return; }
  PROD = { p, ser, through: all.through };
  const s = p.s || {};
  const tile = (t, v, u) => h('div', { class: 'rp-tile' }, h('span', { text: t }), h('b', { text: v }), u ? h('small', { text: u }) : null);
  box.replaceChildren(
    h('div', { class: 'rp-tiles' },
      tile('First production', p.f), tile('Months producing', fmt(s.months)),
      tile('Peak gas rate', fmt(s.peakGas, 1), 'e³m³/d, best of the first 3 months'),
      tile('Gas, first 12 months', fmt(s.gas12), 'e³m³'), tile('Liquids, first 12 months', fmt(s.liq12), 'm³'),
      tile('Cumulative gas', fmt(s.cumGas), 'e³m³'), tile('Cumulative liquids', fmt(s.cumLiq), 'm³'), tile('Cumulative water', fmt(s.cumWater), 'm³')),
    h('div', { class: 'rp-pcharts', id: 'rp-pc' }),
    h('p', { class: 'rp-cap', text: `Calendar-day rates: each month’s volume over the days in the month. Liquids are condensate and oil. BC Energy Regulator zone production through ${all.through}.` }));
  prodCharts();
}
function prodCharts() {
  const box = $('rp-pc');
  if (!box || !PROD) return;
  const W = printW || box.clientWidth, ser = PROD.ser, n = ser.length;
  const one = (k, title, u, cls) => {
    const Ht = 150, ml = 50, mr = 14, mt = 22, mb = 24;
    const vals = ser.map(x => x[k]).filter(num), top = niceCeil(Math.max(...vals, 0) * 1.05);
    const X = i => ml + (n > 1 ? i / (n - 1) : 0.5) * (W - ml - mr), Y = v => mt + (1 - v / top) * (Ht - mt - mb);
    const yt = niceStep(top, 3), out = [];
    for (let v = 0; v <= top + 1e-9; v += yt) out.push(`<line class="gr" x1="${ml}" x2="${W - mr}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}"/><text class="ax" x="${ml - 6}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end">${fmt(v, yt < 1 ? 1 : 0)}</text>`);
    // a tick each January, labelled every year or every few when they crowd
    const perYear = (W - ml - mr) / Math.max(1, n / 12), every = perYear >= 36 ? 1 : perYear >= 18 ? 2 : 5;
    ser.forEach((x, i) => {
      if (!x.ym.endsWith('-01')) return;
      out.push(`<line class="gr" x1="${X(i).toFixed(1)}" x2="${X(i).toFixed(1)}" y1="${mt}" y2="${Ht - mb}"/>`);
      if (+x.ym.slice(0, 4) % every === 0) out.push(`<text class="ax" x="${X(i).toFixed(1)}" y="${Ht - 6}" text-anchor="middle">${x.ym.slice(0, 4)}</text>`);
    });
    let d = '', pen = false;
    ser.forEach((x, i) => { const v = x[k]; if (!num(v)) { pen = false; return; } d += (pen ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(v).toFixed(1); pen = true; });
    out.push(`<path class="pl ${cls}" d="${d}"/><g class="p-hl"></g>`);
    return { svg: `<div class="rp-pc"><div class="rp-pc-t"><b>${esc(title)}</b> <span>${esc(u)}</span></div><svg width="${W}" height="${Ht}" viewBox="0 0 ${W} ${Ht}" role="img" aria-label="${esc(title + ', ' + u + ', by month')}">${out.join('')}</svg></div>`, X, Y, ml, mr, k, cls, y0: mt, y1: Ht - mb };
  };
  const charts = [one('gas', 'Gas', 'e³m³ a day', 'gas'), one('liq', 'Liquids', 'm³ a day', 'liq')];
  box.innerHTML = charts.map(c => c.svg).join('') + '<div class="rp-tip" id="pc-tip" hidden></div>';
  box.querySelectorAll('svg').forEach((svg, j) => {
    svg.addEventListener('pointermove', e => {
      const r = svg.getBoundingClientRect(), mx = e.clientX - r.left, c = charts[j];
      const i = Math.max(0, Math.min(n - 1, Math.round((mx - c.ml) / (W - c.ml - c.mr) * (n - 1)))), x = ser[i];
      box.querySelectorAll('.p-hl').forEach((g, jj) => {
        const cc = charts[jj], v = x[cc.k];
        g.innerHTML = `<line class="xh" x1="${cc.X(i).toFixed(1)}" x2="${cc.X(i).toFixed(1)}" y1="${cc.y0}" y2="${cc.y1}"/>` + (num(v) ? `<circle class="dot ${cc.cls}" cx="${cc.X(i).toFixed(1)}" cy="${cc.Y(v).toFixed(1)}" r="4"/>` : '');
      });
      const tip = $('pc-tip');
      tip.innerHTML = `<div class="tt-h"><b>${esc(x.ym)}</b>${x.on != null ? ` <span class="m">${x.on} producing days</span>` : ''}</div>`
        + `<div class="tt-k"><i class="k-gas"></i>Gas <b>${fmt(x.gas, 1)} e³m³/d</b></div><div class="tt-k"><i class="k-liq"></i>Liquids <b>${fmt(x.liq, 1)} m³/d</b></div>`
        + (num(x.water) ? `<div class="tt-k m">Water ${fmt(x.water, 1)} m³/d</div>` : '');
      tip.hidden = false;
      const top = svg.parentNode.offsetTop, tw = tip.offsetWidth;
      let tx = c.X(i) + 14; if (tx + tw > W - 4) tx = c.X(i) - tw - 14;
      tip.style.left = Math.max(0, tx) + 'px'; tip.style.top = (top + 10) + 'px';
    });
    svg.addEventListener('pointerleave', () => { $('pc-tip').hidden = true; box.querySelectorAll('.p-hl').forEach(g => { g.innerHTML = ''; }); });
  });
}

// ---------- buttons ----------
function download() {
  const a = h('a', { href: URL.createObjectURL(new Blob([csv(M)], { type: 'text/csv' })), download: `FracView-${M.wa}-stages.csv` });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}
$('rp-csv').onclick = () => { if (M) download(); };
$('rp-print').onclick = () => window.print();
$('rp-charts').onclick = () => { if (M) window.open(`wellview.html?wa=${encodeURIComponent(M.wa)}`, 'stratum-charts'); };

// ---------- start ----------
let drawn = 0;
const redraw = () => { if (!M) return; overlay(); prodCharts(); };
new ResizeObserver(() => { const w = $('rp-main').clientWidth; if (w !== drawn && !printW) { drawn = w; redraw(); } }).observe($('rp-main'));
// on paper the charts are drawn for a Letter or A4 page, so their text prints at its size
addEventListener('beforeprint', () => { printW = 700; redraw(); });
addEventListener('afterprint', () => { printW = 0; redraw(); });
async function start() {
  if (!WA) { $('rp-name').textContent = 'No well chosen'; $('rp-ident').textContent = 'Open a stage report from a well’s 2D section (Stage report ↗).'; return; }
  M = await load(WA);
  if (!M) { $('rp-name').textContent = `Well ${WA} not found`; $('rp-ident').textContent = 'There is no FracView file for this well.'; document.body.classList.add('rp-none'); return; }
  document.body.classList.remove('rp-loading');
  header(); badges(); flagList(); controls(); table();
  await overlay();
  drawn = $('rp-main').clientWidth;
  production();
}
// the area this window is on, for a saved session's list (session.js)
window.stratumArea = () => (M && M.pad ? M.pad.name || '' : '');
start();
})();
