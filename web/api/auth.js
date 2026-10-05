// Stratum accounts, one function: /api/auth?a=<action>.
//
//   GET  me                     who is signed in (renews the cookie daily)
//   POST login   {email, password}
//   POST signup  {code, name, email, password}   an invite code makes an account;
//                                                a reset code sets a new password
//   POST logout
//   admin only:
//   GET  invites | users
//   POST invite  {note, role, uses, days}        a new invite code
//   POST revoke  {code}
//   POST reset   {email}                         a one-time password-reset code
//   POST remove  {email}
//
// Accounts and codes are JSON in a private Vercel Blob store (BLOB_READ_WRITE_TOKEN):
// users/<sha256 of email>.json and invites/<code>.json. Passwords are scrypt hashes.
// The very first account comes from STRATUM_BOOTSTRAP_CODE, an admin code that
// only works while no account exists.
import { get, put, del, list, BlobPreconditionFailedError } from '@vercel/blob';
import { createHash, randomBytes, randomInt, scrypt as scryptCb, timingSafeEqual } from 'node:crypto';
import { promisify } from 'node:util';
import { sign, verify, readCookie, setCookie, clearCookie, MAX_AGE } from '../lib/session.js';

const scrypt = promisify(scryptCb);
const N = 32768, R = 8, P = 1, KEYLEN = 64;
const CODE_ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';   // Crockford: no I, L, O, U

// ---------- small things ----------
const json = (status, body, headers = {}) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', ...headers } });
const fail = (status, error, headers) => json(status, { error }, headers);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const now = () => new Date().toISOString();
const normEmail = e => {
  const s = String(e || '').trim().toLowerCase();
  return s.length <= 200 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s) ? s : null;
};
// codes read the way people type them: case, spaces and dashes ignored, O→0, I/L→1
const normCode = c => String(c || '').toUpperCase().replace(/O/g, '0').replace(/[IL]/g, '1').replace(/[^0-9A-Z]/g, '').slice(0, 40);
const showCode = c => c.replace(/(.{4})(?=.)/g, '$1-');
const newCode = () => Array.from({ length: 12 }, () => CODE_ALPHABET[randomInt(CODE_ALPHABET.length)]).join('');
const userId = email => createHash('sha256').update(email).digest('hex');
const userPath = email => `users/${userId(email)}.json`;
const invitePath = code => `invites/${code}.json`;
const publicUser = u => ({ name: u.name, email: u.email, role: u.role, created: u.created, lastLogin: u.lastLogin || null });

// ---------- storage ----------
async function read(path) {
  const r = await get(path, { access: 'private', useCache: false });
  if (!r || r.statusCode !== 200 || !r.stream) return null;
  return { data: JSON.parse(await new Response(r.stream).text()), etag: r.blob.etag };
}
function write(path, data, { create = false, ifMatch } = {}) {
  return put(path, JSON.stringify(data), { access: 'private', contentType: 'application/json', addRandomSuffix: false,
    allowOverwrite: !create, cacheControlMaxAge: 60, ...(ifMatch ? { ifMatch } : {}) });
}
async function readAll(prefix) {
  const out = [];
  let cursor;
  do {
    const page = await list({ prefix, cursor, limit: 1000 });
    // read side by side, a batch at a time
    for (let i = 0; i < page.blobs.length; i += 16) {
      const got = await Promise.all(page.blobs.slice(i, i + 16).map(b => read(b.pathname).catch(() => null)));
      for (const x of got) if (x) out.push(x.data);
    }
    cursor = page.hasMore ? page.cursor : null;
  } while (cursor);
  return out;
}

// ---------- passwords ----------
const passwordProblem = pw => typeof pw !== 'string' || pw.length < 10 ? 'Use a password of at least 10 characters.'
  : pw.length > 200 ? 'That password is too long.' : null;
async function hashPassword(pw) {
  const salt = randomBytes(16);
  const key = await scrypt(pw.normalize('NFKC'), salt, KEYLEN, { N, r: R, p: P, maxmem: 256 * N * R });
  return `scrypt$${N}$${R}$${P}$${salt.toString('base64')}$${key.toString('base64')}`;
}
const DUMMY_HASH = `scrypt$${N}$${R}$${P}$${Buffer.alloc(16).toString('base64')}$${Buffer.alloc(KEYLEN).toString('base64')}`;
async function checkPassword(pw, stored) {
  const [kind, n, r, p, salt, key] = String(stored || '').split('$');
  if (kind !== 'scrypt' || typeof pw !== 'string') return false;
  const want = Buffer.from(key, 'base64');
  const got = await scrypt(pw.normalize('NFKC'), Buffer.from(salt, 'base64'), want.length, { N: +n, r: +r, p: +p, maxmem: 256 * +n * +r });
  return got.length === want.length && timingSafeEqual(got, want);
}

