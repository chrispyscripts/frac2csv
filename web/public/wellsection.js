// Stratum — one well end to end, as a vertical section: surface to TD along the
// line from the pad to the toe, the stages at their measured depths, gamma
// along the lateral. Docked under the map or the 3D view (?embedded=1, driven
// by its parent over postMessage), or popped out into a window of its own that
// follows the well being looked at in the main window (BroadcastChannel
// 'stratum-section': the map, the 3D view and the well charts all announce it).
'use strict';
const $ = id => document.getElementById(id);
const Q = new URLSearchParams(location.search);
const EMBED = Q.get('embedded') === '1';
const ORIGIN = location.origin;
const PREF_KEY = 'stratum.section';

// gamma: the 3D view's amber ramp, dark for low API (cleaner rock) to cream for high
const GAMMA_RAMP = ['#92500b', '#ac5c00', '#c36c00', '#d57f00', '#e29500', '#eaad4a', '#eec57e', '#f2dcb1', '#fef1d0'];
const NEUTRAL = '#d6e6ee', BUILD = '#8fa9b5', CURVES = '#5ee2d0', FILED = '#6b8290', GR_MAX = 250;
const rgb = s => [1, 3, 5].map(j => parseInt(s.slice(j, j + 2), 16));
function gammaInk(v, lo, hi) {
  const t = Math.max(0, Math.min(1, (v - lo) / (hi - lo))) * (GAMMA_RAMP.length - 1);
  const i = Math.min(GAMMA_RAMP.length - 2, Math.floor(t)), f = t - i, a = rgb(GAMMA_RAMP[i]), b = rgb(GAMMA_RAMP[i + 1]);
  return `rgb(${a.map((x, j) => Math.round(x + (b[j] - x) * f)).join(',')})`;
}

let WA = Q.get('wa') || '';
let HI = Q.get('stage');        // the stage picked out, by label
let mode = 'well', colorBy = 'stages';
try { const p = JSON.parse(localStorage.getItem(PREF_KEY) || '{}'); if (p.mode) mode = p.mode; if (p.color) colorBy = p.color; } catch (e) { /* private mode */ }
let W = null;                   // the assembled well: trajectory, stages, gamma
let GAMMA = null;               // data/gamma.json, fetched once
let G = null;                   // this render's geometry, for hover
let hover = null, seq = 0;

const fmt = (v, d = 0) => v == null || !isFinite(v) ? '–'
  : (Math.abs(v) < 0.5 * Math.pow(10, -d) ? 0 : Number(v)).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d });
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
const compass = deg => COMPASS[Math.round(((deg % 360) + 360) % 360 / 22.5) % 16];
function niceStep(span, n) {
  const raw = span / Math.max(1, n), p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
}

const cache = new Map();
function getJSON(u) {
  if (!cache.has(u)) cache.set(u, fetch(u).then(r => { if (!r.ok) throw Error(`${u}: ${r.status}`); return r.json(); })
    .catch(e => { cache.delete(u); throw e; }));
  return cache.get(u);
}

// ---------- data ----------
async function load(wa) {
  const my = ++seq;
  WA = String(wa); W = null; hover = null;
  $('ws-name').textContent = 'Loading…'; $('ws-sub').textContent = '';
  let d, row = null;
  try { d = await getJSON(`data/wells/${encodeURIComponent(WA)}.json`); } catch (e) { if (my === seq) empty(`Well ${WA || '?'} not found.`, `Well ${WA || '?'}`); return; }
  const padId = d.pad && d.pad.id;
  if (padId) try { row = (await getJSON(`data/region/pads/${encodeURIComponent(padId)}.json`)).wells.find(x => String(x.well.wa) === WA) || null; } catch (e) { /* no survey */ }
  if (my !== seq) return;
  W = assemble(d, row);
  attachGamma();
  syncUrl(); header(); render(); announce();
  if (!GAMMA) getJSON('data/gamma.json').then(g => { GAMMA = g; if (W && my === seq) { attachGamma(); header(); render(); } }).catch(() => {});
}

