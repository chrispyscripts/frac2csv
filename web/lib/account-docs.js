// FracView: an account's own small documents, at /api/mine?k=<kind>.
//
//   groups   pads gathered under a name (the Groups screen, and Group mode on the map)
//     GET                                       {groups: [{id, name, pads, note, created, updated}]}
//     POST {action:'save', group:{id?, name, pads, note}}   a new group, or one changed
//     POST {action:'delete', id}
//   prefs    the settings that follow the person: theme, text size, gamma colours,
//            the quake filter, the map's well filter, the well section's and charts' choices
//     GET                                       {prefs: {key: value}, updated}
//     POST {prefs: {key: value | null}}         merged in; null removes a key
//
// In the private Blob store beside the accounts: mine/<account>/<kind>.json, the account
// id taken only from the signed cookie (lib/saved-sessions.js signedIn), and every change
// written only if no one else wrote it meanwhile (retried), so two windows never lose one
// another's edits.
import { signedIn } from './saved-sessions.js';

export const MAX_GROUPS = 100, MAX_PADS = 80;
export const PREF_KEYS = ['stratum.theme', 'stratum.textSize', 'stratum.gammaPalette', 'stratum.quakeFilter', 'stratum.allWells',
                          'stratum.section', 'stratum.hiddenCurves'];
const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } });
const fail = (status, error) => json(status, { error });
const docPath = (uid, kind) => `mine/${uid}/${kind}.json`;
const newId = () => Array.from(crypto.getRandomValues(new Uint8Array(8)), b => b.toString(16).padStart(2, '0')).join('');
const now = () => new Date().toISOString();
const EMPTY = { groups: () => ({ groups: [] }), prefs: () => ({ prefs: {}, updated: null }) };

async function update(store, uid, kind, fn) {
  for (let i = 0; i < 5; i++) {
    const cur = await store.read(docPath(uid, kind));
    const next = fn(cur ? cur.data : EMPTY[kind]());
    if (next instanceof Response) return next;
    try { await store.write(docPath(uid, kind), next, cur ? { ifMatch: cur.etag } : { create: true }); return next; }
    catch (e) { if (!e.conflict) throw e; }
  }
  throw Error('This is being changed elsewhere; try again.');
}

// a group as the page sends it, made safe: a name, pad ids as the region names them, a note
function cleanGroup(g) {
  if (!g || typeof g !== 'object') return { error: 'That is not a group.' };
  const name = typeof g.name === 'string' ? g.name.trim().slice(0, 80) : '';
  if (!name) return { error: 'A group needs a name.' };
  const pads = [...new Set((Array.isArray(g.pads) ? g.pads : []).filter(p => typeof p === 'string' && /^[a-z0-9][a-z0-9-]{0,40}$/.test(p)))];
  if (!pads.length) return { error: 'A group needs at least one pad.' };
  if (pads.length > MAX_PADS) return { error: `A group holds up to ${MAX_PADS} pads.` };
  return { name, pads, note: typeof g.note === 'string' ? g.note.trim().slice(0, 300) : '' };
}

export async function handle(request, store, secret) {
  const uid = await signedIn(request, store, secret);
  if (!uid) return fail(401, 'Sign in first.');
  const url = new URL(request.url), kind = url.searchParams.get('k');
  if (!EMPTY[kind]) return fail(404, 'Unknown kind.');
  if (request.method === 'GET') {
    const cur = await store.read(docPath(uid, kind));
    return json(200, cur ? cur.data : EMPTY[kind]());
  }
  if (request.method !== 'POST') return fail(405, 'Use GET or POST.');
  const origin = request.headers.get('origin');
  if (origin && new URL(origin).host !== url.host) return fail(403, 'Cross-site request refused.');
  const text = await request.text();
  if (text.length > 200_000) return fail(413, 'That is too much at once.');
  let b;
  try { b = JSON.parse(text) || {}; } catch (e) { return fail(400, 'That request was not readable.'); }

  if (kind === 'groups') {
    if (b.action === 'save') {
      const g = cleanGroup(b.group);
      if (g.error) return fail(400, g.error);
      const id = typeof b.group.id === 'string' && /^[0-9a-f]{16}$/.test(b.group.id) ? b.group.id : null;
      let saved = null;
      const next = await update(store, uid, 'groups', cur => {
        const old = id && cur.groups.find(x => x.id === id);
        if (id && !old) return fail(404, 'That group is no longer saved.');
        if (!old && cur.groups.length >= MAX_GROUPS) return fail(400, `You can keep up to ${MAX_GROUPS} groups.`);
        saved = old ? { ...old, ...g, updated: now() } : { id: newId(), ...g, created: now(), updated: now() };
        return { groups: old ? cur.groups.map(x => x.id === id ? saved : x) : [...cur.groups, saved] };
      });
      return next instanceof Response ? next : json(200, { group: saved, groups: next.groups });
    }
    if (b.action === 'delete') {
      const id = String(b.id || '');
      const next = await update(store, uid, 'groups', cur => ({ groups: cur.groups.filter(x => x.id !== id) }));
      return json(200, { groups: next.groups });
    }
    return fail(400, 'Unknown action.');
  }
  // prefs: known keys only, short strings, merged
  const given = b.prefs && typeof b.prefs === 'object' ? b.prefs : null;
  if (!given) return fail(400, 'No settings given.');
  const next = await update(store, uid, 'prefs', cur => {
    const prefs = { ...cur.prefs };
    for (const k of PREF_KEYS) {
      if (!(k in given)) continue;
      const v = given[k];
      if (v === null) delete prefs[k];
      else if (typeof v === 'string' && v.length <= 4000) prefs[k] = v;
    }
    return { prefs, updated: now() };
  });
  return json(200, next);
}
