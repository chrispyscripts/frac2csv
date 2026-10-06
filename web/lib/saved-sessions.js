// FracView's saved sessions, kept with each account (api/sessions.js).
//
//   GET                        the signed-in account's sessions: name, when, how many windows, a summary
//   GET  ?id=<id>              one session in full
//   POST {action:'save', session, summary}       a session of the same name is replaced
//   POST {action:'delete', id}
//   POST {action:'import', sessions:[{session, summary}]}
//                              sessions a browser kept before they lived with the account, carried over once
//
// In the private Blob store beside the accounts: sessions/<account>/<id>.json for each
// session and sessions/<account>/index.json listing them. <account> is the same id the
// account itself is filed under (sha256 of the email), and it comes only from the signed
// sign-in cookie, so no request can name another account's folder.
import { verify, readCookie } from './session.js';

export const MAX_SESSIONS = 60;        // per account; the oldest go past this
export const MAX_BYTES = 2_000_000;    // one session, as JSON
const KINDS = ['fracview-session', 'stratum-session'];

const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } });
const fail = (status, error) => json(status, { error });
const indexPath = uid => `sessions/${uid}/index.json`;
const sessionPath = (uid, id) => `sessions/${uid}/${id}.json`;
const newId = () => Array.from(crypto.getRandomValues(new Uint8Array(8)), b => b.toString(16).padStart(2, '0')).join('');
const str = (v, n) => typeof v === 'string' ? v.slice(0, n) : '';

// the store, as the Blob SDK gives it: read -> {data, etag} | null; write throws {conflict:true}
// when the file changed since it was read (or exists, when it was to be created)
export async function blobStore() {
  const { get, put, del, BlobPreconditionFailedError } = await import('@vercel/blob');
  return {
    async read(path) {
      const r = await get(path, { access: 'private', useCache: false });
      if (!r || r.statusCode !== 200 || !r.stream) return null;
      return { data: JSON.parse(await new Response(r.stream).text()), etag: r.blob.etag };
    },
    async write(path, data, { create = false, ifMatch } = {}) {
      try {
        await put(path, JSON.stringify(data), { access: 'private', contentType: 'application/json', addRandomSuffix: false,
          allowOverwrite: !create, cacheControlMaxAge: 60, ...(ifMatch ? { ifMatch } : {}) });
      } catch (e) {
        if (e instanceof BlobPreconditionFailedError || /already exists/i.test(String(e && e.message))) throw Object.assign(Error('conflict'), { conflict: true });
        throw e;
      }
    },
    remove: path => del(path),
  };
}

// a session as the page sends it: the shape session.js makes, within bounds
function sessionProblem(s) {
  if (!s || typeof s !== 'object' || !KINDS.includes(s.kind)) return 'That is not a FracView session.';
  if (!Array.isArray(s.windows) || !s.windows.length || s.windows.length > 12) return 'A session holds 1 to 12 windows.';
  if (typeof s.name !== 'string' || !s.name.trim()) return 'A session needs a name.';
  if (JSON.stringify(s).length > MAX_BYTES) return 'That session is too large to keep.';
  return null;
}
const entryOf = (id, s, summary) => ({ id, name: s.name.trim().slice(0, 120), saved: str(s.saved, 40) || new Date().toISOString(),
                                       windows: s.windows.length, summary: str(summary, 600) });

// the index, changed by `fn` and written back only if no one else wrote it meanwhile
async function updateIndex(store, uid, fn) {
  for (let i = 0; i < 5; i++) {
    const cur = await store.read(indexPath(uid));
    const next = fn(cur ? cur.data : { sessions: [] });
    try { await store.write(indexPath(uid), next, cur ? { ifMatch: cur.etag } : { create: true }); return next; }
    catch (e) { if (!e.conflict) throw e; }
  }
  throw Error('The sessions are being changed elsewhere; try again.');
}