function assemble(d, row) {
  const w = { ...((row && row.well) || {}), ...(d.well || {}) };
  const t = row && row.trajectory;
  const traj = t && t.md && t.md.length > 1
    ? t.md.map((m, i) => ({ md: m, tvd: t.tvd[i], ns: t.ns[i], ew: t.ew[i] })).filter(p => [p.md, p.tvd, p.ns, p.ew].every(Number.isFinite))
    : [];
  // the section runs from the pad toward TD, so a lateral reads left to right
  const end = traj[traj.length - 1];
  const az = end && Math.hypot(end.ns, end.ew) > 1 ? Math.atan2(end.ew, end.ns) : 0;
  traj.forEach(p => { p.vs = p.ns * Math.cos(az) + p.ew * Math.sin(az); });

  // stages: as filed with the BCER (they carry the summaries), marked where the Lab's curves exist
  const hasSeries = s => s.series && Object.values(s.series).some(a => Array.isArray(a) && a.some(v => v != null));
  const curves = new Map((d.stages || []).filter(hasSeries).map(s => [String(s.label), s]));
  const filed = row && row.stages && row.stages.length ? row.stages : d.bcer_stages || [];
  const seen = new Set(), stages = [];
  const add = s => {
    const label = String(s.label != null ? s.label : s.n);
    if (seen.has(label) || s.top_m == null || !isFinite(s.top_m)) return;
    seen.add(label);
    const a = +s.top_m, b = s.base_m != null && isFinite(s.base_m) ? +s.base_m : a, c = curves.get(label);
    stages.push({ label, top: Math.min(a, b), base: Math.max(a, b), mid: (a + b) / 2, curves: !!c,
                  date: s.date || (c && c.date) || '', start: String((c && c.start) || s.start || '').slice(0, 5),
                  proppant: s.proppant_t, fluid: s.fluid_m3, rate: s.avg_rate_m3_min, pmax: s.max_pressure_mpa,
                  minutes: c ? c.minutes : null });
  };
  filed.forEach(add);
  (d.stages || []).forEach(add);
  if (!stages.length && row) (row.depth_intervals || []).forEach(s => add({ ...s, label: s.n }));
  stages.sort((a, b) => a.mid - b.mid);
  // each stage owns the lateral halfway to its neighbours: the hover target
  stages.forEach((s, i) => {
    const p = stages[i - 1], n = stages[i + 1], half = p && n ? 0 : p ? (s.mid - p.mid) / 2 : n ? (n.mid - s.mid) / 2 : 30;
    s.z0 = p ? (p.mid + s.mid) / 2 : s.mid - half;
    s.z1 = n ? (s.mid + n.mid) / 2 : s.mid + half;
  });

  let heel = w.heel_md > 0 ? +w.heel_md : null;
  if (heel == null) for (let i = 1; i < traj.length; i++) {         // first station past 80° inclination
    const a = traj[i - 1], b = traj[i], dm = b.md - a.md;
    if (dm > 0 && (b.tvd - a.tvd) / dm < Math.cos(80 * Math.PI / 180)) { heel = a.md; break; }
  }
  return { well: w, pad: d.pad || {}, traj, az, stages, heel, td: end ? end.md : w.td_m, gamma: null, nCurves: curves.size };
}

function attachGamma() {
  if (!W) return;
  const g = GAMMA && GAMMA.wells && GAMMA.wells[WA];
  W.gamma = g && Array.isArray(g.v) && g.v.some(v => v != null)
    ? { md0: g.md0, bin: GAMMA.bin_m || 5, v: g.v, estimated: !!g.estimated, from: g.from,
        lo: (GAMMA.scale && GAMMA.scale.lo) || 70, hi: (GAMMA.scale && GAMMA.scale.hi) || 180 }
    : null;
}
const gammaAt = md => {
  const g = W && W.gamma; if (!g) return null;
  const v = g.v[Math.floor((md - g.md0) / g.bin)];
  return v == null ? null : v;
};

// the trajectory at a measured depth, interpolated between survey stations
function at(md) {
  const t = W.traj;
  if (md <= t[0].md) return t[0];
  if (md >= t[t.length - 1].md) return t[t.length - 1];
  let lo = 0, hi = t.length - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (t[m].md <= md) lo = m; else hi = m; }
  const a = t[lo], b = t[hi], f = (md - a.md) / (b.md - a.md);
  return { md, tvd: a.tvd + (b.tvd - a.tvd) * f, vs: a.vs + (b.vs - a.vs) * f };
}
const stageAt = md => W.stages.find(s => md >= s.z0 && md <= s.z1) || null;

// ---------- drawing ----------
function empty(msg, title) {
  $('ws-svg').innerHTML = ''; $('ws-tip').hidden = true;
  $('ws-empty').hidden = false; $('ws-empty').textContent = msg;
  if (title) $('ws-name').textContent = title;
}

