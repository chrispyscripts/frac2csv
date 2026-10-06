// Stratum sessions: the whole workspace — every Stratum window that is open,
// where it sits on screen, what each one shows, and the settings — saved under
// a name, in this browser and as a .stratum-session.json file, and opened again.
//
// Each window keeps its own view in sessionStorage (stratum.* keys: the 3D view,
// the map's camera, the docked section, the compare choices…) and the settings
// it shares with the others in localStorage. Saving asks every open Stratum
// window for both over the 'stratum-session' channel. Opening a session writes
// them back: this window becomes the saved main window, and a bar offers to
// reopen the rest where they were (a browser lets a page open one window per
// click, unless pop-ups are allowed for the site).
//
// Loaded in <head>, before the page's own scripts, so a window opened for a
// session has its state in place before the page reads it.
(() => {
'use strict';
// FracView was Stratum: files saved under the old name still open
const KIND = 'fracview-session', KINDS = [KIND, 'stratum-session'];
const LIST_KEY = 'stratum.sessions', HAND = 'stratum.handoff.', PENDING = 'stratum.pendingWindows';
const PAGES = /^(map|wellview|wellsection|compare|pad|winerack)\.html(\?[^#]*)?$/;
const TOP = window.top === window;
const ME = Math.random().toString(36).slice(2);
const rid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
const ours = k => typeof k === 'string' && k.startsWith('stratum.') && k !== LIST_KEY && k !== PENDING && !k.startsWith(HAND);
const keys = st => { const out = []; try { for (let i = 0; i < st.length; i++) out.push(st.key(i)); } catch (e) { /* private mode */ } return out; };
const parse = s => { try { return JSON.parse(s); } catch (e) { return null; } };
const pagePath = () => location.pathname.replace(/^.*\//, '');

// ---------- a window opened for a session: its state first, before the page runs ----------
let handedOff = false;
(function handoff() {
  const m = location.hash.match(/stratum-restore=([\w-]+)/);
  if (!m) return;
  handedOff = true;
  try {
    const win = parse(localStorage.getItem(HAND + m[1]));
    localStorage.removeItem(HAND + m[1]);
    if (win && win.session) {
      keys(sessionStorage).filter(ours).forEach(k => sessionStorage.removeItem(k));
      for (const [k, v] of Object.entries(win.session)) if (ours(k) && typeof v === 'string') sessionStorage.setItem(k, v);
      if (win.pending) sessionStorage.setItem(PENDING, JSON.stringify(win.pending));
    }
  } catch (e) { /* private mode: the page opens plain */ }
  history.replaceState(history.state, '', location.pathname + location.search);
})();
// hand-offs for windows that never opened go stale after a day
try { keys(localStorage).filter(k => k.startsWith(HAND)).forEach(k => { const h = parse(localStorage.getItem(k)); if (!h || Date.now() - (h.at || 0) > 864e5) localStorage.removeItem(k); }); } catch (e) { /* private mode */ }

// ---------- this window, as saved ----------
const providers = [];
// a page's live view, as {sessionStorage key: string | null}: read at save time
// rather than waiting for the page to write it on its way out
function provide(fn) { providers.push(fn); }
function sessionState() {
  const out = {};
  try { keys(sessionStorage).filter(ours).forEach(k => { out[k] = sessionStorage.getItem(k); }); } catch (e) { /* private mode */ }
  for (const fn of providers) {
    try { for (const [k, v] of Object.entries(fn() || {})) { if (v == null) delete out[k]; else out[k] = String(v); } } catch (e) { /* a page mid-load */ }
  }
  return out;
}
const isPopup = () => !!(window.toolbar && window.toolbar.visible === false);
function snapshot() {
  const q = new URLSearchParams(location.search); q.delete('owner');
  return { url: pagePath() + (String(q) ? '?' + q : ''), title: document.title.replace(/^(FracView|Stratum)\s*—\s*/, ''),
           name: /^stratum-[a-z]+$/.test(window.name) ? window.name : '', popup: isPopup(),
           rect: { x: screenX, y: screenY, w: innerWidth, h: innerHeight }, session: sessionState() };
}

// every Stratum window answers when another saves, and popped-out ones step
// aside when another opens a session
const chan = 'BroadcastChannel' in self ? new BroadcastChannel('stratum-session') : null;
if (chan && TOP) chan.onmessage = e => {
  const m = e.data || {};
  if (m.type === 'collect' && m.from !== ME) chan.postMessage({ type: 'window', id: m.id, win: snapshot() });
  else if (m.type === 'restoring' && m.from !== ME && (isPopup() || window.opener)) window.close();
};
function collect() {
  return new Promise(res => {
    const id = rid(), wins = [];
    const hear = e => { const m = e.data || {}; if (m.type === 'window' && m.id === id && m.win) wins.push(m.win); };
    if (!chan) { res(wins); return; }
    chan.addEventListener('message', hear);
    chan.postMessage({ type: 'collect', id, from: ME });
    setTimeout(() => { chan.removeEventListener('message', hear); res(wins); }, 600);
  });
}
async function capture(name) {
  const others = await collect();
  const settings = {};
  keys(localStorage).filter(ours).forEach(k => { settings[k] = localStorage.getItem(k); });
  return { kind: KIND, v: 1, name, saved: new Date().toISOString(), settings,
           windows: [{ ...snapshot(), role: 'main' }, ...others.map(w => ({ ...w, role: 'window' }))] };
}

// ---------- what a session holds, in words ----------
function describe(w, settings) {
  const page = w.url.split('?')[0].replace('.html', ''), s = w.session || {}, t = (w.title || '').replace(/\s*·\s*section$/, '');
  if (page === 'map') {
    const ug = parse(s['stratum.underground']), dock = parse(s['stratum.sectionDock']);
    return 'Map' + (ug ? ` · 3D ${ug.label || ug.areaName || 'view'}${ug.section ? ' with well section' : ''}` : '')
      + (dock ? ' · well section docked' : '');
  }
  if (page === 'wellview') return `Charts · ${t}`;
  if (page === 'wellsection') return `Well section · ${t}`;
  if (page === 'compare') { const n = (parse(settings && settings['stratum.compare']) || []).length; return `Compare · ${n} well${n === 1 ? '' : 's'}`; }
  if (page === 'pad') return `Pad · ${t}`;
  if (page === 'winerack') { const n = ((parse(s['stratum.racks']) || {}).pads || []).length || (new URLSearchParams(w.url.split('?')[1] || '').get('pads') || '').split(',').filter(Boolean).length; return `Wine racks · ${n} pad${n === 1 ? '' : 's'}`; }
  return t || page;
}
const summary = s => s.windows.map(w => describe(w, s.settings)).join('  ·  ');

// a session from a file is data from elsewhere: Stratum pages and stratum.* keys only
function clean(s) {
  if (!s || !KINDS.includes(s.kind) || !Array.isArray(s.windows)) throw Error('This is not a FracView session file.');
  const str = v => typeof v === 'string';
  const strings = o => Object.fromEntries(Object.entries(o && typeof o === 'object' ? o : {}).filter(([k, v]) => ours(k) && str(v) && v.length < 2e6));
  const num = (v, lo, hi) => Number.isFinite(v) ? Math.max(lo, Math.min(hi, v)) : null;
  const windows = s.windows.filter(w => w && str(w.url) && PAGES.test(w.url.replace(/^\//, ''))).slice(0, 12).map(w => {
    const r = w.rect || {}, rect = [r.x, r.y, r.w, r.h].every(Number.isFinite)
      ? { x: num(r.x, -20000, 20000), y: num(r.y, -20000, 20000), w: num(r.w, 320, 8000), h: num(r.h, 240, 8000) } : null;
    return { role: w.role === 'main' ? 'main' : 'window', url: w.url.replace(/^\//, ''), title: str(w.title) ? w.title.slice(0, 200) : '',
             name: str(w.name) && /^stratum-[a-z]+$/.test(w.name) ? w.name : '', popup: !!w.popup, rect, session: strings(w.session) };
  });
  if (!windows.length) throw Error('This session has no FracView windows in it.');
  return { kind: KIND, v: 1, name: str(s.name) && s.name.trim() ? s.name.trim().slice(0, 120) : 'Session',
           saved: str(s.saved) ? s.saved : '', settings: strings(s.settings), windows };
}

// ---------- the saved list, and files ----------
const list = () => (parse(localStorage.getItem(LIST_KEY)) || []).filter(x => x && x.session);
function keep(entries) {
  try { localStorage.setItem(LIST_KEY, JSON.stringify(entries)); return true; }
  catch (e) { return false; }
}
function remember(session) {
  const rest = list().filter(x => x.session.name !== session.name);
  return keep([{ id: rid(), session }, ...rest].slice(0, 40));
}
function download(session) {
  const slug = session.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'session';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(session, null, 1)], { type: 'application/json' }));
  a.download = `${slug}.fracview-session.json`;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}
function readFile() {
  return new Promise((res, rej) => {
    const inp = document.createElement('input');
    inp.type = 'file'; inp.accept = '.json,application/json';
    inp.onchange = () => {
      const f = inp.files && inp.files[0];
      if (!f) return;
      if (f.size > 8e6) { rej(Error('That file is too large to be a session.')); return; }
      f.text().then(t => { const s = parse(t); if (!s) throw Error('That file is not readable JSON.'); res(clean(s)); }).catch(rej);
    };
    inp.click();
  });
}

// ---------- opening one ----------
function handOff(w, pending) {
  const t = rid();
  localStorage.setItem(HAND + t, JSON.stringify({ session: w.session, pending, at: Date.now() }));
  return t;
}
function open(raw) {
  const s = clean(raw);
  if (chan) chan.postMessage({ type: 'restoring', from: ME });
  // the settings, as they were: nothing kept from now that the session did not have
  keys(localStorage).filter(ours).forEach(k => localStorage.removeItem(k));
  for (const [k, v] of Object.entries(s.settings)) localStorage.setItem(k, v);
  // this window becomes the saved main window (a tab, not a pop-up, where there is one)
  const main = s.windows.find(w => w.role === 'main' && !w.popup) || s.windows.find(w => !w.popup) || s.windows[0];
  const rest = s.windows.filter(w => w !== main);
  const t = handOff(main, rest.length ? { name: s.name, windows: rest } : null);
  // a reload, not a same-page hash change, so the page starts from the session
  history.replaceState(null, '', main.url + '#stratum-restore=' + t);
  location.reload();
}
function openWindow(w) {
  const t = handOff(w, null), r = w.rect;
  const feat = w.popup ? 'popup' + (r ? `,left=${Math.round(r.x)},top=${Math.round(r.y)},width=${Math.round(r.w)},height=${Math.round(r.h)}` : '') : '';
  const win = window.open(w.url + '#stratum-restore=' + t, w.name || '_blank', feat);
  if (!win) { localStorage.removeItem(HAND + t); return false; }
  return true;
}

// ---------- the panel ----------
const CSS = `
:root{--ss-bg:#ffffff;--ss-bar:#fffffff5;--ss-ink:#14212b;--ss-line:#b9c8d2;--ss-shadow:rgba(20,33,43,.22);--ss-veil:rgba(20,33,43,.35);--ss-mut:#566b78;--ss-rule:#e4eaef;
  --ss-btn:#eef3f6;--ss-acc:#0d8577;--ss-go:#0d8577;--ss-go-line:#0d8577;--ss-go-ink:#ffffff;--ss-input:#ffffff;--ss-warn:#9a6700}
:root[data-theme=dark]{--ss-bg:#0d1924;--ss-bar:#0d1924f2;--ss-ink:#e7f4fa;--ss-line:#345260;--ss-shadow:#000a;--ss-veil:#04090ecc;--ss-mut:#93adb9;--ss-rule:#243a46;
  --ss-btn:#152936;--ss-acc:#5ee2d0;--ss-go:#246358;--ss-go-line:#64e8ce;--ss-go-ink:#f2fffc;--ss-input:#0a141d;--ss-warn:#f2c94c}
.ss-dlg{background:var(--ss-bg);color:var(--ss-ink);border:1px solid var(--ss-line);border-radius:14px;padding:0;width:min(640px,calc(100vw - 32px));
  box-shadow:0 24px 60px var(--ss-shadow);font:14px/1.45 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
.ss-dlg::backdrop{background:var(--ss-veil,rgba(20,33,43,.35))}
.ss-dlg header{padding:16px 18px 8px}.ss-dlg h2{margin:0;font-size:18px}.ss-dlg .ss-sub{color:var(--ss-mut);font-size:12.5px;margin-top:3px}
.ss-dlg section{padding:8px 18px}.ss-dlg footer{display:flex;gap:8px;justify-content:space-between;flex-wrap:wrap;padding:10px 18px 16px;border-top:1px solid var(--ss-rule)}
.ss-dlg button{background:var(--ss-btn);border:1px solid var(--ss-line);border-radius:8px;color:var(--ss-ink);padding:7px 12px;font:inherit;font-size:13px;cursor:pointer}
.ss-dlg button:hover{border-color:var(--ss-acc)}.ss-dlg button.go{background:var(--ss-go);border-color:var(--ss-go-line);color:var(--ss-go-ink);font-weight:600}
.ss-dlg button:focus-visible,.ss-dlg input:focus-visible{outline:2px solid var(--ss-acc);outline-offset:2px}
.ss-save{display:flex;gap:8px;flex-wrap:wrap}.ss-save input{flex:1 1 220px;min-width:0;background:var(--ss-input);border:1px solid var(--ss-line);border-radius:8px;color:var(--ss-ink);padding:7px 10px;font:inherit}
.ss-list{list-style:none;margin:0;padding:0;max-height:min(46vh,380px);overflow:auto}
.ss-list li{display:flex;gap:10px;align-items:center;padding:9px 0;border-top:1px solid var(--ss-rule)}
.ss-list .ss-what{flex:1;min-width:0}.ss-list b{display:block;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ss-list .ss-meta{color:var(--ss-mut);font-size:12px;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.ss-list .ss-x{padding:6px 9px}.ss-empty{color:var(--ss-mut);font-size:13px;padding:6px 0 10px}
.ss-msg{color:var(--ss-warn);font-size:12.5px;min-height:1.2em;padding:2px 18px 0}
.ss-bar{position:fixed;left:50%;top:12px;transform:translateX(-50%);z-index:60;display:flex;gap:8px;align-items:center;flex-wrap:wrap;max-width:calc(100vw - 24px);
  background:var(--ss-bar);border:1px solid var(--ss-acc);border-radius:12px;padding:9px 12px;color:var(--ss-ink);box-shadow:0 10px 30px var(--ss-shadow);
  font:13px/1.4 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
.ss-bar button{background:var(--ss-btn);border:1px solid var(--ss-line);border-radius:8px;color:var(--ss-ink);padding:6px 10px;font:inherit;cursor:pointer}
.ss-bar button:hover{border-color:var(--ss-acc)}.ss-bar button.go{background:var(--ss-go);border-color:var(--ss-go-line);color:var(--ss-go-ink);font-weight:600}
.ss-bar button.done{opacity:.55;cursor:default}.ss-bar .ss-hint{flex-basis:100%;color:var(--ss-mut);font-size:12px}`;
function style() {
  if (document.getElementById('ss-style')) return;
  const st = document.createElement('style'); st.id = 'ss-style'; st.textContent = CSS; document.head.append(st);
}
const when = iso => { const d = new Date(iso); return isNaN(d) ? '' : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }); };
function el(tag, props, ...kids) { const e = document.createElement(tag); Object.assign(e, props || {}); e.append(...kids); return e; }

// entry: true when Stratum has just been opened, which offers the saved sessions first
function panel(entry) {
  style();
  const old = document.querySelector('.ss-dlg'); if (old) old.remove();
  const dlg = el('dialog', { className: 'ss-dlg' });
  const msg = el('div', { className: 'ss-msg', role: 'status' });
  const say = t => { msg.textContent = t || ''; };
  const name = el('input', { type: 'text', placeholder: 'Session name', maxLength: 120, value: '' });
  name.setAttribute('aria-label', 'Session name');
  const saveBtn = el('button', { type: 'button', className: 'go', textContent: 'Save' });
  const fileBtn = el('button', { type: 'button', textContent: 'Save + download file' });
  const ul = el('ul', { className: 'ss-list' });
  function draw() {
    const items = list();
    ul.replaceChildren(...items.map(x => {
      const s = x.session;
      const what = el('div', { className: 'ss-what' }, el('b', { textContent: s.name }),
        el('div', { className: 'ss-meta', textContent: `${when(s.saved)} · ${s.windows.length} window${s.windows.length > 1 ? 's' : ''} · ${summary(s)}` }));
      const go = el('button', { type: 'button', className: 'go', textContent: 'Open' });
      go.onclick = () => { try { open(s); } catch (e) { say(e.message); } };
      const dl = el('button', { type: 'button', textContent: '⤓', title: 'Download as a session file' }); dl.setAttribute('aria-label', `Download ${s.name}`);
      dl.onclick = () => download(s);
      const rm = el('button', { type: 'button', className: 'ss-x', textContent: '×', title: 'Forget this session (files you downloaded are kept)' }); rm.setAttribute('aria-label', `Forget ${s.name}`);
      rm.onclick = () => { keep(list().filter(y => y.id !== x.id)); draw(); };
      return el('li', null, what, go, dl, rm);
    }));
    if (!items.length) ul.replaceChildren(el('li', { className: 'ss-empty', textContent: 'No sessions saved in this browser yet.' }));
  }
  async function save(toFile) {
    const n = name.value.trim() || `Session ${new Date().toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}`;
    saveBtn.disabled = fileBtn.disabled = true; say('Asking the open windows…');
    const s = await capture(n);
    saveBtn.disabled = fileBtn.disabled = false;
    const kept = remember(s);
    if (toFile || !kept) download(s);
    say(kept ? `Saved “${n}”: ${s.windows.length} window${s.windows.length > 1 ? 's' : ''}.` : 'This browser is out of room for sessions, so it was saved as a file instead.');
    name.value = ''; draw();
  }
  saveBtn.onclick = () => save(false);
  fileBtn.onclick = () => save(true);
  name.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); save(false); } };
  const openFile = el('button', { type: 'button', textContent: 'Open a session file…' });
  openFile.onclick = () => readFile().then(s => { remember(s); open(s); }).catch(e => say(e.message));
  const close = el('button', { type: 'button', textContent: entry ? 'Start fresh' : 'Close' });
  close.onclick = () => dlg.close();
  dlg.append(
    el('header', null, el('h2', { textContent: entry ? 'Pick up where you left off' : 'Sessions' }),
      el('div', { className: 'ss-sub', textContent: 'A session is every FracView window that is open, where it sits, what it shows, and your settings.' })),
    entry ? '' : el('section', null, el('div', { className: 'ss-save' }, name, saveBtn, fileBtn)),
    el('section', null, ul), msg,
    el('footer', null, openFile, close));
  dlg.addEventListener('close', () => dlg.remove());
  document.body.append(dlg);
  draw();
  dlg.showModal();
  (entry ? (dlg.querySelector('.ss-list .go') || close) : name).focus();
}

