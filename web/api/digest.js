// FracView: the watch-list email digest, called once a day by a Vercel cron job
// (vercel.json). lib/digest.js says what it does and what it needs set up.
// The sign-in middleware lets this path through; the cron secret guards it.
import { run } from '../lib/digest.js';
import { blobStore } from '../lib/saved-sessions.js';

export async function GET(request) {
  try {
    const { list } = await import('@vercel/blob');
    const store = await blobStore();
    return await run(request, process.env, { ...store, list: o => list(o) });
  } catch (e) {
    console.error('digest', e);
    return new Response(JSON.stringify({ error: 'The digest failed.' }), { status: 500, headers: { 'Content-Type': 'application/json' } });
  }
}
