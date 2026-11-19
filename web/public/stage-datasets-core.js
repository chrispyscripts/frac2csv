// FracView — the reckoning behind the datasets stacked under a stage chart
// (stage-datasets.js draws them): which datasets a well has, where a stage
// sits along the well, the stretch of MD drawn around it, and the stack each
// card keeps. No page here, so tests/test_stage_datasets.js runs it in node.
//
// A dataset is one kind of reading along MD:
//   gamma          the well file's LAS gamma ray, or FracView's gamma
//                  (data/gamma.json: the LAS runs merged in bins, or estimated
//                  from offset logs) where the well file has none along the stages
//   las:<name>     every other LAS curve in the well file, one per curve name
//   rock por show  a Saskatchewan (or dropped) well's mud log: rock type,
//                  porosity, oil shows (logs.js)
//   c:… x:…        the mud log's curves: drill time, total gas, ...
//   comments       the well file's `comments`: described intervals and notes
// A card's stack is {kinds: [kind, ...], win: 'stage' | 'lateral' | 'well'}.
(() => {
'use strict';
const HALF = 75;                       // m either side of the stage
const WINS = ['stage', 'lateral', 'well'];
const WIN_NAMES = { stage: `Stage ±${HALF} m`, lateral: 'Lateral', well: 'Whole well' };
const BC_GAMMA = { lo: 70, p50: 114, hi: 180 };      // data/gamma.json's scale, when it is not at hand
// the LAS curves BC wells carry, in the order offered: one a well lacks is shown, disabled
const LAS_COMMON = ['Rate of penetration', 'Neutron porosity', 'Density porosity', 'Sonic', 'Bulk density', 'Caliper', 'Photoelectric'];
const LAS_UNITS = { 'Rate of penetration': 'm/hr', 'Neutron porosity': '%', 'Density porosity': '%', Sonic: 'µs/m', 'Bulk density': 'kg/m³', Caliper: 'mm', Photoelectric: 'b/e' };
const MUD = ['rock', 'por', 'show'];
const MUD_COMMON = ['c:rop', 'c:total_gas'];
const NO_FILE = 'Not on file for this well';
const NO_COMMENTS = 'No comments on file for this well';

const num = v => (v == null || v === '' ? NaN : +v);
// a reading, or NaN for none: LAS writes "no reading" as -999.25 (and a unit
// conversion can scale it: -999250)
const reading = v => { const x = num(v); return isFinite(x) && x > -999 ? x : NaN; };
const fmtM = v => Math.round(v).toLocaleString('en-US');

// LAS units as people write them
function unitName(u) {
  const s = String(u || '').trim(), k = s.toUpperCase();
  if (/^(G?API|AAPI)$/.test(k)) return 'API';
  if (k === 'M/HR' || k === 'M/H') return 'm/hr';
  if (k === 'PERC' || k === 'PU' || k === '%') return '%';
  if (k === 'US/M') return 'µs/m';
  if (k === 'US/F' || k === 'US/FT') return 'µs/ft';
  if (k === 'K/M3' || k === 'KG/M3') return 'kg/m³';
  if (k === 'G/C3' || k === 'G/CC') return 'g/cm³';
  if (k === 'B/E') return 'b/e';
  if (k === 'MM') return 'mm';
  if (k === 'OHMM' || k === 'OHM.M') return 'ohm·m';
  return s;
}

// ---------- where the stages are ----------
function depthOf(s) {
  if (!s) return null;
  const t = num(s.top_m), b = num(s.base_m);
  if (!isFinite(t) && !isFinite(b)) return null;
  const a = isFinite(t) ? t : b, z = isFinite(b) ? b : t;
  return { top: Math.min(a, z), base: Math.max(a, z) };
}
const labelOf = s => (s.label != null ? String(s.label) : s.n != null ? String(s.n) : '');
// the lists that can place a stage, best first: the well file's stages, the
// BCER filing, the depth intervals, then (a Saskatchewan well) its pad row's
function stageLists(file, row) {
  return [file && file.stages, file && file.bcer_stages, file && file.depth_intervals, row && row.stages, row && row.depth_intervals]
    .filter(Array.isArray)
    .map(l => l.filter(Boolean).map(s => ({ label: labelOf(s), d: depthOf(s) })).filter(s => s.d));
}
function depthIn(lists, label) {
  label = String(label);
  for (const l of lists) { const s = l.find(x => x.label === label); if (s) return s.d; }
  return null;
}
// every placed stage, for the marks along the axis: the first list that places any
const stagesIn = lists => (lists.find(l => l.length) || []).map(s => ({ label: s.label, top: s.d.top, base: s.d.base }));

// ---------- runs of readings ----------
// md and v of one length, md rising
function run(md, v) {
  const out = [];
  for (let i = 0; i < md.length; i++) { const m = num(md[i]); if (isFinite(m)) out.push([m, reading(v[i])]); }
  if (out.some((p, i) => i && p[0] < out[i - 1][0])) out.sort((a, b) => a[0] - b[0]);
  return { md: out.map(p => p[0]), v: out.map(p => p[1]) };
}
// readings kept in bins from md0: each at its bin's middle
function binned(md0, bin, v) {
  const md = [], out = [];
  for (let i = 0; i < v.length; i++) { md.push(md0 + (i + 0.5) * bin); out.push(reading(v[i])); }
  return { md, v: out };
}
// where a run has readings
function extent(r) {
  let a = -1, b = -1;
  for (let i = 0; i < r.v.length; i++) if (isFinite(r.v[i])) { if (a < 0) a = i; b = i; }
  return a < 0 ? null : { lo: r.md[a], hi: r.md[b] };
}
// how much of lo..hi a run reaches, 0..1
function cover(r, lo, hi) {
  const e = r && extent(r);
  if (!e || !(hi > lo)) return 0;
  return Math.max(0, Math.min(hi, e.hi) - Math.max(lo, e.lo)) / (hi - lo);
}
// the usual spacing of a run's readings
function spacing(md) {
  const d = [];
  for (let i = 1; i < md.length; i++) if (md[i] > md[i - 1]) d.push(md[i] - md[i - 1]);
  d.sort((a, b) => a - b);
  return d.length ? d[d.length >> 1] : 1;
}
function niceStep(raw) {
  if (!(raw > 0)) return 1;
  const e = Math.pow(10, Math.floor(Math.log10(raw)));
  return [1, 2, 2.5, 5, 10].map(k => k * e).find(s => s >= raw - 1e-12);
}
// a curve's scale over the whole well, so stepping through stages keeps it:
// its 1st to 99th percentile, rounded out to a readable step
function robust(v) {
  const s = v.filter(isFinite).sort((a, b) => a - b);
  if (!s.length) return { lo: 0, hi: 1 };
  const q = p => s[Math.min(s.length - 1, Math.max(0, Math.round(p * (s.length - 1))))];
  let lo = q(0.01), hi = q(0.99);
  if (!(hi > lo)) { const pad = Math.abs(lo) * 0.1 || 1; lo -= pad; hi += pad; }
  const st = niceStep((hi - lo) / 4);
  return { lo: Math.floor(lo / st) * st, hi: Math.ceil(hi / st) * st };
}

// ... over the readings inside span [lo, hi] only, when it holds enough of them
function robustIn(r, span, min = 12) {
  if (!span) return null;
  const v = [];
  for (let i = 0; i < r.md.length; i++) if (r.md[i] >= span[0] && r.md[i] <= span[1] && isFinite(r.v[i])) v.push(r.v[i]);
  return v.length >= min ? robust(v) : null;
}

// ---------- comments ----------
function cleanComments(a) {
  if (!Array.isArray(a)) return [];
  return a.filter(c => c && isFinite(num(c.top)) && c.text != null && String(c.text).trim()).map(c => {
    const t = num(c.top), b = isFinite(num(c.base)) ? num(c.base) : t;
    const rocks = c.rocks && typeof c.rocks === 'object'
      ? Object.entries(c.rocks).map(([k, p]) => [String(k), isFinite(num(p)) ? num(p) : null]).sort((x, y) => (y[1] ?? -1) - (x[1] ?? -1)) : [];
    return { top: Math.min(t, b), base: Math.max(t, b), text: String(c.text).trim(), kind: c.kind === 'note' ? 'note' : 'description',
             rocks, from: c.from ? String(c.from) : '', file: c.file ? String(c.file) : '' };
  }).sort((x, y) => x.top - y.top || x.base - y.base);
}
const commentsIn = (items, lo, hi) => items.filter(c => c.base >= lo && c.top <= hi);
// rows for intervals that overlap, so each is seen: the first row free at its top (at most `max`)
function lanes(items, max = 4) {
  const ends = [];
  return items.map(c => {
    let k = ends.findIndex(e => e < c.top);
    if (k < 0) { if (ends.length < max) { k = ends.length; ends.push(-Infinity); } else k = ends.indexOf(Math.min(...ends)); }
    ends[k] = Math.max(ends[k], c.base);
    return k;
  });
}

// ---------- a well's datasets ----------
const gammaEntry = (gj, wa) => {
  const w = gj && gj.wells;
  if (!w) return null;
  const g = w[wa] || w[String(wa).padStart(5, '0')] || w[String(wa).replace(/^0+/, '')];
  return g && Array.isArray(g.v) && g.v.some(v => v != null) ? g : null;
};
const isLocal = (wa, S) => (S && S.isLocalWell ? S.isLocalWell(wa) : /^(SK|DR\d+-)/.test(String(wa)));
const wellOf = (file, row) => (file && file.well) || (row && row.well) || {};
// the stretch the stages cover, else the lateral: where a gamma run has to reach
function stageSpan(stages, heel, td) {
  if (stages.length) return [Math.min(...stages.map(s => s.top)), Math.max(...stages.map(s => s.base))];
  if (heel != null && td != null && td > heel) return [heel, td];
  return null;
}
// does a BC well want FracView's gamma file? when its own LAS gamma misses most of the stages
function needsGammaFile(wa, file, row, S) {
  if (isLocal(wa, S)) return false;
  const gr = ((file && file.logs) || []).find(L => L && isGamma(L));
  if (!gr) return true;
  const w = wellOf(file, row), lists = stageLists(file, row);
  const span = stageSpan(stagesIn(lists), num(w.heel_md) > 0 ? +w.heel_md : null, num(w.td_m) > 0 ? +w.td_m : null);
  return !span || cover(run(gr.md || [], gr.v || []), span[0], span[1]) < 0.9;
}
const isGamma = L => /^gamma ray$/i.test(String(L.name || '')) || /^(GR|GRC|SGR|CGR)$/i.test(String(L.mnemonic || ''));

// {wa, ok, local, name, heel, td, stages, lists, sets: Map kind -> dataset, offer: [...]}
// `gj` data/gamma.json (BC wells), `S` logs.js (Saskatchewan and dropped wells)
function buildModel(wa, file, row, gj, S) {
  wa = String(wa);
  const local = isLocal(wa, S), w = wellOf(file, row), rw = (row && row.well) || {};
  const pos = v => (num(v) > 0 ? +v : null);
  const heel = pos(w.heel_md) ?? pos(rw.heel_md), td = pos(w.td_m) ?? pos(rw.td_m);
  const lists = stageLists(file, row), stages = stagesIn(lists);
  const span = stageSpan(stages, heel, td);
  const sets = new Map(), offer = [];
  const put = (kind, ds) => { const e = extent(ds); if (!e && ds.style !== 'notes') return; sets.set(kind, { kind, ...e, ...ds }); };
  // a curve's scale: along the lateral, where the stages are (else over the stages), so the strips
  // around a stage read well and keep one scale stage to stage; over the whole run for the whole well
  const along = heel != null && td != null && td > heel ? [heel, td] : span;
  const scales = r => ({ scale: robustIn(r, along) || robust(r.v), scaleAll: robust(r.v) });
  const line = (r, extra) => ({ style: 'line', md: r.md, v: r.v, gap: Math.max(3 * spacing(r.md), 1), ...scales(r), ...extra });

  if (!local) {
    // the well file's LAS curves, one per name (the first: a second "Neutron porosity" is another matrix of the same)
    for (const L of (file && file.logs) || []) {
      if (!L || !L.name || !Array.isArray(L.md) || !Array.isArray(L.v)) continue;
      const g = isGamma(L), kind = g ? 'gamma' : 'las:' + L.name;
      if (sets.has(kind)) continue;
      const r = run(L.md, L.v);
      put(kind, line(r, { t: g ? 'Gamma ray' : L.name, u: g ? 'API' : unitName(L.unit), group: 'log',
        src: `LAS ${L.mnemonic || ''}`.trim(), file: L.file || '', palette: g, cscale: g ? (gj && gj.scale) || BC_GAMMA : null }));
    }
    // FracView's gamma, where the well file's misses the stages
    const ge = gammaEntry(gj, wa);
    if (ge) {
      const bin = +gj.bin_m || 5, r = binned(+ge.md0 || 0, bin, ge.v), own = sets.get('gamma');
      const better = !own || (span ? cover(r, span[0], span[1]) > cover(own, span[0], span[1]) + 0.1 : false);
      if (extent(r) && better) {
        put('gamma', line(r, { t: 'Gamma ray', u: gj.unit || 'API', group: 'log', est: !!ge.estimated, palette: true, cscale: gj.scale || BC_GAMMA,
          src: ge.estimated ? 'estimated from offset logs' : `FracView gamma: the LAS runs in ${bin} m bins`, bin }));
      }
    }
    const g = sets.get('gamma');
    offer.push({ kind: 'gamma', t: 'Gamma ray', u: 'API', group: 'log', ds: g || null });
    // the well's curves, the usual ones in the usual order, then any others as the file has them
    const rank = k => { const i = LAS_COMMON.indexOf(k.slice(4)); return i < 0 ? LAS_COMMON.length : i; };
    const own = [...sets.keys()].filter(k => k.startsWith('las:')).map((k, i) => [k, i]).sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1]).map(x => x[0]);
    for (const k of own) { const ds = sets.get(k); offer.push({ kind: k, t: ds.t, u: ds.u, group: 'log', ds }); }
    for (const n of LAS_COMMON) if (!sets.has('las:' + n)) offer.push({ kind: 'las:' + n, t: n, u: LAS_UNITS[n] || '', group: 'log', ds: null });
  } else {
    // a Saskatchewan or dropped well: its mud log, through logs.js
    // where its log came from: a WellSight log, a printout read by the Lab, or (rock type) the geologist's written descriptions
    const L = row && row.logs, src = L && Array.isArray(L.src) ? L.src.filter(Boolean) : [];
    const said = list => [...new Set(list.map(x => (x.log === 'printout' ? 'mud log, read off its printout' : x.log === 'descriptions' ? 'the written sample descriptions' : 'WellSight mud log')))].join(' and ') || 'WellSight mud log';
    const from = said(src.filter(x => x.log !== 'descriptions')), fromRock = said(src.filter(x => x.lith).length ? src.filter(x => x.lith) : src);
    const kinds = L && S ? S.available([row]).map(t => t.k) : [];
    for (const k of kinds) {
      const t = S.track(row, k);
      if (!t) continue;
      const d = S.def(k), r = binned(+t.md0, +t.bin, t.v);
      const base = { t: d.t, u: d.u || '', group: MUD.includes(k) ? 'mud' : 'log', src: k === 'rock' ? fromRock : from, md0: +t.md0, bin: +t.bin, raw: t.v };
      if (k === 'rock' || k === 'show') put(k, { ...base, style: 'cat', md: r.md, v: r.v });
      else if (k === 'por') put(k, { ...base, style: 'bars', md: r.md, v: r.v, gap: +t.bin * 1.5, scale: { lo: 0, hi: 24 }, scaleAll: { lo: 0, hi: 24 } });
      else put(k, line(r, { ...base, palette: k === 'gamma', cscale: S.scale(k) || null }));
    }
    const def = k => (S ? S.def(k) : { t: k, u: '' });
    const want = ['gamma', ...MUD, ...kinds.filter(k => /^[cx]:/.test(k))];
    for (const k of MUD_COMMON) if (!want.includes(k)) want.push(k);
    for (const k of want) offer.push({ kind: k, t: def(k).t, u: def(k).u || '', group: MUD.includes(k) ? 'mud' : 'log', ds: sets.get(k) || null });
  }

  const cm = cleanComments(file && file.comments);
  if (cm.length) {
    const why = [...new Set(cm.map(c => c.from).filter(Boolean))].join(' and ');
    sets.set('comments', { kind: 'comments', t: 'Comments', u: '', group: 'notes', style: 'notes', items: cm,
      lo: Math.min(...cm.map(c => c.top)), hi: Math.max(...cm.map(c => c.base)), src: why ? `from the ${why}` : '' });
  }
  offer.push({ kind: 'comments', t: 'Comments', u: '', group: 'notes', ds: sets.get('comments') || null, why: NO_COMMENTS });
  return { wa, ok: true, local, name: w.name || '', heel, td, stages, lists, span, sets, offer };
}
const emptyModel = (wa, err) => ({ wa: String(wa), ok: false, err, local: false, name: '', heel: null, td: null, stages: [], lists: [], span: null, sets: new Map(), offer: [] });