function render() {
  const box = $('ws-main'), Wd = box.clientWidth, Ht = box.clientHeight;
  if (!W || !Wd || !Ht) return;
  if (W.traj.length < 2) { empty('No directional survey on file for this well, so there is no path to draw.'); return; }
  $('ws-empty').hidden = true;
  const w = W.well, elev = w.elev_m != null && isFinite(w.elev_m) ? +w.elev_m : null;
  const lateralMode = mode === 'lateral' && W.heel != null;
  const track = W.gamma && Ht >= 210 ? 50 : 0, gap = track ? 10 : 0;
  const x0 = 58, x1 = Wd - (elev != null ? 62 : 18), y0 = 20, y1 = Ht - 24 - track - gap, ty0 = y1 + gap, ty1 = ty0 + track;
  const pts = W.traj;
  let vx0, vx1, dy0, dy1, kx, ky;
  if (!lateralMode) {
    // the whole well filling the frame, with room in pixels for the labels around it;
    // depth is stretched or squeezed to fit, and says so unless it is near true scale
    const a = Math.min(0, ...pts.map(p => p.vs)), b = Math.max(0, ...pts.map(p => p.vs)), dmax = Math.max(1, ...pts.map(p => p.tvd));
    const side = 30, top = 22, bottom = 30;
    kx = (x1 - x0 - 2 * side) / Math.max(1, b - a); ky = Math.max(0.005, (y1 - y0 - top - bottom) / dmax);
    if (ky / kx > 0.85 && ky / kx < 1.2) kx = ky = Math.min(kx, ky);     // close enough: draw it true
    const cx = (a + b) / 2;
    vx0 = cx - (x1 - x0) / kx / 2; vx1 = cx + (x1 - x0) / kx / 2;
    dy0 = -top / ky; dy1 = dy0 + (y1 - y0) / ky;
  } else {
    // the lateral filling the frame, depth stretched so its undulation shows
    const lat = pts.filter(p => p.md >= W.heel), a = at(W.heel), len = Math.max(200, pts[pts.length - 1].vs - a.vs);
    vx0 = a.vs - len * 0.08; vx1 = pts[pts.length - 1].vs + len * 0.04;
    const lo = Math.min(...lat.map(p => p.tvd), a.tvd), hi = Math.max(...lat.map(p => p.tvd), a.tvd), pad = Math.max(12, (hi - lo) * 0.45);
    dy0 = lo - pad; dy1 = hi + pad;
    kx = (x1 - x0) / (vx1 - vx0); ky = (y1 - y0) / (dy1 - dy0);
  }
  const X = v => x0 + (v - vx0) * kx, Y = d => y0 + (d - dy0) * ky, ve = ky / kx;
  const out = [];
  out.push(`<defs><clipPath id="clip"><rect x="${x0}" y="${y0}" width="${x1 - x0}" height="${y1 - y0}"/></clipPath>`
    + `<clipPath id="clipx"><rect x="${x0}" y="0" width="${x1 - x0}" height="${Ht}"/></clipPath></defs>`);

  // grid and axes
  const xs = niceStep(vx1 - vx0, (x1 - x0) / 110), ys = niceStep(dy1 - dy0, (y1 - y0) / 38);
  out.push('<g>');
  for (let v = Math.ceil(vx0 / xs) * xs; v <= vx1; v += xs) {
    const x = X(v).toFixed(1);
    out.push(`<line x1="${x}" x2="${x}" y1="${y0}" y2="${track ? ty1 : y1}" stroke="var(--grid)"/>`
      + `<text class="ax" x="${x}" y="${Ht - 8}" text-anchor="middle">${fmt(v)}</text>`);
  }
  for (let d = Math.ceil(dy0 / ys) * ys; d <= dy1; d += ys) {
    const y = Y(d).toFixed(1);
    out.push(`<line x1="${x0}" x2="${x1}" y1="${y}" y2="${y}" stroke="var(--grid)"/>`
      + `<text class="ax" x="${x0 - 7}" y="${+y + 4}" text-anchor="end">${fmt(d)}</text>`);
  }
  if (elev != null) for (let a = Math.ceil((elev - dy1) / ys) * ys; a <= elev - dy0; a += ys) {
    const y = Y(elev - a);
    out.push(`<line x1="${x1}" x2="${x1 + 4}" y1="${y}" y2="${y}" stroke="var(--line)"/><text class="ax" x="${x1 + 7}" y="${y + 4}">${fmt(a)}</text>`);
  }
  out.push(`<text class="ax-t" x="${x0 - 7}" y="${y0 - 7}" text-anchor="end">TVD m</text>`);
  if (elev != null) out.push(`<text class="ax-t" x="${x1 + 7}" y="${y0 - 7}">m ASL</text>`);
  out.push(`<rect x="${x0}" y="${y0}" width="${x1 - x0}" height="${y1 - y0}" fill="none" stroke="var(--line)"/></g>`);

  // which way the section looks, above the frame
  const azDeg = ((W.az * 180 / Math.PI) + 360) % 360;
  out.push(`<text class="chip" x="${x0 + 2}" y="${y0 - 7}">← ${compass(azDeg + 180)}</text>`
    + `<text class="chip" x="${x1 - 2}" y="${y0 - 7}" text-anchor="end">${compass(azDeg)} →</text>`);

  // surface and sea level
  out.push('<g clip-path="url(#clip)">');
  if (0 >= dy0 && 0 <= dy1) out.push(`<line x1="${x0}" x2="${x1}" y1="${Y(0)}" y2="${Y(0)}" stroke="#4f6d7b" stroke-width="1.5"/>`
    + `<text class="lbl m" x="${x0 + 8}" y="${Y(0) - 6}">surface${elev != null ? ` · KB ${fmt(elev)} m ASL` : ''}</text>`);
  if (elev != null && elev >= dy0 && elev <= dy1) out.push(`<line x1="${x0}" x2="${x1}" y1="${Y(elev)}" y2="${Y(elev)}" stroke="#4f6d7b" stroke-dasharray="5 5"/>`
    + `<text class="lbl m" x="${x1 - 8}" y="${Y(elev) - 6}" text-anchor="end">sea level</text>`);
  const stretch = Math.abs(ve - 1) < 0.02 ? 'true scale' : `depth ×${fmt(ve, ve < 10 ? 1 : 0)}`;
  out.push(`<text class="chip" x="${x1 - 8}" y="${y0 + 16}" text-anchor="end">${stretch}</text>`);

  // the path in screen space: hover samples, and the ground labels are kept clear of
  const step = Math.max(2, (W.td || pts[pts.length - 1].md) / 1500), samples = [];
  for (let m = pts[0].md; m <= pts[pts.length - 1].md; m += step) { const p = at(m); samples.push({ md: m, vs: p.vs, tvd: p.tvd, x: X(p.vs), y: Y(p.tvd) }); }
  // a label's baseline under the path across its width, or over it when there is no room below
  const clear = (xa, xb, yy) => {
    const ys_ = samples.filter(q => q.x >= xa - 4 && q.x <= xb + 4).map(q => q.y).concat(yy);
    const below = Math.max(...ys_) + 17;
    return below <= y1 - 4 ? below : Math.min(...ys_) - 9;
  };
  const tw = t => t.length * 6.6;

  // the wellbore: build in slate, lateral in ink (or gamma)
  const line = list => list.map(p => `${X(p.vs).toFixed(1)},${Y(p.tvd).toFixed(1)}`).join(' ');
  const heel = W.heel != null ? W.heel : pts[pts.length - 1].md;
  const build = pts.filter(p => p.md <= heel).concat([at(heel)]), lat = [at(heel)].concat(pts.filter(p => p.md > heel));
  out.push(`<polyline points="${line(pts)}" fill="none" stroke="#000" stroke-opacity=".5" stroke-width="7" stroke-linejoin="round" stroke-linecap="round"/>`);
  out.push(`<polyline points="${line(build)}" fill="none" stroke="${BUILD}" stroke-width="2.2" stroke-linejoin="round"/>`);
  const g = W.gamma, gammaOn = colorBy === 'gamma' && g;
  out.push(`<polyline points="${line(lat)}" fill="none" stroke="${gammaOn ? FILED : NEUTRAL}" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/>`);
  if (gammaOn) {
    const segs = [];
    g.v.forEach((v, i) => {
      if (v == null) return;
      const m0 = g.md0 + i * g.bin;
      if (m0 + g.bin < heel - 200) return;
      const a = at(m0), b = at(m0 + g.bin);
      segs.push(`<line x1="${X(a.vs).toFixed(1)}" y1="${Y(a.tvd).toFixed(1)}" x2="${X(b.vs).toFixed(1)}" y2="${Y(b.tvd).toFixed(1)}" stroke="${gammaInk(v, g.lo, g.hi)}"/>`);
    });
    out.push(`<g stroke-width="5"${g.estimated ? ' stroke-dasharray="7 4"' : ''}>${segs.join('')}</g>`);
  }

  // stage ticks across the path, at their measured depths
  const ticks = [], placed = [];
  const normal = md => {
    const a = at(md - 12), b = at(md + 12), dx = (X(b.vs) - X(a.vs)), dy = (Y(b.tvd) - Y(a.tvd)), l = Math.hypot(dx, dy) || 1;
    let nx = -dy / l, ny = dx / l; if (ny > 0) { nx = -nx; ny = -ny; }   // pointing up
    return [nx, ny];
  };
  for (const s of W.stages) {
    const p = at(s.mid), x = X(p.vs), y = Y(p.tvd), [nx, ny] = normal(s.mid), r = s.label === HI ? 9 : 6;
    s.px = x; s.py = y; s.nx = nx; s.ny = ny;
    ticks.push(`<line x1="${(x - nx * r).toFixed(1)}" y1="${(y - ny * r).toFixed(1)}" x2="${(x + nx * r).toFixed(1)}" y2="${(y + ny * r).toFixed(1)}" stroke="${s.curves ? CURVES : FILED}" stroke-width="${s.label === HI ? 3 : 2}"/>`);
  }
  out.push(`<g stroke-linecap="round">${ticks.join('')}</g>`);
  // stage numbers where they have room (the first, the last and the picked one always)
  let lastX = -1e9;
  const keep = new Set();
  const inView = W.stages.filter(s => s.px >= x0 && s.px <= x1);
  inView.forEach((s, i) => { if (i === 0 || i === inView.length - 1 || Math.abs(s.px - lastX) >= 26) { keep.add(s); lastX = s.px; } });
  const hiS = W.stages.find(s => s.label === HI);
  if (hiS) { for (const s of [...keep]) if (s !== hiS && Math.abs(s.px - hiS.px) < 26) keep.delete(s); keep.add(hiS); }
  // straight above each tick, clear of the path on either side of it
  out.push('<g>' + [...keep].map(s => {
    const top = Math.min(s.py, ...samples.filter(q => Math.abs(q.x - s.px) <= 9 && Math.abs(q.md - s.mid) < 150).map(q => q.y));
    return `<text class="stn${s === hiS ? ' on' : ''}" x="${s.px.toFixed(1)}" y="${(top - 11).toFixed(1)}" text-anchor="middle">${esc(s.label)}</text>`;
  }).join('') + '</g>');

  // pad, heel and TD
  const td = pts[pts.length - 1], hp = at(heel);
  out.push(`<circle cx="${X(0)}" cy="${Y(0)}" r="5.5" fill="#e7f4fa" stroke="#0a141d" stroke-width="2"/>`);
  if (W.heel != null) {
    const t = `heel ${fmt(W.heel)} m MD`, hx = X(hp.vs), w_ = tw(t), xa = Math.max(x0 + 4, hx - w_ / 2);
    out.push(`<circle cx="${hx}" cy="${Y(hp.tvd)}" r="4" fill="#0a141d" stroke="${NEUTRAL}" stroke-width="2"/>`
      + `<text class="lbl m" x="${xa}" y="${clear(xa, xa + w_, Y(hp.tvd))}">${t}</text>`);
  }
  const tdx = X(td.vs), tdt = `TD ${fmt(td.md)} m MD · ${fmt(td.tvd)} m TVD`, tdw = tw(tdt);
  const tdxa = Math.max(x0 + 4, Math.min(tdx - tdw / 2, x1 - 6 - tdw));     // centred under TD, inside the frame
  out.push(`<circle cx="${tdx}" cy="${Y(td.tvd)}" r="4.5" fill="${NEUTRAL}" stroke="#0a141d" stroke-width="2"/>`
    + `<text class="lbl" x="${tdxa}" y="${clear(tdxa, tdxa + tdw, Y(td.tvd))}">${tdt}</text>`);
  out.push('</g>');

  // gamma under the section, on the same along-section axis
  if (track) {
    out.push(`<rect x="${x0}" y="${ty0}" width="${x1 - x0}" height="${track}" fill="#0d1b25" stroke="var(--line)"/>`);
    for (const a of [100, 200]) {
      const y = ty1 - a / GR_MAX * track;
      out.push(`<line x1="${x0}" x2="${x1}" y1="${y}" y2="${y}" stroke="var(--grid)" stroke-dasharray="3 4"/><text class="ax" x="${x0 - 7}" y="${y + 4}" text-anchor="end">${a}</text>`);
    }
    const bars = [];
    g.v.forEach((v, i) => {
      if (v == null) return;
      const m0 = g.md0 + i * g.bin, a = at(m0), b = at(m0 + g.bin);
      if (Math.abs(b.vs - a.vs) < g.bin * 0.5) return;          // steep hole: no room on this axis
      const xa = X(Math.min(a.vs, b.vs)), xb = X(Math.max(a.vs, b.vs));
      if (xb < x0 || xa > x1) return;
      const h = Math.max(1, Math.min(1, v / GR_MAX) * track);
      bars.push(`<rect x="${xa.toFixed(1)}" y="${(ty1 - h).toFixed(1)}" width="${Math.max(1, xb - xa + .4).toFixed(1)}" height="${h.toFixed(1)}" fill="${gammaInk(v, g.lo, g.hi)}"/>`);
    });
    out.push(`<g clip-path="url(#clipx)"${g.estimated ? ' opacity=".75"' : ''}>${bars.join('')}</g>`);
    out.push(`<text class="chip" x="${x1 - 8}" y="${ty0 + 14}" text-anchor="end">gamma API${g.estimated ? ` · estimated from ${g.from && g.from.length ? g.from.length + ' offset log' + (g.from.length > 1 ? 's' : '') : 'offset logs'} (±15 API)` : ''}</text>`);
  }
  out.push('<g id="ws-hl"></g>');
  $('ws-svg').innerHTML = out.join('');
  $('ws-svg').setAttribute('viewBox', `0 0 ${Wd} ${Ht}`);

  G = { x0, x1, y0, y1, ty0, ty1, track, X, Y, samples, heel, elev };
  $('ws-foot').textContent = `Vertical section along ${fmt(azDeg)}° (${compass(azDeg)}), from the pad's surface location`
    + ` · ${lateralMode ? 'lateral' : 'whole well'}, ${stretch}`
    + ` · ${W.stages.length ? 'teal ticks have treatment curves, slate are filed only · ' : ''}hover for depths · click a stage for its charts`;
  drawHover();
}

