// Stratum — one well end to end, as a vertical section: surface to TD along the
// line from the pad to the toe, the stages at their measured depths, gamma
// along the lateral. Docked under the map or the 3D view (?embedded=1, driven
// by its parent over postMessage), or popped out into a window of its own that
// follows the well being looked at in the main window (BroadcastChannel
// 'stratum-section': the map, the 3D view and the well charts all announce it).
'use strict';
const $ = id => document.getElementById(id);
const Q = new URLSearchParams(location.search);
const EMBED = Q.get('embedded') === '1';
const ORIGIN = location.origin;
const PREF_KEY = 'stratum.section';
// the stages coloured by one of their numbers (metrics.js), or '' for none: a
// setting of its own, kept with the account and in sessions like the others
const METRIC_KEY = 'stratum.sectionMetric';
const FVM = window.FVMetrics || null;

// gamma in the colours chosen for every view (gamma-palettes.js), and the slate
// the lateral is drawn in where there is none
const gammaInk = (v, g) => window.StratumGamma.ink(v, g);
const GR_MAX = 250;
// the marks' inks for the theme on screen (theme.js); text takes its colour from the CSS
const INKS = {
  light: { neutral: '#3d4f5b', build: '#8a9ba6', curves: '#0d8577', filed: '#7b8e9a', ground: '#9fb0bb', halo: '#ffffff', haloOp: .9,
           pad: '#14212b', hole: '#ffffff', track: '#f6f8fa', cross: '#14212b', grid: '#e4eaef', press: '#a31631', rate: '#1f6feb',
           serious: '#d6402b', warning: '#e8a400', bang: { serious: '#ffffff', warning: '#14212b' }, paper: '#ffffff' },
  dark:  { neutral: '#d6e6ee', build: '#8fa9b5', curves: '#5ee2d0', filed: '#6b8290', ground: '#4f6d7b', halo: '#000', haloOp: .5,
           pad: '#e7f4fa', hole: '#0a141d', track: '#0d1b25', cross: '#e7f4fa', grid: '#1a2c37', press: '#f0555a', rate: '#4f8ff7',
           serious: '#ff6f5c', warning: '#f7c03e', bang: { serious: '#0a141d', warning: '#0a141d' }, paper: '#0a141d' },
};
const inks = () => INKS[document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'];
let K = inks();

let WA = Q.get('wa') || '';
let HI = Q.get('stage');        // the stage picked out, by label
let mode = 'well', colorBy = 'stages', curvesOn = true;
try { const p = JSON.parse(localStorage.getItem(PREF_KEY) || '{}'); if (p.mode) mode = p.mode; if (p.color) colorBy = p.color; if (p.curves === false) curvesOn = false; } catch (e) { /* private mode */ }
const readMetric = () => { try { const k = localStorage.getItem(METRIC_KEY) || ''; return FVM && FVM.BY[k] ? k : ''; } catch (e) { return ''; } };
let metric = readMetric();
// the ribbon's name in the axis gutter (the key above it gives the full one)
const SHORT = { avgP: 'Avg P', maxP: 'Peak P', isip: 'ISIP', fg: 'FG', avgRate: 'Rate', prop: 'Sand', clean: 'Fluid', tph: 't/h',
  maxConc: 'Conc', pumpMin: 'Pump', rampMin: 'Ramp', pSlope: 'P trend', propVsFiled: 'Sand %', flagCount: 'Flags' };
let W = null;                   // the assembled well: trajectory, stages, gamma
let GAMMA = null;               // data/gamma.json, fetched once
let G = null;                   // this render's geometry, for hover
let hover = null, seq = 0;
// the wine rack's line where it crosses this well, metres MD (winerack.js, by way of
// the main window): shown as a hover would be, whenever the pointer is not here
let EXT = Q.get('at') != null && isFinite(+Q.get('at')) && Q.get('at') !== '' ? { wa: Q.get('wa') || '', md: +Q.get('at') } : null;
let pointerIn = false;

const fmt = (v, d = 0) => v == null || !isFinite(v) ? '–'
  : (Math.abs(v) < 0.5 * Math.pow(10, -d) ? 0 : Number(v)).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d });
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
const compass = deg => COMPASS[Math.round(((deg % 360) + 360) % 360 / 22.5) % 16];
function niceStep(span, n) {
  const raw = span / Math.max(1, n), p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
}

const cache = new Map();
function getJSON(u) {
  if (!cache.has(u)) cache.set(u, fetch(u).then(r => { if (!r.ok) throw Error(`${u}: ${r.status}`); return r.json(); })
    .catch(e => { cache.delete(u); throw e; }));
  return cache.get(u);
}

// ---------- data ----------
async function load(wa) {
  const my = ++seq;
  WA = String(wa); W = null; hover = null;
  $('ws-name').textContent = 'Loading…'; $('ws-sub').textContent = '';
  let d, row = null;
  try { d = await getJSON(`data/wells/${encodeURIComponent(WA)}.json`); } catch (e) { if (my === seq) empty(`Well ${WA || '?'} not found.`, `Well ${WA || '?'}`); return; }
  const padId = d.pad && d.pad.id;
  if (padId) try { row = (await getJSON(`data/region/pads/${encodeURIComponent(padId)}.json`)).wells.find(x => String(x.well.wa) === WA) || null; } catch (e) { /* no survey */ }
  if (my !== seq) return;
  W = assemble(d, row);
  if (!FVM || !padId) W.mrows = [];           // no numbers to wait for
  attachGamma();
  syncUrl(); header(); render(); announce();
  if (!GAMMA) getJSON('data/gamma.json').then(g => { GAMMA = g; if (W && my === seq) { attachGamma(); header(); render(); } }).catch(() => {});
  // the stages' numbers, worked out from their curves and checked against the filing
  if (FVM && padId) FVM.rows(padId, WA).then(rows => {
    if (my !== seq || !W) return;
    attachMetrics(rows || []); cardFor = null; header(); render();
  }).catch(() => {});
}

// Each stage's row of numbers (metrics.js). A row is the stage's when it has the
// stage's label at the stage's interval, else its label, else it was filed at
// that interval: a chart's label and the filing's do not always agree (a chart
// pumped twice on one interval, or 88A filed as 88a). Rows no stage takes keep
// their flags, shown where they were pumped.
function attachMetrics(rows) {
  W.mrows = rows;
  W.stages.forEach(s => { s.m = null; });
  const free = new Set(rows), lab = x => String(x).toLowerCase();
  const near = (r, s) => r.top != null && Math.abs(r.top - s.top) <= 10;
  const passes = [(r, s) => lab(r.label) === lab(s.label) && near(r, s), (r, s) => lab(r.label) === lab(s.label), near];
  for (const ok of passes) for (const s of W.stages) {
    if (s.m) continue;
    const c = [...free].filter(r => ok(r, s));
    if (!c.length) continue;
    s.m = c.find(r => (r.src !== 'filed') === s.curves) || c[0];
    free.delete(s.m);
  }
  W.loose = [...free].filter(r => r.top != null && FVM.opFlags(r).length);
}

function assemble(d, row) {
  const w = { ...((row && row.well) || {}), ...(d.well || {}) };
  const t = row && row.trajectory;
  const traj = t && t.md && t.md.length > 1
    ? t.md.map((m, i) => ({ md: m, tvd: t.tvd[i], ns: t.ns[i], ew: t.ew[i] })).filter(p => [p.md, p.tvd, p.ns, p.ew].every(Number.isFinite))
    : [];
  // the section runs from the pad toward TD, so a lateral reads left to right
  const end = traj[traj.length - 1];
  const az = end && Math.hypot(end.ns, end.ew) > 1 ? Math.atan2(end.ew, end.ns) : 0;
  traj.forEach(p => { p.vs = p.ns * Math.cos(az) + p.ew * Math.sin(az); });

  // stages: as filed with the BCER (they carry the summaries), marked where the Lab's curves exist
  const hasSeries = s => s.series && Object.values(s.series).some(a => Array.isArray(a) && a.some(v => v != null));
  const curves = new Map((d.stages || []).filter(hasSeries).map(s => [String(s.label), s]));
  const filed = row && row.stages && row.stages.length ? row.stages : d.bcer_stages || [];
  const seen = new Set(), stages = [];
  const add = s => {
    const label = String(s.label != null ? s.label : s.n);
    if (seen.has(label) || s.top_m == null || !isFinite(s.top_m)) return;
    seen.add(label);
    const a = +s.top_m, b = s.base_m != null && isFinite(s.base_m) ? +s.base_m : a, c = curves.get(label);
    stages.push({ label, top: Math.min(a, b), base: Math.max(a, b), mid: (a + b) / 2, curves: !!c,
                  series: c ? c.series : null, step: c ? c.step_s || 1 : null,
                  date: s.date || (c && c.date) || '', start: String((c && c.start) || s.start || '').slice(0, 5),
                  proppant: s.proppant_t, fluid: s.fluid_m3, rate: s.avg_rate_m3_min, pmax: s.max_pressure_mpa,
                  minutes: c ? c.minutes : null });
  };
  filed.forEach(add);
  (d.stages || []).forEach(add);
  if (!stages.length && row) (row.depth_intervals || []).forEach(s => add({ ...s, label: s.n }));
  stages.sort((a, b) => a.mid - b.mid);
  // each stage owns the lateral halfway to its neighbours: the hover target
  stages.forEach((s, i) => {
    const p = stages[i - 1], n = stages[i + 1], half = p && n ? 0 : p ? (s.mid - p.mid) / 2 : n ? (n.mid - s.mid) / 2 : 30;
    s.z0 = p ? (p.mid + s.mid) / 2 : s.mid - half;
    s.z1 = n ? (s.mid + n.mid) / 2 : s.mid + half;
  });

  let heel = w.heel_md > 0 ? +w.heel_md : null;
  if (heel == null) for (let i = 1; i < traj.length; i++) {         // first station past 80° inclination
    const a = traj[i - 1], b = traj[i], dm = b.md - a.md;
    if (dm > 0 && (b.tvd - a.tvd) / dm < Math.cos(80 * Math.PI / 180)) { heel = a.md; break; }
  }
  return { well: w, pad: d.pad || {}, traj, az, stages, heel, td: end ? end.md : w.td_m, gamma: null, nCurves: curves.size, units: d.units || {} };
}