// ---------- sessions ----------
async function issue(user) {
  const t = Math.floor(Date.now() / 1000);
  return setCookie(await sign({ sub: userId(user.email), email: user.email, name: user.name, role: user.role, iat: t, chk: t, exp: t + MAX_AGE },
    process.env.SESSION_SECRET));
}
const session = request => verify(readCookie(request.headers.get('cookie')), process.env.SESSION_SECRET);
// the signed-in account as stored now: a removed account is signed out
async function currentUser(request) {
  const s = await session(request);
  if (!s) return { s: null, u: null };
  const u = await read(userPath(s.email));
  return { s, u: u && !u.data.disabled ? u : null };
}
async function requireAdmin(request) {
  const { u } = await currentUser(request);
  return u && u.data.role === 'admin' ? u.data : null;
}

// ---------- invites ----------
function inviteProblem(inv) {
  if (!inv) return 'That code isn’t valid. Check it, or ask for a new one.';
  if (inv.revoked) return 'That code has been withdrawn. Ask for a new one.';
  if (inv.expires && Date.parse(inv.expires) < Date.now()) return 'That code has expired. Ask for a new one.';
  if ((inv.used || []).length >= (inv.uses || 1)) return 'That code has already been used. Ask for a new one.';
  return null;
}
const inviteStatus = inv => inv.revoked ? 'withdrawn' : inv.expires && Date.parse(inv.expires) < Date.now() ? 'expired'
  : (inv.used || []).length >= (inv.uses || 1) ? 'used' : 'open';

// ---------- actions ----------
async function signup(b) {
  const code = normCode(b.code), email = normEmail(b.email), name = String(b.name || '').trim().slice(0, 80);
  if (!code) return fail(400, 'Enter the invite or reset code you were given.');
  if (!email) return fail(400, 'Enter a valid email address.');
  const pwBad = passwordProblem(b.password); if (pwBad) return fail(400, pwBad);

  // the first admin: a code set in Vercel, good only while there is no account at all
  const boot = process.env.STRATUM_BOOTSTRAP_CODE && code === normCode(process.env.STRATUM_BOOTSTRAP_CODE);
  let inv = null;
  if (boot) {
    const [{ blobs }, used] = await Promise.all([list({ prefix: 'users/', limit: 1 }), read(invitePath('_bootstrap'))]);
    if (blobs.length || used) return fail(403, 'That code has already been used. Ask an admin for an invite.');
  } else {
    inv = await read(invitePath(code));
    const bad = inviteProblem(inv && inv.data); if (bad) { await sleep(300); return fail(403, bad); }
  }
  const kind = boot ? 'invite' : inv.data.kind;

  let user;
  if (kind === 'reset') {
    if (email !== inv.data.email) return fail(403, 'That reset code was made for a different email address.');
    const cur = await read(userPath(email));
    if (!cur) return fail(404, 'There is no account for that email any more. Ask for an invite.');
    user = { ...cur.data, hash: await hashPassword(b.password), passwordSet: now() };
    await write(userPath(email), user, { ifMatch: cur.etag });
  } else {
    if (!name) return fail(400, 'Enter your name.');
    user = { name, email, role: boot ? 'admin' : inv.data.role === 'admin' ? 'admin' : 'user', created: now(),
             hash: await hashPassword(b.password), invite: boot ? 'first admin' : showCode(code), invitedBy: boot ? null : inv.data.by };
    try { await write(userPath(email), user, { create: true }); }
    catch (e) { return fail(409, 'There is already an account for that email. Sign in, or ask an admin for a reset code.'); }
  }

  // the code is spent: conditionally, so two people cannot spend one use at once
  try {
    if (boot) await write(invitePath('_bootstrap'), { used: [{ email, at: now() }] }, { create: true });
    else {
      const spent = { ...inv.data, used: [...(inv.data.used || []), { email, at: now(), kind }] };
      await write(invitePath(code), spent, { ifMatch: inv.etag });
    }
  } catch (e) {
    if (kind !== 'reset') await del(userPath(email)).catch(() => {});
    if (e instanceof BlobPreconditionFailedError || boot) return fail(409, 'That code was used by someone else just now. Ask for a new one.');
    throw e;
  }
  user.lastLogin = now();
  await write(userPath(email), user).catch(() => {});
  return json(200, { user: publicUser(user) }, { 'Set-Cookie': await issue(user) });
}

