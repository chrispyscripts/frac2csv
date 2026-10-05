// The earthquake filter, one for every view that shows quakes (the map, the 3D
// view, a well's charts): a date range, a magnitude range, and whether to leave
// out events whose depth the network did not solve, events that do not
// coincide with a frac stage, and events located only to the kilometre.
//
// Kept as a setting (localStorage stratum.quakeFilter), so it carries across
// windows, reloads and saved sessions; a change fires `stratum:quakefilter` on
// window here and in every other open FracView window.
(() => {
'use strict';
const KEY = 'stratum.quakeFilter';
const DEFAULT = { from: null, to: null, magMin: null, magMax: null, hideFixed: false, onlyMatched: false, onlyRelocated: false };
const DAY = 864e5;
const isDate = s => typeof s === 'string' && /^\d{4}-\d\d-\d\d$/.test(s);
const num = v => v === '' || v == null || !isFinite(+v) ? null : +v;

function get() {
  let f = {};
  try { f = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (e) { /* private mode */ }
  return { from: isDate(f.from) ? f.from : null, to: isDate(f.to) ? f.to : null, magMin: num(f.magMin), magMax: num(f.magMax),
           hideFixed: !!f.hideFixed, onlyMatched: !!f.onlyMatched, onlyRelocated: !!f.onlyRelocated };
}
function set(f) {
  const clean = { ...DEFAULT, ...f };
  try {
    if (active(clean)) localStorage.setItem(KEY, JSON.stringify(clean)); else localStorage.removeItem(KEY);
  } catch (e) { /* private mode: this window only */ }
  window.dispatchEvent(new CustomEvent('stratum:quakefilter', { detail: clean }));
}
addEventListener('storage', e => { if (e.key === KEY) window.dispatchEvent(new CustomEvent('stratum:quakefilter', { detail: get() })); });
const active = (f = get()) => !!(f.from || f.to || f.magMin != null || f.magMax != null || f.hideFixed || f.onlyMatched || f.onlyRelocated);
const dayStart = d => Date.parse(d + 'T00:00:00Z');

// one event, as {t: ms, mag, fixed: depth not solved, matched: coincides with a stage, src}
function pass(q, f = get()) {
  if (f.from && !(q.t >= dayStart(f.from))) return false;
  if (f.to && !(q.t < dayStart(f.to) + DAY)) return false;
  if (f.magMin != null && !(q.mag != null && q.mag >= f.magMin)) return false;
  if (f.magMax != null && !(q.mag != null && q.mag <= f.magMax)) return false;
  if (f.hideFixed && q.fixed) return false;
  if (f.onlyMatched && !q.matched) return false;
  if (f.onlyRelocated && q.src !== 'bcsrc') return false;
  return true;
}
// a row of data/seismic/events.json as that event
const fromRow = r => ({ t: Date.parse(r[0]), mag: r[4], fixed: !!r[6] || r[3] == null, matched: !!r[11], src: r[8] });

// the same test as a MapLibre filter, over features carrying ms, mag, fixed, m, src
function mapFilter(f = get()) {
  const all = ['all'];
  if (f.from) all.push(['>=', ['get', 'ms'], dayStart(f.from)]);
  if (f.to) all.push(['<', ['get', 'ms'], dayStart(f.to) + DAY]);
  if (f.magMin != null) all.push(['>=', ['coalesce', ['get', 'mag'], -99], f.magMin]);
  if (f.magMax != null) all.push(['<=', ['coalesce', ['get', 'mag'], 99], f.magMax]);
  if (f.hideFixed) all.push(['!', ['to-boolean', ['get', 'fixed']]]);
  if (f.onlyMatched) all.push(['!=', ['get', 'm'], '']);
  if (f.onlyRelocated) all.push(['==', ['get', 'src'], 'bcsrc']);
  return all.length > 1 ? all : null;
}
// in words, for a summary line
function describe(f = get()) {
  const bits = [];
  if (f.magMin != null && f.magMax != null) bits.push(`M${f.magMin}–${f.magMax}`);
  else if (f.magMin != null) bits.push(`M${f.magMin} and up`);
  else if (f.magMax != null) bits.push(`up to M${f.magMax}`);
  if (f.from && f.to) bits.push(`${f.from} to ${f.to}`); else if (f.from) bits.push(`from ${f.from}`); else if (f.to) bits.push(`to ${f.to}`);
  if (f.hideFixed) bits.push('solved depths only');
  if (f.onlyMatched) bits.push('coinciding with a stage');
  if (f.onlyRelocated) bits.push('relocated only');
  return bits.join(' · ');
}

// ---------- the form, in a small panel under the button that opens it ----------
const CSS = `
.qf{position:fixed;z-index:90;width:300px;max-width:calc(100vw - 16px);background:#0d1924;border:1px solid #345260;border-radius:12px;
  box-shadow:0 16px 40px #000b;padding:12px 13px 11px;color:#e7f4fa;font:13px/1.4 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
.qf h3{margin:0 0 9px;font-size:13.5px;font-weight:650;display:flex;align-items:center;gap:7px}
.qf h3 i{width:9px;height:9px;border-radius:50%;background:#ff5fa2;display:inline-block}
.qf .row{display:grid;grid-template-columns:76px 1fr 1fr;gap:6px;align-items:center;margin-bottom:7px}
.qf .row>span{color:#93adb9;font-size:12px}
.qf input[type=date],.qf input[type=number]{background:#0a141d;border:1px solid #345260;border-radius:7px;color:#e7f4fa;padding:5px 6px;font:12.5px ui-monospace,Menlo,monospace;min-width:0;width:100%;color-scheme:dark}
.qf label.ck{display:flex;gap:7px;align-items:flex-start;margin:6px 0;font-size:12.5px;color:#d6e6ee;cursor:pointer}
.qf label.ck input{margin:2px 0 0;accent-color:#ff5fa2}
.qf label.ck small{display:block;color:#7f97a4;font-size:11.5px}
.qf .foot{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:9px;padding-top:8px;border-top:1px solid #243a46}
.qf .count{color:#93adb9;font:12px ui-monospace,Menlo,monospace}
.qf button{background:#152936;border:1px solid #345260;border-radius:7px;color:#e7f4fa;padding:5px 10px;font:inherit;font-size:12.5px;cursor:pointer}
.qf button:hover{border-color:#5ee2d0}
.qf input:focus-visible,.qf button:focus-visible{outline:2px solid #5ee2d0;outline-offset:1px}`;
let open = null;
function close() { if (open) { open.el.remove(); document.removeEventListener('pointerdown', open.outside, true); open.anchor.setAttribute('aria-expanded', 'false'); open = null; } }
// anchor: the button; o.bounds {first, last, magMin, magMax} for the placeholders; o.count(f) -> "n of N"
function panel(anchor, o = {}) {
  if (open && open.anchor === anchor) { close(); return; }
  close();
  if (!document.getElementById('qf-style')) { const st = document.createElement('style'); st.id = 'qf-style'; st.textContent = CSS; document.head.append(st); }
  const b = o.bounds || {}, f = get();
  const el = document.createElement('div');
  el.className = 'qf'; el.setAttribute('role', 'dialog'); el.setAttribute('aria-label', 'Filter earthquakes');
  el.innerHTML = `<h3><i></i>Earthquakes shown</h3>
    <div class="row"><span>Dates</span><input type="date" name="from" aria-label="From date"><input type="date" name="to" aria-label="To date"></div>
    <div class="row"><span>Magnitude</span><input type="number" name="magMin" step="0.1" aria-label="Minimum magnitude"><input type="number" name="magMax" step="0.1" aria-label="Maximum magnitude"></div>
    <label class="ck"><input type="checkbox" name="hideFixed"><span>Hide undetermined depths<small>events whose depth the network fixed rather than solved</small></span></label>
    <label class="ck"><input type="checkbox" name="onlyMatched"><span>Only those coinciding with a frac stage</span></label>
    <label class="ck"><input type="checkbox" name="onlyRelocated"><span>Only relocated events<small>BC Seismic Research Consortium, May 2022–Apr 2024, located to a few hundred metres</small></span></label>
    <div class="foot"><span class="count"></span><button type="button" name="reset">Show all</button></div>`;
  const q = n => el.querySelector(`[name=${n}]`);
  if (b.first) { q('from').min = q('to').min = b.first; q('from').placeholder = b.first; }
  if (b.last) { q('from').max = q('to').max = b.last; q('to').placeholder = b.last; }
  if (b.magMin != null) q('magMin').placeholder = `min ${b.magMin}`;
  if (b.magMax != null) q('magMax').placeholder = `max ${b.magMax}`;
  const fill = v => {
    q('from').value = v.from || ''; q('to').value = v.to || '';
    q('magMin').value = v.magMin ?? ''; q('magMax').value = v.magMax ?? '';
    ['hideFixed', 'onlyMatched', 'onlyRelocated'].forEach(k => { q(k).checked = !!v[k]; });
  };
  const read = () => ({ from: q('from').value || null, to: q('to').value || null, magMin: num(q('magMin').value), magMax: num(q('magMax').value),
                        hideFixed: q('hideFixed').checked, onlyMatched: q('onlyMatched').checked, onlyRelocated: q('onlyRelocated').checked });
  const count = () => { el.querySelector('.count').textContent = o.count ? o.count(get()) : ''; };
  fill(f); count();
  let t = 0;
  el.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => { set(read()); count(); }, 120); });
  q('reset').onclick = () => { fill(DEFAULT); set(DEFAULT); count(); };
  el.addEventListener('keydown', e => { if (e.key === 'Escape') { close(); anchor.focus(); } });
  document.body.append(el);
  const r = anchor.getBoundingClientRect(), w = el.offsetWidth, h = el.offsetHeight;
  el.style.left = Math.max(8, Math.min(innerWidth - w - 8, r.right - w)) + 'px';
  el.style.top = (r.bottom + 6 + h <= innerHeight - 8 ? r.bottom + 6 : Math.max(8, r.top - h - 6)) + 'px';
  const outside = e => { if (!el.contains(e.target) && !anchor.contains(e.target)) close(); };
  document.addEventListener('pointerdown', outside, true);
  anchor.setAttribute('aria-expanded', 'true');
  open = { el, anchor, outside };
  q('from').focus();
}

window.StratumQuakes = { get, set, active, pass, fromRow, mapFilter, describe, panel, close };
})();