// the hover layer: picked-out stage band, crosshair and readout
function band(s, color, opacity, width) {
  const ms = [];
  for (let m = s.z0; m <= s.z1; m += Math.max(2, (s.z1 - s.z0) / 24)) ms.push(at(m));
  ms.push(at(s.z1));
  return `<polyline points="${ms.map(p => `${G.X(p.vs).toFixed(1)},${G.Y(p.tvd).toFixed(1)}`).join(' ')}" fill="none" stroke="${color}" stroke-opacity="${opacity}" stroke-width="${width}" stroke-linecap="butt"/>`;
}
function drawHover() {
  const hl = document.getElementById('ws-hl');
  if (!hl || !G) return;
  const out = [];
  const hiS = W.stages.find(s => s.label === HI);
  if (hiS) out.push(band(hiS, CURVES, .28, 16));
  const tip = $('ws-tip');
  if (hover) {
    const s = hover.md >= (G.heel - 1) ? stageAt(hover.md) : null;
    if (s && s !== hiS) out.push(band(s, s.curves ? CURVES : FILED, .2, 16));
    if (G.track && hover.md >= G.heel - 200) out.push(`<line x1="${hover.x}" x2="${hover.x}" y1="${G.y0}" y2="${G.ty1}" stroke="#e7f4fa" stroke-opacity=".35"/>`);
    out.push(`<circle cx="${hover.x}" cy="${hover.y}" r="5" fill="none" stroke="#e7f4fa" stroke-width="2"/>`);
    const gr = gammaAt(hover.md);
    const lines = [`<b>MD ${fmt(hover.md)} m</b> · TVD ${fmt(hover.tvd)} m`,
      `<span class="m">${fmt(hover.vs)} m along the section${G.elev != null ? ` · ${fmt(G.elev - hover.tvd)} m ASL` : ''}</span>`];
    if (gr != null) lines.push(`Gamma ${fmt(gr)} API${W.gamma.estimated ? ' <span class="m">(estimated)</span>' : ''}`);
    if (s) {
      lines.push(`<b>Stage ${esc(s.label)}</b> · ${fmt(s.top, 1)}${s.base !== s.top ? '–' + fmt(s.base, 1) : ''} m MD`);
      const bits = [s.date && `${s.date}${s.start ? ' ' + s.start : ''}`, s.proppant != null && `${fmt(s.proppant, 1)} t`,
        s.fluid != null && `${fmt(s.fluid)} m³`, s.rate != null && `${fmt(s.rate, 1)} m³/min`, s.pmax != null && `max ${fmt(s.pmax, 1)} MPa`].filter(Boolean);
      if (bits.length) lines.push(`<span class="m">${bits.join(' · ')}</span>`);
      lines.push(s.curves ? 'Click for its treatment charts' : '<span class="m">Filed with the BCER; no curves yet</span>');
    }
    tip.innerHTML = lines.join('<br>');
    tip.hidden = false;
    const box = $('ws-main'), tw = tip.offsetWidth, th = tip.offsetHeight;
    let tx = hover.x + 16, ty = hover.y - th - 12;
    if (tx + tw > box.clientWidth - 6) tx = hover.x - tw - 16;
    if (ty < 6) ty = hover.y + 16;
    if (ty + th > box.clientHeight - 6) ty = box.clientHeight - th - 6;
    tip.style.left = Math.max(6, tx) + 'px'; tip.style.top = ty + 'px';
  } else tip.hidden = true;
  hl.innerHTML = out.join('');
  $('ws-svg').style.cursor = hover && hover.md >= G.heel - 1 && stageAt(hover.md) ? 'pointer' : 'crosshair';
}

