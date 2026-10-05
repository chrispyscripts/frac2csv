// The well section's geometry and stages, on a real well's files, without a browser.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const pub=path.join(__dirname,'../web/public');
const source=fs.readFileSync(path.join(pub,'wellsection.js'),'utf8');
const between=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
const c={Math,Number,String,Object,Array,Set,Map,isFinite,W:null};
vm.createContext(c);
vm.runInContext(between('function assemble(d, row)','function attachGamma()'),c);
vm.runInContext(between('function at(md)','// ---------- drawing'),c);

const WA='34346';
const d=JSON.parse(fs.readFileSync(path.join(pub,'data/wells',WA+'.json'),'utf8'));
const pad=JSON.parse(fs.readFileSync(path.join(pub,'data/region/pads',d.pad.id+'.json'),'utf8'));
const row=pad.wells.find(x=>String(x.well.wa)===WA);
const W=c.assemble(d,row);c.W=W;

// the section runs from the pad toward TD, so the toe is to the right of the pad
const end=W.traj[W.traj.length-1];
assert(end.vs>0,'TD sits ahead of the pad along the section');
assert(Math.abs(Math.hypot(end.ns,end.ew)-end.vs)<1,'the section line passes through TD');
assert.equal(W.heel,d.well.heel_md,'heel from the well file');
// stages: every filed stage with a depth, the Lab's curve stages marked
const curveLabels=new Set(d.stages.filter(s=>s.series&&Object.values(s.series).some(a=>Array.isArray(a)&&a.length)).map(s=>String(s.label)));
assert(W.stages.length>0);
assert.equal(W.stages.filter(s=>s.curves).length,curveLabels.size,'one curve mark per Lab stage');
assert(W.stages.every(s=>!s.curves||(s.series&&Array.isArray(s.series.press)&&s.step>0)),'a stage with curves carries them, for its hover chart');
for(let i=1;i<W.stages.length;i++){
  assert(W.stages[i].mid>=W.stages[i-1].mid,'stages in depth order');
  assert.equal(W.stages[i].z0,W.stages[i-1].z1,'hover zones meet without gaps');
}
// interpolation and the zone lookup agree with the stations
const stageAt=vm.runInContext('stageAt',c);   // a const: not on the context object
for(const s of W.stages)assert.equal(stageAt(s.mid),s,'a stage owns its own depth');
const t=W.traj,k=Math.floor(t.length/2),mid=(t[k].md+t[k+1].md)/2,p=c.at(mid);
assert(p.tvd>=Math.min(t[k].tvd,t[k+1].tvd)-1e-9&&p.tvd<=Math.max(t[k].tvd,t[k+1].tvd)+1e-9,'TVD interpolates between stations');
assert.equal(c.at(-50),t[0]);assert.equal(c.at(1e9),t[t.length-1]);
console.log('PASS: section line through TD, heel, stage zones and curve marks for WA '+WA);
