// Group mode, on the map: pick pads into a group of your own. Point at a pad
// (or any of its wells) and it lights up; click to put it in the group or take
// it out; "Add the pads in view" takes everything on screen. Saved groups live
// with the account (menu.js saveGroup, /api/mine?k=groups) and are under
// Menu › Groups, where they open on the map, in 3D or as wine racks.
//
// Started from the legend's Group mode button, from Groups (new, or "Change
// pads on the map" for one of your own), or by the menu from another page.
(() => {
'use strict';
let on = false, sel = new Set(), editing = null, saved = '', bar = null;
const $ = (s, el = document) => el.querySelector(s);
const toggleBtn = document.getElementById('gm-toggle');

function paint() {
  if (map.getLayer('pads-gm')) map.setFilter('pads-gm', ['in', ['get', 'id'], ['literal', [...sel]]]);
  if (!bar) return;
  const pads = [...sel].map(id => PAD_BY_ID[id] || PAD_INFO[id]).filter(Boolean);
  const wells = pads.reduce((n, p) => n + (Array.isArray(p.wells) ? p.wells.length : p.wells || 0), 0);
  $('.gm-count', bar).textContent = sel.size ? `${sel.size} pad${sel.size === 1 ? '' : 's'} · ${wells.toLocaleString()} wells` : 'no pads yet';
  $('[data-gm=save]', bar).disabled = !sel.size;
  $('[data-gm=clear]', bar).disabled = !sel.size;
}
const state = () => JSON.stringify([[...sel].sort(), $('input', bar) ? $('input', bar).value.trim() : '']);

function start(g = {}) {
  if (on) stop(true);
  on = true;
  editing = g && g.id ? g : null;
  sel = new Set((g && g.pads) || []);
  document.body.classList.add('group-mode');
  if (toggleBtn) toggleBtn.setAttribute('aria-pressed', 'true');
  if (window.stratumMapShow) stratumMapShow.clear();
  if (typeof popup !== 'undefined' && popup) popup.remove();
  bar = document.createElement('div');
  bar.className = 'gm-bar'; bar.setAttribute('role', 'region'); bar.setAttribute('aria-label', 'Group mode');
  bar.innerHTML = `<b></b><span class="gm-count"></span>
    <input type="text" maxlength="80" placeholder="Name the group" aria-label="Group name">
    <button type="button" data-gm="view">Add the pads in view</button>
    <button type="button" data-gm="clear">Clear</button>
    <button type="button" class="go" data-gm="save">Save group</button>
    <button type="button" data-gm="done">Done</button>
    <div class="gm-msg" role="status"></div>`;
  $('b', bar).textContent = editing ? `Group mode · changing “${editing.name}”` : 'Group mode · click pads to add them, or take them out';
  $('input', bar).value = editing ? editing.name : (g && g.name) || '';
  $('[data-gm=view]', bar).onclick = addInView;
  $('[data-gm=clear]', bar).onclick = () => { sel.clear(); paint(); };
  $('[data-gm=save]', bar).onclick = save;
  $('[data-gm=done]', bar).onclick = () => stop(false);
  $('input', bar).onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); save(); } };
  document.body.append(bar);
  saved = state();
  paint();
  // fit the group being changed
  if (sel.size) {
    const b = new maplibregl.LngLatBounds();
    sel.forEach(id => { const p = PAD_BY_ID[id] || PAD_INFO[id]; if (p) b.extend([p.lon, p.lat]); });
    if (!b.isEmpty()) map.fitBounds(b, { padding: 120, maxZoom: 13, duration: 500 });
  }
  $('input', bar).focus();
}
function stop(quiet) {
  if (!on) return;
  if (!quiet && sel.size && state() !== saved && !confirm('Leave Group mode without saving this group?')) return;
  on = false; sel.clear(); editing = null;
  document.body.classList.remove('group-mode');
  if (toggleBtn) toggleBtn.setAttribute('aria-pressed', 'false');
  if (bar) { bar.remove(); bar = null; }
  paint();
}
function pick(id) {
  if (!on || !id) return;
  if (sel.has(id)) sel.delete(id); else sel.add(id);
  $('.gm-msg', bar).textContent = '';
  paint();
}
function addInView() {
  const b = map.getBounds();
  let n = 0;
  for (const S of SETS) for (const p of S.pads) if (b.contains([p.lon, p.lat]) && !sel.has(p.id)) { sel.add(p.id); n++; }
  $('.gm-msg', bar).textContent = n ? `Added ${n} pad${n === 1 ? '' : 's'} in view.` : 'Every pad in view is in the group already.';
  paint();
}
async function save() {
  const msg = $('.gm-msg', bar), name = $('input', bar).value.trim();
  if (!sel.size) return;
  if (!name) { msg.textContent = 'Give the group a name first.'; $('input', bar).focus(); return; }
  if (!window.StratumMenu) { msg.textContent = 'Groups are not available on this page.'; return; }
  $('[data-gm=save]', bar).disabled = true; msg.textContent = 'Saving…';
  try {
    const g = await StratumMenu.saveGroup({ id: editing ? editing.id : undefined, name, pads: [...sel], note: editing ? editing.note || '' : '' });
    editing = g; saved = state();
    $('b', bar).textContent = `Group mode · changing “${g.name}”`;
    msg.innerHTML = `Saved “<span></span>” with your groups. <button type="button">See it in Groups</button>`;
    msg.querySelector('span').textContent = g.name;
    msg.querySelector('button').onclick = () => { stop(true); StratumMenu.open('groups', { id: g.id }); };
  } catch (e) { msg.textContent = e.message; }
  $('[data-gm=save]', bar).disabled = !sel.size;
}
if (toggleBtn) toggleBtn.addEventListener('click', () => { if (on) stop(false); else start({}); });
addEventListener('keydown', e => { if (on && e.key === 'Escape' && !document.querySelector('.fvm:not([hidden])')) stop(false); });

window.stratumGroupMode = { start, stop: () => stop(false), pick, active: () => on, picked: () => [...sel] };
})();
