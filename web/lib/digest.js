// FracView's watch-list digest by email (api/digest.js, run by a Vercel cron
// job once a day).
//
// For every account whose watch list asks for a daily or weekly email, when one
// is due: the earthquakes near its watched pads since the last digest (the BC
// Energy Regulator's catalogue, each pad's own reach and smallest magnitude) and
// the regulator's notices of frac jobs near them that are under way or about to
// start; sent only when there is something to say.
//
// Off until it is set up: the cron job's call must carry CRON_SECRET (Vercel
// sends it as a bearer token when the variable is set), and mail goes out only
// with RESEND_API_KEY and DIGEST_FROM (a sender address on a domain verified
// with Resend). Without them the job answers and sends nothing.
const BCER = 'https://geoweb-ags.bc-er.ca/arcgis/rest/services/';
const QUAKES = BCER + 'GEOLOGY/SEISMIC_EVENT_PT/MapServer/0/query';
const FRACS = BCER + 'WELL/HISTORIC_FRACTURING/FeatureServer/0/query';
const DUE_H = { daily: 20, weekly: 6.5 * 24 };
const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } });

const km = (a, b) => Math.hypot((a.lat - b.lat) * 111.32, (a.lon - b.lon) * 111.32 * Math.cos(a.lat * Math.PI / 180));
const stamp = d => d.toISOString().slice(0, 19).replace('T', ' ');
function nearest(pads, pt, ok) {
  let best = null;
  for (const p of pads) { const d = km(p, pt); if (d <= p.km && (!ok || ok(p)) && (!best || d < best.km)) best = { pad: p, km: d }; }
  return best;
}
function box(pads) {
  const r = Math.max(...pads.map(p => p.km)) / 111.32 + 0.02, k = Math.cos(pads[0].lat * Math.PI / 180);
  return [Math.min(...pads.map(p => p.lat)) - r, Math.max(...pads.map(p => p.lat)) + r,
          Math.min(...pads.map(p => p.lon)) - r / k, Math.max(...pads.map(p => p.lon)) + r / k];
}

// what is new near these pads since `since`
export async function news(pads, since, fetcher = fetch) {
  const [la0, la1, lo0, lo1] = box(pads), mn = Math.min(...pads.map(p => p.mag));
  const q1 = new URLSearchParams({ where: `EVENT_DATE_TIME > timestamp '${stamp(since)}' AND LATITUDE >= ${la0.toFixed(4)} AND LATITUDE <= ${la1.toFixed(4)} ` +
    `AND LONGITUDE >= ${lo0.toFixed(4)} AND LONGITUDE <= ${lo1.toFixed(4)} AND MAGNITUDE >= ${mn}`,
    outFields: 'EVENT_DATE_TIME,MAGNITUDE,LATITUDE,LONGITUDE,DEPTH_KM', returnGeometry: 'false', orderByFields: 'EVENT_DATE_TIME DESC', f: 'json' });
  const q2 = new URLSearchParams({ where: `OPS_EXPECTED_END_DATE >= timestamp '${stamp(since)}' AND OPS_EXPECTED_START_DATE <= timestamp '${stamp(new Date(Date.now() + 14 * 864e5))}'`,
    outFields: 'OPS_EXPECTED_START_DATE,OPS_EXPECTED_END_DATE,WA_NUM,WELL_NAME,OPERATOR_ABBREVIATION', geometry: `${lo0},${la0},${lo1},${la1}`,
    geometryType: 'esriGeometryEnvelope', inSR: '4326', outSR: '4326', spatialRel: 'esriSpatialRelIntersects', returnGeometry: 'true', f: 'json' });
  const [a, b] = await Promise.all([fetcher(QUAKES + '?' + q1).then(r => r.json()), fetcher(FRACS + '?' + q2).then(r => r.json())]);
  const quakes = (a.features || []).map(f => f.attributes).map(x => {
    const n = nearest(pads, { lat: x.LATITUDE, lon: x.LONGITUDE }, p => x.MAGNITUDE >= p.mag);
    return n && { t: new Date(x.EVENT_DATE_TIME).toISOString(), mag: x.MAGNITUDE, depth: x.DEPTH_KM, pad: n.pad.name, km: n.km };
  }).filter(Boolean);
  const fracs = (b.features || []).map(f => {
    const g = f.geometry || {}, n = g.y != null && nearest(pads, { lat: g.y, lon: g.x });
    const x = f.attributes;
    return n && { start: x.OPS_EXPECTED_START_DATE ? new Date(x.OPS_EXPECTED_START_DATE).toISOString().slice(0, 10) : '?',
                  end: x.OPS_EXPECTED_END_DATE ? new Date(x.OPS_EXPECTED_END_DATE).toISOString().slice(0, 10) : '?',
                  wa: x.WA_NUM, well: String(x.WELL_NAME || '').replace(/\s+/g, ' ').trim(), operator: x.OPERATOR_ABBREVIATION, pad: n.pad.name, km: n.km };
  }).filter(Boolean);
  return { quakes, fracs };
}

