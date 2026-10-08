// Stratum is private: every page, every data file and the extractor need a
// signed-in user. Runs before anything is served (Vercel Routing Middleware),
// so the well data cannot be fetched around the sign-in page. Only the sign-in
// page itself and the account API are open, and the daily watch-list digest,
// which the cron job's own secret guards (lib/digest.js).
//
// The cookie is checked by its signature on every request. Once an hour of use
// the account itself is looked up too, and the cookie renewed: an account an
// admin removes is shut out within the hour, and a role change takes effect.
import { next } from '@vercel/functions';
import { get } from '@vercel/blob';
import { readCookie, verify, sign, setCookie, clearCookie, userPath, MAX_AGE } from './lib/session.js';

const OPEN = new Set(['/login.html', '/login.css', '/login.js', '/favicon.ico', '/api/auth', '/api/digest']);
const RECHECK_S = 3600;

async function account(email) {
  const r = await get(await userPath(email), { access: 'private', useCache: false });
  if (!r || r.statusCode !== 200 || !r.stream) return null;
  const u = JSON.parse(await new Response(r.stream).text());
  return u && !u.disabled ? u : null;
}

function refuse(request, url, signedOut) {
  const extra = signedOut ? { 'Set-Cookie': clearCookie() } : {};
  // a page: to the sign-in page, which comes back here afterwards
  if (request.method === 'GET' && (request.headers.get('accept') || '').includes('text/html')) {
    const to = new URL('/login.html', url);
    to.searchParams.set('next', url.pathname + url.search);
    return new Response(null, { status: 302, headers: { Location: to.pathname + to.search, 'Cache-Control': 'no-store', ...extra } });
  }
  // data, scripts, the extractor's API: refused
  return new Response('Sign in to FracView first.', { status: 401, headers: { 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store', ...extra } });
}

export default async function middleware(request) {
  const url = new URL(request.url);
  if (OPEN.has(url.pathname)) return next();
  const secret = process.env.SESSION_SECRET;
  const s = await verify(readCookie(request.headers.get('cookie')), secret);
  if (!s) return refuse(request, url, false);
  const t = Math.floor(Date.now() / 1000);
  if (t - (s.chk || s.iat || 0) < RECHECK_S) return next();
  let u;
  try { u = await account(s.email); }
  catch (e) { return next(); }                   // the store unreachable: the signature still stands
  if (!u) return refuse(request, url, true);
  const token = await sign({ ...s, name: u.name, role: u.role, chk: t, exp: t + MAX_AGE }, secret);
  return next({ headers: { 'Set-Cookie': setCookie(token) } });
}
