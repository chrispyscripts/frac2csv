// The well section, from the map and the 3D view. "View well" docks it under
// what is on screen: the 3D view's bottom panel when a pad is locked there,
// otherwise a dock along the bottom of the map. Pop out (in the section) moves
// it into a window of its own that keeps following the selected well; the two
// talk over BroadcastChannel 'stratum-section', addressed by this page's id.
// A stage clicked in the section opens its charts in a window of their own
// (wellsection.js), so this page stays as it is.
//
// The wine rack window (winerack.html) drives the section here too, over
// BroadcastChannel 'stratum-rack': a well clicked there is shown here, and its
// line, as it moves along the pad, moves a cursor along the well (`at`, metres
// MD), picking out the stage there with its chart as if it were hovered.
(() => {
  'use strict';
  const ORIGIN = location.origin;
  const H_KEY = 'stratum.sectionHeight', STATE_KEY = 'stratum.sectionDock';
  const chan = 'BroadcastChannel' in self ? new BroadcastChannel('stratum-section') : null;
  const ME = Math.random().toString(36).slice(2);
  const atq = at => at != null && isFinite(at) ? '&at=' + Math.round(at) : '';
  const url = (wa, stage, at) => 'wellsection.html?wa=' + encodeURIComponent(wa)
    + (stage != null && stage !== '' ? '&stage=' + encodeURIComponent(stage) : '') + atq(at) + '&embedded=1&owner=' + ME + '&page=map';
  const tell = (wa, stage, at) => { if (chan) chan.postMessage({ type: 'show', wa: String(wa), stage, at: at == null ? null : +at, from: ME, page: 'map' }); };
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
  function showIn(frame, wa, stage, at) {
    try {
      const w = frame.contentWindow;
      if (w && typeof w.stratumSectionShow === 'function') { w.stratumSectionShow(wa, stage, at); return; }
    } catch (e) { /* loading */ }
    frame.src = url(wa, stage, at);
  }
  // the rack's line on the well shown: straight to the section where it is a frame here
  function cursorIn(frame, wa, at) {
    try {
      const w = frame.contentWindow;
      if (w && typeof w.stratumSectionCursor === 'function') w.stratumSectionCursor(wa, at);
    } catch (e) { /* loading: it has the line from its address */ }
  }
  const popAlive = () => popHeard;

  function openDock(wa, stage, at) {
    shown = { wa: String(wa), stage: stage == null ? null : String(stage) };
    const u = ug();
    if (u && u.available()) {
      if (docked === 'map') closeDock('map');
      if (u.showing()) showIn(u.frame(), wa, stage, at); else u.show(url(wa, stage, at));
      docked = '3d';
      return;
    }
    if (!dock.hidden) showIn(mapFrame, wa, stage, at); else mapFrame.src = url(wa, stage, at);
    dock.hidden = false; document.body.classList.add('ws-docked'); resizeMap();
    docked = 'map';
  }
  function closeDock(where) {
    if (where === '3d') { const u = ug(); if (u) u.hide(); }
    else { dock.hidden = true; document.body.classList.remove('ws-docked'); mapFrame.src = 'about:blank'; resizeMap(); }
    if (docked === where) docked = null;
  }

  // "View well": to the popped-out window when there is one, docked otherwise
  function view(wa, stage, at) {
    if (wa == null) return;
    if (popAlive()) {
      shown = { wa: String(wa), stage: stage == null ? null : String(stage) };
      tell(wa, stage, at);
      return;
    }
    openDock(wa, stage, at);
  }
  // a cursor along the well shown, at `at` metres MD (null: none), wherever the section is
  function cursor(wa, at) {
    if (wa == null || String(wa) !== shown.wa) return;
    if (popAlive() && chan) chan.postMessage({ type: 'cursor', wa: String(wa), at: at == null ? null : +at, from: ME });
    if (docked === '3d') { const u = ug(); if (u && u.showing()) cursorIn(u.frame(), wa, at); }
    else if (docked === 'map' && !dock.hidden) cursorIn(mapFrame, wa, at);
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
    }
  });
  if (chan) {
    chan.onmessage = e => {
      const m = e.data || {};
      if (m.type === 'hello') {
        popHeard = true; if (m.wa) shown = { wa: String(m.wa), stage: shown.stage };
        chan.postMessage({ type: 'claim', from: ME, page: 'map' });   // e.g. a window reopened from a session
      }
      else if (m.type === 'bye') popHeard = false;
      else if (m.to === ME && m.type === 'dock') {
        chan.postMessage({ type: 'ack', id: m.id });
        popHeard = false; openDock(m.wa, m.stage); try { window.focus(); } catch (err) { /* the browser decides */ }
      }
    };
    // a section popped out before this page loaded: hear from it, and be its main window now
    chan.postMessage({ type: 'ping' });
    chan.postMessage({ type: 'claim', from: ME, page: 'map' });
  }

  // the map's dock comes back with the page (the 3D view keeps its own), and with a saved session
  const dockState = () => docked === 'map' && !dock.hidden && shown.wa ? JSON.stringify(shown) : null;
  if (window.StratumSession) StratumSession.provide(() => ({ [STATE_KEY]: dockState() }));
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

  // the wine rack window: whichever FracView main window spoke to it last is the one it drives
  const rackChan = 'BroadcastChannel' in self ? new BroadcastChannel('stratum-rack') : null;
  if (rackChan) {
    rackChan.onmessage = e => {
      const m = e.data || {};
      if (m.to && m.to !== ME) return;
      if (m.type === 'view') view(m.wa, m.stage, m.at);
      else if (m.type === 'cursor') cursor(m.wa, m.at);
      else if (m.type === 'hello') rackChan.postMessage({ type: 'main', from: ME });
    };
    rackChan.postMessage({ type: 'main', from: ME });
  }

  window.stratumSection = {
    view, follow, cursor, id: ME,
    closeMapDock: () => { if (!dock.hidden) closeDock('map'); },
    open: () => popAlive() || !!docked,
  };
})();
