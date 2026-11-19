// FracView — the map's Data window: the datasets of the well or stage under
// the pointer, stacked along MD (stage-datasets.js, as a solo stack). Its
// button sits under the legend. The stack is built with Add Dataset as on the
// stage charts page (gamma, porosity, the mud log, curves, comments) and kept
// in this browser; it stays as the pointer moves from well to well, and a
// dataset a well lacks shows as "not on file" in its place.
//
// Pointing at a well shows its lateral; at a stage (zoomed in, map-stages.js)
// the stretch around it. Clicking a well or a stage holds the window on it
// until "Follow the pointer". The window can be dragged by its title.
//
//   localStorage stratum.dataWindow   {v, open, stack: {kinds, win, names}, last: {wa, label}, pos: {x, y}}
//
//   stratumDataWindow.point(wa, label)        the pointer is over this well (label null) or stage
//   stratumDataWindow.hold(wa, label, open)   a click: the window stays on it (open: and opens)
(() => {
'use strict';
if (!window.StageDatasets || typeof map === 'undefined') return;
const KEY = 'stratum.dataWindow';
let saved = {};
try { saved = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (e) { saved = {}; }
const keep = () => { try { localStorage.setItem(KEY, JSON.stringify({ ...saved, v: 1 })); } catch (e) { /* private mode: this page only */ } };
const wellOf = wa => { try { return (typeof WELL_BY_WA !== 'undefined' && WELL_BY_WA[wa]) || null; } catch (e) { return null; } };

// ---------- the button, under the legend ----------
const btn = document.createElement('button');
btn.type = 'button'; btn.id = 'dw-open'; btn.className = 'dw-btn';
btn.setAttribute('aria-controls', 'dw'); btn.setAttribute('aria-expanded', 'false');
btn.title = 'The datasets of the well or stage under the pointer, stacked along the well: gamma, porosity, the mud log, comments…';
btn.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M3 6h18M3 12h18M3 18h18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M6 9.5l3-2 3 2.5 3-4 3 2" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" opacity=".55"/></svg><span>Data window</span>';
document.body.append(btn);

// ---------- the window ----------
const box = document.createElement('section');
box.id = 'dw'; box.className = 'dw'; box.hidden = true;
box.setAttribute('role', 'region'); box.setAttribute('aria-label', 'Data window');
box.innerHTML = `<header class="dw-h" title="Drag to move the window">
    <div class="dw-id"><b class="dw-t">Data window</b><span class="dw-s"></span></div>
    <button type="button" class="dw-follow" hidden title="Show whichever well or stage the pointer is over again">Follow the pointer</button>
    <button type="button" class="dw-x" aria-label="Close the Data window" title="Close">×</button></header>
  <p class="dw-hint"></p>
  <div class="dw-body"></div>`;
document.body.append(box);
const sub = box.querySelector('.dw-s'), hint = box.querySelector('.dw-hint'), follow = box.querySelector('.dw-follow');
const ctl = StageDatasets.attach({ solo: true, mount: box.querySelector('.dw-body'), stack: saved.stack,
  onChange: s => { saved.stack = s; keep(); words(); } });

let held = false, cur = null, pendT = 0;
function words() {
  const w = cur && wellOf(cur.wa), n = (saved.stack && saved.stack.kinds.length) || 0;
  sub.textContent = !cur ? '' : [w ? w.name : cur.wa, cur.label != null ? `stage ${cur.label}` : 'lateral'].join(' · ') + (held ? ' · held' : '');
  follow.hidden = !held;
  hint.textContent = !cur ? (n ? 'Point at a well on the map, or at a stage once zoomed in.' : 'Point at a well on the map, or at a stage once zoomed in, then Add Dataset to stack its gamma, porosity, mud log, comments…')
    : !n ? 'Add Dataset to stack this well’s gamma, porosity, mud log, comments… They stay as you move from well to well.' : '';
  hint.hidden = !hint.textContent;
}
function show(wa, label) {
  if (wa == null) return;
  cur = { wa: String(wa), label: label == null ? null : String(label) };
  ctl.setTarget(cur.wa, cur.label);
  saved.last = cur; keep();
  words();
}
// the pointer: shown once it rests a moment, so sweeping across the map reads no wells on the way
function point(wa, label) {
  if (held || wa == null) return;
  if (cur && cur.wa === String(wa) && cur.label === (label == null ? null : String(label))) { clearTimeout(pendT); return; }
  clearTimeout(pendT);
  if (box.hidden) { cur = { wa: String(wa), label: label == null ? null : String(label) }; saved.last = cur; return; }
  pendT = setTimeout(() => show(wa, label), 140);
}
function hold(wa, label, open) {
  if (open && box.hidden) setOpen(true);
  if (box.hidden) return;
  clearTimeout(pendT);
  held = true;
  show(wa, label);
}
follow.addEventListener('click', () => { held = false; words(); box.querySelector('.dw-x').focus(); });

function setOpen(on) {
  box.hidden = !on; btn.hidden = on;
  btn.setAttribute('aria-expanded', String(on));
  saved.open = on; keep();
  document.body.classList.toggle('dw-on', on);
  if (on) {
    place();
    words();
    // the last well shown, once the map has its own data in (it is read after the map's, not beside it)
    const go = () => { const last = cur || saved.last; if (!box.hidden && last && last.wa && !(cur && ctl.target.wa === cur.wa)) show(last.wa, last.label); };
    if (typeof afterLayers === 'function') afterLayers(go); else go();
  }
}
btn.addEventListener('click', () => { setOpen(true); box.querySelector('.dw-x').focus(); });
box.querySelector('.dw-x').addEventListener('click', () => { setOpen(false); held = false; btn.focus(); });
box.addEventListener('keydown', e => { if (e.key === 'Escape' && !e.target.closest('.sd-pick, canvas')) { setOpen(false); held = false; btn.focus(); } });

// ---------- where it sits ----------
// the button: under the legend, as wide as it. The window: where it was
// dragged to, else beside the legend (or under it, on a narrow screen)
const legend = document.querySelector('.legend');
function placeBtn() {
  if (!legend) return;
  const r = legend.getBoundingClientRect();
  btn.style.top = (r.bottom + 10) + 'px';
  btn.style.width = Math.max(150, r.width) + 'px';
}
function place() {
  if (box.hidden) return;
  const W = innerWidth, H = innerHeight, phone = W <= 640;
  box.classList.toggle('dw-sheet', phone);
  if (phone) { box.style.left = box.style.top = box.style.right = ''; return; }
  const w = Math.min(500, W - 24);
  box.style.width = w + 'px';
  let x, y;
  if (saved.pos && isFinite(saved.pos.x) && isFinite(saved.pos.y)) { x = saved.pos.x; y = saved.pos.y; }
  else {
    const r = legend ? legend.getBoundingClientRect() : { left: W - 12, bottom: 12, width: 0 };
    const side = document.querySelector('.side'), sr = side ? side.getBoundingClientRect().right : 0;
    if (r.left - 12 - w >= sr + 12) { x = r.left - 12 - w; y = 12; }       // beside the legend
    else { x = W - 12 - w; y = Math.min(r.bottom + 10, H - 360); }          // under it
  }
  x = Math.max(8, Math.min(W - w - 8, x)); y = Math.max(8, Math.min(H - 120, y));
  box.style.left = x + 'px'; box.style.top = y + 'px'; box.style.right = 'auto';
  box.style.setProperty('--dw-top', y + 'px');
}
placeBtn(); addEventListener('resize', () => { placeBtn(); place(); });
if (legend && 'ResizeObserver' in window) new ResizeObserver(placeBtn).observe(legend);

// dragged by its title
{
  const h = box.querySelector('.dw-h');
  let drag = null;
  h.addEventListener('pointerdown', e => {
    if (e.button !== 0 || e.target.closest('button') || box.classList.contains('dw-sheet')) return;
    const r = box.getBoundingClientRect();
    drag = { dx: e.clientX - r.left, dy: e.clientY - r.top };
    h.setPointerCapture(e.pointerId); box.classList.add('dw-drag');
  });
  h.addEventListener('pointermove', e => {
    if (!drag) return;
    const w = box.offsetWidth;
    const x = Math.max(8, Math.min(innerWidth - w - 8, e.clientX - drag.dx)), y = Math.max(8, Math.min(innerHeight - 120, e.clientY - drag.dy));
    box.style.left = x + 'px'; box.style.top = y + 'px'; box.style.setProperty('--dw-top', y + 'px');
  });
  const end = () => { if (!drag) return; drag = null; box.classList.remove('dw-drag'); saved.pos = { x: parseFloat(box.style.left), y: parseFloat(box.style.top) }; keep(); };
  h.addEventListener('pointerup', end); h.addEventListener('pointercancel', end);
  // a double-click puts it back where it starts
  h.addEventListener('dblclick', e => { if (e.target.closest('button')) return; delete saved.pos; keep(); place(); });
}

if (saved.open) setOpen(true); else words();
window.stratumDataWindow = { point, hold, open: () => setOpen(true), get shown() { return !box.hidden; } };
})();
