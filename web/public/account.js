// Who is signed in: a small menu in any [data-account] slot (the map sidebar,
// the charts page, the admin page) with Invites & accounts for admins and Sign
// out. A session that has ended — signed out elsewhere, the account removed —
// goes back to the sign-in page, which returns here afterwards.
(() => {
'use strict';
const CSS = `
.acct{position:relative;display:inline-block;vertical-align:middle}
.acct>button{width:30px;height:30px;border-radius:50%;background:#246358;border:1px solid #64e8ce;color:#f2fffc;
  font:700 12px/1 -apple-system,Segoe UI,Roboto,sans-serif;cursor:pointer;padding:0;letter-spacing:.02em}
.acct>button:hover,.acct>button:focus-visible{outline:2px solid #5ee2d0;outline-offset:2px}
.acct-menu{position:absolute;right:0;top:38px;z-index:80;min-width:230px;background:#0d1924;border:1px solid #345260;border-radius:10px;
  box-shadow:0 14px 34px #000a;padding:6px;font:13px/1.4 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#e7f4fa;text-align:left}
.acct-menu .who{padding:8px 10px 9px;border-bottom:1px solid #243a46;margin-bottom:4px}
.acct-menu .who b{display:block;font-weight:650}.acct-menu .who span{display:block;color:#93adb9;font-size:12px;word-break:break-all}
.acct-menu a,.acct-menu button{display:block;width:100%;text-align:left;background:none;border:0;color:#e7f4fa;padding:8px 10px;
  border-radius:7px;font:inherit;cursor:pointer;text-decoration:none}
.acct-menu a:hover,.acct-menu button:hover,.acct-menu a:focus-visible,.acct-menu button:focus-visible{background:#152936;outline:none}`;

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
}
if (window.top === window) {
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', load); else load();
}
})();
