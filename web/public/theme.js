// Light or dark: one choice for every FracView window, light unless dark is
// chosen. Loaded first in <head>, so a page paints in its theme from the start:
// it sets <html data-theme="light|dark"> and each page's CSS takes its colours
// from that. Canvas and SVG drawings ask StratumTheme.dark() (or pick) as they
// draw and redraw on `stratum:theme`.
//
// A setting (localStorage stratum.theme), so it carries across windows,
// reloads and saved sessions; a change fires `stratum:theme` on window here and
// in every other open FracView window and frame.
(() => {
'use strict';
const KEY = 'stratum.theme';
const root = document.documentElement;
function get() {
  try { return localStorage.getItem(KEY) === 'dark' ? 'dark' : 'light'; } catch (e) { return 'light'; }
}
function apply(t) { root.dataset.theme = t; root.style.colorScheme = t; syncButtons(); }
function set(t) {
  t = t === 'dark' ? 'dark' : 'light';
  try { localStorage.setItem(KEY, t); } catch (e) { /* private mode: this window only */ }
  apply(t);
  window.dispatchEvent(new CustomEvent('stratum:theme', { detail: t }));
}
addEventListener('storage', e => {
  if (e.key !== KEY) return;
  apply(get());
  window.dispatchEvent(new CustomEvent('stratum:theme', { detail: get() }));
});
const dark = () => root.dataset.theme === 'dark';
const pick = (light, darkValue) => dark() ? darkValue : light;
// pads' colours, in a fixed order, for the theme on screen: the light set clears
// 3:1 on white and keeps neighbours apart for colour-blind eyes (pads are also
// named wherever they are drawn)
const PADS = {
  dark: ['#4d8dff', '#ff8a4d', '#3ecf8e', '#e35d9a', '#f2c94c', '#8f6bff', '#4dd0e1', '#ff6b6b', '#9ccc65', '#ba68c8'],
  light: ['#2563eb', '#e8590c', '#0b8ea3', '#9c36b5', '#5c940d', '#c2255c', '#9a6b00', '#7048e8', '#138a4f'],
};
const padColor = i => { const set = PADS[dark() ? 'dark' : 'light']; return set[((i % set.length) + set.length) % set.length]; };

// the switch: a round button that shows the theme it would change to
const SUN = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><circle cx="12" cy="12" r="4.2" fill="currentColor"/><g stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 2.5v2.4M12 19.1v2.4M2.5 12h2.4M19.1 12h2.4M5.3 5.3l1.7 1.7M17 17l1.7 1.7M5.3 18.7 7 17M17 7l1.7-1.7"/></g></svg>';
const MOON = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M20.2 14.6A8.5 8.5 0 0 1 9.4 3.8a.6.6 0 0 0-.8-.7A9.5 9.5 0 1 0 20.9 15.4a.6.6 0 0 0-.7-.8Z"/></svg>';
const buttons = new Set();
function syncButtons() {
  for (const b of buttons) {
    const d = dark();
    b.innerHTML = d ? SUN : MOON;
    b.title = d ? 'Switch to the light theme' : 'Switch to the dark theme';
    b.setAttribute('aria-label', 'Dark theme');
    b.setAttribute('aria-pressed', String(d));
  }
}
function button() {
  const b = document.createElement('button');
  b.type = 'button'; b.className = 'fv-theme';
  b.onclick = () => set(dark() ? 'light' : 'dark');
  buttons.add(b); syncButtons();
  return b;
}
const CSS = `.fv-theme{display:inline-grid;place-items:center;width:30px;height:30px;padding:0;border-radius:50%;cursor:pointer;vertical-align:middle;
  background:#eef3f6;border:1px solid #b9c8d2;color:#14212b}
.fv-theme:hover,.fv-theme:focus-visible{border-color:#0d8577;outline:none}
.fv-theme:focus-visible{box-shadow:0 0 0 2px #0d857755}
[data-theme=dark] .fv-theme{background:#152936;border-color:#345260;color:#e7f4fa}
[data-theme=dark] .fv-theme:hover,[data-theme=dark] .fv-theme:focus-visible{border-color:#5ee2d0}
[data-theme=dark] .fv-theme:focus-visible{box-shadow:0 0 0 2px #5ee2d055}`;
function mount() {
  if (!document.getElementById('fv-theme-style')) {
    const st = document.createElement('style'); st.id = 'fv-theme-style'; st.textContent = CSS; document.head.append(st);
  }
  document.querySelectorAll('[data-theme-toggle]').forEach(slot => { if (!slot.querySelector('.fv-theme')) slot.append(button()); });
}
apply(get());
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount); else mount();

window.StratumTheme = { get, set, dark, pick, padColor, button, mount };
})();
