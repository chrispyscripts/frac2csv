// Stratum — one well's treatment charts, in the Lab's three views.
//
// Stage chart: the Lab's combined graph, each curve on its own axis rounded up
// to a readable top, curves switched off from the legend (double-click isolates
// one). Stacked and FracView are the Lab's own pages (lab/), embedded and fed
// over the same postMessage protocol the Lab main window speaks to them, so
// they behave exactly as they do beside the Lab. This page plays the Lab's
// part: it owns the selected stage, and the two views follow it.
'use strict';
const $ = id => document.getElementById(id);
const WA = new URLSearchParams(location.search).get('wa') || '';
const ORIGIN = location.origin;

// Stratum's series keys -> the Lab's names and colours ("Our terms"), so a
// curve is called and coloured the same here, in Stacked and in FracView.
const SERIES = [
  { k: 'press', name: 'Tr Press', color: '#f0555a' },
  { k: 'rate', name: 'Slurry Rate', color: '#4f8ff7' },
  { k: 'wh_conc', name: 'WH Prop Conc', color: '#3fb950' },
  { k: 'bh_conc', name: 'BH Prop Conc', color: '#b87fd9' },
  { k: 'bh_press', name: 'BH Press', color: '#39c5cf' },
];
const GP = { L: 50, R: 16, T: 14, B: 40 };
const NICE_STEPS = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
const HIDDEN_KEY = 'stratum.hiddenCurves';

let W = null;          // the well file
let STAGES = [];       // stages that carry curves, in stage order
let sel = 0;
let view = { t0: 0, t1: 1 };   // seconds into the selected stage
let hoverT = null, drag = null;
let hidden = new Set();
let QUAKES = [];       // earthquakes the seismic build matched to this well's stages, as the quake filter leaves them
let QUAKES_ALL = [];   // ... and before it (quake-filter.js: the map's and 3D view's filter, one setting)
try { hidden = new Set(JSON.parse(localStorage.getItem(HIDDEN_KEY) || '[]')); } catch (e) { /* private mode */ }

const fmt = (v, d = 0) => v == null || !isFinite(v) ? '–'
  : Number(v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d });
const p2 = n => String(n).padStart(2, '0');
function niceCeil(v) {
  if (!(v > 0)) return 1;
  const e = Math.pow(10, Math.floor(Math.log10(v))), m = v / e;
  for (const s of NICE_STEPS) if (m <= s + 1e-9) return s * e;
  return 10 * e;
}
const tMax = st => Math.max(st.dsec, (st.n - 1) * st.dsec);
const stageId = st => `${WA} · ${st.label}`;

function buildStages(d) {
  const units = d.units || {};
  return (d.stages || []).filter(s => s.series).map(s => {
    const clock0 = s.date && s.start ? new Date(`${s.date}T${s.start}`).getTime() : NaN;
    const utc0 = s.date && s.start ? Date.parse(`${s.date}T${s.start.slice(0, 8)}-07:00`) : NaN;
    const channels = [];
    for (const def of SERIES) {
      const src = s.series[def.k];
      if (!Array.isArray(src) || !src.some(v => v != null)) continue;
      const values = new Float64Array(src.length);
      let lo = Infinity, hi = -Infinity;
      src.forEach((v, i) => {
        values[i] = v == null || !isFinite(v) ? NaN : v;
        if (v != null && isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; }
      });
      channels.push({ name: def.name, color: def.color, unit: units[def.k] || '', values,
                      dataLo: lo, vmax: hi, hi: niceCeil(hi) });
    }
    const n = Math.max(0, ...channels.map(c => c.values.length));
    return { label: String(s.label), n, dsec: s.step_s || 1, date: s.date || '', start: s.start || '',
             clock0: isFinite(clock0) ? clock0 : null, utc0: isFinite(utc0) ? utc0 : null, top_m: s.top_m, base_m: s.base_m,
             placed: !!s.placed, minutes: s.minutes, channels };
  }).filter(s => s.channels.length)
    .sort((a, b) => (parseFloat(a.label) - parseFloat(b.label)) || (a.label < b.label ? -1 : 1));
}

