// FracView — wine racks, in a window of their own, so the map or 3D view that
// asked for one stays exactly where it was. Each pad asked for is added under
// the ones already here (winerack.html?pads=a,b,c, top to bottom).
//
// A rack is a pad as an engineer reads it across the laterals. On the left, the
// pad from overhead, turned so its laterals run left to right, with a straight
// line across them the user drags along (or plays, or steps with the keys).
// Beside it, a 2D section through the pad at that line, each well where it
// crosses -- its offset across the pad against true vertical depth, the stage
// it is in there, gamma there -- and the spacing between neighbours. Wells drop
// in through their landing curve as the line reaches them and drop out past
// their toes.
//
// The well's own 2D section stays along the bottom of the main window (the map,
// or the 3D view over it): a well clicked here is shown there, and as this
// rack's line moves, a cursor moves along that well there, picking out the stage
// at the line with its chart, as if it were hovered. They talk over
// BroadcastChannel 'stratum-rack' (wellsection-host.js), to the main window that
// last opened a rack here or said hello.
//
// Other pages add a pad with window.stratumRacks.add(id, owner) (they reach this
// window by its name, 'stratum-rack': see stratumRack.open in
// cluster-underground.js).
//
// The wells can be coloured by pad, by gamma at the line, by a stage measure for
// the stage the line is in (metrics.js), parent/child, or frac date; each shows
// its parent/child letter either way. An "as of" date per rack draws the wells
// not yet fracked then as faint outlines, so the pad can be watched developing.
'use strict';
const Q = new URLSearchParams(location.search);
const STATE_KEY = 'stratum.racks';
const $ = id => document.getElementById(id);
const SVGNS = 'http://www.w3.org/2000/svg';
const svgEl = (tag, attrs, parent) => { const e = document.createElementNS(SVGNS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.append(e); return e; };
const fmt = (v, d = 0) => v == null || !isFinite(v) ? '–' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d });
const COMPASS16 = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
const compassOf = d => COMPASS16[Math.round(((d % 360) + 360) % 360 / 22.5) % 16];
const LANDING_M = 400;   // how far up the build a well shows before its heel, so it can be seen arriving
const SG = window.StratumGamma;
const dark = () => document.documentElement.dataset.theme === 'dark';
const padInk = i => window.StratumTheme ? StratumTheme.padColor(i) : '#2563eb';
// marks drawn without a colour of their own: wells in gamma mode on the overview, and no-log wells
const neutral = () => dark() ? '#b9c9d2' : '#566b78';
const hole = () => dark() ? '#0b1620' : '#ffffff';
const MAX_RACKS = 12;

// ---------- data ----------
const chartedOnly = () => { try { return localStorage.getItem('stratum.allWells') !== '1'; } catch (e) { return true; } };
let gamma = null;
const gammaReady = fetch('data/gamma.json').then(r => r.ok ? r.json() : null).then(g => { gamma = g; }).catch(() => {});
let colorBy = 'pad';
const MODES = ['pad', 'gamma', 'metric', 'relation', 'date'];
const FM = window.FVMetrics;  // stage metrics and parent/child labels (metrics.js)
let metric = 'avgP';          // the stage measure in "Stage metric" mode
let rels = null;              // plain WA -> parent/child label, for the limits in Settings
const racks = [];             // {id, i, el, p, g, s, play, asOf, span, dplay, error}
let picked = null;            // the well shown in the main window's section: {pad, wa}

// ---------- the main window ----------
const chan = 'BroadcastChannel' in self ? new BroadcastChannel('stratum-rack') : null;
let owner = Q.get('owner') || null;
const send = m => { if (chan) chan.postMessage(owner ? { ...m, to: owner } : m); };
if (chan) chan.onmessage = e => { const m = e.data || {}; if (m.type === 'main' && m.from) owner = m.from; };
// a well to the main window's section, with where this rack's line crosses it
function showWell(R, o, x) {
  picked = { pad: R.id, wa: String(o.w.well.wa) };
  send({ type: 'view', wa: picked.wa, stage: x && x.stage ? String(x.stage.label) : null, at: x ? Math.round(x.md) : null });
  lastAt = x ? Math.round(x.md) : null;
  renderAll(); save();
}
// the line moved: where it crosses the picked well, once a frame at most
let lastAt, cursorRaf = 0;
function followLine(R) {
  if (!picked || picked.pad !== R.id || !R.g) return;
  cancelAnimationFrame(cursorRaf);
  cursorRaf = requestAnimationFrame(() => {
    const o = R.g.ws.find(q => String(q.w.well.wa) === picked.wa), x = o ? rackCross(o, R.s) : null, at = x ? Math.round(x.md) : null;
    if (at === lastAt) return;
    lastAt = at; send({ type: 'cursor', wa: picked.wa, at });
  });
}
// the well a new rack starts on: the one nearest the middle of the pad, on the line
function centralWell(R) {
  const hits = R.g.ws.map(o => ({ o, x: rackCross(o, R.s) })).filter(h => h.x);
  if (!hits.length) return { o: R.g.ws[0], x: null };
  const landed = hits.filter(h => !h.x.landing), pool = landed.length ? landed : hits, mid = (R.g.c0 + R.g.c1) / 2;
  return pool.sort((a, b) => Math.abs(a.x.c - mid) - Math.abs(b.x.c - mid))[0];
}

// a pad's wells in metres about the pad: x east, y up (-TVD), z north
async function loadPad(id) {
  const r = await fetch('data/region/pads/' + encodeURIComponent(id) + '.json');
  if (!r.ok) throw Error(r.status === 404 ? 'This pad is not in FracView.' : 'Unable to load this pad.');
  const p = await r.json();
  if (chartedOnly()) p.wells = p.wells.filter(w => w.well.curves);
  if (!p.wells.length) throw Error('No wells with treatment charts on this pad. Untick “only wells with treatment charts” on the map to see them all.');
  const k = Math.cos(p.lat * Math.PI / 180), xy = (lon, lat) => [(lon - p.lon) * 111320 * k, (lat - p.lat) * 111320];
  p.wells.forEach(w => {
    const [wx, wz] = xy(w.well.lon, w.well.lat), t = w.trajectory;
    w.points = t.md.map((m, j) => [wx + t.ew[j], -t.tvd[j], wz + t.ns[j]]).filter(q => q.every(Number.isFinite));
    w.pad = p;
  });
  p.wells = p.wells.filter(w => w.points.length > 1);
  if (!p.wells.length) throw Error('No directional surveys on file for this pad’s wells.');
  return p;
}
function attachGamma(p) {
  if (!gamma || !p) return;
  p.wells.forEach(w => {
    const x = gamma.wells[String(w.well.wa).padStart(5, '0')];
    if (!x) return;
    w.gmd0 = x.md0; w.gbin = gamma.bin_m; w.gv = x.v; w.gest = !!x.estimated;
  });
}

