// FracView's main menu: one full-screen place to start from and come back to,
// over whichever page opened it (☰ Menu; Sessions opens it on Sessions).
//
//   Home       where to go next: the map, recent sessions, your groups
//   Sessions   the account's saved sessions: a list on the left; on the right the
//              windows each one opens, as they sat on screen, and what each shows
//   Groups     pads gathered under a name: the prepared areas, and the person's
//              own (made with Group mode on the map, or from Discover's results)
//   Discover   tools for finding wells by what was done to them (discover.js)
//   Settings   theme, text size, gamma colours, the quake filter, the map's and
//              the well section's defaults; they follow the account (account.js)
//
// A thing to show on the map goes to the map in place when this is the map,
// and by its address otherwise (map.html?pads=…, or a hand-off in
// sessionStorage for long lists: see stratumMapShow in map.html).
(() => {
'use strict';
if (window.top !== window) return;               // never inside a frame

const h = (tag, props, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v; else if (k === 'text') e.textContent = v; else if (k === 'html') e.innerHTML = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v); else if (k in e && typeof v !== 'string') e[k] = v; else e.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) e.append(k);
  return e;
};
const fmt = (v, d = 0) => v == null || !isFinite(v) ? '–' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d });
const when = iso => { const d = new Date(iso); return isNaN(d) ? '' : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }); };
const parse = s => { try { return JSON.parse(s); } catch (e) { return null; } };
const store = { get: k => { try { return localStorage.getItem(k); } catch (e) { return null; } },
                set: (k, v) => { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* private mode */ } } };
const prefsChanged = () => window.dispatchEvent(new CustomEvent('stratum:prefs'));
const onMap = () => /\/map(\.html)?$/.test(location.pathname) && !!window.stratumMapShow;

