// The printout under a WellSight log's curves, drawn in pieces ("tiles").
// Shared by the Lab's log pane and the stacked window (logstack.html).
//
// The stitched printout is one long page; the app renders the piece a view
// needs at the scale it needs. Zooming used to grey it out: every step of
// the slider asked for a fresh set of tiles at its own scale, they queued
// behind each other, and nothing was drawn until they came. So:
//   - one picture of the whole printout comes first and is drawn under
//     everything, so a tile that is not here yet shows a softer copy, never
//     grey; when it is sharp enough for the view, no tiles are asked for;
//   - scales are rounded up to steps of a quarter-octave, so a small zoom
//     reuses the tiles it has, drawn a little smaller;
//   - at most three are fetched at once, and a tile no longer on screen is
//     dropped from the queue, so the scale the zoom stopped at comes first;
//   - a tile that fails is asked for again, after a pause.
"use strict";
function WsTiles(onload) {
  const tiles = new Map();
  const queue = [];
  const MAX_INFLIGHT = 3, KEEP = 48, OV_LEN = 6000, OV_W = 480;
  let inflight = 0;

  function pump() {
    while (inflight < MAX_INFLIGHT && queue.length) {
      const t = queue.shift();
      if (!t.want) { tiles.delete(t.key); continue; }
      inflight++;
      t.img.onload = () => { inflight--; t.ok = true; t.busy = false; onload(); pump(); };
      t.img.onerror = () => {
        inflight--; t.busy = false; t.failed = Date.now();
        pump(); setTimeout(onload, 3100);         // draw again; the next frame retries
      };
      t.busy = true;
      t.img.src = t.url;
    }
  }
  function get(key, url, front) {
    let t = tiles.get(key);
    if (t && t.failed && Date.now() - t.failed > 3000) { tiles.delete(key); t = null; }
    if (!t) {
      t = { key, url, img: new Image(), ok: false, busy: false, failed: 0, want: true };
      tiles.set(key, t);
      if (front) queue.unshift(t); else queue.push(t);
    }
    t.want = true;
    tiles.delete(key); tiles.set(key, t);            // most recently used last
    return t;
  }
  function trim() {
    if (tiles.size <= KEEP) return;
    for (const [k, t] of tiles) {
      if (tiles.size <= KEEP) break;
      if (!t.want && !t.busy) tiles.delete(k);
    }
  }
  // the scale a tile is fetched at: the next quarter-octave up
  function level(ppm) { return Math.pow(2, Math.ceil(Math.log2(Math.max(ppm, 0.05)) * 4 - 1e-9) / 4); }

  // o: { id, P, d0, d1, X(depth) -> x, top, h, pxPerM, dpr, w }
  //   P is the printout info; the band runs depth across from X(d0) to X(d1)
  //   and is h tall; w is the band's height in device pixels when the
  //   printout is stretched to it, else 0 (its own proportions).
  function draw(g, o) {
    const P = o.P, top = P.top, bot = P.bottom;
    for (const t of tiles.values()) t.want = false;
    const a0 = Math.max(o.d0, top), b0 = Math.min(o.d1, bot);
    if (!(b0 > a0) || !(o.pxPerM > 0)) { finish(); return; }
    const base = `/api/wellsight-strip?id=${encodeURIComponent(o.id)}`;
    const rev = (P.file || "") + ":" + P.height_pt;
    // the whole printout, once: the long side at most OV_LEN pixels
    const ovPpm = Math.min(400, OV_LEN / Math.max(1, bot - top));
    const ov = get(`${o.id}:${rev}:ov`, `${base}&d0=${top}&d1=${bot}&ppm=${ovPpm.toFixed(4)}&w=${OV_W}`, true);
    // a picture covering depths a..b, turned a quarter left: depth runs across
    const blit = (img, a, b, sy0, sy1) => {
      g.save();
      g.translate(o.X(a), o.top + o.h);
      g.rotate(-Math.PI / 2);
      if (sy0 == null) g.drawImage(img, 0, 0, o.h, (b - a) * o.pxPerM);
      else g.drawImage(img, 0, sy0, img.naturalWidth, sy1 - sy0, 0, 0, o.h, (b - a) * o.pxPerM);
      g.restore();
    };
    if (ov.ok) {
      const H = ov.img.naturalHeight, f = d => (d - top) / (bot - top) * H;
      blit(ov.img, a0, b0, f(a0), f(b0));
    } else {
      g.fillStyle = "#f4f5f7";
      g.fillRect(o.X(a0), o.top, (b0 - a0) * o.pxPerM, o.h);
    }
    const ppmDev = o.pxPerM * o.dpr;
    const acrossDev = o.w || o.h * o.dpr;
    // sharp enough already: no tiles
    if (ov.ok && ppmDev <= ovPpm * 1.05 && acrossDev <= OV_W * 1.05) { finish(); return; }
    const L = level(ppmDev);
    const T = 1024 / L;                                   // metres per tile, ~1024 px long
    const wq = o.w ? `&w=${Math.round(o.w)}` : "";
    for (let k = Math.floor((a0 - top) / T); top + k * T < b0; k++) {
      const a = top + k * T, b = Math.min(a + T, bot);
      const t = get(`${o.id}:${rev}:${L}:${o.w || 0}:${k}`,
                    `${base}&d0=${a.toFixed(3)}&d1=${b.toFixed(3)}&ppm=${L.toFixed(4)}${wq}`);
      if (t.ok) blit(t.img, a, b);
    }
    finish();
  }
  function finish() {
    // queued tiles nobody wants any more go; the rest are fetched in order
    for (let i = queue.length - 1; i >= 0; i--)
      if (!queue[i].want) { tiles.delete(queue[i].key); queue.splice(i, 1); }
    trim();
    pump();
  }
  return { draw };
}