export function compose(name, w, n, since, site) {
  const lines = [`Hello ${name || 'there'},`, '', `What is new near the ${w.pads.length} pad${w.pads.length === 1 ? '' : 's'} you watch in FracView since ${since.toISOString().slice(0, 10)}:`, ''];
  if (n.quakes.length) {
    lines.push(`Earthquakes (BC Energy Regulator catalogue): ${n.quakes.length}, largest M${Math.max(...n.quakes.map(q => q.mag)).toFixed(2)}`);
    for (const q of n.quakes.slice(0, 15)) lines.push(`  M${q.mag.toFixed(2)}  ${q.t.slice(0, 16).replace('T', ' ')} UTC  ${q.km.toFixed(1)} km from ${q.pad}`);
    if (n.quakes.length > 15) lines.push(`  … and ${n.quakes.length - 15} more`);
    lines.push('');
  }
  if (n.fracs.length) {
    lines.push(`Frac jobs under way or starting within two weeks (BCER notices): ${n.fracs.length}`);
    for (const f of n.fracs.slice(0, 15)) lines.push(`  ${f.start} to ${f.end}  ${f.operator || ''}  ${f.well} (WA ${f.wa}), ${f.km.toFixed(1)} km from ${f.pad}`);
    lines.push('');
  }
  lines.push(`Open your watch list: ${site}/map.html (Menu › Watchlist)`, '', 'You get this because your FracView watch list asks for it; change it under Menu › Watchlist.');
  return { subject: `FracView: ${n.quakes.length} earthquake${n.quakes.length === 1 ? '' : 's'}${n.fracs.length ? ` and ${n.fracs.length} frac job${n.fracs.length === 1 ? '' : 's'}` : ''} near your pads`,
           text: lines.join('\n') };
}

// the cron job: every account's watch list, and the digests that are due
export async function run(request, env, blob) {
  // ?status=1: whether mail can go out at all (the Watchlist screen says so); nothing else
  if (new URL(request.url).searchParams.has('status'))
    return json(200, { configured: !!(env.CRON_SECRET && env.RESEND_API_KEY && env.DIGEST_FROM) });
  if (!env.CRON_SECRET) return json(503, { error: 'The digest is not set up (CRON_SECRET).' });
  if (request.headers.get('authorization') !== `Bearer ${env.CRON_SECRET}`) return json(401, { error: 'Not allowed.' });
  if (!env.RESEND_API_KEY || !env.DIGEST_FROM) return json(200, { sent: 0, note: 'No mail service is set up (RESEND_API_KEY, DIGEST_FROM).' });
  const site = env.SITE_URL || 'https://frac2csv-web.vercel.app';
  let cursor, sent = 0, checked = 0;
  const now = new Date();
  do {
    const page = await blob.list({ prefix: 'mine/', cursor, limit: 1000 });
    cursor = page.hasMore ? page.cursor : undefined;
    for (const b of page.blobs.filter(x => x.pathname.endsWith('/watch.json'))) {
      const uid = b.pathname.split('/')[1];
      const cur = await blob.read(b.pathname);
      const w = cur && cur.data;
      if (!w || !w.email || !DUE_H[w.digest] || !w.pads || !w.pads.length) continue;
      checked++;
      const last = w.lastDigest ? new Date(w.lastDigest) : new Date(now - DUE_H[w.digest] * 36e5);
      if (now - last < DUE_H[w.digest] * 36e5) continue;
      const acct = await blob.read(`users/${uid}.json`);
      if (!acct || acct.data.disabled || !acct.data.email) continue;
      const n = await news(w.pads, last);
      if (n.quakes.length || n.fracs.length) {
        const m = compose(acct.data.name, w, n, last, site);
        const r = await fetch('https://api.resend.com/emails', { method: 'POST', headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ from: env.DIGEST_FROM, to: [acct.data.email], subject: m.subject, text: m.text }) });
        if (!r.ok) { console.error('digest mail', r.status, await r.text().catch(() => '')); continue; }
        sent++;
      }
      try { await blob.write(b.pathname, { ...w, lastDigest: now.toISOString() }, { ifMatch: cur.etag }); } catch (e) { /* changed meanwhile: next run */ }
    }
  } while (cursor);
  return json(200, { sent, checked });
}
