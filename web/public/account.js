// Who is signed in: a small menu in any [data-account] slot (the map sidebar,
// the charts page, the admin page) with Invites & accounts for admins and Sign
// out. A session that has ended — signed out elsewhere, the account removed —
// goes back to the sign-in page, which returns here afterwards.
(() => {
'use strict';
// light by default; theme.js sets [data-theme=dark] on <html> for the dark one
const CSS = `
.acct{position:relative;display:inline-block;vertical-align:middle}
.acct>button{width:30px;height:30px;border-radius:50%;background:#0d8577;border:1px solid #0d8577;color:#ffffff;
  font:700 12px/1 -apple-system,Segoe UI,Roboto,sans-serif;cursor:pointer;padding:0;letter-spacing:.02em}
.acct>button:hover,.acct>button:focus-visible{outline:2px solid #0d8577;outline-offset:2px}
.acct-menu{position:absolute;right:0;top:38px;z-index:80;min-width:230px;background:#ffffff;border:1px solid #b9c8d2;border-radius:10px;
  box-shadow:0 14px 34px rgba(20,33,43,.2);padding:6px;font:13px/1.4 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#14212b;text-align:left}
.acct-menu .who{padding:8px 10px 9px;border-bottom:1px solid #d3dde4;margin-bottom:4px}
.acct-menu .who b{display:block;font-weight:650}.acct-menu .who span{display:block;color:#566b78;font-size:12px;word-break:break-all}
.acct-menu a,.acct-menu button{display:block;width:100%;text-align:left;background:none;border:0;color:#14212b;padding:8px 10px;
  border-radius:7px;font:inherit;cursor:pointer;text-decoration:none}
.acct-menu a:hover,.acct-menu button:hover,.acct-menu a:focus-visible,.acct-menu button:focus-visible{background:#eef3f6;outline:none}
[data-theme=dark] .acct>button{background:#246358;border-color:#64e8ce;color:#f2fffc}
[data-theme=dark] .acct>button:hover,[data-theme=dark] .acct>button:focus-visible{outline-color:#5ee2d0}
[data-theme=dark] .acct-menu{background:#0d1924;border-color:#345260;box-shadow:0 14px 34px #000a;color:#e7f4fa}
[data-theme=dark] .acct-menu .who{border-bottom-color:#243a46}
[data-theme=dark] .acct-menu .who span{color:#93adb9}
[data-theme=dark] .acct-menu a,[data-theme=dark] .acct-menu button{color:#e7f4fa}
[data-theme=dark] .acct-menu a:hover,[data-theme=dark] .acct-menu button:hover,[data-theme=dark] .acct-menu a:focus-visible,[data-theme=dark] .acct-menu button:focus-visible{background:#152936}`;

const toLogin = () => location.replace('/login.html?next=' + encodeURIComponent(location.pathname + location.search));
const initials = n => String(n || '?').trim().split(/\s+/).slice(0, 2).map(w => w[0] || '').join('').toUpperCase() || '?';

function render(me) {
  if (!document.getElementById('acct-style')) {
    const st = document.createElement('style'); st.id = 'acct-style'; st.textContent = CSS; document.head.append(st);
  }
  document.querySelectorAll('[data-account]').forEach(slot => {
    const box = document.createElement('div'); box.className = 'acct';
    const btn = document.createElement('button');
    btn.type = 'button'; btn.textContent = initials(me.name);
    btn.title = `Signed in as ${me.name}`; btn.setAttribute('aria-haspopup', 'menu'); btn.setAttribute('aria-expanded', 'false');
    const menu = document.createElement('div'); menu.className = 'acct-menu'; menu.setAttribute('role', 'menu'); menu.hidden = true;
    const who = document.createElement('div'); who.className = 'who';
    const b = document.createElement('b'); b.textContent = me.name;
    const sp = document.createElement('span'); sp.textContent = me.email + (me.role === 'admin' ? ' · admin' : '');
    who.append(b, sp); menu.append(who);
    if (me.role === 'admin' && !location.pathname.endsWith('/admin.html')) {
      const a = document.createElement('a'); a.href = 'admin.html'; a.textContent = 'Invites & accounts'; a.setAttribute('role', 'menuitem'); menu.append(a);
    }
    const out = document.createElement('button'); out.type = 'button'; out.textContent = 'Sign out'; out.setAttribute('role', 'menuitem');
    out.onclick = async () => {
      try { await fetch('/api/auth?a=logout', { method: 'POST', credentials: 'same-origin' }); } catch (e) { /* signed out below anyway */ }
      location.replace('/login.html');
    };
    menu.append(out);
    const set = open => { menu.hidden = !open; btn.setAttribute('aria-expanded', String(open)); if (open) (menu.querySelector('a,button') || btn).focus(); };
    btn.onclick = e => { e.stopPropagation(); set(menu.hidden); };
    document.addEventListener('click', e => { if (!box.contains(e.target)) set(false); });
    box.addEventListener('keydown', e => { if (e.key === 'Escape') { set(false); btn.focus(); } });
    box.append(btn, menu);
    slot.replaceChildren(box);
  });
}

async function load() {
  let r;
  try { r = await fetch('/api/auth?a=me', { credentials: 'same-origin', cache: 'no-store' }); }
  catch (e) { return; }                         // offline: leave the page as it is
  if (r.status === 401) { toLogin(); return; }
  if (!r.ok) return;
  const { user } = await r.json();
  window.stratumUser = user;
  render(user);
  window.dispatchEvent(new CustomEvent('stratum:user', { detail: user }));
  pull();
}

// ---------- settings that follow the person (/api/mine?k=prefs) ----------
// The page works from this browser's copy (localStorage, read as pages load);
// the account keeps the person's. On sign-in the account's copy is taken when it
// is newer than what this browser last had from it; changes made here go up a
// little after they are made and when the page is put away.
const PREF_KEYS = ['stratum.theme', 'stratum.textSize', 'stratum.gammaPalette', 'stratum.quakeFilter', 'stratum.allWells',
                   'stratum.section', 'stratum.hiddenCurves', 'stratum.spacingLimits', 'stratum.sectionMetric', 'stratum.mapColour'];
const AT_KEY = 'fv.prefsAt';                   // not stratum.*: sessions leave it alone
const local = k => { try { return localStorage.getItem(k); } catch (e) { return null; } };
const snapshot = () => Object.fromEntries(PREF_KEYS.map(k => [k, local(k)]));
let sent = null, pulled = false;
function take(prefs) {
  for (const k of PREF_KEYS) {
    const v = prefs[k] == null ? null : String(prefs[k]);
    if (v === local(k)) continue;
    // live where the page can change in place; the rest is read as pages load
    if (k === 'stratum.theme' && window.StratumTheme && v) StratumTheme.set(v);
    else if (k === 'stratum.textSize' && window.StratumTheme && v) StratumTheme.setText(v);
    else if (k === 'stratum.gammaPalette' && window.StratumGamma && v) StratumGamma.set(v);
    else if (k === 'stratum.quakeFilter' && window.StratumQuakes) { try { StratumQuakes.set(v ? JSON.parse(v) : {}); } catch (e) { /* unreadable: skipped */ } }
    else if (k === 'stratum.spacingLimits' && window.FVMetrics && v) { try { FVMetrics.setLimits(JSON.parse(v)); } catch (e) { /* unreadable: skipped */ } }
    else try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* private mode */ }
  }
}
async function pull() {
  let j;
  try { const r = await fetch('/api/mine?k=prefs', { credentials: 'same-origin', cache: 'no-store' }); if (!r.ok) return; j = await r.json(); }
  catch (e) { return; }
  pulled = true;
  if (j.updated && (!local(AT_KEY) || j.updated > local(AT_KEY))) {
    take(j.prefs || {});
    try { localStorage.setItem(AT_KEY, j.updated); } catch (e) { /* private mode */ }
    sent = JSON.stringify(snapshot());
  } else push();                                 // the account has none yet, or this browser is up to date
}
function push(keepalive) {
  if (!pulled) return;
  const snap = snapshot(), body = JSON.stringify(snap);
  if (body === sent) return;
  sent = body;
  fetch('/api/mine?k=prefs', { method: 'POST', credentials: 'same-origin', keepalive: !!keepalive, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prefs: snap }) })
    .then(r => r.ok ? r.json() : null).then(j => { if (j && j.updated) try { localStorage.setItem(AT_KEY, j.updated); } catch (e) { /* private mode */ } })
    .catch(() => { sent = null; });
}
let pushT = 0;
const soon = () => { clearTimeout(pushT); pushT = setTimeout(() => push(false), 1500); };
['stratum:theme', 'stratum:textsize', 'stratum:gammapalette', 'stratum:quakefilter', 'stratum:spacing', 'stratum:prefs'].forEach(t => addEventListener(t, soon));
addEventListener('storage', e => { if (PREF_KEYS.includes(e.key)) soon(); });
addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') push(true); });
addEventListener('pagehide', () => push(true));
window.StratumPrefs = { push: () => push(false), pull, KEYS: PREF_KEYS };
if (window.top === window) {
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', load); else load();
}
})();
