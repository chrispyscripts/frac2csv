(() => {
'use strict';
// The DLS and NTS survey grids, as pmtiles vector tiles out of data/grids/.
// Levels are separate archives so each can be tiled only over the zooms where it
// is legible; MapLibre overzooms past an archive's max, so a level stays drawn
// once it switches on.

// MapLibre 4 wants a promise-returning protocol handler. pmtiles 3 still exposes
// `.tile`, but that is the v3 callback shim (it returns {cancel}, not a promise)
// and silently breaks every tile here -- `.tilev4` is the one to register.
maplibregl.addProtocol('pmtiles', new pmtiles.Protocol().tilev4);

const NTS = '#7fb2d9', DLS = '#e2a75f';

// deg: nominal cell size [lon, lat], used to gate labelling on on-screen size.
// A cell split across a tile boundary arrives in pieces, so its drawn size is
// not its real size -- the nominal size is what decides whether it gets a label.
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
];
const BY_ID = Object.fromEntries(LEVELS.map(l => [l.id, l]));

const MIN_LABEL_PX = 46;    // smaller than this and the text does not fit the cell
const MAX_LABEL_PX = 2600;  // bigger than this and the level's label is off-screen anyway
const MAX_MARKERS  = 220;   // a hard ceiling; nts_qtr would otherwise place thousands

const on = { nts: true, dls: false };
let available = [];         // levels whose archive actually loaded

// ---------------------------------------------------------------- layer setup
async function probe(L) {
  try {
    const r = await fetch('data/grids/' + L.id + '.pmtiles', { headers: { Range: 'bytes=0-15' } });
    return r.ok ? L : null;
  } catch (e) { return null; }
}

function addLayers(levels) {
  // keep the grid under the wells, whichever order the two modules finish in
  const overlay = ['areas-fill', 'areas-line', 'laterals-halo', 'laterals', 'toes', 'pads'];
  const before = (map.getStyle().layers || []).map(l => l.id).find(id => overlay.includes(id));
  // finest first, so the coarser, heavier lines draw over shared borders
  for (const L of [...levels].reverse()) {
    map.addSource(L.id, { type: 'vector', url: 'pmtiles://data/grids/' + L.id + '.pmtiles' });
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
        'line-color': L.fam === 'nts' ? NTS : DLS,
        'line-opacity': L.op,
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
  const twp = s.dls_twp && s.dls_twp.label, sec = s.dls_sec && s.dls_sec.label,
        lsd = s.dls_lsd && s.dls_lsd.n;
  if (twp) {
    const m = /^(\d+)-(\d+)W(\d+)$/.exec(twp);
    if (m) {
      let loc = '';
      if (lsd != null && sec) loc = `${pad(lsd, 2)}-${pad(sec, 2)}-`;
      else if (sec)           loc = `${pad(sec, 2)}-`;
      rows.push(['DLS', `${loc}${pad(m[1], 3)}-${pad(m[2], 2)}W${m[3]}`]);
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
    <button type="button" data-fam="nts" class="on">NTS</button>
    <button type="button" data-fam="dls">DLS</button></span>`;
  box.append(row);
  row.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
    const fam = b.dataset.fam;
    on[fam] = !on[fam];
    b.classList.toggle('on', on[fam]);
    for (const L of available) if (L.fam === fam) for (const pre of ['grid-', 'grid-hit-'])
      if (map.getLayer(pre + L.id))
        map.setLayoutProperty(pre + L.id, 'visibility', on[fam] ? 'visible' : 'none');
    if (!on.nts && !on.dls) { clearLabels(); readout.hidden = true; } else relabel();
  }));
}

// ------------------------------------------------------------------------ wire
async function start() {
  const levels = (await Promise.all(LEVELS.map(probe))).filter(Boolean);
  if (!levels.length) return;
  const missing = LEVELS.filter(L => !levels.includes(L)).map(L => L.id);
  if (missing.length) console.warn('survey grid: no archive for ' + missing.join(', '));
  addLayers(levels);
  control();
  map.on('moveend', relabel);
  // 'load' fires before any tile has rendered, so the first relabel finds nothing
  // to place; 'idle' is when the tiles are actually up.
  map.on('idle', relabel);
  map.on('mousemove', e => queueReadout(e.point));
  map.on('mouseout', () => { readout.hidden = true; });
  relabel();
}

if (map.isStyleLoaded()) start(); else map.on('load', start);
})();