function attachGamma() {
  if (!W) return;
  const g = GAMMA && GAMMA.wells && GAMMA.wells[WA];
  W.gamma = g && Array.isArray(g.v) && g.v.some(v => v != null)
    ? { md0: g.md0, bin: GAMMA.bin_m || 5, v: g.v, estimated: !!g.estimated, from: g.from,
        lo: (GAMMA.scale && GAMMA.scale.lo) || 70, hi: (GAMMA.scale && GAMMA.scale.hi) || 180, p50: GAMMA.scale ? GAMMA.scale.p50 : null }
    : null;
}
const gammaAt = md => {
  const g = W && W.gamma; if (!g) return null;
  const v = g.v[Math.floor((md - g.md0) / g.bin)];
  return v == null ? null : v;
};

// the trajectory at a measured depth, interpolated between survey stations
function at(md) {
  const t = W.traj;
  if (md <= t[0].md) return t[0];
  if (md >= t[t.length - 1].md) return t[t.length - 1];
  let lo = 0, hi = t.length - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (t[m].md <= md) lo = m; else hi = m; }
  const a = t[lo], b = t[hi], f = (md - a.md) / (b.md - a.md);
  return { md, tvd: a.tvd + (b.tvd - a.tvd) * f, vs: a.vs + (b.vs - a.vs) * f };
}
const stageAt = md => W.stages.find(s => md >= s.z0 && md <= s.z1) || null;
// the rack's line as a hover point, in this render's geometry
function extHover() {
  if (!EXT || EXT.wa !== WA || !W || !G || !W.traj.length) return null;
  const p = at(EXT.md);
  return { md: EXT.md, vs: p.vs, tvd: p.tvd, x: G.X(p.vs), y: G.Y(p.tvd), ext: true };
}
// a curve squeezed into `n` columns: each column's low and high, in order, so a
// spike survives however narrow the stage is drawn. [[column, value], ...]
function spark(v, n) {
  const out = [], len = v.length;
  if (!len) return out;
  n = Math.max(1, Math.min(n, len));
  for (let c = 0; c < n; c++) {
    let lo = null, hi = null, ilo = 0, ihi = 0;
    for (let i = Math.floor(c * len / n); i < Math.floor((c + 1) * len / n); i++) {
      const x = v[i];
      if (x == null || !isFinite(x)) continue;
      if (lo == null || x < lo) { lo = x; ilo = i; }
      if (hi == null || x > hi) { hi = x; ihi = i; }
    }
    if (lo == null) { out.push(null); continue; }
    if (lo === hi) out.push([c, lo]);
    else if (ilo < ihi) out.push([c, lo], [c, hi]); else out.push([c, hi], [c, lo]);
  }
  return out;
}
// one scale for every stage's pressure, and one for rate, so stages compare by eye
function curveScale() {
  const top = k => niceCeil(Math.max(0, ...W.stages.filter(s => s.series && Array.isArray(s.series[k]))
    .map(s => s.series[k].reduce((m, x) => x != null && isFinite(x) && x > m ? x : m, 0))));
  return { press: top('press'), rate: top('rate') };
}