// ---------- page ----------
async function load() {
  let d;
  try {
    const r = await fetch(`data/wells/${encodeURIComponent(WA)}.json`);
    if (!r.ok) throw Error(r.status);
    d = await r.json();
  } catch (e) {
    $('wc-name').textContent = `Well ${WA || '?'} not found`;
    return;
  }
  W = d;
  const w = d.well || {};
  document.title = `FracView — ${w.name || 'WA ' + WA}`;
  $('wc-name').textContent = w.name || `WA ${WA}`;
  STAGES = buildStages(d);
  $('wc-ident').textContent = [`WA ${WA}`, w.uwi, d.pad && d.pad.name,
    STAGES.length ? `${STAGES.length} of ${(d.stages || []).length} stages with treatment curves`
      : `${(d.bcer_stages || d.stages || []).length} stages filed · no treatment curves yet`].filter(Boolean).join(' · ');
  const steps = STAGES.map(s => s.dsec).sort((a, b) => a - b);
  $('wc-foot').textContent = STAGES.length
    ? `Curves: the Lab's read of ${d.file || 'the operator’s frac report'}, kept at ~${fmt(STAGES[0].n)} points a stage (one every ${steps[0]}–${steps[steps.length - 1]} s). Stacked and Sequential (the Lab's FracView) are Carmine's Lab views, read-only here.`
    : '';
  if (!STAGES.length) {
    // no curves yet: the stages as filed with the BCER still say what was pumped where
    const filed = (d.bcer_stages || []).filter(s => s.top_m != null || s.avg_rate_m3_min != null)
      .sort((a, b) => a.n - b.n);
    const box = $('wc-empty');
    box.hidden = false;
    box.classList.toggle('wc-filed', filed.length > 0);
    box.replaceChildren();
    const p = document.createElement('p');
    p.textContent = filed.length
      ? `No treatment curves yet: the Lab has not read this well's frac report. These are its ${filed.length} stages as filed with the BCER.`
      : 'No treatment curves have been extracted for this well yet.';
    box.append(p);
    if (filed.length) {
      const cols = [['Stage', s => s.label], ['Date', s => s.date || '–'], ['Top–base MD (m)', s => s.top_m == null ? '–' : `${fmt(s.top_m, 1)}–${fmt(s.base_m, 1)}`],
        ['Avg rate (m³/min)', s => fmt(s.avg_rate_m3_min, 2)], ['Avg P (MPa)', s => fmt(s.avg_pressure_mpa, 1)],
        ['Max P (MPa)', s => fmt(s.max_pressure_mpa, 1)], ['Breakdown (MPa)', s => fmt(s.breakdown_mpa, 1)], ['ISIP (MPa)', s => fmt(s.isip_mpa, 1)],
        ['Proppant (t)', s => fmt(s.proppant_t, 1)], ['Fluid (m³)', s => fmt(s.fluid_m3, 1)]];
      const t = document.createElement('table');
      t.innerHTML = '<thead><tr>' + cols.map(c => `<th>${c[0]}</th>`).join('') + '</tr></thead>';
      const tb = document.createElement('tbody');
      filed.forEach(s => { const tr = document.createElement('tr'); cols.forEach(c => { const td = document.createElement('td'); td.textContent = c[1](s); tr.append(td); }); tb.append(tr); });
      t.append(tb); box.append(t);
      $('wc-canvas').hidden = true;
    }
    ['tab-stacked', 'tab-frac', 'wc-prev', 'wc-next'].forEach(id => { $(id).disabled = true; });
    document.querySelector('.wc-stagenav').hidden = true; document.querySelector('.wc-hint').hidden = true;
    announceSection();
    return;
  }
  renderSteps();
  loadQuakes();
  const want = new URLSearchParams(location.search).get('stage');
  const i = want != null ? STAGES.findIndex(s => s.label === want) : -1;
  selectStage(i >= 0 ? i : 0);
}

// quakes are an extra: the page works without them
async function loadQuakes() {
  try {
    const q = await (await fetch('data/seismic/events.json')).json();
    QUAKES_ALL = q.rows.filter(r => r[11] && r[11][0] === String(WA).padStart(5, '0'))
      .map(r => ({ t: Date.parse(r[0]), mag: r[4], src: r[8], herr: r[9], stage: String(r[11][1]), rel: r[11][2],
                   mins: r[11][3], km: r[11][4], dz: r[11][5], fixed: !!r[6] || r[3] == null, matched: true }));
  } catch (e) { QUAKES_ALL = []; }
  // the pad's own accelerometer: triggers fired while one of this well's stages pumped
  try {
    const g = await (await fetch('data/seismic/gmmr.json')).json(), me = String(WA).padStart(5, '0'), seen = new Set();
    for (const r of Object.values(g)) for (const x of r.triggers || []) for (const [wa, st] of x.pumping || []) {
      const k = x.t + st;
      if (wa === me && !seen.has(k)) { seen.add(k); QUAKES_ALL.push({ t: Date.parse(x.t), stage: String(st), gm: x.pga_pct_g, vendor: r.vendor }); }
    }
  } catch (e) { /* no reports */ }
  applyQuakeFilter();
}
// the filter speaks to catalogue earthquakes; the pad's own accelerometer triggers always show
function applyQuakeFilter() {
  const SQ = window.StratumQuakes;
  QUAKES = QUAKES_ALL.filter(q => q.gm != null || !SQ || SQ.pass(q));
  document.querySelectorAll('#wc-steps button').forEach((b, i) => {
    const n = QUAKES.filter(q => q.stage === STAGES[i].label).length;
    b.classList.toggle('qk', n > 0);
    b.title = b.title.replace(/ · \d+ earthquakes? coincides?$/, '') + (n ? ` · ${n} earthquake${n > 1 ? 's' : ''} coincide` : '');
  });
  if (STAGES.length) { renderInfo(); drawChart(); }
}
addEventListener('stratum:quakefilter', () => { if (QUAKES_ALL.length) applyQuakeFilter(); });

