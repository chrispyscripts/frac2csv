// Saved sessions kept per account (web/lib/saved-sessions.js), on an in-memory
// store standing in for the private Blob store: each account sees only its own.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { handle, MAX_SESSIONS } from '../web/lib/saved-sessions.js';
import { sign, COOKIE } from '../web/lib/session.js';

const SECRET = 'test-secret-' + 'x'.repeat(24);
const files = new Map();      // path -> {text, etag}
let n = 0, conflictsLeft = 0;
const store = {
  async read(path) { const f = files.get(path); return f ? { data: JSON.parse(f.text), etag: f.etag } : null; },
  async write(path, data, { create = false, ifMatch } = {}) {
    const cur = files.get(path);
    if ((create && cur) || (ifMatch && (!cur || cur.etag !== ifMatch))) throw Object.assign(Error('conflict'), { conflict: true });
    if (path.endsWith('index.json') && conflictsLeft > 0) { conflictsLeft--; files.set(path, { text: JSON.stringify({ sessions: [] }), etag: 'e' + (++n) }); throw Object.assign(Error('conflict'), { conflict: true }); }
    files.set(path, { text: JSON.stringify(data), etag: 'e' + (++n) });
  },
  async remove(path) { files.delete(path); },
};
const uid = email => createHash('sha256').update(email).digest('hex');
const account = (email, extra = {}) => files.set(`users/${uid(email)}.json`, { text: JSON.stringify({ email, name: email, role: 'user', ...extra }), etag: 'u' });
const cookieFor = async (email, secret = SECRET) => {
  const t = Math.floor(Date.now() / 1000);
  return `${COOKIE}=${await sign({ sub: uid(email), email, iat: t, chk: t, exp: t + 3600 }, secret)}`;
};
const call = async (cookie, { method = 'GET', q = '', body, origin } = {}) => {
  const headers = { cookie: cookie || '' };
  if (origin) headers.origin = origin;
  const r = await handle(new Request('https://fv.test/api/sessions' + q, { method, headers, body: body ? JSON.stringify(body) : undefined }), store, SECRET);
  return { status: r.status, body: await r.json() };
};
const session = (name, saved = new Date().toISOString(), windows = 1) => ({ kind: 'fracview-session', v: 1, name, saved, settings: {},
  windows: Array.from({ length: windows }, (_, i) => ({ role: i ? 'window' : 'main', url: 'map.html', session: {} })) });

account('carmine@example.com'); account('bob@example.com'); account('gone@example.com', { disabled: true });
const carmine = await cookieFor('carmine@example.com'), bob = await cookieFor('bob@example.com');

// signed out, forged, or a removed account: nothing
assert.equal((await call('')).status, 401);
assert.equal((await call(await cookieFor('carmine@example.com', 'another-secret-entirely-xxxxxxx'))).status, 401, 'a cookie signed with another secret');
assert.equal((await call(await cookieFor('gone@example.com'))).status, 401, 'a disabled account');
assert.equal((await call(await cookieFor('nobody@example.com'))).status, 401, 'an account that does not exist');

// save, list, open, replace by name, delete
assert.deepEqual((await call(carmine)).body, { sessions: [] });
const saved = await call(carmine, { method: 'POST', body: { action: 'save', session: session('Gundy review', '2026-10-06T10:00:00Z', 3), summary: 'Map · Wine racks' } });
assert.equal(saved.status, 200);
const id = saved.body.id;
assert.match(id, /^[0-9a-f]{16}$/);
let list = (await call(carmine)).body.sessions;
assert.deepEqual(list.map(x => [x.name, x.windows, x.summary]), [['Gundy review', 3, 'Map · Wine racks']]);
assert.equal((await call(carmine, { q: '?id=' + id })).body.session.name, 'Gundy review');
await call(carmine, { method: 'POST', body: { action: 'save', session: session('Gundy review', '2026-10-06T11:00:00Z', 2) } });
list = (await call(carmine)).body.sessions;
assert.equal(list.length, 1, 'the same name replaces');
assert.equal(list[0].windows, 2);

// another account sees none of it, and cannot open it by its id
assert.deepEqual((await call(bob)).body, { sessions: [] }, 'Bob does not see Carmine’s sessions');
assert.equal((await call(bob, { q: '?id=' + id })).status, 404, 'nor open one by its id');
await call(bob, { method: 'POST', body: { action: 'delete', id } });
assert.equal((await call(carmine)).body.sessions.length, 1, 'nor delete it');
assert.equal((await call(bob, { q: '?id=../' + uid('carmine@example.com') + '/' + id })).status, 400, 'nor reach it by a path');

// bad requests
assert.equal((await call(carmine, { method: 'POST', body: { action: 'save', session: { kind: 'x' } } })).status, 400);
assert.equal((await call(carmine, { method: 'POST', body: { action: 'save', session: session('') } })).status, 400);
assert.equal((await call(carmine, { method: 'POST', origin: 'https://evil.example', body: { action: 'save', session: session('X') } })).status, 403, 'another site cannot save');

// delete
const del = await call(carmine, { method: 'POST', body: { action: 'delete', id } });
assert.deepEqual(del.body.sessions, []);
assert.equal(files.has(`sessions/${uid('carmine@example.com')}/${id}.json`), false, 'its file is gone');

// a busy index is retried, not lost
conflictsLeft = 2;
assert.equal((await call(carmine, { method: 'POST', body: { action: 'save', session: session('Retry') } })).status, 200);
assert.deepEqual((await call(carmine)).body.sessions.map(x => x.name), ['Retry']);

// at most MAX_SESSIONS: the oldest go, files and all
for (let i = 0; i < MAX_SESSIONS + 2; i++) await call(bob, { method: 'POST', body: { action: 'save', session: session('s' + i, new Date(Date.UTC(2026, 0, 1, 0, i)).toISOString()) } });
list = (await call(bob)).body.sessions;
assert.equal(list.length, MAX_SESSIONS);
assert.equal(list.at(-1).name, 's2', 's0 and s1, the oldest, are gone');
assert.equal([...files.keys()].filter(k => k.startsWith(`sessions/${uid('bob@example.com')}/`) && !k.endsWith('index.json')).length, MAX_SESSIONS);

// a browser's own list carried over once: newer ones in, older duplicates of the account's left out
const dave = (account('dave@example.com'), await cookieFor('dave@example.com'));
await call(dave, { method: 'POST', body: { action: 'save', session: session('Shared name', '2026-10-05T12:00:00Z') } });
const imp = await call(dave, { method: 'POST', body: { action: 'import', sessions: [
  { session: session('From the laptop', '2026-10-01T09:00:00Z'), summary: 'Map' },
  { session: session('Shared name', '2026-10-01T09:00:00Z'), summary: 'older' },
  { session: { kind: 'nope' } }] } });
assert.equal(imp.body.added, 1);
assert.deepEqual(imp.body.sessions.map(x => x.name).sort(), ['From the laptop', 'Shared name']);
assert.notEqual(imp.body.sessions.find(x => x.name === 'Shared name').summary, 'older', 'the account’s newer one stays');
assert.deepEqual((await call(carmine)).body.sessions.map(x => x.name), ['Retry'], 'Dave’s import went to Dave only');
console.log('PASS: saved sessions are per account: listed, opened, replaced, deleted, capped and imported, none shared');