async function login(b) {
  const email = normEmail(b.email);
  const cur = email ? await read(userPath(email)) : null;
  // the same work and the same answer whether or not the account exists
  const ok = await checkPassword(String(b.password || ''), cur ? cur.data.hash : DUMMY_HASH);
  if (!ok || !cur || cur.data.disabled) { await sleep(400); return fail(401, 'That email and password don’t match an account.'); }
  const user = { ...cur.data, lastLogin: now() };
  await write(userPath(email), user).catch(() => {});
  return json(200, { user: publicUser(user) }, { 'Set-Cookie': await issue(user) });
}

async function admin(action, request, b) {
  const me = await requireAdmin(request);
  if (!me) return fail(403, 'Only an admin can do that.');
  if (action === 'invites') {
    const all = (await readAll('invites/')).filter(i => i.code)
      .map(i => ({ code: showCode(i.code), kind: i.kind, role: i.role, note: i.note || '', email: i.email || null, uses: i.uses || 1,
                   used: i.used || [], created: i.created, by: i.by, expires: i.expires || null, status: inviteStatus(i) }))
      .sort((x, y) => String(y.created).localeCompare(String(x.created)));
    return json(200, { invites: all });
  }
  if (action === 'users') {
    const all = (await readAll('users/')).map(u => ({ ...publicUser(u), invite: u.invite || null, invitedBy: u.invitedBy || null }))
      .sort((x, y) => String(x.created).localeCompare(String(y.created)));
    return json(200, { users: all, me: me.email });
  }
  if (request.method !== 'POST') return fail(405, 'Use POST.');
  if (action === 'invite' || action === 'reset') {
    let email = null;
    if (action === 'reset') {
      email = normEmail(b.email);
      if (!email || !await read(userPath(email))) return fail(404, 'No account has that email.');
    }
    const days = Math.max(1, Math.min(90, Math.round(+b.days || (action === 'reset' ? 3 : 14))));
    const inv = { code: newCode(), kind: action === 'reset' ? 'reset' : 'invite', role: action === 'invite' && b.role === 'admin' ? 'admin' : 'user',
                  email, note: String(b.note || '').trim().slice(0, 120) || (email ? `password reset for ${email}` : ''),
                  uses: action === 'reset' ? 1 : Math.max(1, Math.min(50, Math.round(+b.uses || 1))), used: [],
                  created: now(), by: me.email, expires: new Date(Date.now() + days * 864e5).toISOString() };
    await write(invitePath(inv.code), inv, { create: true });
    return json(200, { code: showCode(inv.code), expires: inv.expires, kind: inv.kind });
  }
  if (action === 'revoke') {
    const code = normCode(b.code), cur = code ? await read(invitePath(code)) : null;
    if (!cur) return fail(404, 'No such code.');
    await write(invitePath(code), { ...cur.data, revoked: true, revokedBy: me.email, revokedAt: now() }, { ifMatch: cur.etag });
    return json(200, { ok: true });
  }
  if (action === 'remove') {
    const email = normEmail(b.email);
    if (!email) return fail(400, 'No email given.');
    if (email === me.email) return fail(400, 'You can’t remove your own account here.');
    if (!await read(userPath(email))) return fail(404, 'No account has that email.');
    await del(userPath(email));
    return json(200, { ok: true });
  }
  return fail(404, 'Unknown action.');
}

async function route(request) {
  const action = new URL(request.url).searchParams.get('a') || '';
  if (request.method === 'POST') {
    // a form on another site cannot act as a signed-in user
    const origin = request.headers.get('origin');
    if (origin && new URL(origin).host !== new URL(request.url).host) return fail(403, 'Cross-site request refused.');
  }
  let b = {};
  if (request.method === 'POST') { try { b = await request.json(); } catch (e) { b = {}; } if (!b || typeof b !== 'object') b = {}; }

  if (action === 'me') {
    const { s, u } = await currentUser(request);
    if (!s || !u) return fail(401, 'Signed out.', s ? { 'Set-Cookie': clearCookie() } : {});
    const renew = Date.now() / 1000 - (s.iat || 0) > 86400 ? { 'Set-Cookie': await issue(u.data) } : {};
    return json(200, { user: publicUser(u.data) }, renew);
  }
  if (request.method === 'POST' && action === 'logout') return json(200, { ok: true }, { 'Set-Cookie': clearCookie() });
  if (request.method === 'POST' && action === 'login') return login(b);
  if (request.method === 'POST' && action === 'signup') return signup(b);
  return admin(action, request, b);
}

async function handle(request) {
  try { return await route(request); }
  catch (e) { console.error('auth', e); return fail(500, 'Something went wrong. Try again in a moment.'); }
}
export const GET = handle;
export const POST = handle;
