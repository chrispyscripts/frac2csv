// FracView's share links: a saved session handed to colleagues as a link
// (api/share.js).
//
//   GET                         the signed-in account's share links
//   GET  ?t=<token>             a shared session, for anyone signed in to FracView
//   POST {action:'create', id}  a link to one of this account's saved sessions (a copy
//                               of it as it is now; sharing it again refreshes the copy,
//                               same link)
//   POST {action:'revoke', token}
//
// A link opens a copy: the person opening it never changes the original, and the
// owner can withdraw it. FracView is invite-only, so a link works only for people
// with an account; it shows a session's views, not anything the data files don't.
//
// In the private Blob store: shares/<token>.json (owner, session copy) and
// sessions/<account>/shares.json listing an account's links. The owner comes only
// from the signed cookie, as for sessions.
import { signedIn } from './saved-sessions.js';

export const MAX_SHARES = 60;
const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } });
const fail = (status, error) => json(status, { error });
const sharePath = t => `shares/${t}.json`;
const listPath = uid => `sessions/${uid}/shares.json`;
const sessionPath = (uid, id) => `sessions/${uid}/${id}.json`;
const TOKEN = /^[A-Za-z0-9_-]{24}$/;
const newToken = () => btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(18)))).replace(/\+/g, '-').replace(/\//g, '_');

async function updateList(store, uid, fn) {
  for (let i = 0; i < 5; i++) {
    const cur = await store.read(listPath(uid));
    const next = fn(cur ? cur.data : { shares: [] });
    try { await store.write(listPath(uid), next, cur ? { ifMatch: cur.etag } : { create: true }); return next; }
    catch (e) { if (!e.conflict) throw e; }
  }
  throw Error('Your links are being changed elsewhere; try again.');
}

export async function handle(request, store, secret) {
  const uid = await signedIn(request, store, secret);
  if (!uid) return fail(401, 'Sign in to FracView to open shared sessions.');
  const url = new URL(request.url);
  if (request.method === 'GET') {
    const t = url.searchParams.get('t');
    if (t != null) {
      if (!TOKEN.test(t)) return fail(404, 'That link is not a FracView share link.');
      const got = await store.read(sharePath(t));
      if (!got) return fail(404, 'That link has been withdrawn, or never existed.');
      const d = got.data;
      return json(200, { session: d.session, name: d.name, by: d.ownerName || 'a FracView user', created: d.created, mine: d.owner === uid });
    }
    return json(200, { shares: ((await store.read(listPath(uid)))?.data || { shares: [] }).shares });
  }
  if (request.method !== 'POST') return fail(405, 'Use GET or POST.');
  const origin = request.headers.get('origin');
  if (origin && new URL(origin).host !== url.host) return fail(403, 'Cross-site request refused.');
  let b = {};
  try { b = JSON.parse((await request.text()).slice(0, 10_000)) || {}; } catch (e) { return fail(400, 'That request was not readable.'); }

  if (b.action === 'create') {
    const id = String(b.id || '');
    if (!/^[0-9a-f]{16}$/.test(id)) return fail(400, 'No such session.');
    const s = await store.read(sessionPath(uid, id));
    if (!s) return fail(404, 'That session is no longer saved.');
    const acct = await store.read(`users/${uid}.json`);
    const list = ((await store.read(listPath(uid)))?.data || { shares: [] }).shares;
    const have = list.find(x => x.sessionId === id);
    if (!have && list.length >= MAX_SHARES) return fail(400, `You can keep up to ${MAX_SHARES} share links; withdraw one first.`);
    const token = have ? have.token : newToken(), created = new Date().toISOString();
    await store.write(sharePath(token), { owner: uid, ownerName: (acct && acct.data.name) || '', sessionId: id, name: s.data.name, created, session: s.data });
    const next = await updateList(store, uid, cur => ({
      shares: [{ token, sessionId: id, name: s.data.name, created }, ...cur.shares.filter(x => x.token !== token)].slice(0, MAX_SHARES) }));
    return json(200, { token, shares: next.shares });
  }
  if (b.action === 'revoke') {
    const t = String(b.token || '');
    if (!TOKEN.test(t)) return fail(400, 'No such link.');
    const got = await store.read(sharePath(t));
    if (got && got.data.owner !== uid) return fail(403, 'Only the person who shared it can withdraw that link.');
    if (got) await store.remove(sharePath(t)).catch(() => {});
    const next = await updateList(store, uid, cur => ({ shares: cur.shares.filter(x => x.token !== t) }));
    return json(200, { shares: next.shares });
  }
  return fail(400, 'Unknown action.');
}
