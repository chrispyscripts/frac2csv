// The wine rack window's geometry on a real pad, the well section's curve
// sparklines, and the light theme's colours -- without a browser.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const pub=path.join(__dirname,'../web/public');
const read=f=>fs.readFileSync(path.join(pub,f),'utf8');
const slice=(src,a,b)=>{const i=src.indexOf(a);assert(i>=0,'missing '+a);const j=src.indexOf(b,i);assert(j>i,'missing '+b);return src.slice(i,j)};

// ---------- the rack: a pad turned along its laterals, and a line moved along it ----------
const rack=read('winerack.js');
const c={Math,Number,String,Object,Array,Set,Map,isFinite,LANDING_M:400,colorBy:'pad',gamma:null};
vm.createContext(c);
vm.runInContext(slice(rack,'function rackGeom(p)','const rackInk'),c);
vm.runInContext(slice(rack,'function centralWell(R)','\n}\n')+'\n}',c);
// the pad as loadPad() makes it: metres about the pad, x east, y up, z north
const p=JSON.parse(read('data/region/pads/gundy-01.json'));
p.wells=p.wells.filter(w=>w.well.curves);
const k=Math.cos(p.lat*Math.PI/180),xy=(lon,lat)=>[(lon-p.lon)*111320*k,(lat-p.lat)*111320];
p.wells.forEach(w=>{const [wx,wz]=xy(w.well.lon,w.well.lat),t=w.trajectory;w.points=t.md.map((m,j)=>[wx+t.ew[j],-t.tvd[j],wz+t.ns[j]]).filter(q=>q.every(Number.isFinite));w.pad=p});
const g=c.rackGeom(p);
assert(g.ws.length===p.wells.length&&g.ws.length>1,'every well with charts is in the rack');
assert(g.start>g.sMin&&g.start<g.sMax,'the line starts inside the pad');
const at=s=>g.ws.map(o=>c.rackCross(o,s)).filter(Boolean);
const startHits=at(g.start);
assert(startHits.filter(x=>!x.landing).length>=Math.ceil(g.ws.length*.8),'at the start most wells are landed on the line');
assert.equal(at(g.sMax+50).length,0,'past the toes no well is on the line');
// a lateral runs away from the pad: moving the line out reaches deeper into each well
for(const o of g.ws){const a=c.rackCross(o,g.start-200),b=c.rackCross(o,g.start+200);if(a&&b)assert(b.md>a.md,'MD grows along the pad for WA '+o.w.well.wa)}
// laterals run parallel: the axis is the pad's, so wells keep their places across it
const spread=x=>Math.max(...x.map(h=>h.c))-Math.min(...x.map(h=>h.c));
assert(spread(at(g.start))<(g.c1-g.c0)+1,'crossings stay inside the pad');
// a new rack starts on the well nearest the middle of the pad
const R={g,s:g.start},mid=(g.c0+g.c1)/2,pick=c.centralWell(R);
assert(pick.x&&!pick.x.landing,'the middle well is landed on the line');
for(const h of startHits.filter(x=>!x.landing))assert(Math.abs(pick.x.c-mid)<=Math.abs(h.c-mid)+1e-9,'no landed well is nearer the middle');

// ---------- the section's sparklines: each stage squeezed into a few columns ----------
const ws=read('wellsection.js'),s={Math,isFinite};
vm.createContext(s);vm.runInContext(slice(ws,'function spark(v, n)','// one scale for every stage'),s);
const plain=o=>JSON.parse(JSON.stringify(o));
assert.deepEqual(plain(s.spark([1,5,2,8,3],2)),[[0,1],[0,5],[1,2],[1,8]],'each column keeps its low and high, in time order');
assert.deepEqual(plain(s.spark([9,null,null,null],2)),[[0,9],null],'a column with no readings is a gap');
assert.deepEqual(plain(s.spark([4,4,4],5)),[[0,4],[1,4],[2,4]],'never more columns than readings');
const flat=Array(1000).fill(40);flat[613]=97;
assert.equal(Math.max(...s.spark(flat,30).filter(Boolean).map(q=>q[1])),97,'a one-sample spike survives');

// ---------- the light theme: pads and gamma stay readable on white ----------
const L=h=>{const v=[1,3,5].map(i=>parseInt(h.slice(i,i+2),16)/255).map(x=>x<=.03928?x/12.92:((x+.055)/1.055)**2.4);return .2126*v[0]+.7152*v[1]+.0722*v[2]};
const contrast=(a,b)=>{const x=L(a),y=L(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05)};
const store=new Map(),root={dataset:{},style:{}};
const t={localStorage:{getItem:k=>store.has(k)?store.get(k):null,setItem:(k,v)=>store.set(k,String(v)),removeItem:k=>store.delete(k)},
  document:{documentElement:root,readyState:'complete',querySelectorAll:()=>[],getElementById:()=>({}),createElement:()=>({}),head:{append(){}}},
  CustomEvent:class{constructor(n,o){this.type=n;this.detail=o&&o.detail}},addEventListener(){},dispatchEvent(){}};
t.window=t;vm.createContext(t);vm.runInContext(read('theme.js'),t);
const T=t.StratumTheme;
assert.equal(T.get(),'light','light unless dark is chosen');assert.equal(root.dataset.theme,'light');
const lightPads=Array.from({length:9},(_,i)=>T.padColor(i));
assert.equal(new Set(lightPads).size,9,'nine distinct pad colours before they repeat');
for(const col of lightPads)assert(contrast(col,'#ffffff')>=3,`pad colour ${col} clears 3:1 on white`);
T.set('dark');assert.equal(root.dataset.theme,'dark');assert.equal(store.get('stratum.theme'),'dark','the choice is kept');
assert.equal(T.padColor(0),'#4d8dff','dark keeps its pad colours');
const gp={localStorage:t.localStorage,document:{documentElement:{dataset:{theme:'light'}},getElementById:()=>({})},CustomEvent:t.CustomEvent,addEventListener(){},dispatchEvent(){}};
gp.window=gp;vm.createContext(gp);vm.runInContext(read('gamma-palettes.js'),gp);
for(const [id,pal] of Object.entries(gp.StratumGamma.PALETTES)){
  assert.equal(pal.light.length>=8,true,id+' has light stops');
  for(const col of pal.light)assert(contrast(col,'#ffffff')>=2.3,`${id} ${col} stays visible on white`);
  assert.deepEqual(plain(gp.StratumGamma.stops(id)),plain(pal.light),id+': the light stops on the light theme');
}
gp.document.documentElement.dataset.theme='dark';
assert.deepEqual(plain(gp.StratumGamma.stops('amber')),plain(gp.StratumGamma.PALETTES.amber.stops),'and the dark ones on the dark theme');
console.log('PASS: wine rack geometry on gundy-01, section sparklines, light theme colours');
