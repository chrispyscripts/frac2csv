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
console.log(`PASS: Discover's ${rows.length} wells, nearest neighbours and filters`);
