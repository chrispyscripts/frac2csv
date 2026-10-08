// The stage report's numbers on real wells' files, without a browser: a table
// row per stage, a CSV with its source line, header and a line per stage, the
// P10-P90 envelope in order at every x, the proppant check as the totals' ratio.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const pub=path.join(__dirname,'../web/public');
const read=f=>fs.readFileSync(path.join(pub,f),'utf8');
// fetch reads the site's own files from disk
const fetch=async u=>{const f=path.join(pub,decodeURIComponent(String(u).split('?')[0]));
  return fs.existsSync(f)?{ok:true,status:200,json:async()=>JSON.parse(fs.readFileSync(f,'utf8'))}:{ok:false,status:404,json:async()=>null}};
const c={console,Math,JSON,Promise,Number,String,Object,Array,Set,Map,isFinite,Date,fetch,
  localStorage:{getItem:()=>null,setItem(){},removeItem(){}},
  document:{documentElement:{dataset:{theme:'light'}},getElementById:()=>null},   // no page: the pure parts only
  addEventListener(){},dispatchEvent(){},CustomEvent:class{}};
c.window=c;vm.createContext(c);
vm.runInContext(read('metrics.js'),c);vm.runInContext(read('report.js'),c);
const R=c.FVReport,FVM=c.FVMetrics,plain=o=>JSON.parse(JSON.stringify(o));
assert(R&&typeof R.load==='function','report.js puts its working parts on window.FVReport');

// a CSV line's fields, quotes respected
function fields(line){const out=[];let cur='',q=false;
  for(let i=0;i<line.length;i++){const ch=line[i];
    if(q){if(ch==='"'&&line[i+1]==='"'){cur+='"';i++}else if(ch==='"')q=false;else cur+=ch}
    else if(ch==='"')q=true;else if(ch===','){out.push(cur);cur=''}else cur+=ch}
  out.push(cur);return out}

