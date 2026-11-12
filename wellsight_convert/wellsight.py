"""Read WellSight StripLog / HorizontalLog files (.sl6 .slg .hl6 .hlg) without WellSight software.

Standard library only (Python 3.9+). Decodes:
  - the AACS container (zlib blocks) and raw 6.5.0 files
  - the main well header (15 fields, 16 in 6.5) and the header text boxes (OPERATOR, GEOLOGIST, ...)
  - the log depth range (first scale record)
  - every data curve: display name, units, source mnemonic, step, samples
  - depth-tagged text (formation tops, geological descriptions, comments) with their column

Depth convention: sample i of every curve sits at top + i*step, where top/bottom come from the
log's first scale record. A curve stores span/step + 1 samples (older files) or span/step + 2
(newer files: one extra sample after the bottom). WellSight LogViewer draws sample i at
top + (i - 0.5)*step, i.e. at the middle of the interval that ends at the sample depth; this was
measured against the printed PDFs for both kinds of file (see verify_pdf.py).
"""
import math
import re
import struct
import zlib

NULL_BYTES = b'\x00\x00\x00\x00\x00\x00\x20\x38'
NULL_VALUE = struct.unpack('<d', NULL_BYTES)[0]          # 2.350988701644575e-38
LAS_NULL = -999.25

HEADER_FIELDS = [
    'well_name', 'location', 'licence', 'region', 'spud_date', 'completion_date',
    'surface_coordinates', 'bottom_hole_coordinates', 'ground_elevation', 'kb_elevation',
    'logged_interval_top', 'logged_interval_bottom', 'total_depth', 'drilling_fluid',
    'formation', 'well_id',
]

_PRINTABLE = re.compile(rb'[\t\n\r -~\x80-\xff]*')
_CURVE_RE = re.compile(rb'[\x00\x01](.{8})' + re.escape(NULL_BYTES) + rb'(.{4})', re.S)
_DISPLAY_MARK = b'\x10\x00\x00\x00\x64\x00\x00\x00'
_BOX_RE = re.compile(rb'\x01([\x00-\xff]{32})\x00\x00\x00\x00([\x00-\x28])\x00\x00\x00')
_ANN_RE = re.compile(rb'\x02\x00\x00\x00([\x00-\xff]{32})([\x00-\xff]{4})\x00\x00\x00\x00([\x00-\xff]{4})')
_CUSTOM_HEADER = b'\x0d\x00\x00\x00Custom Header'
CUSTOM_LABELS = {
    'WELL NAME': 'well_name', 'UWI': 'well_id', 'U.W.I.': 'well_id', 'LICENCE NO.': 'licence', 'LICENSE NO.': 'licence',
    'LICENCE': 'licence', 'LICENSE': 'licence', 'LICENCE NUMBER': 'licence', 'LICENSE NUMBER': 'licence',
    'SURFACE LOCATION': 'location', 'LOCATION': 'location', 'SURFACE COORDINATES': 'surface_coordinates',
    'BOTTOM HOLE COORDINATES': 'bottom_hole_coordinates', 'GROUND ELEVATION': 'ground_elevation',
    'KB ELEVATION': 'kb_elevation', 'K.B. ELEVATION': 'kb_elevation', 'SPUD DATE': 'spud_date',
    'REGION': 'region', 'AREA': 'region', 'FIELD': 'region', 'TOTAL DEPTH': 'total_depth',
    'DRILLING FLUID': 'drilling_fluid', 'MUD TYPE': 'drilling_fluid', 'FORMATION': 'formation',
}
_COL_RE = re.compile(rb'([\x00-\x0f])\x00\x00\x00([\x00-\xff])\x11\x00\x00([\x01-\x3c])\x00\x00\x00')
_SCALE_RE = re.compile(rb'[\x03-\x3c]\x00\x00\x001:\d')


class NotReadable(Exception):
    """The file is not a readable WellSight log (empty, all zeros, a PDF, damaged...)."""


def _u32(b, p):
    return struct.unpack_from('<I', b, p)[0]


def _text(raw):
    return raw.decode('cp1252', errors='replace')


# ---------------------------------------------------------------- container

def inflate(raw, problems=None):
    """Return (body, container) for the bytes of a native file. Chunk checksum mismatches go into problems."""
    if not raw:
        raise NotReadable('empty file')
    if raw[:4] == b'AACS':
        nblocks = _u32(raw, 0x0C)
        off, parts = 0x80, []
        for i in range(nblocks):
            if off + 16 > len(raw):
                raise NotReadable('AACS block %d header past end of file' % i)
            clen, ulen, _chk, nxt = struct.unpack_from('<IIII', raw, off)
            try:
                part = zlib.decompress(raw[off + 16:off + 16 + clen])
            except zlib.error as ex:
                raise NotReadable('AACS block %d: zlib %s' % (i, ex))
            if problems is not None and (zlib.crc32(part, 0xFFFFFFFF) ^ 0xFFFFFFFF) != _chk:
                problems.append('AACS block %d checksum mismatch' % i)
            if len(part) != ulen:
                raise NotReadable('AACS block %d inflated to %d bytes, header says %d' % (i, len(part), ulen))
            parts.append(part)
            off = nxt
        return b''.join(parts), 'AACS'
    if raw[:9] == b'STRIP.LOG' or raw[:14] == b'HORIZONTAL.LOG':
        return raw, 'raw'
    if raw[:5] == b'%PDF-':
        raise NotReadable('file is a PDF, not a log')
    if raw.count(0) == len(raw):
        raise NotReadable('all zero bytes (data lost)')
    raise NotReadable('unknown format, starts %s' % raw[:8].hex())


