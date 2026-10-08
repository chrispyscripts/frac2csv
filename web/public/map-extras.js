// The map's extra layers and tools, beside map.html's own script (it uses that
// script's map, SETS, PAD_BY_ID, WELL_BY_WA, afterLayers):
//
//   Colour wells by   any well measure in Discover's table (completion, production,
//                     stage metrics from the curves, spacing), parent/child at the
//                     limits in Settings, or when the well was fracked; pad colours
//                     otherwise. A setting (stratum.mapColour).
//   As of             only the wells fracked by a date, to watch an area develop;
//                     ▶ plays it month by month. Kept for the window (stratum.mapAsOf).
//   Seismicity        the BC Energy Regulator's seismic monitoring areas and their
//                     rules; a traffic light at each pad (the largest earthquake near
//                     it while it was fracked, graded by today's rules); each event's
//                     location error (the regulator's error ellipse, or the
//                     consortium's error as a circle) under the earthquakes.
//   Export            the map as a PNG (pad names drawn in), the wells in view as
//                     GeoJSON or KML with their Discover measures.
//   Pop-ups           a pad's traffic light and ☆ Watch; a well's stage report.
(() => {
'use strict';
const $ = (s, el = document) => el.querySelector(s);
const dark = () => !!(window.StratumTheme && StratumTheme.dark());
const getJSON = u => fetch(u).then(r => (r.ok ? r.json() : null)).catch(() => null);
const plain = wa => String(+wa);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const store = { get: k => { try { return localStorage.getItem(k); } catch (e) { return null; } }, set: (k, v) => { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* private mode */ } } };

let wellsP = null;
const wells = () => wellsP || (wellsP = getJSON('data/discover/wells.json').then(d => {
  const m = new Map();
  if (d) for (const r of d.rows) { const o = Object.fromEntries(d.columns.map((c, i) => [c, r[i]])); m.set(plain(o.wa), o); }
  return m;
}));

// ---------- colour wells by ----------
const MEASURES = [
  ['pad', 'Pad'], ['relation', 'Parent / child'], ['fracDate', 'When fracked'],
  ['proppantPerM', 'Proppant intensity', 't/m', 2], ['fluidPerM', 'Fluid intensity', 'm³/m', 1], ['stageSpacing', 'Stage spacing', 'm', 0],
  ['gas12Per100m', 'Gas, first 12 months per 100 m', 'e³m³', 0], ['liq12Per100m', 'Liquids, first 12 months per 100 m', 'm³', 1],
  ['cgr12', 'Condensate–gas ratio, first year', 'm³/e³m³', 3], ['peakGas', 'Peak gas rate', 'e³m³/d', 0],
  ['tph', 'Sand rate (curves)', 't/h', 0], ['pumpMin', 'Pump time per stage (curves)', 'min', 0], ['avgP', 'Avg treating pressure', 'MPa', 1],
  ['isip', 'ISIP', 'MPa', 1], ['fg', 'Frac gradient', 'kPa/m', 1], ['flagged', 'Stages flagged (curves)', '', 0],
  ['nnH', 'Nearest lateral, across', 'm', 0], ['gamma', 'Landing gamma', 'API', 0], ['quakes', 'Earthquakes at its stages', '', 0],
];
const M = Object.fromEntries(MEASURES.map(([k, t, u, d]) => [k, { k, t, u, d }]));
const BINS = 9;
let colourKey = M[store.get('stratum.mapColour')] ? store.get('stratum.mapColour') : 'pad';
let legendKey = null;

const day = s => { if (!s) return null; const p = String(s).slice(0, 10).split('-').map(Number); return Date.UTC(p[0], (p[1] || 1) - 1, p[2] || 1); };
const fmtv = (v, m) => v == null || !isFinite(v) ? '–' : Number(v).toLocaleString(undefined, { maximumFractionDigits: m.d ?? 1, minimumFractionDigits: m.d ?? 1 }) + (m.u ? ' ' + m.u : '');

// wa -> colour, for the measure; and the key to draw
async function colours(key) {
  const W = await wells(), F = window.FVMetrics, out = new Map();
  if (key === 'relation' && F) {
    const rel = await F.relations();
    for (const wa of W.keys()) { const r = rel.get(wa); out.set(wa, F.relColour(r ? r.relation : 'standalone')); }
    return { out, key: 'relation' };
  }
  const val = key === 'fracDate' ? (w => day(w.fracStart)) : (w => w[key]);
  const vals = [...W.values()].map(val).filter(v => v != null && isFinite(v));
  const dom = F ? F.domain(vals, key) : null;
  for (const [wa, w] of W) {
    const v = val(w);
    if (v == null || !isFinite(v) || !dom) { out.set(wa, F ? F.colour(null, dom, key) : '#999'); continue; }
    // in bins, so the map's expression stays short
    const t = Math.max(0, Math.min(1, (v - dom[0]) / (dom[1] - dom[0]))), b = Math.round(t * (BINS - 1)) / (BINS - 1);
    out.set(wa, F.colour(dom[0] + b * (dom[1] - dom[0]), dom, key));
  }
  return { out, dom, key };
}
function expr(out) {
  const by = new Map();
  for (const [wa, c] of out) { if (!by.has(c)) by.set(c, []); by.get(c).push(wa, wa.padStart(5, '0')); }
  const e = ['match', ['to-string', ['get', 'wa']]];
  for (const [c, was] of by) e.push([...new Set(was)], c);
  e.push(['get', 'color']);
  return e;
}
const COLOURED = [['laterals', 'line-color'], ['laterals-hl', 'line-color'], ['laterals-sel', 'line-color'], ['toes', 'circle-color'], ['toes-hl', 'circle-color']];
async function applyColour() {
  if (!map.getLayer('laterals')) return;
  if (colourKey === 'pad') {
    for (const [l, p] of COLOURED) if (map.getLayer(l)) map.setPaintProperty(l, p, ['get', 'color']);
    drawKey(null); return;
  }
  if (!window.FVMetrics) return;
  const c = await colours(colourKey);
  const e = expr(c.out);
  for (const [l, p] of COLOURED) if (map.getLayer(l)) map.setPaintProperty(l, p, e);
  drawKey(c);
}
function drawKey(c) {
  const box = $('#mc-key');
  if (!box) return;
  if (!c) { box.innerHTML = ''; box.hidden = true; return; }
  box.hidden = false;
  const F = window.FVMetrics;
  if (c.key === 'relation') {
    box.innerHTML = Object.entries(F.REL).map(([k, r]) => `<span class="mc-rel"><i style="background:${F.relColour(k)}"></i>${esc(r.s)} ${esc(r.t)}</span>`).join('')
      + `<small>Limits ${F.limits().across} m across · ${F.limits().vertical} m vertical · ${F.limits().siblingDays} days (Settings)</small>`;
    return;
  }
  const m = M[c.key], th = dark() ? 'dark' : 'light';
  const stops = Array.from({ length: BINS }, (_, i) => F.colour(c.dom[0] + i / (BINS - 1) * (c.dom[1] - c.dom[0]), c.dom, c.key));
  const lab = v => c.key === 'fracDate' ? new Date(v).toISOString().slice(0, 7) : fmtv(v, m);
  box.innerHTML = `<span class="mc-ramp"><span>${esc(lab(c.dom[0]))}</span><i style="background:linear-gradient(90deg,${stops.join(',')})"></i><span>${esc(lab(c.dom[1]))}</span></span>`
    + `<span class="mc-rel"><i style="background:${F.colour(null, null, c.key)}"></i>not known</span>` + (th ? '' : '');
}

// ---------- as of ----------
const ASOF_KEY = 'stratum.mapAsOf';
let asOf = null, playT = 0;
try { asOf = JSON.parse(sessionStorage.getItem(ASOF_KEY) || 'null'); } catch (e) { asOf = null; }
if (window.StratumSession) StratumSession.provide(() => ({ [ASOF_KEY]: asOf ? JSON.stringify(asOf) : null }));
const monthOf = ms => { const d = new Date(ms); return d.getUTCFullYear() * 12 + d.getUTCMonth(); };
const msOf = m => Date.UTC(Math.floor(m / 12), m % 12 + 1, 0);      // the month's last day
const FILTERED = ['laterals', 'laterals-halo', 'toes', 'laterals-hit'];
async function applyAsOf() {
  if (!map.getLayer('laterals')) return;
  try { if (asOf) sessionStorage.setItem(ASOF_KEY, JSON.stringify(asOf)); else sessionStorage.removeItem(ASOF_KEY); } catch (e) { /* private mode */ }
  const label = $('#asof-date');
  if (!asOf || !asOf.on) {
    for (const l of FILTERED) if (map.getLayer(l)) map.setFilter(l, null);
    if (map.getLayer('pads')) map.setFilter('pads', null);
    if (label) label.textContent = 'all wells';
    return;
  }
  const W = await wells(), until = msOf(asOf.m), keep = [], pads = new Set();
  for (const [wa, w] of W) { const t = day(w.fracStart); if (t != null && t <= until) { keep.push(wa, wa.padStart(5, '0')); pads.add(w.pad); } }
  const f = ['in', ['to-string', ['get', 'wa']], ['literal', [...new Set(keep)]]];
  for (const l of FILTERED) if (map.getLayer(l)) map.setFilter(l, f);
  if (map.getLayer('pads')) map.setFilter('pads', ['in', ['get', 'id'], ['literal', [...pads]]]);
  if (label) label.textContent = `fracked by ${new Date(until).toISOString().slice(0, 7)} · ${(keep.length / 2) | 0} wells`;
}

// ---------- seismicity ----------
const LEVEL = {
  notify: { t: 'Notify', w: 3, light: '#d9a400', dark: '#ffd43b', s: '▲' },
  mitigate: { t: 'Mitigate', w: 4.5, light: '#e8590c', dark: '#ff922b', s: '◆' },
  suspend: { t: 'Suspend', w: 6, light: '#c92a2a', dark: '#ff6b6b', s: '■' },
};
let lights = null, areas = null;
async function seismicLayers() {
  [lights, areas] = await Promise.all([getJSON('data/seismic/padlights.json'), getJSON('data/seismic/areas.json')]);
  const th = () => (dark() ? 'dark' : 'light');
  if (areas && !map.getSource('smma')) {
    map.addSource('smma', { type: 'geojson', data: areas.areas });
    map.addLayer({ id: 'smma-fill', type: 'fill', source: 'smma', layout: { visibility: 'none' }, paint: { 'fill-color': '#7048e8', 'fill-opacity': 0.05 } }, 'areas-fill');
    map.addLayer({ id: 'smma-line', type: 'line', source: 'smma', layout: { visibility: 'none' }, paint: { 'line-color': '#7048e8', 'line-width': 2, 'line-dasharray': [4, 3] } }, 'areas-fill');
    map.on('click', 'smma-fill', e => {
      if (pickAt(e.point)) return;
      const r = areas.rules[e.features[0].properties.rule];
      if (!r) return;
      if (popup) popup.remove();
      popup = new maplibregl.Popup({ closeButton: true, maxWidth: '330px' }).setLngLat(e.lngLat).setHTML(`<div class="pop"><b>${esc(r.name)}</b><div class="facts">
        Within ${r.km} km of a well's trajectory (local magnitude):<br>ML ${r.notify}+ notify the BCER within 24 h<br>ML ${r.mitigate}+ start the mitigation plan
        <br>ML ${r.suspend}+ suspend fracturing on the pad${r.resuspend ? `<br>after a restart, suspend again at ML ${r.resuspend}` : ''}<br>in force since ${esc(r.since)}</div></div>`).addTo(map);
    });
  }
  if (lights && !map.getLayer('pads-tl')) {
    const byLevel = lv => Object.entries(lights.pads).filter(([, v]) => v.level === lv).map(([k]) => k);
    const colour = ['match', ['get', 'id']], width = ['match', ['get', 'id']];
    for (const lv of Object.keys(LEVEL)) { const ids = byLevel(lv); if (ids.length) { colour.push(ids, LEVEL[lv][th()]); width.push(ids, LEVEL[lv].w); } }
    colour.push('rgba(0,0,0,0)'); width.push(0);
    map.addLayer({ id: 'pads-tl', type: 'circle', source: 'pads', layout: { visibility: 'none' },
      paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 7, 8, 11, 13, 14, 18], 'circle-color': 'rgba(0,0,0,0)',
               'circle-stroke-color': colour.length > 3 ? colour : 'rgba(0,0,0,0)', 'circle-stroke-width': width.length > 3 ? width : 0 } }, 'pads');
  }
}
function recolourLights() {
  if (!lights || !map.getLayer('pads-tl')) return;
  const th = dark() ? 'dark' : 'light', colour = ['match', ['get', 'id']];
  for (const lv of Object.keys(LEVEL)) { const ids = Object.entries(lights.pads).filter(([, v]) => v.level === lv).map(([k]) => k); if (ids.length) colour.push(ids, LEVEL[lv][th]); }
  colour.push('rgba(0,0,0,0)');
  if (colour.length > 3) map.setPaintProperty('pads-tl', 'circle-stroke-color', colour);
}
// each event's location error, as the catalogue gives it: an ellipse (BCER) or a circle (BCSRC)
function ellipse(lon, lat, a, b, azDeg, n = 32) {
  const k = Math.cos(lat * Math.PI / 180), az = (azDeg || 0) * Math.PI / 180, pts = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n * 2 * Math.PI, x = a * Math.cos(t), y = b * Math.sin(t);
    // the major axis along the azimuth, clockwise from north
    const e = x * Math.sin(az) + y * Math.cos(az), nn = x * Math.cos(az) - y * Math.sin(az);
    pts.push([lon + e / (111320 * k), lat + nn / 111320]);
  }
  return pts;
}
async function errorLayer() {
  if (map.getSource('quake-err') || !map.getLayer('quakes')) return;
  const q = await getJSON('data/seismic/events.json');
  if (!q) return;
  const feats = [];
  for (const r of q.rows) {
    const [maj, min, az] = [r[12], r[13], r[14]];
    const a = maj || (r[8] === 'bcsrc' ? r[9] : null), b = min || (r[8] === 'bcsrc' ? r[9] : null);
    if (!a || !b) continue;
    feats.push({ type: 'Feature', geometry: { type: 'Polygon', coordinates: [ellipse(r[2], r[1], a, b, maj ? az : 0)] },
                 properties: { ms: Date.parse(r[0]), mag: r[4], fixed: !!r[6] || r[3] == null, src: r[8], m: r[11] ? r[11].join('|') : '' } });
  }
  map.addSource('quake-err', { type: 'geojson', data: { type: 'FeatureCollection', features: feats } });
  const c = MARK().quake;
  // outlines only, and only close in: thousands of them overlap at the region's scale
  map.addLayer({ id: 'quake-err-line', type: 'line', source: 'quake-err', minzoom: 10.5, layout: { visibility: 'none' },
    paint: { 'line-color': c, 'line-width': 0.9, 'line-opacity': ['interpolate', ['linear'], ['zoom'], 10.5, 0.25, 13, 0.6] } }, 'quakes');
}
function errVisible() {
  const on = $('#qk') && $('#qk').checked && $('#qk-err') && $('#qk-err').checked;
  for (const l of ['quake-err-line']) if (map.getLayer(l)) {
    map.setLayoutProperty(l, 'visibility', on ? 'visible' : 'none');
    if (window.StratumQuakes) map.setFilter(l, StratumQuakes.mapFilter());
  }
}

