// The quake filter and the gamma colour schemes, the two settings every view shares.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const pub=path.join(__dirname,'../web/public');
const store=new Map(),events=[];
const c={console,JSON,Math,Date,Object,Array,Number,String,isFinite,parseInt,
  localStorage:{getItem:k=>store.has(k)?store.get(k):null,setItem:(k,v)=>store.set(k,String(v)),removeItem:k=>store.delete(k)},
  CustomEvent:class{constructor(t,o){this.type=t;this.detail=o&&o.detail}},
  document:{getElementById:()=>null,createElement:()=>({}),head:{append(){}},documentElement:{append(){}}},
  addEventListener(){}};
c.window=c;c.dispatchEvent=e=>events.push(e.type);
vm.createContext(c);
vm.runInContext(fs.readFileSync(path.join(pub,'quake-filter.js'),'utf8'),c);
vm.runInContext(fs.readFileSync(path.join(pub,'gamma-palettes.js'),'utf8'),c);
const Q=c.StratumQuakes,G=c.StratumGamma,plain=o=>JSON.parse(JSON.stringify(o));

// quakes: one setting, open by default
assert.equal(Q.active(),false);
const ev=(t,mag,extra={})=>({t:Date.parse(t),mag,fixed:false,matched:false,src:'nrcan',...extra});
assert.equal(Q.pass(ev('2019-05-01T00:00Z',1.2)),true,'with no filter everything shows');
Q.set({from:'2020-01-01',to:'2023-12-31',magMin:1.5,magMax:3});
assert.deepEqual(plain(events),['stratum:quakefilter'],'a change is announced');
assert.equal(Q.active(),true);
assert.equal(Q.pass(ev('2019-12-31T23:59Z',2)),false,'before the range');
assert.equal(Q.pass(ev('2020-01-01T00:00Z',2)),true,'the first day counts');
assert.equal(Q.pass(ev('2023-12-31T23:59Z',2)),true,'the last day counts, all of it');
assert.equal(Q.pass(ev('2024-01-01T00:00Z',2)),false,'after the range');
assert.equal(Q.pass(ev('2021-06-01T00:00Z',1.4)),false,'below the minimum magnitude');
assert.equal(Q.pass(ev('2021-06-01T00:00Z',3.1)),false,'above the maximum magnitude');
assert.equal(Q.pass(ev('2021-06-01T00:00Z',null)),false,'no magnitude when a magnitude range is set');
Q.set({hideFixed:true,onlyMatched:true,onlyRelocated:true});
assert.equal(Q.pass(ev('2021-06-01T00:00Z',2,{fixed:true,matched:true,src:'bcsrc'})),false,'undetermined depth hidden');
assert.equal(Q.pass(ev('2021-06-01T00:00Z',2,{matched:false,src:'bcsrc'})),false,'not on a stage');
assert.equal(Q.pass(ev('2021-06-01T00:00Z',2,{matched:true,src:'nrcan'})),false,'not relocated');
assert.equal(Q.pass(ev('2021-06-01T00:00Z',2,{matched:true,src:'bcsrc'})),true);
// a catalogue row: a missing depth is an undetermined one
const row=['2023-02-03T04:05:06Z',56.7,-122.1,null,2.1,'ML',false,false,'bcsrc',300,400,['40070','12','during',0,1.2,null]];
assert.deepEqual(plain(Q.fromRow(row)),{t:Date.parse(row[0]),mag:2.1,fixed:true,matched:true,src:'bcsrc'});
assert.equal(plain(Q.mapFilter())[0],'all','the map gets one expression');
assert.match(Q.describe(),/solved depths only/);
Q.set({});
assert.equal(Q.active(),false,'cleared');assert.equal(store.has('stratum.quakeFilter'),false,'an empty filter leaves no setting behind');
assert.equal(Q.mapFilter(),null,'and no map filter');
// nonsense in storage is ignored, not obeyed
store.set('stratum.quakeFilter',JSON.stringify({from:'yesterday',magMin:'x',hideFixed:'yes'}));
assert.deepEqual(plain(Q.get()),{from:null,to:null,magMin:null,magMax:null,hideFixed:true,onlyMatched:false,onlyRelocated:false});

// gamma: four schemes, amber by default, a stored choice obeyed and an unknown one not
assert.deepEqual(plain(Object.keys(G.PALETTES)),['amber','viridis','sandshale','coolwarm']);
assert.equal(G.current(),'amber');
G.set('viridis');assert.equal(G.current(),'viridis');
store.set('stratum.gammaPalette','rainbow');assert.equal(G.current(),'amber','unknown schemes fall back to amber');
const scale={lo:70,hi:180,p50:114};
assert.equal(G.position(70,scale,'amber'),0);assert.equal(G.position(180,scale,'amber'),1);
assert.equal(G.position(30,scale,'amber'),0,'below the scale clamps');assert.equal(G.position(400,scale,'amber'),1);
assert.equal(G.position(114,scale,'coolwarm'),0.5,'cool to warm puts the median in the middle');
assert(G.position(100,scale,'coolwarm')<0.5&&G.position(130,scale,'coolwarm')>0.5);
assert.equal(G.steps(24,'sandshale').length,24);
assert.equal(G.bucket(180,scale,24,'amber'),23);
assert.match(G.ink(120,scale,'viridis'),/^rgb\(\d+,\d+,\d+\)$/);
console.log('PASS: quake filter rules and gamma colour schemes');
