// FracView: share links for saved sessions, at /api/share (lib/shares.js says
// what it does). Behind the sign-in like every page.
import { handle } from '../lib/shares.js';
import { blobStore } from '../lib/saved-sessions.js';

async function route(request) {
  try { return await handle(request, await blobStore(), process.env.SESSION_SECRET); }
  catch (e) {
    console.error('share', e);
    return new Response(JSON.stringify({ error: 'That could not be reached. Try again in a moment.' }),
      { status: 500, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } });
  }
}
export const GET = route;
export const POST = route;
