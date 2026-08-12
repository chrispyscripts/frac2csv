"""Per-well export builders shared by the desktop app.

Mirrors the web Lab's export exactly: every stage stacked into ONE file per
well, separated by the STAGE column (native MView-style). Charts that share a
stage label (a STEP surface+chemical pair, a BJ main+breaker pair) merge
side-by-side by sample index. Column order is Carmine's canonical four first,
then extras in first-seen order.

The .xlsx writer is a minimal OOXML build over the stdlib zipfile — no
openpyxl dependency in the frozen EXE. Layouts: MAIN + one tab per stage
(tabs=True) or a single MAIN sheet (tabs=False).
"""
import csv
import io
import re
import zipfile
from datetime import datetime, timedelta

import numpy as np

import aliases

CANON = ["Tr Press", "Slurry Rate", "WH Prop Conc", "BH Prop Conc"]


def stage_num(label):
    m = re.search(r"\d+", str(label))
    return int(m.group()) if m else 10 ** 9


def canon_series(result):
    """{name: values}, {name: unit} with vendor names mapped to canonical."""
    data, units, seen = {}, {}, set()
    for name, vals in result["data"].items():
        c = aliases.canon(name)
        key = c if c and c not in seen else name
        seen.add(key)
        data[key] = vals
        units[key] = result.get("units", {}).get(name, "") or \
            (aliases.canon_unit(c) if c else "")
    return data, units


def filename_uwi(name):
    """UWI from Carmine's file naming — charts on some templates (Liberty)
    carry no parseable UWI. Two forms exist on his drives:
    '<index>-<UWI>_<WA>_...' and '<UWI>-<WA>-...' (AB filings)."""
    s = str(name or "")
    m = (re.match(r"^\d+-([0-9A-Z]{10,20})_\d", s)
         or re.match(r"^([12]\d{2}[0-9A-Z]{9,13}W?\d{0,3})[-_]\d", s))
    return m.group(1) if m else ""


def build_well(series_results, fallback_uwi="", seq=False):
    """pipeline 'series' results (one well) -> {head, unit_row, blocks}.

    blocks = [{stage, rows}] with typed cells (str for UWI/STAGE/DATETIME/
    LABEL, float/None elsewhere) — one source for both CSV and XLSX.

    STAGE carries the sequential position (1, 2, 3...) and LABEL the chart's
    own printed name ("24A", "1 Attempt 2"). They used to hold the SAME value,
    picked by a setting, so a file could tell you the order or the printed
    name but never both. `seq` is kept for call compatibility and no longer
    changes the output.
    """
    canoned = [(r, *canon_series(r)) for r in series_results]

    # Carmine's spec (his 0422 seconds example): ALWAYS exactly the four
    # canonical channels with his unit strings — vendor extras never export
    cols = list(CANON)
    units_all = {"Tr Press": "MPa", "Slurry Rate": "m3/Min",
                 "WH Prop Conc": "Kg/m3", "BH Prop Conc": "Kg/m3"}

    order, groups = [], {}
    for item in canoned:
        key = item[0]["meta"].get("stage") or "?"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)
    order.sort(key=lambda k: (stage_num(k), str(k)))

    head = ["UWI", "STAGE", "DATETIME", "ELAPSED", "TIMESTAMP", "LABEL"] + cols
    unit_row = ["Units", "", "YYYY-mm-dd HH:MM:SS", "secs", "secs", ""] + \
               [units_all.get(c, "") for c in cols]
    blocks = []
    for bi, key in enumerate(order):
        seq_no = str(bi + 1)                  # position within the well
        # the chart's own printed name; templates that report none give "?",
        # which is no use in a deliverable — fall back to the position
        label = str(key) if str(key) not in ("", "?") else seq_no
        grp = groups[key]
        meta = grp[0][0]["meta"]
        try:
            t0 = datetime.strptime(
                f"{meta.get('date') or '2000-01-01'} "
                f"{meta.get('start_time') or '00:00:00'}",
                "%Y-%m-%d %H:%M:%S")
        except ValueError:
            t0 = datetime(2000, 1, 1)
        epoch0 = t0.timestamp()
        n = max(len(r["samples"]) for r, _, _ in grp)
        dsec = 1.0
        if len(grp[0][0]["samples"]) > 1:
            s = grp[0][0]["samples"]
            dsec = float(s[1] - s[0])
        chan = {}
        for _, data, _ in grp:
            for k, v in data.items():
                if k not in chan:
                    chan[k] = v
        uwi = meta.get("uwi") or fallback_uwi or ""
        rows = []
        for i in range(n):
            sec = i * dsec
            dt = (t0 + timedelta(seconds=sec)).strftime("%Y-%m-%d %H:%M:%S")
            row = [uwi, seq_no, dt, round(sec, 5), round(epoch0 + sec, 5), label]
            for c in cols:
                v = chan[c][i] if c in chan and i < len(chan[c]) else None
                row.append(None if v is None or
                           (isinstance(v, float) and not np.isfinite(v))
                           else float(v))
            rows.append(row)
        # pen-up separators, matching Carmine's reference exports: first and
        # last row of every stage block carry blank channel values so stage
        # plots never get connected by a stray line in FracPrep
        for edge in (0, -1):
            if rows:
                rows[edge] = rows[edge][:6] + [None] * len(cols)
        blocks.append({"stage": seq_no, "label": label, "rows": rows})
    return {"head": head, "unit_row": unit_row, "blocks": blocks}