// the ribbon's key, centred above the frame between the compass chips: the
// measure, its low and high ends, and the grey of a stage with no number; the
// measure's name goes first when there is no room, then the grey
function ribbonKey(m, dom, x0, x1, y, comp) {
  const room = x1 - x0 - 2 * (comp.length * 6.6 + 30), mid = (x0 + x1) / 2;
  if (!dom) return room > 220 ? `<text class="rb-t" x="${mid}" y="${y}" text-anchor="middle">${esc(m.t)}: no numbers for this well</text>` : '';
  const lo = FVM.fmt(dom[0], m.k), hi = FVM.fmt(dom[1], m.k), GR = 64;
  const all = [{ k: 'name', w: m.t.length * 5.9 + 12 }, { k: 'lo', w: lo.length * 6.6 + 6 }, { k: 'bar', w: GR + 6 },
               { k: 'hi', w: hi.length * 6.6 + 14 }, { k: 'none', w: 14 + 4 * 5.9 }];
  const fit = [all, all.filter(p => p.k !== 'name'), all.filter(p => p.k !== 'name' && p.k !== 'none')]
    .find(ps => ps.reduce((a, p) => a + p.w, 0) <= room);
  if (!fit) return '';
  const n = 9, stops = Array.from({ length: n }, (_, i) =>
    `<stop offset="${(i / (n - 1)).toFixed(3)}" stop-color="${FVM.colour(dom[0] + (dom[1] - dom[0]) * i / (n - 1), dom, m.k)}"/>`).join('');
  let x = mid - fit.reduce((a, p) => a + p.w, 0) / 2;
  const out = [`<defs><linearGradient id="ws-kg" x1="0" x2="1" y1="0" y2="0">${stops}</linearGradient></defs>`];
  for (const p of fit) {
    if (p.k === 'name') out.push(`<text class="rb-t" x="${x}" y="${y}">${esc(m.t)}</text>`);
    else if (p.k === 'lo' || p.k === 'hi') out.push(`<text class="rb-n" x="${x}" y="${y}">${esc(p.k === 'lo' ? lo : hi)}</text>`);
    else if (p.k === 'bar') out.push(`<rect x="${x}" y="${y - 8}" width="${GR}" height="8" rx="4" fill="url(#ws-kg)"/>`);
    else out.push(`<rect x="${x}" y="${y - 8}" width="10" height="8" rx="2" fill="${FVM.colour(null, null, m.k)}"/><text class="rb-t" x="${x + 14}" y="${y}">none</text>`);
    x += p.w;
  }
  return `<g>${out.join('')}<title>${esc(`${m.t}: ${lo} to ${hi} (the well's 5th to 95th percentile); grey has no number`)}</title></g>`;
}
// a flagged stage's marker: a triangle pointing at the hole, red-orange when one
// of its flags is serious (a possible screenout), amber for a warning
function flagMark(x, y, r, label) {
  const f = FVM.opFlags(r), lvl = f.some(k => FVM.FLAG_INFO[k].level === 'serious') ? 'serious' : 'warning';
  return `<g transform="translate(${x.toFixed(1)},${y.toFixed(1)})"><title>${esc(`Stage ${label}: ${f.map(k => FVM.FLAG_INFO[k].t).join(' · ')}`)}</title>`
    + `<path d="M0,-6.5L6.2,4.6H-6.2Z" fill="${K[lvl]}" stroke="${K.paper}" stroke-width="1.5" stroke-linejoin="round"/>`
    + `<text y="3.4" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="8" font-weight="700" fill="${K.bang[lvl]}">!</text></g>`;
}
// a stage's numbers on its card: from its curves, with the filing beside them
// where both exist; a stage with no curves, its filed numbers
function cardMetrics(s) {
  const r = s.m;
  if (!FVM || !r) return '';
  const f = (v, k) => esc(FVM.fmt(v, k)), out = [];
  const pair = (t, v) => { if (v != null) out.push(`<dt>${t}</dt><dd>${v}</dd>`); };
  const wide = (t, v) => { if (v != null) out.push(`<dt style="grid-column:1">${t}</dt><dd class="w">${v}</dd>`); };
  const filed = r.src === 'filed';
  if (filed) {
    pair('Avg pressure', r.fAvgP != null ? f(r.fAvgP, 'avgP') : null);
    pair('Peak', r.fMaxP != null ? f(r.fMaxP, 'maxP') : null);
    pair('Rate', r.fRate != null ? f(r.fRate, 'avgRate') : null);
    pair('Frac gradient', r.fg != null ? f(r.fg, 'fg') : null);
    wide('ISIP', r.fIsip != null ? f(r.fIsip, 'isip') : null);
    wide('Proppant', r.fProp != null ? f(r.fProp, 'prop') : null);
    wide('Clean fluid', r.fFluid != null ? f(r.fFluid, 'clean') : null);
  } else {
    pair('Pump time', r.pumpMin != null ? f(r.pumpMin, 'pumpMin') : null);
    pair('Avg pressure', r.avgP != null ? f(r.avgP, 'avgP') : null);
    pair('Frac gradient', r.fg != null ? f(r.fg, 'fg') : null);
    pair('Sand rate', r.tph != null ? f(r.tph, 'tph') : null);
    wide('ISIP', r.fIsip != null ? `${f(r.fIsip, 'isip')} filed${r.isip != null ? ` <span class="m">· ${f(r.isip, 'isip')} from the falloff</span>` : ''}`
      : r.isip != null ? `${f(r.isip, 'isip')} from the falloff` : null);
    wide('Proppant', r.prop != null ? `${f(r.prop, 'prop')} from the curves${r.fProp ? ` <span class="m">· ${f(r.fProp, 'prop')} filed (${fmt(100 * r.prop / r.fProp)}%)</span>` : ''}`
      : r.fProp != null ? `${f(r.fProp, 'prop')} filed` : null);
  }
  const fl = FVM.flags(r).map(k => { const i = FVM.FLAG_INFO[k]; return `<li class="${i.level}"><i aria-hidden="true">${i.level === 'info' ? '•' : '▲'}</i><span>${esc(i.t)}</span></li>`; });
  const src = filed ? 'As filed with the BCER; the Lab has no curves for it' : r.src && r.src !== '1 s' ? `From the curves as thinned (a point every ${esc(r.src)})` : '';
  if (!out.length && !fl.length) return src ? `<div class="src">${src}</div>` : '';
  return (src ? `<div class="src">${src}</div>` : '') + (out.length ? `<dl>${out.join('')}</dl>` : '') + (fl.length ? `<ul>${fl.join('')}</ul>` : '');
}

// ---------- drawing ----------
function empty(msg, title) {
  $('ws-svg').innerHTML = ''; $('ws-tip').hidden = true;
  $('ws-empty').hidden = false; $('ws-empty').textContent = msg;
  if (title) $('ws-name').textContent = title;
}

function render() {
  const box = $('ws-main'), Wd = box.clientWidth, Ht = box.clientHeight;
  if (!W || !Wd || !Ht) return;
  if (W.traj.length < 2) { empty('No directional survey on file for this well, so there is no path to draw.'); return; }
  $('ws-empty').hidden = true;
  const w = W.well, elev = w.elev_m != null && isFinite(w.elev_m) ? +w.elev_m : null;
  const lateralMode = mode === 'lateral' && W.heel != null;
  K = inks();
  const track = W.gamma && Ht >= 210 ? 50 : 0, gap = track ? 10 : 0;
  // each stage's pressure over its rate, along the top, where the lateral is
  const hasCurves = W.stages.some(s => s.series), strip = curvesOn && hasCurves && Ht >= 230 ? Math.round(Math.max(48, Math.min(86, Ht * 0.2))) : 0;
  const sy0 = 8, sy1 = sy0 + strip;
  // the stages coloured by one of their numbers: a ribbon under the curves strip, on the same axis
  const rib = metric && W.mrows && W.mrows.length && Ht >= 130 ? 12 : 0, ry0 = strip ? sy1 + 5 : 8, ry1 = ry0 + rib;
  const x0 = 58, x1 = Wd - (elev != null ? 62 : 18), y0 = rib ? ry1 + 22 : strip ? sy1 + 22 : 20, y1 = Ht - 24 - track - gap, ty0 = y1 + gap, ty1 = ty0 + track;
  const pts = W.traj;
  let vx0, vx1, dy0, dy1, kx, ky;
  if (!lateralMode) {
    // the whole well filling the frame, with room in pixels for the labels around it;
    // depth is stretched or squeezed to fit, and says so unless it is near true scale
    const a = Math.min(0, ...pts.map(p => p.vs)), b = Math.max(0, ...pts.map(p => p.vs)), dmax = Math.max(1, ...pts.map(p => p.tvd));
    const side = 30, top = 22, bottom = 30;
    kx = (x1 - x0 - 2 * side) / Math.max(1, b - a); ky = Math.max(0.005, (y1 - y0 - top - bottom) / dmax);
    if (ky / kx > 0.85 && ky / kx < 1.2) kx = ky = Math.min(kx, ky);     // close enough: draw it true
    const cx = (a + b) / 2;
    vx0 = cx - (x1 - x0) / kx / 2; vx1 = cx + (x1 - x0) / kx / 2;
    dy0 = -top / ky; dy1 = dy0 + (y1 - y0) / ky;
  } else {
    // the lateral filling the frame, depth stretched so its undulation shows
    const lat = pts.filter(p => p.md >= W.heel), a = at(W.heel), len = Math.max(200, pts[pts.length - 1].vs - a.vs);
    vx0 = a.vs - len * 0.08; vx1 = pts[pts.length - 1].vs + len * 0.04;
    const lo = Math.min(...lat.map(p => p.tvd), a.tvd), hi = Math.max(...lat.map(p => p.tvd), a.tvd), pad = Math.max(12, (hi - lo) * 0.45);
    dy0 = lo - pad; dy1 = hi + pad;
    kx = (x1 - x0) / (vx1 - vx0); ky = (y1 - y0) / (dy1 - dy0);
  }
  const X = v => x0 + (v - vx0) * kx, Y = d => y0 + (d - dy0) * ky, ve = ky / kx;
  const out = [];
  out.push(`<defs><clipPath id="clip"><rect x="${x0}" y="${y0}" width="${x1 - x0}" height="${y1 - y0}"/></clipPath>`
    + `<clipPath id="clipx"><rect x="${x0}" y="0" width="${x1 - x0}" height="${Ht}"/></clipPath></defs>`);

  // grid and axes
  const xs = niceStep(vx1 - vx0, (x1 - x0) / 110), ys = niceStep(dy1 - dy0, (y1 - y0) / 38);
  out.push('<g>');
  for (let v = Math.ceil(vx0 / xs) * xs; v <= vx1; v += xs) {
    const x = X(v).toFixed(1);
    out.push(`<line x1="${x}" x2="${x}" y1="${strip ? sy0 : rib ? ry0 : y0}" y2="${track ? ty1 : y1}" stroke="var(--grid)"/>`
      + `<text class="ax" x="${x}" y="${Ht - 8}" text-anchor="middle">${fmt(v)}</text>`);
  }
  for (let d = Math.ceil(dy0 / ys) * ys; d <= dy1; d += ys) {
    const y = Y(d).toFixed(1);
    out.push(`<line x1="${x0}" x2="${x1}" y1="${y}" y2="${y}" stroke="var(--grid)"/>`
      + `<text class="ax" x="${x0 - 7}" y="${+y + 4}" text-anchor="end">${fmt(d)}</text>`);
  }
  if (elev != null) for (let a = Math.ceil((elev - dy1) / ys) * ys; a <= elev - dy0; a += ys) {
    const y = Y(elev - a);
    out.push(`<line x1="${x1}" x2="${x1 + 4}" y1="${y}" y2="${y}" stroke="var(--line)"/><text class="ax" x="${x1 + 7}" y="${y + 4}">${fmt(a)}</text>`);
  }
  out.push(`<text class="ax-t" x="${x0 - 7}" y="${y0 - 7}" text-anchor="end">TVD m</text>`);
  if (elev != null) out.push(`<text class="ax-t" x="${x1 + 7}" y="${y0 - 7}">m ASL</text>`);
  out.push(`<rect x="${x0}" y="${y0}" width="${x1 - x0}" height="${y1 - y0}" fill="none" stroke="var(--line)"/></g>`);

  // which way the section looks, above the frame
  const azDeg = ((W.az * 180 / Math.PI) + 360) % 360;
  out.push(`<text class="chip" x="${x0 + 2}" y="${y0 - 7}">← ${compass(azDeg + 180)}</text>`
    + `<text class="chip" x="${x1 - 2}" y="${y0 - 7}" text-anchor="end">${compass(azDeg)} →</text>`);

  // surface and sea level
  out.push('<g clip-path="url(#clip)">');
  if (0 >= dy0 && 0 <= dy1) out.push(`<line x1="${x0}" x2="${x1}" y1="${Y(0)}" y2="${Y(0)}" stroke="${K.ground}" stroke-width="1.5"/>`
    + `<text class="lbl m" x="${x0 + 8}" y="${Y(0) - 6}">surface${elev != null ? ` · KB ${fmt(elev)} m ASL` : ''}</text>`);
  if (elev != null && elev >= dy0 && elev <= dy1) out.push(`<line x1="${x0}" x2="${x1}" y1="${Y(elev)}" y2="${Y(elev)}" stroke="${K.ground}" stroke-dasharray="5 5"/>`
    + `<text class="lbl m" x="${x1 - 8}" y="${Y(elev) - 6}" text-anchor="end">sea level</text>`);
  const stretch = Math.abs(ve - 1) < 0.02 ? 'true scale' : `depth ×${fmt(ve, ve < 10 ? 1 : 0)}`;
  out.push(`<text class="chip" x="${x1 - 8}" y="${y0 + 16}" text-anchor="end">${stretch}</text>`);

  // the path in screen space: hover samples, and the ground labels are kept clear of
  const step = Math.max(2, (W.td || pts[pts.length - 1].md) / 1500), samples = [];
  for (let m = pts[0].md; m <= pts[pts.length - 1].md; m += step) { const p = at(m); samples.push({ md: m, vs: p.vs, tvd: p.tvd, x: X(p.vs), y: Y(p.tvd) }); }
  // a label's baseline under the path across its width, or over it when there is no room below
  const clear = (xa, xb, yy) => {
    const ys_ = samples.filter(q => q.x >= xa - 4 && q.x <= xb + 4).map(q => q.y).concat(yy);
    const below = Math.max(...ys_) + 17;
    return below <= y1 - 4 ? below : Math.min(...ys_) - 9;
  };
  const tw = t => t.length * 6.6;

  // the wellbore: build in slate, lateral in ink (or gamma)
  const line = list => list.map(p => `${X(p.vs).toFixed(1)},${Y(p.tvd).toFixed(1)}`).join(' ');
  const heel = W.heel != null ? W.heel : pts[pts.length - 1].md;
  const build = pts.filter(p => p.md <= heel).concat([at(heel)]), lat = [at(heel)].concat(pts.filter(p => p.md > heel));
  out.push(`<polyline points="${line(pts)}" fill="none" stroke="${K.halo}" stroke-opacity="${K.haloOp}" stroke-width="7" stroke-linejoin="round" stroke-linecap="round"/>`);
  out.push(`<polyline points="${line(build)}" fill="none" stroke="${K.build}" stroke-width="2.2" stroke-linejoin="round"/>`);
  const g = W.gamma, gammaOn = colorBy === 'gamma' && g;
  out.push(`<polyline points="${line(lat)}" fill="none" stroke="${gammaOn ? K.filed : K.neutral}" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/>`);
  if (gammaOn) {
    const segs = [];
    g.v.forEach((v, i) => {
      if (v == null) return;
      const m0 = g.md0 + i * g.bin;
      if (m0 + g.bin < heel - 200) return;
      const a = at(m0), b = at(m0 + g.bin);
      segs.push(`<line x1="${X(a.vs).toFixed(1)}" y1="${Y(a.tvd).toFixed(1)}" x2="${X(b.vs).toFixed(1)}" y2="${Y(b.tvd).toFixed(1)}" stroke="${gammaInk(v, g)}"/>`);
    });
    out.push(`<g stroke-width="5"${g.estimated ? ' stroke-dasharray="7 4"' : ''}>${segs.join('')}</g>`);
  }

  // stage ticks across the path, at their measured depths
  const ticks = [], placed = [];
  const normal = md => {
    const a = at(md - 12), b = at(md + 12), dx = (X(b.vs) - X(a.vs)), dy = (Y(b.tvd) - Y(a.tvd)), l = Math.hypot(dx, dy) || 1;
    let nx = -dy / l, ny = dx / l; if (ny > 0) { nx = -nx; ny = -ny; }   // pointing up
    return [nx, ny];
  };
  for (const s of W.stages) {
    const p = at(s.mid), x = X(p.vs), y = Y(p.tvd), [nx, ny] = normal(s.mid), r = s.label === HI ? 9 : 6;
    s.px = x; s.py = y; s.nx = nx; s.ny = ny;
    ticks.push(`<line x1="${(x - nx * r).toFixed(1)}" y1="${(y - ny * r).toFixed(1)}" x2="${(x + nx * r).toFixed(1)}" y2="${(y + ny * r).toFixed(1)}" stroke="${s.curves ? K.curves : K.filed}" stroke-width="${s.label === HI ? 3 : 2}"/>`);
  }
  out.push(`<g stroke-linecap="round">${ticks.join('')}</g>`);
  // stage numbers where they have room (the first, the last and the picked one always)
  let lastX = -1e9;
  const keep = new Set();
  const inView = W.stages.filter(s => s.px >= x0 && s.px <= x1);
  inView.forEach((s, i) => { if (i === 0 || i === inView.length - 1 || Math.abs(s.px - lastX) >= 26) { keep.add(s); lastX = s.px; } });
  const hiS = W.stages.find(s => s.label === HI);
  if (hiS) { for (const s of [...keep]) if (s !== hiS && Math.abs(s.px - hiS.px) < 26) keep.delete(s); keep.add(hiS); }
  // straight above each tick, clear of the path on either side of it
  out.push('<g>' + [...keep].map(s => {
    const top = Math.min(s.py, ...samples.filter(q => Math.abs(q.x - s.px) <= 9 && Math.abs(q.md - s.mid) < 150).map(q => q.y));
    return `<text class="stn${s === hiS ? ' on' : ''}" x="${s.px.toFixed(1)}" y="${(top - 11).toFixed(1)}" text-anchor="middle">${esc(s.label)}</text>`;
  }).join('') + '</g>');

  // pad, heel and TD
  const td = pts[pts.length - 1], hp = at(heel);
  out.push(`<circle cx="${X(0)}" cy="${Y(0)}" r="5.5" fill="${K.pad}" stroke="${K.hole}" stroke-width="2"/>`);
  const boxes = [];                     // the labels' boxes, for the flag markers to keep off
  if (W.heel != null) {
    const t = `heel ${fmt(W.heel)} m MD`, hx = X(hp.vs), w_ = tw(t), xa = Math.max(x0 + 4, hx - w_ / 2), ly = clear(xa, xa + w_, Y(hp.tvd));
    out.push(`<circle cx="${hx}" cy="${Y(hp.tvd)}" r="4" fill="${K.hole}" stroke="${K.neutral}" stroke-width="2"/>`
      + `<text class="lbl m" x="${xa}" y="${ly}">${t}</text>`);
    boxes.push([xa, xa + w_, ly - 11, ly + 3]);
  }
  const tdx = X(td.vs), tdt = `TD ${fmt(td.md)} m MD · ${fmt(td.tvd)} m TVD`, tdw = tw(tdt);
  const tdxa = Math.max(x0 + 4, Math.min(tdx - tdw / 2, x1 - 6 - tdw)), tdy = clear(tdxa, tdxa + tdw, Y(td.tvd));     // centred under TD, inside the frame
  out.push(`<circle cx="${tdx}" cy="${Y(td.tvd)}" r="4.5" fill="${K.neutral}" stroke="${K.hole}" stroke-width="2"/>`
    + `<text class="lbl" x="${tdxa}" y="${tdy}">${tdt}</text>`);
  boxes.push([tdxa, tdxa + tdw, tdy - 11, tdy + 3]);

  // stages with an operational flag: a marker under the hole, its level in its
  // colour and named in its tooltip (and on the stage's card); one that would sit
  // on the heel or TD label goes under the label instead
  if (rib) {
    const place = (x, y) => { const b = boxes.find(q => x + 7 > q[0] && x - 7 < q[1] && y + 5 > q[2] && y - 7 < q[3]); return b ? [x, b[3] + 8] : [x, y]; };
    const marks = W.stages.filter(s => s.m && FVM.opFlags(s.m).length)
      .map(s => flagMark(...place(s.px - s.nx * 15, s.py - s.ny * 15), s.m, s.label));
    for (const r of W.loose || []) {
      const md = (r.top + (r.base != null ? r.base : r.top)) / 2, p = at(md), [nx, ny] = normal(md);
      marks.push(flagMark(...place(X(p.vs) - nx * 15, Y(p.tvd) - ny * 15), r, r.label));
    }
    out.push(`<g>${marks.join('')}</g>`);
  }
  out.push('</g>');

  // gamma under the section, on the same along-section axis
  if (track) {
    out.push(`<rect x="${x0}" y="${ty0}" width="${x1 - x0}" height="${track}" fill="${K.track}" stroke="var(--line)"/>`);
    for (const a of [100, 200]) {
      const y = ty1 - a / GR_MAX * track;
      out.push(`<line x1="${x0}" x2="${x1}" y1="${y}" y2="${y}" stroke="var(--grid)" stroke-dasharray="3 4"/><text class="ax" x="${x0 - 7}" y="${y + 4}" text-anchor="end">${a}</text>`);
    }
    const bars = [];
    g.v.forEach((v, i) => {
      if (v == null) return;
      const m0 = g.md0 + i * g.bin, a = at(m0), b = at(m0 + g.bin);
      if (Math.abs(b.vs - a.vs) < g.bin * 0.5) return;          // steep hole: no room on this axis
      const xa = X(Math.min(a.vs, b.vs)), xb = X(Math.max(a.vs, b.vs));
      if (xb < x0 || xa > x1) return;
      const h = Math.max(1, Math.min(1, v / GR_MAX) * track);
      bars.push(`<rect x="${xa.toFixed(1)}" y="${(ty1 - h).toFixed(1)}" width="${Math.max(1, xb - xa + .4).toFixed(1)}" height="${h.toFixed(1)}" fill="${gammaInk(v, g)}"/>`);
    });
    out.push(`<g clip-path="url(#clipx)"${g.estimated ? ' opacity=".75"' : ''}>${bars.join('')}</g>`);
    out.push(`<text class="chip" x="${x1 - 8}" y="${ty0 + 14}" text-anchor="end">gamma API${g.estimated ? ` · estimated from ${g.from && g.from.length ? g.from.length + ' offset log' + (g.from.length > 1 ? 's' : '') : 'offset logs'} (±15 API)` : ''}</text>`);
  }
  let scale = null;
  if (strip) {
    // pressure in the top 60%, rate under it; a stage spans its own stretch of hole
    scale = W.cvScale || (W.cvScale = curveScale());
    const pm = sy0 + Math.round(strip * 0.6), u = W.units || {}, unit = k => esc(String(u[k] || '').replace(/m3/g, 'm³'));
    const rows = [{ k: 'press', top: sy0 + 3, bot: pm - 3, max: scale.press, ink: K.press, name: 'Press' },
                  { k: 'rate', top: pm + 3, bot: sy1 - 3, max: scale.rate, ink: K.rate, name: 'Rate' }];
    out.push(`<rect class="cv-bg" x="${x0}" y="${sy0}" width="${x1 - x0}" height="${strip}"/>`
      + `<line class="cv-sep" x1="${x0}" x2="${x1}" y1="${pm}" y2="${pm}"/>`);
    for (const r of rows) out.push(`<text class="cv-k" x="${x0 - 7}" y="${(r.top + r.bot) / 2 + 2}" text-anchor="end" fill="${r.ink}">${r.name}<title>${r.name === 'Press' ? 'Treating pressure' : 'Slurry rate'}, 0–${fmt(r.max)} ${unit(r.k)} on every stage</title></text>`
      + `<text class="cv-n" x="${x0 - 7}" y="${(r.top + r.bot) / 2 + 13}" text-anchor="end">${fmt(r.max)}</text>`);
    const paths = { press: [], rate: [] };
    for (const s of W.stages) {
      s.sx0 = s.sx1 = null;
      if (!s.series) continue;
      let xa = X(at(s.z0).vs), xb = X(at(s.z1).vs);
      if (xb < xa) [xa, xb] = [xb, xa];
      if (xb < x0 || xa > x1) continue;
      s.sx0 = xa; s.sx1 = xb;
      const inset = xb - xa > 8 ? 1.5 : 0, a = xa + inset, wpx = Math.max(1, xb - xa - 2 * inset);
      for (const r of rows) {
        const v = s.series[r.k];
        if (!Array.isArray(v) || !v.length) continue;
        const n = Math.max(2, Math.round(wpx * 1.5)), pts_ = spark(v, n);
        let d = '', pen = false;
        for (const q of pts_) {
          if (!q) { pen = false; continue; }
          const px = a + (n > 1 ? q[0] / (n - 1) : 0.5) * wpx, py = r.bot - Math.max(0, Math.min(1, q[1] / r.max)) * (r.bot - r.top);
          d += (pen ? 'L' : 'M') + px.toFixed(1) + ' ' + py.toFixed(1); pen = true;
        }
        if (d) paths[r.k].push(d);
      }
    }
    out.push(`<g clip-path="url(#clipx)" fill="none" stroke-width="1.2" stroke-linejoin="round">`
      + `<path d="${paths.press.join('')}" stroke="${K.press}"/><path d="${paths.rate.join('')}" stroke="${K.rate}"/></g>`);
  }
  if (rib) {
    // each stage's own stretch of hole, in its colour; no number, the neutral grey
    const m = FVM.BY[metric], cells = [], dom = FVM.domain(W.mrows.map(r => FVM.value(r, metric)), metric);
    for (const s of W.stages) {
      let xa = X(at(s.z0).vs), xb = X(at(s.z1).vs);
      if (xb < xa) [xa, xb] = [xb, xa];
      s.rx0 = s.rx1 = null;
      if (xb < x0 || xa > x1) continue;
      s.rx0 = xa; s.rx1 = xb;
      const g_ = xb - xa > 5 ? .5 : 0;            // a hairline of plot between neighbours
      cells.push(`<rect x="${(xa + g_).toFixed(1)}" y="${ry0}" width="${Math.max(.8, xb - xa - 2 * g_).toFixed(1)}" height="${rib}" fill="${FVM.colour(s.m ? FVM.value(s.m, metric) : null, dom, metric)}"/>`);
    }
    out.push(`<rect class="cv-bg" x="${x0}" y="${ry0 - .5}" width="${x1 - x0}" height="${rib + 1}"/><g clip-path="url(#clipx)">${cells.join('')}</g>`
      + `<text class="rb-k" x="${x0 - 7}" y="${ry0 + rib - 2}" text-anchor="end">${esc(SHORT[metric] || m.t.slice(0, 7))}<title>Stages coloured by ${esc(m.t.toLowerCase())}</title></text>`);
    out.push(ribbonKey(m, dom, x0, x1, y0 - 7, compass(((W.az * 180 / Math.PI) + 360) % 360)));
  }
  out.push('<g id="ws-hl"></g>');
  $('ws-svg').innerHTML = out.join('');
  $('ws-svg').setAttribute('viewBox', `0 0 ${Wd} ${Ht}`);

  G = { x0, x1, y0, y1, ty0, ty1, track, X, Y, samples, heel, elev, strip, sy0, sy1, rib, ry0, ry1 };
  if (!pointerIn) hover = extHover();
  $('ws-foot').textContent = `Vertical section along ${fmt(azDeg)}° (${compass(azDeg)}), from the pad's surface location`
    + ` · ${lateralMode ? 'lateral' : 'whole well'}, ${stretch}`
    + ` · ${W.stages.length ? 'teal ticks have treatment curves, slate are filed only · ' : ''}`
    + (scale ? `above: each stage's pressure (0–${fmt(scale.press)} ${String((W.units || {}).press || '').replace(/m3/g, 'm³')}) and rate (0–${fmt(scale.rate)} ${String((W.units || {}).rate || '').replace(/m3/g, 'm³')}), one scale for all · ` : '')
    + (rib ? `stages coloured by ${FVM.BY[metric].t.toLowerCase()}${FVM.BY[metric].filed ? ' (as filed where the curves give none)' : FVM.BY[metric].prefer ? ' (as filed where there is one, else from the curves)' : ''}, grey where there is no number · ▲ a flagged stage · ` : '')
    + 'hover for depths · click a stage for its charts';
  const cb = $('ws-curves');
  if (cb) { cb.disabled = !hasCurves; cb.setAttribute('aria-pressed', String(curvesOn && hasCurves)); cb.title = hasCurves ? 'Each stage\'s pressure and rate, above the well' : 'The Lab has not read this well\'s treatment curves yet'; }
  drawHover();
}

// the hover layer: picked-out stage band, crosshair and readout
function band(s, color, opacity, width) {
  const ms = [];
  for (let m = s.z0; m <= s.z1; m += Math.max(2, (s.z1 - s.z0) / 24)) ms.push(at(m));
  ms.push(at(s.z1));
  return `<polyline points="${ms.map(p => `${G.X(p.vs).toFixed(1)},${G.Y(p.tvd).toFixed(1)}`).join(' ')}" fill="none" stroke="${color}" stroke-opacity="${opacity}" stroke-width="${width}" stroke-linecap="butt"/>`;
}
function drawHover() {
  const hl = document.getElementById('ws-hl');
  if (!hl || !G) return;
  const out = [];
  const hiS = W.stages.find(s => s.label === HI);
  // a stage's stretch of the curves strip, picked out
  const lit = (s, op) => { if (G.strip && s && s.sx0 != null) out.push(`<rect x="${s.sx0.toFixed(1)}" y="${G.sy0}" width="${Math.max(1, s.sx1 - s.sx0).toFixed(1)}" height="${G.sy1 - G.sy0}" fill="${K.curves}" fill-opacity="${op}" stroke="${K.curves}" stroke-opacity="${op * 3}"/>`); };
  if (hiS) { out.push(band(hiS, K.curves, .28, 16)); lit(hiS, .14); }
  const tip = $('ws-tip');
  if (hover && hover.rib) {
    // over the ribbon: the stage's band below, its cell outlined, and its card with the number
    const s = hover.rib;
    if (s !== hiS) { out.push(band(s, s.curves ? K.curves : K.filed, .2, 16)); lit(s, .1); }
    out.push(`<rect x="${s.rx0.toFixed(1)}" y="${G.ry0 - 1}" width="${Math.max(1, s.rx1 - s.rx0).toFixed(1)}" height="${G.ry1 - G.ry0 + 2}" fill="none" stroke="${K.cross}" stroke-width="1.5"/>`);
    tip.hidden = true;
    const m = FVM.BY[metric], v = s.m ? FVM.value(s.m, metric) : null;
    showCard(s, [`${esc(m.t)}: <b>${esc(FVM.fmt(v, metric))}</b>${v == null ? ' <span class="m">(no number for this stage)</span>' : ''}`],
      { x: (s.rx0 + s.rx1) / 2, y: G.ry1 });
  } else if (hover && hover.strip) {
    // over the curves strip: the stage's band below, a cursor through its curves, and its chart
    const s = hover.strip;
    if (s !== hiS) { out.push(band(s, K.curves, .2, 16)); lit(s, .1); }
    out.push(`<line x1="${hover.x}" x2="${hover.x}" y1="${G.sy0}" y2="${G.sy1}" stroke="${K.cross}" stroke-opacity=".45"/>`);
    tip.hidden = true;
    const n = curveMinutes(s), t = Math.max(0, Math.min(1, hover.frac)) * n, val = k => {
      const v = s.series[k]; if (!Array.isArray(v) || !v.length) return null;
      const x = v[Math.round(Math.max(0, Math.min(1, hover.frac)) * (v.length - 1))]; return x == null || !isFinite(x) ? null : x;
    }, u = W.units || {}, un = k => String(u[k] || '').replace(/m3/g, 'm³'), p = val('press'), r = val('rate');
    showCard(s, [`${fmt(t)} min in: ${[p != null && `${fmt(p, 1)} ${un('press')}`, r != null && `${fmt(r, 2)} ${un('rate')}`].filter(Boolean).join(' · ') || 'no reading'}`],
      { x: (s.sx0 + s.sx1) / 2, y: G.sy0 });
  } else if (hover) {
    const s = hover.md >= (G.heel - 1) ? stageAt(hover.md) : null;
    if (s && s !== hiS) { out.push(band(s, s.curves ? K.curves : K.filed, .2, 16)); lit(s, .1); }
    if (G.track && hover.md >= G.heel - 200) out.push(`<line x1="${hover.x}" x2="${hover.x}" y1="${G.y0}" y2="${G.ty1}" stroke="${K.cross}" stroke-opacity=".35"/>`);
    out.push(`<circle cx="${hover.x}" cy="${hover.y}" r="5" fill="none" stroke="${K.cross}" stroke-width="2"/>`);
    const gr = gammaAt(hover.md);
    const lines = [`<b>MD ${fmt(hover.md)} m</b> · TVD ${fmt(hover.tvd)} m`,
      `<span class="m">${fmt(hover.vs)} m along the section${G.elev != null ? ` · ${fmt(G.elev - hover.tvd)} m ASL` : ''}</span>`];
    if (gr != null) lines.push(`Gamma ${fmt(gr)} API${W.gamma.estimated ? ' <span class="m">(estimated)</span>' : ''}`);
    if (s) {
      lines.push(`<b>Stage ${esc(s.label)}</b> · ${fmt(s.top, 1)}${s.base !== s.top ? '–' + fmt(s.base, 1) : ''} m MD`);
      const bits = [s.date && `${s.date}${s.start ? ' ' + s.start : ''}`, s.proppant != null && `${fmt(s.proppant, 1)} t`,
        s.fluid != null && `${fmt(s.fluid)} m³`, s.rate != null && `${fmt(s.rate, 1)} m³/min`, s.pmax != null && `max ${fmt(s.pmax, 1)} MPa`].filter(Boolean);
      if (bits.length) lines.push(`<span class="m">${bits.join(' · ')}</span>`);
      lines.push(s.curves ? 'Click to open its chart in a window' : '<span class="m">Filed with the BCER; no curves yet</span>');
    }
    if (s) { tip.hidden = true; showCard(s, [(hover.ext ? 'Wine rack line · ' : '') + `MD ${fmt(hover.md)} m · TVD ${fmt(hover.tvd)} m${gr != null ? ` · GR ${fmt(gr)} API` : ''}`]); }
    else {
    hideCard();
    tip.innerHTML = (hover.ext ? '<span class="m">Wine rack line</span><br>' : '') + lines.join('<br>');
    tip.hidden = false;
    const box = $('ws-main'), tw = tip.offsetWidth, th = tip.offsetHeight;
    let tx = hover.x + 16, ty = hover.y - th - 12;
    if (tx + tw > box.clientWidth - 6) tx = hover.x - tw - 16;
    if (ty < 6) ty = hover.y + 16;
    if (ty + th > box.clientHeight - 6) ty = box.clientHeight - th - 6;
    tip.style.left = Math.max(6, tx) + 'px'; tip.style.top = ty + 'px';
    }
  } else {
    tip.hidden = true;
    // stepping through stages from the keyboard shows each one's card too
    if (hiS && document.activeElement === $('ws-svg')) showCard(hiS, null); else hideCard();
  }
  hl.innerHTML = out.join('');
  $('ws-svg').style.cursor = hover && (hover.strip || hover.rib || (hover.md >= G.heel - 1 && stageAt(hover.md))) ? 'pointer' : 'crosshair';
}

// ---------- a stage's chart, above it ----------
// The stage chart in miniature: the Lab's curves, named and coloured as on the
// well's charts page (wellview.js SERIES), each on its own scale rounded up to a
// readable top, and the curves hidden there hidden here too.
const LAB_CURVES = [
  { k: 'press', name: 'Tr Press', short: 'Press', color: '#f0555a', light: '#a31631' },
  { k: 'rate', name: 'Slurry Rate', short: 'Rate', color: '#4f8ff7', light: '#1f6feb' },
  { k: 'wh_conc', name: 'WH Prop Conc', short: 'WH conc', color: '#3fb950', light: '#1e7a34' },
  { k: 'bh_conc', name: 'BH Prop Conc', short: 'BH conc', color: '#b87fd9', light: '#7a4fd6' },
  { k: 'bh_press', name: 'BH Press', short: 'BH press', color: '#39c5cf', light: '#0b7f8a' },
];
const curveInk = c => document.documentElement.dataset.theme === 'dark' ? c.color : c.light;
const NICE_STEPS = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
function niceCeil(v) {
  if (!(v > 0)) return 1;
  const e = Math.pow(10, Math.floor(Math.log10(v))), m = v / e;
  for (const s of NICE_STEPS) if (m <= s + 1e-9) return s * e;
  return 10 * e;
}
function hiddenCurves() { try { return new Set(JSON.parse(localStorage.getItem('stratum.hiddenCurves') || '[]')); } catch (e) { return new Set(); } }

let cardFor = null;
// anchored on the stage's tick on the well, or on a point given (its curves along the top)
function showCard(s, readout, anchor) {
  const card = $('ws-card'), r = $('ws-svg').getBoundingClientRect();
  const ax = r.left + (anchor ? anchor.x : s.px), ay = r.top + (anchor ? anchor.y : s.py);
  if (cardFor !== s) {
    cardFor = s;
    const bits = [s.date && `${s.date}${s.start ? ' ' + s.start : ''}`, s.series && s.step && `${fmt(curveMinutes(s))} min`].filter(Boolean);
    card.querySelector('.ws-card-h').innerHTML = `<b>Stage ${esc(s.label)}</b><span>${fmt(s.top, 1)}${s.base !== s.top ? '–' + fmt(s.base, 1) : ''} m MD</span>`;
    card.querySelector('.ws-card-d').textContent = bits.join(' · ');
    const pumped = [s.proppant != null && `${fmt(s.proppant, 1)} t`, s.fluid != null && `${fmt(s.fluid)} m³`,
      s.rate != null && `${fmt(s.rate, 1)} m³/min avg`, s.pmax != null && `max ${fmt(s.pmax, 1)} MPa`].filter(Boolean);
    const mb = cardMetrics(s);
    card.querySelector('.ws-card-m').innerHTML = mb;
    card.querySelector('.ws-card-p').textContent = mb ? '' : pumped.join(' · ');
  }
  card.querySelector('.ws-card-r').innerHTML = (readout || []).join('<br>');
  card.querySelector('.ws-card-f').textContent = s.curves ? 'Click to open this stage’s chart in a window' : 'Filed with the BCER; the Lab has not read its curves yet';
  const cv = card.querySelector('canvas'), legend = card.querySelector('.ws-card-l');
  cv.hidden = legend.hidden = !s.series;
  card.classList.remove('below', 'side-r', 'side-l');
  card.hidden = false;
  // above the stage when the chart fits there, else below, else beside it (a short dock)
  const rest = card.offsetHeight - (s.series ? cv.offsetHeight : 0);
  const roomAbove = ay - 30 - rest - 4, roomBelow = innerHeight - ay - 24 - rest - 4, need = s.series ? 70 : 0;
  const place = roomAbove >= need ? 'above' : roomBelow >= need ? 'below' : 'side';
  if (s.series) {
    const room = place === 'above' ? roomAbove : place === 'below' ? roomBelow : innerHeight - 8 - rest;
    cv.style.height = Math.round(Math.max(40, Math.min(110, room))) + 'px';
    drawThumb(cv, legend, s);
  }
  const cw = card.offsetWidth, ch = card.offsetHeight;
  let left, top;
  if (place === 'side') {
    const right = ax + 22 + cw <= innerWidth - 6;
    left = right ? ax + 22 : ax - 22 - cw;
    top = Math.max(4, Math.min(innerHeight - ch - 4, ay - ch / 2));
    card.classList.add(right ? 'side-r' : 'side-l');
    card.style.setProperty('--tipy', Math.max(12, Math.min(ch - 12, ay - top)) + 'px');
  } else {
    left = Math.max(6, Math.min(innerWidth - cw - 6, ax - cw / 2));
    top = place === 'above' ? ay - 26 - ch : ay + 20;
    if (place === 'below') card.classList.add('below');
    card.style.setProperty('--tip', Math.max(14, Math.min(cw - 14, ax - left)) + 'px');
  }
  card.style.left = left + 'px'; card.style.top = top + 'px';
}
function hideCard() { $('ws-card').hidden = true; cardFor = null; }
const curveMinutes = s => {
  const n = Math.max(0, ...LAB_CURVES.map(c => Array.isArray(s.series[c.k]) ? s.series[c.k].length : 0));
  return Math.max(1, n - 1) * s.step / 60;
};
function drawThumb(cv, legend, s) {
  const dpr = devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
  cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
  const pad = 4, H = h - pad * 2;
  g.strokeStyle = K.grid; g.lineWidth = 1;
  for (const f of [0.25, 0.5, 0.75]) { const y = Math.round(pad + H * f) + 0.5; g.beginPath(); g.moveTo(0, y); g.lineTo(w, y); g.stroke(); }
  const off = hiddenCurves(), shown = [];
  for (const c of LAB_CURVES) {
    const v = s.series[c.k];
    if (!Array.isArray(v) || !v.some(x => x != null && isFinite(x))) continue;
    const vals = v.filter(x => x != null && isFinite(x)), max = Math.max(...vals), top = niceCeil(max);
    shown.push({ ...c, max, hidden: off.has(c.name) });
    if (off.has(c.name)) continue;
    g.strokeStyle = curveInk(c); g.lineWidth = 1.5; g.lineJoin = 'round'; g.beginPath();
    let pen = false;
    v.forEach((x, i) => {
      if (x == null || !isFinite(x)) { pen = false; return; }
      const px = v.length > 1 ? i / (v.length - 1) * w : w / 2, py = pad + H - Math.max(0, Math.min(1, x / top)) * H;
      if (pen) g.lineTo(px, py); else { g.moveTo(px, py); pen = true; }
    });
    g.stroke();
  }
  const u = W.units || {};
  const unit = k => esc(String(u[k] || '').replace(/m3/g, 'm³'));
  legend.innerHTML = (shown.length ? '<span class="m">peak</span>' : '')
    + shown.map(c => `<span${c.hidden ? ' class="off" title="Hidden on the stage chart"' : ''}><i style="background:${curveInk(c)}"></i>${c.short} ${fmt(c.max, c.max < 100 ? 1 : 0)} ${unit(c.k)}</span>`).join('');
}

const svg = $('ws-svg');
svg.setAttribute('tabindex', '0');
svg.addEventListener('pointermove', e => {
  if (!G) return;
  const r = svg.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
  let best = null, bd = Infinity;
  if (G.rib && my >= G.ry0 - 3 && my <= G.ry1 + 4) {
    // the ribbon: the stage whose stretch is under the pointer
    const s = W.stages.find(q => q.rx0 != null && mx >= q.rx0 && mx <= q.rx1);
    best = s ? { rib: s, md: s.mid, x: mx } : null;
    if (best ? !hover || hover.rib !== s : hover) { hover = best; drawHover(); }
    return;
  }
  if (G.strip && my <= G.sy1 + (G.rib ? 2 : 6)) {
    // the curves strip: the stage under the pointer, and how far through it
    const s = W.stages.find(q => q.sx0 != null && mx >= q.sx0 && mx <= q.sx1);
    best = s ? { strip: s, md: s.mid, x: mx, frac: (mx - s.sx0) / Math.max(1, s.sx1 - s.sx0) } : null;
    if (best || hover) { hover = best; drawHover(); }
    return;
  }
  if (G.track && my >= G.ty0 - 4) {
    for (const s of G.samples) { if (s.md < G.heel - 200) continue; const d = Math.abs(s.x - mx); if (d < bd) { bd = d; best = s; } }
    if (bd > 30) best = null;
  } else {
    for (const s of G.samples) { const d = Math.hypot(s.x - mx, s.y - my); if (d < bd) { bd = d; best = s; } }
    if (bd > 34) best = null;
  }
  if (best !== hover) { hover = best; drawHover(); }
});
svg.addEventListener('pointerenter', () => { pointerIn = true; });
svg.addEventListener('pointerleave', () => { pointerIn = false; hover = extHover(); drawHover(); });
svg.addEventListener('blur', () => { if (!hover) hideCard(); });
svg.addEventListener('click', () => {
  const picked = hover && (hover.strip || hover.rib);
  if (picked) { HI = picked.label; syncUrl(); render(); openStage(picked); return; }
  if (!hover || hover.md < G.heel - 1) return;
  const s = stageAt(hover.md);
  if (s) { HI = s.label; syncUrl(); render(); openStage(s); }
});
svg.addEventListener('keydown', e => {
  if (!W || !W.stages.length) return;
  const i = W.stages.findIndex(s => s.label === HI);
  if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
    e.preventDefault();
    const j = i < 0 ? 0 : Math.max(0, Math.min(W.stages.length - 1, i + (e.key === 'ArrowRight' ? 1 : -1)));
    hover = null;                       // the keys take over from the pointer
    HI = W.stages[j].label; syncUrl(); render();
  } else if (e.key === 'Enter' && i >= 0) openStage(W.stages[i]);
});
new ResizeObserver(() => render()).observe($('ws-main'));
addEventListener('stratum:gammapalette', () => { setPressed(); render(); });
addEventListener('stratum:theme', () => { cardFor = null; render(); });