// what the picker lists for a well: every dataset it has, and the usual ones it
// lacks (disabled, with why). `have` the kinds already stacked
function catalogue(m, have = []) {
  return m.offer.map(o => {
    const added = have.includes(o.kind), ds = o.ds;
    let note;
    if (!ds) note = o.why || NO_FILE;
    else if (added) note = 'In this stack';
    else note = about(ds, m);
    return { kind: o.kind, t: o.t, u: o.u, group: o.group, ok: !!ds && !added, added, note };
  });
}
// a dataset in a line: where it runs and where it is from
function about(ds, m) {
  if (ds.style === 'notes') return `${ds.items.length} on file · ${fmtM(ds.lo)}–${fmtM(ds.hi)} m${ds.src ? ' · ' + ds.src : ''}`;
  const parts = [`${fmtM(ds.lo)}–${fmtM(ds.hi)} m MD`];
  if (m && m.span && ds.hi < m.span[0] - 10) parts.push('ends above the stages');
  else if (m && m.span && ds.lo > m.span[1] + 10) parts.push('starts below the stages');
  if (ds.src) parts.push(ds.src);
  return parts.join(' · ');
}

// ---------- the stack ----------
// a stack's kinds the well has, in order, once each
const resolve = (kinds, m) => [...new Set(kinds || [])].filter(k => m && m.sets.has(k));
function sanitizeStack(o) {
  if (!o || typeof o !== 'object' || !Array.isArray(o.kinds)) return null;
  const kinds = [...new Set(o.kinds.filter(k => typeof k === 'string' && k && k.length < 120))].slice(0, 16);
  return { kinds, win: WINS.includes(o.win) ? o.win : 'stage' };
}
// the same stack: the same kinds in the same order, and (with any) the same window
const sameStack = (a, b) => a.kinds.length === b.kinds.length && a.kinds.every((k, i) => k === b.kinds[i]) && (!a.kinds.length || a.win === b.win);
// what a card of this well would open with under the default `def`
const expected = (def, m) => (def ? { kinds: m ? resolve(def.kinds, m) : def.kinds.slice(), win: def.win } : { kinds: [], win: 'stage' });

