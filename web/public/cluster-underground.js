(() => {
'use strict';
const button=document.createElement('button');button.id='change-view';button.textContent='Change View';button.setAttribute('aria-label','Change View to underground cluster');document.body.append(button);
const overlay=document.createElement('section');overlay.id='underground';overlay.setAttribute('aria-label','Underground cluster explorer');overlay.setAttribute('aria-hidden','true');overlay.inert=true;
overlay.innerHTML=`<canvas aria-label="Interactive surveyed well paths. Arrow keys move the view, Shift and the arrows turn and tilt it, plus and minus zoom. Select pads using the pad menu." tabindex="0"></canvas><div class="ug-head"><div><div class="ug-title">Below the surface</div><div class="ug-sub">Loading…</div></div><div class="ug-tools"><div class="ug-color" role="group" aria-label="Colour wells by"><span>Colour</span><button data-color="pad" aria-pressed="true">Pad</button><button data-color="gamma" aria-pressed="false">Gamma</button></div><button id="ug-quakes" type="button" aria-pressed="false" title="Earthquakes since 2013 (Earthquakes Canada)">Quakes</button><button id="ug-qfilter" type="button" hidden aria-haspopup="dialog" aria-expanded="false" title="Filter the earthquakes: dates, magnitude, undetermined depths">Filter</button><button id="ug-all">All pads</button><button id="ug-reset">Reset camera</button><button id="ug-back">Surface view ↗</button></div></div><aside class="ug-panel"><label for="ug-pad">Explore the cluster</label><select id="ug-pad"><option value="">All pads</option></select><div id="ug-content" class="ug-summary">Loading directional surveys…</div></aside><div class="ug-hint">Drag to orbit · Shift-drag / right-drag to pan · Scroll to zoom · Arrow keys move, Shift + arrows turn and tilt, + / − zoom · Click a pad to lock on<br>Survey geometry uses local surface-relative TVD; measured intervals are shown; treatment-stage matching is unverified.</div><div class="ug-tip"></div><div class="ug-legend" hidden></div>`;
document.body.append(overlay);
const padPage=document.createElement('iframe');padPage.className='ug-pad-page';padPage.title='Pad data';padPage.hidden=true;overlay.append(padPage);
const returnButton=document.createElement('button');returnButton.id='ug-return';returnButton.textContent='← Back to underground';returnButton.hidden=true;overlay.querySelector('.ug-tools').prepend(returnButton);

const canvas=overlay.querySelector('canvas'),ctx=canvas.getContext('2d'),tip=overlay.querySelector('.ug-tip'),padMenu=overlay.querySelector('select'),content=overlay.querySelector('#ug-content');
let entryCamera=null;
let data=null,active=false,pad=null,well=null,stage=null,interval=null,hits=[],hover=null,width=0,height=0,drag=null,raf=0,colorBy='pad',gamma=null,quakes=null,showQuakes=false;
const camera={yaw:-.5,pitch:.4,scale:.085,target:[0,-1000,0],pan:[110,20]},goal={scale:.085,target:[0,-1000,0]};
// Gamma ray, low API (cleaner rock) to high (shalier), in the colours chosen in
// gamma-palettes.js (amber, viridis, sand to shale, cool to warm about the median);
// every step clears 2.3:1 on the backdrop, so a low reading never reads as a
// missing one; missing is dashed slate.
const GAMMA_N=24,SG=window.StratumGamma;
let GAMMA_RAMP=SG.stops();
// the scene's own inks, for the theme on screen (theme.js): the light one draws dark on pale
const UGK={dark:{grid:'#397082',gridA:[.22,.09],depth:'#7695a5',neutral:'#d6e6ee',none:'#6b8290',lit:'#5ee2d0',on:'#ffffff',padOn:'#e6fff7',padRing:'#b4ebef',glow:1,quake:'#ff5fa2',base:'#29404c',mut:'#93adb9',hl:'#ffffff'},
 light:{grid:'#4f7584',gridA:[.3,.12],depth:'#566b78',neutral:'#3d4f5b',none:'#7b8e9a',lit:'#0d8577',on:'#14212b',padOn:'#14212b',padRing:'#ffffff',glow:0,quake:'#d6336c',base:'#d3dde4',mut:'#566b78',hl:'#14212b'}};
const isDark=()=>typeof document!=='undefined'&&!!document.documentElement&&!!document.documentElement.dataset&&document.documentElement.dataset.theme==='dark';
let UK=UGK[isDark()?'dark':'light'];
const padColor=i=>typeof window!=='undefined'&&window.StratumTheme?StratumTheme.padColor(i):PAD_COLORS[i%PAD_COLORS.length];
let GAMMA_INK=SG.steps(GAMMA_N);
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
 if(data&&pad)selectPad('');rackLayer.replaceChildren();well=null;stage=null;interval=null;hover=null;
 const d={pads};data=d;
 const lat0=d.pads.reduce((a,p)=>a+p.lat,0)/d.pads.length,lon0=d.pads.reduce((a,p)=>a+p.lon,0)/d.pads.length;
 const xy=(lon,lat)=>[(lon-lon0)*111320*Math.cos(lat0*Math.PI/180),(lat-lat0)*111320];d.xy=xy;
 while(padMenu.options.length>1)padMenu.remove(1);
 d.pads.forEach((p,i)=>{p.ci=i;p.color=padColor(i);const [x,z]=xy(p.lon,p.lat);p.point=[x,0,z];p.wells.forEach(w=>{const [wx,wz]=xy(w.well.lon,w.well.lat),t=w.trajectory;w.points=t.md.map((m,j)=>[wx+t.ew[j],-t.tvd[j],wz+t.ns[j]]).filter(q=>q.every(Number.isFinite));w.pad=p;w.depth_intervals=(w.depth_intervals||[]).filter(d=>d.top_m!=null).map(d=>({...d,point:pointAt(w,(d.top_m+(d.base_m??d.top_m))/2)}));});const opt=document.createElement('option');opt.value=p.id;opt.textContent=p.name+' · '+p.wells.length+' wells';padMenu.append(opt);});
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
 data.quakes=quakes.rows.map(r=>{const [x,z]=data.xy(r[2],r[1]),m=r[11];const e={t:Date.parse(r[0]),date:r[0].slice(0,16).replace('T',' ')+' UTC',x,z,depth:r[3]==null?null:r[3]*1000+elev,mag:r[4],type:r[5],fixed:!!r[6]||r[3]==null,industry:!!r[7],src:r[8],herr:r[9],derr:r[10],match:m,matched:!!m};
  if(m){const w=byWa[m[0]];e.near=`coincides with the frac of WA ${m[0]}${w?' ('+w.pad.name+')':''}: stage ${m[1]} ${m[2]==='after'?'had ended '+m[3]+' min before':'was pumping'}, ${m[4]} km away`+(m[5]!=null?`, ${Math.abs(m[5])} m ${m[5]>0?'below':'above'} it`:'')}
  return e}).filter(e=>Math.abs(e.x)<=data.gridR&&Math.abs(e.z)<=data.gridR);}
function drawQuakes(){for(const e of data.quakes||[]){if(!SQ.pass(e))continue;const s=project([e.x,0,e.z]),r=3+Math.max(0,e.mag)*2.6;
  if(!e.fixed){const h=project([e.x,-e.depth,e.z]);ctx.setLineDash([2,3]);ctx.strokeStyle=UK.quake;ctx.globalAlpha=.55;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(s[0],s[1]);ctx.lineTo(h[0],h[1]);ctx.stroke();ctx.setLineDash([]);ctx.globalAlpha=.9;ctx.fillStyle=UK.quake;ctx.beginPath();ctx.arc(h[0],h[1],2.2,0,Math.PI*2);ctx.fill();}
  ctx.globalAlpha=e.near?.5:e.src==='bcsrc'?.32:.18;ctx.fillStyle=UK.quake;ctx.beginPath();ctx.arc(s[0],s[1],r,0,Math.PI*2);ctx.fill();ctx.globalAlpha=e.near?1:.75;ctx.strokeStyle=UK.quake;ctx.lineWidth=e.near?1.8:1;ctx.stroke();ctx.globalAlpha=1;
  hits.push({x:s[0],y:s[1],q:e,r:Math.max(6,r)});}}
overlay.querySelector('#ug-quakes').onclick=async e=>{showQuakes=!showQuakes;e.currentTarget.setAttribute('aria-pressed',String(showQuakes));qfButton.hidden=!showQuakes;if(!showQuakes)SQ.close();await quakesReady;if(data&&!data.quakes)attachQuakes();renderPanel()};
// the quake filter (quake-filter.js) is shared with the map and the well charts: one setting, every view
const SQ=window.StratumQuakes,qfButton=overlay.querySelector('#ug-qfilter');
const qfLabel=()=>{qfButton.textContent=SQ.active()?'Filter · on':'Filter';qfButton.classList.toggle('on',SQ.active())};qfLabel();
qfButton.onclick=e=>{if(!quakes)return;const rows=quakes.rows,days=rows.map(r=>r[0].slice(0,10)).sort(),mags=rows.map(r=>r[4]).filter(m=>m!=null),here=()=>data&&data.quakes||[];
 SQ.panel(e.currentTarget,{bounds:{first:days[0],last:days.at(-1),magMin:Math.min(...mags),magMax:Math.max(...mags)},count:f=>`${here().filter(q=>SQ.pass(q,f)).length} of ${here().length} here shown`})};
addEventListener('stratum:quakefilter',()=>{qfLabel();if(data&&showQuakes)renderPanel()});

// Gamma is an extra layer: if it fails to load, the view still opens in pad colours.
const gammaReady=fetch('data/gamma.json').then(r=>r.ok?r.json():null).then(g=>{if(g){gamma=g;if(data)attachGamma(g)}}).catch(e=>console.warn('gamma layer',e)).then(()=>{if(!gamma){const b=overlay.querySelector('[data-color=gamma]');b.disabled=true;b.title='Gamma data unavailable'}});
function gammaBucket(v){return SG.bucket(v,gamma.scale,GAMMA_N)}
// another scheme chosen, here or in another window: recolour everything that shows gamma
addEventListener('stratum:gammapalette',()=>{GAMMA_RAMP=SG.stops();GAMMA_INK=SG.steps(GAMMA_N);if(gamma)attachGamma(gamma);if(data)renderPanel()});
// light or dark (theme.js): the pads take that theme's colours; the scene redraws on its next frame
addEventListener('stratum:theme',()=>{UK=UGK[isDark()?'dark':'light'];if(data)data.pads.forEach(p=>{p.color=padColor(p.ci)});if(data)renderPanel()});
// Each bin becomes one segment of the path between its two MD edges; segments are
// grouped by colour once here so a frame strokes one path per colour, not per bin.
function attachGamma(g){gamma=g;const bin=g.bin_m;if(data)data.pads.forEach(p=>p.wells.forEach(w=>{const x=g.wells[String(w.well.wa).padStart(5,'0')];if(!x)return;w.gmd0=x.md0;w.gbin=bin;w.gv=x.v;w.gruns=x.runs;w.gest=!!x.estimated;w.gfrom=x.from||[];w.gpts=x.v.concat([null]).map((_,i)=>pointAt(w,x.md0+i*bin));w.gby=GAMMA_INK.map(()=>[]);x.v.forEach((v,i)=>{if(v!=null)w.gby[gammaBucket(v)].push(i)})}));renderLegend();}
function renderLegend(){const L=overlay.querySelector('.ug-legend');if(!gamma){L.hidden=true;return}const s=gamma.scale,all=data?data.pads.flatMap(p=>p.wells):[],n=all.filter(w=>w.gv&&!w.gest).length,est=all.filter(w=>w.gest).length,none=all.length-n-est,E=gamma.estimate;
 L.innerHTML=`<div class="ug-glabel">Wells coloured by gamma ray</div><div class="ug-gbar" style="background:linear-gradient(90deg,${GAMMA_RAMP.join(',')})"></div><div class="ug-gticks"><span>≤${s.lo}</span><span>${SG.PALETTES[SG.current()].diverging?'median '+s.p50:Math.round((s.lo+s.hi)/2)}</span><span>≥${s.hi} API</span></div><div class="ug-gticks ug-gends"><span>cleaner</span><span>shalier</span></div><div class="ug-gnone ug-gest"><i></i>Estimated from offset logs · ${est} wells</div><div class="ug-gnone"><i></i>No gamma · ${none} wells</div><div class="ug-gfoot">${n} measured (LAS logs from the BCER eLibrary)${est&&E?`; ${est} estimated: neighbours' gamma at the same subsea depth, smoothed to ${E.smoothed_m} m. Tested on ${E.tested} logged wells, an estimate's lateral level is off by ${E.level_mae} API on average`:''}. Scale spans the laterals (P2–P98).</div>`;L.querySelector('.ug-gbar').after(SG.picker());L.hidden=colorBy!=='gamma';}
async function setColor(m){if(m==='gamma'){await gammaReady;if(!gamma)m='pad'}colorBy=m;overlay.querySelectorAll('.ug-color button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.color===m)));renderLegend();if(data)renderPanel();}
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
 if(next&&!pad){entryCamera=structuredClone(camera);pad=next;overlay.classList.add('pad-data');sectionOn=false;padPage.title='Pad data';padPage.src=padUrl();padPage.hidden=false;returnButton.hidden=false;padMenu.disabled=true;overlay.querySelector('#ug-all').hidden=true;overlay.querySelector('.ug-title').textContent=pad.name+' · Pad data';resize();}
 if(!next){pad=null;sectionOn=false;padPage.hidden=true;returnButton.hidden=true;overlay.classList.remove('pad-data');padMenu.disabled=false;overlay.querySelector('#ug-all').hidden=false;overlay.querySelector('.ug-title').textContent=areaTitle;resize();}
 padMenu.value=pad?.id||'';well=pad?.wells[0]||null;stage=null;interval=null;hover=null;tip.style.display='none';fit(pad);renderPanel();
}
function returnToCluster(){if(!pad)return;const saved=entryCamera;selectPad('');if(saved){Object.assign(camera,structuredClone(saved));goal.scale=saved.scale;goal.target=saved.target.slice();}entryCamera=null;returnButton.hidden=true;canvas.focus();}
returnButton.onclick=()=>returnToCluster();

function renderPanel(){content.replaceChildren();if(!pad){const all=data.pads.flatMap(p=>p.wells),nS=all.reduce((n,w)=>n+(w.stages||[]).length,0),nI=all.reduce((n,w)=>n+w.depth_intervals.length,0),nG=all.filter(w=>w.gv).length;content.innerHTML=`<div class="ug-stat">${all.length} wells · ${fmt(nS)} stage summaries · ${fmt(nI)} stage depths</div>Click a pad marker to lock on to it, or press its Wine rack button to open it in the wine rack window. Other pads stay visible.<p>Stage summaries and depths are as filed with the BCER. Open a well for its treatment charts where the Lab has read its frac report.</p>`+(colorBy==='gamma'&&gamma?`<p>Gamma ray is drawn along ${nG} of these wells (${all.filter(w=>w.gest).length} of them estimated from offset logs, dashed). Hover a well for its reading; lock a pad and pick a well for its full log.</p>`:'')+(showQuakes&&data.quakes?quakeSummary():'');return;}
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
function quakeSummary(){const q=data.quakes.filter(e=>SQ.pass(e)),n=q.length,rel=q.filter(e=>e.src==='bcsrc').length,near=q.filter(e=>e.near).length,big=n?Math.max(...q.map(e=>e.mag||0)):0,c=quakes.control;
 return `<p class="ug-quake"><b>${n} earthquakes</b> here since 2013${n?`, largest M${big}; ${rel} relocated by the BC Seismic Research Consortium (May 2022–Apr 2024, located to a few hundred metres), the rest from Earthquakes Canada (km-scale)`:''}. <b>${near}</b> coincide with a frac stage on a nearby well${c&&c.share_beyond_chance!=null?`; across the region about ${Math.round(c.share_beyond_chance*100)}% of such coincidences are more than chance (matching the same events with dates shifted by weeks finds ${c.by_chance} of ${c.matched})`:''}. A coincidence names the stage that was pumping, not a proven cause. Ring size is magnitude; a dashed line drops to the solved depth.${SQ.active()?` <b>Filtered:</b> ${SQ.describe()} (${n} of ${data.quakes.length} here).`:''}</p>`}
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
 c.strokeStyle=UK.base;c.beginPath();c.moveTo(0,base+.5);c.lineTo(W,base+.5);c.stroke();
 c.globalAlpha=w.gest?.55:1;w.gv.forEach((v,i)=>{if(v==null)return;const x0=X(w.gmd0+i*w.gbin),h=Math.min(1,v/200)*(base-4);c.fillStyle=GAMMA_INK[gammaBucket(v)];c.fillRect(x0,base-h,Math.max(1,X(w.gbin)),h)});c.globalAlpha=1;
 if(heel){c.strokeStyle=UK.mut;c.setLineDash([2,3]);c.beginPath();c.moveTo(X(heel)+.5,2);c.lineTo(X(heel)+.5,base);c.stroke();c.setLineDash([]);}
 if(interval){c.fillStyle=UK.on;c.fillRect(X(interval.top_m),base+1,Math.max(2,X(interval.base_m-interval.top_m)),3)}
 c.fillStyle=UK.mut;c.font='10px system-ui';c.textBaseline='bottom';c.fillText('0 m',0,H);c.textAlign='right';c.fillText(fmt(td)+' m MD',W,H);if(heel){c.textAlign='center';c.fillText('heel',Math.min(W-60,Math.max(20,X(heel))),H)}
 cv.onpointermove=e=>{const md=(e.clientX-cv.getBoundingClientRect().left)/W*td,i=Math.floor((md-w.gmd0)/w.gbin),v=w.gv[i];read.textContent=fmt(md)+' m MD · '+(v==null?'no reading':'GR '+v+' API')};cv.onpointerleave=()=>{read.textContent='Hover the strip for a reading'};
}
function project(q){const x=q[0]-camera.target[0],y=q[1]-camera.target[1],z=q[2]-camera.target[2],c=Math.cos(camera.yaw),s=Math.sin(camera.yaw),xx=x*c-z*s,zz=x*s+z*c,cp=Math.cos(camera.pitch),sp=Math.sin(camera.pitch);return [width/2+camera.pan[0]+xx*camera.scale,height/2+camera.pan[1]-(y*cp-zz*sp)*camera.scale,zz*cp+y*sp];}
function path(points,color,lineWidth,alpha=1){ctx.beginPath();points.forEach((q,i)=>{const a=project(q);i?ctx.lineTo(a[0],a[1]):ctx.moveTo(a[0],a[1])});ctx.strokeStyle=color;ctx.lineWidth=lineWidth;ctx.globalAlpha=alpha;ctx.stroke();ctx.globalAlpha=1;}
function draw(){if(!active)return;raf=requestAnimationFrame(draw);keyNav();camera.scale+=(goal.scale-camera.scale)*.11;camera.target=camera.target.map((v,i)=>v+(goal.target[i]-v)*.1);ctx.clearRect(0,0,width,height);hits=[];
 const GR=data.gridR||6000,GD=data.gridD||3000,GS=GR>12000?2000:1000;for(let d=0;d<=GD;d+=1000){for(let a=-GR;a<=GR;a+=GS){path([[a,-d,-GR],[a,-d,GR]],UK.grid,.6,UK.gridA[d===0?0:1]);path([[-GR,-d,a],[GR,-d,a]],UK.grid,.6,UK.gridA[d===0?0:1])}const t=project([-GR*.6,-d,0]);ctx.fillStyle=UK.depth;ctx.font='11px monospace';ctx.fillText(d+' m TVD',t[0],t[1]);}
 if(showQuakes&&data.quakes)drawQuakes();
 const wells=data.pads.flatMap(p=>p.wells).sort((a,b)=>project(a.points.at(-1))[2]-project(b.points.at(-1))[2]);
 // In gamma mode colour means gamma only: pads, toes and intervals go neutral.
 const g=colorBy==='gamma',ink=c=>g?UK.neutral:c;
 // the well under the pointer is picked out: an outline of ink, and thicker
 const hw=hover&&hover.w&&!hover.q?hover.w:null;
 wells.forEach(w=>{const selected=w===well,bright=!pad||w.pad===pad,hov=w===hw&&bright;if(hov)path(w.points,UK.hl,(selected?3.5:3)+4,.85);if(g)gammaWell(w,selected||hov,bright);else path(w.points,w.pad.color,selected?3.5:hov?3:bright?1.7:1,bright?(hov?1:.88):.25);
  // hover targets along the path, so a well can be caught anywhere, not only at its toe
  if(bright)for(let i=2;i<w.points.length-1;i+=3){const a=project(w.points[i]);hits.push({x:a[0],y:a[1],w,p:w.pad,r:6,path:true})}const q=project(w.points.at(-1)),lit=rackHover===w.pad;ctx.beginPath();ctx.arc(q[0],q[1],selected?4:lit?5:2,0,Math.PI*2);ctx.fillStyle=lit?UK.lit:ink(w.pad.color);ctx.globalAlpha=bright?1:.18;ctx.fill();ctx.globalAlpha=1;if(bright)hits.push({x:q[0],y:q[1],w,p:w.pad,r:8});w.depth_intervals.forEach(d=>{const a=project(d.point),on=interval===d||hover?.d===d,s=on?4:g?1.2:1.7;ctx.globalAlpha=bright?(g&&!on?.55:1):.22;ctx.fillStyle=on?UK.on:ink(w.pad.color);ctx.fillRect(a[0]-s,a[1]-s,s*2,s*2);ctx.globalAlpha=1;if(bright)hits.push({x:a[0],y:a[1],w,p:w.pad,d,r:5})});});
 const labels=[];data.pads.forEach(p=>{const q=project(p.point),selectable=!pad||p===pad,pc=ink(p.color);ctx.globalAlpha=selectable?1:.18;const on=p===pad||hover?.p===p;ctx.beginPath();ctx.arc(q[0],q[1],on?12:9,0,Math.PI*2);ctx.fillStyle=on?UK.padOn:pc;ctx.shadowColor=pc;ctx.shadowBlur=UK.glow?(on?20:8):(on?10:0);ctx.fill();ctx.shadowBlur=0;ctx.strokeStyle=UK.padRing;ctx.lineWidth=UK.glow?1:1.5;ctx.stroke();ctx.fillStyle=on?UK.padOn:pc;ctx.font=(on?'600 ':'')+'12px system-ui';let ly=q[1];while(labels.some(l=>Math.abs(l.x-q[0])<115&&Math.abs(l.y-ly)<20))ly+=22;labels.push({x:q[0],y:ly});if(ly!==q[1]){ctx.beginPath();ctx.moveTo(q[0]+7,q[1]);ctx.lineTo(q[0]+14,ly);ctx.strokeStyle=pc;ctx.stroke();}ctx.fillText(p.name,q[0]+14,ly+4);if(selectable){hits.push({x:q[0],y:q[1],p,r:18});hits.push({x:q[0]+55,y:ly,p,r:14,label:true});}ctx.globalAlpha=1;});
 placeRackButtons();
}
// The whole path dashed in slate first: where there is no reading (no LAS, or above
// the first logged depth) that is what shows; logged bins are stroked over it.
function gammaWell(w,selected,bright){ctx.setLineDash([3,4]);path(w.points,UK.none,selected?1.8:1.1,bright?.85:.2);ctx.setLineDash([]);if(!w.gpts)return;
 const P=w.gpts.map(project);ctx.lineCap='round';ctx.lineWidth=selected?4.5:bright?2.4:1.2;ctx.globalAlpha=bright?.96:.22;
 if(w.gest){ctx.setLineDash([7,5]);ctx.lineCap='butt';ctx.globalAlpha*=.8}
 w.gby.forEach((ix,k)=>{if(!ix.length)return;ctx.beginPath();ix.forEach(i=>{ctx.moveTo(P[i][0],P[i][1]);ctx.lineTo(P[i+1][0],P[i+1][1])});ctx.strokeStyle=GAMMA_INK[k];ctx.stroke()});
 ctx.setLineDash([]);ctx.globalAlpha=1;ctx.lineCap='butt';
 if(bright)for(let i=1;i<w.gv.length;i+=3)if(w.gv[i]!=null)hits.push({x:(P[i][0]+P[i+1][0])/2,y:(P[i][1]+P[i+1][1])/2,w,p:w.pad,g:i,r:5});}
function resize(){width=overlay.clientWidth;height=canvas.clientHeight;const d=devicePixelRatio||1;canvas.width=width*d;canvas.height=height*d;ctx.setTransform(d,0,0,d,0,0)}
async function openArea(ids,opts={}){button.disabled=true;button.textContent='Loading…';if(window.stratumSection)window.stratumSection.closeMapDock();
 try{await loadArea(ids);if(opts.title){areaTitle=opts.title+' · Below the surface';overlay.querySelector('.ug-title').textContent=areaTitle}areaName=opts.title||'';active=true;overlay.inert=false;overlay.classList.add('active');overlay.setAttribute('aria-hidden','false');resize();selectPad('');camera.scale=goal.scale*.75;cancelAnimationFrame(raf);draw();
  if(opts.pad)selectPad(opts.pad);else overlay.querySelector('#ug-all').focus();button.textContent='Change View'}
 catch(e){button.textContent='Retry Change View';console.error(e)}finally{button.disabled=false}}
button.onclick=()=>openArea(areaIds());
// for the map: open 3D on the pads around one pad, locked to it
window.stratum3D={section,open:padId=>openArea(idsAround(padId),{pad:padId}),openArea:(ids,opts={})=>openArea(ids,opts),ready:regionReady};
function close(){active=false;cancelAnimationFrame(raf);overlay.classList.remove('active');overlay.setAttribute('aria-hidden','true');overlay.inert=true;positionButton();button.focus()}
overlay.querySelector('#ug-back').onclick=close;overlay.querySelector('#ug-all').onclick=()=>selectPad('');overlay.querySelector('#ug-reset').onclick=()=>{camera.yaw=-.5;camera.pitch=.4;fit(pad)};padMenu.onchange=()=>selectPad(padMenu.value);
window.addEventListener('resize',()=>{resize();if(active)fit(pad)});overlay.addEventListener('keydown',e=>{if(e.key==='Escape'){if(pad)returnToCluster();else close()}});
canvas.oncontextmenu=e=>e.preventDefault();canvas.onpointerdown=e=>{drag={x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY,pan:e.shiftKey||e.button===2};canvas.setPointerCapture(e.pointerId);tip.style.display='none'};
canvas.onpointermove=e=>{if(drag){const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(drag.pan){camera.pan[0]+=dx;camera.pan[1]+=dy}else{camera.yaw+=dx*.006;camera.pitch=Math.max(-.9,Math.min(1.3,camera.pitch+dy*.005))}drag.x=e.clientX;drag.y=e.clientY;return}hover=[...hits].reverse().find(h=>Math.hypot(h.x-e.clientX,h.y-e.clientY)<h.r);canvas.style.cursor=hover?'pointer':'grab';tip.style.display=hover?'block':'none';if(hover){tip.textContent=hover.q?`M${hover.q.mag} ${hover.q.type} · ${hover.q.date} · ${hover.q.src==='bcsrc'?'relocated (BC Seismic Research Consortium), ±'+(hover.q.herr??'?')+' m across, ±'+(hover.q.derr??'?')+' m deep':'Earthquakes Canada'+(hover.q.fixed?', depth not solved':'')}${hover.q.industry?' · suspected industry-related':''}${hover.q.near?' · '+hover.q.near:''}`:hover.d?'WA '+hover.w.well.wa+' · depth order '+hover.d.n+' · '+fmt(hover.d.top_m,1)+'–'+fmt(hover.d.base_m,1)+' m MD':hover.g!=null?'WA '+hover.w.well.wa+' · '+fmt(hover.w.gmd0+(hover.g+.5)*hover.w.gbin)+' m MD · GR '+(hover.w.gest?'~':'')+hover.w.gv[hover.g]+' API'+(hover.w.gest?' (estimated from WA '+hover.w.gfrom.map(f=>f.wa).join(', ')+')':''):hover.w?'WA '+hover.w.well.wa+' · '+hover.w.stages.length+' stage summaries':hover.p.name+' · '+hover.p.wells.length+' wells · Click to lock';tip.style.left=Math.min(width-270,e.clientX+16)+'px';tip.style.top=Math.min(height-65,e.clientY+16)+'px'}};
canvas.onpointerup=e=>{if(drag&&Math.hypot(e.clientX-drag.startX,e.clientY-drag.startY)<5){const hit=[...hits].reverse().find(h=>Math.hypot(h.x-e.clientX,h.y-e.clientY)<h.r);if(hit&&!hit.q&&(!pad||hit.p===pad)){if(!pad)selectPad(hit.p.id);if(hit.w){well=hit.w;if(hit.d)focusInterval(well,hit.d);else renderPanel();viewPicked()}}}drag=null};canvas.onpointercancel=()=>drag=null;canvas.onpointerleave=()=>{hover=null;tip.style.display='none'};
canvas.addEventListener('wheel',e=>{e.preventDefault();goal.scale=Math.max(.012,Math.min(2,goal.scale*Math.exp(-e.deltaY*.0015)))},{passive:false});
// ---------- the keyboard ----------
// As on the map: the arrows move across the scene, Shift and an arrow turn it
// (left, right) and tilt it (up, down), + and − zoom. Held, they keep going,
// a little each frame. Not while typing or choosing in a menu.
const navKeys=new Set(),NAV=['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-','_'];let navShift=false,navLast=0;
const typing=t=>!!(t&&t.closest&&t.closest('input,select,textarea,[contenteditable=""],[contenteditable=true]'));
addEventListener('keydown',e=>{navShift=e.shiftKey;if(!active||e.metaKey||e.ctrlKey||e.altKey||!NAV.includes(e.key)||typing(e.target))return;e.preventDefault();if(!navKeys.size)navLast=0;navKeys.add(e.key);tip.style.display='none'});
addEventListener('keyup',e=>{navShift=e.shiftKey;navKeys.delete(e.key);if(e.key==='+'||e.key==='=')navKeys.delete('+'),navKeys.delete('=');if(e.key==='-'||e.key==='_')navKeys.delete('-'),navKeys.delete('_')});
addEventListener('blur',()=>{navKeys.clear();navShift=false});
function keyNav(){if(!navKeys.size)return;const now=performance.now(),dt=navLast?Math.min(.05,(now-navLast)/1000):1/60;navLast=now;const k=x=>navKeys.has(x)?1:0;
 const h=k('ArrowRight')-k('ArrowLeft'),v=k('ArrowDown')-k('ArrowUp'),z=Math.sign(k('+')+k('=')-k('-')-k('_'));
 if(navShift){camera.yaw+=h*1.5*dt;camera.pitch=Math.max(-.9,Math.min(1.3,camera.pitch+v*.9*dt))}
 else{camera.pan[0]-=h*620*dt;camera.pan[1]-=v*620*dt}
 if(z)goal.scale=Math.max(.012,Math.min(2,goal.scale*Math.exp(z*1.6*dt)))}

// ---------- Wine rack ----------
// A pad across its laterals (winerack.html), in a window of its own, so this
// view and the map stay exactly as they are. One window: each pad sent to it is
// added under the racks already there. Its wells show their 2D section here, in
// this page's dock (wellsection-host.js), following the rack's line. The window is found by its name; one
// still loading takes the pad from a queue it reads as it starts.
let rackHover=null;
const RACK_WIN='stratum-rack';
function openRackWindow(id){if(!id)return false;let w=null;const me=window.stratumSection&&window.stratumSection.id;
 try{w=window.open('',RACK_WIN,'popup,width=1240,height=920')}catch(e){}
 if(!w){rackBlocked(id);return false}
 try{if(w.stratumRacks){w.stratumRacks.add(id,me);w.focus();return true}
  if(/\/winerack(\.html)?$/.test(w.location.pathname)){(w.stratumRackQueue=w.stratumRackQueue||[]).push(id);w.focus();return true}}catch(e){}
 // a fresh window: load the racks into it
 try{w.location.href='winerack.html?pads='+encodeURIComponent(id)+(me?'&owner='+encodeURIComponent(me):'');w.focus()}catch(e){rackBlocked(id);return false}
 return true}
// a pop-up blocker in the way: a link instead, which opens the racks in a tab
function rackBlocked(id){let n=document.getElementById('rack-blocked');if(!n){n=document.createElement('div');n.id='rack-blocked';n.setAttribute('role','status');document.body.append(n)}
 n.innerHTML='Your browser blocked the wine rack window. <a target="'+RACK_WIN+'" href="winerack.html?pads='+encodeURIComponent(id)+'">Open the wine rack</a> <button type="button" aria-label="Dismiss">×</button>';n.hidden=false;n.querySelector('button').onclick=()=>{n.hidden=true};n.querySelector('a').onclick=()=>{n.hidden=true};clearTimeout(n._t);n._t=setTimeout(()=>{n.hidden=true},12000)}
window.stratumRack={open:openRackWindow};
const rackLayer=document.createElement('div');rackLayer.className='ug-rackbtns';overlay.append(rackLayer);
// where a pad's button rides: the middle of its toes
function toeMid(p){if(!p.toeMid)p.toeMid=[0,1,2].map(i=>p.wells.reduce((a,w)=>a+w.points.at(-1)[i],0)/p.wells.length);return p.toeMid}
// The buttons ride on each pad's cluster of toes as the scene turns; ones that
// would land on each other step down, the way the pad labels do.
function placeRackButtons(){if(!data)return;const placed=[];data.pads.forEach(p=>{let b=p.rackBtn;if(!b){b=p.rackBtn=document.createElement('button');b.type='button';b.className='ug-rackbtn';b.onclick=()=>openRackWindow(p.id);b.onmouseenter=b.onfocus=()=>{rackHover=p};b.onmouseleave=b.onblur=()=>{if(rackHover===p)rackHover=null};rackLayer.append(b)}
 const on=active&&(!pad||p===pad),q=on?project(toeMid(p)):null,vis=on&&q[0]>20&&q[0]<width-20&&q[1]>90&&q[1]<height-30;b.hidden=!vis;if(!vis)return;
 b.textContent='Wine rack ↗';b.title='Wine rack: '+p.name+' across its laterals, in the wine rack window';b.setAttribute('aria-label',b.title);let y=q[1]+12;while(placed.some(l=>Math.abs(l.x-q[0])<90&&Math.abs(l.y-y)<30))y+=30;placed.push({x:q[0],y});b.style.transform=`translate(${Math.round(q[0])}px,${Math.round(y)}px) translateX(-50%)`;});}
// Leaving for a well view and coming back should land where you were, not at the
// default cluster. The camera, the focused pad and the selected well are stashed
// for this tab only, and restored once, so a normal close still reopens clean.
const UG_KEY='stratum.underground';
function ugSave(){if(!active)return;try{sessionStorage.setItem(UG_KEY,JSON.stringify(ugState()))}catch(e){}}
function ugState(){return({
 yaw:camera.yaw,pitch:camera.pitch,scale:camera.scale,target:camera.target.slice(),pan:camera.pan.slice(),
 pad:pad?pad.id:'',wa:well&&well.well?well.well.wa:'',entryCamera,
 stage:stage?stage.label:null,interval:interval?interval.n:null,colorBy,area:data?data.pads.map(p=>p.id):null,areaName,
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
 draw();button.textContent='Change View';
})();
})();
