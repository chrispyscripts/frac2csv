// FracView — datasets stacked under each stage chart (stages.html): the well's
// gamma, porosity, mud log, curves and comments, each a strip along MD around
// the stage, with an "Add Dataset" button below the last.
//
// A card opens blank, or with the default stack once one is saved ("Save as
// Default" at the top right, shown while a card's stack differs from it). A
// card stepped to another stage keeps its stack and the strips re-centre on the
// new stage. The reckoning (what a well has, the window, the stack) is
// stage-datasets-core.js; this file draws and wires it.
//
//   localStorage   stratum.stageDatasets        the default: {v, kinds, win, saved}
//   sessionStorage stratum.stageDatasets.cards  each card's own: [{wa, label, kinds, win}]
// Both are stratum.* keys, so a saved session (session.js) carries them.
//
//   StageDatasets.attach({wa, label, mount}) -> {setStage(label), destroy()}
//
// A solo stack (the map's Data window, data-window.js) is one card that moves
// from well to well: attach({solo: true, mount, stack, onChange}) ->
// {setTarget(wa, label), ...}. Its stack is the datasets asked for, kept by
// the caller (onChange), and stays as it is from well to well: a dataset the
// well in view lacks shows as "not on file" in its place. It takes no part in
// the stage page's default or its saved cards. With no stage (label null) it
// shows the lateral.
(() => {
'use strict';
const C = window.StageDatasetsCore;
const SL = () => window.StratumLogs || null;
const DEF_KEY = 'stratum.stageDatasets', CARDS_KEY = 'stratum.stageDatasets.cards';
const HEIGHT = { line: 64, bars: 56, cat: 22, axis: 38 }, PAD = 8;
const $ = id => document.getElementById(id);
const fmt = (v, d = 0) => (v == null || !isFinite(v) ? '–' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));
const fmtV = v => fmt(v, Math.abs(v) >= 100 ? 0 : Math.abs(v) >= 10 ? 1 : 2);
const parse = s => { try { return JSON.parse(s); } catch (e) { return null; } };
const later = fn => (window.queueMicrotask ? queueMicrotask(fn) : Promise.resolve().then(fn));
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
let uid = 0;

// ---------- what is kept ----------
function readDefault() { let s = null; try { s = localStorage.getItem(DEF_KEY); } catch (e) { /* private mode */ } return C.sanitizeStack(parse(s)); }
let DEF = readDefault();
// the cards' own stacks from before a reload: each taken by the first card of its well and stage
let RESTORE = [];
try {
  const a = parse(sessionStorage.getItem(CARDS_KEY));
  if (Array.isArray(a)) RESTORE = a.filter(r => r && r.wa != null && r.label != null).map(r => ({ wa: String(r.wa), label: String(r.label), ...(C.sanitizeStack(r) || { kinds: [], win: 'stage' }) }));
} catch (e) { /* private mode */ }
const ctls = [], solos = [];
const every = () => ctls.concat(solos);
let lastEdited = null;
const cardsJson = () => JSON.stringify(ctls.map(c => ({ wa: c.wa, label: c.label, kinds: (c.pending ? c.pending.kinds : c.kinds).slice(), win: c.win })));
function persist() {
  RESTORE = [];
  if (solos.length && !ctls.length) return;      // (the map's Data window: no stage cards to keep)
  try { sessionStorage.setItem(CARDS_KEY, cardsJson()); } catch (e) { /* private mode: this page only */ }
}
if (window.StratumSession) StratumSession.provide(() => (ctls.length ? { [CARDS_KEY]: cardsJson() } : {}));

// ---------- the wells ----------
// (kept for the last few wells: the Data window reads one well after another as the pointer moves)
const wells = new Map(), KEEP = 40;
let gammaP = null;
const getJSON = u => fetch(u).then(r => { if (!r.ok) throw Error(String(r.status)); return r.json(); });
const gammaFile = () => gammaP || (gammaP = getJSON('data/gamma.json').catch(() => null));
function model(wa) {
  if (wells.has(wa)) { const p = wells.get(wa); wells.delete(wa); wells.set(wa, p); return p; }
  while (wells.size >= KEEP) wells.delete(wells.keys().next().value);
  if (!wells.has(wa)) wells.set(wa, (async () => {
    const S = SL();
    let file;
    try { file = await getJSON(S ? S.wellUrl(wa) : `data/wells/${encodeURIComponent(wa)}.json`); }
    catch (e) { return C.emptyModel(wa, 'This well’s file could not be read, so its datasets cannot be shown.'); }
    let row = null;
    if (S && S.isLocalWell(wa)) {
      await S.skReady;
      const pid = file.pad && file.pad.id;
      if (pid) try { row = ((await getJSON(S.padUrl(pid))).wells || []).find(x => x && x.well && String(x.well.wa) === wa) || null; } catch (e) { /* no pad: no log */ }
    }
    const gj = C.needsGammaFile(wa, file, row, S) ? await gammaFile() : null;
    return C.buildModel(wa, file, row, gj, S);
  })());
  return wells.get(wa);
}

// ---------- colours: the page's tokens (stages.css), read as drawn ----------
let INK = null;
function ink() {
  if (INK) return INK;
  const s = getComputedStyle(document.documentElement), g = n => s.getPropertyValue(n).trim();
  return (INK = { ink: g('--ink'), mut: g('--mut'), grid: g('--sd-grid'), panel: g('--panel'), accent: g('--accent'),
    stage: g('--sd-stage'), stageEdge: g('--sd-stage-edge'), cursor: g('--sd-cursor'), note: g('--sd-note'), desc: g('--sd-desc'),
    c: [1, 2, 3, 4, 5, 6, 7, 8].map(i => g('--sd-c' + i)) });
}
function hue(ds) {
  const K = ink(), t = (ds.t + ' ' + ds.kind).toLowerCase();
  const i = /penetration|drill time|c:rop/.test(t) ? 0 : /neutron/.test(t) ? 1 : /density por/.test(t) ? 2 : /sonic/.test(t) ? 3
    : /bulk density/.test(t) ? 4 : /caliper/.test(t) ? 5 : /photoelectric|c:pe\b/.test(t) ? 6 : /gas|c:c\d/.test(t) ? 7 : -1;
  if (i >= 0) return K.c[i];
  let h = 0; for (const ch of ds.kind) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return K.c[h % K.c.length];
}
const rockLabel = term => {
  const S = SL(), sk = S && S.sk(), r = sk && Array.isArray(sk.rocks) && sk.rocks.find(x => x[0] === term);
  return r ? r[1] : String(term).replace(/^raw:/, '').replace(/^\w/, ch => ch.toUpperCase());
};
const rockInk = term => (SL() ? SL().rockInk(term) : ink().desc);
const catInk = (k, v) => (SL() ? SL().ink(k, v) : null);
const catWords = (k, v) => (SL() ? SL().words(k, v) : String(v));

// ---------- a card's datasets ----------
function attach(o) {
  const solo = !!o.solo;
  const c = { id: 'sd' + (++uid), wa: o.wa == null ? '' : String(o.wa), label: o.label == null ? null : String(o.label), kinds: [], win: 'stage', pending: null, m: null, mP: null,
              cursor: null, hot: -1, panels: new Map(), open: false, W: null, raf: 0, liveT: 0,
              solo, want: [], names: {}, onChange: o.onChange || null, onLoad: o.onLoad || null };
  if (solo) {
    const s = C.sanitizeStack(o.stack);
    if (s) { c.want = s.kinds; c.win = s.win; }
    const n = o.stack && o.stack.names;
    if (n && typeof n === 'object') for (const k of c.want) if (n[k] && typeof n[k].t === 'string') c.names[k] = { t: n[k].t.slice(0, 80), u: String(n[k].u || '').slice(0, 20) };
  } else {
    const i = RESTORE.findIndex(r => r.wa === c.wa && r.label === c.label);
    if (i >= 0) { const r = RESTORE.splice(i, 1)[0]; c.kinds = r.kinds; c.win = r.win; }
    else if (DEF && DEF.kinds.length) { c.pending = DEF; c.win = DEF.win; }
  }

  const root = c.root = el('div', 'sd');
  // (the page's list is a live region: the readouts change as a pointer moves, so they are kept quiet,
  // and the keyboard's readout is told through .sd-live)
  root.setAttribute('aria-live', 'off');
  root.innerHTML = `<div class="sd-bar" hidden>
      <span class="sd-lbl">Along the well (MD)</span>
      <div class="sd-win" role="group" aria-label="Stretch of the well the datasets show">
        ${C.WINS.map(w => `<button type="button" data-win="${w}" aria-pressed="false">${C.WIN_NAMES[w]}</button>`).join('')}</div>
      <span class="sd-range"></span></div>
    <canvas class="sd-axis" aria-hidden="true" hidden></canvas>
    <div class="sd-list"></div>
    <p class="sd-note" hidden></p>
    <button type="button" class="sd-add" aria-expanded="false" aria-controls="${c.id}-pick"><span class="sd-plus" aria-hidden="true">+</span> Add Dataset</button>
    <div class="sd-pick" id="${c.id}-pick" role="region" aria-label="Datasets to add" hidden></div>
    <div class="sd-live" aria-live="polite"></div>`;
  c.bar = root.querySelector('.sd-bar'); c.axis = root.querySelector('.sd-axis'); c.list = root.querySelector('.sd-list');
  c.note = root.querySelector('.sd-note'); c.add = root.querySelector('.sd-add'); c.pick = root.querySelector('.sd-pick'); c.live = root.querySelector('.sd-live');
  c.bar.querySelectorAll('[data-win]').forEach(b => { b.onclick = () => { if (c.win === b.dataset.win) return; c.win = b.dataset.win; c.cursor = null; edited(c); }; });
  c.add.onclick = () => openPick(c, !c.open);
  c.pick.addEventListener('click', e => {
    if (e.target.closest('.sd-pick-x')) { openPick(c, false); c.add.focus(); return; }
    const b = e.target.closest('.sd-opt');
    if (b && b.getAttribute('aria-disabled') !== 'true') addKind(c, b.dataset.kind);
  });
  c.pick.addEventListener('keydown', e => pickKey(c, e));
  hover(c, c.axis, null);
  o.mount.append(root);
  if (ro) ro.observe(c.list);

  (solo ? solos : ctls).push(c);
  if (c.wa && (c.kinds.length || c.pending || c.want.length || c.onLoad)) ensure(c);
  render(c);
  if (!solo) later(() => { persist(); refreshSave(); });
  return {
    setStage(label) { label = label == null ? null : String(label); if (label === c.label) return; c.label = label; c.cursor = null; c.hot = -1; render(c); persist(); refreshSave(); },
    // (solo) the well and stage to show: the stack stays, the well's datasets fill it
    setTarget(wa, label) {
      wa = wa == null ? '' : String(wa); label = label == null ? null : String(label);
      if (wa === c.wa) { this.setStage(label); return; }
      c.wa = wa; c.label = label; c.m = null; c.mP = null; c.cursor = null; c.hot = -1;
      if (c.wa && (c.want.length || c.open || c.onLoad)) ensure(c);
      if (c.open) renderPick(c, false);
      render(c);
    },
    get target() { return { wa: c.wa, label: c.label, name: c.m && c.m.ok ? c.m.name : '' }; },
    // (solo) another card's stack, taken as this one's: the Data window's cards share one
    setStack(st) {
      const s = C.sanitizeStack(st);
      if (!s) return;
      c.want = s.kinds; c.win = s.win;
      const n = (st && st.names) || {};
      c.names = {};
      for (const k of c.want) if (n[k] && typeof n[k].t === 'string') c.names[k] = { t: n[k].t.slice(0, 80), u: String(n[k].u || '').slice(0, 20) };
      if (c.wa && c.want.length) ensure(c);
      settle(c); render(c);
      if (c.open) renderPick(c, false);
    },
    destroy() {
      for (const l of [ctls, solos]) { const k = l.indexOf(c); if (k >= 0) l.splice(k, 1); }
      if (lastEdited === c) lastEdited = null;
      if (ro) ro.unobserve(c.list);
      if (!solo) { persist(); refreshSave(); }
    },
    get stack() { return stackOf(c); },
  };
}
const stackOf = c => (c.solo ? { kinds: c.want.slice(), win: c.win, names: { ...c.names } } : { kinds: c.kinds.slice(), win: c.win });
// read the well, and settle a stack waiting on it (the default: only the kinds this well has)
function ensure(c) {
  if (c.m) { settle(c); return; }
  if (c.mP || !c.wa) return;
  const wa = c.wa;
  c.mP = model(wa).then(m => {
    if (c.wa !== wa) return;                 // (a solo stack moved on to another well meanwhile)
    c.m = m; settle(c);
    if (c.onLoad) c.onLoad(m);
    if (c.open) renderPick(c, c.pick.contains(document.activeElement) || document.activeElement === c.add);
    render(c);
    if (!c.solo) { persist(); refreshSave(); }
  });
}
function settle(c) {
  if (!c.m) return;
  if (c.solo) { c.kinds = c.want.filter(k => c.m.sets.has(k)); return; }
  if (c.pending) { c.kinds = C.resolve(c.pending.kinds, c.m); c.win = c.pending.win; c.pending = null; }
  else c.kinds = C.resolve(c.kinds, c.m);
}
function edited(c) {
  if (c.solo) { settle(c); render(c); if (c.onChange) c.onChange(stackOf(c)); return; }
  lastEdited = c; render(c); persist(); refreshSave();
}
// the stack's own order: a solo stack's asked-for datasets, else the card's
const order = c => (c.solo ? c.want : c.kinds);

function addKind(c, kind) {
  const L = order(c);
  if (L.includes(kind)) return;
  if (c.solo) {
    const o = offers(c).find(x => x.kind === kind);
    if (!o) return;
    c.names[kind] = { t: o.t, u: o.u || '' };
  } else if (!c.m || !c.m.sets.has(kind)) return;
  L.push(kind);
  openPick(c, false);
  edited(c);
  c.add.focus();
}
function removeKind(c, kind) {
  const L = order(c), i = L.indexOf(kind);
  if (i < 0) return;
  L.splice(i, 1);
  if (c.solo) delete c.names[kind];
  const p = c.panels.get(kind); if (p) { p.sec.remove(); c.panels.delete(kind); }
  edited(c);
  if (c.open) renderPick(c, false);
  const next = c.panels.get(L[Math.min(i, L.length - 1)]);
  (next ? next.sec.querySelector('.sd-x') : c.add).focus();
}
function moveKind(c, kind, d, btn) {
  const L = order(c), i = L.indexOf(kind), j = i + d;
  if (i < 0 || j < 0 || j >= L.length) return;
  [L[i], L[j]] = [L[j], L[i]];
  edited(c);
  if (btn.disabled) { const p = c.panels.get(kind); if (p) p.sec.querySelector(d < 0 ? '.sd-dn' : '.sd-up').focus(); }
  else btn.focus();
}

// ---------- the picker ----------
function openPick(c, on) {
  c.open = on;
  c.add.setAttribute('aria-expanded', String(on));
  c.add.classList.toggle('on', on);
  c.pick.hidden = !on;
  if (!on) return;
  ensure(c);
  renderPick(c, true);
}
// a panel's ↑ ↓ × buttons
function actions(c, kind, t) {
  const pa = el('div', 'sd-pa');
  const btn = (cls, txt, label) => { const b = el('button', cls, txt); b.type = 'button'; b.setAttribute('aria-label', label); b.title = label; return b; };
  const up = btn('sd-up', '↑', `Move ${t} up`), dn = btn('sd-dn', '↓', `Move ${t} down`), x = btn('sd-x', '×', `Remove ${t}`);
  up.onclick = () => moveKind(c, kind, -1, up); dn.onclick = () => moveKind(c, kind, 1, dn); x.onclick = () => removeKind(c, kind);
  pa.append(up, dn, x);
  return pa;
}
// (solo) a dataset asked for that the well in view lacks: its name, and why there is no strip
function missingFor(c, kind, why) {
  let p = c.panels.get(kind);
  if (p && p.missing && p.why === why) return p;
  if (p) { p.sec.remove(); c.panels.delete(kind); }
  const nm = c.names[kind] || { t: kind.replace(/^(las|c|x):/, ''), u: '' };
  const sec = el('section', 'sd-p sd-missing'); sec.dataset.kind = kind;
  sec.setAttribute('aria-label', `${nm.t}: ${why}`);
  const ph = el('div', 'sd-ph'), pt = el('div', 'sd-pt');
  pt.append(el('b', '', nm.t));
  if (nm.u) pt.append(el('span', 'sd-u', nm.u));
  pt.append(el('span', 'sd-src', why));
  ph.append(pt, actions(c, kind, nm.t));
  sec.append(ph);
  p = { kind, sec, missing: true, why, m: c.m };
  c.panels.set(kind, p);
  return p;
}
const GROUPS = [['log', 'Logs'], ['mud', 'Mud log'], ['notes', 'Notes']];
// (solo) the usual datasets, offered whichever well is in view: a stack that follows the pointer keeps them for the wells that have them
function usual() {
  const S = SL(), d = k => (S && S.def(k)) || null;
  const mud = k => { const x = d(k) || {}; return { kind: k, t: x.t || k, u: x.u || '', group: ['rock', 'por', 'show'].includes(k) ? 'mud' : 'log' }; };
  return [{ kind: 'gamma', t: 'Gamma ray', u: 'API', group: 'log' },
    ...C.LAS_COMMON.map(n => ({ kind: 'las:' + n, t: n, u: (C.LAS_UNITS || {})[n] || '', group: 'log' })),
    ...['rock', 'por', 'show', 'c:rop', 'c:total_gas'].map(mud),
    { kind: 'comments', t: 'Comments', u: '', group: 'notes' }];
}
// what the picker lists: the well's datasets (and the usual ones it lacks, disabled); a solo stack can take any of them
function offers(c) {
  const have = order(c), ready = !!(c.m && c.m.ok);
  const base = ready ? C.catalogue(c.m, have) : [];
  if (!c.solo) return base;
  const seen = new Set(base.map(o => o.kind));
  const later = 'shown for the wells that have it';
  return [...base.map(o => (o.ok || o.added ? o : { ...o, ok: true, note: `${o.note} · ${later}` })),
    ...usual().filter(o => !seen.has(o.kind)).map(o => {
      const added = have.includes(o.kind);
      return { ...o, added, ok: !added, note: added ? 'In this stack' : ready ? `${C.NO_FILE} · ${later}` : `Shown for each well you point at that has it` };
    })];
}
function renderPick(c, focus) {
  const p = c.pick;
  p.replaceChildren();
  const h = el('div', 'sd-pick-h');
  const sub = c.solo ? (c.m && c.m.ok ? `what ${c.m.name || 'this well'} has first` : c.wa ? 'reading this well…' : 'point at a well or a stage on the map to see what it has')
    : c.m && c.m.ok ? 'drawn along the well’s MD, around the stage' : '';
  h.append(el('b', '', 'Add a dataset'), el('span', '', sub));
  const x = el('button', 'sd-pick-x', '×'); x.type = 'button'; x.setAttribute('aria-label', 'Close the list of datasets');
  h.append(x); p.append(h);
  if (!c.solo && !c.m) { p.append(el('p', 'sd-pick-wait', 'Reading this well’s logs…')); if (focus) x.focus(); return; }
  if (!c.solo && !c.m.ok) { p.append(el('p', 'sd-pick-wait', c.m.err)); if (focus) x.focus(); return; }
  const opts = offers(c);
  for (const [g, name] of GROUPS) {
    const list = opts.filter(o => o.group === g);
    if (!list.length) continue;
    const box = el('div', 'sd-grp'), hid = `${c.id}-g-${g}`;
    const hh = el('div', 'sd-grp-h', name); hh.id = hid;
    const row = el('div', 'sd-opts'); row.setAttribute('role', 'group'); row.setAttribute('aria-labelledby', hid);
    for (const o of list) {
      const b = el('button', 'sd-opt' + (o.added ? ' added' : '')); b.type = 'button'; b.dataset.kind = o.kind;
      b.setAttribute('aria-disabled', String(!o.ok));
      const t = el('span', 'sd-opt-t'); t.append(el('b', '', o.t)); if (o.u) t.append(el('span', 'sd-u', o.u));
      if (o.added) t.append(el('span', 'sd-tick', '✓'));
      b.append(t, el('small', '', o.note));
      row.append(b);
    }
    box.append(hh, row); p.append(box);
  }
  if (focus) { const first = p.querySelector('.sd-opt[aria-disabled=false]') || p.querySelector('.sd-opt') || x; first.focus(); }
}
function pickKey(c, e) {
  if (e.key === 'Escape') { e.preventDefault(); openPick(c, false); c.add.focus(); return; }
  const all = [...c.pick.querySelectorAll('.sd-opt')], i = all.indexOf(document.activeElement);
  if (i < 0) return;
  const to = { ArrowDown: i + 1, ArrowRight: i + 1, ArrowUp: i - 1, ArrowLeft: i - 1, Home: 0, End: all.length - 1 }[e.key];
  if (to == null) return;
  e.preventDefault();
  all[(to + all.length) % all.length].focus();
}

// ---------- the panels ----------
function panelFor(c, kind) {
  let p = c.panels.get(kind);
  if (p && !p.missing && p.m === c.m) return p;
  if (p) { p.sec.remove(); c.panels.delete(kind); }       // (a solo stack's: the well in view changed)
  const ds = c.m.sets.get(kind);
  if (c.solo) c.names[kind] = { t: ds.t, u: ds.u || '' };
  const sec = el('section', 'sd-p sd-' + ds.style); sec.dataset.kind = kind;
  sec.setAttribute('aria-label', ds.t + (ds.u ? `, ${ds.u}` : ''));
  const ph = el('div', 'sd-ph'), pt = el('div', 'sd-pt');
  const sw = el('i', 'sd-sw'); sw.setAttribute('aria-hidden', 'true');
  pt.append(sw, el('b', '', ds.t));
  if (ds.u) pt.append(el('span', 'sd-u', ds.u));
  const src = el('span', 'sd-src', ds.src || '');
  if (ds.file) src.title = ds.file;
  if (ds.est) src.classList.add('est');
  const sc = el('span', 'sd-scale');
  pt.append(src, sc);
  const read = el('div', 'sd-read');
  ph.append(pt, read, actions(c, kind, ds.t));
  const cv = el('canvas', 'sd-c'); cv.tabIndex = 0; cv.setAttribute('role', 'img');
  sec.append(ph, cv);
  p = { kind, ds, sec, cv, read, sw, sc, wkey: '', m: c.m };
  if (ds.style === 'cat') { p.key = el('div', 'sd-key'); sec.append(p.key); }
  if (ds.style === 'notes') {
    p.count = el('div', 'sd-cm-n'); p.rows = el('ol', 'sd-cm'); sec.append(p.count, p.rows);
    const on = e => { const li = e.target.closest('li[data-i]'); setHot(c, li ? +li.dataset.i : -1); };
    p.rows.addEventListener('pointerover', on); p.rows.addEventListener('focusin', on);
    p.rows.addEventListener('pointerleave', () => setHot(c, -1)); p.rows.addEventListener('focusout', () => setHot(c, -1));
  }
  hover(c, cv, p);
  cv.addEventListener('keydown', e => canvasKey(c, e));
  c.panels.set(kind, p);
  return p;
}

// the strips share one cursor along MD: a pointer over any of them, or the arrow keys
function hover(c, cv, p) {
  const at = e => { const r = cv.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top, w: r.width }; };
  const move = e => {
    if (!c.W) return;
    const q = at(e);
    c.cursor = mdAt(c.W, q.x, q.w);
    if (p && p.ds.style === 'notes') setHot(c, hitNote(c, p, q.x, q.y, q.w), true);
    schedule(c);
  };
  cv.addEventListener('pointermove', move);
  cv.addEventListener('pointerdown', move);
  cv.addEventListener('pointerleave', () => { c.cursor = null; if (p && p.ds.style === 'notes') setHot(c, -1, true); schedule(c); });
}
function canvasKey(c, e) {
  if (!c.W) return;
  const span = c.W.hi - c.W.lo, step = span / 100 * (e.shiftKey ? 10 : 1);
  const mid = c.W.stage ? (c.W.stage.top + c.W.stage.base) / 2 : (c.W.lo + c.W.hi) / 2;
  const now = c.cursor != null ? c.cursor : mid;
  const to = { ArrowLeft: now - step, ArrowRight: now + step, Home: c.W.lo, End: c.W.hi }[e.key];
  if (e.key === 'Escape') { c.cursor = null; schedule(c); return; }
  if (to == null) return;
  e.preventDefault();
  c.cursor = Math.max(c.W.lo, Math.min(c.W.hi, c.cursor == null && (e.key === 'ArrowLeft' || e.key === 'ArrowRight') ? mid : to));
  schedule(c);
  clearTimeout(c.liveT);
  c.liveT = setTimeout(() => { c.live.textContent = `${fmt(c.cursor)} m MD: ` + c.kinds.map(k => c.panels.get(k)).filter(Boolean).map(p => `${p.ds.t} ${valueWords(c, p, c.cursor)}`).join('; '); }, 250);
}
function setHot(c, i, fromStrip) {
  if (c.hot === i) return;
  c.hot = i;
  const p = c.panels.get('comments');
  if (p && p.rows) for (const li of p.rows.children) {
    const on = +li.dataset.i === i;
    li.classList.toggle('on', on);
    if (on && fromStrip) { const top = li.offsetTop - p.rows.offsetTop, bot = top + li.offsetHeight; if (top < p.rows.scrollTop) p.rows.scrollTop = top; else if (bot > p.rows.scrollTop + p.rows.clientHeight) p.rows.scrollTop = bot - p.rows.clientHeight; }
  }
  schedule(c);
}