// after opening a session: the other windows, one click each (or all, where pop-ups are allowed)
function pendingBar() {
  const p = parse(sessionStorage.getItem(PENDING));
  sessionStorage.removeItem(PENDING);
  if (!p || !Array.isArray(p.windows) || !p.windows.length) return;
  style();
  const bar = el('div', { className: 'ss-bar', role: 'region' });
  bar.setAttribute('aria-label', 'Reopen the session’s other windows');
  const left = new Set(p.windows);
  const hint = el('div', { className: 'ss-hint', hidden: true, textContent: 'Your browser opens one window per click: click each, or allow pop-ups for this site to open them all at once.' });
  const settings = Object.fromEntries(keys(localStorage).filter(ours).map(k => [k, localStorage.getItem(k)]));
  const btns = p.windows.map(w => {
    const b = el('button', { type: 'button', textContent: describe(w, settings) });
    b.onclick = () => { if (!left.has(w)) return; if (openWindow(w)) { left.delete(w); b.classList.add('done'); b.textContent = '✓ ' + b.textContent; finish(); } else hint.hidden = false; };
    return b;
  });
  const all = el('button', { type: 'button', className: 'go', textContent: 'Open all' });
  all.onclick = () => { for (let i = 0; i < p.windows.length; i++) if (left.has(p.windows[i])) btns[i].click(); };
  const dismiss = el('button', { type: 'button', textContent: 'Not now' });
  dismiss.onclick = () => bar.remove();
  function finish() { if (!left.size) setTimeout(() => bar.remove(), 900); }
  bar.append(el('span', { textContent: `“${p.name}”: ${p.windows.length} more window${p.windows.length > 1 ? 's' : ''}` }), ...btns, all, dismiss, hint);
  document.body.append(bar);
}

function ready() {
  if (!TOP) return;
  document.querySelectorAll('[data-sessions]').forEach(b => b.addEventListener('click', () => panel(false)));
  pendingBar();
  // Stratum just opened (not back from a well, not a reload): offer the saved sessions
  const nav = performance.getEntriesByType && performance.getEntriesByType('navigation')[0];
  let fromUs = false;
  try { const r = new URL(document.referrer); fromUs = r.origin === location.origin && PAGES.test(r.pathname.replace(/^.*\//, '')); } catch (e) { /* no referrer */ }
  if (pagePath() === 'map.html' && !handedOff && (!nav || nav.type === 'navigate') && !fromUs && list().length) panel(true);
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready); else ready();

window.StratumSession = { provide, panel: () => panel(false), capture, open, clean };
})();
