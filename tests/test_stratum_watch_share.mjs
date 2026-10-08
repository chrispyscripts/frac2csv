// Watch lists (web/lib/account-docs.js, k=watch), share links (web/lib/shares.js)
// and the email digest (web/lib/digest.js), on an in-memory store standing in
// for the private Blob store and a stub for the regulator's map services.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { handle as mine, MAX_WATCH } from '../web/lib/account-docs.js';
import { handle as shareHandle } from '../web/lib/shares.js';
import { news, compose, run } from '../web/lib/digest.js';
import { sign, COOKIE } from '../web/lib/session.js';

const SECRET = 'test-secret-' + 'z'.repeat(24);
const files = new Map();
let n = 0;
const store = {
  async read(path) { const f = files.get(path); return f ? { data: JSON.parse(f.text), etag: f.etag } : null; },
  async write(path, data, { create = false, ifMatch } = {}) {
    const cur = files.get(path);
    if ((create && cur) || (ifMatch && (!cur || cur.etag !== ifMatch))) throw Object.assign(Error('conflict'), { conflict: true });
    files.set(path, { text: JSON.stringify(data), etag: 'e' + (++n) });
  },
  async remove(path) { files.delete(path); },
};
const uid = email => createHash('sha256').update(email).digest('hex');
for (const [e, name] of [['carmine@example.com', 'Carmine'], ['dave@example.com', 'Dave']]) files.set(`users/${uid(e)}.json`, { text: JSON.stringify({ email: e, name }), etag: 'u' });
const cookieFor = async email => { const t = Math.floor(Date.now() / 1000); return `${COOKIE}=${await sign({ sub: uid(email), email, iat: t, exp: t + 3600 }, SECRET)}`; };
const carmine = await cookieFor('carmine@example.com'), dave = await cookieFor('dave@example.com');
const req = (url, cookie, body, origin) => {
  const headers = { cookie: cookie || '' }; if (origin) headers.origin = origin;
  return new Request(url, { method: body ? 'POST' : 'GET', headers, body: body ? JSON.stringify(body) : undefined });
};
const watch = async (cookie, body) => { const r = await mine(req('https://fv.test/api/mine?k=watch', cookie, body), store, SECRET); return { status: r.status, body: await r.json() }; };
const share = async (cookie, body, q = '', origin) => { const r = await shareHandle(req('https://fv.test/api/share' + q, cookie, body, origin), store, SECRET); return { status: r.status, body: await r.json() }; };

// ---- watch lists ----
assert.equal((await watch('')).status, 401, 'signed out');
assert.deepEqual((await watch(carmine)).body.pads, [], 'empty to start');
let w = await watch(carmine, { action: 'set', watch: { pads: [
  { id: 'gundy-01', name: 'Gundy pad 1', lat: 56.7997, lon: -122.11, km: 80, mag: -3 },
  { id: 'gundy-01', name: 'twice', lat: 56.8, lon: -122.1 },
  { id: 'BAD ID', lat: 56, lon: -122 }, { id: 'far-away', lat: 10, lon: 10 },
  { id: 'region-40402', name: 'Blueberry', lat: 56.7455, lon: -121.9532 }], digest: 'weekly', email: true, quakeAlerts: 1 } });
assert.equal(w.status, 200);
assert.deepEqual(w.body.pads.map(p => [p.id, p.km, p.mag]), [['gundy-01', 50, 0], ['region-40402', 10, 2]], 'pads cleaned: once each, in BC, reach and magnitude bounded');
assert.equal(w.body.digest, 'weekly'); assert.equal(w.body.quakeAlerts, true);
assert.deepEqual((await watch(dave)).body.pads, [], 'Dave does not see Carmine’s list');
assert.equal((await watch(carmine, { action: 'set', watch: { pads: Array.from({ length: MAX_WATCH + 1 }, (_, i) => ({ id: 'region-' + i, lat: 56, lon: -122 })) } })).status, 400);
w = await watch(carmine, { action: 'seen', at: '2026-10-01T00:00:00Z' });
assert.equal(w.body.seen, '2026-10-01T00:00:00Z');
w = await watch(carmine, { action: 'seen', at: '2026-09-01T00:00:00Z' });
assert.equal(w.body.seen, '2026-10-01T00:00:00Z', 'seen never goes backwards');
w = await watch(carmine, { action: 'seen', at: '2999-01-01T00:00:00Z' });
assert(w.body.seen < '2999', 'nor into the future');
assert.equal((await watch(carmine, { action: 'set', watch: { digest: 'hourly', pads: [] } })).body.digest, 'off', 'unknown digests are off');

// ---- share links ----
const sess = { kind: 'fracview-session', v: 1, name: 'Gundy look', saved: '2026-10-08T10:00:00Z', area: 'Gundy', settings: { 'stratum.theme': 'dark' },
               windows: [{ role: 'main', url: 'map.html', session: {} }] };
