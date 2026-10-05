// Sessions without a browser: a window opened for a session takes its state
// before the page runs, and a session file from elsewhere can only name
// Stratum pages and stratum.* settings.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/public/session.js'),'utf8');
const plain=o=>JSON.parse(JSON.stringify(o));   // objects from the sandbox, compared here
function storage(init={}){const m=new Map(Object.entries(init));return{get length(){return m.size},key:i=>[...m.keys()][i]??null,getItem:k=>m.has(k)?m.get(k):null,setItem:(k,v)=>m.set(k,String(v)),removeItem:k=>m.delete(k),dump:()=>Object.fromEntries(m)}}
function page(hash,local,session){
  const replaced=[];
  const c={console,JSON,Math,Date,Object,Array,Number,String,URL,URLSearchParams,Set,Map,Promise,setTimeout,
    localStorage:storage(local),sessionStorage:storage(session),
    location:{hash,pathname:'/compare.html',search:'',origin:'https://stratum.test'},
    history:{state:null,replaceState:(s,t,u)=>replaced.push(u)},
    document:{readyState:'loading',title:'Stratum — Compare wells',referrer:'',querySelectorAll:()=>[],getElementById:()=>null,addEventListener(){}},
    performance:{getEntriesByType:()=>[{type:'navigate'}]},
    screenX:0,screenY:0,innerWidth:1200,innerHeight:700,toolbar:{visible:true}};
  c.window=c;c.top=c;c.self=c;
  vm.createContext(c);vm.runInContext(source,c);
  return{c,replaced};
}

// a hand-off: the window's session keys replace whatever it had; anything not stratum.* is ignored
const t='abc123';
const {c,replaced}=page('#stratum-restore='+t,
  {['stratum.handoff.'+t]:JSON.stringify({at:Date.now(),session:{'stratum.compareView':'{"axis":"stage"}','not.ours':'x'},pending:{name:'S',windows:[{url:'map.html'}]}}),
   'stratum.handoff.old':JSON.stringify({at:Date.now()-2*864e5,session:{}})},
  {'stratum.compareView':'{"axis":"md"}','stratum.mapView':'{}','other':'kept'});
const ss=c.sessionStorage.dump(),ls=c.localStorage.dump();
assert.equal(ss['stratum.compareView'],'{"axis":"stage"}','the session view replaces the old one');
assert.equal(ss['stratum.mapView'],undefined,'stratum keys the session did not have are cleared');
assert.equal(ss['other'],'kept','keys that are not Stratum’s are left alone');
assert.equal(ss['not.ours'],undefined,'a hand-off cannot write other keys');
assert(ss['stratum.pendingWindows'],'the other windows are offered after a session opens');
assert.equal(ls['stratum.handoff.'+t],undefined,'a hand-off is used once');
assert.equal(ls['stratum.handoff.old'],undefined,'stale hand-offs are cleared');
assert.deepEqual(replaced,['/compare.html'],'the token leaves the address bar');

// a file from elsewhere
const clean=c.StratumSession.clean;
assert.throws(()=>clean({kind:'other'}),/not a Stratum session/);
assert.throws(()=>clean({kind:'stratum-session',windows:[{url:'https://evil.example/map.html'}]}),/no Stratum windows/);
const s=clean({kind:'stratum-session',name:'  x  ',settings:{'stratum.allWells':'1','stratum.sessions':'[]','stratum.handoff.z':'{}','evil':'1','stratum.n':5},
  windows:[{url:'javascript:alert(1)'},{url:'//evil.example/map.html'},{url:'map.html?a=1#frag'},
           {role:'main',url:'/wellview.html?wa=1&stage=2',name:'_top',popup:true,rect:{x:1e9,y:-5,w:1,h:1e9},session:{'stratum.wellTab':'tab-frac','x':'y'}}]});
assert.deepEqual(plain(Object.keys(s.settings)),['stratum.allWells'],'only stratum settings, never the session list or hand-offs');
assert.equal(s.windows.length,1);
assert.equal(s.windows[0].url,'wellview.html?wa=1&stage=2');
assert.equal(s.windows[0].name,'','only stratum-* window names');
assert.deepEqual(plain(s.windows[0].rect),{x:20000,y:-5,w:320,h:8000},'window placement clamped');
assert.deepEqual(plain(s.windows[0].session),{'stratum.wellTab':'tab-frac'});
assert.equal(s.name,'x');
console.log('PASS: session hand-off and file checks');
