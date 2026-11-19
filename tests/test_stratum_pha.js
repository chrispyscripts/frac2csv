// pha.js: a Photon well export (.pha) read in the browser for the map's drop
// zone. A made-up export only: two wells with surveys on one pad, a horizontal
// with none, and a well with no location.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict'), path = require('node:path');
const ctx = { Math, Number, String, Object, Array, Map, Set, JSON, isFinite, parseFloat, Error, RegExp };
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/public/pha.js'), 'utf8'), ctx);
const P = ctx.PHA;
const plain = o => JSON.parse(JSON.stringify(o));

const WELL = 'WELLID WELLNAME COMPANY LICENSE TRAJECTORY TD TVD KB GRD UTMZONE UTMX UTMY BottomUTMX BottomUTMY TopLat TopLng BotLat BotLng SPUDDATE SURFACE_UWI'.split(' ');
const head = [
  '# a test export', 'struct WELL {', ...WELL.map(f => '  ' + f), '}',
  'struct DIR_XYZ[N] {', '  TYPE', '  UNITS', '  X', '  Y', '  Z', '  INCL', '  AZIM', '}',
  'struct WELTOPS_MD[N] {', '  UNITS', '  FMNDEPTH', '  KEYNAME', '  SNAME', '  LNAME', '}',
  'struct STAGES[N] {', '  NUMBER', '  LABEL', '  TOP', '  BOT', '  TYPE', '  DATE', '}',
];
const well = v => 'WELL ' + WELL.map(f => (v[f] == null ? '""' : /\s/.test(String(v[f])) ? `"${v[f]}"` : v[f])).join(' ');
// on zone 13's central meridian (105 W): easting 500000
const text = [
  ...head,
  well({ WELLID: '100010100101W300', WELLNAME: 'TEST ONE HZ 1-1-1-1', COMPANY: 'Test Oil Ltd.', LICENSE: '0000101', TRAJECTORY: 'Horizontal',
         TD: 1500, TVD: 800, UTMZONE: 13, UTMX: 500000, UTMY: 5500000, SPUDDATE: '2021/05/04', SURFACE_UWI: '01-01-001-01W3' }),
  'DIR_XYZ 4', '0 m 0 0 0 0 0', '0 m 0 0 700 0 0', '0 m 0 100 790 90 0', '0 m 0 800 800 90 0',
  'WELTOPS_MD 2', 'F 2296.59 "FIRST TOP" FT "First Top"', 'M 795 SECOND SECOND "Second Top"',
  'STAGES 2', '2 2 1200 1210 FRAC 2021/06/02', '1 1 1400 1410 FRAC 2021/06/01',
  // its neighbour on the pad, 20 m east: a vertical
  well({ WELLID: '100010100101W302', WELLNAME: 'TEST TWO', LICENSE: '0000102', TRAJECTORY: 'Vertical', TD: 900, UTMZONE: 13, UTMX: 500020, UTMY: 5500000 }),
  'DIR_XYZ 2', '0 m 0 0 0 0 0', '0 m 0 0 900 0 0',
  // 5 km away, a horizontal with no survey: down to its TVD, out to its bottom hole
  well({ WELLID: '100020100101W300', WELLNAME: 'TEST THREE HZ', LICENSE: '099Z003', TRAJECTORY: 'Horizontal', TD: 2400, TVD: 900,
         UTMZONE: 13, UTMX: 505000, UTMY: 5500000, BottomUTMX: 505000, BottomUTMY: 5501200 }),
  // no location at all
  well({ WELLID: 'X', WELLNAME: 'NOWHERE', TD: 100 }),
].join('\r\n');

const parsed = P.parse(text);
assert.equal(parsed.wells.length, 4);
assert.deepEqual(plain(parsed.structs.STAGES), ['NUMBER', 'LABEL', 'TOP', 'BOT', 'TYPE', 'DATE']);
assert.equal(parsed.wells[0].WELLNAME, 'TEST ONE HZ 1-1-1-1', 'a quoted name is one word');
assert.equal(parsed.wells[0]._sec.DIR_XYZ.length, 4);
assert.throws(() => P.parse('WELL 1 2 3\n'), /not a Photon well export/);