// ---------- the window along MD ----------
// {lo, hi, win (the one drawn), stage: {top, base} | null, note}
function windowFor(win, m, label, kinds = []) {
  const st = depthIn(m.lists || [], label);
  const out = (lo, hi, w, note = '') => {
    if (!(hi - lo >= 20)) { const mid = (lo + hi) / 2; lo = mid - 10; hi = mid + 10; }
    return { lo, hi, win: w, stage: st, note };
  };
  if (win === 'stage' && st) return out(st.top - HALF, st.base + HALF, 'stage');
  const note = win === 'stage' ? 'This stage’s depth is not on file, so the lateral is shown.' : '';
  if (win !== 'well') {
    if (m.heel != null && m.td != null && m.td > m.heel) return out(m.heel, m.td, 'lateral', note);
    if (m.stages.length) {
      const lo = Math.min(...m.stages.map(s => s.top)), hi = Math.max(...m.stages.map(s => s.base));
      return out(lo - 30, hi + 30, 'lateral', note);
    }
  }
  const los = [], his = [];
  for (const k of kinds) { const ds = m.sets.get(k); if (ds && isFinite(ds.lo)) { los.push(ds.lo); his.push(ds.hi); } }
  for (const s of m.stages) { los.push(s.top); his.push(s.base); }
  if (m.td != null) his.push(m.td);
  if (!los.length && !his.length) return out(0, 1000, 'well', win === 'well' ? '' : note || 'Neither this well’s lateral nor its stages are on file.');
  const lo = los.length ? Math.max(0, Math.min(...los)) : 0, hi = Math.max(...his, lo + 20);
  return out(lo, hi, 'well', win === 'well' ? '' : note || 'Neither this well’s lateral nor its stages are on file.');
}

