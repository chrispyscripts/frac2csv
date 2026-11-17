// logs.js: the kinds of log data a well can be coloured by, their colours, words
// and menu. A synthetic Saskatchewan index and wells only (the WellSight logs are
// not public).
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict'), path = require('node:path');
const read = f => fs.readFileSync(path.join(__dirname, '../web/public', f), 'utf8');

// a little DOM: enough for the menu and the style tag
class El {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.style = {}; this.textContent = ''; this.disabled = false; }
  append(...c) { this.children.push(...c); }
  setAttribute(k, v) { this.attrs[k] = v; }
  get options() { return this.children.flatMap(c => (c.tag === 'optgroup' ? c.children : c.tag === 'option' ? [c] : [])); }
}
class Option extends El { constructor(text, value) { super('option'); this.textContent = text; this.value = value; } }
const store = new Map(), events = [];
const index = {
  bin_m: 2, rocks: [['sandstone', 'Sandstone'], ['shale', 'Shale'], ['raw:PAYZONE', 'PAY ZONE']],
  types: { 'c:rop': { t: 'Drill time (rate of penetration)', u: 'min/m', wells: 3 }, 'c:total_gas': { t: 'Total gas', u: 'units', wells: 2 } },
  scales: { gamma: { lo: 20, p50: 70, hi: 140 }, 'c:rop': { lo: 0.5, p50: 2, hi: 12 } }, pads: [],
};
const win = {
  document: { documentElement: { dataset: { theme: 'light' } }, createElement: t => new El(t), getElementById: () => null, head: new El('head') },
  localStorage: { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) },
  fetch: async u => ({ ok: u === 'data/sk/index.json', json: async () => index }),
  addEventListener: () => {}, dispatchEvent: e => events.push(e), CustomEvent: class { constructor(t, o) { this.type = t; this.detail = o && o.detail; } },
  Option, Promise, Math, Number, String, Object, Array, Map, JSON, isFinite, encodeURIComponent,
};
win.window = win;
// the gamma palettes, for the curves' colours
vm.createContext(win);
vm.runInContext(read('gamma-palettes.js'), win);
vm.runInContext(read('logs.js'), win);
const L = win.StratumLogs;
// objects made in the sandbox have its prototypes: compare them as plain data
const plain = o => JSON.parse(JSON.stringify(o));