files.set(`sessions/${uid('carmine@example.com')}/0123456789abcdef.json`, { text: JSON.stringify(sess), etag: 's1' });
assert.equal((await share('', null)).status, 401, 'signed out');
assert.equal((await share(dave, { action: 'create', id: '0123456789abcdef' })).status, 404, 'Dave cannot share Carmine’s session by its id');
const made = await share(carmine, { action: 'create', id: '0123456789abcdef' });
assert.equal(made.status, 200);
const token = made.body.token;
assert.match(token, /^[A-Za-z0-9_-]{24}$/);
assert.equal((await share(carmine, { action: 'create', id: '0123456789abcdef' })).body.token, token, 'sharing again keeps the link');
const opened = await share(dave, null, '?t=' + token);
assert.equal(opened.status, 200);
assert.equal(opened.body.by, 'Carmine'); assert.equal(opened.body.name, 'Gundy look'); assert.equal(opened.body.mine, false);
assert.equal(opened.body.session.windows.length, 1, 'any signed-in account opens the copy');
assert.equal((await share('', null, '?t=' + token)).status, 401, 'but not someone signed out');
assert.deepEqual((await share(dave, null)).body.shares, [], 'Dave has no links of his own');
assert.equal((await share(carmine, null)).body.shares.length, 1);
assert.equal((await share(dave, { action: 'revoke', token })).status, 403, 'only the owner withdraws it');
assert.equal((await share(carmine, { action: 'create', id: '0123456789abcdef' }, '', 'https://evil.example')).status, 403, 'another site cannot');
assert.equal((await share(carmine, { action: 'revoke', token })).status, 200);
assert.equal((await share(dave, null, '?t=' + token)).status, 404, 'withdrawn');
assert.equal((await share(dave, null, '?t=../users/x')).status, 404, 'tokens are tokens');

// ---- the digest ----
const pads = [{ id: 'gundy-01', name: 'Gundy pad 1', lat: 56.7997, lon: -122.11, km: 10, mag: 2 }];
const stub = async url => ({ json: async () => (url.includes('SEISMIC_EVENT_PT')
  ? { features: [
      { attributes: { EVENT_DATE_TIME: Date.parse('2026-10-05T10:00:00Z'), MAGNITUDE: 2.4, LATITUDE: 56.83, LONGITUDE: -122.05, DEPTH_KM: 2 } },
      { attributes: { EVENT_DATE_TIME: Date.parse('2026-10-06T10:00:00Z'), MAGNITUDE: 1.6, LATITUDE: 56.80, LONGITUDE: -122.11, DEPTH_KM: 2 } },   // too small
      { attributes: { EVENT_DATE_TIME: Date.parse('2026-10-06T11:00:00Z'), MAGNITUDE: 3.1, LATITUDE: 57.40, LONGITUDE: -122.11, DEPTH_KM: 2 } }] } // too far
  : { features: [{ attributes: { OPS_EXPECTED_START_DATE: Date.parse('2026-10-09'), OPS_EXPECTED_END_DATE: Date.parse('2026-10-20'), WA_NUM: '55555',
        WELL_NAME: 'TOURMALINE  HZ  GUNDY X', OPERATOR_ABBREVIATION: 'TOURMALINE' }, geometry: { x: -122.0, y: 56.82 } }] }) });
const nw = await news(pads, new Date('2026-10-01T00:00:00Z'), stub);
assert.deepEqual(nw.quakes.map(q => q.mag), [2.4], 'only events within the pad’s reach and from its magnitude');
assert(Math.abs(nw.quakes[0].km - 4.9) < 0.5, 'distance in km');
assert.equal(nw.fracs.length, 1); assert.equal(nw.fracs[0].well, 'TOURMALINE HZ GUNDY X');
const mail = compose('Carmine', { pads }, nw, new Date('2026-10-01T00:00:00Z'), 'https://fv.test');
assert.match(mail.subject, /1 earthquake and 1 frac job/);
assert.match(mail.text, /M2\.40 .* from Gundy pad 1/);
// the cron job: off without its secret, refused with the wrong one, and quiet without a mail service
const env = { CRON_SECRET: 's3cret' };
assert.equal((await run(new Request('https://fv.test/api/digest'), {}, null)).status, 503);
assert.equal((await run(new Request('https://fv.test/api/digest', { headers: { authorization: 'Bearer nope' } }), env, null)).status, 401);
const quiet = await run(new Request('https://fv.test/api/digest', { headers: { authorization: 'Bearer s3cret' } }), env, null);
assert.equal(quiet.status, 200); assert.equal((await quiet.json()).sent, 0);
assert.deepEqual(await (await run(new Request('https://fv.test/api/digest?status=1'), env, null)).json(), { configured: false }, 'the status says only whether mail can go out');
console.log('PASS: watch lists and share links per account, digests only near watched pads and only when set up');