// ticks along lo..hi, at least `minPx` apart on `px` pixels
function ticks(lo, hi, px, minPx = 70) {
  const step = niceStep((hi - lo) * minPx / Math.max(1, px));
  const at = [];
  for (let v = Math.ceil(lo / step - 1e-9) * step; v <= hi + 1e-9 && at.length < 200; v += step) at.push(+v.toFixed(6));
  return { step, at };
}

// a dataset's reading at md: {md, v} (v null where there is none), or null off its run
function valueAt(ds, md) {
  if (!ds || !isFinite(md)) return null;
  if (ds.style === 'notes') return { md, v: ds.items.filter(c => c.top <= md && c.base >= md) };
  if (ds.style === 'cat') {
    const i = Math.floor((md - ds.md0) / ds.bin);
    if (i < 0 || i >= ds.raw.length) return null;
    const v = ds.raw[i];
    return { md: ds.md0 + (i + 0.5) * ds.bin, v: v == null ? null : v };
  }
  const a = ds.md;
  if (!a.length) return null;
  let lo = 0, hi = a.length - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (a[mid] < md) lo = mid; else hi = mid; }
  const i = Math.abs(a[lo] - md) <= Math.abs(a[hi] - md) ? lo : hi;
  if (Math.abs(a[i] - md) > (ds.gap || 1)) return null;
  return { md: a[i], v: isFinite(ds.v[i]) ? ds.v[i] : null };
}
// the first and last index of a run inside lo..hi (one either side, so a line reaches the edge)
function slice(md, lo, hi) {
  let a = 0, b = md.length - 1;
  while (a < md.length && md[a] < lo) a++;
  while (b >= 0 && md[b] > hi) b--;
  return [Math.max(0, a - 1), Math.min(md.length - 1, b + 1)];
}

