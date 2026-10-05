// The sign-in cookie the middleware trusts: genuine and unexpired, or nothing.
const assert=require('node:assert/strict'),path=require('node:path'),crypto=require('node:crypto');
(async()=>{
  const m=await import(path.join(__dirname,'../web/lib/session.js'));
  const secret='test-secret-'+crypto.randomBytes(8).toString('hex'),now=Math.floor(Date.now()/1000);
  const good=await m.sign({email:'a@b.test',role:'user',iat:now,exp:now+60},secret);
  assert.equal((await m.verify(good,secret)).email,'a@b.test','a cookie it signed is accepted');
  assert.equal(await m.verify(good,secret+'x'),null,'another secret: refused');
  const [body,sig]=good.split('.');
  const forged=Buffer.from(JSON.stringify({email:'a@b.test',role:'admin',iat:now,exp:now+60})).toString('base64url');
  assert.equal(await m.verify(forged+'.'+sig,secret),null,'a changed payload (made admin) keeps no signature');
  assert.equal(await m.verify(body+'.'+sig.slice(0,-2)+'AA',secret),null,'a changed signature: refused');
  assert.equal(await m.verify(await m.sign({email:'a@b.test',exp:now-1},secret),secret),null,'expired: refused');
  assert.equal(await m.verify(await m.sign({email:'a@b.test'},secret),secret),null,'no expiry: refused');
  for(const junk of [null,'',good+'.x','.'.repeat(3),'a'.repeat(5000)])assert.equal(await m.verify(junk,secret),null);
  assert.equal(await m.verify(good,''),null,'no secret configured: nobody is signed in');
  assert.equal(m.readCookie('x=1; __Host-stratum='+good+'; y=2'),good);
  assert.equal(m.readCookie('__Host-stratumX=1'),null);
  assert.match(m.setCookie('t'),/HttpOnly; Secure; SameSite=Lax/);
  assert.equal(await m.userPath('a@b.test'),'users/'+crypto.createHash('sha256').update('a@b.test').digest('hex')+'.json','the edge and Node name an account alike');
  console.log('PASS: sign-in cookie signing, tampering, expiry and account paths');
})().catch(e=>{console.error(e);process.exitCode=1});
