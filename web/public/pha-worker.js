// FracView — reads a dropped Photon export off the page's thread (drop.js
// starts it; pha.js does the reading). In: {file, n, name}. Out: progress
// messages {type:'progress', phase, f}, then {type:'done', result} or
// {type:'error', message}.
importScripts('pha.js');
self.onmessage = async e => {
  const { file, n, name } = e.data;
  try {
    self.postMessage({ type: 'progress', phase: 'Opening', f: 0 });
    const text = await file.text();
    const parsed = PHA.parse(text, f => self.postMessage({ type: 'progress', phase: 'Reading', f }));
    if (!parsed.wells.length) throw new Error('The export holds no wells.');
    self.postMessage({ type: 'progress', phase: 'Placing the wells', f: 1 });
    const result = PHA.convert(parsed, { n, name });
    if (!result.pads.length) throw new Error(`None of its ${parsed.wells.length} wells has a location and a depth to place it by.`);
    self.postMessage({ type: 'done', result });
  } catch (err) {
    self.postMessage({ type: 'error', message: String(err && err.message || err) });
  }
};
