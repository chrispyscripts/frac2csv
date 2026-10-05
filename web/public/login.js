// Stratum's sign-in page: sign in, or use an invite or reset code. The only page
// open without an account (middleware.js); afterwards it goes back where you were.
'use strict';
const $ = id => document.getElementById(id);
const q = new URLSearchParams(location.search);
// only a path on this site: never somewhere else after signing in
const next = (() => { const n = q.get('next') || ''; return /^\/(?!\/)[^\\\s]*$/.test(n) && !n.startsWith('/login') ? n : '/map.html'; })();
const say = (t, ok) => { $('msg').textContent = t || ''; $('msg').classList.toggle('ok', !!ok); };

function tab(which) {
  for (const [t, f] of [['tab-in', 'form-in'], ['tab-code', 'form-code']]) {
    const on = f === which;
    $(t).setAttribute('aria-selected', String(on)); $(t).tabIndex = on ? 0 : -1; $(f).hidden = !on;
  }
  say('');
  const first = $(which).querySelector('input:not([value]), input'); if (first) first.focus();
}
$('tab-in').onclick = () => tab('form-in');
$('tab-code').onclick = () => tab('form-code');
document.querySelector('[data-to=code]').onclick = e => { e.preventDefault(); tab('form-code'); };

async function call(action, body) {
  const r = await fetch(`/api/auth?a=${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                  credentials: 'same-origin', body: JSON.stringify(body) });
  let d = {}; try { d = await r.json(); } catch (e) { /* not JSON */ }
  if (!r.ok) throw Error(d.error || 'Something went wrong. Try again in a moment.');
  return d;
}
function busy(form, on) { form.querySelector('button.go').disabled = on; }

$('form-in').onsubmit = async e => {
  e.preventDefault();
  const f = e.target, email = f.email.value.trim(), password = f.password.value;
  if (!email || !password) { say('Enter your email and password.'); return; }
  busy(f, true); say('');
  try { await call('login', { email, password }); location.replace(next); }
  catch (err) { say(err.message); f.password.select(); }
  finally { busy(f, false); }
};
$('form-code').onsubmit = async e => {
  e.preventDefault();
  const f = e.target;
  const body = { code: f.code.value, name: f.name.value.trim(), email: f.email.value.trim(), password: f.password.value };
  if (!body.code.trim()) { say('Enter the code you were given.'); return; }
  if (!body.email) { say('Enter your email address.'); return; }
  if (body.password.length < 10) { say('Use a password of at least 10 characters.'); return; }
  if (body.password !== f.confirm.value) { say('The two passwords don’t match.'); f.confirm.select(); return; }
  busy(f, true); say('');
  try { await call('signup', body); say('Done. Opening FracView…', true); location.replace(next); }
  catch (err) { say(err.message); }
  finally { busy(f, false); }
};

// an invite link carries its code; someone already signed in goes straight on
if (q.get('code')) { $('form-code').code.value = q.get('code'); tab('form-code'); }
else $('form-in').email.focus();
fetch('/api/auth?a=me', { credentials: 'same-origin' }).then(r => { if (r.ok && !q.get('code')) location.replace(next); }).catch(() => {});