const ICON = {
  home: '<path d="M3 11.5 12 4l9 7.5M5.5 9.8V20h4.8v-5.6h3.4V20h4.8V9.8" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>',
  map: '<path d="M9 4 3 6.5v13.5l6-2.5 6 2.5 6-2.5V4l-6 2.5L9 4Zm0 0v13.5m6-11v13.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>',
  sessions: '<rect x="3" y="5" width="13" height="10" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M8 19h12V9" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>',
  groups: '<circle cx="7" cy="8" r="2.6" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="17" cy="8" r="2.6" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="12" cy="16.5" r="2.6" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M4 4h16v16H4z" fill="none" stroke="currentColor" stroke-width="1.2" stroke-dasharray="2.5 2.5"/>',
  discover: '<circle cx="10.5" cy="10.5" r="6" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="m15 15 5.5 5.5M8 12.5l2-4 2 3 1.5-2" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
  settings: '<circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M12 2.8v2.6M12 18.6v2.6M2.8 12h2.6M18.6 12h2.6M5.5 5.5l1.8 1.8M16.7 16.7l1.8 1.8M5.5 18.5l1.8-1.8M16.7 7.3l1.8-1.8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
};
const svgIcon = k => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[k]}</svg>`;
const SCREENS = [['home', 'Home'], ['sessions', 'Sessions'], ['groups', 'Groups'], ['discover', 'Discover'], ['settings', 'Settings']];

// ---------- shared data ----------
let regionP = null, presetsP = null;
const region = () => regionP || (regionP = fetch('data/region/index.json').then(r => r.ok ? r.json() : { pads: [] }).catch(() => ({ pads: [] })));
const padsById = () => region().then(d => new Map((d.pads || []).map(p => [p.id, p])));
const presets = () => presetsP || (presetsP = fetch('data/region/featured.json').then(r => r.ok ? r.json() : { areas: [] })
  .then(d => (d.areas || []).map(a => ({ id: 'preset:' + a.name, name: a.name, note: a.blurb || '', pads: a.pads, preset: true }))).catch(() => []));
async function mine(kind, body) {
  let r;
  try {
    r = await fetch('/api/mine?k=' + kind, body ? { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
                                               : { credentials: 'same-origin', cache: 'no-store' });
  } catch (e) { throw Error('That could not be reached. Check the connection and try again.'); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw Error(j.error || (r.status === 401 ? 'Sign in again first.' : 'That could not be reached. Try again in a moment.'));
  return j;
}
let groupsCache = null;
const myGroups = fresh => (!fresh && groupsCache) ? Promise.resolve(groupsCache) : mine('groups').then(j => (groupsCache = j.groups || []));
async function saveGroup(g) { const j = await mine('groups', { action: 'save', group: g }); groupsCache = j.groups || []; return j.group; }
async function deleteGroup(id) { const j = await mine('groups', { action: 'delete', id }); groupsCache = j.groups || []; }

// ---------- to the map ----------
// here when this is the map; otherwise the map is told by its address, or by a
// hand-off in its window's sessionStorage when the list is long
function toMap(show) {
  if (onMap()) { close(); window.stratumMapShow.apply(show); return; }
  let target = window;
  try { if (window.opener && !window.opener.closed && /\/map(\.html)?$/.test(window.opener.location.pathname)) target = window.opener; } catch (e) { /* not ours */ }
  try { target.sessionStorage.setItem('fv.show', JSON.stringify(show)); } catch (e) { /* private mode */ }
  target.location.href = 'map.html?show=1';
  if (target !== window) { try { target.focus(); } catch (e) { /* the browser decides */ } close(); }
}

// ---------- the frame ----------
let root = null, main = null, current = null, lastFocus = null;
function build() {
  if (root) return;
  if (!document.querySelector('link[href="menu.css"]')) document.head.append(h('link', { rel: 'stylesheet', href: 'menu.css' }));
  const nav = h('nav', { 'aria-label': 'Menu' }, SCREENS.map(([k, label]) =>
    h('button', { type: 'button', 'data-screen': k, html: svgIcon(k) + `<span>${label}</span>`, onclick: () => show(k) })));
  const back = h('button', { type: 'button', class: 'fvm-back go', text: onMap() ? 'Back to the map' : 'Back', onclick: close });
  const who = h('div', { class: 'fvm-who' });
  main = h('main', { class: 'fvm-main' });
  root = h('div', { class: 'fvm', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'FracView menu', hidden: true },
    h('aside', { class: 'fvm-nav' }, h('div', { class: 'fvm-brand', html: '<i></i>FracView' }), nav, h('div', { class: 'fvm-navfoot' }, back, who)),
    main);
  root.addEventListener('keydown', e => { if (e.key === 'Escape' && !e.target.closest('input,select,textarea')) { e.preventDefault(); close(); } });
  document.body.append(root);
  const setWho = () => { const u = window.stratumUser; who.textContent = u ? `${u.name} · ${u.email}` : ''; };
  setWho(); addEventListener('stratum:user', setWho);
}
function open(which = 'home', opts) {
  build();
  if (root.hidden) lastFocus = document.activeElement;
  root.hidden = false;
  document.documentElement.classList.add('fv-menu-open');
  show(which, opts);
}
function close() {
  if (!root || root.hidden) return;
  root.hidden = true;
  document.documentElement.classList.remove('fv-menu-open');
  hideTip();
  if (lastFocus && lastFocus.focus) try { lastFocus.focus(); } catch (e) { /* gone */ }
}
function show(which, opts = {}) {
  current = which;
  root.querySelectorAll('[data-screen]').forEach(b => b.setAttribute('aria-current', b.dataset.screen === which ? 'page' : 'false'));
  main.replaceChildren();
  main.scrollTop = 0;
  ({ home, sessions, groups, discover, settings }[which] || home)(opts);
  const first = main.querySelector('h1');
  if (first) { first.tabIndex = -1; first.focus({ preventScroll: true }); }
}

// a small floating note for charts and tables
let tipEl = null;
function tip(e, lines) {
  if (!tipEl) { tipEl = h('div', { class: 'fvm-tip', hidden: true }); document.body.append(tipEl); }
  tipEl.replaceChildren(...lines.filter(Boolean).map(([t, b]) => h(b ? 'b' : 'div', { text: t })));
  tipEl.hidden = false;
  const w = tipEl.offsetWidth, hh = tipEl.offsetHeight;
  tipEl.style.left = Math.max(6, Math.min(innerWidth - w - 8, e.clientX + 14)) + 'px';
  tipEl.style.top = (e.clientY + 16 + hh > innerHeight - 6 ? e.clientY - hh - 10 : e.clientY + 16) + 'px';
}
function hideTip() { if (tipEl) tipEl.hidden = true; }

// ---------- Home ----------
function home() {
  const u = window.stratumUser, hr = new Date().getHours();
  const hello = (hr < 12 ? 'Good morning' : hr < 18 ? 'Good afternoon' : 'Good evening') + (u && u.name ? ', ' + u.name.split(/\s+/)[0] : '');
  const sub = h('p', { class: 'fvm-sub', text: 'Northeast BC frac completions, from the BC Energy Regulator’s public filings and the Lab’s read of the treatment reports.' });
  region().then(d => { const ps = d.pads || []; sub.textContent = `${fmt(ps.length)} pads · ${fmt(ps.reduce((n, p) => n + (p.wells || 0), 0))} wells · ${fmt(ps.reduce((n, p) => n + (p.curves || 0), 0))} with treatment curves, within ${d.radius_km || 100} km of Gundy`; });
  const tile = (k, title, text, act, lead) => {
    const b = h('button', { type: 'button', class: 'fvm-tile' + (lead ? ' lead' : ''), onclick: act, html: svgIcon(k) }, h('b', { text: title }), h('span', { text }));
    const em = h('em'); b.append(em); return { b, em };
  };
  const tMap = tile('map', onMap() ? 'Continue to the map' : 'The map', 'Pads and laterals on the surface; zoom in for the 3D view, wine racks and each well in 2D.', () => onMap() ? close() : (location.href = 'map.html'), true);
  const tS = tile('sessions', 'Sessions', 'Every window you had open, saved under a name, opened again where it was.', () => show('sessions'));
  const tG = tile('groups', 'Groups', 'Pads gathered under a name: the prepared areas and your own.', () => show('groups'));
  const tD = tile('discover', 'Discover', 'Find wells by what was pumped, how they produced, their spacing and the earthquakes at their stages.', () => show('discover'));
  const tSet = tile('settings', 'Settings', 'Light or dark, text size, gamma colours, the earthquake filter, defaults.', () => show('settings'));
  tMap.em.textContent = onMap() ? 'Esc closes this menu' : '';
  tSet.em.textContent = `${store.get('stratum.theme') === 'dark' ? 'Dark' : 'Light'} · text ${({ s: 'small', m: 'default', l: 'large', xl: 'extra large' })[store.get('stratum.textSize') || 'm'] || 'default'}`;
  const recent = h('ul', { class: 'fvm-recent' }, h('li', { class: 'fvm-empty', text: 'Loading your sessions…' }));
  const chips = h('div', { class: 'fvm-chips' });
  const title = h('h1', { text: hello });
  // the name arrives with the account, which may be after this opened
  if (!u) addEventListener('stratum:user', e => { if (current === 'home' && e.detail && e.detail.name) title.textContent += ', ' + e.detail.name.split(/\s+/)[0]; }, { once: true });
  main.append(h('div', { class: 'fvm-screen' },
    title, sub,
    h('div', { class: 'fvm-tiles' }, tMap.b, tS.b, tG.b, tD.b, tSet.b),
    h('div', { class: 'fvm-row' },
      h('div', { class: 'fvm-card' }, h('h2', { text: 'Recent sessions' }), recent),
      h('div', { class: 'fvm-card' }, h('h2', { text: 'Groups' }), chips))));
  if (window.StratumSession && StratumSession.list) StratumSession.list().then(items => {
    tS.em.textContent = items.length ? `${items.length} saved · latest ${when(items[0].saved)}` : 'None saved yet';
    recent.replaceChildren(...(items.length ? items.slice(0, 4).map(x => h('li', null,
      h('div', { class: 'what' }, h('b', { text: x.name }), h('span', { text: [when(x.saved), x.area, `${x.windows} window${x.windows > 1 ? 's' : ''}`].filter(Boolean).join(' · ') })),
      h('button', { type: 'button', class: 'go', text: 'Open', onclick: e => openSession(x.id, e.currentTarget) }))) :
      [h('li', { class: 'fvm-empty', text: 'Nothing saved yet. Open Sessions to save the windows you have open.' })]));
  }).catch(e => recent.replaceChildren(h('li', { class: 'fvm-empty', text: e.message })));
  Promise.all([presets(), myGroups().catch(() => [])]).then(([pre, own]) => {
    tG.em.textContent = `${pre.length} prepared · ${own.length} your own`;
    chips.replaceChildren(...[...own, ...pre].map(g => h('button', { type: 'button', text: g.name + (g.preset ? '' : ' ★'), title: `${g.pads.length} pads`, onclick: () => show('groups', { id: g.id }) })),
      h('button', { type: 'button', text: '＋ New group', onclick: () => startGroupMode(null) }));
  });
}
async function openSession(id, btn) {
  if (btn) btn.disabled = true;
  try { const s = await StratumSession.fetchOne(id); close(); StratumSession.open(s); }
  catch (e) { if (btn) { btn.disabled = false; btn.title = e.message; } alert(e.message); }
}

// ---------- Sessions ----------
const PAGE = { map: 'Map', wellview: 'Well charts', wellsection: 'Well section', winerack: 'Wine racks', stages: 'Stage charts', compare: 'Compare', pad: 'Pad' };
// what one saved window shows, in words: [kind, headline, details]
function windowWords(w, settings, pads) {
  const page = w.url.split('?')[0].replace('.html', ''), q = new URLSearchParams(w.url.split('?')[1] || ''), s = w.session || {};
  const padName = id => (pads.get(id) || {}).name || id;
  if (page === 'map') {
    const mv = parse(s['stratum.mapView']) || {}, ug = parse(s['stratum.underground']), dock = parse(s['stratum.sectionDock']);
    const bits = [];
    if (mv.zoom) bits.push(`zoom ${fmt(mv.zoom, 1)}${mv.quakes ? ' · earthquakes on' : ''}`);
    if (ug) bits.push(`3D: ${ug.label || ug.areaName || 'an area'}${ug.wa ? `, well ${ug.wa}` : ''}${ug.colorBy === 'gamma' ? ', by gamma' : ''}`);
    if (dock && dock.wa) bits.push(`well section: WA ${dock.wa}${dock.stage ? ' stage ' + dock.stage : ''}`);
    return ['Map', ug ? '3D view' : 'Surface view', bits.join(' · ') || 'the map'];
  }
  if (page === 'wellview') return ['Well charts', `WA ${q.get('wa') || '?'}${q.get('stage') ? ' · stage ' + q.get('stage') : ''}`,
    ({ 'tab-stacked': 'Stacked', 'tab-frac': 'Sequential' })[s['stratum.wellTab']] || 'Stage chart'];
  if (page === 'wellsection') return ['Well section', `WA ${q.get('wa') || '?'}`, q.get('stage') ? `stage ${q.get('stage')} picked` : 'the whole well in 2D'];
  if (page === 'winerack') { const ids = (q.get('pads') || '').split(',').filter(Boolean); return ['Wine racks', `${ids.length} pad${ids.length === 1 ? '' : 's'}`, ids.map(padName).join(', ')]; }
  if (page === 'stages') { const st = (q.get('s') || '').split(',').filter(Boolean); return ['Stage charts', `${st.length} stage${st.length === 1 ? '' : 's'}`, st.map(x => { const [wa, l] = x.split(':').map(decodeURIComponent); return `WA ${wa} stage ${l}`; }).join(', ')]; }
  if (page === 'compare') { const n = (parse(settings && settings['stratum.compare']) || []).length; return ['Compare', `${n} well${n === 1 ? '' : 's'}`, 'curves side by side']; }
  return [PAGE[page] || page, w.title || '', ''];
}
function sessions(opts = {}) {
  const list = h('div', { class: 'fvm-items', role: 'listbox', 'aria-label': 'Saved sessions' });
  const detail = h('div', { class: 'fvm-detail' }, h('div', { class: 'fvm-empty', text: 'Pick a session on the left to see the windows it opens.' }));
  const msg = h('div', { class: 'fvm-msg', role: 'status' });
  const name = h('input', { type: 'text', placeholder: 'Name what is open now', maxLength: 120, 'aria-label': 'Session name' });
  const saveBtn = h('button', { type: 'button', class: 'go', text: 'Save' });
  const search = h('input', { type: 'search', placeholder: 'Search by name or area', 'aria-label': 'Search sessions' });
  let items = [], picked = opts.id || null;
  const say = t => { msg.textContent = t || ''; };
  function draw() {
    const q = search.value.trim().toLowerCase(), shown = items.filter(x => !q || (x.name + ' ' + (x.area || '') + ' ' + (x.summary || '')).toLowerCase().includes(q));
    list.replaceChildren(...(shown.length ? shown.map(x => h('button', { type: 'button', class: 'fvm-item', role: 'option', 'aria-selected': String(x.id === picked), onclick: () => { picked = x.id; draw(); pick(x); } },
      h('b', { text: x.name }), h('span', { text: [when(x.saved), x.area].filter(Boolean).join(' · ') }),
      h('span', { text: `${x.windows} window${x.windows > 1 ? 's' : ''}${x.summary ? ' · ' + x.summary : ''}` }))) :
      [h('div', { class: 'fvm-empty', text: items.length ? 'No session matches that.' : 'No saved sessions yet. Name what is open now and save it.' })]));
  }
  async function load(sel) {
    list.replaceChildren(h('div', { class: 'fvm-empty', text: 'Loading your sessions…' }));
    try { items = await StratumSession.list(); } catch (e) { list.replaceChildren(h('div', { class: 'fvm-empty', text: e.message })); return; }
    if (sel) picked = sel;
    if (!picked && items.length) picked = items[0].id;
    draw();
    const x = items.find(i => i.id === picked); if (x) pick(x);
  }
  async function pick(x) {
    detail.replaceChildren(h('div', { class: 'fvm-empty', text: 'Opening ' + x.name + '…' }));
    let s, pads;
    try { [s, pads] = await Promise.all([StratumSession.fetchOne(x.id), padsById()]); }
    catch (e) { detail.replaceChildren(h('div', { class: 'fvm-empty', text: e.message })); return; }
    if (picked !== x.id) return;
    const open = h('button', { type: 'button', class: 'go', text: 'Open this session', onclick: () => { close(); StratumSession.open(s); } });
    const dl = h('button', { type: 'button', text: 'Download file', onclick: () => StratumSession.download(s) });
    const del = h('button', { type: 'button', class: 'danger', text: 'Delete', onclick: async () => {
      if (!confirm(`Delete “${s.name}” from your saved sessions? Files you downloaded are kept.`)) return;
      del.disabled = true;
      try { await StratumSession.forget(x.id); picked = null; say(`Deleted “${s.name}”.`); load(); } catch (e) { say(e.message); del.disabled = false; }
    } });
    const st = s.settings || {}, qf = parse(st['stratum.quakeFilter']);
    detail.replaceChildren(
      h('div', { class: 'fvm-detail-head' },
        h('div', { class: 'id' }, h('h1', { text: s.name }),
          h('div', { class: 'fvm-facts' }, h('span', { html: `Saved <b>${when(s.saved)}</b>` }), s.area ? h('span', { html: `Area <b></b>` }) : null,
            h('span', { html: `<b>${s.windows.length}</b> window${s.windows.length > 1 ? 's' : ''}` }))),
        h('div', { class: 'fvm-acts' }, open, dl, del)),
      screenMap(s, pads),
      h('h2', { text: 'Windows' }),
      h('div', { class: 'fvm-wins' }, s.windows.map((w, i) => {
        const [kind, head, more] = windowWords(w, st, pads);
        return h('div', { class: 'fvm-win' + (w.role === 'main' ? ' main' : '') },
          h('b', null, `${i + 1}. ${kind}`, w.role === 'main' ? h('i', { text: 'main window' }) : w.popup ? h('i', { text: 'window' }) : h('i', { text: 'tab' })),
          h('p', { text: [head, more, w.area && w.area !== s.area ? w.area : ''].filter(Boolean).join(' · ') }));
      })),
      h('h2', { text: 'Settings saved with it', style: 'margin-top:1.4em' }),
      h('dl', { class: 'fvm-kv' },
        h('dt', { text: 'Theme' }), h('dd', { text: st['stratum.theme'] === 'dark' ? 'Dark' : 'Light' }),
        h('dt', { text: 'Gamma colours' }), h('dd', { text: (window.StratumGamma && StratumGamma.PALETTES[st['stratum.gammaPalette']] || {}).name || 'Amber' }),
        h('dt', { text: 'Earthquakes' }), h('dd', { text: qf && window.StratumQuakes ? StratumQuakes.describe(qf) || 'all' : 'all' }),
        h('dt', { text: 'Wells on the map' }), h('dd', { text: st['stratum.allWells'] === '1' ? 'every well' : 'only those with treatment charts' })));
    const areaB = detail.querySelector('.fvm-facts span:nth-child(2) b'); if (areaB && s.area) areaB.textContent = s.area;
  }
  async function save() {
    const n = name.value.trim() || `Session ${new Date().toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}`;
    saveBtn.disabled = true; say('Asking the open windows…');
    try {
      const s = await StratumSession.capture(n);
      say('Saving…');
      const r = await StratumSession.remember(s);
      say(`Saved “${n}”: ${s.windows.length} window${s.windows.length > 1 ? 's' : ''}.`); name.value = '';
      load(r && r.id);
    } catch (e) { say(e.message); }
    saveBtn.disabled = false;
  }
  saveBtn.onclick = save;
  name.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); save(); } };
  search.oninput = draw;
  main.append(h('div', { class: 'fvm-screen split' },
    h('div', { class: 'fvm-list' },
      h('div', { class: 'fvm-list-head' }, h('h1', { text: 'Sessions' }),
        h('div', { class: 'row' }, name, saveBtn), msg, search),
      list,
      h('div', { class: 'fvm-list-foot' },
        h('button', { type: 'button', text: 'Open a session file…', onclick: () => StratumSession.readFile().then(async s => { try { await StratumSession.remember(s); } catch (e) { /* opened all the same */ } close(); StratumSession.open(s); }).catch(e => say(e.message)) }))),
    detail));
  load();
}
// the windows as they sat on screen, scaled into one picture
function screenMap(s, pads) {
  const W = 760, H = 300, ws = s.windows, rects = ws.map(w => w.rect && isFinite(w.rect.w) ? w.rect : null);
  const have = rects.filter(Boolean);
  let place;
  if (have.length === ws.length && have.length) {
    const x0 = Math.min(...have.map(r => r.x)), y0 = Math.min(...have.map(r => r.y)), x1 = Math.max(...have.map(r => r.x + r.w)), y1 = Math.max(...have.map(r => r.y + r.h));
    const k = Math.min((W - 20) / Math.max(1, x1 - x0), (H - 20) / Math.max(1, y1 - y0)), ox = (W - (x1 - x0) * k) / 2, oy = (H - (y1 - y0) * k) / 2;
    place = r => [ox + (r.x - x0) * k, oy + (r.y - y0) * k, r.w * k, r.h * k];
  } else {
    // positions not known: side by side
    const n = ws.length, cw = (W - 20 - (n - 1) * 10) / n;
    place = (r, i) => [10 + i * (cw + 10), 30, cw, H - 60];
  }
  const NS = 'http://www.w3.org/2000/svg', svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`); svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', `${ws.length} windows as they sat on screen`);
  const el = (tag, a, text) => { const e = document.createElementNS(NS, tag); for (const k in a) e.setAttribute(k, a[k]); if (text != null) e.textContent = text; svg.append(e); return e; };
  // the main window first, so the others sit over it as they did
  ws.map((w, i) => ({ w, i })).sort((a, b) => (b.w.role === 'main') - (a.w.role === 'main')).forEach(({ w, i }) => {
    const [x, y, ww, hh] = place(rects[i], i), [kind, head] = windowWords(w, s.settings, pads);
    el('rect', { x, y, width: ww, height: hh, rx: 6, class: 'win' + (w.role === 'main' ? ' main' : '') });
    el('rect', { x: x + 1, y: y + 1, width: Math.max(0, ww - 2), height: Math.min(14, hh / 4), rx: 5, class: 'bar' });
    if (ww > 70 && hh > 44) {
      const cut = (t, cw) => t.length * cw > ww - 20 ? t.slice(0, Math.max(3, Math.floor((ww - 20) / cw) - 1)) + '…' : t;
      el('text', { x: x + 10, y: y + 40 }, cut(`${i + 1}. ${kind}`, 10.5));
      if (hh > 68) el('text', { x: x + 10, y: y + 64, class: 'm' }, cut(head, 8.5));
    }
  });
  return h('div', { class: 'fvm-screenmap' }, svg);
}