const r = P.convert(parsed, { n: 7, name: 'test.pha' });
assert.deepEqual(plain(r.report), { wells: 4, placed: 3, surveyed: 2, estimated: 1, 'no location': 1, 'no depth': 0, 'with stages': 1, 'with tops': 1, pads: 2 });
const wells = r.pads.flatMap(p => p.wells), byLic = Object.fromEntries(wells.map(w => [w.well.licence, w]));
// a licence as the province writes it
assert.deepEqual(Object.keys(byLic).sort(), ['101', '102', '99Z003']);
const one = byLic['101'];
// on the central meridian: 105 W exactly
assert.ok(Math.abs(one.well.lon + 105) < 1e-9 && one.well.lat > 49.6 && one.well.lat < 49.7, `surface ${one.well.lat}, ${one.well.lon}`);
// MD by minimum curvature: 700 m down, a quarter circle of radius 90 m to horizontal (100 m north, 90 m deeper), then 700 m on
const t = one.trajectory;
assert.equal(t.md[1], 700);
// (the arc through two stations: its chord times (b/2)/sin(b/2), b the dogleg, here 90 degrees)
const chord = Math.hypot(100, 90), dogleg = Math.PI / 2;
assert.ok(Math.abs(t.md[2] - (700 + chord * (dogleg / 2) / Math.sin(dogleg / 2))) < 0.2, 'md ' + t.md[2]);
assert.ok(Math.abs(t.md[3] - (t.md[2] + 700)) < 0.1);
// north/east metres from the surface as build_viking.py works them out (from lat/lon at 111,320 m a degree: within 0.5 %)
assert.ok(Math.abs(t.ns[3] - 800) < 4 && Math.abs(t.ew[3]) < 0.5, 'true north on the central meridian: ' + t.ns[3]);
assert.equal(one.well.heel_md, t.md[2], 'the heel: where it runs flat, the build behind it');
assert.equal(one.well.uwi, '100/01-01-001-01W3/00');
assert.equal(one.well.year, 2021);
assert.equal(one.well.path_estimated, false);
// stages in order, as the export gives them; tops in metres
assert.deepEqual(plain(one.stages.map(s => [s.n, s.top_m, s.base_m, s.date])), [[1, 1400, 1410, '2021-06-01'], [2, 1200, 1210, '2021-06-02']]);
assert.deepEqual(plain(one.well.tops), [['First Top', 700], ['Second Top', 795]]);
assert.equal(one.depth_intervals.length, 2);
// one pad for the two 20 m apart, its id the lowest well's
const pad = r.pads.find(p => p.wells.length === 2);
assert.deepEqual(plain(pad.wells.map(w => w.well.wa).sort()), ['DR7-101', 'DR7-102']);
assert.equal(pad.id, 'drop-7-101');
assert.equal(pad.name, '01-01-001-01W3', 'a pad is named by its surface location');
// no survey: down to its TVD, then out to its bottom hole, and said to be an estimate
const three = byLic['99Z003'];
assert.equal(three.well.path_estimated, true);
assert.deepEqual(plain(three.trajectory.tvd), [0, 900, 900]);
assert.ok(Math.abs(three.trajectory.ns[2] - 1200) < 6 && Math.abs(three.trajectory.md[2] - 2100) < 0.5);
// what the map and the 3D view read
const mp = r.mapPads.find(p => p.id === 'drop-7-101');
assert.equal(mp.wells.length, 2);
assert.ok(mp.wells.every(w => w.path.length >= 2 && w.path[0].length === 2));
assert.equal(r.indexPads.find(p => p.id === 'drop-7-101').stages, 2);
assert.deepEqual(plain(r.wells.map(w => w.wa).sort()), ['DR7-101', 'DR7-102', 'DR7-99Z003']);
assert.ok(r.bounds[0][1] < r.bounds[1][1]);
// a licence, a UWI
assert.equal(P.licKey('099Z901'), '99Z901');
assert.equal(P.licKey('0000123'), '123');
assert.equal(P.uwiText('200A001B002C0300'), '200/A-001-B/002-C-03/00');
console.log('pha: ok');
