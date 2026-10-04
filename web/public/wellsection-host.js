// The well section, from the map and the 3D view. "View well" docks it under
// what is on screen: the 3D view's bottom panel when a pad is locked there,
// otherwise a dock along the bottom of the map. Pop out (in the section) moves
// it into a window of its own that keeps following the selected well; the two
// talk over BroadcastChannel 'stratum-section', addressed by this page's id.
// A stage clicked in the section, docked or popped, opens its charts here.
(() => {
  'use strict';
  const ORIGIN = location.origin;
  const H_KEY = 'stratum.sectionHeight', STATE_KEY = 'stratum.sectionDock';
  const chan = 'BroadcastChannel' in self ? new BroadcastChannel('stratum-section') : null;
  const ME = Math.random().toString(36).slice(2);
  const url = (wa, stage) => 'wellsection.html?wa=' + encodeURIComponent(wa)
    + (stage != null && stage !== '' ? '&stage=' + encodeURIComponent(stage) : '') + '&embedded=1&owner=' + ME + '&page=map';
  const tell = (wa, stage) => { if (chan) chan.postMessage({ type: 'show', wa: String(wa), stage, from: ME, page: 'map' }); };
  const ug = () => window.stratum3D && window.stratum3D.section;   // the 3D view's bottom panel

  let popHeard = false;                  // a popped-out section window has said hello
  let docked = null;                     // 'map' | '3d'
  let shown = { wa: null, stage: null };

  const dock = document.createElement('div');
  dock.id = 'ws-dock'; dock.hidden = true;
  dock.innerHTML = '<div class="ws-grip" role="separator" aria-orientation="horizontal" aria-label="Resize the well section" tabindex="0"></div><iframe title="Well section"></iframe>';
  document.body.append(dock);
  const mapFrame = dock.querySelector('iframe'), grip = dock.querySelector('.ws-grip');

  const resizeMap = () => { try { if (typeof map !== 'undefined') map.resize(); } catch (e) { /* not ready */ } };
  function setHeight(px, save) {
    const h = Math.round(Math.max(180, Math.min(innerHeight * 0.8, px)));
    document.body.style.setProperty('--ws-h', h + 'px');
    if (save) try { localStorage.setItem(H_KEY, String(h)); } catch (e) { /* private mode */ }
    resizeMap();
  }
  let h0 = Math.round(innerHeight * 0.42);
  try { h0 = +localStorage.getItem(H_KEY) || h0; } catch (e) { /* private mode */ }
  setHeight(h0, false);
  grip.addEventListener('pointerdown', e => {
    e.preventDefault(); grip.setPointerCapture(e.pointerId); mapFrame.style.pointerEvents = 'none';
    const move = ev => setHeight(innerHeight - ev.clientY, false);
    const up = ev => { grip.removeEventListener('pointermove', move); grip.removeEventListener('pointerup', up); mapFrame.style.pointerEvents = ''; setHeight(innerHeight - ev.clientY, true); };
    grip.addEventListener('pointermove', move); grip.addEventListener('pointerup', up);
  });
  grip.addEventListener('keydown', e => {
    const h = dock.getBoundingClientRect().height;
    if (e.key === 'ArrowUp') { e.preventDefault(); setHeight(h + 40, true); }
    if (e.key === 'ArrowDown') { e.preventDefault(); setHeight(h - 40, true); }
  });

  // the section in a frame: told directly when it is already a section, loaded otherwise
  function showIn(frame, wa, stage) {
    try {
      const w = frame.contentWindow;
      if (w && typeof w.stratumSectionShow === 'function') { w.stratumSectionShow(wa, stage); return; }
    } catch (e) { /* loading */ }
    frame.src = url(wa, stage);
  }
  const popAlive = () => popHeard;

  function openDock(wa, stage) {
    shown = { wa: String(wa), stage: stage == null ? null : String(stage) };
    const u = ug();
    if (u && u.available()) {
      if (docked === 'map') closeDock('map');
      if (u.showing()) showIn(u.frame(), wa, stage); else u.show(url(wa, stage));
      docked = '3d';
      return;
    }
    if (!dock.hidden) showIn(mapFrame, wa, stage); else mapFrame.src = url(wa, stage);
    dock.hidden = false; document.body.classList.add('ws-docked'); resizeMap();
    docked = 'map';
  }
  function closeDock(where) {
    if (where === '3d') { const u = ug(); if (u) u.hide(); }
    else { dock.hidden = true; document.body.classList.remove('ws-docked'); mapFrame.src = 'about:blank'; resizeMap(); }
    if (docked === where) docked = null;
  }

  // "View well": to the popped-out window when there is one, docked otherwise
  function view(wa, stage) {
    if (wa == null) return;
    if (popAlive()) {
      shown = { wa: String(wa), stage: stage == null ? null : String(stage) };
      tell(wa, stage);
      return;
    }
    openDock(wa, stage);
  }
  // the selection moved: an open section follows it
  function follow(wa, stage) {
    if (wa == null) return;
    stage = stage == null ? null : String(stage);
    if (shown.wa === String(wa) && shown.stage === stage) return;
    let followed = false;
    if (popAlive()) { tell(wa, stage); followed = true; }
    if (docked === '3d') {
      const u = ug();
      if (u && u.showing()) { showIn(u.frame(), wa, stage); followed = true; } else docked = null;
    } else if (docked === 'map' && !dock.hidden) { showIn(mapFrame, wa, stage); followed = true; }
    if (followed) shown = { wa: String(wa), stage };
  }

  addEventListener('message', e => {
    if (e.origin !== ORIGIN) return;
    const m = e.data;
    if (!m || typeof m !== 'object' || typeof m.type !== 'string' || !m.type.startsWith('ws:')) return;
    const u = ug(), from3D = u && e.source === u.frame().contentWindow;
    const fromDock = e.source === mapFrame.contentWindow;
    if (m.type === 'ws:close' && (from3D || fromDock)) closeDock(from3D ? '3d' : 'map');
    else if (m.type === 'ws:popped' && (from3D || fromDock)) {      // the section opened its own window
      popHeard = true; shown = { wa: String(m.wa), stage: m.stage == null ? null : String(m.stage) };
      closeDock(from3D ? '3d' : 'map');
    } else if (m.type === 'ws:stage' && m.wa) openCharts(m.wa, m.label);
  });
  const openCharts = (wa, label) => {
    location.href = 'wellview.html?wa=' + encodeURIComponent(wa) + (label ? '&stage=' + encodeURIComponent(label) : '');
  };
  if (chan) {
    chan.onmessage = e => {
      const m = e.data || {};
      if (m.type === 'hello') { popHeard = true; if (m.wa) shown = { wa: String(m.wa), stage: shown.stage }; }
      else if (m.type === 'bye') popHeard = false;
      else if (m.to === ME && (m.type === 'open-stage' || m.type === 'dock')) {
        chan.postMessage({ type: 'ack', id: m.id });
        if (m.type === 'dock') { popHeard = false; openDock(m.wa, m.stage); try { window.focus(); } catch (err) { /* the browser decides */ } }
        else openCharts(m.wa, m.label);
      }
    };
    // a section popped out before this page loaded: hear from it, and be its main window now
    chan.postMessage({ type: 'ping' });
    chan.postMessage({ type: 'claim', from: ME, page: 'map' });
  }

  // the map's dock comes back with the page (the 3D view keeps its own)
  addEventListener('pagehide', () => {
    try {
      if (docked === 'map' && !dock.hidden && shown.wa) sessionStorage.setItem(STATE_KEY, JSON.stringify(shown));
      else sessionStorage.removeItem(STATE_KEY);
    } catch (e) { /* private mode */ }
  });
  try {
    const s = JSON.parse(sessionStorage.getItem(STATE_KEY) || 'null');
    sessionStorage.removeItem(STATE_KEY);
    if (s && s.wa) setTimeout(() => { if (!(ug() && ug().available())) openDock(s.wa, s.stage); }, 0);
  } catch (e) { /* private mode */ }

  window.stratumSection = {
    view, follow,
    closeMapDock: () => { if (!dock.hidden) closeDock('map'); },
    open: () => popAlive() || !!docked,
  };
})();
