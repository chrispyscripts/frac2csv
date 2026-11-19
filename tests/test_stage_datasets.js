// stage-datasets-core.js: the datasets stacked under a stage chart (stages.html).
// Which a well has, where its stage is, the window drawn around it, the default
// stack and what a card keeps. Synthetic wells only; the comments are made up
// here (no data file carries them yet).
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict'), path = require('node:path');
const read = f => fs.readFileSync(path.join(__dirname, '../web/public', f), 'utf8');

// logs.js, for the Saskatchewan wells' mud logs (a synthetic index)
const index = {
  bin_m: 2, rocks: [['sandstone', 'Sandstone'], ['shale', 'Shale']],
  types: { 'c:rop': { t: 'Drill time (rate of penetration)', u: 'min/m', wells: 3 }, 'c:total_gas': { t: 'Total gas', u: 'units', wells: 2 } },
  scales: { gamma: { lo: 20, p50: 70, hi: 140 }, 'c:rop': { lo: 0.5, p50: 2, hi: 12 } }, pads: [],
};
const win = {
  document: { documentElement: { dataset: { theme: 'light' } }, createElement: () => ({ append() {}, setAttribute() {}, style: {} }), getElementById: () => ({}), head: null },
  localStorage: { getItem: () => null, setItem() {} },
  fetch: async u => ({ ok: u === 'data/sk/index.json', json: async () => index }),
  addEventListener() {}, dispatchEvent() {}, CustomEvent: class {},
  Promise, Math, Number, String, Object, Array, Map, Set, JSON, isFinite, encodeURIComponent,
};
win.window = win;
vm.createContext(win);
vm.runInContext(read('logs.js'), win);
vm.runInContext(read('stage-datasets-core.js'), win);
const S = win.StratumLogs, C = win.StageDatasetsCore;
const plain = o => JSON.parse(JSON.stringify(o));
const range = (a, b, step) => { const out = []; for (let x = a; x <= b + 1e-9; x += step) out.push(+x.toFixed(3)); return out; };