// ---------- geometry ----------
// Per pad, once: the line the laterals run along (an axial mean, so a pad
// drilled both ways still has one, facing the side most toes are on), and every
// well in that frame: along the pad, across it, and TVD.
function rackGeom(p) {
  if (p.rack) return p.rack;
  const ws = p.wells.map(w => {
    const md = w.trajectory.md, heel = w.well.heel_md || md[Math.floor(md.length * .4)] || 0, lat = w.points.filter((q, j) => md[j] >= heel);
    return { w, heel, lat: lat.length > 1 ? lat : w.points.slice(-2) };
  });
  let sx = 0, sy = 0;
  ws.forEach(o => { const a = o.lat[0], b = o.lat.at(-1), th = Math.atan2(b[0] - a[0], b[2] - a[2]); sx += Math.cos(2 * th); sy += Math.sin(2 * th); });
  let yaw = Math.atan2(sy, sx) / 2;
  const ahead = ws.filter(o => { const a = o.lat[0], b = o.lat.at(-1); return (b[0] - a[0]) * Math.sin(yaw) + (b[2] - a[2]) * Math.cos(yaw) > 0; }).length;
  if (ahead < ws.length / 2) yaw += Math.PI;
  const ox = ws.reduce((a, o) => a + o.w.points[0][0], 0) / ws.length, oz = ws.reduce((a, o) => a + o.w.points[0][2], 0) / ws.length;
  const ue = Math.sin(yaw), un = Math.cos(yaw);
  const along = q => (q[0] - ox) * ue + (q[2] - oz) * un, across = q => (q[0] - ox) * un - (q[2] - oz) * ue;
  ws.forEach(o => {
    const w = o.w, md = w.trajectory.md;
    o.plan = w.points.map(q => [along(q), across(q)]);
    o.pts = w.points.map((q, j) => ({ a: along(q), c: across(q), tvd: -q[1], md: md[j] })).filter(q => q.md >= o.heel - LANDING_M);
    // each stage owns the hole halfway to its neighbours, as on the well section; where the
    // filed stages carry no depths (the Gundy pads) the filed stage depths stand in by number,
    // as the section does, with that stage's summary where one was filed
    const byLabel = new Map((w.stages || []).map(s => [String(s.label), s]));
    let src = (w.stages || []).filter(s => s.top_m != null);
    if (!src.length) src = (w.depth_intervals || []).filter(d => d.top_m != null).map(d => {
      const s = byLabel.get(String(d.n)) || {};
      return { ...s, label: String(d.n), top_m: d.top_m, base_m: d.base_m, date: s.date || String(d.date || '').replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3') };
    });
    const st = src.map(s => ({ s, mid: (s.top_m + (s.base_m ?? s.top_m)) / 2 })).sort((x, y) => x.mid - y.mid);
    o.zones = st.map((z, i) => ({ s: z.s, z0: i ? (st[i - 1].mid + z.mid) / 2 : z.mid - ((st[1]?.mid ?? z.mid + 60) - z.mid) / 2,
                                  z1: i < st.length - 1 ? (z.mid + st[i + 1].mid) / 2 : z.mid + (z.mid - (st[i - 1]?.mid ?? z.mid - 60)) / 2 }));
  });
  const all = ws.flatMap(o => o.pts), plan = ws.flatMap(o => o.plan);
  const g = { yaw, az: (yaw * 180 / Math.PI + 360) % 360, ws,
    sMin: Math.min(...all.map(q => q.a)), sMax: Math.max(...all.map(q => q.a)),
    c0: Math.min(...all.map(q => q.c)), c1: Math.max(...all.map(q => q.c)), t0: Math.min(...all.map(q => q.tvd)), t1: Math.max(...all.map(q => q.tvd)),
    pa0: Math.min(...plan.map(q => q[0])), pa1: Math.max(...plan.map(q => q[0])), pc0: Math.min(...plan.map(q => q[1])), pc1: Math.max(...plan.map(q => q[1])) };
  // start in the middle of the stretch where the most wells are on the line, landed
  const tries = [];
  for (let s = g.sMin; s <= g.sMax; s += (g.sMax - g.sMin) / 80 || 1) tries.push({ s, n: ws.filter(o => { const x = rackCross(o, s); return x && !x.landing; }).length });
  const most = Math.max(...tries.map(t => t.n)), best = tries.filter(t => t.n === most);
  g.start = best[Math.floor(best.length / 2)].s;
  return p.rack = g;
}
// where one well crosses the line `s` metres along the pad: the deepest crossing
function rackCross(o, s) {
  let hit = null;
  for (let i = 1; i < o.pts.length; i++) {
    const a = o.pts[i - 1], b = o.pts[i];
    if ((a.a - s) * (b.a - s) > 0 || a.a === b.a) continue;
    const f = (s - a.a) / (b.a - a.a), md = a.md + (b.md - a.md) * f;
    if (!hit || md > hit.md) hit = { c: a.c + (b.c - a.c) * f, tvd: a.tvd + (b.tvd - a.tvd) * f, md };
  }
  if (hit) {
    hit.landing = hit.md < o.heel;
    const z = o.zones.find(z => hit.md >= z.z0 && hit.md <= z.z1); hit.stage = z ? z.s : null;
    const w = o.w;
    if (w.gv) { const v = w.gv[Math.floor((hit.md - w.gmd0) / w.gbin)]; hit.gamma = v == null ? null : v; }
  }
  return hit;
}
const rackInk = (R, o, x) => inkFor(colorBy, R, o, x);

// ---------- colour: pad, gamma, a stage measure, parent/child, frac date ----------
const DAY = 864e5;
const dayOf = s => { const m = /^(\d{4})-?(\d{2})-?(\d{2})/.exec(String(s || '')); return m ? Date.UTC(+m[1], m[2] - 1, +m[3]) / DAY : null; };
const dayStr = d => d == null || !isFinite(d) ? '' : new Date(Math.round(d) * DAY).toISOString().slice(0, 10);
// a well's frac: its first and last filed stage dates, in days
function fracDays(w) {
  if (w.frac) return w.frac;
  const d = (w.stages || []).map(s => dayOf(s.date)).filter(v => v != null);
  return (w.frac = d.length ? [Math.min(...d), Math.max(...d)] : [null, null]);
}
// not fracked yet on the "as of" date; a well with no dates on file always shows
const future = (w, asOf) => asOf != null && fracDays(w)[0] != null && fracDays(w)[0] > asOf;
const relOf = w => (rels && rels.get(String(+w.well.wa))) || null;
const relLetter = r => (r && FM && FM.REL[r.relation] ? FM.REL[r.relation].s : '');
// the pad's stage metrics row for the stage the line is in (by its label)
const stageRow = (o, x) => (x && x.stage && o.mrows ? o.mrows.get(String(x.stage.label)) || null : null);
const stageValue = (o, x, k) => { const r = stageRow(o, x); return r && FM ? FM.value(r, k) : null; };
// a rack's range for a measure: every stage of its wells, kept until the measure or the rows change
function rackDomain(R, k) {
  if (R.dom && R.dom.k === k) return R.dom.d;
  const vals = R.g.ws.flatMap(o => (o.mrows ? [...o.mrows.values()].map(r => FM.value(r, k)) : []));
  R.dom = { k, d: FM.domain(vals, k) };
  return R.dom.d;
}
// the rack's frac start dates, oldest to newest: the date colours and the "as of" range
function dateSpan(R) {
  const d = R.g.ws.map(o => fracDays(o.w)[0]).filter(v => v != null);
  return d.length ? [Math.min(...d), Math.max(...d)] : null;
}
function inkFor(mode, R, o, x) {
  if (mode === 'gamma') return x && x.gamma != null && gamma ? SG.ink(x.gamma, gamma.scale) : null;
  if (!FM || mode === 'pad') return padInk(R.i);
  if (mode === 'metric') return FM.colour(stageValue(o, x, metric), rackDomain(R, metric), metric);
  if (mode === 'relation') { const r = relOf(o.w); return r ? FM.relColour(r.relation) : null; }
  if (mode === 'date') { const sp = dateSpan(R); return FM.colour(fracDays(o.w)[0], sp && [sp[0], Math.max(sp[1], sp[0] + 1)]); }
  return padInk(R.i);
}
// spacing to the next well along the top: across, and the vertical step when it fits
function spacingLabel(gap, dv, room) {
  const short = fmt(gap) + ' m', long = `${short} / ${dv > 0 ? '↓' : '↑'}${fmt(Math.abs(dv))} m`;
  return Math.abs(dv) >= 1 && room >= long.length * 6.4 + 10 ? long : short;
}
const spacingText = l => `Spacing limits: ${fmt(l.across)} m across · ${fmt(l.vertical)} m vertical · ${fmt(l.siblingDays)} days`;
// the ends of the sequential ramp in words: pale to dark on the light theme, dark to bright on the dark one
const rampEnds = () => (dark() ? ['dark', 'bright'] : ['light', 'dark']);
const ago = d => (d < 60 ? `${fmt(d)} days` : `${fmt(d / 30.44)} months`);
const NEAR_REL = { parent: 'its parent', sibling: 'co-completed', child: 'its child' };
// a well's spacing label in words, for the tooltip: [text, tag]
function relationLines(r) {
  if (!r || !FM || !FM.REL[r.relation]) return [];
  const L = FM.REL[r.relation], par = r.near.filter(n => n.rel === 'parent');
  const out = [[`${L.t} (${L.s}): ${L.d}`, 'b']];
  if (FM.BOUNDED[r.bounded]) out.push([FM.BOUNDED[r.bounded]]);
  if (par.length) out.push([`Parent${par.length > 1 ? 's' : ''}: ${par.map(n => 'WA ' + n.wa).join(', ')}`
    + (r.depletionDays != null ? ` · ${par.length > 1 ? 'the longest ' : ''}produced ${ago(r.depletionDays)} before this frac` : '')]);
  if (r.near.length) {
    out.push([`Offsets within the limits, looking toward the toes:`]);
    r.near.slice().sort((a, b) => Math.abs(a.across) - Math.abs(b.across)).slice(0, 5).forEach(n => out.push([
      `WA ${n.wa}: ${fmt(Math.abs(n.across))} m ${n.across >= 0 ? 'right' : 'left'}, ${Math.abs(n.vertical) < 1 ? 'level' : fmt(Math.abs(n.vertical)) + ' m ' + (n.vertical > 0 ? 'deeper' : 'shallower')}${n.rel ? ' · ' + NEAR_REL[n.rel] : ''}`]));
    if (r.near.length > 5) out.push([`and ${r.near.length - 5} more`]);
  }
  return out;
}
function niceStep(span, n) { const raw = span / n, e = Math.pow(10, Math.floor(Math.log10(raw))); return [1, 2, 2.5, 5, 10].map(m => m * e).find(s => s >= raw) || 10 * e; }

// ---------- one rack ----------
const TEMPLATE = `<header class="rk-head"><div class="rk-id"><div class="rk-title"><i></i><span></span></div><div class="rk-sub"></div><div class="rk-key" hidden></div></div>
  <div class="rk-acts"><button type="button" class="rk-png" title="Save this rack as a PNG image">PNG</button><button type="button" class="rk-up" title="Move this rack up">↑</button><button type="button" class="rk-x" title="Close this rack" aria-label="Close this rack">×</button></div></header>
  <div class="rk-body"><div class="rk-planbox"><svg class="rk-plan" role="img" aria-label="The pad from overhead with the section line"></svg>
  <div class="rk-ctl"><button type="button" class="rk-play" aria-label="Play the line along the pad">▶</button><input type="range" class="rk-slider" aria-label="Section line position along the pad"><span class="rk-where"></span></div>
  <div class="rk-ctl rk-asof"><span class="rk-asof-l">As of</span><button type="button" class="rk-dplay" aria-label="Play the pad's fracs through time">▶</button><input type="range" class="rk-date" step="1" aria-label="As of date: wells fracked after it are drawn faint"><span class="rk-when"></span></div></div>
  <svg class="rk-section" role="group"></svg></div>`;

function make(id, s0, asOf) {
  const R = { id, i: 0, p: null, g: null, s: s0, play: 0, asOf: asOf ?? null, dplay: 0 };
  const el = R.el = document.createElement('section');
  el.className = 'rk'; el.dataset.pad = id; el.setAttribute('aria-label', 'Wine rack');
  el.innerHTML = TEMPLATE;
  el.querySelector('.rk-title span').textContent = id;
  el.querySelector('.rk-sub').textContent = 'Loading the pad…';
  el.querySelector('.rk-body').hidden = true;
  el.querySelector('.rk-x').onclick = () => remove(R);
  el.querySelector('.rk-up').onclick = () => { const k = racks.indexOf(R); if (k > 0) { racks.splice(k, 1); racks.splice(k - 1, 0, R); placeAll(); el.querySelector('.rk-up').focus(); } };
  el.querySelector('.rk-slider').oninput = e => { stop(R); move(R, +e.target.value); };
  el.querySelector('.rk-play').onclick = () => play(R);
  el.querySelector('.rk-date').oninput = e => { stopDates(R); setAsOf(R, +e.target.value); };
  el.querySelector('.rk-dplay').onclick = () => playDates(R);
  el.querySelector('.rk-png').onclick = () => savePng(R);
  const plan = el.querySelector('.rk-plan');
  let dragging = false;
  const at = e => { const r = plan.getBoundingClientRect(), m = plan._map; if (m) move(R, m.inv(e.clientX - r.left)); };
  plan.addEventListener('pointerdown', e => { if (!R.g) return; stop(R); dragging = true; plan.setPointerCapture(e.pointerId); at(e); });
  plan.addEventListener('pointermove', e => { if (dragging) at(e); });
  plan.addEventListener('pointerup', () => { dragging = false; save(); });
  plan.addEventListener('pointercancel', () => { dragging = false; });
  el.addEventListener('keydown', e => {
    if (!R.g || e.target.closest('input, select') || !['ArrowLeft', 'ArrowRight'].includes(e.key)) return;
    e.preventDefault(); stop(R); move(R, R.s + (e.key === 'ArrowRight' ? 1 : -1) * (e.shiftKey ? 250 : 25));
  });
  return R;
}
async function fill(R) {
  try {
    const p = await loadPad(R.id);
    await gammaReady;
    attachGamma(p);
    R.p = p; R.g = rackGeom(p); R.dom = null;
    if (R.s == null || !isFinite(R.s)) R.s = R.g.start;
    R.s = Math.max(R.g.sMin, Math.min(R.g.sMax, R.s));
    R.span = dateSpan(R);
    if (R.asOf != null && (!R.span || R.asOf >= R.span[1])) R.asOf = null;
    R.el.setAttribute('aria-label', 'Wine rack: ' + p.name);
    R.el.querySelector('.rk-body').hidden = false;
    render(R);
    loadMetrics(R);
  } catch (e) {
    R.error = e.message;
    R.el.querySelector('.rk-sub').textContent = e.message;
  }
  head();
}
// each well's stage metrics, by stage label; the rack draws without them first
async function loadMetrics(R) {
  if (!FM || !R.g) return;
  const g = R.g;
  await Promise.all(g.ws.map(async o => { o.mrows = new Map((await FM.rows(R.id, o.w.well.wa)).map(r => [String(r.label), r])); }));
  if (R.g !== g) return;
  R.dom = null;
  render(R);
}

// "as of" a date: wells fracked after it are faint; the right end is every well
function setAsOf(R, d) {
  if (!R.g) return;
  const sp = R.span;
  R.asOf = d == null || !sp || d >= sp[1] ? null : Math.max(sp[0], Math.floor(d));
  render(R); saveSoon();
}
function stopDates(R) { cancelAnimationFrame(R.dplay); R.dplay = 0; const b = R.el.querySelector('.rk-dplay'); b.textContent = '▶'; b.setAttribute('aria-label', 'Play the pad’s fracs through time'); }
function playDates(R) {
  if (R.dplay) { stopDates(R); return; }
  const sp = R.span;
  if (!R.g || !sp || sp[1] <= sp[0]) return;
  // about ten seconds from the first frac to the last, a day at a time at least
  let t = R.asOf == null ? sp[0] : R.asOf, last = performance.now();
  const b = R.el.querySelector('.rk-dplay'); b.textContent = '❚❚'; b.setAttribute('aria-label', 'Pause');
  setAsOf(R, t);
  const step = now => {
    const dt = Math.min(.1, (now - last) / 1000); last = now;
    t += Math.max(1, (sp[1] - sp[0]) / 10) * dt;
    setAsOf(R, t);
    if (t >= sp[1]) { stopDates(R); return; }
    R.dplay = requestAnimationFrame(step);
  };
  R.dplay = requestAnimationFrame(step);
}

function move(R, s) { if (!R.g) return; R.s = Math.max(R.g.sMin, Math.min(R.g.sMax, s)); render(R); followLine(R); saveSoon(); }
function stop(R) { cancelAnimationFrame(R.play); R.play = 0; const b = R.el.querySelector('.rk-play'); b.textContent = '▶'; b.setAttribute('aria-label', 'Play the line along the pad'); }
function play(R) {
  if (R.play) { stop(R); return; }
  if (!R.g) return;
  const g = R.g, span = g.sMax - g.sMin;
  if (R.s >= g.sMax - 1) move(R, g.sMin);
  const b = R.el.querySelector('.rk-play'); b.textContent = '❚❚'; b.setAttribute('aria-label', 'Pause');
  let last = performance.now();
  const step = now => {
    const dt = Math.min(.1, (now - last) / 1000); last = now;
    const s = R.s + span / 14 * dt; move(R, s);
    if (s >= g.sMax) { stop(R); return; }
    R.play = requestAnimationFrame(step);
  };
  R.play = requestAnimationFrame(step);
}

const tip = $('wr-tip');
function showTip(e, lines) {
  tip.replaceChildren();
  lines.filter(Boolean).forEach(([t, b]) => { const d = document.createElement(b || 'div'); d.textContent = t; tip.append(d); });
  tip.hidden = false;
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.max(6, Math.min(innerWidth - w - 8, e.clientX + 16)) + 'px';
  tip.style.top = (e.clientY + 16 + h > innerHeight - 6 ? Math.max(6, e.clientY - h - 12) : e.clientY + 16) + 'px';
}
const hideTip = () => { tip.hidden = true; };

function render(R) {
  if (!R.g) return;
  const p = R.p, g = R.g, s = R.s, el = R.el;
  const hits = g.ws.map(o => ({ o, x: rackCross(o, s) })).filter(h => h.x);
  const sl = el.querySelector('.rk-slider');
  sl.min = Math.floor(g.sMin); sl.max = Math.ceil(g.sMax); sl.step = 5; sl.value = Math.round(s);
  el.querySelector('.rk-where').textContent = `${fmt(Math.abs(s))} m ${s >= 0 ? 'out' : 'back'} from the pad · ${hits.length} of ${g.ws.length} wells on the line`;
  el.querySelector('.rk-title i').style.background = padInk(R.i);
  el.querySelector('.rk-title span').textContent = p.name;
  const gone = g.ws.filter(o => !hits.some(h => h.o === o));
  el.querySelector('.rk-sub').textContent = `${g.ws.length} well${g.ws.length > 1 ? 's' : ''} · laterals run toward ${Math.round(g.az)}° (${compassOf(g.az)}) · ${hits.length} cross the line`
    + (gone.length && gone.length <= 4 ? ` · not here: ${gone.map(o => o.w.well.wa).join(', ')}` : gone.length ? ` · ${gone.length} not here` : '');
  // as of: the right end of the slider is every well
  const sp = R.span, dl = el.querySelector('.rk-date'), done = g.ws.filter(o => !future(o.w, R.asOf)).length;
  dl.disabled = el.querySelector('.rk-dplay').disabled = !sp || sp[1] <= sp[0];
  if (sp) { dl.min = sp[0]; dl.max = sp[1]; dl.value = R.asOf ?? sp[1]; }
  dl.setAttribute('aria-valuetext', R.asOf == null ? 'All wells' : dayStr(R.asOf));
  el.querySelector('.rk-when').textContent = !sp ? 'No frac dates on file' : R.asOf == null ? `All wells · fracked ${dayStr(sp[0])}${sp[1] > sp[0] ? ' to ' + dayStr(sp[1]) : ''}`
    : `${dayStr(R.asOf)} · ${done} of ${g.ws.length} wells fracked`;
  rackKey(R);
  renderPlan(R, hits); renderSection(R, hits);
}
// the rack's own key, where its colours run over its own wells' range
function rackKey(R) {
  const k = R.el.querySelector('.rk-key');
  k.hidden = !FM || (colorBy !== 'metric' && colorBy !== 'date');
  if (k.hidden) return;
  let html;
  if (colorBy === 'metric') {
    const m = FM.BY[metric], dom = rackDomain(R, metric);
    html = `<span class="rk-key-l">${m.t}, stage at the line</span>` + (dom ? FM.legend(metric, dom) : '<span>No values on this pad</span>');
  } else {
    const sp = R.span, n = 7, stops = Array.from({ length: n }, (_, i) => FM.colour(i / (n - 1), [0, 1]));
    html = sp ? `<span class="rk-key-l">Frac start</span><span class="fvm-key" style="display:inline-flex;align-items:center;gap:6px"><span>${dayStr(sp[0])}</span>`
      + `<span style="display:inline-block;width:90px;height:8px;border-radius:4px;background:linear-gradient(90deg,${stops.join(',')})"></span><span>${dayStr(sp[1])}</span></span>` : '<span>No frac dates on file</span>';
  }
  // the line moves every frame while dragged: rewrite the key only when it changes
  if (k._html !== html) { k.innerHTML = html; k._html = html; }
}
const renderAll = () => racks.forEach(render);

// the pad from overhead, laterals left to right, the line across them
function renderPlan(R, hits) {
  const g = R.g, s = R.s, svg = R.el.querySelector('.rk-plan');
  svg.replaceChildren();
  const W = svg.clientWidth, H = svg.clientHeight;
  if (!W || !H) return;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  const P = { l: 14, r: 14, t: 30, b: 28 }, pw = W - P.l - P.r, ph = H - P.t - P.b, a0 = g.pa0 - 60, a1 = g.pa1 + 60, c0 = g.pc0 - 60, c1 = g.pc1 + 60;
  // one scale both ways, so the pad keeps its true shape
  const k = Math.min(pw / (a1 - a0), ph / (c1 - c0)), ax = P.l + (pw - (a1 - a0) * k) / 2, cy = P.t + (ph - (c1 - c0) * k) / 2, X = a => ax + (a - a0) * k, Y = c => cy + (c1 - c) * k;
  svg._map = { inv: x => a0 + (x - ax) / k };
  const grid = svgEl('g', { class: 'rk-grid' }, svg), st = niceStep(a1 - a0, Math.max(2, Math.min(6, pw / 95)));
  for (let a = Math.ceil(a0 / st) * st; a <= a1; a += st) {
    svgEl('line', { x1: X(a), x2: X(a), y1: P.t, y2: P.t + ph, class: a === 0 ? 'rk-zero' : '' }, grid);
    svgEl('text', { x: X(a), y: H - 10, 'text-anchor': 'middle' }, grid).textContent = (a < 0 ? '−' : '') + fmt(Math.abs(a)) + ' m';
  }
  svgEl('text', { x: P.l, y: 13, class: 'rk-axis' }, svg).textContent = `← ${compassOf(g.az + 180)}`;
  svgEl('text', { x: W - P.r, y: 13, class: 'rk-axis', 'text-anchor': 'end' }, svg).textContent = `toes · ${compassOf(g.az)} →`;
  // north, as it sits in this turned view
  const nx = W - P.r - 16, ny = P.t + 30, na = -g.yaw;
  svgEl('line', { x1: nx - Math.sin(na) * 10, y1: ny + Math.cos(na) * 10, x2: nx + Math.sin(na) * 10, y2: ny - Math.cos(na) * 10, class: 'rk-north' }, svg);
  svgEl('text', { x: nx + Math.sin(na) * 19, y: ny - Math.cos(na) * 19 + 4, 'text-anchor': 'middle', class: 'rk-axis' }, svg).textContent = 'N';
  const paths = svgEl('g', { class: 'rk-paths' }, svg), tags = [];
  g.ws.forEach(o => {
    // colour that runs along a well (gamma, a stage measure) is the section's; overhead the well is plain
    const on = isPicked(R, o.w), fut = future(o.w, R.asOf), ink = colorBy === 'gamma' || colorBy === 'metric' ? neutral() : inkFor(colorBy, R, o, null) || neutral();
    svgEl('polyline', { points: o.plan.map(q => X(q[0]).toFixed(1) + ',' + Y(q[1]).toFixed(1)).join(' '), stroke: ink, class: (on ? 'on' : '') + (fut ? ' fut' : '') }, paths);
    const t = o.plan.at(-1);
    svgEl('circle', { cx: X(t[0]), cy: Y(t[1]), r: 2.5, fill: ink, class: fut ? 'fut' : '' }, paths);
    tags.push({ o, x: X(t[0]), y: Y(t[1]), on });
  });
  // a number at each toe, inside the frame, the picked well's first; ones that would overlap are left off
  const kept = [];
  tags.sort((a, b) => b.on - a.on).forEach(t => {
    const right = t.x + 42 <= W - P.r, x = right ? t.x + 5 : t.x - 5;
    if (kept.some(k => Math.abs(k.y - t.y) < 11 && Math.abs(k.x - x) < 44)) return;
    kept.push({ x, y: t.y });
    svgEl('text', { x, y: t.y + 3.5, 'text-anchor': right ? 'start' : 'end', class: 'rk-plan-wa' + (t.on ? ' on' : '') }, paths).textContent = t.o.w.well.wa;
  });
  svgEl('circle', { cx: X(0), cy: Y(0), r: 5, class: 'rk-padpt' }, svg);
  // the line, and where each well meets it
  const lx = X(s);
  svgEl('line', { x1: lx, x2: lx, y1: P.t - 6, y2: P.t + ph + 4, class: 'rk-line' }, svg);
  svgEl('rect', { x: lx - 7, y: P.t - 12, width: 14, height: 11, rx: 3, class: 'rk-handle' }, svg);
  hits.forEach(h => { const fut = future(h.o.w, R.asOf); svgEl('circle', { cx: lx, cy: Y(h.x.c), r: 4, fill: fut ? hole() : rackInk(R, h.o, h.x) || hole(), class: 'rk-meet' + (h.x.landing ? ' landing' : '') + (fut ? ' fut' : '') }, svg); });
}

// the section across the pad at the line
function renderSection(R, hits) {
  const g = R.g, s = R.s, svg = R.el.querySelector('.rk-section');
  svg.replaceChildren();
  const W = svg.clientWidth, H = svg.clientHeight;
  if (!W || !H) return;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  const small = W < 520, Rr = small ? 8 : 11, P = { l: 72, r: 20, t: 40, b: 46 }, pw = W - P.l - P.r, ph = H - P.t - P.b;
  // one frame for the whole pad, so wells move within it as the line moves
  const mx = Math.max(30, (g.c1 - g.c0) * .05), my = Math.max(10, (g.t1 - g.t0) * .06), x0 = g.c0 - mx, x1 = g.c1 + mx, y0 = g.t0 - my, y1 = g.t1 + my;
  const X = v => P.l + Rr + (v - x0) / (x1 - x0) * (pw - 2 * Rr), Y = v => P.t + Rr + (v - y0) / (y1 - y0) * (ph - 2 * Rr - 26);
  const ex = ((ph - 2 * Rr - 26) / (y1 - y0)) / ((pw - 2 * Rr) / (x1 - x0));
  const grid = svgEl('g', { class: 'rk-grid' }, svg), ys = niceStep(y1 - y0, 6), xs = niceStep(x1 - x0, 7);
  for (let v = Math.ceil(y0 / ys) * ys; v <= y1; v += ys) {
    svgEl('line', { x1: P.l, x2: P.l + pw, y1: Y(v), y2: Y(v) }, grid);
    svgEl('text', { x: P.l - 8, y: Y(v) + 4, 'text-anchor': 'end' }, grid).textContent = fmt(v) + ' m';
  }
  for (let v = Math.ceil(x0 / xs) * xs; v <= x1; v += xs) {
    svgEl('line', { x1: X(v), x2: X(v), y1: P.t, y2: P.t + ph, class: v === 0 ? 'rk-zero' : '' }, grid);
    svgEl('text', { x: X(v), y: P.t + ph + 16, 'text-anchor': 'middle' }, grid).textContent = (v > 0 ? '+' : v < 0 ? '−' : '') + fmt(Math.abs(v)) + ' m';
  }
  svgEl('text', { x: P.l + pw / 2, y: H - 8, 'text-anchor': 'middle', class: 'rk-axis' }, svg).textContent = (small ? 'Across the pad' : 'Across the pad, looking toward the toes') + ` (${Math.round(g.az)}°) · depth ×${ex.toFixed(1)}`;
  svgEl('text', { x: 14, y: P.t + ph / 2, 'text-anchor': 'middle', class: 'rk-axis', transform: `rotate(-90 14 ${P.t + ph / 2})` }, svg).textContent = 'True vertical depth';
  if (!hits.length) { svgEl('text', { x: P.l + pw / 2, y: P.t + ph / 2, 'text-anchor': 'middle', class: 'rk-empty' }, svg).textContent = 'No well crosses the line here. Move it along the pad.'; return; }
  // spacing between neighbours across the pad, along the top, with the step up or down where it
  // fits: the pad as it stood on the "as of" date, so wells not yet fracked are left out
  const live = hits.filter(h => !future(h.o.w, R.asOf));
  const sorted = live.slice().sort((a, b) => a.x.c - b.x.c), dim = svgEl('g', { class: 'rk-dim' }, svg), dy = P.t - 14;
  sorted.forEach((h, i) => {
    const x = X(h.x.c);
    svgEl('line', { x1: x, x2: x, y1: dy - 5, y2: dy + 5 }, dim);
    if (i) {
      const pv = sorted[i - 1], px = X(pv.x.c), gap = h.x.c - pv.x.c, dv = h.x.tvd - pv.x.tvd;
      svgEl('line', { x1: px, x2: x, y1: dy, y2: dy }, dim);
      if (x - px > 34) {
        const t = svgEl('text', { x: (px + x) / 2, y: dy - 6, 'text-anchor': 'middle' }, dim);
        t.textContent = spacingLabel(gap, dv, x - px);
        svgEl('title', {}, t).textContent = `WA ${h.o.w.well.wa} is ${fmt(gap)} m right of WA ${pv.o.w.well.wa}` + (Math.abs(dv) < 1 ? ', level with it' : ` and ${fmt(Math.abs(dv))} m ${dv > 0 ? 'deeper' : 'shallower'}`);
      }
    }
  });
  const labels = [], ends = svgEl('g', { class: 'rk-ends' }, svg), none = dark() ? '#6b8290' : '#7b8e9a';
  hits.slice().sort((a, b) => a.x.tvd - b.x.tvd).forEach(h => {
    const o = h.o, w = o.w, x = h.x, cx = X(x.c), cy = Y(x.tvd), fut = future(w, R.asOf), ink = fut ? null : rackInk(R, o, x), r = relOf(w), letter = relLetter(r);
    const v = colorBy === 'metric' ? stageValue(o, x, metric) : null, [f0, f1] = fracDays(w);
    const a = svgEl('g', { class: 'rk-end' + (isPicked(R, w) ? ' on' : '') + (x.landing ? ' landing' : '') + (fut ? ' fut' : ''), tabindex: 0, role: 'button',
      'aria-label': `${w.well.name}, WA ${w.well.wa}: ${fmt(x.c)} metres across, ${fmt(x.tvd)} metres TVD${x.stage ? ', stage ' + x.stage.label : ''}`
        + `${r ? ', ' + FM.REL[r.relation].t.toLowerCase() : ''}${fut ? ', not fracked yet on ' + dayStr(R.asOf) : ''}. Show its section in the main window.` }, ends);
    svgEl('circle', { cx, cy, r: Rr, fill: fut ? hole() : x.landing ? hole() : ink || hole(), stroke: x.landing || fut ? ink || none : hole(),
      class: 'rk-dot ' + (fut ? 'rk-fut' : ink ? (colorBy === 'gamma' && w.gest ? 'rk-est' : '') : 'rk-none') }, a);
    // parent/child: the letter on the marker when that is the colour, a chip beside it otherwise
    if (letter && !fut) {
      if (colorBy === 'relation') svgEl('text', { x: cx, y: cy, 'text-anchor': 'middle', 'dominant-baseline': 'central', class: 'rk-rel' + (small ? ' sm' : ''), fill: x.landing ? ink || none : hole() }, a).textContent = letter;
      else {
        const qx = cx + Rr * .8, qy = cy - Rr * .8;
        svgEl('circle', { cx: qx, cy: qy, r: small ? 5 : 6.5, fill: FM.relColour(r.relation), class: 'rk-chip' }, a);
        svgEl('text', { x: qx, y: qy, 'text-anchor': 'middle', 'dominant-baseline': 'central', class: 'rk-chipt' + (small ? ' sm' : ''), fill: hole() }, a).textContent = letter;
      }
    }
    const lh = small ? 13 : 26, bw = small ? 36 : 52;
    let ly = cy + Rr + 14;
    const box = l => labels.some(b => Math.abs(b.x - cx) < bw && Math.abs(b.y - l) < lh);
    if (box(ly)) ly = cy - Rr - (small ? 6 : 18);
    labels.push({ x: cx, y: ly });
    svgEl('text', { x: cx, y: ly, 'text-anchor': 'middle', class: 'rk-wa' }, a).textContent = w.well.wa + (x.stage && !small && !fut ? ' · stg ' + x.stage.label : '');
    // the second line: what the colour says, where it is not the depth (none for a well still to come)
    const sub = colorBy === 'metric' ? FM.fmt(v, metric) : colorBy === 'date' && f0 != null ? dayStr(f0) : fmt(x.tvd) + ' m' + (x.landing ? ' · landing' : '');
    if (!small && !fut) svgEl('text', { x: cx, y: ly + 12, 'text-anchor': 'middle', class: 'rk-tvd' }, a).textContent = sub;
    // nearest neighbour on this line, in the section's own metres
    let nn = null;
    hits.forEach(k => { if (k === h || future(k.o.w, R.asOf)) return; const d = Math.hypot(k.x.c - x.c, k.x.tvd - x.tvd); if (!nn || d < nn.d) nn = { d, h: Math.abs(k.x.c - x.c), v: k.x.tvd - x.tvd, wa: k.o.w.well.wa }; });
    const open = () => { hideTip(); showWell(R, o, x); };
    a.addEventListener('click', open);
    a.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });
    a.addEventListener('pointerenter', e => {
      const st = x.stage, row = stageRow(o, x);
      showTip(e, [[w.well.name, 'b'], [`WA ${w.well.wa} · MD ${fmt(x.md)} m at the line · ${fmt(x.tvd)} m TVD${x.landing ? ' (landing, before the heel)' : ''}`],
        st ? [`Stage ${st.label}${st.date ? ' · ' + st.date : ''}${st.proppant_t != null ? ' · ' + fmt(st.proppant_t, 1) + ' t' : ''}${st.avg_rate_m3_min != null ? ' · ' + fmt(st.avg_rate_m3_min, 1) + ' m³/min' : ''}`] : null,
        colorBy === 'metric' ? [`${FM.BY[metric].t}: ${v == null ? 'no value for this stage' : FM.fmt(v, metric)}${row && row.src === 'filed' ? ' (as filed)' : ''}`] : null,
        x.gamma != null ? [`Gamma ${w.gest ? '~' : ''}${fmt(x.gamma)} API at the line${w.gest ? ' (estimated)' : ''}`] : null,
        [f0 == null ? 'No frac dates on file' : `Fracked ${dayStr(f0)}${f1 > f0 ? ' to ' + dayStr(f1) : ''}${fut ? ', after the as-of date' : ''}`],
        nn ? [`Nearest on this line: WA ${nn.wa}, ${fmt(nn.h)} m across, ${fmt(Math.abs(nn.v))} m ${nn.v < 0 ? 'shallower' : 'deeper'}`] : null,
        ...relationLines(r),
        [isPicked(R, w) ? 'Its section is in the main window' : 'Click to show its section in the main window', 'i']]);
    });
    a.addEventListener('pointerleave', hideTip);
  });
}
const isPicked = (R, w) => !!picked && picked.pad === R.id && picked.wa === String(w.well.wa);

