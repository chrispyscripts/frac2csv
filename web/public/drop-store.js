// FracView — wells from a dropped file, kept in this browser.
//
// A Photon export dropped on the map (drop.js) is read in the browser and its
// wells kept here, in IndexedDB: nothing is uploaded, and the wells stay
// until they are removed (they are this browser's, not the account's). The
// files are the Saskatchewan set's (pha.js), under data/drop/:
//
//   data/drop/pads/<pad id>.json    a pad and its wells' surveys and stages
//   data/drop/wells/<wa>.json       a well's page
//
// Every page that fetches a pad or a well through StratumLogs (the map, the 3D
// view, the well section, the wine rack) gets these from here: fetch() is
// answered from IndexedDB for data/drop/ and goes to the server for anything
// else. Each dropped file has a number n; its pads are drop-<n>-..., its
// wells DR<n>-....
//
//   StratumDrop.ready          -> Promise of {drops, mapPads, indexPads}
//   StratumDrop.next()         -> the number the next dropped file gets
//   StratumDrop.add(n, meta, result)   keeps a converted file
//   StratumDrop.remove(n), .clear()
//   'stratum:dropped' (window event) when the wells change, in every window
(() => {
'use strict';
const DB = 'fracview-drop', FILES = 'files', DROPS = 'drops';
let dbP = null;
function db() {
  if (!dbP) dbP = new Promise((res, rej) => {
    let rq;
    try { rq = indexedDB.open(DB, 1); } catch (e) { rej(e); return; }
    rq.onupgradeneeded = () => {
      const d = rq.result;
      if (!d.objectStoreNames.contains(FILES)) d.createObjectStore(FILES);
      if (!d.objectStoreNames.contains(DROPS)) d.createObjectStore(DROPS, { keyPath: 'n' });
    };
    rq.onsuccess = () => res(rq.result);
    rq.onerror = () => rej(rq.error);
    rq.onblocked = () => rej(new Error('the browser kept the store closed'));
  });
  return dbP;
}
const done = tx => new Promise((res, rej) => { tx.oncomplete = () => res(); tx.onerror = () => rej(tx.error); tx.onabort = () => rej(tx.error || new Error('aborted')); });
const req = r => new Promise((res, rej) => { r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });

async function get(path) {
  const d = await db();
  return req(d.transaction(FILES).objectStore(FILES).get(path));
}
async function drops() {
  try { const d = await db(); return (await req(d.transaction(DROPS).objectStore(DROPS).getAll())).sort((a, b) => a.n - b.n); }
  catch (e) { return []; }
}

// ---------- what the pages read ----------
let state = null;
function load() {
  return drops().then(ds => {
    state = { drops: ds.map(({ mapPads, indexPads, ...m }) => m),
              mapPads: ds.flatMap(d => d.mapPads || []), indexPads: ds.flatMap(d => d.indexPads || []) };
    return state;
  });
}
let ready = load();

// fetch() for data/drop/: from IndexedDB, as the server would answer
const DROP_URL = /(?:^|\/)data\/drop\/([^?#]+)/;
const realFetch = window.fetch.bind(window);
window.fetch = function (input, init) {
  const url = typeof input === 'string' ? input : input && input.url;
  const m = url && DROP_URL.exec(url);
  if (!m) return realFetch(input, init);
  const path = decodeURIComponent(m[1]);
  return get(path).then(v => v == null
    ? new Response('not found', { status: 404, statusText: 'Not Found' })
    : new Response(JSON.stringify(v), { status: 200, headers: { 'Content-Type': 'application/json' } }),
  e => new Response(String(e && e.message || e), { status: 500 }));
};

// ---------- changes, in every window ----------
let chan = null;
try { chan = new BroadcastChannel(DB); } catch (e) { /* an old browser: this window only */ }
function changed(local) {
  ready = load();
  ready.then(s => window.dispatchEvent(new CustomEvent('stratum:dropped', { detail: s })));
  if (local && chan) chan.postMessage('changed');
}
if (chan) chan.onmessage = () => changed(false);

async function next() {
  const ds = await drops();
  return ds.reduce((m, d) => Math.max(m, d.n), 0) + 1;
}

async function add(n, meta, r) {
  const d = await db();
  const tx = d.transaction([FILES, DROPS], 'readwrite');
  const fs = tx.objectStore(FILES);
  for (const p of r.pads) fs.put(p, 'pads/' + p.id + '.json');
  for (const w of r.wells) fs.put(w.file, 'wells/' + w.wa + '.json');
  tx.objectStore(DROPS).put({ n, ...meta, report: r.report, bounds: r.bounds, pads: r.pads.length,
                              wells: r.wells.length, mapPads: r.mapPads, indexPads: r.indexPads, added: new Date().toISOString() });
  await done(tx);
  changed(true);
}

async function remove(n) {
  const d = await db();
  const tx = d.transaction([FILES, DROPS], 'readwrite');
  const fs = tx.objectStore(FILES);
  // its files: pads/drop-<n>-..., wells/DR<n>-...
  fs.delete(IDBKeyRange.bound(`pads/drop-${n}-`, `pads/drop-${n}-￿`));
  fs.delete(IDBKeyRange.bound(`wells/DR${n}-`, `wells/DR${n}-￿`));
  tx.objectStore(DROPS).delete(n);
  await done(tx);
  changed(true);
}

async function clear() {
  const d = await db();
  const tx = d.transaction([FILES, DROPS], 'readwrite');
  tx.objectStore(FILES).clear(); tx.objectStore(DROPS).clear();
  await done(tx);
  changed(true);
}

const isDropPad = id => /^drop-/.test(String(id || ''));
const isDropWell = wa => /^DR\d+-/.test(String(wa || ''));

window.StratumDrop = { get ready() { return ready; }, state: () => state, next, add, remove, clear, isDropPad, isDropWell };
})();
