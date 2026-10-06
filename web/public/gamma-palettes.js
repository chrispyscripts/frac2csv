// Gamma ray colour schemes, one choice for every view (the 3D view, the wine
// rack, the well section). Each runs from low API (cleaner rock) to high API
// (shalier), and every step stays visible on the ground it is drawn on (at
// least 2.3:1 against it, so a low reading never reads as a missing one). So
// each has two sets of stops: `stops` for the dark theme, where high readings
// are the brightest, and `light` for the light theme, where they are the
// darkest -- the shalier the rock, the more it stands out, either way.
//
//   Amber        one hue, dark to cream: the quiet default
//   Viridis      blue to green to yellow, evenly spaced to the eye, colour-blind safe
//   Sand → shale the log convention: clean sand yellow, shale grey-green
//   Cool → warm  diverging on the lateral median: blue cleaner than usual,
//                grey typical, red shalier -- the one that makes outliers jump
//
// The choice is a setting (localStorage stratum.gammaPalette), so it carries
// across windows, reloads and saved sessions; a change fires
// `stratum:gammapalette` on window here and in every other open FracView window,
// and so does a change of theme (theme.js), since the colours change with it.
(() => {
'use strict';
const KEY = 'stratum.gammaPalette';
const PALETTES = {
  amber:     { name: 'Amber', stops: ['#92500b', '#ac5c00', '#c36c00', '#d57f00', '#e29500', '#eaad4a', '#eec57e', '#f2dcb1', '#fef1d0'],
               light: ['#c88a12', '#bd7a0a', '#b06a05', '#a05a03', '#8f4c02', '#7c3f04', '#693306', '#562807', '#431e06'] },
  viridis:   { name: 'Viridis', stops: ['#3b528b', '#31688e', '#287c8e', '#20908d', '#22a785', '#3dbc74', '#73d056', '#b8de29', '#fde725'],
               light: ['#3aa676', '#259a7f', '#1f8a8a', '#25788e', '#2d678e', '#36568b', '#3e4385', '#45307a', '#440154'] },
  sandshale: { name: 'Sand → shale', stops: ['#fff3a3', '#f3da55', '#d7c13c', '#a8b443', '#749f4e', '#4f895c', '#477266', '#56646f'],
               light: ['#c29a12', '#ad9222', '#94892f', '#7b7d3a', '#657144', '#52644c', '#445650', '#3b4a52', '#333e4f'] },
  coolwarm:  { name: 'Cool → warm', stops: ['#3a6fd8', '#5b93f5', '#93b6f2', '#c2cddb', '#cdd2d6', '#eec0a7', '#f2906b', '#e75c47', '#cc3639'],
               light: ['#1f4fb8', '#3a6fd0', '#6b8fd4', '#8c9cb6', '#97a0a8', '#b08f80', '#d06a4c', '#c23f2c', '#a1111d'], diverging: true },
};
const dark = () => { const d = document.documentElement; return !!(d && d.dataset && d.dataset.theme === 'dark'); };
// the stops for the theme on screen
const stopsOf = (id = current()) => (dark() || !PALETTES[id].light ? PALETTES[id].stops : PALETTES[id].light);
const rgb = h => [1, 3, 5].map(j => parseInt(h.slice(j, j + 2), 16));
function current() {
  let id = 'amber';
  try { id = localStorage.getItem(KEY) || id; } catch (e) { /* private mode */ }
  return PALETTES[id] ? id : 'amber';
}
// n evenly spaced colours along the palette
function steps(n, id = current()) {
  const s = stopsOf(id);
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
const ink = (v, scale, id = current()) => { const k = id + (dark() ? ':d' : ':l'); return (memo[k] || (memo[k] = steps(64, id)))[bucket(v, scale, 64, id)]; };
const gradient = (id = current()) => `linear-gradient(90deg,${stopsOf(id).join(',')})`;
function set(id) {
  if (!PALETTES[id]) return;
  try { localStorage.setItem(KEY, id); } catch (e) { /* private mode: this window only */ }
  window.dispatchEvent(new CustomEvent('stratum:gammapalette', { detail: id }));
}
addEventListener('storage', e => { if (e.key === KEY) window.dispatchEvent(new CustomEvent('stratum:gammapalette', { detail: current() })); });
addEventListener('stratum:theme', () => window.dispatchEvent(new CustomEvent('stratum:gammapalette', { detail: current() })));

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
.gp-pick button{display:flex;flex-direction:column;align-items:stretch;gap:4px;background:#f3f6f8;border:1px solid #d3dde4;border-radius:7px;color:#3d505c;padding:5px 6px 4px;font:11px/1.2 -apple-system,Segoe UI,Roboto,sans-serif;cursor:pointer;text-align:left;min-width:0}
.gp-pick button:hover{border-color:#0d8577}.gp-pick button[aria-checked=true]{border-color:#0d8577;background:#dff2ee;color:#0b5f55}
[data-theme=dark] .gp-pick button{background:#132331;border-color:#2c4452;color:#c9dbe3}
[data-theme=dark] .gp-pick button:hover{border-color:#5ee2d0}[data-theme=dark] .gp-pick button[aria-checked=true]{border-color:#64e8ce;background:#173a3a;color:#f2fffc}
.gp-pick i{display:block;height:7px;border-radius:3px}.gp-pick span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}`;
  (document.head || document.documentElement).append(st);
}
window.StratumGamma = { PALETTES, current, set, stops: stopsOf, steps, position, bucket, ink, gradient, picker };
})();
