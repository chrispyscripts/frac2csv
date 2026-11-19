// FracView — the map's Data window button. It sits under the legend and opens
// the Data window in a window of its own (datawindow.html), then tells it over
// BroadcastChannel 'stratum-data' which well or stage the pointer is on, here
// and in the 3D view (cluster-underground.js), and which were clicked: those
// are stacked there, a card each.
//
//   stratumDataWindow.point(wa, label, name)        the pointer is over this well (label null) or stage
//   stratumDataWindow.pick(wa, label, name, open)   a click: stacked in the Data window when one is open
//                                                    (open: opened on it when none is)
//   stratumDataWindow.open()                         the button
//   stratumDataWindow.shown                          a Data window is open
//   stratumDataWindow.picks                          [{wa, label}] stacked in the open Data windows
//   'stratum:datapicks' (window event)               the picks changed
(() => {
'use strict';
const NAME = 'stratum-data', PAGE = 'datawindow.html', FEATURES = 'popup,width=900,height=960';
let chan = null;
try { chan = new BroadcastChannel(NAME); } catch (e) { /* an old browser: the window opens, but does not follow */ }
const wins = new Map();          // id -> {picks, follow}
let PICKS = [];
const alive = () => wins.size > 0;
const changed = () => {
  const seen = new Set();
  PICKS = [...wins.values()].flatMap(w => w.picks || []).filter(p => { const k = p.wa + ':' + p.label; if (seen.has(k)) return false; seen.add(k); return true; });
  btnWords();
  dispatchEvent(new CustomEvent('stratum:datapicks', { detail: PICKS }));
};
if (chan) {
  chan.onmessage = e => {
    const m = e.data || {};
    if (m.type === 'here' && m.id) { wins.set(m.id, m); changed(); }
    else if (m.type === 'bye') { wins.delete(m.id); changed(); }
  };
  chan.postMessage({ type: 'ping' });
  addEventListener('focus', () => chan.postMessage({ type: 'ping' }));
}

// ---------- the button, under the legend (where Change View was) ----------
const btn = document.createElement('button');
btn.type = 'button'; btn.id = 'dw-open'; btn.className = 'dw-btn';
btn.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M3 6h18M3 12h18M3 18h18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M6 9.5l3-2 3 2.5 3-4 3 2" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" opacity=".55"/></svg><span>Data window</span><small></small>';
document.body.append(btn);
const note = document.createElement('div');
note.className = 'dw-note'; note.hidden = true; note.setAttribute('role', 'status');
document.body.append(note);
function btnWords() {
  btn.querySelector('small').textContent = alive() ? (PICKS.length ? `open · ${PICKS.length} picked` : 'open') : '';
  btn.title = alive() ? 'Bring the Data window forward. Click wells or stages on the map or in the 3D view to stack them there.'
    : 'Open the Data window: the datasets of the well or stage under the pointer, and of each one you click, stacked along the well (gamma, porosity, the mud log, comments…)';
}
btnWords();
const legend = document.querySelector('.legend');
function placeBtn() {
  if (!legend) return;
  const r = legend.getBoundingClientRect();
  btn.style.top = (r.bottom + 10) + 'px'; btn.style.width = Math.max(150, r.width) + 'px';
  note.style.top = (r.bottom + 56) + 'px'; note.style.width = Math.max(150, r.width) + 'px';
}
placeBtn(); addEventListener('resize', placeBtn);
if (legend && 'ResizeObserver' in window) new ResizeObserver(placeBtn).observe(legend);

// ---------- the window ----------
const urlFor = p => PAGE + (p ? '?p=' + encodeURIComponent(p.wa) + ':' + (p.label == null ? '' : encodeURIComponent(p.label)) : '');
function openWin(p) {
  let w = null;
  try {
    if (alive()) {
      // the open one, found by its name: brought forward (and told of the pick)
      w = window.open('', NAME, FEATURES);
      if (w && /^about:blank/.test(w.location.href)) w.location.href = urlFor(p);
      else if (p && chan) chan.postMessage({ type: 'pick', ...p });
    } else w = window.open(urlFor(p), NAME, FEATURES);
  } catch (e) { w = null; }
  if (w) { try { w.focus(); } catch (e) { /* the browser decides */ } note.hidden = true; return; }
  note.replaceChildren();
  const a = document.createElement('a'); a.href = urlFor(p); a.target = NAME; a.textContent = 'Open it';
  const x = document.createElement('button'); x.type = 'button'; x.textContent = '×'; x.setAttribute('aria-label', 'Dismiss'); x.onclick = () => { note.hidden = true; };
  note.append('Your browser blocked the Data window. ', a, x);
  note.hidden = false;
}
btn.addEventListener('click', () => openWin(null));

let lastPoint = '';
function point(wa, label, name) {
  if (!chan || !alive() || wa == null) return;
  const k = wa + ':' + (label == null ? '' : label);
  if (k === lastPoint) return;
  lastPoint = k;
  chan.postMessage({ type: 'point', wa: String(wa), label: label == null ? null : String(label), name: name || '' });
}
function pick(wa, label, name, open) {
  if (wa == null) return false;
  const p = { wa: String(wa), label: label == null ? null : String(label), name: name || '' };
  if (open) { openWin(p); return true; }
  if (!chan || !alive()) return false;
  chan.postMessage({ type: 'pick', ...p });
  return true;
}
window.stratumDataWindow = { point, pick, open: () => openWin(null), get shown() { return alive(); }, get picks() { return PICKS; } };
})();
