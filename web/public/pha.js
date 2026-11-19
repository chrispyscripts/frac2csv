// FracView — a Photon Systems ASCII well export (.pha) read in the browser.
//
// The export opens with its structs (struct WELL { WELLID ... }, struct
// DIR_XYZ[N] { TYPE UNITS X Y Z INCL AZIM }, ...), then one WELL line per
// wellbore, each followed by its sections ("DIR_XYZ 228" and that many rows).
// Here it becomes the files the Saskatchewan set is made of (scripts/
// build_sk.py write() and build_viking.py): pad files, well files, the map's
// pads and the 3D view's index, so a dropped export opens in every view.
//
// Nothing leaves the browser: drop.js runs this in a worker (pha-worker.js)
// and keeps what it makes in IndexedDB (drop-store.js).
//
//   PHA.parse(text)               -> {structs, wells}
//   PHA.convert(parsed, {n, name}) -> {pads, wells, mapPads, indexPads, report, bounds}
(function (root) {
'use strict';
const PAD_M = 60;                 // wells whose surface holes are this close share a pad (build_sk.PAD_M)
const FT = 0.3048;
const SOURCE = 'Photon export';

// ---------- reading ----------
// a line's words as Python's shlex.split reads them: quoted words whole
function words(line) {
  if (line.indexOf('"') < 0 && line.indexOf("'") < 0) { const t = line.trim(); return t ? t.split(/\s+/) : []; }
  const out = [], re = /"((?:[^"\\]|\\.)*)"|'([^']*)'|(\S+)/g;
  let m;
  while ((m = re.exec(line))) out.push(m[1] != null ? m[1].replace(/\\(.)/g, '$1') : m[2] != null ? m[2] : m[3]);
  return out;
}

function parse(text, progress) {
  const lines = text.replace(/\r/g, '').split('\n');
  const structs = {};
  let i = 0;
  for (; i < lines.length; i++) {
    const m = /^struct\s+(\w+)(\[\s*N\s*\])?\s*\{/.exec(lines[i]);
    if (m) {
      const fields = [];
      for (i++; i < lines.length && !lines[i].startsWith('}'); i++) if (lines[i].trim()) fields.push(lines[i].trim());
      structs[m[1]] = fields;
    } else if (lines[i].startsWith('WELL ')) break;
  }
  if (!structs.WELL) throw new Error('This is not a Photon well export: it has no "struct WELL".');
  const wells = [];
  let cur = null;
  const every = Math.max(1, Math.floor(lines.length / 50));
  for (; i < lines.length; i++) {
    const line = lines[i];
    if (progress && i % every === 0) progress(i / lines.length);
    if (line.startsWith('WELL ')) {
      const v = words(line.slice(5));
      cur = { _sec: {} };
      structs.WELL.forEach((f, j) => { cur[f] = v[j]; });
      wells.push(cur);
      continue;
    }
    const m = /^([A-Z_]+)\s+(\d+)\s*$/.exec(line);
    if (m && structs[m[1]] && cur) {
      const n = +m[2];
      cur._sec[m[1]] = lines.slice(i + 1, i + 1 + n).map(words);
      i += n;
    }
  }
  return { structs, wells };
}

// ---------- numbers, names ----------
const num = s => {
  if (s == null) return null;
  const v = typeof s === 'number' ? s : parseFloat(s.indexOf(',') < 0 ? s : s.replace(/,/g, ''));
  return isFinite(v) ? v : null;
};
const r1 = v => Math.round(v * 10) / 10, r2 = v => Math.round(v * 100) / 100, r6 = v => Math.round(v * 1e6) / 1e6;
// a licence as the province writes it: 0999901 -> 999901, 099Z901 -> 99Z901
function licKey(lic) {
  const s = String(lic || '').replace(/\s/g, '').toUpperCase();
  if (/^\d+$/.test(s)) return s.replace(/^0+/, '') || '0';
  const m = /^0*(\d+)([A-Z])(\d+)$/.exec(s);
  return m ? String(+m[1]).padStart(2, '0') + m[2] + m[3] : s;
}
const uwiKey = u => String(u || '').toUpperCase().replace(/[^0-9A-Z]/g, '');
// 101011100109W400 -> 101/01-11-001-09W4/00 (DLS); 200A001B002C0300 -> 200/A-001-B/002-C-03/00 (NTS)
function uwiText(u) {
  u = uwiKey(u);
  if (/^\d{12}W\d{3}$/.test(u))
    return `${u.slice(0, 3)}/${u.slice(3, 5)}-${u.slice(5, 7)}-${u.slice(7, 10)}-${u.slice(10, 12)}${u.slice(12, 14)}/${u.slice(14, 16)}`;
  const m = /^(\d{3})([A-D])(\d{3})([A-L])(\d{3})([A-P])(\d{2})(\d{2})$/.exec(u);
  return m ? `${m[1]}/${m[2]}-${m[3]}-${m[4]}/${m[5]}-${m[6]}-${m[7]}/${m[8]}` : u;
}
const yearOf = (...ts) => { for (const t of ts) { const m = /\b(19\d\d|20\d\d)\b/.exec(String(t || '')); if (m) return +m[1]; } return null; };
const unitScale = u => /^f/i.test(String(u || '')) ? FT : 1;      // m, M, metres: 1; f, ft, feet: 0.3048

// NAD83 UTM -> lat/lon (GRS80; Snyder's series: well under a centimetre here)
const A = 6378137.0, F = 1 / 298.257222101, K0 = 0.9996;
function utmToLatLon(e, n, zone) {
  const e2 = F * (2 - F), ep2 = e2 / (1 - e2);
  const mu = n / K0 / (A * (1 - e2 / 4 - 3 * e2 * e2 / 64 - 5 * e2 ** 3 / 256));
  const e1 = (1 - Math.sqrt(1 - e2)) / (1 + Math.sqrt(1 - e2));
  const p1 = mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * Math.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * Math.sin(4 * mu)
    + (151 * e1 ** 3 / 96) * Math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * Math.sin(8 * mu);
  const s = Math.sin(p1), c = Math.cos(p1), t = Math.tan(p1);
  const c1 = ep2 * c * c, t1 = t * t, n1 = A / Math.sqrt(1 - e2 * s * s), r1 = A * (1 - e2) / (1 - e2 * s * s) ** 1.5;
  const d = (e - 500000) / (n1 * K0);
  const lat = p1 - (n1 * t / r1) * (d * d / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * ep2) * d ** 4 / 24
    + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * ep2 - 3 * c1 * c1) * d ** 6 / 720);
  const lon = (d - (1 + 2 * t1 + c1) * d ** 3 / 6 + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * ep2 + 24 * t1 * t1) * d ** 5 / 120) / c;
  return [lat * 180 / Math.PI, (zone - 1) * 6 - 180 + 3 + lon * 180 / Math.PI];
}

