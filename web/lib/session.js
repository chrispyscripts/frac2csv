// Stratum's sign-in cookie: a signed, expiring statement of who is signed in.
// `<payload>.<signature>`, both base64url; the signature is HMAC-SHA256 under
// SESSION_SECRET (a Vercel environment variable). Shared by the middleware,
// which checks it on every request, and api/auth.js, which issues it. Web
// Crypto only, so it runs at the edge and in Node alike.
export const COOKIE = '__Host-stratum';
export const MAX_AGE = 14 * 24 * 3600;            // seconds; renewed daily while in use

const enc = new TextEncoder(), dec = new TextDecoder();
const b64u = bytes => btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const unb64u = s => Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0));

let cached = null;
async function hmacKey(secret) {
  if (!cached || cached.secret !== secret) {
    cached = { secret, key: await crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign', 'verify']) };
  }
  return cached.key;
}

export async function sign(payload, secret) {
  if (!secret) throw Error('SESSION_SECRET is not set');
  const body = b64u(enc.encode(JSON.stringify(payload)));
  return body + '.' + b64u(await crypto.subtle.sign('HMAC', await hmacKey(secret), enc.encode(body)));
}

// the payload when the token is genuine and unexpired, otherwise null
export async function verify(token, secret) {
  if (!secret || typeof token !== 'string' || token.length > 4096) return null;
  const [body, sig, extra] = token.split('.');
  if (!body || !sig || extra !== undefined) return null;
  try {
    if (!await crypto.subtle.verify('HMAC', await hmacKey(secret), unb64u(sig), enc.encode(body))) return null;
    const p = JSON.parse(dec.decode(unb64u(body)));
    return p && typeof p.exp === 'number' && p.exp * 1000 > Date.now() ? p : null;
  } catch (e) {
    return null;
  }
}

export function readCookie(header, name = COOKIE) {
  for (const part of String(header || '').split(';')) {
    const i = part.indexOf('=');
    if (i > 0 && part.slice(0, i).trim() === name) return part.slice(i + 1).trim();
  }
  return null;
}

export const setCookie = token => `${COOKIE}=${token}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${MAX_AGE}`;
export const clearCookie = () => `${COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0`;

// where an account lives in the private store: users/<sha256 of the email>.json
// (api/auth.js names it the same way, with Node's hash)
export async function userPath(email) {
  const h = new Uint8Array(await crypto.subtle.digest('SHA-256', enc.encode(email)));
  return `users/${Array.from(h, b => b.toString(16).padStart(2, '0')).join('')}.json`;
}
