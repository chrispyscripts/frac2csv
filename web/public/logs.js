// FracView — the log data a well can be coloured by, one choice for every view
// (the 3D view, the wine rack, the well section).
//
//   Gamma ray    the BC wells' LAS gamma (data/gamma.json) and the gamma curve
//                of a WellSight log
//   Rock type    the log's lithology column: the rock at each depth
//   Porosity     the log's Porosity cells: where the bar ends, %
//   Oil show     the log's Oil Show symbols, dead to strong
//   curves       every other curve-track curve the logs hold (ROP, total gas,
//                C1, ...), by kind, each on its own scale
//
// The WellSight logs are Saskatchewan wells and not public data: they are
// built by scripts/build_sk.py into a folder outside the repo, which the local
// server mounts at data/sk/ (scripts/serve.py --mount). Where data/sk/ is
// missing (the live site) there are no Saskatchewan pads and the choices are
// gamma alone, as before.
//
// The type chosen is a setting (localStorage stratum.logType) shared by every
// window: a change fires `stratum:logtype` here and in every other open
// FracView window. Continuous types take the colours chosen for gamma
// (gamma-palettes.js); rock types and shows have colours of their own.
(() => {
'use strict';
const KEY = 'stratum.logType';
const BASE = [
  { k: 'gamma', t: 'Gamma ray', short: 'Gamma', u: 'API', kind: 'ramp' },
  { k: 'rock', t: 'Rock type', short: 'Rock type', kind: 'cat' },
  { k: 'por', t: 'Porosity', short: 'Porosity', u: '%', kind: 'por' },
  { k: 'show', t: 'Oil show', short: 'Oil show', kind: 'show' },
];
const dark = () => { const d = document.documentElement; return !!(d && d.dataset && d.dataset.theme === 'dark'); };
const SG = () => window.StratumGamma || null;
const fmt = (v, d = 0) => v == null || !isFinite(v) ? '–' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d });
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// ---------- the Saskatchewan set, where it is ----------
let SK = null;
const skReady = fetch('data/sk/index.json').then(r => (r.ok ? r.json() : null)).then(d => { SK = d && Array.isArray(d.pads) ? d : null; return SK; }).catch(() => null);
// (a pad or well from a file dropped on the map is kept in this browser:
// drop-store.js answers data/drop/ out of IndexedDB. It opens as a
// Saskatchewan pad does: a survey and stages, no BCER pad page)
const isSkPad = id => /^sk-/.test(String(id || ''));
const isDropPad = id => /^drop-/.test(String(id || ''));
const isDropWell = wa => /^DR\d+-/.test(String(wa || ''));
const isLocalPad = id => isSkPad(id) || isDropPad(id);
const isLocalWell = wa => /^SK/.test(String(wa || '')) || isDropWell(wa);
const padUrl = id => (isDropPad(id) ? 'data/drop/pads/' : isSkPad(id) ? 'data/sk/pads/' : 'data/region/pads/') + encodeURIComponent(id) + '.json';
const wellUrl = wa => (isDropWell(wa) ? 'data/drop/wells/' : /^SK/.test(String(wa || '')) ? 'data/sk/wells/' : 'data/wells/') + encodeURIComponent(wa) + '.json';
// how a well is named: its BCER well authorisation, or a Saskatchewan licence
const wellId = w => (w && w.licence ? 'Licence ' + w.licence : w && isDropWell(w.wa) ? (w.uwi || 'From your file') : 'WA ' + (w ? w.wa : '?'));

// ---------- the types ----------
// a curve type's name, unit and scale come from the set's index
function def(k) {
  const b = BASE.find(x => x.k === k);
  if (b) return b;
  const t = SK && SK.types && SK.types[k];
  if (!t) return { k, t: k.replace(/^[cx]:/, '').replace(/_/g, ' '), short: k.replace(/^[cx]:/, ''), u: '', kind: 'ramp' };
  const name = t.t.replace(/\s*\(rate of penetration\)/i, ' (ROP)');
  return { k, t: name, short: name.length > 16 ? name.replace(/\s*\(.*\)$/, '') : name, u: t.u || '', kind: 'ramp', curve: true };
}
function current() {
  let k = 'gamma';
  try { k = localStorage.getItem(KEY) || k; } catch (e) { /* private mode */ }
  return k;
}
function set(k) {
  if (!k) return;
  try { localStorage.setItem(KEY, k); } catch (e) { /* private mode: this window only */ }
  window.dispatchEvent(new CustomEvent('stratum:logtype', { detail: k }));
}
addEventListener('storage', e => { if (e.key === KEY) window.dispatchEvent(new CustomEvent('stratum:logtype', { detail: current() })); });

