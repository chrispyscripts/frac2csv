(() => {
'use strict';
const button=document.createElement('button');button.id='change-view';button.textContent='Change View';button.setAttribute('aria-label','Change View to underground cluster');document.body.append(button);
const overlay=document.createElement('section');overlay.id='underground';overlay.setAttribute('aria-label','Underground cluster explorer');overlay.setAttribute('aria-hidden','true');overlay.inert=true;
overlay.innerHTML=`<canvas aria-label="Interactive surveyed well paths. Select pads using the pad menu." tabindex="0"></canvas><div class="ug-head"><div><div class="ug-title">Gundy · Below the surface</div><div class="ug-sub">8 pads / 76 surveyed well paths · metres</div></div><div class="ug-tools"><button id="ug-all">All pads</button><button id="ug-reset">Reset camera</button><button id="ug-back">Surface view ↗</button></div></div><aside class="ug-panel"><label for="ug-pad">Explore the cluster</label><select id="ug-pad"><option value="">All pads</option></select><div id="ug-content" class="ug-summary">Loading directional surveys…</div></aside><div class="ug-hint">Drag to orbit · Shift-drag / right-drag to pan · Scroll to zoom · Click a pad to lock on<br>Survey geometry uses local surface-relative TVD; measured intervals are shown; treatment-stage matching is unverified.</div><div class="ug-tip"></div>`;
document.body.append(overlay);
const padPage=document.createElement('iframe');padPage.className='ug-pad-page';padPage.title='Pad data';padPage.hidden=true;overlay.append(padPage);
const returnButton=document.createElement('button');returnButton.id='ug-return';returnButton.textContent='← Back to underground';returnButton.hidden=true;overlay.querySelector('.ug-tools').prepend(returnButton);

const canvas=overlay.querySelector('canvas'),ctx=canvas.getContext('2d'),tip=overlay.querySelector('.ug-tip'),padMenu=overlay.querySelector('select'),content=overlay.querySelector('#ug-content');
let entryCamera=null;
let data=null,active=false,pad=null,well=null,stage=null,interval=null,hits=[],hover=null,width=0,height=0,drag=null,raf=0;
const camera={yaw:-.5,pitch:.4,scale:.085,target:[0,-1000,0],pan:[110,20]},goal={scale:.085,target:[0,-1000,0]};
function positionButton(){const r=document.querySelector('.legend').getBoundingClientRect();button.style.top=(r.bottom+10)+'px';button.style.width=r.width+'px';button.style.height=r.height+'px';button.classList.toggle('visible',map.getZoom()>=13);}
map.on('zoom',positionButton);new ResizeObserver(positionButton).observe(document.querySelector('.legend'));positionButton();
const ready=fetch('data/underground.json').then(r=>{if(!r.ok)throw Error('Unable to load cluster');return r.json()}).then(d=>{
 data=d;const origin=[d.pads[0].lon,d.pads[0].lat];const xy=(lon,lat)=>[(lon-origin[0])*111320*Math.cos(origin[1]*Math.PI/180),(lat-origin[1])*111320];
 d.pads.forEach((p,i)=>{p.color=PAD_COLORS[i%PAD_COLORS.length];const [x,z]=xy(p.lon,p.lat);p.point=[x,0,z];p.wells.forEach(w=>{const [wx,wz]=xy(w.well.lon,w.well.lat),t=w.trajectory;w.points=t.md.map((m,j)=>[wx+t.ew[j],-t.tvd[j],wz+t.ns[j]]).filter(q=>q.every(Number.isFinite));w.pad=p;w.depth_intervals=(w.depth_intervals||[]).map(d=>({...d,point:pointAt(w,(d.top_m+d.base_m)/2)}));});const opt=document.createElement('option');opt.value=p.id;opt.textContent=p.name+' · '+p.wells.length+' wells';padMenu.append(opt);});return d;
});
function pointAt(w,md){const t=w.trajectory;let i=t.md.findIndex(m=>m>=md);if(i<0)i=t.md.length-1;if(i===0)return w.points[0];const a=w.points[i-1],b=w.points[i],v=(md-t.md[i-1])/(t.md[i]-t.md[i-1]||1);return a.map((x,k)=>x+(b[k]-x)*v);}
function focusInterval(w,d){well=w;interval=d;goal.target=d.point.slice();goal.scale=Math.max(goal.scale,.45);camera.pan=[width>640?145:70,0];renderPanel();}
function fit(p){const points=(p?[p]:data.pads).flatMap(p=>p.wells.flatMap(w=>w.points));const min=[0,1,2].map(i=>Math.min(...points.map(q=>q[i]))),max=[0,1,2].map(i=>Math.max(...points.map(q=>q[i])));goal.target=min.map((v,i)=>(v+max[i])/2);
 const c=Math.cos(camera.yaw),s=Math.sin(camera.yaw),cp=Math.cos(camera.pitch),sp=Math.sin(camera.pitch);const projected=points.map(q=>{const x=q[0]-goal.target[0],y=q[1]-goal.target[1],z=q[2]-goal.target[2];return [x*c-z*s,y*cp-(x*s+z*c)*sp]});const lo=[0,1].map(i=>Math.min(...projected.map(q=>q[i]))),hi=[0,1].map(i=>Math.max(...projected.map(q=>q[i])));goal.scale=Math.max(.015,Math.min((width-(width>640?370:240))/(hi[0]-lo[0]),(height-230)/(hi[1]-lo[1]))*.9);camera.pan=[(width>640?145:85)-(lo[0]+hi[0])/2*goal.scale,15+(lo[1]+hi[1])/2*goal.scale];}

function selectPad(id){
 const next=data.pads.find(p=>p.id===id)||null;
 if(pad&&next&&next!==pad)return;
 if(next&&!pad){entryCamera=structuredClone(camera);pad=next;overlay.classList.add('pad-data');padPage.src='pad.html?set=gundy&pad='+encodeURIComponent(pad.id)+'&embedded=1';padPage.hidden=false;returnButton.hidden=false;padMenu.disabled=true;overlay.querySelector('#ug-all').hidden=true;overlay.querySelector('.ug-title').textContent=pad.name+' · Pad data';resize();}
 if(!next){pad=null;padPage.hidden=true;returnButton.hidden=true;overlay.classList.remove('pad-data');padMenu.disabled=false;overlay.querySelector('#ug-all').hidden=false;overlay.querySelector('.ug-title').textContent='Gundy · Below the surface';resize();}
 padMenu.value=pad?.id||'';well=pad?.wells[0]||null;stage=null;interval=null;hover=null;tip.style.display='none';fit(pad);renderPanel();
}
function returnToCluster(){if(!pad)return;const saved=entryCamera;selectPad('');if(saved){Object.assign(camera,structuredClone(saved));goal.scale=saved.scale;goal.target=saved.target.slice();}entryCamera=null;returnButton.hidden=true;canvas.focus();}
returnButton.onclick=returnToCluster;

function renderPanel(){content.replaceChildren();if(!pad){content.innerHTML='<div class="ug-stat">76 wells · 3,156 stage summaries · 3,172 depth intervals</div>Click any surface pad marker to focus its wine rack. Other pads remain visible.<p>All 76 wells have summaries and measured depth intervals.</p>';return;}
 const select=document.createElement('select');select.setAttribute('aria-label','Select well');pad.wells.forEach(w=>{const o=document.createElement('option');o.value=w.well.wa;o.textContent='WA '+w.well.wa+' · '+w.stages.length+' stages';select.append(o)});select.value=well.well.wa;select.onchange=()=>{well=pad.wells.find(w=>w.well.wa===select.value);stage=null;interval=null;renderPanel()};content.append(select);
 const title=document.createElement('div');title.textContent=well.well.name;content.append(title);
 const depthSelect=document.createElement('select');depthSelect.setAttribute('aria-label','Measured depth interval');const empty=document.createElement('option');empty.value='';empty.textContent='Measured intervals · select to focus';depthSelect.append(empty);well.depth_intervals.forEach(d=>{const o=document.createElement('option');o.value=d.n;o.textContent='Depth order '+d.n+' · '+fmt(d.top_m,1)+'–'+fmt(d.base_m,1)+' m';depthSelect.append(o)});depthSelect.value=interval?.n||'';depthSelect.onchange=()=>{const d=well.depth_intervals.find(d=>String(d.n)===depthSelect.value);if(d)focusInterval(well,d)};content.append(depthSelect);if(interval){const x=document.createElement('div');x.textContent='Selected interval: '+fmt(interval.top_m,1)+'–'+fmt(interval.base_m,1)+' m MD. Depth-order ID '+interval.n+'.';content.append(x)}
 const label=document.createElement('div');label.textContent='Treatment summaries (independent numbering)';content.append(label);
 const grid=document.createElement('div');grid.className='ug-stages';well.stages.forEach(s=>{const b=document.createElement('button');b.textContent=s.label;b.classList.toggle('on',stage===s);b.title='Stage '+s.label;b.onclick=()=>{stage=s;renderPanel()};grid.append(b)});content.append(grid);
 const info=document.createElement('div');const v=(x)=>x==null?'Not supplied':fmt(x,2);info.innerHTML=stage?`<strong>Stage ${stage.n}</strong><dl><dt>Average rate</dt><dd>${v(stage.avg_rate_m3_min)}${stage.avg_rate_m3_min==null?'':' m³/min'}</dd><dt>Proppant</dt><dd>${v(stage.proppant_t)}${stage.proppant_t==null?'':' t'}</dd><dt>Top / base MD</dt><dd>Not supplied</dd></dl>`:well.stages.length?'Choose a stage above.':'Stage data not supplied for this well.';if(stage){const date=document.createElement('div');date.textContent=stage.date||'Date not supplied';info.append(date)}
 const note=document.createElement('p');note.textContent='Depth-order IDs and treatment summaries are kept separate unless printed depths support their match. Open the well dashboard for treatment curves and the reconciliation details.';info.append(note);const link=document.createElement('a');link.href='wellview.html?wa='+encodeURIComponent(well.well.wa);link.textContent='Open well dashboard →';info.append(link);content.append(info);
}
function project(q){const x=q[0]-camera.target[0],y=q[1]-camera.target[1],z=q[2]-camera.target[2],c=Math.cos(camera.yaw),s=Math.sin(camera.yaw),xx=x*c-z*s,zz=x*s+z*c,cp=Math.cos(camera.pitch),sp=Math.sin(camera.pitch);return [width/2+camera.pan[0]+xx*camera.scale,height/2+camera.pan[1]-(y*cp-zz*sp)*camera.scale,zz*cp+y*sp];}
function path(points,color,lineWidth,alpha=1){ctx.beginPath();points.forEach((q,i)=>{const a=project(q);i?ctx.lineTo(a[0],a[1]):ctx.moveTo(a[0],a[1])});ctx.strokeStyle=color;ctx.lineWidth=lineWidth;ctx.globalAlpha=alpha;ctx.stroke();ctx.globalAlpha=1;}
function draw(){if(!active)return;raf=requestAnimationFrame(draw);camera.scale+=(goal.scale-camera.scale)*.11;camera.target=camera.target.map((v,i)=>v+(goal.target[i]-v)*.1);ctx.clearRect(0,0,width,height);hits=[];
 for(let d=0;d<=3000;d+=1000){for(let a=-6000;a<=6000;a+=1000){path([[a,-d,-6000],[a,-d,6000]],'#397082',.6,d===0?.22:.09);path([[-6000,-d,a],[6000,-d,a]],'#397082',.6,d===0?.22:.09)}const t=project([-3500,-d,0]);ctx.fillStyle='#7695a5';ctx.font='11px monospace';ctx.fillText(d+' m TVD',t[0],t[1]);}
 const wells=data.pads.flatMap(p=>p.wells).sort((a,b)=>project(a.points.at(-1))[2]-project(b.points.at(-1))[2]);
 wells.forEach(w=>{const selected=w===well,bright=!pad||w.pad===pad;path(w.points,w.pad.color,selected?3.5:bright?1.7:1,bright?.88:.25);const q=project(w.points.at(-1));ctx.beginPath();ctx.arc(q[0],q[1],selected?4:2,0,Math.PI*2);ctx.fillStyle=w.pad.color;ctx.globalAlpha=bright?1:.18;ctx.fill();ctx.globalAlpha=1;if(bright)hits.push({x:q[0],y:q[1],w,p:w.pad,r:8});w.depth_intervals.forEach(d=>{const a=project(d.point),on=interval===d||hover?.d===d;ctx.globalAlpha=bright?1:.22;ctx.fillStyle=on?'#ffffff':w.pad.color;ctx.fillRect(a[0]-(on?4:1.7),a[1]-(on?4:1.7),on?8:3.4,on?8:3.4);ctx.globalAlpha=1;if(bright)hits.push({x:a[0],y:a[1],w,p:w.pad,d,r:5})});});
 const labels=[];data.pads.forEach(p=>{const q=project(p.point),selectable=!pad||p===pad;ctx.globalAlpha=selectable?1:.18;const on=p===pad||hover?.p===p;ctx.beginPath();ctx.arc(q[0],q[1],on?10:7,0,Math.PI*2);ctx.fillStyle=on?'#e6fff7':p.color;ctx.shadowColor=p.color;ctx.shadowBlur=on?20:8;ctx.fill();ctx.shadowBlur=0;ctx.strokeStyle='#b4ebef';ctx.lineWidth=1;ctx.stroke();ctx.fillStyle=on?'#e6fff7':p.color;ctx.font=(on?'600 ':'')+'12px system-ui';let ly=q[1];while(labels.some(l=>Math.abs(l.x-q[0])<115&&Math.abs(l.y-ly)<20))ly+=22;labels.push({x:q[0],y:ly});if(ly!==q[1]){ctx.beginPath();ctx.moveTo(q[0]+7,q[1]);ctx.lineTo(q[0]+14,ly);ctx.strokeStyle=p.color;ctx.stroke();}ctx.fillText(p.name,q[0]+14,ly+4);if(selectable){hits.push({x:q[0],y:q[1],p,r:15});hits.push({x:q[0]+55,y:ly,p,r:14,label:true});}ctx.globalAlpha=1;});
}
function resize(){width=overlay.clientWidth;height=canvas.clientHeight;const d=devicePixelRatio||1;canvas.width=width*d;canvas.height=height*d;ctx.setTransform(d,0,0,d,0,0)}
button.onclick=async()=>{button.disabled=true;button.textContent='Loading…';try{await ready;active=true;overlay.inert=false;overlay.classList.add('active');overlay.setAttribute('aria-hidden','false');resize();selectPad('');camera.scale=goal.scale*.75;draw();overlay.querySelector('#ug-all').focus()}catch(e){button.textContent='Retry Change View';console.error(e)}finally{button.disabled=false;if(active)button.textContent='Change View'}};
function close(){active=false;cancelAnimationFrame(raf);overlay.classList.remove('active');overlay.setAttribute('aria-hidden','true');overlay.inert=true;button.focus()}
overlay.querySelector('#ug-back').onclick=close;overlay.querySelector('#ug-all').onclick=()=>selectPad('');overlay.querySelector('#ug-reset').onclick=()=>{camera.yaw=-.5;camera.pitch=.4;fit(pad)};padMenu.onchange=()=>selectPad(padMenu.value);
window.addEventListener('resize',()=>{resize();if(active)fit(pad)});overlay.addEventListener('keydown',e=>{if(e.key==='Escape'){if(pad)returnToCluster();else close()}});
canvas.oncontextmenu=e=>e.preventDefault();canvas.onpointerdown=e=>{drag={x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY,pan:e.shiftKey||e.button===2};canvas.setPointerCapture(e.pointerId);tip.style.display='none'};
canvas.onpointermove=e=>{if(drag){const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(drag.pan){camera.pan[0]+=dx;camera.pan[1]+=dy}else{camera.yaw+=dx*.006;camera.pitch=Math.max(-.9,Math.min(1.3,camera.pitch+dy*.005))}drag.x=e.clientX;drag.y=e.clientY;return}hover=[...hits].reverse().find(h=>Math.hypot(h.x-e.clientX,h.y-e.clientY)<h.r);canvas.style.cursor=hover?'pointer':'grab';tip.style.display=hover?'block':'none';if(hover){tip.textContent=hover.d?'WA '+hover.w.well.wa+' · depth order '+hover.d.n+' · '+fmt(hover.d.top_m,1)+'–'+fmt(hover.d.base_m,1)+' m MD':hover.w?'WA '+hover.w.well.wa+' · '+hover.w.stages.length+' stage summaries':hover.p.name+' · '+hover.p.wells.length+' wells · Click to lock';tip.style.left=Math.min(width-270,e.clientX+16)+'px';tip.style.top=Math.min(height-65,e.clientY+16)+'px'}};
canvas.onpointerup=e=>{if(drag&&Math.hypot(e.clientX-drag.startX,e.clientY-drag.startY)<5){const hit=[...hits].reverse().find(h=>Math.hypot(h.x-e.clientX,h.y-e.clientY)<h.r);if(hit&&(!pad||hit.p===pad)){if(!pad)selectPad(hit.p.id);if(hit.w){well=hit.w;if(hit.d)focusInterval(well,hit.d);else renderPanel()}}}drag=null};canvas.onpointercancel=()=>drag=null;canvas.onpointerleave=()=>{hover=null;tip.style.display='none'};
canvas.addEventListener('wheel',e=>{e.preventDefault();goal.scale=Math.max(.012,Math.min(2,goal.scale*Math.exp(-e.deltaY*.0015)))},{passive:false});

// Leaving for a well view and coming back should land where you were, not at the
// default cluster. The camera, the focused pad and the selected well are stashed
// for this tab only, and restored once, so a normal close still reopens clean.
const UG_KEY='stratum.underground';
function ugSave(){if(!active)return;try{sessionStorage.setItem(UG_KEY,JSON.stringify({
 yaw:camera.yaw,pitch:camera.pitch,scale:camera.scale,target:camera.target.slice(),pan:camera.pan.slice(),
 pad:pad?pad.id:'',wa:well&&well.well?well.well.wa:'',entryCamera,
 stage:stage?stage.label:null,interval:interval?interval.n:null,
 panelScroll:overlay.querySelector('.ug-panel').scrollTop,
 surface:{center:map.getCenter().toArray(),zoom:map.getZoom(),bearing:map.getBearing(),pitch:map.getPitch()}}))}catch(e){}}
function ugClear(){try{sessionStorage.removeItem(UG_KEY)}catch(e){}}
addEventListener('pagehide',ugSave);
overlay.querySelector('#ug-back').addEventListener('click',ugClear);
(async()=>{let s=null;try{s=JSON.parse(sessionStorage.getItem(UG_KEY)||'null')}catch(e){}
 if(!s)return;ugClear();
 try{await ready}catch(e){return}
 active=true;overlay.inert=false;overlay.classList.add('active');overlay.setAttribute('aria-hidden','false');resize();
 selectPad(s.pad||'');
 if(s.wa&&pad){const w=pad.wells.find(x=>x.well&&x.well.wa===s.wa);if(w){well=w;stage=w.stages.find(x=>x.label===s.stage)||null;interval=w.depth_intervals.find(x=>x.n===s.interval)||null;renderPanel()}}
 if(s.entryCamera)entryCamera=structuredClone(s.entryCamera);
 overlay.querySelector('.ug-panel').scrollTop=s.panelScroll||0;
 if(s.surface)map.jumpTo(s.surface);
 camera.yaw=s.yaw;camera.pitch=s.pitch;camera.scale=s.scale;
 camera.pan=s.pan.slice();camera.target=s.target.slice();
 goal.scale=s.scale;goal.target=s.target.slice();
 draw();button.textContent='Change View';
})();
})();