async function save(store, uid, s, summary) {
  const idx = (await store.read(indexPath(uid)))?.data || { sessions: [] };
  const same = idx.sessions.find(x => x.name === s.name.trim().slice(0, 120));
  const id = same ? same.id : newId();
  await store.write(sessionPath(uid, id), s);
  let dropped = [];
  const next = await updateIndex(store, uid, cur => {
    const rest = cur.sessions.filter(x => x.id !== id && x.name !== s.name.trim().slice(0, 120));
    const all = [entryOf(id, s, summary), ...rest].sort((a, b) => String(b.saved).localeCompare(String(a.saved)));
    dropped = all.slice(MAX_SESSIONS);
    // a same-named session saved meanwhile by another window, under another id, is replaced too
    dropped.push(...cur.sessions.filter(x => x.id !== id && x.name === s.name.trim().slice(0, 120)));
    return { sessions: all.slice(0, MAX_SESSIONS) };
  });
  await Promise.all(dropped.map(x => store.remove(sessionPath(uid, x.id)).catch(() => {})));
  return { id, sessions: next.sessions };
}

export async function handle(request, store, secret) {
  // who is asking: the signed cookie, and an account that still exists
  const s = await verify(readCookie(request.headers.get('cookie')), secret);
  const uid = s && typeof s.sub === 'string' && /^[0-9a-f]{64}$/.test(s.sub) ? s.sub : null;
  if (!uid) return fail(401, 'Sign in to see your saved sessions.');
  const acct = await store.read(`users/${uid}.json`);
  if (!acct || acct.data.disabled) return fail(401, 'Sign in to see your saved sessions.');

  const url = new URL(request.url);
  if (request.method === 'GET') {
    const id = url.searchParams.get('id');
    if (id != null) {
      if (!/^[0-9a-f]{16}$/.test(id)) return fail(400, 'No such session.');
      const got = await store.read(sessionPath(uid, id));
      return got ? json(200, { session: got.data }) : fail(404, 'That session is no longer saved.');
    }
    const idx = (await store.read(indexPath(uid)))?.data || { sessions: [] };
    return json(200, { sessions: idx.sessions });
  }
  if (request.method !== 'POST') return fail(405, 'Use GET or POST.');
  // a form on another site cannot act as the signed-in user
  const origin = request.headers.get('origin');
  if (origin && new URL(origin).host !== url.host) return fail(403, 'Cross-site request refused.');
  const text = await request.text();
  if (text.length > MAX_BYTES * 3) return fail(413, 'That is too much to save at once.');
  let b = {};
  try { b = JSON.parse(text) || {}; } catch (e) { return fail(400, 'That request was not readable.'); }

  if (b.action === 'save') {
    const bad = sessionProblem(b.session); if (bad) return fail(400, bad);
    return json(200, await save(store, uid, b.session, b.summary));
  }
  if (b.action === 'delete') {
    const id = String(b.id || '');
    if (!/^[0-9a-f]{16}$/.test(id)) return fail(400, 'No such session.');
    const next = await updateIndex(store, uid, cur => ({ sessions: cur.sessions.filter(x => x.id !== id) }));
    await store.remove(sessionPath(uid, id)).catch(() => {});
    return json(200, { sessions: next.sessions });
  }
  if (b.action === 'import') {
    // a browser's own list, carried over: what the account has saved more recently under the same name stays
    const items = (Array.isArray(b.sessions) ? b.sessions : []).slice(0, 40);
    let sessions = ((await store.read(indexPath(uid)))?.data || { sessions: [] }).sessions, added = 0;
    for (const it of items) {
      if (!it || sessionProblem(it.session)) continue;
      const have = sessions.find(x => x.name === it.session.name.trim().slice(0, 120));
      if (have && String(have.saved) >= String(it.session.saved || '')) continue;
      sessions = (await save(store, uid, it.session, it.summary)).sessions; added++;
    }
    return json(200, { sessions, added });
  }
  return fail(400, 'Unknown action.');
}