function renderSteps() {
  const box = $('wc-steps');
  box.replaceChildren(...STAGES.map((s, i) => {
    const b = document.createElement('button');
    b.type = 'button'; b.textContent = s.label;
    b.title = `Stage ${s.label}` + (s.date ? ` · ${s.date} ${s.start.slice(0, 5)}` : '');
    b.onclick = () => selectStage(i);
    return b;
  }));
}

function selectStage(i, from) {
  if (i < 0 || i >= STAGES.length) return;
  sel = i;
  const st = STAGES[i];
  view = { t0: 0, t1: tMax(st) };
  hoverT = null;
  document.querySelectorAll('#wc-steps button').forEach((b, k) => {
    b.classList.toggle('on', k === i);
    b.setAttribute('aria-pressed', String(k === i));
  });
  const on = $('wc-steps').children[i];
  if (on) on.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  $('wc-prev').disabled = i === 0;
  $('wc-next').disabled = i === STAGES.length - 1;
  renderInfo(); renderLegend(); afterView(false);
  pushStacked();
  if (from !== 'fv') fvSel();
  const q = new URLSearchParams(location.search); q.set('stage', st.label);
  history.replaceState(history.state, '', '?' + q);
  announceSection();
}

function renderInfo() {
  const st = STAGES[sel];
  const bits = [`<b>Stage ${st.label}</b>`];
  if (st.date) bits.push(`${st.date} ${st.start.slice(0, 5)}`);
  bits.push(`${fmt(tMax(st) / 60)} min`);
  if (st.top_m != null) bits.push(`${fmt(st.top_m, 1)}${st.base_m != null && st.base_m !== st.top_m ? '–' + fmt(st.base_m, 1) : ''} m MD${st.placed ? ' (placed by number)' : ''}`);
  const qs = QUAKES.filter(q => q.stage === st.label);
  const eq = qs.filter(q => q.gm == null), gm = qs.filter(q => q.gm != null);
  if (eq.length) bits.push(`<span class="wc-qk">${eq.length} earthquake${eq.length > 1 ? 's' : ''} coincide (largest M${Math.max(...eq.map(q => q.mag || 0))})</span>`);
  if (gm.length) bits.push(`<span class="wc-qk">pad accelerometer triggered (${Math.max(...gm.map(q => q.gm))} %g)</span>`);
  const hid = QUAKES_ALL.filter(q => q.stage === st.label && q.gm == null).length - eq.length;
  if (hid > 0) bits.push(`${hid} earthquake${hid > 1 ? 's' : ''} hidden by the quake filter`);
  $('wc-stageinfo').innerHTML = bits.join(' · ');
}

// ---------- legend: hide, and isolate ----------
function saveHidden() {
  try { localStorage.setItem(HIDDEN_KEY, JSON.stringify([...hidden])); } catch (e) { /* private mode */ }
}
function renderLegend() {
  const st = STAGES[sel];
  $('wc-legend').replaceChildren(...st.channels.map(c => {
    const b = document.createElement('button');
    b.type = 'button';
    b.setAttribute('aria-pressed', String(!hidden.has(c.name)));
    b.title = (hidden.has(c.name) ? 'Show' : 'Hide') + ' this curve · double-click to show it alone';
    const i = document.createElement('i'); i.style.background = c.color;
    const unit = document.createElement('span'); unit.textContent = `${fmt(c.vmax, 2)} ${c.unit}`;
    b.append(i, c.name, unit);
    b.onclick = () => { hidden.has(c.name) ? hidden.delete(c.name) : hidden.add(c.name); curvesChanged(); };
    // Two clicks have already toggled this curve off and on again by the time
    // dblclick fires, so isolating works from whatever state it was in.
    b.ondblclick = () => {
      const others = st.channels.filter(x => x !== c);
      const alone = others.every(x => hidden.has(x.name)) && !hidden.has(c.name);
      others.forEach(x => alone ? hidden.delete(x.name) : hidden.add(x.name));
      hidden.delete(c.name);
      curvesChanged();
    };
    return b;
  }));
}
function curvesChanged() {
  saveHidden(); renderLegend(); drawChart();
  pushStacked();            // the stacked view dims the same curve, as beside the Lab
}