// ---------- header and controls ----------
function header() {
  const w = W.well;
  $('ws-name').textContent = w.name || `WA ${WA}`;
  document.title = `FracView — ${w.name || 'WA ' + WA} · section`;
  const n = W.stages.length;
  $('ws-sub').textContent = [`WA ${WA}`, w.uwi, w.operator, w.formation, W.td ? `TD ${fmt(W.td)} m MD` : null,
    w.tvd_m ? `${fmt(w.tvd_m)} m TVD` : null, w.lateral_m ? `lateral ${fmt(w.lateral_m)} m` : null,
    n ? `${n} stages${W.nCurves ? `, ${W.nCurves} with curves` : ''}` : null].filter(Boolean).join(' · ');
  $('ws-sub').title = $('ws-sub').textContent;
  const gb = document.querySelector('[data-color=gamma]');
  gb.disabled = !W.gamma;
  gb.title = W.gamma ? (W.gamma.estimated ? 'Gamma estimated from offset logs' : 'Gamma from this well’s LAS log') : 'No gamma log on file for this well';
  document.querySelector('[data-mode=lateral]').disabled = W.heel == null;
  const ms = $('ws-metric');
  if (FVM) {
    const has = !!(W.mrows && W.mrows.length);
    ms.disabled = !has; ms.value = metric; ms.classList.toggle('on', !!metric && has);
    ms.title = has ? 'Colour each stage by a number from its treatment curves (or its filing)'
      : W.mrows ? 'No stage numbers for this well yet' : 'Loading the stages\' numbers…';
  }
  setPressed();
}
function setPressed() {
  document.querySelectorAll('[data-mode]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.mode === mode)));
  document.querySelectorAll('[data-color]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.color === colorBy)));
  const pal = $('ws-palette');
  if (pal) { pal.hidden = !(colorBy === 'gamma' && W && W.gamma); pal.value = window.StratumGamma.current(); }
}
{
  const pal = $('ws-palette');
  for (const [id, p] of Object.entries(window.StratumGamma.PALETTES)) { const o = document.createElement('option'); o.value = id; o.textContent = p.name; pal.append(o); }
  pal.onchange = () => window.StratumGamma.set(pal.value);
}
const savePrefs = () => { try { localStorage.setItem(PREF_KEY, JSON.stringify({ mode, color: colorBy, curves: curvesOn })); } catch (e) { /* private mode */ } };
if (FVM) {
  const ms = $('ws-metric');
  ms.append(new Option('Stage colour: none', ''));
  for (const m of FVM.METRICS) ms.append(new Option(m.t, m.k));
  ms.value = metric; ms.hidden = false; ms.disabled = true;
  ms.onchange = () => {
    metric = FVM.BY[ms.value] ? ms.value : '';
    try { if (metric) localStorage.setItem(METRIC_KEY, metric); else localStorage.removeItem(METRIC_KEY); } catch (e) { /* private mode */ }
    hover = null; cardFor = null; header(); render();
  };
  // chosen in another window (a docked section and a popped-out one, a session opened)
  addEventListener('storage', e => { if (e.key === METRIC_KEY && readMetric() !== metric) { metric = readMetric(); cardFor = null; if (W) { header(); render(); } } });
}
$('ws-report').onclick = () => {
  if (!WA) return;
  const url = `report.html?wa=${encodeURIComponent(WA)}`, w = window.open(url, 'stratum-report');
  if (w) { try { w.focus(); } catch (e) { /* the browser decides */ } }
  else note(`Your browser blocked the report window. <a href="${url}" target="_blank" rel="noopener">Open the stage report</a>`);
};
$('ws-png').onclick = () => savePng().catch(() => note('The picture could not be made in this browser.'));
$('ws-curves').onclick = () => { curvesOn = !curvesOn; savePrefs(); hover = null; render(); };
document.querySelectorAll('[data-mode]').forEach(b => b.onclick = () => { mode = b.dataset.mode; savePrefs(); setPressed(); render(); });
document.querySelectorAll('[data-color]').forEach(b => b.onclick = () => { colorBy = b.dataset.color; savePrefs(); setPressed(); render(); });

function syncUrl() {
  const q = new URLSearchParams(location.search);
  q.set('wa', WA); if (HI) q.set('stage', HI); else q.delete('stage');
  if (EXT && EXT.wa === WA) q.set('at', Math.round(EXT.md)); else q.delete('at');
  history.replaceState(null, '', '?' + q);
}

// The main window is whichever page last sent a well here: the map that docked or
// popped this section out, or a well's charts. A popped-out section talks to it
// over the channel only, so it never depends on the window that opened it (a
// dock's frame, gone once the dock closes). Messages to the main window carry its
// id and are answered, so a closed one is noticed.
const chan = 'BroadcastChannel' in self ? new BroadcastChannel('stratum-section') : null;
let owner = Q.get('owner'), ownerPage = Q.get('page');
const pending = new Map();
function ask(msg) {
  if (!chan || !owner) return Promise.resolve(false);
  const id = Math.random().toString(36).slice(2);
  chan.postMessage({ ...msg, to: owner, id });
  return new Promise(res => { pending.set(id, res); setTimeout(() => { if (pending.delete(id)) res(false); }, 700); });
}
let noteTimer = 0;
function note(html) {
  const n = $('ws-note'); n.innerHTML = html; n.hidden = false;
  clearTimeout(noteTimer); noteTimer = setTimeout(() => { n.hidden = true; }, 9000);
}
const chartsUrl = label => `wellview.html?wa=${encodeURIComponent(WA)}${label ? '&stage=' + encodeURIComponent(label) : ''}`;
// A stage's charts open in a window of their own, so the map or 3D view this
// section sits under stays where it is. One window, reused: a stage of the well
// it already shows is picked there without reloading it.
let chartsWin = null;
function chartsWindow(label) {
  const url = chartsUrl(label);
  try {
    if (chartsWin && !chartsWin.closed && /\/wellview(\.html)?$/.test(chartsWin.location.pathname)
        && new URLSearchParams(chartsWin.location.search).get('wa') === WA) {
      if (label) chartsWin.postMessage({ type: 'ws:select-stage', wa: WA, label }, ORIGIN);
      chartsWin.focus();
      return;
    }
  } catch (e) { /* a window this page no longer reaches: open afresh */ }
  chartsWin = window.open(url, 'stratum-charts', 'popup,width=1280,height=860');
  if (chartsWin) { try { chartsWin.focus(); } catch (e) { /* the browser decides */ } }
  else note(`Your browser blocked the charts window. <a href="${url}" target="_blank" rel="noopener">Open the charts</a>`);
}
function openStage(s) {
  const label = s && s.curves ? s.label : null;
  // popped out beside a well's charts page: the stage is picked on that page instead
  if (!EMBED && owner && ownerPage === 'charts') {
    ask({ type: 'open-stage', wa: WA, label }).then(ok => {
      if (!ok) { ownerPage = null; note(`That charts page has closed. <a href="${chartsUrl(label)}" target="_blank" rel="noopener">Open the charts</a>`); }
    });
    return;
  }
  if (!label) { note(`Stage ${esc(s ? s.label : '')} was filed with the BCER; the Lab has not read its curves yet.`); return; }
  stageWindow(s);
}

// ---------- a stage's chart in a window of its own (stages.html) ----------
// The first stage opens a window. With one open already, a small dialog asks:
// stack it under the charts there, or give it a window of its own. The stage
// windows say what they hold over 'stratum-stages'; this page keeps the list.
const stChan = 'BroadcastChannel' in self ? new BroadcastChannel('stratum-stages') : null;
const stageWins = new Map();          // id -> {id, name, at, stages}
const stAcks = new Map();             // a stage sent over the channel, until its window says it has it
if (stChan) {
  stChan.onmessage = e => {
    const m = e.data || {};
    if (m.type === 'here' && m.id) stageWins.set(m.id, m);
    else if (m.type === 'bye') stageWins.delete(m.id);
    else if (m.type === 'added' && stAcks.has(m.rid)) { clearTimeout(stAcks.get(m.rid)); stAcks.delete(m.rid); }
  };
  stChan.postMessage({ type: 'ping' });
  addEventListener('focus', () => stChan.postMessage({ type: 'ping' }));
}
const openWins = () => [...stageWins.values()].sort((a, b) => (b.at || 0) - (a.at || 0));
const stageUrl = (wa, label) => `stages.html?s=${encodeURIComponent(wa)}:${encodeURIComponent(label)}`;
const letters = () => Array.from({ length: 6 }, () => String.fromCharCode(97 + Math.floor(Math.random() * 26))).join('');
function newStageWindow(wa, label) {
  const w = window.open(stageUrl(wa, label), 'stratum-stages' + letters(), 'popup,width=1180,height=820');
  if (w) { try { w.focus(); } catch (e) { /* the browser decides */ } }
  else note(`Your browser blocked the stage window. <a href="${stageUrl(wa, label)}" target="_blank" rel="noopener">Open stage ${esc(label)}</a>`);
}
// into an open stage window: found by its name, so it can be brought forward; told over the channel otherwise
function stackStage(win, wa, label) {
  let w = null;
  try { w = window.open('', win.name); } catch (e) { /* blocked */ }
  try {
    if (w && w.stratumStages) { w.stratumStages.add(wa, label); w.focus(); return; }
    if (w && /\/stages(\.html)?$/.test(w.location.pathname)) { (w.stratumStageQueue = w.stratumStageQueue || []).push({ wa, label }); w.focus(); return; }
    if (w) w.close();               // not reachable by name from here: a blank window was made for it
  } catch (e) { /* not ours */ }
  if (!stChan) return;
  // a window that went without saying so never answers: say where the stage can still be opened
  const rid = letters();
  stAcks.set(rid, setTimeout(() => {
    stAcks.delete(rid); stageWins.delete(win.id);
    note(`That stage window has closed. <a href="${stageUrl(wa, label)}" target="_blank" rel="noopener">Open stage ${esc(label)} in a new window</a>`);
  }, 900));
  stChan.postMessage({ type: 'add', to: win.id, wa, label, rid });
}
const stageList = st => {
  const by = new Map();
  st.forEach(x => { if (!by.has(x.wa)) by.set(x.wa, []); by.get(x.wa).push(x.label); });
  return [...by].map(([wa, ls]) => (by.size > 1 || wa !== WA ? `WA ${wa}: ` : '') + 'stage' + (ls.length > 1 ? 's ' : ' ') + ls.join(', ')).join(' · ');
};
function stageWindow(s) {
  const wins = openWins().filter(w => w.name);
  if (!wins.length) { newStageWindow(WA, s.label); return; }
  chooser(s, wins);
}
let chooseEl = null;
function closeChooser(refocus) {
  if (!chooseEl) return;
  chooseEl.remove(); chooseEl = null;
  document.removeEventListener('pointerdown', outsideChooser, true);
  if (refocus) $('ws-svg').focus();
}
const outsideChooser = e => { if (chooseEl && !chooseEl.contains(e.target)) closeChooser(false); };
function chooser(s, wins) {
  closeChooser(false); hideCard();
  const el = chooseEl = document.createElement('div');
  el.className = 'ws-choose'; el.setAttribute('role', 'dialog'); el.setAttribute('aria-label', `Where to open stage ${s.label}`);
  el.innerHTML = `<div class="ws-choose-h"><b>Stage ${esc(s.label)}</b><span>${esc(W.well.name || 'WA ' + WA)}</span></div>
    <p>A stage chart window is open. Stack this stage under the charts there, or give it a window of its own?</p>`;
  const acts = document.createElement('div'); acts.className = 'ws-choose-acts';
  wins.slice(0, 4).forEach((w, i) => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'go';
    const here = (w.stages || []).some(x => String(x.wa) === WA && String(x.label) === String(s.label));
    b.innerHTML = `<b>${here ? 'Show it in' : 'Stack in'} ${wins.length > 1 ? (i ? 'window ' + (i + 1) : 'the last window') : 'that window'}</b><span></span>`;
    b.querySelector('span').textContent = (w.stages || []).length ? stageList(w.stages) : 'empty';
    b.onclick = () => { closeChooser(false); stackStage(w, WA, s.label); };
    acts.append(b);
  });
  const nw = document.createElement('button');
  nw.type = 'button'; nw.innerHTML = '<b>Open a new window</b><span>this stage on its own</span>';
  nw.onclick = () => { closeChooser(false); newStageWindow(WA, s.label); };
  const x = document.createElement('button');
  x.type = 'button'; x.className = 'ws-choose-x'; x.setAttribute('aria-label', 'Cancel'); x.textContent = '×';
  x.onclick = () => closeChooser(true);
  acts.append(nw); el.append(x, acts);
  el.addEventListener('keydown', e => { if (e.key === 'Escape') { e.stopPropagation(); closeChooser(true); } });
  document.body.append(el);
  // beside the stage, inside the frame
  const r = $('ws-svg').getBoundingClientRect(), ax = r.left + (s.px != null ? s.px : r.width / 2), cw = el.offsetWidth, ch = el.offsetHeight;
  el.style.left = Math.max(8, Math.min(innerWidth - cw - 8, ax - cw / 2)) + 'px';
  el.style.top = Math.max(8, Math.min(innerHeight - ch - 8, r.top + r.height / 2 - ch / 2)) + 'px';
  document.addEventListener('pointerdown', outsideChooser, true);
  acts.querySelector('button').focus();
}
$('ws-charts').onclick = () => openStage(W && (W.stages.find(s => s.label === HI && s.curves) || W.stages.find(s => s.curves)));

// ---------- the section as a picture ----------
// The drawing as it is on screen (the stage picked out, no pointer), with the
// stylesheet's colours written onto each mark so it draws without the page, under
// a caption naming the well. Twice the screen's pixels, so it prints sharply.
const PAINT = ['fill', 'fill-opacity', 'stroke', 'stroke-width', 'stroke-opacity', 'stroke-dasharray', 'stroke-linejoin', 'stroke-linecap',
  'paint-order', 'opacity', 'font-family', 'font-size', 'font-weight'];
async function savePng() {
  if (!W || !G) return;
  const svg = $('ws-svg'), box = svg.getBoundingClientRect(), w = Math.round(box.width), h = Math.round(box.height);
  const was = hover; hover = null; drawHover();
  const copy = svg.cloneNode(true);
  hover = was; drawHover();
  const from = svg.querySelectorAll('*'), to = copy.querySelectorAll('*');
  from.forEach((el, i) => {
    const cs = getComputedStyle(el);
    to[i].removeAttribute('class');
    to[i].setAttribute('style', PAINT.map(k => [k, cs.getPropertyValue(k)]).filter(([, v]) => v && !v.includes('url(')).map(([k, v]) => `${k}:${v}`).join(';'));
  });
  copy.querySelectorAll('title').forEach(t => t.remove());
  copy.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  copy.setAttribute('width', w); copy.setAttribute('height', h); copy.removeAttribute('style');
  const img = new Image();
  img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(new XMLSerializer().serializeToString(copy));
  await img.decode();
  const cap = 46, k = 2, cv = document.createElement('canvas');
  cv.width = w * k; cv.height = (h + cap) * k;
  const g = cv.getContext('2d'), css = getComputedStyle(document.documentElement);
  g.scale(k, k);
  g.fillStyle = K.paper; g.fillRect(0, 0, w, h + cap);
  g.fillStyle = css.getPropertyValue('--ink').trim() || K.pad;
  g.font = '600 15px -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif';
  g.fillText($('ws-name').textContent, 12, 20);
  g.fillStyle = css.getPropertyValue('--mut').trim() || K.filed;
  g.font = '11px ui-monospace,Menlo,Consolas,monospace';
  g.fillText(`${$('ws-sub').textContent} · FracView ${new Date().toISOString().slice(0, 10)}`.slice(0, Math.floor((w - 24) / 6.6)), 12, 37);
  g.drawImage(img, 0, cap, w, h);
  const blob = await new Promise(res => cv.toBlob(res, 'image/png'));
  if (!blob) throw Error('no picture');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = `FracView-${WA}-section.png`;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}

// the wine rack's line on this well moved (null: it is off this well)
function cursorTo(wa, md) {
  EXT = md == null || !isFinite(md) ? null : { wa: String(wa), md: +md };
  if (!W || String(wa) !== WA || pointerIn) return;
  hover = extHover(); drawHover();
}
function show(wa, stage, at) {
  if (wa == null || wa === '') return;
  if (at !== undefined) EXT = at == null || !isFinite(at) ? null : { wa: String(wa), md: +at };
  HI = stage != null && stage !== '' ? String(stage) : null;
  if (String(wa) === WA && W) { syncUrl(); render(); return; }
  load(wa);
}
function announce() { if (!EMBED && chan) chan.postMessage({ type: 'hello', wa: WA }); }
if (EMBED) {
  // docked: the parent closes it and says which well to show; Pop out opens the
  // window from here, inside the click, so no popup blocker stands in the way
  document.body.classList.add('embedded');
  $('ws-pop').hidden = false; $('ws-close').hidden = false;
  $('ws-pop').onclick = () => {
    const q = new URLSearchParams({ wa: WA });
    if (HI) q.set('stage', HI); if (owner) q.set('owner', owner); if (ownerPage) q.set('page', ownerPage);
    const w = window.open('wellsection.html?' + q, 'stratum-section', 'popup,width=1280,height=620');
    if (w) parent.postMessage({ type: 'ws:popped', wa: WA, stage: HI }, ORIGIN);
  };
  $('ws-close').onclick = () => parent.postMessage({ type: 'ws:close' }, ORIGIN);
  window.stratumSectionShow = show;          // the parent's direct line, same origin
  window.stratumSectionCursor = cursorTo;
  addEventListener('message', e => {
    if (e.origin !== ORIGIN || e.source !== parent) return;
    const m = e.data;
    if (m && m.type === 'ws:show') show(m.wa, m.stage, m.at);
  });
} else {
  // popped out: follow the main window, and say so, so it sends wells here rather than docking
  const dockable = () => { $('ws-dock').hidden = !(owner && ownerPage === 'map'); };
  if (chan) chan.onmessage = e => {
    const m = e.data || {};
    if (m.type === 'show') {
      if (m.from) { owner = m.from; ownerPage = m.page || null; dockable(); }
      show(m.wa, m.stage, m.at);
    }
    else if (m.type === 'cursor') cursorTo(m.wa, m.at); else if (m.type === 'claim' && m.from) { owner = m.from; ownerPage = m.page || null; dockable(); }
    else if (m.type === 'ping') announce();
    else if (m.type === 'ack' && pending.has(m.id)) { pending.get(m.id)(true); pending.delete(m.id); }
  };
  addEventListener('pagehide', () => { if (chan) chan.postMessage({ type: 'bye' }); });
  dockable();
  $('ws-dock').onclick = () => ask({ type: 'dock', wa: WA, stage: HI }).then(ok => {
    if (ok) window.close(); else { owner = null; dockable(); note('The map window has closed.'); }
  });
}
addEventListener('keydown', e => { if (e.key === 'Escape' && EMBED && !chooseEl) parent.postMessage({ type: 'ws:close' }, ORIGIN); });

if (WA) load(WA); else empty('No well chosen. Open this page from a well on the map.', 'Well section');
