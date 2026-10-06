// Exercise the shipped state transitions and hit generation without a browser.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/public/cluster-underground.js'),'utf8');
const between=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
const objects=new Map();
const element=()=>({hidden:false,disabled:false,value:'',textContent:'',scrollTop:0,style:{},focus(){},addEventListener(){}});
const nodes=new Map();
const overlay={classList:{add(){},remove(){}},setAttribute(){},querySelector(s){if(!nodes.has(s))nodes.set(s,element());return nodes.get(s)}};
const pads=[0,1].map(i=>({id:'pad-'+i,name:'Pad '+i,color:'#abcdef',point:[i*200,0,0],wells:[]}));
pads.forEach((p,i)=>p.wells.push({pad:p,well:{wa:String(i)},points:[[i*200,0,0],[i*200,-1000,1000]],stages:[{label:'2'}],depth_intervals:[{n:7,point:[i*200,-1000,700]}]}));
const initial={yaw:.91,pitch:-.2,scale:.27,target:[111,-800,245],pan:[55,-31]};
const plain=o=>JSON.parse(JSON.stringify(o));
const noop=()=>{};
const c={console,structuredClone,Math,JSON,Promise,data:{pads},pad:null,well:null,stage:null,interval:null,hover:null,entryCamera:null,
  camera:structuredClone(initial),goal:{scale:1,target:[0,0,0]},padMenu:element(),padPage:element(),returnButton:element(),canvas:element(),tip:element(),overlay,
  resize:noop,renderPanel:noop,fit(){c.camera.pan=[900,900];c.goal.target=[0,0,0];c.goal.scale=1;},
  active:true,hits:[],width:1000,height:800,raf:0,requestAnimationFrame:()=>1,path:noop,project:p=>p,
  ctx:new Proxy({},{get:()=>noop,set:()=>true}),draw:noop,
  sessionStorage:{setItem:(k,v)=>objects.set(k,v),getItem:k=>objects.get(k)||null,removeItem:k=>objects.delete(k)},
  addEventListener:noop,ready:Promise.resolve(),button:element(),
  map:{getCenter:()=>({toArray:()=>[-122,56]}),getZoom:()=>13,getBearing:()=>12,getPitch:()=>4,jumpTo:v=>{c.surface=v}},
  colorBy:'pad',GAMMA_INK:['#000','#111'],setColor:async m=>{c.colorBy=m},keyNav:noop,
  UK:{grid:'#4f7584',gridA:[.3,.12],depth:'#566b78',neutral:'#3d4f5b',none:'#7b8e9a',lit:'#0d8577',on:'#14212b',padOn:'#14212b',padRing:'#ffffff',glow:0,quake:'#d6336c'},
  sectionOn:false,padUrl:()=>'pad.html?embedded=1',
  rackHover:null,placeRackButtons:noop,loadArea:async()=>{},areaTitle:'Test area · Below the surface',showQuakes:false,areaName:''
};
vm.createContext(c);
vm.runInContext(between('function selectPad(id)','function renderPanel'),c);
c.selectPad('pad-0');assert.deepEqual(plain(c.entryCamera),initial);
c.selectPad('');c.camera=structuredClone(initial);c.selectPad('pad-0');
c.camera.yaw=2;c.camera.target[0]=999;
c.selectPad('pad-1');assert.equal(c.pad.id,'pad-0','neighbour pad must not become selected');
c.returnToCluster();assert.deepEqual(plain(c.camera),initial,'back restores every camera component');
assert.deepEqual(plain(c.goal.target),initial.target);
c.selectPad('pad-0');c.stage=c.well.stages[0];c.interval=c.well.depth_intervals[0];
overlay.querySelector('.ug-panel').scrollTop=43;
vm.runInContext(between('function draw(){','function resize()'),c);
c.draw();assert(c.hits.length>0);assert(c.hits.every(h=>h.p===c.pad),'background pads, toes and intervals have no hit targets');
// Gamma mode: a logged well gets per-bin hit targets on the locked pad only; an
// unlogged well (pad-1) draws dashed and must not throw or add gamma targets.
const logged=pads[0].wells[0];Object.assign(logged,{gmd0:0,gbin:5,gv:[90,null,120,140,60],gpts:[[0,0,0],[0,-5,0],[0,-10,0],[0,-15,0],[0,-20,0],[0,-25,0]],gby:[[0,4],[2,3]]});
c.colorBy='gamma';c.draw();const gh=c.hits.filter(h=>h.g!=null);
assert.deepEqual(plain(gh.map(h=>h.g)),[4],'bins 1,4,7… are hover targets; bin 1 has no reading so only 4 remains');assert(c.hits.every(h=>h.p===c.pad),'gamma targets stay on the locked pad');
c.colorBy='pad';
// Save the focused view, then simulate a fresh map page reached via Back.
const tail=between("const UG_KEY=",'(async()=>{let s=null');
vm.runInContext(tail,c);c.ugSave();
const saved=JSON.parse(objects.get('stratum.underground'));
assert.deepEqual(saved.entryCamera,initial);assert.equal(saved.stage,'2');assert.equal(saved.interval,7);assert.equal(saved.colorBy,'pad');assert.deepEqual(plain(saved.area),['pad-0','pad-1'],'the open area is saved, so Back reloads the same pads');assert.equal(saved.rack,undefined,'wine racks live in their own window now, not in the 3D view');
c.pad=null;c.well=null;c.entryCamera=null;c.camera={yaw:0,pitch:0,scale:1,target:[0,0,0],pan:[0,0]};c.draw=noop;
const restore=source.slice(source.indexOf('(async()=>{let s=null'),source.lastIndexOf('})();'));
(async()=>{
 await vm.runInContext(restore,c);
 assert.equal(c.pad.id,'pad-0');assert.equal(c.stage.label,'2');assert.equal(c.interval.n,7);
 assert.equal(overlay.querySelector('.ug-panel').scrollTop,43);
 assert.deepEqual(plain(c.camera.target),saved.target);
 c.returnToCluster();assert.deepEqual(plain(c.camera),initial,'well → pad → cluster restores original entry camera');
 console.log('PASS: exact camera restoration, locked neighbour hit targets, and well round-trip state');
})().catch(e=>{console.error(e);process.exitCode=1});