def signature(body):
    sig = _text(body[:32].split(b'\x00')[0]).strip()
    m = re.match(r'(STRIP\.LOG|HORIZONTAL\.LOG)\s+(.*)', sig)
    if not m:
        raise NotReadable('no STRIP.LOG / HORIZONTAL.LOG signature')
    return m.group(1), m.group(2)


# ---------------------------------------------------------------- strings

def read_str(b, p, maxlen=20000):
    """u32-length-prefixed string at p -> (text, end) or None."""
    if p < 0 or p + 4 > len(b):
        return None
    n = _u32(b, p)
    if n > maxlen or p + 4 + n > len(b):
        return None
    s = b[p + 4:p + 4 + n]
    if not _PRINTABLE.fullmatch(s):
        return None
    return _text(s), p + 4 + n


def str_ending_at(b, end, maxlen=120):
    """u32-length-prefixed string whose last byte is end-1 -> (text, start_of_prefix) or None."""
    for n in range(0, maxlen + 1):
        p = end - n - 4
        if p < 0:
            break
        if _u32(b, p) == n and _PRINTABLE.fullmatch(b[p + 4:end]):
            return _text(b[p + 4:end]), p
    return None


# ---------------------------------------------------------------- header boxes

def header_boxes(b):
    """All header text boxes: title, field list, free text. The main header has 15/16 fields."""
    boxes = []
    for m in _BOX_RE.finditer(b):
        dbl = struct.unpack('<4d', m.group(1))
        if not all(0.01 <= d <= 1000 for d in dbl):
            continue
        title = str_ending_at(b, m.start(), 200)
        if not title or not title[0].strip():
            continue
        count = m.group(2)[0]
        p, fields = m.end(), []
        for _ in range(count + 1):          # count fields + one free-text string
            r = read_str(b, p)
            if r is None:
                break
            fields.append(r[0])
            p = r[1]
        if len(fields) != count + 1:
            continue
        fields = [f.replace('\r\n', '\n').replace('\r', '\n') for f in fields]
        boxes.append({'offset': m.start(), 'title': title[0].strip(), 'kind': _u32(b, title[1] - 4) if title[1] >= 4 else None,
                      'fields': fields[:count], 'text': fields[count]})
    return boxes


def main_header(boxes):
    for bx in boxes:
        if len(bx['fields']) in (15, 16):
            vals = list(bx['fields'])
            hdr = {k: (vals[i].strip() if i < len(vals) else '') for i, k in enumerate(HEADER_FIELDS)}
            if len(vals) == 16:
                hdr['well_id_label'] = bx['text'].strip()
            return bx, hdr
    return None, {}


# ---------------------------------------------------------------- depth range

def depth_range(b):
    """First scale record: label + 8 doubles; doubles 6 and 7 are the log top and bottom."""
    for m in _SCALE_RE.finditer(b):
        r = read_str(b, m.start(), 60)
        if not r or not r[0].startswith('1:') or r[1] + 64 > len(b):
            continue
        d = struct.unpack_from('<8d', b, r[1])
        top, bottom = d[6], d[7]
        if all(math.isfinite(x) for x in (top, bottom)) and bottom > top and -1000 <= top <= 10000:
            return r[0], top, bottom
    return None, None, None


_AX_NUM = r'(\d{3,4}(?:\.\d+)?)'
_AX_MD = re.compile(_AX_NUM + r'\s*m?\s*(?:MD|M\.D\.)\b', re.I)
_AX_TVD = re.compile(_AX_NUM + r'\s*m?\s*(?:TVD|T\.V\.D\.)\b', re.I)


def axis_votes(annotations):
    """Is the depth axis MD or TVD? Depth-tagged text that states both an MD and a TVD value (formation tops,
    casing points) sits on the log at whichever one the axis uses. Returns (md_votes, tvd_votes)."""
    md = tvd = 0
    for a in annotations:
        mds, tvds = _AX_MD.findall(a['text']), _AX_TVD.findall(a['text'])
        if not mds or not tvds:
            continue
        m, v = float(mds[0]), float(tvds[0])
        if abs(m - v) < 3:
            continue                          # vertical hole: both the same, no evidence
        dm, dv = abs(a['depth'] - m), abs(a['depth'] - v)
        if min(dm, dv) > 15 or abs(dm - dv) < 3:
            continue                          # text box not clearly nearer one of the two values
        if dm < dv:
            md += 1
        else:
            tvd += 1
    return md, tvd


def decide_axis(votes, file_name):
    md, tvd = votes
    if tvd > md:
        return 'TVD', 'formation tops sit at their TVD values (%d of %d)' % (tvd, md + tvd)
    if md > tvd:
        return 'MD', 'formation tops sit at their MD values (%d of %d)' % (md, md + tvd)
    if re.search('tvd', file_name or '', re.I):
        return 'TVD', 'file name says TVD (no tops with both MD and TVD)'
    return 'MD', 'default (no evidence either way)'


# ---------------------------------------------------------------- curves

def _clean(v):
    if v == NULL_VALUE or v != v or abs(v) > 1e30 or abs(v - LAS_NULL) < 1e-3 or (v != 0 and abs(v) < 1e-30):
        return None
    return v


_TRACK_RE = re.compile(rb'\x02\x00\x00\x00([\x00-\xff]{2})\x00\x00\x0b\x00\x00\x00Graph Paper')