// ---------- stage chart ----------
function afterView(fromStacked) {
  const st = STAGES[sel];
  const full = view.t0 <= 0 && view.t1 >= tMax(st) - 1e-6;
  $('wc-zoomreset').hidden = full;
  drawChart();
  if (!fromStacked) postStacked({ type: 'stacked:view', seq: stackSeq, t0: view.t0, t1: view.t1 });
}
function clampView(t0, t1) {
  const st = STAGES[sel], max = tMax(st), min = Math.min(max, st.dsec * 8);
  let span = Math.max(min, Math.min(max, t1 - t0));
  t0 = Math.max(0, Math.min(max - span, t0));
  view = { t0, t1: t0 + span };
}
function timeTicks(span) {
  const steps = [10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 14400];
  const plotW = $('wc-canvas').clientWidth - GP.L - GP.R;
  return steps.find(s => span / s <= Math.max(2, plotW / 90)) || 28800;
}
function stamp(st, t, withSec) {
  if (st.clock0 != null) {
    const d = new Date(st.clock0 + t * 1000);
    return `${p2(d.getHours())}:${p2(d.getMinutes())}` + (withSec ? `:${p2(d.getSeconds())}` : '');
  }
  const m = Math.floor(t / 60), s = Math.round(t % 60);
  return `+${m}:${p2(s)}`;
}