// A well's run of one type along MD: {md0, bin, v, est, from}, or null. A
// scene well carries a WellSight log as `logs` (its pad file), and a BC
// well's LAS gamma as gmd0/gbin/gv (attached from data/gamma.json).
function track(w, k) {
  if (!w) return null;
  const L = w.logs;
  if (L && L.types && Array.isArray(L.types[k]) && L.types[k].some(v => v != null)) return { md0: L.md0, bin: L.bin, v: L.types[k] };
  if (k === 'gamma' && Array.isArray(w.gv)) return { md0: w.gmd0, bin: w.gbin, v: w.gv, est: !!w.gest, from: w.gfrom };
  return null;
}
const at = (t, md) => { if (!t) return null; const v = t.v[Math.floor((md - t.md0) / t.bin)]; return v == null ? null : v; };
const has = (w, k) => !!track(w, k);
// the types these wells hold, gamma first, then rock, porosity, shows, then the
// curves the most wells have
function available(wells) {
  const n = new Map();
  for (const w of wells || []) {
    if (w.logs && w.logs.types) for (const [k, a] of Object.entries(w.logs.types)) if (a.some(v => v != null)) n.set(k, (n.get(k) || 0) + 1);
    if (Array.isArray(w.gv)) n.set('gamma', (n.get('gamma') || 0) + 1);
  }
  const base = BASE.filter(b => n.has(b.k)).map(b => b.k);
  const curves = [...n.keys()].filter(k => !BASE.some(b => b.k === k)).sort((a, b) => n.get(b) - n.get(a) || def(a).t.localeCompare(def(b).t));
  return base.concat(curves).map(k => ({ ...def(k), wells: n.get(k) }));
}
// the type to show for these wells: the one chosen, else the first they have
function pick(wells) {
  const av = available(wells), k = current();
  return av.find(x => x.k === k) ? k : av.length ? av[0].k : k;
}

// ---------- scales and colours ----------
// gamma on a BC well keeps data/gamma.json's scale (pass it as `bc`); every
// other run uses the Saskatchewan set's (P2-P98 over every log); porosity is
// the log's own 0-24 %, and shows run dead to strong
function scale(k, bc) {
  if (k === 'por') return { lo: 0, hi: 24, p50: 12 };
  if (k === 'show') return { lo: 0, hi: 4, p50: 2 };
  if (k === 'gamma' && bc) return bc;
  const s = SK && SK.scales && SK.scales[k];
  return s || (k === 'gamma' && bc) || null;
}
const POR = { light: ['#cfe3f3', '#a9cde9', '#7fb3dc', '#5797cb', '#357cb7', '#1f62a0', '#134b85', '#0c3768'],
              dark: ['#1d3a55', '#24527a', '#2b6b9e', '#3586c0', '#4aa2da', '#6cbbe8', '#96d2f1', '#c4e7f8'] };
const SHOW = { light: ['#9aa4ab', '#e3cd7a', '#d9a03b', '#b9651c', '#7a300c'], dark: ['#64727a', '#7a6a32', '#b5862f', '#e09a35', '#ffbe5c'] };
const SHOW_NAMES = ['Dead', 'Questionable', 'Weak', 'Moderate', 'Strong'];
// rock types in the usual mud-log colours; pale ones a shade deeper on the light theme
const ROCK = { sandstone: '#e8c33b', siltstone: '#c49a5e', shale: '#7f9470', claystone: '#9cab8e', limestone: '#5d9fd6',
  dolomite: '#a77fd0', anhydrite: '#e48fa4', gypsum: '#d79ab9', salt: '#9fb4c7', coal: '#262626', chert: '#b5651d',
  conglomerate: '#e0904d', breccia: '#d0845a', marlstone: '#8fb091', bentonite: '#cdb46a', till: '#b5ad93', igneous: '#c0504d',
  metamorphic: '#7f6a93', cement: '#8f969e' };
