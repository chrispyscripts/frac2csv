// Gamma ray colour schemes, one choice for every view (the 3D view, the wine
// rack, the well section). Each runs from low API (cleaner rock) to high API
// (shalier), and every step stays visible on FracView's dark ground (at least
// 2.3:1 against it, so a low reading never reads as a missing one).
//
//   Amber        one hue, dark to cream: the quiet default
//   Viridis      blue to green to yellow, evenly spaced to the eye, colour-blind safe
//   Sand → shale the log convention: clean sand yellow, shale grey-green
//   Cool → warm  diverging on the lateral median: blue cleaner than usual,
//                grey typical, red shalier -- the one that makes outliers jump
//
// The choice is a setting (localStorage stratum.gammaPalette), so it carries
// across windows, reloads and saved sessions; a change fires
// `stratum:gammapalette` on window here and in every other open FracView window.
(() => {
'use strict';
const KEY = 'stratum.gammaPalette';
const PALETTES = {
  amber:     { name: 'Amber', stops: ['#92500b', '#ac5c00', '#c36c00', '#d57f00', '#e29500', '#eaad4a', '#eec57e', '#f2dcb1', '#fef1d0'] },
  viridis:   { name: 'Viridis', stops: ['#3b528b', '#31688e', '#287c8e', '#20908d', '#22a785', '#3dbc74', '#73d056', '#b8de29', '#fde725'] },
  sandshale: { name: 'Sand → shale', stops: ['#fff3a3', '#f3da55', '#d7c13c', '#a8b443', '#749f4e', '#4f895c', '#477266', '#56646f'] },
  coolwarm:  { name: 'Cool → warm', stops: ['#3a6fd8', '#5b93f5', '#93b6f2', '#c2cddb', '#cdd2d6', '#eec0a7', '#f2906b', '#e75c47', '#cc3639'], diverging: true },
};
const rgb = h => [1, 3, 5].map(j => parseInt(h.slice(j, j + 2), 16));
function current() {
  let id = 'amber';
  try { id = localStorage.getItem(KEY) || id; } catch (e) { /* private mode */ }
  return PALETTES[id] ? id : 'amber';
}
// n evenly spaced colours along the palette
function steps(n, id = current()) {
  const s = PALETTES[id].stops;
  return Array.from({ length: n }, (_, k) => {
    const t = n > 1 ? k / (n - 1) * (s.length - 1) : 0, i = Math.min(s.length - 2, Math.floor(t)), f = t - i, a = rgb(s[i]), b = rgb(s[i + 1]);
    return `rgb(${a.map((x, j) => Math.round(x + (b[j] - x) * f)).join(',')})`;
  });
}
// where a reading sits on the scale, 0..1: straight from lo to hi, or for a
// diverging palette with the median in the middle
function position(v, scale, id = current()) {
  const { lo, hi } = scale, mid = scale.p50 != null ? scale.p50 : (lo + hi) / 2;
  if (!PALETTES[id].diverging) return Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
  return v <= mid ? Math.max(0, 0.5 * (v - lo) / (mid - lo)) : Math.min(1, 0.5 + 0.5 * (v - mid) / (hi - mid));
}
const bucket = (v, scale, n, id) => Math.round(position(v, scale, id) * (n - 1));
const memo = {};
const ink = (v, scale, id = current()) => (memo[id] || (memo[id] = steps(64, id)))[bucket(v, scale, 64, id)];
const gradient = (id = current()) => `linear-gradient(90deg,${PALETTES[id].stops.join(',')})`;
function set(id) {
  if (!PALETTES[id]) return;
  try { localStorage.setItem(KEY, id); } catch (e) { /* private mode: this window only */ }
  window.dispatchEvent(new CustomEvent('stratum:gammapalette', { detail: id }));
}
addEventListener('storage', e => { if (e.key === KEY) window.dispatchEvent(new CustomEvent('stratum:gammapalette', { detail: current() })); });

// a row of swatches to choose with; `onPick` after the choice is stored
function picker(onPick) {
  const row = document.createElement('div');
  row.className = 'gp-pick'; row.setAttribute('role', 'radiogroup'); row.setAttribute('aria-label', 'Gamma colours');
  const now = current();
  for (const [id, p] of Object.entries(PALETTES)) {
    const b = document.createElement('button');
    b.type = 'button'; b.setAttribute('role', 'radio'); b.setAttribute('aria-checked', String(id === now)); b.title = p.name;
    b.innerHTML = `<i style="background:${gradient(id)}"></i><span></span>`;
    b.querySelector('span').textContent = p.name;
    b.onclick = () => { set(id); if (onPick) onPick(id); };
    row.append(b);
  }
  return row;
}
if (!document.getElementById('gp-style')) {
  const st = document.createElement('style'); st.id = 'gp-style';
  st.textContent = `.gp-pick{display:grid;grid-template-columns:1fr 1fr;gap:5px;margin:8px 0 2px;pointer-events:auto}
.gp-pick button{display:flex;flex-direction:column;align-items:stretch;gap:4px;background:#132331;border:1px solid #2c4452;border-radius:7px;color:#c9dbe3;padding:5px 6px 4px;font:11px/1.2 -apple-system,Segoe UI,Roboto,sans-serif;cursor:pointer;text-align:left;min-width:0}
.gp-pick button:hover{border-color:#5ee2d0}.gp-pick button[aria-checked=true]{border-color:#64e8ce;background:#173a3a;color:#f2fffc}
.gp-pick i{display:block;height:7px;border-radius:3px}.gp-pick span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}`;
  (document.head || document.documentElement).append(st);
}
window.StratumGamma = { PALETTES, current, set, steps, position, bucket, ink, gradient, picker };
})();
