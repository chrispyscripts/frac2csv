// FracView — stage charts, in a window of their own. A stage clicked on a
// well's 2D view opens here; the next one is stacked underneath, or given a
// window of its own, as the user chooses (wellsection.js asks). Each card is
// the well charts page's stage chart (wellview.html?solo=1), so it zooms,
// pans, hides curves and follows the theme exactly as it does there.
//
// The stages are in the address (stages.html?s=WA:stage,WA:stage), so a reload
// or a saved session brings them back. The window says what it holds over
// BroadcastChannel 'stratum-stages', so a page choosing where a stage goes
// knows which stage windows are open, and finds this one by its name.
'use strict';
const ORIGIN = location.origin;
const $ = id => document.getElementById(id);
const ME = Math.random().toString(36).slice(2);
const MAX = 16;
const cards = [];        // {wa, label, el, frame, name, stages}
let used = Date.now();   // when this window was last added to or looked at

// a name another page can find this window by (window.open('', name))
if (!/^stratum-stages[a-z]*$/.test(window.name)) {
  window.name = 'stratum-stages' + Array.from({ length: 6 }, () => String.fromCharCode(97 + Math.floor(Math.random() * 26))).join('');
}

const parse = q => (q || '').split(',').map(x => x.trim()).filter(Boolean).map(x => {
  const i = x.indexOf(':');
  return i > 0 ? { wa: decodeURIComponent(x.slice(0, i)), label: decodeURIComponent(x.slice(i + 1)) } : null;
}).filter(Boolean);
const key = (wa, label) => String(wa) + ':' + String(label);
const chartsUrl = c => `wellview.html?wa=${encodeURIComponent(c.wa)}&stage=${encodeURIComponent(c.label)}`;

function make(wa, label) {
  const c = { wa: String(wa), label: String(label), name: '', stages: [] };
  const el = c.el = document.createElement('section');
  el.className = 'sg-card';
  el.innerHTML = `<div class="sg-card-h"><div class="sg-id"><div class="sg-title"></div><div class="sg-meta"></div></div>
    <div class="sg-acts"><div class="sg-step" role="group" aria-label="Step this card through the well's stages">
      <button type="button" class="sg-prev" aria-label="Previous stage">‹</button><button type="button" class="sg-next" aria-label="Next stage">›</button></div>
    <a class="sg-btn sg-charts" target="stratum-charts" title="This well's full charts: stage chart, Stacked and Sequential">Charts ↗</a>
    <button type="button" class="sg-up" title="Move this chart up">↑</button>
    <button type="button" class="sg-x" title="Close this chart" aria-label="Close this chart">×</button></div></div>
    <iframe title="Stage chart"></iframe>`;
  c.frame = el.querySelector('iframe');
  c.frame.src = `wellview.html?wa=${encodeURIComponent(c.wa)}&stage=${encodeURIComponent(c.label)}&solo=1`;
  el.querySelector('.sg-x').onclick = () => remove(c);
  el.querySelector('.sg-up').onclick = () => { const k = cards.indexOf(c); if (k > 0) { cards.splice(k, 1); cards.splice(k - 1, 0, c); place(); el.querySelector('.sg-up').focus(); } };
  const step = d => { const i = c.stages.indexOf(c.label), j = i + d; if (i >= 0 && j >= 0 && j < c.stages.length) c.frame.contentWindow.postMessage({ type: 'ws:select-stage', wa: c.wa, label: c.stages[j] }, ORIGIN); };
  el.querySelector('.sg-prev').onclick = () => step(-1);
  el.querySelector('.sg-next').onclick = () => step(1);
  head(c);
  return c;
}
function head(c) {
  const el = c.el, i = c.stages.indexOf(c.label);
  const t = el.querySelector('.sg-title');
  t.replaceChildren();
  const b = document.createElement('b'); b.textContent = `Stage ${c.label}`;
  const sp = document.createElement('span'); sp.textContent = ' · ' + (c.name || `WA ${c.wa}`);
  t.append(b, sp);
  el.querySelector('.sg-meta').textContent = [`WA ${c.wa}`, c.pad, c.stages.length ? `stage ${i + 1} of ${c.stages.length} with curves` : null].filter(Boolean).join(' · ');
  el.querySelector('.sg-prev').disabled = i <= 0;
  el.querySelector('.sg-next').disabled = i < 0 || i >= c.stages.length - 1;
  el.querySelector('.sg-charts').href = chartsUrl(c);
  el.setAttribute('aria-label', `Stage ${c.label}, ${c.name || 'WA ' + c.wa}`);
}
// a card's chart says what it shows: on load, and when it is stepped to another stage
addEventListener('message', e => {
  const m = e.data;
  if (e.origin !== ORIGIN || !m || m.type !== 'wc:solo') return;
  const c = cards.find(x => x.frame.contentWindow === e.source);
  if (!c) return;
  if (m.label != null) c.label = String(m.label);
  Object.assign(c, { name: m.name || '', pad: m.pad || '', date: m.date || '', stages: Array.isArray(m.stages) ? m.stages.map(String) : [] });
  head(c); save();
});