// ---------- export ----------
function download(blob, name) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = name;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}
function png() {
  map.once('render', () => {
    const src = map.getCanvas(), dpr = src.width / src.clientWidth;
    const c = document.createElement('canvas'); c.width = src.width; c.height = src.height + Math.round(26 * dpr);
    const g = c.getContext('2d');
    g.fillStyle = dark() ? '#0b1015' : '#ffffff'; g.fillRect(0, 0, c.width, c.height);
    g.drawImage(src, 0, 0);
    // the pad names are page elements over the map, not in its canvas: drawn in here
    g.font = `600 ${12 * dpr}px -apple-system,Segoe UI,Roboto,sans-serif`; g.textAlign = 'center'; g.textBaseline = 'top';
    const b = map.getBounds();
    if (map.getZoom() >= 11.5) for (const S of SETS) for (const p of S.pads) {
      if (!b.contains([p.lon, p.lat]) || (map.getLayer('pads') && map.getFilter('pads') && asOf && asOf.on && !map.queryRenderedFeatures(map.project([p.lon, p.lat]), { layers: ['pads'] }).length)) continue;
      const pt = map.project([p.lon, p.lat]), x = pt.x * dpr, y = (pt.y + 13) * dpr;
      g.lineWidth = 3 * dpr; g.strokeStyle = dark() ? '#0b1015' : '#ffffff'; g.strokeText(p.name, x, y);
      g.fillStyle = p.color; g.fillText(p.name, x, y);
    }
    g.font = `${11 * dpr}px -apple-system,Segoe UI,Roboto,sans-serif`; g.textAlign = 'left'; g.textBaseline = 'middle';
    g.fillStyle = dark() ? '#93a3b3' : '#566b78';
    const what = colourKey === 'pad' ? 'wells by pad' : 'wells by ' + M[colourKey].t.toLowerCase();
    g.fillText(`FracView · ${new Date().toISOString().slice(0, 10)} · ${what}${asOf && asOf.on ? ' · ' + ($('#asof-date') || {}).textContent : ''} · basemap Esri · data BC Energy Regulator (Open Data Licence)`, 10 * dpr, src.height + 13 * dpr);
    c.toBlob(bl => bl && download(bl, `FracView-map-${new Date().toISOString().slice(0, 10)}.png`), 'image/png');
  });
  map.triggerRepaint();
}
async function wellsInView() {
  const b = map.getBounds(), W = await wells(), out = [];
  const shown = new Set(map.getLayer('laterals') ? map.queryRenderedFeatures({ layers: ['laterals'] }).map(f => plain(f.properties.wa)) : []);
  for (const S of SETS) for (const p of S.pads) for (const w of p.wells) {
    if (!w.path || w.path.length < 2 || !w.path.some(c => b.contains(c))) continue;
    if (shown.size && !shown.has(plain(w.wa))) continue;
    out.push({ w, p, d: W.get(plain(w.wa)) || {} });
  }
  return out;
}
const PROPS = ['operator', 'formation', 'field', 'year', 'fracStart', 'fracEnd', 'firstProd', 'lateral', 'tvd', 'stages', 'stageSpacing', 'proppant', 'proppantPerM',
               'fluid', 'fluidPerM', 'avgP', 'isip', 'fg', 'tph', 'pumpMin', 'flagged', 'gas12', 'gas12Per100m', 'liq12', 'cgr12', 'peakGas', 'cumGas', 'cumLiq',
               'nnH', 'nnV', 'relation', 'bounded', 'depletionDays', 'quakes', 'quakeMax', 'gamma'];