const ROCK_DARK = { coal: '#6e6e6e', shale: '#93aa83', claystone: '#b0bfa2', salt: '#c9d6e2' };
function rockInk(term) {
  if (dark() && ROCK_DARK[term]) return ROCK_DARK[term];
  if (ROCK[term]) return ROCK[term];
  let h = 0; for (const ch of String(term)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return `hsl(${h % 360} 38% ${dark() ? 62 : 52}%)`;
}
const rockTerm = i => (SK && SK.rocks && SK.rocks[i] ? SK.rocks[i][0] : String(i));
const rockName = i => (SK && SK.rocks && SK.rocks[i] ? SK.rocks[i][1] : 'Rock ' + i);
const ramp = (stops, f) => stops[Math.max(0, Math.min(stops.length - 1, Math.round(f * (stops.length - 1))))];
// a reading's colour, or null for none
function ink(k, v, s) {
  if (v == null) return null;
  if (k === 'rock') return rockInk(rockTerm(v));
  if (k === 'por') return ramp(POR[dark() ? 'dark' : 'light'], Math.min(1, v / 24));
  if (k === 'show') return SHOW[dark() ? 'dark' : 'light'][Math.max(0, Math.min(4, Math.round(v)))];
  const g = SG();
  if (!g || !s) return null;
  return g.ink(v, s);
}
// how a bar for the reading stands, 0..1, for the strips under a well: the
// reading on its scale; a rock fills its bar
function height(k, v, s) {
  if (v == null) return 0;
  if (k === 'rock') return 1;
  if (k === 'show') return (Math.round(v) + 1) / 5;
  if (k === 'por') return Math.max(.08, Math.min(1, v / 24));
  if (!s) return .5;
  return Math.max(.06, Math.min(1, (v - Math.min(0, s.lo)) / ((s.hi - Math.min(0, s.lo)) || 1)));
}
// a reading in words
function words(k, v) {
  if (v == null) return k === 'rock' ? 'no rock described' : k === 'show' ? 'no show' : 'no reading';
  if (k === 'rock') return rockName(v);
  if (k === 'por') return fmt(v, 1) + ' % porosity';
  if (k === 'show') return (SHOW_NAMES[Math.round(v)] || '?') + ' show';
  const d = def(k), dg = Math.abs(v) >= 100 ? 0 : Math.abs(v) >= 10 ? 1 : 2;
  return `${d.short} ${fmt(v, dg)}${d.u ? ' ' + d.u : ''}`;
}

// ---------- the menu: the type, and a step back and on through the ones here ----------
// `opts`: {types: available(...), onPick(k), label}
function menu(opts) {
  const box = document.createElement('div');
  box.className = 'lg-menu';
  const types = opts.types || [];
  const now = opts.value || current();
  const prev = document.createElement('button'), next = document.createElement('button'), sel = document.createElement('select');
  prev.type = next.type = 'button';
  prev.textContent = '◀'; next.textContent = '▶';
  prev.title = 'The previous kind of log data'; next.title = 'The next kind of log data';
  prev.setAttribute('aria-label', prev.title); next.setAttribute('aria-label', next.title);
  sel.setAttribute('aria-label', opts.label || 'Log data to colour the wells by');
  const logs = types.filter(t => !t.curve), curves = types.filter(t => t.curve);
  const group = (label, list) => {
    if (!list.length) return;
    const g = document.createElement('optgroup'); g.label = label;
    list.forEach(t => g.append(new Option(t.t + (t.u && t.kind === 'ramp' ? ` (${t.u})` : ''), t.k)));
    sel.append(g);
  };
  group('Log', logs); group('Log curves', curves);
  if (!types.length) sel.append(new Option('No log data here', ''));
  sel.value = types.some(t => t.k === now) ? now : (types[0] ? types[0].k : '');
  sel.disabled = types.length < 2; prev.disabled = next.disabled = types.length < 2;
  const go = k => { set(k); if (opts.onPick) opts.onPick(k); };
  sel.onchange = () => go(sel.value);
  const step = d => { const i = types.findIndex(t => t.k === sel.value); const t = types[(i + d + types.length) % types.length]; if (t) { sel.value = t.k; go(t.k); } };
  prev.onclick = () => step(-1); next.onclick = () => step(1);
  box.append(prev, sel, next);
  box.step = step;
  return box;
}
// step through the types from the keyboard: [ and ] (the views call this from their own key handlers)
function stepKey(e, types, onPick) {
  if (e.metaKey || e.ctrlKey || e.altKey || (e.key !== '[' && e.key !== ']') || !types || types.length < 2) return false;
  const k = current(), i = types.findIndex(t => t.k === k), t = types[(Math.max(0, i) + (e.key === ']' ? 1 : -1) + types.length) % types.length];
  set(t.k); if (onPick) onPick(t.k);
  return true;
}

// ---------- the key ----------
// the swatches or bar for a type, as HTML: `s` its scale; `rocks` the rock
// indices to show (the commonest first) for the rock key
function keyHtml(k, s, rocks) {
  const d = def(k);
  if (k === 'rock') {
    const list = (rocks || []).slice(0, 10);
    return `<div class="lg-sw">${list.map(i => `<span><b style="background:${rockInk(rockTerm(i))}"></b>${esc(rockName(i))}</span>`).join('') || '<span>No rocks described here</span>'}</div>`;
  }
  if (k === 'show') return `<div class="lg-sw">${SHOW_NAMES.map((n, i) => `<span><b style="background:${SHOW[dark() ? 'dark' : 'light'][i]}"></b>${n}</span>`).join('')}</div>`;
  if (k === 'por') {
    const st = POR[dark() ? 'dark' : 'light'];
    return `<div class="lg-bar" style="background:linear-gradient(90deg,${st.join(',')})"></div><div class="lg-ticks"><span>0 %</span><span>12 %</span><span>24 %+</span></div>`;
  }
  const g = SG();
  if (!s || !g) return '<div class="lg-note">No scale for this curve</div>';
  const dg = Math.abs(s.hi) >= 100 ? 0 : Math.abs(s.hi) >= 10 ? 1 : 2;
  const mid = g.PALETTES[g.current()].diverging ? 'median ' + fmt(s.p50, dg) : fmt((s.lo + s.hi) / 2, dg);
  return `<div class="lg-bar" style="background:${g.gradient()}"></div><div class="lg-ticks"><span>≤${fmt(s.lo, dg)}</span><span>${mid}</span><span>≥${fmt(s.hi, dg)}${d.u ? ' ' + esc(d.u) : ''}</span></div>`
    + (k === 'gamma' ? '<div class="lg-ticks lg-ends"><span>cleaner</span><span>shalier</span></div>' : '');
}
// the rocks along these wells, the most metres first
function rocksIn(wells) {
  const n = new Map();
  for (const w of wells || []) { const t = track(w, 'rock'); if (t) for (const v of t.v) if (v != null) n.set(v, (n.get(v) || 0) + 1); }
  return [...n.keys()].sort((a, b) => n.get(b) - n.get(a));
}
// what a type is, for the key's foot
function about(k) {
  if (k === 'gamma') return 'Gamma ray: the BC wells’ LAS logs (BCER eLibrary), and the gamma curve of a Saskatchewan mud log.';
  if (k === 'rock') return 'Rock type: the mud log’s lithology column, the rock at each depth (a horizontal log’s from its cross-section where the well crosses it).';
  if (k === 'por') return 'Porosity: the mud log’s Porosity cells, where the bar ends (0–24 %, a cell every 3 %).';
  if (k === 'show') return 'Oil show: the mud log’s Oil Show symbols, dead to strong, each reaching down to the next sample.';
  return def(k).t + ': the mud log’s curve, averaged every ' + ((SK && SK.bin_m) || 2) + ' m of MD; the scale spans every Saskatchewan log (P2–P98).';
}

if (!document.getElementById('lg-style')) {
  const st = document.createElement('style'); st.id = 'lg-style';
  st.textContent = `.lg-menu{display:flex;align-items:center;gap:4px;margin:4px 0 6px;pointer-events:auto}
.lg-menu select{flex:1;min-width:0;font:12px/1.2 -apple-system,Segoe UI,Roboto,sans-serif;padding:3px 4px;border-radius:6px;border:1px solid #c5d1d9;background:#fff;color:#14212b}
.lg-menu button{font:11px/1 -apple-system,Segoe UI,Roboto,sans-serif;padding:4px 6px;border-radius:6px;border:1px solid #c5d1d9;background:#f3f6f8;color:#3d505c;cursor:pointer}
.lg-menu button:hover:not(:disabled){border-color:#0d8577}.lg-menu button:disabled{opacity:.45;cursor:default}
[data-theme=dark] .lg-menu select{background:#0d1b25;border-color:#2c4452;color:#e7f4fa}
[data-theme=dark] .lg-menu button{background:#132331;border-color:#2c4452;color:#c9dbe3}
.lg-bar{height:9px;border-radius:4px;margin:4px 0 2px}.lg-ticks{display:flex;justify-content:space-between;font-size:11px;opacity:.85}
.lg-ends{opacity:.6}.lg-note{font-size:11px;opacity:.7}
.lg-sw{display:flex;flex-wrap:wrap;gap:3px 10px;margin:4px 0 2px;font-size:11px}.lg-sw span{display:inline-flex;align-items:center;gap:4px;white-space:nowrap}
.lg-sw b{display:inline-block;width:12px;height:10px;border-radius:2px;box-shadow:inset 0 0 0 1px rgba(0,0,0,.18)}`;
  (document.head || document.documentElement).append(st);
}

window.StratumLogs = { BASE, KEY, skReady, sk: () => SK, isLocalPad, isLocalWell, isSkPad, isDropPad, isDropWell, padUrl, wellUrl, wellId,
  def, current, set, track, at, has, available, pick, scale, ink, height, words, menu, stepKey, keyHtml, rocksIn, about,
  rockName, rockInk, rockTerm, SHOW_NAMES };
})();