// ---------- a well's stages on the map (map-stages.js) ----------
// the point at `md` along a trajectory {md, lat, lon}: [lon, lat], or null off
// it. A port a little past the last station (at TD) still sits at the toe.
function along(t, md) {
  if (!t || !Array.isArray(t.md) || !Array.isArray(t.lat) || !Array.isArray(t.lon) || !isFinite(md)) return null;
  const pts = [];
  for (let i = 0; i < t.md.length; i++) {
    const m = num(t.md[i]), la = num(t.lat[i]), lo = num(t.lon[i]);
    if (isFinite(m) && isFinite(la) && isFinite(lo) && (!pts.length || m >= pts[pts.length - 1][0])) pts.push([m, lo, la]);
  }
  if (pts.length < 2 || md < pts[0][0] - 1 || md > pts[pts.length - 1][0] + 30) return null;
  if (md >= pts[pts.length - 1][0]) return [pts[pts.length - 1][1], pts[pts.length - 1][2]];
  if (md <= pts[0][0]) return [pts[0][1], pts[0][2]];
  let lo = 0, hi = pts.length - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (pts[mid][0] <= md) lo = mid; else hi = mid; }
  const a = pts[lo], b = pts[hi], f = b[0] > a[0] ? (md - a[0]) / (b[0] - a[0]) : 0;
  return [+(a[1] + f * (b[1] - a[1])).toFixed(6), +(a[2] + f * (b[2] - a[2])).toFixed(6)];
}
// a pad file's well {well, trajectory, stages, depth_intervals}: its stages
// where they sit on the map, [{label, top, base, md, at: [lon, lat]}], placed
// as the datasets under a stage chart place them (stagesIn)
function stagePoints(w) {
  if (!w) return [];
  const out = [];
  for (const s of stagesIn(stageLists(w, null))) {
    const md = (s.top + s.base) / 2, at = along(w.trajectory, md);
    if (at) out.push({ label: s.label, top: s.top, base: s.base, md, at });
  }
  return out;
}
// what was filed for a stage, in words: [[name, value], ...] (the treatment
// summary where the well's stages carry one, else the depth interval's filing)
const FACTS = [['date', 'Date'], ['completion_type', 'Completion'], ['proppant_t', 'Proppant', 't'], ['fluid_m3', 'Fluid', 'm³'],
  ['avg_rate_m3_min', 'Average rate', 'm³/min'], ['avg_pressure_mpa', 'Average pressure', 'MPa'], ['max_pressure_mpa', 'Max pressure', 'MPa'],
  ['breakdown_mpa', 'Breakdown', 'MPa'], ['isip_mpa', 'ISIP', 'MPa']];