async function geojson() {
  const list = await wellsInView();
  const fc = { type: 'FeatureCollection', name: 'FracView wells', features: list.map(({ w, p, d }) => ({ type: 'Feature', geometry: { type: 'LineString', coordinates: w.path },
    properties: { wa: w.wa, name: w.name, uwi: w.uwi || '', pad: p.name, padId: p.id, ...Object.fromEntries(PROPS.map(k => [k, d[k] ?? null])) } })) };
  download(new Blob([JSON.stringify(fc)], { type: 'application/geo+json' }), `FracView-wells-${list.length}.geojson`);
}
async function kml() {
  const list = await wellsInView(), x = s => esc(s).replace(/'/g, '&apos;');
  const body = list.map(({ w, p, d }) => `<Placemark><name>${x(w.name)}</name><description>${x(`WA ${w.wa} · ${p.name}${d.operator ? ' · ' + d.operator : ''}`)}</description>
<ExtendedData>${[['wa', w.wa], ['pad', p.name], ...PROPS.map(k => [k, d[k]])].filter(([, v]) => v != null).map(([k, v]) => `<Data name="${k}"><value>${x(v)}</value></Data>`).join('')}</ExtendedData>
<LineString><tessellate>1</tessellate><coordinates>${w.path.map(c => c[0].toFixed(6) + ',' + c[1].toFixed(6)).join(' ')}</coordinates></LineString></Placemark>`).join('\n');
  download(new Blob([`<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>FracView wells</name>\n${body}\n</Document></kml>`],
    { type: 'application/vnd.google-earth.kml+xml' }), `FracView-wells-${list.length}.kml`);
}

// ---------- pop-ups ----------
function padPopup(p, el) {
  const acts = $('.acts', el), L = lights && lights.pads[p.id];
  if (L && L.rule && areas) {
    const r = lights.rules[L.rule], lv = LEVEL[L.level];
    const line = document.createElement('div');
    line.className = 'facts tl';
    line.textContent = L.max == null ? `No earthquake within ${r.km} km of its laterals while it was fracked (${r.name.split(' (')[0]} rules).`
      : `${lv ? lv.s + ' ' + lv.t + ' level' : 'Below notification'}: largest ML ${L.max.toFixed(2)}, ${L.maxKm.toFixed(1)} km away on ${L.maxAt.slice(0, 10)} while it was fracked (${L.n} event${L.n === 1 ? '' : 's'}); today's ${L.rule === 'BC' ? 'province-wide' : L.rule} rules.`;
    if (lv) line.style.borderLeft = `4px solid ${lv[dark() ? 'dark' : 'light']}`;
    acts.before(line);
  }
  const w = document.createElement('button');
  w.type = 'button';
  const draw = () => { const on = window.StratumWatch && StratumWatch.has(p.id); w.textContent = on ? '★ Watching' : '☆ Watch'; w.title = on ? 'Stop watching this pad' : 'Hear about earthquakes and frac jobs near this pad (Menu › Watchlist)'; w.setAttribute('aria-pressed', String(!!on)); };
  w.onclick = async () => {
    if (!window.StratumWatch) return;
    w.disabled = true;
    try { await StratumWatch.toggle({ id: p.id, name: p.name, lat: p.lat, lon: p.lon }); } catch (e) { w.title = e.message; }
    w.disabled = false; draw();
  };
  acts.append(w);
  if (window.StratumWatch) StratumWatch.get().then(draw).catch(() => {}); else draw();
}
function wellPopup(p, el) {
  const a = document.createElement('a');
  a.href = `report.html?wa=${encodeURIComponent(p.wa)}`; a.textContent = 'Stage report ↗';
  a.title = 'Every stage’s metrics, flags and checks against the filing, in a window of its own';
  a.addEventListener('click', e => { e.preventDefault(); const w = window.open(a.href, 'stratum-report'); if (w) w.focus(); else location.href = a.href; });
  $('.acts', el).append(a);
}

// ---------- the legend's controls ----------
function controls() {
  const legend = $('.legend');
  if (!legend || $('#mc', legend)) return;
  const css = document.createElement('style');
  css.textContent = `.legend .mx{margin-top:7px;padding-top:7px;border-top:1px solid var(--line);display:flex;flex-direction:column;gap:5px;max-width:250px}
  .legend .mx label{display:flex;align-items:center;gap:6px}
  .legend .mx select{flex:1;min-width:0;background:var(--btn);color:var(--ink);border:1px solid var(--btn-line);border-radius:7px;padding:3px 6px;font:12px -apple-system,Segoe UI,Roboto,sans-serif}
  .legend #mc-key{display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;font-size:11.5px}
  .legend #mc-key small{flex-basis:100%;color:var(--mut)}
  .legend .mc-ramp{display:flex;align-items:center;gap:6px;font-variant-numeric:tabular-nums}
  .legend .mc-ramp i{display:inline-block;width:90px;height:8px;border-radius:4px}
  .legend .mc-rel{display:inline-flex;align-items:center;gap:4px}
  .legend .mc-rel i{display:inline-block;width:10px;height:10px;border-radius:3px}
  .legend .asof{display:flex;align-items:center;gap:6px}
  .legend .asof input[type=range]{flex:1;min-width:80px;accent-color:var(--go)}
  .legend .asof button,.legend .mx .xbtn{background:var(--btn);color:var(--ink);border:1px solid var(--btn-line);border-radius:7px;padding:2px 8px;font:600 11.5px -apple-system,Segoe UI,Roboto,sans-serif;cursor:pointer}
  .legend .asof button:hover,.legend .mx .xbtn:hover{border-color:var(--hov)}
  .legend #asof-date{color:var(--mut);font-size:11.5px}
  .legend .tlk{display:flex;gap:8px;flex-wrap:wrap;padding-left:20px;font-size:11.5px}
  .legend .tlk span{display:inline-flex;align-items:center;gap:3px}
  .legend .xrow{display:flex;gap:5px;flex-wrap:wrap}
  .pop .facts.tl{padding-left:7px;margin-top:6px}`;
  document.head.append(css);
  const box = document.createElement('div');
  box.className = 'mx';
  box.innerHTML = `<label>Colour wells by <select id="mc" aria-label="Colour wells by">${MEASURES.map(([k, t]) => `<option value="${k}">${esc(t)}</option>`).join('')}</select></label>
    <div id="mc-key" hidden></div>
    <label class="row qk"><input type="checkbox" id="asof-on"> As of a date</label>
    <div class="asof" id="asof-row" hidden><input type="range" id="asof" aria-label="Wells fracked by"><button type="button" id="asof-play" aria-label="Play through time">▶</button></div>
    <span id="asof-date"></span>
    <label class="row qk"><input type="checkbox" id="smma-on"> seismic monitoring areas (BCER)</label>
    <label class="row qk"><input type="checkbox" id="tl-on"> traffic light at each pad</label>
    <div class="tlk" id="tl-key" hidden>${Object.values(LEVEL).map(l => `<span><i style="display:inline-block;width:10px;height:10px;border-radius:50%;border:${l.w / 2 + 1}px solid ${l[dark() ? 'dark' : 'light']}"></i>${l.s} ${l.t}</span>`).join('')}</div>
    <div class="xrow"><button type="button" class="xbtn" id="x-png" title="The map as an image, pad names included">PNG</button><button type="button" class="xbtn" id="x-geo" title="The wells in view, with their measures, for GIS and Power BI">GeoJSON</button><button type="button" class="xbtn" id="x-kml" title="The wells in view for Google Earth">KML</button></div>`;
  legend.append(box);
  const qrow = $('#qk-frow');
  if (qrow) {
    const lab = document.createElement('label');
    lab.className = 'row qk qk-f'; lab.innerHTML = '<input type="checkbox" id="qk-err"> location error (zoom in)';
    lab.title = 'Each event’s location error: the regulator’s error ellipse, or the consortium’s error as a circle (from zoom 10.5)';
    qrow.after(lab);
    const sync = () => { lab.hidden = !$('#qk').checked; errVisible(); };
    $('#qk').addEventListener('change', sync); $('#qk-err').addEventListener('change', errVisible); sync();
    addEventListener('stratum:quakefilter', errVisible);
  }
  const sel = $('#mc');
  sel.value = colourKey;
  sel.onchange = () => { colourKey = sel.value; store.set('stratum.mapColour', colourKey === 'pad' ? null : colourKey); window.dispatchEvent(new CustomEvent('stratum:prefs')); applyColour(); };
  // as of: months from the first frac in the region to now
  wells().then(W => {
    const t = [...W.values()].map(w => day(w.fracStart)).filter(Boolean);
    if (!t.length) return;
    const r = $('#asof'), lo = monthOf(Math.min(...t)), hi = monthOf(Date.now());
    r.min = lo; r.max = hi; r.step = 1; r.value = asOf && asOf.m ? asOf.m : hi;
    $('#asof-on').checked = !!(asOf && asOf.on); $('#asof-row').hidden = !(asOf && asOf.on);
    $('#asof-on').onchange = e => { asOf = { on: e.target.checked, m: +r.value }; $('#asof-row').hidden = !asOf.on; if (!asOf.on) stop(); applyAsOf(); };
    r.oninput = () => { asOf = { on: true, m: +r.value }; applyAsOf(); };
    const stop = () => { clearInterval(playT); playT = 0; $('#asof-play').textContent = '▶'; };
    $('#asof-play').onclick = () => {
      if (playT) { stop(); return; }
      if (+r.value >= hi) r.value = lo;
      $('#asof-play').textContent = '❚❚';
      playT = setInterval(() => { if (+r.value >= hi) { stop(); return; } r.value = +r.value + 1; asOf = { on: true, m: +r.value }; applyAsOf(); }, 160);
    };
    applyAsOf();
  });
  $('#smma-on').onchange = e => { for (const l of ['smma-fill', 'smma-line']) if (map.getLayer(l)) map.setLayoutProperty(l, 'visibility', e.target.checked ? 'visible' : 'none'); };
  $('#tl-on').onchange = e => { if (map.getLayer('pads-tl')) map.setLayoutProperty('pads-tl', 'visibility', e.target.checked ? 'visible' : 'none'); $('#tl-key').hidden = !e.target.checked; };
  $('#x-png').onclick = png;
  $('#x-geo').onclick = geojson;
  $('#x-kml').onclick = kml;
}

afterLayers(async () => {
  controls();
  await seismicLayers().catch(e => console.warn('seismic layers', e));
  // the quake layer arrives a moment after the others
  const wait = () => map.getLayer('quakes') ? errorLayer().then(errVisible) : setTimeout(wait, 400);
  wait();
  applyColour(); applyAsOf();
});
addEventListener('stratum:theme', () => { setTimeout(() => { applyColour(); recolourLights(); if (map.getLayer('quake-err-line')) map.setPaintProperty('quake-err-line', 'line-color', MARK().quake); }, 0); });
addEventListener('stratum:spacing', () => { if (colourKey === 'relation') applyColour(); });
addEventListener('storage', e => { if (e.key === 'stratum.mapColour') { colourKey = M[e.newValue] ? e.newValue : 'pad'; const s = $('#mc'); if (s) s.value = colourKey; applyColour(); } });
// the map's layers come back after the charted-only box changes the data: colours and filters with them
const box = document.getElementById('charted');
if (box) box.addEventListener('change', () => setTimeout(() => { applyColour(); applyAsOf(); }, 50));

window.stratumMapExtras = { padPopup, wellPopup, applyColour, applyAsOf, png, geojson, kml };
})();
