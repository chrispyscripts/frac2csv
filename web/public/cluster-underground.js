(() => {
'use strict';
const button=document.createElement('button');button.id='change-view';button.textContent='Change View';button.setAttribute('aria-label','Change View to underground cluster');document.body.append(button);
const overlay=document.createElement('section');overlay.id='underground';overlay.setAttribute('aria-label','Underground cluster explorer');overlay.setAttribute('aria-hidden','true');overlay.inert=true;
overlay.innerHTML=`<canvas aria-label="Interactive surveyed well paths. Select pads using the pad menu." tabindex="0"></canvas><div class="ug-head"><div><div class="ug-title">Below the surface</div><div class="ug-sub">Loading…</div></div><div class="ug-tools"><div class="ug-color" role="group" aria-label="Colour wells by"><span>Colour</span><button data-color="pad" aria-pressed="true">Pad</button><button data-color="gamma" aria-pressed="false">Gamma</button></div><button id="ug-all">All pads</button><button id="ug-reset">Reset camera</button><button id="ug-back">Surface view ↗</button></div></div><aside class="ug-panel"><label for="ug-pad">Explore the cluster</label><select id="ug-pad"><option value="">All pads</option></select><div id="ug-content" class="ug-summary">Loading directional surveys…</div></aside><div class="ug-hint">Drag to orbit · Shift-drag / right-drag to pan · Scroll to zoom · Click a pad to lock on<br>Survey geometry uses local surface-relative TVD; measured intervals are shown; treatment-stage matching is unverified.</div><div class="ug-tip"></div><div class="ug-legend" hidden></div>`;
document.body.append(overlay);
const padPage=document.createElement('iframe');padPage.className='ug-pad-page';padPage.title='Pad data';padPage.hidden=true;overlay.append(padPage);
const returnButton=document.createElement('button');returnButton.id='ug-return';returnButton.textContent='← Back to underground';returnButton.hidden=true;overlay.querySelector('.ug-tools').prepend(returnButton);

const canvas=overlay.querySelector('canvas'),ctx=canvas.getContext('2d'),tip=overlay.querySelector('.ug-tip'),padMenu=overlay.querySelector('select'),content=overlay.querySelector('#ug-content');
let entryCamera=null;
let data=null,active=false,pad=null,well=null,stage=null,interval=null,hits=[],hover=null,width=0,height=0,drag=null,raf=0,colorBy='pad',gamma=null;
const camera={yaw:-.5,pitch:.4,scale:.085,target:[0,-1000,0],pan:[110,20]},goal={scale:.085,target:[0,-1000,0]};
// Gamma ray, one amber hue: dark for low API (cleaner rock) up to cream for high
// (shalier). The darkest step still clears 2.3:1 on the lightest part of the
// backdrop, so a low reading never reads as a missing one; missing is dashed slate.
const GAMMA_RAMP=['#92500b','#ac5c00','#c36c00','#d57f00','#e29500','#eaad4a','#eec57e','#f2dcb1','#fef1d0'],GAMMA_N=24,GAMMA_NONE='#6b8290',NEUTRAL='#d6e6ee';
const GAMMA_INK=Array.from({length:GAMMA_N},(_,k)=>{const t=k/(GAMMA_N-1)*(GAMMA_RAMP.length-1),i=Math.min(GAMMA_RAMP.length-2,Math.floor(t)),f=t-i,rgb=s=>[1,3,5].map(j=>parseInt(s.slice(j,j+2),16)),a=rgb(GAMMA_RAMP[i]),b=rgb(GAMMA_RAMP[i+1]);return 'rgb('+a.map((x,j)=>Math.round(x+(b[j]-x)*f)).join(',')+')'});
function positionButton(){const r=document.querySelector('.legend').getBoundingClientRect();button.style.top=(r.bottom+10)+'px';button.style.width=r.width+'px';button.style.height=r.height+'px';const on=map.getZoom()>=12;button.classList.toggle('visible',on);if(on&&region&&!button.disabled&&!active){const n=areaIds().length;button.textContent=n?'Change View · '+n+' pad'+(n>1?'s':''):'Change View';}}
map.on('zoom',positionButton);map.on('moveend',positionButton);new ResizeObserver(positionButton).observe(document.querySelector('.legend'));positionButton();
// The region: every pad's position, so the 3D view can take whichever pads the
// map is showing. A pad's wells are fetched only when an area containing it opens.
let region=null,areaTitle='Below the surface';
const regionReady=fetch('data/region/index.json').then(r=>{if(!r.ok)throw Error('Unable to load the region');return r.json()}).then(d=>{region=d;positionButton();return d});
const padCache=new Map(),AREA_MAX=30;
function fetchPad(id){if(!padCache.has(id))padCache.set(id,fetch('data/region/pads/'+encodeURIComponent(id)+'.json').then(r=>{if(!r.ok)throw Error('pad '+id);return r.json()}));return padCache.get(id)}
const padDist=(a,lat,lon)=>Math.hypot(a.lat-lat,(a.lon-lon)*Math.cos(lat*Math.PI/180))*111.32;
// the pads in the map's view, nearest its centre first, at most AREA_MAX of them
// so the scene stays legible; an empty view takes the nearest few instead
function areaIds(){if(!region)return[];const b=map.getBounds(),c=map.getCenter(),near=p=>padDist(p,c.lat,c.lng);let ps=region.pads.filter(p=>b.contains([p.lon,p.lat]));if(!ps.length)ps=region.pads.slice().sort((x,y)=>near(x)-near(y)).slice(0,6);return ps.sort((x,y)=>near(x)-near(y)).slice(0,AREA_MAX).map(p=>p.id)}
// the pads around one pad, for opening the 3D view on it from the map
function idsAround(id,km=4){const c=region&&region.pads.find(p=>p.id===id);if(!c)return[];return region.pads.filter(p=>padDist(p,c.lat,c.lon)<=km).sort((x,y)=>padDist(x,c.lat,c.lon)-padDist(y,c.lat,c.lon)).slice(0,AREA_MAX).map(p=>p.id)}
async function loadArea(ids){await regionReady;const entries=ids.map(id=>region.pads.find(p=>p.id===id)).filter(Boolean);if(!entries.length)throw Error('No pads in this area');
 const raw=await Promise.all(entries.map(e=>fetchPad(e.id)));
 if(data&&pad)selectPad('');exitRack(true);rackLayer.replaceChildren();well=null;stage=null;interval=null;hover=null;
 // copies: the scene writes points, colours and caches onto its pads
 const d={pads:raw.map(p=>structuredClone(p))};data=d;
 const lat0=d.pads.reduce((a,p)=>a+p.lat,0)/d.pads.length,lon0=d.pads.reduce((a,p)=>a+p.lon,0)/d.pads.length;
 const xy=(lon,lat)=>[(lon-lon0)*111320*Math.cos(lat0*Math.PI/180),(lat-lat0)*111320];
 while(padMenu.options.length>1)padMenu.remove(1);
 d.pads.forEach((p,i)=>{p.color=PAD_COLORS[i%PAD_COLORS.length];const [x,z]=xy(p.lon,p.lat);p.point=[x,0,z];p.wells.forEach(w=>{const [wx,wz]=xy(w.well.lon,w.well.lat),t=w.trajectory;w.points=t.md.map((m,j)=>[wx+t.ew[j],-t.tvd[j],wz+t.ns[j]]).filter(q=>q.every(Number.isFinite));w.pad=p;w.depth_intervals=(w.depth_intervals||[]).filter(d=>d.top_m!=null).map(d=>({...d,point:pointAt(w,(d.top_m+(d.base_m??d.top_m))/2)}));});const opt=document.createElement('option');opt.value=p.id;opt.textContent=p.name+' · '+p.wells.length+' wells';padMenu.append(opt);});
 // the grid reaches past the furthest well, and down past the deepest
 const pts=d.pads.flatMap(p=>p.wells.flatMap(w=>w.points));d.gridR=Math.max(6000,Math.ceil(Math.max(...pts.map(q=>Math.max(Math.abs(q[0]),Math.abs(q[2]))))/1000)*1000+1000);d.gridD=Math.max(3000,Math.ceil(-Math.min(...pts.map(q=>q[1]))/1000)*1000);
 const fields={};entries.forEach(e=>{if(e.field)fields[e.field]=(fields[e.field]||0)+e.wells});const top=Object.entries(fields).sort((a,b)=>b[1]-a[1])[0];
 areaTitle=(top?top[0]+' area':'This area')+' · Below the surface';
 overlay.querySelector('.ug-title').textContent=areaTitle;
 overlay.querySelector('.ug-sub').textContent=`${d.pads.length} pads / ${d.pads.reduce((n,p)=>n+p.wells.length,0)} surveyed well paths · metres`;
 if(gamma)attachGamma(gamma);
 return d;}
// Gamma is an extra layer: if it fails to load, the view still opens in pad colours.
const gammaReady=fetch('data/gamma.json').then(r=>r.ok?r.json():null).then(g=>{if(g){gamma=g;if(data)attachGamma(g)}}).catch(e=>console.warn('gamma layer',e)).then(()=>{if(!gamma){const b=overlay.querySelector('[data-color=gamma]');b.disabled=true;b.title='Gamma data unavailable'}});
function gammaBucket(v){const s=gamma.scale;return Math.max(0,Math.min(GAMMA_N-1,Math.round((v-s.lo)/(s.hi-s.lo)*(GAMMA_N-1))))}
// Each bin becomes one segment of the path between its two MD edges; segments are
// grouped by colour once here so a frame strokes one path per colour, not per bin.
function attachGamma(g){gamma=g;const bin=g.bin_m;if(data)data.pads.forEach(p=>p.wells.forEach(w=>{const x=g.wells[String(w.well.wa).padStart(5,'0')];if(!x)return;w.gmd0=x.md0;w.gbin=bin;w.gv=x.v;w.gruns=x.runs;w.gpts=x.v.concat([null]).map((_,i)=>pointAt(w,x.md0+i*bin));w.gby=GAMMA_INK.map(()=>[]);x.v.forEach((v,i)=>{if(v!=null)w.gby[gammaBucket(v)].push(i)})}));renderLegend();}
function renderLegend(){const L=overlay.querySelector('.ug-legend');if(!gamma){L.hidden=true;return}const s=gamma.scale,all=data?data.pads.flatMap(p=>p.wells):[],n=all.filter(w=>w.gv).length,none=all.length-n;
 L.innerHTML=`<div class="ug-glabel">Wells coloured by gamma ray</div><div class="ug-gbar" style="background:linear-gradient(90deg,${GAMMA_RAMP.join(',')})"></div><div class="ug-gticks"><span>≤${s.lo}</span><span>${Math.round((s.lo+s.hi)/2)}</span><span>≥${s.hi} API</span></div><div class="ug-gticks ug-gends"><span>cleaner</span><span>shalier</span></div><div class="ug-gnone"><i></i>No gamma log · ${none} wells</div><div class="ug-gfoot">${n} of ${n+none} wells here have a gamma log loaded (so far the Gundy cluster's LAS files from the BCER eLibrary). Scale spans the laterals (P2–P98).</div>`;L.hidden=colorBy!=='gamma';}
async function setColor(m){if(m==='gamma'){await gammaReady;if(!gamma)m='pad'}colorBy=m;overlay.querySelectorAll('.ug-color button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.color===m)));renderLegend();if(data)renderPanel();renderRack();}
overlay.querySelectorAll('.ug-color button').forEach(b=>b.onclick=()=>setColor(b.dataset.color));
function pointAt(w,md){const t=w.trajectory;let i=t.md.findIndex(m=>m>=md);if(i<0)i=t.md.length-1;if(i===0)return w.points[0];const a=w.points[i-1],b=w.points[i],v=(md-t.md[i-1])/(t.md[i]-t.md[i-1]||1);return a.map((x,k)=>x+(b[k]-x)*v);}
function focusInterval(w,d){well=w;interval=d;goal.target=d.point.slice();goal.scale=Math.max(goal.scale,.45);camera.pan=[width>640?145:70,0];renderPanel();}
function fit(p){const points=(p?[p]:data.pads).flatMap(p=>p.wells.flatMap(w=>w.points));const min=[0,1,2].map(i=>Math.min(...points.map(q=>q[i]))),max=[0,1,2].map(i=>Math.max(...points.map(q=>q[i])));goal.target=min.map((v,i)=>(v+max[i])/2);
 const c=Math.cos(camera.yaw),s=Math.sin(camera.yaw),cp=Math.cos(camera.pitch),sp=Math.sin(camera.pitch);const projected=points.map(q=>{const x=q[0]-goal.target[0],y=q[1]-goal.target[1],z=q[2]-goal.target[2];return [x*c-z*s,y*cp-(x*s+z*c)*sp]});const lo=[0,1].map(i=>Math.min(...projected.map(q=>q[i]))),hi=[0,1].map(i=>Math.max(...projected.map(q=>q[i])));goal.scale=Math.max(.015,Math.min((width-(width>640?370:240))/(hi[0]-lo[0]),(height-230)/(hi[1]-lo[1]))*.9);camera.pan=[(width>640?145:85)-(lo[0]+hi[0])/2*goal.scale,15+(lo[1]+hi[1])/2*goal.scale];}

function selectPad(id){
 const next=data.pads.find(p=>p.id===id)||null;
 if(pad&&next&&next!==pad)return;
 if(rack&&rack!==next)exitRack(true);   // a rack belongs to one pad; leaving the pad closes it
 if(next&&!pad){entryCamera=structuredClone(camera);pad=next;overlay.classList.add('pad-data');padPage.src='pad.html?set='+encodeURIComponent(pad.set||'region')+'&pad='+encodeURIComponent(pad.id)+'&embedded=1';padPage.hidden=false;returnButton.hidden=false;padMenu.disabled=true;overlay.querySelector('#ug-all').hidden=true;overlay.querySelector('.ug-title').textContent=pad.name+' · Pad data';resize();}
 if(!next){pad=null;padPage.hidden=true;returnButton.hidden=true;overlay.classList.remove('pad-data');padMenu.disabled=false;overlay.querySelector('#ug-all').hidden=false;overlay.querySelector('.ug-title').textContent=areaTitle;resize();}
 padMenu.value=pad?.id||'';well=pad?.wells[0]||null;stage=null;interval=null;hover=null;tip.style.display='none';fit(pad);renderPanel();
}
function returnToCluster(){if(!pad)return;const saved=entryCamera;selectPad('');if(saved){Object.assign(camera,structuredClone(saved));goal.scale=saved.scale;goal.target=saved.target.slice();}entryCamera=null;returnButton.hidden=true;canvas.focus();}
returnButton.onclick=()=>{exitRack(true);returnToCluster()};

function renderPanel(){content.replaceChildren();if(!pad){const all=data.pads.flatMap(p=>p.wells),nS=all.reduce((n,w)=>n+(w.stages||[]).length,0),nI=all.reduce((n,w)=>n+w.depth_intervals.length,0),nG=all.filter(w=>w.gv).length;content.innerHTML=`<div class="ug-stat">${all.length} wells · ${fmt(nS)} stage summaries · ${fmt(nI)} stage depths</div>Click a pad marker to lock on to it, or press its Wine rack button. Other pads stay visible.<p>Stage summaries and depths are as filed with the BCER. Open a well for its treatment charts where the Lab has read its frac report.</p>`+(colorBy==='gamma'&&gamma?`<p>Gamma ray is drawn along ${nG} of these wells from their LAS logs. Hover a well for its reading; lock a pad and pick a well for its full log.</p>`:'');return;}
 const select=document.createElement('select');select.setAttribute('aria-label','Select well');pad.wells.forEach(w=>{const o=document.createElement('option');o.value=w.well.wa;o.textContent='WA '+w.well.wa+' · '+w.stages.length+' stages';select.append(o)});select.value=well.well.wa;select.onchange=()=>{well=pad.wells.find(w=>w.well.wa===select.value);stage=null;interval=null;renderPanel()};content.append(select);
 const title=document.createElement('div');title.textContent=well.well.name;content.append(title);
 const W_=well.well,facts=[W_.operator,W_.formation,W_.year,W_.cum_gas_e3m3!=null?fmt(W_.cum_gas_e3m3)+' e³m³ gas to date':null,W_.refracs?W_.refracs+' later completion'+(W_.refracs>1?'s':'')+' on file':null].filter(Boolean);if(facts.length){const f=document.createElement('div');f.className='ug-facts';f.textContent=facts.join(' · ');content.append(f)}
 if(colorBy==='gamma')gammaPanel(well);
 const depthSelect=document.createElement('select');depthSelect.setAttribute('aria-label','Measured depth interval');const empty=document.createElement('option');empty.value='';empty.textContent='Measured intervals · select to focus';depthSelect.append(empty);well.depth_intervals.forEach(d=>{const o=document.createElement('option');o.value=d.n;o.textContent='Depth order '+d.n+' · '+fmt(d.top_m,1)+'–'+fmt(d.base_m,1)+' m';depthSelect.append(o)});depthSelect.value=interval?.n||'';depthSelect.onchange=()=>{const d=well.depth_intervals.find(d=>String(d.n)===depthSelect.value);if(d)focusInterval(well,d)};content.append(depthSelect);if(interval){const x=document.createElement('div');x.textContent='Selected interval: '+fmt(interval.top_m,1)+'–'+fmt(interval.base_m,1)+' m MD. Depth-order ID '+interval.n+'.';content.append(x)}
 const label=document.createElement('div');label.textContent=well.stages[0]?.source==='BCER hydraulic fracture'?'Stage summaries as filed with the BCER':'Treatment summaries (independent numbering)';content.append(label);
 const grid=document.createElement('div');grid.className='ug-stages';well.stages.forEach(s=>{const b=document.createElement('button');b.textContent=s.label;b.classList.toggle('on',stage===s);b.title='Stage '+s.label;b.onclick=()=>{stage=s;renderPanel()};grid.append(b)});content.append(grid);
 const info=document.createElement('div');const v=(x)=>x==null?'Not supplied':fmt(x,2);info.innerHTML=stage?`<strong>Stage ${stage.n}</strong><dl><dt>Average rate</dt><dd>${v(stage.avg_rate_m3_min)}${stage.avg_rate_m3_min==null?'':' m³/min'}</dd><dt>Proppant</dt><dd>${v(stage.proppant_t)}${stage.proppant_t==null?'':' t'}</dd><dt>Max pressure</dt><dd>${v(stage.max_pressure_mpa)}${stage.max_pressure_mpa==null?'':' MPa'}</dd><dt>Fluid pumped</dt><dd>${v(stage.fluid_m3)}${stage.fluid_m3==null?'':' m³'}</dd><dt>Top / base MD</dt><dd>${stage.top_m!=null?fmt(stage.top_m,1)+'–'+fmt(stage.base_m,1)+' m':'Not supplied'}</dd></dl>`:well.stages.length?'Choose a stage above.':'Stage data not supplied for this well.';if(stage){const date=document.createElement('div');date.textContent=stage.date||'Date not supplied';info.append(date)}
 const note=document.createElement('p');note.textContent='Depth-order IDs and treatment summaries are kept separate unless printed depths support their match. The well charts show each stage\'s treatment curves: stage chart, stacked and FracView.';info.append(note);const link=document.createElement('a');link.href='wellview.html?wa='+encodeURIComponent(well.well.wa)+(stage?'&stage='+encodeURIComponent(stage.label):'');link.textContent='Open well charts →';info.append(link);content.append(info);
}
// The selected well's gamma as a log strip along MD: bar height and colour are both
// the reading, so the strip reads without the legend. Hover it for a value.
function gammaPanel(w){const box=document.createElement('div');box.className='ug-gamma';content.append(box);const head=document.createElement('div');head.className='ug-glabel';head.textContent='Gamma ray · API';box.append(head);
 if(!w.gv){box.append('No gamma log filed with the BCER for this well; its path is dashed.');return}
 const td=w.trajectory.md.at(-1),heel=w.well.heel_md||0,mdAt=i=>w.gmd0+(i+.5)*w.gbin,logged=w.gv.map((v,i)=>v==null?null:mdAt(i)).filter(m=>m!=null);
 const lat=w.gv.filter((v,i)=>v!=null&&mdAt(i)>=heel).sort((a,b)=>a-b),q=f=>lat.length?lat[Math.floor(f*(lat.length-1))]:null;
 const cv=document.createElement('canvas');cv.setAttribute('role','img');cv.setAttribute('aria-label','Gamma ray against measured depth, '+fmt(logged[0])+' to '+fmt(logged.at(-1))+' m');box.append(cv);
 const read=document.createElement('div');read.className='ug-gread';read.textContent='Hover the strip for a reading';box.append(read);
 const dl=document.createElement('dl');[['Lateral median',q(.5)==null?'–':q(.5)+' API'],['Lateral P10–P90',q(.1)==null?'–':q(.1)+'–'+q(.9)+' API'],['Logged',fmt(logged[0])+'–'+fmt(logged.at(-1))+' m MD']].forEach(([k,v])=>{const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=k;dd.textContent=v;dl.append(dt,dd)});box.append(dl);
 const src=document.createElement('div');src.className='ug-gsrc';src.textContent=w.gruns.map(r=>r.mnemonic+' · '+r.file).join(' + ');box.append(src);
 const W=cv.clientWidth||230,H=74,base=H-14,d=devicePixelRatio||1;cv.width=W*d;cv.height=H*d;const c=cv.getContext('2d');c.setTransform(d,0,0,d,0,0);const X=md=>md/td*W;
 c.strokeStyle='#29404c';c.beginPath();c.moveTo(0,base+.5);c.lineTo(W,base+.5);c.stroke();
 w.gv.forEach((v,i)=>{if(v==null)return;const x0=X(w.gmd0+i*w.gbin),h=Math.min(1,v/200)*(base-4);c.fillStyle=GAMMA_INK[gammaBucket(v)];c.fillRect(x0,base-h,Math.max(1,X(w.gbin)),h)});
 if(heel){c.strokeStyle='#93adb9';c.setLineDash([2,3]);c.beginPath();c.moveTo(X(heel)+.5,2);c.lineTo(X(heel)+.5,base);c.stroke();c.setLineDash([]);}
 if(interval){c.fillStyle='#ffffff';c.fillRect(X(interval.top_m),base+1,Math.max(2,X(interval.base_m-interval.top_m)),3)}
 c.fillStyle='#93adb9';c.font='10px system-ui';c.textBaseline='bottom';c.fillText('0 m',0,H);c.textAlign='right';c.fillText(fmt(td)+' m MD',W,H);if(heel){c.textAlign='center';c.fillText('heel',Math.min(W-60,Math.max(20,X(heel))),H)}
 cv.onpointermove=e=>{const md=(e.clientX-cv.getBoundingClientRect().left)/W*td,i=Math.floor((md-w.gmd0)/w.gbin),v=w.gv[i];read.textContent=fmt(md)+' m MD · '+(v==null?'no reading':'GR '+v+' API')};cv.onpointerleave=()=>{read.textContent='Hover the strip for a reading'};
}
function project(q){const x=q[0]-camera.target[0],y=q[1]-camera.target[1],z=q[2]-camera.target[2],c=Math.cos(camera.yaw),s=Math.sin(camera.yaw),xx=x*c-z*s,zz=x*s+z*c,cp=Math.cos(camera.pitch),sp=Math.sin(camera.pitch);return [width/2+camera.pan[0]+xx*camera.scale,height/2+camera.pan[1]-(y*cp-zz*sp)*camera.scale,zz*cp+y*sp];}
function path(points,color,lineWidth,alpha=1){ctx.beginPath();points.forEach((q,i)=>{const a=project(q);i?ctx.lineTo(a[0],a[1]):ctx.moveTo(a[0],a[1])});ctx.strokeStyle=color;ctx.lineWidth=lineWidth;ctx.globalAlpha=alpha;ctx.stroke();ctx.globalAlpha=1;}
function draw(){if(!active)return;raf=requestAnimationFrame(draw);camera.scale+=(goal.scale-camera.scale)*.11;camera.target=camera.target.map((v,i)=>v+(goal.target[i]-v)*.1);ctx.clearRect(0,0,width,height);hits=[];
 const GR=data.gridR||6000,GD=data.gridD||3000,GS=GR>12000?2000:1000;for(let d=0;d<=GD;d+=1000){for(let a=-GR;a<=GR;a+=GS){path([[a,-d,-GR],[a,-d,GR]],'#397082',.6,d===0?.22:.09);path([[-GR,-d,a],[GR,-d,a]],'#397082',.6,d===0?.22:.09)}const t=project([-GR*.6,-d,0]);ctx.fillStyle='#7695a5';ctx.font='11px monospace';ctx.fillText(d+' m TVD',t[0],t[1]);}
 const wells=data.pads.flatMap(p=>p.wells).sort((a,b)=>project(a.points.at(-1))[2]-project(b.points.at(-1))[2]);
 // In gamma mode colour means gamma only: pads, toes and intervals go neutral.
 const g=colorBy==='gamma',ink=c=>g?NEUTRAL:c;
 wells.forEach(w=>{const selected=w===well,bright=!pad||w.pad===pad;if(g)gammaWell(w,selected,bright);else path(w.points,w.pad.color,selected?3.5:bright?1.7:1,bright?.88:.25);const q=project(w.points.at(-1)),lit=rackHover===w.pad;ctx.beginPath();ctx.arc(q[0],q[1],selected?4:lit?5:2,0,Math.PI*2);ctx.fillStyle=lit?'#5ee2d0':ink(w.pad.color);ctx.globalAlpha=bright?1:.18;ctx.fill();ctx.globalAlpha=1;if(bright)hits.push({x:q[0],y:q[1],w,p:w.pad,r:8});w.depth_intervals.forEach(d=>{const a=project(d.point),on=interval===d||hover?.d===d,s=on?4:g?1.2:1.7;ctx.globalAlpha=bright?(g&&!on?.55:1):.22;ctx.fillStyle=on?'#ffffff':ink(w.pad.color);ctx.fillRect(a[0]-s,a[1]-s,s*2,s*2);ctx.globalAlpha=1;if(bright)hits.push({x:a[0],y:a[1],w,p:w.pad,d,r:5})});});
 const labels=[];data.pads.forEach(p=>{const q=project(p.point),selectable=!pad||p===pad,pc=ink(p.color);ctx.globalAlpha=selectable?1:.18;const on=p===pad||hover?.p===p;ctx.beginPath();ctx.arc(q[0],q[1],on?10:7,0,Math.PI*2);ctx.fillStyle=on?'#e6fff7':pc;ctx.shadowColor=pc;ctx.shadowBlur=on?20:8;ctx.fill();ctx.shadowBlur=0;ctx.strokeStyle='#b4ebef';ctx.lineWidth=1;ctx.stroke();ctx.fillStyle=on?'#e6fff7':pc;ctx.font=(on?'600 ':'')+'12px system-ui';let ly=q[1];while(labels.some(l=>Math.abs(l.x-q[0])<115&&Math.abs(l.y-ly)<20))ly+=22;labels.push({x:q[0],y:ly});if(ly!==q[1]){ctx.beginPath();ctx.moveTo(q[0]+7,q[1]);ctx.lineTo(q[0]+14,ly);ctx.strokeStyle=pc;ctx.stroke();}ctx.fillText(p.name,q[0]+14,ly+4);if(selectable){hits.push({x:q[0],y:q[1],p,r:15});hits.push({x:q[0]+55,y:ly,p,r:14,label:true});}ctx.globalAlpha=1;});
 placeRackButtons();
}
// The whole path dashed in slate first: where there is no reading (no LAS, or above
// the first logged depth) that is what shows; logged bins are stroked over it.
function gammaWell(w,selected,bright){ctx.setLineDash([3,4]);path(w.points,GAMMA_NONE,selected?1.8:1.1,bright?.85:.2);ctx.setLineDash([]);if(!w.gpts)return;
 const P=w.gpts.map(project);ctx.lineCap='round';ctx.lineWidth=selected?4.5:bright?2.4:1.2;ctx.globalAlpha=bright?.96:.22;
 w.gby.forEach((ix,k)=>{if(!ix.length)return;ctx.beginPath();ix.forEach(i=>{ctx.moveTo(P[i][0],P[i][1]);ctx.lineTo(P[i+1][0],P[i+1][1])});ctx.strokeStyle=GAMMA_INK[k];ctx.stroke()});
 ctx.globalAlpha=1;ctx.lineCap='butt';
 if(bright)for(let i=1;i<w.gv.length;i+=3)if(w.gv[i]!=null)hits.push({x:(P[i][0]+P[i+1][0])/2,y:(P[i][1]+P[i+1][1])/2,w,p:w.pad,g:i,r:5});}
function resize(){width=overlay.clientWidth;height=canvas.clientHeight;const d=devicePixelRatio||1;canvas.width=width*d;canvas.height=height*d;ctx.setTransform(d,0,0,d,0,0)}
async function openArea(ids,opts={}){button.disabled=true;button.textContent='Loading…';
 try{await loadArea(ids);active=true;overlay.inert=false;overlay.classList.add('active');overlay.setAttribute('aria-hidden','false');resize();selectPad('');camera.scale=goal.scale*.75;cancelAnimationFrame(raf);draw();
  if(opts.pad){selectPad(opts.pad);if(opts.rack&&pad)enterRack(pad)}else overlay.querySelector('#ug-all').focus();button.textContent='Change View'}
 catch(e){button.textContent='Retry Change View';console.error(e)}finally{button.disabled=false}}
button.onclick=()=>openArea(areaIds());
// for the map: open 3D on the pads around one pad, locked to it, or straight into its wine rack
window.stratum3D={open:(padId,opts={})=>openArea(idsAround(padId),{pad:padId,rack:!!opts.rack}),ready:regionReady};
function close(){exitRack(true);active=false;cancelAnimationFrame(raf);overlay.classList.remove('active');overlay.setAttribute('aria-hidden','true');overlay.inert=true;positionButton();button.focus()}
overlay.querySelector('#ug-back').onclick=close;overlay.querySelector('#ug-all').onclick=()=>selectPad('');overlay.querySelector('#ug-reset').onclick=()=>{camera.yaw=-.5;camera.pitch=.4;fit(pad)};padMenu.onchange=()=>selectPad(padMenu.value);
window.addEventListener('resize',()=>{resize();if(active&&!rack)fit(pad);renderRack()});overlay.addEventListener('keydown',e=>{if(e.key==='Escape'){if(rack)exitRack();else if(pad)returnToCluster();else close()}});
canvas.oncontextmenu=e=>e.preventDefault();canvas.onpointerdown=e=>{drag={x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY,pan:e.shiftKey||e.button===2};canvas.setPointerCapture(e.pointerId);tip.style.display='none'};
canvas.onpointermove=e=>{if(drag){const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(drag.pan){camera.pan[0]+=dx;camera.pan[1]+=dy}else{camera.yaw+=dx*.006;camera.pitch=Math.max(-.9,Math.min(1.3,camera.pitch+dy*.005))}drag.x=e.clientX;drag.y=e.clientY;return}hover=[...hits].reverse().find(h=>Math.hypot(h.x-e.clientX,h.y-e.clientY)<h.r);canvas.style.cursor=hover?'pointer':'grab';tip.style.display=hover?'block':'none';if(hover){tip.textContent=hover.d?'WA '+hover.w.well.wa+' · depth order '+hover.d.n+' · '+fmt(hover.d.top_m,1)+'–'+fmt(hover.d.base_m,1)+' m MD':hover.g!=null?'WA '+hover.w.well.wa+' · '+fmt(hover.w.gmd0+(hover.g+.5)*hover.w.gbin)+' m MD · GR '+hover.w.gv[hover.g]+' API':hover.w?'WA '+hover.w.well.wa+' · '+hover.w.stages.length+' stage summaries':hover.p.name+' · '+hover.p.wells.length+' wells · Click to lock';tip.style.left=Math.min(width-270,e.clientX+16)+'px';tip.style.top=Math.min(height-65,e.clientY+16)+'px'}};
canvas.onpointerup=e=>{if(drag&&Math.hypot(e.clientX-drag.startX,e.clientY-drag.startY)<5){const hit=[...hits].reverse().find(h=>Math.hypot(h.x-e.clientX,h.y-e.clientY)<h.r);if(hit&&(!pad||hit.p===pad)){if(!pad)selectPad(hit.p.id);if(hit.w){well=hit.w;if(hit.d)focusInterval(well,hit.d);else renderPanel()}}}drag=null};canvas.onpointercancel=()=>drag=null;canvas.onpointerleave=()=>{hover=null;tip.style.display='none'};
canvas.addEventListener('wheel',e=>{e.preventDefault();goal.scale=Math.max(.012,Math.min(2,goal.scale*Math.exp(-e.deltaY*.0015)))},{passive:false});

// ---------- Wine rack ----------
// A pad seen end-on: the camera turns to look straight down the laterals, then
// the scene becomes a 2D section across the pad, every well end placed by its
// offset across the pad and its true vertical depth -- the gun-barrel view an
// engineer reads spacing and landing benches off. Each end opens its well page.
let rack=null,rackEntry=null,rackHover=null,tweenRaf=0;
const rackLayer=document.createElement('div');rackLayer.className='ug-rackbtns';overlay.append(rackLayer);
const rackView=document.createElement('section');rackView.className='ug-rack';rackView.hidden=true;rackView.setAttribute('aria-label','Wine rack: the pad\'s well ends by offset and depth');
rackView.innerHTML='<div class="ug-rack-head"><button type="button" class="ug-rack-back">← 3D view</button><div><div class="ug-rack-title"></div><div class="ug-rack-sub"></div></div><div class="ug-rack-key"></div></div><svg role="group"></svg>';
overlay.append(rackView);
const SVGNS='http://www.w3.org/2000/svg',svgEl=(tag,attrs,parent)=>{const e=document.createElementNS(SVGNS,tag);for(const k in attrs)e.setAttribute(k,attrs[k]);if(parent)parent.append(e);return e};
// Per pad, once: the laterals' mean bearing, and each well's lateral and toe in
// the section plane. Across-pad offset uses the same axis the camera's screen x
// has once it faces down that bearing, so the turn hands over without a jump.
function rackGeom(p){if(p.rack)return p.rack;
 const ws=p.wells.map(w=>{const heel=w.well.heel_md||0,md=w.trajectory.md,lat=w.points.filter((q,j)=>md[j]>=heel);return {w,lat:lat.length>1?lat:w.points.slice(-2),toe:w.points.at(-1)}});
 let dx=0,dz=0;ws.forEach(o=>{const a=o.lat[0],b=o.lat.at(-1),L=Math.hypot(b[0]-a[0],b[2]-a[2])||1;dx+=(b[0]-a[0])/L;dz+=(b[2]-a[2])/L});
 const yaw=Math.atan2(dx,dz),c=Math.cos(yaw),s=Math.sin(yaw),u=q=>q[0]*c-q[2]*s;
 ws.forEach(o=>{o.trace=o.lat.map(q=>[u(q),-q[1]]);o.end=[u(o.toe),-o.toe[1]];});
 const mid=ws.reduce((a,o)=>a+o.end[0],0)/ws.length;ws.forEach(o=>{o.end[0]-=mid;o.trace.forEach(q=>q[0]-=mid)});
 ws.forEach(o=>{let best=null;ws.forEach(k=>{if(k===o)return;const h=k.end[0]-o.end[0],v=k.end[1]-o.end[1],d=Math.hypot(h,v);if(!best||d<best.d)best={d,h:Math.abs(h),v:Math.abs(v),k}});o.nn=best});
 return p.rack={yaw,az:(yaw*180/Math.PI+360)%360,ws,toeMid:[0,1,2].map(i=>ws.reduce((a,o)=>a+o.toe[i],0)/ws.length)};}
function lateralGamma(w){if(!w.gv)return null;const heel=w.well.heel_md||0,v=w.gv.filter((x,i)=>x!=null&&w.gmd0+(i+.5)*w.gbin>=heel).sort((a,b)=>a-b);return v.length?v[Math.floor(v.length/2)]:null}
function bottleInk(o){if(colorBy!=='gamma')return o.w.pad.color;const g=lateralGamma(o.w);return g==null?null:GAMMA_INK[gammaBucket(g)]}
// The buttons ride on each pad's cluster of toes as the scene turns; ones that
// would land on each other step down, the way the pad labels do.
function placeRackButtons(){if(!data)return;const placed=[];data.pads.forEach(p=>{let b=p.rackBtn;if(!b){b=p.rackBtn=document.createElement('button');b.type='button';b.className='ug-rackbtn';b.onclick=()=>enterRack(p);b.onmouseenter=b.onfocus=()=>{rackHover=p};b.onmouseleave=b.onblur=()=>{if(rackHover===p)rackHover=null};rackLayer.append(b)}
 const on=active&&!rack&&(!pad||p===pad),q=on?project(rackGeom(p).toeMid):null,vis=on&&q[0]>20&&q[0]<width-20&&q[1]>90&&q[1]<height-30;b.hidden=!vis;if(!vis)return;
 b.textContent=pad?'Wine rack ▸':'Wine rack';b.title='Wine rack: '+p.name+' seen end-on';b.setAttribute('aria-label',b.title);let y=q[1]+12;while(placed.some(l=>Math.abs(l.x-q[0])<90&&Math.abs(l.y-y)<30))y+=30;placed.push({x:q[0],y});b.style.transform=`translate(${Math.round(q[0])}px,${Math.round(y)}px) translateX(-50%)`;});}
function tweenCamera(to,ms,done){cancelAnimationFrame(tweenRaf);if(!ms){camera.yaw=to.yaw;camera.pitch=to.pitch;if(done)done();return}const from={yaw:camera.yaw,pitch:camera.pitch},t0=performance.now();
 const step=now=>{const k=ms?Math.min(1,(now-t0)/ms):1,e=k<.5?2*k*k:1-Math.pow(-2*k+2,2)/2;camera.yaw=from.yaw+(to.yaw-from.yaw)*e;camera.pitch=from.pitch+(to.pitch-from.pitch)*e;if(k<1)tweenRaf=requestAnimationFrame(step);else if(done)done()};tweenRaf=requestAnimationFrame(step);}
function enterRack(p,instant){if(!data||rack)return;if(!pad)selectPad(p.id);if(pad!==p)return;const g=rackGeom(p);
 rack=p;rackHover=null;rackEntry={yaw:camera.yaw,pitch:camera.pitch,scale:goal.scale,target:goal.target.slice()};
 let y=g.yaw;while(y-camera.yaw>Math.PI)y-=2*Math.PI;while(y-camera.yaw<-Math.PI)y+=2*Math.PI;   // the short way round
 goal.target=g.toeMid.slice();tip.style.display='none';
 tweenCamera({yaw:y,pitch:0},instant?0:750,()=>{if(rack!==p)return;overlay.classList.add('racking');rackView.hidden=false;renderRack();if(!instant)rackView.querySelector('.ug-rack-back').focus()});}
function exitRack(quiet){if(!rack)return;rack=null;overlay.classList.remove('racking');rackView.hidden=true;tip.style.display='none';const e=rackEntry;rackEntry=null;if(!e||quiet){cancelAnimationFrame(tweenRaf);return}goal.target=e.target;goal.scale=e.scale;tweenCamera({yaw:e.yaw,pitch:e.pitch},600);canvas.focus();}
rackView.querySelector('.ug-rack-back').onclick=()=>exitRack();
function niceStep(span,n){const raw=span/n,e=Math.pow(10,Math.floor(Math.log10(raw)));return [1,2,2.5,5,10].map(m=>m*e).find(s=>s>=raw)||10*e}
function renderRack(){if(!rack)return;const p=rack,g=rackGeom(p),svg=rackView.querySelector('svg');svg.replaceChildren();
 // on a phone the header wraps to several rows: start below whatever it takes
 rackView.style.top=innerWidth<=640?(overlay.querySelector('.ug-head').getBoundingClientRect().bottom+8)+'px':'';
 const W=svg.clientWidth,H=svg.clientHeight;if(!W||!H)return;svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
 const P={l:78,r:24,t:18,b:54},pw=W-P.l-P.r,ph=H-P.t-P.b;
 // framed on the ends, not the whole laterals: a lateral that drifts off the
 // pad's bearing would otherwise widen the section and crush the rack flat
 const xs=g.ws.map(o=>o.end[0]),ys=g.ws.map(o=>o.end[1]);
 let x0=Math.min(...xs),x1=Math.max(...xs),y0=Math.min(...ys),y1=Math.max(...ys);const mx=Math.max(30,(x1-x0)*.04),my=Math.max(8,(y1-y0)*.06);x0-=mx;x1+=mx;y0-=my;y1+=my;
 // inner room in pixels, not metres: the labels under the deepest end and the
 // half-bottle at each side need the same space whatever the pad's spread
 const small=W<520,R=small?8:12,ix=R+18,it=R+8,ib=small?R+20:R+36,X=v=>P.l+ix+(v-x0)/(x1-x0)*(pw-2*ix),Y=v=>P.t+it+(v-y0)/(y1-y0)*(ph-it-ib),ex=((ph-it-ib)/(y1-y0))/((pw-2*ix)/(x1-x0));
 const grid=svgEl('g',{class:'rk-grid'},svg),ys2=niceStep(y1-y0,6),xs2=niceStep(x1-x0,7);
 for(let v=Math.ceil(y0/ys2)*ys2;v<=y1;v+=ys2){svgEl('line',{x1:P.l,x2:P.l+pw,y1:Y(v),y2:Y(v)},grid);svgEl('text',{x:P.l-8,y:Y(v)+4,'text-anchor':'end'},grid).textContent=fmt(v)+' m'}
 for(let v=Math.ceil(x0/xs2)*xs2;v<=x1;v+=xs2){svgEl('line',{x1:X(v),x2:X(v),y1:P.t,y2:P.t+ph,class:v===0?'rk-zero':''},grid);svgEl('text',{x:X(v),y:P.t+ph+18,'text-anchor':'middle'},grid).textContent=(v>0?'+':v<0?'−':'')+fmt(Math.abs(v))+' m'}
 svgEl('text',{x:P.l+pw/2,y:H-8,'text-anchor':'middle',class:'rk-axis'},svg).textContent=small?'Across the pad · looking toward '+Math.round(g.az)+'°':'Across the pad, looking down the laterals toward '+Math.round(g.az)+'° (toe ends facing you)';
 svgEl('text',{x:14,y:P.t+ph/2,'text-anchor':'middle',class:'rk-axis',transform:`rotate(-90 14 ${P.t+ph/2})`},svg).textContent='True vertical depth';
 // laterals first, faint, so the ends sit on top of them
 const clip='rk-clip-'+p.id;svgEl('rect',{x:P.l,y:P.t,width:pw,height:ph},svgEl('clipPath',{id:clip},svg));
 const traces=svgEl('g',{class:'rk-traces','clip-path':`url(#${clip})`},svg);g.ws.forEach(o=>{const ink=bottleInk(o)||GAMMA_NONE;svgEl('polyline',{points:o.trace.map(q=>X(q[0]).toFixed(1)+','+Y(q[1]).toFixed(1)).join(' '),stroke:ink},traces)});
 const labels=[],ends=svgEl('g',{class:'rk-ends'},svg);
 g.ws.slice().sort((a,b)=>a.end[1]-b.end[1]).forEach(o=>{const w=o.w,cx=X(o.end[0]),cy=Y(o.end[1]),ink=bottleInk(o);
  const a=svgEl('a',{href:'wellview.html?wa='+encodeURIComponent(w.well.wa),class:'rk-end'+(w===well?' on':''),'aria-label':`${w.well.name}, WA ${w.well.wa}, toe at ${fmt(o.end[1])} metres true vertical depth. Open its charts.`},ends);
  svgEl('circle',{cx,cy,r:R,fill:ink||'#0b1620',class:ink?'':'rk-none'},a);
  const lh=small?13:26,bw=small?36:46;let ly=cy+R+15;const box=l=>labels.some(b=>Math.abs(b.x-cx)<bw&&Math.abs(b.y-l)<lh);if(box(ly))ly=cy-R-(small?6:18);labels.push({x:cx,y:ly});
  svgEl('text',{x:cx,y:ly,'text-anchor':'middle',class:'rk-wa'},a).textContent=w.well.wa;if(!small)svgEl('text',{x:cx,y:ly+12,'text-anchor':'middle',class:'rk-tvd'},a).textContent=fmt(o.end[1])+' m';
  a.addEventListener('pointerenter',e=>{const nn=o.nn,gm=lateralGamma(w);tip.innerHTML='';[[w.well.name,'b'],[`WA ${w.well.wa} · toe ${fmt(o.end[1])} m TVD · lateral ${fmt(w.well.lateral_m)} m`],nn?[`Nearest end: WA ${nn.k.w.well.wa}, ${fmt(nn.h)} m across, ${fmt(nn.v)} m vertical`]:null,gm!=null?[`Lateral gamma median ${gm} API`]:null,['Click to open its charts']].filter(Boolean).forEach(([t,b])=>{const d=document.createElement(b||'div');d.textContent=t;if(b)d.style.display='block';tip.append(d)});tip.style.display='block';const r=overlay.getBoundingClientRect();tip.style.left=Math.min(r.width-270,e.clientX-r.left+16)+'px';tip.style.top=Math.min(r.height-110,e.clientY-r.top+16)+'px'});
  a.addEventListener('pointerleave',()=>{tip.style.display='none'});});
 const n=g.ws.length;
 rackView.querySelector('.ug-rack-title').textContent=p.name+' · Wine rack';
 rackView.querySelector('.ug-rack-sub').textContent=`${n} well ends · toes ${fmt(Math.min(...g.ws.map(o=>o.end[1])))}–${fmt(Math.max(...g.ws.map(o=>o.end[1])))} m TVD · vertical exaggeration ×${ex.toFixed(1)}`;
 const key=rackView.querySelector('.ug-rack-key');key.replaceChildren();if(colorBy==='gamma'&&gamma){key.innerHTML=`<span>Lateral median gamma</span><i style="background:linear-gradient(90deg,${GAMMA_RAMP.join(',')})"></i><span>${gamma.scale.lo}–${gamma.scale.hi} API</span><span class="rk-nonekey">no log</span>`}else key.textContent='Click a well end to open its charts';
}

// Leaving for a well view and coming back should land where you were, not at the
// default cluster. The camera, the focused pad and the selected well are stashed
// for this tab only, and restored once, so a normal close still reopens clean.
const UG_KEY='stratum.underground';
function ugSave(){if(!active)return;try{sessionStorage.setItem(UG_KEY,JSON.stringify({
 yaw:camera.yaw,pitch:camera.pitch,scale:camera.scale,target:camera.target.slice(),pan:camera.pan.slice(),
 pad:pad?pad.id:'',wa:well&&well.well?well.well.wa:'',entryCamera,
 stage:stage?stage.label:null,interval:interval?interval.n:null,colorBy,rack:rack?rack.id:null,rackEntry,area:data?data.pads.map(p=>p.id):null,
 panelScroll:overlay.querySelector('.ug-panel').scrollTop,
 surface:{center:map.getCenter().toArray(),zoom:map.getZoom(),bearing:map.getBearing(),pitch:map.getPitch()}}))}catch(e){}}
function ugClear(){try{sessionStorage.removeItem(UG_KEY)}catch(e){}}
addEventListener('pagehide',ugSave);
overlay.querySelector('#ug-back').addEventListener('click',ugClear);
(async()=>{let s=null;try{s=JSON.parse(sessionStorage.getItem(UG_KEY)||'null')}catch(e){}
 if(!s)return;ugClear();
 try{if(!s.area)return;await loadArea(s.area)}catch(e){return}
 active=true;overlay.inert=false;overlay.classList.add('active');overlay.setAttribute('aria-hidden','false');resize();
 if(s.colorBy==='gamma')await setColor('gamma');
 selectPad(s.pad||'');
 if(s.wa&&pad){const w=pad.wells.find(x=>x.well&&x.well.wa===s.wa);if(w){well=w;stage=w.stages.find(x=>x.label===s.stage)||null;interval=w.depth_intervals.find(x=>x.n===s.interval)||null;renderPanel()}}
 if(s.entryCamera)entryCamera=structuredClone(s.entryCamera);
 overlay.querySelector('.ug-panel').scrollTop=s.panelScroll||0;
 if(s.surface)map.jumpTo(s.surface);
 camera.yaw=s.yaw;camera.pitch=s.pitch;camera.scale=s.scale;
 camera.pan=s.pan.slice();camera.target=s.target.slice();
 goal.scale=s.scale;goal.target=s.target.slice();
 if(s.rack&&pad&&pad.id===s.rack){enterRack(pad,true);if(s.rackEntry)rackEntry=s.rackEntry}
 draw();button.textContent='Change View';
})();
})();