// measured depth between two stations [x, y, z, inc, az]: the minimum-curvature
// arc through them, from the chord and the dogleg
function arc(a, b) {
  const chord = Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
  const i1 = a[3] * Math.PI / 180, i2 = b[3] * Math.PI / 180, da = (b[4] - a[4]) * Math.PI / 180;
  const cb = Math.cos(i2 - i1) - Math.sin(i1) * Math.sin(i2) * (1 - Math.cos(da));
  const beta = Math.acos(Math.max(-1, Math.min(1, cb)));
  return beta < 1e-7 ? chord : chord * (beta / 2) / Math.sin(beta / 2);
}

// ---------- a well ----------
// where its surface is, and how to turn east/north metres from it into lat/lon
function placeOf(w) {
  const zone = num(w.UTMZONE), e0 = num(w.UTMX), n0 = num(w.UTMY);
  if (zone && e0 != null && n0 != null && zone >= 1 && zone <= 60) {
    const [lat0, lon0] = utmToLatLon(e0, n0, zone);
    return { lat0, lon0, at: (x, y) => utmToLatLon(e0 + x, n0 + y, zone), utm: { zone, e0, n0 } };
  }
  const lat0 = num(w.TopLat), lon0 = num(w.TopLng);
  if (lat0 == null || lon0 == null || (lat0 === 0 && lon0 === 0)) return null;
  const k = Math.cos(lat0 * Math.PI / 180);
  return { lat0, lon0, at: (x, y) => [lat0 + y / 111320, lon0 + x / (111320 * k)], utm: null };
}

// stations [x, y, z, inc, az] -> the trajectory: MD by minimum curvature from
// the first station's depth (straight between an estimate's made-up stations),
// true north/east metres from the surface
function trajectory(st, pl, straight) {
  const k = Math.cos(pl.lat0 * Math.PI / 180);
  const t = { md: [], inc: [], az: [], tvd: [], ns: [], ew: [], lat: [], lon: [] };
  let md = st[0][2];
  st.forEach((s, j) => {
    if (j) md += straight ? Math.hypot(s[0] - st[j - 1][0], s[1] - st[j - 1][1], s[2] - st[j - 1][2]) : arc(st[j - 1], s);
    const [la, lo] = pl.at(s[0], s[1]);
    t.md.push(r1(md)); t.tvd.push(r1(s[2])); t.inc.push(r2(s[3])); t.az.push(r2(((s[4] % 360) + 360) % 360));
    t.ns.push(r1((la - pl.lat0) * 111320)); t.ew.push(r1((lo - pl.lon0) * 111320 * k));
    t.lat.push(r6(la)); t.lon.push(r6(lo));
  });
  return t;
}

