// FracView's stage metrics and spacing labels, one place for every view.
//
// Stage metrics come from web/scripts/build_stage_metrics.py: per pad,
// data/metrics/pads/<pad>.json holds every well's stage rows (columnar, `cols`),
// worked out from the treatment curves and checked against what was filed.
// Wells without curves carry their filed numbers only (src "filed"), so a view
// can colour every well by what was filed and the charted ones by more.
//
//   FVMetrics.pad(id)            -> Promise<{cols, flags, wells}> (cached)
//   FVMetrics.rows(id, wa)       -> Promise<[row objects]> for one well, toe first
//   FVMetrics.value(row, key)    the measure for a row (filed when the curves lack it)
//   FVMetrics.METRICS            the measures a view can colour by
//   FVMetrics.flags(row)         the flags on a row, as keys of FLAGS
//   FVMetrics.domain(vals, key)  a robust range for colouring
//   FVMetrics.colour(v, dom, key) colour for the theme on screen
//   FVMetrics.legend(key, dom)   a small HTML key
//
// Parent/child labels come from discover/neighbours.json (every offset lateral
// within 805 m across and 300 m up or down, signed + to the right looking
// heel to toe) and the wells' frac and first-production dates, worked out here
// with the limits in Settings (localStorage stratum.spacingLimits) so every view
// relabels together when they change (`stratum:spacing`).
//
//   FVMetrics.limits() / setLimits({across, vertical, siblingDays})
//   FVMetrics.relations()        -> Promise<Map wa -> {relation, bounded, near, parents, depletionDays}>
//   FVMetrics.REL                the four labels, with colours
(() => {
'use strict';
const dark = () => (window.StratumTheme ? StratumTheme.dark() : document.documentElement.dataset.theme === 'dark');
const getJSON = u => fetch(u).then(r => (r.ok ? r.json() : null)).catch(() => null);
const pad5 = wa => String(wa).replace(/^0+/, '').padStart(5, '0');
const plain = wa => String(+wa);

// ---- stage metrics ----
const padCache = new Map();
function pad(id) {
  // a failed load is not kept: the next ask tries again (a rebuild, a dropped connection)
  if (!padCache.has(id)) padCache.set(id, getJSON(`data/metrics/pads/${encodeURIComponent(id)}.json`).then(d => { if (!d) padCache.delete(id); return d; }));
  return padCache.get(id);
}
async function rows(id, wa) {
  const d = await pad(id);
  const w = d && d.wells[pad5(wa)];
  if (!w) return [];
  return w.rows.map(r => Object.fromEntries(d.cols.map((c, i) => [c, r[i]])));
}
async function totals(id, wa) {
  const d = await pad(id);
  const w = d && d.wells[pad5(wa)];
  return w ? w.totals : null;
}

const FLAGS = ['screenout', 'shutdown', 'spike', 'drop', 'short', 'gaps', 'qcProp', 'qcFluid', 'qcIsip', 'depth'];
const FLAG_INFO = {
  screenout: { t: 'Possible screenout', level: 'serious', d: 'Pressure climbed hard over the last three minutes with sand still going in.' },
  shutdown: { t: 'Mid-stage shutdown', level: 'warning', d: 'The rate was down for a minute or more between the first and last pumping.' },
  spike: { t: 'Pressure spike at steady rate', level: 'warning', d: 'Pressure jumped 8 MPa or more within 20 s while the rate held.' },
  drop: { t: 'Pressure break at steady rate', level: 'warning', d: 'Pressure fell 5 MPa or more within 20 s while the rate held (a plug, casing, or a new cluster taking fluid).' },
  short: { t: 'Short stage', level: 'warning', d: 'Under half the well’s usual pump time and sand.' },
  gaps: { t: 'Gaps in the curves', level: 'info', d: 'Over a tenth of the stage has no pressure or rate on the chart.' },
  qcProp: { t: 'Proppant differs from the filing', level: 'info', d: 'Sand integrated from the curves is more than 20% from what the operator filed.' },
  qcFluid: { t: 'Fluid differs from the filing', level: 'info', d: 'Clean fluid integrated from the curves is more than 20% from what was filed.' },
  qcIsip: { t: 'ISIP differs from the filing', level: 'info', d: 'The ISIP read from the falloff is more than 3 MPa from the filed ISIP.' },
  depth: { t: 'Depth differs from the filing', level: 'info', d: 'The report prints a depth outside the interval filed for the stage pumped at that time.' },
};
const OPS = new Set(['screenout', 'shutdown', 'spike', 'drop', 'short']);
function flags(row) {
  const m = (row && row.flags) || 0;
  return FLAGS.filter((f, i) => m >> i & 1);
}
const opFlags = row => flags(row).filter(f => OPS.has(f));

// the measures a view can colour stages by; `filed` is the operator's own
// number for the same thing, used when the curves don't give one
const METRICS = [
  { k: 'avgP', t: 'Avg treating pressure', u: 'MPa', d: 1, filed: 'fAvgP' },
  { k: 'maxP', t: 'Peak pressure', u: 'MPa', d: 1, filed: 'fMaxP' },
  { k: 'isip', t: 'ISIP', u: 'MPa', d: 1, prefer: 'fIsip' },
  { k: 'fg', t: 'Frac gradient', u: 'kPa/m', d: 1 },
  { k: 'avgRate', t: 'Slurry rate', u: 'm³/min', d: 1, filed: 'fRate' },
  { k: 'prop', t: 'Proppant', u: 't', d: 0, filed: 'fProp' },
  { k: 'clean', t: 'Clean fluid', u: 'm³', d: 0, filed: 'fFluid' },
  { k: 'tph', t: 'Sand rate', u: 't/h', d: 0, curves: 1 },
  { k: 'maxConc', t: 'Peak concentration', u: 'kg/m³', d: 0, curves: 1 },
  { k: 'pumpMin', t: 'Pump time', u: 'min', d: 0, curves: 1 },
  { k: 'rampMin', t: 'Ramp-up time', u: 'min', d: 1, curves: 1 },
  { k: 'pSlope', t: 'Pressure trend at rate', u: 'MPa/min', d: 2, curves: 1, centre: 0 },
  { k: 'propVsFiled', t: 'Proppant, curves vs filed', u: '%', d: 0, curves: 1, centre: 100,
    calc: r => (r.prop != null && r.fProp ? 100 * r.prop / r.fProp : null) },
  { k: 'flagCount', t: 'Flags (operations)', u: '', d: 0, curves: 1, calc: r => (r.src === 'filed' ? null : opFlags(r).length) },
];
const BY = Object.fromEntries(METRICS.map(m => [m.k, m]));
function value(row, k) {
  const m = BY[k];
  if (!row || !m) return null;
  if (m.calc) return m.calc(row);
  if (m.prefer && row[m.prefer] != null) return row[m.prefer];
  if (row[k] != null) return row[k];
  return m.filed && row[m.filed] != null ? row[m.filed] : null;
}
const fmt = (v, k) => {
  if (v == null || !isFinite(v)) return '—';
  const m = BY[k] || { d: 1 };
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: m.d, minimumFractionDigits: m.d }) + (m.u ? (m.u === '%' ? '%' : ' ' + m.u) : '');
};