function place() {
  const list = $('sg-list');
  cards.forEach((c, i) => { list.append(c.el); c.el.querySelector('.sg-up').hidden = i === 0; });
  save();
}
function add(wa, label, quiet) {
  if (wa == null || label == null || label === '') return;
  used = Date.now();
  const here = cards.find(c => key(c.wa, c.label) === key(wa, label));
  if (here) { if (!quiet) flash(here); announce(); return; }
  if (cards.length >= MAX) { const old = cards.shift(); old.el.remove(); }
  const c = make(wa, label);
  cards.push(c);
  place();
  if (!quiet) flash(c);
}
function flash(c) {
  c.el.classList.remove('fresh'); void c.el.offsetWidth; c.el.classList.add('fresh');
  c.el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
function remove(c) {
  const k = cards.indexOf(c);
  if (k < 0) return;
  cards.splice(k, 1); c.el.remove(); place();
}

function save() {
  const parts = [cards.length ? 's=' + cards.map(c => encodeURIComponent(c.wa) + ':' + encodeURIComponent(c.label)).join(',') : ''];
  const q = new URLSearchParams(location.search); q.delete('s');
  if (String(q)) parts.push(String(q));
  history.replaceState(null, '', location.pathname + (parts.filter(Boolean).length ? '?' + parts.filter(Boolean).join('&') : ''));
  const n = cards.length;
  $('sg-empty').hidden = n > 0;
  const wells = new Set(cards.map(c => c.wa)).size;
  $('sg-sub').textContent = n ? `${n} stage${n > 1 ? 's' : ''}${wells > 1 ? ` from ${wells} wells` : ''} · newest at the bottom` : 'No stages yet';
  document.title = 'FracView — ' + (n === 1 ? `Stage ${cards[0].label} · ${cards[0].name || 'WA ' + cards[0].wa}` : `Stage charts${n ? ' · ' + n : ''}`);
  announce();
}

// ---------- telling the other windows what is here ----------
const chan = 'BroadcastChannel' in self ? new BroadcastChannel('stratum-stages') : null;
function announce() {
  if (chan) chan.postMessage({ type: 'here', id: ME, name: window.name, at: used,
    stages: cards.map(c => ({ wa: c.wa, label: c.label, name: c.name })) });
}
if (chan) chan.onmessage = e => {
  const m = e.data || {};
  if (m.type === 'ping') announce();
  else if (m.type === 'add' && m.to === ME) { add(m.wa, m.label); chan.postMessage({ type: 'added', rid: m.rid, id: ME }); }
};
addEventListener('focus', () => { used = Date.now(); announce(); });
addEventListener('pagehide', () => { if (chan) chan.postMessage({ type: 'bye', id: ME }); });

window.stratumStages = { add: (wa, label) => add(wa, label), list: () => cards.map(c => ({ wa: c.wa, label: c.label })) };
{
  // a page that reached this window while it was still loading left its stages here
  const queued = Array.isArray(window.stratumStageQueue) ? window.stratumStageQueue : [];
  parse(new URLSearchParams(location.search).get('s')).forEach(x => add(x.wa, x.label, true));
  queued.forEach(x => x && add(x.wa, x.label, true));
  save();
}
