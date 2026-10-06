// Groups and settings kept per account (web/lib/account-docs.js), on an in-memory
// store standing in for the private Blob store: each account sees only its own.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { handle, MAX_PADS } from '../web/lib/account-docs.js';
import { sign, COOKIE } from '../web/lib/session.js';

const SECRET = 'test-secret-' + 'y'.repeat(24);
const files = new Map();
let n = 0, conflictsLeft = 0;
const store = {
  async read(path) { const f = files.get(path); return f ? { data: JSON.parse(f.text), etag: f.etag } : null; },
  async write(path, data, { create = false, ifMatch } = {}) {
    const cur = files.get(path);
    if (conflictsLeft > 0 && path.startsWith('mine/')) { conflictsLeft--; throw Object.assign(Error('conflict'), { conflict: true }); }
    if ((create && cur) || (ifMatch && (!cur || cur.etag !== ifMatch))) throw Object.assign(Error('conflict'), { conflict: true });
    files.set(path, { text: JSON.stringify(data), etag: 'e' + (++n) });
  },
  async remove(path) { files.delete(path); },
};
const uid = email => createHash('sha256').update(email).digest('hex');
for (const e of ['carmine@example.com', 'dave@example.com']) files.set(`users/${uid(e)}.json`, { text: JSON.stringify({ email: e }), etag: 'u' });
const cookieFor = async email => { const t = Math.floor(Date.now() / 1000); return `${COOKIE}=${await sign({ sub: uid(email), email, iat: t, exp: t + 3600 }, SECRET)}`; };
const call = async (cookie, k, body, origin) => {
  const headers = { cookie: cookie || '' }; if (origin) headers.origin = origin;
  const r = await handle(new Request('https://fv.test/api/mine?k=' + k, { method: body ? 'POST' : 'GET', headers, body: body ? JSON.stringify(body) : undefined }), store, SECRET);
  return { status: r.status, body: await r.json() };
};
const carmine = await cookieFor('carmine@example.com'), dave = await cookieFor('dave@example.com');

assert.equal((await call('', 'groups')).status, 401, 'signed out');
assert.equal((await call(carmine, 'nope')).status, 404, 'unknown kind');

// groups: save, change, delete; another account sees none of them
assert.deepEqual((await call(carmine, 'groups')).body, { groups: [] });
const made = await call(carmine, 'groups', { action: 'save', group: { name: '  Altares north  ', pads: ['region-37949', 'region-37949', 'gundy-01', 'BAD ID', 7] } });
assert.equal(made.status, 200);
const g = made.body.group;
assert.equal(g.name, 'Altares north');
assert.deepEqual(g.pads, ['region-37949', 'gundy-01'], 'pad ids kept once each; anything else dropped');
assert.match(g.id, /^[0-9a-f]{16}$/);
const changed = await call(carmine, 'groups', { action: 'save', group: { id: g.id, name: 'Altares N', pads: ['gundy-01'], note: 'tight spacing' } });
assert.deepEqual(changed.body.groups.map(x => [x.name, x.pads.length, x.note]), [['Altares N', 1, 'tight spacing']], 'changed in place');
assert.deepEqual((await call(dave, 'groups')).body, { groups: [] }, 'Dave does not see Carmine’s groups');
assert.equal((await call(dave, 'groups', { action: 'save', group: { id: g.id, name: 'mine now', pads: ['gundy-02'] } })).status, 404, 'nor change one by its id');
await call(dave, 'groups', { action: 'delete', id: g.id });
assert.equal((await call(carmine, 'groups')).body.groups.length, 1, 'nor delete it');
assert.equal((await call(carmine, 'groups', { action: 'save', group: { name: 'x', pads: [] } })).status, 400, 'a group needs pads');
assert.equal((await call(carmine, 'groups', { action: 'save', group: { name: '', pads: ['gundy-01'] } })).status, 400, 'and a name');
assert.equal((await call(carmine, 'groups', { action: 'save', group: { name: 'big', pads: Array.from({ length: MAX_PADS + 1 }, (_, i) => 'region-' + i) } })).status, 400);
assert.equal((await call(carmine, 'groups', { action: 'save', group: { name: 'x', pads: ['gundy-01'] } }, 'https://evil.example')).status, 403, 'another site cannot');
conflictsLeft = 2;
assert.equal((await call(carmine, 'groups', { action: 'save', group: { name: 'Second', pads: ['gundy-03'] } })).status, 200, 'a busy file is retried');
assert.deepEqual((await call(carmine, 'groups')).body.groups.map(x => x.name), ['Altares N', 'Second']);
assert.deepEqual((await call(carmine, 'groups', { action: 'delete', id: g.id })).body.groups.map(x => x.name), ['Second']);

// settings: known keys only, merged, null removes
await call(carmine, 'prefs', { prefs: { 'stratum.theme': 'dark', 'stratum.textSize': 'l', 'evil.key': 'x', 'stratum.sessions': '[]' } });
let p = (await call(carmine, 'prefs')).body;
assert.deepEqual(p.prefs, { 'stratum.theme': 'dark', 'stratum.textSize': 'l' }, 'only settings that follow the person');
assert.ok(p.updated);
await call(carmine, 'prefs', { prefs: { 'stratum.textSize': null, 'stratum.gammaPalette': 'viridis' } });
p = (await call(carmine, 'prefs')).body;
assert.deepEqual(p.prefs, { 'stratum.theme': 'dark', 'stratum.gammaPalette': 'viridis' }, 'merged; null removes');
assert.deepEqual((await call(dave, 'prefs')).body.prefs, {}, 'Dave’s settings are his own');
console.log('PASS: groups and settings are per account: saved, changed, merged and deleted, none shared');