// ---------- the list ----------
// order on screen follows `racks`; each keeps its colour by its place
function placeAll() {
  const list = $('wr-list');
  racks.forEach((R, i) => { R.i = i; list.append(R.el); R.el.querySelector('.rk-up').hidden = i === 0; });
  renderAll(); head(); save();
}
function head() {
  const ok = racks.filter(R => R.p);
  $('wr-empty').hidden = racks.length > 0;
  $('wr-sub').textContent = !racks.length ? 'No pads yet' : `${racks.length} pad${racks.length > 1 ? 's' : ''}`
    + (ok.length ? ` · ${ok.reduce((n, R) => n + R.p.wells.length, 0)} wells` : '') + ' · newest at the bottom'
    + (chartedOnly() ? ' · wells with treatment charts' : '');
  document.title = 'FracView — ' + (ok.length === 1 ? ok[0].p.name + ' · Wine rack' : `Wine racks${racks.length ? ' · ' + racks.length + ' pads' : ''}`);
  const gb = document.querySelector('[data-color=gamma]');
  gb.disabled = !gamma; gb.title = gamma ? 'Colour the wells by gamma ray at the line' : 'Gamma data unavailable';
  if (!FM) document.querySelectorAll('[data-color=metric],[data-color=relation],[data-color=date]').forEach(b => { b.disabled = true; b.title = 'Stage metrics unavailable'; });
  key();
}
function key() {
  const k = $('wr-key');
  k.hidden = colorBy === 'pad' || (colorBy === 'gamma' && !gamma) || (colorBy !== 'gamma' && !FM);
  if (k.hidden) return;
  k.replaceChildren();
  const select = (label, opts, value, onchange) => {
    const sel = document.createElement('select');
    sel.setAttribute('aria-label', label);
    opts.forEach(([id, t]) => { const o = document.createElement('option'); o.value = id; o.textContent = t; sel.append(o); });
    sel.value = value; sel.onchange = () => onchange(sel.value);
    k.append(sel);
  };
  if (colorBy === 'gamma') {
    k.innerHTML = `<span>Gamma at the line</span><i style="background:${SG.gradient()}"></i><span>${gamma.scale.lo}–${gamma.scale.hi} API</span><span class="rk-nonekey">no log</span>`;
    select('Gamma colours', Object.entries(SG.PALETTES).map(([id, q]) => [id, q.name]), SG.current(), v => SG.set(v));
  } else if (colorBy === 'metric') {
    k.innerHTML = '<span>Stage at the line</span>';
    select('Stage metric', FM.METRICS.map(m => [m.k, m.t + (m.u ? ` (${m.u})` : '')]), metric, setMetric);
    k.insertAdjacentHTML('beforeend', '<span class="wr-keynote">each rack’s own range · grey: no value</span>');
  } else if (colorBy === 'relation') {
    k.innerHTML = Object.entries(FM.REL).map(([id, x]) => `<span class="wr-rel" title="${x.d}"><b style="background:${FM.relColour(id)};color:${hole()}">${x.s}</b>${x.t}</span>`).join('');
  } else k.innerHTML = `<span>First stage date, oldest ${rampEnds()[0]} to newest ${rampEnds()[1]}</span><span class="wr-keynote">each rack’s own range</span>`;
}
function setMetric(k) {
  if (!FM || !FM.BY[k]) return;
  metric = k; renderAll(); save();
}
// the limits the parent/child labels use, from Settings
function limitsNote() {
  const b = $('wr-limits');
  b.hidden = !FM;
  if (FM) b.textContent = spacingText(FM.limits());
}