const svg = $('ws-svg');
svg.setAttribute('tabindex', '0');
svg.addEventListener('pointermove', e => {
  if (!G) return;
  const r = svg.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
  let best = null, bd = Infinity;
  if (G.track && my >= G.ty0 - 4) {
    for (const s of G.samples) { if (s.md < G.heel - 200) continue; const d = Math.abs(s.x - mx); if (d < bd) { bd = d; best = s; } }
    if (bd > 30) best = null;
  } else {
    for (const s of G.samples) { const d = Math.hypot(s.x - mx, s.y - my); if (d < bd) { bd = d; best = s; } }
    if (bd > 34) best = null;
  }
  if (best !== hover) { hover = best; drawHover(); }
});
svg.addEventListener('pointerleave', () => { hover = null; drawHover(); });
svg.addEventListener('click', () => {
  if (!hover || hover.md < G.heel - 1) return;
  const s = stageAt(hover.md);
  if (s) { HI = s.label; syncUrl(); render(); openStage(s); }
});
svg.addEventListener('keydown', e => {
  if (!W || !W.stages.length) return;
  const i = W.stages.findIndex(s => s.label === HI);
  if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
    e.preventDefault();
    const j = i < 0 ? 0 : Math.max(0, Math.min(W.stages.length - 1, i + (e.key === 'ArrowRight' ? 1 : -1)));
    HI = W.stages[j].label; syncUrl(); render();
  } else if (e.key === 'Enter' && i >= 0) openStage(W.stages[i]);
});
new ResizeObserver(() => render()).observe($('ws-main'));