// colours: one hue light to dark for a magnitude; blue, grey, orange around a
// centre (100% of filed, a flat trend); the light ramp starts where it still
// shows on white, the dark one rises to bright on the dark ground
const SEQ = {
  light: ['#9cc3f0', '#6ea6e6', '#4489d8', '#2a6cc3', '#1a52a3', '#0f3a7d', '#082a5e'],
  dark: ['#24466f', '#2b5b92', '#3474b7', '#4a8fd6', '#6aa9eb', '#93c3f4', '#c2defb'],
};
const DIV = {
  light: ['#1a52a3', '#4f86cf', '#9db8de', '#b9bcc2', '#ecb07c', '#d0712a', '#9a4708'],
  dark: ['#6aa9eb', '#4a7fb9', '#3b506b', '#5c626b', '#7b5634', '#c37a37', '#f0a35a'],
};
const NONE = { light: '#c9ced6', dark: '#4a5260' };
const lerp = (a, b, t) => a + (b - a) * t;
function hex2rgb(h) { const n = parseInt(h.slice(1), 16); return [n >> 16 & 255, n >> 8 & 255, n & 255]; }
function ramp(stops, t) {
  t = Math.max(0, Math.min(1, t));
  const x = t * (stops.length - 1), i = Math.min(stops.length - 2, Math.floor(x)), f = x - i;
  const a = hex2rgb(stops[i]), b = hex2rgb(stops[i + 1]);
  return '#' + a.map((v, j) => Math.round(lerp(v, b[j], f)).toString(16).padStart(2, '0')).join('');
}
function domain(vals, k) {
  const v = vals.filter(x => x != null && isFinite(x)).sort((a, b) => a - b);
  if (!v.length) return null;
  const q = p => v[Math.min(v.length - 1, Math.max(0, Math.round(p * (v.length - 1))))];
  let lo = q(0.05), hi = q(0.95);
  const c = BY[k] && BY[k].centre;
  if (c != null) { const r = Math.max(Math.abs(lo - c), Math.abs(hi - c)) || 1; lo = c - r; hi = c + r; }
  if (hi <= lo) hi = lo + (Math.abs(lo) || 1) * 0.01;
  return [lo, hi];
}
function colour(v, dom, k) {
  const th = dark() ? 'dark' : 'light';
  if (v == null || !isFinite(v) || !dom) return NONE[th];
  const t = (v - dom[0]) / (dom[1] - dom[0]);
  return ramp((BY[k] && BY[k].centre != null ? DIV : SEQ)[th], t);
}
function legend(k, dom) {
  const th = dark() ? 'dark' : 'light', m = BY[k] || { t: k, d: 1 };
  const stops = (m.centre != null ? DIV : SEQ)[th];
  const grad = `linear-gradient(90deg,${stops.join(',')})`;
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  return `<span class="fvm-key" style="display:inline-flex;align-items:center;gap:6px;font-variant-numeric:tabular-nums">
    <span>${dom ? esc(fmt(dom[0], k)) : ''}</span>
    <span style="display:inline-block;width:90px;height:8px;border-radius:4px;background:${grad}"></span>
    <span>${dom ? esc(fmt(dom[1], k)) : ''}</span>
    <span style="display:inline-flex;align-items:center;gap:4px;opacity:.85"><span style="display:inline-block;width:10px;height:8px;border-radius:2px;background:${NONE[th]}"></span>none</span></span>`;
}