function stageFacts(w, label) {
  label = String(label);
  const find = l => (Array.isArray(l) ? l.find(s => s && labelOf(s) === label) : null);
  const merged = { ...(find(w && w.depth_intervals) || {}), ...(find(w && w.stages) || {}) };
  const out = [];
  for (const [k, name, u] of FACTS) {
    const v = merged[k];
    if (v == null || v === '') continue;
    if (u) { const x = num(v); if (isFinite(x)) out.push([name, `${x.toLocaleString('en-US', { maximumFractionDigits: x >= 100 ? 0 : 1 })} ${u}`]); }
    else out.push([name, k === 'date' && /^\d{8}$/.test(String(v)) ? `${String(v).slice(0, 4)}-${String(v).slice(4, 6)}-${String(v).slice(6)}` : String(v)]);
  }
  return out;
}

window.StageDatasetsCore = { HALF, WINS, WIN_NAMES, BC_GAMMA, LAS_COMMON, LAS_UNITS, NO_FILE, NO_COMMENTS, unitName, depthOf, stageLists, depthIn, stagesIn,
  run, binned, extent, cover, spacing, niceStep, robust, robustIn, cleanComments, commentsIn, lanes, gammaEntry, needsGammaFile, buildModel, emptyModel,
  catalogue, about, resolve, sanitizeStack, sameStack, expected, windowFor, ticks, valueAt, slice, fmtM, along, stagePoints, stageFacts };
})();
