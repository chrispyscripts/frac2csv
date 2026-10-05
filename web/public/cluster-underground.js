(() => {
'use strict';
const button=document.createElement('button');button.id='change-view';button.textContent='Change View';button.setAttribute('aria-label','Change View to underground cluster');document.body.append(button);
const overlay=document.createElement('section');overlay.id='underground';overlay.setAttribute('aria-label','Underground cluster explorer');overlay.setAttribute('aria-hidden','true');overlay.inert=true;
overlay.innerHTML=`<canvas aria-label="Interactive surveyed well paths. Select pads using the pad menu." tabindex="0"></canvas><div class="ug-head"><div><div class="ug-title">Below the surface</div><div class="ug-sub">Loading…</div></div><div class="ug-tools"><div class="ug-color" role="group" aria-label="Colour wells by"><span>Colour</span><button data-color="pad" aria-pressed="true">Pad</button><button data-color="gamma" aria-pressed="false">Gamma</button></div><button id="ug-quakes" type="button" aria-pressed="false" title="Earthquakes since 2013 (Earthquakes Canada)">Quakes</button><button id="ug-all">All pads</button><button id="ug-reset">Reset camera</button><button id="ug-back">Surface view ↗</button></div></div><aside class="ug-panel"><label for="ug-pad">Explore the cluster</label><select id="ug-pad"><option value="">All pads</option></select><div id="ug-content" class="ug-summary">Loading directional surveys…</div></aside><div class="ug-hint">Drag to orbit · Shift-drag / right-drag to pan · Scroll to zoom · Click a pad to lock on<br>Survey geometry uses local surface-relative TVD; measured intervals are shown; treatment-stage matching is unverified.</div><div class="ug-tip"></div><div class="ug-legend" hidden></div>`;
document.body.append(overlay);
const padPage=document.createElement('iframe');padPage.className='ug-pad-page';padPage.title='Pad data';padPage.hidden=true;overlay.append(padPage);
const returnButton=document.createElement('button');returnButton.id='ug-return';returnButton.textContent='← Back to underground';returnButton.hidden=true;overlay.querySelector('.ug-tools').prepend(returnButton);

const canvas=overlay.querySelector('canvas'),ctx=canvas.getContext('2d'),tip=overlay.querySelector('.ug-tip'),padMenu=overlay.querySelector('select'),content=overlay.querySelector('#ug-content');
let entryCamera=null;
let data=null,active=false,pad=null,well=null,stage=null,interval=null,hits=[],hover=null,width=0,height=0,drag=null,raf=0,colorBy='pad',gamma=null,quakes=null,showQuakes=false;
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
let region=null,areaTitle='Below the surface',areaName='';
const regionReady=fetch('data/region/index.json').then(r=>{if(!r.ok)throw Error('Unable to load the region');return r.json()}).then(d=>{region=d;positionButton();return d});
const padCache=new Map(),AREA_MAX=30;
function fetchPad(id){if(!padCache.has(id))padCache.set(id,fetch('data/region/pads/'+encodeURIComponent(id)+'.json').then(r=>{if(!r.ok)throw Error('pad '+id);return r.json()}));return padCache.get(id)}
const padDist=(a,lat,lon)=>Math.hypot(a.lat-lat,(a.lon-lon)*Math.cos(lat*Math.PI/180))*111.32;
// the map's setting: only wells with treatment charts, or every well
const chartedOnly=()=>!!(window.stratumWells&&window.stratumWells.chartedOnly());
const shownPads=()=>chartedOnly()?region.pads.filter(p=>p.curves):region.pads;
// the pads in the map's view, nearest its centre first, at most AREA_MAX of them
// so the scene stays legible; an empty view takes the nearest few instead
function areaIds(){if(!region)return[];const b=map.getBounds(),c=map.getCenter(),near=p=>padDist(p,c.lat,c.lng);let ps=shownPads().filter(p=>b.contains([p.lon,p.lat]));if(!ps.length)ps=shownPads().slice().sort((x,y)=>near(x)-near(y)).slice(0,6);return ps.sort((x,y)=>near(x)-near(y)).slice(0,AREA_MAX).map(p=>p.id)}
// the pads around one pad, for opening the 3D view on it from the map
function idsAround(id,km=4){const c=region&&region.pads.find(p=>p.id===id);if(!c)return[];return shownPads().filter(p=>padDist(p,c.lat,c.lon)<=km).sort((x,y)=>padDist(x,c.lat,c.lon)-padDist(y,c.lat,c.lon)).slice(0,AREA_MAX).map(p=>p.id)}
async function loadArea(ids){await regionReady;const entries=ids.map(id=>region.pads.find(p=>p.id===id)).filter(Boolean);if(!entries.length)throw Error('No pads in this area');
 const raw=await Promise.all(entries.map(e=>fetchPad(e.id)));
 // copies: the scene writes points, colours and caches onto its pads
 let pads=raw.map(p=>structuredClone(p));if(chartedOnly()){pads.forEach(p=>p.wells=p.wells.filter(w=>w.well.curves));pads=pads.filter(p=>p.wells.length);if(!pads.length)throw Error('No wells with treatment charts in this area')}
 if(data&&pad)selectPad('');exitRack(true);rackLayer.replaceChildren();well=null;stage=null;interval=null;hover=null;
 const d={pads};data=d;
 const lat0=d.pads.reduce((a,p)=>a+p.lat,0)/d.pads.length,lon0=d.pads.reduce((a,p)=>a+p.lon,0)/d.pads.length;
 const xy=(lon,lat)=>[(lon-lon0)*111320*Math.cos(lat0*Math.PI/180),(lat-lat0)*111320];d.xy=xy;
 while(padMenu.options.length>1)padMenu.remove(1);
 d.pads.forEach((p,i)=>{p.color=PAD_COLORS[i%PAD_COLORS.length];const [x,z]=xy(p.lon,p.lat);p.point=[x,0,z];p.wells.forEach(w=>{const [wx,wz]=xy(w.well.lon,w.well.lat),t=w.trajectory;w.points=t.md.map((m,j)=>[wx+t.ew[j],-t.tvd[j],wz+t.ns[j]]).filter(q=>q.every(Number.isFinite));w.pad=p;w.depth_intervals=(w.depth_intervals||[]).filter(d=>d.top_m!=null).map(d=>({...d,point:pointAt(w,(d.top_m+(d.base_m??d.top_m))/2)}));});const opt=document.createElement('option');opt.value=p.id;opt.textContent=p.name+' · '+p.wells.length+' wells';padMenu.append(opt);});
 // the grid reaches past the furthest well, and down past the deepest
 const pts=d.pads.flatMap(p=>p.wells.flatMap(w=>w.points));d.gridR=Math.max(6000,Math.ceil(Math.max(...pts.map(q=>Math.max(Math.abs(q[0]),Math.abs(q[2]))))/1000)*1000+1000);d.gridD=Math.max(3000,Math.ceil(-Math.min(...pts.map(q=>q[1]))/1000)*1000);
 const fields={};entries.forEach(e=>{if(e.field)fields[e.field]=(fields[e.field]||0)+e.wells});const top=Object.entries(fields).sort((a,b)=>b[1]-a[1])[0];
 areaTitle=(top?top[0]+' area':'This area')+' · Below the surface';
 overlay.querySelector('.ug-title').textContent=areaTitle;
 overlay.querySelector('.ug-sub').textContent=`${d.pads.length} pads / ${d.pads.reduce((n,p)=>n+p.wells.length,0)} surveyed well paths · metres`;
 if(gamma)attachGamma(gamma);
 if(quakes)attachQuakes();
 return d;}
// ---------- Earthquakes ----------
// Natural Resources Canada's catalog. Each event is a ring on the surface at its
// epicentre, sized by magnitude; where the network solved a depth a dashed line
// drops to it (more than half are reported at a fixed 1, 5 or 10 km and get no
// line). Each is checked against the frac jobs drawn here: a well whose stages
// ran from a day before to a week before the event, within 5 km, is named.
let gmmr=null;fetch('data/seismic/gmmr.json').then(r=>r.ok?r.json():null).then(g=>{gmmr=g;if(data&&pad)renderPanel()}).catch(()=>{});
const quakesReady=fetch('data/seismic/events.json').then(r=>r.ok?r.json():null).then(q=>{quakes=q;if(data)attachQuakes()}).catch(e=>console.warn('quakes',e));
const DAY=864e5;
function attachQuakes(){if(!quakes||!data||!data.xy)return;
 const byWa={};data.pads.forEach(p=>p.wells.forEach(w=>byWa[String(w.well.wa).padStart(5,'0')]=w));
 // catalogue depths are below sea level; the scene measures down from the wellheads
 const elev=data.pads.flatMap(p=>p.wells).reduce((a,w,_,all)=>a+(w.well.elev_m||0)/all.length,0);
 data.quakes=quakes.rows.map(r=>{const [x,z]=data.xy(r[2],r[1]),m=r[11];const e={t:Date.parse(r[0]),date:r[0].slice(0,16).replace('T',' ')+' UTC',x,z,depth:r[3]==null?null:r[3]*1000+elev,mag:r[4],type:r[5],fixed:!!r[6]||r[3]==null,industry:!!r[7],src:r[8],herr:r[9],derr:r[10],match:m};
  if(m){const w=byWa[m[0]];e.near=`coincides with the frac of WA ${m[0]}${w?' ('+w.pad.name+')':''}: stage ${m[1]} ${m[2]==='after'?'had ended '+m[3]+' min before':'was pumping'}, ${m[4]} km away`+(m[5]!=null?`, ${Math.abs(m[5])} m ${m[5]>0?'below':'above'} it`:'')}
  return e}).filter(e=>Math.abs(e.x)<=data.gridR&&Math.abs(e.z)<=data.gridR);}
function drawQuakes(){for(const e of data.quakes||[]){const s=project([e.x,0,e.z]),r=3+Math.max(0,e.mag)*2.6;
  if(!e.fixed){const h=project([e.x,-e.depth,e.z]);ctx.setLineDash([2,3]);ctx.strokeStyle='#ff5fa2';ctx.globalAlpha=.55;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(s[0],s[1]);ctx.lineTo(h[0],h[1]);ctx.stroke();ctx.setLineDash([]);ctx.globalAlpha=.9;ctx.fillStyle='#ff5fa2';ctx.beginPath();ctx.arc(h[0],h[1],2.2,0,Math.PI*2);ctx.fill();}
  ctx.globalAlpha=e.near?.5:e.src==='bcsrc'?.32:.18;ctx.fillStyle='#ff5fa2';ctx.beginPath();ctx.arc(s[0],s[1],r,0,Math.PI*2);ctx.fill();ctx.globalAlpha=e.near?1:.75;ctx.strokeStyle='#ff5fa2';ctx.lineWidth=e.near?1.8:1;ctx.stroke();ctx.globalAlpha=1;
  hits.push({x:s[0],y:s[1],q:e,r:Math.max(6,r)});}}
overlay.querySelector('#ug-quakes').onclick=async e=>{showQuakes=!showQuakes;e.currentTarget.setAttribute('aria-pressed',String(showQuakes));await quakesReady;if(data&&!data.quakes)attachQuakes();renderPanel()};

// Gamma is an extra layer: if it fails to load, the view still opens in pad colours.
const gammaReady=fetch('data/gamma.json').then(r=>r.ok?r.json():null).then(g=>{if(g){gamma=g;if(data)attachGamma(g)}}).catch(e=>console.warn('gamma layer',e)).then(()=>{if(!gamma){const b=overlay.querySelector('[data-color=gamma]');b.disabled=true;b.title='Gamma data unavailable'}});
function gammaBucket(v){const s=gamma.scale;return Math.max(0,Math.min(GAMMA_N-1,Math.round((v-s.lo)/(s.hi-s.lo)*(GAMMA_N-1))))}
// Each bin becomes one segment of the path between its two MD edges; segments are
// grouped by colour once here so a frame strokes one path per colour, not per bin.
function attachGamma(g){gamma=g;const bin=g.bin_m;if(data)data.pads.forEach(p=>p.wells.forEach(w=>{const x=g.wells[String(w.well.wa).padStart(5,'0')];if(!x)return;w.gmd0=x.md0;w.gbin=bin;w.gv=x.v;w.gruns=x.runs;w.gest=!!x.estimated;w.gfrom=x.from||[];w.gpts=x.v.concat([null]).map((_,i)=>pointAt(w,x.md0+i*bin));w.gby=GAMMA_INK.map(()=>[]);x.v.forEach((v,i)=>{if(v!=null)w.gby[gammaBucket(v)].push(i)})}));renderLegend();}
function renderLegend(){const L=overlay.querySelector('.ug-legend');if(!gamma){L.hidden=true;return}const s=gamma.scale,all=data?data.pads.flatMap(p=>p.wells):[],n=all.filter(w=>w.gv&&!w.gest).length,est=all.filter(w=>w.gest).length,none=all.length-n-est,E=gamma.estimate;
 L.innerHTML=`<div class="ug-glabel">Wells coloured by gamma ray</div><div class="ug-gbar" style="background:linear-gradient(90deg,${GAMMA_RAMP.join(',')})"></div><div class="ug-gticks"><span>≤${s.lo}</span><span>${Math.round((s.lo+s.hi)/2)}</span><span>≥${s.hi} API</span></div><div class="ug-gticks ug-gends"><span>cleaner</span><span>shalier</span></div><div class="ug-gnone ug-gest"><i></i>Estimated from offset logs · ${est} wells</div><div class="ug-gnone"><i></i>No gamma · ${none} wells</div><div class="ug-gfoot">${n} measured (LAS logs from the BCER eLibrary)${est&&E?`; ${est} estimated: neighbours' gamma at the same subsea depth, smoothed to ${E.smoothed_m} m. Tested on ${E.tested} logged wells, an estimate's lateral level is off by ${E.level_mae} API on average`:''}. Scale spans the laterals (P2–P98).</div>`;L.hidden=colorBy!=='gamma';}
async function setColor(m){if(m==='gamma'){await gammaReady;if(!gamma)m='pad'}colorBy=m;overlay.querySelectorAll('.ug-color button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.color===m)));renderLegend();if(data)renderPanel();renderRack();}
overlay.querySelectorAll('.ug-color button').forEach(b=>b.onclick=()=>setColor(b.dataset.color));
function pointAt(w,md){const t=w.trajectory;let i=t.md.findIndex(m=>m>=md);if(i<0)i=t.md.length-1;if(i===0)return w.points[0];const a=w.points[i-1],b=w.points[i],v=(md-t.md[i-1])/(t.md[i]-t.md[i-1]||1);return a.map((x,k)=>x+(b[k]-x)*v);}
function focusInterval(w,d){well=w;interval=d;goal.target=d.point.slice();goal.scale=Math.max(goal.scale,.45);camera.pan=[width>640?145:70,0];renderPanel();}
function fit(p){const points=(p?[p]:data.pads).flatMap(p=>p.wells.flatMap(w=>w.points));const min=[0,1,2].map(i=>Math.min(...points.map(q=>q[i]))),max=[0,1,2].map(i=>Math.max(...points.map(q=>q[i])));goal.target=min.map((v,i)=>(v+max[i])/2);
 const c=Math.cos(camera.yaw),s=Math.sin(camera.yaw),cp=Math.cos(camera.pitch),sp=Math.sin(camera.pitch);const projected=points.map(q=>{const x=q[0]-goal.target[0],y=q[1]-goal.target[1],z=q[2]-goal.target[2];return [x*c-z*s,y*cp-(x*s+z*c)*sp]});const lo=[0,1].map(i=>Math.min(...projected.map(q=>q[i]))),hi=[0,1].map(i=>Math.max(...projected.map(q=>q[i])));goal.scale=Math.max(.015,Math.min((width-(width>640?370:240))/(hi[0]-lo[0]),(height-230)/(hi[1]-lo[1]))*.9);camera.pan=[(width>640?145:85)-(lo[0]+hi[0])/2*goal.scale,15+(lo[1]+hi[1])/2*goal.scale];}

// the bottom panel shows the locked pad's data, or a well's section (wellsection-host.js) when asked
let sectionOn=false;
const padUrl=()=>'pad.html?set='+encodeURIComponent(pad.set||'region')+'&pad='+encodeURIComponent(pad.id)+'&embedded=1';
const viewPicked=()=>{if(window.stratumSection&&well)window.stratumSection.view(well.well.wa,stage?stage.label:null)};
const section={available:()=>active&&!!pad,showing:()=>sectionOn&&active&&!!pad,frame:()=>padPage,
 show:src=>{sectionOn=true;padPage.title='Well section';padPage.src=src},
 hide:()=>{if(!sectionOn)return;sectionOn=false;if(pad){padPage.title='Pad data';padPage.src=padUrl()}}};
function selectPad(id){
 const next=data.pads.find(p=>p.id===id)||null;
 if(pad&&next&&next!==pad)return;
 if(rack&&rack!==next)exitRack(true);   // a rack belongs to one pad; leaving the pad closes it
 if(next&&!pad){entryCamera=structuredClone(camera);pad=next;overlay.classList.add('pad-data');sectionOn=false;padPage.title='Pad data';padPage.src=padUrl();padPage.hidden=false;returnButton.hidden=false;padMenu.disabled=true;overlay.querySelector('#ug-all').hidden=true;overlay.querySelector('.ug-title').textContent=pad.name+' · Pad data';resize();}
 if(!next){pad=null;sectionOn=false;padPage.hidden=true;returnButton.hidden=true;overlay.classList.remove('pad-data');padMenu.disabled=false;overlay.querySelector('#ug-all').hidden=false;overlay.querySelector('.ug-title').textContent=areaTitle;resize();}
 padMenu.value=pad?.id||'';well=pad?.wells[0]||null;stage=null;interval=null;hover=null;tip.style.display='none';fit(pad);renderPanel();
}
function returnToCluster(){if(!pad)return;const saved=entryCamera;selectPad('');if(saved){Object.assign(camera,structuredClone(saved));goal.scale=saved.scale;goal.target=saved.target.slice();}entryCamera=null;returnButton.hidden=true;canvas.focus();}
returnButton.onclick=()=>{exitRack(true);returnToCluster()};

function renderPanel(){content.replaceChildren();if(!pad){const all=data.pads.flatMap(p=>p.wells),nS=all.reduce((n,w)=>n+(w.stages||[]).length,0),nI=all.reduce((n,w)=>n+w.depth_intervals.length,0),nG=all.filter(w=>w.gv).length;content.innerHTML=`<div class="ug-stat">${all.length} wells · ${fmt(nS)} stage summaries · ${fmt(nI)} stage depths</div>Click a pad marker to lock on to it, or press its Wine rack button. Other pads stay visible.<p>Stage summaries and depths are as filed with the BCER. Open a well for its treatment charts where the Lab has read its frac report.</p>`+(colorBy==='gamma'&&gamma?`<p>Gamma ray is drawn along ${nG} of these wells (${all.filter(w=>w.gest).length} of them estimated from offset logs, dashed). Hover a well for its reading; lock a pad and pick a well for its full log.</p>`:'')+(showQuakes&&data.quakes?quakeSummary():'');return;}
 const select=document.createElement('select');select.setAttribute('aria-label','Select well');pad.wells.forEach(w=>{const o=document.createElement('option');o.value=w.well.wa;o.textContent='WA '+w.well.wa+' · '+w.stages.length+' stages';select.append(o)});select.value=well.well.wa;select.onchange=()=>{well=pad.wells.find(w=>w.well.wa===select.value);stage=null;interval=null;renderPanel();viewPicked()};content.append(select);
 const title=document.createElement('div');title.textContent=well.well.name;content.append(title);
 if(window.stratumSection){const vw=document.createElement('button');vw.type='button';vw.className='ug-viewwell';vw.textContent='View well';vw.title='The whole well in 2D, below; pop it out to keep it beside this view';vw.onclick=()=>window.stratumSection.view(well.well.wa,stage?stage.label:null);content.append(vw);window.stratumSection.follow(well.well.wa,stage?stage.label:null)}
 const W_=well.well,facts=[W_.operator,W_.formation,W_.year,W_.cum_gas_e3m3!=null?fmt(W_.cum_gas_e3m3)+' e³m³ gas to date':null,W_.refracs?W_.refracs+' later completion'+(W_.refracs>1?'s':'')+' on file':null].filter(Boolean);if(facts.length){const f=document.createElement('div');f.className='ug-facts';f.textContent=facts.join(' · ');content.append(f)}
 if(colorBy==='gamma')gammaPanel(well);
 gmmrPanel(pad);
 const depthSelect=document.createElement('select');depthSelect.setAttribute('aria-label','Measured depth interval');const empty=document.createElement('option');empty.value='';empty.textContent='Measured intervals · select to focus';depthSelect.append(empty);well.depth_intervals.forEach(d=>{const o=document.createElement('option');o.value=d.n;o.textContent='Depth order '+d.n+' · '+fmt(d.top_m,1)+'–'+fmt(d.base_m,1)+' m';depthSelect.append(o)});depthSelect.value=interval?.n||'';depthSelect.onchange=()=>{const d=well.depth_intervals.find(d=>String(d.n)===depthSelect.value);if(d)focusInterval(well,d)};content.append(depthSelect);if(interval){const x=document.createElement('div');x.textContent='Selected interval: '+fmt(interval.top_m,1)+'–'+fmt(interval.base_m,1)+' m MD. Depth-order ID '+interval.n+'.';content.append(x)}
 const label=document.createElement('div');label.textContent=well.stages[0]?.source==='BCER hydraulic fracture'?'Stage summaries as filed with the BCER':'Treatment summaries (independent numbering)';content.append(label);
 const grid=document.createElement('div');grid.className='ug-stages';well.stages.forEach(s=>{const b=document.createElement('button');b.textContent=s.label;b.classList.toggle('on',stage===s);b.title='Stage '+s.label;b.onclick=()=>{stage=s;renderPanel()};grid.append(b)});content.append(grid);
 const info=document.createElement('div');const v=(x)=>x==null?'Not supplied':fmt(x,2);info.innerHTML=stage?`<strong>Stage ${stage.n}</strong><dl><dt>Average rate</dt><dd>${v(stage.avg_rate_m3_min)}${stage.avg_rate_m3_min==null?'':' m³/min'}</dd><dt>Proppant</dt><dd>${v(stage.proppant_t)}${stage.proppant_t==null?'':' t'}</dd><dt>Max pressure</dt><dd>${v(stage.max_pressure_mpa)}${stage.max_pressure_mpa==null?'':' MPa'}</dd><dt>Fluid pumped</dt><dd>${v(stage.fluid_m3)}${stage.fluid_m3==null?'':' m³'}</dd><dt>Top / base MD</dt><dd>${stage.top_m!=null?fmt(stage.top_m,1)+'–'+fmt(stage.base_m,1)+' m':'Not supplied'}</dd></dl>`:well.stages.length?'Choose a stage above.':'Stage data not supplied for this well.';if(stage){const date=document.createElement('div');date.textContent=stage.date||'Date not supplied';info.append(date)}
 const note=document.createElement('p');note.textContent='Depth-order IDs and treatment summaries are kept separate unless printed depths support their match. The well charts show each stage\'s treatment curves: stage chart, stacked and sequential.';info.append(note);const link=document.createElement('a');link.href='wellview.html?wa='+encodeURIComponent(well.well.wa)+(stage?'&stage='+encodeURIComponent(stage.label):'');link.textContent='Open well charts →';info.append(link);content.append(info);
}
// The selected well's gamma as a log strip along MD: bar height and colour are both
// the reading, so the strip reads without the legend. Hover it for a value.
function quakeSummary(){const q=data.quakes,n=q.length,rel=q.filter(e=>e.src==='bcsrc').length,near=q.filter(e=>e.near).length,big=n?Math.max(...q.map(e=>e.mag||0)):0,c=quakes.control;
 return `<p class="ug-quake"><b>${n} earthquakes</b> here since 2013${n?`, largest M${big}; ${rel} relocated by the BC Seismic Research Consortium (May 2022–Apr 2024, located to a few hundred metres), the rest from Earthquakes Canada (km-scale)`:''}. <b>${near}</b> coincide with a frac stage on a nearby well${c&&c.share_beyond_chance!=null?`; across the region about ${Math.round(c.share_beyond_chance*100)}% of such coincidences are more than chance (matching the same events with dates shifted by weeks finds ${c.by_chance} of ${c.matched})`:''}. A coincidence names the stage that was pumping, not a proven cause. Ring size is magnitude; a dashed line drops to the solved depth.</p>`}
// The pad's ground-motion monitoring reports, once each: wells on a pad file
// copies of the same report, so they are grouped by content.
function gmmrPanel(p){if(!gmmr)return;const reps={};p.wells.forEach(w=>{const r=gmmr[String(w.well.wa).padStart(5,'0')];if(r&&!reps[r.pad_report])reps[r.pad_report]=r});const list=Object.values(reps);if(!list.length)return;
 const box=document.createElement('div');box.className='ug-gmmr';const h=document.createElement('div');h.className='ug-glabel';h.textContent='Ground motion at this pad (filed with the BCER)';box.append(h);
 const loc=t=>new Date(Date.parse(t)-7*36e5).toISOString().slice(0,16).replace('T',' ')+' local';
 list.forEach(r=>{const d=document.createElement('div');const peak=r.peak_pct_g;
  const lines=[`${r.vendor}${r.window?`, ${r.window[0]} to ${r.window[1]}`:''}`+(r.availability_pct!=null?` · data ${r.availability_pct}%`:''),
   r.triggers.length?`${new Set(r.triggers.map(x=>x.t)).size} trigger${r.triggers.length>1?'s':''} recorded`:(r.n_triggers!=null?`${r.n_triggers} triggers above the logger threshold`:'no triggers listed'),
   peak!=null?`peak ${peak} %g${peak>=0.8?' — over the BCER 0.8 %g reporting threshold':''}`:null].filter(Boolean);
  lines.forEach(t=>{const x=document.createElement('div');x.textContent=t;if(/over the BCER/.test(t))x.className='ug-hot';d.append(x)});
  const seen=new Set();r.triggers.filter(x=>{const k=x.t;if(seen.has(k))return false;seen.add(k);return true}).sort((a,b)=>b.pga_pct_g-a.pga_pct_g).slice(0,4).forEach(x=>{const y=document.createElement('div');y.className='ug-gtrig';
   y.textContent=`${loc(x.t)} · ${x.pga_pct_g} %g`+(x.pumping&&x.pumping.length?` · pumping: ${x.pumping.map(q=>'WA '+q[0]+' stage '+q[1]).join(', ')}`:x.after?` · ${x.after[2]} min after WA ${x.after[0]} stage ${x.after[1]}`:' · no stage pumping');d.append(y)});
  (r.felt||[]).forEach(f=>{const y=document.createElement('div');y.className='ug-felt';y.textContent='Felt: '+f;d.append(y)});
  box.append(d)});
 content.append(box)}
function gammaPanel(w){const box=document.createElement('div');box.className='ug-gamma';content.append(box);const head=document.createElement('div');head.className='ug-glabel';head.textContent='Gamma ray · API'+(w.gest?' · estimated':'');box.append(head);
 if(!w.gv){box.append('No gamma log filed with the BCER for this well; its path is dashed.');return}
 const td=w.trajectory.md.at(-1),heel=w.well.heel_md||0,mdAt=i=>w.gmd0+(i+.5)*w.gbin,logged=w.gv.map((v,i)=>v==null?null:mdAt(i)).filter(m=>m!=null);
 const lat=w.gv.filter((v,i)=>v!=null&&mdAt(i)>=heel).sort((a,b)=>a-b),q=f=>lat.length?(w.gest?'~':'')+lat[Math.floor(f*(lat.length-1))]:null;
 const cv=document.createElement('canvas');cv.setAttribute('role','img');cv.setAttribute('aria-label','Gamma ray against measured depth, '+fmt(logged[0])+' to '+fmt(logged.at(-1))+' m');box.append(cv);
 const read=document.createElement('div');read.className='ug-gread';read.textContent='Hover the strip for a reading';box.append(read);
 const dl=document.createElement('dl');[['Lateral median',q(.5)==null?'–':q(.5)+' API'],['Lateral P10–P90',q(.1)==null?'–':q(.1)+'–'+q(.9)+' API'],['Logged',fmt(logged[0])+'–'+fmt(logged.at(-1))+' m MD']].forEach(([k,v])=>{const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=k;dd.textContent=v;dl.append(dt,dd)});box.append(dl);
 const src=document.createElement('div');src.className='ug-gsrc';src.textContent=w.gest?'No gamma log was filed for this well. Estimated from '+w.gfrom.map(f=>'WA '+f.wa+' ('+f.km+' km)').join(', ')+' at the same subsea depth, smoothed; expect its level to be within about '+(gamma.estimate?.level_mae??'?')+' API, and no detail along the lateral.':w.gruns.map(r=>r.mnemonic+' · '+r.file).join(' + ');box.append(src);
 const W=cv.clientWidth||230,H=74,base=H-14,d=devicePixelRatio||1;cv.width=W*d;cv.height=H*d;const c=cv.getContext('2d');c.setTransform(d,0,0,d,0,0);const X=md=>md/td*W;
 c.strokeStyle='#29404c';c.beginPath();c.moveTo(0,base+.5);c.lineTo(W,base+.5);c.stroke();
 c.globalAlpha=w.gest?.55:1;w.gv.forEach((v,i)=>{if(v==null)return;const x0=X(w.gmd0+i*w.gbin),h=Math.min(1,v/200)*(base-4);c.fillStyle=GAMMA_INK[gammaBucket(v)];c.fillRect(x0,base-h,Math.max(1,X(w.gbin)),h)});c.globalAlpha=1;
 if(heel){c.strokeStyle='#93adb9';c.setLineDash([2,3]);c.beginPath();c.moveTo(X(heel)+.5,2);c.lineTo(X(heel)+.5,base);c.stroke();c.setLineDash([]);}
 if(interval){c.fillStyle='#ffffff';c.fillRect(X(interval.top_m),base+1,Math.max(2,X(interval.base_m-interval.top_m)),3)}
 c.fillStyle='#93adb9';c.font='10px system-ui';c.textBaseline='bottom';c.fillText('0 m',0,H);c.textAlign='right';c.fillText(fmt(td)+' m MD',W,H);if(heel){c.textAlign='center';c.fillText('heel',Math.min(W-60,Math.max(20,X(heel))),H)}
 cv.onpointermove=e=>{const md=(e.clientX-cv.getBoundingClientRect().left)/W*td,i=Math.floor((md-w.gmd0)/w.gbin),v=w.gv[i];read.textContent=fmt(md)+' m MD · '+(v==null?'no reading':'GR '+v+' API')};cv.onpointerleave=()=>{read.textContent='Hover the strip for a reading'};
}
function project(q){const x=q[0]-camera.target[0],y=q[1]-camera.target[1],z=q[2]-camera.target[2],c=Math.cos(camera.yaw),s=Math.sin(camera.yaw),xx=x*c-z*s,zz=x*s+z*c,cp=Math.cos(camera.pitch),sp=Math.sin(camera.pitch);return [width/2+camera.pan[0]+xx*camera.scale,height/2+camera.pan[1]-(y*cp-zz*sp)*camera.scale,zz*cp+y*sp];}
function path(points,color,lineWidth,alpha=1){ctx.beginPath();points.forEach((q,i)=>{const a=project(q);i?ctx.lineTo(a[0],a[1]):ctx.moveTo(a[0],a[1])});ctx.strokeStyle=color;ctx.lineWidth=lineWidth;ctx.globalAlpha=alpha;ctx.stroke();ctx.globalAlpha=1;}
function draw(){if(!active)return;raf=requestAnimationFrame(draw);camera.scale+=(goal.scale-camera.scale)*.11;camera.target=camera.target.map((v,i)=>v+(goal.target[i]-v)*.1);ctx.clearRect(0,0,width,height);hits=[];
 const GR=data.gridR||6000,GD=data.gridD||3000,GS=GR>12000?2000:1000;for(let d=0;d<=GD;d+=1000){for(let a=-GR;a<=GR;a+=GS){path([[a,-d,-GR],[a,-d,GR]],'#397082',.6,d===0?.22:.09);path([[-GR,-d,a],[GR,-d,a]],'#397082',.6,d===0?.22:.09)}const t=project([-GR*.6,-d,0]);ctx.fillStyle='#7695a5';ctx.font='11px monospace';ctx.fillText(d+' m TVD',t[0],t[1]);}
 if(showQuakes&&data.quakes)drawQuakes();
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
 if(w.gest){ctx.setLineDash([7,5]);ctx.lineCap='butt';ctx.globalAlpha*=.8}
 w.gby.forEach((ix,k)=>{if(!ix.length)return;ctx.beginPath();ix.forEach(i=>{ctx.moveTo(P[i][0],P[i][1]);ctx.lineTo(P[i+1][0],P[i+1][1])});ctx.strokeStyle=GAMMA_INK[k];ctx.stroke()});
 ctx.setLineDash([]);ctx.globalAlpha=1;ctx.lineCap='butt';
 if(bright)for(let i=1;i<w.gv.length;i+=3)if(w.gv[i]!=null)hits.push({x:(P[i][0]+P[i+1][0])/2,y:(P[i][1]+P[i+1][1])/2,w,p:w.pad,g:i,r:5});}
function resize(){width=overlay.clientWidth;height=canvas.clientHeight;const d=devicePixelRatio||1;canvas.width=width*d;canvas.height=height*d;ctx.setTransform(d,0,0,d,0,0)}
async function openArea(ids,opts={}){button.disabled=true;button.textContent='Loading…';if(window.stratumSection)window.stratumSection.closeMapDock();
 try{await loadArea(ids);if(opts.title){areaTitle=opts.title+' · Below the surface';overlay.querySelector('.ug-title').textContent=areaTitle}areaName=opts.title||'';active=true;overlay.inert=false;overlay.classList.add('active');overlay.setAttribute('aria-hidden','false');resize();selectPad('');camera.scale=goal.scale*.75;cancelAnimationFrame(raf);draw();
  if(opts.pad){selectPad(opts.pad);if(opts.rack&&pad)enterRack(pad)}else overlay.querySelector('#ug-all').focus();button.textContent='Change View'}
 catch(e){button.textContent='Retry Change View';console.error(e)}finally{button.disabled=false}}
button.onclick=()=>openArea(areaIds());
// for the map: open 3D on the pads around one pad, locked to it, or straight into its wine rack
window.stratum3D={section,open:(padId,opts={})=>openArea(idsAround(padId),{pad:padId,rack:!!opts.rack}),openArea:(ids,opts={})=>openArea(ids,opts),ready:regionReady};
function close(){exitRack(true);active=false;cancelAnimationFrame(raf);overlay.classList.remove('active');overlay.setAttribute('aria-hidden','true');overlay.inert=true;positionButton();button.focus()}
overlay.querySelector('#ug-back').onclick=close;overlay.querySelector('#ug-all').onclick=()=>selectPad('');overlay.querySelector('#ug-reset').onclick=()=>{camera.yaw=-.5;camera.pitch=.4;fit(pad)};padMenu.onchange=()=>selectPad(padMenu.value);
window.addEventListener('resize',()=>{resize();if(active&&!rack)fit(pad);renderRack()});overlay.addEventListener('keydown',e=>{if(e.key==='Escape'){if(rack)exitRack();else if(pad)returnToCluster();else close()}});
canvas.oncontextmenu=e=>e.preventDefault();canvas.onpointerdown=e=>{drag={x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY,pan:e.shiftKey||e.button===2};canvas.setPointerCapture(e.pointerId);tip.style.display='none'};
canvas.onpointermove=e=>{if(drag){const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(drag.pan){camera.pan[0]+=dx;camera.pan[1]+=dy}else{camera.yaw+=dx*.006;camera.pitch=Math.max(-.9,Math.min(1.3,camera.pitch+dy*.005))}drag.x=e.clientX;drag.y=e.clientY;return}hover=[...hits].reverse().find(h=>Math.hypot(h.x-e.clientX,h.y-e.clientY)<h.r);canvas.style.cursor=hover?'pointer':'grab';tip.style.display=hover?'block':'none';if(hover){tip.textContent=hover.q?`M${hover.q.mag} ${hover.q.type} · ${hover.q.date} · ${hover.q.src==='bcsrc'?'relocated (BC Seismic Research Consortium), ±'+(hover.q.herr??'?')+' m across, ±'+(hover.q.derr??'?')+' m deep':'Earthquakes Canada'+(hover.q.fixed?', depth not solved':'')}${hover.q.industry?' · suspected industry-related':''}${hover.q.near?' · '+hover.q.near:''}`:hover.d?'WA '+hover.w.well.wa+' · depth order '+hover.d.n+' · '+fmt(hover.d.top_m,1)+'–'+fmt(hover.d.base_m,1)+' m MD':hover.g!=null?'WA '+hover.w.well.wa+' · '+fmt(hover.w.gmd0+(hover.g+.5)*hover.w.gbin)+' m MD · GR '+(hover.w.gest?'~':'')+hover.w.gv[hover.g]+' API'+(hover.w.gest?' (estimated from WA '+hover.w.gfrom.map(f=>f.wa).join(', ')+')':''):hover.w?'WA '+hover.w.well.wa+' · '+hover.w.stages.length+' stage summaries':hover.p.name+' · '+hover.p.wells.length+' wells · Click to lock';tip.style.left=Math.min(width-270,e.clientX+16)+'px';tip.style.top=Math.min(height-65,e.clientY+16)+'px'}};
canvas.onpointerup=e=>{if(drag&&Math.hypot(e.clientX-drag.startX,e.clientY-drag.startY)<5){const hit=[...hits].reverse().find(h=>Math.hypot(h.x-e.clientX,h.y-e.clientY)<h.r);if(hit&&!hit.q&&(!pad||hit.p===pad)){if(!pad)selectPad(hit.p.id);if(hit.w){well=hit.w;if(hit.d)focusInterval(well,hit.d);else renderPanel();viewPicked()}}}drag=null};canvas.onpointercancel=()=>drag=null;canvas.onpointerleave=()=>{hover=null;tip.style.display='none'};
canvas.addEventListener('wheel',e=>{e.preventDefault();goal.scale=Math.max(.012,Math.min(2,goal.scale*Math.exp(-e.deltaY*.0015)))},{passive:false});

// ---------- Wine rack ----------
// A pad as an engineer reads it across the laterals. Above, or to the left, the
// pad from overhead, turned so its laterals run left to right, with a straight
// line across them the user drags along (or plays, or steps with the keys).
// Beside it, the rack: a 2D section through the pad at that line, each well
// where it crosses -- its offset across the pad against true vertical depth,
// the stage it is in there, gamma there -- and the spacing between neighbours.
// Wells drop in through their landing curve as the line reaches them and drop
// out past their toes. No 3D behind it. Clicking a well opens it below.
let rack=null,rackEntry=null,rackHover=null,tweenRaf=0,rackS=null,rackPlay=0;
const rackLayer=document.createElement('div');rackLayer.className='ug-rackbtns';overlay.append(rackLayer);
const rackView=document.createElement('section');rackView.className='ug-rack';rackView.hidden=true;rackView.setAttribute('aria-label','Wine rack: the pad from overhead and a section across its wells at a line you move along it');
rackView.innerHTML='<div class="ug-rack-head"><button type="button" class="ug-rack-back">← 3D view</button><div><div class="ug-rack-title"></div><div class="ug-rack-sub"></div></div><div class="ug-rack-key"></div></div>'
 +'<div class="ug-rack-body"><div class="ug-rack-plan"><svg class="rk-plan" role="img" aria-label="The pad from overhead with the section line"></svg>'
 +'<div class="ug-rack-ctl"><button type="button" class="rk-play" aria-label="Play the line along the pad">▶</button><input type="range" class="rk-slider" aria-label="Section line position along the pad"><span class="rk-where"></span></div></div>'
 +'<svg class="rk-section" role="group"></svg></div>';
overlay.append(rackView);
const SVGNS='http://www.w3.org/2000/svg',svgEl=(tag,attrs,parent)=>{const e=document.createElementNS(SVGNS,tag);for(const k in attrs)e.setAttribute(k,attrs[k]);if(parent)parent.append(e);return e};
const COMPASS16=['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW'],compassOf=d=>COMPASS16[Math.round(((d%360)+360)%360/22.5)%16];
const LANDING_M=400;   // how far up the build a well shows before its heel, so it can be seen arriving
// Per pad, once: the line the laterals run along (an axial mean, so a pad
// drilled both ways still has one, facing the side most toes are on), and every
// well in that frame: along the pad, across it, and TVD.
function rackGeom(p){if(p.rack)return p.rack;
 const ws=p.wells.map(w=>{const md=w.trajectory.md,heel=w.well.heel_md||md[Math.floor(md.length*.4)]||0,lat=w.points.filter((q,j)=>md[j]>=heel);return {w,heel,lat:lat.length>1?lat:w.points.slice(-2)}});
 let sx=0,sy=0;ws.forEach(o=>{const a=o.lat[0],b=o.lat.at(-1),th=Math.atan2(b[0]-a[0],b[2]-a[2]);sx+=Math.cos(2*th);sy+=Math.sin(2*th)});
 let yaw=Math.atan2(sy,sx)/2;
 const ahead=ws.filter(o=>{const a=o.lat[0],b=o.lat.at(-1);return (b[0]-a[0])*Math.sin(yaw)+(b[2]-a[2])*Math.cos(yaw)>0}).length;if(ahead<ws.length/2)yaw+=Math.PI;
 const ox=ws.reduce((a,o)=>a+o.w.points[0][0],0)/ws.length,oz=ws.reduce((a,o)=>a+o.w.points[0][2],0)/ws.length,ue=Math.sin(yaw),un=Math.cos(yaw);
 const along=q=>(q[0]-ox)*ue+(q[2]-oz)*un,across=q=>(q[0]-ox)*un-(q[2]-oz)*ue;
 ws.forEach(o=>{const w=o.w,md=w.trajectory.md;
  o.plan=w.points.map(q=>[along(q),across(q)]);
  o.pts=w.points.map((q,j)=>({a:along(q),c:across(q),tvd:-q[1],md:md[j]})).filter(q=>q.md>=o.heel-LANDING_M);
  // each stage owns the hole halfway to its neighbours, as on the well section
  const st=(w.stages||[]).filter(s=>s.top_m!=null).map(s=>({s,mid:(s.top_m+(s.base_m??s.top_m))/2})).sort((x,y)=>x.mid-y.mid);
  o.zones=st.map((z,i)=>({s:z.s,z0:i?(st[i-1].mid+z.mid)/2:z.mid-((st[1]?.mid??z.mid+60)-z.mid)/2,z1:i<st.length-1?(z.mid+st[i+1].mid)/2:z.mid+(z.mid-(st[i-1]?.mid??z.mid-60))/2}));
  o.toeA=o.pts.length?o.pts.at(-1).a:0;});
 const all=ws.flatMap(o=>o.pts),plan=ws.flatMap(o=>o.plan);
 const g={yaw,az:(yaw*180/Math.PI+360)%360,ws,along,across,
  sMin:Math.min(...all.map(q=>q.a)),sMax:Math.max(...all.map(q=>q.a)),
  c0:Math.min(...all.map(q=>q.c)),c1:Math.max(...all.map(q=>q.c)),t0:Math.min(...all.map(q=>q.tvd)),t1:Math.max(...all.map(q=>q.tvd)),
  pa0:Math.min(...plan.map(q=>q[0])),pa1:Math.max(...plan.map(q=>q[0])),pc0:Math.min(...plan.map(q=>q[1])),pc1:Math.max(...plan.map(q=>q[1])),
  toeMid:[0,1,2].map(i=>ws.reduce((a,o)=>a+o.w.points.at(-1)[i],0)/ws.length)};
 // start in the middle of the stretch where the most wells are on the line, landed
 const tries=[];for(let s=g.sMin;s<=g.sMax;s+=(g.sMax-g.sMin)/80||1)tries.push({s,n:ws.filter(o=>{const x=rackCross(o,s);return x&&!x.landing}).length});
 const most=Math.max(...tries.map(t=>t.n)),best=tries.filter(t=>t.n===most);g.start=best[Math.floor(best.length/2)].s;
 return p.rack=g;}
// where one well crosses the line `s` metres along the pad: the deepest crossing
function rackCross(o,s){let hit=null;for(let i=1;i<o.pts.length;i++){const a=o.pts[i-1],b=o.pts[i];if((a.a-s)*(b.a-s)>0||a.a===b.a)continue;const f=(s-a.a)/(b.a-a.a),md=a.md+(b.md-a.md)*f;if(!hit||md>hit.md)hit={c:a.c+(b.c-a.c)*f,tvd:a.tvd+(b.tvd-a.tvd)*f,md}}
 if(hit){hit.landing=hit.md<o.heel;const z=o.zones.find(z=>hit.md>=z.z0&&hit.md<=z.z1);hit.stage=z?z.s:null;const w=o.w;if(w.gv){const v=w.gv[Math.floor((hit.md-w.gmd0)/w.gbin)];hit.gamma=v==null?null:v}}
 return hit}
const rackInk=(o,x)=>colorBy!=='gamma'?o.w.pad.color:(x&&x.gamma!=null?GAMMA_INK[gammaBucket(x.gamma)]:null);
function lateralGamma(w){if(!w.gv)return null;const heel=w.well.heel_md||0,v=w.gv.filter((x,i)=>x!=null&&w.gmd0+(i+.5)*w.gbin>=heel).sort((a,b)=>a-b);return v.length?v[Math.floor(v.length/2)]:null}
// The buttons ride on each pad's cluster of toes as the scene turns; ones that
// would land on each other step down, the way the pad labels do.
function placeRackButtons(){if(!data)return;const placed=[];data.pads.forEach(p=>{let b=p.rackBtn;if(!b){b=p.rackBtn=document.createElement('button');b.type='button';b.className='ug-rackbtn';b.onclick=()=>enterRack(p);b.onmouseenter=b.onfocus=()=>{rackHover=p};b.onmouseleave=b.onblur=()=>{if(rackHover===p)rackHover=null};rackLayer.append(b)}
 const on=active&&!rack&&(!pad||p===pad),q=on?project(rackGeom(p).toeMid):null,vis=on&&q[0]>20&&q[0]<width-20&&q[1]>90&&q[1]<height-30;b.hidden=!vis;if(!vis)return;
 b.textContent=pad?'Wine rack ▸':'Wine rack';b.title='Wine rack: '+p.name+' across its laterals';b.setAttribute('aria-label',b.title);let y=q[1]+12;while(placed.some(l=>Math.abs(l.x-q[0])<90&&Math.abs(l.y-y)<30))y+=30;placed.push({x:q[0],y});b.style.transform=`translate(${Math.round(q[0])}px,${Math.round(y)}px) translateX(-50%)`;});}
function tweenCamera(to,ms,done){cancelAnimationFrame(tweenRaf);if(!ms){camera.yaw=to.yaw;camera.pitch=to.pitch;if(done)done();return}const from={yaw:camera.yaw,pitch:camera.pitch},t0=performance.now();
 const step=now=>{const k=ms?Math.min(1,(now-t0)/ms):1,e=k<.5?2*k*k:1-Math.pow(-2*k+2,2)/2;camera.yaw=from.yaw+(to.yaw-from.yaw)*e;camera.pitch=from.pitch+(to.pitch-from.pitch)*e;if(k<1)tweenRaf=requestAnimationFrame(step);else if(done)done()};tweenRaf=requestAnimationFrame(step);}
// straight in: the 3D view stays where it was underneath, for coming back
function enterRack(p,instant){if(!data||rack)return;if(!pad)selectPad(p.id);if(pad!==p)return;const g=rackGeom(p);
 rack=p;rackHover=null;rackEntry={yaw:camera.yaw,pitch:camera.pitch,scale:goal.scale,target:goal.target.slice()};tip.style.display='none';
 if(!rackS||rackS.pad!==p.id)rackS={pad:p.id,s:g.start};
 overlay.classList.add('racking');rackView.hidden=false;renderRack();if(!instant)rackView.querySelector('.rk-slider').focus();}
function exitRack(quiet){if(!rack)return;rackStop();rack=null;overlay.classList.remove('racking');rackView.hidden=true;tip.style.display='none';rackEntry=null;if(!quiet)canvas.focus();}
rackView.querySelector('.ug-rack-back').onclick=()=>exitRack();
function niceStep(span,n){const raw=span/n,e=Math.pow(10,Math.floor(Math.log10(raw)));return [1,2,2.5,5,10].map(m=>m*e).find(s=>s>=raw)||10*e}
// the line: dragged on the overview, the slider, the keys, or played
function rackMove(s){if(!rack)return;const g=rackGeom(rack);rackS={pad:rack.id,s:Math.max(g.sMin,Math.min(g.sMax,s))};renderRack()}
function rackStop(){cancelAnimationFrame(rackPlay);rackPlay=0;const b=rackView.querySelector('.rk-play');b.textContent='▶';b.setAttribute('aria-label','Play the line along the pad')}
rackView.querySelector('.rk-slider').oninput=e=>{rackStop();rackMove(+e.target.value)};
rackView.querySelector('.rk-play').onclick=()=>{if(rackPlay){rackStop();return}if(!rack)return;const g=rackGeom(rack),span=g.sMax-g.sMin;if(rackS.s>=g.sMax-1)rackMove(g.sMin);
 const b=rackView.querySelector('.rk-play');b.textContent='❚❚';b.setAttribute('aria-label','Pause');let last=performance.now();
 const step=now=>{const dt=Math.min(.1,(now-last)/1000);last=now;const s=rackS.s+span/14*dt;rackMove(s);if(s>=g.sMax){rackStop();return}rackPlay=requestAnimationFrame(step)};rackPlay=requestAnimationFrame(step)};
{const plan=rackView.querySelector('.rk-plan');let dragging=false;
 const at=e=>{const r=plan.getBoundingClientRect(),m=plan._map;if(m)rackMove(m.inv(e.clientX-r.left))};
 plan.addEventListener('pointerdown',e=>{if(!rack)return;rackStop();dragging=true;plan.setPointerCapture(e.pointerId);at(e)});
 plan.addEventListener('pointermove',e=>{if(dragging)at(e)});
 plan.addEventListener('pointerup',()=>{dragging=false});plan.addEventListener('pointercancel',()=>{dragging=false});}
rackView.addEventListener('keydown',e=>{if(!rack||e.target.closest('.rk-slider')||!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();rackStop();rackMove(rackS.s+(e.key==='ArrowRight'?1:-1)*(e.shiftKey?250:25))});
function rackTip(e,lines){tip.innerHTML='';lines.filter(Boolean).forEach(([t,b])=>{const d=document.createElement(b||'div');d.textContent=t;if(b)d.style.display='block';tip.append(d)});tip.style.display='block';const r=overlay.getBoundingClientRect();tip.style.left=Math.min(r.width-270,e.clientX-r.left+16)+'px';tip.style.top=Math.min(r.height-130,e.clientY-r.top+16)+'px'}
function renderRack(){if(!rack)return;const p=rack,g=rackGeom(p),s=rackS.s;
 // the header wraps to more rows when the window narrows: start below whatever it takes
 rackView.style.top=Math.max(84,overlay.querySelector('.ug-head').getBoundingClientRect().bottom-overlay.getBoundingClientRect().top+10)+'px';
 const hits=g.ws.map(o=>({o,x:rackCross(o,s)})).filter(h=>h.x);
 const sl=rackView.querySelector('.rk-slider');sl.min=Math.floor(g.sMin);sl.max=Math.ceil(g.sMax);sl.step=5;sl.value=Math.round(s);
 rackView.querySelector('.rk-where').textContent=`${fmt(Math.abs(s))} m ${s>=0?'out':'back'} from the pad · ${hits.length} of ${g.ws.length} wells on the line`;
 renderRackPlan(g,s,hits);renderRackSection(g,s,hits);
 rackView.querySelector('.ug-rack-title').textContent=p.name+' · Wine rack';
 const gone=g.ws.filter(o=>!hits.some(h=>h.o===o));
 rackView.querySelector('.ug-rack-sub').textContent=`Laterals run toward ${Math.round(g.az)}° (${compassOf(g.az)}) · ${hits.length} of ${g.ws.length} wells cross the line`+(gone.length&&gone.length<=4?` · not here: ${gone.map(o=>o.w.well.wa).join(', ')}`:gone.length?` · ${gone.length} not here`:'');
 const key=rackView.querySelector('.ug-rack-key');key.replaceChildren();if(colorBy==='gamma'&&gamma){key.innerHTML=`<span>Gamma at the line</span><i style="background:linear-gradient(90deg,${GAMMA_RAMP.join(',')})"></i><span>${gamma.scale.lo}–${gamma.scale.hi} API</span><span class="rk-nonekey">no log</span>`}else key.textContent='Drag the line along the pad · click a well to view it below';
}
// the pad from overhead, laterals left to right, the line across them
function renderRackPlan(g,s,hits){const svg=rackView.querySelector('.rk-plan');svg.replaceChildren();const W=svg.clientWidth,H=svg.clientHeight;if(!W||!H)return;svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
 const P={l:14,r:14,t:30,b:28},pw=W-P.l-P.r,ph=H-P.t-P.b,a0=g.pa0-60,a1=g.pa1+60,c0=g.pc0-60,c1=g.pc1+60;
 // one scale both ways, so the pad keeps its true shape
 const k=Math.min(pw/(a1-a0),ph/(c1-c0)),ax=P.l+(pw-(a1-a0)*k)/2,cy=P.t+(ph-(c1-c0)*k)/2,X=a=>ax+(a-a0)*k,Y=c=>cy+(c1-c)*k;
 svg._map={inv:x=>a0+(x-ax)/k};
 const grid=svgEl('g',{class:'rk-grid'},svg),st=niceStep(a1-a0,Math.max(2,Math.min(6,pw/95)));
 for(let a=Math.ceil(a0/st)*st;a<=a1;a+=st){svgEl('line',{x1:X(a),x2:X(a),y1:P.t,y2:P.t+ph,class:a===0?'rk-zero':''},grid);svgEl('text',{x:X(a),y:H-10,'text-anchor':'middle'},grid).textContent=(a<0?'−':'')+fmt(Math.abs(a))+' m'}
 svgEl('text',{x:P.l,y:13,class:'rk-axis'},svg).textContent=`← ${compassOf(g.az+180)}`;
 svgEl('text',{x:W-P.r,y:13,class:'rk-axis','text-anchor':'end'},svg).textContent=`toes · ${compassOf(g.az)} →`;
 // north, as it sits in this turned view
 const nx=W-P.r-16,ny=P.t+30,na=-g.yaw;svgEl('line',{x1:nx-Math.sin(na)*10,y1:ny+Math.cos(na)*10,x2:nx+Math.sin(na)*10,y2:ny-Math.cos(na)*10,class:'rk-north'},svg);svgEl('text',{x:nx+Math.sin(na)*19,y:ny-Math.cos(na)*19+4,'text-anchor':'middle',class:'rk-axis'},svg).textContent='N';
 const paths=svgEl('g',{class:'rk-paths'},svg);
 const tags=[];
 g.ws.forEach(o=>{const on=o.w===well,ink=colorBy==='gamma'?'#b9c9d2':o.w.pad.color;
  svgEl('polyline',{points:o.plan.map(q=>X(q[0]).toFixed(1)+','+Y(q[1]).toFixed(1)).join(' '),stroke:ink,class:on?'on':''},paths);
  const t=o.plan.at(-1);svgEl('circle',{cx:X(t[0]),cy:Y(t[1]),r:2.5,fill:ink},paths);tags.push({o,x:X(t[0]),y:Y(t[1]),on});});
 // a number at each toe, inside the frame, the selected well's first; ones that would overlap are left off
 const kept=[];tags.sort((a,b)=>b.on-a.on).forEach(t=>{const right=t.x+42<=W-P.r,x=right?t.x+5:t.x-5;if(kept.some(k=>Math.abs(k.y-t.y)<11&&Math.abs(k.x-x)<44))return;kept.push({x,y:t.y});
  svgEl('text',{x,y:t.y+3.5,'text-anchor':right?'start':'end',class:'rk-plan-wa'+(t.on?' on':'')},paths).textContent=t.o.w.well.wa;});
 svgEl('circle',{cx:X(0),cy:Y(0),r:5,class:'rk-padpt'},svg);
 // the line, and where each well meets it
 const lx=X(s);svgEl('line',{x1:lx,x2:lx,y1:P.t-6,y2:P.t+ph+4,class:'rk-line'},svg);
 svgEl('rect',{x:lx-7,y:P.t-12,width:14,height:11,rx:3,class:'rk-handle'},svg);
 hits.forEach(h=>svgEl('circle',{cx:lx,cy:Y(h.x.c),r:4,fill:rackInk(h.o,h.x)||'#0b1620',class:'rk-meet'+(h.x.landing?' landing':'')},svg));
}
// the section across the pad at the line
function renderRackSection(g,s,hits){const svg=rackView.querySelector('.rk-section');svg.replaceChildren();const W=svg.clientWidth,H=svg.clientHeight;if(!W||!H)return;svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
 const small=W<520,R=small?8:11,P={l:72,r:20,t:40,b:46},pw=W-P.l-P.r,ph=H-P.t-P.b;
 // one frame for the whole pad, so wells move within it as the line moves
 const mx=Math.max(30,(g.c1-g.c0)*.05),my=Math.max(10,(g.t1-g.t0)*.06),x0=g.c0-mx,x1=g.c1+mx,y0=g.t0-my,y1=g.t1+my;
 const X=v=>P.l+R+(v-x0)/(x1-x0)*(pw-2*R),Y=v=>P.t+R+(v-y0)/(y1-y0)*(ph-2*R-26),ex=((ph-2*R-26)/(y1-y0))/((pw-2*R)/(x1-x0));
 const grid=svgEl('g',{class:'rk-grid'},svg),ys=niceStep(y1-y0,6),xs=niceStep(x1-x0,7);
 for(let v=Math.ceil(y0/ys)*ys;v<=y1;v+=ys){svgEl('line',{x1:P.l,x2:P.l+pw,y1:Y(v),y2:Y(v)},grid);svgEl('text',{x:P.l-8,y:Y(v)+4,'text-anchor':'end'},grid).textContent=fmt(v)+' m'}
 for(let v=Math.ceil(x0/xs)*xs;v<=x1;v+=xs){svgEl('line',{x1:X(v),x2:X(v),y1:P.t,y2:P.t+ph,class:v===0?'rk-zero':''},grid);svgEl('text',{x:X(v),y:P.t+ph+16,'text-anchor':'middle'},grid).textContent=(v>0?'+':v<0?'−':'')+fmt(Math.abs(v))+' m'}
 svgEl('text',{x:P.l+pw/2,y:H-8,'text-anchor':'middle',class:'rk-axis'},svg).textContent=(small?'Across the pad':'Across the pad, looking toward the toes')+` (${Math.round(g.az)}°) · depth ×${ex.toFixed(1)}`;
 svgEl('text',{x:14,y:P.t+ph/2,'text-anchor':'middle',class:'rk-axis',transform:`rotate(-90 14 ${P.t+ph/2})`},svg).textContent='True vertical depth';
 if(!hits.length){svgEl('text',{x:P.l+pw/2,y:P.t+ph/2,'text-anchor':'middle',class:'rk-empty'},svg).textContent='No well crosses the line here. Move it along the pad.';return}
 // spacing between neighbours across the pad, along the top
 const sorted=hits.slice().sort((a,b)=>a.x.c-b.x.c),dim=svgEl('g',{class:'rk-dim'},svg),dy=P.t-14;
 sorted.forEach((h,i)=>{const x=X(h.x.c);svgEl('line',{x1:x,x2:x,y1:dy-5,y2:dy+5},dim);if(i){const px=X(sorted[i-1].x.c),gap=h.x.c-sorted[i-1].x.c;svgEl('line',{x1:px,x2:x,y1:dy,y2:dy},dim);if(x-px>34)svgEl('text',{x:(px+x)/2,y:dy-6,'text-anchor':'middle'},dim).textContent=fmt(gap)+' m'}});
 const labels=[],ends=svgEl('g',{class:'rk-ends'},svg);
 hits.slice().sort((a,b)=>a.x.tvd-b.x.tvd).forEach(h=>{const o=h.o,w=o.w,x=h.x,cx=X(x.c),cy=Y(x.tvd),ink=rackInk(o,x);
  const a=svgEl('g',{class:'rk-end'+(w===well?' on':'')+(x.landing?' landing':''),tabindex:0,role:'button','aria-label':`${w.well.name}, WA ${w.well.wa}: ${fmt(x.c)} metres across, ${fmt(x.tvd)} metres TVD${x.stage?', stage '+x.stage.label:''}. View it below.`},ends);
  svgEl('circle',{cx,cy,r:R,fill:x.landing?'#0b1620':ink||'#0b1620',stroke:x.landing?ink||'#6b8290':'#0b1620',class:ink?(colorBy==='gamma'&&w.gest?'rk-est':''):'rk-none'},a);
  const lh=small?13:26,bw=small?36:52;let ly=cy+R+14;const box=l=>labels.some(b=>Math.abs(b.x-cx)<bw&&Math.abs(b.y-l)<lh);if(box(ly))ly=cy-R-(small?6:18);labels.push({x:cx,y:ly});
  svgEl('text',{x:cx,y:ly,'text-anchor':'middle',class:'rk-wa'},a).textContent=w.well.wa+(x.stage&&!small?' · stg '+x.stage.label:'');
  if(!small)svgEl('text',{x:cx,y:ly+12,'text-anchor':'middle',class:'rk-tvd'},a).textContent=fmt(x.tvd)+' m'+(x.landing?' · landing':'');
  // nearest neighbour on this line, in the section's own metres
  let nn=null;hits.forEach(k=>{if(k===h)return;const d=Math.hypot(k.x.c-x.c,k.x.tvd-x.tvd);if(!nn||d<nn.d)nn={d,h:Math.abs(k.x.c-x.c),v:k.x.tvd-x.tvd,wa:k.o.w.well.wa}});
  const open=()=>{well=w;stage=x.stage;interval=null;renderPanel();viewPicked();renderRack()};
  a.addEventListener('click',open);a.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open()}});
  a.addEventListener('pointerenter',e=>{const st=x.stage;rackTip(e,[[w.well.name,'b'],[`WA ${w.well.wa} · MD ${fmt(x.md)} m at the line · ${fmt(x.tvd)} m TVD${x.landing?' (landing, before the heel)':''}`],
   st?[`Stage ${st.label}${st.date?' · '+st.date:''}${st.proppant_t!=null?' · '+fmt(st.proppant_t,1)+' t':''}${st.avg_rate_m3_min!=null?' · '+fmt(st.avg_rate_m3_min,1)+' m³/min':''}`]:null,
   x.gamma!=null?[`Gamma ${w.gest?'~':''}${fmt(x.gamma)} API at the line${w.gest?' (estimated)':''}`]:null,
   nn?[`Nearest on this line: WA ${nn.wa}, ${fmt(nn.h)} m across, ${fmt(Math.abs(nn.v))} m ${nn.v<0?'shallower':'deeper'}`]:null,['Click to view it below']])});
  a.addEventListener('pointerleave',()=>{tip.style.display='none'});});
}
// Leaving for a well view and coming back should land where you were, not at the
// default cluster. The camera, the focused pad and the selected well are stashed
// for this tab only, and restored once, so a normal close still reopens clean.
const UG_KEY='stratum.underground';
function ugSave(){if(!active)return;try{sessionStorage.setItem(UG_KEY,JSON.stringify(ugState()))}catch(e){}}
function ugState(){return({
 yaw:camera.yaw,pitch:camera.pitch,scale:camera.scale,target:camera.target.slice(),pan:camera.pan.slice(),
 pad:pad?pad.id:'',wa:well&&well.well?well.well.wa:'',entryCamera,
 stage:stage?stage.label:null,interval:interval?interval.n:null,colorBy,rack:rack?rack.id:null,rackEntry,rackSlice:rack&&rackS?rackS.s:null,area:data?data.pads.map(p=>p.id):null,areaName,
 panelScroll:overlay.querySelector('.ug-panel').scrollTop,section:sectionOn,label:pad?pad.name:areaTitle.replace(/ · Below the surface$/,''),
 surface:{center:map.getCenter().toArray(),zoom:map.getZoom(),bearing:map.getBearing(),pitch:map.getPitch()}})}
function ugClear(){try{sessionStorage.removeItem(UG_KEY)}catch(e){}}
addEventListener('pagehide',ugSave);
overlay.querySelector('#ug-back').addEventListener('click',ugClear);
// a saved session reads the 3D view as it is now (session.js)
if(typeof window!=='undefined'&&window.StratumSession)StratumSession.provide(()=>({[UG_KEY]:active?JSON.stringify(ugState()):null}));
(async()=>{let s=null;try{s=JSON.parse(sessionStorage.getItem(UG_KEY)||'null')}catch(e){}
 if(!s)return;ugClear();
 try{if(!s.area)return;await loadArea(s.area)}catch(e){return}
 if(s.areaName){areaName=s.areaName;areaTitle=areaName+' · Below the surface';overlay.querySelector('.ug-title').textContent=areaTitle}
 active=true;overlay.inert=false;overlay.classList.add('active');overlay.setAttribute('aria-hidden','false');resize();
 if(s.colorBy==='gamma')await setColor('gamma');
 selectPad(s.pad||'');
 if(s.wa&&pad){const w=pad.wells.find(x=>x.well&&x.well.wa===s.wa);if(w){well=w;stage=w.stages.find(x=>x.label===s.stage)||null;interval=w.depth_intervals.find(x=>x.n===s.interval)||null;renderPanel()}}
 if(s.section&&pad&&well&&window.stratumSection)window.stratumSection.view(well.well.wa,stage?stage.label:null);
 if(s.entryCamera)entryCamera=structuredClone(s.entryCamera);
 overlay.querySelector('.ug-panel').scrollTop=s.panelScroll||0;
 if(s.surface)map.jumpTo(s.surface);
 camera.yaw=s.yaw;camera.pitch=s.pitch;camera.scale=s.scale;
 camera.pan=s.pan.slice();camera.target=s.target.slice();
 goal.scale=s.scale;goal.target=s.target.slice();
 if(s.rack&&pad&&pad.id===s.rack){if(s.rackSlice!=null)rackS={pad:pad.id,s:s.rackSlice};enterRack(pad,true);if(s.rackEntry)rackEntry=s.rackEntry}
 draw();button.textContent='Change View';
})();
})();