def well_csv(model):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(model["head"])
    w.writerow(model["unit_row"])
    for b in model["blocks"]:
        for r in b["rows"]:
            w.writerow(["" if v is None else
                        (f"{v:.5f}" if isinstance(v, float) else v)
                        for v in r])
    return buf.getvalue()


# ---------- minimal OOXML (.xlsx) writer ----------

def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _col_letter(n):
    s = ""
    n += 1
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _sheet_xml(rows):
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<worksheet xmlns="http://schemas.openxmlformats.org/'
           'spreadsheetml/2006/main"><sheetData>']
    for ri, cells in enumerate(rows):
        parts = []
        for ci, v in enumerate(cells):
            if v is None or v == "":
                continue
            ref = _col_letter(ci) + str(ri + 1)
            if isinstance(v, (int, float)) and np.isfinite(v):
                parts.append(f'<c r="{ref}"><v>{v}</v></c>')
            else:
                parts.append(f'<c r="{ref}" t="inlineStr"><is>'
                             f'<t xml:space="preserve">{_esc(v)}</t></is></c>')
        out.append(f'<row r="{ri + 1}">{"".join(parts)}</row>')
    out.append("</sheetData></worksheet>")
    return "".join(out)


def _sheet_name(name, used):
    n = re.sub(r'[\\/?*\[\]:]', "-", str(name))[:31] or "Sheet"
    base = n
    i = 2
    while n.lower() in used:
        n = (base[:27] + "_" + str(i))[:31]
        i += 1
    used.add(n.lower())
    return n


def build_xlsx(sheets):
    """sheets = [(name, rows)] -> xlsx bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        ov = "".join(
            f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
            f'ContentType="application/vnd.openxmlformats-officedocument.'
            f'spreadsheetml.worksheet+xml"/>' for i in range(len(sheets)))
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/'
                   '2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.'
                   'openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType='
                   '"application/vnd.openxmlformats-officedocument.'
                   'spreadsheetml.sheet.main+xml"/>' + ov + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.'
                   'openxmlformats.org/officeDocument/2006/relationships/'
                   'officeDocument" Target="xl/workbook.xml"/></Relationships>')
        used = set()
        names = [_sheet_name(nm, used) for nm, _ in sheets]
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/'
                   'spreadsheetml/2006/main" xmlns:r="http://schemas.'
                   'openxmlformats.org/officeDocument/2006/relationships">'
                   '<sheets>' +
                   "".join(f'<sheet name="{_esc(nm)}" sheetId="{i + 1}" '
                           f'r:id="rId{i + 1}"/>'
                           for i, nm in enumerate(names)) +
                   "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/relationships">' +
                   "".join(f'<Relationship Id="rId{i + 1}" Type="http://'
                           f'schemas.openxmlformats.org/officeDocument/2006/'
                           f'relationships/worksheet" '
                           f'Target="worksheets/sheet{i + 1}.xml"/>'
                           for i in range(len(sheets))) +
                   "</Relationships>")
        for i, (_, rows) in enumerate(sheets):
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", _sheet_xml(rows))
    return buf.getvalue()


def well_xlsx(model, tabs=True):
    all_rows = [model["head"], model["unit_row"]]
    for b in model["blocks"]:
        all_rows.extend(b["rows"])
    sheets = [("MAIN", all_rows)]
    if tabs:
        for b in model["blocks"]:
            sheets.append(("Stage " + str(b["stage"]),
                           [model["head"], model["unit_row"]] + b["rows"]))
    return build_xlsx(sheets)


# ---------- TXT file-list manifests ----------

def parse_manifest(text):
    """Carmine's lists: 'UWI  K:\\BCER-Frac\\<folder>\\<file>.PDF' per line.
    -> [(uwi, path)] — header/blank rows skipped, spaces in filenames kept."""
    rows = []
    for line in text.splitlines():
        t = line.strip()
        if not t or re.search(r"\bFNAME\b", t, re.I):
            continue
        m = re.match(r"^(\S+)\s+(.+)$", t)
        if m and re.search(r"\.pdf\s*$", m.group(2), re.I):
            rows.append((m.group(1), m.group(2).strip()))
    return rows


def index_pdfs(root_dir):
    """{lowercased basename: full path} for every PDF under root_dir — the
    layout-proof fallback when manifest paths don't match the tree."""
    import os
    out = {}
    for dirpath, _dirs, files in os.walk(root_dir):
        for f in files:
            if f.lower().endswith(".pdf") and f.lower() not in out:
                out[f.lower()] = os.path.join(dirpath, f)
    return out


def resolve_manifest_path(path, txt_dir, index=None):
    """Find the actual file for a manifest path. The literal path works on
    the machine that owns the drive; otherwise resolve the tail segments
    against the TXT file's own folder, or (last) match by filename in a
    prebuilt index of the tree (any layout)."""
    import os
    if os.path.exists(path):
        return path
    segs = [s for s in re.split(r"[\\/]+", path) if s]
    if re.fullmatch(r"[A-Za-z]:", segs[0]):
        segs = segs[1:]
    # cut through the segment matching the txt folder's name
    base = os.path.basename(os.path.normpath(txt_dir))
    lower = [s.lower() for s in segs]
    if base.lower() in lower:
        segs = segs[lower.index(base.lower()) + 1:]
    for tail in (segs, segs[-2:], segs[-1:]):
        if not tail:
            continue
        cand = os.path.join(txt_dir, *tail)
        if os.path.exists(cand):
            return cand
    if index is not None:
        return index.get(segs[-1].lower())
    return None