// ---------- drawing ----------
const X = (W, w) => md => PAD + (md - W.lo) / (W.hi - W.lo) * (w - 2 * PAD);
const mdAt = (W, x, w) => Math.max(W.lo, Math.min(W.hi, W.lo + (x - PAD) / Math.max(1, w - 2 * PAD) * (W.hi - W.lo)));
function canvas(cv, h) {
  const w = cv.clientWidth, r = window.devicePixelRatio || 1;
  if (!w) return null;
  if (cv.width !== Math.round(w * r) || cv.height !== Math.round(h * r)) { cv.width = Math.round(w * r); cv.height = Math.round(h * r); }
  cv.style.height = h + 'px';
  const g = cv.getContext('2d');
  g.setTransform(r, 0, 0, r, 0, 0); g.clearRect(0, 0, w, h);
  return { g, w, h };
}
function schedule(c) { if (!c.raf) c.raf = requestAnimationFrame(() => { c.raf = 0; draw(c); }); }

function render(c) {
  const ready = !!(c.m && c.m.ok), show = ready && c.kinds.length > 0;
  // (a solo stack, while the next well is read: the last one's strips stay, dimmed)
  const reading = c.solo && !!c.wa && !c.m && c.want.length > 0;
  c.root.classList.toggle('sd-busy', reading);
  if (!reading) c.bar.hidden = c.axis.hidden = !show;
  c.bar.querySelectorAll('[data-win]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.win === c.win)));
  // the panels, in the stack's order
  const L = order(c);
  for (const [k, p] of c.panels) if (!L.includes(k) || (!c.solo && !c.kinds.includes(k))) { p.sec.remove(); c.panels.delete(k); }
  const place = (p, i, n) => {
    if (c.list.children[i] !== p.sec) c.list.insertBefore(p.sec, c.list.children[i] || null);
    p.sec.querySelector('.sd-up').disabled = i === 0;
    p.sec.querySelector('.sd-dn').disabled = i === n - 1;
  };
  if (c.solo && !reading) L.forEach((k, i) => {
    const why = !c.wa ? 'Point at a well or a stage on the map' : !ready ? (c.m && c.m.err) || C.NO_FILE
      : ((c.m.offer.find(o => o.kind === k) || {}).why || C.NO_FILE);
    place(ready && c.m.sets.has(k) ? panelFor(c, k) : missingFor(c, k, why), i, L.length);
  });
  else if (!c.solo && ready) c.kinds.forEach((k, i) => place(panelFor(c, k), i, c.kinds.length));
  c.add.title = c.solo ? (L.length ? 'Stack another dataset under these: gamma, porosity, the mud log, comments…' : 'Stack gamma, porosity, the mud log, comments… for the well or stage under the pointer, along MD')
    : c.kinds.length ? 'Stack another dataset under this one: gamma, porosity, the mud log, comments…' : 'Stack the well’s gamma, porosity, mud log, comments… under this stage’s chart, along MD';
  c.root.classList.toggle('has', show);
  if (!reading) draw(c);
  else { c.note.hidden = false; c.note.textContent = 'Reading this well’s logs…'; }
}

function draw(c) {
  const busy = c.pending || (c.kinds.length && !c.m) || (c.mP && !c.m && c.open);
  if (!c.m || !c.m.ok || !c.kinds.length) {
    c.W = null;
    c.note.hidden = !(busy || (c.m && !c.m.ok && c.kinds.length));
    c.note.textContent = c.m && !c.m.ok ? c.m.err : 'Reading this well’s logs…';
    return;
  }
  // (no stage: a solo stack pointed at a well shows its lateral)
  const win = c.label == null && c.win === 'stage' ? 'lateral' : c.win;
  const W = c.W = C.windowFor(win, c.m, c.label, c.kinds);
  c.note.hidden = !W.note; c.note.textContent = W.note;
  c.bar.querySelector('.sd-range').textContent = `${fmt(W.lo)}–${fmt(W.hi)} m MD`;
  const ax = canvas(c.axis, HEIGHT.axis);
  if (!ax) return;
  const tk = C.ticks(W.lo, W.hi, ax.w - 2 * PAD);
  drawAxis(c, ax, tk);
  for (const k of c.kinds) {
    const p = c.panels.get(k);
    if (!p) continue;
    const h = p.ds.style === 'notes' ? notesHeight(c, p) : HEIGHT[p.ds.style] || 60;
    const cx = canvas(p.cv, h);
    if (!cx) continue;
    const wkey = `${W.lo}|${W.hi}|${c.label}`;
    if (p.wkey !== wkey) {
      p.wkey = wkey; describe(c, p);
      const s = ds => scaleOf(c, ds);
      p.sc.textContent = p.ds.style === 'line' ? `scale ${fmtV(s(p.ds).lo)}–${fmtV(s(p.ds).hi)}` : '';
      p.sc.title = c.W.win === 'well' ? 'The strip’s scale: the readings along the whole well' : 'The strip’s scale: the readings along the lateral, the same for every stage of this well';
      p.sw.style.background = swatch(p.ds);
    }
    grid(cx, W, tk);
    // (comments keep their colours: the stage shades the strip under them, and over the others)
    const notes = p.ds.style === 'notes';
    if (notes) stageMark(c, cx);
    const drawn = (p.ds.style === 'line' ? drawLine : p.ds.style === 'bars' ? drawBars : p.ds.style === 'cat' ? drawCat : drawNotes)(c, p, cx);
    if (!notes) stageMark(c, cx);
    if (!drawn) empty(c, p, cx);
    cursorMark(c, p, cx);
    const v = valueWords(c, p, c.cursor);
    p.read.textContent = c.cursor != null ? `${fmt(c.cursor)} m: ${v}` : notes || !v ? v : `Stage ${c.label}: ${v}`;
  }
}
// the little key by a strip's name
function swatch(ds) {
  if (ds.palette && window.StratumGamma) return StratumGamma.gradient();
  if (ds.style === 'line') return hue(ds);
  if (ds.style === 'notes') return `linear-gradient(90deg,${ink().desc} 50%,${ink().note} 50%)`;
  const vs = ds.kind === 'rock' ? [...new Set(ds.raw.filter(v => v != null))].slice(0, 4) : ds.kind === 'show' ? [0, 2, 4] : [3, 12, 21];
  const cs = vs.map(v => catInk(ds.kind, v)).filter(Boolean);
  return cs.length > 1 ? `linear-gradient(90deg,${cs.join(',')})` : cs[0] || ink().mut;
}
function grid({ g, w, h }, W, tk) {
  const K = ink(), x = X(W, w);
  g.strokeStyle = K.grid; g.lineWidth = 1;
  g.beginPath();
  for (const t of tk.at) { const px = Math.round(x(t)) + 0.5; g.moveTo(px, 0); g.lineTo(px, h); }
  g.stroke();
}
// the stage: shaded where it was pumped (a port or a short interval still shows)
function stageMark(c, { g, w, h }) {
  const st = c.W.stage;
  if (!st) return;
  const K = ink(), x = X(c.W, w);
  let a = x(st.top), b = x(st.base);
  if (b - a < 4) { const m = (a + b) / 2; a = m - 2; b = m + 2; }
  g.fillStyle = K.stage; g.fillRect(a, 0, b - a, h);
  g.strokeStyle = K.stageEdge; g.lineWidth = 1; g.setLineDash([3, 3]);
  g.beginPath(); g.moveTo(Math.round(a) + 0.5, 0); g.lineTo(Math.round(a) + 0.5, h); g.moveTo(Math.round(b) - 0.5, 0); g.lineTo(Math.round(b) - 0.5, h); g.stroke();
  g.setLineDash([]);
}
function cursorMark(c, p, { g, w, h }) {
  if (c.cursor == null) return;
  const K = ink(), px = Math.round(X(c.W, w)(c.cursor)) + 0.5;
  g.strokeStyle = K.cursor; g.lineWidth = 1;
  g.beginPath(); g.moveTo(px, 0); g.lineTo(px, h); g.stroke();
  if (p.ds.style === 'line' || p.ds.style === 'bars') {
    const r = C.valueAt(p.ds, c.cursor);
    if (r && r.v != null) { const y = yOf(p.ds, h, scaleOf(c, p.ds))(r.v); g.fillStyle = K.ink; g.beginPath(); g.arc(px, y, 3, 0, 2 * Math.PI); g.fill(); }
  }
}
const scaleOf = (c, ds) => (c.W && c.W.win === 'well' && ds.scaleAll ? ds.scaleAll : ds.scale);
const yOf = (ds, h, s) => v => { const f = Math.max(0, Math.min(1, (v - s.lo) / ((s.hi - s.lo) || 1))); return h - 3 - f * (h - 8); };
function empty(c, p, { g, w, h }) {
  const K = ink(), ds = p.ds;
  g.font = '11px -apple-system,Segoe UI,Roboto,sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
  const where = ds.style === 'notes' ? `none in this stretch (${ds.items.length} on file, ${fmt(ds.lo)}–${fmt(ds.hi)} m MD)`
    : ds.hi < c.W.lo ? `it ends at ${fmt(ds.hi)} m MD, above this stretch` : ds.lo > c.W.hi ? `it starts at ${fmt(ds.lo)} m MD, below this stretch` : `none in this stretch (it runs ${fmt(ds.lo)}–${fmt(ds.hi)} m MD)`;
  const t = `No readings here: ${where}`, tw = Math.min(w - 16, g.measureText(t).width);
  g.fillStyle = K.panel; g.globalAlpha = 0.92; g.fillRect(w / 2 - tw / 2 - 6, h / 2 - 8, tw + 12, 16); g.globalAlpha = 1;
  g.fillStyle = K.mut; g.fillText(t, w / 2, h / 2, w - 16);
}
function drawLine(c, p, cx) {
  const { g, w, h } = cx, ds = p.ds, K = ink(), x = X(c.W, w), y = yOf(ds, h, scaleOf(c, ds));
  const [a, b] = C.slice(ds.md, c.W.lo, c.W.hi);
  const runs = [];
  let cur = null;
  for (let i = a; i <= b && ds.md.length; i++) {
    const v = ds.v[i];
    if (!isFinite(v) || (cur && ds.md[i] - ds.md[i - 1] > ds.gap)) { if (cur) runs.push(cur); cur = null; }
    if (isFinite(v)) (cur = cur || []).push(i);
  }
  if (cur) runs.push(cur);
  if (!runs.length || !runs.some(r => r.some(i => ds.md[i] >= c.W.lo && ds.md[i] <= c.W.hi))) return false;
  const col = hue(ds), G = ds.palette && window.StratumGamma;
  g.save(); g.beginPath(); g.rect(PAD - 1, 0, w - 2 * PAD + 2, h); g.clip();
  for (const r of runs) {
    // the fill: a gamma run in the gamma colours (the 3D view's and the well section's), others in a wash of their own
    if (G && ds.cscale) {
      for (let k = 0; k < r.length; k++) {
        const i = r[k], x0 = k ? (x(ds.md[r[k - 1]]) + x(ds.md[i])) / 2 : x(ds.md[i]) - 1, x1 = k < r.length - 1 ? (x(ds.md[i]) + x(ds.md[r[k + 1]])) / 2 : x(ds.md[i]) + 1;
        g.fillStyle = StratumGamma.ink(ds.v[i], ds.cscale);
        g.fillRect(x0, y(ds.v[i]), Math.max(1, x1 - x0 + 0.5), h - y(ds.v[i]));
      }
    } else {
      g.beginPath(); g.moveTo(x(ds.md[r[0]]), h);
      for (const i of r) g.lineTo(x(ds.md[i]), y(ds.v[i]));
      g.lineTo(x(ds.md[r[r.length - 1]]), h); g.closePath();
      g.globalAlpha = 0.16; g.fillStyle = col; g.fill(); g.globalAlpha = 1;
    }
    g.beginPath();
    r.forEach((i, k) => (k ? g.lineTo(x(ds.md[i]), y(ds.v[i])) : g.moveTo(x(ds.md[i]), y(ds.v[i]))));
    g.strokeStyle = G ? K.ink : col; g.globalAlpha = G ? 0.75 : 1; g.lineWidth = 1.4; g.lineJoin = 'round'; g.stroke(); g.globalAlpha = 1;
  }
  g.restore();
  return true;
}
// porosity as the mud log draws it: a bar per sample, its length the reading
function drawBars(c, p, cx) {
  const { g, w, h } = cx, ds = p.ds, x = X(c.W, w), y = yOf(ds, h, scaleOf(c, ds));
  const [a, b] = C.slice(ds.md, c.W.lo, c.W.hi);
  let any = false;
  for (let i = a; i <= b; i++) {
    const v = ds.v[i];
    if (!isFinite(v)) continue;
    const x0 = x(ds.md[i] - ds.bin / 2), x1 = x(ds.md[i] + ds.bin / 2);
    g.fillStyle = catInk(ds.kind, v) || hue(ds);
    g.fillRect(x0, y(v), Math.max(1, x1 - x0), h - y(v));
    if (ds.md[i] >= c.W.lo && ds.md[i] <= c.W.hi) any = true;
  }
  return any;
}
// rock type and shows: a band of colour per sample
function drawCat(c, p, cx) {
  const { g, w, h } = cx, ds = p.ds, x = X(c.W, w);
  const i0 = Math.max(0, Math.floor((c.W.lo - ds.md0) / ds.bin)), i1 = Math.min(ds.raw.length - 1, Math.ceil((c.W.hi - ds.md0) / ds.bin));
  let any = false;
  for (let i = i0; i <= i1; i++) {
    const v = ds.raw[i];
    if (v == null) continue;
    const x0 = x(ds.md0 + i * ds.bin), x1 = x(ds.md0 + (i + 1) * ds.bin);
    g.fillStyle = catInk(ds.kind, v) || ink().mut;
    g.fillRect(x0, 2, Math.max(1, x1 - x0 + 0.4), h - 4);
    any = true;
  }
  return any;
}
const notesIn = (c, p) => C.commentsIn(p.ds.items, c.W.lo, c.W.hi);
function notesHeight(c, p) { const items = c.W ? notesIn(c, p) : []; return Math.max(24, 8 + 13 * (items.length ? Math.max(...C.lanes(items)) + 1 : 1)); }
function noteBoxes(c, p, w) {
  const items = notesIn(c, p), ln = C.lanes(items), x = X(c.W, w);
  return items.map((it, k) => { let a = x(it.top), b = x(it.base); if (b - a < 4) { const m = (a + b) / 2; a = m - 2; b = m + 2; } return { it, i: p.ds.items.indexOf(it), a, b, y: 4 + 13 * ln[k] }; });
}
function noteInk(it) {
  const K = ink();
  if (it.kind === 'note') return K.note;
  const r = it.rocks.find(x => x[1] != null) || it.rocks[0];
  return r ? rockInk(r[0]) : K.desc;
}
function drawNotes(c, p, cx) {
  const { g, w } = cx, K = ink(), boxes = noteBoxes(c, p, w);
  if (!boxes.length) return false;
  for (const bx of boxes) {
    g.globalAlpha = c.hot < 0 || c.hot === bx.i ? 0.9 : 0.35;
    g.fillStyle = noteInk(bx.it); g.fillRect(bx.a, bx.y, bx.b - bx.a, 10);
    g.globalAlpha = 1;
    if (c.hot === bx.i) { g.strokeStyle = K.ink; g.lineWidth = 1.5; g.strokeRect(bx.a - 0.5, bx.y - 0.5, bx.b - bx.a + 1, 11); }
  }
  return true;
}
function hitNote(c, p, px, py, w) {
  let best = -1, bd = 7;
  for (const bx of noteBoxes(c, p, w)) {
    const dx = px < bx.a ? bx.a - px : px > bx.b ? px - bx.b : 0, dy = py < bx.y ? bx.y - py : py > bx.y + 10 ? py - bx.y - 10 : 0;
    if (dx + dy < bd) { bd = dx + dy; best = bx.i; }
  }
  return best;
}
// the ruler: depths below, the stages above (this one named)
function drawAxis(c, { g, w, h }, tk) {
  const K = ink(), W = c.W, x = X(W, w), font = '10.5px -apple-system,Segoe UI,Roboto,sans-serif';
  g.font = font; g.textBaseline = 'alphabetic';
  g.strokeStyle = K.grid; g.lineWidth = 1;
  g.beginPath(); g.moveTo(PAD, h - 0.5); g.lineTo(w - PAD, h - 0.5); g.stroke();
  g.fillStyle = K.mut; g.textAlign = 'center';
  for (const t of tk.at) {
    const px = Math.round(x(t)) + 0.5;
    g.beginPath(); g.moveTo(px, h - 5); g.lineTo(px, h); g.strokeStyle = K.mut; g.stroke();
    g.fillText(fmt(t), Math.min(w - 20, Math.max(20, px)), h - 7);
  }
  // the well's stages in this stretch
  const sts = c.m.stages.filter(s => s.base >= W.lo && s.top <= W.hi).sort((a, b) => a.top - b.top);
  const me = W.stage ? x((W.stage.top + W.stage.base) / 2) : null;
  let lastX = -Infinity;
  g.textAlign = 'center';
  for (const s of sts) {
    if (s.label === c.label) continue;
    const mid = x((s.top + s.base) / 2);
    g.fillStyle = K.mut; g.globalAlpha = 0.65;
    g.fillRect(Math.round(mid), 1, 1, 7);
    g.globalAlpha = 1;
    // its number, where it clears the last one and this stage's name
    if (mid - lastX > 22 && (me == null || Math.abs(mid - me) > 40) && sts.length < 80) { g.fillText(s.label, mid, 18); lastX = mid; }
  }
  if (W.stage) {
    const t = `Stage ${c.label}`;
    g.font = '600 ' + font;
    const tw = g.measureText(t).width, tx = Math.min(w - PAD - tw / 2, Math.max(PAD + tw / 2, me));
    g.fillStyle = K.accent; g.fillRect(Math.round(me) - 1, 0, 2, 8);
    g.fillText(t, tx, 18);
    g.font = font;
  }
  if (c.cursor != null) {
    const px = Math.round(x(c.cursor)) + 0.5, t = `${fmt(c.cursor)} m`;
    const tw = g.measureText(t).width, tx = Math.min(w - tw / 2 - 4, Math.max(tw / 2 + 4, px));
    g.strokeStyle = K.cursor; g.beginPath(); g.moveTo(px, 0); g.lineTo(px, h); g.stroke();
    g.fillStyle = K.ink; g.fillRect(tx - tw / 2 - 4, h - 19, tw + 8, 15);
    g.fillStyle = K.panel; g.fillText(t, tx, h - 7);
  }
}

// ---------- words: the readout, and each strip as text ----------
function valueWords(c, p, md) {
  const ds = p.ds;
  if (md == null) {
    if (ds.style === 'notes') { const n = c.W ? notesIn(c, p).length : 0; return `${n} comment${n === 1 ? '' : 's'} in view`; }
    if (!c.W || !c.W.stage) return '';
    md = (c.W.stage.top + c.W.stage.base) / 2;
  }
  const r = C.valueAt(ds, md);
  if (ds.style === 'notes') {
    const n = r ? r.v.length : 0;
    if (!n) return 'no comment';
    const t = r.v[0].text;
    return (t.length > 48 ? t.slice(0, 47).replace(/\s+\S*$/, '') + '…' : t) + (n > 1 ? ` (+${n - 1} more)` : '');
  }
  if (!r || r.v == null) return ds.style === 'cat' ? catWords(ds.kind, null) : 'no reading';
  if (ds.style === 'cat') return catWords(ds.kind, r.v);
  return `${fmtV(r.v)}${ds.u ? ' ' + ds.u : ''}`;
}
// the strip as text (its label), and what goes under it: the rock or show key, the comments
function describe(c, p) {
  const ds = p.ds, W = c.W, span = `${fmt(W.lo)}–${fmt(W.hi)} m MD`;
  let words;
  if (ds.style === 'line' || ds.style === 'bars') {
    const [a, b] = C.slice(ds.md, W.lo, W.hi), vs = [];
    for (let i = a; i <= b; i++) if (ds.md[i] >= W.lo && ds.md[i] <= W.hi && isFinite(ds.v[i])) vs.push(ds.v[i]);
    words = vs.length ? `${fmtV(Math.min(...vs))} to ${fmtV(Math.max(...vs))}${ds.u ? ' ' + ds.u : ''}` : 'no readings';
  } else if (ds.style === 'cat') {
    const n = new Map(); let all = 0;
    const i0 = Math.max(0, Math.floor((W.lo - ds.md0) / ds.bin)), i1 = Math.min(ds.raw.length - 1, Math.floor((W.hi - ds.md0) / ds.bin));
    for (let i = i0; i <= i1; i++) { const v = ds.raw[i]; if (v != null) { n.set(v, (n.get(v) || 0) + 1); all++; } }
    const top = [...n.entries()].sort((x, y) => y[1] - x[1]);
    words = all ? top.slice(0, 4).map(([v, k]) => `${catWords(ds.kind, v)} ${Math.round(100 * k / all)} %`).join(', ') : 'nothing logged';
    p.key.replaceChildren(...top.slice(0, 10).map(([v]) => { const s = el('span'), b = el('b'); b.style.background = catInk(ds.kind, v) || ''; s.append(b, document.createTextNode(catWords(ds.kind, v))); return s; }));
    if (!top.length) p.key.textContent = '';
  } else {
    const items = notesIn(c, p);
    words = `${items.length} comment${items.length === 1 ? '' : 's'}, listed below`;
    p.count.textContent = items.length ? `${items.length} of ${ds.items.length} comment${ds.items.length === 1 ? '' : 's'} in ${span}` : `No comments in ${span} (${ds.items.length} on file, ${fmt(ds.lo)}–${fmt(ds.hi)} m)`;
    p.rows.replaceChildren(...items.map(it => {
      const li = el('li'); li.dataset.i = String(ds.items.indexOf(it)); li.tabIndex = 0;
      const sw = el('i', 'sd-cm-sw'); sw.style.background = noteInk(it); sw.setAttribute('aria-hidden', 'true');
      const d = el('span', 'sd-cm-d', it.base > it.top ? `${fmt(it.top, 1)}–${fmt(it.base, 1)} m` : `${fmt(it.top, 1)} m`);
      const k = el('span', 'sd-cm-k', it.kind === 'note' ? 'Note' : 'Description');
      const t = el('span', 'sd-cm-t', it.text);
      li.append(sw, d, k, t);
      if (it.rocks.length) li.append(el('span', 'sd-cm-r', it.rocks.map(([r, pc]) => rockLabel(r) + (pc != null ? ` ${fmt(pc)} %` : '')).join(' · ')));
      if (it.from || it.file) li.title = [it.from && `From the ${it.from}`, it.file].filter(Boolean).join(': ');
      li.classList.toggle('on', +li.dataset.i === c.hot);
      return li;
    }));
  }
  const at = W.stage && ds.style !== 'notes' ? `; at stage ${c.label}, ${valueWords(c, p, null)}` : '';
  p.cv.setAttribute('aria-label', `${ds.t} along ${span}: ${words}${at}. Arrow keys move a readout along the well.`);
}

// ---------- the default: Save as Default at the top right ----------
const differs = c => !c.pending && !C.sameStack({ kinds: c.kinds, win: c.win }, C.expected(DEF, c.m));
function target() {
  if (lastEdited && ctls.includes(lastEdited) && differs(lastEdited)) return lastEdited;
  for (let i = ctls.length - 1; i >= 0; i--) if (differs(ctls[i])) return ctls[i];
  return null;
}
const names = c => c.kinds.map(k => (c.m && c.m.sets.get(k) ? c.m.sets.get(k).t : k));
function refreshSave() {
  const b = $('sg-savedef');
  if (!b) return;
  const t = target();
  b.hidden = !t;
  if (t) b.title = t.kinds.length
    ? `Make stage ${t.label}'s datasets (${names(t).join(', ')}; ${C.WIN_NAMES[t.win]}) the default: every stage opened from now on shows them, and so does any open stage that has none`
    : `Stage ${t.label} has no datasets: save that as the default, and stages open blank from now on`;
}
function saveDefault() {
  const t = target(), b = $('sg-savedef'), had = !!b && document.activeElement === b;
  if (!t) return;
  DEF = { kinds: t.kinds.slice(), win: t.win };
  try { localStorage.setItem(DEF_KEY, JSON.stringify({ v: 1, kinds: DEF.kinds, win: DEF.win, saved: new Date().toISOString() })); } catch (e) { /* private mode: this page only */ }
  fill();
  refreshSave();
  const n = $('sg-savenote');
  if (n) {
    n.textContent = DEF.kinds.length ? `Default saved: ${names(t).join(', ')}` : 'Default saved: stages open blank';
    clearTimeout(n._t); n._t = setTimeout(() => { n.textContent = ''; }, 4000);
  }
  // the button goes once nothing differs: focus moves to the card it saved from
  if (had && b.hidden) t.add.focus({ preventScroll: true });
}
// the open cards with no datasets of their own take the default
function fill() {
  if (!DEF || !DEF.kinds.length) return;
  for (const c of ctls) if (!c.kinds.length && !c.pending) { c.pending = DEF; c.win = DEF.win; ensure(c); render(c); }
  persist();
}
{
  const b = $('sg-savedef');
  if (b) b.onclick = saveDefault;
}
addEventListener('storage', e => { if (e.key === DEF_KEY) { DEF = readDefault(); fill(); refreshSave(); } });

// ---------- redraws ----------
const ro = 'ResizeObserver' in window ? new ResizeObserver(es => { for (const e of es) { const c = every().find(x => x.list === e.target); if (c) schedule(c); } }) : null;
const repaint = () => { INK = null; for (const c of every()) { for (const p of c.panels.values()) p.wkey = ''; schedule(c); } };
addEventListener('stratum:theme', repaint);
addEventListener('stratum:gammapalette', repaint);
addEventListener('stratum:textsize', repaint);
if (!ro) addEventListener('resize', () => every().forEach(schedule));

window.StageDatasets = { attach, DEF_KEY, CARDS_KEY, get default() { return DEF; } };
})();
