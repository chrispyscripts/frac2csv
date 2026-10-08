// What FracView no longer serves to anyone, signed in or not (middleware.js).
//
// The site's root was the Frac2CSV extractor (public/index.html and its Python
// API). FracView is the product people sign in to now; the extractor is the
// Lab's tool and isn't offered here. Its files stay in the repository, unreached:
// the root and index.html go to the map, the extractor's endpoints answer 404.
const TO_MAP = new Set(['/', '/index.html']);
const EXTRACTOR = /^\/api\/(extract|bcer|bj1|frac_core|halliburton_ifs|raster_core|wellfiles|well-intervals|well-extract)(\.py)?\/?$/;

// -> 'map' (send to the map), 'gone' (404) or null (served as usual)
export function closed(pathname) {
  if (TO_MAP.has(pathname)) return 'map';
  if (EXTRACTOR.test(pathname)) return 'gone';
  return null;
}