// the survey, where the export has one
function surveyed(w, pl) {
  const st = [];
  for (const r of w._sec.DIR_XYZ || []) {
    if (r.length < 7) continue;
    const f = unitScale(r[1]);
    const x = num(r[2]), y = num(r[3]), z = num(r[4]), inc = num(r[5]), az = num(r[6]);
    if (x == null || y == null || z == null || inc == null || az == null) continue;
    st.push([x * f, y * f, z * f, inc, az]);
  }
  return st.length >= 2 ? st : null;
}

// no survey: a path from the surface and the bottom hole, drawn as the well's
// kind says (a horizontal down to its TVD, then out to the bottom hole; any
// other well straight from the surface to it) -- an estimate, and marked one
function estimated(w, pl) {
  let td = num(w.TD), tvd = num(w.TVD);
  if (td == null && tvd == null) return null;
  let dx = 0, dy = 0;
  const be = num(w.BottomUTMX), bn = num(w.BottomUTMY);
  if (pl.utm && be != null && bn != null && (be || bn)) { dx = be - pl.utm.e0; dy = bn - pl.utm.n0; }
  else {
    const bl = num(w.BotLat), bg = num(w.BotLng);
    if (bl != null && bg != null && (bl || bg)) { dy = (bl - pl.lat0) * 111320; dx = (bg - pl.lon0) * 111320 * Math.cos(pl.lat0 * Math.PI / 180); }
  }
  const h = Math.hypot(dx, dy);
  if (tvd == null) tvd = h < 25 ? td : null;
  if (td == null) td = tvd;
  if (tvd == null) return null;
  const az = (Math.atan2(dx, dy) * 180 / Math.PI + 360) % 360;
  if (h < 25) return [[0, 0, 0, 0, 0], [0, 0, tvd, 0, 0]];
  if (/horiz/i.test(w.TRAJECTORY || '') || td - tvd > 0.5 * h)
    return [[0, 0, 0, 0, 0], [0, 0, tvd, 0, az], [dx, dy, tvd, 90, az]];
  const inc = Math.atan2(h, tvd) * 180 / Math.PI;
  return [[0, 0, 0, inc, az], [dx, dy, tvd, inc, az]];
}

function heelOf(t) {
  for (let j = 1; j < t.md.length; j++) {
    const dm = t.md[j] - t.md[j - 1];
    if (dm > 0 && (t.tvd[j] - t.tvd[j - 1]) / dm < Math.cos(80 * Math.PI / 180)) return t.md[j - 1];
  }
  return null;
}