// ---------- Groups ----------
function groups(opts = {}) {
  const list = h('div', { class: 'fvm-items' });
  const detail = h('div', { class: 'fvm-detail' }, h('div', { class: 'fvm-empty', text: 'Loading groups…' }));
  const msg = h('div', { class: 'fvm-msg', role: 'status' });
  let picked = opts.id || null, all = [];
  async function load(sel) {
    if (sel) picked = sel;
    const [pre, own, pads] = await Promise.all([presets(), myGroups(true).catch(e => { msg.textContent = e.message; return []; }), padsById()]);
    all = [...own, ...pre];
    if (!picked || !all.some(g => g.id === picked)) picked = (own[0] || pre[0] || {}).id || null;
    const item = g => h('button', { type: 'button', class: 'fvm-item', 'aria-selected': String(g.id === picked), onclick: () => { picked = g.id; load(); } },
      h('b', { text: g.name }), h('span', { text: `${g.pads.length} pad${g.pads.length === 1 ? '' : 's'} · ${fmt(g.pads.reduce((n, id) => n + ((pads.get(id) || {}).wells || 0), 0))} wells${g.note ? ' · ' + g.note : ''}` }));
    list.replaceChildren(h('h3', { text: 'Your groups' }), ...(own.length ? own.map(item) : [h('div', { class: 'fvm-empty', text: 'None yet. Start one with Group mode on the map, or save a Discover result as a group.', style: 'padding:.4em .7em' })]),
      h('h3', { text: 'Prepared areas' }), ...pre.map(item));
    const g = all.find(x => x.id === picked);
    if (g) drawGroup(g, pads); else detail.replaceChildren(h('div', { class: 'fvm-empty', text: 'No groups yet.' }));
  }
  function drawGroup(g, pads) {
    const ps = g.pads.map(id => pads.get(id) || { id, name: id, missing: true });
    const wells = ps.reduce((n, p) => n + (p.wells || 0), 0), curves = ps.reduce((n, p) => n + (p.curves || 0), 0);
    const ops = [...new Set(ps.map(p => p.operator).filter(Boolean))];
    const yrs = ps.flatMap(p => p.years || []).filter(Boolean);
    const nameIn = g.preset ? h('h1', { text: g.name }) : h('input', { type: 'text', value: g.name, maxLength: 80, 'aria-label': 'Group name' });
    const acts = h('div', { class: 'fvm-acts' },
      h('button', { type: 'button', class: 'go', text: 'Show on the map', onclick: () => toMap({ pads: g.pads, title: g.name }) }),
      h('button', { type: 'button', text: 'Open in 3D', onclick: () => toMap({ pads: g.pads, title: g.name, view: '3d' }) }),
      h('button', { type: 'button', text: 'Wine racks ↗', title: 'Every pad in the group, stacked in the wine rack window', onclick: () => toMap({ pads: g.pads, title: g.name, racks: true }) }),
      g.preset ? h('button', { type: 'button', text: 'Save a copy as mine', onclick: async () => { try { const n = await saveGroup({ name: g.name + ' (mine)', pads: g.pads, note: g.note }); msg.textContent = `Saved “${n.name}” to your groups.`; load(n.id); } catch (e) { msg.textContent = e.message; } } })
               : h('button', { type: 'button', text: 'Change pads on the map', onclick: () => startGroupMode(g) }),
      g.preset ? null : h('button', { type: 'button', class: 'danger', text: 'Delete', onclick: async () => {
        if (!confirm(`Delete the group “${g.name}”? The pads stay where they are.`)) return;
        try { await deleteGroup(g.id); msg.textContent = `Deleted “${g.name}”.`; picked = null; load(); } catch (e) { msg.textContent = e.message; }
      } }));
    const note = g.preset ? h('p', { class: 'fvm-sub', text: g.note }) : h('input', { type: 'text', value: g.note || '', maxLength: 300, placeholder: 'A note about this group', 'aria-label': 'Note', style: 'width:100%;margin:.6em 0 0' });
    let saveT = 0;
    const saveEdits = () => { clearTimeout(saveT); saveT = setTimeout(async () => {
      const nm = nameIn.value.trim(); if (!nm) return;
      try { const n = await saveGroup({ id: g.id, name: nm, pads: g.pads, note: note.value }); msg.textContent = 'Saved.'; g.name = n.name; g.note = n.note; } catch (e) { msg.textContent = e.message; }
    }, 600); };
    if (!g.preset) { nameIn.oninput = saveEdits; note.oninput = saveEdits; }
    let sortK = 'name', dir = 1;
    const cols = [['name', 'Pad'], ['operator', 'Operator'], ['field', 'Field'], ['years', 'Years'], ['wells', 'Wells', 1], ['curves', 'With curves', 1]];
    const table = h('table', { class: 'fvm-table' });
    const drawTable = () => {
      const val = (p, k) => k === 'years' ? (p.years || [])[0] || 0 : p[k] ?? '';
      const rows = ps.slice().sort((a, b) => { const x = val(a, sortK), y = val(b, sortK); return (x > y ? 1 : x < y ? -1 : 0) * dir; });
      table.replaceChildren(h('thead', null, h('tr', null, cols.map(([k, t, num]) => h('th', { class: num ? 'num' : null, 'aria-sort': k === sortK ? (dir > 0 ? 'ascending' : 'descending') : null },
        h('button', { type: 'button', text: t, onclick: () => { dir = sortK === k ? -dir : 1; sortK = k; drawTable(); } }))))),
        h('tbody', null, rows.map(p => h('tr', { title: p.missing ? 'Not in the region any more' : 'Show this pad on the map', onclick: () => !p.missing && toMap({ pads: [p.id], title: p.name, pad: p.id }) },
          h('td', { text: p.name }), h('td', { text: p.operator || '–' }), h('td', { text: p.field || '–' }),
          h('td', { text: p.years ? (p.years[0] === p.years[1] ? p.years[0] : p.years.join('–')) : '–' }), h('td', { class: 'num', text: fmt(p.wells) }), h('td', { class: 'num', text: fmt(p.curves) })))));
    };
    drawTable();
    detail.replaceChildren(
      h('div', { class: 'fvm-detail-head' }, h('div', { class: 'id' }, g.preset ? nameIn : h('div', { class: 'fvm-name' }, nameIn),
        h('div', { class: 'fvm-facts' }, h('span', { html: `<b>${ps.length}</b> pads` }), h('span', { html: `<b>${fmt(wells)}</b> wells` }), h('span', { html: `<b>${fmt(curves)}</b> with treatment curves` }),
          yrs.length ? h('span', { html: `<b>${Math.min(...yrs)}–${Math.max(...yrs)}</b>` }) : null, ops.length ? h('span', { text: ops.length > 2 ? `${ops.length} operators` : ops.join(', ') }) : null), note), acts),
      msg, plan(ps), table);
  }
  main.append(h('div', { class: 'fvm-screen split' },
    h('div', { class: 'fvm-list' },
      h('div', { class: 'fvm-list-head' }, h('h1', { text: 'Groups' }),
        h('p', { class: 'fvm-sub', style: 'margin:0', text: 'Pick pads on the map with Group mode, or save what Discover finds.' }),
        h('button', { type: 'button', class: 'go', text: '＋ New group on the map', onclick: () => startGroupMode(null) })),
      list),
    detail));
  load();
}
// a group's pads from overhead, true to their places
function plan(ps) {
  const pts = ps.filter(p => isFinite(p.lat) && isFinite(p.lon));
  const W = 760, H = 260, NS = 'http://www.w3.org/2000/svg', svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', `${pts.length} pads from overhead`);
  if (!pts.length) return h('div', { class: 'fvm-plan' }, svg);
  const lat0 = pts.reduce((a, p) => a + p.lat, 0) / pts.length, k = Math.cos(lat0 * Math.PI / 180);
  const xs = pts.map(p => p.lon * k), ys = pts.map(p => p.lat), x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const s = Math.min((W - 160) / Math.max(1e-4, x1 - x0), (H - 60) / Math.max(1e-4, y1 - y0)), ox = (W - (x1 - x0) * s) / 2, oy = (H - (y1 - y0) * s) / 2;
  const ops = [...new Set(pts.map(p => p.operator || ''))];
  const ink = p => window.StratumTheme ? StratumTheme.padColor(ops.indexOf(p.operator || '')) : '#0d8577';
  const placed = [];
  pts.forEach(p => {
    const x = ox + (p.lon * k - x0) * s, y = oy + (y1 - p.lat) * s;
    const c = document.createElementNS(NS, 'circle'); c.setAttribute('cx', x); c.setAttribute('cy', y); c.setAttribute('r', Math.max(4, Math.min(9, 3 + Math.sqrt(p.wells || 1)))); c.setAttribute('fill', ink(p)); svg.append(c);
    const tt = document.createElementNS(NS, 'title'); tt.textContent = `${p.name} · ${p.wells || 0} wells`; c.append(tt);
    if (pts.length <= 30 && !placed.some(q => Math.abs(q.x - x) < 120 && Math.abs(q.y - y) < 14)) {
      placed.push({ x, y });
      const t = document.createElementNS(NS, 'text'); t.setAttribute('x', x + 11); t.setAttribute('y', y + 4); t.textContent = p.name; svg.append(t);
    }
  });
  return h('div', { class: 'fvm-plan' }, svg);
}
// Group mode, on the map: there when this is the map, by its address otherwise
function startGroupMode(g) {
  const show = { groupMode: g ? { id: g.id, name: g.name, pads: g.pads, note: g.note || '' } : {} };
  if (onMap() && window.stratumGroupMode) { close(); window.stratumGroupMode.start(show.groupMode); return; }
  toMap(show);
}

