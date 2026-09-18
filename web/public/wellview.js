(() => {
'use strict';
// Stratum's single-well view: one horizontal well, drawn from its own
// directional survey, with the treatment that was pumped at each stage.
//
// Every value shown is read from the well record. Where a source has no value
// the panel says "Not supplied" -- a blank is never turned into a zero, and no
// curve is ever synthesised from a summary. Geology notes and formation
// materials are not held for any well yet, so those sections say so rather
// than standing empty.

const qs = new URLSearchParams(location.search);
const WA = qs.get('wa') || '';
const $ = id => document.getElementById(id);

const cv = $('wv-canvas'), ctx = cv.getContext('2d');
const tip = $('wv-tip');
let W = null;                 // the well record
let STAGES = [];              // treatment stages, ordered by number
let ENG = new Map();          // stage key -> engineering summary
let pts = [];                 // trajectory as [x=east, y=-tvd, z=north] metres
let sel = 0;                  // selected stage index
let follow = false, playing = 0;
let hits = [];                // stage markers in screen space, for hover/click

const camera = { yaw: -0.6, pitch: 0.35, scale: 0.09, target: [0, -1000, 0], pan: [0, 0] };
const goal = { scale: 0.09, target: [0, -1000, 0] };
let drag = null, hover = null, raf = 0;

const fmt = (v, d = 0) => v == null || v === '' || Number.isNaN(+v)
  ? null : Number(v).toLocaleString(undefined, { maximumFractionDigits: d });

// ---------------------------------------------------------------- geometry
function buildPoints(t) {
  const n = (t.md || []).length;
  const out = [];
  for (let i = 0; i < n; i++) {
    const ew = t.ew[i], ns = t.ns[i], tvd = t.tvd[i];
    if (![ew, ns, tvd].every(Number.isFinite)) continue;
    out.push([ew, -tvd, ns, t.md[i]]);
  }
  return out;
}

function pointAtMd(md) {
  if (!pts.length || md == null) return null;
  let i = pts.findIndex(p => p[3] >= md);
  if (i < 0) return pts[pts.length - 1];
  if (i === 0) return pts[0];
  const a = pts[i - 1], b = pts[i];
  const v = (md - a[3]) / ((b[3] - a[3]) || 1);
  return [a[0] + (b[0] - a[0]) * v, a[1] + (b[1] - a[1]) * v, a[2] + (b[2] - a[2]) * v, md];
}

function project(p) {
  const c = Math.cos(camera.yaw), s = Math.sin(camera.yaw);
  const cp = Math.cos(camera.pitch), sp = Math.sin(camera.pitch);
  const x = p[0] - camera.target[0], y = p[1] - camera.target[1], z = p[2] - camera.target[2];
  const X = x * c - z * s, Z = x * s + z * c;
  // canvas y grows downward and world y is -TVD, so the vertical term is
  // subtracted: deeper has to draw lower, not higher
  return [cv.width / 2 + (X * camera.scale) + camera.pan[0],
          cv.height / 2 - ((y * cp - Z * sp) * camera.scale) + camera.pan[1]];
}

function orientToLateral() {
  // Point the camera across the well's own heading, so the lateral reads at its
  // true length instead of being foreshortened into a vertical stick.
  if (pts.length < 2) return;
  const a = pts[0], b = pts[pts.length - 1];
  const de = b[0] - a[0], dn = b[2] - a[2];
  if (Math.hypot(de, dn) < 1) return;
  camera.yaw = Math.atan2(-dn, de);
}

function fitAll() {
  if (!pts.length) return;
  const mn = [0, 1, 2].map(i => Math.min(...pts.map(p => p[i])));
  const mx = [0, 1, 2].map(i => Math.max(...pts.map(p => p[i])));
  goal.target = mn.map((v, i) => (v + mx[i]) / 2);
  camera.target = goal.target.slice();
  camera.pan = [0, 0];
  const save = camera.scale; camera.scale = 1;
  const pj = pts.map(project);
  camera.scale = save;
  const w = Math.max(...pj.map(q => q[0])) - Math.min(...pj.map(q => q[0]));
  const h = Math.max(...pj.map(q => q[1])) - Math.min(...pj.map(q => q[1]));
  goal.scale = Math.min((cv.width * 0.78) / (w || 1), (cv.height * 0.72) / (h || 1));
  camera.scale = goal.scale;
}

function focusStage(i, hard) {
  sel = Math.max(0, Math.min(STAGES.length - 1, i));
  const s = STAGES[sel];
  const p = s && pointAtMd(s.top_m);
  if (p && (follow || hard)) {
    goal.target = [p[0], p[1], p[2]];
    goal.scale = Math.max(goal.scale, 0.5);
  }
  render();
  draw();
}

// -------------------------------------------------------------------- draw
function resize() {
  const r = cv.parentElement.getBoundingClientRect();
  const dpr = Math.min(devicePixelRatio || 1, 2);
  cv.width = Math.max(1, Math.round(r.width * dpr));
  cv.height = Math.max(1, Math.round(r.height * dpr));
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  draw();
}

function draw() {
  if (!pts.length) return;
  camera.target = camera.target.map((v, i) => v + (goal.target[i] - v) * 0.22);
  camera.scale += (goal.scale - camera.scale) * 0.22;
  const dpr = cv.width / cv.parentElement.clientWidth;
  ctx.clearRect(0, 0, cv.width, cv.height);

  // a short ground tick at the wellhead for orientation
  const surf = pts[0];
  const span = Math.max(60, Math.abs(pts[pts.length - 1][0] - surf[0]) * 0.06);
  const a = project([surf[0] - span, 0, surf[2]]), b = project([surf[0] + span, 0, surf[2]]);
  ctx.strokeStyle = '#24404f'; ctx.lineWidth = 1 * dpr;
  ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();

  // the whole surveyed path, kept faintly visible
  ctx.strokeStyle = '#3c6070'; ctx.lineWidth = 2 * dpr;
  ctx.beginPath();
  pts.forEach((p, i) => { const q = project(p); i ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1]); });
  ctx.stroke();

  // the selected stage's own interval, bright
  const s = STAGES[sel];
  if (s && s.top_m != null) {
    const top = pointAtMd(s.top_m), base = pointAtMd(s.base_m != null ? s.base_m : s.top_m);
    if (top && base) {
      const p1 = project(top), p2 = project(base);
      ctx.strokeStyle = '#5ee2d0'; ctx.lineWidth = 5 * dpr; ctx.lineCap = 'round';
      ctx.beginPath(); ctx.moveTo(p1[0], p1[1]); ctx.lineTo(p2[0], p2[1]); ctx.stroke();
      ctx.beginPath(); ctx.arc(p1[0], p1[1], 9 * dpr, 0, 7);
      ctx.strokeStyle = '#9afbe8'; ctx.lineWidth = 2 * dpr; ctx.stroke();
    }
  }

  // every stage marker
  hits = [];
  STAGES.forEach((st, i) => {
    if (st.top_m == null) return;
    const p = pointAtMd(st.top_m); if (!p) return;
    const q = project(p);
    const on = i === sel, hv = hover === i;
    ctx.beginPath(); ctx.arc(q[0], q[1], (on ? 5 : hv ? 4.5 : 3) * dpr, 0, 7);
    ctx.fillStyle = on ? '#9afbe8' : st.series && Object.keys(st.series).length ? '#4d8dff' : '#5d7585';
    ctx.fill();
    hits.push({ i, x: q[0] / dpr, y: q[1] / dpr, r: 9 });
  });

  // heel + toe callouts, each labelled with the depth basis it actually is
  const toe = pts[pts.length - 1];
  label(project(pts[0]), 'surface', '#7f97a4', dpr);
  label(project(toe), `toe ${fmt(toe[3])} m MD · ${fmt(-toe[1])} m TVD`, '#7f97a4', dpr);
}