def tracks(b):
    """Track (column) starts: every track has a 'Graph Paper' record (track id 10000+); its title ends 19 bytes before."""
    out = []
    for m in _TRACK_RE.finditer(b):
        r = str_ending_at(b, m.start() - 19, 80)
        out.append((m.start(), struct.unpack('<H', m.group(1))[0], r[0].strip() if r else ''))
    return out


def curves(b, top, bottom):
    out = []
    trk = tracks(b)
    span = (bottom - top) if top is not None else None
    for m in _CURVE_RE.finditer(b):
        step = struct.unpack('<d', m.group(1))[0]
        n = struct.unpack('<I', m.group(2))[0]
        if not (0.001 <= step <= 50) or abs(step * 10000 - round(step * 10000)) > 1e-6:
            continue
        if not (2 <= n <= 10_000_000) or m.end() + 8 * n > len(b):
            continue
        s = m.start()
        vals = [_clean(v) for v in struct.unpack_from('<%dd' % n, b, m.end())]
        nonnull = [v for v in vals if v is not None]
        # names
        mn = str_ending_at(b, s, 40) or str_ending_at(b, s - 2, 40)
        mnemonic = mn[0] if mn and mn[0].strip() else None
        name = units = None
        mk = b.rfind(_DISPLAY_MARK, max(0, s - 260), s)
        if mk >= 0:
            u = str_ending_at(b, mk - 8, 60)
            if u:
                units = u[0].strip()
                nm = str_ending_at(b, u[1], 120)
                if nm:
                    name = nm[0].strip()
        if not name and not mnemonic:
            continue  # bytes that only look like a curve record (no name, no mnemonic)
        # registration
        pad = None
        if span is not None:
            k = (n - 1) - math.floor(span / step + 1e-6)   # n = floor(span/step) + 1, or + 2 in newer files
            if k in (0, 1):
                pad = k
        out.append({
            'offset': s, 'name': name, 'units': units, 'source_mnemonic': mnemonic,
            'track': next((t[2] for t in reversed(trk) if t[0] < s), None),
            'step': round(step, 6), 'samples': n, 'pad': pad, 'values': vals,
            'nonnull': len(nonnull),
            'min': min(nonnull) if nonnull else None, 'max': max(nonnull) if nonnull else None,
            'first_depth': top if pad is not None else None,
        })
    return out


# ---------------------------------------------------------------- columns + depth-tagged text

def columns(b):
    cols = []
    for m in _COL_RE.finditer(b):
        r = read_str(b, m.end() - 4, 60)
        if r and r[0].strip() and re.search(r'[A-Za-z]', r[0]):
            cols.append((m.start(), r[0].strip()))
    return cols


def text_records(b):
    """Every positioned text item: [u32 2][f64 x][f64 y][f64 w][f64 h][u32 id][u32 0][u32 len][text]."""
    out = []
    for m in _ANN_RE.finditer(b):
        x, y, w, h = struct.unpack('<4d', m.group(1))
        if not all(math.isfinite(v) for v in (x, y, w, h)):
            continue
        if not (0 < w < 100) or not (0 < h < 1000) or not (-1 <= x <= 100):
            continue
        r = read_str(b, m.end() - 4, 20000)
        if not r or not r[0].strip():
            continue
        out.append((m.start(), x, y, w, h, r[0].replace('\r\n', '\n').replace('\r', '\n').strip()))
    return out


def annotations(recs, top, bottom, cols, header_start):
    out = []
    if top is None:
        return out
    lo, hi = top - 50, bottom + 50
    ci = 0
    for off, x, depth, w, h, text in recs:
        if not (lo <= depth <= hi) or (header_start is not None and off > header_start and depth < 2):
            continue
        while ci + 1 < len(cols) and cols[ci + 1][0] < off:
            ci += 1
        col = cols[ci][1] if cols and cols[ci][0] < off else None
        out.append({'offset': off, 'column': col, 'depth': round(depth, 3), 'x': round(x, 3), 'text': text})
    return out


def custom_header(b, recs):
    """Free-form header page made of positioned text: returns (lines, label->value, header-field dict)."""
    start = b.find(_CUSTOM_HEADER)
    if start < 0:
        return None, [], {}, {}
    items = sorted([r for r in recs if r[0] > start and 0 <= r[2] < 2], key=lambda r: (r[2], r[1]))
    if not items:
        return start, [], {}, {}
    rows, cur = [], [items[0]]
    for it in items[1:]:
        if abs(it[2] - cur[0][2]) < 0.002:
            cur.append(it)
        else:
            rows.append(cur)
            cur = [it]
    rows.append(cur)
    lines, pairs = [], {}
    # an item may hold a label, a value, or "LABEL: value" -- and several of those separated by wide gaps
    label_re = re.compile(r"^([A-Za-z][A-Za-z0-9 ./&()#'-]{0,60}?)\s*(:|\bNo\.|\bNo,|\bNO\.|\bNO,)\s*(.*)$", re.S)
    for row in rows:
        row = sorted(row, key=lambda r: r[1])
        texts = [r[5] for r in row]
        lines.append('    '.join(t.replace('\n', ' | ') for t in texts))
        label = None
        for t in texts:
            for part in re.split(r'\s{3,}', t.replace('\n', ' | ')):
                part = part.strip()
                if not part:
                    continue
                m = label_re.match(part)
                lab = None
                if m:
                    cand = (m.group(1) + ('' if m.group(2) == ':' else ' ' + m.group(2).rstrip(',').rstrip('.') + '.')).strip()
                    words = m.group(1).split()
                    if len(words) <= 7 and (m.group(1).upper() == m.group(1) or _label_key(cand) or cand.upper() in CUSTOM_LABELS):
                        lab = cand
                if lab:
                    label = lab
                    pairs.setdefault(label, '')
                    if m.group(3).strip():
                        pairs[label] = (pairs[label] + ' ' + m.group(3).strip()).strip()
                elif label is not None:
                    pairs[label] = (pairs[label] + ' ' + part).strip()
    fields = {}
    for k, v in pairs.items():
        key = CUSTOM_LABELS.get(k.upper().strip()) or _label_key(k)
        if key and v and key not in fields:
            fields[key] = v
    return start, lines, pairs, fields