// add a pad's rack underneath the others, or bring it into view if it is here already;
// asked for (not restored), it also puts its middle well in the main window's section
function add(id, opts = {}) {
  id = String(id || '').trim();
  if (!id) return null;
  if (opts.owner) owner = opts.owner;
  const here = racks.find(R => R.id === id);
  if (here) { if (!opts.quiet) { flash(here); if (here.g && (!picked || picked.pad !== here.id)) { const c = centralWell(here); showWell(here, c.o, c.x); } } return here; }
  if (racks.length >= MAX_RACKS) { const old = racks.shift(); stop(old); stopDates(old); old.el.remove(); }
  const R = make(id, opts.s, opts.asOf);
  racks.push(R);
  placeAll();
  fill(R).then(() => {
    if (opts.quiet) return;
    flash(R);
    if (R.g) { const c = centralWell(R); showWell(R, c.o, c.x); }
  });
  return R;
}
function flash(R) {
  R.el.classList.remove('fresh'); void R.el.offsetWidth; R.el.classList.add('fresh');
  R.el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  try { window.focus(); } catch (e) { /* the browser decides */ }
}
function remove(R) {
  const k = racks.indexOf(R);
  if (k < 0) return;
  stop(R); stopDates(R); racks.splice(k, 1); R.el.remove(); hideTip();
  if (picked && picked.pad === R.id) picked = null;
  placeAll();
}