function label(q, text, colour, dpr) {
  ctx.font = `${11 * dpr}px ui-monospace,Menlo,monospace`;
  ctx.fillStyle = colour;
  ctx.fillText(text, q[0] + 8 * dpr, q[1] - 6 * dpr);
}

function loop() { draw(); raf = requestAnimationFrame(loop); }

// ------------------------------------------------------------------ graphs
// Both graphs share one elapsed-time window, so zooming or panning either
// moves both. Gaps in the source stay gaps: a null breaks the line.
const view = { t0: 0, t1: 1 };
const CH = { press: ['Treating pressure', '#ff6b6b'], rate: ['Slurry rate', '#4d8dff'],
             wh_conc: ['WH proppant conc', '#3ecf8e'], bh_conc: ['BH proppant conc', '#c79bff'] };

function stageSeries(st) {
  const out = {};
  for (const k of Object.keys(CH)) {
    const v = st && st.series && st.series[k];
    if (Array.isArray(v) && v.some(x => x != null)) out[k] = v;
  }
  return out;
}

function elapsedOf(st, n) {
  const step = st.step_s || 1;
  return Array.from({ length: n }, (_, i) => i * step);
}

function resetZoom() {
  const st = STAGES[sel]; const ser = stageSeries(st);
  const n = Math.max(0, ...Object.values(ser).map(a => a.length));
  view.t0 = 0; view.t1 = Math.max(1, (n - 1) * (st.step_s || 1));
  drawGraphs();
}

