// Discover's tables (web/scripts/build_discover.py) and its filters (discover.js),
// on the region as built, without a browser.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const pub=path.join(__dirname,'../web/public');
const W=JSON.parse(fs.readFileSync(path.join(pub,'data/discover/wells.json'),'utf8'));
const S=JSON.parse(fs.readFileSync(path.join(pub,'data/discover/spacing.json'),'utf8'));
const rows=W.rows.map(r=>Object.fromEntries(W.columns.map((c,i)=>[c,r[i]])));

// the table: one row per well in the region, every column in every row
const region=JSON.parse(fs.readFileSync(path.join(pub,'data/region/index.json'),'utf8'));
assert.equal(rows.length,region.pads.reduce((n,p)=>n+p.wells,0),'every well in the region');
assert(W.rows.every(r=>r.length===W.columns.length));
assert.equal(new Set(rows.map(r=>r.wa)).size,rows.length,'each well once');
for(const k of ['proppantPerM','fluidPerM','stageSpacing','gasPerM','nnH'])assert(rows.filter(r=>r[k]!=null).length>rows.length*.5,k+' filled for most wells');
assert(rows.every(r=>r.maxP==null||r.maxP<=150),'impossible peak pressures left out');
// intensities agree with their totals
for(const r of rows.filter(r=>r.proppant&&r.lateral).slice(0,200))assert(Math.abs(r.proppantPerM-r.proppant/r.lateral)<0.01);
// the nearest neighbour is the first of the spacing list, and is a well in the table
const byWa=new Map(rows.map(r=>[r.wa,r]));
for(const r of rows.filter(r=>r.nn)){const nb=S.wells[r.wa][0];assert.equal(nb[0],r.nn);assert.equal(nb[1],r.nnH);assert(byWa.has(r.nn),'neighbour '+r.nn+' is a well')}
// spacing is symmetric enough: a well's nearest usually lists it back
let back=0,n=0;for(const r of rows.filter(r=>r.nn)){n++;if((S.wells[r.nn]||[]).some(x=>x[0]===r.wa))back++}
assert(back/n>.7,'most nearest neighbours see each other');

// the filters
const store=new Map(),c={console,JSON,Math,Number,String,Object,Array,Set,Map,isFinite,
  sessionStorage:{getItem:k=>store.get(k)??null,setItem:(k,v)=>store.set(k,v)},document:{},fetch:()=>Promise.reject()};
c.window=c;vm.createContext(c);vm.runInContext(fs.readFileSync(path.join(pub,'discover.js'),'utf8'),c);
const D=c.StratumDiscover,base={q:'',operator:'',formation:'',field:'',curves:false,quakes:false,ranges:{}};
const count=s=>rows.filter(w=>D.pass(w,{...base,...s})).length;
assert.equal(count({}),rows.length,'no filter, every well');
const tour='Tourmaline Oil Corp.';
assert.equal(count({operator:tour}),rows.filter(r=>r.operator===tour).length);
assert.equal(count({ranges:{year:{min:2021}}}),rows.filter(r=>r.year!=null&&r.year>=2021).length,'a minimum');
assert.equal(count({ranges:{proppantPerM:{min:1,max:2}}}),rows.filter(r=>r.proppantPerM!=null&&r.proppantPerM>=1&&r.proppantPerM<=2).length,'a range; wells without the measure are out');
assert.equal(count({curves:true}),rows.filter(r=>r.curves).length);
assert.equal(count({quakes:true}),rows.filter(r=>r.quakes).length);
assert.equal(count({q:'gundy'}),rows.filter(r=>`${r.name} ${r.wa} ${r.padName} ${r.field||''}`.toLowerCase().includes('gundy')).length,'search reads name, WA, pad and field');
assert.equal(count({operator:tour,ranges:{year:{min:2021}}}),rows.filter(r=>r.operator===tour&&r.year>=2021).length,'filters combine');
assert.equal(D.short('Canadian Natural Resources Limited'),'CNRL');assert.equal(D.short('Kelt Exploration Ltd.'),'Kelt');assert.equal(D.short(null),'Not filed');

// the new finder filters: parent/child and boundedness, production and curve measures, a month as text
for(const r of ['parent','child','co-completed','standalone'])assert.equal(count({relation:r}),rows.filter(w=>w.relation===r).length,'relation '+r);
assert.equal(['parent','child','co-completed','standalone'].reduce((n,r)=>n+count({relation:r}),0),rows.length,'every well has one relation');
for(const b of ['bounded','half','unbounded'])assert.equal(count({bounded:b}),rows.filter(w=>w.bounded===b).length,'bounded '+b);
assert.equal(count({relation:'child',bounded:'bounded'}),rows.filter(w=>w.relation==='child'&&w.bounded==='bounded').length,'relation and boundedness combine');
assert.equal(count({ranges:{gas12Per100m:{min:2000}}}),rows.filter(w=>w.gas12Per100m!=null&&w.gas12Per100m>=2000).length,'12-month gas per 100 m');
assert.equal(count({ranges:{firstProd:{min:'2020-01',max:'2021-12'}}}),rows.filter(w=>w.firstProd&&w.firstProd>='2020-01'&&w.firstProd<='2021-12').length,'first production between two months');
assert.equal(count({ranges:{depletionDays:{max:365}}}),rows.filter(w=>w.depletionDays!=null&&w.depletionDays<=365).length,'parents producing under a year');
assert.equal(count({ranges:{screenouts:{min:1}}}),rows.filter(w=>w.screenouts>=1).length,'wells with a possible screenout');
assert.equal(count({ranges:{propVsFiled:{min:.9,max:1.1}},curves:true}),rows.filter(w=>w.curves&&w.propVsFiled!=null&&w.propVsFiled>=.9&&w.propVsFiled<=1.1).length);
for(const [k] of [...D.RANGES,...D.RANGES2])assert(D.COL[k],'every range filter is a column: '+k);
assert(count({ranges:{peakGas:{min:100}},relation:'child'})>0&&count({ranges:{peakGas:{min:100}},relation:'child'})<count({relation:'child'}));

