// The wine rack and the 3D view coloured by stage metric, parent/child and frac
// date, shown "as of" a date -- on a real pad (gundy-01: its filed stages carry no
// depths, so the filed stage depths stand in), with metrics.js as the page loads
// it, without a browser.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const pub=path.join(__dirname,'../web/public');
const read=f=>fs.readFileSync(path.join(pub,f),'utf8');
const slice=(src,a,b)=>{const i=src.indexOf(a);assert(i>=0,'missing '+a);const j=src.indexOf(b,i);assert(j>i,'missing '+b);return src.slice(i,j)};
const plain=o=>JSON.parse(JSON.stringify(o));

(async()=>{
// ---------- metrics.js, reading the site's own data files ----------
const store=new Map(),root={dataset:{theme:'light'}};
const m={Promise,JSON,Math,Number,String,Object,Array,Set,Map,isFinite,Date,parseInt,encodeURIComponent,
  fetch:u=>{const f=path.join(pub,decodeURIComponent(u));return Promise.resolve(fs.existsSync(f)?{ok:true,json:()=>Promise.resolve(JSON.parse(fs.readFileSync(f,'utf8')))}:{ok:false,json:()=>Promise.resolve(null)})},
  localStorage:{getItem:k=>store.has(k)?store.get(k):null,setItem:(k,v)=>store.set(k,String(v)),removeItem:k=>store.delete(k)},
  document:{documentElement:root},CustomEvent:class{constructor(n,o){this.type=n;this.detail=o&&o.detail}},addEventListener(){},dispatchEvent(){}};
m.window=m;vm.createContext(m);vm.runInContext(read('metrics.js'),m);
const FM=m.FVMetrics;

// ---------- the rack: geometry, then the colour of each well where the line crosses it ----------
const rack=read('winerack.js');
const c={Math,Number,String,Object,Array,Set,Map,isFinite,Date,LANDING_M:400,colorBy:'pad',gamma:null,SG:null,FM,metric:'avgP',rels:null,
  padInk:i=>['#2563eb','#e8590c'][i%2]};
vm.createContext(c);
vm.runInContext(slice(rack,'const fmt =','\n'),c);
vm.runInContext(slice(rack,'function rackGeom(p)','function niceStep'),c);
// the file's const helpers live in the script scope: lift them where the test can call them
vm.runInContext('Object.assign(globalThis,{stageRow,stageValue,future,relOf,relLetter,dayOf,dayStr,spacingText,ago})',c);
const p=JSON.parse(read('data/region/pads/gundy-01.json'));
p.wells=p.wells.filter(w=>w.well.curves);
const k=Math.cos(p.lat*Math.PI/180),xy=(lon,lat)=>[(lon-p.lon)*111320*k,(lat-p.lat)*111320];
p.wells.forEach(w=>{const [wx,wz]=xy(w.well.lon,w.well.lat),t=w.trajectory;w.points=t.md.map((q,j)=>[wx+t.ew[j],-t.tvd[j],wz+t.ns[j]]).filter(q=>q.every(Number.isFinite));w.pad=p});
assert(p.wells.every(w=>w.stages.every(s=>s.top_m==null)),'gundy-01 files no stage depths: the case the fallback is for');
const g=c.rackGeom(p),R={id:'gundy-01',i:0,g,s:g.start};
for(const o of g.ws)o.mrows=new Map((await FM.rows('gundy-01',o.w.well.wa)).map(r=>[String(r.label),r]));
const hits=g.ws.map(o=>({o,x:c.rackCross(o,g.start)})).filter(h=>h.x&&!h.x.landing);
assert(hits.length>=8,'most wells are landed on the line');
assert(hits.every(h=>h.x.stage),'every landed well is in a stage: the filed stage depths stand in by number');
// the depth order matches the stage it is numbered as: stage 1 at the toe
const o0=g.ws[0],z=o0.zones;
assert.equal(z[z.length-1].s.label,'1','the deepest interval is stage 1');
assert(z.every((q,i)=>!i||q.z0>=z[i-1].z0),'zones run up the hole in order');
assert(z[z.length-1].s.proppant_t!=null,'and carries the filed summary for that stage');
// stage metric: the value for the stage the line is in, on the rack's own range
const all=g.ws.flatMap(o=>[...o.mrows.values()].map(r=>FM.value(r,'avgP')));
const dom=c.rackDomain(R,'avgP');
assert.deepEqual(plain(dom),plain(FM.domain(all,'avgP')),'the range spans every stage of the rack’s wells');
for(const h of hits){
  const row=h.o.mrows.get(String(h.x.stage.label));
  assert(row,'a metrics row for WA '+h.o.w.well.wa+' stage '+h.x.stage.label);
  assert.equal(c.stageValue(h.o,h.x,'avgP'),FM.value(row,'avgP'));
  assert.equal(c.inkFor('metric',R,h.o,h.x),FM.colour(FM.value(row,'avgP'),dom,'avgP'),'the marker wears the stage’s colour');
}
// a different line position, a different stage, and (usually) a different colour
const a1=hits[0],far=c.rackCross(a1.o,g.start+600);
assert(far&&far.stage&&far.stage.label!==a1.x.stage.label,'600 m on, the line is in another stage');
assert.equal(c.inkFor('metric',R,a1.o,far),FM.colour(c.stageValue(a1.o,far,'avgP'),dom,'avgP'));
// no row for the stage: the "none" colour, not a guess
assert.equal(c.inkFor('metric',R,{w:a1.o.w,mrows:new Map()},a1.x),FM.colour(null,dom,'avgP'),'a stage without a value is grey');
assert.equal(c.inkFor('metric',R,a1.o,{...a1.x,stage:null}),FM.colour(null,dom,'avgP'),'no stage at the line is grey');
// a new measure, a new range
const domProp=c.rackDomain(R,'prop');assert.notDeepEqual(plain(domProp),plain(dom));assert.equal(R.dom.k,'prop');
// pad colour stays the pad's
assert.equal(c.inkFor('pad',R,a1.o,a1.x),'#2563eb');

// ---------- as of a date ----------
const days=g.ws.map(o=>c.fracDays(o.w));
assert(days.every(d=>d[0]!=null&&d[1]>=d[0]),'every well has a frac start and end from its stage dates');
const sp=c.dateSpan(R);
assert.deepEqual(plain(sp),[Math.min(...days.map(d=>d[0])),Math.max(...days.map(d=>d[0]))]);
assert.equal(c.dayStr(c.dayOf('2019-02-16')),'2019-02-16');assert.equal(c.dayOf('20190216'),c.dayOf('2019-02-16'),'either date form');
assert.equal(g.ws.filter(o=>c.future(o.w,null)).length,0,'off ("All wells"): every well shows');
assert.equal(g.ws.filter(o=>c.future(o.w,sp[1])).length,0,'at the last start every well is fracked');
assert.equal(g.ws.filter(o=>!c.future(o.w,sp[0])).length,days.filter(d=>d[0]===sp[0]).length,'at the first start only the first well(s)');
const mid=Math.floor((sp[0]+sp[1])/2);
assert.deepEqual(g.ws.filter(o=>c.future(o.w,mid)).map(o=>o.w.well.wa),g.ws.filter(o=>c.fracDays(o.w)[0]>mid).map(o=>o.w.well.wa),'later starts are not fracked yet');
assert.equal(c.future({stages:[{date:null}],well:{}},mid),false,'a well with no dates on file always shows');
// frac date colour: oldest at one end of the ramp, newest at the other
const oldest=g.ws.find(o=>c.fracDays(o.w)[0]===sp[0]),newest=g.ws.find(o=>c.fracDays(o.w)[0]===sp[1]);
assert.equal(c.inkFor('date',R,oldest,null),FM.colour(0,[0,1]));assert.equal(c.inkFor('date',R,newest,null),FM.colour(1,[0,1]));

// ---------- parent/child: letters, words, distances ----------
c.rels=await FM.relations();
for(const [key,v] of Object.entries(FM.REL))assert.equal(c.relLetter({relation:key}),v.s);
assert.deepEqual(Object.values(FM.REL).map(v=>v.s),['P','C','S','–'],'the four letters');
assert.equal(c.relLetter(null),'','no label, no letter');
const r44=c.relOf({well:{wa:'028744'}});assert(r44,'leading zeros do not matter');
assert.equal(c.inkFor('relation',R,{w:{well:{wa:'28744'}}},null),FM.relColour(r44.relation));
assert.equal(c.inkFor('relation',R,{w:{well:{wa:'99999'}}},null),null,'a well with no label has no relation colour');
const fake={relation:'child',bounded:'half',parents:2,depletionDays:400,near:[
  {wa:'1',across:-296,vertical:-54,rel:'parent'},{wa:'2',across:120,vertical:30,rel:'parent'},{wa:'3',across:350,vertical:0,rel:'sibling'}]};
const lines=c.relationLines(fake).map(x=>x[0]);
assert.equal(lines[0],'Child (C): An offset was already producing when it was fracked');
assert.equal(lines[1],'Half-bounded (one side)');
assert.equal(lines[2],'Parents: WA 1, WA 2 · the longest produced 13 months before this frac');
assert.deepEqual(plain(lines.slice(4)),['WA 2: 120 m right, 30 m deeper · its parent','WA 1: 296 m left, 54 m shallower · its parent','WA 3: 350 m right, level · co-completed'],'nearest first, signed across and up/down in words');
assert.equal(c.relationLines({...fake,parents:1,depletionDays:45,near:[fake.near[0]]})[2][0],'Parent: WA 1 · produced 45 days before this frac');
// ---------- spacing along the top, and the limits note ----------
assert.equal(c.spacingLabel(312,45,200),'312 m / ↓45 m','deeper to the right: down');
assert.equal(c.spacingLabel(312,-45,200),'312 m / ↑45 m','shallower to the right: up');
assert.equal(c.spacingLabel(312,45,50),'312 m','no room: across only');
assert.equal(c.spacingLabel(312,.4,200),'312 m','level: across only');
assert.equal(c.spacingText(FM.limits()),'Spacing limits: 400 m across · 100 m vertical · 90 days');

// ---------- the 3D view: stage pieces along each lateral, whole-well colours, ghosts ----------
const ug=read('cluster-underground.js');
const u={Math,Number,String,Object,Array,Set,Map,isFinite,Date,window:{FVMetrics:FM},colorBy:'metric',hits:[],
  UK:{none:'#7b8e9a'},project:q=>q,path(){},ctx:new Proxy({},{get:()=>()=>{},set:()=>true})};
vm.createContext(u);
vm.runInContext(slice(ug,'function pointAt(w,md)','\n'),u);
vm.runInContext(slice(ug,'// ---------- Colour by stage metric','function resize()'),u);
vm.runInContext('Object.assign(globalThis,{UGX,ghost,dayOf,dayStr})',u);
const w=structuredClone(p.wells[0]);w.points=p.wells[0].points;w.depth_intervals=w.depth_intervals.filter(d=>d.top_m!=null);
const zs=u.stageZones(w);
assert.equal(zs.length,w.depth_intervals.length,'a zone per filed stage depth');
assert(zs.every((q,i)=>q.z0<q.mid&&q.mid<q.z1&&(!i||Math.abs(q.z0-zs[i-1].z1)<1e-9)),'zones abut, each round its stage');
const rows=new Map((await FM.rows('gundy-01',w.well.wa)).map(r=>[String(r.label),r]));
u.UGX.rows.set(w.well.wa.padStart(5,'0'),rows);
const vals=[...rows.values()].map(r=>FM.value(r,'avgP'));u.UGX.dom=FM.domain(vals,'avgP');
const S=u.metricSegs(w);
assert.equal(S.marks.length,zs.length,'a hover mark per stage');
for(const [col,segs] of S.by)for(const seg of segs){assert(seg.length>=2&&seg.every(q=>q.every(Number.isFinite)),'each piece is a run of points');}
for(const mk of S.marks){const want=FM.colour(FM.value(rows.get(mk.z.label),'avgP'),u.UGX.dom,'avgP');assert(S.by.get(want),'stage '+mk.z.label+' is drawn in its colour');}
assert.equal(u.metricSegs(w),S,'cached until something changes');u.UGX.ver++;assert.notEqual(u.metricSegs(w),S,'rebuilt after a change');
u.metricWell(w,false,true);u.metricHits(w);assert.equal(u.hits.length,zs.length,'stage hover targets');assert(u.hits.every(h=>h.m&&h.w===w));
// whole-well colours, cached per change
u.colorBy='relation';u.UGX.rel=c.rels;u.UGX.ver++;
assert.equal(u.wellInk(w),FM.relColour(c.rels.get(String(+w.well.wa)).relation));
u.colorBy='date';u.UGX.dateDom=[sp[0],sp[1]];u.UGX.ver++;
assert.equal(u.wellInk(w),FM.colour(u.fracDay(w),[sp[0],sp[1]]));
u.UGX.asOf=u.fracDay(w)-1;assert.equal(u.ghost(w),true,'fracked after the date: a ghost');
u.UGX.asOf=u.fracDay(w);assert.equal(u.ghost(w),false,'fracked on the date: drawn');
u.UGX.asOf=null;assert.equal(u.ghost(w),false,'off: drawn');
assert.equal(u.ghost({stages:[],well:{}}),false,'no dates: drawn');
console.log('PASS: rack colour at the line (stage metric, relation, frac date), as-of filter, relation letters and words, spacing labels; 3D stage pieces, well colours and ghosts');
})().catch(e=>{console.error(e);process.exitCode=1});