function drawGraph(cnv, keys, emptyEl, labEl) {
  const st = STAGES[sel]; const ser = stageSeries(st);
  const use = keys.filter(k => ser[k]);
  const g = cnv.getContext('2d');
  const dpr = Math.min(devicePixelRatio || 1, 2);
  const r = cnv.parentElement.getBoundingClientRect();
  cnv.width = Math.max(1, Math.round(r.width * dpr));
  cnv.height = Math.max(1, Math.round(r.height * dpr));
  g.clearRect(0, 0, cnv.width, cnv.height);
  if (!use.length) {
    emptyEl.hidden = false;
    emptyEl.textContent = st && st.source && String(st.source).startsWith('BCER')
      ? 'No treatment curves for this stage — the completion table gives its depth and date only. Summary values are listed beside the well.'
      : 'This channel was not supplied for this stage.';
    labEl.style.opacity = .35;
    return;
  }
  emptyEl.hidden = true; labEl.style.opacity = 1;
  const PADL = 46 * dpr, PADR = 10 * dpr, PADT = 22 * dpr, PADB = 18 * dpr;
  const x = t => PADL + (t - view.t0) / ((view.t1 - view.t0) || 1) * (cnv.width - PADL - PADR);
  // one vertical scale per graph, across the channels it draws
  let hi = -Infinity, lo = Infinity;
  for (const k of use) for (const v of ser[k]) if (v != null) { if (v > hi) hi = v; if (v < lo) lo = v; }
  if (!Number.isFinite(hi)) { hi = 1; lo = 0; }
  if (lo > 0) lo = 0;                       // keep zero in view, but never clip negatives
  const y = v => cnv.height - PADB - (v - lo) / ((hi - lo) || 1) * (cnv.height - PADT - PADB);

  g.strokeStyle = '#172836'; g.lineWidth = 1 * dpr;
  g.beginPath(); g.moveTo(PADL, y(0)); g.lineTo(cnv.width - PADR, y(0)); g.stroke();

  for (const k of use) {
    const vals = ser[k], ts = elapsedOf(st, vals.length);
    g.strokeStyle = CH[k][1]; g.lineWidth = 1.4 * dpr; g.beginPath();
    let pen = false;
    for (let i = 0; i < vals.length; i++) {
      if (vals[i] == null) { pen = false; continue; }      // a gap stays a gap
      const px = x(ts[i]), py = y(vals[i]);
      if (!pen) { g.moveTo(px, py); pen = true; } else g.lineTo(px, py);
    }
    g.stroke();
  }
  g.fillStyle = '#6d8794'; g.font = `${10 * dpr}px ui-monospace,Menlo,monospace`;
  g.fillText(fmt(hi, 1), 6 * dpr, PADT + 4 * dpr);
  g.fillText(fmt(lo, 1), 6 * dpr, cnv.height - PADB + 2 * dpr);
  const mins = t => (t / 60).toFixed(0) + 'm';
  g.fillText(mins(view.t0), PADL, cnv.height - 4 * dpr);
  g.textAlign = 'right'; g.fillText(mins(view.t1), cnv.width - PADR, cnv.height - 4 * dpr);
  g.textAlign = 'left';
}

