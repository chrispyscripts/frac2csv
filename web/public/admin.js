// Invites & accounts, for admins: make invite codes, withdraw them, issue
// password-reset codes, remove accounts. Everything is checked again by
// /api/auth, which only acts for an admin.
'use strict';
const $ = id => document.getElementById(id);
const when = iso => { const d = new Date(iso); return iso && !isNaN(d) ? d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '–'; };
const day = iso => { const d = new Date(iso); return iso && !isNaN(d) ? d.toLocaleDateString(undefined, { dateStyle: 'medium' }) : '–'; };
const say = (t, ok) => { $('msg').textContent = t || ''; $('msg').classList.toggle('ok', !!ok); };
function cell(text, cls) { const td = document.createElement('td'); if (cls) td.className = cls; td.textContent = text; return td; }

async function api(action, body) {
  const r = await fetch(`/api/auth?a=${action}`, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin', body: JSON.stringify(body) } : { credentials: 'same-origin', cache: 'no-store' });
  let d = {}; try { d = await r.json(); } catch (e) { /* not JSON */ }
  if (r.status === 401) { location.replace('/login.html?next=/admin.html'); throw Error('signed out'); }
  if (!r.ok) { const e = Error(d.error || 'Something went wrong.'); e.status = r.status; throw e; }
  return d;
}

// Blob's listing trails a write by a second or two: show the change now, and again once it has caught up
const later = fn => { fn(); setTimeout(fn, 2500); };

let lastCode = null;
function showMade(code, note) {
  lastCode = code;
  $('made-code').textContent = code;
  $('made-note').textContent = note;
  $('made').hidden = false;
}
const link = code => `${location.origin}/login.html?code=${encodeURIComponent(code)}`;
async function copy(text, what) {
  try { await navigator.clipboard.writeText(text); say(`${what} copied.`, true); }
  catch (e) { say(`Couldn’t copy: select it and copy by hand.`); }
}
$('copy-code').onclick = () => lastCode && copy(lastCode, 'Code');
$('copy-link').onclick = () => lastCode && copy(link(lastCode), 'Invite link');

$('new').onsubmit = async e => {
  e.preventDefault();
  const f = e.target, btn = f.querySelector('button');
  btn.disabled = true; say('');
  try {
    const d = await api('invite', { note: f.note.value, role: f.role.value, uses: +f.uses.value, days: +f.days.value });
    showMade(d.code, `${f.role.value === 'admin' ? 'Admin' : 'User'} invite · ${+f.uses.value > 1 ? f.uses.value + ' uses' : 'one use'} · expires ${day(d.expires)}. Send it to them; they choose “I have a code” on the sign-in page, or open the invite link.`);
    f.note.value = '';
    later(loadInvites);
  } catch (err) { say(err.message); }
  finally { btn.disabled = false; }
};

async function loadInvites() {
  const { invites } = await api('invites');
  const tb = $('invites');
  tb.replaceChildren();
  if (!invites.length) { const tr = document.createElement('tr'); const td = cell('No codes yet.', 'empty'); td.colSpan = 8; tr.append(td); tb.append(tr); return; }
  for (const i of invites) {
    const tr = document.createElement('tr');
    const usedBy = i.used.map(u => u.email).join(', ');
    const forCell = cell(i.note || '–'); if (usedBy) { const m = document.createElement('div'); m.className = 'm'; m.textContent = 'used by ' + usedBy; forCell.append(m); }
    const st = document.createElement('td'); const badge = document.createElement('span'); badge.className = 'st ' + i.status; badge.textContent = i.status; st.append(badge);
    const acts = document.createElement('td'); const box = document.createElement('div'); box.className = 'acts';
    if (i.status === 'open') {
      const c = document.createElement('button'); c.type = 'button'; c.textContent = 'Copy link'; c.onclick = () => copy(link(i.code), 'Invite link');
      const w = document.createElement('button'); w.type = 'button'; w.textContent = 'Withdraw';
      w.onclick = async () => { if (!confirm(`Withdraw ${i.code}? It will stop working.`)) return; try { await api('revoke', { code: i.code }); later(loadInvites); } catch (err) { say(err.message); } };
      box.append(c, w);
    }
    acts.append(box);
    tr.append(cell(i.code, 'code'), forCell, cell(i.kind === 'reset' ? 'password reset' : i.role === 'admin' ? 'admin invite' : 'invite'),
      cell(`${i.used.length} of ${i.uses}`), st, cell(`${day(i.created)} · ${i.by || ''}`), cell(day(i.expires)), acts);
    tb.append(tr);
  }
}

async function loadUsers() {
  const { users, me } = await api('users');
  const tb = $('users');
  tb.replaceChildren();
  for (const u of users) {
    const tr = document.createElement('tr');
    const acts = document.createElement('td'); const box = document.createElement('div'); box.className = 'acts';
    const r = document.createElement('button'); r.type = 'button'; r.textContent = 'Reset code';
    r.onclick = async () => {
      try { const d = await api('reset', { email: u.email }); showMade(d.code, `Password reset for ${u.email} · one use · expires ${day(d.expires)}. They choose “I have a code” and set a new password.`); later(loadInvites); window.scrollTo({ top: 0, behavior: 'smooth' }); }
      catch (err) { say(err.message); }
    };
    box.append(r);
    if (u.email !== me) {
      const x = document.createElement('button'); x.type = 'button'; x.textContent = 'Remove';
      x.onclick = async () => { if (!confirm(`Remove ${u.name} (${u.email})? They are signed out and can’t sign in again without a new invite.`)) return;
        try { await api('remove', { email: u.email }); tr.remove(); later(loadUsers); } catch (err) { say(err.message); } };
      box.append(x);
    }
    acts.append(box);
    tr.append(cell(u.name), cell(u.email), cell(u.role), cell(day(u.created)), cell(when(u.lastLogin)), cell(u.invite || '–', 'code'), acts);
    tb.append(tr);
  }
}

(async () => {
  try { await Promise.all([loadInvites(), loadUsers()]); $('admin').hidden = false; }
  catch (e) { if (e.status === 403) $('denied').hidden = false; else if (e.message !== 'signed out') { $('admin').hidden = false; say(e.message); } }
})();
