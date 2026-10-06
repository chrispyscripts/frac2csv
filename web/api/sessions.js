// FracView: each account's saved sessions, at /api/sessions (lib/saved-sessions.js
// says what it does). Behind the sign-in like every page (middleware.js), and it
// checks the cookie itself too: the account it serves is the one signed in.
import { handle, blobStore } from '../lib/saved-sessions.js';

async function route(request) {
  try { return await handle(request, await blobStore(), process.env.SESSION_SECRET); }
  catch (e) {
    console.error('sessions', e);
    return new Response(JSON.stringify({ error: 'Your saved sessions could not be reached. Try again in a moment.' }),
      { status: 500, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } });
  }
}
export const GET = route;
export const POST = route;