function drawGraphs() {
  drawGraph($('wv-g1'), ['press', 'rate'], $('wv-g1-empty'), $('wv-g1-lab'));
  drawGraph($('wv-g2'), ['wh_conc', 'bh_conc'], $('wv-g2-empty'), $('wv-g2-lab'));
  const st = STAGES[sel], ser = stageSeries(st);
  $('wv-legend').innerHTML = Object.keys(CH).filter(k => ser[k])
    .map(k => `<span><i style="background:${CH[k][1]}"></i>${CH[k][0]} (${(W.units || {})[k] || ''})</span>`).join('')
    || '<span>no channels for this stage</span>';
}

function wireGraph(cnv) {
  cnv.addEventListener('wheel', e => {
    e.preventDefault();
    const r = cnv.getBoundingClientRect();
    const f = (e.clientX - r.left - 23) / Math.max(1, r.width - 28);
    const at = view.t0 + f * (view.t1 - view.t0);
    const k = e.deltaY > 0 ? 1.18 : 1 / 1.18;
    view.t0 = at - (at - view.t0) * k;
    view.t1 = at + (view.t1 - at) * k;
    drawGraphs();
  }, { passive: false });
  let gd = null;
  cnv.addEventListener('pointerdown', e => { gd = { x: e.clientX, t0: view.t0, t1: view.t1 }; cnv.setPointerCapture(e.pointerId); });
  cnv.addEventListener('pointermove', e => {
    if (!gd) return;
    const r = cnv.getBoundingClientRect();
    const d = (e.clientX - gd.x) / Math.max(1, r.width) * (gd.t1 - gd.t0);
    view.t0 = gd.t0 - d; view.t1 = gd.t1 - d;
    drawGraphs();
  });
  cnv.addEventListener('pointerup', () => { gd = null; });
}

// ------------------------------------------------------------- side panel
const NA = '<dd class="na">Not supplied</dd>';
function row(label, value, unit) {
  const v = value == null || value === '' ? null : value;
  return `<dt>${label}</dt>${v == null ? NA : `<dd>${v}${unit ? ' ' + unit : ''}</dd>`}`;
}

function engFor(st) {
  return ENG.get(String(st.label)) || ENG.get('n:' + st.n) || null;
}

function render() {
  const st = STAGES[sel] || {};
  const e = engFor(st) || {};
  const w = W.well || {};
  const curves = Object.keys(stageSeries(st)).length;
  const depthNote = st.placed
    ? '<div class="wv-warn">This stage has no printed depth. It is placed by its stage number, not measured.</div>' : '';
  const mismatch = (W.bcer_stages || []).length && (W.bcer_stages || []).length !== STAGES.length
    ? `<div class="wv-warn">The operator filed ${W.bcer_stages.length} intervals and the Lab charted ${STAGES.length}. The two numberings are kept separate; where they cannot be reconciled a stage keeps its own label.</div>` : '';

  $('wv-side').innerHTML = `
  <section>
    <h2>Selected stage</h2>
    <dl class="wv-facts">
      ${row('Stage', st.label)}
      ${row('Treatment date', st.date)}
      ${row(st.base_m != null && st.base_m !== st.top_m ? 'Interval top (MD)' : 'Port depth (MD)', fmt(st.top_m, 1), 'm')}
      ${st.base_m != null && st.base_m !== st.top_m ? row('Interval base (MD)', fmt(st.base_m, 1), 'm') : ''}
      ${row('Duration', fmt(e.minutes != null ? e.minutes : st.minutes, 1), 'min')}
    </dl>
    ${depthNote}
  </section>

  <section>
    <h2>Reported treatment</h2>
    <dl class="wv-facts">
      ${row('Average rate', fmt(e.avg_rate_m3_min, 2), 'm³/min')}
      ${row('Maximum rate', fmt(e.max_rate_m3_min, 2), 'm³/min')}
      ${row('Average pressure', fmt(e.avg_pressure_mpa, 1), 'MPa')}
      ${row('Minimum pressure', fmt(e.min_pressure_mpa, 1), 'MPa')}
      ${row('Maximum pressure', fmt(e.max_pressure_mpa, 1), 'MPa')}
      ${row('Breakdown pressure', fmt(e.breakdown_mpa, 1), 'MPa')}
      ${row('ISIP', fmt(e.isip_mpa, 1), 'MPa')}
      ${row('Proppant placed', fmt(e.proppant_t, 1), 't')}
      ${row('Slurry volume', fmt(e.slurry_vol_m3, 1), 'm³')}
      ${row('Pad volume', fmt(e.pad_vol_m3, 1), 'm³')}
      ${row('Average concentration', fmt(e.avg_conc_kg_m3, 1), 'kg/m³')}
    </dl>
    ${e.proppant_types ? `<div class="wv-note" style="margin-top:8px">Proppant: ${e.proppant_types}</div>` : ''}
    ${e.chemicals && Object.keys(e.chemicals).length
      ? `<div class="wv-note" style="margin-top:6px">Chemicals (L): ${Object.entries(e.chemicals).map(([k, v]) => `${k} ${fmt(v, 1)}`).join(' · ')}</div>` : ''}
  </section>

  <section>
    <h2>Geologist notes</h2>
    <div class="wv-empty">Not supplied. No geology has been filed for this well; notes would be joined by verified well and stage identity, never copied across stages.</div>
  </section>

  <section>
    <h2>Formation materials</h2>
    <div class="wv-empty">Not supplied. Rock and mineral observations are held separately from pumped proppant and chemicals, and none exist for this well.</div>
  </section>

  <section>
    <h2>Source</h2>
    <dl class="wv-facts">
      ${row('Report', W.file)}
      ${row('Stage source', st.source)}
      ${row('Summary source', e.source)}
      ${row('Survey stations', fmt((W.trajectory && W.trajectory.md || []).length))}
      ${row('Curve points', curves ? fmt((st.series[Object.keys(st.series)[0]] || []).length) : null)}
      ${row('Sample step', st.step_s ? st.step_s + ' s' : null)}
    </dl>
    ${(st.notes || []).length ? `<div class="wv-note" style="margin-top:8px">${st.notes.join('<br>')}</div>` : ''}
    ${mismatch}
  </section>`;

  document.querySelectorAll('#wv-steps button').forEach((b, i) => b.classList.toggle('on', i === sel));
  $('wv-badge').textContent = `stage ${st.label || '–'} · ${curves ? curves + ' channels' : 'summary only'}`;
  resetZoom();
}