// ---- spacing: parent, child, co-completed, standalone ----
const LIM_KEY = 'stratum.spacingLimits';
const DEF = { across: 400, vertical: 100, siblingDays: 90 };
function limits() {
  try { return Object.assign({}, DEF, JSON.parse(localStorage.getItem(LIM_KEY) || '{}')); } catch (e) { return { ...DEF }; }
}
function setLimits(l) {
  const v = Object.assign(limits(), l || {});
  try { localStorage.setItem(LIM_KEY, JSON.stringify(v)); } catch (e) { /* private mode */ }
  relCache = null;
  window.dispatchEvent(new CustomEvent('stratum:spacing', { detail: v }));
}
addEventListener('storage', e => {
  if (e.key !== LIM_KEY) return;
  relCache = null;
  window.dispatchEvent(new CustomEvent('stratum:spacing', { detail: limits() }));
});
const REL = {
  parent: { t: 'Parent', s: 'P', d: 'Offsets came after it while it was producing', light: '#2563eb', dark: '#4d8dff' },
  child: { t: 'Child', s: 'C', d: 'An offset was already producing when it was fracked', light: '#e8590c', dark: '#ff8a4d' },
  'co-completed': { t: 'Co-completed', s: 'S', d: 'Fracked with its offsets, none producing yet', light: '#0b8ea3', dark: '#3ecf8e' },
  standalone: { t: 'Standalone', s: '–', d: 'No offset lateral within the limits', light: '#868e96', dark: '#9aa1a9' },
};
const relColour = r => (REL[r] ? REL[r][dark() ? 'dark' : 'light'] : NONE[dark() ? 'dark' : 'light']);
const day = s => { if (!s) return null; const p = String(s).slice(0, 10).split('-').map(Number); return Date.UTC(p[0], (p[1] || 1) - 1, p[2] || 1) / 864e5; };
let relCache = null, baseP = null;
function base() {
  return baseP || (baseP = Promise.all([getJSON('data/discover/neighbours.json'), getJSON('data/discover/wells.json')]).then(([nb, w]) => {
    const info = new Map();
    if (w) {
      const ci = Object.fromEntries(w.columns.map((c, i) => [c, i]));
      for (const r of w.rows) info.set(String(r[ci.wa]), { fracStart: r[ci.fracStart], firstProd: r[ci.firstProd], pad: r[ci.pad] });
    }
    // without the offsets file nothing can be labelled (rather than every well "standalone")
    if (!nb) { baseP = null; throw Error('The spacing data could not be loaded.'); }
    return { nb: nb.wells || {}, info };
  }));
}
// (`near` lists every offset within the limits with its own label, parents included,
// each parent with the days it had produced when this well was fracked (prodDays);
// an empty map when the offsets could not be loaded)
// at its own completion: a child if an offset within the limits had been
// producing for longer than the sibling window, co-completed if offsets were
// fracked within that window, a parent if offsets only came later; bounded by
// offsets on both sides (any time), half-bounded on one, unbounded on neither
async function relations(lim = limits()) {
  const key = JSON.stringify(lim);
  if (relCache && relCache.key === key) return relCache.map;
  let got;
  try { got = await base(); } catch (e) { return new Map(); }
  const { nb, info } = got;
  const map = new Map();
  for (const [wa, list] of Object.entries(nb)) {
    const me = info.get(wa) || {}, start = day(me.fracStart);
    const near = list.filter(n => Math.abs(n[1]) <= lim.across && Math.abs(n[2]) <= lim.vertical)
      .map(n => ({ wa: String(n[0]), across: n[1], vertical: n[2], overlap: n[3] }));
    const sides = new Set(near.map(n => Math.sign(n.across) || 1));
    let parents = 0, sibs = 0, later = 0, dep = null;
    for (const n of near) {
      const o = info.get(n.wa) || {}, os = day(o.fracStart), op = day(o.firstProd);
      if (start == null || os == null) { n.rel = null; continue; }
      const gap = start - os;
      if (gap > lim.siblingDays && op != null && start - op > 0) { n.rel = 'parent'; n.prodDays = Math.round(start - op); parents++; dep = Math.max(dep ?? 0, start - op); }
      else if (Math.abs(gap) <= lim.siblingDays) { n.rel = 'sibling'; sibs++; }
      else if (gap < -lim.siblingDays) { n.rel = 'child'; later++; }
      else n.rel = null;
    }
    const relation = !near.length ? 'standalone' : parents ? 'child' : later ? 'parent' : sibs ? 'co-completed' : 'standalone';
    map.set(wa, { relation, bounded: sides.size === 2 ? 'bounded' : sides.size ? 'half' : 'unbounded', near, parents,
                  depletionDays: dep == null ? null : Math.round(dep) });
  }
  relCache = { key, map };
  return map;
}
const BOUNDED = { bounded: 'Bounded (offsets both sides)', half: 'Half-bounded (one side)', unbounded: 'Unbounded' };

window.FVMetrics = { pad, rows, totals, value, fmt, flags, opFlags, FLAGS, FLAG_INFO, METRICS, BY, domain, colour, legend,
                     limits, setLimits, relations, REL, relColour, BOUNDED, DEF_LIMITS: DEF, pad5, plain };
})();