(async()=>{
  // ---------- WA 40403, Blueberry A-97-L (region-40402): 102 charts from 1-second exports ----------
  const WA='40403',padId='region-40402';
  const raw=JSON.parse(read(`data/metrics/pads/${padId}.json`)).wells[WA];
  const m=await R.load(WA);
  assert(m,'the well loads');
  assert.equal(m.pad.id,padId);
  assert.equal(m.rows.length,raw.rows.length,'every metrics row is in the report');
  const tr=R.tableRows(m.rows);
  assert.equal(tr.length,raw.rows.length,'one table row per stage row');
  assert(tr.every(t=>t.cells.length===R.TABLE.length),'every row has every column');
  assert.deepEqual(plain(tr.map(t=>t.cells[0].s)),plain(m.rows.map(r=>String(r.label))),'the first column is the stage');
  const tops=m.rows.map(r=>r.top).filter(v=>v!=null);
  for(let i=1;i<tops.length;i++)assert(tops[i]<=tops[i-1],'toe to heel: MD falls down the table');
  // a filed-only row shows its filed figures where the curves have none, and says so
  const fr=tr.find(t=>t.r.src==='filed'&&t.r.fAvgP!=null);
  if(fr){const j=R.TABLE.findIndex(x=>x.k==='avgP');assert.equal(fr.cells[j].v,fr.r.fAvgP);assert(fr.cells[j].filed,'marked as filed')}

  // the CSV: a line naming the sources, the header, a line per stage, every column on each
  const lines=R.csv(m).trim().split('\n');
  assert(lines[0].startsWith('# FracView stage report'),'a comment line first');
  assert(lines[0].includes(raw.totals.file),'it names the source PDF');
  assert(lines[0].includes('BC Energy Regulator hydraulic fracture table')&&lines[0].includes('Open Data Licence'),'and the filing and its licence');
  assert(!lines[0].includes(','),'no commas in the comment, so a spreadsheet keeps it in one cell');
  assert.deepEqual(fields(lines[1]),plain(R.CSV_COLS.map(x=>x[1])),'the header');
  assert.equal(lines.length,2+raw.rows.length,'a header and one line per stage');
  for(const l of lines.slice(2))assert.equal(fields(l).length,R.CSV_COLS.length,'every column on every line');
  const fi=R.CSV_COLS.findIndex(x=>x[0]==='fProp');
  assert.equal(fields(lines[2])[fi],String(m.rows[0].fProp),'filed proppant carried through');

  // the overlay: every chart joined to its row, and the envelope ordered at every x
  const withCurves=m.d.stages.filter(s=>s.series&&Object.values(s.series).some(a=>Array.isArray(a)&&a.some(v=>v!=null)));
  assert.equal(m.charts.length,withCurves.length,'one overlay line per chart');
  assert(m.charts.filter(x=>x.r).length>=withCurves.length-1,'charts find their rows by label, date and start');
  for(const ch of Object.keys(R.CHANNELS))for(const xm of ['min','vol']){
    const curves=m.charts.map(x=>R.stageCurve(x.s,ch,xm)).filter(Boolean);
    assert(curves.length>90,`${ch} by ${xm}: the charts have the curve`);
    for(const cv of curves)for(let i=1;i<cv.x.length;i++)assert(cv.x[i]>=cv.x[i-1],'x never runs backwards');
    const end=Math.max(...curves.map(cv=>cv.x[cv.x.length-1])),minN=R.minStages(curves.length);
    const env=R.envelope(curves,R.grid(end,240),minN),drawn=env.filter(e=>e.p50!=null);
    assert(drawn.length>60,`${ch} by ${xm}: an envelope to draw`);
    for(const e of drawn){
      assert(e.p10<=e.p50&&e.p50<=e.p90,`${ch} by ${xm} at ${e.x}: p10 <= median <= p90`);
      assert(e.n>=minN,'only where enough stages reach');
    }
  }
  // minutes: sample i is i x step_s; slurry: rate x time
  const s0=m.charts[0].s,cm=R.stageCurve(s0,'press','min');
  assert.equal(cm.x[10],10*s0.step_s/60);
  const cvol=R.stageCurve(s0,'rate','vol'),rates=s0.series.rate;
  const vol=rates.slice(0,-1).reduce((a,v)=>a+(v>0?v*s0.step_s/60:0),0);
  assert(Math.abs(cvol.x[cvol.x.length-1]-vol)<1e-9,'the slurry axis is the rate integrated over time');
  // the envelope on numbers worked by hand
  const flat=[1,2,3].map(v=>({x:[0,1,2],y:[v,v,v]})),e=R.envelope(flat,[0,1,2,3],3);
  assert.equal(e[1].p50,2);assert(Math.abs(e[1].p10-1.2)<1e-12&&Math.abs(e[1].p90-2.8)<1e-12);
  assert.equal(e[3].p50,null,'past every curve, no envelope');
  assert.equal(R.valueAt({x:[0,1,2],y:[0,null,4]},0.5),0,'across a gap, the nearer edge');
  assert.equal(R.valueAt({x:[0,1,2],y:[0,2,4]},1.5),3,'straight between samples');

  // the checks: the proppant percentage is the totals' ratio
  const q=R.qc(m.totals,m.rows);
  assert(Math.abs(q.prop.pct/100-raw.totals.prop/raw.totals.propFiledCharted)<1e-12,'proppant, curves vs filed');
  assert(Math.abs(q.fluid.pct/100-raw.totals.clean/raw.totals.fluidFiledCharted)<1e-12,'fluid, curves vs filed');
  const d=m.rows.filter(r=>r.isip!=null&&r.fIsip!=null).map(r=>r.isip-r.fIsip).sort((a,b)=>a-b);
  assert.equal(q.isip.n,d.length);assert(Math.abs(q.isip.median-R.quantile(d,.5))<1e-12,'ISIP: the median difference');
  assert.equal(q.matched.n,raw.totals.matchedByTime);assert.equal(q.matched.of,raw.totals.stagesCharted);

  // production: calendar-day rates from the first producing month
  const P=JSON.parse(read('data/prod/wells.json')).wells[WA],ser=R.prodSeries(P);
  assert.equal(ser.length,P.g.length);assert.equal(ser[0].ym,P.f);
  assert(Math.abs(ser[0].gas-P.g[0]/R.daysIn(P.f))<1e-12,'gas over the days in the month');
  assert.equal(R.daysIn('2024-02'),29);assert.equal(R.daysIn('2023-02'),28);assert.equal(R.addMonths('2022-11',3),'2023-02');

  // the pad's other charted wells, to compare with
  assert(m.others.length>0&&m.others.every(o=>o.wa!==WA),'other wells on the pad');

  // ---------- a Gundy well with two possible screenouts (gundy-08) ----------
  const g=await R.load('34737'),groups=R.flagGroups(g.rows),so=groups.find(x=>x.k==='screenout');
  assert(so&&so.rows.length===2,'both screenouts listed');
  // its rows have no filed interval: the charts' own, marked, and toe to heel by depth then stage number (not as text)
  const gt=g.rows.filter(r=>r.top!=null);
  assert(gt.length>0&&gt.every(r=>r.mdFrom==='chart'),'depths from the charts, marked');
  for(let i=1;i<gt.length;i++)assert(gt[i].top<=gt[i-1].top,'deepest first');
  const gn=g.rows.filter(r=>r.top==null).map(r=>+r.n);
  for(let i=1;i<gn.length;i++)assert(gn[i]>=gn[i-1],'undepthed rows by stage number');
  assert.deepEqual(plain(groups.map(x=>x.k)),plain(FVM.FLAGS.filter(k=>groups.some(x=>x.k===k))),'flags in metrics.js order');

  // ---------- a well with its filing only (region-30023) ----------
  const f=await R.load('30023');
  assert.equal(f.charts.length,0,'no curves');
  assert.equal(R.tableRows(f.rows).length,f.rows.length);
  assert.equal(R.csv(f).trim().split('\n').length,2+f.rows.length);
  assert.equal(R.qc(f.totals,f.rows).charted,0);
  assert.equal(await R.load('99999'),null,'an unknown well');
  console.log(`PASS: stage report for WA ${WA} (${raw.rows.length} rows, ${m.charts.length} charts), Gundy screenouts, a filed-only well`);
})().catch(e=>{console.error(e);process.exitCode=1});