// --------------------------------------------------------------------- run
async function load() {
  if (!WA) { $('wv-name').textContent = 'No well selected'; return; }
  let d;
  try { d = await (await fetch(`data/wells/${encodeURIComponent(WA)}.json`)).json(); }
  catch (err) { $('wv-name').textContent = `Well ${WA} not found`; return; }
  W = d;
  const w = d.well || {};
  STAGES = (d.stages || []).slice().sort((a, b) => (a.n || 0) - (b.n || 0));
  for (const e of d.engineering_stages || []) {
    ENG.set(String(e.label), e);
    if (!ENG.has('n:' + e.n)) ENG.set('n:' + e.n, e);
  }
  pts = buildPoints(d.trajectory || {});

  $('wv-name').textContent = w.name || `WA ${WA}`;
  $('wv-ident').textContent = [w.uwi, `WA ${w.wa || WA}`, w.prov, d.pad && d.pad.name,
    w.td_m ? `MD ${fmt(w.td_m)} m` : null, w.tvd_m ? `TVD ${fmt(w.tvd_m)} m` : null,
    w.lateral_m ? `lateral ~${fmt(w.lateral_m)} m` : null].filter(Boolean).join(' · ');

  $('wv-steps').innerHTML = STAGES.map((s, i) =>
    `<button type="button" data-i="${i}" title="Stage ${s.label}">${s.label}</button>`).join('');
  $('wv-steps').querySelectorAll('button').forEach(b =>
    b.addEventListener('click', () => focusStage(+b.dataset.i, true)));

  $('wv-foot').innerHTML = pts.length
    ? `Drawn from ${fmt(pts.length)} directional-survey stations. Depths are measured (MD) unless marked TVD. Curves are the Lab's export thinned to ${STAGES[0] && STAGES[0].step_s ? STAGES[0].step_s + ' s' : 'a few seconds'} per point; gaps in the source are left as gaps.`
    : 'No directional survey is held for this well, so no path can be drawn.';

  resize(); orientToLateral(); fitAll();
  const want = +qs.get('stage');
  sel = Math.max(0, STAGES.findIndex(s => +s.n === want));
  if (sel < 0) sel = 0;
  render();
  loop();
}

