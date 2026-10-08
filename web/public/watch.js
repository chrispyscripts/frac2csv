// FracView's watch list: pads to keep an eye on, and what is new near them.
//
// A pad is watched from its popup on the map (☆ Watch) or from Groups; the list
// lives with the account (/api/mine?k=watch; this browser's copy when the
// account can't be reached). For each pad: how far to look (km) and the smallest
// earthquake worth hearing about.
//
// What's new near watched pads, asked of the BC Energy Regulator live (its map
// services answer FracView's pages directly):
//   earthquakes   its seismicity catalogue (ML 1.5 and up, updated daily)
//   frac jobs     its notices of fracturing operations (expected start and end)
// and of FracView's own data (data/updates.json, written when the data is rebuilt):
//   charts        wells whose treatment charts came in
//   production    wells with new months of production
// Items newer than the last look (`seen`) count as new; the menu shows how many.
// With alerts on, a FracView window that is open checks every ten minutes and the
// browser shows a notification for a new earthquake (only while FracView is open;
// the daily or weekly email digest is api/digest.js).
(() => {
'use strict';
if (window.StratumWatch) return;
const API = '/api/mine?k=watch', LOCAL = 'fv.watch', POLL = 'fv.watchPoll';
const BCER = 'https://geoweb-ags.bc-er.ca/arcgis/rest/services/';
const QUAKES = BCER + 'GEOLOGY/SEISMIC_EVENT_PT/MapServer/0/query';
const FRACS = BCER + 'WELL/HISTORIC_FRACTURING/FeatureServer/0/query';
const EMPTY = { pads: [], digest: 'off', quakeAlerts: false, email: false, seen: null, updated: null };
const chan = 'BroadcastChannel' in window ? new BroadcastChannel('stratum-watch') : null;
let doc = null, docP = null, offline = false;

const readLocal = () => { try { return Object.assign({}, EMPTY, JSON.parse(localStorage.getItem(LOCAL) || '{}')); } catch (e) { return { ...EMPTY }; } };
const writeLocal = d => { try { localStorage.setItem(LOCAL, JSON.stringify(d)); } catch (e) { /* private mode */ } };
async function call(body) {
  const r = await fetch(API, body ? { method: 'POST', credentials: 'same-origin', cache: 'no-store', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
                                  : { credentials: 'same-origin', cache: 'no-store' });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(Error(j.error || 'Your watch list could not be reached.'), { status: r.status });
  return j;
}
function get() {
  if (doc) return Promise.resolve(doc);
  return docP || (docP = call(null).then(j => (doc = Object.assign({}, EMPTY, j))).catch(() => { offline = true; return (doc = readLocal()); }).finally(() => { docP = null; }));
}
function changed(d, quiet) {
  doc = d;
  if (offline) writeLocal(d);
  window.dispatchEvent(new CustomEvent('stratum:watch', { detail: d }));
  if (chan && !quiet) chan.postMessage({ type: 'changed' });
}
if (chan) chan.onmessage = e => { if (e.data && e.data.type === 'changed') { doc = null; get().then(d => changed(d, true)); } };

async function set(w) {
  const cur = await get();
  const next = { ...cur, ...w };
  if (offline) { changed(next); return next; }
  const j = await call({ action: 'set', watch: { pads: next.pads, digest: next.digest, quakeAlerts: next.quakeAlerts, email: next.email } });
  changed(Object.assign({}, EMPTY, j));
  return doc;
}
const has = id => !!(doc && doc.pads.some(p => p.id === id));
async function toggle(pad) {
  const d = await get();
  const pads = d.pads.some(p => p.id === pad.id) ? d.pads.filter(p => p.id !== pad.id)
    : [...d.pads, { id: pad.id, name: pad.name || pad.id, lat: pad.lat, lon: pad.lon, km: pad.km || 10, mag: pad.mag ?? 2 }];
  return set({ pads });
}
async function seen(at = new Date().toISOString()) {
  const d = await get();
  if (offline) { changed({ ...d, seen: at }); return; }
  try { changed(Object.assign({}, EMPTY, await call({ action: 'seen', at }))); } catch (e) { changed({ ...d, seen: at }); }
}

// ---- what's new ----
const km = (a, b) => { const k = Math.cos(a.lat * Math.PI / 180); return Math.hypot((a.lat - b.lat) * 111.32, (a.lon - b.lon) * 111.32 * k); };
function box(pads) {
  const r = Math.max(...pads.map(p => p.km)) / 111.32 + 0.02;
  const lat = pads.map(p => p.lat), lon = pads.map(p => p.lon), k = Math.cos(lat[0] * Math.PI / 180);
  return [Math.min(...lat) - r, Math.max(...lat) + r, Math.min(...lon) - r / k, Math.max(...lon) + r / k];
}
async function arcgis(url, where, fields, order) {
  const q = new URLSearchParams({ where, outFields: fields, f: 'json', returnGeometry: url === FRACS ? 'true' : 'false', outSR: '4326',
                                  orderByFields: order, resultRecordCount: '1000' });
  const r = await fetch(url + '?' + q, { cache: 'no-store' });
  const j = await r.json();
  if (j.error) throw Error(j.error.message || 'The regulator’s service did not answer.');
  return j.features || [];
}
const stamp = d => d.toISOString().slice(0, 19).replace('T', ' ');
// nearest watched pad within its reach, for a point
function nearest(pads, pt, magOk) {
  let best = null;
  for (const p of pads) { const d = km(p, pt); if (d <= p.km && (!magOk || magOk(p)) && (!best || d < best.km)) best = { pad: p, km: d }; }
  return best;
}
async function quakes(pads, since) {
  const [la0, la1, lo0, lo1] = box(pads), mn = Math.min(...pads.map(p => p.mag));
  const f = await arcgis(QUAKES, `EVENT_DATE_TIME > timestamp '${stamp(since)}' AND LATITUDE >= ${la0.toFixed(4)} AND LATITUDE <= ${la1.toFixed(4)} ` +
    `AND LONGITUDE >= ${lo0.toFixed(4)} AND LONGITUDE <= ${lo1.toFixed(4)} AND MAGNITUDE >= ${mn}`,
    'EVENT_DATE_TIME,MAGNITUDE,MAGNITUDE_TYPE,LATITUDE,LONGITUDE,DEPTH_KM,MAJOR_AXIS_ERROR', 'EVENT_DATE_TIME DESC');
  return f.map(x => x.attributes).map(a => {
    const pt = { lat: a.LATITUDE, lon: a.LONGITUDE }, n = nearest(pads, pt, p => a.MAGNITUDE >= p.mag);
    return n && { kind: 'quake', t: new Date(a.EVENT_DATE_TIME).toISOString(), mag: a.MAGNITUDE, type: a.MAGNITUDE_TYPE || 'ML',
                  lat: a.LATITUDE, lon: a.LONGITUDE, depth: a.DEPTH_KM, err: a.MAJOR_AXIS_ERROR, pad: n.pad, km: n.km };
  }).filter(Boolean);
}
async function fracs(pads) {
  const [la0, la1, lo0, lo1] = box(pads);
  const from = new Date(Date.now() - 30 * 864e5);
  // the notices carry a point and dates, not latitude fields: the box goes as a geometry
  const q = new URLSearchParams({ where: `OPS_EXPECTED_END_DATE >= timestamp '${stamp(from)}'`, outFields: 'OPS_EXPECTED_START_DATE,OPS_EXPECTED_END_DATE,WA_NUM,WELL_NAME,OPERATOR_ABBREVIATION,OBJECTIVE_FORMATION',
    geometry: `${lo0},${la0},${lo1},${la1}`, geometryType: 'esriGeometryEnvelope', inSR: '4326', spatialRel: 'esriSpatialRelIntersects',
    outSR: '4326', returnGeometry: 'true', orderByFields: 'OPS_EXPECTED_START_DATE DESC', resultRecordCount: '500', f: 'json' });
  const r = await fetch(FRACS + '?' + q, { cache: 'no-store' }), j = await r.json();
  if (j.error) throw Error(j.error.message || 'The regulator’s service did not answer.');
  return (j.features || []).map(x => {
    const a = x.attributes, g = x.geometry || {}, pt = { lat: g.y, lon: g.x }, n = g.y != null && nearest(pads, pt);
    return n && { kind: 'frac', t: a.OPS_EXPECTED_START_DATE ? new Date(a.OPS_EXPECTED_START_DATE).toISOString() : null,
                  end: a.OPS_EXPECTED_END_DATE ? new Date(a.OPS_EXPECTED_END_DATE).toISOString() : null, wa: a.WA_NUM,
                  well: (a.WELL_NAME || '').replace(/\s+/g, ' ').trim(), operator: a.OPERATOR_ABBREVIATION, formation: a.OBJECTIVE_FORMATION,
                  lat: g.y, lon: g.x, pad: n.pad, km: n.km };
  }).filter(Boolean);
}
let updatesP = null, wellsP = null;
const getJSON = u => fetch(u).then(r => (r.ok ? r.json() : null)).catch(() => null);
async function fracview(pads) {
  const [u, w] = await Promise.all([updatesP || (updatesP = getJSON('data/updates.json')), wellsP || (wellsP = getJSON('data/discover/wells.json'))]);
  if (!u || !w) return [];
  const ci = Object.fromEntries(w.columns.map((c, i) => [c, i])), out = [];
  for (const r of w.rows) {
    const e = u.wells[String(r[ci.wa])];
    if (!e) continue;
    const n = nearest(pads, { lat: r[ci.lat], lon: r[ci.lon] });
    if (!n) continue;
    const base = { wa: String(r[ci.wa]), well: r[ci.name], operator: r[ci.operator], padId: r[ci.pad], lat: r[ci.lat], lon: r[ci.lon], pad: n.pad, km: n.km };
    if (e.charts && e.charts > u.baseline) out.push({ kind: 'charts', t: e.charts + 'T12:00:00Z', ...base });
    if (e.prodSeen && e.prodSeen > u.baseline) out.push({ kind: 'production', t: e.prodSeen + 'T12:00:00Z', through: e.prodThrough, ...base });
  }
  return out;
}
// everything near the watched pads, newest first; `since` bounds the earthquakes (30 days by default)
async function feed(o = {}) {
  const d = await get();
  if (!d.pads.length) return { items: [], errors: [], seen: d.seen };
  const since = o.since || new Date(Date.now() - 30 * 864e5), errors = [];
  const parts = await Promise.all([
    quakes(d.pads, since).catch(e => { errors.push('earthquakes: ' + e.message); return []; }),
    fracs(d.pads).catch(e => { errors.push('frac notices: ' + e.message); return []; }),
    fracview(d.pads).catch(() => []),
  ]);
  const items = parts.flat().sort((a, b) => String(b.t).localeCompare(String(a.t)));
  for (const it of items) it.fresh = !d.seen || String(it.t) > d.seen;
  return { items, errors, seen: d.seen };
}
async function count() {
  const f = await feed().catch(() => ({ items: [] }));
  return f.items.filter(i => i.fresh && i.kind !== 'frac').length + f.items.filter(i => i.fresh && i.kind === 'frac' && i.t && i.t <= new Date().toISOString()).length;
}

// ---- alerts while a FracView window is open ----
async function poll() {
  if (window.top !== window || !('Notification' in window) || Notification.permission !== 'granted') return;
  const d = await get();
  if (!d.quakeAlerts || !d.pads.length) return;
  let last = 0;
  try { last = +localStorage.getItem(POLL) || 0; } catch (e) { /* private mode */ }
  if (Date.now() - last < 9 * 60e3) return;          // another FracView window asked a moment ago
  try { localStorage.setItem(POLL, String(Date.now())); } catch (e) { /* private mode */ }
  const since = new Date(Math.max(last || Date.now() - 864e5, Date.now() - 864e5));
  const qs = await quakes(d.pads, since).catch(() => []);
  for (const q of qs.slice(0, 3)) {
    new Notification(`M${q.mag} earthquake ${q.km.toFixed(1)} km from ${q.pad.name}`, {
      body: `${q.t.slice(0, 16).replace('T', ' ')} UTC · BC Energy Regulator catalogue`, tag: 'fv-quake-' + q.t });
  }
}
async function allowAlerts() {
  if (!('Notification' in window)) throw Error('This browser cannot show notifications.');
  const p = await Notification.requestPermission();
  if (p !== 'granted') throw Error('Notifications are blocked for FracView in this browser’s settings.');
  await set({ quakeAlerts: true });
  poll();
}
if (window.top === window) setInterval(poll, 10 * 60e3), setTimeout(poll, 20e3);

window.StratumWatch = { get, set, has, toggle, seen, feed, count, allowAlerts, offline: () => offline };
})();
