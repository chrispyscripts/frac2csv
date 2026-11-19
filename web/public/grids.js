(() => {
'use strict';
// The DLS and NTS survey grids, as pmtiles vector tiles out of data/grids/.
// Levels are separate archives so each can be tiled only over the zooms where it
// is legible; MapLibre overzooms past an archive's max, so a level stays drawn
// once it switches on.
//
// The Saskatchewan DLS (sk_*) is ISC's SaskGrid, whose licence does not allow it
// to be published: it is never in this repo or on the live site. A local copy
// builds it outside the repo (scripts/grids/build_skgrid.sh) and the local
// server mounts it at data/skgrid/ (scripts/serve.py --mount). Where it is not
// there the levels simply don't load and the map goes on without them; where it
// is, they draw as part of the DLS, under ISC's source notice.

// MapLibre 4 wants a promise-returning protocol handler. pmtiles 3 still exposes
// `.tile`, but that is the v3 callback shim (it returns {cancel}, not a promise)
// and silently breaks every tile here -- `.tilev4` is the one to register.
maplibregl.addProtocol('pmtiles', new pmtiles.Protocol().tilev4);

// line colour per family, [light, dark] -- the theme (theme.js) is read as the
// layers are added and again whenever it changes. grids.css carries the same
// pair for the legend's toggle buttons.
const LINE = { nts: ['#2f6aa3', '#7fb2d9'], dls: ['#b45309', '#e2a75f'] };
const dark = () => !!(window.StratumTheme && StratumTheme.dark());
const lineColour = fam => LINE[fam][dark() ? 1 : 0];
// dark lines on white read heavier than light ones on dark: lighter-handed in the light theme
const lineOpacity = L => L.op * (dark() ? 1 : 0.6);

// deg: nominal cell size [lon, lat], used to gate labelling on on-screen size.
// A cell split across a tile boundary arrives in pieces, so its drawn size is
// not its real size -- the nominal size is what decides whether it gets a label.
// (A DLS cell's width in degrees grows northward; the BC sizes are taken at 56N,
// the SK ones at 52N, the middle of the province's oil country.)
// sk: from the Saskatchewan set, which lives at data/skgrid/ where it is at all.
const SK_DIR = 'data/skgrid/';
const SK_NOTICE = 'Source: Information Services Corporation, SaskGrid Township Fabric Map.';
const SK_DISCLAIMER = 'The incorporation of data sourced from the Information Services Corporation within this product shall not be construed as constituting an endorsement by the Information Services Corporation of such product.';
const LEVELS = [
  { id:'nts_pri',  fam:'nts', z:4,    w:2.4, op:.85, deg:[8, 4]            },
  { id:'nts_ltr',  fam:'nts', z:5,    w:1.9, op:.78, deg:[2, 1]            },
  { id:'nts_six',  fam:'nts', z:6.5,  w:1.5, op:.68, deg:[0.5, 0.25]       },
  { id:'nts_blk',  fam:'nts', z:8.5,  w:1.15,op:.55, deg:[0.125, 1/12]     },
  { id:'nts_unit', fam:'nts', z:12,   w:0.85,op:.42, deg:[0.0125, 1/120]   },
  { id:'nts_qtr',  fam:'nts', z:14,   w:0.6, op:.32, deg:[0.00625, 1/240]  },
  { id:'dls_twp',  fam:'dls', z:8,    w:1.6, op:.72, deg:[0.155, 0.0872]   },
  { id:'dls_sec',  fam:'dls', z:11,   w:1.0, op:.5,  deg:[0.0255, 0.01446] },
  { id:'dls_lsd',  fam:'dls', z:13,   w:0.7, op:.34, deg:[0.0064, 0.0036]  },
  // Saskatchewan: the BC levels' zooms and weights, plus the quarter section
  // between section and LSD -- the unit SK land is held and described by.
  { id:'sk_twp',   fam:'dls', z:8,    w:1.6, op:.72, deg:[0.141, 0.0869],   sk:true },
  { id:'sk_sec',   fam:'dls', z:11,   w:1.0, op:.5,  deg:[0.0235, 0.01447], sk:true },
  { id:'sk_qtr',   fam:'dls', z:12,   w:0.85,op:.42, deg:[0.01174, 0.00724],sk:true },
  { id:'sk_lsd',   fam:'dls', z:13,   w:0.7, op:.34, deg:[0.00587, 0.00362],sk:true },
];
const BY_ID = Object.fromEntries(LEVELS.map(l => [l.id, l]));
const archive = L => (L.sk ? SK_DIR : 'data/grids/') + L.id + '.pmtiles';

const MIN_LABEL_PX = 46;    // smaller than this and the text does not fit the cell
const MAX_LABEL_PX = 2600;  // bigger than this and the level's label is off-screen anyway
const MAX_MARKERS  = 220;   // a hard ceiling; nts_qtr would otherwise place thousands

const on = { nts: true, dls: false };
const GRID_KEY = 'stratum.grids';
try { Object.assign(on, JSON.parse(sessionStorage.getItem(GRID_KEY) || '{}')); } catch (e) { /* private mode */ }
const saveGrids = () => { try { sessionStorage.setItem(GRID_KEY, JSON.stringify(on)); } catch (e) { /* private mode */ } };
if (window.StratumSession) StratumSession.provide(() => ({ [GRID_KEY]: JSON.stringify(on) }));
let available = [];         // levels whose archive actually loaded

// ---------------------------------------------------------------- layer setup
// An archive counts only if it is really there: a 200 that is not a pmtiles
// archive (an HTML fallback page, say) would otherwise fail on every tile. Only
// the first chunk is read, so a server that ignores Range costs nothing either.
async function probe(L) {
  try {
    const r = await fetch(archive(L), { headers: { Range: 'bytes=0-15' } });
    if (!r.ok || !r.body) return null;
    const rd = r.body.getReader();
    const { value } = await rd.read();
    rd.cancel().catch(() => {});
    return value && value.length >= 7 && String.fromCharCode(...value.subarray(0, 7)) === 'PMTiles' ? L : null;
  } catch (e) { return null; }
}

// The SK set is all there or not at all, and on the live site it is never there:
// ask for its township archive once, and the rest only if that one came back.
async function probeAll() {
  const bc = LEVELS.filter(L => !L.sk), sk = LEVELS.filter(L => L.sk);
  const [found, first] = await Promise.all([Promise.all(bc.map(probe)), probe(sk[0])]);
  const skFound = first ? [first, ...await Promise.all(sk.slice(1).map(probe))] : [];
  const missing = bc.filter((L, i) => !found[i]).map(L => L.id);
  if (first) missing.push(...sk.filter(L => !skFound.includes(L)).map(L => L.id));
  if (missing.length) console.warn('survey grid: no archive for ' + missing.join(', '));
  return LEVELS.filter(L => found.includes(L) || skFound.includes(L));
}

function addLayers(levels) {
  // keep the grid under the wells, whichever order the two modules finish in
  const overlay = ['areas-fill', 'areas-line', 'laterals-halo', 'laterals', 'toes', 'pads'];
  const before = (map.getStyle().layers || []).map(l => l.id).find(id => overlay.includes(id));
  // finest first, so the coarser, heavier lines draw over shared borders
  for (const L of [...levels].reverse()) {
    // the attribution control shows a source's notice while its layers are drawn
    map.addSource(L.id, Object.assign({ type: 'vector', url: 'pmtiles://' + archive(L) },
                                      L.sk ? { attribution: SK_NOTICE } : {}));
    // An invisible fill per level, purely to hit-test against: these are LINE
    // layers, so querying a point only finds a cell when the cursor is on its
    // boundary -- the readout needs the cell the cursor is INSIDE.
    map.addLayer({
      id: 'grid-hit-' + L.id, type: 'fill', source: L.id, 'source-layer': L.id,
      minzoom: L.z,
      layout: { visibility: on[L.fam] ? 'visible' : 'none' },
      paint: { 'fill-opacity': 0 }
    }, before);
    map.addLayer({
      id: 'grid-' + L.id, type: 'line', source: L.id, 'source-layer': L.id,
      minzoom: L.z,
      layout: { visibility: on[L.fam] ? 'visible' : 'none', 'line-join': 'round' },
      paint: {
        'line-color': lineColour(L.fam),
        'line-opacity': lineOpacity(L),
        'line-width': ['interpolate', ['linear'], ['zoom'], L.z, L.w, L.z + 4, L.w * 1.45]
      }
    }, before);
    available.push(L);
  }
}

// ------------------------------------------------------------------- labelling
// The base style carries no glyphs, so a symbol layer draws nothing here (the pad
// names are HTML markers for the same reason). Labels are markers placed at each
// feature's own cx/cy, which is identical on every piece of a split cell -- so a
// cell that straddles a tile seam still gets exactly one label, in the right spot.
const markers = new Map();

function cellPx(L) {
  const c = map.getCenter();
  const a = map.project([c.lng, c.lat]);
  const b = map.project([c.lng + L.deg[0], c.lat]);
  const d = map.project([c.lng, c.lat + L.deg[1]]);
  return Math.min(Math.abs(b.x - a.x), Math.abs(d.y - a.y));
}

function labelText(p) {
  return p.n != null && p.n !== '' ? String(p.n) : (p.label || '');
}

function relabel() {
  const z = map.getZoom();
  const layers = available
    .filter(L => on[L.fam] && z >= L.z)
    .filter(L => { const px = cellPx(L); return px >= MIN_LABEL_PX && px <= MAX_LABEL_PX; })
    .map(L => 'grid-' + L.id)
    .filter(id => map.getLayer(id));

  const want = new Map();
  if (layers.length) {
    for (const f of map.queryRenderedFeatures({ layers })) {
      const p = f.properties, t = labelText(p);
      if (!t || p.cx == null) continue;
      const key = f.layer.id + ':' + p.cx + ',' + p.cy;
      if (!want.has(key)) want.set(key, { lng: p.cx, lat: p.cy, text: t, fam: BY_ID[f.layer.id.slice(5)].fam });
      if (want.size >= MAX_MARKERS) break;
    }
  }
  for (const [key, m] of markers) if (!want.has(key)) { m.remove(); markers.delete(key); }
  for (const [key, v] of want) {
    if (markers.has(key)) continue;
    const el = document.createElement('div');
    el.className = 'gridlabel ' + v.fam;
    el.textContent = v.text;
    markers.set(key, new maplibregl.Marker({ element: el, anchor: 'center' })
      .setLngLat([v.lng, v.lat]).addTo(map));
  }
}

function recolour() {
  for (const L of available) if (map.getLayer('grid-' + L.id)) {
    map.setPaintProperty('grid-' + L.id, 'line-color', lineColour(L.fam));
    map.setPaintProperty('grid-' + L.id, 'line-opacity', lineOpacity(L));
  }
}

function clearLabels() {
  for (const [, m] of markers) m.remove();
  markers.clear();
}

// -------------------------------------------------------------- the readout
// Each level knows only its own relative label, so the fully-qualified location
// is assembled from every grid layer under the cursor at once -- no offline join.
const readout = document.createElement('div');
readout.className = 'gridread';
readout.hidden = true;
document.body.append(readout);

const pad = (v, n) => String(v).padStart(n, '0');
const last = s => String(s).split('-').pop();

function stack(pt) {
  const layers = available.filter(L => on[L.fam] && map.getLayer('grid-hit-' + L.id))
                          .map(L => 'grid-hit-' + L.id);
  const out = {};
  if (!layers.length) return out;
  for (const f of map.queryRenderedFeatures(pt, { layers })) {
    const id = f.layer.id.slice(9);
    if (!(id in out)) out[id] = f.properties;
  }
  return out;
}

function describe(s) {
  const rows = [];
  const pri = s.nts_pri && s.nts_pri.label, ltr = s.nts_ltr && s.nts_ltr.label,
        six = s.nts_six && s.nts_six.label, blk = s.nts_blk && s.nts_blk.label,
        unit = s.nts_unit && s.nts_unit.n,  qtr = s.nts_qtr && s.nts_qtr.label;
  if (pri) {
    let map_ = pad(pri, 3);
    if (ltr) map_ += '-' + last(ltr);
    if (six) map_ += '-' + pad(last(six), 2);
    let loc = '';
    if (qtr && unit != null && blk) loc = `${qtr}-${pad(unit, 3)}-${blk}/`;
    else if (unit != null && blk)   loc = `${pad(unit, 3)}-${blk}/`;
    else if (blk)                   loc = `${blk}/`;
    rows.push(['NTS', loc + map_]);
  }
  // BC and SK never overlap, so whichever province is under the cursor answers.
  // SK adds the quarter section, shown until the LSD level is drawn; a few SK
  // townships, ranges and sections carry a letter (a fractional survey), kept.
  const dl = id => s['dls_' + id] || s['sk_' + id] || {};
  const twp = dl('twp').label, sec = dl('sec').label, lsd = dl('lsd').n,
        quarter = s.sk_qtr && s.sk_qtr.label;
  const padn = (v, n) => String(v).replace(/^\d+/, d => d.padStart(n, '0'));
  if (twp) {
    const m = /^(\d+[A-Z]?)-(\d+[A-Z]?)W(\d+)$/.exec(twp);
    if (m) {
      let loc = '';
      if (lsd != null && sec) loc = `${pad(lsd, 2)}-${padn(sec, 2)}-`;
      else if (quarter && sec) loc = `${quarter}-${padn(sec, 2)}-`;
      else if (sec)           loc = `${padn(sec, 2)}-`;
      rows.push(['DLS', `${loc}${padn(m[1], 3)}-${padn(m[2], 2)}W${m[3]}`]);
    }
  }
  return rows;
}

let pending = null, raf = 0;
function queueReadout(pt) {
  pending = pt;
  if (raf) return;
  raf = requestAnimationFrame(() => { raf = 0; showReadout(pending); });
}

function showReadout(pt) {
  const rows = describe(stack(pt));
  if (!rows.length) { readout.hidden = true; return; }
  readout.innerHTML = rows.map(([k, v]) => `<span class="k">${k}</span><span class="v">${v}</span>`).join('');
  readout.hidden = false;
}

// ------------------------------------------------------------------ the toggle
function control() {
  const box = document.querySelector('.legend');
  if (!box) return;
  const row = document.createElement('div');
  row.className = 'gridtoggle';
  row.innerHTML = `<span class="lab">survey grid</span><span class="btns">
    <button type="button" data-fam="nts" class="${on.nts ? 'on' : ''}">NTS</button>
    <button type="button" data-fam="dls" class="${on.dls ? 'on' : ''}">DLS</button></span>`;
  box.append(row);
  // ISC's licence asks for its notice wherever SaskGrid is shown: here while the
  // DLS is on, and in the map's attribution while an SK level is drawn.
  let note = null;
  if (available.some(L => L.sk)) {
    note = document.createElement('div');
    note.className = 'gridsrc';
    note.textContent = SK_NOTICE;
    note.title = SK_DISCLAIMER;
    note.hidden = !on.dls;
    box.append(note);
  }
  row.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
    const fam = b.dataset.fam;
    on[fam] = !on[fam]; saveGrids();
    b.classList.toggle('on', on[fam]);
    if (note) note.hidden = !on.dls;
    for (const L of available) if (L.fam === fam) for (const pre of ['grid-', 'grid-hit-'])
      if (map.getLayer(pre + L.id))
        map.setLayoutProperty(pre + L.id, 'visibility', on[fam] ? 'visible' : 'none');
    if (!on.nts && !on.dls) { clearLabels(); readout.hidden = true; } else relabel();
  }));
}

// ------------------------------------------------------------------------ wire
async function start() {
  const levels = await probeAll();
  if (!levels.length) return;
  addLayers(levels);
  control();
  map.on('moveend', relabel);
  // 'load' fires before any tile has rendered, so the first relabel finds nothing
  // to place; 'idle' is when the tiles are actually up.
  map.on('idle', relabel);
  map.on('mousemove', e => queueReadout(e.point));
  map.on('mouseout', () => { readout.hidden = true; });
  addEventListener('stratum:theme', recolour);
  relabel();
}

if (map.isStyleLoaded()) start(); else map.on('load', start);
})();
