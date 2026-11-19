// FracView — drop a Photon well export (.pha) on the map to see its wells.
//
// The file is read in this browser (pha-worker.js, pha.js) and its wells kept
// here (drop-store.js): nothing is uploaded. They join the map as "Your
// files", open in 3D, the wine rack and the well section like any other pad,
// and stay until removed from the legend's list.
(() => {
'use strict';
if (!window.StratumDrop || typeof map === 'undefined') return;
const SD = window.StratumDrop;
const fmt = v => Number(v || 0).toLocaleString();

// ---------- styles ----------
const css = document.createElement('style');
css.textContent = `
  .dr-files { margin-top:6px; display:flex; flex-direction:column; gap:3px; max-width:250px; }
  .dr-files:empty { display:none; }
  .dr-file { display:flex; align-items:center; gap:6px; color:var(--ink); font-size:11.5px; }
  .dr-file .dr-name { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; cursor:pointer; }
  .dr-file .dr-name:hover { color:var(--hov); }
  .dr-file .dr-n { color:var(--mut); font-family:var(--mono); white-space:nowrap; }
  .dr-file button { background:none; border:1px solid transparent; color:var(--mut); border-radius:6px; padding:0 5px; font:600 13px/1.2 sans-serif; cursor:pointer; }
  .dr-file button:hover, .dr-file button:focus-visible { border-color:var(--btn-line); color:var(--ink); }
  .dr-note { color:var(--mut); font-size:11px; max-width:250px; }
  .dr-over { position:fixed; inset:0; z-index:40; display:grid; place-items:center; background:color-mix(in srgb, var(--page) 70%, transparent);
             pointer-events:none; }
  .dr-over[hidden] { display:none; }
  .dr-over div { border:2px dashed var(--hov); border-radius:16px; padding:28px 34px; background:var(--panel); color:var(--ink);
                 font:600 16px/1.4 -apple-system,Segoe UI,Roboto,sans-serif; text-align:center; box-shadow:0 0 0 6px var(--glow); max-width:min(440px, 86vw); }
  .dr-over small { display:block; margin-top:6px; color:var(--mut); font-weight:400; font-size:12.5px; }
  .dr-toast { position:fixed; left:50%; bottom:28px; transform:translateX(-50%); z-index:30; max-width:min(560px, calc(100vw - 24px));
              background:var(--panel); color:var(--ink); border:1px solid var(--hov); border-radius:12px; box-shadow:0 10px 30px var(--shadow), 0 0 0 3px var(--glow);
              padding:10px 12px 10px 14px; font:13px/1.4 -apple-system,Segoe UI,Roboto,sans-serif; display:flex; gap:10px; align-items:center; }
  .dr-toast[hidden] { display:none; }
  .dr-toast.err { border-color:#d6336c; box-shadow:0 10px 30px var(--shadow), 0 0 0 3px #d6336c33; }
  .dr-toast .dr-msg { flex:1; }
  .dr-toast .dr-bar { height:4px; border-radius:2px; background:var(--line); margin-top:6px; overflow:hidden; }
  .dr-toast .dr-bar i { display:block; height:100%; width:0; background:var(--hov); transition:width .2s; }
  .dr-toast button { background:var(--btn); color:var(--ink); border:1px solid var(--btn-line); border-radius:7px; padding:5px 10px; font:600 12.5px sans-serif; cursor:pointer; }
  .dr-toast button:hover { border-color:var(--hov); }
  body.ws-docked .dr-toast { bottom:calc(var(--ws-h, 42vh) + 16px); }`;
document.head.append(css);

// ---------- the legend's button and list ----------
const legend = document.querySelector('.legend');
const btn = document.createElement('button');
btn.type = 'button'; btn.className = 'gm-btn'; btn.id = 'dr-open';
btn.title = 'Put the wells of a Photon well export (.pha) on the map. It is read in this browser: nothing is uploaded.';
btn.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path d="M12 15V4m0 0-4 4m4-4 4 4M5 15v4h14v-4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg> Load wells from a .pha file…';
const input = document.createElement('input');
input.type = 'file'; input.accept = '.pha,.PHA'; input.multiple = true; input.hidden = true;
const list = document.createElement('div');
list.className = 'dr-files';
const note = document.createElement('div');
note.className = 'dr-note';
note.textContent = 'or drop one on the map';
if (legend) legend.append(btn, input, note, list);
btn.addEventListener('click', () => input.click());
input.addEventListener('change', () => { const fs = [...input.files]; input.value = ''; run(fs); });

function renderList(st) {
  list.replaceChildren();
  for (const d of (st && st.drops) || []) {
    const row = document.createElement('div');
    row.className = 'dr-file';
    const name = document.createElement('span');
    name.className = 'dr-name'; name.textContent = d.name; name.title = `Show ${d.name}'s wells`;
    name.addEventListener('click', () => fit(d.bounds));
    const n = document.createElement('span');
    n.className = 'dr-n'; n.textContent = fmt(d.wells) + ' wells';
    const x = document.createElement('button');
    x.type = 'button'; x.textContent = '×'; x.title = `Remove ${d.name}'s wells from this browser`; x.setAttribute('aria-label', x.title);
    x.addEventListener('click', async () => { x.disabled = true; try { await SD.remove(d.n); toast(`Removed ${d.name}'s wells.`); } catch (e) { toast('Could not remove them: ' + e.message, { err: true }); x.disabled = false; } });
    row.append(name, n, x);
    list.append(row);
  }
  note.textContent = st && st.drops.length ? 'Kept in this browser only · drop another on the map' : 'or drop one on the map';
}
SD.ready.then(renderList).catch(() => {});
addEventListener('stratum:dropped', e => renderList(e.detail));

// ---------- the toast ----------
const box = document.createElement('div');
box.className = 'dr-toast'; box.hidden = true; box.setAttribute('role', 'status'); box.setAttribute('aria-live', 'polite');
box.innerHTML = '<div class="dr-msg"><span></span><div class="dr-bar" hidden><i></i></div></div>';
const close = document.createElement('button');
close.type = 'button'; close.textContent = 'Close';
close.addEventListener('click', () => { box.hidden = true; });
document.body.append(box);
let hideT = 0;
function toast(msg, o = {}) {
  clearTimeout(hideT);
  box.hidden = false; box.classList.toggle('err', !!o.err);
  box.querySelector('.dr-msg span').textContent = msg;
  const bar = box.querySelector('.dr-bar');
  bar.hidden = o.f == null;
  if (o.f != null) bar.firstChild.style.width = Math.round(o.f * 100) + '%';
  [...box.querySelectorAll(':scope > button')].forEach(b => b.remove());
  for (const a of o.acts || []) {
    const b = document.createElement('button');
    b.type = 'button'; b.textContent = a.t; b.addEventListener('click', () => { a.f(); box.hidden = true; });
    box.append(b);
  }
  if (o.f == null) box.append(close);
  if (o.hide) hideT = setTimeout(() => { box.hidden = true; }, o.hide);
}

function fit(bounds) {
  if (!bounds) return;
  const [[x0, y0], [x1, y1]] = bounds;
  const side = document.querySelector('.side');
  const left = side && innerWidth > 760 ? side.getBoundingClientRect().right + 20 : 40;
  map.fitBounds([[x0, y0], [x1, y1]], { padding: { top: 60, bottom: 60, left, right: 60 }, maxZoom: 13.5, duration: 900 });
}

// ---------- reading a file ----------
const isPha = async f => /\.pha$/i.test(f.name) || /struct\s+WELL\b/.test(await f.slice(0, 65536).text());
let busy = false;
async function run(files) {
  if (busy) { toast('Still reading the last file: drop this one again when it is done.', { hide: 5000 }); return; }
  busy = true;
  try { for (const f of files) await one(f); } finally { busy = false; }
}

function one(file) {
  return new Promise(async resolve => {
    if (!(await isPha(file))) { toast(`${file.name} is not a Photon well export (.pha).`, { err: true }); resolve(); return; }
    // the same file again: it replaces the one kept before
    const st = await SD.ready;
    const old = st.drops.filter(d => d.name === file.name && d.size === file.size);
    const n = await SD.next();
    let worker;
    try { worker = new Worker('pha-worker.js'); } catch (e) { toast('This browser cannot read the file here: ' + e.message, { err: true }); resolve(); return; }
    toast(`Opening ${file.name}…`, { f: 0 });
    worker.onmessage = async e => {
      const m = e.data;
      if (m.type === 'progress') { toast(`${m.phase} ${file.name}…`, { f: m.phase === 'Reading' ? m.f * 0.85 : m.phase === 'Opening' ? 0.02 : 0.9 }); return; }
      worker.terminate();
      if (m.type === 'error') { toast(`${file.name}: ${m.message}`, { err: true }); resolve(); return; }
      const r = m.result;
      try {
        toast(`Keeping ${fmt(r.report.placed)} wells in this browser…`, { f: 0.95 });
        await SD.add(n, { name: file.name, size: file.size, modified: file.lastModified }, r);
        for (const d of old) await SD.remove(d.n);
      } catch (err) {
        toast(`Could not keep ${file.name}'s wells in this browser (${err.message || err}). Its storage may be full or switched off.`, { err: true });
        resolve(); return;
      }
      const R = r.report, left = R['no location'] + R['no depth'];
      const bits = [`${fmt(R.placed)} wells on ${fmt(R.pads)} pads`,
        R.surveyed ? `${fmt(R.surveyed)} with a survey` : null,
        R.estimated ? `${fmt(R.estimated)} drawn from surface to bottom hole (no survey)` : null,
        R['with stages'] ? `${fmt(R['with stages'])} with frac stages` : null,
        left ? `${fmt(left)} left out (no location or depth)` : null].filter(Boolean);
      toast(`${file.name}: ${bits.join(' · ')}.`, { acts: [{ t: 'Show them', f: () => fit(r.bounds) }] });
      fit(r.bounds);
      resolve();
    };
    worker.onerror = e => { worker.terminate(); toast(`${file.name}: ${e.message || 'could not be read'}`, { err: true }); resolve(); };
    worker.postMessage({ file, n, name: file.name });
  });
}

// ---------- dropping ----------
const over = document.createElement('div');
over.className = 'dr-over'; over.hidden = true;
over.innerHTML = '<div>Drop a Photon well export (.pha) to put its wells on the map<small>Read in this browser and kept here: nothing is uploaded.</small></div>';
document.body.append(over);
const hasFiles = e => !!e.dataTransfer && [...(e.dataTransfer.types || [])].includes('Files');
let depth = 0;
addEventListener('dragenter', e => { if (!hasFiles(e)) return; e.preventDefault(); depth++; over.hidden = false; });
addEventListener('dragover', e => { if (!hasFiles(e)) return; e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; });
addEventListener('dragleave', e => { if (!hasFiles(e)) return; depth = Math.max(0, depth - 1); if (!depth) over.hidden = true; });
addEventListener('drop', e => {
  if (!hasFiles(e)) return;
  e.preventDefault(); depth = 0; over.hidden = true;
  const fs = [...e.dataTransfer.files];
  if (fs.length) run(fs);
});
})();
