// FracView — the Data window, in a window of its own (the map's Data window
// button opens it: data-window.js). The datasets of a well or a stage stacked
// along MD (stage-datasets.js, a solo stack per card):
//
//   the top card   the well or stage under the pointer on the map or in the 3D
//                  view, while "Follow the pointer" is on
//   a card each    for the wells and stages clicked there, stacked in the order
//                  picked, so several can be read one above the other
//
// Every card shows the same datasets: Add Dataset (or ↑ ↓ ×, or the stretch
// along the well) on any card changes them all, and they are kept in this
// browser. A dataset a well lacks shows as "not on file" in its place.
//
// The map and the 3D view talk to it over BroadcastChannel 'stratum-data':
//   in   {type: 'point' | 'pick' | 'unpick', wa, label, name}, {type: 'ping'}
//   out  {type: 'here', id, picks: [{wa, label}], follow}, {type: 'bye', id}
// The picks are in the address (datawindow.html?p=WA:stage,WA:), so a reload
// or a saved session brings them back.
//
//   localStorage stratum.dataWindow   {v, stack: {kinds, win, names}, follow}
'use strict';
(() => {
const KEY = 'stratum.dataWindow', MAX = 12;
const $ = id => document.getElementById(id);
const ME = Math.random().toString(36).slice(2);
let saved = {};
try { saved = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (e) { saved = {}; }
const keep = () => { try { localStorage.setItem(KEY, JSON.stringify({ ...saved, v: 1 })); } catch (e) { /* private mode: this window only */ } };
let STACK = saved.stack || null, follow = saved.follow !== false;
const list = $('dw-list');
const cards = [];          // {wa, label, name, el, ctl, live, m}
const key = (wa, label) => String(wa) + ':' + (label == null ? '' : String(label));
const fmt = (v, d = 0) => (v == null || !isFinite(v) ? '–' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));
const idOf = wa => (/^SK/.test(wa) ? 'Licence ' + wa.slice(2) : /^DR\d+-/.test(wa) ? 'from your file' : 'WA ' + wa);

// ---------- a card ----------
function card(o) {
  const c = { wa: o.wa == null ? '' : String(o.wa), label: o.label == null ? null : String(o.label), name: o.name || '', live: !!o.live, m: null };
  const el = c.el = document.createElement('section');
  el.className = 'sg-card dw-card' + (c.live ? ' dw-live' : '');
  el.innerHTML = `<div class="sg-card-h"><div class="sg-id"><div class="sg-title"></div><div class="sg-meta"></div></div><div class="sg-acts"></div></div><div class="dw-mount"></div>`;
  if (!c.live) {
    const x = document.createElement('button');
    x.type = 'button'; x.className = 'dw-x'; x.textContent = '×';
    x.addEventListener('click', () => unpick(c, true));
    el.querySelector('.sg-acts').append(x);
  }
  c.ctl = StageDatasets.attach({ solo: true, wa: c.wa || null, label: c.label, mount: el.querySelector('.dw-mount'), stack: STACK,
    onChange: s => shared(s, c), onLoad: m => { if (m.wa === c.wa) { c.m = m; title(c); } } });
  title(c);
  return c;
}
function title(c) {
  const t = c.el.querySelector('.sg-title'), meta = c.el.querySelector('.sg-meta');
  t.replaceChildren();
  if (c.live) { const k = document.createElement('span'); k.className = 'dw-tag'; k.textContent = 'Under the pointer'; t.append(k); }
  if (!c.wa) { meta.textContent = 'Point at a well on the map or in the 3D view, or at a stage once the map is zoomed in.'; return; }
  const name = (c.m && c.m.ok && c.m.name) || c.name || idOf(c.wa);
  const b = document.createElement('b'); b.textContent = name;
  const s = document.createElement('span'); s.textContent = c.label != null ? ` · stage ${c.label}` : ' · whole lateral';
  t.append(b, s);
  const st = c.m && c.label != null ? C().depthIn(c.m.lists || [], c.label) : null;
  meta.textContent = [idOf(c.wa), st ? (st.base - st.top > 0.5 ? `${fmt(st.top, 1)}–${fmt(st.base, 1)} m MD` : `${fmt(st.top, 1)} m MD`) : null,
    c.m && c.m.ok && c.m.td ? `TD ${fmt(c.m.td)} m` : null].filter(Boolean).join(' · ');
  const x = c.el.querySelector('.dw-x');
  if (x) { x.setAttribute('aria-label', `Take ${name}${c.label != null ? ' stage ' + c.label : ''} out of this window`); x.title = 'Take it out of this window'; }
}
const C = () => window.StageDatasetsCore;
// one stack for every card
function shared(s, from) {
  STACK = s; saved.stack = s; keep();
  for (const c of cards) if (c !== from) c.ctl.setStack(s);
}

// ---------- the top card: under the pointer ----------
const live = card({ live: true });
cards.push(live);
list.insertBefore(live.el, $('dw-empty'));
let pendT = 0;
function point(m) {
  if (!follow || m.wa == null) return;
  clearTimeout(pendT);
  // shown once the pointer rests a moment, so a sweep across the map reads no wells on the way
  pendT = setTimeout(() => {
    const wa = String(m.wa), label = m.label == null ? null : String(m.label);
    if (wa === live.wa && label === live.label) return;
    if (wa !== live.wa) { live.m = null; live.name = m.name || ''; }
    live.wa = wa; live.label = label;
    live.ctl.setTarget(wa, label);
    title(live);
  }, 140);
}

// ---------- picked wells and stages ----------
const picks = () => cards.filter(c => !c.live);
function pick(m, quiet) {
  if (m.wa == null) return;
  const k = key(m.wa, m.label), have = picks().find(c => key(c.wa, c.label) === k);
  if (have) { if (!quiet) flash(have); return; }
  while (picks().length >= MAX) unpick(picks()[0], false);
  const c = card({ wa: m.wa, label: m.label, name: m.name });
  cards.push(c);
  list.insertBefore(c.el, $('dw-empty'));
  if (!quiet) flash(c);
  sync();
}
function unpick(c, focus) {
  const i = cards.indexOf(c);
  if (i < 0 || c.live) return;
  const next = cards[i + 1] || cards[i - 1];
  c.ctl.destroy(); c.el.remove(); cards.splice(i, 1);
  sync();
  if (focus) { const b = next && (next.el.querySelector('.dw-x') || next.el.querySelector('.sd-add')); if (b) b.focus(); }
}
function flash(c) {
  c.el.classList.remove('fresh'); void c.el.offsetWidth; c.el.classList.add('fresh');
  c.el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

// ---------- the header, the address, the channel ----------
const chan = 'BroadcastChannel' in self ? new BroadcastChannel('stratum-data') : null;
function sync() {
  const P = picks();
  live.el.hidden = !follow;
  $('dw-follow').setAttribute('aria-pressed', String(follow));
  $('dw-follow').textContent = follow ? 'Following the pointer' : 'Follow the pointer';
  $('dw-clear').hidden = !P.length;
  $('dw-empty').hidden = follow || P.length > 0;
  $('dw-how').hidden = P.length > 0 || !follow;
  $('dw-sub').textContent = [follow ? 'the well or stage under the pointer' : null, P.length ? `${P.length} picked` : null].filter(Boolean).join(' · ') || 'nothing shown';
  const q = new URLSearchParams(location.search);
  if (P.length) q.set('p', P.map(c => encodeURIComponent(c.wa) + ':' + (c.label == null ? '' : encodeURIComponent(c.label))).join(',')); else q.delete('p');
  history.replaceState(history.state, '', location.pathname + (String(q) ? '?' + q : ''));
  document.title = P.length ? `FracView — Data window · ${P.length} picked` : 'FracView — Data window';
  here();
}
function here() { if (chan) chan.postMessage({ type: 'here', id: ME, picks: picks().map(c => ({ wa: c.wa, label: c.label })), follow }); }
if (chan) chan.onmessage = e => {
  const m = e.data || {};
  if (m.type === 'point') point(m);
  else if (m.type === 'pick') pick(m);
  else if (m.type === 'unpick') { const c = picks().find(x => key(x.wa, x.label) === key(m.wa, m.label)); if (c) unpick(c, false); }
  else if (m.type === 'ping') here();
};
addEventListener('pagehide', () => { if (chan) chan.postMessage({ type: 'bye', id: ME }); });
addEventListener('pageshow', e => { if (e.persisted) here(); });

$('dw-follow').addEventListener('click', () => { follow = !follow; saved.follow = follow; keep(); sync(); });
$('dw-clear').addEventListener('click', () => { for (const c of picks()) unpick(c, false); $('dw-follow').focus(); });

// the picks in the address (a reload, a saved session, or the map opening this window on one)
for (const x of (new URLSearchParams(location.search).get('p') || '').split(',').filter(Boolean)) {
  const i = x.indexOf(':');
  if (i <= 0) continue;
  const wa = decodeURIComponent(x.slice(0, i)), l = x.slice(i + 1);
  pick({ wa, label: l === '' ? null : decodeURIComponent(l) }, true);
}
sync();
window.stratumDataWin = { pick, point };
})();