(async () => {
  await S.skReady;

  // ---------- a BC well: LAS gamma and ROP along the whole hole, two stages ----------
  const md = range(600, 4200, 2.4);
  const bc = {
    well: { wa: '28751', name: 'TEST HZ', heel_md: 2300, td_m: 4267 },
    stages: [{ label: '28', top_m: 2840.2, base_m: 2840.3, series: {} }, { label: '29', top_m: 2797.7, base_m: 2797.8 }],
    depth_intervals: [{ n: 30, top_m: 2739, base_m: 2739.1 }],
    logs: [
      { name: 'Gamma ray', mnemonic: 'GR', unit: 'aapi', md, v: md.map(m => (m > 2300 ? 100 + 20 * Math.sin(m / 30) : 60)) },
      { name: 'Rate of penetration', mnemonic: 'ROP', unit: 'm/hr', md, v: md.map((m, i) => (i === 10 ? -999.25 : i === 11 ? -999250 : 40)) },
    ],
  };
  assert.equal(C.needsGammaFile('28751', bc, null, S), false, 'its own gamma reaches the stages: no gamma file');
  const m = C.buildModel('28751', bc, null, null, S);
  assert.deepEqual(plain([...m.sets.keys()]), ['gamma', 'las:Rate of penetration']);
  const g = m.sets.get('gamma');
  assert.equal(g.u, 'API'); assert.equal(g.src, 'LAS GR'); assert.equal(g.palette, true);
  assert.deepEqual(plain(C.robustIn(g, [2300, 4267])), plain(g.scale), 'the scale is the lateral’s, the same for every stage');
  assert.ok(g.scale.lo >= 70 && g.scale.hi <= 130, 'the vertical hole’s low readings do not flatten the lateral');
  assert.equal(g.scaleAll.lo <= 60, true, 'the whole well keeps a scale of its own');
  const rop = m.sets.get('las:Rate of penetration');
  assert.ok(Number.isNaN(rop.v[10]) && Number.isNaN(rop.v[11]), 'LAS -999.25 (and a scaled copy) is no reading');
  assert.equal(rop.u, 'm/hr');

  // where the stages are: the well file's stages, then its depth intervals
  assert.deepEqual(plain(C.depthIn(m.lists, '28')), { top: 2840.2, base: 2840.3 });
  assert.deepEqual(plain(C.depthIn(m.lists, '30')), { top: 2739, base: 2739.1 }, 'a stage only the depth intervals place');
  assert.equal(C.depthIn(m.lists, '99'), null);

  // the window: the stage ±75 m, the lateral, the whole well
  let W = C.windowFor('stage', m, '28', ['gamma']);
  assert.deepEqual([+W.lo.toFixed(1), +W.hi.toFixed(1), W.win], [2765.2, 2915.3, 'stage']);
  W = C.windowFor('lateral', m, '28', ['gamma']);
  assert.deepEqual([W.lo, W.hi, W.win], [2300, 4267, 'lateral']);
  W = C.windowFor('well', m, '28', ['gamma']);
  assert.deepEqual([W.lo, W.hi, W.win], [600, 4267, 'well']);
  W = C.windowFor('stage', m, '99', ['gamma']);
  assert.equal(W.win, 'lateral'); assert.match(W.note, /not on file/, 'a stage with no depth: the lateral, and why');

  // the picker: what the well has, the usual curves it lacks (disabled, with why), comments
  let cat = C.catalogue(m, ['gamma']);
  const opt = k => cat.find(o => o.kind === k);
  assert.equal(opt('gamma').added, true); assert.equal(opt('gamma').ok, false); assert.equal(opt('gamma').note, 'In this stack');
  assert.equal(opt('las:Rate of penetration').ok, true);
  assert.match(opt('las:Rate of penetration').note, /^600–4,200 m MD · LAS ROP$/);
  assert.equal(opt('las:Neutron porosity').ok, false); assert.equal(opt('las:Neutron porosity').note, C.NO_FILE);
  assert.equal(opt('comments').ok, false); assert.equal(opt('comments').note, 'No comments on file for this well');
  assert.deepEqual(plain(cat.map(o => o.group)).filter((v, i, a) => a.indexOf(v) === i), ['log', 'notes']);

  // a reading at a depth: the nearest sample, none across a gap
  assert.equal(C.valueAt(rop, 624.2).v, null, 'the -999.25 sample');
  assert.equal(C.valueAt(rop, 700).v, 40);
  assert.equal(C.valueAt(rop, 5000), null, 'off the run');

  // ---------- a BC well whose own gamma stops above the stages: FracView's gamma ----------
  const wl = range(0, 2200, 2.4);
  const bc2 = { well: { heel_md: 2340, td_m: 4169 }, stages: [{ label: '20', top_m: 3391.4, base_m: 3391.5 }],
    logs: [{ name: 'Gamma ray', mnemonic: 'GR', unit: 'GAPI', md: wl, v: wl.map(() => 80) },
           { name: 'Neutron porosity', mnemonic: 'NPSS', unit: 'PERC', md: wl, v: wl.map(() => 20) },
           { name: 'Neutron porosity', mnemonic: 'NPDL', unit: 'PERC', md: wl, v: wl.map(() => 5) }] };
  assert.equal(C.needsGammaFile('28744', bc2, null, S), true);
  const gj = { bin_m: 5, unit: 'API', scale: { lo: 70, p50: 114, hi: 180 },
               wells: { '28744': { md0: 0, v: Array.from({ length: 831 }, () => 110) }, '09999': { md0: 0, v: [90, 91], estimated: true } } };
  const m2 = C.buildModel('28744', bc2, null, gj, S);
  assert.match(m2.sets.get('gamma').src, /FracView gamma/);
  assert.equal(m2.sets.get('gamma').hi, 4152.5, 'bins read at their middles');
  assert.equal(m2.sets.get('las:Neutron porosity').src, 'LAS NPSS', 'one dataset per curve name: the first');
  assert.equal(m2.sets.get('las:Neutron porosity').u, '%');
  const np = C.catalogue(m2).find(o => o.kind === 'las:Neutron porosity');
  assert.match(np.note, /ends above the stages/);
  // a well with no gamma of its own: the gamma file, by its zero-padded number, estimated
  const m3 = C.buildModel('9999', { well: {}, stages: [] }, null, gj, S);
  assert.equal(m3.sets.get('gamma').est, true);
  assert.equal(m3.sets.get('gamma').src, 'estimated from offset logs');

  // ---------- a Saskatchewan well: its stages and mud log on its pad row ----------
  const row = { well: { wa: 'SK1', heel_md: 800, td_m: 1400 },
    stages: [{ n: 1, label: '1', top_m: 1300, base_m: 1300 }, { n: 2, label: '2', top_m: 1250, base_m: 1252 }],
    logs: { md0: 1000, bin: 2, src: [{ log: 'printout' }], types: { rock: [0, 0, 1, null, 1], por: [9, 12, null, 3, 24], show: [null, 1, 4, 0, null],
      gamma: [60, 90, 120, 30, 140], 'c:rop': [1, 2, 3, 4, 5], 'c:total_gas': [null, null, null, null, null] } } };
  const file = { well: { wa: 'SK1', heel_md: 800, td_m: 1400 }, stages: [] };
  assert.equal(C.needsGammaFile('SK1', file, row, S), false);
  const sk = C.buildModel('SK1', file, row, null, S);
  assert.deepEqual(plain([...sk.sets.keys()]), ['gamma', 'rock', 'por', 'show', 'c:rop']);
  assert.equal(sk.sets.get('rock').style, 'cat'); assert.equal(sk.sets.get('show').style, 'cat'); assert.equal(sk.sets.get('por').style, 'bars');
  assert.equal(sk.sets.get('rock').src, 'mud log, read off its printout');
  assert.deepEqual(plain(C.valueAt(sk.sets.get('rock'), 1004.5)), { md: 1005, v: 1 });
  assert.deepEqual(plain(C.depthIn(sk.lists, '2')), { top: 1250, base: 1252 }, 'the stage from the pad row');
  const skc = C.catalogue(sk);
  assert.equal(skc.find(o => o.kind === 'c:total_gas').ok, false, 'a curve with no readings is not on file');
  assert.equal(skc.find(o => o.kind === 'rock').group, 'mud');
  assert.deepEqual(plain(C.windowFor('stage', sk, '1', ['rock'])).lo, 1225);

  // ---------- comments (synthetic): intervals along MD, listed by depth ----------
  const withComments = { ...bc, comments: [
    { top: 2850, base: 2870, text: 'Shale, dark grey, firm.', kind: 'description', rocks: { shale: 90, siltstone: null }, from: 'printout', file: 'a.pdf' },
    { top: 2800, base: 2830, text: 'Sandstone, fine, trace oil stain.', kind: 'description', rocks: { sandstone: 70, shale: 30 }, from: 'printout' },
    { top: 2820, base: 2825, text: 'Losses 4 m3/hr.', kind: 'note', from: 'report' },
    { top: 3500, text: 'Far away.', kind: 'note' },
    { top: 'x', text: 'no depth' }, { top: 2900, text: '   ' },
  ] };
  const mc = C.buildModel('28751', withComments, null, null, S);
  const cm = mc.sets.get('comments');
  assert.equal(cm.items.length, 4, 'a comment needs a depth and some words');
  assert.deepEqual(plain(cm.items.map(c => c.top)), [2800, 2820, 2850, 3500], 'by depth');
  assert.equal(cm.items[3].base, 3500, 'a comment at a point');
  assert.deepEqual(plain(cm.items[2].rocks), [['shale', 90], ['siltstone', null]]);
  assert.equal(cm.src, 'from the printout and report');
  assert.equal(C.catalogue(mc).find(o => o.kind === 'comments').ok, true);
  const inWin = C.commentsIn(cm.items, 2765.2, 2915.3);
  assert.deepEqual(plain(inWin.map(c => c.text)), ['Sandstone, fine, trace oil stain.', 'Losses 4 m3/hr.', 'Shale, dark grey, firm.']);
  assert.deepEqual(plain(C.lanes(inWin)), [0, 1, 0], 'overlapping intervals on rows of their own');
  assert.equal(C.valueAt(cm, 2822).v.length, 2);

  // ---------- the stack: the default, what a card opens with, what differs ----------
  const def = C.sanitizeStack({ kinds: ['las:Neutron porosity', 'gamma', 'gamma', 7, 'comments'], win: 'lateral' });
  assert.deepEqual(plain(def), { kinds: ['las:Neutron porosity', 'gamma', 'comments'], win: 'lateral' });
  assert.equal(C.sanitizeStack({ kinds: 'gamma' }), null);
  assert.equal(C.sanitizeStack({ kinds: [], win: 'sideways' }).win, 'stage');
  assert.deepEqual(plain(C.resolve(def.kinds, m)), ['gamma'], 'the kinds this well lacks are skipped');
  assert.deepEqual(plain(C.resolve(def.kinds, mc)), ['gamma', 'comments']);
  assert.deepEqual(plain(C.expected(def, m)), { kinds: ['gamma'], win: 'lateral' });
  assert.deepEqual(plain(C.expected(null, m)), { kinds: [], win: 'stage' }, 'no default: blank');
  assert.equal(C.sameStack({ kinds: ['gamma'], win: 'lateral' }, C.expected(def, m)), true, 'a card the default filled does not differ from it');
  assert.equal(C.sameStack({ kinds: ['gamma'], win: 'stage' }, C.expected(def, m)), false, 'another window differs');
  assert.equal(C.sameStack({ kinds: [], win: 'well' }, { kinds: [], win: 'stage' }), true, 'with no datasets the window does not matter');
  assert.equal(C.sameStack({ kinds: ['gamma', 'comments'], win: 'stage' }, { kinds: ['comments', 'gamma'], win: 'stage' }), false, 'order counts');

  // ---------- ticks ----------
  const t = C.ticks(2765.2, 2915.3, 700);
  assert.equal(t.step, 20); assert.deepEqual(plain(t.at.slice(0, 2)), [2780, 2800]);
  assert.equal(C.ticks(0, 4267, 700).step, 500);

  // ---------- a well whose file could not be read ----------
  const bad = C.emptyModel('1', 'gone');
  assert.equal(bad.ok, false); assert.deepEqual(plain(C.catalogue(bad)), []); assert.deepEqual(plain(C.resolve(['gamma'], bad)), []);

  // ---------- rock type from the written descriptions: said so ----------
  {
    const row2 = { well: { wa: 'SK2' }, logs: { md0: 1000, bin: 2, src: [{ log: 'printout', lith: false }, { log: 'descriptions', lith: true }],
      types: { rock: [0, 0, 1], gamma: [80, 90, 100] } } };
    const m2 = C.buildModel('SK2', { well: { wa: 'SK2' } }, row2, null, S);
    assert.equal(m2.sets.get('rock').src, 'the written sample descriptions', 'rock from descriptions');
    assert.equal(m2.sets.get('gamma').src, 'mud log, read off its printout', 'the curves from the printout');
  }

  // ---------- the stages on the map: placed by MD along the trajectory ----------
  {
    const traj = { md: [0, 1000, 2000, 3000], lat: [55, 55, 55.01, 55.02], lon: [-120, -120, -120, -120] };
    assert.deepEqual(plain(C.along(traj, 2500)), [-120, 55.015], 'half way between stations');
    assert.deepEqual(plain(C.along(traj, 3020)), [-120, 55.02], 'a port just past the last station sits at the toe');
    assert.equal(C.along(traj, 3100), null, 'well past TD: off the well');
    assert.equal(C.along({ md: [0, 10] }, 5), null, 'no positions');
    const w = { trajectory: traj,
      stages: [{ n: 1, label: '1', top_m: null, base_m: null, proppant_t: 40, date: '2020-01-02' }, { n: 2, label: '2', top_m: null, base_m: null }],
      depth_intervals: [{ n: 1, top_m: 2900, base_m: 2900.2, date: '20200102', completion_type: 'OHB' }, { n: 2, top_m: 2600, base_m: 2600.2 }] };
    const pts = C.stagePoints(w);
    assert.deepEqual(plain(pts.map(p => p.label)), ['1', '2'], 'labels from the list that places them');
    assert.ok(Math.abs(pts[0].at[1] - 55.019) < 1e-5 && Math.abs(pts[1].at[1] - 55.016) < 1e-5, 'each where its MD is');
    const facts = Object.fromEntries(C.stageFacts(w, '1'));
    assert.equal(facts.Date, '2020-01-02', "the treatment summary's date wins over the filing's");
    assert.equal(facts.Completion, 'OHB'); assert.equal(facts.Proppant, '40 t');
    assert.deepEqual(plain(C.stageFacts(w, '9')), [], 'a stage not on file');
    assert.deepEqual(plain(C.stagePoints({ stages: [{ label: '1', top_m: 100, base_m: 100 }] })), [], 'no trajectory: not placed');
  }

  console.log('PASS: stage datasets: what a well has, its stage, the window, comments and the default stack; stages on the map');
})().catch(e => { console.error(e); process.exitCode = 1; });
