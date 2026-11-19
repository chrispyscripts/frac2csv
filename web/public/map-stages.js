// FracView — the stages on the map, once it is zoomed in close enough to tell
// them apart: a dot for each stage where it sits along its lateral, placed by
// MD on the pad file's trajectory (stage-datasets-core.js stagePoints, the
// same depths the stage charts' datasets use). Only the wells the map is
// drawing get them, and only the pads in view are read.
//
// Pointing at a stage picks it out, names it by the pointer and shows it in the
// Data window (data-window.js). Clicking one opens its popup: what was filed
// for it, its chart (where the Lab has read its curves) and the well section on
// that stage; with the Data window open the stage is stacked there too (the
// popup's button opens one on it). The wells and stages stacked in the Data
// window are ringed on the map.
//
//   stratumStages.hover(props | null, point)   from map.html's pointer
//   stratumStages.open(props, lngLat)          from map.html's click
(() => {
'use strict';
const C = window.StageDatasetsCore, SL = window.StratumLogs;
if (!C || typeof map === 'undefined') return;
const MINZ = 13, MAXPADS = 60;
const fmt = (v, d = 0) => (v == null || !isFinite(v) ? '–' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));
const getJSON = u => fetch(u).then(r => { if (!r.ok) throw Error(String(r.status)); return r.json(); });
const padFiles = new Map();          // pad id -> Promise of the pad file (or null)
const padFile = id => {
  if (!padFiles.has(id)) padFiles.set(id, getJSON(SL ? SL.padUrl(id) : 'data/region/pads/' + encodeURIComponent(id) + '.json').catch(() => null));
  return padFiles.get(id);
};
const NONE = ['==', ['get', 'id'], '\u0000'];
const empty = { type: 'FeatureCollection', features: [] };
const shownPads = () => (typeof SETS !== 'undefined' ? SETS.flatMap(S => S.pads) : []);

// ---------- the layers: under the pads, over the laterals ----------
function addLayers() {
  if (map.getSource('stages')) return;
  const k = MARK();
  map.addSource('stages', { type: 'geojson', data: empty });
  const before = map.getLayer('pads') ? 'pads' : undefined;
  const r = (a, b, c) => ['interpolate', ['linear'], ['zoom'], MINZ, a, 15, b, 17.5, c];
  map.addLayer({ id: 'stages', type: 'circle', source: 'stages', minzoom: MINZ,
    paint: { 'circle-radius': r(2.4, 4.2, 7), 'circle-color': ['get', 'color'], 'circle-stroke-color': k.toeRing,
             'circle-stroke-width': r(0.6, 1.2, 1.6), 'circle-opacity': ['interpolate', ['linear'], ['zoom'], MINZ, 0, MINZ + 0.4, 1] } }, before);
  map.addLayer({ id: 'stages-sel', type: 'circle', source: 'stages', minzoom: MINZ, filter: NONE,
    paint: { 'circle-radius': r(6, 8, 12), 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': k.sel, 'circle-stroke-width': 3 } }, before);
  // the ones stacked in the Data window
  map.addLayer({ id: 'stages-picked', type: 'circle', source: 'stages', minzoom: MINZ, filter: NONE,
    paint: { 'circle-radius': r(5, 7, 11), 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': k.sel, 'circle-stroke-width': 2, 'circle-stroke-opacity': .85 } }, before);
  if (map.getSource('laterals')) map.addLayer({ id: 'laterals-picked', type: 'line', source: 'laterals', filter: ['in', ['get', 'wa'], ['literal', []]],
    paint: { 'line-color': k.sel, 'line-width': ['interpolate', ['linear'], ['zoom'], 8, 3, 12, 7], 'line-opacity': .35 },
    layout: { 'line-cap': 'round', 'line-join': 'round' } }, map.getLayer('laterals') ? 'laterals' : undefined);
  map.addLayer({ id: 'stages-hl', type: 'circle', source: 'stages', minzoom: MINZ, filter: NONE,
    paint: { 'circle-radius': r(4.5, 6.5, 10), 'circle-color': ['get', 'color'], 'circle-stroke-color': k.hl, 'circle-stroke-width': 2 } }, before);
  map.on('moveend', update);
  addEventListener('stratum:theme', () => {
    const m = MARK();
    if (map.getLayer('stages')) map.setPaintProperty('stages', 'circle-stroke-color', m.toeRing);
    if (map.getLayer('stages-hl')) map.setPaintProperty('stages-hl', 'circle-stroke-color', m.hl);
    if (map.getLayer('stages-sel')) map.setPaintProperty('stages-sel', 'circle-stroke-color', m.sel);
    if (map.getLayer('stages-picked')) map.setPaintProperty('stages-picked', 'circle-stroke-color', m.sel);
    if (map.getLayer('laterals-picked')) map.setPaintProperty('laterals-picked', 'line-color', m.sel);
    update();
  });
  // the wells shown change (the legend's filter, a dropped file): so do their stages
  document.getElementById('charted').addEventListener('change', () => setTimeout(update, 0));
  addEventListener('stratum:dropped', () => { for (const id of [...padFiles.keys()]) if (/^drop-/.test(id)) padFiles.delete(id); setTimeout(update, 0); });
  addEventListener('stratum:datapicks', marks);
  marks();
  update();
}
// the Data window's picks: a stage ringed, a well (picked whole) drawn over in a wash
function marks() {
  const P = (window.stratumDataWindow && stratumDataWindow.picks) || [];
  if (map.getLayer('stages-picked')) map.setFilter('stages-picked', ['in', ['get', 'id'], ['literal', P.filter(p => p.label != null).map(p => p.wa + '|' + p.label)]]);
  if (map.getLayer('laterals-picked')) map.setFilter('laterals-picked', ['in', ['get', 'wa'], ['literal', P.filter(p => p.label == null).map(p => p.wa)]]);
}

// ---------- the stages in view ----------
let seq = 0;
async function update() {
  const src = map.getSource('stages');
  if (!src) return;
  if (map.getZoom() < MINZ - 0.25) return;            // (kept as they were: the layer hides them below MINZ)
  const my = ++seq, b = map.getBounds(), c = map.getCenter(), k = Math.cos(c.lat * Math.PI / 180);
  // the pads whose wells reach into view (a pad off screen can have its laterals on it)
  const reach = p => p.wells.some(w => Array.isArray(w.path) && w.path.some(q => b.contains(q))) || b.contains([p.lon, p.lat]);
  const near = p => Math.hypot(p.lat - c.lat, (p.lon - c.lng) * k);
  const pads = shownPads().filter(reach).sort((x, y) => near(x) - near(y)).slice(0, MAXPADS);
  const files = await Promise.all(pads.map(p => padFile(p.id)));
  if (my !== seq) return;
  const feats = [];
  pads.forEach((p, i) => {
    const f = files[i];
    if (!f || !Array.isArray(f.wells)) return;
    const drawn = new Map(p.wells.map(w => [String(w.wa), w]));
    for (const fw of f.wells) {
      const wa = String((fw.well && fw.well.wa) || '');
      const mw = drawn.get(wa);
      if (!mw) continue;                            // a well the map is not drawing
      for (const s of stagePts(fw)) feats.push({ type: 'Feature', geometry: { type: 'Point', coordinates: s.at },
        properties: { id: wa + '|' + s.label, wa, label: s.label, top: s.top, base: s.base, md: s.md, color: p.color, pad: p.id, padName: p.name, name: mw.name || wa } });
    }
  });
  src.setData({ type: 'FeatureCollection', features: feats });
}
const ptsCache = new WeakMap();
function stagePts(fw) { if (!ptsCache.has(fw)) ptsCache.set(fw, C.stagePoints(fw)); return ptsCache.get(fw); }

// ---------- pointing, and the tip by the pointer ----------
const tip = document.createElement('div');
tip.className = 'stg-tip'; tip.hidden = true; tip.setAttribute('aria-hidden', 'true');
document.body.append(tip);
let hot = null;
function hover(p, pt) {
  const id = p ? p.id : null;
  if (id !== hot && map.getLayer('stages-hl')) { hot = id; map.setFilter('stages-hl', id ? ['==', ['get', 'id'], id] : NONE); }
  if (!p || !pt) { tip.hidden = true; return; }
  tip.replaceChildren();
  const b = document.createElement('b'); b.textContent = `Stage ${p.label}`;
  const s = document.createElement('span');
  s.textContent = ` ${p.top === p.base ? fmt(p.top) : fmt(p.top) + '–' + fmt(p.base)} m MD`;
  tip.append(b, s);
  const r = map.getContainer().getBoundingClientRect();
  tip.style.left = (r.left + pt.x + 14) + 'px'; tip.style.top = (r.top + pt.y + 12) + 'px';
  tip.hidden = false;
}
map.getCanvas().addEventListener('mouseleave', () => hover(null));
map.on('movestart', () => { tip.hidden = true; });

// ---------- a stage's popup ----------
const letters = () => Array.from({ length: 6 }, () => String.fromCharCode(97 + Math.floor(Math.random() * 26))).join('');
const stageUrl = (wa, label) => `stages.html?s=${encodeURIComponent(wa)}:${encodeURIComponent(label)}`;
function select(id) { if (map.getLayer('stages-sel')) map.setFilter('stages-sel', id ? ['==', ['get', 'id'], id] : NONE); }
async function open(p, lngLat) {
  hover(null);
  if (popup) popup.remove();
  select(p.id);
  popup = new maplibregl.Popup({ closeButton: true, maxWidth: '330px' }).setLngLat(lngLat)
    .setHTML(`<div class="pop"><b></b><div class="facts"></div><dl class="stg-facts"></dl><div class="acts">
      <button type="button" class="go" data-act="dw"></button><button type="button" data-act="ws">View well</button></div></div>`).addTo(map);
  const el = popup.getElement(), me = popup;
  me.on('close', () => select(null));
  el.querySelector('.pop > b').textContent = `Stage ${p.label} · ${p.name}`;
  el.querySelector('.facts').textContent = `${p.top === p.base ? fmt(p.top, 1) : fmt(p.top, 1) + '–' + fmt(p.base, 1)} m MD · ${p.padName}`;
  // with the Data window open, the stage is stacked there; the button brings the window forward (or opens one on it)
  const DW = window.stratumDataWindow, dwb = el.querySelector('[data-act=dw]');
  const stacked = !!(DW && DW.shown && DW.pick(p.wa, p.label, p.name));
  dwb.textContent = stacked ? 'In the Data window ↗' : 'Data window ↗';
  dwb.title = stacked ? 'Stacked in the Data window: bring it forward' : 'Open the Data window on this stage: its well’s datasets around it, along MD';
  dwb.addEventListener('click', () => { if (DW) DW.pick(p.wa, p.label, p.name, true); });
  el.querySelector('[data-act=ws]').title = 'The well in 2D, docked below, with this stage picked out';
  el.querySelector('[data-act=ws]').addEventListener('click', () => { if (window.stratumSection) stratumSection.view(p.wa, p.label); });
  // what was filed for it, from its pad file
  const f = await padFile(p.pad), fw = f && (f.wells || []).find(w => w.well && String(w.well.wa) === String(p.wa));
  if (popup !== me) return;
  const dl = el.querySelector('.stg-facts');
  for (const [k, v] of fw ? C.stageFacts(fw, p.label) : []) {
    const dt = document.createElement('dt'), dd = document.createElement('dd');
    dt.textContent = k; dd.textContent = v; dl.append(dt, dd);
  }
  // its chart, where the Lab has read the stage's curves (the well file says)
  if (SL && SL.isLocalWell(p.wa)) return;
  try {
    const d = await getJSON(SL ? SL.wellUrl(p.wa) : `data/wells/${encodeURIComponent(p.wa)}.json`);
    const st = (d.stages || []).find(s => String(s.label != null ? s.label : s.n) === String(p.label));
    const has = st && st.series && Object.values(st.series).some(a => Array.isArray(a) && a.some(v => v != null));
    if (!has || popup !== me) return;
    const a = document.createElement('button');
    a.type = 'button'; a.textContent = 'Stage chart ↗'; a.title = 'This stage’s treatment chart, in a window of its own';
    a.addEventListener('click', () => {
      const w = window.open(stageUrl(p.wa, p.label), 'stratum-stages' + letters(), 'popup,width=1180,height=820');
      if (w) { try { w.focus(); } catch (e) { /* the browser decides */ } } else location.href = stageUrl(p.wa, p.label);
    });
    el.querySelector('.acts').append(a);
  } catch (e) { /* no well file: no chart */ }
}

afterLayers(addLayers);
window.stratumStages = { hover, open, update };
})();