// Gutenberg–Richter on a synthetic sample: b = 1 from M 1.0 in 0.1 bins (seeded)
let seed=20261008;const rnd=()=>{seed=(seed+0x6D2B79F5)|0;let t=Math.imul(seed^(seed>>>15),1|seed);t=(t+Math.imul(t^(t>>>7),61|t))^t;return (((t^(t>>>14))>>>0)+.5)/4294967296};  // mulberry32
const mags=Array.from({length:2000},()=>Math.round((0.95-Math.log(rnd())/(1*Math.LN10))*10)/10);
const g=D.gr(mags);
assert.equal(g.n,2000);
assert(Math.abs(g.mc-1.2)<1e-9,'Mc by maximum curvature: the fullest bin (1.0) plus 0.2, got '+g.mc);
assert(Math.abs(g.b-1)<0.1,'b within 0.1 of 1, got '+g.b.toFixed(3));
assert(g.sb>0&&g.sb<0.06,'Shi & Bolt uncertainty about b/sqrt(n), got '+g.sb.toFixed(3));
assert.equal(g.nAbove,mags.filter(m=>m>=1.2-1e-9).length,'events at or above Mc');
assert(g.bins.every((b,i)=>i===0||b.cum<=g.bins[i-1].cum),'cumulative counts fall with magnitude');
assert.equal(g.bins[0].cum,2000);
// the moment and McGarr's bound
assert.equal(D.mcgarr(10000),3e14,'G·ΔV for 10,000 m³ at G = 30 GPa');
assert(Math.abs(D.moment(2)-10**12.1)<1e6,'M0 = 10^(1.5 M + 9.1)');
assert(Math.abs(D.segDist({x:1,y:1},{x:0,y:0},{x:2,y:0})-1)<1e-12&&Math.abs(D.segDist({x:3,y:0},{x:0,y:0},{x:2,y:0})-1)<1e-12,'distance to a segment, beside and past its end');

// type curves: aligned on the first producing month, P10 <= P50 <= P90, a stop below 5 wells
const P={through:'2026-08',wells:{}};
const fake=[];for(let i=0;i<8;i++){const wa=String(90000+i);fake.push({wa,lateral:2000,proppant:4000});P.wells[wa]={f:i<6?'2025-01':'2026-07',g:[310,280,248,240].map(v=>v*(1+i/10)),c:[0,0,0,0],o:[0,0,0,0],w:[1,1,1,1]}}
const tc=D.typeCurves(fake,P,{fluid:'gas',basis:'rate',norm:'none',months:4})[0];
assert.equal(tc.n,8);
assert.deepEqual(tc.months.map(m=>m.n),[8,8,6,6],'the two wells first producing 2026-07 have two months to August');
assert(Math.abs(tc.months[0].p50-D.pct([0,1,2,3,4,5,6,7].map(i=>310*(1+i/10)/(i<6?31:31)).sort((a,b)=>a-b),.5))<1e-9,'month 1 is each well’s first producing month, over its days');
assert(Math.abs(tc.months[1].p10-D.pct([0,1,2,3,4,5,6,7].map(i=>280*(1+i/10)/(i<6?28:31)).sort((a,b)=>a-b),.1))<1e-9,'month 2: February (28 days) for some, August (31) for the others');
const cum=D.typeCurves(fake,P,{fluid:'gas',basis:'cum',norm:'lat',months:4})[0];
assert(Math.abs(cum.months[1].p50-D.pct([0,1,2,3,4,5,6,7].map(i=>590*(1+i/10)*100/2000).sort((a,b)=>a-b),.5))<1e-9,'cumulative per 100 m');
assert.equal(D.typeCurves(fake,P,{fluid:'gas',basis:'rate',months:4,minN:7})[0].months[2].p50,null,'a curve stops where fewer wells remain');
const PR=JSON.parse(fs.readFileSync(path.join(pub,'data/prod/wells.json'),'utf8'));
const real=D.typeCurves(rows,PR,{fluid:'gas',basis:'rate',norm:'lat',months:36,keys:w=>[D.short(w.operator)]});
for(const grp of real)for(const m of grp.months){if(m.p50==null)continue;assert(m.p10<=m.p50&&m.p50<=m.p90,`P10 <= P50 <= P90 for ${grp.key} month ${m.m}`);assert(m.n>=5)}
for(const grp of real)assert(grp.months.every((m,i)=>i===0||m.n<=grp.months[i-1].n),'wells only drop out as months go on');

// child degradation on a hand-made pair, and on the region
const par1={wa:'1',gas12Per100m:1000},par2={wa:'2',gas12Per100m:500},par3={wa:'3',gas12Per100m:null};
const kid={wa:'9',relation:'child',gas12Per100m:600,parentWas:['1','2','3']};
const dg=D.degradation([kid,{...kid,wa:'8',relation:'parent'}],new Map([par1,par2,par3].map(w=>[w.wa,w])));
assert.equal(dg.length,1,'only children count');assert.equal(dg[0].parents.length,2,'parents without the number are left out');
assert(Math.abs(dg[0].ratio-0.8)<1e-12,'600 against the mean of 1000 and 500');
console.log(`PASS: Discover's ${rows.length} wells, nearest neighbours and filters; b ${g.b.toFixed(3)} ± ${g.sb.toFixed(3)} (Mc ${g.mc}) on the synthetic sample; type curves and child degradation`);
