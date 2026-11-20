// FracView — the map's Data window button. It sits under the legend and opens
// the Data window in a window of its own (datawindow.html); data-link.js tells
// it which well or stage the pointer is on, here and in the 3D view
// (cluster-underground.js), and which were clicked: those are stacked there,
// a card each. The well section (wellsection.js) talks to it the same way.
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
const DL = window.StratumDataLink;
if (!DL) return;

// ---------- the button, under the legend (where Change View was) ----------
const btn = document.createElement('button');
btn.type = 'button'; btn.id = 'dw-open'; btn.className = 'dw-btn';
btn.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M3 6h18M3 12h18M3 18h18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M6 9.5l3-2 3 2.5 3-4 3 2" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" opacity=".55"/></svg><span>Data window</span><small></small>';
document.body.append(btn);
const note = document.createElement('div');
note.className = 'dw-note'; note.hidden = true; note.setAttribute('role', 'status');
document.body.append(note);
function btnWords() {
  const n = DL.picks.length;
  btn.querySelector('small').textContent = DL.shown ? (n ? `open · ${n} picked` : 'open') : '';
  btn.title = DL.shown ? 'Bring the Data window forward. Click wells or stages on the map, in the 3D view or in the well section to stack them there.'
    : 'Open the Data window: the datasets of the well or stage under the pointer, and of each one you click, stacked along the well (gamma, porosity, the mud log, comments…)';
}
btnWords();
addEventListener('stratum:datapicks', btnWords);
const legend = document.querySelector('.legend');
function placeBtn() {
  if (!legend) return;
  const r = legend.getBoundingClientRect();
  btn.style.top = (r.bottom + 10) + 'px'; btn.style.width = Math.max(150, r.width) + 'px';
  note.style.top = (r.bottom + 56) + 'px'; note.style.width = Math.max(150, r.width) + 'px';
}
placeBtn(); addEventListener('resize', placeBtn);
if (legend && 'ResizeObserver' in window) new ResizeObserver(placeBtn).observe(legend);

// a pop-up blocker: a link to open it instead
function blocked(p) {
  note.replaceChildren();
  const a = document.createElement('a'); a.href = DL.url(p); a.target = 'stratum-data'; a.textContent = 'Open it';
  const x = document.createElement('button'); x.type = 'button'; x.textContent = '×'; x.setAttribute('aria-label', 'Dismiss'); x.onclick = () => { note.hidden = true; };
  note.append('Your browser blocked the Data window. ', a, x);
  note.hidden = false;
}
function openWin(p) { if (DL.open(p) === 'blocked') blocked(p); else note.hidden = true; }
btn.addEventListener('click', () => openWin(null));

function pick(wa, label, name, open) {
  const r = DL.pick(wa, label, name, open);
  if (r === 'blocked') { blocked({ wa: String(wa), label: label == null ? null : String(label) }); return false; }
  if (open) note.hidden = true;
  return r;
}
window.stratumDataWindow = { point: DL.point, pick, open: () => openWin(null), get shown() { return DL.shown; }, get picks() { return DL.picks; } };
})();
