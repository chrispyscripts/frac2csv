// The well charts page lays a well's stages on the clock for FracView the way
// the Lab's fvLayout does, and turns Stratum's series into the Lab's channels.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/public/wellview.js'),'utf8');
const between=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
const plain=o=>JSON.parse(JSON.stringify(o));
const c={Date,Math,Number,String,Float64Array,isFinite,parseFloat};
vm.createContext(c);
vm.runInContext(between('const SERIES = [','let W = null;'),c);
vm.runInContext(between('function niceCeil','const tMax'),c);
vm.runInContext('var tMax = st => Math.max(st.dsec, (st.n - 1) * st.dsec);',c);
vm.runInContext(between('function buildStages','// ---------- page'),c);
vm.runInContext(between('function fvLayout','function fvPayload'),c);

// series -> channels: Lab names and colours, nulls as gaps, an axis top rounded up
const st=c.buildStages({units:{press:'MPa',rate:'m3/min'},stages:[
  {label:'2',date:'2019-02-16',start:'13:00:00',step_s:10,series:{press:[1,null,58.2],rate:[null,null,null]}},
  {label:'1',date:'2019-02-16',start:'12:00:00',step_s:10,series:{press:[0,40,41]}},
  {label:'3',top_m:4000}]});
assert.deepEqual(st.map(s=>s.label),['1','2'],'ordered by stage; a stage with no curves is left out');
const ch=st[1].channels;
assert.equal(ch.length,1,'an all-null curve is not a channel');
assert.equal(ch[0].name,'Tr Press');assert.equal(ch[0].unit,'MPa');assert.equal(ch[0].hi,60);
assert(Number.isNaN(ch[0].values[1]),'null becomes a gap');

// clock layout: printed starts kept, a missing one placed after its neighbour,
// a backwards start reported as a jump and the axis ordered by time
const mk=(label,clock0,n=60,dsec=10)=>({label,clock0,n,dsec});
const t=Date.parse('2019-02-16T12:00:00');
let L=c.fvLayout([mk('1',t),mk('2',null),mk('3',t-3600e3)]);
assert.equal(L.synthetic,false);
assert.deepEqual(plain(L.order),[2,0,1],'ordered by start');
assert.deepEqual(plain(L.jumps),[],'a placed stage is never one side of a jump');
L=c.fvLayout([mk('1',t),mk('2',t-3600e3)]);
assert.deepEqual(plain(L.jumps),[{from:'1',to:'2',tFrom:t,tTo:t-3600e3}]);
L=c.fvLayout([mk('1',null),mk('2',null)]);
assert.equal(L.synthetic,true,'no clock anywhere -> a synthetic axis FracView will not label as real time');
assert.equal(L.starts[1]-L.starts[0],600e3,'stages laid end to end');
console.log('PASS: Lab channels from Stratum series, and FracView clock layout');