// ---------- header and controls ----------
function header() {
  const w = W.well;
  $('ws-name').textContent = w.name || `WA ${WA}`;
  document.title = `Stratum — ${w.name || 'WA ' + WA} · section`;
  const n = W.stages.length;
  $('ws-sub').textContent = [`WA ${WA}`, w.uwi, w.operator, w.formation, W.td ? `TD ${fmt(W.td)} m MD` : null,
    w.tvd_m ? `${fmt(w.tvd_m)} m TVD` : null, w.lateral_m ? `lateral ${fmt(w.lateral_m)} m` : null,
    n ? `${n} stages${W.nCurves ? `, ${W.nCurves} with curves` : ''}` : null].filter(Boolean).join(' · ');
  $('ws-sub').title = $('ws-sub').textContent;
  const gb = document.querySelector('[data-color=gamma]');
  gb.disabled = !W.gamma;
  gb.title = W.gamma ? (W.gamma.estimated ? 'Gamma estimated from offset logs' : 'Gamma from this well’s LAS log') : 'No gamma log on file for this well';
  document.querySelector('[data-mode=lateral]').disabled = W.heel == null;
  setPressed();
}
function setPressed() {
  document.querySelectorAll('[data-mode]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.mode === mode)));
  document.querySelectorAll('[data-color]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.color === colorBy)));
}
const savePrefs = () => { try { localStorage.setItem(PREF_KEY, JSON.stringify({ mode, color: colorBy })); } catch (e) { /* private mode */ } };
document.querySelectorAll('[data-mode]').forEach(b => b.onclick = () => { mode = b.dataset.mode; savePrefs(); setPressed(); render(); });
document.querySelectorAll('[data-color]').forEach(b => b.onclick = () => { colorBy = b.dataset.color; savePrefs(); setPressed(); render(); });

function syncUrl() {
  const q = new URLSearchParams(location.search);
  q.set('wa', WA); if (HI) q.set('stage', HI); else q.delete('stage');
  history.replaceState(null, '', '?' + q);
}

// The main window is whichever page last sent a well here: the map that docked or
// popped this section out, or a well's charts. A popped-out section talks to it
// over the channel only, so it never depends on the window that opened it (a
// dock's frame, gone once the dock closes). Messages to the main window carry its
// id and are answered, so a closed one is noticed.
const chan = 'BroadcastChannel' in self ? new BroadcastChannel('stratum-section') : null;
let owner = Q.get('owner'), ownerPage = Q.get('page');
const pending = new Map();
function ask(msg) {
  if (!chan || !owner) return Promise.resolve(false);
  const id = Math.random().toString(36).slice(2);
  chan.postMessage({ ...msg, to: owner, id });
  return new Promise(res => { pending.set(id, res); setTimeout(() => { if (pending.delete(id)) res(false); }, 700); });
}
let noteTimer = 0;
function note(html) {
  const n = $('ws-note'); n.innerHTML = html; n.hidden = false;
  clearTimeout(noteTimer); noteTimer = setTimeout(() => { n.hidden = true; }, 9000);
}
const chartsUrl = label => `wellview.html?wa=${encodeURIComponent(WA)}${label ? '&stage=' + encodeURIComponent(label) : ''}`;
function openStage(s) {
  const label = s && s.curves ? s.label : null;
  if (EMBED) { parent.postMessage({ type: 'ws:stage', wa: WA, label }, ORIGIN); return; }
  if (!owner) { window.open(chartsUrl(label), '_blank'); return; }
  ask({ type: 'open-stage', wa: WA, label }).then(ok => {
    if (!ok) note(`The main window has closed. <a href="${chartsUrl(label)}" target="_blank" rel="noopener">Open the charts in a new tab</a>`);
  });
}
$('ws-charts').onclick = () => openStage(W && (W.stages.find(s => s.label === HI && s.curves) || W.stages.find(s => s.curves)));

function show(wa, stage) {
  if (wa == null || wa === '') return;
  HI = stage != null && stage !== '' ? String(stage) : null;
  if (String(wa) === WA && W) { syncUrl(); render(); return; }
  load(wa);
}
function announce() { if (!EMBED && chan) chan.postMessage({ type: 'hello', wa: WA }); }
if (EMBED) {
  // docked: the parent closes it and says which well to show; Pop out opens the
  // window from here, inside the click, so no popup blocker stands in the way
  document.body.classList.add('embedded');
  $('ws-pop').hidden = false; $('ws-close').hidden = false;
  $('ws-pop').onclick = () => {
    const q = new URLSearchParams({ wa: WA });
    if (HI) q.set('stage', HI); if (owner) q.set('owner', owner); if (ownerPage) q.set('page', ownerPage);
    const w = window.open('wellsection.html?' + q, 'stratum-section', 'popup,width=1280,height=620');
    if (w) parent.postMessage({ type: 'ws:popped', wa: WA, stage: HI }, ORIGIN);
  };
  $('ws-close').onclick = () => parent.postMessage({ type: 'ws:close' }, ORIGIN);
  window.stratumSectionShow = show;          // the parent's direct line, same origin
  addEventListener('message', e => {
    if (e.origin !== ORIGIN || e.source !== parent) return;
    const m = e.data;
    if (m && m.type === 'ws:show') show(m.wa, m.stage);
  });
} else {
  // popped out: follow the main window, and say so, so it sends wells here rather than docking
  const dockable = () => { $('ws-dock').hidden = !(owner && ownerPage === 'map'); };
  if (chan) chan.onmessage = e => {
    const m = e.data || {};
    if (m.type === 'show') {
      if (m.from) { owner = m.from; ownerPage = m.page || null; dockable(); }
      show(m.wa, m.stage);
    } else if (m.type === 'claim' && m.from) { owner = m.from; ownerPage = m.page || null; dockable(); }
    else if (m.type === 'ping') announce();
    else if (m.type === 'ack' && pending.has(m.id)) { pending.get(m.id)(true); pending.delete(m.id); }
  };
  addEventListener('pagehide', () => { if (chan) chan.postMessage({ type: 'bye' }); });
  dockable();
  $('ws-dock').onclick = () => ask({ type: 'dock', wa: WA, stage: HI }).then(ok => {
    if (ok) window.close(); else { owner = null; dockable(); note('The map window has closed.'); }
  });
}
addEventListener('keydown', e => { if (e.key === 'Escape' && EMBED) parent.postMessage({ type: 'ws:close' }, ORIGIN); });

if (WA) load(WA); else empty('No well chosen. Open this page from a well on the map.', 'Well section');