// ---------- Discover ----------
let discoverP = null;
function discover(opts = {}) {
  const box = h('div', { class: 'fvm-screen split' }, h('div', { class: 'fvm-empty', text: 'Loading Discover…', style: 'padding:2em' }));
  main.append(box);
  discoverP = discoverP || new Promise((res, rej) => { const s = h('script', { src: 'discover.js' }); s.onload = res; s.onerror = () => { discoverP = null; rej(Error('Discover could not be loaded.')); }; document.head.append(s); });
  discoverP.then(() => { if (current !== 'discover') return; box.replaceChildren(); window.StratumDiscover.render(box, { h, fmt, tip, hideTip, toMap, saveGroup, padsById, tool: opts.tool, show }); })
    .catch(e => { box.replaceChildren(h('div', { class: 'fvm-empty', text: e.message, style: 'padding:2em' })); });
}

// ---------- Settings ----------
function settings() {
  const seg = (label, opts, cur, set) => {
    const box = h('div', { class: 'fvm-seg', role: 'group', 'aria-label': label });
    const draw = v => box.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.v === v)));
    opts.forEach(([v, t]) => box.append(h('button', { type: 'button', 'data-v': v, text: t, onclick: () => { set(v); draw(v); prefsChanged(); } })));
    draw(cur); return box;
  };
  const field = (label, ...kids) => h('div', { class: 'field' }, h('span', { text: label }), ...kids);
  const check = (label, small, on, set) => h('label', { class: 'fvm-check' }, h('input', { type: 'checkbox', checked: !!on, onchange: e => { set(e.target.checked); prefsChanged(); } }), h('span', null, label, small ? h('small', { text: small }) : null));
  const T = window.StratumTheme;

  // appearance
  const pal = h('div', { class: 'fvm-pal', role: 'group', 'aria-label': 'Gamma colours' });
  const drawPal = () => { if (!window.StratumGamma) return; pal.replaceChildren(...Object.entries(StratumGamma.PALETTES).map(([id, p]) => h('button', { type: 'button', 'aria-pressed': String(StratumGamma.current() === id), onclick: () => { StratumGamma.set(id); drawPal(); prefsChanged(); } },
    h('i', { style: `background:${StratumGamma.gradient(id)}` }), h('span', { text: p.name })))); };
  drawPal();
  const appearance = h('section', null, h('h2', { text: 'Appearance' }),
    field('Theme', seg('Theme', [['light', 'Light'], ['dark', 'Dark']], T ? T.get() : 'light', v => { T && T.set(v); drawPal(); })),
    field('Text size', seg('Text size', [['s', 'Small'], ['m', 'Default'], ['l', 'Large'], ['xl', 'Extra large']], T ? T.text() : 'm', v => T && T.setText(v)),
      h('div', { class: 'fvm-preview', text: 'Panels, lists, headers and pop-ups grow with this. Charts, the map and the 3D view keep their own scale (zoom them as usual).' })),
    window.StratumGamma ? field('Gamma ray colours', pal) : null);

  // earthquakes: the filter every view shares (quake-filter.js)
  const Q = window.StratumQuakes, f = Q ? Q.get() : {};
  const inp = (type, key, attrs = {}) => h('input', { type, value: f[key] ?? '', step: type === 'number' ? '0.1' : null, 'aria-label': attrs.label, placeholder: attrs.ph || null });
  const from = inp('date', 'from', { label: 'From date' }), to = inp('date', 'to', { label: 'To date' });
  const mn = inp('number', 'magMin', { label: 'Minimum magnitude', ph: 'min' }), mx = inp('number', 'magMax', { label: 'Maximum magnitude', ph: 'max' });
  const boxes = {};
  const qCount = h('div', { class: 'fvm-preview' });
  const read = () => ({ from: from.value || null, to: to.value || null, magMin: mn.value === '' ? null : +mn.value, magMax: mx.value === '' ? null : +mx.value,
                        hideFixed: boxes.hideFixed.checked, onlyMatched: boxes.onlyMatched.checked, onlyRelocated: boxes.onlyRelocated.checked });
  let rows = null;
  const count = () => { if (!rows || !Q) return; const n = rows.filter(r => Q.pass(Q.fromRow(r))).length; qCount.textContent = `${fmt(n)} of ${fmt(rows.length)} earthquakes in the catalogue pass this filter, on the map, in 3D and on the well charts.${Q.active() ? ' ' + Q.describe() + '.' : ''}`; };
  fetch('data/seismic/events.json').then(r => r.ok ? r.json() : null).then(d => { if (d) { rows = d.rows; count(); } }).catch(() => {});
  let qT = 0;
  const qSet = () => { clearTimeout(qT); qT = setTimeout(() => { if (Q) { Q.set(read()); count(); prefsChanged(); } }, 150); };
  [from, to, mn, mx].forEach(i => { i.oninput = qSet; });
  const qBox = (key, label, small) => { const c = h('label', { class: 'fvm-check' }, boxes[key] = h('input', { type: 'checkbox', checked: !!f[key], onchange: qSet }), h('span', null, label, small ? h('small', { text: small }) : null)); return c; };
  const quakes = Q ? h('section', null, h('h2', { text: 'Earthquakes' }),
    field('Dates', h('div', { class: 'fvm-pair' }, from, to)),
    field('Magnitude', h('div', { class: 'fvm-pair' }, mn, mx)),
    qBox('hideFixed', 'Hide undetermined depths', 'events whose depth the network fixed rather than solved'),
    qBox('onlyMatched', 'Only those coinciding with a frac stage'),
    qBox('onlyRelocated', 'Only relocated events', 'BC Seismic Research Consortium, May 2022–Apr 2024, located to a few hundred metres'),
    h('div', { style: 'margin-top:.8em' }, h('button', { type: 'button', text: 'Show all earthquakes', onclick: () => { Q.set({}); show('settings'); prefsChanged(); } })),
    qCount) : null;

  // the map, the well section, the charts
  const sec = parse(store.get('stratum.section')) || {};
  const setSec = (k, v) => { const cur = parse(store.get('stratum.section')) || {}; cur[k] = v; store.set('stratum.section', JSON.stringify(cur)); };
  const hidden = parse(store.get('stratum.hiddenCurves')) || [];
  const defaults = h('section', null, h('h2', { text: 'Map and wells' }),
    check('Only wells with treatment charts', 'the map, the 3D view and the wine racks keep to wells whose curves the Lab has read', store.get('stratum.allWells') !== '1', on => {
      store.set('stratum.allWells', on ? '0' : '1');
      const box = document.getElementById('charted'); if (box && box.checked !== on) { box.checked = on; box.dispatchEvent(new Event('change')); }
    }),
    field('A well in 2D opens on', seg('Well section extent', [['well', 'The whole well'], ['lateral', 'The lateral']], sec.mode || 'well', v => setSec('mode', v))),
    field('Its lateral coloured by', seg('Well section colour', [['stages', 'Stages'], ['gamma', 'Gamma']], sec.color || 'stages', v => setSec('color', v))),
    check('Pressure and rate above each stage', 'the curves strip along the top of the 2D view', sec.curves !== false, on => setSec('curves', on)),
    field('Curves hidden on the stage charts', hidden.length ? h('div', null, h('span', { text: hidden.join(', ') + ' ' }),
      h('button', { type: 'button', text: 'Show them all again', onclick: () => { store.set('stratum.hiddenCurves', null); prefsChanged(); show('settings'); } })) : h('span', { class: 'fvm-pill', text: 'none' })));

  const u = window.stratumUser;
  const account = h('section', null, h('h2', { text: 'Account' }),
    u ? h('dl', { class: 'fvm-kv' }, h('dt', { text: 'Name' }), h('dd', { text: u.name }), h('dt', { text: 'Email' }), h('dd', { text: u.email }), h('dt', { text: 'Role' }), h('dd', { text: u.role })) : null,
    h('p', { class: 'fvm-preview', text: 'Your settings, sessions and groups are kept with your account, so they follow you to any computer you sign in from. No one else sees them.' }),
    h('div', { class: 'fvm-acts', style: 'margin-top:.8em' },
      u && u.role === 'admin' ? h('button', { type: 'button', text: 'Invites & accounts', onclick: () => { location.href = 'admin.html'; } }) : null,
      h('button', { type: 'button', text: 'Reset settings to defaults', onclick: () => {
        if (!confirm('Put every setting back to its default? Your sessions and groups are kept.')) return;
        T && T.set('light'); T && T.setText('m'); window.StratumGamma && StratumGamma.set('amber'); Q && Q.set({});
        ['stratum.allWells', 'stratum.section', 'stratum.hiddenCurves'].forEach(k => store.set(k, null));
        prefsChanged(); show('settings');
      } }),
      h('button', { type: 'button', class: 'danger', text: 'Sign out', onclick: async () => { try { await fetch('/api/auth?a=logout', { method: 'POST', credentials: 'same-origin' }); } catch (e) { /* signed out below anyway */ } location.replace('/login.html'); } })));

  main.append(h('div', { class: 'fvm-screen' }, h('h1', { text: 'Settings' }),
    h('p', { class: 'fvm-sub', text: 'Changes apply straight away, in every FracView window you have open.' }),
    h('div', { class: 'fvm-set' }, appearance, quakes, defaults, account)));
}

// ---------- the buttons that open it ----------
function bind() {
  document.querySelectorAll('[data-menu]').forEach(b => { if (!b.dataset.menuBound) { b.dataset.menuBound = '1'; b.addEventListener('click', () => open(b.dataset.menu || 'home')); } });
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind); else bind();
window.StratumMenu = { open, close, show: k => open(k), saveGroup, myGroups, toMap };
})();