// controls
$('wv-prev').onclick = () => focusStage(sel - 1, true);
$('wv-next').onclick = () => focusStage(sel + 1, true);
$('wv-reset').onclick = () => { camera.pitch = 0.35; orientToLateral(); fitAll(); draw(); };
$('wv-gzoom').onclick = resetZoom;
$('wv-follow').onclick = e => {
  follow = !follow;
  e.target.classList.toggle('on', follow); e.target.setAttribute('aria-pressed', follow);
  if (follow) focusStage(sel, true);
};
$('wv-play').onclick = e => {
  if (playing) { clearInterval(playing); playing = 0; }
  else playing = setInterval(() => {
    if (sel >= STAGES.length - 1) { clearInterval(playing); playing = 0; e.target.classList.remove('on'); e.target.setAttribute('aria-pressed', false); return; }
    focusStage(sel + 1, true);
  }, 1100);
  e.target.classList.toggle('on', !!playing); e.target.setAttribute('aria-pressed', !!playing);
};
// back: the browser's own history restores the pad or underground view with the
// camera and selection it had; only fall back when this page was opened cold
$('wv-back').onclick = () => {
  if (history.length > 1 && document.referrer && new URL(document.referrer, location.href).origin === location.origin) history.back();
  else location.href = W && W.pad && W.pad.id
    ? `pad.html?set=${encodeURIComponent(String(W.pad.id).replace(/-\d+$/, ''))}&pad=${encodeURIComponent(W.pad.id)}`
    : 'map.html';
};
addEventListener('keydown', e => {
  if (e.key === 'ArrowLeft') focusStage(sel - 1, true);
  if (e.key === 'ArrowRight') focusStage(sel + 1, true);
});

// 3D interaction
cv.addEventListener('contextmenu', e => e.preventDefault());
cv.addEventListener('pointerdown', e => {
  drag = { x: e.clientX, y: e.clientY, pan: e.shiftKey || e.button === 2 };
  cv.setPointerCapture(e.pointerId); cv.style.cursor = 'grabbing';
});
cv.addEventListener('pointermove', e => {
  if (drag) {
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (drag.pan) { camera.pan[0] += dx; camera.pan[1] += dy; }
    else { camera.yaw += dx * 0.006; camera.pitch = Math.max(-0.9, Math.min(1.3, camera.pitch + dy * 0.005)); }
    drag.x = e.clientX; drag.y = e.clientY;
    return;
  }
  const r = cv.getBoundingClientRect();
  const mx = e.clientX - r.left, my = e.clientY - r.top;
  const h = hits.find(q => Math.hypot(q.x - mx, q.y - my) < q.r);
  hover = h ? h.i : null;
  cv.style.cursor = h ? 'pointer' : 'grab';
  if (h) {
    const st = STAGES[h.i], en = engFor(st) || {};
    tip.style.display = 'block';
    tip.innerHTML = `<b>Stage ${st.label}</b><br>${st.top_m != null ? fmt(st.top_m, 1) + ' m MD' : 'depth not supplied'}`
      + `${st.date ? ' · ' + st.date : ''}<br>`
      + `${en.avg_rate_m3_min != null ? fmt(en.avg_rate_m3_min, 2) + ' m³/min' : 'rate not supplied'}`
      + ` · ${en.proppant_t != null ? fmt(en.proppant_t, 1) + ' t' : 'proppant not supplied'}`;
    tip.style.left = Math.min(innerWidth - 270, e.clientX + 14) + 'px';
    tip.style.top = Math.min(innerHeight - 80, e.clientY + 14) + 'px';
  } else tip.style.display = 'none';
});
cv.addEventListener('pointerup', e => {
  if (drag && Math.abs(e.clientX - drag.x) < 3 && hover != null) focusStage(hover, true);
  drag = null; cv.style.cursor = 'grab';
});
cv.addEventListener('wheel', e => {
  e.preventDefault();
  goal.scale = Math.max(0.01, Math.min(40, goal.scale * (e.deltaY > 0 ? 1 / 1.12 : 1.12)));
}, { passive: false });
addEventListener('resize', () => { resize(); drawGraphs(); });
wireGraph($('wv-g1')); wireGraph($('wv-g2'));
load();
})();