function stagesOf(w) {
  const out = [];
  for (const r of w._sec.STAGES || []) {                 // NUMBER LABEL TOP BOT TYPE DATE
    const n = num(r[0]), top = num(r[2]), bot = num(r[3]);
    if (n == null && top == null) continue;
    const s = { n: n != null ? Math.round(n) : out.length + 1, label: r[1] || String(n != null ? Math.round(n) : out.length + 1), source: SOURCE };
    if (top != null) s.top_m = top;
    if (bot != null) s.base_m = bot; else if (top != null) s.base_m = top;
    if (r[5]) s.date = String(r[5]).replace(/\//g, '-');
    if (r[4]) s.type = r[4];
    out.push(s);
  }
  return out.sort((a, b) => a.n - b.n);
}

function intervalsOf(w, stages) {
  const rows = stages.filter(s => s.top_m != null).map(s => ({ n: s.n, top_m: s.top_m, base_m: s.base_m, completion_type: s.type || 'FRACTURED', source: SOURCE, ...(s.date ? { date: s.date.replace(/-/g, '') } : {}) }));
  if (rows.length) return rows;
  for (const r of w._sec.FRACTURES || []) {             // NUMBER TOP BOT TYPE DATE
    const top = num(r[1]), bot = num(r[2]);
    if (top == null) continue;
    rows.push({ n: num(r[0]) != null ? Math.round(num(r[0])) : rows.length + 1, top_m: top, base_m: bot != null ? bot : top,
                completion_type: r[3] || 'FRACTURED', source: SOURCE, ...(r[4] ? { date: String(r[4]).replace(/\D/g, '') } : {}) });
  }
  return rows;
}

function topsOf(w) {
  const out = [];
  for (const r of w._sec.WELTOPS_MD || []) {              // UNITS FMNDEPTH KEYNAME SNAME LNAME
    const d = num(r[1]);
    if (d == null) continue;
    out.push([r[4] || r[3] || r[2] || '?', +(d * unitScale(r[0])).toFixed(2)]);
  }
  return out.sort((a, b) => a[1] - b[1]);
}

// ---------- the set ----------
function convert(parsed, opts = {}) {
  const n = opts.n || 1;
  const report = { wells: parsed.wells.length, placed: 0, surveyed: 0, estimated: 0, 'no location': 0, 'no depth': 0, 'with stages': 0, 'with tops': 0 };
  const wells = [];
  const seenLic = new Set();
  parsed.wells.forEach((p, i) => {
    const pl = placeOf(p);
    if (!pl) { report['no location']++; return; }
    let st = surveyed(p, pl), est = false;
    if (st) report.surveyed++;
    else { st = estimated(p, pl); est = !!st; if (!st) { report['no depth']++; return; } report.estimated++; }
    report.placed++;
    const t = trajectory(st, pl, est);
    const lic = licKey(p.LICENSE), uk = uwiKey(p.WELLID);
    let key = (lic && lic !== '0' ? lic : '') || uk || 'W' + (i + 1);
    if (seenLic.has(key)) key = (uk && !seenLic.has(uk)) ? uk : key + '-' + (i + 1);     // a second leg under one licence
    seenLic.add(key);
    const stages = stagesOf(p), tops = topsOf(p), heel = heelOf(t);
    if (stages.length) report['with stages']++;
    if (tops.length) report['with tops']++;
    const td = Math.max(num(p.TD) || 0, t.md[t.md.length - 1]);
    wells.push({
      key, lat: +pl.lat0.toFixed(6), lon: +pl.lon0.toFixed(6), trajectory: t, stages, depth_intervals: intervalsOf(p, stages),
      well: {
        name: p.WELLNAME || key, licence: lic && lic !== '0' ? lic : '', uwi: uwiText(p.WELLID), prov: p.PROVINCE || '',
        operator: p.COMPANY || '', formation: p.FORMATION || '', status: p.STATUS || '', fluid: p.WELLFLUID || '',
        pool: p.POOL || '', field: p.FIELD || '', spud: p.SPUDDATE || '', rig_release: p.RRDATE || '',
        cum_oil_m3: num(p.CUM_OIL_VOL), cum_gas_e3m3: num(p.CUM_GAS_VOL), cum_water_m3: num(p.CUM_WAT_VOL), cum_hours: num(p.CUM_PRD_HOUR),
        drilling_company: p.DRILLINGCOMPANY || '', tops, curves: 0, logs: 0, vertical: !/horiz|direct|devia/i.test(p.TRAJECTORY || '') && t.inc.every(v => v < 10),
        lat: +pl.lat0.toFixed(6), lon: +pl.lon0.toFixed(6), td_m: +td.toFixed(1), tvd_m: +Math.max(...t.tvd).toFixed(1),
        lateral_m: heel != null ? Math.round(t.md[t.md.length - 1] - heel) : 0, heel_md: heel != null ? +heel.toFixed(1) : null,
        year: yearOf(p.SPUDDATE, p.RRDATE), elev_m: num(p.KB), ground_m: num(p.GRD),
        surface_loc: String(p.SURFACE_UWI || '').trim(), placed_by: "the export's surface coordinates" + (pl.utm ? ' (NAD83 UTM ' + pl.utm.zone + ')' : ' (lat/lon)'),
        path_from: est ? "estimated from the export's surface and bottom-hole locations and its TD and TVD" : 'survey (Photon export)',
        path_estimated: est, stages_filed: stages.length, dropped: opts.name || 'a dropped export',
      },
    });
  });

  // pads: surface holes within PAD_M of each other (build_sk.write)
  wells.sort((a, b) => a.lat - b.lat || a.lon - b.lon);
  const pads = [], cells = new Map();
  const cell = (lat, lon) => [Math.floor(lat * 111320 / PAD_M), Math.floor(lon * 111320 * 0.62 / PAD_M)];
  for (const w of wells) {
    const k = Math.cos(w.lat * Math.PI / 180), [cy, cx] = cell(w.lat, w.lon);
    let best = null;
    for (let dy = -1; dy <= 1; dy++) for (let dx = -2; dx <= 2; dx++) for (const p of cells.get(`${cy + dy},${cx + dx}`) || [])
      if (Math.hypot((p.lat - w.lat) * 111320, (p.lon - w.lon) * 111320 * k) <= PAD_M && (!best || p.i < best.i)) best = p;
    if (best) best.wells.push(w);
    else { const p = { lat: w.lat, lon: w.lon, wells: [w], i: pads.length }; pads.push(p); const c = `${cy},${cx}`; if (!cells.has(c)) cells.set(c, []); cells.get(c).push(p); }
  }
  const seen = new Map();
  for (const p of pads) for (const w of p.wells) {
    const base = 'DR' + n + '-' + w.key.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 24);
    seen.set(base, (seen.get(base) || 0) + 1);
    w.well.wa = seen.get(base) === 1 ? base : `${base}-${seen.get(base)}`;
  }
  pads.sort((a, b) => (a.wells.map(w => w.well.wa).sort()[0] < b.wells.map(w => w.well.wa).sort()[0] ? -1 : 1));
  const padFiles = [], wellFiles = [], mapPads = [], indexPads = [];
  let minLon = 180, minLat = 90, maxLon = -180, maxLat = -90;
  for (const p of pads) {
    const first = p.wells.map(w => w.well.wa).sort()[0];
    p.id = 'drop-' + first.slice(2).toLowerCase();
    p.lat = p.wells.reduce((s, w) => s + w.lat, 0) / p.wells.length;
    p.lon = p.wells.reduce((s, w) => s + w.lon, 0) / p.wells.length;
    p.name = p.wells[0].well.surface_loc || p.wells[0].well.name || p.id;
    padFiles.push({ id: p.id, name: p.name, lat: +p.lat.toFixed(6), lon: +p.lon.toFixed(6), set: 'drop',
                    wells: p.wells.map(w => ({ well: w.well, trajectory: w.trajectory, stages: w.stages, depth_intervals: w.depth_intervals, logs: null })) });
    for (const w of p.wells) wellFiles.push({ wa: w.well.wa, file: { well: w.well, pad: { id: p.id, name: p.name }, stages: [], units: {}, log_notes: [] } });
    const planPath = t => { const m = t.md.length, idx = [...new Set([0, m - 1, ...Array.from({ length: 24 }, (_, i) => Math.floor(i * (m - 1) / 23))])].sort((a, b) => a - b); return idx.map(i => [t.lon[i], t.lat[i]]); };
    mapPads.push({ id: p.id, name: p.name, lat: +p.lat.toFixed(6), lon: +p.lon.toFixed(6), wells: p.wells.map(w => ({
      wa: w.well.wa, name: w.well.name, uwi: w.well.uwi, td: w.well.td_m, tvd: w.well.tvd_m, lateral: w.well.lateral_m,
      lat: w.lat, lon: w.lon, stations: w.trajectory.md.length, path: planPath(w.trajectory), stages: w.stages.length, ports: 0,
      logs: 0, ws: 0, depth_intervals: w.depth_intervals.length, summaries: 0, file: null, est: w.well.path_estimated ? 1 : 0 })) });
    const years = p.wells.map(w => w.well.year).filter(Boolean);
    const commonest = f => { const c = new Map(); for (const w of p.wells) c.set(f(w), (c.get(f(w)) || 0) + 1); return [...c].sort((a, b) => b[1] - a[1])[0][0]; };
    indexPads.push({ id: p.id, name: p.name, set: 'drop', lat: +p.lat.toFixed(6), lon: +p.lon.toFixed(6), wells: p.wells.length,
                     field: commonest(w => w.well.pool || w.well.field || ''), operator: commonest(w => w.well.operator),
                     years: years.length ? [Math.min(...years), Math.max(...years)] : null, curves: 0, logs: 0,
                     stages: p.wells.reduce((s, w) => s + w.stages.length, 0), dropped: true });
    for (const w of p.wells) for (let j = 0; j < w.trajectory.lat.length; j++) {
      const la = w.trajectory.lat[j], lo = w.trajectory.lon[j];
      if (lo < minLon) minLon = lo; if (lo > maxLon) maxLon = lo; if (la < minLat) minLat = la; if (la > maxLat) maxLat = la;
    }
  }
  report.pads = pads.length;
  return { pads: padFiles, wells: wellFiles, mapPads, indexPads, report, bounds: pads.length ? [[minLon, minLat], [maxLon, maxLat]] : null };
}

const PHA = { parse, convert, words, licKey, uwiText, utmToLatLon, arc };
root.PHA = PHA;
})(typeof globalThis !== 'undefined' ? globalThis : self);
