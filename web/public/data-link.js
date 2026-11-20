// FracView — a page's link to the Data window (datawindow.html, a window of its
// own named 'stratum-data'): which well or stage the pointer is on, and which
// were clicked, over BroadcastChannel 'stratum-data'. The map (data-window.js,
// with the 3D view) and the well section (wellsection.js) use it.
//
//   StratumDataLink.point(wa, label, name)        the pointer is over this well (label null) or stage
//   StratumDataLink.pick(wa, label, name, open)   a click: stacked in the Data window when one is open
//                                                  (open: opened on it, or brought forward, when asked)
//                                                  -> true, false (none open), or 'blocked' (a pop-up blocker)
//   StratumDataLink.open(pick)                    open the Data window (or bring it forward) -> 'blocked' or true
//   StratumDataLink.url(pick)                     its address, for a link
//   StratumDataLink.shown                         a Data window is open
//   StratumDataLink.picks                         [{wa, label}] stacked in the open Data windows
//   'stratum:datapicks' (window event)            either of those changed
(() => {
'use strict';
if (window.StratumDataLink) return;
const NAME = 'stratum-data', PAGE = 'datawindow.html', FEATURES = 'popup,width=900,height=960';
let chan = null;
try { chan = new BroadcastChannel(NAME); } catch (e) { /* an old browser: the window opens, but does not follow */ }
const wins = new Map();          // id -> {picks, follow}
let PICKS = [];
const alive = () => wins.size > 0;
function changed() {
  const seen = new Set();
  PICKS = [...wins.values()].flatMap(w => w.picks || []).filter(p => { const k = p.wa + ':' + p.label; if (seen.has(k)) return false; seen.add(k); return true; });
  dispatchEvent(new CustomEvent('stratum:datapicks', { detail: PICKS }));
}
if (chan) {
  chan.onmessage = e => {
    const m = e.data || {};
    if (m.type === 'here' && m.id) { wins.set(m.id, m); changed(); }
    else if (m.type === 'bye') { wins.delete(m.id); changed(); }
  };
  chan.postMessage({ type: 'ping' });
  addEventListener('focus', () => chan.postMessage({ type: 'ping' }));
}

const url = p => PAGE + (p ? '?p=' + encodeURIComponent(p.wa) + ':' + (p.label == null ? '' : encodeURIComponent(p.label)) : '');
const norm = (wa, label, name) => ({ wa: String(wa), label: label == null || label === '' ? null : String(label), name: name || '' });
function open(p) {
  let w = null;
  try {
    if (alive()) {
      // the open one, found by its name: brought forward (and told of the pick)
      w = window.open('', NAME, FEATURES);
      if (w && /^about:blank/.test(w.location.href)) w.location.href = url(p);
      else if (p && chan) chan.postMessage({ type: 'pick', ...p });
    } else w = window.open(url(p), NAME, FEATURES);
  } catch (e) { w = null; }
  if (!w) return 'blocked';
  try { w.focus(); } catch (e) { /* the browser decides */ }
  return true;
}
let lastPoint = '';
function point(wa, label, name) {
  if (!chan || !alive() || wa == null) return;
  const p = norm(wa, label, name), k = p.wa + ':' + (p.label == null ? '' : p.label);
  if (k === lastPoint) return;
  lastPoint = k;
  chan.postMessage({ type: 'point', ...p });
}
function pick(wa, label, name, openIt) {
  if (wa == null) return false;
  const p = norm(wa, label, name);
  if (openIt) return open(p);
  if (!chan || !alive()) return false;
  chan.postMessage({ type: 'pick', ...p });
  return true;
}
window.StratumDataLink = { point, pick, open, url, get shown() { return alive(); }, get picks() { return PICKS; } };
})();