// ---------- state: the URL lists the pads; the lines, colour and picked well come back with the page and a saved session ----------
function state() { return { pads: racks.map(R => ({ id: R.id, s: R.s, asOf: R.asOf })), colorBy, metric, picked }; }
function save() {
  // pads first, in order, commas left readable
  const q = new URLSearchParams(location.search); q.delete('pads');
  const parts = [racks.length ? 'pads=' + racks.map(R => encodeURIComponent(R.id)).join(',') : '', String(q)].filter(Boolean);
  history.replaceState(null, '', location.pathname + (parts.length ? '?' + parts.join('&') : ''));
  try { sessionStorage.setItem(STATE_KEY, JSON.stringify(state())); } catch (e) { /* private mode */ }
}
let saveT = 0;
const saveSoon = () => { clearTimeout(saveT); saveT = setTimeout(save, 250); };
if (window.StratumSession) StratumSession.provide(() => ({ [STATE_KEY]: JSON.stringify(state()) }));

function setColor(m) {
  colorBy = !MODES.includes(m) || (m === 'gamma' && !gamma) || (m !== 'gamma' && m !== 'pad' && !FM) ? 'pad' : m;
  document.querySelectorAll('[data-color]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.color === colorBy)));
  key(); renderAll(); save();
}
document.querySelectorAll('[data-color]').forEach(b => { b.onclick = () => setColor(b.dataset.color); });
addEventListener('stratum:gammapalette', () => { key(); renderAll(); });
addEventListener('stratum:theme', () => { key(); renderAll(); });
// the parent/child labels, again whenever the limits change in Settings (here or in another window)
const loadRels = () => FM && FM.relations().then(m => { rels = m; renderAll(); }).catch(() => {});
addEventListener('stratum:spacing', () => { limitsNote(); loadRels(); });
$('wr-limits').onclick = () => { if (window.StratumMenu) StratumMenu.open('settings'); };
let rz = 0;
addEventListener('resize', () => { cancelAnimationFrame(rz); rz = requestAnimationFrame(renderAll); });
// the map's "only wells with treatment charts" changed: the racks reload with it
addEventListener('storage', e => { if (e.key === 'stratum.allWells') racks.forEach(R => { R.p = R.g = null; R.error = null; R.el.querySelector('.rk-body').hidden = true; fill(R); }); });

// ---------- start ----------
window.stratumRacks = { add: (id, from) => add(id, { owner: from }), list: () => racks.map(R => R.id),
  png: id => { const R = racks.find(x => x.id === id); return R ? rackPng(R) : Promise.resolve(null); } };
(async () => {
  let st = null;
  try { st = JSON.parse(sessionStorage.getItem(STATE_KEY) || 'null'); } catch (e) { /* private mode */ }
  const lines = new Map(((st && st.pads) || []).map(x => [String(x.id), x.s]));
  const asOfs = new Map(((st && st.pads) || []).map(x => [String(x.id), Number.isFinite(x.asOf) ? x.asOf : null]));
  if (st && st.picked) picked = st.picked;
  if (st && FM && FM.BY[st.metric]) metric = st.metric;
  limitsNote(); loadRels();
  const ids = (Q.get('pads') || '').split(',').map(x => x.trim()).filter(Boolean);
  // a page that reached this window while it was still loading left its pads here
  const queued = Array.isArray(window.stratumRackQueue) ? window.stratumRackQueue.map(String) : [];
  // opened just now for a pad (not reopened with the page or a session): that pad starts the main window's section
  const fresh = !st && ids.length === 1 && !queued.length;
  [...ids, ...queued].forEach(id => add(id, { s: lines.get(id), asOf: asOfs.get(id), quiet: !fresh }));
  if (chan && !owner) chan.postMessage({ type: 'hello' });
  head();
  await gammaReady;
  if (st && st.colorBy && st.colorBy !== 'pad') setColor(st.colorBy); else head();
})();

// ---------- PNG: a rack as it is on screen, plan and section, at twice the size ----------
// CSS variables don't survive serialising an SVG, so every mark's computed colours go inline
const INLINE = ['fill', 'stroke', 'stroke-width', 'stroke-dasharray', 'opacity', 'font-size', 'font-family', 'font-weight', 'paint-order', 'stroke-linejoin'];
function svgImage(svg) {
  const copy = svg.cloneNode(true), from = svg.querySelectorAll('*'), to = copy.querySelectorAll('*');
  from.forEach((e, i) => { const cs = getComputedStyle(e); to[i].setAttribute('style', INLINE.map(p => `${p}:${cs.getPropertyValue(p)}`).join(';')); });
  copy.querySelectorAll('title').forEach(t => t.remove());
  copy.setAttribute('xmlns', SVGNS); copy.setAttribute('width', svg.clientWidth); copy.setAttribute('height', svg.clientHeight);
  copy.setAttribute('style', `font-family:${getComputedStyle(svg).fontFamily}`);
  return new Promise((res, rej) => {
    const img = new Image();
    img.onload = () => res(img); img.onerror = () => rej(Error('The drawing could not be read as an image.'));
    img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(new XMLSerializer().serializeToString(copy));
  });
}
const MODE_NAME = { pad: 'pad', gamma: 'gamma at the line', relation: 'parent/child', date: 'frac date' };
async function rackPng(R) {
  if (!R.g) return null;
  const css = getComputedStyle(document.documentElement), v = n => css.getPropertyValue(n).trim();
  const body = R.el.querySelector('.rk-body').getBoundingClientRect(), svgs = [...R.el.querySelectorAll('.rk-body svg')];
  const head = 58, m = 16, W = Math.ceil(body.width + 2 * m), H = Math.ceil(body.height + head + m), k = 2;
  const cv = document.createElement('canvas'); cv.width = W * k; cv.height = H * k;
  const c = cv.getContext('2d'); c.scale(k, k);
  c.fillStyle = v('--panel'); c.fillRect(0, 0, W, H);
  const sans = '-apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif', mono = 'ui-monospace, Menlo, Consolas, monospace';
  c.fillStyle = v('--ink'); c.font = `600 16px ${sans}`; c.fillText(`${R.p.name} · wine rack`, m, 24);
  // a measure about a centre (a trend, % of filed) runs blue through grey to orange
  const dom = colorBy === 'metric' ? rackDomain(R, metric) : null, sp = R.span, ends = colorBy === 'metric' && FM.BY[metric].centre != null ? ['blue', 'orange'] : rampEnds();
  const how = colorBy === 'metric' ? `${FM.BY[metric].t} for the stage at the line${dom ? ` (${FM.fmt(dom[0], metric)} ${ends[0]} to ${FM.fmt(dom[1], metric)} ${ends[1]})` : ''}`
    : colorBy === 'date' && sp ? `frac date (${dayStr(sp[0])} ${rampEnds()[0]} to ${dayStr(sp[1])} ${rampEnds()[1]})` : MODE_NAME[colorBy];
  c.fillStyle = v('--mut'); c.font = `11.5px ${mono}`;
  c.fillText(`${R.el.querySelector('.rk-where').textContent} · coloured by ${how} · ${R.asOf == null ? 'all wells' : 'as of ' + dayStr(R.asOf)}`, m, 42);
  for (const s of svgs) {
    const b = s.getBoundingClientRect(), x = m + b.left - body.left, y = head + b.top - body.top;
    c.fillStyle = v('--plot'); c.strokeStyle = v('--line'); c.lineWidth = 1;
    c.beginPath(); c.roundRect(x + .5, y + .5, b.width - 1, b.height - 1, 12); c.fill(); c.stroke();
    c.drawImage(await svgImage(s), x, y, b.width, b.height);
  }
  return new Promise(res => cv.toBlob(res, 'image/png'));
}
async function savePng(R) {
  const b = R.el.querySelector('.rk-png');
  b.disabled = true;
  try {
    const blob = await rackPng(R);
    if (!blob) return;
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = `FracView-rack-${R.id}.png`;
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  } catch (e) { console.warn('rack PNG', e); } finally { b.disabled = false; }
}

// the area this window is on, for a saved session's list (session.js)
window.stratumArea = () => racks.filter(R => R.p).map(R => R.p.name).slice(0, 3).join(', ') + (racks.length > 3 ? ` +${racks.length - 3}` : '');