_KEYWORDS = [  # first match wins; checked against the upper-cased label
    ('LICEN', 'licence'), ('UWI', 'well_id'), ('U.W.I', 'well_id'), ('WELL NAME', 'well_name'),
    ('OPERATOR', 'operator'), ('SPUD', 'spud_date'), ('GROUND', 'ground_elevation'), ('K.B', 'kb_elevation'),
    ('KB ', 'kb_elevation'), ('SURFACE LOC', 'location'), ('SURFACE COORD', 'surface_coordinates'),
    ('BOTTOM HOLE', 'bottom_hole_coordinates'), ('FIELD', 'region'), ('AREA', 'region'), ('REGION', 'region'),
    ('FLUID', 'drilling_fluid'), ('MUD TYPE', 'drilling_fluid'),
]


def _label_key(label):
    u = label.upper() + ' '
    for kw, key in _KEYWORDS:
        if kw in u:
            return key
    return None


# ---------------------------------------------------------------- symbol library + lithology

ROCK_NAMES = {
    'ANHY': 'Anhydrite', 'BENT': 'Bentonite', 'BREC': 'Breccia', 'CHT': 'Chert', 'CLYST': 'Claystone', 'COAL': 'Coal',
    'CONGL': 'Conglomerate', 'DOL': 'Dolomite', 'GYP': 'Gypsum', 'IGNE': 'Igneous', 'LMST': 'Limestone',
    'META': 'Metamorphic', 'MRLST': 'Marlstone', 'SALT': 'Salt', 'SHALE': 'Shale', 'SHCOL': 'Shale (coloured)',
    'SHGY': 'Shale (grey)', 'SLTST': 'Siltstone', 'SS': 'Sandstone', 'TILL': 'Till', 'BLANK': 'Blank (no sample)',
    'REDSH': 'Shale (red)', 'GYSH': 'Shale (grey)', 'CEMENT': 'Cement', 'DKCHT': 'Chert (dark)',
}
_CAT_RE = re.compile(rb'([\x00-\xff]{4})([\x03-\x20])\x00\x00\x00(?=[A-Za-z])')
_ARR_TAIL = re.compile(rb'([\x00-\xff]{4})([\x00-\xff]{4})([\x00-\xff]{8})\x00\x00\x00\x00([\x00-\xff]{4})')