function drawChart() {
  const cv = $('wc-canvas');
  if ($('pane-chart').hidden || !STAGES.length) return;
  const r = cv.getBoundingClientRect(), d = devicePixelRatio || 1;
  if (!r.width || !r.height) return;
  if (cv.width !== Math.round(r.width * d) || cv.height !== Math.round(r.height * d)) {
    cv.width = Math.round(r.width * d); cv.height = Math.round(r.height * d);
  }
  const ctx = cv.getContext('2d');
  ctx.setTransform(d, 0, 0, d, 0, 0);
  const Wd = r.width, H = r.height, { L, R, T, B } = GP, plotW = Wd - L - R, plotH = H - T - B;
  ctx.clearRect(0, 0, Wd, H);
  const st = STAGES[sel];
  const vis = st.channels.filter(c => !hidden.has(c.name));
  const X = t => L + (t - view.t0) / (view.t1 - view.t0) * plotW;
  const Y = (v, c) => T + (1 - v / c.hi) * plotH;

  // grid, and one row of axis labels per curve at each line, in its colour
  const fracs = vis.length > 5 ? [0, 1] : vis.length > 3 ? [0, 0.5, 1] : [0, 0.25, 0.5, 0.75, 1];
  ctx.font = '11px ui-monospace,Menlo,monospace'; ctx.textAlign = 'right';
  for (const f of fracs) {
    const y = T + (1 - f) * plotH;
    ctx.strokeStyle = f === 0 ? '#345260' : '#1b2f3b'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(L, Math.round(y) + .5); ctx.lineTo(L + plotW, Math.round(y) + .5); ctx.stroke();
    if (f === 0) continue;
    // the rows move as one block, so the top line's labels stay on the canvas
    // without landing on each other
    const dy0 = -((vis.length - 1) / 2) * 12 + 4, shift = Math.max(0, 12 - (y + dy0));
    vis.forEach((c, ci) => {
      const v = c.hi * f, txt = v >= 10 ? v.toFixed(0) : v >= 1 ? v.toFixed(1) : v.toFixed(2);
      ctx.fillStyle = c.color;
      ctx.fillText(txt, L - 6, y + dy0 + ci * 12 + shift);
    });
  }

  // time axis
  const step = timeTicks(view.t1 - view.t0);
  ctx.textAlign = 'center'; ctx.fillStyle = '#93adb9';
  const first = Math.ceil(view.t0 / step) * step;
  for (let t = first; t <= view.t1 + 1e-6; t += step) {
    const x = X(t);
    ctx.strokeStyle = '#1b2f3b';
    ctx.beginPath(); ctx.moveTo(Math.round(x) + .5, T); ctx.lineTo(Math.round(x) + .5, T + plotH); ctx.stroke();
    ctx.fillText(stamp(st, t, step < 60), x, T + plotH + 16);
  }
  ctx.textAlign = 'left'; ctx.fillStyle = '#7f97a4';
  ctx.fillText(st.clock0 != null ? `${st.date} · clock time` : 'elapsed (no clock on the chart)', L, H - 6);

  // curves
  ctx.save();
  ctx.beginPath(); ctx.rect(L, T - 1, plotW, plotH + 2); ctx.clip();
  const i0 = Math.max(0, Math.floor(view.t0 / st.dsec) - 1);
  for (const c of vis) {
    const i1 = Math.min(c.values.length - 1, Math.ceil(view.t1 / st.dsec) + 1);
    ctx.beginPath(); let pen = false;
    for (let i = i0; i <= i1; i++) {
      const v = c.values[i];
      if (!isFinite(v)) { pen = false; continue; }
      const x = X(i * st.dsec), y = Y(v, c);
      if (pen) ctx.lineTo(x, y); else { ctx.moveTo(x, y); pen = true; }
    }
    ctx.strokeStyle = c.color; ctx.lineWidth = 1.6; ctx.lineJoin = 'round'; ctx.stroke();
  }
  ctx.restore();

  // earthquakes that coincided with this stage, at the moment they happened
  if (st.utc0 != null) {
    ctx.save(); ctx.font = '11px ui-monospace,Menlo,monospace'; ctx.textAlign = 'left';
    QUAKES.filter(q => q.stage === st.label).forEach((q, k) => {
      const t = (q.t - st.utc0) / 1000;
      if (t < view.t0 || t > view.t1) return;
      const x = X(t);
      ctx.strokeStyle = '#ff5fa2'; ctx.lineWidth = 1.5; ctx.setLineDash([4, 3]);
      ctx.beginPath(); ctx.moveTo(Math.round(x) + .5, T); ctx.lineTo(Math.round(x) + .5, T + plotH); ctx.stroke();
      ctx.setLineDash([]); ctx.fillStyle = '#ff5fa2';
      ctx.beginPath(); ctx.arc(x, T + 6, 4 + Math.max(0, q.mag || 0) * 1.5, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = '#ffd6e7';
      const label = q.gm != null ? `ground motion at pad · ${q.gm} %g${q.gm >= 0.8 ? ' (over BCER threshold)' : ''}`
        : `M${q.mag} · ${q.km} km` + (q.src === 'bcsrc' ? (q.herr ? ` ±${(q.herr / 1000).toFixed(1)}` : '') : ' (catalogue, km-scale)');
      // near the right edge the label goes on the line's left
      const flip = x + 8 + ctx.measureText(label).width > L + plotW;
      ctx.textAlign = flip ? 'right' : 'left';
      ctx.fillText(label, flip ? x - 8 : x + 8, T + 12 + k * 13);
    });
    ctx.restore();
  }

  // hover: a rule and the reading of every shown curve at that sample
  if (hoverT != null && vis.length) {
    const i = Math.max(0, Math.min(st.n - 1, Math.round(hoverT / st.dsec))), t = i * st.dsec, x = X(t);
    ctx.strokeStyle = '#9fb7c4'; ctx.setLineDash([3, 3]);
    ctx.beginPath(); ctx.moveTo(Math.round(x) + .5, T); ctx.lineTo(Math.round(x) + .5, T + plotH); ctx.stroke();
    ctx.setLineDash([]);
    const rows = vis.map(c => ({ c, v: c.values[i] }));
    rows.forEach(({ c, v }) => {
      if (!isFinite(v)) return;
      ctx.beginPath(); ctx.arc(x, Y(v, c), 3.5, 0, Math.PI * 2);
      ctx.fillStyle = c.color; ctx.fill(); ctx.strokeStyle = '#0b1620'; ctx.lineWidth = 2; ctx.stroke();
    });
    const head = `${stamp(st, t, true)}  ·  +${Math.floor(t / 60)}:${p2(Math.round(t % 60))}`;
    ctx.font = '12px ui-monospace,Menlo,monospace';
    const lines = rows.map(({ c, v }) => `${c.name.padEnd(12)} ${isFinite(v) ? fmt(v, 2) : '–'} ${c.unit}`);
    const bw = Math.max(ctx.measureText(head).width, ...lines.map(s => ctx.measureText(s).width)) + 34;
    const bh = 22 + lines.length * 17;
    const bx = x + 14 + bw > L + plotW ? x - 14 - bw : x + 14, by = T + 8;
    ctx.fillStyle = 'rgba(16,39,51,.95)'; ctx.strokeStyle = '#5ccbb7'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.roundRect(bx, by, bw, bh, 8); ctx.fill(); ctx.stroke();
    ctx.textAlign = 'left'; ctx.fillStyle = '#e7f4fa'; ctx.fillText(head, bx + 10, by + 16);
    rows.forEach(({ c }, k) => {
      ctx.fillStyle = c.color; ctx.fillRect(bx + 10, by + 27 + k * 17, 10, 3);
      ctx.fillStyle = '#e7f4fa'; ctx.fillText(lines[k], bx + 26, by + 33 + k * 17);
    });
  }
  if (!vis.length) {
    ctx.fillStyle = '#93adb9'; ctx.textAlign = 'center'; ctx.font = '13px system-ui';
    ctx.fillText('Every curve is hidden — click a name above to show it.', L + plotW / 2, T + plotH / 2);
  }
}

const cv = $('wc-canvas');
const tAt = clientX => {
  const r = cv.getBoundingClientRect(), plotW = r.width - GP.L - GP.R;
  return view.t0 + (clientX - r.left - GP.L) / plotW * (view.t1 - view.t0);
};
cv.addEventListener('wheel', e => {
  if (!STAGES.length) return;
  e.preventDefault();
  const t = tAt(e.clientX), k = Math.exp(e.deltaY * 0.0015);
  clampView(t - (t - view.t0) * k, t + (view.t1 - t) * k);
  afterView(false);
}, { passive: false });
cv.addEventListener('pointerdown', e => {
  if (!STAGES.length) return;
  drag = { x: e.clientX, t0: view.t0, t1: view.t1 };
  cv.setPointerCapture(e.pointerId); cv.style.cursor = 'grabbing';
});
cv.addEventListener('pointermove', e => {
  if (!STAGES.length) return;
  if (drag) {
    const r = cv.getBoundingClientRect(), dt = (e.clientX - drag.x) / (r.width - GP.L - GP.R) * (drag.t1 - drag.t0);
    clampView(drag.t0 - dt, drag.t1 - dt); hoverT = null; afterView(false); return;
  }
  const t = tAt(e.clientX);
  hoverT = t >= view.t0 && t <= view.t1 ? t : null;
  drawChart();
});
const endDrag = () => { drag = null; cv.style.cursor = 'crosshair'; };
cv.addEventListener('pointerup', endDrag);
cv.addEventListener('pointercancel', endDrag);
cv.addEventListener('pointerleave', () => { hoverT = null; drawChart(); });
cv.addEventListener('dblclick', () => { if (STAGES.length) { view = { t0: 0, t1: tMax(STAGES[sel]) }; afterView(false); } });
$('wc-zoomreset').onclick = () => { view = { t0: 0, t1: tMax(STAGES[sel]) }; afterView(false); };
new ResizeObserver(drawChart).observe(document.querySelector('.wc-plot'));

// ---------- the Lab's views, embedded ----------
const frames = {};
// Controls that only mean something inside the Lab: the source-PDF page in
// Stacked, and FracView's stage editing, whose edits go back to the Lab.
const HIDE = { stacked: '#openpdf,#pglbl{display:none!important}',
               frac: '#adjust,#trim,#undo,#reset,#state{display:none!important}' };
function ensureFrame(kind) {
  if (frames[kind]) return;
  const f = document.createElement('iframe');
  f.title = kind === 'stacked' ? 'Stacked charts' : 'Sequential: the whole job, stage after stage';
  f.src = kind === 'stacked' ? 'lab/stacked.html' : 'lab/fracview.html';
  f.addEventListener('load', () => {
    try {
      const s = f.contentDocument.createElement('style');
      s.textContent = HIDE[kind]; f.contentDocument.head.append(s);
    } catch (e) { /* not same-origin: leave the controls */ }
  });
  $(kind === 'stacked' ? 'pane-stacked' : 'pane-frac').append(f);
  frames[kind] = f;
}
const win = kind => frames[kind] && frames[kind].contentWindow;

// Stacked: the Lab's "stacked:stage" for the selected stage. Every push bumps
// seq; the view echoes what it applied, and asks again (stacked:sync) when it
// is behind, so a push that landed mid-load is re-sent rather than lost.
let stackSeq = 0;
function postStacked(msg) { const w = win('stacked'); if (w) try { w.postMessage(msg, ORIGIN); } catch (e) { /* loading */ } }
function stackedPayload() {
  const st = STAGES[sel];
  if (!st) return { type: 'stacked:none', seq: stackSeq, id: '' };
  return {
    type: 'stacked:stage', seq: stackSeq, id: stageId(st), file: `WA ${WA}`, chart: st.label,
    title: `Stage ${st.label} · WA ${WA}`,
    sub: [st.date && `${st.date} ${st.start}`, `${fmt(tMax(st) / 60)} min`].filter(Boolean).join(' · '),
    n: st.n, dsec: st.dsec, tMax: tMax(st), t0: view.t0, t1: view.t1, clock0: st.clock0,
    page: null, pageCount: 0,
    channels: st.channels.map(c => ({ name: c.name, unit: c.unit, color: c.color, lo: 0, hi: c.hi,
      printed: false, dataLo: isFinite(c.dataLo) ? c.dataLo : null, dataHi: isFinite(c.vmax) ? c.vmax : null,
      vmax: Math.round(c.vmax * 100) / 100, off: hidden.has(c.name), values: c.values })),
  };
}
function pushStacked() { stackSeq++; postStacked(stackedPayload()); }

// FracView: the whole well at once, laid on the clock the way the Lab's
// fvLayout does it — a stage with no printed start is placed after the one
// before it and marked, a start that runs backwards is kept and reported as a
// jump, and the axis is ordered by time.
function fvLayout(stages) {
  const raw = stages.map(s => s.clock0 == null ? NaN : s.clock0);
  const dur = i => Math.max(60000, stages[i].n * stages[i].dsec * 1000);
  const invented = new Set(), why = {};
  if (!raw.some(isFinite)) {
    const starts = []; let t = Date.parse('2000-01-01T00:00:00');
    stages.forEach((_, i) => { starts.push(t); t += dur(i); invented.add(i); why[i] = 'placed'; });
    return { order: stages.map((_, i) => i), starts, synthetic: true, jumps: [], invented, why };
  }
  const starts = raw.slice(), first = raw.findIndex(isFinite);
  for (let i = first - 1; i >= 0; i--) { starts[i] = starts[i + 1] - dur(i); invented.add(i); why[i] = 'placed'; }
  for (let i = first + 1; i < stages.length; i++) {
    if (isFinite(starts[i])) continue;
    starts[i] = starts[i - 1] + dur(i - 1); invented.add(i); why[i] = 'placed';
  }
  const jumps = [];
  for (let i = 1; i < stages.length; i++) {
    if (invented.has(i) || invented.has(i - 1) || starts[i] >= starts[i - 1]) continue;
    jumps.push({ from: stages[i - 1].label, to: stages[i].label, tFrom: starts[i - 1], tTo: starts[i] });
  }
  const order = stages.map((_, i) => i).sort((x, y) => (starts[x] - starts[y]) || (x - y));
  const oStarts = order.map(i => starts[i]), oInv = new Set(), oWhy = {};
  order.forEach((i, k) => { if (invented.has(i)) { oInv.add(k); oWhy[k] = why[i]; } });
  for (let k = 1; k < oStarts.length; k++) {
    if (oStarts[k] > oStarts[k - 1]) continue;
    oStarts[k] = oStarts[k - 1] + dur(order[k - 1]); oInv.add(k); oWhy[k] = oWhy[k] || 'pushed';
  }
  return { order, starts: oStarts, synthetic: false, jumps, invented: oInv, why: oWhy };
}
function fvPayload() {
  const L = fvLayout(STAGES);
  return {
    type: 'fv:well', file: `WA ${WA}`, uwi: (W.well && W.well.uwi) || '', synthetic: L.synthetic, jumps: L.jumps,
    stages: L.order.map((i, k) => {
      const s = STAGES[i];
      return { key: s.label, label: s.label, date: s.date, made: L.invented.has(k) ? (L.why[k] || 'placed') : '',
               seq: i + 1, t0: L.starts[k], dsec: s.dsec, n: s.n,
               channels: s.channels.map(c => ({ name: c.name, unit: c.unit, values: c.values })) };
    }),
    edits: null,
  };
}
function fvSel() {
  const w = win('frac'), st = STAGES[sel];
  if (w && st) try { w.postMessage({ type: 'fv:sel', file: `WA ${WA}`, label: st.label }, ORIGIN); } catch (e) { /* loading */ }
}

addEventListener('message', e => {
  if (e.origin !== ORIGIN) return;
  const d = e.data;
  if (!d || typeof d !== 'object' || typeof d.type !== 'string' || !STAGES.length) return;
  if (e.source === win('stacked')) {
    if (d.type === 'stacked:ready' ||
        (d.type === 'stacked:sync' && (d.seq !== stackSeq || d.id !== stageId(STAGES[sel])))) {
      postStacked(stackedPayload());
    } else if (d.type === 'stacked:zoom' && isFinite(d.t0) && isFinite(d.t1)) {
      clampView(d.t0, d.t1); afterView(true);
    }
  } else if (e.source === win('frac')) {
    if (d.type === 'fv:ready') {
      try { win('frac').postMessage(fvPayload(), ORIGIN); } catch (err) { /* loading */ }
      fvSel();
    } else if (d.type === 'fv:select') {
      const i = STAGES.findIndex(s => s.label === String(d.label));
      if (i >= 0 && i !== sel) selectStage(i, 'fv');
    }
  }
});

// ---------- tabs, stage keys, header ----------
const TABS = [['tab-chart', 'pane-chart'], ['tab-stacked', 'pane-stacked'], ['tab-frac', 'pane-frac']];
function setTab(id) {
  TABS.forEach(([t, p]) => {
    const on = t === id;
    $(t).setAttribute('aria-selected', String(on)); $(t).tabIndex = on ? 0 : -1;
    $(p).hidden = !on;
  });
  if (id === 'tab-stacked') ensureFrame('stacked');
  if (id === 'tab-frac') ensureFrame('frac');
  if (id === 'tab-chart') drawChart();
  try { sessionStorage.setItem('stratum.wellTab', id); } catch (e) { /* private mode */ }
}
TABS.forEach(([t], k) => {
  $(t).onclick = () => setTab(t);
  $(t).onkeydown = e => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    e.preventDefault(); e.stopPropagation();
    const next = TABS[(k + (e.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length][0];
    if (!$(next).disabled) { setTab(next); $(next).focus(); }
  };
});
$('wc-prev').onclick = () => selectStage(sel - 1);
$('wc-next').onclick = () => selectStage(sel + 1);
addEventListener('keydown', e => {
  if (!STAGES.length || e.target.closest('[role=tablist]') || e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === 'ArrowLeft') { e.preventDefault(); selectStage(sel - 1); }
  else if (e.key === 'ArrowRight') { e.preventDefault(); selectStage(sel + 1); }
  else if (e.key === 'Home') { e.preventDefault(); selectStage(0); }
  else if (e.key === 'End') { e.preventDefault(); selectStage(STAGES.length - 1); }
});

// back: the browser's own history restores the pad or underground view with the
// camera and selection it had; only fall back when this page was opened cold
$('wc-back').onclick = () => {
  if (history.length > 1 && document.referrer && new URL(document.referrer, location.href).origin === location.origin) history.back();
  else location.href = W && W.pad && W.pad.id
    ? `pad.html?set=${encodeURIComponent(String(W.pad.id).replace(/-\d+$/, ''))}&pad=${encodeURIComponent(W.pad.id)}`
    : 'map.html';
};
// the well section window (wellsection.html, popped out): it follows the well
// and stage on screen here, and a stage clicked there selects it here. Messages
// to this page carry its id (ME) and are acknowledged, so the section can tell
// when its main window has gone.
const secChan = 'BroadcastChannel' in self ? new BroadcastChannel('stratum-section') : null;
const ME = Math.random().toString(36).slice(2);
function announceSection() {
  if (secChan) secChan.postMessage({ type: 'show', wa: WA, stage: STAGES[sel] ? STAGES[sel].label : null, from: ME, page: 'charts' });
}
$('wc-section').onclick = () => {
  const st = STAGES[sel];
  const w = window.open(`wellsection.html?wa=${encodeURIComponent(WA)}${st ? '&stage=' + encodeURIComponent(st.label) : ''}&owner=${ME}&page=charts`,
    'stratum-section', 'popup,width=1280,height=620');
  if (w) announceSection();
};
if (secChan) secChan.onmessage = e => {
  const m = e.data || {};
  if (m.type === 'hello') { secChan.postMessage({ type: 'claim', from: ME, page: 'charts' }); return; }
  if (m.type !== 'open-stage' || m.to !== ME || !m.wa) return;
  secChan.postMessage({ type: 'ack', id: m.id });
  const i = String(m.wa) === WA && m.label != null ? STAGES.findIndex(s => s.label === String(m.label)) : -1;
  if (i >= 0) selectStage(i);
  else if (String(m.wa) !== WA) location.href = `wellview.html?wa=${encodeURIComponent(m.wa)}${m.label ? '&stage=' + encodeURIComponent(m.label) : ''}`;
};

// the compare window: wells are handed over through localStorage, so the window
// can be reloaded or opened cold, and announced on a BroadcastChannel so one
// that is already open picks the well up straight away
const CMP_KEY = 'stratum.compare';
const cmpChan = 'BroadcastChannel' in self ? new BroadcastChannel('stratum-compare') : null;
const openCompare = () => window.open('compare.html', 'stratum-compare', 'width=1180,height=860');
$('wc-compare').onclick = () => { const w = openCompare(); if (w) w.focus(); };
$('wc-add').onclick = e => {
  let list = [];
  try { list = JSON.parse(localStorage.getItem(CMP_KEY) || '[]').map(String); } catch (err) { /* empty */ }
  if (!list.includes(String(WA))) list.push(String(WA));
  try { localStorage.setItem(CMP_KEY, JSON.stringify(list)); } catch (err) { /* private mode */ }
  if (cmpChan) cmpChan.postMessage({ type: 'add', wa: String(WA) });
  const w = openCompare(); if (w) w.focus();
  e.target.textContent = 'Added ✓';
  setTimeout(() => { e.target.textContent = 'Add to compare'; }, 1600);
};

let startTab = 'tab-chart';
try { startTab = sessionStorage.getItem('stratum.wellTab') || startTab; } catch (e) { /* private mode */ }
load().then(() => { if (STAGES.length) setTab(startTab); });