(async () => {
  await L.skReady;
  // where a pad and a well are: the Saskatchewan set's are local
  assert.equal(L.padUrl('sk-0007'), 'data/sk/pads/sk-0007.json');
  assert.equal(L.padUrl('region-123'), 'data/region/pads/region-123.json');
  assert.equal(L.wellUrl('SK10X001'), 'data/sk/wells/SK10X001.json');
  assert.equal(L.wellUrl('28744'), 'data/wells/28744.json');
  assert.equal(L.wellId({ wa: 'SK10X001', licence: '10X001' }), 'Licence 10X001');
  assert.equal(L.wellId({ wa: '28744' }), 'WA 28744');

  // a WellSight well's runs, and a BC well's LAS gamma
  const sk = { logs: { md0: 1000, bin: 2, types: { rock: [0, 0, 1, null, 2], por: [9, 12, null, 3, 24], show: [null, 1, 4, 0, null],
    gamma: [60, 90, 120, 30, 140], 'c:rop': [1, 2, 3, 4, 5], 'c:total_gas': [null, null, null, null, null] } } };
  const bc = { gmd0: 2000, gbin: 5, gv: [80, null, 150], gest: true };
  assert.deepEqual(plain(L.track(sk, 'por')), { md0: 1000, bin: 2, v: [9, 12, null, 3, 24] });
  assert.equal(L.track(sk, 'c:total_gas'), null, 'a run with no readings is none');
  assert.equal(L.track(bc, 'gamma').est, true);
  assert.equal(L.track(bc, 'rock'), null);
  assert.equal(L.at(L.track(sk, 'rock'), 1004.5), 1);
  assert.equal(L.at(L.track(sk, 'por'), 1004.9), null);
  assert.equal(L.at(L.track(bc, 'gamma'), 2011), 150);

  // the kinds here, gamma first, the curves after the log's own
  const av = L.available([sk, bc]).map(t => t.k);
  assert.deepEqual(plain(av), ['gamma', 'rock', 'por', 'show', 'c:rop']);
  assert.deepEqual(plain(L.available([bc]).map(t => t.k)), ['gamma']);
  assert.equal(L.def('c:rop').t, 'Drill time (ROP)');
  assert.equal(L.def('c:rop').curve, true);
  // the choice is kept where the wells have it, else the first they have
  L.set('show');
  assert.equal(store.get('stratum.logType'), 'show');
  assert.equal(events.at(-1).type, 'stratum:logtype');
  assert.equal(L.pick([sk]), 'show');
  assert.equal(L.pick([bc]), 'gamma', 'a BC area has gamma only');

  // colours: rocks by name, porosity and shows on their own ramps, curves on the gamma colours
  assert.equal(L.ink('rock', 0), '#e8c33b');
  assert.match(L.ink('rock', 2), /^hsl\(/, 'a log’s own rock name still gets a colour');
  assert.notEqual(L.ink('por', 0), L.ink('por', 24));
  assert.equal(new Set([0, 1, 2, 3, 4].map(v => L.ink('show', v))).size, 5, 'each show level its own colour');
  assert.equal(L.ink('show', null), null);
  assert.ok(L.ink('c:rop', 5, L.scale('c:rop')));
  assert.equal(L.ink('c:total_gas', 5, L.scale('c:total_gas')), null, 'no scale, no colour');
  assert.deepEqual(plain(L.scale('por')), { lo: 0, hi: 24, p50: 12 });
  assert.deepEqual(plain(L.scale('gamma', { lo: 70, hi: 180, p50: 120 })), { lo: 70, hi: 180, p50: 120 }, 'a BC well keeps gamma.json’s scale');
  assert.deepEqual(plain(L.scale('gamma')), index.scales.gamma);
  assert.equal(L.height('rock', 1), 1);
  assert.equal(L.height('show', 4), 1);
  assert.ok(L.height('por', 12) > L.height('por', 3));

  // words
  assert.equal(L.words('rock', 1), 'Shale');
  assert.equal(L.words('por', 12), '12 % porosity');
  assert.equal(L.words('show', 3), 'Moderate show');
  assert.equal(L.words('show', null), 'no show');
  assert.equal(L.words('c:rop', 2.25), 'Drill time (ROP) 2.25 min/m');

  // the menu: every kind here, the log's own then the curves, a step either way that wraps
  const types = L.available([sk]);
  let picked = null;
  const m = L.menu({ types, value: 'show', onPick: k => { picked = k; } });
  const [prev, sel, next] = m.children;
  assert.deepEqual(plain(sel.children.map(g => g.attrs.label || g.label)), ['Log', 'Log curves']);
  assert.deepEqual(plain(sel.options.map(o => o.value)), ['gamma', 'rock', 'por', 'show', 'c:rop']);
  assert.equal(sel.value, 'show');
  next.onclick(); assert.equal(picked, 'c:rop');
  next.onclick(); assert.equal(picked, 'gamma', 'past the last, back to the first');
  prev.onclick(); assert.equal(picked, 'c:rop');
  assert.equal(store.get('stratum.logType'), 'c:rop');
  const one = L.menu({ types: L.available([bc]) });
  assert.ok(one.children[0].disabled && one.children[2].disabled, 'one kind: nothing to step through');

  // [ and ] step through them from the keyboard
  L.set('rock');
  assert.equal(L.stepKey({ key: ']' }, types), true); assert.equal(L.current(), 'por');
  assert.equal(L.stepKey({ key: '[' }, types), true); assert.equal(L.current(), 'rock');
  assert.equal(L.stepKey({ key: ']', metaKey: true }, types), false);
  assert.equal(L.stepKey({ key: 'x' }, types), false);

  // the key: the rocks here, the commonest first
  assert.deepEqual(plain(L.rocksIn([sk])), [0, 1, 2]);
  assert.match(L.keyHtml('rock', null, [1, 0]), /Shale.*Sandstone/s);
  assert.match(L.keyHtml('show'), /Questionable/);
  assert.match(L.keyHtml('c:rop', L.scale('c:rop')), /min\/m/);
  console.log('PASS: log kinds, runs, colours, words, the menu and its keys');
})().catch(e => { console.error(e); process.exitCode = 1; });