def _bmp_len(b, p):
    """Stored length of a bitmap at p: file header + DIB header + palette + pixels, from its geometry.
    Some palette bitmaps declare a wrong bfSize/bfOffBits, so bfSize is used only if the geometry is unusable."""
    try:
        bi_size, w, h = struct.unpack_from('<Iii', b, p + 14)
        bpp, comp = struct.unpack_from('<HI', b, p + 28)
        clr = struct.unpack_from('<I', b, p + 46)[0]
        if bi_size in (40, 108, 124) and 0 < w < 10000 and 0 < abs(h) < 10000 and bpp in (1, 4, 8, 16, 24, 32) and comp in (0, 3):
            pal = clr if clr else (1 << bpp if bpp <= 8 else 0)
            return 14 + bi_size + 4 * pal + (12 if comp == 3 and bi_size == 40 else 0) + ((w * bpp + 31) // 32) * 4 * abs(h)
    except struct.error:
        pass
    return _u32(b, p + 2)


def symbol_library(b):
    """Symbol categories stored in the file: {category_name: (category_id, {symbol_id: (code, label)})}."""
    cats = {}
    for m in _CAT_RE.finditer(b):
        cid = struct.unpack('<I', m.group(1))[0]
        L = m.group(2)[0]
        name = b[m.end():m.end() + L]           # take the name by its stored length (a count of 32 is a space byte)
        if not (1000 <= cid <= 20000) or not re.fullmatch(rb'[A-Za-z][A-Za-z /%().-]*', name) or m.end() + L + 4 > len(b):
            continue
        cnt = _u32(b, m.end() + L)
        if not (1 <= cnt <= 400):
            continue
        p, syms, ok = m.end() + L + 4, {}, True
        for _ in range(cnt):
            r = read_str(b, p, 60)
            if not r or p + 4 > len(b):
                ok = False
                break
            code, p = r
            sid = _u32(b, r[1])
            p = r[1] + 5                       # id + one flag byte
            if b[p:p + 2] == b'BM':
                p += _bmp_len(b, p)            # pattern bitmap (present even when the flag is 0)
            p += 1
            r = read_str(b, p, 60)
            if not r:
                ok = False
                break
            syms[sid] = (code.strip(), r[0].strip())
            p = r[1]
        if ok and syms:
            cats.setdefault(_text(name), (cid, syms))
    return cats


def track_width(b, rec):
    """Printed width (inches) of the track whose 'Graph Paper' record starts at rec: the f64 right after its title."""
    if rec < 19:
        return None
    w = struct.unpack_from('<d', b, rec - 19)[0]
    return round(w, 4) if math.isfinite(w) and 0 < w < 30 else None


def symbol_columns(b, cats):
    """Sampled symbol columns: [cat id][cat id 2][f64 step][u32 0][u32 n] then n records of [u32 k][k x u32 symbol id].
    k = 1 for a lithology column, 10 for % lithology (10 % per cell), many for a horizontal-log cross-section.
    A column that follows its own track record closely (% lithology columns do, about 90 bytes on) also gets that
    track's title and printed width; for other columns the nearest track record belongs to something else."""
    out = []
    trk = tracks(b)
    by_id = {cid: (name, syms) for name, (cid, syms) in cats.items()}
    starts = []
    for cid in by_id:
        key = struct.pack('<I', cid)
        p = b.find(key)
        while p >= 0:
            if p + 24 <= len(b) and b[p + 16:p + 20] == b'\x00\x00\x00\x00':
                starts.append(p)
            p = b.find(key, p + 1)
    for p in sorted(starts):
        m = _ARR_TAIL.match(b, p)
        if not m:
            continue
        cid = struct.unpack('<I', m.group(1))[0]
        cid2 = struct.unpack('<I', m.group(2))[0]
        step = struct.unpack('<d', m.group(3))[0]
        n = struct.unpack('<I', m.group(4))[0]
        if not (cid <= cid2 < cid + 400 or cid2 in by_id[cid][1]) or not (0.01 <= step <= 20) or not (2 <= n <= 5_000_000):
            continue
        s = m.end()
        if s + 4 > len(b):
            continue
        k = _u32(b, s)
        if not (1 <= k <= 1000) or s + n * (4 + 4 * k) > len(b):
            continue
        rl = 4 + 4 * k
        if any(_u32(b, s + j * rl) != k for j in range(0, n, max(1, n // 64))):
            continue
        title = str_ending_at(b, m.start() - 14, 60)
        kind = _u32(b, title[1] - 4) if title and title[1] >= 4 else None
        cells = [struct.unpack_from('<%dI' % k, b, s + j * rl + 4) for j in range(n)]
        name, syms = by_id[cid]
        tr = None
        for t in trk:
            if t[0] < m.start():
                tr = t
            else:
                break
        if tr and m.start() - tr[0] > 200:
            tr = None
        out.append({'offset': m.start(), 'category': name, 'title': title[0].strip() if title else name, 'kind': kind,
                    'step': round(step, 6), 'samples': n, 'cells': k, 'data': cells, 'symbols': syms,
                    'track': tr[2] if tr else None, 'track_width_in': track_width(b, tr[0]) if tr else None})
    return out


def survey(b):
    """Directional survey from a 'TVD Curve' record: <title> 01 01000000 <u32 count>, then per station
    [u32 5][5 or 6 x f64: ?, MD, ?, ?, TVD(, MD)][u32 6][6 x f64: inc, azi, ...]. Returns the longest list found."""
    best = []
    for m in re.finditer(rb'\x09\x00\x00\x00TVD Curve[\x00\x01]\x01\x00\x00\x00', b):
        p = None
        for extra in (0, 1):  # newer files have one more flag byte before the count
            q = m.end() + extra
            if q + 8 <= len(b) and 2 <= _u32(b, q) <= 20000 and _u32(b, q + 4) == 5:
                p, cnt = q + 4, _u32(b, q)
                break
        if p is None:
            continue
        st = []
        for _ in range(cnt):
            if p + 104 > len(b) or _u32(b, p) != 5:
                break
            nd = 5 if _u32(b, p + 44) == 6 else 6 if _u32(b, p + 52) == 6 else None
            if nd is None:
                break
            md, tvd = struct.unpack_from('<d', b, p + 12)[0], struct.unpack_from('<d', b, p + 36)[0]
            q = p + 4 + 8 * nd + 4
            inc, azi = (_clean(v) for v in struct.unpack_from('<dd', b, q))
            p = q + 48
            if not (math.isfinite(md) and math.isfinite(tvd)) or md <= 0 or tvd <= 0 or tvd > md + 0.5:
                continue
            st.append({'md': round(md, 3), 'tvd': round(tvd, 3),
                       'inc': round(inc, 3) if inc is not None and 0 <= inc <= 180 else None,
                       'azi': round(azi, 3) if azi is not None and 0 <= azi <= 360.01 else None})
        st = sorted({s['md']: s for s in st}.values(), key=lambda s: s['md'])
        if len(st) > len(best):
            best = st
    return best if len(best) >= 2 else []


def xsection_window(b):
    """Cross-section TVD window control points [(md, tvd_top, tvd_bottom)] from the 'Well Bore Cross Section' header."""
    i = b.find(b'Well Bore Cross Section')
    if i < 0:
        return []
    p = i + len('Well Bore Cross Section') + 15
    cnt = _u32(b, p)
    if not (1 <= cnt <= 200):
        return []
    p += 4
    pts = []
    for _ in range(cnt):
        md = struct.unpack_from('<d', b, p)[0]
        top = struct.unpack_from('<d', b, p + 12)[0]
        bot = struct.unpack_from('<d', b, p + 24)[0]
        if not all(math.isfinite(v) for v in (md, top, bot)) or not (0 < md < 10000 and 0 < top < bot < 10000):
            return []
        pts.append((md, top, bot))
        p += 32
    return pts


def _interp(x, xs, ys):
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    lo, hi = 0, len(xs) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if xs[mid] <= x:
            lo = mid
        else:
            hi = mid
    t = (x - xs[lo]) / (xs[hi] - xs[lo]) if xs[hi] != xs[lo] else 0
    return ys[lo] + t * (ys[hi] - ys[lo])


_SURV_TEXT = re.compile(r'(\d{3,4}\.\d+)\s*/\s*(\d{1,3}\.\d+)\s*/\s*(\d{1,3}\.\d+)\s*/\s*(\d{3,4}\.\d+)')
_MDTVD_TEXT = re.compile(r'(\d{3,4}(?:\.\d+)?)\s*m?\s*MD\b[^0-9]{0,40}?(\d{3,4}(?:\.\d+)?)\s*m?\s*TVD\b', re.I | re.S)


def survey_from_text(annotations):
    """Survey tables typed into the log as 'MD / Inc / Azi / TVD' lines (e.g. in Eng. Data). Needs >= 10 stations."""
    st = {}
    for a in annotations or []:
        for m in _SURV_TEXT.finditer(a['text']):
            md, inc, azi, tvd = (float(m.group(k)) for k in (1, 2, 3, 4))
            if 0 < tvd <= md + 0.5 and 0 <= inc <= 180 and 0 <= azi <= 360:
                st[round(md, 2)] = {'md': round(md, 2), 'tvd': round(tvd, 2), 'inc': inc, 'azi': azi}
    out = [st[k] for k in sorted(st)]
    return out if len(out) >= 10 else []


def md_tvd_points_from_text(annotations):
    """MD/TVD pairs stated in tops and comments ('1793.6 m MD, 1793.5 m TVD'). Too sparse to place the bit
    in the cross-section (tested: no better than guessing), so they are reported, not used for lithology."""
    pts = {}
    for a in annotations or []:
        for m in _MDTVD_TEXT.finditer(a['text']):
            md, tvd = float(m.group(1)), float(m.group(2))
            if 0 < tvd <= md + 0.5:
                pts.setdefault(round(md, 2), {'md': round(md, 2), 'tvd': round(tvd, 2), 'text': a['text'][:120]})
    return [pts[k] for k in sorted(pts)]


def lithology(b, top, bottom, app, annotations=None):
    """Decode lithology: per-sample rock code along the hole, % lithology, survey and cross-section info."""
    cats = symbol_library(b)
    cols = symbol_columns(b, cats)
    lith_cat = cats.get('Lithology', (1200, {}))
    out = {'library': {name: {str(sid): {'code': c, 'label': lab} for sid, (c, lab) in syms.items()}
                       for name, (cid, syms) in cats.items()},
           'columns': [], 'survey': survey(b), 'survey_source': 'stored survey (TVD Curve)', 'xsection_window': [],
           'along_hole': None, 'percent': None}
    if not out['survey'] and app == 'HORIZONTAL.LOG':
        out['survey'] = survey_from_text(annotations)
        out['survey_source'] = 'survey stations typed into the log text' if out['survey'] else None
        if not out['survey']:
            out['md_tvd_points_from_text'] = md_tvd_points_from_text(annotations)
    span = (bottom - top) if top is not None else None
    for c in cols:
        used = sorted({x for row in c['data'] for x in row if x})
        reg = None
        if span is not None:
            k = (c['samples'] - 1) - math.floor(span / c['step'] + 1e-6)
            reg = k in (0, 1)
        out['columns'].append({'title': c['title'], 'category': c['category'], 'cells': c['cells'], 'step_m': c['step'],
                               'samples': c['samples'], 'depth_registered': reg, 'symbols_used': used,
                               'non_empty': sum(1 for row in c['data'] if any(row)),
                               'track': c['track'], 'track_width_in': c['track_width_in']})
        c['registered'] = reg
    lith_cols = [c for c in cols if c['category'] == 'Lithology' and c['registered'] and any(any(r) for r in c['data'])]
    # main rock per sample
    main = None
    if app == 'STRIP.LOG' or not any(c['cells'] > 10 for c in lith_cols):
        one = [c for c in lith_cols if c['cells'] == 1]
        if one:
            main = (one[0]['step'], [row[0] or None for row in one[0]['data']], 'lithology column')
    if main is None and app == 'HORIZONTAL.LOG':
        grid = [c for c in lith_cols if c['cells'] > 10]
        win = xsection_window(b)
        sv = out['survey']
        out['xsection_window'] = [{'md': m, 'tvd_top': t, 'tvd_bottom': u} for m, t, u in win]
        if grid and win and sv:
            g = grid[0]
            mds, tops, bots = [w[0] for w in win], [w[1] for w in win], [w[2] for w in win]
            smd, stvd = [s['md'] for s in sv], [s['tvd'] for s in sv]
            codes = []
            for i, row in enumerate(g['data']):
                md = top + i * g['step']
                if md < smd[0] - 1 or md > smd[-1] + 1 or not any(row):
                    codes.append(None)
                    continue
                tvd = _interp(md, smd, stvd)
                w = max((k for k in range(len(mds)) if mds[k] <= md), default=0)   # window holds until the next control point
                wt, wb = tops[w], bots[w]
                j = int((tvd - wt) / (wb - wt) * g['cells'])
                codes.append(row[j] or None if 0 <= j < g['cells'] else None)
            if any(codes):
                main = (g['step'], codes, 'cross-section cell crossed by the well path' +
                        ('' if out['survey_source'].startswith('stored') else ' (path from survey typed in the log)'))
    if main:
        step, codes, source = main
        out['along_hole'] = {'step_m': step, 'source': source, 'codes': codes}
    # A 10-cell column in a narrow track (under 0.25 in) is a drawn bar, not a rock mix: the printouts show a solid black
    # strip, usually in a track titled "Slide / Rotate", starting at the kick-off point. It goes with the other columns.
    for c in lith_cols:
        c['bar'] = c['cells'] == 10 and c['track_width_in'] is not None and c['track_width_in'] < 0.25
    pct = [c for c in lith_cols if c['cells'] == 10 and c['title'].startswith('%') and not c['bar']]
    if pct:
        c = pct[0]
        rocks = sorted({x for row in c['data'] for x in row if x})
    if pct and any(lith_cat[1].get(r, ('',))[0] != 'BLANK' for r in rocks):    # a column of only 'no sample' says nothing
        out['percent'] = {'step_m': c['step'], 'rocks': rocks,
                          'values': [[10 * row.count(r) if any(row) else None for r in rocks] for row in c['data']]}
    # horizontal-log cross-section grid, run-length encoded per depth sample: [[cells, symbol id], ...] top to bottom
    grid = [c for c in lith_cols if c['cells'] > 10]
    if grid and app == 'HORIZONTAL.LOG':
        g = grid[0]
        rows = []
        for row in g['data']:
            rle, k = [], 0
            while k < len(row):
                j = k
                while j + 1 < len(row) and row[j + 1] == row[k]:
                    j += 1
                rle.append([j - k + 1, row[k]])
                k = j + 1
            r = rle if any(row) else None
            if rows and rows[-1][1] == r:
                rows[-1][0] += 1
            else:
                rows.append([1, r])
        out['xsection'] = {'cells': g['cells'], 'step_m': g['step'], 'first_md_m': top,
                           'note': ('rows are [repeat, cells]: each block covers "repeat" consecutive depth samples starting '
                                    'at MD first_md_m and stepping step_m; cells are [count, symbol id] runs from the top to '
                                    'the bottom of the TVD window in force at that MD (null = empty)'),
                           'rows': rows}
    # other symbol columns (core/DST intervals, oil shows, porosity type, ...): runs of identical symbol sets
    others = []
    for c in cols:
        if (c['category'] == 'Lithology' and not c.get('bar')) or not c['registered'] or not any(any(r) for r in c['data']):
            continue
        runs, i = [], 0
        while i < len(c['data']):
            key = tuple(sorted({x for x in c['data'][i] if x}))
            j = i
            while j + 1 < len(c['data']) and tuple(sorted({x for x in c['data'][j + 1] if x})) == key:
                j += 1
            if key:
                runs.append({'top_m': round(top + i * c['step'], 3), 'base_m': round(top + (j + 1) * c['step'], 3),
                             'symbols': [c['symbols'].get(x, (str(x), ''))[0] for x in key]})
            i = j + 1
        col = {'column': c['title'], 'category': c['category'], 'intervals': runs}
        if c.get('bar'):
            col['column'] = c['track'] or c['title']
            col['note'] = ('%g in wide track drawn with lithology fill; the printout shows a solid bar (in other logs this '
                           'track is titled "Slide / Rotate"), not a rock mix, so it is not written as %% lithology'
                           % c['track_width_in'])
        others.append(col)
    out['symbol_columns'] = others
    out['_lith_symbols'] = lith_cat[1]
    return out


def accessories(b, cats, top, bottom):
    """Symbols placed at a depth (fossils, minerals, stringers, texture, porosity type, sorting, rounding, oil shows...).
    Per category: <u32 category id><u32 n>, then n x 40 bytes <u32 1><f64 size><f64 depth><f64 0><f64 0><u32 symbol id>.
    The depth is the top of the symbol as printed (checked against printouts)."""
    out = []
    if top is None:
        return out
    for name, (cid, syms) in cats.items():
        key = struct.pack('<I', cid)
        p = b.find(key)
        while p >= 0:
            n = _u32(b, p + 4) if p + 8 <= len(b) else 0
            if 1 <= n <= 20000 and p + 8 + n * 40 <= len(b) and _u32(b, p + 8) == 1:
                recs = []
                for k in range(n):
                    one, size, depth, _z1, _z2, sid = struct.unpack_from('<IddddI', b, p + 8 + k * 40)
                    if one != 1 or not (top - 50 <= depth <= bottom + 50) or sid not in syms:
                        recs = None
                        break
                    recs.append({'category': name, 'depth_m': round(depth, 3), 'symbol_id': sid, 'code': syms[sid][0],
                                 'size': round(size, 3)})
                if recs:
                    out.extend(recs)
                    p = b.find(key, p + 8 + n * 40)
                    continue
            p = b.find(key, p + 1)
    out.sort(key=lambda r: (r['depth_m'], r['category']))
    return out


def lith_intervals(top, step, codes, symbols):
    """Collapse per-sample codes into intervals; sample i stands for depth top + i*step."""
    out, i, n = [], 0, len(codes)
    while i < n:
        c = codes[i]
        j = i
        while j + 1 < n and codes[j + 1] == c:
            j += 1
        if c:
            code, label = symbols.get(c, (str(c), ''))
            out.append({'top_m': round(top + i * step, 3), 'base_m': round(top + (j + 1) * step, 3), 'symbol_id': c,
                        'code': code, 'name': ROCK_NAMES.get(code.upper(), code)})
        i = j + 1
    return out


# ---------------------------------------------------------------- embedded pictures

def bitmaps(b, min_pixels=150_000):
    """Large embedded Windows bitmaps (e.g. a header page pasted in as a picture) -> list of BMP bytes."""
    out, seen, p = [], set(), 0
    while True:
        p = b.find(b'BM', p)
        if p < 0 or p + 54 > len(b):
            break
        size, = struct.unpack_from('<I', b, p + 2)
        dib, w, h = struct.unpack_from('<Iii', b, p + 14)
        planes, bpp = struct.unpack_from('<HH', b, p + 26)
        ok = dib == 40 and planes == 1 and bpp in (8, 24, 32) and 0 < w < 20000 and 0 < abs(h) < 20000 \
            and w * abs(h) >= min_pixels and 54 < size <= len(b) - p
        if ok:
            data = b[p:p + size]
            key = hash(data)
            if key not in seen:
                seen.add(key)
                out.append(data)
            p += size
        else:
            p += 2
    return out


def bmp_to_png(bmp):
    """Convert an uncompressed 8/24/32-bit BMP to PNG bytes (standard library only)."""
    off, = struct.unpack_from('<I', bmp, 10)
    w, h = struct.unpack_from('<ii', bmp, 18)
    bpp, comp = struct.unpack_from('<HI', bmp, 28)
    if comp not in (0, 3):
        raise ValueError('compressed BMP')
    rowlen = ((w * bpp + 31) // 32) * 4
    pal = None
    if bpp == 8:
        ncol = struct.unpack_from('<I', bmp, 46)[0] or 256
        pal = [bmp[54 + 4 * i:54 + 4 * i + 3][::-1] for i in range(ncol)]
    rows = []
    for y in range(abs(h)):
        sy = abs(h) - 1 - y if h > 0 else y
        r = bmp[off + sy * rowlen: off + sy * rowlen + rowlen]
        if bpp == 24:
            px = bytearray(w * 3)
            px[0::3], px[1::3], px[2::3] = r[2:w * 3:3], r[1:w * 3:3], r[0:w * 3:3]
        elif bpp == 32:
            px = bytearray(w * 3)
            px[0::3], px[1::3], px[2::3] = r[2:w * 4:4], r[1:w * 4:4], r[0:w * 4:4]
        else:
            px = b''.join(pal[i] if i < len(pal) else b'\x00\x00\x00' for i in r[:w])
        rows.append(b'\x00' + bytes(px))

    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, abs(h), 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b''.join(rows), 6)) + chunk(b'IEND', b''))


# ---------------------------------------------------------------- whole file

def read_log(raw):
    integrity = []
    body, container = inflate(raw, integrity)
    app, version = signature(body)
    boxes = header_boxes(body)
    hbox, hdr = main_header(boxes)
    scale, top, bottom = depth_range(body)
    cs = curves(body, top, bottom)
    cols = columns(body)
    recs = text_records(body)
    ch_start, ch_lines, ch_pairs, ch_fields = custom_header(body, recs)
    anns = annotations(recs, top, bottom, cols, ch_start)
    try:
        lith = lithology(body, top, bottom, app, anns) if top is not None else None
    except Exception as ex:  # noqa: BLE001 -- lithology is extra; never lose the curves over it
        lith = {'error': '%s: %s' % (type(ex).__name__, ex)}
    try:
        acc = accessories(body, symbol_library(body), top, bottom) if top is not None else []
    except Exception as ex:  # noqa: BLE001
        acc = []
        lith = dict(lith or {}, accessories_error='%s: %s' % (type(ex).__name__, ex))
    header_source = 'template' if hdr else None
    if not hdr and ch_fields:
        hdr = {k: ch_fields.get(k, '') for k in HEADER_FIELDS}
        header_source = 'custom header page'
    if hdr:
        hdr = {k: v.replace('\r\n', '\n').replace('\r', '\n').strip() for k, v in hdr.items()}
        hdr['operator'] = ch_fields.get('operator', '') if header_source != 'template' else ''
        for bx in boxes:  # OPERATOR / GEOLOGIST boxes: [contact, company, address]
            t = bx['title'].upper()
            comp = next((f.strip() for f in bx['fields'][1:2] + bx['fields'][:1] if f.strip()), '')
            if 'OPERATOR' in t and not hdr['operator']:
                hdr['operator'] = comp
            if 'GEOLOG' in t and not hdr.get('geologist_company'):
                hdr['geologist_company'] = comp
    warnings = list(integrity)
    pictures = []
    if not hdr:
        pictures = bitmaps(body)
        warnings.append('no text header found' + ('; %d stored picture(s) saved as PNG (header is one of them)' % len(pictures) if pictures else ''))
    if top is None:
        warnings.append('depth range (scale record) not found')
    unreg = [c for c in cs if c['pad'] is None and c['nonnull']]
    if unreg:
        warnings.append('%d curve(s) with data do not fit the log depth range; left out of LAS/CSV' % len(unreg))
    return {
        'container': container, 'app': app, 'version': version, 'inflated_bytes': len(body),
        'header': hdr, 'header_source': header_source, 'boxes': [bx for bx in boxes if bx is not hbox],
        'custom_header': {'lines': ch_lines, 'fields': ch_pairs} if ch_lines else None,
        'scale': scale, 'top': top, 'bottom': bottom, 'axis_votes': axis_votes(anns),
        'curves': cs, 'columns': [c[1] for c in cols], 'annotations': anns, 'warnings': warnings,
        'pictures': pictures, 'lithology': lith, 'accessories': acc,
    }
