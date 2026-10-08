// FracView: an account's groups, settings and watch list, at /api/mine?k=groups|prefs|watch
// (lib/account-docs.js says what it does). Behind the sign-in like every page,
// and it serves only the account the cookie is signed for.
import { handle } from '../lib/account-docs.js';
import { blobStore } from '../lib/saved-sessions.js';

async function route(request) {
  try { return await handle(request, await blobStore(), process.env.SESSION_SECRET); }
  catch (e) {
    console.error('mine', e);
    return new Response(JSON.stringify({ error: 'That could not be reached. Try again in a moment.' }),
      { status: 500, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } });
  }
}
export const GET = route;
export const POST = route;
